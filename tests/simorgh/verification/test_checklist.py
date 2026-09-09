"""Checklist generation + per-item evaluation (checklist.py). Uses a fake
`think` callable rather than the real cognition.think wire call -- these
are unit tests of the parsing/aggregation logic, not the bus."""

import unittest

from simorgh.verification.api import ThinkReply, VerifyRequest
from simorgh.verification.checklist import AnsweredItem, ChecklistItem, _evidence, _trim, evaluate_checklist, generate_checklist
from simorgh.verification.config import VerificationConfig


def _req(checklist_hint=None) -> VerifyRequest:
    return VerifyRequest(
        verification_id="v1", task_id="t1", kind="task",
        subject={"description": "add empty-list handling", "result": "added a guard clause"},
        checklist_hint=checklist_hint,
    )


class TestGenerateChecklist(unittest.IsolatedAsyncioTestCase):
    async def test_checklist_hint_short_circuits_generation(self):
        items = await generate_checklist(None, _req(checklist_hint="does it work?"), VerificationConfig())
        self.assertEqual(items, [ChecklistItem(question="does it work?", required=True)])

    async def test_parses_numbered_required_and_optional_items(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="1. [required] handles empty list?\n2. [optional] has a test?\n")

        items = await generate_checklist(think, _req(), VerificationConfig())
        self.assertEqual(items, [
            ChecklistItem(question="handles empty list?", required=True),
            ChecklistItem(question="has a test?", required=False),
        ])

    async def test_unmarked_item_defaults_to_required(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="1. handles empty list?\n")

        items = await generate_checklist(think, _req(), VerificationConfig())
        self.assertTrue(items[0].required)

    async def test_floor_reply_yields_no_items(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="", floor=True, ok=False)

        items = await generate_checklist(think, _req(), VerificationConfig())
        self.assertEqual(items, [])

    async def test_respects_max_items(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="\n".join(f"{i}. q{i}" for i in range(1, 10)))

        config = VerificationConfig(checklist_max_items=3)
        items = await generate_checklist(think, _req(), config)
        self.assertEqual(len(items), 3)


class TestEvaluateChecklist(unittest.IsolatedAsyncioTestCase):
    async def test_yes_and_no_answers_parsed(self):
        replies = iter([ThinkReply(text="YES, it does."), ThinkReply(text="NO, missing a case.")])

        async def think(*, purpose, prompt):
            return next(replies)

        items = [ChecklistItem(question="q1", required=True), ChecklistItem(question="q2", required=False)]
        answered = await evaluate_checklist(think, _req(), items)
        self.assertEqual([a.answer for a in answered], ["yes", "no"])

    async def test_non_answer_becomes_none_not_no(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="I'll look at the file first.")

        answered = await evaluate_checklist(think, _req(), [ChecklistItem(question="q1", required=True)])
        self.assertIsNone(answered[0].answer)

    async def test_floor_reply_becomes_none(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="", floor=True, ok=False)

        answered = await evaluate_checklist(think, _req(), [ChecklistItem(question="q1", required=True)])
        self.assertIsNone(answered[0].answer)


if __name__ == "__main__":
    unittest.main()


class TestTheReviewerSeesWhatWasDone(unittest.IsolatedAsyncioTestCase):
    """Both prompts used to show only the task and the final answer's
    prose, so a correct patch with a green suite and a commit failed on
    a question the wording did not cover (2026-09-07). The session's
    step trail now rides in the subject and both prompts render it."""

    def _req_with_steps(self) -> VerifyRequest:
        return VerifyRequest(
            verification_id="v1", task_id="t1", kind="task",
            subject={
                "description": "add DEFAULT_HISTORY_LIMIT", "result": "done",
                "steps": [
                    {"tool": "apply_source_patch", "ok": True, "phase": "act", "summary": "wrote simorgh/x.py\n+DEFAULT_HISTORY_LIMIT = 200"},
                    {"tool": "run_tests", "ok": True, "phase": "act", "summary": "2652 passed"},
                    {"tool": "git_commit", "ok": True, "phase": "act", "summary": "[main abc] add it"},
                ],
            },
        )

    async def test_the_checklist_prompt_carries_the_steps_and_the_only_ask_rule(self):
        seen = []

        async def think(*, purpose, prompt):
            seen.append(prompt)
            return ThinkReply(ok=True, text="1. [required] is the constant there?", floor=False)

        await generate_checklist(think, self._req_with_steps(), VerificationConfig())
        self.assertIn("What was actually done, in order:", seen[0])
        self.assertIn("- apply_source_patch: wrote simorgh/x.py +DEFAULT_HISTORY_LIMIT = 200  ok", seen[0])
        self.assertIn("- run_tests: 2652 passed  ok", seen[0])
        self.assertIn("never [required]", seen[0])

    async def test_the_answer_prompt_carries_the_steps_and_allows_unknown(self):
        seen = []

        async def think(*, purpose, prompt):
            seen.append(prompt)
            return ThinkReply(ok=True, text="UNKNOWN\nnothing shows it", floor=False)

        [answered] = await evaluate_checklist(think, self._req_with_steps(), [ChecklistItem(question="q?", required=True)])
        self.assertIn("- git_commit: [main abc] add it  ok", seen[0])
        self.assertIn("UNKNOWN", seen[0])
        self.assertIsNone(answered.answer)

    async def test_no_steps_means_no_evidence_block(self):
        seen = []

        async def think(*, purpose, prompt):
            seen.append(prompt)
            return ThinkReply(ok=True, text="1. q?", floor=False)

        await generate_checklist(think, _req(), VerificationConfig())
        self.assertNotIn("What was actually done", seen[0])


