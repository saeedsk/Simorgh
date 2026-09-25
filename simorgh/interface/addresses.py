"""Where Sim can be reached from, in the order a phone should try.

The app had ONE address, the one typed at pairing time, and it was a LAN
address -- so the moment the creator left the house it stopped working
("I turned on tailscale on both mac and iphone and went outside, sim app
didn't work", 2026-09-25). Sim was listening on the tailnet the whole
time, because `[interface] http_host` is `0.0.0.0`; nothing had ever told
the phone that second address existed.

Discovery is stdlib and never raises: a machine with no network still
boots, and an address list is a convenience, not a dependency. The
Tailscale CLI is consulted when it happens to be installed, the same
"optional, probed, refused by name" rule `devices.barcode()` follows for
qrencode -- but the tailnet ADDRESS is found without it, because the
kernel already knows the route.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess

#: Tailscale's own MagicDNS resolver. Connecting a UDP socket to it sends
#: no packet and needs no reply -- the kernel just picks the route and the
#: source address, which is this machine's tailnet IP when a tailnet
#: exists and nothing at all when it does not.
_TAILSCALE_DNS = "100.100.100.100"
#: Any off-LAN address does for "which interface reaches the world".
_ELSEWHERE = "8.8.8.8"

#: Tailscale hands out addresses in the CGNAT range (RFC 6598), which is
#: NOT one of the private ranges, and that distinction is the whole bug on
#: the phone: iOS `NSAllowsLocalNetworking` permits insecure HTTP to
#: 10/8, 172.16/12 and 192.168/16 and refuses 100.64/10, so the request
#: never left the device.
TAILNET_PREFIX = "100."


def _source_address_for(target: str) -> str:
    """This machine's address on the route to `target`, or "".

    No packet is sent: a connected UDP socket only fixes the route.
    """
    sock = None
    try:
        # Inside the try: opening the socket AT ALL can fail (no network
        # stack, a sandbox with no AF_INET), and boot must not depend on an
        # address list. Caught by its own test rather than in a house.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        sock.connect((target, 53))
        found = sock.getsockname()[0]
        return str(found) if found and found != "0.0.0.0" else ""
    except OSError:
        return ""
    finally:
        if sock is not None:
            sock.close()


def tailnet_name() -> str:
    """This machine's MagicDNS name, or "".

    Worth the subprocess: a NAME is what the phone can be allowed to
    reach over plain HTTP (an ATS exception is by domain, and an IP
    literal is not a domain), and it survives an address change.
    """
    binary = shutil.which("tailscale") or "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    if not shutil.which(binary) and not shutil.os.path.exists(binary):  # noqa: PTH110
        return ""
    try:
        done = subprocess.run([binary, "status", "--json"],  # noqa: S603 -- a found binary, a literal argv
                              capture_output=True, text=True, timeout=5, check=False)
        if done.returncode != 0:
            return ""
        me = (json.loads(done.stdout) or {}).get("Self") or {}
        if not me.get("Online"):
            return ""
        return str(me.get("DNSName") or "").rstrip(".")
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""


def reachable(port: int, *, scheme: str = "http") -> list[str]:
    """Every base URL this machine answers on, best first.

    Best first means: the MagicDNS name, then the tailnet address, then
    the LAN address, then loopback. A phone should prefer the one that
    works in both places over the one that works in only one -- the
    tailnet reaches Sim at home as well as away, so putting it first
    costs a home user nothing and saves an away user everything.
    """
    out: list[str] = []

    def add(host: str) -> None:
        if not host:
            return
        url = f"{scheme}://{host}:{port}"
        if url not in out:
            out.append(url)

    add(tailnet_name())
    tailnet = _source_address_for(_TAILSCALE_DNS)
    if tailnet.startswith(TAILNET_PREFIX):
        add(tailnet)
    add(_source_address_for(_ELSEWHERE))
    add("127.0.0.1")
    return out


__all__ = ["TAILNET_PREFIX", "reachable", "tailnet_name"]
