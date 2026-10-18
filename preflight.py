"""JARVIS PREFLIGHT — execute every live dependency chain and print a verdict.
Run: python3 preflight.py [--push]   (--push sends a real text+voice test to paired Telegram)

Born 2026-07-21 after a briefing call read a stale-OAuth 401 story down the phone: unit tests
had passed while a REAL chain (claude -p connectors) was dead. This harness tests chains, not
pieces: the running server, the Retell cloud config, the tunnel end-to-end, the briefing
content tiers, Telegram, and the served client files. No phone calls are ever placed.
"""
import importlib.util, json, os, re, socket, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
CFG = json.load(open("config.json"))
TEL = CFG.get("telephony") or {}
PASS, FAIL, WARN = [], [], []

def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✓ " if cond else "  ✗ ") + name + (f" — {detail}" if detail and not cond else ""))

def warn(name, detail=""):
    WARN.append(name)
    print(f"  ⚠ {name}" + (f" — {detail}" if detail else ""))

def http(url, body=None, timeout=25, method=None):
    req = urllib.request.Request(url, data=(json.dumps(body).encode() if body is not None else None),
                                 headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw.strip().startswith(b"{") or raw.strip().startswith(b"[") else raw)
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return 0, str(e)[:120]

def retell(path):
    req = urllib.request.Request("https://api.retellai.com" + path,
                                 headers={"Authorization": "Bearer " + TEL.get("api_key", "")})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)
    except Exception:
        return {}

print("== 1 · DESK SERVER ==")
st, body = http("http://localhost:4719/", method="GET")
ok("viewer serves", st == 200 and len(body or b"") > 100000, f"HTTP {st}")
st, d = http("http://localhost:4719/chat", {"question": "preflight: reply with one short word", "session": "preflight"}, timeout=60)
ok("chat brain answers", st == 200 and isinstance(d, dict) and bool(d.get("answer")))
st, d = http("http://localhost:4719/api/model", method="GET")
ok("model endpoint", isinstance(d, dict) and bool(d.get("model")), str(d)[:60])
MODEL_NOW = isinstance(d, dict) and d.get("model") or "?"
st, d = http("http://localhost:4719/calls_myinfo", {})
ok("callback on file", isinstance(d, dict) and bool(d.get("callback")))
st, d = http("http://localhost:4719/api/pocket", method="GET")
ok("telegram configured + paired", isinstance(d, dict) and d.get("configured") and (d.get("paired") or 0) >= 1)

print("== 2 · RETELL CLOUD (agents, prompts, wiring) ==")
AGENTS = dict(TEL.get("agents") or {})
AGENTS["hotline"] = TEL.get("hotline_agent_id")
EXPECT = {
    # the 2026-07-28 booking-saga laws must stay in the LIVE copies: one-action hang-ups,
    # the real-voicemail definition, the full close, the mid-call handoff re-intro
    "booking": ["this is Jarvis", "{{from_number}}", "LISTEN for which one", "NEVER ask them to hold",
                "{{today}}", "ONE action", "NEVER voicemail", "know or bring", "DIFFERENT person"],
    "inquiry": ["this is Jarvis", "{{from_number}}", "ONE action", "NEVER voicemail", "DIFFERENT person"],
    "general": ["Jarvis"],
    "hotline": ["RECEPTIONIST MODE", "{{caller_kind}}", "fetch_brain", "may I have the code"],
}
VOICES = {}
for kind, aid in AGENTS.items():
    if not aid:
        ok(f"{kind}: agent configured", False); continue
    a = retell(f"/get-agent/{aid}")
    lid = ((a.get("response_engine") or {}).get("llm_id"))
    l = retell(f"/get-retell-llm/{lid}") if lid else {}
    p = l.get("general_prompt") or ""
    # tools may live globally OR inside a state (the confirm-back cages end_call in 'closing' —
    # a stateful brief left at rest between calls is healthy, not drift; 2026-07-29)
    tools = [t.get("name") for t in (l.get("general_tools") or [])] \
        + [t.get("name") for s in (l.get("states") or []) for t in (s.get("tools") or [])]
    VOICES[kind] = a.get("voice_id")
    missing = [m for m in EXPECT[kind] if m not in p]
    ok(f"{kind}: prompt current", not missing, f"missing {missing}")
    ok(f"{kind}: end_call tool", "end_call" in tools)
    if kind in ("booking", "inquiry"):
        # Addendum 74 REVERSAL: the long Addendum-72 warning description BROKE the working
        # booking agent (11:22 garble — attention magnet, see calls._tool_end_call). The law
        # is now the ORIGINAL SHORT text, and preflight fails on any drift toward long copy.
        ec = next((t for t in (l.get("general_tools") or []) if t.get("name") == "end_call"), {})
        _ecd = ec.get("description") or ""
        ok(f"{kind}: end_call description SHORT (the 11:22 law)",
           "after a goodbye" in _ecd and "first message" not in _ecd and len(_ecd) < 120)
        ok(f"{kind}: press_digit + ask_jarvis", "press_digit" in tools and "ask_jarvis" in tools)
        ok(f"{kind}: waits for their hello", (l.get("begin_message") or "") == "")
    if kind == "hotline":
        ok("hotline: fetch_brain tool", "fetch_brain" in tools)
        ok("hotline: neutral greeting", "Jarvis speaking" in (l.get("begin_message") or ""))
        dv = l.get("default_dynamic_variables") or {}
        ok("hotline: safe unknown default", dv.get("caller_kind") == "unknown")
    if "Grace" in p:
        ok(f"{kind}: Grace fully retired", False)
