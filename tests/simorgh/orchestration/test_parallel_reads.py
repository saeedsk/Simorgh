"""Change H: independent read-only calls in one reply run together."""

import unittest

from simorgh.cognition.parser import OutputParser
from simorgh.cognition.service import _tool_instruction_block
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run

TWO_SEARCHES_THEN_A_PATCH = [
    {"tool": "web_search", "args": {"argument": "agent skills google"}},
    {"tool": "web_search", "args": {"argument": "agent skills microsoft"}},
    {"tool": "apply_source_patch", "args": {"argument": "x.py\nprint(1)"}},
]


class TheParserKeepsEveryCall(unittest.TestCase):
    def test_further_calls_are_parsed_in_order(self):
        text = "WEB_SEARCH: skills google\nWEB_SEARCH: skills microsoft\nREAD_FILE: docs/a.md\nextra prose"
        parsed = OutputParser().parse(text, {"kind": "markers", "markers": ("web_search", "read_file")})
        self.assertEqual([c["tool"] for c in parsed.tool_calls], ["web_search", "web_search", "read_file"])
        self.assertEqual([c["args"]["argument"] for c in parsed.tool_calls],
                         ["skills google", "skills microsoft", "docs/a.md"])
        self.assertEqual(parsed.tool_calls[0]["dropped_markers"], 2)

    def test_one_call_keeps_its_shape(self):
        parsed = OutputParser().parse("READ_FILE: a.py", {"kind": "markers", "markers": ("read_file",)})
        self.assertEqual(parsed.tool_calls, ({"tool": "read_file", "args": {"argument": "a.py"}},))


class TheModelIsToldOnlyWhenItIsOn(unittest.TestCase):
    def test_instruction(self):
        base = {"expected": "tool_calls", "tools": ["web_search", "read_file", "git_commit"]}
        self.assertNotIn("run together", _tool_instruction_block(base))
        on = _tool_instruction_block({**base, "parallel_tools": ["web_search", "read_file"], "max_parallel_tools": 4})
        self.assertIn("up to 4 at once: READ_FILE, WEB_SEARCH", on)
        self.assertNotIn("GIT_COMMIT, ", on.split("at once:")[1].split(".")[0])


class ReadsRunTogether(unittest.TestCase):
    async def _session(self, h, parallel: int):
        cognition = FakeCognition(h.client("cognition"), script=[
            {"text": "WEB_SEARCH: ...", "tool_calls": TWO_SEARCHES_THEN_A_PATCH},
            {"text": "Google and Microsoft both publish skills."},
        ])
        gx = FakeGuardianExecution(h.client("guardian"))
        await cognition.start()
        await gx.start()
        runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, parallel_read_tools=parallel)
        session = Session(task_id=f"t-par-{parallel}", kind="chat", mode="execute", profile=profiles.CHAT)
        outcome = await runner.run(session, user_text="who publishes skills?")
        await cognition.stop()
        await gx.stop()
        return outcome, session, cognition, gx

    @run
    async def test_on_two_searches_run_in_one_step_and_the_patch_waits(self):
        async with Harness() as h:
            outcome, session, cognition, gx = await self._session(h, 4)
            self.assertEqual(outcome.kind, "completed")
            self.assertEqual([p.payload["tool"] for p in gx.proposals], ["web_search", "web_search"])
            self.assertEqual(session.budget.steps_used, 2, "two model calls, not three")
            self.assertEqual([s.tool for s in session.steps[:2]], ["web_search", "web_search"])
            fed_back = cognition.calls[1].payload["messages"]
            text = "\n".join(m["content"] for m in fed_back)
            self.assertIn("Results of 2 lookups, run together", text)
            self.assertIn("[2] WEB_SEARCH: agent skills microsoft", text)
            self.assertIn("1 further tool marker, which were NOT run: only read-only lookups", text)
            self.assertEqual(cognition.calls[0].payload.get("max_parallel_tools"), 4)

    @run
    async def test_off_one_call_per_reply_as_before(self):
        async with Harness() as h:
            outcome, session, cognition, gx = await self._session(h, 1)
            self.assertEqual([p.payload["tool"] for p in gx.proposals], ["web_search"])
            text = "\n".join(m["content"] for m in cognition.calls[1].payload["messages"])
            self.assertIn("Result of web_search", text)
            self.assertIn("2 further tool markers, which were NOT run: one tool call per message.", text)
            self.assertNotIn("max_parallel_tools", cognition.calls[0].payload)


if __name__ == "__main__":
    unittest.main()
