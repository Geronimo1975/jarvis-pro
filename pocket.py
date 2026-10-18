"""Jarvis POCKET — text your second brain from anywhere (Telegram).

The community ask (Luke): "get him on our phones — ideas come up away from the desk, and
everything still saves so you can continue back at your desk." This bay long-polls a private
Telegram bot FROM the Mac — no public server, no tunnel, no exposed port. Messages ride the
SAME brain as the desk: conversation memory, control tags (reminders, note captures, project
creation, even brain swaps) all work by text, every exchange lands in the Time Machine, and
captures/creations persist into the graph waiting at the desk. Jarvis also PUSHES the other
way: due reminders and high-priority inbox cards reach the phone even with no browser open
(the desk keeps them when a viewer tab has polled recently).

Plug-in bay contract (like calls/tools/hands): server.py soft-imports `pocket as POCKET`,
routes GET /api/pocket through handle(), init() at boot. Needs config.json → "telegram":
{"bot_token": "..."} (make one in 2 minutes with @BotFather). Graceful no-op until then.
SECURITY: the bot answers ONLY paired chats — pairing requires the 6-digit code minted at
boot (ask at the desk: "Jarvis, pocket code"), so a stranger finding the bot gets a butler
brush-off, never the brain. Paired chats persist in jarvis-pocket.json (gitignored).
"""
import json, os, random, re, threading, time, urllib.error, urllib.parse, urllib.request

CTX = {}                          # init() fills: cfg, root, chat, try_chat_swap, apply_tag, gag_re,
                                  # add_gag, log, open_tasks, mark_reminded, inbox_open, raise_card, last_seen
STATE = {"chats": [], "names": {}, "offset": 0, "pushed": [], "voice": {}}
LOCK = threading.Lock()
# S23: the pairing code is minted ONLY when he asks for it at the desk ("Jarvis, pocket code"),
# from `secrets`, lives 10 minutes, must match the WHOLE message, is consumed by a successful pair,
# and dies after 5 wrong guesses (the old code was `random`, boot-long, substring-matched, reusable —
# ~250 crafted messages paired a stranger with full desk authority)
import secrets as _secrets, hmac as _hmac
PAIR = {"code": "", "born": 0.0, "fails": 0}
PAIR_TTL_S, PAIR_MAX_FAILS = 600, 5

def pairing_code(fresh=False):
    if fresh or not PAIR["code"] or time.time() - PAIR["born"] > PAIR_TTL_S:
        PAIR["code"] = f"{_secrets.randbelow(10**6):06d}"; PAIR["born"] = time.time(); PAIR["fails"] = 0
    return PAIR["code"]

def _pair_ok(text):
    c = PAIR["code"]
    if not c or time.time() - PAIR["born"] > PAIR_TTL_S:
        return False
    return _hmac.compare_digest((text or "").strip(), c)
API = "https://api.telegram.org/bot"
DESK_FRESH_S = 90                 # a viewer tab polled within this window → the desk owns reminders
_started = False


def _cfg():
    return (CTX.get("cfg") or {}).get("telegram") or {}

def token():
    t = (_cfg().get("bot_token") or "").strip()
    return "" if not t or t.startswith("PUT-") else t

def configured():
    return bool(token())

def _state_file():
    return os.path.join(CTX.get("root") or ".", "jarvis-pocket.json")

def load_state():
    global STATE
    try:
        if os.path.exists(_state_file()):
            d = json.load(open(_state_file()))
            if isinstance(d, dict):
                STATE = {"chats": list(d.get("chats") or []), "names": dict(d.get("names") or {}),
                         "offset": int(d.get("offset") or 0), "pushed": list(d.get("pushed") or []),
                         "voice": dict(d.get("voice") or {})}
    except Exception:
        pass

def save_state():
    tmp = _state_file() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(STATE, f)
    os.replace(tmp, _state_file())
    try: os.chmod(_state_file(), 0o600)                         # S23
    except OSError: pass


