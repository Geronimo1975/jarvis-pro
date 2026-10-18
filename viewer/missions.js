// missions.js — Jarvis V5 MISSION BAY client (ES module, loaded after the core IIFE).
// Registers voice routes in window.__jarvisRoutes, drives the bottom-left mission dock,
// and flies the THREE fleet orbs through the graph while THE FLEET is out.
// Fully optional: if the bridge never appears, this module does nothing.
import * as THREE from 'three';
import SpriteText from 'three-spritetext';

const KINDS = {
  fleet:    { icon: '⚔️', ack: 'Deploying the fleet, sir.' },
  buildapp: { icon: '🛠️', ack: 'Opening the workshop, sir — building it now.' },
  reaper:   { icon: '💰', ack: 'Sharpening the scythe, sir — auditing your subscriptions.' },
  warroom:  { icon: '📊', ack: 'The war room is assembling, sir.' },
  announce: { icon: '📣', ack: 'Drafting the announcements, sir — nothing posts without your word.' },
  haters:   { icon: '🔥', ack: 'Reading the comments, sir. Brace yourself.' },
  rea:      { icon: '🔬', ack: 'Taking it apart with REA now, sir — a few minutes.' },                      // S29
  build:    { icon: '🏗️', ack: "Building it now, sir. I'll test it in a hidden browser before I hand it over." },
};
const STAGES = ['SCAFFOLD', 'CODE', 'TEST', 'LAUNCH'];
const AGENT_COLOR = { SCOUT: '#62dbff', FORGE: '#f4a93a', SAGE: '#b58cff', JARVIS: '#34d399',
                      REAPER: '#f4a93a', WARROOM: '#62dbff', HERALD: '#f4a93a', HATERS: '#ff7d6b',
                      REA: '#62dbff', BUILDER: '#f4a93a' };
const M = new Map();          // mid -> mission client state
// EYES (V7): the sight organ asks "is anything awaiting a yes?" before a nod may fire "do it"
window.__missionsConfirm = () => { try { return [...M.values()].some(x => x.status === 'awaiting_confirm' && !x.dead); } catch (_) { return false; } };

let J, OS, dock;
(function boot(n) {
  if (window.__jarvis && window.__os && window.__os.Graph) { try { init(); } catch (e) { console.warn('[missions]', e); } return; }
  if ((n || 0) < 3600) requestAnimationFrame(() => boot((n || 0) + 1));   // ~1 min of patience
})();
function init() {
  J = window.__jarvis; OS = window.__os;
  injectStyle();
  dock = document.createElement('div'); dock.id = 'j-missions'; document.body.appendChild(dock);
  routes();
}

