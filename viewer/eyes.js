// Jarvis V7 — EYES (the sight organ). Give Jarvis the camera and he can SEE you:
// greet you when you sit down, wait for eye contact before speaking up, catch drowsy
// blinks and slouching and phone-scrolling with a dry nudge, answer "what do you think
// of this shirt?" by actually looking, nod/shake your way through confirms, and put a
// living face on him (the FACE card + the WATCH desktop overlay).
// (INSIDE — the selfie-segmentation composite — was REMOVED 2026-08-29 at his request
// after two field passes; do not rebuild without an explicit ask.)
//
// Tracking: MediaPipe FaceLandmarker (478 pts + 52 expression blendshapes + head pose),
// Apache-2.0, SELF-HOSTED in vendor-holo/ — frames stay on this machine. The ONLY thing
// that ever leaves is a single frame to the Claude brain when YOU explicitly ask him to
// look ("look at me", "what do you think of this…"), riding the same /see endpoint as
// screen vision — or ONE frame when an armed SCREEN WATCH nudge fires.
//
// FULLY OPT-IN: inert until the EYES chip / "eyes on" / ?eyes=1. Speech rides
// window.__jarvis unmarked, so the takeover's DV gate mutes us during drives, as it
// should. NAMING LAW: hands = takeover, HOLO = gestures, EYES = sight.
'use strict';

const Q = new URLSearchParams(location.search);
const PROBE = Q.has('eyesprobe');

/* ---------- state ---------- */
let ON = false, faceLm = null;
let video = null, stream = null, rafId = 0, lastVT = -1, J = null;
const F = {                      // the analyzed face state, updated per camera frame
  present: false, lastSeen: -9e9, absentSince: 0,
  yaw: 0, pitch: 0, looking: false, lastLook: -9e9,
  blink: 0,                      // mean of eyeBlinkLeft/Right blendshapes
  faceH: 0,                      // face height as a fraction of frame (lean-in proxy)
  faces: 0,
};
const perclos = [];              // [{t, closed}] rolling eye-closure window
let baseH = null, baseN = 0;     // calibrated upright face-height baseline
let slouchSince = 0, phoneSince = 0, greetArmed = true;
let prevAvatar = null;           // S19p: EYES-on auto-swaps to the FACE; off restores this
// S19t (his call: "it should be instantaneous"): sustains → 0.7s — the callout lands the
// moment the posture registers; per-nudge cooldown 30s so a take can re-trigger.
// "No Jarvis, I need to do something important" → quietUntil silences ALL nudges for a spell.
const PHONE_MS = 700, SLOUCH_MS = 700, NUDGE_GAP_MS = 30000, RELIEF_MS = 180000;
let quietUntil = 0;
// S19v: organs never TOUCH the ear (his law) — but a deaf start must never be silent about
// it again ("the face appears but nothing responds" = the ear was off, twice field-hit)
function earNote(){
  try { return (J && J.hearing && !J.hearing()) ? ' My ears are off, sir — tap the ear button and just talk.' : ''; }
  catch (_){ return ''; }
}
// S21 (his call 2026-09-10, reverses S19s): clicking EYES / WATCH opens the 👂 if it is shut.
// Never from a probe or a muted test tab — a hidden tab must never start listening to him.
// Returns true only when the ear actually came up (a blocked mic still earns the honest note).
function earUp(){
  if (PROBE || Q.has('mute')) return false;
  try { if (J && J.hearing && !J.hearing() && J.hear){ J.hear(true); return !!J.hearing(); } } catch (_){}
  return false;
}
// v2 — nod/shake, attention hold, expression reactions
const headHist = [];             // [{t, yaw, pitch}] rolling ~1.4s head-pose window
let gestCool = 0, prevArmed = false, armedAt = 0, armedCache = false;
let awaySince = 0, held = false, holdAt = 0, lastLookPing = 0;
let frownSince = 0, smileSince = 0, smileShown = 0;
const cool = {};                 // per-nudge cooldowns
let EV = [];
const evLog = (n) => { EV.push({ n, t: performance.now() }); if (EV.length > 8) EV.shift(); };

/* ---------- the funny nudges (his brief: funny, dry, Jarvis) ---------- */
const LINES = {
  slouch: ["Sir, you're slouching toward the screen again. Spine like a Stark, please.",
           "Posture, sir. The chair is furniture, not a destination."],
  drowsy: ["Sir, your eyes have been closing for a while. Coffee, a stretch — or a nap. I won't judge. Much.",
           "Blink rate suggests imminent shutdown, sir. Might I suggest daylight?"],
  phone:  ["Sir, the phone has had you for quite a while now. The galaxy misses you.",
           "Another minute on the phone, sir, and I shall start billing it for my time."],
  frown:  ["Shall I take another run at that, sir?",
           "Not quite it, I gather. Say the word and I'll have another go, sir."],
  greetM: "Good morning, sir.", greetA: "Good afternoon, sir.", greetE: "Good evening, sir.",
};
let seq = 0;
function say(key, text, gapMs){
  const now = performance.now();
  if (key !== 'greet' && now < quietUntil) return false;   // "I need to do something important"
  if (now - (cool[key] || -9e9) < (gapMs ?? NUDGE_GAP_MS)) return false;
  cool[key] = now;
  const L = LINES[key];
  const line = text || (Array.isArray(L) ? L[seq++ % L.length] : L);
  evLog(key);
  if (key === 'greet') try { faceMoodReq('smile'); } catch (_){}     // he greets you — the face warms
  if (!PROBE) try { if (J && J.voice) J.voice(line); } catch (_){}   // battery runs silent
  return true;
}

/* ---------- face analysis (pure math — the probe drives this directly) ---------- */
function yawPitchFromMatrix(m){
  // facialTransformationMatrixes[0].data — column-major 4x4. Rotation only.
  if (!m || m.length < 11) return { yaw: 0, pitch: 0 };
  const yaw = Math.atan2(-m[8], m[10]) * 180 / Math.PI;          // head turn L/R
  const pitch = Math.asin(Math.max(-1, Math.min(1, m[9]))) * 180 / Math.PI;   // nod up/down
  return { yaw, pitch };
}
function analyze(res, now){
  const n = res && res.faceLandmarks ? res.faceLandmarks.length : 0;
  F.faces = n;
  if (!n){
    if (F.present){ F.present = false; F.absentSince = now; }
    F.looking = false;             // an empty chair is not looking (the attention hold keys off this)
    return F;
  }
  if (!F.present){
    F.present = true;
    // greet on arrival after a real absence (5+ min), when he looks over
    if (now - F.lastSeen > 300000) greetArmed = true;
  }
  F.lastSeen = now;
  const lm = res.faceLandmarks[0];
  const mat = res.facialTransformationMatrixes && res.facialTransformationMatrixes[0];
  const hp = yawPitchFromMatrix(mat && mat.data);
  F.yaw = hp.yaw; F.pitch = hp.pitch;
  F.looking = Math.abs(F.yaw) < 22 && F.pitch > -28 && F.pitch < 18;
  if (F.looking) F.lastLook = now;
  // blink / brow / smile levels from blendshapes
  let bl = 0, bd = 0, sm = 0;
  const bs = res.faceBlendshapes && res.faceBlendshapes[0];
  if (bs && bs.categories){
    let l = 0, r = 0;
    for (const c of bs.categories){
      if (c.categoryName === 'eyeBlinkLeft') l = c.score;
      else if (c.categoryName === 'eyeBlinkRight') r = c.score;
      else if (c.categoryName === 'browDownLeft' || c.categoryName === 'browDownRight') bd += c.score;
      else if (c.categoryName === 'mouthSmileLeft' || c.categoryName === 'mouthSmileRight') sm += c.score;
    }
    bl = (l + r) / 2;
  }
  F.blink = bl; F.brow = bd / 2; F.smile = sm / 2;
  // face height fraction (forehead 10 → chin 152)
  F.faceH = Math.abs((lm[152]?.y ?? 0) - (lm[10]?.y ?? 0));
  return F;
}
/* ---------- v2: is anything awaiting a yes? (nod/shake may ONLY fire then) ----------
   Three truths, matching how each bay actually arms:
   - 3d.html's own pendings (agent draft / call adopt / housekeeping) via confirmPending();
   - the missions bay's awaiting_confirm via window.__missionsConfirm;
   - the armed-route bays (hands / calls / tools flip a NEVER regex to a yes-matcher while
     pending). Probed with phrases ONLY those armed matchers accept — never bare "do it",
     which missions.js matches around the clock ("Nothing awaiting my confirmation, sir"). */
const ARMED_PROBES = ['the wheel is yours', 'lock it in', 'yes, do it'];
function confirmArmed(now){
  if (now && now - armedAt < 250) return armedCache;      // camera-rate calls ride a short cache
  armedAt = now || 0;
  let armed = false;
  try { const j = window.__jarvis; armed = !!(j && j.confirmPending && j.confirmPending()); } catch (_){}
  if (!armed) try { armed = !!(window.__missionsConfirm && window.__missionsConfirm()); } catch (_){}
  if (!armed) try {
    armed = (window.__jarvisRoutes || []).some(r => {
      try { return ARMED_PROBES.some(p => r.re.test(p)); } catch (_){ return false; }
    });
  } catch (_){}
  return (armedCache = armed);
}

/* ---------- v2: nod / head-shake = yes / no (fire on the 2nd reversal — pose transitions,
   never release timing, per the gesture law) ---------- */
