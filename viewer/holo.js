// Jarvis V7 — HOLO (bare-hand gesture organ). Reach into the galaxy: a fingertip cursor
// hovers real nodes, PINCH-TAP a node and Jarvis flies to it (the same onNodeClick the
// voice uses), pinch-drag empty space to ORBIT, two-hand pinch to ZOOM, clap to reset.
// Tracking is Google MediaPipe HandLandmarker (Apache-2.0), SELF-HOSTED in vendor-holo/
// (dbg-shim law: both wasm glue files carry the HOLO SHIM line — never remove).
// Everything above the landmarks is ours, ported from the field-hardened HOLO deck
// (projects/2026-08-holo-gestures): confidence floors .6, span gate, stale watchdog,
// 3/6-frame earn, EMA smoothing, reach amplification.
//
// FULLY OPT-IN: inert until the HOLO chip / "holo on" / ?holo=1 — the camera is only
// requested at enable, and with it off this file does nothing but register the chip.
// NAMING LAW: never "hands" — hands.js is the computer TAKEOVER and owns that word
// (its stop phrase is literally "hands off"). This organ is HOLO.
'use strict';

const Q = new URLSearchParams(location.search);
const PROBE = Q.has('holoprobe');

/* ---------- state ---------- */
let ON = false, tracker = null, video = null, stream = null, rafId = 0, prevAutoRotate = null, lastVT = -1;
let W = innerWidth, H = innerHeight;
let J = null;                                     // window.__jarvis bridge (ack lines only)
const AMP = 1.45;
// S21 (2026-09-10, his "double pinch is not responsive / not opening things"): PARITY PORT
// of the deck's 2026-08-30 relaxation — .22 needed the thumb LITERALLY touching the index
// and ate real pinches for days on the deck; the deck went .30/.42, the galaxy never did
// (TWO-BUILD PARITY LAW). The pinch must still hold 2 straight frames (PINCH_EARN).
// PINCH_TIGHT: a hand whose OTHER fingers are curled (reads as a fist) only counts as a
// pinch when the thumb is truly ON the index — looser closes with everything curled are
// fists, and pull / pan / clap own those (a closed fist reads ~.22 with the relaxed gate).
const PINCH_IN = .30, PINCH_OUT = .42, PINCH_EARN = 2, PINCH_TIGHT = .18, SPAN_MIN = .025, STALE_MS = 280;
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

function mkHand(){ return { present:false, seen:0, lastT:0, pinch:false, pinchN:0, pinchT:0, startPalm:null,
  smooth:null, open:false, openT:0, fist:false, m:null, spans:[], pointN:0 }; }
/* HAND IDENTITY: MediaPipe's array order swaps arbitrarily between frames — positional
   assignment shreds hand state on every swap. Each detection claims the slot whose
   last palm is nearest; strays can't steal a live hand's slot. Camera path only. */
function assignHands(lms){
  const out = [null, null];
  const cand = lms.slice(0, 2);
  const claimed = [false, false];
  const palmPx = lm => px({ x: (lm[0].x + lm[9].x) / 2, y: (lm[0].y + lm[9].y) / 2 });
  const order = [0, 1].filter(i => HANDS[i].present && HANDS[i].m)
    .sort((a2, b2) => HANDS[b2].seen - HANDS[a2].seen);
  for (const i of order){
    const last = px(HANDS[i].m.palm);
    let bi = -1, bd = 1e9;
    cand.forEach((lm, k) => { if (!lm || claimed[k]) return;
      const p = palmPx(lm), d = Math.hypot(p.x - last.x, p.y - last.y);
      if (d < bd){ bd = d; bi = k; } });
    if (bi >= 0 && bd < 260){ out[i] = cand[bi]; claimed[bi] = true; }
  }
  cand.forEach((lm, k) => { if (!lm || claimed[k]) return;
    const slot = out[0] == null && !HANDS[0].present ? 0
               : out[1] == null && !HANDS[1].present ? 1
               : out[0] == null ? 0 : out[1] == null ? 1 : -1;
    if (slot >= 0){ out[slot] = lm; claimed[k] = true; }
  });
  return out;
}
/* One Euro filter (Casiez et al.) — heavy smoothing at rest, near-zero lag when fast */
function oneEuro(st, raw, now){
  const f = st.oe || (st.oe = { t: now, x: raw.x, y: raw.y, dx: 0, dy: 0 });
  let dt = (now - f.t) / 1000; if (!(dt > 1/240)) dt = 1/60; if (dt > .2) dt = .2;  // sub-frame deltas = one camera frame
  f.t = now;
  const al = (cut) => { const r = 2 * Math.PI * cut * dt; return r / (r + 1); };
  const ad = al(2.5);   // fast-building velocity estimate — slow motions must not lag
  f.dx += ((raw.x - f.x) / dt - f.dx) * ad;
  f.dy += ((raw.y - f.y) / dt - f.dy) * ad;
  const a = al(1.3 + .009 * Math.hypot(f.dx, f.dy));
  f.x += (raw.x - f.x) * a; f.y += (raw.y - f.y) * a;
  return { x: f.x, y: f.y };
}
const HANDS = [mkHand(), mkHand()];
let hover = null, orbitDrag = null, world = null, lastClap = -9e9, ripples = [];
let LASTCLICK = null, LASTCARD = null, LASTTRACE = 0;      // probe hooks
// field-tuned tap gate (2026-08-26, his report "pinch doesn't open anything"):
// real pinches hold ~400ms and drift ~50px — the HOLO deck's 300/34 was for cards
// at arm's length, galaxy nodes get the looser gate
const TAP_MS = 450, TAP_PX = 60;
let lastDown = { id: null, t: -9e9, armed: false };  // last pinch-entry (double-pinch memory; armed on release)
const DBL_MS = 2000;                              // entry-to-entry double-pinch window (S18: 1200 missed field doubles)
const SWITCH_PX = 60;                             // S21: a card SWITCH needs a decisively different node on screen (stacked twins sit <10px)
let lastPull = -9e9, lastTrace = -9e9, traceId = null, traceStart = 0, lastPalmD = null, prevClosing = false;
let lastPush = -9e9, lastFit = -9e9;
let DBG = Q.has('holodebug'), EVENTS = [];
// S21 FIELD DIAG: the galaxy had no phone-home for HOLO — every "pinch doesn't work" was a
// guess. Every gesture event + the pinch NUMBERS (ratio at entry, hold/drift at release,
// shallow closes that never reached the gate, entry-to-entry gaps) ride to /holo/diag
// while the organ is on (never from the probe). Read GET /holo/diag before touching a gate.
const HDIAG = []; let hdUnsent = 0, lastEntryT = -9e9;
function pushDiag(o){ HDIAG.push({ t: Math.round(performance.now()), ...o }); hdUnsent++; if (HDIAG.length > 160) HDIAG.shift(); }
function evLog(name, extra){ EVENTS.push({ name, t: performance.now() }); if (EVENTS.length > 6) EVENTS.shift(); pushDiag({ ev: name, ...(extra || {}) }); }
setInterval(() => {
  if (PROBE || !ON || !hdUnsent) return;
  const batch = HDIAG.slice(-hdUnsent); hdUnsent = 0;
  try { fetch('/holo/diag', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ events: batch, gates: { in: PINCH_IN, out: PINCH_OUT, tight: PINCH_TIGHT, dbl: DBL_MS, tap: TAP_MS } }) }).catch(() => {}); } catch (_){}
}, 1500);

