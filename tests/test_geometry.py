"""Coordinate maths that has to be right before any event is injected."""
import sys

import pytest

from mcp_vroid.driver import actions as A

win32 = pytest.mark.skipif(sys.platform != "win32", reason="Win32 backend")


def test_edge_px_is_the_plain_fraction_on_the_reference_size():
    # the Linux reference capture: nothing may move there
    for frac in (0.0090, 0.0160, 0.0861, 0.4, 0.9435, 0.9625, 0.9785):
        assert A.edge_px(frac, 2560, 2560) == int(2560 * frac)
        assert A.edge_px(frac, 1440, 1440) == int(1440 * frac)


def test_edge_px_keeps_the_distance_to_the_nearer_edge():
    # the share/export icon sits 96 px from the right edge, whatever the width
    assert 2560 - A.edge_px(0.9625, 2560, 2560) == 96
    assert 3440 - A.edge_px(0.9625, 3440, 2560) == 96
    assert 1024 - A.edge_px(0.9625, 1024, 2560) == 96
    # the icon rail sits 24 px from the left edge
    assert A.edge_px(0.0094, 3440, 2560) == A.edge_px(0.0094, 1024, 2560) == 24


@win32
def test_to_absolute_spans_the_virtual_desktop():
    from mcp_vroid.driver.input_win32 import to_absolute

    virt = (0, 0, 6000, 1440)           # 2560 + 3440 wide, side by side
    assert to_absolute(0, 0, virt) == (0, 0)
    assert to_absolute(5999, 1439, virt) == (65535, 65535)
    # a point on the second monitor must not be scaled by the first one's width
    x, _ = to_absolute(4280, 720, virt)
    assert round(x * 5999 / 65535) == 4280


@win32
def test_to_absolute_with_a_monitor_left_of_the_primary():
    from mcp_vroid.driver.input_win32 import to_absolute

    virt = (-1920, -200, 1920 + 2560, 1640)
    assert to_absolute(-1920, -200, virt) == (0, 0)
    x, y = to_absolute(0, 0, virt)      # the primary's origin is mid-grid
    assert round(x * (virt[2] - 1) / 65535) + virt[0] == 0
    assert round(y * (virt[3] - 1) / 65535) + virt[1] == 0


@win32
def test_corner_hit_checks_every_monitor():
    from mcp_vroid.driver.input_win32 import corner_hit

    mons = [(2560, 0, 6000, 1440), (0, 0, 2560, 1440)]
    assert corner_hit(0, 0, mons)
    assert corner_hit(5999, 1439, mons)
    assert corner_hit(2557, 2, mons)          # top-right of the left monitor
    assert corner_hit(2561, 1438, mons)       # bottom-left of the right one
    assert not corner_hit(1280, 0, mons)      # an edge is not a corner
    assert not corner_hit(2560, 700, mons)
    assert not corner_hit(4000, 700, mons)


@win32
def test_window_contains_is_the_client_rectangle():
    from mcp_vroid.driver.window_win32 import Window

    w = Window("0x1", "UnityWndClass", "VRoid Studio", 2560, 23, 3440, 1369,
               0, True)
    assert w.contains(2560, 23) and w.contains(5999, 1391)
    assert not w.contains(2559, 700)          # the other monitor
    assert not w.contains(3000, 22)           # the title bar
    assert not w.contains(6000, 700) and not w.contains(3000, 1392)
    assert w.to_layout(100, 50) == (2660, 73)


@win32
def test_desktop_chords_are_refused():
    from mcp_vroid.driver import input_win32 as I

    alt, ctrl, shift = I.VK_MENU, I.VK_CONTROL, I.VK_SHIFT
    for mods, key in (([alt], "F4"), ([alt], "Tab"), ([ctrl], "Escape"),
                      ([ctrl, alt], "Delete")):
        with pytest.raises(ValueError):
            I.check_combo(mods, I._vk(key)[0])
    for name in ("super", "win", "Super_L", "meta"):
        with pytest.raises(ValueError):
            I._vk(name)
    # the shortcuts the flows do use stay allowed
    I.check_combo([ctrl], I._vk("a")[0])
    I.check_combo([ctrl, shift], I._vk("s")[0])
    I.check_combo([], I._vk("F4")[0])
