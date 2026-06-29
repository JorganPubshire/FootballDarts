"""Tests for the ML dart-detection subsystem.

These run without onnxruntime / ultralytics installed: the model session
is mocked and the coordinate / decoding math is exercised directly.  They
also assert that :class:`DartDetector` keeps working with no model
(classical fallback) and rejects shadow ROIs when a model is present.
"""

from __future__ import annotations

import numpy as np
import pytest

from dart_football.vision.dart_detector import DartDetector, FlightColor
from dart_football.vision.ml import labels
from dart_football.vision.ml.capture import AutoLabeler, LabelSample
from dart_football.vision.ml.dataset import DatasetWriter
from dart_football.vision.ml.infer import (
    ModelDart,
    YoloDartModel,
    decode_pose_output,
    letterbox,
    nms,
    preprocess,
    unletterbox_xy,
    xywh_to_xyxy,
)
from dart_football.vision.ml.labels import DartLabel

# ── labels ───────────────────────────────────────────────────────────────


def test_dartlabel_line_round_trip():
    lbl = DartLabel(class_id=1, cx=0.5, cy=0.25, w=0.1, h=0.2, tip_x=0.55, tip_y=0.35, vis=2)
    parsed = DartLabel.from_line(lbl.to_line())
    assert parsed == lbl


def test_dartlabel_from_pixels_normalises_and_clamps():
    lbl = DartLabel.from_pixels(
        class_id=labels.CLASS_DART_BLUE,
        bbox=(10, 20, 40, 60),
        tip=(30, 80),
        img_w=100,
        img_h=200,
    )
    assert lbl.cx == pytest.approx(0.30)   # (10 + 40/2) / 100
    assert lbl.cy == pytest.approx(0.25)   # (20 + 60/2) / 200
    assert lbl.w == pytest.approx(0.40)
    assert lbl.h == pytest.approx(0.30)
    assert lbl.tip_x == pytest.approx(0.30)
    assert lbl.tip_y == pytest.approx(0.40)

    # Out-of-frame tip is clamped into [0, 1].
    clamped = DartLabel.from_pixels(
        class_id=0, bbox=(0, 0, 10, 10), tip=(-5, 500), img_w=100, img_h=100,
    )
    assert clamped.tip_x == 0.0
    assert clamped.tip_y == 1.0


def test_pixels_round_trip():
    bbox = (10, 20, 40, 60)
    tip = (30, 80)
    lbl = DartLabel.from_pixels(class_id=0, bbox=bbox, tip=tip, img_w=100, img_h=200)
    out_bbox, out_tip = lbl.to_pixels(100, 200)
    assert out_bbox == bbox
    assert out_tip == tip


def test_write_read_labels(tmp_path):
    path = tmp_path / "frame.txt"
    items = [
        DartLabel(0, 0.1, 0.1, 0.2, 0.2, 0.1, 0.2, 2),
        DartLabel(2, 0.8, 0.8, 0.1, 0.1, 0.82, 0.85, 2),
    ]
    labels.write_labels(path, items)
    assert labels.read_labels(path) == items


def test_read_labels_missing_and_empty(tmp_path):
    assert labels.read_labels(tmp_path / "nope.txt") == []
    empty = tmp_path / "empty.txt"
    labels.write_labels(empty, [])
    assert empty.read_text() == ""          # empty = hard negative
    assert labels.read_labels(empty) == []


def test_bad_label_line_raises():
    with pytest.raises(ValueError):
        DartLabel.from_line("0 0.1 0.2 0.3")


def test_color_class_mapping():
    assert labels.color_to_class("red") == labels.CLASS_DART_RED
    assert labels.color_to_class("blue") == labels.CLASS_DART_BLUE
    assert labels.color_to_class(None) == labels.CLASS_DART
    assert labels.class_to_color(labels.CLASS_DART_RED) == "red"
    assert labels.class_to_color(labels.CLASS_DART) is None


# ── infer: pure geometry / decode ─────────────────────────────────────────


def test_letterbox_shape_and_pad():
    img = np.zeros((50, 100, 3), dtype=np.uint8)
    padded, ratio, (pad_w, pad_h) = letterbox(img, 64)
    assert padded.shape == (64, 64, 3)
    assert ratio == pytest.approx(0.64)
    assert pad_w == 0
    assert pad_h == 16


