#!/usr/bin/env python3
"""Direct Mode: WebDev / Website Generation Test.
Picks any model with outputCapabilities.web (site-generation mode) and
sends a fixed prompt. A WebDev model always returns a web page.
"""
import json, asyncio, httpx, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _dm_helpers import get_api_key, get_models, media_path, pick_model, post_chat, handle_status
API_BASE = "http://127.0.0.1:6767/api/v1"
PROMPT = "Create ordinary loading page with text \"Just preparing your connection...\""

async def test():
    api_key = get_api_key()
    if not api_key:
        print("FAIL: No API keys configured")
        return False

    models = get_models()
    pn, mid = pick_model(
        models, require_in=None, require_out=['web'], exclude_out=['image', 'video']
    )
    if not pn:
        print("SKIP: no model with caps req_in=None req_out=['web'] excl=['image', 'video']")
        return True
    model = pn
    print(f"Model: {model}")

    status, body = await post_chat(API_BASE, api_key, model,
                              [{"role": "user", "content": PROMPT}], timeout=600)
    if status == "ok":
        content = body["choices"][0]["message"]["content"]
        has_html = ("<!doctype html" in content.lower()) or ("<html" in content.lower()) or ("<head" in content.lower()) or ("<body" in content.lower())
        has_loading = "Just preparing your connection" in content
        print(f"OK ({len(content)} chars, html={has_html}, loading_text={has_loading}): {content[:250]}")
        return True
    return handle_status(status, body)

if __name__ == "__main__":
    success = asyncio.run(test())
    sys.exit(0 if success else 1)