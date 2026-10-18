"""osctl — deterministic macOS control for Jarvis (the "AI OS" layer).

Every action is a real system command (osascript / networksetup / pmset / open / mdfind /
pbcopy), NOT vision-clicking — so it's fast and demo-safe. Anything needing a missing
binary or a TCC grant fails gracefully with a spoken hint instead of crashing.

Python 3 stdlib + (optional) pyobjc for the clipboard watcher. All calls time-boxed.
"""
import os
import re
import shutil
import subprocess
import threading
import time

HOME = os.path.expanduser("~")


def _run(args, timeout=8):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"
    except FileNotFoundError:
        return 127, "", "not found"
    except Exception as e:
        return 1, "", str(e)


def _osa(script, timeout=8):
    return _run(["osascript", "-e", script], timeout)


def have(binary):
    return shutil.which(binary) is not None


# app spoken-name → real macOS application name
APP_ALIASES = {
    "chrome": "Google Chrome", "google chrome": "Google Chrome", "browser": "Google Chrome",
    "safari": "Safari", "notes": "Notes", "finder": "Finder", "terminal": "Terminal",
    "iterm": "iTerm", "vscode": "Visual Studio Code", "vs code": "Visual Studio Code",
    "code": "Visual Studio Code", "slack": "Slack", "spotify": "Spotify", "mail": "Mail",
    "messages": "Messages", "calendar": "Calendar", "music": "Music", "photos": "Photos",
    "preview": "Preview", "figma": "Figma", "obsidian": "Obsidian", "zoom": "zoom.us",
    "discord": "Discord", "arc": "Arc", "settings": "System Settings",
    "system settings": "System Settings", "system preferences": "System Settings",
}
def _q(s):
    """S23: anything interpolated into an AppleScript string literal loses quotes, backslashes and
    newlines — a spoken app name (or a process name reported by System Events) can't close the
    literal and append `do shell script`."""
    return re.sub(r'["\\\r\n]', "", str(s or ""))[:80]

def _app(name):
    n = (name or "").strip()
    return _q(APP_ALIASES.get(n.lower(), n))

WHERE = {
    "left": (0.0, 0.0, 0.5, 1.0), "right": (0.5, 0.0, 0.5, 1.0),
    "top": (0.0, 0.0, 1.0, 0.5), "bottom": (0.0, 0.5, 1.0, 0.5),
    "full": (0.0, 0.0, 1.0, 1.0), "fullscreen": (0.0, 0.0, 1.0, 1.0),
    "maximize": (0.0, 0.0, 1.0, 1.0), "center": (0.15, 0.12, 0.7, 0.76),
    "tl": (0.0, 0.0, 0.5, 0.5), "tr": (0.5, 0.0, 0.5, 0.5),
    "bl": (0.0, 0.5, 0.5, 0.5), "br": (0.5, 0.5, 0.5, 0.5),
    "top-left": (0.0, 0.0, 0.5, 0.5), "top-right": (0.5, 0.0, 0.5, 0.5),
    "bottom-left": (0.0, 0.5, 0.5, 0.5), "bottom-right": (0.5, 0.5, 0.5, 0.5),
}


def _screen():
    code, out, _ = _osa('tell application "Finder" to get bounds of window of desktop')
    try:
        b = [int(x) for x in out.split(", ")]
        return b[2], b[3]                       # width, height
    except Exception:
        return 1920, 1080


# ---------------- system deck ----------------
def volume(v):
    if v in ("mute", "off"):
        _osa("set volume output muted true"); return "Muted, sir."
    if v in ("unmute", "on"):
        _osa("set volume output muted false"); return "Sound's back, sir."
    if v in ("up", "down"):
        cur = _osa("output volume of (get volume settings)")[1]
        try: base = int(cur)
        except Exception: base = 50
        nv = max(0, min(100, base + (12 if v == "up" else -12)))
    else:
        try: nv = max(0, min(100, int(re.sub(r"[^0-9]", "", str(v)))))
        except Exception: return None
    _osa(f"set volume output muted false"); _osa(f"set volume output volume {nv}")
    return f"Volume {nv}, sir."


