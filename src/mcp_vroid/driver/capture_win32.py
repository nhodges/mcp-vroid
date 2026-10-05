"""Screenshot the VRoid window on Windows and hand back a PIL image.

The Windows counterpart of capture.py (grim). Same Shot, same functions.

The window itself is read with PrintWindow(PW_RENDERFULLCONTENT), which asks
the compositor (DWM) for the window's own surface: it works for a Direct3D
Unity window, on any monitor, and it only ever returns VRoid's pixels - so a
passive screenshot never leaks somebody else's app. A Unity window that is
covered or in the background can come back as an empty (flat) frame; that is
reported as an error rather than papered over with a copy of the screen.

Coordinates: the process is per-monitor DPI aware (see window_win32), so
image pixels, screen pixels and SendInput pixels are all the same thing here
and a Shot's scale is always 1.0.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageGrab

from . import window_win32 as W
from .capture import Shot, next_capture_path  # noqa: F401  (portable parts)

user32 = W.user32
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int,
                                         ctypes.c_int]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                            wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
                            wintypes.UINT]

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2
MONITOR_DEFAULTTOPRIMARY = 1


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE,
                                   ctypes.POINTER(_MONITORINFO)]


def output_scale() -> float:
    """Image px per coordinate unit. Always 1.0: see the module docstring."""
    return 1.0


def _print_window(hwnd: int, w: int, h: int) -> Image.Image | None:
    """The window's client area via PrintWindow, or None if that failed."""
    hdc = user32.GetDC(hwnd)
    if not hdc:
        return None
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        if not user32.PrintWindow(hwnd, mdc,
                                  PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            return None
        bi = _BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bi.biWidth, bi.biHeight = w, -h          # negative = top-down rows
        bi.biPlanes, bi.biBitCount = 1, 32
        buf = ctypes.create_string_buffer(w * h * 4)
        if gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0) != h:
            return None
        img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).copy()
    finally:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hwnd, hdc)
    if is_blank(img):
        return None
    return img


def is_blank(img: Image.Image) -> bool:
    """A surface the compositor could not read comes back as one flat colour
    (black, or white for a Unity window that is covered or in the
    background). No real VRoid screen is a single colour."""
    return all(lo == hi for lo, hi in img.getextrema())


def grab_region(x: int, y: int, w: int, h: int, tag: str = "",
                path: Path | None = None) -> Shot:
    """Copy a rectangle of the *screen* (virtual-desktop px, any monitor)."""
    path = path or next_capture_path(tag)
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    img = img.convert("RGB")
    img.save(path)
    return Shot(img, path, x, y, 1.0)


def grab_window(win: W.Window | None = None, tag: str = "") -> Shot:
    win = win or W.find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    if W.user32.IsIconic(win.hwnd) or win.w <= 0 or win.h <= 0:
        raise RuntimeError("VRoid Studio is minimised - nothing to capture; "
                           "focus it first")
    img = _print_window(win.hwnd, win.w, win.h)
    if img is None:
        # Copying the screen instead is only honest when VRoid is what is
        # on it; otherwise the "screenshot" would be of some other app.
        if W.foreground() != win.hwnd:
            raise RuntimeError(
                "VRoid Studio is in the background and Windows returned an "
                "empty frame for it - focus it first (vroid_launch, or any "
                "acting tool) and capture again")
        return grab_region(*win.geometry, tag=tag)
    path = next_capture_path(tag)
    img.save(path)
    return Shot(img, path, win.x, win.y, 1.0)


def grab_screen(tag: str = "") -> Shot:
    """The whole monitor VRoid is on (the primary one if it is not running).

    This is a real screen copy: unlike grab_window it shows whatever is on
    that monitor, including VRoid's native save dialog.
    """
    win = W.find_window()
    mon = user32.MonitorFromWindow(win.hwnd if win else None,
                                   MONITOR_DEFAULTTOPRIMARY)
    mi = _MONITORINFO()
    mi.cbSize = ctypes.sizeof(_MONITORINFO)
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    r = mi.rcMonitor
    return grab_region(r.left, r.top, r.right - r.left, r.bottom - r.top,
                       tag=tag)
