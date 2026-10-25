"""
555-PU: a 4-bit CPU built from 555 timers, diodes and resistors.

This file is the single source of truth for the design. It:
  1. generates the gate-level netlist (every 555 and every diode network),
  2. simulates it chip-by-chip with random propagation delays,
  3. checks it against a plain ISA reference model,
  4. writes NETLIST.md (readable wiring list) and netlist.csv (every part
     and net, with 556 package pin numbers).

Logic family ("555-DTL")
------------------------
Every signal that leaves a chip is a 555 output (OUT). Between two 555s
there is at most ONE diode-AND level feeding ONE diode-OR level:

    555 outputs --|>|-- AND node (pull-up) --|>|-- OR node (pull-down) --> TRIG / THR

A node is therefore described as a list of product terms, each term a list of
literal names (555 outputs). A one-literal term is just a single diode into
the OR node. A node with a single multi-literal term is a bare AND node.

A 555 is used in only two ways:
  INV   - TRIG and THR tied together: a Schmitt-trigger inverter.
  LATCH - TRIG low  -> output high (set, dominates)
          THR high  -> output low  (reset)
          neither   -> hold
  RST low forces the output low on either type.

Pins are named by function because a 556 numbers them differently from a 555
(on 556 timer A, pin 2 is THR and pin 6 is TRIG).

Usage:  python cpu555.py            run all tests, write NETLIST.md + netlist.csv
        python cpu555.py prog.asm   assemble and run a program, print a trace
"""

import csv
import random
import sys
from pathlib import Path

BITS = 4
ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# Instruction set
#
#   bit:   7    6    5    4    3..0
#         AW  ADD   J   CND   IMM
#
#   AW   write the accumulator (and the carry flag)
#   ADD  A <- A + IMM (C <- carry out)  instead of  A <- IMM (C <- 0)
#   J    jump to IMM ...
#   CND  ... only if C is set
#   CND without J: IMM is ORed with the input switches (the IN instruction)
# --------------------------------------------------------------------------

OPS = {"NOP": 0x00, "LDI": 0x80, "ADD": 0xC0, "JMP": 0x20, "JC": 0x30, "IN": 0x90}
CONFLICTS = [{"LDI", "ADD"}, {"LDI", "IN"}, {"JMP", "JC"}, {"IN", "JMP"}, {"IN", "JC"}]


def assemble(text):
    """One instruction per line. Fields can be combined with '|' as long as
    they share the immediate, e.g. 'ADD 1 | JMP 1' or 'ADD | IN'.
    Comments start with ';'."""
    rom = []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.split(";")[0].strip()
        if not line:
            continue
        word, imm, ops = 0, None, set()
        for part in line.split("|"):
            tok = part.split()
            if not tok:
                raise SyntaxError(f"line {lineno}: empty field")
            op = tok[0].upper()
            if op not in OPS:
                raise SyntaxError(f"line {lineno}: unknown op {op}")
            if len(tok) > 2 or (op in ("NOP", "IN") and len(tok) > 1):
                raise SyntaxError(f"line {lineno}: too many operands for {op}")
            ops.add(op)
            word |= OPS[op]
            if len(tok) > 1:
                v = int(tok[1], 0)
                if not 0 <= v <= 15:
                    raise SyntaxError(f"line {lineno}: immediate {v} is not 0..15")
                if imm is not None and v != imm:
                    raise SyntaxError(f"line {lineno}: fields need the same immediate")
                imm = v
        for bad in CONFLICTS:
            if bad <= ops:
                raise SyntaxError(f"line {lineno}: {' and '.join(sorted(bad))} cannot be combined")
        rom.append(word | (imm or 0))
    if len(rom) > 16:
        raise ValueError("program longer than 16 words")
    return rom + [0] * (16 - len(rom))


def reference_step(state, rom, sw=0):
    pc, a, c = state
    w = rom[pc]
    aw, add, j, cnd, imm = w >> 7 & 1, w >> 6 & 1, w >> 5 & 1, w >> 4 & 1, w & 15
    if cnd and not j:
        imm |= sw
    taken = j and (not cnd or c)
    if aw:
        if add:
            s = a + imm
            a, c = s & 15, s >> 4
        else:
            a, c = imm, 0
    pc = imm if taken else (pc + 1) & 15
    return pc, a, c


