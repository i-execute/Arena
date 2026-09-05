#!/usr/bin/env bash
# =============================================================================
# LMArena Bridge — installer (Setuper.sh)
#
# You supply ONE thing: the bot token. Everything else is either detected or
# collected inside Telegram, because a shell cannot know it:
#
#   BOT_TOKEN            -> asked here (validated via getMe)
#   OWNER_ID             -> the bot replies with your numeric id (echo-id mode);
#                           you paste it back over SSH
#   TELEGRAM_API_ID/HASH -> inline-input buttons in the bot's /setup
#   log group + topics   -> you ADD the bot to a group, it links itself (/here)
#   arena session        -> Camoufox scrapes it on first bridge start
#   GITHUB_TOKEN         -> only if the anonymous Camoufox download is rate-limited
#
# Every secret ends up in <install>/.env (chmod 600). config.json holds only
# non-secret runtime state.
#
# Usage:
#   bash Setuper.sh                      # interactive
#   BOT_TOKEN=123:abc bash Setuper.sh    # non-interactive token
#   bash Setuper.sh --status             # show service health, change nothing
#   bash Setuper.sh --uninstall          # stop + disable units (keeps data)
# =============================================================================
set -uo pipefail

REPO_URL="${REPO_URL:-https://github.com/i-execute/Arena.git}"
BRANCH="${BRANCH:-main}"
API="https://api.telegram.org"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m'; BOLD=$'\033[1m'; NC=$'\033[0m'
say()  { printf '%s[LMA]%s %s\n' "$CYAN" "$NC" "$*"; }
ok()   { printf '%s[OK]%s %s\n'  "$GREEN" "$NC" "$*"; }
warn() { printf '%s[WARN]%s %s\n' "$YELLOW" "$NC" "$*"; }
err()  { printf '%s[ERR]%s %s\n' "$RED" "$NC" "$*" >&2; }
die()  { err "$*"; exit 1; }

# ── input helpers ────────────────────────────────────────────────────────────
# `read < /dev/tty` explodes when there is no controlling terminal (CI, a
# non-interactive ssh command, `bash Setuper.sh < file`). The original code did
# exactly that inside a `while :;` validation loop, so a tty-less run span
# forever printing "invalid token, try again". These helpers degrade to stdin and
# report EOF instead of looping.
HAVE_TTY=0
if [ -e /dev/tty ] && { : < /dev/tty; } 2>/dev/null; then HAVE_TTY=1; fi

# ask <varname> <prompt>   -> 0 on success, 1 on EOF/no input source
ask() {
    local __var="$1" __prompt="$2" __val=""
    if [ "$HAVE_TTY" = "1" ]; then
        printf '%s' "$__prompt" > /dev/tty
        IFS= read -r __val < /dev/tty || return 1
    elif [ ! -t 0 ]; then
        printf '%s' "$__prompt"
        IFS= read -r __val || return 1
    else
        printf '%s' "$__prompt"
        IFS= read -r __val || return 1
    fi
    eval "$__var=\$__val"
    return 0
}

# ask_secret <varname> <prompt>  — same, but never echoes the value
ask_secret() {
    local __var="$1" __prompt="$2" __val=""
    if [ "$HAVE_TTY" = "1" ]; then
        printf '%s' "$__prompt" > /dev/tty
        IFS= read -rs __val < /dev/tty || { printf '\n' > /dev/tty; return 1; }
        printf '\n' > /dev/tty
    else
        printf '%s' "$__prompt"
        IFS= read -r __val || { printf '\n'; return 1; }
        printf '\n'
    fi
    eval "$__var=\$__val"
    return 0
}

MODE="install"
for arg in "$@"; do
    case "$arg" in
        --status)    MODE="status" ;;
        --uninstall) MODE="uninstall" ;;
        --help|-h)   sed -n '3,25p' "$0" | sed 's/^# \?//'; exit 0 ;;
    esac
done

