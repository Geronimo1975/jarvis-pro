#!/usr/bin/env python3
"""Jarvis PRESENCE — the HUD reactor, floating on the REAL desktop as a black CIRCLE.

A faithful desktop port of the in-app J.A.R.V.I.S. reactor (viewer/#j-orb): blue segmented
rings, an amber accent arc, a rotating scanner, a teal core, "J.A.R.V.I.S." lettering, and a
state label — all painted on a black disc so it reads clearly over anything you screen-share.
Borderless, transparent, all-Spaces, layer 999 — and DRAGGABLE (TARS parity): grab the disc
and park it anywhere; the position is remembered across sessions (jarvis-presence.json). A
plain click makes the core pulse once. Clicks land only on the disc — the transparent corners
of the window stay inert. Driven over UDP 127.0.0.1:4732:

    show · hide · state:idle|listening|speaking|working · level:<0..1> · quit

States (color + label): idle=blue "ONLINE" · listening=cyan "LISTENING" ·
speaking=teal "SPEAKING" (core pulses with voice level) · working=amber "DRIVING".
Needs pyobjc. Spawned as a direct child of the server (which runs in the GUI session).
"""
import json, math, os, socket, sys, threading, time

import objc
from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory, NSBackingStoreBuffered,
                    NSBezierPath, NSColor, NSEvent, NSFont, NSFontAttributeName, NSForegroundColorAttributeName,
                    NSGradient, NSGraphicsContext, NSKernAttributeName, NSMakeRect, NSScreen, NSView,
                    NSWindow, NSWindowCollectionBehaviorMoveToActiveSpace, NSWindowStyleMaskBorderless)
from Foundation import NSObject, NSString, NSTimer, NSMakePoint, NSAffineTransform

POS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis-presence.json")

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
    """True if a window at (x, y) would be at least partly visible on ANY display."""
    for s in NSScreen.screens():
        f = s.frame()
        if (x + SIZE > f.origin.x + 20 and x < f.origin.x + f.size.width - 20 and
                y + SIZE > f.origin.y + 20 and y < f.origin.y + f.size.height - 20):
            return True
    return False

PORT = 4732
SIZE = 224                       # window is square + transparent; we only paint a CIRCLE inside it
CX = CY = SIZE / 2.0
DISC = 104.0                     # black-circle radius
CORE_OUT = (0.031, 0.157, 0.145)
CORE_IN = (0.055, 0.255, 0.235)
WHITE = (0.925, 1.0, 0.984)
# per-state: hud (main), hud2 (secondary), accent, label
PAL = {
    "idle":      ((0.384, 0.859, 1.0), (0.184, 0.624, 0.816), (0.957, 0.663, 0.227), "ONLINE"),
    "listening": ((0.475, 0.941, 1.0), (0.184, 0.624, 0.816), (0.957, 0.663, 0.227), "LISTENING"),
    "speaking":  ((0.490, 1.0, 0.851), (0.184, 0.624, 0.816), (0.957, 0.663, 0.227), "SPEAKING"),
    "working":   ((0.612, 0.800, 0.867), (0.184, 0.624, 0.816), (1.0, 0.816, 0.416), "DRIVING"),
}
ST = {"state": "idle", "level": 0.0, "visible": False, "t0": time.time()}


def _c(rgb, a=1.0):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(rgb[0], rgb[1], rgb[2], a)

def _oval(cx, cy, r):
    return NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(cx - r, cy - r, r * 2, r * 2))

def _rot(deg):
    """Push a rotation about the reactor center; returns the transform for concat()."""
    t = NSAffineTransform.transform()
    t.translateXBy_yBy_(CX, CY)
    t.rotateByDegrees_(deg)
    t.translateXBy_yBy_(-CX, -CY)
    return t

def _ring(cx, cy, r, width, color, alpha, dash=None):
    p = _oval(cx, cy, r)
    p.setLineWidth_(width)
    if dash:
        p.setLineDash_count_phase_(dash, len(dash), 0.0)
    _c(color, alpha).setStroke()
    p.stroke()

def _spin(deg, fn):
    ctx = NSGraphicsContext.currentContext(); ctx.saveGraphicsState()
    _rot(deg).concat(); fn(); ctx.restoreGraphicsState()


