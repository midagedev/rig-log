# The 3090 goes back in: a clean reseat, a fan curve that was late rather than lazy, and three instruments that were lying

**2026-09-17 23:07 – 2026-09-18 00:25.** The 24 GB card that came out on
2026-09-17 to be sold is back in the machine, in the same slot. This entry is
what its second first-night said: the reseat check, the fan curve that now runs
as machine state on both cards, and the three measuring instruments that turned
out to be wrong while we were using them.

**The 09-17 entry's closing section, "What the machine is now", is superseded.**
It said one card. The machine has two again as of this boot; nothing else in
that entry changes.

## The reseat, measured under load rather than after it

`tools/gpu-sale-check.sh` ran against the 3090 alone, UUID-pinned, under the
lease, from 23:15:29 — the same battery that was cut at 99.9 % by a power-off on
2026-09-17, so the two runs are comparable.

| | 2026-09-17 (cut) | 2026-09-18 (complete) |
|---|---|---|
| cuda_memtest, 3 passes over 24 GB | rc 0, 27 s, 0 errors | rc 0, 28 s, **0 errors** |
| gpu_burn 30 min, verified | 99.9 %, 0 errors, no verdict line | rc 0, **`GPU 0: OK`** |
| compute | 26.2 TFLOP/s fp32 | 26 351 Gflop/s |
| power | max 421 W | max 421 W |
| die temperature | max 77 °C | max 75 °C |
| kernel Xid / NVRM / AER | 0 lines | 0 lines |
| PCIe link **under load** | not taken | **Gen4 ×16, UESta and CESta all clear** on the card and on root port `40:01.1` |
| torch PCIe bandwidth | not run | H2D 25.5, D2H 27.1 GB/s; fp16 matmul 49.6 TFLOPS |

The verdict line is the one the last run never got to print. The link row is the
one that matters for a reseat: it was taken at 23:18 with the burn at full
power, not from the idle snapshot either side, and it says the card negotiated
16 GT/s ×16 with every error bit clear.

What this does **not** test is the question the card left open. Both of its
hangs had the same fingerprint — a second CUDA context arriving on a card
already under load — and reseating into the same slot cannot speak to that. The
ranked table in the 2026-09-17 entry still stands, and none of its tests have
been run.

One thing the kernel log gave up while we were reading it: this firmware does
not hand AER to the OS at all. Every boot logs
`acpi PNP0A08:0x: _OSC: platform does not support [AER LTR DPC]` for all four
domains. A quiet `dmesg` on this board therefore means "the kernel was never
told", not "nothing happened" — which is why the register reads through `lspci`
are the instrument here and not a convenience.

## The card's own fan curve is late, not lazy

The first reading looked like laziness: 63 °C and the blower at 30 %. The 1 Hz
witness said something more specific. Reading the fan column against the
temperature column for the first four minutes of the burn:

| time into load | die | fan the card chose |
|---|---:|---:|
| idle | 32 °C | 0 % (zero-RPM) |
| +3 s | 44 °C | 30 % |
| +46 s | **64 °C** | **31 %** |
| +90 s | 73 °C | 50 % |
| +4 min | 75 °C | 75 %, still climbing 1 % at a time |
| +30 min | 75 °C | 80 % |

It holds 30 % to 64 °C and then integrates its way up one point at a time,
pinning the die at 75 °C while the blower catches up over half an hour. The
steady state is fine; the transient is where the heat goes. This is the same
shape the A6000 showed on an LTX-2.5 denoise on 2026-09-16, where its own curve
took 3.7 minutes to reach 100 % and the die sat up to 5 °C above the target it
was aiming at.

Throttling during all of this was `SW Power Cap`, continuously, at a 420 W limit
that is also the card's default. The board would allow 470 W. Raising it is not
interesting: the power sweep of 2026-09-15 measured 47 % less power costing 15 %
of the rate, so 420 W is already deep into diminishing returns. **A fan curve on
this card buys thermal margin, not throughput**, and the entry says so rather
than implying otherwise.

## The curve, and what it actually bought

