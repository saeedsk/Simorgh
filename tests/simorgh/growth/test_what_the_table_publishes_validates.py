"""What the competence table publishes must pass the bus.

Live, 2026-09-21, in the creator's own session, one traceback per
completed task:

    ContractError: learn.competence.updated: $.payload.samples:
        expected type integer, got float
    ContractError: self.estimate.reply: $.payload:
        matched none of 2 anyOf branches

Both were mine, from the same evening's work. Exponential forgetting
made `samples` an effective count -- 1.9999999 for two outcomes
seconds apart -- and expected calibration error added `ece` to an
estimate. The wire said `Int` and knew nothing about `ece`, so every
publish was rejected.

The module tier was green throughout. It tests the table, and the
table was right; nothing took what it produces and ran it past the
schema that carries it. That is this project's own bug shape, and
this file is the join that was missing.
"""

import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message, validate
from simorgh.growth.estimate.competence import CompetenceTable

T0 = 1_700_000_000.0


def _fed() -> CompetenceTable:
    """A table with real, forgotten, calibration-carrying history."""
    from simorgh.contracts.envelope import Event

    table = CompetenceTable()
    for i in range(12):
        table.apply(Event(stream="learn:outcomes", type="outcome", ts=T0 + i * 3.0,
                          trace_id="", causation_id=None,
                          payload={"task_type": "chat", "succeeded": i % 3 != 0,
                                   "strategy": "together:draft", "stated_confidence": 0.9}))
    return table


class WhatTheEstimateCarries(unittest.TestCase):
    def test_it_passes_its_own_schema(self):
        estimate = _fed().estimate("chat")
        validate(Message.new(topics.SELF_ESTIMATE_REPLY, source="growth",
                             correlation_id="c", payload=estimate))

    def test_samples_really_is_fractional(self):
        """If this ever becomes a whole number the test above stops
        proving anything."""
        self.assertNotEqual(_fed().estimate("chat")["samples"] % 1, 0.0)

    def test_and_it_carries_the_calibration_error(self):
        self.assertIn("ece", _fed().estimate("chat"))

    def test_with_a_strategy_too(self):
        estimate = _fed().estimate("chat", strategy="together:draft")
        validate(Message.new(topics.SELF_ESTIMATE_REPLY, source="growth",
                             correlation_id="c", payload=estimate))


class WhatTheOutcomeRecorderPublishes(unittest.TestCase):
    def test_competence_updated_takes_an_effective_count(self):
        table = _fed()
        validate(Message.new(topics.LEARN_COMPETENCE_UPDATED, source="growth", payload={
            "task_type": "chat", "success_rate": 0.5,
            "calibration": table.calibration("chat"),
            "samples": table.samples("chat"),
        }))

    def test_a_plain_integer_still_validates(self):
        """Older producers and replayed history send whole numbers."""
        validate(Message.new(topics.LEARN_COMPETENCE_UPDATED, source="growth", payload={
            "task_type": "chat", "success_rate": 0.5, "calibration": 0.5, "samples": 2,
        }))

    def test_the_strategy_suggestion_too(self):
        validate(Message.new(topics.LEARN_STRATEGY_SUGGEST_REPLY, source="growth",
                             correlation_id="c",
                             payload={"success_rate": 0.5, "samples": _fed().samples("chat")}))


if __name__ == "__main__":
    unittest.main()