def test_unletterbox_inverts_forward_mapping():
    _, ratio, pad = letterbox(np.zeros((50, 100, 3), dtype=np.uint8), 64)
    # Forward: crop point -> letterbox space.
    cx, cy = 37.0, 21.0
    lx = cx * ratio + pad[0]
    ly = cy * ratio + pad[1]
    bx, by = unletterbox_xy(lx, ly, ratio, pad)
    assert bx == pytest.approx(cx)
    assert by == pytest.approx(cy)


def test_preprocess_blob_format():
    img = np.full((40, 80, 3), 255, dtype=np.uint8)
    blob, ratio, pad = preprocess(img, 64)
    assert blob.shape == (1, 3, 64, 64)
    assert blob.dtype == np.float32
    assert 0.0 <= blob.max() <= 1.0


def test_xywh_to_xyxy():
    boxes = np.array([[50.0, 60.0, 20.0, 40.0]])
    out = xywh_to_xyxy(boxes)
    assert out.tolist() == [[40.0, 40.0, 60.0, 80.0]]


def test_nms_suppresses_overlap_keeps_distinct():
    boxes = np.array([
        [0, 0, 10, 10],       # A
        [1, 1, 11, 11],       # overlaps A heavily
        [100, 100, 110, 110],  # far away
    ], dtype=float)
    scores = np.array([0.9, 0.8, 0.7])
    keep = nms(boxes, scores, iou_thresh=0.45)
    assert keep[0] == 0           # highest score first
    assert 2 in keep              # distant box kept
    assert 1 not in keep          # overlapping box suppressed


def _make_pose_output(channels_major: bool):
    """Build a synthetic YOLO-pose output with one strong detection."""
    # channels = 4 box + 3 cls + 3 kpt = 10
    anchor0 = [50.0, 60.0, 20.0, 40.0, 0.1, 0.9, 0.2, 50.0, 80.0, 0.95]
    anchor1 = [10.0, 10.0, 5.0, 5.0, 0.1, 0.1, 0.05, 10.0, 12.0, 0.1]
    arr = np.array([anchor0, anchor1], dtype=np.float32)   # [A=2, C=10]
    if channels_major:
        arr = arr.T                                        # [C=10, A=2]
    return arr[None]                                       # add batch dim


@pytest.mark.parametrize("channels_major", [True, False])
def test_decode_pose_output(channels_major):
    out = _make_pose_output(channels_major)
    boxes, scores, class_ids, kpts = decode_pose_output(out, conf_thresh=0.5)
    assert len(boxes) == 1                       # weak anchor filtered out
    assert scores[0] == pytest.approx(0.9)
    assert class_ids[0] == 1                      # red dart
    assert boxes[0].tolist() == [50.0, 60.0, 20.0, 40.0]
    assert kpts[0, 0].tolist() == [50.0, 80.0, pytest.approx(0.95)]


# ── infer: YoloDartModel with a mocked session ────────────────────────────


class _FakeInput:
    name = "images"


class _FakeSession:
    """Mimics onnxruntime.InferenceSession enough for YoloDartModel."""

    def __init__(self, output):
        self._output = output
        self.last_feed = None

    def get_inputs(self):
        return [_FakeInput()]

    def run(self, output_names, input_feed):
        self.last_feed = input_feed
        return [self._output]


def test_predict_roi_with_mocked_session():
    output = _make_pose_output(channels_major=True)
    sess = _FakeSession(output)
    model = YoloDartModel(session=sess, imgsz=64, conf_thresh=0.5)

    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    darts = model.predict_roi(frame, (40, 40, 40, 40))

    assert len(darts) == 1
    d = darts[0]
    assert isinstance(d, ModelDart)
    assert d.conf == pytest.approx(0.9)
    assert d.flight_color == "red"
    # Tip maps back into the frame.
    assert 0 <= d.tip[0] < 160
    assert 0 <= d.tip[1] < 120
    # The session actually received a properly shaped blob.
    assert sess.last_feed["images"].shape == (1, 3, 64, 64)


def test_predict_roi_empty_when_below_threshold():
    output = _make_pose_output(channels_major=True)
    sess = _FakeSession(output)
    model = YoloDartModel(session=sess, imgsz=64, conf_thresh=0.99)  # nothing passes
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    assert model.predict_roi(frame, (40, 40, 40, 40)) == []


# ── DatasetWriter ─────────────────────────────────────────────────────────


def _stub_image_writer(records):
    def _write(path, image):
        records.append((path, getattr(image, "shape", None)))
    return _write


