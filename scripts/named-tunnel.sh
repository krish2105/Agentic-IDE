#!/usr/bin/env bash
#
# A tunnel hostname that does not change.
#
# A quick tunnel (`cloudflared tunnel --url ...`) gets a new random
# `*.trycloudflare.com` name on every restart, and the web IDE stores whichever
# one it was last given. That is the single most repeated failure in this project:
# a working server, a working tunnel, and a browser holding a hostname that
# stopped existing an hour ago -- reported as "cannot reach the server".
#
# A *named* tunnel is bound to a hostname in a zone you control, so the URL
# outlives every restart, reboot and rotation. Once it exists the web IDE can be
# pointed at it permanently -- including as a Vercel build-time default, so a
# hosted deploy needs nothing pasted at all.
#
# Prerequisite, and the one step this script cannot do for you:
#
#     cloudflared tunnel login      # browser sign-in, then pick your domain
#
# Usage:
#   scripts/named-tunnel.sh sani.example.com          # create + route + serve
#   scripts/named-tunnel.sh sani.example.com --uninstall

set -euo pipefail

HOSTNAME_ARG="${1:-}"
NAME="${TUNNEL_NAME:-sani}"
PORT="${PORT:-8060}"
CONFIG_DIR="$HOME/.cloudflared"
CONFIG="$CONFIG_DIR/$NAME.yml"
LABEL="com.sani.tunnel"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/.sani/tunnel.log"

if [ -z "$HOSTNAME_ARG" ]; then
  echo "usage: $0 <hostname>            e.g. $0 sani.example.com" >&2
  echo "       the hostname must be in a zone on your Cloudflare account" >&2
  exit 1
fi

if [ "${2:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "stopped the tunnel service. The tunnel and DNS record still exist:"
  echo "    cloudflared tunnel delete $NAME"
  exit 0
fi

command -v cloudflared >/dev/null 2>&1 || { echo "error: cloudflared is not installed. brew install cloudflared" >&2; exit 1; }

# The login is interactive and account-specific, so it is a prerequisite rather
# than something this script attempts. Failing here with the exact command is
# more useful than a `cloudflared` error about origin certificates.
if [ ! -f "$CONFIG_DIR/cert.pem" ]; then
  echo "error: not logged in to Cloudflare." >&2
  echo >&2
  echo "  Run this first — it opens a browser and asks which of your domains to use:" >&2
  echo "      cloudflared tunnel login" >&2
  echo >&2
  echo "  A named tunnel needs a zone you control. Without a domain on Cloudflare," >&2
  echo "  use scripts/tunnel.sh (random hostname) or work against localhost." >&2
  exit 1
fi

# Refuse to tunnel an unauthenticated server, same as scripts/tunnel.sh. This one
# is worse if it slips: the hostname is stable and public, so an open server would
# stay reachable rather than disappearing on the next restart.
if ! curl -sf -o /dev/null --max-time 5 "http://127.0.0.1:$PORT/healthz"; then
  echo "error: nothing is serving http://127.0.0.1:$PORT — start it with scripts/serve.sh" >&2
  exit 1
fi
AUTH_REQUIRED="$(curl -sf --max-time 5 "http://127.0.0.1:$PORT/healthz" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("auth",{}).get("required"))' 2>/dev/null || echo unknown)"
if [ "$AUTH_REQUIRED" != "True" ]; then
  echo "error: the server on :$PORT has authentication OFF (auth.required=$AUTH_REQUIRED)." >&2
  echo "  A permanent public hostname in front of an unauthenticated server is a" >&2
  echo "  standing remote shell. Reinstall the service with a token:" >&2
  echo "      WITH_AUTH=1 EXTRA_ORIGINS=https://your-app.vercel.app scripts/install-service.sh" >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR" "$HOME/.sani"

# --- the tunnel -------------------------------------------------------------
if cloudflared tunnel list 2>/dev/null | awk 'NR>1 {print $2}' | grep -qx "$NAME"; then
  echo "tunnel '$NAME' already exists — reusing it"
else
  cloudflared tunnel create "$NAME"
fi

TUNNEL_ID="$(cloudflared tunnel list 2>/dev/null | awk -v n="$NAME" '$2 == n {print $1; exit}')"
[ -n "$TUNNEL_ID" ] || { echo "error: could not determine the tunnel id for '$NAME'" >&2; exit 1; }

# --- DNS --------------------------------------------------------------------
# Idempotent: re-running points the same hostname at the same tunnel.
cloudflared tunnel route dns --overwrite-dns "$NAME" "$HOSTNAME_ARG"

# --- config -----------------------------------------------------------------
cat > "$CONFIG" <<YAML
# Written by scripts/named-tunnel.sh
tunnel: $TUNNEL_ID
credentials-file: $CONFIG_DIR/$TUNNEL_ID.json

ingress:
  - hostname: $HOSTNAME_ARG
    service: http://127.0.0.1:$PORT
  # Anything else that resolves here is refused rather than quietly proxied.
  - service: http_status:404
YAML

# --- keep it running --------------------------------------------------------
# Same reasoning as the server's service: a tunnel whose lifetime depends on which
# terminal window is open is a tunnel that is down when you need it.
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
    <string>exec cloudflared --config '$CONFIG' tunnel run '$NAME'</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST_EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load "$PLIST"

echo
echo "  tunnel  : $NAME ($TUNNEL_ID)"
echo "  hostname: https://$HOSTNAME_ARG   <- this never changes again"
echo "  config  : $CONFIG"
echo "  log     : $LOG"
echo
echo "waiting for DNS and the tunnel to settle…"
for _ in $(seq 1 40); do
  if curl -sf -o /dev/null --max-time 4 "https://$HOSTNAME_ARG/healthz"; then
    echo "  ✅ https://$HOSTNAME_ARG is serving"
    echo
    echo "Point the web IDE at it once and it stays correct. To bake it into the"
    echo "Vercel build so nothing has to be pasted there at all:"
    echo "    vercel env add NEXT_PUBLIC_SANI_SERVER production   # https://$HOSTNAME_ARG"
    exit 0
  fi
  sleep 2
done

echo "  ⚠️ not answering yet. DNS can take a minute; check $LOG" >&2
exit 1