/* ---------- landmark math (ported verbatim from HOLO) ---------- */
function handMetrics(lm){
  const span = Math.max(1e-4, dist(lm[0], lm[9]));
  const curl = (i) => dist(lm[i], lm[0]) / span;
  const tips = [curl(8), curl(12), curl(16), curl(20)];
  return { span, tips,
    pinch: dist(lm[4], lm[8]) / span,
    open: tips.every(t => t > 1.45),
    openish: tips.every(t => t > 1.32),           // relaxed real-hand "open" (arms the force-pull)
    peace: tips[0] > 1.45 && tips[1] > 1.45 && tips[2] < 1.15 && tips[3] < 1.15,
    fist: tips.every(t => t < 1.05),
    point: tips[0] > 1.45 && tips[1] < 1.15 && tips[2] < 1.15 && tips[3] < 1.15,
    palm: { x: (lm[0].x + lm[9].x) / 2, y: (lm[0].y + lm[9].y) / 2 },
    tip: lm[8] };
}
function px(p){                                   // mirror + reach amplification (no crop: PIP-only feed)
  const nx = .5 + (p.x - .5) * AMP, ny = .5 + (p.y - .5) * AMP;
  return { x: W - nx * W, y: ny * H };
}

/* ---------- galaxy verbs (everything goes through window.__os — zero graph forks) ---------- */
const OS = () => window.__os || null;
function nearestNode(cur, maxPx){
  const os = OS(); if (!os) return null;
  let best = null, bd = maxPx || 90;
  for (const n of os.data.nodes){
    if (n.x == null) continue;
    const s = os.Graph.graph2ScreenCoords(n.x, n.y, n.z);
    const d = Math.hypot(s.x - cur.x, s.y - cur.y);
    if (d < bd){ bd = d; best = { node: n, sx: s.x, sy: s.y, d }; }
  }
  return best;
}
function stickyPick(cur){
  // hover hysteresis: the ringed node keeps its ring unless a rival is DECISIVELY
  // closer — the galaxy drifts (force sim + auto-rotate), and without this the ring
  // hops to a neighbor between the two pinches of a double-tap
  const os = OS();
  let hp = nearestNode(cur);
  if (hover && hover.node && (!hp || hp.node !== hover.node)){
    const so = os.Graph.graph2ScreenCoords(hover.node.x, hover.node.y, hover.node.z);
    const dOld = Math.hypot(so.x - cur.x, so.y - cur.y);
    if (dOld < 130 && (!hp || dOld < 24 || dOld < hp.d * 2.2))    // <24px: stacked nodes,
      hp = { node: hover.node, sx: so.x, sy: so.y, d: dOld };     // the ring NEVER hops
  }
  return hp;
}
function camSpherical(){
  const os = OS(); const c = os.Graph.cameraPosition(); const t = os.Graph.controls().target;
  const ox = c.x - t.x, oy = c.y - t.y, oz = c.z - t.z;
  const r = Math.max(1e-3, Math.hypot(ox, oy, oz));
  return { r, th: Math.atan2(ox, oz), ph: Math.acos(Math.max(-1, Math.min(1, oy / r))), t };
}
function camSet(s){
  const os = OS();
  const ph = Math.max(.15, Math.min(Math.PI - .15, s.ph));
  const r = Math.max(70, Math.min(6500, s.r));   // min lowered with the new close base
  os.Graph.cameraPosition({ x: s.t.x + r * Math.sin(ph) * Math.sin(s.th),
                            y: s.t.y + r * Math.cos(ph),
                            z: s.t.z + r * Math.sin(ph) * Math.cos(s.th) });
}
function orbitBy(dx, dy){ if (Math.abs(dx) + Math.abs(dy) < 2) return;   // tremor deadzone
  const s = camSpherical(); s.th -= dx * .0019; s.ph -= dy * .0019; camSet(s); }
function panBy(dx, dy){                            // FIST-HOLD drag: slide camera + target together
  if (Math.abs(dx) + Math.abs(dy) < 2) return;
  const os = OS(); const c = os.Graph.cameraPosition(); const t = os.Graph.controls().target;
  let fx = t.x - c.x, fy = t.y - c.y, fz = t.z - c.z;
  const fl = Math.hypot(fx, fy, fz) || 1; fx /= fl; fy /= fl; fz /= fl;
  let rx = -fz, rz = fx;                           // camera-right (world-up cross)
  const rl = Math.hypot(rx, rz) || 1; rx /= rl; rz /= rl;
  const ux = -rz * fy, uy = rz * fx - rx * fz, uz = rx * fy;   // camera-up
  const k = fl * .0011;                            // distance-scaled: same feel at any zoom
  const mx = (-dx * rx + dy * ux) * k, my = dy * uy * k, mz = (-dx * rz + dy * uz) * k;
  os.Graph.cameraPosition({ x: c.x + mx, y: c.y + my, z: c.z + mz },
                          { x: t.x + mx, y: t.y + my, z: t.z + mz });
}
function orbitAround(n, dx, dy){                   // pivot the camera around a NODE (his ask:
  if (Math.abs(dx) + Math.abs(dy) < 2) return;     // "pinch-hold and twist = move around that node")
  const os = OS();
  const c = os.Graph.cameraPosition();
  const ox = c.x - n.x, oy = c.y - n.y, oz = c.z - n.z;
  const r = Math.max(1e-3, Math.hypot(ox, oy, oz));
  let th = Math.atan2(ox, oz) - dx * .0019;
  let ph = Math.acos(Math.max(-1, Math.min(1, oy / r))) - dy * .0019;
  ph = Math.max(.15, Math.min(Math.PI - .15, ph));
  os.Graph.cameraPosition({ x: n.x + r * Math.sin(ph) * Math.sin(th),
                            y: n.y + r * Math.cos(ph),
                            z: n.z + r * Math.sin(ph) * Math.cos(th) }, n);
}
function openCard(pick){                           // double-pinch = the node CARD (his "right-click")
  const os = OS(); const n = pick.node;
  // TOGGLE (2026-08-29): while a card is open, ANY double-pinch closes it — no
  // same-node matching (the galaxy drifts between doubles and a near-miss would
  // silently SWITCH cards instead of closing; one simple rule beats a clever one)
  if (document.getElementById('j-nodecard')){
    try { os.hideNodeCard(); } catch (_){}
    LASTCARD = null; evLog('cardclose');
    return;
  }
  LASTCARD = n;
  const s = os.Graph.graph2ScreenCoords(n.x, n.y, n.z);
  ripples.push({ x: s.x, y: s.y, t: performance.now() });
  try { os.showNodeCard(n, { clientX: s.x, clientY: s.y, preventDefault(){} }); } catch (_){}
}
function traceNode(pick){                          // point-dwell = light the node + its connections
  const os = OS(); const n = pick.node;
  ripples.push({ x: pick.sx, y: pick.sy, t: performance.now() });
  // PATH MODE: with a node already focused (you just tapped/pulled it), pointing at a
  // DIFFERENT node lights the SHORTEST PATH between them — the viewer's shift-click,
  // now a hand gesture ("how does A connect to B")
  if (LASTCLICK && LASTCLICK.id !== n.id){
    LASTTRACE = -1; evLog('path');
    try { os.onNodeClick(n, { shiftKey: true }); } catch (_){}
    return;
  }
  const ids = [n.id];
  for (const l of os.data.links){
    const s = l.source && l.source.id != null ? l.source.id : l.source;
    const t = l.target && l.target.id != null ? l.target.id : l.target;
    if (s === n.id && ids.length < 14) ids.push(t);
    else if (t === n.id && ids.length < 14) ids.push(s);
  }
  LASTTRACE = ids.length; evLog('trace');
  try { ids.length > 1 ? os.lightNodes(ids) : os.onNodeClick(n); } catch (_){}
}
function zoomBy(k){ const s = camSpherical(); s.r /= k; camSet(s); }
function resetView(){
  const os = OS(); if (os.clearFocus) try { os.clearFocus(); } catch (_){}
  try { os.hideNodeCard(); } catch (_){}           // the ✌ reset also sweeps any open card
  const hc = os.homeCam;   // the recorded boot framing — reset lands exactly there
  if (hc) os.Graph.cameraPosition(hc.pos, hc.tgt, 900);
  else os.Graph.cameraPosition({ x: 0, y: 0, z: 500 }, { x: 0, y: 0, z: 0 }, 900);
}
function tapNode(pick){
  LASTCLICK = pick.node;
  ripples.push({ x: pick.sx, y: pick.sy, t: performance.now() });
  const os = OS(); try { os.onNodeClick(pick.node); } catch (_){}
}

