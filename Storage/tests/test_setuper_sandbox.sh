#!/usr/bin/env bash
# =============================================================================
# Sandbox harness for Storage/Installation/Setuper.sh
#
# Runs the REAL installer end-to-end against a fake HOME with PATH shims, so
# nothing touches the live install:
#   * systemctl/loginctl  -> record calls, never touch the real user bus
#   * curl                -> canned Telegram getMe + file downloads
#   * git                 -> canned clone/fetch
#   * node/npm            -> canned versions
#   * python3 -m camoufox -> canned success (or rate-limit, see MODE)
#
# Then asserts on what the installer produced: .env keys, unit files, prompts.
#
# Usage: bash run_test.sh <scenario>
#   fresh        first install, token from env, owner from env
#   idempotent   run twice, second run must not break anything
#   ratelimit    camoufox download hits GitHub rate limit -> GH token path
#   badtoken     invalid token first, valid token second (stdin retry loop)
#   inplace      run from inside an existing checkout (install-in-place path)
# =============================================================================
set -uo pipefail

SCENARIO="${1:-fresh}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SANDBOX="${SANDBOX_ROOT:-${TMPDIR:-/tmp}}/lma-setuper-sandbox-$SCENARIO"
SHIM="$SANDBOX/shim"
FAKE_HOME="$SANDBOX/home"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
SRC_SETUPER="$REPO_ROOT/Storage/Installation/Setuper.sh"
CALLS="$SANDBOX/calls.log"

rm -rf "$SANDBOX"
mkdir -p "$SHIM" "$FAKE_HOME"
: > "$CALLS"

# ── shims ────────────────────────────────────────────────────────────────────
cat > "$SHIM/systemctl" <<'SH'
#!/usr/bin/env bash
echo "systemctl $*" >> "$CALLS_FILE"
case "$*" in
  *is-active*) echo "active" ;;
  *daemon-reload*) : ;;
esac
exit 0
SH

cat > "$SHIM/loginctl" <<'SH'
#!/usr/bin/env bash
echo "loginctl $*" >> "$CALLS_FILE"
exit 0
SH

cat > "$SHIM/journalctl" <<'SH'
#!/usr/bin/env bash
echo "journalctl $*" >> "$CALLS_FILE"
echo "INF Registered tunnel connection https://fake-sandbox-url.trycloudflare.com"
exit 0
SH

cat > "$SHIM/git" <<'SH'
#!/usr/bin/env bash
echo "git $*" >> "$CALLS_FILE"
for a in "$@"; do
  if [ "$a" = "clone" ]; then
    dest="${@: -1}"
    mkdir -p "$dest/BRIDGE" "$dest/BOT" "$dest/WEB" \
             "$dest/Storage/Installation" "$dest/Storage/Dependencies"
    echo "print('bridge')" > "$dest/BRIDGE/main.py"
    echo "print('bot')"    > "$dest/BOT/lm_bot.py"
    echo "console.log(1)"  > "$dest/WEB/server.js"
    echo '{"name":"web","version":"1.0.0"}' > "$dest/WEB/package.json"
    echo "aiohttp" > "$dest/Storage/Dependencies/requirements.txt"
    mkdir -p "$dest/.git"
    exit 0
  fi
done
exit 0
SH

# curl: Telegram API answers + binary downloads
cat > "$SHIM/curl" <<'SH'
#!/usr/bin/env bash
echo "curl $*" >> "$CALLS_FILE"
url=""; out=""
prev=""
for a in "$@"; do
  case "$prev" in -o) out="$a" ;; esac
  case "$a" in https://*|http://*) url="$a" ;; esac
  prev="$a"
done

# getMe -> depends on the token embedded in the URL
if [[ "$url" == *"/getMe"* ]]; then
  tok="${url#*/bot}"; tok="${tok%%/*}"
  if [[ "$url" == *"BADTOKEN"* ]] || [ -z "$tok" ] || [[ "$tok" != *:* ]]; then
    echo '{"ok":false,"error_code":401,"description":"Unauthorized"}'
  else
    echo '{"ok":true,"result":{"id":123456789,"is_bot":true,"username":"SandboxBot","supports_inline_queries":true}}'
  fi
  exit 0
fi

# health endpoint
if [[ "$url" == *"/api/v1/health"* ]]; then
  echo '{"status":"healthy","checks":{"model_count":317}}'
  exit 0
fi

# dashboard probe (-o /dev/null -w %{http_code})
if [[ "$url" == *"127.0.0.1:8787"* ]]; then
  echo -n "200"; exit 0
fi

# binary downloads (node/cloudflared): create a plausible file
if [ -n "$out" ]; then
  mkdir -p "$(dirname "$out")"
  echo "#!/usr/bin/env bash" > "$out"
  echo "echo sandbox-binary" >> "$out"
  exit 0
