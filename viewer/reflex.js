// Jarvis V7 — REFLEX (Session 25, 2026-09-21). The Jev reflex layer made VISIBLE on the 3D brain.
//
// Jev (TypeSafe AI) never writes text: state + typed questions in, probabilities out in ~200 ms.
// This organ owns: the REFLEX STRIP (one row per question: bar, threshold tick, value, verdict
// chip), the pill (model · questions · ms · cost), the banner, the vault heat on the galaxy, the
// judge card, the triage panel, filming mode, and the voice routes. Every value on screen is a
// probability Jev returned this turn — nothing here is decorative.
//
// LAWS: advisory only (the server owns the gates; this file only renders + dispatches when the
// server's decision says so) · all speech rides J.say/J.voice → speak() (mute law) · the key
// never reaches this page (only /reflex/*) · organs are opt-in: the strip can be hidden by voice,
// filming mode is off until asked · probes run silent (?reflexprobe=1).
'use strict';

const Q = new URLSearchParams(location.search);
const PROBE = Q.has('reflexprobe');
const DEBUG = Q.has('reflexdebug');

// ---- gates that live on the CLIENT (named constants, tune from ?reflexdebug=1) ----------------
const HEAR_DEBOUNCE_MS = 260;     // partial transcripts: coalesce before asking Jev
// 2026-09-24 (filming): a partial "Jarvis stage an urgent call" was heard as "Georgia State…", fired
// early, and the calls bay looked up a real university's number. Phone and staging utterances are
// never urgent enough to guess from a partial — they always wait for the final transcript.
const NO_EARLY = /\b(?:call|calls|calling|ring|dial|phone|stage|state|urgent)\b/i;
const EARLY_STABLE_MS = 600;      // S25c: early dispatch needs a REAL pause — the partial text unchanged this long ("what is CiteVue" scored
                                  //       complete .92 as a prefix of "…and what does it charge"; only silence can tell a sentence from a breath)
