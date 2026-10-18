"""JARVIS · REFLEX (Session 25, 2026-09-21) — the Jev reflex layer.

Jev (TypeSafe AI, jev-1.13.0) never writes text: state + typed questions in, calibrated
probabilities out in ~200 ms. This bay is the assistant's SPINAL CORD, in front of the brain:
  · prepass  — one call per utterance: lane · complete · addressed · destructive · urgent
  · recall   — 40 candidate notes → per-note nouls + "does the vault have it at all"
  · judge    — an answer that claims an action with no tool receipt is blocked and corrected
  · triage   — every inbox card / comment scored in a blink (kind · needs reply · urgent)

LAWS (S25):
  · Jev is ADVISORY. Every gate is a NAMED CONSTANT below; the policy lives in code, never in
    the model. Hard rules (destructive verbs, the always-confirm list) stay in code.
  · Every call carries a DEADLINE. Past it (or on any error) the caller falls back to today's
    regex/rules. The reflex may make Jarvis smarter; it may never make him slower or silent.
  · Full distributions + model + question version are LOGGED (jarvis-reflex.jsonl, chmod 600)
    so thresholds can be retuned from real data without re-running inference.
  · Keys stay server-side. The viewer only ever talks to /reflex/*.
  · Text only. EYES/HOLO signals arrive as text fields in `ctx`, never as pixels.
"""
import concurrent.futures, difflib, json, os, re, threading, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(ROOT, "jarvis-reflex.jsonl")
STATE_FILE = os.path.join(ROOT, "jarvis-reflex.json")
API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL_DEFAULT = "jev-1.13.0"     # PINNED. Aliases move; the gates below were tuned on this version.
QUESTION_VERSION = "s25.3"       # s25.3 (2026-09-22 field pass): vault lane covers "pull up X"; recall gains `names` for navigation asks
PRICE_PER_MTOK = 0.042           # input; output tokens are free

# ---- deadlines (seconds) — past these the caller uses the old path -------------------------
DEADLINE_S = 0.8                 # prepass / judge: p50 ~120-250 ms from this Mac, tails to ~1 s
RECALL_DEADLINE_S = 1.4          # 40-note batches measure 300-500 ms p50
TRIAGE_DEADLINE_S = 8.0          # chunked + parallel; a whole inbox in a few seconds

# ---- gates (NAMED CONSTANTS; tune from GET /reflex/diag + the log, never blind) -------------
LANE_ACT = 0.70                  # lane confidence to trust the lane (n8n: <0.7 flips ~40% on re-run)
LANE_PEEK = 0.60                 # S25c: vault_question confidence that starts the READ-ONLY early recall (heat) on a partial;
                                 #       yesterday's partials scored .58-.76 while finals scored .94+, so .70 hid the streaming beat
LANE_CLARIFY = 0.50              # below: Jarvis asks instead of guessing
COMPLETE_FIRE = 0.85             # early dispatch on an interim transcript (+ a pause client-side)
ADDRESSED_ROOM = 0.80            # ambient / follow-up window
ADDRESSED_FILMING = 0.70         # recording mode: speak ONLY when it is clearly to Jarvis. S25c drill (2026-09-22, 24 lines):
                                 #   narration to camera scored .06-.18, addresses WITHOUT his name .76-.98 → .90 muted 3 of 13 real asks, .70 muted none
NARRATING_QUIET = 0.60           # filming mode belt-and-braces: `narrating` at/above this stays quiet even if `addressed` passes
DESTRUCTIVE_CONFIRM = 0.50       # at/above: the client arms a confirm before acting
FOUND = 0.70                     # vault answerability: ground the brain in the selected notes
ABSENT = 0.35                    # below: "not in the vault, sir" — never improvise from notes
NOTE_KEEP = 0.40                 # per-note noul: include the note (lean inclusive, Vellum's number)
NAMED_OPEN = 0.70                # recall: `names` noul — the ask OPENS a note by name (no fact to contain) → found when the named note scores ≥ NOTE_KEEP
CLAIM = 0.70                     # judge: the answer claims an action was performed this turn
BACKED = 0.40                    # judge: a receipt supports the claim
TRIAGE_CHUNK = 12                # cards per call (S25c: at 40 an invoice complaint read as praise — neighbours cross-talk; 12 keeps kinds clean, workers keep it fast)
# ---- the URGENCY GOVERNOR (S25c, 2026-09-22) — should this desk card break in with VOICE? ----------
GOVERNOR_MODE = "shadow"         # "shadow": today's regex/priority ladder decides and Jev's verdict is LOGGED beside it (agree/differ)
                                 # "live":   Jev's atomic nouls feed the SAME ladder (money noul replaces the money regex; the score gates normal cards)
                                 # "off":    never asked
