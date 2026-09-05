import json
import asyncio
import httpx

# Test configurations for Direct mode
TESTS = {
    "text_generation": {
        "name": "Text Generation",
        "capability": "text",
        "model_filter": lambda m: m.get("capabilities", {}).get("outputCapabilities", {}).get("text"),
        "prompt": "The cat sat on the mat. What i write right now ?"
    },
    "image_generation": {
        "name": "Image Generation",
        "capability": "image",
        "model_filter": lambda m: m.get("capabilities", {}).get("outputCapabilities", {}).get("image"),
        "prompt": "Draw an apple"
    },
    "video_generation": {
        "name": "Video Generation",
        "capability": "video",
        "model_filter": lambda m: m.get("capabilities", {}).get("outputCapabilities", {}).get("video"),
        "prompt": "Falling stars at the midnight"
    },
    "webdev_generation": {
        "name": "WebDev/Website Generation",
        "capability": "web",
        "model_filter": lambda m: m.get("capabilities", {}).get("outputCapabilities", {}).get("web"),
        "prompt": "Create ordinary loading page with text \"Just preparing your connection...\""
    },
    "vision_recognition": {
        "name": "Vision/Image Recognition",
        "capability": "vision",
        "model_filter": lambda m: m.get("capabilities", {}).get("inputCapabilities", {}).get("image"),
        "prompt": "What happened on this image ? Describe objects, animals, and actions you see using comma-separated words (cat, sausage, phone, camera, etc)",
        "requires_image": True
    }
}

async def run_direct_mode_tests():
    api_key = "sk-lmab-357ff040-705d-4f0f-8fce-687f08e9a238"
    api_base = "http://localhost:6767/api/v1"
    
    results = {}
    
    for test_id, test_config in TESTS.items():
        print(f"\n[TEST] {test_config['name']}")
        print(f"  Capability: {test_config['capability']}")
        print(f"  Prompt: {test_config['prompt']}")
        
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                payload = {
                    "model": "gpt-5.4-mini-high",  # Default model, will be overridden by capability
                    "messages": [{
                        "role": "user",
                        "content": test_config['prompt']
                    }],
                    "stream": False
                }
                
                resp = await client.post(
                    f"{api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                    timeout=180
                )
                
                result = resp.json() if resp.status_code == 200 else {"error": resp.text[:200]}
                results[test_id] = {
                    "status": resp.status_code,
                    "response": result
                }
                
                print(f"  Status: {resp.status_code}")
                if resp.status_code == 200:
                    print(f"  ✓ Success")
                else:
                    print(f"  ✗ Error: {result}")
                    
        except Exception as e:
            results[test_id] = {"error": str(e)}
            print(f"  ✗ Exception: {e}")
    
    with open("/home/forget/QwertyWork/direct_mode_tests.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print("\n\nResults saved to /home/forget/QwertyWork/direct_mode_tests.json")

if __name__ == "__main__":
    asyncio.run(run_direct_mode_tests())
