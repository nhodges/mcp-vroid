"""MCP server (stdio) that drives VRoid Studio's GUI on Hyprland/Wayland.

Every tool is a thin, well-described wrapper over `mcp_vroid.driver`, which
does the actual see -> locate -> act loop: `grim` screenshots, tesseract OCR
and cv2 blob/template matching to find widgets, a `zwlr_virtual_pointer_v1`
client for the mouse and X11 XTEST for keys and the wheel.

Design notes for anyone reading the tool list:

* Coordinates are **image pixels of a capture of the VRoid window** by
  default (`space="image"`), which is exactly what `vroid_screenshot`,
  `vroid_find_text` and `vroid_find_button` hand back. Do not convert
  anything yourself.
* Nothing types or clicks unless VRoid Studio is the focused window; the
  guard lives in the driver and every acting tool re-checks it.
* The server parks VRoid on its own Hyprland workspace (9) and remembers the
  workspace the user was on, so `vroid_release` can put them back.
"""

from __future__ import annotations

import functools
import os
import shutil
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

import anyio
from mcp.server.mcpserver import Image, MCPServer
from PIL import Image as PILImage
from pydantic import BaseModel, Field

from .session_env import ensure_session_env

# Must happen before the driver modules resolve paths or shell out.
_FILLED_ENV = ensure_session_env()

from .driver import actions as A  # noqa: E402
from .driver import locate as L  # noqa: E402
from .driver.backend import capture as C  # noqa: E402
from .driver.backend import input as I  # noqa: E402
from .driver.backend import window as W  # noqa: E402
from .driver.paths import CAPTURES, OUT, VPOINTER  # noqa: E402

server = MCPServer(
    name="vroid",
    version="0.1.0",
    instructions=(
        "Drives the VRoid Studio desktop app (Steam; Proton on Hyprland, or "
        "native on Windows) by screenshotting it, locating widgets with "
        "OCR, and injecting real pointer/keyboard events.\n\n"
        "The working loop is: vroid_launch -> vroid_screenshot (LOOK at the "
        "image) -> vroid_find_text / vroid_find_button to get coordinates -> "
        "vroid_click / vroid_type -> vroid_screenshot again to confirm. Never "
        "click a coordinate you have not just seen in a fresh screenshot: the "
        "UI reflows, and modals (e.g. 'Close Hairstyle Editor') silently "
        "swallow clicks.\n\n"
        "All x/y values are image pixels of the most recent window capture "
        "unless you pass space='layout'. Prefer the high-level tools "
        "(vroid_open_tab, vroid_set_slider, vroid_set_color, "
        "vroid_export_vrm) over raw clicks where they fit - they locate their "
        "own targets and verify the result."
    ),
)


# --------------------------------------------------------------------------
# session state: which workspace the user was on before we took over
# --------------------------------------------------------------------------

_prev_workspace: int | None = None
MAX_IMAGE_EDGE = int(os.environ.get("MCP_VROID_MAX_IMAGE_PX", "1600"))


async def _blocking(fn, *args, **kwargs):
    """Run a blocking driver call off the event loop."""
    return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))


def _require_window() -> W.Window:
    win = W.find_window()
    if win is None:
        raise RuntimeError(
            "VRoid Studio is not running (no Hyprland window with class "
            "steam_app_1486350 / title 'VRoid Studio ...'). Call vroid_launch "
            "first."
        )
    return win


def _ensure_ready() -> W.Window:
    """Focus VRoid the way the driver expects before any input is injected.

    Parks the window on workspace 9, remembers the workspace the user was on
    (once, so vroid_release can restore it), switches there, focuses and
    fullscreens so window geometry is stable, and closes an idle screensaver
    overlay if one grabbed the session. Raises if VRoid is not running or
    cannot be focused - it never types into somebody else's window.
    """
    global _prev_workspace
    win = _require_window()
    W.dismiss_screensaver()
    W.park(win)
    prev = W.enter()
    if _prev_workspace is None and prev != W.WORKSPACE:
        _prev_workspace = prev
    win = W.fullscreen(win)
    W.assert_vroid_focused()
    return win


