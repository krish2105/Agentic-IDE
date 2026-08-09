#!/usr/bin/env bash
#
# Keep the server running: at login, after a crash, and after you close the
# terminal you started it from.
#
# Every "it stopped working" in this project traced back to the server not being
# up -- a Ctrl-C, a closed tab, a terminal that owned the process. Running it in
# the foreground makes the server's lifetime an accident of which window is open.
# launchd is macOS's own answer to that: RunAtLoad starts it with your session,
# KeepAlive restarts it if it dies.
#
# Defaults to SANI_NO_AUTH=1, because an always-on service is for the local
# setup: server on loopback, web IDE on localhost, nothing to paste. Pass
# WITH_AUTH=1 if you intend to tunnel -- and note scripts/tunnel.sh refuses an
# unauthenticated server anyway, so a mistake here is caught rather than exposed.
#
# Usage:
#   scripts/install-service.sh              # install and start
#   WITH_AUTH=1 scripts/install-service.sh  # require a bearer token
#   WITH_AUTH=1 EXTRA_ORIGINS=https://foo.vercel.app scripts/install-service.sh
#   scripts/install-service.sh --uninstall  # stop and remove

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.sani.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/.sani/server.log"
PORT="${PORT:-8060}"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "removed $LABEL — the server will no longer start on login"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.sani"
chmod 700 "$HOME/.sani"

AUTH_ENV=""
[ "${WITH_AUTH:-}" = "1" ] || AUTH_ENV="SANI_NO_AUTH=1"

# Baked into the plist, not read from the environment at run time: launchd starts
# the job with its own minimal environment, so anything expected to arrive from
# your shell arrives empty. A hosted origin missing from the CORS list is
# invisible -- the WebSocket still connects, so the page loads and only the
# fetches fail, which the browser reports as a network error.
EXTRA_ORIGINS="${EXTRA_ORIGINS:-}"

# `bash -lc` so the login PATH is present: serve.sh shells out to curl, lsof and
# python3, and a launchd job starts with a minimal environment.
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>cd '$REPO' && PORT=$PORT $AUTH_ENV EXTRA_ORIGINS='$EXTRA_ORIGINS' exec ./scripts/serve.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>WorkingDirectory</key><string>$REPO</string>
</dict>
</plist>
PLIST_EOF

# Replace any previous copy rather than stacking two jobs on one port.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load "$PLIST"

echo "installed $LABEL"
echo "  plist : $PLIST"
echo "  log   : $LOG"
echo "  auth  : $([ "${WITH_AUTH:-}" = "1" ] && echo "on (token in ~/.sani/auth-token)" || echo "off — loopback only, no tunnel")"
echo "  extra origins : ${EXTRA_ORIGINS:-none beyond localhost}"
echo
echo "waiting for it to come up…"
for _ in $(seq 1 20); do
  if curl -sf -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/healthz"; then
    echo "  ✅ serving on http://127.0.0.1:$PORT"
    echo
    echo "It now starts at login and restarts if it dies. To stop permanently:"
    echo "    scripts/install-service.sh --uninstall"
    exit 0
  fi
  sleep 1
done

echo "  ⚠️ not answering yet — check $LOG" >&2
exit 1
