"""Codebase RAG endpoints (spec Section 7, the last two rows).

The index is per workspace rather than per session: two sessions on one repo
should not pay to index it twice, and an index outlives the session that built
it. Sessions pick up the index for their workspace automatically, so retrieval
needs no per-session opt-in.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sani_core.rag import DEFAULT_TOP_K

from ..deps import get_manager
from ..manager import InvalidWorkspace, SessionManager

router = APIRouter(tags=["rag"])


class IndexRequest(BaseModel):
    workspace: str | None = Field(
        default=None, description="Workspace to index. Defaults to the session's."
    )
    session_id: str | None = Field(
        default=None, description="Index the workspace belonging to this session."
    )


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    workspace: str | None = None
    session_id: str | None = None
    limit: int = Field(default=DEFAULT_TOP_K, ge=1, le=50)


def _workspace_for(
    manager: SessionManager, workspace: str | None, session_id: str | None
) -> Path:
    if session_id:
        return manager.get(session_id).session.workspace
    if workspace:
        path = Path(workspace).expanduser().resolve()
        if not path.is_dir():
            raise InvalidWorkspace(f"workspace {path} does not exist or is not a directory")
        return path
    raise InvalidWorkspace("either workspace or session_id is required")


@router.post("/rag/index")
async def index_workspace(
    body: IndexRequest, manager: SessionManager = Depends(get_manager)
) -> dict:
    """(Re)index a workspace. Rebuilds wholesale rather than incrementally."""
    workspace = _workspace_for(manager, body.workspace, body.session_id)
    stats = await manager.rag.index(workspace)
    return {"workspace": str(workspace), **stats.to_dict()}


@router.post("/rag/query")
async def query_index(
    body: QueryRequest, manager: SessionManager = Depends(get_manager)
) -> dict:
    """Retrieve relevant chunks. Same call the planner makes."""
    workspace = _workspace_for(manager, body.workspace, body.session_id)
    matches = await manager.rag.query(workspace, body.query, body.limit)
    return {
        "workspace": str(workspace),
        "query": body.query,
        "matches": [match.to_dict() for match in matches],
    }


@router.get("/rag/status")
async def index_status(
    workspace: str | None = None,
    session_id: str | None = None,
    manager: SessionManager = Depends(get_manager),
) -> dict:
    """What is indexed, and what is doing the indexing."""
    resolved = _workspace_for(manager, workspace, session_id)
    return {"workspace": str(resolved), **await manager.rag.stats(resolved)}
