"""Jarvis V7 — FOCUS SESSIONS (the accountability timer). Session 19.

"Jarvis, thirty minutes on this" → the frontmost app AT THAT MOMENT becomes THE TARGET,
a countdown renders on the desktop face (facewin) + a HUD chip, and Jarvis calls him out
funny-dry when focus breaks: app-switch (NSWorkspace frontmost — public API, no TCC, no
pixels), face gone / phone head-down (EYES feed from the client). Grace before any callout,
escalating tiers, opt-in drill-sergeant voice, spoken report card + streak at the end,
logged as 'focus' episodes.

SECURITY LAWS (the selling point — enforced STRUCTURALLY here):
  1. compare-and-discard: the target bundle id lives ONLY in module-private _TARGET and the
     frontmost id ONLY in a local inside _poll_loop(); the ENGINE receives booleans, so no
     app identity can ever reach state payloads, logs, speech, or disk. Jarvis may say you
     LEFT — never where you WENT.
  2. NO window titles anywhere in this bay — app-level only keeps it permissionless.
  3. Disk stores aggregates only (jarvis-focus.json): minutes on target, drift count/seconds,
     streak — never a timeline of apps.
  4. ZERO-KEY PATH: detection is a local string compare + EYES booleans; every callout line
     ships in the canned pools below — the entire feature runs with NO API keys.
Known honest limit: app-level can't tell work-in-Chrome from YouTube-in-Chrome.

Verify: probe_battery() (hermetic, fake clock — served to the browser via POST /focus/probe
for the ?focusprobe=1 battery) + test_focus.py; preflight carries live focus entries.
"""
import hashlib, json, os, re, subprocess, threading, time

ROOT = os.path.dirname(os.path.abspath(__file__))
AGG_FILE = os.path.join(ROOT, "jarvis-focus.json")

# ---- named numbers (the field-tuning law: every threshold is one name) ----
GRACE_APP_MS = 800        # S19n ("immediately, every time"): app/tab switch confirmed in ~1-2s
                          # (still forgives a sub-second cmd-tab bounce)
GRACE_EYES_MS = 12000     # away/phone keep the long grace (glancing at a notification ≠ a drift)
CALLOUT_GAP_MS = 3000     # S19n: EVERY distinct drift speaks — this floor only guards true
                          # machine-gun flapping; the nag cadence owns a CONTINUING drift
EXCUSE_MAX_MS = 900000    # "it's okay, I'm doing research" forgives the CURRENT excursion this long
NAG_MS = 300000           # S19b: while ONE drift persists, keep speaking up on this cadence
                          # (his spec: "say something every five minutes if I'm not focusing";
                          #  voice-settable — "call me out every five seconds" for the demo)
NAG_MIN_S, NAG_MAX_S = 2, 3600   # S20: "check every two seconds after" — 2s is legal now
SNOOZE_MAX_S = 1800       # "give me N minutes" quiet window cap
TICK_S = 1.0              # server poll cadence (S19j: ~2s switch-to-callout wants a 1s heartbeat)
DT_CAP_MS = 5000          # per-tick elapsed clamp — a sleeping Mac must not "spend" the session
EYES_STALE_MS = 10000     # EYES feed older than this is ignored (fail-open, never false-accuse)
PAUSE_MAX_MS = 3600000    # a paused session forgotten for an hour quietly stands down
REPORT_TTL_MS = 600000    # an unclaimed report card survives a dead tab this long
CLEAN_PCT = 0.85          # a session at or above this on-target fraction extends the streak
DEFAULT_MIN = 30
MAX_MIN = 240
KEEP_SESSIONS = 60        # aggregate ledger depth

CTX = {"log": None, "facewin_send": None, "facewin_claim": None}

# ---------- the canned pools (LAW 4: the zero-key path IS the product) ----------
# kind: app = switched apps · away = left the desk · phone = head down in the phone
# tiers escalate with the session's drift count: dry → pointed → sharp.
LINES = {
    "app": [
        ["Sir, that isn't the thing. The thing is the other window.",
         "I don't know where you wandered off to, sir. Only that it wasn't here.",
         "A brief detour, I'm sure. The work sends its regards."],
        ["That's twice now, sir. The task is starting to take it personally.",
         "Back again, are we? The other window will survive without you — I've checked.",
         "Sir. The clock is still running, and it is not impressed."],
        ["Third time, sir. At this point the detours are the project.",
         "I could lock the door, sir, but I'm told that's 'a feature for later'. Back to it.",
         "The timer and I have started a betting pool on your return, sir. Don't make me lose."],
    ],
    "away": [
        ["The chair appears to have lost you, sir. It happens to the best of chairs.",
         "Gone, sir? The work remains heroically unfinished."],
        ["Still out there somewhere, sir. The desk grows sentimental.",
         "Second walkabout, sir. Hydration is noble; absence is a statistic now."],
        ["Sir, I'd send a search party, but I only have the one voice.",
         "The expedition continues, sir. I'll be here, guarding the minutes you left behind."],
    ],
    "phone": [
        ["The phone again, sir? It will say the same things in an hour, only louder.",
         "Head down, thumb moving. I know that posture, sir. The scroll can wait."],
        ["Twice into the phone, sir. It's a rectangle. The work is also a rectangle — the paying kind.",
         "Sir, the phone has had its minute. The clock would like its own back."],
        ["Third time, sir. Shall I read the feed aloud so we can at least call it multitasking?",
         "The phone wins again, sir. I'm starting to think it has better material than I do."],
    ],
    "screen": [                        # SHARE LOCK: the tab/window on screen isn't the one we locked
        ["Sir — that is not the tab we agreed on. Back we go.",
         "A new tab, sir? Bold. The locked one misses you already.",
         "You've wandered off-screen, sir. The work is one click to the left."],
        ["That's twice off the locked tab, sir. It's starting to look like a habit.",
         "Again, sir? If this tab were the work, I'd have locked THAT one."],
        ["Third departure, sir. Shall I bookmark the distraction so we can at least be efficient about it?",
         "Sir, at this rate the wrong tab is getting more of you than the right one ever did."],
    ],
}
SGT = {   # drill-sergeant mode (opt-in): one hot pool per kind, no tiers — already max heat
    "app": ["EYES ON THE TARGET, SIR. That window is NOT the mission.",
            "Wrong window, soldier. You have a clock and it is EATING. Move.",
            "Back on the objective, sir. NOW. The detour does not get a medal."],
    "away": ["POSITION ABANDONED, sir. The chair is empty and I am NOT the one leaving.",
             "Where is my operator? Desk. Now. The minutes are deserting with you, sir."],
    "phone": ["DROP THE PHONE, sir. It is a morale hazard and it knows it.",
              "Phone DOWN. Chin UP. The feed will still be terrible when you're finished, sir."],
    "screen": ["WRONG TAB, sir. The locked one. NOW.",
               "That is NOT the surface we agreed on, sir. Return to position."],
}
# S19x: the NAMED pools — {x} is the distraction's spoken name ("Instagram", "Slack").
# Four lines per tier so a long drift doesn't loop three phrases; the name itself rotates.
LINES_NAMED = {
    "screen": [
        ["Sir, you're on {x} again. That has nothing to do with the work.",
         "That's {x}, sir, and I'm fairly sure {x} isn't on today's list. Back to the task.",
         "A visit to {x}, sir? The work is exactly where you left it, and it is still waiting.",
         "Sir, {x} is open and the work is not. Let's correct that, shall we."],
        ["Twice into {x} now, sir. The task is starting to take it personally. Back to it.",
         "Sir, you're back on {x}. It will still be there when the session ends, I promise.",
         "{x} again, sir. At this point it's less a detour and more a destination. Back to work.",
         "Sir, that's {x} for the second time. The clock noticed, and so did I."],
        ["Third visit to {x}, sir. Shall I count {x} as the project, or are we going back to the real one?",
         "Sir, {x} has had more of your attention than the work has. Time to correct that.",
         "{x} once more, sir. I could bookmark it for later, if that's what it takes to get you back.",
         "At this rate, sir, {x} should be paying your invoices. Back to the task."],
    ],
    "app": [
        ["Sir, you're in {x} again. That has nothing to do with the work.",
         "That's {x}, sir, not the job. The window you need is the other one.",
         "A detour into {x}, sir? Noted, and forgiven this once. Back to the work.",
         "Sir, {x} is open and the work is not. Let's correct that, shall we."],
        ["Twice into {x} now, sir. The task is starting to take it personally. Back to it.",
         "Sir, you're back in {x}. It will survive without you; I've checked. The work will not.",
         "{x} again, sir. At this point it's less a detour and more a destination. Back to work.",
         "Sir, that's {x} for the second time. The clock noticed, and so did I."],
        ["Third time in {x}, sir. The detours are becoming the project. Back to the real one.",
         "Sir, {x} has had its share of you. The work would like its own back.",
         "{x} wins again, sir. I'm starting to think it has better material than the task does.",
         "I could lock {x}, sir, but I'm told that's a feature for later. Back to it."],
    ],
}
SGT_NAMED = {
    "screen": ["EYES OFF {x}, sir. That is NOT the mission. Back on target.",
               "{x}. Close it. NOW, sir. The clock is EATING and the work is waiting.",
               "Back from {x}, soldier. The detour does not get a medal. Move."],
    "app": ["{x} is NOT the objective, sir. Back on target. NOW.",
            "Out of {x}, soldier. You have a clock and it is EATING.",
            "{x}? Wrong window, sir. The work is in the other one. Move."],
}
# S20 (his ask: "if I'm still drifting, every two seconds, point me back to work"): the FOLLOW-UPS.
# Short on purpose — they ride a tight cadence and must never talk over each other. {x} optional.
NAG_LINES = ["Still on {x}, sir. Back to work.",
             "Sir, you should get back to work.",
             "Sir, {x} again. Get back to it.",
             "The work is waiting, sir. Leave {x}.",
             "Come on, sir. {x} can wait. Work.",
             "Sir. Back to the task, please."]
