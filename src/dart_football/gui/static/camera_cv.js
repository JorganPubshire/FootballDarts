/**
 * Homography (image pixels → board SVG coords) and simple dart localization via frame differencing.
 */

import {
  BOARD_R,
  DART_R_INNER_SINGLE_OUT,
  DART_R_TRIPLE_OUT,
  DART_R_OUTER_SINGLE_OUT,
  DART_R_DOUBLE_OUT,
} from "./board_geometry.js";

/** Warped board patch: BOARD_R corresponds to half the side length (centered). */
export const WARP_SIZE = 360;

const LS_KEY = "dartFootballBoardHomography";
const DART_COLORS_KEY = "dartFootballDartColorProfiles";

/** Board landmarks: bull + four outer-wire cardinals (perspective-safe, n≥4 DLT). */
export const CALIBRATION_LANDMARKS = [
  { key: "bull", label: "Bullseye center", dst: [0, 0] },
  { key: "top", label: "Outer wire at 20 (top)", dst: [0, -BOARD_R] },
  { key: "right", label: "Outer wire at 6 (right)", dst: [BOARD_R, 0] },
  { key: "bottom", label: "Outer wire at 3 (bottom)", dst: [0, BOARD_R] },
  { key: "left", label: "Outer wire at 11 (left)", dst: [-BOARD_R, 0] },
];

/** @param {number[][]} pts [[x,y], ...] */
function normalizePoints2d(pts) {
  const n = pts.length;
  let cx = 0;
  let cy = 0;
  for (const [x, y] of pts) {
    cx += x;
    cy += y;
  }
  cx /= n;
  cy /= n;
  let meanDist = 0;
  for (const [x, y] of pts) meanDist += Math.hypot(x - cx, y - cy);
  meanDist /= n;
  const s = meanDist > 1e-12 ? Math.SQRT2 / meanDist : 1;
  const T = [
    [s, 0, -s * cx],
    [0, s, -s * cy],
    [0, 0, 1],
  ];
  const normalized = pts.map(([x, y]) => [s * (x - cx), s * (y - cy)]);
  return { pts: normalized, T };
}

function multiply3x3(a, b) {
  const r = [
    [0, 0, 0],
    [0, 0, 0],
    [0, 0, 0],
  ];
  for (let i = 0; i < 3; i++) {
    for (let j = 0; j < 3; j++) {
      for (let k = 0; k < 3; k++) r[i][j] += a[i][k] * b[k][j];
    }
  }
  return r;
}

function solveLinearSystemLeastSquares(A, b) {
  const m = A.length;
  const n = A[0].length;
  const ata = Array.from({ length: n }, () => Array(n).fill(0));
  const atb = Array(n).fill(0);
  for (let i = 0; i < m; i++) {
    for (let j = 0; j < n; j++) {
      atb[j] += A[i][j] * b[i];
      for (let k = 0; k < n; k++) ata[j][k] += A[i][j] * A[i][k];
    }
  }
  return solveLinearSystem(ata, atb);
}

/**
 * Image (u,v) → board (x,y) homography via DLT. Supports n≥4 points (least squares when n>4)
 * so off-angle / perspective views are modeled, not just perpendicular shots.
 * @param {number[][]} srcPts - [[u,v], ...]
 * @param {number[][]} dstPts - [[x,y], ...] board space (same length, ≥4)
 * @returns {number[][] | null} 3×3 H
 */
export function homographyImageToBoard(srcPts, dstPts) {
  const n = srcPts.length;
  if (n !== dstPts.length || n < 4) return null;

  const srcNorm = normalizePoints2d(srcPts);
  const dstNorm = normalizePoints2d(dstPts);
  const A = [];
  const b = [];
  for (let i = 0; i < n; i++) {
    const u = srcNorm.pts[i][0];
    const v = srcNorm.pts[i][1];
    const x = dstNorm.pts[i][0];
    const y = dstNorm.pts[i][1];
    A.push([u, v, 1, 0, 0, 0, -x * u, -x * v]);
    b.push(x);
    A.push([0, 0, 0, u, v, 1, -y * u, -y * v]);
    b.push(y);
  }
  const h = n === 4 ? solveLinearSystem(A, b) : solveLinearSystemLeastSquares(A, b);
  if (!h) return null;
  const Hn = [
    [h[0], h[1], h[2]],
    [h[3], h[4], h[5]],
    [h[6], h[7], 1],
  ];
  const TdstInv = invert3x3(dstNorm.T);
  if (!TdstInv) return null;
  return multiply3x3(TdstInv, multiply3x3(Hn, srcNorm.T));
}

