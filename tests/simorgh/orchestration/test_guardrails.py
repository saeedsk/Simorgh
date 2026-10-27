"""`orchestration/guardrails.py` (stage 16 item 2): forge's validator,
error budget and step enforcer, as pure code, then wired into the
session loop.

The lines this must hold (docs/plan/stage-16-forge-guardrails.md, "What
this must never do"): Guardian is never bypassed and a safety denial is
never nudged or retried; a chat or voice text reply is an answer; every
nudge path is bounded; a nudge spends no step of `max_steps` and is on
the task stream; `ablate = ["nudge", "steps"]` is the loop as it was."""

from __future__ import annotations

import unittest
from dataclasses import replace

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.orchestration import guardrails as g
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Budget, Session
from simorgh.orchestration.config import ABLATABLE, Config
from simorgh.orchestration.resume import restore_session
from simorgh.orchestration.session import NO_RECOVERY_REASON, SessionRunner
from simorgh.orchestration.tools import forget_registered, note_schema, offered_tools

from .fakes import FakeCognition, FakeGuardianExecution, FakeVerification
from .harness import Harness, run

OFFERED = ("read_file", "run_tests", "git_commit")


# -- pure ---------------------------------------------------------------------


class Validate(unittest.TestCase):
    def test_a_good_call_passes(self):
        verdict = g.validate([{"tool": "read_file", "args": {"path": "a"}}], OFFERED)
        self.assertIsInstance(verdict, g.Ok)

    def test_an_unknown_tool_is_a_tool_channel_nudge_listing_the_tools(self):
        verdict = g.validate([{"tool": "teleport", "args": {}}], OFFERED)
        self.assertEqual((verdict.kind, verdict.role), ("unknown_tool", "tool"))
        self.assertIn("read_file, run_tests, git_commit", verdict.content)

    def test_args_that_are_not_an_object_are_bad_args(self):
        for call in ({"tool": "read_file", "args": "a"}, {"tool": "read_file", "args": {}, "error": "not JSON"}):
            verdict = g.validate([call], OFFERED)
            self.assertEqual((verdict.kind, verdict.role), ("bad_args", "tool"), call)

    def test_schema_required_and_kind_are_checked_like_guardian(self):
        schema = {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"},
                                                                          "limit": {"type": "integer"}}}
        self.assertEqual(g.validate([{"tool": "read_file", "args": {}}], OFFERED, {"read_file": schema}).kind,
                         "bad_args")
        self.assertEqual(g.validate([{"tool": "read_file", "args": {"path": ["a"]}}], OFFERED,
                                    {"read_file": schema}).kind, "bad_args")
        # Guardian's widening: a number written as text, and an extra key, pass.
        self.assertIsInstance(g.validate([{"tool": "read_file", "args": {"path": "a", "limit": "5", "x": 1}}],
                                         OFFERED, {"read_file": schema}), g.Ok)

    def test_a_marker_tool_needs_only_what_its_line_guarantees(self):
        # `cam_ptz` is one line, `{"camera": ...}`; its schema may require more.
        schema = {"required": ["camera", "command"], "properties": {"camera": {"type": "string"}}}
        self.assertEqual(g.schema_problems("cam_ptz", {"camera": "front left"}, schema), [])


class LooksLikeCall(unittest.TestCase):
    def test_prose_mentioning_a_tool_is_an_answer(self):
        self.assertFalse(g.looks_like_call("I used read_file on it and the answer is 4.", OFFERED))
        self.assertFalse(g.looks_like_call("Call read_file (the file reader) to see it.", OFFERED))

    def test_a_call_shape_is_not(self):
        self.assertTrue(g.looks_like_call('read_file({"path": "a"})', OFFERED))
        self.assertTrue(g.looks_like_call('Sure.\nrun_tests{"target": "tests"}', OFFERED))
        self.assertTrue(g.looks_like_call('```json\n{"name": "read_file", "arguments": {}}\n```', OFFERED))

    def test_a_tool_not_offered_does_not_count(self):
        self.assertFalse(g.looks_like_call("teleport(now)", OFFERED))

    def test_fenced_json_that_names_no_offered_tool_is_an_answer(self):
        # A chat answer that is itself JSON ("give me Ira as JSON") has a
        # `name` key and is still an answer, not a call (ADR-013).
        self.assertFalse(g.looks_like_call('```json\n{"name": "Ira", "age": 5}\n```', OFFERED))
        self.assertFalse(g.looks_like_call('```json\n{"tool": "a hammer"}\n```', OFFERED))
        self.assertTrue(g.looks_like_call('```json\n{"tool": "run_tests", "args": {}}\n```', OFFERED))

    def test_whole_counts_only_a_reply_that_is_nothing_but_the_call(self):
        call = '```json\n{"tool": "run_tests", "args": {}}\n```'
        self.assertTrue(g.looks_like_call(call, OFFERED, whole=True))
        self.assertTrue(g.looks_like_call('read_file({"path": "a"})', OFFERED, whole=True))
        self.assertFalse(g.looks_like_call(f"Sure, I'd run {call}", OFFERED, whole=True))
        self.assertFalse(g.looks_like_call(f"{call}\nShall I?", OFFERED, whole=True))
        self.assertFalse(g.looks_like_call('Sure.\nrun_tests{"target": "tests"}', OFFERED, whole=True))


