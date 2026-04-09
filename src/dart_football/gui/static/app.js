/**
 * Dart Football GUI — drives /api/state and /api/apply.
 * Dartboard: polar hit-test; segment order clockwise from top per standard London board.
 */

const SEGMENT_ORDER = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5];

/**
 * Dartboard geometry: rNorm = r / R where R is the board outer radius (SVG units).
 * Keep classifyRing, drawBoard, and hit-test (rNorm) aligned.
 * Inner and outer single zones have equal radial depth D (along a radius from center).
 * Triple and double bands are thin (same thickness t); number ring is outside DOUBLE_OUT.
 */
const DART_R_BULL_INNER = 0.038;
const DART_R_BULL_OUTER = 0.092;
const DART_R_TRIPLE_BAND = 0.045;
const DART_R_DOUBLE_BAND = 0.045;
const DART_R_DOUBLE_OUT = 0.84;
/** 2*D + triple_band + double_band = DOUBLE_OUT − bull ⇒ equal inner/outer single radial depth D. */
const DART_R_SINGLE_DEPTH =
  (DART_R_DOUBLE_OUT -
    DART_R_BULL_OUTER -
    DART_R_TRIPLE_BAND -
    DART_R_DOUBLE_BAND) /
  2;
const DART_R_INNER_SINGLE_OUT = DART_R_BULL_OUTER + DART_R_SINGLE_DEPTH;
const DART_R_TRIPLE_OUT = DART_R_INNER_SINGLE_OUT + DART_R_TRIPLE_BAND;
const DART_R_OUTER_SINGLE_OUT = DART_R_TRIPLE_OUT + DART_R_SINGLE_DEPTH;

function nth(n) {
  if (n === 1) return "st";
  if (n === 2) return "nd";
  if (n === 3) return "rd";
  return "th";
}

let uiData = null;
let boardProfile = null;
let boardTitle = "";
let scrimmageCfg = { segment_min: 1, segment_max: 20, bull_green: 20, bull_red: 18 };
let kickoffCfg = { segment_min: 1, segment_max: 20 };
let puntCfg = { segment_min: 1, segment_max: 20 };

function toast(msg, isErr) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.remove("hidden", "err");
  if (isErr) el.classList.add("err");
  setTimeout(() => el.classList.add("hidden"), 3200);
}

function segmentFromAngle(x, y) {
  const angleDeg = (Math.atan2(y, x) * 180) / Math.PI;
  const fromTop = (angleDeg + 90 + 360) % 360;
  const idx = Math.floor(fromTop / 18) % 20;
  return SEGMENT_ORDER[idx];
}

/** rNorm: distance / maxRadius (0..1) */
function classifyRing(rNorm) {
  if (rNorm <= DART_R_BULL_INNER) return { ring: "inner_bull", bull: "red" };
  if (rNorm <= DART_R_BULL_OUTER) return { ring: "outer_bull", bull: "green" };
  if (rNorm <= DART_R_INNER_SINGLE_OUT) return { ring: "single" };
  if (rNorm <= DART_R_TRIPLE_OUT) return { ring: "triple" };
  if (rNorm <= DART_R_OUTER_SINGLE_OUT) return { ring: "single_mid" };
  if (rNorm <= DART_R_DOUBLE_OUT) return { ring: "double" };
  return { ring: "outside" };
}

