"""The growth merge left growth unable to write anything (2026-09-20).

Stage 8 item 1 folded learning, reflection and curiosity into one
subsystem, so their events now publish under the name `growth`. The
ledger's writer table still named the three that no longer existed,
and a bound ledger refuses a write whose source is not a declared
writer -- so from the merge until this test, every append to
`learn:*`, `reflect:*` and `curiosity:*` raised `WriterViolation` and
growth recorded nothing at all. No outcomes, no findings, no ticks.

Nothing caught it. The module tier builds a Service directly and hands
it the shared client; only a booted Kernel hands out a BOUND one, and
the only thing that boots a Kernel and then makes growth work is the
household simulator, which found it on its second run.

So this is the test that belongs beside the merge: every stream a part
of growth writes, growth may write.
"""

import unittest

from simorgh.contracts.streamnames import writers_for


class GrowthWritesWhatItsPartsAlwaysWrote(unittest.TestCase):
    #: One per part, plus the subsystem's own two.
    STREAMS = (
        "learn:outcomes",           # estimate (was learning)
        "reflect:patterns",         # monitors (was reflection)
        "reflect:health",
        "reflect:calibration",
        "reflection:alerts",
        "curiosity:ticks",          # explore (was curiosity)
        "curiosity:projects",
        "growth:policies",          # the subsystem's own
        "growth:candidates",
    )

    def test_every_stream_growth_writes_names_growth(self):
        for stream in self.STREAMS:
            with self.subTest(stream=stream):
                self.assertIn("growth", writers_for(stream),
                              f"growth cannot write {stream}: writers are {sorted(writers_for(stream))}")

    def test_the_subsystems_that_no_longer_exist_are_not_writers(self):
        gone = {"learning", "reflection", "curiosity"}
        for stream in self.STREAMS:
            with self.subTest(stream=stream):
                self.assertFalse(gone & writers_for(stream),
                                 f"{stream} still names a subsystem the merge removed")

    def test_the_old_prefixes_are_kept(self):
        """Renaming the streams would orphan every event written before
        the merge, so the prefixes stay and only the writer changes."""
        self.assertIn("growth", writers_for("learn:outcomes"))
        self.assertIn("growth", writers_for("curiosity:ticks"))


class ABoundLedgerLetsGrowthThrough(unittest.IsolatedAsyncioTestCase):
    """The check that actually failed live: a BOUND ledger, which is
    the only kind a booted subsystem gets."""

    async def test_growth_may_append_to_each_of_its_streams(self):
        from simorgh.contracts.envelope import Event
        from simorgh.ledger.bound import BoundLedger
        from simorgh.ledger.factory import make_ledger

        ledger = make_ledger({"backend": "memory"})
        await ledger.start()
        bound = BoundLedger(ledger, "growth")
        try:
            for stream in GrowthWritesWhatItsPartsAlwaysWrote.STREAMS:
                with self.subTest(stream=stream):
                    await bound.append(stream, Event(stream=stream, type="t", ts=1.0, trace_id="t",
                                                     causation_id=None, payload={"n": 1}))
        finally:
            await ledger.stop()

    async def test_somebody_else_still_may_not(self):
        """The rule is not being switched off, only pointed at the
        subsystem that exists."""
        from simorgh.contracts.envelope import Event
        from simorgh.ledger.bound import BoundLedger, WriterViolation
        from simorgh.ledger.factory import make_ledger

        ledger = make_ledger({"backend": "memory"})
        await ledger.start()
        try:
            with self.assertRaises(WriterViolation):
                await BoundLedger(ledger, "memory").append(
                    "growth:policies", Event(stream="growth:policies", type="t", ts=1.0,
                                             trace_id="t", causation_id=None, payload={}))
        finally:
            await ledger.stop()


if __name__ == "__main__":
    unittest.main()