function solveLinearSystem(A, b) {
  const n = b.length;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let col = 0; col < n; col++) {
    let pivot = col;
    for (let r = col + 1; r < n; r++) {
      if (Math.abs(M[r][col]) > Math.abs(M[pivot][col])) pivot = r;
    }
    if (Math.abs(M[pivot][col]) < 1e-12) return null;
    [M[col], M[pivot]] = [M[pivot], M[col]];
    const div = M[col][col];
    for (let c = col; c <= n; c++) M[col][c] /= div;
    for (let r = 0; r < n; r++) {
      if (r === col) continue;
      const f = M[r][col];
      for (let c = col; c <= n; c++) M[r][c] -= f * M[col][c];
    }
  }
  return M.map((row) => row[n]);
}

/** 3×3 matrix inverse (non-singular). */
export function invert3x3(m) {
  const a = m[0][0],
    b = m[0][1],
    c = m[0][2];
  const d = m[1][0],
    e = m[1][1],
    f = m[1][2];
  const g = m[2][0],
    h = m[2][1],
    i = m[2][2];
  const A = e * i - f * h;
  const B = -(d * i - f * g);
  const C = d * h - e * g;
  const D = -(b * i - c * h);
  const E = a * i - c * g;
  const F = -(a * h - b * g);
  const G = b * f - c * e;
  const H = -(a * f - c * d);
  const I = a * e - b * d;
  const det = a * A + b * B + c * C;
  if (Math.abs(det) < 1e-14) return null;
  const invDet = 1 / det;
  return [
    [A * invDet, D * invDet, G * invDet],
    [B * invDet, E * invDet, H * invDet],
    [C * invDet, F * invDet, I * invDet],
  ];
}

/** Apply 3×3 H to Euclidean image point; returns [x,y] board. */
export function applyHomography(H, u, v) {
  const x0 = H[0][0] * u + H[0][1] * v + H[0][2];
  const y0 = H[1][0] * u + H[1][1] * v + H[1][2];
  const w0 = H[2][0] * u + H[2][1] * v + H[2][2];
  if (Math.abs(w0) < 1e-12) return null;
  return [x0 / w0, y0 / w0];
}

/** Board (x,y) → image (u,v) using H⁻¹ (H maps image→board). */
export function boardToImage(Hinv, x, y) {
  return applyHomography(Hinv, x, y);
}

/** Board-space circle → perspective ellipse in image (dense sampling for skewed views). */
export function boardCircleToImagePoints(Hinv, radiusBoard, segments = 96) {
  const out = [];
  for (let i = 0; i < segments; i++) {
    const ang = (i / segments) * Math.PI * 2;
    const x = radiusBoard * Math.cos(ang);
    const y = radiusBoard * Math.sin(ang);
    const p = applyHomography(Hinv, x, y);
    if (p && Number.isFinite(p[0]) && Number.isFinite(p[1])) out.push(p);
  }
  if (out.length >= 3) out.push(out[0]);
  return out;
}

/** Dotted ring overlays drawn on the live calib video after markers define H. */
export const CALIBRATION_PREVIEW_RINGS = [
  { key: "outer", rBoard: BOARD_R, color: "rgba(255,255,255,0.9)", dash: [10, 6], width: 2 },
  {
    key: "double_out",
    rBoard: BOARD_R * DART_R_DOUBLE_OUT,
    color: "rgba(94,184,255,0.85)",
    dash: [6, 5],
    width: 1.5,
  },
  {
    key: "double_in",
    rBoard: BOARD_R * DART_R_OUTER_SINGLE_OUT,
    color: "rgba(94,184,255,0.65)",
    dash: [6, 5],
    width: 1.5,
  },
  {
    key: "triple_out",
    rBoard: BOARD_R * DART_R_TRIPLE_OUT,
    color: "rgba(255,196,72,0.85)",
    dash: [5, 4],
    width: 1.5,
  },
  {
    key: "triple_in",
    rBoard: BOARD_R * DART_R_INNER_SINGLE_OUT,
    color: "rgba(255,196,72,0.6)",
    dash: [5, 4],
    width: 1.5,
  },
];

/**
 * Bilinear sample from ImageData at fractional (u,v). Outside: black.
 * @param {ImageData} src
 */
