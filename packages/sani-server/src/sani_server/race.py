"""Parallel agent race: N agents, one task, keep the best answer.

This is the feature Cursor leads with. The difference here is what surrounds it:
every racer runs behind the same approval gate and the same risk scoring as a
solo session, so parallelism does not become a way to launder autonomy past the
thing that makes this product trustworthy.

Each racer gets its own git worktree, so they cannot see each other's edits and
the loser's changes are discarded by deleting a directory rather than by
unpicking a merge.

Deliberately *not* implemented: automatic winner selection. Choosing which
solution is best is the judgement the human is here to make, and a product whose
whole argument is "keep the human in the loop" should not quietly pick for them.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .manager import SessionManager
from .worktrees import WorktreeError, WorktreePool

#: Racing more than this is almost always a mistake: each racer is a full
#: session with its own sandbox and model calls, and reviewing eight divergent
#: solutions costs more human attention than it saves.
MAX_RACERS = 6


def new_race_id() -> str:
    return f"race_{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class Racer:
    session_id: str
    worktree: str
    branch: str
    label: str


@dataclass(slots=True)
class Race:
    id: str
    task: str
    source_workspace: str
    racers: list[Racer] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    pool: WorktreePool | None = None

    def to_dict(self, manager: SessionManager) -> dict[str, Any]:
        entries = []
        for racer in self.racers:
            try:
                session = manager.get(racer.session_id).session
                entries.append(
                    {
                        "session_id": racer.session_id,
                        "label": racer.label,
                        "branch": racer.branch,
                        "worktree": racer.worktree,
                        "status": session.status.value,
                        "current_step": session.current_step,
                        "total_steps": len(session.plan.steps) if session.plan else 0,
                        "elapsed_s": session.elapsed_s,
                        "approval_needed": session.pending_action is not None,
                        "files_changed": len(session.diffs),
                        "cost": session.cost.to_dict(),
                    }
                )
            except Exception:
                # A racer whose session was killed or reaped still belongs in
                # the board; dropping it would make the race look smaller than
                # it was.
                entries.append(
                    {
                        "session_id": racer.session_id,
                        "label": racer.label,
                        "branch": racer.branch,
                        "worktree": racer.worktree,
                        "status": "unknown",
                        "current_step": None,
                        "total_steps": 0,
                        "elapsed_s": 0.0,
                        "approval_needed": False,
                        "files_changed": 0,
                        "cost": None,
                    }
                )

        finished = {"complete", "failed", "killed"}
        return {
            "race_id": self.id,
            "task": self.task,
            "source_workspace": self.source_workspace,
            "created_at": self.created_at,
            "racers": entries,
            "running": sum(1 for e in entries if e["status"] not in finished),
            "awaiting_approval": sum(1 for e in entries if e["approval_needed"]),
        }


class RaceCoordinator:
    """Owns every race in this process."""

    def __init__(self, manager: SessionManager) -> None:
        self.manager = manager
        self._races: dict[str, Race] = {}

    def get(self, race_id: str) -> Race:
        race = self._races.get(race_id)
        if race is None:
            raise KeyError(race_id)
        return race

    def list(self) -> list[Race]:
        return list(self._races.values())

    async def start(
        self,
        *,
        task: str,
        workspace: str,
        count: int,
        model_backend: str | None = None,
        script: list[dict[str, Any]] | None = None,
    ) -> Race:
        if count < 2:
            raise WorktreeError("a race needs at least two racers")
        if count > MAX_RACERS:
            raise WorktreeError(f"at most {MAX_RACERS} racers (asked for {count})")

        source = Path(workspace).resolve()
        pool = WorktreePool(source)
        race = Race(
            id=new_race_id(), task=task, source_workspace=str(source), pool=pool
        )

        try:
            for index in range(count):
                label = chr(ord("a") + index)
                worktree = await pool.add(label)
                record = self.manager.create(
                    task=task,
                    workspace=str(worktree.path),
                    model_backend=model_backend,
                    script=script,
                )
                race.racers.append(
                    Racer(
                        session_id=record.session.id,
                        worktree=str(worktree.path),
                        branch=worktree.branch,
                        label=label,
                    )
                )
        except Exception:
            # A half-built race is worse than none: it leaves worktrees behind
            # and shows a board that does not match what is running.
            await self._abandon(race)
            raise

        self._races[race.id] = race
        return race

    async def _abandon(self, race: Race) -> None:
        for racer in race.racers:
            try:
                await self.manager.kill(racer.session_id)
            except Exception:
                pass
        if race.pool is not None:
            await race.pool.cleanup()

    async def discard(self, race_id: str, keep: str | None = None) -> dict[str, Any]:
        """End a race, optionally naming the racer whose work you kept.

        The losers are killed and their worktrees removed. The winner's worktree
        is deliberately **left in place**, because that is where its work
        actually is: the agent edits files in the working directory and does not
        commit them, so the branch tip does not contain the change. Removing the
        winner's worktree would delete the very thing the user chose to keep.

        Merging is still not done for you -- that is a history-touching
        operation and belongs behind the approval gate rather than happening as
        a side effect of closing a dialog.
        """
        race = self.get(race_id)
        kept = next((r for r in race.racers if r.label == keep or r.session_id == keep), None)

        for racer in race.racers:
            if kept is not None and racer.session_id == kept.session_id:
                continue
            try:
                await self.manager.kill(racer.session_id)
            except Exception:
                pass
            # Drop the loser's worktree and branch: leaving them behind means a
            # user's repository accumulates sani/race-* refs forever.
            if race.pool is not None:
                worktree = next(
                    (w for w in race.pool.worktrees if str(w.path) == racer.worktree), None
                )
                if worktree is not None:
                    await race.pool.remove(worktree)

        result = {
            "race_id": race_id,
            "kept": kept.label if kept else None,
            "kept_worktree": kept.worktree if kept else None,
            "kept_branch": kept.branch if kept else None,
            # The honest bit: the work is uncommitted in the worktree, not on
            # the branch. Telling the user to "merge the branch" would send them
            # to an empty ref.
            "work_is_uncommitted": kept is not None,
        }

        if kept is None and race.pool is not None:
            await race.pool.cleanup()

        self._races.pop(race_id, None)
        return result

    async def shutdown(self) -> None:
        await asyncio.gather(
            *(self._abandon(race) for race in self._races.values()),
            return_exceptions=True,
        )
        self._races.clear()