def _win_dict(win: W.Window | None) -> dict[str, Any]:
    if win is None:
        return {"present": False}
    return {
        "present": True,
        "address": win.address,
        "class": win.cls,
        "title": win.title,
        "workspace": win.workspace,
        "fullscreen": win.fullscreen,
        "focused": win.focused,
        "geometry_layout": {"x": win.x, "y": win.y, "w": win.w, "h": win.h},
    }


def _windows_helpers() -> dict[str, Any]:
    """What the Windows backend depends on: SendInput and PrintWindow are
    part of the OS, so the only thing that can be missing is an OCR
    language."""
    try:
        from .driver import ocr_winrt

        lang = ocr_winrt._get_engine("eng").recognizer_language.language_tag
        ocr: dict[str, Any] = {"present": True, "language": lang}
    except Exception as e:  # report it, do not fail vroid_status
        ocr = {"present": False, "error": str(e)}
    return {"backend": "win32 (SendInput + PrintWindow)", "windows_ocr": ocr}


class Region(BaseModel):
    """A rectangle in image-pixel coordinates of a VRoid window capture."""

    x: int = Field(description="left edge, image px")
    y: int = Field(description="top edge, image px")
    w: int = Field(description="width, image px")
    h: int = Field(description="height, image px")

    def box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)


def _shrink(img: PILImage.Image) -> tuple[PILImage.Image, float]:
    """Downscale for transport; returns (image, factor applied)."""
    longest = max(img.size)
    if MAX_IMAGE_EDGE <= 0 or longest <= MAX_IMAGE_EDGE:
        return img, 1.0
    f = MAX_IMAGE_EDGE / longest
    return img.resize((int(img.width * f), int(img.height * f)),
                      PILImage.LANCZOS), f


def _png_bytes(img: PILImage.Image) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _match_dict(m: L.Match) -> dict[str, Any]:
    return {
        "text": m.text,
        "confidence": round(m.conf, 1),
        "x": m.center[0],
        "y": m.center[1],
        "box": {"x": m.left, "y": m.top, "w": m.width, "h": m.height},
    }


# --------------------------------------------------------------------------
# lifecycle
# --------------------------------------------------------------------------


@server.tool()
async def vroid_launch(
    restart: Annotated[
        bool,
        Field(description="Kill a running VRoid Studio first (UNSAVED WORK IS "
                          "LOST) and start a clean instance."),
    ] = False,
    timeout: Annotated[
        float, Field(description="Seconds to wait for the window to appear.")
    ] = 240.0,
) -> dict[str, Any]:
    """Start VRoid Studio (Steam appid 1486350, Proton) and take control of it.

    Idempotent: if the window already exists it is reused, not relaunched.
    Then the window is parked on Hyprland workspace 9, the workspace the user
    was on is remembered (vroid_release puts them back), and the window is
    focused and fullscreened so its geometry - and therefore every coordinate
    you will read off a screenshot - is stable.

    Cold start over Proton takes 30-90 s; the call blocks until the window is
    up. It does NOT wait for the start screen to finish drawing, so take a
    vroid_screenshot and look before clicking anything.
    """

    def work() -> dict[str, Any]:
        global _prev_workspace
        if restart:
            A.close_vroid()
        win, prev = W.prepare(timeout)
        if _prev_workspace is None and prev != W.WORKSPACE:
            _prev_workspace = prev
        return {
            **_win_dict(win),
            "restarted": bool(restart),
            "driving_workspace": W.WORKSPACE,
            "previous_workspace": _prev_workspace,
            "captures_dir": str(CAPTURES),
        }

    return await _blocking(work)


