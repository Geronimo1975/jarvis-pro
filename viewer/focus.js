// Jarvis V7 — FOCUS SESSIONS (Session 19 + 19b field round). "Jarvis, thirty minutes on
// this" → the server locks the frontmost app as THE TARGET and ticks; this module owns the
// voice routes, the HUD chip in the dock column, the EYES signal feed, and the speaking of
// whatever the server queues (callouts, acks, the report card).
//
// S19b (his field feedback): pause/resume/stop understand many more phrasings and work
// ungated when they name the timer; "call me out every N seconds/minutes" sets the nag
// cadence (re-callouts while a drift PERSISTS); "give me 15 seconds" snoozes the
// commentary; and when SCREEN WATCH starts, Jarvis offers deep work ("Are we doing deep
// work, sir?") — "yes" inside the window starts 30 minutes.
//
// PRIVACY LAW (client half): the target app id NEVER reaches this page. /focus/state is
// booleans and counters; renderFocus() reads a hard whitelist of keys so even a hostile
// payload can't smuggle an app name onto the chip; the EYES feed we POST is exactly
// {present, down} — two booleans, nothing else.
// Zero-key: every line spoken here originates in the server's canned pools or the tiny
// canned strings below. No model is consulted.
'use strict';

const Q = new URLSearchParams(location.search);
const PROBE = Q.has('focusprobe');

let J = null;
(function waitJ(){ const w = setInterval(() => { if (window.__jarvis){ J = window.__jarvis; clearInterval(w); } }, 800); })();

const FS = { on: false, paused: false, sergeant: false, last: null, pollId: 0 };
const OFFER_WINDOW_MS = 45000;    // how long "yes" counts after the deep-work offer
const OFFER_COOL_MS = 600000;     // don't re-offer on every share toggle

function spk(t, panel){
  const f = window.__focusTestSpk;
  if (f){ f(t, !!panel); return null; }
  if (PROBE) return null;                              // battery runs silent
  try {
    if (J){ return panel && J.say ? J.say(t) : (J.voice ? J.voice(t) : null); }
  } catch (_){}
  return null;
}

async function jpost(p, body){
  try {
    const r = await fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                               body: JSON.stringify(body || {}) });
    return await r.json();
  } catch (_){ return null; }
}

/* ---------- pure helpers (the probe drives these directly) ---------- */
const NUMW = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9,
  ten: 10, eleven: 11, twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16,
  seventeen: 17, eighteen: 18, nineteen: 19, twenty: 20, thirty: 30, forty: 40, fifty: 50,
  sixty: 60, seventy: 70, eighty: 80, ninety: 90 };
function parseMin(s){
  if (!s) return null;
  s = String(s).toLowerCase().replace(/-/g, ' ').replace(/\s+/g, ' ').trim();
  if (/^\d+$/.test(s)){ const n = parseInt(s, 10); return n > 0 ? n : null; }
  if (/^(?:an?|one) hour$/.test(s)) return 60;
  if (/^half an hour$/.test(s)) return 30;
  const w = s.split(' ');
  if (w.length === 1 && NUMW[w[0]]) return NUMW[w[0]];
  if (w.length === 2 && NUMW[w[0]] >= 20 && NUMW[w[1]] && NUMW[w[1]] < 10) return NUMW[w[0]] + NUMW[w[1]];
  return null;
}
function fmt(ms){
  ms = Math.max(0, ms | 0);
  return Math.floor(ms / 60000) + ':' + String(Math.floor((ms % 60000) / 1000)).padStart(2, '0');
}
function renderFocus(st){
  // WHITELIST READER: on, paused, remain_ms, on_target — nothing else can reach the chip.
  if (!st || !st.on) return { text: 'off', on: false, drift: false };
  const t = fmt(st.remain_ms | 0);
  if (st.paused) return { text: '❚❚ ' + t, on: true, drift: false };
  if (!st.on_target) return { text: '⚠ ' + t, on: true, drift: true };
  return { text: t, on: true, drift: false };
}
function eyesSnap(){
  // the signal feed: EXACTLY three booleans — camera presence, phone posture (head-down
  // past -35°), and the SHARE LOCK verdict. Camera off → neutral values, never accusations.
  const e = window.__eyes;
  const cam = !!(e && e.on);
  if (!cam && !LOCK.on) return null;
  return { present: cam ? !!e.present : true,
           down: cam ? ((typeof e.pitch === 'number' ? e.pitch : 0) < -35) : false,
           screen_off: LOCK.on ? !!LOCK.off : false };
}

/* ---------- SHARE LOCK (S19c): "lock this tab/window/screen" — pixel accountability ------
   He picks a surface via getDisplayMedia (or we ride the live WATCH share); a 128×10
   thumbnail of the TOP STRIP (menu bar + tab strip — scrolling the work page never touches
   it, switching tabs/apps always does) is diffed locally ~1.2s against a reference taken at
   lock time. PIXELS NEVER LEAVE THE PAGE — the server only ever sees the screen_off boolean.
   An excuse re-references: "I'm researching on this tab" makes THIS view the new normal. */
const LOCK = { on: false, stream: null, video: null, cv: null, cx: null, ref: null,
               off: false, offN: 0, iv: 0, own: false, lastDiff: 0 };
// S19f (his monitor-share test stayed silent): a real tab switch only moves ~1-2% of the
// strip's pixels — a MEAN-delta metric at .10 could never fire. The metric is now the
// FRACTION OF CHANGED PIXELS (each must move > PX_DELTA), gated low.
const LOCK_TICK_MS = 1200, STRIP_GATE = 0.035, PX_DELTA = 0.12, LOCK_OFF_N = 2, STRIP_W = 128, STRIP_H = 10;
const STRIP_SPAN = 0.90;   // left 90% of the frame — excludes the facewin card, the menu-bar
                           // clock, and macOS notification banners (all top-RIGHT churn)
