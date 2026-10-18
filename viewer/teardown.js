// teardown.js — Jarvis TEARDOWN organ (S28, 2026-10-13): REA website teardowns.
// "Jarvis, reverse engineer igloo dot inc" / "how does linear.app do that" / "tear down this site".
// The server bay (teardown.py) opens a clean Chrome window, REA captures the page while Jarvis
// scrolls it, and the brain writes an evidence-cited note into the vault. This organ owns the
// voice routes, the live TEARDOWN panel (steps → snapshot → stack chips), and the moment the
// note is born in the galaxy under the REA concept node.
// ⚖ The panel never auto-hides (his rule: instruments stay until he dismisses them).
// ⚖ Focus belongs to the answer path: the organ births nodes through __os.addNote, which flies
//   to the newborn exactly like a "remember that" capture — nothing else touches the camera.
// Fully optional: if the bridge never appears, this module does nothing.

let J, OS, panel, timer = null, cur = null;


function init() {
  J = window.__jarvis; OS = window.__os;
  injectStyle();
  routes();
  watchFit();
  window.__teardownAdopt = job => adopt(job, false);   // the brain's [TEARDOWN:] tag path (answer() speaks the ack)
  window.__teardownReader = rel => openReader(rel || null);   // S29: the mission dock's "Read the full teardown"
  window.__teardownBirth = res => birth(res);                 // S29: REA worker missions birth their note the same way
  window.__teardownMission = { start: missionStart, event: missionEvent, done: missionDone };   // S29c: the app teardown lives HERE
}

