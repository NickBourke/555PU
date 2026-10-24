"""
555-PU: a 4-bit CPU built from 555 timers, diodes and resistors.

This file is the single source of truth for the design. It:
  1. generates the gate-level netlist (every 555 and every diode network),
  2. simulates it chip-by-chip with random propagation delays,
  3. checks it against a plain ISA reference model,
  4. writes NETLIST.md (the wiring list you would build from).

Logic family ("555-DTL")
------------------------
Every signal that leaves a chip is a 555 output (pin 3). Between two 555s
there is at most ONE diode-AND level feeding ONE diode-OR level:

    555 outputs --|>|-- AND node (pull-up) --|>|-- OR node (pull-down) --> pin 2 / pin 6

A node is therefore described as a list of product terms, each term a list of
literal names (555 outputs). A one-literal term is just a single diode into
the OR node. A node with a single multi-literal term is a bare AND node.

A 555 is used in only two ways:
  INV   - pins 2 and 6 tied together: a Schmitt-trigger inverter.
  LATCH - pin 2 low  -> output high (set, dominates)
          pin 6 high -> output low  (reset)
          neither    -> hold
  Pin 4 (reset) forces the output low on either type.

Usage:  python cpu555.py            run all tests, write NETLIST.md
        python cpu555.py prog.asm   assemble and run a program, print a trace
"""

import random
import sys
from pathlib import Path

BITS = 4

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
# --------------------------------------------------------------------------

OPS = {"NOP": 0x00, "LDI": 0x80, "ADD": 0xC0, "JMP": 0x20, "JC": 0x30}


def assemble(text):
    """One instruction per line. Fields can be combined with '|' as long as
    they share the immediate, e.g. 'ADD 1 | JMP 0'. Comments start with ';'."""
    rom = []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.split(";")[0].strip()
        if not line:
            continue
        word, imm = 0, None
        for part in line.split("|"):
            tok = part.split()
            op = tok[0].upper()
            if op not in OPS:
                raise SyntaxError(f"line {lineno}: unknown op {op}")
            word |= OPS[op]
            if len(tok) > 1:
                v = int(tok[1], 0) & 0xF
                if imm is not None and v != imm:
                    raise SyntaxError(f"line {lineno}: fields need the same immediate")
                imm = v
        rom.append(word | (imm or 0))
    if len(rom) > 16:
        raise ValueError("program longer than 16 words")
    return rom + [0] * (16 - len(rom))


def reference_step(state, rom):
    pc, a, c = state
    w = rom[pc]
    aw, add, j, cnd, imm = w >> 7 & 1, w >> 6 & 1, w >> 5 & 1, w >> 4 & 1, w & 15
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
    def __init__(self, name, kind, pin2, pin6, reset=None, group="", note=""):
        self.name, self.kind = name, kind
        self.pin2, self.pin6 = clean(pin2), clean(pin6)
        self.reset, self.group, self.note = reset, group, note


def build(rom):
    chips = []

    def inv(name, node, group, note="", reset=None):
        chips.append(Chip(name, "INV", node, node, reset, group, note))

    def latch(name, pin2, pin6, group, note="", reset=None):
        chips.append(Chip(name, "LATCH", pin2, pin6, reset, group, note))

    def register_bit(x, xterms):
        """Master-slave flip-flop for state bit x, next-state logic folded in.

        The master stores NOT x so the slave can take its output directly:
          master pin 2 = OR(x terms, nMEN)        low  -> m = 1 (x = 0)
          master pin 6 = OR(each x term · MEN)    high -> m = 0 (x = 1)
          slave  pin 2 = OR(m, nSEN)              low  -> x = 1
          slave  pin 6 = AND(m, SEN)              high -> x = 0
        """
        m = "m" + x
        latch(m, xterms + [["nMEN"]], [t + ["MEN"] for t in xterms],
              "state", f"master of {x} (holds NOT {x})")
        latch(x, [[m], ["nSEN"]], [[m, "SEN"]], "state", f"slave: {x}", reset="nRST")
        inv(n(x), [[x]], "state", f"NOT {x}")

    # ---- clock: interlocked two-phase, non-overlapping ----------------------
    # SRC comes from the astable (RUN) or the debounced STEP latch. Each phase
    # opens only after the other phase's last enable line has gone inactive, so
    # master and slave are never transparent together whatever the gate delays.
    # Reset holds the masters open and the slaves closed (and cleared).
    inv("nSRC", [["SRC"]], "clock", "inverted clock source")
    inv("nMEN", [["SRC", "SOFF"]], "clock", "master enable, active low", reset="nRST")
    inv("MEN", [["nMEN"]], "clock", "master enable")
    inv("MOFF", [["MEN"]], "clock", "master fully closed (interlock)")
    inv("nSEN", [["nSRC", "MOFF"]], "clock", "slave enable, active low")
    inv("SEN", [["nSEN"]], "clock", "slave enable")
    inv("SOFF", [["SEN"]], "clock", "slave fully closed (interlock)")

    # ---- program ROM: 4->16 decoder (word lines) + diode matrix -----------
    pc = [f"PC{i}" for i in range(BITS)]
    word_lines = [[pc[i] if w >> i & 1 else n(pc[i]) for i in range(BITS)] for w in range(16)]
    rom_bits = ["I0", "I1", "I2", "I3", "CND", "J", "ADD", "AW"]
    for b, name in enumerate(rom_bits):
        bitline = [word_lines[w] for w in range(16) if rom[w] >> b & 1]
        inv(n(name), bitline, "rom", f"ROM bit {b} restore (inverted)")
        inv(name, [[n(name)]], "rom", f"ROM bit {b} restore")

    # ---- ALU: ripple adder A + I -------------------------------------------
    carry_in = None
    a_next = []
    for i in range(BITS):
        A, I, C = f"A{i}", f"I{i}", carry_in
        lits = [A, I] + ([C] if C else [])
        odd, cy, ncy = [], [], []
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

    # AW = 0 holds the value: x_next = AW·new + nAW·x  (the master is never gated,
    # so reset leaves every master consistent with its cleared slave)
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
    if not node_value(c.pin2, sig):     # trigger below 1/3 Vcc
        return True
    if node_value(c.pin6, sig):         # threshold above 2/3 Vcc
        return False
    return sig[c.name]


