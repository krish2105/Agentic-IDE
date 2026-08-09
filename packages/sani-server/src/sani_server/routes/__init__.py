from . import (
    approvals,
    diff,
    lifecycle,
    mission_control,
    provenance,
    race,
    rag,
    sessions,
    stream,
    terminal,
    timeline,
    trust,
    workspace,
)

ROUTERS = [
    sessions.router,
    stream.router,
    approvals.router,
    lifecycle.router,
    diff.router,
    trust.router,
    mission_control.router,
    workspace.router,
    terminal.router,
    rag.router,
    timeline.router,
    provenance.router,
    race.router,
]

__all__ = ["ROUTERS"]
