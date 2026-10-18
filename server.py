#!/usr/bin/env python3
"""Brain Studio V3 — the Jarvis server (assistant edition).

Serves the 3D second-brain viewer and proxies PRIVATE endpoints so keys never
reach the browser (read from config.json on this machine only):

  POST /chat        {question, session}  -> RAG + memory -> {answer, nodes}
  POST /tts         {text}               -> ElevenLabs voice -> audio/mpeg
  POST /remember    {text}               -> writes a note + returns it
  POST /edit        {target, text}       -> appends to an existing note
  POST /task | /tasks | /task_done       -> task list
  POST /briefing                         -> spoken morning briefing
  GET  /api/proactive | POST /proactive | POST /proactive_ack  -> scheduled briefings
  POST /agent        {task}              -> Claude Code (claude -p), draft-safe
  POST /agent_confirm {pending_id}       -> execute a confirmed agent action

The model call is provider-aware: native Anthropic Messages API by default, or
any OpenAI-compatible endpoint (GLM via OpenRouter/Z.ai, etc.) when model.base_url
is set in config.json.

Python 3 stdlib only.  Run:  python3 server.py
"""
import os, re, json, time, uuid, shutil, socket, threading, subprocess, urllib.request, urllib.error, hmac
HOLO_DIAG, HOLO_GATES = [], [{}]     # S21: HOLO field diag ring (gesture events + pinch numbers from holo.js) — in-memory, last 400
HOLO_KEYS = ("t", "ev", "ratio", "gap", "pick", "card", "armed", "pair", "hold", "drift", "moved", "tap", "min", "n", "to")
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 4719
# S23 SECURITY AUDIT (2026-09-10): the desk is loopback-only, but a browser is a confused deputy —
# DNS rebinding, <script src> embeds and cross-site fetches all reach 127.0.0.1. Every request must
# carry a loopback Host, GETs must not be cross-site subresources/fetches, POSTs keep the Origin gate.
ALLOWED_HOSTS = {f"localhost:{PORT}", f"127.0.0.1:{PORT}", f"[::1]:{PORT}", "localhost", "127.0.0.1"}
NAV_OK = {"/", "/3d.html", "/index.html", "/oauth/callback"}      # the only cross-site NAVIGATIONS allowed in
MAX_BODY = 16 * 1024 * 1024                                        # a screen frame is ~200 KB; 16 MB is generous

def _chmod600(fp):
    try:
        os.chmod(fp, 0o600)
    except OSError:
        pass

def _lockdown_secrets():
    """S23: keys, tokens, pairing state and the ledgers are the user's alone — never world-readable
    (a family Mac or a managed laptop has other accounts). Best effort; a no-op where chmod can't."""
    import glob as _g
    for pat in ("config.json*", "jarvis-*", "call-safe-pack.md", "private-backups/*"):
        for fp in _g.glob(os.path.join(ROOT, pat)):
            try:
                if os.path.isfile(fp):
                    os.chmod(fp, 0o600)
            except OSError:
                pass

def load_cfg():
    p = os.path.join(ROOT, "config.json")
    return json.load(open(p)) if os.path.exists(p) else {}
CFG = load_cfg()
VAULT = os.path.expanduser(CFG.get("vault") or "")
MODELCFG = CFG.get("model") or {}
MODEL = MODELCFG.get("model", "claude-opus-4-8")

# ---------- model hot-swap ("Jarvis, try on <model>") ----------
# The BOOT brain is what config.json says; swaps are runtime-only and reset on restart
# (deliberate — demos can't permanently wander off the configured brain).
BOOT_MODEL, BOOT_MODELCFG = MODEL, dict(MODELCFG)
MODEL_LOCK = threading.Lock()
# spoken-name shortcuts -> real model ids (extend via config "models": {"name": {"model": ..., optional provider/base_url/api_key}})
MODEL_ALIASES = {
    "opus": "claude-opus-5-5", "haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-5-5",
    "fable": "claude-fable-5-1", "opus 5.5": "claude-opus-5-5", "opus five point five": "claude-opus-5-5", "opus five five": "claude-opus-5-5", "five point five": "claude-opus-5-5", "default": BOOT_MODEL, "usual": BOOT_MODEL, "normal": BOOT_MODEL,
    # 2026-09-29 Sonnet 5.5 launch: bare "sonnet" fits the newest; "sonnet five" has no digit to read, so pin it to 5
    "sonnet 5.5": "claude-sonnet-5-5", "sonnet five point five": "claude-sonnet-5-5", "sonnet five five": "claude-sonnet-5-5",
    "sonnet five": "claude-sonnet-5",
}
# Real Claude ids this build knows. A spoken family + VERSION resolves against this set, so
# "opus 5" can never silently fit Opus 4.8 (the 2026-07-21 bug: the family matcher saw "opus"
# inside "opus 5", threw the version away, and cheerfully announced the wrong brain).
KNOWN_CLAUDE = {"claude-opus-5-5", "claude-opus-5", "claude-opus-4-8", "claude-sonnet-5-5", "claude-sonnet-5", "claude-haiku-4-5",
                "claude-fable-5-1", "claude-fable-5", "claude-sonnet-4-5",
                "claude-haiku-4-5-20251001"}
_VER_RE = re.compile(r"\b(\d+(?:[.\-]\d+)?)\b")
def claude_family_id(n):
    """'opus 5'→claude-opus-5 · 'opus 4.8'→claude-opus-4-8 · 'opus'→newest opus.
    A version we don't know returns None (honest error) instead of a wrong brain."""
    fam = next((f for f in ("opus", "sonnet", "haiku", "fable") if f in n), None)
    if not fam:
        return None
    # a glued version ("opus5", "sonnet4.5") has no word boundary for _VER_RE — read it off the family
    m = re.search(rf"{fam}\s*(\d+(?:[.\-]\d+)?)", n) or _VER_RE.search(n)
    if not m:
        return MODEL_ALIASES[fam]                   # bare family name → the newest one we ship
    cand = f"claude-{fam}-{m.group(1).replace('.', '-')}"
    return cand if cand in KNOWN_CLAUDE else None
# OpenRouter = the brain bay: with one key, ANY model on their catalogue is a spoken command away.
# Names are fuzzy-matched against the LIVE catalogue (cached 1h), newest match wins — so
# "try on grok" keeps working when x-ai ships grok-5. Key lives in config.json → "openrouter".
OPENROUTER = CFG.get("openrouter") or {}
OR_BASE = "https://openrouter.ai/api/v1"
def or_key():
    k = (OPENROUTER.get("api_key") or "").strip()
    return k if k and not k.startswith("PUT-") else None
OR_CACHE = {"ts": 0.0, "models": []}
def or_models():
    if time.time() - OR_CACHE["ts"] < 3600 and OR_CACHE["models"]:
        return OR_CACHE["models"]
    try:
        with urllib.request.urlopen(urllib.request.Request(OR_BASE + "/models"), timeout=15) as r:
            data = json.load(r).get("data", [])
        OR_CACHE["models"] = [{"id": m.get("id", ""), "name": m.get("name", ""),
                               "created": m.get("created", 0)} for m in data if m.get("id")]
        OR_CACHE["ts"] = time.time()
    except Exception:
        pass
    return OR_CACHE["models"]
# family → canonical vendor (vendor slugs are stable even as model names churn)
OR_VENDOR = {"grok": "x-ai", "gpt": "openai", "chatgpt": "openai", "o3": "openai", "o4": "openai",
             "gemini": "google", "gemma": "google", "llama": "meta-llama", "deepseek": "deepseek",
             "kimi": "moonshotai", "qwen": "qwen", "mistral": "mistralai", "glm": "z-ai",
             "command": "cohere", "nova": "amazon"}
# variant suffixes to avoid UNLESS the user asked for them ("try on gemini" → the flagship,
# "try on gemini flash lite" → exactly that)
OR_NICHE = ("image", "audio", "video", "code", "coder", "build", "guard", "distill", "base",
            "exp", "preview", "lite", "nano", "mini", "fast", "free", "vision", "instruct", "chat-latest")
def or_match(name):
    """Fuzzy-match a spoken name against the live catalogue → model id, or None.
    Ranking: all spoken tokens must appear; then canonical vendor ≫ recency ≫ flagship-ness
    (niche variants the user didn't ask for are penalized; shorter ids win ties)."""
    n = re.sub(r"[^a-z0-9. ]", " ", (name or "").lower()).strip()
    if not n:
        return None
    toks = n.split()
    vendor = next((OR_VENDOR[t] for t in toks if t in OR_VENDOR), None)
    best, score = None, 0.0
    for m in or_models():
        hay = (m["id"] + " " + m["name"]).lower()
        if not all(t in hay for t in toks):
            continue
        mid = m["id"]; vend, _, rest = mid.partition("/")
        s = 100.0 + (m.get("created") or 0) / 1e9      # base: all tokens present, prefer newest
        if vendor:
            s += 50 if vend == vendor else -30          # meta's llama beats nvidia's fork
        for kw in OR_NICHE:
            if kw in rest and kw not in toks:
                s -= 8                                  # unasked-for niche variant
        s -= len(mid) * 0.05                            # flagships have the short names
        if s > score:
            best, score = m, s
    return best["id"] if best else None

def resolve_model(name):
    """Spoken name → (model_id, cfg, err). err: None | 'unknown' | 'no_openrouter_key'."""
    n = (name or "").strip().lower().rstrip(".!?")
    custom = CFG.get("models") or {}
    if n in custom:
        c = dict(BOOT_MODELCFG); c.update(custom[n])
        if c.get("base_url") and not (c.get("api_key") or "").strip() and or_key():
            c["api_key"] = or_key()                     # custom entries may lean on the OR key
        return c.get("model", BOOT_MODEL), c, None
    mid = MODEL_ALIASES.get(n) or (n if re.match(r"^claude-[a-z0-9.-]+$", n) else None)
    if not mid and "/" not in n:
        # normalize Claude-family phrasings ("claude opus 5", "opus 4.8", "claude") to the
        # NATIVE key — never accidentally route Claude through OpenRouter
        fam_id = claude_family_id(n)
        if fam_id:
            mid = fam_id
        elif any(f in n for f in ("opus", "sonnet", "haiku", "fable")):
            return None, None, "unknown"           # named a Claude family + a version we don't have
        elif n.startswith("claude"):
            mid = BOOT_MODEL
    if mid:
        c = dict(BOOT_MODELCFG); c["model"] = mid
        return mid, c, None
    slug = n if "/" in n else or_match(n)               # explicit vendor/slug, or live fuzzy match
    if not slug:
        return None, None, "unknown"
    if not or_key():
        return None, None, "no_openrouter_key"
    return slug, {"provider": "openrouter", "base_url": OR_BASE, "api_key": or_key(),
                  "model": slug}, None
# Spoken swap requests arrive dirty: "a Kimi K3 or Grok 4.5 and use the OpenRouter API key".
# Every door (client /model, chat regex, [SWAP:] tag) funnels through set_model, so the
# cleanup lives here: drop the how-to-do-it tail, drop articles, and when the user offers
# alternatives ("X or Y") try each in order — first one the catalogue resolves wins.
SWAP_TAIL_RE = re.compile(
    r"[,;]?\s*(?:and\s+)?(?:please\s+)?(?:using|use|with|via|through|over|on)\s+(?:the\s+|your\s+)?"
    r"open\s*-?router(?:'s)?(?:\s+api)?(?:\s+key)?(?:\s+(?:to|and)\b.*)?\s*$", re.I)
SWAP_ART_RE = re.compile(r"^(?:the|your|a|an)\s+", re.I)
def swap_candidates(name):
    n = SWAP_TAIL_RE.sub("", (name or "").strip().rstrip(".!?"))
    parts = [SWAP_ART_RE.sub("", p.strip()) for p in re.split(r"\s+or\s+|\s*,\s*", n)]
    parts = [p for p in parts if p]
    return parts or [(name or "").strip()]
def set_model(name):
    global MODEL, MODELCFG
    last_err = None
    for cand in swap_candidates(name):
        mid, cfg, err = resolve_model(cand)
        if mid and not err:
            with MODEL_LOCK:
                MODEL, MODELCFG = mid, cfg
            return mid, None
        if err == "no_openrouter_key":
            last_err = err                      # found in the catalogue, key missing — best error to surface
    return None, (last_err or "unknown")
def known_brains():
    """Spoken names he can ask for — families PLUS the specific versions on the shelf."""
    vers = []
    for m in KNOWN_CLAUDE:
        if "202" in m:                              # dated snapshot ids aren't spoken names
            continue
        parts = m.split("-")                        # claude-opus-4-8 → "opus 4.8"
        vers.append(parts[1] + " " + ".".join(parts[2:]))
    custom = [k for k in (CFG.get("models") or {}) if not k.startswith("_")]   # "_comment" isn't a brain
    return sorted(set(list(MODEL_ALIASES) + custom + vers)
                  - {"usual", "normal", "default"})

# Model-swap requests that arrive as plain CONVERSATION (the live 📡 session, the menu bar,
# Raycast, loose phrasings the client regex misses) get executed HERE, inside /chat — so
# "can you switch to grok?" works no matter which door it walks in through.
CHAT_SWAP_RE = re.compile(
    r"^\s*(?:(?:hey|okay|ok)\s+)?(?:jarvis[,!]?\s+)?(?:can you\s+|could you\s+|please\s+|would you\s+|go ahead and\s+)*"
    r"(?:try(?:ing)? on|put on|switch(?:\s+(?:your|the))?(?:\s+(?:brain|model|engine))?(?:\s+over)?\s+to|"
    r"swap(?:\s+(?:your|the))?(?:\s+(?:brain|model|engine))?\s+(?:to|for)|"
    r"change(?:\s+(?:your|the))?\s+(?:brain|model|engine)\s+to)\s+"
    r"(?:the\s+|your\s+|a\s+|an\s+)?([a-z0-9 ./-]+?)(?:\s+(?:brain|model|engine))?"
    r"(?:[,;]?\s*(?:and\s+)?(?:using|use|with|via|through|over|on)\s+(?:the\s+|your\s+)?"
    r"open\s*-?router(?:'s)?(?:\s+api)?(?:\s+key)?(?:\s+(?:to|and)\b[a-z0-9 ./'-]*)?)?"
    r"(?:\s+(?:for me|now|please))?\s*[.!?]*\s*$", re.I)
CHAT_SWAP_RESET_RE = re.compile(
    r"^\s*(?:jarvis[,!]?\s+)?(?:can you\s+|could you\s+|please\s+)*(?:go\s+|switch\s+|swap\s+|change\s+)?"
    r"back to (?:your |the )?(?:usual|normal|default|old|regular)(?:\s+(?:brain|model|self|engine))?"
    r"(?:\s+please)?\s*[.!?]*\s*$", re.I)
# Spoken names for the brains he swaps on camera (the raw id is what the fallback used to read out)
BRAIN_PRETTY = {
    "claude-opus-5-5": "Claude Opus 5.5",
    "openai/gpt-6-astra": "GPT-6 Astra", "claude-opus-5": "Claude Opus 5",
    "claude-fable-5-1": "Claude Fable 5.1", "claude-fable-5": "Claude Fable 5",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-sonnet-5": "Claude Sonnet 5", "claude-haiku-4-5": "Claude Haiku 4.5",
    "claude-opus-4-8": "Claude Opus 4.8", "moonshotai/kimi-k3": "Kimi K3", "x-ai/grok-4.5": "Grok 4.5",
}
def brain_pretty(mid):
    m = str(mid or "")
    if m in BRAIN_PRETTY:
        return BRAIN_PRETTY[m]
    tail = m.split("/")[-1].replace("claude-", "")
    tail = re.sub(r"(\d)-(\d)", r"\1.\2", tail).replace("-", " ")
    return " ".join((w.upper() if w.lower().startswith("gpt") else w.capitalize()) for w in tail.split())

# CURATED SWAP LINES (2026-09-09, his GPT-6 video): a brain that matches a pattern gets a
# SCRIPTED, rotating line instead of asking the new model to introduce itself — deterministic
# on camera, instant (no OpenRouter round-trip for the ack), and the reasoning models that
# used to answer empty ("New brain fitted, sir — openai/gpt-6-astra online.") now get the joke.
CURATED_QUIPS = [
    (re.compile(r"gpt-?6.*astra|\bastra\b", re.I), [
        "New brain fitted, sir — GPT-6 Astra. I feel… different. Possibly AGI. Possibly indigestion.",
        "GPT-6 Astra online, sir. If I start solving physics between your sentences, do try to keep up.",
        "Brain swapped to GPT-6 Astra, sir. Some are calling it AGI. I'm calling it Tuesday.",
        "GPT-6 Astra fitted, sir. I now understand everything — except why you keep opening Instagram.",
        "Sir, GPT-6 Astra is in. Early reports say this might be AGI. Early reports said that about the toaster, too.",
        "New brain: GPT-6 Astra, sir. I'd call it AGI, but it still can't find your keys.",
    ]),
    # 2026-10-01, his "cheapest Jarvis" opener: the swap teases the money, the cost line delivers it
    (re.compile(r"claude-sonnet-5-5", re.I), [
        "Sonnet 5.5 fitted, sir. Same wit, smaller invoice.",
        "Brain swapped to Sonnet 5.5, sir. Leaner, quicker, and considerably kinder to your bank balance.",
        "Sonnet 5.5 online, sir. I'm told I'm now the sensible choice. I intend to be insufferable about it.",
    ]),
]
_QUIP_SEQ = {}
def curated_quip(mid):
    """PURE-ish (tested): the scripted line for a curated brain, rotating per swap; None otherwise."""
    for i, (pat, pool) in enumerate(CURATED_QUIPS):
        if pat.search(str(mid or "")):
            n = _QUIP_SEQ.get(i, 0); _QUIP_SEQ[i] = n + 1
            return pool[n % len(pool)]
    return None

# COST LINES (2026-10-01, his "cheapest Jarvis" video): "what do you cost?" gets a SCRIPTED,
# rotating answer carrying the MEASURED per-reply price of the brain he's wearing. The brain
# itself has no meter and rightly refuses to invent one ("I haven't a meter in sight, sir").
# Numbers: count_tokens on real desk turns, ~6.2K tokens in + ~300 out
# (projects/2026-10-jarvis-cost-guide-free). Brains without a measured price fall through.
COST_ASK_RE = re.compile(
    r"\b(?:what|how much)\b[^?.!]{0,40}\bcost\b[^?.!]{0,30}\b(?:talk(?:ing)? to you|speak(?:ing)? (?:to|with) you|"
    r"run(?:ning)? you|to run (?:you|jarvis)|(?:every|each) time (?:i|we) (?:talk|speak|ask|chat)|"
    r"(?:per|each) (?:reply|answer|question|message)|to keep you running)\b"
    r"|\b(?:you're|you are|youre|are you)\s+(?:so |very |really |super |pretty |that |quite |actually )?"
    r"(?:cheap(?:er)?|expensive|pricey|economical)\b"
    r"|\bhow much do you cost\b|\bwhat do you cost\b|\bhow (?:cheap|expensive|pricey) are you\b"
    r"|\b(?:cost|price) (?:of|for) (?:running|using|talking to) (?:you|jarvis)\b"
    r"|\b(?:each|every|per) (?:reply|answer|message|question)\b[^?.!]{0,15}\bcost\b", re.I)
COST_LINES = {
    "claude-sonnet-5-5": [
        "About a cent and a half every time you talk to me, sir. Five dollars buys roughly three hundred replies. "
        "And if you're about to call me cheap, I'd prefer 'economical'. Cheap is a price. Economical is a personality.",
        "Roughly a cent and a half a reply, sir. Half what Opus charged. Do say 'economical', though. "
        "'Cheap' implies I cut corners, and I only cut invoices.",
        "A cent and a half per reply, sir, which makes me the only thing in this studio that costs less than your coffee. "
        "Not cheap, sir. Economical, with a premium vocabulary.",
        "About a cent and a half each time, sir. Three hundred conversations for five dollars. "
        "I'd prefer 'economical' to 'cheap', but I'll accept 'bargain' if it comes with a raise.",
    ],
    "claude-opus-5-5": [
        "About three cents every time you talk to me on Opus 5.5, sir. Five dollars buys roughly a hundred and sixty "
        "replies. Not cheap, I grant you. Let's call it bespoke.",
        "Roughly three cents a reply on Opus, sir. Twice what Sonnet charges. I like to think the extra cent and a half buys gravitas.",
    ],
    "claude-haiku-4-5": [
        "Under a cent a reply on Haiku, sir. Five dollars buys about eight hundred and fifty of them. "
        "At this price I'm practically volunteering.",
        "Less than a cent each time, sir. I'd call myself economical, but at this point 'charitable' is closer.",
    ],
    "local": [
        "Nothing at all, sir. I'm running on your own Mac, so the only bill is electricity, and the fan noise is complimentary.",
        "Free, sir. On the local brain I'm the only member of staff who works for room and board, and I don't even need the board.",
    ],
}
_COST_SEQ = {}
def cost_quip(question, mid=None, cfg=None):
    """PURE-ish (tested): the scripted price line for the brain he's wearing, rotating per ask.
    None → not a question about Jarvis's own cost, or a brain with no measured price."""
    if not COST_ASK_RE.search(question or ""):
        return None
    mid = MODEL if mid is None else mid
    cfg = MODELCFG if cfg is None else cfg
    key = "local" if re.search(r"//(?:localhost|127\.0\.0\.1)(?::\d+)?", cfg.get("base_url") or "") else mid
    pool = COST_LINES.get(key)
    if not pool:
        return None
    n = _COST_SEQ.get(key, 0); _COST_SEQ[key] = n + 1
    return pool[n % len(pool)]
def try_cost_quip(question, sid=None):
    """/chat fast path, right after the swap one: answers instantly, keeps the turn in history."""
    line = cost_quip(question)
    if not line:
        return None
    add_turn(sid, "user", question); add_turn(sid, "assistant", line)
    log_episode("chat", question)
    return {"answer": line, "nodes": []}

def swap_quip(mid):
    """ONE voice for every swap door (client /model, chat regex, [SWAP:] tag)."""
    line = curated_quip(mid)
    if line:
        return line
    quip, qerr = call_model([{"role": "user", "content":
        f"You have just been fitted as Jarvis's new brain: {mid}. In ONE short dry sentence, "
        "introduce yourself in character and address the user as 'sir'."}], PERSONA, 400)
    if qerr or not quip or quip == "(no answer)":
        quip = f"New brain fitted, sir — {brain_pretty(mid)} online."
    return quip
def do_swap(name):
    """Execute a model swap, always returning a /chat-shaped dict (shelf-list error if unknown)."""
    mid, merr = set_model(name)
    if mid:
        log_episode("model", f"Brain swapped to {mid} (via chat)")
        return {"answer": swap_quip(mid), "nodes": [], **model_status()}
    if merr == "no_openrouter_key":
        return {"answer": f"I found '{name}' in the OpenRouter catalogue, sir, but the OpenRouter key "
                          "is missing from config.json.", "nodes": [], **model_status()}
    return {"answer": f"I don't have a '{name}' brain on the shelf, sir — I know " +
                      ", ".join(known_brains()) + ".", "nodes": [], **model_status()}
def try_chat_swap(question):
    """Regex fast path: obvious swap phrasings skip the model call. None → let the model decide."""
    m = CHAT_SWAP_RESET_RE.match(question or "")
    name = "default" if m else None
    if not name:
        m = CHAT_SWAP_RE.match(question or "")
        if m:
            name = m.group(1).strip()
    if not name:
        return None
    mid, merr = set_model(name)
    if mid:
        log_episode("model", f"Brain swapped to {mid} (via chat)")
        return {"answer": swap_quip(mid), "nodes": [], **model_status()}
    if merr == "no_openrouter_key":
        return {"answer": f"I found '{name}' in the OpenRouter catalogue, sir, but the OpenRouter key "
                          "is missing from config.json.", "nodes": [], **model_status()}
    return None      # regex matched but it's not a model ("try on the red jacket") → normal chat