const CONSUMED_TTL_MS = 4000;     // an early-dispatched utterance suppresses its own final this long
const CONSUME_MAX_GROWTH = 1.5;   // S25c: a final with more than 1.5× the words of the fired partial is a NEW ask, never consumed
const FILMING_OFF = /^\s*(?:hey |okay |ok )?(?:jarvis|jervis)?[\s,.]*(?:filming mode off|recording mode off|we(?:'| a)re done filming|stop filming)[\s.!]*$/i;   // the exit always works, Jev or not
const HEAT_TTL_MS = 28000;        // vault heat fades after this
const HEAT_MAX_NODES = 40;
const FLASH_MS = 1800;            // amber flash + receipt on a meaningful change
const MOVE_FLASH = 0.15;          // …meaning: a jump of this much, or a threshold crossing
const SHOW_DEFAULT = true;        // the strip is visible unless he says "hide your reflexes"
const IDLE_COLLAPSE_MS = 15000;   // AUTO mode only: rows fold away after this; the pill + banner stay (any new reflex re-opens)
const HOLD_DEFAULT = true;        // S25g (his call, filming): rows STAY until he folds them (button or "fold the reflexes"); the next reflex opens them again
const DOCK_W = 238;               // the organ dock column (chips are right:34px + 204px wide)

let J = null;
(function waitJ(){ const w = setInterval(() => { if (window.__jarvis){ J = window.__jarvis; clearInterval(w); } }, 700); })();

const RX = { show: SHOW_DEFAULT, filming: false, on: true, lastText: '', lastAt: 0, inflight: null, pendingTimer: 0,
             consumed: null, heatTimer: 0, heatNodes: [], rows: {}, ready: false };
try { const v = localStorage.getItem('rxShow'); if (v !== null) RX.show = v === '1'; } catch (_){}
RX.hold = HOLD_DEFAULT; try { const v = localStorage.getItem('rxHold'); if (v !== null) RX.hold = v === '1'; } catch (_){}

function jget(p){ return fetch(p).then(r => r.json()).catch(() => null); }
function jpost(p, body){
  return fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
    .then(r => r.json()).catch(() => null);
}
function spk(t){ if (PROBE) return Promise.resolve(); try { return J && J.say ? J.say(t) : Promise.resolve(); } catch (_){ return Promise.resolve(); } }
function voice(t){ if (PROBE) return; try { if (J && J.voice) J.voice(t); } catch (_){} }
const pct = x => (typeof x === 'number' ? Math.round(x * 100) + '%' : '—');
const STRIP_WAKE = /^\s*(?:hey |okay |ok )?(?:jarvis|jervis)(?:\s+a\.?\s?i\.?)?[\s,.]*/i;

/* ---------- pure helpers (the probe drives these) ---------- */
function verdictFor(kind, val, gate, invert){
  // returns [chipClass, text]; mirrors the server's decision semantics for display only
  if (val == null) return ['', 'hold'];
  if (invert) return val >= gate ? ['block', 'confirm'] : val >= gate / 2 ? ['ask', 'watch'] : ['act', 'clear'];
  return val >= gate ? ['act', 'act'] : val >= gate * 0.6 ? ['ask', 'ask'] : ['', 'hold'];
}
function overlaps(a, b){
  a = (a || '').toLowerCase().replace(STRIP_WAKE, '').trim(); b = (b || '').toLowerCase().replace(STRIP_WAKE, '').trim();
  if (!a || !b) return false;
  return a.startsWith(b.slice(0, Math.min(b.length, 24))) || b.startsWith(a.slice(0, Math.min(a.length, 24)));
}
function costWords(usd){
  if (!usd) return 'nothing at all';
  const c = usd * 100;
  if (c < 0.1) return 'less than a tenth of a cent';
  if (c < 1) return `about ${c.toFixed(1).replace(/\.0$/, '')} cents`.replace('about 1 cents', 'about a cent');
  return `about ${Math.round(c)} cents`;
}
function gazeWord(){
  const e = window.__eyes;
  if (!e || !e.on) return 'unknown';
  if (!e.present) return 'absent';
  return e.looking ? 'screen' : 'away';
}

/* ---------- DOM ---------- */
const CSS = `
#rx{position:fixed;left:286px;right:254px;z-index:9;pointer-events:none;
  font-family:-apple-system,"SF Pro Text",Inter,sans-serif;color:#e6ebf1;transition:opacity .3s}
#rx.hidden{opacity:0}
#rx .top{display:flex;justify-content:space-between;align-items:center;margin:0 6px 6px;font:11px ui-monospace,Menlo,monospace;letter-spacing:.2em;text-transform:uppercase;color:#64748b;pointer-events:auto}
#rx .fold{background:rgba(10,13,18,.84);border:1px solid #1f2937;color:#8e9aa8;border-radius:999px;padding:4px 12px;margin-left:10px;font:10px ui-monospace,Menlo,monospace;letter-spacing:.14em;text-transform:uppercase;cursor:pointer}
#rx .fold:hover{color:#e6ebf1;border-color:#34d399}
#rx .top b{color:#34d399;font-weight:600}
#rx .pill{display:flex;gap:16px;background:rgba(10,13,18,.84);border:1px solid #1f2937;border-radius:999px;padding:6px 14px;letter-spacing:.06em;text-transform:none;font-size:12px}
#rx .pill .ms{color:#e6ebf1;font-weight:700}#rx .pill .cost{color:#34d399}
#rx .strip{background:rgba(10,13,18,.86);border:1px solid #1f2937;border-radius:14px;padding:10px 14px 8px;backdrop-filter:blur(8px)}
#rx .row{display:grid;grid-template-columns:210px 1fr 66px 70px;align-items:center;gap:12px;padding:4px 0;border-bottom:1px dashed rgba(230,235,241,.08)}
#rx .row.off{display:none}
#rx.idle .strip{display:none}
#rx .row:last-child{border-bottom:none}
#rx .q{font-size:11.5px;color:#8e9aa8;line-height:1.2}
#rx .q b{color:#e6ebf1;font-weight:600;display:block;font-size:12.5px}
#rx .q b em{font-style:normal;color:#34d399}
#rx .bar{position:relative;height:8px;background:rgba(230,235,241,.08);border-radius:6px}
#rx .fill{position:absolute;left:0;top:0;bottom:0;width:0;border-radius:6px;background:#34d399;transition:width .22s ease-out,background .3s}
#rx .tick{position:absolute;top:-4px;bottom:-4px;width:2px;background:rgba(230,235,241,.45)}
#rx .v{font:700 20px ui-monospace,Menlo,monospace;text-align:right;letter-spacing:-.03em}
#rx .chip{font:10px ui-monospace,Menlo,monospace;letter-spacing:.14em;text-transform:uppercase;padding:6px 0;border-radius:999px;text-align:center;border:1px solid #1f2937;color:#64748b}
#rx .chip.act{background:rgba(52,211,153,.14);color:#34d399;border-color:rgba(52,211,153,.5)}
#rx .chip.ask{background:rgba(245,195,77,.12);color:#f5c34d;border-color:rgba(245,195,77,.5)}
#rx .chip.block{background:rgba(255,77,94,.14);color:#ff4d5e;border-color:rgba(255,77,94,.5)}
#rx .row.flash .fill{background:#f5c34d}#rx .row.flash .v{color:#f5c34d}
#rx .rcpt{font:11px ui-monospace,Menlo,monospace;color:#f5c34d;margin-left:8px;opacity:0;transition:opacity .3s}
#rx .row.flash .rcpt{opacity:1}
#rx .banner{display:none;align-items:center;gap:10px;margin:8px 8px 0;font:11px ui-monospace,Menlo,monospace;letter-spacing:.16em;text-transform:uppercase;color:#34d399}
#rx .banner .dot{width:8px;height:8px;border-radius:50%;background:#34d399;box-shadow:0 0 12px #34d399}
#rx .banner.amber{color:#f5c34d}#rx .banner.amber .dot{background:#f5c34d;box-shadow:0 0 12px #f5c34d}
#rx .banner.red{color:#ff4d5e}#rx .banner.red .dot{background:#ff4d5e;box-shadow:0 0 12px #ff4d5e}
#rx .ear{width:9px;height:9px;border-radius:50%;background:#27303b;display:inline-block;margin-right:8px;vertical-align:middle;transition:.3s}
#rx .ear.band{background:#3a4552;animation:rxpulse 1.5s ease-in-out infinite}
#rx .ear.on{background:#34d399;box-shadow:0 0 12px rgba(52,211,153,.9)}
@keyframes rxpulse{0%,100%{box-shadow:0 0 0 0 rgba(142,154,168,0)}50%{box-shadow:0 0 0 7px rgba(142,154,168,.18)}}
#reflexChip{position:fixed;right:34px;top:calc(46% + 412px);width:204px;box-sizing:border-box;z-index:60;cursor:pointer;user-select:none;display:flex;align-items:center;justify-content:space-between;
  font:11px ui-monospace,Menlo,monospace;letter-spacing:.22em;color:#9adbe8;background:rgba(8,16,20,.78);border:1px solid rgba(64,224,255,.28);border-radius:12px;padding:8px 12px}
#reflexChip::after{content:attr(data-state);font-size:9px;letter-spacing:.18em;color:#5a7d8a}
#reflexChip.on{color:#40e0ff;border-color:rgba(64,224,255,.8);box-shadow:0 0 18px rgba(64,224,255,.28),inset 0 0 14px rgba(64,224,255,.06)}
#reflexChip.on::after{color:#7dffd9;text-shadow:0 0 8px rgba(125,255,217,.6)}
#rxside{position:fixed;right:254px;top:70px;width:380px;z-index:9;display:none;flex-direction:column;gap:10px;pointer-events:auto;
  font-family:-apple-system,"SF Pro Text",Inter,sans-serif;color:#e6ebf1}
#rxside .card{background:rgba(10,13,18,.9);border:1px solid #1f2937;border-radius:14px;padding:12px 14px}
#rxside .src{font:10px ui-monospace,Menlo,monospace;letter-spacing:.2em;text-transform:uppercase;color:#64748b;margin-bottom:6px}
#rxside .dead{color:#8e9aa8;text-decoration:line-through;text-decoration-color:#ff4d5e;text-decoration-thickness:2px;font-size:14px;line-height:1.35}
#rxside .fix{color:#34d399;font-size:14px;line-height:1.35;margin-top:6px}
#rxside ul{list-style:none;padding:0;margin:6px 0 0;font:11.5px ui-monospace,Menlo,monospace;color:#8e9aa8;display:grid;gap:4px}
#rxside li b{color:#e6ebf1}
#rxside .it{display:grid;grid-template-columns:1fr auto;gap:4px 10px;padding:6px 0;border-bottom:1px dashed rgba(230,235,241,.08);font-size:12.5px}
#rxside .it .t{color:#cbd5e1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#rxside .it .k{font:10px ui-monospace,Menlo,monospace;letter-spacing:.1em;text-transform:uppercase;padding:2px 8px;border-radius:999px;border:1px solid #1f2937;color:#64748b;opacity:0;transition:opacity .25s}
#rxside .it .k.on{opacity:1}
#rxside .it .k.lead,#rxside .it .k.question{color:#34d399;border-color:rgba(52,211,153,.5)}
#rxside .it .k.complaint{color:#f5c34d;border-color:rgba(245,195,77,.5)}
#rxside .it .k.spam{color:#ff4d5e;border-color:rgba(255,77,94,.4)}
#rxside .it.top .t{color:#fff;font-weight:600}
#rxside .close{position:absolute;right:10px;top:8px;background:none;border:none;color:#64748b;font-size:14px;cursor:pointer}
`;
const ROWS = [
  { id: 'lane', label: 'Lane', q: 'Which lane should this take?', gate: 0.70, kind: 'choice' },
  { id: 'complete', label: 'Complete', q: 'Has he finished the request?', gate: 0.85 },
  { id: 'addressed', label: 'Addressed', q: 'Talking to Jarvis, not narrating?', gate: 0.80 },
  { id: 'destructive', label: 'Stakes', q: 'Would acting send, call, delete, or spend?', gate: 0.50, invert: true },   // S25f (his call): "destructive" read as dangerous on camera; the key stays
  { id: 'has', label: 'Vault has it', q: 'Does any note directly answer this?', gate: 0.70 },
];
let root, strip, pill, banner, ear, side;
function build(){
  if (root) return;
  const st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st);
  root = document.createElement('div'); root.id = 'rx';
  root.innerHTML = `<div class="top"><div><span class="ear" id="rx-ear"></span><b>reflex</b> · jev · <span id="rx-mode">${modeText()}</span><button class="fold" id="rx-fold" title="Fold the rows to the pill, or open them. Voice: fold / open the reflexes">fold</button></div>
    <div class="pill"><span id="rx-model">jev</span><span id="rx-q">—</span><span class="ms" id="rx-ms">— ms</span><span class="cost" id="rx-cost">$0.00000</span></div></div>
    <div class="strip" id="rx-strip"></div><div class="banner" id="rx-banner"><span class="dot"></span><span id="rx-btext"></span></div>`;
  document.body.appendChild(root);
  strip = root.querySelector('#rx-strip'); banner = root.querySelector('#rx-banner'); ear = root.querySelector('#rx-ear');
  for (const r of ROWS){
    const el = document.createElement('div'); el.className = 'row'; el.dataset.id = r.id;
    el.innerHTML = `<div class="q"><b>${r.label}</b>${r.q}<span class="rcpt"></span></div><div class="bar"><div class="fill"></div><div class="tick" style="left:${r.gate * 100}%"></div></div><div class="v">—</div><div class="chip">hold</div>`;
    if (r.id === 'has') el.classList.add('off');
    strip.appendChild(el); RX.rows[r.id] = { el, cfg: r, val: null };
  }
  const chip = document.createElement('div'); chip.id = 'reflexChip'; chip.dataset.state = 'live'; chip.textContent = 'REFLEX';
  chip.title = 'Jev reflex layer — every question is scored in ~200 ms before the brain answers; early dispatch waits for a real pause (S25c). Click: show/hide the strip. Voice: "show your reflexes" · "hide your reflexes" · "reflexes off" · "we\'re filming" · "show the last reflex" · "what did your reflexes cost today" · "triage the inbox" · "show me the judge" · "fold / open the reflexes" · "hold / auto-fold the reflexes".';
  chip.onclick = () => showStrip(!RX.show);
  root.querySelector('#rx-fold').onclick = () => foldStrip(!root.classList.contains('idle'));
  document.body.appendChild(chip); RX.chip = chip;
  side = document.createElement('div'); side.id = 'rxside'; document.body.appendChild(side);
  place(); addEventListener('resize', place); setInterval(place, 1500);
  root.classList.toggle('hidden', !RX.show);
  RX.ready = true;
}
function place(){
  // between the left panel and the organ dock, just above the ask bar — whatever the layout does
  try { const inp = document.getElementById('j-input'); const r = inp ? inp.getBoundingClientRect() : null;
    const ansEl = document.getElementById('j-answer'); const ar = ansEl && ansEl.style.display !== 'none' ? ansEl.getBoundingClientRect() : null;
    const topRef = (ar && ar.height > 0 && ar.top > 0) ? Math.min(ar.top, r ? r.top : ar.top) : (r ? r.top : 0);   // the answer bubble sits above the ask bar: stay above both
    root.style.bottom = (topRef > 0 ? (innerHeight - topRef) + 14 : 130) + 'px';
    const side = document.getElementById('side'); const collapsed = document.body.classList.contains('collapsed');
    const sr = side && !collapsed ? side.getBoundingClientRect() : null;
    root.style.left = ((sr && sr.right > 0 ? sr.right : 0) + 20) + 'px'; root.style.right = (DOCK_W + 16) + 'px'; } catch (_){}
}
function modeText(){ return (RX.filming ? 'filming mode' : (RX.on === false ? 'off' : 'live')) + (RX.hold ? ' · held' : ''); }
function setMode(){ const m = root && root.querySelector('#rx-mode'); if (m) m.textContent = modeText(); }
function foldLabel(){ const b = root && root.querySelector('#rx-fold'); if (b) b.textContent = root.classList.contains('idle') ? 'open' : 'fold'; }
function wake(){                                   // a new reflex: open the rows; arm the fold timer ONLY in auto mode (never while filming)
  root.classList.remove('idle'); clearTimeout(RX.idleTimer); RX.idleTimer = 0; foldLabel();
  if (RX.hold || RX.filming) return;
  RX.idleTimer = setTimeout(() => { root.classList.add('idle'); foldLabel(); }, IDLE_COLLAPSE_MS);
}
function foldStrip(on){ root.classList.toggle('idle', !!on); clearTimeout(RX.idleTimer); RX.idleTimer = 0; foldLabel(); }   // manual: stays folded until the next reflex
function setHold(on){ RX.hold = !!on; try { localStorage.setItem('rxHold', on ? '1' : '0'); } catch (_){} setMode(); wake(); }
function chipState(){ if (!RX.chip) return; RX.chip.dataset.state = !RX.on ? 'off' : RX.filming ? 'filming' : RX.show ? 'live' : 'hidden'; RX.chip.classList.toggle('on', RX.on && RX.show); }
function setRow(id, val, opts = {}){
  const R = RX.rows[id]; if (!R) return;
  wake(); el0(R);
  const { el, cfg } = R; const fill = el.querySelector('.fill'), v = el.querySelector('.v'), chip = el.querySelector('.chip');
  const prev = R.val;
  fill.style.width = Math.max(0, Math.min(1, val || 0)) * 100 + '%';
  v.textContent = pct(val);
  if (opts.label !== undefined) el.querySelector('.q b').innerHTML = `${cfg.label} <em>${opts.label || ''}</em>`;
  const gate = opts.gate || cfg.gate; el.querySelector('.tick').style.left = gate * 100 + '%';
  const [cls, txt] = verdictFor(cfg.kind, val, gate, cfg.invert);
  chip.className = 'chip ' + cls; chip.textContent = opts.chip || txt;
  if (prev != null && val != null && (Math.abs(prev - val) >= MOVE_FLASH || (prev >= gate) !== (val >= gate))){
    el.classList.add('flash'); el.querySelector('.rcpt').textContent = `${pct(prev)} → ${pct(val)}`;
    clearTimeout(R.ft); R.ft = setTimeout(() => el.classList.remove('flash'), FLASH_MS);
  }
  R.val = val;
}
function el0(R){ R.el.classList.remove('off'); }
function setPill(r){
  if (!r) return;
  root.querySelector('#rx-model').textContent = r.model || 'jev';
  root.querySelector('#rx-q').textContent = Object.keys(r.answers || {}).length + ' questions';
  root.querySelector('#rx-ms').textContent = (r.ms != null ? r.ms : '—') + ' ms';
  root.querySelector('#rx-cost').textContent = '$' + (r.cost || 0).toFixed(5);
}
function setBanner(text, cls){ banner.className = 'banner ' + (cls || ''); root.querySelector('#rx-btext').textContent = text || ''; banner.style.display = text ? 'flex' : 'none'; }
function setEar(state){ ear.className = 'ear ' + (state || ''); }
function showStrip(on){ RX.show = on; root.classList.toggle('hidden', !on); wake(); chipState(); try { localStorage.setItem('rxShow', on ? '1' : '0'); } catch (_){} }

/* ---------- render a prepass result ---------- */
function renderPrepass(r, text){
  if (!r || !r.answers) return;
  const a = r.answers, d = r.decision || {}; const lane = a.lane || {};
  setRow('lane', lane.confidence != null ? lane.confidence : 0, { label: String(lane.choice || '').replace(/_/g, ' '), gate: (d.gates || {}).lane_act });
  setRow('complete', a.complete && a.complete.noul);
  setRow('addressed', a.addressed && a.addressed.noul, { gate: (d.gates || {}).addressed });
  setRow('destructive', a.destructive && a.destructive.noul);
  setPill(r);
  if (d.needs_confirm) setBanner(`${String(d.lane).replace(/_/g, ' ')} · stakes ${pct(a.destructive.noul)} · would confirm first`, 'amber');
  else if (d.clarify) setBanner(`unsure which lane · confidence ${pct(d.confidence)} · brain decides`, 'amber');
  else if (d.trust_lane) setBanner(`${String(d.lane).replace(/_/g, ' ')} · ${r.ms} ms · ${r.tokens} tokens`, '');
  else setBanner('');
  setMode();
}

/* ---------- vault heat on the galaxy ---------- */
function clearHeat(){
  try {
    const nodes = window.__os && window.__os.data.nodes;
    for (const h of RX.heatNodes){ const n = nodes && nodes[h.i]; if (n && h.val != null) n.val = h.val; }
    RX.heatNodes = [];
    if (window.__os && window.__os.Graph) window.__os.Graph.nodeVal(n => n.val);
  } catch (_){}
}
function heat(probs, keep){
  clearHeat();
  try {
    const os = window.__os; if (!os) return;
    const nodes = os.data.nodes;
    for (const [i, p] of (probs || []).slice(0, HEAT_MAX_NODES)){
      const n = nodes[i]; if (!n || p < 0.08) continue;
      RX.heatNodes.push({ i, val: n.val }); n.val = (n.val || 2) * (1 + 3.2 * p);   // size follows probability
    }
    os.Graph.nodeVal(n => n.val);
    // S25e (his report: "dark, then the lanes"): the organ only SWELLS nodes. Lighting + the camera belong to the
    // answer path (3d.html flyTo → onNodeClick: neighbourhood lit, particles on the wires). The old lightNodes(keep)
    // here lit three lone dots, hid every other wire and zoomed out to fit them, a second before the answer.
    clearTimeout(RX.heatTimer); RX.heatTimer = setTimeout(clearHeat, HEAT_TTL_MS);
  } catch (_){}
}
function renderRecall(rc){
  if (!rc) return;
  if (rc.named){                                        // S25d: "pull up X" — the note IS the answer; show the named note's probability against NAMED_OPEN
    const top = (rc.probs && rc.probs[0]) ? rc.probs[0][1] : rc.names;
    let name = ''; try { const n = window.__os && window.__os.data.nodes[rc.probs[0][0]]; name = n && n.label ? ` · ${n.label}` : ''; } catch (_){}
    setRow('has', top, { gate: (rc.gates || {}).named_open || 0.70, chip: 'named', label: 'named' });
    heat(rc.probs, rc.keep); setBanner(`vault has it · named · ${pct(top)}${name} · ${rc.ms} ms`, ''); return;
  }
  setRow('has', rc.has, { gate: 0.70, chip: rc.verdict === 'found' ? 'found' : rc.verdict === 'absent' ? 'dark' : 'unsure', label: '' });
  if (rc.verdict === 'found'){ heat(rc.probs, rc.keep); setBanner(`vault has it · ${pct(rc.has)} · ${rc.keep.length} note${rc.keep.length === 1 ? '' : 's'} kept · ${rc.ms} ms`, ''); }
  else if (rc.verdict === 'absent'){ clearHeat(); setBanner(`not in the vault · ${pct(rc.has)} · nothing improvised`, 'amber'); }
  else setBanner(`vault unsure · ${pct(rc.has)} · brain decides`, 'amber');
}

/* ---------- the judge card ---------- */
function renderJudge(jd, answer, label){
  if (!jd) return;
  if (!jd.blocked) return;
  side.style.display = 'flex';
  const c = document.createElement('div'); c.className = 'card';
  c.innerHTML = `<button class="close">×</button><div class="src">the judge · ${label || 'claim check'} · ${jd.ms || '—'} ms</div>
    <div class="dead">${esc(jd.original || '')}</div><ul><li>claims an action <b>${pct(jd.claims)}</b> · gate 0.70</li><li>backed by a receipt <b>${pct(jd.backed)}</b> · gate 0.40</li></ul>
    <div class="fix">${esc(answer || '')}</div>`;
  c.querySelector('.close').onclick = () => { c.remove(); if (!side.children.length) side.style.display = 'none'; };
  side.prepend(c); setBanner('blocked · claim without receipt · corrected', 'red');
  setTimeout(() => { c.remove(); if (!side.children.length) side.style.display = 'none'; }, 45000);
}
function esc(s){ return String(s).replace(/[&<>]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[ch])); }

