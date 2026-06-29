"""Runtime inference for the YOLO dart-pose model.

The trained model is exported to ONNX and run on CPU via onnxruntime so
the game has no torch dependency at play time.  An ultralytics ``.pt``
model is also accepted as a convenience fallback (lazy import).

The model is **not** run on the full frame every tick.  The detector
proposes candidate regions of interest from cheap background subtraction
and calls :meth:`YoloDartModel.predict_roi` on a padded crop; the model
then (a) confirms whether the blob is really a dart — rejecting shadows
and lighting changes — and (b) regresses the precise tip contact point.

All coordinate transforms (letterbox, un-letterbox, NMS, output decode)
are isolated as module-level pure functions operating on numpy arrays so
they can be unit-tested with a mocked inference session and no real model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from dart_football.vision.ml.labels import (
    CLASS_NAMES,
    NUM_KEYPOINTS,
    class_to_color,
)

# Channels in a YOLO-pose head output: 4 box + nc classes + nk*3 keypoints.
_NUM_CLASSES = len(CLASS_NAMES)
_BOX_CH = 4
_KPT_CH = NUM_KEYPOINTS * 3
_EXPECTED_CH = _BOX_CH + _NUM_CLASSES + _KPT_CH


@dataclass(frozen=True)
class ModelDart:
    """A dart predicted by the model, in full-frame pixel coordinates."""

    bbox: tuple[int, int, int, int]   # (x, y, w, h)
    tip: tuple[int, int]              # (x, y) contact point
    conf: float
    class_id: int
    flight_color: str | None          # "red" / "blue" / None


class _Session(Protocol):
    """Minimal interface satisfied by onnxruntime.InferenceSession."""

    def run(self, output_names, input_feed): ...
    def get_inputs(self): ...


# ── Pure geometry / decoding helpers ────────────────────────────────────


def letterbox(
    image: np.ndarray,
    new_shape: int = 640,
    color: int = 114,
) -> tuple[np.ndarray, float, tuple[float, float]]:
    """Resize *image* into a square ``new_shape`` keeping aspect ratio.

    Returns ``(padded_image, ratio, (pad_w, pad_h))`` where *ratio* is the
    single scale factor applied and the pads are the left/top padding in
    pixels.  Mirrors the preprocessing Ultralytics applies at train time.
    """
    import cv2

    h, w = image.shape[:2]
    ratio = min(new_shape / h, new_shape / w)
    new_w, new_h = int(round(w * ratio)), int(round(h * ratio))
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    pad_w = (new_shape - new_w) / 2
    pad_h = (new_shape - new_h) / 2
    top, bottom = int(round(pad_h - 0.1)), int(round(pad_h + 0.1))
    left, right = int(round(pad_w - 0.1)), int(round(pad_w + 0.1))
    padded = cv2.copyMakeBorder(
        resized, top, bottom, left, right, cv2.BORDER_CONSTANT,
        value=(color, color, color),
    )
    return padded, ratio, (left, top)


def preprocess(image: np.ndarray, new_shape: int = 640) -> tuple[np.ndarray, float, tuple[float, float]]:
    """Letterbox + BGR→RGB + CHW + scale to a ``[1,3,H,W]`` float32 blob."""
    padded, ratio, pad = letterbox(image, new_shape)
    blob = padded[:, :, ::-1].transpose(2, 0, 1)          # HWC BGR -> CHW RGB
    blob = np.ascontiguousarray(blob, dtype=np.float32) / 255.0
    return blob[None], ratio, pad


def unletterbox_xy(x: float, y: float, ratio: float, pad: tuple[float, float]) -> tuple[float, float]:
    """Map a point from letterboxed-input space back to crop space."""
    pad_w, pad_h = pad
    return (x - pad_w) / ratio, (y - pad_h) / ratio


def xywh_to_xyxy(boxes: np.ndarray) -> np.ndarray:
    """Convert ``(cx, cy, w, h)`` rows to ``(x1, y1, x2, y2)``."""
    out = np.empty_like(boxes)
    out[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
    out[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
    out[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
    out[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
    return out


def nms(boxes_xyxy: np.ndarray, scores: np.ndarray, iou_thresh: float = 0.45) -> list[int]:
    """Greedy non-maximum suppression.  Returns kept indices, best first."""
    if len(boxes_xyxy) == 0:
        return []
    x1, y1, x2, y2 = boxes_xyxy[:, 0], boxes_xyxy[:, 1], boxes_xyxy[:, 2], boxes_xyxy[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]

    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[i] + areas[rest] - inter
        iou = np.where(union > 0, inter / union, 0.0)
        order = rest[iou <= iou_thresh]
    return keep


def decode_pose_output(
    output: np.ndarray,
    conf_thresh: float,
    *,
    num_classes: int = _NUM_CLASSES,
    num_kpts: int = NUM_KEYPOINTS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Decode a raw YOLO-pose ONNX output into filtered detections.

    Accepts ``[1, C, A]`` / ``[C, A]`` (channels-major, the Ultralytics
    export default) or ``[1, A, C]`` / ``[A, C]`` and normalises to
    anchor-major ``[A, C]``.

    Returns ``(boxes_xywh, scores, class_ids, kpts)`` where coordinates are
    in **letterboxed-input** pixel space and ``kpts`` has shape
    ``[N, num_kpts, 3]`` of ``(x, y, conf)``.  Rows are pre-filtered by
    ``conf_thresh`` but **not** NMS-suppressed.
    """
    arr = np.asarray(output)
    if arr.ndim == 3:
        arr = arr[0]
    if arr.ndim != 2:
        raise ValueError(f"unexpected output rank: {arr.shape}")

    channels = _BOX_CH + num_classes + num_kpts * 3
    # Orient to anchor-major [A, C]: the channel dim equals `channels`.
    if arr.shape[0] == channels and arr.shape[1] != channels:
        arr = arr.T
    elif arr.shape[1] != channels and arr.shape[0] != channels:
        raise ValueError(
            f"output shape {arr.shape} matches neither [A,{channels}] nor [{channels},A]"
        )

    boxes = arr[:, :_BOX_CH]
    cls_scores = arr[:, _BOX_CH:_BOX_CH + num_classes]
    kpts = arr[:, _BOX_CH + num_classes:].reshape(-1, num_kpts, 3)

    scores = cls_scores.max(axis=1)
    class_ids = cls_scores.argmax(axis=1)

    keep = scores >= conf_thresh
    return boxes[keep], scores[keep], class_ids[keep], kpts[keep]


