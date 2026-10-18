"""Jarvis HANDS — permission-gated computer takeover. Mac + Windows (beta).

"May I take the wheel, sir?" → "go ahead" → Jarvis drives the real machine to do a task
(fill this form, show me how to do X) using Claude's computer-use vision loop:
screenshot → Claude picks an action → we execute it → screenshot → repeat,
until Claude says it's done, the step cap is hit, the user hits STOP, or the user grabs the
physical mouse. Never submits payment/purchase/delete forms — it fills them and stops for you.

Input synthesis per platform (the TARS-proven cross-platform layer, ported 2026-08-20):
Mac = Quartz CGEvents + `screencapture`; Windows = ctypes SendInput + a PowerShell
System.Drawing grab — pure stdlib on both, nothing to pip-install. Mac needs the TCC grants
the FIRST time (Screen Recording + Accessibility for the process running the server);
Windows needs no permission switches at all.

Plug-in bay contract (like missions/tools): server.py soft-imports `hands as HANDS`, routes
/hands* through handle(), and calls init() at boot. State is in-memory only (nothing persisted).
"""
import base64, json, os, subprocess, sys, tempfile, threading, time, urllib.error, urllib.parse, urllib.request

IS_WIN = sys.platform == "win32"

CTX = {}                         # init() fills: cfg, model, key, base, jpersona, mem_block, presence, log
RUN = {"active": False, "stop": False, "task": "", "started": 0.0}
EVENTS = []                      # normalized [{ts, kind, text}] the client polls; kind: say|action|done|error|need_confirm
EV_LOCK = threading.Lock()
PENDING = {}                     # confirm_id -> task text awaiting "go ahead"

MAX_STEPS = 40
MAX_SECONDS = 300
SEND_W = 1280                    # downscale screenshots to this width — best click accuracy + cheap tokens
# SPEED TIERS — the vision loop is round-trip-bound (screenshot→model→CGEvent→re-screenshot), so the
# only real lever is the model. Computer-use tool versions are PINNED PER MODEL (verified live, ported
# from TARS): Haiku takes computer_20250124/2025-01-24; Sonnet 5 & Opus 4.8 take the newer pair — the
# cross-pairs 400. Takeover ALWAYS runs on a Claude model regardless of the chat brain.
SPEED_TIERS = {
    "fast":     ("claude-haiku-4-5", "computer_20250124", "computer-use-2025-01-24"),
    "balanced": ("claude-sonnet-5",  "computer_20251124", "computer-use-2025-11-24"),
    "smart":    ("claude-opus-4-8",  "computer_20251124", "computer-use-2025-11-24"),
}
SPEED = "balanced"               # far faster than Opus, far more accurate than Haiku — the sweet spot
COMPUTER_MODEL, TOOL_TYPE, TOOL_BETA = SPEED_TIERS[SPEED]

def set_speed(tier):
    """Pick the takeover model/tool tier: fast | balanced | smart. Returns the active tier."""
    global SPEED, COMPUTER_MODEL, TOOL_TYPE, TOOL_BETA
    if tier in SPEED_TIERS:
        SPEED = tier
        COMPUTER_MODEL, TOOL_TYPE, TOOL_BETA = SPEED_TIERS[tier]
    return SPEED
# tasks that must NOT be auto-driven to completion — fill, then stop and hand back
DANGER = ("buy", "purchase", "pay ", "payment", "checkout", "place order", "wire ", "send money",
          "delete account", "close account", "transfer", "confirm order")

# ---------- event log ----------

def _orb_release(presence):
    """Drive over: hand the desktop orb back to the screen-share if one still holds a claim,
    else clear it off the desktop (2026-08-11: state:idle alone stranded the orb after
    share-free drives — it stayed up forever)."""
    if not presence:
        return
    try:
        live = bool(CTX.get("share_on") and CTX["share_on"]())
    except Exception:
        live = False
    presence("state:idle" if live else "hide")


def emit(kind, text):
    with EV_LOCK:
        EVENTS.append({"ts": time.time(), "kind": kind, "text": text})
        if len(EVENTS) > 400: del EVENTS[:200]
    if kind in ("say", "action", "done", "error") and CTX.get("log"):
        try: CTX["log"](kind, text)
        except Exception: pass

