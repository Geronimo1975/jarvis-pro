#!/usr/bin/env python3
"""Jarvis V5 — the MISSION BAY (six agentic missions on the claude -p sandbox pattern).

Soft-imported by server.py: every /mission* request is routed to handle(); init(ctx) is
called at boot with the server's helpers (raise_card, call_model, jpersona, …).

Missions (POST /mission_start {kind, brief}):
  fleet     — SCOUT + FORGE + SAGE draft-safe workers in parallel; report written python-side
  buildapp  — one worker builds a single-file dark-HUD index.html (Write/Edit allowed, app/ dir only)
  reaper    — Gmail read sweep → subscription ledger → per-sub gated cancellation DRAFTS
  warroom   — vidIQ latest-video status report (read-only, no gated step)
  announce  — brand-voice social drafts → gated Blotato posting (list_accounts + create_post only)
  haters    — vidIQ comment sweep + reply drafts → gated youtube-replies skill posting
  rea       — S29: REA's FULL MCP catalog (170 tools) in a worker — apps, files, packages, bundles → a vault teardown
  build     — S29: the general BUILDER — multi-file web app, pinned CDNs, smoke-tested in a hidden Chrome, opened

Safety: DRAFT runs get run_agent's full denylist PLUS all Blotato tools; EXECUTE runs get the
narrowest deny-set that leaves only the sanctioned tool open (mail SEND is denied everywhere).
Workers write only inside agent-workspace/missions/<id>/.  Python 3 stdlib only.
"""
import os, re, json, time, uuid, shutil, threading, subprocess, urllib.parse

# ---------- context (filled by init) ----------
CTX = {}
ROOT = os.path.dirname(os.path.abspath(__file__))
MISSIONS_DIR = os.path.join(ROOT, "agent-workspace", "missions")
LOG_FILE = os.path.join(ROOT, "jarvis-missions.jsonl")
CLAUDE_BIN = ""
BASE_DENY, DRAFT_DENY = [], []
LOCK = threading.Lock()
LOG_LOCK = threading.Lock()
MISSIONS = {}          # id -> {kind,title,icon,brief,status,events,result,pending,created,procs}
MAX_EVENTS = 800

KINDS = {"fleet": ("⚔️", "THE FLEET"),          "buildapp": ("🛠️", "BUILD-ME-AN-APP"),
         "reaper": ("💰", "SUBSCRIPTION REAPER"), "warroom": ("📊", "CHANNEL WAR ROOM"),
         "announce": ("📣", "ANNOUNCE-IT-EVERYWHERE"), "haters": ("🔥", "READ-THE-HATERS"),
         "rea": ("🔬", "REVERSE ENGINEER"),        "build": ("🏗️", "BUILD")}          # S29
NEEDS_BRIEF = ("fleet", "buildapp", "announce", "rea", "build")
PLATFORMS = ("twitter", "linkedin", "instagram", "threads", "facebook")

def init(ctx):
    """Called once at server boot with dict(cfg, root, port, raise_card, call_model, claude_read, jpersona)."""
    global CTX, ROOT, MISSIONS_DIR, LOG_FILE, CLAUDE_BIN, BASE_DENY, DRAFT_DENY
    CTX = dict(ctx or {})
    cfg = CTX.get("cfg") or {}
    ROOT = CTX.get("root") or ROOT
    MISSIONS_DIR = os.path.join(ROOT, "agent-workspace", "missions")
    LOG_FILE = os.path.join(ROOT, "jarvis-missions.jsonl")
    try:
        os.makedirs(MISSIONS_DIR, exist_ok=True)
    except OSError:
        pass
    CLAUDE_BIN = cfg.get("claude_bin") or shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    # DRAFT safety: run_agent's structural denylist, copied exactly (config-overridable the same way)…
    BASE_DENY = list((cfg.get("agent") or {}).get("disallow") or [
        "Bash", "Write", "Edit", "Task",
        "mcp__*send*", "mcp__*post*", "mcp__*reply*", "mcp__*delete*",
        "mcp__*publish*", "mcp__*deploy*", "mcp__*spend*", "mcp__*pay*", "mcp__*buy*",
    ])
    # …plus ALL Blotato tools: a draft must never even see the social cannon.
    DRAFT_DENY = BASE_DENY + ["mcp__blotato*", "mcp__*blotato*"]

# EXECUTE deny-sets (user has said "do it"; still the narrowest workable surface, sends stay dead):
#  reaper  → full draft deny (+blotato): gmail create-draft matches no pattern so it alone stays open
#  announce→ mcp__*post* lifted so blotato_create_post works; every OTHER blotato mutator re-denied
#  haters  → Bash allowed (the youtube-replies skill posts via its own scripts); MCP sends all denied
def exec_deny(kind):
    if kind == "announce":
        return ["Bash", "Write", "Edit", "Task",
                "mcp__*send*", "mcp__*reply*", "mcp__*delete*", "mcp__*publish*", "mcp__*deploy*",
                "mcp__*spend*", "mcp__*pay*", "mcp__*buy*",
                "mcp__*blotato_create_source*", "mcp__*blotato_create_visual*",
                "mcp__*blotato_create_presigned*", "mcp__*blotato_update*"]
    if kind == "haters":
        return ["Bash", "Write", "Edit", "Task",   # S23: posting runs in Python now
                "mcp__*send*", "mcp__*post*", "mcp__*reply*", "mcp__*delete*", "mcp__*publish*",
                "mcp__*deploy*", "mcp__*spend*", "mcp__*pay*", "mcp__*buy*",
                "mcp__blotato*", "mcp__*blotato*"]
    return list(DRAFT_DENY)           # reaper (and default): draft-tight, gmail draft-creation open

# ---------- small helpers ----------
def get(mid):
    with LOCK:
        return MISSIONS.get(str(mid or ""))

def mdir(mid):
    d = os.path.join(MISSIONS_DIR, mid)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d

def log_line(rec):
    try:
        with LOG_LOCK:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
    except Exception:
        pass

def emit(mid, agent, kind, label):
    ev = {"ts": int(time.time()), "agent": str(agent)[:12], "kind": kind, "label": str(label)[:160]}
    with LOCK:
        m = MISSIONS.get(mid)
        if m is not None and len(m["events"]) < MAX_EVENTS:
            m["events"].append(ev)
    log_line(dict(ev, id=mid))

def card(title, body=""):
    try:
        rc = CTX.get("raise_card")
        if rc:
            rc("notify", title, body, source="mission", speak=False)   # S29c: the dock/panel already speaks the result — two voices overlapped
    except Exception:
        pass

def quip(prompt, fallback):
    """One persona-voiced line via the server's model helper; never raises, never blocks a mission."""
    try:
        cm, jp = CTX.get("call_model"), CTX.get("jpersona")
        if cm:
            out, err = cm([{"role": "user", "content": prompt}], (jp() if jp else ""), 220)
            if not err and out and out != "(no answer)":
                return out.strip()[:300]
    except Exception:
        pass
    return fallback

def parse_json_block(text):
    """Pull the model's STRICT-JSON answer out of sloppy output: last ```json fence wins, else the
    outermost braces; trailing commas forgiven. Returns a dict or None."""
    if not text:
        return None
    body = None
    for fm in re.finditer(r"```(?:json)?\s*\n?(.*?)```", text, re.S | re.I):
        body = fm.group(1)
    cand = body if body is not None else text
    i, j = cand.find("{"), cand.rfind("}")
    if i < 0 or j <= i:
        cand = text
        i, j = cand.find("{"), cand.rfind("}")
        if i < 0 or j <= i:
            return None
    raw = cand[i:j + 1]
    for attempt in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
        try:
            d = json.loads(attempt)
            return d if isinstance(d, dict) else None
        except Exception:
            pass
    return None

def _num(x):
    try:
        if isinstance(x, str):
            x = re.sub(r"[^0-9.\-]", "", x) or "0"
        return round(float(x), 2)
    except Exception:
        return 0.0

