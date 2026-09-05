"""
Comprehensive API capability tests - simplified version
Tests all input/output combinations with stream=true/false
Validates OpenAI API compatibility
"""
import json
import asyncio
import httpx
import base64
import time
from pathlib import Path

# Configuration
API_KEY = "sk-lmab-357ff040-705d-4f0f-8fce-687f08e9a238"
API_BASE = "http://localhost:6767/api/v1"
MEDIA_PATH = Path("/home/forget/Arena/Storage/Media")
RESULTS_PATH = Path("/home/forget/QwertyWork")

# Test models (use real model IDs)
MODELS = {
    "text": "gpt-5.4-mini-high",
    "image": "flux-2-pro",
    "video": "sora-1",
    "web": "cursor-composer",
    "vision": "gpt-5.4-large-vision"
}

TIMEOUTS = {
    "text": 180,
    "image": 240,
    "video": 300,
    "web": 120,
    "vision": 60,
}

PROMPTS = {
    "text": "The cat sat on the mat. What i write right now ?",
    "image": "Draw an apple",
    "video": "Falling stars at the midnight",
    "web": "Create ordinary loading page with text \"Just preparing your connection...\"",
    "vision": "What happened on this image? Describe all objects, animals, people, and actions using comma-separated English words (cat, sausage, phone, camera, etc). Be detailed.",
}

# Vision keywords for validation
VISION_KEYWORDS = [
    "cat", "kitten", "feline", "tom cat",
    "sausage", "wurst",
    "phone", "mobile", "telephone", "device",
    "camera", "lens", "photo", "photograph",
    "sit", "sitting", "sitting cat",
    "two", "couple", "pair",
    "female", "male",
    "photo", "photograph", "picture",
    "photoshoot", "photo session",
    "photographer",
    "photograph", "photographing"
]