def test_dataset_writer_split_and_yaml(tmp_path):
    records: list = []
    dw = DatasetWriter(
        tmp_path / "ds", val_fraction=0.2, image_writer=_stub_image_writer(records),
    )
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    lab = [DartLabel(0, 0.5, 0.5, 0.2, 0.2, 0.5, 0.6, 2)]
    for _ in range(6):
        dw.add_sample(img, lab)

    # val_every = round(1/0.2) = 5 -> one of six routed to val.
    assert dw.counts["val"] == 1
    assert dw.counts["train"] == 5
    assert dw.total == 6
    assert len(records) == 6

    yaml_path = dw.write_data_yaml()
    text = yaml_path.read_text()
    assert "kpt_shape: [1, 3]" in text
    assert "train: images/train" in text
    assert "0: dart" in text
    # Label files were actually written next to images.
    train_labels = list((tmp_path / "ds" / "labels" / "train").glob("*.txt"))
    assert len(train_labels) == 5


def test_dataset_writer_negative(tmp_path):
    records: list = []
    dw = DatasetWriter(tmp_path / "ds", image_writer=_stub_image_writer(records))
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    img_path, lbl_path = dw.add_negative(img)
    assert dw.counts["negatives"] == 1
    assert lbl_path.read_text() == ""        # empty label = hard negative


# ── AutoLabeler ───────────────────────────────────────────────────────────


class _FakeDetection:
    def __init__(self, bbox, tip, color):
        self.bbox = bbox
        self.tip = tip
        self.flight_color = color


def test_autolabeler_propose_and_edit():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    det = _FakeDetection((10, 20, 30, 40), (25, 55), FlightColor.RED)
    sample = AutoLabeler.propose(frame, det)
    assert isinstance(sample, LabelSample)
    assert sample.img_w == 200 and sample.img_h == 100
    assert sample.flight_color == "red"

    moved = sample.with_tip(99, 88).with_color("blue")
    lbl = moved.to_label()
    assert lbl.class_id == labels.CLASS_DART_BLUE
    bbox, tip = lbl.to_pixels(200, 100)
    assert tip == (99, 88)


# ── DartDetector integration (fallback + model path) ──────────────────────


def _frame_with_blob():
    """A clean background and a frame with one bright elongated blob."""
    bg = np.full((200, 200, 3), 40, dtype=np.uint8)
    frame = bg.copy()
    frame[60:120, 90:115] = 255           # ~60x25 bright rectangle
    return bg, frame


class _FakeModel:
    """Stand-in for YoloDartModel used by the detector."""

    def __init__(self, darts):
        self._darts = darts
        self.calls = 0

    def predict_roi(self, frame, roi):
        self.calls += 1
        return list(self._darts)


def test_detector_classical_fallback_no_model():
    bg, frame = _frame_with_blob()
    det = DartDetector(board_only=False)        # no model -> classical path
    det.set_background(bg)
    results = det.detect(frame)
    assert len(results) >= 1                     # the blob is detected classically


def test_detector_model_rejects_shadow():
    bg, frame = _frame_with_blob()
    # Model finds nothing in the candidate ROI -> treated as shadow/noise.
    det = DartDetector(board_only=False, model=_FakeModel([]))
    det.set_background(bg)
    assert det.detect(frame) == []


def test_detector_model_supplies_tip_and_colour():
    bg, frame = _frame_with_blob()
    md = ModelDart(bbox=(90, 60, 25, 60), tip=(102, 118), conf=0.8,
                   class_id=labels.CLASS_DART_BLUE, flight_color="blue")
    det = DartDetector(board_only=False, model=_FakeModel([md]))
    det.set_background(bg)
    results = det.detect(frame)
    assert len(results) == 1
    assert results[0].tip == (102, 118)          # tip comes from the model
    assert results[0].flight_color is FlightColor.BLUE
    assert results[0].confidence == pytest.approx(0.8)


def test_detector_dedupes_overlapping_model_darts():
    bg, frame = _frame_with_blob()
    # Two near-identical darts (e.g. from overlapping ROIs) collapse to one.
    md1 = ModelDart((90, 60, 25, 60), (102, 118), 0.9, 0, None)
    md2 = ModelDart((91, 61, 25, 60), (104, 119), 0.6, 0, None)
    det = DartDetector(board_only=False, model=_FakeModel([md1, md2]))
    det.set_background(bg)
    results = det.detect(frame)
    assert len(results) == 1
    assert results[0].confidence == pytest.approx(0.9)   # higher-conf kept
