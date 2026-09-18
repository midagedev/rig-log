# The fault reproduced in 133 seconds, and a second instrument the driver does not touch lost the card too

> ~~The instrument that lost the card *first* was not the driver.~~ That was this
> entry's original title, written before the driver source was read. The driver
> polls for the card's presence, so *first* was never a comparison the witness
> could make; what it did measure is that a path with no PCIe and no NVIDIA
> driver in it lost the card as well.

**2026-09-18, 06:31–07:20.** The one hardware question on this machine with no
answer — why the 3090 fell off the bus on 2026-09-16 — now has a reproducer.
Two ranks of NCCL DDP, one per card, killed it in 133 seconds. The 2026-09-16
occurrence was at 110 seconds. This entry is what the instruments said, what
that changes about the leading hypothesis, and why nothing has been filed
upstream.

The machine's owner authorised the run, having accepted a reboot as its cost.
The interpretation below was agreed in writing **before** the run, with the peer
session that ran the load: a clean fifteen minutes would mean only that this
configuration did not reproduce in fifteen minutes, on one attempt, at this
driver version, while a fault would largely answer the question. That asymmetry
is why the test was worth running, and writing it down beforehand is the only
way it survives a result either of us liked.

## The fault

```
06:32:12  two-rank NCCL DDP launched, one rank per card
06:34:24  NVRM: Xid (PCI:0000:41:00): 79, GPU has fallen off the bus.      <- the 3090
06:34:24  NVRM: Xid (PCI:0000:41:00): 154, recovery action 0x0 -> 0x2 (OS Reboot)
06:34:24  NVRM: Xid (PCI:0000:61:00): 154, recovery action 0x0 -> 0x2 (OS Reboot)   <- the A6000
06:34:24  NVRM: _issueRpcAndWait: rpcSendMessage failed with status 0x0000000f
          NVRM: nvCheckOkFailedNoLog: GPU lost from the bus [NV_ERR_GPU_IS_LOST]
```

`0x0000000f` is `NV_ERR_GPU_IS_LOST`, the same status the 2026-09-16 evening
hang printed. The second Xid 154 is the part that was not predicted: **the
A6000 was marked reboot-required too.** It kept answering `nvidia-smi` at 46 °C
throughout, and `torch.cuda.is_available()` returned False with
`device_count()` 0. This is not "the 3090 was lost", it is "the machine's GPUs
were lost until it reboots".

Two reproductions now, 110 s on 2026-09-16 and 133 s today, **one before the
A6000's slot move and one after**. Whatever this is, the slot is not it.

## The ordering, which is the finding

A witness sampled `nvidia-smi` and the BMC's per-slot PCIe temperature sensors
into the same row, each column tagged with whether it answered. The two probes
run in parallel and share a timestamp — that was a fix made fifteen minutes
before launch, and without it the rows below would have been an artefact of the
witness's own scheduling rather than a measurement.

```
time     ,smi_ok,gf3090_c,gf3090_w,a6000_c,a6000_w,ipmi_ok,pcie01_c,pcie05_c
06:34:18 ,1     ,68      ,372.53  ,76     ,286.53 ,1      ,67      ,75
06:34:24 ,1     ,68      ,382.52  ,75     ,275.02 ,1      ,        ,76
06:34:25   *** alarm: nvidia-smi STOPPED ANSWERING ***
06:34:30 ,1     ,70      ,129.77  ,       ,       ,1      ,        ,70
```

**The BMC lost the card one sample before the driver did**, while `nvidia-smi`
was still returning a full-power 382.5 W reading for it. On 2026-09-16 the
relation ran the other way: `nvidia-smi` could not open either card while the
BMC still read both. So "the BMC answers when the driver cannot" is not a rule
about this hardware; it was one observation, and here the side-band went first.

PCIE01 did not blank for a sample. It read `ns / No Reading` for the whole
thirty-five minutes to the reboot, and came back at 30 °C afterwards.

## Why that sensor matters, and how far the inference goes

The slot sensor is not a thermistor sitting in slot air. Across this run, die
against slot sensor:

| | samples | die range | mean \|die − slot\| | max |
|---|---:|---|---:|---:|
| 3090 / PCIE01 | 35 | 31 → 68 °C | **0.69 °C** | 5 °C |
| A6000 / PCIE05 | 36 | 40 → 76 °C | **0.44 °C** | 3 °C |