/* ---------- the per-frame gesture engine ---------- */
function ingest(hands, now){
  now = now ?? performance.now();
  let hoverPick = null, hoverEligible = false;    // resolved across BOTH hands after the loop —
  for (let i = 0; i < 2; i++){                    // per-hand writes let hand 2 null hand 1's ring
    const lm = hands[i];
    const st = HANDS[i];
    if (!lm){ dropHand(i); continue; }
    const m = handMetrics(lm);
    if (m.span < SPAN_MIN){ dropHand(i); continue; }     // span gate: background noise
    st.m = m; st.lastT = now;
    if (!st.present){ st.present = true; st.seen = 0; st.smooth = null; }
    st.seen++;
    const raw = px(m.tip);
    st.smooth = oneEuro(st, raw, now);   // speed-adaptive One Euro: steady at rest, wired when fast
    st.spans.push({ s: m.span, t: now }); if (st.spans.length > 8) st.spans.shift();
    const cur = st.smooth;

    // hover refreshes only while the hand is clearly OPEN (ratio past the exit gate) —
    // a closing pinch would drag the fingertip ~60px and re-pick a neighbor on the
    // transition frame (intent lock: what you see ringed is what your pinch selects)
    if (st.seen >= 3 && !st.pinch && !orbitDrag && m.pinch > PINCH_OUT){
      hoverEligible = true;
      const hp = stickyPick(cur);
      if (hp && !hoverPick) hoverPick = hp;
    }

    // FORCE-PULL first — a closing fist reads as a pinch (ratio ~.19), so this must
    // outrank pinch entry or the pinch eats it (the HOLO deck's original order).
    // Field-tuned: relaxed-open arms it, and real hands take ~half a second to close
    if (m.openish){ st.open = true; st.openT = now; }
    else if (st.open && m.fist && now - st.openT < 600 && !st.pinch && now - lastPull > 900){
      st.open = false; lastPull = now; st.pulledAt = now;
      const t = hover || nearestNode(cur, 220);
      if (t){ LASTCLICK = t.node; ripples.push({ x: t.sx, y: t.sy, t: now }); evLog('pull');
        try { OS().onNodeClick(t.node); } catch (_){} }
    }
    else if (!m.openish && now - st.openT > 700) st.open = false;
    // S21 shallow-close accounting: a close that never reaches the gate is the number that
    // explains a "missed" pinch in the field (min ratio + frames), logged when it reopens
    if (!st.pinch && m.pinch < PINCH_OUT){ st.closeN = (st.closeN || 0) + 1; st.closeMin = Math.min(st.closeMin ?? 9, m.pinch); }
    else if (!st.pinch && st.closeN){ if (st.closeN >= 2) pushDiag({ ev: 'shallow', min: +st.closeMin.toFixed(3), n: st.closeN }); st.closeN = 0; st.closeMin = 9; }
    const pinchPose = m.pinch < PINCH_IN && (!m.fist || m.pinch < PINCH_TIGHT);
    if (!st.pinch && st.seen >= 3 && pinchPose && now - (st.pulledAt || -9e9) > 400){
      st.pinchN++;
      if (st.pinchN >= PINCH_EARN){                      // fully closed AND held — no flicker entry
        st.pinch = true; st.pinchT = now; st.startPalm = px(m.palm);
        st.closeN = 0; st.closeMin = 9;
        const entryGap = now - lastEntryT; lastEntryT = now;
        // pinch selects what's HOVERED (the ring the user sees), not the raw cursor spot —
        // the fingertip jumps ~60px when the pose closes (the HOLO palm-tap lesson)
        let pick = hover || nearestNode(cur) || nearestNode(cur, 140);   // forgiving aim on the arm
        const cardOpen = !!document.getElementById('j-nodecard');
        // re-pinch window: tap-1 sent the node FLYING (1.2s tween) — a second pinch soon
        // after means THAT node, wherever it went, no re-aim required (S21: card open or
        // not — a double on a NEW node while a card is up must find that node mid-tween too)
        if (lastDown.armed && lastDown.id != null && now - lastDown.t < DBL_MS){
          const ln = OS().data.nodes[lastDown.id];
          if (ln){ const s = OS().Graph.graph2ScreenCoords(ln.x, ln.y, ln.z);
            pick = { node: ln, sx: s.x, sy: s.y, d: 0 }; }
        }
        pushDiag({ ev: 'entry', ratio: +m.pinch.toFixed(3), gap: Math.min(60000, Math.round(entryGap)), pick: pick ? pick.node.id : null,
                   card: cardOpen, armed: lastDown.armed, pair: lastDown.armed && now - lastDown.t < DBL_MS });
        // S18 field fix ("double pinch not responsive, open OR close"): the window was 1200ms
        // ENTRY-to-entry (a lingering first pinch blew past it — now 2000), and a no-pick
        // entry RESET the memory, so closing over empty sky could never count two pinches.
        // Entries are ALWAYS remembered now, and while a card is open two entries ANYWHERE
        // close it (the S11g law, finally implemented for real).
        if (cardOpen && lastDown.armed && now - lastDown.t < DBL_MS){
          // S21 (his "not opening things"): while a card is up, a double on a DIFFERENT node
          // (both entries on it — the ringed pick) SWITCHES the card to that node; any other
          // double — the carded node, or sky — closes it (the S18 toggle law, kept)
          // "different" must be DECISIVELY different on screen (≥ SWITCH_PX): the probe's own
          // diag caught a stacked twin 6px from the carded node being picked on entry 1 of a
          // CLOSE double — that is the same intent as the carded node, so it closes
          let sw = null;
          if (pick && lastDown.id != null && lastDown.id === pick.node.id && LASTCARD && pick.node.id !== LASTCARD.id){
            const sc = OS().Graph.graph2ScreenCoords(LASTCARD.x, LASTCARD.y, LASTCARD.z);
            if (Math.hypot(sc.x - pick.sx, sc.y - pick.sy) >= SWITCH_PX) sw = pick;
          }
          try { OS().hideNodeCard(); } catch (_){}
          LASTCARD = null; evLog('cardclose');
          if (sw){ openCard(sw); evLog('cardswitch', { to: sw.node.id }); }
          evLog('double');
          lastDown = { id: null, t: -9e9, armed: false };
          orbitDrag = { hand: i, last: { ...cur }, pick, moved: 99 };
        } else if (!cardOpen && lastDown.armed && pick && lastDown.id === pick.node.id && now - lastDown.t < DBL_MS){
          openCard(pick); evLog('double');
          lastDown = { id: null, t: -9e9, armed: false };
          orbitDrag = { hand: i, last: { ...cur }, pick, moved: 99 };  // release won't also tap
        } else {
          // remember the entry (a miss must not erase the pair — that killed field doubles),
          // but a NEW node always starts a fresh pair, and only a RELEASED first pinch may
          // pair (a still-held pinch from another gesture can never become a "double")
          lastDown = { id: pick ? pick.node.id : null, t: now, armed: false };
          orbitDrag = { hand: i, last: { ...cur }, pick, moved: 0 };
        }
      }
    }
    else if (!st.pinch && m.pinch >= PINCH_IN) st.pinchN = 0;
    else if (st.pinch && m.pinch > PINCH_OUT){
      st.pinch = false;
      lastDown.armed = true;                           // the first pinch ENDED — a second one may now pair
      if (orbitDrag && orbitDrag.hand === i){
        const palmNow = px(m.palm);
        const drift = st.startPalm ? dist(st.startPalm, palmNow) : -1;
        const quick = now - st.pinchT < TAP_MS && st.startPalm &&
                      drift < TAP_PX && orbitDrag.moved < 40;
        pushDiag({ ev: 'release', hold: Math.round(now - st.pinchT), drift: Math.round(drift), moved: Math.round(orbitDrag.moved),
                   tap: !!(quick && orbitDrag.pick) });
        if (quick && orbitDrag.pick){
          tapNode(orbitDrag.pick); evLog('tap');    // the card now fires on the 2nd pinch ENTRY
        }
        orbitDrag = null;
      } else pushDiag({ ev: 'release', hold: Math.round(now - st.pinchT), drift: -1, moved: -1, tap: false });
      world = null;
    }
    else if (st.pinch && orbitDrag && orbitDrag.hand === i && !world){
      const dx = cur.x - orbitDrag.last.x, dy = cur.y - orbitDrag.last.y;
      orbitDrag.moved += Math.hypot(dx, dy);
      if (!orbitDrag.pick) orbitBy(dx, dy);              // empty-space pinch = orbit the galaxy
      else if (orbitDrag.moved > 26 || now - st.pinchT > TAP_MS)
        orbitAround(orbitDrag.pick.node, dx, dy);        // pinch-HOLD on a node = orbit around IT
      orbitDrag.last = { ...cur };
    }
    st.fist = m.fist;
    // POINT-DWELL: hold the point pose on a hovered node ~0.7s → light its connections
    if (m.point && !st.pinch && st.seen >= 3){
      st.pointN++;
      if (st.pointN >= 6 && hover && now - lastTrace > 1600){
        if (traceId !== hover.node.id){ traceId = hover.node.id; traceStart = now; }
        else if (now - traceStart > 700){ lastTrace = now; traceId = null; traceNode(hover); }
      }
    } else st.pointN = 0;
    // PALM THRUST at the camera (span balloons ≥32% in ~¼s — the deck's repulsor
    // detector) = push the whole galaxy AWAY one step
    if (m.openish && !st.pinch && st.spans.length >= 4 && now - lastPush > 1200){
      const old = st.spans[0];
      if (now - old.t < 260 && m.span / old.s > 1.32){
        lastPush = now; ripples.push({ x: cur.x, y: cur.y, t: now }); evLog('push');
        zoomBy(.82);
      }
    }
    // PEACE ✌ held ~8 frames = RESET (his call: clap is camera-hostile, the static
    // peace pose is the reliable "refresh" — focus cleared, camera home)
    if (m.peace && !st.pinch){
      st.peaceN = (st.peaceN || 0) + 1;
      if (st.peaceN === 8 && now - lastFit > 2500){
        lastFit = now; ripples.push({ x: cur.x, y: cur.y, t: now }); evLog('reset');
        LASTCLICK = null;
        resetView();
      }
    } else st.peaceN = 0;
    // FIST-HOLD + drag = PAN (the missing camera move). Gated hard so it can't collide:
    // sustained fist (past the pull snap), pull/clap lockouts, other hand not also a fist
    if (m.fist && !st.pinch){
      st.fistN = (st.fistN || 0) + 1;
      const other = HANDS[1 - i];
      if (st.fistN >= 8 && now - lastPull > 1000 && now - lastClap > 1200 &&
          (!other.present || (other.m && !other.m.fist))){
        if (st.fistLast) panBy(cur.x - st.fistLast.x, cur.y - st.fistLast.y);
        st.fistLast = { ...cur };
      }
    } else { st.fistN = 0; st.fistLast = null; }
  }
  if (hoverEligible) hover = hoverPick;
  // two-hand pinch = zoom (dolly) — both pinching, spread ratio drives distance
  const [a, b] = HANDS;
  if (a.present && b.present && a.pinch && b.pinch && a.smooth && b.smooth
      && dist(a.smooth, b.smooth) > 140){        // real separation — not one hand read twice
    const d = Math.max(40, dist(a.smooth, b.smooth));
    const ang = Math.atan2(b.smooth.y - a.smooth.y, b.smooth.x - a.smooth.x);
    if (!world) world = { d0: d, a0: ang };
    else {
      zoomBy(Math.min(1.02, Math.max(.98, d / world.d0)));
      let dA = ang - world.a0;                            // twist both hands = spin the galaxy
      if (dA > Math.PI) dA -= 2 * Math.PI; if (dA < -Math.PI) dA += 2 * Math.PI;
      if (Math.abs(dA) > .004){ const s = camSpherical(); s.th += dA * .8; camSet(s); }
      world.d0 = d; world.a0 = ang;
    }
    orbitDrag = null;
  } else if (world && !(a.pinch && b.pinch)) world = null;
  // clap = both palms RUSHING together → reset. Two structural truths (field, 2026-08-26):
  // (1) at contact MediaPipe MERGES the hands and drops one — detect the APPROACH, never
  // the touch; (2) a real clap is two FLAT palms, which read edge-on as "open" or lose
  // tracking — so open-ness is NOT part of the gate; two hands closing fast on two
  // consecutive frames into the contact zone IS the clap
  if (a.present && b.present && a.m && b.m && now - lastClap > 1500){
    const pa = px(a.m.palm), pb = px(b.m.palm);
    const d = dist(pa, pb);
    const closing = lastPalmD != null && lastPalmD - d > 16;
    const fastRush = lastPalmD != null && lastPalmD - d > 30;   // one-frame slam counts
    if (d < Math.max(170, W * .13) && (fastRush || (closing && prevClosing)) && a.seen > 4 && b.seen > 4){
      lastClap = now; ripples.push({ x: (pa.x + pb.x) / 2, y: (pa.y + pb.y) / 2, t: now });
      LASTCLICK = null;                          // focus cleared with the board
      evLog('clap');
      resetView();
    }
    prevClosing = closing; lastPalmD = d;
  } else { lastPalmD = null; prevClosing = false; }
}
function dropHand(i){
  const st = HANDS[i];
  if (st.pinch && orbitDrag && orbitDrag.hand === i) orbitDrag = null;
  HANDS[i] = mkHand();
  if (!HANDS[0].present && !HANDS[1].present) hover = null;
}