def events_since(n):
    with EV_LOCK:
        return EVENTS[max(0, n):], len(EVENTS)

# ---------- platform input layer: Quartz (Mac) / ctypes SendInput (Windows, TARS-proven) ----------

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    try:    # be DPI-aware so cursor/coordinate math matches real pixels on scaled displays
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            _user32.SetProcessDPIAware()
        except Exception:
            pass

    _ULONG_PTR = wintypes.WPARAM   # pointer-sized unsigned int

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", _ULONG_PTR)]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", _ULONG_PTR)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    def _send(*inputs):
        arr = (_INPUT * len(inputs))(*inputs)
        _user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))

    def _mi(dx=0, dy=0, data=0, flags=0):
        return _INPUT(0, _INPUTUNION(mi=_MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)))

    def _ki(vk=0, scan=0, flags=0):
        return _INPUT(1, _INPUTUNION(ki=_KEYBDINPUT(vk, scan, flags, 0, 0)))

    def _abs_xy(x, y):
        # MOUSEEVENTF_ABSOLUTE normalizes 0..65535 over the PRIMARY display —
        # which is also the only display we capture, so the math stays honest
        w = _user32.GetSystemMetrics(0) or 1
        h = _user32.GetSystemMetrics(1) or 1
        return int(x * 65535 / max(1, w - 1)), int(y * 65535 / max(1, h - 1))

    _WIN_BTN = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010),
                "middle": (0x0020, 0x0040)}

    # primary-screen JPEG via System.Drawing, downscaled to {W}; prints "w h" on success
    _PS_GRAB = (
        "Add-Type -AssemblyName System.Drawing;"
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$bd=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
        "$bmp=New-Object System.Drawing.Bitmap $bd.Width,$bd.Height;"
        "$g=[System.Drawing.Graphics]::FromImage($bmp);"
        "$g.CopyFromScreen($bd.Location,[System.Drawing.Point]::Empty,$bd.Size);"
        "$w={W};$h=[int][math]::Round($bd.Height*$w/$bd.Width);"
        "$sm=New-Object System.Drawing.Bitmap $bmp,$w,$h;"
        "$enc=[System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders()|"
        "Where-Object{$_.MimeType -eq 'image/jpeg'};"
        "$ep=New-Object System.Drawing.Imaging.EncoderParameters 1;"
        "$ep.Param[0]=New-Object System.Drawing.Imaging.EncoderParameter("
        "[System.Drawing.Imaging.Encoder]::Quality,[long]72);"
        "$sm.Save('{PATH}',$enc,$ep);"
        "Write-Output ($w.ToString()+' '+$h.ToString());"
        "$g.Dispose();$bmp.Dispose();$sm.Dispose()"
    )

def _q():
    import Quartz
    return Quartz

def screen_points():
    """Main-display size in POINTS (CGEvent coordinate space; ≠ pixels on Retina)."""
    if IS_WIN:
        return _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)
    Q = _q()
    b = Q.CGDisplayBounds(Q.CGMainDisplayID())
    return int(b.size.width), int(b.size.height)

