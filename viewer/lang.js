// lang.js — Jarvis V5 MULTILINGUAL bay (ES module, loaded after the core IIFE).
// Client side of multilingual mode: keeps the browser in step with the server's
// language state (jarvis-lang.json). window.__jarvisLang (BCP-47) steers both
// speech recognizers + the browser-voice picker; a 🌐 chip under the reactor
// shows the active tongue; voice routes handle "speak Spanish" / "switch to
// French" / "back to English" / "what languages do you speak". The model can
// also flip the language server-side via the [LANG:] tag from ANY phrasing —
// a light poll notices and catches the client up.
// Fully optional: if the bridge never appears, this module does nothing.

const BCP = { en: 'en-US', es: 'es-ES', fr: 'fr-FR', de: 'de-DE', it: 'it-IT', pt: 'pt-BR',
              nl: 'nl-NL', hi: 'hi-IN', ur: 'ur-PK', ar: 'ar-SA', ja: 'ja-JP', ko: 'ko-KR',
              zh: 'zh-CN', ru: 'ru-RU', tr: 'tr-TR', pl: 'pl-PL' };
const NATIVE = { en: 'English', es: 'Español', fr: 'Français', de: 'Deutsch', it: 'Italiano',
                 pt: 'Português', nl: 'Nederlands', hi: 'हिन्दी', ur: 'اردو', ar: 'العربية',
                 ja: '日本語', ko: '한국어', zh: '中文', ru: 'Русский', tr: 'Türkçe', pl: 'Polski' };
// every name the SWITCH routes accept (the server's LANG_ALIAS covers all of these)
const NAMES = 'spanish|espa[ñn]ol|french|fran[çc]ais|german|deutsch|italian|italiano|portuguese|' +
              'portugu[êe]s|dutch|hindi|urdu|arabic|japanese|korean|chinese|mandarin|russian|' +
              'turkish|polish|english';

let J, CUR = 'en';

// INSTANT boot: apply the cached language BEFORE the /api/lang round-trip returns,
// so the recognizers get the right locale on the very first mic use after a reload.
// THE EAR (2026-10-07, his ask: "I speak English, you answer in X"): the reply language and the
// LISTENING language are separate. Recognizers read window.__jarvisEar, which stays English
// unless he says "listen in Spanish" (localStorage 'jarvis-ear' = '1' → the ear follows).
let EAR_FOLLOWS = false;
try { EAR_FOLLOWS = localStorage.getItem('jarvis-ear') === '1'; } catch (_) {}
function setEar() { try { window.__jarvisEar = (EAR_FOLLOWS && CUR !== 'en') ? BCP[CUR] : ''; } catch (_) {} }
try {
  const c = localStorage.getItem('jarvis-lang');
  if (c && c !== 'en' && BCP[c]) { CUR = c; window.__jarvisLang = BCP[c]; }
} catch (_) {}
setEar();

(function boot(n) {
  if (window.__jarvis) { try { init(); } catch (e) { console.warn('[lang]', e); } return; }
  if ((n || 0) < 3600) requestAnimationFrame(() => boot((n || 0) + 1));   // ~1 min of patience
})();

function init() {
  J = window.__jarvis;
  chip(CUR);
  routes();
  sync();          // the server is the source of truth — reconcile the cache right away
  watchers();
}

// ---------- state ----------
function apply(code) {
  if (!BCP[code]) return;
  CUR = code;
  try { window.__jarvisLang = (code === 'en') ? '' : BCP[code]; } catch (_) {}
  try {
    if (code === 'en') localStorage.removeItem('jarvis-lang');
    else localStorage.setItem('jarvis-lang', code);
  } catch (_) {}
  setEar();
  chip(code);
  try { window.dispatchEvent(new CustomEvent('jarvis-lang', { detail: code })); } catch (_) {}   // 3d.html pre-translates its fixed lines
}

async function sync() {
  try {
    const d = await fetch('/api/lang').then(r => r.json());
    if (d && d.code && d.code !== CUR) apply(d.code);   // [LANG:] tag / another surface flipped it
  } catch (_) {}
}

// ---------- 🌐 chip (same pill family as #j-brain-chip) ----------
// 2026-10-05, his screenshot: hanging under #j-brain put the chip exactly where eyes.js's
// RING/CUBE/FACE row sits (46%+148px, z 60), which buried it. It now owns its own slot in the
// right-hand column, centred UNDER that row, in the gap above the EYES chip (46%+236px).
function chip(code) {
  try {
    let holder = document.getElementById('j-lang-holder');
    if (!code || code === 'en') { if (holder) holder.remove(); return; }
    if (!holder) {
      holder = document.createElement('div');
      holder.id = 'j-lang-holder';
      holder.style.cssText = 'position:fixed;right:34px;top:calc(46% + 186px);width:204px;' +
        'text-align:center;z-index:60;pointer-events:none;';
      const el = document.createElement('span');
      el.id = 'j-lang-chip';
      el.style.cssText = 'display:inline-block;font-family:"SF Mono",ui-monospace,monospace;' +
        'font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:#34d399;' +
        'border:1px solid rgba(52,211,153,.45);border-radius:999px;padding:5px 14px;' +
        'background:rgba(10,22,18,.72);backdrop-filter:blur(6px);';
      holder.appendChild(el); document.body.appendChild(holder);
    }
    document.getElementById('j-lang-chip').textContent = '🌐 ' + (NATIVE[code] || code);
  } catch (_) {}
}

