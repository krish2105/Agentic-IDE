"""Browser adapter (spec Phase 3c).

The point of the Tool Adapter interface is that this needed no executor
changes: propose / execute / result, same as the file editor and the shell. A
browser session is not a separate system, it is a session with a different
adapter -- which is the architectural claim the whole three-stretch-features
argument rests on.

Verification is DOM-based and deterministic. Vision-model screenshot
interpretation is the part of Section 3c that depends on free-tier quota, so it
sits behind the LiteLLM backend and is not covered by tests; screenshots are
always captured as artifacts either way.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..actions import ProposedAction, ToolResult
from ..permissions import ActionType
from ..plan import PlanStep
from .base import ToolAdapter, ToolError

#: Where screenshots land, relative to the workspace. Inside the workspace on
#: purpose: the file API already serves it and the file tree already shows it,
#: so an artifact is something the user can find rather than something buried
#: in a temp directory they never look in.
ARTIFACT_DIR = ".sani/artifacts"

BROWSER_EXECUTABLE_ENV_VAR = "SANI_BROWSER_EXECUTABLE"

#: Playwright's bundled download can mismatch the browser actually installed.
#: These are checked in order when no executable is configured.
FALLBACK_EXECUTABLES = (
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium/chrome-linux/chrome",
)

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", ""})

DEFAULT_TIMEOUT_MS = 15_000
VIEWPORT = {"width": 1280, "height": 800}

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def is_local_url(url: str) -> bool:
    """Whether a URL stays on this machine.

    ``file:`` counts as local; a bare path with no scheme is treated as local
    because the agent means a relative page, not a remote host.
    """
    parsed = urlparse(url)
    if parsed.scheme in ("", "file"):
        return True
    if parsed.scheme not in ("http", "https"):
        return False
    return (parsed.hostname or "") in LOCAL_HOSTS


def classify(op: str, params: dict[str, Any]) -> ActionType:
    if op == "goto" and not is_local_url(str(params.get("url", ""))):
        return ActionType.BROWSER_NAVIGATE_EXTERNAL
    return ActionType.BROWSER_ACTION


def resolve_executable() -> str | None:
    configured = os.environ.get(BROWSER_EXECUTABLE_ENV_VAR)
    if configured:
        return configured
    for candidate in FALLBACK_EXECUTABLES:
        if os.path.exists(candidate):
            return candidate
    return None  # let Playwright use its own download


class BrowserTool(ToolAdapter):
    name = "browser"

    def __init__(self, workspace, *, runner=None, headless: bool = True) -> None:
        super().__init__(workspace, runner=runner)
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._page = None
        self._shots = 0

    # ---- lifecycle -------------------------------------------------------

    async def _ensure_page(self):
        if self._page is not None:
            return self._page
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - optional extra
            raise ToolError(
                "the browser tool requires the browser extra: uv sync --extra browser"
            ) from exc

        self._playwright = await async_playwright().start()
        launch: dict[str, Any] = {"headless": self.headless}
        executable = resolve_executable()
        if executable:
            launch["executable_path"] = executable

        try:
            self._browser = await self._playwright.chromium.launch(**launch)
        except Exception as exc:
            await self.aclose()
            raise ToolError(f"could not start a browser: {exc}") from exc

        self._page = await self._browser.new_page(viewport=VIEWPORT)
        self._page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        return self._page

    async def aclose(self) -> None:
        """Release the browser. The executor calls this when a session ends."""
        for closer in (self._browser, self._playwright):
            if closer is None:
                continue
            try:
                await (closer.close() if closer is self._browser else closer.stop())
            except Exception:
                pass
        self._playwright = self._browser = self._page = None

    # ---- adapter ---------------------------------------------------------

    def propose(self, step: PlanStep) -> ProposedAction:
        op = step.params.get("op")
        if not op:
            raise ToolError(f"step {step.index}: browser requires an 'op' param")

        summaries = {
            "goto": lambda p: f"Open {p.get('url')}",
            "click": lambda p: f"Click {p.get('selector')}",
            "fill": lambda p: f"Type into {p.get('selector')}",
            "assert_text": lambda p: f"Check the page shows {p.get('text')!r}",
            "screenshot": lambda p: f"Screenshot {p.get('name', 'page')}",
            "text": lambda p: f"Read text from {p.get('selector', 'body')}",
        }
        if op not in summaries:
            raise ToolError(f"unsupported browser op {op!r} (have {sorted(summaries)})")

        action_type = classify(op, step.params)
        return ProposedAction(
            action_type=action_type,
            tool=self.name,
            summary=summaries[op](step.params),
            step_index=step.index,
            payload=dict(step.params),
            preview={
                **{k: v for k, v in step.params.items() if k != "op"},
                "op": op,
                "classified_as": action_type.value,
                "leaves_this_machine": action_type is ActionType.BROWSER_NAVIGATE_EXTERNAL,
            },
        )

    async def execute(self, action: ProposedAction, *, hunk_ids: list[str] | None = None) -> Any:
        page = await self._ensure_page()
        params = action.payload
        op = params["op"]

        try:
            if op == "goto":
                response = await page.goto(str(params["url"]))
                return {"url": page.url, "status": response.status if response else None}

            if op == "click":
                await page.click(str(params["selector"]))
                return {"url": page.url}

            if op == "fill":
                await page.fill(str(params["selector"]), str(params.get("text", "")))
                return {"url": page.url}

            if op == "text":
                selector = str(params.get("selector", "body"))
                return {"text": await page.inner_text(selector), "selector": selector}

            if op == "assert_text":
                expected = str(params["text"])
                body = await page.inner_text(str(params.get("selector", "body")))
                return {"expected": expected, "found": expected in body, "body": body[:2000]}

            if op == "screenshot":
                return {"screenshot": await self._screenshot(page, params.get("name"))}
        except ToolError:
            raise
        except Exception as exc:
            # A selector that does not match is a failed step, not a crashed
            # session -- the plan continues and the result says what happened.
            return {"error": f"{type(exc).__name__}: {str(exc).splitlines()[0]}"}

        raise ToolError(f"unsupported browser op {op!r}")

    async def _screenshot(self, page, name: str | None) -> str:
        self._shots += 1
        safe = _UNSAFE_NAME.sub("-", name or f"shot-{self._shots}").strip("-")
        target = self.workspace / ARTIFACT_DIR / f"{self._shots:02d}-{safe}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(target), full_page=True)
        return str(target.relative_to(self.workspace))

    def result(self, action: ProposedAction, raw: Any) -> ToolResult:
        op = action.payload["op"]

        if isinstance(raw, dict) and raw.get("error"):
            return ToolResult(
                ok=False,
                summary=f"Browser {op} failed: {raw['error']}",
                data={"op": op, **raw},
            )

        if op == "assert_text":
            found = bool(raw["found"])
            return ToolResult(
                ok=found,
                summary=(
                    f"Page shows {raw['expected']!r}"
                    if found
                    else f"Page does not show {raw['expected']!r}"
                ),
                output=raw["body"],
                data={"op": op, "expected": raw["expected"], "found": found},
            )

        if op == "screenshot":
            return ToolResult(
                ok=True,
                summary=f"Captured {raw['screenshot']}",
                data={"op": op, "artifact": raw["screenshot"], "kind": "image"},
            )

        if op == "text":
            return ToolResult(
                ok=True,
                summary=f"Read {len(raw['text'])} chars from {raw['selector']}",
                output=raw["text"],
                data={"op": op, "selector": raw["selector"]},
            )

        return ToolResult(
            ok=True,
            summary=f"{action.summary} — now at {raw.get('url')}",
            data={"op": op, **raw},
        )