NAG_PLAIN = ["Sir, you should get back to work.",
             "Sir, back to work.",
             "The work is waiting, sir.",
             "Back to it, sir."]
SGT_NAG = ["BACK TO WORK, sir. NOW.",
           "Out of {x}. MOVE, soldier.",
           "The task, sir. Not {x}. NOW."]
SGT_NAG_PLAIN = ["BACK TO WORK, sir. NOW.", "The task, soldier. MOVE."]
def _est_ms(line):
    """How long a line takes to SPEAK (~16 chars/s for the butler's TTS), capped. The cadence
    counts from when the previous line has likely FINISHED, so follow-ups never stack on it."""
    return min(7000, 250 + 60 * len(str(line or "")))

ACKS = {
    "start": "{m} on the clock, sir. This window, nothing else. Eyes forward.",
    "start_sgt": "{m} on the clock, sir. This window and nothing else. I will be watching. Loudly.",
    "pause": "Paused, sir. The clock holds its breath.",
    "resume": "And we're back, sir. The clock resumes.",
    "extend": "Very good, sir — {m} more on the clock.",
    "abort": "Standing down, sir.",
    "sgt_on": "Drill-sergeant mode, sir. May your focus forgive me.",
    "sgt_off": "As you were, sir. The butler resumes.",
    "nag": "Understood, sir — while you're adrift I'll speak up every {t}.",
    "snooze": "Very well, sir — {t} of peace. Then the commentary resumes.",
    "excuse": "Very good, sir — carry on. I'll count this one as work.",
    # S19w: the lock defers when he starts FROM the Jarvis tab — SAY SO, or he sits there
    "defer": "Go to what you're working on, sir, and I'll lock on there.",
    "retarget_go": "Go to it, sir — I'll lock on where you land.",
    "retarget": "Locked on, sir.",
}

def _dur(seconds):
    s = int(seconds)
    if s < 60: return "1 second" if s == 1 else "%d seconds" % s
    m = s // 60
    return ("1 minute" if m == 1 else "%d minutes" % m) if s % 60 == 0 else "%d minutes %d seconds" % (m, s % 60)

def _mins(n):
    n = int(n)
    return "1 minute" if n == 1 else "%d minutes" % n

INTENT_ECHO_MAX = 48      # S19o ("it keeps repeating what I'm saying"): a long dictated intent
                          # is never parroted back — echo only when it reads like a title

# ---------- module-private identity cells (LAW 1 — nothing below this ever serializes) ---------
_TARGET = [None]

# S19h — THE TAB LANE (his "no visibility" field find): pixels can't reliably police tabs, so
# when the locked app is a scriptable browser we poll the ACTIVE TAB via AppleScript, hash the
# URL in-process, and compare-and-discard exactly like the bundle id. No share, no pixels, no
# TCC screen permissions — one macOS Automation approval ("may control Google Chrome") on
# first use. The hash lives ONLY in _TAB_TARGET; the URL string dies in the reader.
# S19x (his ask: "it should see that I'm on Instagram and say so"): the CALLOUT may name
# the distraction — "Sir, Instagram can wait." This is a deliberate, scoped loosening of
# LAW 1: a short display label (site or app NAME, never a URL, never a bundle id) rides ONE
# engine tick into the spoken line and nowhere else — not state(), not the ledger, not
# episodes, not the chat brain's note(). Flip NAME_SITES off to return to nameless lines.
NAME_SITES = True
SITE_NAMES = {   # host → the name he'd say out loud; anything else reads as its bare domain
    "instagram.com": "Instagram", "youtube.com": "YouTube", "youtu.be": "YouTube",
    "x.com": "X", "twitter.com": "X", "reddit.com": "Reddit", "tiktok.com": "TikTok",
    "facebook.com": "Facebook", "netflix.com": "Netflix", "twitch.tv": "Twitch",
    "linkedin.com": "LinkedIn", "amazon.com": "Amazon", "threads.net": "Threads",
    "discord.com": "Discord", "pinterest.com": "Pinterest", "news.ycombinator.com": "Hacker News",
    "mail.google.com": "Gmail", "gmail.com": "Gmail", "espn.com": "ESPN", "cnn.com": "CNN",
    "bbc.com": "the BBC", "bbc.co.uk": "the BBC", "nytimes.com": "the Times",
}
def _site_label(host):
    """PURE (probed): a spoken name for a host, or None for the Jarvis tab / nothing.
    The big distractions get their proper names; anything else is its bare domain."""
    h = (host or "").lower().split(":")[0].strip(".")
    if not h or h in ("localhost", "127.0.0.1"):
        return None
    if h in SITE_NAMES:
        return SITE_NAMES[h]
    parts = h.split(".")
    for i in range(len(parts)):                 # longest suffix match: news.ycombinator.com, m.youtube.com
        cand = ".".join(parts[i:])
        if cand in SITE_NAMES:
            return SITE_NAMES[cand]
    if parts and parts[0] in ("www", "m", "mobile", "app", "web") and len(parts) > 2:
        parts = parts[1:]
    return ".".join(parts[-3:] if (len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "ac")) else parts[-2:])

# ⚖ S19y (his field round: "it says Python can stand down"): clicking the desktop card's LOCK pill
# makes the card's OWN python process the frontmost app. The re-target was guarded against that
# (S19x) but the one-second POLL was not — so the poll registered an APP DRIFT named "Python",
# spoke it, and that callout ate the 3-second gap so his real tab switch right after went silent.
# The card is never where he is: filter it to "unreadable" (fail-open, hold), for the settle too.
_PY_PREFIXES = ("org.python", "com.apple.python")
_PY_NAMES = ("python", "python3", "facewin")
def _front_filter(fid, fname):
    """PURE (probed): the frontmost identity the poll may act on. The desktop card's process
    (a python host) becomes (None, None) — unreadable — so it can neither drift nor settle."""
    f = (fid or "").lower(); n = (fname or "").strip().lower()
    if (f and f.startswith(_PY_PREFIXES)) or (n in _PY_NAMES):
        return None, None
    return fid, fname

CHROME_APPS = {"com.google.Chrome": "Google Chrome",
               "com.google.Chrome.canary": "Google Chrome Canary",
               "com.brave.Browser": "Brave Browser",
               "com.microsoft.edgemac": "Microsoft Edge"}
_TAB_TARGET = [None]
_TAB_APP = [None]
_TAB_WARNED = [False]
# S19i (the killer field flaw): FOCUS is clicked IN THE JARVIS TAB, so locking the active tab
# at click time locked the one tab he's guaranteed to leave. When the start context IS the
# Jarvis tab, the lock DEFERS: the first non-Jarvis surface he settles on (~3s) becomes the
# target — and the Jarvis tab itself is HOME BASE, never a drift (he returns to talk).
_DEFER = [False]
_SETTLE = [None, 0]          # (candidate identity key, consecutive ticks) — private cell, LAW 1
_DEFER_N = [0]               # ticks spent deferring — a stuck defer arms app-only at 45
# ⚖ S19l: a SECOND Chrome instance (e.g. a stray --user-data-dir test browser) hijacks the
# AppleEvent routing for "Google Chrome" — the windowless twin answers "no windows" forever
# while the real one goes unwatched. Detect the persistent-blindness and NAME it once.
_NOWIN = [0]
_NOWIN_WARNED = [False]

def _tab_read_health(ok):
    if ok:
        _NOWIN[0] = 0
        return
    _NOWIN[0] += 1
    if _NOWIN[0] >= 20 and not _NOWIN_WARNED[0] and ENGINE.on:
        _NOWIN_WARNED[0] = True
        _queue_say("I cannot reach your Chrome's windows, sir — if a second Chrome is running, "
                   "close the spare and I will see your tabs again.")

def _active_tab_read(app_name):
    """The ONLY reader of tab identity. Returns (status, sha1-or-None, is_jarvis_tab, label);
    the URL string never leaves this function. `label` (S19x) is a spoken display name for
    the site — it rides one tick into a callout and is discarded; it is NOT an identity key.
    ⚖ S19l: the hash is of the URL's HOST, not the full URL — his work site is an SPA whose
    path changes with every click (full-URL hashing made the settle flap and navigation
    inside the work site read as drift). Site-level is the honest granularity: skool.com is
    the work, youtube.com is the drift."""
    try:
        out = subprocess.run(
            ["osascript", "-e", 'tell application "%s" to get URL of active tab of front window' % app_name],
            capture_output=True, text=True, timeout=3)
        if out.returncode != 0:
            err = (out.stderr or "").lower()
            return ("denied" if ("not authorized" in err or "-1743" in err) else "none", None, False, None)
        u = (out.stdout or "").strip()
        if not u:
            return ("none", None, False, None)
        if not (u.startswith("http://") or u.startswith("https://")):
            # chrome://newtab, devtools, etc — transit surfaces, never lockable work (S19m)
            return ("transit", None, False, None)
        try:
            from urllib.parse import urlparse
            host = (urlparse(u).netloc or u).lower()
        except Exception:
            host = u.lower()
        isj = host in ("localhost:4719", "127.0.0.1:4719")
        return ("ok", hashlib.sha1(host.encode()).hexdigest(), isj, (None if isj else _site_label(host)))
    except Exception:
        return ("none", None, False, None)

def _active_tab_hash(app_name):
    """The identity-only view (status, sha1, is_jarvis) — every caller that must never see
    a label (start, settle, retarget, diag) reads through this."""
    st2, h, isj, _lab = _active_tab_read(app_name)
    return st2, h, isj

# ⚖ S19w: _second_window_hash (S19m, "the work may live on display 2") is GONE. It let the
# settle lock a BACKGROUND window's active tab while the Jarvis window was frontmost — with
# three Chrome windows open it locked a tab he never looked at ~3s into the share, and his
# real work tab then read as a drift (2026-09-09, 4 drifts / 90s in a 3-minute session).
# Only the surface he is actually on may settle; a wrong lock is worse than no tab lock.

