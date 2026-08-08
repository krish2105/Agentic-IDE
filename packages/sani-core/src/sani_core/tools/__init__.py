"""Tool adapters.

Phase 0 ships the file editor and the shell. The browser adapter (Phase 3c)
implements the same three methods and slots in here with no executor changes --
that is the whole point of the interface.
"""

from __future__ import annotations

from pathlib import Path

from ..runners import CommandRunner
from .base import ToolAdapter, ToolError
from .browser import BrowserTool
from .file_editor import FileEditorTool
from .shell import ShellTool

REGISTRY: dict[str, type[ToolAdapter]] = {
    FileEditorTool.name: FileEditorTool,
    ShellTool.name: ShellTool,
    # Phase 3c. Implements the same three methods as the others and needed no
    # executor changes, which was the point of the interface.
    BrowserTool.name: BrowserTool,
}


def build_tools(
    names: list[str], workspace: Path, *, runner: CommandRunner | None = None
) -> dict[str, ToolAdapter]:
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise ToolError(f"unknown tool(s): {unknown}; available: {sorted(REGISTRY)}")
    return {name: REGISTRY[name](workspace, runner=runner) for name in names}


__all__ = [
    "REGISTRY",
    "BrowserTool",
    "FileEditorTool",
    "ShellTool",
    "ToolAdapter",
    "ToolError",
    "build_tools",
]
