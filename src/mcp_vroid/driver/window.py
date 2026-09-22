"""Find / launch / focus the VRoid Studio window through hyprctl."""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass

STEAM_APPID = "1486350"

# VRoid runs under Proton, so it is an XWayland window. Hyprland reports
#   class = "steam_app_1486350"   title = "VRoid Studio 2.14.0"
CLASS_HINTS = ("vroidstudio", "vroid studio", f"steam_app_{STEAM_APPID}")
TITLE_HINTS = ("vroid",)

WORKSPACE = 9  # dedicated workspace we drive VRoid on


def hyprctl(*args: str) -> str:
    return subprocess.run(
        ["hyprctl", *args], capture_output=True, text=True, check=True
    ).stdout


def hyprctl_json(*args: str):
    return json.loads(hyprctl("-j", *args))


def dispatch(lua: str) -> str:
    """Hyprland >= 0.55 takes Lua dispatchers, e.g.
    hyprctl dispatch 'hl.dsp.window.close()'.
    """
    out = hyprctl("dispatch", lua)
    if out.strip().startswith("error"):
        raise RuntimeError(f"hyprctl dispatch failed: {lua}\n{out}")
    return out


def _win_expr(win: "Window | None") -> str:
    return f"hl.get_window('address:{win.address}')" if win else "nil"


def notify(msg: str, ms: int = 3000, color: str = "rgb(88aaff)") -> None:
    subprocess.run(["hyprctl", "notify", "1", str(ms), color, msg],
                   capture_output=True)


@dataclass
class Window:
    address: str
    cls: str
    title: str
    x: int
    y: int
    w: int
    h: int
    workspace: int
    focused: bool
    fullscreen: bool = False

    @property
    def geometry(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) in Hyprland *layout* (logical) coordinates."""
        return (self.x, self.y, self.w, self.h)

    def to_layout(self, x: float, y: float) -> tuple[float, float]:
        """Window-relative point -> layout point."""
        return (self.x + x, self.y + y)


def _clients() -> list[dict]:
    return hyprctl_json("clients")


def _mk(c: dict) -> Window:
    return Window(
        address=c["address"], cls=c.get("class", ""), title=c.get("title", ""),
        x=c["at"][0], y=c["at"][1], w=c["size"][0], h=c["size"][1],
        workspace=c["workspace"]["id"], focused=c.get("focusHistoryID", -1) == 0,
        fullscreen=bool(c.get("fullscreen", 0)),
    )


def find_window() -> Window | None:
    """Return the VRoid Studio window, or None. Never matches anything else."""
    for c in _clients():
        cls = (c.get("class") or "").lower()
        title = (c.get("title") or "").lower()
        if any(h in cls for h in CLASS_HINTS) or any(h in title for h in TITLE_HINTS):
            # Guard against e.g. a browser tab named "VRoid": require the
            # window class to look like the game, or an exact-ish title.
            if any(h in cls for h in CLASS_HINTS) or title.startswith("vroid studio"):
                return _mk(c)
    return None


def find_dialog(titles: tuple[str, ...]) -> dict | None:
    """A top-level window whose title is one of `titles` (lower-case), or None.

    The file dialogs VRoid opens (Wine's, under Proton) are windows of their
    own, not part of VRoid's geometry.
    """
    for c in _clients():
        if (c.get("title") or "").strip().lower() in titles:
            return c
    return None


def is_vroid_focused() -> bool:
    try:
        a = hyprctl_json("activewindow")
    except subprocess.CalledProcessError:
        return False
    if not a or "class" not in a:
        return False
    cls = (a.get("class") or "").lower()
    title = (a.get("title") or "").lower()
    return any(h in cls for h in CLASS_HINTS) or title.startswith("vroid studio")


def assert_vroid_focused() -> None:
    if not is_vroid_focused():
        a = hyprctl_json("activewindow")
        raise RuntimeError(
            "refusing to act: focused window is not VRoid Studio "
            f"(class={a.get('class')!r} title={a.get('title')!r})"
        )


def kill() -> None:
    """End VRoid Studio outright; unsaved work is lost."""
    subprocess.run(["pkill", "-f", "VRoidStudio.exe"], capture_output=True)


def launch() -> None:
    subprocess.Popen(
        ["steam", f"steam://rungameid/{STEAM_APPID}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


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


# --- workspace juggling -----------------------------------------------------

def active_workspace() -> int:
    return hyprctl_json("activeworkspace")["id"]


def park(win: Window, workspace: int = WORKSPACE) -> None:
    """Move VRoid to its own workspace without switching to it."""
    if win.workspace != workspace:
        dispatch(f"hl.dsp.window.move({{ workspace = {workspace}, "
                 f"silent = true, window = {_win_expr(win)} }})")
        time.sleep(0.3)


def enter(workspace: int = WORKSPACE) -> int:
    """Switch to the driving workspace; returns the workspace we came from."""
    prev = active_workspace()
    if prev != workspace:
        dispatch(f"hl.dsp.focus({{ workspace = {workspace} }})")
        time.sleep(0.3)
    return prev


def leave(prev: int) -> None:
    if active_workspace() != prev:
        dispatch(f"hl.dsp.focus({{ workspace = {prev} }})")


def dismiss_screensaver() -> bool:
    """Close an idle screensaver overlay if one grabbed the session.

    Only ever closes a window whose class contains "screensaver" - the same
    thing any keypress would do, but without typing into an unknown window.
    """
    for c in _clients():
        if "screensaver" in (c.get("class") or "").lower():
            dispatch(f"hl.dsp.window.close({{ window = "
                     f"hl.get_window('address:{c['address']}') }})")
            time.sleep(1.0)
            return True
    return False


def focus(win: Window | None = None) -> Window:
    win = win or find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    dispatch(f"hl.dsp.focus({{ window = {_win_expr(win)} }})")
    time.sleep(0.25)
    return find_window() or win


def fullscreen(win: Window | None = None) -> Window:
    """Make VRoid maximised/fullscreen so geometry is stable across runs."""
    win = focus(win)
    if not win.fullscreen:
        dispatch("hl.dsp.window.fullscreen()")
        time.sleep(0.6)
    return find_window() or win


def prepare(timeout: float = 240.0) -> tuple[Window, int]:
    """Launch if needed, park on our workspace, switch there, focus, maximise.

    Returns (window, previous_workspace) so the caller can restore.
    """
    win = launch_and_wait(timeout)
    dismiss_screensaver()
    park(win)
    prev = enter()
    win = fullscreen(win)
    assert_vroid_focused()
    return win, prev
