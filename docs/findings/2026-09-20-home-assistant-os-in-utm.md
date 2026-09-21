# Home Assistant OS in a UTM VM, 2026-09-20

## Bridged over Wi-Fi WORKS here (measured 2026-09-20, after this was written)

This document opened by warning that bridging over Wi-Fi was unproven on
macOS 26 and that the move might not deliver discovery. The creator did the
install the same evening, and the bridge took:

    homeassistant.local -> 192.168.50.208
    192.168.50.208 at 46:4f:96:a4:c9:30 on en0      (its own MAC in the host's ARP table)
    ping: 2 of 2, 1.0 ms average

That is a real device on the LAN with its own address and its own mDNS
name, on `Mac15,7` / macOS 26.5.2 / UTM 4.7.5 / Wi-Fi `en0` into an ASUS
ZenWiFi Pro ET12. The caution below was right to insist on evidence and
wrong about the outcome; both halves are left in place, because the
research said "unproven", not "broken", and the difference matters when the
next person reads this.

What is still unproven is the thing the move was FOR: whether Home
Assistant, from inside that VM, discovers other devices by mDNS. Core was
still installing at the time of writing. The decisive test is unchanged --
does the Lutron bridge at 192.168.50.108 appear by itself under Settings ->
Devices -> Discovered.


The creator's decision, verbatim: *"let's move HA OS in a UTM VM with a bridged
adapter"* — off the Docker container recommended in
[2026-09-20-home-assistant-on-the-mac.md](2026-09-20-home-assistant-on-the-mac.md),
onto the real product, so that Home Assistant becomes a device on
192.168.50.0/24 and gets back the two things a container on this Mac can never
have: mDNS/SSDP discovery, and Supervisor add-ons.

This document is the guide for doing that. It opens with a correction, because
the decision was made partly on a sentence I wrote yesterday and that sentence
was too confident.

---

## The correction: "bridged" over Wi-Fi is not the escape hatch I called it

The Docker note ends by saying that if discovery matters, the answer is "HA OS
in a UTM VM with a *bridged* network adapter … the escape hatch this document
already recommends keeping open", softened only by "test the bridge over Wi-Fi
before committing to it". That ordering was wrong. The test is not a formality
at the end; it is the whole question, and this house has no Ethernet, so it is
the only question. **Bridging over Wi-Fi is the part of this plan most likely to
fail, and if it fails the move buys add-ons and USB passthrough but not
discovery — which is the reason the move was proposed.**

Here is what I could establish, with sources and dates.

**UTM does not promise it.** Its own documentation describes bridged mode as
"The host creates a layer 2 bridge with the specified interface. This is for
advanced users," and adds, flatly: "Note that bridging with an Wifi interface
may require additional configuration." That is the vendor hedging on exactly
our case.

**It is not actually a layer-2 bridge over Wi-Fi, and cannot be.** An 802.11
station is associated with the access point under one MAC address. Putting a
second MAC on the air needs WDS / four-address mode, which the client side of
consumer Wi-Fi does not do. Apple's `vmnet.framework` therefore fakes bridging
on Wi-Fi with proxy-ARP and MAC translation: the guest gets a LAN IP from the
ZenWiFi's DHCP, but its frames go out under the Mac's own MAC. This has been the
arrangement since Big Sur and is the subject of a long-running Apple Developer
Forums thread, "macOS BigSur >= 11.1 wifi bridging issue on VMs" (thread
677034). Over Ethernet, bridged is a real bridge; over Wi-Fi it is an emulation,
and the parts of it that are emulated are precisely the parts discovery uses.

**There are open, unfixed bridged-mode faults against macOS 26 hosts.**

- utmapp/UTM issue **#7617**, opened 16 February 2026: with the *host* on macOS
  Tahoe 26.2 or later and the VM in bridged mode, the guest floods "bad tcp
  cksum" and "bad udp cksum" and Apple-framework networking fails; the same VM
  moved to a Sequoia 15.3.1 host works. The reporter's guest was macOS, so this
  is not proof against a Linux guest, but the cause they identify is host-side
  and this Mac is on 26.5.2.
- utmapp/UTM discussion **#7472** (macOS Sequoia 15.7 + UTM 4.7.4, last comment
  April 2026, no fix): `vmnet-shared` stopped working outright — no `vmnet1`
  interface, no DHCP answer in any guest — and the reporter's summary of the
  cause is "macOS Sequoia's new networking sandbox fully blocks UTM's NAT
  (vmnet-shared)" with "vmnetd … fully deprecated". Bridged was their
  *workaround*, not their problem. Note carefully what they say about it, though
  — see the fallback section below, because it inverts the usual advice.