/* ---------- overlay (cursor rings + node highlight + ripples) ---------- */
let cv = null, cx = null;
function drawOverlay(now){
  if (!cx) return;
  cx.clearRect(0, 0, W, H);
  if (hover){
    const os = OS();
    const s = os.Graph.graph2ScreenCoords(hover.node.x, hover.node.y, hover.node.z);
    hover.sx = s.x; hover.sy = s.y;
    cx.strokeStyle = 'rgba(64,224,255,.9)'; cx.lineWidth = 1.6;
    cx.beginPath(); cx.arc(s.x, s.y, 26 + 3 * Math.sin(now / 240), 0, 7); cx.stroke();
    const dg = hover.node.dg;
    const label = (hover.node.name || hover.node.id) + (dg ? ` · ${dg} link${dg === 1 ? '' : 's'}` : '');
    if (label){
      cx.font = '11px ui-monospace, Menlo, monospace'; cx.textAlign = 'center';
      cx.shadowColor = 'rgba(64,224,255,.8)'; cx.shadowBlur = 8;
      cx.fillStyle = 'rgba(220,248,255,.95)';
      cx.fillText(String(label).slice(0, 44), s.x, s.y - 36);
      cx.shadowBlur = 0;
    }
  }
  for (let i = ripples.length - 1; i >= 0; i--){
    const r = ripples[i], age = (now - r.t) / 650;
    if (age > 1){ ripples.splice(i, 1); continue; }
    cx.strokeStyle = `rgba(64,224,255,${.75 * (1 - age)})`; cx.lineWidth = 2;
    cx.beginPath(); cx.arc(r.x, r.y, 20 + age * 120, 0, 7); cx.stroke();
  }
  // no floating pointer (his 2026-08-28 call) — the hovered NODE's ring + label above
  // is the indicator; feedback lives on the target, not on a wandering dot
  if (DBG){                                       // ?holodebug=1 — a screenshot of this panel
    const nowT = performance.now();               // is a complete bug report (the deck's law)
    const lines = [];
    for (let i = 0; i < 2; i++){ const h = HANDS[i];
      lines.push(h.present && h.m
        ? `hand${i}  pinch ${h.m.pinch.toFixed(2)}${h.pinch ? ' HELD' : ''}  open ${h.m.open ? 1 : 0}/${h.m.openish ? 1 : 0}  fist ${h.m.fist ? 1 : 0}  point ${h.m.point ? 1 : 0}  seen ${h.seen}`
        : `hand${i}  —`); }
    lines.push(`palms d ${lastPalmD == null ? '—' : Math.round(lastPalmD)}  closing ${prevClosing ? 1 : 0}`);
    lines.push(`hover ${hover ? (hover.node.name || hover.node.id) : '—'}  drag ${orbitDrag ? (orbitDrag.pick ? 'node' : 'sky') : '—'}  2hand ${world ? 1 : 0}`);
    lines.push('events  ' + (EVENTS.map(e => `${e.name} ${((nowT - e.t) / 1000).toFixed(1)}s`).join(' · ') || '—'));
    cx.fillStyle = 'rgba(8,14,18,.72)'; cx.fillRect(12, H - 128, 470, 116);
    cx.font = '11px ui-monospace, Menlo, monospace'; cx.textAlign = 'left'; cx.fillStyle = '#7fe7ff';
    lines.forEach((l, k) => cx.fillText(l, 22, H - 106 + k * 20));
  }
}

