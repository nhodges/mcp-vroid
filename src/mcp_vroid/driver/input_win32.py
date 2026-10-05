"""Pointer + keyboard injection on Windows, through SendInput.

The Windows counterpart of input.py (Wayland virtual pointer + XTEST), with
the same public functions. Unity reads real input, so nothing here posts
window messages: every event goes through SendInput and moves the user's
actual cursor and keyboard focus.

Because of that, the guard is stricter than on Linux and cannot be turned
off. Before every injected event group:

* fail-safe - if the cursor sits in a corner of any monitor, abort
  (FailSafeError). Shove the mouse into a corner to stop a run.
* pointer events need VRoid Studio to be the foreground window and every
  target point to lie inside its client rectangle (if something else took
  the foreground, the guard asks for it back once, then checks; it never
  acts on a window it did not verify);
* key events need the foreground window to be VRoid Studio, or the native
  file dialog VRoid itself opened (checked by class, title, process and
  owner - see window_win32.find_save_dialog);
* Win-key combinations and the window-manager chords (Alt+F4, Alt+Tab, ...)
  are refused outright, since they act on the desktop rather than on VRoid.

All public coordinates are *window-relative pixels* unless you pass
space="layout" (absolute screen px) or space="image" (px of a Shot).
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from . import window_win32 as W

BUTTONS = {"left": "left", "right": "right", "middle": "middle",
           1: "left", 2: "middle", 3: "right"}

FAILSAFE_PX = 4     # how close to a monitor corner counts as "in the corner"


class FailSafeError(RuntimeError):
    """The cursor was in a screen corner: the user asked us to stop."""


user32 = W.user32

# --- SendInput plumbing -----------------------------------------------------

_ULONG_PTR = ctypes.c_size_t


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", _ULONG_PTR)]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", _ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT),
                             ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = ctypes.c_short
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]

_MonitorEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE,
                                      wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT),
                                      wintypes.LPARAM)
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p,
                                       _MonitorEnumProc, wintypes.LPARAM]

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
_BUTTON_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010),
                 "middle": (0x0020, 0x0040)}
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
WHEEL_DELTA = 120
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79


def _send(*inputs: _INPUT) -> None:
    arr = (_INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))
    if sent != len(inputs):
        raise RuntimeError(
            f"SendInput injected {sent}/{len(inputs)} events - input is "
            "blocked (UAC prompt, lock screen, or a higher-integrity "
            "foreground window)")


# --- geometry (pure; unit-tested) -------------------------------------------

def to_absolute(x: float, y: float,
                virtual: tuple[int, int, int, int]) -> tuple[int, int]:
    """Screen px -> SendInput's 0..65535 grid over the virtual desktop.

    `virtual` is (left, top, width, height) of the virtual desktop; its
    origin is negative when a monitor sits left of / above the primary one.
    """
    vx, vy, vw, vh = virtual
    nx = round((x - vx) * 65535 / max(vw - 1, 1))
    ny = round((y - vy) * 65535 / max(vh - 1, 1))
    return nx, ny


def corner_hit(x: int, y: int, monitors: list[tuple[int, int, int, int]],
               margin: int = FAILSAFE_PX) -> bool:
    """Is (x, y) within `margin` px of a corner of any monitor rectangle
    (left, top, right, bottom)?"""
    for left, top, right, bottom in monitors:
        near_x = x - left <= margin or right - 1 - x <= margin
        near_y = y - top <= margin or bottom - 1 - y <= margin
        inside = left <= x < right and top <= y < bottom
        if inside and near_x and near_y:
            return True
    return False


def _virtual_screen() -> tuple[int, int, int, int]:
    g = user32.GetSystemMetrics
    return (g(SM_XVIRTUALSCREEN), g(SM_YVIRTUALSCREEN),
            g(SM_CXVIRTUALSCREEN), g(SM_CYVIRTUALSCREEN))


def _monitors() -> list[tuple[int, int, int, int]]:
    out: list[tuple[int, int, int, int]] = []

    @_MonitorEnumProc
    def cb(_mon, _hdc, rect, _lparam):
        r = rect.contents
        out.append((r.left, r.top, r.right, r.bottom))
        return True

    user32.EnumDisplayMonitors(None, None, cb, 0)
    return out


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# --- the guard --------------------------------------------------------------

def set_safety(on: bool) -> None:
    """Kept for interface parity with the Linux backend. The Windows guard
    cannot be disabled: this drives the user's real mouse and keyboard."""


