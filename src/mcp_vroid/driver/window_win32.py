"""Find / launch / focus the VRoid Studio window through the Win32 API.

The Windows counterpart of window.py (Hyprland). It keeps the same names so
actions.py, cli.py and the server do not care which one they got:

    Window, find_window, is_vroid_focused, assert_vroid_focused, launch,
    wait_for_window, launch_and_wait, focus, fullscreen, prepare,
    active_workspace, park, enter, leave, dismiss_screensaver

Windows has no workspaces to park the app on, so park/enter/leave are no-ops
and "fullscreen" means *maximised*. Coordinates are physical screen pixels of
the virtual desktop (the process is made per-monitor DPI aware on import), and
a Window's x/y/w/h describe its **client** rectangle - the part Unity draws
into and the part capture_win32 screenshots - so "window-relative" means the
same thing here as it does on Hyprland.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

STEAM_APPID = "1486350"
EXE_NAME = "vroidstudio.exe"

# Unity's player window:  class = "UnityWndClass"  title = "VRoid Studio"
CLASS_HINTS = ("unitywndclass",)
TITLE_HINTS = ("vroid",)

WORKSPACE = 0  # no workspaces on Windows; kept for the shared interface

# The common file dialog VRoid opens for Export / Save As.
DIALOG_CLASS = "#32770"
DIALOG_TITLES = ("export", "save as", "save")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# LRESULT / HANDLE-sized returns must not be truncated to a C int.
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD,
                                     wintypes.BOOL]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                wintypes.LPARAM]
user32.FindWindowExW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR,
                                 wintypes.LPCWSTR]
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD)]
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                      wintypes.LPARAM)
user32.EnumWindows.argtypes = [_EnumWindowsProc, wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND, _EnumWindowsProc,
                                    wintypes.LPARAM]

GW_OWNER = 4
GA_ROOTOWNER = 3
SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
WM_CLOSE, WM_GETTEXT, WM_GETTEXTLENGTH = 0x0010, 0x000D, 0x000E
SMTO_ABORTIFHUNG = 0x0002
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000


def _dpi_aware() -> None:
    """Per-monitor-v2 DPI awareness, so every rectangle the API hands back is
    in physical pixels - the same pixels a screenshot is made of and SendInput
    aims at - whatever scaling each monitor uses."""
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except AttributeError:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


_dpi_aware()


# --- small Win32 helpers ----------------------------------------------------

def _text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _pid(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _exe(pid: int) -> str:
    """Full image path of a process, or '' if it cannot be opened."""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return ""
        return buf.value
    finally:
        kernel32.CloseHandle(h)


def _top_level() -> list[int]:
    out: list[int] = []

    @_EnumWindowsProc
    def cb(hwnd, _lparam):
        out.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return out


def _client_rect(hwnd: int) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the client area in physical screen pixels."""
    rc = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, rc.right - rc.left, rc.bottom - rc.top


def foreground() -> int:
    return user32.GetForegroundWindow() or 0


