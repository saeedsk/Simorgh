"""Crews, visible (stage 18 item 5).

A crew member is drawn under the task that spawned it, in the same ⏺/⎿
shape as a tool call: a branch when it starts, its progress hanging from
it, the branch again with its outcome. The live rows above the prompt show
the members under their running root instead of as running tasks of their
own, and nothing is wider than the terminal at any width.
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.evals.house.record import Printed, Record
from simorgh.evals.house.script import tui_is_sane
from simorgh.interface import crewview, panel
from simorgh.interface.activity import TaskBook
from simorgh.interface.config import Config
from simorgh.interface.render import display_width, terminal_width
from simorgh.interface.service import Service

ROOT = "root0001aaaa"
WIDTHS = (40, 60, 80, 120, 200)
LONG = ("compare the delivery dates, warranty terms and the total price including installation "
        "for the two dishwashers the household shortlisted last week")


def _at(columns: int):
    return mock.patch("shutil.get_terminal_size", return_value=os.terminal_size((columns, 24)))


def six_member_crew() -> list[tuple[str, dict]]:
    """Three under the root, two under the first, one under one of those."""
    spawned = [
        ("h1aaaaaaaaaa", ROOT, "research", "price of dishwasher A"),
        ("h2bbbbbbbbbb", ROOT, "research", "price of dishwasher B"),
        ("h3cccccccccc", ROOT, "browser", LONG),
        ("h4dddddddddd", "h1aaaaaaaaaa", "research", "retailer one"),
        ("h5eeeeeeeeee", "h1aaaaaaaaaa", "research", "retailer two"),
        ("h6ffffffffff", "h4dddddddddd", "browser", "the retailer's delivery page"),
    ]
    events = [(crewview.SPAWNED, {"crew_id": ROOT, "handle": h, "parent": p, "agent": a, "brief_ref": b,
                                  "report_policy": "progress", "budget": {"usd": 0.05}})
              for h, p, a, b in spawned]
    events += [
        (crewview.MESSAGE, {"crew_id": ROOT, "from": "h1aaaaaaaaaa", "to": ROOT, "kind": "progress",
                            "body": "found two retailers, checking a third", "seq": 1}),
        (crewview.MESSAGE, {"crew_id": ROOT, "from": "h3cccccccccc", "to": ROOT, "kind": "question",
                            "body": "which postcode should I check delivery for?", "seq": 2}),
        (crewview.MESSAGE, {"crew_id": ROOT, "from": "h1aaaaaaaaaa", "to": ROOT, "kind": "progress",
                            "body": LONG, "seq": 3}),
        (crewview.MESSAGE, {"crew_id": ROOT, "from": ROOT, "to": "h3cccccccccc", "kind": "answer",
                            "body": "95112", "seq": 4, "reply_to": 2}),
        (crewview.REPORT, {"crew_id": ROOT, "handle": "h2bbbbbbbbbb", "report": {
            "status": "ok", "summary": "B is $649 at two retailers", "steps": 4, "cost_usd": 0.012}}),
        (crewview.CANCEL, {"crew_id": ROOT, "handle": "h4dddddddddd", "reason": "the first retailer was enough"}),
        (crewview.REPORT, {"crew_id": ROOT, "handle": "h5eeeeeeeeee", "report": {
            "status": "failed", "summary": "the site refused the request", "steps": 2}}),
    ]
    return events


class TheFold(unittest.TestCase):
    def setUp(self):
        self.crew = crewview.Crew(crew_id=ROOT)
        for type_, payload in six_member_crew():
            self.crew.apply(type_, payload)

    def test_members_sit_under_their_parents(self):
        walk = [(m.handle[:2], d) for m, d in self.crew.walk()]
        self.assertEqual(walk, [("h1", 1), ("h4", 2), ("h6", 3), ("h5", 2), ("h2", 1), ("h3", 1)])

    def test_status_follows_what_each_member_said(self):
        status = {h[:2]: m.status for h, m in self.crew.members.items()}
        self.assertEqual(status["h1"], "running")      # it reported progress
        self.assertEqual(status["h2"], "done")         # its report said ok
        self.assertEqual(status["h3"], "running")      # asked, then was answered
        self.assertEqual(status["h4"], "cancelled")
        self.assertEqual(status["h5"], "failed")
        self.assertEqual(status["h6"], "cancelled", "a cancel cascades to what the member started")

    def test_a_question_waits_until_it_is_answered(self):
        crew = crewview.Crew(crew_id=ROOT)
        for type_, payload in six_member_crew()[:8]:   # spawns, a progress, the question
            crew.apply(type_, payload)
        self.assertEqual(crew.members["h3cccccccccc"].status, "waiting")
        self.assertEqual(crew.members["h3cccccccccc"].last_kind, "question")

    def test_the_report_carries_steps_and_cost(self):
        member = self.crew.members["h2bbbbbbbbbb"]
        self.assertEqual((member.steps, member.cost_usd), (4, 0.012))
        self.assertEqual(member.last, "B is $649 at two retailers")

    def test_a_status_event_on_the_stream_is_folded(self):
        self.crew.apply("crew.member.status", {"handle": "h1aaaaaaaaaa", "status": "blocked"})
        self.assertEqual(self.crew.members["h1aaaaaaaaaa"].status, "blocked")

    def test_an_unknown_event_is_skipped_not_refused(self):
        self.assertIsNone(self.crew.apply("crew.board", {"handle": "h1aaaaaaaaaa", "key": "k", "value": "v"}))

    def test_a_running_members_steps_and_cost_come_from_its_own_task_steps(self):
        book = crewview.CrewBook()
        for type_, payload in six_member_crew():
            book.on_event(type_, payload)
        book.on_step("h1aaaaaaaaaa", {"ok": True, "cost_usd": 0.004})
        book.on_step("h1aaaaaaaaaa", {"ok": None})            # in flight: not a step yet
        member = book.crews[ROOT].members["h1aaaaaaaaaa"]
        self.assertEqual((member.steps, member.cost_usd), (1, 0.004))
        self.assertTrue(book.is_member("h1aaaaaaaaaa"))
        self.assertFalse(book.is_member(ROOT))

    def test_a_body_in_a2a_parts_reads_as_its_text(self):
        self.assertEqual(crewview.message_text({"parts": [{"kind": "text", "text": "hi"},
                                                          {"kind": "data", "data": {"x": 1}}]}), "hi")


class TheLinesFitTheTerminal(unittest.TestCase):
    def test_no_tree_line_is_wider_than_the_terminal(self):
        crew = crewview.fold(ROOT, [SimpleNamespace(type=t, payload=p, ts=None) for t, p in six_member_crew()])
        for columns in WIDTHS:
            with _at(columns):
                lines = crewview.crew_tree(crew) + crewview.message_lines(crew)
                for member, depth in crew.walk():
                    lines.append(crewview.member_line(member, depth=depth, unicode=False))
                for line in lines:
                    self.assertLessEqual(display_width(line), terminal_width(), (columns, line))

    def test_a_branch_names_the_member_its_agent_and_its_outcome(self):
        crew = crewview.fold(ROOT, [SimpleNamespace(type=t, payload=p) for t, p in six_member_crew()])
        with _at(120):
            line = crewview.member_line(crew.members["h2bbbbbbbbbb"])
        self.assertTrue(line.lstrip().startswith("⏺ "), line)
        for word in ("research", "price of dishwasher B", "done", "4 steps", "$0.01", "[h2bbbbbb]"):
            self.assertIn(word, line)


class TheLiveRows(unittest.TestCase):
    def test_members_ride_under_their_root_not_as_running_tasks(self):
        book = TaskBook()
        book.on_created({"task_id": ROOT, "kind": "research", "origin": "human", "description": "dishwashers"})
        book.on_started(ROOT, now=0.0)
        crews = crewview.CrewBook()
        for type_, payload in six_member_crew():
            book.on_created({"task_id": payload.get("handle", "x"), "kind": "research", "origin": "research",
                             "description": "a member"})
            book.on_started(payload.get("handle", "x"), now=0.0)
            crews.on_event(type_, payload)
        with _at(100):
            text = panel.plain(panel.live_rows(book, now=5.0, crews=crews))
        self.assertIn("dishwashers", text)
        self.assertNotIn("more running", text, "members are not counted as running tasks")
        self.assertIn("price of dishwasher A", text)
        self.assertNotIn("price of dishwasher B", text, "a finished member drops out of the live rows")


class TheTranscript(unittest.TestCase):
    def setUp(self):
        self.service = Service.__new__(Service)
        self.printed: list[str] = []
        self.service._out = self.printed.append                       # noqa: SLF001
        self.service.config = Config(narrate=True, narrate_autonomous=True, unicode="auto")
        self.service._color = False                                   # noqa: SLF001
        self.service._tree_owner = ""                                 # noqa: SLF001
        self.service._live = SimpleNamespace(enabled=False)           # noqa: SLF001
        self.service._pending_turns = {}                              # noqa: SLF001
        self.service._watched_tasks = set()                           # noqa: SLF001
        self.service._book = TaskBook()                               # noqa: SLF001
        self.service._crews = crewview.CrewBook()                     # noqa: SLF001
        self.service._crew_branch_owner = ""                          # noqa: SLF001
        self.service._crew_last_note = {}                             # noqa: SLF001
        self.service._book.on_created({"task_id": ROOT, "kind": "research", "origin": "human",  # noqa: SLF001
                                       "description": "which dishwasher should we buy"})

    async def _play(self) -> None:
        for type_, payload in six_member_crew():
            await self.service._on_crew_event(Message.new(type_, source="test", payload=payload))  # noqa: SLF001

    def test_the_tree_holds_the_terminal_grammar_with_a_six_member_crew(self):
        import asyncio

        for columns in (80, 200):
            self.printed.clear()
            self.service._tree_owner = ""                             # noqa: SLF001
            self.service._crews = crewview.CrewBook()                 # noqa: SLF001
            with _at(columns):
                asyncio.run(self._play())
            record = Record(printed=[Printed(text=line, at=1.0) for line in self.printed])
            verdict = tui_is_sane(width=columns).check(record, 0.0)
            self.assertEqual(verdict, "", "\n".join(self.printed))
            self.assertIn("which dishwasher", self.printed[0], "the root is named before its first branch")
            self.assertEqual(sum(1 for line in self.printed if "[h" in line and "⏺" in line) >= 6, True)

    def test_progress_hangs_from_its_own_members_branch(self):
        import asyncio

        with _at(120):
            asyncio.run(self._play())
        for index, line in enumerate(self.printed):
            if "⎿" in line and "found two retailers" in line:
                self.assertIn("[h1aaaaaa]", self.printed[index - 1], "the corner hangs under its own branch")
                break
        else:
            self.fail("\n".join(self.printed))
        self.assertTrue(any("asks: which postcode" in line for line in self.printed), self.printed)

    def test_a_crew_under_a_root_this_session_never_saw_is_named_by_the_crew(self):
        import asyncio

        self.service._book = TaskBook()                               # noqa: SLF001
        with _at(120):
            asyncio.run(self._play())
        self.assertTrue(self.printed[0].startswith("⏺ crew root0001"), self.printed[0])
        self.assertFalse(any("? · ?" in line or "(no description)" in line for line in self.printed))

    def test_a_crew_message_kind_the_tree_does_not_draw_prints_nothing(self):
        import asyncio

        asyncio.run(self.service._on_crew_event(Message.new(crewview.SPAWNED, source="test", payload=six_member_crew()[0][1])))  # noqa: SLF001
        before = len(self.printed)
        asyncio.run(self.service._on_crew_event(Message.new(crewview.MESSAGE, source="test", payload={  # noqa: SLF001
            "crew_id": ROOT, "from": ROOT, "to": "h1aaaaaaaaaa", "kind": "steer", "body": "try retailer three",
            "seq": 9})))
        self.assertEqual(len(self.printed), before)


class TheTopicsAreTheContractsOwn(unittest.TestCase):
    def test_the_fold_reads_the_catalogue_values(self):
        self.assertEqual((crewview.SPAWNED, crewview.MESSAGE, crewview.REPORT, crewview.CANCEL),
                         (topics.CREW_SPAWNED, topics.CREW_MESSAGE, topics.CREW_REPORT, topics.CREW_CANCEL))
