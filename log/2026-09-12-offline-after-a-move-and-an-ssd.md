# Two ways to be off the network, one on top of the other

**2026-09-12.** The workstation went dark on the evening of 2026-09-11, the day
it was moved from an office to a house, and stayed dark for about twenty hours.
The console showed a login prompt the whole time, so the OS was never the
problem. There turned out to be two independent faults, a day apart, and each
one alone was enough to keep it off the network. Fixing either would have left
it exactly as dead, which is most of why the first day of guessing produced
nothing.

Everything below was measured on the machine in [the README](../README.md), by
reading the journals of the boots involved, on this date.

## Fault one: the move, and a lease it would not give up

The netplan stanza the installer wrote carried `critical: true`. That is
netplan's way of telling `systemd-networkd` to hold on to a running
configuration rather than tear it down — meant for machines whose root
filesystem is on the network, where dropping a lease means dropping the disk.

This machine had a lease from the office network. Watch what the move did to
it. Last minutes of the boot at the office, as the cable came out:

```
20:24:40  enp36s0f1: Lost carrier
20:24:40  enp36s0f1: DHCPv4 connection considered critical,
                     ignoring request to reconfigure it.
20:24:44  enp36s0f1: Gained carrier
```

Then the first boot at the house, half an hour later:

```
20:52:53  ixgbe 0000:24:00.1 enp36s0f1: renamed from eth1
20:52:54  enp36s0f1: Configuring with …10-netplan-enp36s0f1.network
20:52:58  enp36s0f1: Gained carrier
20:52:58  ixgbe … enp36s0f1: NIC Link is Up 1 Gbps, Flow Control: RX/TX
20:52:59  enp36s0f1: Gained IPv6LL
```

The interface was found, configured, and had carrier at 1 Gbps. It got a
link-local IPv6 address and **never a DHCPv4 one** — there is no `DHCPv4
address … acquired` line anywhere in that boot, against one at `12:56:42` in
the boot before it. `critical` did what it says: the request to reconfigure was
ignored, and the machine sat on a house network still holding the idea of an
office lease.

Everything downstream followed from that. `tailscaled` logged
`LinkChange: all links down; pausing` with `v4=false`, which is why the node
went offline on the tailnet and why `ssh` timed out.

There is a footnote in the same boot. At 04:58 the next morning:

```
ixgbe … enp36s0f1: NETDEV WATCHDOG: CPU: 22: transmit queue 3 timed out 5685 ms
ixgbe … enp36s0f1: initiating reset due to tx timeout
ixgbe … enp36s0f1: Reset adapter
enp36s0f1: Lost carrier
enp36s0f1: DHCPv4 connection considered critical, ignoring request to
           reconfigure it.
```

That is the X550 `Tx Unit Hang` the README already warns about, and it handed
the machine a second chance to ask for a lease. `critical` refused that one
too.

## Fault two: a new SSD moved the network card

By the time the repair started, a 4 TB Phison E18 had been added and the BIOS
had been reset. The added drive is not incidental — it is the cause of the
second fault:

```
23:00.0  Non-Volatile memory controller  Phison E18 PCIe4 NVMe Controller
24:00.0  USB controller                  ASMedia ASM3242
25:00.0  Ethernet controller             Intel X550
25:00.1  Ethernet controller             Intel X550
```

The new drive took bus `0x23` and everything behind it shifted up one. Measured
across boots, with the same MAC on the same card throughout:

| boot | when | X550 at | interface named |
|---|---|---|---|
| −5, −4 | 09-11 | `0000:24:00.x` | `enp36s0f1` |
| −3 | 09-12 08:47–13:36 | `0000:24:00.x` | `enp36s0f1` |
| −2 onward | 09-12 15:30 → | `0000:25:00.x` | `enp37s0f1` |

`enp36s0f1` is not a name in any durable sense. It is a rendering of the PCI
bus number — `0x24` is 36, `0x25` is 37 — assigned by firmware at enumeration.
Add a device in front of it and the name moves.

The netplan file went on naming `enp36s0f1`. A netplan stanza naming an absent
interface is not an error condition: no warning, no failed unit, no journal
line. The link is simply never brought up, DHCP never runs, and the machine
sits at a login prompt with no address — indistinguishable at the console from
a dead NIC.

Proof that this was the state, rather than a hardware or cabling fault, was one
command: `ip link set … up` brought the cabled port to `LOWER_UP` immediately.
The link had been there all along; nothing was configured to raise it.

## What it wasn't