Sub-degree agreement across a 37-degree swing would be suggestive on its own.
The ramp is what settles it:

```
06:32:15  die 31   PCIE01 31    29 W
06:32:21  die 32   PCIE01 37    32 W    <- the slot sensor LEADS the die by 5
06:32:44  die 46   PCIE01 41   313 W    <- and trails by 5 on the steepest segment
06:33:05  die 60   PCIE01 60   381 W
```

A board thermistor cannot lead a die into a thermal ramp; heat travels one way.
Excursions in both directions that settle within seconds are two sensors read at
slightly different instants during a fast transient. So the BMC is reading the
GPU's own sensor over an I2C/SMBus side-band — a path that shares no silicon
with PCIe config space and involves the NVIDIA driver not at all.

**The limits of that, stated rather than buried.** This is inference from
behaviour, not from a schematic. It rules out a slot-air thermistor strongly. It
does not distinguish side-band-to-the-GPU from some other on-card sensor path,
and it does not say which bus. An `i2cdetect` on the BMC's bus, or the ASMB9's
documentation, would settle it properly and would outrank everything in this
section.

If it holds, the card stopped answering a path the driver does not touch, and
stopped answering it *first*. That is hard to tell as a story about driver
software. ~~The ordering carries that argument.~~ **Amended the same day**, in
the next section: the driver's side of the comparison is a poll, so *first* is
not a measurement the witness could have made. What survives is that a second,
independent interrogator lost the card at all.

## What Xid 79 actually measures, read from the driver's own source

Every rung of the test ladder below costs a hard reset and somebody standing at
the machine. Reading the code costs nothing, and it turns out the exact source is
available: DKMS keeps `/usr/src/nvidia-615.71.09` on the box, and the matching
tag is published upstream. The installed tree is only the `kernel-open`
interface layer — the resource manager, where all of this lives, ships as a
19.9 MB `nv-kernel.o_binary` — but the two trees agree where they overlap
(`nv-pci.c` and `nv-linux.h` are md5-identical across them), and the single
distro patch only turns off `-fstack-clash-protection` and `-fcf-protection`.
So the code quoted here is the code that ran.

**First, the evidence was nearly not there.** `dmesg-full-at-fault.txt`, taken
during the forensics, begins at 06:56:26 — twenty-two minutes *after* the fault.
4 327 lines of `_issueRpcAndWait: rpcSendMessage failed with status 0x0000000f`
had flooded the kernel ring buffer and pushed the fault window out of it; only
`xid.txt`, grepped in the first minutes, still held the Xid lines. The journal on
this box is persistent, so the window was recovered from `journalctl -k -b -1`
and saved as `dmesg-journal-faultwindow.txt`, and it carries lines the preserved
`dmesg` does not. The rule that follows: **take the fault window from the
journal, never from `dmesg`** — the post-fault RPC flood destroys the ring buffer
faster than anyone gets to it. The recovered window also measures how quiet it
was beforehand: between 06:30:00 and 06:34:23.827 there is **no kernel line at
all**, and then everything arrives inside 700 microseconds.

Now the register. `osHandleGpuLost()`, in
`src/nvidia/arch/nvalloc/unix/src/osinit.c:359`, is the whole of it:

```c
pmc_boot_0 = NV_PRIV_REG_RD32(nv->regs->map_u, NV_PMC_BOOT_0);
if (pmc_boot_0 != nvp->pmc_boot_0)
```

One 32-bit read of BAR0 offset zero, compared against the chip identity cached at
probe. Xid 79 is not an error the GPU raised and not a link event the fabric
reported: **it is the host failing to read the chip's own identity register and
concluding the card is gone.** That matters for how this entry has been reading
its own evidence. The 3090's config space reading all `ff` and the Xid 79 have
been standing next to each other as two facts; they are one phenomenon — a read
to that device returning all-ones — observed in two address spaces. And zero AER
is not evidence against a link event, because this board's firmware denies the OS
AER and the driver's only instrument is the same all-ones read. Nothing in the
stack was positioned to say more than "it stopped answering".

Whether that observation is prompt is the question the ordering finding turns on.
Two paths call it, both reading the same register:

