"""UI style catalog loading and lightweight auto-selection helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_UI_HINT_RE = re.compile(
    r"(ui|界面|页面|组件|样式|css|tailwind|布局|主题|颜色|字体|design|frontend|前端)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class UiStyleEntry:
    slug: str
    title: str
    role: str
    path: str
    tags: list[str] = field(default_factory=list)
    fit_domains: list[str] = field(default_factory=list)
    fit_surfaces: list[str] = field(default_factory=list)
    avoid_surfaces: list[str] = field(default_factory=list)
    tone_keywords: list[str] = field(default_factory=list)
    compact_tokens: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UiStyleSelection:
    slug: str
    reason: str
    confidence: float
    top_candidates: list[str] = field(default_factory=list)
    #: Human-readable scoring rubric (for `/ui-style why` and notifications).
    rubric: str = ""
    #: "slug=raw, slug=raw, ..." for top-N candidates by raw score.
    top_scores_preview: str = ""


@dataclass(slots=True)
class UiStyleEvalResult:
    slug: str
    color_consistency: float
    component_semantics: float
    tone_consistency: float
    token_hit_rate: float
    token_hits: int
    token_total: int
    anti_pattern_penalty: float = 0.0
    selection_risk: float = 0.0
    next_best_slug: str = ""
    repair_actions: list[str] = field(default_factory=list)
    matched_anti_patterns: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UiAntiPatternRule:
    pattern: str
    severity: str = "medium"
    domains: list[str] = field(default_factory=list)
    surfaces: list[str] = field(default_factory=list)
    conflicts_with_tags: list[str] = field(default_factory=list)
    rewrite_hint: str = ""


_AUTO_PICK_MIN_CONFIDENCE = 0.0

_AUTO_PICK_TOP_N = 10


def is_ui_intent(text: str) -> bool:
    return bool(_UI_HINT_RE.search(text or ""))


def ui_style_auto_pick_rubric_text() -> str:
    """Explain auto-pick dimensions (shown in `/ui-style why` and tooling)."""
    return (
        "【自动选型标准】对每条风格，把用户请求里命中的信号按权重累加，取总分最高者为默认样式。\n"
        "加分：style 的 tag 在文中 +1.2；fit_domain +1.4；fit_surface +1.6；tone_keyword +1.0；"
        "slug / title / role 子串命中各 +0.8；scene_tags 与 style.tags 交集 +1.1/词，"
        "与 fit_surfaces 交集 +0.7/词；settings 默认 ui 偏好 slug +0.5。\n"
        "减分：avoid_surface 关键词在文中每命中一次 -1.5。\n"
        "【confidence】由原始总分映射到 0–1，仅作参考；发送消息时始终采用总分最高的风格（不再因低 confidence 拦截）。"
    )


def ui_style_auto_pick_top_n() -> int:
    return _AUTO_PICK_TOP_N


def derive_scene_tags(request: str) -> list[str]:
    """Infer lightweight scene tags from user request text."""
    t = (request or "").lower()
    out: set[str] = set()
    pairs = [
        ("prototype", "prototype"),
        ("wireframe", "prototype"),
        ("usability", "usability"),
        ("a11y", "accessibility"),
        ("accessibility", "accessibility"),
        ("responsive", "responsive"),
        ("mobile", "responsive"),
        ("performance", "performance"),
        ("latency", "performance"),
        ("component", "component_architecture"),
        ("state", "stateful_ui"),
        ("dashboard", "stateful_ui"),
        ("design system", "design_system"),
    ]
    for kw, tag in pairs:
        if kw in t:
            out.add(tag)
    return sorted(out)


def _candidate_claw_roots(workspace_root: str | Path) -> list[Path]:
    """Return candidate roots that may contain `.claw/` metadata.

    Walks up from *workspace_root* so layouts like ``repo/test`` still find
    ``repo/clawcode/.claw/...`` when metadata lives next to a sibling folder.
    """
    root = Path(workspace_root).expanduser().resolve()
    out: list[Path] = []
    seen: set[str] = set()
    cur: Path | None = root
    depth = 0
    max_depth = 12
    while cur is not None and depth < max_depth:
        for row in (cur, cur / "clawcode"):
            key = str(row)
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
        depth += 1
    return out


def _ui_style_workspace_bases(
    workspace_root: str | Path,
    *,
    cli_launch_directory: str | Path | None = None,
) -> list[Path]:
    """Bases to search: ``-c`` target first, then CLI host cwd (when different)."""
    out: list[Path] = []
    seen: set[str] = set()
    for raw in (workspace_root, cli_launch_directory):
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue
        p = Path(s).expanduser().resolve()
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def ui_catalog_candidate_paths(
    workspace_root: str | Path,
    *,
    cli_launch_directory: str | Path | None = None,
) -> list[Path]:
    out: list[Path] = []
    seen_file: set[str] = set()
    for base in _ui_style_workspace_bases(workspace_root, cli_launch_directory=cli_launch_directory):
        for root in _candidate_claw_roots(base):
            cand = root / ".claw" / "design" / "UI" / "catalog.json"
            fk = str(cand)
            if fk in seen_file:
                continue
            seen_file.add(fk)
            out.append(cand)
    return out


def _ui_root_candidates(
    workspace_root: str | Path,
    *,
    cli_launch_directory: str | Path | None = None,
) -> list[Path]:
    out: list[Path] = []
    seen_dir: set[str] = set()
    for base in _ui_style_workspace_bases(workspace_root, cli_launch_directory=cli_launch_directory):
        for root in _candidate_claw_roots(base):
            d = root / ".claw" / "design" / "UI"
            dk = str(d)
            if dk in seen_dir:
                continue
            seen_dir.add(dk)
            out.append(d)
    return out


def ui_catalog_candidate_hints(
    workspace_root: str | Path,
    *,
    cli_launch_directory: str | Path | None = None,
) -> list[str]:
    ws = Path(workspace_root).expanduser().resolve()
    launch: Path | None = None
    lc = str(cli_launch_directory or "").strip()
    if lc:
        launch = Path(lc).expanduser().resolve()
    out: list[str] = []
    seen_label: set[str] = set()
    for p in ui_catalog_candidate_paths(ws, cli_launch_directory=launch):
        label: str | None = None
        try:
            rel = p.relative_to(ws).as_posix()
            label = rel if rel.startswith(".") else f"./{rel}"
        except Exception:
            pass
        if label is None and launch is not None:
            try:
                rel2 = p.relative_to(launch).as_posix()
                label = rel2 if rel2.startswith(".") else f"./{rel2}"
            except Exception:
                pass
        if label is None:
            label = str(p)
        if label in seen_label:
            continue
        seen_label.add(label)
        out.append(label)
    return out


def _read_anti_pattern_payload(
    workspace_root: str | Path,
    *,
    cli_launch_directory: str | Path | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for ui_root in _ui_root_candidates(workspace_root, cli_launch_directory=cli_launch_directory):
        p = ui_root / "anti_patterns.json"
        if not p.is_file():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(raw, dict):
            payload = raw
            break
    return payload


def _normalize_anti_rule(raw: Any) -> UiAntiPatternRule | None:
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        return UiAntiPatternRule(pattern=s)
    if not isinstance(raw, dict):
        return None
    pat = str(raw.get("pattern", "")).strip()
    if not pat:
        return None
    sev = str(raw.get("severity", "medium")).strip().lower() or "medium"
    if sev not in {"low", "medium", "high"}:
        sev = "medium"
    to_list = lambda x: [str(v).strip() for v in x if str(v).strip()] if isinstance(x, list) else []
    return UiAntiPatternRule(
        pattern=pat,
        severity=sev,
        domains=to_list(raw.get("domains")),
        surfaces=to_list(raw.get("surfaces")),
        conflicts_with_tags=to_list(raw.get("conflicts_with_tags")),
        rewrite_hint=str(raw.get("rewrite_hint", "")).strip(),
    )


def load_ui_anti_pattern_rules(
    workspace_root: str | Path,
    *,
    slug: str = "",
    cli_launch_directory: str | Path | None = None,
) -> list[UiAntiPatternRule]:
    """Load anti-pattern rules; supports both legacy string list and object schema."""
    payload = _read_anti_pattern_payload(
        workspace_root, cli_launch_directory=cli_launch_directory
    )
    if not payload:
        return []
    out: list[UiAntiPatternRule] = []
    g = payload.get("global", [])
    if isinstance(g, list):
        for x in g:
            r = _normalize_anti_rule(x)
            if r is not None:
                out.append(r)
    by_style = payload.get("by_style", {})
    if slug and isinstance(by_style, dict):
        rows = by_style.get(slug, [])
        if isinstance(rows, list):
            for x in rows:
                r = _normalize_anti_rule(x)
                if r is not None:
                    out.append(r)
    # unique + stable
    seen: set[str] = set()
    dedup: list[UiAntiPatternRule] = []
    for x in out:
        key = x.pattern
        if key in seen:
            continue
        seen.add(key)
        dedup.append(x)
    return dedup


def load_ui_anti_patterns(
    workspace_root: str | Path,
    *,
    slug: str = "",
    cli_launch_directory: str | Path | None = None,
) -> list[str]:
    """Backward-compatible flat anti-pattern list."""
    return [
        r.pattern
        for r in load_ui_anti_pattern_rules(
            workspace_root, slug=slug, cli_launch_directory=cli_launch_directory
        )
    ]


def load_agent_scene_tags(
    workspace_root: str | Path,
    *,
    cli_launch_directory: str | Path | None = None,
) -> list[str]:
    """Read `.claw/agents` docs and expose coarse scene tags for routing."""
    corpus: list[str] = []
    for base in _ui_style_workspace_bases(workspace_root, cli_launch_directory=cli_launch_directory):
        for root in _candidate_claw_roots(base):
            files = [
                root / ".claw" / "agents" / "clawteam-ui-ux-designer.md",
                root / ".claw" / "agents" / "clawteam-rnd-frontend.md",
            ]
            for path in files:
                try:
                    if path.is_file():
                        corpus.append(path.read_text(encoding="utf-8").lower())
                except Exception:
                    continue
    text = "\n".join(corpus)
    if not text:
        return []
    checks = [
        ("prototype", "prototype"),
        ("usability", "usability"),
        ("design system", "design_system"),
        ("accessibility", "accessibility"),
        ("responsive", "responsive"),
        ("performance", "performance"),
        ("component", "component_architecture"),
        ("state", "stateful_ui"),
    ]
    out: set[str] = set()
    for needle, tag in checks:
        if needle in text:
            out.add(tag)
    return sorted(out)


def _to_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def load_ui_catalog(
    workspace_root: str | Path,
    *,
    cli_launch_directory: str | Path | None = None,
) -> list[UiStyleEntry]:
    catalog_path = next(
        (
            p
            for p in ui_catalog_candidate_paths(
                workspace_root, cli_launch_directory=cli_launch_directory
            )
            if p.is_file()
        ),
        None,
    )
    if catalog_path is None:
        return []
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = payload.get("styles", []) if isinstance(payload, dict) else []
    out: list[UiStyleEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug", "")).strip()
        if not slug:
            continue
        out.append(
            UiStyleEntry(
                slug=slug,
                title=str(row.get("title", slug)).strip() or slug,
                role=str(row.get("role", "")).strip(),
                path=str(row.get("path", "")).strip(),
                tags=_to_list(row.get("tags")),
                fit_domains=_to_list(row.get("fit_domains")),
                fit_surfaces=_to_list(row.get("fit_surfaces")),
                avoid_surfaces=_to_list(row.get("avoid_surfaces")),
                tone_keywords=_to_list(row.get("tone_keywords")),
                compact_tokens=row.get("compact_tokens", {}) if isinstance(row.get("compact_tokens"), dict) else {},
            )
        )
    return out


def select_ui_style_auto(
    request: str,
    styles: list[UiStyleEntry],
    *,
    scene_tags: list[str] | None = None,
    preferred_slug: str = "",
) -> UiStyleSelection | None:
    text = (request or "").lower()
    if not styles:
        return None
    scene = {x.strip().lower() for x in (scene_tags or []) if x.strip()}
    preferred = preferred_slug.strip().lower()
    scored: list[tuple[float, UiStyleEntry, list[str]]] = []
    for st in styles:
        score = 0.0
        hits: list[str] = []
        for kw in [x.lower() for x in st.tags]:
            if kw and kw in text:
                score += 1.2
                hits.append(f"tag:{kw}")
        for kw in [x.lower() for x in st.fit_domains]:
            if kw and kw in text:
                score += 1.4
                hits.append(f"domain:{kw}")
        for kw in [x.lower() for x in st.fit_surfaces]:
            if kw and kw in text:
                score += 1.6
                hits.append(f"surface:{kw}")
        for kw in [x.lower() for x in st.tone_keywords]:
            if kw and kw in text:
                score += 1.0
                hits.append(f"tone:{kw}")
        for kw, label in (
            (st.slug.lower(), "slug"),
            (st.title.lower(), "title"),
            (st.role.lower(), "role"),
        ):
            if kw and kw in text:
                score += 0.8
                hits.append(f"{label}:{kw}")
        for kw in [x.lower() for x in st.avoid_surfaces]:
            if kw and kw in text:
                score -= 1.5
                hits.append(f"avoid:{kw}")
        if scene:
            inter_tags = scene.intersection({x.lower() for x in st.tags})
            if inter_tags:
                score += 1.1 * len(inter_tags)
                hits.extend(f"scene_tag:{x}" for x in sorted(inter_tags))
            inter_surfaces = scene.intersection({x.lower() for x in st.fit_surfaces})
            if inter_surfaces:
                score += 0.7 * len(inter_surfaces)
                hits.extend(f"scene_surface:{x}" for x in sorted(inter_surfaces))
        if preferred and st.slug.lower() == preferred:
            score += 0.5
            hits.append("preferred")
        scored.append((score, st, hits))
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best, best_hits = scored[0]
    top = [row[1].slug for row in scored[:_AUTO_PICK_TOP_N]]
    # Relaxed mapping so displayed confidence is less harsh for weak matches.
    confidence = max(0.0, min(1.0, round((best_score + 3.0) / 12.0, 3)))
    reason_hits = ", ".join(best_hits[:8]) if best_hits else "fallback (no keyword hits; first catalog order)"
    reason = f"选中 `{best.slug}`：原始分 {best_score:.2f}；命中信号: {reason_hits}"
    preview = "; ".join(f"{row[1].slug}={row[0]:.2f}" for row in scored[:_AUTO_PICK_TOP_N])
    return UiStyleSelection(
        slug=best.slug,
        reason=reason,
        confidence=confidence,
        top_candidates=top,
        rubric=ui_style_auto_pick_rubric_text(),
        top_scores_preview=preview,
    )


def ui_style_auto_pick_min_confidence() -> float:
    """Legacy threshold (currently 0). TUI no longer blocks sends on low confidence."""
    return _AUTO_PICK_MIN_CONFIDENCE


def choose_secondary_ui_style_candidate(
    request: str,
    styles: list[UiStyleEntry],
    *,
    top_candidates: list[str],
) -> tuple[str, str] | None:
    """Pick a safer secondary candidate when confidence is near threshold."""
    if len(top_candidates) < 2:
        return None
    text = (request or "").lower()
    rows: list[tuple[int, str]] = []
    for slug in top_candidates[1 : min(10, len(top_candidates))]:
        st = next((x for x in styles if x.slug == slug), None)
        if st is None:
            continue
        surface_hits = sum(1 for x in st.fit_surfaces if x and x.lower() in text)
        domain_hits = sum(1 for x in st.fit_domains if x and x.lower() in text)
        avoid_hits = sum(1 for x in st.avoid_surfaces if x and x.lower() in text)
        score = (surface_hits * 3) + (domain_hits * 2) - (avoid_hits * 2)
        rows.append((score, slug))
    if not rows:
        return None
    rows.sort(key=lambda x: x[0], reverse=True)
    if rows[0][0] <= 0:
        return None
    return rows[0][1], f"secondary-candidate domain/surface score={rows[0][0]}"


def format_ui_style_compact(entry: UiStyleEntry) -> str:
    lines = [f"# UI Style: {entry.slug}", ""]
    if entry.role:
        lines.append(f"- role: {entry.role}")
    if entry.tags:
        lines.append(f"- tags: {', '.join(entry.tags)}")
    if entry.fit_domains:
        lines.append(f"- fit_domains: {', '.join(entry.fit_domains)}")
    if entry.fit_surfaces:
        lines.append(f"- fit_surfaces: {', '.join(entry.fit_surfaces)}")
    if entry.avoid_surfaces:
        lines.append(f"- avoid_surfaces: {', '.join(entry.avoid_surfaces)}")
    if entry.tone_keywords:
        lines.append(f"- tone_keywords: {', '.join(entry.tone_keywords)}")
    ct = entry.compact_tokens or {}
    if ct:
        lines.append("")
        lines.append("## Compact tokens")
        for k in ("primary_color", "background", "text", "radius", "shadow", "font_family"):
            v = ct.get(k)
            if v:
                lines.append(f"- {k}: {v}")
    return "\n".join(lines).strip() + "\n"


def style_prompt_prefix(entry: UiStyleEntry) -> str:
    ct = entry.compact_tokens or {}
    primary = str(ct.get("primary_color", "")).strip()
    bg = str(ct.get("background", "")).strip()
    text = str(ct.get("text", "")).strip()
    font = str(ct.get("font_family", "")).strip()
    radius = str(ct.get("radius", "")).strip()
    shadow = str(ct.get("shadow", "")).strip()
    lines = [
        "UI STYLE CONTEXT (must apply before coding):",
        f"- style_slug: {entry.slug}",
    ]
    if entry.tags:
        lines.append(f"- style_tags: {', '.join(entry.tags)}")
    if primary or bg or text:
        lines.append("## colors")
        lines.append(
            f"- core_colors: primary={primary or 'n/a'}, background={bg or 'n/a'}, text={text or 'n/a'}"
        )
    if font:
        lines.append("## typography")
        lines.append(f"- font_family: {font}")
    if entry.fit_surfaces or entry.fit_domains:
        lines.append("## components")
        if entry.fit_surfaces:
            lines.append(f"- fit_surfaces: {', '.join(entry.fit_surfaces[:6])}")
        if entry.fit_domains:
            lines.append(f"- fit_domains: {', '.join(entry.fit_domains[:6])}")
    if radius or shadow:
        lines.append("## interaction")
        lines.append(f"- shape_depth: radius={radius or 'n/a'}, shadow={shadow or 'n/a'}")
    if entry.avoid_surfaces:
        lines.append(f"- avoid_patterns: {', '.join(entry.avoid_surfaces[:6])}")
    if entry.tone_keywords:
        lines.append(f"- tone_keywords: {', '.join(entry.tone_keywords[:6])}")
    lines.append("- follow the selected style's DESIGN.md conventions for typography/components/responsive rules.")
    return "\n".join(lines) + "\n\n"


def ui_critic_checklist(
    entry: UiStyleEntry,
    *,
    anti_patterns: list[str] | None = None,
    anti_rules: list[UiAntiPatternRule] | None = None,
) -> str:
    anti = [x.strip() for x in (anti_patterns or []) if x.strip()]
    if anti_rules:
        for r in anti_rules:
            if r.pattern not in anti:
                anti.append(r.pattern)
    lines = [
        "UI CRITIC CHECKLIST (self-review before final answer):",
        f"- preserve brand semantics for `{entry.slug}` components and layout rhythm",
        "- verify heading/subheading/button copy tone matches style keywords",
        "- verify accessibility basics: semantic landmarks, focus visibility, contrast",
        "- verify responsive behavior for mobile and desktop breakpoints",
    ]
    if anti:
        lines.append("- avoid known anti-patterns:")
        for item in anti[:8]:
            lines.append(f"  - {item}")
    return "\n".join(lines) + "\n\n"


def _contains_any(haystack: str, words: list[str]) -> int:
    t = (haystack or "").lower()
    hit = 0
    for w in words:
        if w and w.lower() in t:
            hit += 1
    return hit


def evaluate_ui_style_text(
    text: str,
    entry: UiStyleEntry,
    *,
    anti_patterns: list[str] | None = None,
    anti_rules: list[UiAntiPatternRule] | None = None,
    next_best_slug: str = "",
) -> UiStyleEvalResult:
    raw_body = (text or "").lower()
    # Ignore the injected "UI CRITIC CHECKLIST" block itself during scoring.
    body_lines: list[str] = []
    in_critic = False
    for ln in raw_body.splitlines():
        if "ui critic checklist" in ln:
            in_critic = True
            continue
        if in_critic:
            if not ln.strip():
                in_critic = False
            continue
        body_lines.append(ln)
    body = "\n".join(body_lines)
    notes: list[str] = []
    ct = entry.compact_tokens or {}
    token_keys = ("primary_color", "background", "text", "radius", "shadow", "font_family")
    token_total = 0
    token_hits = 0
    for k in token_keys:
        v = str(ct.get(k, "")).strip()
        if not v:
            continue
        token_total += 1
        if v.lower() in body:
            token_hits += 1
    token_hit_rate = (token_hits / token_total) if token_total else 0.0
    color_consistency = token_hit_rate

    comp_words = [*entry.fit_surfaces, *entry.fit_domains, *entry.tags]
    comp_total = max(1, len([x for x in comp_words if str(x).strip()]))
    comp_hit = _contains_any(body, [str(x) for x in comp_words])
    component_semantics = min(1.0, comp_hit / comp_total)

    tone_total = max(1, len([x for x in entry.tone_keywords if str(x).strip()]))
    tone_hit = _contains_any(body, [str(x) for x in entry.tone_keywords])
    tone_consistency = min(1.0, tone_hit / tone_total)

    # anti-pattern penalty / risk
    severity_weight = {"low": 0.15, "medium": 0.3, "high": 0.5}
    merged_rules: dict[str, UiAntiPatternRule] = {}
    if anti_rules:
        for r in anti_rules:
            merged_rules[r.pattern] = r
    for p in [x.strip() for x in (anti_patterns or []) if x.strip()]:
        merged_rules.setdefault(p, UiAntiPatternRule(pattern=p))
    matched_anti: list[str] = []
    anti_penalty = 0.0
    repair_actions: list[str] = []
    for rule in merged_rules.values():
        if rule.pattern.lower() not in body:
            continue
        matched_anti.append(rule.pattern)
        anti_penalty += severity_weight.get(rule.severity, 0.3)
        if rule.rewrite_hint:
            repair_actions.append(f"rewrite: {rule.rewrite_hint}")
        else:
            repair_actions.append(f"remove anti-pattern: {rule.pattern}")
    anti_penalty = min(1.0, round(anti_penalty, 3))
    if matched_anti:
        notes.append("matched anti-patterns found; consider revising layout/copy/style details")
    if token_hit_rate < 0.35:
        notes.append("token hit rate is low; inject more explicit color/radius/shadow/font usage")
        repair_actions.append("inject compact tokens explicitly in colors/radius/shadow/font sections")
    if component_semantics < 0.35:
        repair_actions.append("align component hierarchy to fit_surfaces and fit_domains")
    if tone_consistency < 0.35:
        repair_actions.append("rewrite heading/cta copy to match tone_keywords")
    selection_risk = round(
        min(1.0, (1.0 - token_hit_rate) * 0.45 + (1.0 - component_semantics) * 0.35 + anti_penalty * 0.2),
        3,
    )
    # stable + dedup actions
    seen_actions: set[str] = set()
    dedup_actions: list[str] = []
    for x in repair_actions:
        if x in seen_actions:
            continue
        seen_actions.add(x)
        dedup_actions.append(x)

    return UiStyleEvalResult(
        slug=entry.slug,
        color_consistency=round(color_consistency, 3),
        component_semantics=round(component_semantics, 3),
        tone_consistency=round(tone_consistency, 3),
        token_hit_rate=round(token_hit_rate, 3),
        token_hits=token_hits,
        token_total=token_total,
        anti_pattern_penalty=anti_penalty,
        selection_risk=selection_risk,
        next_best_slug=next_best_slug,
        repair_actions=dedup_actions[:8],
        matched_anti_patterns=matched_anti,
        notes=notes,
    )
