import tempfile
import unittest
from pathlib import Path

from src.agents.interests import InterestTracker, NewsItem, WorldFeed
from src.agents.skills.research import SkillResearchAgent
from src.main import (
    SHELL_PREFIX,
    _run_shell_passthrough,
    autocorrect_command,
    build_router,
    discover_command,
    discover_creative_improvements,
    extract_batch_args,
    extract_evolve_args,
    extract_patch_args,
    extract_plan_args,
    extract_propose_topic,
    extract_remind_args,
    handle_turn,
    note_interest,
    plan_goal,
    propose_patch_batch,
    propose_self_patch,
    propose_skill,
    propose_skill_batch,
    remind_command,
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
from src.orchestrator.tasks import BLOCKED, DONE, FAILED, PATCH_TASK, PENDING, SKILL_TASK, TaskStore


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
            SkillResearchAgent(), AuditGate(), store, ActivityLog(store), "rocketry",
            repo_root=self.repo_root,
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
            SkillResearchAgent(), AuditGate(), store, ActivityLog(store), "rocketry",
            repo_root=self.repo_root,
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
            SkillResearchAgent(), AuditGate(), store, ActivityLog(store), "rocketry",
            repo_root=self.repo_root,
        )

        self.assertIn("APPLIED", message)
        self.assertIn("NOT committed", message)
        self.assertTrue((self.repo_root / "src/agents/skills/rocketry.py").exists())

    def test_empty_topic_is_rejected_with_usage_message(self):
        store = InMemoryStore()
        message = propose_skill(
            SkillResearchAgent(), AuditGate(), store, ActivityLog(store), "",
            repo_root=self.repo_root,
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

        activity_log = ActivityLog(store)
        message = propose_skill(
            research, AuditGate(), store, activity_log, "flaky", repo_root=self.repo_root
        )

        self.assertIn("APPLIED", message)
        self.assertEqual(len(research.calls), 2)
        self.assertIsNone(research.calls[0])
        self.assertTrue(any("eval" in r for r in research.calls[1]))

        # Same recording as propose_self_patch: the rejected first
        # attempt's reason survives past the live terminal.
        drafts = [r for r in store.query(kind="tool_call") if r.metadata["tool"] == "DRAFT"]
        self.assertEqual(len(drafts), 2)
        self.assertTrue(drafts[0].metadata["succeeded"])
        self.assertFalse(drafts[1].metadata["succeeded"])
        self.assertIn("eval", drafts[1].metadata["result_summary"])

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
            research, AuditGate(), store, ActivityLog(store), "bad",
            repo_root=self.repo_root, max_attempts=2,
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


class _StubFeed(WorldFeed):
    def __init__(self, items):
        self._items = items

    def fetch(self, topic, limit=5):
        return self._items[:limit]


class TestNewsCommand(unittest.TestCase):
    def test_reports_nothing_when_no_interests_are_tracked(self):
        from src.main import news_command
        from src.orchestrator.socializing import NewsSocializer

        tracker = InterestTracker(InMemoryStore())

        message = news_command(tracker, NewsSocializer(), CognitionRouter())

        self.assertIn("nothing new", message)

    def test_shares_the_next_item_bypassing_the_pacing_cooldown(self):
        from src.main import news_command
        from src.orchestrator.socializing import NewsSocializer

        store = InMemoryStore()
        items = [NewsItem(title="t1", summary="s1", source="src", published_at=0.0)]
        tracker = InterestTracker(store, feed=_StubFeed(items))
        tracker.note_interest("https://example.com/feed", "seeded")
        # A fresh NewsSocializer is always ready anyway, but a long
        # cooldown here proves 'news' bypasses it (share_next, not
        # maybe_share) rather than happening to be ready by accident.
        socializer = NewsSocializer(cooldown_seconds=3600.0)

        message = news_command(tracker, socializer, CognitionRouter())

        self.assertIn("t1", message)
        self.assertFalse(socializer.ready())


class TestGrowthCommand(unittest.TestCase):
    def test_reports_nothing_when_nothing_has_been_applied(self):
        from src.main import growth_command
        from src.orchestrator.socializing import GrowthSocializer

        message = growth_command(GrowthSocializer(InMemoryStore()), CognitionRouter())

        self.assertIn("nothing applied", message)

    def test_shares_the_most_recent_change_bypassing_the_pacing_cooldown(self):
        from src.main import growth_command
        from src.orchestrator.socializing import GrowthSocializer

        store = InMemoryStore()
        store.remember(APPLIED_KIND, "src/agents/skills/rocketry.py", rationale="fun")
        # A fresh GrowthSocializer is always ready anyway, but a long
        # cooldown here proves 'growth' bypasses it (share_next, not
        # maybe_share) rather than happening to be ready by accident.
        socializer = GrowthSocializer(store, cooldown_seconds=3600.0)

        message = growth_command(socializer, CognitionRouter())

        self.assertIn("rocketry.py", message)
        self.assertFalse(socializer.ready())


class TestBuildRouterConversationalSelfMod(unittest.TestCase):
    def test_propose_fn_is_threaded_through_to_logic_agent(self):
        from src.cognition.provider import LLMResponse
        from src.orchestrator.router import AgentRequest

        class ScriptedProvider:
            name = "scripted"

            def __init__(self, responses):
                self._responses = responses
                self.calls = 0

            def available(self):
                return True

            def complete(self, prompt, **kwargs):
                text = self._responses[min(self.calls, len(self._responses) - 1)]
                self.calls += 1
                return LLMResponse(text=text, provider_name=self.name)

        calls = []
        provider = ScriptedProvider(["PROPOSE: rocketry", "done"])
        router = build_router(
            cognition=CognitionRouter([provider]),
            propose_skill_fn=lambda topic: calls.append(topic) or "[APPLIED] ok",
        )

        router.dispatch("logic", AgentRequest(text="add a rocketry skill"))

        self.assertEqual(calls, ["rocketry"])

    def test_use_skill_fn_is_threaded_through_to_logic_agent(self):
        from src.cognition.provider import LLMResponse
        from src.orchestrator.router import AgentRequest

        class ScriptedProvider:
            name = "scripted"

            def __init__(self, responses):
                self._responses = responses
                self.calls = 0

            def available(self):
                return True

            def complete(self, prompt, **kwargs):
                text = self._responses[min(self.calls, len(self._responses) - 1)]
                self.calls += 1
                return LLMResponse(text=text, provider_name=self.name)

        calls = []
        provider = ScriptedProvider(["USE: rocketry", "done"])
        router = build_router(
            cognition=CognitionRouter([provider]),
            use_skill_fn=lambda name: calls.append(name) or "computed: 42",
        )

        router.dispatch("logic", AgentRequest(text="run the rocketry skill"))

        self.assertEqual(calls, ["rocketry"])

    def test_news_fn_is_threaded_through_to_logic_agent(self):
        from src.cognition.provider import LLMResponse
        from src.orchestrator.router import AgentRequest

        class ScriptedProvider:
            name = "scripted"

            def __init__(self, responses):
                self._responses = responses
                self.calls = 0

            def available(self):
                return True

            def complete(self, prompt, **kwargs):
                text = self._responses[min(self.calls, len(self._responses) - 1)]
                self.calls += 1
                return LLMResponse(text=text, provider_name=self.name)

        calls = []
        provider = ScriptedProvider(["NEWS:", "done"])
        router = build_router(
            cognition=CognitionRouter([provider]),
            news_fn=lambda: calls.append(1) or "[news] something interesting",
        )

        router.dispatch("logic", AgentRequest(text="check the news"))

        self.assertEqual(calls, [1])

    def test_growth_fn_is_threaded_through_to_logic_agent(self):
        from src.cognition.provider import LLMResponse
        from src.orchestrator.router import AgentRequest

        class ScriptedProvider:
            name = "scripted"

            def __init__(self, responses):
                self._responses = responses
                self.calls = 0

            def available(self):
                return True

            def complete(self, prompt, **kwargs):
                text = self._responses[min(self.calls, len(self._responses) - 1)]
                self.calls += 1
                return LLMResponse(text=text, provider_name=self.name)

        calls = []
        provider = ScriptedProvider(["GROWTH:", "done"])
        router = build_router(
            cognition=CognitionRouter([provider]),
            growth_fn=lambda: calls.append(1) or "[growth] I just fixed my own tone",
        )

        router.dispatch("logic", AgentRequest(text="what have you improved lately?"))

        self.assertEqual(calls, [1])


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


class TestShellPassthrough(unittest.TestCase):
    def test_runs_command_and_reports_no_error_on_success(self):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _run_shell_passthrough("exit 0")
        self.assertNotIn("exit", buf.getvalue())

    def test_nonzero_exit_is_reported(self):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _run_shell_passthrough("exit 7")
        self.assertIn("exit 7", buf.getvalue())

    def test_empty_command_prints_usage_without_spawning_a_shell(self):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _run_shell_passthrough("")
        self.assertIn("usage", buf.getvalue())

    def test_timeout_is_reported_not_raised(self):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _run_shell_passthrough("sleep 5", timeout=0.05)
        self.assertIn("timed out", buf.getvalue())

    def test_prefix_constant_is_a_single_bang(self):
        self.assertEqual(SHELL_PREFIX, "!")


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
    """`proposals` is a list of either `ModificationProposal` (success)
    or `None` (mapped to a "deterministic_fallback" reason, matching the
    real SelfPatchAgent.draft_patch's own tuple return shape) -- or, for
    tests that need a specific retryable failure reason, a 2-tuple
    `(None, reason)` passed through as-is.
    """

    def __init__(self, proposals):
        self._proposals = proposals
        self.calls = []

    def draft_patch(self, subject, topic, prior_reasons=None):
        self.calls.append((subject, topic, prior_reasons))
        index = min(len(self.calls) - 1, len(self._proposals) - 1)
        proposal = self._proposals[index]
        if isinstance(proposal, tuple):
            return proposal
        return (proposal, None) if proposal is not None else (None, "deterministic_fallback")


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

    def test_subject_outside_src_is_rejected_without_calling_the_drafting_agent(self):
        # Live bug report: 'patch docs/EVOLUTION.md ...' burned a real
        # drafting attempt and failed with a misleading "no real
        # drafting intelligence available" -- self-patch has always
        # been scoped to src/ only (apply.py's SELF_PATCH_SCOPE_PREFIX;
        # docs/ is deliberately out of scope, a self-patch changes
        # Simorgh's own logic, not its docs). This should be caught
        # instantly, honestly, and for free -- before ever asking the
        # agent to draft anything.
        store = InMemoryStore()
        agent = FakeSelfPatchAgent([])

        message = propose_self_patch(
            agent, AuditGate(), store, ActivityLog(store), "docs/EVOLUTION.md", "add milestones"
        )

        self.assertIn("rejected", message.lower())
        self.assertIn("scope", message.lower())
        self.assertEqual(agent.calls, [])

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

    def test_relaunch_saves_short_term_context_first(self):
        import subprocess
        from unittest.mock import patch

        from src.memory.short_term import ShortTermMemory
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
        short_term = ShortTermMemory()
        short_term.add("what should we build next", "let's evolve the patch pipeline")
        context_path = self.repo_root / "relaunch_context.json"

        with patch("src.main.DEFAULT_RELAUNCH_CONTEXT_PATH", context_path), patch(
            "src.main.relaunch",
            return_value=RelaunchResult(succeeded=True, detail=""),
        ):
            propose_self_patch(
                agent,
                AuditGate(),
                store,
                ActivityLog(store),
                "src/orchestrator/target.py",
                "bump the value",
                repo_root=self.repo_root,
                do_relaunch=True,
                short_term=short_term,
            )

        restored = ShortTermMemory.load_and_clear(context_path)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.recent()[0].request_text, "what should we build next")

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

    def test_a_refused_target_stops_immediately_without_retrying(self):
        # A "refused: ..." reason (out-of-scope/too-large target) is a
        # problem with the FILE, not the draft -- retrying can't help,
        # unlike an invalid-Python draft.
        store = InMemoryStore()
        agent = FakeSelfPatchAgent([(None, "refused: 'x' is not a file")])

        message = propose_self_patch(
            agent,
            AuditGate(),
            store,
            ActivityLog(store),
            "src/orchestrator/target.py",
            "bad idea",
            repo_root=self.repo_root,
            max_attempts=3,
            do_relaunch=False,
        )

        self.assertIn("rejected", message.lower())
        self.assertIn("not a file", message)
        self.assertEqual(len(agent.calls), 1)  # never retried

    def test_invalid_python_draft_is_retried_with_feedback_not_abandoned(self):
        # Direct fix for a live-caught bug: a real provider answering
        # with invalid Python used to abandon the whole attempt on the
        # very first try, even though max_attempts existed for exactly
        # this kind of recoverable failure (same as an audit rejection).
        self._write_passing_test()
        store = InMemoryStore()
        good = ModificationProposal(
            subject="src/orchestrator/target.py", code="VALUE = 2\n", rationale="good"
        )
        agent = FakeSelfPatchAgent([(None, "'fake' answered but its response wasn't Python"), good])

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
        self.assertTrue(any("wasn't Python" in (r or "") for r in agent.calls[1][2]))

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
        activity_log = ActivityLog(store)

        message = propose_self_patch(
            agent,
            AuditGate(),
            store,
            activity_log,
            "src/orchestrator/target.py",
            "fix it",
            repo_root=self.repo_root,
            do_relaunch=False,
        )

        self.assertIn("APPLIED", message)
        self.assertEqual(len(agent.calls), 2)
        self.assertTrue(any("eval" in (r or "") for r in agent.calls[1][2]))

        # The rejected first attempt's specific reason must be recorded,
        # not just live-printed and lost -- see propose_self_patch's
        # docstring on why this matters when nobody's watching live.
        # query() returns most-recent-first, so [0] is the 2nd (winning)
        # attempt and [1] is the 1st (rejected) one; TEST_SUITE's own
        # tool_call record (already existed) is excluded by tool="DRAFT".
        drafts = [r for r in store.query(kind="tool_call") if r.metadata["tool"] == "DRAFT"]
        self.assertEqual(len(drafts), 2)
        self.assertTrue(drafts[0].metadata["succeeded"])
        self.assertFalse(drafts[1].metadata["succeeded"])
        self.assertIn("eval", drafts[1].metadata["result_summary"])


