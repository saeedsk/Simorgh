"""Stage 19 items 4-7 (docs/plan/stage-19-code-first-problem-solving.md):
the supervisor chooses HOW a job is done (`direct|compute|parallel|
decompose|background`), tells Sim the concrete next step, holds it to that
approach early and at the answer, keeps lessons, and a split job runs as
crew members at once.

The creator, 2026-10-28, after Sim "counted" a month's top senders from
the 67 lines of a listing it could see: "this is generic feedback ...
solve this lack of intuitive thinking for all cases". So the prompts are
checked for subject words, and every model here is scripted."""

from __future__ import annotations

import asyncio
import json
import re
import time
import unittest
from dataclasses import replace

from simorgh.contracts import topics
from simorgh.orchestration import profiles, supervisor, tools
from simorgh.orchestration.api import Budget, Session
from simorgh.orchestration.config import Config
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeGuardianExecution
from .harness import Harness, run

#: Subject words no prompt this stage adds may contain (the plan's
#: definition of done: "No domain-specific rule in any prompt").
DOMAIN_WORDS = ("mail", "sender", "inbox", "calendar", "meeting", "invoice", "light", "music", "camera",
                "unsubscribe", "promo")


def _bar(approach, *, split=(), criteria=None, why="a count over more items than one page"):
    return json.dumps({"approach": approach, "why": why,
                       "criteria": criteria if criteria is not None else [
                           {"done_when": "the exact top ten over the whole period", "measured_by": "a program's count"}],
                       "split": [{"brief": b, "done_when": f"{b} is answered", "measured_by": "a report",
                                  "approach": "compute"} for b in split]})


class Cognition:
    """Sim's thinks per task id (`scripts`, the last step repeating; a step
    may be a callable of the message); the supervisor's by its prompt: the
    bar from `bars` (per task id, `*` for any), reviews from `reviews`."""

    def __init__(self, bus, scripts, *, bars=None, reviews=(), delay=None):
        self._bus, self._scripts, self._bars = bus, scripts, bars or {}
        self._reviews, self._delay = list(reviews), delay or {}
        self.calls: dict[str, list] = {}
        self.bar_prompts: list[str] = []
        self.review_prompts: list[str] = []
        self.spans: list[tuple[str, float, float]] = []

    async def start(self):
        self._sub = await self._bus.subscribe(topics.COGNITION_THINK, self._on)

    async def stop(self):
        await self._sub.unsubscribe()

    async def _on(self, message):
        said = str(message.payload["messages"][-1].get("content"))
        task_id = message.trace_id
        start = time.monotonic()
        if said.startswith(supervisor.CRITERIA_INTRO[:70]):
            self.bar_prompts.append(said)
            step = {"text": self._bars.get(task_id, self._bars.get("*", json.dumps({"criteria": []})))}
        elif said.startswith(supervisor.REVIEW_PROMPT[:70]):
            self.review_prompts.append(said)
            step = {"text": self._reviews.pop(0) if self._reviews else json.dumps({"verdict": "meets_bar"})}
        else:
            mine = self.calls.setdefault(task_id, [])
            mine.append(message)
            delay = self._delay.get(task_id, self._delay.get("*", 0.0))
            if delay:
                await asyncio.sleep(delay)
            script = self._scripts.get(task_id) or self._scripts.get("*") or [{"text": "done"}]
            step = script[min(len(mine) - 1, len(script) - 1)]
            if callable(step):
                step = step(message)
            self.spans.append((task_id, start, time.monotonic()))
        await self._bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
            "text": step.get("text", ""), "tool_calls": step.get("tool_calls", []), "provider": "fake",
            "cost_usd": 0.0, "tokens": 10, "floor": False, "non_answer": False})


def _call(tool, i=0, **args):
    return {"id": f"c{tool}{i}", "tool": tool, "args": args}


def _said(message) -> str:
    return "\n".join(str(m.get("content")) for m in message.payload["messages"])


def _chat(task_id="chat-1", *, channel="cli", speaker="", text="", steps=10):
    profile = profiles.VOICE_CHAT if channel == "voice" else profiles.CHAT
    return Session(task_id=task_id, kind="chat", mode="execute", user_text=text, channel=channel, speaker=speaker,
                   profile=replace(profile, verify=False, max_steps=steps), budget=Budget(max_steps=steps))


