"""GET /provenance -- git blame for AI.

Attribution is derived from the diffs the agent already emitted rather than
tracked in a parallel bookkeeping structure. That means it cannot disagree with
the diff history: the diffs *are* the record, and this is a projection of them.

Per-workspace rather than per-session, for the same reason the RAG index is:
several sessions edit one repo over time, and the question a reviewer asks is
about the repo, not about one run.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sani_core.provenance import Attribution, WorkspaceProvenance

from ..deps import get_manager
from ..manager import SessionManager

router = APIRouter(tags=["provenance"])


def _added_line_indices(diff: dict) -> tuple[list[int], int]:
    """Which new-file line numbers this diff added, and how far the file runs.

    Hunks carry their own new-file start, so the indices come straight from the
    opcode geometry rather than from re-parsing the unified text.
    """
    indices: list[int] = []
    highest = 0

    for hunk in diff.get("hunks", []):
        cursor = hunk.get("new_start", 0)
        for line in hunk.get("lines", []):
            if line.startswith("+"):
                indices.append(cursor)
                cursor += 1
            elif line.startswith("-"):
                continue
            else:
                cursor += 1
        highest = max(highest, cursor)

    return indices, highest


@router.get("/provenance")
async def get_provenance(
    workspace: str | None = Query(None, description="Absolute workspace path."),
    session_id: str | None = Query(None, description="Use this session's workspace."),
    manager: SessionManager = Depends(get_manager),
) -> dict:
    if session_id:
        workspace = str(manager.get(session_id).session.workspace)
    if not workspace:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_workspace", "detail": "workspace or session_id required"},
        )

    root = str(Path(workspace).resolve())
    provenance = WorkspaceProvenance()

    # Fold every diff every session produced against this workspace, oldest
    # first, so a later write correctly overwrites an earlier attribution.
    records = sorted(manager.list(), key=lambda record: record.session.created_at)
    for record in records:
        if str(Path(record.session.workspace).resolve()) != root:
            continue

        attribution_base = Attribution(
            session_id=record.session.id,
            model=record.session.cost.model,
            at=record.session.created_at,
        )

        for path, diff in record.session.diffs.items():
            payload = diff if isinstance(diff, dict) else diff.to_dict()
            indices, total = _added_line_indices(payload)
            if not indices:
                continue
            provenance.file(path).record_agent_lines(
                indices, attribution_base, total_lines=total
            )

    return {"workspace": root, **provenance.to_dict()}