function stripDiff(a, b){                                  // pure — probed
  if (!a || !b || a.length !== b.length) return 0;
  let n = 0;
  for (let i = 0; i < a.length; i++) if (Math.abs(a[i] - b[i]) > PX_DELTA) n++;
  return n / a.length;
}
function lockJudge(d){                                     // pure state step — probed
  if (d > STRIP_GATE){ LOCK.offN++; if (LOCK.offN >= LOCK_OFF_N) LOCK.off = true; }
  else { LOCK.offN = 0; LOCK.off = false; }
  return LOCK.off;
}
function stripThumb(){
  const v = LOCK.video;
  if (!v || v.readyState < 2 || !v.videoWidth) return null;
  LOCK.cx.drawImage(v, 0, 0, Math.round(v.videoWidth * STRIP_SPAN),
                    Math.max(1, Math.round(v.videoHeight * 0.09)),
                    0, 0, STRIP_W, STRIP_H);
  const d = LOCK.cx.getImageData(0, 0, STRIP_W, STRIP_H).data;
  const g = new Float32Array(STRIP_W * STRIP_H);
  for (let i = 0; i < g.length; i++){ const j = i * 4; g[i] = (d[j] + d[j + 1] + d[j + 2]) / 765; }
  return g;
}
function lockSample(){
  const t = stripThumb();
  if (!t) return;
  if (!LOCK.ref){
    LOCK.ref = t;
    // S19m: the click happens ON the Jarvis tab, so the first reference is the Jarvis view —
    // not the work. Remember that, and re-reference the moment he leaves for the real work.
    LOCK.refWhileVisible = document.visibilityState === 'visible';
    return;
  }
  if (LOCK.refWhileVisible && document.hidden){
    lockRef();                                             // next frame = the WORK surface
    LOCK.refWhileVisible = false;
    return;
  }
  LOCK.lastDiff = stripDiff(LOCK.ref, t);
  lockJudge(LOCK.lastDiff);
}
function lockRef(){ LOCK.ref = null; LOCK.off = false; LOCK.offN = 0; }   // next frame = new normal
function surfaceVerdict(surface){                          // pure — probed
  // 'monitor' has the menu bar + tab strip in frame (sees EVERY tab/app change); 'window'
  // sees its own chrome (in-window tab changes). A captured TAB keeps rendering itself
  // while you wander — it can NEVER report a switch, and its top strip is page content
  // (scrolling would read as drift). Never arm pixels on it. (S19e — his skool-tab test.)
  if (surface === 'browser') return { arm: false,
    line: 'A single tab cannot tell me when you abandon it, sir — it keeps playing to me even while you are off gallivanting. Share the Entire Screen and nothing escapes me. Until then I hold you to the app alone.' };
  if (surface === 'window') return { arm: true,
    line: 'Locked on that window, sir — I will catch what changes inside it. Share the entire screen next time and nothing gets past me.' };
  return { arm: true,
    line: 'Locked on your entire screen, sir — tabs, windows, all of it. Stray and I will know.' };
}
async function lockOn(quietFail, defer){
  // defer: don't speak or start — hand the verdict line back so the caller composes ONE
  // ack through the server's say queue (the two-Jarvises fix: a single voice door)
  if (LOCK.on){ if (!defer) spk('Already locked on, sir.'); return defer ? { locked: true, line: null } : true; }
  try {
    const W = window.__eyesG && window.__eyesG.WATCH;      // one share, two organs
    if (W && W.on && W.stream){ LOCK.stream = W.stream; LOCK.own = false; }
    else {
      LOCK.stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 2, displaySurface: 'monitor' },   // the picker OPENS on Entire Screen
        audio: false, preferCurrentTab: false,
        selfBrowserSurface: 'exclude', surfaceSwitching: 'exclude' });
      LOCK.own = true;
    }
    const tr = LOCK.stream.getVideoTracks()[0];
    const surface = (tr && tr.getSettings && tr.getSettings().displaySurface) || 'monitor';
    const v = surfaceVerdict(surface);
    if (!v.arm){                                           // a tab share can't police tabs — be honest
      if (LOCK.own){ try { for (const t of LOCK.stream.getTracks()) t.stop(); } catch (_){} }
      LOCK.stream = null; LOCK.own = false;
      if (defer) return { locked: false, line: v.line };
      spk(v.line);
      if (!FS.on) startSession(30);                        // app-level accountability still counts
      return false;
    }
    LOCK.surface = surface;
    LOCK.video = document.createElement('video'); LOCK.video.muted = true; LOCK.video.playsInline = true;
    LOCK.video.srcObject = LOCK.stream; await LOCK.video.play();
    if (!LOCK.cv){ LOCK.cv = document.createElement('canvas'); LOCK.cv.width = STRIP_W; LOCK.cv.height = STRIP_H;
      LOCK.cx = LOCK.cv.getContext('2d', { willReadFrequently: true }); }
    lockRef();
    LOCK.iv = setInterval(lockSample, LOCK_TICK_MS);
    if (tr) tr.addEventListener('ended', () => lockOff(true));
    LOCK.on = true;
    if (defer) return { locked: true, line: v.line };
    spk(v.line);
    if (!FS.on) startSession(30);                          // one gesture = accountable
    return true;
  } catch (_){
    // Chrome only opens the share picker from a real CLICK — a voice command isn't a user
    // gesture. The FOCUS button is the guaranteed path; say so instead of a dead "no".
    if (defer) return { locked: false, line: null };
    if (!quietFail) spk('The browser wants a click for that, sir — press the FOCUS button and pick your surface.');
    return false;
  }
}
function lockOff(quiet){
  if (!LOCK.on) return;
  LOCK.on = false; lockRef();
  if (LOCK.iv){ clearInterval(LOCK.iv); LOCK.iv = 0; }
  try { if (LOCK.own && LOCK.stream) for (const t of LOCK.stream.getTracks()) t.stop(); } catch (_){}
  LOCK.stream = null;
  if (LOCK.video){ LOCK.video.srcObject = null; LOCK.video = null; }
  if (!quiet) spk('The screen lock is off, sir.');
}
addEventListener('pagehide', () => {
  try { if (LOCK.own && LOCK.stream) for (const t of LOCK.stream.getTracks()) t.stop(); } catch (_){}
});

/* ---------- chip (dock column slot under HOLO — 44px rhythm) ---------- */
const css = document.createElement('style');
css.textContent = `
  #focusChip { position:fixed; right:34px; top:calc(46% + 368px); width:204px; box-sizing:border-box;
    z-index:60; cursor:pointer; user-select:none; display:flex; align-items:center; justify-content:space-between;
    font:11px ui-monospace,Menlo,monospace; letter-spacing:.14em; padding:9px 14px; border-radius:12px;
    color:#9adbe8; background:rgba(8,16,20,.78); border:1px solid rgba(64,224,255,.28);
    backdrop-filter:blur(8px); transition:border-color .25s, box-shadow .25s, color .25s; }
  #focusChip::after { content:attr(data-state); font-size:9px; letter-spacing:.18em; color:#5a7d8a; }
  #focusChip.on { color:#40e0ff; border-color:rgba(64,224,255,.8);
    box-shadow:0 0 18px rgba(64,224,255,.28), inset 0 0 14px rgba(64,224,255,.06); }
  #focusChip.on::after { color:#7dffd9; text-shadow:0 0 8px rgba(125,255,217,.6); }
  #focusChip.drift { color:#ffb740; border-color:rgba(255,183,64,.8);
    box-shadow:0 0 18px rgba(255,183,64,.3), inset 0 0 14px rgba(255,183,64,.07); }
  #focusChip.drift::after { color:#ffb740; text-shadow:0 0 8px rgba(255,183,64,.6); }`;
