#!/usr/bin/env python3
"""Jarvis FACEWIN — the living face, pinned to the REAL desktop while SCREEN WATCH is on.

His spec (2026-08-29): "when I click on watch, Jarvis should be on the top right-hand
corner of the screen I'm sharing — he should never get away — so I know Jarvis is always
watching me." A small HUD card: the animated holographic face (jarvis-face.gif, NSImageView
animates GIFs natively — no AVFoundation needed on the system python) over a black rounded
card with a cyan border and a "● WATCHING" band. Falls back to the still PNG if the gif is
missing (member zips ship fine without assets — the card just doesn't animate).

Shell cloned from presence.py (the proven pattern): borderless, transparent, layer 999.
PINNED (his spec, round 2): "all the way top right, at all times" — every `show` snaps it
flush to the top-right corner of the main screen (over the menu bar; layer 999 outranks it),
CanJoinAllSpaces + FullScreenAuxiliary so it follows across every desktop and full-screen
app, and a gentle re-front every few seconds keeps it above late-coming windows. Dragging
still works as a temporary nudge, but the next show snaps it home (nothing persisted).
Driven over UDP 127.0.0.1:4733:  show · hide · quit · timer|MM:SS|state
FOCUS SESSIONS (Session 19): "timer|24:31|focus" paints a countdown line beneath the face
(state focus=cyan · drift=amber · pause=dim; "timer|" clears it). The message carries ONLY
a clock string and a state word — no app identity ever reaches this process.
Needs pyobjc. Spawned as a direct child of the server (which runs in the GUI session).
"""
import json, math, os, socket, sys, threading, time, urllib.request

import objc
from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory, NSBackingStoreBuffered,
                    NSBezierPath, NSColor, NSEvent, NSFont, NSFontAttributeName,
                    NSForegroundColorAttributeName, NSImage, NSImageScaleProportionallyUpOrDown,
                    NSImageView, NSKernAttributeName, NSMakeRect, NSScreen, NSView, NSWindow,
                    NSWindowCollectionBehaviorCanJoinAllSpaces,
                    NSWindowCollectionBehaviorFullScreenAuxiliary, NSWindowStyleMaskBorderless)
from Foundation import NSObject, NSString, NSTimer, NSMakePoint

ROOT = os.path.dirname(os.path.abspath(__file__))
POS_FILE = os.path.join(ROOT, "jarvis-facewin.json")
GIF = os.path.join(ROOT, "viewer", "jarvis-face.gif")
PNG = os.path.join(ROOT, "viewer", "jarvis-face.png")

PORT = 4733
W, H = 172, 246                  # card window (transparent margins stay inert-looking but drag fine)
CARD_R = 16.0
HUD = (0.251, 0.878, 1.0)        # house cyan
AMBER = (1.0, 0.72, 0.25)        # drift
DIM = (0.55, 0.62, 0.66)         # paused
ST = {"visible": False, "t0": time.time(), "timer": None}
IV = [None]                      # the face image view — the timer squeezes its frame a touch
# S19b: the card is a CONTROL SURFACE while a session runs — pause/resume + abort land right
# on the desktop (his "there's no way for me to select it"). View coords, bottom-left origin.
BTN_TOGGLE = (10, 21, 27, 26)
BTN_STOP = (135, 21, 27, 26)
# S19x: "give me a button I can physically click" — a full-width pill above the countdown:
# ⌖ LOCK THIS TAB → POST /focus/retarget {"via":"card"} (the server reads the browser's front
# window directly, so it works even if this click made the card frontmost). Flashes LOCKED.
BTN_LOCK = (10, 48, W - 20, 20)
BTNS = {"toggle": BTN_TOGGLE, "stop": BTN_STOP, "lock": BTN_LOCK}
FLASH_S = 1.6

def _in(rect, x, y):
    return rect[0] <= x <= rect[0] + rect[2] and rect[1] <= y <= rect[1] + rect[3]

def _post_focus(path, body=b"{}"):
    """Fire a focus-bay action at the desk server. Background thread — the UI never blocks."""
    def go():
        try:
            req = urllib.request.Request("http://127.0.0.1:4719" + path, data=body,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=4).read()
        except Exception:
            pass
    threading.Thread(target=go, daemon=True).start()


def _load_pos():
    try:
        d = json.load(open(POS_FILE))
        return float(d["x"]), float(d["y"])
    except Exception:
        return None

def _save_pos(x, y):
    try:
        tmp = POS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"x": x, "y": y}, f)
        os.replace(tmp, POS_FILE)
    except Exception:
        pass

def _on_some_screen(x, y):
    for s in NSScreen.screens():
        f = s.frame()
        if (x + W > f.origin.x + 20 and x < f.origin.x + f.size.width - 20 and
                y + H > f.origin.y + 20 and y < f.origin.y + f.size.height - 20):
            return True
    return False

def _c(rgb, a=1.0):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(rgb[0], rgb[1], rgb[2], a)