class TestAttemptHotSwap(unittest.TestCase):
    """Unit-level tests for _attempt_hot_swap in isolation, with
    `reload_class` injected so these never depend on a real file on disk
    or mutate real sys.modules entries -- that side of the mechanism
    (the real _reload_hot_swap_class default) is exercised separately in
    TestSelfPatchHotSwap below, against the real LogicAgent.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=self.repo_root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=self.repo_root, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo_root, check=True)
        (self.repo_root / "f.txt").write_text("v1")
        subprocess.run(["git", "add", "-A"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=self.repo_root, check=True)
        (self.repo_root / "f.txt").write_text("v2")
        subprocess.run(["git", "add", "-A"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "the patch commit"], cwd=self.repo_root, check=True)
        self.target = self.repo_root / "f.txt"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_subject_not_in_registry_falls_through(self):
        from src.main import _attempt_hot_swap
        from src.orchestrator.deployment import DeploymentManager
        from src.orchestrator.router import Router

        manager = DeploymentManager(Router())

        attempted, message = _attempt_hot_swap(
            manager, {}, "src/main.py", self.repo_root, self.target
        )

        self.assertFalse(attempted)
        self.assertIsNone(message)

    def test_missing_factory_for_an_eligible_subject_falls_through(self):
        from src.main import _attempt_hot_swap
        from src.orchestrator.deployment import DeploymentManager
        from src.orchestrator.router import Router

        manager = DeploymentManager(Router())

        attempted, message = _attempt_hot_swap(
            manager, {}, "src/agents/logic/base.py", self.repo_root, self.target
        )

        self.assertFalse(attempted)

    def test_reload_failure_falls_through_to_relaunch(self):
        from src.main import _attempt_hot_swap
        from src.orchestrator.deployment import DeploymentManager
        from src.orchestrator.router import Router

        manager = DeploymentManager(Router())

        attempted, message = _attempt_hot_swap(
            manager,
            {"src/agents/logic/base.py": lambda cls: cls()},
            "src/agents/logic/base.py",
            self.repo_root,
            self.target,
            reload_class=lambda module_name, class_name: None,
        )

        self.assertFalse(attempted)
        self.assertIsNone(message)

    def test_candidate_construction_failure_falls_through(self):
        from src.main import _attempt_hot_swap
        from src.orchestrator.deployment import DeploymentManager
        from src.orchestrator.router import Router, SubAgent

        class FakeClass(SubAgent):
            name = "logic"

            def handle(self, request, bus):
                raise NotImplementedError

        def broken_factory(cls):
            raise RuntimeError("cannot build it")

        manager = DeploymentManager(Router())

        attempted, message = _attempt_hot_swap(
            manager,
            {"src/agents/logic/base.py": broken_factory},
            "src/agents/logic/base.py",
            self.repo_root,
            self.target,
            reload_class=lambda module_name, class_name: FakeClass,
        )

        self.assertFalse(attempted)

    def test_no_active_version_for_the_slot_falls_through(self):
        from src.main import _attempt_hot_swap
        from src.orchestrator.deployment import DeploymentManager
        from src.orchestrator.router import Router, SubAgent

        class FakeClass(SubAgent):
            name = "logic"

            def handle(self, request, bus):
                from src.orchestrator.router import AgentResponse

                return AgentResponse(agent=self.name, output="ok")

        manager = DeploymentManager(Router())  # nothing deployed for "logic" yet

        attempted, message = _attempt_hot_swap(
            manager,
            {"src/agents/logic/base.py": lambda cls: cls()},
            "src/agents/logic/base.py",
            self.repo_root,
            self.target,
            reload_class=lambda module_name, class_name: FakeClass,
        )

        self.assertFalse(attempted)

    def test_a_working_candidate_is_promoted_without_reverting(self):
        from src.main import _attempt_hot_swap
        from src.orchestrator.deployment import DeploymentManager
        from src.orchestrator.router import AgentResponse, Router, SubAgent

        class BaselineAgent(SubAgent):
            name = "logic"

            def handle(self, request, bus):
                return AgentResponse(agent=self.name, output="baseline")

        class GoodCandidate(SubAgent):
            name = "logic"

            def handle(self, request, bus):
                return AgentResponse(agent=self.name, output="candidate")

        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(BaselineAgent())

        attempted, message = _attempt_hot_swap(
            manager,
            {"src/agents/logic/base.py": lambda cls: cls()},
            "src/agents/logic/base.py",
            self.repo_root,
            self.target,
            reload_class=lambda module_name, class_name: GoodCandidate,
        )

        self.assertTrue(attempted)
        self.assertIsNotNone(message)
        self.assertIn("APPLIED", message)
        self.assertIn("hot-swapped", message)
        # promoted live -- dispatch now reaches the candidate
        from src.orchestrator.router import AgentRequest

        self.assertEqual(router.dispatch("logic", AgentRequest(text="hi")).output, "candidate")
        # the git commit was NOT reverted
        self.assertEqual(self.target.read_text(), "v2")

    def test_a_crashing_candidate_is_reverted_and_reported(self):
        from src.main import _attempt_hot_swap
        from src.orchestrator.deployment import DeploymentManager
        from src.orchestrator.router import AgentResponse, Router, SubAgent

        class BaselineAgent(SubAgent):
            name = "logic"

            def handle(self, request, bus):
                return AgentResponse(agent=self.name, output="baseline")

        class CrashingCandidate(SubAgent):
            name = "logic"

            def handle(self, request, bus):
                raise RuntimeError("boom")

        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(BaselineAgent())

        attempted, message = _attempt_hot_swap(
            manager,
            {"src/agents/logic/base.py": lambda cls: cls()},
            "src/agents/logic/base.py",
            self.repo_root,
            self.target,
            reload_class=lambda module_name, class_name: CrashingCandidate,
        )

        self.assertTrue(attempted)
        self.assertIsNotNone(message)
        self.assertIn("REVERTED", message)
        self.assertIn("hot-swap", message)
        # not promoted -- dispatch still reaches the original baseline
        from src.orchestrator.router import AgentRequest

        self.assertEqual(router.dispatch("logic", AgentRequest(text="hi")).output, "baseline")
        # the git commit WAS reverted
        self.assertEqual(self.target.read_text(), "v1")


class TestSelfPatchHotSwap(unittest.TestCase):
    """propose_self_patch's own wiring: does it actually call
    _attempt_hot_swap (and skip relaunch()) when a subject is
    hot-swap-eligible and deployment_manager/hot_swap_factories are
    given? Uses the REAL LogicAgent class via the real, uninjected
    reload path -- src.agents.logic.base is a real module in this
    process, so importlib.reload genuinely reloads it; the patched
    *content* written to the isolated repo_root here is irrelevant to
    that reload (it reloads the real in-process module, not the copy on
    disk in repo_root) -- which is the accurate real-world behavior this
    is meant to lock in, not a limitation of the test.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        (self.repo_root / "src" / "agents" / "logic").mkdir(parents=True)
        (self.repo_root / "src" / "agents" / "logic" / "base.py").write_text("X = 1\n")
        (self.repo_root / "tests").mkdir()
        (self.repo_root / "tests" / "__init__.py").write_text("")
        (self.repo_root / "tests" / "test_toy.py").write_text(
            "import unittest\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_ok(self):\n"
            "        self.assertTrue(True)\n"
        )
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=self.repo_root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=self.repo_root, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=self.repo_root, check=True)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_hot_swap_success_skips_relaunch_entirely(self):
        from unittest.mock import patch

        from src.orchestrator.deployment import DeploymentManager
        from src.orchestrator.router import Router

        from src.agents.logic.base import LogicAgent

        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(LogicAgent())

        proposal = ModificationProposal(
            subject="src/agents/logic/base.py", code="X = 2\n", rationale="tweak"
        )
        agent = FakeSelfPatchAgent([proposal])

        with patch("src.main.relaunch") as mock_relaunch:
            message = propose_self_patch(
                agent,
                AuditGate(),
                InMemoryStore(),
                ActivityLog(InMemoryStore()),
                "src/agents/logic/base.py",
                "tweak it",
                repo_root=self.repo_root,
                do_relaunch=True,
                deployment_manager=manager,
                hot_swap_factories={"src/agents/logic/base.py": lambda cls: cls()},
            )

        mock_relaunch.assert_not_called()
        self.assertIn("APPLIED", message)
        self.assertNotIn("REVERTED", message)

    def test_subject_outside_the_registry_still_relaunches_as_before(self):
        from unittest.mock import patch

        from src.orchestrator.deployment import DeploymentManager
        from src.orchestrator.router import Router
        from src.orchestrator.self_patch import RelaunchResult

        (self.repo_root / "src" / "orchestrator").mkdir(parents=True)
        (self.repo_root / "src" / "orchestrator" / "target.py").write_text("VALUE = 1\n")
        import subprocess

        subprocess.run(["git", "add", "-A"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "add target"], cwd=self.repo_root, check=True)

        proposal = ModificationProposal(
            subject="src/orchestrator/target.py", code="VALUE = 2\n", rationale="tweak"
        )
        agent = FakeSelfPatchAgent([proposal])
        manager = DeploymentManager(Router())

        with patch(
            "src.main.relaunch", return_value=RelaunchResult(succeeded=True, detail="")
        ) as mock_relaunch:
            propose_self_patch(
                agent,
                AuditGate(),
                InMemoryStore(),
                ActivityLog(InMemoryStore()),
                "src/orchestrator/target.py",
                "tweak it",
                repo_root=self.repo_root,
                do_relaunch=True,
                deployment_manager=manager,
                hot_swap_factories={"src/agents/logic/base.py": lambda cls: cls()},
            )

        mock_relaunch.assert_called_once()