| path | source | when it looks |
|---|---|---|
| opportunistic | `gpu_access.c:1300-1355`, `gpuSanityCheckRegRead` | any register read whose value comes back all-ones re-reads `NV_PMC_BOOT_0`, and if that is invalid too calls `osHandleGpuLost` |
| periodic | `kernel_bif.c:187`, `_kbifCheckIfGpuExists` on `osSchedule1HzCallback` | once a second, `gpuVerifyExistence` compares `NV_PMC_BOOT_0` against `pGpu->chipId0` |

The periodic one is conditional, and the condition is worth checking rather than
assuming: `kernel_bif.c:184` registers it only when
`PDB_PROP_KBIF_CHECK_IF_GPU_EXISTS_DEF` is set and the GPU is not virtual, and the
generated hal table (`g_kernel_bif_nvoc.c:247`) sets that property for a chip list
that contains **GA102** — which is both of these cards. So both were being polled
once a second.

Detection is therefore bounded by one second — but it is a poll, not an interrupt,
and how much faster than a second it actually was is not something this reading
establishes. The opportunistic path only fires on a register read that comes back
all-ones, and on a GSP client the kernel-side RM touches few BAR0 registers on the
hot path: an RPC writes a doorbell and polls a queue in system memory. The 1 Hz
callback may well have been the detector here. The driver learns the card is gone
when it next happens to look. So the witness's
`06:34:24` BMC blank against the `06:34:25` `nvidia-smi` alarm cannot establish
which event came first: one column has up to a second of slack in it, and the
witness's own spacing is coarser than the gap being claimed. The half of that
finding that survives is the half that never depended on ordering — the BMC
reaches the card over a path with no PCIe and no NVIDIA driver in it, and the
card stopped answering that too.

Nor is the RPC flood a second instrument. `_issueRpcAndWait` reports
`rpcSendMessage failed with status 0x0000000f` downstream of a gate at the top of
the send path (`kernel_gsp.c:387`) which returns `NV_ERR_GPU_IS_LOST` from the same
cached property bits, touching no hardware. All 4 327 of those lines are the
driver repeating a conclusion it had already reached.

**Which raises a question this entry had not asked.** The 2026-09-16 *evening*
hang logged `rpcSendMessage failed 0xf` with **no Xid 79 at all**, and
`log/2026-09-17-the-3090-comes-out.md` says the two hangs "share two facts". On
this reading they may not share the important one: today's fault is BAR0 having
stopped answering, and that gate can return the same status with BAR0 still
readable, if something else cleared the connected bit — `osHandleGpuLost` returns
early and emits nothing when it has already run, and `osIsGpuShutdown` reaches the
same `GPU_IS_LOST` return by a different route. So the evening hang and today's
fault are **not established to be the same driver-level class**, and the #1134
family that rung 3 of the ladder targets was matched to the evening one. That is an
open question, not a conclusion; settling it needs the evening hang's own journal
read the same way this one was.

`_threadNodeCheckTimeout: API_GPU_ATTACHED_SANITY_CHECK failed!`, repeated 22
times in the log, is not a second instrument agreeing. The macro
(`g_gpu_nvoc.h:6267`) reads three cached property bits and touches no hardware,
and `osHandleGpuLost` had already cleared the first of them through
`gpuSetDisconnectedProperties`. Those are threads noticing a flag, not
observations.

## Why the A6000 was told to reboot

This is the part the source settles outright. The chain from the one card's fault
to the other card's Xid 154 is four links, each in the tree at this tag:

`krcRcAndNotifyAllChannels_IMPL` notifies every channel of critical error 79.
For each one, `krcErrorSetNotifier_IMPL` (`kernel_rc_notification.c:260`) runs a
workaround that is commented as such — *"WAR bug 4503046: mark reboot required
when any UVM channels receive an error"* — and calls
`sysSetRecoveryOsRebootRequired` when `pKernelChannel->bUvmOwned`. That setter
puts the flag on **`pSys`, the system object, not on a GPU**, and queues
`_sysRefreshAllGpuRecoveryAction`, which walks every GPU in the box through
`gpumgrGetNextGpu`. Each one lands in `gpuRefreshRecoveryAction`
(`gpu.c:7311`), where the system flag is tested *before* any per-GPU condition,
and each logs its own Xid 154.

**So the A6000's Xid 154 is one system-wide flag printed once per card, and says
nothing about the A6000's health.** This entry, the 2026-09-16 one, and
`docs/machine-changes.md` have all read "Xid 154 on both cards" as both cards
being affected. ~~Both cards were marked for OS reboot.~~ One card fell off the
bus; the other was told to reboot because the machine was.

