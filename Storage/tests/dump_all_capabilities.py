#!/usr/bin/env python3
"""
Dump all LMArena capability responses through the bridge API.
Tests each capability (text, image, video, web, search, vision) with a
capability-appropriate model, retries on rate-limit/5xx with backoff,
and saves each raw response to Storage/dumps/ for schema analysis.

Usage: python3 dump_all_capabilities.py [--max-attempts N]
"""

import asyncio, json, os, sys, time, datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # /home/forget/LMArena

BRIDGE = "http://127.0.0.1:6767"
DUMPS = os.path.join(REPO_ROOT, "Storage", "dumps")
os.makedirs(DUMPS, exist_ok=True)

def load_config():
    cfg_path = os.path.join(REPO_ROOT, "WEB", "data", "config.json")
    with open(cfg_path) as f:
        return json.load(f)

def get_api_key():
    cfg = load_config()
    keys = cfg.get("api_keys", [])
    if not keys:
        raise RuntimeError("No API keys in config")
    return keys[0]["key"] if isinstance(keys[0], dict) else str(keys[0])

def pick_model(models, *, require_in=None, require_out=None, exclude_out=None):
    """Pick a model matching required input/output capabilities (provider-aware)."""
    best = None
    for m in models:
        caps = m.get("capabilities", {})
        ic = caps.get("inputCapabilities", {})
        oc = caps.get("outputCapabilities", {})
        ok = True
        if require_in:
            for k in (require_in if isinstance(require_in, (list, tuple)) else [require_in]):
                if not ic.get(k):
                    ok = False
                    break
        if not ok:
            continue
        if require_out:
            for k in (require_out if isinstance(require_out, (list, tuple)) else [require_out]):
                if not oc.get(k):
                    ok = False
                    break
        if not ok:
            continue
        if exclude_out:
            for k in (exclude_out if isinstance(exclude_out, (list, tuple)) else [exclude_out]):
                if oc.get(k):
                    ok = False
                    break
        if not ok:
            continue
        # Prefer models with provider (non-stealth)
        name = m.get("name") or m.get("publicName")
        best = (m.get("rank", 999), name, m)
        break
    return best

async def dump_one(name, api_key, model, messages, max_attempts=30):
    import httpx
    out_path = os.path.join(DUMPS, f"{name}.json")
    url = f"{BRIDGE}/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": model, "messages": messages, "stream": False}
    start = time.time()
    async with httpx.AsyncClient(timeout=120) as c:
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await c.post(url, json=body, headers=headers)
                text = resp.text
                # Detect success: choices present (or error with detail)
                try:
                    data = json.loads(text)
                    if "choices" in data and data["choices"]:
                        with open(out_path, "w") as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                        elapsed = time.time() - start
                        content = data["choices"][0].get("message", {}).get("content", "")[:80]
                        print(f"  ✅ {name} ({model}): OK in {elapsed:.0f}s | content={content!r}")
                        return True
                    if isinstance(data, dict) and data.get("error"):
                        msg = str(data["error"].get("message", ""))
                    else:
                        msg = text[:120]
                except Exception:
                    msg = text[:120]
                # Rate limit / upstream down — retry with backoff
                if resp.status_code in (429, 503, 502) or "Too Many Requests" in msg or "Max retries" in msg or "reCAPTCHA" in msg:
                    wait = min(5 * attempt, 60)
                    print(f"  ⏳ {name} attempt {attempt}: {resp.status_code} {msg[:60]} — retry in {wait}s")
                    await asyncio.sleep(wait)
                    continue
                # Hard failure
                print(f"  ❌ {name} ({model}): {resp.status_code} {msg[:100]}")
                return False
            except httpx.TimeoutException:
                print(f"  ⏳ {name} attempt {attempt}: timeout — retry in 15s")
                await asyncio.sleep(15)
                continue
    print(f"  ❌ {name}: max attempts reached")
    return False

async def main():
    max_attempts = int(sys.argv[sys.argv.index("--max-attempts") + 1]) if "--max-attempts" in sys.argv else 30
    cfg = load_config()
    models = cfg.get("models", [])
    api_key = get_api_key()

    print(f"📦 Models in config: {len(models)}")
    print(f"📁 Dumps dir: {DUMPS}")
    print(f"⏱️  Max attempts per test: {max_attempts}\n")

    tests = {
        "text":  {"require_out": "text", "exclude_out": ["image", "video"], "messages": [{"role": "user", "content": "Say hello in three words."}]},
        "image": {"require_out": "image", "messages": [{"role": "user", "content": "Generate a simple red circle on white background."}]},
        "video": {"require_out": "video", "messages": [{"role": "user", "content": "Generate a short video of a bouncing ball."}]},
        "web":   {"require_out": "web", "exclude_out": ["image"], "messages": [{"role": "user", "content": "Build a simple website with a heading and a button."}]},
        "search":{"require_out": "search", "exclude_out": ["image"], "messages": [{"role": "user", "content": "What is the capital of France? Include sources."}]},
        "vision": {"require_in": "image", "require_out": "text", "exclude_out": ["image"], "messages": [{"role": "user", "content": "Describe what you see in this image."}]},
    }

    results = {}
    for name, spec in tests.items():
        picked = pick_model(
            models,
            require_in=spec.get("require_in"),
            require_out=spec.get("require_out"),
            exclude_out=spec.get("exclude_out"),
        )
        if picked is None:
            print(f"  ⚠️ {name}: no model found for capabilities {spec}")
            results[name] = "no-model"
            continue
        _, model, _ = picked
        print(f"--- {name} → model: {model} ---")
        results[name] = await dump_one(name, api_key, model, spec["messages"], max_attempts)

    print("\n=== SUMMARY ===")
    for name, r in results.items():
        print(f"  {name}: {'✅ dumped' if r is True else '❌ failed' if r is False else r}")

if __name__ == "__main__":
    asyncio.run(main())
