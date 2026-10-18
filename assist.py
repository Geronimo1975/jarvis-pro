"""Jarvis ASSIST — the second-brain organs behind every surface (2026-07-27).

What it gives the desk, the hotline, and Telegram alike:
- EXTRACTION: any free-form text (a hotline transcript, a rambling voice note) → durable
  objects — notes into the graph, reminders, tasks — executed through the SAME control-tag
  machinery the desk uses, plus a capture ledger for the morning digest.
- OPEN-LOOP LEDGER: every promise ("I'll call you right back", "check with my boss") becomes
  a tracked loop that ages, gets surfaced in briefings, and closes when the follow-up happens.
- PEOPLE MEMORY: calls and mentions accumulate per-person history — "what's my history with X".
- EPISODE SEARCH: the full activity log, keyword-searchable from any surface.

Plug-in bay contract: server.py soft-imports `assist as ASSIST`, calls init() with
apply_tag / raise_card / log / cfg / root, and routes /assist* through handle(). The calls and
pocket bays receive its functions via their own CTX injections. A broken assist bay can never
hurt the core. State: jarvis-captures.jsonl, jarvis-loops.json, jarvis-people.jsonl (gitignored).
"""
import json, os, re, threading, time, urllib.request

CTX = {}                     # init(): apply_tag, raise_card, log, cfg, root
LOCK = threading.Lock()

def _f(name):
    return os.path.join(CTX.get("root") or os.path.dirname(os.path.abspath(__file__)), name)

# ---------------------------------------------------------------- fast model helper
def _fast(system, user, max_tokens=400):
    key = ((CTX.get("cfg") or {}).get("model") or {}).get("api_key") or ""
    if not key:
        return None
    try:
        body = {"model": "claude-haiku-4-5-20251001", "max_tokens": max_tokens,
                "system": system, "messages": [{"role": "user", "content": user}]}
        req = urllib.request.Request("https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode(),
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.load(r)
        return "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text").strip()
    except Exception:
        return None

def _jsonish(txt):
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}

# ---------------------------------------------------------------- capture ledger + digest
def _log_capture(kind, text, where, source):
    try:
        with open(_f("jarvis-captures.jsonl"), "a") as f:
            f.write(json.dumps({"ts": int(time.time()), "kind": kind, "text": text[:200],
                                "where": where[:80], "source": source}) + "\n")
    except Exception:
        pass

def digest_recent(hours=26):
    """'You captured six thoughts yesterday: three filed to CiteVue…' — for the briefing."""
    cutoff = time.time() - hours * 3600
    rows = []
    try:
        for line in open(_f("jarvis-captures.jsonl")).read().strip().splitlines()[-200:]:
            try:
                r = json.loads(line)
                if r.get("ts", 0) >= cutoff:
                    rows.append(r)
            except Exception:
                continue
    except Exception:
        pass
    if not rows:
        return ""
    by_kind = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)
    bits = []
    for kind, items in by_kind.items():
        wheres = sorted({i["where"] for i in items if i.get("where")})
        bits.append(f"{len(items)} {kind}{'s' if len(items) > 1 else ''}"
                    + (f" (→ {', '.join(wheres[:3])})" if wheres else ""))
    return f"Captured since yesterday: {'; '.join(bits)}."

# ---------------------------------------------------------------- extraction → durable objects
_EXTRACT_SYS = """You extract DURABLE items from a snippet of George talking to (or through) his
assistant. Return STRICT JSON ONLY:
{"notes":[{"topic":"<short note text, third person>","related":"<existing project/thing it belongs
to, or empty>"}],"reminders":[{"text":"...","when":"<their phrasing, or empty>"}],
"tasks":["..."],"loops":[{"text":"<an open promise/follow-up someone must close>"}],
"people":[{"name":"...","context":"<one line>"}],
"deals":[{"kind":"<proposal|invoice|quote>","brief":"<one line: who it's for, what's included,
amounts if he said them>"}]}
Rules: EMPTY lists when nothing qualifies — questions, chit-chat, and commands to call/book are
NOT captures. A "note" is substance worth keeping (an idea, a fact, a decision). A "loop" is an
unclosed commitment ("I'll call them back", "waiting on X", "need to check with Y") — a REQUEST
for a document ("create a quote for X") is a command, NEVER a loop, note, or task. A "deal"
ONLY when he explicitly asks for a proposal/invoice/quote/estimate to be created. Keep each
item under 20 words. Never invent."""

