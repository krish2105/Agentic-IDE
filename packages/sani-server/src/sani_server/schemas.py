"""Request and response models for the Section 7 API contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    task: str = Field(min_length=1, description="What the agent should accomplish")
    workspace: str | None = Field(
        default=None,
        description="Absolute path the session may operate in. A temp dir is created if omitted.",
    )
    tools: list[str] | None = Field(
        default=None, description="Tool adapters to attach. Defaults to file_editor + shell."
    )
    lifecycle: Literal["foreground", "background"] = "foreground"
    model_backend: Literal["scripted", "litellm"] | None = Field(
        default=None, description="Overrides SANI_MODEL_BACKEND for this session."
    )
    trust_overrides: dict[str, bool] | None = Field(
        default=None,
        description=(
            "Initial auto-approve state per action type, applied before the session "
            "starts. Rejected with 400 for always-confirm action types."
        ),
    )
    script: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Fixed plan for the scripted backend. Test and demo affordance only; "
            "ignored when the backend is litellm."
        ),
    )


class ApproveRequest(BaseModel):
    action_id: str
    hunk_ids: list[str] | None = Field(
        default=None,
        description=(
            "Per-hunk accept. Omit to accept the whole action; pass a subset of "
            "hunk ids to apply only those. An empty list accepts nothing."
        ),
    )
    note: str | None = None


class RejectRequest(BaseModel):
    action_id: str
    reason: str | None = None


class TrustPatchRequest(BaseModel):
    action_type: str
    auto_approve: bool


class ErrorResponse(BaseModel):
    error: str
    detail: str