One thing the source does not settle is who the RPC flood belonged to. 864 of the
4 327 lines carry a `GPU1` prefix and the rest none, and the driver's instance
numbering is not `nvidia-smi`'s: on the current boot `/proc/driver/nvidia/gpus/`
gives the 3090 `Device Minor: 1` and the A6000 `0`, the reverse of bus order. The
behavioural evidence points at the 3090 — `nvidia-smi` read the A6000 successfully
at 44 °C and 20 W six seconds after the fault, which a card whose RPCs were all
failing could not have answered — but probe order on the faulted boot was not
recorded, so this is an argument and not a mapping. **Left open.**

The `nvGpuOpsReportFatalError: uvm encountered global fatal error 0x60,
requiring os reboot to recover` line, 4.3 seconds later, is the same setter
reached a second time from UVM's own path (`nv_gpu_ops.c:11835`); `0x60` is
`NV_ERR_RC_ERROR`. It logged no third Xid because
`sysSetRecoveryOsRebootRequired` acts only on a change of state, and the flag
was already up.

## What the code reading changes, and what it does not

It does not explain why a card stops answering. No driver code runs during a DMA
transfer; the engine doing the work is on the card. Every rung of the ladder
below still has to be climbed, and this section does not shorten it.

What it does is fix the instruments and retire one question. A reproduction no
longer has to account for two cards failing, because only one did. Xid 79's
timestamp is a detection time with up to a second of slack, so it must not be
lined up against witness samples as though it were the event — the BMC column,
whose path is independent of all of this, is the better clock and should be
sampled faster than the 5.2 s the last run managed. And the fault window gets
captured from the journal.

Everything in these three sections is a code reading, not a measurement, which in
this repo is a hypothesis with a good pedigree and not a result. The claims are
"the source at tag 615.71.09, at `file:line`, says"; the one live check available
— that the preserved config-space dump reads all `ff`, the same not-answering
condition the quoted code tests for in BAR0 — is consistent with it and is not
the same register.

## What else the faulted machine said before it was rebooted

- **The 3090's config space read all `ff`.** The A6000's read `de 10 30 22`.
  All-ones is what a host bridge returns when nothing answers — not a driver
  giving up on a device. `current_link_speed` read `Unknown` and
  `current_link_width` read `63`, which is `0x3f` out of the same all-ones.
- **The device node stayed in sysfs** and `lspci` still listed it, from the
  earlier scan. Presence in `lspci` is not evidence the device is there.
- **Zero AER**, corrected and uncorrectable, on the card and on all three other
  ports, read from the registers. For contrast, the Gen4 margin problem this
  machine *did* diagnose announced itself as 27 corrected errors in 483 s of
  load. This fault takes a card off the bus in silence. Note the kernel cannot
  help here either way: this firmware logs
  `_OSC: platform does not support [AER LTR DPC]` for all four domains, so a
  quiet `dmesg` means the kernel was never told. The registers are the
  instrument; `dmesg` is not.
- **There is no software recovery path.**
  `echo 1 > /sys/bus/pci/devices/0000:41:00.0/remove` never returned in over
  eight minutes with the box otherwise fully responsive — the driver's teardown
  waits on a device that will not answer. For the same reason `systemctl reboot`
  did not complete: the host went offline and had not returned six minutes
  later, and the owner pressed the physical reset. **Operationally, this fault
  requires someone at the machine or at the BMC.** The BMC's web interface
  answered throughout, on standby power, and is the remote version of that.
- The driver wrote a crash dump and asked for `nvidia-bug-report.sh` before the
  module unloads. It was captured: 774 KB, with the other artefacts under
  `/home/user/gpu-check/fault-20260918/`.

After the reset both cards came back completely — config space `de 10 04 22`
and `de 10 30 22`, CUDA seeing 2, every CESta clear, zero Xid, and PCIE01
reading 30 °C again.

## Two defects in the witness, found by the load's session and not by us