def _failsafe() -> None:
    x, y = cursor_pos()
    if corner_hit(x, y, _monitors()):
        raise FailSafeError(
            f"fail-safe: the cursor is in a screen corner ({x}, {y}) - "
            "aborting. Move it away to let the driver act again.")


def _guard_pointer(*points: tuple[float, float]) -> W.Window:
    """Fail-safe + VRoid is foreground + every screen point is inside its
    client rectangle. Returns the window it checked against."""
    _failsafe()
    win = W.find_window()
    if win is None:
        raise RuntimeError("refusing to act: VRoid Studio window not found")
    if W.foreground() != win.hwnd and W.find_save_dialog(win) is None:
        win = W.focus(win)          # one attempt to take it back, then check
    if W.foreground() != win.hwnd:
        W.assert_vroid_focused()
        raise RuntimeError("refusing to act: VRoid Studio is not the "
                           "foreground window")
    for sx, sy in points:
        if not win.contains(sx, sy):
            raise RuntimeError(
                f"refusing to act: target ({sx:.0f}, {sy:.0f}) is outside "
                f"VRoid's client rectangle {win.geometry}")
    return win


def _guard_keys() -> None:
    """Fail-safe + keyboard focus is VRoid's window or VRoid's own verified
    save dialog. Keys go wherever focus is, so this is the whole check."""
    _failsafe()
    win = W.find_window()
    if win is None:
        raise RuntimeError("refusing to act: VRoid Studio window not found")
    for attempt in range(2):
        fg = W.foreground()
        if fg == win.hwnd:
            return
        dlg = W.find_save_dialog(win)
        if dlg is not None and fg == dlg:
            return
        if attempt == 0:
            W.focus(win)            # one attempt to take it back, then check
    W.assert_vroid_focused()
    raise RuntimeError("refusing to act: VRoid Studio is not the "
                       "foreground window")


def _guard() -> None:
    _guard_keys()


def _resolve(x: float, y: float, space: str, shot=None) -> tuple[float, float]:
    if space == "layout":
        return x, y
    if space == "image":
        if shot is None:
            raise ValueError("space='image' needs shot=")
        return shot.to_layout(x, y)
    win = W.find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    return win.to_layout(x, y)


# --- pointer ----------------------------------------------------------------

def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> _INPUT:
    i = _INPUT(type=INPUT_MOUSE)
    i.mi = _MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
    return i


def _move_abs(sx: float, sy: float, verify: bool = True) -> None:
    """Put the real cursor on a screen pixel, and check that it got there.

    `verify=False` is for the intermediate steps of a glide, where only the
    motion matters; the point a button goes down on is always verified.
    """
    tx, ty = int(round(sx)), int(round(sy))
    virt = _virtual_screen()
    for _ in range(5 if verify else 1):
        nx, ny = to_absolute(tx, ty, virt)
        _send(_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
                     | MOUSEEVENTF_VIRTUALDESK, nx, ny))
        time.sleep(0.008)
        cx, cy = cursor_pos()
        if not verify or (abs(cx - tx) <= 1 and abs(cy - ty) <= 1):
            return
    clip = wintypes.RECT()
    user32.GetClipCursor(ctypes.byref(clip))
    raise RuntimeError(
        f"cursor did not reach ({tx}, {ty}); it is at {cursor_pos()} - "
        "something else is moving the mouse, or another application has "
        f"confined it (clip rectangle {clip.left},{clip.top},{clip.right},"
        f"{clip.bottom}; virtual screen {virt})")


def _glide(sx: float, sy: float, steps: int, step_ms: int) -> None:
    cx, cy = cursor_pos()
    for i in range(1, steps + 1):
        t = i / steps
        _move_abs(cx + (sx - cx) * t, cy + (sy - cy) * t, verify=i == steps)
        time.sleep(step_ms / 1000.0)


def _button(button: str, down: bool) -> None:
    flags = _BUTTON_FLAGS[BUTTONS.get(button, "left")]
    _send(_mouse(flags[0] if down else flags[1]))