@server.tool()
async def vroid_status() -> dict[str, Any]:
    """Report whether VRoid Studio is running, focused, and where it sits.

    Cheap and side-effect free (no OCR, no input) - use it before anything
    else, and after anything that might have lost focus. `focused` false means
    every acting tool will refuse until vroid_launch (or any acting tool's own
    focus step) takes the window back.

    Also reports whether the external helpers this server needs are present:
    the vpointer binary (built by native/build.sh), grim, tesseract, hyprctl.
    """

    def work() -> dict[str, Any]:
        win = W.find_window()
        out: dict[str, Any] = {
            "window": _win_dict(win),
            "focused": W.is_vroid_focused(),
            "active_workspace": W.active_workspace(),
            "driving_workspace": W.WORKSPACE,
            "previous_workspace": _prev_workspace,
            "captures_dir": str(CAPTURES),
            "out_dir": str(OUT),
            "recovered_session_env": _FILLED_ENV,
            "helpers": {
                "vpointer": {"path": str(VPOINTER), "present": VPOINTER.exists()},
                "grim": bool(shutil.which("grim")),
                "tesseract": bool(shutil.which("tesseract")),
                "hyprctl": bool(shutil.which("hyprctl")),
            },
        }
        if sys.platform == "win32":
            out["helpers"] = _windows_helpers()
        if win is not None:
            try:
                out["capture_scale"] = C.output_scale()
            except Exception:  # pragma: no cover - monitor query is best effort
                pass
        return out

    return await _blocking(work)


@server.tool()
async def vroid_release() -> dict[str, Any]:
    """Hand the desktop back: switch to the workspace the user was on before.

    Leaves VRoid running on workspace 9. Call this when you are done with a
    session, or before handing control back to the human.
    """

    def work() -> dict[str, Any]:
        global _prev_workspace
        prev = _prev_workspace
        if prev is not None:
            W.leave(prev)
            _prev_workspace = None
        return {"restored_workspace": prev,
                "active_workspace": W.active_workspace()}

    return await _blocking(work)


@server.tool()
async def vroid_close() -> dict[str, Any]:
    """Quit VRoid Studio. UNSAVED WORK IS LOST - export or save first.

    Ends VRoid's own process (after asking its window to close); it never
    sends a window-manager shortcut, so no other application can be hit.
    Returns closed=false if VRoid was not running.
    """

    def work() -> dict[str, Any]:
        return {"closed": A.close_vroid()}

    return await _blocking(work)


# --------------------------------------------------------------------------
# seeing
# --------------------------------------------------------------------------


@server.tool(structured_output=False)
async def vroid_screenshot(
    region: Annotated[
        Region | None,
        Field(description="Optional crop in image px of the window capture. "
                          "Omit for the whole window."),
    ] = None,
    tag: Annotated[
        str, Field(description="Short label used in the saved filename.")
    ] = "",
    whole_screen: Annotated[
        bool,
        Field(description="Capture the whole output instead of just the VRoid "
                          "window - needed for the Wine save/export dialog, "
                          "which is a separate window."),
    ] = False,
    full_resolution: Annotated[
        bool,
        Field(description="Return the image at native resolution instead of "
                          "downscaling it for transport. Large."),
    ] = False,
) -> list[Any]:
    """Screenshot VRoid and return the image, plus the path it was saved to.

    LOOK at the returned image before you decide anything - this is the only
    way to see the app. Every capture is also written to the captures dir so
    it can be re-read later.

    Coordinate space: the reported `image_size` is the native capture size
    (2560x1440 on the reference machine) and that is the space every other
    tool means by `space="image"`. The transported image may be downscaled
    (`downscale` in the text block says by how much); if you read a coordinate
    off the picture by eye, divide it by that factor before clicking. Better:
    get coordinates from vroid_find_text / vroid_find_button, which always
    report native image px.

    Gotchas carried over from the driver: capture the WHOLE window, not a
    crop, when checking "did that work" - modals appear in the middle of the
    screen and a top-strip-only check will miss them. And do not judge change
    by the 3D viewport, which dithers every frame; watch a UI strip instead.
    """

    def work():
        _require_window()
        shot = C.grab_screen(tag) if whole_screen else C.grab_window(tag=tag)
        img = shot.image
        if region is not None:
            img = img.crop(region.box())
        native = img.size
        sent, factor = (img, 1.0) if full_resolution else _shrink(img)
        meta = {
            "path": str(shot.path),
            "image_size": {"w": native[0], "h": native[1]},
            "origin_layout": {"x": shot.ox, "y": shot.oy},
            "scale_image_px_per_layout_unit": shot.scale,
            "downscale": round(factor, 4),
            "region": region.model_dump() if region else None,
            "whole_screen": whole_screen,
        }
        note = (
            f"VRoid capture saved to {shot.path}\n"
            f"native image size {native[0]}x{native[1]} px "
            f"(this is the 'image' coordinate space)\n"
            f"transported at downscale {factor:.3f}"
            + ("" if factor == 1.0 else
               f" - multiply any coordinate you read off the picture by "
               f"{1 / factor:.3f}")
            + (f"\nregion crop applied: {region.model_dump()} (coordinates in "
               "the returned metadata are absolute image px of the full "
               "capture only if you add the region origin back)"
               if region else "")
        )
        return [Image(data=_png_bytes(sent), format="png"), note, meta]

    return await _blocking(work)


