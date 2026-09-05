#!/usr/bin/env python3
"""Direct Mode: Image Generation Test.
Picks any model with outputCapabilities.image and sends a fixed prompt.
"""
import json, asyncio, httpx, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _dm_helpers import get_api_key, get_models, media_path, pick_model, post_chat, handle_status
API_BASE = "http://127.0.0.1:6767/api/v1"
PROMPT = "Draw an apple"

async def test():
    api_key = get_api_key()
    if not api_key:
        print("FAIL: No API keys configured")
        return False

    models = get_models()
    pn, mid = pick_model(
        models, require_in=None, require_out=['image'], exclude_out=None
    )
    if not pn:
        print("SKIP: no model with caps req_in=None req_out=['image'] excl=None")
        return True
    model = pn
    print(f"Model: {model}")

    status, body = await post_chat(API_BASE, api_key, model,
                              [{"role": "user", "content": PROMPT}], timeout=300)
    if status == "ok":
        content = body["choices"][0]["message"]["content"]
        has_image_md = ("![" in content) or ("data:image" in content) or ("http" in content and ("image" in content.lower() or "png" in content.lower()))
        print(f"OK ({len(content)} chars, image_md={has_image_md}): {content[:250]}")
        return True
    return handle_status(status, body)

if __name__ == "__main__":
    success = asyncio.run(test())
    sys.exit(0 if success else 1)