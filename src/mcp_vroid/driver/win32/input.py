"""Pointer + keyboard injection with SendInput.

One path for everything. The Hyprland backend splits pointer (Wayland
virtual pointer) from keys and wheel (X11 XTEST) because VRoid runs under
Proton there; natively on Windows the real input stream serves all three.

Text goes in as KEYEVENTF_UNICODE, one UTF-16 unit per event. Deriving a
virtual key from a character is not safe here: on a Japanese IME keyboard
layout VkKeyScanW('.') answers "Z with the Hankaku modifier", so "0.250"
arrived as "0z250". Named keys (Return, BackSpace, ctrl+a, ...) do use
virtual keys - that is what they are. Unicode input also passes straight
through a switched-on IME, which a number box would otherwise swallow.

Everything goes to whichever window has focus, so every call re-checks that
it is VRoid (or one of VRoid's own dialogs) first.

All public coordinates are *window-relative* pixels unless you pass
space="layout" (screen pixels) or space="image" (needs the Shot).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time

from . import key_input, mouse_input, send, user32
from . import window as W

BUTTONS = {"left": "left", "right": "right", "middle": "middle",
           1: "left", 2: "middle", 3: "right"}

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
_DOWN = {"left": 0x0002, "right": 0x0008, "middle": 0x0020}
_UP = {"left": 0x0004, "right": 0x0010, "middle": 0x0040}
WHEEL_DELTA = 120

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

_SAFE = True   # module-level guard: verify VRoid focus before every action


def set_safety(on: bool) -> None:
    global _SAFE
    _SAFE = on


def _guard() -> None:
    if not _SAFE:
        return
    if not W.is_vroid_focused() and W.dismiss_screensaver():
        W.focus()
    W.assert_vroid_focused()


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

def _virtual_desktop() -> tuple[int, int, int, int]:
    SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
    SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
    return (user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))


def _abs_move(x: float, y: float) -> None:
    """Absolute move across the whole virtual desktop, so a second monitor
    (or one left of or above the primary) is reachable."""
    vx, vy, vw, vh = _virtual_desktop()
    nx = int(round((x - vx) * 65535 / max(vw - 1, 1)))
    ny = int(round((y - vy) * 65535 / max(vh - 1, 1)))
    send(mouse_input(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
                     | MOUSEEVENTF_VIRTUALDESK, nx, ny))


def _cursor() -> tuple[float, float]:
    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return float(p.x), float(p.y)


def _glide(lx: float, ly: float, steps: int, pause: float) -> None:
    cx, cy = _cursor()
    for i in range(1, steps + 1):
        t = i / steps
        _abs_move(cx + (lx - cx) * t, cy + (ly - cy) * t)
        time.sleep(pause)


def move(x: float, y: float, space: str = "window", shot=None) -> None:
    lx, ly = _resolve(x, y, space, shot)
    _abs_move(lx, ly)


def click(x: float, y: float, button: str = "left", space: str = "window",
          shot=None, settle: float = 0.35, moves: int = 3) -> None:
    """Move (in a few steps, so hover states fire) then click."""
    _guard()
    lx, ly = _resolve(x, y, space, shot)
    b = BUTTONS.get(button, "left")
    _glide(lx, ly, moves, 0.012)
    time.sleep(0.06)
    send(mouse_input(_DOWN[b]))
    time.sleep(0.02)
    send(mouse_input(_UP[b]))
    time.sleep(settle)


def double_click(x: float, y: float, **kw) -> None:
    click(x, y, **kw)
    time.sleep(0.05)
    click(x, y, settle=kw.get("settle", 0.35))


def drag(x1: float, y1: float, x2: float, y2: float, button: str = "left",
         space: str = "window", shot=None, steps: int = 24,
         settle: float = 0.4) -> None:
    """Press at (x1,y1), glide to (x2,y2), release. Used for sliders."""
    _guard()
    ax, ay = _resolve(x1, y1, space, shot)
    bx, by = _resolve(x2, y2, space, shot)
    b = BUTTONS.get(button, "left")
    _abs_move(ax, ay)
    time.sleep(0.12)
    send(mouse_input(_DOWN[b]))
    time.sleep(0.12)
    for i in range(1, steps + 1):
        t = i / steps
        _abs_move(ax + (bx - ax) * t, ay + (by - ay) * t)
        time.sleep(0.016)
    time.sleep(0.15)
    send(mouse_input(_UP[b]))
    time.sleep(settle)


def _wheel(flag: int, delta: int, ticks: int) -> None:
    for _ in range(abs(ticks)):
        send(mouse_input(flag, data=delta))
        time.sleep(0.07)


def scroll(ticks: int, x: float | None = None, y: float | None = None,
           space: str = "window", shot=None, settle: float = 0.3,
           backend: str = "x11") -> None:
    """Wheel scroll. Negative = up/away, positive = down.

    `backend` is the Hyprland module's choice between XTEST and the virtual
    pointer; there is only one wheel here and it is ignored.
    """
    _guard()
    if x is not None and y is not None:
        move(x, y, space, shot)
        time.sleep(0.2)
    # Windows counts a positive delta as away from the user - the opposite
    # sign convention to this API's.
    _wheel(MOUSEEVENTF_WHEEL, -WHEEL_DELTA if ticks > 0 else WHEEL_DELTA, ticks)
    time.sleep(settle)


def hscroll(ticks: int, x: float | None = None, y: float | None = None,
            space: str = "window", shot=None, settle: float = 0.3) -> None:
    """Horizontal wheel. Negative = left, positive = right."""
    _guard()
    if x is not None and y is not None:
        move(x, y, space, shot)
        time.sleep(0.2)
    _wheel(MOUSEEVENTF_HWHEEL, WHEEL_DELTA if ticks > 0 else -WHEEL_DELTA, ticks)
    time.sleep(settle)


# --- keyboard ---------------------------------------------------------------
#
# Names follow X keysyms, as the Hyprland backend and the vroid_key tool
# document; compared case-insensitively.

_VK = {
    "return": 0x0D, "enter": 0x0D, "escape": 0x1B, "esc": 0x1B, "tab": 0x09,
    "backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "space": 0x20,
    "home": 0x24, "end": 0x23, "prior": 0x21, "pageup": 0x21,
    "next": 0x22, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "ctrl": 0x11, "control": 0x11, "control_l": 0x11, "control_r": 0x11,
    "shift": 0x10, "shift_l": 0x10, "shift_r": 0x10,
    "alt": 0x12, "alt_l": 0x12, "alt_r": 0x12,
    "super": 0x5B, "meta": 0x5B, "super_l": 0x5B, "win": 0x5B,
    **{f"f{n}": 0x6F + n for n in range(1, 13)},
}
# Keys whose scan code carries the E0 prefix; without the flag, Delete and
# the arrows arrive as their numeric-keypad twins.
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B}


def _vk(name: str) -> tuple[int, list[int]]:
    """(virtual key, modifiers the layout needs) for a key name."""
    low = name.lower()
    if low in _VK:
        return _VK[low], []
    if len(name) == 1 and name.isascii() and name.isalnum():
        return ord(name.upper()), []
    if len(name) == 1:
        r = user32.VkKeyScanW(ord(name))
        if r != -1:
            state = (r >> 8) & 0xFF
            if state & ~0x07:
                # Hankaku / kana state bits (see the module docstring):
                # not a key this layout can press on its own.
                raise ValueError(f"no plain key for {name!r} on this layout; "
                                 f"use type_text")
            mods = ([0x10] if state & 1 else []) + ([0x11] if state & 2 else []) \
                + ([0x12] if state & 4 else [])
            return r & 0xFF, mods
    raise ValueError(f"no virtual key for {name!r}")


def _kv(vk: int, up: bool = False) -> object:
    MAPVK_VK_TO_VSC = 0
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0)
    return key_input(vk, user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC), flags)


def _tap(vk: int, mods: list[int], hold: float = 0.02) -> None:
    for m in mods:
        send(_kv(m))
    send(_kv(vk))
    time.sleep(hold)
    send(_kv(vk, up=True))
    for m in reversed(mods):
        send(_kv(m, up=True))


def type_text(text: str, delay_ms: int = 22) -> None:
    """Type a literal string into the focused widget (KEYEVENTF_UNICODE)."""
    _guard()
    for ch in text:
        if ch == "\n":
            key("Return")
            continue
        units = ch.encode("utf-16-le")
        for i in range(0, len(units), 2):          # surrogate pairs: two events
            u = int.from_bytes(units[i:i + 2], "little")
            send(key_input(0, u, KEYEVENTF_UNICODE),
                 key_input(0, u, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        time.sleep(delay_ms / 1000.0)
    time.sleep(0.15)


def key(name: str, mods: list[str] | None = None, times: int = 1) -> None:
    """Press a named key: Return, Escape, Tab, BackSpace, a, ... with mods."""
    _guard()
    vk, needed = _vk(name)
    mod_vks = [_vk(m)[0] for m in (mods or [])]
    mod_vks += [m for m in needed if m not in mod_vks]
    for _ in range(times):
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