// ---------- voice routes ----------
// Only phrasings that NAME a site (a dotted address, localhost, or "this site") are caught here;
// "reverse engineer Stripe's homepage" has no address, so the brain resolves it and emits the tag.
const DOMAIN = String.raw`(?:https?:\/\/)?(?:[a-z0-9-]+\s*(?:\.|\bdot\b)\s*)+[a-z]{2,24}(?:\s*(?:\/|\bslash\b)\s*[\w-]+)*|localhost(?:\s*(?::|\bcolon\b)\s*\d{2,5})?|this (?:site|page|website|tab|one)|(?:the )?current (?:tab|site|page)`;
// S29g (2026-10-13, for the 7.2 kit): ANY member, ANY phrasing. The verbs that mean "take it apart"; the words
// that say the thing is a site or an app (a sentence needs one of these before a vaguer verb like "break down",
// "analyze" or "how is X built" is treated as a teardown, so "break down my week" stays with the galaxy/brain).
const VERBS = String.raw`reverse[- ]?engineer(?:ing)?|tear(?:ing)?\s+down|teardown|take apart|taking apart|dissect(?:ing)?|x-?ray(?:ing)?|deconstruct(?:ing)?|decompile|pick apart|pull apart`;
const SOFT_VERBS = String.raw`break(?:ing)? down|analy[sz]e|analy[sz]ing|inspect(?:ing)?|investigate|study|audit|look under the hood of|look into|dig into|figure out`;
const SIGNAL = String.raw`(?:website|web ?site|site|web ?page|homepage|landing page|url|domain|app|application|program|software|file|zip|dmg|package|bundle|binary|exe|installer|on my (?:mac|computer|pc|laptop)|dot (?:com|inc|io|ai|app|co|org|net|dev)|\.(?:com|inc|io|ai|app|co|org|net|dev)\b|\.(?:zip|dmg|exe|apk|ipa|asar)\b)`;
const HAS_SIGNAL = new RegExp(String.raw`\b` + SIGNAL, 'i');
const TD = new RegExp(String.raw`\b(?:` + VERBS + '|' + SOFT_VERBS + String.raw`)\b.*?(` + DOMAIN + `)`, 'i');
const HOW = new RegExp(String.raw`\bhow (?:does|did|do|is|was|are) (?:the (?:site |website )?)?(` + DOMAIN + String.raw`) (?:do|doing|make|build|pull off|get|create|achieve|animate|work|built|made|done|run)\b`, 'i');
const WHAT = new RegExp(String.raw`\bwhat(?:'s| is| was) (` + DOMAIN + String.raw`) (?:built|made|running|coded) (?:with|in|on)\b`, 'i');
// no address in the sentence, but a site/app word → "how is the Notes app built", "what's the stripe website made with",
// "what tech stack does igloo inc use", "analyze the linear app", "break down the stripe website"
const HOWB = new RegExp(String.raw`^(?=[\s\S]*\b` + SIGNAL + String.raw`)[\s\S]*?\bhow (?:does|did|do|is|was|are|were) (?:the |this |that |their )?(.+?) (?:built|made|coded|put together|work|working|run|do (?:that|this|it)|pull (?:that|this|it) off)\b`, 'i');
const WHATB = new RegExp(String.raw`^(?=[\s\S]*\b` + SIGNAL + String.raw`)[\s\S]*?\bwhat(?:'s| is| was| are)? ?(?:the )?(?:tech(?:nology)?(?: stack)?|stack|framework|library|libraries|engine) ?(?:does |did |is |are )?(?:the |this |that |their )?(.+?) (?:built|made|running|coded|written|developed|using|use|run on|made with|built with)\b|^(?=[\s\S]*\b` + SIGNAL + String.raw`)[\s\S]*?\bwhat(?:'s| is| was| are) (?:the |this |that |their )?(.+?) (?:built|made|running|coded|written|developed) (?:with|in|on)\b`, 'i');
const SOFT = new RegExp(String.raw`^(?=[\s\S]*\b` + SIGNAL + String.raw`)[\s\S]*?\b(?:` + SOFT_VERBS + String.raw`)\b\s+(?:how\s+)?(?:the\s+|my\s+|this\s+|that\s+)?(.+?)\s*[.?!]*\s*$`, 'i');
// "clone igloo.inc", "recreate the stripe website", "make me my own version of the Notes app" → teardown, THEN build
const CLONE = new RegExp(String.raw`^(?=[\s\S]*(?:\b` + SIGNAL + '|' + DOMAIN + String.raw`))[\s\S]*?\b(?:clone|recreate|re-?create|replicate|rebuild|re-?build|(?:make|build|create|code)(?: me)?(?: an?| my own| an? original)? (?:version|copy|clone|take|replica) of)\b\s+(?:the\s+|my\s+)?(?!(?:it|that|this|one)\b)(.+?)\s*[.?!]*\s*$`, 'i');
// "…and build me one" / "…then make my own version" after a teardown verb → the build follows the note automatically
const WANTS_BUILD = /\b(?:and|then|after that|afterwards|,)\s*(?:then\s+)?(?:build|make|create|code|recreate|clone|replicate|copy|rebuild)\b|\b(?:clone|recreate|re-?create|replicate|rebuild|re-?build)\b/i;
function cleanTarget(t) {
  return String(t || '').replace(/^(?:how\s+)?(?:the|this|that|their|my)\s+/i, '')
    .replace(/\s+(?:is|was|were|are|got|gets)\s+(?:built|made|coded|put together|done|created|developed)\b.*$/i, '')
    .replace(/\s+(?:for me|please|now|again|too|real quick|quickly)\s*$/i, '').trim();
}
const SHOW = /\b(?:show|open|bring up|pull up|read)(?: me)? (?:the |that |my )?(?:(?:last|latest|previous|earlier|recent) )?tear ?down\b(?:\s+(?:of|for|on|about)\s+(.+?))?\s*[.?!]*$/i;
const FULL = /\b(?:open|show|pull up|bring up|read)(?: me)? (?:the |that |my )?(?:(?:last|latest|previous|earlier|recent) )?(?:full|whole|entire|complete) tear ?down\b(?:\s+(?:of|for|on|about)\s+(.+?))?|\bopen (?:the |that )?tear ?down note\b/i;
const HIDE = /\b(?:close|hide|dismiss) (?:the |that )?tear ?down\b/i;
const STOP = /\b(?:cancel|stop|abort) (?:the |that )?tear ?down\b/i;
// S29e: the spoken walkthrough — opens the full note, then one or two spoken lines per section while the
// reader scrolls to each. Named ("…of the Apple notes") or the one on screen / the newest.
const SUMM = /\b(?:summari[sz]e|give me (?:a |the )?(?:quick |short |brief )?(?:summary|rundown|overview|walk ?through) of|walk me through|talk me through|read (?:me )?|explain)\s*(?:the |that |this |my )?(?:(?:last|latest|previous|full|whole|entire|complete) )*tear ?down\b(?:\s+(?:out loud|aloud|to me|and summari[sz]e it))?(?:\s+(?:of|for|on|about)\s+(.+?))?\s*[.?!]*$/i;
const SUMM_IT = /^(?:jarvis[,!\s]+)?(?:summari[sz]e (?:it|that|this)|give me (?:a |the )?(?:quick |short |brief )?(?:summary|rundown|overview) of (?:it|that|this)|walk me through (?:it|that|this))[.?!]*$/i;
// S29: the same verbs with NO address in the sentence — an app, a file, a package, a bundle name —
// go to the REA analyst mission (missions.js), which runs REA's whole catalog, not the browser path.
const OTHER = /\b(?:reverse[- ]?engineer(?:ing)?|tear(?:ing)?\s+down|take apart|dissect|x-?ray)\b\s+(?:the\s+|my\s+)?(.+?)\s*[.?!]*\s*$/i;   // verbs only: "open the previous teardown of X" is never a new job