- utmapp/UTM issue **#7658**, 23 March 2026: bridged VMs will not boot at all on
  M5 Pro Macs with the new N1 Wi-Fi 7 chip. **This does not apply here** — this
  machine is a `Mac15,7`, Apple M3 Pro — but it is a reminder that bridged is the
  mode Apple breaks.
- The Home Assistant community thread "Selecting Bridged Network causes error
  with UTM on MacOS" (#773985) is this exact setup: an M1 iMac gets
  `qemu-aarch64-softmmu: -netdev vmnet-bridged,id=net0,ifname=en0: cannot create
  vmnet interface: general failure (possibly not enough privileges)` and never
  resolves it. A second user on an M2 mini reports bridged working fine once he
  picked the right interface. So: some people, some Macs.

**Home Assistant does not support this path.** The project's macOS installation
page documents VirtualBox in detail and says only: "If VirtualBox is not
supported on your Mac and you have experience using virtual machines, you can
try running the Home Assistant Operating System on UTM." That is a decline, not
an endorsement.

**And the thing I most wanted to find, I could not find.** I looked for one
confirmed report of HA OS in UTM, bridged over Wi-Fi, on a macOS 26 Apple
Silicon host, actually auto-discovering a device by mDNS. There isn't one in
anything I can reach. There are reports of the VM *getting an address* that way,
which is a weaker claim and the one people usually mean when they say bridging
works.

**Why it might still work, and what half-working looks like.** Inbound
multicast is plausible: `224.0.0.251` is a group address, the AP delivers it to
the station regardless of MAC, and vmnet can hand it to the guest. Outbound is
the doubtful direction, because the guest's query leaves under the host's MAC
and the reply has to be steered back. So the realistic bad outcome is not "no
network" — it is **discovery that half works**: HA hears some announcements,
its own queries go unanswered, devices appear and vanish. That is worse than no
discovery, because it reads as a device fault and you can spend a week on it.
Watch for it.

### What to do about it, in order

1. **Best, and the only one I would call reliable: a USB-C Ethernet adapter into
   the ZenWiFi.** Over a wired interface `vmnet` bridged is a genuine layer-2
   bridge, multicast included, and the whole argument above evaporates. Cost is
   an adapter and a cable across the room. **One caveat, and it is a real one:**
   the reporter in UTM discussion #7472 found bridged worked over Wi-Fi `en0`
   and *did not* work over their USB Ethernet adapters `en8`/`en9` — the guest
   saw an unplugged cable. Not every USB adapter appears in vmnet's bridgeable
   list. Buy one you can return, plug it in, and check it shows up in UTM's
   Bridged interface dropdown *before* believing this paragraph.
2. **Try bridged over Wi-Fi as a timed experiment, not as a migration.** It is
   about 45 minutes and it has a clean pass/fail (below). If it passes, keep it.
   If it half-passes, stop — do not tune it.
3. **Shared (NAT) mode plus a DHCP reservation and manual integrations.** This
   is the honest floor. It costs you discovery, which is the reason for the move,
   so the move reduces to "add-ons and USB passthrough" — worth something, but
   say so out loud rather than pretending the goal was met. And note #7472: on
   recent macOS, shared mode is the one that has been failing outright. If you
   land here, verify the VM gets a `192.168.64.x` address and not a `169.254.x.x`
   one.

### The argument nobody in those threads makes