class OrbView(NSView):
    def acceptsFirstMouse_(self, event):
        return True                                    # first click grabs, even when unfocused

    def mouseDown_(self, event):
        p = event.locationInWindow()
        if math.hypot(p.x - CX, p.y - CY) > DISC + 8:  # the transparent corners stay inert
            self._grab = None
            return
        m = NSEvent.mouseLocation()
        f = self.window().frame()
        self._grab = (m.x - f.origin.x, m.y - f.origin.y)
        self._moved = False

    def mouseDragged_(self, event):
        g = getattr(self, "_grab", None)
        if not g:
            return
        m = NSEvent.mouseLocation()
        self._moved = True
        self.window().setFrameOrigin_(NSMakePoint(m.x - g[0], m.y - g[1]))

    def mouseUp_(self, event):
        g = getattr(self, "_grab", None)
        self._grab = None
        if not g:
            return
        if getattr(self, "_moved", False):             # a drag: remember where he parked it
            f = self.window().frame()
            _save_pos(f.origin.x, f.origin.y)
        else:                                          # a plain click: the core answers with a pulse
            ST["pulse_until"] = time.time() + 0.8

    def drawRect_(self, rect):
        el = time.time() - ST["t0"]
        hud, hud2, accent, _label = PAL.get(ST["state"], PAL["idle"])
        lvl = ST["level"] if ST["state"] == "speaking" else 0.0
        if ST["state"] == "speaking":
            # nobody streams live voice levels to the desktop orb — while speaking, breathe on
            # our own (double-sine ≈ organic cadence) so the core visibly GLOWS with the voice
            # instead of sitting static (2026-08-11 ask)
            synth = 0.46 + 0.26 * math.sin(el * 5.6) + 0.12 * math.sin(el * 13.7)
            lvl = max(lvl, max(0.0, min(1.0, synth)))
        pu = ST.get("pulse_until", 0.0)
        if pu > time.time():
            lvl = max(lvl, (pu - time.time()) / 0.8)

        # --- black disc (this is what makes it a CIRCLE, not a square) ---
        _c((0.02, 0.03, 0.04), 0.93).setFill(); _oval(CX, CY, DISC).fill()
        _ring(CX, CY, DISC - 2, 1.0, hud, 0.16)                       # faint rim to define the edge

        # --- outer tick ring (slow CCW) ---
        def ticks():
            _c(hud, 0.85).setStroke()
            for i in range(56):
                ang = math.radians(i * (360 / 56))
                ca, sa = math.cos(ang), math.sin(ang)
                p = NSBezierPath.bezierPath()
                p.moveToPoint_(NSMakePoint(CX + 74 * ca, CY + 74 * sa))
                p.lineToPoint_(NSMakePoint(CX + 82 * ca, CY + 82 * sa))
                p.setLineWidth_(1.0); p.stroke()
        _spin(-el * 5, ticks)

        # --- segmented main ring (CW) ---
        _spin(el * 14, lambda: _ring(CX, CY, 69, 3.0, hud, 0.95, dash=[36.0, 24.0]))
        _ring(CX, CY, 63, 1.0, hud2, 0.45)                            # static thin ring

        # --- amber accent arc (CW) ---
        def accent_arc():
            a0 = 46
            p = NSBezierPath.bezierPath()
            p.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
                NSMakePoint(CX, CY), 56, a0, a0 + 116)
            p.setLineWidth_(3.4); _c(accent, 0.95).setStroke(); p.stroke()
        _spin(el * 22, accent_arc)

        # --- dotted ring (CCW) + inner thin ring ---
        _spin(-el * 18, lambda: _ring(CX, CY, 45, 1.4, hud, 0.7, dash=[1.6, 6.0]))
        _ring(CX, CY, 33, 1.0, hud2, 0.4)

        # --- scanner sweep (fast CW) ---
        def radar():
            p = NSBezierPath.bezierPath()
            p.moveToPoint_(NSMakePoint(CX, CY)); p.lineToPoint_(NSMakePoint(CX, CY + 41))
            p.setLineWidth_(1.6); _c(hud, 0.55).setStroke(); p.stroke()
        _spin(el * 60, radar)

        # --- accent dots (slow CW) ---
        def dots():
            _c(accent, 0.85).setFill()
            for a in (18, 74, 205, 322):
                ar = math.radians(a)
                _oval(CX + 59 * math.cos(ar), CY + 59 * math.sin(ar), 2.0).fill()
        _spin(el * 5, dots)

        # --- teal core (radial), glowing with voice level when speaking ---
        glow_r = 30 + 10 * lvl
        _c(hud, 0.05 + 0.20 * lvl).setFill(); _oval(CX, CY, glow_r + 9).fill()   # soft outer halo
        _c(hud, 0.06 + 0.5 * lvl).setFill(); _oval(CX, CY, glow_r).fill()
        core = _oval(CX, CY, 27)
        NSGradient.alloc().initWithStartingColor_endingColor_(_c(CORE_IN), _c(CORE_OUT)) \
            .drawInBezierPath_relativeCenterPosition_(core, NSMakePoint(0.0, 0.12))
        _c(hud, 0.35 + 0.5 * lvl).setStroke(); core.setLineWidth_(1.2); core.stroke()

        # --- J.A.R.V.I.S. lettering (center) ---
        font = NSFont.fontWithName_size_("Menlo-Bold", 11.5) or NSFont.boldSystemFontOfSize_(11.5)
        attrs = {NSFontAttributeName: font, NSForegroundColorAttributeName: _c(WHITE, 0.96),
                 NSKernAttributeName: 1.2}
        s = NSString.stringWithString_("J.A.R.V.I.S.")
        tw = s.sizeWithAttributes_(attrs).width
        s.drawAtPoint_withAttributes_((CX - tw / 2.0, CY - 6.5), attrs)

        # --- state label, in the black band below the reactor (● ONLINE / ● DRIVING) ---
        lfont = NSFont.fontWithName_size_("Menlo-Bold", 9) or NSFont.boldSystemFontOfSize_(9)
        lattrs = {NSFontAttributeName: lfont, NSForegroundColorAttributeName: _c(hud, 0.85),
                  NSKernAttributeName: 2.0}
        ls = NSString.stringWithString_("● " + _label)
        lw = ls.sizeWithAttributes_(lattrs).width
        ls.drawAtPoint_withAttributes_((CX - lw / 2.0, CY - 92), lattrs)


