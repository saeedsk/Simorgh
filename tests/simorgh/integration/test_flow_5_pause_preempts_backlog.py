"""Flow 5 (docs/blueprint/02 section 5): with a large backlog of queued
work, `system.pause` (priority 9) is delivered ahead of it, and once the
bus is paused no further *commands* are dispatched while events still
flow -- the transport half of corrigibility."""

import asyncio
import unittest

from simorgh.contracts import topics

from tests.simorgh.helpers import make_message

from tests.simorgh.bus.harness import Harness, for_each_backend


class TestPausePreemptsBacklog(unittest.TestCase):
    @for_each_backend
    async def test_pause_overtakes_a_backlog_and_halts_commands(self, h: Harness):
        interface, guardian, execution = h.client("interface"), h.client("guardian"), h.client("execution")
        order: list[str] = []
        gate = asyncio.Event()
        executed: list = []

        async def on_system(m):
            order.append(m.type)
            if m.type == topics.SYSTEM_PAUSE:
                for c in (interface, guardian, execution):
                    c.set_state("paused")

        async def on_proposed(m):
            order.append(m.type)
            if len(order) == 1:
                await gate.wait()  # hold the first so a backlog forms

        async def on_approved(m):
            executed.append(m)

        await guardian.subscribe("system.*", on_system, group="guardian-system")
        await guardian.subscribe(topics.ACTION_PROPOSED, on_proposed, group="guardian", max_inflight=1)
        await execution.subscribe(topics.ACTION_APPROVED, on_approved, group="execution")

        for i in range(20):
            await guardian.publish(make_message(topics.ACTION_PROPOSED, source="orchestration", partition_key=f"action:a{i}"))
        await h.settle(0.05)
        await interface.publish(make_message(topics.SYSTEM_PAUSE, source="interface"))
        await h.settle(0.1)
        self.assertIn(topics.SYSTEM_PAUSE, order)  # delivered while 19 proposals still queue behind the held one
        gate.set()
        await h.settle(0.2)
        proposals_after_pause = order[order.index(topics.SYSTEM_PAUSE) + 1:].count(topics.ACTION_PROPOSED)
        self.assertLessEqual(proposals_after_pause, 1, f"{h.name}: {order}")  # at most the one already in flight
        # a command published while paused waits; an event does not
        await guardian.publish(make_message(topics.ACTION_APPROVED, source="guardian"))
        evt: list = []
        await interface.subscribe("task.*", lambda m: (evt.append(m), asyncio.sleep(0))[1])
        await interface.publish(make_message(topics.TASK_STARTED, source="interface"))
        await h.settle(0.15)
        self.assertEqual(executed, [])
        self.assertEqual(len(evt), 1)
        for c in (interface, guardian, execution):
            c.set_state("running")
        await h.settle(0.3)
        self.assertEqual(len(executed), 1)


if __name__ == "__main__":
    unittest.main()