If discovery and add-ons are worth a weekend, they are worth $60. A Raspberry Pi
5 or a used mini PC running HA OS on bare metal gives you bridged-by-definition
networking, real mDNS, every add-on, USB Zigbee/Z-Wave sticks, and none of the
questions above — and it does not disappear when the lid of this MacBook closes.
**That last point applies to the VM and the container equally and is the real
ceiling on both**: a household automation hub that stops when the laptop sleeps
is not a hub. It is fine for building and testing Sim's `home_*` tools against
something real, which is what this is for today. It is not the end state, and
neither the container nor the VM gets you there. Nothing below is wasted if that
Pi arrives: an HA backup restores from any of these into any other.

---

## What is actually on this machine, as of writing

The ground moved during this session, so these are measured, not assumed:

| | |
|---|---|
| Mac | `Mac15,7`, Apple M3 Pro, 36 GB RAM, macOS 26.5.2 (25F84) |
| Network | Wi-Fi `en0` only, 192.168.50.33, gateway 192.168.50.1 (ZenWiFi Pro ET12). `en4`/`en5`/`en11` exist but are `status: inactive`, `media: none` — no wired link |
| UTM | **now installed**, 4.7.5, `utmctl` at `/Applications/UTM.app/Contents/MacOS/utmctl`, 1.1 GB, no VMs defined |
| Docker HA | **already running**: container `homeassistant`, HA **2026.9.3**, 141 components, up about an hour |
| Sim's credentials | **already configured**: `vault:home_assistant:url` = `http://127.0.0.1:8123` and a working long-lived token in `~/.simorgh/secrets.toml`; `tools/ha.py status` exits 0 |
| Free disk | **21 GiB and falling** — see below |

So this is not a first install. **It is a migration**, and the section on moving
the configuration across matters as much as the install steps.

### The disk, honestly

Free space on the data volume went **37 GiB → 29 GiB → 21 GiB within one hour**
while I was writing this, as Docker pulled the HA image and built. Docker now
holds 10.16 GB of images. The 39.8 GB figure this work started from is stale.

What HA OS in UTM costs on top:

| Item | Size |
|---|---|
| UTM.app | 1.1 GB — already spent |
| `haos_generic-aarch64-18.3.qcow2.xz` download | 344 MB (exact, from the release asset) |
| The decompressed `.qcow2` | a few GB; delete both it and the `.xz` after UTM imports the VM |
| The VM's disk in use | starts around 4 GB, grows with the recorder database toward whatever you set as the maximum |

Set the VM disk to 32 GB *nominal*. qcow2 is thin-provisioned so that is a
ceiling, not an allocation — but at 21 GiB free **the ceiling is a lie you are
telling yourself**, and if HA ever tried to fill it the boot volume would die
first. Two consequences, both non-optional:

- Free space **before** starting, not after. `docker system df` shows 511 MB of
  reclaimable build cache and 67 MB of dead containers for free. Read
  [2026-09-20-the-disk.md](2026-09-20-the-disk.md) — it is the same volume, and
  the Ledger already reports `degraded` under 5% free, which is 23 GiB. **You are
  at or just above that line right now.**
