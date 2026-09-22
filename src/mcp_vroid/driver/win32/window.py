"""Find / launch / focus the VRoid Studio window with EnumWindows and DWM.

Mirrors the Hyprland window module name for name. Windows has no workspace
to park VRoid on, so "workspace" here is the window the user was in: enter()
remembers it, leave() gives it back. SendInput moves the real cursor, so
while a session drives VRoid the desktop is not the user's to use.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import time
import winreg
from dataclasses import dataclass
from pathlib import Path

from . import dwmapi, key_input, send, user32

STEAM_APPID = "1486350"
VROID_CLASS = "UnityWndClass"
TITLE_PREFIX = "vroid studio"
DIALOG_CLASS = "#32770"          # the common file dialog, and message boxes

# The "driving workspace". There is none; nothing a caller compares against
# it (a window handle) is ever equal to None.
WORKSPACE = None

SW_RESTORE, SW_MAXIMIZE = 9, 3
KEYEVENTF_KEYUP = 0x0002
VK_MENU = 0x12


@dataclass
class Window:
    address: str      # hex HWND, the Hyprland module's "address"
    cls: str
    title: str
    x: int
    y: int
    w: int
    h: int
    workspace: int    # the monitor index is the closest thing; 0 here
    focused: bool
    fullscreen: bool = False   # maximised

    @property
    def hwnd(self) -> int:
        return int(self.address, 16)

    @property
    def geometry(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) of the client area, in physical screen pixels."""
        return (self.x, self.y, self.w, self.h)

    def to_layout(self, x: float, y: float) -> tuple[float, float]:
        """Window-relative point -> screen point."""
        return (self.x + x, self.y + y)


# --- raw window facts -------------------------------------------------------

