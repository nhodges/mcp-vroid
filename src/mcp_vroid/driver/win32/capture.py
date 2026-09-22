"""Screenshot the VRoid window with PIL.ImageGrab.

The process is per-monitor DPI aware (see win32/__init__.py), so window
geometry and ImageGrab both speak physical pixels: a Shot's scale is 1.0 and
OCR pixel coords go straight back to input.click().

ImageGrab reads the composed desktop, so it sees whatever is on top - the
same as grim. Tested against VRoid 2.14.0's Direct3D window: not black.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from pathlib import Path

from PIL import ImageGrab

from ..shot import Shot, next_capture_path  # noqa: F401  (re-exported)
from . import user32
from . import window as W


def output_scale() -> float:
    """Image pixels per layout unit. Both are physical pixels here."""
    return 1.0


def grab_region(x: int, y: int, w: int, h: int, tag: str = "",
                path: Path | None = None) -> Shot:
    path = path or next_capture_path(tag)
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).convert("RGB")
    img.save(path)
    scale = img.width / w if w else 1.0
    return Shot(img, path, x, y, scale)


def grab_window(win: W.Window | None = None, tag: str = "") -> Shot:
    win = win or W.find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    return grab_region(*win.geometry, tag=tag)


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


user32.MonitorFromWindow.argtypes = (wt.HWND, wt.DWORD)
user32.GetMonitorInfoW.argtypes = (wt.HANDLE, ctypes.POINTER(_MONITORINFO))


def _monitor_rect() -> tuple[int, int, int, int]:
    """The monitor VRoid is on (its dialogs open there too), else primary."""
    win = W.find_window()
    MONITOR_DEFAULTTOPRIMARY = 1
    hmon = user32.MonitorFromWindow(win.hwnd if win else 0, MONITOR_DEFAULTTOPRIMARY)
    mi = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
    r = mi.rcMonitor
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def grab_screen(tag: str = "") -> Shot:
    return grab_region(*_monitor_rect(), tag=tag)
