"""A whisper-server outliving its Sim is found and ended.

A server is a CHILD of the Sim that started it, and Sim's shutdown ends
with `os._exit` (Ctrl-C had to work while a tool thread was busy), so
`close()` does not always run -- and a crash never runs it. The server
survives holding a multi-gigabyte model in RAM, and the next boot starts
another. Five were alive on the creator's laptop on 2026-09-22.

What makes an orphan findable is reparenting: its parent is pid 1, while
a server belonging to a LIVE Sim has that Sim's pid. Pinned here,
because that distinction is the whole safety of reaping: a parallel
agent's server, or one `tools/voice_replay.py` is using, must survive.
"""

import subprocess
import unittest

from simorgh.voice.stt.whisper_server import orphaned_servers, reap_orphaned_servers

PS_OUTPUT = """  501     1 /opt/homebrew/bin/whisper-server -m large-v3-turbo --host 127.0.0.1
  502  9900 /opt/homebrew/bin/whisper-server -m large-v3-turbo --host 127.0.0.1
  503     1 /opt/homebrew/bin/ffmpeg -i rtsp://camera
  504     1 /opt/homebrew/bin/whisper-cli -m large-v3-turbo
"""


def _ps(_argv, **_kw):
    return subprocess.CompletedProcess([], 0, stdout=PS_OUTPUT)


class OrphanedServers(unittest.TestCase):
    def test_only_the_orphan_is_named(self):
        self.assertEqual(orphaned_servers("/opt/homebrew/bin/whisper-server", ps=_ps), [501],
                         "502 belongs to a live Sim; 503 and 504 are other programs")

    def test_reaping_ends_exactly_those(self):
        killed = []
        ended = reap_orphaned_servers("whisper-server", ps=_ps, kill=lambda pid, sig: killed.append(pid))
        self.assertEqual((ended, killed), (1, [501]))

    def test_a_machine_without_ps_is_not_an_error(self):
        def _boom(_argv, **_kw):
            raise FileNotFoundError("ps")

        self.assertEqual(orphaned_servers("whisper-server", ps=_boom), [])


if __name__ == "__main__":
    unittest.main()
