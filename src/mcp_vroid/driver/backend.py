"""Pick the window / capture / input implementation for this desktop.

Everything above this layer - actions, the MCP server, the CLI - reaches
`window`, `capture` and `input` through here and never names a platform:

    from .backend import capture as C, input as I, window as W

Backends:

    hyprland   window.py / capture.py / input.py next to this file
               (hyprctl, grim, the wlr virtual pointer, XTEST)
    win32      win32/window.py, capture.py, input.py
               (EnumWindows + DWM, PIL.ImageGrab, SendInput)

The choice follows the running platform. MCP_VROID_BACKEND overrides it,
which is how the Hyprland modules can be imported and inspected on a
machine that is not running Hyprland.

What a backend has to provide is whatever the callers use; see
CONTRACT below, which the backends are checked against.
"""
from __future__ import annotations

import os
import shutil
import sys

NAME = os.environ.get("MCP_VROID_BACKEND") or (
    "win32" if sys.platform == "win32" else "hyprland")

if NAME == "hyprland":
    from . import capture, input, window  # noqa: F401
elif NAME == "win32":
    from .win32 import capture, input, window  # noqa: F401
else:
    raise ImportError(
        f"mcp-vroid has no {NAME!r} backend "
        f"(platform {sys.platform!r}; set MCP_VROID_BACKEND to override)")


def helpers() -> dict:
    """External programs this backend needs, and whether each is present."""
    if NAME == "win32":
        # Everything else is the Win32 API through ctypes.
        return {"tesseract": bool(shutil.which("tesseract"))}
    from .paths import VPOINTER
    return {
        "vpointer": {"path": str(VPOINTER), "present": VPOINTER.exists()},
        "grim": bool(shutil.which("grim")),
        "tesseract": bool(shutil.which("tesseract")),
        "hyprctl": bool(shutil.which("hyprctl")),
    }


# What actions.py, server.py and cli.py call on each module. A new backend
# must provide all of it; the names are Hyprland's because that is where they
# came from ("workspace" is wherever the user was before we took the screen).
CONTRACT = {
    "window": ("Window", "WORKSPACE", "active_workspace", "assert_vroid_focused",
               "dismiss_screensaver", "enter", "find_dialog", "find_window",
               "fullscreen", "is_vroid_focused", "kill", "leave", "park",
               "prepare"),
    "capture": ("grab_screen", "grab_window", "output_scale"),
    "input": ("clear_field", "click", "double_click", "drag", "hotkey",
              "hscroll", "key", "scroll", "type_text"),
}

# Used when present, with a fallback in the caller when not.
#   window.fill_save_dialog(dialog, path)   actions._save_dialog(): drive the
#       file dialog as controls instead of typing into it and OCR-checking.
OPTIONAL = {
    "window": ("fill_save_dialog",),
}
