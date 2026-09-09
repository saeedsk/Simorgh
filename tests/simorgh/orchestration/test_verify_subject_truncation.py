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


class TestWrittenPathsTravelWithTheVerifyRequest(unittest.TestCase):
    """The non-Python checks (`js_syntax`, `render`,
    `trailing_narration`) have to open the artifact to say anything true
    about it, and the request carried only prose -- so a generated page
    with an unclosed brace or the model's own commentary appended passed
    every mechanical gate (both happened, 2026-09-09). The session knows
    exactly which paths it wrote; now it says so."""

    @run
    async def test_the_paths_the_session_wrote_are_in_the_blobbed_subject(self):
        async with Harness() as h:
            bus = h.client("orchestration")
            runner = SessionRunner(bus, h.ledger, clock=h.clock.now)
            session = Session(
                task_id="t-paths", kind="patch", mode="execute", profile=profiles.PATCH,
                user_text="build the page", subject="docs/games/x.html",
            )
            session.steps.append(Step(1, "act", "wrote it", tool="apply_source_patch", ok=True))
            session.uncommitted.add("docs/games/x.html")
            session.created.add("docs/games/x.html")

            ref = await runner._put_verify_subject(session, "done")
            payload = json.loads(await h.ledger.get_blob(ref))

            self.assertEqual(payload["written_paths"], ["docs/games/x.html"])
            self.assertEqual(payload["subject"], "docs/games/x.html")

    @run
    async def test_a_session_that_wrote_nothing_reports_an_empty_list(self):
        async with Harness() as h:
            bus = h.client("orchestration")
            runner = SessionRunner(bus, h.ledger, clock=h.clock.now)
            session = Session(
                task_id="t-none", kind="research", mode="execute", profile=profiles.RESEARCH,
                user_text="what is x?",
            )
            session.steps.append(Step(1, "act", "read", tool="read_file", ok=True))

            payload = json.loads(await h.ledger.get_blob(await runner._put_verify_subject(session, "x")))
            self.assertEqual(payload["written_paths"], [])
            self.assertEqual(payload["subject"], "")


class TestRunTestsTargetMarkerReflectsWhatActuallyRan(unittest.TestCase):
    """`_propose_and_await` prefixes a `run_tests` step's recorded detail
    with `[ran target='...']`, which `FullSuiteRanCheck`
    (verification/checks/fullsuiteran.py) trusts to tell a whole-suite
    run from a narrowed one.

    The first version of this read `call.get("args", {}).get("target")`
    -- `call` is the marker-parsed call, and EVERY real marker call
    arrives as `call["args"] == {"argument": "<raw text>"}`.
    `to_action_payload` remaps that to the tool's real schema key in a
    FRESH dict it returns; it never mutates `call`. So the lookup always
    found nothing and always fell back to the literal `"tests"` default,
    for every real call, regardless of what actually ran -- an observer
    proved live that a 34-test slice was recorded and trusted as proof
    the whole 3080-test suite had passed (2026-09-08). This drives the
    real marker-call shape through the real `to_action_payload` remap,
    the only way the bug was actually reachable.
    """

    @run
    async def test_a_narrowed_marker_call_is_recorded_as_narrowed(self):
        from simorgh.contracts.envelope import Message

        async with Harness() as h:
            bus = h.client("orchestration")

            async def _answer_with_target(message):
                # A real tool result: `stdout_preview` never carries the
                # target back -- confirming the fix cannot depend on it.
                reply = message.caused(topics.ACTION_RESULT, {
                    "action_id": message.payload["action_id"], "ok": True,
                    "output_ref": "", "stdout_preview": "3 passed",
                    "duration_ms": 1, "side_effects": [],
                }, source="execution")
                await bus.publish(reply)

            from simorgh.contracts import topics
            sub = await bus.subscribe(topics.ACTION_PROPOSED, _answer_with_target)

            runner = SessionRunner(bus, h.ledger, clock=h.clock.now)
            session = Session(task_id="t-target", kind="patch", mode="execute", profile=profiles.PATCH)
            # The real marker shape: parser.py always produces this for
            # a single-string-argument marker, run_tests included.
            call = {"tool": "run_tests", "args": {"argument": "tests/simorgh/interface/test_service.py"}}
            ok, _bounded, full = await runner._propose_and_await(session, call, step_no=1)
            await sub.unsubscribe()

            self.assertTrue(ok)
            self.assertIn("[ran target='tests/simorgh/interface/test_service.py']", full)
            self.assertNotIn("[ran target='tests']", full)

    @run
    async def test_a_real_marker_call_with_no_target_is_recorded_as_the_whole_suite(self):
        from simorgh.contracts.envelope import Message

        async with Harness() as h:
            bus = h.client("orchestration")

            async def _answer(message):
                reply = message.caused(topics.ACTION_RESULT, {
                    "action_id": message.payload["action_id"], "ok": True,
                    "output_ref": "", "stdout_preview": "3080 passed",
                    "duration_ms": 1, "side_effects": [],
                }, source="execution")
                await bus.publish(reply)

            from simorgh.contracts import topics
            sub = await bus.subscribe(topics.ACTION_PROPOSED, _answer)

            runner = SessionRunner(bus, h.ledger, clock=h.clock.now)
            session = Session(task_id="t-whole", kind="patch", mode="execute", profile=profiles.PATCH)
            call = {"tool": "run_tests", "args": {"argument": ""}}
            _ok, _bounded, full = await runner._propose_and_await(session, call, step_no=1)
            await sub.unsubscribe()

            self.assertIn("[ran target='tests']", full)
