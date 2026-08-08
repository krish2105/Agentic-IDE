"""Workspace path resolution.

Every path that reaches the filesystem -- whether the agent proposed it or a
human clicked it in the file tree -- goes through :func:`resolve_in_workspace`.
Two callers with two different escape checks is how a containment bug gets in,
so there is one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Directories never worth showing in a file tree.
IGNORED_DIR_NAMES = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next", "dist", "build",
        ".turbo", ".idea", ".vscode", "target", ".terraform",
    }
)

#: Files above this size are listed but never sent to an editor.
MAX_EDITABLE_BYTES = 2_000_000


@dataclass(slots=True)
class ResolvedPath:
    path: Path
    relpath: str
    escaped: bool


def resolve_in_workspace(workspace: Path, raw_path: str) -> ResolvedPath:
    """Resolve ``raw_path`` against ``workspace`` and report containment.

    ``Path.resolve`` follows symlinks, so a link inside the workspace pointing
    outside it is caught here rather than at write time.
    """
    workspace = Path(workspace).resolve()
    candidate = Path(raw_path)
    target = (candidate if candidate.is_absolute() else workspace / candidate).resolve()

    escaped = not target.is_relative_to(workspace)
    relpath = raw_path if escaped else str(target.relative_to(workspace))
    return ResolvedPath(path=target, relpath=relpath, escaped=escaped)


def is_probably_binary(path: Path, sniff_bytes: int = 4096) -> bool:
    try:
        chunk = path.open("rb").read(sniff_bytes)
    except OSError:
        return True
    return b"\x00" in chunk


def build_tree(workspace: Path, *, max_entries: int = 5000) -> list[dict]:
    """A flat, sorted listing of the workspace.

    Flat rather than nested: the client already needs a lookup by path for
    editor tabs and diff highlighting, and a flat list is cheaper to diff
    against on refresh than a tree of nested objects.
    """
    workspace = Path(workspace).resolve()
    entries: list[dict] = []

    def walk(directory: Path) -> None:
        if len(entries) >= max_entries:
            return
        try:
            children = sorted(
                directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
            )
        except OSError:
            return

        for child in children:
            if len(entries) >= max_entries:
                return
            if child.name in IGNORED_DIR_NAMES:
                continue
            relative = child.relative_to(workspace)
            if child.is_dir() and not child.is_symlink():
                entries.append(
                    {"path": str(relative), "name": child.name, "type": "dir", "size": None}
                )
                walk(child)
            elif child.is_file():
                try:
                    size = child.stat().st_size
                except OSError:
                    continue
                entries.append(
                    {"path": str(relative), "name": child.name, "type": "file", "size": size}
                )

    walk(workspace)
    return entries