def _api(method, data=None, timeout=20):
    """One Telegram Bot API call. Returns the parsed dict, or {} on any failure."""
    if not configured():
        return {}
    url = API + token() + "/" + method
    body = urllib.parse.urlencode(data or {}).encode()
    req = urllib.request.Request(url, data=body)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return {}

def _chunks(text, cap=3800):
    """Telegram hard-caps messages at 4096 chars — split long reports on sentence-ish seams."""
    text = (text or "").strip()
    if len(text) <= cap:
        return [text] if text else []
    parts, cur = [], ""
    for seg in text.replace("\r", "").split("\n"):
        seg += "\n"
        while len(seg) > cap:                      # a single monster line — hard split
            parts.append((cur + seg[:cap]).strip()); cur, seg = "", seg[cap:]
        if cur and len(cur) + len(seg) > cap:
            parts.append(cur.strip()); cur = seg
        else:
            cur += seg
    if cur.strip():
        parts.append(cur.strip())
    return parts

def send(chat_id, text):
    for part in _chunks(text):
        _api("sendMessage", {"chat_id": chat_id, "text": part})


# ---------- voice notes (2026-07-21): speak to the pocket, and it can speak back ----------
# TEXT is the default both ways. "voice on" flips replies to ElevenLabs voice notes (with the
# text as caption, so nothing becomes unskimmable); "voice off" / "text only" flips back —
# persisted per chat. Inbound voice notes ALWAYS work: Whisper (the OpenAI key already in
# config) transcribes them into the same brain path as typed text. Every failure at any hop
# falls back to plain text — voice can never break the pocket.
VOICE_ON_RE = re.compile(r"^(?:voice(?: replies| notes)?(?: mode)? on|reply in voice|speak to me)[.!]?$", re.I)
VOICE_OFF_RE = re.compile(r"^(?:voice(?: replies| notes)?(?: mode)? off|text only|text mode|stop (?:the )?voice(?: notes)?)[.!]?$", re.I)

def _voice_on(chat):
    return bool((STATE.get("voice") or {}).get(str(chat)))

def _set_voice(chat, on):
    with LOCK:
        STATE.setdefault("voice", {})[str(chat)] = bool(on)
        save_state()