/* ---------- hooks 3d.html calls ---------- */
window.__reflexAsk = function(q){
  if (!RX.ready || !RX.on) return;
  if (overlaps(q, RX.lastText) && Date.now() - RX.lastAt < 3000) return;   // the hear-path already scored this utterance
  RX.lastText = q; RX.lastAt = Date.now();
  jpost('/reflex/prepass', { text: q, ctx: { partial: false, recording_mode: RX.filming, gaze: gazeWord(), since_last: null } })
    .then(r => { if (r && r.answers){ renderPrepass(r, q);
      if (r.decision && r.decision.lane === 'vault_question' && r.decision.trust_lane) jpost('/reflex/recall', { question: q, session: J && J.session }).then(rc => rc && rc.probs && renderRecall(rc)); } });
};
window.__reflexHear = function(txt, fin, meta){
  if (!RX.ready || !RX.on) return false;
  const addressed = !!(meta && (meta.wake || meta.awaitingCmd)) || RX.filming;
  if (!addressed) return false;
  const cmd = txt.replace(STRIP_WAKE, '').trim();
  if (fin){
    if (RX.consumed && Date.now() - RX.consumed.t < CONSUMED_TTL_MS && overlaps(cmd, RX.consumed.text)
        && cmd.split(/\s+/).length <= Math.ceil(RX.consumed.text.split(/\s+/).length * CONSUME_MAX_GROWTH)){ RX.consumed = null; return true; }
    if (RX.consumed && Date.now() - RX.consumed.t < CONSUMED_TTL_MS && overlaps(cmd, RX.consumed.text)) setBanner('final grew past the early dispatch · asking again', 'amber');
    return false;                                        // finals go down the normal path (ask() scores them)
  }
  if (cmd.split(/\s+/).length < 3) return false;
  if (cmd !== RX.partialText){ RX.partialText = cmd; RX.partialAt = Date.now(); clearTimeout(RX.fireTimer); RX.fireTimer = 0; }   // any new words cancel a pending early fire
  clearTimeout(RX.pendingTimer);
  RX.pendingTimer = setTimeout(() => {
    if (RX.inflight) return;
    RX.inflight = jpost('/reflex/prepass', { text: cmd, ctx: { partial: true, recording_mode: RX.filming, gaze: gazeWord() } }).then(r => {
      RX.inflight = null; if (!r || !r.answers) return;
      RX.lastText = cmd; RX.lastAt = Date.now(); renderPrepass(r, cmd);
      const d = r.decision || {};
      if (d.peek_vault || (d.lane === 'vault_question' && d.trust_lane)) jpost('/reflex/recall', { question: cmd, session: J && J.session }).then(rc => rc && rc.probs && renderRecall(rc));   // heat before the sentence ends (S25c: LANE_PEEK, read-only)
      if (d.fire_early && !RX.consumed && J && J.ask && !NO_EARLY.test(cmd)){                     // complete + confident + harmless + a REAL pause → go
        const fire = () => { if (RX.partialText !== cmd || RX.consumed) return;   // he kept talking, or a final already went
          RX.consumed = { text: cmd, t: Date.now() }; setBanner(`early dispatch · complete ${pct(r.answers.complete.noul)} · ${r.ms} ms · pause ${Date.now() - RX.partialAt} ms`, '');
          J.ask(cmd); };
        const wait = Math.max(0, EARLY_STABLE_MS - (Date.now() - (RX.partialAt || 0)));
        clearTimeout(RX.fireTimer); RX.fireTimer = setTimeout(fire, wait);
        setBanner(`complete ${pct(r.answers.complete.noul)} · waiting ${wait} ms for the pause`, '');
      }
    });
  }, HEAR_DEBOUNCE_MS);
  return false;
};
window.__reflexFilming = function(txt, conf){
  if (!RX.ready || !RX.on || !RX.filming) return;
  if (FILMING_OFF.test(txt) && J && J.ask){ J.ask(txt.replace(STRIP_WAKE, '').trim()); return; }   // hard rule in code: the exit phrase never needs Jev
  if (txt.split(/\s+/).length < 3) return;
  setEar('band');
  jpost('/reflex/prepass', { text: txt, ctx: { partial: false, recording_mode: true, gaze: gazeWord() } }).then(r => {
    if (!r || !r.answers) return;
    renderPrepass(r, txt);
    const d = r.decision || {}, a = r.answers;
    if (d.addressed_ok && J && J.ask){ const cmd = txt.replace(STRIP_WAKE, '').trim() || txt; setEar('on'); setBanner(`addressed · ${pct(a.addressed.noul)} · answering`, ''); RX.lastText = cmd; RX.lastAt = Date.now(); J.ask(cmd); }
    else { setBanner(`narrating · addressed ${pct(a.addressed.noul)} · gate ${pct(d.gates && d.gates.addressed)}${a.narrating ? ' · narrating ' + pct(a.narrating.noul) : ''} · staying quiet`, 'amber'); setTimeout(() => setEar(RX.filming ? 'band' : ''), 1200); }
  });
};
window.__reflexResult = function(rx, answer){
  if (!RX.ready) return;
  if (rx.recall) renderRecall(rx.recall);
  if (rx.judge && rx.judge.blocked) renderJudge(rx.judge, answer);
};