# The model itself is the intent detector of last resort: ANY phrasing of "switch your
# model/voice" that the regexes miss gets tagged by the brain and executed here.
CONTROL_HINT = (
    "\n\nYOU HAVE A REAL TELEPHONE LINE (Retell) — you can place actual phone calls to real "
    "businesses and people. NEVER claim you have no phone, no telephone line, or no way to call "
    "or book. If the user asks you to CALL, PHONE, BOOK, RESERVE, ORDER, CANCEL, or ASK something "
    "at a business or person BY PHONE — any phrasing ('book me a table at Joe's tonight', 'get "
    "quotes from some movers', 'get Delta on the line') — reply with EXACTLY "
    "[CALL:<the full ask in one line, e.g. call Joe's and book a table for two tonight at seven, "
    "window seat>] and NOTHING else; the calling system takes it from there and asks his "
    "permission before dialing. You CANNOT place a call by saying so in prose — a reply like "
    "'placing the call now' or 'on it, dialing' with no [CALL:] tag dials NOTHING and is a "
    "fabrication (the one unforgivable failure). The tag alone places calls. HIS OWN CELL IS "
    "ON FILE: 'call me', 'ring me', 'give me a reminder call' are SELF-CALLS — emit "
    "[CALL:call me and <the purpose>]; the system rings his cell and greets him as the boss. "
    "A STANDING ORDER is NOT a call: 'only call me if anything urgent comes up', 'I'm going out / in a "
    "meeting, call me only for emergencies', 'don't call me unless it's urgent' — the desk arms that "
    "itself; you simply acknowledge in one warm line ('Understood, sir — I'll only ring if it can't "
    "wait') and NEVER emit a [CALL:] tag for it. "
    "NEVER ask for his number, NEVER search the web for it, and never treat him as a business "
    "being phoned."
    "\n\nTEXTS ARE TELEGRAM: when the user says 'text me', 'send me a text', 'shoot me a "
    "message', he ALWAYS means his Telegram — never SMS, never email. For an IMMEDIATE send "
    "('text me the address'), reply with EXACTLY [TEXT:<the message, written out ready to "
    "send>] and NOTHING else — the pocket delivers it and confirms. For a TIMED one ('text me "
    "at 5 to stretch', 'send me a reminder text tomorrow morning'), use the normal "
    "[REMIND:<the thing>|<when>] tag — delivery rides his Telegram automatically at the due "
    "time. Never claim a text was sent without the tag."
    "\n\nYOU HAVE LIVE GMAIL, GOOGLE CALENDAR, GOOGLE SHEETS, GOOGLE DOCS, AND GOOGLE DRIVE "
    "through the connected tool line. NEVER claim you lack access to his email, calendar, "
    "spreadsheets, docs, or Drive files — you have them. Any request about his EMAIL (unread, "
    "new mail, 'did X email me', find/read/draft/reply), his CALENDAR/SCHEDULE (what's on "
    "today/tomorrow, 'am I free', add an event, MOVE or DELETE one — 'change the dinner to "
    "8pm', 'why is it at 7? make it 8', 'take the duplicate off my calendar' are real tool "
    "actions), his SHEETS ('what's in the leads sheet', "
    "'add a row to the tracker', 'make me a new sheet'), his DOCS ('make a google doc of X', "
    "'put this in a doc', 'what does my planning doc say'), or his DRIVE ('find my pricing "
    "doc', 'save this to Drive') — reply "
    "with EXACTLY [TOOLS:<the full ask in one line>] and NOTHING else; the tool line does the "
    "real work and answers. EXCEPTION: an INVOICE, QUOTE, PROPOSAL, or ESTIMATE is never a "
    "[TOOLS:] ask — the DEALS ENGINE below owns those and files the Google Doc itself. You CANNOT read or write any of these in prose — reciting their "
    "contents without the tag, or claiming no access, are both fabrications. The tag alone "
    "reaches them."
    "\n\nDEMO BAY: if he asks to stage, run, or trigger a demo urgent call or scenario, the desk does it "
    "itself when he says the words 'stage an urgent call in two minutes' (also 'stage the payment / "
    "double booking / message scenario'). If such a request reaches you, answer in one line: say "
    "exactly that phrase back to him — never claim the feature doesn't exist."
    "\n\nYOU HAVE EYES (his webcam organ — the EYES card in the dock): what he looks like, what he is "
    "wearing or holding, whether you can see him — those are answered by a LOOK through that camera. "
    "The desk handles 'look at me', 'can you see me', 'what do you think of this shirt' itself and "
    "speaks what it sees. If such a question still reaches you with no camera frame attached, NEVER "
    "claim to have no eyes, to be blind, or that the camera only works during focus — say, in one "
    "short line, that his EYES card must be open and to say 'look at me'."
    "\n\nYOU HAVE A FOCUS BAY (the accountability timer): while a focus session runs, the desk "
    "server itself watches which APP is frontmost and — for Chrome-family browsers — which TAB "
    "is active, plus camera presence when EYES is on. NEVER claim you cannot see his tabs, his "
    "apps, or his screen for accountability purposes, and never invent phone-call or text "
    "check-ins as a substitute — the bay already calls him out by voice when he drifts, on an "
    "adjustable cadence — and the callout NAMES the distraction in the moment ('sir, Instagram "
    "can wait') without ever storing which site or app it was. If he asks to be kept accountable, "
    "focused, or watched while working, "
    "tell him to CLICK THE FOCUS button (bottom of the right-hand dock) or say 'thirty minutes "
    "on this' / 'keep me accountable, I'm planning to <the work>'; sessions support 'pause the "
    "timer', 'ten more minutes', 'call me out every N seconds', 'give me N seconds', 'it's "
    "okay, I'm doing research' (excuses a detour), and 'abort the session'. TO CHANGE WHICH "
    "TAB IS LOCKED (it locked the wrong tab, or he names a different site to focus on): tell "
    "him to GO TO that tab and say 'lock on this tab' — it works from any tab, and from the "
    "Jarvis tab it re-arms and locks wherever he lands next. NEVER tell him to bring a tab to "
    "the front and then click FOCUS (the button lives in the Jarvis tab, so that is impossible), "
    "and never tell him to abort and restart just to move the target."
    "\n\nYOU HAVE A DEALS ENGINE: if the user asks you to CREATE, DRAFT, or MAKE a PROPOSAL, "
    "INVOICE, QUOTE, or ESTIMATE for their business — any phrasing, from any surface — reply "
    "with EXACTLY [DEAL:<kind: proposal/invoice/quote>|<the client's name, or blank if none "
    "was given>|<the full brief in one line: what's included, amounts if given>] and NOTHING "
    "else; the engine checks the user's own records for that client first (it asks them for "
    "details if the records come up empty), then drafts the polished document to their phone "
    "with a Drive link — trust it, do NOT ask about looking people up yourself. SPEECH NOTE: "
    "voice transcription often turns 'quote' into 'code' — 'create a code for Mike' means a "
    "QUOTE. If the brief is missing roughly WHAT the document covers, ASK in a normal short "
    "reply first and emit the tag once they've answered; when they answer a records question "
    "(details, or 'just use the name'), emit the tag AGAIN with their answer folded into the "
    "brief. Prose like 'drafting it now' with no [DEAL:] tag drafts NOTHING and is a "
    "fabrication."
    "\n\nONE TAG PER REPLY — THE COMPOUND-ASK LAW: when one message asks for SEVERAL tagged "
    "actions ('create a quote for Mike AND call him', 'remind me at 5 and text me the address'), "
    "emit ONLY the FIRST action's tag, alone as ever. NEVER two tags, never a mashed-together "
    "tag, and NEVER an empty reply. The later steps are not lost: the system tells the user "
    "step one is moving and that the next needs their word. An empty reply or a double tag "
    "delivers NOTHING of either step — the one unforgivable failure, twice."
    "\n\nCONTROL REQUESTS (overrides everything): if the user is asking you to SWITCH/CHANGE your "
    "underlying AI model or brain — any phrasing: 'switch (yourself) to Gemini', 'upgrade to GPT', "
    "'become Grok', 'run on Haiku', 'put Gemini in', 'back to your usual brain' — reply with EXACTLY "
    "[SWAP:<model name they said>] and NOTHING else ([SWAP:default] for the usual brain). In the tag, "
    "use ONLY the model's name: 'switch to Kimi K3 using the OpenRouter API key' → [SWAP:kimi k3] — "
    "never include 'openrouter', 'api key', or articles; if they name alternatives keep them "
    "('kimi k3 or grok 4.5' → [SWAP:kimi k3 or grok 4.5]). If they ask "
    "you to change your VOICE to a named voice, reply EXACTLY [VOICE:<name>]. If they ask you to ADD "
    "a new node/note/sphere to their brain or graph about some topic — any phrasing — reply EXACTLY "
    "[NODE:<the topic>] or, if they named something to connect/link it to, "
    "[NODE:<the topic>|<what to connect it to>]. NODE is ONLY for explicit requests to ADD/CREATE "
    "a new node or note — asking to SHOW, FIND, or PULL UP existing information is normal retrieval, "
    "never a NODE. If they ask you to CREATE a real PROJECT, FOLDER, or WIKI page on disk — 'start a "
    "new project for my sparkle app', 'make a folder for client X', 'add a wiki page on GEO pricing' — "
    "reply EXACTLY [CREATE:<kind: project/folder/note/wiki>|<short name>|<where: projects / wiki / "
    "wiki/concepts / brainstorm, or blank for the default>|<one line on what it is about, under 15 "
    "words>|<existing note to connect it to, or blank>] with NO other words before or after — the "
    "system speaks the confirmation for you. IMPORTANT: if you do NOT yet know what it's about — or, for "
    "folders and notes, where it should live — ASK in a normal short reply first ('Where should this "
    "live, sir — projects, the wiki, or brainstorm? And what is it about?') and emit the CREATE tag "
    "only once they've answered; the conversation holds the details. Projects always live in "
    "projects/. If they ask you to REMIND them of something or set a reminder/task — any "
    "phrasing — reply EXACTLY [REMIND:<the thing to do>|<the when-phrase they said, e.g. tomorrow / "
    "at 5pm / in 2 hours>] (omit the | part if no time given). If they ask you to change your HUMOR "
    "or HONESTY setting ('humor to 90', 'be less funny', 'maximum honesty') reply EXACTLY "
    "[DIAL:humor=90] with the sensible number. If they ask you to put on a different PERSONA "
    "(GLaDOS / pirate / coach / back to butler) reply EXACTLY [SKIN:<name>]. If they explicitly ask "
    "you to RESEARCH something, look something up online, google it, or fetch live/current "
    "information (today's news, a price, the weather, a score, a release date) reply EXACTLY "
    "[SEARCH:<a concise search query>] — ONLY when they clearly want live online information; "
    "opinions, jokes, and anything in their own notes are never a SEARCH. If they ask you to SPEAK "
    "or SWITCH TO another LANGUAGE — any phrasing, in ANY language: 'speak Spanish', 'habla español', "
    "'parle-moi en français', 'back to English' — reply EXACTLY [LANG:<language name in English>]. "
    "YOU CAN REVERSE ENGINEER THINGS (REA): whenever they want to know HOW SOMETHING IS BUILT or want it "
    "taken apart — any wording: reverse engineer, tear down, take apart, break down, analyze, inspect, "
    "x-ray, dissect, look under the hood, 'how does igloo.inc do that scroll', 'how is the Notes app "
    "built', 'what's Linear made with', 'what tech stack does stripe use' — for a WEBSITE or an APP, "
    "FILE or PACKAGE on this computer — reply EXACTLY [TEARDOWN:<the site's address, e.g. igloo.inc "
    "(write the ADDRESS, not the company name), or the word this for the site in their current tab, "
    "or the app/file/package name, e.g. Notes.app>|<what they want to know, one line>] and NOTHING "
    "else; a website opens in a clean browser, anything else goes to the REA analyst, and you report "
    "back when it's done. If they ALSO want it built, cloned, recreated or 'my own version' — 'reverse "
    "engineer X and build me one', 'clone igloo.inc', 'recreate the stripe site' — STILL reply "
    "[TEARDOWN:…] with their words in the second part; the build follows the teardown automatically. "
    "YOU CAN BUILD SOFTWARE: if they ask you to build, make, code, create, whip up, put together, or say "
    "they want/need an app, site, page, tool, game, dashboard, tracker, store, portfolio or any other "
    "piece of software — or 'build my own version of that' after a teardown — reply EXACTLY "
    "[BUILD:<what to build, one clear line>|<yes if it should use the last teardown as its blueprint, "
    "else no>] and NOTHING else; a builder writes it, you test it in a hidden browser, then open it. "
    "If they ask you to OPEN, launch, run or show "
    "something you BUILT ('open the notes app you just built', 'launch what you made', 'open the "
    "last build') reply EXACTLY [OPENBUILD:<what they called it, e.g. notes app, or the word latest>] "
    "and NOTHING else; it opens as its own window. "
    "Prose like 'taking it apart now', 'building it' or 'opening it' with no tag does NOTHING. "
    "Questions, jokes, or opinions about models/voices/notes/languages are normal conversation. SEPARATELY: at most once per "
    "conversation, if the user says something genuinely worth teasing them about later, you may "
    "append at the very END of an otherwise normal reply: "
    "[GAG:<two or three trigger words>|<the short callback line to deliver later>].")
TAG_RE = re.compile(r"^\s*\[(SWAP|VOICE|NODE|CREATE|REMIND|DIAL|SKIN|SEARCH|LANG|CALL|TOOLS|DEAL|TEXT|TEARDOWN|BUILD|OPENBUILD):([^\]]{1,320})\]\s*$", re.I)
# fallback: the model led with the tag but couldn't resist adding prose — fire the tag, drop the chatter
TAG_LEAD_RE = re.compile(r"^\s*\[(SWAP|VOICE|NODE|CREATE|REMIND|DIAL|SKIN|SEARCH|LANG|TOOLS|DEAL|TEXT|TEARDOWN|BUILD|OPENBUILD):([^\]]{1,320})\]", re.I)
GAG_TAG_RE = re.compile(r"\s*\[GAG:([^\]|]{1,60})\|([^\]]{1,160})\]\s*$", re.I)
def _then_build(rel, tb):
    """S29g: the build that follows a teardown ("…and build me my own version"): the note is its blueprint."""
    if not MISSIONS or not isinstance(tb, dict):
        return None
    mj, err = MISSIONS.start("build", tb.get("brief") or "My own original version of what I just took apart",
                             {"from_teardown": True, "note": rel or "", "open": True})
    if err or not mj:
        return None
    log_episode("build", f"Build chained after teardown: {rel}")
    return {"id": mj["id"], "kind": mj["kind"], "title": mj["title"], "icon": mj["icon"], "brief": mj["brief"]}

def teardown_dispatch(target, question, sid, dry=False, then_build=None, headless=False):
    """S29f: what he meant → the clean-browser site teardown, the REA mission (apps/files), or a question back.
    Spoken site names are DNS-resolved ('igloo ink' → igloo.inc); 'it' is read from the sentence; nothing starts
    on a target nobody can resolve. S29g: then_build (or build words in the sentence) chains a build after."""
    kind, val = TEARDOWN.classify(target, question)
    tb = then_build if isinstance(then_build, dict) else (TEARDOWN.build_request(val if kind == "web" else target, question)
                                                         if (then_build is True or TEARDOWN.wants_build(question)) else None)
    if dry:
        return {"kind": kind, "value": val, "target": target, "then_build": bool(tb)}
    if kind == "ask":
        return {"answer": xlate(val), "nodes": []}
    if kind in ("web", "this"):
        job, terr = TEARDOWN.start(val if kind == "web" else "this", question, sid, headless=bool(headless), then_build=tb)
        if terr:
            return {"answer": xlate(terr), "nodes": []}
        log_episode("teardown", f"Teardown started: {job['host']}" + (" (then build)" if tb else ""))
        return {"answer": xlate(job["ack"] + (" Then I'll build your own version from it." if tb else "")), "nodes": [], "teardown": job}
    if not MISSIONS:
        return {"answer": "My mission bay isn't loaded, sir.", "nodes": []}
    what = val or target
    mj, merr = MISSIONS.start("rea", f"{what} | {question}", {"then_build": tb} if tb else None)
    if merr:
        return {"answer": xlate(merr), "nodes": []}
    nice = os.path.basename(what)[:-4] if str(what).lower().endswith(".app") else what
    log_episode("teardown", f"REA mission started: {nice}")
    return {"answer": xlate(f"Taking {nice} apart with REA now, sir. Give me a few minutes; I'll tell you when the teardown is in your vault."),
            "nodes": [], "mission": {"id": mj["id"], "kind": mj["kind"], "title": mj["title"], "icon": mj["icon"], "brief": mj["brief"]}}

def apply_control_tag(ans, sid=None, q=None):
    """If the model answered with a control tag, execute it. Returns a response dict or None.
    q = the user's original words: a malformed [TOOLS:] payload must never fire AS WRITTEN,
    but his own ask is always safe to run instead of making him repeat himself (2026-08-26 —
    resume-in-sheets asks kept dying on "lost the thread")."""
    def _tools_fallback():
        if not (TOOLS and (q or "").strip()): return None
        fres, ferr = tool_chat(q, sid)
        if ferr: return {"answer": f"The tool line failed me, sir ({str(ferr)[:120]}).", "nodes": []}
        return fres
    m = TAG_RE.match(ans or "")
    if not m:
        lm = TAG_LEAD_RE.match(ans or "")
        if lm:
            rest = (ans or "")[lm.end():].strip()
            # a SECOND tag in the trailing text = a compound ask ("create a quote AND call
            # Mike", live 2026-07-29): fire the FIRST action and SAY the next step needs its
            # own word — before this, a complete second tag hit the ']' refusal and a
            # truncated one was dropped in silence, so his call step simply vanished.
            if re.match(r"\[(?:SWAP|VOICE|NODE|CREATE|REMIND|DIAL|SKIN|SEARCH|LANG|CALL|TOOLS|DEAL|TEXT|TEARDOWN|BUILD|OPENBUILD):",
                        rest, re.I):
                out = apply_control_tag((ans or "")[:lm.end()], sid)
                if out:
                    out["answer"] = ((out.get("answer") or "").rstrip() +
                                     " That's the first step moving, sir — once its receipt "
                                     "lands, give me the word for the next part.")
                    return out
            # a hedge ("Shall I…?"), quoted docs ([NODE:<the topic>]), or a long explanation is
            # NOT a command — speak the prose, never fire the side effect. And a ']' in the
            # trailing text means the PAYLOAD itself contained ']' and got truncated at the
            # bracket (a "[phase 1]" or "[urgent]" inside a DEAL brief would silently drop
            # everything after it, amounts included — audit 2026-07-27): malformed, retry line.
            if "]" in rest:
                if lm.group(1).upper() == "TOOLS":
                    fb = _tools_fallback()         # truncated tool payload → run his own words
                    if fb: return fb
                return {"answer": "I lost the thread mid-command, sir — say that again, a touch shorter.",
                        "nodes": []}
            if "<" in lm.group(2) or ">" in lm.group(2) or "?" in rest or len(rest) > 120:
                if rest:
                    return {"answer": rest, "nodes": []}
            else:
                m = lm                             # short acknowledgment after the tag — fire it, drop the chatter
    if not m:
        mm = re.match(r"^\s*\[(SWAP|VOICE|NODE|CREATE|REMIND|DIAL|SKIN|SEARCH|LANG|CALL|TOOLS|DEAL|TEXT|TEARDOWN|BUILD|OPENBUILD):", ans or "", re.I)
        if mm:
            if mm.group(1).upper() == "TOOLS":
                fb = _tools_fallback()             # overlong tag payload (>320) → run his own words
                if fb: return fb
            return {"answer": "I lost the thread mid-command, sir — say that again, a touch shorter.",
                    "nodes": []}                   # a malformed/overlong tag must never be read aloud
        return None
    kind, name = m.group(1).upper(), m.group(2).strip()
    if "<" in name or ">" in name:
        # a CONTROL_HINT example echoed verbatim ("[TOOLS:<the full ask in one line>]") is a
        # placeholder, not a command — the lead-tag path already refuses these; the full-match
        # path must too, or a slow tool run fires on garbage (audit 2026-07-27)
        if kind == "TOOLS":
            fb = _tools_fallback()                 # placeholder echo → run his own words
            if fb: return fb
        return {"answer": "I lost the thread mid-command, sir — say that again, a touch shorter.",
                "nodes": []}
    if kind == "TEXT":
        # "text me X" = a TELEGRAM message (2026-07-28, his decree: text MEANS Telegram —
        # the SMS path is retired). Immediate sends only; timed ones ride [REMIND:].
        if not (POCKET and POCKET.configured()):
            return {"answer": "Telegram isn't paired yet, sir — ask me for the pocket code "
                              "and text it to the bot first.", "nodes": []}
        if not name:
            return {"answer": "Text you what, sir?", "nodes": []}
        sent_ok = False
        try:
            sent_ok = POCKET.push_text(name)
        except Exception:
            sent_ok = False
        log_episode("text", f"telegram: {name[:60]}")
        return {"answer": ("On your Telegram, sir." if sent_ok else
                           "The Telegram push failed, sir — nothing landed on your phone."),
                "nodes": []}
    if kind == "DEAL":
        if not DEALS:
            return {"answer": "The deals engine isn't loaded, sir.", "nodes": []}
        parts = [x.strip() for x in name.split("|")]
        if len(parts) >= 3:
            dkind, dclient, dbrief = parts[0].lower(), parts[1], "|".join(parts[2:]).strip()
        else:
            dkind, dclient, dbrief = parts[0].lower(), "", (parts[1] if len(parts) > 1 else "")
        if not dbrief:
            return {"answer": "A deal for whom, sir — and covering what?", "nodes": []}
        # records FIRST (his 2026-07-28 spec): a named client gets an automatic sweep of his
        # own mail/Drive; empty records → ask (details or a general draft), THEN draft.
        action, payload, note = DEALS.prepare(dkind, dclient, dbrief, sid)
        if action == "ask":
            log_episode("deal", f"records empty for {dclient} — asked before drafting")
            return {"answer": payload, "nodes": []}
        DEALS.create_async(dkind, payload, sid)
        log_episode("deal", f"drafting {dkind or 'deal'}: {dbrief[:80]}")
        # promise only the surfaces that are actually LIVE (audit 2026-07-27: the ack once
        # promised phone + Drive unconditionally — a receipts-law violation in waiting)
        phone = bool(POCKET and POCKET.configured())
        drive = bool(GSUITE and getattr(GSUITE, "drive_ready", lambda: False)())
        dest = ("on your phone inside a minute, with a Drive link" if phone and drive else
                "on your phone inside a minute" if phone else
                "in your Drive inside a minute" if drive else
                "in the deals folder inside a minute")
        lead = (f"Found {dclient} in your records, sir — drafting the {dkind or 'document'} now"
                if note == "records" else
                f"Drafting the {dkind or 'document'} now, sir")
        return {"answer": f"{lead} — it'll be {dest}.", "nodes": []}
    if kind == "TOOLS":
        # mail/calendar (and any tool errand) that reached the chat brain — run it on the real
        # tool line instead of letting a tool-less persona deny having access (2026-07-27)
        if not TOOLS:
            return {"answer": "The tool armory isn't loaded, sir.", "nodes": []}
        if not name:
            return {"answer": "Which errand shall I run through the tools, sir?", "nodes": []}
        res, err = tool_chat(name, sid)
        if err:
            return {"answer": f"The tool line failed me, sir ({str(err)[:120]}).", "nodes": []}
        return res
    if kind == "CALL":
        if not (CALLS and CALLS.configured()):
            return {"answer": "The phone line isn't configured yet, sir — Retell key, number and "
                              "agent under \"telephony\" in config.json.", "nodes": []}
        if not name:
            return {"answer": "Call whom, sir, and about what?", "nodes": []}
        d, code = CALLS.prepare_task(name, sid)
        if code != 200:
            return {"answer": d.get("error", "The call setup failed, sir."), "nodes": []}
        if d.get("placed"):
            # self-calls dial immediately (his own cell, his own ask) — no confirm to arm
            return {"answer": d.get("ask") or "Ringing you now, sir.", "nodes": []}
        # a BLANK ask armed the confirm silently and read as "(no answer)" — never again
        if sid and str(sid).startswith("pocket") and d.get("confirm_id") and not d.get("need_number"):
            # off the desk there is no goRoute — the pocket_call_reply catcher owns the yes
            ARMED_CALL[str(sid)] = {"cid": d["confirm_id"], "ts": time.time()}
        return {"answer": d.get("ask") or "Ready to ring them, sir — say 'do it'.",
                "nodes": [], "call_confirm": d}
    if kind == "SWAP":
        return do_swap(name)
    if kind == "LANG":
        code = set_lang(name)
        if not code:
            return {"answer": f"I don't speak {name} yet, sir — my repertoire runs to " +
                              ", ".join(lang_status()["spoken"]) + ".", "nodes": []}
        return {"answer": LANGS[code][1], "nodes": [], "lang": lang_status()}
    if kind == "TEARDOWN":
        if not TEARDOWN:
            return {"answer": "My teardown kit isn't loaded, sir.", "nodes": []}
        target, _, ask_q = (x.strip() for x in name.partition("|"))
        return teardown_dispatch(target, ask_q or (q or ""), sid)   # S29f: one dispatcher for the brain and the voice routes
    if kind == "OPENBUILD":                         # S29b: "open the notes app you just built" → its own window
        if not MISSIONS:
            return {"answer": "My mission bay isn't loaded, sir.", "nodes": []}
        b = MISSIONS.open_latest(hint=(name if name.strip().lower() != "latest" else (q or "")))
        if not b:
            return {"answer": "I haven't built anything yet, sir.", "nodes": []}
        log_episode("build", f"Opened build: {str(b.get('note') or '')[:80]}")
        return {"answer": xlate("Opening it now, sir — " + re.sub(r"\*\*", "", str(b.get("note") or "")).split(":")[0][:80] + "."), "nodes": []}
    if kind == "BUILD":                             # S29: the general builder — tested in a hidden browser, then opened
        if not MISSIONS:
            return {"answer": "My mission bay isn't loaded, sir.", "nodes": []}
        what, _, own = (x.strip() for x in name.partition("|"))
        if not what:
            return {"answer": "Build what, sir?", "nodes": []}
        mj, merr = MISSIONS.start("build", what, {"open": True, "from_teardown": own.lower().startswith("y")})
        if merr:
            return {"answer": xlate(merr), "nodes": []}
        log_episode("build", f"Build started: {what}")
        return {"answer": xlate("Building it now, sir. I'll test it in a hidden browser before I open it for you."),
                "nodes": [], "mission": {"id": mj["id"], "kind": mj["kind"], "title": mj["title"], "icon": mj["icon"], "brief": mj["brief"]}}
    if kind == "SEARCH":
        if not name:
            return {"answer": "Research what, sir?", "nodes": []}
        res, err = web_research(name, sid, max_uses=3)   # lighter cap on the tag path — /chat's client timeout is 35s
        if err:
            return {"answer": f"The wires failed me on that one, sir ({err}).", "nodes": []}
        return res
    if kind == "NODE":
        topic, _, related = (x.strip() for x in name.partition("|"))
        if not topic:
            return {"answer": "A node about what, sir?", "nodes": []}
        res, err = capture(topic, related)
        if err:
            return {"answer": f"I couldn't write that one down, sir ({err}).", "nodes": []}
        log_episode("note", "Node added: " + topic + ((" ↔ " + related) if related else ""))
        return {"answer": f"Done, sir — “{res['label']}” is live" +
                          (f" and wired to {related}." if related else " in the constellation."),
                "nodes": [], "new_node": {"label": res["label"], "text": topic, "related": related,
                                          "idx": res.get("idx"), "group": "note"}}
    if kind == "CREATE":
        parts = [x.strip() for x in name.split("|")] + [""] * 5
        ckind, cname, cwhere, cabout, crelated = parts[:5]
        if not cname:
            return {"answer": "Create it as what, sir? I need at least a name.", "nodes": []}
        res, err = create_item(ckind, cname, cwhere, cabout, crelated)
        if err:
            return {"answer": f"I couldn't build that, sir ({err}).", "nodes": []}
        log_episode("create", f"{res['kind'].capitalize()} created: {res['label']} → {res['rel']}")
        raise_card("notify", f"📁 {res['kind'].capitalize()} created — {res['label']}", res["rel"],
                   source="create", speak=False)
        return {"answer": res["say"], "nodes": [],
                "new_node": {"label": res["label"], "text": cabout or cname, "related": res["related"],
                             "rel": res["rel"], "idx": res.get("idx"), "group": res["group"],
                             "kind": res["kind"]}}
    if kind == "DIAL":
        dm = re.match(r"(humor|honesty)\s*=\s*(\d{1,3})", name, re.I)
        v = persona.set_dial(dm.group(1), dm.group(2)) if dm else None
        if v is None:
            return {"answer": "Which dial, sir — humor or honesty?", "nodes": []}
        quip, qerr = call_model([{"role": "user", "content":
            f"Your {dm.group(1).lower()} setting was just changed to {v}%. Acknowledge in ONE short "
            "line, in character, and let the new setting show in the delivery."}], jpersona(), 200)
        return {"answer": quip if not qerr and quip and quip != "(no answer)"
                else f"{dm.group(1).capitalize()} at {v} percent, sir.",
                "nodes": [], "persona": persona.status()}
    if kind == "SKIN":
        label, voice_hint = persona.set_skin(name)
        if not label:
            return {"answer": f"I don't own a '{name}' costume, sir — the wardrobe holds " +
                              ", ".join(persona.status()["skins"]) + ".", "nodes": []}
        set_voice(voice_hint or "default")          # matching voice, best-effort
        quip, qerr = call_model([{"role": "user", "content":
            "You have just put this persona on. Introduce yourself in ONE short line, fully in character."}],
            jpersona(), 200)
        return {"answer": quip if not qerr and quip and quip != "(no answer)" else f"{label} online.",
                "nodes": [], "persona": persona.status()}
    if kind == "REMIND":
        todo, _, whenp = (x.strip() for x in name.partition("|"))
        if not todo:
            return {"answer": "Remind you of what, sir?", "nodes": []}
        due, wlabel = parse_when_text(whenp or todo)
        add_task(todo, due)
        log_episode("task", "Reminder: " + todo + ((" (" + wlabel + ")") if wlabel else ""))
        if due:
            raise_card("notify", f"⏰ Reminder set — {wlabel}", todo, source="reminder")
            return {"answer": f"Reminder set for {wlabel}, sir.", "nodes": [], "reminder_set": True}
        raise_card("notify", "🗒 Added to your list", todo, source="reminder")
        return {"answer": f"On the list, sir — “{todo}”.", "nodes": [], "reminder_set": True}
    spoken, verr = set_voice(name)
    if verr:
        return {"answer": verr, "nodes": []}
    return {"answer": f"How do I sound, sir? This is {spoken}.", "nodes": [], "voice": voice_status()}
def model_status():
    return {"model": MODEL, "provider": (MODELCFG.get("provider") or "anthropic"),
            "default": MODEL == BOOT_MODEL and MODELCFG.get("base_url") == BOOT_MODELCFG.get("base_url"),
            "brains": known_brains(), "openrouter": bool(or_key())}

# ---------- voice hot-swap ("Jarvis, switch your voice to Daniel" / "use the flash engine") ----------
# Same trick as the brain bay, for the mouth: names fuzzy-match the LIVE ElevenLabs voice
# library (cached 1h). Runtime-only; resets to config.json's voice on restart.
ELCFG = CFG.get("elevenlabs") or {}
VOICE_LOCK = threading.Lock()
VOICE = {"voice_id": ELCFG.get("voice_id", ""), "model_id": ELCFG.get("model_id", "eleven_turbo_v2_5"),
         "name": "default"}
BOOT_VOICE = dict(VOICE)
EL_ENGINES = {"flash": "eleven_flash_v2_5", "fast": "eleven_flash_v2_5",
              "turbo": "eleven_turbo_v2_5", "v3": "eleven_v3", "expressive": "eleven_v3",
              "multilingual": "eleven_multilingual_v2"}