document.head.appendChild(css);
const chipF = document.createElement('div');
chipF.id = 'focusChip'; chipF.textContent = 'FOCUS'; chipF.dataset.state = 'off';
chipF.title = 'Accountability timer — click: share your ENTIRE SCREEN (preselected; Cancel = app-only), then tell Jarvis what you\'re working on when he asks. Voice: "thirty minutes on this" · "keep me accountable, I\'m planning to …" · "lock on this tab" / "keep me in this tab" (re-target from the tab you want, or the ⌖ LOCK THIS TAB pill on the desktop card) · "abort the session". The target and every pixel stay on this machine.';
document.body.appendChild(chipF);
// THE guaranteed activation (S19d/f/g): the click IS the user gesture Chrome demands for
// the share picker; the session starts THE INSTANT the share resolves (countdown + face
// immediately), and the single composed ack ends in "what are we focusing on?" with the
// answer window armed — his reply attaches to the running clock.
async function lockOrStart(){
  // S19s (his call): FOCUS never touches the 👂 — he runs the ear himself; with it on,
  // __focusHot keeps the whole session wake-word-free
  const r = await lockOn(true, true);          // WATCH-reuse or picker; cancel → app-only
  startWithAsk(r && r.line);
}
chipF.onclick = () => { if (FS.on) spk(statusLine()); else lockOrStart(); };

function applyChip(r){
  chipF.dataset.state = r.text;
  chipF.classList.toggle('on', r.on && !r.drift);
  chipF.classList.toggle('drift', !!r.drift);
}

/* ---------- state plumbing ---------- */
function consume(st){
  if (!st || typeof st !== 'object') return;
  FS.last = st; FS.on = !!st.on; FS.paused = !!st.paused; FS.sergeant = !!st.sergeant;
  // S19i (his ask: "it shouldn't rely on me to say Jarvis"): while a session runs the
  // follow-up window never expires — armFollowup stays hot, like the screen-share mode
  try { window.__focusHot = FS.on; } catch (_){}
  applyChip(renderFocus(st));
  const line = typeof st.say === 'string' ? st.say : null;     // whitelist: say is a string or nothing
  if (line){
    const p = spk(line, !!st.report);                          // the report card earns the answer panel
    if (FS.armAsk){                                            // the start ack ends in a QUESTION —
      FS.armAsk = false;                                       // open the no-wake-word answer window
      const arm = () => { try { if (J && J.listen) J.listen(); } catch (_){} };
      if (p && p.then) p.then(arm); else arm();
    }
  }
  if (!st.on){ stopPolling(); if (LOCK.on) lockOff(true); }    // the lock lives and dies with the session
}
const MUTED = Q.has('mute');
async function pollNow(){
  // ⚖ S19l: a MUTED tab must never CLAIM say lines (it would swallow spoken callouts
  // meant for the real tab) — it observes via GET, which claims nothing.
  if (MUTED){
    try { consume(await (await fetch('/focus/state')).json()); } catch (_){}
    return;
  }
  const st = await jpost('/focus/state', { eyes: eyesSnap() });
  consume(st);
}
function startPolling(){
  if (FS.pollId) return;
  FS.pollId = setInterval(pollNow, 650);   // S19n: callouts claim ~0.3s sooner — "immediately"
}
function stopPolling(){
  if (FS.pollId){ clearInterval(FS.pollId); FS.pollId = 0; }
}

function statusLine(){
  const st = FS.last;
  if (!st || !st.on) return 'No focus session running, sir. Say "thirty minutes on this" and we\'ll fix that.';
  const t = fmt(st.remain_ms | 0);
  if (st.paused) return 'Paused with ' + t + ' on the clock, sir.';
  const d = st.drifts | 0;
  return t + ' left, sir — ' + (d ? d + ' drift' + (d === 1 ? '' : 's') + ' on the board.' : 'clean so far.') +
    (st.deferred ? ' I am still waiting for you to settle on your work — go to it and I will lock on.' : '') +
    (st.on_target ? '' : ' And you are adrift at this very moment, as it happens.');
}

/* ---------- actions ---------- */
async function startSession(min, intent, ack){
  if (FS.on){ spk('One session at a time, sir — abort the current one first.'); return; }
  min = Math.max(1, Math.min(240, min || 30));
  // S21 (his call, reverses S19s): every session start opens the 👂 if it is shut (quietly —
  // the start ack is the one voice); never from a muted test tab
  try { if (!MUTED && J && J.hearing && !J.hearing() && J.hear) J.hear(true); } catch (_){}
  const r = await jpost('/focus/start', { minutes: min, intent: intent || null, ack: ack || null });
  if (!r){ spk('The focus bay is not answering, sir.'); return; }
  if (r.error){ spk(r.error === 'already running' ? 'A session is already running, sir.' : 'The focus bay declined, sir.'); return; }
  consume(r); startPolling(); pollNow();
}

/* ---------- the INTENT ask (S19f/g, his spec): the clock starts THE MOMENT the share
   resolves (chip counts, face up — no dead air), the start ack ENDS in the question, and
   consume() arms the no-wake-word answer window (J.listen — the S19g root cause: without
   armFollowup, everything he answered was discarded by the wake recognizer). His answer
   attaches to the RUNNING session via POST /focus/intent and colors the first callout,
   the report card, and the episode. One composed ack = one voice (the two-Jarvises fix). */
