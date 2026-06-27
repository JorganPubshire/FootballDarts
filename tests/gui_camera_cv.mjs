/**
 * Node smoke test for homography + board hit math (run: node tests/gui_camera_cv.mjs).
 */
import assert from "node:assert/strict";
import {
  homographyImageToBoard,
  invert3x3,
  applyHomography,
  diffDartCentroid,
  WARP_SIZE,
  ewmaCvBias,
  CV_BIAS_LEARN_ALPHA,
  CALIBRATION_LANDMARKS,
  homographyMatchesVideo,
  homographyInverseFromStored,
  boardCircleToImagePoints,
  CALIBRATION_PREVIEW_RINGS,
  rgbDistance,
} from "../src/dart_football/gui/static/camera_cv.js";
import { hitFromBoardXY, BOARD_R } from "../src/dart_football/gui/static/board_geometry.js";

const src = [
  [0, 0],
  [100, 0],
  [100, 100],
  [0, 100],
];
const dst = [
  [-BOARD_R, -BOARD_R],
  [BOARD_R, -BOARD_R],
  [BOARD_R, BOARD_R],
  [-BOARD_R, BOARD_R],
];
const H = homographyImageToBoard(src, dst);
assert(H, "H computed");
const mid = applyHomography(H, 50, 50);
assert(mid);
assert.ok(Math.abs(mid[0]) < 0.01 && Math.abs(mid[1]) < 0.01, `center maps to origin got ${mid}`);

const Hinv = invert3x3(H);
assert(Hinv);
const corner = applyHomography(Hinv, BOARD_R, BOARD_R);
assert.ok(Math.abs(corner[0] - 100) < 0.5 && Math.abs(corner[1] - 100) < 0.5, `inverse corner ${corner}`);

const ref = new Float32Array(WARP_SIZE * WARP_SIZE);
const cur = new Float32Array(WARP_SIZE * WARP_SIZE);
const cx = (WARP_SIZE / 2) | 0;
const cy = (WARP_SIZE / 2) | 0;
for (let i = 0; i < ref.length; i++) ref[i] = 120;
for (let i = 0; i < cur.length; i++) cur[i] = 120;
for (let dy = -3; dy <= 3; dy++) {
  for (let dx = -3; dx <= 3; dx++) {
    const idx = (cy + dy) * WARP_SIZE + (cx + dx);
    cur[idx] = 200;
  }
}
const det = diffDartCentroid(ref, cur, 40);
assert(det);
assert.ok(Math.abs(det.x) < 5 && Math.abs(det.y) < 5, `blob peak ${det.x},${det.y}`);

const h = hitFromBoardXY(0, -BOARD_R * 0.5);
assert.equal(h.segment, 20);

const b1 = ewmaCvBias(0, 0, 0, 0, 10, -5);
assert.ok(Math.abs(b1.x - CV_BIAS_LEARN_ALPHA * 10) < 1e-12, `b1.x ${b1.x}`);
assert.ok(Math.abs(b1.y - CV_BIAS_LEARN_ALPHA * -5) < 1e-12, `b1.y ${b1.y}`);

for (const lm of CALIBRATION_LANDMARKS) {
  const [x, y] = lm.dst;
  const r = Math.hypot(x, y);
  assert.ok(r <= BOARD_R + 1e-6, `${lm.key} landmark should lie on or inside board disk`);
}
assert.equal(CALIBRATION_LANDMARKS.length, 5);
assert.equal(CALIBRATION_LANDMARKS[0].dst[0], 0);
assert.equal(CALIBRATION_LANDMARKS[0].dst[1], 0);

const src5 = [
  [320, 240],
  [320, 80],
  [520, 240],
  [320, 400],
  [120, 240],
];
const dst5 = CALIBRATION_LANDMARKS.map((lm) => lm.dst);
const H5 = homographyImageToBoard(src5, dst5);
assert(H5, "5-point perspective H computed");
const bull5 = applyHomography(H5, 320, 240);
assert.ok(bull5 && Math.abs(bull5[0]) < 2 && Math.abs(bull5[1]) < 2, `5pt bull ${bull5}`);

assert.equal(homographyMatchesVideo({ H, videoW: 640, videoH: 480 }, 640, 480), true);
assert.equal(homographyMatchesVideo({ H, videoW: 640, videoH: 480 }, 1280, 720), false);
assert.equal(homographyMatchesVideo({ H, videoW: null, videoH: null }, 640, 480), true);

const stored = { H, Hinv: invert3x3(H), videoW: 640, videoH: 480 };
assert(homographyInverseFromStored(stored));
const ringPts = boardCircleToImagePoints(invert3x3(H), 180);
assert.ok(ringPts.length > 10, "board circle projects to image");
assert.ok(CALIBRATION_PREVIEW_RINGS.length >= 3, "preview rings defined");

assert.ok(rgbDistance({ r: 0, g: 0, b: 0 }, { r: 3, g: 4, b: 0 }) > 0);
assert.equal(rgbDistance(null, { r: 1, g: 1, b: 1 }), Infinity);

console.log("gui_camera_cv.mjs OK");