@server.tool()
async def vroid_find_text(
    query: Annotated[
        str,
        Field(description="Label to look for, e.g. 'Export', 'Hairstyle', "
                          "'Avatar Name'. Matching is case- and "
                          "punctuation-insensitive substring by default."),
    ],
    region: Annotated[
        Region | None,
        Field(description="Restrict OCR to this rectangle (image px). Strongly "
                          "recommended: OCR of a full 2560x1440 frame takes "
                          "~10 s, a panel-sized region under 2 s."),
    ] = None,
    exact: Annotated[
        bool,
        Field(description="Require the whole word to match, not a substring. "
                          "Use for captions that share a prefix with a heading "
                          "(e.g. 'Name' vs 'Avatar Name')."),
    ] = False,
    limit: Annotated[int, Field(description="Max matches to return.")] = 12,
) -> dict[str, Any]:
    """OCR the current VRoid window and return where `query` appears.

    Takes its own fresh screenshot, so coordinates are current. Results are
    image px, ordered by OCR confidence, ready to pass straight to
    vroid_click (which defaults to space='image').

    Known OCR weaknesses in this UI: small, letter-spaced or light-on-dark
    labels get split or dropped ('Export' -> 'E' + 'xport'), and white text on
    VRoid's blue primary buttons often disappears entirely - use
    vroid_find_button for those. Icons (toolbar, left rail) have no text at
    all; the README's UI map has their fractional positions.

    If nothing is found, that is information: the screen may not be the one
    you think it is, or a modal is covering it. Take a screenshot and look.
    """

    def work() -> dict[str, Any]:
        _require_window()
        shot = C.grab_window(tag="find")
        box = region.box() if region else None
        matches = L.find_text(shot, query, region=box, exact=exact,
                              all_matches=True) or []
        return {
            "query": query,
            "count": len(matches),
            "matches": [_match_dict(m) for m in matches[:limit]],
            "capture": str(shot.path),
            "image_size": {"w": shot.image.width, "h": shot.image.height},
            "space": "image",
        }

    return await _blocking(work)


@server.tool()
async def vroid_find_button(
    color: Annotated[
        Literal["primary", "disabled"],
        Field(description="'primary' finds the enabled blue #0096FA pill; "
                          "'disabled' finds the grey pill, which is the app "
                          "telling you a required field is still empty."),
    ] = "primary",
    label: Annotated[
        str | None,
        Field(description="Optional label to disambiguate when several pills "
                          "are visible; the button interior is OCR'd at high "
                          "upscale to check it."),
    ] = None,
    region: Annotated[
        Region | None,
        Field(description="Restrict the search to this rectangle (image px)."),
    ] = None,
    limit: Annotated[int, Field(description="Max blobs to return.")] = 6,
) -> dict[str, Any]:
    """Find VRoid's primary action buttons by their colour, not their text.

    VRoid's confirm buttons ('Export', 'OK', 'Create') are solid #0096FA
    pills whose white labels tesseract regularly loses, so this matches the
    button chrome. Blobs come back biggest-first, in image px, ready for
    vroid_click.

    A grey pill (`color='disabled'`) where you expected a blue one means the
    action is disabled - on the VRM Settings modal that means Avatar Name or
    Creators is still empty.
    """

    def work() -> dict[str, Any]:
        _require_window()
        shot = C.grab_window(tag="button")
        rgb = L.ACCENT if color == "primary" else (200, 200, 200)
        box = region.box() if region else None
        if label:
            m = L.find_button(shot, label=label, rgb=rgb, region=box)
            blobs = [m] if m else []
        else:
            blobs = L.find_color_blobs(shot, rgb=rgb, region=box)
        return {
            "color": color,
            "label": label,
            "count": len(blobs),
            "buttons": [_match_dict(m) for m in blobs[:limit]],
            "capture": str(shot.path),
            "space": "image",
        }

    return await _blocking(work)