**The per-card column labels go wrong at the fault.** `nvidia-smi` enumerates by
index; when the dead card drops out the survivor shifts into position 0, so from
06:34:30 the column labelled `gf3090` is the A6000. PCIE05 is what proves it —
it tracks that column exactly, 70/70, 68/68, 64/64, 62/62, down to 57/56. Every
post-fault row reads as "the 3090 is cooling" when it is the A6000 idling.
Querying by UUID rather than index is the fix. Until then the BMC column is what
disambiguated it, which is an argument for having built it that did not exist
before the fault.

**`smi_ok` stayed 1 through the whole event**, because the command kept
succeeding for the surviving card. The alarm, which used `nvidia-smi -L`, fired
correctly at 06:34:25. Two definitions of "answering" in one harness, and the
flag had the worse one.

## The control that was already on disk, and what it narrows to

The fingerprint carried since 2026-09-17 was "sustained load plus a second CUDA
context arriving on the card". Today's run does not fit it: DDP put **one**
context on each card, not two on one. So the fingerprint needs re-reading, and
the nights of 09-17 and 09-18 happen to contain the controls.

| load on this machine | duration | contexts | fault |
|---|---|---|---|
| gpu_burn, 3090 alone, 421 W | 30 min | 1, on the 3090 | none |
| gpu_burn, **both cards**, independent processes, 421 + 301 W | 10 min | 1 per card, no IPC | none |
| NCCL DDP, both cards | **133 s** | 1 per card, **NCCL between them** | **Xid 79 + 154 ×2** |
| NCCL DDP, both cards (2026-09-16) | **110 s** | 1 per card, NCCL between them | Xid 79 + 154 |
| llama-server on the 3090 + a torch process on the same card (2026-09-16 pm) | — | **2 on the 3090** | GSP RPC 0xf, no Xid |
| **pinned host↔device DMA, both cards, no NCCL** (rung 1, 08:00) | **15 min** | 1 per card, no IPC | **none** |
| **the same, plus a matmul loop at 419 W** (rung 1b, 08:20) | **15 min** | 1 per card, no IPC | **none** |
| NCCL DDP, both cards, stock limits (08:44) | **89 s** | 1 per card, NCCL | **the whole machine died** |
| **NCCL DDP, both cards capped to 250 W** (08:57) | **15 min** | 1 per card, NCCL | **none** |

The two-card burn is the control that matters and it passed: two processes, both
cards at full power, no inter-process communication, running **4.5 times longer
than today's time-to-fault** without incident. The thing DDP adds over it is
NCCL — and with `nvidia-smi topo -p2p rw` reading GNS between these cards, NCCL
is staging through **pinned host memory**, not P2P.

So the sharper statement is: sustained load alone does not do it on either card
or on both; two independent contexts on two cards do not do it; the two events
that killed the machine in about two minutes both had NCCL between the ranks.
The 2026-09-16 evening hang sits outside that — one card, two contexts, no NCCL
— and printed a different signature (`rpcSendMessage failed 0xf`, no Xid), so it
may well not be the same fault at all and this entry stops treating it as one.

**Peak power is not the variable, which kills the simplest hardware story.**
The run that took the machine down peaked at **384.1 W** on the 3090; the
30-minute gpu_burn the same card survived peaked at **420.5 W** and averaged
370.9. The fault happened 36 W *below* a load this card holds comfortably for
half an hour. So whatever NCCL does, it is not drawing more current than the
card tolerates — found by the session that ran the load, verified here against
both witness files.

What that leaves is the **shape** of the bus traffic rather than its magnitude,
and that is measurable rather than a story. gpu_burn is compute-bound with
almost no PCIe traffic; NCCL with GNS stages every gradient through pinned host
memory, which is large bidirectional DMA against the root port, continuously.

## Rung 1: bus traffic alone does not do it

That hypothesis was tested the same morning, because it is the cheap rung and the
machine was free. [`tools/gpu-dma-control.py`](../tools/gpu-dma-control.py) is the
whole load: one process per card selected by UUID, pinned host buffers, 25 MiB per
transfer — PyTorch DDP's default gradient bucket cap, so the transfers are the size
the faulting run actually moved — eight deep, both directions on separate streams.
No NCCL, no `torch.distributed`, no model, no second context.

It ran for fifteen minutes, **6.8 times the time the fault took**, and moved
30 499 GB across the 3090's link.

| | 3090 | A6000 |
|---|---:|---:|
| rxpci, mean / max | 17 813 / 19 098 MB/s | 18 550 / 21 711 MB/s |
| txpci, mean / max | 19 331 / 22 226 MB/s | 20 119 / 22 640 MB/s |
| power, mean / max | 160 / 164 W | 114 / 117 W |
| die temperature, max | 54 °C | 63 °C |

