"""Resolve sandbox implementation from settings."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .docker import DockerSandbox
from .local import LocalSandbox

if TYPE_CHECKING:
    from ..settings_models import ResearchSandboxConfig


def _default_work_dir(cfg: "ResearchSandboxConfig") -> Path:
    raw = (cfg.work_dir or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(tempfile.gettempdir()) / "clawcode-research"


def get_sandbox_for_settings(cfg: "ResearchSandboxConfig") -> LocalSandbox | DockerSandbox:
    work = _default_work_dir(cfg)
    if cfg.type == "docker":
        return DockerSandbox(cfg.docker_image, work)
    # k8s: remote orchestration not bundled; use local workspace with the same layout.
    return LocalSandbox(work)
