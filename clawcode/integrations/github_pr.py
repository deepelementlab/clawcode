"""GitHub pull request helpers (REST API + git remote)."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

GITHUB_API = "https://api.github.com"

_PR_URL = re.compile(
    r"github\.com[/:](?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<num>\d+)",
    re.IGNORECASE,
)


@dataclass
class RepoRef:
    owner: str
    repo: str


@dataclass
class PrRef:
    owner: str
    repo: str
    number: int


def github_auth_instructions() -> str:
    return (
        "**GitHub API not configured.**\n\n"
        "Set `GITHUB_TOKEN` (classic PAT with `repo` scope) or install the GitHub CLI "
        "(`gh`) and run `gh auth login`.\n\n"
        "Then use:\n"
        "  `/pr-comments <number>`\n"
        "  `/review <number>`\n"
        "from a git checkout whose `origin` points at github.com/owner/repo."
    )


def _strip_git_suffix(path: str) -> str:
    p = path.removesuffix(".git")
    return p.rstrip("/")


def parse_pr_number_from_tail(tail: str) -> int | None:
    t = (tail or "").strip()
    if not t:
        return None
    m = _PR_URL.search(t)
    if m:
        return int(m.group("num"))
    if t.isdigit():
        return int(t)
    return None


def parse_pr_ref(tail: str) -> PrRef | None:
    """Parse owner/repo/number from URL in tail, or number-only (needs remote)."""
    t = (tail or "").strip()
    if not t:
        return None
    m = _PR_URL.search(t)
    if m:
        return PrRef(
            owner=m.group("owner"),
            repo=_strip_git_suffix(m.group("repo")),
            number=int(m.group("num")),
        )
    if t.isdigit():
        return None  # caller combines with RepoRef from git
    return None


def parse_remote_url(remote_url: str) -> RepoRef | None:
    """Extract owner/repo from common GitHub remote URL forms."""
    u = (remote_url or "").strip()
    if not u:
        return None
    if u.startswith("git@"):
        # git@github.com:owner/repo.git
        if "github.com:" in u:
            path = u.split("github.com:", 1)[1]
            path = _strip_git_suffix(path)
            parts = path.split("/")
            if len(parts) >= 2:
                return RepoRef(owner=parts[0], repo=parts[1])
        return None
    if "github.com" in u:
        parsed = urlparse(u if "://" in u else "https://" + u)
        path = _strip_git_suffix(parsed.path or "")
        segments = [s for s in path.split("/") if s]
        if len(segments) >= 2 and segments[0] not in ("pull", "repos"):
            return RepoRef(owner=segments[0], repo=segments[1])
    return None


def resolve_repo_from_git(cwd: str) -> RepoRef | None:
    try:
        r = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    url = (r.stdout or "").strip()
    return parse_remote_url(url)


def get_github_token() -> str | None:
    return (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip() or None


def _gh_api_token() -> str | None:
    try:
        r = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    tok = (r.stdout or "").strip()
    return tok or None


def github_authorization_header() -> dict[str, str] | None:
    tok = get_github_token() or _gh_api_token()
    if not tok:
        return None
    return {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}


def resolve_pr_ref(tail: str, cwd: str) -> PrRef | None:
    """Full PR reference: URL in tail or number + origin remote."""
    direct = parse_pr_ref(tail)
    if direct:
        return direct
    num = parse_pr_number_from_tail(tail)
    if num is None:
        return None
    repo = resolve_repo_from_git(cwd)
    if repo is None:
        return None
    return PrRef(owner=repo.owner, repo=repo.repo, number=num)


async def _get_json(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> Any:
    r = await client.get(url, headers=headers)
    r.raise_for_status()
    return r.json()


def format_pr_comments_markdown(data: dict[str, Any]) -> str:
    """Human-readable summary from fetch_pr_comments payload."""
    pr = data.get("pull") or {}
    lines: list[str] = []
    title = pr.get("title") or ""
    lines.append(f"## PR #{pr.get('number', '')}: {title}")
    lines.append(f"State: {pr.get('state', '')}  |  {pr.get('html_url', '')}")
    body = (pr.get("body") or "").strip()
    if body:
        lines.append("\n### Description\n")
        lines.append(body[:8000] + ("…" if len(body) > 8000 else ""))

    issue_comments = data.get("issue_comments") or []
    if issue_comments:
        lines.append("\n### Issue comments\n")
        for c in issue_comments[:200]:
            user = (c.get("user") or {}).get("login", "?")
            lines.append(f"- **{user}**: {(c.get('body') or '').strip()[:2000]}")

    review_comments = data.get("review_comments") or []
    if review_comments:
        lines.append("\n### Review comments\n")
        for c in review_comments[:200]:
            user = (c.get("user") or {}).get("login", "?")
            path = c.get("path") or ""
            lines.append(f"- **{user}** `{path}`: {(c.get('body') or '').strip()[:1500]}")

    reviews = data.get("reviews") or []
    if reviews:
        lines.append("\n### Reviews\n")
        for rv in reviews[:100]:
            user = (rv.get("user") or {}).get("login", "?")
            state = rv.get("state", "")
            body_r = (rv.get("body") or "").strip()
            lines.append(f"- **{user}** [{state}]: {body_r[:1500]}")

    return "\n".join(lines) if lines else "(no data)"


async def fetch_pr_comments(pr: PrRef) -> dict[str, Any]:
    headers = github_authorization_header()
    if not headers:
        raise RuntimeError("no_github_auth")

    owner, repo, num = pr.owner, pr.repo, pr.number
    base = f"{GITHUB_API}/repos/{owner}/{repo}"
    from ..core.http_pool import get_shared_http_client

    client = await get_shared_http_client()
    pull = await _get_json(client, f"{base}/pulls/{num}", headers)
    issue_comments = await _get_json(client, f"{base}/issues/{num}/comments", headers)
    review_comments = await _get_json(client, f"{base}/pulls/{num}/comments", headers)
    reviews = await _get_json(client, f"{base}/pulls/{num}/reviews", headers)

    return {
        "pull": pull,
        "issue_comments": issue_comments if isinstance(issue_comments, list) else [],
        "review_comments": review_comments if isinstance(review_comments, list) else [],
        "reviews": reviews if isinstance(reviews, list) else [],
    }


async def fetch_pr_review_context(
    pr: PrRef,
    *,
    max_files: int = 40,
    patch_chars: int = 24_000,
) -> dict[str, Any]:
    """PR metadata + file list + truncated patches for LLM review."""
    headers = github_authorization_header()
    if not headers:
        raise RuntimeError("no_github_auth")

    owner, repo, num = pr.owner, pr.repo, pr.number
    base = f"{GITHUB_API}/repos/{owner}/{repo}"
    from ..core.http_pool import get_shared_http_client_with_timeout

    client = await get_shared_http_client_with_timeout(45.0)
    pull = await _get_json(client, f"{base}/pulls/{num}", headers)
    files = await _get_json(client, f"{base}/pulls/{num}/files?per_page=100", headers)

    file_list = files if isinstance(files, list) else []
    chunks: list[str] = []
    used = 0
    for f in file_list[:max_files]:
        name = f.get("filename", "")
        patch = f.get("patch") or ""
        status = f.get("status", "")
        header = f"### {name} ({status})\n"
        if used + len(header) > patch_chars:
            break
        chunks.append(header)
        used += len(header)
        room = patch_chars - used
        if patch and room > 200:
            piece = patch[:room] + ("…" if len(patch) > room else "")
            chunks.append("```diff\n" + piece + "\n```\n")
            used += len(chunks[-1])

    return {"pull": pull, "files_meta": file_list, "patch_excerpt": "\n".join(chunks)}


def run_git_diff(cwd: str, *, max_chars: int = 48_000) -> str:
    """Best-effort diff against main or master."""
    for base in ("main", "master", "origin/main", "origin/master"):
        try:
            r = subprocess.run(
                ["git", "merge-base", "HEAD", base],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if r.returncode != 0 or not (r.stdout or "").strip():
                continue
            merge_base = (r.stdout or "").strip()
            d = subprocess.run(
                ["git", "diff", merge_base, "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if d.returncode == 0 and (d.stdout or "").strip():
                out = d.stdout
                return out[:max_chars] + ("…\n(truncated)" if len(out) > max_chars else "")
        except (OSError, subprocess.SubprocessError):
            continue
    try:
        d = subprocess.run(
            ["git", "diff", "HEAD~50..HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if d.returncode == 0 and (d.stdout or "").strip():
            out = d.stdout
            return out[:max_chars] + ("…\n(truncated)" if len(out) > max_chars else "")
    except (OSError, subprocess.SubprocessError):
        pass
    return "(Could not compute git diff. Ensure this is a git repo with commits.)"
