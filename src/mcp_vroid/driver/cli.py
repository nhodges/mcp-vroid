"""vroid-driver CLI:  python -m driver.cli <subcommand>

    launch                      launch VRoid, park it on ws 9, focus, fullscreen
    shot [tag]                  screenshot the window -> captures/NNN-tag.png
    screen                      print which screen we're on
    text [--region x,y,w,h]     dump every word tesseract sees, with centres
    find "Export"               locate text, print centre (image px)
    click X Y [--space]         click (default space: image px of a fresh shot)
    type "text"                 type into the focused widget
    key Return [--mods ctrl]    press a key
    scroll N                    wheel N notches (negative = up)
    tab Face                    open an editor tab
    slider "Fem Height" 0.6     set a Parameters value
    new-character [Fem|Masc]    start screen -> new model
    export out/spike.vrm        full Export-as-VRM walk
    export-screen               open the Export-as-VRM screen and stop there
    close                       quit VRoid Studio (unsaved work is lost)
    restore                     switch back to the workspace you came from

Every acting subcommand refuses to run unless VRoid Studio is the focused
window.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import actions as A
from . import locate as L
from .backend import capture as C
from .backend import input as I
from .backend import window as W


def _region(spec: str | None):
    if not spec:
        return None
    x, y, w, h = (int(v) for v in spec.split(","))
    return (x, y, x + w, y + h)


def main(argv=None) -> int:
    from ..session_env import ensure_session_env
    ensure_session_env()
    if sys.platform == "win32":
        # OCR output is not always representable in the console code page
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="vroid-driver", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("launch").add_argument("--timeout", type=float, default=240)
    sp = sub.add_parser("shot"); sp.add_argument("tag", nargs="?", default="")
    sp.add_argument("--screen", action="store_true", help="whole output, not just VRoid")
    sub.add_parser("screen")
    sp = sub.add_parser("text"); sp.add_argument("--region")
    sp = sub.add_parser("find"); sp.add_argument("needle"); sp.add_argument("--region")
    sp = sub.add_parser("click")
    sp.add_argument("x", type=float); sp.add_argument("y", type=float)
    sp.add_argument("--space", default="image", choices=["image", "window", "layout"])
    sp.add_argument("--button", default="left")
    sp = sub.add_parser("drag")
    for a in ("x1", "y1", "x2", "y2"):
        sp.add_argument(a, type=float)
    sp.add_argument("--space", default="image", choices=["image", "window", "layout"])
    sp = sub.add_parser("type"); sp.add_argument("text")
    sp = sub.add_parser("key"); sp.add_argument("name"); sp.add_argument("--mods", default="")
    sp = sub.add_parser("scroll"); sp.add_argument("ticks", type=int)
    sp = sub.add_parser("tab"); sp.add_argument("name")
    sp = sub.add_parser("slider")
    sp.add_argument("label"); sp.add_argument("value", type=float)
    sp = sub.add_parser("new-character"); sp.add_argument("base", nargs="?", default="Fem")
    sp = sub.add_parser("apply-params"); sp.add_argument("json_path")
    sp = sub.add_parser("cam")
    sp.add_argument("verb", choices=["zoom", "orbit", "pan", "full-body", "turn"])
    sp.add_argument("a", type=float, nargs="?", default=0.0)
    sp.add_argument("b", type=float, nargs="?", default=0.0)
    sp = sub.add_parser("export")
    sp.add_argument("out", nargs="?", default=None)
    sp.add_argument("--name", default="SpikeAvatar")
    sp.add_argument("--creators", default="arrakis-vroid-driver")
    sp.add_argument("--vrm-version", default="1.0", choices=["1.0", "0.0"])
    sub.add_parser("export-screen")
    sub.add_parser("close")
    sp = sub.add_parser("restore"); sp.add_argument("workspace", type=int)

    a = p.parse_args(argv)

    if a.cmd == "launch":
        win, prev = W.prepare(a.timeout)
        print(json.dumps({"address": win.address, "title": win.title,
                          "geometry": win.geometry, "previous_workspace": prev}))
        return 0

    if a.cmd == "restore":
        W.leave(a.workspace)
        return 0

    if a.cmd == "close":
        print(json.dumps({"closed": A.close_vroid()}))
        return 0

    if a.cmd == "shot":
        s = C.grab_screen(a.tag) if a.screen else C.grab_window(tag=a.tag)
        print(s.path)
        return 0

    if a.cmd == "screen":
        print(A.current_screen())
        return 0

    if a.cmd == "text":
        s = C.grab_window()
        img = s.crop(_region(a.region)) if a.region else s
        for m in L.all_text(img):
            print(f"{m.center[0]:5d} {m.center[1]:5d}  {m.conf:5.1f}  {m.text}")
        return 0

    if a.cmd == "find":
        s = C.grab_window()
        ms = L.find_text(s, a.needle, region=_region(a.region), all_matches=True)
        if not ms:
            print("not found", file=sys.stderr)
            return 1
        for m in ms:
            print(f"{m.center[0]} {m.center[1]}  conf={m.conf:.0f}  {m.text!r}")
        return 0

    # everything below acts on the app
    W.assert_vroid_focused()

    if a.cmd == "click":
        s = C.grab_window() if a.space == "image" else None
        I.click(a.x, a.y, button=a.button, space=a.space, shot=s)
    elif a.cmd == "drag":
        s = C.grab_window() if a.space == "image" else None
        I.drag(a.x1, a.y1, a.x2, a.y2, space=a.space, shot=s)
    elif a.cmd == "type":
        I.type_text(a.text)
    elif a.cmd == "key":
        I.key(a.name, mods=[m for m in a.mods.split(",") if m])
    elif a.cmd == "scroll":
        I.scroll(a.ticks)
    elif a.cmd == "tab":
        print(A.open_tab(a.name).path)
        return 0
    elif a.cmd == "slider":
        print(A.set_slider(a.label, a.value).path)
        return 0
    elif a.cmd == "new-character":
        print(A.new_character(a.base).path)
        return 0
    elif a.cmd == "apply-params":
        print(json.dumps(A.apply_params(a.json_path)))
        return 0
    elif a.cmd == "cam":
        if a.verb == "zoom":
            A.cam_zoom(int(a.a))
        elif a.verb == "orbit":
            A.cam_orbit(int(a.a), int(a.b))
        elif a.verb == "pan":
            A.cam_pan(int(a.a), int(a.b))
        elif a.verb == "turn":
            print(A.cam_turn(a.a).path)
            return 0
        elif a.verb == "full-body":
            print(A.cam_full_body().path)
            return 0
    elif a.cmd == "export":
        out = Path(a.out) if a.out else A.default_out()
        print(A.export_vrm(out, avatar_name=a.name, creators=a.creators,
                           version=a.vrm_version))
        return 0
    elif a.cmd == "export-screen":
        print(A.open_export_screen().path)
        return 0

    print(C.grab_window(tag=a.cmd).path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