That is roughly **37 GB/s aggregate on the 3090's link, held for 900 seconds** —
near what Gen4 ×16 will practically carry in both directions at once, and far more
than NCCL's bursty gradient exchange sustains. Nothing happened. Zero Xid, one
kernel line in the whole window (the journal mark this runner writes itself), and
the `UESta`/`CESta` registers of both cards and both root ports **byte-identical**
before and after.

So the sharpened hypothesis of the section above is, in its simple form, wrong:
**sustained bidirectional DMA at the link's practical limit is not sufficient to
take this card off the bus.** What still separates this run from the faulting one
is that this load leaves the SMs idle — 160 W against the fault's 384 W — and that
it never enters the driver's NCCL path. Rung 1b varies the first of those by adding
compute beside the same DMA loop; only after that does the remaining difference
become the software path itself.

## Rung 1b: nor does bus traffic with the card at full power

Rung 1's load left the SMs idle at 160 W, so it did not test whether the fault needs
the card loaded and transferring at the same time. Rung 1b adds a 4096² fp32 matmul
loop on its own stream beside the same DMA. A short calibration picked the setting:
four matmuls per DMA iteration reaches **417.8 W** while still moving 19.1 GB/s, and
raising it further buys no power and only costs transfer rate.

That combination beats the faulting run on **both** axes at once — 419 W against its
384 W peak, and a sustained 18.5 GB/s against gradient exchange that is bursty by
construction. It ran the full fifteen minutes. The 3090 moved 16 675 GB, the A6000
15 234 GB, and the `UESta`/`CESta` registers of both cards and both root ports were
again byte-identical before and after.

**The telemetry for this run was lost, and the reason is worth more than the run.**
The witness never started: the scripts had just been renamed on their way into
`tools/`, the box still had the old names, the runner's call failed, and the next line
of the runner printed `witness up` because it announced the witness rather than
checking it. Fifteen minutes ran with every instrument silent and a run log that said
everything was fine. What survives is the load's own counters, the AER comparison, and
three spot readings of power taken by hand during the run (419.17, 418.93, 418.81 W at
73–74 °C) — enough to carry the negative, not enough to be a record. The runner now
asserts that four loggers are live and four files are growing before it will start the
load, and refuses the run otherwise; a round whose instruments are silent is not a
cheaper round, it is a wasted one.

So the two rungs together say: **neither bus traffic at the link's limit, nor bus
traffic with the card at the power the fault happened at, is sufficient.** The
variable that remains is the one neither rung touches — the NCCL path itself.

**A flag stopped meaning anything on the way past.** Both cards reported
`clocks_event_reasons.active = 0x400` — the bit this entry decoded as
`Reliability` — for the entire run, at 160 W and 54 °C on a card whose limits are
nowhere near. A bit that is set on a nearly idle card cannot distinguish a stressed
one, so it joins `throttled` in this repo's list of flags that are questions rather
than findings, and the earlier reading of `0x400` during the fault carries no weight
on its own.

**The instruments were rebuilt for this run**, against the three defects the
previous one exposed: everything is queried by UUID rather than index, presence is
`nvidia-smi -L` counting cards rather than "did a query return something", and the
BMC channel reads a dumped SDR with `-S` and the exact sensor name, which took its
sample cost from 5.2 s to 0.11 s. Measured across the run: 25 260 presence rows at
a 0.188 s worst-case gap, and 8 074 BMC rows at 0.449 s, against the 5.2 s mean the
ordering claim had to rest on last time. `nvidia-smi dmon -s put` supplied rxpci and
txpci, which no previous run recorded.
**Every clean row in the table above is compute-bound**, so the control table
has no row combining heavy sustained PCIe traffic with no fault — the variable
now suspected is the one the controls never varied. `nvidia-smi dmon -s t`
reports `rxpci`/`txpci` in MB/s and works on this driver; it was not in the
witness and should have been.

A limit on every power number in this entry, from the session that produced
them: witness spacing is **mean 5.2 s, max 10 s**, so `max 384 W` is the highest
of sparse samples and is blind to microsecond excursions by three or four orders
of magnitude. If the mechanism is a current transient at a DMA burst boundary,
nothing here would see it. These numbers rule out a *sustained*-power story and
nothing more, and an IPMI rail reading carries the same limit unless sampled far
faster than either session has sampled anything.