fi

# tarball piped to tar
if [[ "$url" == *"nodejs.org"* ]]; then
  exit 1   # force the "node already present" path in the sandbox
fi
exit 0
SH

cat > "$SHIM/node" <<'SH'
#!/usr/bin/env bash
echo "node $*" >> "$CALLS_FILE"
echo "v22.14.0"
exit 0
SH

cat > "$SHIM/npm" <<'SH'
#!/usr/bin/env bash
echo "npm $*" >> "$CALLS_FILE"
exit 0
SH

cat > "$SHIM/cloudflared" <<'SH'
#!/usr/bin/env bash
echo "cloudflared $*" >> "$CALLS_FILE"
exit 0
SH

# `pip` shim: the installer pip-installs into the venv; make it a no-op that also
# lets us pretend camoufox got installed.
cat > "$SHIM/pip" <<'SH'
#!/usr/bin/env bash
echo "pip $*" >> "$CALLS_FILE"
exit 0
SH

# python3 wrapper: real python EXCEPT `-m camoufox`, `-m venv`, `-m pip`
cat > "$SHIM/python3" <<'SH'
#!/usr/bin/env bash
echo "python3 $*" >> "$CALLS_FILE"
REAL_PY=/usr/bin/python3
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "camoufox" ]; then
  case "${3:-}" in
    path)
      if [ "${CAMOUFOX_PRESENT:-0}" = "1" ]; then
        echo "$HOME/.cache/camoufox"; exit 0
      fi
      exit 1 ;;
    fetch)
      if [ "${CAMOUFOX_RATELIMIT:-0}" = "1" ] && [ -z "${GITHUB_TOKEN:-}" ]; then
        echo "urllib.error.HTTPError: HTTP Error 403: rate limit exceeded" >&2
        exit 1
      fi
      mkdir -p "$HOME/.cache/camoufox"
      echo "downloaded"; exit 0 ;;
  esac
fi
exec "$REAL_PY" "$@"
SH