def _api_file(method, chat_id, field, fname, mime, blob, caption=""):
    """Multipart upload (sendVoice/sendAudio) — stdlib only."""
    if not configured() or not blob:
        return {}
    bound = "----jarvispocket" + os.urandom(8).hex()
    parts = []
    for name, val in (("chat_id", chat_id),) + ((("caption", caption[:1000]),) if caption else ()):
        parts.append(f"--{bound}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{val}\r\n".encode())
    parts.append((f"--{bound}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{fname}\"\r\n"
                  f"Content-Type: {mime}\r\n\r\n").encode() + blob + b"\r\n")
    parts.append(f"--{bound}--\r\n".encode())
    req = urllib.request.Request(API + token() + "/" + method, data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={bound}"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.load(r)
    except Exception:
        return {}

def _dl_voice(file_id):
    d = _api("getFile", {"file_id": file_id})
    path = ((d.get("result") or {}).get("file_path") or "")
    if not path:
        return None
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/file/bot{token()}/{path}", timeout=30) as r:
            return r.read()
    except Exception:
        return None

def _transcribe(ogg):
    """Whisper rides the OpenAI key already in config. None → the caller apologises in text."""
    key = ((CTX.get("cfg") or {}).get("openai") or {}).get("api_key") or ""
    if not key or key.startswith("PUT-") or not ogg:
        return None
    bound = "----jarviswhisper" + os.urandom(8).hex()
    body = (f"--{bound}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nwhisper-1\r\n"
            f"--{bound}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"note.ogg\"\r\n"
            "Content-Type: audio/ogg\r\n\r\n").encode() + ogg + f"\r\n--{bound}--\r\n".encode()
    req = urllib.request.Request("https://api.openai.com/v1/audio/transcriptions", data=body,
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": f"multipart/form-data; boundary={bound}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return (json.load(r).get("text") or "").strip() or None
    except Exception:
        return None

_SPEAK_JUNK = re.compile(
    r"\*\*|`+|https?://\S+"
    r"|\{\s*\"[^{}]*\}"                                  # JSON payloads
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"   # UUIDs
    r"|\b[0-9a-f]{12,}\b", re.I)                          # long hex ids
def _tts(text):
    """His cloned ElevenLabs voice. Opus/Ogg first (Telegram's native voice-note format — no
    ffmpeg on this Mac, and none needed); mp3 fallback if the plan ever refuses opus.
    Returns (bytes, kind) with kind 'ogg' | 'mp3', or (None, None)."""
    el = (CTX.get("cfg") or {}).get("elevenlabs") or {}
    key, vid = (el.get("api_key") or "").strip(), (el.get("voice_id") or "").strip()
    if not key or key.startswith("PUT-") or not vid:
        return None, None
    clean = _SPEAK_JUNK.sub("", text or "").strip()[:900]
    if not clean:
        return None, None
    for fmt, kind in (("opus_48000_32", "ogg"), ("mp3_44100_128", "mp3")):
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{vid}?output_format={fmt}",
            data=json.dumps({"text": clean, "model_id": "eleven_turbo_v2_5"}).encode(),
            headers={"xi-api-key": key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                blob = r.read()
            if blob:
                return blob, kind
        except Exception:
            continue
    return None, None

def _send_voice(chat, text):
    """A voice note in HIS voice, text as the caption. Any failed hop → plain text, always."""
    blob, kind = _tts(text)
    if not blob:
        return send(chat, text)
    cap = (text or "")[:1000]
    r = (_api_file("sendVoice", chat, "voice", "note.ogg", "audio/ogg", blob, caption=cap)
         if kind == "ogg" else
         _api_file("sendAudio", chat, "audio", "note.mp3", "audio/mpeg", blob, caption=cap))
    if not r.get("ok"):
        send(chat, text)

def _reply(chat, text):
    (_send_voice if _voice_on(chat) else send)(chat, text)

def push_text(text):
    """A plain message to every paired chat — the delivery leg of 'text me X' (2026-07-28:
    'text' MEANS Telegram in this house; the SMS path is retired by user decision).
    Returns True when at least one paired chat exists to receive it."""
    if not configured() or not (text or "").strip():
        return False
    with LOCK:
        chats = list(STATE["chats"])
    for c in chats:
        send(c, text)
    return bool(chats)

def push_file(blob, fname, mime="application/pdf", caption=""):
    """A DOCUMENT to every paired chat (the deals bay's proposals/invoices land this way).
    Returns True if at least one chat accepted it."""
    if not configured() or not blob:
        return False
    with LOCK:
        chats = list(STATE["chats"])
    ok_any = False
    for c in chats:
        r = _api_file("sendDocument", c, "document", fname, mime, blob, caption=caption[:1000])
        ok_any = ok_any or bool(r.get("ok"))
    return ok_any

def push_call_report(text, card_id=None):
    """His standing rule (2026-07-21): call-task outcomes arrive as TEXT **and** a VOICE NOTE,
    regardless of the voice toggle. card_id marks the inbox card as pushed so the desk-closed
    card sweep never double-sends it."""
    if not configured():
        return
    with LOCK:
        chats = list(STATE["chats"])
        if card_id and card_id not in STATE["pushed"]:
            STATE["pushed"] = (STATE["pushed"] + [card_id])[-100:]
            save_state()
    for c in chats:
        send(c, text)
        _send_voice(c, text)


# ---------- inbound: the phone talks to the desk brain ----------
def _handle_msg(m):
    chat = (m.get("chat") or {}).get("id")
    text = (m.get("text") or "").strip()
    vmsg = m.get("voice") or m.get("audio") or None
    if not chat or (not text and not vmsg):
        return
    user = (m.get("from") or {}).get("username") or (m.get("from") or {}).get("first_name") or "someone"
    with LOCK:
        paired = chat in STATE["chats"]
    if paired and vmsg and not text:                # his voice note → Whisper → same brain path
        text = _transcribe(_dl_voice(vmsg.get("file_id"))) or ""
        if not text:
            return send(chat, "I couldn't make that voice note out, sir — once more, or type it?")
    if not paired and vmsg and not text:            # strangers don't get free transcription
        return send(chat, "This is a private butler, I'm afraid. If you're my principal: ask at "
                          "the desk for the pocket code (“Jarvis, pocket code”) and text it here.")
    if not paired:
        if _pair_ok(text):                          # S23: the whole message IS the code, once, within 10 min
            PAIR["code"] = ""                       # consumed
            with LOCK:
                if chat not in STATE["chats"]:
                    STATE["chats"].append(chat)
                STATE["names"][str(chat)] = user
                save_state()
            send(chat, "Paired, sir. The brain at the desk is listening — ask me anything, "
                       "set reminders, capture notes. It all lands in the graph at home.")
            try:
                CTX["raise_card"]("notify", f"📱 Pocket paired — @{user}",
                                  "Telegram is now a surface. Texts ride the desk brain.",
                                  source="pocket", speak=None)
            except Exception:
                pass
            return
        if PAIR["code"]:
            PAIR["fails"] += 1
            if PAIR["fails"] >= PAIR_MAX_FAILS:
                PAIR["code"] = ""                   # S23: five misses kill the code — ask again at the desk
        send(chat, "This is a private butler, I'm afraid. If you're my principal: ask at the "
                   "desk for the pocket code (“Jarvis, pocket code”) and text it here.")
        return
    if text in ("/start", "/help"):
        send(chat, "At your service, sir. Text me anything — questions ride your vault, "
                   "“remind me to…” sets reminders, “remember that…” files notes into the "
                   "graph, “create a project for…” builds it on disk. Due reminders, urgent "
                   "cards, and call reports get pushed here when you're away from the desk. "
                   "Voice notes work too — and say “voice on” if you'd rather hear my replies.")
        return
    RECALLISH = re.compile(r"\b(what did .{2,30} say|when did (?:i|we)\b|what happened (?:on|last|this)|"
                           r"(?:my )?history with|who is \w+ again|open loops?|still (?:open|outstanding|pending))\b", re.I)
    if RECALLISH.search(text) and CTX.get("brain_lookup"):
        try:
            ans = CTX["brain_lookup"](text)
            if ans:
                _reply(chat, ans)
                return
        except Exception:
            pass
    if VOICE_ON_RE.match(text):
        _set_voice(chat, True)
        return _send_voice(chat, "Voice replies on, sir — you'll be hearing from me properly now.")
    if VOICE_OFF_RE.match(text):
        _set_voice(chat, False)
        return send(chat, "Back to text, sir.")
    sid = f"pocket-{chat}"
    try:
        swapped = CTX["try_chat_swap"](text)        # "switch to grok" works from the beach too
        if swapped:
            _reply(chat, swapped.get("answer") or "Done, sir.")
            return
        ans, nodes, err = CTX["chat"](text, sid)
        if err:
            send(chat, f"The brain hit a snag, sir ({err}).")
            return
        tagged = CTX["apply_tag"](ans, sid)         # reminders/captures/creates fire exactly like the desk
        if tagged:
            ans = tagged.get("answer") or ans
        else:
            if CTX.get("assist_file"):               # free-form thoughts get auto-filed (async)
                def _file_it(t=text, c=chat):
                    try:
                        filed = CTX["assist_file"](t, f"pocket-{c}")
                        if filed:
                            send(c, "🗂 " + filed)
                    except Exception:
                        pass
                threading.Thread(target=_file_it, daemon=True).start()
            gm = CTX["gag_re"].search(ans or "")
            if gm:
                try: CTX["add_gag"](gm.group(1), gm.group(2))
                except Exception: pass
                ans = CTX["gag_re"].sub("", ans).strip()
            try: CTX["log"]("pocket", text, nodes)
            except Exception: pass
        # the Addendum-61 desk-door guard, pocket edition (live 2026-07-29: two "(no answer)"
        # bubbles landed on his Telegram — call_model's empty-reply sentinel walked straight
        # through this door)
        if not ans or ans.strip() == "(no answer)":
            ans = "I lost my words mid-thought, sir — say that again?"
        _reply(chat, ans)
    except Exception as e:
        send(chat, f"Something snapped in the wiring, sir ({str(e)[:80]}).")

def _poll_loop():
    while True:
        if not configured():
            time.sleep(30); continue
        try:
            with LOCK:
                off = STATE["offset"]
            r = _api("getUpdates", {"timeout": 50, "offset": off + 1}, timeout=70)
            for u in (r.get("result") or []):
                with LOCK:
                    STATE["offset"] = max(STATE["offset"], int(u.get("update_id") or 0))
                    save_state()
                _handle_msg(u.get("message") or {})
        except Exception:
            time.sleep(5)


# ---------- outbound: the desk pushes to the phone ----------
def _desk_is_live():
    try:
        return (time.time() - float(CTX["last_seen"]())) < DESK_FRESH_S
    except Exception:
        return False

def _push_once():
    """One sweep: due reminders (only when the desk is closed) + high-priority cards → the phone."""
    if not configured():
        return
    with LOCK:
        chats = list(STATE["chats"])
    if not chats:
        return
    # due reminders — ONLY when no viewer tab is around to speak them (the desk wins at the desk)
    if not _desk_is_live():
        now = time.time()
        routed = CTX.get("routed_elsewhere") or (lambda text: False)
        for t in (CTX["open_tasks"]() or []):
            if t.get("due") and not t.get("reminded") and t["due"] <= now:
                # a reminder CALL belongs to the server's call loop — racing it here delivered
                # "give me a reminder call" as a TEXT and the phone never rang (audit 2026-07-28
                # night). The predicate is capability-aware: if the call channel is down, the
                # task falls back to this loop rather than being dropped.
                try:
                    if routed(t.get("text") or ""):
                        continue
                except Exception:
                    pass
                CTX["mark_reminded"](t.get("ts"))
                for c in chats:
                    send(c, "⏰ It's time, sir — " + (t.get("text") or "your reminder."))
    # high-priority cards go to the pocket regardless — they're rare and they matter.
    # PHONE-CALL cards (outcomes, hotline summaries, sweep reports) also push when the desk is
    # closed (2026-07-21): "book a table" from the road should report back to the road.
    desk_live = _desk_is_live()
    for card in (CTX["inbox_open"]() or []):
        wanted = (card.get("priority") == "high"
                  or (card.get("source") == "calls" and not desk_live))
        if wanted and card.get("id") not in STATE["pushed"]:
            with LOCK:
                STATE["pushed"] = (STATE["pushed"] + [card["id"]])[-100:]
                save_state()
            icon = "📞" if card.get("source") == "calls" else "🔔"
            for c in chats:
                send(c, f"{icon} {card.get('title','')}\n{card.get('body','')}".strip())

def _push_loop():
    while True:
        time.sleep(20)
        try:
            _push_once()
        except Exception:
            pass


# ---------- HTTP surface ----------
def handle(handler, method, raw_path, payload):
    path = raw_path.split("?")[0]
    if method == "GET" and path == "/api/pocket":
        with LOCK:
            chats, names = list(STATE["chats"]), dict(STATE["names"])
        handler._json({"configured": configured(), "paired": len(chats),
                       "who": [names.get(str(c), "?") for c in chats],
                       "code": (pairing_code(True) if configured() and not chats else "")})
        return True
    return False


def init(ctx):
    global _started
    CTX.update(ctx or {})
    load_state()
    if _started:
        return
    _started = True
    threading.Thread(target=_poll_loop, daemon=True).start()
    threading.Thread(target=_push_loop, daemon=True).start()