# --------------------------------------------------------------------------
# acting: raw input
# --------------------------------------------------------------------------

SPACE_DOC = (
    "'image' = pixels of a window capture (what vroid_screenshot / "
    "vroid_find_* report - the default, and almost always what you want); "
    "'window' = Hyprland layout units relative to the window's top-left; "
    "'layout' = absolute Hyprland layout units of the whole output. (On "
    "Windows all three are plain pixels: of the capture, of the window's "
    "client area, and of the virtual desktop.)"
)


def _shot_for(space: str):
    return C.grab_window(tag="act") if space == "image" else None


@server.tool()
async def vroid_click(
    x: Annotated[float, Field(description="X coordinate in `space`.")],
    y: Annotated[float, Field(description="Y coordinate in `space`.")],
    space: Annotated[
        Literal["image", "window", "layout"], Field(description=SPACE_DOC)
    ] = "image",
    button: Annotated[
        Literal["left", "right", "middle"],
        Field(description="Mouse button. right/middle also orbit/pan the 3D "
                          "viewport when dragged."),
    ] = "left",
    double: Annotated[
        bool, Field(description="Send two clicks (selects a word in a text box).")
    ] = False,
) -> dict[str, Any]:
    """Click a point in the VRoid window with the real compositor cursor.

    Refuses unless VRoid Studio is the focused window; it focuses the window
    itself first (workspace 9, fullscreen) and raises rather than clicking
    into somebody else's app.

    The pointer glides to the target in a few steps so hover states fire, then
    clicks and settles ~0.35 s. Coordinates must come from a CURRENT capture -
    take a fresh vroid_screenshot or vroid_find_text right before clicking,
    because panels reflow and modals move.
    """

    def work() -> dict[str, Any]:
        _ensure_ready()
        shot = _shot_for(space)
        fn = I.double_click if double else I.click
        fn(x, y, button=button, space=space, shot=shot)
        return {"clicked": {"x": x, "y": y, "space": space, "button": button,
                            "double": double}}

    return await _blocking(work)


@server.tool()
async def vroid_drag(
    x1: Annotated[float, Field(description="Press point X in `space`.")],
    y1: Annotated[float, Field(description="Press point Y in `space`.")],
    x2: Annotated[float, Field(description="Release point X in `space`.")],
    y2: Annotated[float, Field(description="Release point Y in `space`.")],
    space: Annotated[
        Literal["image", "window", "layout"], Field(description=SPACE_DOC)
    ] = "image",
    button: Annotated[
        Literal["left", "right", "middle"],
        Field(description="left = slider handles and drawing; right = orbit "
                          "the camera (~400 image px is 90 deg of yaw); "
                          "middle = pan the model."),
    ] = "left",
) -> dict[str, Any]:
    """Press, glide and release - slider handles, the 3D camera, hair guides.

    For Parameters sliders prefer vroid_set_slider, which types an exact value
    into the row's numeric box; dragging is only for controls that have no
    numeric box. The glide is 24 interpolated steps, which is what the app
    needs to register a drag rather than a click.
    """

    def work() -> dict[str, Any]:
        _ensure_ready()
        shot = _shot_for(space)
        I.drag(x1, y1, x2, y2, button=button, space=space, shot=shot)
        return {"dragged": {"from": [x1, y1], "to": [x2, y2], "space": space,
                            "button": button}}

    return await _blocking(work)


