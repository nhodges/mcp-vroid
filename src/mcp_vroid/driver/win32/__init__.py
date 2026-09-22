"""Windows backend: EnumWindows + DWM for the window, PIL.ImageGrab for the
screen, SendInput for the mouse and keyboard. ctypes only - nothing to build,
nothing to install beyond what the package already depends on.

VRoid Studio runs natively on Windows, so none of the Linux backend's
workarounds for Proton/XWayland apply: one input path serves pointer, wheel
and keys, and the file dialogs take ordinary Windows paths.

Coordinates are *physical* screen pixels. The process declares per-monitor
DPI awareness before anything else, so window rectangles, screenshots and
SendInput all agree and a Shot's scale is 1.0.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _declare_dpi_awareness() -> None:
    # PER_MONITOR_AWARE_V2 (-4); Windows 8.1-era fallback; then give up and
    # accept virtualised coordinates rather than fail to import.
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except AttributeError:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


_declare_dpi_awareness()

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


INPUT_MOUSE, INPUT_KEYBOARD = 0, 1

user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wt.UINT
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = (wt.HWND, ctypes.POINTER(wt.DWORD))
user32.MapVirtualKeyW.restype = wt.UINT
user32.VkKeyScanW.restype = ctypes.c_short
user32.MonitorFromWindow.restype = wt.HANDLE


def send(*inputs: INPUT) -> None:
    """SendInput, and refuse to pretend when Windows drops events.

    UIPI silently blocks input into a window of a higher integrity level
    (an elevated VRoid, say); SendInput then reports fewer events sent.
    """
    arr = (INPUT * len(inputs))(*inputs)
    n = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if n != len(inputs):
        raise OSError(
            f"SendInput delivered {n}/{len(inputs)} events "
            f"(error {ctypes.get_last_error()}) - is VRoid running elevated?")


def mouse_input(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    i = INPUT(type=INPUT_MOUSE)
    i.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
    return i


def key_input(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    i = INPUT(type=INPUT_KEYBOARD)
    i.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i