export function sampleBilinear(src, u, v) {
  const w = src.width;
  const h = src.height;
  if (u < 0 || v < 0 || u > w - 1 || v > h - 1) return 0;
  const x0 = Math.floor(u);
  const y0 = Math.floor(v);
  const x1 = Math.min(x0 + 1, w - 1);
  const y1 = Math.min(y0 + 1, h - 1);
  const fx = u - x0;
  const fy = v - y0;
  const d = src.data;
  const idx = (x, y) => 4 * (y * w + x);
  const g = (xi, yi) => {
    const o = idx(xi, yi);
    return 0.299 * d[o] + 0.587 * d[o + 1] + 0.114 * d[o + 2];
  };
  const g00 = g(x0, y0);
  const g10 = g(x1, y0);
  const g01 = g(x0, y1);
  const g11 = g(x1, y1);
  return (1 - fx) * (1 - fy) * g00 + fx * (1 - fy) * g10 + (1 - fx) * fy * g01 + fx * fy * g11;
}

/**
 * Warp video frame to grayscale WARP_SIZE×WARP_SIZE; board disk radius = BOARD_R in pixel coords from center.
 * @param {ImageData} frame
 * @param {number[][]} Hinv - board→image
 * @returns {Float32Array} length WARP_SIZE * WARP_SIZE
 */
export function warpFrameToBoardGray(frame, Hinv) {
  const cx = WARP_SIZE / 2;
  const cy = WARP_SIZE / 2;
  const out = new Float32Array(WARP_SIZE * WARP_SIZE);
  let o = 0;
  for (let j = 0; j < WARP_SIZE; j++) {
    const yb = j + 0.5 - cy;
    for (let i = 0; i < WARP_SIZE; i++) {
      const xb = i + 0.5 - cx;
      const p = applyHomography(Hinv, xb, yb);
      out[o++] = p ? sampleBilinear(frame, p[0], p[1]) : 0;
    }
  }
  return out;
}

export function floatGrayToImageData(gray) {
  const c = document.createElement("canvas");
  c.width = WARP_SIZE;
  c.height = WARP_SIZE;
  const ctx = c.getContext("2d");
  const img = ctx.createImageData(WARP_SIZE, WARP_SIZE);
  for (let i = 0; i < gray.length; i++) {
    const v = Math.max(0, Math.min(255, gray[i] | 0));
    const o = 4 * i;
    img.data[o] = v;
    img.data[o + 1] = v;
    img.data[o + 2] = v;
    img.data[o + 3] = 255;
  }
  return img;
}

function warpPixelToBoardXY(px, py, boardCx) {
  return { x: px + 0.5 - boardCx, y: py + 0.5 - boardCx };
}

function isInsideBoardDisk(px, py, boardCx, boardR) {
  const xb = px + 0.5 - boardCx;
  const yb = py + 0.5 - boardCx;
  return xb * xb + yb * yb <= boardR * boardR;
}

/**
 * Bilinear RGB sample from ImageData at fractional (u,v). Outside: null.
 * @param {ImageData} src
 */
export function sampleRgbBilinear(src, u, v) {
  const w = src.width;
  const h = src.height;
  if (u < 0 || v < 0 || u > w - 1 || v > h - 1) return null;
  const x0 = Math.floor(u);
  const y0 = Math.floor(v);
  const x1 = Math.min(x0 + 1, w - 1);
  const y1 = Math.min(y0 + 1, h - 1);
  const fx = u - x0;
  const fy = v - y0;
  const d = src.data;
  const idx = (x, y) => 4 * (y * w + x);
  const ch = (off) => {
    const c00 = d[idx(x0, y0) + off];
    const c10 = d[idx(x1, y0) + off];
    const c01 = d[idx(x0, y1) + off];
    const c11 = d[idx(x1, y1) + off];
    return (1 - fx) * (1 - fy) * c00 + fx * (1 - fy) * c10 + (1 - fx) * fy * c01 + fx * fy * c11;
  };
  return { r: ch(0), g: ch(1), b: ch(2) };
}

/** Mean RGB in a square patch (image pixels). */
export function meanRgbPatch(frame, u, v, half = 7) {
  let sr = 0;
  let sg = 0;
  let sb = 0;
  let n = 0;
  for (let dy = -half; dy <= half; dy++) {
    for (let dx = -half; dx <= half; dx++) {
      const c = sampleRgbBilinear(frame, u + dx, v + dy);
      if (!c) continue;
      sr += c.r;
      sg += c.g;
      sb += c.b;
      n++;
    }
  }
  if (n === 0) return null;
  return { r: sr / n, g: sg / n, b: sb / n };
}

