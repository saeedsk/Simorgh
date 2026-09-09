"""`Scheduler.dispatch_ready` -- which ready tasks actually get offered.

A pure unit: a fake store, a fake bus that records what was published.
"""

from __future__ import annotations

import unittest

from simorgh.planning.config import Config
from simorgh.planning.scheduler import Scheduler

class TestAutoOffActuallyStopsAutonomousWork(unittest.IsolatedAsyncioTestCase):
    """`auto off` is a `scope="autonomous"` pause: the system stays
    RUNNING, so every consumer keying off the whole-system state carries
    on regardless.

    Live-caught 2026-09-09 -- the creator typed `auto off` and then
    watched curiosity-origin patch tasks keep being offered, claimed and
    run. Curiosity itself had stopped generating new candidates (it is
    the one subsystem that reads `autonomous_paused`), but the backlog
    already in the store kept executing, which is not what anyone means
    by "off". `system.state.changed` had carried `autonomous_paused` all
    along and nothing read it.
    """

    def _scheduler(self, sent):
        class _Task:
            def __init__(self, origin):
                self.origin = origin
                self.id = origin
                self.kind = "patch"
                self.created_at = 0.0
                self.updated_at = 0.0

        class _Store:
            def ready(self, limit=1000):
                return [_Task("curiosity"), _Task("human"), _Task("reflection"), _Task("project")]

        class _Bus:
            source = "planning"

            async def publish(self, message):
                sent.append(message.payload["task_id"])

        class _Clock:
            def now(self):
                return 0.0

        return Scheduler(_Store(), _Bus(), _Clock(), source="planning",
                         autonomous_origins=Config().autonomous_origins)

    async def test_autonomous_origins_are_not_offered_while_paused(self):
        sent = []
        scheduler = self._scheduler(sent)
        scheduler.autonomous_paused = True
        await scheduler.dispatch_ready()
        self.assertEqual(sent, ["human"])

    async def test_everything_is_offered_again_once_resumed(self):
        sent = []
        scheduler = self._scheduler(sent)
        scheduler.autonomous_paused = True
        await scheduler.dispatch_ready()
        sent.clear()
        scheduler.autonomous_paused = False
        await scheduler.dispatch_ready()
        self.assertIn("curiosity", sent)
        self.assertIn("human", sent)

    async def test_a_human_task_still_runs_while_autonomy_is_paused(self):
        # The whole point of a SCOPED pause: stop Sim's own ideas, keep
        # doing what the person in front of it just asked for.
        sent = []
        scheduler = self._scheduler(sent)
        scheduler.autonomous_paused = True
        await scheduler.dispatch_ready()
        self.assertIn("human", sent)

    async def test_a_full_pause_still_stops_everything(self):
        sent = []
        scheduler = self._scheduler(sent)
        scheduler.paused = True
        await scheduler.dispatch_ready()
        self.assertEqual(sent, [])