def grab_screen():
    """(b64 jpeg, sent_w, sent_h) — a fresh screenshot downscaled to SEND_W. None on failure."""
    if IS_WIN:
        # Pillow first when present: pure GDI, immune to the constrained-language PowerShell
        # that Smart App Control / locked-down Defender boxes enforce (Add-Type is blocked
        # there → "capture failed", first member report 2026-08-20). The PowerShell
        # System.Drawing grab below stays as the zero-install fallback.
        try:
            import io
            from PIL import ImageGrab
            img = ImageGrab.grab()
            w0, h0 = img.size
            h1 = max(1, round(h0 * SEND_W / max(1, w0)))
            img = img.convert("RGB").resize((SEND_W, h1))
            buf = io.BytesIO(); img.save(buf, "JPEG", quality=72)
            return base64.b64encode(buf.getvalue()).decode(), SEND_W, h1
        except Exception:
            pass
        fd, path = tempfile.mkstemp(suffix=".jpg"); os.close(fd)
        try:
            script = (_PS_GRAB.replace("{W}", str(SEND_W))
                              .replace("{PATH}", path.replace("'", "''")))
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                                "-Command", script],
                               capture_output=True, text=True, timeout=25)
            out = (r.stdout or "").strip().splitlines()
            if r.returncode != 0 or not out or not os.path.getsize(path):
                return None, 0, 0
            w, h = (int(v) for v in out[-1].split()[:2])
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode(), (w or SEND_W), (h or 800)
        except Exception:
            return None, 0, 0
        finally:
            try: os.remove(path)
            except OSError: pass
    fd, raw = tempfile.mkstemp(suffix=".jpg"); os.close(fd)
    small = raw.replace(".jpg", "-s.jpg")
    try:
        r = subprocess.run(["screencapture", "-x", "-o", "-t", "jpg", "-m", raw],
                           capture_output=True, timeout=15)
        if r.returncode != 0 or not os.path.getsize(raw):
            return None, 0, 0
        subprocess.run(["sips", "--resampleWidth", str(SEND_W), raw, "--out", small],
                       capture_output=True, timeout=15)
        use = small if os.path.exists(small) else raw
        dims = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", use],
                             capture_output=True, text=True, timeout=10).stdout
        w = h = 0
        for line in dims.splitlines():
            if "pixelWidth:" in line: w = int(line.split(":")[1])
            if "pixelHeight:" in line: h = int(line.split(":")[1])
        with open(use, "rb") as f:
            return base64.b64encode(f.read()).decode(), (w or SEND_W), (h or 800)
    except Exception:
        return None, 0, 0
    finally:
        for f in (raw, small):
            try: os.remove(f)
            except OSError: pass

def cursor_point():
    if IS_WIN:
        pt = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        return (float(pt.x), float(pt.y))
    Q = _q()
    e = Q.CGEventCreate(None)
    loc = Q.CGEventGetLocation(e)
    return (loc.x, loc.y)

def _mouse(x, y, etype, button):
    Q = _q()
    ev = Q.CGEventCreateMouseEvent(None, etype, (x, y), button)
    Q.CGEventPost(Q.kCGHIDEventTap, ev)

def move_to(x, y):
    if IS_WIN:
        ax, ay = _abs_xy(x, y)
        _send(_mi(ax, ay, 0, 0x0001 | 0x8000))    # MOVE | ABSOLUTE
        return
    Q = _q()
    _mouse(x, y, Q.kCGEventMouseMoved, 0)

def click_at(x, y, button="left", count=1):
    if IS_WIN:
        down, up = _WIN_BTN[button]
        move_to(x, y); time.sleep(0.03)
        for _ in range(count):
            _send(_mi(0, 0, 0, down))
            _send(_mi(0, 0, 0, up))
            time.sleep(0.04)
        return
    Q = _q()
    down = {"left": Q.kCGEventLeftMouseDown, "right": Q.kCGEventRightMouseDown,
            "middle": Q.kCGEventOtherMouseDown}[button]
    up = {"left": Q.kCGEventLeftMouseUp, "right": Q.kCGEventRightMouseUp,
          "middle": Q.kCGEventOtherMouseUp}[button]
    btn = {"left": 0, "right": 1, "middle": 2}[button]
    move_to(x, y); time.sleep(0.03)
    for i in range(count):
        d = Q.CGEventCreateMouseEvent(None, down, (x, y), btn)
        Q.CGEventSetIntegerValueField(d, Q.kCGMouseEventClickState, i + 1)
        Q.CGEventPost(Q.kCGHIDEventTap, d)
        u = Q.CGEventCreateMouseEvent(None, up, (x, y), btn)
        Q.CGEventSetIntegerValueField(u, Q.kCGMouseEventClickState, i + 1)
        Q.CGEventPost(Q.kCGHIDEventTap, u)
        time.sleep(0.04)