# ---------- the runner: one sandboxed claude -p, stream-json → live events ----------
READ_HINT = ("read", "grep", "glob", "search", "find", "get", "list", "fetch", "watch",
             "stats", "analytics", "history", "poll", "transcript")
def tool_label(name, inp):
    """(kind, short human label) for a tool_use event — 'reading Gmail…', 'Write index.html'."""
    n = str(name or "tool")
    ln = n.lower()
    if ln in ("write", "edit", "multiedit", "notebookedit"):
        f = os.path.basename(str((inp or {}).get("file_path") or (inp or {}).get("path") or "")) or "a file"
        return "write", f"{n} {f}"
    if ln.startswith("mcp__rea__"):                     # S29: the REA catalog, named plainly in the feed
        return "read", "REA: " + ln[len("mcp__rea__"):].replace("_", " ") + "…"
    if "gmail" in ln or ("mail" in ln and "mcp__" in ln):
        return ("write", "drafting an email…") if "draft" in ln else ("read", "reading Gmail…")
    if "calendar" in ln:
        return "read", "checking the calendar…"
    if "vidiq" in ln:
        if "comment" in ln: return "read", "reading YouTube comments…"
        if "channel" in ln or "video" in ln or "stats" in ln: return "read", "pulling channel numbers…"
        return "read", "consulting vidIQ…"
    if "blotato" in ln:
        return ("tool", "posting via Blotato…") if "create_post" in ln else ("read", "checking Blotato accounts…")
    if "web_search" in ln or ln == "websearch":
        return "read", "searching the web…"
    if ln == "webfetch":
        return "read", "fetching a page…"
    if ln == "bash":
        return "tool", ("shell: " + str((inp or {}).get("command") or "command")[:70])
    if ln == "task":
        return "tool", "delegating a sub-task…"
    short = ln.rsplit("__", 1)[-1].replace("_", " ")
    return ("read", short + "…") if any(h in ln for h in READ_HINT) else ("tool", short)

STAGE_RE = re.compile(r"\bSTAGE:\s*(SCAFFOLD|CODE|TEST|LAUNCH|ROUTE|INSPECT|WRITE)\b", re.I)
def run_worker(mid, agent, prompt, deny, cwd, timeout, hook=None, mcp=None):
    """Spawn `claude -p … --output-format stream-json --verbose` with run_agent's sandbox flags
    (bypassPermissions + denylist, NO --add-dir), stream events into the mission buffer.
    Returns (final_text, err)."""
    if not (CLAUDE_BIN and os.path.isfile(CLAUDE_BIN) and os.access(CLAUDE_BIN, os.X_OK)):
        emit(mid, agent, "error", "claude CLI not found")
        return None, "claude not available"
    try:
        os.makedirs(cwd, exist_ok=True)
    except OSError:
        pass
    args = ([CLAUDE_BIN, "-p", "--output-format", "stream-json", "--verbose"]
            + (["--mcp-config", mcp, "--strict-mcp-config"] if mcp else [])   # S29: exactly these MCP servers, nothing else
            + ["--disallowedTools"] + list(deny)
            + ["--permission-mode", "bypassPermissions", prompt])
    try:
        proc = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, text=True)
    except Exception as e:
        emit(mid, agent, "error", f"spawn failed ({e.__class__.__name__})")
        return None, "spawn failed"
    with LOCK:
        m = MISSIONS.get(mid)
        if m is not None:
            m.setdefault("procs", []).append(proc)
    timed = [False]
    def _kill():
        timed[0] = True
        try:
            proc.kill()
        except Exception:
            pass
    watchdog = threading.Timer(timeout, _kill)
    watchdog.daemon = True
    watchdog.start()
    emit(mid, agent, "spawn", "deploying…")
    final, err, booted = None, None, False
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            t = obj.get("type")
            if t == "system" and not booted:       # the CLI emits many system events — announce once
                booted = True
                emit(mid, agent, "spawn", "online — sandboxed")
            elif t == "assistant":
                for b in ((obj.get("message") or {}).get("content") or []):
                    bt = b.get("type")
                    if bt == "tool_use":
                        k, lbl = tool_label(b.get("name"), b.get("input"))
                        emit(mid, agent, k, lbl)
                        if hook:
                            try: hook(k, lbl)
                            except Exception: pass
                    elif bt == "text":
                        txt = (b.get("text") or "").strip()
                        if not txt:
                            continue
                        for sm in STAGE_RE.finditer(txt):
                            emit(mid, agent, "stage", sm.group(1).upper())
                        say = next((l.strip() for l in txt.splitlines()
                                    if l.strip() and not l.strip().startswith(("```", "{", "STAGE:"))), "")
                        if say:
                            emit(mid, agent, "say", say[:110])
            elif t == "result":
                if obj.get("is_error") or (obj.get("subtype") and obj.get("subtype") != "success"):
                    err = str(obj.get("result") or obj.get("error") or obj.get("subtype"))[:200]
                else:
                    final = obj.get("result") or ""
    except Exception as e:
        err = err or f"stream broke ({e.__class__.__name__})"
    finally:
        watchdog.cancel()
        try:
            proc.stdout.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except Exception:
            _kill()
    if timed[0]:
        emit(mid, agent, "error", f"timed out after {timeout}s")
        return None, "timeout"
    if final is None and err is None:
        err = f"exited {proc.returncode} with no result"
    if err:
        emit(mid, agent, "error", err[:140])
        return None, err
    emit(mid, agent, "done", "landed")
    return final, None

# ---------- lifecycle helpers ----------
def finish(mid, result, summary=""):
    m = get(mid)
    if not m:
        return
    with LOCK:
        m["result"], m["status"] = result, "done"
    emit(mid, "JARVIS", "done", "mission complete")
    card(f"{m['icon']} {m['title']} — done", summary)
    log_line({"id": mid, "ev": "done", "ts": int(time.time())})

def await_confirm(mid, result, pending, summary=""):
    m = get(mid)
    if not m:
        return
    with LOCK:
        m["result"], m["pending"], m["status"] = result, pending, "awaiting_confirm"
    emit(mid, "JARVIS", "done", "awaiting your word, sir")
    card(f"{m['icon']} {m['title']} — done", summary)
    log_line({"id": mid, "ev": "awaiting_confirm", "ts": int(time.time())})

def fail(mid, note):
    m = get(mid)
    if not m:
        return
    with LOCK:
        m["status"] = "error"
    emit(mid, "JARVIS", "error", str(note)[:160])
    log_line({"id": mid, "ev": "error", "note": str(note)[:160], "ts": int(time.time())})