class ErrorBudgetTest(unittest.TestCase):
    def test_retries_exhaust_after_the_limit_and_a_clean_proposal_resets(self):
        b = g.ErrorBudget(max_retries=3)
        self.assertIsNone(b.retry("unknown_tool"))
        b.clean_proposal()
        for _ in range(3):
            self.assertIsNone(b.retry("bad_args"))
        ended = b.retry("bad_args")
        self.assertEqual((ended.outcome, ended.reason), ("failed", "retries exhausted: bad_args"))

    def test_hard_errors_count_per_step_and_a_clean_step_resets(self):
        b = g.ErrorBudget(max_tool_errors=2)
        for _ in range(2):
            b.result(False, "failed")
            b.result(False, "failed")  # two in one step count once
            self.assertEqual(b.end_step(), (None, False))
        b.result(True)
        self.assertEqual(b.end_step(), (None, True))
        self.assertEqual(b.tool_errors, 0)
        for _ in range(2):
            b.result(False, "failed")
            b.end_step()
        b.result(False, "failed")
        ended, _ = b.end_step()
        self.assertEqual((ended.outcome, ended.reason), ("failed", "tool errors exhausted"))

    def test_a_soft_error_is_not_counted(self):
        b = g.ErrorBudget(max_tool_errors=1)
        for _ in range(5):
            b.result(False, "transient")
            self.assertEqual(b.end_step(), (None, False))
        self.assertEqual(b.tool_errors, 0)

    def test_the_same_refusal_twice_is_blocked(self):
        b = g.ErrorBudget()
        self.assertIsNone(b.result(False, "unconfigured", ("notify", "h1")))
        self.assertIsNone(b.result(False, "unconfigured", ("notify", "h2")), "a different call is not a repeat")
        ended = b.result(False, "unconfigured", ("notify", "h1"))
        self.assertEqual(ended.outcome, "blocked")

    def test_a_denial_is_neither_counted_nor_clean(self):
        b = g.ErrorBudget(max_tool_errors=0)
        b.result(False, "denied", ("x", "h"))
        b.result(False, "denied", ("x", "h"))
        self.assertEqual(b.end_step(), (None, False))