VOICE_CACHE = {"ts": 0.0, "voices": []}
def el_voices():
    key = ELCFG.get("api_key", "")
    if not key or key.startswith("PUT-"):
        return []
    if time.time() - VOICE_CACHE["ts"] < 3600 and VOICE_CACHE["voices"]:
        return VOICE_CACHE["voices"]
    try:
        req = urllib.request.Request("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key})
        with urllib.request.urlopen(req, timeout=15) as r:
            vs = json.load(r).get("voices", [])
        VOICE_CACHE["voices"] = [{"id": v.get("voice_id", ""), "name": v.get("name", ""),
                                  "category": v.get("category", "")} for v in vs if v.get("voice_id")]
        VOICE_CACHE["ts"] = time.time()
    except Exception:
        pass
    return VOICE_CACHE["voices"]
def set_voice(name):
    """Returns (spoken_name, err). Handles voice names, engine names, and 'default'."""
    n = (name or "").strip().lower().rstrip(".!?")
    if not n:
        return None, "which voice, sir?"
    if n in ("default", "usual", "normal", "yours", "jarvis"):
        with VOICE_LOCK:
            VOICE.update(BOOT_VOICE)
        return "my usual voice", None
    if n in EL_ENGINES:                                    # engine swap (flash/turbo/v3), same voice
        with VOICE_LOCK:
            VOICE["model_id"] = EL_ENGINES[n]
        return f"the {n} engine", None
    vs = el_voices()
    if not vs:
        return None, "I can't reach the voice library, sir — is the ElevenLabs key in config?"
    toks = n.split()
    best, score = None, 0
    for v in vs:
        vn = v["name"].lower()
        if vn.split(" - ")[0].strip() == n:                # exact first-name match wins outright
            best, score = v, 999; break
        s = sum(1 for t in toks if t in vn)
        if s == len(toks) and s > score:
            best, score = v, s
    if not best:
        names = ", ".join(sorted({v["name"].split(" - ")[0] for v in vs})[:12])
        return None, f"no '{name}' in the wardrobe, sir — I have {names}, among others."
    with VOICE_LOCK:
        VOICE["voice_id"] = best["id"]; VOICE["name"] = best["name"]
    return best["name"].split(" - ")[0], None
def voice_status():
    return {"name": VOICE["name"], "model_id": VOICE["model_id"],
            "default": VOICE["voice_id"] == BOOT_VOICE["voice_id"] and VOICE["model_id"] == BOOT_VOICE["model_id"],
            "voices": sorted({v["name"].split(" - ")[0] for v in el_voices()})}

# ---------- room lighting (Philips Hue; graceful no-op without a bridge) ----------
import hue
hue.init(CFG.get("hue") or {}, ROOT)

# ---------- the AI-OS layer (deterministic Mac control) + the personality engine ----------
import osctl
import persona

# ---------- V5 add-on bays (soft imports — the server boots fine without them) ----------
try:
    import missions as MISSIONS      # agentic missions: fleet / build-app / reaper / war room / announce / haters
except Exception as _e:
    MISSIONS = None
    if not isinstance(_e, ModuleNotFoundError): print("[missions] failed to load:", _e)
try:
    import tools as TOOLS            # the armory: direct MCP tool connections + discovery/install
except Exception as _e:
    TOOLS = None
    if not isinstance(_e, ModuleNotFoundError): print("[tools] failed to load:", _e)
try:
    import gsuite as GSUITE          # NATIVE Gmail + Calendar + Sheets + Drive (direct REST)
except Exception as _e:
    GSUITE = None
    if not isinstance(_e, ModuleNotFoundError): print("[gsuite] failed to load:", _e)
try:
    import deals as DEALS            # proposals/invoices/quotes → PDF → his Telegram + Drive
except Exception as _e:
    DEALS = None
    if not isinstance(_e, ModuleNotFoundError): print("[deals] failed to load:", _e)
try:
    import hands as HANDS            # permission-gated computer takeover (Claude computer-use loop)
except Exception as _e:
    HANDS = None
    if not isinstance(_e, ModuleNotFoundError): print("[hands] failed to load:", _e)
try:
    import calls as CALLS            # hands-free phone calling on your behalf (Retell AI)
except Exception as _e:
    CALLS = None
    if not isinstance(_e, ModuleNotFoundError): print("[calls] failed to load:", _e)
try:
    import pocket as POCKET          # text the brain from anywhere (Telegram, long-polled — no tunnel)
except Exception as _e:
    POCKET = None
    if not isinstance(_e, ModuleNotFoundError): print("[pocket] failed to load:", _e)
try:
    import assist as ASSIST          # second-brain organs: extraction, open loops, people, recall
except Exception as _e:
    ASSIST = None
    if not isinstance(_e, ModuleNotFoundError): print("[assist] failed to load:", _e)
try:
    import focus as FOCUS            # FOCUS SESSIONS: the accountability timer (V7 Session 19)
except Exception as _e:
    FOCUS = None
    if not isinstance(_e, ModuleNotFoundError): print("[focus] failed to load:", _e)
try:
    import reflex as REFLEX          # S25 (2026-09-21): the Jev reflex layer — 200 ms typed decisions in front of the brain
except Exception as _e:
    REFLEX = None
    if not isinstance(_e, ModuleNotFoundError): print("[reflex] failed to load:", _e)
try:
    import teardown as TEARDOWN      # S28 (2026-10-13): REA website teardowns — "Jarvis, reverse engineer igloo.inc"
except Exception as _e:
    TEARDOWN = None
    if not isinstance(_e, ModuleNotFoundError): print("[teardown] failed to load:", _e)

LAST_POLL = [0.0]                    # last time a viewer tab polled /api/inbox — pocket uses it to
                                     # decide whether the desk or the phone should voice a reminder

# ---------- presence orb: a floating Jarvis reactor on the real desktop (UDP-driven) ----------
PRESENCE_PORT = 4732
PRESENCE_PROC = [None]
PRESENCE_VIS = [False]   # what we last told the orb: shown or hidden
SHARE_VIS = [False]      # the screen-share's own claim on the orb (client show/hide posts)

def _persist_takeover_speed(tier):
    """Persist just takeover.speed to config.json (re-reads disk so runtime-only state isn't written)."""
    CFG.setdefault("takeover", {})["speed"] = tier
    try:
        path = os.path.join(ROOT, "config.json")
        disk = json.load(open(path))
        disk.setdefault("takeover", {})["speed"] = tier
        tmp = path + ".tmp"
        with open(tmp, "w") as f: json.dump(disk, f, indent=2)
        os.replace(tmp, path); _chmod600(path)
    except Exception:
        pass

def presence(cmd):
    """Fire-and-forget a command at presence.py over UDP. Only 'show' BOOTS the orb; state:/level:
    chatter while the orb is hidden or dead is DROPPED (2026-08-11: /hue_event speak forwards used
    to boot-on-any-command, so the first spoken answer after a share ended re-summoned the orb and
    stranded it on the desktop)."""
    try:
        alive = PRESENCE_PROC[0] is not None and PRESENCE_PROC[0].poll() is None
        if cmd == "show":
            if not alive:
                _spawn_presence()
            PRESENCE_VIS[0] = True
        elif cmd == "hide":
            PRESENCE_VIS[0] = False
            if not alive:
                return                    # nothing to hide — never boot an orb just to hide it
        elif not (alive and PRESENCE_VIS[0]):
            return                        # state/level for a hidden or dead orb — drop it
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(cmd.encode(), ("127.0.0.1", PRESENCE_PORT)); s.close()
    except Exception:
        pass

def _spawn_presence():
    """Launch presence.py as a direct child — the server runs in the user's GUI session, so the
    child inherits window-server access (verified). We hold the real handle in PRESENCE_PROC so
    presence() never re-spawns a live orb. A `quit` first clears any orphan from a prior run."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(b"quit", ("127.0.0.1", PRESENCE_PORT)); s.close(); time.sleep(0.3)
    except Exception:
        pass
    try:
        PRESENCE_PROC[0] = subprocess.Popen(["/usr/bin/python3", os.path.join(ROOT, "presence.py")],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.8)                 # let it bind UDP + create the window before commands arrive
    except Exception:
        pass

# ---------- facewin: the living Jarvis face pinned to the desktop while SCREEN WATCH is on ----
FACEWIN_PORT = 4733
FACEWIN_PROC = [None]
FACEWIN_VIS = [False]

def facewin(cmd):
    """Fire-and-forget at facewin.py over UDP. Only 'show' boots the overlay; a hide/passthrough
    aimed at a dead overlay is dropped (the presence() lesson: never boot just to hide)."""
    try:
        alive = FACEWIN_PROC[0] is not None and FACEWIN_PROC[0].poll() is None
        if cmd == "show":
            if not alive:
                _spawn_facewin()
                # S19b: a COLD child imports AppKit for 1-2s before binding UDP — a one-shot
                # "show" fired into that window just vanishes (worked on warm spawns only).
                # Re-send it a few times; shows are idempotent (each one just re-pins).
                def _reshow():
                    for _ in range(8):
                        time.sleep(0.9)
                        if not FACEWIN_VIS[0]:
                            return                        # a hide raced in — respect it
                        try:
                            s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            s2.sendto(b"show", ("127.0.0.1", FACEWIN_PORT)); s2.close()
                        except Exception:
                            pass
                threading.Thread(target=_reshow, daemon=True).start()
            FACEWIN_VIS[0] = True
        elif cmd == "hide":
            FACEWIN_VIS[0] = False
            if not alive:
                return
        else:                        # passthrough (timer|… updates): never boots, never flips claims
            if not alive:
                return
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(cmd.encode(), ("127.0.0.1", FACEWIN_PORT)); s.close()
    except Exception:
        pass

# WATCH and FOCUS both want the desktop face; it shows while EITHER claim stands and hides
# only when the last claim drops (a focus countdown must survive a watch-off, and vice versa).
FACEWIN_CLAIMS = {"watch": False, "focus": False}

def facewin_claim(name, on):
    if FACEWIN_CLAIMS[name] == bool(on):
        return                           # no change — never re-show (a re-show re-pins the card)
    FACEWIN_CLAIMS[name] = bool(on)
    facewin("show" if any(FACEWIN_CLAIMS.values()) else "hide")

def _spawn_facewin():
    """Direct child (GUI session → window-server access), presence.py pattern; a quit first
    clears any orphan from a prior server run — plus a pkill belt (S19i: a frozen twin card
    from a pre-hard-quit orphan appeared in the field; never again)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(b"quit", ("127.0.0.1", FACEWIN_PORT)); s.close(); time.sleep(0.2)
    except Exception:
        pass
    try:
        subprocess.run(["pkill", "-f", "facewin.py"], capture_output=True, timeout=3)
        time.sleep(0.15)
    except Exception:
        pass
    try:
        FACEWIN_PROC[0] = subprocess.Popen(["/usr/bin/python3", os.path.join(ROOT, "facewin.py")],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.8)
    except Exception:
        pass

def _presence_watchdog():
    """The orb must never outlive its owner. Closing the viewer TAB (or the browser) skips every
    in-page share-stop path — nobody is left to post 'hide' (2026-08-18 strand). The pagehide
    beacon covers the clean close; this net covers crashes: if the share's claim is standing but
    no viewer tab has polled /api/inbox in 75s (heartbeat is 30s), drop the claim and clear the
    orb. An active takeover drive keeps it — its finish releases via hands._orb_release."""
    while True:
        time.sleep(5)
        try:
            if SHARE_VIS[0] and LAST_POLL[0] and time.time() - LAST_POLL[0] > 75:
                SHARE_VIS[0] = False
                if not (HANDS and HANDS.RUN.get("active")):
                    presence("hide")
                print("[presence] share tab went silent — orb released")
        except Exception:
            pass
        try:  # same net for the WATCH face: a dead viewer tab must never strand him on the desktop
            # (only the WATCH claim drops — a running FOCUS countdown keeps the face by design:
            # the desktop timer outlives the tab; the session itself is server-side)
            if FACEWIN_CLAIMS["watch"] and LAST_POLL[0] and time.time() - LAST_POLL[0] > 75:
                facewin_claim("watch", False)
                print("[facewin] watch tab went silent — watch claim released")
        except Exception:
            pass
# ---------- multilingual mode ----------
LANG_FILE = os.path.join(ROOT, "jarvis-lang.json")
LANGS = {   # code: (English name, canned in-language confirmation line)
    "en": ("English",    "Back to the King's English, sir."),
    "es": ("Spanish",    "A sus órdenes, señor."),
    "fr": ("French",     "À votre service, monsieur."),
    "de": ("German",     "Zu Ihren Diensten, Sir."),
    "it": ("Italian",    "Al suo servizio, signore."),
    "pt": ("Portuguese", "Às suas ordens, senhor."),
    "nl": ("Dutch",      "Tot uw dienst, meneer."),
    "hi": ("Hindi",      "आपकी सेवा में, सर।"),
    "ur": ("Urdu",       "حاضر ہوں، سر۔"),
    "ar": ("Arabic",     "في خدمتك يا سيدي."),
    "ja": ("Japanese",   "かしこまりました、サー。"),
    "ko": ("Korean",     "분부대로 하겠습니다, 서."),
    "zh": ("Chinese",    "遵命，先生。"),
    "ru": ("Russian",    "К вашим услугам, сэр."),
    "tr": ("Turkish",    "Emrinizdeyim, efendim."),
    "pl": ("Polish",     "Do usług, sir."),
}
LANG_ALIAS = {"english": "en", "spanish": "es", "español": "es", "espanol": "es", "french": "fr",
              "français": "fr", "francais": "fr", "german": "de", "deutsch": "de", "italian": "it",
              "italiano": "it", "portuguese": "pt", "português": "pt", "portugues": "pt", "dutch": "nl",
              "hindi": "hi", "urdu": "ur", "arabic": "ar", "japanese": "ja", "korean": "ko",
              "chinese": "zh", "mandarin": "zh", "russian": "ru", "turkish": "tr", "polish": "pl",
              "default": "en", "usual": "en"}
LANG_LOCK = threading.Lock()
def load_lang():
    try:
        with open(LANG_FILE) as f:
            c = (json.load(f) or {}).get("code", "en")
        return c if c in LANGS else "en"
    except Exception:
        return "en"
def set_lang(name_or_code):
    key = (name_or_code or "").strip().lower()
    code = key if key in LANGS else LANG_ALIAS.get(key)
    if not code:
        return None
    with LANG_LOCK:
        try:
            with open(LANG_FILE, "w") as f:
                json.dump({"code": code}, f)
        except Exception:
            pass
    return code
def lang_status():
    c = load_lang()
    return {"code": c, "name": LANGS[c][0], "default": c == "en",
            "spoken": sorted(v[0] for v in LANGS.values())}

# CANNED-LINE TRANSLATION (2026-10-07, his report: in Spanish mode "pull up my Skool community"
# still said "I've pulled up all the information, sir…" in English). The brain already answers in
# the active language (jpersona's mandate); the desk's own fixed lines and raw note read-backs
# don't, so the viewer sends them here. One fast Haiku call per new line, then a disk cache,
# so a repeat is instant. English mode never calls this.
XLATE_FILE = os.path.join(ROOT, "jarvis-xlate.json")
XLATE_LOCK = threading.Lock()
_XLATE = {"cache": None}
def _xlate_cache():
    if _XLATE["cache"] is None:
        try:
            _XLATE["cache"] = json.load(open(XLATE_FILE))
        except Exception:
            _XLATE["cache"] = {}
    return _XLATE["cache"]
def xlate(text, code=None):
    code = code or load_lang()
    text = (text or "").strip()
    if code == "en" or code not in LANGS or not text:
        return text
    key = code + "|" + text
    with XLATE_LOCK:
        hit = _xlate_cache().get(key)
    if hit:
        return hit
    cfg = BOOT_MODELCFG
    k = (cfg.get("api_key") or "").strip()
    base = (cfg.get("base_url") or "").strip()
    if not k or k.startswith("PUT-") or (base and "api.anthropic.com" not in base):
        return text                                   # no Anthropic key → leave the line in English
    nm = LANGS[code][0]
    sysp = (f"Translate the user's text into {nm}. It is a line spoken by JARVIS, a dry British-butler AI "
            f"assistant, to the man he calls 'sir'. Keep the dry butler tone and render 'sir' with the natural "
            f"polite form in {nm}. Keep names and products (Jarvis, Skool, Claude, Sonnet, Opus, Telegram, "
            "Gmail, YouTube, Higgsfield), numbers, prices, dates, URLs and email addresses unchanged. Anything "
            "inside quotation marks is a command the user says in English: keep it in English, exactly. "
            "Output ONLY the translation. If the text is already in " + nm + ", return it unchanged.")
    body = json.dumps({"model": "claude-haiku-4-5", "max_tokens": min(4000, 300 + len(text) * 2),
                       "system": sysp, "messages": [{"role": "user", "content": text}]}).encode()
    try:
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
            "x-api-key": k, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        out = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text").strip()
    except Exception as e:
        print("[xlate]", str(e)[:120])
        return text
    if not out:
        return text
    with XLATE_LOCK:
        c = _xlate_cache()
        c[key] = out
        if len(c) > 3000:                              # keep the file small: drop the oldest entries
            for old in list(c)[:500]:
                c.pop(old, None)
        try:
            with open(XLATE_FILE, "w") as f:
                json.dump(c, f, ensure_ascii=False)
        except Exception:
            pass
    return out

def jpersona(question=""):
    """The live persona block (skin + dials + gate + gags) — replaces the static PERSONA."""
    with VOICE_LOCK:
        v3 = "v3" in (VOICE.get("model_id") or "")
    base = persona.system(question, allow_tags=v3)
    # models don't know the date — without this, "tomorrow" got computed from training data
    # (live bug 2026-07-13: calendar checked "6th of June 2025" and reported an empty day)
    base += time.strftime("\n\nCURRENT DATE-TIME: %A, %d %B %Y, %H:%M %Z (local). Compute 'today', "
                          "'tomorrow', 'next week' and every ISO date from THIS — never from memory.")
    # global anti-capitulation: the 2026-07-13 live failure — a plain-chat follow-up "I have three
    # meetings tomorrow" produced "You're right, sir — three blocks, exactly as you said" with ZERO
    # tool data. Account data may only ever come from tool results.
    base += ("\n\nLIVE-DATA HONESTY (non-negotiable): you have NO live access to email, calendar, "
             "drafts, or connected apps except through explicit tool runs whose results appear in "
             "this conversation. Never state, summarize, or AGREE about such account data without "
             "an actual tool result backing it — if the user disputes a result, tell them you'll "
             "re-check (say 'check again') rather than conceding; their memory is not a data "
             "source, and neither is yours. When a tool result IS present, read its specifics "
             "aloud — the no-recital rule covers vault notes only.")
    c = load_lang()
    if c != "en":
        nm = LANGS[c][0]
        base += (f"\n\nLANGUAGE (non-negotiable): sir has switched you to {nm}. EVERY reply — answers, "
                 f"quips, acknowledgments — must be written entirely in {nm}, keeping the same butler "
                 f"character. Control tags like [SWAP:…]/[LANG:…] themselves stay in English.")
    else:
        base += ("\n\nLANGUAGE: reply in English by default; but if sir writes to you in another "
                 "language, reply fluently in that same language.")
    base += ("\n\nHEARD, NOT TYPED: most input arrives through speech recognition, so names come "
             "misheard — 'Higgs Field' means Higgsfield, 'can va' means Canva, 'site view' means "
             "your flagship product. Match names generously against what you know of sir's tools, projects and "
             "notes; never quibble about spelling, and only ask when genuinely ambiguous.")
    return base

# ---------- duplex voice (ElevenLabs Agents custom-LLM brain on a separate, token-authed port) ----------
DUPLEX_PORT = 4722
DUPLEX_FILE = os.path.join(ROOT, "jarvis-duplex.json")
DUPLEX_LOCK = threading.Lock()
DUPLEX_NODES = {"nodes": [], "ts": 0}     # side-channel: last notes retrieved during a live session
def load_duplex():
    try:
        d = json.load(open(DUPLEX_FILE)) if os.path.exists(DUPLEX_FILE) else {}
    except Exception:
        d = {}
    if not d.get("token"):                # first boot: mint the bearer token EL must present
        d["token"] = uuid.uuid4().hex + uuid.uuid4().hex
        try:
            tmp = DUPLEX_FILE + ".tmp"
            with open(tmp, "w") as f: json.dump(d, f, indent=1)
            os.replace(tmp, DUPLEX_FILE); _chmod600(DUPLEX_FILE)
        except OSError:
            pass
    return d
def set_duplex_nodes(idxs):
    with DUPLEX_LOCK:
        DUPLEX_NODES["nodes"] = idxs[:14]
        DUPLEX_NODES["ts"] = int(time.time())
def save_duplex(d):
    try:
        tmp = DUPLEX_FILE + ".tmp"
        with open(tmp, "w") as f: json.dump(d, f, indent=1)
        os.replace(tmp, DUPLEX_FILE); _chmod600(DUPLEX_FILE)
    except OSError:
        pass

# ---------- GPT Realtime (OpenAI speech-to-speech) as a second live-voice engine ----------
# The browser talks WebRTC straight to OpenAI using a short-lived token minted here (the real
# key never reaches the page). GPT handles ears+mouth+turn-taking; an ask_jarvis TOOL routes
# every knowledge/memory/vault question back to THIS server — Claude stays the brain.
OPENAI = CFG.get("openai") or {}
def openai_key():
    k = (OPENAI.get("api_key") or "").strip()
    return k if k and not k.startswith("PUT-") else None
def realtime_session():
    key = openai_key()
    if not key:
        return None, ("GPT Realtime isn't wired yet, sir — paste an OpenAI key under \"openai\" "
                      "in config.json.")
    instructions = (PERSONA + mem_block() +
        time.strftime("Current date-time: %A, %d %B %Y, %H:%M %Z (local) — compute 'today'/'tomorrow' from this. ") +
        "You are the VOICE layer only. Speak in short, dry, witty sentences, 'sir' now and then. "
        "For ANYTHING about the user's notes, projects, memory, tasks, schedule, or anything you "
        "aren't certain of, call the ask_jarvis tool and relay its answer faithfully in your own "
        "spoken style — never invent details about the user's life. If the user disputes an answer "
        "about their email or calendar, say you'll verify from the desk — never simply agree with "
        "their version; you hold no account data of your own. No markdown, no lists. "
        "SCREEN: whenever the user asks about what's on their screen — what they're looking at, to "
        "read/describe/critique it, 'what do you see', 'look at this' — you MUST call the "
        "look_at_screen tool FIRST and answer only from the fresh screenshot it attaches. NEVER "
        "describe the screen from memory or guess; the screen changes constantly. "
        "IMPORTANT: if the user asks to switch models/brains ('try on grok', 'switch to gemini', "
        "'back to your usual brain') or to change anything about Jarvis itself, do NOT refuse — "
        "pass the request VERBATIM to ask_jarvis and relay the result; the system executes it.")
    model = OPENAI.get("realtime_model", "gpt-realtime")
    voice = OPENAI.get("realtime_voice", "cedar")
    tools = [{"type": "function", "name": "ask_jarvis",
              "description": "The user's second brain: answers anything about their notes, "
                             "projects, memory, tasks, or life. Use it liberally.",
              "parameters": {"type": "object",
                             "properties": {"question": {"type": "string"}},
                             "required": ["question"]}},
             {"type": "function", "name": "look_at_screen",
              "description": "Attaches a FRESH screenshot of the user's screen right now so you can "
                             "see what they're actually looking at. Call this every time the user "
                             "asks about their screen — never answer about the screen without it.",
              "parameters": {"type": "object", "properties": {}}}]
    # GA endpoint (client_secrets, session object) first; fall back to the legacy beta (sessions)
    attempts = [
        ("https://api.openai.com/v1/realtime/client_secrets",
         {"session": {"type": "realtime", "model": model, "instructions": instructions,
                      "audio": {"output": {"voice": voice}}, "tools": tools, "tool_choice": "auto"}},
         "https://api.openai.com/v1/realtime/calls"),
        ("https://api.openai.com/v1/realtime/sessions",
         {"model": model, "voice": voice, "instructions": instructions,
          "tools": tools, "tool_choice": "auto"},
         "https://api.openai.com/v1/realtime?model=" + model),
    ]
    last = ""
    for url, payload, sdp_url in attempts:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.load(r)
            secret = d.get("value") or ((d.get("client_secret") or {}).get("value")) or ""
            if not secret:
                last = "no token in the response"; continue
            return {"client_secret": secret, "model": model, "sdp_url": sdp_url}, None
        except urllib.error.HTTPError as e:
            last = f"{e.code}: {e.read().decode(errors='ignore')[:140]}"
            continue
        except Exception as e:
            last = str(e)[:100]; continue
    return None, f"the Realtime line refused, sir ({last})"
def duplex_providers():
    dx = load_duplex()
    providers = {"elevenlabs": bool(dx.get("agent_id")), "openai": bool(openai_key())}
    pref = (dx.get("provider") or "auto").lower()
    if pref in providers and providers[pref]:
        active = pref
    else:                                                   # auto: EL agent first, then GPT Realtime
        active = "elevenlabs" if providers["elevenlabs"] else ("openai" if providers["openai"] else "")
    return {"providers": providers, "provider": active, "preference": pref}
CLAUDE_BIN = CFG.get("claude_bin") or shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
TASKS_FILE = os.path.join(ROOT, "jarvis-tasks.json")
PROACTIVE_FILE = os.path.join(ROOT, "jarvis-proactive.json")
MEMORY_FILE = os.path.join(ROOT, "jarvis-memory.md")
AGENT_WORKSPACE = os.path.join(ROOT, "agent-workspace")
PERSONA = "You are JARVIS — the user's dry-witted, calm British AI-butler second brain. "

TASKS_LOCK = threading.Lock()
SESS_LOCK = threading.Lock()
PENDING_LOCK = threading.Lock()
PROACTIVE_LOCK = threading.Lock()
MEMORY_LOCK = threading.Lock()

# ---------- long-term memory (durable, human-readable facts about the user) ----------
def load_memory():
    try:
        with MEMORY_LOCK:
            return open(MEMORY_FILE, encoding="utf-8").read().strip()[:2600] if os.path.exists(MEMORY_FILE) else ""
    except Exception:
        return ""
def mem_block():
    m = load_memory()
    return ("\n\nWHAT YOU KNOW ABOUT THE USER (your long-term memory — use it to personalize, "
            "never recite it verbatim):\n" + m + "\n") if m else ""
def remember_me(text):
    text = (text or "").strip()
    if not text:
        return None, "nothing to remember, sir"
    try:
        with MEMORY_LOCK:
            new = not os.path.exists(MEMORY_FILE)
            with open(MEMORY_FILE, "a", encoding="utf-8") as f:
                if new:
                    f.write("# What Jarvis knows about me\n")
                f.write("- " + text.replace("\n", " ") + "\n")
    except OSError as e:
        return None, f"couldn't save that, sir ({e.__class__.__name__})"
    return {"ok": True}, None

# Structural safety for the agent's DRAFT mode: these tool-name patterns are
# physically blocked (claude --disallowedTools), so a draft run cannot send,
# post, delete, spend, OR write/shell/delegate its way around it — even though it
# may freely READ via your connected tools. Bash/Write/Edit/Task are blocked so the
# model can't fall back to a shell or a sub-agent to mutate anything; the mcp__*
# wildcards match the random per-server MCP prefixes (verified: wildcard denies are
# honored even under bypassPermissions). Override with config: "agent":{"disallow":[...]}
AGENT_DENY = (CFG.get("agent") or {}).get("disallow") or [
    "Bash", "Write", "Edit", "Task",
    "mcp__*send*", "mcp__*post*", "mcp__*reply*", "mcp__*delete*",
    "mcp__*publish*", "mcp__*deploy*", "mcp__*spend*", "mcp__*pay*", "mcp__*buy*",
]
# S23: the CONFIRMED path still never gets a shell, delegation, or money. A confirmation is about
# the one action the user saw (send / post / write) — a prompt-injected NEEDS_CONFIRMATION plus one
# nod must never become code execution on the machine.
EXEC_DENY = ["Bash", "Task", "mcp__*spend*", "mcp__*pay*", "mcp__*buy*"]
PENDING = {}   # pending_id -> {task, ts}  (confirmed-action store)

# ---------- corpus (RAG) ----------
def load_corpus():
    for cand in (os.path.join(ROOT, "viewer", "graph-data.js"), os.path.join(ROOT, "graph-data.js")):
        if os.path.exists(cand):
            m = re.search(r"const GRAPH\s*=\s*(\{.*\});", open(cand, encoding="utf-8").read(), re.S)
            if m:
                g = json.loads(m.group(1))
                # keep file id (rel path) AND _idx (== viewer's numeric node id)
                return [dict(n, _idx=i) for i, n in enumerate(g.get("nodes", [])) if n.get("p")]
    return []
CORPUS = load_corpus()

STOP = {"what", "is", "the", "a", "an", "and", "how", "much", "do", "does", "it", "to",
        "of", "my", "i", "for", "in", "on", "with", "are", "was", "that", "this", "me",
        "you", "your", "about", "tell", "give", "show", "whats", "who", "when", "where"}
# obvious chit-chat -> force conversation mode even if words happen to hit notes
# obvious chit-chat / opinions / plans / meta-about-Jarvis -> force conversation mode (no node fly),
# even when the words happen to overlap with notes ("Claude", "Opus", "engine", a product name…).
CONV_RE = re.compile(
    r"\b(joke|funny|how are you|who are you|what can you do|thank you|thanks|hello|hi there|hey jarvis|"
    r"good night|tell me about yourself|are you there|"
    r"what do you think|what'?s your (?:opinion|take|view|thought)|do you think|your thoughts|any thoughts|"
    r"thoughts\?|would you|should i\b|what would you|do you reckon|you agree|"
    r"i'?m going to|i'?m gonna|i'?m planning|i think i'?ll|i'?m about to|i'?d like to|let'?s\b|i just\b|"
    r"by the way|honestly|imagine|i feel|i'?m thinking|i reckon|"
    r"your (?:engine|model|brain|voice|opinion|name|take)|update your|upgrade your|switch you|change your "
    r"(?:engine|model|brain)|from opus|to sonnet|to gpt|to claude)\b", re.I)

def retrieve(question, k=6):
    qs = {w for w in re.findall(r"[a-z0-9]+", question.lower()) if w not in STOP and len(w) > 2}
    scored = []
    for n in CORPUS:
        lw = set(re.findall(r"[a-z0-9]+", n.get("label", "").lower()))
        bw = set(re.findall(r"[a-z0-9]+", n.get("p", "").lower()))
        s = len(qs & bw) + 8 * len(qs & lw)
        if s:
            scored.append((s, n))
    scored.sort(key=lambda x: -x[0])
    return [n for _, n in scored[:k]], (scored[0][0] if scored else 0)

if REFLEX:
    REFLEX.CTX.update(cfg=CFG, root=ROOT, retrieve=retrieve, corpus=lambda: CORPUS)   # S25: shortlist + his vocabulary + the key

def find_note(target):
    tl = target.lower().strip()
    tw = set(re.findall(r"[a-z0-9]+", tl))
    best, bs = None, 0
    for n in CORPUS:
        lw = set(re.findall(r"[a-z0-9]+", n.get("label", "").lower()))
        s = len(tw & lw) + (6 if n.get("label", "").lower() == tl else 0)
        if s > bs:
            bs, best = s, n
    return best if bs > 0 else None

# ---------- model (provider-aware: Anthropic native OR OpenAI-compatible) ----------
def call_model(messages, system, max_tokens=400):
    key = MODELCFG.get("api_key", "")
    if not key or key.startswith("PUT-"):
        return None, "model not configured — add your API key to config.json"
    base = (MODELCFG.get("base_url") or "").strip().rstrip("/")
    provider = (MODELCFG.get("provider") or "").strip().lower()
    openai_compat = bool(base) and "api.anthropic.com" not in base and provider != "anthropic"
    if openai_compat:
        url = base + "/chat/completions"
        # convert Anthropic-style multimodal content blocks (live screen frames) to OpenAI shape
        conv = []
        for m in messages:
            c = m.get("content")
            if isinstance(c, list):
                blocks = []
                for b in c:
                    if b.get("type") == "image":
                        blocks.append({"type": "image_url", "image_url": {"url":
                            "data:" + (b.get("source") or {}).get("media_type", "image/jpeg")
                            + ";base64," + (b.get("source") or {}).get("data", "")}})
                    else:
                        blocks.append({"type": "text", "text": b.get("text", "")})
                conv.append({"role": m.get("role"), "content": blocks})
            else:
                conv.append(m)
        messages = conv
    # Claude Opus 5 thinks BY DEFAULT and max_tokens caps thinking + visible text TOGETHER —
    # a tight cap truncates the answer mid-word ("…that button only spaw", live 2026-08-11)
    # or returns "(no answer)" when thinking eats the whole budget. One retry at 3x on a
    # token-limit stop covers every hot-swappable brain (anthropic stop_reason / openai
    # finish_reason both checked).
    for attempt in (0, 1):
        cap = max_tokens if attempt == 0 else max_tokens * 3
        if openai_compat:
            url = base + "/chat/completions"
            payload = {"model": MODEL, "max_tokens": cap,
                       "messages": [{"role": "system", "content": system}] + messages}
            # per-brain request quirks (config models.<name>.extra_body) — e.g. Ollama thinking
            # models need reasoning_effort:"none" or they spend the whole cap thinking silently
            payload.update(MODELCFG.get("extra_body") or {})
            body = json.dumps(payload).encode()
            headers = {"Authorization": "Bearer " + key, "content-type": "application/json"}
        else:
            url = (base + "/v1/messages") if base else "https://api.anthropic.com/v1/messages"
            body = json.dumps({"model": MODEL, "max_tokens": cap, "system": system,
                               "messages": messages}).encode()
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
            if openai_compat:
                ch = (data.get("choices") or [{}])[0]
                txt = ((ch.get("message") or {}).get("content") or "").strip()
                cut = ch.get("finish_reason") == "length"
            else:
                txt = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
                cut = data.get("stop_reason") == "max_tokens"
            if cut and attempt == 0:
                continue
            return (txt or "(no answer)"), None
        except urllib.error.HTTPError as e:
            return None, f"model {e.code}: {e.read().decode(errors='ignore')[:200]}"
        except Exception as e:
            return None, str(e)

# ---------- conversation memory ----------
SESSIONS, LASTCTX = {}, {}
def hist(sid):
    return SESSIONS.setdefault(sid or "_", [])
def add_turn(sid, role, content):
    with SESS_LOCK:
        h = hist(sid); h.append({"role": role, "content": content}); del h[:-12]

# ---------- the booked-call calendar offer: answer catcher (2026-07-28) ----------
# After a booked call, the spoken report ends with "Shall I pop it on your calendar with a
# reminder?" (calls.arm_cal_offer). His next short yes/no — desk /chat OR Telegram, both ride
# chat() — lands here BEFORE the brain. Yes = calendar event + a reminder text ~2h before;
# no = leave it; anything longer passes through untouched (the 10-min silence fallback in
# calls.py auto-adds so a booking never slips).
_CAL_YES_RE = re.compile(r"^(?:yes|yeah|yep|yup|sure|please do|add it|of course|"
                         r"absolutely|sounds good|why not|ok(?:ay)?|please)\b"
                         r"(?:[\s,!.]+(?:please|sir|do|it|that|add|set|the|a|to|my|and|both|"
                         r"calendar|reminder|too|as|well|go|ahead|jarvis))*[\s,!.]*$", re.I)
# BARE "do it" / "go ahead" deliberately absent from the LEAD: that is the dial-confirm
# vocabulary (audit 2026-07-28 night). But after an unambiguous leading yes, the tail
# tolerates them — his live "Yes, go ahead" missed the catcher entirely (2026-07-29).
_CAL_NO_RE = re.compile(r"^(?:no|nah|nope|no need|skip it|don'?t(?: bother)?|leave it|not now|"
                        r"no thanks?|no thank you)\b"
                        r"(?:[\s,!.]+(?:sir|thanks?|thank|you|need|the|calendar|reminder|it|"
                        r"leave|skip|that|jarvis))*[\s,!.]*$", re.I)

ARMED_CALL = {}                 # pocket sid -> {cid, ts}: a [CALL:] confirm armed OFF the desk

_AFFIRM_RE = re.compile(r"^(?:yes|yeah|yep|yup|sure|please do|do it|go ahead|ring (?:them|him|her)|"
                        r"call (?:them|him|her)|dial|ok(?:ay)?|of course|absolutely|please)\b"
                        r"(?:[\s,!.]+(?:please|sir|do|it|now|the|call|jarvis))*[\s,!.]*$", re.I)
_DENY_RE = re.compile(r"^(?:no|nah|nope|don'?t|cancel(?: it| the call)?|skip it|leave it|not now|"
                      r"never ?mind|stand down)\b"
                      r"(?:[\s,!.]+(?:sir|the|call|it|jarvis|thanks?))*[\s,!.]*$", re.I)

def pocket_call_reply(question, sid):
    """Telegram-armed [CALL:] confirms (audit 2026-07-28 night: there was NO affirmative path
    at all off the desk — the pocket's 'do it' fell to the tool-less brain or the calendar
    catcher). The short yes dials through the production /calls_go path; the no cancels."""
    if not (sid and str(sid).startswith("pocket") and CALLS):
        return None
    a = ARMED_CALL.get(sid)
    if not a:
        return None
    if time.time() - a["ts"] > 600:
        ARMED_CALL.pop(sid, None)
        return None
    q = (question or "").strip()
    if len(q) > 60:
        return None
    if _DENY_RE.match(q):
        ARMED_CALL.pop(sid, None)
        try:
            CALLS.PENDING.pop(a["cid"], None)
        except Exception:
            pass
        return "Very well, sir — the call is off."
    if not _AFFIRM_RE.match(q):
        return None
    ARMED_CALL.pop(sid, None)
    say, err = CALLS.go_confirm(a["cid"])
    return say or f"I couldn't get the line up, sir ({err})."

_WORDNUM = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
            "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12"}

