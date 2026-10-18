#!/usr/bin/env python3
"""Jarvis guide-mode overlay — draws a poking precision ARROW + label on the REAL desktop.

Usage: python3 overlay.py <x_pct 0-100> <y_pct 0-100> [label]
The window is transparent, always-on-top, click-THROUGH (ignores mouse), and exits by
itself after ~10 seconds. Needs pyobjc (pip3 install --user pyobjc-framework-Cocoa).

The arrow's tip lands on the EXACT target pixel (it pokes toward the point, kissing it
at the near end of each stroke) and the body always approaches from the roomiest
quadrant of the screen, so it can never run off an edge. Every stroke is drawn with a
black + white casing under the accent color so it reads on ANY background — white web
pages, dark apps, photos, video.
"""
import math
import sys
import time

import objc
from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory, NSBackingStoreBuffered,
                    NSBezierPath, NSColor, NSFont, NSFontAttributeName,
                    NSForegroundColorAttributeName, NSMakeRect, NSScreen, NSView, NSWindow,
                    NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowStyleMaskBorderless)
from Foundation import NSObject, NSString, NSTimer

LIFETIME = 10.0         # seconds on screen
ACCENT = (1.00, 0.23, 0.16)   # hot red-orange

# arrow geometry (px): head length / head half-width, neck depth (fraction of head
# length where the shaft meets it), shaft half-width / length, poke travel
HEAD_L, HEAD_W = 38.0, 19.0
NECK, SHAFT_W, SHAFT_L = 0.62, 7.0, 52.0
POKE = 14.0


class ArrowView(NSView):
    # plain Python attributes, set after init (a custom ObjC init taking an NSRect would
    # need an explicit type signature — this avoids the problem entirely)
    center = (0.0, 0.0)
    direction = (-0.7071, -0.7071)   # unit vector pointing TOWARD the target
    label = ""
    t0 = 0.0

    def drawRect_(self, rect):
        elapsed = time.time() - self.t0
        # slide the whole arrow along its axis; tip touches the exact point at bounce=0
        bounce = (1.0 - math.cos(elapsed * 3.2)) * 0.5 * POKE
        tx, ty = self.center
        ux, uy = self.direction
        px, py = -uy, ux                       # perpendicular to the axis
        r, g, b = ACCENT
        tipx, tipy = tx - ux * bounce, ty - uy * bounce

        def pt(du, dp):                        # local (behind tip, sideways) → screen
            return (tipx - ux * du + px * dp, tipy - uy * du + py * dp)

        tail = HEAD_L * NECK + SHAFT_L
        pts = [(tipx, tipy),
               pt(HEAD_L, HEAD_W),
               pt(HEAD_L * NECK, SHAFT_W),
               pt(tail, SHAFT_W),
               pt(tail, -SHAFT_W),
               pt(HEAD_L * NECK, -SHAFT_W),
               pt(HEAD_L, -HEAD_W)]
        path = NSBezierPath.bezierPath()
        path.moveToPoint_(pts[0])
        for p in pts[1:]:
            path.lineToPoint_(p)
        path.closePath()
        path.setLineJoinStyle_(1)              # round joins — no miter spikes off the tip
        # tri-tone casing: black halo, white ring, accent body
        for cr, cg, cb, ca, cw in ((0.0, 0.0, 0.0, 0.70, 10.0),
                                   (1.0, 1.0, 1.0, 0.95, 5.5)):
            NSColor.colorWithCalibratedRed_green_blue_alpha_(cr, cg, cb, ca).setStroke()
            path.setLineWidth_(cw)
            path.stroke()
        NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0).setFill()
        path.fill()

        if self.label:
            attrs = {
                NSFontAttributeName: NSFont.boldSystemFontOfSize_(16),
                NSForegroundColorAttributeName: NSColor.whiteColor(),
            }
            s = NSString.stringWithString_(self.label)
            size = s.sizeWithAttributes_(attrs)
            pad_x, pad_y = 12.0, 7.0
            bw, bh = size.width + pad_x * 2, size.height + pad_y * 2
            # hang the plate off the arrow's tail, clamped fully on-screen
            ax = tipx - ux * (tail + 36.0)
            ay = tipy - uy * (tail + 36.0)
            bx = min(max(ax - bw / 2.0, 8.0), self.bounds().size.width - bw - 8.0)
            by = min(max(ay - bh / 2.0, 8.0), self.bounds().size.height - bh - 8.0)
            plate = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(bx, by, bw, bh), bh / 2.0, bh / 2.0)
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.05, 0.05, 0.07, 0.88).setFill()
            plate.fill()
            NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 0.95).setStroke()
            plate.setLineWidth_(2.0)
            plate.stroke()
            s.drawAtPoint_withAttributes_((bx + pad_x, by + pad_y - 1), attrs)


class Driver(NSObject):
    view = None
    app = None

    def tick_(self, timer):
        if time.time() - self.view.t0 > LIFETIME:
            self.app.terminate_(None)
        self.view.setNeedsDisplay_(True)


def main():
    x_pct = float(sys.argv[1]) if len(sys.argv) > 1 else 50.0
    y_pct = float(sys.argv[2]) if len(sys.argv) > 2 else 50.0
    label = sys.argv[3] if len(sys.argv) > 3 else ""

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    screen = NSScreen.mainScreen().frame()
    w, h = screen.size.width, screen.size.height
    # incoming y is % from the TOP of the screen; AppKit's origin is bottom-left
    cx, cy = w * x_pct / 100.0, h * (1.0 - y_pct / 100.0)

    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, w, h), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setOpaque_(False)
    win.setLevel_(1000)                      # NSScreenSaverWindowLevel — above everything
    win.setIgnoresMouseEvents_(True)         # clicks pass straight through to the target
    win.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces)

    view = ArrowView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    view.center = (cx, cy)
    # approach from the roomiest quadrant: the unit vector points TOWARD the target,
    # so the body extends away from it into open screen
    sx = -1.0 if cx < w / 2.0 else 1.0
    sy = -1.0 if cy < h / 2.0 else 1.0
    k = 1.0 / math.sqrt(2.0)
    view.direction = (sx * k, sy * k)
    view.label = label
    view.t0 = time.time()
    win.setContentView_(view)
    win.makeKeyAndOrderFront_(None)

    driver = Driver.alloc().init()
    driver.view, driver.app = view, app
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        1.0 / 30.0, driver, "tick:", None, True)
    app.run()


if __name__ == "__main__":
    main()
