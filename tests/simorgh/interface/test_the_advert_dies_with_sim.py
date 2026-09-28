"""The mDNS advert for Sim ends when Sim does, and is never for port 0.

2026-09-27: `dns-sd -R Sim` processes were found orphaned, one three
days old, one advertising port 0 -- a test server's "any free port" --
beside the live one. The publisher runs in its own session and Sim's
shutdown ends in `os._exit`, so `stop()` did not always run."""

import os
import subprocess
import sys
import time
import unittest

from simorgh.interface.announce import Announcer, _dies_with


def _alive(pattern: str) -> int:
    return len(subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout.split())


class TheAdvertDiesWithSim(unittest.TestCase):
    def test_port_zero_is_never_announced(self):
        announcer = Announcer(0, ["http://127.0.0.1:0"])
        self.assertFalse(announcer.start())
        self.assertIn("0 is only for tests", announcer.detail)

    def test_the_child_ends_when_its_parent_does(self):
        parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
        watched = subprocess.Popen(_dies_with(parent.pid, ["sleep", "117"]), start_new_session=True)
        try:
            time.sleep(0.5)
            self.assertEqual(_alive("^sleep 117"), 1)
            parent.wait()
            watched.wait(timeout=6)
            time.sleep(0.2)
            self.assertEqual(_alive("^sleep 117"), 0)
        finally:
            subprocess.run(["pkill", "-f", "^sleep 117"])

    def test_a_clean_stop_ends_the_child_at_once(self):
        watched = subprocess.Popen(_dies_with(os.getpid(), ["sleep", "118"]), start_new_session=True)
        try:
            time.sleep(0.5)
            watched.terminate()
            watched.wait(timeout=2)
            time.sleep(0.2)
            self.assertEqual(_alive("^sleep 118"), 0)
        finally:
            subprocess.run(["pkill", "-f", "^sleep 118"])


if __name__ == "__main__":
    unittest.main()