class StepsTest(unittest.TestCase):
    def test_premature_tiers_one_two_three_then_blocked(self):
        s = g.Steps(required=("run_tests",), terminal=("git_commit",))
        commit = [{"tool": "git_commit", "args": {}}]
        tiers = [s.check(commit).tier for _ in range(3)]
        self.assertEqual(tiers, [1, 2, 3])
        self.assertIn("STOP.", g.step_text("git_commit", ["run_tests"], 3))
        ended = s.check(commit)
        self.assertEqual((ended.outcome, ended.reason), ("blocked", "required steps not done: run_tests"))

    def test_a_text_finish_is_premature_until_the_step_succeeds(self):
        s = g.Steps(required=("run_tests",))
        self.assertEqual(s.check_finish().kind, "step")
        s.record("run_tests", {}, ok=False, ran=True)
        self.assertEqual(s.check_finish().kind, "step", "a required step must succeed")
        s.record("run_tests", {}, ok=True)
        self.assertIsNone(s.check_finish())

    def test_a_name_prerequisite_is_met_by_a_run_even_a_failing_one(self):
        s = g.Steps(prerequisites={"git_commit": ["run_tests"]})
        commit = [{"tool": "git_commit", "args": {"path": "a"}}]
        nudge = s.check(commit)
        self.assertEqual((nudge.kind, nudge.role), ("prerequisite", "user"))
        s.record("run_tests", {"target": "tests"}, ok=False, ran=True)
        self.assertIsNone(s.check(commit))

    def test_an_arg_matched_prerequisite(self):
        s = g.Steps(prerequisites={"worktree_land": [{"tool": "git_commit", "match_arg": "path"}]})
        s.record("git_commit", {"path": "a.py", "message": "m"}, ok=True)
        self.assertEqual(s.check([{"tool": "worktree_land", "args": {"path": "b.py"}}]).kind, "prerequisite")
        self.assertIsNone(s.check([{"tool": "worktree_land", "args": {"path": "a.py"}}]))
        self.assertEqual(s.ran["git_commit"], [{"path": "a.py"}], "only the matched argument is kept")

    def test_prerequisite_violations_end_blocked_and_a_clean_step_resets_them(self):
        s = g.Steps(prerequisites={"git_commit": ["run_tests"]}, max_prereq=2)
        commit = [{"tool": "git_commit", "args": {}}]
        self.assertIsInstance(s.check(commit), g.Nudge)
        s.clean()
        self.assertIsInstance(s.check(commit), g.Nudge)
        self.assertIsInstance(s.check(commit), g.Nudge)
        self.assertEqual(s.check(commit).outcome, "blocked")

    def test_check_last_ends_blocked_without_counting(self):
        steps = g.Steps(prerequisites={"git_commit": ["run_tests"]})
        commit = {"tool": "git_commit", "args": {"path": "a.py"}}
        self.assertEqual(steps.check_last(commit), g.End("blocked", "prerequisite not done: run_tests"))
        self.assertEqual(steps.prereq_violations, 0)
        self.assertIsNone(steps.check_last({"tool": "read_file", "args": {}}))
        steps.record("run_tests", {}, ok=False, ran=True)
        self.assertIsNone(steps.check_last(commit))

    def test_state_round_trips(self):
        s = g.Steps(required=("run_tests",), prerequisites={"git_commit": ["run_tests"]})
        s.record("run_tests", {}, ok=True)
        s.check([{"tool": "git_commit", "args": {}}])
        again = g.Steps(required=("run_tests",), prerequisites={"git_commit": ["run_tests"]}).load(s.to_state())
        self.assertEqual(again.to_state(), s.to_state())
        self.assertIsNone(again.check_finish())


class FrontmatterAndConfig(unittest.TestCase):
    def test_the_new_keys_load_and_the_defaults_are_where_a_test_tool_is(self):
        self.assertEqual(profiles.PATCH.prerequisites, {"git_commit": ["run_tests"]})
        self.assertEqual(profiles.SKILL.prerequisites, {"git_commit": ["run_tests"]})
        for p in (profiles.CHAT, profiles.VOICE_CHAT, profiles.RESEARCH):
            self.assertEqual((p.required_steps, p.terminal_tools, p.prerequisites), ((), (), {}), p.name)

    def test_a_malformed_prerequisite_is_refused_at_load(self):
        text = '+++\ntools = []\nread_only = true\nmax_steps = 1\nmax_revisions = 0\nscaffold = "chat"\n' \
               'prerequisites = { git_commit = [{ tol = "run_tests" }] }\n+++\nbody'
        meta, _ = profiles.parse(text, source="x.md")
        with self.assertRaises(profiles.AgentFileError):
            profiles._prerequisites(meta["prerequisites"], source="x.md")

    def test_config_keys_and_switches(self):
        self.assertEqual((Config().max_retries, Config().max_tool_errors, Config().max_premature_attempts,
                          Config().max_prereq_violations), (3, 2, 3, 2))
        self.assertTrue({"nudge", "steps"} <= ABLATABLE)
        self.assertEqual(Config.from_mapping({"ablate": ["nudge", "steps"]}).problems, ())


# -- wired into the session -----------------------------------------------------


