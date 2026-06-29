"""Machine-learning dart detection: dataset capture, training, inference.

Layout
------
* :mod:`labels`   — YOLO-pose label format (pure python, always importable).
* :mod:`dataset`  — :class:`DatasetWriter` for building a training set.
* :mod:`capture`  — :class:`AutoLabeler` assisted labelling from the
  classical detector.
* :mod:`infer`    — :class:`YoloDartModel` CPU/ONNX runtime inference.
* :mod:`train`    — Ultralytics training CLI (optional ``ml-train`` extra).

:class:`YoloDartModel` is exposed lazily so that importing this package
(or :mod:`dart_football.vision`) never hard-requires onnxruntime; the
attribute is resolved on first access.
"""

from __future__ import annotations

from dart_football.vision.ml.capture import AutoLabeler, LabelSample
from dart_football.vision.ml.dataset import DatasetWriter
from dart_football.vision.ml.labels import (
    CLASS_NAMES,
    DartLabel,
    class_to_color,
    color_to_class,
)

__all__ = [
    "AutoLabeler",
    "CLASS_NAMES",
    "DartLabel",
    "DatasetWriter",
    "LabelSample",
    "ModelDart",
    "YoloDartModel",
    "class_to_color",
    "color_to_class",
]


def __getattr__(name: str):
    # Lazy: only import infer (and transitively, optionally, onnxruntime)
    # when the model classes are actually requested.
    if name in ("YoloDartModel", "ModelDart"):
        from dart_football.vision.ml import infer

        return getattr(infer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
