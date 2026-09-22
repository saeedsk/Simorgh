"""Consolidation's wait IS the deadline the providers share.

Live, 2026-09-22: Memory asked Cognition with a 30 s wait; the Router
splits what is left between the candidates (`remaining / (still to try
+ 1)`), so each of four providers got about 8 s. Together timed out,
Gemini was abandoned at 8 s -- and its answer came back `200 OK` five
seconds later -- the Claude CLI got 6.9 s, and the offline floor
"consolidated" nothing. Nobody waits on this work.
"""

import asyncio
import unittest
from unittest import mock

from simorgh.memory.config import Config
from simorgh.memory.service import Service


class TheWait(unittest.TestCase):
    def test_the_default_leaves_a_real_slice_for_each_provider(self):
        # Four candidates, the Router's own share: remaining / (left + 1).
        self.assertGreaterEqual(Config().consolidate_timeout_s / 5, 20.0)

    def test_the_configured_wait_reaches_run_consolidation(self):
        service = Service.__new__(Service)
        service._config = Config(consolidate_timeout_s=99.0)   # noqa: SLF001
        service._keep_per_kind = 10                            # noqa: SLF001
        service.engine = object()
        service._ctx = mock.MagicMock()                        # noqa: SLF001
        service._ctx.bus.publish = mock.AsyncMock()            # noqa: SLF001
        service._ctx.clock.now.return_value = 1000.0
        seen = {}

        async def _fake(engine, **kw):
            seen.update(kw)
            return mock.Mock(contradictions=[], refused=[], distilled=None, pruned={})

        with mock.patch("simorgh.memory.service.run_consolidation", side_effect=_fake):
            asyncio.run(service._consolidate(window=None))     # noqa: SLF001
        self.assertEqual(seen.get("cognition_timeout"), 99.0)


if __name__ == "__main__":
    unittest.main()
