"""
Anti-detection scripts for browser automation.

These scripts are injected into browser contexts to reduce bot detection
and bypass fingerprinting checks.

Usage:
    from .anti_detect import get_stealth_scripts, inject_stealth_scripts
    
    # Get all stealth scripts
    scripts = get_stealth_scripts()
    
    # Inject into a page/context
    await inject_stealth_scripts(context)
"""

# Comprehensive stealth script that patches multiple detection vectors
STEALTH_SCRIPT = """
// ===== ANTI-DETECTION SCRIPT =====
// Patches navigator properties to reduce bot detection

// 1. Remove webdriver property
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
});

// 2. Override navigator.plugins to look like a real browser
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
        ];
        plugins.length = 3;
        return plugins;
    },
});

// 3. Override navigator.languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en', 'ru'],
});

// 4. Override navigator.platform
Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32',
});

// 5. Override navigator.hardwareConcurrency to realistic value
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8,
});

// 6. Override navigator.deviceMemory
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8,
});

// 7. Override navigator.maxTouchPoints
Object.defineProperty(navigator, 'maxTouchPoints', {
    get: () => 0,
});

// 8. Fix chrome.runtime detection
window.chrome = window.chrome || {};
window.chrome.runtime = window.chrome.runtime || {};

// 9. Override permissions query
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);

// 10. Override WebGL vendor/renderer
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, parameter);
};

// 11. Override canvas fingerprint
const toDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(type) {
    if (type === 'image/webp') {
        return toDataURL.apply(this, arguments);
    }
    const context = this.getContext('2d');
    if (context) {
        const shift = { r: Math.floor(Math.random() * 10) - 5, g: Math.floor(Math.random() * 10) - 5, b: Math.floor(Math.random() * 10) - 5 };
        const width = this.width, height = this.height;
        if (width && height) {
            const imageData = context.getImageData(0, 0, width, height);
            for (let i = 0; i < imageData.data.length; i += 4) {
                imageData.data[i] += shift.r;
                imageData.data[i+1] += shift.g;
                imageData.data[i+2] += shift.b;
            }
            context.putImageData(imageData, 0, 0);
        }
    }
    return toDataURL.apply(this, arguments);
};

// 12. Override AudioContext fingerprint
const AudioContext = window.AudioContext || window.webkitAudioContext;
if (AudioContext) {
    const originalCreateOscillator = AudioContext.prototype.createOscillator;
    AudioContext.prototype.createOscillator = function() {
        const oscillator = originalCreateOscillator.call(this);
        const originalFrequency = oscillator.frequency.value;
        oscillator.frequency.value = originalFrequency + Math.random() * 0.001;
        return oscillator;
    };
}

// 13. Override screen dimensions
Object.defineProperty(screen, 'availWidth', { get: () => 1920 });
Object.defineProperty(screen, 'availHeight', { get: () => 1040 });
Object.defineProperty(screen, 'width', { get: () => 1920 });
Object.defineProperty(screen, 'height', { get: () => 1080 });
Object.defineProperty(screen, 'colorDepth', { get: () => 24 });

// 14. Override timezone
Object.defineProperty(Intl.DateTimeFormat.prototype, 'resolvedOptions', {
    value: function() {
        return { timeZone: 'America/New_York', locale: 'en-US' };
    }
});

// 15. Fix toString detection
const originalToString = Function.prototype.toString;
Function.prototype.toString = function() {
    if (this === Function.prototype.toString) return 'function toString() { [native code] }';
    return originalToString.call(this);
};

// 16. Override navigator.connection
if (navigator.connection) {
    Object.defineProperty(navigator.connection, 'rtt', { get: () => 50 });
}

// 17. Add fake window.outerHeight/outerWidth
Object.defineProperty(window, 'outerHeight', { get: () => 1080 });
Object.defineProperty(window, 'outerWidth', { get: () => 1920 });

// 18. Override toString for native functions
const nativeToString = Function.prototype.toString;
const customFunctions = new Map();
Function.prototype.toString = function() {
    if (customFunctions.has(this)) return customFunctions.get(this);
    return nativeToString.call(this);
};

console.log('[Anti-Detect] Stealth scripts injected successfully');
"""

# Minimal script for lightweight anti-detection
MINIMAL_STEALTH_SCRIPT = """
// Minimal anti-detection patches
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || {};
window.chrome.runtime = window.chrome.runtime || {};
"""


def get_stealth_scripts(minimal=False):
    """
    Get anti-detection scripts for injection.
    
    Args:
        minimal: If True, return minimal script (faster, less comprehensive)
        
    Returns:
        str: JavaScript code to inject
    """
    if minimal:
        return MINIMAL_STEALTH_SCRIPT
    return STEALTH_SCRIPT


async def inject_stealth_scripts(context_or_page, minimal=False):
    """
    Inject anti-detection scripts into a browser context or page.
    
    Args:
        context_or_page: Playwright BrowserContext or Page object
        minimal: If True, inject minimal script
    """
    script = get_stealth_scripts(minimal=minimal)
    try:
        await context_or_page.add_init_script(script)
        return True
    except Exception as e:
        print(f"[Anti-Detect] Failed to inject scripts: {e}")
        return False


# Fingerprint rotation data
FINGERPRINTS = [
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
        "locale": "en-US",
        "timezone": "America/New_York",
    },
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "viewport": {"width": 1366, "height": 768},
        "locale": "en-US",
        "timezone": "America/Chicago",
    },
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "viewport": {"width": 1440, "height": 900},
        "locale": "en-US",
        "timezone": "America/Los_Angeles",
    },
]


def get_random_fingerprint():
    """
    Get a random browser fingerprint for rotation.
    
    Returns:
        dict: Fingerprint configuration
    """
    import random
    return random.choice(FINGERPRINTS)
