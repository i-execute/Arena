#!/usr/bin/env bash
# LMArena Bridge — one-liner bootstrap.
#
#   curl -fsSL https://raw.githubusercontent.com/i-execute/Arena/main/Storage/Installation/QuickStart.sh | bash
#
# Downloads Setuper.sh and runs it. Setuper does the real work and asks for a
# single secret (the bot token); everything else is configured inside Telegram.
set -euo pipefail

REPO="${REPO:-i-execute/Arena}"
BRANCH="${BRANCH:-main}"
RAW="https://raw.githubusercontent.com/${REPO}/${BRANCH}/Storage/Installation/Setuper.sh"
TMP="$(mktemp /tmp/LMArena_setuper.XXXXXX.sh)"
trap 'rm -f "$TMP"' EXIT

if [ "$(id -u)" -eq 0 ]; then
    echo "Do not run as root — services install as systemd --user units." >&2
    exit 1
fi

echo "Downloading Setuper.sh from ${REPO}@${BRANCH}..."
if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$RAW" -o "$TMP"
elif command -v wget >/dev/null 2>&1; then
    wget -qO "$TMP" "$RAW"
else
    echo "ERROR: install curl or wget first" >&2
    exit 1
fi

[ -s "$TMP" ] || { echo "ERROR: download produced an empty file" >&2; exit 1; }
chmod +x "$TMP"

# stdin is the pipe when invoked via `curl | bash`, so hand the installer the tty
# for its prompts. Falls back to plain stdin in non-interactive environments.
if [ -e /dev/tty ]; then
    bash "$TMP" "$@" < /dev/tty
else
    bash "$TMP" "$@"
fi