/**
 * Absolute difference; largest blob inside the board disk. Hit point = strongest diff pixel
 * in that blob (closer to dart tip than a plain centroid when the flight is visible).
 * @returns {{ x: number, y: number, cx: number, cy: number, area: number } | null} — x,y SVG coords
 */
export function diffDartCentroid(refGray, curGray, threshold = 28) {
  const n = refGray.length;
  if (n !== curGray.length || n !== WARP_SIZE * WARP_SIZE) return null;
  const boardCx = WARP_SIZE / 2;
  const boardR = BOARD_R;
  const mask = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    const px = i % WARP_SIZE;
    const py = (i / WARP_SIZE) | 0;
    if (!isInsideBoardDisk(px, py, boardCx, boardR)) continue;
    if (Math.abs(curGray[i] - refGray[i]) >= threshold) mask[i] = 1;
  }
  const seen = new Uint8Array(n);
  let bestArea = 0;
  let bestPeak = -1;
  let bestPeakDiff = 0;
  for (let start = 0; start < n; start++) {
    if (!mask[start] || seen[start]) continue;
    const q = [start];
    seen[start] = 1;
    let area = 0;
    let peak = start;
    let peakDiff = 0;
    for (let qi = 0; qi < q.length; qi++) {
      const cur = q[qi];
      area++;
      const diff = Math.abs(curGray[cur] - refGray[cur]);
      if (diff > peakDiff) {
        peakDiff = diff;
        peak = cur;
      }
      const px = cur % WARP_SIZE;
      const nbs = [];
      if (px > 0) nbs.push(cur - 1);
      if (px < WARP_SIZE - 1) nbs.push(cur + 1);
      if (cur >= WARP_SIZE) nbs.push(cur - WARP_SIZE);
      if (cur < n - WARP_SIZE) nbs.push(cur + WARP_SIZE);
      for (const nb of nbs) {
        if (seen[nb] || !mask[nb]) continue;
        seen[nb] = 1;
        q.push(nb);
      }
    }
    if (area > bestArea && area >= 8) {
      bestArea = area;
      bestPeak = peak;
      bestPeakDiff = peakDiff;
    }
  }
  if (bestArea < 8 || bestPeak < 0) return null;
  const peakPx = bestPeak % WARP_SIZE;
  const peakPy = (bestPeak / WARP_SIZE) | 0;
  const { x: xSvg, y: ySvg } = warpPixelToBoardXY(peakPx, peakPy, boardCx);
  return { x: xSvg, y: ySvg, cx: peakPx + 0.5, cy: peakPy + 0.5, area: bestArea, peakDiff: bestPeakDiff };
}

function isValidHomography(m) {
  if (!m || !Array.isArray(m) || m.length !== 3) return false;
  for (const row of m) {
    if (!Array.isArray(row) || row.length !== 3) return false;
    for (const v of row) {
      if (typeof v !== "number" || !Number.isFinite(v)) return false;
    }
  }
  return true;
}

/** True when saved homography matches the live camera frame size. */
export function homographyMatchesVideo(hData, videoW, videoH) {
  if (!hData?.H || !videoW || !videoH) return false;
  if (hData.videoW == null || hData.videoH == null) return true;
  return hData.videoW === videoW && hData.videoH === videoH;
}

export function loadHomography() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return null;
    const o = JSON.parse(raw);
    if (!isValidHomography(o.H)) return null;
    const Hinv = isValidHomography(o.Hinv) ? o.Hinv : null;
    return { H: o.H, Hinv, videoW: o.videoW ?? null, videoH: o.videoH ?? null };
  } catch {
    return null;
  }
}

/** Cached inverse from save time, or compute from H. */
export function homographyInverseFromStored(stored) {
  if (!stored?.H) return null;
  if (stored.Hinv) return stored.Hinv;
  return invert3x3(stored.H);
}

/** @returns {boolean} */
export function saveHomography(H, videoW, videoH) {
  if (!isValidHomography(H)) return false;
  const Hinv = invert3x3(H);
  if (!Hinv) return false;
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({ H, Hinv, videoW, videoH, v: 2 }));
    return loadHomography() != null;
  } catch {
    return false;
  }
}

export function clearHomography() {
  localStorage.removeItem(LS_KEY);
}

const REF_KEY = "dartFootballBoardRefGray";

