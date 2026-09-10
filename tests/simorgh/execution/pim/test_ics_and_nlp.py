"""The two pure parsers: iCalendar (ics.py) and "tomorrow at 3" (nlp.py).

Both are written rather than imported, so both need to earn that. The
cases here are the ones that actually go wrong in a calendar: all-day
events, timezones, folded lines, quoted parameters containing colons,
recurrence, and a time of day nobody can be sure about."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from simorgh.execution.pim.ics import (
    expand,
    parse_datetime,
    parse_duration,
    parse_events,
    parse_line,
    parse_rrule,
    parse_tasks,
    unfold,
)
from simorgh.execution.pim.nlp import Ambiguous, parse_delay, parse_range, parse_when

WEDNESDAY = datetime(2026, 9, 9, 14, 30)


def _cal(*bodies: str) -> str:
    return "BEGIN:VCALENDAR\n" + "\n".join(bodies) + "\nEND:VCALENDAR"


def _event(**fields) -> str:
    lines = ["BEGIN:VEVENT"] + [f"{k}:{v}" for k, v in fields.items()] + ["END:VEVENT"]
    return "\n".join(lines)


class LineParsingTestCase(unittest.TestCase):
    def test_a_plain_property(self):
        self.assertEqual(parse_line("SUMMARY:Dentist"), ("SUMMARY", {}, "Dentist"))

    def test_parameters_are_split_out(self):
        name, params, value = parse_line("DTSTART;TZID=Europe/London:20260910T150000")
        self.assertEqual((name, params["TZID"], value), ("DTSTART", "Europe/London", "20260910T150000"))

    def test_a_quoted_parameter_containing_a_colon_does_not_split_the_line(self):
        """`CN="Smith, John:esq"` is legal, and a naive split(":", 1)
        turns it into a property nobody can read."""
        name, params, value = parse_line('ATTENDEE;CN="Smith, John:esq";ROLE=REQ:mailto:j@x.com')
        self.assertEqual(name, "ATTENDEE")
        self.assertEqual(params["CN"], "Smith, John:esq")
        self.assertEqual(value, "mailto:j@x.com")

    def test_folded_lines_are_rejoined(self):
        lines = unfold("SUMMARY:A very long\n  title that was folded\nUID:1")
        self.assertEqual(lines[0], "SUMMARY:A very long title that was folded")

    def test_folding_with_a_tab_is_also_unfolded(self):
        self.assertEqual(unfold("SUMMARY:one\n\ttwo")[0], "SUMMARY:onetwo")


class DateTimeTestCase(unittest.TestCase):
    def test_a_utc_datetime(self):
        value, all_day = parse_datetime("20260910T150000Z", {})
        self.assertEqual(value, datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc))
        self.assertFalse(all_day)

    def test_a_floating_datetime_has_no_timezone(self):
        value, _ = parse_datetime("20260910T150000", {})
        self.assertIsNone(value.tzinfo)

    def test_a_tzid_is_applied(self):
        value, _ = parse_datetime("20260910T150000", {"TZID": "UTC"})
        self.assertIsNotNone(value.tzinfo)

    def test_an_unknown_timezone_falls_back_to_floating_rather_than_failing(self):
        value, _ = parse_datetime("20260910T150000", {"TZID": "Mars/Olympus"})
        self.assertEqual(value.hour, 15)

    def test_an_all_day_value_is_flagged_and_not_given_a_timezone(self):
        """An all-day event has no timezone at all. Treating it as
        midnight UTC moves it a day for anyone west of Greenwich."""
        value, all_day = parse_datetime("20260910", {"VALUE": "DATE"})
        self.assertTrue(all_day)
        self.assertIsNone(value.tzinfo)
        self.assertEqual((value.hour, value.minute), (0, 0))

    def test_a_date_without_the_value_parameter_is_still_all_day(self):
        _, all_day = parse_datetime("20260910", {})
        self.assertTrue(all_day)

    def test_rubbish_parses_to_nothing_rather_than_raising(self):
        self.assertEqual(parse_datetime("not a date", {}), (None, False))


class DurationTestCase(unittest.TestCase):
    def test_hours_and_minutes(self):
        self.assertEqual(parse_duration("PT1H30M"), timedelta(hours=1, minutes=30))

    def test_days_and_weeks(self):
        self.assertEqual(parse_duration("P1W2D"), timedelta(weeks=1, days=2))

    def test_an_unparseable_duration_is_an_hour_not_a_crash(self):
        self.assertEqual(parse_duration("later"), timedelta(hours=1))


class EventTestCase(unittest.TestCase):
    def test_a_simple_event(self):
        events = parse_events(_cal(_event(
            UID="1", SUMMARY="Dentist", DTSTART="20260910T090000Z", DTEND="20260910T093000Z",
            LOCATION="High Street")))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].summary, "Dentist")
        self.assertEqual(events[0].location, "High Street")
        self.assertEqual(events[0].duration, timedelta(minutes=30))

    def test_escaped_text_is_unescaped(self):
        events = parse_events(_cal(_event(
            UID="1", SUMMARY=r"Coffee\, then lunch", DTSTART="20260910T090000Z")))
        self.assertEqual(events[0].summary, "Coffee, then lunch")

    def test_a_duration_stands_in_for_a_missing_end(self):
        events = parse_events(_cal(_event(
            UID="1", SUMMARY="Standup", DTSTART="20260910T090000Z", DURATION="PT15M")))
        self.assertEqual(events[0].duration, timedelta(minutes=15))

    def test_an_alarm_inside_an_event_does_not_end_the_event(self):
        """A naive scan for `END:` closes the event at the alarm and
        loses every property after it."""
        text = _cal("BEGIN:VEVENT\nUID:1\nSUMMARY:Dentist\nDTSTART:20260910T090000Z\n"
                    "BEGIN:VALARM\nTRIGGER:-PT15M\nEND:VALARM\nLOCATION:High Street\nEND:VEVENT")
        events = parse_events(text)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].location, "High Street")

    def test_attendees_and_organizer_lose_their_mailto(self):
        text = _cal("BEGIN:VEVENT\nUID:1\nSUMMARY:Review\nDTSTART:20260910T090000Z\n"
                    "ORGANIZER:mailto:boss@x.com\nATTENDEE:mailto:a@x.com\n"
                    "ATTENDEE:mailto:b@x.com\nEND:VEVENT")
        events = parse_events(text)
        self.assertEqual(events[0].organizer, "boss@x.com")
        self.assertEqual(events[0].attendees, ("a@x.com", "b@x.com"))

    def test_an_event_with_no_start_is_skipped_not_guessed_at(self):
        self.assertEqual(parse_events(_cal(_event(UID="1", SUMMARY="No start"))), [])

    def test_events_come_back_in_time_order(self):
        events = parse_events(_cal(
            _event(UID="2", SUMMARY="Later", DTSTART="20260910T150000Z"),
            _event(UID="1", SUMMARY="Earlier", DTSTART="20260910T090000Z")))
        self.assertEqual([e.summary for e in events], ["Earlier", "Later"])

    def test_an_all_day_event_renders_as_all_day(self):
        events = parse_events(_cal(
            "BEGIN:VEVENT\nUID:1\nSUMMARY:Holiday\nDTSTART;VALUE=DATE:20260910\nEND:VEVENT"))
        self.assertTrue(events[0].all_day)
        self.assertIn("all day", events[0].render())


class RecurrenceTestCase(unittest.TestCase):
    WINDOW = (datetime(2026, 9, 7, tzinfo=timezone.utc), datetime(2026, 9, 21, tzinfo=timezone.utc))

    def test_a_weekly_rule_expands_over_the_window(self):
        events = parse_events(_cal(_event(
            UID="1", SUMMARY="Standup", DTSTART="20260907T090000Z", DURATION="PT15M",
            RRULE="FREQ=WEEKLY;BYDAY=MO,WE")), window=self.WINDOW)
        self.assertEqual(len(events), 4)
        self.assertEqual({e.start.weekday() for e in events}, {0, 2})

    def test_count_bounds_the_expansion(self):
        events = parse_events(_cal(_event(
            UID="1", SUMMARY="Daily", DTSTART="20260907T090000Z", RRULE="FREQ=DAILY;COUNT=3")),
            window=self.WINDOW)
        self.assertEqual(len(events), 3)

    def test_until_bounds_the_expansion(self):
        events = parse_events(_cal(_event(
            UID="1", SUMMARY="Daily", DTSTART="20260907T090000Z",
            RRULE="FREQ=DAILY;UNTIL=20260909T235959Z")), window=self.WINDOW)
        self.assertEqual(len(events), 3)

    def test_an_interval_skips(self):
        events = parse_events(_cal(_event(
            UID="1", SUMMARY="Fortnightly", DTSTART="20260907T090000Z",
            RRULE="FREQ=WEEKLY;INTERVAL=2")), window=self.WINDOW)
        self.assertEqual(len(events), 1)

    def test_an_exdate_removes_one_instance(self):
        text = _cal("BEGIN:VEVENT\nUID:1\nSUMMARY:Daily\nDTSTART:20260907T090000Z\n"
                    "RRULE:FREQ=DAILY;COUNT=3\nEXDATE:20260908T090000Z\nEND:VEVENT")
        events = parse_events(text, window=self.WINDOW)
        self.assertEqual(len(events), 2)

    def test_an_unsupported_rule_still_shows_the_event_once(self):
        """A calendar that silently drops a repeating event is worse
        than one that shows it without every instance."""
        events = parse_events(_cal(_event(
            UID="1", SUMMARY="Monthly bills", DTSTART="20260907T090000Z",
            RRULE="FREQ=MONTHLY;BYMONTHDAY=7")), window=self.WINDOW)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].recurrence, "FREQ=MONTHLY;BYMONTHDAY=7")

    def test_an_endless_rule_terminates(self):
        start = datetime(2026, 9, 7, 9, tzinfo=timezone.utc)
        occurrences = expand(start, parse_rrule("FREQ=DAILY"),
                             window_start=self.WINDOW[0], window_end=self.WINDOW[1])
        self.assertEqual(len(occurrences), 14)


class TaskTestCase(unittest.TestCase):
    def test_a_todo_with_a_due_date(self):
        text = _cal("BEGIN:VTODO\nUID:t1\nSUMMARY:Renew passport\n"
                    "DUE;VALUE=DATE:20261001\nPRIORITY:1\nEND:VTODO")
        tasks = parse_tasks(text)
        self.assertEqual(tasks[0].summary, "Renew passport")
        self.assertEqual(tasks[0].due.date().isoformat(), "2026-10-01")
        self.assertEqual(tasks[0].priority, 1)
        self.assertFalse(tasks[0].done)

    def test_a_completed_todo_is_done(self):
        text = _cal("BEGIN:VTODO\nUID:t2\nSUMMARY:x\nSTATUS:COMPLETED\nEND:VTODO")
        self.assertTrue(parse_tasks(text)[0].done)


class DelayTestCase(unittest.TestCase):
    def test_bare_and_prefixed_delays(self):
        self.assertEqual(parse_delay("20m"), 1200)
        self.assertEqual(parse_delay("in 2 hours"), 7200)
        self.assertEqual(parse_delay("1w"), 604800)

    def test_something_that_is_not_a_delay(self):
        self.assertIsNone(parse_delay("tomorrow"))


class WhenTestCase(unittest.TestCase):
    def test_a_delay_is_relative_to_now(self):
        self.assertEqual(parse_when("20m", now=WEDNESDAY), WEDNESDAY + timedelta(minutes=20))

    def test_tomorrow_with_a_time(self):
        self.assertEqual(parse_when("tomorrow 9am", now=WEDNESDAY), datetime(2026, 9, 10, 9, 0))

    def test_tomorrow_without_a_time_is_the_morning(self):
        self.assertEqual(parse_when("tomorrow", now=WEDNESDAY), datetime(2026, 9, 10, 9, 0))

    def test_tonight_is_the_evening(self):
        self.assertEqual(parse_when("tonight", now=WEDNESDAY).hour, 20)

    def test_a_weekday_means_the_next_one(self):
        self.assertEqual(parse_when("friday at 15:00", now=WEDNESDAY), datetime(2026, 9, 11, 15, 0))

    def test_todays_weekday_means_next_week_not_today(self):
        """"wednesday" said on a Wednesday means the one coming, not the
        one already half over."""
        self.assertEqual(parse_when("wednesday", now=WEDNESDAY).date().isoformat(), "2026-09-16")

    def test_an_iso_datetime(self):
        self.assertEqual(parse_when("2026-10-01 07:30", now=WEDNESDAY), datetime(2026, 10, 1, 7, 30))

    def test_a_bare_time_means_the_next_time_it_is_that_oclock(self):
        self.assertEqual(parse_when("at 3pm", now=WEDNESDAY), datetime(2026, 9, 9, 15, 0))

    def test_a_bare_time_already_past_rolls_to_tomorrow(self):
        self.assertEqual(parse_when("at 9am", now=WEDNESDAY), datetime(2026, 9, 10, 9, 0))

    def test_an_hour_that_could_be_either_asks_rather_than_guessing(self):
        """Waking someone at three in the morning because they meant the
        afternoon is exactly what this refuses to risk."""
        with self.assertRaises(Ambiguous) as caught:
            parse_when("at 3", now=WEDNESDAY)
        self.assertIn("3am", str(caught.exception))

    def test_an_unreadable_phrase_says_what_would_work(self):
        with self.assertRaises(Ambiguous) as caught:
            parse_when("sometime soonish", now=WEDNESDAY)
        self.assertIn("tomorrow 9am", str(caught.exception))

    def test_nothing_at_all_asks_when(self):
        with self.assertRaises(Ambiguous):
            parse_when("", now=WEDNESDAY)


class RangeTestCase(unittest.TestCase):
    def test_today_is_midnight_to_midnight(self):
        start, end = parse_range("today", now=WEDNESDAY)
        self.assertEqual(start, datetime(2026, 9, 9))
        self.assertEqual(end, datetime(2026, 9, 10))

    def test_this_week_starts_on_monday(self):
        start, end = parse_range("this week", now=WEDNESDAY)
        self.assertEqual(start.weekday(), 0)
        self.assertEqual((end - start).days, 7)

    def test_next_week_is_the_following_one(self):
        start, _ = parse_range("next week", now=WEDNESDAY)
        self.assertEqual(start.date().isoformat(), "2026-09-14")

    def test_a_duration_becomes_a_window(self):
        start, end = parse_range("7 days", now=WEDNESDAY)
        self.assertEqual((end - start).days, 7)

    def test_an_empty_range_is_today(self):
        self.assertEqual(parse_range("", now=WEDNESDAY), parse_range("today", now=WEDNESDAY))

    def test_an_unreadable_range_says_what_would_work(self):
        with self.assertRaises(Ambiguous) as caught:
            parse_range("whenever", now=WEDNESDAY)
        self.assertIn("this week", str(caught.exception))
