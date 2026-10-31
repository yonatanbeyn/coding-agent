---
name: desktop-gui
description: Control macOS desktop apps (Postman, Chrome, IntelliJ, Slack, Finder…) by opening them, taking screenshots, finding UI elements with vision, clicking and typing. Use when the user asks to do something inside a GUI application rather than in code, e.g. "send a GET request in Postman" or "open Chrome and search for X".
compatibility: macOS with Accessibility and Screen Recording permissions; requires pyautogui and pillow.
allowed-tools: open_app focus_app screenshot mouse_click click_and_type keyboard_type keyboard_hotkey vision_find
---

# Desktop GUI automation

Activating this skill unlocks the GUI tools listed in `allowed-tools`. Every
action that touches the screen still goes through the user's permission prompt.

## Before you start
- Do NOT explore the project's files for GUI-only tasks like "open Postman" or
  "click a button".
- If the task is ambiguous (e.g. "make a GET request" with no URL), ask the user
  for the missing details first. Never infer URLs or endpoints from workspace code.

## Workflow
1. `open_app` to launch the app, or `focus_app` if it is already running.
2. `screenshot(focus="AppName")` to capture the app in front.
3. `vision_find` to locate the UI element you need (returns x, y).
4. To type into a field use `click_and_type(x, y, text, focus="AppName")`. It
   clicks AND types in one step, so focus is never lost. Never use
   `mouse_click` followed by a separate `keyboard_type`.
5. `keyboard_hotkey` for shortcuts, e.g. `["cmd", "enter"]` to send in Postman.
6. Take a fresh screenshot after each important action to confirm the result
   before continuing.

## Safety
- Moving the mouse to the top-left corner aborts automation (pyautogui failsafe).
- Never type passwords or secrets unless the user typed them for this task.

See `reference/app-tips.md` for app-specific shortcuts.
