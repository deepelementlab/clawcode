from __future__ import annotations

import re
from typing import Any

from ..domain_schema import DomainFieldDef, DomainSchema

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


class DomainValidator:
    def __init__(self, schema: DomainSchema) -> None:
        self.schema = schema

    def _entity_def(self, entity_type: str):
        for one in self.schema.entities:
            if one.name.lower() == (entity_type or "").lower():
                return one
        return None

    def validate_page(self, content: str, frontmatter: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        entity_type = str(frontmatter.get("type", "") or "")
        entity_def = self._entity_def(entity_type)
        if entity_def is not None:
            for key in entity_def.required_fields:
                if key not in frontmatter:
                    errors.append(f"missing required field '{key}' for entity '{entity_type}'")
            for f in entity_def.fields:
                if f.name in frontmatter and not self._validate_field_type(frontmatter[f.name], f):
                    errors.append(f"field type mismatch: {f.name} should be {f.type}")
        errors.extend(self._validate_relations(content))
        return errors

    def _validate_field_type(self, value: Any, field_def: DomainFieldDef) -> bool:
        checks: dict[str, Any] = {
            "string": lambda v: isinstance(v, str),
            "number": lambda v: isinstance(v, (int, float)),
            "boolean": lambda v: isinstance(v, bool),
            "list": lambda v: isinstance(v, list),
            "dict": lambda v: isinstance(v, dict),
            "date": lambda v: isinstance(v, str),
            "enum": lambda v: isinstance(v, str) and v in field_def.enum_values,
        }
        check = checks.get(field_def.type)
        if check is None:
            return True
        if not check(value):
            return False
        if field_def.validation_regex and isinstance(value, str):
            return bool(re.match(field_def.validation_regex, value))
        return True

    def _validate_relations(self, content: str) -> list[str]:
        links = _WIKILINK_RE.findall(content)
        if self.schema.relations and not links:
            return ["expected at least one wikilink relation for this domain"]
        return []