function drawBoard(svg) {
  svg.replaceChildren();
  const ns = "http://www.w3.org/2000/svg";
  const R = 180;
  const BULL_INNER = DART_R_BULL_INNER;
  const BULL_OUTER = DART_R_BULL_OUTER;
  const INNER_SINGLE_OUT = DART_R_INNER_SINGLE_OUT;
  const TRIPLE_OUT = DART_R_TRIPLE_OUT;
  const OUTER_SINGLE_OUT = DART_R_OUTER_SINGLE_OUT;
  const DOUBLE_OUT = DART_R_DOUBLE_OUT;

  const wireStroke = "#d0d0d0";
  const wireDim = "rgba(210,210,210,0.65)";
  const scoreRed = "#c8102e";
  const singleBlack = "#121212";
  const scoreGreen = "#157a3a";
  const singleCream = "#e8dcc8";
  const outerRing = "#050505";
  /** True London order: alternate black / cream singles; black→red D+T, cream→green D+T. */
  function wedgeStyle(i) {
    const blackWedge = i % 2 === 0;
    return {
      dt: blackWedge ? scoreRed : scoreGreen,
      single: blackWedge ? singleBlack : singleCream,
    };
  }
  const greenBullFill = "#1fa34a";
  const redBullFill = "#d9102a";

  /** Annular sector path: angles in radians, CCW from +x */
  function sectorPath(r0, r1, a0, a1) {
    const x0o = r1 * Math.cos(a0);
    const y0o = r1 * Math.sin(a0);
    const x1o = r1 * Math.cos(a1);
    const y1o = r1 * Math.sin(a1);
    const x0i = r0 * Math.cos(a1);
    const y0i = r0 * Math.sin(a1);
    const x1i = r0 * Math.cos(a0);
    const y1i = r0 * Math.sin(a0);
    const large = a1 - a0 > Math.PI ? 1 : 0;
    return [
      `M ${x1i} ${y1i}`,
      `L ${x0o} ${y0o}`,
      `A ${r1} ${r1} 0 ${large} 1 ${x1o} ${y1o}`,
      `L ${x0i} ${y0i}`,
      `A ${r0} ${r0} 0 ${large} 0 ${x1i} ${y1i}`,
      "Z",
    ].join(" ");
  }

  function wedgeAngles(i) {
    const a0 = ((i * 18 - 90 - 9) * Math.PI) / 180;
    const a1 = ((i * 18 - 90 + 9) * Math.PI) / 180;
    return { a0, a1 };
  }

  const bg = document.createElementNS(ns, "circle");
  bg.setAttribute("cx", "0");
  bg.setAttribute("cy", "0");
  bg.setAttribute("r", String(R));
  bg.setAttribute("fill", outerRing);
  svg.appendChild(bg);

  for (let i = 0; i < 20; i++) {
    const { a0, a1 } = wedgeAngles(i);
    const { dt, single } = wedgeStyle(i);

    const pInner = document.createElementNS(ns, "path");
    pInner.setAttribute("d", sectorPath(R * BULL_OUTER, R * INNER_SINGLE_OUT, a0, a1));
    pInner.setAttribute("fill", single);
    pInner.setAttribute("stroke", "none");
    svg.appendChild(pInner);

    const pTrip = document.createElementNS(ns, "path");
    pTrip.setAttribute("d", sectorPath(R * INNER_SINGLE_OUT, R * TRIPLE_OUT, a0, a1));
    pTrip.setAttribute("fill", dt);
    pTrip.setAttribute("stroke", "none");
    svg.appendChild(pTrip);

    const pMid = document.createElementNS(ns, "path");
    pMid.setAttribute("d", sectorPath(R * TRIPLE_OUT, R * OUTER_SINGLE_OUT, a0, a1));
    pMid.setAttribute("fill", single);
    pMid.setAttribute("stroke", "none");
    svg.appendChild(pMid);

    const pDbl = document.createElementNS(ns, "path");
    pDbl.setAttribute("d", sectorPath(R * OUTER_SINGLE_OUT, R * DOUBLE_OUT, a0, a1));
    pDbl.setAttribute("fill", dt);
    pDbl.setAttribute("stroke", "none");
    svg.appendChild(pDbl);

    const pNum = document.createElementNS(ns, "path");
    pNum.setAttribute("d", sectorPath(R * DOUBLE_OUT, R, a0, a1));
    pNum.setAttribute("fill", outerRing);
    pNum.setAttribute("stroke", "none");
    svg.appendChild(pNum);
  }

  const greenBull = document.createElementNS(ns, "circle");
  greenBull.setAttribute("cx", "0");
  greenBull.setAttribute("cy", "0");
  greenBull.setAttribute("r", String(R * BULL_OUTER));
  greenBull.setAttribute("fill", greenBullFill);
  greenBull.setAttribute("stroke", wireStroke);
  greenBull.setAttribute("stroke-width", "1.1");
  svg.appendChild(greenBull);

  const redBull = document.createElementNS(ns, "circle");
  redBull.setAttribute("cx", "0");
  redBull.setAttribute("cy", "0");
  redBull.setAttribute("r", String(R * BULL_INNER));
  redBull.setAttribute("fill", redBullFill);
  redBull.setAttribute("stroke", wireStroke);
  redBull.setAttribute("stroke-width", "0.95");
  svg.appendChild(redBull);

  /* Spider: inner/outer bull, inner/outer triple, inner/outer double, board edge. */
  const radii = [BULL_INNER, BULL_OUTER, INNER_SINGLE_OUT, TRIPLE_OUT, OUTER_SINGLE_OUT, DOUBLE_OUT, 1.0];
  radii.forEach((t) => {
    const c = document.createElementNS(ns, "circle");
    c.setAttribute("cx", "0");
    c.setAttribute("cy", "0");
    c.setAttribute("r", String(R * t));
    c.setAttribute("fill", "none");
    const onBoardEdge = t >= 0.999;
    const onDoubleOuter = Math.abs(t - DOUBLE_OUT) < 1e-6;
    c.setAttribute("stroke", onBoardEdge || onDoubleOuter ? wireStroke : wireDim);
    c.setAttribute("stroke-width", onBoardEdge ? "1.5" : onDoubleOuter ? "1.25" : "0.95");
    svg.appendChild(c);
  });

  /**
   * Radials only between wedge boundaries: outer bull to outer double (classic spider), not through the number ring.
   */
  const rRadialInner = R * BULL_OUTER;
  const rRadialOuter = R * DOUBLE_OUT;
  for (let i = 0; i < 20; i++) {
    const a = ((i * 18 - 90 - 9) * Math.PI) / 180;
    const x1 = rRadialInner * Math.cos(a);
    const y1 = rRadialInner * Math.sin(a);
    const x2 = rRadialOuter * Math.cos(a);
    const y2 = rRadialOuter * Math.sin(a);
    const line = document.createElementNS(ns, "line");
    line.setAttribute("x1", String(x1));
    line.setAttribute("y1", String(y1));
    line.setAttribute("x2", String(x2));
    line.setAttribute("y2", String(y2));
    line.setAttribute("stroke", wireStroke);
    line.setAttribute("stroke-width", "1.05");
    line.setAttribute("opacity", "1");
    svg.appendChild(line);
  }

  /* Numbers in the wide black ring, on each wedge's angular bisector (center of the 18° slice). */
  const numRingMid = R * (DOUBLE_OUT + (1 - DOUBLE_OUT) * 0.52);
  for (let i = 0; i < 20; i++) {
    const { a0, a1 } = wedgeAngles(i);
    const mid = (a0 + a1) / 2;
    const seg = SEGMENT_ORDER[i];
    const tx = numRingMid * Math.cos(mid);
    const ty = numRingMid * Math.sin(mid);
    const t = document.createElementNS(ns, "text");
    t.setAttribute("x", String(tx));
    t.setAttribute("y", String(ty));
    t.setAttribute("text-anchor", "middle");
    t.setAttribute("dominant-baseline", "middle");
    t.setAttribute("fill", "#eaeaea");
    t.setAttribute("font-size", "12");
    t.setAttribute("font-weight", "600");
    t.setAttribute("font-family", "Arial, Helvetica, sans-serif");
    t.setAttribute("stroke", "rgba(0,0,0,0.55)");
    t.setAttribute("stroke-width", "0.3");
    t.setAttribute("paint-order", "stroke fill");
    t.textContent = String(seg);
    svg.appendChild(t);
  }
}