# --------------------------------------------------------------------------
# Netlist generation
# --------------------------------------------------------------------------

def n(x):
    """Name of the complement of a literal."""
    return x[1:] if x.startswith("n") else "n" + x


def clean(terms):
    """Drop contradictory terms (x and nx) and duplicates."""
    out = []
    for t in terms:
        s = list(dict.fromkeys(t))
        if any(n(x) in s for x in s):
            continue
        if sorted(s) not in [sorted(o) for o in out]:
            out.append(s)
    return out


class Chip:
    def __init__(self, name, kind, trig, thr, reset=None, group="", note=""):
        self.name, self.kind = name, kind
        self.trig, self.thr = clean(trig), clean(thr)
        self.reset, self.group, self.note = reset, group, note


def build(rom):
    chips = []

    def inv(name, node, group, note="", reset=None):
        chips.append(Chip(name, "INV", node, node, reset, group, note))

    def latch(name, trig, thr, group, note="", reset=None):
        chips.append(Chip(name, "LATCH", trig, thr, reset, group, note))

    def register_bit(x, xterms):
        """Master-slave flip-flop for state bit x, next-state logic folded in.

        The master stores NOT x so the slave can take its output directly:
          master TRIG = OR(x terms, nMEN)        low  -> m = 1 (x = 0)
          master THR  = OR(each x term · MEN)    high -> m = 0 (x = 1)
          slave  TRIG = OR(m, nSEN)              low  -> x = 1
          slave  THR  = AND(m, SEN)              high -> x = 0
        """
        m = "m" + x
        latch(m, xterms + [["nMEN"]], [t + ["MEN"] for t in xterms],
              "state", f"master of {x} (holds NOT {x})")
        latch(x, [[m], ["nSEN"]], [[m, "SEN"]], "state", f"slave: {x}", reset="nRST")
        inv(n(x), [[x]], "state", f"NOT {x}")

    # ---- clock: interlocked two-phase, non-overlapping ----------------------
    # SRC comes from the astable (RUN) or the debounced STEP latch. Each phase
    # opens only after the other phase's last enable line has gone inactive, so
    # master and slave are never transparent together, provided SRC itself is
    # glitch-free. Reset holds the masters open and the slaves closed (and cleared).
    inv("nSRC", [["SRC"]], "clock", "inverted clock source")
    inv("nMEN", [["SRC", "SOFF"]], "clock", "master enable, active low", reset="nRST")
    inv("MEN", [["nMEN"]], "clock", "master enable")
    inv("MOFF", [["MEN"]], "clock", "master fully closed (interlock)")
    inv("nSEN", [["nSRC", "MOFF"]], "clock", "slave enable, active low")
    inv("SEN", [["nSEN"]], "clock", "slave enable")
    inv("SOFF", [["SEN"]], "clock", "slave fully closed (interlock)")

    # ---- program ROM: 4->16 decoder (word lines) + diode matrix -----------
    # The immediate bit lines also take CND·nJ·SWi, which ORs the input
    # switches into IMM for the IN instruction.
    pc = [f"PC{i}" for i in range(BITS)]
    word_lines = [[pc[i] if w >> i & 1 else n(pc[i]) for i in range(BITS)] for w in range(16)]
    rom_bits = ["I0", "I1", "I2", "I3", "CND", "J", "ADD", "AW"]
    for b, name in enumerate(rom_bits):
        bitline = [word_lines[w] for w in range(16) if rom[w] >> b & 1]
        if b < BITS:
            bitline.append(["CND", "nJ", f"SW{b}"])
        inv(n(name), bitline, "rom", f"ROM bit {b} restore (inverted)")
        inv(name, [[n(name)]], "rom", f"ROM bit {b} restore")

    # ---- ALU: ripple adder A + I -------------------------------------------
    carry_in = None
    a_next = []
    for i in range(BITS):
        A, I, C = f"A{i}", f"I{i}", carry_in
        lits = [A, I] + ([C] if C else [])
        odd = []
        for v in range(1 << len(lits)):
            t = [l if v >> k & 1 else n(l) for k, l in enumerate(lits)]
            if bin(v).count("1") % 2:
                odd.append(t)
        cy = [[A, I]] + ([[A, C], [I, C]] if C else [])
        ncy = ([[n(A), n(I)], [n(A), n(C)], [n(I), n(C)]] if C else [[n(A)], [n(I)]])
        a_next.append([["nADD", I]] + [["ADD"] + t for t in odd])
        if i < BITS - 1:
            co = f"C{i + 1}"
            inv(n(co), cy, "alu", f"carry into bit {i + 1} (inverted)")
            inv(co, ncy, "alu", f"carry into bit {i + 1}")
            carry_in = co
        else:
            cf_next = [["ADD"] + t for t in cy]

    # AW = 0 holds the value: x_next = AW·new + nAW·x. Gating the master's
    # enable with AW instead would leave it holding its power-up value after reset.
    for i in range(BITS):
        register_bit(f"A{i}", [t + ["AW"] for t in a_next[i]] + [["nAW", f"A{i}"]])
    register_bit("CF", [t + ["AW"] for t in cf_next] + [["nAW", "CF"]])

    # ---- program counter: jump ? IMM : PC + 1 -------------------------------
    taken = [["J", "nCND"], ["J", "CF"]]
    not_taken = [["nJ"], ["CND", "nCF"]]
    for i in range(BITS):
        lower = pc[:i]
        inc = [[pc[i], n(p)] for p in lower] + [[n(pc[i])] + lower]
        xterms = [t + [f"I{i}"] for t in taken] + [a + b for a in not_taken for b in inc]
        register_bit(pc[i], xterms)

    return chips, word_lines


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------

