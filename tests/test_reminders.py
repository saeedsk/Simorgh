import contextlib
import io
import time
import unittest

from src.orchestrator.reminders import parse_duration, schedule_reminder


class TestParseDuration(unittest.TestCase):
    def test_bare_number_is_seconds(self):
        self.assertEqual(parse_duration("30"), 30.0)

    def test_seconds_suffix(self):
        self.assertEqual(parse_duration("45s"), 45.0)

    def test_minutes_suffix(self):
        self.assertEqual(parse_duration("2m"), 120.0)

    def test_hours_suffix(self):
        self.assertEqual(parse_duration("1h"), 3600.0)

    def test_case_insensitive_suffix(self):
        self.assertEqual(parse_duration("1M"), 60.0)

    def test_fractional_value(self):
        self.assertEqual(parse_duration("1.5m"), 90.0)

    def test_whitespace_is_tolerated(self):
        self.assertEqual(parse_duration(" 1 m "), 60.0)

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_duration("not a duration"))

    def test_zero_returns_none(self):
        self.assertIsNone(parse_duration("0s"))

    def test_negative_returns_none(self):
        self.assertIsNone(parse_duration("-5s"))

    def test_absurdly_long_returns_none(self):
        self.assertIsNone(parse_duration("999h"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(parse_duration(""))


class TestScheduleReminder(unittest.TestCase):
    def test_fires_after_the_delay_and_prints_the_message(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            timer = schedule_reminder(0.05, "wake up")
            timer.join(timeout=2.0)

        self.assertIn("wake up", buf.getvalue())
        self.assertIn("reminder", buf.getvalue())

    def test_does_not_block_the_caller(self):
        start = time.time()
        schedule_reminder(5.0, "later")
        elapsed = time.time() - start

        self.assertLess(elapsed, 1.0)

    def test_returned_timer_is_a_daemon_thread(self):
        timer = schedule_reminder(5.0, "later")
        self.assertTrue(timer.daemon)
        timer.cancel()


if __name__ == "__main__":
    unittest.main()