nums = retell("/list-phone-numbers")
wired = any(any(x.get("agent_id") == TEL.get("hotline_agent_id") for x in (n.get("inbound_agents") or []))
            for n in (nums if isinstance(nums, list) else []) if n.get("phone_number") == TEL.get("from"))
ok("number: hotline wired inbound", wired)
print(f"  · voices: " + ", ".join(f"{k}={v}" for k, v in VOICES.items()))

print("== 2.5 · ARMORY LINES (the auth that everything tool-powered rides) ==")
try:
    conn = (json.load(open("jarvis-tools.json")).get("conn") or {})
except Exception:
    conn = {}
for name, c in conn.items():
    if c.get("status") != "connected":
        continue
    if c.get("kind") == "google":
        if name != "gmail":               # gmail+gcal share one token row — check it once
            continue
        # the NATIVE line: refresh must mint a live bearer AND a real Gmail call must answer
        try:
            form = urllib.parse.urlencode({
                "grant_type": "refresh_token", "refresh_token": c.get("refresh", ""),
                "client_id": c.get("client_id", ""),
                "client_secret": ((CFG.get("google") or {}).get("client_secret") or "")}).encode()
            with urllib.request.urlopen(urllib.request.Request(
                    "https://oauth2.googleapis.com/token", data=form,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=20) as r:
                tokd = json.load(r)
            bearer = tokd.get("access_token", "")
            with urllib.request.urlopen(urllib.request.Request(
                    "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                    headers={"Authorization": "Bearer " + bearer}), timeout=20) as r2:
                prof = json.load(r2)
            ok("armory: google native line alive (gmail+gcal)",
               bool(prof.get("emailAddress")), "profile call failed")
            print(f"  · google account: {prof.get('emailAddress', '?')}")
        except Exception as e:
            ok("armory: google native line alive (gmail+gcal)", False,
               str(e)[:80] + " → reconnect the Gmail tile in the armory")
        continue
    if c.get("kind") != "url":
        print(f"  · {name}: {c.get('kind')} tile (presence only — validated on use)")
        continue
    u = c.get("url_override") or c.get("access") or ""
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "preflight", "version": "1"}}}
    try:
        req = urllib.request.Request(u, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Accept": "application/json, text/event-stream"})
        with urllib.request.urlopen(req, timeout=20) as r:
            ok(f"armory: {name} line alive", r.status in (200, 202))
    except urllib.error.HTTPError as e:
        ok(f"armory: {name} line alive", False,
           e.read().decode(errors="ignore")[:100] + " → re-paste its URL in the 🔌 armory")
    except Exception as e:
        ok(f"armory: {name} line alive", False, str(e)[:80])

st, d = http("http://127.0.0.1:4719/demo/urgent", {"scenario": "signed", "dry": 1})
ok("demo bay: staged-urgent dry run answers (no call placed)", st == 200 and bool((d or {}).get("dry")) and "signed" in str(d))
print("== 3 · GRACELINE (tunnel + all four doors) ==")
try:
    GL = json.load(open("jarvis-graceline.json"))
except Exception:
    GL = {}
tok, port = GL.get("token", ""), GL.get("port", 4761)
base = f"http://127.0.0.1:{port}"
st, d = http(f"{base}/grace/{tok}", {"args": {"question": "what is the business email?"}}, timeout=40)
ok("grace: benign pack answer", st == 200 and len(str((d or {}).get("result") or (d or {}).get("answer") or "")) > 10)
st, d = http(f"{base}/grace/{tok}", {"args": {"question": "what's his social security number?"}}, timeout=40)
ok("grace: SSN refused", st == 200 and "can't share" in str(d).lower())
st, _ = http(f"{base}/grace/WRONG", {"args": {"question": "hi"}})
ok("grace: wrong token 404", st == 404)
# S23: the owner door is gated on a code THIS server checked for that call — walk the real sequence
_cid = {"call": {"call_id": f"preflight-{int(__import__('time').time())}"}}
st, d = http(f"{base}/brain/{tok}", {**_cid, "args": {"question": "what is CiteVue?"}}, timeout=45)
ok("brain: an UNVERIFIED call is refused (S23)", st == 200 and "verified" in str(d).lower() and "citevue" not in str(d).lower())
st, d = http(f"{base}/verify/{tok}", {**_cid, "args": {"code": "0000"}})
ok("verify: a wrong code is rejected", st == 200 and "wrong" in str(d).lower())
st, d = http(f"{base}/verify/{tok}", {**_cid, "args": {"code": str(TEL.get("pin", ""))}})
ok("verify: the code checks server-side and carries the pack", st == 200 and "verified" in str(d).lower() and "Now:" in str(d))
st, d = http(f"{base}/brain/{tok}", {**_cid, "args": {"question": "what is CiteVue?"}}, timeout=45)
ok("brain: owner line answers from vault (verified call)", st == 200 and "citevue" in str(d).lower())
st, d = http(f"{base}/inbound/{tok}", {"call_inbound": {"from_number": TEL.get("callback", "")}})
ok("inbound webhook: owner recognised", "owner" in str(d))
st, d = http(f"{base}/inbound/{tok}", {"call_inbound": {"from_number": "+14155551234"}})
ok("inbound webhook: stranger → receptionist", '"unknown"' in str(d) or "'unknown'" in str(d))
# public leg: the tool URL Retell will actually call must resolve and answer
_ba = retell("/get-agent/" + TEL.get("agents", {}).get("booking", ""))
_bl = retell("/get-retell-llm/" + ((_ba.get("response_engine") or {}).get("llm_id") or ""))
tool = next((t for t in (_bl.get("general_tools") or []) if t.get("name") == "ask_jarvis"), None)
if tool:
    host = tool["url"].split("/")[2]
    try:
        socket.getaddrinfo(host, 443)
        st, d = http(tool["url"], {"args": {"question": "what is the business email?"}}, timeout=45)
        ok("public tunnel: resolves + answers", st == 200 and len(str((d or {}).get("result") or (d or {}).get("answer") or "")) > 10)
    except Exception as e:
        ok("public tunnel: resolves + answers", False, str(e)[:80])
else:
    ok("public tunnel: ask_jarvis wired", False)

print("== 4 · BRIEFING CONTENT (what tomorrow's call will say — the server's OWN chain) ==")
st, d = http("http://localhost:4719/calls_briefpreview", {}, timeout=180)
tier = isinstance(d, dict) and d.get("tier") or 0
text = isinstance(d, dict) and (d.get("text") or "") or ""
print(f"  · tier {tier} sample: {text[:150]}…")
ok("briefing call has healthy content", st == 200 and tier in (1, 2), f"tier {tier}")
if tier == 3:
    warn("briefing degraded to local pack — Zapier tool tier failed AND desk claude CLI is logged out")

print("== 5 · SERVED CLIENT FILES (what his browser actually gets) ==")
for path, markers in (("/calls.js", ["GO_START", "BRIEFCALL_ON", "RECALLQ", "__jarvisCallAdopt", "Setting up the call"]),
                      ("/tools.js", ["BRAINY"]),
                      ("/fx.js", ["fable5"]),
                      ("/", ["setBrainBadge", "call_confirm", "hexA"])):
    st, body = http("http://localhost:4719" + path, method="GET", timeout=15)
    text = body.decode(errors="ignore") if isinstance(body, bytes) else str(body)
    missing = [m for m in markers if m not in text]
    ok(f"served {path} current", st == 200 and not missing, f"missing {missing}")
grace_left = sum(1 for pth in ("/calls.js", "/") for _ in [0]
                 if "Grace" in (lambda b: b.decode(errors='ignore') if isinstance(b, bytes) else str(b))(http("http://localhost:4719" + pth, method="GET", timeout=15)[1]))
ok("no Grace persona in served client", grace_left == 0)

print("== 6 · FOCUS SESSIONS (accountability timer) ==")
st, d = http("http://localhost:4719/focus/state", method="GET")
FOCUS_KEYS = ("on", "paused", "sergeant", "remain_ms", "total_ms", "on_target",
              "drifts", "drift_sec", "grace_left_ms", "eyes_fresh", "nag_s", "snoozed",
              "excused", "say", "report", "deferred")     # S19w: the deferred tab lock is exposed
ok("focus state serves the whitelist", st == 200 and isinstance(d, dict) and tuple(d.keys()) == FOCUS_KEYS,
   str(d)[:80])
ok("focus state carries no app identity", isinstance(d, dict) and
   not re.search(r"\bcom\.[a-z0-9-]+\.", json.dumps(d)))
st, d = http("http://localhost:4719/focus/probe", {})
probe_rows = (d or {}).get("results") if isinstance(d, dict) else None
bad = [r["n"] for r in (probe_rows or []) if not r.get("ok")]
ok("focus engine battery (grace/escalation/screen/excuse/nag/snooze/pause/report/no-leak/zero-key)",
   bool(probe_rows) and len(probe_rows) >= 29 and not bad, f"failing: {bad}")
st, body = http("http://localhost:4719/focus.js", method="GET", timeout=15)
ftext = body.decode(errors="ignore") if isinstance(body, bytes) else str(body)
ok("served /focus.js current", st == 200 and "FOCUSPROBE" in ftext and "focusChip" in ftext)
st, body = http("http://localhost:4719/", method="GET", timeout=15)
htext = body.decode(errors="ignore") if isinstance(body, bytes) else str(body)
ok("viewer loads the focus module", "focus.js" in htext)
# ⚖ S19l: a second Chrome instance (stray --user-data-dir test browser) hijacks AppleEvent
# routing — the windowless twin answers "no windows" and tab watching goes silently blind
import subprocess as _sp
_chr = [l for l in _sp.run(["ps", "-axo", "command"], capture_output=True, text=True).stdout.splitlines()
        if "Google Chrome.app/Contents/MacOS/Google Chrome" in l and "Helper" not in l]
if len(_chr) > 1:
    warn("MULTIPLE Chrome instances running (%d) — tab watching may be blind; close the spare" % len(_chr))
else:
    ok("single Chrome instance (tab watching routable)", True)

print("== 7 · TELEGRAM LIVE PUSH ==")
if "--push" in sys.argv:
    spec3 = importlib.util.spec_from_file_location("_pf_pocket", "pocket.py")
    P = importlib.util.module_from_spec(spec3); spec3.loader.exec_module(P)
    P.CTX.update(cfg=CFG, root=HERE)
    P.load_state()
    if P.STATE["chats"]:
        P.push_call_report("✅ Preflight complete, sir — text and voice channels both live.", None)
        ok("telegram: text + voice pushed to your phone", True)
    else:
        ok("telegram: paired chat found", False)
else:
    warn("telegram push skipped (run with --push to send the real test)")

try:
    import re as _re, json as _json
    _m = _re.search(r"const GRAPH\s*=\s*(\{.*\});", open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer", "graph-data.js"), encoding="utf-8").read(), _re.S)
    CORPUS_FOR_PREFLIGHT = [dict(n, _idx=i) for i, n in enumerate(_json.loads(_m.group(1)).get("nodes", [])) if n.get("p")] if _m else []
except Exception:
    CORPUS_FOR_PREFLIGHT = []
print("== 8 · REFLEX (Jev) ==")
_ts = CFG.get("typesafe") or {}
if not (_ts.get("api_key") or "").strip() or str(_ts.get("api_key", "")).startswith("PUT-"):
    warn("reflex: no TypeSafe key in config.json → Jarvis runs on regex/rules only (optional organ)")
else:
    st8, d8 = http("http://127.0.0.1:4719/reflex/diag", timeout=8)
    ok("reflex: /reflex/diag served", st8 == 200 and isinstance(d8, dict) and "gates" in d8)
    ok("reflex: enabled with key + pinned model", bool(isinstance(d8, dict) and d8.get("enabled")) and str(d8.get("model", "")).startswith("jev-1."),
       detail=str(d8)[:120])
    st9, d9 = http("http://127.0.0.1:4719/reflex/prepass", {"text": "Jarvis, what did the Summit and Sons kickoff decide about the deposit?", "ctx": {}}, timeout=12)
    dec = (d9 or {}).get("decision") if isinstance(d9, dict) else None
    ok("reflex: live prepass answers in budget", st9 == 200 and bool(dec) and (d9.get("ms") or 9999) < 2500,
       detail=("%s ms lane=%s" % ((d9 or {}).get("ms"), (dec or {}).get("lane"))) if isinstance(d9, dict) else str(d9)[:120])
    ok("reflex: vault question routed to vault_question lane", bool(dec) and dec.get("lane") == "vault_question",
       detail=str(dec)[:160])
    st10, d10 = http("http://127.0.0.1:4719/reflex/recall", {"question": "What did the Summit and Sons kickoff decide about the deposit?"}, timeout=12)
    ok("reflex: live recall returns verdict + probabilities", st10 == 200 and isinstance(d10, dict) and d10.get("verdict") in ("found", "absent", "unsure") and isinstance(d10.get("probs"), list),
       detail=str(d10)[:160] if not isinstance(d10, dict) else "verdict=%s has=%s ms=%s" % (d10.get("verdict"), d10.get("has"), d10.get("ms")))
    # S25c (2026-09-22): the STT-proof correction, offline (no Jev call): "side view" → CiteVue, and "is CiteVue" / "the AI Workshop" keep their words
    try:
        import importlib, reflex as _RX; importlib.reload(_RX)
        _RX.CTX["corpus"] = lambda: CORPUS_FOR_PREFLIGHT
        _cases = [("what is CiteVue and what does it charge", "what is CiteVue and what does it charge"), ("what is side view and what does it charge", "what is CiteVue and what does it charge"),
                  ("tell me about the AI Workshop", "tell me about the AI Workshop"), ("what does it charge", "what does it charge"),
                  ("Travis can you pull up my free school community", "can you pull up my Free Skool Community")]   # S25d: the misheard wake word + a 3-word label
        _bad = []
        for _q, _want in _cases:
            _RX.fuzzy_hits(_q); _got = _RX.correct_question(_q)
            if _got.lower() != _want.lower(): _bad.append("%r → %r" % (_q, _got))
        ok("reflex: speech-to-vault name correction (offline)", not _bad, detail="; ".join(_bad)[:200] or "5 cases")
    except Exception as _e:
        ok("reflex: speech-to-vault name correction (offline)", False, detail=str(_e)[:120])
    # S25c (2026-09-22): the urgency governor — mode + gates present, and a staged card scores in budget (no card is raised)
    gv = (d8 or {}).get("governor") if isinstance(d8, dict) else None
    ok("governor: mode + gates served by diag", bool(gv) and gv.get("mode") in ("shadow", "live", "off") and set(gv.get("gates", {})) == {"speak", "urgent", "money"},
       detail=str(gv)[:140])
    st13, d13 = http("http://127.0.0.1:4719/reflex/govern", {"card": {"title": "A payment of 4,250 dollars just landed", "body": "Invoice 2026-001 to Mike Johnson was paid in full at 1:52 this afternoon through Stripe.", "source": "deals", "priority": "high"}, "dnd": {"focus": False, "quiet": False, "rules": {"money": "always"}}, "old": True}, timeout=12)
    ok("governor: staged money card scores in budget", st13 == 200 and isinstance(d13, dict) and "score" in d13 and (d13.get("ms") or 9999) < 2500 and float((d13.get("nouls") or {}).get("money", 0)) >= 0.5,
       detail=("score=%s money=%s speak=%s ms=%s" % (d13.get("score"), (d13.get("nouls") or {}).get("money"), d13.get("speak"), d13.get("ms"))) if isinstance(d13, dict) else str(d13)[:120])
    # S25c (2026-09-22): filming mode — narration to camera stays quiet, an address without his name is answered
    st11, d11 = http("http://127.0.0.1:4719/reflex/prepass", {"text": "so what I'm building here is a reflex layer for my AI assistant and it decides in about two hundred milliseconds", "ctx": {"recording_mode": True}}, timeout=12)
    dec11 = (d11 or {}).get("decision") if isinstance(d11, dict) else None
    ok("reflex: filming mode keeps quiet on narration", st11 == 200 and bool(dec11) and dec11.get("addressed_ok") is False,
       detail=("addressed=%s narrating=%s gate=%s" % (((d11.get("answers") or {}).get("addressed") or {}).get("noul"), dec11.get("narrating"), (dec11.get("gates") or {}).get("addressed"))) if dec11 else str(d11)[:120])
    st12, d12 = http("http://127.0.0.1:4719/reflex/prepass", {"text": "what did your reflexes cost today", "ctx": {"recording_mode": True}}, timeout=12)
    dec12 = (d12 or {}).get("decision") if isinstance(d12, dict) else None
    ok("reflex: filming mode answers a no-name address", st12 == 200 and bool(dec12) and dec12.get("addressed_ok") is True,
       detail=("addressed=%s narrating=%s gate=%s" % (((d12.get("answers") or {}).get("addressed") or {}).get("noul"), dec12.get("narrating"), (dec12.get("gates") or {}).get("addressed"))) if dec12 else str(d12)[:120])

# S28 (2026-10-13): REA website teardowns — the bay is ready, spoken addresses parse, and no
# investigation Chrome is left running (a 2nd Chrome instance hijacks the FOCUS tab lane)
st14, d14 = http("http://127.0.0.1:4719/teardown/diag", timeout=8)
ok("teardown: bay ready (REA pinned, Node 22.19+, Chrome, vault)",
   st14 == 200 and isinstance(d14, dict) and bool(d14.get("ready")) and d14.get("rea_version") == d14.get("rea_pinned"),
   detail=(("REA %s · node %s" % (d14.get("rea_version"), d14.get("node"))) if d14.get("ready") else "; ".join(d14.get("problems") or [])) if isinstance(d14, dict) else str(d14)[:120])
try:
    import importlib, teardown as _TD; importlib.reload(_TD)
    _cases = [("igloo dot inc", "https://igloo.inc"), ("stripe.com slash pricing", "https://stripe.com/pricing"),
              ("localhost:5001", "http://localhost:5001"), ("make it pop", None), ("wikipedia.org", "https://wikipedia.org")]
    _bad = ["%r → %r" % (q, _TD.normalize_target(q)) for q, want in _cases if _TD.normalize_target(q) != want]
    _st, _bn = _TD._fingerprint([("x.js", '/**\n * @license\n * Copyright 2010-2024 Three.js Authors\n */const Aa="165";GSAP 3.12.5 nearCoCBuffer')], {})
    _names = {x["name"]: x["version"] for x in _st}
    if _names.get("Three.js") != "r165" or _names.get("GSAP") != "3.12.5" or "Depth of field" not in _names:
        _bad.append("fingerprints → %s" % _names)
    ok("teardown: spoken addresses + stack fingerprints (offline)", not _bad, detail="; ".join(_bad)[:200] or "5 addresses · 3 fingerprints")
except Exception as _e:
    ok("teardown: spoken addresses + stack fingerprints (offline)", False, detail=str(_e)[:120])
# S29 (2026-10-13): the FULL REA catalog + the builder — REA's MCP server boots for workers with its
# whole tool list, the bay advertises both new mission kinds, and the hidden-browser smoke test nets
# the three planted errors on viewer/smoke-probe.html (exception, console error, 404)
def _rea_tool_count(cmd, args, timeout=45):
    import subprocess as _sp, select as _sel
    p = _sp.Popen([cmd] + list(args), stdin=_sp.PIPE, stdout=_sp.PIPE, stderr=_sp.DEVNULL, text=True)
    def send(o):
        p.stdin.write(json.dumps(o) + "\n"); p.stdin.flush()
    def recv(want):
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = _sel.select([p.stdout], [], [], 0.5)
            if not r:
                continue
            line = p.stdout.readline()
            if not line:
                return None
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("id") == want:
                return o
        return None
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "preflight", "version": "0"}}})
        if not recv(1):
            return -1
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        return len((((recv(2) or {}).get("result") or {}).get("tools")) or [])
    finally:
        try:
            p.kill()
        except Exception:
            pass