def _text(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _pid(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _frame(hwnd: int) -> tuple[int, int, int, int]:
    """Visible bounds, title bar included. GetWindowRect adds the invisible
    resize border - 8 px on each side of a maximised window, which puts the
    neighbouring monitor into a capture and every click 8 px off."""
    r = wt.RECT()
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    if dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
                                    ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def _client(hwnd: int) -> tuple[int, int, int, int]:
    """The client area in screen pixels: the window minus its title bar.

    This is what the VRoid geometry means. Hyprland shows VRoid fullscreen
    with no decoration, and every anchor in actions.py and docs/ui-map.md
    was measured on that picture - the tab strip "at y ~ 1.6 % of the
    height", the top 5 % that current_screen() reads. A maximised Windows
    window keeps its ~23 px title bar; counting it pushes the tab labels
    half out of that 5 % band and the editor is never recognised.
    """
    r = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    p = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(p))
    return (p.x, p.y, r.right - r.left, r.bottom - r.top)


def _top_level_windows() -> list[int]:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def _is_vroid(hwnd: int) -> bool:
    return _class(hwnd) == VROID_CLASS and _text(hwnd).lower().startswith(TITLE_PREFIX)


def _mk(hwnd: int) -> Window:
    x, y, w, h = _client(hwnd)
    return Window(address=hex(hwnd), cls=_class(hwnd), title=_text(hwnd),
                  x=x, y=y, w=w, h=h, workspace=0,
                  focused=user32.GetForegroundWindow() == hwnd,
                  fullscreen=bool(user32.IsZoomed(hwnd)))


# --- finding ----------------------------------------------------------------

def find_window() -> Window | None:
    """Return the VRoid Studio window, or None. Never matches anything else:
    the Unity window class *and* the title prefix both have to agree, so a
    browser tab called "VRoid Studio" is not it."""
    for hwnd in _top_level_windows():
        if _is_vroid(hwnd):
            return _mk(hwnd)
    return None


def find_dialog(titles: tuple[str, ...]) -> dict | None:
    """A top-level window of VRoid's own process whose title is one of
    `titles` (lower-case), or None."""
    win = find_window()
    if win is None:
        return None
    pid = _pid(win.hwnd)
    for hwnd in _top_level_windows():
        if hwnd != win.hwnd and _pid(hwnd) == pid \
                and _text(hwnd).strip().lower() in titles:
            x, y, w, h = _frame(hwnd)
            return {"address": hex(hwnd), "class": _class(hwnd),
                    "title": _text(hwnd), "at": [x, y], "size": [w, h]}
    return None


WM_SETTEXT, WM_GETTEXT, WM_GETTEXTLENGTH, WM_COMMAND = 0x000C, 0x000D, 0x000E, 0x0111
IDOK = 1
EDT_FILE_NAME = 1001     # the file-name box of the common Save dialog

user32.SendMessageW.argtypes = (wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.PostMessageW.argtypes = (wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.GetDlgItem.restype = wt.HWND


def _children(hwnd: int) -> list[int]:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        found.append(h)
        return True

    user32.EnumChildWindows(hwnd, cb, 0)
    return found


def _control_text(hwnd: int) -> str:
    n = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.SendMessageW(hwnd, WM_GETTEXT, n + 1, ctypes.addressof(buf))
    return buf.value


def fill_save_dialog(dialog: dict, path) -> None:
    """Put `path` into a Windows Save dialog and confirm it - as controls,
    not as keystrokes and OCR.

    The common dialog is made of standard controls, so the file-name box
    can be written with WM_SETTEXT and read back with WM_GETTEXT (an exact
    check, where OCR of a 12 px field is not), and the default button is
    IDOK whatever the Windows display language calls it ("保存(&S)" here).
    The address bar also carries control id 1001, hence the class check.

    Raises if the box is missing, does not take the path, or the dialog is
    still open afterwards (Windows answers a bad path with a message box of
    its own).
    """
    hwnd = int(dialog["address"], 16)
    box = next((h for h in _children(hwnd)
                if _class(h) == "Edit" and user32.GetDlgCtrlID(h) == EDT_FILE_NAME), None)
    if box is None:
        raise RuntimeError("save dialog has no file-name box (Edit, id 1001)")
    target = str(Path(path).resolve())
    buf = ctypes.create_unicode_buffer(target)
    user32.SendMessageW(box, WM_SETTEXT, 0, ctypes.addressof(buf))
    got = _control_text(box)
    if got != target:
        raise RuntimeError(f"save dialog file-name box holds {got!r}, not {target!r}")
    ok = user32.GetDlgItem(hwnd, IDOK)
    user32.PostMessageW(hwnd, WM_COMMAND, IDOK, ok or 0)
    deadline = time.time() + 10
    while time.time() < deadline:
        if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
            return
        time.sleep(0.3)
    raise RuntimeError(f"save dialog still open after confirming {target!r}")


def _foreground_is_vroid_process() -> bool:
    fg = user32.GetForegroundWindow()
    win = find_window()
    return bool(fg) and win is not None and _pid(fg) == _pid(win.hwnd)


def is_vroid_focused() -> bool:
    """True when the foreground window belongs to VRoid - the main window or
    one of its own dialogs (the file dialogs are separate top-level windows,
    and typing a path into them is the point)."""
    return _foreground_is_vroid_process()


def assert_vroid_focused() -> None:
    if not is_vroid_focused():
        fg = user32.GetForegroundWindow()
        raise RuntimeError(
            "refusing to act: focused window is not VRoid Studio "
            f"(class={_class(fg)!r} title={_text(fg)!r})")


# --- launching --------------------------------------------------------------

def _installed_exe() -> Path | None:
    """Newest VRoid Studio from the installer's Uninstall entries."""
    best: tuple[tuple[int, ...], Path] | None = None
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in roots:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, i)) as k:
                        name = winreg.QueryValueEx(k, "DisplayName")[0]
                        if not name.lower().replace(" ", "").startswith("vroidstudio"):
                            continue
                        loc = Path(winreg.QueryValueEx(k, "InstallLocation")[0])
                        ver = winreg.QueryValueEx(k, "DisplayVersion")[0]
                except OSError:
                    continue
                exe = loc / "VRoidStudio.exe"
                key = tuple(int(p) for p in ver.split(".") if p.isdigit())
                if exe.exists() and (best is None or key > best[0]):
                    best = (key, exe)
    return best[1] if best else None


def kill() -> None:
    """End VRoid Studio outright; unsaved work is lost. Only the process that
    owns the VRoid window - another program's "VRoidStudio.exe" in its
    command line is not a match here, as it would be for pkill -f."""
    win = find_window()
    if win is not None:
        subprocess.run(["taskkill", "/PID", str(_pid(win.hwnd)), "/F"],
                       capture_output=True)


def launch() -> None:
    """MCP_VROID_EXE, else the newest installed VRoid Studio, else Steam."""
    exe = os.environ.get("MCP_VROID_EXE")
    path = Path(exe) if exe else _installed_exe()
    if path is not None:
        subprocess.Popen([str(path)], cwd=str(path.parent),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        os.startfile(f"steam://rungameid/{STEAM_APPID}")


def wait_for_window(timeout: float = 180.0, poll: float = 2.0) -> Window:
    deadline = time.time() + timeout
    while time.time() < deadline:
        w = find_window()
        if w and w.w > 200 and w.h > 200:
            return w
        time.sleep(poll)
    raise TimeoutError(f"VRoid Studio window did not appear within {timeout}s")


def launch_and_wait(timeout: float = 240.0) -> Window:
    w = find_window()
    if w:
        return w
    launch()
    return wait_for_window(timeout)


# --- "workspace" juggling ---------------------------------------------------

def active_workspace() -> int:
    """The foreground window's handle."""
    return int(user32.GetForegroundWindow() or 0)


def park(win: Window, workspace=WORKSPACE) -> None:
    """Nothing to park on; VRoid stays where the user put it."""


def enter(workspace=WORKSPACE) -> int:
    """Returns the window to hand back to later. The switch itself happens
    when focus() raises VRoid."""
    return active_workspace()


def leave(prev: int) -> None:
    if prev and user32.IsWindow(prev) and active_workspace() != prev:
        _set_foreground(prev)


def dismiss_screensaver() -> bool:
    """A locked workstation cannot be unlocked from here and a running
    screensaver belongs to the secure desktop; report that nothing was
    closed, and let the focus check refuse to act."""
    return False


# --- focus ------------------------------------------------------------------

def _set_foreground(hwnd: int) -> bool:
    """SetForegroundWindow, which Windows refuses to a background process
    unless it sent the last input event. Holding Alt across the call makes it
    so; releasing Alt *after* the switch lands the key-up in the new window,
    so the window we left does not see a lone Alt and open its menu bar."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if user32.SetForegroundWindow(hwnd) and user32.GetForegroundWindow() == hwnd:
        return True
    send(key_input(VK_MENU))
    try:
        user32.SetForegroundWindow(hwnd)
    finally:
        send(key_input(VK_MENU, flags=KEYEVENTF_KEYUP))
    time.sleep(0.15)
    return user32.GetForegroundWindow() == hwnd


def focus(win: Window | None = None) -> Window:
    win = win or find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    if not _set_foreground(win.hwnd):
        raise RuntimeError("Windows refused to bring VRoid Studio to the front")
    time.sleep(0.25)
    return find_window() or win


def fullscreen(win: Window | None = None) -> Window:
    """Maximise VRoid so geometry is stable across runs."""
    win = focus(win)
    if not win.fullscreen:
        user32.ShowWindow(win.hwnd, SW_MAXIMIZE)
        time.sleep(0.6)
    return find_window() or win


def prepare(timeout: float = 240.0) -> tuple[Window, int]:
    """Launch if needed, remember the foreground window, focus, maximise.

    Returns (window, previous_foreground) so the caller can restore.
    """
    win = launch_and_wait(timeout)
    dismiss_screensaver()
    park(win)
    prev = enter()
    win = fullscreen(win)
    assert_vroid_focused()
    return win, prev
