"""Dart detection via background subtraction and contour analysis.

Detects darts that have been thrown into a dartboard by comparing
the current frame against a learned background (the empty board).
Classifies each dart's flight colour as red or blue, draws a bounding
box, and estimates the tip contact point.

Both the demo and the game import from here.

Typical usage
-------------
    detector = DartDetector()
    detector.set_background(clean_frame)
    detections = detector.detect(current_frame, calibration)

Temporal smoothing
------------------
The ``DetectionTracker`` (used automatically when you call
``detector.detect_stable()``) requires a detection to appear in
*N* consecutive frames before it is "confirmed", then EMA-smooths
the bounding box and locks the flight colour.  This eliminates the
jittery boxes / flickering colour that raw per-frame detection
produces on stationary darts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

import cv2
import numpy as np

from dart_football.vision.board_detector import BoardCalibration, BoardSegment

if TYPE_CHECKING:
    from dart_football.vision.ml.infer import ModelDart, YoloDartModel


class FlightColor(Enum):
    """Detected colour of the dart flight."""
    RED = "red"
    BLUE = "blue"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DartDetection:
    """A single detected dart."""

    bbox: tuple[int, int, int, int]   # (x, y, w, h) bounding box
    tip: tuple[int, int]              # estimated tip contact point (x, y)
    flight_color: FlightColor
    contour: np.ndarray               # the raw contour for advanced use
    segment: BoardSegment | None      # board segment at the tip (if calibrated)
    confidence: float                 # 0..1 rough detection confidence


# ── HSV ranges for flight colour classification ─────────────────────────

# Red wraps around hue 0/180 in OpenCV's HSV (0..180 scale).
_RED_LOWER_1 = np.array([0, 70, 50])
_RED_UPPER_1 = np.array([10, 255, 255])
_RED_LOWER_2 = np.array([170, 70, 50])
_RED_UPPER_2 = np.array([180, 255, 255])

_BLUE_LOWER = np.array([95, 70, 50])
_BLUE_UPPER = np.array([130, 255, 255])


def _bbox_to_contour(bbox: tuple[int, int, int, int]) -> np.ndarray:
    """Build a 4-point rectangle contour from ``(x, y, w, h)``.

    Model detections have no contour of their own; this synthesises one so
    the :class:`DartDetection` contract (and any contour-based consumers)
    still hold.
    """
    x, y, w, h = bbox
    return np.array(
        [[[x, y]], [[x + w, y]], [[x + w, y + h]], [[x, y + h]]],
        dtype=np.int32,
    )


# ── Temporal smoothing / tracking ───────────────────────────────────────

class _TrackedDart:
    """Internal bookkeeping for one tracked detection across frames."""

    def __init__(
        self,
        det: DartDetection,
        *,
        confirm_frames: int,
        ema_alpha: float,
    ) -> None:
        self.confirm_frames = confirm_frames
        self.ema_alpha = ema_alpha

        # Raw values from latest frame.
        self._raw_bbox = det.bbox
        self._raw_tip = det.tip
        self._raw_contour = det.contour
        self._raw_segment = det.segment
        self._raw_confidence = det.confidence

        # Smoothed values (initialised to raw).
        self.bbox_f = tuple(float(v) for v in det.bbox)  # (x, y, w, h) as floats
        self.tip_f = (float(det.tip[0]), float(det.tip[1]))

        # Colour voting: accumulate votes, lock once confirmed.
        self._color_votes: dict[FlightColor, int] = {det.flight_color: 1}
        self._locked_color: FlightColor | None = None

        self.frames_seen = 1
        self.frames_missing = 0
        self.confirmed = self.frames_seen >= self.confirm_frames

    # ── Matching ────────────────────────────────────────────────────────

    def distance_to(self, det: DartDetection) -> float:
        """Pixel distance between this track's smoothed tip and *det*'s tip."""
        dx = self.tip_f[0] - det.tip[0]
        dy = self.tip_f[1] - det.tip[1]
        return math.sqrt(dx * dx + dy * dy)

    # ── Update ──────────────────────────────────────────────────────────

    def update(self, det: DartDetection) -> None:
        """Merge a new raw detection into this track."""
        self.frames_seen += 1
        self.frames_missing = 0

        self._raw_bbox = det.bbox
        self._raw_tip = det.tip
        self._raw_contour = det.contour
        self._raw_segment = det.segment
        self._raw_confidence = det.confidence

        # EMA smooth bbox.
        a = self.ema_alpha
        self.bbox_f = tuple(
            a * float(r) + (1 - a) * s
            for r, s in zip(det.bbox, self.bbox_f)
        )

        # EMA smooth tip.
        self.tip_f = (
            a * det.tip[0] + (1 - a) * self.tip_f[0],
            a * det.tip[1] + (1 - a) * self.tip_f[1],
        )

        # Colour vote.
        self._color_votes[det.flight_color] = self._color_votes.get(det.flight_color, 0) + 1

        # Lock colour once we have enough evidence.
        if self._locked_color is None and self.frames_seen >= self.confirm_frames:
            best = max(self._color_votes, key=self._color_votes.get)
            if best is not FlightColor.UNKNOWN:
                self._locked_color = best

        self.confirmed = self.frames_seen >= self.confirm_frames

    def mark_missing(self) -> None:
        self.frames_missing += 1

    @property
    def flight_color(self) -> FlightColor:
        if self._locked_color is not None:
            return self._locked_color
        return max(self._color_votes, key=self._color_votes.get)

    def to_detection(self) -> DartDetection:
        """Produce a smoothed :class:`DartDetection`."""
        bbox = tuple(int(round(v)) for v in self.bbox_f)
        tip = (int(round(self.tip_f[0])), int(round(self.tip_f[1])))
        return DartDetection(
            bbox=bbox,
            tip=tip,
            flight_color=self.flight_color,
            contour=self._raw_contour,
            segment=self._raw_segment,
            confidence=self._raw_confidence,
        )


class DetectionTracker:
    """Tracks detections across frames to provide stable output.

    Parameters
    ----------
    confirm_frames : int
        A detection must appear in this many consecutive frames before
        it is reported as confirmed.
    drop_frames : int
        A tracked detection is dropped after this many consecutive
        frames of not being matched.
    match_radius : float
        Maximum pixel distance between tips to consider a raw detection
        the same dart as an existing track.
    ema_alpha : float
        Exponential moving average weight for smoothing (0..1).
        Lower = smoother but slower to react.
    """

    def __init__(
        self,
        *,
        confirm_frames: int = 4,
        drop_frames: int = 8,
        match_radius: float = 50.0,
        ema_alpha: float = 0.25,
    ) -> None:
        self.confirm_frames = confirm_frames
        self.drop_frames = drop_frames
        self.match_radius = match_radius
        self.ema_alpha = ema_alpha
        self._tracks: list[_TrackedDart] = []

    def reset(self) -> None:
        self._tracks.clear()

    def update(self, raw_detections: list[DartDetection]) -> list[DartDetection]:
        """Feed one frame's raw detections, return stable outputs.

        Only confirmed (seen for >= ``confirm_frames``) darts are
        returned, with smoothed bounding boxes and locked colours.
        """
        used_tracks: set[int] = set()
        used_dets: set[int] = set()

        # Greedy nearest-neighbour matching.
        pairs: list[tuple[float, int, int]] = []
        for ti, track in enumerate(self._tracks):
            for di, det in enumerate(raw_detections):
                d = track.distance_to(det)
                if d <= self.match_radius:
                    pairs.append((d, ti, di))
        pairs.sort(key=lambda t: t[0])

        for _, ti, di in pairs:
            if ti in used_tracks or di in used_dets:
                continue
            self._tracks[ti].update(raw_detections[di])
            used_tracks.add(ti)
            used_dets.add(di)

        # Mark unmatched tracks as missing.
        for ti, track in enumerate(self._tracks):
            if ti not in used_tracks:
                track.mark_missing()

        # Create new tracks for unmatched detections.
        for di, det in enumerate(raw_detections):
            if di not in used_dets:
                self._tracks.append(_TrackedDart(
                    det,
                    confirm_frames=self.confirm_frames,
                    ema_alpha=self.ema_alpha,
                ))

        # Prune stale tracks.
        self._tracks = [
            t for t in self._tracks
            if t.frames_missing <= self.drop_frames
        ]

        # Return only confirmed tracks.
        return [t.to_detection() for t in self._tracks if t.confirmed]


# ── Locked dart & event-driven registry ────────────────────────────────

@dataclass
class LockedDart:
    """A dart whose position has been confirmed and frozen.

    Locked darts are excluded from per-frame detection so they consume
    no processing time.  Their continued presence is verified
    periodically via patch correlation.
    """

    detection: DartDetection
    patch: np.ndarray              # BGR crop at lock time
    frame_locked: int              # frame counter when locked
    _bbox_dilated: tuple[int, int, int, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        x, y, w, h = self.detection.bbox
        margin = 5
        self._bbox_dilated = (x - margin, y - margin, w + 2 * margin, h + 2 * margin)

    @property
    def exclusion_rect(self) -> tuple[int, int, int, int]:
        """Bounding box with a small margin for masking (x, y, w, h)."""
        return self._bbox_dilated


@dataclass
class DetectionFrame:
    """Result of one call to :meth:`DartDetector.detect_events`.

    Provides the full picture of what changed this frame.
    """

    locked: list[DartDetection]        # all currently-locked darts
    arrivals: list[DartDetection]      # darts newly confirmed this frame
    removals: list[DartDetection]      # darts that disappeared this frame
    pending_count: int                 # unconfirmed candidates still tracking


class DartRegistry:
    """Manages locked darts and pending arrivals for event-driven detection.

    Locked darts are excluded from per-frame background-subtraction
    detection.  New foreground blobs are tracked as pending arrivals
    until they are confirmed, then promoted to locked.

    Parameters
    ----------
    confirm_frames : int
        Frames a candidate must be seen before being locked.
    drop_frames : int
        Frames a pending candidate can be missing before being dropped.
    match_radius : float
        Max pixel distance for matching raw detections to pending tracks.
    ema_alpha : float
        EMA weight for smoothing pending tracks.
    presence_interval : int
        Check locked-dart presence every N frames.
    presence_threshold : float
        Mean pixel difference below this means the region matches the
        background and the dart has been removed.
    """

    def __init__(
        self,
        *,
        confirm_frames: int = 3,
        drop_frames: int = 6,
        match_radius: float = 50.0,
        ema_alpha: float = 0.3,
        presence_interval: int = 10,
        presence_threshold: float = 15.0,
    ) -> None:
        self.confirm_frames = confirm_frames
        self.drop_frames = drop_frames
        self.match_radius = match_radius
        self.ema_alpha = ema_alpha
        self.presence_interval = presence_interval
        self.presence_threshold = presence_threshold

        self.locked_darts: list[LockedDart] = []
        self._pending: list[_TrackedDart] = []
        self._frame_count: int = 0

    def reset(self) -> None:
        """Clear all locked darts and pending tracks."""
        self.locked_darts.clear()
        self._pending.clear()
        self._frame_count = 0

    @property
    def exclusion_rects(self) -> list[tuple[int, int, int, int]]:
        """Bounding boxes of locked darts to exclude from detection."""
        return [ld.exclusion_rect for ld in self.locked_darts]

    def update(
        self,
        raw_detections: list[DartDetection],
        frame: np.ndarray,
        background: np.ndarray | None = None,
    ) -> DetectionFrame:
        """Process one frame's raw detections (from non-locked regions).

        Returns a :class:`DetectionFrame` with arrivals, removals, and
        the current set of locked darts.
        """
        self._frame_count += 1
        arrivals: list[DartDetection] = []
        removals: list[DartDetection] = []

        # ── Match raw detections to pending tracks ─────────────────────
        used_tracks: set[int] = set()
        used_dets: set[int] = set()

        pairs: list[tuple[float, int, int]] = []
        for ti, track in enumerate(self._pending):
            for di, det in enumerate(raw_detections):
                d = track.distance_to(det)
                if d <= self.match_radius:
                    pairs.append((d, ti, di))
        pairs.sort(key=lambda t: t[0])

        newly_confirmed: list[int] = []
        for _, ti, di in pairs:
            if ti in used_tracks or di in used_dets:
                continue
            track = self._pending[ti]
            was_confirmed = track.confirmed
            track.update(raw_detections[di])
            used_tracks.add(ti)
            used_dets.add(di)
            if track.confirmed and not was_confirmed:
                newly_confirmed.append(ti)

        # Mark unmatched pending tracks as missing.
        for ti, track in enumerate(self._pending):
            if ti not in used_tracks:
                track.mark_missing()

        # Create new pending tracks for unmatched detections.
        for di, det in enumerate(raw_detections):
            if di not in used_dets:
                new_track = _TrackedDart(
                    det,
                    confirm_frames=self.confirm_frames,
                    ema_alpha=self.ema_alpha,
                )
                self._pending.append(new_track)
                # If confirm_frames <= 1, it's immediately confirmed.
                if new_track.confirmed:
                    newly_confirmed.append(len(self._pending) - 1)

        # ── Promote confirmed pending tracks to locked ─────────────────
        promoted_indices: set[int] = set()
        for ti in newly_confirmed:
            track = self._pending[ti]
            det = track.to_detection()
            x, y, w, h = det.bbox
            # Crop the patch from the current frame.
            fh, fw = frame.shape[:2]
            y1 = max(0, y)
            y2 = min(fh, y + h)
            x1 = max(0, x)
            x2 = min(fw, x + w)
            patch = frame[y1:y2, x1:x2].copy()

            locked = LockedDart(
                detection=det,
                patch=patch,
                frame_locked=self._frame_count,
            )
            self.locked_darts.append(locked)
            arrivals.append(det)
            promoted_indices.add(ti)

        # Remove promoted and stale pending tracks.
        self._pending = [
            t for i, t in enumerate(self._pending)
            if i not in promoted_indices and t.frames_missing <= self.drop_frames
        ]

        # ── Periodic presence check for locked darts ───────────────────
        if self._frame_count % self.presence_interval == 0:
            still_present: list[LockedDart] = []
            for ld in self.locked_darts:
                if self._check_presence(ld, frame, background):
                    still_present.append(ld)
                else:
                    removals.append(ld.detection)
            self.locked_darts = still_present

        return DetectionFrame(
            locked=[ld.detection for ld in self.locked_darts],
            arrivals=arrivals,
            removals=removals,
            pending_count=len(self._pending),
        )

    def _check_presence(
        self, ld: LockedDart, frame: np.ndarray,
        background: np.ndarray | None = None,
    ) -> bool:
        """Return True if the locked dart still appears in *frame*.

        Compares the current patch against the clean background.  If the
        region now looks like the background, the dart has been removed.
        """
        x, y, w, h = ld.detection.bbox
        fh, fw = frame.shape[:2]
        y1, y2 = max(0, y), min(fh, y + h)
        x1, x2 = max(0, x), min(fw, x + w)

        if y2 <= y1 or x2 <= x1:
            return False

        current_patch = frame[y1:y2, x1:x2]

        if background is not None:
            bg_patch = background[y1:y2, x1:x2]
        else:
            bg_patch = ld.patch

        gray_current = cv2.cvtColor(current_patch, cv2.COLOR_BGR2GRAY)
        gray_bg = cv2.cvtColor(bg_patch, cv2.COLOR_BGR2GRAY)

        if gray_current.size == 0 or gray_bg.size == 0:
            return False

        # Mean absolute difference: low = region matches background = dart gone.
        diff = cv2.absdiff(gray_current, gray_bg)
        mean_diff = float(diff.mean())
        # If the region looks very similar to the background, dart is gone.
        return mean_diff > self.presence_threshold


# ── Main detector ───────────────────────────────────────────────────────

class DartDetector:
    """Detects darts by comparing frames against a clean background.

    The detector uses MOG2 background subtraction seeded with a clean
    (no-darts) reference frame.  New foreground blobs that pass shape
    and size filters are classified as darts.

    Parameters
    ----------
    min_area : int
        Minimum contour area (px^2) to consider a blob a dart candidate.
    max_area : int
        Maximum contour area.
    min_aspect : float
        Minimum aspect ratio (length / width) — darts are elongated.
    morph_kernel : int
        Size of the morphological kernel for cleaning the foreground mask.
    board_only : bool
        When True *and* a calibration is provided, detections whose tip
        falls outside the board ellipse are discarded.
    model : YoloDartModel, optional
        A trained dart-pose model.  When provided, background subtraction
        is used only to propose candidate regions; the model confirms
        whether each region is really a dart (rejecting shadows / lighting
        changes) and regresses the precise tip contact point.  When
        ``None`` the detector uses the classical contour pipeline, so
        nothing about the existing behaviour changes without a model.
    model_merge_radius : float
        Tips within this many pixels are treated as the same dart when
        deduplicating model predictions from overlapping candidate ROIs.
    """

    def __init__(
        self,
        *,
        min_area: int = 300,
        max_area: int = 25_000,
        min_aspect: float = 1.5,
        morph_kernel: int = 5,
        history: int = 50,
        var_threshold: float = 40.0,
        board_only: bool = True,
        model: YoloDartModel | None = None,
        model_merge_radius: float = 25.0,
    ) -> None:
        self.min_area = min_area
        self.max_area = max_area
        self.min_aspect = min_aspect
        self.morph_kernel = morph_kernel
        self.board_only = board_only
        self.model = model
        self.model_merge_radius = model_merge_radius

        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=history,
            varThreshold=var_threshold,
            detectShadows=True,
        )
        self._background: np.ndarray | None = None
        self._background_set = False
        self._tracker = DetectionTracker()
        self._registry = DartRegistry()

    # ── Public API ──────────────────────────────────────────────────────

    def set_background(self, frame: np.ndarray) -> None:
        """Learn *frame* as the clean background (board with no darts).

        Call this once after board detection succeeds, with a clear view
        of the board.
        """
        self._background = frame.copy()
        self._background_set = True
        self._tracker.reset()
        self._registry.reset()
        # Feed the frame several times so MOG2 converges quickly.
        for _ in range(self._bg_subtractor.getHistory()):
            self._bg_subtractor.apply(frame, learningRate=0.5)

    @property
    def has_background(self) -> bool:
        return self._background_set

    def detect(
        self,
        frame: np.ndarray,
        calibration: BoardCalibration | None = None,
    ) -> list[DartDetection]:
        """Detect darts in *frame* (raw, unsmoothed).

        Parameters
        ----------
        frame : ndarray
            Current camera frame (BGR).
        calibration : BoardCalibration, optional
            If provided, each detection includes the board segment at
            the dart tip.  If ``board_only`` is True, detections outside
            the board are discarded.

        Returns
        -------
        list[DartDetection]
        """
        if not self._background_set:
            return []

        fg_mask = self._build_foreground_mask(frame, calibration)
        contours = self._extract_candidates(fg_mask)
        detections = self._candidates_to_detections(frame, contours, calibration)

        # Board-only filtering (tip must be inside the board ellipse).
        if self.board_only and calibration is not None:
            detections = [
                d for d in detections
                if self._tip_inside_board(d.tip, calibration)
            ]

        return detections

    def detect_events(
        self,
        frame: np.ndarray,
        calibration: BoardCalibration | None = None,
    ) -> DetectionFrame:
        """Event-driven dart detection with locked-dart registry.

        Locked darts are masked out of the foreground so they are not
        re-detected every frame.  Only genuinely new foreground blobs
        are tracked as pending arrivals and promoted to locked once
        confirmed.  Locked darts are periodically checked for removal
        via patch correlation.

        Returns a :class:`DetectionFrame` with arrivals, removals, the
        full set of locked darts, and pending-candidate count.
        """
        if not self._background_set:
            return DetectionFrame(locked=[], arrivals=[], removals=[], pending_count=0)

        # Detect only in non-locked regions.
        exclusion = self._registry.exclusion_rects
        fg_mask = self._build_foreground_mask(frame, calibration, exclusion_rects=exclusion)
        contours = self._extract_candidates(fg_mask)
        raw = self._candidates_to_detections(frame, contours, calibration)

        if self.board_only and calibration is not None:
            raw = [d for d in raw if self._tip_inside_board(d.tip, calibration)]

        return self._registry.update(raw, frame, self._background)

    def detect_stable(
        self,
        frame: np.ndarray,
        calibration: BoardCalibration | None = None,
    ) -> list[DartDetection]:
        """Detect darts with temporal smoothing (legacy API).

        Like :meth:`detect` but feeds raw detections through the
        internal :class:`DetectionTracker` so that results are stable:
        bounding boxes are EMA-smoothed, flight colour is locked after
        a few frames, and transient blobs are suppressed.

        Consider using :meth:`detect_events` instead for event-driven
        detection with arrival/removal callbacks.
        """
        raw = self.detect(frame, calibration)
        return self._tracker.update(raw)

    def get_foreground_mask(self, frame: np.ndarray,
                            calibration: BoardCalibration | None = None) -> np.ndarray:
        """Return the cleaned foreground mask for debugging/display."""
        return self._build_foreground_mask(frame, calibration)

    # ── Drawing helpers ─────────────────────────────────────────────────

    @staticmethod
    def draw_detections(
        frame: np.ndarray,
        detections: list[DartDetection],
        *,
        show_labels: bool = True,
    ) -> np.ndarray:
        """Draw bounding boxes and crosshairs on a copy of *frame*."""
        out = frame.copy()

        for det in detections:
            # Box colour matches flight colour.
            if det.flight_color is FlightColor.RED:
                color = (0, 0, 255)       # BGR red
            elif det.flight_color is FlightColor.BLUE:
                color = (255, 130, 0)     # BGR blue
            else:
                color = (200, 200, 200)   # grey for unknown

            x, y, w, h = det.bbox
            cv2.rectangle(out, (x, y), (x + w, y + h), color, 2)

            # Crosshair at tip.
            tx, ty = det.tip
            cross_size = 12
            cv2.line(out, (tx - cross_size, ty), (tx + cross_size, ty), color, 2)
            cv2.line(out, (tx, ty - cross_size), (tx, ty + cross_size), color, 2)
            # Small filled circle at exact tip.
            cv2.circle(out, (tx, ty), 3, color, -1)

            # Label.
            if show_labels:
                label_parts = [det.flight_color.value.upper()]
                if det.segment is not None:
                    label_parts.append(det.segment.label)
                label = " | ".join(label_parts)
                label_y = max(y - 8, 15)
                # Background rectangle for readability.
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.rectangle(out, (x, label_y - th - 4), (x + tw + 4, label_y + 2), (0, 0, 0), -1)
                cv2.putText(out, label, (x + 2, label_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

        return out

    # ── Private helpers ─────────────────────────────────────────────────

    @staticmethod
    def _tip_inside_board(
        tip: tuple[int, int],
        cal: BoardCalibration,
    ) -> bool:
        """Return True if *tip* is inside the board ellipse (with a
        small margin so darts right at the edge aren't clipped)."""
        norm_r, _ = cal.pixel_to_polar(tip[0], tip[1])
        # Allow up to 1.05 — a little past the double ring — so that
        # darts that just barely hit the wire aren't rejected.
        return norm_r <= 1.05

    def _build_foreground_mask(
        self,
        frame: np.ndarray,
        calibration: BoardCalibration | None = None,
        *,
        exclusion_rects: list[tuple[int, int, int, int]] | None = None,
    ) -> np.ndarray:
        """Produce a binary mask of foreground (new) objects.

        Parameters
        ----------
        exclusion_rects : list of (x, y, w, h), optional
            Regions to zero out in the mask (used by :meth:`detect_events`
            to hide already-locked darts from re-detection).
        """
        # Apply the background model (learning rate 0 = don't update model).
        fg = self._bg_subtractor.apply(frame, learningRate=0)

        # Threshold: MOG2 marks shadows as 127, definite fg as 255.
        _, fg = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)

        # Also do a simple absolute-difference against the stored
        # background to catch subtle darts the model might miss.
        if self._background is not None:
            diff = cv2.absdiff(frame, self._background)
            diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            _, diff_mask = cv2.threshold(diff_gray, 30, 255, cv2.THRESH_BINARY)
            fg = cv2.bitwise_or(fg, diff_mask)

        # Morphological clean-up.
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (self.morph_kernel, self.morph_kernel),
        )
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel, iterations=1)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel, iterations=2)
        # Dilate slightly to reconnect thin dart shafts.
        fg = cv2.dilate(fg, kernel, iterations=1)

        # Optionally mask to board region only.
        if self.board_only and calibration is not None:
            board_mask = self._make_board_mask(frame.shape[:2], calibration)
            fg = cv2.bitwise_and(fg, board_mask)

        # Zero out locked-dart regions so they are not re-detected.
        if exclusion_rects:
            fh, fw = fg.shape[:2]
            for ex, ey, ew, eh in exclusion_rects:
                x1 = max(0, ex)
                y1 = max(0, ey)
                x2 = min(fw, ex + ew)
                y2 = min(fh, ey + eh)
                if x2 > x1 and y2 > y1:
                    fg[y1:y2, x1:x2] = 0

        return fg

    @staticmethod
    def _make_board_mask(
        shape: tuple[int, int],
        cal: BoardCalibration,
        margin: float = 1.10,
    ) -> np.ndarray:
        """Create a binary mask of the board ellipse (with margin)."""
        mask = np.zeros(shape, dtype=np.uint8)
        axes = (int(cal.axes[0] * margin), int(cal.axes[1] * margin))
        cv2.ellipse(mask, cal.center, axes, cal.angle, 0, 360, 255, -1)
        return mask

    def _extract_candidates(self, mask: np.ndarray) -> list[np.ndarray]:
        """Find contours in *mask* that could be darts."""
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates: list[np.ndarray] = []

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if not (self.min_area <= area <= self.max_area):
                continue
            candidates.append(cnt)

        return candidates

    # ── Candidate → detection (model or classical) ──────────────────────

    def _candidates_to_detections(
        self,
        frame: np.ndarray,
        contours: list[np.ndarray],
        calibration: BoardCalibration | None,
    ) -> list[DartDetection]:
        """Turn candidate contours into detections.

        With a model loaded, each candidate's bounding box becomes a region
        of interest the model verifies and localises (shadow rejection +
        precise tip).  Without a model, the classical contour pipeline is
        used unchanged.
        """
        if self.model is None:
            out: list[DartDetection] = []
            for cnt in contours:
                det = self._classify_contour(frame, cnt, calibration)
                if det is not None:
                    out.append(det)
            return out
        return self._detect_with_model(frame, contours, calibration)

    def _detect_with_model(
        self,
        frame: np.ndarray,
        contours: list[np.ndarray],
        calibration: BoardCalibration | None,
    ) -> list[DartDetection]:
        """Run the ML model over candidate ROIs and build detections."""
        model_darts: list[ModelDart] = []
        for cnt in contours:
            roi = cv2.boundingRect(cnt)
            model_darts.extend(self.model.predict_roi(frame, roi))

        model_darts = self._dedupe_model_darts(model_darts)

        detections: list[DartDetection] = []
        for md in model_darts:
            detections.append(self._model_dart_to_detection(frame, md, calibration))
        return detections

    def _dedupe_model_darts(self, darts: list[ModelDart]) -> list[ModelDart]:
        """Merge model darts whose tips coincide (overlapping ROIs).

        Keeps the highest-confidence dart in each cluster.
        """
        kept: list[ModelDart] = []
        for md in sorted(darts, key=lambda d: d.conf, reverse=True):
            dup = False
            for k in kept:
                dx = md.tip[0] - k.tip[0]
                dy = md.tip[1] - k.tip[1]
                if (dx * dx + dy * dy) <= self.model_merge_radius ** 2:
                    dup = True
                    break
            if not dup:
                kept.append(md)
        return kept

    def _model_dart_to_detection(
        self,
        frame: np.ndarray,
        md: ModelDart,
        calibration: BoardCalibration | None,
    ) -> DartDetection:
        """Convert a :class:`ModelDart` to a :class:`DartDetection`."""
        # Flight colour: prefer the model's class; fall back to HSV.
        if md.flight_color == "red":
            flight_color = FlightColor.RED
        elif md.flight_color == "blue":
            flight_color = FlightColor.BLUE
        else:
            flight_color = self._classify_flight_color_bbox(frame, md.bbox, md.tip)

        segment: BoardSegment | None = None
        if calibration is not None:
            segment = calibration.pixel_to_segment(md.tip[0], md.tip[1])

        return DartDetection(
            bbox=md.bbox,
            tip=md.tip,
            flight_color=flight_color,
            contour=_bbox_to_contour(md.bbox),
            segment=segment,
            confidence=md.conf,
        )

    def _classify_contour(
        self,
        frame: np.ndarray,
        cnt: np.ndarray,
        calibration: BoardCalibration | None,
    ) -> DartDetection | None:
        """Classify a single contour as a dart (or reject it)."""
        # Bounding rectangle.
        x, y, w, h = cv2.boundingRect(cnt)

        # Aspect ratio check — darts are elongated.
        long_side = max(w, h)
        short_side = max(min(w, h), 1)
        aspect = long_side / short_side
        if aspect < self.min_aspect:
            return None

        # ── Tip estimation ──────────────────────────────────────────────
        tip = self._estimate_tip(cnt, calibration)

        # ── Flight colour classification ────────────────────────────────
        flight_color = self._classify_flight_color(frame, cnt, tip)

        # ── Board segment at tip ────────────────────────────────────────
        segment: BoardSegment | None = None
        if calibration is not None:
            segment = calibration.pixel_to_segment(tip[0], tip[1])

        # Rough confidence: higher for more elongated, larger blobs.
        area = cv2.contourArea(cnt)
        confidence = min(1.0, (aspect / 4.0) * (area / self.max_area) * 4)

        return DartDetection(
            bbox=(x, y, w, h),
            tip=tip,
            flight_color=flight_color,
            contour=cnt,
            segment=segment,
            confidence=confidence,
        )

    def _estimate_tip(
        self,
        cnt: np.ndarray,
        calibration: BoardCalibration | None,
    ) -> tuple[int, int]:
        """Estimate the dart tip using axis-aware contour selection.

        Strategy
        --------
        1.  Fit a line through the contour with ``cv2.fitLine`` to get
            the shaft direction vector.
        2.  Project every contour point onto that axis to determine which
            end of the dart is tip vs. flight.
        3.  Select contour points in the tip-end quarter of projections.
        4.  Among those tip-end points, pick the one closest to the
            board centre (calibrated) or lowest in frame (uncalibrated).

        This combines the axis-awareness of line fitting (so we know
        which end is the tip even for oblique darts) with the precision
        of selecting an actual contour point (no averaging artifacts).
        """
        pts = cnt.reshape(-1, 2).astype(np.float32)

        if len(pts) < 2:
            # Degenerate: single-point contour.
            return int(pts[0, 0]), int(pts[0, 1])

        # ── Stage 1: fit the shaft axis ────────────────────────────────
        try:
            line = cv2.fitLine(cnt, cv2.DIST_L2, 0, 0.01, 0.01)
        except cv2.error:
            return self._estimate_tip_fallback(cnt, calibration)

        vx, vy = float(line[0][0]), float(line[1][0])
        x0, y0 = float(line[2][0]), float(line[3][0])

        # Guard against a zero-length direction vector.
        length = math.sqrt(vx * vx + vy * vy)
        if length < 1e-6:
            return self._estimate_tip_fallback(cnt, calibration)
        vx /= length
        vy /= length

        # ── Stage 2: project contour points onto the axis ──────────────
        dx = pts[:, 0] - x0
        dy = pts[:, 1] - y0
        projections = dx * vx + dy * vy

        t_min = float(np.min(projections))
        t_max = float(np.max(projections))

        # The two ends of the dart along the axis.
        endpoint_a = (x0 + t_min * vx, y0 + t_min * vy)
        endpoint_b = (x0 + t_max * vx, y0 + t_max * vy)

        # ── Stage 3: identify which end is the tip ─────────────────────
        if calibration is not None:
            cx, cy = calibration.center
            dist_a = (endpoint_a[0] - cx) ** 2 + (endpoint_a[1] - cy) ** 2
            dist_b = (endpoint_b[0] - cx) ** 2 + (endpoint_b[1] - cy) ** 2
            tip_is_min_end = dist_a < dist_b
        else:
            # Uncalibrated: tip is the end lower in the frame.
            tip_is_min_end = endpoint_a[1] > endpoint_b[1]

        # ── Stage 4: select tip-end contour points ─────────────────────
        # Take the quarter of contour points closest to the tip end.
        t_range = t_max - t_min
        if t_range < 1e-6:
            # All points are at the same projection — degenerate.
            return self._estimate_tip_fallback(cnt, calibration)

        quarter = t_range * 0.25
        if tip_is_min_end:
            tip_mask = projections <= (t_min + quarter)
        else:
            tip_mask = projections >= (t_max - quarter)

        tip_pts = pts[tip_mask]

        if len(tip_pts) == 0:
            return self._estimate_tip_fallback(cnt, calibration)

        # Among tip-end points, pick the one closest to the board
        # centre (or lowest in frame if uncalibrated).
        if calibration is not None:
            cx, cy = calibration.center
            dists = (tip_pts[:, 0] - cx) ** 2 + (tip_pts[:, 1] - cy) ** 2
            best_idx = int(np.argmin(dists))
        else:
            best_idx = int(np.argmax(tip_pts[:, 1]))

        return int(tip_pts[best_idx, 0]), int(tip_pts[best_idx, 1])

    @staticmethod
    def _estimate_tip_fallback(
        cnt: np.ndarray,
        calibration: BoardCalibration | None,
    ) -> tuple[int, int]:
        """Last-resort tip estimation using minAreaRect."""
        rect = cv2.minAreaRect(cnt)
        box = cv2.boxPoints(rect)

        if calibration is not None:
            cx, cy = calibration.center
            tip_pt = min(box, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
        else:
            tip_pt = max(box, key=lambda p: p[1])

        return int(tip_pt[0]), int(tip_pt[1])

    def _classify_flight_color(
        self,
        frame: np.ndarray,
        cnt: np.ndarray,
        tip: tuple[int, int],
    ) -> FlightColor:
        """Determine flight colour by sampling the half of the contour
        bounding box furthest from the tip (where the flight feathers are).
        """
        return self._classify_flight_color_bbox(frame, cv2.boundingRect(cnt), tip)

    def _classify_flight_color_bbox(
        self,
        frame: np.ndarray,
        bbox: tuple[int, int, int, int],
        tip: tuple[int, int],
    ) -> FlightColor:
        """Flight-colour classification from a bounding box + tip.

        Samples the half of *bbox* furthest from the tip (where the flight
        feathers are) and counts red vs. blue HSV pixels.  Shared by the
        classical contour path and the model path.
        """
        x, y, w, h = bbox

        # The flight is at the far end from the tip.
        tip_x, tip_y = tip
        bbox_cx = x + w // 2
        bbox_cy = y + h // 2

        # Build an ROI for the flight half.
        if h > w:
            # Vertically oriented dart.
            if tip_y < bbox_cy:
                # Tip is at top -> flight is bottom half.
                flight_roi = frame[y + h // 2 : y + h, x : x + w]
            else:
                # Tip is at bottom -> flight is top half.
                flight_roi = frame[y : y + h // 2, x : x + w]
        else:
            # Horizontally oriented dart.
            if tip_x < bbox_cx:
                flight_roi = frame[y : y + h, x + w // 2 : x + w]
            else:
                flight_roi = frame[y : y + h, x : x + w // 2]

        if flight_roi.size == 0:
            return FlightColor.UNKNOWN

        hsv = cv2.cvtColor(flight_roi, cv2.COLOR_BGR2HSV)

        # Count red pixels.
        red_mask1 = cv2.inRange(hsv, _RED_LOWER_1, _RED_UPPER_1)
        red_mask2 = cv2.inRange(hsv, _RED_LOWER_2, _RED_UPPER_2)
        red_count = cv2.countNonZero(red_mask1) + cv2.countNonZero(red_mask2)

        # Count blue pixels.
        blue_mask = cv2.inRange(hsv, _BLUE_LOWER, _BLUE_UPPER)
        blue_count = cv2.countNonZero(blue_mask)

        total_px = flight_roi.shape[0] * flight_roi.shape[1]
        min_coverage = 0.05  # at least 5% of the ROI

        if red_count > blue_count and red_count > total_px * min_coverage:
            return FlightColor.RED
        if blue_count > red_count and blue_count > total_px * min_coverage:
            return FlightColor.BLUE
        return FlightColor.UNKNOWN
