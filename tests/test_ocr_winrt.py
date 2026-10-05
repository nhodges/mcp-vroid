"""Shaping Windows.Media.Ocr results into the word boxes locate.py uses.

No WinRT needed: the result is duck-typed.
"""
from types import SimpleNamespace as NS

from mcp_vroid.driver.ocr_winrt import merge_readings, words_from_result


def _word(text, x, y, w, h):
    return NS(text=text, bounding_rect=NS(x=x, y=y, width=w, height=h))


def test_boxes_are_scaled_back_to_the_original_image():
    result = NS(lines=[NS(words=[_word("Head", 200.0, 100.0, 60.0, 24.0),
                                 _word("Size", 270.0, 100.0, 50.0, 24.0)]),
                       NS(words=[_word("  ", 0, 0, 1, 1)])])   # blank: dropped
    assert words_from_result(result, upscale=2.0) == [
        ("Head", 100.0, 100, 50, 30, 12),
        ("Size", 100.0, 135, 50, 25, 12),
    ]


def test_merge_keeps_a_different_reading_of_the_same_spot():
    at_2x = [("Titte", 100.0, 1477, 647, 28, 11),
             ("Required", 100.0, 1520, 648, 50, 11)]
    at_1x = [("Title", 100.0, 1478, 648, 27, 10),
             ("Required", 100.0, 1521, 648, 50, 10)]
    merged = merge_readings(at_2x, at_1x)
    assert [w[0] for w in merged] == ["Titte", "Required", "Title"]


def test_merge_keeps_the_same_word_in_another_place():
    a = [("Required", 100.0, 1520, 648, 50, 11)]
    b = [("Required", 100.0, 1536, 742, 50, 11)]
    assert len(merge_readings(a, b)) == 2
