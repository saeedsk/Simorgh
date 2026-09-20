"""Heavy steps as real child processes, killed when the step is (stage 7 item 8).

`asyncio.to_thread(subprocess.run, ...)` was how every heavy tool ran: a
test suite, a container, the landing gate. It has one flaw that matters
when a person changes their mind -- a thread cannot be cancelled, and
neither can the child inside it. Cancelling the task returned control to
Sim while pytest carried on compiling, holding the CPU and, worse,
holding the tree it was testing.

So: the child gets its own process group (`start_new_session`), the
parent waits on it with a deadline, and anything that ends the wait --
the deadline, a cancel, the session going away -- kills the whole group.
A child that ignores SIGTERM gets SIGKILL a moment later, because the
promise "it is gone" is the only useful kind.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import time
from dataclasses import dataclass

#: How long a child gets to end politely before it is killed.
GRACE_S = 1.5


@dataclass(frozen=True)
class Completed:
    """What `subprocess.run` would have given, plus whether it was killed."""

    returncode: int
    stdout: str
    stderr: str
    seconds: float
    timed_out: bool = False
    killed: bool = False


async def run_child(args, *, cwd=None, env=None, timeout: float | None = None,
                    stdin_devnull: bool = True, preexec_fn=None) -> Completed:
    """Run `args` as a child in its own process group; never leaves it behind.

    `timeout` expiring, the caller being cancelled, or the loop shutting
    down all end the same way: the group is killed and the partial output
    is returned, because half a test run tells you more than nothing.
    """
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL if stdin_devnull else None,
        start_new_session=True,          # its own group, so one kill reaches its children too
        preexec_fn=preexec_fn,
    )
    # Read both pipes as they fill, rather than with one `communicate()`
    # at the end: a run that is killed has usually said something useful
    # first, and a `communicate()` cancelled mid-read loses all of it.
    chunks: dict[str, bytearray] = {"out": bytearray(), "err": bytearray()}
    readers = [asyncio.ensure_future(_drain(proc.stdout, chunks["out"])),
               asyncio.ensure_future(_drain(proc.stderr, chunks["err"]))]
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
        await asyncio.gather(*readers, return_exceptions=True)
        return Completed(proc.returncode or 0, _text(chunks["out"]), _text(chunks["err"]),
                         time.monotonic() - started)
    except asyncio.TimeoutError:
        await _end(proc, readers)
        return Completed(-1, _text(chunks["out"]), _text(chunks["err"]), time.monotonic() - started,
                         timed_out=True, killed=True)
    except asyncio.CancelledError:
        # The step was cancelled. The child goes with it -- that is the
        # whole point of this module -- and the cancellation continues.
        await _end(proc, readers)
        raise


async def _drain(stream, into: bytearray) -> None:
    if stream is None:
        return
    with contextlib.suppress(Exception):
        while True:
            chunk = await stream.read(8192)
            if not chunk:
                return
            into.extend(chunk)


async def _end(proc, readers) -> None:
    """Kill the child's whole group, politely then not, and stop reading."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if proc.returncode is not None:
            break
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(os.getpgid(proc.pid), sig)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=GRACE_S)
    for reader in readers:
        reader.cancel()
    await asyncio.gather(*readers, return_exceptions=True)


def _text(raw) -> str:
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)


def alive(pid: int) -> bool:
    """Whether `pid` is still there -- for a test that wants to prove the
    child is gone rather than trust that it is."""
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
    return True


__all__ = ["Completed", "GRACE_S", "alive", "run_child"]
