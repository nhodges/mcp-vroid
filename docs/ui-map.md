# VRoid Studio UI map

VRoid Studio **2.14.0**, English UI, captured fullscreen at **2560 × 1440**
(Hyprland layout 2048 × 1152, scale 1.25). All coordinates below are **image
px** — the space `vroid_click` and `vroid_find_text` use by default.

Treat every number as a *hint*. The tools locate by OCR and colour first and
fall back to these anchors only for things that have no text (icons).

**VRoid lays its UI out in fixed pixels from the window's edges**, not in
proportion to the window. Measured again on Windows at 1920 × 1017 and
1366 × 705 (client area, VRoid 2.14.0, 100 % scale): the tabs, the left rail,
the hamburger and the `Create New` card sit at the same pixel positions as
below; the toolbar icons and the Parameters value column keep the same
distance from the right edge (share icon 96 px, value box 55 px); the base
chooser and VRM Settings keep the same distance from the centre. So read a
right-hand coordinate below as "this far from the right edge"; the anchors in
`actions.py` are written that way (`x < 0` counts from the right). A display
or UI scale other than 100 % has not been measured.

## Start screen

* `Create New` `+` card at ≈ (118, 218), its caption at (118, 328)
* `New` / `Open` top-right at (2439, 99) / (2495, 100)
* Sample Models grid below

`Create New` opens a modal — *"Select a base to start with"* — with captions
`Fem` at (1199, 862) and `Masc` at (1359, 862). Click the **thumbnail ~100 px
above** the caption, not the caption itself.

## Editor

Tab strip at y ≈ 23:

| tab | x |
|---|---|
| `Face` | 97 |
| `Hairstyle` | 198 |
| `Body` | 302 |
| `Outfit` | 392 |
| `Accessories` | 509 |
| `Look` | 622 |

* Hamburger `☰` at (29, 23) → Save (Ctrl+S), Save As… (Ctrl+Shift+S),
  import / bulk export, undo/redo, back to model selection. **Escape does not
  close this menu** — click elsewhere.
* Toolbar top-right: camera (2415, 23), **share/export** (2464, 23),
  kebab `⋮` (2512, 23).
* Left icon rail (x ≈ 24, first icon y ≈ 77, then every ~48 px) —
  sub-category for the current tab.
* Left panel: preset grid, with `Presets` / `Custom` at y ≈ 120.
* Right panel: Customize, then Parameters.

### Right-panel controls

| control | drive it by |
|---|---|
| slider | the numeric box at x ≈ 2505, i.e. 55 px from the right edge (`vroid_set_slider`); the track spans x ≈ 2278 → 2516 with 0.0 centred |
| colour | the `#RRGGBB` box at x ≈ 2450 (`vroid_set_color`) |
| checkbox / radio | click the square/circle |
| accordion | click the caption (e.g. `> Reduce Polygons`) |
| dropdown | only in the native Wine dialogs; click, then arrow keys |

### Parameter names

`Body` starts `Model's Height : 161.2 cm`, then `Fem Height`, `Masc Height`,
`Body Size`, `Head Size`, `Head Width`, `Head Tip (Y)`, `Neck Length` /
`Thickness` / `Width`, `Soften Collarbone`, `Show Adam's Apple`,
`Shoulder Width`, …

`Face` has ~40 rows: `Eye Size X/Y`, `Eyes Position (X/Y)`,
`Rotate Eye Socket`, `Inner/Outer Eye Slant`, `Iris Size X/Y`, `Gaze (Y)`, …

`vroid_set_slider` scrolls the panel to find the row for you.

On the Body tab the `Parameters` header (y ≈ 459) stays put and only the list
below it scrolls, 50 px per wheel notch, with the pointer over the list. On a
short window that list is a narrow band — about 125 px of it usable at
1366 × 705 — so the panel is scrolled from near its bottom edge, a few
notches at a time.

## Hair editor

Hairstyle tab → left-rail part icon → `Custom` sub-tab → `+ Create New` →
right panel `Edit Hairstyle`.

Inside:

* `Add Freehand Hair Guides` / `Add Procedural Hair Guides` top-left
* a `Hair Groups` list down the left
* tool palette at (330 / 365 / 398 / 432, 83)
* undo / redo at (76, 23) / (133, 23)

**Leaving asks first.** The `✕` at (23, 23) pops a *Close Hairstyle Editor*
modal offering `Save as new item` / `Overwrite` / `Close without saving`.

## Export as VRM

1. Share icon (2464, 23) → `Export as VRM`
2. Full-screen export page; the blue `Export` pill sits at ≈ (2412, 197).
   Reduce Polygons / Materials / Bones accordions are on the right.
3. **VRM Settings** modal — centred, roughly x 1000 → 1560, scrollable:
   * `Export Format` radios: `VRM1.0` / `VRM0.0`
   * `Avatar Name` **required**
   * `Version`
   * `Creators` **required**
   * copyright / contact / references, usage permission checkboxes

   The Export pill stays **grey and dead** until both required fields are
   filled — `vroid_find_button(color='disabled')` will tell you so.
   **Escape does not close this modal**; a click outside it does.
4. **Save dialog** — its own window, title `Export` (`Save` for Save As).

### On Linux: Wine's dialog

The `File name:` field opens focused and selected, so typing a Windows path
replaces it and Return fires the default button.

Two traps here:

* The Proton prefix maps `Z:\` to `/`, so `/home/you/models/x.vrm` is
  `Z:\home\you\models\x.vrm`. `vroid_export_vrm` does the translation.
* **Do not click a `Save` located by OCR** in that dialog: the `Save in:`
  label matches the same needle.

Use `vroid_screenshot(whole_screen=true)` while the Wine dialog is up — it is
not a child of the VRoid window and is not inside its geometry.

### On Windows: the common file dialog

Class `#32770`, owned by VRoid's process, opening near the top-left of
VRoid's monitor. Its labels follow the **Windows display language** (on a
Japanese system the button is `保存(&S)`), so nothing in it is located by OCR.
The file-name box is an `Edit` with control id 1001 (the address bar is also
1001, as a toolbar) and the default button is `IDOK`: `vroid_export_vrm` and
`vroid_save_project` write the path into the box, read it back, and send
`IDOK`. The dialog is never screenshotted — which also keeps the folder
listing it shows out of the captures.
