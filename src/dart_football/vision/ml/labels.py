"""YOLO-pose label format for dart detection.

A dart is labelled as a single bounding box plus one keypoint (the tip
contact point).  This matches the layout produced by Ultralytics' pose
trainer and consumed by it again at training time.

Label-file format (one line per dart, all coordinates normalised to the
image size, in ``[0, 1]``)::

    <class> <cx> <cy> <w> <h> <tip_x> <tip_y> <vis>

* ``class``   integer class id (see :data:`CLASS_NAMES`).
* ``cx cy``   bounding-box centre.
* ``w h``     bounding-box width / height.
* ``tip_x``   tip keypoint x.
* ``tip_y``   tip keypoint y.
* ``vis``     keypoint visibility: 0 = absent, 1 = occluded, 2 = visible.

A frame with **no** dart is represented by an empty (or absent) label
file — Ultralytics treats such images as hard negatives, which is exactly
how we teach the model to ignore shadows, hands, and lighting changes.

This module is pure Python + numpy, has no OpenCV / onnxruntime /
ultralytics dependency, and is therefore safe to import and unit-test
anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# ── Class ids ───────────────────────────────────────────────────────────
# We keep the flight colour in the class so the model can also classify
# red vs. blue darts.  ``DART`` is a colour-agnostic fallback used when a
# sample's colour is unknown.
CLASS_NAMES: list[str] = ["dart", "dart_red", "dart_blue"]

CLASS_DART = 0
CLASS_DART_RED = 1
CLASS_DART_BLUE = 2

# One keypoint (the tip), with (x, y, visibility) per keypoint.
NUM_KEYPOINTS = 1
KPT_DIMS = 3

VIS_ABSENT = 0
VIS_OCCLUDED = 1
VIS_VISIBLE = 2


def color_to_class(flight_color: str | None) -> int:
    """Map a flight-colour string ("red"/"blue"/None) to a class id."""
    if flight_color == "red":
        return CLASS_DART_RED
    if flight_color == "blue":
        return CLASS_DART_BLUE
    return CLASS_DART


def class_to_color(class_id: int) -> str | None:
    """Inverse of :func:`color_to_class`."""
    if class_id == CLASS_DART_RED:
        return "red"
    if class_id == CLASS_DART_BLUE:
        return "blue"
    return None


@dataclass(frozen=True)
class DartLabel:
    """One labelled dart in normalised image coordinates (all in [0, 1])."""

    class_id: int
    cx: float
    cy: float
    w: float
    h: float
    tip_x: float
    tip_y: float
    vis: int = VIS_VISIBLE

    # ── Construction from pixel coordinates ──────────────────────────────

    @classmethod
    def from_pixels(
        cls,
        *,
        class_id: int,
        bbox: tuple[int, int, int, int],
        tip: tuple[int, int],
        img_w: int,
        img_h: int,
        vis: int = VIS_VISIBLE,
    ) -> DartLabel:
        """Build a label from a pixel bbox ``(x, y, w, h)`` and tip ``(px, py)``.

        Coordinates are clamped into ``[0, 1]`` after normalisation so a
        tip sitting exactly on the image border still produces a valid
        label.
        """
        x, y, w, h = bbox
        px, py = tip
        iw = float(max(1, img_w))
        ih = float(max(1, img_h))
        return cls(
            class_id=class_id,
            cx=_clamp01((x + w / 2) / iw),
            cy=_clamp01((y + h / 2) / ih),
            w=_clamp01(w / iw),
            h=_clamp01(h / ih),
            tip_x=_clamp01(px / iw),
            tip_y=_clamp01(py / ih),
            vis=vis,
        )

    def to_pixels(self, img_w: int, img_h: int) -> tuple[tuple[int, int, int, int], tuple[int, int]]:
        """Return ``(bbox=(x, y, w, h), tip=(px, py))`` in pixels."""
        iw, ih = float(img_w), float(img_h)
        w = self.w * iw
        h = self.h * ih
        x = self.cx * iw - w / 2
        y = self.cy * ih - h / 2
        return (
            (int(round(x)), int(round(y)), int(round(w)), int(round(h))),
            (int(round(self.tip_x * iw)), int(round(self.tip_y * ih))),
        )

    # ── Serialisation ────────────────────────────────────────────────────

    def to_line(self) -> str:
        """Serialise to a single YOLO-pose label line."""
        return (
            f"{self.class_id} "
            f"{self.cx:.6f} {self.cy:.6f} {self.w:.6f} {self.h:.6f} "
            f"{self.tip_x:.6f} {self.tip_y:.6f} {self.vis}"
        )

    @classmethod
    def from_line(cls, line: str) -> DartLabel:
        """Parse a single YOLO-pose label line."""
        parts = line.split()
        if len(parts) != 8:
            raise ValueError(
                f"expected 8 fields (class cx cy w h tip_x tip_y vis), got {len(parts)}: {line!r}"
            )
        return cls(
            class_id=int(float(parts[0])),
            cx=float(parts[1]),
            cy=float(parts[2]),
            w=float(parts[3]),
            h=float(parts[4]),
            tip_x=float(parts[5]),
            tip_y=float(parts[6]),
            vis=int(float(parts[7])),
        )


def write_labels(path: str | Path, labels: list[DartLabel]) -> None:
    """Write a list of labels to *path* (one per line).

    An empty list writes an empty file, which YOLO interprets as a
    negative (background-only) sample.
    """
    text = "\n".join(label.to_line() for label in labels)
    if text:
        text += "\n"
    Path(path).write_text(text, encoding="utf-8")


def read_labels(path: str | Path) -> list[DartLabel]:
    """Read labels from *path*.  Returns ``[]`` for a missing/empty file."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[DartLabel] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(DartLabel.from_line(line))
    return out


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v