// ---------- voice routes ----------
function routes() {
  const R = (window.__jarvisRoutes = window.__jarvisRoutes || []);
  // "speak Spanish" / "respond in French" / "talk to me in German" / "answer in Urdu"
  // (NOTE: "speak IN spanish" is stolen upstream by the voice-wardrobe intent — by route order)
  const SWITCH = new RegExp('^(?:jarvis[,!\\s]+)?(?:speak|talk|respond|reply|answer)(?: to me)?(?: in)? (' +
                            NAMES + ')[?.!]*$', 'i');
  // bare "switch to X" is constrained to real language names so "switch to grok" (model swap)
  // and "switch to dark mode" (OS) keep their existing server-side handling untouched
  const SWITCH2 = new RegExp('^(?:jarvis[,!\\s]+)?switch to (' + NAMES + ')[?.!]*$', 'i');
  const SWITCH3 = /^(?:jarvis[,!\s]+)?switch the language to (\w+)[?.!]*$/i;   // explicit → let the server 404 with wit
  const BACK = /^(?:jarvis[,!\s]+)?(?:go |get |take (?:it|us) )?back to (?:normal |regular |plain )?english(?: please)?[?.!]*$/i;
  const LIST = /^(?:jarvis[,!\s]+)?(?:what|which) languages (?:do you|can you) speak[?.!]*$/i;

  // "Jarvis, I'm going to speak in English and you respond to me only in Spanish" — the reply
  // language is whatever follows respond/reply/answer, wherever it sits in the sentence
  // (addressed to HIM — "you respond…" — so "how should I respond in Spanish to this client?" stays a question)
  const SWITCH4 = new RegExp('\\byou(?:\'ll| will| should| can| to)? (?:only )?(?:respond|reply|answer|talk|speak)(?: back)?(?: to me)?(?: only)? in (' + NAMES + ')\\b', 'i');
  // the ear: "listen in Spanish" / "I'll speak Spanish to you" → recognition follows; "listen in English" → back
  const EARON = new RegExp('^(?:jarvis[,!\\s]+)?(?:listen in|i(?:\'ll| will) (?:be )?speak(?:ing)?(?: to you)? in) (' + NAMES + ')(?: to you)?[?.!]*$', 'i');

  R.push({ re: EARON,   handler: async (q, m) => earTo(m[1]) });
  R.push({ re: SWITCH4, handler: async (q, m) => switchTo(m[1]) });
  R.push({ re: BACK,    handler: async () => switchTo('english') });
  R.push({ re: SWITCH,  handler: async (q, m) => switchTo(m[1]) });
  R.push({ re: SWITCH2, handler: async (q, m) => switchTo(m[1]) });
  R.push({ re: SWITCH3, handler: async (q, m) => switchTo(m[1]) });
  R.push({ re: LIST,    handler: async () => listLangs() });
}

async function switchTo(word) {
  let d;
  try { d = await J.post('/lang', { lang: word }, 15000); }
  catch (_) { await J.say("The language centre didn't answer, sir."); return; }
  if (!d || d.error || !d.code) {           // unknown tongue → the server's witty 404 lists the repertoire
    await J.say((d && d.error) || 'The language centre refused, sir.'); return;
  }
  apply(d.code);                            // recognizers + voice pick FIRST, so the line below…
  await J.say(d.line || 'Done, sir.');      // …the canned confirmation, arrives IN the new language
}

async function earTo(word) {
  const english = /^english$/i.test(word);
  EAR_FOLLOWS = !english;
  try { if (EAR_FOLLOWS) localStorage.setItem('jarvis-ear', '1'); else localStorage.removeItem('jarvis-ear'); } catch (_) {}
  if (english) { setEar(); await J.say("Understood, sir. I'll listen in English and reply in whatever language you've chosen."); return; }
  await switchTo(word);                     // listening in Spanish means replying in Spanish too
}

async function listLangs() {
  let d = null;
  try { d = await fetch('/api/lang').then(r => r.json()); } catch (_) {}
  const names = (d && d.spoken) || [];
  if (!names.length) { await J.say("I couldn't consult my phrasebook just now, sir."); return; }
  await J.say('My repertoire runs to ' + names.join(', ') + ' — ' + names.length +
              ' tongues in all, sir. Say "speak Spanish", or simply address me in one and I shall reply in kind.');
}

// ---------- tag-path catch-up: the model may execute [LANG:] server-side from ANY phrasing ----------
function watchers() {
  try { setInterval(() => { if (document.visibilityState === 'visible') sync(); }, 20000); } catch (_) {}
  try { document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') sync(); }); } catch (_) {}
  try {                                      // any answer landing on screen → re-check shortly after
    const ansEl = document.getElementById('j-answer');
    if (ansEl && window.MutationObserver) {
      let t = null;
      new MutationObserver(() => { clearTimeout(t); t = setTimeout(sync, 2000); })
        .observe(ansEl, { childList: true, characterData: true, subtree: true });
    }
  } catch (_) {}
}