class TestProposePatchBatch(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        (self.repo_root / "src" / "orchestrator").mkdir(parents=True)
        (self.repo_root / "src" / "orchestrator" / "a.py").write_text("A = 1\n")
        (self.repo_root / "src" / "orchestrator" / "b.py").write_text("B = 1\n")
        (self.repo_root / "tests").mkdir()
        (self.repo_root / "tests" / "__init__.py").write_text("")
        (self.repo_root / "tests" / "test_toy.py").write_text(
            "import unittest\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_ok(self):\n"
            "        self.assertTrue(True)\n"
        )

    def tearDown(self):
        self._tmpdir.cleanup()

    def _init_git_repo(self):
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=self.repo_root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=self.repo_root, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=self.repo_root, check=True)

    def test_usage_message_for_invalid_count(self):
        store = InMemoryStore()
        message = propose_patch_batch(
            _FakeBrainstormCognition(""), FakeSelfPatchAgent([]), AuditGate(), store,
            ActivityLog(store), "goal", 0, repo_root=self.repo_root,
        )
        self.assertIn("usage", message)

    def test_usage_message_for_count_above_max(self):
        store = InMemoryStore()
        message = propose_patch_batch(
            _FakeBrainstormCognition(""), FakeSelfPatchAgent([]), AuditGate(), store,
            ActivityLog(store), "goal", 11, repo_root=self.repo_root,
        )
        self.assertIn("usage", message)

    def test_deterministic_fallback_from_brainstorm_step_is_reported(self):
        store = InMemoryStore()
        cognition = _FakeBrainstormCognition("1. src/a.py :: fix it", provider_name="deterministic_fallback")
        message = propose_patch_batch(
            cognition, FakeSelfPatchAgent([]), AuditGate(), store, ActivityLog(store),
            "goal", 1, repo_root=self.repo_root,
        )
        self.assertIn("no real drafting intelligence", message)

    def test_unparseable_brainstorm_response_is_reported(self):
        store = InMemoryStore()
        cognition = _FakeBrainstormCognition("I refuse to make a list.")
        message = propose_patch_batch(
            cognition, FakeSelfPatchAgent([]), AuditGate(), store, ActivityLog(store),
            "goal", 1, repo_root=self.repo_root,
        )
        self.assertIn("could not produce real file targets", message)

    def test_applies_each_brainstormed_target_without_relaunching(self):
        store = InMemoryStore()
        cognition = _FakeBrainstormCognition(
            "1. src/orchestrator/a.py :: bump a\n2. src/orchestrator/b.py :: bump b\n"
        )
        agent = FakeSelfPatchAgent(
            [
                ModificationProposal(subject="src/orchestrator/a.py", code="A = 2\n", rationale="bump a"),
                ModificationProposal(subject="src/orchestrator/b.py", code="B = 2\n", rationale="bump b"),
            ]
        )

        message = propose_patch_batch(
            cognition, agent, AuditGate(), store, ActivityLog(store), "goal", 2,
            repo_root=self.repo_root, do_relaunch=False,
        )

        self.assertIn("2/2", message)
        self.assertEqual((self.repo_root / "src/orchestrator/a.py").read_text(), "A = 2\n")
        self.assertEqual((self.repo_root / "src/orchestrator/b.py").read_text(), "B = 2\n")

    def test_commits_each_target_separately_against_a_real_git_repo(self):
        self._init_git_repo()
        store = InMemoryStore()
        cognition = _FakeBrainstormCognition(
            "1. src/orchestrator/a.py :: bump a\n2. src/orchestrator/b.py :: bump b\n"
        )
        agent = FakeSelfPatchAgent(
            [
                ModificationProposal(subject="src/orchestrator/a.py", code="A = 2\n", rationale="bump a"),
                ModificationProposal(subject="src/orchestrator/b.py", code="B = 2\n", rationale="bump b"),
            ]
        )

        propose_patch_batch(
            cognition, agent, AuditGate(), store, ActivityLog(store), "goal", 2,
            repo_root=self.repo_root, do_relaunch=False,
        )

        import subprocess

        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=self.repo_root, capture_output=True, text=True
        )
        self.assertEqual(len(log.stdout.strip().splitlines()), 3)  # initial + 2 patches

    def test_relaunch_failure_reverts_every_commit_from_the_batch(self):
        from unittest.mock import patch

        from src.orchestrator.self_patch import RelaunchResult

        self._init_git_repo()
        store = InMemoryStore()
        cognition = _FakeBrainstormCognition(
            "1. src/orchestrator/a.py :: bump a\n2. src/orchestrator/b.py :: bump b\n"
        )
        agent = FakeSelfPatchAgent(
            [
                ModificationProposal(subject="src/orchestrator/a.py", code="A = 2\n", rationale="bump a"),
                ModificationProposal(subject="src/orchestrator/b.py", code="B = 2\n", rationale="bump b"),
            ]
        )

        with patch(
            "src.main.relaunch",
            return_value=RelaunchResult(succeeded=False, detail="ImportError: boom"),
        ):
            message = propose_patch_batch(
                cognition, agent, AuditGate(), store, ActivityLog(store), "goal", 2,
                repo_root=self.repo_root, do_relaunch=True,
            )

        self.assertIn("REVERTED", message)
        self.assertEqual((self.repo_root / "src/orchestrator/a.py").read_text(), "A = 1\n")
        self.assertEqual((self.repo_root / "src/orchestrator/b.py").read_text(), "B = 1\n")