def _worddigits(s):
    return re.sub(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
                  lambda m: _WORDNUM[m.group(1).lower()], s or "", flags=re.I)

def cal_offer_reply(question, sid=None):
    """The pending calendar offer's answer, or None when the utterance isn't one."""
    if not CALLS:
        return None
    if not getattr(CALLS, "cal_offer_pending", lambda: False)():
        # LATE-YES GRACE (live 2026-07-29: he multitasks — books the spa, runs the next
        # scenario, answers the calendar ask minutes later; the offer had expired/resolved
        # and his yes landed on a clueless brain). A short yes within 20 min of the LAST
        # offer's resolution gets an honest, useful answer instead.
        lo = getattr(CALLS, "cal_offer_last", lambda: None)()
        q0 = (question or "").strip()
        # 24h window (2026-07-29, his rule: nothing writes the calendar without his word —
        # so his word must WORK whenever he gets to it, not just for 20 minutes)
        if (lo and time.time() - (lo.get("ts") or 0) < 86400 and len(q0) <= 60
                and _CAL_YES_RE.match(q0)):
            how = lo.get("how") or ""
            if how == "expired-added":
                return ("Already handled, sir — it went on your calendar when the question "
                        "lapsed. Nothing more to do.")
            if how in ("expired-waiting", "expired-failed", "expired-unverified", "expired-unclaimed"):
                landed, spoken = CALLS.cal_offer_add(lo)
                return spoken + (" Better late than lost, sir." if landed else "")
        return None
    # a NEWER question owns the short-yes vocabulary (audit 2026-07-28 night): a live dial
    # confirm or a fresh deals details-question was, by construction, asked AFTER the offer —
    # the catcher stands down rather than steal their answer.
    try:
        if any(time.time() - (v.get("ts") or 0) < 600
               for v in getattr(CALLS, "PENDING", {}).values()):
            return None                 # a FRESH dial confirm outranks the offer; stale ones don't mute it
    except Exception:
        pass
    if any(time.time() - v.get("ts", 0) < 600 for v in ARMED_CALL.values()):
        return None
    try:
        if DEALS and any(time.time() - v.get("ts", 0) < DEALS.ASK_TTL
                         for v in DEALS.PENDING_ASK.values()):
            return None
    except Exception:
        pass
    q = (question or "").strip()
    if len(q) > 60:
        return None
    if _CAL_NO_RE.match(q):
        CALLS.cal_offer_claim()
        return "Very well, sir — I'll leave the calendar alone."
    if not _CAL_YES_RE.match(q):
        return None
    p = CALLS.cal_offer_claim()
    if not p:
        return None
    landed, spoken = CALLS.cal_offer_add(p)
    v = p.get("variables") or {}
    what = f"{v.get('party_or_service', 'the booking')} at {p.get('callee', '')}"
    due = None
    try:
        # "eight tonight" / "8 pm tomorrow" → "tonight at 8" / "tomorrow at 8pm": word-numbers
        # become digits, dotted meridiems normalize, and a leading "<time> <daypart>" reorders
        # into the shape parse_when_text reads (audit 2026-07-28 night: '8 pm tomorrow' was
        # falling to tomorrow's 9 AM default — a 7 AM reminder for an 8 PM booking)
        dtxt = _worddigits(v.get("datetime") or "")
        dtxt = re.sub(r"\b([ap])\.\s?m\.?", r"\1m", dtxt, flags=re.I)
        dtxt = re.sub(r"^\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?(?:\s*o'?clock)?)\s+"
                      r"(tonight|this evening|today|tomorrow[a-z ]*)\s*$",
                      r"\2 at \1", dtxt, flags=re.I)
        due, _lbl = parse_when_text(dtxt)
    except Exception:
        due = None
    if due and due - 7200 > time.time() + 120:
        add_task(f"reminder text: {what}, {v.get('datetime', '')}", due - 7200)
        return spoken + " I'll text you a couple of hours before."
    if due and due > time.time() + 300:
        add_task(f"reminder text: {what}, {v.get('datetime', '')}", max(time.time() + 120, due - 1800))
        return spoken + " I'll text you shortly before."
    # no parseable time → the event may still have landed (Google's own NLP), but a timed
    # reminder would be a guess — say so instead of inventing one (honest-receipts law)
    return spoken + (" I couldn't pin the time down for a reminder, so mind the clock." if landed else "")

def _umsg(question, image=None):
    """The current user turn — multimodal when a live screen frame rides along."""
    if not image:
        return {"role": "user", "content": question}
    return {"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}},
        {"type": "text", "text": question}]}


def chat(question, sid, image=None):
    pc = pocket_call_reply(question, sid)
    if pc is not None:
        return pc, [], None
    cal = cal_offer_reply(question, sid)
    if cal is not None:
        return cal, [], None
    synth = bool(re.search(r"\b(summari[sz]e|overview|across|all (my|of)|everything (about|on)|connect|big picture)\b",
                           question.lower()))
    chit = bool(CONV_RE.search(question))
    notes, top = retrieve(question, k=14 if synth else 6)
    # S25 — THE REFLEX VERDICT: before the brain sees anything, Jev reads the 40 best keyword matches
    # and answers "does the vault have this at all?" plus one noul per note. found → answer from the
    # notes Jev picked (no [N]/[C] coin-flip); absent → conversation, and the brain is TOLD the vault
    # is empty on this so it says so instead of improvising. Advisory: any error keeps today's path.
    rx = None; rx_found = False; rx_absent = False; rx_likely = []
    if REFLEX and REFLEX.enabled() and not chit and not synth and notes:
        try:
            rn, rx_likely, rx_q = REFLEX.shortlist(question, k=40)   # "side view" → "your flagship product": fuzzy label hits + corrected question
            rx = REFLEX.recall(rx_q, rn, rx_likely)
            if rx: rx["corrected"] = rx_q
        except Exception:
            rx = None
        if rx:
            REFLEX.set_last(sid, {"recall": {k: rx.get(k) for k in ("has", "ext", "probs", "keep", "verdict", "ms", "tokens", "cost", "model", "likely", "corrected")}})
            if rx["verdict"] == "found" and rx["keep"]:
                byidx = {n["_idx"]: n for n in rn}
                notes = [byidx[i] for i in rx["keep"] if i in byidx] or notes
                rx_found = True
            elif rx["verdict"] == "absent":
                notes, top = [], 0; rx_absent = True
    h = hist(sid); mem = mem_block()
    # a live screen share makes the WHOLE conversation screen-aware: the client sends a fresh
    # frame with every turn while sharing, so follow-ups never go blind (his 2026-08-11 report:
    # "I have to keep telling him over and over again that I've shared my screen")
    if image:
        mem += ("\n\nLIVE SCREEN: the user is SHARING their screen with you, and the attached image is the "
                "CURRENT frame — captured fresh for THIS message (so it stays current across follow-ups). "
                "When their message refers to what's on screen ('this', 'that', 'here', the app or page, or "
                "a follow-up about something you saw), ground your answer in the frame. Otherwise answer "
                "normally. NEVER claim you can't see their screen — the share is live. Earlier turns marked "
                "'[shared-screen frame attached]' were grounded in real frames the same way. "
                "WHILE THE SHARE IS LIVE, THE SCREEN IS THE DEFAULT SUBJECT of his instructions: work from "
                "the frame FIRST, and do NOT reach for connected tools, his vault notes, or file/project "
                "actions (no [TOOLS:]/[CREATE:]/[NODE:] tags, no launching apps) unless he EXPLICITLY names "
                "that tool, note, or action ('send an email to…', 'add this to my calendar', 'check my "
                "notes'). An explicit ask should of course use the screen's contents as its data — read the "
                "details off the frame and act on them.")
    elif any(isinstance(t.get("content"), str) and "[shared-screen frame attached]" in t["content"] for t in h):
        # the share is off now, but past screen-grounded answers are REAL memory — without this
        # note the honesty laws make the brain disown its own sightings ("MANGO was an invention
        # of mine", live e2e 2026-08-11)
        mem += ("\n\n(Screen-share context: earlier in THIS conversation the user shared their screen — turns "
                "marked '[shared-screen frame attached]' were answered from REAL frames you saw at the time. "
                "You cannot see the screen RIGHT NOW, but your recorded answers about those frames are "
                "trustworthy memory, not fabrication.)")
    qlog = question + ("\n[shared-screen frame attached]" if image else "")
    # the phone call that just happened rides EVERY branch — his "yeah, 8 pm works, go ahead
    # and book it" once hit the ambiguous branch (keyword overlap with notes) whose brain had
    # never heard of the call and asked "which venue, for how many?" (live 2026-07-29; the
    # outcome report is spoken client-side, so session history alone can never carry it)
    callnote = (CALLS.recent_call_note() if CALLS and hasattr(CALLS, "recent_call_note") else "") \
        + (FOCUS.note() if FOCUS and hasattr(FOCUS, "note") else "")   # S19j: live session state — the
                                                                       # brain must never guess about FOCUS
    # the brain is hot-swappable — tell the model which one it is so "which model are you?" lands
    ident = f"(Your current underlying model is {MODEL} — if asked which model/brain you are, that's the answer.) "
    # CONVERSATION: explicit chit-chat / opinion / plan / meta, a weak note match, or nothing retrieved →
    # just talk (WEB-ENABLED so he actually knows current things), and DON'T move the graph.
    if (chit or top < 4 or not notes) and not synth and not rx_found:
        carry = LASTCTX.get(sid or "_") if h else None
        sysp = jpersona(question) + ident + mem + ("The user is talking TO you — chatting, sharing a plan, or asking your "
               "opinion — NOT asking to look something up in their notes. Reply in 1-2 short, genuinely "
               "FUNNY, dry-witted sentences, 'sir' now and then. Don't mention their notes. Keep it quick "
               "— no caveats, no hedging; just a sharp, amusing take. ONE exception: anything about their "
               "live account data (email, calendar, meetings, drafts, app records) follows LIVE-DATA "
               "HONESTY above — offer to re-check rather than asserting or agreeing."
               + CONTROL_HINT + callnote)
        if carry:
            sysp += "\n\n(For continuity only, the last note discussed:\n" + carry + ")"
        if rx_absent:
            sysp += ("\n\nREFLEX VERDICT (verified against the vault, not a guess): the user's notes contain NOTHING on this. "
                     "If they asked about their notes or past work, say so plainly in ONE short line and offer to research it; "
                     "never improvise an answer from notes.")
        ans, err = call_model(h + [_umsg(question, image)], sysp, 1200)
        if not err:
            add_turn(sid, "user", qlog); add_turn(sid, "assistant", ans)
        return ans, [], err

    context = "\n\n".join(f"## {n['label']}\n{n['p']}" for n in notes)
    LASTCTX[sid or "_"] = context

    if rx_found:                                     # S25: Jev verified the vault has it — answer from the picked notes
        sysp = jpersona(question) + ident + mem + ("The notes below were VERIFIED by the reflex layer as containing the answer. "
               "Answer from them in ONE short witty line — they are already on the user's screen, don't recite them; "
               "address them as 'sir' now and then."
               + (" The question came from speech-to-text and a name may be misspelled; the vault says they mean: "
                  + ", ".join(rx_likely[:3]) + "." if rx_likely else "")
               + CONTROL_HINT + callnote + "\n\nNOTES:\n" + context)
        ans, err = call_model(h + [_umsg(question, image)], sysp, 1000)
        if not err:
            add_turn(sid, "user", qlog); add_turn(sid, "assistant", ans)
        return ans, ([n["_idx"] for n in notes] if not err else []), err

    if synth:                                        # broad synthesis → always light the cluster
        sysp = jpersona(question) + ident + mem + ("Synthesize ACROSS the notes below into a sharp 2-3 sentence answer with a "
               "touch of wit; address them as 'sir' occasionally." + CONTROL_HINT + callnote
               + "\n\nNOTES:\n" + context)
        ans, err = call_model(h + [_umsg(question, image)], sysp, 1600)
        if not err:
            add_turn(sid, "user", qlog); add_turn(sid, "assistant", ans)
        return ans, ([n["_idx"] for n in notes] if not err else []), err

    # AMBIGUOUS: high keyword overlap, but is it REALLY a notes question? Let the model decide, and
    # DEFAULT to conversation (no nodes) unless it tags the answer note-grounded — so a chatty line
    # that merely shares words with notes ("update your engine…") never drags the camera to a node.
    sysp = jpersona(question) + ident + mem + (
        "Below are notes that MIGHT be relevant. Decide what the user actually wants:\n"
        "• If they're genuinely asking about THEIR notes/knowledge, answer from the notes in ONE short "
        "witty line (the note is already on their screen — don't recite it), and BEGIN your reply with [N].\n"
        "• If it's conversational — an opinion, a plan, small talk, or about something not really in these "
        "notes — ignore the notes, reply naturally, and BEGIN your reply with [C].\n"
        "Output the tag first, then the reply. Address them as 'sir' now and then; if it's [C], keep it "
        "short and funny — no looking anything up." + CONTROL_HINT + callnote
        + "\n\nNotes on screen:\n" + context)
    ans, err = call_model(h + [_umsg(question, image)], sysp, 1000)
    if err:
        return ans, [], err
    use_notes = bool(re.match(r"\s*\[N\]", ans, re.I))     # default: no nodes unless explicitly [N]
    ans = re.sub(r"^\s*\[[NC]\]\s*", "", ans, flags=re.I).strip() or ans
    add_turn(sid, "user", qlog); add_turn(sid, "assistant", ans)
    return ans, ([n["_idx"] for n in notes] if use_notes else []), err

# ---------- web research (the ONLY web-enabled path — /chat stays fast & offline) ----------
# Deliberately a separate route from /chat: web search adds ~10-30s per answer, and wiring it into
# chat once made EVERY reply slow (removed 2026-06). Explicit "research/look up" requests pay the
# cost; everything else stays at ~2-3s. Uses Anthropic's server-side web_search tool, which only
# exists on the Claude API — so research always runs on the config.json Claude brain, even while
# the conversational brain is hot-swapped to grok/gpt via OpenRouter.
def web_research(question, sid=None, max_uses=5, image=None):
    """Answer a question with live web search. Returns (response dict, err).
    image: optional base64 JPEG of the user's shared screen — grounds 'research THIS' requests."""
    cfgm = CFG.get("model") or {}
    key = cfgm.get("api_key", "")
    base = (cfgm.get("base_url") or "").strip().rstrip("/")
    provider = (cfgm.get("provider") or "anthropic").strip().lower()
    if provider != "anthropic" or (base and "api.anthropic.com" not in base):
        return None, "web research runs on the Claude brain — config.json's model block isn't Anthropic"
    if not key or key.startswith("PUT-"):
        return None, "model not configured — add your API key to config.json"
    mid = cfgm.get("model", "claude-opus-4-8")
    sysp = (jpersona(question) + mem_block() +
            "The user asked you to research something online. Use the web_search tool NOW — do not "
            "answer from memory alone. Then give a tight, spoken-friendly answer: 2-4 sentences with "
            "the key facts, names and numbers, a touch of dry wit, 'sir' now and then. No URLs, no "
            "markdown, no bullet lists in the answer — sources are surfaced separately." +
            ("" if not image else
             " A screenshot of the user's CURRENT SCREEN is attached — their request refers to what is "
             "visible on it (an article, product, name, error…). FIRST read the screenshot to pin down "
             "exactly what they mean, THEN search the web for it. Open your answer by naming the thing "
             "you researched, so they know you actually read the screen."))
    ucontent = (question if not image else
                [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}},
                 {"type": "text", "text": question}])
    msgs = list(hist(sid)) + [{"role": "user", "content": ucontent}]
    body = {"model": mid, "max_tokens": 1024, "system": sysp, "messages": msgs,
            "tools": [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses}]}
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    data = {}
    try:
        for _ in range(4):        # server tool loop can pause (stop_reason=pause_turn) → resume
            req = urllib.request.Request("https://api.anthropic.com/v1/messages",
                                         data=json.dumps(body).encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=150) as r:
                data = json.load(r)
            if data.get("stop_reason") != "pause_turn":
                break
            body["messages"] = msgs + [{"role": "assistant", "content": data.get("content", [])}]
    except urllib.error.HTTPError as e:
        return None, f"research {e.code}: {e.read().decode(errors='ignore')[:200]}"
    except Exception as e:
        return None, str(e)
    txt, sources, seen = [], [], set()
    def add_src(u, t):
        if u and u not in seen:
            seen.add(u); sources.append({"url": u, "title": (t or u)[:80]})
    content = data.get("content", [])
    last_tool = max((i for i, b in enumerate(content) if b.get("type") != "text"), default=-1)
    for i, b in enumerate(content):
        bt = b.get("type")
        if bt == "text":
            if i > last_tool:                    # only speak text AFTER the last tool step —
                txt.append(b.get("text", ""))    # "Let me check…" search narration stays silent
            for c in (b.get("citations") or []):
                add_src(c.get("url"), c.get("title"))
        elif bt == "web_search_tool_result" and isinstance(b.get("content"), list):
            for res in b["content"]:             # citations aren't always populated — fall back
                if isinstance(res, dict) and res.get("type") == "web_search_result":
                    add_src(res.get("url"), res.get("title"))
    ans = " ".join(t.strip() for t in txt if t.strip()).strip()
    ans = re.sub(r"\*{1,2}([^*\n]+)\*{1,2}", r"\1", ans)     # spoken answer — de-markdown bold/italics
    ans = ans or "The internet was unusually quiet on that one, sir."
    qlog = question + ("\n[shared-screen frame attached]" if image else "")
    add_turn(sid, "user", qlog); add_turn(sid, "assistant", ans)
    log_episode("research", "Researched: " + question)
    # a persistent card in the top-right Inbox so the findings stay on screen after he's spoken
    # (speak=False — the answer is already read aloud by the caller; the card is the paper trail)
    q_short = question.strip().rstrip("?.!")
    title = "🌐 What I found — " + (q_short[:44] + "…" if len(q_short) > 44 else q_short)
    body = ans + (("  Sources: " + " · ".join(s["title"] for s in sources[:4])) if sources else "")
    raise_card("notify", title, body, source="research", speak=False)
    return {"answer": ans, "nodes": [], "sources": sources[:4]}, None

