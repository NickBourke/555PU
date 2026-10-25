"""
Block diagram and schematics for the 555-PU, drawn from cpu555.build().

Every logic sheet is generated from the same netlist the simulator tests, so
the drawings cannot drift from the design. Writes SVGs into docs/.

Usage:  python drawings.py      (also run at the end of python cpu555.py)
"""

import math
from html import escape

from cpu555 import BITS, PINS_556, ROOT, allocate, assemble, build

OUT = ROOT / "docs"

STYLE = """
.bg{fill:#fff}
.w{stroke:#111;stroke-width:1.2;fill:none;stroke-linecap:round}
.thin{stroke:#888;stroke-width:0.8;fill:none}
.bus{stroke:#111;stroke-width:2.2;fill:none}
.box{stroke:#111;stroke-width:1.6;fill:#fbfbf4}
.blk{stroke:#234;stroke-width:1.6;fill:#eaf1fb}
.blk2{stroke:#432;stroke-width:1.6;fill:#fbf1e6}
.blk3{stroke:#243;stroke-width:1.6;fill:#eaf7ec}
.solid{fill:#111;stroke:#111;stroke-width:1}
.open{fill:#fff;stroke:#999;stroke-width:1}
.arrow{stroke:#234;stroke-width:1.8;fill:none;marker-end:url(#ah)}
text{font-family:Consolas,Menlo,monospace;font-size:11px;fill:#111}
.lab{fill:#0b4fa8}
.pin{font-size:8.5px;fill:#666}
.val{font-size:9.5px;fill:#444}
.ttl{font-family:Helvetica,Arial,sans-serif;font-size:18px;font-weight:bold}
.sub{font-family:Helvetica,Arial,sans-serif;font-size:12px;fill:#444}
.bt{font-family:Helvetica,Arial,sans-serif;font-size:13px;font-weight:bold}
.bs{font-family:Helvetica,Arial,sans-serif;font-size:11px;fill:#333}
.un{font-weight:bold;font-size:12px}
"""


class Svg:
    def __init__(self):
        self.el, self.w, self.h, self.x0 = [], 0, 0, 1e9

    def _ext(self, x, y, xmin=None):
        self.w, self.h = max(self.w, x), max(self.h, y)
        self.x0 = min(self.x0, x if xmin is None else xmin)

    def line(self, x1, y1, x2, y2, cls="w"):
        self.el.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="{cls}"/>')
        self._ext(max(x1, x2), max(y1, y2), min(x1, x2))

    def path(self, pts, cls="w", closed=False):
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + (" Z" if closed else "")
        self.el.append(f'<path d="{d}" class="{cls}"/>')
        for x, y in pts:
            self._ext(x, y)

    def rect(self, x, y, w, h, cls="box", rx=0):
        self.el.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" class="{cls}"/>')
        self._ext(x + w, y + h, x)

    def text(self, x, y, s, cls="", anchor="start"):
        c = f' class="{cls}"' if cls else ""
        self.el.append(f'<text x="{x:.1f}" y="{y:.1f}"{c} text-anchor="{anchor}">{escape(str(s))}</text>')
        n = len(str(s)) * 6.5
        lo = {"start": x, "middle": x - n / 2, "end": x - n}[anchor]
        self._ext(lo + n, y + 4, lo)

    def dot(self, x, y):
        self.el.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" class="solid"/>')

    def circle(self, x, y, r, cls="open"):
        self.el.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" class="{cls}"/>')

    def place(self, other, dx, dy):
        self.el.append(f'<g transform="translate({dx:.1f},{dy:.1f})">')
        self.el.extend(other.el)
        self.el.append("</g>")
        self._ext(dx + other.w, dy + other.h, dx + min(other.x0, other.w))

    def save(self, name, title, subtitle="", margin=24):
        body = Svg()
        body.text(margin, margin + 14, title, "ttl")
        if subtitle:
            for k, s in enumerate(subtitle.split("\n")):
                body.text(margin, margin + 34 + 16 * k, s, "sub")
        top = margin + 30 + 16 * (subtitle.count("\n") + 1) + 14
        body.place(self, margin - min(self.x0, 0), top)
        W, H = body.w + margin, body.h + margin
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
               f'viewBox="0 0 {W:.0f} {H:.0f}">\n<style>{STYLE}</style>\n'
               '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
               'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
               'fill="#234"/></marker></defs>\n'
               f'<rect width="100%" height="100%" class="bg"/>\n' + "\n".join(body.el) + "\n</svg>\n")
        OUT.mkdir(exist_ok=True)
        (OUT / name).write_text(svg, encoding="utf-8")


# ---------------------------------------------------------------- symbols

