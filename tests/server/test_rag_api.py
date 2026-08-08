"""Phase 3: the RAG endpoints, and retrieval reaching the planner."""

from __future__ import annotations

import pytest

from .helpers import first, read_until, start_session, types

AUTH_SOURCE = '''\
"""Permission checks."""


def check_permission(action, ladder):
    """Decide whether an action needs approval."""
    if action in ALWAYS_CONFIRM:
        return True
    return not ladder.auto_approve
'''


@pytest.fixture
def repo(workspace):
    (workspace / "auth.py").write_text(AUTH_SOURCE)
    (workspace / "plotting.py").write_text(
        "import matplotlib.pyplot as plt\n\n\ndef draw_scatter(x, y):\n    plt.scatter(x, y)\n"
    )
    return workspace


def test_index_then_query_a_workspace(client, repo):
    indexed = client.post("/rag/index", json={"workspace": str(repo)}).json()
    assert indexed["files"] >= 2
    assert indexed["chunks"] >= 2
    assert indexed["workspace"] == str(repo)

    body = client.post(
        "/rag/query",
        json={"workspace": str(repo), "query": "decide whether an action needs approval"},
    ).json()

    assert body["matches"], "expected the permission code back"
    top = body["matches"][0]
    assert top["path"] == "auth.py"
    assert top["name"] == "check_permission"
    assert 0 < top["score"] <= 1
    assert "ALWAYS_CONFIRM" in top["text"]


def test_status_reports_what_is_indexing(client, repo):
    client.post("/rag/index", json={"workspace": str(repo)})
    status = client.get("/rag/status", params={"workspace": str(repo)}).json()

    assert status["indexed"] is True
    assert status["chunks"] > 0
    assert status["embedder"]["name"] == "hashing"
    # The default embedder is lexical; the API must not imply otherwise.
    assert status["embedder"]["semantic"] is False
    assert status["store"]["kind"] == "memory"


def test_a_workspace_can_be_named_by_session(client, repo):
    session_id = start_session(client, repo, [])
    indexed = client.post("/rag/index", json={"session_id": session_id}).json()
    assert indexed["workspace"] == str(repo)

    body = client.post(
        "/rag/query", json={"session_id": session_id, "query": "scatter plot"}
    ).json()
    assert body["matches"][0]["path"] == "plotting.py"


def test_querying_an_unindexed_workspace_is_empty_not_an_error(client, repo):
    body = client.post(
        "/rag/query", json={"workspace": str(repo), "query": "anything at all"}
    ).json()
    assert body["matches"] == []


def test_bad_targets_are_rejected(client, tmp_path):
    missing = client.post("/rag/index", json={"workspace": str(tmp_path / "nope")})
    assert missing.status_code == 400
    assert missing.json()["error"] == "invalid_workspace"

    neither = client.post("/rag/index", json={})
    assert neither.status_code == 400

    unknown_session = client.post("/rag/query", json={"session_id": "ses_x", "query": "q"})
    assert unknown_session.status_code == 404


def test_an_indexed_workspace_feeds_the_planner_and_says_so(client, repo):
    """Retrieval that silently steers a plan is the opacity the gate exists to stop."""
    client.post("/rag/index", json={"workspace": str(repo)})

    session_id = start_session(
        client, repo, [], task="update how we decide if an action needs approval"
    )
    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "session.complete")

    assert "rag.retrieved" in types(events), "retrieval must be disclosed to the client"
    retrieved = first(events, "rag.retrieved")["data"]
    assert retrieved["chars"] > 0
    assert any("auth.py" in label for label in retrieved["chunks"])

    # Disclosed before the plan, not after it.
    order = types(events)
    assert order.index("rag.retrieved") < order.index("plan.proposed")


def test_a_session_without_an_index_plans_normally_and_stays_quiet(client, workspace):
    session_id = start_session(client, workspace, [])
    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "session.complete")

    assert "rag.retrieved" not in types(events)
    assert types(events)[-1] == "session.complete"


def test_healthz_advertises_the_new_event_type(client):
    assert "rag.retrieved" in client.get("/healthz").json()["event_types"]