function headGesture(now){
  headHist.push({ t: now, yaw: F.yaw, pitch: F.pitch });
  while (headHist.length && now - headHist[0].t > 1400) headHist.shift();
  if (now - gestCool < 2600 || headHist.length < 6) return null;
  let pMin = 1e9, pMax = -1e9, yMin = 1e9, yMax = -1e9;
  for (const h of headHist){
    if (h.pitch < pMin) pMin = h.pitch; if (h.pitch > pMax) pMax = h.pitch;
    if (h.yaw < yMin) yMin = h.yaw; if (h.yaw > yMax) yMax = h.yaw;
  }
  const pAmp = pMax - pMin, yAmp = yMax - yMin;
  const revs = (k) => {                                   // direction reversals above the tremor floor
    let r = 0, dir = 0;
    for (let i = 1; i < headHist.length; i++){
      const d = headHist[i][k] - headHist[i - 1][k];
      if (Math.abs(d) < .8) continue;
      const s = d > 0 ? 1 : -1;
      if (dir && s !== dir) r++;
      dir = s;
    }
    return r;
  };
  if (pAmp >= 7 && pAmp > yAmp * 1.6 && revs('pitch') >= 2) return 'nod';
  if (yAmp >= 9 && yAmp > pAmp * 1.6 && revs('yaw') >= 2) return 'shake';
  return null;
}

/* ---------- v2.1: attention — pause the sentence when he CLEARLY looks away, resume on
   return. Only ever calls 3d.html's attnHold (which pauses/resumes the CURRENT audio and
   nothing else), so the DV gate and the VAD machinery stay untouched.
   FIELD LESSON (his "eyes on = Jarvis goes mute" report): v2 held on !looking — but a warm-up
   frame, an off-axis camera, or a lost face all read as !looking, so speech paused the moment
   the eyes opened and never came back. v2.1 rules: (a) the machinery is DISARMED until the
   first real eye contact of the session (a misaligned camera can never mute him); (b) hold
   only on a HARD away — face PRESENT and head clearly turned (wide bounds), never on absence
   (a lost face is a detector problem, not a departure); (c) release the moment he is not
   hard-away; (d) 60s cap. ---------- */
const AWAY_YAW = 38, AWAY_PITCH_DN = -38, AWAY_PITCH_UP = 30;
let attnReady = false;
function hardAway(){
  return F.present && (Math.abs(F.yaw) > AWAY_YAW || F.pitch < AWAY_PITCH_DN || F.pitch > AWAY_PITCH_UP);
}
function attnStep(now){
  const hold = (on) => { const f = window.__eyesTestAH || (J && J.attnHold); try { if (f) f(on); } catch (_){} };
  if ((!ON && !PROBE) || window.__handsActive){           // organ off / drive owns the voice
    if (held){ held = false; hold(false); }
    awaySince = 0; return;
  }
  if (F.looking) attnReady = true;                        // first eye contact arms the gate
  if (!attnReady || !hardAway()){
    awaySince = 0;
    if (held){ held = false; evLog('attn-back'); hold(false); }
    if (F.looking && now - lastLookPing > 30000){ lastLookPing = now;   // a deferred briefing lands on eye contact
      if (!PROBE) try { if (J && J.attnLook) J.attnLook(); } catch (_){} }
    return;
  }
  if (!awaySince){ awaySince = now; return; }
  if (!held && now - awaySince > 900){ held = true; holdAt = now; evLog('attn-hold'); hold(true); }
  if (held && now - holdAt > 60000){ held = false; hold(false); }
}

function tick(now){
  attnStep(now);                                          // runs even with the chair empty
  if (!F.present) return;
  // greeting: armed by arrival, delivered on eye contact
  if (greetArmed && F.looking){
    greetArmed = false;
    const h = new Date().getHours();
    say('greet', LINES[h < 12 ? 'greetM' : h < 18 ? 'greetA' : 'greetE'], 60000);
  }
  // PERCLOS drowsiness: % of the last 60s with eyes mostly closed
  perclos.push({ t: now, closed: F.blink > .55 ? 1 : 0 });
  while (perclos.length && now - perclos[0].t > 60000) perclos.shift();
  if (perclos.length > 40){
    const frac = perclos.reduce((a, p) => a + p.closed, 0) / perclos.length;
    if (frac > .28) say('drowsy');
  }
  // slouch: calibrate an upright baseline while attentive — but NEVER learn from the
  // lean itself (a slow slouch would become the new "normal" and go unnudged)
  if (F.looking && F.blink < .4 && (baseH == null || F.faceH < baseH * 1.15)){
    baseH = baseH == null ? F.faceH : baseH + (F.faceH - baseH) * (baseN < 200 ? .02 : .002);
    baseN++;
  }
  if (baseH && baseN > 100 && F.faceH > baseH * 1.32){
    if (!slouchSince) slouchSince = now;
    else if (now - slouchSince > SLOUCH_MS) say('slouch');
  } else slouchSince = 0;
  // phone: head pitched well down, sustained — the honest proxy for phone-scrolling
  if (F.pitch < -35){
    if (!phoneSince) phoneSince = now;
    else if (now - phoneSince > PHONE_MS) say('phone');
  } else phoneSince = 0;
  // v2 — nod / head-shake answer a pending confirm, exactly as saying it would
  const armed = confirmArmed(now);
  if (armed && !prevArmed) headHist.length = 0;           // stale oscillation must never answer a fresh question
  prevArmed = armed;
  if (armed){
    const g = headGesture(now);
    if (g){
      gestCool = now; headHist.length = 0; evLog(g);
      const inj = window.__eyesTestAsk || window.__jarvisAsk;
      try { if (J && J.status) J.status(g === 'nod' ? '● a nod — very good, sir' : '● a shake — standing down'); } catch (_){}
      try { if (inj) inj(g === 'nod' ? 'do it' : 'cancel'); } catch (_){}
    }
  } else { headHist.length = 0; gestCool = 0; }
  // v2 — expression reactions, only while an answer is fresh on screen
  const shown = window.__jarvisShownAt || 0;
  const fresh = shown && Date.now() - shown < 45000;
  if (fresh && F.brow > .55 && F.blink < .5){             // sustained frown at the answer (blink guard: squinting ≠ frowning)
    if (!frownSince) frownSince = now;
    else if (now - frownSince > 2600 && say('frown')) frownSince = 0;
  } else frownSince = 0;
  if (fresh && F.smile > .55 && Date.now() - shown > 1200 && shown !== smileShown){
    if (!smileSince) smileSince = now;
    else if (now - smileSince > 1400){
      smileShown = shown; smileSince = 0; evLog('smile'); // one per answer — a grin is not a metronome
      try { faceMoodReq('smile'); } catch (_){}           // you smiled — he smiles back
      if (!PROBE) fetch('/episode', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: 'eyes', text: 'He smiled at the answer on screen.' }) }).catch(() => {});
    }
  } else smileSince = 0;
}

/* ---------- camera + loop ---------- */
async function loop(){
  if (!ON) return;
  const now = performance.now();
  if (faceLm && video && video.readyState >= 2 && video.currentTime !== lastVT){
    lastVT = video.currentTime;
    try { tick(analyze(faceLm.detectForVideo(video, now), now) && now); } catch (_){}
    try { window.__eyes = { on: true, looking: F.looking, present: F.present, lastLook: F.lastLook, faces: F.faces, pitch: +F.pitch.toFixed(1) }; } catch (_){}
  }
  rafId = requestAnimationFrame(loop);
}
async function enable(quiet){
  if (ON) return true;
  chipE.dataset.state = '…';
  try {
    if (!faceLm){
      const vision = await import('/vendor-holo/vision_bundle.mjs');
      const files = await vision.FilesetResolver.forVisionTasks('/vendor-holo/wasm');
      const mk = (d) => vision.FaceLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: '/vendor-holo/face_landmarker.task', delegate: d },
        runningMode: 'VIDEO', numFaces: 2,
        outputFaceBlendshapes: true, outputFacialTransformationMatrixes: true });
      try { faceLm = await mk('GPU'); } catch (_){ faceLm = await mk('CPU'); }
    }
    if (!PROBE){
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 960 }, height: { ideal: 540 }, facingMode: 'user' }, audio: false });
      } catch (e1){
        if (e1 && (e1.name === 'NotAllowedError' || e1.name === 'SecurityError')) throw e1;
        // exotic constraint refusals / flaky device enumeration: one plain retry
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      }
      video.srcObject = stream; await video.play();
    }
    ON = true;
    attnReady = false;                                 // attention gate stays disarmed until real eye contact
    chipE.dataset.state = 'watching'; chipE.classList.add('on');
    // S19p (his spec): eyes on = the FACE takes the reactor + hands-free hearing goes hot
    try {
      if (facePref !== false && avatarPref !== 'portrait'){ prevAvatar = avatarPref; setAvatar('portrait', true); }
    } catch (_){}
    try { window.__eyesHot = true; } catch (_){}
    // S21 (his call, reverses S19s): opening the eyes opens the ear too; the stay-hot clause
    // then keeps the whole session wake-word-free. ONE combined line — never two voices.
    const earOn = earUp();
    try { if (J && J.listen) J.listen(); } catch (_){}
    if (!quiet) try { if (J) J.voice(earOn ? 'Eyes open, sir — and listening.' : 'Eyes open, sir.' + earNote()); } catch (_){}
    loop();
    return true;
  } catch (e){
    chipE.dataset.state = 'off'; chipE.classList.remove('on');
    // name the ACTUAL failure — a blind "would not open" cost a field round (S17e)
    const nm = (e && e.name) || '';
    let line = 'My eyes would not open, sir.';
    if (nm === 'NotAllowedError' || nm === 'SecurityError') line = 'The camera is blocked for this site, sir.';
    else if (nm === 'NotReadableError' || nm === 'AbortError') line = 'The camera is held by another app or tab, sir — close whatever has it, then try me again.';
    else if (nm === 'NotFoundError') line = 'I cannot find a camera on this machine, sir.';
    try { if (J){ J.voice(line); if (J.showLine) J.showLine('EYES failed: ' + (nm || 'unknown') + ' — ' + ((e && e.message) || '')); } } catch (_){}
    console.warn('[eyes] enable failed:', e);
    return false;
  }
}
/* a closed or crashed tab must never strand the camera for the next session (the classic
   cause of NotReadableError on the following "eyes on") */
