"""Right-side information panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from rich.text import Text
from textual.widgets import Static


@dataclass(frozen=True)
class InfoPanelModel:
    version: str = "dev"
    repo: str = ""
    cwd: str = "—"
    session_title: str = "—"
    lsp_lines: list[str] = None  # type: ignore[assignment]
    modified_files: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "lsp_lines", list(self.lsp_lines or []))
        object.__setattr__(self, "modified_files", list(self.modified_files or []))


class InfoPanel(Static):
    MAX_VISIBLE_LSP_LINES = 6

    DEFAULT_CSS = """
    InfoPanel {
        height: auto;
        padding: 1 2;
        background: $surface;
        color: $text;
    }

    InfoPanel .title {
        text-style: bold;
        color: $text;
    }
    """

    def render_model(self, model: InfoPanelModel, *, accent: str = "#fab283", muted: str = "#6a6a6a") -> Text:
        out = Text()
        out.append(f"ClawCode v{model.version}\n", style=f"bold {accent}")
        if model.repo:
            out.append(f"{model.repo}\n", style=muted)
        out.append("\n")
        out.append(f"cwd: ", style=muted)
        out.append(f"{model.cwd}\n\n")

        out.append("Session:\n", style=f"bold {accent}")
        out.append(f"  {model.session_title}\n\n")

        out.append("LSP Configuration\n", style=f"bold {accent}")
        if model.lsp_lines:
            visible = model.lsp_lines[: self.MAX_VISIBLE_LSP_LINES]
            for ln in visible:
                out.append(f"  {ln}\n")
            hidden_count = len(model.lsp_lines) - len(visible)
            if hidden_count > 0:
                out.append(f"  ... and {hidden_count} more\n", style=muted)
        else:
            out.append("  (none)\n", style=muted)
        out.append("\n")

        out.append("Modified Files:\n", style=f"bold {accent}")
        if model.modified_files:
            for ln in model.modified_files:
                out.append(f"  {ln}\n")
        else:
            out.append("  No modified files\n", style=muted)

        return out

    def set_model(self, model: InfoPanelModel, *, accent: str = "#fab283", muted: str = "#6a6a6a") -> None:
        self.update(self.render_model(model, accent=accent, muted=muted))


def format_lsp_lines(items: Iterable[tuple[str, str]]) -> list[str]:
    """Format LSP config as lines: '• Name (cmd ...)'."""
    max_len = 80

    def _clip(text: str) -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - 1] + "…"

    out: list[str] = []
    for name, cmd in items:
        nm = (name or "").strip() or "LSP"
        cm = (cmd or "").strip()
        if cm:
            out.append(_clip(f"• {nm} ({cm})"))
        else:
            out.append(_clip(f"• {nm}"))
    return out


__all__ = ["InfoPanel", "InfoPanelModel", "format_lsp_lines"]

