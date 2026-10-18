// Jarvis V6 — HANDS (computer takeover) client. Registers voice routes in window.__jarvisRoutes:
// an EXPLICIT takeover command ("take over and <task>") IS the permission — he answers "Okay —
// taking over the screen now, sir." and drives immediately (no may-I round trip, his 2026-08-11
// decree). The ask-then-yes flow (requestTakeover/goRoute) remains for indirect entry points, and he
// drives → a live action card streams what he's doing with a big STOP → "stop" / "hand it over" /
// "give me the screen" halts instantly. He NARRATES the drive out loud (latest-line queue so speech
// never lags the mouse); "quiet" hushes it for the run, "narrate" brings it back.
// The desktop presence orb is server-side (presence.py); here we just flip it to "working" while
// he drives and poll the action log. Fully optional: no bridge, no effect.

const $id = (i) => document.getElementById(i);
let J = null;
let poll = 0, since = 0, pendingTask = null;

const NEVER = /$^/;
const goRoute = { re: NEVER, handler: goAhead };   // ANY natural yes grabs the wheel ONLY while a request is pending
const stopRoute = { re: NEVER, handler: stopDriving };
const narrRoute = { re: NEVER, handler: narrToggle };   // "quiet" / "narrate" — armed only while driving
const nayRoute = { re: NEVER, handler: standDown };     // "no / cancel / not now" — armed only while a request is pending

// The yes-matcher (his 2026-08-11 report: "it should just ask me once, I say yes, and it should
// do it" — compound yeses like "yes, go ahead" missed the old anchored list and chat re-asked in
// circles). STRONG action phrases accept trailing words ("go ahead and show me"); WEAK bare
// affirmatives ("okay", "yeah") count alone or stacked — but "okay, what's on my calendar?"
// falls through to normal routing with the ask still armed.
const YES_STRONG = "go ahead|do it|take (?:over|the wheel)|go for it|proceed|absolutely|of course|please do|by all means|(?:permission )?granted|you have (?:my )?permission|the wheel is yours|yes,? you (?:can|may)|let'?s (?:do it|go)|sounds good|make it so|drive";
const YES_WEAK = "yes|yeah|yep|yup|sure|okay|ok|alright|please";
const YES_RE = new RegExp(
  "^(?:jarvis[,:]? )?(?:(?:" + YES_WEAK + ")[,.! ]+)*(?:(?:" + YES_WEAK + ")|(?:" + YES_STRONG + ")[\\w ,'’-]*)[.!]?$", "i");