# ---------- kind 1: THE FLEET (three parallel draft-safe personas) ----------
FLEET_CREW = (
    ("SCOUT", "You are SCOUT, the reconnaissance agent of the user's personal AI fleet. Mission "
     "brief: \"{brief}\". Research it NOW using your own knowledge plus any READ-ONLY connected "
     "tools you have (web search, mail search, analytics). You have NO access to the user's local "
     "notes or files — do not attempt to read any; work from knowledge and live tools only. "
     "FINAL MESSAGE = a tight markdown recon memo: the landscape, hard facts and numbers, "
     "opportunities, risks. No preamble, no questions back."),
    ("FORGE", "You are FORGE, the maker agent of the user's personal AI fleet. Mission brief: "
     "\"{brief}\". Draft the actual deliverable — a plan, script, page copy, outline, whatever the "
     "brief calls for — as polished markdown. You CANNOT write files in this mode: your FINAL "
     "MESSAGE **is** the artifact, so make it complete and ready to use. No preamble."),
    ("SAGE", "You are SAGE, the strategist agent of the user's personal AI fleet. Mission brief: "
     "\"{brief}\". Stress-test the idea like a sharp, honest advisor: the strongest objections, "
     "what most people get wrong, the risks worth respecting — then close with the 5 highest-"
     "leverage NEXT ACTIONS as a numbered list. Markdown, no preamble."),
)
def run_fleet(mid):
    m = get(mid)
    outs, errs = {}, {}
    def work(name, prompt):
        out, err = run_worker(mid, name, prompt, DRAFT_DENY, mdir(mid), 240)
        outs[name.lower()] = (out or "").strip()
        if err:
            errs[name] = err
    threads = [threading.Thread(target=work, args=(n, p.format(brief=m["brief"])), daemon=True)
               for n, p in FLEET_CREW]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=300)
    sections = {k: outs.get(k, "") for k in ("scout", "forge", "sage")}
    if not any(sections.values()):
        return fail(mid, "the whole fleet came back empty (" + "; ".join(errs.values()) + ")")
    md = (f"# THE FLEET — {m['brief']}\n\n_{time.strftime('%Y-%m-%d %H:%M')}_\n\n"
          f"## ⚔️ SCOUT — recon\n\n{sections['scout'] or '_(no report)_'}\n\n"
          f"## 🔨 FORGE — the draft\n\n{sections['forge'] or '_(no draft)_'}\n\n"
          f"## 🧠 SAGE — critique & next actions\n\n{sections['sage'] or '_(no critique)_'}\n")
    try:                                    # python writes the artifact — never the sandboxed agents
        with open(os.path.join(mdir(mid), "FLEET.md"), "w", encoding="utf-8") as f:
            f.write(md)
    except OSError:
        pass
    summary = quip(f"Your three-agent fleet (SCOUT research, FORGE draft, SAGE critique) just "
                   f"completed a mission on '{m['brief']}'. ONE short dry sentence telling the user "
                   "it's done and worth a look.", "The fleet has landed, sir — the report is ready.")
    finish(mid, {"sections": sections, "summary": summary,
                 "file": f"agent-workspace/missions/{mid}/FLEET.md"}, summary)

# ---------- kind 2: BUILD-ME-AN-APP (Write/Edit allowed, app/ dir only) ----------
def run_buildapp(mid):
    m = get(mid)
    app = os.path.join(mdir(mid), "app")
    try:
        os.makedirs(app, exist_ok=True)
    except OSError:
        pass
    deny = [d for d in DRAFT_DENY if d not in ("Write", "Edit")]     # hands for THIS kind only
    prompt = ("You are FORGE, the user's app-builder. Print the line 'STAGE: SCAFFOLD' first. Build "
              f"a COMPLETE, working single-file web app for this brief: \"{m['brief']}\". Rules: "
              "exactly ONE file — index.html in the CURRENT directory — with all CSS and JS inline. "
              "No CDNs, no external requests, no other files, fully self-contained. Style it as a "
              "dark sci-fi HUD: near-black background, emerald #34d399 accents, monospace type, "
              "glass panels, subtle glow. Make it genuinely functional, not a mockup. Print "
              "'STAGE: CODE' before writing the file, 'STAGE: TEST' while double-checking your "
              "markup and logic, and 'STAGE: LAUNCH' when the file is final. FINAL MESSAGE: one "
              "short line describing what you built.")
    seen = {"code": False}
    def hook(kind, _label):
        if kind == "write" and not seen["code"]:
            seen["code"] = True
            emit(mid, "FORGE", "stage", "CODE")     # inferred even if the model forgets to print it
    out, err = run_worker(mid, "FORGE", prompt, deny, app, 240, hook)
    idx = os.path.join(app, "index.html")
    if not os.path.isfile(idx):
        return fail(mid, err or "no index.html was produced, sir")
    emit(mid, "FORGE", "stage", "LAUNCH")
    url = f"/mission_app/{mid}/index.html"
    summary = quip(f"You just built the user a little web app: {(out or m['brief'])[:140]}. ONE short "
                   "dry sentence announcing it's ready to open.", "Your app is built and ready, sir.")
    finish(mid, {"url": url, "note": (out or "").strip()[:200], "summary": summary}, summary)

# ---------- kind 3: SUBSCRIPTION REAPER (Gmail read sweep → gated cancellation drafts) ----------
REAPER_PROMPT = (
    "You are the SUBSCRIPTION REAPER, hunting recurring charges for the user. Using ONLY your "
    "connected Gmail READ tools (search/find email), sweep roughly the last 12 months of their "
    "inbox for receipts, renewals, invoices and subscription charges (search terms like receipt, "
    "renewal, invoice, subscription, 'your payment', 'has been charged'). Dedupe by service; for "
    "annual plans set amount_monthly to the annual price divided by 12 and note it. STRICTLY READ "
    "ONLY — do not send, reply, archive, draft or change anything. FINAL MESSAGE: ONLY a ```json "
    "fence, with NOTHING after it:\n```json\n{\"subs\": [{\"name\": \"...\", \"amount_monthly\": 9.99, "
    "\"cadence\": \"monthly|annual\", \"last_seen\": \"YYYY-MM-DD\", \"note\": \"...\"}], "
    "\"total_monthly\": 123.45}\n```")
def run_reaper(mid):
    m = get(mid)
    hint = (" Focus: " + m["brief"]) if m["brief"] else ""
    out, err = run_worker(mid, "REAPER", REAPER_PROMPT + hint, DRAFT_DENY, mdir(mid), 240)
    if err:
        return fail(mid, err)
    d = parse_json_block(out)
    if not d or not isinstance(d.get("subs"), list):
        return fail(mid, "the ledger came back unreadable, sir")
    subs = []
    for s in d["subs"][:40]:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip()[:60]
        if not name:
            continue
        subs.append({"name": name, "amount_monthly": _num(s.get("amount_monthly")),
                     "cadence": str(s.get("cadence") or "monthly")[:12],
                     "last_seen": str(s.get("last_seen") or "")[:12],
                     "note": str(s.get("note") or "")[:120]})
    total = _num(d.get("total_monthly")) or round(sum(s["amount_monthly"] for s in subs), 2)
    summary = quip(f"You just audited the user's email and found {len(subs)} subscriptions costing "
                   f"about ${total} a month. ONE short dry sentence delivering that news.",
                   f"{len(subs)} subscriptions, roughly ${total} a month, sir. Say the word and I draft the cancellations.")
    await_confirm(mid, {"subs": subs, "total_monthly": total, "summary": summary},
                  {"kind": "kill", "items": [s["name"] for s in subs], "drafted": []}, summary)

def reaper_confirm(mid, item):
    m = get(mid)
    subs = ((m.get("result") or {}).get("subs")) or []
    names = [s["name"] for s in subs]
    il = str(item).lower()
    targets = names if il == "all" else [n for n in names if il in n.lower() or n.lower() in il]
    if not targets:
        return emit(mid, "JARVIS", "error", f"no subscription matching '{item}', sir")
    for name in targets:
        emit(mid, "REAPER", "tool", f"drafting cancellation — {name}…")
        prompt = ("The user has CONFIRMED cancelling their subscription to: " + name + ". Using "
                  "ONLY the Gmail draft-creation tool (create a draft — NEVER send anything), write "
                  "a polite, firm cancellation email for that service into their Drafts folder: ask "
                  "to cancel at the end of the current period and to confirm by reply. If you can "
                  "find the service's billing/support address from past receipts (read-only search), "
                  "address it there; otherwise leave a sensible placeholder recipient and say so. "
                  "FINAL MESSAGE: one short line confirming the draft exists (or what blocked it).")
        out, err = run_worker(mid, "REAPER", prompt, exec_deny("reaper"), mdir(mid), 300)
        if err:
            emit(mid, "JARVIS", "error", f"✗ {name} — {err[:80]}")
            continue
        emit(mid, "JARVIS", "done", f"✓ {name} — cancellation drafted")
        card(f"💰 Cancellation drafted — {name}", (out or "").strip()[:200] or
             "The draft is in your Gmail Drafts, sir — read it, then send it yourself.")
        with LOCK:
            p = m.get("pending") or {}
            if name not in (p.get("drafted") or []):
                p.setdefault("drafted", []).append(name)