// ---------- styling (house look: mono, emerald, glass) ----------
function injectStyle() {
  const s = document.createElement('style');
  s.textContent = `
  #j-missions{position:fixed;left:286px;bottom:100px;z-index:56;display:flex;flex-direction:column;gap:10px;
    width:300px;max-height:62vh;overflow-y:auto;overflow-x:hidden;font-family:'SF Mono',ui-monospace,monospace;
    transition:left .35s cubic-bezier(.4,0,.2,1);scrollbar-width:thin;scrollbar-color:#1c3a2e transparent;}
  body.collapsed #j-missions{left:22px;}
  .jm-card{background:rgba(10,16,20,.94);border:1px solid rgba(52,211,153,.4);border-radius:12px;
    padding:10px 12px;backdrop-filter:blur(12px);box-shadow:0 12px 40px rgba(0,0,0,.55);
    animation:jm-in .3s ease-out;}
  @keyframes jm-in{from{opacity:0;transform:translateX(-14px) scale(.97);}to{opacity:1;transform:none;}}
  .jm-h{display:flex;align-items:center;gap:7px;}
  .jm-ic{font-size:14px;flex:none;}
  .jm-t{flex:1;font-size:10px;letter-spacing:.12em;color:#bfe8d6;font-weight:700;text-transform:uppercase;
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .jm-led{width:8px;height:8px;border-radius:50%;flex:none;background:#62dbff;box-shadow:0 0 8px currentColor;color:#62dbff;}
  .jm-led.run{animation:jm-pulse 1.1s ease-in-out infinite;}
  .jm-led.wait{background:#f4a93a;color:#f4a93a;animation:jm-pulse 1.4s ease-in-out infinite;}
  .jm-led.done{background:#34d399;color:#34d399;animation:none;}
  .jm-led.err{background:#ff5d5d;color:#ff5d5d;animation:none;}
  @keyframes jm-pulse{0%,100%{opacity:.35;transform:scale(.8);}50%{opacity:1;transform:scale(1.15);}}
  .jm-x{flex:none;background:none;border:none;color:#3f584d;font-size:12px;cursor:pointer;padding:0 2px;font-family:inherit;}
  .jm-x:hover{color:#eaf0ec;}
  .jm-feed{margin-top:8px;font-size:9.5px;line-height:1.55;color:#7fa89a;max-height:104px;overflow:hidden;}
  .jm-feed div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .jm-feed b{font-weight:700;}
  .jm-res{margin-top:8px;font-size:10.5px;color:#cdd8d2;line-height:1.5;}
  .jm-stage{display:flex;gap:4px;margin-top:8px;}
  .jm-stage span{flex:1;text-align:center;font-size:8.5px;letter-spacing:.08em;padding:3px 0;border-radius:5px;
    border:1px solid rgba(52,211,153,.18);color:#3f584d;}
  .jm-stage span.on{border-color:rgba(52,211,153,.6);color:#34d399;background:rgba(52,211,153,.1);}
  .jm-btn{display:inline-block;margin-top:7px;font-size:10px;letter-spacing:.06em;border-radius:7px;padding:5px 12px;
    cursor:pointer;border:1px solid rgba(52,211,153,.5);background:rgba(52,211,153,.16);color:#7ef0c2;font-family:inherit;}
  .jm-btn:hover{filter:brightness(1.3);}
  .jm-btn[disabled]{opacity:.4;cursor:default;}
  .jm-total{font-size:20px;font-weight:700;color:#34d399;letter-spacing:.03em;margin:6px 0 2px;}
  .jm-total small{font-size:10px;color:#7fa89a;font-weight:400;}
  .jm-row{display:flex;align-items:center;gap:6px;padding:4px 0;border-top:1px solid rgba(52,211,153,.1);}
  .jm-row .n{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#cdd8d2;font-size:10.5px;}
  .jm-row .a{color:#7fa89a;font-size:10px;flex:none;}
  .jm-row button{font-size:9px;border-radius:5px;padding:2px 8px;cursor:pointer;font-family:inherit;
    border:1px solid rgba(52,211,153,.3);background:rgba(52,211,153,.1);color:#7ef0c2;}
  .jm-row button.kill{border-color:rgba(255,93,93,.45);background:rgba(255,93,93,.12);color:#ff9d8f;}
  .jm-row button:hover{filter:brightness(1.3);}
  .jm-row.dead{opacity:.45;}
  .jm-row.drafted .n{color:#ff9d8f;}
  .jm-row.flash{animation:jm-flash .6s ease-out;}
  @keyframes jm-flash{0%{background:rgba(255,93,93,.35);}100%{background:transparent;}}
  .jm-stats{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px;}
  .jm-stat{border:1px solid rgba(52,211,153,.18);border-radius:8px;padding:6px 8px;background:rgba(52,211,153,.05);}
  .jm-stat b{display:block;font-size:15px;color:#eaf0ec;}
  .jm-stat i{font-style:normal;font-size:8.5px;letter-spacing:.1em;color:#5a6b62;text-transform:uppercase;}
  .jm-post{border:1px solid rgba(52,211,153,.18);border-radius:8px;padding:6px 8px;margin-top:6px;background:rgba(52,211,153,.04);}
  .jm-post .p{font-size:9px;letter-spacing:.12em;color:#62dbff;text-transform:uppercase;display:flex;justify-content:space-between;}
  .jm-post .p .mk{font-size:10px;}
  .jm-post .tx{margin-top:3px;color:#b9c9c2;font-size:10px;line-height:1.45;max-height:72px;overflow:hidden;}
  .jm-com{border-top:1px solid rgba(52,211,153,.1);padding:6px 0 2px;margin-top:4px;}
  .jm-com .au{color:#62dbff;font-size:9.5px;}
  .jm-com .cm{color:#9fb2ab;font-size:10px;font-style:italic;line-height:1.4;}
  .jm-com .rp{color:#cdd8d2;font-size:10px;line-height:1.4;margin-top:3px;}
  .jm-com .rp::before{content:'↳ ';color:#34d399;}`;
  document.head.appendChild(s);
}