addEventListener('pagehide', () => {
  try { if (stream) for (const t of stream.getTracks()) t.stop(); } catch (_){}
  try { if (WATCH.stream) for (const t of WATCH.stream.getTracks()) t.stop(); } catch (_){}
});
function disable(quiet){
  if (!ON) return;
  ON = false;
  cancelAnimationFrame(rafId);
  if (stream){ for (const t of stream.getTracks()) t.stop(); stream = null; }
  if (video) video.srcObject = null;
  F.present = false; F.looking = false; attnReady = false;
  if (held){ held = false; try { if (J && J.attnHold) J.attnHold(false); } catch (_){} }   // never leave a sentence paused
  awaySince = 0; headHist.length = 0; prevArmed = false;
  try { window.__eyes = { on: false, looking: false, present: false, lastLook: -9e9, faces: 0, pitch: 0 }; } catch (_){}
  try { window.__eyesHot = false; } catch (_){}
  try {
    if (prevAvatar && avatarPref === 'portrait'){ setAvatar(prevAvatar, true); }
    prevAvatar = null;
  } catch (_){}
  chipE.dataset.state = 'off'; chipE.classList.remove('on');
  if (!quiet) try { if (J) J.voice('Eyes closed.'); } catch (_){}
}
/* ---------- "look at me" / "what do you think of this…" — one frame to the brain ---------- */
async function grabFrame(){
  if (!ON || !video || video.readyState < 2) return null;
  const vw = video.videoWidth, vh = video.videoHeight;
  if (!vw) return null;
  const w = Math.min(1024, vw), h = Math.round(vh * (w / vw));
  const cv = document.createElement('canvas'); cv.width = w; cv.height = h;
  cv.getContext('2d').drawImage(video, 0, 0, w, h);
  const data = cv.toDataURL('image/jpeg', .72);
  return data.length > 3000 ? data.split(',')[1] : null;
}
function watchFrame(){
  // one decent-res frame off the WATCH share (base64) — the nudge and screen questions share it
  try {
    const v = WATCH.video, vw = v && v.videoWidth, vh = v && v.videoHeight;
    if (!vw) return null;
    const w = Math.min(1280, vw), h = Math.round(vh * (w / vw));
    const cv = document.createElement('canvas'); cv.width = w; cv.height = h;
    cv.getContext('2d').drawImage(v, 0, 0, w, h);
    const data = cv.toDataURL('image/jpeg', .68);
    return data.length > 3000 ? data.split(',')[1] : null;
  } catch (_){ return null; }
}
async function lookAndAnswer(q){
  // S19r: during WATCH with the camera off, "what do you think of this?" means the SCREEN —
  // never silently switch the webcam on to answer it
  if (!ON && WATCH.on){
    const img2 = watchFrame();
    if (img2){
      try { if (J) J.voice('Taking a look, sir.'); } catch (_){}
      try {
        const r2 = await fetch('/see', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ image: img2,
            question: "This is the user's live screen (you are JARVIS, watching it at their request). " +
              'Answer their question about what is on it — concise, specific, dry British-butler wit, 1-3 sentences. Question: ' + q }) });
        const d2 = await r2.json();
        const ans2 = d2.answer || d2.text || d2.error || 'I looked, sir, but words fail me.';
        try { if (J) J.say(ans2); } catch (_){}
      } catch (_){ try { if (J) J.voice('My vision line dropped, sir.'); } catch (_){} }
      return;
    }
  }
  if (!ON){
    const ok2 = await enable();
    if (!ok2) return;
    await new Promise(r => setTimeout(r, 900));           // first frames
  }
  const img = await grabFrame();
  if (!img){ try { if (J) J.voice('I could not get a clear look, sir.'); } catch (_){} return; }
  try { if (J) J.voice('Taking a look, sir.'); } catch (_){}
  try {
    const r = await fetch('/see', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: img,
        question: 'This is a live webcam photo of the user at their desk (you are JARVIS and this is your camera). ' +
                  'Answer their question about what you see — concise, specific, dry British-butler wit, 1-3 sentences. Question: ' + q }) });
    const d = await r.json();
    const ans = d.answer || d.text || d.error || 'I looked, sir, but words fail me.';
    try { if (J) J.say(ans); else console.log('[eyes]', ans); } catch (_){}
  } catch (e){ try { if (J) J.voice('My vision line dropped, sir.'); } catch (_){} }
}

/* ---------- v2: SCREEN WATCH (opt-in) — "you've been staring at that for a while, sir" ----
   "watch my screen" → his own display share → a 64×36 thumbnail is diffed LOCALLY every 5s
   (zero cost, zero frames leave the machine). Only when the screen has sat unchanged past
   the stare threshold does ONE frame ride /see for a dry, genuinely useful nudge — then a
   cooldown. If EYES is also on and the chair is empty, no nudge (nobody is staring).
   S19q demo cadence: stare 4min→60s, cooldown 10min→3min — WATCH visibly DOES something
   inside a demo take. */
const WATCH = { on: false, stream: null, video: null, cv: null, cx: null, prev: null,
                staticSince: 0, iv: 0, cool: -9e9 };
const WATCH_STARE_MS = 60000, WATCH_COOL_MS = 180000, WATCH_TICK_MS = 5000;
function watchAssess(changedFrac, now){               // pure logic — probed
  if (changedFrac > .02){ WATCH.staticSince = now; return false; }
  if (!WATCH.staticSince) WATCH.staticSince = now;
  if (now - WATCH.staticSince < WATCH_STARE_MS) return false;
  if (now - WATCH.cool < WATCH_COOL_MS) return false;
  WATCH.cool = now; WATCH.staticSince = now;
  return true;
}
function watchSample(){
  const v = WATCH.video;
  if (!v || v.readyState < 2) return;
  const w = 64, h = 36;
  WATCH.cx.drawImage(v, 0, 0, w, h);
  let d; try { d = WATCH.cx.getImageData(0, 0, w, h).data; } catch (_){ return; }
  let changed = 0; const total = w * h;
  if (WATCH.prev){
    for (let i = 0; i < d.length; i += 4){
      if (Math.abs(d[i] - WATCH.prev[i]) + Math.abs(d[i + 1] - WATCH.prev[i + 1]) +
          Math.abs(d[i + 2] - WATCH.prev[i + 2]) > 34) changed++;
    }
  } else changed = total;
  WATCH.prev = d;
  const himAway = ON && F.present === false;          // camera says the chair is empty — nobody is staring
  if (!himAway && watchAssess(changed / total, performance.now())) watchNudge();
}
async function watchNudge(){
  evLog('stare');
  if (PROBE) return;
  try {
    const img = watchFrame();
    if (!img) return;
    const mins = Math.max(1, Math.round(WATCH_STARE_MS / 60000));
    const r = await fetch('/see', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: img,
        question: "This is the user's screen. It has not changed for about " + mins + " minutes — they appear stuck or zoned out on it. You are JARVIS: in ONE or TWO short sentences, dry British-butler wit, name what they seem to be staring at and make one genuinely useful offer — help, the obvious next step, or a nudge to move on." }) });
    const d2 = await r.json();
    const ans = d2.answer || d2.text;
    if (ans){ try { if (J) J.say(ans); } catch (_){} }
  } catch (_){}
}
async function watchOn(){
  if (WATCH.on) return true;
  try {
    WATCH.stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 2 }, audio: false });
    WATCH.video = document.createElement('video'); WATCH.video.muted = true; WATCH.video.playsInline = true;
    WATCH.video.srcObject = WATCH.stream; await WATCH.video.play();
    if (!WATCH.cv){ WATCH.cv = document.createElement('canvas'); WATCH.cv.width = 64; WATCH.cv.height = 36;
      WATCH.cx = WATCH.cv.getContext('2d', { willReadFrequently: true }); }
    WATCH.prev = null; WATCH.staticSince = 0;
    WATCH.iv = setInterval(watchSample, WATCH_TICK_MS);
    const t = WATCH.stream.getVideoTracks()[0];
    if (t) t.onended = () => watchOff(true);          // he ended the share from the browser chrome
    WATCH.on = true; chipW.dataset.state = 'on screen'; chipW.classList.add('on');
    evLog('watch-on');
    // S21 (his call, reverses S19s): WATCH opens the 👂 too; the stay-hot clause then makes
    // the share an open conversation. ONE combined line below — never two voices.
    const earOn = earUp();
    try { if (J && J.listen) J.listen(); } catch (_){}
    // S19u (his correction): WATCH is SCREEN-ONLY — it never touches the camera; the
    // instant phone/slouch callouts + the relief valve are EYES features (turn EYES on
    // alongside WATCH when you want both)
    // the desktop overlay: Jarvis's living face pinned top-right of the REAL screen while
    // he watches — so you can SEE that he's watching, on the very screen you're sharing
    try { fetch('/facewin', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ on: true }) }).catch(() => {}); } catch (_){}
    try { if (J) J.voice(earOn ? "Eyes on your screen and listening, sir. I'll speak up if you get stuck."
                                : "Eyes on your screen, sir. I'll speak up if you get stuck." + earNote()); } catch (_){}
    // S19b: a fresh screen share is the deep-work moment — the focus bay may offer the clock
    setTimeout(() => { try { if (window.__focusOffer) window.__focusOffer('watch'); } catch (_){} }, 3500);
    return true;
  } catch (e){
    try { if (J) J.voice('The screen was not shared, sir.'); } catch (_){}
    return false;
  }
}
function watchOff(fromShare){
  if (!WATCH.on) return;
  WATCH.on = false;
  clearInterval(WATCH.iv);
  if (WATCH.stream){ for (const t of WATCH.stream.getTracks()) t.stop(); WATCH.stream = null; }
  WATCH.video = null; WATCH.prev = null; WATCH.staticSince = 0;
  chipW.dataset.state = 'off'; chipW.classList.remove('on');
  evLog('watch-off');
  try { fetch('/facewin', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ on: false }) }).catch(() => {}); } catch (_){}
  try { if (J) J.voice(fromShare ? 'Screen share ended — my watch is over, sir.' : 'Standing down from the screen, sir.'); } catch (_){}
}