def extract_and_file(text, source="desk", sid=None, allow_deals=True):
    """Free text → filed objects via the desk's own tag machinery. Returns a filed-summary
    string ('filed: note → CiteVue, reminder Thursday') or '' when nothing qualified.
    allow_deals=False for text an UNAUTHENTICATED speaker authored (receptionist callers)."""
    text = (text or "").strip()
    if len(text) < 12:
        return ""
    d = _jsonish(_fast(_EXTRACT_SYS, text[:4000]))
    if not d:
        return ""
    apply_tag = CTX.get("apply_tag")
    filed = []
    for n in (d.get("notes") or [])[:4]:
        topic = (n.get("topic") or "").strip()
        if not topic:
            continue
        rel = (n.get("related") or "").strip()
        if apply_tag:
            try:
                apply_tag(f"[NODE:{topic}" + (f"|{rel}]" if rel else "]"), sid)
            except Exception:
                continue
        _log_capture("note", topic, rel or "graph", source)
        filed.append(f"note → {rel or 'the graph'}")
    for r in (d.get("reminders") or [])[:3]:
        t = (r.get("text") or "").strip()
        if not t:
            continue
        when = (r.get("when") or "").strip()
        if apply_tag:
            try:
                apply_tag(f"[REMIND:{t}" + (f"|{when}]" if when else "]"), sid)
            except Exception:
                continue
        _log_capture("reminder", t, when or "sometime", source)
        filed.append("reminder" + (f" {when}" if when else ""))
    for t in (d.get("tasks") or [])[:3]:
        t = str(t).strip()
        if not t:
            continue
        if apply_tag:
            try:
                apply_tag(f"[REMIND:{t}]", sid)
            except Exception:
                continue
        _log_capture("task", t, "tasks", source)
        filed.append("task")
    for lp in (d.get("loops") or [])[:3]:
        t = (lp.get("text") or "").strip()
        if t:
            add_loop(t, source)
            filed.append("open loop")
    # deals fire ONLY where no tag machinery already ran (hotline transcripts): pocket's chat
    # brain owns [DEAL:] on Telegram — double-detection drafted duplicates (audit 2026-07-27;
    # 2026-07-28 LIVE: the guard checked "pocket" but the server lambda passes source="telegram",
    # so a voice note got BOTH the brain's clarifying question AND an instant extractor invoice).
    # And never off an unauthenticated caller's words (allow_deals=False on the stranger sweep).
    if allow_deals and str(source) not in ("telegram",) and not str(source).startswith("pocket"):
        for dl in (d.get("deals") or [])[:2]:
            brief = re.sub(r"[\[\]<>]", " ", (dl.get("brief") or "")).strip()[:300]
            if not brief:
                continue
            dkind = (dl.get("kind") or "proposal").strip().lower()
            fired = False
            if apply_tag:
                try:
                    # the desk's own [DEAL:] machinery — drafts the PDF, pushes to his phone.
                    # apply_control_tag signals refusal by RETURNING a dict, never raising —
                    # only a real "Drafting…" ack earns the filed receipt (house receipts law)
                    r = apply_tag(f"[DEAL:{dkind}|{brief}]", sid)
                    fired = bool(r) and (r.get("answer") or "").startswith("Drafting")
                except Exception:
                    continue
            if fired:
                _log_capture("deal", brief, dkind, source)
                filed.append(f"{dkind} → your phone")
    for p in (d.get("people") or [])[:4]:
        if (p.get("name") or "").strip():
            note_person(p["name"].strip(), (p.get("context") or "").strip(), source)
    return ("filed: " + ", ".join(filed)) if filed else ""

