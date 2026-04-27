"""Docker-backed sandbox (optional; requires Docker CLI on host)."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from .base import Sandbox, SandboxResult


class DockerSandbox(Sandbox):
    """Minimal docker run wrapper for batch commands."""

    def __init__(self, image: str, work_dir: Path) -> None:
        self.id = f"docker-{uuid.uuid4().hex[:8]}"
        self._image = image
        self._work = work_dir.resolve()
        self._work.mkdir(parents=True, exist_ok=True)

    async def execute_command(self, command: str, *, cwd: Path | None = None) -> SandboxResult:
        if not shutil.which("docker"):
            return SandboxResult(
                ok=False,
                stdout="",
                stderr="docker CLI not found on PATH",
                exit_code=127,
            )
        # Mount work dir at /work
        vol = f"{self._work}:/work"
        inner_cwd = "/work"
        if cwd:
            try:
                rel = cwd.resolve().relative_to(self._work)
                inner_cwd = f"/work/{rel.as_posix()}"
            except ValueError:
                inner_cwd = "/work"
        full = [
            "docker",
            "run",
            "--rm",
            "-v",
            vol,
            "-w",
            inner_cwd,
            self._image,
            "sh",
            "-c",
            command,
        ]
        proc = await asyncio.create_subprocess_exec(
            *full,
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
        target = (self._work / path).resolve()
        if self._work not in target.parents and target != self._work:
            raise ValueError("path escapes sandbox root")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    async def read_file(self, path: str) -> str:
        target = (self._work / path).resolve()
        if self._work not in target.parents and target != self._work:
            raise ValueError("path escapes sandbox root")
        return target.read_text(encoding="utf-8")