def move(x: float, y: float, space: str = "window", shot=None) -> None:
    sx, sy = _resolve(x, y, space, shot)
    _guard_pointer((sx, sy))
    _move_abs(sx, sy)


def click(x: float, y: float, button: str = "left", space: str = "window",
          shot=None, settle: float = 0.35, moves: int = 3) -> None:
    """Move (in a few steps, so hover states fire) then click."""
    sx, sy = _resolve(x, y, space, shot)
    _guard_pointer((sx, sy))
    _glide(sx, sy, moves, 12)
    time.sleep(0.06)
    # the glide took time: make sure nothing stole focus before the press
    _guard_pointer(cursor_pos())
    _button(button, True)
    time.sleep(0.04)
    _button(button, False)
    time.sleep(settle)


def double_click(x: float, y: float, **kw) -> None:
    click(x, y, **kw)
    time.sleep(0.05)
    click(x, y, settle=kw.get("settle", 0.35))


def drag(x1: float, y1: float, x2: float, y2: float, button: str = "left",
         space: str = "window", shot=None, steps: int = 24,
         settle: float = 0.4) -> None:
    """Press at (x1,y1), glide to (x2,y2), release. Used for sliders."""
    ax, ay = _resolve(x1, y1, space, shot)
    bx, by = _resolve(x2, y2, space, shot)
    _guard_pointer((ax, ay), (bx, by))
    _move_abs(ax, ay)
    time.sleep(0.12)
    _guard_pointer(cursor_pos())
    _button(button, True)
    try:
        time.sleep(0.12)
        for i in range(1, steps + 1):
            t = i / steps
            _move_abs(ax + (bx - ax) * t, ay + (by - ay) * t,
                      verify=i == steps)
            time.sleep(0.016)
        time.sleep(0.15)
    finally:
        _button(button, False)     # never leave a button held down
    time.sleep(settle)


def _wheel(flag: int, delta: int, ticks: int) -> None:
    for _ in range(abs(ticks)):
        _guard_pointer(cursor_pos())
        _send(_mouse(flag, data=delta))
        time.sleep(0.07)


def scroll(ticks: int, x: float | None = None, y: float | None = None,
           space: str = "window", shot=None, settle: float = 0.3,
           backend: str = "sendinput") -> None:
    """Wheel scroll. Negative = up/away, positive = down.

    The wheel goes to whatever is under the cursor, so without x/y the
    cursor must already be over VRoid.
    """
    if x is not None and y is not None:
        move(x, y, space, shot)
        time.sleep(0.2)
    _wheel(MOUSEEVENTF_WHEEL, -WHEEL_DELTA if ticks > 0 else WHEEL_DELTA,
           ticks)
    time.sleep(settle)


def hscroll(ticks: int, x: float | None = None, y: float | None = None,
            space: str = "window", shot=None, settle: float = 0.3) -> None:
    """Horizontal wheel. Negative = left, positive = right."""
    if x is not None and y is not None:
        move(x, y, space, shot)
        time.sleep(0.2)
    _wheel(MOUSEEVENTF_HWHEEL, WHEEL_DELTA if ticks > 0 else -WHEEL_DELTA,
           ticks)
    time.sleep(settle)


# --- keyboard ---------------------------------------------------------------
#
# Key names follow the X keysym spelling the Linux backend takes ("Return",
# "BackSpace", "Prior"), so callers do not change. Named keys and shortcuts
# are sent as scan codes, which is what Unity's input layer wants; literal
# text is sent as KEYEVENTF_UNICODE packets, which arrive as WM_CHAR and so do
# not depend on the keyboard layout at all.

_VK = {
    "return": 0x0D, "enter": 0x0D, "escape": 0x1B, "esc": 0x1B, "tab": 0x09,
    "backspace": 0x08, "delete": 0x2E, "space": 0x20, "up": 0x26,
    "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "prior": 0x21, "pagedown": 0x22, "next": 0x22,
    "insert": 0x2D,
    "ctrl": 0x11, "control": 0x11, "control_l": 0x11, "shift": 0x10,
    "shift_l": 0x10, "alt": 0x12, "alt_l": 0x12,
    **{f"f{n}": 0x6F + n for n in range(1, 13)},
}
_EXTENDED = {0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22, 0x2D, 0x2E}
_WIN_KEYS = {"super", "meta", "win", "windows", "cmd", "super_l", "super_r",
             "lwin", "rwin"}
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
# chords the shell or window manager acts on, whatever has focus
_FORBIDDEN = {
    (VK_MENU, 0x73): "alt+F4", (VK_MENU, 0x09): "alt+Tab",
    (VK_MENU, 0x1B): "alt+Escape", (VK_MENU, 0x20): "alt+Space",
    (VK_CONTROL, 0x1B): "ctrl+Escape",
}