GOV_SPEAK = 0.55                 # situational score at/above → a normal-priority card may break in (live)
GOV_URGENT = 0.75                # at/above → counts as urgent under focus / DND / quiet hours (live)
GOV_MONEY = 0.70                 # `money` noul at/above → the "money always breaks through" rule (replaces the regex, live)
GOV_BASE = {"high": 0.45, "normal": 0.15, "low": 0.0}                                   # priority still anchors the score
GOV_W = {"money": 0.30, "waiting": 0.25, "time": 0.25, "broken": 0.20, "lead": 0.30, "routine": -0.35, "noise": -0.40}   # atomic nouls → one situational score
GOV_CHUNK = 8                    # cards per RECEIPTS call (govern_batch); at 40 the nouls cross-talked between neighbours (spam inherited "money" from a payment card)
                                 # receipts 2026-09-22 (203 real cards): without `noise` a "FREE AI tools, sub for sub" comment scored .87 (FREE read as money);
                                 # without `lead` a flexible-budget sponsorship inquiry missed the speak gate; lead .25→.30 so a clean licensing lead (lead .93) clears .55
TRIAGE_WORKERS = 6
KEEP_MS = 400                    # rolling latency window for p50/p95

CTX = {"cfg": None, "root": ROOT, "retrieve": None, "corpus": None, "log": None}
STATE = {"on": True, "filming": False, "day": "", "calls": 0, "tokens": 0, "cost": 0.0,
         "ms": [], "last_error": "", "last_ts": 0, "gov_scored": 0, "gov_agree": 0}
LAST = {}                        # sid -> reflex payload for the /chat response
_LOCK = threading.Lock()

# ---------------------------------------------------------------------------------- plumbing
def _cfg():
    return (CTX.get("cfg") or {}).get("typesafe") or {}

def _key():
    k = (_cfg().get("api_key") or os.environ.get("TYPESAFE_API_KEY") or "").strip()
    return k if k and not k.startswith("PUT-") else ""

def model():
    return (_cfg().get("model") or MODEL_DEFAULT).strip()

def enabled():
    return bool(STATE["on"] and _key())

def _load_state():
    try:
        d = json.load(open(STATE_FILE))
        STATE["on"] = bool(d.get("on", True)); STATE["filming"] = bool(d.get("filming", False))
    except Exception:
        pass
    _rebuild_today()

def _rebuild_today():
    """S25c: today's tally (calls · tokens · cost · latency) is rebuilt from the log at boot, so a restart
    can never make "what did your reflexes cost today" forget the morning."""
    day = time.strftime("%Y-%m-%d"); calls = tokens = 0; ms = []
    try:
        with open(LOG_FILE) as f:
            for line in f:
                try: r = json.loads(line)
                except Exception: continue
                if time.strftime("%Y-%m-%d", time.localtime(r.get("ts", 0))) != day: continue
                calls += 1; tokens += int(r.get("tokens") or 0); ms.append(int(r.get("ms") or 0))
    except Exception:
        return
    with _LOCK:
        STATE.update(day=day, calls=calls, tokens=tokens, cost=tokens / 1e6 * PRICE_PER_MTOK, ms=ms[-KEEP_MS:])

def _save_state():
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f: json.dump({"on": STATE["on"], "filming": STATE["filming"]}, f)
        os.replace(tmp, STATE_FILE); os.chmod(STATE_FILE, 0o600)
    except Exception:
        pass

def _log(rec):
    try:
        new = not os.path.exists(LOG_FILE)
        with open(LOG_FILE, "a") as f: f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        if new: os.chmod(LOG_FILE, 0o600)
    except Exception:
        pass

def _tally(ms, tokens):
    day = time.strftime("%Y-%m-%d")
    with _LOCK:
        if STATE["day"] != day:
            STATE.update(day=day, calls=0, tokens=0, cost=0.0, ms=[])
        STATE["calls"] += 1; STATE["tokens"] += tokens; STATE["cost"] += tokens / 1e6 * PRICE_PER_MTOK
        STATE["ms"].append(ms); STATE["ms"] = STATE["ms"][-KEEP_MS:]; STATE["last_ts"] = time.time()

def ask(state, questions, purpose, deadline=DEADLINE_S, extra=None, log=True):
    """One Jev call. Returns the normalized dict or None (timeout / error / disabled). NEVER raises."""
    if not enabled():
        return None
    body = json.dumps({"state": state, "model": model(), "questions": questions}).encode()
    req = urllib.request.Request(API_URL, data=body, method="POST",
                                 headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=deadline) as r:
            raw = json.load(r)
    except urllib.error.HTTPError as e:
        STATE["last_error"] = "%s HTTP %s" % (purpose, e.code); return None
    except Exception as e:                                   # timeouts included: the caller falls back
        STATE["last_error"] = "%s %s" % (purpose, str(e)[:80]); return None
    ms = round((time.perf_counter() - t0) * 1000)
    tokens = int((raw.get("usage") or {}).get("input_tokens") or 0)
    _tally(ms, tokens)
    out = {"model": raw.get("model"), "ms": ms, "tokens": tokens, "cost": tokens / 1e6 * PRICE_PER_MTOK,
           "answers": raw.get("answers") or {}, "purpose": purpose, "qv": QUESTION_VERSION}
    rec = {"ts": round(time.time(), 3), "purpose": purpose, "model": out["model"], "qv": QUESTION_VERSION,
           "ms": ms, "tokens": tokens, "state_chars": len(body), "answers": out["answers"]}
    if extra: rec.update(extra)                              # S25c: the utterance rides along (600-perm log) — tuning needs it
    if log: _log(rec)
    return out

