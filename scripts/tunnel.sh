#!/usr/bin/env bash
#
# Expose the local server over HTTPS, and make its URL easy to paste.
#
# A quick Cloudflare tunnel gets a *new random hostname every restart*, and the
# web IDE stores whichever one you last gave it. So the normal failure is not a
# broken tunnel — it is a live tunnel plus a stale URL in the browser, which
# shows as "Cannot reach https://<old-name>.trycloudflare.com" and looks like
# the server is down when it is fine.
#
# This prints the URL prominently and copies it to the clipboard, so the paste
# into "Change connection" is a ⌘V rather than a transcription.
#
# HTTPS is not optional: the Vercel page is HTTPS and a browser blocks
# plain-http requests from it as mixed content.
#
# Usage:
#   scripts/tunnel.sh            # tunnels port 8060
#   PORT=8000 scripts/tunnel.sh

set -euo pipefail

PORT="${PORT:-8060}"
LOG="$(mktemp -t sani-tunnel)"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "error: cloudflared is not installed. brew install cloudflared" >&2
  exit 1
fi

# Fail early if nothing is listening: a tunnel to a closed port resolves and
# then 502s, which is a slower and less obvious way to learn the same thing.
if ! curl -sf -o /dev/null --max-time 5 "http://127.0.0.1:$PORT/healthz"; then
  echo "error: nothing is serving http://127.0.0.1:$PORT — start it with scripts/serve.sh" >&2
  exit 1
fi

# Refuse to expose an unauthenticated server.
#
# serve.sh already refuses SANI_NO_AUTH=1 while a tunnel is up, but that check
# only fires at *its* startup — start the server first and the tunnel second and
# nothing objected, which is exactly what happened: an open server with a shell
# tool, reachable from the internet, and no warning anywhere. The guard has to
# exist at both ends because either order is a plausible thing to do.
AUTH_REQUIRED="$(curl -sf --max-time 5 "http://127.0.0.1:$PORT/healthz" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("auth",{}).get("required"))' 2>/dev/null || echo unknown)"
if [ "$AUTH_REQUIRED" != "True" ]; then
  echo "error: the server on :$PORT has authentication OFF (auth.required=$AUTH_REQUIRED)." >&2
  echo >&2
  echo "  Tunnelling it would put an unauthenticated server on the public internet," >&2
  echo "  and its shell tool executes commands. Restart it with a token:" >&2
  echo >&2
  echo "      kill \$(lsof -ti tcp:$PORT) && ./scripts/serve.sh" >&2
  echo >&2
  echo "  SANI_NO_AUTH=1 is for the local-only setup: web IDE on localhost, no tunnel." >&2
  exit 1
fi

echo "starting tunnel to :$PORT …"
cloudflared tunnel --url "http://127.0.0.1:$PORT" > "$LOG" 2>&1 &
TUNNEL_PID=$!
trap 'kill "$TUNNEL_PID" 2>/dev/null || true' EXIT

URL=""
for _ in $(seq 1 40); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 1
done

if [ -z "$URL" ]; then
  echo "error: cloudflared did not report a URL. Its log:" >&2
  tail -20 "$LOG" >&2
  exit 1
fi

# Deliberately does NOT touch the clipboard.
#
# The web IDE needs two values pasted seconds apart — this URL and the auth
# token — and only one clipboard exists. Copying the URL here means the next ⌘V
# puts a URL in the token field, which produces 401s indistinguishable from a
# stale token and costs an hour. The URL is human-readable and can be copied off
# the screen; the token is opaque and cannot. So the clipboard is reserved for
# the token, and the token copy is the last thing you do.
TOKEN_FILE="${SANI_DIR:-$HOME/.sani}/auth-token"

cat <<BANNER

  ┌─────────────────────────────────────────────────────────────────────┐
     $URL
  └─────────────────────────────────────────────────────────────────────┘

  In the web IDE, "Change connection":

    1. SERVER URL  — the address above (select it here and copy)
    2. AUTH TOKEN  — run this, THEN paste, so the clipboard holds the token
                     and not the URL:

           tr -d '\\n' < $TOKEN_FILE | pbcopy

    3. Save and reconnect

  The clipboard is left alone on purpose: two values, one clipboard, and a
  URL in the token field is the single most confusing failure here.

  This hostname dies when this process does. Leave it running.

BANNER

wait "$TUNNEL_PID"