class Driver(NSObject):
    def initWithView_window_(self, view, window):
        self = objc.super(Driver, self).init()
        self.view = view; self.window = window
        return self

    def tick_(self, timer):
        if ST["visible"]:
            self.view.setNeedsDisplay_(True)

    def apply_(self, timer):
        if ST.get("_dirty"):
            ST["_dirty"] = False
            if ST["visible"]:
                # re-materialize on the CURRENT desktop each time it's shown (a share may start on
                # a different Space than last time) — orderOut then front forces active-Space placement
                self.window.orderOut_(None)
                self.window.orderFrontRegardless()
            elif self.window.isVisible():
                self.window.orderOut_(None)


def udp_listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", PORT))
    except OSError:
        return
    while True:
        try:
            data, _ = s.recvfrom(256)
        except OSError:
            break
        msg = data.decode(errors="ignore").strip()
        if msg == "quit":
            NSApplication.sharedApplication().terminate_(None); return
        elif msg == "show":
            ST["visible"] = True; ST["_dirty"] = True; ST["t0"] = time.time()
        elif msg == "hide":
            ST["visible"] = False; ST["_dirty"] = True
        elif msg.startswith("state:"):
            v = msg.split(":", 1)[1]
            if v in PAL: ST["state"] = v
        elif msg.startswith("level:"):
            try: ST["level"] = max(0.0, min(1.0, float(msg.split(":", 1)[1])))
            except ValueError: pass


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    screen = NSScreen.mainScreen().frame()
    x = screen.size.width - SIZE - 20
    y = (screen.size.height - SIZE) / 2.0
    saved = _load_pos()                                # he parked it somewhere last time — honor that
    if saved and _on_some_screen(*saved):
        x, y = saved
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(x, y, SIZE, SIZE), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setHasShadow_(False)                           # a HUD disc casts no window shadow
    win.setLevel_(999)
    win.setIgnoresMouseEvents_(False)                  # the disc is grabbable — corners stay pass-through
    # MoveToActiveSpace (NOT CanJoinAllSpaces): the orb lives on ONE desktop at a time — the one
    # you're on when it's shown — instead of being painted across every Space. So it rides the
    # screen you're actually sharing and doesn't follow you everywhere.
    win.setCollectionBehavior_(NSWindowCollectionBehaviorMoveToActiveSpace)
    view = OrbView.alloc().initWithFrame_(NSMakeRect(0, 0, SIZE, SIZE))
    win.setContentView_(view)

    driver = Driver.alloc().initWithView_window_(view, win)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        1 / 24.0, driver, "tick:", None, True)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.1, driver, "apply:", None, True)

    if "--show" in sys.argv:
        ST["visible"] = True; ST["_dirty"] = True; win.orderFrontRegardless()
    threading.Thread(target=udp_listener, daemon=True).start()
    app.run()


if __name__ == "__main__":
    main()
