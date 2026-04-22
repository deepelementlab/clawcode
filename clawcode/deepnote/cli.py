from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from ..config.settings import Settings
from .domain_registry import DomainRegistry
from .importers import ImporterRegistry
from .learning_service import DeepNoteLearningService


def _builtin_domain_schema_paths() -> list[Path]:
    """Return schema paths for all built-in DeepNote domains."""
    base = Path(__file__).resolve().parent / "domains"
    paths: list[Path] = []
    if not base.exists():
        return paths
    for schema in sorted(base.glob("*/schema.json")):
        paths.append(schema)
    return paths


def _parse_only_prefixes(raw: str) -> list[str]:
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def cycle_main(argv: list[str] | None = None) -> int:
    """Standalone entrypoint: run DeepNote cycle without subcommands."""
    parser = argparse.ArgumentParser(description="Run one DeepNote learning cycle")
    parser.add_argument("--window-hours", type=int, default=168)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    settings = Settings()
    settings.working_directory = str(args.cwd.resolve())
    svc = DeepNoteLearningService(settings=settings)
    dry = bool(args.dry_run or (not args.apply))
    result = svc.run_learning_cycle(window_hours=max(1, int(args.window_hours)), dry_run=dry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DeepNote closed-loop learning CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run-cycle", help="Run DeepNote learning cycle")
    run.add_argument("--window-hours", type=int, default=168)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--apply", action="store_true")
    run.add_argument("--cwd", type=Path, default=Path.cwd())

    domain = sub.add_parser("domain", help="Domain knowledge management")
    domain_sub = domain.add_subparsers(dest="domain_action", required=True)
    dreg = domain_sub.add_parser("register", help="Register domain schema")
    dreg.add_argument("schema_path", type=Path)
    dreg.add_argument("--cwd", type=Path, default=Path.cwd())
    dbuiltin = domain_sub.add_parser("register-builtins", help="Register all built-in domain schemas")
    dbuiltin.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma-separated domain_id prefixes, e.g. finance,marketing or fin,mark",
    )
    dbuiltin.add_argument("--cwd", type=Path, default=Path.cwd())
    dlist = domain_sub.add_parser("list", help="List domain schemas")
    dlist.add_argument("--cwd", type=Path, default=Path.cwd())
    dimport = domain_sub.add_parser("import", help="Import domain knowledge source")
    dimport.add_argument("domain_id", type=str)
    dimport.add_argument("source", type=str)
    dimport.add_argument("--title", type=str, default="")
    dimport.add_argument("--section", type=str, default="concepts")
    dimport.add_argument("--format", choices=["auto", "text", "txt", "md", "csv", "tsv", "pdf"], default="auto")
    dimport.add_argument("--cwd", type=Path, default=Path.cwd())
    dval = domain_sub.add_parser("validate", help="Validate domain metadata files")
    dval.add_argument("domain_id", type=str)
    dval.add_argument("--cwd", type=Path, default=Path.cwd())
    _ = dlist

    args = parser.parse_args(argv)
    settings = Settings()
    settings.working_directory = str(args.cwd.resolve())
    svc = DeepNoteLearningService(settings=settings)

    if args.cmd == "run-cycle":
        dry = bool(args.dry_run or (not args.apply))
        result = svc.run_learning_cycle(window_hours=max(1, int(args.window_hours)), dry_run=dry)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "domain":
        registry = DomainRegistry()
        if args.domain_action == "register":
            schema = registry.load_from_file(args.schema_path)
            print(json.dumps({"ok": True, "domain_id": schema.domain_id}, ensure_ascii=False, indent=2))
            return 0
        if args.domain_action == "register-builtins":
            only_prefixes = _parse_only_prefixes(getattr(args, "only", ""))
            loaded: list[dict[str, str]] = []
            for schema_path in _builtin_domain_schema_paths():
                domain_id = schema_path.parent.name.lower()
                if only_prefixes and not any(domain_id.startswith(p) for p in only_prefixes):
                    continue
                schema = registry.load_from_file(schema_path)
                loaded.append({"domain_id": schema.domain_id, "schema_path": str(schema_path)})
            print(
                json.dumps(
                    {"ok": True, "registered": len(loaded), "only": only_prefixes, "domains": loaded},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.domain_action == "list":
            print(json.dumps({"domains": registry.list_domains()}, ensure_ascii=False, indent=2))
            return 0
        if args.domain_action == "import":
            store = svc.store
            source_path = Path(args.source)
            importer = ImporterRegistry.resolve(source_path if source_path.exists() else args.source, fmt=args.format)
            if importer is None:
                print(
                    json.dumps(
                        {"ok": False, "error": f"no importer for format={args.format}", "supported": ImporterRegistry.list_formats()},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 1
            items: list[dict[str, Any]] = []
            if source_path.exists():
                ok, msg = importer.validate_source(source_path)
                if not ok:
                    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False, indent=2))
                    return 1

                async def _collect_from_file() -> list[dict[str, Any]]:
                    out: list[dict[str, Any]] = []
                    async for item in importer.import_from_file(
                        source_path,
                        {"title": args.title, "section": args.section, "tags": [args.domain_id]},
                    ):
                        out.append(item)
                    return out

                items = asyncio.run(_collect_from_file())
            else:
                async def _collect_from_url() -> list[dict[str, Any]]:
                    out: list[dict[str, Any]] = []
                    async for item in importer.import_from_url(
                        args.source,
                        {"title": args.title, "section": args.section, "tags": [args.domain_id]},
                    ):
                        out.append(item)
                    return out

                items = asyncio.run(_collect_from_url())

            results: list[dict[str, Any]] = []
            for item in items:
                results.append(
                    store.ingest_with_domain(
                        source=str(item.get("body") or ""),
                        title=str(item.get("title") or args.title or args.source[:60]),
                        domain_id=args.domain_id,
                        section=str(item.get("section") or args.section),
                        tags=list(item.get("tags") or [args.domain_id]),
                        summary=str(item.get("body") or ""),
                    )
                )
            print(json.dumps({"ok": True, "imported": len(results), "results": results}, ensure_ascii=False, indent=2))
            return 0
        if args.domain_action == "validate":
            schema = registry.get(args.domain_id)
            if schema is None:
                print(json.dumps({"ok": False, "error": "domain not found"}, ensure_ascii=False, indent=2))
                return 1
            meta_dir = svc.store.meta / "domain_metadata"
            count = len(list(meta_dir.glob(f"*_{args.domain_id}.json"))) if meta_dir.exists() else 0
            print(json.dumps({"ok": True, "metadata_files": count}, ensure_ascii=False, indent=2))
            return 0

    return 1


__all__ = ["main", "cycle_main"]