function buildEvent(profile, hit, fgZone) {
  const { segment, ring, bull } = hit;
  const sc = scrimmageCfg;
  const bg = sc.bull_green ?? 20;
  const br = sc.bull_red ?? 18;

  if (profile === "strip") {
    if (ring.startsWith("bull") || ring === "outside") {
      throw new Error("Strip dart: numbered wedge only");
    }
    if (segment < sc.segment_min || segment > sc.segment_max) {
      throw new Error(`Segment must be ${sc.segment_min}–${sc.segment_max}`);
    }
    return { type: "ScrimmageStripDart", segment };
  }

  if (profile === "kickoff" || profile === "kickoff_run_out") {
    if (ring === "outside") {
      return {
        type: profile === "kickoff_run_out" ? "KickoffRunOutKick" : "KickoffKick",
        segment,
        bull: "none",
        miss: true,
      };
    }
    if (ring === "inner_bull" || ring === "outer_bull") {
      const isGreen = bull === "green";
      return {
        type: profile === "kickoff_run_out" ? "KickoffRunOutKick" : "KickoffKick",
        segment: isGreen ? bg : br,
        bull: isGreen ? "green" : "red",
      };
    }
    return {
      type: profile === "kickoff_run_out" ? "KickoffRunOutKick" : "KickoffKick",
      segment,
      bull: "none",
    };
  }

  if (profile === "kickoff_return") {
    if (ring === "outside") {
      return {
        type: "KickoffReturnKick",
        segment,
        bull: "none",
        double_ring: false,
        triple_ring: false,
        triple_inner: null,
        miss: true,
      };
    }
    const base = {
      type: "KickoffReturnKick",
      segment,
      bull: "none",
      double_ring: false,
      triple_ring: false,
      triple_inner: null,
    };
    if (ring === "double") base.double_ring = true;
    if (ring === "triple") base.triple_ring = true;
    if (ring === "inner_bull" || ring === "outer_bull") {
      const isGreen = bull === "green";
      base.bull = isGreen ? "green" : "red";
      base.segment = isGreen ? bg : br;
    }
    return base;
  }

  if (profile === "punt") {
    if (ring === "outside") {
      return { type: "PuntKick", segment, bull: "none", miss: true };
    }
    if (ring === "inner_bull" || ring === "outer_bull") {
      const isGreen = bull === "green";
      return {
        type: "PuntKick",
        segment: isGreen ? bg : br,
        bull: isGreen ? "green" : "red",
      };
    }
    return { type: "PuntKick", segment, bull: "none" };
  }

  if (profile === "field_goal_offense") {
    if (!fgZone) throw new Error("Select FG zone");
    if (ring === "outside") {
      return { type: "FieldGoalOffenseDart", zone: fgZone, segment, miss: true };
    }
    return { type: "FieldGoalOffenseDart", zone: fgZone, segment, miss: false };
  }

  if (profile === "field_goal_fake" || profile === "field_goal_defense") {
    const ev =
      profile === "field_goal_fake" ? "FieldGoalFakeOffenseDart" : "FieldGoalDefenseDart";
    if (ring === "outside") {
      return {
        type: ev,
        segment,
        bull: "none",
        double_ring: false,
        triple_ring: false,
        triple_inner: null,
        miss: true,
      };
    }
    const o = {
      type: ev,
      segment,
      bull: "none",
      double_ring: false,
      triple_ring: false,
      triple_inner: null,
      miss: false,
    };
    if (ring === "double") o.double_ring = true;
    if (ring === "triple") o.triple_ring = true;
    if (ring === "inner_bull" || ring === "outer_bull") {
      const isGreen = bull === "green";
      o.bull = isGreen ? "green" : "red";
      o.segment = isGreen ? bg : br;
    }
    return o;
  }

  /* scrimmage_offense / scrimmage_defense */
  const isDef = profile === "scrimmage_defense";
  const typ = isDef ? "ScrimmageDefense" : "ScrimmageOffense";
  if (ring === "outside") {
    return {
      type: typ,
      segment,
      bull: "none",
      double_ring: false,
      triple_ring: false,
      triple_inner: null,
      miss: true,
    };
  }
  const o = {
    type: typ,
    segment,
    bull: "none",
    double_ring: false,
    triple_ring: false,
    triple_inner: null,
    miss: false,
  };
  if (ring === "double") o.double_ring = true;
  if (ring === "triple") o.triple_ring = true;
  if (ring === "inner_bull" || ring === "outer_bull") {
    const isGreen = bull === "green";
    o.bull = isGreen ? "green" : "red";
    o.segment = isGreen ? bg : br;
  }
  return o;
}