// ---------- voice routes ----------
function routes() {
  const R = (window.__jarvisRoutes = window.__jarvisRoutes || []);
  const clean = t => String(t || '').replace(/^[\s,.:;!—–-]+/, '').replace(/^(?:on|about|for|to|that|of)\s+/i, '').trim();
  const restAfter = (q, m) => clean(q.slice((m.index || 0) + m[0].length));

  R.push({ re: /\b(?:assemble|deploy|launch) the fleet\b|\bput the fleet on\b|\bfleet[,:]\s*(.+)/i,
    handler: async (q, m) => {
      const brief = clean(m && m[1]) || restAfter(q, m);
      if (!brief) { await J.say('On what, sir? Give me "deploy the fleet on…" and a brief.'); return; }
      launch('fleet', brief);
    } });
  // S29: the general BUILDER replaces the single-file HUD builder on the voice path —
  // "build me a notes app", "make a landing page for…", "code a pomodoro timer", "build my own version of that"
  // S29g: "my own version of THAT" = the latest teardown; "my own version of igloo.inc / the Notes app" (a named
  // target) belongs to teardown.js's CLONE route, which takes it apart first, then builds — so OWN refuses an "of <name>"
  const OWN = /\b(?:build|make|create|code|develop)(?: me)?(?: up)? my own (?:version|copy|take|spin|replica)(?: of (?:the (?:last |latest |previous )?(?:tear ?down|site|app|website|page|thing)|(?:that|it|this)(?: (?:tear ?down|site|app|website|page|thing))?))?\b(?!\s+of\b)(.*)|\b(?:rebuild|re-?create|recreate|replicate) (?:the (?:last |latest |previous )?(?:tear ?down|site|app|website|page|thing)|(?:that|it|this)(?: (?:tear ?down|site|app|website|page|thing))?)\b(?!\s+of\b)(.*)/i;
  const BUILD_OBJ = String.raw`app|application|web ?app|site|website|web ?page|page|tool|game|dashboard|landing ?page|portfolio|calculator|tracker|timer|clone|editor|player|generator|simulator|visuali[sz]er|prototype|demo|widget|form|board|planner|notes? app|to-?do(?: list)?|journal|diary|budget(?:er)?|invoice(?:r| generator)?|scheduler|booking (?:page|system|tool)|quiz|flashcards?|slideshow|presentation|deck|spreadsheet|table|chart|graph|map|kanban|crm|cms|blog|store|shop|storefront|checkout|chat(?:bot)?|bot|assistant|interface|ui|mockup|wireframe|animation|effect|component|screen|menu|gallery|viewer|reader|converter|counter|stopwatch|clock|checklist|habit tracker|workout (?:app|tracker|planner)|recipe (?:app|book)|resume|cv|landing`;
  const BUILD = new RegExp(String.raw`\b(?:build|make|create|code|develop|write|generate|design|prototype|craft|produce|whip up|spin up|put together|cook up|ship)(?: me)?(?: up)?\s+((?:an?|the|my|one|some|a quick|a simple|a little|a small|a basic)\s+(?:[\w'-]+\s+){0,6}?(?:` + BUILD_OBJ + String.raw`)\b.*)|\bi (?:want|need|would like)(?: to have)?\s+((?:an?|my own|a quick|a simple|a little)\s+(?:[\w'-]+\s+){0,6}?(?:` + BUILD_OBJ + String.raw`)\b.*)`, 'i');
  R.push({ re: OWN, handler: async (q, m) => {
      const extra = clean((m && (m[1] || m[2])) || '').replace(/^(?:but|and|,|-)\s*/i, '');
      launch('build', 'My own original version of the site or app in my latest teardown' + (extra ? ' — ' + extra : ''), { from_teardown: true, open: true });
    } });
  R.push({ re: BUILD, handler: async (q, m) => {
      const brief = clean(m && (m[1] || m[2]));
      if (!brief) { await J.say('Build what, sir?'); return; }
      launch('build', brief, { open: true });
    } });
  // "open the app you built" / "launch the last build" → the newest FINISHED build, as its own window
  // (works while a new build is still running; survives restarts — the builds live on disk)
  // "open the NOTES app you just built" fell through to the brain (2026-10-13 evening) — words between
  // "the" and "app" are allowed now; the "you built" tail is required unless he says last/latest/newest
  R.push({ re: /\b(?:open|launch|show me|bring up|pull up|run)\s+(?:the |my |that |this )?(?:(?:last|latest|new|newest|finished)\s+)?(?:[\w'-]+\s+){0,3}?(?:app|application|build|site|website|page|thing)\s+(?:that )?(?:you|jarvis|he)\s+(?:just |recently )?(?:built|made|created|coded)\b|\b(?:open|launch|show me|bring up|pull up|run)\s+(?:the |my |that )?(?:last|latest|new|newest|finished)\s+(?:app|application|build|site|website|page|thing)\b/i,
    handler: async q => {
      let r = null;
      try { r = await J.post('/mission_open', { hint: q }, 15000); } catch (e) {}   // the phrase picks the build by name
      if (!r || r.error) { await J.say((r && r.error) || "I haven't built anything yet, sir."); return; }
      await J.say('Opening it now, sir' + (r.note ? ' — ' + String(r.note).replace(/\*\*/g, '').slice(0, 90) : '.'));
    } });
  R.push({ re: /\baudit my subscriptions?\b|\bsubscription (?:audit|reaper)\b|\bfind (?:me )?(?:the )?(?:wasted )?money\b/i,
    handler: async () => launch('reaper', '') });
  R.push({ re: /\bwar ?room\b|\bhow(?:'s| is) (?:the|my) (?:new |last |latest )?video(?: doing)?\b|\bchannel status\b|\bstatus report\b/i,
    handler: async () => launch('warroom', '') });
  R.push({ re: /\bannounce (?:it|this|the video)(?: everywhere)?\b|\bpost (?:it|this) everywhere\b/i,
    handler: async (q, m) => {
      const brief = restAfter(q, m);
      if (!brief) { await J.say('Announce what, sir? Say it again with a line about the thing.'); return; }
      launch('announce', brief);
    } });
  R.push({ re: /\bread (?:me )?the (?:haters|comments)\b|\bwhat are (?:they|people) saying\b/i,
    handler: async () => launch('haters', '') });
  R.push({ re: /^(?:do it|go ahead|approve|send it|post it|kill (?:it|them)(?: all)?)[.!]?$/i,
    handler: async q => {
      const st = [...M.values()].reverse().find(x => x.status === 'awaiting_confirm' && !x.dead);
      if (!st) { await J.say('Nothing awaiting my confirmation, sir.'); return; }
      confirmMission(st.id, 'all');
    } });
}

// ---------- mission lifecycle ----------
async function launch(kind, brief, opts) {
  const k = KINDS[kind];
  await J.say(k.ack);
  let r;
  try { r = await J.post('/mission_start', Object.assign({ kind, brief }, opts || {}), 20000); }
  catch (e) { await J.say("The mission bay didn't answer, sir."); return; }
  if (!r || r.error || !r.id) { await J.say((r && r.error) || 'The mission bay refused, sir.'); return; }
  adopt(r, kind, brief);
}
// S29: a mission the server already started (the brain's [TEARDOWN:]/[BUILD:] tags, or another organ)
function adopt(r, kind, brief) {
  kind = kind || r.kind;
  if (!r || !r.id || !KINDS[kind] || M.has(r.id)) return;
  const st = { id: r.id, kind, title: r.title || kind, brief: brief || r.brief || '', status: 'running', since: 0, result: null,
               pending: null, dead: false, saidRead: false, stages: new Set(), marks: {}, feed: [] };
  M.set(r.id, st);
  if (kind === 'rea' && window.__teardownMission) window.__teardownMission.start(st);   // S29c: the big TEARDOWN panel, not a dock card
  else addCard(st);
  if (kind === 'fleet') fleetSpawn(st);
  schedule(r.id, 800);
}
window.__missionLaunch = (kind, brief, opts) => launch(kind, brief, opts);
window.__missionAdopt = r => adopt(r, r && r.kind);
function openUrl(u0) {                                  // S23 guard: same-origin http(s) only, no opener
  let u = null; try { u = new URL(u0, location.href); } catch (_) {}
  if (!u || !/^https?:$/.test(u.protocol)) return;
  const w = window.open(u.href, '_blank'); if (w) w.opener = null;
}

function schedule(mid, ms) {
  const st = M.get(mid); if (!st || st.dead) return;
  clearTimeout(st.timer);
  st.timer = setTimeout(() => poll(mid), ms);
}

async function poll(mid) {
  const st = M.get(mid); if (!st || st.dead) return;
  let d;
  try { d = await fetch(`/mission_events?id=${encodeURIComponent(mid)}&since=${st.since}`).then(r => r.json()); }
  catch (e) { schedule(mid, 3000); return; }
  if (!d || d.error) { schedule(mid, 3000); return; }
  st.since = (typeof d.next === 'number') ? d.next : st.since + (d.events || []).length;
  for (const ev of (d.events || [])) onEvent(st, ev);
  const was = st.status;
  st.status = d.status || st.status; st.result = d.result; st.pending = d.pending;
  setLed(st);
  if (st.status !== was || (st.result && !st.rendered)) renderResult(st);
  if (st.status === 'done' || st.status === 'error') {
    if (st.kind === 'fleet') fleetRetire(st, st.status === 'done');
    if (st.kind === 'rea' && !st.el && window.__teardownMission && !st.panelDone) { st.panelDone = true; window.__teardownMission.done(st); }
    if (st.status === 'done' && st.el && st.result && st.result.next_mission && !st.chained) {   // S29g: a dock-hosted teardown that chains a build
      st.chained = true; adopt(st.result.next_mission, 'build');
      try { J.say("Now building your own version from that teardown, sir."); } catch (e) {}
    }
    if (st.status === 'done' && st.kind === 'rea' && st.result && !st.birthed) {   // S29: born under REA, like a site teardown
      st.birthed = true;
      try { if (window.__teardownBirth) window.__teardownBirth(st.result); } catch (e) {}
    }
    if (st.status === 'done') sayRead(st);
    // one last short poll in case trailing events land, then stop
    if (!st.finalPolled) { st.finalPolled = true; schedule(mid, 1500); }
    return;
  }
  schedule(mid, document.hidden ? 4000 : (st.status === 'awaiting_confirm' ? 1600 : 800));
}

function sayRead(st) {
  if (st.saidRead || !st.result) return;
  const line = st.result.read || st.result.summary;
  if (line) { st.saidRead = true; try { J.setLastNote(line); J.say(line); } catch (e) {} }
}

async function confirmMission(mid, item) {
  const st = M.get(mid); if (!st) return;
  try {
    const r = await J.post('/mission_confirm', { id: mid, item }, 20000);
    if (r && r.error) { J.say(r.error); return; }
    if (r && r.answer) J.say(r.answer);
    st.finalPolled = false;
    schedule(mid, 900);
  } catch (e) { J.say("The confirmation didn't go through, sir."); }
}

// ---------- dock cards ----------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

function addCard(st) {
  const c = el('div', 'jm-card');
  const h = el('div', 'jm-h');
  h.appendChild(el('span', 'jm-ic', KINDS[st.kind].icon));
  h.appendChild(el('span', 'jm-t', st.title));
  st.led = el('span', 'jm-led run');
  h.appendChild(st.led);
  const x = el('button', 'jm-x', '✕');
  x.title = 'Dismiss';
  x.onclick = () => dismiss(st);
  h.appendChild(x);
  c.appendChild(h);
  st.feedEl = el('div', 'jm-feed');
  c.appendChild(st.feedEl);
  if (st.kind === 'buildapp' || st.kind === 'build') {   // stage tracker lives from birth
    st.stageEl = el('div', 'jm-stage');
    for (const sName of STAGES) { const sp = el('span', '', sName); sp.dataset.s = sName; st.stageEl.appendChild(sp); }
    c.appendChild(st.stageEl);
    markStage(st, 'SCAFFOLD');
  }
  st.resEl = el('div', 'jm-res');
  c.appendChild(st.resEl);
  st.el = c;
  dock.appendChild(c);
}

function dismiss(st) {
  st.dead = true;
  clearTimeout(st.timer);
  if (st.status === 'running') { try { J.post('/mission_cancel', { id: st.id }, 8000); } catch (e) {} }
  if (st.kind === 'fleet') fleetRetire(st, false);
  try { st.el.remove(); } catch (e) {}
  M.delete(st.id);
}

function setLed(st) {
  if (!st.led) return;
  st.led.className = 'jm-led ' + (st.status === 'done' ? 'done' : st.status === 'error' ? 'err'
    : st.status === 'awaiting_confirm' ? 'wait' : 'run');
}

function onEvent(st, ev) {
  if (!st.feedEl) { if (window.__teardownMission) window.__teardownMission.event(st, ev); return; }   // S29c: panel-hosted mission
  // feed line (keep the last 8)
  const row = document.createElement('div');
  const b = el('b', '', ev.agent);
  b.style.color = AGENT_COLOR[ev.agent] || '#7fa89a';
  row.appendChild(b);
  row.appendChild(document.createTextNode(' · ' + (ev.label || ev.kind)));
  if (ev.kind === 'error') row.style.color = '#ff9d8f';
  st.feedEl.appendChild(row);
  while (st.feedEl.childNodes.length > 8) st.feedEl.removeChild(st.feedEl.firstChild);
  st.feedEl.scrollTop = st.feedEl.scrollHeight;
  // kind-specific reactions
  if (ev.kind === 'stage') markStage(st, ev.label);
  if (st.kind === 'announce') {
    const m = String(ev.label || '').match(/^([✓✗])\s*(\w+)/);
    if (m) markPlatform(st, m[2].toLowerCase(), m[1] === '✓');
  }
  if (st.kind === 'fleet') fleetOnEvent(st, ev);
}

function markStage(st, name) {
  if (!st.stageEl) return;
  st.stages.add(String(name).toUpperCase());
  // light every stage up to the furthest reached
  let last = -1;
  STAGES.forEach((sName, i) => { if (st.stages.has(sName)) last = Math.max(last, i); });
  [...st.stageEl.children].forEach((sp, i) => sp.classList.toggle('on', i <= last));
}

// ---------- result UIs ----------
function renderResult(st) {
  const r = st.result;
  if (!r) return;
  st.rendered = true;
  if (!st.resEl) return;                               // S29c: panel-hosted missions have no dock card
  const box = st.resEl;
  box.textContent = '';
  if (st.kind === 'fleet') {
    box.appendChild(el('div', '', r.summary || 'The fleet has landed, sir.'));
    const meta = el('div', '');
    meta.style.cssText = 'margin-top:4px;font-size:9px;color:#5a6b62;';
    const sz = k => ((r.sections || {})[k] || '').length;
    meta.textContent = `scout ${sz('scout')}ch · forge ${sz('forge')}ch · sage ${sz('sage')}ch — ${r.file || ''}`;
    box.appendChild(meta);
  }
  else if (st.kind === 'buildapp') {
    if (r.note) box.appendChild(el('div', '', r.note));
    if (r.url) {
      const b = el('button', 'jm-btn', 'Open the app');
      b.onclick = () => openUrl(r.url);
      box.appendChild(b);
    }
  }
  else if (st.kind === 'rea') {                        // S29: the teardown lives in the vault; read it in the same reader
    box.appendChild(el('div', '', r.summary || r.spoken || 'The teardown is in your vault, sir.'));
    const b = el('button', 'jm-btn', 'Read the full teardown');
    b.onclick = () => { if (window.__teardownReader) window.__teardownReader(r.rel || null); };
    box.appendChild(b);
  }
  else if (st.kind === 'build') {                      // S29: what he built + how the hidden-browser test went
    if (r.note) box.appendChild(el('div', '', r.note));
    const t = r.test || {};
    const line = el('div', '');
    line.style.cssText = 'margin-top:4px;font-size:9.5px;color:' + (t.ok ? '#34d399' : t.ok === false ? '#ff9d8f' : '#5a6b62') + ';';
    line.textContent = t.ok ? '✓ tested in a hidden browser — 0 errors' + (t.fixed ? ` (${t.fixed} fixed on the way)` : '')
      : t.ok === false ? `✗ ${(t.errors || []).length} error(s) remain after a repair pass` : 'not tested';
    box.appendChild(line);
    if (r.shot) {
      const img = document.createElement('img'); img.src = r.shot; img.alt = '';
      img.style.cssText = 'display:block;width:100%;height:96px;object-fit:cover;object-position:top;border-radius:8px;margin-top:6px;border:1px solid rgba(52,211,153,.18);box-sizing:border-box;';
      box.appendChild(img);
    }
    if (r.url) { const b = el('button', 'jm-btn', 'Open it'); b.onclick = () => { J.post('/mission_open', { id: st.id }, 15000).catch(() => openUrl(r.url)); }; box.appendChild(b); }
  }
  else if (st.kind === 'reaper') renderReaper(st, box);
  else if (st.kind === 'warroom') renderWarroom(st, box);
  else if (st.kind === 'announce') renderAnnounce(st, box);
  else if (st.kind === 'haters') renderHaters(st, box);
}

function renderReaper(st, box) {
  const r = st.result;
  const total = Number(r.total_monthly) || 0;
  const tick = el('div', 'jm-total', '$0.00');
  const small = el('small', '', ' /mo found');
  tick.appendChild(small);
  box.appendChild(tick);
  const t0 = performance.now();                        // count-up ticker
  (function up(ts) {
    const p = Math.min(1, (ts - t0) / 1300), v = total * (1 - Math.pow(1 - p, 3));
    if (tick.firstChild) tick.firstChild.nodeValue = '$' + v.toFixed(2);
    if (p < 1) requestAnimationFrame(up);
  })(t0);
  const drafted = new Set(((st.pending || {}).drafted) || []);
  for (const s of (r.subs || [])) {
    const row = el('div', 'jm-row');
    row.appendChild(el('span', 'n', s.name + (s.cadence === 'annual' ? ' (annual)' : '')));
    row.appendChild(el('span', 'a', '$' + Number(s.amount_monthly || 0).toFixed(2)));
    if (drafted.has(s.name)) { row.classList.add('drafted'); row.appendChild(el('span', 'a', 'DRAFTED')); }
    else {
      const keep = el('button', '', 'KEEP');
      keep.onclick = () => { row.classList.add('dead'); keep.remove(); kill.remove(); };
      const kill = el('button', 'kill', 'KILL');
      kill.onclick = () => {
        row.classList.add('drafted', 'flash');
        keep.remove(); kill.remove();
        row.appendChild(el('span', 'a', 'DRAFTED'));
        confirmMission(st.id, s.name);
      };
      row.appendChild(keep); row.appendChild(kill);
    }
    box.appendChild(row);
  }
}

function renderWarroom(st, box) {
  const r = st.result, s = r.stats || {};
  box.appendChild(el('div', '', r.headline || ''));
  const grid = el('div', 'jm-stats');
  const stat = (v, l) => { const d = el('div', 'jm-stat'); d.appendChild(el('b', '', String(v ?? '—'))); d.appendChild(el('i', '', l)); return d; };
  grid.appendChild(stat(s.views_24h, 'views 24h'));
  grid.appendChild(stat(s.median_delta, 'vs median'));
  grid.appendChild(stat(s.subs, 'subs'));
  grid.appendChild(stat(s.watch_hours, 'watch hrs'));
  box.appendChild(grid);
  for (const v of (r.videos || []).slice(0, 3)) {
    const row = el('div', 'jm-row');
    row.appendChild(el('span', 'n', v.title || ''));
    row.appendChild(el('span', 'a', String(v.views ?? '')));
    box.appendChild(row);
  }
  for (const c of (r.comments || []).slice(0, 3)) {
    const d = el('div', 'jm-com');
    d.appendChild(el('div', 'au', (c.author || 'someone') + (c.likes ? ` · ${c.likes} likes` : '')));
    d.appendChild(el('div', 'cm', c.text || ''));
    box.appendChild(d);
  }
  sayRead(st);   // spoken as soon as the report renders, even while awaiting nothing
}

function renderAnnounce(st, box) {
  const r = st.result;
  st.platEls = {};
  for (const p of (r.posts || [])) {
    const d = el('div', 'jm-post');
    const head = el('div', 'p');
    head.appendChild(el('span', '', p.platform));
    const mk = el('span', 'mk', st.marks[p.platform] || '');
    head.appendChild(mk);
    st.platEls[p.platform] = mk;
    d.appendChild(head);
    d.appendChild(el('div', 'tx', p.text));
    box.appendChild(d);
  }
  if (st.status === 'awaiting_confirm') {
    const b = el('button', 'jm-btn', 'Approve all — post it');
    b.onclick = () => { b.disabled = true; b.textContent = 'Posting…'; confirmMission(st.id, 'all'); };
    box.appendChild(b);
  }
  for (const [plat, mark] of Object.entries(st.marks)) markPlatform(st, plat, mark === '✓');
}

function markPlatform(st, plat, ok) {
  st.marks[plat] = ok ? '✓' : '✗';
  const e = (st.platEls || {})[plat];
  if (e) { e.textContent = st.marks[plat]; e.style.color = ok ? '#34d399' : '#ff5d5d'; }
}

function renderHaters(st, box) {
  const r = st.result;
  const posted = new Set(((st.pending || {}).posted) || []);
  (r.items || []).forEach((it, i) => {
    const d = el('div', 'jm-com');
    d.appendChild(el('div', 'au', (it.author || 'someone') + (it.likes ? ` · ${it.likes} likes` : '')));
    d.appendChild(el('div', 'cm', it.comment || ''));
    d.appendChild(el('div', 'rp', it.reply || ''));
    if (posted.has(i)) d.appendChild(el('span', 'a', 'POSTED'));
    else {
      const b = el('button', 'jm-btn', 'Post reply');
      b.style.marginTop = '4px';
      b.onclick = () => { b.disabled = true; b.textContent = 'Posting…'; confirmMission(st.id, String(i)); };
      d.appendChild(b);
    }
    box.appendChild(d);
  });
  if ((r.items || []).length && st.status === 'awaiting_confirm') {
    const all = el('button', 'jm-btn', 'Post all');
    all.onclick = () => { all.disabled = true; all.textContent = 'Posting…'; confirmMission(st.id, 'all'); };
    box.appendChild(all);
  }
  sayRead(st);
}

// ---------- FLEET ORBS: three glowing agents flying the graph while the fleet works ----------
const FLEET_DEF = [['SCOUT', 0x62dbff], ['FORGE', 0xf4a93a], ['SAGE', 0xb58cff]];
let fleetRaf = 0;
const activeFleets = new Set();

function graphRadius() {
  let r = 240;
  try {
    const ns = OS.data.nodes;
    let m = 0;
    for (let i = 0; i < ns.length; i += 7) {
      const n = ns[i];
      if (Number.isFinite(n.x)) m = Math.max(m, Math.abs(n.x), Math.abs(n.y), Math.abs(n.z));
    }
    if (m > 40) r = Math.min(m, 420);
  } catch (e) {}
  return r;
}
function midNodePos() {
  try {
    const ns = OS.data.nodes.filter(n => Number.isFinite(n.x) && n.dg >= 3 && n.dg <= 40);
    if (!ns.length) return null;
    const n = ns[(Math.random() * ns.length) | 0];
    return new THREE.Vector3(n.x, n.y, n.z);
  } catch (e) { return null; }
}
function driftPoint(R) {
  const v = new THREE.Vector3().randomDirection();
  return v.multiplyScalar(R * (0.35 + Math.random() * 0.55));
}

function fleetSpawn(st) {
  let scene;
  try { scene = OS.Graph.scene(); } catch (e) { return; }
  if (!scene || !scene.add) return;
  const group = new THREE.Group();
  group.name = 'jm-fleet-' + st.id;
  const R = graphRadius();
  st.orbs = {};
  for (const [name, color] of FLEET_DEF) {
    const o = new THREE.Group();
    const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.92,
      blending: THREE.AdditiveBlending, depthWrite: false });
    const halo = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.18,
      blending: THREE.AdditiveBlending, depthWrite: false });
    o.add(new THREE.Mesh(new THREE.SphereGeometry(6, 20, 20), mat));
    o.add(new THREE.Mesh(new THREE.SphereGeometry(10, 14, 14), halo));
    let label = null;
    try {
      label = new SpriteText(name, 7, '#' + color.toString(16).padStart(6, '0'));
      label.position.y = 15; label.material.depthWrite = false;
      o.add(label);
    } catch (e) {}
    o.position.set(0, 0, 0);
    group.add(o);
    st.orbs[name] = { obj: o, mats: [mat, halo], label, mode: 'burst', t0: performance.now(),
                      from: new THREE.Vector3(0, 0, 0), to: driftPoint(R), target: null,
                      orbitUntil: 0, phase: Math.random() * Math.PI * 2, alive: true, R };
  }
  st.fleetGroup = group;
  scene.add(group);
  activeFleets.add(st);
  if (!fleetRaf) fleetRaf = requestAnimationFrame(fleetTick);
}