@dataclass
class Window:
    address: str      # the HWND, as hex - what Hyprland calls the address
    cls: str
    title: str
    x: int            # client-area origin, physical screen px
    y: int
    w: int            # client-area size, physical px
    h: int
    workspace: int
    focused: bool
    fullscreen: bool = False   # maximised
    pid: int = 0

    @property
    def hwnd(self) -> int:
        return int(self.address, 16)

    @property
    def geometry(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) of the client area in screen pixels."""
        return (self.x, self.y, self.w, self.h)

    def to_layout(self, x: float, y: float) -> tuple[float, float]:
        """Window-relative point -> screen point."""
        return (self.x + x, self.y + y)

    def contains(self, sx: float, sy: float) -> bool:
        """Is this screen point inside the client rectangle?"""
        return (self.x <= sx < self.x + self.w
                and self.y <= sy < self.y + self.h)


def _mk(hwnd: int) -> Window:
    x, y, w, h = _client_rect(hwnd)
    return Window(
        address=f"{hwnd:#x}", cls=_class(hwnd), title=_text(hwnd),
        x=x, y=y, w=w, h=h, workspace=WORKSPACE,
        focused=foreground() == hwnd,
        fullscreen=bool(user32.IsZoomed(hwnd)), pid=_pid(hwnd),
    )


def _is_vroid(hwnd: int) -> bool:
    """A visible Unity player window that belongs to VRoidStudio.exe.

    The executable name is the real test: a browser tab or a folder window
    titled "VRoid Studio" must never match.
    """
    if not user32.IsWindowVisible(hwnd):
        return False
    if _class(hwnd).lower() not in CLASS_HINTS:
        return False
    return Path(_exe(_pid(hwnd))).name.lower() == EXE_NAME


def find_window() -> Window | None:
    """Return the VRoid Studio window, or None. Never matches anything else."""
    for hwnd in _top_level():
        if _is_vroid(hwnd):
            return _mk(hwnd)
    return None


def is_vroid_focused() -> bool:
    fg = foreground()
    return bool(fg) and _is_vroid(fg)


def assert_vroid_focused() -> None:
    """Raise unless input would land on VRoid: its window, or the native
    save dialog it owns (keys only - see input_win32 for the pointer rule)."""
    if not (is_vroid_focused() or is_save_dialog_focused()):
        fg = foreground()
        raise RuntimeError(
            "refusing to act: focused window is not VRoid Studio "
            f"(class={_class(fg)!r} title={_text(fg)!r})"
        )


# --- the file dialog VRoid opens for Export / Save As ------------------------

def find_save_dialog(win: Window | None = None) -> int | None:
    """HWND of VRoid's own native save dialog, or None.

    It has to be a common dialog (#32770) with one of the expected titles,
    created by the VRoid process, and owned by the VRoid window. Nothing else
    qualifies - this is the only window besides VRoid's that input may go to.
    """
    win = win or find_window()
    if win is None:
        return None
    for hwnd in _top_level():
        if not user32.IsWindowVisible(hwnd) or _class(hwnd) != DIALOG_CLASS:
            continue
        if _text(hwnd).strip().lower() not in DIALOG_TITLES:
            continue
        if _pid(hwnd) != win.pid:
            continue
        if (user32.GetWindow(hwnd, GW_OWNER) or 0) != win.hwnd and \
                (user32.GetAncestor(hwnd, GA_ROOTOWNER) or 0) != win.hwnd:
            continue
        return hwnd
    return None


def is_save_dialog_focused() -> bool:
    dlg = find_save_dialog()
    return dlg is not None and foreground() == dlg


def save_dialog_filename(dlg: int) -> str:
    """Read (never write) the text of the dialog's "File name" edit box."""
    best = ""

    @_EnumWindowsProc
    def cb(hwnd, _lparam):
        nonlocal best
        if _class(hwnd) == "Edit" and user32.IsWindowVisible(hwnd):
            n = ctypes.c_size_t(0)
            user32.SendMessageTimeoutW(hwnd, WM_GETTEXTLENGTH, 0, 0,
                                       SMTO_ABORTIFHUNG, 500, ctypes.byref(n))
            buf = ctypes.create_unicode_buffer(n.value + 2)
            user32.SendMessageTimeoutW(
                hwnd, WM_GETTEXT, n.value + 1,
                ctypes.cast(buf, ctypes.c_void_p).value,
                SMTO_ABORTIFHUNG, 500, ctypes.byref(n))
            if len(buf.value) >= len(best):
                best = buf.value
        return True

    user32.EnumChildWindows(dlg, cb, 0)
    return best


# --- launch / close ---------------------------------------------------------

def launch() -> None:
    """Start VRoid through Steam, as the Linux backend does.

    MCP_VROID_EXE overrides this with a direct path to VRoidStudio.exe, for
    installs that Steam's URL handler cannot reach.
    """
    exe = os.environ.get("MCP_VROID_EXE")
    if exe:
        subprocess.Popen([exe], cwd=str(Path(exe).parent),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
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


def close(timeout: float = 15.0) -> bool:
    """Close VRoid Studio: ask its own window to close, then end its own
    process if it is still there (it asks about unsaved work, which nobody
    is going to answer). UNSAVED WORK IS LOST. Returns False if it was not
    running. Touches no other window and no other process.
    """
    win = find_window()
    if win is None:
        return False
    pid = win.pid
    user32.PostMessageW(win.hwnd, WM_CLOSE, 0, 0)
    h = kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
    if not h:
        time.sleep(timeout)
        return True
    try:
        if kernel32.WaitForSingleObject(h, int(timeout * 1000)) != 0:
            kernel32.TerminateProcess(h, 0)
            kernel32.WaitForSingleObject(h, 10000)
    finally:
        kernel32.CloseHandle(h)
    return True


# --- workspace juggling (none on Windows) -----------------------------------

def active_workspace() -> int:
    return WORKSPACE


def park(win: Window, workspace: int = WORKSPACE) -> None:
    """No workspaces on Windows; VRoid stays where the user put it."""


def enter(workspace: int = WORKSPACE) -> int:
    return WORKSPACE


def leave(prev: int) -> None:
    """Nothing to switch back to."""


def dismiss_screensaver() -> bool:
    """A Windows screensaver or lock screen cannot be dismissed from here;
    the focus guard simply refuses to act while one is up."""
    return False


# --- focus ------------------------------------------------------------------

def _set_foreground(hwnd: int) -> bool:
    """Bring `hwnd` to the foreground without touching any other window.

    Windows only lets the foreground process hand focus away, so a plain
    SetForegroundWindow from a background server is often refused. Attaching
    our input queue to the current foreground thread for the duration of the
    call is the documented way round that; it sends no input anywhere.
    """
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if foreground() == hwnd:
        return True
    user32.SetForegroundWindow(hwnd)
    if foreground() == hwnd:
        return True
    me = kernel32.GetCurrentThreadId()
    fg = foreground()
    other = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    target = user32.GetWindowThreadProcessId(hwnd, None)
    attached = []
    for tid in {other, target} - {0, me}:
        if user32.AttachThreadInput(me, tid, True):
            attached.append(tid)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        for tid in attached:
            user32.AttachThreadInput(me, tid, False)
    if foreground() == hwnd:
        return True
    # Last resort, and only for VRoid's own main window: a window that is
    # restored from minimised is given the foreground by the shell itself.
    if _is_vroid(hwnd):
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        time.sleep(0.3)
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.5)
    return foreground() == hwnd


def focus(win: Window | None = None) -> Window:
    win = win or find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    # While VRoid's own save dialog is up, the dialog is what must keep focus.
    dlg = find_save_dialog(win)
    target = dlg or win.hwnd
    for _ in range(3):
        if _set_foreground(target):
            break
        time.sleep(0.3)
    time.sleep(0.25)
    return find_window() or win


def ensure_focus() -> None:
    """Take the foreground back if something else grabbed it; a no-op (and
    no delay) when VRoid or its save dialog already has it."""
    if not (is_vroid_focused() or is_save_dialog_focused()):
        focus()


def fullscreen(win: Window | None = None) -> Window:
    """Maximise VRoid (on whichever monitor it is on) so geometry is stable
    across runs."""
    win = focus(win)
    if not win.fullscreen and find_save_dialog(win) is None:
        user32.ShowWindow(win.hwnd, SW_MAXIMIZE)
        time.sleep(0.8)
    return find_window() or win


def prepare(timeout: float = 240.0) -> tuple[Window, int]:
    """Launch if needed, focus, maximise.

    Returns (window, previous_workspace) like the Hyprland backend; the
    second value is always 0 here.
    """
    win = launch_and_wait(timeout)
    win = fullscreen(win)
    assert_vroid_focused()
    return win, WORKSPACE
