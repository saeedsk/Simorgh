"""Energy: tariffs, meters, and the three tools.

The tariff maths and the meter differencing are pure, and they are
where the money is. Two traps get most of the attention here: a Home
Assistant energy sensor is CUMULATIVE, so its raw value is a lifetime
total and only a difference means anything; and a meter is allowed to
reset, which a naive subtraction turns into a large negative bill."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from simorgh.contracts.home.fakes import FakeHomeAssistant
from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.energy.api import Rate, Reading, Tariff
from simorgh.execution.energy.meters import (
    add_standing_charge,
    consumed,
    cost_of,
    hourly_from_history,
    project_bill,
    reading_from,
)
from simorgh.execution.energy.tools import energy_tools

WEDNESDAY = datetime(2026, 6, 17, 14, 30)

TOU = Tariff(
    name="tou", currency="GBP", standing_charge_per_day=0.50,
    rates=(Rate("off_peak", 0.09, hours=(0, 7)),
           Rate("day", 0.24, export_price=0.05, hours=(7, 16)),
           Rate("peak", 0.34, export_price=0.05, hours=(16, 19)),
           Rate("evening", 0.24, export_price=0.05, hours=(19, 24))))


def _ctx() -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                       data_dir=Path("."), clock=None, logger=None, ledger=None)


class RateTestCase(unittest.TestCase):
    def test_an_hour_window_covers_its_hours(self):
        rate = Rate("peak", 0.34, hours=(16, 19))
        self.assertTrue(rate.covers(datetime(2026, 6, 17, 17)))
        self.assertFalse(rate.covers(datetime(2026, 6, 17, 19)), "the end hour is exclusive")

    def test_a_window_that_wraps_midnight(self):
        rate = Rate("night", 0.09, hours=(22, 7))
        self.assertTrue(rate.covers(datetime(2026, 6, 17, 23)))
        self.assertTrue(rate.covers(datetime(2026, 6, 17, 3)))
        self.assertFalse(rate.covers(datetime(2026, 6, 17, 12)))

    def test_a_seasonal_rate_only_applies_in_its_months(self):
        rate = Rate("summer", 0.30, months=(6, 7, 8))
        self.assertTrue(rate.covers(datetime(2026, 7, 1, 12)))
        self.assertFalse(rate.covers(datetime(2026, 1, 1, 12)))

    def test_a_weekday_rate_only_applies_on_its_days(self):
        rate = Rate("weekend", 0.15, weekdays=(5, 6))
        self.assertTrue(rate.covers(datetime(2026, 6, 20, 12)))    # Saturday
        self.assertFalse(rate.covers(datetime(2026, 6, 17, 12)))   # Wednesday


class TariffTestCase(unittest.TestCase):
    def test_the_right_band_is_picked_for_each_hour(self):
        for hour, name in ((3, "off_peak"), (9, "day"), (17, "peak"), (21, "evening")):
            with self.subTest(hour=hour):
                self.assertEqual(TOU.rate_at(datetime(2026, 6, 17, hour)).name, name)

    def test_the_most_specific_rate_wins_not_the_first(self):
        """A rule with a season and a weekday restriction is a
        deliberate exception; declaration order should not decide."""
        tariff = Tariff(rates=(Rate("general", 0.20),
                                Rate("summer_weekend", 0.10, months=(6,), weekdays=(5, 6))))
        self.assertEqual(tariff.rate_at(datetime(2026, 6, 20, 12)).name, "summer_weekend")
        self.assertEqual(tariff.rate_at(datetime(2026, 6, 17, 12)).name, "general")

    def test_an_uncovered_hour_is_named_rather_than_priced_at_a_guess(self):
        tariff = Tariff(rates=(Rate("morning", 0.2, hours=(0, 6)),))
        self.assertEqual(tariff.rate_at(datetime(2026, 6, 17, 12)).name, "unpriced")

    def test_gaps_are_reported(self):
        """A tariff with a hole in it silently prices part of the day at
        zero, and every number downstream is wrong."""
        tariff = Tariff(rates=(Rate("morning", 0.2, hours=(0, 6)),))
        self.assertEqual(tariff.gaps(), list(range(6, 24)))

    def test_a_complete_tariff_has_no_gaps(self):
        self.assertEqual(TOU.gaps(), [])

    def test_export_is_priced_separately_from_import(self):
        """Net metering is not symmetric anywhere worth modelling."""
        when = datetime(2026, 6, 17, 17)
        self.assertNotEqual(TOU.price_at(when), TOU.export_price_at(when))

    def test_a_tariff_round_trips_through_a_dict(self):
        restored = Tariff.from_dict({
            "name": "t", "currency": "EUR", "standing_charge_per_day": 0.4,
            "rates": [{"name": "flat", "price": 0.3, "hours": [0, 24]}]})
        self.assertEqual(restored.currency, "EUR")
        self.assertEqual(restored.rates[0].price, 0.3)


class MeterTestCase(unittest.TestCase):
    def _reading(self, value: float, *, cumulative: bool = True) -> Reading:
        return Reading("sensor.grid", "grid_import", value,
                       state_class="total_increasing" if cumulative else "measurement")

    def test_a_cumulative_meter_is_differenced(self):
        """The raw value is a lifetime total. Treating it as
        consumption overstates a day by several years of it."""
        self.assertEqual(consumed(self._reading(1000.0), self._reading(1012.5)), 12.5)

    def test_a_meter_reset_is_not_negative_consumption(self):
        """A `total_increasing` sensor may go back to zero when a device
        is replaced. A bill that goes down because of that is worse than
        one that misses an hour."""
        self.assertEqual(consumed(self._reading(1012.5), self._reading(3.0)), 0.0)

    def test_a_measurement_sensor_is_taken_as_is(self):
        self.assertEqual(consumed(None, self._reading(4.0, cumulative=False)), 4.0)

    def test_a_missing_reading_is_zero_rather_than_a_crash(self):
        self.assertEqual(consumed(None, None), 0.0)

    def test_an_unavailable_sensor_is_not_a_reading(self):
        """Reporting it as zero silently claims the house used no
        electricity."""
        from simorgh.contracts.home.api import Entity

        self.assertIsNone(reading_from(Entity("sensor.x", "unavailable"), role="grid_import"))

    def test_a_numeric_sensor_becomes_a_reading(self):
        from simorgh.contracts.home.api import Entity

        entity = Entity("sensor.x", "12.5", {"unit_of_measurement": "kWh",
                                              "state_class": "total_increasing"})
        reading = reading_from(entity, role="grid_import")
        self.assertEqual(reading.value, 12.5)
        self.assertTrue(reading.cumulative)


class CostTestCase(unittest.TestCase):
    def test_each_hour_is_priced_at_its_own_rate(self):
        hourly = [(datetime(2026, 6, 17, hour), 1.0) for hour in (3, 9, 17, 21)]
        report = cost_of(hourly, TOU)
        self.assertAlmostEqual(report.import_cost, 0.09 + 0.24 + 0.34 + 0.24, places=6)
        self.assertEqual(report.imported_kwh, 4.0)

    def test_costs_group_by_rate(self):
        hourly = [(datetime(2026, 6, 17, 17), 2.0), (datetime(2026, 6, 17, 3), 1.0)]
        self.assertEqual(set(cost_of(hourly, TOU).by_rate()), {"peak", "off_peak"})

    def test_export_is_credited_not_subtracted_from_consumption(self):
        report = cost_of([(datetime(2026, 6, 17, 12), 2.0)], TOU,
                         exported=[(datetime(2026, 6, 17, 12), 3.0)])
        self.assertEqual(report.imported_kwh, 2.0)
        self.assertEqual(report.exported_kwh, 3.0)
        self.assertAlmostEqual(report.net, 2.0 * 0.24 - 3.0 * 0.05, places=6)

    def test_the_standing_charge_is_added(self):
        report = add_standing_charge(cost_of([], TOU), TOU, days=2)
        self.assertAlmostEqual(report.import_cost, 1.0, places=6)

    def test_a_daylight_saving_day_needs_no_special_case(self):
        """Costing hour by hour means the day is whatever the local
        calendar had -- an hour counted twice or not at all falls out
        for free."""
        hourly = [(datetime(2026, 3, 29, hour), 1.0) for hour in range(23)]
        self.assertEqual(len(cost_of(hourly, TOU).lines), 23)

    def test_a_projection_scales_what_has_happened_so_far(self):
        report = cost_of([(datetime(2026, 6, 17, 12), 10.0)], TOU)
        self.assertAlmostEqual(project_bill(report, elapsed_days=1, cycle_days=30),
                               report.net * 30, places=6)

    def test_a_projection_from_no_time_is_zero_rather_than_infinite(self):
        self.assertEqual(project_bill(cost_of([], TOU), elapsed_days=0), 0.0)


class HistoryTestCase(unittest.TestCase):
    def test_a_cumulative_series_is_bucketed_and_differenced(self):
        rows = [{"state": "100", "last_changed": "2026-06-17T09:00:00+00:00"},
                {"state": "102", "last_changed": "2026-06-17T09:30:00+00:00"},
                {"state": "105", "last_changed": "2026-06-17T10:10:00+00:00"}]
        hourly = hourly_from_history(rows, cumulative=True)
        self.assertEqual(len(hourly), 2)
        self.assertEqual(hourly[0][1], 5.0)

    def test_a_measurement_series_is_averaged_per_hour(self):
        rows = [{"state": "100", "last_changed": "2026-06-17T09:00:00+00:00"},
                {"state": "200", "last_changed": "2026-06-17T09:30:00+00:00"}]
        self.assertEqual(hourly_from_history(rows, cumulative=False)[0][1], 150.0)

    def test_unparseable_rows_are_skipped_not_fatal(self):
        rows = [{"state": "unavailable", "last_changed": "2026-06-17T09:00:00+00:00"},
                {"state": "100", "last_changed": "nonsense"},
                {"state": "100", "last_changed": "2026-06-17T09:00:00+00:00"}]
        self.assertEqual(len(hourly_from_history(rows, cumulative=True)), 1)

    def test_an_empty_history_is_an_empty_series(self):
        self.assertEqual(hourly_from_history([], cumulative=True), [])


class _ToolCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _tools(self, *, house=None, tariff=None, meters=None, **overrides) -> dict:
        self.house = house if house is not None else FakeHomeAssistant()
        if tariff is not None:
            path = self.root / "tariff.json"
            path.write_text(json.dumps(tariff), encoding="utf-8")
        config = Config(repo_root=self.root,
                        energy_tariff_path=str(self.root / "tariff.json"),
                        energy_meters=meters if meters is not None else {
                            "grid_import": "sensor.grid_import",
                            "solar": "sensor.solar_generation"},
                        **overrides)
        return {tool.name: tool for tool in energy_tools(
            config, client=self.house, env={}, clock=lambda: WEDNESDAY.timestamp())}


TOU_DICT = {
    "name": "tou", "currency": "GBP", "standing_charge_per_day": 0.5,
    "rates": [{"name": "off_peak", "price": 0.09, "hours": [0, 7]},
              {"name": "day", "price": 0.24, "hours": [7, 16]},
              {"name": "peak", "price": 0.34, "hours": [16, 19]},
              {"name": "evening", "price": 0.24, "hours": [19, 24]}],
}


class EnergyStatusTestCase(_ToolCase):
    async def test_it_reports_the_meters_and_the_current_rate(self):
        result = await self._tools(tariff=TOU_DICT)["energy_status"].run({}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("grid_import", result.output)
        self.assertEqual(result.metadata["rate"], "day")

    async def test_without_a_tariff_it_says_nothing_can_be_priced(self):
        result = await self._tools()["energy_status"].run({}, ctx=_ctx())
        self.assertIn("no tariff set", result.output)

    async def test_it_says_when_the_rate_next_changes(self):
        result = await self._tools(tariff=TOU_DICT)["energy_status"].run({}, ctx=_ctx())
        self.assertIn("next rate change", result.output)

    async def test_an_unavailable_sensor_is_reported_not_read_as_zero(self):
        house = FakeHomeAssistant()
        house.set_state("sensor.grid_import", "unavailable")
        result = await self._tools(house=house, tariff=TOU_DICT)["energy_status"].run({}, ctx=_ctx())
        self.assertIn("could not read", result.output)
        self.assertNotIn("grid_import   0", result.output)

    async def test_with_no_meters_configured_it_says_what_to_add(self):
        result = await self._tools(meters={})["energy_status"].run({}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("execution.energy_meters", result.error)
        self.assertIn("HOME_FIND", result.error)

    async def test_with_no_house_configured_it_says_what_to_set(self):
        tools = {t.name: t for t in energy_tools(Config(), env={})}
        result = await tools["energy_status"].run({}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("HOME_ASSISTANT_URL", result.error)


class EnergyReportTestCase(_ToolCase):
    async def test_without_a_tariff_it_refuses_rather_than_reporting_zero(self):
        result = await self._tools()["energy_report"].run({"range": "today"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("no tariff", result.error)

    async def test_an_unreadable_range_says_what_would_work(self):
        result = await self._tools(tariff=TOU_DICT)["energy_report"].run(
            {"range": "whenever"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("today", result.error)

    async def test_no_history_says_so_rather_than_reporting_nothing_used(self):
        result = await self._tools(tariff=TOU_DICT)["energy_report"].run(
            {"range": "today"}, ctx=_ctx())
        self.assertTrue(result.ok)
        self.assertIn("no history", result.output)


class EnergyTariffTestCase(_ToolCase):
    async def test_show_before_anything_is_set_gives_an_example(self):
        result = await self._tools()["energy_tariff"].run({"op": "show"}, ctx=_ctx())
        self.assertTrue(result.ok)
        self.assertIn("ENERGY_TARIFF: set", result.output)
        self.assertFalse(result.metadata["set"])

    async def test_setting_writes_it_and_reports_the_bands(self):
        tools = self._tools()
        result = await tools["energy_tariff"].run({"op": "set", "spec": TOU_DICT}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        shown = await tools["energy_tariff"].run({"op": "show"}, ctx=_ctx())
        self.assertIn("off_peak", shown.output)
        self.assertIn("peak", shown.output)

    async def test_a_tariff_with_a_hole_in_it_is_warned_about(self):
        spec = {"name": "broken", "currency": "GBP",
                "rates": [{"name": "morning", "price": 0.2, "hours": [0, 6]}]}
        result = await self._tools()["energy_tariff"].run({"op": "set", "spec": spec}, ctx=_ctx())
        self.assertTrue(result.ok)
        self.assertIn("WARNING", result.output)
        self.assertTrue(result.metadata["gaps"])

    async def test_a_tariff_with_no_rates_is_refused(self):
        result = await self._tools()["energy_tariff"].run(
            {"op": "set", "spec": {"name": "x"}}, ctx=_ctx())
        self.assertFalse(result.ok)

    async def test_an_unknown_op_is_refused(self):
        result = await self._tools()["energy_tariff"].run({"op": "delete"}, ctx=_ctx())
        self.assertFalse(result.ok)
