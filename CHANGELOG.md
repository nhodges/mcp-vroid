# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
follow [semantic versioning](https://semver.org/).

## [Unreleased]

### Added

* **Windows backend** (`driver/win32/`): EnumWindows + DWM for the window,
  `PIL.ImageGrab` for captures, `SendInput` for pointer, wheel and keys, and
  the common Save dialog driven as controls. Nothing to build and no new
  dependencies. Tested on Windows 10 with VRoid Studio 2.14.0 at 1920×1080
  and 1366×768.
* `driver/backend.py` picks the backend for the platform
  (`MCP_VROID_BACKEND` overrides it) and lists in `CONTRACT` what a backend
  provides. `vroid_status` reports the backend in use.
* `MCP_VROID_EXE` — which `VRoidStudio.exe` to launch on Windows.

### Changed

* UI anchors in `actions.py` are pixel offsets from a window edge instead of
  fractions of the window, because VRoid lays its UI out in fixed pixels. At
  2560×1440 they land within 1 px of where they did.
* The Parameters panel is scrolled from near its bottom edge, in steps no
  larger than the visible band, so short windows do not skip rows.
* Captures and exports default to `%LOCALAPPDATA%\mcp-vroid` on Windows.

### Fixed

* OCR output is decoded as UTF-8; on a non-UTF-8 locale a single non-ASCII
  glyph made `ocr_words()` fail.
* `set_slider()`, `drag_slider()` and `set_hex_color()` could type into the
  wrong row: a multi-word label matched any one of its words.
* The VRM Settings fields are checked inside their own boxes, tolerating a
  misread letter, instead of by a short needle anywhere on screen.
* `vroid_launch(restart=true)` no longer shells out to `pkill` from the
  server.

## [0.1.0] — 2026-08-24

First public release.

### Added

* **MCP server** (`mcp-vroid`, stdio) exposing 18 tools over VRoid Studio:
  * lifecycle — `vroid_launch`, `vroid_status`, `vroid_release`
  * seeing — `vroid_screenshot`, `vroid_find_text`, `vroid_find_button`,
    `vroid_current_screen`
  * raw input — `vroid_click`, `vroid_drag`, `vroid_scroll`, `vroid_type`,
    `vroid_key`
  * flows — `vroid_new_character`, `vroid_open_tab`, `vroid_set_slider`,
    `vroid_set_color`, `vroid_export_vrm`, `vroid_save_project`
* **Driver engine** (`mcp_vroid.driver`): `grim` capture, tesseract OCR and
  OpenCV colour matching for locating, `hyprctl` for window management, and
  input through a `zwlr_virtual_pointer_unstable_v1` helper (pointer) plus
  X11 XTEST (keyboard and wheel).
* **`native/vpointer`** — a small C client for the Wayland virtual-pointer
  protocol, built by `native/build.sh`. Moves the real compositor cursor and
  needs no `/dev/uinput` access.
* **Session-environment recovery** so the server works when an MCP client
  launches it with a sanitised environment.
* **Focus guard** — every acting tool refuses to run unless VRoid Studio is
  the focused window; the idle screensaver is dismissed rather than typed
  into.
* **`vroid-driver` CLI** for driving the same engine from a shell.
* `scripts/smoke_test.py` — starts the server, lists tools, calls the
  read-only ones; never sends input.
* Documentation: README, [`docs/ui-map.md`](docs/ui-map.md).

### Known limitations

Calibrated against VRoid Studio 2.14.0 (English) at 2560×1440 / scale 1.25 on
Hyprland. See the README's *Limitations and brittleness* section.

[0.1.0]: https://github.com/nhodges/mcp-vroid/releases/tag/v0.1.0
