import unittest

from simorgh.contracts.envelope import Event
from simorgh.learning.competence import CompetenceTable
from simorgh.learning.config import Config
from simorgh.learning.strategy import build_reply


def _outcome(seq, task_type, succeeded, strategy):
    return Event(stream="learn:outcomes", type="outcome", ts=1.0, trace_id="t", causation_id=None,
                 payload={"task_type": task_type, "succeeded": succeeded, "weight": 1.0,
                          "verdict": "pass" if succeeded else "fail", "cost_usd": 0.0,
                          "duration_s": 0.0, "strategy": strategy}, seq=seq)


class TestBuildReply(unittest.TestCase):
    def test_no_samples_returns_neutral_reply_without_a_strategy(self):
        reply = build_reply("patch", competence=CompetenceTable(), config=Config())
        self.assertEqual(reply["success_rate"], 0.5)
        self.assertEqual(reply["samples"], 0)
        self.assertNotIn("strategy", reply)  # absence *is* the floor signal (real catalog has no floor field)

    def test_with_samples_returns_the_best_strategy(self):
        table = CompetenceTable()
        for i in range(5):
            table.apply(_outcome(i + 1, "patch", True, "claude_code_cli:patch:search_replace"))
        reply = build_reply("patch", competence=table, config=Config())

        self.assertIn("strategy", reply)
        self.assertEqual(reply["strategy"]["provider"], "claude_code_cli")
        self.assertEqual(reply["samples"], 5)
        self.assertGreater(reply["success_rate"], 0.5)

    def test_reply_validates_against_the_real_schema(self):
        from simorgh.contracts.envelope import Message, validate

        table = CompetenceTable()
        table.apply(_outcome(1, "patch", True, "gemini:patch:full_rewrite"))
        payload = build_reply("patch", competence=table, config=Config())
        msg = Message.new("learn.strategy.suggest.reply", source="learning", payload=payload,
                          correlation_id="req-1")
        validate(msg)  # raises on schema mismatch


if __name__ == "__main__":
    unittest.main()