class TestPrintPending(unittest.TestCase):
    def test_empty_store_reports_nothing_applied(self):
        import contextlib
        import io

        from src.main import _print_pending

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_pending(InMemoryStore())

        self.assertIn("nothing applied yet", buf.getvalue())

    def test_bare_pending_lists_paths_and_rationale(self):
        import contextlib
        import io

        from src.main import _print_pending

        store = InMemoryStore()
        store.remember(APPLIED_KIND, "src/agents/skills/rocketry.py", code="X = 1", rationale="fun")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_pending(store)

        output = buf.getvalue()
        self.assertIn("src/agents/skills/rocketry.py", output)
        self.assertIn("fun", output)

    def test_pending_with_subject_shows_the_full_code(self):
        import contextlib
        import io

        from src.main import _print_pending

        store = InMemoryStore()
        store.remember(
            APPLIED_KIND, "src/agents/skills/rocketry.py", code="def run():\n    return 42\n",
            rationale="fun",
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_pending(store, "src/agents/skills/rocketry.py")

        output = buf.getvalue()
        self.assertIn("def run():", output)
        self.assertIn("return 42", output)

    def test_pending_with_a_prior_version_shows_a_diff(self):
        import contextlib
        import io

        from src.main import _print_pending

        store = InMemoryStore()
        store.remember(APPLIED_KIND, "src/agents/skills/rocketry.py", code="OLD = 1", rationale="v1")
        store.remember(APPLIED_KIND, "src/agents/skills/rocketry.py", code="NEW = 2", rationale="v2")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_pending(store, "src/agents/skills/rocketry.py")

        output = buf.getvalue()
        self.assertIn("+NEW = 2", output)
        self.assertIn("-OLD = 1", output)
        self.assertIn("diff vs previous version", output)
        self.assertIn("--full", output)

    def test_pending_with_full_flag_shows_the_whole_current_file(self):
        import contextlib
        import io

        from src.main import _print_pending

        store = InMemoryStore()
        store.remember(APPLIED_KIND, "src/agents/skills/rocketry.py", code="OLD = 1", rationale="v1")
        store.remember(APPLIED_KIND, "src/agents/skills/rocketry.py", code="NEW = 2", rationale="v2")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_pending(store, "src/agents/skills/rocketry.py --full")

        output = buf.getvalue()
        self.assertIn("NEW = 2", output)
        self.assertNotIn("diff vs previous version", output)

    def test_pending_with_only_one_version_shows_the_full_file_not_a_diff(self):
        import contextlib
        import io

        from src.main import _print_pending

        store = InMemoryStore()
        store.remember(APPLIED_KIND, "src/agents/skills/rocketry.py", code="X = 1", rationale="v1")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_pending(store, "src/agents/skills/rocketry.py")

        output = buf.getvalue()
        self.assertIn("X = 1", output)
        self.assertNotIn("diff vs previous version", output)

    def test_pending_with_unknown_subject_reports_not_found(self):
        import contextlib
        import io

        from src.main import _print_pending

        store = InMemoryStore()
        store.remember(APPLIED_KIND, "src/agents/skills/rocketry.py", code="X = 1", rationale="fun")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_pending(store, "src/agents/skills/nope.py")

        self.assertIn("not found", buf.getvalue())

    def test_pending_with_subject_includes_test_summary_for_patches(self):
        import contextlib
        import io

        from src.main import _print_pending

        store = InMemoryStore()
        store.remember(
            APPLIED_PATCH_KIND,
            "src/main.py",
            code="X = 1",
            rationale="fix",
            test_summary="patched: 42 tests (OK)",
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_pending(store, "src/main.py")

        self.assertIn("patched: 42 tests", buf.getvalue())


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
            ActivityLog(store),
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
            ActivityLog(store),
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
            ActivityLog(store),
            "",
            3,
            repo_root=self.repo_root,
        )
        self.assertIn("usage", message)

    def test_deterministic_fallback_from_brainstorm_step_is_reported(self):
        store = InMemoryStore()
        cognition = _FakeBrainstormCognition("1. a\n2. b\n", provider_name="deterministic_fallback")

        message = propose_skill_batch(
            cognition, SkillResearchAgent(), AuditGate(), store, ActivityLog(store), "theme", 2,
            repo_root=self.repo_root,
        )

        self.assertIn("no real drafting intelligence", message)

    def test_unparseable_brainstorm_response_is_reported(self):
        store = InMemoryStore()
        cognition = _FakeBrainstormCognition("I refuse to make a list.")

        message = propose_skill_batch(
            cognition, SkillResearchAgent(), AuditGate(), store, ActivityLog(store), "theme", 2,
            repo_root=self.repo_root,
        )

        self.assertIn("could not produce a topic list", message)

    def test_proposes_and_applies_each_brainstormed_topic(self):
        store = InMemoryStore()
        cognition = _FakeBrainstormCognition("1. rocketry\n2. stopwatch\n")

        message = propose_skill_batch(
            cognition, SkillResearchAgent(), AuditGate(), store, ActivityLog(store), "gadgets", 2,
            repo_root=self.repo_root,
        )

        self.assertIn("2/2", message)
        self.assertTrue((self.repo_root / "src/agents/skills/rocketry.py").exists())
        self.assertTrue((self.repo_root / "src/agents/skills/stopwatch.py").exists())

    def test_brainstorm_prompt_asks_for_the_requested_count_and_theme(self):
        store = InMemoryStore()
        cognition = _FakeBrainstormCognition("1. rocketry\n")

        propose_skill_batch(
            cognition, SkillResearchAgent(), AuditGate(), store, ActivityLog(store), "gadgets", 1,
            repo_root=self.repo_root,
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


class TestExtractEvolveArgs(unittest.TestCase):
    def test_parses_count_and_goal(self):
        text = "evolve 5 improve resilience"
        self.assertEqual(extract_evolve_args(text, text.lower()), (5, "improve resilience"))

    def test_non_matching_input_returns_none(self):
        text = "hey there"
        self.assertIsNone(extract_evolve_args(text, text.lower()))

    def test_missing_count_returns_usage_pair(self):
        text = "evolve a goal with no count"
        self.assertEqual(extract_evolve_args(text, text.lower()), (0, ""))


class TestExtractRemindArgs(unittest.TestCase):
    def test_parses_duration_and_message(self):
        text = "remind 1m wake up"
        self.assertEqual(extract_remind_args(text, text.lower()), ("1m", "wake up"))

    def test_non_matching_input_returns_none(self):
        text = "hey there"
        self.assertIsNone(extract_remind_args(text, text.lower()))

    def test_missing_message_falls_through_to_none(self):
        text = "remind 1m"
        self.assertIsNone(extract_remind_args(text, text.lower()))

    def test_plain_chat_starting_with_remind_is_not_intercepted(self):
        # The live-caught bug: this used to parse as duration="me".
        text = "remind me to wake up in one minute"
        self.assertIsNone(extract_remind_args(text, text.lower()))

    def test_natural_phrasing_with_a_real_duration_word_still_falls_through(self):
        # "in" isn't a valid duration token, so this is still ordinary
        # chat, not the explicit command -- exactly the ambiguity this
        # heuristic accepts as a tradeoff for never hijacking real chat.
        text = "remind in five minutes to check the oven"
        self.assertIsNone(extract_remind_args(text, text.lower()))

    def test_explicit_command_shaped_input_is_still_recognized(self):
        text = "remind 1m wake up"
        self.assertEqual(extract_remind_args(text, text.lower()), ("1m", "wake up"))


class TestRemindCommand(unittest.TestCase):
    def test_usage_message_when_missing_args(self):
        message = remind_command("", "")
        self.assertIn("usage", message)

    def test_invalid_duration_reports_it(self):
        message = remind_command("not-a-duration", "wake up")
        self.assertIn("isn't a valid duration", message)

    def test_valid_duration_schedules_and_reports_it(self):
        message = remind_command("1m", "wake up")
        self.assertIn("scheduled", message)
        self.assertIn("wake up", message)


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

    def test_reconsiders_a_blocked_task_when_nothing_else_is_pending(self):
        task = self.task_store.add("rocketry", SKILL_TASK)
        self.task_store.update_status(task.id, BLOCKED, note="denied: eval", attempt=True)

        message = work_on_next_task(
            self.task_store, SkillResearchAgent(), None, self.audit_gate, self.store,
            self.activity_log, self.cognition, repo_root=self.repo_root,
        )

        # A blocked task is reset to PENDING and then actually worked in
        # the same call -- deterministic-fallback drafting always
        # succeeds for a plain SKILL_TASK, so this ends DONE, not stuck.
        self.assertIn("APPLIED", message)
        self.assertEqual(self.task_store.get(task.id).status, DONE)

    def test_fresh_pending_work_takes_priority_over_a_blocked_task(self):
        blocked = self.task_store.add("blocked one", SKILL_TASK)
        self.task_store.update_status(blocked.id, BLOCKED, note="denied", attempt=True)
        self.task_store.add("fresh one", SKILL_TASK)

        work_on_next_task(
            self.task_store, SkillResearchAgent(), None, self.audit_gate, self.store,
            self.activity_log, self.cognition, repo_root=self.repo_root,
        )

        self.assertEqual(self.task_store.get(blocked.id).status, BLOCKED)


class TestWorkOnNextTaskHotSwap(unittest.TestCase):
    """A PATCH_TASK (unlike a SKILL_TASK) sets needs_relaunch=True, so
    work_on_next_task is what actually calls _relaunch_or_rollback --
    this covers the DONE-vs-BLOCKED bookkeeping bug risk specifically: a
    hot-swap SUCCESS must not be mistaken for a failure just because
    _relaunch_or_rollback's return value is no longer None on success.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        (self.repo_root / "src" / "agents" / "logic").mkdir(parents=True)
        (self.repo_root / "src" / "agents" / "logic" / "base.py").write_text("X = 1\n")
        (self.repo_root / "tests").mkdir()
        (self.repo_root / "tests" / "__init__.py").write_text("")
        (self.repo_root / "tests" / "test_toy.py").write_text(
            "import unittest\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_ok(self):\n"
            "        self.assertTrue(True)\n"
        )
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=self.repo_root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=self.repo_root, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=self.repo_root, check=True)
        self.store = InMemoryStore()
        self.task_store = TaskStore(self.store)
        self.activity_log = ActivityLog(self.store)
        self.audit_gate = AuditGate()
        self.cognition = CognitionRouter()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_hot_swap_success_marks_the_task_done_not_blocked(self):
        from src.orchestrator.deployment import DeploymentManager
        from src.orchestrator.router import Router

        from src.agents.logic.base import LogicAgent

        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(LogicAgent())

        proposal = ModificationProposal(
            subject="src/agents/logic/base.py", code="X = 2\n", rationale="tweak"
        )
        agent = FakeSelfPatchAgent([proposal])
        task = self.task_store.add(
            "tweak logic", PATCH_TASK, subject="src/agents/logic/base.py"
        )

        message = work_on_next_task(
            self.task_store, SkillResearchAgent(), agent, self.audit_gate, self.store,
            self.activity_log, self.cognition, repo_root=self.repo_root,
            deployment_manager=manager,
            hot_swap_factories={"src/agents/logic/base.py": lambda cls: cls()},
        )

        self.assertIn("APPLIED", message)
        self.assertIn("hot-swapped", message)
        self.assertEqual(self.task_store.get(task.id).status, DONE)


class TestReconsiderBlockedTasks(unittest.TestCase):
    def test_no_blocked_tasks_returns_none(self):
        from src.main import _reconsider_blocked_tasks

        store = InMemoryStore()
        task_store = TaskStore(store)
        task_store.add("fine", SKILL_TASK)

        self.assertIsNone(_reconsider_blocked_tasks(task_store))

    def test_resets_a_blocked_task_to_pending(self):
        from src.main import _reconsider_blocked_tasks

        store = InMemoryStore()
        task_store = TaskStore(store)
        task = task_store.add("stuck", SKILL_TASK)
        task_store.update_status(task.id, BLOCKED, note="denied", attempt=True)

        result = _reconsider_blocked_tasks(task_store)

        self.assertIsNotNone(result)
        self.assertEqual(task_store.get(task.id).status, PENDING)

    def test_gives_up_permanently_past_the_retry_ceiling(self):
        from src.main import MAX_BLOCKED_RETRY_ATTEMPTS, _reconsider_blocked_tasks

        store = InMemoryStore()
        task_store = TaskStore(store)
        task = task_store.add("truly stuck", SKILL_TASK)
        for _ in range(MAX_BLOCKED_RETRY_ATTEMPTS):
            task_store.update_status(task.id, BLOCKED, note="denied", attempt=True)

        result = _reconsider_blocked_tasks(task_store)

        self.assertIsNone(result)
        self.assertEqual(task_store.get(task.id).status, FAILED)

    def test_skips_a_permanently_failed_task_and_retries_a_retriable_one(self):
        from src.main import MAX_BLOCKED_RETRY_ATTEMPTS, _reconsider_blocked_tasks

        store = InMemoryStore()
        task_store = TaskStore(store)
        exhausted = task_store.add("exhausted", SKILL_TASK)
        for _ in range(MAX_BLOCKED_RETRY_ATTEMPTS):
            task_store.update_status(exhausted.id, BLOCKED, note="denied", attempt=True)
        retriable = task_store.add("still worth a shot", SKILL_TASK)
        task_store.update_status(retriable.id, BLOCKED, note="denied", attempt=True)

        result = _reconsider_blocked_tasks(task_store)

        self.assertEqual(result.id, retriable.id)
        self.assertEqual(task_store.get(exhausted.id).status, FAILED)
        self.assertEqual(task_store.get(retriable.id).status, PENDING)


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


class TestDiscoverCreativeImprovements(unittest.TestCase):
    """discover_creative_improvements is Sim setting its own agenda when
    nothing has actually gone wrong -- the creative half of "find gaps,
    find improvement areas... be creative, think big" (direct creator
    feedback). See its own docstring in src/main.py.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_no_real_provider_returns_nothing(self):
        store = InMemoryStore()
        task_store = TaskStore(store)

        created = discover_creative_improvements(
            CognitionRouter(), task_store, repo_root=self.repo_root
        )

        self.assertEqual(created, [])
        self.assertEqual(task_store.all(), [])

    def test_parses_brainstormed_targets_into_tasks(self):
        store = InMemoryStore()
        task_store = TaskStore(store)
        cognition = _FakeBrainstormCognition(
            "1. src/orchestrator/foo.py :: teach it to notice X\n"
            "2. src/orchestrator/bar.py :: teach it to notice Y\n"
        )

        created = discover_creative_improvements(cognition, task_store, repo_root=self.repo_root, count=2)

        self.assertEqual(len(created), 2)
        self.assertEqual(len(task_store.all()), 2)
        self.assertTrue(all(t.discovered_via == "creative_agenda" for t in created))
        self.assertTrue(all(t.kind == PATCH_TASK for t in created))
        self.assertEqual(created[0].subject, "src/orchestrator/foo.py")

    def test_unparseable_response_creates_nothing(self):
        store = InMemoryStore()
        task_store = TaskStore(store)
        cognition = _FakeBrainstormCognition("I refuse to make a list.")

        created = discover_creative_improvements(cognition, task_store, repo_root=self.repo_root)

        self.assertEqual(created, [])

    def test_dedupes_against_an_existing_task_description(self):
        store = InMemoryStore()
        task_store = TaskStore(store)
        description = "teach it to notice a specific real recurring pattern in its own logs"
        task_store.add(description, PATCH_TASK, subject="src/orchestrator/foo.py")
        cognition = _FakeBrainstormCognition(f"1. src/orchestrator/foo.py :: {description}\n")

        created = discover_creative_improvements(cognition, task_store, repo_root=self.repo_root, count=1)

        self.assertEqual(created, [])
        self.assertEqual(len(task_store.all()), 1)  # still just the pre-existing one

    def test_filters_out_a_target_that_can_never_pass_the_audit_gate(self):
        # Live-caught: a creative-agenda idea targeting self_patch.py (a
        # protected file, audit.py's PROTECTED_SUBJECTS) burned three
        # real LLM calls, got rejected three times, went BLOCKED, then
        # got retried and rejected again -- guaranteed to fail forever,
        # no matter how good the draft is. Filtered before ever
        # touching the task store.
        store = InMemoryStore()
        task_store = TaskStore(store)
        cognition = _FakeBrainstormCognition(
            "1. src/orchestrator/self_patch.py :: add a rollback-and-score loop\n"
            "2. src/orchestrator/foo.py :: a genuinely reachable idea\n"
        )

        created = discover_creative_improvements(cognition, task_store, repo_root=self.repo_root, count=2)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].subject, "src/orchestrator/foo.py")
        self.assertEqual(len(task_store.all()), 1)

    def test_prompt_asks_for_the_requested_count(self):
        store = InMemoryStore()
        task_store = TaskStore(store)
        cognition = _FakeBrainstormCognition("1. src/orchestrator/foo.py :: idea\n")

        discover_creative_improvements(cognition, task_store, repo_root=self.repo_root, count=1)

        self.assertIn("exactly 1", cognition.prompts[0])


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