def _runner(h, **kw):
    kw.setdefault("think_timeout_s", 30.0)
    return SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05,
                         supervisor=True, **kw)


async def _turn(h, session, scripts, *, bars, reviews=(), delay=None, runner=None, until=None, **kw):
    """One turn; `until`, a predicate, keeps the fakes up after it (for
    background members) until it holds."""
    cognition = Cognition(h.client("cognition"), scripts, bars=bars, reviews=reviews, delay=delay)
    gx = FakeGuardianExecution(h.client("guardian"))
    await cognition.start(); await gx.start()
    runner = runner or _runner(h, **kw)
    try:
        outcome = await asyncio.wait_for(runner.run(session, user_text=session.user_text), timeout=30)
        if until is not None:
            await _until(until)
    finally:
        await cognition.stop(); await gx.stop()
    return cognition, outcome, runner


async def _until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition never held")
        await asyncio.sleep(0.02)


def _workbench_registered(test):
    """`run_analysis` as Execution's registry has it (stage 19 items 1-3,
    built beside this): offered whether or not other tools registered."""
    had = "run_analysis" in tools.known_tools()
    tools.note_registered("run_analysis")
    if not had:
        test.addCleanup(lambda: tools._REGISTERED.discard("run_analysis"))  # noqa: SLF001


# -- item 4: the approach at bar-setting -------------------------------------------------