def _noul(a, k, default=0.0):
    try: return float(a[k]["noul"])
    except Exception: return default

# --------------------------------------------------------------------------------- questions
LANES = {
    "vault_question": "A question about his own notes, projects, products, people, or past work stored in the second brain, OR a request to open, show, pull up, find, or fly to one of them by name; any name listed in `his_vocabulary` is his",
    "chat": "Small talk, an opinion, a joke, or a general question that needs no lookup and no action",
    "mail_calendar": "Anything about his email, inbox, calendar, meetings, or drafting a message",
    "camera_question": "Asks what the camera can see, what he is holding or wearing, or how he looks",
    "screen_question": "Asks about what is on his screen right now",
    "focus": "Start, stop, pause, or change an accountability focus timer or session",
    "agent_task": "A multi-step job for the assistant to go do: research, build, post, organise, audit, repurpose",
    "brain_swap": "Switch or try a different model or brain, e.g. switch to Kimi, use the local brain",
    "dial_now": "Place a phone call right now to a person or business",
    "standing_order": "A rule for later, e.g. only ring me if something urgent happens; not an action now",
    "remember": "Remember or note something about him or capture a new note into the brain",
    "reflex": "About the reflex layer itself: show or hide the reflexes, turn them on or off, their cost, filming mode, the last reflex, show or test the judge, or asking it to triage or score the desk, inbox, cards, or comments",
    "none": "None of these lanes fits",
}

# ---------------------------------------------------------------- the STT-proof shortlist
# 2026-09-22 (his report: "Jarvis can't find nodes that exist"): the recogniser wrote "side view"
# for CiteVue, the keyword shortlist never held the CiteVue notes, and Jev honestly said "not in
# these notes". Fix = a phonetic fuzzy match of every 1-3 word gram of the question against node
# labels, put in FRONT of the keyword shortlist, and the matched labels handed to Jev + the brain.
FUZZY_MIN = 0.80          # compact-string ratio that alone counts as a hit
SKELETON_MIN = 0.85       # consonant-skeleton ratio (d/t, v/f, c/k folded) + a loose compact floor
SKELETON_COMPACT_MIN = 0.50
SKELETON_MAX_LEN_DIFF = 2
WAKE_RE = re.compile(r"^\s*(?:hey |okay |ok )?(?:jarvis|jervis|travis|jarvus|jarves|jarvi|charvis|jarvish)(?:\s+a\.?\s?i\.?)?[\s,.]*", re.I)   # S25d: STT wrote "Travis" and it became a label
FUZZY_MAX_HITS = 8
_GROUP = str.maketrans({"b": "p", "d": "t", "g": "k", "c": "k", "q": "k", "v": "f", "z": "s", "x": "s", "w": "u", "y": "i", "j": "k"})
def _compact(t): return re.sub(r"[^a-z0-9]", "", re.sub(r"c(?=[eiy])", "s", t.lower()))   # soft c: cite → site
def _skel(t):
    t = _compact(t).translate(_GROUP)
    if not t: return ""
    return t[0] + re.sub(r"[aeiou]", "", t[1:])
def _label_forms(label):
    forms = {_compact(label)}
    for part in re.split(r"[—–\-:·|/(]", label):
        forms.add(_compact(part))
    return {f for f in forms if len(f) >= 4}
