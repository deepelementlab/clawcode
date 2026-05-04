from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .experience_models import ResearchTECAP


class ResearchTECAPService:
    def __init__(self, settings: Any) -> None:
        self._settings = settings
        root = settings.ensure_data_directory() / "learning" / "research-team"
        root.mkdir(parents=True, exist_ok=True)
        self._dir = root / "capsules"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, rtecap_id: str) -> Path:
        return self._dir / f"{rtecap_id}.json"

    def list_capsules(self, limit: int = 100) -> list[ResearchTECAP]:
        rows: list[ResearchTECAP] = []
        for p in sorted(self._dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(obj, dict):
                    rows.append(ResearchTECAP.from_dict(obj))
            except Exception:
                continue
        return rows

    def get(self, rtecap_id: str) -> ResearchTECAP | None:
        p = self._path(rtecap_id)
        if not p.is_file():
            return None
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                return ResearchTECAP.from_dict(obj)
        except Exception:
            return None
        return None

    def save(self, capsule: ResearchTECAP) -> Path:
        if not capsule.rtecap_id:
            capsule.rtecap_id = f"rtecap-{int(time.time())}"
        p = self._path(capsule.rtecap_id)
        p.write_text(json.dumps(capsule.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return p