def drag(x1, y1, x2, y2):
    if IS_WIN:
        move_to(x1, y1); time.sleep(0.03)
        _send(_mi(0, 0, 0, 0x0002)); time.sleep(0.05)     # LEFTDOWN
        steps = 12
        for i in range(1, steps + 1):
            move_to(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)
            time.sleep(0.012)
        _send(_mi(0, 0, 0, 0x0004))                        # LEFTUP
        return
    Q = _q()
    move_to(x1, y1); time.sleep(0.03)
    _mouse(x1, y1, Q.kCGEventLeftMouseDown, 0); time.sleep(0.05)
    steps = 12
    for i in range(1, steps + 1):
        _mouse(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps, Q.kCGEventLeftMouseDragged, 0)
        time.sleep(0.012)
    _mouse(x2, y2, Q.kCGEventLeftMouseUp, 0)

def scroll(dy, dx=0):
    if IS_WIN:
        # WHEEL delta 120/line; positive = up/away, matching the Quartz sign convention
        if int(dy):
            _send(_mi(0, 0, int(dy) * 120, 0x0800))
        if int(dx):
            _send(_mi(0, 0, int(-dx) * 120, 0x1000))       # HWHEEL positive = right
        return
    Q = _q()
    ev = Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitLine, 2, int(dy), int(dx))
    Q.CGEventPost(Q.kCGHIDEventTap, ev)

def type_text(text):
    if IS_WIN:
        for ch in text:
            if ch in ("\n", "\r"):
                press_key("enter"); time.sleep(0.008); continue
            if ch == "\t":
                press_key("tab"); time.sleep(0.008); continue
            units = ch.encode("utf-16-le")                 # surrogate pairs ride as 2 units
            for i in range(0, len(units), 2):
                scan = int.from_bytes(units[i:i + 2], "little")
                _send(_ki(0, scan, 0x0004))                # KEYEVENTF_UNICODE
                _send(_ki(0, scan, 0x0004 | 0x0002))       # … | KEYUP
            time.sleep(0.008)
        return
    Q = _q()
    for ch in text:
        for down in (True, False):
            e = Q.CGEventCreateKeyboardEvent(None, 0, down)
            Q.CGEventKeyboardSetUnicodeString(e, len(ch), ch)
            Q.CGEventPost(Q.kCGHIDEventTap, e)
        time.sleep(0.008)

# US-ANSI virtual keycodes for the keys Claude's `key` action emits (xdotool-style names)
KEYCODE = {"return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51, "backspace": 51,
           "escape": 53, "esc": 53, "left": 123, "right": 124, "down": 125, "up": 126,
           "home": 115, "end": 119, "pageup": 116, "page_up": 116, "pagedown": 121, "page_down": 121,
           "forward_delete": 117, "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7,
           "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31,
           "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
           "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26, "8": 28, "9": 25, "0": 29}
MODS = {"cmd": "kCGEventFlagMaskCommand", "command": "kCGEventFlagMaskCommand", "meta": "kCGEventFlagMaskCommand",
        "super": "kCGEventFlagMaskCommand", "ctrl": "kCGEventFlagMaskControl", "control": "kCGEventFlagMaskControl",
        "alt": "kCGEventFlagMaskAlternate", "option": "kCGEventFlagMaskAlternate",
        "shift": "kCGEventFlagMaskShift"}

# Windows virtual-key codes (delete = real DEL here — Windows convention, not Mac's)
WIN_VK = {"return": 0x0D, "enter": 0x0D, "tab": 0x09, "space": 0x20,
          "backspace": 0x08, "delete": 0x2E, "forward_delete": 0x2E,
          "escape": 0x1B, "esc": 0x1B, "left": 0x25, "up": 0x26, "right": 0x27,
          "down": 0x28, "home": 0x24, "end": 0x23, "pageup": 0x21, "page_up": 0x21,
          "pagedown": 0x22, "page_down": 0x22}
for _c in "abcdefghijklmnopqrstuvwxyz0123456789":
    WIN_VK[_c] = ord(_c.upper())
for _i in range(1, 13):
    WIN_VK["f%d" % _i] = 0x6F + _i
# cmd/meta map to Ctrl — a model slipping into Mac muscle memory ("cmd+l") must
# NEVER hit the Win key by accident (win+l locks the whole machine)
WIN_MODS = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "option": 0x12,
            "shift": 0x10, "cmd": 0x11, "command": 0x11, "meta": 0x11,
            "win": 0x5B, "super": 0x5B}

