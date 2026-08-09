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
#   SANI_NO_AUTH=1 scripts/serve.sh    # local only: no token, no tunnel allowed

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
# `SANI_NO_AUTH=1` for the local-only setup: server on loopback, web IDE on
# localhost, no tunnel. There is nothing to authenticate against a socket only
# this machine can open, and requiring a token there costs two clipboard pastes
# that have to be redone on every rotation -- which is the single largest source
# of friction in getting this running, and every failure it causes looks like a
# broken server.
#
# It is refused the moment a tunnel is up, because then the token is the only
# thing between the internet and a shell.
if [ "${SANI_NO_AUTH:-}" = "1" ]; then
  if pgrep -f "cloudflared tunnel" >/dev/null 2>&1; then
    echo "error: SANI_NO_AUTH=1 but a cloudflared tunnel is running." >&2
    echo "         An open tunnel to an unauthenticated server is a remote shell." >&2
    echo "         Stop the tunnel, or drop SANI_NO_AUTH." >&2
    exit 1
  fi
  unset SANI_AUTH_TOKEN
  AUTH_NOTE="OFF — loopback only, no token needed by the browser.
             Do NOT start a tunnel while this is running."
else
  if [ ! -f "$TOKEN_FILE" ]; then
    umask 077
    python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    echo "generated a new auth token at $TOKEN_FILE"
  fi
  SANI_AUTH_TOKEN="$(tr -d '\n' < "$TOKEN_FILE")"
  export SANI_AUTH_TOKEN
  AUTH_NOTE="on, token in $TOKEN_FILE"
fi

# --- model backend ----------------------------------------------------------
# The key's presence decides this. Defaulting to `scripted` when it is absent is
# deliberate: the suite must stay reproducible with no API key, and a server
# that silently failed every plan would be worse than one that replays a demo.
# An explicit SANI_MODEL_BACKEND wins over inference from the key file. Running
# the test suites needs the scripted planner even on a machine that has a Groq
# key, and without this the only way to get it was to move the key file aside.
if [ "${SANI_MODEL_BACKEND:-}" = "scripted" ]; then
  export SANI_MODEL_BACKEND=scripted
  BACKEND_NOTE="scripted (forced by SANI_MODEL_BACKEND) — fixed demo plan, ignores your task"
elif [ -s "$GROQ_FILE" ]; then
  GROQ_API_KEY="$(tr -d '\n' < "$GROQ_FILE")"

  # Reject the placeholder from the instructions. Pasting the example verbatim is
  # an easy slip, and the consequence is silent until you run a session: the
  # banner cheerfully says `litellm` and then every plan dies on "Invalid API
  # Key". A refusal here costs a second and says exactly what to do.
  case "$GROQ_API_KEY" in
    gsk_your_real_key|gsk_...|*your_real_key*|*YOUR_KEY*|*gsk_\.\.\.*)
      echo "error: $GROQ_FILE contains the placeholder from the docs, not a key." >&2
      echo "         Replace 'gsk_your_real_key' with your actual key from" >&2
      echo "         https://console.groq.com/keys :" >&2
      echo >&2
      echo "           umask 077; printf %s 'gsk_ACTUAL_KEY_HERE' > $GROQ_FILE" >&2
      echo >&2
      echo "         Or delete the file to run on the scripted backend:  rm $GROQ_FILE" >&2
      exit 1
      ;;
  esac

  # Verify it before serving. Otherwise the first sign of a bad key is a failed
  # session several clicks later, which looks like a bug in the agent rather than
  # a credential problem. A network failure is not treated as a bad key -- being
  # offline should not stop the server from starting.
  KEY_CHECK="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
    -H "Authorization: Bearer $GROQ_API_KEY" \
    https://api.groq.com/openai/v1/models 2>/dev/null || echo 000)"
  case "$KEY_CHECK" in
    200) KEY_NOTE="key verified against Groq" ;;
    401|403)
      echo "error: Groq rejected the key in $GROQ_FILE (HTTP $KEY_CHECK)." >&2
      echo "         Get a fresh one at https://console.groq.com/keys, then:" >&2
      echo "           umask 077; printf %s 'gsk_...' > $GROQ_FILE" >&2
      exit 1
      ;;
    000) KEY_NOTE="key NOT verified — could not reach Groq (offline?)" ;;
    *)   KEY_NOTE="key check returned HTTP $KEY_CHECK — proceeding anyway" ;;
  esac

  export GROQ_API_KEY
  export SANI_MODEL_BACKEND=litellm
  export SANI_MODEL="${SANI_MODEL:-groq/llama-3.3-70b-versatile}"
  BACKEND_NOTE="litellm · $SANI_MODEL
             $KEY_NOTE"
else
  export SANI_MODEL_BACKEND=scripted
  BACKEND_NOTE="scripted — replays a fixed demo plan and IGNORES your task.
             Put a Groq key in $GROQ_FILE for real inference:
               umask 077; printf %s 'gsk_...' > $GROQ_FILE"
fi

# --- session store ----------------------------------------------------------
# Inferred from whether Redis actually answers, the same way the backend is
# inferred from the key file. With the memory store a restart silently discards
# every session, including one parked on an approval nobody has answered yet --
# and "Mission Control is empty again" gives no hint that a store was the reason.
#
# An explicit SANI_SESSION_STORE wins, so `SANI_SESSION_STORE=memory` is still
# available for a throwaway run.
REDIS_URL="${SANI_REDIS_URL:-redis://127.0.0.1:6379/0}"
if [ -n "${SANI_SESSION_STORE:-}" ]; then
  STORE_NOTE="$SANI_SESSION_STORE (set explicitly)"
elif command -v redis-cli >/dev/null 2>&1 && \
     [ "$(redis-cli -u "$REDIS_URL" ping 2>/dev/null)" = "PONG" ]; then
  export SANI_SESSION_STORE=redis
  export SANI_REDIS_URL="$REDIS_URL"
  STORE_NOTE="redis — sessions survive a restart ($REDIS_URL)"
else
  export SANI_SESSION_STORE=memory
  STORE_NOTE="memory — sessions are LOST on restart. Start redis for durable history:
               brew services start redis"
fi

# --- CORS -------------------------------------------------------------------
# 3000 through 3003, both spellings, because `next dev` silently takes the next
# free port when 3000 is busy — and the resulting CORS block is invisible: the
# WebSocket is not CORS-checked, so the page loads and the stream connects while
# every fetch fails, which the browser reports to JS as a plain network error and
# the UI renders as "cannot reach the server". A server that is running fine.
# 3200 is the port the e2e suite uses.
ORIGINS=""
for port in 3000 3001 3002 3003 3200; do
  ORIGINS="$ORIGINS,http://localhost:$port,http://127.0.0.1:$port"
done
ORIGINS="${ORIGINS#,}"
if [ -n "${EXTRA_ORIGINS:-}" ]; then
  ORIGINS="$EXTRA_ORIGINS,$ORIGINS"
fi
export SANI_CORS_ORIGINS="$ORIGINS"

# --- go ---------------------------------------------------------------------
cat <<BANNER
Ṣāni' server
  port      : $PORT (loopback only — expose it with a tunnel, never --host 0.0.0.0)
  auth      : $AUTH_NOTE
  backend   : $BACKEND_NOTE
  store     : $STORE_NOTE
  origins   : $SANI_CORS_ORIGINS

BANNER

exec ./.venv/bin/uvicorn sani_server.app:app --host 127.0.0.1 --port "$PORT"
