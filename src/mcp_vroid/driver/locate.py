"""Find things in a screenshot: OCR word boxes (tesseract) + template match (cv2)."""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .capture import Shot


@dataclass
class Match:
    text: str
    conf: float
    left: int
    top: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)

    def __repr__(self) -> str:
        return (f"Match({self.text!r} conf={self.conf:.0f} "
                f"center={self.center} box=({self.left},{self.top},"
                f"{self.width},{self.height}))")


# --- OCR --------------------------------------------------------------------

def _prep(img: Image.Image, upscale: float, invert: bool) -> Image.Image:
    g = img.convert("L")
    if invert:
        g = ImageOps.invert(g)
    if upscale != 1.0:
        g = g.resize((int(g.width * upscale), int(g.height * upscale)),
                     Image.LANCZOS)
    return ImageOps.autocontrast(g)


def ocr_words(img: Image.Image | Shot, upscale: float = 2.0,
              invert: bool = False, lang: str = "eng",
              psm: int = 11, min_conf: float = 40.0) -> list[Match]:
    """Word boxes in *image pixel* coordinates of the original image."""
    if isinstance(img, Shot):
        img = img.image
    prepped = _prep(img, upscale, invert)
    if sys.platform == "win32":
        # Windows' built-in OCR instead of the tesseract binary; same boxes.
        from .ocr_winrt import merge_readings
        from .ocr_winrt import ocr_words as winrt_words
        words = winrt_words(prepped, upscale, lang)
        if upscale != 1.0:
            # a second reading at native size: see merge_readings
            words = merge_readings(
                words, winrt_words(_prep(img, 1.0, invert), 1.0, lang))
        return [Match(*w) for w in words if w[1] >= min_conf]
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ocr.png"
        prepped.save(p)
        out = subprocess.run(
            ["tesseract", str(p), "stdout", "-l", lang, "--psm", str(psm), "tsv"],
            capture_output=True, text=True,
        )
    matches: list[Match] = []
    lines = out.stdout.splitlines()
    if not lines:
        return matches
    header = lines[0].split("\t")
    try:
        i_conf, i_l, i_t, i_w, i_h, i_txt = (
            header.index("conf"), header.index("left"), header.index("top"),
            header.index("width"), header.index("height"), header.index("text"))
    except ValueError:
        return matches
    for line in lines[1:]:
        f = line.split("\t")
        if len(f) <= i_txt:
            continue
        text = f[i_txt].strip()
        if not text:
            continue
        try:
            conf = float(f[i_conf])
        except ValueError:
            continue
        if conf < min_conf:
            continue
        matches.append(Match(text, conf,
                             int(int(f[i_l]) / upscale), int(int(f[i_t]) / upscale),
                             int(int(f[i_w]) / upscale), int(int(f[i_h]) / upscale)))
    return matches


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_text(img: Image.Image | Shot, needle: str, *, exact: bool = False,
              all_matches: bool = False, region: tuple | None = None,
              **kw):
    """Locate `needle` and return its center in image-pixel coords.

    Returns a Match (or list with all_matches=True), or None.
    Tries dark-on-light then light-on-dark, since VRoid mixes both.
    """
    src = img.image if isinstance(img, Shot) else img
    off = (0, 0)
    if region:
        src = src.crop(region)
        off = (region[0], region[1])

    want = _norm(needle)
    found: list[Match] = []
    seen = set()
    psms = [kw.pop("psm")] if "psm" in kw else [11, 6]
    for invert, psm in [(i, p) for i in (False, True) for p in psms]:
        for m in ocr_words(src, invert=invert, psm=psm, **kw):
            t = _norm(m.text)
            hit = (t == want) if exact else (want in t or (len(t) > 2 and t in want))
            if not hit:
                continue
            m = Match(m.text, m.conf, m.left + off[0], m.top + off[1],
                      m.width, m.height)
            key = (round(m.left / 8), round(m.top / 8), t)
            if key in seen:
                continue
            seen.add(key)
            found.append(m)
    rows = {id(m): _row_words(m, found) for m in found}
    found.sort(key=lambda m: (-m.conf, -rows[id(m)]))
    if all_matches:
        return found
    return found[0] if found else None


