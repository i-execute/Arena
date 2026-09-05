"""
LMArena Bot — Rich Messages (Bot API 10.3), TL-tests style.

Every menu streams into a NEW message via sendRichMessageDraft → sendRichMessage,
with <tg-thinking> frames and premium <tg-emoji>. Tunnels read from journalctl.
"""
import asyncio
import aiohttp
import traceback
import time
import os
import sys
import re
import json
import html as html_mod
import inspect
import subprocess

LMA_DIR = os.environ.get("LMA_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LMA_DIR)
from BRIDGE import secrets_env as se  # noqa: E402  (secrets live in the root .env)

try:
    from BOT import mtproto as _mt  # noqa: E402
except Exception:  # running as a plain script
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "_mt", os.path.join(os.path.dirname(os.path.abspath(__file__)), "mtproto.py"))
    _mt = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mt)

LOG_DIR = os.path.join(LMA_DIR, "Storage", "logs")
CONFIG_PATH = os.path.join(LMA_DIR, "WEB", "data", "config.json")
SITES_FILE = "/tmp/lmarena_deployer_sites.json"
BRIDGE_URL = se.get("BRIDGE_URL", "http://127.0.0.1:6767")

# Every credential comes from .env (env var > .env file). config.json holds only
# non-secret runtime state now — see BRIDGE/secrets_env.py.
TOKEN = se.bot_token()
API_URL = f"https://api.telegram.org/bot{TOKEN}"

# Premium emoji IDs from TL-tests
EMOJI = {
    "ok": '<tg-emoji emoji-id="5447363161034346459">👌</tg-emoji>',
    "cool": '<tg-emoji emoji-id="5449619723966761441">😌</tg-emoji>',
    "stats": '<tg-emoji emoji-id="5384182740411240426">💯</tg-emoji>',
    "brain": '<tg-emoji emoji-id="5447595110743168717">🧠</tg-emoji>',
    "format": '<tg-emoji emoji-id="5192784923093652913">📅</tg-emoji>',
    "map": '<tg-emoji emoji-id="5447163161587241349">🗺</tg-emoji>',
    "math": '<tg-emoji emoji-id="5384182985224374928">🧐</tg-emoji>',
    "refresh": '<tg-emoji emoji-id="5447271394763099136">🤔</tg-emoji>',
    "up": '<tg-emoji emoji-id="5190683945351535076">🤩</tg-emoji>',
    "down": '<tg-emoji emoji-id="5193200486949346651">😞</tg-emoji>',
}


