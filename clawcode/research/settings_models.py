"""Pydantic models for research mode (loaded via main Settings)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ResearchWorkflowRuntimeConfig(BaseModel):
    """Per-workflow limits and behavior."""

    max_iterations: int = 10
    max_subagents: int = 5
    enable_verification: bool = True
    output_format: str = "markdown"


class ResearchSubAgentConfig(BaseModel):
    """Sub-agent pool settings."""

    max_concurrent: int = 3
    timeout_seconds: int = 300
    builtin_agents: list[str] = Field(
        default_factory=lambda: ["researcher", "reviewer", "writer", "verifier"]
    )


class ResearchSandboxConfig(BaseModel):
    """Isolated execution backend for research runs."""

    type: Literal["local", "docker", "k8s"] = "local"
    docker_image: str = "clawcode-research-sandbox:latest"
    #: Empty = OS temp directory + clawcode-research
    work_dir: str = ""


class ResearchMemoryConfig(BaseModel):
    """Long-form research memory (file-backed by default)."""

    enabled: bool = True
    storage_subdir: str = "research_memory"


class ResearchToolsConfig(BaseModel):
    """Built-in research tool toggles."""

    web_search_enabled: bool = True
    paper_search_enabled: bool = True
    sandbox_execute_enabled: bool = True


class ResearchConfig(BaseModel):
    """Top-level research mode configuration (nested under Settings.research)."""

    enabled: bool = True
    #: native = in-process engine; external = optional adapter (see adapters.base)
    backend: Literal["native", "external"] = "native"
    external_adapter: str = ""
    default_model: str = ""
    s2_api_key: str = ""
    workflows: dict[str, ResearchWorkflowRuntimeConfig] = Field(default_factory=dict)
    subagents: ResearchSubAgentConfig = Field(default_factory=ResearchSubAgentConfig)
    sandbox: ResearchSandboxConfig = Field(default_factory=ResearchSandboxConfig)
    memory: ResearchMemoryConfig = Field(default_factory=ResearchMemoryConfig)
    tools: ResearchToolsConfig = Field(default_factory=ResearchToolsConfig)