def _row_words(m: Match, found: list[Match]) -> int:
    """How many different matched words share m's text row.

    A tie-break for multi-word needles: "Head Size" hits the "Size" of
    "Body Size" too, and an OCR engine with no per-word confidence (Windows)
    cannot rank the two. The row holding more of the needle's words wins.
    """
    return len({_norm(o.text) for o in found
                if abs(o.center[1] - m.center[1]) < 12})


def all_text(img: Image.Image | Shot, **kw) -> list[Match]:
    """Every word tesseract sees, both polarities, deduped."""
    src = img.image if isinstance(img, Shot) else img
    out: list[Match] = []
    seen = set()
    for invert in (False, True):
        for m in ocr_words(src, invert=invert, **kw):
            key = (round(m.left / 8), round(m.top / 8), _norm(m.text))
            if key in seen or not _norm(m.text):
                continue
            seen.add(key)
            out.append(m)
    out.sort(key=lambda m: (m.top, m.left))
    return out


# --- template matching ------------------------------------------------------

def find_template(img: Image.Image | Shot, template: Image.Image | str | Path,
                  threshold: float = 0.85) -> Match | None:
    import cv2

    src = img.image if isinstance(img, Shot) else img
    if isinstance(template, (str, Path)):
        template = Image.open(template).convert("RGB")
    hay = cv2.cvtColor(np.array(src), cv2.COLOR_RGB2GRAY)
    needle = cv2.cvtColor(np.array(template.convert("RGB")), cv2.COLOR_RGB2GRAY)
    if needle.shape[0] > hay.shape[0] or needle.shape[1] > hay.shape[1]:
        return None
    res = cv2.matchTemplate(hay, needle, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(res)
    if mx < threshold:
        return None
    return Match("<template>", mx * 100, loc[0], loc[1],
                 needle.shape[1], needle.shape[0])


def diff_ratio(a: Image.Image | Shot, b: Image.Image | Shot) -> float:
    """Fraction of pixels that changed between two shots (same size)."""
    ia = a.image if isinstance(a, Shot) else a
    ib = b.image if isinstance(b, Shot) else b
    if ia.size != ib.size:
        ib = ib.resize(ia.size)
    na = np.asarray(ia.convert("L"), dtype=np.int16)
    nb = np.asarray(ib.convert("L"), dtype=np.int16)
    return float((np.abs(na - nb) > 12).mean())


# --- solid-colour widgets ---------------------------------------------------

ACCENT = (0, 150, 250)   # VRoid's primary-button blue (#0096fa)


def find_color_blobs(img: Image.Image | Shot, rgb=ACCENT, tol: int = 26,
                     min_w: int = 40, min_h: int = 14,
                     region: tuple | None = None) -> list[Match]:
    """Connected regions of a flat colour, biggest first.

    VRoid's primary buttons ("Export", "OK", "Create") are solid #0096fa
    pills. Tesseract regularly loses white-on-blue button labels, so match
    the button chrome instead of its text.
    """
    import cv2

    src = img.image if isinstance(img, Shot) else img
    off = (0, 0)
    if region:
        src = src.crop(region)
        off = (region[0], region[1])
    a = np.asarray(src.convert("RGB")).astype(np.int16)
    mask = (np.abs(a - np.array(rgb, dtype=np.int16)).max(axis=2) <= tol)
    mask = mask.astype(np.uint8)
    n, _, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w < min_w or h < min_h or area < 0.4 * w * h:
            continue
        out.append(Match(f"<blob {rgb}>", 100.0, int(x + off[0]), int(y + off[1]),
                         int(w), int(h)))
    out.sort(key=lambda m: -(m.width * m.height))
    return out


def find_button(img: Image.Image | Shot, label: str | None = None,
                rgb=ACCENT, **kw) -> Match | None:
    """Primary (accent-coloured) button; if `label` is given, prefer the blob
    whose interior OCRs to that label, else return the largest blob."""
    blobs = find_color_blobs(img, rgb=rgb, **kw)
    if not blobs:
        return None
    if label is None:
        return blobs[0]
    src = img.image if isinstance(img, Shot) else img
    want = _norm(label)
    for b in blobs:
        pad = 2
        sub = src.crop((b.left + pad, b.top + pad,
                        b.left + b.width - pad, b.top + b.height - pad))
        for m in ocr_words(sub, upscale=4.0, psm=7, min_conf=20):
            if want in _norm(m.text):
                return b
    return None