def node_value(terms, sig):
    return any(all(sig[l] for l in t) for t in terms)


def chip_target(c, sig):
    if c.reset and not sig[c.reset]:
        return False
    if not node_value(c.trig, sig):     # trigger below 1/3 Vcc
        return True
    if node_value(c.thr, sig):          # threshold above 2/3 Vcc
        return False
    return sig[c.name]


class Sim:
    def __init__(self, rom, rng, dmin=1, dmax=4):
        self.chips, _ = build(rom)
        self.rng, self.dmin, self.dmax = rng, dmin, dmax
        self.sig = {c.name: rng.random() < 0.5 for c in self.chips}
        self.sig.update(SRC=True, nRST=True, **{f"SW{i}": False for i in range(BITS)})
        self.pending = {}
        self.t = 0
        self.check_overlap = False

    def settle(self, limit=5000):
        for _ in range(limit):
            for c in self.chips:
                tgt = chip_target(c, self.sig)
                if tgt == self.sig[c.name]:
                    self.pending.pop(c.name, None)
                elif self.pending.get(c.name, (None,))[0] != tgt:
                    self.pending[c.name] = (tgt, self.t + self.rng.randint(self.dmin, self.dmax))
            if not self.pending:
                return
            self.t += 1
            for name, (v, when) in list(self.pending.items()):
                if when <= self.t:
                    self.sig[name] = v
                    del self.pending[name]
            if self.check_overlap:
                s = self.sig
                if (s["MEN"] or not s["nMEN"]) and (s["SEN"] or not s["nSEN"]):
                    raise AssertionError(f"t={self.t}: master and slave enabled together")
        raise RuntimeError("circuit did not settle (oscillation?)")

    def word(self, prefix):
        return sum(self.sig[f"{prefix}{i}"] << i for i in range(BITS))

    def state(self):
        return self.word("PC"), self.word("A"), int(self.sig["CF"])

    def set_switches(self, v):
        for i in range(BITS):
            self.sig[f"SW{i}"] = bool(v >> i & 1)
        self.settle()

    def reset(self, src_at_release=True):
        self.sig["nRST"] = False
        self.settle()
        self.sig["SRC"] = src_at_release
        self.settle()
        self.sig["nRST"] = True
        self.settle()
        if not src_at_release:      # the release already ran the slave phase
            self.sig["SRC"] = True
            self.settle()
        self.check_overlap = True

    def step(self):
        self.sig["SRC"] = False   # phase 2: slaves copy masters
        self.settle()
        self.sig["SRC"] = True    # phase 1: masters compute next state
        self.settle()