let intentUntil = 0, intentTimer = 0, pendingLine = null;
const INTENT_WINDOW_MS = 20000;   // S19o: long windows swallowed mid-session speech as "intent"
const intentOpen = () => performance.now() < intentUntil;
function cleanIntent(s){                                   // pure — probed (S19o: de-ramble dictation)
  s = String(s || '').trim().replace(/[.!?]+$/, '');
  for (let i = 0; i < 4; i++)
    s = s.replace(/^(?:no|yeah|yes|yep|okay|ok|so|well|um|uh|alright|right)[,.]?\s+/i, '');
  s = s.replace(/^(?:i(?:'m| am) (?:trying|going|planning) to |i want to |we(?:'re| are) (?:going|trying) to |let(?:'s| us) )/i, '');
  s = s.replace(/^(?:do |work on |build (?:out )?|focus on )/i, '');
  s = s.replace(/\s+/g, ' ').trim();
  return s.slice(0, 80);
}
// a protest ("no, this IS what I'm working on") while OFF target = an excuse, never an intent
const PROTEST = /^(?:no[,.]? )?(?:this is (?:what|where|the|it|my)|i(?:'m| am) (?:trying|working|looking)|i(?:'m| am) on the right)\b/i;
// S19w (pure — probed): the ONE composed start ack. When the click happens ON the Jarvis
// tab (this document visible), the server DEFERS the tab lock to wherever he settles — so
// the ack must SAY SO, before the question, or he sits on the Jarvis tab wondering why
// nothing locked (and a background window used to get locked for him: the S19m bug).
const DEFER_LINE = 'Go to what you\'re working on and I\'ll lock on there.';
function composeStartAck(lockLine, min, deferring, earN){
  // S21: the ear note rides BEFORE the question — the ack must still END in the question,
  // because the answer window opens the moment it lands
  return (lockLine ? lockLine + ' ' : '') + min + ' minutes on the clock, sir.' +
         (deferring ? ' ' + DEFER_LINE : '') + (earN || '') + ' And what are we focusing on?';
}
function startWithAsk(lockLine, min){
  min = min || 30;
  let earN = '';
  try {
    if (J && J.hearing && !J.hearing()){
      // S21 (his call, reverses S19s): the FOCUS click opens the 👂 itself — quietly, so this
      // ONE ack carries the news (never from a muted test tab); a blocked mic keeps the honest note
      const opened = (!MUTED && J.hear) ? !!J.hear(true) : false;
      earN = opened ? ' Listening mode on.' : ' My ears are off, sir — tap the ear button to answer.';
    }
  } catch (_){}
  const ack = composeStartAck(lockLine, min, !document.hidden, earN);
  FS.armAsk = true;                                       // consume() opens the mic after THIS ack
  intentUntil = performance.now() + INTENT_WINDOW_MS;
  clearTimeout(intentTimer);
  intentTimer = setTimeout(() => { intentUntil = 0; }, INTENT_WINDOW_MS + 500);
  return startSession(min, null, ack);
}
async function setIntent(text){
  clearTimeout(intentTimer); intentTimer = 0; intentUntil = 0;
  if (!text) return;
  const r = await jpost('/focus/intent', { intent: text });   // the "noted, sir" ack rides the queue
  if (r && !r.error) pollNow();
}
function beginSession(min, intent){
  clearTimeout(intentTimer); intentTimer = 0; intentUntil = 0;
  if (FS.on){ pendingLine = null; return; }               // something else already started it
  let ack = null;
  if (pendingLine || intent){
    ack = (pendingLine ? pendingLine + ' ' : '') +
          (intent ? '"' + intent + '" — noted, sir. ' : '') +
          (min || 30) + ' minutes on the clock.';
  }
  pendingLine = null;
  startSession(min || 30, intent, ack);
}
async function stopSession(){
  const r = await jpost('/focus/stop', {});
  if (r && r.error){ spk('No session to abort, sir.'); return; }
  consume(r); pollNow();                                        // the tally line arrives on the claim
}
async function pauseSession(){
  const r = await jpost('/focus/pause', {});
  if (r && r.error){ spk('Nothing to pause, sir — no session on the clock.'); return; }
  if (r){ consume(r); pollNow(); }
}
async function resumeSession(){
  const r = await jpost('/focus/resume', {});
  if (r && r.error){ spk('Nothing paused, sir.'); return; }
  if (r){ consume(r); pollNow(); }
}
async function extendSession(min){
  const r = await jpost('/focus/extend', { minutes: Math.max(1, Math.min(240, min || 10)) });
  if (r && !r.error){ consume(r); pollNow(); }
}
async function setSergeant(on){
  await jpost('/focus/sergeant', { on: !!on });
  FS.sergeant = !!on;
  spk(on ? 'Drill-sergeant mode, sir. May your focus forgive me.' : 'As you were, sir. The butler resumes.');
}
async function setNag(seconds){
  const r = await jpost('/focus/nag', { seconds: seconds });
  if (!r || r.error){ spk('I did not catch the cadence, sir.'); return; }
  // with a session on, the engine's ack rides the poll; otherwise speak it here
  if (!FS.on) spk('Understood, sir — while you\'re adrift I\'ll speak up every ' +
                  (seconds < 60 ? seconds + ' seconds' : Math.round(seconds / 60) + ' minute' + (seconds >= 120 ? 's' : '')) + '.');
}
async function snoozeSession(seconds){
  const r = await jpost('/focus/snooze', { seconds: seconds });
  if (r && r.error) spk('No session running, sir.');
}
async function retargetHere(){                             // S19w
  const r = await jpost('/focus/retarget', {});
  if (!r || r.error){ spk('No session running, sir.'); return; }
  if (LOCK.on) lockRef();          // this view is the new pixel-normal as well
  pollNow();                       // "Locked on, sir." / "Go to it, sir" arrives on the claim
}
async function excuseDrift(){
  const r = await jpost('/focus/excuse', {});
  if (r && r.error){ spk('No session running, sir.'); return; }
  if (LOCK.on) lockRef();          // this view is legitimate — it becomes the new normal
  pollNow();                       // the carry-on ack arrives on the claim
}

/* ---------- voice routes ---------- */
// DND owns "focus mode"/"focus off"/"stop focus"/"exit focus" (the interrupt governor) —
// every start form here REQUIRES a duration, and stop forms REQUIRE a timer noun, so the
// two vocabularies can never collide.
const NUM = '(\\d{1,3}|[a-z]+(?:[ -][a-z]+)?)';
const HOURS = '(half an hour|an hour|one hour)';
const UNIT = '(seconds?|secs?|minutes?|mins?)';
const TNOUN = '(?:session|sprint|timer|clock|countdown)';
const START = new RegExp('^(?:jarvis[,:]? )?(?:(?:start |begin |give me )?(?:a )?focus(?: session| sprint| timer)?(?: for| of)? (?:' + NUM + ' ?(?:minutes?|min)|' + HOURS + ')(?: on this)?|(?:' + NUM + ' ?minutes?|' + HOURS + ') on this(?: one| task| app)?|focus on this for (?:' + NUM + ' ?(?:minutes?|min)|' + HOURS + '))[.!?]*$', 'i');
const STOP = new RegExp('^(?:jarvis[,:]? )?(?:abort|end|cancel|kill|finish|stop) (?:the |this |my )?(?:focus )?' + TNOUN + '[.!?]*$', 'i');
const PAUSE_OBJ = new RegExp('^(?:jarvis[,:]? )?(?:pause|hold) (?:the |this |my )?(?:focus )?' + TNOUN + '[.!?]*$', 'i');
const PAUSE_BARE = /^(?:jarvis[,:]? )?pause(?: it| here)?[.!?]*$/i;
const RESUME_OBJ = new RegExp('^(?:jarvis[,:]? )?(?:resume|continue|unpause|restart) (?:the |this |my )?(?:focus )?' + TNOUN + '[.!?]*$', 'i');
const RESUME_BARE = /^(?:jarvis[,:]? )?(?:resume|unpause|back to work)(?: it)?[.!?]*$/i;
const STATUS = /^(?:jarvis[,:]? )?(?:how (?:am i|are we) doing|how much (?:time(?:'s| is)? left|longer)|time left|focus status|what'?s left on the clock|how(?:'s| is) (?:the|my) (?:focus )?session(?: going)?)[.!?]*$/i;
const EXTEND = new RegExp('^(?:jarvis[,:]? )?(?:' + NUM + ' more minutes?|extend (?:it |the (?:session|timer) )?(?:by )?' + NUM + ' ?minutes?|add ' + NUM + ' ?minutes?)[.!?]*$', 'i');
const SGTON = /^(?:jarvis[,:]? )?(?:(?:be a |go )?drill.?sergeant(?: mode)?(?: on)?|sergeant mode on)[.!?]*$/i;
const SGTOFF = /^(?:jarvis[,:]? )?(?:drill.?sergeant (?:mode )?off|sergeant mode off|ease up|stand easy|back to (?:the )?butler)[.!?]*$/i;
const NAG = new RegExp('^(?:jarvis[,:]? )?(?:call me out|nag(?: me)?|check (?:in )?on me|update me|give me updates) every ' + NUM + ' ?' + UNIT + '[.!?]*$', 'i');
const SNOOZE = new RegExp('^(?:jarvis[,:]? )?(?:give me|gimme) (?:like )?' + NUM + ' ?' + UNIT + '(?: of (?:peace|quiet))?(?:,? ?(?:and )?then (?:give me )?(?:updates?|check on me))?[.!?]*$', 'i');
const OFFER_YES = /^(?:jarvis[,:]? )?(?:yes|yeah|yep|sure|absolutely|indeed|we are|start the clock|let'?s (?:do it|go)|deep work)\b.*$/i;
const OFFER_NO = /^(?:jarvis[,:]? )?(?:no|nope|not now|no thanks,?|negative|later)\b.*$/i;
// S19c: "no Jarvis, it's okay — I'm just doing research on this other tab" → retro-forgive
const EXCUSE = /^(?:no,? )?(?:jarvis[,:]? )?(?:it'?s (?:okay|ok|fine|all ?right)|i'?m (?:still )?(?:working|researching)|(?:i'?m )?(?:just )?doing research(?: on (?:this|that|the)(?: other)? (?:tab|window|app|site))?|this (?:is|counts as) (?:work|research)|i need (?:this|that) (?:tab|window)|(?:excuse|allow) (?:this|that)|this is part of (?:it|the work))\b.*$/i;
// S19w: the explicit RE-TARGET — say it FROM the tab you want ("lock on this tab") and the
// server locks it; say it from the Jarvis tab and the lock re-arms to wherever you land
// next ("Go to it, sir"). Gated on a running session, and placed BEFORE LOCKON so "lock this
// tab" mid-session means the target, not the pixel share. Never "my screen" (that stays LOCKON).
const RETARGET = /^(?:(?:okay|ok|so|alright)[,.]? )?(?:jarvis[,:]? )?(?:i(?:'m| am) (?:gonna|going to) need you to |i need you to |can you |could you |please |go ahead and )?(?:lock (?:on ?to |onto |on )?(?:this|that) (?:tab|one|page|window|app|site)|lock (?:on )?here|(?:this|that) is (?:the (?:right |correct )?(?:tab|one|page|site)|my (?:tab|work(?: tab)?))|focus on (?:this|that) (?:tab|one|page|site)|(?:switch|move|change) (?:the )?(?:lock|target|focus) (?:to )?(?:this tab|this|here)|keep me (?:in|on) (?:this|that) (?:tab|one|page|site|window|app)|keep me (?:here|on it)|(?:stay|stick) (?:in|on|with) (?:this|that) (?:tab|one|page)|hold me (?:to|on|in) (?:this|that) (?:tab|one|page))[.!?]*$/i;
// S19c: SHARE LOCK — pick a tab/window/screen and it becomes pixel-level accountability
const LOCKON = /^(?:jarvis[,:]? )?(?:lock (?:on ?to |onto |on )?(?:this|my|the) (?:screen|tab|window)|watch this (?:tab|window|screen) and keep me (?:accountable|honest|focused))[.!?]*$/i;
// S19f: "keep me accountable — I'm planning to <the work>" carries the intent inline
const KEEPACC = /^(?:jarvis[,:]? )?keep me accountable[,.]?\s*(?:i(?:'m| am) (?:planning|going) to |i (?:will|want to|wanna) |on |for |to )?(.{0,140})$/i;
const LOCKREL = /^(?:jarvis[,:]? )?(?:unlock (?:the |my )?(?:screen|tab|window)|release the (?:screen|tab|window)|screen lock off|stop the screen lock)[.!?]*$/i;

// conditional routes: a real RegExp with a gated test() so ask()'s q.match still works —
// (a duck object here breaks q.match; don't regress it)
function gated(re, cond){
  const r = new RegExp(re.source, re.flags);
  const c = cond || (() => FS.on);
  r.test = (s) => c() && re.test(s);
  return r;
}
function minsFrom(q){
  const m = q.match(START) || q.match(EXTEND);
  if (!m) return null;
  for (let i = 1; i < m.length; i++) if (m[i]){ const n = parseMin(m[i]); if (n) return n; }
  return null;
}
function secsFrom(q, re){
  const m = q.match(re);
  if (!m) return null;
  let n = null, unit = '';
  for (let i = 1; i < m.length; i++){
    if (!m[i]) continue;
    if (/^(seconds?|secs?|minutes?|mins?)$/i.test(m[i])) unit = m[i];
    else if (n == null) n = parseMin(m[i]);
  }
  if (!n) return null;
  return /min/i.test(unit) ? n * 60 : n;
}

/* ---------- the deep-work offer (SCREEN WATCH pings this via window.__focusOffer) ------- */
let offerUntil = 0, offerCool = -9e9;
const offerPending = () => performance.now() < offerUntil;
window.__focusOffer = (src) => {
  const now = performance.now();
  if (FS.on || now - offerCool < OFFER_COOL_MS) return false;
  offerCool = now; offerUntil = now + OFFER_WINDOW_MS;
  spk('Are we doing deep work, sir? Say yes and I shall put thirty minutes on the clock — and keep you honest.');
  return true;
};

const R = (window.__jarvisRoutes = window.__jarvisRoutes || []);
R.push(
  { re: gated(OFFER_YES, offerPending), handler: async () => {
      offerUntil = 0;
      // the offer fires from a live WATCH share — a yes locks onto it (no picker needed);
      // the offer already asked its question, so no intent interrogation here
      const r = await lockOn(true, true);
      pendingLine = (r && r.line) || null;
      beginSession(30, null);
    } },
  { re: gated(OFFER_NO, offerPending), handler: () => { offerUntil = 0; spk('Very good, sir. The clock stays in its drawer.'); } },
  { re: START, handler: (q) => { const n = minsFrom(q); if (n) startSession(n); else spk('For how many minutes, sir?'); } },
  { re: STOP, handler: () => stopSession() },
  { re: PAUSE_OBJ, handler: () => pauseSession() },
  { re: gated(PAUSE_BARE), handler: () => pauseSession() },
  { re: RESUME_OBJ, handler: () => resumeSession() },
  { re: gated(RESUME_BARE), handler: () => resumeSession() },
  { re: gated(STATUS), handler: () => spk(statusLine()) },
  { re: gated(EXTEND), handler: (q) => { const n = minsFrom(q); if (n) extendSession(n); } },
  { re: NAG, handler: (q) => { const s = secsFrom(q, NAG); if (s) setNag(s); else spk('I did not catch the cadence, sir.'); } },
  { re: gated(SNOOZE), handler: (q) => { const s = secsFrom(q, SNOOZE); if (s) snoozeSession(s); } },
  { re: gated(EXCUSE), handler: () => excuseDrift() },
  { re: gated(RETARGET), handler: () => retargetHere() },  // S19w — before LOCKON on purpose
  { re: LOCKON, handler: () => lockOn() },
  { re: gated(LOCKREL, () => LOCK.on), handler: () => lockOff() },
  { re: KEEPACC, handler: async (q) => {
      if (FS.on){ spk('One session at a time, sir.'); return; }
      const m = q.match(KEEPACC);
      let desc = cleanIntent(((m && m[1]) || ''));
      if (/^(?:this|that)(?: (?:tab|window|screen|app|one))?$/i.test(desc)) desc = '';
      const W = window.__eyesG && window.__eyesG.WATCH;
      let line = null;
      if (W && W.on && W.stream){ const r = await lockOn(true, true); line = (r && r.line) || null; }
      if (desc){ pendingLine = line; beginSession(30, desc); }
      else startWithAsk(line);
    } },
  { re: SGTON, handler: () => setSergeant(true) },
  { re: SGTOFF, handler: () => setSergeant(false) },
  // a protest while adrift, any time in the session, is the correction valve (S19o)
  { re: gated(PROTEST, () => FS.on && !intentOpen() && FS.last && FS.last.on_target === false),
    handler: () => excuseDrift() },
  // the intent-answer window (open ~20s after "what are we focusing on?" — the clock is
  // ALREADY RUNNING): a decline just closes the window; a protest while adrift excuses;
  // anything else becomes the work (de-rambled, never parroted back if long)
  { re: gated(/^(?:cancel|never ?mind|skip|no|nothing)[.!?]*$/i, intentOpen),
    handler: () => { clearTimeout(intentTimer); intentTimer = 0; intentUntil = 0; } },
  { re: gated(/^.{3,140}$/i, intentOpen), handler: (q) => {
      if (PROTEST.test(q) && FS.last && FS.last.on_target === false){
        clearTimeout(intentTimer); intentTimer = 0; intentUntil = 0;
        excuseDrift();
        return;
      }
      setIntent(cleanIntent(q));
    } }
);

// a reloaded tab rejoins a running session (the session is server-side; the countdown never
// died) — muted tabs observe without claiming (S19l)
if (!PROBE) setTimeout(async () => {
  let st = null;
  if (MUTED){ try { st = await (await fetch('/focus/state')).json(); } catch (_){} }
  else st = await jpost('/focus/state', { eyes: null });
  if (st && (st.on || st.report)){ consume(st); if (st.on) startPolling(); }
}, 1200);

/* ---------- ?focusdebug=1 — the field bug report (holodebug law: tune from numbers) ------- */
if (Q.has('focusdebug')){
  const dbg = document.createElement('div');
  dbg.style.cssText = 'position:fixed;right:14px;bottom:14px;z-index:80;font:10.5px ui-monospace,Menlo,monospace;' +
    'color:#9adbe8;background:rgba(6,12,16,.82);border:1px solid rgba(64,224,255,.35);border-radius:10px;' +
    'padding:8px 11px;white-space:pre;pointer-events:none;line-height:1.5;';
  document.body.appendChild(dbg);
  setInterval(() => {
    const st = FS.last || {};
    dbg.textContent =
      `FOCUS ${FS.on ? 'on' : 'off'}${st.paused ? ' ❚❚' : ''}  lock ${LOCK.on ? (LOCK.surface || '?') : 'off'}\n` +
      `diff ${(LOCK.lastDiff || 0).toFixed(3)} / gate ${STRIP_GATE}  offN ${LOCK.offN}  screen_off ${LOCK.off ? 1 : 0}\n` +
      `on_target ${st.on_target ? 1 : 0}  drifts ${st.drifts | 0}  excused ${st.excused ? 1 : 0}  deferred ${st.deferred ? 1 : 0}\n` +
      `intent-win ${intentOpen() ? 1 : 0}  offer-win ${offerPending() ? 1 : 0}`;
  }, 400);
}

/* ---------- dev hooks + ?focusprobe=1 battery (hermetic: recorders, no real speech) ------- */
window.__focusG = { FS, LOCK, parseMin, fmt, renderFocus, eyesSnap, consume, statusLine,
  startSession, stopSession, applyChip, offerPending, stripDiff, lockJudge, lockRef, lockOn, lockOff,
  surfaceVerdict, startWithAsk, setIntent, beginSession, intentOpen, cleanIntent,
  composeStartAck, retargetHere, DEFER_LINE };
if (PROBE) setTimeout(async () => {
  const R2 = [];
  const ok = (n, c) => R2.push((c ? 'PASS:' : 'FAIL:') + n);
  try {
    const MY = [START, STOP, PAUSE_OBJ, PAUSE_BARE, RESUME_OBJ, RESUME_BARE, STATUS, EXTEND,
                SGTON, SGTOFF, NAG, SNOOZE, EXCUSE, LOCKON, LOCKREL, RETARGET];
    const hit = (s) => MY.some(re => re.test(s));
    // start + control phrasings land; the DND governor's vocabulary does NOT
    ok('routes', START.test('focus for 30 minutes') && START.test('thirty minutes on this') &&
       START.test('Jarvis, twenty five minutes on this') && START.test('focus on this for 45 minutes') &&
       START.test('an hour on this') && START.test('focus for half an hour') &&
       STOP.test('abort the session') && STOP.test('stop the timer') && STOP.test('end the focus session') &&
       SGTON.test('drill sergeant mode') && SGTOFF.test('ease up'));
    ok('pauseroutes', PAUSE_OBJ.test('pause the timer') && PAUSE_OBJ.test('pause the session') &&
       PAUSE_OBJ.test('hold the clock') && PAUSE_OBJ.test('pause the countdown') &&
       RESUME_OBJ.test('resume the timer') && RESUME_OBJ.test('unpause the session') &&
       PAUSE_BARE.test('pause') && RESUME_BARE.test('back to work'));
    ok('anti-dnd', !hit('focus mode') && !hit('focus off') && !hit('stop focus') &&
       !hit('exit focus') && !hit('focus') && !hit('do not disturb') && !hit('hold my calls'));
    // number parsing
    ok('parse', parseMin('30') === 30 && parseMin('thirty') === 30 && parseMin('twenty five') === 25 &&
       parseMin('twenty-five') === 25 && parseMin('an hour') === 60 && parseMin('half an hour') === 30 &&
       parseMin('ninety') === 90 && parseMin('gibberish') === null && parseMin('0') === null);
    ok('mins-from', minsFrom('focus for half an hour') === 30 && minsFrom('ten more minutes') === 10 &&
       minsFrom('twenty five minutes on this') === 25);
    // de-rambled intents: fillers and lead-ins fall away, the object survives
    ok('intent-clean', cleanIntent("yeah so I'm trying to build out the classroom section") === 'the classroom section' &&
       cleanIntent('no, okay, well, the thumbnail sprint.') === 'the thumbnail sprint' &&
       cleanIntent('editing the video script') === 'editing the video script');
    // a protest while adrift is an excuse, not an intent
    ok('protest', PROTEST.test("no this is the time I'm looking at right now") &&
       PROTEST.test("this is what I'm working on") && PROTEST.test("I'm on the right tab") &&
       !PROTEST.test('the classroom section') && !PROTEST.test('pause the timer'));
    // nag + snooze parsing (seconds vs minutes)
    ok('nag-parse', NAG.test('call me out every five seconds') && NAG.test('nag me every 2 minutes') &&
       secsFrom('call me out every five seconds', NAG) === 5 &&
       secsFrom('nag me every 2 minutes', NAG) === 120 &&
       secsFrom('update me every thirty seconds', NAG) === 30);
    ok('snooze-parse', SNOOZE.test('give me 15 seconds') &&
       SNOOZE.test('give me like 15 seconds and then give me updates') &&
       secsFrom('give me like 15 seconds and then give me updates', SNOOZE) === 15 &&
       secsFrom('give me five minutes', SNOOZE) === 300);
    // his exact excuse sentence lands; a bare "no" stays out of it
    ok('excuse-routes', EXCUSE.test("no jarvis it's okay i'm just doing research on this other tab") &&
       EXCUSE.test("it's okay, this is research") && EXCUSE.test("i'm still working") &&
       EXCUSE.test('i need this tab') && !EXCUSE.test('no') && !EXCUSE.test('no thanks'));
    // lock routes land; the WATCH organ's own phrasings stay untouched
    ok('lockroutes', LOCKON.test('lock this tab') && LOCKON.test('lock my screen') &&
       LOCKON.test('lock onto this window') &&
       LOCKON.test('watch this tab and keep me accountable') &&
       KEEPACC.test('keep me accountable on this tab') &&
       !LOCKON.test('watch my screen') && !LOCKON.test('stop watching') &&
       LOCKREL.test('unlock the screen') && LOCKREL.test('screen lock off'));
    // S19w: the explicit re-target lands from the work tab AND from the Jarvis tab; the
    // pixel phrasing ("lock my screen") stays LOCKON's; the start ack names the deferred lock
    ok('retarget-routes', RETARGET.test('lock on this tab') && RETARGET.test('lock this tab') &&
       RETARGET.test('lock on this one') && RETARGET.test('this is the tab') &&
       RETARGET.test('this is the right tab') && RETARGET.test('focus on this tab') &&
       RETARGET.test('switch the lock to this tab') && RETARGET.test('Jarvis, lock on here') &&
       RETARGET.test('keep me in this tab') && RETARGET.test("okay, I'm gonna need you to keep me in this tab") &&
       RETARGET.test('keep me here') && RETARGET.test('stay on this tab') &&
       !RETARGET.test('keep me accountable on this tab') && !RETARGET.test('keep me posted') &&
       !RETARGET.test('lock my screen') && !RETARGET.test('watch this tab and keep me accountable') &&
       !RETARGET.test('lock the door') && LOCKON.test('lock my screen') &&
       KEEPACC.test('keep me accountable on this tab'));
    ok('defer-ack', composeStartAck('L.', 30, true, '').indexOf(DEFER_LINE) > 0 &&
       composeStartAck('L.', 30, true, '').endsWith('And what are we focusing on?') &&
       composeStartAck('L.', 30, false, '').indexOf(DEFER_LINE) === -1 &&
       composeStartAck(null, 25, true, ' E').startsWith('25 minutes') &&
       composeStartAck(null, 25, true, ' E').endsWith(' E And what are we focusing on?'));   // S21: note before the question
    // strip math (S19f changed-pixel metric): identical = 0, inverted = 1, sub-threshold
    // noise = 0, one-of-four changed = .25 (a real tab switch ≈ .05-.15 > the .035 gate,
    // where the old mean metric read ~.01 and stayed silent); the judge needs two hot
    // samples and self-resets
    const A = new Float32Array([0, 0, 1, 1]), B = new Float32Array([1, 1, 0, 0]);
    const C = new Float32Array([.5, .5, .5, .5]), D = new Float32Array([.55, .55, .55, .55]);
    const E = new Float32Array([.5, .5, .5, 1]);
    const keepLock = { off: LOCK.off, offN: LOCK.offN };
    LOCK.off = false; LOCK.offN = 0;
    const s1 = lockJudge(0.5), s2 = lockJudge(0.5), s3 = lockJudge(0.02);
    LOCK.off = keepLock.off; LOCK.offN = keepLock.offN;
    ok('strip', stripDiff(A, A) === 0 && stripDiff(A, B) === 1 &&
       stripDiff(C, D) === 0 && stripDiff(C, E) === 0.25 &&
       s1 === false && s2 === true && s3 === false);
    // "keep me accountable, I'm planning to edit the script" carries the work inline
    const km = 'keep me accountable, I\'m planning to edit the video script'.match(KEEPACC);
    const km2 = 'keep me accountable'.match(KEEPACC);
    ok('keepacc', km && km[1].trim() === 'edit the video script' && km2 && !(km2[1] || '').trim() &&
       !KEEPACC.test('keep the change'));
    // the intent-answer window: the catch-all only exists while the question is open
    const kw = intentUntil;
    intentUntil = 0;
    const iwDead = R.some(r => r.re && r.re.test && r.re.test('polish the thumbnail draft'));
    intentUntil = performance.now() + 5000;
    const iwLive = R.some(r => r.re && r.re.test && r.re.test('polish the thumbnail draft'));
    intentUntil = kw;
    ok('intent-win', !iwDead && iwLive);
    // surface truth: monitor + window arm the pixels; a TAB share never does (it can't see
    // you leave), and its line steers to the Entire Screen
    ok('surface', surfaceVerdict('monitor').arm && surfaceVerdict('window').arm &&
       !surfaceVerdict('browser').arm && /entire screen/i.test(surfaceVerdict('browser').line));
    // clock text
    ok('fmt', fmt(1501000) === '25:01' && fmt(0) === '0:00' && fmt(-5) === '0:00');
    // chip renderer states
    const r1 = renderFocus({ on: true, remain_ms: 1501000, on_target: true, paused: false });
    const r2 = renderFocus({ on: true, remain_ms: 1501000, on_target: false, paused: false });
    const r3 = renderFocus({ on: true, remain_ms: 1501000, on_target: true, paused: true });
    const r4 = renderFocus({ on: false });
    ok('render', r1.text === '25:01' && r1.on && !r1.drift &&
       r2.text === '⚠ 25:01' && r2.drift && r3.text === '❚❚ 25:01' && r4.text === 'off' && !r4.on);
    // NO-LEAK: a hostile payload cannot put an app identity on the chip or in the mouth
    const hostile = { on: true, remain_ms: 60000, on_target: true, paused: false,
                      app: 'com.evil.app', title: 'SecretDoc', say: null };
    const rh = renderFocus(hostile);
    ok('no-leak-render', rh.text.indexOf('com.evil') < 0 && rh.text.indexOf('SecretDoc') < 0);
    // NO-LEAK: the signal feed is exactly {present, down, screen_off}, all booleans —
    // and a lock-only feed (camera off) reports neutral presence, never accusations
    const keepEyes = window.__eyes;
    window.__eyes = { on: true, present: true, pitch: -41, secret: 'com.leaky.thing', title: 'Doc' };
    const snap = eyesSnap();
    window.__eyes = { on: false };
    const keepLk = LOCK.on; LOCK.on = true; LOCK.off = true;
    const snap2 = eyesSnap();
    LOCK.on = keepLk; LOCK.off = false;
    window.__eyes = keepEyes;
    ok('no-leak-feed', snap && Object.keys(snap).sort().join(',') === 'down,present,screen_off' &&
       snap.down === true && snap.present === true && snap.screen_off === false &&
       snap2 && snap2.present === true && snap2.down === false && snap2.screen_off === true);
    // gating: session-scoped phrasings are dead while off, live while on
    const GATED = ['ten more minutes', 'how am i doing', 'pause', 'give me 15 seconds',
                   'back to work', "it's okay i'm still working"];
    const keepOn = FS.on;
    FS.on = false;
    const dead = GATED.filter(s => R.some(r => r.re && r.re.test && r.re.test(s))).length;
    FS.on = true;
    const live = GATED.filter(s => R.some(r => r.re && r.re.test && r.re.test(s))).length;
    FS.on = keepOn;
    ok('gate', dead === 0 && live === GATED.length);
    // the deep-work offer: speaks once, arms the yes-window, cools down
    const oSpoke = [];
    window.__focusTestSpk = (t) => oSpoke.push(t);
    const keepCool = offerCool; offerCool = -9e9; offerUntil = 0;
    const fired = window.__focusOffer('probe');
    const armed = offerPending();
    const yesLive = R.some(r => r.re && r.re.test && r.re.test('yes'));
    const again = window.__focusOffer('probe');           // cooldown must refuse
    offerUntil = 0;
    const yesDead = R.some(r => r.re && r.re.test && r.re.test('yes'));
    offerCool = keepCool;
    delete window.__focusTestSpk;
    ok('offer', fired && armed && yesLive && !again && !yesDead &&
       oSpoke.length === 1 && /deep work/i.test(oSpoke[0]));
    // consume() speaks a queued line once, routes the report to the panel, stops the poll
    const spoke = [];
    window.__focusTestSpk = (t, panel) => spoke.push({ t, panel });
    consume({ on: true, paused: false, on_target: true, remain_ms: 60000, say: 'Test callout', report: null });
    consume({ on: true, paused: false, on_target: true, remain_ms: 59000, say: null, report: null });
    consume({ on: false, say: 'Time, sir. 27 of 30 minutes on target.', report: { planned_min: 30 } });
    delete window.__focusTestSpk;
    ok('consume', spoke.length === 2 && spoke[0].t === 'Test callout' && !spoke[0].panel &&
       spoke[1].panel === true && FS.pollId === 0);
    // the server half: hermetic engine battery (fake clock, throwaway engines, no NSWorkspace)
    let sv = [];
    try { sv = ((await (await fetch('/focus/probe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })).json()) || {}).results || []; }
    catch (_){}
    ok('sv-reached', sv.length >= 29);
    for (const t of sv) ok('sv-' + t.n, t.ok);
  } catch (e){ R2.push('FAIL:exception ' + (e && e.message)); }
  const pass = R2.filter(r => r.startsWith('PASS')).length;
  document.title = `FOCUSPROBE ${pass}/${R2.length} · ` + R2.join(' ');
}, 700);
