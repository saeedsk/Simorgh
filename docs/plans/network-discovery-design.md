# Network discovery: Sim listens to the house and finds what is on it

Design pass, 2026-09-09 (Fable). Implementation is handed to Opus; this
document is written so that nothing below needs a design decision.
Companion to `home-automation-design.md` -- discovery is how the `home`
subsystem's registry gets *populated* and how a new device gets
*registered* in Home Assistant. The five invariants and the ten-step
wiring checklist in `resourcefulness-toolset.md` apply to every tool.

The ask: discover every device on the home network at layer 2, layer 3
and the application layer -- IoT, cameras, network gear, smart devices
-- group and categorise them automatically, and connect/register them
in their systems.

## 0. Three facts that shape everything

1. **Guardian refuses `socket.` in any generated code**
   (`guardian/config.py` denylist: "opens raw network sockets"), and
   `scapy`/raw frames need `CAP_NET_RAW`. So discovery cannot be
   something Sim *scripts* through `run_script`; it must be
   **built-in tools**, written once, reviewed once, gated by Guardian
   as tools. This is the right shape anyway: a port scanner is not a
   thing an autonomous system should be able to improvise.
2. **Layer-2 traffic does not cross a VPN.** ARP, mDNS, SSDP,
   WS-Discovery and DHCP are broadcast/multicast on the local segment.
   Tailscale carries none of it. Discovery runs on a machine that is
   physically on the home LAN -- the HA box, or a Pi/NUC beside it --
   which is also where `home` should run. The Sim laptop on Wi-Fi works
   for development; note that Wi-Fi client isolation on some routers
   blocks it.
3. **This machine has almost none of the tooling** (checked):
   `tcpdump` and `dns-sd` yes; `nmap`, `arp-scan`, `scapy`, `zeroconf`,
   `bleak`, `python-kasa`, an OUI database -- all absent. One
   interface, `en0 192.168.50.0/24`. Every dependency below is optional,
   probed by `capabilities`, installable by `install_package`, and its
   absence is a clean refusal naming the package -- the Tier 5 rule.

## 1. Open-source inventory

| tool | layer | what it gives | how Sim uses it | privilege |
|---|---|---|---|---|
| **`tcpdump`** (present) / **`scapy`** | L2 passive | ARP, DHCP, mDNS, SSDP, LLDP/CDP frames as they happen | `net_listen` -- the "listen to the network" half | root / `CAP_NET_RAW` |
| **`arp-scan`** or scapy `arping` | L2 active | every host on the segment in ~2s, with MAC, even ones that ignore ping | `net_scan arp` | root |
| **IEEE OUI registry** (`oui.csv`, via `manuf` or a direct download) | L2 | MAC prefix → vendor ("Amazon Technologies", "Ring LLC", "Hangzhou Hikvision") | first classification signal | none |
| **a standard OSS port scanner** (e.g. `nmap` + `python-nmap`) | L3/L4 | reachability sweep, open-port enumeration, service banners, OS guess | `net_scan ping|ports|deep` | root for SYN/OS; unprivileged connect-scan works |
| **`python-zeroconf`** | app: mDNS / DNS-SD | `_hue._tcp`, `_googlecast._tcp`, `_hap._tcp`, `_esphomelib._tcp`, `_shelly._tcp`, `_ipp._tcp`, `_airplay._tcp`, `_matter._tcp`, `_meshcop._udp`, `_sonos._tcp`, `_rtsp._tcp`… with TXT records | the richest single source for smart devices | none |
| **`async-upnp-client`** (`ssdp`) | app: SSDP / UPnP | M-SEARCH `ssdp:all`: device type, friendly name, manufacturer, model, presentation URL -- Echos, TVs, Sonos, routers, NAS, Hue bridge | | none |
| **`WSDiscovery`** (`python-ws-discovery`) | app: WS-Discovery | every ONVIF camera/NVR announces here; gives the device service URL | cameras specifically | none |
| **`onvif-zeep-async`** | app: ONVIF | `GetDeviceInformation` (manufacturer/model/firmware/serial), `GetProfiles` → RTSP URLs | camera identification; register into HA `onvif` | needs camera creds for most calls |
| **`python-kasa`** | app | TP-Link Kasa plugs/bulbs/strips, UDP 9999 broadcast; full identity, no creds | | none |
| **`tinytuya`** | app | Tuya/Smart Life devices, UDP 6666/6667 beacons (ids + IPs; keys need the cloud) | detect, not control | none |
| **`aiohue`** | app | Hue bridge via mDNS/`discovery.meethue.com`, then every bulb behind it | one hub → many devices | bridge button press |
| **`bleak`** | Bluetooth LE | advertisements: name, manufacturer data, service UUIDs (Govee, Xiaomi, Tile, Apple, sensors) | `net_scan ble` | none on Linux with BlueZ; macOS prompts |
| **`pysnmp`** | L2 via managed switches | `dot1dTpFdbTable` (MAC → switch port), LLDP neighbors | which port a device is on = which room | none, needs community string |
| **`aiounifi`** / OPNsense / pfSense API | L2/L3 | the router's DHCP leases + client list + AP per client + signal | best source of hostnames and *which AP* = which floor | API key |
| **Home Assistant discovery** (`config_entries/flow` WS) | app | what HA has already seen (its own `zeroconf`, `ssdp`, `dhcp`, `bluetooth`, `usb` discovery) and not yet configured | the registration target and a free second opinion | HA token |
| **Frigate** | app | camera streams already known | | |
| **Zigbee2MQTT** / **Z-Wave JS** | non-IP | device lists over MQTT; these devices have no IP and no MAC | included in the inventory as `transport: zigbee` | MQTT |

