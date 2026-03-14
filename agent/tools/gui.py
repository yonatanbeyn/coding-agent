"""GUI automation tools.

Minimal layer that works on ANY app — native, Electron, system UI, Dock, menu bar.

Tools:
  open_app      — launch any app by name
  screenshot    — capture screen → returns image path
  mouse_click   — click at x,y
  keyboard_type — type text (handles unicode via clipboard)
  keyboard_hotkey — press key combos (cmd+t, cmd+space, etc.)
  vision_find   — screenshot + Claude vision → returns x,y of described element

Permissions needed (System Settings → Privacy):
  • Accessibility    — mouse & keyboard control
  • Screen Recording — screenshots
"""

import base64
import json
import os
import subprocess
import tempfile
import time

try:
    import pyautogui
    pyautogui.FAILSAFE = True   # move mouse to top-left corner to abort
    pyautogui.PAUSE = 0.15      # pause between actions (more reliable)
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

_MISSING = {"error": "pyautogui not installed. Run: pip install pyautogui pillow"}


# ── open_app ──────────────────────────────────────────────────────────────────

def open_app(name: str, wait: float = 1.5) -> dict:
    """Open any macOS application by name and wait for it to appear."""
    result = subprocess.run(
        ["open", "-a", name],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {"success": False, "error": result.stderr.strip()}
    time.sleep(wait)
    return {"success": True, "app": name}


def focus_app(name: str, wait: float = 1.0) -> dict:
    """Bring an already-running app to the foreground using AppleScript."""
    script = f'tell application "{name}" to activate'
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True,
    )
    time.sleep(wait)
    if result.returncode != 0:
        return {"success": False, "error": result.stderr.strip()}
    return {"success": True, "app": name}


# ── screenshot ────────────────────────────────────────────────────────────────

def screenshot(save_path: str | None = None, focus: str | None = None) -> dict:
    """Take a full-screen screenshot. Returns the file path and screen dimensions.

    Args:
        save_path: Optional path to save the screenshot.
        focus: App name to bring to foreground before capturing (e.g. "Postman").
    """
    if not HAS_PYAUTOGUI:
        return _MISSING
    if focus:
        focus_result = focus_app(focus)
        if not focus_result.get("success"):
            return focus_result
    try:
        img = pyautogui.screenshot()
        if not save_path:
            save_path = os.path.join(tempfile.gettempdir(), f"agent_screen_{int(time.time())}.png")
        img.save(save_path)
        w, h = img.size
        return {"path": save_path, "width": w, "height": h}
    except Exception as e:
        return {"error": str(e)}


# ── mouse_click ───────────────────────────────────────────────────────────────

def mouse_click(x: int, y: int, button: str = "left", double: bool = False) -> dict:
    """Click at screen coordinates. button: left | right | middle."""
    if not HAS_PYAUTOGUI:
        return _MISSING
    try:
        clicks = 2 if double else 1
        pyautogui.click(x, y, button=button, clicks=clicks, interval=0.1)
        return {"success": True, "x": x, "y": y, "button": button}
    except Exception as e:
        return {"error": str(e)}


# ── click_and_type ────────────────────────────────────────────────────────────

def click_and_type(x: int, y: int, text: str, focus: str | None = None) -> dict:
    """
    Click an element at (x, y) and immediately type text into it.
    Optionally brings an app to front first. Clears existing content before typing.
    Use this instead of separate mouse_click + keyboard_type to avoid focus loss.
    """
    if not HAS_PYAUTOGUI:
        return _MISSING
    try:
        if focus:
            focus_result = focus_app(focus)
            if not focus_result.get("success"):
                return focus_result
        # Click the target element
        pyautogui.click(x, y)
        time.sleep(0.3)
        # Select all existing content and replace
        pyautogui.hotkey("cmd", "a")
        time.sleep(0.1)
        pyautogui.press("delete")
        time.sleep(0.1)
        # Paste via clipboard
        subprocess.run("pbcopy", input=text.encode("utf-8"), check=True)
        time.sleep(0.15)
        pyautogui.hotkey("cmd", "v")
        time.sleep(0.1)
        return {"success": True, "x": x, "y": y, "typed": text}
    except Exception as e:
        return {"error": str(e)}


# ── keyboard_type ─────────────────────────────────────────────────────────────

def keyboard_type(text: str, focus: str | None = None, clear: bool = True) -> dict:
    """
    Type text into the focused element.
    Uses clipboard paste so unicode, symbols, and special chars all work.

    Args:
        focus: App name to bring to foreground before typing (e.g. "Postman").
               Always pass this when another tool call may have shifted focus.
        clear: If True (default), select-all then delete before typing to
               replace any existing text in the field.
    """
    if not HAS_PYAUTOGUI:
        return _MISSING
    try:
        if focus:
            focus_result = focus_app(focus)
            if not focus_result.get("success"):
                return focus_result
        if clear:
            pyautogui.hotkey("cmd", "a")
            time.sleep(0.1)
            pyautogui.press("delete")
            time.sleep(0.1)
        # Copy to clipboard then paste — handles any character
        subprocess.run("pbcopy", input=text.encode("utf-8"), check=True)
        time.sleep(0.1)
        pyautogui.hotkey("cmd", "v")
        return {"success": True, "typed": text}
    except Exception as e:
        return {"error": str(e)}


# ── keyboard_hotkey ───────────────────────────────────────────────────────────

