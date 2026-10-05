# VRoid Studio UI map

VRoid Studio **2.14.0**, English UI, captured fullscreen at **2560 × 1440**
(Hyprland layout 2048 × 1152, scale 1.25). All coordinates below are **image
px** — the space `vroid_click` and `vroid_find_text` use by default.

Treat every number as a *hint*. The tools locate by OCR and colour first and
fall back to these anchors only for things that have no text (icons). On
another resolution or DPI scale, the fractional anchors will need
re-measuring.

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
| slider | the numeric box at x ≈ 2505 (`vroid_set_slider`); the track spans x ≈ 2278 → 2516 with 0.0 centred |
| colour | the `#RRGGBB` box at x ≈ 2450 (`vroid_set_color`) |
| checkbox / radio | click the square/circle |
| accordion | click the caption (e.g. `> Reduce Polygons`) |
| dropdown | click it, then click an entry of the list that opens (export page); in the native Wine dialogs: click, then arrow keys |

### Parameter names

`Body` starts `Model's Height : 161.2 cm`, then `Fem Height`, `Masc Height`,
`Body Size`, `Head Size`, `Head Width`, `Head Tip (Y)`, `Neck Length` /
`Thickness` / `Width`, `Soften Collarbone`, `Show Adam's Apple`,
`Shoulder Width`, …

`Face` has ~40 rows: `Eye Size X/Y`, `Eyes Position (X/Y)`,
`Rotate Eye Socket`, `Inner/Outer Eye Slant`, `Iris Size X/Y`, `Gaze (Y)`, …

`vroid_set_slider` scrolls the panel to find the row for you.

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
4. **Wine save dialog** — its own window, title `Export`. The `File name:`
   field opens focused and selected, so typing a Windows path replaces it and
   Return fires the default button.

Two traps here:

* The Proton prefix maps `Z:\` to `/`, so `/home/you/models/x.vrm` is
  `Z:\home\you\models\x.vrm`. `vroid_export_vrm` does the translation.
* **Do not click a `Save` located by OCR** in that dialog: the `Save in:`
  label matches the same needle.

Use `vroid_screenshot(whole_screen=true)` while the Wine dialog is up — it is
not a child of the VRoid window and is not inside its geometry.

## Checked on Windows

VRoid Studio **2.14.0**, English UI, native on **Windows 11** at 100 %
scaling, with the window maximised on a 3440 × 1440 monitor (client area
**3440 × 1369**) and, for comparison, at its initial 1024 × 768. `W` and `H`
below are the width and height of the capture.

### The layout is fixed-size, pinned to the edges

Nothing stretches with the window. Everything measured from the left or the
top above is at the same pixel on Windows at any window size (`Face` is at
x 97 in a 1024-wide window and in a 3440-wide one). Everything on the right
keeps its distance from the right edge, so read the 2560-wide numbers above
as:

| thing | above | really |
|---|---|---|
| camera / share-export / kebab | 2415 / 2464 / 2512 | `W − 145` / `W − 96` / `W − 48` |
| `New` / `Open` on the start screen | 2439 / 2495 | `W − 121` / `W − 65` |
| numeric box of a Parameters row | 2505 | `W − 56` |
| Export pill on the export page | 2412 | `W − 148` |

Modals (base chooser, VRM Settings) are centred. VRM Settings is 570 px
wide.

### Differences from the map above

* **First run.** A fresh install opens on a splash — the VRoid Studio logo
  and one blue `Get Started` pill — instead of the start screen. It appears
  once.
* **Start screen with no saved models:** `Recently Edited` holds only the
  `Create New` card (caption still at (118, 328)); the `Sample Models` heading
  is at y ≈ 407 and the grid under it is as many columns wide as the window allows.
* **The right-hand panel is not always there.** `Hairstyle → Hairstyle Sets`
  and `Outfit → Whole Sets` show only the preset grid on the left; the
  Parameters panel appears for sub-categories that have parameters (`Face`,
  `Body`).
* **There are dropdowns inside VRoid**, not only in the file dialog: on the
  export page, `Materials` and `Texture Quality` / `Texture Atlas
  Resolution`. Click the box, then click an entry of the list that opens
  under it (entries are ~32 px apart).
* **Export page, right column.** Three accordions above the pill, all closed
  at first, pill at y ≈ 197:
  * `Reduce Polygons` — `Edit Hair Cross-Section` (off), `Delete Transparent
    Meshes` (**on** by default), then `Hair Smoothness`, `Hair`, `Face`,
    `Body`, `Outfit`, each a 0–100 slider with a numeric box at `W − 56` that
    takes a typed value, and `Reset`.
  * `Reduce Materials` — `Materials`: `Default` / `2` / `8` / `12`. With
    `Default`: a `Combine Hair Mesh` checkbox and `Texture Quality`. With a
    number: `Texture Atlas Resolution`, `4096 x 4096` / `2048 x 2048`.
  * `Reduce Bones`.

  Opening them pushes the pill down (y ≈ 826 with the first two open). The
  `Export Info` box left of the column reports polygons / materials / bones
  and updates as you change things; the whole window dims for a few seconds
  while it recomputes and **ignores clicks until it is done**.
* **VRM Settings depends on the format.** `VRM1.0` asks for `Avatar Name`
  and `Creators`; with `VRM0.0` selected the form is `Title` **required**,
  `Creator` **required**, `Contact Information`, `Reference`, `Version`, …
  The choice of format is remembered for the session. Escape does not close
  the modal; **a click outside it does**, silently.
* **Save dialog.** On Windows it is the native common file dialog, a
  separate top-level window (class `#32770`) owned by the VRoid window. The
  driver types the full path into its `File name` box, reads the box back to
  check it, and presses Return.

### Camera

As measured on Linux: wheel down over the viewport zooms out (17 notches
from the default framing shows the whole body), middle-drag moves the model
with the pointer.