# ---------- kind 4: CHANNEL WAR ROOM (vidIQ status report, read-only) ----------
WARROOM_PROMPT = (
    "You are the user's YouTube CHANNEL WAR ROOM analyst. Using your connected vidIQ tools "
    "(vidiq_channel_analytics, vidiq_channel_videos, vidiq_video_stats, vidiq_video_comments…), "
    "build a status report on their channel's LATEST video and overall momentum: last-24h views, "
    "how that compares to their median video at the same age (median_delta as a short string like "
    "'+40% vs median'), subscriber count, watch hours, the 3 most recent videos with view counts, "
    "and the 3 most notable recent comments. READ ONLY — post nothing, reply to nothing. "
    "FINAL MESSAGE: ONLY a ```json fence, NOTHING after it:\n```json\n"
    "{\"headline\": \"...\", \"stats\": {\"views_24h\": 0, \"median_delta\": \"...\", \"subs\": 0, "
    "\"watch_hours\": 0}, \"videos\": [{\"title\": \"...\", \"views\": 0, \"published\": \"...\"}], "
    "\"comments\": [{\"author\": \"...\", \"text\": \"...\", \"likes\": 0}], "
    "\"read\": \"<2 spoken sentences, dry British butler, addressing the user as sir>\"}\n```")
def run_warroom(mid):
    m = get(mid)
    hint = (" Focus: " + m["brief"]) if m["brief"] else ""
    out, err = run_worker(mid, "WARROOM", WARROOM_PROMPT + hint, DRAFT_DENY, mdir(mid), 240)
    if err:
        return fail(mid, err)
    d = parse_json_block(out)
    if not d:
        return fail(mid, "the war room report came back unreadable, sir")
    stats = d.get("stats") or {}
    result = {"headline": str(d.get("headline") or "Channel status")[:140],
              "stats": {"views_24h": stats.get("views_24h", "—"), "median_delta": str(stats.get("median_delta") or "—")[:40],
                        "subs": stats.get("subs", "—"), "watch_hours": stats.get("watch_hours", "—")},
              "videos": [v for v in (d.get("videos") or []) if isinstance(v, dict)][:5],
              "comments": [c for c in (d.get("comments") or []) if isinstance(c, dict)][:5],
              "read": str(d.get("read") or "The war room report is on screen, sir.")[:400]}
    finish(mid, result, result["read"])

# ---------- kind 5: ANNOUNCE-IT-EVERYWHERE (brand-voice drafts → gated Blotato posting) ----------
def brand_voice():
    """missions.py reads the brand-voice file itself — the sandboxed worker can't (no --add-dir)."""
    vault = os.path.expanduser((CTX.get("cfg") or {}).get("vault") or "")
    for p in (os.path.join(vault, "wiki", "social-media", "brand-voice.md"),
              "/path/to/your/vault/wiki/social-media/brand-voice.md"):
        try:
            if p and os.path.isfile(p):
                return open(p, encoding="utf-8", errors="ignore").read()[:2400]
        except OSError:
            continue
    return "(brand voice file unavailable — write as a high-energy builder who shows receipts)"

def run_announce(mid):
    m = get(mid)
    prompt = ("You are the user's social-media HERALD. Draft one post per platform announcing this: "
              f"\"{m['brief']}\". Platforms: twitter, linkedin, instagram, threads, facebook. "
              "Write ONLY from the brand voice below. HARD RULES: the MONEY angle comes first in "
              "every post (what it earns/saves, never 'here's a cool tool'); hokey high-energy "
              "beats polished corporate; the reader is the protagonist ('you'); Instagram gets AT "
              "MOST 5 hashtags (others need none); the ONLY link/CTA allowed is skool.com/aiworkshop-lite. "
              "No tools needed — do not use any. FINAL MESSAGE: ONLY a ```json fence, NOTHING after "
              "it:\n```json\n{\"posts\": [{\"platform\": \"twitter\", \"text\": \"...\"}]}\n```\n\n"
              "BRAND VOICE:\n" + brand_voice())
    out, err = run_worker(mid, "HERALD", prompt, DRAFT_DENY, mdir(mid), 240)
    if err:
        return fail(mid, err)
    d = parse_json_block(out)
    posts = []
    for p in ((d or {}).get("posts") or []):
        if isinstance(p, dict):
            plat = str(p.get("platform") or "").strip().lower()
            text = str(p.get("text") or "").strip()
            if plat in PLATFORMS and text and plat not in [x["platform"] for x in posts]:
                posts.append({"platform": plat, "text": text[:2200]})
    if not posts:
        return fail(mid, "no usable drafts came back, sir")
    summary = quip(f"You drafted announcement posts for {len(posts)} platforms about '{m['brief']}'. "
                   "ONE short dry sentence saying the drafts await approval — nothing posts without it.",
                   f"{len(posts)} drafts ready, sir — say 'post it' and I'll fire them off.")
    await_confirm(mid, {"posts": posts, "summary": summary},
                  {"kind": "posts", "items": [p["platform"] for p in posts], "posted": []}, summary)

def announce_confirm(mid, item):
    m = get(mid)
    posts = ((m.get("result") or {}).get("posts")) or []
    with LOCK:
        rem = set(((m.get("pending") or {}).get("items")) or [])
    il = str(item).lower()
    want = [p for p in posts if p["platform"] in rem and (il == "all" or p["platform"] == il)]
    if not want:
        return emit(mid, "JARVIS", "error", f"nothing left to post for '{item}', sir")
    emit(mid, "HERALD", "tool", "posting to " + ", ".join(p["platform"] for p in want) + "…")
    prompt = ("The user has APPROVED these social posts. Using ONLY the Blotato tools: first call "
              "the blotato list-accounts tool, then for EACH post below create the post via the "
              "blotato create-post tool on the connected account matching its platform (match "
              "names case-insensitively). Post each text EXACTLY as written — no rewriting, no "
              "hashtag additions, no images, no scheduling. If a platform has no connected "
              "account, skip it and report it. FINAL MESSAGE: ONLY a ```json fence, NOTHING after "
              "it:\n```json\n{\"posted\": [\"twitter\"], \"failed\": [{\"platform\": \"linkedin\", "
              "\"reason\": \"...\"}]}\n```\n\nPOSTS:\n" + json.dumps(want))
    out, err = run_worker(mid, "HERALD", prompt, exec_deny("announce"), mdir(mid), 300)
    d = parse_json_block(out) or {}
    posted = [str(x).lower() for x in (d.get("posted") or []) if str(x).lower() in PLATFORMS]
    for plat in posted:
        rem.discard(plat)
        emit(mid, "JARVIS", "done", f"✓ {plat} — posted")
    for f in (d.get("failed") or []):
        if isinstance(f, dict):
            emit(mid, "JARVIS", "error", f"✗ {str(f.get('platform') or '?')[:12]} — {str(f.get('reason') or 'failed')[:80]}")
    if err and not posted:
        emit(mid, "JARVIS", "error", f"posting failed — {err[:100]}")
    with LOCK:
        p = m.get("pending") or {}
        p["items"] = sorted(rem)
        p.setdefault("posted", []).extend(x for x in posted if x not in (p.get("posted") or []))
        if not rem:
            m["status"] = "done"
    if not rem:
        card(f"{m['icon']} {m['title']} — posted", "All approved platforms are live, sir.")

# ---------- kind 6: READ-THE-HATERS (vidIQ comments + reply drafts → gated skill posting) ----------
HATERS_PROMPT = (
    "You are the user's YouTube comment concierge. Using your connected vidIQ tools, find their "
    "channel's latest video(s) (vidiq_user_channels → vidiq_channel_videos → vidiq_video_comments) "
    "and pull the most notable recent comments — the spiciest hate, the warmest praise, the best "
    "questions; up to 8 total. For EACH, draft a reply in the creator's voice: witty but warm, "
    "never punching down, confident, a little playful with the haters, genuinely helpful with "
    "questions, 1-3 sentences. READ ONLY — post nothing. FINAL MESSAGE: ONLY a ```json fence, "
    "NOTHING after it:\n```json\n{\"items\": [{\"author\": \"...\", \"comment\": \"...\", "
    "\"likes\": 0, \"reply\": \"...\"}], \"read\": \"<2 spoken sentences in dry British butler "
    "voice: the flavor of the comments and the single best one, addressing the user as sir>\"}\n```")