/** Store warped reference frame as base64 of Float32 bytes. */
export function saveReferenceGray(gray) {
  const u8 = new Uint8Array(gray.buffer, gray.byteOffset, gray.byteLength);
  let s = "";
  for (let i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
  localStorage.setItem(REF_KEY, btoa(s));
}

export function loadReferenceGray() {
  try {
    const b64 = localStorage.getItem(REF_KEY);
    if (!b64) return null;
    const bin = atob(b64);
    const buf = new Float32Array(bin.length / 4);
    const u8 = new Uint8Array(buf.buffer);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    if (buf.length !== WARP_SIZE * WARP_SIZE) return null;
    return buf;
  } catch {
    return null;
  }
}

export function clearReferenceGray() {
  localStorage.removeItem(REF_KEY);
}

const BIAS_KEY = "dartFootballCvBoardBias";
const LAST_DETECT_KEY = "dartFootballLastCvDetect";

export function loadCvBoardBias() {
  try {
    const raw = localStorage.getItem(BIAS_KEY);
    if (!raw) return { x: 0, y: 0 };
    const o = JSON.parse(raw);
    return { x: Number(o.x) || 0, y: Number(o.y) || 0 };
  } catch {
    return { x: 0, y: 0 };
  }
}

export function saveCvBoardBias(x, y) {
  localStorage.setItem(BIAS_KEY, JSON.stringify({ x, y, v: 1 }));
}

/** Apply learned offset (board SVG coords) to raw centroid before classification. */
export function applyCvBoardBias(x, y) {
  const b = loadCvBoardBias();
  return { x: x + b.x, y: y + b.y };
}

export const CV_BIAS_LEARN_ALPHA = 0.35;

/**
 * One EWMA step toward error = (corrected − raw); used by learnCvBoardBiasFromCorrection.
 * Pure math — safe to unit test in Node without localStorage.
 */
export function ewmaCvBias(biasX, biasY, rawX, rawY, correctedX, correctedY, alpha = CV_BIAS_LEARN_ALPHA) {
  const errX = correctedX - rawX;
  const errY = correctedY - rawY;
  return {
    x: (1 - alpha) * biasX + alpha * errX,
    y: (1 - alpha) * biasY + alpha * errY,
  };
}

export function learnCvBoardBiasFromCorrection(rawX, rawY, correctedX, correctedY) {
  const b = loadCvBoardBias();
  const n = ewmaCvBias(b.x, b.y, rawX, rawY, correctedX, correctedY);
  saveCvBoardBias(n.x, n.y);
}

export function saveLastCvDetectionSnapshot(rawX, rawY, appliedX, appliedY) {
  try {
    localStorage.setItem(LAST_DETECT_KEY, JSON.stringify({ rawX, rawY, appliedX, appliedY, v: 1 }));
  } catch {
    /* ignore quota / privacy mode */
  }
}

export function loadLastCvDetectionSnapshot() {
  try {
    const raw = localStorage.getItem(LAST_DETECT_KEY);
    if (!raw) return null;
    const o = JSON.parse(raw);
    if (typeof o.rawX !== "number" || typeof o.rawY !== "number") return null;
    return {
      rawX: o.rawX,
      rawY: o.rawY,
      appliedX: o.appliedX,
      appliedY: o.appliedY,
    };
  } catch {
    return null;
  }
}

export function clearLastCvDetectionSnapshot() {
  try {
    localStorage.removeItem(LAST_DETECT_KEY);
  } catch {
    /* ignore */
  }
}

/** @returns {{ red: {r:number,g:number,b:number} | null, green: {r:number,g:number,b:number} | null } | null} */
export function loadDartColorProfiles() {
  try {
    const raw = localStorage.getItem(DART_COLORS_KEY);
    if (!raw) return null;
    const o = JSON.parse(raw);
    const pick = (x) =>
      x && typeof x.r === "number" && typeof x.g === "number" && typeof x.b === "number" ? x : null;
    return { red: pick(o.red), green: pick(o.green) };
  } catch {
    return null;
  }
}

export function saveDartColorProfile(team, rgb) {
  const cur = loadDartColorProfiles() || { red: null, green: null };
  if (team === "red") cur.red = rgb;
  else if (team === "green") cur.green = rgb;
  localStorage.setItem(DART_COLORS_KEY, JSON.stringify({ ...cur, v: 1 }));
}

export function clearDartColorProfiles() {
  localStorage.removeItem(DART_COLORS_KEY);
}

/** Squared RGB distance between two color samples. */
export function rgbDistance(a, b) {
  if (!a || !b) return Infinity;
  const dr = a.r - b.r;
  const dg = a.g - b.g;
  const db = a.b - b.b;
  return dr * dr + dg * dg + db * db;
}
