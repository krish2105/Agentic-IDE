"""Plan and step models.

A plan is produced up front and streamed to the client *before* anything runs
(spec Section 8, step 3). Steps carry only intent; the tool adapter turns a step
into a concrete proposed action at execution time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    REJECTED = "rejected"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class PlanStep:
    index: int
    description: str
    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    detail: str | None = None

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "description": self.description,
            "tool": self.tool,
            "params": self.params,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass(slots=True)
class Plan:
    task: str
    steps: list[PlanStep] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "rationale": self.rationale,
            "steps": [s.to_dict() for s in self.steps],
        }
