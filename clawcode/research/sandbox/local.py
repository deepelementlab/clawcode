"""Process-isolated local sandbox (workspace subdirectory)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from .base import Sandbox, SandboxResult


class LocalSandbox(Sandbox):
    """Runs commands in a dedicated directory under the host OS."""

    def __init__(self, root: Path) -> None:
        self.id = f"local-{uuid.uuid4().hex[:8]}"
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _safe_join(self, rel: str) -> Path:
        p = (self._root / rel).resolve()
        if self._root not in p.parents and p != self._root:
            raise ValueError("path escapes sandbox root")
        return p

    async def execute_command(self, command: str, *, cwd: Path | None = None) -> SandboxResult:
        work = cwd.resolve() if cwd else self._root
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(work),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await proc.communicate()
        return SandboxResult(
            ok=proc.returncode == 0,
            stdout=out_b.decode(errors="replace"),
            stderr=err_b.decode(errors="replace"),
            exit_code=proc.returncode,
        )

    async def write_file(self, path: str, content: str) -> None:
        target = self._safe_join(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    async def read_file(self, path: str) -> str:
        return self._safe_join(path).read_text(encoding="utf-8")