function hitFromClient(svg, clientX, clientY) {
  const pt = svg.createSVGPoint();
  pt.x = clientX;
  pt.y = clientY;
  const ctm = svg.getScreenCTM();
  if (!ctm) throw new Error("no CTM");
  const loc = pt.matrixTransform(ctm.inverse());
  const x = loc.x;
  const y = loc.y;
  const r = Math.hypot(x, y);
  const rNorm = r / 180;
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

/** Euclidean distance from board center in SVG units (same geometry as drawBoard R=180). */
function distanceFromBoardCenter(hit) {
  return hit.rNorm * 180;
}

function addCoinTossMarker(svg, x, y, fill) {
  const ns = "http://www.w3.org/2000/svg";
  const c = document.createElementNS(ns, "circle");
  c.setAttribute("cx", String(x));
  c.setAttribute("cy", String(y));
  c.setAttribute("r", "7");
  c.setAttribute("fill", fill);
  c.setAttribute("stroke", "rgba(255,255,255,0.85)");
  c.setAttribute("stroke-width", "1.5");
  c.setAttribute("opacity", "0.92");
  svg.appendChild(c);
  return c;
}

/** @type {{ red: { dist: number, x: number, y: number } | null, green: { dist: number, x: number, y: number } | null } | null} */
let coinTossDartSession = null;

function describeHit(hit) {
  const r = hit.ring;
  if (r === "inner_bull") return "Inner bull (red)";
  if (r === "outer_bull") return "Outer bull (green)";
  if (r === "triple") return `Wedge ${hit.segment} — triple`;
  if (r === "double") return `Wedge ${hit.segment} — double`;
  if (r === "outside") return "Miss (outer number ring — 0 yd)";
  return `Wedge ${hit.segment} — single`;
}

/** NFL-style number at each 10-yard line: distance from nearest goal. */
function yardLineNumber(y) {
  if (y === 50) return "50";
  return String(Math.min(y, 100 - y));
}

/**
 * Renders the football field as SVG (Green goal left yard 0, Red goal right yard 100).
 * Data from ``gui_field_graphic_spec`` / ``field_graphic`` API payload.
 */
function renderFieldGraphic(spec) {
  const svg = document.getElementById("field-svg");
  const legend = document.getElementById("field-legend");
  if (!svg) return;

  const ns = "http://www.w3.org/2000/svg";
  svg.replaceChildren();

  if (!spec || typeof spec.los_yard !== "number") {
    if (legend) legend.replaceChildren();
    const err = document.createElementNS(ns, "text");
    err.setAttribute("x", "232");
    err.setAttribute("y", "120");
    err.setAttribute("text-anchor", "middle");
    err.setAttribute("fill", "#8a9bb0");
    err.setAttribute("font-size", "4");
    err.textContent = "No field data";
    svg.setAttribute("viewBox", "0 0 464 240");
    return;
  }

  /** Multiple SVG units per yard so yard lines land on crisp coordinates when scaled. */
  const UPY = 4;
  /** NFL playing field: 100 yd goal-to-goal, 53⅓ yd (160/3) sideline-to-sideline. */
  const FIELD_LENGTH_YD = 100;
  const FIELD_WIDTH_YD = 160 / 3;
  const ez = 8 * UPY;
  const fieldW = FIELD_LENGTH_YD * UPY;
  const fieldH = (fieldW * FIELD_WIDTH_YD) / FIELD_LENGTH_YD;
  const fieldX0 = ez;
  const fieldX1 = fieldX0 + fieldW;
  const W = ez + fieldW + ez;
  const top = 7;
  const bottomPad = Math.max(10, fieldH * 0.04);
  const H = top + fieldH + bottomPad;

  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", String(W));
  svg.setAttribute("height", String(H));
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

  function ydX(y) {
    return fieldX0 + Math.max(0, Math.min(100, Number(y))) * UPY;
  }

  const defs = document.createElementNS(ns, "defs");
  const turfGrad = document.createElementNS(ns, "linearGradient");
  turfGrad.setAttribute("id", "field-turf-grad");
  turfGrad.setAttribute("x1", "0");
  turfGrad.setAttribute("y1", "0");
  turfGrad.setAttribute("x2", "1");
  turfGrad.setAttribute("y2", "0");
  const ts0 = document.createElementNS(ns, "stop");
  ts0.setAttribute("offset", "0%");
  ts0.setAttribute("stop-color", "#152e20");
  const ts1 = document.createElementNS(ns, "stop");
  ts1.setAttribute("offset", "50%");
  ts1.setAttribute("stop-color", "#1a4028");
  const ts2 = document.createElementNS(ns, "stop");
  ts2.setAttribute("offset", "100%");
  ts2.setAttribute("stop-color", "#142a1c");
  turfGrad.appendChild(ts0);
  turfGrad.appendChild(ts1);
  turfGrad.appendChild(ts2);
  defs.appendChild(turfGrad);

  /* Horizontal-only turf texture — avoids vertical lines that beat against the 1-yd grid */
  const stripe = document.createElementNS(ns, "pattern");
  stripe.setAttribute("id", "field-stripes");
  stripe.setAttribute("width", "3");
  stripe.setAttribute("height", "3");
  stripe.setAttribute("patternUnits", "userSpaceOnUse");
  const s0 = document.createElementNS(ns, "rect");
  s0.setAttribute("width", "3");
  s0.setAttribute("height", "3");
  s0.setAttribute("fill", "transparent");
  stripe.appendChild(s0);
  const s1 = document.createElementNS(ns, "line");
  s1.setAttribute("x1", "0");
  s1.setAttribute("y1", "2.5");
  s1.setAttribute("x2", "3");
  s1.setAttribute("y2", "2.5");
  s1.setAttribute("stroke", "rgba(255,255,255,0.04)");
  s1.setAttribute("stroke-width", "0.35");
  stripe.appendChild(s1);
  defs.appendChild(stripe);
  svg.appendChild(defs);

  const gEz = document.createElementNS(ns, "rect");
  gEz.setAttribute("x", "0");
  gEz.setAttribute("y", String(top));
  gEz.setAttribute("width", String(ez));
  gEz.setAttribute("height", String(fieldH));
  gEz.setAttribute("fill", "#153d28");
  gEz.setAttribute("stroke", "rgba(61,214,140,0.45)");
  gEz.setAttribute("stroke-width", String(0.6 * UPY));
  svg.appendChild(gEz);

  const field = document.createElementNS(ns, "rect");
  field.setAttribute("x", String(fieldX0));
  field.setAttribute("y", String(top));
  field.setAttribute("width", String(fieldW));
  field.setAttribute("height", String(fieldH));
  field.setAttribute("fill", "url(#field-turf-grad)");
  svg.appendChild(field);

  const fieldStripe = document.createElementNS(ns, "rect");
  fieldStripe.setAttribute("x", String(fieldX0));
  fieldStripe.setAttribute("y", String(top));
  fieldStripe.setAttribute("width", String(fieldW));
  fieldStripe.setAttribute("height", String(fieldH));
  fieldStripe.setAttribute("fill", "url(#field-stripes)");
  svg.appendChild(fieldStripe);

  const rEz = document.createElementNS(ns, "rect");
  rEz.setAttribute("x", String(fieldX1));
  rEz.setAttribute("y", String(top));
  rEz.setAttribute("width", String(ez));
  rEz.setAttribute("height", String(fieldH));
  rEz.setAttribute("fill", "#3d1818");
  rEz.setAttribute("stroke", "rgba(255,107,107,0.45)");
  rEz.setAttribute("stroke-width", String(0.6 * UPY));
  svg.appendChild(rEz);

  const gLabel = document.createElementNS(ns, "text");
  gLabel.setAttribute("x", String(ez / 2));
  gLabel.setAttribute("y", String(top + fieldH / 2 + 1));
  gLabel.setAttribute("text-anchor", "middle");
  gLabel.setAttribute("dominant-baseline", "middle");
  gLabel.setAttribute("fill", "rgba(61,214,140,0.85)");
  gLabel.setAttribute("font-size", String(Math.max(4, fieldH * 0.022)));
  gLabel.setAttribute("font-weight", "700");
  gLabel.setAttribute("font-family", "Orbitron, sans-serif");
  gLabel.textContent = "G";
  svg.appendChild(gLabel);

  const rLabel = document.createElementNS(ns, "text");
  rLabel.setAttribute("x", String(fieldX1 + ez / 2));
  rLabel.setAttribute("y", String(top + fieldH / 2 + 1));
  rLabel.setAttribute("text-anchor", "middle");
  rLabel.setAttribute("dominant-baseline", "middle");
  rLabel.setAttribute("fill", "rgba(255,107,107,0.9)");
  rLabel.setAttribute("font-size", String(Math.max(4, fieldH * 0.022)));
  rLabel.setAttribute("font-weight", "700");
  rLabel.setAttribute("font-family", "Orbitron, sans-serif");
  rLabel.textContent = "R";
  svg.appendChild(rLabel);

  /*
   * Yard grid: x = fieldX0 + y * UPY (integer spacing, no subpixel drift).
   * Full-height lines for 5 yd, 10 yd, and midfield; 1 yd marks are short hash ticks
   * at top and bottom (broadcast / diagram style — avoids moiré from 99 full-height hairlines).
   */
  const hashLen = Math.min(12, Math.max(4, fieldH * 0.045));
  const yTopLo = top + 0.2;
  const yTopHi = top + hashLen;
  const yBotLo = top + fieldH - hashLen;
  const yBotHi = top + fieldH - 0.2;
  const yFullLo = top + 0.25;
  const yFullHi = top + fieldH - 0.25;

  const addVLine = (x, y1, y2, stroke, sw) => {
    const line = document.createElementNS(ns, "line");
    line.setAttribute("x1", String(x));
    line.setAttribute("x2", String(x));
    line.setAttribute("y1", String(y1));
    line.setAttribute("y2", String(y2));
    line.setAttribute("stroke", stroke);
    line.setAttribute("stroke-width", String(sw));
    line.setAttribute("shape-rendering", "crispEdges");
    svg.appendChild(line);
  };

  for (let y = 1; y < 100; y += 1) {
    const x = ydX(y);
    const isMid = y === 50;
    const isTen = y % 10 === 0 && !isMid;
    const isFive = y % 5 === 0 && !isTen && !isMid;
    const fullMajor = isMid || isTen || isFive;

    let stroke;
    let sw;
    if (isMid) {
      stroke = "rgba(255,255,255,0.38)";
      sw = 0.78;
    } else if (isTen) {
      stroke = "rgba(255,255,255,0.24)";
      sw = 0.75;
    } else if (isFive) {
      stroke = "rgba(255,255,255,0.15)";
      sw = 0.42;
    } else {
      stroke = "rgba(255,255,255,0.38)";
      sw = 0.55;
    }

    if (fullMajor) {
      addVLine(x, yFullLo, yFullHi, stroke, sw);
    } else {
      addVLine(x, yTopLo, yTopHi, stroke, sw);
      addVLine(x, yBotLo, yBotHi, stroke, sw);
    }
  }

  const glLeft = document.createElementNS(ns, "line");
  glLeft.setAttribute("x1", String(fieldX0));
  glLeft.setAttribute("x2", String(fieldX0));
  glLeft.setAttribute("y1", String(top));
  glLeft.setAttribute("y2", String(top + fieldH));
  glLeft.setAttribute("stroke", "rgba(255,255,255,0.75)");
  glLeft.setAttribute("stroke-width", String(1.2 * UPY));
  svg.appendChild(glLeft);

  const glRight = document.createElementNS(ns, "line");
  glRight.setAttribute("x1", String(fieldX1));
  glRight.setAttribute("x2", String(fieldX1));
  glRight.setAttribute("y1", String(top));
  glRight.setAttribute("y2", String(top + fieldH));
  glRight.setAttribute("stroke", "rgba(255,255,255,0.75)");
  glRight.setAttribute("stroke-width", String(1.2 * UPY));
  svg.appendChild(glRight);

  const sidelineT = document.createElementNS(ns, "line");
  sidelineT.setAttribute("x1", String(fieldX0));
  sidelineT.setAttribute("x2", String(fieldX1));
  sidelineT.setAttribute("y1", String(top));
  sidelineT.setAttribute("y2", String(top));
  sidelineT.setAttribute("stroke", "rgba(255,255,255,0.35)");
  sidelineT.setAttribute("stroke-width", String(0.5 * UPY));
  svg.appendChild(sidelineT);

  const sidelineB = document.createElementNS(ns, "line");
  sidelineB.setAttribute("x1", String(fieldX0));
  sidelineB.setAttribute("x2", String(fieldX1));
  sidelineB.setAttribute("y1", String(top + fieldH));
  sidelineB.setAttribute("y2", String(top + fieldH));
  sidelineB.setAttribute("stroke", "rgba(255,255,255,0.35)");
  sidelineB.setAttribute("stroke-width", String(0.5 * UPY));
  svg.appendChild(sidelineB);

  /** Decade yard numbers on both sidelines; top row rotated 180° for far-side perspective. */
  const yardMarkFs = Math.max(8.5, fieldH * 0.038);
  const yardPad = Math.max(2.2, fieldH * 0.028);
  const yardMarkYBot = top + fieldH - yardPad;
  const yardMarkYTop = top + yardPad;
  for (let yd = 10; yd <= 90; yd += 10) {
    const x = ydX(yd);
    const label = yardLineNumber(yd);
    const is50 = yd === 50;
    const fs = is50 ? yardMarkFs * 1.06 : yardMarkFs;
    const fill = is50 ? "rgba(255,255,255,0.82)" : "rgba(255,255,255,0.78)";
    const fwt = is50 ? "700" : "600";

    const tBot = document.createElementNS(ns, "text");
    tBot.setAttribute("x", String(x));
    tBot.setAttribute("y", String(yardMarkYBot));
    tBot.setAttribute("text-anchor", "middle");
    tBot.setAttribute("dominant-baseline", "middle");
    tBot.setAttribute("fill", fill);
    tBot.setAttribute("font-size", String(fs));
    tBot.setAttribute("font-weight", fwt);
    tBot.setAttribute("font-family", "Orbitron, sans-serif");
    tBot.textContent = label;
    svg.appendChild(tBot);

    const tTop = document.createElementNS(ns, "text");
    tTop.setAttribute("x", String(x));
    tTop.setAttribute("y", String(yardMarkYTop));
    tTop.setAttribute("text-anchor", "middle");
    tTop.setAttribute("dominant-baseline", "middle");
    tTop.setAttribute("fill", fill);
    tTop.setAttribute("font-size", String(fs));
    tTop.setAttribute("font-weight", fwt);
    tTop.setAttribute("font-family", "Orbitron, sans-serif");
    tTop.setAttribute("transform", `rotate(180 ${x} ${yardMarkYTop})`);
    tTop.textContent = label;
    svg.appendChild(tTop);
  }

  const los = spec.los_yard;
  const losX = ydX(los);
  const showFd = spec.show_scrimmage_markers && spec.first_down_yard != null;
  const fdYard = spec.first_down_yard;
  const same = spec.los_and_first_same;

  if (showFd && !same && fdYard != null) {
    const fdX = ydX(fdYard);
    const fdLine = document.createElementNS(ns, "line");
    fdLine.setAttribute("x1", String(fdX));
    fdLine.setAttribute("x2", String(fdX));
    fdLine.setAttribute("y1", String(top - 0.5));
    fdLine.setAttribute("y2", String(top + fieldH + 0.5));
    fdLine.setAttribute("stroke", "#e8c547");
    fdLine.setAttribute("stroke-width", String(0.55 * UPY));
    fdLine.setAttribute("stroke-dasharray", `${1.15 * UPY} ${0.95 * UPY}`);
    fdLine.setAttribute("opacity", "0.95");
    svg.appendChild(fdLine);
  }

  const losLine = document.createElementNS(ns, "line");
  losLine.setAttribute("x1", String(losX));
  losLine.setAttribute("x2", String(losX));
  losLine.setAttribute("y1", String(top - 1));
  losLine.setAttribute("y2", String(top + fieldH + 1));
  losLine.setAttribute("stroke", same ? "#fbbf24" : "#5eb8ff");
  losLine.setAttribute("stroke-width", String(same ? 1.05 * UPY : 0.82 * UPY));
  losLine.setAttribute("stroke-linecap", "round");
  svg.appendChild(losLine);

  const ballG = document.createElementNS(ns, "radialGradient");
  ballG.setAttribute("id", "ball-grad");
  const b0 = document.createElementNS(ns, "stop");
  b0.setAttribute("offset", "0%");
  b0.setAttribute("stop-color", "#8b4513");
  const b1 = document.createElementNS(ns, "stop");
  b1.setAttribute("offset", "100%");
  b1.setAttribute("stop-color", "#4a2510");
  ballG.appendChild(b0);
  ballG.appendChild(b1);
  defs.appendChild(ballG);

  const ballRx = 2.65 * UPY;
  const ballRy = Math.max(2.2, fieldH * 0.032);
  const ball = document.createElementNS(ns, "ellipse");
  ball.setAttribute("cx", String(losX));
  ball.setAttribute("cy", String(top + fieldH / 2));
  ball.setAttribute("rx", String(ballRx));
  ball.setAttribute("ry", String(ballRy));
  ball.setAttribute("fill", "url(#ball-grad)");
  ball.setAttribute("stroke", "rgba(0,0,0,0.35)");
  ball.setAttribute("stroke-width", "0.35");
  svg.appendChild(ball);

  const ballShine = document.createElementNS(ns, "ellipse");
  ballShine.setAttribute("cx", String(losX - 0.65 * UPY));
  ballShine.setAttribute("cy", String(top + fieldH / 2 - ballRy * 0.25));
  ballShine.setAttribute("rx", String(0.95 * UPY));
  ballShine.setAttribute("ry", String(ballRy * 0.28));
  ballShine.setAttribute("fill", "rgba(255,255,255,0.25)");
  svg.appendChild(ballShine);

  if (legend) {
    legend.replaceChildren();
    const mk = (cls, swatchColor, label) => {
      const row = document.createElement("span");
      row.className = `field-legend-item ${cls}`;
      const sw = document.createElement("span");
      sw.className = "field-legend-swatch";
      sw.style.background = swatchColor;
      const tx = document.createElement("span");
      tx.textContent = label;
      row.append(sw, tx);
      legend.appendChild(row);
    };
    if (same && showFd) {
      mk("los", "#fbbf24", "LOS & 1st-to-go line");
    } else {
      mk("los", "#5eb8ff", `LOS ${los} yd`);
      if (showFd && fdYard != null) mk("fd", "#e8c547", `1st down ${fdYard} yd`);
    }
    mk("ball", "#6b3e18", "Ball");
    const goal = document.createElement("span");
    goal.className = "field-legend-axis";
    goal.textContent =
      spec.goal_yard === 100 ? "Offense → Red goal" : "Offense → Green goal";
    legend.appendChild(goal);
  }
}

async function fetchState() {
  const r = await fetch("/api/state");
  if (!r.ok) throw new Error("state failed");
  uiData = await r.json();
  render();
}

function render() {
  if (!uiData) return;
  document.getElementById("rules-path").textContent = uiData.rules_path
    ? `Rules: ${uiData.rules_path}`
    : "";
  const st = uiData.state;
  const clk = st.clock || {};
  const playNum = (clk.plays_in_quarter ?? 0) + 1;
  document.getElementById("clock-line").textContent = `Q${clk.quarter ?? "?"} · Play ${playNum}`;
  renderFieldGraphic(uiData.field_graphic);
  const phaseRaw = uiData.phase || "";
  const phasePretty = phaseRaw.replace(/_/g, " ");
  document.getElementById("phase-title").textContent = phasePretty;
  document.getElementById("phase-hint").textContent = "";
  document.getElementById("rules-help").textContent = uiData.rules_help || "";

  const phaseCard = document.getElementById("phase-card");
  phaseCard.classList.toggle("phase-fourth", phaseRaw.includes("fourth_down"));

  const scores = st.scores || {};
  document.getElementById("score-red").textContent = String(scores.red ?? 0);
  document.getElementById("score-green").textContent = String(scores.green ?? 0);

  const to = st.timeouts || {};
  const q = clk.quarter ?? 1;
  const firstHalf = q <= 2;
  const tr = firstHalf ? to.red_q1_q2 : to.red_q3_q4;
  const tg = firstHalf ? to.green_q1_q2 : to.green_q3_q4;
  document.getElementById("to-red").textContent = String(tr ?? "—");
  document.getElementById("to-green").textContent = String(tg ?? "—");

  document.getElementById("quarter-badge").textContent = `Q${q}`;

  const poss = st.offense === "red" ? "Red" : "Green";
  const d = st.downs || {};
  const chipsEl = document.getElementById("chips");
  chipsEl.replaceChildren();
  const addChip = (text, extraClass) => {
    const s = document.createElement("span");
    s.className = extraClass ? `chip ${extraClass}` : "chip";
    s.textContent = text;
    chipsEl.appendChild(s);
  };
  addChip(`${poss} ball`, "chip-accent");
  if (d.down != null && d.to_go != null) {
    addChip(`${d.down}${nth(d.down)} & ${d.to_go}`, d.down === 4 ? "chip-gold" : undefined);
  }
  addChip(`Play #${playNum}`);

  document.getElementById("state-line").textContent =
    `Possession: ${poss} · Down ${d.down ?? "?"} & ${d.to_go ?? "?"} · ` +
    `Timeouts — Red ${tr} · Green ${tg}`;

  scrimmageCfg = uiData.scrimmage || scrimmageCfg;
  kickoffCfg = uiData.kickoff || kickoffCfg;
  puntCfg = uiData.punt || puntCfg;

  const logEl = document.getElementById("play-log");
  logEl.replaceChildren();
  (uiData.play_log || []).slice(-20).forEach((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    logEl.appendChild(li);
  });

  const actionsEl = document.getElementById("actions");
  actionsEl.replaceChildren();
  (uiData.actions || []).forEach((a) => {
    const b = document.createElement("button");
    b.textContent = a.label;
    const accent = a.accent;
    if (accent === "red" || accent === "green") {
      b.classList.add(`action-${accent}`);
    }
    b.addEventListener("click", () => onAction(a));
    actionsEl.appendChild(b);
  });

  const metaEl = document.getElementById("meta-nav");
  metaEl.replaceChildren();
  (uiData.meta || []).forEach((m) => {
    const b = document.createElement("button");
    b.textContent = m.label;
    b.addEventListener("click", () => onMeta(m.id));
    metaEl.appendChild(b);
  });
}

async function applyEvent(ev) {
  const r = await fetch("/api/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event: ev }),
  });
  const data = await r.json();
  if (!r.ok) {
    toast(data.error || "Apply failed", true);
    return;
  }
  if (data.halftime_prompt) {
    window.alert("Halftime. The first half is over. Continue to the second half when ready.");
  }
  if (data.ui) {
    uiData = data.ui;
    render();
  } else {
    await fetchState();
  }
  toast(data.effects_summary || "OK", false);
}