@server.tool()
async def vroid_scroll(
    dy: Annotated[
        int,
        Field(description="Vertical wheel notches. POSITIVE scrolls DOWN "
                          "(further into a panel); over the 3D viewport, "
                          "positive zooms OUT."),
    ] = 0,
    dx: Annotated[
        int,
        Field(description="Horizontal wheel notches, positive = right. Rarely "
                          "useful; VRoid's panels scroll vertically only."),
    ] = 0,
    x: Annotated[
        float | None,
        Field(description="Park the pointer here first - the wheel goes to "
                          "whatever is under the cursor, so this decides "
                          "WHICH panel scrolls. ~(0.93w, 0.60h) is the "
                          "right-hand Parameters panel, the centre is the 3D "
                          "viewport."),
    ] = None,
    y: Annotated[float | None, Field(description="See `x`.")] = None,
    space: Annotated[
        Literal["image", "window", "layout"], Field(description=SPACE_DOC)
    ] = "image",
) -> dict[str, Any]:
    """Wheel-scroll a panel or zoom the 3D viewport.

    Sent as X11 button 4/5 (6/7 horizontally): VRoid is an XWayland client and
    ignores Wayland virtual-pointer axis events, so this is the only wheel
    that works on it.

    Long Parameters lists need this - a label that vroid_find_text cannot see
    is usually just below the fold. vroid_set_slider scrolls to its own row
    automatically, so you rarely need to do it by hand.
    """

    def work() -> dict[str, Any]:
        _ensure_ready()
        shot = _shot_for(space)
        if dy:
            I.scroll(dy, x, y, space=space, shot=shot)
        if dx:
            I.hscroll(dx, None if dy else x, None if dy else y,
                      space=space, shot=shot)
        return {"scrolled": {"dx": dx, "dy": dy, "at": [x, y], "space": space}}

    return await _blocking(work)


@server.tool()
async def vroid_type(
    text: Annotated[
        str,
        Field(description="Literal text to type. '\\n' presses Return."),
    ],
    clear_first: Annotated[
        bool,
        Field(description="Select-all + backspace before typing, so the field "
                          "is replaced rather than appended to."),
    ] = False,
) -> dict[str, Any]:
    """Type into whatever widget currently has keyboard focus.

    Click the field first (vroid_click) - this tool has no idea where the
    caret is. Keystrokes go through X11 XTEST because the Wayland virtual
    keyboard is mis-read by this Proton client (a whole string arrives as a
    single character).

    Always screenshot afterwards to confirm the text landed in the field you
    meant: VRoid's forms have several boxes with near-identical captions, and
    typing into the wrong one leaves the primary button greyed out with no
    other symptom.
    """

    def work() -> dict[str, Any]:
        _ensure_ready()
        if clear_first:
            I.clear_field()
        I.type_text(text)
        return {"typed": text, "cleared_first": clear_first}

    return await _blocking(work)


@server.tool()
async def vroid_key(
    combo: Annotated[
        str,
        Field(description="A key, optionally with modifiers, e.g. 'Return', "
                          "'Escape', 'Tab', 'BackSpace', 'ctrl+s', "
                          "'ctrl+shift+s', 'ctrl+z'. Names follow X keysyms; "
                          "'enter', 'esc', 'space', arrows are aliased."),
    ],
    times: Annotated[int, Field(description="Repeat count.")] = 1,
) -> dict[str, Any]:
    """Press a key combination in the focused VRoid widget.

    Useful ones: Return confirms a value box or a Wine dialog's default
    button; ctrl+s saves the project; ctrl+shift+s is Save As; ctrl+z/ctrl+y
    undo/redo in the editor.

    Note Escape does NOT close VRoid's hamburger menu - click elsewhere to
    dismiss it.
    """

    def work() -> dict[str, Any]:
        _ensure_ready()
        *mods, name = combo.split("+")
        I.key(name, mods=mods or None, times=times)
        return {"pressed": combo, "times": times}

    return await _blocking(work)