/* ---------- v4: HOLOFACE — the LIVE 3D face. No video anywhere. ----------
   His verdict: "it cannot be a video… build an actual live 3D version… lips light up /
   move exactly when Jarvis speaks." So: the vendored FaceLandmarker runs ONCE over the
   approved portrait (IMAGE mode) → the real 478-point 3D geometry OF THAT FACE + the
   bundle's own edge/lip/eye/iris index sets (cached in localStorage, ~1s first time,
   instant after). three.js (the page's import map) renders it as ~8k additive particles
   sampled along the tesselation edges, each colored from the portrait's own pixels —
   the "face made of streaming data", genuinely in 3D and genuinely procedural:
   noise-driven head micro-motion + breathing, Poisson-timed blinks, iris saccades,
   falling data-rain, a jaw that opens with the LIVE voice level (6.5Hz syllable flutter
   on top) while the lip particles GLOW with it, and a smile morph for greet/smiled-back
   moments. Nothing loops — every frame is computed. hfCompute() is pure math (probed
   headless); the renderer just draws its output.
   TWO MOUNTS, HIS CHOICE ("use your face" / "bring back the orb", persisted):
   avatar=face → the reactor orb hides (body.jface) and the face lives at the orb's spot
   full-time; avatar=orb (default) → the face lives in the EYES card as before. */
let facePref = true; try { facePref = localStorage.getItem('jarvis-face') !== '0'; } catch (_){}
let avatarPref = 'orb';
try {
  const av0 = localStorage.getItem('jarvis-avatar');
  avatarPref = av0 === 'face' || av0 === 'cube' ? 'cube' : (av0 === 'portrait' ? 'portrait' : 'orb');
} catch (_){}
let hfWant = false;
let HF = null, hfRaf = 0, hfMountEl = null, hfR = null, hfScene = null, hfCam = null, hfPts = null, hfRain = null;
let hfLvS = 0, hfBlink = { next: 0, t0: -9e9 }, hfSacc = { next: 0, x: 0, y: 0, tx: 0, ty: 0 }, hfMood = null;
let hfInitP = null, avatarWired = false;
function faceMoodReq(m){ if (m === 'smile') hfMood = { t0: performance.now() }; }

/* geometry: extract once from the portrait, cache forever (keyed by portrait size) */
async function hfGeo(){
  let key = 'jarvis-hf-geo-v2';
  try { const c = localStorage.getItem(key); if (c) return JSON.parse(c); } catch (_){}
  const vision = await import('/vendor-holo/vision_bundle.mjs');
  const files = await vision.FilesetResolver.forVisionTasks('/vendor-holo/wasm');
  const mk = (d) => vision.FaceLandmarker.createFromOptions(files, {
    baseOptions: { modelAssetPath: '/vendor-holo/face_landmarker.task', delegate: d },
    runningMode: 'IMAGE', numFaces: 1 });
  let lm; try { lm = await mk('GPU'); } catch (_){ lm = await mk('CPU'); }
  // createImageBitmap, NOT Image.decode(): decode() defers forever in a hidden pane (no
  // compositor) — the bitmap path is compositor-independent and mediapipe accepts it
  const bmp = await fetch('/jarvis-face.png').then(r => r.blob()).then(b => createImageBitmap(b));
  const res = lm.detect(bmp);
  try { bmp.close(); } catch (_){}
  try { lm.close(); } catch (_){}
  if (!res.faceLandmarks || !res.faceLandmarks[0]) throw new Error('no face found in the portrait');
  const F = vision.FaceLandmarker;
  const pair = (cs) => cs.map(c => [c.start, c.end]);
  const setOf = (cs) => [...new Set(cs.flatMap(c => [c.start, c.end]))];
  const geo = {
    pts: res.faceLandmarks[0].map(p => [+p.x.toFixed(4), +p.y.toFixed(4), +p.z.toFixed(4)]),
    edges: pair(F.FACE_LANDMARKS_TESSELATION),
    lips: setOf(F.FACE_LANDMARKS_LIPS),
    le: setOf(F.FACE_LANDMARKS_LEFT_EYE), re: setOf(F.FACE_LANDMARKS_RIGHT_EYE),
    li: setOf(F.FACE_LANDMARKS_LEFT_IRIS), ri: setOf(F.FACE_LANDMARKS_RIGHT_IRIS),
    oval: setOf(F.FACE_LANDMARKS_FACE_OVAL),
  };
  try { localStorage.setItem(key, JSON.stringify(geo)); } catch (_){}
  return geo;
}

/* pure build: geo (+ per-landmark colors) → animation state. No DOM, no GL — probed. */
function hfBuild(geo, colors){
  const n = geo.pts.length;
  // normalize: center + unit height, y up, z toward viewer
  let minX = 9e9, maxX = -9e9, minY = 9e9, maxY = -9e9;
  for (const p of geo.pts){ minX = Math.min(minX, p[0]); maxX = Math.max(maxX, p[0]);
                            minY = Math.min(minY, p[1]); maxY = Math.max(maxY, p[1]); }
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2, s = 1 / Math.max(1e-4, maxY - minY);
  const norm = { cx, cy, s };                          // the image cloud shares this exact mapping
  const base = new Float32Array(n * 3), cur = new Float32Array(n * 3);
  for (let i = 0; i < n; i++){
    base[i * 3] = (geo.pts[i][0] - cx) * s;
    base[i * 3 + 1] = -(geo.pts[i][1] - cy) * s;
    base[i * 3 + 2] = -geo.pts[i][2] * s * 1.15;       // mediapipe z is subtle — lift the relief
  }
  const lipSet = new Set(geo.lips);
  // particles ride the edges: {a, b, t} — every deformation of the landmarks carries them
  const parts = [];
  for (const [ea, eb] of geo.edges){
    const lip = lipSet.has(ea) || lipSet.has(eb);
    for (const t of [0, .34, .67]) parts.push({ a: ea, b: eb, t, lip });
  }
  const centroid = (set) => {
    let x = 0, y = 0;
    for (const i of set){ x += base[i * 3]; y += base[i * 3 + 1]; }
    return { x: x / set.length, y: y / set.length };
  };
  const eyeL = centroid(geo.le), eyeR = centroid(geo.re);
  let lipY = centroid(geo.lips).y;
  const lower = geo.lips.filter(i => base[i * 3 + 1] < lipY);              // the jaw half
  const chin = geo.oval.filter(i => base[i * 3 + 1] < lipY - .04);
  let lipL = geo.lips[0], lipR = geo.lips[0];
  for (const i of geo.lips){ if (base[i * 3] < base[lipL * 3]) lipL = i;
                             if (base[i * 3] > base[lipR * 3]) lipR = i; }
  return { n, base, cur, parts, colors, norm,
           le: geo.le, re: geo.re, li: geo.li, ri: geo.ri,
           eyeL, eyeR, lower, chin, lipL, lipR };
}

/* pure per-frame animator — writes st.cur from st.base. Everything live, nothing looped. */
function hfCompute(st, t, lv, blinkAmt, mood){
  hfLvS += (Math.min(1, lv * 1.6) - hfLvS) * .35;      // fast attack, soft release
  const lvS = hfLvS;
  if (!st.shift) st.shift = { x: 0, y: 0, tx: 0, ty: 0, next: 0 };
  const sh = st.shift;
  if (t >= sh.next){                                  // a person re-settles their gaze — metronomes don't
    sh.next = t + 3800 + Math.random() * 5200;
    sh.tx = (Math.random() - .5) * .11; sh.ty = (Math.random() - .5) * .05;
  }
  sh.x += (sh.tx - sh.x) * .028; sh.y += (sh.ty - sh.y) * .028;
  const yaw = (Math.sin(t * .00013) + Math.sin(t * .000041 + 2)) * .07 + sh.x,
        pit = (Math.sin(t * .00009 + 1) + Math.sin(t * .000031)) * .035 + sh.y,
        rol = Math.sin(t * .00006 + 4) * .02 + sh.x * .18,
        breathe = 1 + .006 * Math.sin(t * .0007);
  const cy2 = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pit), sp = Math.sin(pit),
        cr = Math.cos(rol), sr = Math.sin(rol);
  const { base, cur, n } = st;
  for (let i = 0; i < n; i++){
    let x = base[i * 3] * breathe, y = base[i * 3 + 1] * breathe, z = base[i * 3 + 2] * breathe;
    let x1 = x * cy2 + z * sy, z1 = -x * sy + z * cy2;          // yaw
    let y1 = y * cp - z1 * sp, z2 = y * sp + z1 * cp;           // pitch
    let x2 = x1 * cr - y1 * sr, y2 = x1 * sr + y1 * cr;         // roll
    cur[i * 3] = x2; cur[i * 3 + 1] = y2; cur[i * 3 + 2] = z2;
  }
  if (!st.rigid) st.rigid = new Float32Array(n * 3);
  st.rigid.set(cur);                                   // pose WITHOUT the local edits — the cloud
  st.rot = { cy2, sy, cp, sp, cr, sr, breathe };       // extracts blink/jaw/smile deltas from it
  if (blinkAmt > 0){                                    // lids fall toward each eye's center
    for (const set of [st.le, st.re]){
      const c = set === st.le ? st.eyeL : st.eyeR;
      for (const i of set) cur[i * 3 + 1] += (c.y - cur[i * 3 + 1]) * blinkAmt * .9;
    }
  }
  if (lvS > .01){                                       // the voice opens the jaw, with syllable flutter
    const open = lvS * .075 * (1 + .45 * Math.sin(t * .0408));
    for (const i of st.lower) cur[i * 3 + 1] -= open;
    for (const i of st.chin) cur[i * 3 + 1] -= open * .55;
  }
  const sx = hfSacc.x, sy2 = hfSacc.y;                  // iris micro-saccades
  if (sx || sy2) for (const set of [st.li, st.ri])
    for (const i of set){ cur[i * 3] += sx; cur[i * 3 + 1] += sy2; }
  if (mood != null){                                    // smile morph: corners up and out
    for (const [idx, dir] of [[st.lipL, -1], [st.lipR, 1]]){
      cur[idx * 3] += dir * .022 * mood; cur[idx * 3 + 1] += .028 * mood;
    }
  }
  return cur;
}

