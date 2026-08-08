from . import (
    approvals,
    diff,
    lifecycle,
    mission_control,
    sessions,
    stream,
    terminal,
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
]

__all__ = ["ROUTERS"]
