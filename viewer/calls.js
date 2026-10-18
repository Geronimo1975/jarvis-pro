// Jarvis V6 — HANDS-FREE CALLING client. Registers voice routes in window.__jarvisRoutes:
// "call Luigi's and book a table for 4 at 7 tonight" → Jarvis finds the number, asks permission
// ("Shall I ring them, sir?") → "do it" → dials via Retell → a live call card shows dialing →
// ringing → on the call → ended, and Jarvis speaks the outcome ("Booked, sir — 7:15, patio").
// Every real call needs an explicit "do it". Fully optional: no bridge, no effect.

const $id = (i) => document.getElementById(i);
let J = null;
let pending = null;           // {confirm_id, callee, number, need_number}
let poll = 0;

const NEVER = /$^/;
const goRoute = { re: NEVER, handler: goCall };     // dials — armed only while a call is pending confirm
const noRoute = { re: NEVER, handler: cancelCall }; // stands down — armed alongside goRoute
const rxEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// A plain "yes" MUST dial while the confirm is armed (2026-07-21: bare "yes" used to fall
// through to the chat brain, which re-classified the call from scratch — the double-confirm +
// "you didn't give me details" loop). Round 2 (same day): "go ahead and lock it in" style
// approvals also missed — now ANY utterance that STARTS with an affirmation dials, unless it
// contains a hesitation/change word. Safe: these matchers exist ONLY while a confirm is pending.
const GO_START = /^(?:yes|yeah|yep|sure|okay|ok|please do|affirmative|do it|go ahead|dial|call them|ring them|go for it|lock it in|confirm it|book it|make the call|place the call)\b/i;
const GO_BLOCK = /\b(?:no|not|don'?t|wait|hold on|change|instead|but|actually|cancel|later|different|first)\b/i;
function armGo(on) {
  goRoute.re = on ? { test: (q) => GO_START.test(q.trim()) && !GO_BLOCK.test(q) } : NEVER;
  noRoute.re = on ? /^(?:okay |ok |yeah )?(?:no|nope|cancel|stop|never ?mind|don'?t(?: call)?|stand down|forget it|hold off)[.!,]?$/i : NEVER;
}
async function cancelCall() {
  dismiss();
  try { await J.post('/calls_cancel', {}, 8000); } catch (_) {}
  return J.say('Very good, sir — standing down.');
}

function panel() {
  let el = $id('j-call');
  if (el) return el;
  el = document.createElement('div');
  el.id = 'j-call';
  el.style.cssText = 'position:fixed;right:26px;bottom:96px;width:322px;z-index:88;display:none;'
    + 'background:rgba(12,14,18,.95);border:1px solid rgba(96,200,255,.4);border-radius:16px;'
    + 'padding:15px 16px;backdrop-filter:blur(12px);font-family:-apple-system,"Segoe UI",sans-serif;'
    + 'box-shadow:0 12px 40px rgba(0,0,0,.5);';
  el.innerHTML = `<div style="display:flex;align-items:center;gap:9px;margin-bottom:10px;">
      <span id="jc-dot" style="width:9px;height:9px;border-radius:50%;background:#60c8ff;box-shadow:0 0 8px #60c8ff;"></span>
      <span style="font-family:'SF Mono',ui-monospace,monospace;font-size:11px;letter-spacing:.14em;color:#60c8ff;" id="jc-head">CALL</span>
      <button id="jc-x" style="margin-left:auto;background:rgba(251,113,133,.16);border:1px solid rgba(251,113,133,.55);color:#fb7185;border-radius:99px;font-size:11.5px;font-weight:600;padding:5px 13px;cursor:pointer;">✕</button>
    </div>
    <div id="jc-callee" style="font-size:14px;color:#eaf0ec;font-weight:600;"></div>
    <div id="jc-num" style="font-size:12px;color:#8a97a0;margin-top:1px;"></div>
    <div id="jc-body" style="font-size:12.5px;color:#c7d0d6;line-height:1.5;margin-top:9px;"></div>`;
  document.body.appendChild(el);
  el.querySelector('#jc-x').onclick = dismiss;
  return el;
}
function show() { panel().style.display = 'block'; }
function dismiss() { const el = $id('j-call'); if (el) el.style.display = 'none'; clearInterval(poll); pending = null; armGo(false); }

function setHead(txt, color) {
  const h = $id('jc-head'), d = $id('jc-dot');
  if (h) { h.textContent = txt; h.style.color = color; }
  if (d) { d.style.background = color; d.style.boxShadow = '0 0 8px ' + color; }
}

async function prepare(task) {
  show();
  setHead('PREPARING…', '#60c8ff');
  $id('jc-callee').textContent = ''; $id('jc-num').textContent = '';
  // neutral copy — a given number skips the lookup entirely, so never claim we're searching
  $id('jc-body').textContent = 'Setting up the call, sir…';
  const r = await J.post('/calls_prepare', { task, session: J.session }, 40000);
  if (!r || r.error) { $id('jc-body').textContent = (r && r.error) || 'I could not set that up, sir.'; setHead('—', '#8a97a0'); return J.say((r && r.error) || 'I could not set that up, sir.'); }
  pending = r;
  $id('jc-callee').textContent = r.callee || (r.kind === 'sweep' ? `Quote sweep — ${r.count} places` : '');
  $id('jc-num').textContent = r.pretty || '';
  if (r.need_number) {
    setHead('NEED NUMBER', '#f0b446');
    $id('jc-body').textContent = r.ask;
    return J.say(r.ask);
  }
  setHead('CONFIRM', '#f0b446');
  setBody(r.ask, 'say “do it” to ring — or “cancel”');
  armGo(true);
  await J.say(r.ask);
}

// S23 SECURITY: everything shown in the card is TEXT — the ask line is model output, the summary and
// outcome come from a phone transcript the OTHER party authored, and a recording link is only ever
// a real https URL. innerHTML with any of that was code execution in the desk's own origin.
function setBody(text, hint) {
  const body = $id('jc-body'); body.textContent = String(text == null ? '' : text);
  if (hint) { const h = document.createElement('div'); h.style.cssText = 'margin-top:8px;color:#8a97a0;font-size:11.5px;'; h.textContent = hint; body.appendChild(h); }
  return body;
}
function safeHttpUrl(u) {
  try { const x = new URL(String(u || ''), location.href); return /^https?:$/.test(x.protocol) ? x.href : null; } catch (_) { return null; }
}

async function supplyNumber(numText) {
  if (!pending || !pending.need_number) return false;
  const r = await J.post('/calls_number', { confirm_id: pending.confirm_id, number: numText }, 15000);
  if (!r || r.error) return J.say((r && r.error) || "That number won't dial, sir.");
  pending.need_number = false; pending.number = r.number;
  $id('jc-num').textContent = r.pretty || r.number;
  setHead('CONFIRM', '#f0b446');
  setBody(r.ask, 'say “do it” to ring');
  armGo(true);
  await J.say(r.ask);
}

// The chat brain can also arm a call via the [CALL:] tag ("book me a table at Joe's" with no
// call-word). The server returns call_confirm; 3d.html hands it here to run the same confirm flow.
window.__jarvisCallAdopt = async (r) => {
  if (!r || !r.confirm_id) return;
  pending = r; show();
  $id('jc-callee').textContent = r.callee || (r.kind === 'sweep' ? `Quote sweep — ${r.count} places` : '');
  $id('jc-num').textContent = r.pretty || '';
  if (r.need_number) {
    setHead('NEED NUMBER', '#f0b446');
    $id('jc-body').textContent = r.ask;
    return J.say(r.ask);
  }
  setHead('CONFIRM', '#f0b446');
  setBody(r.ask, 'say “do it” to ring — or “cancel”');
  armGo(true);
  await J.say(r.ask);
};

async function goCall() {
  if (!pending) return false;
  const cid = pending.confirm_id; armGo(false);
  let r; try { r = await J.post('/calls_go', { confirm_id: cid }, 30000); } catch (_) { r = null; }
  if (!r || r.error) {
    const line = (r && r.error) || 'The line would not connect, sir.';
    $id('jc-body').textContent = line;
    if (r && r.retryable) {
      // the server KEPT the confirm armed ("say 'do it' to try again") — re-arm goRoute so
      // 'do it' actually retries instead of falling to the chat brain (audit 2026-07-28 night)
      armGo(true); setHead('CONFIRM', '#f0b446');
    } else {
      pending = null; setHead('FAILED', '#fb7185');
    }
    return J.say(line);
  }
  pending = null;
  if (r.sweep_id) {                 // sweep: N parallel calls; the comparison arrives as a card
    setHead('SWEEPING', '#34d399');
    $id('jc-body').textContent = r.say;
    return J.say(r.say);
  }
  setHead('DIALING', '#60c8ff');
  $id('jc-body').textContent = 'Ringing now, sir…';
  await J.say(r.say);
  watch(r.call_id, r.callee);
}

const STATUS_UI = {
  registered: ['DIALING', '#60c8ff', 'Connecting the call, sir…'],
  ongoing:    ['ON THE CALL', '#34d399', 'On the call now — I\'ll report back, sir.'],
  ended:      ['ENDED', '#8a97a0', ''],
  error:      ['ERROR', '#fb7185', ''],
  not_connected: ['NO ANSWER', '#f0b446', ''],
};

function watch(cid, callee) {
  clearInterval(poll);
  poll = setInterval(async () => {
    let d;
    try { d = await (await fetch('/api/calls?id=' + encodeURIComponent(cid))).json(); } catch (_) { return; }
    const ui = STATUS_UI[d.status] || ['…', '#60c8ff', ''];
    setHead(ui[0], ui[1]);
    if (!d.done && ui[2]) $id('jc-body').textContent = ui[2];
    if (d.done) {
      clearInterval(poll);
      const line = d.summary || (callee + ' call finished, sir.');
      { const body = setBody(''); const sp = document.createElement('span'); sp.style.color = '#eaf0ec'; sp.textContent = line; body.appendChild(sp);
        if (d.outcome) { const o = document.createElement('div'); o.style.cssText = `margin-top:6px;color:${ui[1]};font-size:11.5px;`; o.textContent = d.outcome; body.appendChild(o); }
        const rec = safeHttpUrl(d.recording);
        if (rec) { const w = document.createElement('div'); w.style.marginTop = '6px'; const a = document.createElement('a'); a.href = rec; a.target = '_blank'; a.rel = 'noopener'; a.style.cssText = 'color:#60c8ff;font-size:11.5px;'; a.textContent = '▶ recording'; w.appendChild(a); body.appendChild(w); } }
      J.setLastNote && J.setLastNote(line);
      await J.say(line);
      // the ended-call report can END with a spoken question ("shall I pop it on your
      // calendar?") — arm the no-wake-word window AFTER the speech so a bare "yes" is heard
      // (audit 2026-07-28 night: the wake gate was discarding the offer's natural answer)
      if (J.listen) J.listen();
      setTimeout(() => { const el = $id('j-call'); if (el && el.style.display === 'block' && !pending) { /* leave it up */ } }, 100);
    }
  }, 1500);
}

// intents — ORDER MATTERS: the me-specific routes must beat the generic CALL word-match,
// or "call me when it's done" becomes a call to a business named "me".
const CALL = /\b(call|ring|phone|dial|give (?:a |them a )?(?:call|ring)|get (?:me )?on the phone with|get .+ on the line|put me through to|connect me (?:to|with)|book (?:me |us )?(?:a |an )?(?:table|reservation|appointment)|cancel (?:my |the |his )|reschedule (?:my |the |his )|move my |push (?:back |up )?my |check (?:on|the status of) my |make (?:me |us )?(?:a |an )?(?:reservation|booking|appointment)|reserve (?:me |us )?(?:a |an )?table|get (?:me |us )(?:a |an )?(?:table|quotes?)\b)/i;
const STRIP = /^(?:jarvis[,:\s]+)?(?:can you |could you |please |go ahead and |i (?:want|need) you to )*/i;
const callGate = new RegExp(CALL.source, CALL.flags);
callGate.test = (s) => CALL.test(s) && !CALL_NOT.test(s);   // S24d: a conditional or noun "call" is never a dial order
const OUTCOME_Q = /\b(did they (?:answer|pick up|say)|what did they say|how did (?:the|that) call go|any luck with the call)\b/i;
const MYNUM = /^(?:jarvis[,:\s]+)?my (?:number|cell|phone(?: number)?) is\b(.+)$/i;
const MYNUMQ = /^(?:jarvis[,:\s]+)?(?:do you (?:have|know) my (?:phone )?(?:number|cell)|what(?:'s| is) my (?:number|cell)(?: on file)?|(?:is|do you have) my (?:number|cell) on file)\b/i;
const RINGME = /^(?:jarvis[,:\s]+)?(?:call|ring) me (?:when|once|as soon as) (?:it'?s|it is|that'?s|the (?:mission|build|job|task|research) (?:is|'s)|you'?re) (?:done|finished|complete|ready|over)\b/i;
// S24d (his report: "every time he hears the word call, he calls me"): the standing-order phrasing is
// natural speech with a preamble — "I'm going out, only call me if anything urgent comes up" — so this
// is unanchored and lenient, and the CALL route below refuses conditional / noun uses of "call".
const URGENT_ON = /\b(?:only |just )?(?:call|ring) me (?:only )?(?:for|if|when|about|in case|should|unless)\b.{0,40}\b(?:urgent|important|emergenc(?:y|ies)|big|critical|can'?t wait)|\bif (?:anything|something|it'?s) (?:urgent|important|critical|an emergency).{0,40}\b(?:call|ring) me\b|\b(?:call|ring) me (?:only )?(?:for|about) (?:urgent|important|critical) (?:things|stuff|matters)\b/i;
const CALL_NOT = /\b(?:call|ring) me\b.{0,30}\b(?:if|when|only|unless|in case|should)\b|\bdon'?t (?:call|ring)\b|\bonly (?:call|ring) me\b|\b(?:a|the|my|our|this|that|on a|in a|another) (?:phone |video |zoom )?call\b|\bcall (?:at|with|about|from) \b/i;
function urgentAck(q) {
  const s = q.toLowerCase();
  if (/\bmeeting|\bpresentation|\binterview|\bclient|\bon a call/.test(s)) return "Very good, sir — have a good meeting. I'll only ring you if it can't wait.";
  if (/\bgoing out|\bheading out|\bstepping out|\bleaving|\bon the road|\bdriving|\btravel|\bflight|\bout for/.test(s)) return "Very good, sir — I'll hold the fort. I'll only ring you if it can't wait.";
  if (/\bgym|\blunch|\bdinner/.test(s)) return "Very good, sir — enjoy. I'll only ring you if it can't wait.";
  if (/\bsleep|\bbed\b|\bnap\b|\brest\b/.test(s)) return "Sleep well, sir. I'll only ring you if it truly can't wait.";
  return "Understood, sir — I'll only ring you if it can't wait.";
}
const URGENT_OFF = /^(?:jarvis[,:\s]+)?(?:stop|don'?t|quit|no more) (?:calling|ringing)(?: me)?\b/i;
const BRIEFCALL_ON = /^(?:jarvis[,:\s]+)?(?:call|ring) me (?:with|for) the briefing(?: every (?:morning|day))?(?: at (.+?))?[.!]?$/i;
const BRIEFCALL_AT = /^(?:jarvis[,:\s]+)?(?:morning )?briefing calls? at (.+?)[.!]?$/i;
const BRIEFCALL_OFF = /^(?:jarvis[,:\s]+)?(?:stop|no more|cancel) (?:the )?(?:morning|briefing) calls?[.!]?$/i;
const RECALLQ = /^(?:jarvis[,:\s]+)?(?:what did (.+?) say(?: on the (?:call|phone))?|when did (?:i|we) (?:last )?call (.+?)|find the call (?:to|with|about) (.+?))[.!?]?$/i;
const WHATSOPEN = /^(?:jarvis[,:\s]+)?(?:what(?:'s| is) (?:still )?open|(?:my |any )?open loops?|anything (?:open|outstanding|pending))[.!?]?$/i;
const CLOSELOOP = /^(?:jarvis[,:\s]+)?close (?:the )?loop (?:about |on |for )?(.+)$/i;
const CALLME = /^(?:jarvis[,:\s]+)?(?:call|ring) (?:me|my (?:phone|cell))(?: now| please)?[.!]?$/i;
// V7.1 DEMO BAY: "stage an urgent call [in two minutes]" · "run the urgent demo in 90 seconds" ·
// "stage the payment / double booking / message / signed scenario [in N minutes]"
const DEMO_URGENT = /^(?:jarvis[,:\s]+)?(?:stage|run|fire|trigger|start|launch)\b(?=.*\b(?:urgent|demo|scenario)\b).*$|\b(?:stage|state)\b(?=.{0,30}\burgent (?:call|event|demo)\b)/i;   // loose on purpose — the recogniser hears "a signed" as "assigned", "the demo" as "a demo", etc.
const NUMWORD = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, fifteen: 15, twenty: 20, thirty: 30, 'forty-five': 45, 'forty five': 45, fortyfive: 45, sixty: 60, ninety: 90 };
function demoArgs(q) {
  const s = q.toLowerCase();
  const scenario = /\bdouble/.test(s) ? 'double' : /\bpayment|\bpaid\b|\bstripe/.test(s) ? 'payment'
    : /\bmessage|\bcaller|\bvoicemail/.test(s) ? 'message' : 'signed';          // "signed" / "assigned" / "contract" / default
  const m = s.match(/\bin\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty[- ]?five|sixty|ninety)\s*(seconds?|secs?|minutes?|mins?)\b/);
  let delay_s = 90;
  if (m) { const n = NUMWORD[m[1].replace(/\s+/g, '-')] || NUMWORD[m[1]] || parseInt(m[1], 10); if (n) delay_s = /^min/.test(m[2]) ? n * 60 : n; }
  return { scenario, delay_s };
}

async function simpleCallPost(path, body, fallback) {
  let d; try { d = await J.post(path, body || {}, 20000); } catch (_) { d = null; }
  const line = (d && (d.say || d.error)) || fallback;
  return J.say(line);
}

function routes() {
  const R = (window.__jarvisRoutes = window.__jarvisRoutes || []);
  R.push(
    { re: OUTCOME_Q, handler: async () => {
        let live; try { live = await (await fetch('/api/calls')).json(); } catch (_) {}
        const el = $id('j-call'), body = $id('jc-body');
        if (body && el && el.style.display === 'block') { show(); return J.say('Here on the card, sir — ' + (body.textContent || '').slice(0, 120)); }
        return J.say('No calls on the books just now, sir.');
      } },
    { re: RINGME, handler: async () => simpleCallPost('/calls_ringme', {}, 'The ring-me hook misfired, sir.') },
    { re: URGENT_ON, handler: async (q) => {
        let d; try { d = await J.post('/calls_urgent', { on: true }, 20000); } catch (_) { d = null; }
        return J.say((d && !d.error) ? urgentAck(q) : ((d && d.error) || 'The urgent line misfired, sir.'));
      } },
    { re: URGENT_OFF, handler: async () => simpleCallPost('/calls_urgent', { on: false }, 'The urgent line misfired, sir.') },
    { re: MYNUMQ, handler: async () => simpleCallPost('/calls_myinfo', {}, 'The number check misfired, sir.') },
    { re: MYNUM, handler: async (q) => {
        const m = q.match(MYNUM);
        return simpleCallPost('/calls_mynumber', { number: (m && m[1] || '').trim() }, "That number didn't take, sir.");
      } },
    { re: BRIEFCALL_OFF, handler: async () => simpleCallPost('/calls_briefcall', { off: true }, 'The briefing schedule misfired, sir.') },
    { re: BRIEFCALL_ON, handler: async (q) => {
        const m = q.match(BRIEFCALL_ON) || [];
        const at = (m[1] || '').trim();
        if (/^(?:now|right now)$/i.test(at) || !at) return simpleCallPost('/calls_briefcall', at ? { now: true } : { now: true }, 'The briefing call misfired, sir.');
        return simpleCallPost('/calls_briefcall', { at }, 'The briefing schedule misfired, sir.');
      } },
    { re: BRIEFCALL_AT, handler: async (q) => {
        const m = q.match(BRIEFCALL_AT) || [];
        return simpleCallPost('/calls_briefcall', { at: (m[1] || '').trim() }, 'The briefing schedule misfired, sir.');
      } },
    { re: WHATSOPEN, handler: async () => simpleCallPost('/assist_loops', {}, 'The loop ledger misfired, sir.') },
    { re: CLOSELOOP, handler: async (q) => {
        const m = q.match(CLOSELOOP) || [];
        return simpleCallPost('/assist_loops', { close: (m[1] || '').trim() }, 'The loop ledger misfired, sir.');
      } },
    { re: RECALLQ, handler: async (q) => {
        const m = q.match(RECALLQ) || [];
        const topic = (m[1] || m[2] || m[3] || '').trim();
        return simpleCallPost('/calls_recall', { q: topic }, 'The call log misfired, sir.');
      } },
    { re: DEMO_URGENT, handler: async (q) => simpleCallPost('/demo/urgent', demoArgs(q), 'The demo bay misfired, sir.') },
    { re: CALLME, handler: async () => simpleCallPost('/calls_callme', { reason: 'you asked me to ring you — consider this the line check' }, 'The line to you misfired, sir.') },
    { re: callGate, handler: async (q) => {
        // if we're waiting for a number and they just said one, take it
        if (pending && pending.need_number) return supplyNumber(q);
        const task = q.replace(STRIP, '').trim();
        await prepare(task);
      } },
  );
  // if a number is pending, a bare number utterance supplies it
  R.unshift({ re: /^[\d\s+().-]{7,}$/, handler: async (q) => (pending && pending.need_number) ? supplyNumber(q) : false });
  R.unshift(noRoute);   // "no / cancel" stands down — armed only while a call is pending
  R.unshift(goRoute);   // "yes / do it" dials — outranks other bays ONLY while a call is pending (regex NEVER otherwise)
}

(function boot() {
  let n = 0;
  const w = setInterval(() => {
    if (window.__jarvis) { clearInterval(w); J = window.__jarvis; routes(); }
    else if (++n > 100) clearInterval(w);
  }, 150);
})();