def _settle_candidate(fid, in_browser, st2, h, isj):
    """PURE (probed): the settle key for ONE tick. In a browser, a readable NON-Jarvis tab is
    the candidate; the Jarvis tab and transit pages HOLD (key None, count kept); a failed
    read SKIPS (count kept, never reset). Outside a browser the app alone is the key."""
    if not fid:
        return None, False
    if not in_browser:
        return (fid, None), False
    if st2 == "ok":
        return (((fid, h), False) if (h and not isj) else (None, False))
    if st2 == "transit":
        return None, False
    return None, True

def _retarget_plan(fid, in_browser, st2, h, isj):
    """PURE (probed): what 'lock on this tab' means from where he is. A readable work tab →
    lock it now; a non-browser app → lock the app; the Jarvis tab, a transit page, or an
    unreadable surface → re-arm the DEFER and lock wherever he lands next."""
    if not fid:
        return "defer"
    if not in_browser:
        return "app"
    if st2 == "ok" and h and not isj:
        return "tab"
    return "defer"

def _retarget_tab():
    """An excused detour becomes the new normal (mirrors the client's lockRef)."""
    if _TAB_APP[0]:
        st2, h, _isj = _active_tab_hash(_TAB_APP[0])
        if st2 == "ok" and h:
            _TAB_TARGET[0] = h

def _frontmost_read():
    """The ONLY reader of app identity. `lsappinfo` (LaunchServices CLI) — public tooling,
    no TCC, no pixels, and a FRESH window-server query on every call.
    ⚖ S19k LAW: NSWorkspace.frontmostApplication FREEZES in a long-lived headless process —
    it updates via run-loop notifications the server never pumps, so it forever returns the
    app that was frontmost at the FIRST query. Fresh-process tests always pass (first query
    is correct), which masked this for six field rounds of zero drifts. Never use NSWorkspace
    for frontmost in the server; lsappinfo tracked Chrome→Finder→Chrome live where NSWorkspace
    stayed frozen (proven 2026-08-30).
    Returns (bundle_id, display_name); (None, None) when unavailable (Windows members): the
    app signal fails OPEN. S19x: the display name is the spoken label for an app drift."""
    try:
        r = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True, timeout=3)
        asn = (r.stdout or "").strip()
        if not asn:
            return None, None
        r2 = subprocess.run(["lsappinfo", "info", "-only", "bundleid,name", asn],
                            capture_output=True, text=True, timeout=3)
        m = re.search(r'"CFBundleIdentifier"\s*=\s*"([^"]+)"', r2.stdout or "")
        n = re.search(r'"LSDisplayName"\s*=\s*"([^"]+)"', r2.stdout or "")
        return (m.group(1) if m else None), (n.group(1)[:40] if n else None)
    except Exception:
        return None, None

def _frontmost_id():
    return _frontmost_read()[0]