class APITest:
    def __init__(self):
        self.results = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "api_base": API_BASE,
            "tests": {}
        }
    
    def validate_openai_response(self, response, test_id):
        """Validate OpenAI compatibility"""
        errors = []
        warnings = []
        
        if "choices" not in response:
            errors.append("Missing 'choices'")
        elif not response["choices"]:
            errors.append("Empty 'choices'")
        else:
            choice = response["choices"][0]
            if "message" not in choice:
                errors.append("Missing 'message'")
            elif "content" not in choice["message"]:
                errors.append("Missing 'content'")
        
        if "model" not in response:
            warnings.append("Missing 'model'")
        if "usage" not in response:
            warnings.append("Missing 'usage'")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
    
    async def test(self, test_id, capability, model, stream, attach_media=False):
        """Run single test"""
        print(f"\n{'='*60}")
        print(f"TEST: {test_id}")
        print(f"Model: {model} | Capability: {capability} | Stream: {stream} | Media: {attach_media}")
        print(f"{'='*60}")
        
        result = {
            "capability": capability,
            "model": model,
            "stream": stream,
            "attach_media": attach_media,
            "status": "PENDING",
            "http_code": None,
            "openai_valid": False,
            "response_preview": None,
            "error": None,
            "validation": None,
            "duration": 0
        }
        
        start = time.time()
        
        try:
            prompt = PROMPTS.get(capability, f"Test {capability}")
            messages = [{"role": "user", "content": prompt}]
            
            # Attach media
            if attach_media:
                if capability == "vision" and (MEDIA_PATH / "Vision_capability_test.jpeg").exists():
                    with open(MEDIA_PATH / "Vision_capability_test.jpeg", "rb") as f:
                        img_b64 = base64.b64encode(f.read()).decode()
                    messages[0]["images"] = [f"data:image/jpeg;base64,{img_b64}"]
                    print("✓ Attached Vision_capability_test.jpeg")
            
            payload = {"model": model, "messages": messages, "stream": stream}
            
            timeout = TIMEOUTS.get(capability, 120)
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                if stream:
                    chunks = []
                    async with client.stream("POST", f"{API_BASE}/chat/completions",
                                            headers={"Authorization": f"Bearer {API_KEY}"},
                                            json=payload) as resp:
                        result["http_code"] = resp.status_code
                        if resp.status_code != 200:
                            result["error"] = f"HTTP {resp.status_code}"
                            result["status"] = "FAILED"
                            print(f"✗ FAILED: HTTP {resp.status_code}")
                            return result
                        
                        async for line in resp.aiter_lines():
                            if line.startswith("data: ") and line != "data: [DONE]":
                                try:
                                    chunks.append(json.loads(line[6:]))
                                except:
                                    pass
                    
                    result["status"] = "PASSED" if chunks else "FAILED"
                    result["response_preview"] = f"{len(chunks)} chunks received"
                    print(f"✓ PASSED: Stream with {len(chunks)} chunks")
                else:
                    resp = await client.post(f"{API_BASE}/chat/completions",
                                            headers={"Authorization": f"Bearer {API_KEY}"},
                                            json=payload)
                    
                    result["http_code"] = resp.status_code
                    
                    if resp.status_code != 200:
                        result["error"] = f"HTTP {resp.status_code}"
                        result["status"] = "FAILED"
                        print(f"✗ FAILED: HTTP {resp.status_code}")
                        return result
                    
                    data = resp.json()
                    validation = self.validate_openai_response(data, test_id)
                    result["validation"] = validation
                    result["openai_valid"] = validation["valid"]
                    
                    if validation["valid"]:
                        content = data["choices"][0]["message"]["content"]
                        result["response_preview"] = str(content)[:150]
                        result["status"] = "PASSED"
                        print(f"✓ PASSED: Valid OpenAI response")
                        print(f"  Content: {str(content)[:100]}...")
                    else:
                        result["status"] = "FAILED"
                        print(f"✗ FAILED: {validation['errors']}")
        
        except asyncio.TimeoutError:
            result["error"] = f"Timeout after {TIMEOUTS.get(capability, 120)}s"
            result["status"] = "TIMEOUT"
            print(f"✗ TIMEOUT")
        except Exception as e:
            result["error"] = str(e)[:200]
            result["status"] = "FAILED"
            print(f"✗ FAILED: {e}")
        
        finally:
            result["duration"] = round(time.time() - start, 2)
            print(f"Duration: {result['duration']}s")
        
        return result
    
    async def run_all(self):
        """Run all tests"""
        print("\n" + "="*60)
        print("ARENA API CAPABILITY TEST SUITE")
        print("="*60)
        
        tests = [
            ("01_text_nonstream", "text", MODELS["text"], False, False),
            ("02_text_stream", "text", MODELS["text"], True, False),
            ("03_image_nonstream", "image", MODELS["image"], False, False),
            ("04_image_stream", "image", MODELS["image"], True, False),
            ("05_video_nonstream", "video", MODELS["video"], False, False),
            ("06_video_stream", "video", MODELS["video"], True, False),
            ("07_web_nonstream", "web", MODELS["web"], False, False),
            ("08_web_stream", "web", MODELS["web"], True, False),
            ("09_vision_nonstream", "vision", MODELS["vision"], False, True),
            ("10_vision_stream", "vision", MODELS["vision"], True, True),
        ]
        
        for i, (test_id, cap, model, stream, media) in enumerate(tests, 1):
            result = await self.test(test_id, cap, model, stream, media)
            self.results["tests"][test_id] = result
            
            if i < len(tests):
                print(f"\nWaiting 15s before next test...")
                await asyncio.sleep(15)
        
        return self.results
    
    def save(self):
        """Save results"""
        path = RESULTS_PATH / "capability_tests_final.json"
        with open(path, "w") as f:
            json.dump(self.results, f, indent=2, default=str)
        print(f"\nResults: {path}")
        
        # Summary
        passed = sum(1 for t in self.results["tests"].values() if t["status"] == "PASSED")
        total = len(self.results["tests"])
        print(f"\nPassed: {passed}/{total}")

async def main():
    tester = APITest()
    results = await tester.run_all()
    tester.save()

if __name__ == "__main__":
    asyncio.run(main())