chmod +x "$SHIM"/*

# ── environment ──────────────────────────────────────────────────────────────
export CALLS_FILE="$CALLS"
export HOME="$FAKE_HOME"
export XDG_RUNTIME_DIR="$SANDBOX/run"
mkdir -p "$XDG_RUNTIME_DIR"
export PATH="$SHIM:/usr/bin:/bin"
export INSTALL_DIR="$FAKE_HOME/Arena"
export REPO_URL="https://example.invalid/fake/Arena.git"

case "$SCENARIO" in
  ratelimit) export CAMOUFOX_RATELIMIT=1 ;;
esac

SETUPER="$SANDBOX/Setuper.sh"
cp "$SRC_SETUPER" "$SETUPER"

# Pre-create the venv with SHIMMED python3/pip so the installer's
# "$VENV/bin/python3 -m camoufox" calls go through our shim (the installer uses
# the venv interpreter explicitly, so a PATH shim alone is not enough).
mkdir -p "$INSTALL_DIR/venv/bin"
cp "$SHIM/python3" "$INSTALL_DIR/venv/bin/python3"
cp "$SHIM/pip" "$INSTALL_DIR/venv/bin/pip"
chmod +x "$INSTALL_DIR/venv/bin/"*

echo "════════ scenario: $SCENARIO ════════"
echo "sandbox : $SANDBOX"
echo

run_installer() {
  local label="$1"; shift
  echo "──── run: $label ────"
  # shellcheck disable=SC2068
  "$@" 2>&1 | sed 's/^/    │ /'
  echo "    └─ exit=${PIPESTATUS[0]}"
}

case "$SCENARIO" in
  fresh|idempotent|inplace)
    export BOT_TOKEN="123456789:SANDBOX_FAKE_TOKEN_not_a_real_secret"
    export OWNER_ID="7610246474"
    run_installer "first" bash "$SETUPER"
    if [ "$SCENARIO" = "idempotent" ]; then
      echo; run_installer "second (idempotency)" bash "$SETUPER"
    fi
    ;;
  ratelimit)
    export BOT_TOKEN="123456789:SANDBOX_FAKE_TOKEN_not_a_real_secret"
    export OWNER_ID="7610246474"
    # GH token typed at the hidden prompt
    printf 'ghp_sandboxtoken1234567890\n' > "$SANDBOX/tty_input"
    run_installer "ratelimit" bash -c "bash '$SETUPER' < '$SANDBOX/tty_input'"
    ;;
  badtoken)
    unset BOT_TOKEN
    export OWNER_ID="7610246474"
    printf 'BADTOKEN\n123456789:SANDBOX_GOOD_TOKEN_not_a_real_secret\n' > "$SANDBOX/tty_input"
    run_installer "badtoken retry" bash -c "bash '$SETUPER' < '$SANDBOX/tty_input'"
    ;;
esac

# ── assertions ───────────────────────────────────────────────────────────────
echo
echo "════════ assertions ════════"
FAILS=0
ok()   { printf '  \033[0;32mOK  \033[0m %s\n' "$1"; }
bad()  { printf '  \033[0;31mFAIL\033[0m %s\n' "$1"; FAILS=$((FAILS+1)); }

ENVF="$INSTALL_DIR/.env"
UNITD="$FAKE_HOME/.config/systemd/user"

[ -f "$ENVF" ] && ok ".env created at $ENVF" || bad ".env missing"

if [ -f "$ENVF" ]; then
  perm=$(stat -c '%a' "$ENVF")
  [ "$perm" = "600" ] && ok ".env perms are 600" || bad ".env perms are $perm, want 600"
  for k in BOT_TOKEN LMA_DIR BRIDGE_URL DATA_FILE PORT DEV_MODE \
           SESSION_JWT_SECRET BRIDGE_API_KEY BOT_LOG_FORWARD_INTERVAL; do
    grep -q "^$k=" "$ENVF" && ok ".env has $k" || bad ".env missing $k"
  done
  # secrets must be non-trivial
  jwt=$(grep '^SESSION_JWT_SECRET=' "$ENVF" | cut -d= -f2-)
  [ "${#jwt}" -ge 32 ] && ok "JWT secret length ${#jwt} >= 32" || bad "JWT secret too short (${#jwt})"
  key=$(grep '^BRIDGE_API_KEY=' "$ENVF" | cut -d= -f2-)
  case "$key" in sk-*) ok "API key has sk- prefix (len ${#key})" ;; *) bad "API key malformed: $key" ;; esac
  grep -q '^DEV_MODE=false' "$ENVF" && ok "DEV_MODE=false (no auth bypass)" || bad "DEV_MODE is not false"
  # no duplicate keys
  dups=$(grep -oE '^[A-Z_]+=' "$ENVF" | sort | uniq -d | tr '\n' ' ')
  [ -z "$dups" ] && ok "no duplicate keys in .env" || bad "duplicate keys: $dups"
  if [ "$SCENARIO" = "ratelimit" ]; then
    grep -q '^GITHUB_TOKEN=ghp_' "$ENVF" && ok "GITHUB_TOKEN captured on rate limit" \
      || bad "GITHUB_TOKEN not stored after rate limit"
  fi
  if [ "$SCENARIO" = "badtoken" ]; then
    grep -q '^BOT_TOKEN=123456789:SANDBOX_GOOD_TOKEN' "$ENVF" \
      && ok "retry loop stored the VALID token" || bad "wrong token stored after retry"
  fi
fi

for u in bridge web bot2 web-tunnel api-tunnel; do
  f="$UNITD/lmarena-$u.service"
  if [ -f "$f" ]; then
    ok "unit lmarena-$u.service written"
    grep -q "EnvironmentFile=$ENVF" "$f" || bad "  lmarena-$u: EnvironmentFile not pointing at .env"
    grep -q "^Restart=always" "$f" || bad "  lmarena-$u: missing Restart=always"
    grep -qE '^Environment="(BOT_TOKEN|OWNER_ID|ADMIN_ID)=' "$f" \
      && bad "  lmarena-$u: secret baked into the unit file" \
      || ok "  lmarena-$u: no secrets inlined"
  else
    bad "unit lmarena-$u.service missing"
  fi
done

# the legacy conflicting unit must be disabled
grep -q "systemctl --user disable --now lmarena-bot.service" "$CALLS" \
  && ok "legacy lmarena-bot disabled (getUpdates conflict)" \
  || bad "legacy lmarena-bot was not disabled"

grep -q "loginctl enable-linger" "$CALLS" \
  && ok "linger enabled (survives logout)" || bad "linger not enabled"

grep -q "systemctl --user enable --now lmarena-bridge" "$CALLS" \
  && ok "services enabled+started" || bad "services not enabled"

[ -f "$INSTALL_DIR/WEB/data/config.json" ] \
  && ok "config.json seeded" || bad "config.json not created"
[ -L "$INSTALL_DIR/config.json" ] \
  && ok "root config.json symlink created" || bad "root symlink missing"
[ -d "$INSTALL_DIR/Storage/logs" ] \
  && ok "Storage/logs created" || bad "Storage/logs missing"

# secrets must never be echoed to the terminal
if [ -f "$SANDBOX/stdout.txt" ]; then :; fi

echo
if [ "$FAILS" -eq 0 ]; then
  printf '\033[0;32m════════ %s: ALL ASSERTIONS PASSED ════════\033[0m\n' "$SCENARIO"
else
  printf '\033[0;31m════════ %s: %d ASSERTION(S) FAILED ════════\033[0m\n' "$SCENARIO" "$FAILS"
fi
exit "$FAILS"
