#!/usr/bin/env python3
"""haos: drive the Home Assistant OS virtual machine this Mac runs under UTM.

The creator chose, on 2026-09-20, to run Home Assistant OS in a UTM VM
with a bridged network adapter rather than Home Assistant Container
under Docker. The reason is discovery: a bridged VM is a real device on
192.168.50.0/24 with its own address and its own MAC, so mDNS and SSDP
reach it and the Supervisor's add-ons come with it. A container on
Docker Desktop is behind a user-space network stack inside a Linux VM
and can never hear LAN multicast. See
`docs/findings/2026-09-20-home-assistant-os-in-utm.md` for the whole
argument, including the honest caveats about bridging over Wi-Fi.

What changes for a tool is the shape of the failure. With Docker there
were four ways to be down; with a VM there are six, and from Sim's side
they all look like `home_call` saying "could not reach Home Assistant":

    UTM is not installed
    the VM does not exist
    the VM is not running
    the VM is running but has no LAN address (the bridge did not take)
    HA is booting, or up but unreachable at the address we think it has
    HA answers but no token is configured for Sim

This tool tells those six apart in one command.

    python3 tools/haos.py status   # UTM, VM, address, API, token
    python3 tools/haos.py up       # start the VM
    python3 tools/haos.py down     # ask the VM to shut down cleanly
    python3 tools/haos.py ip       # the VM's address on the LAN, and how it was found
    python3 tools/haos.py token    # how to mint a long-lived token and where to put it

`status` never raises on a machine with no UTM, which is this machine
today: it says so and exits 1. It exits 0 only when the HA API actually
answers.

Finding the address is deliberately not left to `utmctl`. UTM can only
report a guest's address when it has a channel into the guest (a guest
agent, or the Apple virtualisation backend's lease table), and Home
Assistant OS under the QEMU backend gives it neither. What it does give
is mDNS: HA OS announces itself as `homeassistant.local`, and macOS's
own resolver answers that. So the order here is the configured URL
first (what Sim will actually use), then mDNS, then `utmctl` as a
long shot. Each answer says where it came from, because "the VM has an
address" and "the address Sim is configured with still works" are
different facts and confusing them wastes an evening.

No secret is ever printed. `status` says a token is present or absent
and nothing more; this output goes into terminals, ledgers and agent
transcripts, and a token in any of those has to be revoked.

stdlib only, like the rest of `tools/`. `tools/ha.py` is kept beside
this one on purpose: the Docker path is the fallback if bridging over
Wi-Fi does not hold, and it is a different set of commands, not a
different version of these.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

#: The VM's name in UTM. The install guide suggests "Home Assistant",
#: but UTM's own default for a new machine is "Virtual Machine" and
#: that is what the creator's install ended up called (2026-09-20), so
#: both are tried in order before giving up. Overridable, so a second
#: VM -- a restore test, say -- can be driven by the same commands.
VM_NAMES = tuple(n for n in (os.environ.get("SIMORGH_HAOS_VM"), "Home Assistant", "Virtual Machine") if n)
VM = VM_NAMES[0]

#: HA OS announces itself over mDNS under this name. This is the
#: load-bearing consequence of bridging: on the Docker path there is no
#: such name, because there is no device.
MDNS_NAME = os.environ.get("SIMORGH_HAOS_MDNS", "homeassistant.local")

PORT = int(os.environ.get("SIMORGH_HA_PORT", "8123"))

SECRETS_FILE = Path(os.environ.get("SIMORGH_SECRETS_FILE", "~/.simorgh/secrets.toml")).expanduser()
VAULT_URL_KEY = "vault:home_assistant:url"
VAULT_TOKEN_KEY = "vault:home_assistant:token"

# UTM does not put utmctl on PATH; it lives inside the app bundle, and
# the bundle can be in either of two places depending on whether it came
# from the App Store or the direct download (both land in /Applications,
# but a per-user install is common enough to be worth looking for).
UTM_BUNDLES = (
    Path("/Applications/UTM.app"),
    Path("~/Applications/UTM.app").expanduser(),
)
UTMCTL_IN_BUNDLE = "Contents/MacOS/utmctl"


def utmctl_bin() -> str | None:
    """The utmctl binary, or None when UTM is not installed. PATH first,
    because someone may have symlinked it, then the app bundles."""
    found = shutil.which("utmctl")
    if found:
        return found
    for bundle in UTM_BUNDLES:
        candidate = bundle / UTMCTL_IN_BUNDLE
        if candidate.exists():
            return str(candidate)
    return None


def run(args: list[str], *, timeout: float = 20.0) -> tuple[int, str, str]:
    """Run a command and never raise. A missing binary and a timeout are
    ordinary answers here, not exceptions -- every caller below wants to
    print something about them rather than stop."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "", f"{args[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{' '.join(args[:2])}: no answer in {timeout:.0f}s"
    return done.returncode, done.stdout.strip(), done.stderr.strip()


# -- what UTM knows ----------------------------------------------------------


def vm_state(binary: str) -> str | None:
    """The VM's state as UTM reports it -- "started", "stopped",
    "paused", "suspended" -- or None when UTM has no such VM.

    `utmctl status <name>` prints one word. Its exact vocabulary is
    UTM's, not ours, so nothing here compares against a list of expected
    states beyond treating "started" as running; an unfamiliar word is
    printed through rather than swallowed. The fallback parse of
    `utmctl list` exists because the status subcommand's spelling has
    changed across UTM versions and a listing has not.
    """
    for name in VM_NAMES:
        code, out, _ = run([binary, "status", name], timeout=15.0)
        if code == 0 and out:
            return out.splitlines()[-1].strip().lower()

    code, out, _ = run([binary, "list"], timeout=15.0)
    if code != 0 or not out:
        return None
    # Columns are UUID, Status, Name; the name may contain spaces, so
    # split off the first two fields and keep the rest as the name.
    listed = {}
    for line in out.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) == 3:
            listed[parts[2].strip()] = parts[1].strip().lower()
    for name in VM_NAMES:
        if name in listed:
            return listed[name]
    # One VM and none of the names matched: it is almost certainly that
    # one, and saying "does not exist" about the only machine on the
    # host would be pedantry rather than accuracy.
    if len(listed) == 1:
        return next(iter(listed.values()))
    return None


def is_running(state: str | None) -> bool:
    return state in {"started", "running"}


# -- where Home Assistant is -------------------------------------------------


def configured() -> tuple[str, bool, str]:
    """`(url, token_present, where)` exactly as Sim will see it.

    This mirrors `_HomeTool._lookup`: the secret store first (which
    resolves `vault:`-prefixed names out of `secrets.toml` and then the
    encrypted vault), then the plain environment variables. The vault
    itself is deliberately not opened -- that would touch the macOS
    keychain and prompt -- so a credential kept only in the vault is
    reported here as "not found in the file" while still working for
    Sim. Say so rather than claim it is missing.
    """
    values: dict[str, str] = {}
    where = "nowhere"
    if SECRETS_FILE.is_file():
        try:
            with SECRETS_FILE.open("rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            print(f"  warning: {SECRETS_FILE} could not be read ({exc})")
            data = {}
        for key in (VAULT_URL_KEY, VAULT_TOKEN_KEY):
            if isinstance(data.get(key), str) and data[key]:
                values[key] = data[key]
        if values:
            where = str(SECRETS_FILE)

    url = values.get(VAULT_URL_KEY) or os.environ.get("HOME_ASSISTANT_URL") or ""
    token = values.get(VAULT_TOKEN_KEY) or os.environ.get("HOME_ASSISTANT_TOKEN") or ""
    if not values and (url or token):
        where = "the environment"
    return url, bool(token), where


def _secret(name: str) -> str:
    if not SECRETS_FILE.is_file():
        return ""
    try:
        with SECRETS_FILE.open("rb") as fh:
            value = tomllib.load(fh).get(name)
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    return value if isinstance(value, str) else ""


def resolve_mdns(name: str) -> str | None:
    """The IPv4 address behind an mDNS name, via the host's own
    resolver. macOS answers `.local` through mDNSResponder, so this
    needs no library and no multicast socket of our own -- and it is the
    single best check that the bridge is doing its job, because a VM on
    a shared (NAT) adapter has no LAN name at all."""
    try:
        infos = socket.getaddrinfo(name, None, socket.AF_INET)
    except (socket.gaierror, UnicodeError, OSError):
        return None
    for info in infos:
        address = info[4][0]
        if isinstance(address, str):
            return address
    return None


def utmctl_ip(binary: str) -> str | None:
    """What UTM thinks the guest's address is. Usually nothing for a
    QEMU-backend Linux guest without a guest agent, which is why this is
    tried last and its absence is not reported as a fault."""
    code, out, _ = run([binary, "ip-address", VM], timeout=15.0)
    if code != 0 or not out:
        return None
    for line in out.splitlines():
        candidate = line.strip()
        # Keep IPv4 only, and skip the link-local block: a 169.254
        # address means DHCP did not answer, which is a symptom, not an
        # address worth handing to anyone.
        parts = candidate.split(".")
        if len(parts) == 4 and all(p.isdigit() for p in parts) and not candidate.startswith("169.254."):
            return candidate
    return None


#: HA OS serves a small status page here while Core is still starting.
#: It is the difference between "the VM is broken" and "the VM is
#: installing Home Assistant", which on a first boot is several minutes
#: and on a tight disk is longer.
OBSERVER_PORT = 4357


def core_answering(address: str) -> tuple[bool, str]:
    """Whether Home Assistant Core is up on `address` yet, and how it
    looks if not.

    Core opens 8123 only once it has started; before that HA OS answers
    on the observer port alone. Reporting "connection refused" for a
    machine that is midway through its first install is true and
    useless, so the two are told apart.
    """
    import socket

    for port, what in ((PORT, "core"), (OBSERVER_PORT, "observer")):
        sock = socket.socket()
        sock.settimeout(2.0)
        try:
            sock.connect((address, port))
        except Exception:  # noqa: BLE001 -- a closed port is an answer
            continue
        finally:
            sock.close()
        if what == "core":
            return True, f"answering on {PORT}"
        return False, (f"not up yet -- the HA OS observer is answering on {OBSERVER_PORT}, "
                       "which means Home Assistant is still starting")
    return False, f"nothing answers on {PORT} or {OBSERVER_PORT}; the VM may still be booting"


def find_address() -> tuple[str | None, str]:
    """`(address_or_url, how)`. The configured URL wins when there is
    one, because that is the address Sim will use and the only one whose
    failure matters."""
    url, _, where = configured()
    if url:
        return url, f"configured URL (from {where})"
    address = resolve_mdns(MDNS_NAME)
    if address:
        return f"http://{address}:{PORT}", f"mDNS: {MDNS_NAME} resolves to {address}"
    binary = utmctl_bin()
    if binary:
        address = utmctl_ip(binary)
        if address:
            return f"http://{address}:{PORT}", "utmctl ip-address"
    return None, "not found: no configured URL, no mDNS answer, nothing from utmctl"


# -- asking Home Assistant ---------------------------------------------------


def probe_api(url: str, token: str) -> tuple[bool, str]:
    """Ask HA whether it is running. `GET /api/` needs the token;
    `GET /` does not and is what tells a stopped VM apart from a missing
    token, so both are tried in that order."""
    ok, note = _get(f"{url.rstrip('/')}/api/", token)
    if ok:
        return True, note
    if token:
        return False, note
    reachable, plain = _get(url.rstrip("/") + "/", "")
    if reachable:
        return False, "HA is listening but no token is configured"
    return False, plain


def _get(target: str, token: str) -> tuple[bool, str]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(target, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5.0) as response:
            raw = response.read(4096)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return False, "HA refused the token (401/403): mint a new one, `haos.py token`"
        return False, f"HA answered {exc.code}"
    except urllib.error.URLError as exc:
        # `exc.reason` and never the URL: the URL is the one string here
        # that could carry a token.
        return False, f"nothing listening ({exc.reason})"
    except TimeoutError:
        return False, "no answer in 5s"
    try:
        message = str(json.loads(raw.decode("utf-8", "replace")).get("message", ""))
    except (ValueError, AttributeError):
        message = ""
    return True, message or "answered"


# -- the verbs ---------------------------------------------------------------


def cmd_status(_args) -> int:
    binary = utmctl_bin()
    if binary is None:
        print("utm: not installed. UTM is not on this machine.")
        print("  fix: install UTM (free: https://mac.getutm.app, or the Mac App Store),")
        print("       then follow docs/findings/2026-09-20-home-assistant-os-in-utm.md")
        print("  note: `python3 tools/ha.py status` drives the Docker fallback instead")
        return 1
    print(f"utmctl: {binary}")

    state = vm_state(binary)
    if state is None:
        print(f"vm {VM!r}: does not exist in UTM")
        print("  fix: create it -- docs/findings/2026-09-20-home-assistant-os-in-utm.md")
        print(f"  note: if the VM has another name, set SIMORGH_HAOS_VM to it")
        return 1
    print(f"vm {VM!r}: {state}")
    if not is_running(state):
        print("  fix: `python3 tools/haos.py up`")
        return 1

    # The VM's OWN address first, and separately from whatever Sim is
    # configured to talk to. On the night of the move those are two
    # different machines -- the VM booting on the LAN, the Docker
    # container still answering on localhost -- and a status line that
    # reported the configured URL as "the VM" would have said
    # everything was fine while Core was still installing (2026-09-20).
    on_lan = resolve_mdns(MDNS_NAME)
    if on_lan is None:
        print(f"address: unknown -- {MDNS_NAME} does not resolve")
        print("  this is what a bridge that did not take looks like: the VM runs but is")
        print("  not on the LAN. Check the VM's network mode is Bridged on en0, and")
        print("  HA's own Settings -> System -> Network. See the findings doc.")
        return 1
    address = f"http://{on_lan}:{PORT}"
    print(f"address: {address} (mDNS: {MDNS_NAME})")
    core_up, core_why = core_answering(on_lan)
    print(f"core: {core_why}")
    if not core_up:
        print(f"  watch it come up at http://{MDNS_NAME}:{OBSERVER_PORT} (the HA OS observer)")

    url, has_token, where = configured()
    if url:
        print(f"config: url set, token {'set' if has_token else 'MISSING'} (from {where})")
        # The one that catches somebody out on the night of the move:
        # Sim is still pointed at the container, the container still
        # answers, and every check passes while the VM sits unused.
        if on_lan not in url and "homeassistant" not in url:
            print(f"  NOTE: Sim is configured for {url}, which is NOT this VM.")
            print(f"        Point it at http://{on_lan}:{PORT} (or http://{MDNS_NAME}:{PORT})")
            print("        once the VM has its data -- and pin the address on the router first.")
    else:
        print(f"config: nothing for Sim yet (looked in {SECRETS_FILE} and the environment)")
        print("  note: a credential kept only in the encrypted vault is not visible here")

    token = os.environ.get("HOME_ASSISTANT_TOKEN", "")
    if not token and has_token:
        token = _secret(VAULT_TOKEN_KEY)
    ok, note = probe_api(address, token)
    if ok:
        print(f"api: answers at {address} ({note})")
    else:
        print(f"api: not usable at {address} -- {note}")
        if not has_token:
            print("  fix: `python3 tools/haos.py token`")
        return 1
    return 0


def _require_utm() -> str | None:
    binary = utmctl_bin()
    if binary is None:
        print("UTM is not installed on this machine.")
        print("  see docs/findings/2026-09-20-home-assistant-os-in-utm.md")
        return None
    return binary


def cmd_up(_args) -> int:
    binary = _require_utm()
    if binary is None:
        return 1
    state = vm_state(binary)
    if state is None:
        print(f"UTM has no VM named {VM!r}. Create it first (see the findings doc),")
        print("or set SIMORGH_HAOS_VM if it is called something else.")
        return 1
    if is_running(state):
        address, how = find_address()
        print(f"{VM} is already running ({address or 'address unknown'}, {how})")
        return 0
    code, _, err = run([binary, "start", VM], timeout=120.0)
    if code != 0:
        print(f"could not start {VM}: {err or 'utmctl start failed'}")
        return 1
    print(f"{VM} started. HA OS takes about a minute to boot and another")
    print("30-60s before the API answers; re-run `haos.py status` until it does.")
    return 0


def cmd_down(_args) -> int:
    binary = _require_utm()
    if binary is None:
        return 1
    state = vm_state(binary)
    if state is None:
        print(f"UTM has no VM named {VM!r}.")
        return 1
    if not is_running(state):
        print(f"{VM} is already {state}.")
        return 0
    # A plain `stop` is UTM's request for an orderly guest shutdown. HA
    # OS has a recorder database open; killing the VM is how that gets
    # corrupted, so there is no --force here on purpose.
    code, _, err = run([binary, "stop", VM], timeout=180.0)
    if code != 0:
        print(f"could not stop {VM}: {err or 'utmctl stop failed'}")
        print("  the VM window's own stop button can force it, but HA's database is")
        print("  open: prefer Settings -> System -> Shut down inside HA first.")
        return 1
    print(f"{VM} asked to shut down. The disk image is untouched.")
    return 0


def cmd_ip(_args) -> int:
    """Every way of answering "where is it", all of them, because when
    they disagree that disagreement is the finding."""
    url, _, where = configured()
    print(f"configured URL: {url or '(none)'}" + (f"  [{where}]" if url else ""))

    address = resolve_mdns(MDNS_NAME)
    print(f"mDNS {MDNS_NAME}: {address or '(no answer)'}")
    if address is None:
        print("  no answer means either the VM is off, or it is not bridged onto the")
        print("  LAN -- a shared/NAT adapter gives the guest no name this host can see.")

    binary = utmctl_bin()
    if binary is None:
        print("utmctl: not installed")
    else:
        reported = utmctl_ip(binary)
        print(f"utmctl ip-address: {reported or '(nothing -- normal for a QEMU guest with no guest agent)'}")

    chosen, how = find_address()
    print()
    print(f"Sim would use: {chosen or '(nothing)'} -- {how}")
    return 0 if chosen else 1


def cmd_token(_args) -> int:
    url, has_token, where = configured()
    address, _ = find_address()
    example = address or f"http://{MDNS_NAME}:{PORT}"
    print("A long-lived access token is made in the HA web UI, once, by hand:")
    print(f"  1. open {example} and sign in")
    print("  2. click your user name at the bottom of the sidebar")
    print("  3. Security tab -> Long-lived access tokens -> Create token")
    print("  4. name it 'simorgh' and copy the string; HA shows it exactly once")
    print()
    print(f"Then put it where Sim looks. Append to {SECRETS_FILE} (keys quoted, they contain colons):")
    print()
    print(f'  "{VAULT_URL_KEY}" = "{example}"')
    print(f'  "{VAULT_TOKEN_KEY}" = "<the token>"')
    print()
    print(f"  chmod 600 {SECRETS_FILE}   # the store refuses a group/world-readable file")
    print()
    print("Use the VM's IP address rather than homeassistant.local in that URL, and pin")
    print("it as a DHCP reservation on the ZenWiFi: mDNS is fine for a human at a")
    print("browser and a poor thing to hang a daemon's config on. HA also refuses")
    print("requests to a hostname it does not know -- if it answers 400, add the")
    print("address under `http:` in HA's configuration.yaml or use the IP.")
    print()
    print("`[execution] secrets` in ~/.simorgh/simorgh.toml already lists \"vault:*\", so both")
    print("names are in scope for the tools; no config change is needed. Restart Sim, then")
    print("`python3 tools/haos.py status`. HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN in")
    print("the environment work too and are what a one-off shell should use.")
    print()
    if url and has_token:
        print(f"Right now: a url and a token are already configured, from {where}.")
    elif url:
        print(f"Right now: a url is configured from {where}, but no token.")
    else:
        print("Right now: nothing is configured.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="UTM, VM, address, API and token, in that order")
    subparsers.add_parser("up", help="start the VM")
    subparsers.add_parser("down", help="ask the VM to shut down cleanly")
    subparsers.add_parser("ip", help="every answer to 'where is it', and which one Sim uses")
    subparsers.add_parser("token", help="how to mint a token and where to put it")
    args = parser.parse_args()

    handlers = {"status": cmd_status, "up": cmd_up, "down": cmd_down,
                "ip": cmd_ip, "token": cmd_token}
    handler = handlers.get(args.command or "status")
    if handler is None:
        parser.print_help()
        return 2
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
