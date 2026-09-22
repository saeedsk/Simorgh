"""A cancelled `run_container` leaves nothing running (stage 7 item 8).

It ran `docker run` in a thread, which a cancel cannot stop: the step
ended and the container went on. And a container outlives its client
-- with `--rm` and nobody attached, killing the `docker` CLI does not
stop it. Now `docker run` is a `procs.run_child` process group, and a
cancel or a timeout also sends `docker kill <name>`.

Driven with a stand-in `docker` script, so no daemon is needed: `run`
records its pid and sleeps, `kill`/`rm` record themselves.
"""

import asyncio
import os
import stat
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.container import RunContainerTool


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie still answers kill(0); ask ps whether it is really running.
    state = os.popen(f"ps -o stat= -p {pid}").read().strip()
    return bool(state) and not state.startswith("Z")


class ACancelledContainer(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.marks = self.root / "marks"
        self.pidfile = self.root / "pid"
        docker = self.root / "docker"
        docker.write_text(textwrap.dedent(f"""\
            #!/bin/sh
            case "$1" in
              info) echo 24.0 ;;
              run) echo $$ > {self.pidfile}; exec sleep 30 ;;
              kill|rm) echo "$1 $2" >> {self.marks} ;;
            esac
            """))
        docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
        self.config = Config(repo_root=self.root)
        self.tool = RunContainerTool(self.config, docker_path=str(docker))
        self.ctx = ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                               data_dir=self.root, clock=None, logger=None, ledger=None)

    async def _started(self):
        for _ in range(100):
            if self.pidfile.exists() and self.pidfile.read_text().strip():
                return int(self.pidfile.read_text())
            await asyncio.sleep(0.05)
        self.fail("docker run never started")

    async def test_a_cancel_kills_the_client_and_the_container(self):
        run = asyncio.ensure_future(self.tool.run({"image": "python:3.12", "command": ["true"]}, ctx=self.ctx))
        pid = await self._started()
        run.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await run
        deadline = time.monotonic() + 2.0
        while _alive(pid) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        self.assertFalse(_alive(pid), "the docker client outlived the cancel")
        self.assertIn("kill simorgh-a1", self.marks.read_text())

    async def test_a_timeout_does_the_same(self):
        result = await self.tool.run({"image": "python:3.12", "command": ["true"], "timeout_s": 0.5}, ctx=self.ctx)
        pid = int(self.pidfile.read_text())
        self.assertFalse(result.ok)
        self.assertFalse(_alive(pid))
        self.assertIn("kill simorgh-a1", self.marks.read_text())


if __name__ == "__main__":
    unittest.main()
