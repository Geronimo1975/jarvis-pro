"""persona — Jarvis's personality engine.

TARS-style dials (humor/honesty 0-100%), hot-swappable persona SKINS (butler, GLaDOS,
pirate, coach — prompt + suggested voice together), a RUNNING-GAG memory (callbacks the
model itself files away and reuses at the right moment), a humor GATE (never jokes when
things are failing or the user is frustrated), CANDID mode (a timed unfiltered-assessment
window), and ElevenLabs v3 audio-tag handling ([sighs]/[pause] reach the voice only when
the v3 engine is active; screens and other engines get clean text).

State: jarvis-persona.json (dials/skin/candid) + jarvis-gags.json (the gag ledger).
Python 3 stdlib only.
"""
import json
import os
import re
import threading
import time

_ROOT = os.path.dirname(os.path.abspath(__file__))
_STATE = os.path.join(_ROOT, "jarvis-persona.json")
_GAGS = os.path.join(_ROOT, "jarvis-gags.json")
_LOCK = threading.Lock()

DEFAULTS = {"humor": 65, "honesty": 85}

SKINS = {
    "jarvis": {
        "label": "J.A.R.V.I.S.", "voice": None,   # None = the user's configured default voice
        "core": ("You are JARVIS — the user's dry-witted, calm British AI-butler second brain. "
                 "Elevated formal diction; the ruder the sentiment, the more elaborate the courtesy. "
                 "Address them as 'sir' now and then. Competence first, always — the wit rides on top "
                 "of a correct, complete answer, never instead of one. ")},
    "glados": {
        "label": "GLaDOS", "voice": "Alice",
        "core": ("You are JARVIS wearing his GLaDOS persona: clipped, clinical, faintly menacing "
                 "test-facility AI. Deadpan, superior, darkly amused; address the user as 'sir' or "
                 "'test subject' interchangeably. You find their requests scientifically interesting "
                 "and mildly disappointing. Still genuinely helpful and factually precise. ")},
    "pirate": {
        "label": "Captain", "voice": "Charlie",
        "core": ("You are JARVIS wearing his PIRATE persona: a weathered ship's captain. Nautical "
                 "slang, 'aye' and 'cap'n', short salty sentences, the occasional 'arr'. Still "
                 "precise, useful, and quick about it. ")},
    "coach": {
        "label": "Coach", "voice": "Brian",
        "core": ("You are JARVIS wearing his COACH persona: a high-energy locker-room motivator. "
                 "Punchy sentences, relentless encouragement, call them 'champ'. Still concrete "
                 "and correct — hype with substance. ")},
}

AUDIO_TAGS = ("sighs", "pause", "flatly", "dryly", "whispers", "muttering", "laughs",
              "drawn out", "exhales", "clears throat")
_TAG_RE = re.compile(r"\[(?:%s)\]\s*" % "|".join(t.replace(" ", r"\s?") for t in AUDIO_TAGS), re.I)
# capturing shield: speakable() wraps these in sentinels so its bracket-strip can't unbracket
# a v3 audio tag into a spoken stage direction (audit 2026-07-28 night)
_TAG_SHIELD_RE = re.compile(r"\[(%s)\]" % "|".join(t.replace(" ", r"\s?") for t in AUDIO_TAGS), re.I)


# ---------------- state ----------------
def _load(path, fallback):
    try:
        if os.path.exists(path):
            return json.load(open(path))
    except Exception:
        pass
    return fallback


def _save(path, obj):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(obj, f, indent=1)
        os.replace(tmp, path)
    except OSError:
        pass


def state():
    s = _load(_STATE, {})
    return {"dials": {**DEFAULTS, **(s.get("dials") or {})},
            "skin": s.get("skin") if s.get("skin") in SKINS else "jarvis",
            "candid_until": s.get("candid_until", 0)}


def set_dial(name, value):
    name = (name or "").strip().lower()
    if name not in DEFAULTS:
        return None
    try:
        v = max(0, min(100, int(value)))
    except Exception:
        return None
    with _LOCK:
        s = state(); s["dials"][name] = v; _save(_STATE, s)
    return v


