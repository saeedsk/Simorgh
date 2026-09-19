"""One typed turn is one trace, percept to turn.completed (stage 1 item 2).

Before, a chat session used its conversation id as the trace of every
message it sent, so each turn of a conversation shared one trace, and the
context requests Cognition made while assembling a prompt minted fresh
traces of their own: "why was that turn slow" had no single answer.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest

from simorgh.contracts import topics
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel

_WATCHED = (topics.PERCEPT_TEXT_RECEIVED, topics.COGNITION_THINK, topics.PERSONA_VOICE,
            topics.SELF_SUMMARY, topics.TURN_COMPLETED)


class OneTurnIsOneTrace(unittest.IsolatedAsyncioTestCase):
    async def test_two_turns_are_two_traces_each_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = Kernel(LoadedConfig({"runtime": {"data_dir": tmp}}, None), secrets=EnvSecretStore({}))
            await kernel.boot()
            try:
                interface = kernel._supervisor.services["interface"].service  # noqa: SLF001
                interface._out = lambda *_: None  # noqa: SLF001
                seen: list[tuple[str, str]] = []

                def _see(message):
                    seen.append((message.type, message.trace_id))
                    return asyncio.sleep(0)

                subs = [await kernel.bus.subscribe(t, _see) for t in _WATCHED]
                traces = []
                for line in ("hello there", "and how are you"):
                    before = len(seen)
                    await interface._handle_line(line)  # noqa: SLF001
                    for _ in range(200):
                        if any(t == topics.TURN_COMPLETED for t, _ in seen[before:]):
                            break
                        await asyncio.sleep(0.05)
                    turn = seen[before:]
                    kinds = {t for t, _ in turn}
                    self.assertIn(topics.PERCEPT_TEXT_RECEIVED, kinds)
                    self.assertIn(topics.COGNITION_THINK, kinds)
                    self.assertIn(topics.TURN_COMPLETED, kinds)
                    ids = {tr for _, tr in turn}
                    self.assertEqual(len(ids), 1, turn)
                    traces.append(ids.pop())
                self.assertNotEqual(traces[0], traces[1])
                for sub in subs:
                    await sub.unsubscribe()
            finally:
                await kernel.shutdown()


if __name__ == "__main__":
    unittest.main()