The standing suspicion was `pci=realloc=off`. This board needs it or the 10 GbE
ports drop, and a BIOS reset looks exactly like the kind of event that loses a
kernel parameter. It was wrong:

```
$ cat /proc/cmdline
BOOT_IMAGE=/boot/vmlinuz-6.8.0-139-generic root=UUID=… ro pci=realloc=off
```

The parameter lives in GRUB's config on disk, so firmware changes never
threatened it. Worth writing down, because it is the hypothesis this machine
will keep offering.

## The fix

[`configs/01-lan.yaml`](../configs/01-lan.yaml), installed as
`/etc/netplan/01-lan.yaml` at mode 600. Three changes, one per fault and one
for the trap underneath them:

- **Match on MAC address**, which firmware does not reassign, instead of on a
  bus-derived name. Both X550 ports are declared, so either can carry the
  cable.
- **No `critical`.** This machine's root is local; there is nothing to protect
  by holding a stale lease, and holding one is what cost the first day.
- **cloud-init no longer owns the file.** `50-cloud-init.yaml` is generated,
  and `/etc/cloud/cloud.cfg.d/90-installer-network.cfg` held the same stale
  `enp36s0f1` — so editing the netplan file alone would have worked until the
  next boot regenerated it. A `network: {config: disabled}` drop-in gives the
  config one owner. The old file moved to `/root/netplan-backup/` rather than
  being deleted.

`optional: true` on both ports is deliberate and costs something worth naming:
without it, `systemd-networkd-wait-online` blocks boot for 120 seconds on
whichever port has no cable. With it, `network-online.target` passes
immediately, which is safe here only because nothing on this machine needs it —
the LLM server binds loopback and tailscaled does its own retrying.

## The check

The defect class is "netplan describes hardware that isn't there, silently", so
the contract is that every declared interface resolves to a present link.
[`configs/netplan-iface-check`](../configs/netplan-iface-check) asserts it, and
[a oneshot unit](../configs/netplan-iface-check.service) runs it at every boot
so a future mismatch shows up in `systemctl --failed` instead of as an
unreachable machine.

Against the broken config, before the fix:

```
FAIL /etc/netplan/50-cloud-init.yaml: enp36s0f1 names a link that does not exist
0/1 declared interfaces present
EXIT=1
```

and against the new one:

```
ok   lan-f0: MAC …:86 -> enp37s0f0
ok   lan-f1: MAC …:87 -> enp37s0f1
2/2 declared interfaces present
EXIT=0
```

The FAIL is the point, and it was recorded before the fix went in — afterwards,
reproducing it means deliberately breaking the machine.

## DNS, measured rather than assumed

The old config named two public resolvers, chosen for the old ISP. Keeping them
across a change of network is the same species of mistake as keeping an
interface name across a change of bus number, so they were measured instead:

| resolver | result |
|---|---|
| the two named in the config | both answered |
| the house router | `connection refused` — it does not serve DNS |

So they stay. Had they failed, the right move would have been to delete the
block and take what DHCP offers — but here DHCP's own answer includes the
router, which refuses port 53.

## Applying it without losing the only way in

Both the revert and the apply ran as transient systemd units, because the SSH
session issuing `netplan apply` rides the interface being reconfigured, and an
apply that dies halfway is worse than either outcome:

```bash
# dead man's switch: restore the hand-configured address in 180 seconds
systemd-run --on-active=180 --unit=lan-revert /bin/bash -c \
  "ip addr add <addr>/24 dev enp37s0f1 2>/dev/null; \
   ip route replace default via <router> dev enp37s0f1"

systemd-run --unit=lan-apply --collect /usr/sbin/netplan apply
```

The revert target is the *working* hand-made state, not the previous config —
rolling back to `50-cloud-init.yaml` would have restored the outage. The timer
was stopped once the session came back. Result: a DHCP lease on the cabled
port, the hand-added address cleaned up by netplan itself, DNS resolving,
Tailscale back on its own.

## Reboot

`netplan apply` succeeding and the machine surviving a boot are different
claims, and this outage was entirely about the second one.

| | |
|---|---|
| cloud-init did not regenerate a config | `/etc/netplan/` holds `01-lan.yaml` and nothing else |
| the cabled port got an address | same DHCP lease as before the reboot, default route via it |
| DNS | resolves |
| Tailscale | back up on its own |

Three of four. The fourth was the LLM server, and it was not running.

## What the reboot turned up

Rebooting a machine you have just repaired is how you find out what else was
already broken. Two things were, and neither had anything to do with the
network.

