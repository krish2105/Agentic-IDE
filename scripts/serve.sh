#!/usr/bin/env bash
#
# Start the server the way it actually gets run, with the secrets kept out of
# both the shell history and the process list where possible.
#
# Everything here was previously reassembled by hand on every restart, and each
# piece has a failure mode that does not look like its cause:
#
#   * No token  -> a tunnelled server is an unauthenticated remote shell.
#   * Wrong CORS -> the WebSocket still connects, so the plan renders while
#     every fetch is blocked. Looks like three broken components, not a config
#     error.
#   * No GROQ_API_KEY -> the scripted planner replays a fixed demo plan and
#     ignores what you asked for. Nothing errors; you just get someone else's
#     three steps.
#
# Secrets live in files under ~/.sani rather than in this script or your rc
# files:
#
#   ~/.sani/auth-token   generated on first run if absent
#   ~/.sani/groq-key     you create this; without it the backend is `scripted`
#
# Usage:
#   scripts/serve.sh                       # port 8060, local origins
#   PORT=8000 scripts/serve.sh
#   EXTRA_ORIGINS=https://foo.vercel.app scripts/serve.sh

set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${PORT:-8060}"
SANI_DIR="${SANI_DIR:-$HOME/.sani}"
TOKEN_FILE="$SANI_DIR/auth-token"
GROQ_FILE="$SANI_DIR/groq-key"

mkdir -p "$SANI_DIR"
chmod 700 "$SANI_DIR"

# --- is the port free? ------------------------------------------------------
# uvicorn's own failure here is `[Errno 48] address already in use`, printed
# *after* a successful-looking startup banner and immediately followed by
# "Application shutdown complete" — so it reads like the server started and then
# stopped for some unrelated reason. It also never says who holds the port,
# which is the only thing you need to know.
# `|| true` is load-bearing: lsof exits 1 when nothing matches, which under
# `set -e` + `pipefail` kills this script with no output at all — i.e. the check
# added to make a busy port obvious would instead make a *free* port fail
# silently. Exactly the class of bug this script exists to prevent.
HOLDER="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $2; exit}' || true)"
if [ -n "$HOLDER" ]; then
  # Match against the *full* command line and truncate only for display: this
  # repo's path is long enough that `sani_server` sits past any sane cut point,
  # so testing the shortened string mislabels our own server as a stranger.
  HOLDER_CMD="$(ps -o command= -p "$HOLDER" 2>/dev/null || true)"
  echo "error: port $PORT is already in use by PID $HOLDER" >&2
  echo "         $(printf '%s' "$HOLDER_CMD" | cut -c1-100)" >&2
  echo >&2
  if printf '%s' "$HOLDER_CMD" | grep -q "sani_server"; then
    echo "  That is another Ṣāni' server. Stop it and rerun:" >&2
    echo "      kill $HOLDER" >&2
    echo "  ...or run a second one elsewhere:  PORT=8070 $0" >&2
  else
    echo "  That is not a Ṣāni' server, so pick another port:" >&2
    echo "      PORT=8070 $0" >&2
  fi
  exit 1
fi

# --- the venv ---------------------------------------------------------------
# Called directly rather than through `uv run`, which re-syncs on every
# invocation. See the UF_HIDDEN note in CLAUDE.md: if imports fail, check
# `ls -lO .venv` before touching the environment.
if [ ! -x ./.venv/bin/uvicorn ]; then
  echo "error: ./.venv/bin/uvicorn is missing. Run: uv sync --extra litellm" >&2
  exit 1
fi

# --- auth -------------------------------------------------------------------
if [ ! -f "$TOKEN_FILE" ]; then
  umask 077
  python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
  echo "generated a new auth token at $TOKEN_FILE"
fi
SANI_AUTH_TOKEN="$(tr -d '\n' < "$TOKEN_FILE")"
export SANI_AUTH_TOKEN

# --- model backend ----------------------------------------------------------
# The key's presence decides this. Defaulting to `scripted` when it is absent is
# deliberate: the suite must stay reproducible with no API key, and a server
# that silently failed every plan would be worse than one that replays a demo.
if [ -s "$GROQ_FILE" ]; then
  GROQ_API_KEY="$(tr -d '\n' < "$GROQ_FILE")"
  export GROQ_API_KEY
  export SANI_MODEL_BACKEND=litellm
  export SANI_MODEL="${SANI_MODEL:-groq/llama-3.3-70b-versatile}"
  BACKEND_NOTE="litellm · $SANI_MODEL"
else
  export SANI_MODEL_BACKEND=scripted
  BACKEND_NOTE="scripted — replays a fixed demo plan and IGNORES your task.
             Put a Groq key in $GROQ_FILE for real inference:
               umask 077; printf %s 'gsk_...' > $GROQ_FILE"
fi

# --- CORS -------------------------------------------------------------------
ORIGINS="http://localhost:3000,http://127.0.0.1:3000,http://localhost:3200,http://127.0.0.1:3200"
if [ -n "${EXTRA_ORIGINS:-}" ]; then
  ORIGINS="$EXTRA_ORIGINS,$ORIGINS"
fi
export SANI_CORS_ORIGINS="$ORIGINS"

# --- go ---------------------------------------------------------------------
cat <<BANNER
Ṣāni' server
  port      : $PORT (loopback only — expose it with a tunnel, never --host 0.0.0.0)
  auth      : on, token in $TOKEN_FILE
  backend   : $BACKEND_NOTE
  origins   : $SANI_CORS_ORIGINS

BANNER

exec ./.venv/bin/uvicorn sani_server.app:app --host 127.0.0.1 --port "$PORT"
