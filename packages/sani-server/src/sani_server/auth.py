"""Bearer-token authentication.

Until now the server had none, which is why the honest advice was "localhost
only". This is what makes a hosted frontend talking to a tunnelled backend a
defensible arrangement rather than publishing remote code execution.

Two design points worth stating:

**It is pure ASGI middleware, not an HTTP dependency.** FastAPI dependencies and
``BaseHTTPMiddleware`` never see WebSocket connections. Guarding only the HTTP
routes would leave ``/stream`` and ``/terminal`` open -- and ``/terminal`` is a
shell. Anything that authenticates this server has to cover both, so this sits
below the protocol split where it cannot miss one.

**Unset means open.** Existing localhost workflows keep working untouched; the
token is opt-in. ``/healthz`` reports which mode is active so a client can tell
the difference between "no token needed" and "your token was wrong".
"""

from __future__ import annotations

import hmac
import os

from starlette.types import ASGIApp, Receive, Scope, Send

AUTH_TOKEN_ENV_VAR = "SANI_AUTH_TOKEN"

#: Reachable without a token. Only the health probe: it carries no session data
#: and clients need it to discover whether auth is even on.
PUBLIC_PATHS = frozenset({"/healthz"})

#: Close code for an unauthenticated WebSocket. 4401 mirrors HTTP 401 in the
#: application-defined range.
WS_UNAUTHORIZED = 4401


def configured_token() -> str | None:
    token = os.environ.get(AUTH_TOKEN_ENV_VAR, "").strip()
    return token or None


def describe_auth() -> dict:
    return {"required": configured_token() is not None, "scheme": "bearer"}


def _presented_token(scope: Scope) -> str | None:
    """Pull a token from the header, or the query string for WebSockets.

    Browsers cannot set headers on a WebSocket handshake, so ``?token=`` is the
    only option there. That does put the token in URLs and therefore in access
    logs, which is a real downside -- but the alternative is leaving the
    terminal unauthenticated, and that is not a trade worth making.
    """
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
    authorization = headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()

    if scope["type"] == "websocket":
        from urllib.parse import parse_qs

        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        values = query.get("token")
        if values:
            return values[0]
    return None


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        expected = configured_token()
        if expected is None:
            await self.app(scope, receive, send)
            return

        # A CORS preflight carries no credentials by design; rejecting it would
        # make the browser report an opaque CORS failure instead of a 401.
        if scope["type"] == "http" and scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        if scope.get("path") in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        presented = _presented_token(scope)
        if presented is not None and hmac.compare_digest(presented, expected):
            await self.app(scope, receive, send)
            return

        await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            # Accept-then-close would look like a working socket that hung up.
            # Closing during the handshake is the honest signal.
            await send({"type": "websocket.close", "code": WS_UNAUTHORIZED})
            return

        body = b'{"error":"unauthorized","detail":"a valid bearer token is required"}'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b'Bearer realm="sani"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
