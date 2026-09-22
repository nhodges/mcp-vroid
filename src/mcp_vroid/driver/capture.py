"""Screenshot the VRoid window with grim and hand back a PIL image.

Coordinates: Hyprland's layout is *logical* (2048x1152 here for a 2560x1440
panel at scale 1.25). grim renders at the output's native scale, so image
pixels are `scale` times the layout units. A Shot carries the mapping so
callers can hand OCR pixel coords straight back to input.click().
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image

from . import window as W
from .shot import Shot, next_capture_path  # noqa: F401  (re-exported)


def output_scale() -> float:
    mons = W.hyprctl_json("monitors")
    return float(mons[0].get("scale", 1.0)) if mons else 1.0


def grab_region(x: int, y: int, w: int, h: int, tag: str = "",
                path: Path | None = None) -> Shot:
    path = path or next_capture_path(tag)
    scale = output_scale()
    subprocess.run(
        ["grim", "-g", f"{x},{y} {w}x{h}", str(path)],
        check=True, capture_output=True,
    )
    img = Image.open(path).convert("RGB")
    # grim may clamp the region at the output edge; derive the real scale.
    if w:
        scale = img.width / w
    return Shot(img, path, x, y, scale)


def grab_window(win: W.Window | None = None, tag: str = "") -> Shot:
    win = win or W.find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    return grab_region(*win.geometry, tag=tag)


def grab_screen(tag: str = "") -> Shot:
    mon = W.hyprctl_json("monitors")[0]
    scale = float(mon.get("scale", 1.0))
    w = int(round(mon["width"] / scale))
    h = int(round(mon["height"] / scale))
    return grab_region(int(mon["x"]), int(mon["y"]), w, h, tag=tag)
