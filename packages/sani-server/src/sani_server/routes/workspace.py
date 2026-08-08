"""Workspace file access for the editor and file tree.

This is the human-driven path, distinct from the agent's file_editor tool. It
shares the same containment check, because "the user clicked it" is not a
reason to serve a file from outside the workspace -- the browser asking is not
proof of what the person intended.

Unlike the agent path there is no approval gate here: a human editing their own
open file is the baseline interaction of an IDE, not an action to be reviewed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sani_core.workspace import MAX_EDITABLE_BYTES, build_tree, is_probably_binary, resolve_in_workspace

from ..deps import get_manager
from ..manager import InvalidState, SessionManager

router = APIRouter(tags=["workspace"])


class SaveFileRequest(BaseModel):
    path: str
    content: str


class FileOutsideWorkspace(Exception):
    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"{path} is outside the session workspace")


def _resolve(manager: SessionManager, session_id: str, path: str):
    record = manager.get(session_id)
    resolved = resolve_in_workspace(record.session.workspace, path)
    if resolved.escaped:
        raise FileOutsideWorkspace(path)
    return record, resolved


@router.get("/session/{session_id}/files")
async def list_files(session_id: str, manager: SessionManager = Depends(get_manager)) -> dict:
    """Flat listing of the workspace, sorted directories-first."""
    record = manager.get(session_id)
    return {
        "session_id": session_id,
        "workspace": str(record.session.workspace),
        "entries": build_tree(record.session.workspace),
    }


@router.get("/session/{session_id}/file")
async def read_file(
    session_id: str,
    path: str = Query(description="Path relative to the session workspace"),
    manager: SessionManager = Depends(get_manager),
) -> dict:
    _, resolved = _resolve(manager, session_id, path)

    if not resolved.path.is_file():
        raise InvalidState(f"{path} is not a file")

    size = resolved.path.stat().st_size
    if size > MAX_EDITABLE_BYTES:
        return {"path": resolved.relpath, "size": size, "too_large": True, "content": None}
    if is_probably_binary(resolved.path):
        return {"path": resolved.relpath, "size": size, "binary": True, "content": None}

    return {
        "path": resolved.relpath,
        "size": size,
        "binary": False,
        "too_large": False,
        "content": resolved.path.read_text(encoding="utf-8", errors="replace"),
    }


@router.put("/session/{session_id}/file")
async def save_file(
    session_id: str, body: SaveFileRequest, manager: SessionManager = Depends(get_manager)
) -> dict:
    """Save an edit made by the human in the editor."""
    _, resolved = _resolve(manager, session_id, body.path)
    resolved.path.parent.mkdir(parents=True, exist_ok=True)
    resolved.path.write_text(body.content, encoding="utf-8")
    return {
        "path": resolved.relpath,
        "size": resolved.path.stat().st_size,
        "saved": True,
    }
