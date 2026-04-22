from __future__ import annotations

import json
from pathlib import Path

from .domain_schema import DomainSchema


class DomainRegistry:
    _instance: DomainRegistry | None = None

    def __new__(cls) -> DomainRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._schemas = {}
        return cls._instance

    def register(self, schema: DomainSchema) -> None:
        self._schemas[schema.domain_id] = schema

    def unregister(self, domain_id: str) -> bool:
        if domain_id in self._schemas:
            del self._schemas[domain_id]
            return True
        return False

    def get(self, domain_id: str) -> DomainSchema | None:
        return self._schemas.get(domain_id)

    def list_domains(self) -> list[str]:
        return sorted(self._schemas.keys())

    def load_from_file(self, path: Path) -> DomainSchema:
        payload = json.loads(path.read_text(encoding="utf-8"))
        schema = DomainSchema(**payload)
        self.register(schema)
        return schema

    def save_to_file(self, domain_id: str, path: Path) -> None:
        schema = self.get(domain_id)
        if schema is None:
            raise ValueError(f"domain not found: {domain_id}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(schema.model_dump_json(indent=2), encoding="utf-8")