const NAY_RE = /^(?:jarvis[,:]? )?(?:no|nope|nah|not (?:now|yet)|don'?t|do not|cancel|never ?mind|stand down|forget it|leave it|stop|hold (?:on|off)|wait)\b.*$/i;

// drive-voice mark: 3d.html's speak() MUTES everything unmarked while a drive is active
// (2026-08-18: narration + a chat answer spoke at once — "two Jarvises"). The mark rides the
// text itself so a long narration line can never let other speech slip through the gate.
const DV = '\u2063';
const dv = (t) => J.voice(DV + t);          // speak only (screen untouched)
const dvSay = (t) => J.say(DV + t);         // answer-panel line + speech

async function standDown() {
  pendingTask = null; goRoute.re = NEVER; nayRoute.re = NEVER;
  const now = $id('jh-now'); if (now) now.textContent = 'Standing down.';
  setTimeout(hidePanel, 1500);
  await dvSay('Very well, sir — hands to myself.');
  return false;
}

// ---- spoken narration of the drive (his 2026-08-11 ask: "narrate what it's doing") ----
// Drop-stale queue: if a line is still being spoken when the next arrives, keep only the NEWEST
// pending line — speech never lags more than one step behind the mouse.
let narrOn = true, narrBusy = false, narrNext = null;
function narrate(t) {
  if (!narrOn || !t) return;
  if (narrBusy) { narrNext = t; return; }
  narrBusy = true;
  (async () => {
    try { await dv(t); } catch (_) {}
    narrBusy = false;
    const n = narrNext; narrNext = null;
    if (n) narrate(n);
  })();
}
async function narrToggle(q) {
  if (/\b(?:quiet|silence|silently|stop narrating|no narration|hush)\b/i.test(q)) {
    narrOn = false; narrNext = null; await dv('Silently, sir.');
  } else { narrOn = true; await dv('Narrating, sir.'); }
  return false;
}

function panel() {
  let el = $id('j-hands');
  if (el) return el;
  el = document.createElement('div');
  el.id = 'j-hands';
  el.style.cssText = 'position:fixed;right:26px;bottom:96px;width:320px;z-index:88;display:none;'
    + 'background:rgba(12,14,18,.94);border:1px solid rgba(240,180,70,.4);border-radius:16px;'
    + 'padding:15px 16px;backdrop-filter:blur(12px);font-family:-apple-system,"Segoe UI",sans-serif;'
    + 'box-shadow:0 12px 40px rgba(0,0,0,.5);';
  el.innerHTML = `<div style="display:flex;align-items:center;gap:9px;margin-bottom:10px;">
      <span id="jh-dot" style="width:9px;height:9px;border-radius:50%;background:#f0b446;box-shadow:0 0 8px #f0b446;"></span>
      <span style="font-family:'SF Mono',ui-monospace,monospace;font-size:11px;letter-spacing:.14em;color:#f0b446;">JARVIS IS DRIVING</span>
      <button id="jh-stop" style="margin-left:auto;background:rgba(251,113,133,.16);border:1px solid rgba(251,113,133,.6);color:#fb7185;border-radius:99px;font-size:12px;font-weight:600;padding:6px 16px;cursor:pointer;">◼ STOP</button>
    </div>
    <div id="jh-now" style="font-size:13px;color:#eaf0ec;line-height:1.5;min-height:20px;"></div>
    <div id="jh-log" style="margin-top:9px;max-height:132px;overflow-y:auto;font-size:11.5px;color:#8a97a0;line-height:1.7;"></div>
    <div style="display:flex;align-items:center;gap:6px;margin-top:11px;padding-top:9px;border-top:0.5px solid rgba(255,255,255,.08);">
      <span style="font-size:10px;color:#5a6b62;letter-spacing:.1em;">SPEED</span>
      <span id="jh-speed" style="display:flex;gap:5px;margin-left:auto;"></span>
    </div>`;
  document.body.appendChild(el);
  el.querySelector('#jh-stop').onclick = stopDriving;
  renderSpeed();
  return el;
}
function showPanel() { panel().style.display = 'block'; }
function hidePanel() { const el = $id('j-hands'); if (el) el.style.display = 'none'; }

const SPEEDS = [['fast', 'Fast'], ['balanced', 'Balanced'], ['smart', 'Smart']];
let curSpeed = 'balanced';
function renderSpeed() {
  const wrap = $id('jh-speed'); if (!wrap) return;
  wrap.innerHTML = SPEEDS.map(([id, label]) => {
    const on = id === curSpeed;
    return `<button data-s="${id}" style="font-size:10.5px;padding:3px 9px;border-radius:99px;cursor:pointer;`
      + (on ? 'border:1px solid rgba(240,180,70,.7);background:rgba(240,180,70,.16);color:#f0b446;'
            : 'border:1px solid rgba(255,255,255,.14);background:transparent;color:#8a97a0;') + '">' + label + '</button>';
  }).join('');
  wrap.querySelectorAll('button').forEach((b) => { b.onclick = () => setSpeed(b.dataset.s, true); });
}
async function setSpeed(tier, spoken) {
  const r = await J.post('/hands_speed', { tier }, 8000);
  curSpeed = (r && r.speed) || tier; renderSpeed();
  if (spoken) dvSay(`${curSpeed} driver, sir.`);
}
async function syncSpeed() {
  try { const d = await (await fetch('/api/hands')).json(); if (d.speed) { curSpeed = d.speed; renderSpeed(); } } catch (_) {}
}

function render(events) {
  const now = $id('jh-now'), log = $id('jh-log');
  if (!now) return;
  for (const e of events) {
    if (e.kind === 'action') { now.textContent = '⚙ ' + e.text; addLog(log, e.text, '#8a97a0'); }
    else if (e.kind === 'say') { now.textContent = e.text; narrate(e.text); }
    else if (e.kind === 'done') { now.textContent = '✓ ' + e.text; addLog(log, e.text, '#e8b64c'); finish(e.text); }
    else if (e.kind === 'error') { now.textContent = '⚠ ' + e.text; addLog(log, e.text, '#fb7185'); finish(null); }
  }
}
function addLog(log, text, color) {
  if (!log) return;
  const d = document.createElement('div'); d.style.color = color; d.textContent = '· ' + text;
  log.appendChild(d); log.scrollTop = log.scrollHeight;
}

async function goAhead() {
  const task = pendingTask; pendingTask = null; goRoute.re = NEVER; nayRoute.re = NEVER;
  if (!task) return false;
  window.__handsActive = true;
  try { J.post('/presence', { cmd: 'show' }); J.post('/presence', { cmd: 'state:working' }); } catch (_) {}
  showPanel();
  $id('jh-now').textContent = 'Taking the wheel, sir…';
  since = 0;
  const r = await J.post('/hands_go', { task, session: J.session }, 20000);
  if (!r || r.error) { $id('jh-now').textContent = (r && r.error) || 'Could not start.'; return finish(null); }
  // every reasonable way of taking the screen back halts him instantly (his 2026-08-11 ask:
  // "Jarvis, stop" or "hand me over the screen" → immediate stop)
  stopRoute.re = /^(?:okay |ok |jarvis[,:]? |please )*(?:stop|halt|cancel|let go|drop it|stop driving|that's enough|hand (?:it |me )?(?:over|back)|hand (?:me )?(?:over )?(?:the |my )?(?:screen|wheel|mouse|controls?)|give me (?:back )?(?:the |my )?(?:screen|wheel|mouse|controls?)(?: back)?|(?:my|the) (?:screen|mouse|computer) back|take your hands off|let me (?:drive|take over)|i(?:'ll| will)? take (?:it|over)(?: from here)?)(?: now| please)?[.!]?$/i;
  narrOn = true; narrBusy = false; narrNext = null;
  narrRoute.re = /^(?:okay |ok |jarvis[,:]? |please )*(?:quiet|silence|silently|hush|stop narrating|no narration|narrate(?: again)?|talk me through it)(?: please)?[.!]?$/i;
  await dvSay('Okay — taking over the screen now, sir.');
  clearInterval(poll);
  poll = setInterval(pollOnce, 900);
}

