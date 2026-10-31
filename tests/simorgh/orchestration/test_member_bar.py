"""The supervisor's closed loop with crew members (2026-10-30).

The creator, after five research helpers were refused round after round
("2 items, one dated by URL alone", "snippets only") and the sixth was
refused at the crew cap: "wouldn't it be more effective if bar raiser tells
the agents what it is that it looking for, and the standard it [expects];
also if bar raiser don't accept the result, there should be closed loop
feedback to agent so agent knows what was missing to go and improve it".

So: a member is told its bar and the standard up front; its answer is
reviewed before it reports and sent back to it below the bar; a parent can
reopen a finished member with what is missing, under the same handle; and
the parent's review reads the members' reports in full."""

from __future__ import annotations

import json
import unittest

from simorgh.orchestration import supervisor
from simorgh.orchestration.config import Config
from simorgh.orchestration.crew import Crew, CrewMember, Report

from .harness import Harness, run
from .test_code_first import PARTS, _bar, _call, _chat, _said, _turn

BELOW = json.dumps({"verdict": "below_bar", "unmet": ["Monday has no dated item"], "principle": "Dive Deep",
                    "feedback": "Monday rests on a snippet.", "next": "read a Monday page in full"})
MEETS = json.dumps({"verdict": "meets_bar"})


class TheBarGoesWithTheMember(unittest.TestCase):
    def test_a_part_brief_carries_the_measure_and_the_standard(self):
        part = {"brief": "Monday's moves", "criterion": "done when: three dated items -- measured by: a page date",
                "approach": "direct"}
        brief = supervisor.part_brief(part)
        self.assertIn("three dated items (measured by: a page date)", brief)
        self.assertIn(supervisor.MEMBER_STANDARD, brief)

    def test_a_reworded_brief_finds_its_part(self):
        split = [{"brief": "semiconductor stocks this week"}, {"brief": "mega-cap tech stocks this week"},
                 {"brief": "tech ETFs this week"}]
        self.assertEqual(supervisor.match_part("look at ETFs that track tech", split, []), 2)
        # A brief like none of the parts left takes the first one left.
        self.assertEqual(supervisor.match_part("quarterly figures", split, [2]), 0)
        self.assertIsNone(supervisor.match_part("anything", split, [0, 1, 2]))

    @run
    async def test_a_spawned_part_is_held_to_its_own_criterion(self):
        member = [{"tool_calls": [_call("report_progress", text="halfway")]}, {"text": "first source: 4 items"}]
        script = {"chat-1": [{"tool_calls": [_call("report_progress", text="x")]},
                             {"tool_calls": [_call("spawn", i, agent="research", brief=b) for i, b in enumerate(PARTS)]},
                             {"tool_calls": [_call("await_agents", mode="all", timeout_s=20)]},
                             {"text": "all three"}],
                  "chat-1-h1": member, "chat-1-h2": member, "chat-1-h3": member}
        async with Harness() as h:
            cognition, _, _ = await _turn(h, _chat(text="compare the three sources"), script,
                                          bars={"*": _bar("parallel", split=PARTS)}, chat_crews=True)
        first = _said(cognition.calls["chat-1-h1"][0])
        self.assertIn("Your supervisor's bar for this part", first)
        self.assertIn("(measured by: a report)", first)
        member_reviews = [p for p in cognition.review_prompts if "Expected approach" not in p]
        self.assertEqual(len(member_reviews), 3)
        self.assertTrue(all("is answered -- measured by: a report" in p for p in member_reviews))


def _one_member(member_script, *, parent_tail=None):
    parent = [{"tool_calls": [_call("spawn", agent="research", brief="find Monday's moves")]},
              {"tool_calls": [_call("await_agents", mode="all", timeout_s=20)]}]
    parent += parent_tail or [lambda m: {"text": "parent: " + _said(m).split("research) ok")[-1][:400]}]
    return {"chat-1": parent, "chat-1-h1": member_script}


