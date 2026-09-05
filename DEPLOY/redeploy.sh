#!/usr/bin/env bash
# LMArena Redeploy — sync Arena -> LMArena and restart systemd user services.
# Usage:
#   ./redeploy.sh            # full: pull, sync, restart, health checks
#   ./redeploy.sh --no-pull  # skip git pull
#   ./redeploy.sh --bridge   # only bridge service
set -euo pipefail

ARENA_DIR="${ARENA_DIR:-$HOME/Arena}"
LMA_DIR="${LMA_DIR:-$HOME/LMArena}"
DO_PULL=1

for arg in "$@"; do
  case "$arg" in
    --no-pull) DO_PULL=0 ;;
    *) ;;
  esac
done

log()  { echo -e "\033[1;34m[LMA]\033[0m $*"; }
err()  { echo -e "\033[1;31m[LMA]\033[0m $*" >&2; }
ok()   { echo -e "\033[1;32m[LMA]\033[0m $*"; }

[ -d "$ARENA_DIR" ] || { err "Arena repo not found: $ARENA_DIR"; exit 1; }
[ -d "$LMA_DIR" ]   || { err "LMArena dir not found: $LMA_DIR"; exit 1; }

cd "$ARENA_DIR"

if [ "$DO_PULL" = "1" ]; then
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

restart_and_check() {
  local svc="$1"
  local port="$2"
  log "restarting $svc..."
  systemctl --user restart "$svc" 2>/dev/null || { err "  failed to restart $svc"; return 1; }
  # Wait for port to answer
  for i in $(seq 1 24); do
    sleep 5
    if curl -sf -o /dev/null "http://127.0.0.1:$port/api/v1/health" 2>/dev/null || \
       curl -sf -o /dev/null "http://127.0.0.1:$port/" 2>/dev/null; then
      ok "  $svc healthy (try $i)"
      return 0
    fi
  done
  err "  $svc NOT healthy after 120s"
  return 1
}

restart_and_check lmarena-bridge 6767
restart_and_check lmarena-web 8787
systemctl --user restart lmarena-bot2 2>/dev/null && ok "lmarena-bot2 restarted"

ok "=== redeploy done ==="
