"""An instruction is a request. This is a check.

`DISTILL_INSTRUCTION` already says "every statement must be traceable to
the transcript -- add nothing, recommend nothing". It landed 2026-09-10
in `4c2f59d`, "Sim remembered a conversation that never happened", after
a distillation answered its window instead of summarising it.

It was not enough. On 2026-09-16 -- six days later -- a distillation
wrote this into durable memory, in the flat register of a fact:

    "A code note records that `prune_old` in `simorgh/memory.py` was
     reworked to compress rather than drop entries. ... Four tests pass
     in `tests/simorgh/test_memory.py`, committed as `abc1234`/`abc1235`."

Every specific is invented. There is no `simorgh/memory.py` (memory is a
package), no `prune_old` anywhere in the tree, no
`tests/simorgh/test_memory.py`, and neither sha is a valid git object.

The cruellest part is what the transcript actually held. The task it
claimed to describe had finished honestly -- "Nothing in the source tree
was changed, so there is nothing to commit", and it explained why it had
withheld the destructive prune. The truthful record went in; the lie
came out; and recall then handed the lie back as history.

So the guard is not stronger wording. A name the transcript never
mentioned is not a summary of it, whatever the sentence around it is
doing -- and that is mechanically checkable. Prose is left alone:
summarising is the job, and paraphrase is not fabrication.
"""

from __future__ import annotations

import unittest

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config
from simorgh.memory.consolidation import NOTHING, run_consolidation, untraceable
from simorgh.memory.store import MemoryEngine
from tests.simorgh.helpers import FakeClock

#: What the window actually said, on the night this was caught.
HONEST_WINDOW = (
    "Saeed: run a one-off prune that compresses old memories down to the important ones.\n"
    "Sim: Nothing in the source tree was changed, so there is nothing to commit. "
    "I did not run the prune itself because it is destructive."
)

#: What came back out of the distiller.
THE_FABRICATION = (
    "A code note records that `prune_old` in simorgh/memory.py was reworked to compress "
    "rather than drop entries. Four tests pass in tests/simorgh/test_memory.py, "
    "committed as abc1234/abc1235."
)


class TheCheckItselfTestCase(unittest.TestCase):
    def test_the_real_fabrication_is_caught(self):
        invented = untraceable(THE_FABRICATION, HONEST_WINDOW)
        for name in ("prune_old", "simorgh/memory.py", "abc1234"):
            self.assertIn(name, invented)

    def test_an_honest_summary_passes(self):
        self.assertEqual(
            untraceable("Saeed asked for a memory prune; Sim changed nothing and did not run it.",
                        HONEST_WINDOW),
            [])

    def test_a_specific_the_transcript_did_mention_is_not_invented(self):
        """The false positive that would make this guard useless: a
        summary is *supposed* to name what the transcript named."""
        window = "Sim: I reworked run_consolidation in simorgh/memory/consolidation.py."
        self.assertEqual(untraceable("Sim reworked simorgh/memory/consolidation.py.", window), [])

    def test_prose_is_never_the_thing_checked(self):
        """Paraphrase is the job. Only code-shaped specifics are held to
        the transcript."""
        self.assertEqual(
            untraceable("The family talked about dinner and the children argued about pizza.",
                        "Ira: pizza is not fair. Iris: you always get it."),
            [])


class ItIsNotStoredTestCase(unittest.IsolatedAsyncioTestCase):
    """The unrecoverable step is `engine.store`: once written, a
    fabrication is indistinguishable from a memory forever after."""

    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.engine = MemoryEngine(self.ledger, Config(half_life_seconds=1_000_000.0), clock=self.clock)
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="memory", clock=self.clock)
        await self.bus.start()

    async def asyncTearDown(self):
        await self.bus.stop()

    async def _consolidate(self, answer: str):
        async def _answer_think(message: Message) -> None:
            await self.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
                "text": answer, "tool_calls": [], "provider": "fake", "cost_usd": 0.0,
                "tokens": 10, "floor": False, "non_answer": False,
            })

        sub = await self.bus.subscribe(topics.COGNITION_THINK, _answer_think)
        try:
            return await run_consolidation(
                self.engine, bus=self.bus, source="memory",
                keep_per_kind={"episodic": 100, "semantic": 100})
        finally:
            await sub.unsubscribe()

    async def _semantic(self) -> list[str]:
        items, _ = await self.engine.retrieve(query="", kinds=["semantic"], k=20, filters=None)
        return [i.content for i in items]

    async def test_the_fabrication_never_reaches_memory(self):
        await self.engine.store(kind="episodic", content=HONEST_WINDOW,
                                tags=[], source_ref="", confidence=1.0)
        report = await self._consolidate(THE_FABRICATION)

        self.assertFalse(report.distilled, "it was stored anyway")
        self.assertTrue(report.refused, "the refusal was not reported")
        self.assertEqual(await self._semantic(), [], "a fabrication is in durable memory")

    async def test_a_faithful_distillation_is_still_stored(self):
        """The guard must not simply switch consolidation off."""
        await self.engine.store(kind="episodic", content=HONEST_WINDOW,
                                tags=[], source_ref="", confidence=1.0)
        report = await self._consolidate("Saeed asked for a memory prune; nothing was changed.")

        self.assertTrue(report.distilled)
        self.assertEqual(report.refused, [])
        self.assertEqual(len(await self._semantic()), 1)

    async def test_nothing_is_still_the_opt_out(self):
        await self.engine.store(kind="episodic", content=HONEST_WINDOW,
                                tags=[], source_ref="", confidence=1.0)
        report = await self._consolidate(NOTHING)

        self.assertFalse(report.distilled)
        self.assertEqual(report.refused, [])
        self.assertEqual(await self._semantic(), [])

    async def test_the_refusal_names_what_was_invented(self):
        """A refusal that says nothing is the bare `except` this
        codebase keeps being bitten by."""
        await self.engine.store(kind="episodic", content=HONEST_WINDOW,
                                tags=[], source_ref="", confidence=1.0)
        report = await self._consolidate(THE_FABRICATION)
        self.assertIn("simorgh/memory.py", report.refused)


if __name__ == "__main__":
    unittest.main()