def dark_mode(v):
    cur = _osa('tell application "System Events" to tell appearance preferences to get dark mode')[1]
    want = {"on": "true", "dark": "true", "off": "false", "light": "false"}.get(v)
    if want is None:                            # toggle
        want = "false" if cur == "true" else "true"
    code, _, err = _osa('tell application "System Events" to tell appearance preferences '
                        f'to set dark mode to {want}')
    if code != 0:
        return _tcc_hint("Automation", err) or "I couldn't reach the appearance settings, sir."
    return "Dark mode on, sir." if want == "true" else "Back to the light, sir."


def brightness(v):
    if have("brightness") and v not in ("up", "down"):
        try:
            lvl = max(0.0, min(1.0, int(re.sub(r"[^0-9]", "", str(v))) / 100.0))
            _run(["brightness", f"{lvl:.2f}"]); return f"Brightness {int(lvl*100)}, sir."
        except Exception:
            pass
    key = 144 if v != "down" else 145           # F-key brightness up/down (best-effort, deps-free)
    code, _, err = _osa(f'tell application "System Events" to key code {key}')
    if code != 0:
        return _tcc_hint("Accessibility", err) or "I can't reach the brightness keys, sir."
    return "Brighter, sir." if v != "down" else "Dimmer, sir."


def nightshift(v):
    on = v not in ("off", "false")
    # No public CLI. Try a user shortcut named "Night Shift On/Off"; else say so.
    name = "Night Shift On" if on else "Night Shift Off"
    code, _, _ = _run(["shortcuts", "run", name], timeout=6)
    if code == 0:
        return f"Night Shift {'on' if on else 'off'}, sir."
    return (f"macOS gives me no direct switch for Night Shift, sir — make a Shortcut named "
            f"\"{name}\" (one action: Set Night Shift) and I'll run it.")


def wifi(v):
    on = v not in ("off", "false", "0")
    code, _, err = _run(["networksetup", "-setairportpower", "en0", "on" if on else "off"])
    if code != 0:
        return f"The Wi-Fi switch wouldn't budge, sir ({err[:40]})."
    return "Wi-Fi on, sir." if on else "Wi-Fi off, sir — you're dark."


def bluetooth(v):
    if not have("blueutil"):
        return "I need blueutil for Bluetooth, sir — `brew install blueutil` and I'll manage the radio."
    arg = "1" if v not in ("off", "false") else "0"
    if v == "toggle": arg = "toggle"
    _run(["blueutil", "-p", arg]); return f"Bluetooth {v}, sir."


def airpods(name, cfg):
    if not have("blueutil"):
        return "I need blueutil to reach your AirPods, sir — `brew install blueutil` first."
    mac = (cfg.get("airpods_mac") or "").strip()
    if not mac:
        return "Tell me your AirPods' Bluetooth address once (config → hardware.airpods_mac), sir."
    code, _, _ = _run(["blueutil", "--connect", mac], timeout=12)
    return "Connecting your AirPods, sir." if code == 0 else "They wouldn't pair, sir."


def sleep_(v):
    if v == "system":
        _run(["pmset", "sleepnow"]); return "Goodnight, sir."
    _run(["pmset", "displaysleepnow"]); return "Screen off, sir."


def focus_mode(on):
    name = "Focus On" if on else "Focus Off"
    code, _, _ = _run(["shortcuts", "run", name], timeout=6)
    if code == 0:
        return f"Do Not Disturb {'on' if on else 'off'}, sir."
    return (f"macOS won't let me set Focus directly, sir — make a Shortcut named \"{name}\" "
            f"(Set Focus → Do Not Disturb) and I'll trigger it.")