# ── refuse root: everything runs as systemd --user under the real user ────────
if [ "$(id -u)" -eq 0 ]; then
    die "Do not run as root. Services are installed as systemd --user units under
     your own account. Re-run without sudo:  bash Setuper.sh"
fi

INSTALL_DIR_DEFAULT="$HOME/Arena"
if [ -f "$(cd "$(dirname "$0")/../.." && pwd)/BRIDGE/main.py" ]; then
    # Running from inside a checkout -> install in place.
    INSTALL_DIR_DEFAULT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
INSTALL_DIR="${INSTALL_DIR:-$INSTALL_DIR_DEFAULT}"

UNIT_DIR="$HOME/.config/systemd/user"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
SERVICES=(lmarena-bridge lmarena-web lmarena-bot2 lmarena-web-tunnel lmarena-api-tunnel)

# ── --status / --uninstall short circuits ─────────────────────────────────────
if [ "$MODE" = "status" ]; then
    say "services:"
    for s in "${SERVICES[@]}"; do
        printf '  %-22s %s\n' "$s" "$(systemctl --user is-active "$s" 2>/dev/null || echo inactive)"
    done
    printf '\n'
    say "endpoints:"
    curl -sf -m 5 http://127.0.0.1:6767/api/v1/health && printf '\n' || echo "  bridge :6767 DOWN"
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:8787/ || echo 000)
    echo "  dashboard :8787 HTTP $code"
    printf '\n'
    say "tunnels:"
    for svc in lmarena-web-tunnel lmarena-api-tunnel; do
        u=$(journalctl --user -u "$svc" --no-pager -o cat 2>/dev/null \
            | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1)
        printf '  %-22s %s\n' "$svc" "${u:-<no url>}"
    done
    exit 0
fi

if [ "$MODE" = "uninstall" ]; then
    say "stopping and disabling units (data in $INSTALL_DIR is kept)..."
    systemctl --user disable --now "${SERVICES[@]}" 2>/dev/null || true
    systemctl --user daemon-reload
    ok "uninstalled. Remove $INSTALL_DIR manually if you also want the data gone."
    exit 0
fi

printf '\n%s=== LMArena Bridge installer ===%s\n\n' "$BOLD" "$NC"
say "install dir : $INSTALL_DIR"
say "units        : $UNIT_DIR (systemd --user)"
printf '\n'

# ── 1. dependencies ──────────────────────────────────────────────────────────
say "[1/8] checking dependencies..."
MISSING=()
for bin in python3 git curl; do command -v "$bin" >/dev/null 2>&1 || MISSING+=("$bin"); done
python3 -c 'import venv' 2>/dev/null || MISSING+=("python3-venv")
if [ ${#MISSING[@]} -gt 0 ]; then
    err "missing: ${MISSING[*]}"
    echo "     install them first, e.g.:"
    echo "       sudo apt-get update && sudo apt-get install -y python3 python3-venv git curl"
    exit 1
fi

NODE_BIN="$(command -v node || true)"
if [ -z "$NODE_BIN" ]; then
    warn "node not found — installing a local Node.js into ~/.local (no sudo)"
    NODE_VER="v22.14.0"
    case "$(uname -m)" in
        x86_64) NARCH="x64" ;;
        aarch64|arm64) NARCH="arm64" ;;
        *) die "unsupported architecture $(uname -m) — install Node.js 20+ manually" ;;
    esac
    mkdir -p "$HOME/.local"
    curl -fsSL "https://nodejs.org/dist/${NODE_VER}/node-${NODE_VER}-linux-${NARCH}.tar.xz" \
        | tar -xJ -C "$HOME/.local" --strip-components=1 \
        || die "Node.js download failed"
    NODE_BIN="$HOME/.local/bin/node"
fi
ok "node $("$NODE_BIN" --version 2>/dev/null || echo '?') at $NODE_BIN"