class _Results(FakeGuardianExecution):
    """Approves every call; each result is the next of `results`
    ((ok, error_kind)), the last one repeating."""

    results: list = [(True, "")]

    async def _on(self, message: Message) -> None:
        self.proposals.append(message)
        ok, kind = self.results[min(len(self.proposals) - 1, len(self.results) - 1)]
        await self._bus.publish(message.caused(topics.ACTION_RESULT, {
            "action_id": message.payload["action_id"], "ok": ok, "output_ref": "",
            "stdout_preview": "done" if ok else "", "error": None if ok else "it broke",
            **({"error_kind": kind} if kind else {}), "duration_ms": 1, "side_effects": [],
        }, source="execution"))


def _results(*results):
    return type("_R", (_Results,), {"results": list(results)})


async def _session(h, *, script, ablate=(), execution=FakeGuardianExecution, profile=None, task_id="t-g",
                   max_steps=8, session=None, limits=(3, 2, 3, 2)):
    cognition = FakeCognition(h.client("cognition"), script=list(script))
    gx = execution(h.client("guardian"))
    verification = FakeVerification(h.client("verification"), verdicts=["pass"])
    for fake in (cognition, gx, verification):
        await fake.start()
    runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05,
                           ablate=tuple(ablate), guard_limits=limits)
    profile = profile or replace(profiles.RESEARCH, verify=False, max_revisions=0, max_steps=max_steps)
    session = session or Session(task_id=task_id, kind="research", mode="execute", user_text="find it",
                                 profile=profile, budget=Budget(max_steps=max_steps, max_revisions=0))
    outcome = await runner.run(session, user_text="find it")
    for fake in (cognition, gx, verification):
        await fake.stop()
    return outcome, cognition, gx, session


async def _steps(h, task_id="t-g"):
    return [e.payload for e in await h.ledger.read(f"task:{task_id}") if e.type == topics.TASK_STEP]


_TELEPORT = {"tool_calls": [{"id": "c1", "tool": "teleport", "args": {}}]}
_READ = {"tool_calls": [{"tool": "read_file", "args": {"path": "a"}}]}


