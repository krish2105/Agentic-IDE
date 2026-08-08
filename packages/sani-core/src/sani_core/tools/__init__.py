"""Tool adapters.

Phase 0 ships the file editor and the shell. The browser adapter (Phase 3c)
implements the same three methods and slots in here with no executor changes --
that is the whole point of the interface.
"""

from __future__ import annotations

from pathlib import Path

from .base import ToolAdapter, ToolError
from .file_editor import FileEditorTool
from .shell import ShellTool

REGISTRY: dict[str, type[ToolAdapter]] = {
    FileEditorTool.name: FileEditorTool,
    ShellTool.name: ShellTool,
}


def build_tools(names: list[str], workspace: Path) -> dict[str, ToolAdapter]:
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise ToolError(f"unknown tool(s): {unknown}; available: {sorted(REGISTRY)}")
    return {name: REGISTRY[name](workspace) for name in names}


__all__ = ["REGISTRY", "FileEditorTool", "ShellTool", "ToolAdapter", "ToolError", "build_tools"]
