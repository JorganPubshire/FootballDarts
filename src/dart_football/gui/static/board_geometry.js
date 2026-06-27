/**
 * Dartboard hit classification in SVG board space (origin center, y down, outer radius BOARD_R).
 * Shared by pointer hit-test and webcam pipeline.
 */

export const BOARD_R = 180;

export const SEGMENT_ORDER = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5];

/** Normalized radii (r / BOARD_R); shared with SVG drawing in app.js */
export const DART_R_BULL_INNER = 0.038;
export const DART_R_BULL_OUTER = 0.092;
export const DART_R_TRIPLE_BAND = 0.045;
export const DART_R_DOUBLE_BAND = 0.045;
export const DART_R_DOUBLE_OUT = 0.84;
export const DART_R_SINGLE_DEPTH =
  (DART_R_DOUBLE_OUT - DART_R_BULL_OUTER - DART_R_TRIPLE_BAND - DART_R_DOUBLE_BAND) / 2;
export const DART_R_INNER_SINGLE_OUT = DART_R_BULL_OUTER + DART_R_SINGLE_DEPTH;
export const DART_R_TRIPLE_OUT = DART_R_INNER_SINGLE_OUT + DART_R_TRIPLE_BAND;
export const DART_R_OUTER_SINGLE_OUT = DART_R_TRIPLE_OUT + DART_R_SINGLE_DEPTH;

export function segmentFromAngle(x, y) {
  const angleDeg = (Math.atan2(y, x) * 180) / Math.PI;
  const fromTop = (angleDeg + 90 + 360) % 360;
  const idx = Math.floor(fromTop / 18) % 20;
  return SEGMENT_ORDER[idx];
}

/** rNorm: distance / BOARD_R (0..1) */
export function classifyRing(rNorm) {
  if (rNorm <= DART_R_BULL_INNER) return { ring: "inner_bull", bull: "red" };
  if (rNorm <= DART_R_BULL_OUTER) return { ring: "outer_bull", bull: "green" };
  if (rNorm <= DART_R_INNER_SINGLE_OUT) return { ring: "single" };
  if (rNorm <= DART_R_TRIPLE_OUT) return { ring: "triple" };
  if (rNorm <= DART_R_OUTER_SINGLE_OUT) return { ring: "single_mid" };
  if (rNorm <= DART_R_DOUBLE_OUT) return { ring: "double" };
  return { ring: "outside" };
}

/**
 * @returns {{ segment: number, ring: string, bull: string | null, rNorm: number, x: number, y: number }}
 */
export function hitFromBoardXY(x, y) {
  const r = Math.hypot(x, y);
  const rNorm = r / BOARD_R;
  const seg = segmentFromAngle(x, y);
  const ringInfo = classifyRing(rNorm);
  let bull = null;
  if (ringInfo.ring === "inner_bull") bull = "red";
  else if (ringInfo.ring === "outer_bull") bull = "green";
  return {
    segment: seg,
    ring: ringInfo.ring,
    bull,
    rNorm,
    x,
    y,
  };
}

export function distanceFromBoardXY(hit) {
  return hit.rNorm * BOARD_R;
}