def diode(s, x, y, to_right):
    """Horizontal diode from x to x+24. to_right: cathode on the right."""
    s.line(x, y, x + 8, y)
    s.line(x + 16, y, x + 24, y)
    if to_right:
        s.path([(x + 8, y - 5), (x + 8, y + 5), (x + 16, y)], "solid", True)
        s.line(x + 16, y - 5, x + 16, y + 5)
    else:
        s.path([(x + 16, y - 5), (x + 16, y + 5), (x + 8, y)], "solid", True)
        s.line(x + 8, y - 5, x + 8, y + 5)


def diode_v(s, x, y, down):
    """Vertical diode from y to y+24. down: cathode at the bottom."""
    s.line(x, y, x, y + 8)
    s.line(x, y + 16, x, y + 24)
    if down:
        s.path([(x - 5, y + 8), (x + 5, y + 8), (x, y + 16)], "solid", True)
        s.line(x - 5, y + 16, x + 5, y + 16)
    else:
        s.path([(x - 5, y + 16), (x + 5, y + 16), (x, y + 8)], "solid", True)
        s.line(x - 5, y + 8, x + 5, y + 8)


def diode_diag(s, x0, y0, x1, y1):
    """Small diode between two points, anode at (x0, y0)."""
    L = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    px, py = -uy, ux
    a = (x0 + ux * (L / 2 - 3.5), y0 + uy * (L / 2 - 3.5))
    c = (x0 + ux * (L / 2 + 3.5), y0 + uy * (L / 2 + 3.5))
    s.line(x0, y0, a[0], a[1])
    s.line(c[0], c[1], x1, y1)
    s.path([(a[0] + px * 4, a[1] + py * 4), (a[0] - px * 4, a[1] - py * 4), c], "solid", True)
    s.line(c[0] + px * 4, c[1] + py * 4, c[0] - px * 4, c[1] - py * 4)


def res_v(s, x, y1, y2, label="", left=False):
    m = (y1 + y2) / 2
    s.line(x, y1, x, m - 9)
    s.rect(x - 4, m - 9, 8, 18, "box")
    s.line(x, m + 9, x, y2)
    if label:
        s.text(x - 8 if left else x + 8, m + 4, label, "val", "end" if left else "start")


def res_h(s, x1, x2, y, label=""):
    m = (x1 + x2) / 2
    s.line(x1, y, m - 9, y)
    s.rect(m - 9, y - 4, 18, 8, "box")
    s.line(m + 9, y, x2, y)
    if label:
        s.text(m, y - 8, label, "val", "middle")


def cap_v(s, x, y1, y2, label="", polar=False, left=False):
    m = (y1 + y2) / 2
    s.line(x, y1, x, m - 3)
    s.line(x - 8, m - 3, x + 8, m - 3)
    s.line(x - 8, m + 3, x + 8, m + 3)
    s.line(x, m + 3, x, y2)
    if polar:
        s.text(x + 10, m - 6, "+", "val")
    if label:
        s.text(x - 12 if left else x + 12, m + 4, label, "val", "end" if left else "start")


def gnd(s, x, y):
    s.line(x - 7, y, x + 7, y)
    s.line(x - 4.5, y + 3, x + 4.5, y + 3)
    s.line(x - 2, y + 6, x + 2, y + 6)


def vcc(s, x, y):
    s.line(x - 7, y, x + 7, y)
    s.text(x, y - 4, "VCC", "pin", "middle")


def label(s, x, y, name, anchor="end"):
    s.text(x, y + 4, name, "lab", anchor)


def chip(s, x, y, w, h, title, sub, pins):
    """A timer box. pins: list of (fn, side, offset, pin_no). Returns {fn: (x, y)}
    for the outer end of each 14px pin stub."""
    s.rect(x, y, w, h, "box", 3)
    s.text(x + w / 2, y + h / 2 - 4, title, "un", "middle")
    for k, line in enumerate(sub.split("\n") if sub else []):
        s.text(x + w / 2, y + h / 2 + 11 + 12 * k, line, "pin", "middle")
    ends = {}
    for fn, side, off, no in pins:
        if side == "L":
            px, py = x, y + off
            s.line(px - 14, py, px, py)
            s.text(px + 3, py + 3, fn, "pin")
            s.text(px - 3, py - 3, str(no), "pin", "end")
            ends[fn] = (px - 14, py)
        elif side == "R":
            px, py = x + w, y + off
            s.line(px, py, px + 14, py)
            s.text(px - 3, py + 3, fn, "pin", "end")
            s.text(px + 3, py - 3, str(no), "pin")
            ends[fn] = (px + 14, py)
        elif side == "T":
            px, py = x + off, y
            s.line(px, py - 14, px, py)
            s.text(px, py + 10, fn, "pin", "middle")
            s.text(px + 3, py - 5, str(no), "pin")
            ends[fn] = (px, py - 14)
        else:
            px, py = x + off, y + h
            s.line(px, py, px, py + 14)
            s.text(px, py - 4, fn, "pin", "middle")
            s.text(px + 3, py + 11, str(no), "pin")
            ends[fn] = (px, py + 14)
    return ends


# ---------------------------------------------------------------- networks

ROW = 15


