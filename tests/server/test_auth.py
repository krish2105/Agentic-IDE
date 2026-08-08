"""Bearer-token authentication.

The property that matters most here is coverage: an auth layer that guards the
HTTP routes and misses the WebSockets leaves ``/terminal`` -- a shell -- open to
anyone. Every one of these tests exists to stop that regressing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sani_server.app import create_app
from sani_server.auth import AUTH_TOKEN_ENV_VAR, WS_UNAUTHORIZED
from sani_server.manager import SessionManager
from starlette.websockets import WebSocketDisconnect

TOKEN = "s3cret-token-value"
WRONG = "s3cret-token-valuf"  # one character off, to exercise the comparison


@pytest.fixture
def secured(monkeypatch, workspace):
    monkeypatch.setenv(AUTH_TOKEN_ENV_VAR, TOKEN)
    with TestClient(create_app(SessionManager())) as client:
        yield client


@pytest.fixture
def session_id(secured, workspace):
    response = secured.post(
        "/session",
        json={"task": "auth check", "workspace": str(workspace), "script": []},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 201
    return response.json()["session_id"]


# ---- discovery --------------------------------------------------------------


def test_health_is_public_and_says_auth_is_on(secured):
    """A client must be able to tell "no token needed" from "token was wrong"."""
    body = secured.get("/healthz").json()
    assert body["auth"] == {"required": True, "scheme": "bearer"}


def test_health_says_auth_is_off_when_no_token_is_configured(client):
    assert client.get("/healthz").json()["auth"]["required"] is False


def test_without_a_token_the_server_is_open(client, workspace):
    """Unset means open, so existing localhost workflows are untouched."""
    assert client.get("/mission-control").status_code == 200


# ---- HTTP -------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/mission-control"),
        ("get", "/session/ses_x"),
        ("post", "/session"),
        ("post", "/rag/index"),
    ],
)
def test_http_routes_refuse_an_unauthenticated_caller(secured, method, path):
    kwargs = {"json": {}} if method == "post" else {}
    response = getattr(secured, method)(path, **kwargs)
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
    assert response.headers["www-authenticate"].startswith("Bearer")


def test_a_wrong_token_is_refused(secured):
    response = secured.get("/mission-control", headers={"Authorization": f"Bearer {WRONG}"})
    assert response.status_code == 401


def test_a_malformed_header_is_refused(secured):
    for value in ("", "Bearer", f"Basic {TOKEN}", TOKEN):
        response = secured.get("/mission-control", headers={"Authorization": value})
        assert response.status_code == 401, value


def test_the_right_token_gets_through(secured):
    response = secured.get("/mission-control", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200


def test_a_cors_preflight_is_not_blocked(secured):
    """Preflights carry no credentials; refusing them turns a 401 into an
    opaque CORS error the user cannot diagnose."""
    response = secured.options(
        "/session",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200


# ---- WebSockets: the part a naive implementation misses ---------------------


def test_the_event_stream_refuses_an_unauthenticated_socket(secured, session_id):
    with pytest.raises(WebSocketDisconnect) as caught:
        with secured.websocket_connect(f"/session/{session_id}/stream") as ws:
            ws.receive_json()
    assert caught.value.code == WS_UNAUTHORIZED


def test_the_terminal_refuses_an_unauthenticated_socket(secured, session_id):
    """This one is a shell. It must never be reachable without a token."""
    with pytest.raises(WebSocketDisconnect) as caught:
        with secured.websocket_connect(f"/session/{session_id}/terminal") as ws:
            ws.receive_json()
    assert caught.value.code == WS_UNAUTHORIZED


def test_a_wrong_token_on_a_socket_is_refused(secured, session_id):
    with pytest.raises(WebSocketDisconnect) as caught:
        with secured.websocket_connect(
            f"/session/{session_id}/stream?token={WRONG}"
        ) as ws:
            ws.receive_json()
    assert caught.value.code == WS_UNAUTHORIZED


def test_a_token_in_the_query_string_authenticates_a_socket(secured, session_id):
    """Browsers cannot set headers on a WebSocket handshake, so this is the
    only mechanism available to the web client."""
    with secured.websocket_connect(f"/session/{session_id}/stream?token={TOKEN}") as ws:
        assert ws.receive_json()["type"] == "session.status"


def test_the_token_coexists_with_from_seq(secured, session_id):
    with secured.websocket_connect(
        f"/session/{session_id}/stream?from_seq=0&token={TOKEN}"
    ) as ws:
        assert ws.receive_json()["seq"] == 1


def test_an_authenticated_terminal_still_works(secured, session_id):
    with secured.websocket_connect(f"/session/{session_id}/terminal?token={TOKEN}") as ws:
        assert ws.receive_json()["type"] == "ready"
