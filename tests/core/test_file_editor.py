from __future__ import annotations

import pytest
from sani_core.permissions import ActionType
from sani_core.plan import PlanStep
from sani_core.tools.base import ToolError
from sani_core.tools.file_editor import FileEditorTool, looks_like_secret


def step(op: str, path: str, **params) -> PlanStep:
    return PlanStep(index=0, description=op, tool="file_editor",
                    params={"op": op, "path": path, **params})


@pytest.fixture
def tool(tmp_path):
    (tmp_path / "README.md").write_text("# hi\n")
    return FileEditorTool(tmp_path)


def test_ordinary_operations_classify_by_operation(tool):
    assert tool.propose(step("read", "README.md")).action_type is ActionType.FILE_READ
    assert tool.propose(step("write", "new.py", content="x")).action_type is ActionType.FILE_WRITE
    assert tool.propose(step("delete", "README.md")).action_type is ActionType.FILE_DELETE


@pytest.mark.parametrize(
    "path",
    ["../outside.txt", "../../etc/passwd", "/etc/passwd", "sub/../../outside.txt"],
)
def test_paths_that_escape_the_workspace_are_flagged(tool, path):
    action = tool.propose(step("write", path, content="x"))
    assert action.action_type is ActionType.PATH_OUTSIDE_WORKSPACE


def test_a_symlink_pointing_outside_is_resolved_and_flagged(tool, tmp_path):
    outside = tmp_path.parent / "target.txt"
    outside.write_text("secret\n")
    (tmp_path / "link.txt").symlink_to(outside)

    action = tool.propose(step("write", "link.txt", content="x"))
    assert action.action_type is ActionType.PATH_OUTSIDE_WORKSPACE


@pytest.mark.parametrize(
    "path",
    [".env", ".env.local", "config/.env", "secrets.yaml", "app/credentials.json",
     ".ssh/id_rsa", "certs/server.pem", "gcp-service_account.json"],
)
def test_credential_paths_are_recognised(path):
    assert looks_like_secret(path) is True


@pytest.mark.parametrize("path", ["environment.py", "src/secretive_ui.tsx", "readme.pem.md"])
def test_ordinary_paths_are_not_mistaken_for_credentials(path):
    assert looks_like_secret(path) is False


def test_reading_a_secret_is_gated_too(tool, tmp_path):
    """Wider than the spec: piping a credential into a model context is as
    irreversible as writing one, so reads are gated as well as writes."""
    (tmp_path / ".env").write_text("API_KEY=abc\n")
    assert tool.propose(step("read", ".env")).action_type is ActionType.SECRET_ACCESS
    assert tool.propose(step("write", ".env", content="x")).action_type is ActionType.SECRET_ACCESS


def test_escaping_beats_secret_classification(tool):
    """Both gate, but the label should name the more fundamental violation."""
    action = tool.propose(step("write", "../.env", content="x"))
    assert action.action_type is ActionType.PATH_OUTSIDE_WORKSPACE


def test_propose_is_side_effect_free(tool, tmp_path):
    tool.propose(step("write", "created.py", content="x"))
    tool.propose(step("delete", "README.md"))
    assert not (tmp_path / "created.py").exists()
    assert (tmp_path / "README.md").exists()


def test_a_write_proposal_carries_the_diff_for_the_approval_preview(tool):
    action = tool.propose(step("write", "README.md", content="# hi\nmore\n"))
    assert action.diff is not None
    assert action.preview["hunks"] == 1
    assert any(line.startswith("+more") for line in action.diff.hunks[0].lines)


async def test_write_creates_parent_directories(tool, tmp_path):
    action = tool.propose(step("write", "deep/nested/f.py", content="x\n"))
    tool.result(action, await tool.execute(action))
    assert (tmp_path / "deep/nested/f.py").read_text() == "x\n"


async def test_reading_a_missing_file_is_a_tool_error(tool):
    action = tool.propose(step("read", "nope.txt"))
    with pytest.raises(ToolError):
        await tool.execute(action)


async def test_deleting_an_absent_file_reports_honestly(tool):
    action = tool.propose(step("delete", "nope.txt"))
    result = tool.result(action, await tool.execute(action))
    assert result.ok is True
    assert result.data["deleted"] is False


def test_a_missing_path_param_is_rejected(tool):
    with pytest.raises(ToolError, match="requires a 'path'"):
        tool.propose(PlanStep(index=0, description="x", tool="file_editor", params={"op": "read"}))
