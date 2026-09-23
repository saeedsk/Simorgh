"""You can ask reflection what it has noticed, before it acts on it.

`reflect.review.request` had a subscriber in Growth's monitors -- which
answers with the patterns it currently sees over a window -- and no
publisher anywhere (`tools/scan_half_wired.py`, 2026-09-23). The answer
existed and there was no way to ask the question.

It earns its place now. The creator, seeing reflection's own tasks
queued, 2026-09-22: "I don't like the fact sim is scheduling nonsense".
This is how to look first.
"""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.interface import dispatch
from simorgh.interface.parser import parse


class _Clock:
    def now(self):
        return 0.0


class _Bus:
    def __init__(self, reply):
        self.requested: list[tuple[str, dict]] = []
        self._reply = reply

    def new(self, type, payload, **_kw):
        return _Message(type, payload)

    async def request(self, message, timeout=None):
        self.requested.append((message.type, message.payload))
        return _Message(topics.REFLECT_REVIEW_REPLY, self._reply)

    async def request_or_error(self, message, timeout=None):
        return await self.request(message, timeout=timeout)


class _Message:
    def __init__(self, type, payload):
        self.type, self.payload = type, payload


PATTERNS = {"patterns": [{"kind": "failure_rate", "rate": 0.86,
                          "proposal": "'research' tasks failed 6/7 recent outcomes (86%) -- worth reviewing."}],
            "takeaways": []}


class ReflectionCanBeAskedWhatItSees(unittest.IsolatedAsyncioTestCase):
    async def _run(self, line: str, reply=PATTERNS):
        bus = _Bus(reply)
        outcome = await dispatch.dispatch(parse(line), bus=bus, clock=_Clock(), session_id="s",
                                          vitals=None, ledger=None)
        return bus, outcome

    async def test_it_asks_the_topic_nothing_used_to_publish(self):
        bus, outcome = await self._run("alerts review")
        self.assertEqual([t for t, _ in bus.requested], [topics.REFLECT_REVIEW_REQUEST])
        self.assertIn("86%", outcome.text)
        self.assertIn("research", outcome.text)

    async def test_a_window_in_hours_is_passed_on(self):
        bus, _outcome = await self._run("alerts review 6h")
        self.assertEqual(bus.requested[0][1], {"window_seconds": 6 * 3600.0})

    async def test_nothing_noticed_says_so_plainly(self):
        _bus, outcome = await self._run("alerts review", reply={"patterns": [], "takeaways": []})
        self.assertIn("no pattern", outcome.text)

    async def test_the_answer_says_what_happens_next(self):
        """A pattern becomes a research task, not a patch -- the thing
        the creator wanted to be sure of."""
        _bus, outcome = await self._run("alerts review")
        self.assertIn("research task, not a patch", outcome.text)


if __name__ == "__main__":
    unittest.main()