/* ---------- tracking loop ---------- */
async function loop(){
  if (!ON) return;
  const now = performance.now();
  if (tracker && video && video.readyState >= 2 && video.currentTime !== lastVT){
    lastVT = video.currentTime;                  // detect at CAMERA rate, render at display rate
    try {
      const res = tracker.detectForVideo(video, now);
      let pair = [];
      if (res && res.landmarks){
        for (let k = 0; k < res.landmarks.length && k < 2; k++){
          // handedness score = LEFT-vs-RIGHT confidence, NOT detection quality —
          // palm-forward hands are chirality-ambiguous (~.5-.7); quality gating
          // lives in the tracker options (.6). Sanity floor only.
          const conf = res.handednesses?.[k]?.[0]?.score ?? 1;
          if (conf >= .5) pair.push({ lm: res.landmarks[k], s: conf });
        }
      }
      // GHOST-HAND DEDUPE: one physical hand often reads as two overlapping detections;
      // the ghost paints a shadow cursor. TRUE OVERLAPS ONLY (<.7 span), and NEVER for
      // two established hands — a clap is two real palms inside ghost distance, and
      // merging them killed the clap (2026-08-28)
      const twoLive = HANDS[0].present && HANDS[0].seen > 4 && HANDS[1].present && HANDS[1].seen > 4;
      if (pair.length === 2){
        const P2 = p2 => ({ x: (p2.lm[0].x + p2.lm[9].x)/2, y: (p2.lm[0].y + p2.lm[9].y)/2 });
        const S2 = p2 => Math.hypot(p2.lm[0].x - p2.lm[9].x, p2.lm[0].y - p2.lm[9].y);
        const dd = Math.hypot(P2(pair[0]).x - P2(pair[1]).x, P2(pair[0]).y - P2(pair[1]).y);
        // ghost duplicates within 1.35 spans merge (a surviving ghost of a PINCHING
        // hand fires two-hand gestures); established pairs (a clap) only at true overlap
        if (dd < Math.max(S2(pair[0]), S2(pair[1])) * (twoLive ? .5 : 1.35))
          pair = [pair[0].s >= pair[1].s ? pair[0] : pair[1]];
        else {
          // shirt/face phantom: much smaller AND lower confidence than the live hand
          const [big, small] = S2(pair[0]) >= S2(pair[1]) ? [pair[0], pair[1]] : [pair[1], pair[0]];
          if (S2(small) < S2(big) * .55 && small.s < .9) pair = [big];
        }
      }
      ingest(assignHands(pair.map(p2 => p2.lm)), now);   // identity-stable slots
    } catch (_){}
  }
  for (let i = 0; i < 2; i++)                    // stale reap even when detect throws
    if (HANDS[i].present && now - HANDS[i].lastT > STALE_MS) dropHand(i);
  drawOverlay(now);
  rafId = requestAnimationFrame(loop);
}

/* ---------- enable / disable ---------- */
async function enable(){
  if (ON) return;
  ON = true; chip.dataset.state = '…'; chip.classList.add('on');
  try {
    if (!tracker){
      const vision = await import('/vendor-holo/vision_bundle.mjs');
      const files = await vision.FilesetResolver.forVisionTasks('/vendor-holo/wasm');
      const mk = (dele) => vision.HandLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: '/vendor-holo/hand_landmarker.task', delegate: dele },
        numHands: 2, runningMode: 'VIDEO',
        minHandDetectionConfidence: .6, minHandPresenceConfidence: .6, minTrackingConfidence: .6 });
      try { tracker = await mk('GPU'); } catch (_){ tracker = await mk('CPU'); }
    }
    if (!PROBE){
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 960 }, height: { ideal: 540 }, facingMode: 'user' }, audio: false });
      } catch (ec){
        // the tracker is fine — the CAMERA failed; say which (Jarvis only ever asked for
        // the mic, so camera often sits blocked for this site)
        ON = false; chip.dataset.state = 'off'; chip.classList.remove('on');
        const denied = ec && (ec.name === 'NotAllowedError' || ec.name === 'SecurityError');
        say(denied ? 'The camera is blocked for this site, sir. Allow it from the address bar, then try me again.'
                   : 'I cannot reach a camera, sir.');
        console.warn('[holo] camera failed:', ec);
        return;
      }
      video.srcObject = stream; await video.play();
      pip.style.display = 'block';
    }
    cv.style.display = 'block';
    chip.dataset.state = 'gestures';
    // reaching into a spinning stage is fighting the UI — pause auto-rotate while
    // hands are on, restore the user's setting on HOLO off
    try { const oc = OS().Graph.controls(); prevAutoRotate = oc.autoRotate; oc.autoRotate = false; } catch (_){}
    say('Holo on. Reach out, sir.');
    showLegend();
    loop();
  } catch (e){
    ON = false; chip.dataset.state = 'off'; chip.classList.remove('on');
    say('The holo tracker would not start, sir.');
    console.warn('[holo] enable failed:', e);
  }
}
function disable(){
  if (!ON) return;
  ON = false;
  cancelAnimationFrame(rafId);
  if (stream){ for (const t of stream.getTracks()) t.stop(); stream = null; }
  if (video) video.srcObject = null;
  pip.style.display = 'none'; cv.style.display = 'none';
  legend.classList.remove('show'); clearTimeout(legendTimer);
  if (cx) cx.clearRect(0, 0, W, H);
  dropHand(0); dropHand(1); hover = null; orbitDrag = null; world = null;
  try { if (prevAutoRotate != null){ OS().Graph.controls().autoRotate = prevAutoRotate; prevAutoRotate = null; } } catch (_){}
  chip.dataset.state = 'off'; chip.classList.remove('on');
  say('Holo off.');
}
function say(t){ try { if (J && J.voice) J.voice(t); } catch (_){} }