function openBoard(profile, title, needsFgZone) {
  boardProfile = profile;
  boardTitle = title;
  const overlay = document.getElementById("modal-overlay");
  const fg = document.getElementById("fg-zone");
  document.getElementById("modal-title").textContent = title || "Dartboard";
  document.getElementById("modal-sub").textContent =
    "Click where the dart hit, or the outer black number ring to record a miss (0 yd).";
  fg.classList.toggle("hidden", !needsFgZone);
  overlay.classList.remove("hidden");
  const svg = document.getElementById("dart-svg");
  drawBoard(svg);
  document.getElementById("dart-hover").textContent = "";

  const onMove = (e) => {
    try {
      const h = hitFromClient(svg, e.clientX, e.clientY);
      document.getElementById("dart-hover").textContent = describeHit(h);
    } catch {
      /* ignore */
    }
  };
  const onClick = async (e) => {
    e.preventDefault();
    let h;
    try {
      h = hitFromClient(svg, e.clientX, e.clientY);
    } catch {
      return;
    }
    let fgZone = null;
    if (needsFgZone) {
      const z = document.querySelector('input[name="fgz"]:checked');
      fgZone = z ? z.value : "triple_ring";
    }
    let ev;
    try {
      ev = buildEvent(profile, h, fgZone);
    } catch (err) {
      toast(err.message || String(err), true);
      return;
    }
    closeBoard();
    await applyEvent(ev);
  };

  svg.onmousemove = onMove;
  svg.onclick = onClick;
}