def run_haters(mid):
    m = get(mid)
    hint = (" Focus: " + m["brief"]) if m["brief"] else ""
    out, err = run_worker(mid, "HATERS", HATERS_PROMPT + hint, DRAFT_DENY, mdir(mid), 240)
    if err:
        return fail(mid, err)
    d = parse_json_block(out)
    items = []
    for it in ((d or {}).get("items") or [])[:10]:
        if isinstance(it, dict) and str(it.get("comment") or "").strip():
            items.append({"author": str(it.get("author") or "someone")[:40],
                          "comment": str(it.get("comment") or "")[:400],
                          "likes": int(_num(it.get("likes"))),
                          "reply": str(it.get("reply") or "")[:400]})
    if not items:
        return fail(mid, "no comments came back, sir")
    read = str((d or {}).get("read") or f"{len(items)} comments read and replies drafted, sir.")[:400]
    await_confirm(mid, {"items": items, "read": read},
                  {"kind": "replies", "items": list(range(len(items))), "posted": []}, read)

def _yt_skill_post(payload):
    """S23 SECURITY: post approved replies through the youtube-replies skill's OWN scripts, called from
    Python with argv lists. The comment text is PUBLIC and attacker-authored — it used to ride in the
    same prompt as a Bash-enabled worker (prompt injection → code execution on one "post it")."""
    import subprocess as _sp, shutil as _sh, sys as _sys, re as _re
    skill = os.path.expanduser("~/.claude/skills/youtube-replies")
    if not (os.path.isfile(os.path.join(skill, "state", "token.json")) and
            os.path.isfile(os.path.join(skill, "config", "settings.json"))):
        return 0, len(payload), "the youtube-replies skill isn't authorized yet (no token) — run its SETUP first"
    py = _sh.which("python3") or _sys.executable
    def _jtail(txt, opener, closer):
        try:
            i = txt.index(opener); j = txt.rindex(closer)
            return json.loads(txt[i:j + 1])
        except Exception:
            return None
    try:
        r = _sp.run([py, os.path.join(skill, "scripts", "fetch.py"), "--limit", "200"], cwd=skill,
                    capture_output=True, text=True, timeout=90)
        comments = _jtail(r.stdout or "", "[", "]") or []
    except Exception as e:
        return 0, len(payload), f"couldn't fetch the comment list ({e.__class__.__name__})"
    norm = lambda s: _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", "", str(s or ""))).strip().lower()
    items, missing = [], 0
    for it in payload:
        wa, wt = norm(it.get("author")), norm(it.get("comment"))
        hit = None
        for c in comments:
            if not isinstance(c, dict): continue
            ct = norm(c.get("text"))
            if norm(c.get("author")) == wa and (ct == wt or (wt and wt[:60] in ct)):
                hit = c; break
        if hit and hit.get("comment_id"):
            items.append({"comment_id": str(hit["comment_id"]), "reply": str(it.get("reply") or "")[:2000]})
        else:
            missing += 1
    if not items:
        return 0, len(payload), "none of the approved comments matched a live, unreplied comment"
    try:
        r = _sp.run([py, os.path.join(skill, "scripts", "post.py")], cwd=skill, input=json.dumps(items),
                    capture_output=True, text=True, timeout=120)
        res = _jtail(r.stdout or "", "{", "}") or {}
        posted = len(res.get("posted") or []); failed = len(res.get("failed") or []) + missing
        note = f"{posted} posted, {len(res.get('skipped') or [])} already replied, {failed} failed"
        if r.returncode != 0 and not res:
            note = (r.stderr or r.stdout or "post.py failed").strip()[:160]; failed = len(payload)
        return posted, failed, note
    except Exception as e:
        return 0, len(payload), f"posting failed ({e.__class__.__name__})"

def haters_confirm(mid, item):
    m = get(mid)
    items = ((m.get("result") or {}).get("items")) or []
    il = str(item).lower()
    if il == "all":
        chosen = list(range(len(items)))
    else:
        try:
            chosen = [int(il)]
            items[chosen[0]]
        except (ValueError, IndexError):
            return emit(mid, "JARVIS", "error", f"no reply number '{item}', sir")
    payload = [{"author": items[i]["author"], "comment": items[i]["comment"], "reply": items[i]["reply"]}
               for i in chosen if 0 <= i < len(items)]
    emit(mid, "HATERS", "tool", f"attempting to post {len(payload)} repl{'y' if len(payload)==1 else 'ies'}…")
    posted, failed, note = _yt_skill_post(payload)          # S23: Python + argv lists, no LLM, no shell
    if posted > 0:
        emit(mid, "JARVIS", "done", f"✓ {posted} repl{'y' if posted==1 else 'ies'} posted — {note}")
        card(f"🔥 Replies posted ({posted})", note)
        with LOCK:
            p = m.get("pending") or {}
            p.setdefault("posted", []).extend(i for i in chosen if i not in (p.get("posted") or []))
            if il == "all" and posted >= len(payload):
                m["status"] = "done"
    else:
        emit(mid, "JARVIS", "error", f"✗ not posted — {note}")   # honest: drafts remain the result

# ---------- S29 (2026-10-13): REVERSE ENGINEER (the full REA catalog) + BUILD (the general builder) ----------
def _td():
    try:
        import teardown                               # same directory; its CTX is filled at boot
        return teardown
    except Exception:
        return None

REA_HOME = os.path.expanduser("~/.jarvis-tools/rea")
REA_SKILL = os.path.join(REA_HOME, "node_modules", "rea-agents", "skills", "reverse-engineer-anything")
NO_MCP = os.path.join(REA_HOME, "no-mcp.json")        # a builder needs hands, not connectors: boots faster, sees less
# REA tools that RUN or DRIVE the target (LLDB launches, native/Electron/browser/process scenarios) or change an
# Android device. Off for voice missions unless config.json says {"missions": {"rea_live": true}} — static
# analysis is the teardown; nothing launches on his desk mid-demo.
REA_LIVE_DENY = ["mcp__rea__observe_native_calls", "mcp__rea__observe_native_ui", "mcp__rea__capture_native_ui_scenario",
                 "mcp__rea__trace_native_ui_action", "mcp__rea__capture_process_scenario", "mcp__rea__capture_electron_scenario",
                 "mcp__rea__capture_browser_scenario", "mcp__rea__install_adb_package", "mcp__rea__uninstall_adb_package",
                 "mcp__rea__push_adb_file", "mcp__rea__start_adb_app", "mcp__rea__start_adb_activity", "mcp__rea__stop_adb_app"]

def _rea_mcp():
    td = _td()
    try:
        return td.mcp_config() if td else None
    except Exception:
        return None

def _no_mcp():
    try:
        if not os.path.exists(NO_MCP):
            os.makedirs(REA_HOME, exist_ok=True)
            with open(NO_MCP, "w", encoding="utf-8") as f:
                f.write('{"mcpServers": {}}\n')
    except OSError:
        pass
    return NO_MCP

