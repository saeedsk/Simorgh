"""`[orchestration] ablate` (stage 14 item 3): each guardrail switched off
on its own changes what the loop does, and the default changes nothing.

The switches exist for the eval sandbox's ablation matrix
(docs/plan/stage-14-toolchain-evals-and-ablation.md, "Switch meanings").
None of them may touch Guardian: a denial of an offered tool on safety
grounds is still a denial the model hears about."""

from __future__ import annotations

import unittest
from dataclasses import replace

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.orchestration import profiles, scaffolds
from simorgh.orchestration.api import Budget, Session
from simorgh.orchestration.config import Config
from simorgh.orchestration.session import NO_RECOVERY_REASON, VERIFICATION_REASON, SessionRunner

from .fakes import FakeCognition, FakeGuardianExecution, FakeVerification
from .harness import Harness, run


class _FailingExecution(FakeGuardianExecution):
    """Approves every call; the tool then fails, as a flaky device would."""

    async def _on(self, message: Message) -> None:
        self.proposals.append(message)
        await self._bus.publish(message.caused(topics.ACTION_RESULT, {
            "action_id": message.payload["action_id"], "ok": False, "output_ref": "",
            "stdout_preview": "", "error": "device unreachable", "error_kind": "failed",
            "duration_ms": 1, "side_effects": [],
        }, source="execution"))


async def _session(h, *, script, ablate=(), verdicts=("pass",), execution=FakeGuardianExecution,
                   verify=False, max_revisions=0, task_id="t-ablate"):
    cognition = FakeCognition(h.client("cognition"), script=list(script))
    gx = execution(h.client("guardian")) if execution is not None else None
    verification = FakeVerification(h.client("verification"), verdicts=list(verdicts))
    await cognition.start(); await verification.start()
    if gx is not None:
        await gx.start()
    runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05,
                           ablate=tuple(ablate))
    session = Session(task_id=task_id, kind="research", mode="execute", user_text="find it",
                      profile=replace(profiles.RESEARCH, verify=verify, max_revisions=max_revisions, max_steps=8),
                      budget=Budget(max_steps=8, max_revisions=max_revisions))
    outcome = await runner.run(session, user_text="find it")
    await cognition.stop(); await verification.stop()
    if gx is not None:
        await gx.stop()
    return outcome, cognition, verification, session


class ConfigKey(unittest.TestCase):
    def test_default_is_empty_and_reports_nothing(self):
        self.assertEqual(Config().ablate, ())
        self.assertEqual(Config.from_mapping({}).problems, ())

    def test_unknown_names_are_problems_not_a_crash(self):
        cfg = Config.from_mapping({"ablate": ["verify", "guardian", "scafold", "verify"]})
        self.assertEqual(cfg.ablate, ("verify",))
        self.assertEqual(len(cfg.problems), 2)
        self.assertIn("'guardian'", cfg.problems[0])

    def test_profiles_ablated_is_identity_with_no_switch(self):
        self.assertIs(profiles.ablated(profiles.PATCH, ()), profiles.PATCH)
        self.assertIs(profiles.ablated(profiles.PATCH, ("scaffold", "recovery")), profiles.PATCH)


class DefaultChangesNothing(unittest.TestCase):
    def test_the_rules_are_byte_identical(self):
        for profile in (profiles.CHAT, profiles.PATCH, profiles.RESEARCH, profiles.VOICE_CHAT):
            self.assertEqual(scaffolds.render(profile, task="x", channel="cli"),
                             scaffolds.render(profile, task="x", channel="cli", workflow=True))

    @run
    async def test_a_failed_tool_still_goes_back_to_the_model(self):
        async with Harness() as h:
            outcome, cognition, verification, _ = await _session(
                h, script=[{"tool_calls": [{"tool": "read_file", "args": {"path": "a"}}]}, {"text": "it was down"}],
                execution=_FailingExecution, verify=True, max_revisions=1)
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(len(cognition.calls), 2)
            self.assertEqual(len(verification.requests), 1)
            self.assertIn(scaffolds.scaffold_body(profiles.RESEARCH)[:60], cognition.calls[0].payload["task_rules"])