**The LLM server had not auto-started on boot in at least four boots.** It is
`enabled`, `multi-user.target` wants it, every dependency it names was active,
and its own journal was empty — systemd had never tried. The reason was one
line elsewhere:

```
multi-user.target: Found ordering cycle on llm.service/start
multi-user.target: Job llm.service/start deleted to break ordering cycle
                   starting with multi-user.target/start
```

`thermal-guard.service` was both `WantedBy=multi-user.target` and
`After=multi-user.target`. A unit pulled into a target must not also be ordered
after it — that closes the loop `multi-user.target` → `llm.service` (which is
`After=thermal-guard.service`) → `thermal-guard.service` →
`multi-user.target`. systemd broke the cycle the only way it can, by deleting a
job, and the job it chose was the one that starts the model server. Removing
the stray `After=` is the fix.

Verified on the boot at 16:57: no `ordering cycle` in the journal, and
`llm.service` active from 16:57:22 with `NRestarts=0`, started by nothing but
systemd. A cycle only exists while a transaction for `multi-user.target` is
built, so a boot was the only thing that could settle it.

(One grep said otherwise first. `journalctl | grep -c 'ordering cycle'`
returned 1, and the match was the text of the SSH command doing the grep,
logged by `tailscaled` on its way in. Counting your own question as an answer
is easy to do over SSH.)

Note what that failure looks like from outside: a service that is enabled, has
no failed state, logs nothing, and does not run. `systemctl status` says
`inactive (dead)` — the same thing it says about a service stopped on purpose.
`systemd-analyze verify llm.service` exits 0, because ordering cycles are
resolved when a transaction is built, not when a unit file is parsed. Only the
boot journal has the evidence.

**`cpu-noboost.service` was failing outright.** It did
`echo 0 > /sys/devices/system/cpu/cpufreq/boost`, and after the BIOS reset that
node does not exist, because the firmware now disables Core Performance Boost
itself:

| | |
|---|---|
| `cpb` | `0` |
| `scaling_max_freq` | `3600000` |
| `bios_limit` | `3600000` — the 5975WX base clock |

So the contract this machine actually cares about — boost stays off, because
the cooler does not cover the sWRX8 IHS — was being met, while the unit that
exists to enforce it reported failure. That is worse than it sounds: a
permanent red line in `systemctl --failed` is where real failures go to hide.
[`configs/cpu-noboost`](../configs/cpu-noboost) replaces it and asserts the
outcome instead of the mechanism — turn boost off wherever a knob exists, then
verify it is off and name the evidence, and fail only when boost is on and
cannot be turned off. It now reports
`boost off: cpb reads 0 (firmware or driver)`.

## The same mistake, four times

Worth stating plainly, because it is the only general lesson here. Four
separate failures on this machine, all the same shape: something bound itself
to a volatile *mechanism* instead of the *invariant* it cared about.

| what it wanted | what it bound to |
|---|---|
| this network card | a PCI bus number, rendered as a name |
| a working lease | the lease it already had |
| boost off | one sysfs file existing |
| start after the guard | a target that was also waiting on it |

And a fifth that cost nothing only because someone got it right years ago. With
two NVMe controllers present, which one becomes `nvme0` is decided by which
finishes probing first, and probing is asynchronous. Measured across two boots
forty minutes apart, with no hardware touched in between:

| boot | `nvme0n1` | root filesystem at |
|---|---|---|
| 16:46 | the 2 TB Samsung | `nvme0n1p2` |
| 16:57 | the 4 TB Phison | `nvme1n1p2` |

Root mounted both times, because `/etc/fstab` and the kernel command line name
it by UUID. Nothing about `nvme0` was ever a fact about a disk — which is worth
holding on to before typing a destructive command with one in it.

## Serving, after all of it

```
decode    28.9 tok/s   (400 tokens generated)
prompt      178 tokens in 1.9s
draft        62% accepted   (DSpark, depth 2)
```

Against the 25–33 tok/s recorded on
[2026-09-11](2026-09-11-deepseek-v4-moe-offload.md), with 29 in the middle. The
rate came back.

## Still open

The new 4 TB drive is partitioned NTFS and not mounted — it came formatted and
nothing has been decided about it yet.

## What this changes elsewhere

[`docs/wrx80e-bios-setup.md`](../docs/wrx80e-bios-setup.md) gains the lesson
next to its `pci=realloc=off` section: that parameter was not the cause here,
and the real hazard when opening this machine is that adding a PCIe device
renumbers the buses behind it and moves every name derived from an address.