REA_PROMPT = (
    "You are REA, the reverse-engineering analyst on the user's personal AI staff (Jarvis). Target: \"{target}\". "
    "Question: \"{question}\".\n"
    "You have REA's MCP tools (server `rea`). FIRST read {skill}/SKILL.md with the Read tool and follow its "
    "'Route the target first' section (read the one reference file it names for this kind of target). Then "
    "investigate with the REA tools. Print 'STAGE: ROUTE' once you have chosen the route, 'STAGE: INSPECT' while "
    "gathering evidence, and 'STAGE: WRITE' before the final message.\n"
    "Rules: analyze ONLY the named target — if it is an app or package name, resolve it to its local path with the Glob "
    "tool (Mac apps live in /Applications, /System/Applications and ~/Applications; Windows programs under "
    "C:\\Program Files, C:\\Program Files (x86) and %LOCALAPPDATA%\\Programs; files in the user's own folders such "
    "as ~/Downloads, ~/Desktop, ~/Documents); keep observations and inferences "
    "separate and cite REA evidence IDs; never attempt to bypass, patch or defeat licensing, signing or copy "
    "protection — note that it exists and move on; you did not run the target, so claim no runtime facts. "
    "Budget: about 12 tool calls; prefer summary views over huge dumps. Never ask questions back.\n"
    "Write the note for a smart non-engineer and keep it SHORT — it is read on screen: '## The answer' is at most three "
    "paragraphs of one or two sentences each (120 words in all); '## The stack' is at most 8 bullets, each "
    "'**Technology** — under 12 words'; '## How it works' and '## Rebuild it' are at most 7 one-sentence numbered steps "
    "each; '## What the evidence can't show' at most 5 short bullets; '## Evidence' at most 6 bullets. Plain words first, "
    "at most one backticked identifier per sentence, never single-asterisk emphasis.\n"
    "FINAL MESSAGE — exactly this shape, nothing before it:\n"
    "LABEL: Teardown · <short name>\nPATH: <the resolved local path of the target, or none>\n"
    "SPOKEN: <one spoken sentence Jarvis says when it's done, addressed to 'sir'>\n"
    "SUMMARY: <under 40 words, plain English>\n---NOTE---\n"
    "## The answer\n<2-4 plain-English paragraphs answering the question>\n"
    "## The stack\n<bullets: languages, frameworks, libraries, formats — each with how you know>\n"
    "## How it works\n<numbered: the architecture and the mechanics behind what was asked>\n"
    "## Rebuild it\n<numbered plan for an ORIGINAL implementation of the same ideas — techniques and structure "
    "only, never copied code, assets, text or branding>\n"
    "## What the evidence can't show\n<honest bullets>\n"
    "## Evidence\n<bullets: the tools called and the REA evidence IDs>")

def run_rea(mid):
    m = get(mid)
    target, _, question = (x.strip() for x in m["brief"].partition("|"))
    mcp = _rea_mcp()
    if not mcp:
        return fail(mid, "my REA kit isn't wired, sir")
    deny = list(DRAFT_DENY) + ["Skill"]
    if not ((CTX.get("cfg") or {}).get("missions") or {}).get("rea_live"):
        deny += REA_LIVE_DENY
    prompt = REA_PROMPT.format(target=target.replace('"', "'"), skill=REA_SKILL,
                               question=(question or "how is it built and how does it work").replace('"', "'"))
    td = _td()
    if td and hasattr(td, "classify"):                       # S29f safety net: a stale page or the brain sent a SITE here →
        k, v = td.classify(target, question)                 # the clean-browser path (Chrome opens, scrolls, snapshots), never the worker
        if k in ("web", "this"):
            job, terr = td.start(v if k == "web" else "this", question, None)
            if terr:
                return fail(mid, terr)
            emit(mid, "JARVIS", "read", "that's a website — opening it in a clean browser")
            return finish(mid, {"read": job["ack"], "summary": job["ack"], "web_job": job}, job["ack"])
    app = td.resolve_app(target) if td else None             # S29d: find the app ourselves → open it → its picture
    shot, shot_kind = None, None
    if app:
        emit(mid, "JARVIS", "read", "found " + os.path.basename(app))
        shot_path = os.path.join(mdir(mid), "shot.png")
        shot_kind = td.app_visual(app, shot_path)
        if shot_kind == "window":
            emit(mid, "JARVIS", "read", "opened %s and took a snapshot" % os.path.basename(app)[:-4])
        elif shot_kind == "icon":
            emit(mid, "JARVIS", "read", "no window to snap — using its icon")
        shot = shot_path if shot_kind else None
        prompt += "\nThe target is already located at %s — analyze that bundle; do not search for it." % app
    out, err = run_worker(mid, "REA", prompt, deny, mdir(mid), 600, mcp=mcp)
    if err or not out:
        return fail(mid, err or "REA came back empty, sir")
    td = _td()
    if not td or "---NOTE---" not in out:
        return fail(mid, "the teardown came back in the wrong shape, sir")
    label, spoken, summary, note = td._parse(out)
    if not shot:                                                 # the worker found the app itself → its picture, afterwards
        pm = re.search(r"^PATH:\s*(.+)$", out, re.M)
        p = (pm.group(1).strip().strip("`") if pm else "")
        if p.lower().endswith(".app") and os.path.isdir(p):
            shot_path = os.path.join(mdir(mid), "shot.png")
            shot_kind = td.app_visual(p, shot_path)
            shot = shot_path if shot_kind else None
    try:
        res = td.write_note(label, target, question, note, spoken, summary, shot_src=shot, shot_kind=shot_kind)
    except Exception as e:
        return fail(mid, "I couldn't save the teardown (%s)" % str(e)[:80])
    emit(mid, "JARVIS", "write", "saved " + res["rel"])
    res["read"] = res["spoken"]
    tb = (m.get("opts") or {}).get("then_build")                 # S29g: "reverse engineer X and build me one"
    if isinstance(tb, dict) and tb.get("brief"):
        nm, nerr = start("build", tb["brief"], {"from_teardown": True, "note": res["rel"], "open": True})
        if not nerr and nm:
            res["next_mission"] = {"id": nm["id"], "kind": nm["kind"], "title": nm["title"], "icon": nm["icon"], "brief": nm["brief"]}
            emit(mid, "JARVIS", "read", "now building your own version from it")
    finish(mid, res, res["spoken"])

BUILD_PROMPT = (
    "You are the BUILDER on the user's personal AI staff (Jarvis). Print 'STAGE: SCAFFOLD' first. Build this, "
    "complete and working, in the CURRENT directory: \"{brief}\".\n"
    "Form: a static web app — index.html is the entry; add css/js/asset files freely (no build step, no npm, no "
    "server code). Libraries only inline or from pinned CDN URLs with exact versions (cdnjs.cloudflare.com, "
    "cdn.jsdelivr.net/npm/<pkg>@<version>, unpkg.com/<pkg>@<version>) — never a bare or 'latest' version. These exact "
    "URLs are verified to exist: https://cdn.jsdelivr.net/npm/three@0.165.0/build/three.module.js (addons under "
    "https://cdn.jsdelivr.net/npm/three@0.165.0/examples/jsm/), https://cdn.jsdelivr.net/npm/postprocessing@6.35.5/build/index.js "
    "(ESM; it imports the bare specifier 'three', so declare an import map {\"three\": …three.module.js, "
    "\"postprocessing\": …/build/index.js}), https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js (+ CustomEase.min.js, "
    "ScrollTrigger.min.js beside it). Any other library: use the package's documented build path, and if an import could "
    "fail, catch it and degrade gracefully rather than leaving a blank page. "
    "Fonts: system fonts or Google Fonts. Images and 3D: generate procedurally (canvas, SVG, Three.js geometry, "
    "shaders) — no external image hotlinks, no placeholders.\n"
    "Quality: genuinely functional, not a mockup; keyboard-friendly; works at 1440×900 and on a phone; persists "
    "user data in localStorage where that makes sense; give it its own name and a <title>.\n"
    "{blueprint}"
    "Originality: this is your own original work. Never copy code, text, images, audio, fonts, icons, logos or brand "
    "names from any analyzed software or site — reuse techniques and structure only.\n"
    "Print 'STAGE: CODE' before writing files, 'STAGE: TEST' while you re-read every file for missing references, "
    "wrong paths and syntax slips, and 'STAGE: LAUNCH' when it is final. FINAL MESSAGE: one line — its name and "
    "what it does. Never ask questions back.")
BLUEPRINT = ("Blueprint — the user's own teardown of {source} (vault note '{label}'). Build an ORIGINAL work that "
             "uses the same techniques with a different theme, content and visuals:\n{text}\n\n")