class AMemberBelowTheBarIsSentBack(unittest.TestCase):
    @run
    async def test_the_feedback_reaches_the_member_and_its_better_answer_is_the_report(self):
        member = [{"tool_calls": [_call("report_progress", text="searched")]}, {"text": "Monday: one snippet"},
                  {"tool_calls": [_call("report_progress", text="read the page")]},
                  {"text": "Monday: three dated items"}]
        async with Harness() as h:
            session = _chat(text="what moved on Monday")
            cognition, outcome, _ = await _turn(h, session, _one_member(member), bars={"*": _bar("direct")},
                                                reviews=[BELOW, MEETS, MEETS], chat_crews=True)
        sent_back = str(cognition.calls["chat-1-h1"][2].payload["messages"][-1]["content"])
        self.assertIn("BELOW THE BAR (Dive Deep)", sent_back)
        self.assertIn("read a Monday page in full", sent_back)
        self.assertIn(f"Review 1 of {supervisor.MEMBER_REVIEW_ROUNDS}", sent_back)
        self.assertIn("three dated items", outcome.result_summary)
        self.assertNotIn("Supervisor's review of this report", outcome.result_summary)

    @run
    async def test_out_of_rounds_the_report_goes_up_with_what_is_missing(self):
        rounds = supervisor.MEMBER_REVIEW_ROUNDS
        member = []
        for i in range(rounds + 1):
            member += [{"tool_calls": [_call("report_progress", i, text=f"try {i}")]}, {"text": f"Monday: try {i}"}]
        async with Harness() as h:
            cognition, outcome, _ = await _turn(h, _chat(text="what moved on Monday"), _one_member(member),
                                                bars={"*": _bar("direct")}, reviews=[BELOW] * (rounds + 1) + [MEETS],
                                                chat_crews=True)
        self.assertIn(f"Monday: try {rounds}", outcome.result_summary)
        self.assertIn("Supervisor's review of this report: BELOW THE BAR", outcome.result_summary)
        self.assertIn("read a Monday page in full", outcome.result_summary)
        self.assertEqual(len(cognition.review_prompts), rounds + 2, "each round, the last recorded, the parent's")

    @run
    async def test_switched_off_a_member_is_not_reviewed(self):
        member = [{"tool_calls": [_call("report_progress", text="x")]}, {"text": "Monday: one snippet"}]
        async with Harness() as h:
            cognition, outcome, _ = await _turn(h, _chat(text="what moved on Monday"), _one_member(member),
                                                bars={"*": _bar("direct")}, chat_crews=True, supervisor_members=False)
        self.assertEqual(len(cognition.review_prompts), 1, "only the parent's answer")
        self.assertNotIn(supervisor.MEMBER_STANDARD, _said(cognition.calls["chat-1-h1"][0]))
        self.assertTrue(Config().supervisor_members)
        self.assertFalse(Config.from_mapping({"supervisor_members": False}).supervisor_members)


