"""Keyless searches stay a gap apart even when several run at once."""

import threading
import time
import unittest

from simorgh.execution import websearch
from simorgh.execution.config import Config

SEARCH = next(v for v in vars(websearch).values() if isinstance(v, type) and hasattr(v, "_space_out"))


class Spacing(unittest.TestCase):
    def test_concurrent_searches_go_out_one_gap_apart(self):
        tool = SEARCH(Config(web_search_min_interval_s=0.15))
        tool._space_out()  # a search just went out
        times: list[float] = []
        lock = threading.Lock()

        def one():
            tool._space_out()
            with lock:
                times.append(time.monotonic())

        threads = [threading.Thread(target=one) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        times.sort()
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertTrue(all(g >= 0.12 for g in gaps), gaps)

    def test_after_a_refusal_the_retry_waits(self):
        tool = SEARCH(Config(web_search_min_interval_s=0.1))
        tool._last_call = time.monotonic() + 0.1  # what a refusal sets
        start = time.monotonic()
        tool._space_out()
        self.assertGreaterEqual(time.monotonic() - start, 0.18)


if __name__ == "__main__":
    unittest.main()