class TheApproachIsParsedAndRendered(unittest.TestCase):
    def test_each_approach_parses_and_an_unknown_one_is_direct(self):
        for approach in ("direct", "compute", "background"):
            bar = supervisor.parse_criteria(_bar(approach))
            self.assertEqual(bar.approach, approach)
            self.assertEqual(len(bar), 1)
        bar = supervisor.parse_criteria(_bar("parallel", split=["part A", "part B", "part C"]))
        self.assertEqual((bar.approach, len(bar.split)), ("parallel", 3))
        self.assertEqual(bar.split[0]["approach"], "compute")
        self.assertTrue(bar.split[0]["criterion"].startswith("done when: part A is answered"))
        self.assertEqual(supervisor.parse_criteria(_bar("telepathy")).approach, "direct")
        self.assertEqual(supervisor.parse_criteria(_bar("parallel", split=["only one"])).approach, "direct",
                         "a split of one part is no split")
        self.assertEqual(supervisor.parse_criteria(_bar("compute")).why, "a count over more items than one page")
        # The 2026-10-28 shape, with no approach, is the bar as it was.
        old = supervisor.parse_criteria(json.dumps({"criteria": [{"done_when": "x", "measured_by": "y"}]}))
        self.assertEqual((old, old.approach), (["done when: x -- measured by: y"], "direct"))

    def test_every_approach_renders_its_next_step(self):
        split = [{"brief": f"part {x}", "criterion": f"done when: part {x} is answered", "approach": "compute"}
                 for x in "ABC"]
        self.assertEqual(supervisor.approach_step("direct"), "")
        compute = supervisor.approach_step("compute", refs=["a1b2c3"])
        for must in ("run_analysis", '"inputs": ["a1b2c3"]', "sim.rows", "sim.call", "sim.db()", "sim.save",
                     "sim.result"):
            self.assertIn(must, compute)
        parallel = supervisor.approach_step("parallel", split=split, request="the job")
        self.assertEqual(parallel.count('spawn{"agent": "research"'), 3)
        self.assertIn("all in one reply, without asking", parallel)
        for line in re.findall(r"spawn(\{.*\})", parallel):
            self.assertTrue(json.loads(line)["brief"].startswith("part "), "each spawn line is valid JSON")
        self.assertIn("Compute it with run_analysis", parallel, "a part keeps its own approach")
        decompose = supervisor.approach_step("decompose", split=split)
        self.assertIn("in order", decompose)
        background = supervisor.approach_step("background", request="the whole job", criteria=["done when: x"],
                                              inner="compute")
        self.assertIn('"background": true', background)
        self.assertIn("one short sentence", background)
        self.assertIn("Compute it with run_analysis", background)
        spoken_split = supervisor.approach_step("background", split=split)
        self.assertEqual(spoken_split.count('"background": true'), 3)
        self.assertIn("splitting this into 3", spoken_split)
        message = supervisor.criteria_message(["done when: x"], approach="compute", refs=["r1"])
        self.assertIn("Your supervisor set the bar", message)
        self.assertIn("Approach: compute", message)
        self.assertEqual(supervisor.criteria_message(["done when: x"]).count("Approach"), 0)

    def test_the_prompts_have_general_triggers_and_no_subject_rules(self):
        prompt = supervisor.criteria_prompt("r", [], approach=True)
        for trigger in ("more items than one page", "count, rank, total", "the same step repeats for each item",
                        "joins two sources", "more steps than one helper can take in this turn",
                        "do not depend on each other"):
            self.assertIn(trigger, prompt)
        self.assertNotIn("approach", supervisor.criteria_prompt("r", []), "off is the prompt as it was")
        split = [{"brief": "part", "criterion": "", "approach": "compute"}] * 2
        added = " ".join([supervisor.APPROACH_PROMPT, supervisor.REVIEW_METHOD,
                          *(supervisor.approach_step(a, split=split) for a in supervisor.APPROACHES)]).lower()
        for word in DOMAIN_WORDS:
            self.assertNotIn(word, added, word)

    def test_an_unscoped_job_gets_a_default_scope_not_everything(self):
        # Live 2026-10-30 (task cef68b40): an unscoped "summarize" got a bar of
        # every item a source held, each with its own gist, as a program;
        # three reviews held a fair digest below it and no answer went out.
        prompt = supervisor.criteria_prompt("r", [], approach=True)
        for rule in ("names no scope or count", "sensible default", "states that scope",
                     "Never set a bar that needs everything a source holds", "cannot read for meaning"):
            self.assertIn(rule, prompt)
        self.assertNotIn(supervisor.SCOPE_RULE, supervisor.criteria_prompt("r", []), "off is the prompt as it was")
        self.assertIn("never order the assistant to widen past what the person asked for",
                      supervisor.REVIEW_METHOD)

    def test_the_approach_is_what_the_turn_can_take(self):
        eff = supervisor.effective_approach
        self.assertEqual(eff("compute", voice=False, crews=True, compute=True), "compute")
        self.assertEqual(eff("compute", voice=False, crews=True, compute=False), "direct")
        self.assertEqual(eff("parallel", voice=False, crews=False, compute=True), "direct")
        self.assertEqual(eff("compute", voice=True, crews=True, compute=True), "background")
        self.assertEqual(eff("parallel", voice=True, crews=True, compute=True), "background")
        self.assertEqual(eff("direct", voice=True, crews=True, compute=True), "direct")

    def test_chat_and_voice_offer_the_workbench_and_tolerate_its_absence(self):
        for profile in (profiles.CHAT, profiles.VOICE_CHAT, profiles.RESEARCH):
            self.assertIn("run_analysis", profile.tools, profile.name)
        saved = set(tools.known_tools())
        self.addCleanup(lambda: (tools.forget_registered(), [tools.note_registered(t) for t in saved]))
        tools.forget_registered()
        self.assertIn("run_analysis", tools.offered_tools(profiles.CHAT.tools), "nothing registered yet")
        tools.note_registered("web_search")
        self.assertNotIn("run_analysis", tools.offered_tools(profiles.CHAT.tools),
                         "a registry without it: not offered")
        self.assertIn("web_search", tools.offered_tools(profiles.CHAT.tools))
        tools.note_registered("run_analysis")
        self.assertIn("run_analysis", tools.offered_tools(profiles.VOICE_CHAT.tools))
        self.assertEqual(tools.to_action_payload(action_id="a", task_id="t", call={"tool": "run_analysis", "args": {"code": "x"}}, rationale="")["reversibility"], "reversible")

    def test_the_switches_are_read_from_the_file(self):
        self.assertTrue(Config().supervisor_approach)
        self.assertTrue(Config().supervisor_lessons)
        off = Config.from_mapping({"supervisor_approach": False, "supervisor_lessons": False})
        self.assertFalse(off.supervisor_approach or off.supervisor_lessons)


# -- item 5: the review checks the method -----------------------------------------------

LISTING = {"tool_calls": [_call("web_search", query="every item of the period")]}
COUNTED = {"text": "The top three: alpha 12, beta 9, gamma 7."}
ANALYSIS = {"tool_calls": [_call("run_analysis", code="import sim\nprint(len(sim.rows('last')))", inputs=["last"])]}
COMPUTED = {"text": "From all 1000 rows: alpha 212, beta 190, gamma 87."}


