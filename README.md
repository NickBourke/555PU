# 555-PU — a 4-bit CPU made of 555 timers

A deliberately tiny CPU where **every active part is a 555 timer**. The rest of
the board is diodes and resistors. It has a program counter, a 16-word program
ROM, a 4-bit accumulator, a ripple-carry adder, a carry flag and conditional
jumps.

| | |
|---|---|
| Data width | 4 bits (accumulator `A`, carry flag `C`) |
| Program | 16 × 8-bit words, diode matrix or DIP switches |
| Instructions | `LDI`, `ADD`, `JMP`, `JC`, `NOP` (and combinations of them) |
| 555s | **58**: 56 logic + astable clock + step-button debouncer (29 × 556 duals) |
| Other parts | ~715 small-signal diodes (1N4148) + one per 1-bit in the program, ~190 resistors |
| Supply | 9 V, CMOS 555s (TLC555 / LMC555 / ICM7555, or TLC556 duals) |
| Speed | anything from single-step to a few kHz; run it at 1–10 Hz to watch the LEDs |

`sim/cpu555.py` is the source of truth. It generates the whole netlist, simulates
it one 555 at a time with random gate delays, checks the result against a plain
model of the instruction set, and writes [NETLIST.md](NETLIST.md), the wiring list.

```
python sim/cpu555.py                        # run the tests, regenerate NETLIST.md
python sim/cpu555.py programs/countdown.asm # trace a program
```

---

## 1. Instruction set

Every instruction is one byte. The top four bits are control lines that go
straight to the hardware with no decoder. The bottom four bits are the immediate.

```
 bit  7    6    5    4    3 2 1 0
     AW  ADD   J   CND    IMM
```

| bit | when set |
|---|---|
| `AW`  | write the accumulator and carry flag this cycle |
| `ADD` | `A ← A + IMM`, `C ← carry out` (otherwise `A ← IMM`, `C ← 0`) |
| `J`   | jump to `IMM` ... |
| `CND` | ... but only if `C` is set |

| mnemonic | hex | effect |
|---|---|---|
| `NOP`     | `00` | |
| `LDI n`   | `8n` | `A ← n`, `C ← 0` |
| `ADD n`   | `Cn` | `A ← A + n`, `C ← carry` |
| `JMP n`   | `2n` | `PC ← n` |
| `JC n`    | `3n` | `if C: PC ← n` |
| `ADD n \| JMP n` | `En` | both at once (the jump tests the *old* `C`) |

Subtract by adding the two's complement: `ADD 15` is `A − 1`. It leaves `C = 1`
unless `A` was 0, so it doubles as a "was zero?" test. To halt, jump to yourself.
`A`, `C` and `PC` go to LEDs; the accumulator is the output.

```asm
; countdown.asm: show 9, 8, ... 0 on the LEDs and stop
LDI 9
ADD 15      ; A = A - 1, C = 0 only if A was already 0
JC 1
LDI 0       ; A went 0 -> 15; put it back
JMP 4       ; halt
```

More in [programs/](programs/): `counter`, `knight_rider`, `add_overflow`.

---

## 2. Making logic out of a 555

A 555 is two comparators and an SR flip-flop. That is enough to build every
part of a computer.

```
            ┌───────────┐
  pin 2 ────┤ < 1/3 Vcc ├──► SET   (wins)        output (pin 3) high
  pin 6 ────┤ > 2/3 Vcc ├──► RESET               output low
  pin 4 ────┤   low     ├──► force output low (overrides everything)
            └───────────┘          between 1/3 and 2/3: hold
```

The design uses a 555 in only two ways:

* **INV.** Pins 2 and 6 are tied together as one input. Low in gives high out,
  high in gives low out. It is a Schmitt-trigger inverter that restores clean
  logic levels.
* **LATCH.** Pin 2 and pin 6 are driven separately: pin 2 low sets the output,
  pin 6 high resets it, and anything else holds it. This is one bit of memory.

There are no other gates. All logic is **diode-resistor logic** placed in front
of those pins:

```
 555 outputs ──|◄── AND node ──|►──┐               (AND: diode cathodes to inputs,
 555 outputs ──|◄──┘  (100k↑)      ├── OR node ──► pin 2 / pin 6     100k pull-up)
 555 output  ───────────────|►─────┘   (1M↓)       (OR: diode anodes from terms,
                                                     1M pull-down)
```

**The one design rule:** between two 555s a signal goes through at most one
diode-AND and then one diode-OR. That is a sum of products, so any boolean
function fits. A deeper diode chain loses a little voltage at each level, so
this rule keeps levels within the 555's thresholds. Each AND input must be a
555 output, so every literal is available in both polarities: `X` and `nX`.
`nX` is an inverter 555 driven by `X`.

## 3. Registers: next-state logic folded into the latch

Each state bit (`PC0–3`, `A0–3`, `C`) is a master-slave flip-flop built from two
555 latches, plus one inverter that supplies `nX`. That is **3 × 555 per bit**.

The design saves parts here. A latch needs a "set when" network on pin 2 and a
"reset when" network on pin 6. Both are sums of products, so **the next-state
logic is wired straight into the master's pins.** There is no separate adder
output, multiplexer or incrementer. Those functions are diode terms on the
latch inputs.

```
master m  (stores NOT x):  pin 2 = OR( x_next terms…, nMEN )          → low  ⇒ m = 1
                           pin 6 = OR( each x_next term · MEN )       → high ⇒ m = 0
slave  x:                  pin 2 = OR( m, nSEN )                      → low  ⇒ x = 1
                           pin 6 = AND( m, SEN )                      → high ⇒ x = 0
                           pin 4 = nRST
```