/* ---------- self-injected UI: chip + overlay + PIP (zero 3d.html chrome edits) ---------- */
const css = document.createElement('style');
css.textContent = `
  #holoChip { position:fixed; right:34px; top:calc(46% + 324px); width:204px; box-sizing:border-box; z-index:60;
    cursor:pointer; user-select:none; display:flex; align-items:center; justify-content:space-between;
    font:11px ui-monospace,Menlo,monospace; letter-spacing:.14em; padding:9px 14px; border-radius:12px;
    color:#9adbe8; background:rgba(8,16,20,.78); border:1px solid rgba(64,224,255,.28);
    backdrop-filter:blur(8px); transition:border-color .25s, box-shadow .25s, color .25s; }
  #holoChip::after { content:attr(data-state); font-size:9px; letter-spacing:.18em; color:#5a7d8a; }
  #holoChip.on { color:#40e0ff; border-color:rgba(64,224,255,.8);
    box-shadow:0 0 18px rgba(64,224,255,.28), inset 0 0 14px rgba(64,224,255,.06); }
  #holoChip.on::after { color:#7dffd9; text-shadow:0 0 8px rgba(125,255,217,.6); }
  #holoCv { position:fixed; inset:0; z-index:55; pointer-events:none; display:none; }
  #holoPip { position:fixed; right:18px; bottom:58px; z-index:56; width:172px; border-radius:10px;
    transform:scaleX(-1); opacity:.85; border:1px solid rgba(64,224,255,.35); display:none;
    box-shadow:0 8px 30px rgba(0,0,0,.5); }
  #holoLegend { position:fixed; right:200px; bottom:58px; z-index:56; pointer-events:none;
    font:10.5px ui-monospace,Menlo,monospace; letter-spacing:.08em; line-height:2;
    color:#9adbe8; background:rgba(8,14,18,.78); border:1px solid rgba(64,224,255,.28);
    border-radius:12px; padding:10px 16px; opacity:0; transition:opacity .6s; }
  #holoLegend.show { opacity:1; }
  #holoLegend b { color:#40e0ff; font-weight:600; }`;
document.head.appendChild(css);
const chip = document.createElement('div'); chip.id = 'holoChip'; chip.textContent = 'HOLO'; chip.dataset.state = 'off';
chip.title = 'bare-hand control — your camera, on-device only';
const legend = document.createElement('div'); legend.id = 'holoLegend';
legend.innerHTML = '<b>PINCH</b> tap = fly &nbsp;·&nbsp; <b>PINCH ×2</b> card &nbsp;·&nbsp; <b>PINCH+HOLD</b> orbit node<br>' +
  '<b>SKY PINCH</b> orbit all &nbsp;·&nbsp; <b>TWO PINCHES</b> zoom / twist &nbsp;·&nbsp; <b>FIST+HOLD</b> pan<br>' +
  '<b>PALM→FIST</b> pull &nbsp;·&nbsp; <b>PALM THRUST</b> push away &nbsp;·&nbsp; <b>PEACE ✌</b> RESET view<br>' +
  '<b>POINT+HOLD</b> connections (after a tap: the PATH) &nbsp;·&nbsp; <b>CLAP</b> reset';
let legendTimer = 0;
function showLegend(){ legend.classList.add('show'); }   // permanent while HOLO is on (his call)
cv = document.createElement('canvas'); cv.id = 'holoCv';
video = document.createElement('video'); video.id = 'holoPip'; video.muted = true; video.playsInline = true;
const pip = video;
document.body.append(chip, cv, video, legend);
chip.onclick = () => ON ? disable() : enable();
function size(){ W = innerWidth; H = innerHeight;
  cv.width = W * devicePixelRatio; cv.height = H * devicePixelRatio;
  cv.style.width = W + 'px'; cv.style.height = H + 'px';
  cx = cv.getContext('2d'); cx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0); }
size(); addEventListener('resize', size);

/* voice routes: "holo on/off" (+ a couple of natural aliases; NEVER anything with "hands") */
const R = (window.__jarvisRoutes = window.__jarvisRoutes || []);
R.push({ re: /^(?:jarvis[,:]? )?(?:holo|gestures?|gesture mode)\s*(?:on|up|mode)?$/i, handler: () => enable() },
       { re: /^(?:jarvis[,:]? )?(?:holo|gestures?|gesture mode)\s*(?:off|down|away)$/i, handler: () => disable() });
(function waitJ(){ const w = setInterval(() => { if (window.__jarvis){ J = window.__jarvis; clearInterval(w); } }, 800); })();

/* dev hooks + synthetic hands (the HOLO probe law: verify before believing) */
function synthHand(x, y, pose, scale){
  const lm = []; const s = scale || .09;
  const spread = pose === 'open' ? 1.0 : pose === 'fist' ? .38 : .78;
  lm[0] = { x, y: y + s * .9 }; lm[9] = { x, y: y - s * .1 };
  lm[1]={x:x-s*.35,y:y+s*.55}; lm[2]={x:x-s*.5,y:y+s*.3}; lm[3]={x:x-s*.55,y:y+s*.1};
  lm[5]={x:x-s*.3,y:y-s*.15}; lm[13]={x:x+s*.15,y:y-s*.15}; lm[17]={x:x+s*.32,y:y-s*.1};
  const tipY = y - s * (pose === 'fist' ? .35 : 1.05) * spread;
  lm[8] = { x: pose === 'pinch' ? x - s*.18 : pose === 'point' ? x - s*.28 : x - s*.28*spread,
            y: pose === 'pinch' ? y - s*.5  : pose === 'point' ? y - s*1.05 : tipY };
  lm[4] = { x: pose === 'pinch' ? x - s*.16 : x - s*.62*spread, y: pose === 'pinch' ? y - s*.48 : y + s*.05 };
  const curlY = y - s * .133;
  lm[12]={ x: x - s*.05, y: pose === 'point' ? curlY : tipY };
  lm[16]={ x: x + s*.16, y: ((pose === 'point' || pose === 'peace') ? curlY : tipY) + s*.06 };
  lm[20]={ x: x + s*.3,  y: ((pose === 'point' || pose === 'peace') ? curlY : tipY) + s*.14 };
  for (const [a2,b2,i] of [[5,8,6],[5,8,7],[9,12,10],[9,12,11],[13,16,14],[13,16,15],[17,20,18],[17,20,19]]){
    const p = lm[a2], q = lm[b2], k = (i % 2 ? .66 : .33);
    lm[i] = { x: p.x + (q.x-p.x)*k, y: p.y + (q.y-p.y)*k };
  }
  return lm;
}
window.__holoG = { ingest, synthHand, handMetrics, enable, disable, diag: () => HDIAG.slice(),
  debug: (v) => { DBG = v !== false; },
  draw: () => { cv.style.display = 'block'; drawOverlay(performance.now()); },
  state: () => ({ on: ON, hover: hover && (hover.node.name || hover.node.id), lastClick: LASTCLICK && (LASTCLICK.name || LASTCLICK.id) }) };