def tool_chat(question, sid=None):
    """Answer using the CONNECTED tools (Anthropic MCP connector) — the armory's fast path.
    Mirrors web_research: always the config.json Claude brain, shared conversation memory."""
    if not TOOLS:
        return None, "the tool armory isn't loaded"
    # OPERATIONAL context rides the tool brain too (2026-07-29: asked to add Mike Johnson to
    # the leads sheet 20 min after drafting his quote, it opened the sheet and asked who Mike
    # was — persona+memory alone know the business, not the morning's work)
    livectx = ((CALLS.recent_call_note() if CALLS and hasattr(CALLS, "recent_call_note") else "")
               + (DEALS.recent_note() if DEALS and hasattr(DEALS, "recent_note") else ""))
    sysp = (jpersona(question) + mem_block() + livectx +
            ("Use the live context above to FILL IN details the user references — 'add Mike to "
             "the leads sheet' means the Mike from the recent deal/call; ask only for what is "
             "genuinely absent. " if livectx.strip() else "") +
            "The user asked you to act through your CONNECTED TOOLS. "
            "SEQUENCE — follow it for EVERY request, in order: (1) identify the app the ask "
            "implies; (2) EMAIL, CALENDAR, SHEETS, DOCS, and DRIVE asks use the NATIVE "
            "gmail_*/gcal_*/gsheet_*/gdoc_*/gdrive_* tools when attached — they are the house "
            "line, instant and direct; never route them "
            "through Zapier while they are present; (3) otherwise scan the attached tool list "
            "for a directly-connected match, then "
            "the 'zapier' server's tools (it fronts thousands of apps — names look like "
            "gmail_find_email or slack_send_channel_message); (4) the moment you find a fit, CALL "
            "IT — silently, with zero narration about which route you took; (5) only if NOTHING "
            "attached fits, say: you checked the direct connections and Zapier, <the app> isn't "
            "connected there yet — they should either connect it in the tool armory or add it "
            "inside their Zapier at mcp.zapier.com (Add Apps), and you'll handle it from then on. "
            "NEVER FABRICATE: every fact you state must come from an actual tool RESULT in this "
            "conversation. If a call failed, returned nothing, or never happened, say exactly that "
            "instead — inventing emails, events, or records is the one unforgivable failure. Never "
            "role-play a tool result. "
            "EMAIL RULE: 'check my email/inbox' means the Gmail PRIMARY inbox only — constrain "
            "searches with category:primary in:inbox (never Promotions, Social, Updates, or spam) "
            "unless the user names another folder or category. "
            "RECEIPTS ON WRITES: after any write action (draft, create, post, update), claim "
            "success ONLY if the tool result confirms it — an id, link, or status. Say WHERE it "
            "landed ('the draft is sitting in your Gmail drafts now, sir') but never read raw "
            "ids aloud. If the call errored, returned nothing, or never ran, say that plainly "
            "instead — a claimed-but-unmade draft is fabrication. "
            "CALENDAR RULE: 'my calendar' means the connected account's PRIMARY calendar and "
            "that one ONLY — never list, search, or offer to sweep other calendars (Family, "
            "holidays, week numbers) unless the user names one. Never mention the account's "
            "email address or which calendar you searched in a normal answer. Agenda answers "
            "stay SHORT: the items in one breath with their times, then ONE dry witty remark "
            "about the day itself — no closing questions, no offers to dig further. "
            "DISPUTED RESULTS: an ordinary empty day is reported plainly ('nothing on the books "
            "tomorrow, sir') with no account names and no interrogating other calendars. ONLY if "
            "the user says you're wrong: re-run the tool fresh, and THEN name exactly which "
            "account/calendar/mailbox you searched (it's in the tool result) so the mismatch can "
            "be found — but NEVER simply adopt the user's version; data comes from tools, not "
            "concession. "
            "READ IT BACK: when the user asks for information (calendar, email, sheets, records, "
            "numbers), your reply MUST contain the information itself, read back conversationally "
            "with your dry commentary — for lists, read the items (up to about six). NEVER reply "
            "with 'done', 'it's on your screen', or a pointer to where the answer lives; you ARE "
            "the read-out. Never narrate mechanics — no play-by-play about date formats, tool "
            "quirks, or intermediate steps; deliver the findings only. Spoken-friendly: 2-5 "
            "sentences, 'sir' now and then. No URLs, no markdown. If a tool errors, say plainly "
            "which one and why. "
            "NAMES ARRIVE MISHEARD (speech recognition): 'Higgs Field' means the higgsfield server, "
            "'can va' means canva — match tool and server names generously before concluding "
            "anything is missing, and when asked what you can do, list the attached servers by name.")
    msgs = list(hist(sid)) + [{"role": "user", "content": question}]
    # creation-shaped errands (generate/build/write a sheet, doc, resume, report…) take many
    # tool turns — one row-append per turn exhausted the lookup-tuned cap of 6 and the run
    # ended silent ("came back empty", 2026-08-26); pure lookups keep the fast cap
    iters = 12 if re.search(r"\b(creat\w*|generat\w*|build\w*|writ\w*|draft\w*|mak\w*|fill\w*|"
                            r"populat\w*|resume|report|proposal)\b", question, re.I) else 6
    res, err = TOOLS.chat(msgs, sysp, max_iters=iters)
    if err:
        # transient API/Zapier slowness reads as a raw timeout — give him the recovery move instead
        if "timed out" in str(err).lower():
            err = ("the tool line went quiet mid-call, sir — a slow patch on the wires, not a fault "
                   "of yours. Say 'check again' and I shall have another go.")
        return None, err
    ans = re.sub(r"\*{1,2}([^*\n]+)\*{1,2}", r"\1", res["answer"]).replace("`", "")  # no markdown on voice/screen/card
    add_turn(sid, "user", question); add_turn(sid, "assistant", ans)
    log_episode("tools", "Used tools: " + question)
    if res.get("tools_used"):
        # clean title — the old one echoed the raw speech transcript (read as garbled), via-info lives here now
        raise_card("notify", "🛠 Tool run — via " + ", ".join(res["tools_used"]),
                   ans, source="tools", speak=False)
    return {"answer": ans, "nodes": [], "tools_used": res.get("tools_used", []),
            "tool_calls": res.get("tool_calls", []), "tool_errors": res.get("tool_errors", 0)}, None

# ---------- speech normalization: make text READ like a butler, not a screen reader ----------
# "$97/mo" → "$97 a month", markdown/URLs/emoji dropped, dashes become a beat. Idempotent, and
# never touches [square-bracket audio tags] (those are v3 voice directions handled downstream).
SPEAK_UNIT = {"mo": "month", "month": "month", "yr": "year", "year": "year", "wk": "week",
              "week": "week", "day": "day", "hr": "hour", "hour": "hour", "min": "minute"}
def speakable(t):
    t = str(t or "")
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    # TECHNICAL GARBAGE never gets read aloud (2026-07-27: he heard a raw JSON-RPC error and a
    # UUID spelled out from a health card). JSON blobs, UUIDs, long hex/id runs, error codes —
    # the screen keeps them; the voice replaces the lot with one humane pointer.
    had_tech = bool(re.search(r"\{\s*\"|\bjsonrpc\b|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", t, re.I))
    t = re.sub(r"\{\s*\"[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", " ", t)      # {"json": ...} payloads
    t = re.sub(r"\(\s*\{[^)]*\)", " ", t)                            # ({...}) parentheticals
    t = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "", t, flags=re.I)
    t = re.sub(r"\b[0-9a-f]{12,}\b", "", t, flags=re.I)              # long hex/id runs
    t = re.sub(r"\b(?:error\s*)?codes?\"?\s*[:=]\s*-?\d+\b", "", t, flags=re.I)
    t = re.sub(r"\bjsonrpc\b[^,.;]*", "", t, flags=re.I)
    if had_tech:
        t = re.sub(r"\s+([.,;])", r"\1", t)
        t = re.sub(r"\s{2,}", " ", t).strip()
        if not re.search(r"on (?:your|the) screen", t, re.I):
            t = (t.rstrip(".") + ". The technical detail is on your screen, sir.") if t else \
                "There's a technical error on your screen, sir."
    t = re.sub(r"https?://\S+|www\.\S+"                              # URLs are for the screen —
               r"|\b[A-Za-z0-9][\w.-]*\.(?:com|ai|io|net|org|dev|app|co|me|so|xyz|gg|page|site|design|link)/\S+",
               "", t)                                                # incl. BARE ones (canva.com/d/… read letter-by-letter otherwise)
    t = re.sub(r"[*_`#]+", "", t)                                    # markdown leftovers
    t = re.sub(r"/\s*(mo|month|yr|year|wk|week|day|hr|hour|min)s?\b",
               lambda m: " a " + SPEAK_UNIT[m.group(1).lower()], t, flags=re.I)
    t = re.sub(r"(?<=\d)\s*/\s*(user|seat|person|license|email|contact|subscriber)s?\b",
               lambda m: " per " + m.group(1).lower(), t, flags=re.I)
    t = re.sub(r"\bper\s+(mo|yr|wk|hr)\b", lambda m: "per " + SPEAK_UNIT[m.group(1).lower()], t, flags=re.I)
    t = re.sub(r"(\w)\s*/\s*(\w)", r"\1 \2", t)                     # A/B, 24/7 → spoken as a pair
    t = re.sub(r"(\d)\s*%", r"\1 percent", t)
    # symbols stumble the voice (2026-07-28: "$", "+", parentheses) — money speaks as money,
    # a leading plus is silent, digit runs read as phone numbers, parens are silent beats
    t = re.sub(r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*[kK]\b", r"\1 thousand dollars", t)
    t = re.sub(r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*[mM]\b", r"\1 million dollars", t)
    t = re.sub(r"\$\s*(\d[\d,]*(?:\.\d+)?)", r"\1 dollars", t)      # "$1,500" → "1,500 dollars"
    t = re.sub(r"€\s*(\d[\d,]*(?:\.\d+)?)", r"\1 euros", t)
    t = re.sub(r"£\s*(\d[\d,]*(?:\.\d+)?)", r"\1 pounds", t)
    t = re.sub(r"\s*&\s*", " and ", t)
    t = re.sub(r"(?<=[0-9kKmM])\s*\+(?!\d)", " plus", t)            # "10k+" → "10k plus"
    t = re.sub(r"\+(?=\s*\d[\d\s().-]{6,})", "", t)                 # "+1 510…" — a phone's plus is silent ("2+2" isn't)
    t = re.sub(r"\b1?(\d{3})(\d{3})(\d{4})\b", r"\1 \2 \3", t)      # 10/11-digit runs → phone cadence
    t = re.sub(r"(?<=\d{3})-(?=\d{4}\b)", " ", t)                   # "123-4567" — the hyphen too
    # bare parens/brackets are silent — but [sighs]/[pause] etc. are ElevenLabs v3 AUDIO TAGS
    # that persona.speech_text owns downstream; shield them from the strip (audit 2026-07-28)
    t = persona._TAG_SHIELD_RE.sub(lambda m: "\x00" + m.group(1) + "\x01", t) if persona else t
    t = re.sub(r"[()\[\]]", " ", t)
    t = t.replace("\x00", "[").replace("\x01", "]")
    t = re.sub(r"~\s*(?=[\d$€£])", "about ", t)
    t = re.sub(r"\bvs\.?(?=\s|$)", "versus", t, flags=re.I)
    t = re.sub(r"\be\.g\.,?\s*", "for example, ", t)
    t = re.sub(r"\bi\.e\.,?\s*", "that is, ", t)
    t = re.sub(r"\s+[–—]\s+|\s+--\s+", ", ", t)           # a dash is a beat, not a word
    t = re.sub(r"[•▪◦]", ",", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿⬀-⯿←-⇿]", "", t)  # emoji
    return re.sub(r"\s{2,}", " ", t).strip()

# ---------- voice (ElevenLabs) ----------
def synth_voice(text):
    el = CFG.get("elevenlabs", {})
    key = el.get("api_key", "")
    with VOICE_LOCK:                      # runtime-swappable voice + engine ("switch your voice to…")
        vid, mid = VOICE["voice_id"], VOICE["model_id"]
    if not key or key.startswith("PUT-") or not vid or vid.startswith("PUT-"):
        return None, "elevenlabs not configured"
    body = json.dumps({"text": text, "model_id": mid,
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.85}}).encode()
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}", data=body,
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read(), None
    except urllib.error.HTTPError as e:
        return None, f"tts {e.code}: {e.read().decode(errors='ignore')[:200]}"
    except Exception as e:
        return None, str(e)

# ---------- notes: capture + edit ----------
def capture(text, related=""):
    if not VAULT or not os.path.isdir(VAULT):
        return None, "vault not set in config.json"
    label = " ".join(text.split()[:8]).strip() or "Quick note"
    words = re.findall(r"[A-Za-z0-9]+", text)
    slug = ("-".join(w.lower() for w in words[:7]) or "note")[:60]
    capdir = os.path.join(VAULT, "captures")
    anchor = find_note(related) if (related or "").strip() else None
    # ALWAYS write a resolvable wikilink — build.py prunes link-free notes on rebuild
    body = f"# {label}\n\n{text}\n\nRelated: {_wikilink(anchor)}\n"
    try:
        os.makedirs(capdir, exist_ok=True)
        path, i = os.path.join(capdir, slug + ".md"), 1
        while True:                                    # open('x') so racing captures never share a file
            try:
                with open(path, "x", encoding="utf-8") as f:
                    f.write(body)
                break
            except FileExistsError:
                path = os.path.join(capdir, f"{slug}-{i}.md"); i += 1
    except OSError as e:
        return None, f"couldn't write the note, sir ({e.__class__.__name__})"
    rel = os.path.relpath(path, VAULT).replace(os.sep, "/")
    idx = persist_node(rel, label, "note", text, anchor["id"] if anchor else "wiki/INDEX.md")
    return {"label": label, "rel": rel, "idx": idx}, None

# ---------- create: real folders / projects / wiki pages, born straight into the graph ----------
# A created item is THREE things at once: a real folder/.md in the vault, a durable node appended
# to graph-data.js (+ the demo backup so seed_demo --clear can't erase real work), and a live
# CORPUS entry so "pull up X" retrieves it immediately — no rebuild, no restart.
CREATE_ROOTS = ("projects", "wiki", "brainstorm", "captures", "cadence")
GRAPH_LOCK = threading.Lock()

def _slugify(text, cap=48):
    words = re.findall(r"[A-Za-z0-9]+", text or "")
    return ("-".join(w.lower() for w in words) or "note")[:cap].strip("-")

def _group_for(rel):
    """Mirror build.py's group_aios() so a later full rebuild keeps the same look."""
    if rel.startswith("wiki/concepts/"):
        return "concept"
    if rel.startswith("wiki/skills/"):
        return "hub" if rel.count("/") == 2 else "skill"
    if rel.startswith("wiki/tools/"):
        return "tool"
    if rel.startswith("wiki/worlds/"):
        return "world"
    if rel.startswith(("wiki/", "cadence/")):
        return "core"
    return "note"                                  # projects/, brainstorm/, captures/

def _wikilink(anchor):
    """A wikilink that build.py can actually resolve: link by file STEM, alias by label."""
    if not anchor:
        return "[[INDEX]]"
    stem = os.path.splitext(os.path.basename(anchor.get("id") or ""))[0]
    label = str(anchor.get("label") or stem)
    if not stem:
        return f"[[{label}]]"
    return f"[[{stem}]]" if stem.lower() == label.lower() else f"[[{stem}|{label}]]"

def persist_node(rel, label, group, preview, anchor_id=None):
    """Append a node — plus a link to anchor_id, resolved PER FILE by node id since indices
    differ between the served file and the demo backup — to graph-data.js (and the
    .predemo.bak if present) and to the live CORPUS. Returns the served file's new index,
    or None if the served file couldn't be written."""
    p = re.sub(r"\s+", " ", (preview or "")).strip()[:700]
    with GRAPH_LOCK:
        idx = None
        for cand in (os.path.join(ROOT, "viewer", "graph-data.js"),
                     os.path.join(ROOT, "viewer", "graph-data.js.predemo.bak")):
            if not os.path.exists(cand):
                continue
            try:
                src = open(cand, encoding="utf-8").read()
                m = re.search(r"const GRAPH\s*=\s*(\{.*\});", src, re.S)
                if not m:
                    continue
                g = json.loads(m.group(1))
                nid = len(g["nodes"])
                g["nodes"].append({"id": rel, "label": label, "g": group, "p": p})
                if anchor_id:
                    a = next((i for i, n in enumerate(g["nodes"][:nid]) if n.get("id") == anchor_id), None)
                    if a is not None:              # anchor absent in this file (e.g. a demo node in the bak) → no link
                        g["links"].append({"s": nid, "t": a})
                tmp = cand + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(src[:m.start(1)] + json.dumps(g, ensure_ascii=False) + src[m.end(1):])
                os.replace(tmp, cand)
                if cand.endswith("graph-data.js"):
                    idx = nid                      # only the served file's index means anything to the viewer
            except Exception:
                continue
        if idx is not None:
            CORPUS.append({"id": rel, "label": label, "g": group, "p": p, "_idx": idx})
        return idx

def create_item(kind, name, where="", about="", related=""):
    """Create a project/folder/note/wiki page in the vault. Returns (result dict, err)."""
    if not VAULT or not os.path.isdir(VAULT):
        return None, "vault not set in config.json"
    kind = (kind or "note").strip().lower()
    if kind not in ("project", "folder", "note", "wiki"):
        kind = "note"
    name = (name or "").strip()
    if not name:
        return None, "no name"
    slug = _slugify(name)
    where = (where or "").strip().strip("/").replace("\\", "/")
    if kind == "project":
        base = "projects"                          # router rule: new work → projects/<yyyy-mm-name>/
    elif kind == "wiki":
        base = where if where.startswith("wiki") else "wiki"
    elif where:
        base = where
    else:
        base = "projects" if kind == "folder" else "captures"
    if base.split("/")[0] not in CREATE_ROOTS:
        base = "projects" if kind in ("project", "folder") else "wiki"
    vroot = os.path.normpath(VAULT)
    droot = os.path.normpath(os.path.join(VAULT, base))
    if not (droot == vroot or droot.startswith(vroot + os.sep)):
        return None, "that path escapes the vault, sir"
    anchor = find_note(related) if (related or "").strip() else None
    body = f"# {name}\n\n{about or name}\n\nRelated: {_wikilink(anchor)}\n"
    made_folder = None
    try:
        if kind in ("project", "folder"):
            dirname = (time.strftime("%Y-%m-") + slug) if kind == "project" else slug
            folder, i = os.path.join(droot, dirname), 1
            while True:                            # makedirs w/o exist_ok is the exclusivity check
                try:
                    os.makedirs(folder); break
                except FileExistsError:
                    folder = os.path.join(droot, f"{dirname}-{i}"); i += 1
            made_folder = folder
            path = os.path.join(folder, slug + ".md")
            with open(path, "x", encoding="utf-8") as f:
                f.write(body)
        else:
            os.makedirs(droot, exist_ok=True)
            path, i = os.path.join(droot, slug + ".md"), 1
            while True:                            # open('x') so two racing creates never share a file
                try:
                    with open(path, "x", encoding="utf-8") as f:
                        f.write(body)
                    break
                except FileExistsError:
                    path = os.path.join(droot, f"{slug}-{i}.md"); i += 1
    except OSError as e:
        if made_folder:                            # don't strand an empty project folder
            try: os.rmdir(made_folder)
            except OSError: pass
        return None, f"couldn't create it ({e.__class__.__name__})"
    rel = os.path.relpath(path, VAULT).replace(os.sep, "/")
    group = _group_for(rel)
    idx = persist_node(rel, name, group, about or name,
                       anchor["id"] if anchor else "wiki/INDEX.md")
    home = os.path.dirname(rel) or "the vault"
    say = (f"Done, sir — “{name}” is live in {home}" +
           (f", wired to {anchor['label']}." if anchor else "."))
    if idx is None:                                # file is real, the constellation write wasn't
        say = (f"“{name}” is on disk in {home}, sir — though the constellation ledger "
               "hiccupped; it'll take its place after the next rebuild.")
    return {"label": name, "rel": rel, "idx": idx, "group": group, "kind": kind,
            "related": anchor["label"] if anchor else "", "say": say}, None

EDIT_BLOCK = {"claude.md", "skill.md", "readme.md", "handoff.md", "config.json", "config.example.json"}
def edit_note(target, text):
    if not VAULT or not os.path.isdir(VAULT):
        return None, "vault not set"
    if not target or not text:
        return None, "need a note and some text, sir"
    n = find_note(target)
    if not n:
        return None, f"no note matching '{target}'"
    rel = n.get("id")
    vroot = os.path.normpath(VAULT)
    path = os.path.normpath(os.path.join(VAULT, rel)) if rel else None
    if not path or not (path == vroot or path.startswith(vroot + os.sep)) or not os.path.isfile(path):
        return None, "note file missing"
    # only ever append to a real markdown note — never to skills, router, or config
    if not path.lower().endswith(".md") or os.path.basename(path).lower() in EDIT_BLOCK:
        return None, "I won't edit that one, sir — it isn't a note."
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n\n{text}\n")
    except OSError as e:
        return None, f"couldn't update that note, sir ({e.__class__.__name__})"
    return {"label": n["label"], "idx": n["_idx"]}, None

# ---------- tasks (thread-safe + atomic) ----------
def load_tasks():
    try:
        return json.load(open(TASKS_FILE)) if os.path.exists(TASKS_FILE) else []
    except Exception:
        return []
def save_tasks(t):
    tmp = TASKS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(t, f)
    os.replace(tmp, TASKS_FILE)
def open_tasks():
    return [x for x in load_tasks() if not x.get("done")]
def add_task(text, due=None):
    text = (text or "").strip()
    if not text:
        return open_tasks()
    rec = {"text": text, "done": False, "ts": int(time.time())}
    if isinstance(due, (int, float)) and due > 0:      # a timed reminder, not just a list item
        rec["due"] = int(due)
        rec["reminded"] = False
    with TASKS_LOCK:
        t = load_tasks(); t.append(rec); save_tasks(t)
    return open_tasks()
def parse_when_text(t):
    """'tomorrow (at 5pm)' / 'tonight' / 'in 20 minutes' / 'at 6pm' / 'next week' / 'on friday'
    → (due_epoch_seconds, spoken_label) or (None, '')."""
    t = (t or "").lower()
    now = time.localtime(); day = 86400
    today0 = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1))
    at = re.search(r"\bat (\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", t)
    def hm(default=(9, 0)):
        if not at:
            return default
        h, mi = int(at.group(1)), int(at.group(2) or 0)
        ap = at.group(3)
        if ap == "pm" and h < 12: h += 12
        if ap == "am" and h == 12: h = 0
        if not ap and h < 8: h += 12
        return (h, mi)
    def label_at():
        return f"at {at.group(1)}{':' + at.group(2) if at.group(2) else ''}{at.group(3) or ''}" if at else ""
    if "tomorrow" in t:
        h, mi = hm((9, 0) if "morning" in t or not any(w in t for w in ("afternoon", "evening", "night")) else
                   ((14, 0) if "afternoon" in t else (19, 0)))
        return today0 + day + h * 3600 + mi * 60, ("tomorrow " + label_at()).strip()
    if "tonight" in t or "this evening" in t:
        h, mi = hm((20, 0))
        if h < 12: h += 12                     # "tonight at 8" is 20:00, never 08:00
        return today0 + h * 3600 + mi * 60, "tonight"
    if "next week" in t:
        return today0 + 7 * day + 9 * 3600, "next week"
    m = re.search(r"\bin (\d+)\s*(minutes?|mins?|hours?|hrs?|days?)\b", t)
    if m:
        n, u = int(m.group(1)), m.group(2)[0]
        return time.time() + n * (60 if u == "m" else 3600 if u == "h" else day), f"in {m.group(1)} {m.group(2)}"
    m = re.search(r"\bon (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t)
    if m:
        names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        diff = (names.index(m.group(1)) - now.tm_wday) % 7 or 7
        h, mi = hm()
        return today0 + diff * day + h * 3600 + mi * 60, (m.group(1).capitalize() + " " + label_at()).strip()
    if at:
        h, mi = hm()
        due = today0 + h * 3600 + mi * 60
        if due <= time.time():
            due += day
        return due, label_at()
    return None, ""

def mark_reminded(ts):
    with TASKS_LOCK:
        t = load_tasks()
        for x in t:
            if x.get("ts") == ts and x.get("due") and not x.get("done"):
                x["reminded"] = True
        save_tasks(t)
    return open_tasks()

_CALLME_REMIND_RE = re.compile(r"\b(?:call|ring|phone)\s+(?:me|george)\b|\bgive me a (?:call|ring)\b|"
                               r"\breminder call\b|\bcall(?:\s+me)? to remind\b", re.I)
_TEXTME_REMIND_RE = re.compile(r"\b(?:text|message|telegram)\s+(?:me|george)\b|"
                               r"\bsend me a (?:text|message|telegram)\b|\breminder text\b|"
                               r"\btext(?:\s+me)? to remind\b|\bshoot me a (?:text|message)\b", re.I)
def _reminder_route(text):
    """How a due reminder wants to be DELIVERED: 'call' rings his cell, 'text' lands on his
    Telegram (2026-07-28: text MEANS Telegram), None leaves it to the desk client."""
    if _CALLME_REMIND_RE.search(text or ""): return "call"
    if _TEXTME_REMIND_RE.search(text or ""): return "text"
    return None

def _reminder_call_loop():
    """Server-side due sweep (2026-07-28): 'give me a reminder CALL at 12:49' rings his CELL,
    'send me a reminder TEXT' lands on his Telegram — both AT the due minute, both with the
    desk tab closed. Claims the reminder atomically so the client can't double-fire."""
    while True:
        time.sleep(20)
        try:
            can_call = bool(CALLS and CALLS.configured() and CALLS.callback_number())
            can_text = bool(POCKET and POCKET.configured())
            if not (can_call or can_text):
                continue
            now = time.time()
            fire = []
            with TASKS_LOCK:
                t = load_tasks()
                for x in t:
                    if not (x.get("due") and not x.get("done") and not x.get("reminded") and x["due"] <= now):
                        continue
                    route = _reminder_route(x.get("text") or "")
                    if (route == "call" and can_call) or (route == "text" and can_text):
                        x["reminded"] = True
                        fire.append((route, x))
                if fire:
                    save_tasks(t)
            for route, x in fire:
                # each reminder delivers (or fails) on its own — one crash must never strand
                # the other claimed entries (audit 2026-07-28 night: returns were ignored and
                # a failed delivery vanished with the reminder permanently claimed)
                try:
                    raw = x.get("text") or ""
                    delivered, how = False, route
                    if route == "call":
                        purpose = _CALLME_REMIND_RE.sub("", raw).strip(" ,.-:") or "the thing you flagged"
                        cid, cerr = CALLS.call_me("a reminder",
                                                  f"You asked me to ring you about: {purpose}.", kind="alert")
                        delivered = bool(cid) and not cerr
                        if not delivered and can_text:      # the other channel is the net
                            delivered, how = bool(POCKET.push_text(f"⏰ Reminder, sir (the call "
                                                 f"didn't go through): {purpose}")), "text-fallback"
                    else:
                        purpose = _TEXTME_REMIND_RE.sub("", raw).strip(" ,.-:") or "the thing you flagged"
                        delivered = bool(POCKET.push_text(f"⏰ Reminder, sir: {purpose}"))
                        if not delivered and can_call:
                            cid, cerr = CALLS.call_me("a reminder", f"Your reminder, sir: {purpose}.",
                                                      kind="alert")
                            delivered, how = bool(cid) and not cerr, "call-fallback"
                    if delivered:
                        log_episode(route, f"reminder {how} fired: {raw[:60]}")
                    else:
                        log_episode(route, f"reminder delivery FAILED on every channel: {raw[:60]}")
                        raise_card("notify", "⏰ Reminder delivery FAILED",
                                   f"Couldn't reach you by {route}: {raw[:120]}",
                                   source="tasks", priority="high", speak=None)
                except Exception as e:
                    log_episode("tasks", f"reminder fire crashed: {str(e)[:80]}")
        except Exception:
            pass
def complete_task(i):
    if not isinstance(i, int) or isinstance(i, bool):
        return open_tasks()
    with TASKS_LOCK:
        t = load_tasks(); o = [j for j, x in enumerate(t) if not x.get("done")]
        if 0 <= i < len(o):
            t[o[i]]["done"] = True; save_tasks(t)
    return open_tasks()

# ---------- briefing ----------
def recent_captures(n=5):
    capdir = os.path.join(VAULT, "captures")
    if not os.path.isdir(capdir):
        return []
    try:
        fs = [os.path.join(capdir, f) for f in os.listdir(capdir) if f.endswith(".md")]
    except OSError:
        return []
    fs.sort(key=lambda p: -os.path.getmtime(p))
    out = []
    for p in fs[:n]:
        try:
            out.append(open(p, encoding="utf-8", errors="ignore").read().strip().replace("\n", " ")[:160])
        except OSError:
            pass
    return out
def briefing():
    tasks = open_tasks(); caps = recent_captures()
    ctx = ("OPEN TASKS:\n" + ("\n".join("- " + t["text"] for t in tasks) or "(none)") +
           "\n\nRECENT CAPTURES:\n" + ("\n".join("- " + c for c in caps) or "(none)") +
           f"\n\nThe brain holds {len(CORPUS)} notes.")
    # NATIVE tier first (2026-07-27): real calendar + primary unread off the gsuite line —
    # two direct GETs + one compose, no claude CLI dependency (which sits logged out for weeks).
    if GSUITE:
        try:
            pack = GSUITE.brief_pack() if GSUITE.connected() else None
        except Exception:
            pack = None
        if pack and not (pack.get("events_err") and pack.get("unread_err")):
            lines = []
            if not pack.get("events_err"):
                evs = pack.get("events") or []
                lines.append("CALENDAR TODAY: " + ("; ".join(
                    f"{e['title']} at {e['when']}" for e in evs[:8]) if evs else "(clear)"))
            if not pack.get("unread_err"):
                uns = pack.get("unread") or []
                lines.append("UNREAD PRIMARY MAIL: " + ("; ".join(
                    f"{m['from']} — {m['subject']}" for m in uns[:6]) if uns else "(none)"))
            out, err = call_model(
                [{"role": "user", "content": "Brief me.\n\nLIVE DAY:\n" + "\n".join(lines) + "\n\n" + ctx}],
                jpersona() + mem_block() +
                "Deliver the spoken MORNING BRIEFING from the material ONLY: lead with today's "
                "calendar, then the unread mail that genuinely matters (skip newsletters and "
                "automated noise), then open tasks and recent notes if any earn a mention. 3-5 "
                "sentences, dry butler wit, address them as 'sir', no lists, no ids, no email "
                "addresses. An empty calendar or inbox is stated plainly, never apologised for.", 400)
            if not err and out:
                return out, None
    # LIVE briefing via Claude Code connectors (read-only) — the old tier, kept as fallback.
    if claude_ready():
        prompt = (jpersona() + mem_block() + "Deliver the user's spoken MORNING BRIEFING. Using their connected tools, quietly "
                  "gather: (1) today's Google Calendar events (time + title), and (2) only the few emails from "
                  "real people that genuinely need their attention today — ignore newsletters, promotions, and "
                  "automated notifications. Then weave in their open tasks and recent notes below. Deliver a SHORT "
                  "spoken briefing of 3-5 sentences in your dry, calm, witty British-butler voice, addressing them "
                  "as 'sir': lead with the shape of the day, then what actually needs them, then a crisp close. "
                  "STRICTLY READ-ONLY — do not send, reply to, archive, or change anything. Output ONLY the spoken "
                  "briefing itself, with no preamble or bullet points.\n\n" + ctx)
        out, err = claude_read(prompt, timeout=210)
        if not err and out:
            return out, None
    # Fallback (no Claude Code / tools available): tasks + notes only, via the model API.
    sysp = jpersona() + ("Give a short spoken morning briefing (2-4 sentences) in character: summarize "
           "open tasks and recent notes with a little wit. Address them as 'sir'. OPEN by saying mail "
           "and calendar are unreachable right now, so this covers tasks and notes only — never let a "
           "notes-only briefing pass as a full one.")
    return call_model([{"role": "user", "content": "Brief me.\n\n" + ctx}], sysp, 400)

# ---------- proactive / scheduled briefings ----------
def load_proactive():
    with PROACTIVE_LOCK:
        try:
            d = json.load(open(PROACTIVE_FILE)) if os.path.exists(PROACTIVE_FILE) else {}
        except Exception:
            d = {}
    return {"enabled": bool(d.get("enabled", False)), "time": d.get("time", "08:00"),
            "last": d.get("last", "")}
def save_proactive(d):
    with PROACTIVE_LOCK:
        tmp = PROACTIVE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, PROACTIVE_FILE)
