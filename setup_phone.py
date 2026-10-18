#!/usr/bin/env python3
"""JARVIS PHONE SETUP — create the three Retell calling agents with ONE command.

    python3 setup_phone.py          # creates booking + inquiry + general, writes ids to config.json
    python3 setup_phone.py --dry    # show the plan without creating anything

Prereqs: config.json → telephony.api_key (from retellai.com) — that's it.
The prompts come from retell-agent-prompts.md (the source of truth). The begin
message stays EMPTY for outbound agents (they wait for the callee's hello — the law).
The HOTLINE agent is created automatically the first time the server boots.
Voice: telephony.voice_id if set, else a stock voice — swap to your cloned voice
any time in the Retell dashboard or by setting telephony.voice_id and re-running.
Idempotent: agents already in config.json that still exist on Retell are kept.
"""
import json, os, re, sys, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

API = "https://api.retellai.com"
DRY = "--dry" in sys.argv


def http(path, body=None, method=None, key=""):
    req = urllib.request.Request(API + path,
                                 data=(json.dumps(body).encode() if body is not None else None),
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"},
                                 method=method or ("POST" if body is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode(errors="ignore")[:300]}
    except Exception as e:
        return 0, {"error": str(e)[:200]}


def load_prompts():
    """Split retell-agent-prompts.md on its ALL-CAPS '## SECTION' headings."""
    text = open("retell-agent-prompts.md", encoding="utf-8").read()
    sections, current, buf = {}, None, []
    for line in text.splitlines():
        m = re.match(r"^## ([A-Z][A-Z ]+)\s*$", line)
        if m:
            if current:
                sections[current] = "\n".join(buf).strip()
            current, buf = m.group(1).strip().lower(), []
        elif current:
            buf.append(line)
    if current:
        sections[current] = "\n".join(buf).strip()
    return sections


GENERAL_PROMPT = ("## Identity\nYou are Jarvis, a capable AI assistant making calls on your "
                  "principal's behalf. This agent is re-briefed with a COMPLETE call script "
                  "before every call — follow the briefed script exactly.")

TOOLS = [{"type": "end_call", "name": "end_call",
          "description": "Hang up the call. Use only after a goodbye, or per the edge cases."},
         {"type": "press_digit", "name": "press_digit",
          "description": "Press a keypad digit to navigate an automated phone menu (IVR). "
                         "Use ONLY when an automated system asks you to press a number."}]


def main():
    try:
        cfg = json.load(open("config.json"))
    except FileNotFoundError:
        sys.exit("✗ No config.json here yet — run the Jarvis setup first (it copies "
                 "config.example.json to config.json), then add your Retell API key to "
                 "telephony.api_key and re-run.")
    except json.JSONDecodeError as e:
        sys.exit(f"✗ config.json isn't valid JSON ({e}) — fix that line "
                 "(or re-copy config.example.json and redo your keys), then re-run.")
    tel = cfg.setdefault("telephony", {})
    key = (tel.get("api_key") or "").strip()
    if not key or key.startswith("PUT-"):
        sys.exit("✗ Add your Retell API key to config.json → telephony.api_key first "
                 "(create one at retellai.com), then re-run.")
    voice = (tel.get("voice_id") or "").strip() or "11labs-Anthony"
    prompts = load_prompts()
    plans = []
    for kind in ("booking", "inquiry", "general"):
        prompt = prompts.get(kind) or (GENERAL_PROMPT if kind == "general" else None)
        if not prompt:
            sys.exit(f"✗ Couldn't find the {kind.upper()} section in retell-agent-prompts.md")
        plans.append((kind, prompt))

    agents = dict(tel.get("agents") or {})
    for kind, prompt in plans:
        existing = agents.get(kind)
        if existing:
            st, _ = http(f"/get-agent/{existing}", key=key)
            if st == 200:
                print(f"  ✓ {kind}: already set up ({existing[:18]}…) — keeping it")
                continue
            print(f"  · {kind}: configured id no longer exists on Retell — recreating")
        if DRY:
            print(f"  → would create {kind}: llm ({len(prompt)} chars prompt, begin_message '') "
                  f"+ agent (voice {voice})")
            continue
        st, llm = http("/create-retell-llm",
                       {"general_prompt": prompt, "begin_message": "",
                        "model": "gpt-4.1", "general_tools": TOOLS}, key=key)
        if not (llm or {}).get("llm_id"):
            sys.exit(f"✗ {kind}: Retell refused the brain ({st}: {llm.get('error', '')[:120]})")
        st, ag = http("/create-agent",
                      {"response_engine": {"type": "retell-llm", "llm_id": llm["llm_id"]},
                       "voice_id": voice, "agent_name": f"Jarvis - {kind.capitalize()}",
                       "enable_backchannel": True, "interruption_sensitivity": 0.9}, key=key)
        if not (ag or {}).get("agent_id"):
            sys.exit(f"✗ {kind}: Retell refused the agent ({st}: {ag.get('error', '')[:120]})")
        agents[kind] = ag["agent_id"]
        print(f"  ✓ {kind}: created — {ag['agent_id'][:22]}…")

    if DRY:
        print("Dry run — nothing created, config untouched.")
        return
    tel["agents"] = agents
    tel["agent_id"] = agents.get("booking", tel.get("agent_id", ""))
    tmp = "config.json.tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, "config.json")
    print("\n✓ Done — agent ids written to config.json.")
    print("  Next: set telephony.from (your Retell number) + callback (your cell), then")
    print("  `python3 server.py` — the hotline creates itself on first boot.")
    print("  Voice: swap to your cloned voice in the Retell dashboard whenever you like.")


if __name__ == "__main__":
    main()
