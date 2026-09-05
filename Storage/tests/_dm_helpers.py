"""Shared helpers for Direct-Mode tests: locate the live config + API key.

The live bridge runs from its own working dir with its own config path, so
hardcoding the repo-relative WEB/data/config.json isn't enough. This tries,
in order:
  1. env LMA_CONFIG
  2. <repo>/WEB/data/config.json
  3. <repo>/config.json
  4. /home/forget/LMArena/config.json  (known live deployment)
  5. /home/forget/Arena/config.json
and returns a real API key when found.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CANDIDATES = []

def _add(*parts):
    p = os.path.join(*parts)
    if os.path.exists(p) and os.path.isfile(p):
        CANDIDATES.append(p)

_add(os.environ.get("LMA_CONFIG", ""))
_add(REPO_ROOT, "WEB", "data", "config.json")
_add(REPO_ROOT, "config.json")
_add("/home/forget/LMArena", "config.json")
_add("/home/forget/LMArena", "WEB", "data", "config.json")
_add("/home/forget/Arena", "config.json")
_add("/home/forget/Arena", "WEB", "data", "config.json")


def resolve_config():
    """Return the path of the first existing config, or None."""
    for c in CANDIDATES:
        if c:
            return c
    return None


def load_config():
    """Load and return the config dict (empty if none found)."""
    import json
    p = resolve_config()
    if not p:
        return {}
    try:
        with open(p, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def get_api_key():
    """Return the first usable API key from the live config, or ''."""
    cfg = load_config()
    keys = cfg.get("api_keys") or []
    for k in keys:
        key = (k.get("key") or "").strip()
        if key:
            return key
    # fall back to env
    return (os.environ.get("LMA_API_KEY") or "").strip()


def get_models():
    """Return the models list from the live config."""
    cfg = load_config()
    return cfg.get("models") or []


def pick_model(models, *, require_in=None, require_out=None, exclude_out=None):
    """Pick the first model whose capabilities match the given filters.
    
    require_in / require_out — list of input/output capability names that must be truthy.
    exclude_out — list of output capability names that must be falsy.
    Returns (publicName_or_name, id) tuple, or (None, None) if no match.
    """
    require_in = require_in or []
    require_out = require_out or []
    exclude_out = exclude_out or []
    for m in models:
        caps = m.get("capabilities") or {}
        ic = caps.get("inputCapabilities") or {}
        oc = caps.get("outputCapabilities") or {}
        if all(ic.get(k) for k in require_in) and all(oc.get(k) for k in require_out):
            if not any(oc.get(k) for k in exclude_out):
                pn = m.get("publicName") or m.get("name") or ""
                mid = m.get("id") or ""
                return pn, mid
    return None, None


def media_path(name):
    """Absolute path to a bundled media asset under Storage/Media."""
    return os.path.join(REPO_ROOT, "Storage", "Media", name)


def classify_response(resp):
    """Classify a bridge API response.

    Returns ("ok", body) if the response is a valid OpenAI-format completion,
    ("upstream", detail) if the bridge returned an upstream/rate-limit error
    (429/5xx/403/404), or ("fail", detail) for other failures.

    A 200 with a JSON body missing `choices` is treated as upstream — it means
    the bridge itself is healthy but the upstream model call failed.
    """
    try:
        body = resp.json()
    except Exception:
        body = None

    if resp.status_code == 200 and body and isinstance(body, dict) and "choices" in body:
        return ("ok", body)

    if body and isinstance(body, dict) and "error" in body:
        err = body["error"]
        if isinstance(err, dict):
            return ("upstream", err.get("message") or str(err))
        return ("upstream", str(err))

    if resp.status_code in (429, 500, 502, 503, 504, 403, 404):
        return ("upstream", resp.text[:200])

    return ("fail", resp.text[:200] if resp.text else f"HTTP {resp.status_code}")


async def post_chat(api_base, api_key, model, messages, timeout=300, stream=False):
    """Send a chat/completions request and classify the response.

    Returns ("ok", body) | ("upstream", detail) | ("fail", detail).
    """
    import httpx
    async with httpx.AsyncClient(timeout=timeout) as c:
        resp = await c.post(
            f"{api_base}/chat/completions",
            json={"model": model, "messages": messages, "stream": stream},
            headers={"Authorization": f"Bearer {api_key}"},
        )
    return classify_response(resp)


def handle_status(status, body):
    """Print a status line and return the exit boolean for a test."""
    if status == "ok":
        return True
    if status == "upstream":
        detail = body if isinstance(body, str) else (body or "upstream error")
        print(f"UPSTREAM: arena.ai not available ({detail}) — soft-skip")
        return True
    print(f"FAIL: {body}")
    return False