class TheMethodIsReviewed(unittest.TestCase):
    @run
    async def test_counts_read_off_a_listing_are_ordered_to_run_analysis_over_its_ref(self):
        _workbench_registered(self)
        async with Harness() as h:
            session = _chat(text="who sent me the most this period, exactly")
            cognition, outcome, _ = await _turn(h, session, {"chat-1": [LISTING, COUNTED, ANALYSIS, COMPUTED]},
                                                bars={"*": _bar("compute")})
        sim = cognition.calls["chat-1"]
        self.assertEqual(len(sim), 4)
        self.assertIn("Approach: compute", _said(sim[1]), "Sim is told the method with the bar")
        self.assertIn(f'"inputs": ["{session.result_refs[0]}"]', _said(sim[1]), "with the ref already in hand")
        order = str(sim[2].payload["messages"][-1]["content"])
        self.assertIn("BELOW THE BAR (Insist on the Highest Standards)", order)
        self.assertIn(f"run_analysis over ref {session.result_refs[0]}", order)
        self.assertEqual(len(cognition.review_prompts), 1, "the counted answer was held without a think")
        self.assertIn("Expected approach: compute", cognition.review_prompts[0])
        self.assertIn("1 run_analysis run(s)", cognition.review_prompts[0])
        self.assertIn("The method is judged too", cognition.review_prompts[0])
        self.assertIn("alpha 212", outcome.result_summary)

    @run
    async def test_a_direct_job_is_still_judged_on_its_method(self):
        async with Harness() as h:
            cognition, _, _ = await _turn(h, _chat(text="x"), {"chat-1": [LISTING, COUNTED]},
                                          bars={"*": _bar("direct")})
        self.assertIn("The method is judged too", cognition.review_prompts[0])
        self.assertNotIn("Expected approach", cognition.review_prompts[0])

    @run
    async def test_approach_off_is_the_bar_and_review_as_they_were(self):
        _workbench_registered(self)
        async with Harness() as h:
            cognition, _, _ = await _turn(h, _chat(text="x"), {"chat-1": [LISTING, COUNTED]},
                                          bars={"*": _bar("compute")}, supervisor_approach=False)
        self.assertTrue(cognition.bar_prompts[0].startswith(supervisor.CRITERIA_PROMPT))
        self.assertNotIn("Approach:", _said(cognition.calls["chat-1"][1]))
        self.assertNotIn("The method is judged", cognition.review_prompts[0])


# -- item 6: lessons ---------------------------------------------------------------------


class LessonsAreKeptAndRecalled(unittest.TestCase):
    @run
    async def test_a_lesson_from_one_session_is_recalled_for_a_similar_job_only(self):
        _workbench_registered(self)
        async with Harness() as h:
            first = _chat(text="who sent me the most promotional email this month")
            await _turn(h, first, {"chat-1": [LISTING, COUNTED, ANALYSIS, COMPUTED]}, bars={"*": _bar("compute")})
            events = await h.ledger.read(supervisor.LESSONS_STREAM)
            lessons = [e.payload for e in events if e.type == supervisor.LESSON_EVENT]
            self.assertEqual(len(lessons), 1)
            lesson = lessons[0]
            for key in ("situation", "rule", "evidence_ref", "principle", "created_at", "hits"):
                self.assertIn(key, lesson)
            self.assertIn("run_analysis", lesson["rule"])
            self.assertEqual(lesson["principle"], "Insist on the Highest Standards")
            self.assertTrue(any(s.summary.startswith("supervisor: lesson kept") for s in first.steps))

            # A second session -- a new runner, the same ledger.
            similar = _chat("chat-2", text="rank the people who mailed me most in the last 30 days")
            seen, _, _ = await _turn(h, similar, {"chat-2": [LISTING, {"text": "ok"}]}, bars={"*": _bar("direct")})
            unrelated = _chat("chat-3", text="turn off the kitchen lights")
            other, _, _ = await _turn(h, unrelated, {"chat-3": [LISTING, {"text": "ok"}]},
                                      bars={"*": _bar("direct")})
            hits = [e for e in await h.ledger.read(supervisor.LESSONS_STREAM)
                    if e.type == supervisor.LESSON_HIT_EVENT]
        self.assertIn("Lessons from your own earlier reviews", seen.bar_prompts[0])
        self.assertIn(lesson["rule"][:60], seen.bar_prompts[0])
        self.assertNotIn("Lessons from your own earlier reviews", other.bar_prompts[0])
        self.assertEqual(len(hits), 1)

    def test_at_most_three_newest_first_on_ties(self):
        lessons = [{"id": str(i), "situation": "rank the items of the period", "rule": f"rule {i}",
                    "created_at": float(i)} for i in range(5)]
        got = supervisor.recall_lessons(lessons, "rank the items of the period")
        self.assertEqual([l["id"] for l in got], ["4", "3", "2"])
        self.assertEqual(supervisor.recall_lessons(lessons, "play some jazz"), [])

    @run
    async def test_lessons_off_writes_and_recalls_nothing(self):
        _workbench_registered(self)
        async with Harness() as h:
            await _turn(h, _chat(text="x"), {"chat-1": [LISTING, COUNTED, ANALYSIS, COMPUTED]},
                        bars={"*": _bar("compute")}, supervisor_lessons=False)
            events = await h.ledger.read(supervisor.LESSONS_STREAM)
        self.assertEqual(events, [])