- Shorten HA's recorder retention in the new instance (`recorder:
  purge_keep_days: 10`) rather than discovering the growth later.

If you cannot get back above roughly 40 GiB free, do not do this install this
week. That is not a hedge; a VM disk that hits a full host volume corrupts the
guest filesystem.

---

## The install

### 1. UTM

Already installed, 4.7.5, so this step is done. For the record, since the
question was asked: UTM's site says "UTM is and always will be completely free
and open source. The Mac App Store version is identical to the free version and
there are no features left out of the free version," and "The only advantage of
the Mac App Store version is that you can get automatic updates." So the
difference is automatic updates and about ten dollars going to the project, not
capability. 4.7.5 (build 118) is the current release, 3 January 2026, on QEMU
10.0.2.

### 2. The image

Current release is **HA OS 18.3**, published 17 September 2026. Take the qcow2,
not the vdi/vmdk (those are for VirtualBox and VMware) and not the `.img`:

```sh
cd ~/Downloads
curl -L -O https://github.com/home-assistant/operating-system/releases/download/18.3/haos_generic-aarch64-18.3.qcow2.xz
xz -dv haos_generic-aarch64-18.3.qcow2.xz     # replaces the .xz with the .qcow2
```

`generic-aarch64` is the right architecture for an M3 Pro. `xz` ships with
macOS. Check the release page for a newer 18.x before downloading — this is the
one thing in this document guaranteed to go stale.

### 3. The VM

New VM → **Virtualize** (not Emulate — the guest is ARM64 and so is the host;
emulation here would be ten times slower for no reason) → **Linux**.

- **Boot**: tick **Use UEFI**. Home Assistant will not boot without it.
- **Boot ISO image**: leave empty — skip it. There is no installer; the qcow2
  *is* the installed system.
- **Memory**: 2048 MB is HA's documented minimum and is enough for a starter
  configuration; 4096 MB is comfortable and this Mac has 36 GB. Take 4096.
- **CPU cores**: 2.
- **Storage**: whatever the wizard asks for here gets replaced in a moment;
  accept the default.
- **Shared directory**: skip.
- Name it exactly **`Home Assistant`** — `tools/haos.py` defaults to that name
  (override with `SIMORGH_HAOS_VM`).
- **Tick "Open VM Settings"** on the summary page before Save.

Then, in the VM's settings:

- **Drives**: delete the empty drive the wizard created. **Import Drive** →
  choose the decompressed `haos_generic-aarch64-18.3.qcow2`. Make sure its
  interface is **VirtIO** and it is the boot drive.
- **Network** → **Network Mode: Bridged (Advanced)** → **Bridged Interface:
  `en0`**. `en0` is Wi-Fi on this machine (confirmed:
  `networksetup -listallhardwareports`). Leave "Isolate Guest from Host"
  **off** — the Mac must be able to reach HA.
- Leave everything else alone.

If starting the VM fails with `cannot create vmnet interface: general failure
(possibly not enough privileges)`, that is the HA-community error above. Things
worth trying, in order: quit and reopen UTM; make sure macOS **Internet Sharing
is off** (System Settings → General → Sharing — it takes over `vmnet` and is a
documented conflict, UTM issue #3636); and confirm you picked `en0` and not one
of the inactive `en4`/`en5`/`en11` entries.

### 4. First boot and the pass/fail test

Start it. HA OS boots to a console in under a minute and then spends five to
fifteen minutes on first-run setup before the web UI answers. Do not intervene.

**The test, in this order. Stop at the first failure.**

1. At the VM console, log in as `root` (no password) and run `network info`.
   **Pass:** an address in `192.168.50.0/24`. **Fail:** `169.254.x.x` or nothing
   — the bridge did not take; go to the alternatives above.
2. From a Mac terminal: `ping -c3 homeassistant.local`. **Pass:** it resolves
   and replies. This proves mDNS crosses the emulated bridge *inbound*, which is
   the cheap half.
3. Open `http://homeassistant.local:8123` and complete onboarding (see step 5 —
   or skip straight to restoring the backup).
4. **The real test:** Settings → Devices & Services. The Lutron Caseta bridge at
   192.168.50.108 should appear on its own under Discovered, because HA's
   `lutron_caseta` integration finds it by mDNS/HomeKit announcement. **Pass:**
   it is there within a few minutes. **Fail, and this is the decisive one:** it
   never appears — outbound multicast is not making it out, which is the
   direction the physics predicted. The move has not bought discovery. Decide
   between the Ethernet adapter and going back to the container.
5. Also worth checking while you are there: HA's own Settings → System → Network
   → Network Adapter, which must be on the bridged adapter, and Settings → System
   → Network → "Enable mDNS" if it is offered.

### 5. Migrating, rather than starting again

The container at `127.0.0.1:8123` is a real, onboarded HA 2026.9.3 with 141
components. Do not retype it.

1. In the **container's** UI: Settings → System → Backups → Create backup (full).
   Download it to the Mac.
2. In the **VM's** onboarding screen, the first page offers **"Restore from
   backup"** — use it, not "Create my smart home". Upload the `.tar`.
