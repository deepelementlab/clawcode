"""UI style catalog loading and auto-selection with TF-IDF + synonym expansion."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_UI_HINT_RE = re.compile(
    r"(ui|ux|界面|页面|主页|仪表盘|组件|样式|css|html|tailwind|布局|主题|颜色|字体|图标|按钮|表单|弹窗|导航|交互|design|frontend|前端)",
    re.IGNORECASE,
)

_WORD_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)

_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


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
    rubric: str = ""
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

_DIMENSION_WEIGHTS: dict[str, float] = {
    "fit_surfaces": 2.0,
    "fit_domains": 1.6,
    "tags": 1.2,
    "tone_keywords": 0.8,
    "identity": 0.4,
}

_SYNONYM_GROUPS: list[set[str]] = [
    {"dashboard", "admin_panel", "control_panel", "管理后台", "管理面板", "后台管理"},
    {"landing_page", "product_landing", "landing", "落地页", "首页", "主页"},
    {"ecommerce", "shopping", "商城", "电商", "shop", "store", "商店", "店铺"},
    {"developer_tooling", "devtools", "开发工具", "工具", "developer"},
    {"minimal", "minimalist", "简洁", "极简", "clean", "简单"},
    {"premium", "luxury", "高端", "高级", "精致"},
    {"social", "社交", "community", "社区", "论坛", "forum"},
    {"fintech", "金融", "finance", "banking", "银行", "支付"},
    {"docs", "documentation", "文档", "文档站", "知识库", "knowledge"},
    {"blog", "content", "博客", "内容", "文章", "article"},
    {"crm", "客户管理", "客户关系"},
    {"saas", "b2b_saas", "b2b", "企业服务"},
    {"portfolio", "作品集", "展示", "showcase", "gallery"},
    {"marketing", "营销", "品牌", "branding", "品牌营销"},
    {"analytics", "分析", "数据看板", "统计", "statistics"},
    {"mobile", "移动端", "手机", "app", "响应式", "responsive"},
    {"dark_mode", "暗色", "夜间", "dark theme", "深色"},
    {"accessibility", "a11y", "无障碍", "可访问性"},
    {"prototype", "wireframe", "原型", "线框图", "mockup"},
    {"game", "游戏", "gamification", "游戏化"},
    {"education", "教育", "学习", "learning", "course", "课程"},
    {"healthcare", "医疗", "健康", "health", "医疗健康"},
    {"video", "视频", "streaming", "直播", "live"},
    {"music", "音乐", "audio", "音频", "播客", "podcast"},
    {"chat", "聊天", "messenger", "即时通讯", "im"},
    {"email", "邮件", "mail", "邮箱"},
    {"calendar", "日程", "scheduling", "预约", "booking"},
    {"map", "地图", "地图导航", "navigation"},
    {"weather", "天气", "forecast"},
    {"travel", "旅行", "旅游", "出行", "trip"},
]

_BRAND_SLUG_MAP: dict[str, str] = {
    "apple": "apple", "苹果": "apple",
    "airbnb": "airbnb", "爱彼迎": "airbnb",
    "airtable": "airtable",
    "bmw": "bmw", "宝马": "bmw",
    "cal.com": "cal", "cal": "cal", "calcom": "cal",
    "claude": "claude", "anthropic": "claude",
    "clay": "clay",
    "clickhouse": "clickhouse",
    "cohere": "cohere",
    "coinbase": "coinbase",
    "composio": "composio",
    "cursor": "cursor",
    "elevenlabs": "elevenlabs", "eleven labs": "elevenlabs",
    "expo": "expo",
    "figma": "figma",
    "framer": "framer",
    "hashicorp": "hashicorp",
    "ibm": "ibm",
    "intercom": "intercom",
    "kraken": "kraken",
    "linear": "linear.app", "linear.app": "linear.app",
    "lovable": "lovable",
    "minimax": "minimax",
    "mintlify": "mintlify",
    "miro": "miro",
    "mistral": "mistral.ai", "mistral.ai": "mistral.ai",
    "mongodb": "mongodb", "mongo": "mongodb",
    "notion": "notion",
    "nvidia": "nvidia",
    "ollama": "ollama",
    "opencode": "opencode.ai", "opencode.ai": "opencode.ai",
    "pinterest": "pinterest",
    "posthog": "posthog",
    "raycast": "raycast",
    "replicate": "replicate",
    "resend": "resend",
    "revolut": "revolut",
    "runway": "runwayml", "runwayml": "runwayml",
    "sanity": "sanity",
    "sentry": "sentry",
    "spacex": "spacex",
    "spotify": "spotify",
    "stripe": "stripe",
    "supabase": "supabase",
    "superhuman": "superhuman",
    "together.ai": "together.ai", "together": "together.ai",
    "uber": "uber",
    "vercel": "vercel",
    "voltagent": "voltagent",
    "warp": "warp",
    "webflow": "webflow",
    "wise": "wise",
    "x.ai": "x.ai", "xai": "x.ai", "grok": "x.ai",
    "zapier": "zapier",
}

_SYNONYM_INDEX: dict[str, set[str]] = {}


def _build_synonym_index() -> None:
    if _SYNONYM_INDEX:
        return
    for group in _SYNONYM_GROUPS:
        normalized = {w.lower() for w in group}
        for w in normalized:
            existing = _SYNONYM_INDEX.get(w)
            if existing is None:
                _SYNONYM_INDEX[w] = normalized.copy()
            else:
                existing.update(normalized)
                _SYNONYM_INDEX[w] = existing


def is_ui_intent(text: str) -> bool:
    return bool(_UI_HINT_RE.search(text or ""))


def ui_style_auto_pick_rubric_text() -> str:
    return (
        "【自动选型标准 v2】TF-IDF 归一化 + 同义词扩展 + 词边界匹配。\n"
        "维度权重：fit_surfaces=2.0, fit_domains=1.6, tags=1.2, tone_keywords=0.8, identity=0.4。\n"
        "加分：关键词经同义词扩展后在请求中匹配，乘以维度权重和 IDF 系数。\n"
        "减分：avoid_surface 关键词命中 -2.5/词，不可被正向分数抵消。\n"
        "直通：用户请求中明确提到品牌名时直接锁定对应 style。\n"
        "【confidence】= 0.6×绝对质量 + 0.4×区分度（best 与 second 差距）。\n"
        "始终采用总分最高的风格（不再因低 confidence 拦截）。"
    )


def ui_style_auto_pick_top_n() -> int:
    return _AUTO_PICK_TOP_N


def tokenize(text: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_RE.finditer(text or "")}


def _extract_cjk_ngrams(text: str) -> set[str]:
    chars = [c for c in text if "\u4e00" <= c <= "\u9fff"]
    if not chars:
        return set()
    ngrams: set[str] = set()
    for c in chars:
        ngrams.add(c)
    for i in range(len(chars) - 1):
        ngrams.add(chars[i] + chars[i + 1])
    for i in range(len(chars) - 2):
        ngrams.add(chars[i] + chars[i + 1] + chars[i + 2])
    for i in range(len(chars) - 3):
        ngrams.add(chars[i] + chars[i + 1] + chars[i + 2] + chars[i + 3])
    return ngrams


def _cjk_expand(text: str) -> set[str]:
    _build_synonym_index()
    ngrams = _extract_cjk_ngrams(text)
    expanded: set[str] = set()
    for ng in ngrams:
        syns = _SYNONYM_INDEX.get(ng)
        if syns:
            expanded.update(syns)
    expanded_lower = {x.lower() for x in expanded}
    return expanded_lower


def _keyword_tokens(keyword: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_RE.finditer(keyword or "")}


def _token_match_overlap(query_tokens: set[str], keyword: str) -> bool:
    kw_tokens = _keyword_tokens(keyword)
    if not kw_tokens:
        return False
    return bool(query_tokens & kw_tokens)


def _expand_with_synonyms(tokens: set[str]) -> set[str]:
    _build_synonym_index()
    expanded: set[str] = set(tokens)
    for t in tokens:
        syns = _SYNONYM_INDEX.get(t)
        if syns:
            expanded.update(syns)
    return expanded


def derive_scene_tags(request: str) -> list[str]:
    t = (request or "").lower()
    tokens = tokenize(t)
    expanded = _expand_with_synonyms(tokens)
    out: set[str] = set()
    pairs = [
        ("prototype", "prototype"),
        ("wireframe", "prototype"),
        ("原型", "prototype"),
        ("usability", "usability"),
        ("可用性", "usability"),
        ("a11y", "accessibility"),
        ("accessibility", "accessibility"),
        ("无障碍", "accessibility"),
        ("responsive", "responsive"),
        ("mobile", "responsive"),
        ("移动端", "responsive"),
        ("响应式", "responsive"),
        ("performance", "performance"),
        ("latency", "performance"),
        ("性能", "performance"),
        ("component", "component_architecture"),
        ("组件", "component_architecture"),
        ("state", "stateful_ui"),
        ("dashboard", "stateful_ui"),
        ("管理后台", "stateful_ui"),
        ("design system", "design_system"),
        ("设计系统", "design_system"),
        ("saas", "b2b_saas"),
        ("b2b", "b2b_saas"),
        ("企业", "b2b_saas"),
        ("ecommerce", "ecommerce"),
        ("电商", "ecommerce"),
        ("商城", "ecommerce"),
        ("social", "social_media"),
        ("社交", "social_media"),
        ("fintech", "fintech"),
        ("金融", "fintech"),
        ("payments", "payments"),
        ("支付", "payments"),
        ("docs", "documentation"),
        ("文档", "documentation"),
        ("blog", "content_publishing"),
        ("博客", "content_publishing"),
        ("marketing", "marketing"),
        ("营销", "marketing"),
        ("品牌", "marketing"),
        ("analytics", "analytics"),
        ("分析", "analytics"),
        ("数据", "analytics"),
        ("game", "gaming"),
        ("游戏", "gaming"),
        ("education", "education"),
        ("教育", "education"),
        ("学习", "education"),
        ("healthcare", "healthcare"),
        ("医疗", "healthcare"),
        ("video", "video_streaming"),
        ("视频", "video_streaming"),
        ("music", "audio"),
        ("音乐", "audio"),
        ("chat", "messaging"),
        ("聊天", "messaging"),
        ("email", "email"),
        ("邮件", "email"),
        ("calendar", "scheduling"),
        ("日程", "scheduling"),
        ("travel", "travel"),
        ("旅行", "travel"),
        ("旅游", "travel"),
        ("portfolio", "portfolio"),
        ("作品集", "portfolio"),
        ("crm", "crm"),
        ("客户管理", "crm"),
    ]
    for kw, tag in pairs:
        if kw in t or kw in expanded:
            out.add(tag)
    return sorted(out)


def _candidate_claw_roots(workspace_root: str | Path) -> list[Path]:
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
    corpus: list[str] = []
    for base in _ui_style_workspace_bases(workspace_root, cli_launch_directory=cli_launch_directory):
        for root in _candidate_claw_roots(base):
            files = [
                root / ".claw" / "agents" / "clawteam-ui-ux-designer.md",
                root / ".claw" / "agents" / "clawteam-rnd-frontend.md",
                root / ".claw" / "agents" / "designteam-ui-designer.md",
                root / ".claw" / "agents" / "designteam-interaction-designer.md",
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


def _style_document_text(entry: UiStyleEntry) -> str:
    parts: list[str] = []
    parts.extend(entry.tags)
    parts.extend(entry.fit_domains)
    parts.extend(entry.fit_surfaces)
    parts.extend(entry.tone_keywords)
    if entry.slug:
        parts.append(entry.slug)
    if entry.title:
        parts.append(entry.title)
    if entry.role:
        parts.extend(_keyword_tokens(entry.role))
    return " ".join(parts).lower()


def _compute_idf(styles: list[UiStyleEntry]) -> dict[str, float]:
    N = max(len(styles), 1)
    term_doc_count: dict[str, int] = {}
    for st in styles:
        doc_text = _style_document_text(st)
        seen: set[str] = set()
        for token in doc_text.split():
            if token and token not in seen:
                seen.add(token)
                term_doc_count[token] = term_doc_count.get(token, 0) + 1
    idf: dict[str, float] = {}
    for term, df in term_doc_count.items():
        idf[term] = math.log((N + 1) / (df + 1)) + 1.0
    return idf


def _dimension_of(keyword: str, entry: UiStyleEntry) -> str:
    kw = keyword.lower()
    kw_toks = _keyword_tokens(kw)
    for kw_item in entry.fit_surfaces:
        if _keyword_tokens(kw_item) & kw_toks:
            return "fit_surfaces"
    for kw_item in entry.fit_domains:
        if _keyword_tokens(kw_item) & kw_toks:
            return "fit_domains"
    for kw_item in entry.tags:
        if _keyword_tokens(kw_item) & kw_toks:
            return "tags"
    for kw_item in entry.tone_keywords:
        if _keyword_tokens(kw_item) & kw_toks:
            return "tone_keywords"
    return "identity"


def _check_brand_direct(request: str, styles: list[UiStyleEntry]) -> str | None:
    t = (request or "").lower().strip()
    tokens = tokenize(t)
    slug_set = {st.slug.lower(): st.slug for st in styles}
    for brand_name, slug in _BRAND_SLUG_MAP.items():
        if brand_name.lower() in slug_set:
            if brand_name.lower() in tokens or brand_name.lower() in t:
                return slug
        normalized_slug = slug.lower().replace(".", "").replace(" ", "")
        normalized_token_brand = brand_name.lower().replace(".", "").replace(" ", "")
        if normalized_token_brand and normalized_token_brand in t:
            if normalized_slug in slug_set:
                return slug_set[normalized_slug]
    for st in styles:
        s = st.slug.lower()
        if s in tokens:
            return st.slug
        title_toks = tokenize(st.title)
        if title_toks & tokens:
            return st.slug
    return None


def _compute_confidence(best_score: float, second_score: float, max_possible: float) -> float:
    if max_possible <= 0:
        return 0.0
    absolute = min(1.0, best_score / max_possible) if max_possible > 0 else 0.0
    gap = (best_score - second_score) / max_possible if max_possible > 0 else 0.0
    gap = min(1.0, gap * 2.0)
    confidence = 0.6 * absolute + 0.4 * gap
    return round(max(0.0, min(1.0, confidence)), 3)


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

    brand_slug = _check_brand_direct(request, styles)

    query_tokens = tokenize(text)
    expanded_query = _expand_with_synonyms(query_tokens)
    cjk_expanded = _cjk_expand(text)
    expanded_query |= cjk_expanded
    scene = {x.strip().lower() for x in (scene_tags or []) if x.strip()}
    preferred = preferred_slug.strip().lower()
    idf = _compute_idf(styles)

    scored: list[tuple[float, UiStyleEntry, list[str]]] = []
    for st in styles:
        score = 0.0
        hits: list[str] = []
        matched_dims: set[str] = set()

        for kw in st.fit_surfaces:
            if not kw:
                continue
            kw_lower = kw.lower()
            kw_tokens = _keyword_tokens(kw_lower)
            if kw_tokens & query_tokens:
                idf_val = idf.get(kw_lower, 1.0)
                w = _DIMENSION_WEIGHTS["fit_surfaces"]
                score += w * idf_val
                hits.append(f"surface:{kw_lower}")
                matched_dims.add(kw_lower)
            elif kw_tokens & expanded_query:
                idf_val = idf.get(kw_lower, 1.0)
                w = _DIMENSION_WEIGHTS["fit_surfaces"]
                score += w * idf_val * 0.7
                hits.append(f"surface~syn:{kw_lower}")

        for kw in st.fit_domains:
            if not kw:
                continue
            kw_lower = kw.lower()
            kw_tokens = _keyword_tokens(kw_lower)
            if kw_tokens & query_tokens:
                idf_val = idf.get(kw_lower, 1.0)
                w = _DIMENSION_WEIGHTS["fit_domains"]
                score += w * idf_val
                hits.append(f"domain:{kw_lower}")
                matched_dims.add(kw_lower)
            elif kw_tokens & expanded_query:
                idf_val = idf.get(kw_lower, 1.0)
                w = _DIMENSION_WEIGHTS["fit_domains"]
                score += w * idf_val * 0.7
                hits.append(f"domain~syn:{kw_lower}")

        for kw in st.tags:
            if not kw:
                continue
            kw_lower = kw.lower()
            kw_tokens = _keyword_tokens(kw_lower)
            if kw_tokens & query_tokens:
                idf_val = idf.get(kw_lower, 1.0)
                w = _DIMENSION_WEIGHTS["tags"]
                score += w * idf_val
                hits.append(f"tag:{kw_lower}")
                matched_dims.add(kw_lower)
            elif kw_tokens & expanded_query:
                idf_val = idf.get(kw_lower, 1.0)
                w = _DIMENSION_WEIGHTS["tags"]
                score += w * idf_val * 0.7
                hits.append(f"tag~syn:{kw_lower}")

        for kw in st.tone_keywords:
            if not kw:
                continue
            kw_lower = kw.lower()
            kw_tokens = _keyword_tokens(kw_lower)
            if kw_tokens & query_tokens:
                idf_val = idf.get(kw_lower, 1.0)
                w = _DIMENSION_WEIGHTS["tone_keywords"]
                score += w * idf_val
                hits.append(f"tone:{kw_lower}")
                matched_dims.add(kw_lower)
            elif kw_tokens & expanded_query:
                idf_val = idf.get(kw_lower, 1.0)
                w = _DIMENSION_WEIGHTS["tone_keywords"]
                score += w * idf_val * 0.7
                hits.append(f"tone~syn:{kw_lower}")

        for kw, label in (
            (st.slug.lower(), "slug"),
            (st.title.lower(), "title"),
        ):
            if not kw:
                continue
            kw_tokens = _keyword_tokens(kw)
            if kw_tokens & query_tokens:
                idf_val = idf.get(kw, 1.0)
                w = _DIMENSION_WEIGHTS["identity"]
                score += w * idf_val
                hits.append(f"{label}:{kw}")
            elif kw_tokens & expanded_query:
                idf_val = idf.get(kw, 1.0)
                w = _DIMENSION_WEIGHTS["identity"]
                score += w * idf_val * 0.5
                hits.append(f"{label}~syn:{kw}")

        for kw in st.avoid_surfaces:
            if not kw:
                continue
            kw_lower = kw.lower()
            kw_tokens = _keyword_tokens(kw_lower)
            if kw_tokens & query_tokens:
                score -= 2.5
                hits.append(f"avoid:{kw_lower}")
            elif kw_tokens & expanded_query:
                score -= 1.5
                hits.append(f"avoid~syn:{kw_lower}")

        if scene:
            st_tags_lower = {x.lower() for x in st.tags}
            inter_tags = scene & st_tags_lower
            if inter_tags:
                bonus = 1.1 * len(inter_tags)
                score += bonus
                hits.extend(f"scene_tag:{x}" for x in sorted(inter_tags))
            st_surfaces_lower = {x.lower() for x in st.fit_surfaces}
            inter_surfaces = scene & st_surfaces_lower
            if inter_surfaces:
                bonus = 0.7 * len(inter_surfaces)
                score += bonus
                hits.extend(f"scene_surface:{x}" for x in sorted(inter_surfaces))
            st_domains_lower = {x.lower() for x in st.fit_domains}
            inter_domains = scene & st_domains_lower
            if inter_domains:
                bonus = 0.9 * len(inter_domains)
                score += bonus
                hits.extend(f"scene_domain:{x}" for x in sorted(inter_domains))
            for stag in scene:
                if any(stag in dl for dl in st_domains_lower):
                    if f"scene_domain:{stag}" not in hits:
                        score += 0.6
                        hits.append(f"scene_domain~sub:{stag}")
                if any(stag in tl for tl in st_tags_lower):
                    if f"scene_tag:{stag}" not in hits:
                        score += 0.5
                        hits.append(f"scene_tag~sub:{stag}")

        if preferred and st.slug.lower() == preferred:
            score += 0.5
            hits.append("preferred")

        scored.append((score, st, hits))

    scored.sort(key=lambda x: x[0], reverse=True)

    if brand_slug is not None:
        brand_score = scored[0][0] + 10.0
        for i, (s, st, h) in enumerate(scored):
            if st.slug == brand_slug:
                h_copy = list(h) + ["brand_direct"]
                scored[i] = (brand_score, st, h_copy)
                scored.sort(key=lambda x: x[0], reverse=True)
                break

    best_score, best, best_hits = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0

    if best_score <= 0.0 and brand_slug is None and scene:
        tag_scored: list[tuple[float, UiStyleEntry, list[str]]] = []
        for s, st, h in scored:
            ts = 0.0
            all_kw = [x.lower() for x in st.tags + st.fit_domains + st.fit_surfaces + st.tone_keywords]
            for stag in scene:
                for kw in all_kw:
                    if stag in kw or kw in stag:
                        ts += 1.0
                        break
            tag_scored.append((ts, st, h))
        tag_scored.sort(key=lambda x: x[0], reverse=True)
        if tag_scored[0][0] > 0:
            tie_best_tag, tie_best_st, tie_best_h = tag_scored[0]
            best_score = 0.001
            best = tie_best_st
            best_hits = [f"scene_fallback:{tag_scored[0][0]:.0f} overlaps"]
            scored = [(s if st.slug != tie_best_st.slug else (0.001, st, h))
                      for s, st, h in scored]
            scored.sort(key=lambda x: x[0], reverse=True)
            second_score = scored[1][0] if len(scored) > 1 else 0.0

    if best_score <= 0.0 and brand_slug is None and not scene:
        text_lower = text
        for s, st, h in scored:
            ts = 0.0
            all_kw = " ".join(x.lower() for x in st.tags + st.fit_domains + st.fit_surfaces + st.tone_keywords + [st.role])
            for kw in all_kw.split():
                if len(kw) >= 2 and kw in text_lower:
                    ts += 0.5
            for kw in all_kw.split("_"):
                if len(kw) >= 2 and kw in text_lower:
                    ts += 0.3
            if ts > 0:
                idx = next(i for i, (ss, sst, hh) in enumerate(scored) if sst.slug == st.slug)
                scored[idx] = (ts, st, h + [f"text_fallback:{ts:.1f}"])
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored[0][0] > 0:
            best_score, best, best_hits = scored[0]
            second_score = scored[1][0] if len(scored) > 1 else 0.0

    # ── 启发式 fallback：避免零分时总是取 catalog 字母序第一（Airbnb） ──
    if best_score <= 0.0:
        _FALLBACK_GENERIC_TAGS = {"minimal", "modern", "clean", "technical", "corporate"}
        best_h_val = -1.0
        best_h_idx = 0
        for idx, (s, st, h) in enumerate(scored):
            tag_lower = {t.lower() for t in st.tags}
            generic_overlap = len(tag_lower & _FALLBACK_GENERIC_TAGS)
            avoid_penalty = len(st.avoid_surfaces) * 0.5
            domain_richness = min(len(st.fit_domains), 6) * 0.2
            heuristic = generic_overlap + domain_richness - avoid_penalty
            if heuristic > best_h_val:
                best_h_val = heuristic
                best_h_idx = idx
        if best_h_idx != 0:
            item = scored.pop(best_h_idx)
            scored.insert(0, item)
        best_score, best, best_hits = scored[0]
        if not best_hits:
            best_hits = ["heuristic_fallback:generic_fit"]

    top = [row[1].slug for row in scored[:_AUTO_PICK_TOP_N]]

    max_possible = (
        _DIMENSION_WEIGHTS["fit_surfaces"] * 2.0
        + _DIMENSION_WEIGHTS["fit_domains"] * 2.0
        + _DIMENSION_WEIGHTS["tags"] * 2.0
        + _DIMENSION_WEIGHTS["tone_keywords"] * 1.0
    )
    confidence = _compute_confidence(best_score, second_score, max_possible)

    reason_hits = ", ".join(best_hits[:8]) if best_hits else "heuristic_fallback (no keyword hits; generic versatility pick)"
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
    return _AUTO_PICK_MIN_CONFIDENCE


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


_SESSION_OVERRIDE_THRESHOLD = 2


@dataclass
class UiStyleSessionMemory:
    user_overrides: dict[str, int] = field(default_factory=dict)
    last_user_slug: str = ""
    last_auto_slug: str = ""


def update_session_memory(
    memory: UiStyleSessionMemory,
    *,
    auto_slug: str = "",
    user_slug: str = "",
) -> None:
    if auto_slug:
        memory.last_auto_slug = auto_slug
    if user_slug:
        memory.last_user_slug = user_slug
        memory.user_overrides[user_slug] = memory.user_overrides.get(user_slug, 0) + 1


def session_preferred_slug(memory: UiStyleSessionMemory) -> str:
    if not memory.user_overrides:
        return ""
    best_slug = max(memory.user_overrides, key=lambda k: memory.user_overrides[k])
    if memory.user_overrides.get(best_slug, 0) >= _SESSION_OVERRIDE_THRESHOLD:
        return best_slug
    return ""


def select_ui_style_with_memory(
    request: str,
    styles: list[UiStyleEntry],
    memory: UiStyleSessionMemory | None = None,
    *,
    scene_tags: list[str] | None = None,
    preferred_slug: str = "",
) -> UiStyleSelection | None:
    session_pref = session_preferred_slug(memory) if memory else ""
    effective_preferred = session_pref or preferred_slug
    result = select_ui_style_auto(
        request,
        styles,
        scene_tags=scene_tags,
        preferred_slug=effective_preferred,
    )
    if result is None:
        return None
    if memory is not None and session_pref:
        slug_set = {s.slug for s in styles}
        if session_pref in slug_set:
            override_count = memory.user_overrides.get(session_pref, 0)
            if result.slug != session_pref and override_count >= _SESSION_OVERRIDE_THRESHOLD:
                from .ui_style import format_ui_style_compact as _fsc
                result.slug = session_pref
                result.reason = (
                    f"选中 `{session_pref}`：用户在该会话中手动覆盖了 {override_count} 次，优先使用用户偏好。{result.reason}"
                )
    return result


_EMBEDDING_AVAILABLE: bool | None = None


def _check_embedding_available() -> bool:
    global _EMBEDDING_AVAILABLE
    if _EMBEDDING_AVAILABLE is not None:
        return _EMBEDDING_AVAILABLE
    try:
        import numpy  # noqa: F401
        _EMBEDDING_AVAILABLE = True
    except ImportError:
        _EMBEDDING_AVAILABLE = False
    return _EMBEDDING_AVAILABLE


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _get_style_embedding_text(entry: UiStyleEntry) -> str:
    parts: list[str] = []
    parts.append(entry.slug)
    parts.append(entry.title)
    parts.append(entry.role)
    parts.extend(entry.tags)
    parts.extend(entry.fit_domains)
    parts.extend(entry.fit_surfaces)
    parts.extend(entry.tone_keywords)
    return " ".join(p for p in parts if p)


def _simple_tfidf_vector(
    text: str,
    vocabulary: list[str],
) -> list[float]:
    tokens = tokenize(text)
    expanded = _expand_with_synonyms(tokens)
    total = len(vocabulary)
    if total == 0:
        return []
    vec: list[float] = [0.0] * total
    token_count: dict[str, int] = {}
    for t in tokens | expanded:
        token_count[t] = token_count.get(t, 0) + 1
    max_tf = max(token_count.values()) if token_count else 1
    for i, term in enumerate(vocabulary):
        term_tokens = _keyword_tokens(term)
        if term_tokens & (tokens | expanded):
            tf = 0.5 + 0.5 * (token_count.get(term.lower(), 1) / max_tf)
            vec[i] = tf
    return vec


def select_ui_style_hybrid(
    request: str,
    styles: list[UiStyleEntry],
    memory: UiStyleSessionMemory | None = None,
    *,
    scene_tags: list[str] | None = None,
    preferred_slug: str = "",
) -> UiStyleSelection | None:
    keyword_result = select_ui_style_with_memory(
        request, styles, memory, scene_tags=scene_tags, preferred_slug=preferred_slug,
    )
    if keyword_result is None or not styles:
        return keyword_result

    vocabulary: list[str] = []
    seen_vocab: set[str] = set()
    for st in styles:
        for kw in st.tags + st.fit_domains + st.fit_surfaces + st.tone_keywords + [st.slug, st.title]:
            kl = kw.lower()
            if kl and kl not in seen_vocab:
                seen_vocab.add(kl)
                vocabulary.append(kl)

    if len(vocabulary) == 0:
        return keyword_result

    query_vec = _simple_tfidf_vector(request, vocabulary)
    style_rankings: list[tuple[float, str]] = []
    for st in styles:
        style_text = _get_style_embedding_text(st)
        style_vec = _simple_tfidf_vector(style_text, vocabulary)
        sim = _cosine_similarity(query_vec, style_vec)
        style_rankings.append((sim, st.slug))

    style_rankings.sort(key=lambda x: x[0], reverse=True)

    K = 60
    rrf_scores: dict[str, float] = {}
    keyword_ranked = keyword_result.top_candidates
    for rank, slug in enumerate(keyword_ranked):
        rrf_scores[slug] = rrf_scores.get(slug, 0) + 1.0 / (K + rank + 1)
    for rank, (_, slug) in enumerate(style_rankings):
        rrf_scores[slug] = rrf_scores.get(slug, 0) + 1.0 / (K + rank + 1)

    best_slug = max(rrf_scores, key=rrf_scores.get) if rrf_scores else keyword_result.slug

    if best_slug == keyword_result.slug:
        return keyword_result

    entry = next((s for s in styles if s.slug == best_slug), None)
    if entry is None:
        return keyword_result

    keyword_score = rrf_scores.get(keyword_result.slug, 0)
    hybrid_score = rrf_scores.get(best_slug, 0)
    if hybrid_score <= keyword_score * 1.05:
        return keyword_result

    second_slug = keyword_result.slug
    top_sorted = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    top_candidates = [s for s, _ in top_sorted[:_AUTO_PICK_TOP_N]]
    best_rrf_score = top_sorted[0][1]
    second_rrf_score = top_sorted[1][1] if len(top_sorted) > 1 else 0.0

    reason = f"选中 `{best_slug}`：RRF hybrid 混合排序（keyword + TF-IDF cosine）；RRF分 {best_rrf_score:.4f}"
    top_preview = "; ".join(f"{s}={v:.4f}" for s, v in top_sorted[:_AUTO_PICK_TOP_N])
    confidence = _compute_confidence(best_rrf_score, second_rrf_score, best_rrf_score + 0.01)

    return UiStyleSelection(
        slug=best_slug,
        reason=reason,
        confidence=confidence,
        top_candidates=top_candidates,
        rubric=ui_style_auto_pick_rubric_text(),
        top_scores_preview=top_preview,
    )


def _style_brief_description(entry: UiStyleEntry) -> str:
    """从 style entry metadata 生成一行简要中文描述，供 LLM 判断。"""
    _DOMAIN_MAP = {
        "travel": "旅游", "ecommerce": "电商", "social": "社交",
        "developer_tooling": "开发工具", "fintech": "金融科技",
        "marketing": "品牌营销", "documentation": "文档",
        "analytics": "数据分析", "ai_platform": "AI平台",
        "enterprise_saas": "企业SaaS", "mobile": "移动端",
        "design_tools": "设计工具", "productivity": "效率工具",
        "healthcare": "医疗", "education": "教育",
        "audio": "音频", "video_streaming": "视频", "crm": "CRM",
        "automation": "自动化", "collaboration": "协作",
        "payments": "支付", "infrastructure": "基础设施",
        "b2b_saas": "B2B SaaS", "project_management": "项目管理",
        "scheduling": "日程", "api_service": "API服务",
        "site_builder": "建站", "cms": "CMS",
    }
    _TAG_MAP = {
        "minimal": "极简", "dark_native": "深色系", "vibrant": "鲜明色彩",
        "premium": "高端", "technical": "技术感", "playful": "活泼",
        "rounded_soft": "圆润柔和", "geometric": "几何线条",
        "photo_first": "图片优先", "corporate": "商务",
        "modern": "现代", "high_density": "高密度",
        "warm_marketplace": "温暖市场", "editorial_utility": "编辑实用",
        "fintech_premium": "金融高端", "minimal_engineering": "极简工程",
    }
    parts: list[str] = []
    if entry.fit_domains:
        domains = [_DOMAIN_MAP.get(d, d) for d in entry.fit_domains[:4]]
        parts.append("适用: " + "/".join(domains))
    if entry.tags:
        tags = [_TAG_MAP.get(t, t) for t in entry.tags[:3]]
        parts.append("风格: " + "/".join(tags))
    if entry.tone_keywords:
        parts.append("调性: " + "/".join(entry.tone_keywords[:3]))
    return " | ".join(parts) if parts else entry.title


def style_delegation_menu(
    picked_slug: str,
    top_candidates: list[str],
    catalog: list[UiStyleEntry],
) -> str:
    slug_map = {s.slug: s for s in catalog}
    picked = slug_map.get(picked_slug)
    lines = [
        "UI STYLE DELEGATION MENU:",
        f"- recommended_style: {picked_slug}",
    ]
    if picked:
        lines.append(f"  title: {picked.title}")
        if picked.tags:
            lines.append(f"  tags: {', '.join(picked.tags[:5])}")
        if picked.fit_domains:
            lines.append(f"  fit_domains: {', '.join(picked.fit_domains[:5])}")
        brief = _style_brief_description(picked)
        if brief:
            lines.append(f"  summary: {brief}")
    lines.append("")
    lines.append("alternative_styles (use if recommended does not fit the user's intent):")
    alternatives = [s for s in top_candidates if s != picked_slug]
    for i, slug in enumerate(alternatives[:9], 1):
        entry = slug_map.get(slug)
        if entry is None:
            continue
        parts = [f"  {i}. {slug} — {entry.title}"]
        brief = _style_brief_description(entry)
        if brief:
            parts.append(f"\n     {brief}")
        meta: list[str] = []
        if entry.tags:
            meta.extend(entry.tags[:4])
        if entry.fit_domains:
            meta.extend(entry.fit_domains[:3])
        if entry.fit_surfaces:
            meta.extend(entry.fit_surfaces[:2])
        if entry.tone_keywords:
            meta.extend(entry.tone_keywords[:2])
        if meta:
            parts.append(f"\n     tags: [{', '.join(meta)}]")
        lines.append("".join(parts))
    lines.append("")
    lines.append(
        "delegation_instruction: Based on the user's specific request and design intent, "
        "choose the most appropriate style from the recommended and alternative candidates above. "
        "Apply that style's conventions for typography, colors, components, and responsive rules. "
        "State which style you are applying at the beginning of your response."
    )
    return "\n".join(lines) + "\n\n"

