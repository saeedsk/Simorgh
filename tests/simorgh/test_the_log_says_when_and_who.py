"""A log line says which DAY and which PROCESS it came from.

`sim.log` is a rotating ring several days deep, and more than one Sim
writes it -- a trial, a replay, the live one. With a bare `%H:%M:%S`,
yesterday's lines sit between today's and nothing says which process
wrote which. Supervising the SWE-bench run on 2026-09-22, yesterday's
Gemini failures read as today's twice, and "is the fix actually live?"
is the question this file exists to answer.
"""

import logging
import re
import unittest

from simorgh.kernel.cli import _log_handler  # noqa: PLC2701 -- the thing under test


class _Runtime:
    def __init__(self, data_dir):
        self.data_dir = data_dir


class _Config:
    def __init__(self, data_dir):
        self.runtime = _Runtime(data_dir)


class TheLogSaysWhenAndWho(unittest.TestCase):
    def test_a_line_carries_the_date_and_the_pid(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            handler = _log_handler(_Config(tmp))
            record = logging.LogRecord("simorgh.test", logging.INFO, __file__, 1, "something happened", (), None)
            line = handler.formatter.format(record)
        self.assertRegex(line, r"^\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[\d+\] INFO simorgh\.test something happened$",
                         f"got {line!r}")


if __name__ == "__main__":
    unittest.main()
