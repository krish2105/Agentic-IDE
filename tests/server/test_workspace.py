"""File tree and editor file access."""

from __future__ import annotations

import pytest

from .helpers import start_session


@pytest.fixture
def session_id(client, workspace):
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_text("print('hi')\n")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "junk.js").write_text("// noise\n")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "config").write_text("[core]\n")
    return start_session(client, workspace, [])


def test_file_tree_lists_directories_first_and_skips_noise(client, session_id):
    body = client.get(f"/session/{session_id}/files").json()
    paths = [e["path"] for e in body["entries"]]

    assert "src" in paths
    assert "src/app.py" in paths
    assert "README.md" in paths
    # Vendored and VCS directories are never worth showing.
    assert not any(p.startswith("node_modules") for p in paths)
    assert not any(p.startswith(".git") for p in paths)

    assert paths.index("src") < paths.index("src/app.py")
    src_entry = next(e for e in body["entries"] if e["path"] == "src")
    assert src_entry["type"] == "dir" and src_entry["size"] is None


def test_reading_a_file_returns_its_contents(client, session_id):
    body = client.get(f"/session/{session_id}/file", params={"path": "src/app.py"}).json()
    assert body["content"] == "print('hi')\n"
    assert body["binary"] is False
    assert body["size"] == 12


def test_saving_a_file_writes_it_to_disk(client, session_id, workspace):
    response = client.put(
        f"/session/{session_id}/file",
        json={"path": "src/app.py", "content": "print('edited')\n"},
    )
    assert response.status_code == 200
    assert response.json()["saved"] is True
    assert (workspace / "src" / "app.py").read_text() == "print('edited')\n"


def test_saving_creates_missing_directories(client, session_id, workspace):
    client.put(
        f"/session/{session_id}/file",
        json={"path": "deep/nested/new.py", "content": "x = 1\n"},
    )
    assert (workspace / "deep" / "nested" / "new.py").read_text() == "x = 1\n"


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "src/../../escape.txt"])
def test_the_file_api_refuses_to_escape_the_workspace(client, session_id, path):
    """A human clicking it is not a reason to serve a file from outside."""
    assert client.get(f"/session/{session_id}/file", params={"path": path}).status_code == 403

    write = client.put(
        f"/session/{session_id}/file", json={"path": path, "content": "pwned"}
    )
    assert write.status_code == 403
    assert write.json()["error"] == "outside_workspace"


def test_a_symlink_escape_is_refused_too(client, session_id, workspace, tmp_path):
    outside = tmp_path.parent / "linked_secret.txt"
    outside.write_text("secret\n")
    (workspace / "innocent.txt").symlink_to(outside)

    response = client.get(f"/session/{session_id}/file", params={"path": "innocent.txt"})
    assert response.status_code == 403
    assert outside.read_text() == "secret\n"


def test_binary_files_are_flagged_rather_than_streamed(client, session_id, workspace):
    (workspace / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")
    body = client.get(f"/session/{session_id}/file", params={"path": "logo.png"}).json()
    assert body["binary"] is True
    assert body["content"] is None


def test_reading_a_directory_or_missing_file_is_an_error(client, session_id):
    assert client.get(f"/session/{session_id}/file", params={"path": "src"}).status_code == 409
    assert client.get(
        f"/session/{session_id}/file", params={"path": "nope.py"}
    ).status_code == 409


def test_workspace_endpoints_404_for_an_unknown_session(client):
    assert client.get("/session/ses_nope/files").status_code == 404
    assert client.get("/session/ses_nope/file", params={"path": "a"}).status_code == 404


def test_the_agent_and_the_editor_see_the_same_file(client, session_id, workspace):
    """The tree reflects what the agent wrote, without a restart."""
    (workspace / "agent_made_this.py").write_text("# from the agent\n")

    paths = [e["path"] for e in client.get(f"/session/{session_id}/files").json()["entries"]]
    assert "agent_made_this.py" in paths

    body = client.get(
        f"/session/{session_id}/file", params={"path": "agent_made_this.py"}
    ).json()
    assert body["content"] == "# from the agent\n"