async function hfInit(){
  if (HF) return HF;
  if (hfInitP) return hfInitP;
  hfInitP = (async () => {
    /* S17j — THE VIKI PORT (his call: "I just built this in the VIKI project — incorporate
       the same thing, male version"). His own proven technique from
       projects/2026-08-viki/viewer/viki.js: a FIXED dot lattice on the four cube walls —
       the dots NEVER move (my mesh-warp distortion is structurally impossible) — and a
       512px face-source canvas drives dot brightness+size through the vertex shader.
       The male idle FILM paints the canvas each frame (grayscale+contrast, VIKI's grade);
       speech = VIKI's mouth-darkening driven by the live voice; the still portrait is the
       fallback with painted Poisson blinks. Landmarks are detected ONCE on a film frame so
       the mouth/eye anchors land exactly (cached; constants as last resort). */
    const T = await import('three');
    // the film (his liked loop), else the still portrait
    let faceVid = null, still = null;
    try {
      const v2 = document.createElement('video');
      v2.muted = true; v2.playsInline = true; v2.loop = true;
      v2.src = '/jarvis-face-loop.mp4';
      const vOk = await new Promise(res => {
        v2.onloadeddata = () => res(true);
        v2.onerror = () => res(false);
        setTimeout(() => res(false), 4000);
      });
      if (vOk){ faceVid = v2; v2.play().catch(() => {}); }
    } catch (_){}
    if (!faceVid){
      still = await fetch('/jarvis-face.png').then(r => r.blob()).then(b2 => createImageBitmap(b2)).catch(() => null);
    }
    // ---- anchors: detect once on the ACTUAL source (film frame or still) ----
    let anchors = { mouth: { x: .5, y: .62, rx: .105, ry: .042 }, eyes: { y: .40, lx: .40, rx: .60, r: .05 } };
    try {
      const key = 'jarvis-hf-anchors-v1-' + (faceVid ? 'film' : 'still');
      const cached = localStorage.getItem(key);
      if (cached) anchors = JSON.parse(cached);
      else {
        const src2 = faceVid || still;
        if (src2){
          const ac = document.createElement('canvas');
          ac.width = faceVid ? faceVid.videoWidth : still.width;
          ac.height = faceVid ? faceVid.videoHeight : still.height;
          ac.getContext('2d').drawImage(src2, 0, 0);
          const vision = await import('/vendor-holo/vision_bundle.mjs');
          const files = await vision.FilesetResolver.forVisionTasks('/vendor-holo/wasm');
          const mk = (d) => vision.FaceLandmarker.createFromOptions(files, {
            baseOptions: { modelAssetPath: '/vendor-holo/face_landmarker.task', delegate: d },
            runningMode: 'IMAGE', numFaces: 1 });
          let lm2; try { lm2 = await mk('GPU'); } catch (_){ lm2 = await mk('CPU'); }
          const bmp3 = await createImageBitmap(ac);
          const res2 = lm2.detect(bmp3);
          try { bmp3.close(); lm2.close(); } catch (_){}
          const pts2 = res2.faceLandmarks && res2.faceLandmarks[0];
          if (pts2){
            const F2 = (await import('/vendor-holo/vision_bundle.mjs')).FaceLandmarker;
            const setOf = (cs) => [...new Set(cs.flatMap(c => [c.start, c.end]))];
            const cen = (idx) => { let x = 0, y = 0; for (const i2 of idx){ x += pts2[i2].x; y += pts2[i2].y; } return { x: x / idx.length, y: y / idx.length }; };
            const lips2 = setOf(F2.FACE_LANDMARKS_LIPS), le2 = setOf(F2.FACE_LANDMARKS_LEFT_EYE), re2 = setOf(F2.FACE_LANDMARKS_RIGHT_EYE);
            const mc = cen(lips2), lc = cen(le2), rc = cen(re2);
            anchors = { mouth: { x: mc.x, y: mc.y, rx: .105, ry: .042 },
                        eyes: { y: (lc.y + rc.y) / 2, lx: lc.x, rx: rc.x, r: .05 } };
            try { localStorage.setItem(key, JSON.stringify(anchors)); } catch (_){}
          }
        }
      }
    } catch (_){}
    // ---- S17l: THE EXACT FILM, full fidelity, on the four faces ("this exact attached
    // one on the four faces"). No dots, no grade, no vertex warping — four DEAD-FLAT
    // planes showing the bridge canvas (the film verbatim + 2D speech paints), per-face
    // opacity computed on the CPU from facing angle (front owns, rest ghost), VIKI's
    // dust + cage + the slow spin kept for the 3D read.
    const bw = faceVid ? faceVid.videoWidth : (still ? still.width : 540);
    const bh = faceVid ? faceVid.videoHeight : (still ? still.height : 720);
    const bc = document.createElement('canvas'); bc.width = bw; bc.height = bh;
    const bcx = bc.getContext('2d');
    if (still) bcx.drawImage(still, 0, 0, bw, bh);
    const tex = new T.CanvasTexture(bc);
    tex.colorSpace = T.SRGBColorSpace;
    tex.minFilter = T.LinearFilter; tex.magFilter = T.LinearFilter;
    const S2 = 3.2;
    const ph2 = S2 * .96, pw2 = ph2 * (bw / bh);
    const scene = new T.Scene();
    const cam = new T.PerspectiveCamera(42, 1, .1, 100);
    cam.position.set(0, 0.15, 5.1);
    const rig3 = new T.Group();
    const faceMeshes = [];
    for (let side = 0; side < 4; side++){
      const m3 = new T.Mesh(
        new T.PlaneGeometry(pw2, ph2),
        new T.MeshBasicMaterial({ map: tex, transparent: true, opacity: 1,
          blending: T.AdditiveBlending, depthWrite: false, side: T.DoubleSide }));
      const ry = side * Math.PI / 2;
      m3.rotation.y = ry;
      m3.position.set(Math.sin(ry) * S2 / 2 * .98, 0, Math.cos(ry) * S2 / 2 * .98);
      m3.userData.ry = ry;
      rig3.add(m3); faceMeshes.push(m3);
    }
    // interior dust (kept from the VIKI port — the atmosphere inside the glass)
    const DUST = 2200;
    const dpos = new Float32Array(DUST * 3);
    for (let k = 0; k < DUST; k++){
      dpos[k * 3] = (Math.random() - .5) * S2; dpos[k * 3 + 1] = (Math.random() - .5) * S2;
      dpos[k * 3 + 2] = (Math.random() - .5) * S2;
    }
    const dg = new T.BufferGeometry();
    dg.setAttribute('position', new T.BufferAttribute(dpos, 3));
    const dust = new T.Points(dg, new T.PointsMaterial({ size: .016, color: 0x2e6fe8,
      transparent: true, opacity: .35, blending: T.AdditiveBlending, depthWrite: false }));
    rig3.add(dust);
    const edges = new T.LineSegments(                 // spherical cage (his call — not a box)
      new T.WireframeGeometry(new T.SphereGeometry(2.5, 18, 10)),
      new T.LineBasicMaterial({ color: 0x8fb8cc, transparent: true, opacity: .09,
        blending: T.AdditiveBlending, depthWrite: false }));
    rig3.add(edges);
    scene.add(rig3);

    const r = new T.WebGLRenderer({ alpha: true, antialias: true });
    r.setPixelRatio(Math.min(2, devicePixelRatio || 1));
    r.domElement.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;';
    HF = { scene, cam, r, T, rig3, faceMeshes, cage: edges, dust, spin: 0, lastTs: 0,
           vid: faceVid, still, bc, bcx, tex, anchors,
           shift: { x: 0, y: 0, tx: 0, ty: 0, next: 0 } };
    return HF;
  })().catch(e => { hfInitP = null; throw e; });
  return hfInitP;
}