class Sim:
    def __init__(self, rom, rng, dmin=1, dmax=4):
        self.chips, _ = build(rom)
        self.rng, self.dmin, self.dmax = rng, dmin, dmax
        self.sig = {c.name: rng.random() < 0.5 for c in self.chips}
        self.sig.update(SRC=True, nRST=True)
        self.pending = {}
        self.t = 0

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
        raise RuntimeError("circuit did not settle (oscillation?)")

    def word(self, prefix):
        return sum(self.sig[f"{prefix}{i}"] << i for i in range(BITS))

    def state(self):
        return self.word("PC"), self.word("A"), int(self.sig["CF"])

    def reset(self):
        self.sig["nRST"] = False
        self.settle()
        self.sig["SRC"] = True
        self.settle()
        self.sig["nRST"] = True
        self.settle()

    def step(self):
        self.sig["SRC"] = False   # phase 2: slaves copy masters
        self.settle()
        self.sig["SRC"] = True    # phase 1: masters compute next state
        self.settle()


def check(rom, cycles=40, seeds=10):
    for seed in range(seeds):
        sim = Sim(rom, random.Random(seed))
        sim.reset()
        ref = (0, 0, 0)
        assert sim.state() == ref, f"reset gave {sim.state()}"
        for cyc in range(cycles):
            sim.step()
            ref = reference_step(ref, rom)
            if sim.state() != ref:
                raise AssertionError(f"seed {seed} cycle {cyc}: sim {sim.state()} != ref {ref}")


# --------------------------------------------------------------------------
# Netlist report
# --------------------------------------------------------------------------

def fmt_node(terms):
    if len(terms) == 1 and len(terms[0]) == 1:
        return f"wire from `{terms[0][0]}`"
    if not terms:
        return "(pull-down only: always low)"
    return " + ".join("Â·".join(t) for t in terms)


def node_parts(terms, shared_and=False):
    """(diodes, resistors) for one node. Single-literal terms are one diode."""
    if len(terms) == 1 and len(terms[0]) == 1:     # plain wire
        return 0, 0
    if len(terms) == 1 and len(terms[0]) > 1:      # bare AND node
        return len(terms[0]), 1
    d = r = 0
    for t in terms:
        if len(t) == 1:
            d += 1
        else:
            d += 1 if shared_and else len(t) + 1
            r += 0 if shared_and else 1
    return d, r + 1