if ! command -v cloudflared >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/cloudflared" ]; then
    say "installing cloudflared into ~/.local/bin ..."
    case "$(uname -m)" in
        x86_64) CF_ARCH="amd64" ;;
        aarch64|arm64) CF_ARCH="arm64" ;;
        *) die "unsupported architecture for cloudflared" ;;
    esac
    mkdir -p "$HOME/.local/bin"
    curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}" \
        -o "$HOME/.local/bin/cloudflared" || die "cloudflared download failed"
    chmod +x "$HOME/.local/bin/cloudflared"
fi
CF_BIN="$(command -v cloudflared || echo "$HOME/.local/bin/cloudflared")"
ok "cloudflared at $CF_BIN"

# ── 2. repository ────────────────────────────────────────────────────────────
say "[2/8] repository..."
if [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" fetch --quiet origin "$BRANCH" \
        && ok "fetched origin/$BRANCH (working tree left untouched)" \
        || warn "git fetch failed — continuing with the local checkout"
elif [ -f "$INSTALL_DIR/BRIDGE/main.py" ]; then
    ok "existing checkout without .git — using as-is"
else
    git clone --quiet -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR" || die "git clone failed"
    ok "cloned into $INSTALL_DIR"
fi
cd "$INSTALL_DIR" || die "cannot enter $INSTALL_DIR"

ENV_FILE="$INSTALL_DIR/.env"
CONFIG_FILE="$INSTALL_DIR/WEB/data/config.json"
VENV="$INSTALL_DIR/venv"

# env_set KEY VALUE — upsert into .env, never echoing secret values
env_set() {
    python3 - "$ENV_FILE" "$1" "$2" <<'PY'
import os, re, sys, tempfile
path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
lines = []
if os.path.exists(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
pat = re.compile(r"^\s*(?:export\s+)?%s\s*=" % re.escape(key))
out, replaced = [], False
for line in lines:
    if pat.match(line):
        if not replaced:
            out.append(f"{key}={value}")
            replaced = True
    else:
        out.append(line)
if not replaced:
    out.append(f"{key}={value}")
d = os.path.dirname(path) or "."
os.makedirs(d, exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=d, prefix=".env.", suffix=".tmp")
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    fh.write("\n".join(out).rstrip("\n") + "\n")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY
}
env_get() {
    [ -f "$ENV_FILE" ] || { echo ""; return; }
    python3 - "$ENV_FILE" "$1" <<'PY'
import re, sys
path, key = sys.argv[1], sys.argv[2]
pat = re.compile(r"^\s*(?:export\s+)?%s\s*=\s*(.*)$" % re.escape(key))
val = ""
for line in open(path, encoding="utf-8", errors="replace"):
    m = pat.match(line.rstrip("\n"))
    if m:
        val = m.group(1).strip().strip('"').strip("'")
print(val)
PY
}

# ── 3. python venv ───────────────────────────────────────────────────────────
say "[3/8] python environment..."
[ -d "$VENV" ] || python3 -m venv "$VENV" || die "venv creation failed"
"$VENV/bin/pip" install --quiet --upgrade pip
REQ="$INSTALL_DIR/Storage/Dependencies/requirements.txt"
[ -f "$REQ" ] || REQ="$INSTALL_DIR/requirements.txt"
if [ -f "$REQ" ]; then
    "$VENV/bin/pip" install --quiet -r "$REQ" || warn "some requirements failed"
fi
# telethon = optional MTProto layer (premium emoji in inline, coloured buttons)
"$VENV/bin/pip" install --quiet aiohttp telethon || warn "aiohttp/telethon install failed"
ok "python deps installed"

# ── 4. camoufox browser (GitHub token only as a rate-limit fallback) ─────────
say "[4/8] Camoufox browser..."
if "$VENV/bin/python3" -m camoufox path >/dev/null 2>&1 \
   && [ -n "$("$VENV/bin/python3" -m camoufox path 2>/dev/null)" ] \
   && [ -d "$("$VENV/bin/python3" -m camoufox path 2>/dev/null)" ]; then
    ok "already downloaded"
else
    say "downloading anonymously (no token needed unless GitHub rate-limits us)..."
    FETCH_LOG=$(mktemp)
    if "$VENV/bin/python3" -m camoufox fetch >"$FETCH_LOG" 2>&1; then
        ok "downloaded"
    else
        tail -3 "$FETCH_LOG" | sed 's/^/     /'
        if grep -qiE "rate limit|403|429" "$FETCH_LOG"; then
            warn "GitHub rate-limited the anonymous download."
            echo "     A GitHub token lifts the limit. No scopes required (public read)."
            echo "     Create one: https://github.com/settings/tokens  (Generate new token, classic)"
            GH_TOKEN=""
            ask_secret GH_TOKEN "${CYAN}GitHub token (input hidden, ENTER to skip): ${NC}" || true
            GH_TOKEN="$(printf '%s' "${GH_TOKEN:-}" | tr -d '[:space:]')"
            if [ -n "${GH_TOKEN:-}" ]; then
                env_set GITHUB_TOKEN "$GH_TOKEN"
                if GITHUB_TOKEN="$GH_TOKEN" "$VENV/bin/python3" -m camoufox fetch \
                        >"$FETCH_LOG" 2>&1; then
                    ok "downloaded with token"
                else
                    tail -3 "$FETCH_LOG" | sed 's/^/     /'
                    warn "still failing — the bridge will retry on first start"
                fi
            else
                warn "skipped — retry later:  GITHUB_TOKEN=... $VENV/bin/python3 -m camoufox fetch"
            fi
        else
            warn "download failed for a non-rate-limit reason; bridge will retry"
        fi
    fi
    rm -f "$FETCH_LOG"
fi

# ── 5. node deps ─────────────────────────────────────────────────────────────
say "[5/8] dashboard dependencies..."
if [ -f "$INSTALL_DIR/WEB/package.json" ]; then
    NPM_BIN="$(dirname "$NODE_BIN")/npm"
    [ -x "$NPM_BIN" ] || NPM_BIN="$(command -v npm || true)"
    if [ -n "$NPM_BIN" ]; then
        (cd "$INSTALL_DIR/WEB" && "$NPM_BIN" install --omit=dev --silent) \
            && ok "node modules installed" || warn "npm install failed"
    else
        warn "npm not found — dashboard deps not installed"
    fi
fi

# ── 6. bot token (the ONLY secret you type here) ─────────────────────────────
say "[6/8] Telegram bot token..."
BOT_TOKEN="${BOT_TOKEN:-$(env_get BOT_TOKEN)}"
BOT_USERNAME=""
TOKEN_TRIES=0
TOKEN_MAX_TRIES=5
while :; do
    if [ -z "$BOT_TOKEN" ]; then
        TOKEN_TRIES=$((TOKEN_TRIES + 1))
        if [ "$TOKEN_TRIES" -gt "$TOKEN_MAX_TRIES" ]; then
            die "no valid bot token after $TOKEN_MAX_TRIES attempts.
     Re-run non-interactively:  BOT_TOKEN=<token> bash Setuper.sh"
        fi
        echo "     Create a bot with @BotFather, then paste its token."
        if ! ask BOT_TOKEN "${CYAN}BOT_TOKEN: ${NC}"; then
            die "no token supplied and no input available.
     Re-run non-interactively:  BOT_TOKEN=<token> bash Setuper.sh"
        fi
        BOT_TOKEN="$(printf '%s' "$BOT_TOKEN" | tr -d '[:space:]')"
        [ -n "$BOT_TOKEN" ] || continue
    fi
    # Shape check before spending a network round-trip: <digits>:<35+ chars>
    if ! printf '%s' "$BOT_TOKEN" | grep -qE '^[0-9]{6,12}:[A-Za-z0-9_-]{30,}$'; then
        err "that does not look like a bot token (expected 123456789:AA...)"
        BOT_TOKEN=""
        continue
    fi
    ME=$(curl -s -m 20 "$API/bot${BOT_TOKEN}/getMe" || echo '{}')
    BOT_USERNAME=$(printf '%s' "$ME" | python3 -c \
        "import sys,json;d=json.load(sys.stdin);print(d.get('result',{}).get('username','') if d.get('ok') else '')" 2>/dev/null)
    if [ -n "$BOT_USERNAME" ]; then
        INLINE_OK=$(printf '%s' "$ME" | python3 -c \
            "import sys,json;print(json.load(sys.stdin)['result'].get('supports_inline_queries',False))" 2>/dev/null)
        ok "token valid — @$BOT_USERNAME"
        if [ "$INLINE_OK" != "True" ]; then
            warn "inline mode is OFF for @$BOT_USERNAME"
            echo "     The bot collects api_id/api_hash through inline input, so enable it:"
            echo "       @BotFather -> /setinline -> @$BOT_USERNAME -> send any placeholder"
            echo "     (You can do this after the install; the bot will remind you.)"
        fi
        break
    fi
    err "invalid token, try again"
    BOT_TOKEN=""
done

env_set BOT_TOKEN "$BOT_TOKEN"
env_set LMA_DIR "$INSTALL_DIR"
env_set BRIDGE_URL "http://127.0.0.1:6767"
env_set DATA_FILE "$CONFIG_FILE"
env_set PORT 8787
env_set CORS_ORIGINS "*"
env_set SESSION_TTL_HOURS 24
env_set INITDATA_MAX_AGE_HOURS 24
# DEV_MODE=true would let anyone with the tunnel URL mint a dashboard session.
env_set DEV_MODE false
env_set BOT_LOG_FORWARD_INTERVAL 20

[ -n "$(env_get SESSION_JWT_SECRET)" ] || \
    env_set SESSION_JWT_SECRET "$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
[ -n "$(env_get BRIDGE_API_KEY)" ] || \
    env_set BRIDGE_API_KEY "sk-$(python3 -c "
import secrets,string
a=string.ascii_letters+string.digits
print(''.join(secrets.choice(a) for _ in range(48)))")"
chmod 600 "$ENV_FILE"
ok "secrets written to $ENV_FILE (chmod 600)"

mkdir -p "$INSTALL_DIR/WEB/data" "$INSTALL_DIR/Storage/logs" "$INSTALL_DIR/Storage/sessions"
[ -f "$CONFIG_FILE" ] || echo '{"models": [], "usage_stats": {}}' > "$CONFIG_FILE"
ln -sf WEB/data/config.json "$INSTALL_DIR/config.json" 2>/dev/null || true

# ── 7. systemd --user units ──────────────────────────────────────────────────
say "[7/8] installing systemd --user units..."
mkdir -p "$UNIT_DIR"
loginctl enable-linger "$USER" >/dev/null 2>&1 || \
    warn "could not enable linger — services stop when you log out"

write_unit() { # write_unit <name> <description> <exec> [workdir]
    cat > "$UNIT_DIR/lmarena-$1.service" <<UNIT
[Unit]
Description=$2
After=network.target

[Service]
Type=simple
WorkingDirectory=${4:-$INSTALL_DIR}
EnvironmentFile=$ENV_FILE
Environment="PATH=$VENV/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$3
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
UNIT
}

write_unit bridge     "LMArena Python Bridge (FastAPI :6767)" "$VENV/bin/python3 -m BRIDGE.main"
write_unit web        "LMArena dashboard (Node :8787)"        "$NODE_BIN $INSTALL_DIR/WEB/server.js"
write_unit bot2       "LMArena Telegram admin bot"            "$VENV/bin/python3 -u -m BOT.lm_bot"
write_unit web-tunnel "LMArena dashboard tunnel"              "$CF_BIN tunnel --url http://127.0.0.1:8787 --no-autoupdate"
write_unit api-tunnel "LMArena API tunnel"                    "$CF_BIN tunnel --url http://127.0.0.1:6767 --no-autoupdate"

# The legacy lmarena-bot unit polls the SAME token as bot2 -> Telegram answers
# "Conflict: terminated by other getUpdates request". Only bot2 may run.
systemctl --user disable --now lmarena-bot.service >/dev/null 2>&1 || true

systemctl --user daemon-reload
systemctl --user enable --now lmarena-bridge lmarena-web lmarena-bot2 \
    lmarena-web-tunnel lmarena-api-tunnel >/dev/null 2>&1 || warn "enable/start reported errors"
ok "units installed and started"

# ── 8. owner id via the bot itself (echo-id mode) ─────────────────────────────
say "[8/8] linking your Telegram account..."
OWNER_ID="${OWNER_ID:-$(env_get OWNER_ID)}"
if [ -z "$OWNER_ID" ]; then
    printf '\n'
    echo "     ${BOLD}Open a DM with @$BOT_USERNAME and send any message.${NC}"
    echo "     The bot replies with your numeric id (echo-id bootstrap) and"
    echo "     registers you as the owner automatically."
    printf '\n'
    say "waiting up to 180s for the bot to capture an owner id..."
    for _ in $(seq 1 60); do
        sleep 3
        OWNER_ID="$(env_get OWNER_ID)"
        [ -n "$OWNER_ID" ] && break
    done
    if [ -n "$OWNER_ID" ]; then
        ok "owner id captured automatically: $OWNER_ID"
    else
        warn "no DM seen yet."
        OWNER_ID=""
        ask OWNER_ID "${CYAN}Paste the id the bot sent you (ENTER to skip): ${NC}" || true
        OWNER_ID="$(printf '%s' "${OWNER_ID:-}" | tr -d '[:space:]')"
    fi
fi
if [ -n "${OWNER_ID:-}" ]; then
    case "$OWNER_ID" in
        ''|*[!0-9]*) warn "'$OWNER_ID' is not numeric — skipped" ;;
        *)
            env_set OWNER_ID "$OWNER_ID"
            env_set ADMIN_ID "$OWNER_ID"
            systemctl --user restart lmarena-bot2 lmarena-web
            ok "owner set to $OWNER_ID"
            ;;
    esac
