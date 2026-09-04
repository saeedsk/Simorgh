import tempfile
import unittest
from pathlib import Path

from src.agents.interests import InterestTracker
from src.agents.skills.research import SkillResearchAgent
from src.main import (
    autocorrect_command,
    build_router,
    discover_command,
    extract_batch_args,
    extract_patch_args,
    extract_plan_args,
    extract_propose_topic,
    handle_turn,
    note_interest,
    plan_goal,
    propose_self_patch,
    propose_skill,
    propose_skill_batch,
    run_skill_code,
    run_task,
    strip_command_slash,
    use_skill,
    work_on_next_task,
)
from src.cognition.provider import CognitionRouter
from src.memory.long_term import InMemoryStore
from src.orchestrator.activity_log import ActivityLog
from src.orchestrator.apply import APPLIED_KIND, APPLIED_PATCH_KIND
from src.orchestrator.audit import AuditGate, ModificationProposal
from src.orchestrator.health import HealthMonitor
from src.orchestrator.reflection import OutcomeLog, ReflectionAgent
from src.orchestrator.tasks import BLOCKED, DONE, PATCH_TASK, PENDING, SKILL_TASK, TaskStore


class TestMainCli(unittest.TestCase):
    def test_handle_turn_returns_combined_reaction_and_response(self):
        router = build_router()

        output = handle_turn(router, "This is great news, thanks!")

        self.assertIn("Here's my take", output)
        self.assertTrue(output[0].isupper())

    def test_handle_turn_updates_shared_mood_across_calls(self):
        router = build_router()

        handle_turn(router, "This is terrible and awful")

        self.assertLess(router.bus.read().valence, 0)

    def test_handle_turn_flags_heavy_cognitive_load(self):
        router = build_router()

        for _ in range(15):
            handle_turn(router, "another task")

        output = handle_turn(router, "one more task")

        self.assertIn("taking a moment to think this through", output)

    def test_handle_turn_records_outcomes_when_given_a_log(self):
        router = build_router()
        log = OutcomeLog(InMemoryStore())

        handle_turn(router, "hello there", log)

        outcomes = log.recent()
        agents = {o.agent for o in outcomes}
        self.assertEqual(agents, {"emotion", "logic"})
        self.assertTrue(all(o.succeeded for o in outcomes))

    def test_handle_turn_without_a_log_does_not_error(self):
        router = build_router()
        # outcome_log defaults to None -- should behave exactly as before
        output = handle_turn(router, "hello there")
        self.assertTrue(output)

    def test_handle_turn_self_corrects_when_mood_is_pinned_at_an_extreme(self):
        router = build_router()
        for _ in range(6):
            router.bus.publish_state("test", valence=1.0, arousal=1.0)
        monitor = HealthMonitor()

        output = handle_turn(router, "just checking in", health_monitor=monitor)

        self.assertIn("self-correction", output)
        self.assertEqual(router.bus.read().valence, 0.0)
        self.assertEqual(router.bus.read().arousal, 0.0)

    def test_handle_turn_without_health_monitor_does_not_self_correct(self):
        router = build_router()
        for _ in range(6):
            router.bus.publish_state("test", valence=1.0, arousal=1.0)

        output = handle_turn(router, "just checking in")

        self.assertNotIn("self-correction", output)
        self.assertEqual(router.bus.read().valence, 1.0)

    def test_handle_turn_with_health_monitor_and_stable_mood_is_unaffected(self):
        router = build_router()
        monitor = HealthMonitor()

        output = handle_turn(router, "hello there", health_monitor=monitor)

        self.assertNotIn("self-correction", output)

    def test_handle_turn_records_conversation_turn_when_given_an_activity_log(self):
        router = build_router()
        store = InMemoryStore()
        activity_log = ActivityLog(store)

        reply = handle_turn(router, "hello there", activity_log=activity_log)

        entries = activity_log.recent()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].content, "hello there")
        self.assertEqual(entries[0].metadata["reply"], reply)

    def test_handle_turn_without_activity_log_does_not_error(self):
        router = build_router()
        output = handle_turn(router, "hello there")
        self.assertTrue(output)

    def test_handle_turn_notices_llm_degraded_to_rule_based_when_llm_was_configured(self):
        import contextlib
        import io

        router = build_router()  # no cognition -- always rule-based

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            handle_turn(router, "hello there", llm_configured=True)

        self.assertIn("LLM access isn't available", buf.getvalue())

    def test_handle_turn_says_nothing_when_llm_was_never_configured(self):
        import contextlib
        import io

        router = build_router()

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            handle_turn(router, "hello there", llm_configured=False)

        self.assertNotIn("LLM access isn't available", buf.getvalue())

    def test_handle_turn_says_nothing_when_llm_actually_answered(self):
        import contextlib
        import io

        from src.agents.logic.base import LogicAgent
        from src.cognition.provider import CognitionRouter, LLMResponse

        class FakeProvider:
            def available(self):
                return True

            def complete(self, prompt, **kwargs):
                return LLMResponse(text="a real answer", provider_name="fake")

        router = build_router(cognition=CognitionRouter([FakeProvider()]))

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            handle_turn(router, "hello there", llm_configured=True)

        self.assertNotIn("LLM access isn't available", buf.getvalue())

    def test_dispatch_and_record_prints_a_takeaway_on_failure_when_reflection_agent_given(self):
        import contextlib
        import io

        from src.main import _dispatch_and_record
        from src.orchestrator.router import AgentRequest

        class RaisingRouter:
            def dispatch(self, name, request):
                raise ValueError("boom")

        outcome_log = OutcomeLog(InMemoryStore())
        reflection_agent = ReflectionAgent(outcome_log)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _dispatch_and_record(
                RaisingRouter(), "logic", AgentRequest(text="x"), outcome_log, reflection_agent
            )

        self.assertIn("takeaway", buf.getvalue())
        self.assertIn("boom", buf.getvalue())

    def test_dispatch_and_record_without_reflection_agent_prints_no_takeaway(self):
        import contextlib
        import io

        from src.main import _dispatch_and_record
        from src.orchestrator.router import AgentRequest

        class RaisingRouter:
            def dispatch(self, name, request):
                raise ValueError("boom")

        outcome_log = OutcomeLog(InMemoryStore())

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _dispatch_and_record(RaisingRouter(), "logic", AgentRequest(text="x"), outcome_log)

        self.assertNotIn("takeaway", buf.getvalue())