def keyboard_hotkey(keys: list[str]) -> dict:
    """
    Press a key combination simultaneously.
    Examples: ["cmd","t"], ["cmd","space"], ["cmd","shift","4"]
    Key names: cmd, ctrl, alt/option, shift, enter, tab, escape, space,
               up, down, left, right, delete, f1-f12
    """
    if not HAS_PYAUTOGUI:
        return _MISSING
    try:
        pyautogui.hotkey(*keys)
        return {"success": True, "keys": keys}
    except Exception as e:
        return {"error": str(e)}


# ── vision_find ───────────────────────────────────────────────────────────────

def vision_find(description: str, then_click: bool = False, focus: str | None = None) -> dict:
    """
    Take a screenshot and ask Claude to locate a UI element by description.
    Returns x,y pixel coordinates of the element center.
    Optionally clicks the found location if then_click=True.

    Args:
        focus: App name to bring to foreground before capturing (e.g. "Postman").

    Examples:
      vision_find("URL bar in Postman", focus="Postman")
      vision_find("Apple menu icon", then_click=True)
      vision_find("Sleep option in the Apple menu")
    """
    # 1. Capture screen
    shot = screenshot(focus=focus)
    if "error" in shot:
        return shot

    img_path = shot["path"]
    screen_w = shot["width"]
    screen_h = shot["height"]

    # 2. Encode image
    with open(img_path, "rb") as f:
        img_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

    # 3. Ask Claude vision
    try:
        import anthropic
        api_key = (
            os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("AGENT_API_KEY")
        )
        client = anthropic.Anthropic(api_key=api_key)

        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            f'Find this element on the screen: "{description}"\n'
                            f"Screen resolution: {screen_w}x{screen_h} pixels.\n\n"
                            "Reply with ONLY a JSON object, no explanation:\n"
                            '{"found": true, "x": <int>, "y": <int>, "confidence": "high|medium|low", "note": "<optional short note>"}\n'
                            "x and y must be the center pixel of the element. "
                            'If not found: {"found": false, "note": "<reason>"}'
                        ),
                    },
                ],
            }],
        )

        raw = resp.content[0].text.strip()
        # Extract JSON even if Claude adds extra text
        start, end = raw.find("{"), raw.rfind("}") + 1
        result = json.loads(raw[start:end])
        result["screenshot"] = img_path

    except Exception as e:
        return {"error": f"Vision call failed: {e}", "screenshot": img_path}

    # 4. Optionally click
    if result.get("found") and then_click:
        x, y = result["x"], result["y"]
        click_result = mouse_click(x, y)
        result["clicked"] = click_result.get("success", False)

    return result


# ── Schemas ───────────────────────────────────────────────────────────────────

OPEN_APP_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "App name as it appears in /Applications (e.g. Postman, IntelliJ IDEA, Google Chrome)"},
        "wait": {"type": "number", "description": "Seconds to wait after launching. Default 1.5", "default": 1.5},
    },
    "required": ["name"],
}

SCREENSHOT_SCHEMA = {
    "type": "object",
    "properties": {
        "save_path": {"type": "string", "description": "Optional file path to save the screenshot. Auto-generated if omitted."},
        "focus": {"type": "string", "description": "App name to bring to foreground before capturing (e.g. 'Postman', 'Google Chrome'). Use this to avoid capturing the wrong window."},
    },
}

FOCUS_APP_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "App name to bring to the foreground (e.g. 'Postman', 'IntelliJ IDEA')"},
        "wait": {"type": "number", "description": "Seconds to wait after focusing. Default 1.0", "default": 1.0},
    },
    "required": ["name"],
}

MOUSE_CLICK_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {"type": "integer", "description": "Horizontal pixel coordinate"},
        "y": {"type": "integer", "description": "Vertical pixel coordinate"},
        "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
        "double": {"type": "boolean", "description": "Double-click. Default false", "default": False},
    },
    "required": ["x", "y"],
}

CLICK_AND_TYPE_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {"type": "integer", "description": "Horizontal pixel coordinate to click"},
        "y": {"type": "integer", "description": "Vertical pixel coordinate to click"},
        "text": {"type": "string", "description": "Text to type into the clicked element"},
        "focus": {"type": "string", "description": "App name to bring to foreground first (e.g. 'Postman')"},
    },
    "required": ["x", "y", "text"],
}

KEYBOARD_TYPE_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "Text to type into the focused element"},
        "focus": {"type": "string", "description": "App name to bring to foreground before typing (e.g. 'Postman'). Use this whenever another tool call may have shifted focus away."},
        "clear": {"type": "boolean", "description": "Select-all and delete existing text before typing. Default true.", "default": True},
    },
    "required": ["text"],
}

KEYBOARD_HOTKEY_SCHEMA = {
    "type": "object",
    "properties": {
        "keys": {
            "type": "array",
            "items": {"type": "string"},
            "description": 'Key names to press simultaneously. E.g. ["cmd","t"], ["cmd","space"], ["enter"]',
        },
    },
    "required": ["keys"],
}

VISION_FIND_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": 'Natural language description of the element to find. E.g. "URL bar in Postman", "Apple menu icon", "Send button"',
        },
        "then_click": {
            "type": "boolean",
            "description": "If true, automatically click the found element. Default false.",
            "default": False,
        },
        "focus": {
            "type": "string",
            "description": "App name to bring to foreground before capturing the screenshot (e.g. 'Postman'). Prevents capturing the wrong window.",
        },
    },
    "required": ["description"],
}