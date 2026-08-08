"""The event protocol every Sani' Studio client consumes.

This module is the contract. Both the VS Code extension and the Web IDE render
these events and nothing else, so changes here are breaking changes for every
surface at once. Bump PROTOCOL_VERSION when the envelope shape changes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

PROTOCOL_VERSION = 1


class EventType(str, Enum):
    SESSION_STATUS = "session.status"
    RAG_RETRIEVED = "rag.retrieved"
    PLAN_PROPOSED = "plan.proposed"
    PLAN_STEP_STARTED = "plan.step.started"
    PLAN_STEP_COMPLETED = "plan.step.completed"
    AGENT_MESSAGE_DELTA = "agent.message.delta"
    AGENT_MESSAGE_DONE = "agent.message.done"
    TOOL_PROPOSED = "tool.proposed"
    APPROVAL_REQUIRED = "approval.required"
    APPROVAL_RESOLVED = "approval.resolved"
    TOOL_RESULT = "tool.result"
    DIFF_GENERATED = "diff.generated"
    CONTEXT_USAGE = "context.usage"
    SESSION_COMPLETE = "session.complete"
    SESSION_ERROR = "session.error"


#: Events after which no further events can arrive for a session. The hub uses
#: this to close subscriber sockets cleanly instead of leaving them hanging.
TERMINAL_EVENTS = frozenset({EventType.SESSION_COMPLETE, EventType.SESSION_ERROR})


@dataclass(slots=True)
class Event:
    """One frame on the wire.

    ``seq`` is stamped by the transport's event log, not by the emitter, so it
    is monotonic per session with no gaps. Clients reconnect with
    ``?from_seq=N`` and replay from there.
    """

    type: EventType
    session_id: str
    data: dict[str, Any] = field(default_factory=dict)
    seq: int = 0
    ts: float = field(default_factory=time.time)
    v: int = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": self.v,
            "seq": self.seq,
            "session_id": self.session_id,
            "ts": self.ts,
            "type": self.type.value,
            "data": self.data,
        }

    @property
    def is_terminal(self) -> bool:
        return self.type in TERMINAL_EVENTS
