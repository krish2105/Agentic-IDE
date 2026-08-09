"""Parallel agent race.

N agents, one task, isolated git worktrees, keep the best answer. The
differentiator is not the parallelism -- Cursor ships that -- it is that every
racer runs behind the same approval gate and risk scoring as a solo session, so
parallelism cannot become a way to launder autonomy past the gate.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed"
)


@pytest.fixture
def git_workspace(tmp_path):
    """A real git repo, because worktrees need one."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Demo\n")
    (repo / "scratch.tmp").write_text("left over\n")

    run = lambda *args: subprocess.run(  # noqa: E731
        ["git", *args], cwd=repo, check=True, capture_output=True
    )
    run("init", "-b", "main")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    run("add", "-A")
    run("commit", "-m", "initial")
    return repo


def test_a_race_creates_one_isolated_worktree_per_racer(client, git_workspace):
    response = client.post(
        "/race", json={"task": "add a greeting", "workspace": str(git_workspace), "count": 3}
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert len(body["racers"]) == 3
    worktrees = {racer["worktree"] for racer in body["racers"]}
    assert len(worktrees) == 3, "each racer needs its own directory"

    branches = {racer["branch"] for racer in body["racers"]}
    assert len(branches) == 3
    assert all(branch.startswith("sani/race-") for branch in branches)

    client.post(f"/race/{body['race_id']}/discard", json={})


def test_racers_cannot_see_each_others_workspace(client, git_workspace):
    body = client.post(
        "/race", json={"task": "t", "workspace": str(git_workspace), "count": 2}
    ).json()

    first, second = body["racers"]
    assert first["worktree"] != second["worktree"]
    # And neither is the user's real repository.
    assert str(git_workspace) not in (first["worktree"], second["worktree"])

    client.post(f"/race/{body['race_id']}/discard", json={})


def test_a_workspace_without_git_is_refused_plainly(client, workspace):
    """Silently degrading to something that looks like it worked would be the
    worse failure: the user would think their agents were isolated."""
    response = client.post(
        "/race", json={"task": "t", "workspace": str(workspace), "count": 2}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "race_unavailable"
    assert "git repository" in response.json()["detail"]


def test_a_race_needs_at_least_two_racers(client, git_workspace):
    response = client.post(
        "/race", json={"task": "t", "workspace": str(git_workspace), "count": 1}
    )
    assert response.status_code == 422


def test_the_racer_count_is_capped(client, git_workspace):
    response = client.post(
        "/race", json={"task": "t", "workspace": str(git_workspace), "count": 99}
    )
    assert response.status_code == 422


def test_the_board_reports_progress_per_racer(client, git_workspace):
    body = client.post(
        "/race", json={"task": "t", "workspace": str(git_workspace), "count": 2}
    ).json()

    board = client.get(f"/race/{body['race_id']}").json()
    assert board["race_id"] == body["race_id"]
    assert len(board["racers"]) == 2
    for racer in board["racers"]:
        for key in ("session_id", "label", "status", "files_changed", "elapsed_s"):
            assert key in racer

    client.post(f"/race/{body['race_id']}/discard", json={})


def test_an_unknown_race_is_404(client):
    assert client.get("/race/race_nope").status_code == 404


def test_discarding_records_the_kept_racer_without_merging_it(client, git_workspace):
    """Merging a winner back is a history-touching operation with real blast
    radius. It belongs behind the approval gate, not as a side effect of
    closing a dialog."""
    body = client.post(
        "/race", json={"task": "t", "workspace": str(git_workspace), "count": 2}
    ).json()
    keep = body["racers"][0]["label"]

    result = client.post(f"/race/{body['race_id']}/discard", json={"keep": keep}).json()
    assert result["kept"] == keep
    assert result["kept_branch"].startswith("sani/race-")
    # The branch still exists in the source repo for the human to merge.
    branches = subprocess.run(
        ["git", "branch", "--list"], cwd=git_workspace, capture_output=True, text=True
    ).stdout
    assert result["kept_branch"] in branches


def test_discarding_with_no_winner_cleans_up_entirely(client, git_workspace):
    body = client.post(
        "/race", json={"task": "t", "workspace": str(git_workspace), "count": 2}
    ).json()

    client.post(f"/race/{body['race_id']}/discard", json={})
    assert client.get(f"/race/{body['race_id']}").status_code == 404

    remaining = subprocess.run(
        ["git", "worktree", "list"], cwd=git_workspace, capture_output=True, text=True
    ).stdout
    assert "sani-race-" not in remaining


def test_races_are_listed(client, git_workspace):
    body = client.post(
        "/race", json={"task": "t", "workspace": str(git_workspace), "count": 2}
    ).json()

    listing = client.get("/race").json()
    assert any(race["race_id"] == body["race_id"] for race in listing["races"])

    client.post(f"/race/{body['race_id']}/discard", json={})


def test_every_racer_is_a_real_session_under_the_same_gate(client, git_workspace):
    """The differentiator: parallelism does not bypass the approval model."""
    body = client.post(
        "/race", json={"task": "t", "workspace": str(git_workspace), "count": 2}
    ).json()

    for racer in body["racers"]:
        session = client.get(f"/session/{racer['session_id']}").json()
        # The always-confirm tier is intact inside a racer's session.
        assert session["trust"]["file.delete"]["always_confirm"] is True
        assert session["trust"]["file.delete"]["auto_approve"] is False

    client.post(f"/race/{body['race_id']}/discard", json={})