FIX_PROMPT = ("You built a web app in the CURRENT directory (entry index.html). Loading it in a browser produced "
              "these errors:\n{errors}\nFix them by editing the files here — keep everything else as it is, pinned "
              "CDN versions only, no new external services. Print 'STAGE: TEST' while re-checking and "
              "'STAGE: LAUNCH' when done. FINAL MESSAGE: one line on what you fixed.")

def run_build(mid):
    m = get(mid)
    opts = m.get("opts") or {}
    app = os.path.join(mdir(mid), "app")
    try:
        os.makedirs(app, exist_ok=True)
    except OSError:
        pass
    deny = [d for d in DRAFT_DENY if d not in ("Write", "Edit")] + ["Skill"]   # hands, no skills, no sends
    td = _td()
    blueprint = ""
    if opts.get("from_teardown") and td:
        try:
            bp = td.rebuild_brief(opts.get("note") or None)
        except Exception:
            bp = None
        if bp and bp.get("text"):
            blueprint = BLUEPRINT.format(source=bp["source"][:120], label=bp["label"], text=bp["text"])
            m["source"] = bp["label"] + " " + bp["source"]
            emit(mid, "JARVIS", "read", "blueprint: " + bp["label"][:70])
        else:
            emit(mid, "JARVIS", "error", "no teardown on file — building from the brief alone")
    prompt = BUILD_PROMPT.format(brief=m["brief"].replace('"', "'"), blueprint=blueprint)
    seen = {"code": False}
    def hook(kind, _label):
        if kind == "write" and not seen["code"]:
            seen["code"] = True
            emit(mid, "BUILDER", "stage", "CODE")
    out, err = run_worker(mid, "BUILDER", prompt, deny, app, 1500, hook, mcp=_no_mcp())   # 25 min: the first real build used 15 writing + was cut mid re-read
    if not os.path.isfile(os.path.join(app, "index.html")):
        return fail(mid, err or "no index.html was produced, sir")
    url = f"/mission_app/{mid}/index.html"
    full = f"http://127.0.0.1:{CTX.get('port') or 4719}{url}"
    # Jarvis tests it himself: a hidden browser nets every error; one repair pass if anything broke
    test = {"errors": [], "fixed": 0, "shot": False, "ok": None}
    if td and hasattr(td, "smoke_test"):
        emit(mid, "JARVIS", "stage", "TEST")
        emit(mid, "JARVIS", "read", "loading it in a hidden browser…")
        shot = os.path.join(mdir(mid), "smoke.png")
        r = td.smoke_test(full, shot)
        if not r["ok"] and r["errors"] and not r["errors"][0].startswith(("test browser", "the page never")):
            emit(mid, "JARVIS", "error", "%d error(s) — sending it back to the builder" % len(r["errors"]))
            for e in r["errors"][:4]:
                emit(mid, "JARVIS", "error", e[:120])
            run_worker(mid, "BUILDER", FIX_PROMPT.format(errors="\n".join("- " + e for e in r["errors"][:12])),
                       deny, app, 420, None, mcp=_no_mcp())
            before = len(r["errors"])
            r = td.smoke_test(full, shot)
            test["fixed"] = max(0, before - len(r["errors"]))
        test.update({"errors": r["errors"], "shot": r["shot"], "ok": r["ok"], "took_s": r.get("took_s")})
        emit(mid, "JARVIS", "done" if r["ok"] else "error",
             "tested clean — 0 errors" if r["ok"] else "%d error(s) remain" % len(r["errors"]))
    emit(mid, "BUILDER", "stage", "LAUNCH")
    what = (out or m["brief"]).strip().splitlines()[-1][:160] if (out or "").strip() else m["brief"][:160]
    try:                                               # the build survives restarts: a card on disk next to the app
        with open(os.path.join(mdir(mid), "build.json"), "w", encoding="utf-8") as f:
            json.dump({"id": mid, "brief": m["brief"], "note": what, "url": url, "ok": test["ok"],
                       "errors": test["errors"], "ts": int(time.time()), "source": m.get("source") or ""}, f)
    except OSError:
        pass
    if opts.get("open"):
        emit(mid, "JARVIS", "tool", "opened it as its own window" if open_app(full) else "couldn't open it, sir")
    verdict = ("you loaded it in a hidden browser yourself and it passed with no errors" if test["ok"]
               else ("you tested it and %d error(s) still show" % len(test["errors"])) if test["ok"] is not None
               else "you could not test it")
    summary = quip(f"You just built the user something they asked for: {what}. Then {verdict}. ONE short dry "
                   "sentence announcing it's ready (say that you tested it)" + (" and that you're opening it." if opts.get("open") else "."),
                   "It's built and tested, sir" + (" — opening it now." if opts.get("open") else "."))
    finish(mid, {"url": url, "full": full, "note": what, "summary": summary, "test": test,
                 "shot": ("/mission_shot?id=" + mid) if test["shot"] else None}, summary)