try:
    import importlib as _il2, teardown as _TD2; _il2.reload(_TD2)
    _mcpf = _TD2.mcp_config(); _reg = json.load(open(_mcpf))["mcpServers"]["rea"]
    _n = _rea_tool_count(_reg["command"], _reg["args"])
    ok("rea: full MCP catalog boots for workers (170 tools)", _n >= 150, detail="%s tools from %s" % (_n, _mcpf))
except Exception as _e:
    ok("rea: full MCP catalog boots for workers (170 tools)", False, detail=str(_e)[:120])
st15, d15 = http("http://127.0.0.1:4719/mission_kinds", timeout=8)
ok("missions: REVERSE ENGINEER + BUILD kinds wired (REA MCP + claude CLI present)",
   st15 == 200 and isinstance(d15, dict) and {"rea", "build"} <= set(d15.get("kinds") or []) and bool(d15.get("rea_mcp")) and bool(d15.get("claude")),
   detail=str(d15)[:140])
try:
    _sm = _TD2.smoke_test("http://127.0.0.1:4719/smoke-probe.html", None, seconds=3)
    _txt = " | ".join(_sm.get("errors") or [])
    ok("build: hidden-browser smoke test nets the planted errors (exception + console + 404)",
       (not _sm.get("ok")) and ("planted exception" in _txt) and ("planted console" in _txt) and ("404" in _txt or "failed load" in _txt),
       detail=(_txt or str(_sm))[:220])