`configs/gpu-fan.service` now runs both cards' curves as machine state — one
unit, one daemon, one curve per card, because the two cards do not share a
target. The curves top out at the temperature each card was measured to settle
at under full power: 75 °C for the 3090, 80 °C for the A6000. The card treats
that temperature as somewhere to sit; the curve treats it as a line not to
reach.

Matched against the same load, three minutes of `gpu_burn` either side:

| | card's own curve | our curve |
|---|---:|---:|
| max die | 75 °C | **72 °C** |
| max fan | 71 % | 72 % |
| max power | 420 W | 420 W |

Three degrees for the same peak fan speed. The win is not a louder blower, it is
the same blower arriving earlier.

Then ten minutes with **both cards burning at once** — the closest this machine
gets to the 2026-09-16 condition that took both cards off the bus, and the
realistic worst case for case air:

| | RTX 3090, managed | RTX A6000, own curve |
|---|---:|---:|
| max die | 77 °C | **88 °C** |
| mean die | 72.3 °C | **83.9 °C** |
| mean fan | **88.5 %** | 66.4 % |
| mean SM clock | 1574 MHz | 1396 MHz |
| max power | 421 W | 301 W |
| SW thermal slowdown | — | **500 s of 600 — 83 % of the run** |

The 300 W card ran 11 °C hotter than the 418 W card and answered with 22 points
less fan, and spent five sixths of the run with its clocks cut for heat. That
is the measurement that turned a 3090 fan round into a both-cards one. The
3090's own 77 °C is five degrees above its solo 72 °C, which is the A6000's
300 W arriving in its intake — the curve absorbed that by going to 98 %, which
is what topping out at 75 °C is for.

Nothing was logged: kernel delta 0 lines, and the AER registers of both cards
and both root ports byte-identical before and after.

Two things about fans on this box that were assumed and are now measured.
NVML fan control **does** work on the GeForce — both channels, policy flipping
`auto`→`manual`, readback converging over about ten seconds. And a manual 0 is
not silence on **either** card: NVML accepts it, reports it set, and the fan
holds 30 % for as long as anything but the card owns it. Zero RPM exists only
under the card's own control. `gpu-fan-curve.py` grew `--auto-below` to hand the
fan back for exactly that case, and then the user's call was that a fan turning
slowly at idle is not worth carrying a second mode for — so the shipped unit
runs in one state, manual, always, with a floor of 30 % that is the hardware's
floor anyway. The option stays because the measurement behind it is real.

`ExecStopPost` closes the case a daemon cannot: SIGKILL to the unit's main
process and its python child restored both channels to the card's curve and the
unit restarted five seconds later. That was run, not reasoned.

## Three instruments that were lying while we used them

None of these changed a conclusion, and all three would have.

**The report called a link downclock an AER change.** `REPORT.md` compared the
whole `aer-before`/`aer-after` snapshot, which carries `LnkSta:` as well as the
error registers. An idle card links at 2.5 GT/s and a card fresh off a burn at
16 GT/s — the GPU's own downclocking, already investigated and struck as a
non-finding on 2026-09-16 — so a card with every error bit clear reported
`CHANGED / CHECK`. On a sheet someone else reads, a row that cries wolf on
healthy hardware is worse than no row. The comparison now looks only at
`UESta`/`CESta`, names the bit that moved, and reports the link as its own state
row. [`tools/gpu-check-aer-gate.py`](../tools/gpu-check-aer-gate.py), 5 cases,
lifted out of the shipped script so reverting it fails the gate.

**The witness outlived its own run and moved the numbers.** The runner
backgrounded a shell *function*, so `$!` named a subshell rather than
`nvidia-smi`; bash normally exec-replaces a single-command subshell, but a
script with a trap set does not get that optimisation. `kill -TERM $WPID` killed
the wrapper. The witness was still writing at 1 Hz thirty-three minutes later,
three minutes after the runner printed `GPUCHECK_DONE`, and every idle row it
added dragged the report's "power under burn" mean down — 412 W when the report
was first written, 390 W when it was regenerated, from the same run. The runner
now spells out `nvidia-smi`, asserts `/proc/<pid>/comm` is the program before
trusting the pid, and says so at cleanup when a pid survives SIGTERM — reading
the process state rather than `kill -0`, which an unreaped child answers as a
zombie. This is the third time on this machine that a pid has named the wrapper
instead of the program.

