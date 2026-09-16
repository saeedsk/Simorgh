"""A contradiction needs a subject, not a shared provenance.

`flag_contradictions` groups by first tag, standing in for v1's
`metadata["subject"]`. Consolidation tags every summary `consolidation`,
so all of them shared a "subject" and each pass flagged the two newest
against each other. On the creator's ledger, 2026-09-16: 132
contradictions, all semantic-vs-semantic, all between adjacent records,
all "both tagged 'consolidation'" -- and 132 of the 134 summaries
carried two flags each, so `retrieve` scored every distilled memory at
0.5 x 0.5 = 0.25 and raw transcripts won.
"""

from __future__ import annotations

import time
import types
import unittest

from simorgh.memory.api import NOT_A_SUBJECT, is_real_contradiction, subject_of

LEGACY = {"ref_a": "memory:semantic:9", "ref_b": "memory:semantic:8",
          "evidence": "both tagged 'consolidation': 'Summary: an evening' vs 'Summary: another evening'"}
REAL = {"ref_a": "memory:semantic:4", "ref_b": "memory:semantic:3", "tag": "boiler",
        "evidence": "both tagged 'boiler': 'the boiler was serviced' vs 'the boiler is broken'"}
LEGACY_REAL = {"ref_a": "memory:semantic:2", "ref_b": "memory:semantic:1",
               "evidence": "both tagged 'boiler': 'serviced' vs 'broken'"}


class WhatCountsAsAContradiction(unittest.TestCase):
    def test_provenance_tags_are_not_subjects(self):
        self.assertIn("consolidation", NOT_A_SUBJECT)
        self.assertIn("distilled", NOT_A_SUBJECT)

    def test_two_summaries_of_different_evenings_do_not_contradict(self):
        self.assertFalse(is_real_contradiction(LEGACY))

    def test_two_claims_about_the_same_thing_still_do(self):
        self.assertTrue(is_real_contradiction(REAL))

    def test_a_legacy_event_is_judged_by_the_evidence_it_carries(self):
        """The stream is append-only: the 132 already written cannot be
        rewritten, so they are read for the tag they name."""
        self.assertEqual(subject_of(LEGACY), "consolidation")
        self.assertEqual(subject_of(LEGACY_REAL), "boiler")
        self.assertTrue(is_real_contradiction(LEGACY_REAL), "a real one from before the fix still counts")

    def test_an_unreadable_payload_is_not_treated_as_a_contradiction_subject(self):
        self.assertEqual(subject_of({}), "")
        self.assertTrue(is_real_contradiction({}), "no evidence either way: left alone")


class TheDetectorSkipsProvenance(unittest.IsolatedAsyncioTestCase):
    async def test_consolidation_summaries_are_never_flagged_against_each_other(self):
        from simorgh.memory.store import MemoryEngine
        from simorgh.memory.config import Config

        appended: list = []

        class _Ledger:
            async def read(self, stream, *, from_seq=0, limit=None):
                if not stream.endswith("semantic"):
                    return []
                return [
                    types.SimpleNamespace(seq=1, ts=1.0, payload={"content": "Summary: Monday", "tags": ["consolidation", "distilled"]}),
                    types.SimpleNamespace(seq=2, ts=2.0, payload={"content": "Summary: Tuesday", "tags": ["consolidation", "distilled"]}),
                ]

            async def append(self, stream, event, **kw):
                appended.append(event)
                return len(appended)

        engine = MemoryEngine(ledger=_Ledger(), config=Config(),
                              clock=types.SimpleNamespace(now=time.time))
        flagged = await engine.flag_contradictions(kind="semantic")
        self.assertEqual(flagged, [], "two evenings are two evenings")
        self.assertEqual(appended, [], "and nothing was written to the stream")


if __name__ == "__main__":
    unittest.main()