function fleetOnEvent(st, ev) {
  const orb = st.orbs && st.orbs[ev.agent];
  if (!orb || !orb.alive) return;
  if (ev.kind === 'tool' || ev.kind === 'read' || ev.kind === 'write') {
    const p = midNodePos();
    if (p) { orb.target = p; orb.mode = 'seek'; orb.from = orb.obj.position.clone(); orb.t0 = performance.now(); }
  } else if (ev.kind === 'done' || ev.kind === 'error') {
    orb.mode = 'return'; orb.from = orb.obj.position.clone(); orb.t0 = performance.now();
  }
}

function fleetRetire(st, graceful) {
  if (!st.orbs) return;
  if (!graceful) return fleetRemove(st);
  for (const orb of Object.values(st.orbs)) {
    if (orb.alive && orb.mode !== 'return' && orb.mode !== 'pulse' && orb.mode !== 'gone') {
      orb.mode = 'return'; orb.from = orb.obj.position.clone(); orb.t0 = performance.now();
    }
  }
  setTimeout(() => fleetRemove(st), 6000);            // hard ceiling — never linger
}

function fleetRemove(st) {
  if (!st.fleetGroup) return;
  try {
    const scene = OS.Graph.scene();
    scene.remove(st.fleetGroup);
    st.fleetGroup.traverse(o => {
      if (o.geometry) try { o.geometry.dispose(); } catch (e) {}
      if (o.material) try { o.material.dispose(); } catch (e) {}
    });
  } catch (e) {}
  st.fleetGroup = null; st.orbs = null;
  activeFleets.delete(st);
}