function hfAttach(el, w, h){
  if (!HF) return;
  hfMountEl = el;
  el.appendChild(HF.r.domElement);
  HF.r.setSize(w, h, false);
  HF.cam.aspect = w / h; HF.cam.updateProjectionMatrix();
  if (HF.vid) HF.vid.play().catch(() => {});           // the film rolls whenever the face is up
}
function hfTick(ts){
  hfRaf = requestAnimationFrame(hfTick);
  const H2 = HF; if (!H2 || !hfMountEl || !hfMountEl.isConnected) return;
  const lv = Math.max(0, Math.min(1, window.__voiceLevel || 0));
  hfLvS += (Math.min(1, lv * 1.6) - hfLvS) * .35;
  // ---- the bridge canvas: the film VERBATIM (his blue, untouched) + 2D speech paints
  const bw = H2.bc.width, bh = H2.bc.height, bx2 = H2.bcx, A2 = H2.anchors;
  const src3 = H2.vid && H2.vid.readyState >= 2 ? H2.vid : H2.still;
  if (src3){
    if (H2.vid && H2.vid.paused) H2.vid.play().catch(() => {});   // bg-suspension self-heal
    bx2.globalCompositeOperation = 'source-over';
    bx2.drawImage(src3, 0, 0, bw, bh);
    if (hfLvS > .03){
      const open = hfLvS * (0.75 + 0.25 * Math.sin(ts * .041));   // syllable flutter
      const mx = A2.mouth.x * bw, my = A2.mouth.y * bh, mr = A2.mouth.rx * bw * 1.4;
      bx2.globalCompositeOperation = 'multiply';                  // the mouth opens…
      let gg = bx2.createRadialGradient(mx, my, 0, mx, my, mr * .7);
      gg.addColorStop(0, 'rgba(0,0,20,' + (0.6 * open).toFixed(2) + ')');
      gg.addColorStop(1, 'rgba(255,255,255,0)');
      bx2.fillStyle = gg;
      bx2.beginPath(); bx2.ellipse(mx, my, mr * .7, bh * A2.mouth.ry * (0.5 + open * 1.6), 0, 0, 7); bx2.fill();
      bx2.globalCompositeOperation = 'lighter';                   // …and the lips light up
      gg = bx2.createRadialGradient(mx, my, 0, mx, my, mr);
      gg.addColorStop(0, 'rgba(120,200,255,' + (0.45 * open).toFixed(2) + ')');
      gg.addColorStop(1, 'rgba(120,200,255,0)');
      bx2.fillStyle = gg;
      bx2.beginPath(); bx2.arc(mx, my, mr, 0, 7); bx2.fill();
      bx2.globalCompositeOperation = 'source-over';
    }
    H2.tex.needsUpdate = true;
  }
  // ---- motion + mode: CUBE spins; PORTRAIT holds still and faces you (his option 3)
  const dt = Math.min(50, H2.lastTs ? ts - H2.lastTs : 16); H2.lastTs = ts;
  const portrait = avatarPref === 'portrait';
  if (!portrait) H2.spin += dt * .000135 * (1 + hfLvS * .35);
  const sh2 = H2.shift;
  if (ts >= sh2.next){ sh2.next = ts + 3800 + Math.random() * 5200;
    sh2.tx = (Math.random() - .5) * .10; sh2.ty = (Math.random() - .5) * .05; }
  sh2.x += (sh2.tx - sh2.x) * .028; sh2.y += (sh2.ty - sh2.y) * .028;
  const gy = portrait ? sh2.x * .35 : H2.spin + sh2.x;
  H2.rig3.rotation.y = gy;
  H2.rig3.rotation.x = sh2.y * (portrait ? .3 : .6);
  H2.cage.visible = !portrait; H2.dust.visible = !portrait;
  const camT = portrait ? 4.1 : 5.1;                   // the flat face fills the mount
  H2.cam.position.z += (camT - H2.cam.position.z) * .08;
  // ---- per-face ghosting (cube) / single panel (portrait)
  let gain = 1;
  if (hfMood){
    const mp = (ts - hfMood.t0) / 1400;
    if (mp >= 1) hfMood = null; else gain = 1 + Math.sin(Math.min(1, mp) * Math.PI) * .15;
  }
  for (const m3 of H2.faceMeshes){
    if (portrait){
      m3.material.opacity = m3.userData.ry === 0 ? Math.min(1, gain) : 0;
      continue;
    }
    const nz = Math.cos(gy + m3.userData.ry);          // face normal vs the camera
    const f = nz >= 0 ? nz : -nz * 0.35;
    m3.material.opacity = Math.min(1, (Math.pow(f, 1.5) * 0.95 + 0.05) * gain);
  }
  H2.r.render(H2.scene, H2.cam);
}

function hfStart(el, w, h){
  hfWant = true;
  hfInit().then(() => {
    if (!hfWant) return;                               // stopped while initializing — stay down
    hfAttach(el, w, h);
    if (!hfRaf) hfRaf = requestAnimationFrame(hfTick);
  }).catch(e => {
    console.warn('[eyes] holoface init failed:', e);
    try { document.body.classList.remove('jface'); } catch (_){}
    try { if (J) J.voice('My holographic face would not form, sir — the reactor stays.'); } catch (_){}
  });
}
function hfStop(){
  hfWant = false;
  cancelAnimationFrame(hfRaf); hfRaf = 0;
  if (HF && HF.r.domElement.parentNode) HF.r.domElement.parentNode.removeChild(HF.r.domElement);
  if (HF && HF.vid) try { HF.vid.pause(); } catch (_){}
  hfMountEl = null;
}

/* ONE face, ONE place — the reactor's spot. The old top-right card kept colliding with
   the FILTER panel and the ring (his S17c verdict: "in a frame, half cut off, on top of
   Jarvis") so it is GONE. Rules: avatar=face → the face holds the reactor spot full-time;
   avatar=orb (default) → the ring normally, and the face TAKES the spot while EYES is on
   (eyes close → ring returns). "hide your face" disables the swap entirely. */
function applyAvatar(){
  // S18: three MANUAL modes, picked any time (no longer gated on EYES):
  // orb = the classic reactor ring · cube = the spinning glass block · portrait = the flat face
  const showFace = facePref && avatarPref !== 'orb';
  document.body.classList.toggle('jface', showFace);
  if (showFace) hfStart(document.getElementById('jarvisAvatar'), 204, 204);
  else hfStop();
  pickSync();
  return showFace;
}
const AV_LINES = { orb: 'The reactor is back, sir.', cube: 'The cube it is, sir.', portrait: 'Just my face, sir — watching.' };
function setAvatar(mode, quiet){
  avatarPref = mode === 'cube' || mode === 'face' ? 'cube' : (mode === 'portrait' ? 'portrait' : 'orb');
  try { localStorage.setItem('jarvis-avatar', avatarPref); } catch (_){}
  evLog('avatar-' + avatarPref);
  applyAvatar();
  if (!quiet) try { if (J) J.voice(AV_LINES[avatarPref]); } catch (_){}
}
function setFacePref(on){
  facePref = !!on;
  try { localStorage.setItem('jarvis-face', on ? '1' : '0'); } catch (_){}
  applyAvatar();
  evLog(on ? 'face-on' : 'face-off');
}

/* ---------- UI + routes ---------- */
const css = document.createElement('style');
css.textContent = `
  #eyesChip, #watchChip { position:fixed; right:34px; width:204px; box-sizing:border-box; z-index:60;
    cursor:pointer; user-select:none; display:flex; align-items:center; justify-content:space-between;
    font:11px ui-monospace,Menlo,monospace; letter-spacing:.14em; padding:9px 14px; border-radius:12px;
    color:#9adbe8; background:rgba(8,16,20,.78); border:1px solid rgba(64,224,255,.28);
    backdrop-filter:blur(8px); transition:border-color .25s, box-shadow .25s, color .25s; }
  #eyesChip { top:calc(46% + 236px); } #watchChip { top:calc(46% + 280px); }
  #eyesChip::after, #watchChip::after { content:attr(data-state); font-size:9px; letter-spacing:.18em;
    color:#5a7d8a; }
  #eyesChip.on, #watchChip.on { color:#40e0ff; border-color:rgba(64,224,255,.8);
    box-shadow:0 0 18px rgba(64,224,255,.28), inset 0 0 14px rgba(64,224,255,.06); }
  #eyesChip.on::after, #watchChip.on::after { color:#7dffd9; text-shadow:0 0 8px rgba(125,255,217,.6); }
  #jarvisAvatar { position:fixed; right:34px; top:calc(46% - 14px); transform:translateY(-50%); width:204px; height:204px;
    z-index:54; display:none; pointer-events:none; }
  body.jface #jarvisAvatar { display:block; }
  body.jface #j-orb { display:none !important; }
  #avatarPick { position:fixed; right:34px; top:calc(46% + 148px); width:204px; z-index:60;
    display:flex; gap:6px; justify-content:center; }
  #avatarPick b { font:9px ui-monospace,Menlo,monospace; letter-spacing:.16em; cursor:pointer;
    color:#5a7d8a; padding:4px 9px; border:1px solid rgba(64,224,255,.22); border-radius:8px;
    background:rgba(8,16,20,.72); user-select:none; font-weight:600; }
  #avatarPick b.on { color:#40e0ff; border-color:rgba(64,224,255,.8);
    box-shadow:0 0 10px rgba(64,224,255,.25); }`;
document.head.appendChild(css);
const chipE = document.createElement('div'); chipE.id = 'eyesChip'; chipE.textContent = 'EYES'; chipE.dataset.state = 'off';
chipE.title = 'Jarvis can see you — on-device, frames never leave this machine';
const chipW = document.createElement('div'); chipW.id = 'watchChip'; chipW.textContent = 'WATCH'; chipW.dataset.state = 'off';
chipW.title = "Jarvis watches your screen — local diffing; one frame leaves only when he speaks up";
const avEl = document.createElement('div'); avEl.id = 'jarvisAvatar';   // the face's ONE home: the reactor's spot
const pickEl = document.createElement('div'); pickEl.id = 'avatarPick';   // S18: his manual 3-way choice, always on screen
pickEl.innerHTML = '<b data-m="orb">RING</b><b data-m="cube">CUBE</b><b data-m="portrait">FACE</b>';
pickEl.querySelectorAll('b').forEach(b2 => { b2.onclick = () => setAvatar(b2.dataset.m); });
function pickSync(){
  try { pickEl.querySelectorAll('b').forEach(b2 => b2.classList.toggle('on', b2.dataset.m === avatarPref)); } catch (_){}
}
video = document.createElement('video'); video.muted = true; video.playsInline = true;
document.body.append(chipE, chipW, avEl, pickEl);
pickSync();
chipE.onclick = () => ON ? disable() : enable();
chipW.onclick = () => WATCH.on ? watchOff() : watchOn();