# -- the supervisor holds Sim to the approach (the creator: "hold Sim accountable") ------

PARTS = ["the first source", "the second source", "the third source"]


class TheApproachIsHeldEarly(unittest.TestCase):
    @run
    async def test_a_parallel_job_done_serially_gets_an_early_order_naming_spawn_once(self):
        serial = [LISTING, _call_step("web_search", 1), _call_step("web_search", 2), _call_step("web_search", 3),
                  {"text": "Here are the three."}]
        async with Harness() as h:
            session = _chat(text="compare the three sources")
            cognition, _, _ = await _turn(h, session, {"chat-1": serial},
                                          bars={"*": _bar("parallel", split=PARTS)}, chat_crews=True)
        sim = cognition.calls["chat-1"]
        self.assertIn("Approach: parallel", _said(sim[1]))
        early = str(sim[2].payload["messages"][-1]["content"])
        self.assertIn("BELOW THE BAR (Bias for Action)", early)
        self.assertIn("spawn the remaining members", early)
        self.assertIn("the first source", early)
        flagged = [s for s in session.steps if s.summary.startswith("supervisor: approach not followed")]
        self.assertEqual(len(flagged), 1, "the early check runs once, however long the serial work goes on")
        later = [str(m.payload["messages"][-1]["content"]) for m in sim[3:]]
        self.assertFalse(any("approach not followed" in s for s in later))


def _call_step(tool, i, **args):
    return {"tool_calls": [_call(tool, i, query=f"page {i}", **args)]}


def _member(name):
    return [{"tool_calls": [_call("report_progress", text=f"{name}: halfway")]},
            {"tool_calls": [_call("run_analysis", code="import sim", inputs=["last"])]},
            {"text": f"{name} result: {len(name)} items"}]


def _assemble(message):
    """Sim's assembly: the reports await_agents returned, put together."""
    tool_texts = [str(m.get("content")) for m in message.payload["messages"] if m.get("role") == "tool"]
    reports = [t for t in tool_texts if "result:" in t]
    found = re.findall(r"(\w+ source result: \d+ items)", "\n".join(reports))
    return {"text": "All three: " + "; ".join(dict.fromkeys(found))}