# ---------------------------------------------------------------- open-loop ledger
def _loops_load():
    try:
        return json.load(open(_f("jarvis-loops.json")))
    except Exception:
        return []

def _loops_save(loops):
    try:
        tmp = _f("jarvis-loops.json") + ".tmp"
        with open(tmp, "w") as f:
            json.dump(loops[-200:], f, indent=1)
        os.replace(tmp, _f("jarvis-loops.json"))
    except Exception:
        pass

def add_loop(text, source="desk"):
    text = (text or "").strip()
    if not text:
        return None
    with LOCK:
        loops = _loops_load()
        low = text.lower()
        for l in loops:                              # near-duplicate guard
            if l.get("status") == "open" and (low in l["text"].lower() or l["text"].lower() in low):
                return l["id"]
        lid = os.urandom(4).hex()
        loops.append({"id": lid, "ts": int(time.time()), "text": text[:160],
                      "source": source, "status": "open", "nagged": 0})
        _loops_save(loops)
    try:
        CTX.get("log", lambda *a: None)("loop", f"open: {text[:70]}")
    except Exception:
        pass
    return lid

def open_loops():
    return [l for l in _loops_load() if l.get("status") == "open"]

def close_loop(match):
    """Close the best keyword match. Returns the closed loop's text or None."""
    toks = [t for t in re.sub(r"[^a-z0-9 ]", " ", (match or "").lower()).split() if len(t) > 2]
    with LOCK:
        loops = _loops_load()
        best, score = None, 0
        for l in loops:
            if l.get("status") != "open":
                continue
            hay = l["text"].lower()
            s = sum(1 for t in toks if t in hay)
            if s > score:
                best, score = l, s
        if not best or score == 0:
            return None
        best["status"] = "closed"
        best["closed_ts"] = int(time.time())
        _loops_save(loops)
    return best["text"]

def auto_close_for_callee(callee):
    """A completed call to X closes 'call X back'-style loops on its own."""
    if not callee:
        return None
    return close_loop(f"call back {callee}")

def loop_digest(min_age_hours=4, limit=4):
    """'Two loops aging, sir: …' — for briefings and nags."""
    now = time.time()
    aged = [l for l in open_loops() if now - l["ts"] > min_age_hours * 3600]
    if not aged:
        return ""
    aged.sort(key=lambda l: l["ts"])
    lines = []
    for l in aged[:limit]:
        hrs = int((now - l["ts"]) / 3600)
        age = f"{hrs}h" if hrs < 48 else f"{hrs // 24}d"
        lines.append(f"{l['text']} ({age})")
    more = f" (+{len(aged) - limit} more)" if len(aged) > limit else ""
    return f"Open loops: {'; '.join(lines)}{more}."

# ---------------------------------------------------------------- people memory
def note_person(name, context, source="desk"):
    name = (name or "").strip()
    if len(name) < 2 or name.lower() in ("george", "jarvis", "sir"):
        return
    try:
        with open(_f("jarvis-people.jsonl"), "a") as f:
            f.write(json.dumps({"ts": int(time.time()), "name": name,
                                "context": (context or "")[:160], "source": source}) + "\n")
    except Exception:
        pass

def person_block(question):
    """History paragraphs for any person the question names. '' when none match."""
    try:
        rows = [json.loads(l) for l in open(_f("jarvis-people.jsonl")).read().strip().splitlines()[-500:]]
    except Exception:
        return ""
    q = (question or "").lower()
    names = {}
    for r in rows:
        if r["name"].lower() in q:
            names.setdefault(r["name"], []).append(r)
    out = []
    for name, hist in list(names.items())[:2]:
        hist.sort(key=lambda r: r["ts"], reverse=True)
        last = time.strftime("%b %d", time.localtime(hist[0]["ts"]))
        lines = "; ".join(h["context"] for h in hist[:5] if h.get("context"))
        out.append(f"PERSON {name} (last touch {last}): {lines}")
    return "\n".join(out)

