// Self-contained for WebDeployer: NO import/export statements.
// React + ReactDOM are already loaded as globals by the wrapper HTML.
// The wrapper looks for a global `App` function and renders it — that's it.

const { useState, useEffect, useRef, useCallback, useMemo } = React;

function copyToClipboard(text, showToast) {
  if (typeof navigator !== "undefined" && navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(String(text ?? "")).catch(() => {});
  } else {
    // Fallback for non-secure contexts
    const ta = document.createElement("textarea");
    ta.value = String(text ?? "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(ta);
  }
  if (showToast) {
    try { window.hermesToast && window.hermesToast("Copied"); } catch (e) {}
  }
}

/* ============================================================================
 * Tiny inline icon set (no lucide-react — it isn't available in this runtime)
 * ========================================================================= */
function Icon({ path, size = 16, ...rest }) {
  return React.createElement(
    "svg",
    { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", ...rest },
    React.createElement("path", { d: path })
  );
}
const ICONS = {
  terminal: "M4 17l6-6-6-6M12 19h8",
  shieldCheck: "M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-4zM9 12l2 2 4-4",
  shieldAlert: "M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-4zM12 8v5M12 16h.01",
  refresh: "M21 12a9 9 0 11-3-6.7M21 3v6h-6",
  key: "M21 2l-2 2m-7.61 7.61a5.5 5.5 0 11-7.778 7.778 5.5 5.5 0 017.778-7.778zm0 0L15.5 7.5m0 0L19 4m-3.5 3.5L18 10",
  cloud: "M17.5 19a4.5 4.5 0 000-9 6 6 0 10-11.4 3.2A4 4 0 007 19h10.5z",
  bot: "M12 8V4H8M4 8h16v10a2 2 0 01-2 2H6a2 2 0 01-2-2V8zM9 13v2M15 13v2",
  activity: "M22 12h-4l-3 9L9 3l-3 9H2",
  logout: "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4m7 14l5-5-5-5M20 12H9",
  trash: "M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14z",
  plus: "M12 5v14M5 12h14",
  loader: "M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8",
  // speaker / mute icons
  volume: "M11 5L6 9H2v6h4l5 4V5z",
  mute: "M18.36 6.64L16.95 8.05 15 6.1 13.59 7.51 15.54 9.46 14.13 10.87 12.18 8.92 10.77 10.33 12.72 12.28 11.31 13.69 9.36 11.74 7.95 13.15 10.9 16.1 12.31 14.69 14.26 16.64 15.67 15.23 13.72 13.28 15.13 11.87 17.08 13.82 18.49 12.41 16.54 10.46 18.36 8.64",
};

/* ============================================================================
 * AUTH — Telegram Mini App initData check
 *
 * IMPORTANT FOR WHOEVER TOUCHES THIS NEXT:
 * The bot token can NEVER live in this file or in any bundle shipped to the
 * browser — it's a secret. This frontend only reads `tg.initData` (the raw,
 * signed query-string Telegram injects) and forwards it, as-is, to
 * VERIFY_ENDPOINT below. The actual signature check has to happen on a
 * server that holds the bot token. Right now VERIFY_ENDPOINT is a stub — it
 * will 404 until a real backend route exists. That's expected.
 *
 * How to implement VERIFY_ENDPOINT on the backend (per
 * telegram-auth-tgs-skill.md, section 1):
 *   1. Parse initData as a query string. Pull out `hash`, keep everything
 *      else (user, auth_date, query_id, ...).
 *   2. Build the "data check string": sort the remaining key=value pairs
 *      alphabetically by key, join with "\n".
 *   3. secret_key = HMAC_SHA256(key = "WebAppData", data = <bot_token>)
 *   4. computed_hash = HMAC_SHA256(key = secret_key, data = <data check string>)
 *      then hex-encode it.
 *   5. Compare computed_hash to the `hash` field from initData using a
 *      constant-time comparison. Reject if they don't match.
 *   6. Optionally reject if `auth_date` is older than e.g. 24h (replay
 *      protection).
 *   7. Only if all of the above pass, trust `user.id` from initData and
 *      issue your own session/JWT back to the client.
 *
 * Reference implementation (Node.js, backend-only — do NOT port this into
 * this file, it needs process.env.BOT_TOKEN which must never reach the
 * browser):
 *
 *   const crypto = require("crypto");
 *
 *   function verifyTelegramInitData(initData, botToken) {
 *     const params = new URLSearchParams(initData);
 *     const hash = params.get("hash");
 *     params.delete("hash");
 *
 *     const dataCheckString = [...params.entries()]
 *       .sort(([a], [b]) => a.localeCompare(b))
 *       .map(([k, v]) => `${k}=${v}`)
 *       .join("\n");
 *
 *     const secretKey = crypto.createHmac("sha256", "WebAppData").update(botToken).digest();
 *     const computedHash = crypto.createHmac("sha256", secretKey).update(dataCheckString).digest("hex");
 *
 *     const ok = crypto.timingSafeEqual(Buffer.from(computedHash), Buffer.from(hash));
 *     if (!ok) return { valid: false };
 *
 *     const authDate = Number(params.get("auth_date")) * 1000;
 *     if (Date.now() - authDate > 24 * 60 * 60 * 1000) return { valid: false, reason: "expired" };
 *
 *     return { valid: true, user: JSON.parse(params.get("user") || "{}") };
 *   }
 *
 * That function is what should sit behind VERIFY_ENDPOINT, returning
 * { user } with a 200 on success or a non-2xx on failure. Everything below
 * this comment is just the client half: send initData, trust the server's
 * verdict.
 * ========================================================================= */
// Single source of truth for the backend URL. Point this at wherever
// server.js (see /server) is deployed. Everything else below derives its
// endpoint paths from this constant, so swapping backends is a one-line change.
const API_BASE_URL = "/api";
const VERIFY_ENDPOINT = `${API_BASE_URL}/auth/verify`;
const LOGOUT_ENDPOINT = `${API_BASE_URL}/auth/logout`;
const STATE_ENDPOINT = `${API_BASE_URL}/state`;
const KEYS_ENDPOINT = `${API_BASE_URL}/keys`;
const TOKENS_ENDPOINT = `${API_BASE_URL}/tokens`;
const REFRESH_ENDPOINT = `${API_BASE_URL}/refresh`;
const BRIDGE_HEALTH_ENDPOINT = `${API_BASE_URL}/bridge/health`;
const BRIDGE_MODELS_ENDPOINT = `${API_BASE_URL}/bridge/models`;

function loadTelegramSDK() {
  return new Promise((resolve) => {
    if (window.Telegram && window.Telegram.WebApp) return resolve(window.Telegram.WebApp);
    const s = document.createElement("script");
    s.src = "https://telegram.org/js/telegram-web-app.js";
    s.onload = () => resolve(window.Telegram ? window.Telegram.WebApp : null);
    s.onerror = () => resolve(null);
    document.head.appendChild(s);
  });
}

async function verifyWithBackend(initData) {
  // Add client-side timeout to avoid hanging forever when /api/auth/verify stalls
  const ctl = new AbortController();
  const timeout = setTimeout(() => ctl.abort(), 5000);
  try {
    const res = await fetch(VERIFY_ENDPOINT, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initData }),
      signal: ctl.signal,
    });
    clearTimeout(timeout);
    if (!res.ok) return { ok: false, reason: "server_" + res.status };
    const data = await res.json();
    return { ok: true, user: data.user };
  } catch (e) {
    if (e && e.name === 'AbortError') return { ok: false, reason: 'timeout' };
    return { ok: false, reason: 'network' };
  }
}

