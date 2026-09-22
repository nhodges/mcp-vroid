"""A screenshot plus the mapping from its pixels back to layout coordinates.

Shared by every capture backend: OCR hands image-pixel coords to a Shot, and
the Shot turns them into the coordinates the input backend clicks at.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .paths import CAPTURES


def next_capture_path(tag: str = "") -> Path:
    n = 0
    for p in CAPTURES.glob("[0-9][0-9][0-9]*.png"):
        try:
            n = max(n, int(p.name[:3]))
        except ValueError:
            pass
    name = f"{n + 1:03d}" + (f"-{tag}" if tag else "") + ".png"
    return CAPTURES / name


@dataclass
class Shot:
    image: Image.Image
    path: Path
    ox: int          # region origin x, layout coords
    oy: int
    scale: float     # image px per layout unit

    @property
    def size(self):
        return self.image.size

    def to_window(self, px: float, py: float) -> tuple[float, float]:
        """Image pixel -> window-relative layout coords."""
        return (px / self.scale, py / self.scale)

    def to_layout(self, px: float, py: float) -> tuple[float, float]:
        return (self.ox + px / self.scale, self.oy + py / self.scale)

    def crop(self, box) -> "Shot":
        l, t, r, b = box
        return Shot(self.image.crop(box), self.path,
                    int(self.ox + l / self.scale), int(self.oy + t / self.scale),
                    self.scale)
