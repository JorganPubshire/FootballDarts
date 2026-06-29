"""On-disk YOLO dataset layout for dart pose training.

:class:`DatasetWriter` accumulates labelled frames into the standard
Ultralytics directory structure::

    <root>/
        data.yaml
        images/train/<stem>.jpg
        images/val/<stem>.jpg
        labels/train/<stem>.txt
        labels/val/<stem>.txt

Each call to :meth:`add_sample` writes one image plus its label file;
:meth:`add_negative` writes an image with an **empty** label file (a hard
negative — a shadow, a hand, an empty board — that teaches the model what
is *not* a dart).  Samples are deterministically split between train and
val so a given run is reproducible.

Image encoding is delegated to an injectable ``image_writer`` so the bulk
of this module (paths, splitting, ``data.yaml``) can be unit-tested
without OpenCV installed.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from dart_football.vision.ml.labels import (
    CLASS_NAMES,
    KPT_DIMS,
    NUM_KEYPOINTS,
    DartLabel,
    write_labels,
)

if TYPE_CHECKING:
    import numpy as np

ImageWriter = Callable[[Path, "np.ndarray"], None]


def _default_image_writer(path: Path, image: np.ndarray) -> None:
    """Encode *image* (BGR ndarray) to *path* using OpenCV (lazy import)."""
    import cv2

    if not cv2.imwrite(str(path), image):
        raise OSError(f"failed to write image to {path}")


class DatasetWriter:
    """Accumulate labelled frames into a YOLO pose dataset on disk.

    Parameters
    ----------
    root : path
        Dataset root directory (created if absent).
    val_fraction : float
        Fraction of samples routed to the validation split.  Splitting is
        deterministic: every ``round(1 / val_fraction)``-th sample goes to
        val, so re-running produces the same partition.
    image_ext : str
        Image file extension (with dot), e.g. ``".jpg"``.
    image_writer : callable, optional
        ``(path, ndarray) -> None`` used to encode images.  Defaults to an
        OpenCV-based writer; injectable for testing.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        val_fraction: float = 0.2,
        image_ext: str = ".jpg",
        image_writer: ImageWriter | None = None,
    ) -> None:
        self.root = Path(root)
        self.val_fraction = val_fraction
        self.image_ext = image_ext
        self._write_image: ImageWriter = image_writer or _default_image_writer

        self._counter = 0
        self._val_every = max(2, round(1 / val_fraction)) if val_fraction > 0 else 0
        self.counts = {"train": 0, "val": 0, "negatives": 0}

        for split in ("train", "val"):
            (self.root / "images" / split).mkdir(parents=True, exist_ok=True)
            (self.root / "labels" / split).mkdir(parents=True, exist_ok=True)

    # ── Public API ──────────────────────────────────────────────────────

    def add_sample(
        self,
        image: np.ndarray,
        labels: list[DartLabel],
        *,
        stem: str | None = None,
    ) -> tuple[Path, Path]:
        """Write one labelled frame.  Returns ``(image_path, label_path)``."""
        split = self._next_split()
        stem = stem or f"frame_{self._counter:06d}"
        self._counter += 1

        img_path = self.root / "images" / split / f"{stem}{self.image_ext}"
        lbl_path = self.root / "labels" / split / f"{stem}.txt"

        self._write_image(img_path, image)
        write_labels(lbl_path, labels)

        self.counts[split] += 1
        if not labels:
            self.counts["negatives"] += 1
        return img_path, lbl_path

    def add_negative(self, image: np.ndarray, *, stem: str | None = None) -> tuple[Path, Path]:
        """Write a background-only frame (empty label = hard negative)."""
        return self.add_sample(image, [], stem=stem)

    def write_data_yaml(self) -> Path:
        """Write ``data.yaml`` describing the dataset for Ultralytics."""
        names = "\n".join(f"  {i}: {n}" for i, n in enumerate(CLASS_NAMES))
        # Paths are relative to the data.yaml location (the dataset root).
        text = (
            f"path: {self.root.resolve().as_posix()}\n"
            "train: images/train\n"
            "val: images/val\n"
            f"kpt_shape: [{NUM_KEYPOINTS}, {KPT_DIMS}]\n"
            "flip_idx: [0]\n"
            f"nc: {len(CLASS_NAMES)}\n"
            "names:\n"
            f"{names}\n"
        )
        path = self.root / "data.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    @property
    def total(self) -> int:
        return self.counts["train"] + self.counts["val"]

    # ── Internals ────────────────────────────────────────────────────────

    def _next_split(self) -> str:
        if self._val_every and (self._counter % self._val_every == self._val_every - 1):
            return "val"
        return "train"