function closeBoard() {
  document.getElementById("modal-overlay").classList.add("hidden");
  const svg = document.getElementById("dart-svg");
  svg.onmousemove = null;
  svg.onclick = null;
  if (boardProfile === "coin_toss") {
    coinTossDartSession = null;
  }
  boardProfile = null;
}

function openCoinTossDartBoard() {
  coinTossDartSession = { red: null, green: null };
  boardProfile = "coin_toss";
  boardTitle = "Coin toss";
  const overlay = document.getElementById("modal-overlay");
  const fg = document.getElementById("fg-zone");
  document.getElementById("modal-title").textContent = "Red — coin toss throw";
  document.getElementById("modal-sub").textContent =
    "Tap where Red's dart landed. Then Green throws and taps their hit. Closest to the board center wins.";
  fg.classList.add("hidden");
  overlay.classList.remove("hidden");
  const svg = document.getElementById("dart-svg");
  drawBoard(svg);
  document.getElementById("dart-hover").textContent = "";

  const onMove = (e) => {
    try {
      const h = hitFromClient(svg, e.clientX, e.clientY);
      const d = distanceFromBoardCenter(h);
      document.getElementById("dart-hover").textContent =
        `${d.toFixed(1)} units from center — closest wins (wedge does not matter)`;
    } catch {
      /* ignore */
    }
  };
  const onClick = async (e) => {
    e.preventDefault();
    let h;
    try {
      h = hitFromClient(svg, e.clientX, e.clientY);
    } catch {
      return;
    }
    if (!coinTossDartSession) return;
    const dist = distanceFromBoardCenter(h);
    if (coinTossDartSession.red == null) {
      coinTossDartSession.red = { dist, x: h.x, y: h.y };
      addCoinTossMarker(svg, h.x, h.y, "rgba(255,107,107,0.95)");
      document.getElementById("modal-title").textContent = "Green — coin toss throw";
      document.getElementById("modal-sub").textContent =
        "Tap where Green's dart landed. Closest to the center wins the toss.";
      toast(`Red: ${dist.toFixed(1)} from center`, false);
      return;
    }
    const rDist = coinTossDartSession.red.dist;
    const gDist = dist;
    if (Math.abs(rDist - gDist) < 0.05) {
      toast("Too close to call — tap Green's throw again (or Cancel and restart).", true);
      return;
    }
    addCoinTossMarker(svg, h.x, h.y, "rgba(61,214,140,0.95)");
    const greenWins = gDist < rDist;
    const winner = greenWins ? "green" : "red";
    const summary = `${greenWins ? "Green" : "Red"} wins (${gDist.toFixed(1)} vs ${rDist.toFixed(1)} from center)`;
    coinTossDartSession = null;
    closeBoard();
    toast(summary, false);
    await applyEvent({ type: "CoinTossWinner", winner });
  };

  svg.onmousemove = onMove;
  svg.onclick = onClick;
}