fi

# ── health summary ───────────────────────────────────────────────────────────
printf '\n'
say "waiting for the bridge to finish its first arena.ai scrape (up to 90s)..."
for _ in $(seq 1 30); do
    curl -sf -m 3 http://127.0.0.1:6767/api/v1/health >/dev/null 2>&1 && break
    sleep 3
done

printf '\n%s=== install complete ===%s\n\n' "$GREEN" "$NC"
for s in "${SERVICES[@]}"; do
    printf '  %-22s %s\n' "$s" "$(systemctl --user is-active "$s" 2>/dev/null || echo inactive)"
done
printf '\n'
curl -sf -m 5 http://127.0.0.1:6767/api/v1/health && printf '\n' || echo "  bridge health: not answering yet"
printf '\n'
say "tunnel URLs (may take ~15s to appear):"
sleep 8
for svc in lmarena-web-tunnel lmarena-api-tunnel; do
    label="Dashboard"; [ "$svc" = "lmarena-api-tunnel" ] && label="API"
    u=$(journalctl --user -u "$svc" --no-pager -o cat 2>/dev/null \
        | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1)
    printf '  %-10s %s\n' "$label" "${u:-<pending>}"
done

cat <<NEXT

${BOLD}Finish the setup inside Telegram${NC} (nothing else goes through this shell):

  1. DM @$BOT_USERNAME and send  /setup
  2. Tap "Enter api_id" / "Enter api_hash" — inline input, values from
     https://my.telegram.org  (enables premium emoji + media via MTProto)
  3. Add the bot to your log group as an ADMIN with "Manage Topics",
     enable Topics in that group, then send  /here  there.
     It creates Logs + Requests topics and starts forwarding bridge logs.

Useful:
  bash Storage/Installation/Setuper.sh --status      service + tunnel overview
  systemctl --user restart lmarena-bridge            restart the bridge
  journalctl --user -u lmarena-bridge -f             follow bridge logs
  Secrets:  $ENV_FILE  (chmod 600, never committed)
NEXT