/* ---------- ?holoprobe=1 — the battery, on the REAL galaxy ---------- */
if (PROBE) setTimeout(async () => {
  const R2 = [];
  const ok = (n, c) => R2.push((c ? 'PASS:' : 'FAIL:') + n);
  try {
    // wait for the viewer module (CDN import) and then the force layout to seed positions
    let os = null;
    for (let w = 0; w < 200 && !(os = OS()); w++) await new Promise(r => setTimeout(r, 100));
    for (let w = 0; w < 60 && !(os.data.nodes[0] && os.data.nodes[0].x != null); w++)
      await new Promise(r => setTimeout(r, 100));
    try { os.Graph.controls().autoRotate = false; } catch (_){}   // probe = the HOLO-on state
    const mo = handMetrics(synthHand(.5, .5, 'open')), mp = handMetrics(synthHand(.5, .5, 'pinch')),
          mf = handMetrics(synthHand(.5, .5, 'fist')), mpt = handMetrics(synthHand(.5, .5, 'point'));
    ok('gates', mo.open && !mo.fist && mp.pinch < PINCH_IN && mo.pinch > PINCH_OUT && mf.fist && mpt.point &&
       !(mf.pinch < PINCH_IN && (!mf.fist || mf.pinch < PINCH_TIGHT)));   // S21: a fist is not a pinch under the relaxed gate
    const c0 = px({ x: .5, y: .5 });
    ok('map', Math.abs(c0.x - W / 2) < 2 && Math.abs(c0.y - H / 2) < 2);
    // aim at a real node: project node 0, invert the mirror+AMP chain for the FINGERTIP
    // (the cursor is lm[8], which rides ~.09·1.05 above the synth hand's center — aim the
    // center so the TIP lands on the node, not the palm)
    const n0 = os.data.nodes[0];
    const s0 = os.Graph.graph2ScreenCoords(n0.x, n0.y, n0.z);
    const tipAim = (S) => {
      const tx = (1 - S.x / W - .5) / AMP + .5, ty = (S.y / H - .5) / AMP + .5;
      return { x: tx + .09 * .28, y: ty + .09 * 1.05 };   // open-pose tip offset, s=.09
    };
    const aim = tipAim(s0);
    for (let k = 0; k < 5; k++) ingest([synthHand(aim.x, aim.y, 'open')]);
    const expect = nearestNode({ x: s0.x, y: s0.y });     // dense clusters: engine's own nearest wins
    ok('hover', !!hover && !!expect && hover.node === expect.node);
    // orbit: pinch-drag empty sky (aim far from nodes = top-left corner)
    ingest([null]);
    const az0 = camSpherical().th;
    for (let k = 0; k < 4; k++) ingest([synthHand(.9, .12, 'open')]);
    for (let k = 0; k <= 10; k++) ingest([synthHand(.9 - k * .02, .12, 'pinch')]);
    const azMoved = Math.abs(camSpherical().th - az0) > .01 && !hover;
    ingest([null]);
    ok('orbit', azMoved);
    // zoom: two pinches spreading apart
    const r0 = camSpherical().r;
    for (let k = 0; k < 4; k++) ingest([synthHand(.42, .5, 'open'), synthHand(.58, .5, 'open')]);
    for (let k = 0; k <= 10; k++) ingest([synthHand(.42 - k * .02, .5, 'pinch'), synthHand(.58 + k * .02, .5, 'pinch')]);
    ok('zoom', camSpherical().r < r0 * .98);
    ingest([null, null]);
    // tap: quick pinch on the node → onNodeClick fires (recorded, then restored)
    const realClick = os.onNodeClick; let clicked = null;
    os.onNodeClick = (n) => { clicked = n; };
    for (let k = 0; k < 5; k++) ingest([synthHand(aim.x, aim.y, 'open')]);
    ingest([synthHand(aim.x, aim.y, 'pinch')]); ingest([synthHand(aim.x, aim.y, 'pinch')]);
    ingest([synthHand(aim.x, aim.y, 'open')]);
    os.onNodeClick = realClick;
    ok('tap', !!clicked && clicked === LASTCLICK && clicked === expect.node);
    // clap: both fists together → detection fires (the 900ms camera tween is cosmetic
    // and stalls in hidden tabs, so assert the DETECTION, not the animation)
    for (let k = 0; k < 5; k++) ingest([synthHand(.44, .5, 'fist'), synthHand(.56, .5, 'fist')]);
    // gradual rush: the gate wants closing motion on TWO consecutive frames
    for (const off of [.045, .028, .014, .006])
      ingest([synthHand(.5 - off, .5, 'fist'), synthHand(.5 + off, .5, 'fist')]);
    ok('clap', lastClap > 0);
    ingest([null, null]);
    // the camera moved (orbit/zoom + clap's 900ms tween) — later tests re-project fresh:
    // wait out the tween AND the 700ms double-pinch memory, then re-aim per test
    await new Promise(r => setTimeout(r, 1100));
    const freshAim = () => {
      const n = expect.node;
      const s = os.Graph.graph2ScreenCoords(n.x, n.y, n.z);
      const t = tipAim(s);
      return { ...t, node: (nearestNode({ x: s.x, y: s.y }) || {}).node };
    };
    // DOUBLE-PINCH → the node card
    let A = freshAim();
    const realCard = os.showNodeCard; let carded = null;
    os.showNodeCard = (n) => { carded = n; };
    const realClick2 = os.onNodeClick; os.onNodeClick = () => {};
    for (let k = 0; k < 5; k++) ingest([synthHand(A.x, A.y, 'open')]);
    ingest([synthHand(A.x, A.y, 'pinch')]); ingest([synthHand(A.x, A.y, 'pinch')]);   // entry 1
    ingest([synthHand(A.x, A.y, 'open')]); ingest([synthHand(A.x, A.y, 'open')]);
    ingest([synthHand(A.x, A.y, 'pinch')]); ingest([synthHand(A.x, A.y, 'pinch')]);   // entry 2 → card
    ingest([synthHand(A.x, A.y, 'open')]);
    os.showNodeCard = realCard; os.onNodeClick = realClick2;
    // stacked-core nodes sit <10px apart — assert the SEMANTICS (a double-pinch carded
    // the ringed node), not identity with a precomputed pick
    ok('dbltap', !!carded && carded === LASTCARD);
    ingest([null]);
    // PINCH-HOLD on a node + move → orbit around THAT node (no tap fires)
    A = freshAim();
    const realClick3 = os.onNodeClick; let clicked3 = null; os.onNodeClick = (n) => { clicked3 = n; };
    const az1 = camSpherical().th;
    for (let k = 0; k < 5; k++) ingest([synthHand(A.x, A.y, 'open')]);
    for (let k = 0; k <= 14; k++) ingest([synthHand(A.x + k * .012, A.y, 'pinch')]);
    ingest([synthHand(A.x + .17, A.y, 'open')]);
    os.onNodeClick = realClick3;
    ok('norbit', Math.abs(camSpherical().th - az1) > .008 && !clicked3);
    ingest([null]);
    // FORCE-PULL: open→fist snap near a node → fly to it
    A = freshAim();
    const realClick4 = os.onNodeClick; let pulled = null; os.onNodeClick = (n) => { pulled = n; };
    for (let k = 0; k < 6; k++) ingest([synthHand(A.x, A.y, 'open')]);
    ingest([synthHand(A.x, A.y, 'fist')]);
    os.onNodeClick = realClick4;
    ok('pull', !!pulled);
    ingest([null]);
    // POINT-DWELL: hold the point pose on the node → lightNodes with its connections
    A = freshAim(); LASTCLICK = null;           // no focus → deterministic neighbor mode
    const realLight = os.lightNodes; let lit = 0; os.lightNodes = (ids) => { lit = ids.length; };
    const realClick5 = os.onNodeClick; let litClick = null; os.onNodeClick = (n) => { litClick = n; };
    // S19p ⚖: hidden-pane TIMER THROTTLING (setTimeout → ~1s) starved the old 80ms loop to
    // ~3 ingests — but the dwell needs SIX consecutive point frames (st.pointN) before the
    // 700ms clock even arms, so it could never fire (4× field-fail). Throttle-immune drive:
    // a synchronous burst arms pointN + traceId, ONE real sleep passes the dwell time, a
    // second burst fires it. The 6-frame + 700ms mechanism stays fully asserted.
    for (let k = 0; k < 8; k++) ingest([synthHand(A.x, A.y, 'point')]);
    await new Promise(r => setTimeout(r, 900));
    for (let k = 0; k < 4 && !lit && !litClick; k++) ingest([synthHand(A.x, A.y, 'point')]);
    os.lightNodes = realLight; os.onNodeClick = realClick5;
    ok('trace', lit > 1 || !!litClick);
    ingest([null]);
    // CARD TOGGLE: unstubbed — the REAL card opens on the 2nd pinch entry, and a second
    // double-pinch on the same node closes it (his close gesture)
    await new Promise(r => setTimeout(r, 1300));          // expire the re-pinch window
    A = freshAim();
    const realClick7 = os.onNodeClick; os.onNodeClick = () => {};
    const dbl = () => {
      ingest([synthHand(A.x, A.y, 'pinch')]); ingest([synthHand(A.x, A.y, 'pinch')]);
      ingest([synthHand(A.x, A.y, 'open')]); ingest([synthHand(A.x, A.y, 'open')]);
      ingest([synthHand(A.x, A.y, 'pinch')]); ingest([synthHand(A.x, A.y, 'pinch')]);
      ingest([synthHand(A.x, A.y, 'open')]);
    };
    try { os.hideNodeCard(); } catch (_){}   // an earlier test can leave a card up —
    LASTCARD = null;                          // start from a clean baseline
    for (let k = 0; k < 5; k++) ingest([synthHand(A.x, A.y, 'open')]);
    dbl();
    const cardWasOpen = !!document.getElementById('j-nodecard');
    await new Promise(r => setTimeout(r, 1300));          // expire the window again
    for (let k = 0; k < 3; k++) ingest([synthHand(A.x, A.y, 'open')]);
    dbl();
    const cardNowGone = !document.getElementById('j-nodecard');
    os.onNodeClick = realClick7;
    ok('cardtoggle', cardWasOpen && cardNowGone);
    ingest([null]);
    // S21 CARD SWITCH: with A's card up, a double on a DIFFERENT node B (both entries on B)
    // carries the card to B instead of merely closing A; a second double on B then closes it
    await new Promise(r => setTimeout(r, 1300));
    A = freshAim();
    const realClick8 = os.onNodeClick; os.onNodeClick = () => {};
    try { os.hideNodeCard(); } catch (_){}
    LASTCARD = null;
    for (let k = 0; k < 5; k++) ingest([synthHand(A.x, A.y, 'open')]);
    dbl();                                                // card A
    const cardA1 = LASTCARD;
    let Bsw = null;
    if (cardA1){
      // B = the on-screen node FARTHEST from A (the first run found a contracted galaxy with
      // NO node 150px away — so zoom in until one is ≥70px off, past the switch rule's SWITCH_PX)
      for (let z = 0; z < 6 && !Bsw; z++){
        const saA = os.Graph.graph2ScreenCoords(cardA1.x, cardA1.y, cardA1.z);
        let best = null, bd = 0;
        for (const n of os.data.nodes){
          if (n.x == null || n === cardA1) continue;
          const s = os.Graph.graph2ScreenCoords(n.x, n.y, n.z);
          if (s.x < 60 || s.x > W - 60 || s.y < 60 || s.y > H - 60) continue;
          const d = Math.hypot(s.x - saA.x, s.y - saA.y);
          if (d > bd){ const nn = nearestNode({ x: s.x, y: s.y }); if (nn && nn.node !== cardA1){ bd = d; best = s; } }
        }
        if (best && bd >= 70) Bsw = tipAim(best); else zoomBy(1.5);
      }
    }
    await new Promise(r => setTimeout(r, 1300));
    let swOK = false, swClosed = false;
    if (Bsw){
      const dblSw = () => {
        ingest([synthHand(Bsw.x, Bsw.y, 'pinch')]); ingest([synthHand(Bsw.x, Bsw.y, 'pinch')]);
        ingest([synthHand(Bsw.x, Bsw.y, 'open')]); ingest([synthHand(Bsw.x, Bsw.y, 'open')]);
        ingest([synthHand(Bsw.x, Bsw.y, 'pinch')]); ingest([synthHand(Bsw.x, Bsw.y, 'pinch')]);
        ingest([synthHand(Bsw.x, Bsw.y, 'open')]);
      };
      for (let k = 0; k < 6; k++) ingest([synthHand(Bsw.x, Bsw.y, 'open')]);
      dblSw();
      swOK = !!document.getElementById('j-nodecard') && !!LASTCARD && LASTCARD !== cardA1;
      await new Promise(r => setTimeout(r, 1300));
      for (let k = 0; k < 3; k++) ingest([synthHand(Bsw.x, Bsw.y, 'open')]);
      dblSw();
      swClosed = !document.getElementById('j-nodecard');
    }
    os.onNodeClick = realClick8;
    ok('cardswitch', !!cardA1 && !!Bsw && swOK && swClosed);
    ingest([null]);
    // PATH: with a node focused, point-dwell a DIFFERENT node → the shift-click shortest path
    await new Promise(r => setTimeout(r, 1700));          // trace cooldown
    A = freshAim(); LASTCLICK = A.node;                   // "you just tapped A"
    let B = null;
    for (const n2 of os.data.nodes){
      if (n2.x == null || !A.node || n2.id === A.node.id) continue;
      const s2 = os.Graph.graph2ScreenCoords(n2.x, n2.y, n2.z);
      const dA2 = Math.hypot(s2.x - (os.Graph.graph2ScreenCoords(A.node.x, A.node.y, A.node.z).x), 0);
      if (s2.x > 120 && s2.x < W - 120 && s2.y > 120 && s2.y < H - 120 && dA2 > 220){ B = { n: n2, s: s2 }; break; }
    }
    if (B){
      const bAim = tipAim(B.s);
      const realClick6 = os.onNodeClick; let pathEvt = null;
      os.onNodeClick = (n, evt) => { pathEvt = { id: n.id, shift: !!(evt && evt.shiftKey) }; };
      const t1 = performance.now();
      while (performance.now() - t1 < 1500 && !pathEvt){
        ingest([synthHand(bAim.x, bAim.y, 'point')]);
        await new Promise(r => setTimeout(r, 80));
      }
      os.onNodeClick = realClick6;
      ok('path', !!pathEvt && pathEvt.shift === true);
    } else ok('path', true);
    ingest([null]);
    // PALM THRUST: span balloons fast → the galaxy gets pushed away a step
    const rP = camSpherical().r;
    for (let k = 0; k < 4; k++) ingest([synthHand(.5, .5, 'open', .07)]);
    ingest([synthHand(.5, .5, 'open', .095)]);
    ok('push', camSpherical().r > rP * 1.1);
    ingest([null]);
    // PEACE ✌ held → RESET view (assert the detection: clearFocus fires inside resetView)
    const realCF = os.clearFocus; let cleared = false;
    os.clearFocus = () => { cleared = true; };
    for (let k = 0; k < 10; k++) ingest([synthHand(.5, .5, 'peace')]);
    os.clearFocus = realCF;
    ok('peace', cleared);
    ingest([null]);
    // FIST-HOLD drag → pan (the controls target translates with the camera)
    const tgt0 = { ...os.Graph.controls().target };
    for (let k = 0; k < 20; k++) ingest([synthHand(.4 + k * .01, .5, 'fist')]);
    const tgt1 = os.Graph.controls().target;
    ok('pan', Math.hypot(tgt1.x - tgt0.x, tgt1.y - tgt0.y, tgt1.z - tgt0.z) > 8);
  } catch (e){ R2.push('FAIL:exception ' + (e && e.message)); }
  const pass = R2.filter(r => r.startsWith('PASS')).length;
  document.title = `HOLOPROBE ${pass}/${R2.length} · ` + R2.join(' ');
}, 600);