/* ============================================================================
 * Dashboard API client — thin wrappers around the endpoints exposed by
 * server.js. Every call sends the httpOnly session cookie set during
 * /api/auth/verify (credentials: "include"); the browser never sees a token,
 * only the signed cookie the backend issued after checking initData.
 * ========================================================================= */
async function apiRequest(url, options = {}) {
  const res = await fetch(url, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let bodyText = null;
    try {
      const ct = res.headers.get('content-type') || '';
      if (ct.includes('application/json')) {
        const body = await res.json();
        bodyText = body.detail || body.reason || JSON.stringify(body);
      } else {
        bodyText = await res.text();
      }
    } catch (e) {
      bodyText = null;
    }
    const err = new Error(bodyText ? `${bodyText}` : `api_error_${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}
const api = {
  getState: () => apiRequest(STATE_ENDPOINT),
  createKey: (name, rpm) => apiRequest(KEYS_ENDPOINT, { method: "POST", body: JSON.stringify({ name, rpm }) }),
  deleteKey: (key) => apiRequest(`${KEYS_ENDPOINT}/${encodeURIComponent(key)}`, { method: "DELETE" }),
  addToken: (token) => apiRequest(TOKENS_ENDPOINT, { method: "POST", body: JSON.stringify({ token }) }),
  deleteToken: (index) => apiRequest(`${TOKENS_ENDPOINT}/${index}`, { method: "DELETE" }),
  // refresh accepts optional fetch options (e.g., { signal }) so caller can abort
  refresh: (opts = {}) => apiRequest(REFRESH_ENDPOINT, { method: "POST", ...opts }),
  bridgeHealth: () => apiRequest(BRIDGE_HEALTH_ENDPOINT),
  bridgeModels: () => apiRequest(BRIDGE_MODELS_ENDPOINT),
  arenaStatus: () => apiRequest(`${API_BASE_URL}/arena/status`),
  logout: () => apiRequest(LOGOUT_ENDPOINT, { method: "POST" }),
};

/* ============================================================================
 * Background music — ambient autoplay, no visible control.
 * Browsers/WebViews commonly block sound-on autoplay until a user gesture.
 * We try immediately; if blocked, a single tap/click/keydown anywhere on
 * the page silently unlocks it. There's intentionally no on-screen toggle.
 * ========================================================================= */
const MUSIC_URL = "https://raw.githubusercontent.com/i-execute/Arena/main/Storage/Media/Dashboard_theme.mp3";

function useBackgroundMusic() {
  const audioRef = useRef(null);
  const [muted, setMuted] = useState(false);

  useEffect(() => {
    const audio = new Audio(MUSIC_URL);
    audio.loop = true;
    audio.volume = 0.5;
    audio.muted = muted;
    audioRef.current = audio;

    audio.play().catch(() => {});

    const unlock = () => {
      audio.play().then(() => {
        window.removeEventListener("pointerdown", unlock);
        window.removeEventListener("keydown", unlock);
      }).catch(() => {});
    };
    window.addEventListener("pointerdown", unlock, { once: true });
    window.addEventListener("keydown", unlock, { once: true });

    return () => {
      audio.pause();
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, []);

  // keep muted state in sync with the audio element
  useEffect(() => {
    if (audioRef.current) audioRef.current.muted = muted;
  }, [muted]);

  const toggle = useCallback(() => setMuted((m) => !m), []);
  const music = useMemo(() => ({ muted, setMuted, toggle, audioRef }), [muted]);
  return music;
}

/* ============================================================================
 * Lottie sticker (plain .json — no .tgs gzip step needed)
 * ========================================================================= */
function loadScript(src) {
  return new Promise((resolve) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => resolve();
    document.head.appendChild(s);
  });
}
// This is a plain Lottie .json (confirmed: application/json, ~930KB),
// NOT a gzipped .tgs — so no pako/inflate step, per lottie-json-web-skill.md.
// It's rendered unconditionally in the gate card below, independent of
// auth `phase` — it shows during "boot" and "denied" too, not just once
// access is granted.
async function playLottie(container, jsonUrl) {
  try {
    if (!window.lottie) await loadScript("https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie.min.js");
    const res = await fetch(jsonUrl);
    if (!res.ok) throw new Error("sticker fetch failed: " + res.status);
    const animationData = await res.json();
    return window.lottie.loadAnimation({ container, renderer: "svg", loop: true, autoplay: true, animationData });
  } catch (e) {
    console.error("GateSticker: failed to load animation", e);
    if (container) container.innerHTML = "👻";
    return null;
  }
}
// raw file link, not a github.com/.../blob/... page — blob would return HTML, not JSON
const GATE_STICKER_URL = "https://raw.githubusercontent.com/i-execute/Arena/main/Storage/Media/RTX_GPU.json";
function GateSticker({ url } = {}) {
  const ref = useRef(null);
  useEffect(() => {
    let anim, cancelled = false;
    const src = url || GATE_STICKER_URL;
    if (ref.current) {
      playLottie(ref.current, src).then((a) => {
        if (cancelled && a) a.destroy(); else anim = a;
      });
    }
    return () => { cancelled = true; if (anim) anim.destroy(); };
  }, [url]);
  return React.createElement("div", { className: "gate-sticker", ref });
}

const BOOT_LINES = [
  "initializing secure channel...",
  "requesting telegram.webapp handshake...",
  "reading initData signature...",
  "dispatching hash to verification service...",
  "awaiting server response...",
];
function useBootSequence(active) {
  const [lines, setLines] = useState([]);
  useEffect(() => {
    if (!active) return;
    let i = 0;
    setLines([]);
    const id = setInterval(() => {
      setLines((prev) => (i < BOOT_LINES.length ? [...prev, BOOT_LINES[i]] : prev));
      i += 1;
      if (i > BOOT_LINES.length) clearInterval(id);
    }, 300);
    return () => clearInterval(id);
  }, [active]);
  return lines;
}

/* ============================================================================
 * Page 1 — Access gate (separate screen, never mixed with dashboard markup)
 * ========================================================================= */
function AccessGate({ phase, reason, onRetry }) {
  const bootLines = useBootSequence(phase === "boot");
  return React.createElement(
    "div", { className: "gate" },
    React.createElement(
      "div", { className: "gate-card" },
      React.createElement("div", { className: "gate-brand" }, React.createElement(Icon, { path: ICONS.shieldCheck, size: 16 }), React.createElement("span", null, "SECURE ACCESS")),
      phase === "boot" && React.createElement(
        "div", { className: "gate-log" },
        bootLines.map((l, i) => React.createElement("div", { className: "log-line", key: i }, l)),
        bootLines.length < BOOT_LINES.length && React.createElement(
          "div", { className: "log-line accent" },
          React.createElement(Icon, { path: ICONS.loader, size: 12, className: "spin" }), " working"
        )
      ),
      phase === "denied" && React.createElement(
        "div", null,
        React.createElement(
          "div", { className: "gate-status denied" },
          React.createElement(Icon, { path: ICONS.shieldAlert, size: 20 }),
          reason === "not_opened_via_bot" ? "not opened through the bot" : "verification rejected"
        ),
        React.createElement(
          "p", { className: "gate-detail" },
          reason === "not_opened_via_bot"
            ? "Open this page via the bot's web_app button. A plain link carries no initData, so there's nothing to sign or verify."
            : "The backend could not confirm this request's signature — bad hash, stale auth_date, or the verify endpoint is unreachable."
        ),
        React.createElement("button", { className: "gate-retry", onClick: onRetry }, React.createElement(Icon, { path: ICONS.refresh, size: 13 }), " retry handshake")
      )
    )
  );
}

/* ============================================================================
 * Page 2 — Dashboard (rebuilt from main.py; CSS-only charts, no chart libs)
 * ========================================================================= */
// Empty-state defaults, used only until the real /api/state response lands
// (or if that fetch fails) — no more fake demo data baked into the bundle.
const EMPTY_STATE = { api_keys: [], auth_tokens: [], models: [], usage: {} };
const COLORS = ["#38bdf8", "#22d3ee", "#818cf8", "#7dd3fc", "#a5b4fc", "#0ea5e9", "#67e8f9", "#94a3b8"];

function DonutChart({ data }) {
  const total = data.reduce((a, d) => a + d.value, 0);
  let acc = 0;
  const stops = data.map((d, i) => {
    const start = (acc / total) * 360;
    acc += d.value;
    const end = (acc / total) * 360;
    return `${COLORS[i % COLORS.length]} ${start}deg ${end}deg`;
  });
  return React.createElement(
    "div", { className: "donut-wrap" },
    React.createElement("div", { className: "donut", style: { background: `conic-gradient(${stops.join(",")})` } },
      React.createElement("div", { className: "donut-hole" }, React.createElement("span", null, total), React.createElement("small", null, "requests"))
    ),
    React.createElement(
      "div", { className: "legend" },
      data.map((d, i) => React.createElement(
        "div", { className: "legend-row", key: d.name },
        React.createElement("span", { className: "dot", style: { background: COLORS[i % COLORS.length] } }),
        React.createElement("span", null, d.name), React.createElement("small", null, d.value)
      ))
    )
  );
}
function BarsChart({ data }) {
  const max = Math.max(...data.map((d) => d.value), 1);
  return React.createElement(
    "div", { className: "bars" },
    data.map((d, i) => React.createElement(
      "div", { className: "bar-row", key: d.name },
      React.createElement("div", { className: "bar-label" }, d.name),
      React.createElement("div", { className: "bar-track" },
        React.createElement("div", { className: "bar-fill", style: { width: (d.value / max) * 100 + "%", background: COLORS[i % COLORS.length] } })
      ),
      React.createElement("div", { className: "bar-value" }, d.value)
    ))
  );
}

function Dashboard({ onLogout, music }) {
  const [state, setState] = useState(EMPTY_STATE);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [newTokenValue, setNewTokenValue] = useState("");
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyRpm, setNewKeyRpm] = useState(60);
  const [copiedKey, setCopiedKey] = useState(null);
  const [modelQuery, setModelQuery] = useState("");
  // Separate IN (input capabilities) and OUT (output capabilities) filters.
  const [filterIn, setFilterIn] = useState("all");
  const [filterOut, setFilterOut] = useState("all");
  const [bridgeHealth, setBridgeHealth] = useState(null);
  const [arenaHealth, setArenaHealth] = useState(null);

  const keys = state.api_keys || [];
  const tokens = state.auth_tokens || [];
  const models = state.models || [];

  // Normalize a model's capabilities into a flat list of filterable tokens.
  function modelCaps(m) {
    const caps = [];
    if (typeof m.capabilities === 'object' && m.capabilities !== null && !Array.isArray(m.capabilities)) {
      const ic = m.capabilities.inputCapabilities || {};
      const oc = m.capabilities.outputCapabilities || {};
      if (ic.text) caps.push("chat_input");
      if (ic.image) caps.push("vision");
      if (ic.video) caps.push("video_input");
      if (ic.file) caps.push("file");
      if (oc.text) caps.push("text");
      if (oc.image) caps.push("image");
      if (oc.search) caps.push("search");
      if (oc.web) caps.push("webdev");
      if (oc.video) caps.push("video");
    } else if (Array.isArray(m.capabilities)) {
      caps.push(...m.capabilities);
    }
    return caps;
  }

  const filteredModels = useMemo(() => {
    const q = modelQuery.trim().toLowerCase();
    return models.filter((m) => {
      const name = String(m.name || m.publicName || m.id || "");
      const org = String(m.org || m.organization || m.owned_by || "");
      const capsList = modelCaps(m);
      const searchable = `${name} ${org} ${capsList.join(" ")}`.toLowerCase();

      // IN filter: only input capabilities.
      let inOk = filterIn === "all" || capsList.includes(filterIn);
      // OUT filter: only output capabilities.
      let outOk = filterOut === "all" || capsList.includes(filterOut);

      // Fallback by name when a model has no structured capabilities (e.g. old dumps).
      if (filterIn !== "all" && capsList.length === 0) {
        const n = name.toLowerCase();
        if (filterIn === "chat_input") inOk = !n.includes("search") && !n.includes("grounding") && !n.includes("image") && !n.includes("vision") && !n.includes("video");
        if (filterIn === "vision") inOk = n.includes("image") || n.includes("vision") || n.includes("vl");
        if (filterIn === "video_input") inOk = n.includes("video") || n.includes("vid");
        if (filterIn === "file") inOk = n.includes("file");
      }
      if (filterOut !== "all" && capsList.length === 0) {
        const n = name.toLowerCase();
        if (filterOut === "text") outOk = !n.includes("search") && !n.includes("grounding") && !n.includes("image") && !n.includes("vision") && !n.includes("video");
        if (filterOut === "image") outOk = n.includes("image") || n.includes("vision") || n.includes("vl");
        if (filterOut === "video") outOk = n.includes("video") || n.includes("vid");
        if (filterOut === "search") outOk = n.includes("search") || n.includes("grounding");
        if (filterOut === "webdev") outOk = n.includes("web") || n.includes("site");
      }

      return (!q || searchable.includes(q)) && inOk && outOk;
    });
  }, [models, modelQuery, filterIn, filterOut]);

  const copyKey = async (key) => {
    let ok = false;
    try {
      if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.writeTextToClipboard) {
        if (window.Telegram.WebApp.HapticFeedback && window.Telegram.WebApp.HapticFeedback.impactOccurred) {
          window.Telegram.WebApp.HapticFeedback.impactOccurred('medium');
        }
        window.Telegram.WebApp.writeTextToClipboard(key);
        ok = true;
      } else if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(key);
        if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.HapticFeedback && window.Telegram.WebApp.HapticFeedback.impactOccurred) {
          window.Telegram.WebApp.HapticFeedback.impactOccurred('medium');
        }
        ok = true;
      }
    } catch (e) {
      ok = false;
    }

    if (!ok) {
      try {
        const ta = document.createElement('textarea');
        ta.value = key;
        ta.style.position = 'fixed'; ta.style.top = '0'; ta.style.left = '0'; ta.style.width = '1px'; ta.style.height = '1px'; ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus(); ta.select();
        const res = document.execCommand('copy');
        document.body.removeChild(ta);
        ok = !!res;
      } catch (e) {
        ok = false;
      }
    }

    if (!ok) {
      // Final fallback: show prompt with the key pre-selected so user can manually copy (works in webviews)
      try {
        window.prompt('Copy API key (Ctrl/Cmd+C, Enter to close)', key);
        ok = true; // assume user copied
      } catch (e) {
        ok = false;
      }
    }

    if (ok) setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1500);
  };

  const loadState = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getState();
      setState(data);
    } catch (e) {
      // Session cookie missing/expired mid-session -> bounce back to the gate.
      if (e.status === 401) return onLogout();
      setError("Couldn't load dashboard data from the server.");
    } finally {
      setLoading(false);
    }
  }, [onLogout]);

  useEffect(() => {
    loadState();
    api.bridgeHealth().then(setBridgeHealth).catch(() => setBridgeHealth({ status: "unreachable" }));
    api.arenaStatus().then(setArenaHealth).catch(() => setArenaHealth({ status: "unreachable" }));
  }, [loadState]);

  const hasAuthToken = state.has_auth_token ?? tokens.length > 0;
  const usageData = useMemo(
    () => Object.entries(state.usage || {}).filter(([k, v]) => typeof v === 'number').sort((a, b) => b[1] - a[1]).map(([name, value]) => ({ name, value })),
    [state.usage]
  );
  const totalRequests = state.total_requests ?? usageData.reduce((a, d) => a + d.value, 0);
  // Today's request count — server reports `usage_today` when available.
  const todayRequests = state.usage_today ?? 0;

  const addToken = async (e) => {
    e.preventDefault();
    const t = newTokenValue.trim();
    if (!t) return;
    setNewTokenValue("");
    try {
      await api.addToken(t);
      loadState();
    } catch {
      setError("Failed to add token.");
    }
  };
  const deleteToken = async (idx) => {
    try {
      await api.deleteToken(idx);
      loadState();
    } catch {
      setError("Failed to delete token.");
    }
  };
  const createKey = async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    try {
      // allow empty name -> server will auto-generate
      const name = (newKeyName || '').trim();
      const rpm = Number(newKeyRpm) || 60;
      await api.createKey(name, rpm);
      setNewKeyName(""); setNewKeyRpm(60);
      loadState();
    } catch (err) {
      setError((err && err.message) ? String(err.message) : "Failed to create key.");
    }
  };
  const deleteKey = async (key) => {
    if (!window.confirm("Delete this API key?")) return;
    try {
      await api.deleteKey(key);
      loadState();
    } catch {
      setError("Failed to delete key.");
    }
  };
  const refreshTokensAndModels = async () => {
    setRefreshing(true);
    setError(null);
    const ctl = new AbortController();
    const to = setTimeout(() => ctl.abort(), 180000); // 180s timeout
    try {
      const res = await api.refresh({ signal: ctl.signal });
      clearTimeout(to);
      if (res && res.state) {
        setState(res.state);
      } else if (res && res.ok && res.state) {
        setState(res.state);
      }
    } catch (e) {
      clearTimeout(to);
      if (e && e.status === 401) {
        onLogout();
        return;
      }
      if (e && e.name === 'AbortError') {
        setError('Refresh timed out (180s).');
      } else if (e && e.message) {
        setError(String(e.message));
      } else {
        setError('Refresh failed.');
      }
    } finally {
      setRefreshing(false);
    }
  };
  const handleLogout = async () => {
    try { await api.logout(); } catch {}
    onLogout();
  };

  return React.createElement(
    "div", { className: "dash" },
    React.createElement(
      "header", { className: "dash-header" },
      React.createElement(
        "div", { className: "dash-header-inner" },
          React.createElement("div", { className: "header-sticker" }, React.createElement(GateSticker, { url: GATE_STICKER_URL })),
          React.createElement("div", { className: "dash-title" }, "Arena Dashboard"),
          React.createElement("div", { style: { display: 'flex', gap: 8, alignItems: 'center' } },
            React.createElement("button", { className: "logout-btn", onClick: () => music && music.toggle(), "aria-label": "Toggle mute" }, React.createElement(Icon, { path: music && music.muted ? ICONS.mute : ICONS.volume, size: 14 }), React.createElement("span", { className: "mute-label" }, music && music.muted ? "Unmute" : "Mute")),
          )
        )
      ),
    React.createElement(
      "main", { className: "dash-container" },

      error && React.createElement(
        "div", { className: "empty", style: { color: "#fb7185", marginBottom: 14 } }, error
      ),
      loading && React.createElement(
        "div", { className: "empty" }, "loading dashboard state…"
      ),

      React.createElement(
        "section", { className: "stats-grid" },
        React.createElement("div", { className: "stat-card" }, React.createElement("div", { className: "stat-value" }, keys.length), React.createElement("div", { className: "stat-label" }, "API keys")),
        React.createElement("div", { className: "stat-card" }, React.createElement("div", { className: "stat-value" }, models.length), React.createElement("div", { className: "stat-label" }, "Available models")),
        React.createElement("div", { className: "stat-card requests" },
          React.createElement("div", { className: "stat-value" }, totalRequests),
          React.createElement("div", { className: "stat-label" }, "Requests",
            React.createElement("div", { className: "stat-today" }, "+", todayRequests, " today")
          )
        ),
        React.createElement("div", { className: "stat-card" },
          React.createElement("div", { className: "stat-value " + ((bridgeHealth && (bridgeHealth.status === "healthy" || (bridgeHealth.checks && bridgeHealth.checks.models_loaded))) ? "arena-on" : "arena-off") }, bridgeHealth && bridgeHealth.status !== "unreachable" ? "ON" : "—"),
          React.createElement("div", { className: "stat-label" }, "Bridge status")
        ),
        React.createElement("div", { className: "stat-card" },
          React.createElement("div", { className: "stat-value " + (arenaHealth && arenaHealth.ok ? "arena-on" : "arena-off") }, arenaHealth && arenaHealth.ok ? "ON" : "OFF"),
          React.createElement("div", { className: "stat-label" }, "Arena status")
        )
      ),

      React.createElement(
        "section", { className: "panel" },
        React.createElement(
          "div", { className: "panel-head" },
          React.createElement("h2", null, React.createElement(Icon, { path: ICONS.key, size: 15 }), " Arena authentication tokens"),
          React.createElement("span", { className: "badge " + (hasAuthToken ? "good" : "bad") }, hasAuthToken ? "Configured" : "Not set")
        ),
        React.createElement("p", { className: "hint" }, "Multiple tokens round-robin — each conversation sticks to one consistently."),
        tokens.length === 0 && React.createElement("div", { className: "empty" }, "No tokens configured. Add one below."),
        tokens.map((token, i) => React.createElement(
          "div", { className: "token-row", key: i },
          React.createElement("code", null, token.slice(0, 46) + "…"),
          React.createElement("button", { className: "icon-btn danger", onClick: () => deleteToken(i), "aria-label": "Delete token" }, React.createElement(Icon, { path: ICONS.trash, size: 14 }))
        )),
        React.createElement(
          "form", { className: "form-block", onSubmit: addToken },
          React.createElement("label", { htmlFor: "new_auth_token" }, "New arena auth token"),
          React.createElement("textarea", { id: "new_auth_token", placeholder: "Paste an arena-auth-prod-v1 token here", value: newTokenValue, onChange: (e) => setNewTokenValue(e.target.value), required: true }),
          React.createElement("button", { type: "submit", className: "btn-primary" }, React.createElement(Icon, { path: ICONS.plus, size: 14 }), " Add token")
        )
      ),

      React.createElement(
        "section", { className: "panel" },
        React.createElement(
          "div", { className: "panel-head" },
          React.createElement("h2", null, React.createElement(Icon, { path: ICONS.cloud, size: 15 }), " Cloudflare clearance"),
          React.createElement("span", { className: "badge good" }, "Configured")
        ),
        React.createElement("p", { className: "hint" }, "Fetched automatically on startup. Repeated 404s from the API usually mean it's stale."),
        React.createElement("code", { className: "code-block" }, state.cf_clearance_configured ? "cf_clearance=•••••••••••• (auto-refreshed on startup)" : "cf_clearance not set"),
        React.createElement(
          "button",
          { className: "btn-primary", style: { marginTop: 14 }, onClick: refreshTokensAndModels, disabled: refreshing },
          React.createElement(Icon, { path: ICONS.refresh, size: 14, className: refreshing ? "spin" : "" }),
          refreshing ? " Refreshing…" : " Refresh tokens & models"
        )
      ),

      React.createElement(
        "section", { className: "panel" },
        React.createElement("div", { className: "panel-head" }, React.createElement("h2", null, React.createElement(Icon, { path: ICONS.key, size: 15 }), " API keys")),
        React.createElement(
          "div", { className: "table-wrap" },
          React.createElement(
            "table", null,
            React.createElement("thead", null, React.createElement("tr", null,
              React.createElement("th", null, "Name"), React.createElement("th", null, "Key"),
              React.createElement("th", null, "Rate limit"), React.createElement("th", null, "Created"), React.createElement("th", null)
            )),
            React.createElement(
              "tbody", null,
              keys.length === 0 && React.createElement("tr", null, React.createElement("td", { colSpan: 5, className: "empty" }, "No API keys configured")),
              keys.map((k) => React.createElement(
                "tr", { key: k.key },
                React.createElement("td", null, React.createElement("strong", null, k.name)),
                React.createElement("td", { onClick: () => copyKey(k.key), title: "Click to copy", style: { cursor: 'pointer', position: 'relative' } }, 
                  React.createElement("code", { className: copiedKey === k.key ? "key-code copied" : "key-code" }, copiedKey === k.key ? "Copied!" : k.key)
                ),
                React.createElement("td", null, React.createElement("span", { className: "badge neutral" }, k.rpm + " RPM")),
                React.createElement("td", { className: "muted" }, k.created),
                React.createElement("td", null, React.createElement("button", { className: "icon-btn danger", onClick: () => deleteKey(k.key), "aria-label": "Delete key" }, React.createElement(Icon, { path: ICONS.trash, size: 14 })))
              ))
            )
          )
        ),
        React.createElement(
          "form", { className: "form-row", onSubmit: createKey },
          React.createElement("div", { className: "form-block" },
            React.createElement("label", { htmlFor: "name" }, "Key name (leave empty to auto-generate)"),
            React.createElement("input", { id: "name", placeholder: "e.g. Production key", value: newKeyName, onChange: (e) => setNewKeyName(e.target.value) })
          ),
          React.createElement("div", { className: "form-block" },
            React.createElement("label", { htmlFor: "rpm" }, "Rate limit (RPM)"),
            React.createElement("input", { id: "rpm", type: "number", min: 1, max: 1000, value: newKeyRpm, onChange: (e) => setNewKeyRpm(e.target.value) })
          ),
          React.createElement("button", { type: "submit", className: "btn-primary" }, React.createElement(Icon, { path: ICONS.plus, size: 14 }), " Create key")
        )
      ),

      React.createElement(
        "section", { className: "panel" },
        React.createElement("div", { className: "panel-head" }, React.createElement("h2", null, React.createElement(Icon, { path: ICONS.activity, size: 15 }), " Usage statistics")),
        usageData.length === 0
          ? React.createElement("div", { className: "empty" }, "No usage data yet")
          : React.createElement(
              "div", { className: "charts-grid" },
              React.createElement("div", { className: "chart-box" }, React.createElement("div", { className: "chart-title" }, "Model usage distribution"), React.createElement(DonutChart, { data: usageData })),
              React.createElement("div", { className: "chart-box" }, React.createElement("div", { className: "chart-title" }, "Requests by model"), React.createElement(BarsChart, { data: usageData }))
            )
      ),

      React.createElement(
        "section", { className: "panel" },
        React.createElement("div", { className: "panel-head" }, React.createElement("h2", null, React.createElement(Icon, { path: ICONS.bot, size: 15 }), " Available models"), React.createElement("span", { className: "badge neutral" }, `${filteredModels.length}/${models.length}`)),
        React.createElement("p", { className: "hint" }, "Search models by name, provider, or capability. These are the model IDs accepted by /api/v1/chat/completions."),
        React.createElement("div", { className: "model-filters" },
          React.createElement("input", { placeholder: "Search models…", value: modelQuery, onChange: (e) => setModelQuery(e.target.value) }),
          React.createElement("div", { className: "filter-group" },
            React.createElement("div", { className: "filter-buttons in-group" },
              React.createElement("label", { className: "filter-label in-label" }, "IN"),
              React.createElement("select", { value: filterIn, onChange: (e) => setFilterIn(e.target.value), className: "filter-select in" },
                React.createElement("option", { value: "all" }, "All"),
                React.createElement("option", { value: "chat_input" }, "Chat"),
                React.createElement("option", { value: "vision" }, "Vision"),
                React.createElement("option", { value: "video_input" }, "Video"),
                React.createElement("option", { value: "file" }, "File")
              )
            ),
            React.createElement("div", { className: "filter-buttons out-group" },
              React.createElement("label", { className: "filter-label out-label" }, "OUT"),
              React.createElement("select", { value: filterOut, onChange: (e) => setFilterOut(e.target.value), className: "filter-select out" },
                React.createElement("option", { value: "all" }, "All"),
                React.createElement("option", { value: "text" }, "Text"),
                React.createElement("option", { value: "image" }, "Image"),
                React.createElement("option", { value: "video" }, "Video"),
                React.createElement("option", { value: "webdev" }, "WebDev"),
                React.createElement("option", { value: "search" }, "Search")
              )
            )
          )
        ),
        models.length === 0
          ? React.createElement("div", { className: "empty" }, "No models loaded yet — hit “Refresh tokens & models” above.")
          : React.createElement("div", { className: "model-grid" }, filteredModels.map((m) => {
   const capsList = modelCaps(m);
   const badgeMap = { chat_input: ["Chat", "input"], vision: ["Vision", "input"], video_input: ["Video", "input"], file: ["File", "input"], text: ["Text", "output"], image: ["Image", "output"], video: ["Video", "output"], webdev: ["WebDev", "output"], search: ["Search", "output"] };
   const caps = [...new Set(capsList.map(c => ({ badge: badgeMap[c]?.[0] || c, class: badgeMap[c]?.[1] || "input" })))];
   
   return React.createElement("div", { className: "model-card", key: `${m.name}-${m.rank}` },
     React.createElement("div", { className: "model-card-head" }, React.createElement("span", { className: "model-name", onClick: () => copyToClipboard(m.name, true), title: "Click to copy", style: { cursor: "pointer", color: "#38bdf8" } }, m.name), React.createElement("span", { className: "badge neutral" }, "Rank " + m.rank)),
     React.createElement("div", { className: "muted" }, m.org),
                React.createElement("div", { className: "capability-list" }, caps.map((cap) => React.createElement("span", { className: `badge ${cap.class}`, key: cap.badge }, cap.badge)))
              );
            }))
      )
    )
  );
}

/* ============================================================================
 * Root — wrapper HTML looks for a global `App` and does
 * ReactDOM.createRoot(root).render(React.createElement(App))
 * ========================================================================= */
function App() {
  const [phase, setPhase] = useState("boot");
  const [reason, setReason] = useState("");
  const music = useBackgroundMusic();

  const runAuth = useCallback(async () => {
    setPhase("boot");
    const tg = await loadTelegramSDK();
    if (!tg || !tg.initData) {
      setReason("not_opened_via_bot");
      // Dev-mode bypass: send "dev" as initData so the backend can allow
      // direct browser access when DEV_MODE=true.
      const result = await verifyWithBackend("dev");
      if (result.ok) setPhase("granted");
      else setPhase("denied");
      return;
    }
    tg.ready();
    tg.expand();
    const result = await verifyWithBackend(tg.initData);
    if (result.ok) setPhase("granted");
    else { setReason(result.reason || "rejected"); setPhase("denied"); }
  }, []);

  useEffect(() => { runAuth(); }, [runAuth]);

  return React.createElement(
    React.Fragment, null,
    React.createElement(GlobalStyle, null),
    phase === "granted"
      ? React.createElement(Dashboard, { onLogout: () => setPhase("denied"), music })
      : React.createElement(AccessGate, { phase, reason, onRetry: runAuth })
  );
}

const GlobalStyle = React.memo(function GlobalStyle() {
  return React.createElement("style", null, `
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap');
    *, *::before, *::after { box-sizing: border-box; }
    html, body, #root { margin: 0; width: 100%; min-height: 100%; }
    /* preserve the top spacer set in index.html so content starts below it */
    body { background: #05070a; color: #d7e2ea; font-family: 'Inter', sans-serif; }
    button, input, textarea { font-family: inherit; }

    .gate { min-height: 100vh; width: 100%; display: flex; align-items: center; justify-content: center;
      background: radial-gradient(ellipse 80% 50% at 50% -10%, rgba(56,189,248,0.15), transparent), #0a0f1f; padding: 20px; }
    .gate-card { width: 100%; max-width: 440px; border: 1px solid rgba(56,189,248,0.16); border-radius: 10px;
      background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0)); padding: 24px; }
    .gate-brand { display: flex; align-items: center; gap: 8px; font-family: 'JetBrains Mono', monospace;
      font-size: 12px; letter-spacing: 0.14em; text-transform: uppercase; color: #38bdf8; margin-bottom: 18px;
      padding-bottom: 14px; border-bottom: 1px dashed rgba(56,189,248,0.16); }
    .gate-sticker { width: 220px; height: 220px; margin: 0 auto 18px; display: flex; align-items: center; justify-content: center; }
    .header-sticker { margin-right: 12px; }
    .header-sticker .gate-sticker { width: 68px; height: 68px; margin: 0; }
    .gate-log { font-family: 'JetBrains Mono', monospace; font-size: 13px; }
    .log-line { color: #9fb4bd; padding: 3px 0; display: flex; gap: 8px; }
    .log-line::before { content: '>'; color: #38bdf8; }
    .log-line.accent { color: #38bdf8; align-items: center; }
    .gate-status { display: flex; align-items: center; gap: 10px; font-family: 'JetBrains Mono', monospace; font-size: 15px; }
    .gate-status.denied { color: #fb7185; }
    .gate-detail { color: #7d97a3; font-size: 13px; line-height: 1.6; margin: 12px 0 18px; }
    .gate-retry { display: inline-flex; align-items: center; gap: 8px; background: transparent;
      border: 1px solid rgba(56,189,248,0.3); color: #7dd3fc; font-family: 'JetBrains Mono', monospace;
      font-size: 12px; padding: 9px 16px; border-radius: 6px; cursor: pointer; letter-spacing: 0.04em; }
    .gate-retry:hover { background: rgba(56,189,248,0.08); border-color: rgba(56,189,248,0.55); }
    .spin { animation: spin 1s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }

    .dash-header { border-bottom: 1px solid rgba(56,189,248,0.14); background: rgba(255,255,255,0.015); }
    .dash-header-inner { max-width: 1100px; margin: 0 auto; padding: calc(18px + env(safe-area-inset-top, 0px)) 24px 18px; display: flex; align-items: center; justify-content: space-between; }
    /* Ensure top content is pushed down for Telegram Mini App notch/safe area */
    .dash-header { padding-top: env(safe-area-inset-top, 0px); }
    .dash-title { display: flex; align-items: center; gap: 10px; font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 22px; color: #38bdf8; }
    .logout-btn { display: inline-flex; align-items: center; gap: 4px; background: transparent; border: 1px solid rgba(56,189,248,0.25); color: #7dd3fc; font-size: 11px; padding: 6px 10px; border-radius: 6px; cursor: pointer; min-width: 60px; justify-content: flex-end; }
    .logout-btn:hover { background: rgba(56,189,248,0.08); }
    .logout-btn .mute-label { display: inline-block; width: auto; text-align: right; margin-left: 4px; }
    .dash-container { max-width: 1100px; margin: 0 auto; padding: 28px 24px 64px; }
    .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; margin-bottom: 28px; }
    .stat-card { border: 1px solid rgba(56,189,248,0.14); border-radius: 10px; background: rgba(255,255,255,0.015); padding: 18px; }
    .stat-value { font-family: 'JetBrains Mono', monospace; font-size: 28px; color: #38bdf8; font-weight: 700; }
    .stat-label { font-size: 12px; color: #7d97a3; margin-top: 4px; }
    .panel { border: 1px solid rgba(56,189,248,0.14); border-radius: 10px; background: rgba(255,255,255,0.012); padding: 22px 24px; margin-bottom: 22px; }
    .panel-head { display: flex; align-items: center; justify-content: space-between; padding-bottom: 14px; margin-bottom: 16px; border-bottom: 1px dashed rgba(56,189,248,0.14); }
    .panel-head h2 { margin: 0; font-size: 15px; font-weight: 600; color: #e8f1fb; display: flex; align-items: center; gap: 8px; }
    .hint { color: #7d97a3; font-size: 13px; margin: 0 0 14px; }
    .muted { color: #7d97a3; }
    .empty { color: #5f7982; font-size: 13px; padding: 14px 0; font-family: 'JetBrains Mono', monospace; }
    .badge { font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 6px; letter-spacing: 0.02em; white-space: nowrap; }
    .badge.input { background: transparent; border: 1px solid #7dd3fc; color: #7dd3fc; }
    .badge.output { background: transparent; border: 1px solid #0ea5e9; color: #0ea5e9; }
    .stat-today { font-size: 11px; color: #34d399; margin-top: 2px; }
    .stat-value.arena-on { color: #34d399; }
    .stat-value.arena-off { color: #fb7185; }
    .filter-label { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; min-width: 30px; }
    .in-label { color: #7dd3fc; }
    .out-label { color: #0ea5e9; }
    .badge.good { background: transparent; border: 1px solid #6ee7b7; color: #6ee7b7; }
    .badge.bad { background: rgba(251,113,133,0.12); color: #fb7185; }
    .badge.neutral { background: rgba(56,189,248,0.1); color: #7dd3fc; }
    .token-row { display: flex; align-items: center; gap: 10px; background: rgba(255,255,255,0.02); border-radius: 6px; padding: 10px 12px; margin-bottom: 8px; }
    .token-row code { flex: 1; font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #b7c6cc; word-break: break-all; }
    .code-block { display: block; background: rgba(255,255,255,0.02); padding: 12px 14px; border-radius: 6px; font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #b7c6cc; word-break: break-all; }
    .icon-btn { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; border-radius: 6px; border: 1px solid transparent; background: transparent; cursor: pointer; color: #7d97a3; }
    .icon-btn.danger:hover { background: rgba(251,113,133,0.1); color: #fb7185; }
    .form-block { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
    .form-block label { font-size: 12px; color: #8ba3ad; }
    .form-block input, .form-block textarea { background: rgba(255,255,255,0.02); border: 1px solid rgba(56,189,248,0.18); border-radius: 6px; padding: 10px 12px; color: #e8f1fb; font-size: 13px; width: 100%; }
    .form-block textarea { min-height: 72px; resize: vertical; font-family: 'JetBrains Mono', monospace; }
    .form-block input:focus, .form-block textarea:focus { outline: none; border-color: #38bdf8; }
    .form-row { display: grid; grid-template-columns: 3fr 1fr auto; gap: 12px; align-items: end; margin-top: 18px; }
    @media (max-width: 640px) { .form-row { grid-template-columns: 1fr; } }
    .btn-primary { display: inline-flex; align-items: center; gap: 8px; justify-content: center; background: rgba(56,189,248,0.12); border: 1px solid rgba(56,189,248,0.4); color: #7dd3fc; font-size: 13px; font-weight: 600; padding: 10px 16px; border-radius: 6px; cursor: pointer; white-space: nowrap; }
    .btn-primary:hover { background: rgba(56,189,248,0.2); }
    .table-wrap { overflow-x: auto; }
    /* make the first two columns wider so Name and Key are readable (Name matches Key) */
    th:nth-child(1), td:nth-child(1) { width: 50%; }
    th:nth-child(2), td:nth-child(2) { width: 50%; }
    table { width: 100%; border-collapse: collapse; }
    th { text-align: left; font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; color: #5f7982; padding: 10px 12px; border-bottom: 1px solid rgba(56,189,248,0.14); }
    td { padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.03); font-size: 13px; }
    tr:hover td { background: rgba(255,255,255,0.012); }
    td code { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #7dd3fc; }
    /* key column: prevent awkward wrapping, show ellipsis and allow click-to-copy */
    .key-code { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; cursor: pointer; user-select: all; -webkit-user-select: all; transition: color 0.2s, background 0.2s; }
    .key-code.copied { color: #34d399; background: rgba(52,211,153,0.1); padding: 2px 6px; border-radius: 4px; display: inline-block; }
    .charts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
    @media (max-width: 720px) { .charts-grid { grid-template-columns: 1fr; } }
    .chart-title { text-align: center; font-size: 12px; color: #7d97a3; margin-bottom: 12px; }
    .donut-wrap { display: flex; align-items: center; gap: 20px; justify-content: center; flex-wrap: wrap; }
    .donut { width: 140px; height: 140px; border-radius: 50%; display: flex; align-items: center; justify-content: center; position: relative; }
    .donut-hole { width: 84px; height: 84px; border-radius: 50%; background: #05070a; display: flex; flex-direction: column; align-items: center; justify-content: center; }
    .donut-hole span { font-family: 'JetBrains Mono', monospace; font-size: 18px; color: #e8f1fb; font-weight: 700; }
    .donut-hole small { font-size: 10px; color: #7d97a3; }
    .legend { display: flex; flex-direction: column; gap: 6px; }
    .legend-row { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #b7c6cc; }
    .legend-row small { color: #5f7982; margin-left: auto; padding-left: 12px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
    .bars { display: flex; flex-direction: column; gap: 10px; padding: 6px 0; }
    .bar-row { display: grid; grid-template-columns: 110px 1fr 34px; gap: 10px; align-items: center; }
    .bar-label { font-size: 11px; color: #7d97a3; font-family: 'JetBrains Mono', monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .bar-track { height: 10px; border-radius: 5px; background: rgba(255,255,255,0.04); overflow: hidden; }
    .bar-fill { height: 100%; border-radius: 5px; }
    .bar-value { font-size: 12px; color: #7dd3fc; text-align: right; }
    .model-filters { display: flex; gap: 10px; margin: 12px 0 16px; align-items: center; flex-wrap: wrap; }
    .filter-group { display: flex; gap: 8px; }
    .filter-buttons { display: flex; align-items: center; gap: 6px; }
    .filter-buttons label { font-size: 12px; font-weight: 600; color: #38bdf8; text-transform: uppercase; letter-spacing: 0.05em; min-width: 30px; }
    .filter-select { flex: 1; background: rgba(255,255,255,0.02); border: 1px solid rgba(56,189,248,0.18); border-radius: 6px; padding: 9px 11px; color: #e8f1fb; font-size: 13px; min-width: 120px; }
    .filter-select.in { border-color: rgba(56,189,248,0.3); }
    .filter-select.out { border-color: rgba(29,78,216,0.4); }
    .filter-select:focus { outline: none; border-color: #38bdf8; }
    .model-filters input, .model-filters select { background: rgba(255,255,255,0.02); border: 1px solid rgba(56,189,248,0.18); border-radius: 6px; padding: 9px 11px; color: #e8f1fb; }
    .capability-list { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 9px; }
    .model-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
    .model-card { border: 1px solid rgba(56,189,248,0.14); border-radius: 8px; padding: 14px; background: rgba(255,255,255,0.012); }
    .model-card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
    .model-name { font-family: 'JetBrains Mono', monospace; font-size: 13px; color: #e8f1fb; }
    @media (prefers-reduced-motion: reduce) { .spin { animation: none; } }

    /* === Animations === */
    @keyframes fadeInUp {
      from { opacity: 0; transform: translateY(18px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }
    @keyframes slideInLeft {
      from { opacity: 0; transform: translateX(-14px); }
      to { opacity: 1; transform: translateX(0); }
    }
    @keyframes pulseGlow {
      0%, 100% { box-shadow: 0 0 0 0 rgba(251,113,133,0); }
      50% { box-shadow: 0 0 18px 2px rgba(251,113,133,0.25); }
    }
    @keyframes scanLine {
      0% { top: -2px; }
      100% { top: 100%; }
    }
    @keyframes typewriter {
      from { width: 0; }
      to { width: 100%; }
    }
    .gate-card { animation: fadeInUp 0.5s ease-out; }
    .gate-status.denied { animation: pulseGlow 2s ease-in-out infinite; }
    .gate-sticker { animation: fadeIn 0.6s ease-out; }
    .log-line { animation: slideInLeft 0.25s ease-out both; }
    .log-line:nth-child(1) { animation-delay: 0s; }
    .log-line:nth-child(2) { animation-delay: 0.3s; }
    .log-line:nth-child(3) { animation-delay: 0.6s; }
    .log-line:nth-child(4) { animation-delay: 0.9s; }
    .log-line:nth-child(5) { animation-delay: 1.2s; }
    .stat-card { animation: fadeInUp 0.4s ease-out both; }
    .stat-card:nth-child(1) { animation-delay: 0.05s; }
    .stat-card:nth-child(2) { animation-delay: 0.1s; }
    .stat-card:nth-child(3) { animation-delay: 0.15s; }
    .panel { animation: fadeInUp 0.4s ease-out both; }
    .panel:nth-child(1) { animation-delay: 0.1s; }
    .panel:nth-child(2) { animation-delay: 0.15s; }
    .panel:nth-child(3) { animation-delay: 0.2s; }
    .panel:nth-child(4) { animation-delay: 0.25s; }
    .panel:nth-child(5) { animation-delay: 0.3s; }
    .model-card { transition: transform 0.2s ease, border-color 0.2s ease; }
    .model-card:hover { transform: translateY(-2px); border-color: rgba(56,189,248,0.35); }
    .btn-primary { transition: background 0.2s ease, transform 0.15s ease; }
    .btn-primary:active { transform: scale(0.97); }
    .token-row { animation: fadeIn 0.3s ease-out both; }
    .badge.good { animation: fadeIn 0.5s ease-out; }
    .badge.bad { animation: pulseGlow 2s ease-in-out infinite; }
  `);
});

// Ensure global exposure for wrapper HTML that expects a top-level App function
if (typeof window !== 'undefined' && typeof App === 'function') {
  try { window.App = App; } catch (e) { /* ignore */ }
}