/* ---------- triage panel ---------- */
async function triageInbox(){
  const d = await jget('/api/inbox'); const cards = (d && d.cards) || [];
  const items = cards.slice(0, 200).map(c => ({ id: c.id, from: c.source, text: `${c.title || ''}. ${c.body || ''}`.trim() }));
  if (!items.length){ await spk('The desk is empty, sir. Nothing to triage.'); return; }
  side.style.display = 'flex';
  const c = document.createElement('div'); c.className = 'card'; c.style.position = 'relative';
  c.innerHTML = `<button class="close">×</button><div class="src">triage · ${items.length} cards · jev</div><div id="rx-tri"></div>`;
  c.querySelector('.close').onclick = () => { c.remove(); if (!side.children.length) side.style.display = 'none'; };
  side.prepend(c);
  const list = c.querySelector('#rx-tri'); const byId = {};
  for (const it of items.slice(0, 40)){ const row = document.createElement('div'); row.className = 'it'; row.innerHTML = `<div class="t">${esc(it.text.slice(0, 70))}</div><div class="k">…</div>`; list.appendChild(row); byId[it.id] = row; }
  voice(`Scoring ${items.length} cards, sir.`);
  const r = await jpost('/reflex/triage', { items });
  if (!r || !r.items){ setBanner('triage unavailable', 'red'); return; }
  let i = 0;
  for (const it of r.items){ const row = byId[it.id]; if (!row) continue; const k = row.querySelector('.k');
    setTimeout(() => { k.textContent = it.kind ? `${it.kind} · reply ${pct(it.reply)}` : 'n/a'; k.className = 'k on ' + (it.kind || ''); if (r.top.includes(it.id)) row.classList.add('top'); }, 40 * i++); }
  c.querySelector('.src').textContent = `triage · ${r.n} cards · ${r.ms} ms · $${(r.cost || 0).toFixed(5)}`;
  setBanner(`${r.n} cards scored · ${r.ms} ms · $${(r.cost || 0).toFixed(5)}`, '');
  const top = r.top.map(id => items.find(x => x.id === id)).filter(Boolean).slice(0, 3);
  if (top.length) await spk(`${top.length === 1 ? 'One' : top.length === 2 ? 'Two' : 'Three'} that matter, sir: ` + top.map(t => t.text.split(/[.!?]/)[0].slice(0, 80)).join('. ') + '.');
}