def press_key(combo):
    """combo like 'cmd+a', 'Return', 'ctrl+shift+t'. Best-effort; unknown keys are skipped."""
    parts = [p.strip().lower() for p in combo.replace(" ", "").split("+") if p.strip()]
    if not parts: return
    if IS_WIN:
        vk = WIN_VK.get(parts[-1])
        if vk is None: return
        mods = [WIN_MODS[m] for m in parts[:-1] if m in WIN_MODS]
        for m in mods:
            _send(_ki(m, 0, 0))
        _send(_ki(vk, 0, 0))
        _send(_ki(vk, 0, 0x0002))
        for m in reversed(mods):
            _send(_ki(m, 0, 0x0002))
        return
    Q = _q()
    keyname = parts[-1]
    kc = KEYCODE.get(keyname)
    if kc is None: return
    flags = 0
    for m in parts[:-1]:
        f = MODS.get(m)
        if f: flags |= getattr(Q, f)
    down = Q.CGEventCreateKeyboardEvent(None, kc, True)
    Q.CGEventSetFlags(down, flags)
    Q.CGEventPost(Q.kCGHIDEventTap, down)
    up = Q.CGEventCreateKeyboardEvent(None, kc, False)
    Q.CGEventSetFlags(up, flags)
    Q.CGEventPost(Q.kCGHIDEventTap, up)

# ---------- action dispatch (computer_20250124 vocabulary) ----------

SCALE = {"sx": 1.0, "sy": 1.0}   # sent-space → point-space multipliers, set per run

def _pt(coord):
    return int(coord[0] * SCALE["sx"]), int(coord[1] * SCALE["sy"])

def describe(inp):
    a = inp.get("action", "?")
    if a in ("left_click", "right_click", "double_click", "middle_click", "triple_click") and inp.get("coordinate"):
        return f"{a.replace('_', ' ')} at {inp['coordinate']}"
    if a == "type": return f"type “{(inp.get('text') or '')[:40]}”"
    if a == "key": return f"press {inp.get('text')}"
    if a == "scroll": return f"scroll {inp.get('scroll_direction', '')}"
    if a == "left_click_drag": return "drag"
    return a.replace("_", " ")

def execute(inp):
    """Run one computer action. Returns True if a settle-delay is warranted."""
    a = inp.get("action")
    coord = inp.get("coordinate")
    if a in ("left_click", "right_click", "middle_click", "double_click", "triple_click") and coord:
        x, y = _pt(coord)
        btn = "right" if a == "right_click" else "middle" if a == "middle_click" else "left"
        cnt = 2 if a == "double_click" else 3 if a == "triple_click" else 1
        click_at(x, y, btn, cnt); return True
    if a == "mouse_move" and coord:
        x, y = _pt(coord); move_to(x, y); return False
    if a == "left_click_drag" and coord:
        sc = inp.get("start_coordinate")
        x2, y2 = _pt(coord)
        x1, y1 = _pt(sc) if sc else cursor_point()
        drag(x1, y1, x2, y2); return True
    if a == "type":
        type_text(inp.get("text") or ""); return True
    if a == "key":
        press_key(inp.get("text") or ""); return True
    if a == "scroll":
        amt = int(inp.get("scroll_amount") or 3)
        d = (inp.get("scroll_direction") or "down").lower()
        if coord: move_to(*_pt(coord))
        scroll(-amt if d == "down" else amt if d == "up" else 0,
               -amt if d == "right" else amt if d == "left" else 0)
        return True
    if a == "wait":
        time.sleep(min(3.0, float(inp.get("duration") or 1))); return False
    # screenshot / cursor_position / unknown → just re-screenshot
    return False

# ---------- the takeover loop ----------

def call_model(messages, tools, max_tokens=1500):
    key, base = CTX.get("key", ""), (CTX.get("base") or "").strip().rstrip("/")
    url = (base + "/v1/messages") if base else "https://api.anthropic.com/v1/messages"
    body = json.dumps({"model": COMPUTER_MODEL, "max_tokens": max_tokens,
                       "system": CTX["system"], "messages": messages, "tools": tools}).encode()
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01",
               "anthropic-beta": TOOL_BETA, "content-type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)