class AParallelJobRunsAtOnce(unittest.TestCase):
    @run
    async def test_three_parts_spawn_together_report_progress_and_are_assembled(self):
        _workbench_registered(self)
        spawns = {"tool_calls": [_call("spawn", i, agent="research", brief=b) for i, b in enumerate(PARTS)]}
        script = {"chat-1": [LISTING, spawns, {"tool_calls": [_call("await_agents", mode="all", timeout_s=20)]},
                             _assemble]}
        for i, p in enumerate(PARTS, 1):
            script[f"chat-1-h{i}"] = _member(p.split(" ", 1)[1])
        async with Harness() as h:
            seen: list = []

            async def on(message):
                seen.append(message)

            for t in (topics.CREW_SPAWNED, topics.CREW_MESSAGE, topics.CREW_REPORT):
                await h.client("observer").subscribe(t, on)
            session = _chat(text="compare the three sources")
            cognition, outcome, _ = await _turn(h, session, script, bars={"*": _bar("parallel", split=PARTS)},
                                                chat_crews=True, delay={"*": 0.25, "chat-1": 0.0})
        members = [s for s in cognition.spans if s[0].startswith("chat-1-h")]
        firsts = {}
        for task_id, start, end in members:
            firsts.setdefault(task_id, (start, end))
        self.assertEqual(len(firsts), 3)
        self.assertLess(max(s for s, _ in firsts.values()), min(e for _, e in firsts.values()),
                        "the three members were thinking at the same time")
        types = [m.type for m in seen]
        self.assertEqual(types.count(topics.CREW_SPAWNED), 3)
        self.assertEqual(types.count(topics.CREW_REPORT), 3)
        progress = [m for m in seen if m.type == topics.CREW_MESSAGE and "halfway" in json.dumps(m.payload)]
        self.assertEqual(len(progress), 3, "each member's progress reached the bus the interface folds")
        for part in ("first source result", "second source result", "third source result"):
            self.assertIn(part, outcome.result_summary)
        self.assertFalse(any(s.summary.startswith("supervisor: approach not followed") for s in session.steps))
        # Each member's answer is reviewed against its own part too
        # (`supervisor_members`); the parent's review is the one that
        # judges the method, and it reads the members' reports in full.
        parent = [p for p in cognition.review_prompts if "Expected approach" in p]
        self.assertEqual(len(parent), 1)
        self.assertIn("started together: yes", parent[0])
        self.assertIn("3 member(s) spawned of 3 parts", parent[0])
        self.assertIn("The helpers' reports, in full", parent[0])
        self.assertEqual(len(cognition.review_prompts), 4, "three members' reviews and the parent's")


# -- item 7: a spoken job goes to the background ----------------------------------------


class ASpokenJobGoesToTheBackground(unittest.TestCase):
    @run
    async def test_a_voice_compute_job_spawns_acknowledges_and_delivers(self):
        _workbench_registered(self)
        bg = {"tool_calls": [_call("spawn", agent="research", background=True,
                                   brief="count over the full data")]}
        async with Harness() as h:
            seen: list = []

            async def on(message):
                seen.append(message)

            await h.client("observer").subscribe(topics.PERCEPT_TIME_SCHEDULED, on)
            session = _chat("voice-1", channel="voice", speaker="Soodeh", text="how many of these are there, exactly",
                            steps=6)
            cognition, outcome, _ = await _turn(
                h, session, {"voice-1": [LISTING, bg, {"text": "On it; I'll tell you when it's done."}],
                             "voice-1-h1": [ANALYSIS, {"text": "There are exactly 1000."}]},
                bars={"*": _bar("compute")}, chat_crews=True, until=lambda: seen)
        told = _said(cognition.calls["voice-1"][1])
        self.assertIn("Approach: background", told)
        self.assertIn('"background": true', told)
        self.assertIn("Compute it with run_analysis", told, "the member is told the method the job needs")
        self.assertEqual(session.approach, "background")
        self.assertEqual(outcome.result_summary, "On it; I'll tell you when it's done.")
        self.assertEqual(cognition.review_prompts, [], "the ack is not reviewed as if it were the result")
        self.assertIn("There are exactly 1000", seen[0].payload["label"])
        self.assertEqual(seen[0].payload["person"], "Soodeh")

    @run
    async def test_a_voice_job_that_is_not_sent_back_gets_the_order(self):
        _workbench_registered(self)
        async with Harness() as h:
            session = _chat("voice-1", channel="voice", speaker="Soodeh", text="x", steps=6)
            cognition, _, _ = await _turn(h, session, {"voice-1": [LISTING, LISTING, {"text": "about 30"}]},
                                          bars={"*": _bar("compute")}, chat_crews=True)
        early = str(cognition.calls["voice-1"][2].payload["messages"][-1]["content"])
        self.assertIn("spawn it in the background now", early)


class SupervisorOffIsTheTurnAsItWas(unittest.TestCase):
    @run
    async def test_off_sets_no_approach_and_writes_no_lesson(self):
        async with Harness() as h:
            cognition = Cognition(h.client("cognition"), {"chat-1": [LISTING, COUNTED]},
                                  bars={"*": _bar("compute")})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05,
                                   supervisor=False, chat_crews=True)
            session = _chat(text="x")
            await asyncio.wait_for(runner.run(session, user_text="x"), timeout=30)
            await cognition.stop(); await gx.stop()
            events = await h.ledger.read(supervisor.LESSONS_STREAM)
        self.assertEqual((cognition.bar_prompts, cognition.review_prompts, events), ([], [], []))
        self.assertEqual(session.approach, "direct")


if __name__ == "__main__":
    unittest.main()