def draw_node(s, terms, xr, y0, bus_label=None, force_or=False, pullup="100k"):
    """Draw a diode network whose output arrives at (xr, y). Returns (height, y)."""
    xb = xr - 40           # OR bus
    xd = xb - 34           # OR diode start
    xa = xd - 16           # AND node
    if len(terms) == 1 and len(terms[0]) == 1 and not bus_label:
        label(s, xr - 4, y0 + 8, terms[0][0])
        s.line(xr - 2, y0 + 8, xr, y0 + 8)
        return 16, y0 + 8
    if len(terms) == 1 and len(terms[0]) > 1 and not force_or and not bus_label:
        t = terms[0]
        vcc(s, xb, y0 + 10)
        res_v(s, xb, y0 + 10, y0 + 36, pullup)
        ys = [y0 + 44 + ROW * k for k in range(len(t))]
        s.line(xb, y0 + 36, xb, ys[-1])
        for yy, lit in zip(ys, t):
            diode(s, xb - 34, yy, False)
            s.line(xb - 10, yy, xb, yy)
            s.dot(xb, yy)
            label(s, xb - 38, yy, lit)
        yc = ys[-1]
        s.line(xb, yc, xr, yc)
        return yc - y0 + 10, yc
    y = y0
    taps = []
    if bus_label:
        s.line(xb, y + 8, xb - 70, y + 8)
        label(s, xb - 74, y + 8, bus_label)
        taps.append(y + 8)
        y += 22
    for t in terms:
        if len(t) == 1:
            ym = y + 9
            diode(s, xd, ym, True)
            s.line(xd + 24, ym, xb, ym)
            label(s, xd - 4, ym, t[0])
            taps.append(ym)
            y += 20
        else:
            vcc(s, xa, y + 10)
            res_v(s, xa, y + 10, y + 34, pullup, left=True)
            ys = [y + 42 + ROW * k for k in range(len(t))]
            s.line(xa, y + 34, xa, ys[-1])
            for yy, lit in zip(ys, t):
                diode(s, xa - 34, yy, False)
                s.line(xa - 10, yy, xa, yy)
                s.dot(xa, yy)
                label(s, xa - 38, yy, lit)
            ym = ys[(len(ys) - 1) // 2]
            diode(s, xd, ym, True)
            s.line(xa, ym, xd, ym)
            s.line(xd + 24, ym, xb, ym)
            taps.append(ym)
            y = ys[-1] + 14
    yc = y + 6
    top = taps[0] if taps else yc
    s.line(xb, top, xb, yc + 6, "bus")
    for t in taps:
        s.dot(xb, t)
    s.dot(xb, yc)
    s.line(xb, yc, xr, yc)
    res_v(s, xb, yc + 6, yc + 34, "1M")
    gnd(s, xb, yc + 34)
    return yc + 44 - y0, yc


XR = 230   # x where networks meet the timer pins


def timer_cell(c, unit):
    s = Svg()
    half = unit[-1]
    pn = PINS_556[half]
    force = c.group == "rom"
    bus = f"bit line {c.name[1:]}" if c.group == "rom" and c.name.startswith("n") else None
    if c.kind == "INV":
        h, yc = draw_node(s, c.trig, XR, 26, bus, force)
        bx, by, bh = XR + 14, yc - 34, 68
        s.line(XR, yc, XR + 6, yc)
        s.line(XR + 6, yc - 12, XR + 6, yc + 12)
        s.dot(XR + 6, yc)
        s.line(XR + 6, yc - 12, XR + 14, yc - 12)
        s.line(XR + 6, yc + 12, XR + 14, yc + 12)
        e = chip(s, bx + 14, by, 96, bh, unit, f"INV\n{c.name}",
                 [("TRIG", "L", 22, pn["TRIG"]), ("THR", "L", 46, pn["THR"]),
                  ("RST", "T", 48, pn["RST"]), ("OUT", "R", 34, pn["OUT"])])
    else:
        h1, y1 = draw_node(s, c.trig, XR, 26, None, force)
        h2, y2 = draw_node(s, c.thr, XR, 26 + h1 + 10, None, force)
        h = h1 + h2 + 10
        by = min(y1 - 30, 26)
        bh = max(y2 + 30 - by, 90)
        e = chip(s, XR + 14, by, 96, bh, unit, f"LATCH\n{c.name}",
                 [("TRIG", "L", y1 - by, pn["TRIG"]), ("THR", "L", y2 - by, pn["THR"]),
                  ("RST", "T", 48, pn["RST"]), ("OUT", "R", (y1 + y2) / 2 - by, pn["OUT"])])
    rx, ry = e["RST"]
    if c.reset:
        s.line(rx, ry, rx, ry - 8)
        label(s, rx, ry - 12, c.reset, "middle")
    else:
        vcc(s, rx, ry)
    ox, oy = e["OUT"]
    s.line(ox, oy, ox + 16, oy)
    s.dot(ox + 16, oy)
    label(s, ox + 20, oy, c.name, "start")
    s._ext(ox + 80, 0)
    return s


def grid(cells, cols, gap=30):
    s = Svg()
    x = y = rowh = 0
    for k, cell in enumerate(cells):
        if k and k % cols == 0:
            x, y, rowh = 0, y + rowh + gap, 0
        s.place(cell, x - cell.x0, y)
        x += cell.w - cell.x0 + gap
        rowh = max(rowh, cell.h)
    return s


# ---------------------------------------------------------------- sheets

def sheet_logic(chips, units, names, file, title, subtitle, cols):
    cells = [timer_cell(c, units[c.name]) for c in chips if c.name in names]
    grid(cells, cols).save(file, title, subtitle)


def sheet_rom(chips, units, example):
    s = Svg()
    pc = [f"PC{i}" for i in range(BITS)]
    lits = [l for p in pc for l in (p, "n" + p)]
    bits = ["I0", "I1", "I2", "I3", "CND", "J", "ADD", "AW"]
    x0, y0, dx, dy = 150, 70, 30, 24
    xs_lit = [x0 + dx * k for k in range(len(lits))]
    xm = xs_lit[-1] + 70
    xs_bit = [xm + dx * k for k in range(len(bits))]
    ys = [y0 + dy * w for w in range(16)]
    ybot = ys[-1] + 30

    s.text(x0 - 20, 20, "Decoder: diode-AND per word line", "bt")
    s.text(xm - 10, 20, "ROM matrix: diode-OR per bit line", "bt")
    for x, l in zip(xs_lit, lits):
        label(s, x, 44, l, "middle")
        s.line(x, 52, x, ybot, "w")
    for x, b in zip(xs_bit, bits):
        label(s, x, 44, b, "middle")
        s.line(x, 52, x, ybot + 10, "bus")
    s.text(x0 - 20, 44, "from PC / nPC timers →", "pin", "end")
    for w, y in enumerate(ys):
        vcc(s, 40, y - 10)
        res_h(s, 40, 90, y, "10k")
        s.line(40, y - 10, 40, y)
        s.line(90, y, xs_bit[-1] + 10, y)
        label(s, 100, y - 6, f"W{w:X}", "start")
        for i in range(BITS):
            lit = pc[i] if w >> i & 1 else "n" + pc[i]
            x = xs_lit[lits.index(lit)]
            diode_diag(s, x - 12, y, x, y + 12)      # anode on word line, cathode on literal
            s.dot(x - 12, y)
        for b, x in enumerate(xs_bit):
            if example[w] >> b & 1:
                diode_diag(s, x - 12, y, x, y + 12)
                s.dot(x - 12, y)
            else:
                s.circle(x - 6, y + 6, 2.2)
    yb = ybot + 10
    for b, x in enumerate(xs_bit):
        if b < BITS:
            s.text(x, yb + 44, "+IN", "pin", "middle")
            s.text(x, yb + 54, "term", "pin", "middle")
        res_v(s, x + 12, yb + 2, yb + 28, "")
        s.line(x, yb, x + 12, yb + 2)
        gnd(s, x + 12, yb + 28)
    s.text(xs_bit[0] - 8, yb + 76, "Bit lines: 1M pull-down each, then to the restore inverters below.", "pin")
    s.text(xs_bit[0] - 8, yb + 88, "I0–I3 also take the input-port term CND·nJ·SWi (the IN instruction), drawn on nI0–nI3.", "pin")
    s.text(x0 - 120, yb + 30, "●╱ diode fitted", "val")
    s.text(x0 - 120, yb + 44, "○  empty site (bit = 0)", "val")
    s.text(x0 - 120, yb + 58, "Diodes shown: countdown.asm", "val")

    rest = [timer_cell(c, units[c.name]) for c in chips if c.group == "rom"]
    g = grid(rest, 4)
    s.place(g, 0, yb + 150)
    s.save("schematics/rom.svg", "ROM: decoder, diode matrix and restore",
           "Word lines are 4-diode ANDs of PC/nPC with 10k pull-ups. Each bit line is a diode-OR of word lines.\n"
           "Each bit line is restored by two inverters (nX, then X). Pins are named by function; small numbers are TLC556 pins.")


def sheet_peripherals():
    s = Svg()
    pa, pb = PINS_556["A"], PINS_556["B"]

    # Astable U1A
    s.text(0, 14, "RUN clock: astable, U1A (1.3–10 Hz)", "bt")
    e = chip(s, 170, 60, 110, 130, "U1A", "astable",
             [("DIS", "L", 24, pa["DIS"]), ("THR", "L", 64, pa["THR"]), ("TRIG", "L", 88, pa["TRIG"]),
              ("RST", "T", 55, pa["RST"]), ("OUT", "R", 64, pa["OUT"]), ("CV", "B", 55, pa["CV"])])
    xr = 90
    vcc(s, xr, 30)
    res_v(s, xr, 30, 70, "R1 10k", left=True)
    s.line(xr, 70, xr, 84)
    s.line(xr, 84, e["DIS"][0], 84)
    s.dot(xr, 84)
    res_v(s, xr, 84, 116, "R2 10k", left=True)
    res_v(s, xr, 116, 148, "RV 100k pot", left=True)
    s.line(xr, 148, xr, 156)
    s.line(e["THR"][0], e["THR"][1], 140, e["THR"][1])
    s.line(e["TRIG"][0], e["TRIG"][1], 140, e["TRIG"][1])
    s.line(140, e["THR"][1], 140, 156)
    s.line(xr, 156, 140, 156)
    s.dot(140, 148)
    s.dot(xr, 156)
    cap_v(s, xr, 156, 200, "4.7µF", True)
    gnd(s, xr, 200)
    vcc(s, *e["RST"])
    cap_v(s, e["CV"][0], e["CV"][1], e["CV"][1] + 26, "10nF")
    gnd(s, e["CV"][0], e["CV"][1] + 26)
    ox, oy = e["OUT"]
    s.line(ox, oy, ox + 30, oy)
    label(s, ox + 34, oy, "SRC_RUN", "start")

    # Step latch U1B: SPDT momentary, COM to GND, NO -> TRIG, NC -> RST
    X = 470
    s.text(X, 14, "STEP button: debounced latch, U1B", "bt")
    e = chip(s, X + 220, 80, 110, 130, "U1B", "SR latch",
             [("TRIG", "L", 40, pb["TRIG"]), ("THR", "L", 90, pb["THR"]),
              ("RST", "T", 55, pb["RST"]), ("OUT", "R", 64, pb["OUT"]), ("CV", "B", 55, pb["CV"])])
    rst_y = e["RST"][1]
    trig_y = e["TRIG"][1]
    ncx, ncy = X + 90, rst_y + 26
    nox, noy = X + 90, trig_y
    cx, cy = X + 40, trig_y + 50
    s.circle(ncx, ncy, 3)
    s.circle(nox, noy, 3)
    s.circle(cx, cy, 3, "solid")
    s.line(cx, cy, ncx - 3, ncy + 3)            # lever resting on NC
    s.line(cx, cy, cx, cy + 20)
    gnd(s, cx, cy + 20)
    s.text(cx - 8, cy - 14, "STEP", "val", "end")
    s.text(cx - 8, cy - 2, "(push)", "val", "end")
    s.text(ncx + 6, ncy - 6, "NC", "pin")
    s.text(nox + 6, noy + 14, "NO", "pin")
    s.line(ncx, ncy - 3, ncx, rst_y)
    s.line(ncx, rst_y, e["RST"][0], rst_y)
    s.line(nox + 3, noy, e["TRIG"][0], trig_y)
    vcc(s, X + 140, rst_y - 30)
    res_v(s, X + 140, rst_y - 30, rst_y, "10k", left=True)
    s.dot(X + 140, rst_y)
    vcc(s, X + 180, trig_y - 34)
    res_v(s, X + 180, trig_y - 34, trig_y, "10k")
    s.dot(X + 180, trig_y)
    s.line(e["THR"][0], e["THR"][1], X + 190, e["THR"][1])
    s.line(X + 190, e["THR"][1], X + 190, e["THR"][1] + 12)
    gnd(s, X + 190, e["THR"][1] + 12)
    cap_v(s, e["CV"][0], e["CV"][1], e["CV"][1] + 26, "10nF")
    gnd(s, e["CV"][0], e["CV"][1] + 26)
    ox, oy = e["OUT"]
    s.line(ox, oy, ox + 30, oy)
    label(s, ox + 34, oy, "SRC_STEP", "start")
    s.text(X, 268, "Press: NO pulls TRIG low → OUT high (master phase).", "val")
    s.text(X, 282, "Release: NC pulls RST low → OUT low (slaves copy, LEDs update).", "val")
    s.text(X, 296, "Bounce between contacts: both pulled high → latch holds.", "val")

    # RUN/STEP selector
    Y = 340
    s.text(0, Y, "RUN/STEP selector", "bt")
    s.circle(60, Y + 40, 3)
    s.circle(60, Y + 80, 3)
    label(s, 54, Y + 40, "SRC_RUN")
    label(s, 54, Y + 80, "SRC_STEP")
    s.circle(140, Y + 60, 3, "solid")
    s.line(140, Y + 60, 64, Y + 42)
    s.line(140, Y + 60, 220, Y + 60)
    s.dot(190, Y + 60)
    vcc(s, 190, Y + 20)
    res_v(s, 190, Y + 20, Y + 60, "100k")
    label(s, 224, Y + 60, "SRC", "start")
    s.text(0, Y + 110, "100k pull-up: SRC rests high (harmless master phase) while", "val")
    s.text(0, Y + 124, "the contacts are in transit. Hold RESET while switching.", "val")

    # Reset
    X = 470
    s.text(X, Y, "Reset (nRST)", "bt")
    yl = Y + 64
    vcc(s, X + 60, Y + 24)
    res_v(s, X + 60, Y + 24, yl, "10k", left=True)
    s.line(X + 60, yl, X + 300, yl)
    s.dot(X + 60, yl)
    cap_v(s, X + 60, yl, yl + 46, "10µF", True, left=True)
    gnd(s, X + 60, yl + 46)
    bx = X + 140                                 # push-button to GND
    s.dot(bx, yl)
    s.line(bx, yl, bx, yl + 12)
    s.circle(bx, yl + 14, 2.5)
    s.circle(bx, yl + 34, 2.5)
    s.line(bx + 10, yl + 10, bx + 10, yl + 38)
    s.line(bx + 10, yl + 24, bx + 20, yl + 24)
    s.text(bx + 24, yl + 28, "RESET", "pin")
    s.line(bx, yl + 36, bx, yl + 46)
    gnd(s, bx, yl + 46)
    dx = X + 230                                 # discharge diode: anode nRST, cathode VCC
    s.dot(dx, yl)
    diode_v(s, dx, Y + 24, False)
    s.line(dx, Y + 48, dx, yl)
    vcc(s, dx, Y + 24)
    s.text(dx + 8, Y + 40, "1N4148", "val")
    label(s, X + 304, yl, "nRST", "start")
    s.text(X, Y + 140, "→ RST of every slave latch and of nMEN.", "val")

    # LEDs and input switches
    Y = 520
    s.text(0, Y, "Output LEDs (×9: A0–A3, CF, PC0–PC3)", "bt")
    label(s, 60, Y + 40, "A0")
    res_h(s, 64, 130, Y + 40, "4.7k")
    s.line(130, Y + 40, 150, Y + 40)
    s.line(150, Y + 40, 150, Y + 52)
    diode_v(s, 150, Y + 52, True)
    s.line(160, Y + 60, 168, Y + 56)
    s.line(162, Y + 66, 170, Y + 62)
    gnd(s, 150, Y + 76)
    s.text(180, Y + 64, "high-efficiency LED", "val")

    X = 470
    s.text(X, Y, "Input switches (×4: SW0–SW3)", "bt")
    vcc(s, X + 40, Y + 26)
    s.line(X + 40, Y + 26, X + 40, Y + 36)
    s.circle(X + 40, Y + 38, 2.5)
    s.line(X + 40, Y + 40, X + 54, Y + 56)
    s.circle(X + 40, Y + 60, 2.5)
    s.text(X + 60, Y + 50, "DIP (ON = 1)", "val")
    s.line(X + 40, Y + 62, X + 40, Y + 76)
    s.dot(X + 40, Y + 76)
    s.line(X + 40, Y + 76, X + 160, Y + 76)
    label(s, X + 164, Y + 76, "SW0", "start")
    res_v(s, X + 40, Y + 76, Y + 116, "4.7k", left=True)
    gnd(s, X + 40, Y + 116)
    s.text(X, Y + 140, "Feeds the AND term CND·nJ·SW0 on ROM bit line I0.", "val")

    s.save("schematics/peripherals.svg", "Peripherals: clock source, reset, LEDs, inputs",
           "All timers are TLC556 halves (CMOS 555) at 9 V. Small numbers are TLC556 pin numbers.\n"
           "Every package: 100 nF VCC–GND. Every logic timer: 10 nF CV–GND, DIS unconnected.")


def sheet_conventions():
    s = Svg()
    s.text(0, 14, "Inverter (INV)", "bt")
    e = chip(s, 110, 40, 90, 70, "INV", "", [("TRIG", "L", 22, "2/6"), ("THR", "L", 48, "6/2"),
                                            ("RST", "T", 45, 4), ("OUT", "R", 35, "3/5")])
    s.line(e["TRIG"][0], e["TRIG"][1], 80, e["TRIG"][1])
    s.line(e["THR"][0], e["THR"][1], 80, e["THR"][1])
    s.line(80, e["TRIG"][1], 80, e["THR"][1])
    s.dot(80, 75)
    s.line(40, 75, 80, 75)
    label(s, 36, 75, "X")
    vcc(s, *e["RST"])
    s.line(*e["OUT"], e["OUT"][0] + 20, e["OUT"][1])
    label(s, e["OUT"][0] + 24, e["OUT"][1], "nX", "start")
    s.text(0, 140, "TRIG and THR tied: in < 1/3 Vcc → out high,", "val")
    s.text(0, 154, "in > 2/3 Vcc → out low. Schmitt inverter.", "val")

    X = 360
    s.text(X, 14, "Latch (LATCH)", "bt")
    e = chip(s, X + 110, 40, 90, 80, "LATCH", "", [("TRIG", "L", 22, ""), ("THR", "L", 58, ""),
                                                  ("RST", "T", 45, ""), ("OUT", "R", 40, "")])
    s.line(*e["TRIG"], X + 60, e["TRIG"][1])
    label(s, X + 56, e["TRIG"][1], "set when low")
    s.line(*e["THR"], X + 60, e["THR"][1])
    label(s, X + 56, e["THR"][1], "reset when high")
    s.line(*e["RST"], e["RST"][0], e["RST"][1] - 8)
    label(s, e["RST"][0], e["RST"][1] - 12, "clear when low", "middle")
    s.line(*e["OUT"], e["OUT"][0] + 20, e["OUT"][1])
    label(s, e["OUT"][0] + 24, e["OUT"][1], "Q", "start")
    s.text(X, 150, "TRIG wins over THR; RST overrides both. Neither → hold.", "val")

    Y = 200
    s.text(0, Y, "Diode-AND (100k pull-up)", "bt")
    vcc(s, 140, Y + 26)
    res_v(s, 140, Y + 26, Y + 56, "100k")
    s.line(140, Y + 56, 140, Y + 94)
    for k, lit in enumerate(["A", "B", "C"]):
        yy = Y + 64 + 15 * k
        diode(s, 106, yy, False)
        s.line(130, yy, 140, yy)
        s.dot(140, yy)
        label(s, 102, yy, lit)
    s.line(140, Y + 79, 200, Y + 79)
    label(s, 204, Y + 79, "A·B·C", "start")
    s.text(0, Y + 124, "Cathodes to 555 outputs. Any input low pulls the node low.", "val")

    s.text(X, Y, "Diode-OR (1M pull-down)", "bt")
    for k, lit in enumerate(["P", "Q", "R"]):
        yy = Y + 40 + 18 * k
        diode(s, X + 60, yy, True)
        s.line(X + 84, yy, X + 110, yy)
        s.dot(X + 110, yy)
        label(s, X + 56, yy, lit)
    s.line(X + 110, Y + 40, X + 110, Y + 90, "bus")
    s.line(X + 110, Y + 84, X + 170, Y + 84)
    s.dot(X + 110, Y + 84)
    label(s, X + 174, Y + 84, "P+Q+R → TRIG/THR", "start")
    res_v(s, X + 110, Y + 90, Y + 116, "1M")
    gnd(s, X + 110, Y + 116)
    s.text(X, Y + 140, "Anodes from AND nodes or 555 outputs. Any input high pulls it high.", "val")

    Y = 380
    s.text(0, Y, "Design rule and naming", "bt")
    for k, line in enumerate([
        "• Between two 555s: at most one diode-AND, then one diode-OR (a sum of products).",
        "• Every AND input is a 555 output. nX is always an inverter driven by X.",
        "• Blue names are nets: a 555 output, or a node named in NETLIST.md / netlist.csv.",
        "• Unit names like U12A are TLC556 package + half. Small numbers are package pins.",
        "• 556 pins differ from 555: timer A TRIG=6 THR=2 OUT=5 RST=4; timer B TRIG=8 THR=12 OUT=9 RST=10.",
    ]):
        s.text(0, Y + 24 + 16 * k, line, "bs")
    s.save("schematics/conventions.svg", "Schematic conventions",
           "How to read the 555-PU sheets. Pin numbers on this sheet: 555 / 556-A.")


def block_diagram(chips):
    s = Svg()
    count = {}
    for c in chips:
        key = c.group
        if c.group == "state":
            key = "PC" if "PC" in c.name else ("CF" if "CF" in c.name else "A")
        count[key] = count.get(key, 0) + 1

    def blk(x, y, w, h, title, lines, cls="blk"):
        s.rect(x, y, w, h, cls, 8)
        s.text(x + w / 2, y + 20, title, "bt", "middle")
        for k, l in enumerate(lines):
            s.text(x + w / 2, y + 38 + 14 * k, l, "bs", "middle")
        return x, y, w, h

    def arrow(pts, text=None, at=0, dx=6, dy=-6, anchor="start"):
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        s.el.append(f'<path d="{d}" class="arrow"/>')
        for x, y in pts:
            s._ext(x, y)
        if text:
            x, y = pts[at]
            s.text(x + dx, y + dy, text, "lab", anchor)

    blk(20, 20, 180, 80, "Clock source", ["U1: astable (RUN)", "or STEP button latch", "2 × 555"], "blk2")
    blk(290, 20, 220, 80, "Clock interlock", ["two-phase, non-overlapping", "MEN / SEN never together",
                                             f"{count['clock']} × 555"], "blk2")
    arrow([(200, 60), (290, 60)], "SRC", 0, 22, -8)
    s.line(510, 60, 1050, 60, "bus")
    s.text(560, 52, "MEN nMEN SEN nSEN → every master / slave latch", "lab")
    s.text(560, 80, "nRST → every slave (clear) and nMEN", "lab")

    blk(20, 170, 180, 110, "Program counter", ["PC0–PC3", "master + slave + inverter", "per bit",
                                              f"{count['PC']} × 555"])
    blk(290, 170, 160, 110, "Decoder", ["16 word lines", "4-diode AND each", "10k pull-ups", "0 × 555"], "blk3")
    blk(520, 170, 170, 110, "ROM matrix", ["16 words × 8 bits", "diode or DIP+diode", "per 1-bit", "0 × 555"], "blk3")
    blk(760, 170, 180, 110, "ROM restore", ["two inverters per bit", "AW ADD J CND I0–I3", "and complements",
                                           f"{count['rom']} × 555"])
    arrow([(200, 225), (290, 225)], "PC, nPC", 0, 14, -8)
    arrow([(450, 225), (520, 225)], "W0–WF", 0, 8, -8)
    arrow([(690, 225), (760, 225)], "bit lines", 0, 6, -8)

    blk(520, 340, 170, 70, "Input switches", ["SW0–SW3 (DIP)", "ORed into I0–I3 by IN"], "blk2")
    arrow([(605, 340), (605, 280)], "CND·nJ·SWi", 1, 8, 30)

    blk(20, 470, 180, 110, "Next-state logic", ["diode terms wired", "straight into every", "master latch's",
                                               "TRIG / THR (0 × 555)"], "blk3")
    blk(290, 470, 190, 110, "Adder carry chain", ["C1–C3 and nC1–nC3", "ripple, A + IMM", "",
                                                 f"{count['alu']} × 555"])
    blk(560, 470, 180, 110, "Accumulator A", ["A0–A3", "3 × 555 per bit", "", f"{count['A']} × 555"])
    blk(800, 470, 150, 110, "Carry flag", ["CF", "tested by JC", "", f"{count['CF']} × 555"])
    blk(990, 170, 150, 110, "LEDs", ["9 LEDs, driven", "straight from the", "A0–A3, CF and", "PC0–PC3 timers"], "blk2")

    # control/immediate bus from ROM restore down to the datapath
    arrow([(850, 280), (850, 420), (650, 420), (650, 470)], "AW ADD I0–I3", 1, -6, -8, "end")
    arrow([(850, 420), (875, 420), (875, 470)])
    arrow([(850, 420), (1080, 420), (1080, 640), (110, 640), (110, 580)],
          "J CND I0–I3 → PC next-state (jump target)", 3, 20, -8)
    arrow([(560, 510), (480, 510)], "A, nA", 0, -36, -8)
    arrow([(480, 545), (560, 545)], "carries", 0, 12, 16)
    arrow([(385, 580), (385, 615), (875, 615), (875, 580)], "carry out of bit 3", 1, 120, -6)
    arrow([(950, 525), (990, 525), (990, 655), (90, 655), (90, 580)])
    s.text(560, 670, "CF, nCF → PC next-state (JC condition)", "lab")
    arrow([(110, 470), (110, 280)], "PC + 1 or IMM", 0, 8, -60)
    s.text(20, 710, f"Total: {len(chips)} logic timers + 2 in U1 = {len(chips) + 2} × 555 "
                    f"in {len(chips) // 2 + 1} × TLC556, plus ~730 diodes. No other active parts.", "bs")
    s.save("block-diagram.svg", "555-PU block diagram",
           "4-bit accumulator CPU. Blue = 555 timers, green = diode-only logic, orange = clock and I/O.")


def write_all():
    chips, _ = build([0] * 16)
    units = allocate(chips)
    (OUT / "schematics").mkdir(parents=True, exist_ok=True)
    block_diagram(chips)
    sheet_conventions()
    sheet_peripherals()
    clock = [c.name for c in chips if c.group == "clock"]
    sheet_logic(chips, units, clock, "schematics/clock.svg", "Clock interlock",
                "SRC from the peripherals sheet. A phase opens only after the other phase's last\n"
                "signal (MOFF / SOFF) reports closed. RST of nMEN = nRST holds the masters open during reset.", 4)
    sheet_rom(chips, units, assemble((ROOT / "programs" / "countdown.asm").read_text(encoding="utf-8")))
    alu = [c.name for c in chips if c.group == "alu"]
    sheet_logic(chips, units, alu, "schematics/carry.svg", "Adder carry chain",
                "Carry into bits 1–3, both polarities. The sum bits are folded into the A master latches.", 2)
    regs = [f"PC{i}" for i in range(BITS)] + [f"A{i}" for i in range(BITS)] + ["CF"]
    for r in regs:
        sheet_logic(chips, units, ["m" + r, r, "n" + r], f"schematics/reg-{r}.svg",
                    f"Register bit {r}",
                    f"Master m{r} (stores NOT {r}) with the next-state logic folded into its TRIG/THR,\n"
                    f"slave {r} (cleared by nRST), and inverter n{r}.", 3)
    return sorted(p.relative_to(ROOT).as_posix() for p in OUT.rglob("*.svg"))


if __name__ == "__main__":
    for f in write_all():
        print(f)
