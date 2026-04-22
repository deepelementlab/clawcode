from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from ..observer import DeepNoteObserver
from ..domain_registry import DomainRegistry
from ..validators.domain import DomainValidator
from ..validators.frontmatter import validate_frontmatter
from ..validators.links import known_page_slugs, validate_links
from ..validators.schema import validate_schema_compliance
from ..wiki_store import WikiStore

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from ...llm.tools.base import ToolCall, ToolContext


class WikiLintTool:
    def info(self):
        from ...llm.tools.base import ToolInfo

        return ToolInfo(
            name="wiki_lint",
            description="Lint DeepNote wiki for frontmatter/schema/link issues.",
            parameters={
                "type": "object",
                "properties": {
                    "checks": {"type": "array", "items": {"type": "string"}},
                    "domain": {"type": "string", "description": "Optional domain id for domain-specific validation."},
                },
                "required": [],
            },
            required=[],
        )

    async def run(self, call: ToolCall, context: ToolContext):
        from ...llm.tools.base import ToolResponse
        from ...config import get_settings

        args = call.get_input_dict() if hasattr(call, "get_input_dict") else {}
        obs_input = {"checks": args.get("checks", []), "domain": args.get("domain")}
        domain_id = str(args.get("domain", "") or "").strip().lower()
        settings = get_settings()
        store = WikiStore.from_settings(settings)
        try:
            logger.info("deepnote_tool_invoke", tool="wiki_lint")
            DeepNoteObserver.record_pre("wiki_lint", context, obs_input, settings=settings)
            schema_path = store.root / "SCHEMA.md"
            domain_validator: DomainValidator | None = None
            if domain_id:
                registry = DomainRegistry()
                schema = registry.get(domain_id)
                if schema is None:
                    dcfg = getattr(store.config, "domains", {}).get(domain_id)
                    schema_path_cfg = str(getattr(dcfg, "schema_path", "") or "").strip() if dcfg else ""
                    if schema_path_cfg:
                        try:
                            schema = registry.load_from_file(Path(schema_path_cfg).expanduser().resolve())
                        except Exception:
                            schema = None
                if schema is None:
                    return ToolResponse.error(
                        json.dumps({"success": False, "error": f"domain not found: {domain_id}"}, ensure_ascii=False)
                    )
                domain_validator = DomainValidator(schema)
            issues: list[dict[str, Any]] = []
            known = known_page_slugs(store.root)
            for page in store.iter_wiki_pages():
                text = page.read_text(encoding="utf-8")
                errs: list[str] = []
                errs.extend(validate_frontmatter(text))
                errs.extend(
                    validate_links(
                        page,
                        store.root,
                        min_outbound=store.config.validation.min_outbound_links,
                        known_slugs=known,
                    )
                )
                errs.extend(validate_schema_compliance(text, schema_path))
                if domain_validator is not None:
                    fm = _extract_frontmatter_map(text)
                    errs.extend(domain_validator.validate_page(text, fm))
                if errs:
                    issues.append({"page": str(page.relative_to(store.root)), "issues": errs})
            payload = {"success": True, "issue_count": len(issues), "issues": issues}
            DeepNoteObserver.record_post("wiki_lint", context, obs_input, {"issue_count": len(issues)}, settings=settings)
            return ToolResponse.text(json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            DeepNoteObserver.record_post("wiki_lint", context, obs_input, {"error": str(exc)}, settings=settings, is_error=True)
            raise
        finally:
            store.close()


def create_wiki_lint_tool(permissions: Any = None) -> WikiLintTool:
    return WikiLintTool()


def _extract_frontmatter_map(content: str) -> dict[str, Any]:
    if not content.startswith("---\n"):
        return {}
    end = content.find("\n---", 4)
    if end == -1:
        return {}
    header = content[4:end]
    out: dict[str, Any] = {}
    for line in header.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        k = key.strip()
        v = value.strip()
        if v.startswith("[") and v.endswith("]"):
            try:
                out[k] = json.loads(v)
                continue
            except Exception:
                pass
        out[k] = v
    return out