**This is in tension with the side-band finding above, and the entry is not going
to resolve it by choosing.** The SMBus ordering says the card stopped answering a
path the driver does not touch, which reads as hardware. The NCCL-versus-burn
control says a specific software access pattern is what triggers it, which reads
as software. Both can be true — a host-staging pattern has a different current
profile than a matmul loop, and software can drive hardware into a state it
cannot drive itself out of — but that is a story, not a measurement, and it is
written here as the open shape rather than as an explanation.

## The third fault was not the same fault

The round that finally carried good instruments produced a different failure. At 08:44:40
the DDP arm started; at 08:46:17.4 every channel stopped mid-line — the journal, both dmon
logs, the BMC loop, the presence loop and the step sampler, all within the same tenth of a
second. The machine came back on its own 55 seconds later.

What did **not** happen is the point. There was no Xid of any kind in that boot: the only
NVRM lines are the module banner and a firmware-log complaint. The presence channel counted
two cards in its last sample at 08:46:17.1, and the BMC read both slots at 67 °C and 74 °C
at 08:46:17.3. **Both GPUs were healthy right up to the instant the machine stopped
existing.** The first two events were a card falling off the bus with the host surviving;
this was the host dying with the cards fine.

It was not a kernel panic either. ERST pstore works on this board — it holds a panic from
2026-09-11 — and this event wrote nothing to it. The BMC's event log has no entry. The
return was too quick for the 120 s systemd watchdog. Nothing in software recorded anything,
which is what an instantaneous loss of the machine looks like.

**And the round finally measured the workload.** NCCL's actual PCIe traffic at the moment of
death was 40–80 MB/s on each card with bursts to 2–5 GB/s. Rungs 1 and 1b sustained
18–37 GB/s. The hypothesis those rungs were built to test had them pushing **two to three
orders of magnitude more traffic than the faulting workload ever does**, which is why their
silence was never the strong evidence it looked like: they were not a heavier version of the
fault, they were a different thing. Power at death was 372–390 W and 285–289 W — again below
rung 1b's 419 W and 299 W, which ran fifteen minutes.

What is left, once volume is out and steady power is out and temperature is out at 67 °C, is
the one thing only a collective produces: the two cards are made to **wait for each other and
then draw together**. Independent loads average their transients out; a barrier aligns them.

## Taking the budget away, which is the only way this machine can ask about power

Nothing here can see a transient. Measured 2026-09-18: NVML answers 840 000 power queries a
second but the reading only *changes* every 231 ms on the 3090 and 250 ms on the A6000, and
the BMC's `+12V` sensor did not move off 12.06 V once in twelve seconds of polling at 12.5
reads/s. Microsecond current behaviour is not observable on this box, and saying so is more
useful than another run pretending otherwise.

So the question was asked the way this repo asks power questions — by removing the headroom.
Both cards were capped to 250 W (from 420 and 300) and the same DDP arm was run again with
the full witness.

| | stock limits | capped to 250 W |
|---|---|---|
| time to fault | **89 s** | **none in 900 s** |
| 3090 power, mean / max | 384 / 390 W | 240 / **250 W** (pinned at the cap) |
| A6000 power, mean / max | 286 / 289 W | 231 / 245 W |
| 3090 die temperature, max | 67 °C | 62 °C |
| presence rows below two cards | — | **0 of 23 414** |
| BMC read failures | — | **0 of 8 037** |
| Xid | none, then the machine died | none |
| `UESta`/`CESta` before vs after | — | byte-identical |

**It ran the full fifteen minutes, ten times the shortest time-to-fault.**

And because the step sampler kept running, the mitigation has a price tag:

