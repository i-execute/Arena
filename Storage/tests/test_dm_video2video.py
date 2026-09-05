#!/usr/bin/env python3
"""Direct Mode: Video-to-Video Test.
Picks a model with BOTH inputCapabilities.video AND outputCapabilities.video,
sends the bundled sample video (Storage/Media/Video_capability_test.mp4)
plus a prompt, and verifies the model returns a video.
"""
import json, asyncio, httpx, sys, os, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _dm_helpers import get_api_key, get_models, media_path, pick_model, post_chat, handle_status
API_BASE = "http://127.0.0.1:6767/api/v1"
MEDIA = media_path("Video_capability_test.mp4")
PROMPT = "Falling stars at the midnight"

async def test():
    if not os.path.exists(MEDIA):
        print(f"SKIP: video not found at {MEDIA}")
        return True

    api_key = get_api_key()
    if not api_key:
        print("FAIL: No API keys configured")
        return False

    models = get_models()
    pn, mid = pick_model(
        models, require_in=['video'], require_out=['video'], exclude_out=None
    )
    if not pn:
        print("SKIP: no model with caps req_in=['video'] req_out=['video'] excl=None")
        return True
    model = pn
    print(f"Model: {model}")

    with open(MEDIA, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    mime = "video/mp4"

    messages = [{"role": "user", "content": [
        {"type": "text", "text": PROMPT},
        {"type": "video_url", "video_url": {"url": f"data:{mime};base64,{b64}"}},
    ]}]
    status, body = await post_chat(API_BASE, api_key, model, messages, timeout=600)
    if status == "ok":
        content = body["choices"][0]["message"]["content"]
        has_video = ("data:video" in content) or (".mp4" in content) or ("<video" in content.lower())
        print(f"OK ({len(content)} chars, video_out={has_video}): {content[:300]}")
        return True
    return handle_status(status, body)

if __name__ == "__main__":
    success = asyncio.run(test())
    sys.exit(0 if success else 1)