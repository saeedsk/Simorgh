"""Learning's own health report.

`status` showed Learning green while its whole purpose was unreachable.
Two independent reasons, either fatal on its own (wave-21 observer
W21-12): nothing anywhere publishes `learn.pipeline.run`, and
`PatchPipeline` proposes a `draft_candidate` action for a tool that is
not registered. Answering "0 pipeline(s) running" was technically true
and entirely misleading -- the honesty rule this project keeps
relearning is that nothing may succeed while saying nothing true.
"""

from __future__ import annotations

import unittest

from simorgh.learning.service import Service


class TestLearningSaysWhatItCannotDo(unittest.IsolatedAsyncioTestCase):
    async def test_an_idle_learning_reports_degraded_with_the_real_reason(self):
        health = await Service().health()
        self.assertEqual(health.status, "degraded")
        self.assertIn("learn.pipeline.run", health.detail)
        self.assertIn("draft_candidate", health.detail)

    async def test_the_reason_names_what_does_work_instead(self):
        # A degraded report that leaves the reader stuck is only half
        # honest: `improve` really does work, through another path.
        health = await Service().health()
        self.assertIn("improve", health.detail)

    def test_draft_candidate_is_genuinely_not_registered(self):
        # The claim in the health string, asserted rather than trusted.
        from simorgh.execution.config import Config as ExecConfig
        from simorgh.execution.tools import builtin_tools

        self.assertNotIn("draft_candidate", {t.name for t in builtin_tools(ExecConfig())})

    def test_nothing_publishes_the_message_that_would_start_a_pipeline(self):
        """If someone wires a publisher later this fails, and the health
        string above needs revisiting -- which is the point of pinning
        it. Looks for real publish SITES (`Message.new(topics.X` or
        `.publish(... topics.X`), not mere mentions: the topic
        legitimately appears in `topics.py`, in its message definition,
        and in Learning's own multi-line `consumes` tuple."""
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[3] / "simorgh"
        publish_site = re.compile(
            r"(?:Message\.new|\.publish|bus\.new)\s*\(\s*(?:\n\s*)?topics\.LEARN_PIPELINE_RUN")
        offenders = [
            str(path.relative_to(root))
            for path in root.rglob("*.py")
            if publish_site.search(path.read_text())
        ]
        self.assertEqual(offenders, [], f"a publisher now exists: {offenders}")
