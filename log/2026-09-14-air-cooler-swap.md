# The AIO comes out, an air cooler goes in

**2026-09-14, evening.** The NZXT Kraken AIO that has cooled the 5975WX since
the build was replaced with an ARCTIC Freezer 4U-M tower air cooler on the CPU_FAN header (model name added 2026-09-15). The
reason is in the thermal guard's own log from three hours earlier: at
17:00, during the threshold-sweep window at the 2.7 GHz cap, it wrote
`warn cpu=89C` twice with the coolant in the high forties — a loop that no longer
moved the heat it took in. The swap was the user's; the measurements after
it are below.

## What the new cooler does under load

Same clock cap (2.7 GHz, `cpu-clockcap` re-applied at boot), same room.
Temperatures are k10temp `Tctl`, sampled every 10 s; clocks are the mean of
all 64 threads' `/proc/cpuinfo` MHz.

| load | Tctl | mean clock | note |
|---|---:|---:|---|
| idle after boot | 30–33 °C | 1.8 GHz | |
| `yes` × 64, 40 s | 33.6 °C peak | — | light integer load |
| three concurrent 500-token decodes on the serving profile (2 min) | 39 °C peak | 2.3–2.5 GHz | 21 tok/s each; GPUs 56 / 49 °C |
| `stress-ng --cpu 64 --cpu-method matrixprod`, 240 s | 41 → 43 °C, flat from 130 s | 2.694 GHz throughout | no throttling |
| 20 s after the stress ended | 37 °C | | 35 °C at 60 s |

The old loop's ceiling for the same cap was the 88–89 °C warnings above;
the 59 °C coolant guard that was raised earlier today was a symptom of the
same thing. Forty-three degrees under a four-minute all-core stress means the
2.7 GHz cap is no longer a thermal necessity — it stays because decode is
memory-bound and the cap costs nothing (WKS-22), but the 3.6 GHz
recording-only mode can now be measured for how long it holds rather than
whether it holds.

## What changed for the instrumentation

`liquidctl` reports no device: the air cooler is a plain PWM fan, not a USB
pump. The thermal guard keeps working on CPU and GPU temperature (its
liquidctl block is conditional), but every window script's `cool()` gate
read the coolant temperature and now waits its full timeout before every
arm; those gates move to `Tctl`. Fan RPM does not come from the Super I/O on
this board — all seven `nct6798` fan channels read 0 while five are driven —
but from the BMC over in-band IPMI, `ipmitool sdr type fan`: CPU_FAN 2200,
SOC_FAN 2700, CHIPSET_FAN 2500 RPM, with a 1200 RPM lower-critical
threshold on CPU_FAN. Details and the two Linux drivers that do not cover
this board are in [`docs/wrx80e-bios-setup.md`](../docs/wrx80e-bios-setup.md).

One correction found on the way: the DIMMs are Samsung M378A4G43AB2-CWE,
2Rx8 UDIMMs with no error correction (`dmidecode`), not the ECC modules the
README claimed; struck there.
