# Home Assistant on the MacBook Pro, 2026-09-20

> **Superseded as the plan, kept as the fallback.** On 2026-09-20 the creator
> decided to move to Home Assistant OS in a UTM VM with a bridged network
> adapter, for the two things the container cannot have on macOS: mDNS/SSDP
> discovery and Supervisor add-ons. See
> [2026-09-20-home-assistant-os-in-utm.md](2026-09-20-home-assistant-os-in-utm.md)
> — which also **corrects the last section of this document**: bridging over
> Wi-Fi is far less certain than the closing paragraph here implies, and this
> house has no Ethernet. The container below is running today, `tools/ha.py`
> drives it, and it stays as the fallback if the bridge does not hold. Nothing
> here is withdrawn; the three-option analysis still stands.

Sim has had a complete Home Assistant integration since before the rebirth --
`simorgh/contracts/home/client.py` (REST, stdlib, no dependency),
`simorgh/domains/home/tools.py` (`home_find`, `home_state`, `home_describe`,
`home_call`, `home_undo`), a policy shared with Guardian
(`contracts/home/policy.py::classify_call`), and `[guardian.physical]
auto_approve = false` already set in `~/.simorgh/simorgh.toml`. What it has
never had is a Home Assistant to talk to: the 2026-09-18 review measured zero
`HOME_ASSISTANT_*` keys in the environment, in `~/.simorgh/secrets.toml` or in
the vault, which is why every `home_*`, `energy_*` and `media_*` tool refuses
at call time. This note is about closing that gap on the machine we actually
have: an Apple Silicon MacBook Pro, macOS 26.5.2, Docker Desktop installed and
its daemon currently stopped.

## The three real options

**HA Container under Docker Desktop.** One `docker run`, one bind-mounted
config directory, HA answers on `localhost:8123`. Upgrades are `docker pull`
plus recreate, about a minute a month. It is the only option here that needs
nothing installed that is not installed already. Two things it does not give
you. First, **no add-ons**: the Supervisor is what installs Mosquitto, Z-Wave
JS UI, ESPHome, Node-RED and the backup add-ons, and the container image has no
Supervisor. That is the usual reason people regret this choice -- but each of
those add-ons is a plain container of its own, so the cost is running two
containers instead of one add-on page, not losing the capability. Second, and
more serious on a Mac: Docker Desktop has **no host networking**, so the
container sits behind a NAT inside a Linux VM and mDNS/SSDP discovery does not
reach it. Integrations that find devices by broadcast (Chromecast, Sonos,
HomeKit, ESPHome) have to be added by IP address instead of appearing on their
own. For this household that is a small loss: the TV is already driven by Sim's
own cast tools and the cameras by the Reolink NVR at a fixed address.

**HA Core in a Python venv.** `pip install homeassistant` into a 3.13 venv and
run it natively. It is the only option that runs on the host's own network, so
discovery works properly. It also has no Supervisor and therefore no add-ons,
the HA project documents it as an advanced install it would rather you did not
choose, and the upkeep is the worst of the three: a `pip install --upgrade`
every month that occasionally needs a native build, and a forced migration each
time HA moves its minimum Python version. Nothing isolates it from the rest of
this machine's Python, which is the same machine that runs Sim, the voice stack
and the benchmark harness.

**HA OS in a VM (UTM, free, or Parallels).** The full product: Supervisor,
add-ons, one-click updates, built-in scheduled backups. In exchange you run a
whole second operating system -- allow 2 GB of RAM and 32 GB of disk that stay
allocated -- give the VM a bridged network adapter so discovery works, and
remember to start it. Setup is thirty to forty-five minutes of downloading a
qcow2 image and clicking through UTM. Once it is up its upkeep is the lowest of
the three. It is also the only one that can pass a USB Zigbee or Z-Wave stick
through to HA; Docker Desktop on macOS cannot pass USB devices at all.

## Take the container

Docker Desktop is already installed, the whole setup is two commands, and
`docker` gives both the creator and Claude Code a scriptable handle on it --
is it running, start it, stop it, show me the log -- which none of the other
two do as cleanly. The two things it costs, add-ons and broadcast discovery,
cost this house little today: Sim's devices are reached by address, and the
add-ons a household would actually want are containers anyway. The day a Zigbee
or Z-Wave USB stick arrives is the day this choice becomes wrong, and on that
day an HA backup file restores into HA OS in UTM without redoing any of the
configuration. Choosing the container now does not make that move harder.

## Doing it

```sh
open -a Docker                       # wait for the whale in the menu bar
python3 tools/ha.py up --create      # creates the container; first pull is ~1.5 GB
python3 tools/ha.py status           # daemon, container, API, token
```

`up --create` runs exactly this, with the machine's own timezone filled in:

```sh
docker run -d --name homeassistant --restart unless-stopped \
  -e TZ=<the machine's zone> \
  -v ~/.homeassistant/config:/config \
  -p 8123:8123 \
  ghcr.io/home-assistant/home-assistant:stable
```