function routes() {
  const R = (window.__jarvisRoutes = window.__jarvisRoutes || []);
  R.push({ re: STOP, handler: async () => { stopWalk(); cancel(); } });
  const walkCurrent = async (q, named) => {
    const open = reader && reader.style.display === 'flex';
    const rel = open ? readerRel : ((cur && cur.result && cur.result.rel) || (mis && mis.result && mis.result.rel) || null);
    await walkthrough(named ? null : rel, named);          // no name + nothing on screen → the newest note on file
  };
  R.push({ re: SUMM, handler: async (q, m) => walkCurrent(q, m && m[1] ? q : null) });
  R.push({ re: SUMM_IT, handler: async q => {              // pronouns only count when a teardown is on screen
    const open = reader && reader.style.display === 'flex';
    if (!open && !cur && !mis) { await J.say("Which teardown, sir? Name one, or open it first."); return; }
    await walkCurrent(q, null);
  } });
  R.push({ re: HIDE, handler: async () => { close(); await J.say('Put away, sir.'); } });
  R.push({ re: FULL, handler: async (q, m) => { const ok = await openReader(m && m[1] ? null : (cur && cur.result && cur.result.rel), m && m[1] ? q : null); if (ok) await J.say('The full teardown, sir.'); } });
  R.push({ re: SHOW, handler: async (q, m) => {
    if (m && m[1]) { if (await openReader(null, q)) await J.say('That teardown, sir.'); return; }   // named: straight to the reader
    showLast();
  } });
  for (const re of [TD, HOW, WHAT]) R.push({ re, handler: async (q, m) => launch(m[1], q, WANTS_BUILD.test(q)) });
  // S29f/g: every address-less phrasing goes to the server's dispatcher, which decides what was meant
  // ("Igloo ink" → igloo.inc, "it" → the site named earlier in the sentence or the tab he's on, "the Notes
  // app" → the REA mission) — and asks back instead of guessing. CLONE always chains a build.
  const viaDispatch = (pick, forceBuild) => async (q, m) => {
    const target = cleanTarget(pick(m));
    let r = null;
    try { r = await J.post('/teardown/dispatch', { target, question: q, session: J.session, then_build: forceBuild || WANTS_BUILD.test(q) }, 20000); }
    catch (e) { await J.say("My teardown kit didn't answer, sir."); return; }
    if (!r) { await J.say('The teardown refused, sir.'); return; }
    if (r.teardown) { await adopt(r.teardown, false); }
    else if (r.mission && window.__missionAdopt) window.__missionAdopt(r.mission);
    if (r.answer) await J.say(r.answer);
  };
  R.push({ re: CLONE, handler: viaDispatch(m => m[1], true) });
  R.push({ re: OTHER, handler: viaDispatch(m => m[1], false) });
  R.push({ re: HOWB, handler: viaDispatch(m => m[1], false) });
  R.push({ re: WHATB, handler: viaDispatch(m => m[1] || m[2], false) });
  R.push({ re: SOFT, handler: viaDispatch(m => m[1], false) });
}

async function launch(target, question, thenBuild) {
  let r;
  try { r = await J.post('/teardown', { target, question, session: J.session, then_build: !!thenBuild }, 20000); }
  catch (e) { await J.say("My teardown kit didn't answer, sir."); return; }
  if (!r || r.error || !r.id) { await J.say((r && r.error) || 'The teardown refused, sir.'); return; }
  await adopt(r, true);
}

async function adopt(job, speakAck) {
  if (!job || !job.id) return;
  cur = { id: job.id, host: job.host || '', since: 0, steps: {}, done: false };
  render();
  J.status && J.status('● REA is taking ' + (job.host || 'the site') + ' apart…');
  clearTimeout(timer); timer = setTimeout(poll, 600);
  if (speakAck && job.ack) await J.say(job.ack);
}

async function poll() {
  if (!cur || cur.done) return;
  let d;
  try { d = await fetch('/teardown/status?id=' + encodeURIComponent(cur.id) + '&since=' + cur.since).then(r => r.json()); }
  catch (e) { timer = setTimeout(poll, 2000); return; }
  if (!d || d.error) { timer = setTimeout(poll, 2000); return; }
  cur.since = typeof d.next === 'number' ? d.next : cur.since;
  for (const ev of (d.events || [])) cur.steps[ev.step] = ev;
  cur.status = d.status;
  if (d.status === 'done' && d.result) { cur.done = true; cur.result = d.result; render(); J.status && J.status(''); finish(d.result); return; }
  if (d.status === 'error') { cur.done = true; cur.error = d.error; render(); J.status && J.status('');
    await J.say("The teardown hit a snag, sir — " + String(d.error || 'unknown').replace(/\.$/, '') + '.'); return; }
  render();
  timer = setTimeout(poll, document.hidden ? 2500 : 700);
}

async function finish(res) {
  await birth(res);
  try { J.setLastNote(res.summary || res.spoken || ''); } catch (_) {}
  await J.say(res.spoken || ('I have taken ' + (res.host || 'it') + ' apart, sir. The full teardown is on screen.'));
  if (res.next_mission && window.__missionAdopt) {                      // S29g: "…and build me my own version"
    window.__missionAdopt(res.next_mission);
    await J.say("Now building your own version from that teardown, sir. I'll test it before I open it.");
  }
}
async function birth(res) {
  // birth the REA concept (first teardown ever), then the teardown note hanging off it
  try {
    const nodes = OS.data.nodes;
    // S29: idempotent — the server persisted the note already; if this page was loaded after that
    // (a mission adopted late, a reload mid-mission) the node is on screen and must not be born twice
    if (nodes.some(n => (res.rel && n.id === res.rel) || (res.label && String(n.label || '') === String(res.label)))) return;
    const at = (i, label) => (typeof i === 'number' && nodes[i] && (!label || String(nodes[i].label) === label)) ? i : -1;
    let reaIdx = at(res.rea_idx, 'REA');                 // the server's index first — both sides must agree
    if (reaIdx < 0) reaIdx = nodes.findIndex(n => String(n.label || '') === 'REA');
    if (reaIdx < 0 && res.concept) {
      let aIdx = at(res.concept.anchor_idx, res.concept.anchor_label);
      if (aIdx < 0) aIdx = nodes.findIndex(n => /^jarvis\b/i.test(String(n.label || '')));
      OS.addNote(res.concept.label, res.concept.text, aIdx >= 0 ? aIdx : null, res.concept.group || 'concept');
      reaIdx = OS.data.nodes.length - 1;
      await new Promise(r => setTimeout(r, 1900));    // let the concept's birth pulse land first
    }
    OS.addNote(res.label, res.summary || res.label, reaIdx >= 0 ? reaIdx : null, 'note');
  } catch (e) { console.warn('[teardown] birth', e); }
}