function resetCoinOverlay() {
  const callRow = document.getElementById("coin-call-row");
  const stage = document.getElementById("coin-flip-stage");
  const resultLine = document.getElementById("coin-result-line");
  const disc = document.getElementById("coin-disc");
  const headsBtn = document.getElementById("coin-call-heads");
  const tailsBtn = document.getElementById("coin-call-tails");
  callRow.classList.remove("hidden");
  stage.classList.add("hidden");
  resultLine.textContent = "";
  disc.classList.remove("coin-spinning");
  stage.querySelector(".coin-scene")?.classList.remove("hidden");
  if (headsBtn) headsBtn.disabled = false;
  if (tailsBtn) tailsBtn.disabled = false;
}

function closeCoinOverlay() {
  const overlay = document.getElementById("coin-overlay");
  overlay.classList.add("hidden");
  overlay.setAttribute("aria-hidden", "true");
  resetCoinOverlay();
}

/**
 * Green calls heads/tails; fair bit flip (match CLI: 0 → heads). Match → Green wins.
 */
function openCoinTossSimulatedFlow() {
  resetCoinOverlay();
  const overlay = document.getElementById("coin-overlay");
  overlay.classList.remove("hidden");
  overlay.setAttribute("aria-hidden", "false");

  const runFlip = async (callHeads) => {
    const callRow = document.getElementById("coin-call-row");
    const stage = document.getElementById("coin-flip-stage");
    const resultLine = document.getElementById("coin-result-line");
    const disc = document.getElementById("coin-disc");
    const headsBtn = document.getElementById("coin-call-heads");
    const tailsBtn = document.getElementById("coin-call-tails");
    if (headsBtn) headsBtn.disabled = true;
    if (tailsBtn) tailsBtn.disabled = true;

    callRow.classList.add("hidden");
    stage.classList.remove("hidden");
    resultLine.textContent = "";
    disc.classList.remove("coin-spinning");
    void disc.offsetWidth;
    disc.classList.add("coin-spinning");

    const buf = new Uint8Array(1);
    crypto.getRandomValues(buf);
    const flipIsHeads = (buf[0] & 1) === 0;
    const flipWord = flipIsHeads ? "heads" : "tails";
    const callWord = callHeads ? "heads" : "tails";
    const greenWins = callHeads === flipIsHeads;
    const winner = greenWins ? "green" : "red";

    await new Promise((resolve) => {
      let settled = false;
      const done = () => {
        if (settled) return;
        settled = true;
        clearTimeout(fallback);
        disc.removeEventListener("animationend", done);
        stage.querySelector(".coin-scene")?.classList.add("hidden");
        resultLine.textContent = `It's ${flipWord}. Green called ${callWord} — ${greenWins ? "Green" : "Red"} wins the toss.`;
        resolve();
      };
      const fallback = setTimeout(done, 2600);
      disc.addEventListener("animationend", done, { once: true });
    });

    await new Promise((r) => setTimeout(r, 650));
    closeCoinOverlay();
    await applyEvent({ type: "CoinTossWinner", winner });
  };

  const headsBtn = document.getElementById("coin-call-heads");
  const tailsBtn = document.getElementById("coin-call-tails");
  const h = () => runFlip(true);
  const t = () => runFlip(false);
  headsBtn.onclick = h;
  tailsBtn.onclick = t;
}

