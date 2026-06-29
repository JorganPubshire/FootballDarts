"""Standalone dart-detection demo.

Run with::

    python -m dart_football.vision.demo          # default camera 0
    python -m dart_football.vision.demo --camera 1
    python -m dart_football.vision.demo --camera rtsp://192.168.1.100/stream

Controls (keyboard)
-------------------
    b     Auto-detect board
    c     Enter manual calibration mode (click board edge points)
    a     Enter adjustment mode (tweak calibration — rotation, axes, bullseye)
    d     Toggle live dart detection on/off
    e     Toggle detection mode (event-driven vs temporal smoothing)
    g     Toggle ML detection (loads dart_model.onnx; falls back to classical)
    t     Enter dataset capture / labelling mode (collect training data)
    s     Set current frame as clean background (required before dart detection)
    r     Reset (clear calibration and background)
    o     Toggle board overlay on/off
    m     Toggle foreground mask debug view
    f     Toggle board-only filter (ignore darts outside board)
    +/-   Adjust detection sensitivity (morph kernel size)
    S     Save current calibration to board_cal.json
    L     Load calibration from board_cal.json
    q/X   Quit (keyboard q or window close button)

Dataset capture mode  ([t] to enter)
-------------------------------------
The classical detector pre-labels each thrown dart so you only correct
mistakes.  Collect a few hundred darts (varied lighting/positions) plus
some negatives, then train with
``python -m dart_football.vision.ml.train --data dart_dataset/data.yaml``.

    space   Freeze the current frame and its auto-proposed labels
    click   Move the active dart's tip to the cursor (on a frozen frame)
    j       Cycle which dart is active
    r/b/u   Set active dart colour red / blue / unknown
    Enter   Save the frozen frame + labels to the dataset
    x       Discard the frozen frame without saving
    n       Save the current (live) frame as a hard negative (no darts)
    t/Esc   Exit capture mode (writes data.yaml)

Manual calibration mode
-----------------------
    Click   Add a point on the board edge
    z       Undo last point
    Enter   Accept ellipse fit (need >= 5 points)
    Esc     Cancel and return to normal mode

Learning from calibrations
--------------------------
Every accepted calibration (after the adjustment step) is saved to the
``board_exemplars/`` directory as a frame + calibration pair.  The next
time you press [b] to auto-detect, the detector ORB-matches the live
frame against these real exemplars first, so auto-detection gets more
reliable the more you calibrate this camera/board.

The window title shows the current state and FPS.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from dart_football.vision.board_detector import (
    BoardCalibration,
    BoardDetector,
    CalibrationAdjuster,
    ManualCalibrator,
)
from dart_football.vision.dart_detector import (
    DartDetection,
    DartDetector,
)
from dart_football.vision.ml.capture import AutoLabeler, LabelSample
from dart_football.vision.ml.dataset import DatasetWriter

# ── Default file paths ─────────────────────────────────────────────────
_DEFAULT_CAL_PATH = Path("board_cal.json")
_DEFAULT_MODEL_PATH = Path("dart_model.onnx")
_DEFAULT_DATASET_DIR = Path("dart_dataset")


# ── UI State ────────────────────────────────────────────────────────────

class DemoState:
    """Mutable state bag for the demo loop."""

    def __init__(self) -> None:
        self.board_detector = BoardDetector()
        self.dart_detector = DartDetector()
        self.calibration: BoardCalibration | None = None
        self.dart_detection_active = False
        self.use_event_detection = True  # use detect_events by default
        self.show_overlay = True
        self.show_mask = False
        self.detections: list[DartDetection] = []
        self.pending_count: int = 0
        self.status_message = "Press [b] auto-detect  |  [c] manual calibration"
        self.status_until = 0.0
        self.fps = 0.0

        # Manual calibration state.
        self.manual_mode = False
        self.manual_calibrator = ManualCalibrator()

        # Post-calibration adjustment state.
        self.adjust_mode = False
        self.adjuster: CalibrationAdjuster | None = None

        # ML detection state.
        self.model: object | None = None     # loaded YoloDartModel (engine-agnostic)
        self.model_loaded = False

        # Dataset capture / labelling state.
        self.capture_mode = False
        self.auto_labeler: AutoLabeler | None = None
        self.capture_frame: np.ndarray | None = None        # frozen frame being labelled
        self.capture_samples: list[LabelSample] = []         # editable labels for it
        self.capture_active = 0                               # index of sample being edited
        self.capture_saved = 0                               # samples saved this session

    def set_status(self, msg: str, duration: float = 3.0) -> None:
        self.status_message = msg
        self.status_until = time.monotonic() + duration

    @property
    def current_status(self) -> str:
        if self.manual_mode or self.adjust_mode or self.capture_mode:
            # These modes draw their own status bar.
            return ""
        if time.monotonic() < self.status_until:
            return self.status_message
        parts: list[str] = []
        if self.calibration:
            parts.append("Board: OK")
        else:
            parts.append("Board: [b]auto [c]manual")
        if self.dart_detector.has_background:
            parts.append("BG: set")
        else:
            parts.append("BG: [s] to set")
        if self.dart_detection_active:
            n = len(self.detections)
            filt = "board-only" if self.dart_detector.board_only else "all"
            mode = "events" if self.use_event_detection else "smooth"
            engine = "ML" if self.dart_detector.model is not None else "classic"
            info = f"Darts: ON ({n}) [{filt}] [{mode}] [{engine}]"
            if self.use_event_detection and self.pending_count > 0:
                info += f" +{self.pending_count} pending"
            parts.append(info)
        else:
            parts.append("Darts: [d] to start")
        if self.model_loaded:
            parts.append("Model: [g]toggle")
        return " | ".join(parts)


# ── HUD Drawing ─────────────────────────────────────────────────────────

def draw_hud(frame: np.ndarray, state: DemoState) -> np.ndarray:
    """Draw the heads-up display: status bar and FPS."""
    if state.manual_mode or state.adjust_mode or state.capture_mode:
        # Those modes draw their own chrome.
        return frame

    h, w = frame.shape[:2]

    # Semi-transparent status bar at the top.
    bar_h = 36
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, bar_h), (30, 30, 30), -1)
    frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)

    status = state.current_status
    cv2.putText(frame, status, (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1, cv2.LINE_AA)

    fps_text = f"{state.fps:.1f} FPS"
    (tw, _), _ = cv2.getTextSize(fps_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.putText(frame, fps_text, (w - tw - 10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)

    # Key hints at the bottom.
    hints = "[b]Board [c]Manual [a]Adjust [s]SetBG [d]Darts [e]Mode [f]Filter [g]ML [t]Capture [o]Overlay [m]Mask [r]Reset [q]Quit"
    cv2.putText(frame, hints, (10, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.36, (160, 160, 160), 1, cv2.LINE_AA)

    return frame


# ── Capture / labelling mode drawing ────────────────────────────────────

def draw_capture(frame: np.ndarray, state: DemoState) -> np.ndarray:
    """Render the dataset capture / labelling overlay.

    When a frame is *frozen* the pre-filled labels are shown with the
    active one highlighted; the user corrects the tip by clicking and sets
    the colour with [r]/[b]/[u].  When live, it just guides the user to
    freeze a frame or grab a negative.
    """
    out = frame.copy()
    fh, fw = out.shape[:2]

    if state.capture_frame is not None:
        for i, s in enumerate(state.capture_samples):
            active = i == state.capture_active
            if s.flight_color == "red":
                color = (0, 0, 255)
            elif s.flight_color == "blue":
                color = (255, 130, 0)
            else:
                color = (200, 200, 200)
            x, y, w, h = s.bbox
            thick = 3 if active else 1
            cv2.rectangle(out, (x, y), (x + w, y + h), color, thick)
            tx, ty = s.tip
            cv2.drawMarker(out, (tx, ty), color, cv2.MARKER_CROSS, 18, 2)
            tag = f"#{i + 1} {s.flight_color or 'unknown'}"
            cv2.putText(out, tag, (x, max(y - 6, 14)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
        prompt = (
            f"FROZEN — #{state.capture_active + 1}/{len(state.capture_samples)}  "
            "click=set tip  [j]next  [r/b/u]colour  [Enter]save  [x]discard"
        )
    else:
        prompt = "CAPTURE — [space]freeze proposals  [n]save negative  [t/Esc]exit"

    cv2.rectangle(out, (0, 0), (fw, 36), (30, 30, 30), -1)
    cv2.putText(out, f"DATASET CAPTURE  (saved: {state.capture_saved})",
                (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.rectangle(out, (0, fh - 40), (fw, fh), (30, 30, 30), -1)
    cv2.putText(out, prompt, (10, fh - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 1, cv2.LINE_AA)
    return out


def draw_calibration_marker(frame: np.ndarray, cal: BoardCalibration) -> np.ndarray:
    """Draw a small centre marker on the detected board."""
    cx, cy = cal.center
    cv2.drawMarker(frame, (cx, cy), (0, 255, 0), cv2.MARKER_CROSS, 20, 2)
    # Show the outer ellipse.
    cv2.ellipse(frame, (cx, cy), cal.axes, cal.angle, 0, 360, (0, 255, 0), 2)
    return frame


# ── Window-close detection ──────────────────────────────────────────────

def _window_closed(name: str) -> bool:
    """Return True if the user closed the named window via the X button."""
    try:
        # WND_PROP_VISIBLE returns 0 (or < 1) when the window has been
        # closed by clicking X.  On some backends WND_PROP_AUTOSIZE
        # returns -1 instead.
        if cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE) < 1:
            return True
    except cv2.error:
        return True
    return False


# ── Mouse callback ──────────────────────────────────────────────────────

# Global ref so the callback closure can reach it.
_demo_state: DemoState | None = None


def _mouse_callback(event: int, x: int, y: int, flags: int, param: object) -> None:
    if _demo_state is None:
        return
    # Capture mode: click corrects the active sample's tip on a frozen frame.
    if _demo_state.capture_mode:
        if (
            event == cv2.EVENT_LBUTTONDOWN
            and _demo_state.capture_frame is not None
            and _demo_state.capture_samples
        ):
            i = _demo_state.capture_active
            _demo_state.capture_samples[i] = _demo_state.capture_samples[i].with_tip(x, y)
        return
    if _demo_state.adjust_mode and _demo_state.adjuster is not None:
        if event == cv2.EVENT_LBUTTONDOWN:
            _demo_state.adjuster.set_bullseye(x, y)
            _demo_state.calibration = _demo_state.adjuster.cal
            _demo_state.set_status(f"Bullseye set to ({x}, {y})")
        return
    if not _demo_state.manual_mode:
        return
    if event == cv2.EVENT_LBUTTONDOWN:
        _demo_state.manual_calibrator.add_point(x, y)


# ── Main loop ───────────────────────────────────────────────────────────

def open_camera(source: str | int) -> cv2.VideoCapture:
    """Open a camera or video source."""
    try:
        idx = int(source)
        cap = cv2.VideoCapture(idx)
    except (ValueError, TypeError):
        cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        print(f"ERROR: Cannot open camera source '{source}'", file=sys.stderr)
        sys.exit(1)

    # Try to set a reasonable resolution.
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    return cap


# ── ML model / capture helpers ──────────────────────────────────────────

def _load_model(state: DemoState) -> None:
    """Load the YOLO model from the default path and attach it to the detector."""
    if not _DEFAULT_MODEL_PATH.exists():
        state.set_status(
            f"No model at {_DEFAULT_MODEL_PATH} — train one with "
            "`python -m dart_football.vision.ml.train`",
            5.0,
        )
        return
    try:
        from dart_football.vision.ml import YoloDartModel

        state.model = YoloDartModel.from_file(_DEFAULT_MODEL_PATH)
        state.model_loaded = True
        state.dart_detector.model = state.model
        state.set_status(f"ML model loaded from {_DEFAULT_MODEL_PATH} — ML detection ON")
    except Exception as exc:
        state.set_status(f"Failed to load model: {exc}", 5.0)


def _toggle_model(state: DemoState) -> None:
    """Toggle whether the loaded model drives detection."""
    if state.model is None:
        _load_model(state)
        return
    if state.dart_detector.model is None:
        state.dart_detector.model = state.model
        state.set_status("ML detection ON (model)")
    else:
        state.dart_detector.model = None
        state.set_status("ML detection OFF (classical)")


def _enter_capture(state: DemoState) -> None:
    if not state.dart_detector.has_background:
        state.set_status("Set background with [s] before capturing", 4.0)
        return
    if state.auto_labeler is None:
        state.auto_labeler = AutoLabeler(DatasetWriter(_DEFAULT_DATASET_DIR))
    state.capture_mode = True
    state.capture_frame = None
    state.capture_samples = []
    state.set_status("Capture mode — [space] freeze a frame, [n] negative, [t] exit", 4.0)


def _exit_capture(state: DemoState) -> None:
    if state.auto_labeler is not None:
        try:
            state.auto_labeler.finalize()  # write data.yaml
        except Exception:
            pass
    state.capture_mode = False
    state.capture_frame = None
    state.capture_samples = []
    state.set_status(f"Capture done — {state.capture_saved} sample(s) this session")


def _set_active_color(state: DemoState, color: str | None) -> None:
    if state.capture_samples:
        i = state.capture_active
        state.capture_samples[i] = state.capture_samples[i].with_color(color)


def _handle_capture_key(key: int, ch: str, state: DemoState, frame: np.ndarray) -> bool:
    """Keys while in dataset-capture mode."""
    if state.capture_frame is not None:
        # ── Frozen frame: edit then save / discard ──────────────────────
        if key in (13, 10):  # Enter — save
            if state.capture_samples and state.auto_labeler is not None:
                state.auto_labeler.save(state.capture_frame, state.capture_samples)
                state.capture_saved += 1
                state.set_status(f"Saved sample ({state.capture_saved})", 1.5)
            state.capture_frame = None
            state.capture_samples = []
        elif ch == "x" or key == 27:  # discard freeze
            state.capture_frame = None
            state.capture_samples = []
        elif ch == "j" and state.capture_samples:
            state.capture_active = (state.capture_active + 1) % len(state.capture_samples)
        elif ch == "r":
            _set_active_color(state, "red")
        elif ch == "b":
            _set_active_color(state, "blue")
        elif ch == "u":
            _set_active_color(state, None)
        return True

    # ── Live: freeze / negative / exit ──────────────────────────────────
    if ch == "t" or key == 27:
        _exit_capture(state)
    elif ch == " ":
        dets = state.dart_detector.detect(frame, state.calibration)
        state.capture_frame = frame.copy()
        state.capture_samples = AutoLabeler.propose_many(frame, dets)
        state.capture_active = 0
        if not dets:
            state.set_status("No proposals — [x] to unfreeze, or [n] negative", 2.0)
    elif ch == "n" and state.auto_labeler is not None:
        state.auto_labeler.save_negative(frame)
        state.capture_saved += 1
        state.set_status("Saved negative", 1.0)
    return True


def handle_key(key: int, state: DemoState, frame: np.ndarray) -> bool:
    """Process a keypress.  Returns True if the loop should continue."""
    if key == -1:
        return True

    ch = chr(key & 0xFF)

    # ── Capture / labelling mode keys ───────────────────────────────────
    if state.capture_mode:
        return _handle_capture_key(key, ch, state, frame)

    # ── Manual calibration mode keys ────────────────────────────────────
    if state.manual_mode:
        if key == 27:  # Esc
            state.manual_mode = False
            state.manual_calibrator.reset()
            state.set_status("Manual calibration cancelled")
            return True
        elif key == 13 or key == 10:  # Enter
            cal = state.manual_calibrator.fit()
            if cal is not None:
                state.calibration = cal
                state.manual_mode = False
                state.manual_calibrator.reset()
                # Go straight into adjustment mode so the user can tweak.
                state.adjuster = CalibrationAdjuster(cal)
                state.adjust_mode = True
                state.set_status("Entering adjustment mode — tweak orientation, axes, bullseye")
            else:
                state.set_status(
                    f"Need at least {ManualCalibrator.MIN_POINTS} points "
                    f"(have {len(state.manual_calibrator.points)})",
                    4.0,
                )
            return True
        elif ch == "z":
            state.manual_calibrator.remove_last()
            return True
        # Ignore other keys in manual mode.
        return True

    # ── Adjustment mode keys ────────────────────────────────────────────
    if state.adjust_mode and state.adjuster is not None:
        if key == 27 or key == 13 or key == 10:  # Esc or Enter — done
            final_cal = state.adjuster.cal
            state.calibration = final_cal
            state.adjust_mode = False
            state.adjuster = None
            # Save this verified calibration as training data so future
            # auto-detection learns from it.
            saved = state.board_detector.add_exemplar(frame, final_cal)
            if saved is not None:
                n = state.board_detector.exemplar_count
                state.set_status(
                    f"Adjustment complete — saved as training data "
                    f"({n} exemplar{'s' if n != 1 else ''})"
                )
            else:
                state.set_status("Adjustment complete")
            return True
        # Arrow keys: OpenCV returns 0x25_0000 on Windows, 65361 on Linux.
        if key in (0x250000, 65361):           # Left
            state.adjuster.rotate_ccw()
        elif key in (0x270000, 65363):         # Right
            state.adjuster.rotate_cw()
        elif key in (0x260000, 65362):         # Up
            state.adjuster.scale_uniform(state.adjuster.AXIS_STEP)
        elif key in (0x280000, 65364):         # Down
            state.adjuster.scale_uniform(-state.adjuster.AXIS_STEP)
        elif ch == "W":
            state.adjuster.rotate_ccw(fine=True)
        elif ch == "S":
            state.adjuster.rotate_cw(fine=True)
        elif ch == "w":
            state.adjuster.scale_axis_a(state.adjuster.AXIS_STEP)
        elif ch == "s":
            state.adjuster.scale_axis_a(-state.adjuster.AXIS_STEP)
        elif ch == "a":
            state.adjuster.scale_axis_b(-state.adjuster.AXIS_STEP)
        elif ch == "d":
            state.adjuster.scale_axis_b(state.adjuster.AXIS_STEP)
        elif ch == "e":
            state.adjuster.tilt(state.adjuster.TILT_STEP)
        elif ch == "q":
            state.adjuster.tilt(-state.adjuster.TILT_STEP)

        state.calibration = state.adjuster.cal
        return True

    # ── Normal mode keys ────────────────────────────────────────────────
    if ch == "q":
        return False

    elif ch == "b":
        n_ex = state.board_detector.exemplar_count
        state.set_status(f"Detecting board... ({n_ex} learned exemplar(s))")
        cal = state.board_detector.detect(frame)
        if cal is not None:
            state.calibration = cal
            state.set_status(
                f"Board detected!  Centre=({cal.center[0]},{cal.center[1]})  "
                f"Axes=({cal.axes[0]},{cal.axes[1]})  Angle={cal.angle:.1f}°"
            )
        else:
            hint = (
                "Board not found — try [c] for manual calibration"
                if n_ex > 0 else
                "Board not found — use [c] to calibrate manually; "
                "each manual calibration trains auto-detect"
            )
            state.set_status(hint, 5.0)

    elif ch == "c":
        state.manual_mode = True
        state.manual_calibrator.reset()
        state.set_status("Click points around the board edge (>= 5)")

    elif ch == "a":
        if state.calibration is not None:
            state.adjuster = CalibrationAdjuster(state.calibration)
            state.adjust_mode = True
            state.set_status("Adjustment mode — arrows/keys to tweak, Enter/Esc to finish")
        else:
            state.set_status("Calibrate first before adjusting", 4.0)

    elif ch == "s":
        state.dart_detector.set_background(frame)
        state.set_status("Background captured — darts will be detected against this frame")

    elif ch == "d":
        if not state.dart_detector.has_background:
            state.set_status("Set background first with [s]!", 4.0)
        else:
            state.dart_detection_active = not state.dart_detection_active
            label = "ON" if state.dart_detection_active else "OFF"
            state.set_status(f"Dart detection: {label}")

    elif ch == "e":
        state.use_event_detection = not state.use_event_detection
        mode = "event-driven" if state.use_event_detection else "temporal smoothing"
        state.set_status(f"Detection mode: {mode}")

    elif ch == "f":
        state.dart_detector.board_only = not state.dart_detector.board_only
        label = "ON (board only)" if state.dart_detector.board_only else "OFF (whole frame)"
        state.set_status(f"Board filter: {label}")

    elif ch == "g":
        _toggle_model(state)

    elif ch == "t":
        _enter_capture(state)

    elif ch == "o":
        state.show_overlay = not state.show_overlay
        state.set_status(f"Board overlay: {'ON' if state.show_overlay else 'OFF'}")

    elif ch == "m":
        state.show_mask = not state.show_mask
        state.set_status(f"Mask debug view: {'ON' if state.show_mask else 'OFF'}")

    elif ch == "r":
        state.calibration = None
        state.dart_detection_active = False
        state.detections = []
        # Keep the loaded model attached across a reset.
        state.dart_detector = DartDetector(model=state.model)
        state.set_status("Reset complete")

    elif ch == "+":
        mk = max(3, state.dart_detector.morph_kernel - 2)
        state.dart_detector.morph_kernel = mk
        state.set_status(f"Morph kernel: {mk} (more sensitive)")

    elif ch == "-":
        mk = min(15, state.dart_detector.morph_kernel + 2)
        state.dart_detector.morph_kernel = mk
        state.set_status(f"Morph kernel: {mk} (less sensitive)")

    elif ch == "S":
        if state.calibration is not None:
            state.calibration.save(_DEFAULT_CAL_PATH)
            state.set_status(f"Calibration saved to {_DEFAULT_CAL_PATH}")
        else:
            state.set_status("No calibration to save — detect or calibrate first", 4.0)

    elif ch == "L":
        if _DEFAULT_CAL_PATH.exists():
            try:
                state.calibration = BoardCalibration.load(_DEFAULT_CAL_PATH)
                state.set_status(
                    f"Calibration loaded from {_DEFAULT_CAL_PATH}  "
                    f"Centre=({state.calibration.center[0]},{state.calibration.center[1]})"
                )
            except Exception as exc:
                state.set_status(f"Failed to load calibration: {exc}", 5.0)
        else:
            state.set_status(f"No calibration file found at {_DEFAULT_CAL_PATH}", 4.0)

    return True


def run(source: str | int = 0) -> None:
    """Main demo loop."""
    global _demo_state

    cap = open_camera(source)
    state = DemoState()
    _demo_state = state

    window_name = "Dart Detection Demo"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)
    cv2.setMouseCallback(window_name, _mouse_callback)

    # Auto-load a trained model if one is present (ML detection on by default).
    if _DEFAULT_MODEL_PATH.exists():
        _load_model(state)

    prev_time = time.monotonic()
    alpha = 0.1  # EMA smoothing for FPS

    try:
        while True:
            # ── Check if the user closed the window via X ───────────────
            if _window_closed(window_name):
                break

            ret, frame = cap.read()
            if not ret:
                print("Camera read failed", file=sys.stderr)
                break

            display = frame.copy()

            # ── Manual calibration mode ─────────────────────────────────
            if state.manual_mode:
                display = state.manual_calibrator.draw(display)

            elif state.capture_mode:
                # Show the frozen frame (so labels align) or the live feed.
                base = state.capture_frame if state.capture_frame is not None else frame
                display = draw_capture(base, state)

            elif state.adjust_mode and state.adjuster is not None:
                display = state.adjuster.draw(display)

            else:
                # ── Board overlay ───────────────────────────────────────
                if state.calibration is not None:
                    if state.show_overlay:
                        display = state.calibration.draw_overlay(display)
                    display = draw_calibration_marker(display, state.calibration)

            # ── Dart detection (runs in normal and adjust modes) ───────
            if not state.manual_mode and not state.capture_mode:
                if state.dart_detection_active and state.dart_detector.has_background:
                    if state.use_event_detection:
                        result = state.dart_detector.detect_events(frame, state.calibration)
                        state.detections = result.locked
                        state.pending_count = result.pending_count
                        if result.arrivals:
                            segs = [d.segment.label if d.segment else "?" for d in result.arrivals]
                            state.set_status(f"Dart arrived: {', '.join(segs)}", 2.0)
                        elif result.removals:
                            state.set_status(f"{len(result.removals)} dart(s) removed", 2.0)
                    else:
                        state.detections = state.dart_detector.detect_stable(frame, state.calibration)
                        state.pending_count = 0
                    display = DartDetector.draw_detections(display, state.detections)

            # ── Foreground mask debug ───────────────────────────────────
            mask_display = None
            if state.show_mask and state.dart_detector.has_background:
                mask = state.dart_detector.get_foreground_mask(frame, state.calibration)
                mask_display = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)

            # ── FPS calculation ─────────────────────────────────────────
            now = time.monotonic()
            dt = now - prev_time
            prev_time = now
            if dt > 0:
                instant_fps = 1.0 / dt
                state.fps = alpha * instant_fps + (1 - alpha) * state.fps

            # ── HUD ────────────────────────────────────────────────────
            display = draw_hud(display, state)

            # ── Show windows ────────────────────────────────────────────
            cv2.imshow(window_name, display)
            if mask_display is not None:
                cv2.imshow("Foreground Mask", mask_display)
            else:
                try:
                    if cv2.getWindowProperty("Foreground Mask", cv2.WND_PROP_VISIBLE) >= 1:
                        cv2.destroyWindow("Foreground Mask")
                except cv2.error:
                    pass

            # ── Keyboard ────────────────────────────────────────────────
            key = cv2.waitKeyEx(1)
            if not handle_key(key, state, frame):
                break

    finally:
        _demo_state = None
        cap.release()
        cv2.destroyAllWindows()


# ── CLI entry point ─────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dart detection demo — test board and dart detection interactively.",
    )
    parser.add_argument(
        "--camera", "-c",
        default="0",
        help="Camera index (0, 1, ...) or RTSP/HTTP URL (default: 0)",
    )
    args = parser.parse_args()

    source: str | int
    try:
        source = int(args.camera)
    except ValueError:
        source = args.camera

    run(source)


if __name__ == "__main__":
    main()