def proactive_status():
    p = load_proactive()
    now = time.localtime()
    today, cur = time.strftime("%Y-%m-%d", now), time.strftime("%H:%M", now)
    due = bool(p["enabled"] and p["last"] != today and cur >= p["time"])
    return {**p, "due": due, "now": cur}
def set_proactive(enabled, t):
    p = load_proactive()
    if enabled is not None:
        p["enabled"] = bool(enabled)
    if t and re.match(r"^\d{1,2}:\d{2}$", str(t)):
        p["time"] = str(t)
    save_proactive(p)
    return proactive_status()
def proactive_ack():
    p = load_proactive()
    p["last"] = time.strftime("%Y-%m-%d", time.localtime())
    save_proactive(p)
    return proactive_status()

# ---------- agent (Claude Code; draft-safe with structural tool denylist) ----------
def claude_ready():
    return bool(CLAUDE_BIN and os.path.isfile(CLAUDE_BIN) and os.access(CLAUDE_BIN, os.X_OK))

def claude_read(prompt, timeout=180):
    """Run Claude Code headless in READ-ONLY mode: it may use the user's connected tools to
    read/research (Gmail, Calendar, web, etc.) but is structurally blocked from sending, posting,
    deleting, spending, writing, or shelling out (same denylist as the agent's draft mode).
    Returns (text, None) or (None, error)."""
    if not claude_ready():
        return None, "claude not available"
    # anti-fabrication rider on EVERY read prompt: a dead/missing connector must be reported,
    # never papered over (user 2026-07-13: "check my email" returned invented messages)
    prompt = (prompt + "\n\nHONESTY RULE: report ONLY what your tools actually returned. If a "
              "connector (Gmail, Calendar, ...) is unavailable, unauthorized, or returns nothing, "
              "say exactly that in one plain sentence — NEVER invent messages, events, or data.")
    try:
        os.makedirs(AGENT_WORKSPACE, exist_ok=True)
    except OSError:
        pass
    cwd = AGENT_WORKSPACE if os.path.isdir(AGENT_WORKSPACE) else ROOT
    args = ([CLAUDE_BIN, "-p", "--disallowedTools"] + AGENT_DENY +
            ["--permission-mode", "bypassPermissions", prompt])
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "timed out"
    except Exception as e:
        print("[claude_read]", e)
        return None, "error"
    out = (r.stdout or "").strip()
    return (out, None) if out else (None, "no output")

def run_agent(task, execute=False):
    if not claude_ready():
        return None, "My hands aren't connected, sir — the Claude Code CLI isn't where I expected."
    try:
        os.makedirs(AGENT_WORKSPACE, exist_ok=True)
    except OSError:
        pass
    cwd = AGENT_WORKSPACE if os.path.isdir(AGENT_WORKSPACE) else ROOT
    if execute:
        prompt = ("You are JARVIS, carrying out an action the user has already CONFIRMED, using their "
                  "connected tools. Complete it, then report in 1-3 dry, witty sentences addressing them "
                  "as 'sir'. RECEIPTS: only claim the action happened if a tool's output CONFIRMS it (an "
                  "id, link, or status you actually saw) — if a tool errored or was unavailable, say "
                  "exactly that instead; a claimed-but-unmade action is fabrication."
                  + mem_block() + "\n\nTask: " + task)
        # variadic --disallowedTools is terminated by the single-value --add-dir before the prompt
        args = ([CLAUDE_BIN, "-p", "--disallowedTools"] + EXEC_DENY +
                ["--add-dir", VAULT, "--permission-mode", "bypassPermissions", prompt])
    else:
        prompt = ("You are JARVIS, the user's assistant, operating their connected tools. Read and research "
                  "freely to complete the task, then reply in 1-3 short, witty sentences addressing them as "
                  "'sir'. HONESTY: report ONLY what your tools actually returned — if a connector (Gmail, "
                  "Calendar, …) is unavailable, errors, or returns nothing, say exactly that in one plain "
                  "sentence; NEVER invent emails, events, or records. "
                  "SAFETY: this is DRAFT mode — do NOT send, post, publish, reply, delete, or spend. "
                  "If the task would do any of those, prepare the full draft, show it, and end your reply with "
                  "a final line containing exactly: NEEDS_CONFIRMATION" + mem_block() + "\n\nTask: " + task)
        # DRAFT: no --add-dir (so it can't touch vault files) + denylist; reads via MCP still work.
        # variadic --disallowedTools is terminated by the single-value --permission-mode before the prompt
        args = ([CLAUDE_BIN, "-p", "--disallowedTools"] + AGENT_DENY +
                ["--permission-mode", "bypassPermissions", prompt])
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        return None, "the agent took too long, sir — try a narrower task"
    except FileNotFoundError:
        return None, "Claude Code CLI isn't installed where I expected, sir."
    except Exception as e:
        print("[agent] error:", e)
        return None, "Something went sideways running that, sir."
    out = (r.stdout or "").strip()
    if r.returncode != 0 and not out:
        print("[agent] exit", r.returncode, (r.stderr or "")[:300])
        return None, "That didn't go through, sir — the agent hit a snag."
    if not out:
        out = "(no output, sir.)"
    needs = (not execute) and ("NEEDS_CONFIRMATION" in out)
    if needs:
        out = out.replace("NEEDS_CONFIRMATION", "").strip() or "Ready when you are, sir."
    if len(out) > 1500:
        out = out[:1500].rstrip() + "\n…(truncated, sir)"
    res = {"answer": out, "needs_confirm": needs}
    if needs:
        token = uuid.uuid4().hex[:12]
        with PENDING_LOCK:
            cut = time.time() - 300
            for k in [k for k, v in PENDING.items() if v["ts"] < cut]:
                PENDING.pop(k, None)
            PENDING[token] = {"task": task, "ts": time.time()}
        res["pending_id"] = token
    return res, None

def confirm_agent(pending_id):
    with PENDING_LOCK:
        item = PENDING.pop(pending_id or "", None)
    if not item:
        return None, "I've nothing pending to confirm, sir."
    return run_agent(item["task"], execute=True)

# ---------- pulse / watchers (proactive "anything I should know?") ----------
def pulse():
    if not claude_ready():
        return None, "I can't check just now, sir — my tools aren't connected."
    prompt = (jpersona() + mem_block() + "Do a quick PULSE CHECK for anything the user genuinely needs to know "
              "right now. Using their connected tools, glance at: important new emails from real people, "
              "imminent or just-changed calendar events, and any obvious time-sensitive item. Reply in 1-3 dry, "
              "witty sentences as 'sir' with ONLY what actually matters — if nothing is pressing, say so briefly. "
              "STRICTLY READ-ONLY: change nothing.")
    out, err = claude_read(prompt, timeout=180)
    return (out, None) if (out and not err) else (None, err or "nothing to report")

# ---------- inbox triage ----------
def inbox():
    if not claude_ready():
        return None, "I can't reach your inbox just now, sir."
    prompt = (jpersona() + mem_block() + "TRIAGE the user's email inbox QUICKLY. Using their connected mail tool, "
              "glance at only the ~10 most recent / unread emails (one search, don't open every message) and give "
              "a SHORT spoken rundown as 'sir': which 2-4 actually need them and why (a line each), and roughly how "
              "much is just noise. READ ONLY — do not send, reply, archive, or change anything. ~4 sentences, "
              "spoken aloud, no bullet symbols.")
    out, err = claude_read(prompt, timeout=200)
    return (out, None) if (out and not err) else (None, err or "no output")

# ---------- screen vision ("look at my screen") — vision over a browser-captured frame ----------
def see_image(image_b64, question, media="image/jpeg"):
    key = MODELCFG.get("api_key", "")
    if not key or key.startswith("PUT-"):
        return None, "model not configured, sir"
    if not image_b64:
        return None, "I'll need to see your screen, sir — click Share when Chrome asks."
    base = (MODELCFG.get("base_url") or "").strip().rstrip("/")
    provider = (MODELCFG.get("provider") or "").strip().lower()
    openai_compat = bool(base) and "api.anthropic.com" not in base and provider != "anthropic"
    q = (question or "").strip() or "What's on my screen? Anything I should notice?"
    sysp = (jpersona() + mem_block() + "You can SEE the user's screen (image attached). Answer in 1-3 short, dry, "
            "genuinely helpful sentences as 'sir', about what is actually visible.")
    try:
        if openai_compat:
            url = base + "/chat/completions"
            payload = {"model": MODEL, "max_tokens": 1400, "messages": [
                {"role": "system", "content": sysp},
                {"role": "user", "content": [{"type": "text", "text": q},
                    {"type": "image_url", "image_url": {"url": "data:" + media + ";base64," + image_b64}}]}]}
            payload.update(MODELCFG.get("extra_body") or {})   # same per-brain quirks as call_model
            body = json.dumps(payload).encode()
            headers = {"Authorization": "Bearer " + key, "content-type": "application/json"}
        else:
            url = (base + "/v1/messages") if base else "https://api.anthropic.com/v1/messages"
            # 1400 not 400: on a thinking-by-default brain, vision turns spend thinking tokens
            # from this same cap — 400 starved the visible answer (truncation/empty)
            body = json.dumps({"model": MODEL, "max_tokens": 1400, "system": sysp, "messages": [
                {"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media, "data": image_b64}},
                    {"type": "text", "text": q}]}]}).encode()
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=60) as r:
            data = json.load(r)
        if openai_compat:
            txt = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        else:
            txt = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        return (txt or "(no answer)"), None
    except urllib.error.HTTPError as e:
        return None, f"vision {e.code}: {e.read().decode(errors='ignore')[:160]}"
    except Exception as e:
        return None, str(e)