async function onAction(a) {
  if (a.coin_toss === "darts") {
    openCoinTossDartBoard();
    return;
  }
  if (a.coin_toss === "simulated") {
    openCoinTossSimulatedFlow();
    return;
  }
  if (a.event) {
    await applyEvent(a.event);
    return;
  }
  if (a.board) {
    openBoard(a.board.profile, a.board.title, !!a.board.needs_fg_zone);
    return;
  }
}

async function onMeta(id) {
  if (id === "quit") {
    if (window.confirm("Exit?")) window.close();
    return;
  }
  if (id === "undo") {
    const r = await fetch("/api/meta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "undo" }),
    });
    const data = await r.json();
    if (!r.ok) {
      toast(data.error || "Undo failed", true);
      return;
    }
    uiData = data.ui;
    render();
    return;
  }
  if (id === "history") {
    const r = await fetch("/api/meta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "history" }),
    });
    const data = await r.json();
    if (data.history) {
      window.alert(data.history.map((h) => `${h.seq}: ${h.summary}`).join("\n"));
    }
    return;
  }
  if (id === "save") {
    const path = window.prompt("Save session JSON to path:", "session.json");
    if (!path) return;
    const r = await fetch("/api/meta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "save", path }),
    });
    const data = await r.json();
    if (!r.ok) {
      toast(data.error || "Save failed", true);
      return;
    }
    toast(`Saved ${data.path}`, false);
    return;
  }
  if (id === "timeout") {
    openTimeoutModal();
  }
}

function closeTimeoutModal() {
  const el = document.getElementById("timeout-overlay");
  if (!el) return;
  el.classList.add("hidden");
  el.setAttribute("aria-hidden", "true");
}

function openTimeoutModal() {
  const el = document.getElementById("timeout-overlay");
  if (!el) {
    toast("Timeout picker missing — hard-refresh the page (Ctrl+F5).", true);
    return;
  }
  el.classList.remove("hidden");
  el.setAttribute("aria-hidden", "false");
}

async function applyTimeout(team) {
  closeTimeoutModal();
  const r = await fetch("/api/meta", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "timeout", team }),
  });
  const data = await r.json();
  if (!r.ok) {
    toast(data.error || "Timeout failed", true);
    return;
  }
  if (data.halftime_prompt) {
    window.alert("Halftime — first half over.");
  }
  if (data.ui) {
    uiData = data.ui;
    render();
  }
  toast(data.effects_summary || "Timeout", false);
}

document.getElementById("modal-cancel").addEventListener("click", closeBoard);

(() => {
  const cancel = document.getElementById("coin-modal-cancel");
  if (cancel) cancel.addEventListener("click", closeCoinOverlay);
})();

(() => {
  const cancel = document.getElementById("timeout-pick-cancel");
  const red = document.getElementById("timeout-pick-red");
  const green = document.getElementById("timeout-pick-green");
  if (cancel && red && green) {
    cancel.addEventListener("click", closeTimeoutModal);
    red.addEventListener("click", () => applyTimeout("red"));
    green.addEventListener("click", () => applyTimeout("green"));
  }
})();

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  const coin = document.getElementById("coin-overlay");
  if (coin && !coin.classList.contains("hidden")) {
    e.preventDefault();
    closeCoinOverlay();
    return;
  }
  const dartModal = document.getElementById("modal-overlay");
  if (dartModal && !dartModal.classList.contains("hidden")) {
    e.preventDefault();
    closeBoard();
    return;
  }
  const to = document.getElementById("timeout-overlay");
  if (to && !to.classList.contains("hidden")) {
    e.preventDefault();
    closeTimeoutModal();
  }
});

fetchState().catch((e) => toast(String(e), true));
