#!/usr/bin/env python3
"""Jarvis 7.2 — set up X-RAY VISION (REA, "Reverse Engineer Anything") and the BUILDER.

Run:  python3 setup_rea.py          (installs + checks everything)
      python3 setup_rea.py --check  (checks only, installs nothing)

What it does, in plain words:
  1. finds Node.js 22.19+ (or 24.11+) — REA runs on it; if it's missing it prints the one install line for your OS
  2. installs REA, pinned to the exact version Jarvis was built and tested with, into ~/.jarvis-tools/rea
     (nothing global, nothing in your project, install scripts disabled)
  3. writes the MCP registration Jarvis's workers use (~/.jarvis-tools/rea/mcp.json)
  4. checks Google Chrome (the clean browser teardowns run in) and the `claude` CLI (the builder's hands)
Python 3 standard library only. Safe to run twice."""
import os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CHECK_ONLY = "--check" in sys.argv

def say(ok, text):
    print(("  ✓ " if ok else "  ✗ ") + text)

try:
    import teardown as TD
except Exception as e:
    print("✗ teardown.py didn't import (%s) — run this from the Jarvis folder" % e)
    sys.exit(1)

HOME = TD.TOOLS_HOME
PIN = TD.REA_PIN
WIN = os.name == "nt"

def find_node():
    cands = [shutil.which("node"), os.path.expanduser("~/.local/bin/node"), "/opt/homebrew/bin/node", "/usr/local/bin/node",
             os.path.join(os.environ.get("ProgramFiles", ""), "nodejs", "node.exe") if WIN else None]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None

def node_version(node):
    try:
        return subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""

def find_npm(node):
    for c in (shutil.which("npm"), shutil.which("npm.cmd") if WIN else None,
              os.path.join(os.path.dirname(node), "npm.cmd" if WIN else "npm") if node else None):
        if c and os.path.exists(c):
            return c
    return None

print("Jarvis 7.2 · X-ray vision setup (REA %s)" % PIN)

# 1. Node
node = find_node()
nv = node_version(node) if node else ""
if not node or not TD._node_ok(nv):
    say(False, "Node.js 22.19+ not found" + (" (found %s)" % nv if nv else ""))
    print("     Install it, then run this again:")
    print("       Mac:      brew install node@22      (or download the LTS installer at nodejs.org)")
    print("       Windows:  winget install OpenJS.NodeJS.LTS   (or the LTS installer at nodejs.org)")
    sys.exit(2)
say(True, "Node.js %s at %s" % (nv, node))

# 2. REA, pinned
entry = TD._rea_entry()
have = TD._rea_version()
if have == PIN and entry:
    say(True, "REA %s already installed in %s" % (PIN, HOME))
elif CHECK_ONLY:
    say(False, "REA %s not installed (found %s)" % (PIN, have or "nothing"))
    sys.exit(2)
else:
    npm = find_npm(node)
    if not npm:
        say(False, "npm not found next to Node — reinstall Node.js from nodejs.org (it includes npm)")
        sys.exit(2)
    os.makedirs(HOME, exist_ok=True)
    print("  … installing REA %s (one minute; no install scripts run)" % PIN)
    r = subprocess.run([npm, "install", "rea-agents@" + PIN, "--prefix", HOME, "--ignore-scripts", "--no-fund", "--no-audit"],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or TD._rea_version() != PIN:
        say(False, "npm install failed:\n" + (r.stderr or r.stdout)[-600:])
        sys.exit(1)
    say(True, "REA %s installed in %s" % (PIN, HOME))

# 3. the MCP registration for the workers
try:
    import json
    cfg = json.load(open(os.path.join(HERE, "config.json"))) if os.path.exists(os.path.join(HERE, "config.json")) else {}
except Exception:
    cfg = {}
TD.CTX.update({"cfg": cfg})
mcp = TD.mcp_config()
say(bool(mcp), "workers' MCP registration → %s" % (mcp or "could not write"))

# 4. Chrome + claude
chrome = TD._find_chrome()
say(bool(chrome), "Google Chrome " + (chrome if chrome else "not found — install it from google.com/chrome (teardowns open a clean Chrome window)"))
claude = shutil.which("claude") or (shutil.which("claude.cmd") if WIN else None) or os.path.expanduser("~/.local/bin/claude")
say(bool(claude and os.path.exists(claude)), "claude CLI " + (claude if claude and os.path.exists(claude) else "not found — the builder and the app teardowns need Claude Code installed and logged in"))

# 5. the catalog boots?
if not CHECK_ONLY or True:
    try:
        import json as _j, select as _s, time as _t
        p = subprocess.Popen([node, entry or TD._rea_entry(), "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        p.stdin.write(_j.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "setup", "version": "0"}}}) + "\n"); p.stdin.flush()
        line, end = "", _t.time() + 40
        while _t.time() < end:
            if WIN:
                line = p.stdout.readline(); break
            r, _, _ = _s.select([p.stdout], [], [], 0.5)
            if r:
                line = p.stdout.readline(); break
        p.kill()
        say('"serverInfo"' in line, "REA's tool catalog boots" if '"serverInfo"' in line else "REA's tool catalog did not answer (run: node %s doctor)" % (entry or ""))
    except Exception as e:
        say(False, "could not boot REA (%s)" % e)

print("\nDone. Start (or restart) Jarvis, then say:  \"Jarvis, reverse engineer igloo dot inc\"  or  \"take apart the Notes app on my Mac\".")
print("Build: \"Jarvis, build me a notes app like Apple Notes\" · chain: \"reverse engineer igloo dot inc and build me my own version\".")