# --------------------------------------------------------------------------
# acting: high-level flows
# --------------------------------------------------------------------------


@server.tool()
async def vroid_open_tab(
    name: Annotated[
        str,
        Field(description="One of Face, Hairstyle, Body, Outfit, Accessories, "
                          "Look (the editor's top tab strip)."),
    ],
) -> dict[str, Any]:
    """Switch the editor to a top-level tab, located by OCR of the tab strip.

    Only works on the editor screen (not the start screen, the export screen
    or the hair editor). Waits ~2 s for the panels to redraw and returns the
    path of a verification screenshot - take a vroid_screenshot if you want to
    see the result.
    """

    def work() -> dict[str, Any]:
        _ensure_ready()
        shot = A.open_tab(name)
        return {"tab": name, "capture": str(shot.path)}

    return await _blocking(work)


@server.tool()
async def vroid_set_slider(
    label: Annotated[
        str,
        Field(description="The parameter's label as printed in the right-hand "
                          "panel, e.g. 'Fem Height', 'Head Size', "
                          "'Eye Size X'."),
    ],
    value: Annotated[
        float,
        Field(description="Value to type into the row's numeric box. Most "
                          "VRoid parameters run -1.0..1.0 with 0 centred; the "
                          "app clamps out-of-range values."),
    ],
) -> dict[str, Any]:
    """Set a Parameters slider exactly, by typing into its numeric box.

    Scrolls the right-hand panel from the top until the labelled row is
    visible (so it works for parameters below the fold), clicks the numeric
    box at the end of that row, clears it, types the value and presses Return.

    This is far more reliable than dragging the handle - use vroid_drag only
    for controls with no numeric box. Open the right tab first
    (vroid_open_tab): each tab has its own parameter list.
    """

    def work() -> dict[str, Any]:
        _ensure_ready()
        shot = A.set_param(label, value)
        return {"label": label, "value": value, "capture": str(shot.path)}

    return await _blocking(work)


@server.tool()
async def vroid_set_color(
    label: Annotated[
        str,
        Field(description="The colour row's label, e.g. 'Main Color', "
                          "'Highlight Color', 'Base Color'."),
    ],
    hex: Annotated[
        str,
        Field(description="Colour as '#RRGGBB' or 'RRGGBB'."),
    ],
) -> dict[str, Any]:
    """Set a colour swatch by typing a hex code into its #RRGGBB box.

    Scrolls the right-hand panel to the labelled row, clicks the hex field
    just below the label, replaces its contents and presses Return. Same
    caveat as sliders: the row must belong to the currently open tab and
    sub-category (left icon rail).
    """

    def work() -> dict[str, Any]:
        _ensure_ready()
        shot = A.set_color_param(label, hex)
        return {"label": label, "hex": hex.lstrip("#").upper(),
                "capture": str(shot.path)}

    return await _blocking(work)


@server.tool()
async def vroid_new_character(
    base: Annotated[
        Literal["Fem", "Masc"],
        Field(description="Which base model the 'Select a base to start with' "
                          "modal offers."),
    ] = "Fem",
) -> dict[str, Any]:
    """From the start screen: Create New -> pick a base -> land in the editor.

    Locates the 'Create New' tile by text (so it survives the Recently Edited
    grid growing), clicks the card above its caption, picks the base
    thumbnail, then waits up to a minute for the editor - the 3D viewport
    takes several seconds to appear after a base is chosen.
    """

    def work() -> dict[str, Any]:
        _ensure_ready()
        shot = A.new_character(base)
        return {"base": base, "capture": str(shot.path)}

    return await _blocking(work)