def _vk(name: str) -> tuple[int, bool]:
    """(virtual-key, needs_shift) for a key name or a single character."""
    low = name.lower()
    if low in _WIN_KEYS:
        raise ValueError(f"refusing {name!r}: Win-key combinations act on "
                         "the desktop, not on VRoid Studio")
    if low in _VK:
        return _VK[low], False
    if len(name) == 1:
        r = user32.VkKeyScanW(name)
        if r != -1:
            return r & 0xFF, bool((r >> 8) & 1)
    raise ValueError(f"no keycode for {name!r}")


def check_combo(mod_vks: list[int], vk: int) -> None:
    """Raise for chords that reach beyond the focused application."""
    why = None
    for m in mod_vks:
        why = why or _FORBIDDEN.get((m, vk))
    if VK_CONTROL in mod_vks and VK_MENU in mod_vks and vk == 0x2E:
        why = "ctrl+alt+Delete"
    if why:
        raise ValueError(f"refusing {why}: it acts on the desktop or the "
                         "window manager, not on VRoid Studio")


def _key_event(vk: int, up: bool) -> _INPUT:
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    if vk in _EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    i = _INPUT(type=INPUT_KEYBOARD)
    i.ki = _KEYBDINPUT(vk, user32.MapVirtualKeyW(vk, 0), flags, 0, 0)
    return i


def _tap(vk: int, mods: list[int], hold: float = 0.02) -> None:
    held: list[int] = []
    try:
        for m in mods:
            _send(_key_event(m, False))
            held.append(m)
            time.sleep(0.01)
        _send(_key_event(vk, False))
        held.append(vk)
        time.sleep(hold)
    finally:
        for k in reversed(held):   # never leave a key held down
            _send(_key_event(k, True))
            time.sleep(0.005)


def _unicode_char(ch: str) -> None:
    data = ch.encode("utf-16-le")
    for i in range(0, len(data), 2):         # surrogate pairs: two packets
        unit = int.from_bytes(data[i:i + 2], "little")
        for up in (False, True):
            ev = _INPUT(type=INPUT_KEYBOARD)
            ev.ki = _KEYBDINPUT(0, unit, KEYEVENTF_UNICODE
                                | (KEYEVENTF_KEYUP if up else 0), 0, 0)
            _send(ev)


def type_text(text: str, delay_ms: int = 22) -> None:
    """Type a literal string into the focused widget."""
    for ch in text:
        _guard_keys()              # every character: focus can move mid-word
        if ch == "\n":
            key("Return")
            continue
        _unicode_char(ch)
        time.sleep(delay_ms / 1000.0)
    time.sleep(0.15)


def key(name: str, mods: list[str] | None = None, times: int = 1) -> None:
    """Press a named key: Return, Escape, Tab, BackSpace, a, ... with mods."""
    vk, need_shift = _vk(name)
    mod_vks = [_vk(m)[0] for m in (mods or [])]
    if need_shift and VK_SHIFT not in mod_vks:
        mod_vks.append(VK_SHIFT)
    check_combo(mod_vks, vk)
    for _ in range(times):
        _guard_keys()
        _tap(vk, mod_vks)
        time.sleep(0.06)
    time.sleep(0.12)


def clear_field() -> None:
    """Select-all + delete in the focused text field."""
    key("a", mods=["ctrl"])
    key("BackSpace")


def hotkey(combo: str) -> None:
    """'ctrl+shift+s' -> modifier-held keypress."""
    *mods, k = combo.split("+")
    key(k, mods=mods)


def x_focus_ok() -> bool:
    """True when keyboard focus is on the VRoid window (name kept from the
    X11 backend)."""
    return W.is_vroid_focused()