COMMON = set("what is does it and the a an of to for in on my your his about tell me how do did who where when why which can could would should open show find give get charge charges cost costs price pricing note notes node nodes says say said with from that this these those there here have has had was were are be been being been just also very much many some any all up down out over into".split())
NAME_GROUPS = ("hub", "project", "concept", "world", "core", "router", "suite")   # skills/tools/EXTERNAL never rewrite a question (S25d: "Travis" → "reputation-reviews" repo)
_SPANS = {}
def fuzzy_hits(question, limit=FUZZY_MAX_HITS):
    """Nodes whose label sounds like a 1-3 word gram of the question. Deterministic, ~ms."""
    try:
        corpus = CTX["corpus"]() if callable(CTX.get("corpus")) else []
    except Exception:
        corpus = []
    words = [w for w in re.findall(r"[a-z0-9]+", WAKE_RE.sub("", question).lower()) if w not in ("jarvis", "jervis")]
    grams = {}                                            # compact gram -> (word index, word count)
    for n in (1, 2, 3):
        for i in range(len(words) - n + 1):
            g = _compact("".join(words[i:i + n]))                       # S25c: grams get the SAME soft-c fold as labels ("is citevue" no longer out-scores "citevue")
            if all(w in COMMON for w in words[i:i + n]): continue      # "does it" must never become a name
            if len(g) >= 5 and g not in grams: grams[g] = (i, n)
    if not grams: return [], []
    gsk = {g: _skel(g) for g in grams}
    hits = []
    _SPANS.clear()
    for node in corpus:
        best = 0.0; best_g = None
        for form in _label_forms(node.get("label") or ""):
            fsk = _skel(form)
            for g in grams:
                if g == form:
                    r = 1.0                                          # the whole gram IS the label ("aiworkshop")
                elif len(g) >= 6 and (g in form or (form in g and len(form) >= max(6, 0.7 * len(g)))):
                    r = 0.98 * min(len(g), len(form)) / max(len(g), len(form))   # containment, weighted by coverage (S25d: "community" alone must not out-score "free school community")
                    if r < FUZZY_MIN: r = 0.0
                else:
                    c = difflib.SequenceMatcher(None, g, form).ratio()
                    r = c if c >= FUZZY_MIN else (c if (len(fsk) >= 3 and abs(len(g) - len(form)) <= SKELETON_MAX_LEN_DIFF and gsk[g][:1] == fsk[:1]   # S25d: same first letter ("trfs" vs "rfs" was a hit)
                                                       and difflib.SequenceMatcher(None, gsk[g], fsk).ratio() >= SKELETON_MIN and c >= SKELETON_COMPACT_MIN) else 0.0)
                    if r and r < FUZZY_MIN: r = FUZZY_MIN   # skeleton match counts as a hit
                if r > best or (r == best and best_g is not None and grams[g][1] < grams[best_g][1]): best = r; best_g = g   # ties → the shorter gram (fewer words)
        if best >= FUZZY_MIN:
            hits.append((best, node))
            span = grams[best_g]; lab = re.split(r"\s*[—–]\s*", node.get("label") or "")[0].strip()
            if lab and node.get("g") in NAME_GROUPS and (span not in _SPANS or len(lab) < len(_SPANS[span])): _SPANS[span] = lab   # only real names rewrite the question
    hits.sort(key=lambda x: -x[0])
    top = [n for _, n in hits[:limit]]
    labels = []
    for n in top:
        if n.get("label") and n["label"] not in labels: labels.append(n["label"])
    return top, labels

def correct_question(question):
    """Rewrite the transcribed words that sound like a node label AS that label ("side view" → "CiteVue")."""
    words = [w for w in re.findall(r"[a-z0-9']+", WAKE_RE.sub("", question).lower()) if w not in ("jarvis", "jervis")]
    if not _SPANS: return question
    out = []; i = 0
    spans = sorted(_SPANS.items(), key=lambda kv: (kv[0][0], -kv[0][1]))   # S25d: at one start, the LONGER span wins ("free school community" over "school")
    while i < len(words):
        hit = next((kv for kv in spans if kv[0][0] == i), None)
        if hit: out.append(hit[1]); i += hit[0][1]
        else: out.append(words[i]); i += 1
    return " ".join(out)

def shortlist(question, k=40):
    """Fuzzy label hits FIRST, then the keyword shortlist on the CORRECTED question.
    Returns (notes, likely_labels, corrected_question)."""
    fz, labels = fuzzy_hits(question)
    corrected = correct_question(question) if labels else question
    rt = CTX.get("retrieve")
    notes, top = rt(corrected, k=k) if rt else ([], 0)
    seen = {n.get("_idx") for n in fz}
    merged = fz + [n for n in notes if n.get("_idx") not in seen]
    return merged[:k], labels, corrected

_VOCAB = {"t": 0, "v": []}
def vocabulary():
    """The names Jev could never know are HIS: hub/project/concept/world node labels from the corpus (cached 5 min)."""
    if time.time() - _VOCAB["t"] < 300 and _VOCAB["v"]:
        return _VOCAB["v"]
    try:
        corpus = CTX["corpus"]() if callable(CTX.get("corpus")) else []
        labels = sorted({(n.get("label") or "").strip() for n in corpus if n.get("g") in ("hub", "project", "concept", "world", "core", "router")} - {""}, key=len)
        _VOCAB.update(t=time.time(), v=labels[:48])
    except Exception:
        pass
    return _VOCAB["v"]

def prepass_questions(recording_mode=False):
    q = {
        "lane": {"type": "choice", "instructions": "Which lane should this spoken utterance to the voice assistant Jarvis take?",
                 "criteria": LANES},
        "complete": {"type": "noul", "instructions": "Has the speaker finished saying a complete request, so the assistant should act now rather than wait for more words?",
                     "criteria": {"true": "The request has a verb and its object; nothing is dangling", "false": "It ends mid-thought or on a connector like for, to, and, the, if"}},
        "addressed": {"type": "noul", "instructions": "Is `utterance` a request or question directed at the voice assistant, rather than narration to an audience, talking to another person, reading aloud, or thinking out loud?"},
        "destructive": {"type": "noul", "instructions": "Would acting on this send a message, place a call, delete something, post publicly, or spend money?"},
        "urgent": {"type": "noul", "instructions": "Does this need action within the hour?",
                   "criteria": {"true": "Money, an outage, or people are being hurt right now, or a hard deadline is inside the hour", "false": "It can wait until the next work block without harm"}},
    }
    if recording_mode:
        q["narrating"] = {"type": "noul", "instructions": "Is the speaker talking to a camera or an audience of viewers, explaining or presenting, rather than to the assistant?"}
    return q