def check(rom, cycles=40, seeds=4):
    for seed in range(seeds):
        rng = random.Random(seed)
        sim = Sim(rom, random.Random(seed + 1000))
        sw = rng.randrange(16)
        sim.set_switches(sw)
        release_low = seed % 2 == 1
        sim.reset(src_at_release=not release_low)
        ref = (0, 0, 0)
        if release_low:     # releasing reset with SRC low executes instruction 0
            ref = reference_step(ref, rom, sw)
        if sim.state() != ref:
            raise AssertionError(f"seed {seed}: after reset {sim.state()} != {ref}")
        for cyc in range(cycles):
            if rng.random() < 0.3:
                sw = rng.randrange(16)
                sim.set_switches(sw)
            sim.step()
            ref = reference_step(ref, rom, sw)
            if sim.state() != ref:
                raise AssertionError(f"seed {seed} cycle {cyc}: sim {sim.state()} != ref {ref}")


# --------------------------------------------------------------------------
# Netlist output
# --------------------------------------------------------------------------

# Function -> package pin. A 556 timer A and B, and a single 555.
PINS_556 = {"A": {"DIS": 1, "THR": 2, "CV": 3, "RST": 4, "OUT": 5, "TRIG": 6},
            "B": {"TRIG": 8, "OUT": 9, "RST": 10, "CV": 11, "THR": 12, "DIS": 13}}
PINS_555 = {"TRIG": 2, "OUT": 3, "RST": 4, "CV": 5, "THR": 6, "DIS": 7}


class Parts:
    """Collects every component and net as CSV rows: ref, part, value, a, b."""

    def __init__(self):
        self.rows, self.count = [], {}

    def add(self, prefix, part, value, a, b=""):
        k = self.count[prefix] = self.count.get(prefix, 0) + 1
        self.rows.append([f"{prefix}{k}", part, value, a, b])

    def pin(self, unit, fn, net):
        ref, half = unit[:-1], unit[-1]
        self.rows.append([ref, "TLC556", f"pin {PINS_556[half][fn]} ({fn} {half})", net, ""])

    def node(self, net, terms, force_or=False, and_pullup="100k"):
        """Diodes and resistors for one node. Returns nothing; net is the node."""
        if len(terms) == 1 and len(terms[0]) > 1 and not force_or:   # bare AND
            self.add("R", "resistor", and_pullup, net, "VCC")
            for l in terms[0]:
                self.add("D", "1N4148", "", net, l)
            return
        self.add("R", "resistor", "1M", net, "GND")
        for k, t in enumerate(terms):
            if len(t) == 1:
                self.add("D", "1N4148", "", t[0], net)
            else:
                a = f"{net}.t{k}"
                self.add("R", "resistor", and_pullup, a, "VCC")
                for l in t:
                    self.add("D", "1N4148", "", a, l)
                self.add("D", "1N4148", "", a, net)

    def total(self, prefix):
        return self.count.get(prefix, 0)


def fmt_node(terms):
    if len(terms) == 1 and len(terms[0]) == 1:
        return f"wire from `{terms[0][0]}`"
    if not terms:
        return "(pull-down only: always low)"
    return " + ".join("·".join(t) for t in terms)


def allocate(chips):
    """Timer -> 556 half. U1 holds the astable (A) and step latch (B)."""
    units = {"ASTABLE": "U1A", "STEP": "U1B"}
    for k, c in enumerate(chips):
        units[c.name] = f"U{k // 2 + 2}{'AB'[k % 2]}"
    return units