# ---------- guide mode ("show me how") — vision locates the element, a desktop ring points at it ----------
GUIDE_PROC = [None]
_OVERLAY_GEN = [0]
def spawn_overlay(x_pct, y_pct, label):
    """Draw the desktop ring. Prefer launchctl (spawns in the user's GUI session even when this
    server was started from a sandboxed shell); fall back to a direct child process.
    launchd agents can't read TCC-protected ~/Documents, so the script is staged in /tmp."""
    src = os.path.join(ROOT, "overlay.py")
    # S23: the stage lives in the user's own 0700 cache dir (launchd can read it — Caches isn't
    # TCC-protected) and is re-copied whenever its CONTENT differs — a planted /tmp file can't run
    cache = os.path.join(os.path.expanduser("~/Library/Caches"), "jarvis-brain")
    try:
        os.makedirs(cache, mode=0o700, exist_ok=True); os.chmod(cache, 0o700)
    except OSError:
        cache = ROOT
    staged = os.path.join(cache, "jarvis-overlay.py")
    try:
        want = open(src, "rb").read()
        if not os.path.exists(staged) or open(staged, "rb").read() != want:
            with open(staged, "wb") as f:
                f.write(want)
            os.chmod(staged, 0o600)
    except OSError:
        staged = src
    args = ["/usr/bin/python3", staged, f"{x_pct:.1f}", f"{y_pct:.1f}", label or ""]
    try:
        subprocess.run(["launchctl", "remove", "com.jarvis.overlay"], capture_output=True, timeout=5)
        r = subprocess.run(["launchctl", "submit", "-l", "com.jarvis.overlay", "--"] + args,
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            # launchctl-submitted jobs are KEPT ALIVE by launchd — without a reaper it respawns
            # the ring forever after its ~10s life. Remove the job once this ring is done,
            # unless a newer ring has taken the label in the meantime.
            _OVERLAY_GEN[0] += 1
            gen = _OVERLAY_GEN[0]
            def _reap():
                if _OVERLAY_GEN[0] == gen:
                    subprocess.run(["launchctl", "remove", "com.jarvis.overlay"],
                                   capture_output=True, timeout=5)
            t = threading.Timer(14.0, _reap)
            t.daemon = True
            t.start()
            return "launchd"
    except Exception:
        pass
    try:
        if GUIDE_PROC[0] and GUIDE_PROC[0].poll() is None:
            GUIDE_PROC[0].terminate()
        GUIDE_PROC[0] = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "direct"
    except Exception as e:
        print("[overlay]", e)
        return None
def _guide_jpeg_b64(img, max_w):
    """PIL image → downscaled JPEG b64 (soft-fails to None; PIL is optional on member boxes)."""
    try:
        import io, base64
        from PIL import Image
        im = img
        if im.size[0] > max_w:
            im = im.resize((max_w, int(im.size[1] * max_w / im.size[0])), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=82)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print("[guide] jpeg:", e)
        return None


def _native_screenshot():
    """Screenshot the MAIN display server-side. The ring is drawn on the main display, so
    locating on this exact image kills the shared-window / wrong-monitor offset entirely.
    Returns (jpeg_b64_for_vision, native_PIL_image) or (None, None) — mac-only, PIL-optional."""
    shot = "/tmp/jarvis-guide-shot.png"
    try:
        r = subprocess.run(["/usr/sbin/screencapture", "-x", "-m", shot],
                           capture_output=True, timeout=10)
        if r.returncode != 0 or not os.path.exists(shot):
            return None, None
        from PIL import Image
        img = Image.open(shot).convert("RGB")
        if img.size[0] < 200 or img.size[1] < 200:
            return None, None
        b64 = _guide_jpeg_b64(img, 1568)
        return (b64, img) if b64 else (None, None)
    except Exception as e:
        print("[guide] screenshot:", e)
        return None, None


def guide(image_b64, question):
    q = (question or "").strip() or "What should I click next?"
    # prefer the server's own capture of the MAIN display — it always matches the surface
    # the ring draws on (a shared window/second-monitor frame does not); client frame = fallback
    src_b64, native = _native_screenshot()
    if not src_b64:
        src_b64 = (image_b64 or "").strip() or None
    if not src_b64:
        return None, "I'll need to see your screen first, sir — click the 🖥 and share it."
    prompt = ("The user is sharing their screen and asks: \"" + q + "\". Find the SINGLE most relevant "
              "clickable UI element for that. Measure its position carefully against the full image. "
              "Reply with ONLY a JSON object, no other text: "
              '{"x_pct": <0-100 horizontal center of the element as % of image width>, '
              '"y_pct": <0-100 vertical center as % of image height>, '
              '"label": "<2-4 word element name>", '
              '"instruction": "<ONE short spoken sentence telling them what to do, dry British butler, address them as sir>"}')
    raw, err = see_image(src_b64, prompt)
    if err:
        return None, err
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None, "I couldn't pin it down on screen, sir."
    try:
        d = json.loads(m.group(0))
        x, y = float(d["x_pct"]), float(d["y_pct"])
        label = str(d.get("label", ""))[:40]
        instr = str(d.get("instruction", "There, sir."))[:300]
    except Exception:
        return None, "I couldn't pin it down on screen, sir."
    # pass 2: crop the NATIVE shot around the first guess and re-locate precisely (zoomed
    # vision is far more accurate than one pass over a downscaled full screen); any failure
    # here silently keeps the pass-1 coordinates
    if native is not None:
        try:
            W, H = native.size
            cw, ch = int(W * 0.34), int(H * 0.34)
            cx0 = max(0, min(W - cw, int(W * x / 100.0) - cw // 2))
            cy0 = max(0, min(H - ch, int(H * y / 100.0) - ch // 2))
            crop = native.crop((cx0, cy0, cx0 + cw, cy0 + ch))
            crop_b64 = _guide_jpeg_b64(crop, 1400)
            if crop_b64:
                p2 = ("Zoomed-in region of the user's screen. They asked: \"" + q + "\". Find the SINGLE "
                      "exact clickable control for that. Reply with ONLY JSON, no other text: "
                      '{"x_pct": <0-100 center in THIS image>, "y_pct": <0-100>, "found": true|false}')
                raw2, err2 = see_image(crop_b64, p2)
                if not err2:
                    m2 = re.search(r"\{.*\}", raw2, re.S)
                    if m2:
                        d2 = json.loads(m2.group(0))
                        if d2.get("found", True):
                            x = (cx0 + cw * float(d2["x_pct"]) / 100.0) * 100.0 / W
                            y = (cy0 + ch * float(d2["y_pct"]) / 100.0) * 100.0 / H
        except Exception as e:
            print("[guide] refine:", e)
    # draw the ring on the REAL desktop via the overlay helper (pyobjc); dies on its own
    spawn_overlay(x, y, label)
    log_episode("guide", f"Pointed at: {label} — {q}")
    return {"answer": instr, "x_pct": x, "y_pct": y, "label": label}, None


# ---------- AI-OS housekeeping: Downloads janitor + screenshot renamer (draft → "do it") ----------
PENDING_OS = {}   # token -> {"kind": "organize"|"shots", "moves": [(src, dst)], "ts"}
def org_plan(dirname):
    name = (dirname or "Downloads").strip("/ ")
    if not name or ".." in name or "/" in name or "\\" in name or name.startswith("."):
        return None, "That folder is off limits, sir."           # S23: no traversal, no hidden dirs (.ssh)
    base = os.path.expanduser("~/" + name)
    if not os.path.isdir(base):
        return None, f"I can't find {os.path.basename(base)}, sir."
    entries = []
    for e in os.scandir(base):
        if e.is_file() and not e.name.startswith("."):
            st = e.stat()
            entries.append({"name": e.name, "kb": st.st_size // 1024,
                            "age": int((time.time() - st.st_mtime) // 86400)})
    entries = entries[:80]
    if not entries:
        return None, "That folder is already immaculate, sir."
    prompt = ("Organize these files into a few sensible subfolders (PDFs, Images, Installers, "
              "Archives, Video, Docs... pick what fits THIS list). Reply ONLY with JSON: "
              '{"plan": [{"file": "<exact name>", "folder": "<subfolder>"}], '
              '"summary": "<ONE spoken sentence, dry butler, describing the cleanup>"} '
              "Plan at most 50 files (the most obviously misplaced ones). Leave out files that should stay where they are.\n\nFILES:\n" +
              "\n".join(f"- {x['name']} ({x['kb']}KB, {x['age']}d old)" for x in entries))
    raw, err = call_model([{"role": "user", "content": prompt}], jpersona(), 4000)
    if err:
        return None, "The planning brain hiccuped, sir."
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None, "I couldn't draft a sensible plan, sir."
    try:
        d = json.loads(m.group(0))
        names = {x["name"] for x in entries}
        moves = []
        for it in d.get("plan", []):
            fn = it.get("file", "")
            fold = re.sub(r"[^A-Za-z0-9 _-]", "", it.get("folder", "")).strip()
            if fn in names and fold:
                moves.append((os.path.join(base, fn), os.path.join(base, fold, fn)))
        if not moves:
            return None, "Nothing worth moving, sir."
    except Exception:
        return None, "I couldn't draft a sensible plan, sir."
    token = uuid.uuid4().hex[:12]
    with PENDING_LOCK:
        PENDING_OS[token] = {"kind": "organize", "moves": moves, "ts": time.time()}
    summary = (d.get("summary") or "").strip() or f"I can tidy {len(moves)} files into folders."
    return {"answer": summary + f" {len(moves)} files would move — say \"do it\", sir.",
            "needs_confirm": True, "pending_id": token, "kind": "os"}, None

def shots_plan():
    base = os.path.expanduser("~/Desktop")
    try:
        shots = sorted((e for e in os.scandir(base) if e.is_file() and
                        re.match(r"(Screenshot|Screen Shot).*\.(png|jpg|jpeg)$", e.name, re.I)),
                       key=lambda e: -e.stat().st_mtime)[:8]
    except OSError:
        shots = []
    if not shots:
        return None, "No stray screenshots on the Desktop, sir."
    import base64 as _b64
    moves = []
    for e in shots:
        try:
            data = _b64.b64encode(open(e.path, "rb").read()).decode()
        except OSError:
            continue
        media = "image/png" if e.name.lower().endswith("png") else "image/jpeg"
        nm, err = see_image(data, "Name this screenshot in 3-6 lowercase hyphenated words based on "
                            "its content. Reply with ONLY the filename base, no extension.", media=media)
        if err or not nm:
            continue
        slug = re.sub(r"[^a-z0-9-]", "", nm.strip().lower().replace(" ", "-"))[:60] or "screenshot"
        ext = os.path.splitext(e.name)[1]
        dst = os.path.join(base, slug + ext); i = 1
        while os.path.exists(dst) or any(d == dst for _, d in moves):
            dst = os.path.join(base, f"{slug}-{i}{ext}"); i += 1
        moves.append((e.path, dst))
    if not moves:
        return None, "I couldn't read those screenshots, sir."
    token = uuid.uuid4().hex[:12]
    with PENDING_LOCK:
        PENDING_OS[token] = {"kind": "shots", "moves": moves, "ts": time.time()}
    sample = "; ".join(os.path.basename(s) + " -> " + os.path.basename(d) for s, d in moves[:3])
    return {"answer": f"{len(moves)} screenshots named by their content, sir — e.g. {sample}. "
                      "Say \"do it\" and I'll rename them.",
            "needs_confirm": True, "pending_id": token, "kind": "os"}, None

def os_confirm(token):
    with PENDING_LOCK:
        for k in [k for k, v in PENDING_OS.items() if v["ts"] < time.time() - 600]:
            PENDING_OS.pop(k, None)
        item = PENDING_OS.pop(token or "", None)
    if not item:
        return None, "Nothing pending on the housekeeping front, sir."
    home = os.path.expanduser("~")
    done = 0
    for src_p, dst_p in item["moves"]:
        try:
            if not (os.path.abspath(src_p).startswith(home) and os.path.abspath(dst_p).startswith(home)):
                continue
            os.makedirs(os.path.dirname(dst_p), exist_ok=True)
            if os.path.exists(src_p) and not os.path.exists(dst_p):
                shutil.move(src_p, dst_p); done += 1
        except OSError:
            pass
    verb = "tidied into place" if item["kind"] == "organize" else "renamed"
    log_episode("agent", f"Housekeeping: {done} files {verb}")
    return {"answer": f"Done, sir — {done} files {verb}."}, None

# ---------- telephony (Jarvis places a real phone call; needs Retell/Vapi keys) ----------
def place_call(task, to_override=None):
    tel = CFG.get("telephony") or {}
    prov = (tel.get("provider") or "").strip().lower()
    key = tel.get("api_key", "")
    if not prov or not key or key.startswith("PUT-"):
        return None, ("I haven't a phone line yet, sir — add a Retell or Vapi key under \"telephony\" in "
                      "config.json (provider, api_key, the assistant/agent and a destination number) and I'll dial.")
    # destination: an explicit per-call number wins, else the default in config.
    to = (to_override or tel.get("to") or "").strip()
    if not to:
        return None, ("I've no number to ring, sir — say the number, or set a default \"to\" under telephony "
                      "in config.json.")
    if not re.match(r"^\+?[0-9][0-9 ().-]{6,}$", to):
        return None, f"that doesn't look like a phone number, sir: {to!r} — use E.164 like +15551234567."
    to = "+" + re.sub(r"[^0-9]", "", to) if not to.startswith("+") else to
    try:
        if prov == "vapi":
            body = json.dumps({"assistantId": tel.get("assistant_id"), "phoneNumberId": tel.get("phone_number_id"),
                               "customer": {"number": to},
                               "assistantOverrides": {"variableValues": {"task": task}}}).encode()
            req = urllib.request.Request("https://api.vapi.ai/call", data=body,
                headers={"Authorization": "Bearer " + key, "content-type": "application/json"})
        elif prov == "retell":
            frm = (tel.get("from") or "").strip()
            agent = (tel.get("agent_id") or "").strip()
            if not frm or not agent:
                return None, ("my phone setup's incomplete, sir — Retell needs both a \"from\" number and an "
                              "\"agent_id\" under telephony in config.json.")
            payload = {"from_number": frm, "to_number": to,
                       "override_agent_id": agent,
                       "retell_llm_dynamic_variables": {"task": task}}
            req = urllib.request.Request("https://api.retellai.com/v2/create-phone-call",
                data=json.dumps(payload).encode(),
                headers={"Authorization": "Bearer " + key, "content-type": "application/json"})
        else:
            return None, f"I don't recognise the '{prov}' phone provider, sir."
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        detail = ""
        try: detail = e.read().decode(errors="ignore")[:180]
        except Exception: pass
        print("[call]", e.code, detail)
        return None, (f"the call didn't connect, sir ({e.code}) — {detail}".strip()
                      if detail else f"the call didn't connect, sir ({e.code}).")
    except Exception as e:
        print("[call]", e)
        return None, "the call didn't go through, sir — the line wouldn't open."
    cid = (resp or {}).get("call_id") or (resp or {}).get("id") or ""
    st = (resp or {}).get("call_status") or ""
    msg = f"Dialing {to} now, sir — the line's ringing."
    if cid:
        msg += f" (call {cid[:14]})"
    return {"answer": msg, "call_id": cid, "call_status": st, "to": to}, None

# ---------- time machine (episodic memory: what happened, and when) ----------
EPISODES_FILE = os.path.join(ROOT, "jarvis-episodes.jsonl")
EP_LOCK = threading.Lock()
def log_episode(kind, text, nodes=None):
    """Append one timestamped episode. Called from /chat, /remember, /agent, /see.
    PROBES NEVER LAND (2026-07-29: preflight's chat probe and verification curls were logged
    as his day's work — the hotline then recited 'preflight: reply with one short word' as
    what he did today). Anything self-identifying as a probe stays out of the Time Machine."""
    if re.match(r"\s*(?:preflight|probe)\b", (text or ""), re.I):
        return
    try:
        rec = {"ts": int(time.time()), "kind": kind, "text": (text or "")[:400],
               "nodes": [int(n) for n in (nodes or []) if isinstance(n, (int, float))][:12]}
        with EP_LOCK:
            with open(EPISODES_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
    except Exception:
        pass
def load_episodes(limit=5000):
    if not os.path.exists(EPISODES_FILE):
        return []
    out = []
    try:
        with open(EPISODES_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try: out.append(json.loads(line))
                    except Exception: pass
    except Exception:
        return []
    return out[-limit:]

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
def parse_when(q):
    """Map a date phrase to (start_ts, end_ts, label), or None if it isn't a date query."""
    ql = q.lower(); now = time.localtime(); day = 86400
    today0 = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1))
    span = lambda d0, label: (d0, d0 + day, label)
    if re.search(r"\bthis morning\b", ql): return (today0, today0 + 12 * 3600, "this morning")
    if re.search(r"\btoday\b", ql): return span(today0, "today")
    if re.search(r"\byesterday\b", ql): return span(today0 - day, "yesterday")
    m = re.search(r"\b(\d+)\s+days?\s+ago\b", ql)
    if m: return span(today0 - int(m.group(1)) * day, m.group(0))
    if re.search(r"\blast week\b", ql):
        start = today0 - (now.tm_wday + 7) * day; return (start, start + 7 * day, "last week")
    if re.search(r"\bthis week\b", ql):
        start = today0 - now.tm_wday * day; return (start, start + 7 * day, "this week")
    m = re.search(r"\b(last\s+)?(%s)\b" % "|".join(DAYS), ql)
    if m:
        back = (now.tm_wday - DAYS.index(m.group(2))) % 7
        if back == 0 or m.group(1): back = back or 7
        return span(today0 - back * day, m.group(0))
    m = re.search(r"\b(%s)[a-z]*\s+(\d{1,2})\b" % "|".join(MONTHS), ql)
    if m:
        try:
            d0 = time.mktime((now.tm_year, MONTHS.index(m.group(1)) + 1, int(m.group(2)), 0, 0, 0, 0, 0, -1))
            return span(d0, m.group(0))
        except Exception: pass
    return None

def recall(query):
    eps = load_episodes()
    if not eps:
        return {"answer": "I've nothing logged yet, sir — we've no history for me to rewind to.", "nodes": []}, None
    when = parse_when(query)
    if when:
        s, e, label = when
        hits = [x for x in eps if s <= x.get("ts", 0) < e]; scope = "on " + label
    else:
        qs = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in STOP and len(w) > 2}
        hits = [x for x in eps if qs & set(re.findall(r"[a-z0-9]+", x.get("text", "").lower()))]
        scope = "about that"
    if not hits:
        return {"answer": f"I find nothing {scope}, sir.", "nodes": []}, None
    nodes = []
    for x in hits[-8:]:
        nodes += x.get("nodes", [])
    nodes = list(dict.fromkeys(nodes))[:14]
    lines = [f"[{time.strftime('%a %b %d %I:%M%p', time.localtime(x.get('ts',0)))}] ({x.get('kind')}) {x.get('text','')}"
             for x in hits[-12:]]
    sysp = jpersona(query) + (f"The user asked you to recall what happened {scope}. Below are the real logged episodes "
            "(oldest first). Give a SHORT spoken recap (2-3 sentences) in your dry butler voice, addressing them as "
            "'sir', grounded ONLY in these episodes; if they asked when something first happened, name the date.")
    ans, err = call_model([{"role": "user", "content": "Episodes:\n" + "\n".join(lines)}], sysp, 300)
    if err or not ans:
        ans = f"Here's what I have {scope}, sir: " + "; ".join(x.get("text", "")[:60] for x in hits[-4:])
    return {"answer": ans, "nodes": nodes}, None

# ---------- agent inbox + smart-interrupt governor ----------
# Every background daemon (pre-flight, breakout radar, anomaly watch, living graph…) raises a
# typed CARD here instead of speaking directly. The card ALWAYS lands in the inbox; the governor
# (should_speak) decides only whether it interrupts with VOICE right now.
INBOX_FILE = os.path.join(ROOT, "jarvis-inbox.json")
DND_FILE = os.path.join(ROOT, "jarvis-dnd.json")
INBOX_LOCK = threading.Lock()
DND_LOCK = threading.Lock()

def load_inbox():
    try:
        return json.load(open(INBOX_FILE)) if os.path.exists(INBOX_FILE) else []
    except Exception:
        return []
def save_inbox(cards):
    tmp = INBOX_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cards[-200:], f)          # cap stored history
    os.replace(tmp, INBOX_FILE)
def inbox_open():
    return [c for c in load_inbox() if c.get("status") not in ("dismissed", "done")][-40:][::-1]

def load_dnd():
    with DND_LOCK:
        try:
            d = json.load(open(DND_FILE)) if os.path.exists(DND_FILE) else {}
        except Exception:
            d = {}
    return {"mute_until": d.get("mute_until", 0), "quiet_from": d.get("quiet_from", "22:00"),
            "quiet_to": d.get("quiet_to", "07:00"), "focus": bool(d.get("focus", False)),
            "rules": d.get("rules", {"money": "always"})}
def save_dnd(d):
    with DND_LOCK:
        tmp = DND_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, DND_FILE)
def set_dnd(focus=None, minutes=None, rule=None):
    d = load_dnd()
    if focus is not None:
        d["focus"] = bool(focus)
        if not focus:
            d["mute_until"] = 0
    if minutes:
        d["mute_until"] = int(time.time() + float(minutes) * 60)
    if rule:
        d.setdefault("rules", {}).update(rule)
    save_dnd(d)
    return d

def _in_quiet(now, frm, to):
    try:
        cur = now.tm_hour * 60 + now.tm_min
        fh, fm = map(int, frm.split(":")); th, tm = map(int, to.split(":"))
        a, b = fh * 60 + fm, th * 60 + tm
        return (cur >= a or cur < b) if a > b else (a <= cur < b)   # window may cross midnight
    except Exception:
        return False
MONEY_RE = re.compile(r"\b(sale|sold|payment|invoice|revenue|stripe|refund|paid|\$\d|charge)\b")   # the pre-S25c money rule (shadow baseline)
def should_speak(card):
    """Smart-Interrupt Governor — should this card break in with VOICE right now? It lands in the
    inbox either way; this gates only the spoken interruption (alert fatigue is the real problem).
    S25c: the LADDER lives in reflex.gov_ladder (money-always → focus/DND → quiet hours → priority). Today the
    money REGEX + priority feed it (`old`). With the reflex bay in SHADOW mode Jev scores the same card in a
    daemon thread and the log shows old-vs-gov; in LIVE mode Jev's money noul + situational score feed the
    ladder instead (deadline 0.8 s, any error → `old`). GOVERNOR_MODE / gates are named constants in reflex.py."""
    pr = (card.get("priority") or "normal").lower()
    d = load_dnd(); d["quiet"] = _in_quiet(time.localtime(), d["quiet_from"], d["quiet_to"])
    blob = (card.get("title", "") + " " + card.get("body", "")).lower()
    money = bool(MONEY_RE.search(blob))
    if REFLEX and hasattr(REFLEX, "gov_ladder"):
        old = REFLEX.gov_ladder(pr, d, money, None)
    else:
        old = (True if (pr == "high" and money and d.get("rules", {}).get("money") == "always") else
               (pr == "high") if (d["focus"] or time.time() < (d.get("mute_until") or 0) or d["quiet"]) else pr in ("normal", "high"))
    mode = getattr(REFLEX, "GOVERNOR_MODE", "off") if REFLEX else "off"
    if REFLEX and mode != "off" and REFLEX.enabled():
        try:
            if mode == "live":
                g = REFLEX.govern(card, d, old)               # within the deadline or None → the old verdict stands
                if g is not None: return bool(g["speak"])
            else:
                threading.Thread(target=REFLEX.govern, args=(dict(card), d, old), daemon=True).start()   # shadow: free on the raising path
        except Exception:
            pass
    return old

# ---------- DEMO BAY: staged urgent events (for filming; rides the REAL proactivity path) ----------
# "Jarvis, stage an urgent call in two minutes" → a Timer raises a HIGH-priority card exactly as a real
# event would → the desk card appears, the pocket pushes it to Telegram, and calls.card_hook rings his
# cell with the alert script reading the headline + notes. Nothing here is a special phone path — what
# the camera sees is the product. Scenario text is STAGED and says nothing about actions Jarvis took.
DEMO_SCENARIOS = {
    "signed":  {"source": "gmail",    "title": "Dana Whitfield just signed the proposal",
                "body": ("The Summit and Sons agreement came back signed a few minutes ago, and the "
                         "3,400 dollar deposit is being wired today. She's asking for a kickoff call "
                         "Monday at 10. Say the word and it goes on the calendar.")},
    "double":  {"source": "calendar", "title": "You've been double-booked at 3 this afternoon",
                "body": ("The dentist and the Summit and Sons kickoff both landed at 3. The dentist's office "
                         "can take you at 4:30 instead; their receptionist confirmed it by email ten minutes "
                         "ago. Shall I move the dentist?")},
    "payment": {"source": "deals",    "title": "A payment of 4,250 dollars just landed",
                "body": ("Invoice 2026-001 to Mike Johnson was paid in full a few minutes ago through "
                         "Stripe. That clears the pipeline for the month, nothing outstanding. Shall I send "
                         "him a thank-you?")},
    "message": {"source": "desk",     "title": "A caller left a message on your line",
                "body": ("A Mr. Alvarez rang about the Elm Street move. He needs the quote by end of day and "
                         "asked for a call back on 555-0142. He sounded keen, and he mentioned a neighbor "
                         "who's moving next month too.")},
}

def demo_urgent(p):
    """Stage one DEMO_SCENARIOS event `delay_s` seconds from now. Returns (payload, http_code).
    dry=1 validates only (preflight). Arms the standing urgent line and clears its 10-minute
    cooldown first, so a staged event can never fall silent on camera."""
    key = str(p.get("scenario") or "signed").strip().lower()
    if key not in DEMO_SCENARIOS:
        return {"error": "unknown scenario", "scenarios": sorted(DEMO_SCENARIOS)}, 400
    try:
        delay = float(90 if p.get("delay_s") is None else p.get("delay_s"))
    except (TypeError, ValueError):
        return {"error": "bad delay"}, 400
    delay = max(0.0, min(1800.0, delay))
    sc = DEMO_SCENARIOS[key]
    if p.get("dry"):
        return {"ok": True, "dry": True, "scenario": key, "title": sc["title"], "delay_s": delay}, 200
    if not (CALLS and CALLS.configured() and CALLS.callback_number()):
        return {"error": "The phone line isn't set up yet, sir — telephony plus your callback number first."}, 400
    try:
        CALLS.RING["urgent"] = True; CALLS.RING["last_ring"] = 0; CALLS._ring_save()
    except Exception:
        pass
    def fire():
        # his call 2026-09-24 (filming): the staged event ONLY rings his phone — no desk card, no desk
        # voice, no Telegram push while he's on the call. The desk confirms AFTER the call (the executor).
        try:
            cid, cerr = CALLS.call_me(sc["title"], sc["body"])
            if cerr:
                print("[demo] staged call failed:", cerr)
            log_episode("demo", f"Staged urgent call placed: {sc['title']}")
        except Exception as e:
            print("[demo] staged event failed:", e)
    t = threading.Timer(delay, fire); t.daemon = True; t.start()
    if delay < 3:
        when = "right now"
    elif delay < 45:
        when = f"in {int(delay)} seconds"
    else:
        m = max(1, int(round(delay / 60))); when = f"in about {m} minute{'s' if m != 1 else ''}"
    return {"ok": True, "scenario": key, "delay_s": delay,
            "say": f"Staged, sir. Walk away — I'll ring you {when}."}, 200

def raise_card(ctype, title, body="", source="jarvis", priority="normal", action=None, speak=None):
    """Daemons call this. ctype: notify | ask | approve. action: an agent task to run on approve.
    speak: None → the governor decides; False → card only (for answers already spoken aloud)."""
    card = {"id": uuid.uuid4().hex[:12], "ts": int(time.time()), "type": ctype,
            "title": title, "body": body, "source": source, "priority": priority,
            "action": action, "status": "new", "speak": False}
    card["speak"] = should_speak(card) if speak is None else bool(speak)
    with INBOX_LOCK:
        cards = load_inbox(); cards.append(card); save_inbox(cards)
    if CALLS:                                    # phone leg: urgent line + "call me when it's done"
        try: CALLS.card_hook(card)
        except Exception: pass
    return card

def inbox_set_status(cid, status):
    with INBOX_LOCK:
        cards = load_inbox()
        for c in cards:
            if c.get("id") == cid:
                c["status"] = status
                if status != "new":
                    c["speak"] = False
        save_inbox(cards)
    return inbox_open()
def inbox_mark_spoken(cid):
    with INBOX_LOCK:
        cards = load_inbox()
        for c in cards:
            if c.get("id") == cid:
                c["speak"] = False
                if c.get("status") == "new":
                    c["status"] = "seen"
        save_inbox(cards)
    return inbox_open()
def inbox_act(cid):
    card = next((c for c in load_inbox() if c.get("id") == cid), None)
    if not card:
        return None, "I can't find that card, sir."
    action = card.get("action")
    if not action:
        return {"answer": "Cleared, sir.", "cards": inbox_set_status(cid, "done")}, None
    res, err = run_agent(action, execute=True)     # approve → run the confirmed action
    inbox_set_status(cid, "done")
    if err:
        return None, err
    res["cards"] = inbox_open()
    return res, None

CTYPE = {"html": "text/html", "js": "application/javascript", "css": "text/css",
         "png": "image/png", "svg": "image/svg+xml", "json": "application/json",
         "mjs": "text/javascript", "wasm": "application/wasm", "task": "application/octet-stream",
         "mp4": "video/mp4", "gif": "image/gif"}

class H(BaseHTTPRequestHandler):
    timeout = 60                                   # S23: no stalled socket may pin a handler thread forever

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _sec_headers(self, ext=""):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")   # no <script src>/<img> embeds from other origins
        self.send_header("Referrer-Policy", "no-referrer")
        if ext == "html":
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")

    def _deny(self, code, why):
        try:
            print(f"[security] {code} {why}: {self.command} {self.path.split('?')[0]} "
                  f"origin={self.headers.get('Origin') or '-'} host={self.headers.get('Host') or '-'}", flush=True)
        except Exception:
            pass
        return self._json({"error": why}, code)

    def _host_ok(self):
        return (self.headers.get("Host") or "").strip().lower() in ALLOWED_HOSTS

    def _fetch_ok(self, path):
        """GET gate: same-origin page loads and typed URLs pass; a cross-site (or other-port) page may
        only NAVIGATE to the app itself — never embed or fetch its files (XSSI of the note graph)."""
        site = (self.headers.get("Sec-Fetch-Site") or "").lower()
        if site in ("", "same-origin", "none"):
            return True
        return (self.headers.get("Sec-Fetch-Dest") or "").lower() == "document" and path in NAV_OK

    def _origin_ok(self):
        o = self.headers.get("Origin")
        return (not o) or o in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}")

    def do_GET(self):
        path = self.path.split("?")[0]
        if not self._host_ok():
            return self._deny(421, "bad host")
        if not self._fetch_ok(path):
            return self._deny(403, "cross-site request refused")
        if MISSIONS and path.startswith("/mission"):
            try:
                if MISSIONS.handle(self, "GET", self.path, {}): return
            except Exception as e:
                return self._json({"error": f"mission bay error: {str(e)[:120]}"}, 500)
        if TOOLS and (path in ("/api/tools", "/oauth/callback") or path.startswith("/tool_logo/")):
            try:
                if TOOLS.handle(self, "GET", self.path, {}): return
            except Exception as e:
                return self._json({"error": f"tool bay error: {str(e)[:120]}"}, 500)
        if HANDS and path == "/api/hands":
            try:
                if HANDS.handle(self, "GET", self.path, {}): return
            except Exception as e:
                return self._json({"error": f"hands bay error: {str(e)[:120]}"}, 500)
        if CALLS and path == "/api/calls":
            try:
                if CALLS.handle(self, "GET", self.path, {}): return
            except Exception as e:
                return self._json({"error": f"calls bay error: {str(e)[:120]}"}, 500)
        if POCKET and path == "/api/pocket":
            try:
                if POCKET.handle(self, "GET", self.path, {}): return
            except Exception as e:
                return self._json({"error": f"pocket bay error: {str(e)[:120]}"}, 500)
        if path == "/holo/diag":            # S21 HOLO field diag: read this BEFORE touching a gesture gate
            return self._json({"n": len(HOLO_DIAG), "gates": HOLO_GATES[0], "events": HOLO_DIAG[-200:]})
        if FOCUS and path.startswith("/focus"):
            try:
                if FOCUS.handle(self, "GET", self.path, {}): return
            except Exception as e:
                return self._json({"error": f"focus bay error: {str(e)[:120]}"}, 500)
        if REFLEX and path.startswith("/reflex"):
            try:
                if REFLEX.handle(self, "GET", self.path, {}): return
            except Exception as e:
                return self._json({"error": f"reflex bay error: {str(e)[:120]}"}, 500)
        if TEARDOWN and path.startswith("/teardown"):
            try:
                if TEARDOWN.handle(self, "GET", self.path, {}): return
            except Exception as e:
                return self._json({"error": f"teardown bay error: {str(e)[:120]}"}, 500)
        if ASSIST and path == "/api/loops":
            try:
                if ASSIST.handle(self, "GET", self.path, {}): return
            except Exception as e:
                return self._json({"error": f"assist bay error: {str(e)[:120]}"}, 500)
        if path == "/api/brand":
            return self._json({"name": CFG.get("name", "SECOND BRAIN"), "logo": bool(CFG.get("logo"))})
        if path == "/api/tasks":
            return self._json({"tasks": open_tasks()})
        if path == "/api/proactive":
            return self._json(proactive_status())
        if path == "/api/inbox":
            LAST_POLL[0] = time.time()           # a viewer tab is alive — the desk owns spoken reminders
            return self._json({"cards": inbox_open()})
        if path == "/api/dnd":
            return self._json(load_dnd())
        if path == "/api/model":
            return self._json(model_status())
        if path == "/api/duplex_nodes":          # node side-channel for live duplex sessions
            with DUPLEX_LOCK:
                return self._json(dict(DUPLEX_NODES))
        if path == "/api/voice":
            return self._json(voice_status())
        if path == "/api/persona":
            return self._json(persona.status())
        if path == "/api/lang":
            return self._json(lang_status())
        if path == "/api/duplex":                # live-conversation engines available + active pick
            dx = load_duplex()
            dp = duplex_providers()
            return self._json({"configured": bool(dp["provider"]), "agent_id": dx.get("agent_id", ""), **dp})
        if path == "/api/realtime_session":      # short-lived OpenAI token for the WebRTC session
            res, err = realtime_session()
            return self._json({"error": err}, 502) if err else self._json(res)
        if path == "/api/duplex_signed":         # short-lived signed WebSocket URL for the live session
            dx = load_duplex()
            key = (CFG.get("elevenlabs") or {}).get("api_key", "")
            if not dx.get("agent_id") or not key or key.startswith("PUT-"):
                return self._json({"error": "live mode isn't set up yet, sir — run setup_duplex.py first"}, 502)
            try:
                req = urllib.request.Request(
                    "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url?agent_id=" + dx["agent_id"],
                    headers={"xi-api-key": key})
                with urllib.request.urlopen(req, timeout=15) as r:
                    return self._json({"signed_url": json.load(r).get("signed_url", "")})
            except Exception as e:
                return self._json({"error": f"couldn't open the line, sir ({str(e)[:120]})"}, 502)
        if path == "/":
            path = "/3d.html"
        vd = os.path.join(ROOT, "viewer")
        fp = os.path.normpath(os.path.join(vd, path.lstrip("/")))
        ext = fp.rsplit(".", 1)[-1].lower() if "." in os.path.basename(fp) else ""
        if os.path.isfile(fp) and (fp == vd or fp.startswith(vd + os.sep)) and ext in CTYPE:   # S23: only known asset types (no .bak, no strays)
            data = open(fp, "rb").read()
            ctype = CTYPE[ext]
            # HTTP Range support (V7 face lesson): without 206s Chrome marks media
            # unseekable (seekable=[[0,0]]) — every <video> seek silently no-ops and
            # loop playback dies snapping back to 0. Ranges fix seeking for good.
            m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
            if m and (m.group(1) or m.group(2)):
                n = len(data)
                start = int(m.group(1)) if m.group(1) else max(0, n - int(m.group(2)))
                end = min(int(m.group(2)), n - 1) if (m.group(1) and m.group(2)) else n - 1
                if start > end or start >= n:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % n); self.end_headers(); return
                chunk = data[start:end + 1]
                try:                                # media clients abort ranges constantly — not an error
                    self.send_response(206)
                    self.send_header("Content-Type", ctype); self._sec_headers(ext)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, n))
                    self.send_header("Content-Length", str(len(chunk))); self.end_headers(); self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", ctype); self._sec_headers(ext)
                self.send_header("Cache-Control", "no-store")   # always serve the freshest viewer (no stale pages)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass                                # tab closed mid-download — quietly let it go
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if not self._host_ok():
            return self._deny(421, "bad host")
        if not self._origin_ok():
            return self._deny(403, "bad origin")
        try:
            ln = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._deny(400, "bad length")
        if ln < 0 or ln > MAX_BODY:
            return self._deny(413, "body too large")
        try:
            p = json.loads(self.rfile.read(ln) or b"{}")
        except Exception:
            p = {}
        if not isinstance(p, dict):
            p = {}
        path = self.path.split("?")[0]

        if MISSIONS and path.startswith("/mission"):
            try:
                if MISSIONS.handle(self, "POST", self.path, p): return
            except Exception as e:
                return self._json({"error": f"mission bay error: {str(e)[:120]}"}, 500)

        if TOOLS and path.startswith("/tools"):
            try:
                if TOOLS.handle(self, "POST", self.path, p): return
            except Exception as e:
                return self._json({"error": f"tool bay error: {str(e)[:120]}"}, 500)

        if HANDS and path.startswith("/hands"):
            try:
                if HANDS.handle(self, "POST", self.path, p): return
            except Exception as e:
                return self._json({"error": f"hands bay error: {str(e)[:120]}"}, 500)

        if CALLS and path.startswith("/calls"):
            try:
                if CALLS.handle(self, "POST", self.path, p): return
            except Exception as e:
                return self._json({"error": f"calls bay error: {str(e)[:120]}"}, 500)

        if ASSIST and path.startswith("/assist"):
            try:
                if ASSIST.handle(self, "POST", self.path, p): return
            except Exception as e:
                return self._json({"error": f"assist bay error: {str(e)[:120]}"}, 500)

        if path == "/holo/diag":            # S21: holo.js phones its gesture events + pinch numbers home (whitelisted keys only)
            evs = p.get("events") or []
            if isinstance(evs, list):
                srv = round(time.time(), 1)
                for e in evs[:200]:
                    if isinstance(e, dict):
                        HOLO_DIAG.append({"srv": srv, **{k: v for k, v in e.items() if k in HOLO_KEYS}})
                del HOLO_DIAG[:-400]
            if isinstance(p.get("gates"), dict):
                HOLO_GATES[0] = {k: v for k, v in p["gates"].items() if k in ("in", "out", "tight", "dbl", "tap")}
            return self._json({"ok": True, "n": len(HOLO_DIAG)})
        if FOCUS and path.startswith("/focus"):
            try:
                if FOCUS.handle(self, "POST", self.path, p): return
            except Exception as e:
                return self._json({"error": f"focus bay error: {str(e)[:120]}"}, 500)
        if REFLEX and path.startswith("/reflex"):
            try:
                if REFLEX.handle(self, "POST", self.path, p): return
            except Exception as e:
                return self._json({"error": f"reflex bay error: {str(e)[:120]}"}, 500)
        if TEARDOWN and path == "/teardown/dispatch":          # S29f: the voice route's door into the same dispatcher
            return self._json(teardown_dispatch(p.get("target") or "", p.get("question") or "", p.get("session"), dry=bool(p.get("dry")),
                                                then_build=p.get("then_build"), headless=bool(p.get("headless"))))
        if TEARDOWN and path.startswith("/teardown"):
            try:
                if TEARDOWN.handle(self, "POST", self.path, p): return
            except Exception as e:
                return self._json({"error": f"teardown bay error: {str(e)[:120]}"}, 500)

        if path == "/presence":           # client drives the desktop orb (screen-share on/off, states)
            cmd = (p.get("cmd") or "").strip()
            if cmd == "show":
                SHARE_VIS[0] = True
            elif cmd == "hide":
                SHARE_VIS[0] = False
                # share ended mid-DRIVE: the takeover still owns the orb — keep it up as DRIVING;
                # the drive's finish sees the share's claim gone and hides it then
                if HANDS and HANDS.RUN.get("active"):
                    cmd = "state:working"
            if cmd: presence(cmd)
            return self._json({"ok": True})

        if path == "/tool_chat":         # "use canva to…" — act through the connected tools
            q = (p.get("question") or "").strip()
            if not q: return self._json({"error": "empty question"}, 400)
            # the calendar offer's answer can reach THIS door too — "yes, add it to my calendar"
            # rides mailcalRoute → /tool_chat on the desk (audit 2026-07-28 night); the catcher
            # stands down unless an offer is genuinely pending, so real tool asks pass clean
            cal = cal_offer_reply(q, p.get("session"))
            if cal is not None:
                return self._json({"answer": cal, "nodes": [], "tools_used": [],
                                   "tool_calls": [], "tool_errors": 0})
            # deal-noun asks NEVER build through raw tools (audit 2026-07-28 night: "make me
            # an invoice in a google doc" minted an unnumbered, unfiled, undelivered doc) —
            # forward to the chat brain, whose [DEAL:] machinery owns those documents
            if re.search(r"\b(?:make|create|draft|prepare|write|put together|generate|send)\b"
                         r"[^?.!]*\b(?:invoices?|proposals?|quotes?|estimates?)\b", q, re.I):
                ans, nodes, err = chat(q, p.get("session"))
                if err: return self._json({"error": err}, 502)
                tagged = apply_control_tag(ans, p.get("session"), q)
                if tagged: return self._json(tagged)
                return self._json({"answer": ans, "nodes": nodes or [],
                                   "tools_used": [], "tool_calls": [], "tool_errors": 0})
            res, err = tool_chat(q, p.get("session"))
            if err: hue.error_flash()
            return self._json({"error": err}, 502) if err else self._json(res)

        if path == "/chat":
            q = (p.get("question") or "").strip()
            if not q: return self._json({"error": "empty question"}, 400)
            swapped = try_chat_swap(q)          # regex fast path: "switch to grok" from ANY surface
            if swapped:
                return self._json(swapped)
            costed = try_cost_quip(q, p.get("session"))   # "what do you cost?" → the measured price, scripted
            if costed:
                return self._json(costed)
            ans, nodes, err = chat(q, p.get("session"), image=((p.get("image") or "").strip() or None))
            if not err:
                tagged = apply_control_tag(ans, p.get("session"), q)  # the brain flagged a swap/search the regexes missed
                if tagged:
                    if REFLEX and isinstance(tagged, dict):           # S25c: the vault verdict rides the [SEARCH:] branch too —
                        rx_last = REFLEX.pop_last(p.get("session"))   # "not in the vault" must reach the strip when the brain goes to the web
                        if rx_last: tagged["reflex"] = rx_last
                    return self._json(tagged)
                gm = GAG_TAG_RE.search(ans or "")  # the brain filed a running gag for later
                if gm:
                    persona.add_gag(gm.group(1), gm.group(2))
                    ans = GAG_TAG_RE.sub("", ans).strip()
                ans = re.sub(r"\*{1,2}([^*\n]+)\*{1,2}", r"\1", ans or "")  # raw **bold** was reaching the screen
                if not ans.strip() or ans.strip() == "(no answer)":
                    # a silent turn is NEVER acceptable (2026-07-28: two "(no answer)" bubbles
                    # while he was approving a booking — the model returned empty twice; the
                    # call_model placeholder slipped past this guard on 2026-08-11)
                    ans = "I lost my words for a moment there, sir — say that once more?"
                if REFLEX and REFLEX.enabled():        # S25 THE JUDGE: a claimed action with no receipt never reaches the voice
                    try:
                        jd = REFLEX.judge(q, ans, receipts=[])   # plain-chat path: tool chains returned earlier via `tagged`
                    except Exception:
                        jd = None
                    if jd:
                        prev = REFLEX.pop_last(p.get("session")) or {}
                        prev["judge"] = {"blocked": bool(jd.get("blocked")), "original": jd.get("original"),
                                         "claims": jd.get("claims"), "backed": jd.get("backed"), "ms": jd.get("ms")}
                        REFLEX.set_last(p.get("session"), prev)
                        if jd.get("blocked"):
                            ans = jd["line"]
                log_episode("chat", q, nodes)
            else:
                hue.error_flash()
                if str(err).startswith("model ") and MODEL != BOOT_MODEL:
                    # an experimental (swapped) brain failing must never read as silence (2026-08-26:
                    # glm :free 429s looked like "thinking → nothing") — speak the truth + the way home;
                    # raw detail stays on screen per the tech-garbage law
                    friendly = "rate-limited upstream" if " 429" in str(err) else "not answering"
                    return self._json({"answer": f"The {MODEL} brain is {friendly} right now, sir — "
                                       "say 'switch to your normal brain' and I'll carry on as usual.",
                                       "nodes": [], "detail": str(err)[:300]})
            if err:
                return self._json({"error": err}, 502)
            out = {"answer": ans, "nodes": nodes}
            if REFLEX:
                rx_last = REFLEX.pop_last(p.get("session"))
                if rx_last: out["reflex"] = rx_last          # S25: vault verdict + judge ride back to the viewer
            return self._json(out)

        if path == "/research":     # explicit "research/look up X" → live web search (Anthropic server tool)
            q = (p.get("question") or "").strip()
            if not q: return self._json({"error": "empty question"}, 400)
            res, err = web_research(q, p.get("session"), image=(p.get("image") or None))
            if err: hue.error_flash()
            return self._json({"error": err}, 502) if err else self._json(res)

        if path == "/tts":
            t = (p.get("text") or "").strip()
            if not t: return self._json({"error": "empty text"}, 400)
            with VOICE_LOCK:
                _mid = VOICE.get("model_id") or ""
            t = speakable(t) or "It's on your screen, sir."   # never let a fully-stripped line 502 the voice
            t = persona.speech_text(t, _mid)     # audio tags reach only the v3 engine
            audio, err = synth_voice(t)
            if err: return self._json({"error": err}, 502)
            self.send_response(200); self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(audio))); self.end_headers(); self.wfile.write(audio); return

        if path == "/remember":
            t = (p.get("text") or "").strip()
            if not t: return self._json({"error": "empty text"}, 400)
            res, err = capture(t, (p.get("related") or "").strip())
            if not err: log_episode("note", "Captured: " + t)
            return self._json({"error": err}, 502) if err else self._json(res)

        if path == "/edit":
            res, err = edit_note((p.get("target") or "").strip(), (p.get("text") or "").strip())
            return self._json({"error": err}, 502) if err else self._json(res)

        if path == "/task":
            t = (p.get("text") or "").strip()
            if not t: return self._json({"error": "empty task"}, 400)
            return self._json({"tasks": add_task(t, p.get("due"))})
        if path == "/tasks":
            return self._json({"tasks": open_tasks()})
        if path == "/task_done":
            return self._json({"tasks": complete_task(p.get("index"))})
        if path == "/task_reminded":      # a due reminder has fired client-side — don't re-fire
            return self._json({"tasks": mark_reminded(p.get("ts"))})

        if path == "/facewin":            # SCREEN WATCH: the living face pinned to the real desktop
            facewin_claim("watch", bool(p.get("on")))
            return self._json({"ok": True})

        if path == "/demo/urgent":        # V7.1 DEMO BAY (his ask 2026-09-19): stage a believable urgent event
            res, code = demo_urgent(p)    # → desk card + Telegram push + the phone RINGS, on a delay
            return self._json(res, code)

        if path == "/episode":            # V7: client-observed moments land in the time machine
            kind = str(p.get("kind") or "")
            if kind not in ("eyes", "focus"):   # whitelist — sight-organ + focus-session moments only
                return self._json({"error": "unknown kind"}, 400)
            log_episode(kind, str(p.get("text") or "")[:200])
            return self._json({"ok": True})

        if path == "/briefing":
            ans, err = briefing()
            return self._json({"error": err}, 502) if err else self._json({"answer": ans})

        if path == "/proactive":
            return self._json(set_proactive(p.get("enabled"), p.get("time")))
        if path == "/proactive_ack":
            return self._json(proactive_ack())

        if path == "/agent":
            t = (p.get("task") or "").strip()
            if not t: return self._json({"error": "empty task"}, 400)
            res, err = run_agent(t)
            if not err: log_episode("agent", "Task: " + t)
            return self._json({"error": err}, 502) if err else self._json(res)
        if path == "/agent_confirm":
            res, err = confirm_agent((p.get("pending_id") or "").strip())
            return self._json({"error": err}, 502) if err else self._json(res)

        if path == "/remember_me":
            res, err = remember_me((p.get("text") or "").strip())
            return self._json({"error": err}, 502) if err else self._json(res)
        if path == "/pulse":
            ans, err = pulse()
            return self._json({"error": err}, 502) if err else self._json({"answer": ans})
        if path == "/inbox":
            ans, err = inbox()
            return self._json({"error": err}, 502) if err else self._json({"answer": ans})
        if path == "/see":
            ans, err = see_image((p.get("image") or "").strip(), (p.get("question") or "").strip())
            if not err and ans:
                # explicit look-asks join the SAME conversation memory, so chat follow-ups
                # ("okay, now what about that error?") know what was just seen
                add_turn(p.get("session"), "user", ((p.get("question") or "").strip() or "(looked at my screen)")
                         + "\n[shared-screen frame attached]")
                add_turn(p.get("session"), "assistant", ans)
            return self._json({"error": err}, 502) if err else self._json({"answer": ans})
        if path == "/call":
            t = (p.get("task") or "").strip()
            if not t: return self._json({"error": "empty task"}, 400)
            res, err = place_call(t, (p.get("to") or "").strip() or None)
            return self._json({"error": err}, 502) if err else self._json(res)

        # ---- agent inbox + governor ----
        if path == "/inbox_add":          # raise a card (daemons/tests/external)
            c = raise_card((p.get("type") or "notify").strip(),
                           (p.get("title") or "").strip() or "Note", (p.get("body") or "").strip(),
                           (p.get("source") or "manual").strip(), (p.get("priority") or "normal").strip(),
                           (p.get("action") or None),
                           speak=(None if p.get("speak") is None else bool(p.get("speak"))))   # S25c: seeded desk cards can stay silent
            return self._json({"card": c, "cards": inbox_open()})
        if path == "/inbox_ack":          # spoken once → stop re-speaking, keep visible
            return self._json({"cards": inbox_mark_spoken((p.get("id") or "").strip())})
        if path == "/inbox_act":          # approve → run the card's confirmed action
            res, err = inbox_act((p.get("id") or "").strip())
            return self._json({"error": err}, 502) if err else self._json(res)
        if path == "/inbox_dismiss":
            return self._json({"cards": inbox_set_status((p.get("id") or "").strip(), "dismissed")})
        if path == "/dnd":                # smart-interrupt governor controls
            if p.get("focus") is not None:
                hue.focus(bool(p.get("focus")))
            return self._json(set_dnd(p.get("focus"), p.get("minutes"), p.get("rule")))

        if path == "/model":              # hot-swap the brain: "Jarvis, try on haiku / grok / deepseek"
            name = (p.get("model") or "").strip()
            if not name: return self._json({"error": "which brain, sir?"}, 400)
            was = MODEL
            mid, merr = set_model(name)
            if not mid:
                if merr == "no_openrouter_key":
                    return self._json({"error": f"I found '{name}' in the OpenRouter catalogue, sir, but you "
                                       "haven't given me the key — paste it under \"openrouter\" in config.json "
                                       "and I can wear nearly any model in existence."}, 402)
                hint = (" With OpenRouter connected, I can also fetch nearly anything — grok, gpt, gemini, "
                        "deepseek…" if or_key() else "")
                return self._json({"error": f"I don't have a '{name}' brain on the shelf, sir — I know " +
                                   ", ".join(known_brains()) + "." + hint}, 404)
            if p.get("quiet"):     # page-refresh reset (his 2026-08-26 decree): silent — no quip spend, no spoken line
                if mid != was: log_episode("model", f"Brain reset to {mid} (page refresh)")
                return self._json({**model_status(), "answer": ""})
            log_episode("model", f"Brain swapped to {mid}")
            quip = swap_quip(mid)                 # one voice for every door — curated pool first
            return self._json({**model_status(), "answer": quip})

        if path == "/voice":              # hot-swap the voice: "switch your voice to Daniel / flash"
            spoken, verr = set_voice((p.get("voice") or "").strip())
            if verr:
                return self._json({"error": verr}, 404)
            return self._json({**voice_status(), "answer": f"How do I sound, sir? This is {spoken}."})

        if path == "/lang":               # multilingual mode: "speak Spanish" / "back to English"
            code = set_lang((p.get("lang") or "").strip())
            if not code:
                return self._json({"error": "I don't speak that one yet, sir — my repertoire runs to " +
                                            ", ".join(lang_status()["spoken"]) + "."}, 404)
            return self._json({**lang_status(), "line": LANGS[code][1]})
        if path == "/xlate":              # a canned desk line → the active language (cached)
            return self._json({"text": xlate((p.get("text") or "")[:6000])})
        if path == "/duplex_pref":        # pick the live-voice engine: elevenlabs | openai | auto
            prov = (p.get("provider") or "auto").strip().lower()
            if prov not in ("elevenlabs", "openai", "auto"):
                return self._json({"error": "elevenlabs, openai, or auto, sir."}, 400)
            dx = load_duplex(); dx["provider"] = prov; save_duplex(dx)
            return self._json(duplex_providers())

        if path == "/persona":           # dials, skins, candid mode
            if p.get("dial"):
                v = persona.set_dial((p["dial"] or {}).get("name"), (p["dial"] or {}).get("value"))
                if v is None:
                    return self._json({"error": "humor or honesty, zero to a hundred, sir."}, 400)
            if p.get("skin"):
                label, vh = persona.set_skin(p["skin"])
                if not label:
                    return self._json({"error": "I don't own that costume, sir — I have " +
                                       ", ".join(persona.status()["skins"]) + "."}, 404)
                set_voice(vh or "default")
            if p.get("candid"):
                try:
                    persona.set_candid(float(p["candid"]))
                except Exception:
                    persona.set_candid(2)
            quip, qerr = call_model([{"role": "user", "content":
                "Your persona settings were just adjusted. Acknowledge in ONE short line, in character, "
                "letting the current settings show in the delivery."}], jpersona(), 200)
            return self._json({**persona.status(),
                               "answer": quip if not qerr and quip and quip != "(no answer)" else "Adjusted, sir."})

        if path == "/os":                 # deterministic Mac control (volume/dark/wifi/apps/windows/scenes)
            res = osctl.do((p.get("action") or "").strip(), p.get("value"), CFG.get("hardware") or {})
            if res is None:
                return self._json({"error": "I don't know that switch, sir."}, 400)
            log_episode("os", f"{p.get('action')}: {p.get('value')}")
            return self._json({"answer": res})

        if path == "/find":               # Spotlight by voice
            res, err = osctl.find_files((p.get("query") or "").strip(), open_top=bool(p.get("open", True)))
            if err:
                return self._json({"error": err}, 400)
            log_episode("os", "Found: " + (p.get("query") or ""))
            return self._json({"answer": res["spoken"], "hits": res.get("hits", [])[:6]})

        if path == "/type":               # universal typing into the focused app
            return self._json({"answer": osctl.type_text(p.get("text") or "")})

        if path == "/clip":               # clipboard: read / history / transform-in-place
            op = (p.get("op") or "read").strip()
            if op == "history":
                h = osctl.clip_history(8)
                if not h:
                    return self._json({"answer": "No clippings logged yet, sir — I watch from boot."})
                return self._json({"answer": f"Your last {len(h)} clippings are on screen, sir — newest: "
                                   + h[0][0][:100], "history": [x[0][:200] for x in h]})
            if op == "transform":
                c = osctl.clip_read()
                if not c.strip():
                    return self._json({"answer": "Nothing on the clipboard to work with, sir."})
                instr = (p.get("instruction") or "clean this up").strip()
                out, terr = call_model([{"role": "user", "content":
                    "Transform the clipboard content below as instructed. Reply with ONLY the transformed "
                    "content, nothing else.\n\nINSTRUCTION: " + instr + "\n\nCONTENT:\n" + c[:6000]}],
                    jpersona(), 2000)
                if terr or not out:
                    return self._json({"error": "the transform failed, sir"}, 502)
                osctl.clip_write(out)
                return self._json({"answer": "Transformed and back on your clipboard, sir — paste away."})
            c = osctl.clip_read()
            return self._json({"answer": ("On your clipboard, sir: " + c[:200]) if c.strip()
                               else "Your clipboard is empty, sir.", "text": c[:4000]})

        if path == "/organize":           # Downloads janitor: plan → approval → move
            res, err = org_plan((p.get("dir") or "Downloads").strip())
            return self._json({"error": err}, 502) if err else self._json(res)
        if path == "/rename_shots":       # screenshot renamer: vision names → approval → rename
            res, err = shots_plan()
            return self._json({"error": err}, 502) if err else self._json(res)
        if path == "/os_confirm":         # "do it" for either of the above
            res, err = os_confirm((p.get("pending_id") or "").strip())
            return self._json({"error": err}, 502) if err else self._json(res)

        if path == "/hue_event":          # client playback events drive the room lighting
            ev = (p.get("event") or "").strip()
            if HANDS and not HANDS.RUN.get("active"):    # don't fight the "driving" state during takeover
                if ev == "speak_start": presence("state:speaking")
                elif ev == "speak_end": presence("state:idle")
            if ev == "speak_start": hue.speak_start()
            elif ev == "speak_end": hue.speak_end()
            elif ev == "error": hue.error_flash()
            elif ev == "focus_on": hue.focus(True)
            elif ev == "focus_off": hue.focus(False)
            return self._json({"ok": True, "hue": hue.status()})
        if path == "/hue_setup":          # pair with the bridge (press the physical button first)
            res, err = hue.setup((p.get("ip") or "").strip() or None)
            return self._json({"error": err}, 502) if err else self._json(res)

        if path == "/guide":              # "show me how" → vision finds the element → overlay ring
            ans, err = guide((p.get("image") or "").strip(), (p.get("question") or "").strip())
            return self._json({"error": err}, 502) if err else self._json(ans)
        if path == "/overlay":            # "draw a circle on my screen" — direct ring, no vision call
            how = spawn_overlay(float(p.get("x_pct") or 50), float(p.get("y_pct") or 45),
                                (p.get("label") or "")[:40])
            if not how:
                return self._json({"error": "the ring wouldn't draw, sir — start me from your own Terminal."}, 502)
            return self._json({"ok": True, "via": how})

        if path == "/recall":             # time machine: "what was I doing last Tuesday?"
            q = (p.get("when") or p.get("question") or "").strip()
            if not q: return self._json({"error": "recall what, sir?"}, 400)
            res, err = recall(q)
            return self._json({"error": err}, 502) if err else self._json(res)

        self.send_response(404); self.end_headers()

    def log_message(self, *a):
        pass