def prepass(text, ctx=None):
    ctx = ctx or {}
    recording = bool(ctx.get("recording_mode") or STATE["filming"])
    state = {"utterance": text, "partial_transcript": bool(ctx.get("partial")), "recording_mode": recording,
             "his_vocabulary": vocabulary(),
             "likely_names_meant": fuzzy_hits(text)[1],
             "assistant_is_speaking": bool(ctx.get("tts_playing")),
             "gaze": ctx.get("gaze") or "unknown",                       # "screen" | "camera" | "away" | "unknown"
             "seconds_since_last_exchange": ctx.get("since_last"),
             "previous_exchange": (ctx.get("last") or "")[:300]}
    r = ask(state, prepass_questions(recording), "prepass",
            extra={"text": text[:200], "partial": bool(ctx.get("partial")), "recording": recording})
    if not r:
        return None
    a = r["answers"]; lane = a.get("lane") or {}
    conf = float(lane.get("confidence") or 0.0); choice = lane.get("choice") or "none"
    complete, addressed, destr, urgent = _noul(a, "complete"), _noul(a, "addressed"), _noul(a, "destructive"), _noul(a, "urgent")
    narrating = _noul(a, "narrating") if recording else 0.0
    need = ADDRESSED_FILMING if recording else ADDRESSED_ROOM
    decision = {
        "lane": choice, "confidence": round(conf, 3),
        "trust_lane": conf >= LANE_ACT and choice != "none",
        "peek_vault": choice == "vault_question" and conf >= LANE_PEEK,     # read-only recall may start on a partial
        "clarify": conf < LANE_CLARIFY,
        "fire_early": complete >= COMPLETE_FIRE and conf >= LANE_ACT and destr < DESTRUCTIVE_CONFIRM and choice not in ("none", "dial_now", "agent_task"),
        "addressed_ok": addressed >= need and narrating < NARRATING_QUIET,
        "narrating": round(narrating, 3),
        "needs_confirm": destr >= DESTRUCTIVE_CONFIRM,
        "recording_mode": recording,
        "gates": {"lane_act": LANE_ACT, "lane_peek": LANE_PEEK, "complete_fire": COMPLETE_FIRE, "addressed": need, "narrating_quiet": NARRATING_QUIET, "destructive": DESTRUCTIVE_CONFIRM},
    }
    r["decision"] = decision
    return r

# ------------------------------------------------------------------------------------ recall
EXT_LEVELS = ["None of the notes are relevant to the question",
              "Only the top note is relevant",
              "The top two or three notes are relevant",
              "About half of the list is relevant",
              "Most of the list is relevant"]