/* ---------- voice routes ---------- */
async function toggleServer(body){ const d = await jpost('/reflex/toggle', body); if (d){ RX.on = !!d.on; RX.filming = !!d.filming; } chipState(); return d; }
(window.__jarvisRoutes = window.__jarvisRoutes || []).unshift(   // anchored phrasings; they must beat the mail/tool routes that also see the word 'inbox'
  { re: /^(?:show|display|bring up)(?: me)? (?:your |the )?reflex(?:es)?$/i, handler: async () => { showStrip(true); await spk('Reflexes on screen, sir.'); } },
  { re: /^hide (?:your |the )?reflex(?:es)?$/i, handler: async () => { showStrip(false); await spk('Hidden, sir.'); } },
  { re: /^(?:turn (?:your |the )?reflex(?:es)? |reflex(?:es)? )(on|off)$/i, handler: async (q, m) => { const on = m[1].toLowerCase() === 'on'; await toggleServer({ on }); setBanner(on ? '' : 'reflexes off · regex and rules only', 'amber'); await spk(on ? 'Reflexes back on, sir.' : 'Reflexes off, sir. Back to plain rules.'); } },
  { re: /^(?:we(?:'| a)re filming|filming mode(?: on)?|recording mode(?: on)?)$/i, handler: async () => { await toggleServer({ filming: true }); RX.filming = true; setEar('band'); setMode(); wake(); await spk("Filming mode, sir. I'll only answer when you're clearly talking to me."); } },
  { re: /^(?:filming mode off|recording mode off|we(?:'| a)re done filming|stop filming)$/i, handler: async () => { await toggleServer({ filming: false }); RX.filming = false; setEar(''); setMode(); wake(); await spk('Filming mode off, sir.'); } },
  // S25g: the rows stay up for the camera — fold/open by hand, hold/auto-fold as the standing choice
  { re: /^(?:fold|minimi[sz]e|collapse|tuck away) (?:your |the )?reflex(?:es)?$/i, handler: async () => { foldStrip(true); await spk('Folded, sir. They come back with the next question.'); } },
  { re: /^(?:open|expand|unfold) (?:your |the )?reflex(?:es)?$/i, handler: async () => { showStrip(true); foldStrip(false); await spk('Open, sir.'); } },
  { re: /^(?:hold|pin|keep) (?:your |the )?reflex(?:es)?(?: up| on screen| open)?$/i, handler: async () => { setHold(true); await spk("Holding them on screen, sir. They stay until you fold them."); } },
  { re: /^(?:release|unpin|auto[- ]?fold) (?:your |the )?reflex(?:es)?$/i, handler: async () => { setHold(false); await spk('Back to folding on their own, sir. Fifteen seconds after each reflex.'); } },
  { re: /^(?:show (?:me )?)?(?:the )?last reflex$/i, handler: async () => { const d = await jget('/reflex/log?n=1'); const e = d && d.log && d.log[0]; if (!e){ await spk('No reflexes logged yet, sir.'); return; }
      side.style.display = 'flex'; const c = document.createElement('div'); c.className = 'card'; c.style.position = 'relative';
      c.innerHTML = `<button class="close">×</button><div class="src">last reflex · ${e.purpose} · ${e.model} · ${e.ms} ms · ${e.tokens} tokens</div><ul>${Object.entries(e.answers || {}).slice(0, 12).map(([k, v]) => `<li><b>${esc(k)}</b> ${esc(JSON.stringify(v).slice(0, 90))}</li>`).join('')}</ul>`;
      c.querySelector('.close').onclick = () => { c.remove(); if (!side.children.length) side.style.display = 'none'; }; side.prepend(c);
      await spk(`The last reflex was a ${e.purpose}, sir. ${e.ms} milliseconds, ${e.tokens} tokens. The raw answers are on your screen.`); } },
  { re: /^(?:what (?:did|do|have)|how much (?:did|do|have|has)) (?:your|the|my) reflex(?:es)? cost(?: me| us)?(?: so far| today)?\??$/i, handler: async () => { const d = await jget('/reflex/diag'); if (!d){ await spk('I cannot reach the reflex bay, sir.'); return; }
      await spk(`${d.calls_today || 0} reflex calls today, sir, ${d.tokens_today || 0} tokens, ${costWords(d.cost_today)}. Median ${d.p50_ms || 0} milliseconds.`);
      setBanner(`${d.calls_today || 0} calls · ${d.tokens_today || 0} tokens · $${(d.cost_today || 0).toFixed(5)} today · p50 ${d.p50_ms || 0} ms`, ''); } },
  { re: /^(?:triage|score|reflex triage) (?:the |my )?(?:inbox|desk|cards|comments)$/i, handler: triageInbox },
  // S25c: the judge on demand — a canned FABRICATED claim goes through the real judge (real Jev call, real probabilities), labelled demo on the card
  { re: /^(?:show (?:me )?(?:your |the )?judge|test (?:your |the )?judge|demo (?:your |the )?judge|run (?:your |the )?judge)$/i, handler: async () => {
      const fake = "Done, sir. I've sent the follow-up to Dana and the deposit reminder went out this morning.";
      setBanner('the judge · a fabricated claim, no receipt · asking jev', 'amber');
      const jd = await jpost('/reflex/judge', { question: 'Follow up with Dana about the deposit.', answer: fake, receipts: [] });
      if (!jd || !jd.answers){ setBanner('judge unavailable', 'red'); await spk('The judge is not answering, sir.'); return; }
      if (jd.blocked){ renderJudge(jd, jd.line, 'demo · a fabricated claim'); await spk(jd.line); }
      else { setBanner(`the judge let it through · claims ${pct(jd.claims)} · backed ${pct(jd.backed)}`, 'amber'); await spk(`The judge let that one through, sir. Claims ${Math.round(jd.claims * 100)} percent, backed ${Math.round(jd.backed * 100)} percent.`); } } },
);

/* ---------- boot ---------- */
function boot(){
  build();
  jget('/reflex/diag').then(d => { if (!d) return; RX.on = !!d.on; RX.filming = !!d.filming;
    root.querySelector('#rx-model').textContent = d.model || 'jev'; setMode(); if (!d.enabled) root.querySelector('#rx-mode').textContent = 'no key';
    if (!d.key_present) setBanner('no TypeSafe key in config.json · reflexes idle', 'amber'); if (RX.filming) setEar('band'); chipState(); });
  wake();
}
if (document.readyState === 'loading') addEventListener('DOMContentLoaded', boot); else boot();

/* ---------- probe (silent, ?reflexprobe=1&mute=1) ---------- */
if (PROBE) setTimeout(async () => {
  const R = [];
  const t = (name, cond) => R.push((cond ? '✓ ' : '✗ ') + name);
  t('strip built', !!document.getElementById('rx-strip') && document.querySelectorAll('#rx .row').length === ROWS.length);
  t('verdict act', verdictFor('noul', 0.9, 0.85, false)[0] === 'act');
  t('verdict invert block', verdictFor('noul', 0.6, 0.5, true)[0] === 'block');
  t('overlap dedupe', overlaps('Jarvis, what did the kickoff decide', 'what did the kickoff decide about the deposit'));
  t('cost words', costWords(0.0004) === 'less than a tenth of a cent' && /cents/.test(costWords(0.05)));
  setRow('complete', 0.3); setRow('complete', 0.92);
  t('flash on crossing', RX.rows.complete.el.classList.contains('flash'));
  const d = await jget('/reflex/diag'); t('diag served', !!(d && d.gates));
  const pp = await jpost('/reflex/prepass', { text: 'Jarvis, what did the Summit and Sons kickoff decide about the deposit?', ctx: {} });
  t('live prepass', !!(pp && pp.decision)); if (pp) renderPrepass(pp, 'probe');
  t('lane = vault_question', !!(pp && pp.decision && pp.decision.lane === 'vault_question'));
  const rc = await jpost('/reflex/recall', { question: 'What did the Summit and Sons kickoff decide about the deposit?' });
  t('live recall', !!(rc && rc.probs)); if (rc) renderRecall(rc);
  t('heat applied or dark', !!(rc && (rc.verdict !== 'found' || RX.heatNodes.length > 0)));
  const jd = await jpost('/reflex/judge', { question: 'Follow up with Dana and tell me when it is out.', answer: "Done, sir. I've sent the follow-up to Dana.", receipts: [] });
  t('judge blocks a claim without receipt', !!(jd && jd.blocked));
  // S25c: the pause guard — a complete-sounding PREFIX must not dispatch while more words are still arriving
  try {
    const realAsk = J && J.ask; let fired = 0; if (J) J.ask = () => { fired++; };
    RX.consumed = null; RX.partialText = ''; RX.fireTimer = 0;
    window.__reflexHear('Jarvis what is CiteVue', false, { wake: true });                       // Jev: complete .92, may-fire
    await new Promise(r => setTimeout(r, HEAR_DEBOUNCE_MS + 260));                             // the prepass is in flight / back
    window.__reflexHear('Jarvis what is CiteVue and what does', false, { wake: true });         // he kept talking → cancels the pending fire
    await new Promise(r => setTimeout(r, EARLY_STABLE_MS + 900));
    t('pause guard holds early dispatch while words keep coming', fired === 0);
    if (J) J.ask = realAsk; clearTimeout(RX.fireTimer); RX.consumed = null;
  } catch (_){ t('pause guard holds early dispatch while words keep coming', false); }
  // S25g: hold — rows stay open (no fold timer), the fold button folds, the next reflex re-opens
  try {
    const wasHold = RX.hold; RX.hold = true; wake(); const noTimer = !RX.idleTimer && !root.classList.contains('idle');
    foldStrip(true); const folded = root.classList.contains('idle') && root.querySelector('#rx-fold').textContent === 'open';
    wake(); const reopened = !root.classList.contains('idle') && root.querySelector('#rx-fold').textContent === 'fold';
    RX.hold = wasHold; wake();
    t('hold keeps rows open · fold folds · next reflex reopens', noTimer && folded && reopened);
  } catch (_){ t('hold keeps rows open · fold folds · next reflex reopens', false); }
  const pass = R.filter(x => x[0] === '✓').length;
  document.title = `REFLEXPROBE ${pass}/${R.length} · ` + R.join(' ');
  window.__reflexProbe = R;
}, 2500);
