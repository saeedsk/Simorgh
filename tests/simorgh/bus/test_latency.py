"""The memory backend's latency budget (docs/blueprint/subsystems/01-bus.md
section 5.3): < 5 ms median per request round-trip, measured, so a bus
regression that slows the chat path shows up here rather than in
someone's terminal."""

import time
import unittest

from simorgh.contracts import topics

from tests.simorgh.helpers import make_message

from .harness import Harness, run


class TestLatency(unittest.TestCase):
    @run
    async def test_request_round_trip_median_under_budget(self):
        async with Harness("memory") as h:
            planning, worker = h.client("planning"), h.client("orchestration")

            async def on_claim(m):
                await planning.reply(m, type=topics.TASK_CLAIM_REPLY, payload={"granted": True, "lease_until": 1.0, "task": {}})

            await planning.subscribe(topics.TASK_CLAIM, on_claim, group="planning")
            samples = []
            for i in range(50):
                req = make_message(topics.TASK_CLAIM, source="orchestration", payload={"task_id": f"t{i}", "worker_id": "w1"})
                t0 = time.perf_counter()
                await worker.request(req, timeout=2.0)
                samples.append((time.perf_counter() - t0) * 1000)
            samples.sort()
            self.assertLess(samples[len(samples) // 2], 5.0, f"median {samples[len(samples)//2]:.2f} ms")


if __name__ == "__main__":
    unittest.main()