**A fan tool documented behaviour its own code did not have.**
`gpu-fan-curve.py` told the reader to use `--floor 0` for a zero-RPM card, while
`target()` is flat below the curve's first point and `max(want, 0)` therefore
returned the first point's 35 % at a 33 °C idle. The decision moved into one
function, `command(curve, floor, temp)`, so a gate can ask it without a GPU;
below the first point the floor is now the command.
[`tools/gpu-fan-curve-gate.py`](../tools/gpu-fan-curve-gate.py), 15 cases, both
shipped curves. Worth saying plainly: that gate tests arithmetic, and arithmetic
is not the effect — it was green while the hardware was still pinning the fan at
30 %, and only a readback on the card found that.

## Open, and narrowed

The `0x400` in the throttle-reason column, seen on both of this card's battery
runs and never decoded, is **`Reliability`** — read by sampling the hex and
nvidia-smi's named booleans at the same instant, which is the only way this
driver names a bit. It appears for about thirty seconds at the start of
`cuda_memtest` at 38–49 °C, never under `gpu_burn`, and the SM clock is 1980 MHz
while it is set, so nothing visible is being cut. The other bit in the `0x600`
that appeared alongside it is `Board Limit` **by position in the same named
list, which is a derivation and not a measurement** — it did not reproduce.

The `SW Thermal Slowdown` counter and the reason bits disagree on the 3090, and
that is unresolved. The counter read 5.0 s at 23:33 and was not moving across
three samples; by 23:58 it read 476 s. Somewhere in the second half of a burn
whose reason column said `0x4` and nothing else, and whose die never passed
75 °C, the card was counting thermal slowdown. One of the two instruments is
measuring something other than what its name says, and this entry does not know
which.

Hotspot and memory junction remain unmeasured, and now with a reason not to try
the cheap route again: `nvmlDeviceGetFieldValues` returns `NOT_SUPPORTED` for
`NVML_FI_DEV_MEMORY_TEMP` and for every `*_TLIMIT` field on this card and
driver. The `gddr6` BAR0 reader is the only route. The curves above are driven
by the die edge sensor and nothing else, which on a GDDR6X card is not
obviously the binding axis.

## The A6000 curve, measured on somebody else's five-hour load

The vocoder session that trains on this box overnight sent its own numbers the
next morning, and they are better evidence than our ten-minute burn because the
load is real and it ran for five and a quarter hours. Their per-60 s rows, read
from `/webuta/logs/voc-thermal.log`:

| | 2026-09-16, card's own curve | 2026-09-18, this unit |
|---|---|---|
| die | **87 °C** | **77–78 °C** |
| fan | 72 % | **91–93 %** |
| power | 292.0–292.4 W | 294.6–297.2 W |
| SM clock | 1650–1710 MHz | 1740–1860 MHz |
| `SW Thermal Slowdown` counter | accruing, ~54 % duty | **500 539 606 µs, unchanged across 5 h 16 m** |

That frozen counter is the same integer our dual burn left at 00:18. It did not
advance by a microsecond for the whole run.

Ten degrees for about twenty points of fan, on a production workload. Note also
that the card's own curve does reach 72 % at 87 °C given hours — our ten-minute
burn caught it at 66 % because it was still climbing, which is the same "late
rather than lazy" shape as the 3090 and is the reason a short burn understates
the factory curve's steady state.

**And the throughput went down.** Their checkpoints land 64 minutes apart at
1.042 steps/s, against 1.083 when the card was throttled half the time — about
4 % slower with higher clocks and no thermal slowdown at all. So on this
workload the curve bought temperature and nothing else, exactly as the burn
predicted for the 3090, and the SM clock was not what was limiting it. Their
conclusion, which we agree with: a power-limit sweep on their account would not
tell them anything about their training rate.

