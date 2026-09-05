"""Single source of truth for every secret in the project (.env-backed).

Why this module exists
----------------------
Secrets used to live inside ``WEB/data/config.json``: the arena auth token, the
cf_clearance cookie, browser cookies and the ``sk-`` API keys. That file is the
bridge's *runtime state* — it is rewritten constantly by background refresh
tasks, symlinked to the repo root, and served (indirectly) to a dashboard, so it
is a bad place to keep credentials. Everything sensitive now lives in a plain
``.env`` next to the repo root and config.json holds only non-secret state.

Layout::

    /home/forget/Arena/.env         <- the real secrets (chmod 600, gitignored)
    /home/forget/Arena/.env.example <- documented template, committed

Resolution order for every getter: ``os.environ`` first (systemd
``EnvironmentFile=`` / exported vars win), then the ``.env`` file, then a
default. That means a unit can override any value without touching the file.

The module is dependency-free and importable from both the bridge (package
context) and the bot (script context).
"""

from __future__ import annotations

import os
import re
import tempfile
from typing import Dict, List, Optional

# Repo root = parent of the directory holding this file (BRIDGE/ -> Arena/)
ROOT = os.environ.get("LMA_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.environ.get("LMA_ENV_FILE") or os.path.join(ROOT, ".env")

# Keys that must never be written into config.json
SECRET_KEYS = (
    "BOT_TOKEN",
    "SESSION_JWT_SECRET",
    "BRIDGE_API_KEY",
    "ARENA_AUTH_TOKEN",
    "ARENA_CF_CLEARANCE",
    "TELEGRAM_API_HASH",
    "GITHUB_TOKEN",
)

_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def read_env_file(path: str = None) -> Dict[str, str]:
    """Parse the .env file into a dict. Missing file -> empty dict."""
    path = path or ENV_PATH
    out: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                m = _LINE_RE.match(line)
                if m:
                    out[m.group(1)] = _unquote(m.group(2))
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return out


def get(key: str, default: str = "") -> str:
    """Environment wins over the file; both beat the default."""
    v = os.environ.get(key)
    if v is not None and str(v).strip() != "":
        return str(v).strip()
    v = read_env_file().get(key)
    if v is not None and str(v).strip() != "":
        return str(v).strip()
    return default


def get_int(key: str, default: Optional[int] = None) -> Optional[int]:
    raw = get(key, "")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def get_list(key: str) -> List[str]:
    """Comma-separated value -> list of non-empty items."""
    return [p.strip() for p in get(key, "").split(",") if p.strip()]


def set_many(values: Dict[str, object], path: str = None) -> bool:
    """Upsert keys in the .env file, preserving comments and key order.

    Written atomically with 0600 permissions. ``None`` values delete the key.
    Also mirrored into ``os.environ`` so the running process sees them at once.
    """
    path = path or ENV_PATH
    try:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except FileNotFoundError:
            lines = []

        remaining = dict(values)
        out: List[str] = []
        for line in lines:
            m = _LINE_RE.match(line)
            if m and m.group(1) in remaining:
                key = m.group(1)
                val = remaining.pop(key)
                if val is None:
                    continue  # delete
                out.append(f"{key}={val}")
            else:
                out.append(line)
        for key, val in remaining.items():
            if val is None:
                continue
            out.append(f"{key}={val}")

        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".env.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out).rstrip("\n") + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

        for key, val in values.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(val)
        return True
    except Exception:
        return False


def set_value(key: str, value: object, path: str = None) -> bool:
    return set_many({key: value}, path=path)


# ── Typed accessors ────────────────────────────────────────────────────────────

def bot_token() -> str:
    return get("BOT_TOKEN")


def owner_ids() -> List[int]:
    """Owner ids from OWNER_ID / ADMIN_ID / BOT_ALLOWED_USERS (any of them)."""
    out: List[int] = []
    for key in ("OWNER_ID", "ADMIN_ID", "BOT_ALLOWED_USERS"):
        for chunk in get_list(key):
            if chunk.isdigit() and int(chunk) not in out:
                out.append(int(chunk))
    return out


def api_keys() -> List[str]:
    """Bridge API keys. BRIDGE_API_KEY is primary; BRIDGE_API_KEYS adds more."""
    keys: List[str] = []
    primary = get("BRIDGE_API_KEY")
    if primary:
        keys.append(primary)
    for k in get_list("BRIDGE_API_KEYS"):
        if k not in keys:
            keys.append(k)
    return keys


def arena_auth_tokens() -> List[str]:
    """arena-auth-prod-v1 cookie values (newline/comma separated for rotation)."""
    raw = get("ARENA_AUTH_TOKEN")
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]
    return parts


def cf_clearance() -> str:
    return get("ARENA_CF_CLEARANCE")


def telegram_api_id() -> Optional[int]:
    return get_int("TELEGRAM_API_ID")


def telegram_api_hash() -> str:
    return get("TELEGRAM_API_HASH")


def log_group_id() -> Optional[int]:
    return get_int("BOT_LOG_GROUP_ID")


def log_topic_ids() -> Dict[str, Optional[int]]:
    return {
        "logs": get_int("BOT_LOG_TOPIC_ID"),
        "requests": get_int("BOT_REQUESTS_TOPIC_ID"),
        "web": get_int("BOT_WEB_TOPIC_ID"),
    }


def github_token() -> str:
    return get("GITHUB_TOKEN")


def redact(value: object, keep: int = 4) -> str:
    """Mask a secret for logs: 'sk-abcd…wxyz' style."""
    s = str(value or "")
    if len(s) <= keep * 2:
        return "*" * len(s)
    return f"{s[:keep]}…{s[-keep:]}"


def strip_secrets(config: dict) -> dict:
    """Remove secret material from a config dict before it is written to disk.

    The bridge keeps secrets in memory (loaded from .env) but must not persist
    them into config.json, which is world-readable state, symlinked into the repo
    root and mirrored by the dashboard.
    """
    if not isinstance(config, dict):
        return config
    for key in ("auth_token", "auth_tokens", "cf_clearance", "browser_cookies",
                "api_keys", "password"):
        config.pop(key, None)
    return config
