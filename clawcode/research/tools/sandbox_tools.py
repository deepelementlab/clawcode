"""Execute short snippets in the active research sandbox."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..sandbox.base import Sandbox


async def sandbox_run_command(sbx: "Sandbox", command: str) -> dict[str, Any]:
    res = await sbx.execute_command(command)
    return {
        "ok": res.ok,
        "stdout": res.stdout,
        "stderr": res.stderr,
        "exit_code": res.exit_code,
    }