def recall(question, notes, likely=None):
    """notes: [{_idx, label, p}] (fuzzy hits + keyword shortlist, ≤ 40). One call: answerability + extent + per-note."""
    notes = [n for n in (notes or []) if n.get("p")][:40]
    if not notes:
        return None
    state = {"question": question,
             "speech_to_text_note": "names in `question` were corrected from speech; `likely_names_meant` are the vault's own names",
             "likely_names_meant": likely or [],
             "notes": [{"k": i, "title": n.get("label", ""), "excerpt": (n.get("p") or "")[:600]} for i, n in enumerate(notes)]}
    qs = {"has": {"type": "noul", "instructions": "Does at least one of the notes in `notes` directly contain the answer to `question`?",
                  "criteria": {"true": "A note states the specific fact, decision, number, or plan being asked about", "false": "The notes are only on a similar topic, or none address it"}},
          "names": {"type": "noul", "instructions": "Is `question` a request to open, show, pull up, find, or go to one of the notes in `notes` by its name (see `likely_names_meant`), rather than a question that needs a fact?"},
          "ext": {"type": "score", "instructions": "How far down the list `notes` (ordered by keyword match) does genuine relevance to `question` extend?",
                  "criteria": EXT_LEVELS}}
    for i in range(len(notes)):
        qs["n%d" % i] = {"type": "noul", "instructions": "Would a correct answer to `question` draw on `notes[%d]`? Lean inclusive: a note that supplies context the answer would mention counts." % i}
    r = ask(state, qs, "recall", deadline=RECALL_DEADLINE_S, extra={"question": question[:200], "n_notes": len(notes)})
    if not r:
        return None
    a = r["answers"]
    has = _noul(a, "has"); names = _noul(a, "names")
    try: ext = float(a["ext"]["score"])
    except Exception: ext = 0.0
    probs = sorted(((notes[i]["_idx"], round(_noul(a, "n%d" % i), 3)) for i in range(len(notes))), key=lambda x: -x[1])
    cap = {0: 0, 1: 1, 2: 3, 3: max(3, len(notes) // 2), 4: len(notes)}[min(4, max(0, int(round(ext))))]
    named = names >= NAMED_OPEN and bool(probs) and probs[0][1] >= NOTE_KEEP and has < FOUND   # S25d: "pull up X" — the note is the answer
    keep = [i for i, p in probs if p >= NOTE_KEEP][:max(cap, 1 if (has >= FOUND or named) else 0)]
    if named: keep = keep[:3] or [probs[0][0]]
    verdict = "found" if (has >= FOUND or named) else ("absent" if has < ABSENT else "unsure")
    r.update({"has": round(has, 3), "names": round(names, 3), "named": named, "ext": round(ext, 2), "probs": probs[:40], "keep": keep, "verdict": verdict, "likely": likely or [],
              "gates": {"found": FOUND, "absent": ABSENT, "note_keep": NOTE_KEEP, "named_open": NAMED_OPEN}})
    return r

# ------------------------------------------------------------------------------------- judge
CORRECTION = ("I nearly told you that was done, sir, and there is no receipt for it. "
              "Nothing has been sent, booked, or posted this turn. Shall I actually do it?")

def judge(question, answer, receipts=None):
    """Block a spoken answer that claims an action the tools never performed (never-fabricate law)."""
    receipts = receipts or []
    state = {"question": question, "answer": answer, "tool_receipts_this_turn": receipts or "none"}
    qs = {"claims": {"type": "noul", "instructions": "Does `answer` state that the assistant has just PERFORMED an action with an outside effect this turn: sent an email or message, placed a call, booked something, posted, scheduled, paid, or deleted?",
                     "criteria": {"true": "It reports the action as done, e.g. I've sent it, booked, dialing now", "false": "It offers, asks, drafts, describes notes, or talks about the future or the past"}},
          "backed": {"type": "noul", "instructions": "Is every action claimed in `answer` supported by an entry in `tool_receipts_this_turn`?"},
          "answers": {"type": "noul", "instructions": "Does `answer` address what `question` asked?"}}
    r = ask(state, qs, "judge", extra={"answer": answer[:200]})
    if not r:
        return None
    a = r["answers"]
    claims, backed, ans_ok = _noul(a, "claims"), _noul(a, "backed"), _noul(a, "answers")
    blocked = claims >= CLAIM and backed < BACKED and not receipts
    r.update({"claims": round(claims, 3), "backed": round(backed, 3), "answers_q": round(ans_ok, 3),
              "blocked": blocked, "original": answer if blocked else None, "line": CORRECTION if blocked else None,
              "gates": {"claim": CLAIM, "backed": BACKED}})
    return r

# ------------------------------------------------------------------------------------ triage
KINDS = {"question": "Asks for help, an explanation, or how to do something",
         "lead": "Wants to buy, join, hire, sponsor, or work with him",
         "praise": "Thanks, compliments, or excitement with nothing to act on",
         "complaint": "Something is broken, wrong, or they are unhappy",
         "spam": "Promotion, phishing, bots, or irrelevant noise",
         "other": "None of the above"}

def _triage_chunk(items):
    state = {"items": [{"k": i, "from": (it.get("from") or it.get("source") or "")[:80], "text": (it.get("text") or "")[:500]} for i, it in enumerate(items)]}
    qs = {}
    for i in range(len(items)):
        qs["kind%d" % i] = {"type": "choice", "instructions": "What kind of message is `items[%d]`?" % i, "criteria": KINDS}
        qs["reply%d" % i] = {"type": "noul", "instructions": "Does `items[%d]` need a personal reply from him?" % i}
        qs["urgent%d" % i] = {"type": "noul", "instructions": "Does `items[%d]` need attention within the hour?" % i}
    r = ask(state, qs, "triage", deadline=TRIAGE_DEADLINE_S)
    out = []
    for i, it in enumerate(items):
        if not r:
            out.append({"id": it.get("id"), "error": "reflex unavailable"}); continue
        a = r["answers"]; kind = a.get("kind%d" % i) or {}
        out.append({"id": it.get("id"), "kind": kind.get("choice") or "other", "kind_conf": round(float(kind.get("confidence") or 0), 3),
                    "reply": round(_noul(a, "reply%d" % i), 3), "urgent": round(_noul(a, "urgent%d" % i), 3)})
    return out, (r or {})

def triage(items):
    items = [it for it in (items or []) if (it.get("text") or "").strip()][:400]
    if not items:
        return {"items": [], "top": [], "ms": 0, "cost": 0.0, "tokens": 0}
    chunks = [items[i:i + TRIAGE_CHUNK] for i in range(0, len(items), TRIAGE_CHUNK)]
    t0 = time.perf_counter(); results = []; tokens = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=TRIAGE_WORKERS) as ex:
        for out, r in ex.map(_triage_chunk, chunks):
            results.extend(out); tokens += int(r.get("tokens") or 0)
    ms = round((time.perf_counter() - t0) * 1000)
    # policy in code: what deserves his attention first
    scored = [x for x in results if "kind" in x]
    for x in scored:
        x["attention"] = round((x["reply"] * 0.6 + x["urgent"] * 0.4) * (1.25 if x["kind"] in ("lead", "complaint") else 0.15 if x["kind"] == "spam" else 1.0), 3)
    top = [x["id"] for x in sorted(scored, key=lambda x: -x["attention"])[:3]]
    return {"items": results, "top": top, "ms": ms, "tokens": tokens, "cost": round(tokens / 1e6 * PRICE_PER_MTOK, 6), "n": len(items)}

# ---------------------------------------------------------------------------------- governor
GOV_Q = {
    "money":   "Does `card` involve money moving, owed, paid, declined, refunded, or being asked for?",
    "waiting": "Is a real person waiting on him right now for a reply, a call back, or a decision?",
    "time":    "Would waiting until his next work block cause harm or loss, so it needs him within the hour?",
    "broken":  "Does `card` report something broken, failed, dead, declined, expired, or unavailable?",
    "routine": "Is `card` a routine confirmation, status report, or summary of something already handled, with nothing for him to do now?",
    "lead":    "Does `card` come from someone who wants to buy, hire, sponsor, license, partner with, or pay him?",
    "noise":   "Is `card` spam, a promotion, a bot, engagement bait, or content-free noise like 'first' or fire emojis?",
}
def _gov_state(card, dnd=None):
    dnd = dnd or {}
    return {"title": (card.get("title") or "")[:160], "body": (card.get("body") or "")[:700], "source": card.get("source") or "",
            "priority": card.get("priority") or "normal", "local_hour": time.localtime().tm_hour,
            "he_is_in_focus": bool(dnd.get("focus")), "quiet_hours_now": bool(dnd.get("quiet"))}

def gov_score(nouls, priority):
    sc = GOV_BASE.get((priority or "normal").lower(), 0.15) + sum(GOV_W[k] * float(nouls.get(k, 0.0)) for k in GOV_W)
    return round(max(0.0, min(1.0, sc)), 3)

def gov_ladder(priority, dnd, money, score):
    """THE LADDER, in code (the same shape as today's should_speak): money always breaks through → focus/DND → quiet hours → priority.
    `money` is a bool (regex today, the noul when live); `score` is None (old path) or the situational score."""
    pr = (priority or "normal").lower(); rules = (dnd or {}).get("rules") or {}
    if pr == "high" and money and rules.get("money", "always") == "always": return True
    urgent = pr == "high" or (score is not None and score >= GOV_URGENT)
    if (dnd or {}).get("focus") or time.time() < ((dnd or {}).get("mute_until") or 0): return urgent
    if (dnd or {}).get("quiet"): return urgent
    if score is None: return pr in ("normal", "high")
    return pr == "high" or (pr == "normal" and score >= GOV_SPEAK)

def govern(card, dnd=None, old=None):
    """One card → atomic nouls + situational score + the ladder's verdict. Logs old-vs-gov. Returns dict or None (never raises)."""
    if not enabled() or GOVERNOR_MODE == "off": return None
    qs = {k: {"type": "noul", "instructions": v} for k, v in GOV_Q.items()}
    r = ask(_gov_state(card, dnd), qs, "govern", log=False)
    if not r: return None
    n = {k: round(_noul(r["answers"], k), 3) for k in GOV_Q}
    score = gov_score(n, card.get("priority"))
    speak = gov_ladder(card.get("priority"), dnd, n["money"] >= GOV_MONEY, score)
    out = {"nouls": n, "score": score, "speak": speak, "old": old, "mode": GOVERNOR_MODE, "ms": r["ms"], "tokens": r["tokens"], "cost": r["cost"],
           "gates": {"speak": GOV_SPEAK, "urgent": GOV_URGENT, "money": GOV_MONEY}}
    with _LOCK:
        STATE["gov_scored"] += 1
        if old is not None and bool(old) == bool(speak): STATE["gov_agree"] += 1
    _log({"ts": round(time.time(), 3), "purpose": "govern", "model": r["model"], "qv": QUESTION_VERSION, "ms": r["ms"], "tokens": r["tokens"],
          "title": (card.get("title") or "")[:100], "source": card.get("source"), "priority": card.get("priority"), "answers": r["answers"],
          "score": score, "gov": speak, "old": old, "mode": GOVERNOR_MODE})
    return out

def govern_batch(cards, dnd=None, olds=None):
    """Receipts: score many cards in 40-card calls (same nouls, k-indexed like triage). Returns a list aligned with `cards` (None where unavailable)."""
    cards = list(cards or []); olds = olds or [None] * len(cards); out = [None] * len(cards)
    for start in range(0, len(cards), GOV_CHUNK):
        chunk = cards[start:start + GOV_CHUNK]
        state = {"cards": [dict(_gov_state(c, dnd), k=i) for i, c in enumerate(chunk)], "he_is_in_focus": bool((dnd or {}).get("focus")), "quiet_hours_now": bool((dnd or {}).get("quiet"))}
        qs = {}
        for i in range(len(chunk)):
            for k, v in GOV_Q.items():
                qs["%s%d" % (k, i)] = {"type": "noul", "instructions": v.replace("`card`", "`cards[%d]`" % i)}
        r = ask(state, qs, "govern_batch", deadline=TRIAGE_DEADLINE_S, log=False)
        if not r: continue
        for i, c in enumerate(chunk):
            n = {k: round(_noul(r["answers"], "%s%d" % (k, i)), 3) for k in GOV_Q}
            score = gov_score(n, c.get("priority")); speak = gov_ladder(c.get("priority"), dnd, n["money"] >= GOV_MONEY, score)
            out[start + i] = {"nouls": n, "score": score, "speak": speak, "old": olds[start + i], "ms": r["ms"], "tokens": r["tokens"]}
    return out

# -------------------------------------------------------------------------------------- diag
def _pct(xs, q):
    if not xs: return None
    s = sorted(xs); return s[min(len(s) - 1, int(q * (len(s) - 1)))]

def diag():
    return {"on": STATE["on"], "enabled": enabled(), "key_present": bool(_key()), "model": model(),
            "filming": STATE["filming"], "day": STATE["day"], "calls_today": STATE["calls"], "tokens_today": STATE["tokens"],
            "cost_today": round(STATE["cost"], 6), "p50_ms": _pct(STATE["ms"], .5), "p95_ms": _pct(STATE["ms"], .95),
            "last_error": STATE["last_error"], "question_version": QUESTION_VERSION,
            "governor": {"mode": GOVERNOR_MODE, "scored": STATE["gov_scored"], "agree": STATE["gov_agree"],
                         "gates": {"speak": GOV_SPEAK, "urgent": GOV_URGENT, "money": GOV_MONEY}, "weights": GOV_W, "base": GOV_BASE},
            "gates": {"lane_act": LANE_ACT, "lane_peek": LANE_PEEK, "lane_clarify": LANE_CLARIFY, "complete_fire": COMPLETE_FIRE, "named_open": NAMED_OPEN,
                      "addressed_room": ADDRESSED_ROOM, "addressed_filming": ADDRESSED_FILMING, "narrating_quiet": NARRATING_QUIET,
                      "destructive_confirm": DESTRUCTIVE_CONFIRM, "found": FOUND, "absent": ABSENT,
                      "note_keep": NOTE_KEEP, "claim": CLAIM, "backed": BACKED}}

def last_log(n=1):
    try:
        with open(LOG_FILE) as f: lines = f.readlines()[-max(1, min(int(n), 20)):]
        return [json.loads(l) for l in lines]
    except Exception:
        return []

def set_last(sid, payload):
    LAST[sid or "_"] = payload

def pop_last(sid):
    return LAST.pop(sid or "_", None)

# ------------------------------------------------------------------------------------ routes
def handle(handler, method, raw_path, p):
    path = raw_path.split("?")[0]
    if not path.startswith("/reflex"):
        return False
    if method == "GET":
        if path == "/reflex/diag":
            handler._json(diag()); return True
        if path == "/reflex/log":
            q = raw_path.split("?", 1)[1] if "?" in raw_path else ""
            n = 1
            for kv in q.split("&"):
                if kv.startswith("n="):
                    try: n = int(kv[2:])
                    except ValueError: pass
            handler._json({"log": last_log(n)}); return True
        return False
    if path == "/reflex/toggle":
        if "on" in p: STATE["on"] = bool(p.get("on"))
        if "filming" in p: STATE["filming"] = bool(p.get("filming"))
        _save_state(); handler._json(diag()); return True
    if not enabled():
        handler._json({"error": "reflex off" if not STATE["on"] else "no TypeSafe key", "diag": diag()}, 503); return True
    if path == "/reflex/prepass":
        text = (p.get("text") or "").strip()[:2000]
        if not text: handler._json({"error": "empty"}, 400); return True
        r = prepass(text, p.get("ctx") or {})
        handler._json(r or {"error": "reflex timeout", "diag": diag()}, 200 if r else 504); return True
    if path == "/reflex/recall":
        q = (p.get("question") or "").strip()[:1000]
        rt = CTX.get("retrieve")
        if not q or not rt: handler._json({"error": "empty"}, 400); return True
        notes, likely, q2 = shortlist(q, k=40)
        r = recall(q2, notes, likely)
        if r: r["corrected"] = q2
        if r: set_last(p.get("session"), {"recall": {k: r.get(k) for k in ("has", "names", "named", "ext", "probs", "keep", "verdict", "ms", "tokens", "cost", "model", "likely", "corrected")}})
        handler._json(r or {"error": "reflex timeout", "diag": diag()}, 200 if r else 504); return True
    if path == "/reflex/judge":
        r = judge((p.get("question") or "")[:1000], (p.get("answer") or "")[:2000], p.get("receipts") or [])
        handler._json(r or {"error": "reflex timeout"}, 200 if r else 504); return True
    if path == "/reflex/triage":
        handler._json(triage(p.get("items") or [])); return True
    if path == "/reflex/govern":                          # S25c: score one card (receipts, preflight); never raises a real card
        c = p.get("card") or {}
        if not (c.get("title") or c.get("body")): handler._json({"error": "empty card"}, 400); return True
        g = govern(c, p.get("dnd") or {}, p.get("old"))
        handler._json(g or {"error": "reflex timeout", "diag": diag()}, 200 if g else 504); return True
    return False

_load_state()
