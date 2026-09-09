"""`SessionRunner._put_verify_subject` blobs the step log for the
reviewer (session.py, "The steps travel too"). Two independent
observers (2026-09-08) found the same false-negative: a correct answer
was rejected because the checklist reviewer judged a TRUNCATED
intermediate tool-step summary instead of a later step in the same run
that already held the full, correct data. Root cause: `_put_verify_
subject` cut every non-patch step's `summary` to a bare `[:300]` --
far below the `_DETAIL_CHARS == 2000` a step's `summary` (== `detail`)
actually carries -- and a hard character slice cuts mid-word/mid-number,
so "sampling 21 CoT trajectories... temperature 0.7" became
"...temperature 0.": indistinguishable from a source that only ever
said "0.". `checklist.py::_evidence` then re-truncated to 400 again on
top of that.

These tests exercise the real `_put_verify_subject` (not a fake) against
the real in-memory Ledger, constructing a step list where an early step
carries a long tool-output summary whose relevant fact lands past the
old 300-char cut, and check that the blobbed subject keeps the complete
fact.
"""

from __future__ import annotations

import json
import unittest

from simorgh.orchestration.api import Session, Step
from simorgh.orchestration import profiles
from simorgh.orchestration.session import SessionRunner, _trim_evidence

from .harness import Harness, run


class TestTrimEvidence(unittest.TestCase):
    def test_text_within_the_limit_is_untouched(self):
        self.assertEqual(_trim_evidence("short", 2000), "short")

    def test_a_cut_lands_on_a_word_boundary_and_says_so(self):
        text = "the study describes sampling 21 CoT trajectories at temperature 0.7 with top_p 0.9"
        cut_index = text.index("temperature 0.") + len("temperature 0.")  # lands mid-number
        trimmed = _trim_evidence(text, cut_index)
        self.assertNotEqual(trimmed, text[:cut_index])  # not the naive slice
        self.assertTrue(trimmed.endswith("...[cut]"))
        self.assertNotIn("temperature 0.", trimmed)  # backed off before the broken number


class TestPutVerifySubjectKeepsTheFullFigure(unittest.TestCase):
    """Reproduces the PDF-research scenario end to end through the real
    method and the real Ledger blob store."""

    @run
    async def test_a_tool_output_summary_past_the_old_300_char_cut_survives(self):
        async with Harness() as h:
            bus = h.client("orchestration")
            runner = SessionRunner(bus, h.ledger, clock=h.clock.now)
            session = Session(
                task_id="t-trunc", kind="research", mode="execute",
                profile=profiles.RESEARCH, user_text="what sampling temperature did the paper use?",
            )
            # Step 1: a long tool-output detail (as `_propose_and_await`
            # stores it -- up to `_DETAIL_CHARS == 2000`) whose relevant
            # figure sits past the old 300-char cutoff.
            padding = "the paper first discusses unrelated setup details. " * 6  # > 300 chars
            summary = padding + "The study describes sampling 21 CoT trajectories per problem at temperature 0.7 with top_p 0.9."
            self.assertGreater(len(padding), 300)
            session.steps.append(Step(1, "act", summary, tool="read_file", ok=True))

            ref = await runner._put_verify_subject(session, "The paper used temperature 0.7.")
            blob = await h.ledger.get_blob(ref)
            payload = json.loads(blob)

            kept = payload["steps"][0]["summary"]
            self.assertIn("temperature 0.7 with top_p 0.9.", kept)