class InTheSession(unittest.TestCase):
    def tearDown(self):
        forget_registered()

    @run
    async def test_an_unknown_tool_is_nudged_not_proposed_and_spends_no_step(self):
        async with Harness() as h:
            outcome, cognition, gx, session = await _session(h, script=[_TELEPORT, {"text": "The answer is 4."}])
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(gx.proposals, [], "nothing reached Guardian")
            self.assertEqual(len(cognition.calls), 2)
            self.assertEqual(session.budget.steps_used, 1, "only the answer spent a step")
            tool_turn = [m for m in session.messages if m.get("role") == "tool"]
            self.assertIn("does not exist", tool_turn[0]["content"])
            nudges = [p for p in await _steps(h) if p.get("nudge")]
            self.assertEqual([p["nudge"] for p in nudges], ["unknown_tool"])

    @run
    async def test_a_schema_invalid_call_is_bad_args(self):
        note_schema("read_file", {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}})
        async with Harness() as h:
            outcome, _, gx, _ = await _session(h, script=[
                {"tool_calls": [{"id": "c1", "tool": "read_file", "args": {"path": ["a", "b"]}}]},
                {"text": "The answer is 4."}])
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(gx.proposals, [])
            self.assertEqual([p["nudge"] for p in await _steps(h) if p.get("nudge")], ["bad_args"])

    @run
    async def test_retries_exhausted_ends_failed(self):
        async with Harness() as h:
            outcome, cognition, _, session = await _session(h, script=[_TELEPORT])
            self.assertEqual((outcome.kind, outcome.reason), ("failed", "retries exhausted: unknown_tool"))
            self.assertEqual(len(cognition.calls), 4)
            self.assertEqual(session.budget.steps_used, 1, "three nudges spent nothing; the ending think did")

    @run
    async def test_a_clean_proposal_resets_the_retry_budget(self):
        async with Harness() as h:
            script = [_TELEPORT, _TELEPORT, _TELEPORT, _READ, _TELEPORT, _TELEPORT, _TELEPORT, {"text": "4."}]
            outcome, _, gx, _ = await _session(h, script=script)
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(len(gx.proposals), 1)

    @run
    async def test_hard_tool_errors_exhaust(self):
        async with Harness() as h:
            outcome, cognition, gx, _ = await _session(h, script=[_READ], execution=_results((False, "failed")))
            self.assertEqual((outcome.kind, outcome.reason), ("failed", "tool errors exhausted"))
            self.assertEqual(len(gx.proposals), 3)

    @run
    async def test_soft_errors_are_fed_back_and_not_counted(self):
        async with Harness() as h:
            script = [_READ] * 4 + [{"text": "It kept timing out."}]
            outcome, _, gx, _ = await _session(h, script=script, execution=_results((False, "transient")))
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(len(gx.proposals), 4)

    @run
    async def test_unconfigured_twice_is_blocked(self):
        async with Harness() as h:
            outcome, _, gx, _ = await _session(h, script=[_READ], execution=_results((False, "unconfigured")))
            self.assertEqual(outcome.kind, "blocked")
            self.assertTrue(outcome.reason.startswith("the same call was refused twice"), outcome.reason)
            self.assertEqual(len(gx.proposals), 2)

    @run
    async def test_a_guardian_denial_is_fed_back_and_never_nudged_or_retried(self):
        class _Denying(FakeGuardianExecution):
            def __init__(self, bus):
                super().__init__(bus, deny=True)

        async with Harness() as h:
            outcome, cognition, gx, _ = await _session(
                h, script=[_READ, {"text": "I was not allowed to read it."}], execution=_Denying)
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(len(gx.proposals), 1, "proposed once, not retried")
            self.assertEqual(len(cognition.calls), 2)
            self.assertEqual([p for p in await _steps(h) if p.get("nudge")], [])

    @run
    async def test_a_chat_text_reply_is_never_nudged(self):
        async with Harness() as h:
            chat = replace(profiles.CHAT, verify=False)
            session = Session(task_id="t-g", kind="chat", mode="execute", profile=chat,
                              budget=Budget(max_steps=chat.max_steps, max_revisions=0))
            outcome, cognition, _, _ = await _session(
                h, script=[{"text": "You could use read_file for that; the answer is 4."}], session=session)
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(len(cognition.calls), 1)

    @run
    async def test_a_text_that_looks_like_a_failed_call_is_nudged(self):
        async with Harness() as h:
            chat = replace(profiles.CHAT, verify=False)
            tool = offered_tools(chat.tools)[1]
            session = Session(task_id="t-g", kind="chat", mode="execute", profile=chat,
                              budget=Budget(max_steps=chat.max_steps, max_revisions=0))
            outcome, cognition, _, _ = await _session(
                h, script=[{"text": f'{tool}({{"path": "a"}})'}, {"text": "The answer is 4."}], session=session)
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(len(cognition.calls), 2)
            self.assertEqual([p["nudge"] for p in await _steps(h) if p.get("nudge")], ["retry"])

    @run
    async def test_a_chat_answer_in_json_is_never_nudged(self):
        async with Harness() as h:
            chat = replace(profiles.CHAT, verify=False)
            session = Session(task_id="t-g", kind="chat", mode="execute", profile=chat,
                              budget=Budget(max_steps=chat.max_steps, max_revisions=0))
            outcome, cognition, _, _ = await _session(
                h, script=[{"text": 'Here it is:\n```json\n{"name": "Ira", "age": 5}\n```'}], session=session)
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(len(cognition.calls), 1)

    @run
    async def test_a_nudged_call_is_not_a_step_that_ran_the_tool(self):
        # The step log is what the honesty checks read: a git_commit that
        # was held back by its prerequisite must not read as a commit.
        from simorgh.orchestration import claims, stophook

        async with Harness() as h:
            profile = replace(profiles.PATCH, verify=False, max_revisions=0, max_steps=8)
            commit = {"tool_calls": [{"tool": "git_commit", "args": {"path": "a.py", "message": "m"}}]}
            session = Session(task_id="t-g", kind="patch", mode="execute", profile=profile, subject="a.py",
                              budget=Budget(max_steps=8, max_revisions=0))
            await _session(h, script=[commit, _TELEPORT, {"text": "Done."}], session=session)
            nudged = [s for s in session.steps if s.nudge]
            self.assertEqual([s.nudge for s in nudged], ["prerequisite", "unknown_tool"])
            self.assertTrue(all(s.tool is None for s in nudged))
            self.assertIn("git_commit", nudged[0].summary)
            self.assertEqual(claims._tools_used(session.steps), set())
            self.assertTrue(stophook.claimed_to_commit("The change is committed.", session))

    @run
    async def test_a_premature_finish_escalates_then_blocks(self):
        async with Harness() as h:
            profile = replace(profiles.RESEARCH, verify=False, max_revisions=0, max_steps=8,
                              required_steps=("run_tests",))
            outcome, cognition, _, session = await _session(h, script=[{"text": "The answer is 4."}], profile=profile)
            self.assertEqual((outcome.kind, outcome.reason), ("blocked", "required steps not done: run_tests"))
            nudges = [p for p in await _steps(h) if p.get("nudge")]
            self.assertEqual([(p["nudge"], p["tier"]) for p in nudges], [("step", 1), ("step", 2), ("step", 3)])
            self.assertEqual(session.budget.steps_used, 1)

    @run
    async def test_a_prerequisite_blocks_the_call_until_it_has_run(self):
        async with Harness() as h:
            profile = replace(profiles.PATCH, verify=False, max_revisions=0, max_steps=8)
            commit = {"tool_calls": [{"tool": "git_commit", "args": {"path": "a.py", "message": "m"}}]}
            tests = {"tool_calls": [{"tool": "run_tests", "args": {"target": "tests"}}]}
            session = Session(task_id="t-g", kind="patch", mode="execute", profile=profile, subject="a.py",
                              budget=Budget(max_steps=8, max_revisions=0))
            outcome, _, gx, _ = await _session(h, script=[commit, tests, commit, {"text": "Committed."}],
                                               session=session)
            self.assertEqual([m.payload["tool"] for m in gx.proposals], ["run_tests", "git_commit"])
            self.assertEqual([p["nudge"] for p in await _steps(h) if p.get("nudge")], ["prerequisite"])

    async def _last_step_commit(self, h, script, max_steps, ablate=()):
        profile = replace(profiles.PATCH, verify=False, max_revisions=0, max_steps=max_steps)
        session = Session(task_id="t-l", kind="patch", mode="execute", profile=profile, subject="a.py",
                          budget=Budget(max_steps=max_steps, max_revisions=0))
        session.uncommitted.add("a.py")  # an edit applied by an earlier attempt
        return await _session(h, script=script, session=session, max_steps=max_steps, ablate=ablate)

    @run
    async def test_a_last_step_commit_without_its_tests_is_not_proposed(self):
        # Stage 16 edge case (decided 2026-10-27): prerequisites hold on
        # the last step too, and the edit stays for the next attempt.
        async with Harness() as h:
            commit = {"tool_calls": [{"tool": "git_commit", "args": {"path": "a.py", "message": "m"}}]}
            outcome, _, gx, session = await self._last_step_commit(h, [commit], max_steps=1)
            self.assertEqual((outcome.kind, outcome.reason), ("blocked", "prerequisite not done: run_tests"))
            self.assertEqual(gx.proposals, [])
            self.assertEqual(session.uncommitted, {"a.py"})
            summaries = [p.get("summary", "") for p in await _steps(h, "t-l")]
            self.assertTrue(any(s.startswith("kept 1 uncommitted edit") for s in summaries), summaries)

    @run
    async def test_a_last_step_commit_after_its_tests_runs(self):
        async with Harness() as h:
            tests = {"tool_calls": [{"tool": "run_tests", "args": {"target": "tests"}}]}
            commit = {"tool_calls": [{"tool": "git_commit", "args": {"path": "a.py", "message": "m"}}]}
            outcome, _, gx, _ = await self._last_step_commit(h, [tests, commit], max_steps=2)
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual([m.payload["tool"] for m in gx.proposals], ["run_tests", "git_commit"])

    @run
    async def test_a_last_step_commit_with_steps_ablated_runs_as_before(self):
        async with Harness() as h:
            commit = {"tool_calls": [{"tool": "git_commit", "args": {"path": "a.py", "message": "m"}}]}
            outcome, _, gx, _ = await self._last_step_commit(h, [commit], max_steps=1, ablate=("steps",))
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual([m.payload["tool"] for m in gx.proposals], ["git_commit"])

    @run
    async def test_a_chat_reply_quoting_a_call_in_prose_is_an_answer(self):
        # Stage 16 edge case (decided 2026-10-27): the orchestration half
        # of Cognition's whole-reply rescue -- not nudged as a failed call.
        async with Harness() as h:
            chat = replace(profiles.CHAT, verify=False)
            tool = offered_tools(chat.tools)[1]
            session = Session(task_id="t-g", kind="chat", mode="execute", profile=chat,
                              budget=Budget(max_steps=chat.max_steps, max_revisions=0))
            text = f'Sure, I\'d run this:\n```json\n{{"tool": "{tool}", "args": {{}}}}\n```\nWant me to?'
            outcome, cognition, gx, _ = await _session(h, script=[{"text": text}], session=session)
            self.assertEqual((outcome.kind, len(cognition.calls), gx.proposals), ("completed", 1, []))

    @run
    async def test_step_state_survives_a_resume(self):
        async with Harness() as h:
            profile = replace(profiles.PATCH, verify=False, max_revisions=0, max_steps=8)
            tests = {"tool_calls": [{"tool": "run_tests", "args": {"target": "tests"}}]}
            first = Session(task_id="t-r", kind="patch", mode="execute", profile=profile, subject="a.py",
                            budget=Budget(max_steps=8, max_revisions=0))
            await _session(h, script=[tests, {"tool_calls": [{"id": "c1", "tool": "teleport", "args": {}}]},
                                      {"text": "Tested."}], session=first)
            # The worker died before writing an outcome: the next one resumes.
            second = Session(task_id="t-r", kind="patch", mode="execute", profile=profile, subject="a.py",
                             budget=Budget(max_steps=8, max_revisions=0))
            spent = await restore_session(second, h.ledger)
            self.assertIn("run_tests", second.step_state["ran"])
            self.assertEqual(second.budget.steps_used, spent - 1, "the nudge is not a spent step")
            commit = {"tool_calls": [{"tool": "git_commit", "args": {"path": "a.py", "message": "m"}}]}
            _, _, gx, _ = await _session(h, script=[commit, {"text": "Committed."}], session=second)
            self.assertEqual([m.payload["tool"] for m in gx.proposals], ["git_commit"], "no prerequisite nudge")

    @run
    async def test_recovery_ablated_ends_instead_of_nudging(self):
        async with Harness() as h:
            outcome, cognition, _, _ = await _session(h, script=[_TELEPORT], ablate=("recovery",))
            self.assertEqual(outcome.kind, "failed")
            self.assertTrue(outcome.reason.startswith(NO_RECOVERY_REASON), outcome.reason)
            self.assertIn("teleport is not a tool of this session", outcome.reason)
            self.assertEqual(len(cognition.calls), 1)


