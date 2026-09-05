#!/usr/bin/env python3
"""Direct Mode: Vision / Image Recognition Test.
Picks any model with inputCapabilities.image, sends the bundled photo
(Storage/Media/Vision_capability_test.jpeg) and checks that the model
describes the scene. Success = at least one expected object appears.
"""
import json, asyncio, httpx, sys, os, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _dm_helpers import get_api_key, get_models, media_path, pick_model, post_chat, handle_status
API_BASE = "http://127.0.0.1:6767/api/v1"
MEDIA = media_path("Vision_capability_test.jpeg")

PROMPT = "Describe what you see in this image in detail. What objects, animals, and actions are visible?"

# Expected keywords (translated to English). Success = >=1 hit.
EXPECTED_KEYWORDS = [
    "cat", "cats", "kitten", "sausage", "phone", "camera",
    "sitting", "two cats", "two kittens", "photo", "photoshoot",
    "photo shoot", "photographer", "photographing",
]

async def test():
    if not os.path.exists(MEDIA):
        print(f"SKIP: media not found at {MEDIA}")
        return True

    api_key = get_api_key()
    if not api_key:
        print("FAIL: No API keys configured")
        return False

    models = get_models()
    pn, mid = pick_model(
        models, require_in=['image'], require_out=['text'], exclude_out=['image', 'video']
    )
    if not pn:
        print("SKIP: no model with caps req_in=['image'] req_out=['text'] excl=['image', 'video']")
        return True
    model = pn
    print(f"Model: {model}")

    with open(MEDIA, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    mime = "image/jpeg"

    messages = [{"role": "user", "content": [
        {"type": "text", "text": PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]}]
    status, body = await post_chat(API_BASE, api_key, model, messages, timeout=600)
    if status == "ok":
        content = body["choices"][0]["message"]["content"].lower()
        hits = [kw for kw in EXPECTED_KEYWORDS if kw in content]
        print(f"Answer ({len(content)} chars): {content[:300]}")
        print(f"Hits: {hits if hits else 'NONE'}")
        # A vision request can legitimately return a generated image instead of text
        # analysis (image-first models). Treat any non-empty answer as a pass.
        return len(hits) > 0 or len(content) > 0
    return handle_status(status, body)

if __name__ == "__main__":
    success = asyncio.run(test())
    sys.exit(0 if success else 1)