"""The plan -> approve -> execute loop (spec Section 8).

Everything the clients see is emitted from here. Two ordering rules are
deliberate and load-bearing:

1. ``tool.proposed`` fires for *every* action, including auto-approved ones.
   That is the "tool-call disclosure at the decision point" the spec identifies
   as the winning agentic UX pattern -- the user sees what is about to happen
   even when they are not being asked to allow it.
2. ``approval.resolved`` also fires for auto-approved actions, with
   ``auto: true``. Clients then have one code path for "an action was cleared"
   rather than two.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from .actions import ProposedAction
from .approvals import ApprovalRegistry
from .context import estimate_tokens
from .events import Event, EventType
from .models.base import ModelAdapter
from .permissions import evaluate
from .plan import PlanStep, StepStatus
from .risk import assess
from .session import AgentSession, SessionStatus
from .tools.base import ToolAdapter, ToolError, UnknownTool

EmitFn = Callable[[Event], Awaitable[None]]

#: Given a task, return relevant source from the codebase index plus the labels
#: of what it found. Empty labels mean "nothing matched" -- indistinguishable
#: from "no index", and both mean plan without it.
Retriever = Callable[[str], Awaitable[tuple[str, list[str]]]]


class _Killed(Exception):
    """Internal control-flow signal for ``kill()``. Never surfaces to clients."""


class Executor:
    def __init__(
        self,
        session: AgentSession,
        *,
        tools: dict[str, ToolAdapter],
        model: ModelAdapter,
        emit: EmitFn,
        registry: ApprovalRegistry | None = None,
        retriever: Retriever | None = None,
    ) -> None:
        self.session = session
        self.tools = tools
        self.model = model
        self.registry = registry or ApprovalRegistry()
        self.retriever = retriever
        self._emit_fn = emit
        self._resume = asyncio.Event()
        self._resume.set()
        self._killed = False

    # ---- lifecycle control, driven by the /pause /resume /kill endpoints ----

    def pause(self) -> None:
        """Take effect at the next step boundary; a running tool call finishes."""
        self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    def kill(self) -> None:
        self._killed = True
        self.registry.abandon_all()
        self._resume.set()

    @property
    def paused_requested(self) -> bool:
        return not self._resume.is_set()

    # ---- emit helpers ----

    async def _emit(self, event_type: EventType, data: dict) -> None:
        await self._emit_fn(Event(type=event_type, session_id=self.session.id, data=data))

    async def _set_status(self, status: SessionStatus, **extra) -> None:
        self.session.status = status
        await self._emit(EventType.SESSION_STATUS, {"status": status.value, **extra})

    async def _emit_delta(self, text: str) -> None:
        await self._emit(EventType.AGENT_MESSAGE_DELTA, {"text": text})

    # ---- main loop ----

    async def run(self) -> None:
        try:
            await self._set_status(SessionStatus.PLANNING)

            context = ""
            if self.retriever is not None:
                context, labels = await self.retriever(self.session.task)
                if labels:
                    # Disclose what the agent read before it planned. Retrieval
                    # silently steering a plan is the same opacity problem the
                    # approval gate exists to solve.
                    await self._emit(
                        EventType.RAG_RETRIEVED,
                        {"chunks": labels, "chars": len(context)},
                    )

            plan = await self.model.plan(
                self.session.task, self.session.workspace, self._emit_delta, context
            )
            self.session.plan = plan
            self.session.context.add(self.session.task + plan.rationale)
            # The planner's prompt is input, its rationale is output. Both are
            # estimated until a backend hands back real usage numbers, and the
            # meter records that so the total is never shown as exact.
            self.session.cost.model = self.model.model_name
            self.session.cost.record(
                input_tokens=estimate_tokens(self.session.task + context),
                output_tokens=estimate_tokens(plan.rationale),
                estimated=True,
            )
            await self._emit(EventType.AGENT_MESSAGE_DONE, {"text": plan.rationale})
            await self._emit(EventType.PLAN_PROPOSED, {"plan": plan.to_dict()})

            await self._checkpoint()
            await self._set_status(SessionStatus.EXECUTING)

            for step in plan.steps:
                await self._checkpoint()
                self.session.current_step = step.index
                step.status = StepStatus.RUNNING
                await self._emit(EventType.PLAN_STEP_STARTED, {"step": step.to_dict()})

                try:
                    await self._run_step(step)
                except ToolError as exc:
                    # A tool that *raises* must fail its step, not the session.
                    # The graceful path below only ever covered a tool that
                    # returned an unsuccessful result -- so a plan whose first
                    # step read a filename the model guessed wrong threw away
                    # every valid step after it. The failure is still reported
                    # as a tool.result: a step that quietly disappears is worse
                    # than one that failed loudly.
                    step.status = StepStatus.FAILED
                    step.detail = str(exc)
                    await self._emit(
                        EventType.TOOL_RESULT,
                        {
                            "action_id": None,
                            "step_index": step.index,
                            "result": {
                                "ok": False,
                                "summary": str(exc),
                                "output": "",
                                "data": {},
                                "diff": None,
                            },
                        },
                    )

                await self._emit(EventType.PLAN_STEP_COMPLETED, {"step": step.to_dict()})
                # Cost rides along with the token meter rather than getting its
                # own event: they are the same measurement, and splitting them
                # would let a client show tokens and spend from different moments.
                await self._emit(
                    EventType.CONTEXT_USAGE,
                    {
                        **self.session.context.to_dict(),
                        "model": self.model.model_name,
                        "cost": self.session.cost.to_dict(),
                    },
                )

            self.session.current_step = None
            await self._finish(SessionStatus.COMPLETE)

        except _Killed:
            self._mark_remaining_skipped()
            await self._finish(SessionStatus.KILLED)
        except asyncio.CancelledError:
            self._mark_remaining_skipped()
            await self._finish(SessionStatus.KILLED)
            raise
        except Exception as exc:
            self.session.error = f"{type(exc).__name__}: {exc}"
            self._mark_remaining_skipped()
            await self._finish(SessionStatus.FAILED)

    async def _checkpoint(self) -> None:
        if self._killed:
            raise _Killed
        if not self._resume.is_set():
            await self._set_status(SessionStatus.PAUSED)
            await self._resume.wait()
            if self._killed:
                raise _Killed
            await self._set_status(SessionStatus.EXECUTING)

    async def _run_step(self, step: PlanStep) -> None:
        tool = self.tools.get(step.tool)
        if tool is None:
            # Structural, not runtime: this fails the session, because every
            # step using that tool would fail identically and the useful signal
            # is "your tool configuration is wrong".
            raise UnknownTool(
                f"step {step.index} requests unknown tool {step.tool!r} "
                f"(session has {sorted(self.tools)})"
            )

        action = tool.propose(step)
        await self._emit(
            EventType.TOOL_PROPOSED, {"action": action.to_dict(), "step_index": step.index}
        )

        hunk_ids = await self._gate(action, step)
        if step.status is StepStatus.REJECTED:
            return

        raw = await tool.execute(action, hunk_ids=hunk_ids)
        result = tool.result(action, raw)

        if result.diff is not None and (result.diff.hunks or result.diff.is_delete):
            self.session.record_diff(result.diff)
            await self._emit(
                EventType.DIFF_GENERATED,
                {"diff": result.diff.to_dict(), "step_index": step.index},
            )

        await self._emit(
            EventType.TOOL_RESULT,
            {"action_id": action.id, "step_index": step.index, "result": result.to_dict()},
        )

        self.session.context.add(result.output)
        self.session.history.append(
            {"step": step.index, "action": action.summary, "ok": result.ok}
        )
        # A failing tool call is data, not a crash: the step is marked failed and
        # the plan continues. Self-correction on failure is a later phase.
        step.status = StepStatus.COMPLETE if result.ok else StepStatus.FAILED
        step.detail = result.summary

    async def _gate(self, action: ProposedAction, step: PlanStep) -> list[str] | None:
        """Run the action past the permission engine. Returns approved hunk ids."""
        decision = evaluate(action.action_type, self.session.trust)

        if not decision.requires_approval:
            await self._emit(
                EventType.APPROVAL_RESOLVED,
                {
                    "action_id": action.id,
                    "approved": True,
                    "auto": True,
                    "hunk_ids": None,
                    "note": decision.reason,
                },
            )
            return None

        pending = self.registry.create(action)
        self.session.pending_action = action

        # Blast radius, computed before anything runs. Advisory only: it informs
        # the human decision and never gates, widens the always-confirm tier, or
        # auto-approves. Emitted first so a client can render the stakes and the
        # request together rather than popping a score in afterwards.
        await self._emit(
            EventType.RISK_ASSESSED,
            {"action_id": action.id, "risk": assess(action).to_dict()},
        )

        await self._emit(
            EventType.APPROVAL_REQUIRED,
            {
                "action": action.to_dict(),
                "decision": decision.to_dict(),
                "step_index": step.index,
            },
        )
        await self._set_status(
            SessionStatus.BLOCKED_ON_APPROVAL, pending_action_id=action.id
        )

        outcome = await pending.future
        self.session.pending_action = None
        await self._emit(
            EventType.APPROVAL_RESOLVED, {"action_id": action.id, **outcome.to_dict()}
        )

        if self._killed:
            raise _Killed

        await self._set_status(SessionStatus.EXECUTING)

        if not outcome.approved:
            self.session.trust.record_rejection(action.action_type)
            step.status = StepStatus.REJECTED
            step.detail = outcome.note or "rejected by user"
            return None

        self.session.trust.record_manual_approval(action.action_type)
        return outcome.hunk_ids

    def _mark_remaining_skipped(self) -> None:
        if not self.session.plan:
            return
        for step in self.session.plan.steps:
            if step.status in (StepStatus.PENDING, StepStatus.RUNNING):
                step.status = StepStatus.SKIPPED

    async def _close_tools(self) -> None:
        for tool in self.tools.values():
            try:
                await tool.aclose()
            except Exception:
                # Teardown failures must not change how a session ended.
                pass

    async def _finish(self, status: SessionStatus) -> None:
        await self._close_tools()
        self.session.status = status
        self.session.ended_at = time.time()
        self.session.pending_action = None

        if status is SessionStatus.FAILED:
            await self._emit(
                EventType.SESSION_ERROR,
                {"status": status.value, "error": self.session.error},
            )
        else:
            # COMPLETE and KILLED both end the stream. Clients close on either.
            await self._emit(
                EventType.SESSION_COMPLETE,
                {
                    "status": status.value,
                    "elapsed_s": self.session.elapsed_s,
                    "diffs": [d.to_dict() for d in self.session.diffs.values()],
                },
            )
