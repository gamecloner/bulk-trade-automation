"""
Anti-detection utilities for browser automation.
Provides stealth patches, human-like mouse movements, and fingerprint randomization.
"""

import random
import math
import asyncio
from typing import List, Tuple, Optional


# ── Stealth JavaScript Patches ──────────────────────────────────────
# These scripts are injected into every page to mask automation signals.

STEALTH_SCRIPTS = """
// ═══════════════════════════════════════════════════════
// BULK TRADE BOT — STEALTH INJECTION LAYER
// ═══════════════════════════════════════════════════════

// 1. Remove webdriver flag
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// 2. Override navigator.plugins (empty in headless)
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' },
        ];
        plugins.length = 3;
        return plugins;
    }
});

// 3. Override navigator.languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en']
});

// 4. Fix chrome.runtime (missing in headless)
if (!window.chrome) window.chrome = {};
if (!window.chrome.runtime) {
    window.chrome.runtime = {
        connect: function() {},
        sendMessage: function() {},
        id: 'bulk-trade-extension-mock'
    };
}

// 5. Override permissions query
const originalQuery = window.navigator.permissions?.query;
if (originalQuery) {
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters)
    );
}

// 6. Fix WebGL vendor/renderer (headless gives "Google Inc." / "ANGLE")
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    // UNMASKED_VENDOR_WEBGL
    if (parameter === 37445) {
        return 'Intel Inc.';
    }
    // UNMASKED_RENDERER_WEBGL
    if (parameter === 37446) {
        return 'Intel Iris OpenGL Engine';
    }
    return getParameter.call(this, parameter);
};

// 7. Fix WebGL2 as well
if (typeof WebGL2RenderingContext !== 'undefined') {
    const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter2.call(this, parameter);
    };
}

// 8. Prevent detection via toString
const originalToString = Function.prototype.toString;
Function.prototype.toString = function() {
    if (this === navigator.permissions.query) {
        return 'function query() { [native code] }';
    }
    if (this === WebGLRenderingContext.prototype.getParameter) {
        return 'function getParameter() { [native code] }';
    }
    return originalToString.call(this);
};

// 9. Override connection info to hide automation
Object.defineProperty(navigator, 'connection', {
    get: () => ({
        downlink: 10,
        effectiveType: '4g',
        rtt: 50,
        saveData: false,
    })
});

// 10. Add fake media devices
if (navigator.mediaDevices) {
    navigator.mediaDevices.enumerateDevices = async () => [
        { deviceId: 'default', kind: 'audioinput', label: 'Default', groupId: 'default' },
        { deviceId: 'default', kind: 'videoinput', label: 'Default', groupId: 'default' },
        { deviceId: 'default', kind: 'audiooutput', label: 'Default', groupId: 'default' },
    ];
}

console.log('[STEALTH] Anti-detection patches applied');
"""


# ── Human-Like Mouse Movement ───────────────────────────────────────

def _bezier_point(t: float, p0: Tuple, p1: Tuple, p2: Tuple, p3: Tuple) -> Tuple[float, float]:
    """Calculate point on cubic Bezier curve at parameter t."""
    x = (
        (1 - t) ** 3 * p0[0]
        + 3 * (1 - t) ** 2 * t * p1[0]
        + 3 * (1 - t) * t ** 2 * p2[0]
        + t ** 3 * p3[0]
    )
    y = (
        (1 - t) ** 3 * p0[1]
        + 3 * (1 - t) ** 2 * t * p1[1]
        + 3 * (1 - t) * t ** 2 * p2[1]
        + t ** 3 * p3[1]
    )
    return (x, y)