| configuration | steps/s | against one card |
|---|---:|---:|
| A6000 alone at 300 W (peer's measurement, 06:16) | 1.089 | 1.00× |
| DDP, stock limits — died at 89 s | 2.019 | 1.85× |
| **DDP, both cards at 250 W — clean for 900 s** | **1.648** | **1.51×** |

Cutting the 3090's budget by 40 % and the A6000's by 17 % costs 18 % of the DDP speedup and
keeps **half again the single-card rate**. That is the first thing this investigation has
handed back: a configuration that runs.

**What this is not.** One clean fifteen-minute run is not a stability claim; the faults came
at 89, 110 and 133 seconds, so 900 s is six to ten times that and one sample. The cap moves
the clock and voltage operating point as well as any transient, so it is not a single-variable
change. And no transient or voltage sag has ever been observed here — the mechanism above is
an explanation that fits every row in the control table, not a measurement. Settling it needs
a current clamp on the 8-pin cables or a different power supply.

**The supply is a Super Flower Leadex Platinum SF-2000F14HP, 2000 W**, which `README.md` has
recorded all along. That matters because it removes the obvious version of the story: the two
cards drew about 676 W between them when the machine died, and the system as a whole stays
well under half this unit's rating, so **capacity is not the issue and no amount of headroom
is missing.** What the README also records is the unit's published spec — **ATX12V 2.2 /
EPS12V**. That standard predates the transient requirements ATX 3.0 added precisely because
Ampere-generation cards excurse far above their average for tens of microseconds; a supply
built to the older spec is under no obligation to ride those out, and its protection may act
on a spike a newer unit must tolerate. That is a hypothesis about a named part rather than a
measurement, and the same clamp would settle it.

## Nothing has been filed upstream, and why

The obvious move is an issue on `open-gpu-kernel-modules`, where
[#1134](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1134), #942 and
#1111 describe this symptom class on the open module — #1134 on an RTX 3090,
hanging when a new GPU client process is created while an RPC is in flight,
power-cycle only, with the proprietary module at the same version not
reproducing.

That move is wrong today, because **the strongest evidence this run produced
points away from the driver.** Filing it would be submitting a hypothesis as a
defect, and the version string is most of what we would be adding to a pile that
already describes the symptom.

What changed is that the discriminator is finally runnable. It has been in the
ranked table since 2026-09-17 as the one test, blocked on not having a
reproducer:

| run the same reproducer on the 580 legacy branch | then |
|---|---|
| it reproduces | the cause is the card or its power. No issue; we have the answer instead |
| it does not | a clean bisect between module families, a 133 s reproducer, a crash dump taken before unload, and a side-band ordering none of those three issues has. That is a report worth filing |

580 is the last module family that is not GSP-mandatory, so it is the only
driver-side control available — `NVreg_EnableGpuFirmware=0` does not apply,
because the open module requires GSP and after 580 there is no proprietary
module.

The tests now form a ladder, cheapest first, each discriminating something the
one before it cannot:

1. **A pinned host-to-device memcpy loop on both cards, no NCCL at all.** The
   same PCIe pressure with none of NCCL's software. If it reproduces, the
   variable is bus traffic, NCCL is a red herring, and the reproducer is a page
   of code. If it does not while step 2 does, the bus and the software are
   separated — which is exactly the tension this entry leaves open. Proposed by
   the session that ran the load; needs no training job and no driver swap.
2. **Two trivial NCCL ranks doing nothing but an all-reduce loop.** No model, no
   data loader, no 20 GB of weights to confound it. If it reproduces in about
   two minutes, the reproducer is small enough to hand to a stranger, which is
   what an upstream issue actually needs and what a HiFiGAN training job can
   never be.
3. **The 580 legacy bisect**, last because it is the most invasive.

Whatever runs next carries `dmon -s t` in the witness, and queries by UUID
rather than index.

A caution on the 580 bisect, from the session that ran the load and worth
recording because it is the same asymmetry agreed before today's run: a
non-reproduction on one attempt is weak evidence where today's reproduction was
strong. Three clean runs well past 133 s before calling 580 clean, and the swap
changes more than the GSP path, so "nothing else moved" has to be argued rather
than assumed.

## The load, as its session specified it

PyTorch Lightning DDP, 2 ranks one per GPU, NCCL backend, no P2P;
HiFiGAN-family vocoder training with generator and discriminator alternating,
batch 20 per rank, 44.1 kHz audio, about 20.2 GB resident per rank; driver
615.71.09 open kernel module; the 3090 at 368–382 W sustained through the 90
seconds before the fault and the A6000 at 275–290 W; the fault at 133 s, inside
warm-up, never reaching steady state.

The DDP throughput number the run was launched to get was never obtained, and
that is not a cost. The question behind it was whether two-card training is
available on this hardware, and it is answered: not at present, with evidence
rather than a recollection of 2026-09-16.