class CardView(NSView):
    def acceptsFirstMouse_(self, event):
        return True

    def mouseDown_(self, event):
        self._btn = None
        self._grab = None
        if ST.get("timer"):
            p = self.convertPoint_fromView_(event.locationInWindow(), None)
            if _in(BTN_TOGGLE, p.x, p.y): self._btn = "toggle"; return
            if _in(BTN_STOP, p.x, p.y): self._btn = "stop"; return
            if _in(BTN_LOCK, p.x, p.y): self._btn = "lock"; return
        m = NSEvent.mouseLocation()
        f = self.window().frame()
        self._grab = (m.x - f.origin.x, m.y - f.origin.y)

    def mouseDragged_(self, event):
        g = getattr(self, "_grab", None)
        if not g:
            return
        m = NSEvent.mouseLocation()
        self.window().setFrameOrigin_(NSMakePoint(m.x - g[0], m.y - g[1]))

    def mouseUp_(self, event):
        b = getattr(self, "_btn", None)
        if b:
            self._btn = None
            p = self.convertPoint_fromView_(event.locationInWindow(), None)
            tm = ST.get("timer")
            if tm and _in(BTNS[b], p.x, p.y):
                if b == "stop":
                    _post_focus("/focus/stop")
                elif b == "lock":
                    ST["flash"] = time.time()
                    _post_focus("/focus/retarget", b'{"via":"card"}')
                else:
                    _post_focus("/focus/resume" if tm["state"] == "pause" else "/focus/pause")
            return
        if getattr(self, "_grab", None):
            f = self.window().frame()
            _save_pos(f.origin.x, f.origin.y)

    def drawRect_(self, rect):
        el = time.time() - ST["t0"]
        breathe = 0.55 + 0.25 * math.sin(el * 1.6)     # slow border breathing
        card = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(4, 4, W - 8, H - 8), CARD_R, CARD_R)
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.008, 0.024, 0.031, 0.94).setFill()
        card.fill()
        tm = ST.get("timer")
        rim = HUD if not tm else {"focus": HUD, "drift": AMBER, "pause": DIM}.get(tm["state"], HUD)
        _c(rim, breathe).setStroke()
        card.setLineWidth_(1.6)
        card.stroke()
        if tm:
            # FOCUS SESSION: the countdown line beneath the face + a state band
            col = {"focus": HUD, "drift": AMBER, "pause": DIM}.get(tm["state"], HUD)
            fontT = NSFont.fontWithName_size_("Menlo-Bold", 19) or NSFont.boldSystemFontOfSize_(19)
            attrsT = {NSFontAttributeName: fontT, NSForegroundColorAttributeName: _c(col, 0.96),
                      NSKernAttributeName: 1.4}
            sT = NSString.stringWithString_(tm["txt"])
            twT = sT.sizeWithAttributes_(attrsT).width
            sT.drawAtPoint_withAttributes_((W / 2.0 - twT / 2.0, 24), attrsT)
            # the control surface: ❚❚/▶ toggle + ✕ abort, flanking the countdown
            fontB = NSFont.fontWithName_size_("Menlo-Bold", 11) or NSFont.boldSystemFontOfSize_(11)
            for rect, glyph in ((BTN_TOGGLE, "▶" if tm["state"] == "pause" else "❚❚"), (BTN_STOP, "✕")):
                bp = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    NSMakeRect(rect[0], rect[1], rect[2], rect[3]), 7.0, 7.0)
                _c(col, 0.10).setFill(); bp.fill()
                _c(col, 0.55).setStroke(); bp.setLineWidth_(1.0); bp.stroke()
                attrsB = {NSFontAttributeName: fontB, NSForegroundColorAttributeName: _c(col, 0.9)}
                sB = NSString.stringWithString_(glyph)
                sz = sB.sizeWithAttributes_(attrsB)
                sB.drawAtPoint_withAttributes_((rect[0] + rect[2] / 2.0 - sz.width / 2.0,
                                                rect[1] + rect[3] / 2.0 - sz.height / 2.0), attrsB)
            # S19x: the LOCK pill — the one control he asked for by name
            flashing = (time.time() - ST.get("flash", 0.0)) < FLASH_S
            lp = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(BTN_LOCK[0], BTN_LOCK[1], BTN_LOCK[2], BTN_LOCK[3]), 7.0, 7.0)
            _c(col, 0.22 if flashing else 0.10).setFill(); lp.fill()
            _c(col, 0.9 if flashing else 0.55).setStroke(); lp.setLineWidth_(1.0); lp.stroke()
            fontL = NSFont.fontWithName_size_("Menlo-Bold", 9) or NSFont.boldSystemFontOfSize_(9)
            attrsL = {NSFontAttributeName: fontL, NSForegroundColorAttributeName: _c(col, 0.95),
                      NSKernAttributeName: 1.6}
            sL = NSString.stringWithString_("LOCKED ✓" if flashing else "⌖ LOCK THIS TAB")
            szL = sL.sizeWithAttributes_(attrsL)
            sL.drawAtPoint_withAttributes_((BTN_LOCK[0] + BTN_LOCK[2] / 2.0 - szL.width / 2.0,
                                            BTN_LOCK[1] + BTN_LOCK[3] / 2.0 - szL.height / 2.0), attrsL)
            band = {"focus": "● FOCUS", "drift": "● DRIFT", "pause": "❚❚ PAUSED"}.get(tm["state"], "● FOCUS")
        else:
            col = HUD
            band = "● WATCHING"
        font = NSFont.fontWithName_size_("Menlo-Bold", 9) or NSFont.boldSystemFontOfSize_(9)
        attrs = {NSFontAttributeName: font, NSForegroundColorAttributeName: _c(col, 0.92),
                 NSKernAttributeName: 2.4}
        s = NSString.stringWithString_(band)
        tw = s.sizeWithAttributes_(attrs).width
        s.drawAtPoint_withAttributes_((W / 2.0 - tw / 2.0, 11 if not tm else 9), attrs)


