#!/usr/bin/env bash
# LMArena Tunnel Manager — control cloudflared quick-tunnel daemons.
# Usage:
#   ./tunnel.sh status          # show active state + URLs for both tunnels
#   ./tunnel.sh url             # print just the URLs (key=url per line)
#   ./tunnel.sh restart         # restart both tunnels
#   ./tunnel.sh restart web     # restart only dashboard tunnel
#   ./tunnel.sh restart api     # restart only api tunnel
#   ./tunnel.sh stop|start      # stop/start both
set -uo pipefail

WEB=lmarena-web-tunnel
API=lmarena-api-tunnel
DISPLAY_WEB="Dashboard"
DISPLAY_API="API"

log() { echo -e "\033[1;34m[tun]\033[0m $*"; }
err() { echo -e "\033[1;31m[tun]\033[0m $*" >&2; }

get_url() {
  local svc="$1"
  # cloudflared prints "Your quick Tunnel has been created" then the URL banner line.
  journalctl --user -u "$svc.service" --no-pager -o cat 2>/dev/null \
    | grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" | tail -1
}

status_one() {
  local svc="$1" disp="$2"
  local state url
  state=$(systemctl --user is-active "$svc" 2>/dev/null || echo inactive)
  url=$(get_url "$svc")
  printf "  %-10s %-10s %s\n" "$disp" "$state" "${url:-<no url>}"
}

cmd_status() {
  log "tunnel status:"
  status_one "$WEB" "$DISPLAY_WEB"
  status_one "$API" "$DISPLAY_API"
}

cmd_url() {
  local u1 u2
  u1=$(get_url "$WEB"); u2=$(get_url "$API")
  echo "Dashboard=$u1"
  echo "API=$u2"
}

cmd_restart() {
  local targets=()
  case "${1:-both}" in
    web) targets=("$WEB") ;;
    api) targets=("$API") ;;
    *)   targets=("$WEB" "$API") ;;
  esac
  log "restarting: ${targets[*]}"
  systemctl --user restart "${targets[@]}" || { err "restart failed"; exit 1; }
  # wait for new URLs
  for i in $(seq 1 12); do
    sleep 2
    if get_url "$WEB" >/dev/null 2>&1 && get_url "$API" >/dev/null 2>&1; then
      break
    fi
  done
  cmd_status
}

cmd_start() { log "starting tunnels..."; systemctl --user start "$WEB" "$API"; cmd_status; }
cmd_stop()  { log "stopping tunnels..."; systemctl --user stop "$WEB" "$API"; cmd_status; }

case "${1:-status}" in
  status)  cmd_status ;;
  url)     cmd_url ;;
  restart) cmd_restart "${2:-both}" ;;
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  *) echo "usage: $0 {status|url|restart [web|api]|start|stop}"; exit 1 ;;
esac
