import unittest

from src.memory.long_term import InMemoryStore
from src.orchestrator.reflection import TAKEAWAY_KIND, Outcome, OutcomeLog, ReflectionAgent


class TestOutcomeLog(unittest.TestCase):
    def test_record_then_recent_round_trips(self):
        log = OutcomeLog(InMemoryStore())
        log.record(Outcome(agent="logic", request_text="hi", output="hello", succeeded=True))

        outcomes = log.recent()

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].agent, "logic")
        self.assertTrue(outcomes[0].succeeded)

    def test_recent_returns_most_recent_first(self):
        log = OutcomeLog(InMemoryStore())
        log.record(Outcome(agent="logic", request_text="a", output="1", succeeded=True))
        log.record(Outcome(agent="logic", request_text="b", output="2", succeeded=True))

        outcomes = log.recent()

        self.assertEqual([o.output for o in outcomes], ["2", "1"])


class TestReflectionAgent(unittest.TestCase):
    def _log_with(self, agent: str, successes: int, failures: int) -> OutcomeLog:
        log = OutcomeLog(InMemoryStore())
        for _ in range(successes):
            log.record(Outcome(agent=agent, request_text="x", output="ok", succeeded=True))
        for _ in range(failures):
            log.record(Outcome(agent=agent, request_text="x", output="bad", succeeded=False))
        return log

    def test_no_proposal_below_min_samples(self):
        log = self._log_with("skills", successes=1, failures=3)
        agent = ReflectionAgent(log, min_samples=5)

        self.assertEqual(agent.reflect(), [])

    def test_no_proposal_when_failure_rate_below_threshold(self):
        log = self._log_with("skills", successes=9, failures=1)
        agent = ReflectionAgent(log, concern_threshold=0.3, min_samples=5)

        self.assertEqual(agent.reflect(), [])

    def test_proposal_generated_when_failure_rate_crosses_threshold(self):
        log = self._log_with("skills", successes=5, failures=5)
        agent = ReflectionAgent(log, concern_threshold=0.3, min_samples=5)

        proposals = agent.reflect()

        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].subject, "skills")
        self.assertEqual(proposals[0].evidence_count, 10)
        self.assertIn("skills", proposals[0].rationale)

    def test_creator_correction_counts_as_trouble_even_if_succeeded(self):
        log = OutcomeLog(InMemoryStore())
        for _ in range(5):
            log.record(
                Outcome(agent="logic", request_text="x", output="ok", succeeded=True)
            )
        for _ in range(5):
            log.record(
                Outcome(
                    agent="logic",
                    request_text="x",
                    output="ok but wrong tone",
                    succeeded=True,
                    corrected_by_creator=True,
                )
            )
        agent = ReflectionAgent(log, concern_threshold=0.3, min_samples=5)

        proposals = agent.reflect()

        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].subject, "logic")

    def test_only_flags_the_agent_that_crosses_threshold(self):
        log = OutcomeLog(InMemoryStore())
        for _ in range(10):
            log.record(Outcome(agent="logic", request_text="x", output="ok", succeeded=True))
        for _ in range(5):
            log.record(Outcome(agent="skills", request_text="x", output="bad", succeeded=False))
        for _ in range(5):
            log.record(Outcome(agent="skills", request_text="x", output="ok", succeeded=True))
        agent = ReflectionAgent(log, concern_threshold=0.3, min_samples=5)

        proposals = agent.reflect()

        self.assertEqual([p.subject for p in proposals], ["skills"])


class TestReflectOnOutcome(unittest.TestCase):
    def test_successful_outcome_produces_no_takeaway(self):
        agent = ReflectionAgent(OutcomeLog(InMemoryStore()))
        outcome = Outcome(agent="logic", request_text="hi", output="hello", succeeded=True)

        self.assertIsNone(agent.reflect_on_outcome(outcome))

    def test_failed_outcome_produces_a_concrete_takeaway(self):
        agent = ReflectionAgent(OutcomeLog(InMemoryStore()))
        outcome = Outcome(
            agent="logic",
            request_text="fetch site",
            output="",
            succeeded=False,
            note="ValueError('boom')",
        )

        proposal = agent.reflect_on_outcome(outcome)

        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.subject, "logic")
        self.assertIn("boom", proposal.rationale)
        self.assertIn("patch src/agents/logic/base.py", proposal.rationale)

    def test_corrected_outcome_produces_a_takeaway_even_though_it_succeeded(self):
        agent = ReflectionAgent(OutcomeLog(InMemoryStore()))
        outcome = Outcome(
            agent="logic",
            request_text="hi",
            output="wrong tone",
            succeeded=True,
            corrected_by_creator=True,
        )

        proposal = agent.reflect_on_outcome(outcome)

        self.assertIsNotNone(proposal)
        self.assertIn("corrected", proposal.rationale)

    def test_unknown_agent_gets_a_generic_suggestion_not_a_crash(self):
        agent = ReflectionAgent(OutcomeLog(InMemoryStore()))
        outcome = Outcome(
            agent="some_future_agent", request_text="x", output="", succeeded=False
        )

        proposal = agent.reflect_on_outcome(outcome)

        self.assertIsNotNone(proposal)
        self.assertIn("needs a human look", proposal.rationale)

    def test_takeaway_is_durably_recorded_when_store_given(self):
        store = InMemoryStore()
        agent = ReflectionAgent(OutcomeLog(store), store=store)
        outcome = Outcome(agent="logic", request_text="x", output="", succeeded=False)

        agent.reflect_on_outcome(outcome)

        records = store.query(kind=TAKEAWAY_KIND)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].metadata["agent"], "logic")

    def test_no_store_means_no_durable_record_but_still_returns_a_proposal(self):
        agent = ReflectionAgent(OutcomeLog(InMemoryStore()))
        outcome = Outcome(agent="logic", request_text="x", output="", succeeded=False)

        proposal = agent.reflect_on_outcome(outcome)

        self.assertIsNotNone(proposal)


if __name__ == "__main__":
    unittest.main()