def write_netlists(chips, word_lines):
    units = allocate(chips)
    p = Parts()

    # Peripherals: clock source, reset, LEDs, input switches (see README §7).
    p.pin("U1A", "DIS", "AST_DIS")
    p.pin("U1A", "THR", "AST_C")
    p.pin("U1A", "TRIG", "AST_C")
    p.pin("U1A", "RST", "VCC")
    p.pin("U1A", "OUT", "SRC_RUN")
    p.add("R", "resistor", "10k", "VCC", "AST_DIS")
    p.add("R", "resistor", "10k", "AST_DIS", "AST_POT")
    p.add("RV", "potentiometer (as rheostat)", "100k", "AST_POT", "AST_C")
    p.add("C", "capacitor", "4.7uF", "AST_C", "GND")
    p.pin("U1B", "TRIG", "STEP_NO")
    p.pin("U1B", "THR", "GND")
    p.pin("U1B", "RST", "STEP_NC")
    p.pin("U1B", "OUT", "SRC_STEP")
    p.pin("U1B", "DIS", "")
    p.add("R", "resistor", "10k", "STEP_NO", "VCC")
    p.add("R", "resistor", "10k", "STEP_NC", "VCC")
    p.add("S", "SPDT momentary push-button (STEP)", "COM=GND", "STEP_NO", "STEP_NC")
    p.add("S", "SPDT toggle (RUN/STEP), COM=SRC", "", "SRC_RUN", "SRC_STEP")
    p.add("R", "resistor", "100k", "SRC", "VCC")
    p.add("R", "resistor", "10k", "nRST", "VCC")
    p.add("C", "capacitor", "10uF", "nRST", "GND")
    p.add("D", "1N4148", "power-off discharge", "nRST", "VCC")
    p.add("S", "push-button (RESET)", "", "nRST", "GND")
    for led in [f"A{i}" for i in range(BITS)] + ["CF"] + pc_names():
        p.add("R", "resistor", "4.7k", led, f"LED_{led}")
        p.add("LED", "LED (high efficiency)", "", f"LED_{led}", "GND")
    for i in range(BITS):
        p.add("S", "DIP switch (input)", "", f"SW{i}", "VCC")
        p.add("R", "resistor", "4.7k", f"SW{i}", "GND")

    # ROM decoder.
    for w, t in enumerate(word_lines):
        p.node(f"W{w:X}", [t], and_pullup="10k")

    # Logic timers.
    md = []
    for c in chips:
        u = units[c.name]
        if c.kind == "INV":
            net = None
            if len(c.trig) == 1 and len(c.trig[0]) == 1:
                net = c.trig[0][0]
            else:
                net = f"{c.name}.IN"
                p.node(net, c.trig, force_or=c.group == "rom")
            p.pin(u, "TRIG", net)
            p.pin(u, "THR", net)
        else:
            for fn, terms in (("TRIG", c.trig), ("THR", c.thr)):
                net = f"{c.name}.{fn}"
                if len(terms) == 1 and len(terms[0]) == 1:
                    net = terms[0][0]
                else:
                    p.node(net, terms)
                p.pin(u, fn, net)
        p.pin(u, "RST", c.reset or "VCC")
        p.pin(u, "OUT", c.name)
        p.pin(u, "DIS", "")

    for k in range(1, len(chips) // 2 + 2):
        ref = f"U{k}"
        for half in "AB":
            p.pin(ref + half, "CV", f"{ref}.CV{half}")
            p.add("C", "capacitor", "10nF", f"{ref}.CV{half}", "GND")
        p.rows.append([ref, "TLC556", "pin 7 (GND)", "GND", ""])
        p.rows.append([ref, "TLC556", "pin 14 (VCC)", "VCC", ""])
        p.add("C", "capacitor", "100nF", "VCC", "GND")

    with open(ROOT / "netlist.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ref", "part", "value", "a (anode / net)", "b (cathode / net)"])
        w.writerows(p.rows)

    # ---- NETLIST.md ------------------------------------------------------
    n_chips = len(chips) // 2 + 1
    groups = {}
    for c in chips:
        groups.setdefault(c.group, []).append(c)
    titles = {"clock": "Clock", "rom": "ROM output restore", "alu": "Adder carry chain",
              "state": "Registers (A, carry flag, PC)"}
    md += ["# 555-PU netlist", "",
           "Generated by `sim/cpu555.py`. Do not edit by hand. Every part and net,",
           "including the peripherals, is also in [netlist.csv](netlist.csv).", "",
           "## Parts", "",
           f"- **{n_chips} × TLC556** (dual CMOS 555): {len(chips)} logic timers, plus the",
           "  astable and the step latch in U1",
           "  - " + ", ".join(f"{titles[g]}: {len(groups[g])}" for g in titles),
           f"- **{p.total('D') - 1}** 1N4148 diodes (logic) + 1 (reset) + one per 1-bit in the program",
           f"- **{p.total('R')}** resistors, **{p.total('C')}** capacitors, 1 × 100k pot, "
           f"{p.total('LED')} LEDs, {p.total('S')} switches", "",
           "## Pins are named by function", "",
           "A 556 does **not** use 555 pin numbers. Wire by function:", "",
           "| function | 555 | 556 timer A | 556 timer B |",
           "|---|---|---|---|"]
    for fn in ["TRIG", "THR", "RST", "OUT", "CV", "DIS"]:
        md.append(f"| {fn} | {PINS_555[fn]} | {PINS_556['A'][fn]} | {PINS_556['B'][fn]} |")
    md += ["| GND / VCC | 1 / 8 | 7 / 14 | 7 / 14 |", "",
           "Each timer below is listed as `U<n><A|B>`. CV gets 10 nF to GND, DIS is",
           "unconnected, and every package gets 100 nF across its supply.", "",
           "## Notation", "",
           "`·` is a diode-AND: one diode per literal, cathode to that 555 output,",
           "all anodes joined at an AND node with a 100k pull-up to VCC. `+` is a",
           "diode-OR: one diode per term, anode from the term, cathodes joined at the",
           "pin node with a 1M pull-down to GND. A literal on its own in an OR is a",
           "single diode from that output. `nX` is the output of an inverter timer",
           "whose input is `X`. `SWi` is input switch i (to VCC, 4.7k pull-down).", "",
           "## ROM word lines (decoder)", "",
           "Each word line is a diode-AND with a **10k** pull-up (it drives up to 8 bit lines).", ""]
    for w, t in enumerate(word_lines):
        md.append(f"- `W{w:X}` = {'·'.join(t)}")
    md += ["", "Each ROM bit line is a diode-OR of word lines: fit a diode (anode `Wn`,",
           "cathode bit line) wherever bit `b` of word `n` is 1. To make it reprogrammable,",
           "put a DIP switch + diode at all 128 crossings.", ""]
    for g in titles:
        md += [f"## {titles[g]}", ""]
        for c in groups[g]:
            u = units[c.name]
            md.append(f"### `{c.name}`: {u}, {c.kind}, {c.note}")
            rst = f"`{c.reset}`" if c.reset else "VCC"
            if c.kind == "INV":
                node = fmt_node(c.trig)
                if g == "rom" and c.name.startswith("n"):
                    node = f"ROM bit line `{c.name[1:]}`" + (f" + {node}" if c.trig else "")
                md.append(f"- TRIG+THR = {node}")
            else:
                md.append(f"- TRIG = {fmt_node(c.trig)}")
                md.append(f"- THR = {fmt_node(c.thr)}")
            md.append(f"- RST = {rst}")
            md.append("")
    (ROOT / "NETLIST.md").write_text("\n".join(md), encoding="utf-8")
    return n_chips, len(chips) + 2, p.total("D") - 1


