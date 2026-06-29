"""Dartboard detection and calibration.

Detects the circular (or elliptical, for angled cameras) dartboard in a
camera frame, fits an ellipse to its boundary, and computes the mapping
from pixel coordinates to board segments (wedge number, ring).

Three calibration modes are supported:

1.  **Auto-detect** — Hough circles / contour ellipse fitting with
    dartboard-colour validation so spurious circles are rejected.
2.  **Manual click** — the user clicks points around the *outer edge of
    the double ring* (the scoring-zone boundary) in the demo UI; an
    ellipse is fitted to those points.
3.  **Load from file** — a previously saved calibration JSON is loaded.

After initial calibration the demo offers an **adjustment mode** where
the user can tweak rotation, drag the centre / bullseye, and resize the
ellipse axes.

Both the demo and the game import from here.

Typical usage
-------------
    detector = BoardDetector()
    cal = detector.detect(frame)
    if cal is not None:
        segment = cal.pixel_to_segment(x, y)
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

# ── Standard dartboard layout (clockwise from top) ─────────────────────
# The 20 wedge numbers in clockwise order starting at the top (12-o'clock).
WEDGE_ORDER: list[int] = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17,
                           3, 19, 7, 16, 8, 11, 14, 9, 12, 5]

# Ring boundaries as fractions of the overall board radius.
# The calibration ellipse represents the outer edge of the double ring,
# so 1.0 = the double-ring outer boundary (scoring zone edge).
RING_FRACTIONS: dict[str, tuple[float, float]] = {
    "double_bull": (0.000, 0.034),
    "single_bull": (0.034, 0.085),
    "inner_single": (0.085, 0.528),
    "triple":       (0.528, 0.604),
    "outer_single": (0.604, 0.906),
    "double":       (0.906, 1.000),
    "outside":      (1.000, 999.0),
}


@dataclass(frozen=True)
class BoardSegment:
    """Where on the board a point landed."""

    wedge: int          # 1-20, or 0 for bull zones
    ring: str           # key from RING_FRACTIONS
    score: int          # point value (single/double/triple applied)
    multiplier: int     # 1, 2, or 3

    @property
    def label(self) -> str:
        if self.ring == "double_bull":
            return "D-BULL (50)"
        if self.ring == "single_bull":
            return "S-BULL (25)"
        prefix = {"double": "D", "triple": "T"}.get(self.ring, "S")
        return f"{prefix}{self.wedge} ({self.score})"


# ── Overlay colour palette ──────────────────────────────────────────────
# BGR colours used by the bold overlay.
_CLR_DOUBLE  = (0, 200, 255)     # orange-yellow for double ring
_CLR_TRIPLE  = (0, 200, 255)     # same for triple ring
_CLR_BULL    = (0, 140, 255)     # warm orange for bull rings
_CLR_RING    = (180, 180, 180)   # light grey for inner/outer single
_CLR_WEDGE   = (120, 120, 120)   # grey for wedge divider lines
_CLR_LABEL_FG = (255, 255, 255)  # white text
_CLR_LABEL_BG = (0, 0, 0)       # black text shadow / background


def _ellipse_point(
    cx: int, cy: int,
    axes: tuple[int, int],
    angle_deg: float,
    theta: float,
    r_frac: float = 1.0,
) -> tuple[int, int]:
    """Map a board-polar (theta, r_frac) to pixel coords on an ellipse.

    *theta* is clockwise from 12-o'clock in radians.
    *r_frac* is the fraction of the semi-axes (0 = centre, 1 = edge).
    """
    cos_a = math.cos(math.radians(angle_deg))
    sin_a = math.sin(math.radians(angle_deg))
    dx = r_frac * math.sin(theta)
    dy = r_frac * -math.cos(theta)
    # Rotate into ellipse-aligned frame, scale, rotate back.
    lx = dx * cos_a + dy * sin_a
    ly = -dx * sin_a + dy * cos_a
    lx *= axes[0]
    ly *= axes[1]
    fx = lx * cos_a - ly * sin_a
    fy = lx * sin_a + ly * cos_a
    return int(cx + fx), int(cy + fy)


@dataclass
class BoardCalibration:
    """Result of a successful board detection.

    The ellipse represents the **outer edge of the double ring** — the
    boundary of the scoring zone.  All ring fractions in
    :data:`RING_FRACTIONS` are relative to this ellipse.

    The optional *bullseye* field stores a perspective-corrected centre
    for the internal rings.  When the camera views the board at an angle,
    the geometric centre of the outer ellipse may not coincide with the
    real bullseye.  If set, internal rings are drawn with their centres
    interpolated between *bullseye* (at r = 0) and *center* (at r = 1),
    and coordinate mapping uses the bullseye as the origin.
    """

    center: tuple[int, int]
    axes: tuple[int, int]          # (semi-major, semi-minor)
    angle: float                   # ellipse rotation in degrees
    radius_px: float               # average radius for segment mapping
    orientation_offset: float      # radians to rotate so wedge-20 is at top
    contour: np.ndarray | None = field(default=None, repr=False)
    bullseye: tuple[int, int] | None = None  # perspective-corrected centre

    @property
    def effective_bullseye(self) -> tuple[int, int]:
        """The bullseye position, defaulting to *center* if not set."""
        return self.bullseye if self.bullseye is not None else self.center

    def _ring_center(self, r_frac: float) -> tuple[int, int]:
        """Interpolate the centre for a ring at fraction *r_frac*.

        At r = 0 the centre is the bullseye; at r = 1 it is the ellipse
        centre.  This models the perspective shift of inner rings when
        the camera views the board at an angle.
        """
        bx, by = self.effective_bullseye
        cx, cy = self.center
        return (int(bx + (cx - bx) * r_frac),
                int(by + (cy - by) * r_frac))

    # ── Serialisation ───────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dict (contour is dropped)."""
        d = {
            "center": list(self.center),
            "axes": list(self.axes),
            "angle": self.angle,
            "radius_px": self.radius_px,
            "orientation_offset": self.orientation_offset,
        }
        if self.bullseye is not None:
            d["bullseye"] = list(self.bullseye)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> BoardCalibration:
        bullseye = tuple(d["bullseye"]) if "bullseye" in d else None
        return cls(
            center=tuple(d["center"]),
            axes=tuple(d["axes"]),
            angle=d["angle"],
            radius_px=d["radius_px"],
            orientation_offset=d["orientation_offset"],
            bullseye=bullseye,
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: str | Path) -> BoardCalibration:
        return cls.from_dict(json.loads(Path(path).read_text()))

    # ── Mutation helpers (return new instances) ─────────────────────────

    def with_center(self, cx: int, cy: int) -> BoardCalibration:
        return BoardCalibration(
            center=(cx, cy), axes=self.axes, angle=self.angle,
            radius_px=self.radius_px,
            orientation_offset=self.orientation_offset,
            contour=self.contour, bullseye=self.bullseye,
        )

    def with_bullseye(self, bx: int, by: int) -> BoardCalibration:
        return BoardCalibration(
            center=self.center, axes=self.axes, angle=self.angle,
            radius_px=self.radius_px,
            orientation_offset=self.orientation_offset,
            contour=self.contour, bullseye=(bx, by),
        )

    def with_axes(self, a: int, b: int) -> BoardCalibration:
        return BoardCalibration(
            center=self.center, axes=(max(1, a), max(1, b)),
            angle=self.angle,
            radius_px=float((max(1, a) + max(1, b)) / 2),
            orientation_offset=self.orientation_offset,
            contour=self.contour, bullseye=self.bullseye,
        )

    def with_orientation(self, offset: float) -> BoardCalibration:
        return BoardCalibration(
            center=self.center, axes=self.axes, angle=self.angle,
            radius_px=self.radius_px,
            orientation_offset=offset,
            contour=self.contour, bullseye=self.bullseye,
        )

    def with_angle(self, angle: float) -> BoardCalibration:
        return BoardCalibration(
            center=self.center, axes=self.axes, angle=angle,
            radius_px=self.radius_px,
            orientation_offset=self.orientation_offset,
            contour=self.contour, bullseye=self.bullseye,
        )

    # ── Coordinate mapping ──────────────────────────────────────────────

    def pixel_to_polar(self, x: int, y: int) -> tuple[float, float]:
        """Convert a pixel (x, y) to (normalised_radius, angle_rad).

        ``normalised_radius`` is 0 at the bullseye (or centre if no
        bullseye is set), 1.0 at the outer edge of the double ring.
        ``angle_rad`` is measured clockwise from 12-o'clock after
        applying the orientation offset.

        When a bullseye offset is set, the radius is computed relative
        to the bullseye and normalised by the distance from bullseye
        to the outer ellipse at the same angle.
        """
        bx, by = self.effective_bullseye
        dx = x - bx
        dy = y - by

        # Angle: clockwise from top, with orientation offset.
        raw_angle = math.atan2(dx, -dy)
        adjusted = (raw_angle - self.orientation_offset) % (2 * math.pi)

        # Distance from bullseye to the outer ellipse at this angle.
        # This lets us normalise even when bullseye != center.
        edge_x, edge_y = _ellipse_point(
            self.center[0], self.center[1],
            self.axes, self.angle, raw_angle, 1.0,
        )
        edge_dist = math.sqrt((edge_x - bx) ** 2 + (edge_y - by) ** 2)
        pixel_dist = math.sqrt(dx * dx + dy * dy)

        norm_r = pixel_dist / edge_dist if edge_dist > 0 else 0.0
        return norm_r, adjusted

    def pixel_to_segment(self, x: int, y: int) -> BoardSegment | None:
        """Map a pixel position to a dartboard segment.

        Returns ``None`` if the point is outside the scoring zone.
        """
        norm_r, angle = self.pixel_to_polar(x, y)

        # Determine ring.
        ring_name: str | None = None
        for name, (lo, hi) in RING_FRACTIONS.items():
            if lo <= norm_r < hi:
                ring_name = name
                break
        if ring_name is None or ring_name == "outside":
            return None

        # Bull zones have no wedge.
        if ring_name in ("double_bull", "single_bull"):
            score = 50 if ring_name == "double_bull" else 25
            mult = 2 if ring_name == "double_bull" else 1
            return BoardSegment(wedge=0, ring=ring_name, score=score, multiplier=mult)

        # Determine wedge.  Each wedge spans 18 degrees (pi/10 radians).
        wedge_width = 2 * math.pi / 20
        idx = int((angle + wedge_width / 2) / wedge_width) % 20
        wedge = WEDGE_ORDER[idx]

        mult = {"double": 2, "triple": 3}.get(ring_name, 1)
        return BoardSegment(wedge=wedge, ring=ring_name, score=wedge * mult, multiplier=mult)

    # ── Overlay drawing ─────────────────────────────────────────────────

    def draw_overlay(self, frame: np.ndarray, *, alpha: float = 0.35) -> np.ndarray:
        """Draw a readable board grid on *frame*.

        Ring ellipses use colour-coded lines, wedge dividers are
        drawn from the bull to the double ring, and wedge numbers have
        a subtle background pill for contrast.

        When a bullseye offset is set, inner rings are drawn with their
        centres shifted toward the bullseye (perspective correction).
        """
        overlay = frame.copy()
        cx, cy = self.center
        bx, by = self.effective_bullseye
        wedge_width = 2 * math.pi / 20

        # ── Ring ellipses ───────────────────────────────────────────────
        ring_styles: dict[str, tuple[tuple[int, int, int], int]] = {
            "double_bull": (_CLR_BULL, 1),
            "single_bull": (_CLR_BULL, 1),
            "inner_single": (_CLR_RING, 1),
            "triple":       (_CLR_TRIPLE, 2),
            "outer_single": (_CLR_RING, 1),
            "double":       (_CLR_DOUBLE, 2),
        }
        for name, (_, hi) in RING_FRACTIONS.items():
            if name == "outside":
                continue
            style = ring_styles.get(name, (_CLR_RING, 1))
            a = int(self.axes[0] * hi)
            b = int(self.axes[1] * hi)
            # Shift ring centre toward bullseye for perspective correction.
            rcx, rcy = self._ring_center(hi)
            cv2.ellipse(overlay, (rcx, rcy), (a, b), self.angle, 0, 360,
                        style[0], style[1], cv2.LINE_AA)

        # ── Wedge divider lines (bull to double outer edge) ─────────────
        bull_frac = RING_FRACTIONS["single_bull"][1]
        double_frac = RING_FRACTIONS["double"][1]
        for i in range(20):
            ang = self.orientation_offset + i * wedge_width - wedge_width / 2
            bcx, bcy = self._ring_center(bull_frac)
            p1 = _ellipse_point(bcx, bcy, self.axes, self.angle, ang, bull_frac)
            p2 = _ellipse_point(cx, cy, self.axes, self.angle, ang, double_frac)
            cv2.line(overlay, p1, p2, _CLR_WEDGE, 1, cv2.LINE_AA)

        # ── Wedge number labels with background pills ───────────────────
        label_frac = 0.76  # between outer-single and double
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.42
        font_thick = 1
        lcx, lcy = self._ring_center(label_frac)
        for i, w in enumerate(WEDGE_ORDER):
            ang = self.orientation_offset + i * wedge_width
            px, py = _ellipse_point(lcx, lcy, self.axes, self.angle, ang, label_frac)
            txt = str(w)
            (tw, th), baseline = cv2.getTextSize(txt, font, font_scale, font_thick)
            # Subtle dark pill behind the number.
            pad = 3
            tl = (px - tw // 2 - pad, py - th // 2 - pad)
            br = (px + tw // 2 + pad, py + th // 2 + pad + baseline)
            cv2.rectangle(overlay, tl, br, _CLR_LABEL_BG, -1)
            # White number.
            cv2.putText(overlay, txt,
                        (px - tw // 2, py + th // 2),
                        font, font_scale, _CLR_LABEL_FG, font_thick, cv2.LINE_AA)

        # ── Bullseye cross ─────────────────────────────────────────────
        cv2.drawMarker(overlay, (bx, by), _CLR_BULL, cv2.MARKER_CROSS, 14, 1)

        return cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)


# ── Manual calibration helper ───────────────────────────────────────────

class ManualCalibrator:
    """Guided manual calibration — 6 steps for full board setup.

    The user clicks specific positions on the board in order:

    Steps 1–5:  Click the **outer edge of the double ring** at five
                specific wedge numbers, spread evenly around the board.
                These define the ellipse shape and orientation.

    Step 6:     Click the **bullseye** (centre of the board).  This
                captures perspective skew so the internal rings are
                drawn correctly even when the camera is at an angle.

    Guided steps
    ------------
    1.  Double-ring outer edge at the **20** (top)
    2.  Double-ring outer edge at the **6** (upper-right)
    3.  Double-ring outer edge at the **3** (lower-right)
    4.  Double-ring outer edge at the **11** (lower-left)
    5.  Double-ring outer edge at the **14** (upper-left)
    6.  Click the **bullseye** (dead centre of the board)

    After 6 points, press **Enter** to accept.
    """

    MIN_POINTS = 6  # 5 edge + 1 bullseye

    # The 5 guided edge positions, then the bullseye.
    _GUIDED_STEPS: list[tuple[str, str]] = [
        ("20",       "Step 1/6: Click the outer DOUBLE-RING edge at the 20 (top)"),
        ("6",        "Step 2/6: Click the outer DOUBLE-RING edge at the 6 (upper-right)"),
        ("3",        "Step 3/6: Click the outer DOUBLE-RING edge at the 3 (lower-right)"),
        ("11",       "Step 4/6: Click the outer DOUBLE-RING edge at the 11 (lower-left)"),
        ("14",       "Step 5/6: Click the outer DOUBLE-RING edge at the 14 (upper-left)"),
        ("Bullseye", "Step 6/6: Click the BULLSEYE (dead centre of the board)"),
    ]

    def __init__(self) -> None:
        self.points: list[tuple[int, int]] = []

    def add_point(self, x: int, y: int) -> None:
        self.points.append((x, y))

    def remove_last(self) -> None:
        if self.points:
            self.points.pop()

    def reset(self) -> None:
        self.points.clear()

    @property
    def can_fit(self) -> bool:
        return len(self.points) >= self.MIN_POINTS

    @property
    def current_step(self) -> int:
        return len(self.points)

    @property
    def _current_prompt(self) -> str:
        step = self.current_step
        if step < len(self._GUIDED_STEPS):
            return self._GUIDED_STEPS[step][1]
        return f"{len(self.points)} points  |  [Enter] accept  [z] undo  [Esc] cancel"

    def fit(self) -> BoardCalibration | None:
        """Fit an ellipse to the first 5 edge points and use the 6th
        as the bullseye for perspective correction.

        Returns ``None`` if too few points or the fit is degenerate.
        """
        if not self.can_fit:
            return None

        # First 5 points are edge points for the ellipse.
        edge_pts = np.array(self.points[:5], dtype=np.float32).reshape(-1, 1, 2)
        try:
            ellipse = cv2.fitEllipse(edge_pts)
        except cv2.error:
            return None

        (cx, cy), (w_axis, h_axis), angle = ellipse
        semi_a, semi_b = int(w_axis / 2), int(h_axis / 2)

        if semi_a <= 0 or semi_b <= 0:
            return None

        # Compute orientation offset from the "20" point (step 0).
        # This must be the exact inverse of _ellipse_point, which rotates
        # into the ellipse frame, scales by the axes, then rotates back —
        # so we undo all three steps to recover the board-space angle.
        p20 = self.points[0]
        dx = p20[0] - cx
        dy = p20[1] - cy
        cos_a = math.cos(math.radians(angle))
        sin_a = math.sin(math.radians(angle))
        # 1. Rotate screen vector into the ellipse-aligned frame.
        ux = dx * cos_a + dy * sin_a
        uy = -dx * sin_a + dy * cos_a
        # 2. Un-scale by the semi-axes.
        if semi_a > 0 and semi_b > 0:
            ux /= semi_a
            uy /= semi_b
        # 3. Rotate back out of the ellipse-aligned frame.
        bx_ = ux * cos_a - uy * sin_a
        by_ = ux * sin_a + uy * cos_a
        orientation_offset = math.atan2(bx_, -by_)

        # The 6th point is the bullseye.
        bullseye = self.points[5] if len(self.points) >= 6 else None

        return BoardCalibration(
            center=(int(cx), int(cy)),
            axes=(semi_a, semi_b),
            angle=angle,
            radius_px=float((semi_a + semi_b) / 2),
            orientation_offset=orientation_offset,
            bullseye=bullseye,
        )

    def draw(self, frame: np.ndarray) -> np.ndarray:
        """Draw collected points, live preview, and guided prompts."""
        out = frame.copy()
        fh, fw = out.shape[:2]

        # Draw each clicked point with its label.
        for i, (px, py) in enumerate(self.points):
            if i < len(self._GUIDED_STEPS):
                label = self._GUIDED_STEPS[i][0]
                color = (0, 0, 255) if label == "Bullseye" else (0, 255, 0)
            else:
                label = f"#{i + 1}"
                color = (0, 200, 200)

            cv2.circle(out, (px, py), 6, color, -1)
            cv2.circle(out, (px, py), 6, (255, 255, 255), 1)
            cv2.putText(out, label, (px + 10, py - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

        # Connect the 5 edge points with lines (not the bullseye).
        edge_count = min(len(self.points), 5)
        for i in range(1, edge_count):
            cv2.line(out, self.points[i - 1], self.points[i], (0, 200, 0), 1)
        if edge_count > 2:
            cv2.line(out, self.points[edge_count - 1], self.points[0], (0, 200, 0), 1)

        # Live ellipse preview when we have >= 5 edge points.
        if edge_count >= 5:
            pts = np.array(self.points[:5], dtype=np.float32).reshape(-1, 1, 2)
            try:
                ellipse = cv2.fitEllipse(pts)
                cv2.ellipse(out, ellipse, (0, 255, 255), 2)
            except cv2.error:
                pass

        # Top instruction bar.
        cv2.rectangle(out, (0, 0), (fw, 36), (30, 30, 30), -1)
        cv2.putText(out, "GUIDED CALIBRATION: follow the prompts below",
                    (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 1, cv2.LINE_AA)

        # Bottom status bar with current prompt.
        prompt = self._current_prompt
        cv2.rectangle(out, (0, fh - 44), (fw, fh), (30, 30, 30), -1)
        cv2.putText(out, prompt, (10, fh - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 255), 1, cv2.LINE_AA)

        return out


# ── Post-calibration adjustment mode ────────────────────────────────────

class CalibrationAdjuster:
    """Interactive post-calibration tweaks: rotation, bullseye, ellipse.

    Operated via keyboard and mouse from the demo main loop.

    Controls
    --------
    Left/Right arrows   Rotate wedge orientation (1 degree per press)
    Shift+Left/Right    Rotate wedge orientation (0.1 degree per press)
    Up/Down arrows      Scale both axes uniformly (+/- 2px)
    W/S                 Scale semi-axis A (vertical) +/- 2px
    A/D                 Scale semi-axis B (horizontal) +/- 2px
    E/Q                 Tilt ellipse angle +/- 1 degree
    Left-click          Set bullseye (board centre) to click position
    Right-click         Set bullseye AND recenter the ellipse
    Enter/Esc           Exit adjustment mode (keep changes)
    """

    # Step sizes.
    ROT_STEP = math.radians(1.0)       # 1 degree
    ROT_FINE_STEP = math.radians(0.1)  # 0.1 degree
    AXIS_STEP = 2                      # pixels
    TILT_STEP = 1.0                    # degrees

    def __init__(self, cal: BoardCalibration) -> None:
        self.cal = cal

    # ── Keyboard actions (return updated cal) ───────────────────────────

    def rotate_cw(self, fine: bool = False) -> None:
        step = self.ROT_FINE_STEP if fine else self.ROT_STEP
        self.cal = self.cal.with_orientation(self.cal.orientation_offset + step)

    def rotate_ccw(self, fine: bool = False) -> None:
        step = self.ROT_FINE_STEP if fine else self.ROT_STEP
        self.cal = self.cal.with_orientation(self.cal.orientation_offset - step)

    def scale_uniform(self, delta: int) -> None:
        a, b = self.cal.axes
        self.cal = self.cal.with_axes(a + delta, b + delta)

    def scale_axis_a(self, delta: int) -> None:
        a, b = self.cal.axes
        self.cal = self.cal.with_axes(a + delta, b)

    def scale_axis_b(self, delta: int) -> None:
        a, b = self.cal.axes
        self.cal = self.cal.with_axes(a, b + delta)

    def tilt(self, delta: float) -> None:
        self.cal = self.cal.with_angle(self.cal.angle + delta)

    def set_bullseye(self, x: int, y: int) -> None:
        """Set the bullseye (perspective centre) without moving the outer ellipse."""
        self.cal = self.cal.with_bullseye(x, y)

    def draw(self, frame: np.ndarray) -> np.ndarray:
        """Draw the overlay plus adjustment-mode chrome."""
        out = self.cal.draw_overlay(frame)

        # Draw the outer ellipse outline prominently (fixed boundary).
        cx, cy = self.cal.center
        cv2.ellipse(out, (cx, cy), self.cal.axes, self.cal.angle,
                    0, 360, (0, 255, 0), 2, cv2.LINE_AA)

        # Bullseye marker (may differ from ellipse centre).
        bx, by = self.cal.effective_bullseye
        cv2.drawMarker(out, (bx, by), (0, 0, 255), cv2.MARKER_CROSS, 24, 2)
        if (bx, by) != (cx, cy):
            # Show ellipse centre as a small dot so both are visible.
            cv2.circle(out, (cx, cy), 4, (0, 255, 0), -1)

        # Draw axis handles on the outer ellipse.
        for ang in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
            real_ang = self.cal.orientation_offset + ang
            px, py = _ellipse_point(cx, cy, self.cal.axes, self.cal.angle, real_ang, 1.0)
            cv2.circle(out, (px, py), 5, (0, 255, 0), -1)

        # Info bar at top.
        h, w = out.shape[:2]
        cv2.rectangle(out, (0, 0), (w, 36), (30, 30, 30), -1)
        info = (
            f"ADJUST  |  Bullseye=({bx},{by})  Axes=({self.cal.axes[0]},{self.cal.axes[1]})  "
            f"Tilt={self.cal.angle:.1f}deg  Rot={math.degrees(self.cal.orientation_offset):.1f}deg"
        )
        cv2.putText(out, info, (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)

        # Controls bar at bottom.
        cv2.rectangle(out, (0, h - 44), (w, h), (30, 30, 30), -1)
        controls = (
            "L/R:rotate  Up/Dn:scale  Shift+W/S:fine rot  "
            "w/s:axisA  a/d:axisB  e/q:tilt  Click:bullseye  Enter/Esc:done"
        )
        cv2.putText(out, controls, (10, h - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, (160, 160, 160), 1, cv2.LINE_AA)

        return out


# ── Synthetic dartboard template for feature matching ──────────────────

def _render_dartboard_template(size: int = 800) -> np.ndarray:
    """Render a synthetic dartboard image (BGR) for feature matching.

    The board is drawn centred in a square image with the standard
    colour layout: alternating black/white segments with red/green
    double and triple rings.  Wedge 20 is at the top (12-o'clock).
    """
    img = np.zeros((size, size, 3), dtype=np.uint8)
    cx = cy = size // 2
    radius = size // 2 - 10

    # Fractional radii for each ring boundary (outer edge = 1.0).
    ring_bounds = [
        (0.000, 0.034),  # double bull
        (0.034, 0.085),  # single bull
        (0.085, 0.500),  # inner single
        (0.500, 0.546),  # triple
        (0.546, 0.906),  # outer single
        (0.906, 1.000),  # double
    ]

    # Standard dartboard colours per wedge (alternating).
    # Even-index wedges (0=20, 2=18, 4=13, ...) use one set,
    # odd-index wedges use the other.
    # Colours: BGR
    black = (30, 30, 30)
    white = (220, 220, 210)
    red = (40, 40, 200)
    green = (50, 140, 50)

    wedge_width = 2 * math.pi / 20
    half_wedge = wedge_width / 2

    for wi in range(20):
        # Wedge centre angle (clockwise from top, 20 at index 0).
        centre_ang = wi * wedge_width
        start_deg = math.degrees(centre_ang - half_wedge) - 90
        end_deg = math.degrees(centre_ang + half_wedge) - 90
        span = end_deg - start_deg

        for ri, (r_lo, r_hi) in enumerate(ring_bounds):
            inner_r = int(radius * r_lo)
            outer_r = int(radius * r_hi)

            if ri == 0:
                # Double bull — always red.
                colour = red
            elif ri == 1:
                # Single bull — always green.
                colour = green
            elif ri in (2, 4):
                # Single segments: alternate black/white.
                colour = black if wi % 2 == 0 else white
            elif ri == 3:
                # Triple ring: alternate red/green.
                colour = red if wi % 2 == 0 else green
            elif ri == 5:
                # Double ring: alternate red/green.
                colour = red if wi % 2 == 0 else green

            # Draw the filled arc as an ellipse sector.
            cv2.ellipse(img, (cx, cy), (outer_r, outer_r), 0,
                        start_deg, start_deg + span, colour, -1, cv2.LINE_AA)
            # Punch out the inner part with black if inner_r > 0
            # (will be overdrawn by the next inner ring).

    # Overdraw inner rings from inside out to clean up.
    # The loop above draws outer-to-inner per wedge, but rings overlap.
    # Redraw bull zones cleanly.
    bull_outer = int(radius * 0.085)
    bull_inner = int(radius * 0.034)
    cv2.circle(img, (cx, cy), bull_outer, green, -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), bull_inner, red, -1, cv2.LINE_AA)

    # Thin wire lines between wedges for feature richness.
    wire_color = (160, 160, 160)
    for wi in range(20):
        ang = wi * wedge_width - half_wedge
        dx = math.sin(ang)
        dy = -math.cos(ang)
        inner_r = int(radius * 0.085)
        outer_r = radius
        p1 = (int(cx + dx * inner_r), int(cy + dy * inner_r))
        p2 = (int(cx + dx * outer_r), int(cy + dy * outer_r))
        cv2.line(img, p1, p2, wire_color, 1, cv2.LINE_AA)

    # Ring wires.
    for frac in (0.085, 0.500, 0.546, 0.906, 1.0):
        r = int(radius * frac)
        cv2.circle(img, (cx, cy), r, wire_color, 1, cv2.LINE_AA)

    # Number labels for extra features.
    font = cv2.FONT_HERSHEY_SIMPLEX
    label_r = radius * 1.0
    for wi, num in enumerate(WEDGE_ORDER):
        ang = wi * wedge_width
        lx = int(cx + math.sin(ang) * label_r * 0.78)
        ly = int(cy - math.cos(ang) * label_r * 0.78)
        txt = str(num)
        (tw, th), _ = cv2.getTextSize(txt, font, 0.6, 2)
        cv2.putText(img, txt, (lx - tw // 2, ly + th // 2),
                    font, 0.6, white, 2, cv2.LINE_AA)

    return img


def _warp_calibration(
    cal: BoardCalibration, H: np.ndarray, n_pts: int = 72,
) -> BoardCalibration | None:
    """Warp a known calibration through homography *H* (source → dest frame).

    Samples the source outer ellipse, projects every point through *H*,
    refits an ellipse in the destination frame, and recovers the centre,
    axes, tilt, orientation offset, and bullseye.  Used both for the
    synthetic template and for real calibrated exemplars.
    """
    # Sample points around the source outer ellipse.
    src_pts = np.float32([
        _ellipse_point(
            cal.center[0], cal.center[1], cal.axes, cal.angle,
            2 * math.pi * i / n_pts, 1.0,
        )
        for i in range(n_pts)
    ]).reshape(-1, 1, 2)

    projected = cv2.perspectiveTransform(src_pts, H)
    if projected is None:
        return None
    projected = projected.reshape(-1, 2).astype(np.float32)
    if len(projected) < 5:
        return None

    try:
        ellipse = cv2.fitEllipse(projected.reshape(-1, 1, 2))
    except cv2.error:
        return None

    (ecx, ecy), (w_axis, h_axis), angle = ellipse
    semi_a, semi_b = int(w_axis / 2), int(h_axis / 2)
    if semi_a <= 0 or semi_b <= 0:
        return None

    # Project key points: source centre, source wedge-20 outer point,
    # and source bullseye, so we recover orientation and perspective.
    p20 = _ellipse_point(
        cal.center[0], cal.center[1], cal.axes, cal.angle,
        cal.orientation_offset, 1.0,
    )
    bx, by = cal.effective_bullseye
    key_pts = np.float32([
        [cal.center[0], cal.center[1]],
        [p20[0], p20[1]],
        [bx, by],
    ]).reshape(-1, 1, 2)
    proj_key = cv2.perspectiveTransform(key_pts, H).reshape(-1, 2)

    frame_cx, frame_cy = proj_key[0]
    p20_x, p20_y = proj_key[1]
    bull_x, bull_y = proj_key[2]

    # Orientation: board-space angle of the projected "20" relative to
    # the projected centre.  This must be the exact inverse of
    # _ellipse_point, which rotates into the ellipse frame, scales by the
    # axes, then rotates back — so we undo all three steps in order.
    dx = p20_x - frame_cx
    dy = p20_y - frame_cy
    cos_a = math.cos(math.radians(angle))
    sin_a = math.sin(math.radians(angle))
    # 1. Rotate into the ellipse-aligned frame.
    ux = dx * cos_a + dy * sin_a
    uy = -dx * sin_a + dy * cos_a
    # 2. Un-scale by the semi-axes.
    ux /= semi_a
    uy /= semi_b
    # 3. Rotate back out of the ellipse-aligned frame.
    bx_ = ux * cos_a - uy * sin_a
    by_ = ux * sin_a + uy * cos_a
    orientation_offset = math.atan2(bx_, -by_)

    # Keep the projected bullseye if it differs from the ellipse centre.
    bullseye: tuple[int, int] | None = None
    if math.hypot(bull_x - ecx, bull_y - ecy) > 3:
        bullseye = (int(bull_x), int(bull_y))

    return BoardCalibration(
        center=(int(ecx), int(ecy)),
        axes=(semi_a, semi_b),
        angle=angle,
        radius_px=float((semi_a + semi_b) / 2),
        orientation_offset=orientation_offset,
        bullseye=bullseye,
    )


class TemplateDetector:
    """Detect a dartboard via ORB feature matching against a synthetic template.

    Generates a synthetic dartboard image once, extracts ORB features,
    then matches against each camera frame to estimate a homography.
    The homography maps the known template geometry (centre, radius,
    orientation) into the camera frame, giving the ellipse parameters
    and orientation offset directly.

    Falls back gracefully: returns ``None`` if too few matches are found.
    """

    def __init__(
        self,
        *,
        template_size: int = 800,
        min_matches: int = 15,
        n_features: int = 3000,
        ransac_thresh: float = 5.0,
    ) -> None:
        self.min_matches = min_matches
        self.ransac_thresh = ransac_thresh
        self._template_size = template_size

        # Render the synthetic dartboard and extract features.
        self._template = _render_dartboard_template(template_size)
        self._template_gray = cv2.cvtColor(self._template, cv2.COLOR_BGR2GRAY)

        self._orb = cv2.ORB_create(nfeatures=n_features)
        self._kp_tmpl, self._des_tmpl = self._orb.detectAndCompute(
            self._template_gray, None,
        )

        # Template geometry as a BoardCalibration: centred, circular,
        # wedge-20 at the top (orientation_offset = 0).
        tcx = template_size // 2
        tcy = template_size // 2
        tr = template_size // 2 - 10
        self._template_cal = BoardCalibration(
            center=(tcx, tcy), axes=(tr, tr), angle=0.0,
            radius_px=float(tr), orientation_offset=0.0,
        )

        # BFMatcher with Hamming distance for ORB (binary descriptors).
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

    def detect(self, frame: np.ndarray) -> BoardCalibration | None:
        """Try to detect the dartboard in *frame* via template matching."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        kp_frame, des_frame = self._orb.detectAndCompute(gray, None)

        if des_frame is None or len(kp_frame) < self.min_matches:
            return None
        if self._des_tmpl is None or len(self._kp_tmpl) < self.min_matches:
            return None

        # KNN match and apply Lowe's ratio test.
        raw_matches = self._matcher.knnMatch(self._des_tmpl, des_frame, k=2)
        good: list[cv2.DMatch] = []
        for pair in raw_matches:
            if len(pair) == 2:
                m, n = pair
                if m.distance < 0.75 * n.distance:
                    good.append(m)

        if len(good) < self.min_matches:
            return None

        # Extract matched point pairs.
        pts_tmpl = np.float32(
            [self._kp_tmpl[m.queryIdx].pt for m in good]
        ).reshape(-1, 1, 2)
        pts_frame = np.float32(
            [kp_frame[m.trainIdx].pt for m in good]
        ).reshape(-1, 1, 2)

        # Find homography (template → frame).
        H, mask = cv2.findHomography(
            pts_tmpl, pts_frame, cv2.RANSAC, self.ransac_thresh,
        )
        if H is None:
            return None

        inliers = int(mask.sum()) if mask is not None else 0
        if inliers < self.min_matches:
            return None

        return _warp_calibration(self._template_cal, H)


@dataclass
class _Exemplar:
    """A stored, user-verified calibration with its source frame's features."""

    name: str
    calibration: BoardCalibration
    keypoints: tuple
    descriptors: np.ndarray


class ExemplarStore:
    """Few-shot board detection learned from real, user-verified calibrations.

    Every time the user accepts a manual calibration (or finishes
    adjustment), the source frame and its calibration are saved here as
    an *exemplar*.  At detection time the live frame is ORB-matched
    against each exemplar; the best match's homography warps that
    exemplar's known calibration into the current frame.

    Because exemplars are real frames from the same camera and board,
    matching is far more reliable than matching a synthetic template —
    so detection accuracy improves the more the user calibrates.

    On-disk layout (under *directory*)::

        exemplar_<timestamp>.png    # the source frame
        exemplar_<timestamp>.json   # BoardCalibration.to_dict()
    """

    def __init__(
        self,
        directory: str | Path,
        *,
        n_features: int = 3000,
        min_matches: int = 18,
        ransac_thresh: float = 5.0,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.min_matches = min_matches
        self.ransac_thresh = ransac_thresh

        self._orb = cv2.ORB_create(nfeatures=n_features)
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        self._exemplars: list[_Exemplar] = []
        self.reload()

    @property
    def count(self) -> int:
        return len(self._exemplars)

    def reload(self) -> None:
        """(Re)load all exemplars from disk and extract their features."""
        self._exemplars.clear()
        for img_path in sorted(self.directory.glob("exemplar_*.png")):
            json_path = img_path.with_suffix(".json")
            if not json_path.exists():
                continue
            img = cv2.imread(str(img_path))
            if img is None:
                continue
            try:
                cal = BoardCalibration.load(json_path)
            except (json.JSONDecodeError, KeyError, OSError):
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            kp, des = self._orb.detectAndCompute(gray, None)
            if des is None or len(kp) < self.min_matches:
                continue
            self._exemplars.append(
                _Exemplar(img_path.stem, cal, tuple(kp), des)
            )

    def add(self, frame: np.ndarray, calibration: BoardCalibration) -> str | None:
        """Save *frame* + *calibration* as a new exemplar and index it.

        Returns the exemplar name, or ``None`` if the frame yielded too
        few features to be useful.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        kp, des = self._orb.detectAndCompute(gray, None)
        if des is None or len(kp) < self.min_matches:
            return None

        name = f"exemplar_{int(time.time() * 1000)}"
        img_path = self.directory / f"{name}.png"
        json_path = self.directory / f"{name}.json"
        cv2.imwrite(str(img_path), frame)
        calibration.save(json_path)

        self._exemplars.append(_Exemplar(name, calibration, tuple(kp), des))
        return name

    def detect(self, frame: np.ndarray) -> BoardCalibration | None:
        """Detect the board by matching against the best-fitting exemplar."""
        if not self._exemplars:
            return None

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        kp_frame, des_frame = self._orb.detectAndCompute(gray, None)
        if des_frame is None or len(kp_frame) < self.min_matches:
            return None

        best_inliers = 0
        best_cal: BoardCalibration | None = None

        for ex in self._exemplars:
            raw = self._matcher.knnMatch(ex.descriptors, des_frame, k=2)
            good: list[cv2.DMatch] = []
            for pair in raw:
                if len(pair) == 2:
                    m, n = pair
                    if m.distance < 0.75 * n.distance:
                        good.append(m)
            if len(good) < self.min_matches:
                continue

            src = np.float32(
                [ex.keypoints[m.queryIdx].pt for m in good]
            ).reshape(-1, 1, 2)
            dst = np.float32(
                [kp_frame[m.trainIdx].pt for m in good]
            ).reshape(-1, 1, 2)

            H, mask = cv2.findHomography(
                src, dst, cv2.RANSAC, self.ransac_thresh,
            )
            if H is None:
                continue
            inliers = int(mask.sum()) if mask is not None else 0
            if inliers < self.min_matches or inliers <= best_inliers:
                continue

            cal = _warp_calibration(ex.calibration, H)
            if cal is not None:
                best_inliers = inliers
                best_cal = cal

        return best_cal


class BoardDetector:
    """Detects a dartboard in a camera frame.

    Detection strategy
    ------------------
    1.  **Exemplar matching** (primary, if any saved) — ORB feature
        matching against real, user-verified calibrations captured from
        this camera/board.  Most reliable, and improves as the user
        calibrates more.  See :class:`ExemplarStore`.
    2.  **Template matching** — ORB feature matching against a synthetic
        dartboard image.  Recovers position, size, ellipse shape, and
        orientation in one shot via homography.
    3.  **Hough circles / contour ellipse** (fallback) — classical CV
        for when feature matching fails (e.g. poor lighting).
    4.  Classical candidates are scored by dartboard-colour presence and
        the best is returned.

    Pass *exemplar_dir* to enable learning from manual calibrations:
    call :meth:`add_exemplar` whenever the user accepts one.
    """

    def __init__(
        self,
        *,
        min_radius_frac: float = 0.15,
        max_radius_frac: float = 0.90,
        circularity_tol: float = 0.35,
        exemplar_dir: str | Path | None = "board_exemplars",
    ) -> None:
        self.min_radius_frac = min_radius_frac
        self.max_radius_frac = max_radius_frac
        self.circularity_tol = circularity_tol
        self._template_detector = TemplateDetector()
        self._exemplars: ExemplarStore | None = (
            ExemplarStore(exemplar_dir) if exemplar_dir is not None else None
        )

    # ── Public API ──────────────────────────────────────────────────────

    @property
    def exemplar_count(self) -> int:
        """Number of stored, user-verified calibration exemplars."""
        return self._exemplars.count if self._exemplars is not None else 0

    def add_exemplar(
        self, frame: np.ndarray, calibration: BoardCalibration,
    ) -> str | None:
        """Save a user-verified calibration as training data for detection.

        Returns the exemplar name, or ``None`` if disabled or the frame
        had too few features.
        """
        if self._exemplars is None:
            return None
        return self._exemplars.add(frame, calibration)

    def detect(self, frame: np.ndarray) -> BoardCalibration | None:
        """Attempt to detect the dartboard in *frame*.

        Tries exemplar matching first (real calibrated frames), then the
        synthetic template, then classical CV.  Each gives position,
        size, and orientation in one shot.

        Returns a :class:`BoardCalibration` on success, or ``None``.
        """
        # ── Primary: learned exemplars ─────────────────────────────────
        if self._exemplars is not None:
            ex_cal = self._exemplars.detect(frame)
            if ex_cal is not None:
                return ex_cal

        # ── Secondary: synthetic template ──────────────────────────────
        tmpl_cal = self._template_detector.detect(frame)
        if tmpl_cal is not None:
            return tmpl_cal

        # ── Fallback: classical CV ─────────────────────────────────────
        h, w = frame.shape[:2]
        min_r = int(min(h, w) * self.min_radius_frac)
        max_r = int(min(h, w) * self.max_radius_frac)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (9, 9), 2)

        candidates: list[BoardCalibration] = []

        hough_cals = self._find_hough_circles(frame, blurred, min_r, max_r)
        candidates.extend(hough_cals)

        contour_cal = self._try_contour_ellipse(frame, gray, min_r, max_r)
        if contour_cal is not None:
            candidates.append(contour_cal)

        if not candidates:
            return None

        scored = [(self._score_candidate(frame, c), c) for c in candidates]
        scored.sort(key=lambda t: t[0], reverse=True)

        best_score, best_cal = scored[0]
        if best_score < 0.15:
            return None

        best_cal = self._refine_orientation(frame, best_cal)
        return best_cal

    # ── Candidate scoring ───────────────────────────────────────────────

    def _score_candidate(
        self, frame: np.ndarray, cal: BoardCalibration,
    ) -> float:
        h, w = frame.shape[:2]
        cx, cy = cal.center

        if cx < 0 or cx >= w or cy < 0 or cy >= h:
            return 0.0

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        n_samples = 200
        colour_counts = {"red": 0, "green": 0, "black": 0, "white": 0, "other": 0}

        rng = np.random.RandomState(42)
        for _ in range(n_samples):
            r_norm = rng.uniform(0.05, 0.50)
            theta = rng.uniform(0, 2 * math.pi)

            cos_a = math.cos(math.radians(cal.angle))
            sin_a = math.sin(math.radians(cal.angle))
            dx = r_norm * math.sin(theta)
            dy = r_norm * -math.cos(theta)
            lx = dx * cos_a + dy * sin_a
            ly = -dx * sin_a + dy * cos_a
            lx *= cal.axes[0]
            ly *= cal.axes[1]
            px = int(cx + lx * cos_a - ly * sin_a)
            py = int(cy + lx * sin_a + ly * cos_a)

            if not (0 <= px < w and 0 <= py < h):
                continue

            hue, sat, val = int(hsv[py, px, 0]), int(hsv[py, px, 1]), int(hsv[py, px, 2])

            if val < 50 and sat < 80:
                colour_counts["black"] += 1
            elif val > 180 and sat < 50:
                colour_counts["white"] += 1
            elif sat > 70 and val > 50:
                if hue < 10 or hue > 170:
                    colour_counts["red"] += 1
                elif 35 < hue < 85:
                    colour_counts["green"] += 1
                else:
                    colour_counts["other"] += 1
            else:
                colour_counts["other"] += 1

        total = sum(colour_counts.values())
        if total == 0:
            return 0.0

        min_pct = 0.04
        colours_found = sum(
            1 for c in ("red", "green", "black", "white")
            if colour_counts[c] / total > min_pct
        )

        colour_score = colours_found / 4.0

        dist_from_centre = math.sqrt((cx - w / 2) ** 2 + (cy - h / 2) ** 2)
        max_dist = math.sqrt((w / 2) ** 2 + (h / 2) ** 2)
        proximity_score = 1.0 - (dist_from_centre / max_dist)

        avg_radius = (cal.axes[0] + cal.axes[1]) / 2
        size_ratio = avg_radius / (min(h, w) / 2)
        size_score = 1.0 if 0.15 <= size_ratio <= 0.85 else 0.3

        return colour_score * 0.55 + proximity_score * 0.25 + size_score * 0.20

    # ── Private helpers ─────────────────────────────────────────────────

    def _find_hough_circles(
        self, frame: np.ndarray, blurred: np.ndarray,
        min_r: int, max_r: int,
    ) -> list[BoardCalibration]:
        circles = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT, dp=1.2,
            minDist=min_r,
            param1=100, param2=50,
            minRadius=min_r, maxRadius=max_r,
        )
        if circles is None:
            return []

        results: list[BoardCalibration] = []
        for c in np.round(circles[0]).astype(int):
            cx, cy, r = int(c[0]), int(c[1]), int(c[2])
            results.append(BoardCalibration(
                center=(cx, cy), axes=(r, r), angle=0.0,
                radius_px=float(r), orientation_offset=0.0,
            ))
        return results

    def _try_contour_ellipse(
        self, frame: np.ndarray, gray: np.ndarray,
        min_r: int, max_r: int,
    ) -> BoardCalibration | None:
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 51, 5,
        )
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        candidates: list[tuple[float, np.ndarray]] = []
        for cnt in contours:
            if len(cnt) < 5:
                continue
            area = cv2.contourArea(cnt)
            min_area = math.pi * min_r * min_r * 0.5
            max_area = math.pi * max_r * max_r * 1.5
            if not (min_area < area < max_area):
                continue

            perimeter = cv2.arcLength(cnt, True)
            if perimeter == 0:
                continue
            circularity = 4 * math.pi * area / (perimeter * perimeter)
            if circularity < (1.0 - self.circularity_tol):
                continue

            candidates.append((area, cnt))

        if not candidates:
            return None

        _, best_cnt = max(candidates, key=lambda t: t[0])
        ellipse = cv2.fitEllipse(best_cnt)
        (cx, cy), (w_axis, h_axis), angle = ellipse
        semi_a, semi_b = int(w_axis / 2), int(h_axis / 2)

        if semi_a <= 0 or semi_b <= 0:
            return None

        ratio = min(semi_a, semi_b) / max(semi_a, semi_b)
        if ratio < (1.0 - self.circularity_tol):
            return None

        return BoardCalibration(
            center=(int(cx), int(cy)), axes=(semi_a, semi_b),
            angle=angle, radius_px=float((semi_a + semi_b) / 2),
            orientation_offset=0.0, contour=best_cnt,
        )

    def _refine_orientation(
        self, frame: np.ndarray, cal: BoardCalibration,
    ) -> BoardCalibration:
        cx, cy = cal.center
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h, w = hsv.shape[:2]

        n_samples = 360
        red_angles: list[float] = []

        for i in range(n_samples):
            theta = 2 * math.pi * i / n_samples
            sx, sy = _ellipse_point(cx, cy, cal.axes, cal.angle, theta, 0.56)
            if 0 <= sx < w and 0 <= sy < h:
                hue, sat, val = hsv[sy, sx]
                is_red = (hue < 10 or hue > 170) and sat > 80 and val > 60
                if is_red:
                    red_angles.append(theta)

        if not red_angles:
            return cal

        best_offset = self._find_cluster_near_zero(red_angles, cluster_width=math.pi / 8)

        return BoardCalibration(
            center=cal.center, axes=cal.axes, angle=cal.angle,
            radius_px=cal.radius_px, orientation_offset=best_offset,
            contour=cal.contour,
        )

    @staticmethod
    def _find_cluster_near_zero(
        angles: Sequence[float], cluster_width: float,
    ) -> float:
        if not angles:
            return 0.0

        best_count = 0
        best_centre = 0.0

        for candidate in angles:
            count = sum(
                1 for a in angles
                if abs((a - candidate + math.pi) % (2 * math.pi) - math.pi) < cluster_width / 2
            )
            dist_from_top = abs((candidate + math.pi) % (2 * math.pi) - math.pi)
            if count > best_count or (count == best_count and dist_from_top < abs((best_centre + math.pi) % (2 * math.pi) - math.pi)):
                best_count = count
                best_centre = candidate

        return best_centre
