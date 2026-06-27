
import { homographyImageToBoard, invert3x3, loadHomography, saveHomography, homographyMatchesVideo, CALIBRATION_LANDMARKS } from './src/dart_football/gui/static/camera_cv.js';
import { BOARD_R } from './src/dart_football/gui/static/board_geometry.js';

const w=640, h=480;
const boardScale = (Math.min(w,h)*0.36)/BOARD_R;
const pts = CALIBRATION_LANDMARKS.map(lm => {
  const [bx,by] = lm.dst;
  return [w/2+bx*boardScale, h/2+by*boardScale];
});
const dst = CALIBRATION_LANDMARKS.map(lm => lm.dst);
const H = homographyImageToBoard(pts, dst);
console.log('H', H);
const Hinv = invert3x3(H);
console.log('Hinv ok', !!Hinv);
const saved = JSON.stringify({H, videoW:w, videoH:h, v:1});
const o = JSON.parse(saved);
const H2 = o.H;
const Hinv2 = invert3x3(H2);
console.log('after json Hinv ok', !!Hinv2);
console.log('match same', homographyMatchesVideo(o, w, h));
console.log('match diff', homographyMatchesVideo(o, 1280, 720));