`/etc/localtime` is deliberately not mounted the way the HA documentation shows:
on macOS it is a symlink into a path Docker Desktop does not share, so the mount
fails. `TZ` does the same job.

Then open `http://localhost:8123`, create the owner account, and mint a
long-lived access token from the user page (Security tab, bottom of the
sidebar). `python3 tools/ha.py token` prints those steps and the two lines to
append.

## Where the credentials go

`_HomeTool._lookup` (`simorgh/domains/home/tools.py:65`) asks the secret store
for `vault:home_assistant:url` and `vault:home_assistant:token` first, and falls
back to the `HOME_ASSISTANT_URL` and `HOME_ASSISTANT_TOKEN` environment
variables. The store is a chain -- environment, then `~/.simorgh/secrets.toml`,
then the encrypted vault -- and `FileSecretStore` reads flat top-level keys, so
a quoted key in that file resolves the `vault:`-prefixed name without the
keychain being involved:

```toml
"vault:home_assistant:url" = "http://127.0.0.1:8123"
"vault:home_assistant:token" = "<the long-lived token>"
```

`chmod 600` the file or the store refuses to load it at all. No config change is
needed on top: `[execution] secrets` in `~/.simorgh/simorgh.toml` already lists
`"vault:*"`, which is what scopes both names to the tools.

Note the asymmetry, because it has caught people before: a plain
`HOME_ASSISTANT_TOKEN = "..."` key in `secrets.toml` does **not** work. The
fallback reads `os.environ`, not the store, so the file only ever answers to the
`vault:`-prefixed names.

## mDNS discovery cannot be switched on for the container, and what to do instead

Asked directly (the creator, 2026-09-20): how do you enable discovery of the Lutron
bridge over mDNS for Home Assistant in Docker?

You cannot, on this machine, and it is worth being plain about why rather
than leaving somebody to hunt for the flag.

Discovery works by listening for multicast on the local network --
`224.0.0.251:5353` for mDNS, `239.255.255.250:1900` for SSDP. A container on
Docker Desktop for Mac is not on the local network. It is inside a Linux VM
whose networking, on this install, is gvisor: a **user-space TCP/IP stack**
(`NetworkType: gvisor` in Docker's own settings) that translates outbound
connections and has no L2 path to the Mac's Wi-Fi interface at all. LAN
multicast never reaches it, so there is nothing for Home Assistant to hear.

The two things people reach for do not help here:

- **`--network host`.** Docker Desktop has had a host-networking beta since
  4.34 and this install has it off (`HostNetworkingEnabled: false`, version
  4.88.0). Turning it on would join the container to the **VM's** network
  namespace, which is still the gvisor stack behind the Mac -- not the Mac's
  own LAN. It solves the problem it is named for on Linux and not on macOS.
- **`macvlan`.** It needs L2 access to the physical interface to give the
  container its own MAC on the LAN. The VM has none. And the house is on
  Wi-Fi, where a station cannot carry extra MAC addresses at all -- macvlan
  over Wi-Fi is a dead end even on Linux.

**For the Lutron bridge, none of this costs anything.** Discovery would only
have saved typing an address that is already known: `192.168.50.108`
(`Lutron-047d94d9.local`, `cc:33:31:1e:7c:b1`, LEAP listening on 8081,
`SYSTYPE=SmartBridge`, firmware 08.28.11f000). Add the Caseta integration by
hand with that address and press the button on the back of the bridge when it
asks; the pairing is identical either way. Pin the address as a DHCP
reservation on the ZenWiFi first, the way the NVR at `.42` already is --
manual configuration plus a moving address is a thing that works until the
router reboots.

**If discovery matters generally**, that is the day to move to HA OS in a UTM
VM with a *bridged* network adapter, which is the escape hatch this document
already recommends keeping open: the VM becomes a real device on the LAN with
its own address, so mDNS and SSDP work, and add-ons come with it. Test the
bridge over Wi-Fi before committing to it -- `vmnet` bridged mode is reliable
over Ethernet and mixed over Wi-Fi -- and restore an HA backup into it rather
than starting again.

## `tools/ha.py`

`status` walks the chain in order and names the first link that is broken --
docker CLI missing, daemon stopped, container absent, container stopped, no
token, API not answering -- and exits 1 rather than raising when Docker is down,
which is the normal state of a laptop that has just booted. It prints whether a
token is configured and never the token itself. `up`, `down`, `logs [n]` and
`token` are the rest. It is stdlib only and touches nothing under `simorgh/`.

Verified on this machine with the daemon stopped: `status` reports the daemon
and exits 1, `up`/`down`/`logs` say the same thing plainly, `token` prints the
instructions and reports that nothing is configured yet.

## Not done here

Nothing was installed, no image pulled, no daemon started, no secret written.
The install is the creator's to run. Once HA answers, the next piece of work is
the one the review named: a Guardian `HomeRule` that recomputes `classify_call`
from the proposal's own arguments rather than trusting the label the tool
proposed, so a mislabelled `lock.unlock` is still escalated.
