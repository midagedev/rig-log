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
| Auto-reset a hung OS | Server Mgmt → OS Watchdog Timer | p.68 |
| Fan curves | Monitor menu / `F6` Qfan Control (not documented in the manual) | — |
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
notes, not here.

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
  (p.68): if the OS stops responding, the BMC resets the box on its own.

After first boot: reach the BMC at `https://<its IP>`, default login
`admin` / `admin`, and **change that password immediately** — an unconfigured
AMI BMC left on defaults is an open remote-power-and-console interface on the
LAN. From there: power on/off/reset, live screen (POST codes, boot, kernel
panics), and virtual media, all remote.

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

## Still to measure

- tok/s at a capped PPT versus the fused 280 W, to pick the cap.
- The Qfan curve points that hold the package under load once boost is off.
