"""OCR through Windows' built-in engine (Windows.Media.Ocr).

The Windows stand-in for the `tesseract ... tsv` subprocess in locate.py: it
takes the already-prepared image and returns the same word boxes, so
everything above it (find_text, all_text, find_button, the flows) is
unchanged. Nothing has to be installed - the engine ships with Windows 10/11
and uses whichever OCR language packs the user profile has.

Two differences from tesseract worth knowing:

* there is no per-word confidence, so every word reports conf=100 and
  `min_conf` has nothing to filter on;
* there are no page-segmentation modes (`psm` is ignored).
"""
from __future__ import annotations

from PIL import Image


def words_from_result(result, upscale: float = 1.0,
                      conf: float = 100.0) -> list[tuple]:
    """Flatten an OcrResult into (text, conf, left, top, width, height)
    tuples in pixels of the *original* (pre-upscale) image.

    Takes anything shaped like an OcrResult (`.lines[].words[]` with
    `.text` and `.bounding_rect`), which keeps it testable without WinRT.
    """
    out: list[tuple] = []
    for line in result.lines:
        for w in line.words:
            text = (w.text or "").strip()
            if not text:
                continue
            r = w.bounding_rect
            out.append((text, conf,
                        int(r.x / upscale), int(r.y / upscale),
                        int(r.width / upscale), int(r.height / upscale)))
    return out


def merge_readings(first: list[tuple], second: list[tuple],
                   tol: int = 6) -> list[tuple]:
    """Union of two OCR passes over the same picture at different scales.

    The engine misreads the odd small label at one scale and not at another
    ("Title" comes back as "Titte" at 2x and correctly at 1x, or the other
    way round), and it gives no confidence to choose by. So keep both: a
    word of the second pass is dropped only when the first pass already has
    the same text at the same place; a *different* text at the same place
    is kept as an alternative reading for the caller's needle to match.
    """
    out = list(first)
    for w in second:
        text, _conf, left, top = w[0], w[1], w[2], w[3]
        dup = any(o[0] == text and abs(o[2] - left) <= tol
                  and abs(o[3] - top) <= tol for o in first)
        if not dup:
            out.append(w)
    return out


_engine = None
_engine_lang = None


def _get_engine(lang: str):
    """One engine per process. `lang` is a tesseract code ("eng"); English is
    asked for explicitly because VRoid's UI is driven in English, falling
    back to the user's profile languages."""
    global _engine, _engine_lang
    if _engine is not None and _engine_lang == lang:
        return _engine
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine

    tag = {"eng": "en-US", "jpn": "ja"}.get(lang, lang)
    engine = None
    try:
        language = Language(tag)
        if OcrEngine.is_language_supported(language):
            engine = OcrEngine.try_create_from_language(language)
    except Exception:
        engine = None
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError(
            "Windows OCR has no recognizer language installed. Add one in "
            "Settings > Time & language > Language & region (an English "
            "language pack includes OCR), or as administrator: "
            "Add-WindowsCapability -Online -Name "
            "'Language.OCR~~~en-US~0.0.1.0'")
    _engine, _engine_lang = engine, lang
    return engine


def max_dimension() -> int:
    from winrt.windows.media.ocr import OcrEngine
    return int(OcrEngine.max_image_dimension)


def _software_bitmap(img: Image.Image):
    from winrt.windows.graphics.imaging import (BitmapPixelFormat,
                                                SoftwareBitmap)
    from winrt.windows.storage.streams import DataWriter

    rgba = img.convert("RGBA")
    writer = DataWriter()
    writer.write_bytes(rgba.tobytes("raw", "BGRA"))
    return SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.BGRA8,
        rgba.width, rgba.height)


def ocr_words(prepped: Image.Image, upscale: float = 1.0,
              lang: str = "eng") -> list[tuple]:
    """Word boxes of a prepared image, in pixels of the image *before* it was
    upscaled by `upscale`.

    The engine refuses images larger than max_dimension() on either side;
    such an image is shrunk to fit and the boxes scaled back.
    """
    engine = _get_engine(lang)
    limit = max_dimension()
    fit = min(1.0, limit / max(prepped.size))
    if fit < 1.0:
        prepped = prepped.resize((int(prepped.width * fit),
                                  int(prepped.height * fit)), Image.LANCZOS)
    result = engine.recognize_async(_software_bitmap(prepped)).get()
    return words_from_result(result, upscale * fit)