# ---------------- apps + windows ----------------
def launch(name):
    app = _app(name)
    code, _, err = _run(["open", "-a", app])
    if code != 0:
        return f"I couldn't find {app}, sir."
    return f"{app} is up, sir."


def quit_app(name):
    app = _app(name)
    _osa(f'tell application "{app}" to quit')
    return f"Closing {app}, sir."


def focus_app(name):
    app = _app(name)
    code, _, err = _osa(f'tell application "{app}" to activate')
    return f"{app}, sir." if code == 0 else f"I couldn't bring up {app}, sir."


BG_KEEP = {"Finder", "jarvis", "Python"}
def clean_slate(keep):
    keep_set = {(_app(k)).lower() for k in (keep or [])} | {k.lower() for k in BG_KEEP}
    code, out, _ = _osa('tell application "System Events" to get name of '
                        '(every process whose background only is false)')
    apps = [a.strip() for a in out.split(", ") if a.strip()]
    closed = []
    for a in apps:
        if a.lower() in keep_set or a.lower() in ("system events",):
            continue
        _osa(f'tell application "{_q(a)}" to quit')
        closed.append(a)
    if not closed:
        return "Nothing to clear, sir — the deck's already clean."
    return f"Cleared {len(closed)}, sir: {', '.join(closed[:6])}{'…' if len(closed) > 6 else ''}."


def window(name, where):
    spec = WHERE.get((where or "").strip().lower())
    if not spec:
        return None
    app = _app(name)
    W, H = _screen(); menu = 25
    fx, fy, fw, fh = spec
    x, y = int(W * fx), int(menu + (H - menu) * fy)
    w, h = int(W * fw), int((H - menu) * fh)
    script = (f'tell application "{app}" to activate\n'
              f'delay 0.15\n'
              f'tell application "System Events" to tell process "{app}"\n'
              f'  set position of window 1 to {{{x}, {y}}}\n'
              f'  set size of window 1 to {{{w}, {h}}}\n'
              f'end tell')
    code, _, err = _osa(script, timeout=10)
    if code != 0:
        return _tcc_hint("Accessibility", err) or f"I couldn't move {app}, sir."
    return f"{app} {where}, sir."


def arrange(spec):
    """spec: 'chrome:left; notes:right' → snap several windows in one breath."""
    results, ok = [], 0
    for part in re.split(r"[;,]", spec):
        if ":" not in part:
            continue
        app, where = part.split(":", 1)
        r = window(app.strip(), where.strip())
        if r and "sir" in r and "couldn't" not in r and "reach" not in r:
            ok += 1
        results.append(r or f"couldn't place {app}")
    if ok >= 2:
        return f"Arranged, sir — {ok} windows in place."
    return results[0] if results else "Nothing to arrange, sir."


SCENES = {
    "evening": [("dark", "on"), ("brightness", "down"), ("nightshift", "on"), ("volume", "35")],
    "cinema":  [("dark", "on"), ("brightness", "down"), ("volume", "60"), ("dnd", "on")],
    "focus":   [("dnd", "on"), ("dark", "on")],
    "bright":  [("dark", "off"), ("brightness", "up")],
    "morning": [("dark", "off"), ("brightness", "up"), ("nightshift", "off")],
}
def scene(name):
    steps = SCENES.get((name or "").strip().lower())
    if not steps:
        return None
    for act, val in steps:
        try:
            do(act, val, {})
        except Exception:
            pass
    return f"{name.capitalize()} mode, sir." + (" The room's yours." if name in ("evening", "cinema") else "")


# ---------------- file search ----------------
def find_files(query, limit=6, open_top=False):
    q = (query or "").strip()
    if not q:
        return None, "Find what, sir?"
    code, out, _ = _run(["mdfind", "-onlyin", HOME, "-interpret", q], timeout=8)
    hits = [h for h in out.splitlines() if h.strip()][:limit]
    if not hits:
        return {"hits": [], "spoken": f"Nothing matching “{q}”, sir."}, None
    if open_top:
        _run(["open", hits[0]])
    names = [os.path.basename(h) for h in hits]
    spoken = (f"Found {names[0]}" + (f", and {len(hits)-1} more" if len(hits) > 1 else "") +
              (" — opening it now, sir." if open_top else ", sir."))
    return {"hits": hits, "names": names, "spoken": spoken}, None


