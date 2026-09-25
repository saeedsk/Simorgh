"""Sim, announcing itself on the local network.

A client should not have to be told an address. The creator, 2026-09-25:
"you should make auto discoverable, like sim sends multicast and broadcast
messages and clients should be able to auto discover sim engine" -- which
is what Home Assistant does (`_home-assistant._tcp`, and it is how this
machine found his HA at all).

`_simorgh._tcp`, with the same TXT shape HA uses: the addresses are IN the
record, so one browse hands a phone the tailnet name as well as the LAN
one. That matters because mDNS is multicast and multicast is NOT routed
over a tailnet -- discovery works at home and finds nothing away from it,
so the record has to carry the address that does work away.

Optional, probed, and named when missing, the rule every voice engine and
`devices.barcode()` already follows:

  1. `dns-sd -R` (macOS, built in) or `avahi-publish-service` (Linux) --
     a supervised child, the way a camera relay is.
  2. the `zeroconf` package, if it happens to be installed.
  3. nothing, said out loud in `health()`. Discovery is a convenience;
     a house whose phone has an address does not need it.

No new hard dependency, and no mDNS responder written here: a wrong one
answers for names that are not Sim's, which is worse than not answering.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SERVICE = "_simorgh._tcp"
INSTANCE = "Sim"


def _avahi() -> str:
    return shutil.which("avahi-publish-service") or ""


def _dns_sd() -> str:
    return shutil.which("dns-sd") or ""


def how() -> str:
    """Which mechanism would be used, or "" -- for `health()` and for the
    `interface` status line."""
    if _dns_sd():
        return "dns-sd"
    if _avahi():
        return "avahi"
    try:
        import zeroconf  # noqa: F401
    except ImportError:
        return ""
    return "zeroconf"


def command(port: int, addresses: list[str]) -> list[str]:
    """The argv that registers the service, or [] when nothing here can.

    TXT keys: `base` is the address Sim considers best (the tailnet one,
    which works in both places) and `addresses` is the space-separated
    rest. A client reads `base` and keeps the others as fallbacks.
    """
    best = addresses[0] if addresses else ""
    rest = " ".join(addresses)
    binary = _dns_sd()
    if binary:
        return [binary, "-R", INSTANCE, SERVICE, "local", str(port),
                f"base={best}", f"addresses={rest}"]
    binary = _avahi()
    if binary:
        return [binary, INSTANCE, SERVICE, str(port),
                f"base={best}", f"addresses={rest}"]
    return []


class Announcer:
    """Keeps the registration alive for as long as Sim is up.

    `dns-sd -R` and `avahi-publish-service` both hold the name only while
    they RUN -- they are not fire-and-forget -- so this is a supervised
    child like an ffmpeg relay, stopped with the subsystem.
    """

    def __init__(self, port: int, addresses: list[str], *, log=None) -> None:
        self._port = port
        self._addresses = list(addresses)
        self._log = log
        self._child: subprocess.Popen | None = None
        self.detail = ""

    def start(self) -> bool:
        argv = command(self._port, self._addresses)
        if not argv:
            self.detail = ("no mDNS publisher here (no dns-sd, no avahi-publish-service, no zeroconf "
                           "package) -- clients must be given an address")
            return False
        try:
            self._child = subprocess.Popen(  # noqa: S603 -- a found binary, a literal argv
                argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, start_new_session=True)
        except (OSError, subprocess.SubprocessError) as exc:
            self.detail = f"could not announce over mDNS: {exc!r}"
            return False
        self.detail = f"announcing {INSTANCE}.{SERVICE}.local on port {self._port} via {Path(argv[0]).name}"
        if self._log is not None:
            self._log("info", "interface.announced", service=SERVICE, port=self._port,
                      addresses=self._addresses)
        return True

    @property
    def running(self) -> bool:
        return self._child is not None and self._child.poll() is None

    def stop(self) -> None:
        child = self._child
        self._child = None
        if child is None or child.poll() is not None:
            return
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()


__all__ = ["Announcer", "INSTANCE", "SERVICE", "command", "how"]
