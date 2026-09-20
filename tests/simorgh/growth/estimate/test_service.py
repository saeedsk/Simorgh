"""Learning's `Service`: outcomes in, competence out, and honest health."""

from __future__ import annotations

import unittest

from simorgh.growth.estimate.service import Service


class TestLearningSaysWhatItCannotDo(unittest.IsolatedAsyncioTestCase):
    async def test_an_idle_learning_reports_ok_and_counts_untyped_turns(self):
        # The PatchPipeline that kept this "degraded" was unreachable by
        # construction and was retired on 2026-09-19. Learning's job is
        # recording outcomes; it says how many turns it refused to type.
        health = await Service().health()
        self.assertEqual(health.status, "ok")
        self.assertIn("untyped", health.detail)

    def test_draft_candidate_is_genuinely_not_registered(self):
        # The claim in the health string, asserted rather than trusted.
        from simorgh.execution.config import Config as ExecConfig
        from simorgh.execution.tools import builtin_tools

        self.assertNotIn("draft_candidate", {t.name for t in builtin_tools(ExecConfig())})