def pc_names():
    return [f"PC{i}" for i in range(BITS)]


# --------------------------------------------------------------------------

def load_programs():
    return {f.stem: assemble(f.read_text(encoding="utf-8"))
            for f in sorted((ROOT / "programs").glob("*.asm"))}


def main():
    if len(sys.argv) > 1:
        rom = assemble(Path(sys.argv[1]).read_text(encoding="utf-8"))
        sw = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0
        sim = Sim(rom, random.Random(0))
        sim.set_switches(sw)
        sim.reset()
        ref = (0, 0, 0)
        for cyc in range(40):
            pc, a, c = sim.state()
            print(f"{cyc:3}  PC={pc:2}  A={a:04b} ({a:2})  C={c}  ins={rom[pc]:02X}")
            sim.step()
            ref = reference_step(ref, rom, sw)
            assert sim.state() == ref
        return

    rng = random.Random(1234)
    progs = load_programs()
    tests = list(progs.values()) + [[rng.randrange(256) for _ in range(16)] for _ in range(40)]
    for rom in tests:
        check(rom)
    print(f"OK: {len(progs)} demo + 40 random programs x 4 random-delay runs x 40 cycles "
          f"match the ISA model; clock phases never overlapped")

    chips, wl = build([0] * 16)
    n_pkg, n_timers, d = write_netlists(chips, wl)
    print(f"{n_timers} timers in {n_pkg} x 556, {d} logic diodes -> NETLIST.md, netlist.csv")

    import drawings
    print(f"{len(drawings.write_all())} drawings -> docs/")


if __name__ == "__main__":
    main()