def _pin_top_right(win):
    """Flush top-right of the main screen's FULL frame — over the menu bar; that's the spec."""
    f = NSScreen.mainScreen().frame()
    win.setFrameOrigin_(NSMakePoint(f.origin.x + f.size.width - W - 8,
                                    f.origin.y + f.size.height - H - 8))


class Driver(NSObject):
    def initWithView_window_(self, view, window):
        self = objc.super(Driver, self).init()
        self.view = view; self.window = window
        self._front_t = 0.0
        return self

    def tick_(self, timer):
        if ST["visible"]:
            # timer active → the face lifts to make room for the countdown (main-thread only)
            want = ST.get("timer") is not None
            if IV[0] is not None and want != getattr(self, "_squeezed", False):
                self._squeezed = want
                IV[0].setFrame_(NSMakeRect(10, 74 if want else 30, W - 20, (H - 88) if want else (H - 44)))
            self.view.setNeedsDisplay_(True)
            now = time.time()
            if now - self._front_t > 4.0:              # never gets away: gentle periodic re-front
                self._front_t = now
                self.window.orderFrontRegardless()

    def apply_(self, timer):
        if ST.get("_dirty"):
            ST["_dirty"] = False
            if ST["visible"]:
                _pin_top_right(self.window)            # every show snaps home to the corner
                self.window.orderOut_(None)
                self.window.orderFrontRegardless()
            elif self.window.isVisible():
                self.window.orderOut_(None)


def udp_listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", PORT))
    except OSError:
        # an overlay that can't hear commands is a zombie squatting on the next spawn — die now
        # (Session 19 field find: an orphan holding 4733 made every timer message vanish)
        os._exit(0)
    while True:
        try:
            data, _ = s.recvfrom(128)
        except OSError:
            break
        msg = data.decode(errors="ignore").strip()
        if msg == "quit":
            # terminate_ from a non-main thread is unreliable (the S19 orphan) — exit hard
            os._exit(0)
        elif msg == "show":
            ST["visible"] = True; ST["_dirty"] = True; ST["t0"] = time.time()
        elif msg == "hide":
            ST["visible"] = False; ST["_dirty"] = True
        elif msg.startswith("timer|"):
            # "timer|MM:SS|state" paints the countdown; "timer|" clears it. A clock string and
            # a state word — nothing else ever rides this message.
            parts = msg.split("|")
            if len(parts) < 2 or not parts[1]:
                ST["timer"] = None
            else:
                ST["timer"] = {"txt": parts[1][:8],
                               "state": (parts[2] if len(parts) > 2 else "focus")[:8]}


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    f = NSScreen.mainScreen().frame()
    x = f.origin.x + f.size.width - W - 8              # flush top-right, over the menu bar
    y = f.origin.y + f.size.height - H - 8
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(x, y, W, H), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setHasShadow_(False)
    win.setLevel_(999)
    win.setIgnoresMouseEvents_(False)                  # draggable — park him where you like
    win.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces |
                               NSWindowCollectionBehaviorFullScreenAuxiliary)   # every Space, every full-screen
    view = CardView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
    win.setContentView_(view)

    # the face: animated gif if present (NSImageView animates it), else the still png
    src = GIF if os.path.exists(GIF) else PNG
    if os.path.exists(src):
        img = NSImage.alloc().initWithContentsOfFile_(src)
        if img:
            iv = NSImageView.alloc().initWithFrame_(NSMakeRect(10, 30, W - 20, H - 44))
            iv.setImage_(img)
            iv.setImageScaling_(NSImageScaleProportionallyUpOrDown)
            iv.setAnimates_(True)                      # this line IS the "living" part
            iv.setWantsLayer_(True)
            try:
                iv.layer().setCornerRadius_(11.0)
                iv.layer().setMasksToBounds_(True)
            except Exception:
                pass
            view.addSubview_(iv)
            IV[0] = iv

    driver = Driver.alloc().initWithView_window_(view, win)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        1 / 12.0, driver, "tick:", None, True)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.1, driver, "apply:", None, True)

    if "--show" in sys.argv:
        ST["visible"] = True; ST["_dirty"] = True; win.orderFrontRegardless()
    threading.Thread(target=udp_listener, daemon=True).start()
    app.run()


if __name__ == "__main__":
    main()