async function pollOnce() {
  let d;
  try { d = await (await fetch('/api/hands?since=' + since)).json(); } catch (_) { return; }
  if (d.events && d.events.length) { render(d.events); since = d.total; }
  if (!d.active && (!d.events || !d.events.some((e) => e.kind === 'done' || e.kind === 'error'))) {
    // run ended without a terminal event we saw — stop polling
    finish(null);
  }
}

function finish(sayText) {
  clearInterval(poll); poll = 0;
  stopRoute.re = NEVER; narrRoute.re = NEVER; narrNext = null;
  window.__handsActive = false;
  const dot = $id('jh-dot'); if (dot) { dot.style.background = '#34d399'; dot.style.boxShadow = '0 0 8px #34d399'; }
  try { J.post('/presence', { cmd: window.__jarvisShare ? 'state:idle' : 'hide' }); } catch (_) {}
  if (sayText) {
    J.setLastNote && J.setLastNote(sayText);
    // the completion report must WAIT for the last narration line to finish — starting it
    // mid-line was the classic "two Jarvises at once" (2026-08-18); cap the wait at 6s
    (async () => { for (let i = 0; i < 50 && narrBusy; i++) await new Promise((r) => setTimeout(r, 120));
                   dvSay(sayText); })();
  }
  setTimeout(() => { if (!window.__handsActive) hidePanel(); }, 9000);
  return false;
}

