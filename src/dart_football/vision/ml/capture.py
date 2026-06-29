"""Assisted data collection for the dart-pose dataset.

Bootstrapping a model needs labelled frames, and hand-labelling is slow.
The trick here: the existing *classical* detector already produces a
decent first guess (bounding box + geometric tip + HSV colour) for most
darts.  :class:`AutoLabeler` wraps that guess in an editable
:class:`LabelSample` so the human only has to *correct* mistakes — click
to nudge the tip, toggle the colour, accept or discard — rather than draw
every label from scratch.

Negatives (shadows, hands, empty board under changed lighting) are saved
with no label so the model learns to reject them.

This module depends only on :mod:`dart_football.vision.ml.labels` and
:mod:`dart_football.vision.ml.dataset`; it accepts any duck-typed
detection object exposing ``bbox``, ``tip`` and ``flight_color`` so it
does not pull in the OpenCV-heavy detector just to be imported/tested.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from dart_football.vision.ml.dataset import DatasetWriter
from dart_football.vision.ml.labels import DartLabel, color_to_class

if TYPE_CHECKING:
    import numpy as np


class _Detection(Protocol):
    bbox: tuple[int, int, int, int]
    tip: tuple[int, int]
    flight_color: object  # has a `.value` str, or is a str


def _color_str(flight_color: object) -> str | None:
    """Normalise a FlightColor enum / string to "red"/"blue"/None."""
    value = getattr(flight_color, "value", flight_color)
    if value in ("red", "blue"):
        return value  # type: ignore[return-value]
    return None


@dataclass(frozen=True)
class LabelSample:
    """An editable, pre-filled label for one dart in one frame.

    Immutable; the ``with_*`` helpers return updated copies so the demo
    can rebind its current sample after each edit.
    """

    img_w: int
    img_h: int
    bbox: tuple[int, int, int, int]
    tip: tuple[int, int]
    flight_color: str | None

    def with_tip(self, x: int, y: int) -> LabelSample:
        return replace(self, tip=(int(x), int(y)))

    def with_color(self, color: str | None) -> LabelSample:
        return replace(self, flight_color=color)

    def to_label(self) -> DartLabel:
        """Convert to a normalised :class:`DartLabel`."""
        return DartLabel.from_pixels(
            class_id=color_to_class(self.flight_color),
            bbox=self.bbox,
            tip=self.tip,
            img_w=self.img_w,
            img_h=self.img_h,
        )


class AutoLabeler:
    """Propose and persist labels, seeded by the classical detector.

    Parameters
    ----------
    dataset : DatasetWriter
        Destination for accepted samples and negatives.
    """

    def __init__(self, dataset: DatasetWriter) -> None:
        self.dataset = dataset

    # ── Proposing ────────────────────────────────────────────────────────

    @staticmethod
    def propose(frame: np.ndarray, detection: _Detection) -> LabelSample:
        """Wrap one classical detection as an editable :class:`LabelSample`."""
        h, w = frame.shape[:2]
        return LabelSample(
            img_w=w,
            img_h=h,
            bbox=tuple(detection.bbox),  # type: ignore[arg-type]
            tip=tuple(detection.tip),    # type: ignore[arg-type]
            flight_color=_color_str(detection.flight_color),
        )

    @classmethod
    def propose_many(
        cls, frame: np.ndarray, detections: list[_Detection],
    ) -> list[LabelSample]:
        return [cls.propose(frame, d) for d in detections]

    # ── Persisting ───────────────────────────────────────────────────────

    def save(
        self, frame: np.ndarray, samples: list[LabelSample], *, stem: str | None = None,
    ) -> tuple[Path, Path]:
        """Save *frame* with the labels from *samples*."""
        labels = [s.to_label() for s in samples]
        return self.dataset.add_sample(frame, labels, stem=stem)

    def save_negative(self, frame: np.ndarray, *, stem: str | None = None) -> tuple[Path, Path]:
        """Save *frame* as a hard negative (no darts)."""
        return self.dataset.add_negative(frame, stem=stem)

    def finalize(self) -> Path:
        """Write ``data.yaml``; call once collection is done."""
        return self.dataset.write_data_yaml()
