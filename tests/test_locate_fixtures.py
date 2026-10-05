"""Locating logic on saved captures.

The fixtures are VRoid Studio 2.14.0 (English UI) captured by the Windows
backend with the window maximised on a 3440x1440 monitor at 100 % scaling
(client area 3440x1369):

    start-screen.png        start screen, no saved models
    editor-body.png         editor, Body tab, Parameters panel
    export-screen.png       Export as VRM, Reduce Polygons / Materials open
    vrm-settings-vrm0.png   VRM Settings modal with VRM0.0 selected

The OCR-backed tests run on Windows only: they pin what Windows' engine
reads, not what tesseract would.
"""
import sys
from pathlib import Path

import pytest
from PIL import Image

from mcp_vroid.driver import actions as A
from mcp_vroid.driver import locate as L
from mcp_vroid.driver.capture import Shot

FIX = Path(__file__).parent / "fixtures"
ocr = pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR")


def shot(name: str) -> Shot:
    p = FIX / name
    return Shot(Image.open(p).convert("RGB"), p, 0, 0, 1.0)


def test_export_pill_is_found_by_colour_below_the_open_accordions():
    s = shot("export-screen.png")
    b = L.find_button(s, region=(int(s.image.width * 0.68), 0,
                                 s.image.width, s.image.height))
    assert b is not None
    assert b.width > 200 and 20 < b.height < 40
    # under "Reduce Bones", well below the top quarter it sits in when closed
    assert b.center[1] > s.image.height * 0.25
    assert s.image.width - b.center[0] < 300


def test_dimmed_pill_behind_the_modal_is_not_a_button():
    s = shot("vrm-settings-vrm0.png")
    assert L.find_button(s, region=(int(s.image.width * 0.68), 0,
                                    s.image.width, s.image.height)) is None


def test_row_tie_break_prefers_the_row_with_more_of_the_needle(monkeypatch):
    # what an engine without confidences returns for the Body tab
    words = [L.Match("Body", 100, 3160, 710, 30, 12),
             L.Match("Size", 100, 3195, 710, 28, 12),
             L.Match("Head", 100, 3160, 780, 32, 12),
             L.Match("Size", 100, 3197, 780, 28, 12),
             L.Match("Head", 100, 3160, 850, 32, 12),
             L.Match("Width", 100, 3197, 850, 38, 12)]
    monkeypatch.setattr(L, "ocr_words", lambda *a, **k: list(words))
    m = L.find_text(Image.new("RGB", (3440, 1369)), "Head Size")
    assert m.top == 780


@ocr
@pytest.mark.parametrize("name, screen", [
    ("start-screen.png", "start"),
    ("editor-body.png", "editor"),
    ("export-screen.png", "export_vrm"),
])
def test_current_screen(name, screen):
    assert A.current_screen(shot(name)) == screen


@ocr
def test_tabs_are_where_the_ui_map_says():
    s = shot("editor-body.png")
    region = (0, 0, A._ax(s, 0.4), A._ay(s, 0.04))
    for tab, x in (("Face", 97), ("Hairstyle", 198), ("Body", 302),
                   ("Outfit", 392), ("Accessories", 509), ("Look", 622)):
        m = L.find_text(s, tab, region=region)
        assert m is not None, tab
        assert abs(m.center[0] - x) <= 4 and abs(m.center[1] - 23) <= 4


@ocr
def test_parameter_row_and_its_numeric_box():
    s = shot("editor-body.png")
    m = A._find_label(s, "Head Size")
    assert m is not None
    body = A._find_label(s, "Body Size")
    assert body is not None and body.center[1] < m.center[1]
    # the numeric box is pinned to the right edge, not at 97.85 % of the width
    x = A._ax(s, A.F_PARAM_VALUE_X)
    assert s.image.width - x == 2560 - int(2560 * A.F_PARAM_VALUE_X) == 56
    box = s.crop((x - 30, m.center[1] - 14, x + 30, m.center[1] + 14))
    assert any("0.000" in w.text for w in L.all_text(box))


@ocr
def test_vrm0_form_captions():
    s = shot("vrm-settings-vrm0.png")
    region = (int(s.image.width * 0.36), 0, int(s.image.width * 0.64),
              s.image.height)
    assert L.find_text(s, "Settings", exact=True) is not None
    # VRM0.0 asks for Title / Creator; the VRM1.0 captions are not there
    assert not L.find_text(s, "Name", exact=True, region=region)
    title = L.find_text(s, "Title", exact=True, region=region)
    creator = L.find_text(s, "Creator", exact=True, region=region)
    assert title is not None and creator is not None
    assert title.center[1] < creator.center[1]
    # the radio caption comes back with letter O for zero
    assert any(L.find_text(s, sp, exact=True)
               for sp in ("VRM0.0", "VRMO.0", "VRMO.O", "VRM0.O"))


@ocr
def test_modal_is_not_mistaken_for_the_page_title():
    # "Export as VRM" must not satisfy the wait for the VRM Settings modal
    s = shot("export-screen.png")
    assert L.find_text(s, "Settings", exact=True) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 backend")
def test_flat_frame_is_reported_blank():
    from mcp_vroid.driver.capture_win32 import is_blank

    assert is_blank(Image.new("RGB", (64, 64), (255, 255, 255)))
    assert is_blank(Image.new("RGB", (64, 64), (0, 0, 0)))
    assert not is_blank(shot("start-screen.png").image)