**Not used**: `fingerbank`/`Fing` (API key, cloud, proprietary
fingerprints); `Zeek`/`Suricata` (a full NIDS is a different product);
vulnerability-probing or credential-guessing scripts of any kind --
**Sim never attempts a login it was not given**; `netdisco` (archived,
superseded by HA's own discovery).

## 2. The `network` subsystem (`simorgh/network/`)

An 18th subsystem. Not folded into `home`: discovery is a *sense*
(what is on the wire) and `home` is a *domain* (what the house should
do). `home`'s registry consumes `network`'s inventory; `network` knows
nothing about lights.

```
simorgh/network/
  api.py          Device, Observation, Evidence, Category, Group dataclasses
  config.py       [network] (section 2.1)
  interfaces.py   which interfaces/subnets exist (psutil), which are allowed
  oui.py          MAC prefix → vendor; bundled subset + downloaded full table
  listen.py       passive: tcpdump/scapy → Observations (section 3.1)
  scanners/       one module per active method, common signature (section 3.2)
      arp.py ping.py mdns.py ssdp.py wsd.py ports.py http.py rtsp.py
      onvif.py kasa.py tuya.py hue.py ble.py snmp.py router.py hass.py zigbee.py
  identify.py     evidence → (category, vendor, model, confidence) (section 4)
  grouping.py     groups: room / floor / vendor / category / subnet / risk (section 5)
  inventory.py    the device table: merge, identity, history; ledger stream `network:devices`
  monitors.py     new device, vanished, changed IP, new open port, no-auth camera… (section 6)
  register.py     hand a device to its system: HA config flow, Frigate, aliases (section 7)
  service.py      Service: start/stop/health, the listener task, scheduled sweeps
  fakes.py        FakeNetwork: scripted responders for every scanner, for tests
```

### 2.1 Config

```python
@dataclass(frozen=True)
class Config:
    enabled: bool = False
    # REQUIRED for any active scan. Never inferred silently: a wrong
    # CIDR is an unwanted probe of somebody else's network. `interfaces.py`
    # proposes the RFC1918 subnets it sees; `net_scan` refuses until
    # one is written here or passed with `confirm: true`.
    allowed_cidrs: tuple[str, ...] = ()
    interfaces: tuple[str, ...] = ()          # empty = all that carry an allowed CIDR
    listen: bool = True                       # passive listener on by default when enabled
    listen_helper: str = "tcpdump"            # tcpdump | scapy
    sweep_every_s: float = 3600.0             # scheduled arp+mdns+ssdp sweep (Kernel scheduler)
    deep_sweep_every_s: float = 86400.0       # + ports/http/rtsp, at 03:00 local
    # Active-scan politeness. A home router can be knocked over by an
    # an enthusiastic port sweep; these are the defaults, not the ceiling.
    ports_profile: str = "iot"                # iot | common | full (full = human)
    max_hosts_per_scan: int = 256
    max_rate_pps: int = 200
    per_host_timeout_s: float = 5.0
    oui_path: str = "workspace/network/oui.csv"
    inventory_path: str = "workspace/network/inventory.json"   # human-readable mirror of the ledger
    # Section 6
    alert_new_device: bool = True
    alert_new_open_port: bool = True
    quiet_hours: tuple[int, int] = (23, 7)     # new-device alerts batch into the digest
    # Section 3.2 / ble
    ble: bool = False                          # opt in; macOS prompts for permission
    # Router / switch integrations, all optional, all env-keyed
    router_kind: str = ""                      # unifi | opnsense | pfsense | ""
    router_url_env: str = "ROUTER_URL"
    router_token_env: str = "ROUTER_TOKEN"
    snmp_community_env: str = "SNMP_COMMUNITY"
    snmp_hosts: tuple[str, ...] = ()
```

`ports_profile` tables live in `scanners/ports.py`:

- `iot` (default, ~30 ports): 21 22 23 53 80 81 443 554 631 1883 1900
  5000 5353 5683 6666 6667 8000 8080 8081 8443 8554 8883 9000 9999
  37777 (Dahua) 34567 (XM cameras) 40317 55442 55443 (Echo) 49152-49155
  (UPnP) 62078 (iOS) 5900 3389 445 139
- `common`: the scanner's top ~200 ports
- `full`: 1-65535 → **human-approved only**, and one host at a time.

## 3. Sensing

### 3.1 Passive listening (`listen.py`) -- the "listen to the network" half

Runs continuously as a background task when `enabled` and `listen`.
Watches for, and turns into `Observation`s:

| frame | yields |
|---|---|
| ARP request/reply | MAC↔IP binding, liveness, and *who talks to whom* (a device ARPing for the gateway every 30s is alive) |
| DHCP Discover/Request | hostname (option 12), vendor class (option 60: `android-dhcp-13`, `MSFT 5.0`, `udhcp`, `HUAWEI`…), parameter request list (option 55 -- a fingerprint as good as an OS guess), MAC |
| mDNS announcements | service types + TXT without asking (devices announce on boot and periodically) |
| SSDP NOTIFY | UPnP devices announcing `ssdp:alive` with their location URL |
| LLDP / CDP | switch name + port for the device transmitting it (usually only network gear) |
| IGMP joins | which multicast groups → Chromecast/Sonos/Matter hints |
| DNS queries (only the *names*, only from allowed CIDRs, never payloads) | `device-metrics-us.amazon.com` → an Echo; `*.ring.com` → Ring; `*.tuya.com`; `*.govee.com`; `time.windows.com` -- **the single best classifier for cloud-tethered IoT that exposes no ports** (Ring devices expose nothing locally) |

Privilege, decided: **Sim never runs as root.** The listener spawns
`tcpdump -i <if> -l -n -e -tt <bpf filter>` and parses its text lines
(no pcap library dependency, no raw socket in Sim's process). tcpdump
must be runnable: on Linux, `setcap cap_net_raw,cap_net_admin+eip
/usr/bin/tcpdump` once (documented in `docs/home/setup.md`), or a
sudoers rule limited to exactly that binary; on macOS, membership in
the `access_bpf` group (Wireshark's ChmodBPF installer does this). The
capability probe checks by running `tcpdump -c 1 -i <if>` with a 3s
timeout and reports *which* of the three fixes applies when it fails.
The BPF filter is fixed in code (arp, udp port 67/68/5353/1900, ether
proto lldp, igmp, udp port 53) -- Sim cannot widen it; a "listener"
that could capture arbitrary traffic is a different tool with a
different name and a different Guardian entry.

DNS names are the one privacy-sensitive stream. Decided: recorded as
`(device, domain, count, first, last)` aggregates in the inventory --
never full query logs, never for hosts outside `allowed_cidrs`,
`listen_dns: bool = True` in config to turn off, and the daily digest
says the feature is on.

### 3.2 Active scanners (`scanners/`)

One signature for all:

```python
class Scanner(Protocol):
    name: str                       # "arp", "mdns", ...
    layer: Literal["l2", "l3", "app", "ble", "integration"]
    needs: tuple[str, ...]          # packages / binaries; probed
    privileged: bool
    async def available(self) -> tuple[bool, str]
    async def scan(self, targets: Targets, *, budget: Budget, emit: Callable[[Observation], Awaitable[None]]) -> ScanSummary
```

`Targets` = CIDRs / hosts / interface; `Budget` = `max_hosts`,
`max_rate_pps`, `deadline`. Every scanner emits `Observation(source,
mac?, ip?, evidence: dict, ts)` and never a `Device` -- identity
resolution is `inventory.py`'s job, because one device produces
observations from six scanners and they have to merge.

| scanner | method | evidence emitted |
|---|---|---|
| `arp` | `arp-scan --localnet` if present, else scapy `arping`, else a *ping sweep followed by reading the ARP cache* (`ip neigh` / `arp -a`) -- the unprivileged fallback that always works | mac, ip, vendor(oui) |
| `ping` | reachability sweep via the port scanner or async ping (`icmplib`, unprivileged mode) | ip alive, ttl (64 = Linux/IoT, 128 = Windows, 255 = network gear) |
| `mdns` | `zeroconf` `ServiceBrowser` on `_services._dns-sd._udp.local` then each type; 10s | services, TXT (Hue `bridgeid`, HAP `ci` = **HomeKit category code**, `md` = model, `id`; Chromecast `md`/`fn`; ESPHome `mac`/`board`; Shelly `app`/`gen`) |
| `ssdp` | M-SEARCH `ssdp:all` ×3, then GET each `LOCATION` XML | deviceType, friendlyName, manufacturer, modelName, modelNumber, serialNumber, presentationURL, `SERVER` header |
| `wsd` | WS-Discovery Probe | ONVIF `XAddrs`, `Scopes` (name/hardware/location), type `NetworkVideoTransmitter` |
| `ports` | the port scanner (unprivileged connect mode) with `ports_profile`, `--max-rate`, `-T2`; fallback: asyncio `open_connection` per port | open ports |
| `http` | GET `/` on 80/81/443/8080/8081/8443/8000: `Server` header, `<title>`, `WWW-Authenticate` realm (`Hikvision`, `Dahua`, `Reolink`, `TP-LINK`, `NETGEAR`…), favicon mmh3 hash vs a bundled table of ~60 known IoT favicons, `/onvif/device_service`, `/cgi-bin/`, `/api/system/info` (Frigate/HA/Shelly probes) | vendor/model/role hints, **auth_required: bool** |
| `rtsp` | `OPTIONS rtsp://ip:554/` | RTSP present, `Server:` header, 401 vs 200 (**a 200 means an unauthenticated stream**) |
| `onvif` | `GetDeviceInformation` unauthenticated (many cameras answer), `GetCapabilities` | manufacturer, model, firmware, serial |
| `kasa` | `kasa` discovery broadcast | alias, model, mac, plug/bulb/strip type |
| `tuya` | listen for 6666/6667 beacons 10s | gwId, productKey, version |
| `hue` | mDNS `_hue._tcp` + `/api/config` (no key needed for name/model/bridgeid) | bridge; with a key, every light/sensor behind it |
| `ble` | `bleak` 10s scan | name, manufacturer id (Apple 0x004C, Govee 0x8801/…, Xiaomi 0x038F), service UUIDs, rssi |
| `snmp` | `dot1dTpFdbTable`, `lldpRemTable` on `snmp_hosts` | mac → switch port; neighbor names |
| `router` | UniFi/OPNsense/pfSense client + lease list | hostname, AP/SSID, signal, lease age, `is_wired` |
| `hass` | HA `config_entries/flow/progress` + `zeroconf`/`ssdp`/`dhcp` discoveries | what HA already found, and the flow handler that would adopt it |
| `zigbee` | Zigbee2MQTT `bridge/devices`, Z-Wave JS node list | non-IP devices with `transport`, ieee, model, vendor |

`net_scan` runs scanners **in a fixed order** -- `arp`, `ping`, `mdns`,
`ssdp`, `wsd`, `kasa`, `tuya`, `hue`, `hass`, `zigbee` (the "quick"
set, ~30s, unprivileged where possible, no port scanning) -- and only
with `depth: "deep"` adds `ports`, `http`, `rtsp`, `onvif`, `snmp`,
`router`, `ble`. Quick is `reversible`; deep is `irreversible`-gated
(section 8). Every scanner is bounded by `Budget` and reports
`{hosts_seen, observations, skipped_reason}` -- a scanner whose
dependency is missing is a *row in the summary* naming the package,
never a silent zero.

## 4. Identification (`identify.py`) -- evidence → what is this thing

Pure function: `identify(evidence: dict) -> Identity(category,
vendor, model, role, confidence, why: tuple[str, ...])`. Rules first,
ordered by specificity; cognition only for the leftovers.

**Categories** (closed set; `home`'s registry and the grouping use them):

```
camera, doorbell, nvr, voice_assistant, smart_display, hub_bridge, light, light_strip,
plug_switch, sensor, thermostat, lock, garage, vacuum, tv_media, speaker, streaming_stick,
game_console, printer, nas_storage, router, switch, access_point, mesh_node, phone, tablet,
laptop, desktop, watch_wearable, ereader, appliance, ev_charger, solar_energy, iot_unknown, unknown
```

**Signal → category table** (the core of `identify.py`; each row is a
test):

| evidence | verdict | conf |
|---|---|---|
| WS-Discovery `NetworkVideoTransmitter` or ONVIF answered or RTSP 554 open | `camera` | 0.95 |
| OUI ∈ {Ring LLC} or DNS `*.ring.com` | `doorbell` if OUI/DNS says doorbell, else `camera` (Ring cams) | 0.9 |
| OUI ∈ {Amazon Technologies} + SSDP `MediaRenderer` + ports 8080/40317/55443 | `voice_assistant`; + HTTP title/`fn` contains "Show" → `smart_display` | 0.9 |
| OUI Amazon + no open ports + DNS `device-metrics-us.amazon.com` | `voice_assistant` (Dot) | 0.7 |
| mDNS `_hap._tcp` TXT `ci` | HomeKit category code map: 2 bridge, 5 light, 7 outlet, 8 switch, 9 thermostat, 10 sensor, 11 security, 12 door, 13 window, 14 window covering, 17 IP camera, 18 video doorbell, 19 air purifier, 31 speaker | 0.95 |
| mDNS `_hue._tcp` | `hub_bridge` (Hue); devices behind it via `aiohue` → `light` each | 0.95 |
| mDNS `_googlecast._tcp` TXT `md` | `Chromecast` → `streaming_stick`; `Google Nest Hub` → `smart_display`; `Google Home` → `speaker`; a TV model → `tv_media` | 0.9 |
| mDNS `_esphomelib._tcp` / `_shelly._tcp` TXT `app` | `sensor`/`plug_switch`/`light` per app/board | 0.85 |
| mDNS `_matter._tcp` / `_matterc._udp` | device type from TXT `DT` (Matter device type id: 0x0100 on/off light, 0x010C color temp light, 0x010A plug, 0x0301 thermostat, 0x0015 contact sensor, 0x0107 occupancy, 0x000A door lock…) | 0.9 |
| mDNS `_meshcop._udp` | `hub_bridge` (Thread border router -- often an Echo/Nest/Apple TV) | 0.85 |
| Kasa discovery `model` | plug/bulb/strip → `plug_switch` / `light` / `light_strip` | 0.95 |
| Tuya beacon | `iot_unknown` (vendor Tuya) until HA adopts it and names the type | 0.6 |
| OUI ∈ {Govee, Yeelight, LIFX, Nanoleaf, Wiz} or BLE manufacturer id Govee | `light` / `light_strip` (Govee, Nanoleaf → strip) | 0.85 |
| SSDP `InternetGatewayDevice` / TTL 255 + ports 53/80/443 + is default gateway | `router` | 0.95 |
| LLDP transmitter / SNMP bridge MIB answers | `switch` / `access_point` | 0.9 |
| OUI ∈ {Ubiquiti, TP-Link Deco, eero, Netgear Orbi} + not gateway | `access_point` / `mesh_node` | 0.85 |
| mDNS `_ipp._tcp` / port 631 / 9100 | `printer` | 0.95 |
| SSDP `MediaServer` + ports 445/5000/5001 / OUI Synology/QNAP | `nas_storage` | 0.9 |
| OUI Apple + DHCP vendor class / `_companion-link` / `_rdlink` | `phone` (iPhone: hostname/`_apple-mobdev`), `laptop`/`desktop` (`_smb`/`_rfb`), `watch_wearable`, `tablet` | 0.7 |
| DHCP `android-dhcp-*` | `phone`/`tablet`; with SSDP `MediaRenderer` and a TV OUI → `tv_media` | 0.7 |
| OUI Sony/Nintendo/Microsoft + ports 3074/… | `game_console` | 0.8 |
| HTTP realm/title Hikvision/Dahua/Reolink/Amcrest/Wyze/Eufy/Arlo | `camera` (vendor set) | 0.9 |
| HTTP title contains "NVR" / Dahua 37777 + many RTSP paths | `nvr` | 0.85 |
| OUI ∈ {Ecobee, Google (Nest) + `_hap` ci 9, Honeywell/Resideo, Emerson} | `thermostat` | 0.85 |
| OUI ∈ {August, Schlage, Yale, Level} or Matter DT 0x000A | `lock` | 0.9 |
| OUI ∈ {Chamberlain/myQ} | `garage` | 0.9 |
| OUI ∈ {iRobot, Roborock, Ecovacs} | `vacuum` | 0.9 |
| OUI ∈ {Tesla, ChargePoint, Wallbox, Enphase, SolarEdge} | `ev_charger` / `solar_energy` | 0.9 |
| OUI ∈ {Samsung/LG/Whirlpool/GE Appliances} + no media services | `appliance` | 0.6 |
| anything with an OUI and nothing else | `iot_unknown` (vendor known) | 0.3 |
| randomised MAC (locally-administered bit set) + DHCP Apple/Android | `phone` (privacy MAC) -- and **do not alert as "new device" every day**; match on hostname + DHCP fingerprint instead | 0.6 |

Multiple rows may match; take the highest confidence, and when two
categories tie above 0.8 record both in `why` and mark
`needs_review`. A device's identity is *monotone*: a later scan may
raise confidence or add a model, never silently replace a 0.95
`camera` with a 0.6 `appliance` -- a downgrade needs `why` and shows
in `net_devices` as a change.

**Cognition for the leftovers**: `identify` returns `unknown`/
`iot_unknown` for maybe 10% of a real house. `net_identify <device>`
gathers the full evidence blob (banners, TXT, DNS names, OUI, ports)
and asks cognition for a category from the closed set + a one-line
reason, at most once per device per day (Curiosity budget). Its answer
is stored with `source: "cognition"` and a confidence cap of 0.7; it
never overrides a rule-based verdict ≥ 0.8. The prompt must include
the category list verbatim and demand one of them or `unknown`.

**Vendor**: OUI first (bundled subset in `simorgh/network/data/
oui-iot.csv`, ~1,500 rows covering consumer IoT vendors; the full IEEE
table downloaded on first `net_scan` to `oui_path` and refreshed
monthly via the scheduler), then SSDP/ONVIF/mDNS `manufacturer`. Say
which.

## 5. Grouping (`grouping.py`)

Groups are *views* over the inventory, computed, never stored as
truth (a device is in several):

| group | derived from |
|---|---|
| `by_category` | §4 |
| `by_vendor` / `by_ecosystem` | vendor → ecosystem map: Amazon+Ring → "Amazon"; Google+Nest → "Google"; Hue+Signify → "Hue"; Kasa+Tapo → "TP-Link"; Apple; Tuya-based brands → "Tuya" |
| `by_room` | in order of trust: HA area of the matching entity (once registered) → router AP/switch port → LLDP → mDNS/SSDP name containing a room word ("Kitchen Echo", "bedroom-cam") → BLE rssi triangulation is NOT attempted |
| `by_floor` | AP/mesh node → floor, from a small `workspace/network/topology.toml` the creator fills once (`[ap.upstairs] mac = "…"`) |
| `by_subnet_vlan` | CIDR / VLAN tag |
| `by_transport` | wifi / wired / zigbee / zwave / thread / ble / cloud_only |
| `by_hub` | devices behind a bridge (Hue lights ← Hue bridge; Zigbee ← coordinator; Ring ← Ring cloud) -- a tree, rendered as one |
| `by_risk` | §6: no-auth camera, telnet open, default-credential banner, no updates in a year (firmware date from ONVIF/HTTP), talks to unexpected countries -- **advisory only** |
| `by_system` | which system should own it: `home_assistant` (lights, plugs, sensors, thermostat, locks…), `frigate` (cameras), `alexa` (Echos), `ring` (Ring, via HA's Ring integration), `none` (phones, laptops -- tracked for presence only), `unknown` |

`net_group <group>` renders one; `net_devices` (no args) renders the
inventory grouped by category with counts. Rows also go to `results/`
so `query_data` can `select vendor, count(*) from 'results/<id>.json'
group by 1`.

## 6. Monitoring (`monitors.py`) -- runs on the listener stream and after sweeps

| monitor | fires when | severity |
|---|---|---|
| `new_device` | a MAC never seen before joins (ARP/DHCP) -- unless it is a randomised MAC matching a known hostname+fingerprint | info in quiet hours (digest), warn otherwise, **critical if it is a `camera`/`router`/`access_point` nobody added** |
| `vanished` | a device with `role: infrastructure` or `category: camera` unseen for 15 min; other categories 24h | warn / info |
| `changed_ip` / `changed_mac_for_ip` | binding flips (DHCP churn is info; a *known* IP answering with a new MAC = warn: possible ARP spoof or a swapped device) | info / warn |
| `new_open_port` | a deep sweep finds a port open that was closed last time | warn |
| `unauthenticated_stream` | RTSP 200 without auth, HTTP camera UI without `WWW-Authenticate` | critical -- and the digest repeats it daily until fixed |
| `telnet_or_ftp` | port 23/21 open on an IoT device | warn |
| `default_banner` | HTTP realm/title matching a default-credential-known product (a bundled list of ~40 models) -- **detection only; Sim never tries the credentials** | warn |
| `unexpected_destination` | a device's DNS names include a domain outside its vendor's known set (a bundled per-ecosystem allow-map; e.g. a camera resolving `*.xyz` mining pools) | warn |
| `firmware_stale` | ONVIF/HTTP firmware build date > 2 years | info |
| `listener_down` | tcpdump exited / no frames for 10 min on a live network | critical (via `notify`, like `ha_unreachable`) |
| `subnet_mismatch` | an allowed CIDR no longer matches any interface | warn |

Delivery is identical to `home`'s: `network.monitor.alert` → severity
routing → `notify` / digest; idempotent per (monitor, device) until
cleared. The daily digest (merged with `home`'s) leads with *new
devices this week* and *unresolved risks*.

## 7. Registration (`register.py`) -- "connect and register them in their system"

The inventory says `by_system`. Registration hands a device to that
system, which is nearly always **Home Assistant** (and Frigate for
cameras):

- **HA config flow, programmatic**: WS `config_entries/flow/start`
  `{handler: "<integration>", context: {source: "user"}}` then
  `config_entries/flow/<id>` with step data. For discovery-based
  integrations HA has usually *already* opened a flow
  (`hass` scanner, §3.2) -- then `net_register` just *confirms* it
  (`step_id: "confirm"`) which is a one-click "yes, add it". Handler
  map from category+vendor: `onvif` (cameras), `hue`, `tplink` (Kasa),
  `tuya`, `esphome`, `shelly`, `cast`, `sonos`, `ring`, `nest`,
  `ecobee`, `matter`, `homekit_controller` (for `_hap` devices not in
  another ecosystem), `ipp`, `synology_dsm`, `unifi`, `alexa_media`
  (via HACS -- flag if HACS is missing).
- **Steps needing a secret** (camera username/password, Hue button,
  Tuya cloud keys, Ring 2FA, an API key): `net_register` gets the flow
  to the step, reports *exactly which field it needs*, and stops →
  `needs_human`. The creator finishes in HA's UI, or supplies the value
  once via `net_register <device> --with username=… password=…` which
  goes to HA and **never** into the ledger, metadata, or output
  (test: a password argument containing `SECRET` appears nowhere).
  **Sim never guesses a credential, and never tries a default one.**
- **Frigate**: cameras with a known RTSP URL (from ONVIF `GetProfiles`
  with creds, or the vendor's standard path table: Hikvision
  `/Streaming/Channels/101`, Dahua `/cam/realmonitor?channel=1&subtype=0`,
  Reolink `/h264Preview_01_main`, Amcrest, Wyze RTSP firmware…) →
  `net_register <cam> frigate` writes the camera block into Frigate's
  config via its API (`PUT /api/config/set` + `restart`) -- with
  `detect` enabled at 5 fps and `record` off until asked.
- **Aliases and areas**: after registration, `home_alias` gets a
  proposed alias from the device's friendly name and `by_room`, and
  the HA entity gets its area set (`config/entity_registry/update`)
  when `by_room` is ≥ 0.8. Proposed, shown, applied on the next
  `net_register --accept`; never silently.
- **Devices with no system** (phones, laptops, watches): registered as
  HA `device_tracker` presence sources via the `router` integration
  (UniFi/OPNsense) or the router/`nmap_tracker` integration -- so `home.presence` gets them --
  and nothing else.

Every registration is a ledger event on `network:registrations` with
before/after and the HA `entry_id`, so `net_register --undo` can
`config_entries/delete` it.

## 8. Tools (`simorgh/execution/network.py`) and Guardian

| tool | args | read_only | reversibility | notes |
|---|---|---|---|---|
| `net_devices` | `group?`, `category?`, `since?` | yes | read_only | inventory view; rows → `results/` |
| `net_show` | `device` (mac/ip/name) | yes | read_only | everything known, all evidence, history |
| `net_scan` | `depth: quick\|deep`, `targets?`, `methods?`, `confirm?` | no | quick: reversible / deep: irreversible | active |
| `net_identify` | `device` | no | reversible | deep-identify one host (http/rtsp/onvif/ports on ONE ip) + cognition |
| `net_group` | `group` | yes | read_only | |
| `net_register` | `device`, `system?`, `with?`, `accept?`, `undo?` | no | irreversible | writes to HA/Frigate |
| `net_listen` | `op: status\|start\|stop\|tail`, `minutes?` | no | reversible | the passive listener; `tail` shows recent observations |
| `net_topology` | `op: show\|set`, `spec?` | no | reversible | the room/floor/AP map |
| `net_forget` | `device` | no | reversible | tombstone (ledger), never delete |

Markers: `NET_SCAN: quick` / `NET_SCAN: deep\n{"targets": ["192.168.50.0/24"], "confirm": true}`;
`NET_REGISTER: 192.168.50.44\n{"system": "home_assistant"}`. All
multi-line ones into `_CODE_BEARING_MARKERS` + `_MARKER_JSON_REST`.
Profiles: `net_devices`/`net_show`/`net_group` in RESEARCH and PATCH;
the rest in PATCH only.

**`NetworkRule` (Guardian, after `DenylistRule`)** -- pure, reads
`args` of `net_*` proposals:

- `net_scan` with any target outside `allowed_cidrs`, or outside
  RFC1918/link-local entirely → **deny** ("scanning a network you do
  not own"). Empty `allowed_cidrs` and no `confirm` → deny, naming the
  config key and the subnets `interfaces.py` sees.
- `depth: deep` → escalate (needs_human) unless
  `[network] deep_sweep_every_s` scheduled it (`proposed_by:
  "network-sweep"`), in which case `reversible` -- a nightly deep scan
  the creator configured is not a surprise.
- `ports_profile: full` → escalate always, one host only.
- More than `max_hosts_per_scan` hosts → deny.
- `net_register` → escalate always **except** `accept: true` on a flow
  that HA itself discovered (`source: zeroconf|ssdp|dhcp` -- HA already
  vouched for the device) which is `reversible`.
- `net_register` with `with` containing a key named like a secret →
  the value is scrubbed from the proposal before it is ledgered
  (Guardian's `_remember_rejection` and the trace both) -- test it.
- `net_scan` more than 6 quick scans/hour or 2 deep/day → deny (a
  loop of scans is the thing a curious autonomous system would do).
- `net_listen start` → reversible; changing the BPF filter is not an
  argument that exists.

As with `home`, `always human` here survives `sim.sh`'s auto-approve:
add `"network"` to `auto_approve_exempt_layers`.

## 9. How `home` consumes it

`network` publishes `network.device.discovered {device}` /
`network.device.updated` / `network.device.registered {device,
system, entry_id}`. `home/registry.py` subscribes and:

- maps a registered device's HA `entry_id` → entities → keeps
  `Device.mac` on each `Entity` (so "the bedroom camera is offline"
  can say *which* IP and *when it last ARPed*);
- takes `by_room` as the area suggestion for entities with none;
- feeds `home.presence` from phones/watches on the LAN (ARP liveness
  is a better "is the phone here" than Wi-Fi tracker polling).

And `home`'s `unavailable` monitor gains a second opinion: an entity
HA calls unavailable whose MAC is still ARPing is *HA's* problem
(integration/auth), not the device's -- say so.

## 10. Tests

- `fakes.py::FakeNetwork`: scripted answers per scanner (`arp` returns
  N hosts, `mdns` returns a Hue bridge + a Chromecast + a HAP camera,
  `ssdp` an Echo, `wsd` an ONVIF camera, `http` a Hikvision realm with
  no auth, `kasa` a plug, `router` leases with AP names, `hass` an open
  onvif flow), a fake tcpdump line stream for `listen.py`, and a
  `FakeHomeAssistant` (from `contracts/home/fakes.py`) for
  registration flows. **No test sends a packet**: every scanner takes
  an injected transport; a test that needs the real one is marked
  `@unittest.skip("needs a LAN")` and lives in `tests/manual/`.
- `identify`: one test per row of the §4 table, plus: tie → both in
  `why` + `needs_review`; a downgrade never silently applied;
  randomised MAC handled; cognition never overrides a ≥ 0.8 rule.
- `inventory`: six observations for one device merge to one row; MAC
  is identity; a Zigbee device with no MAC keys on `ieee`; history
  keeps the last 30 (ip, ts) bindings.
- `listen`: tcpdump line parser against 40 captured real lines
  (ARP, DHCP with options 12/60/55, mDNS, SSDP NOTIFY, LLDP, DNS) in
  `tests/simorgh/network/data/tcpdump_lines.txt`; a malformed line is
  skipped, not fatal; the listener restarts tcpdump with backoff.
- `scanners`: budget honoured (`max_hosts`, deadline), missing
  dependency → summary row naming the package, target outside CIDR
  refused at the scanner too (defence in depth behind Guardian).
- Guardian: every `NetworkRule` bullet; the scrub test; auto-approve
  exempt.
- `register`: confirms an HA-discovered flow; stops at a credential
  step naming the field; the secret appears nowhere; `--undo`.
- Integration (`test_network_end_to_end.py`): boot the Kernel with
  `[network] enabled`, `FakeNetwork` + `FakeHomeAssistant` → `NET_SCAN:
  quick` through the marker path → inventory has 8 devices in 6
  categories → `NET_REGISTER: <camera> frigate` and `<plug>
  home_assistant --accept` → the fakes received the config → `home`'s
  registry knows the plug's MAC. Then `net_scan` against `10.0.0.0/8`
  → denied.
- Boundary test, `TestBuiltinTools`, the subsystem-count boot test
  (now 18).

## 11. Build order and acceptance

1. **Inventory + OUI + `net_devices`/`net_show`** on the ARP-cache
   fallback only (no dependencies, no privilege). Acceptance: on this
   laptop, `net_scan quick` with `allowed_cidrs = ["192.168.50.0/24"]`
   lists the hosts in `arp -a` with vendors.
2. **mDNS + SSDP + WS-Discovery + Kasa** scanners, `identify.py` table.
   Acceptance: the Echos, the Hue/other bridge, the cameras, and the
   Kasa/Tuya devices in this house are categorised ≥ 0.8; the trial
   reports the `unknown` count.
3. **Passive listener** + DHCP/DNS evidence + `new_device` monitor.
   Acceptance: plug in a phone; a warn arrives via `notify` within 60s
   naming vendor and category.
4. **Deep scan** (`ports`/`http`/`rtsp`/`onvif`) + risk monitors +
   Guardian escalation. Acceptance: an unauthenticated RTSP camera is
   found and reported critical; `net_scan deep` waits for a human.
5. **Registration** into HA and Frigate, `home` consumption, aliases
   and areas.
6. **Router/SNMP/BLE/Zigbee** integrations and `by_room`/`by_floor`.
7. **`docs/home/setup.md`** section: tcpdump capability, `allowed_cidrs`,
   the topology file, which packages to `install_package`.

Each phase: suite green, commit, push, one `tools/trial.py` run on the
fake; phases 1–3 also one real run on this LAN, recorded in the design
doc's implementation log (the numbers -- hosts found, categorised,
unknown -- are the acceptance).

## 12. Traps

- `arp -a` on macOS shows `(incomplete)` entries and stale bindings;
  filter to entries with a MAC and refresh with a ping sweep first.
- Randomised MACs (iOS 14+, Android 10+) change per network but are
  stable *on* one network -- until "private address" is rotated. Key
  phones on (hostname, DHCP option 55 fingerprint) as a fallback
  identity or `new_device` will cry wolf.
- mDNS on macOS: `zeroconf` works but Bonjour may answer for the
  machine itself -- exclude own interfaces' addresses.
- SSDP `LOCATION` URLs can point at private/link-local addresses on
  another interface, or at `http://0.0.0.0`; validate the host is in
  `allowed_cidrs` before GET (the same SSRF guard as `web_fetch`,
  `netsafety.validate_public_http_url` inverted: *must* be private and
  *must* be allowed).
- HTTP probing a camera's `/` with the wrong path can lock some
  Hikvision firmware into "illegal login" for 30 min. Only GET `/`
  and the ONVIF path; never POST; never retry a 401.
- OS detection needs root and is wrong about IoT most of
  the time; use TTL + DHCP fingerprint + banners instead.
- WS-Discovery multicast (239.255.255.250:3702) is often blocked by
  Wi-Fi client isolation; when `wsd` finds nothing and `http` finds
  ONVIF paths, say "WS-Discovery may be blocked on this Wi-Fi".
- BLE scanning on macOS prompts for Bluetooth permission in a GUI
  dialog -- a headless Sim hangs. `ble: false` default; the probe
  detects macOS + no permission and says so.
- The OUI table is 2 MB; do not read it into memory per lookup --
  load once into a dict keyed by the first 6 hex chars; the IEEE file
  also has 28- and 36-bit blocks (MA-M/MA-S) -- check longest prefix.
- A "deep" scan of 254 hosts at `max_rate_pps = 200` takes minutes and
  is visible in any IDS; it is scheduled at 03:00 for a reason.
- Never store a captured DNS *payload*, a DHCP *client identifier*
  beyond the hostname, or any HTTP *body* -- evidence is headers,
  titles, and service metadata only.
