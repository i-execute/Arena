#!/usr/bin/env python3
"""Service health & daemon tests — verifies that all systemd user services
are running, web endpoints are reachable, and the Arena site is accessible.
"""
import json, asyncio, httpx, sys, os, subprocess, time

# lmarena-bot (legacy log-forwarder) shares BOT_TOKEN with lmarena-bot2 — running both
# makes Telegram answer getUpdates with "Conflict: terminated by other getUpdates
# request", so only bot2 is expected to be active.
SERVICES = ["lmarena-web", "lmarena-bridge", "lmarena-web-tunnel", "lmarena-api-tunnel", "lmarena-bot2"]
BRIDGE_URL = "http://127.0.0.1:6767"
WEB_URL = "http://127.0.0.1:8787"
ARENA_URL = "https://lmarena.ai"

def check_service(name):
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", name],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
        )
        active = r.stdout.strip() == "active"
        print(f"  {name}: {'✓ active' if active else '✗ ' + r.stdout.strip()}")
        return active
    except Exception as e:
        print(f"  {name}: ✗ error: {e}")
        return False

async def check_http(url, label, expected_status=200, timeout=10):
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
            resp = await c.get(url)
            ok = resp.status_code == expected_status
            print(f"  {label}: {'✓' if ok else '✗'} HTTP {resp.status_code}")
            return ok
    except Exception as e:
        print(f"  {label}: ✗ error: {e}")
        return False

async def check_bridge_api():
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(f"{BRIDGE_URL}/api/v1/health")
            ok = resp.status_code == 200
            data = resp.json()
            models_loaded = data.get("checks", {}).get("models_loaded", False)
            print(f"  Bridge API: {'✓' if ok else '✗'} HTTP {resp.status_code}, models={models_loaded}")
            return ok and models_loaded
    except Exception as e:
        print(f"  Bridge API: ✗ {e}")
        return False

async def check_tunnels():
    """Check if cloudflare tunnels are giving us URLs."""
    for svc in ["lmarena-web-tunnel", "lmarena-api-tunnel"]:
        try:
            r = subprocess.run(
                ["journalctl", "--user", "-u", svc, "-n", "200", "--no-pager"],
                capture_output=True, text=True, timeout=5,
                env={**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
            )
            has_url = "trycloudflare.com" in r.stdout
            print(f"  {svc} tunnel: {'✓ url found' if has_url else '✗ no url'}")
        except Exception as e:
            print(f"  {svc} tunnel: ✗ {e}")

async def run():
    print("=== Service daemon health ===")
    results = {}
    for svc in SERVICES:
        results[svc] = check_service(svc)

    print("\n=== HTTP endpoint checks ===")
    results["bridge_api"] = await check_bridge_api()
    results["web_dashboard"] = await check_http(WEB_URL, "WEB Dashboard")
    results["arena_site"] = await check_http(ARENA_URL, "Arena (lmarena.ai)", timeout=8)

    print("\n=== Tunnel checks ===")
    await check_tunnels()

    passed = sum(1 for v in results.values() if v is True)
    total = sum(1 for v in results.values() if v is not None)
    print(f"\n{'='*40}")
    print(f"Result: {passed}/{total} checks passed")
    return passed == total

if __name__ == "__main__":
    success = asyncio.run(run())
    sys.exit(0 if success else 1)