async function cancel() {
  if (!cur || cur.done) { await J.say('Nothing is being taken apart right now, sir.'); return; }
  try { await J.post('/teardown/cancel', { id: cur.id }, 8000); } catch (_) {}
  await J.say('Stopping the teardown, sir. The browser will close.');
}

async function showLast() {
  let d = null;
  try { d = await fetch('/teardown/status').then(r => r.json()); } catch (_) {}
  if (!d || d.error || !d.result) {
    if (await openReader(null)) { await J.say('The last teardown on file, sir.'); return; }
    await J.say("There's no teardown on file yet, sir. Name a site and I'll take it apart."); return;
  }
  cur = { id: d.id, host: d.host, since: d.next, steps: {}, done: true, result: d.result, status: d.status };
  for (const ev of (d.events || [])) cur.steps[ev.step] = ev;
  render();
  await J.say('The last teardown, sir — ' + (d.result.host || d.host) + '.');
}

function close() { clearTimeout(timer); stopWalk(); if (panel) panel.style.display = 'none'; closeReader(); }

// ---------- the full teardown reader ----------
let reader = null, readerPath = '', readerRel = '';
function inline(t) {
  return t.replace(/`([^`]+)`/g, '<code>$1</code>')
          .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
          .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\*)/g, '$1<i>$2</i>')
          .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, '<span class="tr-wl">$2</span>')
          .replace(/\[\[([^\]]+)\]\]/g, '<span class="tr-wl">$1</span>')
          .replace(/\[([^\]]+)\]\((?:[^)]+)\)/g, '$1');
}
function renderMd(md, assets) {
  const out = []; let list = null;
  const endList = () => { if (list) { out.push('</' + list + '>'); list = null; } };
  for (const raw of String(md || '').split('\n')) {
    const line = esc(raw);
    let m;
    if (!line.trim()) { endList(); continue; }
    if ((m = line.match(/^!\[\[([^\]]+)\]\]$/))) { endList(); out.push(`<img src="/teardown/asset?rel=${encodeURIComponent(assets + m[1])}" alt="">`); continue; }
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) { endList(); const n = m[1].length; out.push(`<h${n}>${inline(m[2])}</h${n}>`); continue; }
    if ((m = line.match(/^&gt;\s?(.*)$/))) { endList(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
    if ((m = line.match(/^\s*[-*]\s+(.*)$/))) { if (list !== 'ul') { endList(); out.push('<ul>'); list = 'ul'; } out.push(`<li>${inline(m[1])}</li>`); continue; }
    if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) { if (list !== 'ol') { endList(); out.push('<ol>'); list = 'ol'; } out.push(`<li>${inline(m[1])}</li>`); continue; }
    endList();
    out.push(/^(?:Site|Asked):/.test(raw) ? `<p class="tr-meta">${inline(line)}</p>` : `<p>${inline(line)}</p>`);
  }
  endList();
  return out.join('');
}
async function openReader(rel, hint) {
  let d = null;
  const qs = rel ? '?rel=' + encodeURIComponent(rel) : (hint ? '?hint=' + encodeURIComponent(hint) : '');
  try { d = await fetch('/teardown/note' + qs).then(r => r.json()); } catch (_) {}
  if (!d || d.error || !d.markdown) { await J.say("I can't find that teardown note, sir."); return false; }
  if (!reader) {
    reader = document.createElement('div'); reader.id = 'j-td-reader';
    reader.innerHTML = `<div class="tr-card"><div class="tr-head"><span class="tr-k">TEARDOWN</span><span class="tr-title"></span>
      <button class="tr-btn tr-obs">Open in Obsidian</button><button class="tr-btn tr-x">Close</button></div><div class="tr-body"></div></div>`;
    document.body.appendChild(reader);
    reader.addEventListener('click', e => {
      if (e.target === reader || (e.target.classList && e.target.classList.contains('tr-x'))) closeReader();
      if (e.target.classList && e.target.classList.contains('tr-obs') && readerPath) location.href = 'obsidian://open?path=' + encodeURIComponent(readerPath);
    });
    addEventListener('keydown', e => { if (e.key === 'Escape' && reader && reader.style.display === 'flex') closeReader(); });
  }
  readerPath = d.path || ''; readerRel = d.rel || '';
  reader.querySelector('.tr-title').textContent = String(d.label || '').replace(/^Teardown\s*·\s*/i, '');
  // the note's own '# Teardown · host' line is the header already — don't print it twice
  reader.querySelector('.tr-body').innerHTML = renderMd(String(d.markdown).replace(/^#\s+.*\n/, ''), d.assets || '');
  reader.querySelector('.tr-body').scrollTop = 0;
  reader.style.display = 'flex';
  // "read it out loud" reads the note's answer section, not all ~700 words
  try {
    const m = String(d.markdown).match(/##\s*The answer\s*\n([\s\S]*?)(?=\n##\s|$)/i);
    const said = (m ? m[1] : String(d.markdown).slice(0, 900)).replace(/!\[\[[^\]]+\]\]/g, '').replace(/\[\[([^\]|]+\|)?([^\]]+)\]\]/g, '$2').replace(/[#>*`]/g, '').trim();
    if (said) J.setLastNote(said);
  } catch (_) {}
  return true;
}
function closeReader() { stopWalk(); if (reader) reader.style.display = 'none'; }

