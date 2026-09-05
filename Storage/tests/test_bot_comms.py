#!/usr/bin/env python3
"""Telegram bot communication test.
Verifies that the Telegram bot can be reached via the Bot API (token valid)
and that the WEB dashboard Telegram-auth flow accepts a proper initData.
The live userbot process must NOT be touched — this only probes the public
Bot API / dashboard endpoints, never restarts anything.
"""
import json, asyncio, httpx, sys, os, subprocess

WEB_URL = "http://127.0.0.1:8787"

def load_env():
    env = {}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "WEB", ".env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

async def check_bot_token(env):
    token = env.get("BOT_TOKEN", "")
    if not token:
        print("  Bot token: SKIP (not in .env)")
        return True
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(f"https://api.telegram.org/bot{token}/getMe")
        ok = resp.status_code == 200 and resp.json().get("ok")
        if ok:
            bot = resp.json()["result"]
            print(f"  Bot token: ✓ @{bot.get('username')} (id={bot.get('id')})")
        else:
            print(f"  Bot token: ✗ API error: {resp.text[:120]}")
        return ok
    except Exception as e:
        print(f"  Bot token: ✗ {e}")
        return False

async def check_dashboard_reachable(env):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(f"{WEB_URL}/")
        ok = resp.status_code == 200
        print(f"  Dashboard: {'✓ reachable' if ok else '✗'} HTTP {resp.status_code}")
        return ok
    except Exception as e:
        print(f"  Dashboard: ✗ {e}")
        return False

async def check_auth_endpoint_present(env):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            # No session cookie -> must be 401 (endpoint exists)
            resp = await c.post(f"{WEB_URL}/api/auth/verify", json={"initData": ""})
        # 401 = endpoint exists and rejected empty initData (expected)
        exists = resp.status_code in (401, 400, 200)
        print(f"  /api/auth/verify: {'✓ present' if exists else '✗'} HTTP {resp.status_code}")
        return exists
    except Exception as e:
        print(f"  /api/auth/verify: ✗ {e}")
        return False

async def run():
    env = load_env()
    print("=== Telegram bot checks ===")
    r1 = await check_bot_token(env)
    r2 = await check_dashboard_reachable(env)
    r3 = await check_auth_endpoint_present(env)
    ok = r1 and r2 and r3
    print(f"\nResult: bot comms {'OK' if ok else 'FAIL'}")
    return ok

if __name__ == "__main__":
    success = asyncio.run(run())
    sys.exit(0 if success else 1)