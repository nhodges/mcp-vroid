"""High-level VRoid Studio flows built on window/capture/locate/input.

Everything here follows the same shape: act, screenshot, assert on what the
screenshot says. Callers get the Shot back so they can Read the PNG.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from . import locate as L
from .backend import capture as C
from .backend import input as I
from .backend import window as W
from .capture import Shot
from .paths import OUT

# Anchors expressed as fractions of the captured window, measured on
# 2560x1440 (Hyprland scale 1.25). VRoid lays its UI out in fixed pixels
# pinned to the window edges - it does not stretch with the window - so
# _ax/_ay turn a fraction back into the measured pixel and keep its distance
# from the nearer edge. On a 2560x1440 capture that is the same number the
# plain fraction gives; on any other size it is the one that still hits.
REF_W, REF_H = 2560, 1440
F_CLOSE_X = (0.0090, 0.0160)      # top-left "x" that leaves a full-screen view
F_EXPORT_ICON = (0.9625, 0.0160)  # share/upload icon in the editor toolbar
F_PARAM_VALUE_X = 0.9785          # x of the numeric box on a Parameters row
TAB_Y = 0.0160                    # y of the Face/Hairstyle/... tab strip

TABS = ("Face", "Hairstyle", "Body", "Outfit", "Accessories", "Look")


def shot(tag: str = "") -> Shot:
    if sys.platform == "win32":
        # A background Unity window cannot be captured, and a flow that
        # lost the foreground half-way would otherwise die on its next look.
        W.ensure_focus()
    return C.grab_window(tag=tag)


def _frac(s: Shot, fx: float, fy: float) -> tuple[int, int]:
    return int(s.image.width * fx), int(s.image.height * fy)


def edge_px(frac: float, size: int, ref: int) -> int:
    """A fraction measured on a `ref`-px axis -> pixel on a `size`-px axis,
    keeping the distance to the nearer edge (left/top below 0.5, else
    right/bottom)."""
    px = int(ref * frac)
    return px if frac <= 0.5 else size - (ref - px)


def _ax(s: Shot, fx: float) -> int:
    return edge_px(fx, s.image.width, REF_W)


def _ay(s: Shot, fy: float) -> int:
    return edge_px(fy, s.image.height, REF_H)


def _dx(fx: float) -> int:
    """A horizontal distance (not a position) measured as a fraction."""
    return int(REF_W * fx)


def _dy(fy: float) -> int:
    return int(REF_H * fy)


def _click_frac(s: Shot, fx: float, fy: float, **kw) -> None:
    I.click(_ax(s, fx), _ay(s, fy), space="image", shot=s, **kw)


def wait_for(pred, timeout: float = 30.0, poll: float = 1.0, tag: str = ""):
    """Re-screenshot until pred(shot) is truthy; returns (shot, value)."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = shot(tag)
        v = pred(last)
        if v:
            return last, v
        time.sleep(poll)
    return last, None


def wait_for_text(needle: str, timeout: float = 30.0, region=None, **kw):
    return wait_for(lambda s: L.find_text(s, needle, region=region, **kw),
                    timeout=timeout)


def close_vroid() -> bool:
    """Quit VRoid Studio; False if it was not running. UNSAVED WORK IS LOST.

    Only ever ends VRoid's own process - no window-manager shortcut that
    could land on another application.
    """
    if W.find_window() is None:
        return False
    if sys.platform == "win32":
        return W.close()
    import subprocess
    subprocess.run(["pkill", "-f", "VRoidStudio.exe"], capture_output=True)
    time.sleep(5)
    return True


# --- screen identification --------------------------------------------------