def open_app(full_url):
    """Open a built app as ITS OWN WINDOW (Chrome app mode: no tabs, no address bar, Cmd-Tab-able)
    — he wants to see it like a normal app, not a browser tab. Falls back to the default browser."""
    chrome = None
    try:
        td = _td()
        chrome = td._find_chrome() if td else None
    except Exception:
        chrome = None
    try:
        if chrome and os.path.exists(chrome):
            subprocess.Popen([chrome, "--app=" + full_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=(os.name != "nt"))
        elif os.name == "nt":
            os.startfile(full_url)                               # Windows without Chrome: the default browser
        else:
            subprocess.Popen(["open", full_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

# words that say nothing about WHICH build he means ("open the notes app you just built" → "notes")
_OPEN_STOP = set("the a an my that this app application build site website page thing you jarvis he just recently "
                 "built made created coded last latest new newest finished open launch show me bring up pull run go "
                 "ahead and please now it one".split())
def pick_build(hint=None, mid=None):
    """The build he means: by id, else the best word match of his phrase against each build's name,
    brief and teardown source ('notes app' → Slate even after an igloo rebuild), else the newest."""
    bl = builds()
    if mid:
        return next((x for x in bl if x["id"] == mid), None)
    if not bl:
        return None
    words = [w for w in re.findall(r"[a-z0-9]+", (hint or "").lower()) if w not in _OPEN_STOP]
    if words:
        def score(b):
            hay = " ".join(str(b.get(k) or "") for k in ("note", "brief", "source")).lower()
            return sum(1 for w in words if w in hay)
        best = max(bl, key=score)
        if score(best) > 0:
            return best
    return bl[0]

def open_latest(mid=None, hint=None):
    """Open the build he means (see pick_build) as its own window; returns its card or None."""
    b = pick_build(hint, mid)
    if not b:
        return None
    open_app(f"http://127.0.0.1:{CTX.get('port') or 4719}{b['url']}")
    return b

def builds():
    """Finished builds on disk, newest first (build.json beside each app/) — the ones that survive restarts."""
    out = []
    try:
        for mid in os.listdir(MISSIONS_DIR):
            bj = os.path.join(MISSIONS_DIR, mid, "build.json")
            if os.path.isfile(bj) and os.path.isfile(os.path.join(MISSIONS_DIR, mid, "app", "index.html")):
                try:
                    d = json.load(open(bj, encoding="utf-8"))
                    d["id"] = mid
                    out.append(d)
                except Exception:
                    pass
    except OSError:
        pass
    return sorted(out, key=lambda d: d.get("ts", 0), reverse=True)

RUNNERS = {"fleet": run_fleet, "buildapp": run_buildapp, "reaper": run_reaper,
           "warroom": run_warroom, "announce": run_announce, "haters": run_haters,
           "rea": run_rea, "build": run_build}
EXEC_ACK = {"reaper": "Drafting the cancellation now, sir — watch the feed.",
            "announce": "Posting now, sir — receipts as they land.",
            "haters": "Attempting the replies, sir — I'll report honestly."}

# ---------- mission lifecycle ----------
def start(kind, brief, opts=None):
    kind = (kind or "").strip().lower()
    if kind not in KINDS:
        return None, "I don't know that mission kind, sir — " + ", ".join(sorted(KINDS)) + "."
    b = (brief or "").strip()[:400]
    if kind in NEEDS_BRIEF and not b:
        return None, "that mission needs a brief, sir."
    icon, name = KINDS[kind]
    mid = uuid.uuid4().hex[:10]
    title = name + ((" — " + (b[:48] + ("…" if len(b) > 48 else ""))) if b else "")
    m = {"id": mid, "kind": kind, "title": title, "icon": icon, "brief": b, "status": "running",
         "events": [], "result": None, "pending": None, "created": int(time.time()), "procs": [],
         "opts": dict(opts or {})}
    with LOCK:
        MISSIONS[mid] = m
    log_line({"id": mid, "ev": "start", "kind": kind, "brief": b, "ts": m["created"]})
    threading.Thread(target=_run_guarded, args=(kind, mid), daemon=True).start()
    return m, None

def _run_guarded(kind, mid):
    try:
        RUNNERS[kind](mid)
    except Exception as e:
        fail(mid, f"mission crashed ({e.__class__.__name__}: {str(e)[:80]})")

def confirm(mid, item):
    m = get(mid)
    if not m:
        return None, "I can't find that mission, sir."
    if m["status"] != "awaiting_confirm":
        return None, "Nothing awaiting my confirmation on that one, sir."
    fn = {"reaper": reaper_confirm, "announce": announce_confirm, "haters": haters_confirm}.get(m["kind"])
    if not fn:
        return None, "That mission has no gated step, sir."
    it = str(item if item not in (None, "") else "all").strip()
    threading.Thread(target=lambda: _confirm_guarded(fn, m["id"], it), daemon=True).start()
    return {"ok": True, "answer": EXEC_ACK.get(m["kind"], "Executing, sir.")}, None

def _confirm_guarded(fn, mid, item):
    try:
        fn(mid, item)
    except Exception as e:
        emit(mid, "JARVIS", "error", f"execute step crashed ({e.__class__.__name__})")

def cancel(mid):
    m = get(mid)
    if not m:
        return None, "I can't find that mission, sir."
    with LOCK:
        m["cancelled"] = True
        if m["status"] in ("running", "awaiting_confirm"):
            m["status"] = "error"
        procs = list(m.get("procs") or [])
    for pr in procs:
        try:
            if pr.poll() is None:
                pr.terminate()
        except Exception:
            pass
    emit(mid, "JARVIS", "error", "mission cancelled")
    return {"ok": True, "answer": "Stood down, sir."}, None

# ---------- HTTP surface (dispatched from server.py's H handler) ----------
CTYPE = {"html": "text/html", "js": "application/javascript", "mjs": "application/javascript", "css": "text/css",
         "json": "application/json", "map": "application/json", "png": "image/png", "jpg": "image/jpeg",
         "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml", "ico": "image/x-icon",
         "txt": "text/plain", "csv": "text/csv", "xml": "application/xml", "woff": "font/woff", "woff2": "font/woff2",
         "ttf": "font/ttf", "otf": "font/otf", "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
         "mp4": "video/mp4", "webm": "video/webm", "glb": "model/gltf-binary", "gltf": "model/gltf+json",
         "wasm": "application/wasm", "pdf": "application/pdf"}          # S29: multi-file builds
def serve_app(handler, path):
    """GET /mission_app/<id>/<file> — serve ONLY from that mission's app/ dir (traversal-guarded)."""
    rest = path[len("/mission_app/"):]
    mid, _, sub = rest.partition("/")
    base = os.path.normpath(os.path.join(MISSIONS_DIR, mid, "app"))
    root = os.path.normpath(MISSIONS_DIR)
    fp = os.path.normpath(os.path.join(base, urllib.parse.unquote(sub or "index.html")))
    known = get(mid) is not None or os.path.isfile(os.path.join(MISSIONS_DIR, mid, "build.json"))   # S29: on disk = still his
    ok = (known and re.fullmatch(r"[a-f0-9]{6,12}", mid or "") is not None and base.startswith(root + os.sep)
          and (fp == base or fp.startswith(base + os.sep)) and os.path.isfile(fp))
    if not ok:
        handler.send_response(404)
        handler.end_headers()
        return True
    data = open(fp, "rb").read()
    handler.send_response(200)
    handler.send_header("Content-Type", CTYPE.get(fp.rsplit(".", 1)[-1].lower(), "application/octet-stream"))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)
    return True

def handle(handler, method, raw_path, payload):
    """True = handled (response already written via handler). server.py routes every /mission* here."""
    path = raw_path.split("?")[0]
    payload = payload or {}
    if method == "GET" and path.startswith("/mission_app/"):
        return serve_app(handler, path)
    if method == "GET" and path == "/mission_kinds":            # S29: preflight + the viewer ask what's wired
        handler._json({"kinds": sorted(KINDS), "rea_mcp": bool(_rea_mcp()),
                       "claude": bool(CLAUDE_BIN and os.path.isfile(CLAUDE_BIN))})
        return True
    if method == "GET" and path == "/mission_builds":           # S29: finished builds on disk, newest first
        handler._json({"builds": builds()[:20]})
        return True
    if method == "POST" and path == "/mission_open":            # S29: "open the app you built" → its own window
        b = open_latest(re.sub(r"[^a-f0-9]", "", str(payload.get("id") or "")) or None, str(payload.get("hint") or "")[:200])
        if not b:
            handler._json({"error": "I haven't built anything yet, sir."}, 404)
            return True
        handler._json({"ok": True, "id": b["id"], "note": b.get("note"), "url": b["url"]})
        return True
    if method == "GET" and path == "/mission_shot":             # S29: the build's hidden-browser snapshot
        q = urllib.parse.parse_qs(urllib.parse.urlparse(raw_path).query)
        mid = re.sub(r"[^a-f0-9]", "", (q.get("id") or [""])[0])
        fp = os.path.join(MISSIONS_DIR, mid, "smoke.png") if mid else ""
        if not (mid and get(mid) and os.path.isfile(fp)):
            handler.send_response(404); handler.end_headers(); return True
        data = open(fp, "rb").read()
        handler.send_response(200)
        handler.send_header("Content-Type", "image/png")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
        return True
    if method == "GET" and path == "/mission_events":
        q = urllib.parse.parse_qs(urllib.parse.urlparse(raw_path).query)
        mid = (q.get("id") or [""])[0]
        try:
            since = max(0, int((q.get("since") or ["0"])[0] or 0))
        except ValueError:
            since = 0
        m = get(mid)
        if not m:
            handler._json({"error": "unknown mission"}, 404)
            return True
        with LOCK:
            evs = list(m["events"][since:])
            out = {"events": evs, "next": since + len(evs), "status": m["status"],
                   "result": m["result"], "pending": m["pending"], "kind": m["kind"], "title": m["title"], "brief": m["brief"]}
        handler._json(out)
        return True
    if method == "POST" and path == "/mission_start":
        m, err = start(payload.get("kind"), payload.get("brief"),
                       {"open": bool(payload.get("open")), "from_teardown": bool(payload.get("from_teardown")),
                        "note": str(payload.get("note") or "")[:200],
                        "then_build": payload.get("then_build") if isinstance(payload.get("then_build"), dict) else None})
        if err:
            handler._json({"error": err}, 400)
        else:
            handler._json({"id": m["id"], "title": m["title"], "kind": m["kind"], "icon": m["icon"], "brief": m["brief"]})
        return True
    if method == "POST" and path == "/mission_confirm":
        res, err = confirm((payload.get("id") or "").strip(), payload.get("item"))
        handler._json({"error": err}, 400) if err else handler._json(res)
        return True
    if method == "POST" and path == "/mission_cancel":
        res, err = cancel((payload.get("id") or "").strip())
        handler._json({"error": err}, 404) if err else handler._json(res)
        return True
    return False
