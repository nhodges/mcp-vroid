"""Pick the platform layer: window management, capture and input.

Everything above this line of the stack - locate.py, actions.py, the CLI and
the MCP server - is written against three modules with the same function
names on every platform:

    window   find / launch / focus the VRoid window
    capture  screenshot it into a Shot
    input    pointer and keyboard injection

Linux (Hyprland/Wayland) gets window.py, capture.py and input.py; Windows
gets the *_win32.py modules. Import them from here:

    from .backend import capture as C, input as I, window as W
"""
from __future__ import annotations

import sys

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from . import capture_win32 as capture  # noqa: F401
    from . import input_win32 as input  # noqa: F401
    from . import window_win32 as window  # noqa: F401
else:
    from . import capture  # noqa: F401
    from . import input  # noqa: F401
    from . import window  # noqa: F401