def esc(t):
    return html_mod.escape(str(t))


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def load_sites():
    try:
        with open(SITES_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _get_tunnel_url(service):
    """Return the CURRENT quick-tunnel URL for one cloudflared unit.

    cloudflared quick tunnels mint a new trycloudflare.com URL on every
    process start. The reliable source is the "Your quick Tunnel has been
    created" banner in the unit journal — scanning only the last 50 lines of
    `systemctl status` misses it for quiet tunnels (no request logs), which
    made the API tunnel row disappear from the Tunnels menu.
    """
    try:
        r = subprocess.run(
            ["journalctl", "--user", "-u", f"{service}.service", "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            banner = None
            for line in r.stdout.split("\n"):
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if m:
                    banner = m.group(0)  # keep the LAST one = current tunnel
            if banner:
                return banner
    except Exception:
        pass
    # Fallback: scan systemctl status (older cloudflared versions / no journal access)
    try:
        r = subprocess.run(
            ["systemctl", "--user", "status", f"{service}.service", "--no-pager", "-n", "200"],
            capture_output=True, text=True, timeout=10,
        )
        urls = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", r.stdout)
        if urls:
            return urls[-1]
    except Exception:
        pass
    return None


def get_tunnel_urls():
    """Get active tunnel URLs keyed by display name (Dashboard / API)."""
    urls = {}
    for svc, disp in (
        ("lmarena-web-tunnel", "Dashboard"),
        ("lmarena-api-tunnel", "API"),
    ):
        u = _get_tunnel_url(svc)
        if u:
            urls[disp] = u
    # Also check legacy deployer sites file
    sites = load_sites()
    for sid, s in sites.items():
        u = s.get("url", "")
        if u:
            name = s.get("name", sid[:8])
            urls[name] = u
    return urls


def restart_tunnels():
    """Restart tunnel daemons, then return fresh URLs (sync, called off the event loop)."""
    try:
        subprocess.run(
            ["systemctl", "--user", "restart", "lmarena-web-tunnel", "lmarena-api-tunnel"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as e:
        print(f"restart_tunnels error: {e}")
    # Wait for cloudflared to establish connections (up to 20s)
    for _ in range(10):
        time.sleep(2)
        urls = get_tunnel_urls()
        if urls:
            return urls
    return get_tunnel_urls()


def _restart_tunnel_msg() -> str:
    """Call restart_tunnels() and return HTML result for bot display."""
    urls = restart_tunnels()
    out = "<h1>Tunnel Restart Complete</h1>\n"
    rows = []
    for name in ("Dashboard", "API"):
        u = urls.get(name)
        if u:
            rows.append(f'<tr><td><b>{esc(name)}</b></td><td><code>{esc(u)}</code></td></tr>')
        else:
            rows.append(f'<tr><td><b>{esc(name)}</b></td><td>{EMOJI["down"]} down</td></tr>')
    out += '<table><tr><th>Tunnel</th><th>URL</th></tr>' + "".join(rows) + '</table>\n'
    return out


def read_logs():
    try:
        files = sorted(
            [p for p in os.listdir(LOG_DIR) if p.endswith(".log")],
            key=lambda p: os.path.getmtime(os.path.join(LOG_DIR, p)), reverse=True,
        )[:2]
        parts = []
        for name in files:
            with open(os.path.join(LOG_DIR, name), errors="replace") as f:
                lines = f.read().strip().split("\n")
            parts.append(f"<b>{esc(name)}</b>\n{esc(chr(10).join(lines[-10:]))}")
        return "\n\n".join(parts) or "<i>no logs yet</i>"
    except Exception:
        return "<i>no logs yet</i>"


def read_bot_log(n=40):
    """Read the last N lines of LOG_DIR/bot.log (the bot's own log)."""
    path = os.path.join(LOG_DIR, "bot.log")
    try:
        with open(path, errors="replace") as f:
            lines = f.read().splitlines()
        if not lines:
            return "<i>bot.log is empty yet</i>"
        return "\n".join(lines[-n:])
    except FileNotFoundError:
        return f"<i>bot.log not found ({path})</i>"
    except Exception as e:
        return f"<i>cannot read bot.log: {esc(e)}</i>"


def get_real_stats():
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_s = float(f.readline().split()[0])
            uptime_str = f"{int(uptime_s // 86400)}d {int((uptime_s % 86400) // 3600)}h {int((uptime_s % 3600) // 60)}m"
        with open('/proc/loadavg', 'r') as f:
            load = f.readline().split()[:3]
            cpu_str = f"{load[0]}, {load[1]}, {load[2]}"
            cpu_pct = min(100, float(load[0]) * 10)
        with open('/proc/meminfo', 'r') as f:
            content = f.read()
            total = int(re.search(r"MemTotal:\s+(\d+)", content).group(1))
            free = int(re.search(r"MemFree:\s+(\d+)", content).group(1))
            buffers = int(re.search(r"Buffers:\s+(\d+)", content).group(1))
            cached = int(re.search(r"Cached:\s+(\d+)", content).group(1))
            used = total - free - buffers - cached
            ram_pct = (used / total) * 100
            ram_str = f"{used // 1024} MB / {total // 1024} MB"
        return uptime_str, cpu_str, cpu_pct, ram_str, ram_pct
    except Exception:
        return "N/A", "N/A", 0, "N/A", 0


def gen_bar(pct, length=12):
    pct = max(0, min(100, pct))
    filled = int((pct / 100) * length)
    return "█" * filled + "░" * (length - filled)


async def bridge_health():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{BRIDGE_URL}/api/v1/health", timeout=aiohttp.ClientTimeout(total=6)) as r:
                return r.status
    except Exception:
        return None


# ── Menu builders ───────────────────────────────────────────────────────────

def build_main():
    return (
        f'<h1>{EMOJI["cool"]} LMArena Bridge</h1>\n'
        '<p>OpenAI-compatible gateway to <b>lmarena.ai</b>. Live metrics.</p>\n'
        '<tg-button-row>'
        '<tg-button type="callback_data" data="st">Status</tg-button>'
        '<tg-button type="callback_data" data="mod">Models</tg-button>'
        '</tg-button-row>\n'
        '<tg-button-row>'
        '<tg-button type="callback_data" data="use">Usage</tg-button>'
        '<tg-button type="callback_data" data="logs">Logs</tg-button>'
        '</tg-button-row>\n'
        '<tg-button-row>'
        '<tg-button type="callback_data" data="tun">Tunnels</tg-button>'
        '<tg-button type="callback_data" data="setup">Setup</tg-button>'
        '</tg-button-row>\n'
    )


def build_status(health):
    uptime, cpu, cpu_pct, ram, ram_pct = get_real_stats()
    cfg = load_config()
    models = len(cfg.get("models", []))
    keys = len(se.api_keys())  # keys live in .env, not config.json
    cpu_bar = gen_bar(cpu_pct)
    ram_bar = gen_bar(ram_pct)
    health_txt = f'<code>{health}</code>' if health else '<code>?</code>'
    return (
        f'<h1>{EMOJI["stats"]} Status</h1>\n'
        '<table>'
        '<tr><th>Component</th><th>State</th></tr>'
        f'<tr><td><b>Bridge :6767</b></td><td>{health_txt}</td></tr>'
        f'<tr><td><b>Models</b></td><td>{models}</td></tr>'
        f'<tr><td><b>API keys</b></td><td>{keys}</td></tr>'
        '</table>\n'
        f'<h3>{EMOJI["stats"]} Server (from /proc)</h3>\n'
        '<table>'
        '<tr><th>Metric</th><th>Value</th><th>Load</th></tr>'
        f'<tr><td><b>CPU Load</b></td><td>{cpu}</td><td><code>{cpu_bar}</code></td></tr>'
        f'<tr><td><b>Memory</b></td><td>{ram}</td><td><code>{ram_bar}</code></td></tr>'
        f'<tr><td><b>Uptime</b></td><td>{uptime}</td><td>{EMOJI["ok"]}</td></tr>'
        '</table>\n'
        '<tg-button-row>'
        '<tg-button type="callback_data" data="st">Refresh</tg-button>'
        '<tg-button type="callback_data" data="back">Back</tg-button>'
        '</tg-button-row>\n'
    )


def build_models():
    cfg = load_config()
    models = cfg.get("models", [])
    caps_count = {}
    for m in models:
        oc = m.get("capabilities", {}).get("outputCapabilities", {})
        for cap in ("text", "image", "video", "web", "search"):
            if oc.get(cap):
                caps_count[cap] = caps_count.get(cap, 0) + 1
    rows = "".join(
        f'<tr><td>{cap}</td><td>{caps_count.get(cap, 0)}</td></tr>'
        for cap in ("text", "image", "video", "web", "search")
    )
    ranked = sorted(models, key=lambda m: m.get("rank", 999))[:5]
    top = "".join(f'<li><b>{esc(str(m.get("publicName") or m.get("name", "?"))[:40])}</b></li>' for m in ranked)
    return (
        f'<h1>{EMOJI["format"]} Models</h1>\n'
        f'<p>Total: <b>{len(models)}</b> (userSelectable + provider)</p>\n'
        '<table>'
        '<tr><th>Capability</th><th>Count</th></tr>'
        f'{rows}'
        '</table>\n'
        '<h3>Top 5</h3>\n'
        f'<ul>{top}</ul>\n'
        '<tg-button-row><tg-button type="callback_data" data="back">Back</tg-button></tg-button-row>\n'
    )


def build_usage():
    cfg = load_config()
    usage = cfg.get("usage_stats", {})
    total = sum(usage.values()) if isinstance(usage, dict) else 0
    ut = cfg.get("usage_today", {})
    today = sum(ut.values()) if isinstance(ut, dict) else 0
    top = sorted(usage.items(), key=lambda x: -x[1])[:5] if isinstance(usage, dict) else []
    top_html = "".join(
        f'<tr><td><b>{esc(str(name)[:30])}</b></td><td>{cnt}</td></tr>' for name, cnt in top
    )
    return (
        f'<h1>{EMOJI["stats"]} Request Usage</h1>\n'
        '<table>'
        f'<tr><td><b>Total</b></td><td>{total}</td></tr>'
        f'<tr><td><b>Today</b></td><td>{today}</td></tr>'
        '</table>\n'
        '<h3>By model</h3>\n'
        '<table>'
        '<tr><th>Model</th><th>Requests</th></tr>'
        f'{top_html or "<tr><td colspan=2><i>none yet</i></td></tr>"}'
        '</table>\n'
        '<tg-button-row><tg-button type="callback_data" data="back">Back</tg-button></tg-button-row>\n'
    )


def build_logs():
    body = read_logs()
    return (
        f'<h1>{EMOJI["format"]} Logs</h1>\n'
        f'<pre>{esc(body[:3500])}</pre>\n'
        '<tg-button-row><tg-button type="callback_data" data="back">Back</tg-button></tg-button-row>\n'
    )


def build_bot_logs(n=40):
    """/logs — last N lines of the bot's own bot.log file."""
    body = read_bot_log(n=n)
    return (
        f'<h1>{EMOJI["format"]} Bot log (last {n})</h1>\n'
        f'<pre>{esc(body[:3500])}</pre>\n'
        '<tg-button-row><tg-button type="callback_data" data="back">Back</tg-button></tg-button-row>\n'
    )


def build_tunnel():
    urls = get_tunnel_urls()
    parts = []
    if urls:
        for name, u in urls.items():
            parts.append(f'<tr><td><b>{esc(name)}</b></td><td><a href="{esc(u)}">link</a></td></tr>')
    return (
        f'<h1>{EMOJI["ok"]} Tunnels</h1>\n'
        '<table>'
        '<tr><th>Tunnel</th><th>URL</th></tr>'
        f'{"".join(parts) or "<tr><td colspan=2><i>no active tunnels</i></td></tr>"}'
        '</table>\n'
        '<tg-button-row>'
        '<tg-button type="callback_data" data="tun_r">Restart</tg-button>'
        '<tg-button type="callback_data" data="tun">Refresh</tg-button>'
        '</tg-button-row>\n'
        '<tg-button-row>'
        '<tg-button type="callback_data" data="back">Back</tg-button>'
        '</tg-button-row>\n'
    )


# ── Rich streaming ──────────────────────────────────────────────────────────

async def stream_tunnel_restart(session, chat_id, message_id):
    """Restart both cloudflared units with streamed <tg-thinking>, then the URL table.

    The restart itself takes ~10-25s, which is right at the draft expiry window,
    so the thinking loop keeps re-sending frames while the worker thread runs.
    """
    draft_id = _new_draft_id()
    header = f'<h1>{EMOJI["ok"]} Tunnels</h1>\n'
    loop = asyncio.get_event_loop()
    private = is_private(chat_id)

    # Instant feedback on the tapped message and drop its buttons so the user
    # cannot fire a second restart while this one runs. editMessageText must NOT
    # carry <tg-thinking> (RICH_MESSAGE_BLOCK_UNSUPPORTED) — plain text only here.
    await send_request(session, "editMessageText", {
        "chat_id": chat_id, "message_id": message_id,
        "rich_message": {"html": header + '<p>Restarting tunnels...\u258d</p>'},
    })

    restart_task = loop.run_in_executor(None, restart_tunnels)
    stop = asyncio.Event()
    steps = [
        "Stopping tunnel daemons...",
        "Restarting dashboard tunnel...",
        "Restarting api tunnel...",
        "Waiting for cloudflared to connect...",
        "Fetching fresh URLs...",
    ]
    thinker = None
    if private:
        thinker = asyncio.ensure_future(
            _thinking_loop(session, chat_id, draft_id, header, "", steps, stop))
    try:
        urls = await restart_task
    finally:
        stop.set()
        if thinker is not None:
            await thinker

    urls = urls or get_tunnel_urls()
    rows = []
    for name in ("Dashboard", "API"):
        u = urls.get(name)
        rows.append(
            f'<tr><td><b>{esc(name)}</b></td><td><a href="{esc(u)}">{esc(u)}</a></td></tr>'
            if u else
            f'<tr><td><b>{esc(name)}</b></td><td>{EMOJI["down"]} down</td></tr>'
        )
    final = (
        header
        + '<table><tr><th>Tunnel</th><th>URL</th></tr>' + "".join(rows) + '</table>\n'
        '<tg-button-row>'
        '<tg-button type="callback_data" data="tun_r">Restart</tg-button>'
        '<tg-button type="callback_data" data="tun">Refresh</tg-button>'
        '</tg-button-row>\n'
        '<tg-button-row>'
        '<tg-button type="callback_data" data="back">Back</tg-button>'
        '</tg-button-row>\n'
    )
    await send_request(session, "sendRichMessage", {
        "chat_id": chat_id,
        "rich_message": {"html": final},
    })


async def send_request(session, method, payload):
    url = f"{API_URL}/{method}"
    for _ in range(3):
        try:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    if data.get("error_code") == 429:
                        ra = data.get("parameters", {}).get("retry_after", 1)
                        await asyncio.sleep(ra + 0.1)
                        continue
                    print(f"API Error ({method}):", str(data)[:200])
                return data
        except Exception as e:
            print(f"Request Exception ({method}):", e)
            await asyncio.sleep(1)
    return {"ok": False}


# ── Topic (forum) support ───────────────────────────────────────────────────
# Log destination resolution order:
#   1. env BOT_LOG_GROUP_ID / BOT_LOG_TOPIC_ID  (explicit override)
#   2. config.json  log_group_id / log_topic_id / log_requests_topic_id
# The config path is what the bot WRITES when it is added to a group, so the
# forwarder keeps working after a restart without editing any systemd unit.
# Previously only the env var was read and no unit ever set it, which is why
# /logs_fwd and /reqs always answered "BOT_LOG_GROUP_ID not set".
# Topic state: cid -> {"logs": topic_id, "requests": topic_id}
_topic_state: dict[int, dict[str, int]] = {}
# Continuous forwarder state
FORWARD_INTERVAL_S = float(se.get("BOT_LOG_FORWARD_INTERVAL", "20"))
_fwd_seen: set[int] = set()
_fwd_seen_cap = 800


def _cfg_int(key):
    """Legacy fallback: read a numeric field from config.json (pre-.env installs)."""
    try:
        v = load_config().get(key)
        return int(v) if v not in (None, "", 0) else None
    except Exception:
        return None


def log_group_id():
    """Target group for log forwarding: .env first, then legacy config.json."""
    gid = se.log_group_id()
    return gid if gid is not None else _cfg_int("log_group_id")


def log_topic_id(kind="logs"):
    """Topic id inside the log group: live state, then .env, then legacy config."""
    gid = log_group_id()
    if gid is not None:
        tid = (_topic_state.get(gid) or {}).get(kind)
        if tid:
            return tid
    tid = se.log_topic_ids().get(kind)
    if tid:
        return tid
    legacy = {"logs": "log_topic_id",
              "requests": "log_requests_topic_id",
              "web": "log_web_topic_id"}.get(kind, "log_topic_id")
    return _cfg_int(legacy)


def save_log_destination(chat_id, topics=None):
    """Persist the log group + topic ids into .env (survives restarts)."""
    updates = {"BOT_LOG_GROUP_ID": int(chat_id)}
    _keys = {"logs": "BOT_LOG_TOPIC_ID",
             "requests": "BOT_REQUESTS_TOPIC_ID",
             "web": "BOT_WEB_TOPIC_ID"}
    for kind, tid in (topics or {}).items():
        key = _keys.get(kind)
        if key:
            updates[key] = int(tid)
    ok = se.set_many(updates)
    print(f"[bot] log destination {'saved' if ok else 'SAVE FAILED'}: "
          f"chat={chat_id} topics={topics or {}}")
    return ok


def read_bridge_log_lines(n=20):
    """Last N lines of the bridge log file itself (not the menu-formatted view)."""
    path = os.path.join(LOG_DIR, "bridge.log")
    try:
        with open(path, errors="replace") as f:
            return f.read().splitlines()[-n:]
    except Exception:
        return []


# ── Log forwarding as Rich messages ─────────────────────────────────────────
#
# The old forwarder dumped every new line into ONE <pre> blob, so a single request
# arrived as an unreadable wall containing base64 Set-Cookie headers, SSE `a0:`
# fragments and the parse summary all glued together. Rich messages allow many
# separate blocks per message, so the log is now split into logical sections and
# each section becomes its own fenced code block — same content, readable shape.
#
# Nothing is filtered out: full headers, full SSE dump, full summary. Rich HTML
# caps at 32768 chars per message, so oversized batches split across messages.

RICH_LIMIT = 30000          # keep headroom under the 32768 hard cap
BLOCK_CHAR_LIMIT = 3500     # per code block, so Telegram renders it as a block
MAX_BLOCKS_PER_MSG = 12

# Lines that open a new logical section in bridge.log. Ordered: the first match
# wins, so specific markers must precede generic ones. Pure "=" rules are NOT
# section starts — they are separators that would otherwise steal the title from
# the content that follows them.
_SECTION_MARKERS = (
    ("\U0001f535 NEW API REQUEST RECEIVED", "new request"),
    ("\U0001f4e5 Request body keys", "request details"),
    ("\U0001f504 Recaptcha token expired", "recaptcha refresh"),
    ("\U0001f512 Starting reCAPTCHA", "recaptcha refresh"),
    ("\U0001f4ad Auto-generated Conversation ID", "session"),
    ("\U0001f195 Creating NEW conversation", "session"),
    ("\u267b\ufe0f  Reusing", "session"),
    ("\U0001f680 Making API request", "outbound request"),
    ("\U0001f4cb Response headers", "upstream headers"),
    ("\U0001f50d Processing response", "response processing"),
    ("\U0001f4c4 First 500 chars", "raw SSE body"),
    ("\U0001f4ca Parsing response lines", "parse trace"),
    ("\u2705 Response text preview", "result"),
    ("\U0001f4be Saved new session", "session saved"),
    ("\U0001f504 Starting scheduled", "scheduled refresh"),
    ("Starting initial data retrieval", "camoufox scrape"),
    ("\U0001f9ca Camoufox proxy", "camoufox proxy"),
    ("\U0001f510 Secrets synced", "secrets sync"),
    ("\u274c", "errors"),
)

# Lines that are pure separators — kept in the body, never used as a title.
def _is_separator(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and set(stripped) <= {"=", "-"} and len(stripped) >= 20


# Severity classification for the summary table. This is a *count* of markers for
# the header table — nothing is filtered from the forwarded body.
_SEVERITY = (
    ("\u274c", "errors"),
    ("\u26a0\ufe0f", "warnings"),
    ("\u23f1\ufe0f", "rate limits"),
    ("\U0001f512", "auth"),
    ("\U0001f510", "secrets"),
    ("\U0001f9ca", "browser"),
    ("\U0001f504", "refresh"),
    ("\U0001f4be", "sessions"),
    ("\u2705", "ok"),
)


def _classify(lines):
    """Count severity markers across a batch of log lines."""
    counts = {}
    for ln in lines:
        for glyph, label in _SEVERITY:
            if glyph in ln:
                counts[label] = counts.get(label, 0) + 1
    return counts


def split_log_blocks(lines, *, block_limit=BLOCK_CHAR_LIMIT):
    """Group log lines into (title, text) sections.

    A new section starts on a known marker; long sections are chunked further so
    each rendered code block stays inside Telegram's per-block rendering budget.
    """
    sections = []
    title = "log"
    buf = []

    def flush():
        if not buf:
            return
        text = "\n".join(buf)
        # split oversized sections into numbered parts, never dropping content
        if len(text) <= block_limit:
            sections.append((title, text))
            return
        parts, cur, cur_len = [], [], 0
        for ln in buf:
            if cur_len + len(ln) + 1 > block_limit and cur:
                parts.append("\n".join(cur))
                cur, cur_len = [], 0
            cur.append(ln)
            cur_len += len(ln) + 1
        if cur:
            parts.append("\n".join(cur))
        for i, part in enumerate(parts, 1):
            sections.append((f"{title} {i}/{len(parts)}", part))

    for ln in lines:
        marker_label = None
        if not _is_separator(ln):
            for needle, label in _SECTION_MARKERS:
                if needle and needle in ln:
                    marker_label = label
                    break
        if marker_label and marker_label != title:
            flush()
            buf = []
            title = marker_label
        buf.append(ln)
    flush()
    return sections


def render_log_rich(sections, *, source="bridge", total_lines=0, counts=None):
    """One Rich message: header + severity table + one code block per section."""
    head = [f'<h1>{EMOJI["format"]} {esc(source)} log</h1>']
    rows = [f'<tr><td><b>new lines</b></td><td>{total_lines}</td></tr>',
            f'<tr><td><b>blocks</b></td><td>{len(sections)}</td></tr>']
    for label, n in sorted((counts or {}).items(), key=lambda kv: -kv[1]):
        rows.append(f'<tr><td>{esc(label)}</td><td>{n}</td></tr>')
    head.append('<table><tr><th>metric</th><th>count</th></tr>' + "".join(rows) + '</table>')
    body = "\n".join(head)
    for title, text in sections:
        block = (f'<p><b>{esc(title)}</b></p>\n'
                 f'<pre><code class="language-log">{esc(text)}</code></pre>')
        body += "\n" + block
    return body


def chunk_sections(sections, *, limit=RICH_LIMIT, max_blocks=MAX_BLOCKS_PER_MSG):
    """Split sections across several Rich messages so each stays under the cap."""
    out, cur, cur_len = [], [], 0
    for title, text in sections:
        cost = len(text) + len(title) + 120  # tags + escaping headroom
        if cur and (cur_len + cost > limit or len(cur) >= max_blocks):
            out.append(cur)
            cur, cur_len = [], 0
        cur.append((title, text))
        cur_len += cost
    if cur:
        out.append(cur)
    return out


async def send_log_rich(session, lines, *, source="bridge", topic_id=None, chat_id=None):
    """Deliver a batch of log lines as Rich message(s) with per-section blocks."""
    gid = chat_id if chat_id is not None else log_group_id()
    if gid is None or not lines:
        return False
    sections = split_log_blocks(lines)
    counts = _classify(lines)
    tid = topic_id if topic_id is not None else log_topic_id("logs")
    ok_all = True
    groups = chunk_sections(sections)
    for i, group in enumerate(groups, 1):
        label = source if len(groups) == 1 else f"{source} ({i}/{len(groups)})"
        html = render_log_rich(group, source=label,
                               total_lines=len(lines), counts=counts)
        payload = {"chat_id": gid, "rich_message": {"html": html}}
        if tid:
            payload["message_thread_id"] = tid
        r = await send_request(session, "sendRichMessage", payload)
        if (r or {}).get("ok"):
            print(f"[bot] log rich -> topic {tid}: {label} "
                  f"{len(group)} blocks, {len(html)} chars")
        if not (r or {}).get("ok"):
            # Rich rejected (unsupported block / too long) -> plain <pre> fallback
            # so a log line is never silently lost.
            plain = "\n\n".join(f"{t}\n{x}" for t, x in group)
            fb = {"chat_id": gid, "parse_mode": "HTML",
                  "text": f"<b>{esc(label)}</b>\n<pre>{esc(plain[:3800])}</pre>"}
            if tid:
                fb["message_thread_id"] = tid
            r = await send_request(session, "sendMessage", fb)
            ok_all = ok_all and bool((r or {}).get("ok"))
        await asyncio.sleep(0.25)
    return ok_all


async def forward_bridge_logs(session, n: int = 20, topic_id: int | None = None):
    """Forward the last N bridge log lines on demand (/logs_fwd, /reqs)."""
    lines = read_bridge_log_lines(n)
    if not lines:
        lines = ["(no bridge logs yet)"]
    return await send_log_rich(session, lines, source="bridge", topic_id=topic_id)


def read_log_lines(name, n=200):
    """Last N lines of any file in Storage/logs."""
    path = os.path.join(LOG_DIR, name)
    try:
        with open(path, errors="replace") as f:
            return f.read().splitlines()[-n:]
    except Exception:
        return []


# ── Web topic: tunnel URL changes + dashboard state ─────────────────────────
#
# trycloudflare URLs rotate on every tunnel restart, and until now the new URL
# only existed in journalctl. The watcher below posts a card to the Web topic
# whenever a URL changes (or a tunnel goes down/comes back), so the current
# dashboard/API links are always findable in Telegram.

_web_state: dict = {}      # name -> last seen url ("" when down)
_web_primed = False


def _svc_active(unit: str) -> bool:
    try:
        out = subprocess.run(["systemctl", "--user", "is-active", unit],
                             capture_output=True, text=True, timeout=6)
        return out.stdout.strip() == "active"
    except Exception:
        return False


def render_web_card(changes, urls, *, reason="update"):
    """Rich card describing the current tunnel state and what changed."""
    rows = []
    for name, unit in (("Dashboard", "lmarena-web-tunnel"), ("API", "lmarena-api-tunnel")):
        u = urls.get(name) or ""
        state = "up" if u else "down"
        cell = f'<a href="{esc(u)}">{esc(u)}</a>' if u else "—"
        rows.append(f'<tr><td><b>{esc(name)}</b></td><td>{state}</td><td>{cell}</td></tr>')
        rows.append(f'<tr><td>service</td><td colspan="2"><code>{esc(unit)}</code> '
                    f'{"active" if _svc_active(unit) else "inactive"}</td></tr>')

    chg = "".join(
        f'<li><b>{esc(n)}</b>: <code>{esc(old or "down")}</code> → '
        f'<code>{esc(new or "down")}</code></li>'
        for n, old, new in changes
    )
    icon = EMOJI["up"] if any(urls.values()) else EMOJI["down"]
    html = (f'<h1>{icon} Web / tunnels ({esc(reason)})</h1>\n'
            '<table><tr><th>endpoint</th><th>state</th><th>url</th></tr>'
            + "".join(rows) + '</table>\n')
    if chg:
        html += f'<p><b>changed</b></p>\n<ul>{chg}</ul>\n'
    html += ('<tg-button-row>'
             '<tg-button type="callback_data" data="tun">Refresh</tg-button>'
             '<tg-button type="callback_data" data="tun_r">Restart tunnels</tg-button>'
             '</tg-button-row>\n')
    return html


async def post_web_card(session, changes, urls, *, reason="update"):
    """Send a tunnel-state card to the Web topic (falls back to Logs)."""
    gid = log_group_id()
    if gid is None:
        return False
    tid = log_topic_id("web") or log_topic_id("logs")
    payload = {"chat_id": gid,
               "rich_message": {"html": render_web_card(changes, urls, reason=reason)}}
    if tid:
        payload["message_thread_id"] = tid
    r = await send_request(session, "sendRichMessage", payload)
    if (r or {}).get("ok"):
        print(f"[bot] web card -> topic {tid}: {reason} "
              f"({len(changes)} change(s))")
        return True
    print(f"[bot] web card FAILED: {(r or {}).get('description')}")
    return False


async def check_web_changes(session, *, force_reason=None):
    """Compare current tunnel URLs with the last seen ones; post on any delta."""
    global _web_primed
    urls = get_tunnel_urls()
    changes = []
    for name in ("Dashboard", "API"):
        new = urls.get(name) or ""
        old = _web_state.get(name)
        if old is None:
            _web_state[name] = new
            continue
        if new != old:
            changes.append((name, old, new))
            _web_state[name] = new
    if not _web_primed:
        _web_primed = True
        if force_reason is None:
            return False  # first pass only records the baseline
    if force_reason:
        return await post_web_card(session, changes, urls, reason=force_reason)
    if changes:
        return await post_web_card(session, changes, urls, reason="url changed")
    return False


# ── Per-request cards for the Requests topic ────────────────────────────────
#
# The Requests topic used to stay empty: nothing wrote to it automatically, only
# the manual /reqs command. Now every completed request cycle in bridge.log is
# parsed into a compact card (model, prompt, tokens, timing, finish reason) and
# posted there, while the raw firehose keeps going to the Logs topic.
#
# A cycle starts at "NEW API REQUEST RECEIVED" and ends at the next one; fields
# are pulled with narrow regexes so a format change degrades to "-" instead of
# crashing the forwarder.

_REQ_FIELDS = (
    ("model",      re.compile(r"\U0001f916 Requested model:\s*(.+)")),
    ("modality",   re.compile(r"\U0001f50d Model modality:\s*(.+)")),
    ("messages",   re.compile(r"\U0001f4ac Number of messages:\s*(\d+)")),
    ("prompt_len", re.compile(r"\U0001f4dd User prompt length:\s*(\d+)")),
    ("prompt",     re.compile(r"\U0001f4dd User prompt:\s*(.+)")),
    ("stream",     re.compile(r"\U0001f30a Stream mode:\s*(\w+)")),
    ("attach",     re.compile(r"\U0001f5bc\ufe0f?\s*Attachments:\s*(.+)")),
    ("conv",       re.compile(r"Conversation ID:\s*(\w+)")),
    ("model_id",   re.compile(r"\u2705 Found model ID:\s*([\w-]+)")),
    ("session",    re.compile(r"\U0001f511 Generated session_id:\s*([\w-]+)")),
    ("target",     re.compile(r"\U0001f4e4 Target URL:\s*(.+)")),
    ("finish",     re.compile(r"Finish reason:\s*(\w+)")),
    ("resp_len",   re.compile(r"Final response length:\s*(\d+)")),
    ("reason_len", re.compile(r"Final reasoning length:\s*(\d+)")),
    ("chunks",     re.compile(r"Text chunks found:\s*(\d+)")),
    ("preview",    re.compile(r"\u2705 Response text preview:\s*(.+)")),
    ("http",       re.compile(r"Response status(?: code)?:\s*(\d+)")),
)
_TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")


def parse_request_cycles(lines):
    """Split bridge.log lines into per-request dicts."""
    cycles, cur = [], None
    for ln in lines:
        if "NEW API REQUEST RECEIVED" in ln:
            if cur:
                cycles.append(cur)
            cur = {"raw": [], "errors": [], "warnings": []}
            m = _TS_RE.match(ln)
            if m:
                cur["start"] = m.group(1)
        if cur is None:
            continue
        cur["raw"].append(ln)
        for key, rx in _REQ_FIELDS:
            m = rx.search(ln)
            if m and key not in cur:
                cur[key] = m.group(1).strip()
        m = _TS_RE.match(ln)
        if m:
            cur["end"] = m.group(1)
            # A cycle's segment runs until the NEXT request arrives, so the last
            # timestamp is idle time, not latency. Freeze the clock at the line
            # that actually ends the request.
            if ("Finish reason:" in ln or "Response text preview" in ln
                    or "\u274c" in ln) and "done" not in cur:
                cur["done"] = m.group(1)
        if "\u274c" in ln:
            cur["errors"].append(ln)
        elif "\u26a0\ufe0f" in ln:
            cur["warnings"].append(ln)
    if cur:
        cycles.append(cur)
    return cycles


def _duration(cycle):
    try:
        from datetime import datetime
        fmt = "%Y-%m-%d %H:%M:%S"
        a = datetime.strptime(cycle["start"], fmt)
        b = datetime.strptime(cycle.get("done") or cycle["end"], fmt)
        return f"{int((b - a).total_seconds())}s"
    except Exception:
        return "-"


def render_request_card(cycle):
    """Rich card for one request: table + prompt/answer blocks + error block."""
    g = lambda k, d="-": esc(str(cycle.get(k, d)))
    failed = bool(cycle.get("errors"))
    icon = EMOJI["down"] if failed else EMOJI["up"]
    rows = [
        f'<tr><td><b>model</b></td><td>{g("model")}</td></tr>',
        f'<tr><td><b>modality</b></td><td>{g("modality")}</td></tr>',
        f'<tr><td><b>stream</b></td><td>{g("stream")}</td></tr>',
        f'<tr><td><b>messages</b></td><td>{g("messages")}</td></tr>',
        f'<tr><td><b>prompt chars</b></td><td>{g("prompt_len")}</td></tr>',
        f'<tr><td><b>answer chars</b></td><td>{g("resp_len")}</td></tr>',
        f'<tr><td><b>reasoning chars</b></td><td>{g("reason_len", "0")}</td></tr>',
        f'<tr><td><b>chunks</b></td><td>{g("chunks")}</td></tr>',
        f'<tr><td><b>finish</b></td><td>{g("finish")}</td></tr>',
        f'<tr><td><b>duration</b></td><td>{esc(_duration(cycle))}</td></tr>',
        f'<tr><td><b>attachments</b></td><td>{g("attach", "0")}</td></tr>',
        f'<tr><td><b>conversation</b></td><td><code>{g("conv")}</code></td></tr>',
    ]
    html = (f'<h1>{icon} request {esc(cycle.get("start", ""))}</h1>\n'
            '<table><tr><th>field</th><th>value</th></tr>' + "".join(rows) + '</table>\n')
    if cycle.get("prompt"):
        html += ('<p><b>prompt</b></p>\n<pre><code class="language-text">'
                 + esc(str(cycle["prompt"])[:1500]) + '</code></pre>\n')
    if cycle.get("preview"):
        html += ('<p><b>answer preview</b></p>\n<pre><code class="language-text">'
                 + esc(str(cycle["preview"])[:1500]) + '</code></pre>\n')
    if cycle.get("errors"):
        html += ('<p><b>errors</b></p>\n<pre><code class="language-log">'
                 + esc("\n".join(cycle["errors"])[:1500]) + '</code></pre>\n')
    if cycle.get("warnings"):
        html += ('<p><b>warnings</b></p>\n<pre><code class="language-log">'
                 + esc("\n".join(cycle["warnings"][:6])[:1200]) + '</code></pre>\n')
    return html


def request_key(cycle):
    """Stable identity of a request cycle for dedup."""
    return (cycle.get("session") or cycle.get("conv")
            or f'{cycle.get("start")}|{cycle.get("prompt_len")}')


async def send_request_cards(session, cycles):
    """Post one card per request into the Requests topic (falls back to Logs)."""
    gid = log_group_id()
    if gid is None or not cycles:
        return False
    tid = log_topic_id("requests") or log_topic_id("logs")
    ok_all = True
    for cyc in cycles:
        payload = {"chat_id": gid, "rich_message": {"html": render_request_card(cyc)}}
        if tid:
            payload["message_thread_id"] = tid
        r = await send_request(session, "sendRichMessage", payload)
        if (r or {}).get("ok"):
            print(f"[bot] request card -> topic {tid}: "
                  f"{cyc.get('model', '?')} {cyc.get('start', '')} "
                  f"({_duration(cyc)}, finish={cyc.get('finish', '-')})")
        else:
            ok_all = False
            print(f"[bot] request card FAILED: {(r or {}).get('description')}")
        await asyncio.sleep(0.3)
    return ok_all


# Sources the forwarder watches. bot.log is included so bot-side errors surface in
# the same topic instead of only in journalctl.
_FWD_SOURCES = ("bridge.log", "bot.log")
_fwd_seen_by_src: dict = {}
_req_seen: set = set()

# The forwarder writes its own progress to stdout, which _FileTee mirrors into
# bot.log. Forwarding those lines makes each tick generate a fresh line to
# forward on the next tick — an endless self-feeding loop (observed: a "bot 1
# blocks, 326 chars" message every 20s forever). Skip our own bookkeeping.
_SELF_LOG_PREFIXES = (
    "[bot] log rich ->",
    "[bot] request card ->",
    "[bot] request card FAILED",
    "[bot] forwarder:",
    "[bot] log destination",
    "[bot] log group:",
    "[bot] log -> ",
)


def _is_self_log(line: str) -> bool:
    stripped = line.strip()
    return any(stripped.startswith(p) for p in _SELF_LOG_PREFIXES)


async def log_forwarder_loop(session):
    """Continuously push NEW log lines to the Logs topic as Rich messages.

    Dedup is hash-based per source (not line-count): the tail re-reads overlap on
    every poll, and a count-based cursor double-sends after log rotation.
    """
    # Prime the dedup sets so the first tick doesn't replay the existing history.
    for src in _FWD_SOURCES:
        _fwd_seen_by_src[src] = {hash(ln) for ln in read_log_lines(src, 500)}
    # Prime request cards too: only cycles that appear AFTER startup get posted.
    for cyc in parse_request_cycles(read_log_lines("bridge.log", 2000)):
        _req_seen.add(request_key(cyc))
    while True:
        try:
            await asyncio.sleep(FORWARD_INTERVAL_S)
            if log_group_id() is None:
                continue

            # Web topic: notice rotated tunnel URLs / up-down transitions.
            await check_web_changes(session)

            # Requests topic: one structured card per finished request.
            fresh_cycles = []
            for cyc in parse_request_cycles(read_log_lines("bridge.log", 1200)):
                key = request_key(cyc)
                if key in _req_seen:
                    continue
                # Only post once the cycle looks complete, so the card is not
                # published mid-flight with half the fields missing.
                if not cyc.get("model"):
                    continue  # stray marker / truncated cycle, nothing to show
                if not (cyc.get("finish") or cyc.get("preview") or cyc.get("errors")):
                    continue
                _req_seen.add(key)
                fresh_cycles.append(cyc)
            if fresh_cycles:
                print(f"[bot] forwarder: {len(fresh_cycles)} new request cycle(s)")
                await send_request_cards(session, fresh_cycles)

            for src in _FWD_SOURCES:
                seen = _fwd_seen_by_src.setdefault(src, set())
                fresh = []
                for ln in read_log_lines(src, 400):
                    if not ln.strip() or hash(ln) in seen:
                        continue
                    if src == "bot.log" and _is_self_log(ln):
                        seen.add(hash(ln))  # mark as handled, never forward
                        continue
                    fresh.append(ln)
                if not fresh:
                    continue
                for ln in fresh:
                    seen.add(hash(ln))
                if len(seen) > _fwd_seen_cap:
                    _fwd_seen_by_src[src] = set(list(seen)[-_fwd_seen_cap // 2:])
                await send_log_rich(session, fresh, source=src.replace(".log", ""))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[bot] log_forwarder error: {e}")
            await asyncio.sleep(5)


DRAFT_KEEPALIVE_S = 15.0   # Bot API: a draft is a temporary ~30s preview -> refresh before it dies
FAST_FRAMES = 8            # lively animation first, then cheap keep-alive cadence

BACK_ROW = ('<tg-button-row>'
            '<tg-button type="callback_data" data="back">Back</tg-button>'
            '</tg-button-row>')


def _new_draft_id() -> int:
    return int(time.time() * 1000) % 2147483647 or 1


def is_private(chat_id) -> bool:
    """Bot API: drafts work in PRIVATE chats only.

    sendRichMessageDraft documents chat_id as "the target private chat"; in a
    group/supergroup it returns 400 TEXTDRAFT_PEER_INVALID. Every draft call must
    be gated on this, otherwise a bot added to a group spams the journal with
    hundreds of TEXTDRAFT_PEER_INVALID errors and renders nothing.
    """
    try:
        return int(chat_id) > 0
    except (TypeError, ValueError):
        return False


async def _draft(session, chat_id, draft_id, html):
    """One sendRichMessageDraft frame — private chats only.

    This is also the ONLY method that accepts <tg-thinking>: sendRichMessage and
    editMessageText reject it with RICH_MESSAGE_BLOCK_UNSUPPORTED (verified
    against api.telegram.org).
    """
    if not is_private(chat_id):
        return {"ok": False, "skipped": "not_private"}
    return await send_request(session, "sendRichMessageDraft", {
        "chat_id": chat_id,
        "draft_id": draft_id,
        "rich_message": {"html": html},
    })


async def _thinking_loop(session, chat_id, draft_id, header, buttons, steps, stop_evt):
    """Animate <tg-thinking> frames until stop_evt is set.

    A draft only lives ~25-30s in the chat, so a job that thinks longer MUST
    re-send a frame inside that window or the preview silently disappears. We
    animate quickly for the first FAST_FRAMES frames, then keep re-sending at
    DRAFT_KEEPALIVE_S purely to keep the draft alive.
    """
    i = 0
    while not stop_evt.is_set():
        step = steps[i % len(steps)]
        await _draft(session, chat_id, draft_id,
                     header + f'<tg-thinking>{esc(step)}</tg-thinking>\n' + buttons)
        i += 1
        gap = 1.1 if i < FAST_FRAMES else DRAFT_KEEPALIVE_S
        try:
            await asyncio.wait_for(stop_evt.wait(), timeout=gap)
        except asyncio.TimeoutError:
            pass


async def _run_build(build_fn):
    """Call a builder that may be sync (possibly slow/blocking) or async."""
    if asyncio.iscoroutinefunction(build_fn):
        return await build_fn()
    out = await asyncio.get_event_loop().run_in_executor(None, build_fn)
    if inspect.isawaitable(out):
        out = await out
    return out


async def stream_new(session, chat_id, label, build_fn, *, delay=0.4, steps=None):
    """Stream a NEW message: draft frames (thinking -> body) then a final message.

    Frame order matters:
      1. sendRichMessageDraft + <tg-thinking>   (the only legal place for it)
      2. sendRichMessageDraft body chunks, buttons pinned in EVERY frame
      3. sendRichMessage with the finished html  (drafts are ephemeral)
    """
    draft_id = _new_draft_id()
    header = f'<h1>{EMOJI["brain"]} {esc(label)}</h1>\n'
    steps = steps or [f"Loading {label.lower()}...", "Reading live state...", "Rendering..."]

    # Groups cannot receive drafts (TEXTDRAFT_PEER_INVALID) — build, then send once.
    if not is_private(chat_id):
        html_full = await _run_build(build_fn)
        html_full = html_full or "<p><i>empty</i></p>"
        if not html_full.startswith("<h1>"):
            html_full = header + html_full
        return await send_request(session, "sendRichMessage", {
            "chat_id": chat_id,
            "rich_message": {"html": html_full},
        })

    # Build in the background: webdev/tunnel-restart builders take seconds to minutes,
    # and calling them inline froze the whole poller with no feedback on screen.
    build_task = asyncio.ensure_future(_run_build(build_fn))
    try:
        html_full = await asyncio.wait_for(asyncio.shield(build_task), timeout=0.8)
        slow = False
    except asyncio.TimeoutError:
        slow = True
        html_full = None

    if slow:
        # Buttons aren't known yet -> keep a stable Back row pinned so the
        # keyboard never grows row-by-row while text streams.
        stop = asyncio.Event()
        thinker = asyncio.ensure_future(
            _thinking_loop(session, chat_id, draft_id, header, BACK_ROW, steps, stop))
        try:
            html_full = await build_task
        finally:
            stop.set()
            await thinker
    else:
        await _draft(session, chat_id, draft_id,
                     header + f'<tg-thinking>{esc(steps[0])}</tg-thinking>\n')
        await asyncio.sleep(delay)

    html_full = html_full or "<p><i>empty</i></p>"
    if not html_full.startswith("<h1>"):
        html_full = header + html_full

    # Pull ALL button rows out of the body so they stay intact at the bottom of
    # every frame instead of appearing progressively.
    buttons = "".join(re.findall(r'<tg-button-row>.*?</tg-button-row>', html_full, re.S))
    body = re.sub(r'<tg-button-row>.*?</tg-button-row>', '', html_full, flags=re.S)
    body = re.sub(r'\n{2,}', '\n', body).strip()
    if len(body) > 3500:
        body = body[:3500] + "\n..."

    # Body streaming frames. Chunk on tag boundaries: cutting mid-tag yields
    # RICH_MESSAGE_HTML_INVALID and the frame is dropped.
    marks = [m.end() for m in re.finditer(r'>', body)] or [len(body)]
    n_frames = 6
    picks = sorted({marks[min(len(marks) - 1, int(len(marks) * k / n_frames))]
                    for k in range(1, n_frames + 1)})
    last_sent = time.monotonic()
    for cut in picks:
        await _draft(session, chat_id, draft_id,
                     body[:cut] + "\n" + buttons)
        last_sent = time.monotonic()
        await asyncio.sleep(max(0.2, delay * 0.7))

    # Finalize: a draft is ephemeral, only sendRichMessage persists it.
    await send_request(session, "sendRichMessage", {
        "chat_id": chat_id,
        "rich_message": {"html": body + "\n" + buttons},
    })


# ── File logging ────────────────────────────────────────────────────────────


class _FileTee:
    """Duplicates sys.stdout/stderr writes to BOTH the original stream and a
    log file.  Flushes each write so journald / systemd sees output promptly.
    Auto-rotates the log file at *max_bytes* (default 5 MB)."""

    def __init__(self, original, log_path, max_bytes=5 * 1024 * 1024, backups=3):
        self._orig = original
        self._log_path = log_path
        self._max = max_bytes
        self._backups = backups
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self._fh = open(log_path, "a", encoding="utf-8", errors="replace")
        self._size = os.path.getsize(log_path)

    def write(self, data):
        try:
            self._orig.write(data)
        except Exception:
            pass
        try:
            self._fh.write(data)
            # Flush on every write. Without this the file handle stays block
            # buffered (8 KB) and a long-lived daemon leaves bot.log empty for
            # hours — which is exactly why the log forwarder had nothing to send
            # and /logs showed "bot.log is empty yet".
            self._fh.flush()
            self._size += len(data)
            if self._size >= self._max:
                self._rotate()
        except Exception:
            pass
        return len(data)

    def flush(self):
        try:
            self._orig.flush()
        except Exception:
            pass
        try:
            self._fh.flush()
        except Exception:
            pass

    def _rotate(self):
        try:
            self._fh.close()
            for i in range(self._backups - 1, 0, -1):
                src = f"{self._log_path}.{i}"
                dst = f"{self._log_path}.{i + 1}"
                if os.path.exists(src):
                    os.replace(src, dst)
            if os.path.exists(self._log_path):
                os.replace(self._log_path, f"{self._log_path}.1")
            self._fh = open(self._log_path, "a", encoding="utf-8", errors="replace")
            self._size = 0
        except Exception:
            pass

    def isatty(self):
        return False

    def fileno(self):
        return self._orig.fileno()


def setup_bot_logging():
    """Redirect stdout+stderr to LOG_DIR/bot.log while preserving journald."""
    log_file = os.path.join(LOG_DIR, "bot.log")
    sys.stdout = _FileTee(sys.stdout, log_file)
    sys.stderr = _FileTee(sys.stderr, log_file)
    print(f"[bot] log -> {log_file}")


# ── Telegram-side setup wizard (no terminal input) ──────────────────────────
#
# Setuper.sh only ever asks for BOT_TOKEN. Everything else is collected HERE,
# inside Telegram, because those values cannot be known from a shell:
#   • OWNER_ID   — the installer prints it, but the bot learns it from /start
#   • api_id / api_hash  — pasted via inline input, never echoed in a terminal
#   • log group  — the user must ADD the bot to the group first, so only the
#     bot can discover the chat_id (my_chat_member / /here)
# State lives in telegram_credentials.json + config.json so a restart resumes.

API_ID_RE = re.compile(r"^\d{6,10}$")
API_HASH_RE = re.compile(r"^[a-f0-9]{32}$")

# stage: None | "api_id" | "api_hash" | "group"
_setup_state: dict = {"stage": None, "api_id": None}


def load_creds():
    """MTProto creds from .env (api_hash is a secret — never in config.json)."""
    return {"api_id": se.telegram_api_id(), "api_hash": se.telegram_api_hash()}


def save_creds(**kw):
    mapping = {"api_id": "TELEGRAM_API_ID", "api_hash": "TELEGRAM_API_HASH"}
    updates = {mapping[k]: v for k, v in kw.items() if k in mapping}
    ok = se.set_many(updates) if updates else False
    print(f"[bot] creds {'saved' if ok else 'SAVE FAILED'}: {sorted(updates)}")
    return ok


def setup_missing() -> list:
    """Which setup steps are still outstanding."""
    missing = []
    c = load_creds()
    if not (c.get("api_id") and c.get("api_hash")):
        missing.append("api")
    if log_group_id() is None:
        missing.append("group")
    if _INLINE_SUPPORT.get("checked") and not _INLINE_SUPPORT.get("ok"):
        missing.append("inline")
    return missing


def build_setup():
    """Setup checklist with inline-input buttons (Telegram-only configuration)."""
    c = load_creds()
    api_ok = bool(c.get("api_id") and c.get("api_hash"))
    gid = log_group_id()
    rows = [
        f'<tr><td><b>Bot token</b></td><td>{(EMOJI["up"] + " set") if TOKEN else (EMOJI["down"] + " missing")}</td></tr>',
        f'<tr><td><b>Owner ID</b></td><td>{EMOJI["up"]} {sorted(owners())[0] if owners() else "-"}</td></tr>',
        f'<tr><td><b>API id / hash</b></td><td>{(EMOJI["up"] + " set") if api_ok else (EMOJI["down"] + " missing")}</td></tr>',
        f'<tr><td><b>Log group</b></td><td>{(EMOJI["up"] + " " + str(gid)) if gid is not None else (EMOJI["down"] + " not linked")}</td></tr>',
        f'<tr><td><b>Inline mode</b></td><td>{(EMOJI["up"] + " on") if _INLINE_SUPPORT.get("ok") else (EMOJI["down"] + " off (BotFather /setinline)")}</td></tr>',
        f'<tr><td><b>MTProto layer</b></td><td>{(EMOJI["up"] + " ready") if MT.available else (EMOJI["down"] + " " + esc(MT.why_unavailable()))}</td></tr>',
    ]
    btns = ""
    if not api_ok and _INLINE_SUPPORT.get("ok"):
        # switch_inline_query_current_chat pre-fills "@bot API_ID " so the value is
        # typed in Telegram, never in a shell (Heroku form.py inline-input pattern).
        btns += ('<tg-button-row>'
                 '<tg-button type="switch_inline_query_current_chat" query="API_ID ">'
                 'Enter api_id</tg-button>'
                 '<tg-button type="switch_inline_query_current_chat" query="API_HASH ">'
                 'Enter api_hash</tg-button>'
                 '</tg-button-row>\n')
    elif not api_ok:
        btns += ('<tg-button-row>'
                 '<tg-button type="url" url="https://t.me/BotFather">'
                 'Enable inline in BotFather</tg-button>'
                 '</tg-button-row>\n')
    btns += ('<tg-button-row>'
             '<tg-button type="callback_data" data="setup">Refresh</tg-button>'
             '<tg-button type="callback_data" data="back">Back</tg-button>'
             '</tg-button-row>\n')
    hint = ("<p>All set — nothing left to configure.</p>" if not setup_missing() else
            "<p>Add me to your log group and send <code>/here</code> there to link it. "
            "Paste api_id / api_hash with the buttons below (or just send them here).</p>")
    return (f'<h1>{EMOJI["format"]} Setup</h1>\n'
            + hint
            + '<table><tr><th>Item</th><th>State</th></tr>' + "".join(rows) + '</table>\n'
            + btns)


async def handle_setup_text(session, chat_id, text) -> bool:
    """Consume api_id / api_hash typed (or inline-inserted) in the owner DM.

    Returns True when the message was consumed as setup input.
    """
    raw = text.strip()
    for prefix, kind in (("API_ID ", "api_id"), ("API_HASH ", "api_hash")):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
            _setup_state["stage"] = kind
            break
    else:
        kind = None
        if API_ID_RE.match(raw) and not load_creds().get("api_id"):
            kind = "api_id"
        elif API_HASH_RE.match(raw.lower()):
            kind = "api_hash"
        if kind is None:
            return False
        _setup_state["stage"] = kind

    kind = _setup_state["stage"]
    if kind == "api_id":
        if not API_ID_RE.match(raw):
            await send_request(session, "sendMessage", {
                "chat_id": chat_id, "text": "api_id must be 6-10 digits. Try again."})
            return True
        save_creds(api_id=int(raw))
    else:
        if not API_HASH_RE.match(raw.lower()):
            await send_request(session, "sendMessage", {
                "chat_id": chat_id, "text": "api_hash must be 32 hex chars. Try again."})
            return True
        save_creds(api_hash=raw.lower())
    _setup_state["stage"] = None
    await stream_new(session, chat_id, "Setup", build_setup, delay=0.3)
    return True


# ── Inline mode (Heroku form.py style, arrows instead of emoji) ─────────────
#
# Inline INPUT pattern, copied from Hikka/Heroku inline forms: a rich button of
# type switch_inline_query_current_chat pre-fills "@bot API_ID " in the input
# field; whatever the user types after the prefix comes back as an inline_query,
# and the article they tap sends the value to the bot. That way api_id/api_hash
# are never typed into a terminal.
#
# The arrows ↑ ↓ → ← in the inline article caption are the "query changed"
# indicator the user asked for: the glyph rotates on every keystroke so it is
# obvious the article refreshed rather than being a cached result.
ARROWS = ("→", "↑", "↓", "←")


def arrow_for(q: str) -> str:
    return ARROWS[len(q) % len(ARROWS)]


_INLINE_SUPPORT = {"checked": False, "ok": None, "username": None}

# Optional MTProto side-car: premium emoji in inline results, coloured buttons,
# media by file_reference. Disabled automatically when api_id/api_hash are absent.
MT = _mt.build_layer(se)


async def check_inline_support(session) -> tuple:
    """getMe -> (supports_inline_queries, username). Cached after first call."""
    if _INLINE_SUPPORT["checked"]:
        return _INLINE_SUPPORT["ok"], _INLINE_SUPPORT["username"]
    r = await send_request(session, "getMe", {})
    res = (r or {}).get("result") or {}
    _INLINE_SUPPORT.update(checked=True,
                           ok=bool(res.get("supports_inline_queries")),
                           username=res.get("username"))
    return _INLINE_SUPPORT["ok"], _INLINE_SUPPORT["username"]


def inline_off_html(username) -> str:
    """Shown when the bot has no inline mode: exact BotFather steps."""
    return (
        f'<h1>{EMOJI["down"]} Inline mode is OFF</h1>\n'
        "<p>The setup buttons paste api_id / api_hash through inline input, "
        "so inline mode has to be enabled once:</p>\n"
        "<ol>"
        "<li>Open <a href=\"https://t.me/BotFather\">@BotFather</a></li>"
        "<li>Send <code>/setinline</code></li>"
        f"<li>Pick <code>@{esc(username or 'your_bot')}</code></li>"
        "<li>Send any placeholder, e.g. <code>value</code></li>"
        "</ol>\n"
        "<p>Then press Refresh. You can also just send api_id / api_hash "
        "as plain messages here.</p>\n"
        '<tg-button-row>'
        '<tg-button type="url" url="https://t.me/BotFather">Open BotFather</tg-button>'
        '<tg-button type="callback_data" data="setup">Refresh</tg-button>'
        '</tg-button-row>\n'
    )


async def answer_inline(session, iq_id, articles):
    return await send_request(session, "answerInlineQuery", {
        "inline_query_id": iq_id,
        "results": json.dumps(articles),
        "cache_time": 0,
    })


def rich_article(aid, title, description, html):
    """Inline article carrying a Rich Message body (Bot API 10.x)."""
    return {
        "type": "article",
        "id": aid,
        "title": title,
        "description": description,
        "rich_message": {"html": html},
    }


async def handle_inline_query(session, iq):
    """Inline entry point: value input (API_ID/API_HASH) + live status menu."""
    iq_id = iq["id"]
    user = (iq.get("from") or {}).get("id")
    q = (iq.get("query") or "")
    if not _is_allowed(user):
        await answer_inline(session, iq_id, [rich_article(
            "denied", "Not available",
            "This bot only answers its owner",
            f'<h1>{EMOJI["down"]} Private bot</h1><p>Owner-only.</p>')])
        return

    arrow = arrow_for(q)
    up = q.strip()

    # ── inline INPUT: "API_ID 12345" / "API_HASH deadbeef..." ──
    for prefix, label, rx in (("API_ID", "api_id", API_ID_RE),
                              ("API_HASH", "api_hash", API_HASH_RE)):
        if up.upper().startswith(prefix):
            value = up[len(prefix):].strip()
            valid = bool(rx.match(value.lower()))
            if not value:
                desc = f"{arrow} type your {label} after the prefix"
            elif valid:
                desc = f"{arrow} tap to save {label}"
            else:
                need = "6-10 digits" if label == "api_id" else "32 hex chars"
                desc = f"{arrow} invalid — {label} must be {need}"
            body = (f'<h1>{EMOJI["format"]} {label}</h1>\n'
                    f'<p>{arrow} value: <code>{esc(value) or "—"}</code></p>\n'
                    + ("<p>Saved. Open /setup to continue.</p>" if valid else
                       f"<p>Waiting for a valid {label}.</p>"))
            await answer_inline(session, iq_id, [rich_article(
                f"{label}:{value[:32]}",
                f"{arrow} Set {label}",
                desc, body)])
            return

    # ── default: live status + menu buttons ──
    h = await bridge_health()
    cfg = load_config()
    rows = (
        '<tg-button-row>'
        '<tg-button type="callback_data" data="st">Status</tg-button>'
        '<tg-button type="callback_data" data="mod">Models</tg-button>'
        '</tg-button-row>'
        '<tg-button-row>'
        '<tg-button type="callback_data" data="tun">Tunnels</tg-button>'
        '<tg-button type="callback_data" data="setup">Setup</tg-button>'
        '</tg-button-row>'
    )
    urls = get_tunnel_urls()
    trow_parts = []
    for n, u in (("Dashboard", urls.get("Dashboard")), ("API", urls.get("API"))):
        cell = f'<a href="{esc(u)}">link</a>' if u else "down"
        trow_parts.append(f'<tr><td><b>{esc(n)}</b></td><td>{cell}</td></tr>')
    trows = "".join(trow_parts)
    body = (
        f'<h1>{EMOJI["brain"]} LMArena Bridge</h1>\n'
        '<table><tr><th>Component</th><th>State</th></tr>'
        f'<tr><td><b>Bridge :6767</b></td><td>{"healthy" if h == 200 else h or "down"}</td></tr>'
        f'<tr><td><b>Models</b></td><td>{len(cfg.get("models") or [])}</td></tr>'
        f'{trows}'
        '</table>\n'
        + rows
    )
    await answer_inline(session, iq_id, [rich_article(
        "lm_status", f"{arrow} LMArena Bridge",
        "Health, models, tunnels — tap to send", body)])


# ── Ephemeral messages (Bot API 10.2) ───────────────────────────────────────
#
# In a group the bot answers EPHEMERALLY: the message is delivered only to the
# user who triggered it, so a shared log group never fills up with menus. Verified
# behaviour against api.telegram.org:
#   • group + ephemeral_message_parameters  -> ok, returns ephemeral_message_id
#   • private chat + the same parameters    -> 400 BOT_NOT_ADMIN
# so ephemeral is group-only and the bot must be an admin there. Private chats get
# the normal Rich + <tg-thinking> draft flow instead.
#
# Editing/deleting an ephemeral message needs the triple
# (chat_id, receiver_user_id, ephemeral_message_id) — there is no plain message_id.

_eph_last: dict = {}  # (cid, uid) -> ephemeral_message_id


async def send_ephemeral(session, chat_id, user_id, html, callback_query_id=None,
                         replace_original=False):
    """Rich message visible only to `user_id` inside a group."""
    params = {"receiver_user_id": int(user_id)}
    if callback_query_id:
        params["callback_query_id"] = callback_query_id
        # replace_callback_query_message must be False when the callback itself
        # came from an ephemeral message (Bot API constraint).
        params["replace_callback_query_message"] = bool(replace_original)
    r = await send_request(session, "sendRichMessage", {
        "chat_id": chat_id,
        "rich_message": {"html": html},
        "ephemeral_message_parameters": params,
    })
    eid = ((r or {}).get("result") or {}).get("ephemeral_message_id")
    if eid:
        _eph_last[(int(chat_id), int(user_id))] = eid
    return r


async def edit_ephemeral(session, chat_id, user_id, ephemeral_message_id, html):
    """editEphemeralMessageText with a rich body (no <tg-thinking> allowed)."""
    return await send_request(session, "editEphemeralMessageText", {
        "chat_id": chat_id,
        "receiver_user_id": int(user_id),
        "ephemeral_message_id": int(ephemeral_message_id),
        "rich_message": {"html": html},
    })


async def render_menu(session, chat_id, user_id, label, build_fn, *, delay=0.35,
                      callback_query_id=None, ephemeral_message_id=None):
    """Render a menu the right way for the chat type.

    private  -> streamed drafts with <tg-thinking>, then a persistent message
    group    -> single ephemeral message, only the requesting user sees it
    """
    if is_private(chat_id):
        return await stream_new(session, chat_id, label, build_fn, delay=delay)

    html = await _run_build(build_fn)
    html = html or "<p><i>empty</i></p>"
    if not html.startswith("<h1>"):
        html = f'<h1>{EMOJI["brain"]} {esc(label)}</h1>\n' + html
    if ephemeral_message_id:
        r = await edit_ephemeral(session, chat_id, user_id, ephemeral_message_id, html)
        if (r or {}).get("ok"):
            return r
        # Edit can fail if the ephemeral message already expired -> send a new one.
    return await send_ephemeral(session, chat_id, user_id, html,
                                callback_query_id=callback_query_id)


# ── Group guard + onboarding ────────────────────────────────────────────────
#
# Guard rule (owner-scoped): the bot stays ONLY in groups the owner added it to.
# Anyone else adding it -> post the repo notice once and leave. The "left twice"
# bug in the original protection.py came from handling both the join event AND
# the first group message without a per-chat latch; `_leaving` is that latch.

REPO_URL = "https://github.com/i-execute/Arena"
LEAVE_MESSAGE = (
    "<b>LMArena Bridge — private admin bot</b>\n"
    "This bot only serves its owner's deployment.\n\n"
    f'Self-host it: <a href="{REPO_URL}">{REPO_URL}</a>\n'
    "Leaving now."
)

# cid -> {"logs": tid, "requests": tid, "admin": bool}
_group_state: dict[int, dict] = {}
_leaving: set[int] = set()


def approved_groups() -> set:
    """Groups the owner explicitly added us to.

    Persisted in .env, because the in-memory set is empty right after a restart —
    that gap is what made the bot walk out of its own log group.
    """
    out = set()
    for chunk in se.get_list("BOT_APPROVED_GROUPS"):
        try:
            out.add(int(chunk))
        except ValueError:
            pass
    gid = log_group_id()
    if gid is not None:
        out.add(int(gid))  # the configured log group is approved by definition
    return out


def approve_group(cid) -> bool:
    """Remember that the owner authorised this group."""
    cid = int(cid)
    current = {c for c in approved_groups()}
    current.add(cid)
    ok = se.set_many({"BOT_APPROVED_GROUPS": ",".join(str(c) for c in sorted(current))})
    print(f"[bot] group {cid} approved{'' if ok else ' (SAVE FAILED)'}")
    return ok


def is_approved_group(cid) -> bool:
    try:
        return int(cid) in approved_groups()
    except (TypeError, ValueError):
        return False

# Web = tunnel URLs + dashboard state, so a rotated trycloudflare URL is findable
# in Telegram instead of only in journalctl.
LOG_TOPICS = (("Logs", 0x6FB9F0), ("Requests", 0xF0A030), ("Web", 0x8EEE98))


async def leave_group(session, cid, reason=""):
    """Post the repo notice once, then leave. Latched so it can't double-fire."""
    if int(cid) in _leaving:
        return
    _leaving.add(int(cid))
    try:
        await send_request(session, "sendMessage", {
            "chat_id": cid, "text": LEAVE_MESSAGE,
            "parse_mode": "HTML", "disable_web_page_preview": False,
        })
        await send_request(session, "leaveChat", {"chat_id": cid})
        print(f"[bot] left group {cid} ({reason})")
    finally:
        # keep the latch ~60s so the trailing group message can't re-trigger it
        async def _unlatch():
            await asyncio.sleep(60)
            _leaving.discard(int(cid))
        asyncio.ensure_future(_unlatch())


async def ensure_topics(session, cid):
    """Create Logs/Requests topics. Returns (found, err).

    createForumTopic needs BOTH: the chat must be a forum (Topics enabled in
    group settings — a plain `group` returns "the chat is not a forum", and a
    basic group has to be upgraded to a supergroup first) AND the bot must be an
    admin with can_manage_topics. We surface which one is missing instead of
    claiming success like the old code did.
    """
    found, err = {}, None
    for name, color in LOG_TOPICS:
        r = await send_request(session, "createForumTopic", {
            "chat_id": cid, "name": name, "icon_color": color})
        if isinstance(r, dict) and r.get("ok") and isinstance(r.get("result"), dict):
            tid = r["result"].get("message_thread_id")
            if tid:
                found[name.lower()] = tid
        else:
            err = (r or {}).get("description", "unknown error")
    return found, err


async def group_status(session, cid):
    """(is_forum, is_admin, can_manage_topics) for a chat."""
    me = await send_request(session, "getMe", {})
    my_id = ((me or {}).get("result") or {}).get("id")
    chat = await send_request(session, "getChat", {"chat_id": cid})
    is_forum = bool(((chat or {}).get("result") or {}).get("is_forum"))
    mem = await send_request(session, "getChatMember",
                             {"chat_id": cid, "user_id": my_id})
    m = (mem or {}).get("result") or {}
    return is_forum, m.get("status") in ("administrator", "creator"), bool(m.get("can_manage_topics"))


def group_setup_html(cid, is_forum, is_admin, can_topics, found, err):
    rows = [
        f'<tr><td><b>Chat</b></td><td><code>{esc(cid)}</code></td></tr>',
        f'<tr><td><b>Topics enabled</b></td><td>{"yes" if is_forum else "no"}</td></tr>',
        f'<tr><td><b>Bot is admin</b></td><td>{"yes" if is_admin else "no"}</td></tr>',
        f'<tr><td><b>can_manage_topics</b></td><td>{"yes" if can_topics else "no"}</td></tr>',
        f'<tr><td><b>Topics</b></td><td>{", ".join(sorted(found)) if found else "main chat"}</td></tr>',
    ]
    todo = []
    if not is_forum:
        todo.append("Enable <b>Topics</b> in group settings "
                    "(basic groups must be upgraded to a supergroup first).")
    if not is_admin:
        todo.append("Promote me to <b>admin</b>.")
    elif not can_topics:
        todo.append("Grant the admin right <b>Manage Topics</b>.")
    if todo:
        todo.append("Then send <code>/here</code> in this chat to retry.")
    body = ("<h1>LMArena log group</h1>\n"
            "<table><tr><th>Check</th><th>State</th></tr>" + "".join(rows) + "</table>\n")
    if todo:
        body += ("<p><b>Action needed:</b></p><ul>"
                 + "".join(f"<li>{t}</li>" for t in todo) + "</ul>\n")
        if err:
            body += f"<p>Last API error: <code>{esc(err)}</code></p>\n"
    else:
        body += (f"<p>Forwarding bridge logs here every {int(FORWARD_INTERVAL_S)}s.</p>\n"
                 "<p>Commands: <code>/logs_fwd</code> <code>/reqs</code> "
                 "<code>/stats</code> <code>/tunnel</code></p>\n")
    return body


async def link_log_group(session, cid):
    """Try to set up + persist this chat as the log destination."""
    is_forum, is_admin, can_topics = await group_status(session, cid)
    found, err = ({}, None)
    if is_forum and is_admin and can_topics:
        found, err = await ensure_topics(session, cid)
    elif is_forum and is_admin:
        err = "missing can_manage_topics admin right"
    elif not is_forum:
        err = "chat is not a forum (Topics disabled)"
    else:
        err = "bot is not an admin"
    if found:
        _group_state[int(cid)] = {**_group_state.get(int(cid), {}), **found}
        _topic_state[int(cid)] = {**_topic_state.get(int(cid), {}), **found}
    # Persist even without topics: logs then go to the main chat, which still works.
    save_log_destination(cid, found)
    approve_group(cid)
    return group_setup_html(cid, is_forum, is_admin, can_topics, found, err)


async def on_added_to_group(session, chat, inviter, status):
    """Decide by the INVITER's user id: owner -> stay and onboard, anyone else -> leave.

    `inviter` is my_chat_member.from.id — the user who performed the addition. This
    is the only trustworthy signal: chat titles and member lists can be faked, the
    actor id cannot.
    """
    cid = chat.get("id")
    if not _is_allowed(inviter or 0):
        await leave_group(session, cid,
                          f"added by {inviter}, not the owner {sorted(owners())}")
        return
    approve_group(cid)  # persist BEFORE anything else, so a restart can't undo it
    _group_state[int(cid)] = {**_group_state.get(int(cid), {}),
                              "admin": status == "administrator"}
    print(f"[bot] owner {inviter} added me to {cid} — staying")
    html = await link_log_group(session, cid)
    await send_request(session, "sendRichMessage",
                       {"chat_id": cid, "rich_message": {"html": html}})


# ── Polling ─────────────────────────────────────────────────────────────────

# Only these Telegram user IDs may control the bot (security: tun_r restarts services)
def owners() -> set:
    """Owner ids from .env (OWNER_ID / ADMIN_ID / BOT_ALLOWED_USERS).

    Read live rather than cached at import: a fresh install learns its owner at
    runtime via echo-id bootstrap and must start honouring it immediately.
    """
    out = set(se.owner_ids())
    legacy = _cfg_int("owner_id")  # pre-.env installs
    if legacy:
        out.add(legacy)
    return out


ALLOWED_USERS = set(se.owner_ids())  # snapshot, for startup logging only


def _is_allowed(user_id) -> bool:
    try:
        return int(user_id) in owners()
    except (TypeError, ValueError):
        return False


def save_owner_id(uid) -> bool:
    """Persist the owner id learned in echo-id mode into .env."""
    ok = se.set_many({"OWNER_ID": int(uid), "ADMIN_ID": int(uid)})
    print(f"[bot] owner_id {'saved' if ok else 'SAVE FAILED'}: {uid}")
    return ok



def bridge_api_key():
    """Bridge admin API key from .env (BRIDGE_API_KEY)."""
    keys = se.api_keys()
    return keys[0] if keys else ""


async def _bridge_post(session, path: str, payload: dict, timeout: int = 120):
    """POST to the local bridge with the admin api key."""
    key = bridge_api_key()
    if not key:
        return {"error": "no api key found in config"}
    try:
        async with session.post(f"{BRIDGE_URL}{path}", json=payload,
                                headers={"Authorization": f"Bearer {key}"},
                                timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            try:
                return await r.json()
            except Exception:
                return {"http": r.status, "body": (await r.text())[:300]}
    except Exception as e:
        return {"error": f"bridge call failed: {e}"}


async def build_webdev():
    """Latest webdev deployments with per-site download buttons (/webdev)."""
    sites = load_sites()
    rows = []
    for sid in sorted(sites, reverse=True)[:8]:
        s = sites[sid]
        url = s.get("url", "")
        name = s.get("name", sid[:8])
        files = s.get("files_count", "?")
        row = f"<b>{esc(name)}</b> ({files} files)\n"
        if url:
            row += f'<a href="{esc(url)}">🔗 open site</a>\n'
        row += ('<tg-button-row><tg-button type="callback_data" data="dl:' + sid
                + '">Download zip</tg-button></tg-button-row>')
        rows.append(row)
    if not rows:
        return "<i>No webdev deployments yet.</i>"
    return "<h1>🕸 WebDev sites</h1>\n" + "\n".join(rows)



async def handle_callback(session, cb_id, data, chat_id, message_id, from_user_id=None,
                          ephemeral_message_id=None):
    # answerCallbackQuery must NOT be called before sending an ephemeral message
    # that consumes callback_query_id — answering closes the query. Only ack here
    # for the non-ephemeral paths.
    if is_private(chat_id) or not from_user_id:
        await send_request(session, "answerCallbackQuery", {"callback_query_id": cb_id})

    if not _is_allowed(from_user_id):
        await send_request(session, "answerCallbackQuery", {"callback_query_id": cb_id})
        return  # silently ignore foreign callbacks

    def show(label, fn, *, delay=0.35):
        """Menu render bound to this callback (ephemeral in groups)."""
        return render_menu(session, chat_id, from_user_id, label, fn, delay=delay,
                           callback_query_id=None if is_private(chat_id) else cb_id,
                           ephemeral_message_id=ephemeral_message_id)

    if data.startswith("dl:"):
        # /webdev download button — zip of deployed site
        sid = data[3:]
        key = bridge_api_key()
        if not key:
            await send_request(session, "sendMessage", {
                "chat_id": chat_id, "text": "No api key in config.", "parse_mode": "HTML",
            })
            return
        url = f"{BRIDGE_URL}/api/v1/deployments/{sid}/download"
        try:
            async with session.get(url, headers={"Authorization": f"Bearer {key}"},
                                    timeout=aiohttp.ClientTimeout(total=60)) as r:
                if r.status == 200:
                    body = await r.read()
                    fname = f"/home/forget/QwertyWork/site_{sid[:8]}.zip"
                    import pathlib
                    pathlib.Path("/home/forget/QwertyWork").mkdir(parents=True, exist_ok=True)
                    with open(fname, "wb") as f:
                        f.write(body)
                    # Send file via multipart upload
                    form = aiohttp.FormData()
                    form.add_field("chat_id", str(chat_id))
                    form.add_field("document", body, filename=f"site_{sid[:8]}.zip")
                    async with session.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument",
                                            data=form) as r2:
                        pass
                    await send_request(session, "answerCallbackQuery", {
                        "callback_query_id": cb_id,
                        "text": f"Zip saved locally: {fname}",
                    })
                else:
                    await send_request(session, "answerCallbackQuery", {
                        "callback_query_id": cb_id,
                        "text": f"Download failed: HTTP {r.status}",
                    })
        except Exception as e:
            await send_request(session, "answerCallbackQuery", {
                "callback_query_id": cb_id,
                "text": f"Error: {e}",
            })
        return

    if data == "back":
        await show("Menu", build_main, delay=0.3)
    elif data == "st":
        h = await bridge_health()
        await show("Status", lambda: build_status(h))
    elif data == "mod":
        await show("Models", build_models)
    elif data == "use":
        await show("Usage", build_usage)
    elif data == "logs":
        await show("Logs", build_logs)
    elif data == "tun_r":
        if is_private(chat_id):
            # Streamed <tg-thinking> progress, private chats only.
            await stream_tunnel_restart(session, chat_id, message_id)
            await check_web_changes(session, force_reason="manual restart")
        else:
            eid = (await send_ephemeral(
                session, chat_id, from_user_id,
                f'<h1>{EMOJI["ok"]} Tunnels</h1>\n<p>Restarting tunnels...</p>',
                callback_query_id=cb_id) or {}).get("result", {}).get("ephemeral_message_id")
            urls = await asyncio.get_event_loop().run_in_executor(None, restart_tunnels)
            await render_menu(session, chat_id, from_user_id, "Tunnels", build_tunnel,
                              ephemeral_message_id=eid)
            await check_web_changes(session, force_reason="manual restart")
    elif data == "tun":
        await show("Tunnels", build_tunnel)
    elif data == "setup":
        await show("Setup", build_setup)


async def main():
    if not TOKEN:
        print(f"BOT_TOKEN not set — add it to {se.ENV_PATH} (see .env.example)")
        return
    async with aiohttp.ClientSession() as session:
        setup_bot_logging()
        print("Bot starting up...")
        inline_ok, uname = await check_inline_support(session)
        print(f"[bot] @{uname} inline_queries={'on' if inline_ok else 'OFF (BotFather /setinline)'}")
        if MT.available:
            started = await MT.start()
            print(f"[bot] mtproto layer: {'up' if started else 'failed to start'}")
        else:
            print(f"[bot] mtproto layer: off ({MT.why_unavailable()})")
        if not owners():
            # Bootstrap: no owner yet -> echo-id mode. First person to DM the bot
            # gets their numeric id back and becomes the owner. This is what makes
            # Setuper.sh able to ask for nothing but BOT_TOKEN.
            print("[bot] no owner configured — entering echo-id bootstrap mode")
        gid = log_group_id()
        if gid is None:
            print("[bot] log group: not configured yet "
                  "(add the bot to a group to auto-configure)")
        else:
            print(f"[bot] log group: {gid} topic={log_topic_id('logs')}")
        # Background task: push new bridge log lines to the Logs topic.
        fwd_task = asyncio.ensure_future(log_forwarder_loop(session))
        if log_group_id() is not None:
            # Baseline card so the Web topic shows the live URLs immediately.
            asyncio.ensure_future(check_web_changes(session, force_reason="bot started"))
        offset = None
        while True:
            try:
                params = {"timeout": 30}
                if offset:
                    params["offset"] = offset
                async with session.get(f"{API_URL}/getUpdates", params=params) as resp:
                    if resp.status != 200:
                        await asyncio.sleep(2)
                        continue
                    data = await resp.json()
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        if "message" in update:
                            msg = update["message"]
                            chat_id = msg["chat"]["id"]
                            from_user_id = (msg.get("from") or {}).get("id")
                            if not owners() and int(chat_id) > 0 and from_user_id:
                                # echo-id bootstrap: first DM claims ownership.
                                save_owner_id(from_user_id)
                                await send_request(session, "sendRichMessage", {
                                    "chat_id": chat_id, "rich_message": {"html":
                                        f'<h1>{EMOJI["up"]} Owner registered</h1>\n'
                                        f'<p>Your id: <code>{from_user_id}</code></p>\n'
                                        '<p>Paste this into the installer if it asks, '
                                        'then run <code>/setup</code>.</p>\n'
                                        '<tg-button-row>'
                                        '<tg-button type="callback_data" data="setup">Setup</tg-button>'
                                        '</tg-button-row>\n'}})
                                continue
                            if not _is_allowed(from_user_id):
                                # A stranger talking in a group we were never
                                # authorised to be in -> notice + leave (latched).
                                # NEVER leave an approved group: any member can
                                # chat there, and the bot previously walked out of
                                # its own log group because the in-memory approval
                                # set was empty after a restart.
                                if int(chat_id) < 0 and not is_approved_group(chat_id):
                                    await leave_group(session, chat_id, "unapproved group")
                                continue  # strangers can't use the admin bot
                            text = msg.get("text", "")
                            if text.startswith("/here"):
                                # Link the CURRENT chat as the log destination.
                                # Only the bot can learn a group's id, so this is
                                # the Telegram-side equivalent of an installer prompt.
                                # An owner-issued /here is also an explicit approval.
                                if int(chat_id) < 0:
                                    approve_group(chat_id)
                                html = await link_log_group(session, chat_id)
                                await send_request(session, "sendRichMessage", {
                                    "chat_id": chat_id, "rich_message": {"html": html}})
                            elif text.startswith("/setup"):
                                await render_menu(session, chat_id, from_user_id, "Setup", build_setup, delay=0.35)
                            elif text.startswith("/start"):
                                miss = setup_missing()
                                if miss:
                                    await render_menu(session, chat_id, from_user_id, "Setup", build_setup, delay=0.4)
                                else:
                                    await render_menu(session, chat_id, from_user_id, "Menu", build_main, delay=0.5)
                            elif text.startswith("/help"):
                                await render_menu(session, chat_id, from_user_id, "Help", lambda: build_main(), delay=0.35)
                            elif text.startswith("/stats"):
                                await render_menu(session, chat_id, from_user_id, "Status", lambda: build_status(True), delay=0.5)
                            elif text.startswith("/models"):
                                await render_menu(session, chat_id, from_user_id, "Models", build_models, delay=0.5)
                            elif text.startswith("/health"):
                                await render_menu(session, chat_id, from_user_id, "Health", lambda: build_status(True), delay=0.35)
                            elif text.startswith("/logs"):
                                # /logs  или  /logs <N>  — последние N строк bot.log
                                m = re.match(r"^/logs(?:\s+(\d+))?\s*$", text.strip())
                                n = 40
                                if m and m.group(1):
                                    n = max(1, min(int(m.group(1)), 500))
                                await render_menu(session, chat_id, from_user_id, f"Bot log ({n})",
                                                 lambda nn=n: build_bot_logs(nn), delay=0.35)
                            elif text.startswith("/tunnel"):
                                # /tunnel — туннели с кнопками (refresh/restart)
                                # /tunnel restart — перезапуск обоих туннелей
                                # /tunnel status — статус
                                parts = text.strip().split()
                                if len(parts) > 1 and parts[1] == "restart":
                                    await render_menu(session, chat_id, from_user_id, "Tunnel restart", lambda: _restart_tunnel_msg(), delay=0.4)
                                elif len(parts) > 1 and parts[1] == "status":
                                    await render_menu(session, chat_id, from_user_id, "Tunnels", build_tunnel, delay=0.35)
                                else:
                                    await render_menu(session, chat_id, from_user_id, "Tunnels", build_tunnel, delay=0.35)
                            elif text.startswith("/reqs"):
                                # /reqs — forward last N bridge log lines to Requests topic (if group has one)
                                m = re.match(r"^/reqs(?:\s+(\d+))?\s*$", text.strip())
                                n = 3
                                if m and m.group(1):
                                    n = max(1, min(int(m.group(1)), 20))
                                cycles = parse_request_cycles(
                                    read_log_lines("bridge.log", 3000))[-n:]
                                ok = await send_request_cards(session, cycles)
                                if ok:
                                    await send_request(session, "sendMessage", {
                                        "chat_id": chat_id,
                                        "text": f"Posted {len(cycles)} request card(s) "
                                                f"to the Requests topic.",
                                    })
                                else:
                                    await send_request(session, "sendMessage", {
                                        "chat_id": chat_id,
                                        "text": "No log group configured yet. Add me to a group "
                                                "(topics enabled) — I create Logs/Requests and "
                                                "remember the group automatically.",
                                    })
                            elif text.startswith("/logs_fwd"):
                                # /logs_fwd — форвард последних bridge-логов в группу/топик
                                ok = await forward_bridge_logs(session)
                                if ok:
                                    gid = log_group_id()
                                    await send_request(session, "sendMessage", {
                                        "chat_id": chat_id,
                                        "text": f"Logs forwarded to group {gid}.",
                                    })
                                else:
                                    await send_request(session, "sendMessage", {
                                        "chat_id": chat_id,
                                        "text": "No log group configured yet. Add me to a group "
                                                "(topics enabled) and I'll remember it.",
                                    })
                            elif text.startswith("/refresh"):
                                # /refresh — force token refresh, then show new expiry
                                await send_request(session, "sendMessage", {
                                    "chat_id": chat_id,
                                    "text": "🔄 Refreshing arena tokens...",
                                    "parse_mode": "HTML",
                                })
                                res = await _bridge_post(session, "/api/v1/refresh-tokens", {"force": True}, timeout=120)
                                err = res.get("error", "")
                                if err:
                                    msg = f"⚠️ <b>Refresh failed</b>: {esc(err)}"
                                else:
                                    tokens = res.get("auth_tokens") or []
                                    msg = f"✅ <b>Refresh complete</b> ({len(tokens)} tokens)"
                                await send_request(session, "sendMessage", {
                                    "chat_id": chat_id, "text": msg, "parse_mode": "HTML",
                                })
                            elif text.startswith("/webdev"):
                                await render_menu(session, chat_id, from_user_id, "WebDev", build_webdev, delay=0.5)
                            elif text and not text.startswith("/") and chat_id > 0:
                                # Bare owner DM: may be api_id / api_hash pasted via
                                # the inline-input buttons from /setup.
                                await handle_setup_text(session, chat_id, text)
                        elif "inline_query" in update:
                            try:
                                await handle_inline_query(session, update["inline_query"])
                            except Exception as e:
                                print(f"Inline answer error: {e}")
                        elif "callback_query" in update:
                            cq = update["callback_query"]
                            cmsg = cq.get("message") or {}
                            chat_id = (cmsg.get("chat") or {}).get("id")
                            message_id = cmsg.get("message_id")
                            # Callbacks from an ephemeral message carry this instead
                            # of a normal message_id; edits need the triple
                            # (chat_id, receiver_user_id, ephemeral_message_id).
                            eph_id = cmsg.get("ephemeral_message_id")
                            cb_data = cq.get("data", "")
                            cq_id = cq["id"]
                            from_user_id = (cq.get("from") or {}).get("id")
                            if chat_id is None:
                                await send_request(session, "answerCallbackQuery",
                                                   {"callback_query_id": cq_id})
                            else:
                                await handle_callback(session, cq_id, cb_data, chat_id,
                                                      message_id, from_user_id,
                                                      ephemeral_message_id=eph_id)
                        elif "my_chat_member" in update:
                            mcm = update["my_chat_member"]
                            new_status = (mcm.get("new_chat_member") or {}).get("status")
                            chat = mcm.get("chat") or {}
                            cid = chat.get("id")
                            inviter = (mcm.get("from") or {}).get("id")
                            if cid and int(cid) < 0:
                                print(f"[bot] my_chat_member: chat={cid} "
                                      f"status={new_status} actor={inviter} "
                                      f"owner={_is_allowed(inviter or 0)} "
                                      f"approved={is_approved_group(cid)}")
                                if new_status in ("left", "kicked"):
                                    _group_state.pop(int(cid), None)
                                elif new_status in ("member", "administrator"):
                                    await on_added_to_group(session, chat, inviter, new_status)
            except Exception as e:
                print("Poller error:")
                traceback.print_exc()
                await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())