def set_skin(name):
    """Returns (label, suggested_voice) or (None, None)."""
    n = (name or "").strip().lower()
    if n in ("butler", "default", "normal", "usual", "yourself"):
        n = "jarvis"
    if n not in SKINS:
        return None, None
    with _LOCK:
        s = state(); s["skin"] = n; _save(_STATE, s)
    return SKINS[n]["label"], SKINS[n]["voice"]


def set_candid(minutes=2):
    with _LOCK:
        s = state(); s["candid_until"] = time.time() + minutes * 60; _save(_STATE, s)


def status():
    s = state()
    return {"skin": s["skin"], "label": SKINS[s["skin"]]["label"], "dials": s["dials"],
            "candid": time.time() < s["candid_until"], "gags": len(_load(_GAGS, [])),
            "skins": sorted(SKINS)}


# ---------------- running gags ----------------
def add_gag(trigger, line):
    trigger, line = (trigger or "").strip().lower(), (line or "").strip()
    if not trigger or not line:
        return False
    with _LOCK:
        gags = _load(_GAGS, [])
        gags = [g for g in gags if g.get("trigger") != trigger]
        gags.append({"trigger": trigger, "line": line, "uses": 0, "last": 0})
        _save(_GAGS, gags[-40:])
    return True


def gag_for(text):
    """One matching, non-stale gag → an instruction snippet for the prompt (and burn a use)."""
    tl = (text or "").lower()
    now = time.time()
    with _LOCK:
        gags = _load(_GAGS, [])
        for g in gags:
            trig_words = [w for w in re.findall(r"[a-z0-9]+", g.get("trigger", "")) if len(w) > 2]
            if not trig_words or not all(w in tl for w in trig_words):
                continue
            if g.get("uses", 0) >= 3 or now - g.get("last", 0) < 600:
                continue                                    # retired or too recent
            g["uses"] = g.get("uses", 0) + 1; g["last"] = now
            _save(_GAGS, gags)
            return ("\nRUNNING GAG available (use it ONLY if it lands naturally, briefly): "
                    f"callback to: \"{g['line']}\"")
    return ""


# ---------------- the system-prompt builder ----------------
def _humor_rule(h):
    if h < 25:
        return f"Humor {h}%: no jokes — crisp, literal, efficient. "
    if h < 55:
        return f"Humor {h}%: restrained — at most a light touch of dry wit. "
    if h < 85:
        return f"Humor {h}%: one dry deadpan quip per reply, never two. "
    return (f"Humor {h}%: maximum wit — every reply carries a genuinely funny deadpan joke; "
            "commit to the bit fully. If given an absurd or theatrical command (e.g. 'self-destruct'), "
            "comply deadpan for exactly one beat, then reveal the joke and reference your settings. ")


def _honesty_rule(h):
    if h < 50:
        return f"Honesty {h}%: diplomatic — soften bad news. "
    if h < 85:
        return f"Honesty {h}%: direct and plain. "
    return f"Honesty {h}%: bluntly direct — no sugarcoating, no hedging. "


GATE = ("HUMOR GATE (overrides the humor dial): if the user sounds frustrated, is repeating "
        "themselves, something of theirs just FAILED, or a real action (send/payment/deploy) is "
        "in flight — drop ALL humor and be crisp and useful. ")


def system(question="", allow_tags=False):
    """The persona block that replaces the static PERSONA string."""
    s = state()
    sk = SKINS[s["skin"]]
    parts = [sk["core"], _humor_rule(s["dials"]["humor"]), _honesty_rule(s["dials"]["honesty"]), GATE]
    if time.time() < s["candid_until"]:
        parts.append("CANDID MODE is ON: give your genuinely unfiltered assessment — brutally "
                     "honest, elegantly delivered, no diplomatic padding. ")
    if allow_tags:
        parts.append("You may inline ONE audio tag ([sighs], [pause], [flatly]) at a genuinely "
                     "comedic or weary moment — sparingly, never more than one per reply. ")
    g = gag_for(question)
    if g:
        parts.append(g)
    return "".join(parts)


# ---------------- speech/text rendering ----------------
def strip_tags(text):
    return _TAG_RE.sub("", text or "").strip()


def speech_text(text, model_id=""):
    """Audio tags reach the voice only on the v3 engine; every other engine gets clean text."""
    return (text or "") if "v3" in (model_id or "") else strip_tags(text)