def generate_human_mouse_path(
    start: Tuple[int, int],
    end: Tuple[int, int],
    num_points: int = 20,
    randomness: float = 0.3,
) -> List[Tuple[int, int]]:
    """
    Generate a realistic mouse path between two points using cubic Bezier curves.
    Adds slight randomness to control points for natural-looking curves.
    """
    distance = math.sqrt((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2)
    offset = distance * randomness

    # Random control points for the Bezier curve
    cp1 = (
        start[0] + random.uniform(-offset, offset) + (end[0] - start[0]) * 0.3,
        start[1] + random.uniform(-offset, offset) + (end[1] - start[1]) * 0.1,
    )
    cp2 = (
        start[0] + random.uniform(-offset, offset) + (end[0] - start[0]) * 0.7,
        start[1] + random.uniform(-offset, offset) + (end[1] - start[1]) * 0.9,
    )

    points = []
    for i in range(num_points + 1):
        t = i / num_points
        # Apply easing — slow start, fast middle, slow end
        t_eased = t * t * (3 - 2 * t)  # smoothstep
        point = _bezier_point(t_eased, start, cp1, cp2, end)
        # Add micro-jitter (1-2px) for realism
        jitter_x = random.randint(-1, 1)
        jitter_y = random.randint(-1, 1)
        points.append((int(point[0] + jitter_x), int(point[1] + jitter_y)))

    # Ensure exact start and end
    points[0] = start
    points[-1] = end
    return points


async def human_move_mouse(page, target_x: int, target_y: int):
    """
    Move the mouse to target coordinates with human-like Bezier curve movement.
    Uses the Playwright page object.
    """
    # Get current mouse position (approximate from viewport center if unknown)
    current_x = getattr(page, '_last_mouse_x', 960)
    current_y = getattr(page, '_last_mouse_y', 540)

    path = generate_human_mouse_path(
        start=(current_x, current_y),
        end=(target_x, target_y),
        num_points=random.randint(15, 30),
    )

    for point in path:
        await page.mouse.move(point[0], point[1])
        # Variable speed — faster in the middle, slower at edges
        await asyncio.sleep(random.uniform(0.005, 0.02))

    page._last_mouse_x = target_x
    page._last_mouse_y = target_y


async def human_click(page, selector: str, timeout: int = 10000):
    """
    Click an element with human-like behavior:
    1. Scroll element into view
    2. Move mouse with Bezier curve
    3. Small pause before click
    4. Click with slight position offset
    """
    element = await page.wait_for_selector(selector, timeout=timeout)
    if not element:
        raise Exception(f"Element not found: {selector}")

    # Get element bounding box
    box = await element.bounding_box()
    if not box:
        raise Exception(f"Element has no bounding box: {selector}")

    # Target a random point within the element (not dead center)
    target_x = int(box["x"] + box["width"] * random.uniform(0.3, 0.7))
    target_y = int(box["y"] + box["height"] * random.uniform(0.3, 0.7))

    # Move mouse naturally
    await human_move_mouse(page, target_x, target_y)

    # Small pause before clicking (human reaction time)
    await asyncio.sleep(random.uniform(0.05, 0.15))

    # Click
    await page.mouse.click(target_x, target_y)

    # Small pause after clicking
    await asyncio.sleep(random.uniform(0.1, 0.3))


async def human_type(page, selector: str, text: str, wpm: int = 80):
    """
    Type text with human-like speed and occasional pauses.
    WPM (words per minute) controls average typing speed.
    """
    element = await page.wait_for_selector(selector, timeout=10000)
    await element.click()
    await asyncio.sleep(random.uniform(0.1, 0.3))

    # Clear existing content
    await element.fill("")

    chars_per_second = (wpm * 5) / 60  # Average word = 5 chars
    base_delay = 1.0 / chars_per_second

    for i, char in enumerate(text):
        await element.type(char, delay=0)

        # Variable delay per character
        delay = base_delay * random.uniform(0.5, 1.5)

        # Longer pause after spaces and punctuation
        if char in " .,!?":
            delay *= random.uniform(1.5, 3.0)

        # Occasional longer pause (thinking)
        if random.random() < 0.03:
            delay += random.uniform(0.3, 0.8)

        await asyncio.sleep(delay)


def random_viewport() -> dict:
    """Generate a realistic random viewport size."""
    viewports = [
        {"width": 1920, "height": 1080},
        {"width": 1366, "height": 768},
        {"width": 1536, "height": 864},
        {"width": 1440, "height": 900},
        {"width": 1680, "height": 1050},
        {"width": 2560, "height": 1440},
    ]
    return random.choice(viewports)


def random_user_agent() -> str:
    """Generate a realistic Chrome user agent string."""
    chrome_versions = [
        "124.0.6367.118", "124.0.6367.91", "123.0.6312.122",
        "125.0.6422.60", "125.0.6422.76", "126.0.6478.36",
    ]
    platforms = [
        "Windows NT 10.0; Win64; x64",
        "Windows NT 10.0; Win64; x64",  # Weighted toward Windows
        "Macintosh; Intel Mac OS X 10_15_7",
    ]
    version = random.choice(chrome_versions)
    platform = random.choice(platforms)
    return f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"


async def random_delay(min_ms: int = 200, max_ms: int = 800):
    """Async sleep for a random duration (human-like pacing)."""
    delay = random.uniform(min_ms / 1000, max_ms / 1000)
    await asyncio.sleep(delay)


async def random_scroll(page, direction: str = "down", amount: Optional[int] = None):
    """Perform a random scroll action to appear human."""
    if amount is None:
        amount = random.randint(100, 400)
    if direction == "up":
        amount = -amount
    await page.mouse.wheel(0, amount)
    await asyncio.sleep(random.uniform(0.2, 0.5))