@server.tool()
async def vroid_current_screen() -> dict[str, Any]:
    """Identify which VRoid screen is on top: start, editor, export_vrm,
    hair_editor, or unknown.

    Cheap-ish (OCRs only the top strip, ~2 s) and worth calling whenever a
    flow tool fails - most failures are "you are not on the screen this tool
    expects". 'unknown' usually means a modal is up; screenshot the whole
    window and look.
    """

    def work() -> dict[str, Any]:
        _require_window()
        shot = C.grab_window(tag="screen")
        return {"screen": A.current_screen(shot), "capture": str(shot.path)}

    return await _blocking(work)


@server.tool()
async def vroid_export_vrm(
    path: Annotated[
        str,
        Field(description="Where to write the .vrm, as a normal absolute "
                          "path for this OS. On Linux it is translated to "
                          "the Proton prefix's Z:\\ mapping for the Wine "
                          "save dialog; on Windows it is typed as-is."),
    ],
    avatar_name: Annotated[
        str,
        Field(description="VRM metadata 'Avatar Name' - REQUIRED by VRoid; "
                          "the Export button stays grey until it is filled."),
    ],
    creator: Annotated[
        str,
        Field(description="VRM metadata 'Creators' - also REQUIRED."),
    ],
    version: Annotated[
        str,
        Field(description="VRM spec version to export: '1.0' (VRoid's "
                          "default) or '0.0' for the legacy VRM0.0 format."),
    ] = "1.0",
    timeout: Annotated[
        float,
        Field(description="Seconds to wait for the file to finish being "
                          "written."),
    ] = 180.0,
) -> dict[str, Any]:
    """Walk the entire Export-as-VRM flow and write a .vrm file.

    Editor toolbar share icon -> 'Export as VRM' -> the blue Export pill ->
    the VRM Settings modal (fills Avatar Name and Creators, picks the export
    format, scrolls to the bottom and clicks Export) -> Wine's save dialog
    (types a Z:\\ path and presses Return) -> waits for the file size to stop
    growing.

    Must be started from the EDITOR screen with a model loaded. Takes 30 s to
    a few minutes depending on the model. Returns the written path and its
    size; raises with the path of a diagnostic screenshot if any step fails -
    read that screenshot before retrying, since a half-finished flow usually
    leaves a modal open that the next attempt will trip over.
    """

    def work() -> dict[str, Any]:
        _ensure_ready()
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = OUT / target
        written = A.export_vrm(target, avatar_name=avatar_name,
                               creators=creator, timeout=timeout,
                               version=version)
        return {"path": str(written), "bytes": written.stat().st_size,
                "avatar_name": avatar_name, "creator": creator,
                "vrm_version": version}

    return await _blocking(work)


@server.tool()
async def vroid_save_project(
    name: Annotated[
        str | None,
        Field(description="Save As target: a bare name (written into the "
                          "server's out dir as <name>.vroid) or an absolute "
                          "Linux path. Omit to do a plain Save, which "
                          "silently overwrites the project's existing file."),
    ] = None,
    timeout: Annotated[
        float, Field(description="Seconds to wait for the file to be written.")
    ] = 60.0,
) -> dict[str, Any]:
    """Save the .vroid project - plain Save, or Save As to an explicit path.

    With `name`: presses Ctrl+Shift+S and drives Wine's save dialog the same
    way the VRM export does, then waits for the file. Without `name`: opens
    the hamburger menu and clicks Save, which overwrites the project's
    existing file and opens the Wine dialog only if the project has never
    been saved (in that case call this again WITH a name).

    Worth doing before any risky experiment: nothing else in this server
    persists your work, and vroid_launch(restart=true) discards it.
    """

    def work() -> dict[str, Any]:
        _ensure_ready()
        if name:
            target = Path(name).expanduser()
            if not target.is_absolute():
                target = OUT / target
            written = A.save_project_as(target, timeout=timeout)
            return {"saved": str(written), "bytes": written.stat().st_size,
                    "mode": "save-as"}
        A.save_project()
        return {"saved": None, "mode": "save",
                "note": "plain Save; if this project had never been saved a "
                        "Wine dialog is now open - screenshot with "
                        "whole_screen=true and check."}

    return await _blocking(work)


def main() -> None:
    """Console-script entry point: serve MCP over stdio."""
    server.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
