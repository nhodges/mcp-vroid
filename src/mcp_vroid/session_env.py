"""Recover the desktop-session environment an MCP client may not pass on.

MCP servers are launched by the client, and clients routinely start them with
a sanitised environment (the Python SDK's own stdio client strips everything
except PATH/HOME and friends). Every tool in this server shells out to
`hyprctl` and `grim` and talks to Xwayland, all of which need
`XDG_RUNTIME_DIR`, `WAYLAND_DISPLAY`, `HYPRLAND_INSTANCE_SIGNATURE` and
`DISPLAY`. Rather than fail with "Command 'hyprctl' returned non-zero exit
status 1", discover them from the runtime dir before anything else runs.

Anything already set in the environment wins, so a client that does pass the
full session env changes nothing here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _runtime_dir() -> Path:
    rd = os.environ.get("XDG_RUNTIME_DIR")
    if not rd:
        rd = f"/run/user/{os.getuid()}"
        os.environ["XDG_RUNTIME_DIR"] = rd
    return Path(rd)


def _newest(paths: list[Path]) -> Path | None:
    live = [p for p in paths if p.exists()]
    if not live:
        return None
    return max(live, key=lambda p: p.stat().st_mtime)


def ensure_session_env() -> dict[str, str]:
    """Fill in the missing session variables; returns what this call set."""
    filled: dict[str, str] = {}
    if sys.platform == "win32":
        return filled       # one desktop session, nothing to recover
    rd = _runtime_dir()

    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        inst = _newest(sorted((rd / "hypr").glob("*"))) if (rd / "hypr").is_dir() else None
        if inst is not None and inst.is_dir():
            os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = inst.name
            filled["HYPRLAND_INSTANCE_SIGNATURE"] = inst.name

    if not os.environ.get("WAYLAND_DISPLAY"):
        sock = _newest([p for p in rd.glob("wayland-*") if p.suffix != ".lock"])
        if sock is not None:
            os.environ["WAYLAND_DISPLAY"] = sock.name
            filled["WAYLAND_DISPLAY"] = sock.name

    if not os.environ.get("DISPLAY"):
        x = _newest([p for p in Path("/tmp/.X11-unix").glob("X[0-9]*")
                     if p.name[1:].isdigit()]) if Path("/tmp/.X11-unix").is_dir() else None
        os.environ["DISPLAY"] = f":{x.name[1:]}" if x is not None else ":0"
        filled["DISPLAY"] = os.environ["DISPLAY"]

    return filled
