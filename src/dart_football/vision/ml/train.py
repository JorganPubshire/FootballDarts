"""Train the dart-pose model with Ultralytics YOLO and export to ONNX.

This is a thin convenience wrapper — it requires the optional training
extra (``pip install -e .[ml-train]``, which pulls torch via ultralytics).
The game itself never imports this module.

Usage
-----
After collecting a dataset with the demo's capture mode::

    python -m dart_football.vision.ml.train --data path/to/dataset/data.yaml

It trains a small ``yolo11n-pose`` model and exports the best weights to
ONNX next to the run directory.  Copy the resulting ``.onnx`` to
``dart_model.onnx`` (the demo's default load path) to use it at play time.

The split between training (ultralytics/torch) and inference
(onnxruntime, see :mod:`dart_football.vision.ml.infer`) is deliberate so
the CPU-only game install stays lean.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def train(
    data_yaml: str | Path,
    *,
    base_model: str = "yolo11n-pose.pt",
    epochs: int = 100,
    imgsz: int = 640,
    batch: int = 16,
    device: str = "cpu",
    project: str | Path = "runs/dart_pose",
    name: str = "train",
    export_onnx: bool = True,
) -> Path | None:
    """Train and (optionally) export.  Returns the exported ONNX path."""
    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise SystemExit(
            "ultralytics is required for training. Install it with:\n"
            "    pip install -e .[ml-train]"
        ) from exc

    data_yaml = Path(data_yaml)
    if not data_yaml.exists():
        raise SystemExit(f"data.yaml not found: {data_yaml}")

    model = YOLO(base_model)
    model.train(
        data=str(data_yaml),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
        project=str(project),
        name=name,
    )

    if not export_onnx:
        return None

    best = Path(project) / name / "weights" / "best.pt"
    if not best.exists():
        print(f"warning: best weights not found at {best}; skipping export")
        return None

    exported = YOLO(str(best)).export(format="onnx", imgsz=imgsz, opset=12)
    onnx_path = Path(exported)
    print(f"\nExported ONNX model: {onnx_path}")
    print("Copy it to 'dart_model.onnx' to use it in the demo / game.")
    return onnx_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the dart-pose YOLO model.")
    parser.add_argument("--data", required=True, help="Path to dataset data.yaml")
    parser.add_argument("--base", default="yolo11n-pose.pt", help="Base model weights")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument(
        "--device", default="cpu",
        help="Training device: 'cpu', '0' (GPU 0), etc. Inference is always CPU.",
    )
    parser.add_argument("--no-export", action="store_true", help="Skip ONNX export")
    args = parser.parse_args()

    train(
        args.data,
        base_model=args.base,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        export_onnx=not args.no_export,
    )


if __name__ == "__main__":
    main()