3. The restored instance comes up with the same users, the same long-lived
   tokens and the same history. **The token in `~/.simorgh/secrets.toml` keeps
   working** — you only need to change the URL.
4. Leave the container **stopped, not deleted**: `python3 tools/ha.py down`. Two
   instances polling the same devices will fight; one stopped instance is the
   fallback.

### 6. Pointing Sim at the VM

Change one line in `~/.simorgh/secrets.toml`:

```toml
"vault:home_assistant:url" = "http://192.168.50.NNN:8123"
```

Use the **IP address**, not `homeassistant.local`. mDNS is fine for a human at a
browser; hanging a daemon's configuration on it means every resolver hiccup
looks like HA being down. Pin that address as a **DHCP reservation on the
ZenWiFi**, the way the NVR at `.42` already is. If HA answers 400 to the new
address, it is the `http:` allow-list — use the IP, or add it in
`configuration.yaml`.

Then `python3 tools/haos.py status`, and restart Sim.

---

## `tools/haos.py`

New, beside `tools/ha.py`, stdlib only, touches nothing under `simorgh/`.

`status` walks the chain in order and names the first broken link — UTM not
installed, VM missing, VM not running, VM running with no LAN address, API not
answering, no token — and exits 1 rather than raising. `up` and `down` drive
`utmctl start` / `utmctl stop`; `down` is deliberately the polite shutdown with
no force flag, because HA has a database open. `ip` prints *every* answer to
"where is it" — the configured URL, mDNS, and `utmctl ip-address` — and then
which one Sim would use, because when those three disagree the disagreement is
the finding. `token` prints the minting steps and the two lines to append.

One design note worth keeping. Finding the address is **not** left to `utmctl`:
UTM can only report a guest's IP when it has a channel into the guest, and HA OS
on the QEMU backend gives it none. mDNS is used instead — which is neat, because
the check "does `homeassistant.local` resolve" is simultaneously the check "did
the bridge work". A shared-mode guest has no LAN name at all.

No secret is printed. `status` says a token is present or absent and nothing
more.

**Verified on this machine** in both states, which happened by luck of timing:
with UTM absent, all five subcommands printed a plain message and `status` exited
1 without a traceback; with UTM 4.7.5 present and no VM defined, `status`
correctly reports `vm 'Home Assistant': does not exist in UTM`. `ip` and `token`
read the live `secrets.toml` and report the container's URL and a configured
token without printing it.

## What happens to `tools/ha.py` and the Docker findings doc

**Both are kept.** Neither is edited except for one pointer.

The Docker path is not a superseded draft, it is the running system and the
fallback: if the pass/fail test in step 4 fails, the container is where Home
Assistant lives, and `tools/ha.py` is how it is driven. The two tools do not
overlap — one speaks `docker`, the other `utmctl`, and they answer different
questions about different instances. Deleting either would mean rewriting it in
a fortnight. The Docker document keeps a note at its top recording that the
creator chose HA OS in UTM on 2026-09-20 and pointing here; the body stands,
including the analysis of the three options, which is still the best summary of
the trade-off and which this decision does not falsify — it changes the weight
on one term in it.

The one thing that *would* justify deleting the Docker path is the Pi. If HA
ends up on its own hardware, both the container and the VM become dead weight on
the same day, and the honest cleanup is then to remove both tools and leave one
findings note explaining where HA actually runs.

## Not done here

Nothing was installed by this work, no image downloaded, no VM created, no
secret written, no test suite run. UTM's arrival and the running container are
the creator's own doing, in parallel. The install is his to run; several steps
need the GUI.

The `utmctl` sub-command surface (`status`, `list`, `start`, `stop`,
`ip-address`) could not be exercised against a real VM, since there is none.
`tools/haos.py` is written not to trust it: `status` falls back from `utmctl
status` to parsing `utmctl list`, and address discovery does not depend on
`utmctl` at all. If a sub-command turns out to be spelled differently in 4.7.5,
the failure is a plain message and one line to fix.
