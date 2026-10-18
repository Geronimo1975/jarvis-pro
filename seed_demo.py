#!/usr/bin/env python3
"""Reversible DEMO SEED for the JARVIS second-brain — for recording the YouTube video.

  python3 seed_demo.py          # inject demo nodes + populate Agent Inbox + a week of episodes
  python3 seed_demo.py --clear  # restore the graph and wipe the demo inbox/episodes

It NEVER touches your real notes: it appends a handful of clean demo nodes to a BACKED-UP copy
of graph-data.js and writes only the local state files (inbox/episodes/dnd). --clear puts it all
back. After seeding, RESTART the server (python3 server.py) and hard-reload the page.
"""
import os, re, json, time, uuid, shutil, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
GD = os.path.join(ROOT, "viewer", "graph-data.js")
BAK = GD + ".predemo.bak"
INBOX = os.path.join(ROOT, "jarvis-inbox.json")
EPISODES = os.path.join(ROOT, "jarvis-episodes.jsonl")
DND = os.path.join(ROOT, "jarvis-dnd.json")

# anchor indices in the real graph (verified): AI Workshop=9, CiteVue=11, Claude Code=12, GEO Suite=32
A_WORKSHOP, A_CITEVUE, A_CLAUDE, A_GEO = 9, 11, 12, 32

def clear():
    if os.path.exists(BAK):
        shutil.copy(BAK, GD); os.remove(BAK); print("restored graph-data.js (removed demo nodes)")
    else:
        print("no graph backup found — graph left as-is")
    for f in (INBOX, EPISODES, DND):
        if os.path.exists(f):
            os.remove(f); print("removed", os.path.basename(f))
    print("\nDemo cleared. Restart the server and hard-reload.")