const R = (window.__jarvisRoutes = window.__jarvisRoutes || []);
// S19t: "no Jarvis, I need to do something important" — the nudge-relief valve (only while
// an eye organ is open; a real RegExp with a gated test so ask()'s q.match still works)
const CAM_Q = /^(?![\s\S]*\bscreens?\b)[\s\S]*?\b(?:what do you (?:think|make) (?:about|of)|do you like (?:it|this|that|my|the|what)|how (?:do i|does (?:this|it|that)) look|(?:can|could|do) you (?:see|tell|notice) (?:me|what|it|this|that|my|the|anything|if)|(?:are|can) you (?:seeing|watching|looking at) me|what (?:am i|is in my hand|do i have)(?: holding| wearing| in my hand)?|what(?:'s| is) (?:in my hand|on my (?:face|head|shirt|desk)))\b/i;
const camGate = new RegExp(CAM_Q.source, CAM_Q.flags);
camGate.test = (s) => ON && CAM_Q.test(s);                // an EYES feature: only while the eyes are open
const RELIEF_RE = /^(?:okay |ok |no )?(?:jarvis[,:]? )?(?:i need to (?:do|check|handle|finish) (?:something|this)(?: important| real quick)?|this is important|i need a (?:minute|moment|second)|give me a (?:minute|moment|sec(?:ond)?)|i(?:'m| am) doing something important|it'?s important)[.!?]*$/i;
const reliefGate = new RegExp(RELIEF_RE.source, RELIEF_RE.flags);
reliefGate.test = (s) => ON && RELIEF_RE.test(s);        // an EYES feature (S19u)
R.push(
  { re: reliefGate, handler: () => {
      quietUntil = performance.now() + RELIEF_MS;
      try { if (J) J.voice('Very good, sir — I shall hold my tongue for a few minutes.'); } catch (_){}
    } },
  { re: /^(?:jarvis[,:]? )?eyes (?:on|open)$/i, handler: () => enable() },
  { re: /^(?:jarvis[,:]? )?eyes (?:off|closed?)$/i, handler: () => disable() },
  { re: /^(?:jarvis[,:]? )?look at me\b.*$/i, handler: (q) => lookAndAnswer(q || 'What do you see? Anything to comment on?') },
  // S20b (his field round: "can you see what I'm holding" / "s what do you think about the shirt…
  // do you like it" / "can you see what shirt I'm wearing" all fell to the chat brain, which said
  // "I have no eyes"): while EYES is OPEN, any natural camera question is answered by a LOOK.
  // Unanchored on purpose (the ^-anchored route above missed a stray leading token); screen
  // questions are excluded so SEE/WATCH keep them; gated on ON so with the eyes shut nothing
  // switches the webcam on behind his back (the brain answers honestly instead).
  { re: camGate, handler: (q) => lookAndAnswer(q) },
  { re: /^(?:jarvis[,:]? )?(?:what do you (?:think|make) (?:about|of)|how (?:do i|does this) look|rate (?:this|my))(?!.*screen)\b.*$/i,
    handler: (q) => lookAndAnswer(q) },
  { re: /^(?:jarvis[,:]? )?(?:watch my screen|keep an eye on my screen|screen watch on)$/i, handler: () => watchOn() },
  { re: /^(?:jarvis[,:]? )?(?:stop watching(?: my screen)?|screen watch off)$/i, handler: () => watchOff() },
  { re: /^(?:jarvis[,:]? )?(?:show (?:me )?your face|face on)$/i,
    handler: () => { setFacePref(true); try { if (J) J.voice(ON || avatarPref === 'face' ? 'There I am, sir.' : 'My face will take the reactor when my eyes open, sir.'); } catch (_){} } },
  { re: /^(?:jarvis[,:]? )?(?:hide your face|face off)$/i,
    handler: () => { if (avatarPref === 'face') setAvatar('orb'); else { setFacePref(false); try { if (J) J.voice('As you wish, sir — the ring keeps the watch.'); } catch (_){} } } },
  { re: /^(?:jarvis[,:]? )?(?:use (?:your|the) (?:cube|block)|use your face|spinning face)$/i,
    handler: () => setAvatar('cube') },
  { re: /^(?:jarvis[,:]? )?(?:use (?:your|the) (?:portrait|picture|flat face)|just your face)$/i,
    handler: () => setAvatar('portrait') },
  { re: /^(?:jarvis[,:]? )?(?:use the (?:orb|ring)|bring back the (?:orb|ring)|orb instead|reactor orb)$/i,
    handler: () => setAvatar('orb') }
);
setTimeout(() => applyAvatar(), 400);              // a persisted avatar=face boots straight onto the reactor
(function waitJ(){ const w = setInterval(() => { if (window.__jarvis){ J = window.__jarvis; clearInterval(w); } }, 800); })();
// S23: ?eyes no longer opens the camera — a link in an email could carry ?eyes&mute. The EYES card or "eyes on" only.

/* ---------- ?eyesdebug=1 — the field bug report (holodebug law: tune from numbers, never blind) */
if (Q.has('eyesdebug')){
  const dbg = document.createElement('div');
  dbg.id = 'eyesDbg';
  dbg.style.cssText = 'position:fixed;left:14px;bottom:14px;z-index:80;font:10.5px ui-monospace,Menlo,monospace;' +
    'color:#9adbe8;background:rgba(6,12,16,.82);border:1px solid rgba(64,224,255,.35);border-radius:10px;' +
    'padding:8px 11px;white-space:pre;pointer-events:none;line-height:1.5;';
  document.body.appendChild(dbg);
  setInterval(() => {
    let pAmp = 0, yAmp = 0;
    if (headHist.length > 1){
      let pMin = 1e9, pMax = -1e9, yMin = 1e9, yMax = -1e9;
      for (const h of headHist){ pMin = Math.min(pMin, h.pitch); pMax = Math.max(pMax, h.pitch);
                                 yMin = Math.min(yMin, h.yaw); yMax = Math.max(yMax, h.yaw); }
      pAmp = pMax - pMin; yAmp = yMax - yMin;
    }
    dbg.textContent =
      `EYES ${ON ? 'on' : 'off'}  face ${F.present ? 1 : 0}/${F.faces}  look ${F.looking ? 1 : 0}  held ${held ? 1 : 0}\n` +
      `yaw ${F.yaw.toFixed(1)}  pitch ${F.pitch.toFixed(1)}  blink ${F.blink.toFixed(2)}  brow ${(F.brow || 0).toFixed(2)}  smile ${(F.smile || 0).toFixed(2)}\n` +
      `armed ${armedCache ? 1 : 0}  nodwin p${pAmp.toFixed(1)}° y${yAmp.toFixed(1)}°  base ${(baseH || 0).toFixed(3)}\n` +
      `watch ${WATCH.on ? 1 : 0}  static ${WATCH.staticSince ? Math.round((performance.now() - WATCH.staticSince) / 1000) + 's' : '—'}  face ${facePref ? avatarPref : 'off'}${document.body.classList.contains('jface') ? '·live' : ''}\n` +
      `ev ${EV.slice(-4).map(e => e.n).join(' · ') || '—'}`;
  }, 200);
}

/* ---------- dev hooks + ?eyesprobe=1 battery (pure-math drive, no camera) ---------- */
window.__eyesG = { enable, disable, analyze, tick, F, say, cool, CAM_Q, grabFrame, lookAndAnswer,
  watchAssess, watchOn, watchOff, WATCH, applyAvatar, setFacePref, setAvatar, hfInit, faceMoodReq,
  _hf: () => HF, _hfTick: (ts) => { cancelAnimationFrame(hfRaf); hfRaf = 1; hfTick(ts); cancelAnimationFrame(hfRaf); hfRaf = 0; },
  state: () => ({ on: ON, looking: F.looking, present: F.present, watch: WATCH.on,
                  face: facePref, avatar: avatarPref, jface: document.body.classList.contains('jface'),
                  yaw: +F.yaw.toFixed(1), pitch: +F.pitch.toFixed(1), ev: EV.map(e => e.n) }) };
if (PROBE) setTimeout(async () => {
  const R2 = [];
  const ok = (n, c) => R2.push((c ? 'PASS:' : 'FAIL:') + n);
  const ahCalls = [];                                     // hermetic: attention holds land here, never on the page
  window.__eyesTestAH = (on) => ahCalls.push(on);
  const askCalls = [];                                    // hermetic: nod/shake injections land here, never in chat
  window.__eyesTestAsk = (t) => askCalls.push(t);
  const mkRes = (o) => ({
    faceLandmarks: [Object.assign(Array.from({ length: 478 }, () => ({ x: .5, y: .5, z: 0 })),
      { 10: { x: .5, y: .4 - (o.faceH ?? .3) / 2, z: 0 }, 152: { x: .5, y: .4 + (o.faceH ?? .3) / 2, z: 0 } })],
    facialTransformationMatrixes: [{ data: (() => {
      const yaw = (o.yaw ?? 0) * Math.PI / 180, pitch = (o.pitch ?? 0) * Math.PI / 180;
      const m = new Array(16).fill(0);
      m[8] = -Math.sin(yaw) * Math.cos(pitch); m[10] = Math.cos(yaw) * Math.cos(pitch);
      m[9] = Math.sin(pitch); m[0] = 1; m[5] = 1; m[15] = 1;
      return m; })() }],
    faceBlendshapes: [{ categories: [
      { categoryName: 'eyeBlinkLeft', score: o.blink ?? 0 },
      { categoryName: 'eyeBlinkRight', score: o.blink ?? 0 },
      { categoryName: 'browDownLeft', score: o.brow ?? 0 },
      { categoryName: 'browDownRight', score: o.brow ?? 0 },
      { categoryName: 'mouthSmileLeft', score: o.smile ?? 0 },
      { categoryName: 'mouthSmileRight', score: o.smile ?? 0 }] }],
  });
  try {
    let t0 = 1000000;
    // attention: straight-on = looking; hard turn = not
    analyze(mkRes({ yaw: 0, pitch: 0 }), t0);
    const lookedStraight = F.looking;
    analyze(mkRes({ yaw: 55 }), t0 + 33);
    ok('attention', lookedStraight && !F.looking);
    // greeting fires on arrival + eye contact (attention-gated)
    F.present = false; F.lastSeen = -9e9; greetArmed = true; delete cool.greet;
    analyze(mkRes({ yaw: 0 }), t0 += 1000); tick(t0);
    ok('greet', EV.some(e => e.n === 'greet'));
    // PERCLOS drowsy: a minute of mostly-closed eyes
    perclos.length = 0; delete cool.drowsy;
    for (let k = 0; k < 80; k++){ analyze(mkRes({ blink: .9, yaw: 0 }), t0 += 900); tick(t0); }
    ok('drowsy', EV.some(e => e.n === 'drowsy'));
    // slouch: calibrate upright, then lean in hard for 20s
    baseH = null; baseN = 0; slouchSince = 0; delete cool.slouch;
    for (let k = 0; k < 150; k++){ analyze(mkRes({ faceH: .3, yaw: 0 }), t0 += 100); tick(t0); }
    for (let k = 0; k < 30; k++){ analyze(mkRes({ faceH: .44, yaw: 0 }), t0 += 1000); tick(t0); }
    ok('slouch', EV.some(e => e.n === 'slouch'));
    // phone: head down past the demo sustain (S19p: 2s)
    phoneSince = 0; delete cool.phone;
    for (let k = 0; k < 6; k++){ analyze(mkRes({ pitch: -45 }), t0 += 1000); tick(t0); }
    ok('phone', EV.some(e => e.n === 'phone'));
    // nudge cooldown: a repeat inside NUDGE_GAP_MS must NOT fire
    const evN = EV.filter(e => e.n === 'phone').length;
    phoneSince = 0;
    for (let k = 0; k < 15; k++){ analyze(mkRes({ pitch: -45 }), t0 += 1000); tick(t0); }
    ok('cooldown', EV.filter(e => e.n === 'phone').length === evN);
    // relief valve (S19t): "I need to do something important" silences every nudge, then expires
    const evQ = EV.filter(e => e.n === 'phone').length;
    quietUntil = performance.now() + 600000;
    phoneSince = 0; delete cool.phone;
    for (let k = 0; k < 6; k++){ analyze(mkRes({ pitch: -45 }), t0 += 1000); tick(t0); }
    const heldQuiet = EV.filter(e => e.n === 'phone').length === evQ;
    quietUntil = 0;
    phoneSince = 0; delete cool.phone;
    for (let k = 0; k < 6; k++){ analyze(mkRes({ pitch: -45 }), t0 += 1000); tick(t0); }
    ok('relief', RELIEF_RE.test('no jarvis, I need to do something important') &&
       RELIEF_RE.test('give me a minute') && RELIEF_RE.test('this is important') &&
       !RELIEF_RE.test('what do you think of this') && heldQuiet &&
       EV.filter(e => e.n === 'phone').length === evQ + 1);
    // routes: the vision questions match, screen questions do NOT
    const rr = R.map(r => r.re);
    const hit = (s) => rr.some(re => re.test(s));
    ok('routes', hit('look at me') && hit('what do you think of this shirt') &&
      !hit('what do you think of this screen'));
    // S20b: his exact field phrasings (from the episodes ledger) all reach the camera matcher;
    // screen phrasings never do; and with EYES shut the gated route stays closed (no webcam
    // wake behind his back — the chat brain answers honestly instead)
    const camHits = ["can you see what I'm holding here in my hand",
                     "s what do you think about the shirt that I'm wearing right now do you like it",
                     "can you see what shirt I'm wearing", "can you see me", "do you like it",
                     "how do I look", "what am I holding", "jarvis, can you tell what I'm wearing"];
    const camMiss = ["can you see my screen", "what do you think of this screen", "look at my screen",
                     "what's on my screen", "thirty minutes on this", "switch your brain to opus"];
    ok('cam-routes', camHits.every(s => CAM_Q.test(s)) && camMiss.every(s => !CAM_Q.test(s)) &&
       !ON && !hit('can you see me') && !hit("can you see what I'm holding"));
    // ---- v2 battery ----
    // nod = yes while a confirm is armed (temp armed-style route, same shape the bays use)
    const tmpRoute = { re: /^lock it in$/i, handler: () => {} };
    (window.__jarvisRoutes = window.__jarvisRoutes || []).push(tmpRoute);
    t0 += 3000; armedAt = 0;                              // clear refractory + armed cache
    const nods = [2, -7, 2, -8, 1, -7, 2, -8, 1, -7];
    for (const p of nods){ analyze(mkRes({ pitch: p, yaw: 0 }), t0 += 130); tick(t0); }
    ok('nod', askCalls[askCalls.length - 1] === 'do it' && EV.some(e => e.n === 'nod'));
    // head-shake = no
    t0 += 3000; armedAt = 0;
    const shakes = [0, 10, -5, 9, -6, 8, -5, 9, -6, 8];
    for (const y of shakes){ analyze(mkRes({ yaw: y, pitch: 0 }), t0 += 130); tick(t0); }
    ok('shake', askCalls[askCalls.length - 1] === 'cancel' && EV.some(e => e.n === 'shake'));
    // nothing armed → a nod must inject NOTHING (never a stray "do it" into chat)
    const ri = window.__jarvisRoutes.indexOf(tmpRoute);
    if (ri >= 0) window.__jarvisRoutes.splice(ri, 1);
    t0 += 3000; armedAt = 0;
    const n1 = askCalls.length;
    for (const p of nods){ analyze(mkRes({ pitch: p, yaw: 0 }), t0 += 130); tick(t0); }
    ok('unarmed', askCalls.length === n1);
    // attention: away >0.9s mid-speech → hold(true); eye contact → hold(false)
    t0 += 3000;
    analyze(mkRes({ yaw: 0 }), t0 += 100); tick(t0);      // looking (releases any stale hold)
    const a0 = ahCalls.length;
    analyze(mkRes({ yaw: 60 }), t0 += 100); tick(t0);     // away — timer starts
    analyze(mkRes({ yaw: 60 }), t0 += 1200); tick(t0);    // still away past 900ms → hold
    analyze(mkRes({ yaw: 0 }), t0 += 300); tick(t0);      // back → release
    ok('attnhold', ahCalls.slice(a0).join(',') === 'true,false');
    // frown at a fresh answer → the retry offer
    window.__jarvisShownAt = Date.now(); delete cool.frown; frownSince = 0;
    for (let k = 0; k < 14; k++){ analyze(mkRes({ brow: .8, yaw: 0 }), t0 += 260); tick(t0); }
    ok('frown', EV.some(e => e.n === 'frown'));
    // smile at a fresh answer → one positive episode, once per answer
    window.__jarvisShownAt = Date.now() - 2000; smileShown = 0; smileSince = 0;
    for (let k = 0; k < 10; k++){ analyze(mkRes({ smile: .8, yaw: 0 }), t0 += 260); tick(t0); }
    const smiles1 = EV.filter(e => e.n === 'smile').length;
    for (let k = 0; k < 10; k++){ analyze(mkRes({ smile: .8, yaw: 0 }), t0 += 260); tick(t0); }
    ok('smile', smiles1 === 1 && EV.filter(e => e.n === 'smile').length === 1);
    // screen watch: fires once past the stare threshold, holds through the cooldown,
    // refires after — derived from the constants so demo re-tuning can't break the probe
    let tw = 5e6; WATCH.staticSince = 0; WATCH.cool = -9e9;
    let fires = 0;
    watchAssess(.5, tw);                                   // motion — baseline reset
    const stareTicks = Math.ceil(WATCH_STARE_MS / 5000) + 2;
    for (let k = 0; k < stareTicks; k++){ tw += 5000; if (watchAssess(.005, tw)) fires++; }
    const firesA = fires;
    for (let k = 0; k < 3; k++){ tw += 5000; if (watchAssess(.005, tw)) fires++; }    // inside cooldown
    const firesB = fires;
    const moreTicks = Math.ceil((WATCH_COOL_MS + WATCH_STARE_MS) / 5000) + 4;
    for (let k = 0; k < moreTicks; k++){ tw += 5000; if (watchAssess(.005, tw)) fires++; }
    ok('stare', firesA === 1 && firesB === 1 && fires >= 2);
    // new routes: watch / size / face phrasings land, and only the anchored forms
    const rr2 = R.map(r => r.re);
    const hit2 = (s) => rr2.some(re => re.test(s));
    ok('watchroutes', hit2('watch my screen') && hit2('stop watching') &&
      hit2('hide your face') && hit2('show your face') && hit2('use your face') &&
      hit2('bring back the orb') && !hit2('watch my screen recording setup'));
    // HOLOFACE: pure build+compute on synthetic geometry — voice opens the jaw, blinks close the eye
    const g9 = (() => {
      const pts = [];
      for (let i = 0; i < 24; i++) pts.push([.3 + (i % 6) * .08, .2 + Math.floor(i / 6) * .15, .01 * i]);
      const edges = []; for (let i = 0; i < 23; i++) edges.push([i, i + 1]);
      // lips span TWO rows so a "lower half" exists for the jaw (one-row lips = empty set = 0 drop)
      return { pts, edges, lips: [12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23], le: [0, 1, 6, 7], re: [4, 5, 10, 11],
               li: [0], ri: [4], oval: [0, 5, 18, 23] };
    })();
    const stH = hfBuild(g9, g9.pts.map(() => [.5, .8, 1]));
    hfLvS = 0;
    const quietC = hfCompute(stH, 1000, 0, 0, null).slice();
    let loudC; for (let k = 0; k < 12; k++) loudC = hfCompute(stH, 1000 + k * 16, .9, 0, null);
    const meanY = (arr, set) => set.reduce((a2, i) => a2 + arr[i * 3 + 1], 0) / set.length;
    const jawDrop = meanY(quietC, stH.lower) - meanY(loudC, stH.lower);
    hfLvS = 0;
    const openC = hfCompute(stH, 2000, 0, 0, null).slice();
    const blinkC = hfCompute(stH, 2000, 0, 1, null);
    const gapOf = (arr) => Math.abs(meanY(arr, [0, 1]) - meanY(arr, [6, 7]));
    ok('holoface', jawDrop > .01 && gapOf(blinkC) < gapOf(openC) * .5);
    // S18 manual modes: cube/portrait show the face regardless of EYES; orb = the ring;
    // "hide your face" (facePref) blocks the swap
    const keepPref = facePref, keepAv = avatarPref;
    facePref = true;
    avatarPref = 'cube'; const cubeOn = applyAvatar() && document.body.classList.contains('jface');
    avatarPref = 'portrait'; const portOn = applyAvatar();
    avatarPref = 'orb'; const orbOff = !applyAvatar() && !document.body.classList.contains('jface');
    facePref = false; avatarPref = 'cube'; const blocked = !applyAvatar();
    facePref = keepPref; avatarPref = keepAv; applyAvatar();
    ok('face', cubeOn && portOn && orbOff && blocked);
  } catch (e){ R2.push('FAIL:exception ' + (e && e.message)); }
  delete window.__eyesTestAH; delete window.__eyesTestAsk;
  const pass = R2.filter(r => r.startsWith('PASS')).length;
  document.title = `EYESPROBE ${pass}/${R2.length} · ` + R2.join(' ');
}, 500);