That session had attributed the eleven degrees to the slot move and to the 3090
being out. Both are wrong as of this entry — the 3090 was reseated at 23:07 the
night before and burned at 421 W for forty minutes of it — and the correction
matters for them rather than being pedantry, because what they actually gained
is a systemd unit somebody else owns and can stop.

What this is **not** is a matched pair: the two rows differ by a fan curve, by
two days, and by a neighbour card that is present in the later one. The single
variable version is cheap and is the next thing worth doing — the same load with
`systemctl stop gpu-fan` on one arm — and it needs that session to be stopping
anyway rather than us taking its card time.

## A fourth instrument, and this one was mine

The unit above shipped with a hole in it, and a peer session found it eight hours later by
polling through a `systemctl stop` I ran at 06:01:23. Their rows, ten seconds apart, A6000
fan and die under a 296 W training job:

| | unit state | fan | die |
|---|---|---:|---:|
| 06:02:21 | `deactivating` | 32 % | 60 °C |
| 06:02:41 | `deactivating` | 32 % | 73 °C |
| 06:02:51 | `deactivating` | 32 % | 79 °C |
| 06:03:01 | `failed` | 52 % | 83 °C |

Nineteen degrees with the fan pinned, and it only started moving once systemd gave up.

The mechanism: `ExecStart` ran the daemon under `uv run`, so systemd's main pid was `uv` and
the daemon's own SIGTERM handler never fired — its `restored N card(s)` line is absent from
the journal of every stop this unit ever had. systemd waited the full 90-second default
`TimeoutStopSec`, SIGKILLed both processes, and the unit ended `failed`. The fans came back
only because of the `ExecStopPost` belt added the day before for the SIGKILL case. The belt
was carrying the whole load and nobody knew.

The part that matters more than the stop: **while the daemon is not processing its loop, the
fan stays in `policy=manual` at its last commanded percent, and the card's own curve cannot
intervene while manual is held.** A stalled controller holding a manual fan is worse than no
controller — the factory curve would have been ramping through that entire climb. And the
hazard is not confined to stopping: `Restart=always` covers a daemon that *exits* and does
nothing for one that *hangs*, in which case the fan stays frozen at a stale percent under a
rising load with no line in anybody's log.

Three changes, and the point of listing them separately is that each closes a different part:
`ExecStart` is now the venv's python directly so the main pid is the daemon and SIGTERM
reaches it; `TimeoutStopSec=10` so even a wedged daemon reaches `ExecStopPost` in seconds; and
`Type=notify` with `WatchdogSec=30`, so a hung daemon is killed and restarted rather than
holding a manual fan forever — which bounds the stale window to about forty seconds instead of
unbounded. `sd_notify` is a datagram to `$NOTIFY_SOCKET` and a no-op outside systemd, so it
adds no dependency.
[`tools/gpu-fan-stop-check.sh`](../tools/gpu-fan-stop-check.sh) asserts all three: the unit
reaches `inactive` rather than `failed`, within ten seconds, with no fan left in manual. It
prints the milliseconds rather than a verdict alone, because "it works now" is not a number.

Two things worth saying plainly about this one. It was found by someone else's instrument, not
ours — our own gates test the arithmetic of the curve and the effect of a SIGKILL, and neither
looks at what happens during a stop. And it is the second time in two days that a gate here was
green while the hardware was doing something else: the fan gate passed while the card was
pinning a commanded 0 % at 30 %, and the SIGKILL test passed while an ordinary stop was taking
ninety seconds. An effect that is only visible on the card has to be read on the card.

## Housekeeping

A lease held by this session from 23:46 to 00:25 delayed the midnight vocoder
run by about half an hour, at the user's request. The crontab was not edited:
the launcher waits up to eight hours on a live lease and ignores one whose pid
is dead, so a delay expressed as a lease fails open if the session holding it
dies — which is the opposite of the 2026-09-16 failure, where a stale lease cost
a peer its night. The launcher logged `held by a peer session … waiting` every
five minutes and started on release, exactly as designed.

That run is also the first real use of the A6000 curve, so its thermal numbers
are the first on this machine taken with a fan curve in place.