# ---------------------------------------------------------------- episode search
def episode_search(q, days=365, limit=8):
    """Keyword search over the full activity log — 'when did I first work on X'."""
    toks = [t for t in re.sub(r"[^a-z0-9 ]", " ", (q or "").lower()).split() if len(t) > 2]
    if not toks:
        return []
    cutoff = time.time() - days * 86400
    hits = []
    try:
        for line in open(_f("jarvis-episodes.jsonl")).read().strip().splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("ts", 0) < cutoff:
                continue
            hay = (str(e.get("kind", "")) + " " + str(e.get("text", ""))).lower()
            if sum(1 for t in toks if t in hay) >= max(1, len(toks) // 2):
                hits.append(e)
    except Exception:
        pass
    first, last = hits[:limit // 2], hits[-(limit - limit // 2):] if len(hits) > limit // 2 else []
    seen, out = set(), []
    for e in first + last:
        k = e.get("ts")
        if k not in seen:
            seen.add(k)
            out.append(f"{time.strftime('%b %d %Y', time.localtime(e.get('ts', 0)))}: {e.get('text', '')[:120]}")
    return out

def assist_material(question):
    """Everything this bay knows that bears on a question — spliced into brain_answer."""
    parts = []
    pb = person_block(question)
    if pb:
        parts.append(pb)
    eps = episode_search(question, limit=6)
    if eps:
        parts.append("Activity log matches:\n" + "\n".join(f"- {e}" for e in eps))
    ld = loop_digest(min_age_hours=0)
    if ld and re.search(r"\b(open|loop|pending|waiting|outstanding|follow)\b", (question or "").lower()):
        parts.append(ld)
    return "\n\n".join(parts)

# ---------------------------------------------------------------- briefing decisions
_DECIDE_SYS = """A transcript of Jarvis's briefing phone call with his principal George follows.
Extract any DECISIONS George spoke. Return STRICT JSON ONLY:
{"callbacks":[{"callee":"<who to ring>","about":"<one line>"}],
 "close_loops":["<loop text to mark done>"],"tasks_done":["..."],"new_tasks":["..."]}
Empty lists when he decided nothing. Only what HE explicitly approved or ordered — never infer."""

def parse_decisions(transcript):
    d = _jsonish(_fast(_DECIDE_SYS, (transcript or "")[:6000]))
    return {"callbacks": d.get("callbacks") or [], "close_loops": d.get("close_loops") or [],
            "tasks_done": d.get("tasks_done") or [], "new_tasks": d.get("new_tasks") or []}

# ---------------------------------------------------------------- routes
def handle(handler, method, path, p):
    if method == "GET" and path == "/api/loops":
        handler._json({"open": open_loops()})
        return True
    if method != "POST" or not path.startswith("/assist"):
        return False
    if path == "/assist_loops":
        if p.get("close"):
            t = close_loop(p.get("close"))
            handler._json({"say": (f"Closed, sir — {t}." if t else "No open loop matches that, sir.")})
            return True
        ld = loop_digest(min_age_hours=0, limit=6)
        handler._json({"say": ld or "No open loops, sir — a clean slate."})
        return True
    if path == "/assist_recall":
        eps = episode_search(p.get("q") or "", limit=6)
        pb = person_block(p.get("q") or "")
        say = " … ".join(([pb] if pb else []) + eps) or "Nothing in the long log matches that, sir."
        handler._json({"say": say[:900]})
        return True
    return False

def init(ctx):
    CTX.update(ctx or {})
    print(f"[assist] second-brain organs online — {len(open_loops())} open loops")