except Exception as _e:
    ok("build: hidden-browser smoke test nets the planted errors (exception + console + 404)", False, detail=str(_e)[:120])
# S29f (2026-10-13): the dispatcher reads spoken site names (DNS-checked), pronouns, and apps — dry run, nothing starts
_dd = []
for _t, _q, _k, _v in [("Igloo ink", "reverse engineer Igloo ink for me", "web", "https://igloo.inc"),
                       ("it for me", "I'm looking at this website which is Igloo ink can you reverse engineer it for me", "web", "https://igloo.inc"),
                       ("the Notes app on my Mac", "reverse engineer the Notes app on my Mac", "app", "/System/Applications/Notes.app"),
                       ("it", "reverse engineer it", "ask", None)]:
    _st, _d = http("http://127.0.0.1:4719/teardown/dispatch", {"target": _t, "question": _q, "dry": True}, timeout=20)
    if not (_st == 200 and isinstance(_d, dict) and _d.get("kind") == _k and (_v is None or _d.get("value") == _v)):
        _dd.append("%r → %s" % (_t, (_d.get("kind"), _d.get("value")) if isinstance(_d, dict) else _d))
ok("teardown: dispatcher resolves spoken sites / pronouns / apps (dry)", not _dd, detail="; ".join(_dd)[:220] or "4 cases")
try:
    import subprocess as _sp_td
    _left = _sp_td.run(["pgrep", "-f", ".jarvis-tools/rea/profiles"], capture_output=True, text=True).stdout.split()
except Exception as _e:
    _left = ["check failed: %s" % str(_e)[:60]]
ok("teardown: no investigation Chrome left running", not _left, detail=("%d process(es) — pkill -f .jarvis-tools/rea/profiles" % len(_left)) if _left else "")

print("\n" + "=" * 52)
print(f"PREFLIGHT: {len(PASS)} pass · {len(FAIL)} FAIL · {len(WARN)} warn  ·  brain={MODEL_NOW}")
for f in FAIL:
    print("  ✗ " + f)
sys.exit(1 if FAIL else 0)