class AllSwitchesOff(unittest.TestCase):
    """`ablate = ["nudge", "steps"]` is the loop as it was before stage 16."""

    @run
    async def test_no_guards_and_every_call_goes_to_guardian(self):
        async with Harness() as h:
            outcome, _, gx, session = await _session(h, script=[_TELEPORT, {"text": "The answer is 4."}],
                                                     ablate=("nudge", "steps"))
            self.assertIsNone(session.guards)
            self.assertEqual([m.payload["tool"] for m in gx.proposals], ["teleport"])
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(session.budget.steps_used, 2)
            self.assertTrue(all("nudge" not in p and "steps_state" not in p for p in await _steps(h)))

    @run
    async def test_a_commit_without_tests_and_repeated_failures_are_as_before(self):
        async with Harness() as h:
            profile = replace(profiles.PATCH, verify=False, max_revisions=0, max_steps=8)
            commit = {"tool_calls": [{"tool": "git_commit", "args": {"path": "a.py", "message": "m"}}]}
            session = Session(task_id="t-g", kind="patch", mode="execute", profile=profile, subject="a.py",
                              budget=Budget(max_steps=8, max_revisions=0))
            _, _, gx, _ = await _session(h, script=[commit, _READ, _READ, _READ, _READ, {"text": "Done."}],
                                         ablate=("nudge", "steps"), session=session,
                                         execution=_results((True, ""), (False, "failed")))
            self.assertEqual([m.payload["tool"] for m in gx.proposals],
                             ["git_commit", "read_file", "read_file", "read_file", "read_file"])

    @run
    async def test_steps_alone_can_be_switched_off(self):
        async with Harness() as h:
            profile = replace(profiles.RESEARCH, verify=False, max_revisions=0, max_steps=8,
                              required_steps=("run_tests",))
            outcome, _, _, session = await _session(h, script=[{"text": "The answer is 4."}], profile=profile,
                                                    ablate=("steps",))
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertIsNone(session.guards.steps)


if __name__ == "__main__":
    unittest.main()
