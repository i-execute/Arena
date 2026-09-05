#!/usr/bin/env python3
"""Run all Direct-Mode capability tests in one pass.
Each test picks the first available model for its capability; SKIPs
cleanly when no model has the capability (so it never hard-fails the suite).
"""
import sys, os, subprocess, asyncio

TESTS = [
    "test_dm_text.py",
    "test_dm_image.py",
    "test_dm_video.py",
    "test_dm_web.py",
    "test_dm_vision.py",
    "test_dm_video2video.py",
    "test_reasoning_format.py",
]

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    results = {}
    for t in TESTS:
        path = os.path.join(here, t)
        print(f"\n{'='*50}\nRUNNING: {t}\n{'='*50}")
        r = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=900)
        print(r.stdout)
        if r.stderr:
            print("STDERR:", r.stderr[-500:])
        # SKIP = exit 0 but test printed SKIP; PASS = exit 0; FAIL = exit 1
        results[t] = "SKIP" if ("SKIP" in r.stdout and r.returncode == 0) else ("PASS" if r.returncode == 0 else "FAIL")

    print(f"\n{'='*50}\nSUMMARY\n{'='*50}")
    for t, status in results.items():
        print(f"  {status:5s}  {t}")
    fails = [t for t, s in results.items() if s == "FAIL"]
    print(f"\n{len(results)-len(fails)}/{len(results)} passed")
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()