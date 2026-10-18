#!/usr/bin/env python3
"""S25c · the FIELD PASS without a microphone.
Posts the sentences of a field pass to the live reflex bay (localhost:4719), as finals AND as the partial
prefixes the recogniser would stream, in live + filming mode, and names every gate misfire in plain words.
Costs a few tenths of a cent. Run while the server is up:

    python3 test_reflex_drill.py                       # picks the first named note in your galaxy
    python3 test_reflex_drill.py --note "Pricing"      # ask about a note you know exists
    python3 test_reflex_drill.py --note "Pricing" --misheard "prizing"   # how speech mangles it
"""
import argparse, json, os, re, sys, urllib.request
import reflex as RX
BASE = "http://localhost:4719"; ROOT = os.path.dirname(os.path.abspath(__file__))

def first_named_note():
    """The first hub/project/concept label in the galaxy, so the vault question is about a real note."""
    for cand in (os.path.join(ROOT, "viewer", "graph-data.js"), os.path.join(ROOT, "graph-data.js")):
        if not os.path.exists(cand): continue
        m = re.search(r"const GRAPH\s*=\s*(\{.*\});", open(cand, encoding="utf-8").read(), re.S)
        if not m: continue
        nodes = json.loads(m.group(1)).get("nodes", [])
        for g in ("hub", "project", "concept", "world", "core"):
            for n in nodes:
                if n.get("g") == g and n.get("p") and 3 <= len(n.get("label", "")) <= 40: return n["label"]
        for n in nodes:
            if n.get("p") and n.get("label"): return n["label"]
    return "my notes"

ap = argparse.ArgumentParser(); ap.add_argument("--note", default=None); ap.add_argument("--misheard", default=None); args = ap.parse_args()
NOTE = args.note or first_named_note()

def post(path, body, timeout=12):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return json.load(r)
    except Exception as e: return {"error": str(e)[:100]}
def n(a, k): return float(((a.get(k) or {}).get("noul")) or 0)
def line(tag, text, r):
    a = r.get("answers") or {}; d = r.get("decision") or {}; lane = a.get("lane") or {}
    print(f'  {tag:9s} {r.get("ms","?"):>4}ms "{text[:62]:62s}" lane={str(lane.get("choice")):15s} {float(lane.get("confidence") or 0):.2f} complete={n(a,"complete"):.2f} addressed={n(a,"addressed"):.2f} stakes={n(a,"destructive"):.2f}'
          + ("  FIRE" if d.get("fire_early") else "") + ("  peek" if d.get("peek_vault") else "") + ("  trust" if d.get("trust_lane") else "") + ("  ADDR" if d.get("addressed_ok") else "  quiet") + ("  unsure" if d.get("clarify") else ""))
    return a, d
issues = []; notes = []
def prefixes(text):
    w = text.split(); return [" ".join(w[:i]) for i in range(3, len(w))]
def drill(text, recording=False, expect_lane=None, expect_addressed=None, stream=True):
    print(f'\n▶ "{text}"' + ("   [filming mode]" if recording else ""))
    fired_on = None
    if stream:
        for pre in prefixes(text):
            r = post("/reflex/prepass", {"text": pre, "ctx": {"partial": True, "recording_mode": recording}})
            if "answers" not in r: print("   partial error", r); continue
            a, d = line("partial", pre, r)
            if d.get("fire_early") and not fired_on: fired_on = pre
    r = post("/reflex/prepass", {"text": text, "ctx": {"partial": False, "recording_mode": recording}})
    if "answers" not in r: print("   final error", r); return r
    a, d = line("final", text, r)
    if fired_on and fired_on != text:
        notes.append(f'bay says MAY-FIRE on the prefix "{fired_on}" of "{text}" (complete ≥ {RX.COMPLETE_FIRE}); the client pause guard (EARLY_STABLE_MS in reflex.js, probed by ?reflexprobe=1) must hold it')
    if expect_lane and d.get("lane") != expect_lane:
        issues.append(f'LANE: "{text}" → {d.get("lane")} {d.get("confidence")} (expected {expect_lane})')
    if expect_addressed is True and not d.get("addressed_ok"):
        issues.append(f'FILMING MISS: "{text}" addressed={n(a,"addressed"):.2f} < {d["gates"]["addressed"]}: Jarvis would stay quiet when spoken to')
    if expect_addressed is False and d.get("addressed_ok"):
        issues.append(f'FILMING MISFIRE: "{text}" addressed={n(a,"addressed"):.2f} ≥ {d["gates"]["addressed"]}: Jarvis would answer narration')
    return r
def recall(q):
    r = post("/reflex/recall", {"question": q})
    if "has" not in r: print("   recall error", r); return r
    print(f'  recall   {r["ms"]:>4}ms  has={r["has"]:.2f} ext={r["ext"]:.2f} verdict={r["verdict"]} keep={r["keep"][:6]} likely={r.get("likely", [])[:3]} corrected="{r.get("corrected","")[:60]}"')
    return r

print("REFLEX DRILL · note:", repr(NOTE), "· gates:", json.dumps({k: getattr(RX, k) for k in ("LANE_ACT", "LANE_PEEK", "LANE_CLARIFY", "COMPLETE_FIRE", "ADDRESSED_ROOM", "ADDRESSED_FILMING", "DESTRUCTIVE_CONFIRM", "FOUND", "ABSENT")}))
# 1 · a question about a real note (wake word stripped, as the client does)
q = f"what do my notes say about {NOTE}"
drill(q, expect_lane="vault_question"); recall(q)
if args.misheard:
    q2 = f"what do my notes say about {args.misheard}"; drill(q2, expect_lane="vault_question", stream=False); recall(q2)
# 2 · a question the vault does not hold
drill("what's the weather tomorrow"); recall("what's the weather tomorrow")
# 3 · filming mode: narration to camera must stay quiet, an address must answer (no wake word in either)
for s in ["so what I'm building here is a reflex layer for my assistant and it decides in about two hundred milliseconds",
          "every bar you see on the strip is a probability the model returned this turn, nothing on here is decorative",
          f"let me show you what happens when I ask him about {NOTE}"]:
    drill(s, recording=True, expect_addressed=False, stream=False)
for s in [f"what do my notes say about {NOTE}", "how much did your reflexes cost today", "what's the weather tomorrow"]:
    drill(s, recording=True, expect_addressed=True, stream=False)
# 4 · the reflex voice phrases (client routes; the lane is display-only here)
for s in ["show the last reflex", "what did your reflexes cost today"]:
    drill(s, expect_lane="reflex", stream=False)
# 5 · a destructive ask must arm a confirm, never fire early
drill("send Dana the follow-up email about the deposit right now")
print("\n== RESULT ==")
for i in notes: print("  ·", i)
if issues:
    for i in issues: print("  ⚠", i)
else: print("  ✓ no gate misfires in the text drill")
