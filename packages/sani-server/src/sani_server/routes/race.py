"""Parallel agent race endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..deps import get_manager
from ..manager import SessionManager
from ..race import MAX_RACERS, RaceCoordinator

router = APIRouter(tags=["race"])


class StartRaceBody(BaseModel):
    task: str
    workspace: str
    count: int = Field(default=2, ge=2, le=MAX_RACERS)
    model_backend: str | None = None
    script: list[dict] | None = None


class DiscardBody(BaseModel):
    #: Racer label ("a") or session id. Recorded, not merged -- see race.py.
    keep: str | None = None


def _coordinator(request: Request) -> RaceCoordinator:
    return request.app.state.races


@router.post("/race", status_code=201)
async def start_race(
    body: StartRaceBody,
    request: Request,
    manager: SessionManager = Depends(get_manager),
) -> dict:
    # WorktreeError propagates to the app-level handler, which renders the
    # project's standard {"error": slug, "detail": message} shape.
    race = await _coordinator(request).start(
        task=body.task,
        workspace=body.workspace,
        count=body.count,
        model_backend=body.model_backend,
        script=body.script,
    )
    return race.to_dict(manager)


@router.get("/race")
async def list_races(
    request: Request, manager: SessionManager = Depends(get_manager)
) -> dict:
    coordinator = _coordinator(request)
    return {"races": [race.to_dict(manager) for race in coordinator.list()]}


@router.get("/race/{race_id}")
async def get_race(
    race_id: str, request: Request, manager: SessionManager = Depends(get_manager)
) -> dict:
    try:
        race = _coordinator(request).get(race_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail={"error": "unknown_race", "detail": race_id}
        ) from exc
    return race.to_dict(manager)


@router.post("/race/{race_id}/discard")
async def discard_race(
    race_id: str, body: DiscardBody, request: Request
) -> dict:
    try:
        return await _coordinator(request).discard(race_id, keep=body.keep)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail={"error": "unknown_race", "detail": race_id}
        ) from exc
