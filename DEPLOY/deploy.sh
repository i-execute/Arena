#!/usr/bin/env bash
# LMArena Full Deploy — sync, restart all services, ensure tunnels, health-check.
# Usage:
#   ./deploy.sh              # full deploy + tunnels + health
#   ./deploy.sh --no-tunnel  # skip tunnel restart
#   ./deploy.sh --bridge     # only bridge (fast)
#   ./deploy.sh --status     # show current status, no changes
set -uo pipefail

ARENA_DIR="${ARENA_DIR:-$HOME/Arena}"
LMA_DIR="${LMA_DIR:-$HOME/LMArena}"
DO_TUNNEL=1
MODE="full"

for arg in "$@"; do
  case "$arg" in
    --no-tunnel) DO_TUNNEL=0 ;;
    --bridge)    MODE="bridge" ;;
    --status)    MODE="status" ;;
    *) ;;
  esac
done

log() { echo -e "\033[1;34m[LMA]\033[0m $*"; }
err() { echo -e "\033[1;31m[LMA]\033[0m $*" >&2; }
ok()  { echo -e "\033[1;32m[LMA]\033[0m $*"; }

[ -d "$ARENA_DIR" ] || { err "Arena repo not found: $ARENA_DIR"; exit 1; }
[ -d "$LMA_DIR" ]   || { err "LMArena dir not found: $LMA_DIR"; exit 1; }

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

svc_health() { # svc_name port
  local svc="$1" port="$2"
  if ! systemctl --user is-active "$svc" >/dev/null 2>&1; then
    echo "  $svc: INACTIVE"
    return 1
  fi
  for _ in $(seq 1 12); do
    if curl -sf -o /dev/null --max-time 3 "http://127.0.0.1:$port/api/v1/health" 2>/dev/null; then
      echo "  $svc: OK (:$port)"
      return 0
    fi
    sleep 2
  done
  echo "  $svc: ACTIVE but not answering on :$port"
  return 1
}

if [ "$MODE" = "status" ]; then
  log "Current status:"
  svc_health lmarena-bridge 6767
  curl -sf -o /dev/null --max-time 3 "http://127.0.0.1:8787/" 2>/dev/null && echo "  lmarena-web: OK (:8787)" || echo "  lmarena-web: DOWN"
  systemctl --user is-active lmarena-bot2 >/dev/null 2>&1 && echo "  lmarena-bot2: OK" || echo "  lmarena-bot2: DOWN"
  for t in lmarena-web-tunnel lmarena-api-tunnel; do
    systemctl --user is-active "$t" >/dev/null 2>&1 && echo "  $t: OK" || echo "  $t: DOWN"
  done
  exit 0
fi

cd "$ARENA_DIR"

if [ "$MODE" = "full" ]; then
  log "git pull..."
  git pull --ff-only origin main 2>&1 | tail -3 || true
fi

log "syncing BRIDGE/WEB/BOT -> $LMA_DIR..."
for d in BRIDGE WEB BOT; do
  if [ -d "$ARENA_DIR/$d" ]; then
    cp -r "$ARENA_DIR/$d"/* "$LMA_DIR/$d"/ 2>/dev/null || true
    ok "  synced $d/"
  fi
done

if [ "$MODE" = "bridge" ] || [ "$MODE" = "full" ]; then
  log "restarting lmarena-bridge..."
  systemctl --user restart lmarena-bridge
  sleep 2
  svc_health lmarena-bridge 6767 || err "bridge health check failed!"
fi

if [ "$MODE" = "full" ]; then
  log "restarting lmarena-web..."
  systemctl --user restart lmarena-web 2>/dev/null || true
  log "restarting lmarena-bot2..."
  systemctl --user restart lmarena-bot2 2>/dev/null || true

  if [ "$DO_TUNNEL" = "1" ]; then
    log "restarting tunnels..."
    systemctl --user restart lmarena-web-tunnel lmarena-api-tunnel 2>/dev/null || err "tunnel restart failed"
    sleep 4
    for t in lmarena-web-tunnel lmarena-api-tunnel; do
      systemctl --user is-active "$t" >/dev/null 2>&1 && ok "  $t: OK" || err "  $t: DOWN"
    done
    if [ -x "$ARENA_DIR/DEPLOY/tunnel.sh" ]; then
      ok "tunnel URLs:"
      "$ARENA_DIR/DEPLOY/tunnel.sh" url 2>/dev/null | sed 's/^/    /'
    fi
  fi
fi

ok "Deploy finished."
exit 0