const ease = p => 1 - Math.pow(1 - Math.min(1, Math.max(0, p)), 3);
function fleetTick(now) {
  fleetRaf = 0;
  let any = false;
  for (const st of [...activeFleets]) {
    if (!st.orbs) { activeFleets.delete(st); continue; }
    for (const orb of Object.values(st.orbs)) {
      if (!orb.alive) continue;
      any = true;
      try { stepOrb(orb, now); } catch (e) { orb.alive = false; }
    }
  }
  if (any) fleetRaf = requestAnimationFrame(fleetTick);
}

function stepOrb(orb, now) {
  const pos = orb.obj.position, t = (now - orb.t0) / 1000;
  if (orb.mode === 'burst') {                                   // out from the graph's heart
    pos.lerpVectors(orb.from, orb.to, ease(t / 1.1));
    if (t > 1.1) { orb.mode = 'drift'; orb.t0 = now; orb.from = pos.clone(); orb.to = driftPoint(orb.R); }
  } else if (orb.mode === 'drift') {                            // smooth noise wander among the nodes
    const p = ease(t / 4.5);
    pos.lerpVectors(orb.from, orb.to, p);
    pos.x += Math.sin(now / 900 + orb.phase) * 4;
    pos.y += Math.sin(now / 1300 + orb.phase * 2) * 4;
    pos.z += Math.cos(now / 1100 + orb.phase) * 4;
    if (t > 4.5) { orb.t0 = now; orb.from = pos.clone(); orb.to = driftPoint(orb.R); }
  } else if (orb.mode === 'seek') {                             // fly to the node it's "working"
    pos.lerpVectors(orb.from, orb.target, ease(t / 0.9));
    if (t > 0.9) { orb.mode = 'orbit'; orb.orbitUntil = now + 2000; orb.t0 = now; }
  } else if (orb.mode === 'orbit') {                            // tight 2s orbit around it
    const a = now / 260 + orb.phase, r = 16;
    pos.set(orb.target.x + Math.cos(a) * r, orb.target.y + Math.sin(a * 1.3) * r * 0.5, orb.target.z + Math.sin(a) * r);
    if (now > orb.orbitUntil) { orb.mode = 'drift'; orb.t0 = now; orb.from = pos.clone(); orb.to = driftPoint(orb.R); }
  } else if (orb.mode === 'return') {                           // home to the heart…
    pos.lerpVectors(orb.from, new THREE.Vector3(0, 0, 0), ease(t / 1.2));
    if (t > 1.2) { orb.mode = 'pulse'; orb.t0 = now; }
  } else if (orb.mode === 'pulse') {                            // …pulse, fade, gone
    const p = Math.min(1, t / 1.2), k = 1 + 1.6 * Math.sin(p * Math.PI);
    orb.obj.scale.set(k, k, k);
    for (const m of orb.mats) m.opacity = Math.max(0, (m === orb.mats[0] ? 0.92 : 0.18) * (1 - p));
    if (orb.label) orb.label.material.opacity = 1 - p;
    if (p >= 1) { orb.alive = false; orb.obj.visible = false; orb.mode = 'gone'; }
  }
}