// ---------- S29e: the walkthrough ----------
let walkId = 0;
function stopWalk() { walkId++; if (reader) for (const h of reader.querySelectorAll('.tr-now')) h.classList.remove('tr-now'); }
async function walkthrough(rel, hint) {
  const ok = await openReader(rel, hint);
  if (!ok) return;
  const my = ++walkId;
  J.status && J.status('● reading the teardown…');
  let d = null;
  try { d = await J.post('/teardown/summary', { rel: readerRel }, 60000); } catch (_) {}
  J.status && J.status('');
  if (my !== walkId) return;
  if (!d || d.error || !(d.sections || []).length) { await J.say((d && d.error) || "I couldn't put the walkthrough together, sir."); return; }
  const body = reader.querySelector('.tr-body');
  const heads = [...body.querySelectorAll('h2')];
  const spoken = [];
  for (const sec of d.sections) {
    if (my !== walkId) return;
    const h = heads.find(x => x.textContent.trim().toLowerCase() === String(sec.title || '').trim().toLowerCase())
           || heads.find(x => x.textContent.trim().toLowerCase().startsWith(String(sec.title || '').trim().toLowerCase().slice(0, 8)));
    for (const x of heads) x.classList.remove('tr-now');
    if (h) { h.classList.add('tr-now'); body.scrollTo({ top: Math.max(0, h.offsetTop - 18), behavior: 'smooth' }); }
    spoken.push(sec.say);
    await J.say(sec.say);
  }
  if (my !== walkId) return;
  for (const x of heads) x.classList.remove('tr-now');
  if (d.closing) { spoken.push(d.closing); await J.say(d.closing); }
  try { J.setLastNote(spoken.join(' ')); } catch (_) {}
}
window.__teardownWalk = (rel, hint) => walkthrough(rel || null, hint || null);

// ---------- the panel ----------
const STEPS = [['open', 'Opening the site in a clean browser'], ['load', 'Waiting for it to load'],
  ['watch', 'REA is watching while I scroll'], ['bundle', 'REA is reading the code'], ['shot', 'Taking a snapshot'],
  ['assets', 'Listing everything it loaded'], ['stack', 'Identifying the stack'], ['write', 'Writing the teardown']];