# ---------- the engine (pure: injectable clock, boolean signals only — the probe drives this) ----
class FocusEngine:
    def __init__(self, clock=None, speak=None, facewin=None):
        self.clock = clock or (lambda: time.time() * 1000.0)
        self.speak = speak or (lambda line, report=False: None)    # sink: queue a spoken line
        self.facewin = facewin or (lambda txt, state: None)        # sink: desktop countdown
        self.sergeant = False
        self.nag_ms = NAG_MS               # survives reset — a set cadence is a preference
        self.reset()

    def reset(self):
        self.on = False; self.paused = False
        self.total_ms = 0; self.active_ms = 0
        self.drifts = 0; self.drift_ms = 0.0
        self.off_since = 0; self.in_drift = False; self.drift_kind = None; self.pend_kind = None
        self.cur_drift_ms = 0.0         # what THIS excursion has accrued (excuse refunds it)
        self.excused = False; self.excused_at = 0
        self.intent = None
        self.last_callout = -1e15; self.last_tick = 0
        self.pause_at = 0; self.seq = 0
        self.snooze_until = 0; self._was_quiet = False
        self.pend_speak = False         # S19y: a confirmed drift the gap floor silenced — speak when it lifts
        self.nag_from = 0               # S20: no follow-up may start before the previous line has finished
        self.finished = None            # report dict once done
        self.where = None               # S19x: the distraction's spoken name — ONE tick, never serialized

    def start(self, minutes, intent=None, ack=None, tail=None):
        self.reset()
        self.on = True
        self.intent = str(intent or "").strip()[:140] or None   # his own stated work — colors the lines
        try:
            m = int(minutes)
        except Exception:
            m = DEFAULT_MIN
        self.total_ms = max(1, min(MAX_MIN, m)) * 60000
        self.last_tick = self.clock()
        if ack:
            line = str(ack)[:300]        # ONE composed line (lock verdict + intent + clock) —
        else:                            # the two-Jarvises fix: a single voice door, no racing acks
            line = (ACKS["start_sgt"] if self.sergeant else ACKS["start"]).format(m=_mins(self.total_ms // 60000))
            if self.intent and len(self.intent) <= INTENT_ECHO_MAX:
                line = '"%s" — noted, sir. %s' % (self.intent, line)
            elif self.intent:
                line = "Noted, sir. " + line
        if tail:                         # S19w: "go to your work and I'll lock on there"
            line = (line + " " + str(tail))[:400]
        self.speak(line)
        self._fw()

    def pause(self):
        if not self.on or self.paused: return False
        self.paused = True; self.pause_at = self.clock()
        self.off_since = 0; self.in_drift = False       # a pause is not a drift
        self.speak(ACKS["pause"]); self._fw()
        return True

    def resume(self):
        if not self.on or not self.paused: return False
        self.paused = False; self.last_tick = self.clock(); self.pause_at = 0
        self.speak(ACKS["resume"]); self._fw()
        return True

    def extend(self, minutes):
        if not self.on: return False
        add = max(1, min(MAX_MIN, int(minutes)))
        self.total_ms += add * 60000
        self.speak(ACKS["extend"].format(m=_mins(add))); self._fw()
        return True

    def remain_ms(self):
        return max(0, int(self.total_ms - self.active_ms))

    def grace_left_ms(self):
        if not self.on or self.paused or self.in_drift or not self.off_since: return 0
        g = GRACE_APP_MS if self.pend_kind in ("app", "screen") else GRACE_EYES_MS
        return max(0, int(g - (self.clock() - self.off_since)))

    def tick(self, app_on, eyes, where=None):
        """One heartbeat. app_on: bool (compare-and-discard happened OUTSIDE — we only ever
        see the verdict). eyes: None (no feed / stale) or {'present': bool, 'down': bool,
        'screen_off': bool} — screen_off is the client's SHARE LOCK verdict (pixels stay in
        the browser; only this boolean travels).
        `where` (S19x): the spoken name of what he drifted INTO ("Instagram", "Slack") — used
        only to word THIS tick's callout, overwritten every tick, never stored or serialized."""
        self.where = (str(where)[:40] if (NAME_SITES and where and isinstance(where, str)) else None)
        if not self.on: return
        now = self.clock()
        if self.paused:
            if self.pause_at and now - self.pause_at > PAUSE_MAX_MS:
                self._finish(completed=False, quiet=True)
            return
        dt = min(DT_CAP_MS, max(0, now - self.last_tick))   # a sleeping Mac freezes the clock
        self.last_tick = now
        self.active_ms += dt

        # combine the signals → off? which kind? (phone beats away beats app beats screen —
        # an app switch also trips the strip diff, and "you switched apps" is the truer line)
        kind = None
        if eyes and eyes.get("down"): kind = "phone"
        elif eyes and not eyes.get("present", True): kind = "away"
        if kind is None and not app_on: kind = "app"
        if kind is None and eyes and eyes.get("screen_off"): kind = "screen"
        self.pend_kind = kind

        # "it's okay, I'm doing research": the CURRENT excursion is work — suppress until he
        # is fully back on signal once (or the cap runs out), and never bill it
        if self.excused:
            if kind is None or now - self.excused_at > EXCUSE_MAX_MS:
                self.excused = False
            else:
                self.off_since = 0; self.in_drift = False
                self._was_quiet = now < self.snooze_until
                if self.active_ms >= self.total_ms: self._finish(completed=True)
                else: self._fw()
                return

        quiet = now < self.snooze_until                     # "give me N seconds" — numbers still count
        if kind is None:                                    # fully back on signal
            self.off_since = 0; self.in_drift = False; self.drift_kind = None; self.cur_drift_ms = 0.0
        else:
            grace = GRACE_APP_MS if kind in ("app", "screen") else GRACE_EYES_MS
            if not self.off_since: self.off_since = now
            if self.in_drift:
                self.drift_ms += dt; self.cur_drift_ms += dt
                if self._was_quiet and not quiet:           # snooze expired mid-drift → "then give me updates"
                    self.pend_speak = False
                    self._speak_line(self._nag_line(self.drift_kind or kind), now)
                elif not quiet and self.pend_speak and now >= self.nag_from and now - self.last_callout >= min(CALLOUT_GAP_MS, self.nag_ms):
                    self.pend_speak = False                 # S19y: the swallowed callout, now (after the last line ends)
                    self._speak_line(self._callout(self.drift_kind or kind), now)
                elif not quiet and now >= self.nag_from and now - self.last_callout >= self.nag_ms:
                    # S20: the drift PERSISTS → a SHORT "back to work" follow-up on the nag cadence,
                    # never before the previous line has finished speaking
                    self._speak_line(self._nag_line(self.drift_kind or kind), now)
            elif now - self.off_since >= grace:             # grace spent → this is a real drift
                self.in_drift = True; self.drift_kind = kind
                self.drifts += 1
                backlog = now - self.off_since              # the grace window counts once confirmed
                self.drift_ms += backlog; self.cur_drift_ms = backlog
                if not quiet and now >= self.nag_from and now - self.last_callout >= min(CALLOUT_GAP_MS, self.nag_ms):
                    self._speak_line(self._callout(kind), now)
                elif not quiet:
                    self.pend_speak = True                  # S19y: inside the floor — say it when it lifts
        if kind is None: self.pend_speak = False
        self._was_quiet = quiet

        if self.active_ms >= self.total_ms:
            self._finish(completed=True)
        else:
            self._fw()

    def _speak_line(self, line, now):
        """S20: the ONE door for drift speech — stamps the cadence from when this line will END."""
        self.last_callout = now
        self.nag_from = now + _est_ms(line)
        self.speak(line)

    def _nag_line(self, kind):
        """S20: a SHORT follow-up while the same drift persists — points him back to work."""
        x = self.where if kind in ("screen", "app") else None
        if self.sergeant:
            pool = SGT_NAG if x else SGT_NAG_PLAIN
        else:
            pool = NAG_LINES if x else NAG_PLAIN
        line = pool[self.seq % len(pool)]
        self.seq += 1
        return line.replace("{x}", x) if x else line

    def _callout(self, kind):
        x = self.where if kind in ("screen", "app") else None      # S19x: name the distraction
        if self.intent and self.seq == 0 and len(self.intent) <= INTENT_ECHO_MAX:
            self.seq += 1                              # the first callout names HIS stated work
            if self.sergeant:
                return ('THAT is %s, not "%s", sir. Back on it. NOW.' % (x, self.intent)) if x else \
                       ('THAT is not "%s", sir. Back on it. NOW.' % self.intent)
            return ('Sir, you\'re on %s. That has nothing to do with "%s". Back to it, please.' % (x, self.intent)) if x else \
                   ('Sir, that does not look like "%s" to me. Back to it, please.' % self.intent)
        if self.sergeant:
            pool = (SGT_NAMED.get(kind) if x else None) or SGT.get(kind) or SGT["app"]
        else:
            tiers = (LINES_NAMED.get(kind) if x else None) or LINES.get(kind) or LINES["app"]
            pool = tiers[min(max(self.drifts - 1, 0), len(tiers) - 1)]
        line = pool[self.seq % len(pool)]
        self.seq += 1
        return line.replace("{x}", x) if x else line

    def set_nag(self, seconds, quiet=False):
        try:
            s = int(seconds)
        except Exception:
            return False
        self.nag_ms = max(NAG_MIN_S, min(NAG_MAX_S, s)) * 1000
        if not quiet: self.speak(ACKS["nag"].format(t=_dur(self.nag_ms // 1000)))
        return True

    def snooze(self, seconds):
        if not self.on: return False
        try:
            s = int(seconds)
        except Exception:
            return False
        s = max(1, min(SNOOZE_MAX_S, s))
        self.snooze_until = self.clock() + s * 1000
        self.speak(ACKS["snooze"].format(t=_dur(s)))
        return True

    def excuse(self):
        """'No Jarvis, it's okay — I'm doing research on this other tab.' The CURRENT
        excursion is retro-forgiven (count and seconds refunded) and stays quiet until he's
        fully back on signal once (EXCUSE_MAX_MS cap)."""
        if not self.on or self.paused: return False
        self.forgive()
        self.excused = True; self.excused_at = self.clock()
        self.speak(ACKS["excuse"])
        self._fw()
        return True

    def forgive(self):
        """S19w: quietly end the CURRENT excursion as if it never happened (count + seconds
        refunded, off-signal cleared). No ack, no quiet window — the re-target's new target
        IS where he is, so the next tick is simply on-signal. excuse() = forgive + ack."""
        if not self.on: return False
        if self.in_drift:
            self.drifts = max(0, self.drifts - 1)
            self.drift_ms = max(0.0, self.drift_ms - self.cur_drift_ms)
        self.in_drift = False; self.off_since = 0; self.cur_drift_ms = 0.0
        return True

    def abort(self):
        if not self.on: return False
        self._finish(completed=False)
        return True

    def _finish(self, completed, quiet=False):
        planned_min = self.total_ms // 60000
        active_min = int(round(self.active_ms / 60000.0))
        on_ms = max(0.0, self.active_ms - self.drift_ms)
        on_min = min(int(on_ms // 60000), int(planned_min))
        pct = min(1.0, on_ms / self.total_ms) if self.total_ms else 0.0   # the last tick can overshoot
        self.finished = {
            "planned_min": int(planned_min), "active_min": active_min,
            "on_target_min": on_min, "drifts": int(self.drifts),
            "drift_sec": int(round(self.drift_ms / 1000.0)),
            "pct": round(pct, 3), "completed": bool(completed),
        }
        self.on = False; self.paused = False
        self.facewin("", "clear")
        if quiet: return
        if completed:
            self.speak(self._report_line(self.finished), report=True)
        else:
            self.speak(ACKS["abort"] + " " + self._short_tally(self.finished), report=True)

    def _short_tally(self, r):
        tag = ('"%s": ' % self.intent) if (self.intent and len(self.intent) <= INTENT_ECHO_MAX) else ""
        if r["active_min"] <= 0: return tag + "Nothing on the tape, sir."
        return "%s%d of %d minutes on target before we stood down — %s." % (
            tag, r["on_target_min"], r["planned_min"],
            "no drifts" if not r["drifts"] else
            "%d drift%s" % (r["drifts"], "" if r["drifts"] == 1 else "s"))

    def _report_line(self, r):
        tag = ('"%s": ' % self.intent) if (self.intent and len(self.intent) <= INTENT_ECHO_MAX) else ""
        if r["drifts"] == 0:
            base = "Time, sir. %sa flawless %s — not one drift. I had material prepared; wasted, all of it." % (
                tag, _mins(r["planned_min"]))
        else:
            base = "Time, sir. %s%d of %d minutes on target — %d drift%s, %d seconds adrift." % (
                tag, r["on_target_min"], r["planned_min"], r["drifts"],
                "" if r["drifts"] == 1 else "s", r["drift_sec"])
        return base

    def _fw(self):
        ms = self.remain_ms()
        txt = "%d:%02d" % (ms // 60000, (ms % 60000) // 1000)
        state = "pause" if self.paused else ("drift" if (self.in_drift or (self.off_since and not self.paused)) else "focus")
        self.facewin(txt, state)


# ---------- the live session plumbing (server-side singleton) ----------
_LOCK = threading.RLock()
_SAY = {"line": None, "at": 0, "report": None, "report_at": 0}
_EYES = {"present": None, "down": False, "screen_off": False, "at": 0.0}
_THREAD = [None]

def _queue_say(line, report=False):
    with _LOCK:
        _SAY["line"] = line; _SAY["at"] = time.time() * 1000
        if report:
            _SAY["report"] = ENGINE.finished; _SAY["report_at"] = _SAY["at"]

def _fw_send(txt, state):
    """Desktop countdown: extend the facewin UDP protocol (timer|MM:SS|state).
    S19b field find: the bay must CLAIM the overlay too — timer messages are passthrough
    (they never boot the card), so without the claim the countdown only ever appeared when
    SCREEN WATCH had already spawned it. The claim is change-guarded server-side, so
    claiming on every tick is free."""
    try:
        send = CTX.get("facewin_send"); claim = CTX.get("facewin_claim")
        if state == "clear":
            if send: send("timer|")
            if claim: claim(False)
        else:
            if claim: claim(True)
            if send: send("timer|%s|%s" % (txt, state))
    except Exception:
        pass

ENGINE = FocusEngine(speak=_queue_say, facewin=_fw_send)

def _load_agg():
    try:
        d = json.load(open(AGG_FILE))
        return d if isinstance(d, dict) else {"sessions": []}
    except Exception:
        return {"sessions": []}

def _save_agg(d):
    try:
        tmp = AGG_FILE + ".tmp"
        with open(tmp, "w") as f: json.dump(d, f, indent=1)
        os.replace(tmp, AGG_FILE)
    except Exception:
        pass

_AGG_KEYS = ("ts", "planned_min", "active_min", "on_target_min", "drifts", "drift_sec", "pct", "completed")

def record_session(rep, agg=None, now=None):
    """Append ONE aggregate record (LAW 3 — whitelisted keys only, no app identity exists here)
    and return (streak, compare_line). Pure given agg+now, so the battery drives it."""
    agg = _load_agg() if agg is None else agg
    now = time.time() if now is None else now
    prev = [s for s in agg.get("sessions") or [] if s.get("completed")]
    row = {k: rep.get(k) for k in _AGG_KEYS if k != "ts"}
    row["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))
    sessions = (agg.get("sessions") or []) + [row]
    agg["sessions"] = sessions[-KEEP_SESSIONS:]
    streak = 0
    for s in reversed(agg["sessions"]):
        if not s.get("completed"): break
        if (s.get("pct") or 0) >= CLEAN_PCT: streak += 1
        else: break
    compare = ""
    if rep.get("completed") and prev:
        last = prev[-1]
        try:
            day = time.strftime("%A", time.strptime(last.get("ts", ""), "%Y-%m-%dT%H:%M:%S"))
            today = time.strftime("%A", time.localtime(now))
            label = "your last run" if day == today else day
        except Exception:
            label = "your last run"
        lp = int(round((last.get("pct") or 0) * 100)); np_ = int(round((rep.get("pct") or 0) * 100))
        if np_ > lp: compare = " Better than %s's %d percent." % (label, lp)
        elif np_ < lp: compare = " %s's run was cleaner, sir — %d percent." % (label, lp)
        else: compare = " Dead level with %s, sir." % label
    if rep.get("completed") and streak >= 2:
        compare += " That's %d clean sessions running." % streak
    return agg, streak, compare


def _poll_loop():
    """The heartbeat. LAW 1 lives here: the frontmost id is a LOCAL, compared, discarded."""
    while True:
        time.sleep(TICK_S)
        if not ENGINE.on:
            with _LOCK:
                if not ENGINE.on:
                    _THREAD[0] = None
                    return
        # identity reads happen OUTSIDE the lock (osascript can take ~150ms-3s; /focus/state
        # must never wait on it). The cells are single-writer; a one-tick stale read is benign.
        fid, fname = _front_filter(*_frontmost_read())   # S19y: the card's own process is never "him"
        front_browser = CHROME_APPS.get(fid) if fid else None
        if _DEFER[0]:
            # S19i/l/m/w: waiting for him to settle on the work surface (~2 ticks on the same
            # non-Jarvis app/site). A transient read failure HOLDS the settle; chrome://
            # transit pages never lock; a stuck defer arms app-only after ~45s.
            # ⚖ S19w: ONLY THE SURFACE HE IS ON CAN SETTLE — no background-window guessing.
            key, skip = None, False
            if fid and front_browser:
                st2, h, isj = _active_tab_hash(front_browser)
                _tab_read_health(st2 in ("ok", "transit"))
                key, skip = _settle_candidate(fid, True, st2, h, isj)
                h = None
            elif fid:
                key, skip = _settle_candidate(fid, False, None, None, False)
            if not skip:
                if key and key == _SETTLE[0]:
                    _SETTLE[1] += 1
                    if _SETTLE[1] >= 2:
                        _TARGET[0] = key[0]
                        if key[1]:
                            _TAB_TARGET[0] = key[1]; _TAB_APP[0] = front_browser
                        _DEFER[0] = False; _SETTLE[0] = None; _SETTLE[1] = 0
                        _queue_say("Locked on, sir.")     # S19m: the deal is struck AUDIBLY —
                                                          # if he hears it on the wrong page,
                                                          # "it's okay…" re-targets in one breath
                else:
                    _SETTLE[0] = key; _SETTLE[1] = 1 if key else 0
            _DEFER_N[0] += 1
            if _DEFER[0] and _DEFER_N[0] >= 45 and fid:   # S19m: never run target-less forever
                _TARGET[0] = fid
                _DEFER[0] = False; _SETTLE[0] = None; _SETTLE[1] = 0
            fid = None; key = None
            with _LOCK:
                if not ENGINE.on:
                    _THREAD[0] = None
                    return
                eyes = None                               # S19m: EYES stay alive while deferring
                if _EYES["at"] and (time.time() * 1000 - _EYES["at"]) < EYES_STALE_MS and _EYES["present"] is not None:
                    eyes = {"present": bool(_EYES["present"]), "down": bool(_EYES["down"]),
                            "screen_off": False}          # no screen accusations before a target exists
                ENGINE.tick(True, eyes)
                if ENGINE.finished and not ENGINE.on:
                    _close_out()
            continue
        app_on = True if (fid is None or _TARGET[0] is None) else (fid == _TARGET[0])
        # S19x: what did he drift INTO? An app name for an app drift, a site name for a tab
        # drift — a display string that lives exactly one tick, in this frame only.
        where = fname if (not app_on and NAME_SITES) else None
        fid = None; fname = None                          # compare-and-discard
        # THE TAB LANE (S19h/i): the active tab matters whenever the front app is a browser —
        # to catch leaving the locked tab, and to recognise the Jarvis tab as HOME BASE
        tab_on = True
        if front_browser:
            st2, h, isj, lab = _active_tab_read(front_browser)
            _tab_read_health(st2 in ("ok", "transit"))
            if st2 == "ok":
                if isj:
                    app_on = True; tab_on = True; where = None   # talking to Jarvis is never a drift
                elif not app_on:
                    if NAME_SITES and lab: where = lab           # drifted into a browser → name the SITE
                elif app_on and _TAB_TARGET[0]:
                    tab_on = (h == _TAB_TARGET[0])
                    if not tab_on and NAME_SITES: where = lab    # left the locked tab → name the site
            elif st2 == "denied" and not _TAB_WARNED[0]:
                _TAB_WARNED[0] = True
                _queue_say("macOS is asking whether I may see your browser tabs, sir — "
                           "allow it once and I will keep proper watch.")
            h = None; lab = None                          # compare-and-discard
        with _LOCK:
            if not ENGINE.on:
                _THREAD[0] = None
                return
            eyes = None
            if _EYES["at"] and (time.time() * 1000 - _EYES["at"]) < EYES_STALE_MS and _EYES["present"] is not None:
                eyes = {"present": bool(_EYES["present"]), "down": bool(_EYES["down"]),
                        "screen_off": bool(_EYES["screen_off"]) or (not tab_on)}
            elif not tab_on:                              # the tab lane needs NO browser feed at all
                eyes = {"present": True, "down": False, "screen_off": True}
            ENGINE.tick(app_on, eyes, where=where)
            where = None                                  # the label dies here
            if ENGINE.finished and not ENGINE.on:
                _close_out()

def _close_out():
    rep = ENGINE.finished
    ENGINE.finished = None
    _TARGET[0] = None
    _TAB_TARGET[0] = None; _TAB_APP[0] = None
    _DEFER[0] = False; _SETTLE[0] = None; _SETTLE[1] = 0; _DEFER_N[0] = 0
    try:
        agg, streak, compare = record_session(rep)
        _save_agg(agg)
        if compare and _SAY["report"] is not None:
            _SAY["line"] = (_SAY["line"] or "") + compare
        _SAY["report"] = dict(rep, streak=streak)
        log = CTX.get("log")
        if log:
            tag = (' ("%s")' % ENGINE.intent) if ENGINE.intent else ""
            log("focus", "Focus session%s %s: %d/%d min on target, %d drifts (%ds adrift)." % (
                tag, "complete" if rep["completed"] else "aborted",
                rep["on_target_min"], rep["planned_min"], rep["drifts"], rep["drift_sec"]))
    except Exception:
        pass

def start_session(minutes, sergeant=None, intent=None, ack=None):
    with _LOCK:
        if ENGINE.on:
            return {"error": "already running"}
        tid = _frontmost_id()
        app_name = CHROME_APPS.get(tid) if tid else None  # against OUR constant table only
        _TAB_TARGET[0] = None; _TAB_APP[0] = None
        _DEFER[0] = False; _SETTLE[0] = None; _SETTLE[1] = 0; _DEFER_N[0] = 0
        _NOWIN[0] = 0; _NOWIN_WARNED[0] = False
        if app_name:                                      # a browser start → look at its ACTIVE TAB
            st2, h, isj = _active_tab_hash(app_name)      # (first call = the one-time macOS prompt)
            if st2 == "ok" and h and not isj:
                _TARGET[0] = tid; _TAB_TARGET[0] = h; _TAB_APP[0] = app_name
            else:
                # ⚖ S19l: DEFER on ANY uncertainty — clicked-in-the-Jarvis-tab (the normal
                # flow) OR a failed tab read (the field killer: the Jarvis tab's WebGL boot
                # stalls Chrome's AppleScript past the timeout at exactly the click moment;
                # the old code silently fell back to app-only watching FOREVER). The settle
                # loop retries every second and locks the first surface he settles on.
                _DEFER[0] = True
                _TARGET[0] = None
                if st2 == "denied" and not _TAB_WARNED[0]:
                    _TAB_WARNED[0] = True
                    _queue_say("macOS is asking whether I may see your browser tabs, sir — "
                               "allow it once and I will keep proper watch.")
            h = None
        else:
            _TARGET[0] = tid                              # the id's ONLY home
        tid = None
        if sergeant is not None:
            ENGINE.sergeant = bool(sergeant)
        # S19w: a client-composed ack (the FOCUS click / startWithAsk) carries its own
        # "go to your work" clause; the default voice-start ack gets it from here.
        ENGINE.start(minutes or DEFAULT_MIN, intent=intent, ack=ack,
                     tail=(ACKS["defer"] if (_DEFER[0] and not ack) else None))
        t = _THREAD[0]
        if t is None or not t.is_alive():
            _THREAD[0] = threading.Thread(target=_poll_loop, daemon=True)
            _THREAD[0].start()
        return state(claim=False)

def _browser_for_card():
    """S19x: a click on the desktop card may make the card frontmost — so read the browser's
    FRONT WINDOW directly (osascript answers with the browser backgrounded). The tab-lane
    browser first, then the known browsers in order. Returns (bundle_id, app_name)."""
    by_name = {v: k for k, v in CHROME_APPS.items()}
    names = [n for n in ([_TAB_APP[0]] + list(CHROME_APPS.values())) if n]
    seen = set()
    for n in names:
        if n in seen: continue
        seen.add(n)
        st2, _h, _isj = _active_tab_hash(n)
        if st2 in ("ok", "transit"):
            return by_name.get(n), n
    return None, None

def retarget_now(via=None):
    """S19w — 'lock on this tab': the explicit re-target, from wherever he is. Identity reads
    happen OUTSIDE the lock (like the poll); the plan is applied under it. Nothing spoken
    or returned ever carries an identity (LAW 1). S19x: via='card' (the desktop button) or a
    python-process frontmost → read the browser's front window instead of the card."""
    if not ENGINE.on:
        return None
    fid = _frontmost_id()
    fb = CHROME_APPS.get(fid) if fid else None
    if via == "card" or (fid and fid.lower().startswith(_PY_PREFIXES)):
        fid, fb = _browser_for_card()
    st2, h, isj = _active_tab_hash(fb) if fb else (None, None, False)
    if fb:
        _tab_read_health(st2 in ("ok", "transit"))
    plan = _retarget_plan(fid, bool(fb), st2, h, isj)
    with _LOCK:
        if not ENGINE.on:
            return None
        if plan == "defer":
            _TARGET[0] = None; _TAB_TARGET[0] = None; _TAB_APP[0] = None
            _DEFER[0] = True; _SETTLE[0] = None; _SETTLE[1] = 0; _DEFER_N[0] = 0
            ENGINE.forgive()
            _queue_say(ACKS["retarget_go"])
        else:
            _TARGET[0] = fid
            if plan == "tab":
                _TAB_TARGET[0] = h; _TAB_APP[0] = fb
            else:
                _TAB_TARGET[0] = None; _TAB_APP[0] = None
            _DEFER[0] = False; _SETTLE[0] = None; _SETTLE[1] = 0
            ENGINE.forgive()
            _queue_say(ACKS["retarget"])
        fid = None; h = None                              # compare-and-discard
        return state(claim=False)

# ---------- state (LAW 1: whitelist serializer — booleans/counters/canned text ONLY) ----------
_STATE_KEYS = ("on", "paused", "sergeant", "remain_ms", "total_ms", "on_target",
               "drifts", "drift_sec", "grace_left_ms", "eyes_fresh", "nag_s", "snoozed",
               "excused", "say", "report", "deferred")

def state(claim=False):
    with _LOCK:
        now = time.time() * 1000
        d = {
            "on": bool(ENGINE.on), "paused": bool(ENGINE.paused), "sergeant": bool(ENGINE.sergeant),
            "remain_ms": ENGINE.remain_ms() if ENGINE.on else 0,
            "total_ms": int(ENGINE.total_ms) if ENGINE.on else 0,
            "on_target": bool(ENGINE.on and not ENGINE.off_since),
            "drifts": int(ENGINE.drifts), "drift_sec": int(round(ENGINE.drift_ms / 1000.0)),
            "grace_left_ms": ENGINE.grace_left_ms(),
            "eyes_fresh": bool(_EYES["at"] and now - _EYES["at"] < EYES_STALE_MS),
            "nag_s": int(ENGINE.nag_ms // 1000),
            "snoozed": bool(ENGINE.on and ENGINE.clock() < ENGINE.snooze_until),
            "excused": bool(ENGINE.on and ENGINE.excused),
            "deferred": bool(ENGINE.on and _DEFER[0]),   # S19w: the tab lock is still waiting on him
            "say": None, "report": None,
        }
        if _SAY["report"] is not None and now - _SAY["report_at"] > REPORT_TTL_MS:
            _SAY["report"] = None; _SAY["line"] = None
        if claim:
            if _SAY["line"]: d["say"] = _SAY["line"]; _SAY["line"] = None
            if _SAY["report"] is not None: d["report"] = _SAY["report"]; _SAY["report"] = None
        else:
            d["say"] = None
        return {k: d[k] for k in _STATE_KEYS}

def feed_eyes(e):
    with _LOCK:
        if not isinstance(e, dict):
            return
        _EYES["present"] = bool(e.get("present"))
        _EYES["down"] = bool(e.get("down"))
        _EYES["screen_off"] = bool(e.get("screen_off"))
        _EYES["at"] = time.time() * 1000


def note():
    """S19j: LIVE session state for the chat brain's prompt — it must answer focus questions
    from THIS, never guess ('you haven't clicked FOCUS yet' while the clock ran, field hit).
    Booleans, counters, and his own stated intent only — no identities, per LAW 1."""
    try:
        with _LOCK:
            if not ENGINE.on:
                return ("\n\nFOCUS BAY LIVE STATE: no focus session is running right now. If he asks "
                        "whether you're watching him or what he's focused on, say the clock is idle "
                        "and offer to start one (click FOCUS, or 'thirty minutes on this').")
            rm = ENGINE.remain_ms()
            bits = ["a focus session is RUNNING with %d:%02d remaining" % (rm // 60000, (rm % 60000) // 1000)]
            if ENGINE.intent:
                bits.append('the stated work: "%s"' % ENGINE.intent)
            if _DEFER[0]:
                bits.append("the target lock is still waiting for him to settle on his work surface "
                            "— tell him to go to his work tab and it will lock there")
            elif _TAB_TARGET[0]:
                bits.append("locked to one specific browser tab and its app")
            elif _TARGET[0]:
                bits.append("locked to one app")
            if ENGINE.paused:
                bits.append("PAUSED")
            else:
                bits.append("he is %s target right now" % ("ON" if not ENGINE.off_since else "OFF"))
            if ENGINE.drifts:
                bits.append("%d drift%s so far, %d seconds adrift" % (
                    ENGINE.drifts, "" if ENGINE.drifts == 1 else "s", int(ENGINE.drift_ms / 1000)))
            if ENGINE.sergeant:
                bits.append("drill-sergeant mode")
            return ("\n\nFOCUS BAY LIVE STATE (answer any focus/watching/accountability question from "
                    "THIS — never guess, never claim the session isn't running): " + "; ".join(bits) +
                    ". PRIVACY, say it with pride if asked: the desk names the distraction OUT LOUD in the "
                    "moment ('sir, Instagram can wait') but never writes it down — no site or app identity "
                    "is stored in state, the ledger, episodes, or these notes; YOU only ever learn whether "
                    "he matches the locked target, never where he went. TO CHANGE THE TARGET (wrong tab, or he "
                    "names another site) he says 'lock on this tab' FROM the tab he wants — from the "
                    "Jarvis tab it re-arms and locks wherever he lands next. Never tell him to bring a "
                    "tab to the front and then click FOCUS (the button lives in the Jarvis tab), and "
                    "never tell him to abort and restart just to move the target.")
    except Exception:
        return ""


# ---------- hermetic battery (fake clock, no NSWorkspace, no facewin, throwaway engines) ------
_BUNDLE_RE = re.compile(r"\bcom\.[a-z0-9-]+\.[a-z0-9.-]+", re.I)

def probe_battery():
    R = []
    ok = lambda n, c: R.append({"n": n, "ok": bool(c)})
    CLK = [1000000.0]
    spoken = []
    fw = []
    mk = lambda: FocusEngine(clock=lambda: CLK[0], speak=lambda l, report=False: spoken.append(l),
                             facewin=lambda t, s: fw.append((t, s)))
    step = lambda e, ms, app_on, eyes=None: (CLK.__setitem__(0, CLK[0] + ms), e.tick(app_on, eyes))

    # 1 · grace split: a 1.5s app hop is forgiven; a 10.5s look-away is too (eyes keep the long grace)
    e = mk(); e.start(30); spoken.clear()
    step(e, 1500, False)                                  # 1.5s off-app — inside the fast grace
    step(e, 1500, True)
    g_app = (e.drifts == 0 and not spoken)
    for _ in range(7): step(e, 1500, True, {"present": False, "down": False})   # 10.5s away < 12s
    step(e, 1500, True, {"present": True, "down": False})
    ok("grace", g_app and e.drifts == 0 and e.drift_ms == 0 and not spoken)

    # 2 · app drift confirms past the FAST grace ("immediately"), counts the backlog, speaks tier-0
    for _ in range(3): step(e, 1500, False)               # 4.5s off ≥ 2.5s grace
    ok("drift", e.drifts == 1 and e.in_drift and e.drift_ms >= GRACE_APP_MS and
       len(spoken) == 1 and spoken[0] in LINES["app"][0])

    # 3 · escalation ORDER: 2nd drift speaks the pointed pool, 3rd the sharp pool
    step(e, 1500, True)
    CLK[0] += CALLOUT_GAP_MS
    for _ in range(3): step(e, 1500, False)
    step(e, 1500, True)
    CLK[0] += CALLOUT_GAP_MS
    for _ in range(3): step(e, 1500, False)
    ok("escalation", e.drifts == 3 and len(spoken) == 3 and
       spoken[1] in LINES["app"][1] and spoken[2] in LINES["app"][2])

    # 4 · callout floor (S19n: 3s — flap guard only): a drift confirmed INSIDE 3s of the last
    #     callout counts silently; the next one past the floor SPEAKS (every real switch talks)
    e2 = mk(); e2.start(30); spoken.clear()
    for _ in range(2): step(e2, 1500, False)              # drift 1 confirmed + SPOKEN at +3.0s
    step(e2, 400, True)
    for _ in range(3): step(e2, 400, False)               # drift 2 ~1.6s after the callout → silent
    ok("cooldown", e2.drifts == 2 and len(spoken) == 1)
    step(e2, 400, True)
    CLK[0] += 3200                                        # past the flap floor
    for _ in range(3): step(e2, 1500, False)              # drift 3 → speaks again
    ok("cooldown-release", e2.drifts == 3 and len(spoken) == 2)

    # 5 · away drift: app on-target, face gone past the long grace → the away pool
    e3 = mk(); e3.start(30); spoken.clear()
    for _ in range(10): step(e3, 1500, True, {"present": False, "down": False})
    ok("away", e3.drifts == 1 and e3.drift_kind == "away" and spoken and
       spoken[0] in LINES["away"][0])

    # 6 · phone beats away: head-down is its own callout
    e4 = mk(); e4.start(30); spoken.clear()
    for _ in range(10): step(e4, 1500, True, {"present": True, "down": True})
    ok("phone", e4.drifts == 1 and e4.drift_kind == "phone" and spoken and
       spoken[0] in LINES["phone"][0])

    # 7 · SHARE LOCK: strip-off alone = the "screen" pool (fast grace); with the app ALSO off,
    #     "app" wins (the truer line for a full app switch)
    e5 = mk(); e5.start(30); spoken.clear()
    for _ in range(3): step(e5, 1500, True, {"present": True, "down": False, "screen_off": True})
    k1 = e5.drift_kind
    e5b = mk(); e5b.start(30)
    for _ in range(3): step(e5b, 1500, False, {"present": True, "down": False, "screen_off": True})
    ok("screen", k1 == "screen" and spoken and spoken[0] in LINES["screen"][0] and
       e5b.drift_kind == "app")

    # 8 · no EYES feed → no away/phone/screen accusation (fail-open)
    e6 = mk(); e6.start(30); spoken.clear()
    for _ in range(20): step(e6, 1500, True, None)
    ok("eyes-open", e6.drifts == 0 and not spoken)

    # 9 · EXCUSE: "it's okay, I'm doing research" retro-forgives the excursion and stays
    #     quiet while it CONTINUES; returning once re-arms normal watching
    e7 = mk(); e7.start(30); spoken.clear()
    for _ in range(4): step(e7, 1500, False)              # a real drift, billed + spoken
    ok("excuse-pre", e7.drifts == 1 and e7.drift_ms > 0 and len(spoken) == 1)
    e7.excuse()                                           # +1 spoken (the carry-on ack)
    ex_ok = (e7.drifts == 0 and e7.drift_ms == 0 and e7.excused)
    for _ in range(20): step(e7, 1500, False)             # excursion continues 30s — silent, unbilled
    ex_quiet = (e7.drifts == 0 and e7.drift_ms == 0 and len(spoken) == 2)
    step(e7, 1500, True)                                  # back on target once → excuse clears
    CLK[0] += CALLOUT_GAP_MS
    for _ in range(3): step(e7, 1500, False)              # leaving AGAIN is a fresh drift
    ok("excuse", ex_ok and ex_quiet and not e7.excused and e7.drifts == 1 and len(spoken) == 3)

    # 10 · pause semantics: clock frozen, drifts suspended, resume continues
    e8 = mk(); e8.start(30); spoken.clear()
    step(e8, 1500, True)
    a0 = e8.active_ms
    e8.pause()
    for _ in range(20): step(e8, 1500, False)             # off-target while paused — nobody cares
    ok("pause", e8.paused and e8.active_ms == a0 and e8.drifts == 0 and e8.remain_ms() == e8.total_ms - a0)
    e8.resume()
    step(e8, 1500, True)
    ok("resume", not e8.paused and e8.active_ms > a0)

    # 11 · extend adds whole minutes
    r0 = e8.remain_ms(); e8.extend(10)
    ok("extend", e8.remain_ms() == r0 + 600000)

    # 12 · sergeant mode swaps the pools
    e9 = mk(); e9.sergeant = True; e9.start(30); spoken.clear()
    for _ in range(3): step(e9, 1500, False)
    ok("sergeant", spoken and spoken[0] in SGT["app"])

    # 13 · report math: 30 planned, one ~90s drift → 28 on target, pct ≈ .95
    e10 = mk(); e10.start(30); spoken.clear()
    step(e10, 1500, True)
    for _ in range(60): step(e10, 1500, False)            # 90s off → one drift, all counted
    left = e10.total_ms - e10.active_ms
    while e10.on: step(e10, min(5000, max(1, left)), True); left = e10.total_ms - e10.active_ms
    r = e10.finished
    ok("report", bool(r) and r["completed"] and r["planned_min"] == 30 and r["drifts"] == 1 and
       85 <= r["drift_sec"] <= 95 and r["on_target_min"] == 28 and .93 <= r["pct"] <= .97 and
       "28 of 30" in spoken[-1])

    # 14 · streak + compare are pure over a fake ledger
    agg = {"sessions": [
        {"ts": "2026-08-25T09:00:00", "pct": .90, "completed": True},
        {"ts": "2026-08-26T09:00:00", "pct": .88, "completed": True}]}
    agg2, streak, comp = record_session(dict(r, pct=.95), agg=agg, now=time.time())
    ok("streak", streak == 3 and "Better than" in comp and "3 clean sessions" in comp)

    # 15 · NO-LEAK LAW: no app identity shape anywhere a payload, pool, or ledger row can carry
    blob = json.dumps([LINES, SGT, ACKS, r, agg2["sessions"][-1], spoken])
    row = agg2["sessions"][-1]
    ok("no-leak", not _BUNDLE_RE.search(blob) and set(row.keys()) <= set(_AGG_KEYS))

    # 16 · abort mid-run still tallies honestly
    e11 = mk(); e11.start(30); spoken.clear()
    for _ in range(40): step(e11, 1500, True)
    e11.abort()
    ok("abort", e11.finished and not e11.finished["completed"] and not e11.on and
       "stood down" in spoken[-1])

    # 17 · a forgotten pause quietly stands down (no speech)
    e12 = mk(); e12.start(30); spoken.clear(); e12.pause(); n0 = len(spoken)
    CLK[0] += PAUSE_MAX_MS + 60000
    e12.tick(True, None)
    ok("pause-expire", not e12.on and e12.finished and len(spoken) == n0)

    # 18 · nag cadence: while ONE drift persists, callouts repeat every nag_ms (demo mode = 10s)
    e13 = mk(); e13.set_nag(10, quiet=True); e13.start(30); spoken.clear()
    for _ in range(37): step(e13, 1500, False)            # ~55s off: confirm + ~5 re-nags
    ok("nag", e13.drifts == 1 and 4 <= len(spoken) <= 7 and len(set(spoken)) >= 2)

    # 19 · snooze: "give me 20 seconds" mutes the commentary, expiry prompts an update
    e14 = mk(); e14.start(30); spoken.clear()
    for _ in range(3): step(e14, 1500, False)             # drift confirms → 1 callout
    n1 = len(spoken)
    e14.snooze(20)                                        # +1 (the snooze ack)
    for _ in range(12): step(e14, 1500, False)            # 18s still inside the quiet window
    quiet_extra = len(spoken) - n1 - 1
    for _ in range(3): step(e14, 1500, False)             # window expires mid-drift → ONE update
    ok("snooze", n1 == 1 and quiet_extra == 0 and len(spoken) == n1 + 2)

    # 20 · nag clamps + rejects garbage
    e15 = mk()
    e15.set_nag(1, quiet=True); lo = e15.nag_ms
    e15.set_nag(99999, quiet=True); hi = e15.nag_ms
    ok("nag-clamp", lo == NAG_MIN_S * 1000 and hi == NAG_MAX_S * 1000 and not e15.set_nag("junk"))

    # 21 · INTENT: his stated work colors the ack, the FIRST callout, and the report card
    e16 = mk(); e16.start(30, intent="the thumbnail sprint"); spoken.clear()
    for _ in range(3): step(e16, 1500, False)             # first callout names the work
    first = spoken[-1] if spoken else ""
    step(e16, 1500, True)
    CLK[0] += CALLOUT_GAP_MS
    for _ in range(3): step(e16, 1500, False)             # second falls back to the pools
    second = spoken[-1] if spoken else ""
    ok("intent-callout", "the thumbnail sprint" in first and "the thumbnail sprint" not in second)
    e16.abort()
    ok("intent-report", '"the thumbnail sprint"' in spoken[-1])

    # 22 · a composed ack overrides the default (the two-Jarvises fix: ONE line, one door)
    e17 = mk(); spoken.clear()
    e17.start(30, intent="deck edits", ack="Locked on your entire screen, sir. Deck edits — 30 minutes on the clock.")
    ok("intent-ack", len(spoken) == 1 and spoken[0].startswith("Locked on your entire screen"))

    # 22b · intent attached MID-SESSION (the ask now follows the start) still names the work
    e18 = mk(); e18.start(30); spoken.clear()
    e18.intent = "the outreach batch"                      # what POST /focus/intent assigns
    for _ in range(3): step(e18, 1500, False)
    ok("intent-late", spoken and "the outreach batch" in spoken[-1])

    # 22c · a LONG dictated intent is never parroted back (S19o: "it keeps repeating me")
    long_i = "no this is the time I'm looking at right now I'm trying to do the school Workshop"
    e19 = mk(); spoken.clear()
    e19.start(30, intent=long_i)
    ack_clean = spoken and long_i not in spoken[0] and "Noted, sir." in spoken[0]
    for _ in range(3): step(e19, 1500, False)              # first callout → pools, no echo
    e19.abort()
    ok("intent-noparrot", ack_clean and all(long_i not in s for s in spoken))

    # 23 · zero-key: everything above ran with no config; this module never touches a key
    needles = ("api" + "_key", "config" + ".json")        # built at runtime so these lines can't self-match
    srcp = os.path.join(ROOT, "focus.py")
    src = open(srcp, encoding="utf-8").read() if os.path.exists(srcp) else ""
    ok("zero-key", src and not any(n in src for n in needles))

    # 30 · S19w settle: ONLY the surface he is on can settle — the Jarvis tab HOLDS (no
    # background-window guessing), transit holds, a failed read skips, a work tab is the key
    sc = _settle_candidate
    ok("settle-jarvis-holds", sc("com.google.Chrome", True, "ok", "h1", True) == (None, False))
    ok("settle-work-tab", sc("com.google.Chrome", True, "ok", "h1", False) == (("com.google.Chrome", "h1"), False))
    ok("settle-transit-holds", sc("com.google.Chrome", True, "transit", None, False) == (None, False))
    ok("settle-fail-skips", sc("com.google.Chrome", True, "none", None, False) == (None, True))
    ok("settle-app", sc("com.apple.Notes", False, None, None, False) == (("com.apple.Notes", None), False))
    ok("settle-nofront", sc(None, False, None, None, False) == (None, False))
    # 31 · S19w re-target plan: Jarvis tab / transit / unreadable → re-arm the defer;
    # a readable work tab → lock it; a non-browser app → lock the app
    rp = _retarget_plan
    ok("retarget-plan", rp("com.google.Chrome", True, "ok", "h1", True) == "defer" and
       rp("com.google.Chrome", True, "none", None, False) == "defer" and
       rp("com.google.Chrome", True, "transit", None, False) == "defer" and
       rp(None, False, None, None, False) == "defer" and
       rp("com.google.Chrome", True, "ok", "h1", False) == "tab" and
       rp("com.apple.Notes", False, None, None, False) == "app")
    # 32 · forgive(): the current excursion is refunded SILENTLY (excuse() = forgive + ack)
    e30 = mk(); e30.start(30); spoken.clear()
    for _ in range(3): step(e30, 1500, False)             # 4.5s off ≥ grace → one confirmed drift
    d_before, s_before = e30.drifts, len(spoken)
    okf = e30.forgive()
    ok("forgive", okf and d_before == 1 and e30.drifts == 0 and e30.drift_ms == 0 and
       not e30.in_drift and len(spoken) == s_before)
    # 33 · a deferred DEFAULT start speaks the go-to-your-work tail; a composed ack is untouched
    e31 = mk(); spoken.clear(); e31.start(30, tail=ACKS["defer"])
    e32 = mk(); e32.start(30, ack="composed ack, sir.")
    ok("defer-tail", spoken[0].endswith(ACKS["defer"]) and spoken[1] == "composed ack, sir.")

    # 34 · S19x NAMED CALLOUTS: the spoken line names what he drifted INTO (app or site),
    # rotates through four lines a tier, and the name NEVER reaches the report card
    stepw = lambda e, ms, app_on, eyes=None, where=None: (CLK.__setitem__(0, CLK[0] + ms), e.tick(app_on, eyes, where=where))
    e40 = mk(); e40.start(30); spoken.clear()
    for _ in range(3): stepw(e40, 1500, False, None, "Slack")           # app drift INTO Slack
    n1 = bool(spoken) and "Slack" in spoken[-1]
    for _ in range(2): stepw(e40, 1500, True)                            # back on signal
    for _ in range(3): stepw(e40, 1500, True, {"present": True, "down": False, "screen_off": True}, "Instagram")
    n2 = len(spoken) >= 2 and "Instagram" in spoken[-1] and "Slack" not in spoken[-1]
    ok("named-callouts", n1 and n2 and e40.drifts == 2)
    e40.abort(); rep40 = json.dumps(e40.finished or {})
    ok("named-no-leak", "Slack" not in rep40 and "Instagram" not in rep40)
    e41 = mk(); e41.start(30, intent="the thumbnail sprint"); spoken.clear()
    for _ in range(3): stepw(e41, 1500, False, None, "YouTube")         # first callout: work AND distraction
    ok("named-intent", bool(spoken) and "YouTube" in spoken[0] and "the thumbnail sprint" in spoken[0])
    e42 = mk(); e42.sergeant = True; e42.start(30); spoken.clear()
    for _ in range(3): stepw(e42, 1500, False, None, "Reddit")
    ok("named-sgt", bool(spoken) and "Reddit" in spoken[0])
    e43 = mk(); e43.start(30); spoken.clear()                            # nameless when nothing is known
    for _ in range(3): stepw(e43, 1500, False, None, None)
    ok("named-fallback", bool(spoken) and "{x}" not in spoken[0] and spoken[0] in LINES["app"][0])
    ok("site-label", _site_label("www.instagram.com") == "Instagram" and _site_label("m.youtube.com") == "YouTube"
       and _site_label("x.com") == "X" and _site_label("twitter.com") == "X"
       and _site_label("news.ycombinator.com") == "Hacker News" and _site_label("ulcer.ai:443") == "ulcer.ai"
       and _site_label("docs.google.com") == "google.com" and _site_label("localhost:4719") is None)
    # 35 · S19y the card's own process never counts as "where he is" (poll + settle)
    ff = _front_filter
    ok("front-filter", ff("org.python.python", "Python") == (None, None) and ff(None, "Python") == (None, None)
       and ff("com.apple.python3", "python3") == (None, None) and ff("com.google.Chrome", "Google Chrome") == ("com.google.Chrome", "Google Chrome")
       and ff("com.apple.Notes", "Notes") == ("com.apple.Notes", "Notes"))
    # 36 · S19y a distinct drift confirmed inside the 3s floor speaks as soon as the floor lifts
    e50 = mk(); e50.start(30); spoken.clear()
    for _ in range(3): stepw(e50, 1500, False, None, "Slack")           # drift 1 → speaks
    n_a = len(spoken)
    stepw(e50, 500, True)                                               # back for half a second
    for _ in range(2): stepw(e50, 500, True, {"present": True, "down": False, "screen_off": True}, "YouTube")  # drift 2 confirmed ~1.5s after callout 1 → floor blocks it
    n_b = len(spoken)
    for _ in range(7): stepw(e50, 700, True, {"present": True, "down": False, "screen_off": True}, "YouTube")  # floor lifts + the first line has finished → speaks now, not at the 5-min nag
    n_c = len(spoken)
    ok("gap-deferred-speak", n_a == 1 and n_b == 1 and n_c == 2 and "YouTube" in spoken[-1] and e50.drifts == 2)
    # 37 · S20 the follow-ups: first callout = the long named comment; while the SAME drift persists
    #      on a 2s cadence the re-speaks are SHORT "back to work" lines that name the site, and no
    #      line starts before the previous one has finished (the cadence counts from its end)
    e60 = mk(); e60.set_nag(2, quiet=True); e60.start(30); spoken.clear()
    t_marks = []
    for _ in range(20):
        n0 = len(spoken); stepw(e60, 1000, True, {"present": True, "down": False, "screen_off": True}, "YouTube")
        if len(spoken) > n0: t_marks.append(CLK[0])
    first, rest = spoken[0], spoken[1:]
    gaps_ok = all(t2 - t1 >= _est_ms(spoken[i]) for i, (t1, t2) in enumerate(zip(t_marks, t_marks[1:])))
    ok("nag-followups", "YouTube" in first and len(first) > 45 and len(rest) >= 3 and
       all(len(l) <= 45 and l in [n.replace("{x}", "YouTube") for n in NAG_LINES] for l in rest) and
       all(l not in LINES_NAMED["screen"][0] for l in rest) and gaps_ok and e60.drifts == 1)
    ok("nag-2s-legal", (lambda e: (e.set_nag(2, quiet=True), e.nag_ms)[1])(mk()) == 2000)
    blobn = json.dumps([LINES_NAMED, SGT_NAMED, NAG_LINES, NAG_PLAIN, SGT_NAG, SGT_NAG_PLAIN])
    ok("named-pools-clean", "{x}" in blobn and not _BUNDLE_RE.search(blobn) and
       all(len(t) >= 4 for k in LINES_NAMED for t in LINES_NAMED[k]))
    return R


# ---------- HTTP bay ----------
def init(ctx):
    CTX.update(ctx or {})
    try:
        pref = _load_agg()
        ENGINE.sergeant = bool(pref.get("sergeant"))
        if pref.get("nag_s"): ENGINE.set_nag(pref["nag_s"], quiet=True)
    except Exception:
        pass

def _persist_pref(key, val):
    agg = _load_agg(); agg[key] = val; _save_agg(agg)

def handle(handler, method, raw_path, p):
    path = raw_path.split("?")[0]
    if not path.startswith("/focus"):
        return False
    if method == "GET":
        if path == "/focus/state":
            handler._json(state(claim=False)); return True
        if path == "/focus/diag":         # S19k field diagnosis — statuses/booleans ONLY, no identities
            fid = _frontmost_id()
            fb = CHROME_APPS.get(fid) if fid else None
            st2, h, isj = _active_tab_hash(fb) if fb else ("no-browser", None, False)
            d = {"frontmost_readable": bool(fid), "front_is_browser": bool(fb),
                 "tab_status": st2, "tab_is_jarvis": bool(isj), "tab_hash_present": bool(h),
                 "defer": bool(_DEFER[0]), "settle_ticks": int(_SETTLE[1]),
                 "app_target": bool(_TARGET[0]), "tab_target": bool(_TAB_TARGET[0]),
                 "app_on_now": (bool(fid == _TARGET[0]) if (fid and _TARGET[0]) else None),
                 "tab_on_now": (bool(h == _TAB_TARGET[0]) if (h and _TAB_TARGET[0]) else None),
                 "session_on": bool(ENGINE.on),
                 "tick_thread_alive": bool(_THREAD[0] and _THREAD[0].is_alive())}
            fid = None; h = None
            handler._json(d); return True
        return False
    if path == "/focus/state":            # the client poll: feeds EYES, claims say/report
        if p.get("eyes") is not None:
            feed_eyes(p.get("eyes"))
        handler._json(state(claim=True)); return True
    if path == "/focus/start":
        res = start_session(p.get("minutes") or DEFAULT_MIN, p.get("sergeant"),
                            intent=p.get("intent"), ack=p.get("ack"))
        handler._json(res, 409 if res.get("error") else 200); return True
    if path == "/focus/stop":
        with _LOCK:
            was = ENGINE.abort()
            if was and ENGINE.finished: _close_out()
        handler._json(state(claim=False) if was else {"error": "no session"}); return True
    if path == "/focus/pause":
        with _LOCK: okx = ENGINE.pause()
        handler._json(state(claim=False) if okx else {"error": "no session"}); return True
    if path == "/focus/resume":
        with _LOCK: okx = ENGINE.resume()
        handler._json(state(claim=False) if okx else {"error": "no session"}); return True
    if path == "/focus/extend":
        try:
            mins = int(p.get("minutes") or 10)
        except Exception:
            mins = 10
        with _LOCK: okx = ENGINE.extend(mins)
        handler._json(state(claim=False) if okx else {"error": "no session"}); return True
    if path == "/focus/sergeant":
        with _LOCK: ENGINE.sergeant = bool(p.get("on"))
        _persist_pref("sergeant", ENGINE.sergeant)
        handler._json({"sergeant": ENGINE.sergeant}); return True
    if path == "/focus/nag":
        with _LOCK: okx = ENGINE.set_nag(p.get("seconds"))
        if okx: _persist_pref("nag_s", int(ENGINE.nag_ms // 1000))
        handler._json({"nag_s": int(ENGINE.nag_ms // 1000)} if okx else {"error": "bad seconds"}); return True
    if path == "/focus/snooze":
        with _LOCK: okx = ENGINE.snooze(p.get("seconds"))
        handler._json(state(claim=False) if okx else {"error": "no session"}); return True
    if path == "/focus/excuse":
        with _LOCK:
            okx = ENGINE.excuse()
            if okx: _retarget_tab()       # the excused tab becomes the new normal
        handler._json(state(claim=False) if okx else {"error": "no session"}); return True
    if path == "/focus/retarget":         # S19w: "lock on this tab" — the explicit re-target
        res = retarget_now(via=(p.get("via") or None))
        handler._json(res if res else {"error": "no session"}, 200 if res else 409); return True
    if path == "/focus/intent":           # S19g: the work is named AFTER the clock starts —
        with _LOCK:                       # the session no longer waits on the answer
            okx = ENGINE.on and not ENGINE.paused
            if okx:
                ENGINE.intent = str(p.get("intent") or "").strip()[:140] or None
                if ENGINE.intent and len(ENGINE.intent) <= INTENT_ECHO_MAX:
                    _queue_say('"%s" — noted, sir.' % ENGINE.intent)
                elif ENGINE.intent:
                    _queue_say("Noted, sir.")     # S19o: never parrot a long dictation back
        handler._json(state(claim=False) if okx else {"error": "no session"}); return True
    if path == "/focus/probe":
        handler._json({"results": probe_battery()}); return True
    return False