async function stopDriving() {
  try { await J.post('/hands_stop', {}); } catch (_) {}
  $id('jh-now') && ($id('jh-now').textContent = 'Stopping, sir.');
  await dvSay('Hands off, sir.');
  return finish(null);
}

async function requestTakeover(task) {
  const r = await J.post('/hands_request', { task }, 15000);
  if (!r || r.error) return J.say((r && r.error) || 'I cannot reach the controls, sir.');
  pendingTask = r.task;
  goRoute.re = YES_RE;    // any natural yes — including compound ("yes, go ahead and do it")
  nayRoute.re = NAY_RE;   // and any natural no stands the request down instead of chatting
  showPanel(); syncSpeed();
  $id('jh-now').textContent = r.ask;
  $id('jh-dot').style.background = '#f0b446';
  await J.say(r.ask);
}

// intent: "take over and book…", "fill (out|in) this form…", "do it for me on my screen"
const TAKEOVER = /\b(take over|take the wheel|drive (?:my|the) (?:computer|screen|mac)|do it (?:for me|yourself)|fill (?:out|in) (?:this|the|my)\b|control (?:my|the) (?:computer|screen|mac)|use my (?:computer|mouse|keyboard))\b/i;
const STRIP = /^(?:(?:okay|ok|so|now|hey|alright|right|um|uh|please|jarvis)[,!]? +)*(?:jarvis[,:\s]+)?(?:can you |could you |would you |please |go ahead and |i want you to |i need you to )*/i;
// pull the actual task out from after the trigger ("take over and X" → "X"; "fill out this form" stays whole)
const TRIGGER_LEAD = /^(?:take over(?: (?:the |my )?(?:screen|computer|mac|mouse|wheel))?|take the wheel|drive (?:my|the) (?:computer|screen|mac)|control (?:my|the) (?:computer|screen|mac)|use my (?:computer|mouse|keyboard)|do it (?:for me|yourself))\s*(?:and|then|to|:)?\s*/i;

function extractTask(q) {
  let t = q.replace(STRIP, '').trim();
  const stripped = t.replace(TRIGGER_LEAD, '').trim();
  if (stripped && stripped.length > 3) t = stripped;   // "take over and book X" → "book X"; bare "fill out this form" kept
  t = t.replace(/\bjarvis[,!]?\s*/gi, ' ').replace(/\s{2,}/g, ' ').trim();   // stray vocatives out of the task
  t = t.replace(/^(?:and|then|to|so)\s+/i, '').trim();                       // dangling connector after the strips
  return t;
}

function routes() {
  const R = (window.__jarvisRoutes = window.__jarvisRoutes || []);
  R.push(
    {
      re: TAKEOVER,
      handler: async (q) => {
        if (window.__handsActive) { await dv('Already at the wheel, sir.'); return false; }
        // his explicit takeover command IS the permission — drive immediately, no may-I round trip
        pendingTask = extractTask(q) || 'help me on screen';
        return goAhead();
      },
    },
    {
      re: /\b(?:takeover|driver|drive)\s+(?:speed\s+)?(fast(?:est)?|balanced|smart(?:est)?|careful)\b|\b(?:go|drive)\s+(faster|slower|smarter)\b/i,
      handler: async (q, m) => {
        const w = (m[1] || m[2] || '').toLowerCase();
        const tier = /fast|faster/.test(w) ? 'fast' : /smart|careful|slower|smarter/.test(w) ? 'smart' : 'balanced';
        await setSpeed(tier, true);
      },
    },
  );
  R.unshift(goRoute, stopRoute, narrRoute, nayRoute);   // outrank other bays' "do it"/"stop" — but ONLY while armed (regex is NEVER otherwise)
}

(function boot() {
  let n = 0;
  const w = setInterval(() => {
    if (window.__jarvis) { clearInterval(w); J = window.__jarvis; routes(); }
    else if (++n > 100) clearInterval(w);
  }, 150);
})();
