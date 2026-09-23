"""A research task's answer reaches Planning.

`research.finding.recorded` had a topic, a message type, a JSON schema,
a `Consumes` row in planning/CONTRACT.md and a handler --
`_on_research_finding` -> `on_research_follow_up`, which creates a patch
task SCOPED to the one file the finding names -- and no publisher
anywhere in `simorgh/`. Found by `tools/scan_half_wired.py`, 2026-09-23.

So every research task Sim has ever run ended as prose in a ledger
stream, and the one route from "I found out what is wrong" to "fix that
file" had never once been travelled. It matters more since the same
day: a mined failure pattern now becomes a research task rather than an
unscoped patch, precisely because this door was supposed to exist.
"""

from __future__ import annotations

import unittest
from unittest import mock

from simorgh.contracts import topics
from simorgh.orchestration.api import Outcome
from simorgh.orchestration.session import SessionRunner

ANSWER = """The dispatch window counted tasks it could not offer, so a queue of
benchmark cases starved the household's own work.

FOLLOW_UP: simorgh/planning/scheduler.py :: count offerable work, not the first five ready
"""


class _Ledger:
    def __init__(self):
        self.blobs: list[bytes] = []

    async def put_blob(self, body, content_type=""):
        self.blobs.append(body)
        return f"blob:{len(self.blobs)}"


class _Profile:
    def __init__(self, scaffold):
        self.scaffold = scaffold
        self.name = scaffold
        self.tools = ()


class _Session:
    def __init__(self, scaffold="research"):
        self.task_id = "t-research"
        self.profile = _Profile(scaffold)


class AResearchFindingIsWrittenDown(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runner = SessionRunner.__new__(SessionRunner)
        self.runner._ledger = _Ledger()                     # noqa: SLF001
        self.published: list[tuple[str, dict]] = []

        async def _publish(_session, topic, payload):
            self.published.append((topic, payload))

        self.runner._publish = _publish                     # noqa: SLF001

    async def _record(self, session, outcome):
        await self.runner._record_finding(session, outcome)  # noqa: SLF001
        return self.published

    async def test_the_answer_is_published_with_its_follow_up(self):
        await self._record(_Session(), Outcome("completed", result_summary=ANSWER))
        self.assertEqual(len(self.published), 1)
        topic, payload = self.published[0]
        self.assertEqual(topic, topics.RESEARCH_FINDING_RECORDED)
        self.assertEqual(payload["task_id"], "t-research")
        self.assertTrue(payload["finding_ref"], "the answer itself is kept")
        self.assertEqual(payload["follow_up"]["subject"], "simorgh/planning/scheduler.py")
        self.assertIn("offerable", payload["follow_up"]["description"])

    async def test_an_answer_with_no_follow_up_is_still_recorded(self):
        """"Nothing here needs changing" is a good answer, and the
        finding is still worth keeping."""
        await self._record(_Session(), Outcome("completed", result_summary="Nothing systematic; the two failures were unrelated."))
        _topic, payload = self.published[0]
        self.assertNotIn("follow_up", payload, "no file is named, so no patch is scoped")
        self.assertTrue(payload["finding_ref"])

    async def test_a_path_that_escapes_the_repo_is_not_a_subject(self):
        await self._record(_Session(), Outcome("completed", result_summary="FOLLOW_UP: ../../etc/passwd :: no"))
        _topic, payload = self.published[0]
        self.assertNotIn("follow_up", payload)

    async def test_only_a_research_task_records_a_finding(self):
        for scaffold in ("chat", "patch", "skill"):
            self.published.clear()
            await self._record(_Session(scaffold), Outcome("completed", result_summary=ANSWER))
            self.assertEqual(self.published, [], scaffold)

    async def test_a_task_that_did_not_complete_records_nothing(self):
        for kind in ("blocked", "failed", "paused"):
            self.published.clear()
            await self._record(_Session(), Outcome(kind, result_summary=ANSWER))
            self.assertEqual(self.published, [], kind)


if __name__ == "__main__":
    unittest.main()
