"""Phase 3c: the browser subagent, driving a real Chromium.

The adapter is only interesting if it is genuinely the same shape as the other
tools, so these tests go through propose / execute / result rather than calling
Playwright directly.
"""

from __future__ import annotations

import http.server
import threading
from functools import partial

import pytest
from sani_core.permissions import ALWAYS_CONFIRM, ActionType, TrustLadder, evaluate
from sani_core.plan import PlanStep
from sani_core.tools import build_tools
from sani_core.tools.base import ToolError
from sani_core.tools.browser import BrowserTool, classify, is_local_url

PAGE = """<!doctype html>
<html><body>
  <h1 id="title">Sani Studio</h1>
  <p class="status">all systems nominal</p>
  <input id="name" />
  <button id="go" onclick="document.getElementById('out').textContent='clicked ' + document.getElementById('name').value">go</button>
  <div id="out"></div>
</body></html>
"""

playwright = pytest.importorskip("playwright.async_api", reason="playwright not installed")


def step(op: str, **params) -> PlanStep:
    return PlanStep(index=0, description=op, tool="browser", params={"op": op, **params})


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """A real page over real HTTP, so navigation is not a file:// special case."""
    root = tmp_path_factory.mktemp("site")
    (root / "index.html").write_text(PAGE)

    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    server.shutdown()


@pytest.fixture
async def tool(tmp_path):
    browser = BrowserTool(tmp_path)
    yield browser
    await browser.aclose()


# ---- classification (no browser needed) -------------------------------------


@pytest.mark.parametrize(
    "url,local",
    [
        ("http://localhost:3000/app", True),
        ("http://127.0.0.1:8000", True),
        ("file:///tmp/page.html", True),
        ("relative/page.html", True),
        ("https://example.com", False),
        ("http://10.0.0.5/internal", False),
    ],
)
def test_local_and_remote_urls_are_told_apart(url, local):
    assert is_local_url(url) is local


def test_navigating_off_this_machine_is_always_confirm():
    """Same blast radius as curl: it reaches the network and can act remotely."""
    external = classify("goto", {"url": "https://example.com"})
    assert external is ActionType.BROWSER_NAVIGATE_EXTERNAL
    assert external in ALWAYS_CONFIRM
    assert evaluate(external, TrustLadder()).requires_approval is True


def test_local_interaction_is_gated_but_can_earn_trust():
    local = classify("click", {"selector": "#go"})
    assert local is ActionType.BROWSER_ACTION
    assert local not in ALWAYS_CONFIRM

    ladder = TrustLadder()
    assert evaluate(local, ladder).requires_approval is True
    for _ in range(3):
        ladder.record_manual_approval(local)
    assert evaluate(local, ladder).requires_approval is False


def test_the_browser_is_just_another_adapter(tmp_path):
    tools = build_tools(["file_editor", "shell", "browser"], tmp_path)
    assert set(tools) == {"file_editor", "shell", "browser"}
    for adapter in tools.values():
        assert hasattr(adapter, "propose")
        assert hasattr(adapter, "execute")
        assert hasattr(adapter, "result")


def test_propose_is_side_effect_free_and_says_where_it_goes(tmp_path):
    browser = BrowserTool(tmp_path)
    action = browser.propose(step("goto", url="https://example.com"))
    assert action.preview["leaves_this_machine"] is True
    assert browser._page is None, "propose must not start a browser"

    local = browser.propose(step("goto", url="http://localhost:3000"))
    assert local.preview["leaves_this_machine"] is False


def test_unsupported_and_missing_ops_are_rejected(tmp_path):
    browser = BrowserTool(tmp_path)
    with pytest.raises(ToolError, match="requires an 'op'"):
        browser.propose(PlanStep(index=0, description="x", tool="browser", params={}))
    with pytest.raises(ToolError, match="unsupported browser op"):
        browser.propose(step("hack_the_planet"))


# ---- a real browser ---------------------------------------------------------


async def test_it_opens_a_page_and_reads_it(tool, site):
    action = tool.propose(step("goto", url=site))
    result = tool.result(action, await tool.execute(action))
    assert result.ok is True
    assert result.data["status"] == 200

    read = tool.propose(step("text", selector="#title"))
    text = tool.result(read, await tool.execute(read))
    assert text.output.strip() == "Sani Studio"


async def test_it_fills_clicks_and_verifies_the_result(tool, site):
    """The self-correct loop needs a real assertion, not a screenshot to squint at."""
    for action_step in (
        step("goto", url=site),
        step("fill", selector="#name", text="Krishna"),
        step("click", selector="#go"),
    ):
        action = tool.propose(action_step)
        assert tool.result(action, await tool.execute(action)).ok is True

    check = tool.propose(step("assert_text", text="clicked Krishna"))
    assert tool.result(check, await tool.execute(check)).ok is True


async def test_a_failed_assertion_reports_rather_than_passing(tool, site):
    goto = tool.propose(step("goto", url=site))
    await tool.execute(goto)

    check = tool.propose(step("assert_text", text="text that is not on the page"))
    result = tool.result(check, await tool.execute(check))
    assert result.ok is False
    assert "does not show" in result.summary


async def test_a_bad_selector_fails_the_step_not_the_session(tool, site):
    goto = tool.propose(step("goto", url=site))
    await tool.execute(goto)

    click = tool.propose(step("click", selector="#does-not-exist"))
    result = tool.result(click, await tool.execute(click))
    assert result.ok is False
    assert "failed" in result.summary.lower()


async def test_screenshots_land_in_the_workspace_as_artifacts(tool, site, tmp_path):
    goto = tool.propose(step("goto", url=site))
    await tool.execute(goto)

    shot = tool.propose(step("screenshot", name="landing page"))
    result = tool.result(shot, await tool.execute(shot))

    assert result.ok is True
    assert result.data["kind"] == "image"
    artifact = tmp_path / result.data["artifact"]
    assert artifact.exists()
    assert artifact.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    # Inside the workspace, so the file tree and the file API already show it.
    assert artifact.is_relative_to(tmp_path)


async def test_closing_twice_is_safe(tmp_path, site):
    browser = BrowserTool(tmp_path)
    action = browser.propose(step("goto", url=site))
    await browser.execute(action)
    await browser.aclose()
    await browser.aclose()
    assert browser._page is None
