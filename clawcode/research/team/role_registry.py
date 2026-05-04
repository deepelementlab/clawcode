from __future__ import annotations

from .role_configs import DEFAULT_RESEARCH_ROLES, ResearchRole


class ResearchRoleRegistry:
    def __init__(self) -> None:
        self._roles: dict[str, ResearchRole] = {}
        for role in DEFAULT_RESEARCH_ROLES:
            self.register(role)

    def register(self, role: ResearchRole) -> None:
        self._roles[role.role_id] = role

    def get(self, role_id: str) -> ResearchRole | None:
        return self._roles.get(role_id)

    def list_all(self) -> list[ResearchRole]:
        return list(self._roles.values())

    def resolve_many(self, role_ids: list[str]) -> list[ResearchRole]:
        out: list[ResearchRole] = []
        for rid in role_ids:
            role = self.get(rid)
            if role is not None:
                out.append(role)
        return out
