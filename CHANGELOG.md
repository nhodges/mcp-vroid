# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
follow [semantic versioning](https://semver.org/).

## [Unreleased]

### Added

* **Windows backend.** `driver/backend.py` selects the platform layer; on
  Windows that is `window_win32` (Win32 window APIs, per-monitor DPI aware),
  `capture_win32` (`PrintWindow`), `input_win32` (`SendInput`) and
  `ocr_winrt` (`Windows.Media.Ocr`, so no tesseract). The Linux modules are
  unchanged and still selected on Linux. Port of the original Linux project
  to Windows; tested on Windows 11 with VRoid Studio 2.14.0.
* **Windows input guard:** VRoid must be the foreground window and the
  target inside its client rectangle; keys may also go to the native save
  dialog VRoid owns; a cursor in a screen corner aborts; Win-key and
  window-manager shortcuts are refused.
* `vroid_close` tool, and `close`, `export-screen` and
  `export --vrm-version` in `vroid-driver`.
* `actions.open_export_screen()`; `export_vrm()` starts from the export
  screen (or the VRM Settings modal) when one is already open, so export
  options can be set before the walk continues.
* Tests (`uv run pytest`) with captured screenshots as fixtures.

### Fixed

* UI anchors follow the window edges. VRoid's UI is fixed-size, not
  proportional, so the fractional anchors only hit on a 2560x1440 capture;
  they evaluate to the same pixels as before at that size.
* VRM0.0 export: the form asks for `Title` / `Creator` rather than
  `Avatar Name` / `Creators`; the VRM0.0 radio is matched exactly; the wait
  for the VRM Settings modal no longer fires on the `Export as VRM` title.
* The Export pill is found when the Reduce accordions are open.
* `find_text` breaks confidence ties by row, so `Head Size` does not resolve
  to the `Size` of `Body Size`.

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