class AParentReopensAFinishedMember(unittest.TestCase):
    @run
    async def test_send_agent_to_a_finished_member_reopens_it_with_its_context(self):
        member = [{"text": "Monday: one snippet"}, {"text": "Monday: three dated items"}]
        tail = [{"tool_calls": [_call("send_agent", to="chat-1-h1", text="Monday needs dated items")]},
                {"tool_calls": [_call("await_agents", 2, mode="all", timeout_s=20)]},
                lambda m: {"text": _said(m)[-300:]}]
        async with Harness() as h:
            session = _chat(text="what moved on Monday")
            cognition, outcome, runner = await _turn(h, session, _one_member(member, parent_tail=tail),
                                                     bars={"*": json.dumps({"criteria": []})}, chat_crews=True)
        again = cognition.calls["chat-1-h1"][1].payload["messages"]
        said = "\n".join(str(m.get("content")) for m in again)
        self.assertIn("Monday: one snippet", said, "it goes on from what it found")
        self.assertIn("Monday needs dated items", said)
        self.assertEqual(said.count("Monday needs dated items"), 1, "told once, not again from its inbox")
        self.assertIn("three dated items", outcome.result_summary)
        reopened = [s for s in session.steps if s.tool == "send_agent"]
        self.assertTrue(reopened and reopened[0].ok)
        self.assertEqual(len([s for s in session.steps if s.tool == "spawn"]), 1, "no new member")

    @run
    async def test_a_member_is_reopened_at_most_max_reopens_times(self):
        n = supervisor.MAX_REOPENS
        member = [{"text": f"answer {i}"} for i in range(n + 2)]
        tail = []
        for i in range(n + 1):
            tail += [{"tool_calls": [_call("send_agent", i, to="chat-1-h1", text=f"more {i}")]},
                     {"tool_calls": [_call("await_agents", 10 + i, mode="all", timeout_s=20)]}]
        tail.append({"text": "done"})
        async with Harness() as h:
            session = _chat(text="x", steps=20)
            await _turn(h, session, _one_member(member, parent_tail=tail),
                        bars={"*": json.dumps({"criteria": []})}, chat_crews=True)
        sends = [s for s in session.steps if s.tool == "send_agent"]
        self.assertEqual([s.ok for s in sends], [True] * n + [False])

    @run
    async def test_a_spawn_refused_at_the_cap_names_send_agent(self):
        parent = [{"tool_calls": [_call("spawn", agent="research", brief="find Monday's moves")]},
                  {"tool_calls": [_call("await_agents", mode="all", timeout_s=20)]},
                  {"tool_calls": [_call("spawn", 2, agent="research", brief="find Monday's moves again")]},
                  {"text": "done"}]
        async with Harness() as h:
            session = _chat(text="x")
            await _turn(h, session, {"chat-1": parent, "chat-1-h1": [{"text": "Monday: one snippet"}]},
                        bars={"*": json.dumps({"criteria": []})}, chat_crews=True, crew_max_members=1)
        refused = [s for s in session.steps if s.tool == "spawn" and not s.ok]
        self.assertTrue(refused)
        self.assertIn("send_agent", refused[0].summary + str(getattr(refused[0], "detail", "")))


class TheCrewRecordsAReopen(unittest.TestCase):
    @run
    async def test_a_reopened_member_is_running_again_after_a_restart(self):
        events = []

        async def append(type_, payload):
            events.append(type("E", (), {"type": type_, "payload": payload})())

        crew = Crew("crew-1", append=append)
        crew.members["h1"] = CrewMember(handle="h1", agent="research", parent="root")
        await crew.file_report("h1", Report(status="ok", summary="thin"))
        await crew.reopen("h1")
        self.assertEqual((crew.members["h1"].status, crew.members["h1"].report), ("running", None))
        folded = Crew.fold("crew-1", [type("E", (), {"type": "crew.spawned", "payload": {
            "handle": "h1", "agent": "research", "parent": "root"}})()] + events)
        self.assertEqual(folded.members["h1"].status, "running")
        self.assertIsNone(folded.members["h1"].report)
        self.assertEqual(folded.members["h1"].reopened, 1)


class TheParentsReviewReadsTheReports(unittest.TestCase):
    def test_reports_go_in_full_and_the_review_says_reopen_not_respawn(self):
        member = CrewMember(handle="h1", agent="research", parent="root")
        member.report = Report(status="ok", summary="Monday: " + "x" * 900)
        reports = supervisor.reports_text([member])
        self.assertIn("x" * 900, reports)
        prompt = supervisor.review_prompt(request="r", criteria=["done when: a"], steps=[], answer="a",
                                          reports=reports)
        self.assertIn("The helpers' reports, in full", prompt)
        self.assertIn("send_agent to that helper's handle", prompt)
        self.assertNotIn("send_agent", supervisor.review_prompt(request="r", criteria=[], steps=[], answer="a"))


if __name__ == "__main__":
    unittest.main()
