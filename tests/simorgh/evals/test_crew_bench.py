"""Stage 18 item 6: `crew-bench` runs free and records its numbers.

The bench drives Orchestration's real `SessionRunner` with fake
providers, so what is tested is that it really measures -- every number
is present, the crew beats serial, a message is far under the plan's
50 ms -- and that `main` appends one row and calls no model.
"""

import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.evals import crewbench


class TheBench(unittest.TestCase):
    def test_every_number_is_measured(self):
        row = asyncio.run(crewbench.run(members=3, delay_s=0.1, messages=20, crew_size=3))
        latency, spawn, fan, memory = row["message_latency"], row["spawn_overhead"], row["fan_out"], row["memory"]
        self.assertEqual(latency["messages"], 20)
        self.assertLess(latency["p95_ms"], crewbench.MESSAGE_TARGET_MS)
        self.assertTrue(latency["under_target"])
        self.assertEqual(spawn["members"], 3, "a member never thought")
        self.assertGreaterEqual(spawn["p50_ms"], 0.0)
        # Item 2's acceptance, held here as the bench's own sanity check:
        # three members at once take well under the serial time.
        self.assertLess(fan["ratio"], 0.8, fan)
        self.assertGreater(memory["peak_many_kib"], 0.0)
        self.assertGreaterEqual(memory["per_member_kib"], 0.0)
        self.assertIn("no model was called", crewbench.table(row))

    def test_the_command_records_one_row_and_needs_no_key(self):
        from simorgh.evals.__main__ import main

        env = {k: v for k, v in os.environ.items()
               if not k.endswith("_API_KEY") and k not in ("SIMORGH_EVALS_PAID", "SIMORGH_HOUSE_PAID")}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=True):
            log = Path(tmp) / "bench.jsonl"
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["crew-bench", "--members", "2", "--delay", "0.02", "--messages", "5",
                             "--crew-size", "2", "--log", str(log)])
            rows = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), {"ts", "message_latency", "spawn_overhead", "fan_out", "memory", "seconds"})
        self.assertIn("message latency", out.getvalue())

    def test_nonsense_arguments_are_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            crewbench.main(["--members", "0", "--log", ""])


if __name__ == "__main__":
    unittest.main()
