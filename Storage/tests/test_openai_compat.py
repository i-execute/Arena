#!/usr/bin/env python3
"""OpenAI-compatibility test suite for the LMArena bridge.

Tests that /api/v1/chat/completions responses match the OpenAI schema:
  - top-level: id, object, created, model
  - choices[0]: index, message{role,content}, finish_reason
  - usage: prompt_tokens, completion_tokens, total_tokens
  - conversation_id present
Also validates stream mode returns SSE data chunks with delta content.
"""
import json
import sys
import time
import urllib.request
import urllib.error

BRIDGE = "http://127.0.0.1:6767/api/v1/chat/completions"
CONFIG = "/home/forget/LMArena/WEB/data/config.json"

with open(CONFIG) as f:
    cfg = json.load(f)
KEY = cfg["api_keys"][0]["key"]
MODEL = sys.argv[1] if len(sys.argv) > 1 else "gpt-5.5-instant"
PROMPT = sys.argv[2] if len(sys.argv) > 2 else "What is the capital of France? Answer in one word."


def post(body, timeout=180):
    req = urllib.request.Request(
        BRIDGE,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"},
    )
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, raw, time.time() - start
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), time.time() - start
    except Exception as e:
        return 0, str(e), time.time() - start


def check_non_stream():
    status, raw, elapsed = post({
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": False,
    })
    print(f"[non-stream] HTTP {status}, {elapsed:.1f}s")
    if status != 200:
        print(f"  FAIL: {raw[:300]}")
        return False

    try:
        d = json.loads(raw)
    except Exception as e:
        print(f"  FAIL: invalid JSON: {e}")
        return False

    ok = True
    checks = [
        ("id", "id" in d and str(d["id"]).startswith("chatcmpl-")),
        ("object", d.get("object") == "chat.completion"),
        ("created", isinstance(d.get("created"), int)),
        ("model", "model" in d),
        ("choices", isinstance(d.get("choices"), list) and len(d["choices"]) > 0),
        ("message", "message" in d["choices"][0] if d.get("choices") else False),
        ("content", bool(d["choices"][0]["message"].get("content")) if d.get("choices") else False),
        ("finish_reason", d["choices"][0].get("finish_reason") in ("stop", "length")),
        ("usage", all(k in d.get("usage", {}) for k in ("prompt_tokens", "completion_tokens", "total_tokens"))),
        ("conversation_id", "conversation_id" in d),
    ]
    for name, passed in checks:
        print(f"  {'✅' if passed else '❌'} {name}")
        ok = ok and passed
    return ok


def check_stream():
    status, raw, elapsed = post({
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": True,
    }, timeout=240)
    print(f"[stream] HTTP {status}, {elapsed:.1f}s")
    if status != 200:
        print(f"  FAIL: {raw[:300]}")
        return False

    data_chunks = [l for l in raw.split("\n") if l.startswith("data:")]
    # Exclude the final "[DONE]"
    real = [c for c in data_chunks if "DONE" not in c]
    print(f"  chunks: {len(real)} (total {len(data_chunks)})")
    if not real:
        print("  ❌ no data chunks (keep-alive only)")
        return False
    try:
        first = json.loads(real[0][6:])
        has_delta = "choices" in first and "delta" in first["choices"][0]
        print(f"  {'✅' if has_delta else '❌'} delta content in first chunk")
        return has_delta
    except Exception as e:
        print(f"  ❌ bad chunk JSON: {e}")
        return False


if __name__ == "__main__":
    ns = check_non_stream()
    print()
    st = check_stream()
    print()
    print("RESULT:", "PASS" if (ns and st) else "PARTIAL" if (ns or st) else "FAIL")
