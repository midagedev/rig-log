# The machine was resetting every ten minutes and nothing on it knew

**2026-09-12.** For about forty minutes this afternoon the workstation hard-reset
every ten minutes, four times, and left no record of any of it. What surfaced it
was not the resets — SSH sessions are short and it came back in ninety seconds —
but the owner noticing the GPUs were busy when nothing should have been running.
That was `llm.service` starting up again after each boot.

The cause was a BMC watchdog that the BIOS arms and nothing on this machine
disarmed. It had been armed since the BIOS reset earlier the same day.

Everything below was measured on the machine in [the README](../README.md) on
this date.

## The shape of it

```
boot  started      ended        uptime
 -3   16:46:31     16:56:14     9m 43s
 -2   16:57:19     17:06:52     9m 33s
 -1   17:08:08     17:17:01     8m 53s
```

Regular to within a minute, which is the signature of a timer rather than a
fault. Nothing in the kernel log: no panic, no oops, no MCE, no thermal event.
CPU at 43 °C, NVMe at 48 and 36 °C. The journal of each boot simply stops
mid-sentence — the last line of one is `cron` opening a session for the hourly
run.

## A wrong reading, and what corrected it

The first pass at this concluded the shutdowns were clean, on the strength of
lines like:

```
17:14:36 systemd[8902]: Reached target shutdown.target - Shutdown.
```

That is not the system shutting down. The number in brackets is the PID, and
8902 is a `systemd --user` instance tearing down as an SSH session ends. Four of
those appear per boot here because each of my own SSH commands opened and closed
a session. PID 1 never said anything of the kind.

The check that settles it takes one line, and it is worth keeping:

| boot | system-shutdown records |
|---|---|
| the one rebooted with `systemctl reboot` | 1 |
| every boot after it | 0 |

A clean shutdown writes a record. A hard reset does not get the chance. The
contrast is the evidence, and it is available on any machine that has done both.

## What was actually holding the timer

```
$ ipmitool mc watchdog get
Watchdog Timer Use:     OS Load (0x43)
Watchdog Timer Is:      Started/Running
Watchdog Timer Action:  Hard Reset (0x01)
Initial Countdown:      600.0 sec
Present Countdown:      271.2 sec
```

And in the BMC's own event log, one entry per reset:

```
2beb | Watchdog2 | Hard reset | Asserted
2bf0 | Watchdog2 | Hard reset | Asserted
2bf5 | Watchdog2 | Hard reset | Asserted
```

`OS Load` is a boot watchdog. The firmware arms it during POST and expects the
operating system, once it has finished booting, to either take the timer over or
switch it off — the point being to catch a boot that hangs. Ubuntu here did
neither, so ten minutes after every POST the timer reached zero and the BMC did
what it was told: hard reset. It was not malfunctioning. It was doing its job
with only half the arrangement present, and the missing half was on the OS side.

It had presumably been arming on every boot since the BIOS reset. It went
unnoticed because the machine was unreachable for most of that window for an
unrelated reason — see
[the network outage entry](2026-09-12-offline-after-a-move-and-an-ssd.md) — and
because a ninety-second absence looks like nothing from the outside.

The BMC clock is eight hours off, so SEL timestamps and journal timestamps do
not line up without arithmetic. That cost time during the investigation and is
worth fixing.

## Taking the timer over rather than switching it off

Switching it off is one line and closes the incident. The other option is to use
the watchdog for what a watchdog is for, and that is the one taken here: this
machine is headless, is reached only over the network, and had just spent twenty
hours unreachable. A kernel that wedges is otherwise unrecoverable without
walking to it.

IPMI exposes a single watchdog timer, so a driver that claims it with timer use
`SMS/OS` displaces the firmware's `OS Load` use. Taking it over therefore
subsumes switching it off.

Three files, all in [`configs/watchdog/`](../configs/watchdog):
`/etc/modules-load.d/ipmi_watchdog.conf` loads the driver,
`/etc/modprobe.d/ipmi_watchdog.conf` sets `action=reset` and a panic grace
period, and `/etc/systemd/system.conf.d/watchdog.conf` sets
`RuntimeWatchdogSec=120`. PID 1 then opens `/dev/watchdog`, sets the hardware
timeout, and pets it every 60 seconds.

120 seconds, not the 10 that guides suggest. This machine deliberately runs near
its memory limit — `llm.service` holds around 111 GB resident with
`OOMPolicy=continue` — and a stall in PID 1 under memory pressure must not be
read as a hang. Recovery from a real wedge takes up to two minutes instead of
ten seconds, which is nothing next to twenty hours.

After:

```
Watchdog Timer Use:     SMS/OS (0x44)
Watchdog Timer Is:      Started/Running
Initial Countdown:      120.0 sec
```

Petting confirmed by watching the countdown rather than trusting the setting —
it sawtooths between about 90 and 120 seconds and never goes lower:

```
17:29:31  120.0 sec
17:29:46  105.2 sec
17:30:01  120.0 sec
17:30:16  105.0 sec
```

The machine has since been up for over an hour, against three consecutive
nine-minute lifetimes before.

## What this catches and what it does not

It catches anything that stops PID 1 from being scheduled: kernel deadlock, a
panic that does not reboot, a driver lockup, total memory exhaustion, a CPU soft
lockup. The BMC runs independently of the CPU, so it works when the host is
entirely gone.

It does not catch a machine whose kernel is healthy and whose usefulness is not.
A single hung service, a userspace deadlock, or a network interface that never
gets an address — the failure this machine actually had yesterday — all leave
systemd petting contentedly. Catching those needs a probe that pets only while
some higher-level thing is true, which is a much easier way to build a machine
that reboots itself for no reason. Not done here.

## Still open

- Whether the driver loads and the timer is re-armed **early enough on a cold
  boot** has not been verified. PID 1 reads `RuntimeWatchdogSec` at startup and
  opens `/dev/watchdog` then; if `ipmi_watchdog` is not yet loaded at that
  moment, arming may not happen until something triggers a reload. The firmware's
  own 600-second `OS Load` timer covers the gap only if the takeover happens
  within ten minutes of POST. This needs a reboot and a check that asserts the
  timer is running, in the same spirit as
  [`configs/netplan-iface-check`](../configs/netplan-iface-check).
- The BMC clock is eight hours ahead of the host.
- The BMC still has its default credentials.
