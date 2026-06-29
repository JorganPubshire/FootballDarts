"""Computer-vision subsystem for dartboard and dart detection."""

from dart_football.vision.board_detector import BoardCalibration, BoardDetector, ManualCalibrator
from dart_football.vision.dart_detector import (
    DartDetection,
    DartDetector,
    DetectionFrame,
    LockedDart,
)

__all__ = [
    "BoardCalibration",
    "BoardDetector",
    "DartDetection",
    "DartDetector",
    "DetectionFrame",
    "LockedDart",
    "ManualCalibrator",
    "YoloDartModel",
]


def __getattr__(name: str):
    # Lazy: importing the vision package must not require onnxruntime.
    if name == "YoloDartModel":
        from dart_football.vision.ml import YoloDartModel

        return YoloDartModel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