function mb(n) { n = +n || 0; return n >= 104858 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'; }
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

function ensurePanel() {
  if (panel) return;
  panel = document.createElement('div'); panel.id = 'j-teardown';
  document.body.appendChild(panel);
  panel.addEventListener('click', e => {
    if (e.target && e.target.id === 'td-close') close();
    if (e.target && e.target.classList && e.target.classList.contains('td-read')) openReader(e.target.getAttribute('data-rel') || null);
  });
}

// ---------- S29c: the REA analyst mission (an app, a file, a package) lives in THIS panel ----------
// His call (2026-10-13 evening): the app teardown belonged top-left next to the sidebar, big, in the
// same instrument the site teardown uses — not a small card in the mission dock. missions.js keeps the
// polling and the ONE spoken line; this panel shows REA's live steps, then the stack chips and the button.
let mis = null;
const STEP_WORDS = [[/^read…$/, "Reading REA's playbook"], [/^glob…$/, 'Locating it on disk'], [/^grep…$/, 'Searching the code'],
  [/^toolsearch…$/, 'Choosing the right tool'], [/^REA: open binary…$/, 'REA: opening the target'], [/^REA: close binary…$/, 'REA: closing the target']];
function prettyStep(ev) {
  const k = ev.kind, l = String(ev.label || '');
  if (k === 'stage') return { ROUTE: 'Route chosen', INSPECT: 'Inspecting with REA', WRITE: 'Writing the teardown' }[l.toUpperCase()] || null;
  if (k === 'error') return l;
  if (k === 'write') return 'Saved to your vault';
  if (k === 'spawn') return l.startsWith('online') ? 'REA analyst online' : null;
  if (k !== 'read' && k !== 'tool') return null;
  for (const [re, w] of STEP_WORDS) if (re.test(l)) return w;
  return l.replace(/…$/, '');
}
function missionStart(st) {
  clearTimeout(timer); cur = null;                     // one investigation on screen at a time
  let target = String(st.brief || st.title || '').replace(/^REVERSE ENGINEER\s*[—–-]\s*/i, '').split('|')[0].trim() || 'the target';
  if (/^[~/]/.test(target)) target = target.replace(/\/+$/, '').split('/').pop() || target;   // a path → its file name
  mis = { id: st.id, target, t0: Date.now(), lines: [], calls: 0, done: false, result: null, error: null, stack: null, took: null };
  renderMission();
  J.status && J.status('● REA is taking ' + target + ' apart…');
}
function missionEvent(st, ev) {
  if (!mis || mis.id !== st.id) return;
  const label = prettyStep(ev); if (!label) return;
  if (/^REA: /.test(label)) mis.calls++;
  const last = mis.lines[mis.lines.length - 1];
  if (last && last.label === label && ev.kind !== 'error') last.n = (last.n || 1) + 1;
  else mis.lines.push({ label, kind: ev.kind, n: 1 });
  if (mis.lines.length > 80) mis.lines.shift();
  renderMission();
}
async function missionDone(st) {
  if (!mis || mis.id !== st.id) return;
  mis.done = true; mis.result = st.result || null;
  if (st.result && st.result.next_mission && window.__missionAdopt && !st.chained) {   // S29g: the build follows the app teardown
    st.chained = true; window.__missionAdopt(st.result.next_mission);
    setTimeout(() => { try { J.say("Now building your own version from that teardown, sir. I'll test it before I open it."); } catch (_) {} }, 2500);
  }
  mis.error = st.status === 'error' ? ((mis.lines.filter(l => l.kind === 'error').pop() || {}).label || 'the analysis failed') : null;
  mis.took = ((Date.now() - mis.t0) / 1000).toFixed(1);
  renderMission();
  J.status && J.status('');
  if (mis.result && mis.result.rel) { mis.stack = await stackChips(mis.result.rel); renderMission(); }
}
async function stackChips(rel) {                       // chips from the note's "## The stack" bullets
  try {
    const d = await fetch('/teardown/note?rel=' + encodeURIComponent(rel)).then(r => r.json());
    const m = String(d.markdown || '').match(/^##\s*The stack\s*\n([\s\S]*?)(?=^##\s|(?![\s\S]))/m);
    if (!m) return [];
    return m[1].split('\n').filter(l => /^\s*[-*]\s+/.test(l)).map(l => {
      const t = l.replace(/^\s*[-*]\s+/, '');
      const b = t.match(/^\*\*([^*]+)\*\*/);
      let name = (b ? b[1] : t).split(/\s[—–-]\s|\(|:|,|\s(?:in|with|plus|for|via|over|on)\s/)[0].replace(/[`*]/g, '').trim();
      if (name.length > 22) name = name.slice(0, 22).replace(/\s+\S*$/, '') + '…';   // short, cut on a word
      return name;
    }).filter(Boolean).slice(0, 8);
  } catch (_) { return []; }
}
function renderMission() {
  ensurePanel();
  panel.style.display = 'block';
  let html = `<div class="td-head"><span class="td-k">TEARDOWN</span><span class="td-host">${esc(mis.target)}</span>
    <span class="td-rea">via REA</span><button id="td-close" title="Close">Close</button></div>`;
  const shown = mis.done ? [] : mis.lines.slice(-9);
  html += `<div class="td-steps${mis.done ? ' td-folded' : ''}">`;
  shown.forEach((l, i) => {
    const st = l.kind === 'error' ? 'fail' : (i === shown.length - 1 ? 'run' : 'ok');
    const g = st === 'fail' ? '✕' : st === 'run' ? '●' : '✓';
    html += `<div class="td-step td-${st}"><span class="td-g">${g}</span><span class="td-l">${esc(l.label)}${l.n > 1 ? ' ×' + l.n : ''}</span></div>`;
  });
  html += '</div>';
  if (mis.done && mis.result) {
    html += `<div class="td-done"><span class="td-g">✓</span>Taken apart in ${esc(mis.took)} s</div>`;
    if (mis.result.shot) html += `<img class="td-shot${mis.result.shot_kind === 'icon' ? ' td-icon' : ''}" src="${esc(mis.result.shot)}" alt="">`;
    if (mis.stack && mis.stack.length) html += '<div class="td-sec">STACK</div><div class="td-chips">' + mis.stack.map(s => `<span class="td-chip">${esc(s)}</span>`).join('') + '</div>';
    html += `<div class="td-counts"><span><b>${mis.calls}</b> REA calls</span><span class="td-saved">✓ saved to your vault</span></div>` +
      `<button class="td-read" data-rel="${esc(mis.result.rel || '')}">Read the full teardown</button>`;
  } else if (mis.done && mis.error) {
    html += `<div class="td-err">${esc(mis.error)}</div>`;
  }
  panel.innerHTML = html;
  fit();
}

function render() {
  ensurePanel();
  panel.style.display = 'block';
  const c = cur || {};
  const res = c.result;
  let html = `<div class="td-head"><span class="td-k">TEARDOWN</span><span class="td-host">${esc((res && res.host) || c.host || '')}</span>
    <span class="td-rea">via REA</span><button id="td-close" title="Close">Close</button></div><div class="td-steps">`;
  for (const [k, label] of STEPS) {
    const ev = c.steps[k];
    const st = ev ? ev.state : (c.done ? 'skip' : 'wait');
    const glyph = st === 'ok' ? '✓' : st === 'run' ? '●' : st === 'warn' ? '!' : st === 'fail' ? '✕' : '○';
    const detail = ev && ev.detail && (st === 'ok' || st === 'warn' || st === 'fail') ? `<span class="td-d">${esc(ev.detail)}</span>` : '';
    html += `<div class="td-step td-${st}"><span class="td-g">${glyph}</span><span class="td-l">${esc(label)}</span>${detail}</div>`;
  }
  html += '</div>';
  if (res) {
    html = html.replace('<div class="td-steps">', '<div class="td-steps td-folded">') +
      `<div class="td-done"><span class="td-g">✓</span>Taken apart in ${esc(res.took_s || 0)} s · 8 steps</div>`;
    if (res.shot) html += `<img class="td-shot" src="${esc(res.shot)}" alt="">`;
    if (res.stack && res.stack.length) {
      html += '<div class="td-sec">STACK</div><div class="td-chips">' +
        res.stack.slice(0, 10).map(s => `<span class="td-chip" title="${esc(s.how)}">${esc(s.name)}${s.version ? ' <b>' + esc(s.version) + '</b>' : ''}</span>`).join('') + '</div>';
    }
    const k = res.counts || {};
    html += `<div class="td-counts"><span><b>${k.requests || 0}</b> files · ${mb(k.bytes)}</span><span><b>${k.scripts || 0}</b> scripts · ${mb(k.script_bytes)}</span>` +
      `<span class="td-saved">✓ saved to your vault</span></div>` +
      `<button class="td-read" data-rel="${esc(res.rel || '')}">Read the full teardown</button>`;
  } else if (c.error) {
    html += `<div class="td-err">${esc(c.error)}</div>`;
  }
  panel.innerHTML = html;
  fit();
}

// ⚖ never cover the reflex strip or the answer: the space above whichever rises highest is
// the panel's budget; when it's tight the snapshot goes first, then the panel scrolls inside
function fit() {
  if (!panel || panel.style.display === 'none') return;
  let floor = innerHeight - 140;
  for (const id of ['rx', 'jarvis']) {
    const el = document.getElementById(id);
    if (!el || getComputedStyle(el).display === 'none') continue;
    const r = el.getBoundingClientRect();
    if (r.height > 0 && r.left < panel.getBoundingClientRect().right) floor = Math.min(floor, r.top);
  }
  const room = Math.max(140, floor - panel.getBoundingClientRect().top - 12);
  panel.classList.remove('td-tight');
  panel.style.maxHeight = room + 'px';
  if (panel.scrollHeight > room && panel.querySelector('.td-shot')) panel.classList.add('td-tight');
}
function watchFit() {
  try {
    const ro = new ResizeObserver(() => fit());
    for (const id of ['rx', 'jarvis']) { const el = document.getElementById(id); if (el) ro.observe(el); }
  } catch (_) {}
  addEventListener('resize', fit);
  setInterval(fit, 1500);                              // the strip also slides as rows open — cheap belt and braces
}

function injectStyle() {
  const s = document.createElement('style');
  s.textContent = `
  #j-teardown{position:fixed;left:286px;top:84px;z-index:57;width:400px;max-height:calc(100vh - 300px);overflow-y:auto;
    background:rgba(10,16,20,.9);border:1px solid rgba(52,211,153,.24);border-radius:12px;padding:12px 14px;
    backdrop-filter:blur(10px);box-shadow:0 10px 36px rgba(0,0,0,.5);font-family:'SF Mono',ui-monospace,monospace;color:#cfe9df;display:none}
  #j-teardown .td-head{display:flex;align-items:center;gap:8px;margin-bottom:10px}
  #j-teardown .td-k{font-size:10px;letter-spacing:.18em;color:#34d399;font-weight:700}
  #j-teardown .td-host{font-size:12px;color:#fff;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #j-teardown .td-rea{font-size:9px;letter-spacing:.1em;color:#0b1612;background:#34d399;border-radius:999px;padding:2px 7px;font-weight:700}
  #j-teardown #td-close{font:inherit;font-size:10px;color:#9fbfb3;background:none;border:1px solid rgba(159,191,179,.35);border-radius:6px;padding:2px 7px;cursor:pointer}
  #j-teardown #td-close:hover{color:#fff;border-color:#34d399}
  #j-teardown .td-step{display:flex;align-items:baseline;gap:8px;font-size:11px;line-height:1.75}
  #j-teardown .td-g{width:12px;text-align:center;color:#4b6b60}
  #j-teardown .td-ok .td-g{color:#34d399}
  #j-teardown .td-run .td-g{color:#34d399;animation:tdpulse 1s ease-in-out infinite}
  #j-teardown .td-run .td-l{color:#fff}
  #j-teardown .td-warn .td-g{color:#f4a93a}
  #j-teardown .td-fail .td-g{color:#ff7d6b}
  #j-teardown .td-wait .td-l,#j-teardown .td-skip .td-l{color:#5f7c72}
  #j-teardown .td-l{white-space:nowrap}
  #j-teardown .td-d{margin-left:auto;padding-left:8px;color:#7fa596;font-size:9.5px;max-width:112px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #j-teardown .td-folded{display:none}
  #j-teardown .td-done{display:flex;gap:8px;font-size:11px;color:#cfe9df}
  #j-teardown .td-done .td-g{color:#34d399}
  #j-teardown .td-shot{display:block;box-sizing:border-box;width:100%;height:112px;object-fit:cover;object-position:top;border-radius:8px;margin:10px 0 2px;border:1px solid rgba(52,211,153,.18)}
  #j-teardown .td-sec{font-size:9px;letter-spacing:.18em;color:#34d399;margin:9px 0 5px}
  #j-teardown .td-chips{display:flex;flex-wrap:wrap;gap:4px}
  #j-teardown .td-chip{font-size:9.5px;color:#eaf0ec;border:1px solid rgba(255,255,255,.14);border-radius:999px;padding:2px 7px;background:rgba(255,255,255,.04)}
  #j-teardown .td-shot.td-icon{height:150px;object-position:center}
  #j-teardown .td-chip b{color:#34d399;font-weight:600}
  #j-teardown{overflow-x:hidden}
  #j-teardown::-webkit-scrollbar,#j-td-reader .tr-body::-webkit-scrollbar{width:6px;height:6px}
  #j-teardown::-webkit-scrollbar-thumb,#j-td-reader .tr-body::-webkit-scrollbar-thumb{background:rgba(52,211,153,.35);border-radius:3px}
  #j-teardown::-webkit-scrollbar-track,#j-td-reader .tr-body::-webkit-scrollbar-track{background:transparent}
  #j-teardown .td-counts{display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:10px;font-size:10px;color:#9fbfb3}
  #j-teardown .td-read{display:block;width:100%;margin-top:10px;font:inherit;font-size:11px;letter-spacing:.04em;color:#0b1612;background:#34d399;border:0;border-radius:8px;padding:7px 0;cursor:pointer;font-weight:700}
  #j-teardown .td-read:hover{background:#4be3ad}
  #j-td-reader{position:fixed;inset:0;z-index:90;display:none;align-items:center;justify-content:center;background:rgba(2,6,8,.55);backdrop-filter:blur(4px)}
  #j-td-reader .tr-card{width:min(780px,92vw);max-height:84vh;display:flex;flex-direction:column;background:rgba(10,16,20,.96);border:1px solid rgba(52,211,153,.3);border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,.6)}
  #j-td-reader .tr-head{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid rgba(52,211,153,.15);font-family:'SF Mono',ui-monospace,monospace}
  #j-td-reader .tr-k{font-size:10px;letter-spacing:.18em;color:#34d399;font-weight:700}
  #j-td-reader .tr-title{flex:1;font-size:13px;color:#fff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #j-td-reader .tr-btn{font:inherit;font-size:10px;color:#9fbfb3;background:none;border:1px solid rgba(159,191,179,.35);border-radius:6px;padding:3px 9px;cursor:pointer}
  #j-td-reader .tr-btn:hover{color:#fff;border-color:#34d399}
  #j-td-reader .tr-body{overflow-y:auto;padding:6px 26px 24px;color:#d4e9e1;font:14px/1.62 -apple-system,system-ui,sans-serif}
  #j-td-reader .tr-body h1{font-size:22px;color:#fff;margin:18px 0 6px}
  #j-td-reader .tr-body h2{font-size:15px;color:#34d399;letter-spacing:.02em;margin:22px 0 6px;font-family:'SF Mono',ui-monospace,monospace;transition:color .3s,text-shadow .3s}
  #j-td-reader .tr-body h2.tr-now{color:#fff;text-shadow:0 0 14px rgba(52,211,153,.75)}
  #j-td-reader .tr-body h3{font-size:14px;color:#fff;margin:16px 0 4px}
  #j-td-reader .tr-body p{margin:6px 0}
  #j-td-reader .tr-body .tr-meta{color:#7fa596;font-size:12px;margin:2px 0}
  #j-td-reader .tr-body blockquote{margin:12px 0;padding:8px 14px;border-left:3px solid #34d399;background:rgba(255,255,255,.04);color:#fff;font-size:15px}
  #j-td-reader .tr-body ul,#j-td-reader .tr-body ol{margin:6px 0 6px 20px;padding:0}
  #j-td-reader .tr-body li{margin:4px 0}
  #j-td-reader .tr-body code{font:12px 'SF Mono',ui-monospace,monospace;background:rgba(255,255,255,.07);color:#e6efe9;padding:1px 5px;border-radius:4px}
  #j-td-reader .tr-body b{color:#fff}
  #j-td-reader .tr-body .tr-wl{color:#34d399}
  #j-td-reader .tr-body img{display:block;box-sizing:border-box;width:100%;border-radius:10px;margin:12px 0;border:1px solid rgba(52,211,153,.18)}
  #j-teardown .td-counts b{color:#fff}
  #j-teardown .td-saved{color:#34d399}
  #j-teardown.td-tight .td-shot{display:none}
  #j-teardown .td-err{margin-top:10px;font-size:11px;color:#ff9d8f}
  #j-teardown .td-sum{margin-top:8px;font-size:11px;line-height:1.55;color:#cfe9df}
  @keyframes tdpulse{0%,100%{opacity:1}50%{opacity:.25}}`;
  document.head.appendChild(s);
}

// boot LAST: the route regexes above are module-level consts (TDZ — booting at the top threw
// "Cannot access 'STOP' before initialization" whenever the core bridge was already up)
(function boot(n) {
  if (window.__jarvis && window.__os && window.__os.Graph) { try { init(); } catch (e) { console.warn('[teardown]', e); } return; }
  if ((n || 0) < 3600) requestAnimationFrame(() => boot((n || 0) + 1));
})();