def _trim_images(messages, keep=3):
    """Replace all but the last `keep` screenshot blocks with a placeholder — bounds token cost."""
    coords = []                  # tool_result image blocks, oldest first
    for mi, m in enumerate(messages):
        if not isinstance(m.get("content"), list): continue
        for b in m["content"]:
            if b.get("type") == "tool_result" and isinstance(b.get("content"), list):
                for sub in b["content"]:
                    if sub.get("type") == "image":
                        coords.append(sub)
    for sub in coords[:-keep] if len(coords) > keep else []:
        sub.clear(); sub.update({"type": "text", "text": "[earlier screenshot omitted]"})

def run(task, sid=None):
    key = CTX.get("key", "")
    if not key or key.startswith("PUT-"):
        emit("error", "model not configured, sir"); RUN["active"] = False; return
    provider = (CTX.get("provider") or "anthropic").strip().lower()
    base = (CTX.get("base") or "").strip()
    if provider != "anthropic" or (base and "api.anthropic.com" not in base):
        emit("error", "computer control runs on the Claude brain — config.json's model block isn't Anthropic")
        RUN["active"] = False; return

    presence = CTX.get("presence")
    if presence: presence("show"); presence("state:working")
    b64, sw, sh = grab_screen()
    if not b64:
        emit("error", ("I can't see the screen, sir — the PowerShell capture failed; make sure "
                       "this is a real desktop session, then let me try again.") if IS_WIN else
                      ("I can't see the screen, sir — grant Screen Recording to this app in System "
                       "Settings → Privacy & Security, then let me try again."))
        RUN["active"] = False
        _orb_release(presence)
        return
    pw, ph = screen_points()
    SCALE["sx"], SCALE["sy"] = pw / sw, ph / sh

    danger = any(d in task.lower() for d in DANGER)
    CTX["system"] = (CTX["jpersona"]() + CTX["mem_block"]() +
        f"You are controlling the user's real Mac to accomplish this task: {task}\n"
        "Use the computer tool. A screenshot is attached — look, then act step by step. Prefer "
        "keyboard where reliable (cmd+L for the address bar, Tab between fields). Keep going until "
        "the task is genuinely done, then STOP and end your turn with ONE short spoken sentence to "
        "'sir' summarizing what you did. "
        + ("IMPORTANT: this task is near a payment/purchase/irreversible action — FILL everything "
           "but DO NOT click the final buy/pay/submit/delete button. Stop just before it and tell "
           "sir it's ready for his click. " if danger else "") +
        "Between actions, briefly narrate what you're about to do in one short phrase.")

    tools = [{"type": TOOL_TYPE, "name": "computer",
              "display_width_px": sw, "display_height_px": sh, "display_number": 1}]
    messages = [{"role": "user", "content": [
        {"type": "text", "text": task + "  (screenshot attached — begin)"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}]}]

    last_cursor = None
    t0 = time.time()
    try:
        for step in range(MAX_STEPS):
            if RUN["stop"]:
                emit("done", "Stopped, sir."); break
            if time.time() - t0 > MAX_SECONDS:
                emit("done", "That's taken long enough, sir — I'll pause here."); break
            # physical-mouse abort: if the cursor jumped and we didn't move it, the user grabbed control
            if last_cursor:
                cx, cy = cursor_point()
                if ((cx - last_cursor[0]) ** 2 + (cy - last_cursor[1]) ** 2) ** 0.5 > 90:
                    emit("done", "You've taken the wheel, sir — I'll step back."); break

            _trim_images(messages)
            try:
                resp = call_model(messages, tools)
            except urllib.error.HTTPError as e:
                emit("error", f"the brain balked ({e.code}) — {e.read().decode(errors='ignore')[:120]}"); break
            except Exception as e:
                emit("error", f"connection hiccup, sir: {str(e)[:100]}"); break

            content = resp.get("content", [])
            messages.append({"role": "assistant", "content": content})
            for b in content:
                if b.get("type") == "text" and b.get("text", "").strip():
                    emit("say", b["text"].strip())
            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if resp.get("stop_reason") != "tool_use" or not tool_uses:
                final = " ".join(b["text"].strip() for b in content if b.get("type") == "text")
                emit("done", final or "Done, sir."); break

            results = []
            for tu in tool_uses:
                if RUN["stop"]: break
                inp = tu.get("input") or {}
                emit("action", describe(inp))
                settle = False
                try:
                    settle = execute(inp)
                except Exception as e:
                    emit("error", f"that action slipped, sir: {str(e)[:80]}")
                time.sleep(0.4 if settle else 0.15)
                last_cursor = cursor_point()
                shot, sw2, sh2 = grab_screen()
                if shot:
                    results.append({"type": "tool_result", "tool_use_id": tu["id"],
                                    "content": [{"type": "image", "source": {"type": "base64",
                                                 "media_type": "image/jpeg", "data": shot}}]})
                else:
                    results.append({"type": "tool_result", "tool_use_id": tu["id"],
                                    "content": [{"type": "text", "text": "action done (no screenshot)"}]})
            messages.append({"role": "user", "content": results})
        else:
            emit("done", "I've done what I safely can in one go, sir.")
    finally:
        RUN["active"] = False; RUN["stop"] = False
        _orb_release(presence)