class Scaffold(unittest.TestCase):
    def test_the_workflow_text_is_gone_and_the_tools_stay(self):
        bare = scaffolds.render(profiles.PATCH, task="fix   the parser", subject="a.py", workflow=False)
        self.assertNotIn(scaffolds.scaffold_body(profiles.PATCH)[:80], bare)
        self.assertNotIn("The file is `a.py`", bare)
        self.assertIn("Your task: fix the parser", bare)
        self.assertIn("Tools available to you this session:", bare)
        self.assertIn("- read_file", bare)

    def test_who_is_speaking_and_the_language_stay(self):
        bare = scaffolds.render(profiles.VOICE_CHAT, channel="voice", speaker="Saeed", speaker_relation="owner",
                                heard_language="en", workflow=False)
        self.assertIn(scaffolds.language_line("en"), bare)
        self.assertIn(scaffolds.who_is_here("Saeed", "owner", ""), bare)
        self.assertNotIn(scaffolds.VOICE, bare)
        self.assertNotIn(scaffolds.FARSI_VOWELS, bare)

    @run
    async def test_the_session_sends_the_bare_rules(self):
        async with Harness() as h:
            _, cognition, _, _ = await _session(h, script=[{"text": "done"}], ablate=("scaffold",))
            rules = cognition.calls[0].payload["task_rules"]
            self.assertNotIn(scaffolds.scaffold_body(profiles.RESEARCH)[:60], rules)
            self.assertIn("Your task: find it", rules)
            self.assertTrue(cognition.calls[0].payload["tools"], "the tools are still offered")


class Verify(unittest.TestCase):
    @run
    async def test_no_verification_is_asked_for(self):
        async with Harness() as h:
            outcome, _, verification, session = await _session(
                h, script=[{"text": "answer"}], ablate=("verify",), verify=True, max_revisions=1)
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(verification.requests, [])
            self.assertFalse(session.profile.verify)


class Revisions(unittest.TestCase):
    @run
    async def test_a_rejected_answer_gets_no_revision(self):
        async with Harness() as h:
            outcome, cognition, verification, session = await _session(
                h, script=[{"text": "first"}, {"text": "revised"}], ablate=("revisions",),
                verdicts=("fail", "pass"), verify=True, max_revisions=2)
            self.assertEqual(outcome.kind, "blocked")
            self.assertTrue(outcome.reason.startswith(VERIFICATION_REASON), outcome.reason)
            self.assertEqual(len(verification.requests), 1)
            self.assertEqual(len(cognition.calls), 1)
            self.assertEqual((session.profile.max_revisions, session.budget.max_revisions), (0, 0))

    @run
    async def test_without_the_switch_the_same_answer_is_revised(self):
        async with Harness() as h:
            outcome, _, verification, _ = await _session(
                h, script=[{"text": "first"}, {"text": "revised"}],
                verdicts=("fail", "pass"), verify=True, max_revisions=2)
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(len(verification.requests), 2)


class Recovery(unittest.TestCase):
    @run
    async def test_a_failed_tool_ends_the_session(self):
        async with Harness() as h:
            outcome, cognition, _, session = await _session(
                h, script=[{"tool_calls": [{"tool": "read_file", "args": {"path": "a"}}]}, {"text": "it was down"}],
                ablate=("recovery",), execution=_FailingExecution)
            self.assertEqual(outcome.kind, "failed")
            self.assertTrue(outcome.reason.startswith(NO_RECOVERY_REASON), outcome.reason)
            self.assertIn("device unreachable", outcome.reason)
            self.assertEqual(len(cognition.calls), 1, "the error never went back to the model")
            self.assertFalse(session.steps[-1].ok)

    @run
    async def test_a_malformed_native_call_ends_the_session(self):
        async with Harness() as h:
            outcome, cognition, _, _ = await _session(
                h, script=[{"tool_calls": [{"id": "c1", "tool": "read_file", "args": {},
                                            "error": "arguments were not a JSON object"}]}, {"text": "x"}],
                ablate=("recovery",))
            self.assertEqual(outcome.kind, "failed")
            self.assertIn("malformed read_file", outcome.reason)
            self.assertEqual(len(cognition.calls), 1)

    @run
    async def test_a_marker_for_a_tool_that_does_not_exist_ends_the_session(self):
        async with Harness() as h:
            outcome, cognition, _, _ = await _session(
                h, script=[{"text": "Sure.\nTELEPORT_HOME: now"}, {"text": "x"}], ablate=("recovery",))
            self.assertEqual(outcome.kind, "failed", outcome.reason)
            self.assertIn("TELEPORT_HOME".lower(), outcome.reason.lower())
            self.assertEqual(len(cognition.calls), 1)

    @run
    async def test_a_safety_denial_of_an_offered_tool_is_unchanged(self):
        class _Denying(FakeGuardianExecution):
            def __init__(self, bus):
                super().__init__(bus, deny=True)

        async with Harness() as h:
            outcome, cognition, _, _ = await _session(
                h, script=[{"tool_calls": [{"tool": "read_file", "args": {"path": "a"}}]}, {"text": "I was not allowed"}],
                ablate=("recovery",), execution=_Denying)
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(len(cognition.calls), 2, "the denial still went back to the model")


if __name__ == "__main__":
    unittest.main()