def current_screen(s: Shot | None = None) -> str:
    """One of: start, editor, export_vrm, hair_editor, unknown."""
    s = s or shot()
    top = s.crop((0, 0, s.image.width, int(s.image.height * 0.05)))
    words = {L._norm(m.text) for m in L.all_text(top)}
    if {"vroidediting", "vroid"} & words or "recentlyedited" in words:
        return "start"
    if "editpreset" in words or {"edit", "preset"} <= words:
        return "hair_editor"
    if {"export", "vrm"} <= words:
        return "export_vrm"
    if {"face", "hairstyle", "body"} <= words:
        return "editor"
    if L.find_text(s, "Recently Edited", region=(0, 0, s.image.width // 3,
                                                 s.image.height // 4)):
        return "start"
    return "unknown"


# --- start screen -----------------------------------------------------------

def new_character(base: str = "Fem", timeout: float = 60.0) -> Shot:
    """From the start screen: Create New -> pick a base -> land in the editor."""
    s = shot("start-screen")
    m = L.find_text(s, "Create", region=(0, 0, s.image.width // 2,
                                         s.image.height // 2))
    if m is None:
        raise RuntimeError("no 'Create New' tile - not on the start screen?")
    # the "+" card sits directly above its caption
    I.click(m.center[0], m.center[1] - _dy(0.076),
            space="image", shot=s)
    time.sleep(1.5)

    s, m = wait_for_text(base, timeout=20, exact=True)
    if m is None:
        raise RuntimeError(f"base chooser never offered {base!r}")
    # the thumbnail sits above its label
    I.click(m.center[0], m.center[1] - _dy(0.07),
            space="image", shot=s)

    s, ok = wait_for(lambda sh: current_screen(sh) == "editor",
                     timeout=timeout, poll=2.0, tag="new-character")
    if not ok:
        raise RuntimeError("editor did not open after picking a base")
    time.sleep(4)  # let the 3D view finish loading
    return shot("editor-ready")


# --- editor -----------------------------------------------------------------

def open_tab(name: str) -> Shot:
    s = shot()
    m = L.find_text(s, name, region=(0, 0, _ax(s, 0.4), _ay(s, 0.04)))
    if m is None:
        raise RuntimeError(f"tab {name!r} not found in the tab strip")
    I.click(*m.center, space="image", shot=s)
    time.sleep(2.0)
    return shot(f"tab-{name.lower()}")


def find_param_row(label: str, s: Shot | None = None):
    """(shot, Match) for a Parameters label in the right-hand panel."""
    s = s or shot()
    region = (int(s.image.width * 0.68), 0, s.image.width, s.image.height)
    return s, L.find_text(s, label, region=region)


def set_slider(label: str, value: float, s: Shot | None = None) -> Shot:
    """Set a Parameters slider by typing into its numeric box.

    Far more reliable than dragging the handle: the box takes an exact value
    and the app clamps it. drag_slider() is the fallback when a control has
    no numeric box.
    """
    s, m = find_param_row(label, s)
    if m is None:
        raise RuntimeError(f"no parameter row labelled {label!r}")
    x = _ax(s, F_PARAM_VALUE_X)
    I.click(x, m.center[1], space="image", shot=s)
    time.sleep(0.3)
    I.clear_field()
    I.type_text(f"{value:.3f}")
    I.key("Return")
    time.sleep(1.0)
    return shot(f"slider-{L._norm(label)}")


def drag_slider(label: str, fraction: float, s: Shot | None = None) -> Shot:
    """Drag a slider handle to `fraction` (0..1) of its track."""
    s, m = find_param_row(label, s)
    if m is None:
        raise RuntimeError(f"no parameter row labelled {label!r}")
    x0, x1 = _ax(s, 0.8900), _ax(s, 0.9830)     # track ends, measured
    y = m.center[1] + _dy(0.0167)
    handle = L.find_color_blobs(s, min_w=8, min_h=8,
                                region=(x0 - 20, y - 12, x1 + 20, y + 12))
    start_x = handle[0].center[0] if handle else (x0 + x1) // 2
    I.drag(start_x, y, int(x0 + (x1 - x0) * fraction), y,
           space="image", shot=s)
    return shot(f"drag-{L._norm(label)}")


def set_hex_color(label: str, hexcode: str) -> Shot:
    """Set a '#RRGGBB' colour box (Main Color, Highlight Color, ...)."""
    s, m = find_param_row(label, None)
    if m is None:
        raise RuntimeError(f"no colour row labelled {label!r}")
    x = _ax(s, 0.9435)
    I.click(x, m.center[1] + _dy(0.0167),
            space="image", shot=s)
    time.sleep(0.3)
    I.clear_field()
    I.type_text(hexcode.lstrip("#").upper())
    I.key("Return")
    time.sleep(0.8)
    return shot(f"color-{L._norm(label)}")


def open_hair_editor(part: str = "Front") -> Shot:
    """Hairstyle tab -> part rail -> Custom -> Create New -> Edit Hairstyle."""
    open_tab("Hairstyle")
    s = shot()
    # rail icons run down the far left; index 1 is the first hair part
    rail_x = _ax(s, 0.0094)
    rail_y = _ay(s, 0.0861)                 # 2nd icon
    I.click(rail_x, rail_y, space="image", shot=s)
    time.sleep(1.5)

    s = shot("hair-part")
    m = L.find_text(s, "Custom", region=(0, 0, int(s.image.width * 0.2),
                                         int(s.image.height * 0.15)))
    if m is None:
        raise RuntimeError("no Custom sub-tab in the hair part panel")
    I.click(*m.center, space="image", shot=s)
    time.sleep(1.5)

    s = shot("hair-custom")
    m = L.find_text(s, "Create", region=(0, 0, int(s.image.width * 0.2),
                                         int(s.image.height * 0.4)))
    if m is None:
        raise RuntimeError("no 'Create New' custom-item tile")
    I.click(*m.center, space="image", shot=s)
    time.sleep(2.5)

    s, m = wait_for_text("Edit Hairstyle", timeout=20)
    if m is None:
        raise RuntimeError("'Edit Hairstyle' button never appeared")
    I.click(*m.center, space="image", shot=s)
    s, ok = wait_for(lambda sh: current_screen(sh) == "hair_editor",
                     timeout=25, tag="hair-editor")
    if not ok:
        raise RuntimeError("hair editor did not open")
    return s


def close_hair_editor(save: bool = False) -> Shot:
    s = shot()
    _click_frac(s, *F_CLOSE_X)
    time.sleep(1.5)
    s, m = wait_for_text("Close Hairstyle Editor", timeout=10)
    if m:
        label = "Save as new item" if save else "without"
        s = shot()
        b = L.find_text(s, label)
        if b is None:
            raise RuntimeError(f"confirm dialog has no {label!r} button")
        I.click(*b.center, space="image", shot=s)
        time.sleep(2.5)
    return shot("hair-editor-closed")


# --- export -----------------------------------------------------------------

def export_vrm(out_path: str | Path, avatar_name: str = "SpikeAvatar",
               creators: str = "mcp-vroid",
               timeout: float = 180.0, version: str = "1.0") -> Path:
    """Walk the whole Export-as-VRM flow and return the written file.

    Editor toolbar -> "Export as VRM" -> Export -> VRM Settings (metadata,
    required fields) -> Export -> Wine save dialog (type a Z:\\ path) -> Save.
    """
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    s = open_export_screen()

    # The primary button is white-on-blue; tesseract loses it, so match the
    # button chrome instead. It sits under the accordions, so it moves down
    # the panel as they are opened - search the whole column.
    b = L.find_button(s, region=(int(s.image.width * 0.68), 0,
                                 s.image.width, s.image.height))
    if b is not None:
        I.click(*b.center, space="image", shot=s)
    elif not L.find_text(s, "Settings", exact=True):
        # no pill and no modal over it (a re-run finds the modal still open)
        raise RuntimeError("no accent Export button on the export screen")

    # "Settings" alone, and exactly: a loose "VRM Settings" also matches the
    # "VRM" of the "Export as VRM" title, i.e. before the modal is up.
    s, m = wait_for_text("Settings", timeout=25, exact=True)
    if m is None:
        raise RuntimeError("VRM Settings dialog never opened")

    select_export_format(version)
    _fill_vrm_settings(avatar_name, creators)

    # scroll the dialog to the bottom and hit its Export button
    s = shot("vrm-settings-filled")
    cx, cy = s.image.width // 2, int(s.image.height * 0.62)
    b = None
    for _ in range(8):
        I.scroll(10, cx, cy, space="image", shot=s)
        s = shot("vrm-settings-scroll")
        b = L.find_button(s, region=(int(s.image.width * 0.38),
                                     int(s.image.height * 0.2),
                                     int(s.image.width * 0.63),
                                     s.image.height))
        if b:
            break
    if b is None:
        raise RuntimeError(
            "no enabled Export button in VRM Settings - it stays grey until "
            f"Avatar Name and Creators are filled in; see {s.path}")
    I.click(*b.center, space="image", shot=s)

    _save_dialog(out_path, timeout=60)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if out_path.exists() and out_path.stat().st_size > 1024:
            size = out_path.stat().st_size
            time.sleep(2.0)
            if out_path.stat().st_size == size:
                shot("export-done")
                return out_path
        time.sleep(2.0)
    raise TimeoutError(f"{out_path} was never written")


def open_export_screen() -> Shot:
    """Editor toolbar share icon -> "Export as VRM" -> the export screen.

    A no-op when that screen is already up, so a caller can open it, adjust
    the Reduce Polygons / Materials / Texture Atlas options by hand, and then
    run export_vrm() from there.
    """
    s = shot("editor-before-export")
    if current_screen(s) == "export_vrm":
        return s
    _click_frac(s, *F_EXPORT_ICON)
    time.sleep(1.5)

    s, m = wait_for_text("Export", timeout=15,
                         region=(int(s.image.width * 0.70), 0,
                                 s.image.width, int(s.image.height * 0.2)))
    if m is None:
        raise RuntimeError("toolbar menu has no 'Export as VRM' entry")
    I.click(*m.center, space="image", shot=s)

    s, ok = wait_for(lambda sh: current_screen(sh) == "export_vrm",
                     timeout=30, poll=1.5, tag="export-screen")
    if not ok:
        raise RuntimeError("'Export as VRM' screen never appeared")
    return s


def select_export_format(version: str = "1.0") -> None:
    """Pick the VRM spec version radio at the top of the VRM Settings modal.

    "1.0" is VRoid's default, so that case is a no-op; "0.0" clicks the
    VRM0.0 radio (the circle sits ~20 image px left of its caption).
    """
    v = str(version).strip()
    if v in ("1.0", "1", "vrm1.0", "VRM1.0"):
        return
    if v not in ("0.0", "0", "vrm0.0", "VRM0.0"):
        raise ValueError(f"unknown VRM export format {version!r} (use 1.0 or 0.0)")
    s = shot("vrm-export-format")
    m = None
    for spelling in ("VRM0.0", "VRMO.0", "VRMO.O", "VRM0.O"):   # OCR's 0/O
        m = m or L.find_text(s, spelling, exact=True)
    m = m or L.find_text(s, "VRM0.0") or L.find_text(s, "VRMO.0")
    if m is None:
        raise RuntimeError("no VRM0.0 radio in the VRM Settings modal")
    I.click(m.left - _dx(0.008), m.center[1],
            space="image", shot=s)
    time.sleep(0.6)


def _fill_vrm_settings(avatar_name: str, creators: str) -> None:
    """Avatar Name and Creators are required; everything else keeps defaults.

    Both captions are matched *exactly* on their distinguishing word: a loose
    match on "Avatar" also hits the "Avatar Information" heading, and a loose
    "Creator" also hits "Creator Copyright" - both of which silently type into
    the wrong box and leave Export greyed out.

    The form changes with the export format: VRM1.0 asks for "Avatar Name"
    and "Creators", VRM0.0 for "Title" and "Creator". Each field is tried
    under its VRM1.0 caption first.
    """
    for words, text in ((("Name", "Title"), avatar_name),
                        (("Creators", "Creator"), creators)):
        word = words[0]
        s = shot(f"vrm-field-{word.lower()}")
        title = L.find_text(s, "Settings", region=(
            int(s.image.width * 0.30), 0, int(s.image.width * 0.70),
            int(s.image.height * 0.35)))
        cx = title.center[0] if title else s.image.width // 2
        region = (int(s.image.width * 0.36), 0, int(s.image.width * 0.64),
                  s.image.height)
        hits = []
        for word in words:
            hits = hits or L.find_text(s, word, exact=True, all_matches=True,
                                       region=region)
        if not hits:
            raise RuntimeError(f"VRM Settings has no {words!r} caption")
        m = min(hits, key=lambda h: h.top)      # topmost = the caption we want
        I.click(cx, m.center[1] + _dy(0.0271),
                space="image", shot=s)
        time.sleep(0.3)
        I.clear_field()
        I.type_text(text)
        time.sleep(0.4)

    s = shot("vrm-fields-filled")
    for word, text in (("Name", avatar_name), ("Creators", creators)):
        if not L.find_text(s, text.split("-")[0][:8]):
            raise RuntimeError(
                f"{word} field did not take {text!r} - see {s.path}")


def to_wine_path(p: str | Path) -> str:
    r"""/home/you/x -> Z:\home\you\x  (the Proton prefix maps Z:\ to /)."""
    return "Z:" + str(Path(p).resolve()).replace("/", "\\")


def _save_dialog(out_path: Path, timeout: float = 60.0) -> None:
    """Type the Windows path into Wine's Save dialog and confirm.

    The dialog opens with the file-name field focused and its text selected,
    so typing replaces it; no click needed in the common case.
    """
    if sys.platform == "win32":
        return _save_dialog_native(out_path, timeout)
    win = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        win = _save_dialog_window()
        if win:
            break
        time.sleep(1.0)
    if win is None:
        raise RuntimeError("Wine save dialog never appeared")
    time.sleep(1.0)

    wine_path = to_wine_path(out_path)
    I.type_text(wine_path)
    time.sleep(0.5)
    s = C.grab_screen("save-dialog")
    if not L.find_text(s, out_path.stem, region=(0, 0, int(s.image.width * 0.4),
                                                 int(s.image.height * 0.3))):
        # focus was elsewhere: click the File name box, then retype
        m = L.find_text(s, "name", region=(0, 0, int(s.image.width * 0.4),
                                           int(s.image.height * 0.3)))
        if m is None:
            raise RuntimeError("save dialog has no 'File name:' field")
        I.click(m.center[0] + int(s.image.width * 0.065), m.center[1],
                space="image", shot=s)
        I.clear_field()
        I.type_text(wine_path)
        time.sleep(0.5)
        s = C.grab_screen("save-dialog-retyped")

    # Return activates the dialog's default button. Clicking is the fallback,
    # and it must pick the *rightmost* "Save": the "Save in:" label at the top
    # left matches the same needle and swallows the click.
    I.key("Return")
    time.sleep(2.0)
    if _save_dialog_window() is not None:
        s = C.grab_screen("save-dialog-still-open")
        hits = L.find_text(s, "Save", all_matches=True,
                           region=(0, 0, int(s.image.width * 0.4),
                                   int(s.image.height * 0.3)))
        button = max(hits, key=lambda h: h.left) if hits else None
        if button is None:
            raise RuntimeError(f"save dialog has no Save button; see {s.path}")
        I.click(*button.center, space="image", shot=s)
        time.sleep(2.0)


def _save_dialog_native(out_path: Path, timeout: float = 60.0) -> None:
    """Windows: type the path into the native Save dialog and confirm.

    The dialog is a separate top-level window; W.find_save_dialog() only
    accepts the one VRoid itself owns, and the input guard only lets keys
    through to that one. The "File name" box opens focused with its text
    selected, so the path replaces it; what actually landed in the box is
    read back from the control before Return is pressed.
    """
    dlg = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        dlg = W.find_save_dialog()
        if dlg:
            break
        time.sleep(1.0)
    if dlg is None:
        raise RuntimeError("the Windows save dialog never appeared")
    time.sleep(1.0)
    W.focus()                       # focuses the dialog while it is up

    target = str(out_path)
    for attempt in range(2):
        I.clear_field()
        I.type_text(target, delay_ms=8)
        time.sleep(0.4)
        if W.save_dialog_filename(dlg).strip().lower() == target.lower():
            break
    else:
        raise RuntimeError(
            "save dialog's File name box did not take the path: it holds "
            f"{W.save_dialog_filename(dlg)!r}, wanted {target!r}")
    I.key("Return")

    deadline = time.time() + 15
    while time.time() < deadline:
        if W.find_save_dialog() is None:
            return
        time.sleep(0.5)
    raise RuntimeError(
        "save dialog is still open after Return - it may be asking to "
        "overwrite, or the folder does not exist; take a "
        "whole-screen capture and look")


def _save_dialog_window():
    if sys.platform == "win32":
        return W.find_save_dialog()
    for c in W.hyprctl_json("clients"):
        if (c.get("title") or "").strip().lower() in ("export", "save as", "save"):
            return c
    return None


def default_out() -> Path:
    return OUT / "spike.vrm"


# --- parameter panel with scrolling ----------------------------------------

F_PANEL_SCROLL = (0.93, 0.60)     # a point over the right-hand panel
PANEL_REGION = (0.68, 0.03, 0.97, 1.0)


def _panel_region(s: Shot):
    w, h = s.image.width, s.image.height
    x0, y0, x1, y1 = PANEL_REGION
    return (int(w * x0), int(h * y0), int(w * x1), int(h * y1))


def scroll_panel(ticks: int, s: Shot | None = None) -> None:
    """Wheel the right-hand panel (pointer parked over it first)."""
    s = s or shot()
    I.scroll(ticks, *_frac(s, *F_PANEL_SCROLL), space="image", shot=s)


def _find_label(s: Shot, label: str):
    """Match a parameter label; tesseract swaps word order on some rows
    ("Size Head"), so fall back to matching the distinctive word."""
    reg = _panel_region(s)
    m = L.find_text(s, label, region=reg, exact=True)
    if m:
        return m
    words = label.replace("(", " ").replace(")", " ").split()
    hits = []
    for w in words:
        if len(w) < 3:
            continue
        hits.append(L.find_text(s, w, region=reg, exact=True, all_matches=True) or [])
    if not hits or not all(hits):
        return None
    # rows where every word lands on the same line
    for a in hits[0]:
        if all(any(abs(b.center[1] - a.center[1]) < 12 for b in hs) for hs in hits[1:]):
            return a
    return None


def find_param(label: str, max_pages: int = 10):
    """Scroll the Parameters panel from the top until `label` is visible.
    Returns (shot, Match) with the row in a safe (not edge-clipped) place."""
    s = shot()
    scroll_panel(-80, s)
    time.sleep(0.4)
    for _ in range(max_pages):
        s = shot(f"find-{L._norm(label)}")
        m = _find_label(s, label)
        if m and m.center[1] < s.image.height * 0.93:
            return s, m
        scroll_panel(8, s)
        time.sleep(0.5)
    raise RuntimeError(f"parameter {label!r} not found in the panel")


def set_param(label: str, value: float) -> Shot:
    """Scroll to a Parameters row and type `value` into its numeric box."""
    s, m = find_param(label)
    x = _ax(s, F_PARAM_VALUE_X)
    I.click(x, m.center[1], space="image", shot=s)
    time.sleep(0.3)
    I.clear_field()
    I.type_text(f"{value:.3f}")
    I.key("Return")
    time.sleep(0.8)
    s2 = shot(f"param-{L._norm(label)}")
    return s2


def read_param(label: str) -> str:
    """OCR the numeric box of a row (after find_param)."""
    s, m = find_param(label)
    box = s.crop((_ax(s, 0.963), m.center[1] - 14, _ax(s, 0.993), m.center[1] + 14))
    ms = L.all_text(box)
    return " ".join(t.text for t in ms)


def set_color_param(label: str, hexcode: str) -> Shot:
    """Scroll to a colour row (swatch + hex box under the label) and set it."""
    s, m = find_param(label)
    x = _ax(s, 0.9435)
    I.click(x, m.center[1] + _dy(0.0167), space="image", shot=s)
    time.sleep(0.3)
    I.clear_field()
    I.type_text(hexcode.lstrip("#").upper())
    I.key("Return")
    time.sleep(0.8)
    return shot(f"color-{L._norm(label)}")


def rail_icon(index: int) -> Shot:
    """Click the N-th (0-based) sub-category icon on the far-left rail."""
    s = shot()
    x = _ax(s, 0.0094)
    y = _dy(0.0556 + 0.0347 * index)
    I.click(x, y, space="image", shot=s)
    time.sleep(1.5)
    return shot(f"rail-{index}")


def apply_params(spec: dict | str | Path) -> list[str]:
    """Apply a {tab: {label: value}} spec (dict or path to JSON).

    Values: number -> slider numeric box; "#RRGGBB" -> colour hex box;
    {"rail": n} entry selects a sub-category icon before the labels that
    follow it (tabs are applied in order, labels in insertion order).
    Returns the capture paths taken.
    """
    import json
    if not isinstance(spec, dict):
        spec = json.loads(Path(spec).read_text())
    paths = []
    for tab, params in spec.items():
        open_tab(tab)
        for label, value in params.items():
            if label.startswith("_rail"):
                paths.append(str(rail_icon(int(value)).path))
                continue
            if isinstance(value, str) and value.startswith("#"):
                paths.append(str(set_color_param(label, value).path))
            else:
                paths.append(str(set_param(label, float(value)).path))
    return paths


# --- viewport camera --------------------------------------------------------
# Measured: wheel +N over the viewport zooms OUT, -N zooms in; right-drag
# orbits (~400 image px = 90 deg yaw); middle-drag pans the model with the
# pointer.

F_VIEWPORT = (0.50, 0.50)


def cam_zoom(ticks: int, s: Shot | None = None) -> None:
    s = s or shot()
    I.scroll(ticks, *_frac(s, *F_VIEWPORT), space="image", shot=s)


def cam_orbit(dx: int, dy: int = 0, s: Shot | None = None) -> None:
    s = s or shot()
    x, y = _frac(s, *F_VIEWPORT)
    I.drag(x, y, x + dx, y + dy, button="right", space="image", shot=s)


def cam_pan(dx: int, dy: int, s: Shot | None = None) -> None:
    s = s or shot()
    x, y = _frac(s, *F_VIEWPORT)
    I.drag(x, y, x + dx, y + dy, button="middle", space="image", shot=s)


def cam_full_body(s: Shot | None = None) -> Shot:
    """From VRoid's default editor framing: zoom out and pan so the whole
    model fits the viewport."""
    cam_zoom(30)
    time.sleep(0.5)
    cam_pan(0, -700)
    time.sleep(0.8)
    return shot("cam-full-body")


def cam_turn(deg: float) -> Shot:
    cam_orbit(int(400 * deg / 90))
    time.sleep(0.8)
    return shot(f"cam-turn-{int(deg)}")


# --- Face tab left rail -----------------------------------------------------
# The rail's icon pitch is ~50 image px (2560x1440) but not perfectly even;
# locate a category by clicking candidate slots and reading the panel title.

FACE_RAIL_HINT_Y = {          # image px on a 2560x1440 capture
    "Face Sets": 80, "Eyes Sets": 130, "Irises": 180, "Eye Highlights": 230,
    "Scleras": 265, "Eyebrows": 330, "Eyelids": 380, "Eyeliner": 430,
    "Eyelashes": 465, "Nose": 505, "Mouth": 555, "Mouth Inside": 605,
    "Lips": 655, "Cheeks": 680, "Skin": 730,
}


def _panel_title(s: Shot) -> str:
    return " ".join(m.text for m in L.all_text(
        s.crop((50, _dy(0.031), 600, _dy(0.063)))))


def face_category(name: str) -> Shot:
    """Select a Face-tab left-rail sub-category by panel title."""
    hint = FACE_RAIL_HINT_Y.get(name)
    ys = [hint] if hint else []
    ys += [y for y in range(80, 760, 25) if y not in ys]
    x = 24
    for y in ys:
        s = shot()
        I.click(x, y, space="image", shot=s)
        time.sleep(1.2)
        s = shot(f"face-cat-{L._norm(name)}")
        if L._norm(name) in L._norm(_panel_title(s)):
            return s
    raise RuntimeError(f"face category {name!r} not found on the rail")


# --- Hairstyle tab ----------------------------------------------------------

HAIR_RAIL_HINT_Y = {          # image px on a 2560x1440 capture (Hairstyle tab)
    "Hairstyle Sets": 60, "Front": 125, "Back": 172, "Overall Hair": 220,
    "Extensions": 269, "Side": 317, "Ahoge": 365, "Extra": 412,
    "Hair Base": 461,
}


def hair_category(name: str) -> Shot:
    """Select a Hairstyle-tab left-rail sub-category, verified by panel title."""
    hint = HAIR_RAIL_HINT_Y.get(name)
    ys = [hint] if hint else []
    ys += [y for y in range(60, 500, 24) if y not in ys]
    for y in ys:
        s = shot()
        I.click(24, y, space="image", shot=s)
        time.sleep(1.2)
        s = shot(f"hair-cat-{L._norm(name)}")
        if L._norm(name) in L._norm(_panel_title(s)):
            return s
    raise RuntimeError(f"hair category {name!r} not found on the rail")


def select_none_preset() -> Shot:
    """Click the dashed 'none' tile (first tile) of the current preset grid.

    Scrolls the grid to the top first; the none tile sits at ~(120, 216)
    image px in the two-column preset grid.
    """
    s = shot()
    for _ in range(4):
        I.scroll(-12, 170, 500, space="image", shot=s)
        time.sleep(0.25)
    s = shot()
    I.click(120, 216, space="image", shot=s)
    time.sleep(2)
    return shot("preset-none")


def save_project_as(out_path: str | Path, timeout: float = 60.0) -> Path:
    """Save As (Ctrl+Shift+S) into an explicit .vroid path via the Wine dialog.

    Same dialog as the VRM export, so the same rules apply: the file-name
    field opens focused with its contents selected, a Windows path (Z:\\...)
    goes straight in, and Return fires the default button.
    """
    out_path = Path(out_path).resolve()
    if out_path.suffix.lower() != ".vroid":
        out_path = out_path.with_suffix(".vroid")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    I.hotkey("ctrl+shift+s")
    time.sleep(1.5)
    _save_dialog(out_path, timeout=timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if out_path.exists() and out_path.stat().st_size > 1024:
            size = out_path.stat().st_size
            time.sleep(2.0)
            if out_path.stat().st_size == size:
                shot("project-saved")
                return out_path
        time.sleep(2.0)
    raise TimeoutError(f"{out_path} was never written")


def save_project() -> None:
    """Hamburger -> Save. Silent overwrite when the project already has a
    file; the first ever save instead opens the Wine dialog (drive it like
    export_vrm does)."""
    s = shot()
    I.click(29, 23, space="image", shot=s)
    time.sleep(1.2)
    s = shot("menu")
    m = L.find_text(s, "Save", region=(0, 0, 600, 700))
    if m is None:
        raise RuntimeError("hamburger menu did not show a Save entry")
    I.click(*m.center, space="image", shot=s)
    time.sleep(3)
