# BIOS setup for the WRX80E workstation

The board is an ASUS Pro WS WRX80E-SAGE SE WIFI (WRX80, Threadripper PRO
5975WX, two GPUs, 256 GB DDR4). This is the firmware side of running it as an
unattended LLM host: what to set, where each item hides, and why. Menu paths
and page numbers are from the official
[BIOS manual (E18120)](https://dlcdnets.asus.com/pub/ASUS/mb/SocketTRX4/Pro_WS_WRX80E-SAGE_SE_WIFI/E18120_PRO_WS_WRX80E-SAGE_SE_WIFI_BIOS_Manual_EM_WEB.pdf).

Two settings on this board are not where a desktop BIOS keeps them, and both
cost time to find: the CPU power limit is buried in AMD CBS under a name that
is not "power limit", and there is no fan-curve page in the documented menu at
all. Both are resolved below.

## Where each thing lives

| What | Menu path | Manual |
|---|---|---|
| CPU power limit (PPT / cTDP) | Advanced → AMD CBS → NBIO Common Options → SMU Common Options | p.53 |
| Turn boost off in firmware | Advanced → AMD CBS → CPU Common Options → Core Performance Boost | p.39 |
| Large-VRAM mapping for 2 GPUs | Advanced → PCI Subsystem Settings → Above 4G Decoding | p.25 |
| MMIO aperture for above-4G | Advanced → AMD PBS → Mmio Above 4G Limit | p.35 |
| Auto power-on after outage | Advanced → APM Configuration → Restore AC Power Loss | p.34 |
| Wake-on-LAN | Advanced → APM Configuration → Power On By PCI-E | p.34 |
| BMC / remote KVM | Server Mgmt → BMC Support, BMC network configuration | p.67, 69 |
| Boot watchdog (**not** a hung-OS check — see below) | Server Mgmt → OS Watchdog Timer | p.68 |
| Memory clock | Advanced → AMD CBS → UMC Common Options → DDR4 Common Options → DRAM Timing Configuration → Accept → Overclock [Enabled] → Memory Clock Speed (MEMCLK, half the DDR figure) | p.42 |
| DRAM voltage (does **not** follow the clock on Auto) | Ai Tweaker → DRAM ABCD Voltage / DRAM EFGH Voltage, type the value | p.18 |
| Infinity Fabric clock | **no item on this firmware** — follows the memory clock 1:1 up to 1800 MHz on its own | — |
| Fan curves | not in the BIOS on this board; the BMC drives the headers (CPU_FAN reads a constant 2200 rpm) | — |
| Read-only fan/temp/voltage | Tool → IPMI Hardware Monitor | p.63 |

## CPU power limit — the item that is not called "power limit"

AMD does not expose a "Power Limit" field. The package power ceiling is PPT,
and it lives in **Advanced → AMD CBS → NBIO Common Options → SMU Common
Options** (p.53), not in Ai Tweaker:

- **Power Package Limit Control** — `Auto` uses the fused PPT (280 W on the
  5975WX). Set to `Manual` to expose **Power Package Limit** and enter a lower
  ceiling.
- **cTDP Control** / **cTDP** — the thermal-design-power ceiling, same pattern:
  `Manual` to set a value.

Lowering PPT trades a little all-core clock for a large drop in temperature
and fan noise. For this workload that trade is favourable: CPU-side decoding
is memory-bandwidth bound — the experts are read out of DDR4 at ~116 GB/s
measured, and that is the bottleneck, not core clock — so capping PPT should
cost little throughput while pulling the package well back from the 81 °C
sustained / 91 °C prefill-burst figures in the
[first log entry](../log/2026-09-11-deepseek-v4-moe-offload.md). The exact
tok/s cost at a given cap is **not yet measured**; that is the next bench.

Pair it with **Core Performance Boost → `Disabled`** (AMD CBS → CPU Common
Options, p.39) to pin all cores at base clock. This is the firmware-permanent
form of the `cpufreq/boost=0` the machine was setting from Linux.

## Two GPUs: address space

- **Above 4G Decoding → `Enabled`** (p.25). A 48 GB card and a 24 GB card must
  map above the 4 GB line; without this their BARs do not fit.
- **Re-Size BAR Support → `Auto`** (p.25).
- **Mmio Above 4G Limit → `Auto`** (AMD PBS, p.35; only appears once Above 4G
  Decoding is enabled). If PCIe enumeration misbehaves, `43` is the fallback.
- **SR-IOV → `Disabled`** unless doing GPU SR-IOV.

The Linux counterpart to this is `pci=realloc=off` on the kernel command line,
which this board needs or the 10 GbE ports drop — kept in the private host
notes, not here. It lives in GRUB's config on disk, so changing BIOS settings
does not threaten it, and it is worth not suspecting first: on 2026-09-11 it
was the standing explanation for an outage it had nothing to do with.

The hazard that is real when opening this machine is **PCI renumbering**.
Adding a device changes what sits in front of what: a 4 TB NVMe drive installed
on 2026-09-12 took bus `0x23`, and the 10 GbE controller behind it moved from
`0x24` to `0x25`. Every name derived from that address moves with it. `enp36s0f1` became
`enp37s0f1`, the netplan file went on naming the old one, and the machine came
up with no network and nothing logged, because a netplan stanza naming an
absent interface is silently inert rather than an error. **Match interfaces on
MAC address, never on a bus-derived name.** The config and the check that
asserts it are in
[`configs/01-lan.yaml`](../configs/01-lan.yaml) and
[`configs/netplan-iface-check`](../configs/netplan-iface-check); the full
account is in
[the log entry](../log/2026-09-12-offline-after-a-move-and-an-ssd.md).

## Power and unattended behaviour (APM, p.34)

| Item | Value | Why |
|---|---|---|
| Restore AC Power Loss | `Power On` | comes back by itself after a power blip |
| Power On By PCI-E | `Enabled` | Wake-on-LAN |
| ErP Ready | `Disabled` | Enabled cuts standby power in S5, killing WoL and the BMC |

## Remote recovery: the BMC (Server Mgmt, p.67–70)

This board has an ASMB9-iKVM (ASPEED AST2500) baseboard controller — a full
remote KVM already on the board, no add-in card. It answers even when the host
is powered off, which is exactly what a headless box in another room needs.

- **BMC Support → `Enabled`** (p.67).
- **BMC network configuration → Configure IPV4 support → Lan channel 1**
  (p.69): set **Configuration Address source → `DynamicBmcDhcp`** for a DHCP
  address, or `Static` and fill in the IP. The board has two LAN channels; if
  only one cable is connected, the DHCP setting must be on the channel that
  owns that port, so setting both is safest.
- **OS Watchdog Timer → `Enabled`**, **OS Wtd Timer Policy → `Reset`**
  (p.68), *but only with the OS side in place* — see the correction below.

  > **Corrected 2026-09-12.** This entry used to read "if the OS stops
  > responding, the BMC resets the box on its own." That is wrong, and
  > believing it cost an afternoon. `OS Watchdog Timer` arms a **boot**
  > watchdog: IPMI timer use `OS Load`, a 600-second countdown started at POST,
  > which the operating system is expected to take over or switch off once it
  > has finished booting. It is not a liveness check on a running system —
  > nothing about it notices whether the OS is still responding. With the
  > setting enabled and no OS-side counterpart, a perfectly healthy machine is
  > hard-reset ten minutes after every boot, forever, leaving no shutdown
  > record because a hard reset does not get to write one. That is what
  > happened here, four times, after this guide's own BIOS reset.
  >
  > Keep it enabled **only** if the OS claims the timer. On Ubuntu that means
  > loading `ipmi_watchdog` and setting `RuntimeWatchdogSec` so systemd pets
  > it — the files are in [`configs/watchdog/`](../configs/watchdog), and the
  > whole account is in
  > [the log entry](../log/2026-09-12-bmc-watchdog-reset-loop.md). Doing that
  > gets the thing the old sentence promised: a genuine runtime watchdog that
  > resets a wedged kernel. Without it, set this to `Disabled`.

Set the BMC's clock while in there, or at least know it may be wrong: on this
board it was found eight hours off from the host, which makes the BMC event log
— the one instrument that names a watchdog reset — hard to line up against the
system journal exactly when that matters most.

After first boot: reach the BMC at `https://<its IP>`, default login
`admin` / `admin`, and **change that password immediately** — an unconfigured
AMI BMC left on defaults is an open remote-power-and-console interface on the
LAN. From there: power on/off/reset, live screen (POST codes, boot, kernel
panics), and virtual media, all remote.


### Reading the fans from Linux (2026-09-14)

Only the BMC sees the fan headers. The Super I/O (`nct6798`, driver
`nct6775`) reads voltages and its own temperature inputs fine, but all seven
fan channels report 0 RPM even while it drives PWM 1–5 at 60 %; the tach
lines go to the ASPEED BMC. `asus_ec_sensors` does not list this board and
the DSDT has neither the `ASMX` mutex nor the `BREC` region it needs, and
`asus_wmi_sensors` loads without creating a hwmon device. What works, from
the host, over the in-band IPMI interface:

```
sudo ipmitool sdr type fan          # CPU_FAN 2200 RPM, SOC_FAN 2700, CHIPSET_FAN 2500
sudo ipmitool sdr type temperature  # CPU Temp., LAN Temp., PCIE01 Temp.
sudo ipmitool sensor get CPU_FAN    # lower critical threshold 1200 RPM
```

The BMC's CPU_FAN lower-critical threshold is 1200 RPM, so a stopped or
unplugged CPU fan shows up in the BMC event log on its own; the host-side
thermal guard reads k10temp `Tctl` directly.

## Fans: not in the documented menu

The Tool → IPMI Hardware Monitor page (p.63) is **read-only** — it shows fan
RPM, temperatures and voltages but has no curve editor. The manual documents
no Monitor menu at all, yet the firmware has one: fan curves are under the
**Monitor** menu / the **`F6` Qfan Control** hotkey. This is why fans cannot be
driven from Linux on this board — the headers answer to the ASUS controller,
not to a hwmon the OS can write — and must be curved in firmware.

- Radiator / chassis fans (CHA_FAN): an aggressive curve, ramping early on
  core temperature, because the AIO coolant has little thermal headroom before
  it plateaus.
- The Kraken pump is USB, not a fan header — pinned to 100 % from Linux with
  liquidctl, independent of these curves.

Exact curve points are set against the live graph on the machine and are not
transcribed here yet.

## Memory clock (2026-09-14)

Walked 3200 → 3400 → 3600 → 3666 with a bandwidth probe, a verifying
memory stress, a greedy identity check and three decodes at each stop; the
record is [`log/2026-09-14-memory-clock-3600.md`](../log/2026-09-14-memory-clock-3600.md).
The standing configuration is **Memory Clock Speed 1800MHz (DDR4-3600) with
DRAM ABCD/EFGH Voltage 1.30**. What settled it:

- 3600 passed ten minutes of `stress-ng --vm --verify` at the Auto 1.2 V;
  3666 at 1.3 V returned 139 wrong readbacks with MCE at zero (non-ECC, so
  nothing else would have noticed), and lost 3 % of bandwidth because the
  fabric stays at 1800 MHz. 3733, 3766 and 3800 do not POST.
- Auto DRAM voltage is the SPD 1.2 V regardless of the clock chosen in AMD
  CBS, and it does not move with load — the BMC read 1.22 V idle and under
  stress. The manual item applies: 1.30 reads back 1.29/1.28 V.
- 3600 is the last working step, so it gets the 0.1 V of margin.

## Getting into Setup, and back out of a bad clock

`sudo systemctl reboot --firmware-setup` or `sudo ipmitool chassis bootdev
bios` (one boot only; also works over `lanplus` from outside) both land in
Setup on the next boot. A clock that does not train is recovered with the
**CLR CMOS button on the case** — the BMC web UI has no remote CMOS clear or
BIOS-defaults action.

### After a CMOS clear

Everything resets. The list re-entered on 2026-09-14, in the order it was
found useful:

1. AMD CBS → UMC Common Options → DDR4 Common Options → DRAM Timing
   Configuration → Accept → Overclock Enabled → Memory Clock Speed 1800MHz
2. Ai Tweaker → DRAM ABCD Voltage 1.30, DRAM EFGH Voltage 1.30
3. Advanced → APM Configuration → Restore AC Power Loss = Power On, ErP Ready
   = Disabled
4. Advanced → PCI Subsystem Settings → Above 4G Decoding = Enabled, Re-Size
   BAR Support = Auto (both GPUs must show in `nvidia-smi` afterwards)
5. AMD CBS → DF Common Options → Memory Addressing → NUMA nodes per socket =
   NPS1 (`lscpu` shows one node)
6. Server Mgmt → OS Watchdog Timer = Disabled
7. Left at defaults on purpose: PPT (280 W), Core Performance Boost (Auto),
   Global C-state (Auto), SMT, CSM (Disabled)

## Still to measure

- tok/s at a capped PPT versus the fused 280 W, to pick the cap.
- A clean DDR4-3200 decode row (three single-stream 400-token runs) to close the 3200 → 3600 decode delta; bandwidth is +12.6 %, decode is not yet measured against the same baseline.