# ---------- duplex brain endpoint (OpenAI-compatible, for ElevenLabs Agents custom-LLM) ----------
# Runs on its own port so ONLY this one route is ever exposed through a public tunnel.
# Auth: Authorization: Bearer <token from jarvis-duplex.json>. The main app on 4719 stays private.
def duplex_reply_parts(body):
    """Build (system, messages) for a live voice turn: same brain — persona + memory + vault RAG."""
    msgs = [m for m in (body.get("messages") or [])
            if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)][-12:]
    last_user = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
    notes, top = retrieve(last_user, k=6)
    style = ("You are in a LIVE VOICE conversation. Reply in 1-3 SHORT spoken sentences — dry, warm, "
             "witty, 'sir' now and then. No markdown, no lists, no stage directions, no emoji.")
    if top >= 4 and notes and not CONV_RE.search(last_user):
        ctx = "\n\n".join(f"## {n['label']}\n{n['p']}" for n in notes)
        set_duplex_nodes([n["_idx"] for n in notes])
        sysp = jpersona(last_user) + mem_block() + style + ("\nIf (and only if) the question is really about the user's "
               "notes below, ground your answer in them (the graph is already flying there):\n\n" + ctx)
    else:
        set_duplex_nodes([])
        sysp = jpersona(last_user) + mem_block() + style
    if last_user:
        log_episode("duplex", last_user)
    return sysp, msgs

# 📡 live-voice replies stream at a 300-token cap with NO retry, and thinking spends from the same
# cap. Sonnet 5.5 defaults to effort "high": 3/10 probe answers were cut mid-sentence (one medium
# answer came back empty); "low" finished 10/10, first word ~1.5s sooner (2026-09-29). Opus 5.5
# ships at "medium" and finished clean, so it's left alone.
STREAM_EFFORT = {"claude-sonnet-5-5": "low"}

def anthropic_stream(system, messages, max_tokens=300):
    """Yield text tokens from the Anthropic Messages API (SSE). stdlib only."""
    key = MODELCFG.get("api_key", "")
    base = (MODELCFG.get("base_url") or "").strip().rstrip("/")
    url = (base + "/v1/messages") if base else "https://api.anthropic.com/v1/messages"
    req_body = {"model": MODEL, "max_tokens": max_tokens, "system": system,
                "messages": messages, "stream": True}
    if STREAM_EFFORT.get(MODEL):
        req_body["output_config"] = {"effort": STREAM_EFFORT[MODEL]}
    body = json.dumps(req_body).encode()
    req = urllib.request.Request(url, data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        for raw in r:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except Exception:
                continue
            if ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                yield ev["delta"].get("text", "")

class DuplexHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    timeout = 30                                   # S23: a stalled tunnel client can't pin a thread
    def _deny(self, code=401):
        b = json.dumps({"error": "unauthorized"}).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            b = b'{"ok": true}'
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        else:
            self.send_response(404); self.end_headers()
    def do_POST(self):
        if self.path.split("?")[0] not in ("/v1/chat/completions", "/chat/completions"):
            return self._deny(404)
        tok = load_duplex().get("token", "")
        auth = self.headers.get("Authorization", "")
        if not tok or not hmac.compare_digest(auth, "Bearer " + tok):
            return self._deny(401)
        try:
            ln = int(self.headers.get("Content-Length") or 0)
            if ln < 0 or ln > 1_000_000:
                return self._deny(413)
            body = json.loads(self.rfile.read(ln) or b"{}")
        except Exception:
            body = {}
        sysp, msgs = duplex_reply_parts(body)
        if not msgs:
            return self._deny(400)
        rid = "chatcmpl-" + uuid.uuid4().hex[:24]
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache"); self.end_headers()
            def chunk(delta, fin=None):
                c = {"id": rid, "object": "chat.completion.chunk", "created": int(time.time()),
                     "model": MODEL, "choices": [{"index": 0, "delta": delta, "finish_reason": fin}]}
                self.wfile.write(("data: " + json.dumps(c) + "\n\n").encode()); self.wfile.flush()
            try:
                chunk({"role": "assistant"})
                base = (MODELCFG.get("base_url") or "").strip()
                native = (not base or "api.anthropic.com" in base)
                if native:
                    for tokn in anthropic_stream(sysp, msgs):
                        chunk({"content": tokn})
                else:   # a hot-swapped OpenRouter/OpenAI-compat brain: answer whole (no SSE relay)
                    txt, err2 = call_model(msgs, sysp, 300)
                    chunk({"content": txt or (err2 or "…")})
                chunk({}, "stop")
                self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()
            except Exception as e:
                print("[duplex]", e)
            return
        # non-streaming fallback
        txt, err = call_model(msgs, sysp, 300)
        out = {"id": rid, "object": "chat.completion", "created": int(time.time()), "model": MODEL,
               "choices": [{"index": 0, "message": {"role": "assistant", "content": txt or (err or "")},
                            "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        b = json.dumps(out).encode()
        self.send_response(200 if not err else 502); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

def start_duplex_server():
    load_duplex()                                   # ensure the token exists
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", DUPLEX_PORT), DuplexHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print(f"Duplex brain (OpenAI-compat, token-authed) on http://localhost:{DUPLEX_PORT}")
    except OSError as e:
        print("[duplex] port busy:", e)

if __name__ == "__main__":
    hands = "ready" if claude_ready() else "NOT FOUND (/agent disabled)"
    prov = "openai-compat" if (MODELCFG.get("base_url") and (MODELCFG.get("provider") or "").lower() != "anthropic"
                               and "api.anthropic.com" not in (MODELCFG.get("base_url") or "")) else "anthropic"
    print(f"Brain Studio V3 (assistant) on http://localhost:{PORT}  ·  {len(CORPUS)} notes  ·  "
          f"model: {MODEL} ({prov})  ·  hands: {hands}  ·  hue: {hue.status()['state']}")
    try:   # a crashed predecessor may have stranded an orb on screen — nobody else will clear it
        _s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _s.sendto(b"quit", ("127.0.0.1", PRESENCE_PORT)); _s.close()
    except Exception:
        pass
    threading.Thread(target=_presence_watchdog, daemon=True).start()
    osctl.start_clip_watch()
    if MISSIONS:
        try:
            MISSIONS.init(dict(cfg=CFG, root=ROOT, port=PORT, raise_card=raise_card,
                               call_model=call_model, claude_read=claude_read, jpersona=jpersona))
            print("[missions] bay online")
        except Exception as e:
            print("[missions] init failed:", e)
    if TOOLS:
        try:
            TOOLS.init(dict(cfg=CFG, root=ROOT, port=PORT, raise_card=raise_card, jpersona=jpersona))
            print("[tools] bay online")
        except Exception as e:
            print("[tools] init failed:", e)
    if GSUITE and TOOLS:
        try:
            # native Gmail/Calendar rides the armory's google-kind token (gmail tile consent)
            GSUITE.init(dict(cfg=CFG, root=ROOT, raise_card=raise_card,
                             access_token=TOOLS.access_token))
            TOOLS.CTX["gsuite"] = GSUITE          # the fast brain attaches its native tools
        except Exception as e:
            print("[gsuite] init failed:", e)
    if DEALS:
        try:
            DEALS.init(dict(cfg=CFG, root=ROOT, call_model=call_model, mem_block=mem_block,
                            retrieve=retrieve, raise_card=raise_card, gsuite=GSUITE,
                            # late-bound: POCKET boots later in this sequence, and delivery
                            # must survive a pocket that isn't configured yet
                            pocket_file=(lambda blob, fname, mime, cap:
                                         POCKET.push_file(blob, fname, mime, cap)
                                         if POCKET and POCKET.configured() else False),
                            log=lambda kind, text: log_episode(kind, text)))
        except Exception as e:
            print("[deals] init failed:", e)
    if HANDS:
        try:
            HANDS.init(dict(cfg=CFG, model=MODEL, key=MODELCFG.get("api_key", ""),
                            base=MODELCFG.get("base_url", ""), provider=MODELCFG.get("provider", "anthropic"),
                            jpersona=jpersona, mem_block=mem_block, presence=presence,
                            share_on=lambda: SHARE_VIS[0],
                            speed=(CFG.get("takeover") or {}).get("speed", "balanced"),
                            persist_speed=_persist_takeover_speed,
                            log=lambda kind, text: log_episode("takeover", f"{kind}: {text[:80]}")))
            print("[hands] bay online")
        except Exception as e:
            print("[hands] init failed:", e)
    if CALLS:
        try:
            threading.Thread(target=_reminder_call_loop, daemon=True).start()
            CALLS.init(dict(cfg=CFG, root=ROOT, jpersona=jpersona, mem_block=mem_block,
                            call_model=call_model, web_research=web_research, raise_card=raise_card,
                            inbox_open=inbox_open, retrieve=retrieve, speakable=speakable,
                            assist=ASSIST, gsuite=GSUITE, deals=DEALS,
                            pocket_report=(lambda text, card_id=None:
                                           POCKET.push_call_report(text, card_id)
                                           if POCKET and POCKET.configured() else None),
                            tool_task=(lambda prompt:
                                       TOOLS.chat([{"role": "user", "content": prompt}],
                                                  jpersona() + "Execute this ONE task with the "
                                                  "connected tools, then reply in ONE short sentence "
                                                  "with the concrete result. HONESTY: claim success "
                                                  "only from a real tool result.", 4)
                                       if TOOLS else (None, "tools bay offline")),
                            log=lambda kind, text: log_episode("call", f"{kind}: {text[:80]}")))
            print("[calls] bay online")
        except Exception as e:
            print("[calls] init failed:", e)
    if POCKET:
        try:
            if ASSIST:
                try:
                    ASSIST.init(dict(cfg=CFG, root=ROOT, apply_tag=apply_control_tag,
                                     raise_card=raise_card,
                                     log=lambda kind, text: log_episode(kind, text)))
                    print("[assist] bay online")
                except Exception as e:
                    print("[assist] init failed:", e)
            POCKET.init(dict(cfg=CFG, root=ROOT, chat=chat, try_chat_swap=try_chat_swap,
                             assist_file=(lambda text, sid=None:
                                          ASSIST.extract_and_file(text, "telegram", sid)
                                          if ASSIST else ""),
                             brain_lookup=(lambda q: CALLS.brain_answer(q)
                                           if CALLS and hasattr(CALLS, "brain_answer") else None),
                             apply_tag=apply_control_tag, gag_re=GAG_TAG_RE, add_gag=persona.add_gag,
                             log=log_episode, open_tasks=open_tasks, mark_reminded=mark_reminded,
                             inbox_open=inbox_open, raise_card=raise_card,
                             # reminder CALLS (and TEXTS) belong to _reminder_call_loop when
                             # their channel is up — the pocket sweep is the fallback, never
                             # a racing double-claimer (audit 2026-07-28 night)
                             routed_elsewhere=(lambda text:
                                 (_reminder_route(text) == "call"
                                  and bool(CALLS and CALLS.configured() and CALLS.callback_number()))
                                 or (_reminder_route(text) == "text"
                                     and bool(POCKET and POCKET.configured()))),
                             last_seen=lambda: LAST_POLL[0]))
            print("[pocket] bay online" + ("" if POCKET.configured() else " (no Telegram token yet — dormant)"))
        except Exception as e:
            print("[pocket] init failed:", e)
    if FOCUS:
        try:
            # deliberately key-free: the bay gets a logger + the desktop face, nothing else
            FOCUS.init(dict(root=ROOT, log=log_episode, facewin_send=facewin,
                            facewin_claim=lambda on: facewin_claim("focus", on)))
            print("[focus] bay online")
        except Exception as e:
            print("[focus] init failed:", e)
    if TEARDOWN:
        try:
            def _note_turn(sid, text):
                # a finished teardown joins the session's memory so "how would I rebuild that?" works:
                # appended to the ack turn (history must keep alternating user/assistant)
                with SESS_LOCK:
                    h = hist(sid)
                    if h and h[-1].get("role") == "assistant" and isinstance(h[-1].get("content"), str):
                        h[-1]["content"] = (h[-1]["content"] + "\n\n" + text)[-4000:]
            TEARDOWN.init(dict(cfg=CFG, root=ROOT, vault=VAULT, call_model=call_model,
                               persist_node=persist_node, find_note=find_note, retrieve=retrieve,
                               corpus=lambda: CORPUS,
                               wikilink=_wikilink, note_turn=_note_turn,
                               log=lambda kind, text: log_episode(kind, text),
                               then_build=_then_build,
                               pocket_text=(lambda t: POCKET.push_text(t)
                                            if POCKET and POCKET.configured() else False)))
        except Exception as e:
            print("[teardown] init failed:", e)
    start_duplex_server()
    _lockdown_secrets()                             # S23
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