# ---------------- universal typing ----------------
def type_text(text):
    """Paste `text` into whatever app has focus (clipboard + Cmd-V, clipboard restored)."""
    text = text or ""
    if not text:
        return "Nothing to type, sir."
    old = _run(["pbpaste"])[1]
    p = subprocess.run(["pbcopy"], input=text, text=True)
    time.sleep(0.05)
    code, _, err = _osa('tell application "System Events" to keystroke "v" using command down')
    time.sleep(0.15)
    subprocess.run(["pbcopy"], input=old, text=True)          # restore the user's clipboard
    if code != 0:
        return _tcc_hint("Accessibility", err) or "I couldn't type that in, sir."
    return "Typed it in, sir."


# ---------------- clipboard ----------------
def clip_read():
    return _run(["pbpaste"])[1]
def clip_write(text):
    subprocess.run(["pbcopy"], input=text or "", text=True)


_CLIP = {"hist": [], "count": -1}
_CLIP_LOCK = threading.Lock()
def clip_history(n=10):
    with _CLIP_LOCK:
        return list(_CLIP["hist"])[-n:][::-1]
def _clip_watch():
    try:
        from AppKit import NSPasteboard
        pb = NSPasteboard.generalPasteboard()
    except Exception:
        return
    while True:
        try:
            c = pb.changeCount()
            if c != _CLIP["count"]:
                _CLIP["count"] = c
                s = pb.stringForType_("public.utf8-plain-text")
                if s:
                    s = str(s)
                    with _CLIP_LOCK:
                        if not _CLIP["hist"] or _CLIP["hist"][-1][0] != s:
                            _CLIP["hist"].append((s, int(time.time())))
                            del _CLIP["hist"][:-40]
        except Exception:
            pass
        time.sleep(0.6)
def start_clip_watch():
    threading.Thread(target=_clip_watch, daemon=True).start()


# ---------------- dispatch ----------------
def _tcc_hint(kind, err):
    e = (err or "").lower()
    if "not allowed" in e or "-1743" in e or "assistive" in e or "accessibility" in e or "1002" in e:
        return (f"macOS is blocking me, sir — grant this Terminal/Python **{kind}** access in "
                f"System Settings → Privacy & Security → {kind}, then ask again.")
    return None


def do(action, value, cfg):
    """Return a spoken result string, or None if the action/value is unknown."""
    a = (action or "").strip().lower()
    v = (str(value).strip().lower() if value is not None else "")
    if a == "volume": return volume(v)
    if a in ("dark", "dark_mode", "appearance", "theme"): return dark_mode(v)
    if a == "brightness": return brightness(v)
    if a in ("nightshift", "night_shift"): return nightshift(v)
    if a == "wifi": return wifi(v)
    if a == "bluetooth": return bluetooth(v)
    if a == "airpods": return airpods(value, cfg or {})
    if a == "sleep": return sleep_(v or "display")
    if a in ("dnd", "focus", "focus_mode"): return focus_mode(v not in ("off", "false"))
    if a in ("launch", "open"): return launch(value)
    if a == "quit": return quit_app(value)
    if a in ("switch", "focus_app", "activate"): return focus_app(value)
    if a in ("clean_slate", "clean", "quit_all"):
        keep = value if isinstance(value, list) else [x for x in re.split(r"[;,]", v) if x.strip()]
        return clean_slate(keep)
    if a == "window":
        if ":" in v or ";" in v: return arrange(str(value))
        parts = v.rsplit(" ", 1)
        return window(parts[0], parts[1]) if len(parts) == 2 else None
    if a == "arrange": return arrange(str(value))
    if a == "scene": return scene(v)
    return None