# ── Model wrapper ────────────────────────────────────────────────────────


class YoloDartModel:
    """A YOLO dart-pose model run over candidate regions of interest.

    Construct with :meth:`from_file` for a ``.onnx`` (onnxruntime) or
    ``.pt`` (ultralytics) model, or pass a duck-typed *session* directly
    (used in tests).
    """

    def __init__(
        self,
        session: _Session | None = None,
        *,
        imgsz: int = 640,
        conf_thresh: float = 0.35,
        iou_thresh: float = 0.45,
        roi_pad: float = 0.6,
        ultralytics_model: object | None = None,
        input_name: str | None = None,
    ) -> None:
        self._session = session
        self._ultra = ultralytics_model
        self.imgsz = imgsz
        self.conf_thresh = conf_thresh
        self.iou_thresh = iou_thresh
        self.roi_pad = roi_pad
        self._input_name = input_name
        if session is not None and input_name is None:
            try:
                self._input_name = session.get_inputs()[0].name
            except Exception:  # pragma: no cover - defensive
                self._input_name = "images"

    # ── Loading ──────────────────────────────────────────────────────────

    @classmethod
    def from_file(cls, path: str | Path, **kwargs) -> YoloDartModel:
        """Load a model from a ``.onnx`` or ``.pt`` file."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(p)
        if p.suffix.lower() == ".onnx":
            import onnxruntime as ort

            sess = ort.InferenceSession(str(p), providers=["CPUExecutionProvider"])
            return cls(session=sess, **kwargs)
        if p.suffix.lower() == ".pt":
            from ultralytics import YOLO

            return cls(ultralytics_model=YOLO(str(p)), **kwargs)
        raise ValueError(f"unsupported model file: {p.suffix} (want .onnx or .pt)")

    # ── Inference ────────────────────────────────────────────────────────

    def predict_roi(
        self,
        frame: np.ndarray,
        roi: tuple[int, int, int, int],
    ) -> list[ModelDart]:
        """Run the model on a padded crop of *frame* around *roi*.

        *roi* is ``(x, y, w, h)`` in frame pixels (e.g. a background-
        subtraction candidate box).  Returns model darts in full-frame
        coordinates.
        """
        fh, fw = frame.shape[:2]
        x1, y1, x2, y2 = _pad_roi(roi, self.roi_pad, fw, fh)
        if x2 <= x1 or y2 <= y1:
            return []
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return []

        if self._ultra is not None:
            return self._predict_ultra(crop, x1, y1)
        return self._predict_onnx(crop, x1, y1)

    def predict_frame(self, frame: np.ndarray) -> list[ModelDart]:
        """Run the model on the whole frame (debug / fallback path)."""
        h, w = frame.shape[:2]
        return self.predict_roi(frame, (0, 0, w, h))

    # ── Backends ─────────────────────────────────────────────────────────

    def _predict_onnx(self, crop: np.ndarray, off_x: int, off_y: int) -> list[ModelDart]:
        if self._session is None:
            return []
        blob, ratio, pad = preprocess(crop, self.imgsz)
        outputs = self._session.run(None, {self._input_name: blob})
        output = outputs[0]

        boxes, scores, class_ids, kpts = decode_pose_output(output, self.conf_thresh)
        if len(boxes) == 0:
            return []

        boxes_xyxy = xywh_to_xyxy(boxes)
        keep = nms(boxes_xyxy, scores, self.iou_thresh)

        ch, cw = crop.shape[:2]
        results: list[ModelDart] = []
        for i in keep:
            results.append(self._build_dart(
                boxes_xyxy[i], scores[i], int(class_ids[i]), kpts[i, 0],
                ratio, pad, off_x, off_y, cw, ch,
            ))
        return results

    def _build_dart(
        self, box_xyxy, score, class_id, tip_xyc,
        ratio, pad, off_x, off_y, crop_w, crop_h,
    ) -> ModelDart:
        # Box corners: letterbox -> crop -> frame.
        bx1, by1 = unletterbox_xy(box_xyxy[0], box_xyxy[1], ratio, pad)
        bx2, by2 = unletterbox_xy(box_xyxy[2], box_xyxy[3], ratio, pad)
        bx1 = _clamp(bx1, 0, crop_w) + off_x
        by1 = _clamp(by1, 0, crop_h) + off_y
        bx2 = _clamp(bx2, 0, crop_w) + off_x
        by2 = _clamp(by2, 0, crop_h) + off_y

        tx, ty = unletterbox_xy(tip_xyc[0], tip_xyc[1], ratio, pad)
        tx = _clamp(tx, 0, crop_w) + off_x
        ty = _clamp(ty, 0, crop_h) + off_y

        return ModelDart(
            bbox=(int(round(bx1)), int(round(by1)),
                  int(round(bx2 - bx1)), int(round(by2 - by1))),
            tip=(int(round(tx)), int(round(ty))),
            conf=float(score),
            class_id=int(class_id),
            flight_color=class_to_color(int(class_id)),
        )

    def _predict_ultra(self, crop: np.ndarray, off_x: int, off_y: int) -> list[ModelDart]:
        results = self._ultra.predict(  # type: ignore[union-attr]
            crop, imgsz=self.imgsz, conf=self.conf_thresh,
            iou=self.iou_thresh, verbose=False,
        )
        out: list[ModelDart] = []
        for r in results:
            boxes = r.boxes
            kpts = r.keypoints
            if boxes is None or kpts is None:
                continue
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            clss = boxes.cls.cpu().numpy().astype(int)
            kxy = kpts.xy.cpu().numpy()  # [N, num_kpts, 2]
            for j in range(len(xyxy)):
                x1, y1, x2, y2 = xyxy[j]
                tx, ty = kxy[j, 0]
                cid = int(clss[j])
                out.append(ModelDart(
                    bbox=(int(x1) + off_x, int(y1) + off_y,
                          int(x2 - x1), int(y2 - y1)),
                    tip=(int(tx) + off_x, int(ty) + off_y),
                    conf=float(confs[j]),
                    class_id=cid,
                    flight_color=class_to_color(cid),
                ))
        return out


# ── Small helpers ────────────────────────────────────────────────────────


def _pad_roi(
    roi: tuple[int, int, int, int], pad_frac: float, fw: int, fh: int,
) -> tuple[int, int, int, int]:
    """Expand ``(x, y, w, h)`` by *pad_frac* and clamp to the frame.

    Returns ``(x1, y1, x2, y2)``.  Padding gives the model context around
    the blob so the tip is not cropped off at the box edge.
    """
    x, y, w, h = roi
    px = w * pad_frac
    py = h * pad_frac
    x1 = int(max(0, x - px))
    y1 = int(max(0, y - py))
    x2 = int(min(fw, x + w + px))
    y2 = int(min(fh, y + h + py))
    return x1, y1, x2, y2


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v