class TestTrim(unittest.TestCase):
    """`_trim` is what stands between a real, complete quote and a
    reviewer being handed a fragment that reads as a different fact."""

    def test_short_text_is_unchanged(self):
        self.assertEqual(_trim("all good", 400), "all good")

    def test_cuts_at_a_word_boundary_not_mid_word(self):
        text = "sampling 21 CoT trajectories at temperature 0.7 with top_p 0.9"
        # A bare text[:48] lands mid-number: "...temperature 0."
        trimmed = _trim(text, 48)
        self.assertFalse(trimmed.startswith("sampling 21 CoT trajectories at temperature 0.7"[:48]) and trimmed[-1] == ".")
        # It must not silently end on a bare "0." that looks like a
        # complete (and different) fact.
        self.assertNotEqual(trimmed, text[:48])
        self.assertIn("...[cut]", trimmed)


class TestEvidenceReproducesAndFixesTheTruncationBug(unittest.TestCase):
    """Reproduces the exact shape two independent observers hit
    2026-09-08: an early step's tool-output summary is truncated
    mid-number ("temperature 0."), and a later step in the SAME run
    already has the complete, correct figure ("temperature 0.7"). The
    old `summary[:400]` (checklist.py) stacked on top of the old
    `[:300]` (session.py::_put_verify_subject) could turn a real,
    complete quote into a fragment indistinguishable from a source that
    only ever said "0." -- and a reviewer failed a correct answer on
    that basis. Both cuts are now word-boundary-aware and wide enough
    that the complete figure survives.
    """

    def test_a_later_step_with_the_complete_figure_is_not_swallowed(self):
        # Step 1: as if `_put_verify_subject` had already cut a long PDF
        # excerpt at a naive boundary, landing mid-number.
        early_truncated = (
            "read pages 4-5 of the paper: the study describes "
            "sampling 21 CoT trajectories per problem at temperature 0."
        )
        # Step 2: the full re-read later in the same run.
        later_complete = (
            "read pages 4-5 again in full: the study describes sampling "
            "21 CoT trajectories per problem at temperature 0.7 with top_p 0.9."
        )
        subject = {
            "steps": [
                {"tool": "read_file", "ok": True, "phase": "act", "summary": early_truncated},
                {"tool": "read_file", "ok": True, "phase": "act", "summary": later_complete},
            ],
        }
        rendered = _evidence(subject)
        # The complete figure from the later step must appear verbatim,
        # not itself re-truncated by the evidence formatter.
        self.assertIn("temperature 0.7 with top_p 0.9.", rendered)

    def test_a_long_single_step_summary_is_not_cut_mid_number(self):
        # One long step whose relevant fact lands right at the old
        # 400-char boundary -- reproduces the bug even without a second
        # step, since checklist._evidence used to re-truncate to 400
        # regardless of what session.py had already kept.
        padding = "x" * 380
        summary = f"{padding} the reported temperature was 0.7 exactly"
        subject = {"steps": [{"tool": "read_file", "ok": True, "phase": "act", "summary": summary}]}
        rendered = _evidence(subject)
        self.assertIn("temperature was 0.7 exactly", rendered)
        self.assertNotIn("temperature was 0.  ", rendered)