def write_netlist(chips, word_lines, path):
    diodes = res = 0
    lines = ["# 555-PU netlist", "",
             "Generated by `sim/cpu555.py` â€” do not edit by hand.", "",
             "Notation: `Â·` is a diode-AND (one diode per literal, anodes to the AND",
             "node, cathodes to the 555 outputs named, 100k pull-up to Vcc). `+` is a",
             "diode-OR (one diode per term, anode from the term, cathode to the pin node,",
             "1M pull-down). A literal on its own is a single diode straight into the OR.",
             "`nX` is always the output of an inverter 555 whose input is `X`.", "",
             "## ROM word lines (decoder)", "",
             "Each word line is a diode-AND with a **10k** pull-up (it drives up to 8 bit lines).", ""]
    for w, t in enumerate(word_lines):
        lines.append(f"- `W{w:X}` = {'Â·'.join(t)}")
    diodes += 16 * BITS
    res += 16
    lines += ["", "The 8 ROM bit lines are diode-ORs of word lines: put a diode from `Wn` to bit",
              "line `b` wherever bit `b` of word `n` is 1 (or a DIP switch + diode on every",
              "crossing, 128 of each, to make it reprogrammable).", ""]
    groups = {}
    for c in chips:
        groups.setdefault(c.group, []).append(c)
    titles = {"clock": "Clock", "rom": "ROM output restore", "alu": "Adder carry chain",
              "state": "Registers (A, carry flag, PC)"}
    for g in ["clock", "rom", "alu", "state"]:
        lines += [f"## {titles[g]}", ""]
        for c in groups[g]:
            rst = f", pin 4 = `{c.reset}`" if c.reset else ", pin 4 = Vcc"
            lines.append(f"### `{c.name}` â€” {c.kind} â€” {c.note}{rst}")
            if g == "rom":
                lines.append(f"- pins 2+6 = {'ROM bit line' if c.name.startswith('n') else fmt_node(c.pin2)}")
                if c.name.startswith("n"):
                    res += 1                       # bit line pull-down
            elif c.kind == "INV":
                lines.append(f"- pins 2+6 = {fmt_node(c.pin2)}")
                d, r = node_parts(c.pin2)
                diodes += d
                res += r
            else:
                lines.append(f"- pin 2 = {fmt_node(c.pin2)}")
                lines.append(f"- pin 6 = {fmt_node(c.pin6)}")
                for node in (c.pin2, c.pin6):
                    d, r = node_parts(node)
                    diodes += d
                    res += r
            lines.append("")
    kinds = {}
    for c in chips:
        kinds[c.group] = kinds.get(c.group, 0) + 1
    summary = ["## Parts", "",
               f"- 555 timers: **{len(chips) + 2}** "
               f"({len(chips)} logic + astable clock + single-step debounce latch)",
               "  - " + ", ".join(f"{titles[g]}: {kinds[g]}" for g in titles),
               f"- diodes (logic): **{diodes}** + one per 1-bit in the program",
               f"- resistors (pull-ups/downs): **{res}**", ""]
    lines[4:4] = summary
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return len(chips) + 2, diodes, res


# --------------------------------------------------------------------------

PROGRAMS = {
    "counter": """
        NOP
        ADD 1 | JMP 1   ; add 1 and jump to self: A counts forever
    """,
    "countdown": """
        LDI 9
        ADD 15      ; A = A - 1, C = 0 only if A was already 0
        JC 1
        LDI 0       ; A went 0 -> 15; put it back
        JMP 4       ; halt
    """,
    "knight_rider": """
        LDI 1
        LDI 2
        LDI 4
        LDI 8
        LDI 4
        LDI 2
        JMP 0
    """,
    "add_overflow": """
        LDI 13
        ADD 5       ; 18 -> A = 2, C = 1
        JC 5
        LDI 15      ; skipped
        JMP 3
        ADD 0       ; clears C (2 + 0 has no carry)
        JC 3        ; not taken
        JMP 7       ; halt with A = 2, C = 0
    """,
}


def main():
    if len(sys.argv) > 1:
        rom = assemble(Path(sys.argv[1]).read_text())
        sim = Sim(rom, random.Random(0))
        sim.reset()
        ref = (0, 0, 0)
        for cyc in range(40):
            pc, a, c = sim.state()
            print(f"{cyc:3}  PC={pc:2}  A={a:04b} ({a:2})  C={c}  ins={rom[pc]:02X}")
            sim.step()
            ref = reference_step(ref, rom)
            assert sim.state() == ref
        return

    rng = random.Random(1234)
    tests = [assemble(p) for p in PROGRAMS.values()]
    tests += [[rng.randrange(256) for _ in range(16)] for _ in range(40)]
    for k, rom in enumerate(tests):
        check(rom, cycles=40, seeds=4)
    print(f"OK: {len(tests)} programs x 4 random-delay runs x 40 cycles match the ISA model")

    chips, wl = build(assemble(PROGRAMS["counter"]))
    out = Path(__file__).resolve().parent.parent / "NETLIST.md"
    n555, d, r = write_netlist(chips, wl, out)
    print(f"{n555} x 555, {d} diodes, {r} resistors -> {out}")


if __name__ == "__main__":
    main()
