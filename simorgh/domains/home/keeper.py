"""Bring Home Assistant back when it cannot be reached.

The creator, 2026-09-27: "why HA is not running, sim should be able to
handle HA run state, if it is not running, sim should be able to recover
and kick start" it. Home Assistant OS runs in a UTM virtual machine on
this Mac (docs/findings/2026-09-20-home-assistant-os-in-utm.md), bridged
onto the LAN. On 2026-09-25 at 08:47 the VM stopped, UTM's library lost
track of it, and for two days every light, media and energy question got
"could not reach Home Assistant (Host is down)" -- while the VM sat on
disk ready to start.

`revive(url)` walks the same chain a person would:

  UTM   the configured address is on the LAN: find the VM (registering its
        bundle with UTM if the library lost it), start it if it is stopped,
        and wait for the address to answer.
  Docker  the address is this machine: start the `homeassistant` container
        if it exists and is not running.

At most one attempt per `RETRY_AFTER_S`, so a Home Assistant that is down
for a reason this cannot fix is not hammered, and every tool call in a
burst does not start its own recovery. It says what it did -- a tool that
changed the machine must say so.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import time
import urllib.parse
from pathlib import Path

#: How long a started VM gets to answer. HA OS boots in about a minute.
BOOT_WAIT_S = 120.0
#: One recovery attempt per this long.
RETRY_AFTER_S = 300.0
UTMCTL = "/Applications/UTM.app/Contents/MacOS/utmctl"
UTM_DOCUMENTS = Path.home() / "Library/Containers/com.utmapp.UTM/Data/Documents"
#: The VM's name in UTM: SIMORGH_HAOS_VM, else the names tools/haos.py
#: knows, else the only VM there is.
VM_NAMES = tuple(n for n in (os.environ.get("SIMORGH_HAOS_VM"), "Home Assistant", "Virtual Machine") if n)
CONTAINER = "homeassistant"

_last_attempt = 0.0
_lock: asyncio.Lock | None = None


def _run(args: list[str], timeout: float = 30.0) -> tuple[int, str]:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout,  # noqa: S603 -- fixed argv
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _answers(url: str, timeout: float = 3.0) -> bool:
    parts = urllib.parse.urlparse(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((parts.hostname or "", port), timeout=timeout):
            return True
    except OSError:
        return False


def _is_local(url: str) -> bool:
    return (urllib.parse.urlparse(url).hostname or "") in ("localhost", "127.0.0.1", "::1")


def _utm_vms(run) -> dict[str, str]:
    """name -> status, from `utmctl list`."""
    code, out = run([UTMCTL, "list"])
    vms = {}
    if code != 0:
        return vms
    for line in out.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) == 3:
            vms[parts[2].strip()] = parts[1].strip().lower()
    return vms


def _revive_vm(url: str, run, *, documents: Path = UTM_DOCUMENTS, wait=None) -> str:
    if not Path(UTMCTL).exists() and run is _run:
        return "UTM is not installed, so the Home Assistant VM cannot be started"
    vms = _utm_vms(run)
    name = next((n for n in VM_NAMES if n in vms), None) or (next(iter(vms)) if len(vms) == 1 else None)
    registered = ""
    if name is None:
        # UTM's library can lose a VM whose bundle is still on disk (it did,
        # 2026-09-25): opening the bundle puts it back.
        bundles = sorted(documents.glob("*.utm")) if documents.is_dir() else []
        wanted = [b for b in bundles if b.stem in VM_NAMES] or (bundles if len(bundles) == 1 else [])
        if not wanted:
            return "no Home Assistant VM in UTM, and no single VM bundle to add back"
        run(["open", str(wanted[0])])
        time.sleep(3)
        vms = _utm_vms(run)
        name = wanted[0].stem if wanted[0].stem in vms else next((n for n in VM_NAMES if n in vms), None)
        if name is None:
            return f"added {wanted[0].name} back to UTM, but UTM still does not list it"
        registered = f"added the VM '{name}' back to UTM's library, "
    if vms.get(name) not in ("started", "running"):
        code, out = run([UTMCTL, "start", name])
        if code != 0:
            return f"{registered}could not start the VM '{name}': {out.strip()[:160]}"
        started = f"{registered}started the Home Assistant VM '{name}'"
    else:
        started = f"{registered}the VM '{name}' was already running"
    if (wait or _wait_for)(url):
        return f"{started}; Home Assistant answers again"
    return f"{started}, but Home Assistant has not answered in {BOOT_WAIT_S:.0f}s -- it may still be booting"


def _revive_container(url: str, run, *, wait=None) -> str:
    if not shutil.which("docker") and run is _run:
        return "Home Assistant is on this machine, but docker is not installed"
    code, out = run(["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER])
    if code != 0:
        return f"no '{CONTAINER}' container to start"
    if out.strip() == "true":
        return f"the '{CONTAINER}' container is running, but Home Assistant is not answering"
    code, out = run(["docker", "start", CONTAINER])
    if code != 0:
        return f"could not start the '{CONTAINER}' container: {out.strip()[:160]}"
    if (wait or _wait_for)(url):
        return f"started the '{CONTAINER}' container; Home Assistant answers again"
    return f"started the '{CONTAINER}' container, but Home Assistant has not answered yet"


def _wait_for(url: str) -> bool:
    deadline = time.monotonic() + BOOT_WAIT_S
    while time.monotonic() < deadline:
        if _answers(url):
            return True
        time.sleep(5)
    return False


async def revive(url: str, *, run=_run, clock=time.monotonic, wait=None, documents: Path = UTM_DOCUMENTS) -> str:
    """Try once to bring Home Assistant at `url` back; what was done, or ""
    when nothing was tried (unconfigured, already answering, tried lately)."""
    global _last_attempt, _lock
    if not url:
        return ""
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        if await asyncio.to_thread(_answers, url):
            return ""
        now = clock()
        if _last_attempt and now - _last_attempt < RETRY_AFTER_S:
            return ""
        _last_attempt = now
        if _is_local(url):
            return await asyncio.to_thread(_revive_container, url, run, wait=wait)
        return await asyncio.to_thread(_revive_vm, url, run, documents=documents, wait=wait)


def reset() -> None:
    """Forget the last attempt (tests)."""
    global _last_attempt, _lock
    _last_attempt, _lock = 0.0, None


__all__ = ["BOOT_WAIT_S", "CONTAINER", "RETRY_AFTER_S", "VM_NAMES", "reset", "revive"]