def seed():
    # 1) clean base: restore from backup if present, else create one
    if os.path.exists(BAK):
        shutil.copy(BAK, GD)
    else:
        shutil.copy(GD, BAK)
    src = open(GD, encoding="utf-8").read()
    m = re.search(r"const GRAPH\s*=\s*(\{.*\});", src, re.S)
    g = json.loads(m.group(1))
    base = len(g["nodes"])           # demo nodes get indices base+0 ..

    # 2) the demo cluster — one coherent story
    DEMO = [
        ("JARVIS — Second Brain", "concept",
         "My voice-driven AI second brain: it answers from my notes, speaks in an ElevenLabs butler voice, "
         "and has hands through Claude Code. Runs on the 3D knowledge graph with an agent inbox, a time machine, "
         "screen vision and real phone calls.", [A_CLAUDE, A_WORKSHOP]),
        ("I Built JARVIS — YouTube Video", "note",
         "The 'I Built JARVIS' video: how I built a Jarvis-style assistant with Claude Code, Opus 4.8 and "
         "ElevenLabs. Demos the second brain, the agent inbox, the time machine, screen vision and live phone calls.",
         [A_WORKSHOP]),
        ("CiteVue — First Sale", "note",
         "First $19.99 full GEO audit sold through Stripe on CiteVue — the first real revenue. Proof the free-score "
         "to paid-audit funnel works.", [A_CITEVUE]),
        ("Moving Company Client — Reputation Win", "note",
         "Closed a moving company on the AI Reputation Builder — my #1 target niche. First reputation-services deal, "
         "recurring monthly. Stress, damage and pricing complaints make movers the perfect fit.", [A_WORKSHOP]),
        ("GEO for Restaurants — Video Idea", "concept",
         "Video idea: run GEO audits for local restaurants so they get cited by AI search. Pairs with the restaurant "
         "skill suite and the CiteVue tool.", [A_GEO, A_CITEVUE]),
        ("Sarah — Video Editor", "note",
         "Sarah edits the YouTube channel. Currently waiting on the thumbnail brief for the JARVIS video. Fast "
         "turnaround, prefers a short Loom brief.", [A_WORKSHOP]),
        ("Retell Phone Line", "tool",
         "JARVIS places real outbound phone calls through Retell — booking tables, chasing quotes — every call gated "
         "behind a spoken 'do it'.", [A_WORKSHOP]),
    ]
    idx = {}
    for i, (label, grp, p, _) in enumerate(DEMO):
        idx[label] = base + i
        g["nodes"].append({"id": "demo/%s.md" % re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-"),
                            "label": label, "g": grp, "p": p})
    for i, (label, grp, p, anchors) in enumerate(DEMO):
        me = base + i
        for a in anchors:
            g["links"].append({"s": me, "t": a})
    # cross-link the cluster so it lights up as a group
    J, V, R = idx["JARVIS — Second Brain"], idx["I Built JARVIS — YouTube Video"], idx["Retell Phone Line"]
    for s, t in [(V, J), (R, J), (idx["Sarah — Video Editor"], V), (idx["CiteVue — First Sale"], J)]:
        g["links"].append({"s": s, "t": t})

    new_src = src[:m.start(1)] + json.dumps(g, ensure_ascii=False) + src[m.end(1):]
    open(GD, "w", encoding="utf-8").write(new_src)
    print("injected %d demo nodes (idx %d-%d) + links" % (len(DEMO), base, base + len(DEMO) - 1))

    # 3) Agent Inbox — a realistic, on-brand deck for "what needs me?"
    now = int(time.time())
    cards = [
        ("notify", "high", "anomaly", "First sale, sir — CiteVue",
         "A $19.99 Stripe payment just landed. Your very first one.", None),
        ("approve", "normal", "loop", "Reply drafted for Sarah",
         "She's waiting on the thumbnail brief — I've prepared a reply for your nod.",
         "Draft a short, warm 2-3 sentence reply to Sarah, my video editor, confirming the JARVIS thumbnail "
         "brief is ready and I'll send it today. Output ONLY the draft, sir."),
        ("notify", "normal", "breakout", "A competitor just broke out",
         "A channel in your niche posted a video pacing 3x its average — want three angles?", None),
        ("ask", "normal", "preflight", "Block editing time?",
         "You've a two-hour gap before tomorrow's shoot — shall I hold it for editing?", None),
        ("notify", "normal", "skool", "3 new free-community trials",
         "Three signups joined overnight. The funnel's warm.", None),
    ]
    inbox = []
    for i, (t, pr, src_, title, body, action) in enumerate(cards):
        inbox.append({"id": uuid.uuid4().hex[:12], "ts": now - (len(cards) - i) * 40, "type": t,
                      "title": title, "body": body, "source": src_, "priority": pr,
                      "action": action, "status": "new", "speak": False})
    json.dump(inbox, open(INBOX, "w"))
    print("seeded %d inbox cards" % len(inbox))

    # 4) Episodes — a coherent week so the Time Machine has a story to tell
    day = 86400
    eps = [
        (6, "ship",  "Shipped the CiteVue Stripe integration and took the paid audit live.", [A_CITEVUE, idx["CiteVue — First Sale"]]),
        (5, "win",   "Closed the moving-company reputation client — my first reputation deal.", [idx["Moving Company Client — Reputation Win"], A_WORKSHOP]),
        (4, "film",  "Filmed the GEO report-tool walkthrough for YouTube.", [A_GEO, idx["GEO for Restaurants — Video Idea"]]),
        (3, "draft", "Drafted the moving-company outreach and scheduled the GEO audit.", [idx["Moving Company Client — Reputation Win"]]),
        (2, "build", "Outlined the 'I Built JARVIS' video and built the Agent Inbox.", [idx["I Built JARVIS — YouTube Video"], idx["JARVIS — Second Brain"]]),
        (1, "wire",  "Wired up real phone calls with Retell and tested the Jarvis voice.", [idx["Retell Phone Line"], idx["JARVIS — Second Brain"]]),
    ]
    with open(EPISODES, "w", encoding="utf-8") as f:
        for d, kind, text, nodes in eps:
            f.write(json.dumps({"ts": now - d * day - 3600, "kind": kind, "text": text, "nodes": nodes}) + "\n")
    print("seeded %d episodes (last 6 days)" % len(eps))

    if os.path.exists(DND):
        os.remove(DND)   # focus mode off for the demo
    print("\nDemo seeded. Now: restart the server (python3 server.py) and hard-reload localhost:4719.")
    print("Wipe it after with:  python3 seed_demo.py --clear")

if __name__ == "__main__":
    (clear if "--clear" in sys.argv else seed)()