class TestProposeSkill(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_clean_proposal_is_applied_immediately(self):
        store = InMemoryStore()
        message = propose_skill(
            SkillResearchAgent(), AuditGate(), store, "rocketry", repo_root=self.repo_root
        )

        self.assertIn("APPLIED", message)
        applied = store.query(kind=APPLIED_KIND)
        self.assertEqual(len(applied), 1)
        self.assertIn("rocketry", applied[0].content)
        written = self.repo_root / "src/agents/skills/rocketry.py"
        self.assertTrue(written.exists())
        self.assertIn("rocketry", written.read_text())

    def test_clean_proposal_is_auto_committed_when_repo_root_is_a_real_git_repo(self):
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=self.repo_root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=self.repo_root, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo_root, check=True)
        store = InMemoryStore()

        message = propose_skill(
            SkillResearchAgent(), AuditGate(), store, "rocketry", repo_root=self.repo_root
        )

        self.assertIn("committed (not pushed)", message)
        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=self.repo_root, capture_output=True, text=True
        )
        self.assertIn("rocketry", log.stdout)

    def test_proposal_still_applies_when_repo_root_is_not_a_git_repo(self):
        # Auto-commit failing (no .git here) must never roll back or
        # block the already-successful disk write.
        store = InMemoryStore()

        message = propose_skill(
            SkillResearchAgent(), AuditGate(), store, "rocketry", repo_root=self.repo_root
        )

        self.assertIn("APPLIED", message)
        self.assertIn("NOT committed", message)
        self.assertTrue((self.repo_root / "src/agents/skills/rocketry.py").exists())

    def test_empty_topic_is_rejected_with_usage_message(self):
        store = InMemoryStore()
        message = propose_skill(
            SkillResearchAgent(), AuditGate(), store, "", repo_root=self.repo_root
        )

        self.assertIn("usage", message)
        self.assertEqual(store.query(kind=APPLIED_KIND), [])

    def test_retries_with_feedback_after_a_rejected_draft(self):
        from src.orchestrator.audit import ModificationProposal

        class FlakySkillResearch:
            def __init__(self):
                self.calls = []

            def draft_skill(self, topic, subject=None, prior_reasons=None):
                self.calls.append(prior_reasons)
                if len(self.calls) == 1:
                    code = "eval('1')"  # denylisted -- rejected first try
                else:
                    code = "def run():\n    return 1\n"
                return ModificationProposal(
                    subject=f"src/agents/skills/{topic}.py", code=code, rationale="r"
                )

        store = InMemoryStore()
        research = FlakySkillResearch()

        message = propose_skill(
            research, AuditGate(), store, "flaky", repo_root=self.repo_root
        )

        self.assertIn("APPLIED", message)
        self.assertEqual(len(research.calls), 2)
        self.assertIsNone(research.calls[0])
        self.assertTrue(any("eval" in r for r in research.calls[1]))

    def test_gives_up_after_max_attempts(self):
        from src.orchestrator.audit import ModificationProposal

        class AlwaysBadSkillResearch:
            def __init__(self):
                self.calls = 0

            def draft_skill(self, topic, subject=None, prior_reasons=None):
                self.calls += 1
                return ModificationProposal(
                    subject="src/agents/skills/bad.py", code="eval('1')", rationale="r"
                )

        store = InMemoryStore()
        research = AlwaysBadSkillResearch()

        message = propose_skill(
            research, AuditGate(), store, "bad", repo_root=self.repo_root, max_attempts=2
        )

        self.assertIn("rejected after 2 attempt(s)", message)
        self.assertEqual(research.calls, 2)


