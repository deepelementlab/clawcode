"""Sandbox abstraction for research code runs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SandboxResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int | None = None


class Sandbox(ABC):
    """Isolated workspace for optional execute_code tooling."""

    id: str

    @abstractmethod
    async def execute_command(self, command: str, *, cwd: Path | None = None) -> SandboxResult:
        """Run a shell command inside the sandbox."""

    @abstractmethod
    async def write_file(self, path: str, content: str) -> None:
        """Write a relative path under the sandbox root."""

    @abstractmethod
    async def read_file(self, path: str) -> str:
        """Read a relative path."""