# ---------- HTTP surface ----------

def handle(handler, method, raw_path, payload):
    path = raw_path.split("?")[0]
    p = payload or {}

    if method == "GET" and path == "/api/hands":
        q = urllib.parse.parse_qs(urllib.parse.urlparse(raw_path).query)
        try: since = int((q.get("since") or ["0"])[0])
        except ValueError: since = 0
        evs, total = events_since(since)
        handler._json({"active": RUN["active"], "task": RUN["task"], "events": evs, "total": total,
                       "speed": SPEED})
        return True

    if method != "POST" or not path.startswith("/hands"):
        return False

    if path == "/hands_request":
        task = (p.get("task") or "").strip()
        if not task:
            handler._json({"error": "what should I do, sir?"}, 400); return True
        if RUN["active"]:
            handler._json({"error": "I'm already at the wheel, sir — say stop first."}, 409); return True
        cid = os.urandom(5).hex()
        PENDING.clear(); PENDING[cid] = task
        danger = any(d in task.lower() for d in DANGER)
        # NEVER parrot the task back into the ask — he heard his own sentence read to him
        # ("it's repeating the same thing to me", 2026-08-11); the card shows the task, the
        # voice keeps it short
        handler._json({"confirm_id": cid, "task": task, "danger": danger,
                       "ask": "May I take the wheel, sir?" + (" I'll fill things in but stop "
                              "before anything final." if danger else "")})
        return True

    if path == "/hands_go":
        cid = (p.get("confirm_id") or "").strip()
        task = PENDING.pop(cid, None) or (p.get("task") or "").strip()
        if not task:
            handler._json({"error": "nothing to do, sir"}, 400); return True
        if RUN["active"]:
            handler._json({"error": "already driving, sir"}, 409); return True
        RUN.update({"active": True, "stop": False, "task": task, "started": time.time()})
        with EV_LOCK: EVENTS.clear()
        threading.Thread(target=run, args=(task, p.get("session")), daemon=True).start()
        handler._json({"started": True, "task": task}); return True

    if path == "/hands_stop":
        RUN["stop"] = True
        PENDING.clear()
        handler._json({"stopping": True}); return True

    if path == "/hands_speed":
        tier = (p.get("tier") or "").strip()
        cur = set_speed(tier)
        if CTX.get("persist_speed"):
            try: CTX["persist_speed"](cur)
            except Exception: pass
        handler._json({"speed": cur, "model": COMPUTER_MODEL})
        return True

    return False

def init(ctx):
    CTX.update(ctx or {})
    if CTX.get("speed"):
        set_speed(CTX["speed"])                            # config takeover.speed → tier at boot
    print(f"[hands] takeover bay online — {SPEED} tier ({COMPUTER_MODEL}, {TOOL_TYPE}) "
          "(needs Screen Recording + Accessibility grants)")