The master stores the inverted bit so the slave can use the master's output
directly, with no inverter in between.

The next-state functions (`x_next`) that get folded in:

| bit | x_next (sum of products) |
|---|---|
| `A[i]` | `AW·nADD·I[i]` + `AW·ADD·(odd-parity minterms of A[i], I[i], C[i])` + `nAW·A[i]` |
| `C` | `AW·ADD·(A3·I3 + A3·C3 + I3·C3)` + `nAW·C` |
| `PC[i]` | `taken·I[i]` + `not_taken·(PC + 1)[i]`, with `taken = J·nCND + J·C`, `not_taken = nJ + CND·nC` |

When `AW = 0`, the `nAW·A[i]` term feeds the bit back to itself, so the register
holds. The master is never clock-gated. (An earlier gated version failed in
simulation: after power-up a gated master kept its random value instead of the
reset value.)

## 4. Adder

The adder ripples a carry through bits 0–3. The sum bits need no 555s because
they are folded into the `A` latches as above. Each carry between bits needs
two 555s, because the next bit's terms need both `C[i]` and `nC[i]`:

```
nC[i+1] = INV( A·I + A·C + I·C )        C[i+1] = INV( nA·nI + nA·nC + nI·nC )
```

`C1`, `C2` and `C3` take **6 × 555**. The carry out of bit 3 goes straight into
the carry-flag latch.

## 5. Program ROM

* **Decoder:** 16 word lines, each a 4-diode AND of `PC`/`nPC` (10k pull-ups,
  because each word line drives up to 8 bit lines).
* **Matrix:** 8 bit lines, each a diode-OR. Fit a diode from word `n` to bit `b`
  wherever that bit is 1. For a reprogrammable ROM, put a DIP switch and a diode
  at all 128 crossings.
* **Restore:** decoder plus matrix is already one AND and one OR, so each bit
  line goes into an inverter 555 (`nI0`, `nAW`, …). A second inverter gives the
  true polarity. That is **16 × 555**.

## 6. Clock: interlocked two-phase

A master-slave flip-flop must never have both latches transparent at once. The
simulator found this race in the naive version, where `CLK` and `nCLK` came
from a pair of inverters. A slave output such as `A3` feeds the master's diodes
directly. It could change during the one gate delay of `CLK`/`nCLK` overlap and
corrupt the master.

The fix is a non-overlapping clock in which each phase is interlocked on the
other phase's *last* signal:

```
nSRC = INV(SRC)
nMEN = INV( SRC · SOFF )   ← pin 4 = nRST     MEN = INV(nMEN)   MOFF = INV(MEN)
nSEN = INV( nSRC · MOFF )                     SEN = INV(nSEN)   SOFF = INV(SEN)
```

The masters open only after the slave's chain has reported closed (`SOFF`), and
the slaves open only after `MOFF`. This holds for any gate delays. It costs
**7 × 555**. `SRC` is a 555 astable (pot plus 1 µF for about 1–10 Hz) or a 555
wired as an SR latch behind an SPDT push-button for single-stepping, chosen with
a RUN/STEP switch.

**Reset:** `nRST` (button plus 10k/10µF power-on RC) goes to pin 4 of every
slave and of `nMEN`. All state clears to 0, and the masters are held open, so
they already hold the result of instruction 0. On release, the next clock edge
executes it.

## 7. Electrical notes

* **Use CMOS 555s** (TLC555, LMC555, ICM7555, or TLC556 duals) at **9 V**.
  Rail-to-rail outputs and near-zero input current make diode logic easy: the
  thresholds are 3 V and 6 V, an OR output high is about 7.5 V and an OR output
  low is about 0 V. A bipolar NE555 output only reaches about Vcc − 1.7 V. If you
  must use NE555s, run them at 12 V and recheck the resistor values.
* Resistors: 100k AND pull-ups, 1M OR pull-downs, 10k word-line pull-ups. The
  worst fan-out (`PC0`/`nPC0`) sinks about 9 mA, well within a TLC555's 100 mA.
* Fit 100 nF across the supply at every chip and 10 nF from pin 5 to ground.
  Pin 7 is unused. Pin 4 goes to Vcc except on the slaves and `nMEN`.
* LEDs on `A0–3`, `C` and `PC0–3`: high-efficiency LEDs with 4.7k series
  resistors.

## 8. Parts summary

| block | 555s |
|---|---|
| Clock interlock | 7 |
| Astable + step debouncer | 2 |
| ROM restore (8 bits × 2) | 16 |
| Carry chain (3 × 2) | 6 |
| Registers: PC, A, C (9 bits × 3) | 27 |
| **Total** | **58** |

The full per-pin wiring, every diode term for every latch, is in
[NETLIST.md](NETLIST.md).

## 9. Verification

`sim/cpu555.py` models each 555 exactly as above: trigger wins, then threshold,
then hold, with pin 4 overriding both. Diode networks are ideal ANDs and ORs.
Every 555 gets a random 1–4 tick delay on each transition, and every latch
powers up in a random state. The tests run the four demo programs and 40 random
16-byte ROMs, 4 delay seeds each, 40 cycles each, and compare `PC`, `A` and `C`
with the ISA model after every cycle. All of them pass.

The simulator does **not** model analog behaviour: diode drops, resistor
loading, or noise near the 1/3 and 2/3 thresholds. Those are covered only by the
rule of thumb in section 7. Breadboard one register bit and one ROM bit line
before building the whole thing.

## 10. Limitations

There is no RAM. The only memory is `A`, `C` and `PC`, so this is a
programmable finite-state machine, not a Turing-complete computer. A useful
next step would be a few more 555 latches as a second register, plus an `ADD B`
instruction, which would add one bit to the instruction word.