class TestNoteInterest(unittest.TestCase):
    def test_notes_a_topic(self):
        store = InMemoryStore()
        tracker = InterestTracker(store)

        message = note_interest(tracker, "rocketry")

        self.assertIn("rocketry", message)
        self.assertEqual(len(tracker.list_interests()), 1)

    def test_empty_topic_shows_usage(self):
        tracker = InterestTracker(InMemoryStore())

        message = note_interest(tracker, "")

        self.assertIn("usage", message)
        self.assertEqual(tracker.list_interests(), [])


class TestRunSkillCode(unittest.TestCase):
    def test_build_router_registers_skills_agent(self):
        router = build_router()
        self.assertIn("skills", router.agent_names())

    def test_runs_code_and_returns_stdout(self):
        router = build_router()
        log = OutcomeLog(InMemoryStore())

        output = run_skill_code(router, log, "print('hello from sandbox')")

        self.assertIn("hello from sandbox", output)

    def test_failing_code_is_reported_not_raised(self):
        router = build_router()
        log = OutcomeLog(InMemoryStore())

        output = run_skill_code(router, log, "raise ValueError('boom')")

        self.assertIn("ValueError", output)

    def test_empty_code_shows_usage(self):
        router = build_router()
        log = OutcomeLog(InMemoryStore())

        message = run_skill_code(router, log, "")

        self.assertIn("usage", message)

    def test_run_records_an_outcome(self):
        router = build_router()
        log = OutcomeLog(InMemoryStore())

        run_skill_code(router, log, "print('hi')")

        outcomes = log.recent()
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].agent, "skills")
        self.assertTrue(outcomes[0].succeeded)


class TestStripCommandSlash(unittest.TestCase):
    def test_strips_a_leading_slash(self):
        self.assertEqual(strip_command_slash("/reflect"), "reflect")

    def test_strips_leading_slash_from_prefixed_command(self):
        self.assertEqual(strip_command_slash("/propose a calculator"), "propose a calculator")

    def test_leaves_input_without_a_leading_slash_unchanged(self):
        self.assertEqual(strip_command_slash("reflect"), "reflect")
        self.assertEqual(strip_command_slash("hey there"), "hey there")

    def test_bare_slash_becomes_empty_string(self):
        self.assertEqual(strip_command_slash("/"), "")

    def test_only_strips_one_leading_slash(self):
        self.assertEqual(strip_command_slash("//reflect"), "/reflect")


class TestExtractProposeTopic(unittest.TestCase):
    def test_propose_prefix_extracts_topic(self):
        text = "propose a calculator"
        self.assertEqual(extract_propose_topic(text, text.lower()), "a calculator")

    def test_improve_prefix_also_extracts_topic(self):
        text = "improve yourself with a calculator"
        self.assertEqual(
            extract_propose_topic(text, text.lower()), "yourself with a calculator"
        )

    def test_improve_prefix_is_case_insensitive(self):
        text = "Improve error handling"
        self.assertEqual(extract_propose_topic(text, text.lower()), "error handling")

    def test_non_matching_input_returns_none(self):
        text = "hey there"
        self.assertIsNone(extract_propose_topic(text, text.lower()))

    def test_word_containing_improve_is_not_mistaken_for_the_prefix(self):
        text = "improvement tracking"
        self.assertIsNone(extract_propose_topic(text, text.lower()))


class TestExtractPatchArgs(unittest.TestCase):
    def test_parses_path_and_description(self):
        text = "patch src/agents/logic/base.py handle retries better"
        self.assertEqual(
            extract_patch_args(text, text.lower()),
            ("src/agents/logic/base.py", "handle retries better"),
        )

    def test_non_matching_input_returns_none(self):
        text = "hey there"
        self.assertIsNone(extract_patch_args(text, text.lower()))

    def test_missing_description_returns_empty_pair(self):
        text = "patch src/agents/logic/base.py"
        self.assertEqual(extract_patch_args(text, text.lower()), ("", ""))

    def test_bare_patch_with_no_trailing_space_is_not_matched(self):
        # Consistent with extract_propose_topic: a prefix requires its
        # trailing space, same as "propose"/"improve" alone don't match.
        text = "patch"
        self.assertIsNone(extract_patch_args(text, text.lower()))