class TestPrintAutonomousDigest(unittest.TestCase):
    def test_reports_no_actions_when_empty(self):
        import contextlib
        import io

        from src.main import _print_autonomous_digest
        from src.orchestrator.autonomy import ActivityClock, AutonomyController

        controller = AutonomyController(InMemoryStore(), ActivityClock(), perform_action=lambda: False)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_autonomous_digest(controller)

        self.assertIn("no autonomous actions", buf.getvalue())

    def test_reports_the_tally_when_there_are_actions(self):
        import contextlib
        import io

        from src.main import _print_autonomous_digest
        from src.orchestrator.autonomy import ActivityClock, AutonomyController

        store = InMemoryStore()
        clock = ActivityClock()
        clock._last_activity -= 10_000
        outcomes = iter([True, False])
        controller = AutonomyController(
            store,
            clock,
            perform_action=lambda: True,
            idle_threshold_seconds=60.0,
            action_cooldown_seconds=0.0,
            last_action_succeeded=lambda: next(outcomes),
        )
        controller.tick()
        controller.tick()

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_autonomous_digest(controller)

        output = buf.getvalue()
        self.assertIn("2 action(s)", output)
        self.assertIn("1 succeeded", output)
        self.assertIn("1 failed", output)


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

    def test_falls_back_to_a_creative_agenda_when_nothing_to_react_to(self):
        from src.main import _autonomous_action

        store = InMemoryStore()
        task_store = TaskStore(store)
        activity_log = ActivityLog(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        cognition = _FakeBrainstormCognition(
            "1. src/orchestrator/foo.py :: a genuinely ambitious idea\n"
        )

        did_something = _autonomous_action(
            task_store, reflection_agent, store, SkillResearchAgent(), None, AuditGate(),
            activity_log, cognition, repo_root=self.repo_root,
        )

        self.assertTrue(did_something)
        self.assertEqual(len(task_store.all()), 1)
        self.assertEqual(task_store.all()[0].discovered_via, "creative_agenda")

    def test_a_creative_attempt_that_finds_nothing_still_counts_as_action(self):
        # A real LLM call was still spent even when the brainstorm
        # doesn't parse into any tasks -- must still report "did
        # something" so AutonomyController starts its action_cooldown,
        # not retry every poll_interval_seconds (a real cost/rate risk,
        # unlike discover_improvements' free local-only pass).
        from src.main import _autonomous_action

        store = InMemoryStore()
        task_store = TaskStore(store)
        activity_log = ActivityLog(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        cognition = _FakeBrainstormCognition("I refuse to make a list.")

        did_something = _autonomous_action(
            task_store, reflection_agent, store, SkillResearchAgent(), None, AuditGate(),
            activity_log, cognition, repo_root=self.repo_root,
        )

        self.assertTrue(did_something)
        self.assertEqual(task_store.all(), [])

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

    def test_outcome_sink_receives_true_on_applied_task(self):
        from src.main import _autonomous_action

        store = InMemoryStore()
        task_store = TaskStore(store)
        activity_log = ActivityLog(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        task_store.add("rocketry", SKILL_TASK)
        outcomes = []

        _autonomous_action(
            task_store, reflection_agent, store, SkillResearchAgent(), None, AuditGate(),
            activity_log, CognitionRouter(), repo_root=self.repo_root,
            outcome_sink=outcomes.append,
        )

        self.assertEqual(outcomes, [True])

    def test_outcome_sink_receives_false_when_task_is_rejected(self):
        from src.main import _autonomous_action

        class AlwaysDenyAuditGate(AuditGate):
            def review(self, proposal):
                from src.orchestrator.audit import AuditVerdict

                return AuditVerdict(
                    approved_by_automation=False,
                    requires_human_approval=False,
                    reasons=["denied for the test"],
                )

        store = InMemoryStore()
        task_store = TaskStore(store)
        activity_log = ActivityLog(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        task_store.add("rocketry", SKILL_TASK)
        outcomes = []

        _autonomous_action(
            task_store, reflection_agent, store, SkillResearchAgent(), None, AlwaysDenyAuditGate(),
            activity_log, CognitionRouter(), repo_root=self.repo_root,
            outcome_sink=outcomes.append,
        )

        self.assertEqual(outcomes, [False])

    def test_outcome_sink_not_called_on_a_pure_discovery_tick(self):
        from src.main import _autonomous_action

        store = InMemoryStore()
        task_store = TaskStore(store)
        activity_log = ActivityLog(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        outcomes = []

        _autonomous_action(
            task_store, reflection_agent, store, SkillResearchAgent(), None, AuditGate(),
            activity_log, CognitionRouter(), repo_root=self.repo_root,
            outcome_sink=outcomes.append,
        )

        self.assertEqual(outcomes, [])

    def test_shares_a_ready_news_highlight_before_touching_the_task_queue(self):
        from src.main import _autonomous_action
        from src.orchestrator.socializing import NewsSocializer

        store = InMemoryStore()
        task_store = TaskStore(store)
        task_store.add("rocketry", SKILL_TASK)  # would otherwise be worked
        activity_log = ActivityLog(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        interests = InterestTracker(store, feed=_StubFeed(
            [NewsItem(title="t1", summary="s1", source="src", published_at=0.0)]
        ))
        interests.note_interest("https://example.com/feed", "seeded")

        did_something = _autonomous_action(
            task_store, reflection_agent, store, SkillResearchAgent(), None, AuditGate(),
            activity_log, CognitionRouter(), repo_root=self.repo_root,
            interests=interests, news_socializer=NewsSocializer(cooldown_seconds=0.0),
        )

        self.assertTrue(did_something)
        # the task queue was never touched -- still PENDING, not worked
        self.assertEqual(task_store.all()[0].status, PENDING)
        self.assertEqual(len(interests.unshared_news_items()), 0)

    def test_shares_a_ready_growth_highlight_before_touching_the_task_queue(self):
        from src.main import _autonomous_action
        from src.orchestrator.socializing import GrowthSocializer

        store = InMemoryStore()
        task_store = TaskStore(store)
        task_store.add("rocketry", SKILL_TASK)  # would otherwise be worked
        activity_log = ActivityLog(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        store.remember(APPLIED_KIND, "src/agents/skills/existing.py", rationale="already applied")

        did_something = _autonomous_action(
            task_store, reflection_agent, store, SkillResearchAgent(), None, AuditGate(),
            activity_log, CognitionRouter(), repo_root=self.repo_root,
            growth_socializer=GrowthSocializer(store, cooldown_seconds=0.0),
        )

        self.assertTrue(did_something)
        self.assertEqual(task_store.all()[0].status, PENDING)  # task queue untouched

    def test_growth_takes_priority_over_news_when_both_are_ready(self):
        from src.main import _autonomous_action
        from src.orchestrator.socializing import GrowthSocializer, NewsSocializer

        store = InMemoryStore()
        task_store = TaskStore(store)
        activity_log = ActivityLog(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        store.remember(APPLIED_KIND, "src/agents/skills/existing.py", rationale="already applied")
        interests = InterestTracker(store, feed=_StubFeed(
            [NewsItem(title="t1", summary="s1", source="src", published_at=0.0)]
        ))
        interests.note_interest("https://example.com/feed", "seeded")

        _autonomous_action(
            task_store, reflection_agent, store, SkillResearchAgent(), None, AuditGate(),
            activity_log, CognitionRouter(), repo_root=self.repo_root,
            interests=interests, news_socializer=NewsSocializer(cooldown_seconds=0.0),
            growth_socializer=GrowthSocializer(store, cooldown_seconds=0.0),
        )

        # growth was shared (its only candidate is now used up); news
        # was never even fetched, since growth wins the tick and the
        # news branch is never reached at all.
        self.assertIsNone(GrowthSocializer(store).share_next(None))
        self.assertEqual(len(interests.unshared_news_items()), 0)

    def test_falls_through_to_task_work_when_news_is_not_ready(self):
        from src.main import _autonomous_action
        from src.orchestrator.socializing import NewsSocializer

        store = InMemoryStore()
        task_store = TaskStore(store)
        task_store.add("rocketry", SKILL_TASK)
        activity_log = ActivityLog(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        interests = InterestTracker(store, feed=_StubFeed(
            [
                NewsItem(title="t1", summary="s1", source="src", published_at=0.0),
                NewsItem(title="t2", summary="s2", source="src", published_at=0.0),
            ]
        ))
        interests.note_interest("https://example.com/feed", "seeded")
        socializer = NewsSocializer(cooldown_seconds=3600.0)
        socializer.share_next(interests, None)  # consumes t1, starts the real cooldown clock

        did_something = _autonomous_action(
            task_store, reflection_agent, store, SkillResearchAgent(), None, AuditGate(),
            activity_log, CognitionRouter(), repo_root=self.repo_root,
            interests=interests, news_socializer=socializer,
        )

        self.assertTrue(did_something)
        self.assertEqual(task_store.all()[0].status, DONE)  # the task WAS worked
        self.assertEqual(len(interests.unshared_news_items()), 1)  # t2 untouched

    def test_no_interests_or_socializer_given_behaves_exactly_as_before(self):
        from src.main import _autonomous_action

        store = InMemoryStore()
        task_store = TaskStore(store)
        task_store.add("rocketry", SKILL_TASK)
        activity_log = ActivityLog(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)

        did_something = _autonomous_action(
            task_store, reflection_agent, store, SkillResearchAgent(), None, AuditGate(),
            activity_log, CognitionRouter(), repo_root=self.repo_root,
        )

        self.assertTrue(did_something)
        self.assertEqual(task_store.all()[0].status, DONE)


class TestMaybeVolunteerDuringConversation(unittest.TestCase):
    """`_maybe_volunteer_during_conversation` is the fix for the
    live-caught complaint that Sim only ever acts on its own between
    conversations (the idle loop), never during one -- see its own
    docstring in src/main.py. These exercise it directly, the same way
    TestAutonomousAction exercises the idle-loop's priority logic.
    """

    def test_shares_a_ready_growth_highlight(self):
        import contextlib
        import io

        from src.main import _maybe_volunteer_during_conversation
        from src.orchestrator.socializing import GrowthSocializer

        store = InMemoryStore()
        store.remember(APPLIED_KIND, "src/agents/skills/existing.py", rationale="already applied")
        growth_socializer = GrowthSocializer(store, cooldown_seconds=0.0)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _maybe_volunteer_during_conversation(growth_socializer, None, None, CognitionRouter())

        self.assertIn("existing.py", buf.getvalue())
        self.assertIsNone(growth_socializer.share_next(None))  # consumed, not left for next time

    def test_shares_a_ready_news_highlight_when_growth_has_nothing(self):
        import contextlib
        import io

        from src.main import _maybe_volunteer_during_conversation
        from src.orchestrator.socializing import GrowthSocializer, NewsSocializer

        store = InMemoryStore()
        interests = InterestTracker(store, feed=_StubFeed(
            [NewsItem(title="t1", summary="s1", source="src", published_at=0.0)]
        ))
        interests.note_interest("https://example.com/feed", "seeded")
        growth_socializer = GrowthSocializer(store, cooldown_seconds=0.0)  # nothing applied yet
        news_socializer = NewsSocializer(cooldown_seconds=0.0)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _maybe_volunteer_during_conversation(
                growth_socializer, news_socializer, interests, CognitionRouter()
            )

        self.assertIn("t1", buf.getvalue())

    def test_growth_takes_priority_over_news_when_both_are_ready(self):
        import contextlib
        import io

        from src.main import _maybe_volunteer_during_conversation
        from src.orchestrator.socializing import GrowthSocializer, NewsSocializer

        store = InMemoryStore()
        store.remember(APPLIED_KIND, "src/agents/skills/existing.py", rationale="already applied")
        interests = InterestTracker(store, feed=_StubFeed(
            [NewsItem(title="t1", summary="s1", source="src", published_at=0.0)]
        ))
        interests.note_interest("https://example.com/feed", "seeded")
        growth_socializer = GrowthSocializer(store, cooldown_seconds=0.0)
        news_socializer = NewsSocializer(cooldown_seconds=0.0)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _maybe_volunteer_during_conversation(
                growth_socializer, news_socializer, interests, CognitionRouter()
            )

        self.assertIn("existing.py", buf.getvalue())
        self.assertEqual(len(interests.unshared_news_items()), 0)  # news never even checked

    def test_prints_nothing_when_nothing_is_ready(self):
        import contextlib
        import io

        from src.main import _maybe_volunteer_during_conversation
        from src.orchestrator.socializing import GrowthSocializer, NewsSocializer

        store = InMemoryStore()
        growth_socializer = GrowthSocializer(store, cooldown_seconds=3600.0)
        news_socializer = NewsSocializer(cooldown_seconds=3600.0)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _maybe_volunteer_during_conversation(growth_socializer, news_socializer, None, CognitionRouter())

        self.assertEqual(buf.getvalue(), "")

    def test_no_socializers_given_is_a_safe_no_op(self):
        import contextlib
        import io

        from src.main import _maybe_volunteer_during_conversation

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _maybe_volunteer_during_conversation(None, None, None, CognitionRouter())

        self.assertEqual(buf.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