class FakeSelfPatchAgent:
    def __init__(self, proposals):
        self._proposals = proposals
        self.calls = []

    def draft_patch(self, subject, topic, prior_reasons=None):
        self.calls.append((subject, topic, prior_reasons))
        index = min(len(self.calls) - 1, len(self._proposals) - 1)
        return self._proposals[index]


class TestProposeSelfPatch(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        (self.repo_root / "src" / "orchestrator").mkdir(parents=True)
        (self.repo_root / "src" / "orchestrator" / "target.py").write_text("VALUE = 1\n")
        (self.repo_root / "tests").mkdir()
        (self.repo_root / "tests" / "__init__.py").write_text("")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write_passing_test(self):
        (self.repo_root / "tests" / "test_toy.py").write_text(
            "import unittest\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_ok(self):\n"
            "        self.assertTrue(True)\n"
        )

    def _write_failing_test(self):
        (self.repo_root / "tests" / "test_toy.py").write_text(
            "import unittest\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_fails(self):\n"
            "        self.assertTrue(False)\n"
        )

    def test_usage_message_when_missing_args(self):
        store = InMemoryStore()
        message = propose_self_patch(
            FakeSelfPatchAgent([]), AuditGate(), store, ActivityLog(store), "", ""
        )

        self.assertIn("usage", message)

    def test_clean_patch_passes_full_suite_and_applies_without_relaunching(self):
        self._write_passing_test()
        store = InMemoryStore()
        proposal = ModificationProposal(
            subject="src/orchestrator/target.py", code="VALUE = 2\n", rationale="bump it"
        )
        agent = FakeSelfPatchAgent([proposal])

        message = propose_self_patch(
            agent,
            AuditGate(),
            store,
            ActivityLog(store),
            "src/orchestrator/target.py",
            "bump the value",
            repo_root=self.repo_root,
            do_relaunch=False,
        )

        self.assertIn("APPLIED", message)
        self.assertEqual(
            (self.repo_root / "src" / "orchestrator" / "target.py").read_text(), "VALUE = 2\n"
        )
        applied = store.query(kind=APPLIED_PATCH_KIND)
        self.assertEqual(len(applied), 1)

    def test_relaunch_failure_reverts_the_commit(self):
        import subprocess
        from unittest.mock import patch

        from src.orchestrator.self_patch import RelaunchResult

        subprocess.run(["git", "init", "-q"], cwd=self.repo_root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=self.repo_root, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo_root, check=True)
        self._write_passing_test()
        subprocess.run(["git", "add", "-A"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=self.repo_root, check=True)

        store = InMemoryStore()
        proposal = ModificationProposal(
            subject="src/orchestrator/target.py", code="VALUE = 2\n", rationale="bump it"
        )
        agent = FakeSelfPatchAgent([proposal])

        with patch(
            "src.main.relaunch",
            return_value=RelaunchResult(succeeded=False, detail="ImportError: boom"),
        ):
            message = propose_self_patch(
                agent,
                AuditGate(),
                store,
                ActivityLog(store),
                "src/orchestrator/target.py",
                "bump the value",
                repo_root=self.repo_root,
                do_relaunch=True,
            )

        self.assertIn("REVERTED", message)
        self.assertIn("ImportError", message)
        # The commit that applied VALUE = 2 was reverted, so the file is
        # back to VALUE = 1 in the working tree.
        self.assertEqual(
            (self.repo_root / "src" / "orchestrator" / "target.py").read_text(), "VALUE = 1\n"
        )

    def test_isolated_suite_failure_prevents_apply(self):
        self._write_failing_test()
        store = InMemoryStore()
        proposal = ModificationProposal(
            subject="src/orchestrator/target.py", code="VALUE = 2\n", rationale="bump it"
        )
        agent = FakeSelfPatchAgent([proposal])

        message = propose_self_patch(
            agent,
            AuditGate(),
            store,
            ActivityLog(store),
            "src/orchestrator/target.py",
            "bump the value",
            repo_root=self.repo_root,
            do_relaunch=False,
        )

        self.assertIn("rejected", message.lower())
        self.assertEqual(
            (self.repo_root / "src" / "orchestrator" / "target.py").read_text(), "VALUE = 1\n"
        )
        self.assertEqual(store.query(kind=APPLIED_PATCH_KIND), [])

    def test_denylisted_patch_is_rejected_before_the_suite_ever_runs(self):
        store = InMemoryStore()
        proposal = ModificationProposal(
            subject="src/orchestrator/target.py", code="eval('1')", rationale="bad"
        )
        agent = FakeSelfPatchAgent([proposal])

        message = propose_self_patch(
            agent,
            AuditGate(),
            store,
            ActivityLog(store),
            "src/orchestrator/target.py",
            "bad idea",
            repo_root=self.repo_root,
            max_attempts=1,
            do_relaunch=False,
        )

        self.assertIn("rejected", message.lower())
        self.assertIn("eval", message)

    def test_no_proposal_from_agent_means_nothing_applied(self):
        store = InMemoryStore()
        agent = FakeSelfPatchAgent([None])

        message = propose_self_patch(
            agent,
            AuditGate(),
            store,
            ActivityLog(store),
            "src/orchestrator/target.py",
            "bad idea",
            repo_root=self.repo_root,
            do_relaunch=False,
        )

        self.assertIn("no real drafting intelligence", message)
        self.assertEqual(store.query(kind=APPLIED_PATCH_KIND), [])

    def test_main_py_patch_missing_safety_wiring_is_refused_before_the_suite_runs(self):
        (self.repo_root / "src" / "main.py").write_text("print('original')\n")
        store = InMemoryStore()
        proposal = ModificationProposal(
            subject="src/main.py", code="print('stripped of safety wiring')\n", rationale="oops"
        )
        agent = FakeSelfPatchAgent([proposal])

        message = propose_self_patch(
            agent,
            AuditGate(),
            store,
            ActivityLog(store),
            "src/main.py",
            "simplify",
            repo_root=self.repo_root,
            max_attempts=1,
            do_relaunch=False,
        )

        self.assertIn("rejected", message.lower())
        self.assertIn("AuditGate(", message)
        self.assertEqual(
            (self.repo_root / "src" / "main.py").read_text(), "print('original')\n"
        )

    def test_retries_with_feedback_after_a_rejected_draft(self):
        self._write_passing_test()
        store = InMemoryStore()
        bad = ModificationProposal(
            subject="src/orchestrator/target.py", code="eval('1')", rationale="bad"
        )
        good = ModificationProposal(
            subject="src/orchestrator/target.py", code="VALUE = 2\n", rationale="good"
        )
        agent = FakeSelfPatchAgent([bad, good])

        message = propose_self_patch(
            agent,
            AuditGate(),
            store,
            ActivityLog(store),
            "src/orchestrator/target.py",
            "fix it",
            repo_root=self.repo_root,
            do_relaunch=False,
        )

        self.assertIn("APPLIED", message)
        self.assertEqual(len(agent.calls), 2)
        self.assertTrue(any("eval" in (r or "") for r in agent.calls[1][2]))


class TestUseSkill(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        self.skills_dir = self.repo_root / "src" / "agents" / "skills"
        self.skills_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_usage_message_when_no_name_given(self):
        router = build_router()
        log = OutcomeLog(InMemoryStore())

        message = use_skill(router, log, None, "", repo_root=self.repo_root)

        self.assertIn("usage", message)

    def test_not_found_message_for_unknown_skill(self):
        router = build_router()
        log = OutcomeLog(InMemoryStore())

        message = use_skill(router, log, None, "nonexistent", repo_root=self.repo_root)

        self.assertIn("not found", message)

    def test_runs_an_applied_skill_and_returns_its_output(self):
        (self.skills_dir / "greet.py").write_text("def run():\n    return 'hello from skill'\n")
        router = build_router()
        log = OutcomeLog(InMemoryStore())

        output = use_skill(router, log, None, "greet", repo_root=self.repo_root)

        self.assertIn("hello from skill", output)

    def test_picks_up_a_freshly_overwritten_skill_with_no_relaunch(self):
        target = self.skills_dir / "greet.py"
        target.write_text("def run():\n    return 'v1'\n")
        router = build_router()
        log = OutcomeLog(InMemoryStore())
        use_skill(router, log, None, "greet", repo_root=self.repo_root)

        target.write_text("def run():\n    return 'v2'\n")
        output = use_skill(router, log, None, "greet", repo_root=self.repo_root)

        self.assertIn("v2", output)

    def test_records_an_activity_log_tool_call(self):
        (self.skills_dir / "greet.py").write_text("def run():\n    return 'hi'\n")
        router = build_router()
        log = OutcomeLog(InMemoryStore())
        store = InMemoryStore()
        activity_log = ActivityLog(store)

        use_skill(router, log, activity_log, "greet", repo_root=self.repo_root)

        tool_calls = store.query(kind="tool_call")
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0].metadata["tool"], "USE")


class _FakeBrainstormCognition:
    def __init__(self, text, provider_name="fake"):
        self._text = text
        self._provider_name = provider_name
        self.prompts = []

    def complete(self, prompt, **kwargs):
        from src.cognition.provider import LLMResponse

        self.prompts.append(prompt)
        return LLMResponse(text=self._text, provider_name=self._provider_name)


class TestExtractBatchArgs(unittest.TestCase):
    def test_parses_count_and_theme(self):
        text = "batch 5 digital world skills"
        self.assertEqual(extract_batch_args(text, text.lower()), (5, "digital world skills"))

    def test_non_matching_input_returns_none(self):
        text = "hey there"
        self.assertIsNone(extract_batch_args(text, text.lower()))

    def test_missing_count_returns_usage_pair(self):
        text = "batch some theme"
        self.assertEqual(extract_batch_args(text, text.lower()), (0, ""))

    def test_missing_theme_returns_usage_pair(self):
        text = "batch 5"
        self.assertEqual(extract_batch_args(text, text.lower()), (0, ""))


class TestProposeSkillBatch(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_usage_message_for_invalid_count(self):
        store = InMemoryStore()
        message = propose_skill_batch(
            _FakeBrainstormCognition(""),
            SkillResearchAgent(),
            AuditGate(),
            store,
            "theme",
            0,
            repo_root=self.repo_root,
        )
        self.assertIn("usage", message)

    def test_usage_message_for_count_above_max(self):
        store = InMemoryStore()
        message = propose_skill_batch(
            _FakeBrainstormCognition(""),
            SkillResearchAgent(),
            AuditGate(),
            store,
            "theme",
            21,
            repo_root=self.repo_root,
        )
        self.assertIn("usage", message)

    def test_usage_message_for_empty_theme(self):
        store = InMemoryStore()
        message = propose_skill_batch(
            _FakeBrainstormCognition(""),
            SkillResearchAgent(),
            AuditGate(),
            store,
            "",
            3,
            repo_root=self.repo_root,
        )
        self.assertIn("usage", message)

    def test_deterministic_fallback_from_brainstorm_step_is_reported(self):
        store = InMemoryStore()
        cognition = _FakeBrainstormCognition("1. a\n2. b\n", provider_name="deterministic_fallback")

        message = propose_skill_batch(
            cognition, SkillResearchAgent(), AuditGate(), store, "theme", 2, repo_root=self.repo_root
        )

        self.assertIn("no real drafting intelligence", message)

    def test_unparseable_brainstorm_response_is_reported(self):
        store = InMemoryStore()
        cognition = _FakeBrainstormCognition("I refuse to make a list.")

        message = propose_skill_batch(
            cognition, SkillResearchAgent(), AuditGate(), store, "theme", 2, repo_root=self.repo_root
        )

        self.assertIn("could not produce a topic list", message)

    def test_proposes_and_applies_each_brainstormed_topic(self):
        store = InMemoryStore()
        cognition = _FakeBrainstormCognition("1. rocketry\n2. stopwatch\n")

        message = propose_skill_batch(
            cognition, SkillResearchAgent(), AuditGate(), store, "gadgets", 2, repo_root=self.repo_root
        )

        self.assertIn("2/2", message)
        self.assertTrue((self.repo_root / "src/agents/skills/rocketry.py").exists())
        self.assertTrue((self.repo_root / "src/agents/skills/stopwatch.py").exists())

    def test_brainstorm_prompt_asks_for_the_requested_count_and_theme(self):
        store = InMemoryStore()
        cognition = _FakeBrainstormCognition("1. rocketry\n")

        propose_skill_batch(
            cognition, SkillResearchAgent(), AuditGate(), store, "gadgets", 1, repo_root=self.repo_root
        )

        self.assertIn("gadgets", cognition.prompts[0])
        self.assertIn("1", cognition.prompts[0])


class TestAutocorrectCommand(unittest.TestCase):
    def test_exact_command_is_left_unchanged(self):
        text = "propose a calculator"
        corrected, corrected_lowered, original = autocorrect_command(text, text.lower())
        self.assertEqual(corrected, text)
        self.assertIsNone(original)

    def test_close_typo_is_corrected_and_announced(self):
        text = "porpose a calculator"
        corrected, corrected_lowered, original = autocorrect_command(text, text.lower())
        self.assertEqual(corrected, "propose a calculator")
        self.assertEqual(original, "porpose")

    def test_close_typo_with_no_args_is_corrected(self):
        text = "rlefect"
        corrected, corrected_lowered, original = autocorrect_command(text, text.lower())
        self.assertEqual(corrected, "reflect")
        self.assertEqual(original, "rlefect")

    def test_short_words_are_never_corrected(self):
        text = "hi there"
        corrected, corrected_lowered, original = autocorrect_command(text, text.lower())
        self.assertEqual(corrected, text)
        self.assertIsNone(original)

    def test_ordinary_chat_is_left_alone(self):
        text = "tell me about rocketry today"
        corrected, corrected_lowered, original = autocorrect_command(text, text.lower())
        self.assertEqual(corrected, text)
        self.assertIsNone(original)

    def test_empty_input_is_handled(self):
        corrected, corrected_lowered, original = autocorrect_command("", "")
        self.assertEqual(corrected, "")
        self.assertIsNone(original)


class TestExtractPlanArgs(unittest.TestCase):
    def test_parses_count_and_goal(self):
        text = "plan 4 make things more resilient"
        self.assertEqual(extract_plan_args(text, text.lower()), (4, "make things more resilient"))

    def test_non_matching_input_returns_none(self):
        text = "hey there"
        self.assertIsNone(extract_plan_args(text, text.lower()))

    def test_missing_count_returns_usage_pair(self):
        text = "plan a goal with no count"
        self.assertEqual(extract_plan_args(text, text.lower()), (0, ""))


class TestRunTask(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        self.store = InMemoryStore()
        self.task_store = TaskStore(self.store)
        self.activity_log = ActivityLog(self.store)
        self.audit_gate = AuditGate()
        self.cognition = CognitionRouter()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_skill_task_success_marks_done(self):
        task = self.task_store.add("rocketry", SKILL_TASK)

        message, needs_relaunch = run_task(
            self.task_store, task, SkillResearchAgent(), None, self.audit_gate, self.store,
            self.activity_log, self.cognition, repo_root=self.repo_root,
        )

        self.assertIn("APPLIED", message)
        self.assertFalse(needs_relaunch)
        self.assertEqual(self.task_store.get(task.id).status, DONE)

    def test_marks_in_progress_before_attempting(self):
        # A crash mid-run_task would leave the task IN_PROGRESS, which is
        # exactly what makes "on restart, resume" possible -- confirmed
        # indirectly here by checking the final state is never PENDING
        # when the pipeline actually ran (deterministic fallback always
        # succeeds for a SKILL_TASK).
        task = self.task_store.add("rocketry", SKILL_TASK)

        run_task(
            self.task_store, task, SkillResearchAgent(), None, self.audit_gate, self.store,
            self.activity_log, self.cognition, repo_root=self.repo_root,
        )

        self.assertGreaterEqual(self.task_store.get(task.id).attempts, 1)

    def test_failing_task_is_retried_then_blocked(self):
        from src.orchestrator.audit import ModificationProposal

        class AlwaysBadResearch:
            def draft_skill(self, topic, subject=None, prior_reasons=None):
                return ModificationProposal(
                    subject="src/agents/skills/bad.py", code="eval('1')", rationale="bad"
                )

        task = self.task_store.add("a bad idea", SKILL_TASK)

        for _ in range(3):
            run_task(
                self.task_store, task, AlwaysBadResearch(), None, self.audit_gate, self.store,
                self.activity_log, self.cognition, repo_root=self.repo_root,
            )
            task = self.task_store.get(task.id)

        self.assertEqual(task.status, BLOCKED)


class TestWorkOnNextTask(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        self.store = InMemoryStore()
        self.task_store = TaskStore(self.store)
        self.activity_log = ActivityLog(self.store)
        self.audit_gate = AuditGate()
        self.cognition = CognitionRouter()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_nothing_pending_reports_it(self):
        message = work_on_next_task(
            self.task_store, SkillResearchAgent(), None, self.audit_gate, self.store,
            self.activity_log, self.cognition, repo_root=self.repo_root,
        )

        self.assertIn("nothing pending", message)

    def test_works_the_next_pending_task(self):
        self.task_store.add("rocketry", SKILL_TASK)

        message = work_on_next_task(
            self.task_store, SkillResearchAgent(), None, self.audit_gate, self.store,
            self.activity_log, self.cognition, repo_root=self.repo_root,
        )

        self.assertIn("APPLIED", message)
        self.assertEqual(len(self.task_store.all()), 1)
        self.assertEqual(self.task_store.all()[0].status, DONE)

    def test_prefers_resuming_an_in_progress_task_over_a_fresh_pending_one(self):
        stale = self.task_store.add("stale in-progress task", SKILL_TASK)
        self.task_store.update_status(stale.id, "in_progress", attempt=True)
        self.task_store.add("fresh pending task", SKILL_TASK)

        work_on_next_task(
            self.task_store, SkillResearchAgent(), None, self.audit_gate, self.store,
            self.activity_log, self.cognition, repo_root=self.repo_root,
        )

        self.assertEqual(self.task_store.get(stale.id).status, DONE)
        self.assertEqual(self.task_store.get(self.task_store.all()[1].id).status, PENDING)


class TestDiscoverCommand(unittest.TestCase):
    def test_no_signals_reports_it(self):
        store = InMemoryStore()
        task_store = TaskStore(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)

        message = discover_command(task_store, reflection_agent, store)

        self.assertIn("no new improvement areas", message)

    def test_a_takeaway_is_discovered_as_a_task(self):
        from src.orchestrator.reflection import Outcome

        store = InMemoryStore()
        task_store = TaskStore(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        reflection_agent.reflect_on_outcome(
            Outcome(agent="logic", request_text="x", output="", succeeded=False, note="boom")
        )

        message = discover_command(task_store, reflection_agent, store)

        self.assertIn("1 new task", message)
        self.assertEqual(len(task_store.all()), 1)


class TestPlanGoal(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_usage_message_for_invalid_count(self):
        from src.cognition.provider import CognitionRouter

        store = InMemoryStore()
        task_store = TaskStore(store)

        message = plan_goal(CognitionRouter(), task_store, "a goal", 0)

        self.assertIn("usage", message)

    def test_usage_message_for_empty_goal(self):
        from src.cognition.provider import CognitionRouter

        store = InMemoryStore()
        task_store = TaskStore(store)

        message = plan_goal(CognitionRouter(), task_store, "", 3)

        self.assertIn("usage", message)

    def test_deterministic_fallback_is_reported(self):
        from src.cognition.provider import CognitionRouter

        store = InMemoryStore()
        task_store = TaskStore(store)

        message = plan_goal(CognitionRouter(), task_store, "a real goal", 3)

        self.assertIn("no real drafting intelligence", message)

    def test_saves_brainstormed_steps_as_pending_tasks(self):
        from src.cognition.provider import CognitionRouter, LLMResponse

        class FakeProvider:
            name = "fake"

            def available(self):
                return True

            def complete(self, prompt, **kwargs):
                return LLMResponse(text="1. step one\n2. step two\n", provider_name="fake")

        store = InMemoryStore()
        task_store = TaskStore(store)

        message = plan_goal(CognitionRouter([FakeProvider()]), task_store, "a real goal", 2)

        self.assertIn("saved 2 step", message)
        all_tasks = task_store.all()
        # 1 parent (the goal itself) + 2 sub-tasks
        self.assertEqual(len(all_tasks), 3)
        children = [t for t in all_tasks if t.parent_id is not None]
        self.assertEqual(len(children), 2)
        self.assertEqual({t.status for t in children}, {PENDING})


class TestHandleAutonomousCommand(unittest.TestCase):
    def _controller(self):
        from src.orchestrator.autonomy import ActivityClock, AutonomyController

        store = InMemoryStore()
        return AutonomyController(store, ActivityClock(), perform_action=lambda: False)

    def test_off_disables(self):
        from src.main import _handle_autonomous_command

        controller = self._controller()
        _handle_autonomous_command("off", controller)

        self.assertFalse(controller.enabled)

    def test_on_enables(self):
        from src.main import _handle_autonomous_command

        controller = self._controller()
        controller.enabled = False
        _handle_autonomous_command("on", controller)

        self.assertTrue(controller.enabled)

    def test_no_arg_prints_status_without_changing_state(self):
        import contextlib
        import io

        from src.main import _handle_autonomous_command

        controller = self._controller()

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _handle_autonomous_command("", controller)

        self.assertTrue(controller.enabled)
        self.assertIn("enabled: True", buf.getvalue())


class TestAutonomousAction(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_discovers_when_the_queue_is_empty(self):
        from src.main import _autonomous_action
        from src.orchestrator.reflection import Outcome

        store = InMemoryStore()
        task_store = TaskStore(store)
        activity_log = ActivityLog(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        reflection_agent.reflect_on_outcome(
            Outcome(agent="logic", request_text="x", output="", succeeded=False, note="boom")
        )

        did_something = _autonomous_action(
            task_store, reflection_agent, store, SkillResearchAgent(), None, AuditGate(),
            activity_log, CognitionRouter(), repo_root=self.repo_root,
        )

        self.assertTrue(did_something)
        self.assertEqual(len(task_store.all()), 1)

    def test_returns_false_when_nothing_to_discover_and_queue_empty(self):
        from src.main import _autonomous_action

        store = InMemoryStore()
        task_store = TaskStore(store)
        activity_log = ActivityLog(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)

        did_something = _autonomous_action(
            task_store, reflection_agent, store, SkillResearchAgent(), None, AuditGate(),
            activity_log, CognitionRouter(), repo_root=self.repo_root,
        )

        self.assertFalse(did_something)

    def test_works_a_pending_task_when_queue_is_not_empty(self):
        from src.main import _autonomous_action

        store = InMemoryStore()
        task_store = TaskStore(store)
        activity_log = ActivityLog(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        task_store.add("rocketry", SKILL_TASK)

        did_something = _autonomous_action(
            task_store, reflection_agent, store, SkillResearchAgent(), None, AuditGate(),
            activity_log, CognitionRouter(), repo_root=self.repo_root,
        )

        self.assertTrue(did_something)
        self.assertEqual(task_store.all()[0].status, DONE)


if __name__ == "__main__":
    unittest.main()
