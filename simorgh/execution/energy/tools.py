"""`energy_status`, `energy_report`, `energy_tariff`.

All three read through the same Home Assistant client the `home_*`
tools use, and all three refuse the same way when the house is not set
up. What they add to HA's own Energy dashboard is the thing it does not
know: what any of it cost.

`energy_status` answers "what is the house doing and what is it costing
me right now". `energy_report` answers "what did it cost over a
period, and where did it go". `energy_tariff` is how the prices get in
-- and it reports the gaps in a tariff, because a tariff with a hole in
it silently prices part of the day at zero and every number downstream
of that is quietly wrong.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from simorgh.contracts.home.client import HomeUnavailable
from simorgh.contracts.protocols import ToolContext, ToolResult

from ..home.tools import _HomeTool
from .api import Tariff
from .meters import (
    ROLES,
    add_standing_charge,
    cost_of,
    hourly_from_history,
    project_bill,
    reading_from,
)


class _EnergyTool(_HomeTool):
    """Shares the house client, and adds the tariff."""

    def _tariff_path(self) -> Path:
        raw = str(getattr(self._config, "energy_tariff_path", "workspace/energy/tariff.json"))
        path = Path(raw).expanduser()
        return path if path.is_absolute() else Path(getattr(self._config, "repo_root", ".")) / path

    def _tariff(self) -> Tariff:
        inline = getattr(self._config, "energy_tariff", None)
        if inline:
            return Tariff.from_dict(dict(inline))
        path = self._tariff_path()
        if path.exists():
            try:
                return Tariff.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        return Tariff(name="unset", currency=str(getattr(self._config, "energy_currency", "USD")))

    def _meters(self) -> dict:
        configured = dict(getattr(self._config, "energy_meters", {}) or {})
        return {role: entity_id for role, entity_id in configured.items()
                if role in ROLES and entity_id}

    @staticmethod
    def _no_meters() -> ToolResult:
        return ToolResult(
            ok=False,
            error=("refused: no energy meters are configured. Add the Home Assistant sensors "
                   "that measure the house to simorgh.toml:\n"
                   "[execution.energy_meters]\n"
                   'grid_import = "sensor.grid_import"\n'
                   'solar = "sensor.solar_generation"\n'
                   "Run HOME_FIND: energy to see what your Home Assistant already has."))


class EnergyStatusTool(_EnergyTool):
    name = "energy_status"
    description = (
        "What the house is using and producing right now, what rate it is on, and what today "
        "has cost so far."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "properties": {}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        client = self._client()
        if not client.configured:
            return self._unconfigured(client)
        meters = self._meters()
        if not meters:
            return self._no_meters()

        tariff = self._tariff()
        now = datetime.fromtimestamp(self._clock())
        rate = tariff.rate_at(now)

        readings, problems = {}, []
        for role, entity_id in meters.items():
            try:
                entity = await client.state(entity_id)
            except HomeUnavailable as exc:
                problems.append(f"{role}: {exc}")
                continue
            reading = reading_from(entity, role=role, at=self._clock())
            if reading is None:
                # An unavailable sensor is not a zero: reporting it as
                # one silently claims the house used no electricity.
                problems.append(f"{role}: {entity_id} is unavailable")
                continue
            readings[role] = reading

        lines = [f"rate now: {rate.name} at {rate.price:.4f} {tariff.currency}/kWh"
                 if tariff.name != "unset" else
                 "rate now: no tariff set -- run ENERGY_TARIFF to price any of this"]
        for role, reading in readings.items():
            lines.append(f"  {role:14} {reading.value:g} {reading.unit}  ({reading.label})")

        today = await self._today_cost(client, meters, tariff, now)
        if today is not None:
            lines.append(f"today so far: {today.imported_kwh:.2f} kWh, "
                         f"{today.net:.2f} {tariff.currency}")
        next_change = _next_rate_change(tariff, now)
        if next_change is not None:
            when, upcoming = next_change
            lines.append(f"next rate change: {when:%H:%M} to {upcoming.name} "
                         f"at {upcoming.price:.4f}")
        if problems:
            lines.append("could not read:\n" + "\n".join(f"  - {p}" for p in problems))
        return ToolResult(
            ok=bool(readings), output="\n".join(lines),
            error="; ".join(problems) if not readings else None,
            metadata={"rate": rate.name, "price": rate.price, "currency": tariff.currency,
                      "readings": {r: readings[r].value for r in readings},
                      "today_kwh": today.imported_kwh if today else None,
                      "today_cost": today.net if today else None})

    async def _today_cost(self, client, meters, tariff, now):
        entity_id = meters.get("grid_import")
        if not entity_id or tariff.name == "unset":
            return None
        hours = (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 3600
        try:
            rows = await client.history(entity_id, hours=max(hours, 1.0))
        except HomeUnavailable:
            return None
        hourly = hourly_from_history(rows, cumulative=True)
        if not hourly:
            return None
        report = cost_of(hourly, tariff)
        return add_standing_charge(report, tariff, days=hours / 24)


class EnergyReportTool(_EnergyTool):
    name = "energy_report"
    description = (
        "What the house used and what it cost over a period -- a day, a week, a month -- broken "
        "down by hour and by rate."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {
        "type": "object",
        "properties": {"range": {"type": "string"}, "by": {"type": "string",
                                                            "enum": ["hour", "rate", "day"]}},
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        client = self._client()
        if not client.configured:
            return self._unconfigured(client)
        meters = self._meters()
        if not meters.get("grid_import"):
            return self._no_meters()

        tariff = self._tariff()
        if tariff.name == "unset":
            return ToolResult(ok=False,
                              error=("refused: no tariff is set, so nothing can be priced. "
                                     "ENERGY_TARIFF: set with your rates."))
        hours = _hours_for(str(args.get("range") or "today"))
        if hours is None:
            return ToolResult(ok=False,
                              error=(f"refused: {args.get('range')!r} is not a range I can read. "
                                     "Try today, yesterday, week, month, or a number of days."))
        try:
            rows = await client.history(meters["grid_import"], hours=hours)
            export_rows = (await client.history(meters["grid_export"], hours=hours)
                           if meters.get("grid_export") else [])
        except HomeUnavailable as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")

        hourly = hourly_from_history(rows, cumulative=True)
        if not hourly:
            return ToolResult(
                ok=True,
                output=(f"Home Assistant has no history for {meters['grid_import']} over the last "
                        f"{hours:.0f}h. Its recorder may not be keeping that sensor."),
                metadata={"rows": []})
        exported = hourly_from_history(export_rows, cumulative=True)
        report = cost_of(hourly, tariff, exported=exported)
        add_standing_charge(report, tariff, days=hours / 24)

        grouping = str(args.get("by") or "rate")
        lines = [f"{report.imported_kwh:.2f} kWh imported, "
                 f"{report.import_cost:.2f} {tariff.currency}"]
        if report.exported_kwh:
            lines.append(f"{report.exported_kwh:.2f} kWh exported, "
                         f"-{report.export_credit:.2f} {tariff.currency}")
            lines.append(f"net {report.net:.2f} {tariff.currency}")
        if grouping == "rate":
            for name, cost in sorted(report.by_rate().items(), key=lambda kv: -kv[1]):
                lines.append(f"  {name:12} {cost:8.2f} {tariff.currency}")
        elif grouping == "hour":
            for line in report.lines[-24:]:
                lines.append(f"  {line.hour:%d %b %H:%M}  {line.kwh:6.2f} kWh  "
                             f"{line.cost:6.2f}  ({line.rate})")
        projected = project_bill(report, elapsed_days=hours / 24,
                                 cycle_days=float(getattr(self._config, "energy_cycle_days", 30)))
        lines.append(f"at this rate a {int(getattr(self._config, 'energy_cycle_days', 30))}-day "
                     f"cycle is about {projected:.2f} {tariff.currency}")
        return ToolResult(
            ok=True, output="\n".join(lines),
            metadata={"kwh": report.imported_kwh, "cost": report.import_cost,
                      "exported_kwh": report.exported_kwh, "credit": report.export_credit,
                      "net": report.net, "currency": tariff.currency, "projected": projected,
                      "rows": [{"hour": line.hour.isoformat(), "kwh": line.kwh,
                                "rate": line.rate, "price": line.price, "cost": line.cost}
                               for line in report.lines]})


class EnergyTariffTool(_EnergyTool):
    name = "energy_tariff"
    description = (
        "Show or set what the electricity costs -- a flat rate or time-of-use bands. Nothing "
        "else in the energy tools can price anything until this is set."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {
        "type": "object",
        "properties": {"op": {"type": "string", "enum": ["show", "set"]},
                       "spec": {"type": "object"}, "name": {"type": "string"},
                       "currency": {"type": "string"}, "rates": {"type": "array"},
                       "standing_charge_per_day": {"type": "number"}},
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        op = str(args.get("op") or "show").strip().lower()
        if op == "show":
            tariff = self._tariff()
            if tariff.name == "unset":
                return ToolResult(
                    ok=True,
                    output=("no tariff is set. Set one with, for example:\n"
                            "ENERGY_TARIFF: set\n"
                            '{"name": "tou", "currency": "GBP", "standing_charge_per_day": 0.53,\n'
                            ' "rates": [{"name": "off_peak", "price": 0.09, "hours": [0, 7]},\n'
                            '            {"name": "day", "price": 0.24, "hours": [7, 16]},\n'
                            '            {"name": "peak", "price": 0.34, "hours": [16, 19]},\n'
                            '            {"name": "evening", "price": 0.24, "hours": [19, 24]}]}'),
                    metadata={"set": False})
            lines = [f"{tariff.name} ({tariff.currency}), standing charge "
                     f"{tariff.standing_charge_per_day:.2f}/day"]
            for rate in tariff.rates:
                window = f"{rate.hours[0]:02d}:00-{rate.hours[1]:02d}:00"
                extra = ""
                if rate.months:
                    extra += f" months {list(rate.months)}"
                if rate.weekdays:
                    extra += f" weekdays {list(rate.weekdays)}"
                lines.append(f"  {rate.name:12} {rate.price:.4f}  {window}{extra}"
                             + (f"  export {rate.export_price:.4f}" if rate.export_price else ""))
            gaps = tariff.gaps()
            if gaps:
                # A tariff with a hole in it silently prices part of the
                # day at zero, and every number downstream is wrong.
                lines.append(f"WARNING: no rate covers hour(s) {gaps} -- they are priced at "
                             f"{tariff.default_price:.4f}, which is almost certainly not right")
            return ToolResult(ok=True, output="\n".join(lines),
                              metadata={"set": True, "name": tariff.name, "gaps": gaps,
                                        "currency": tariff.currency})

        if op != "set":
            return ToolResult(ok=False, error=f"refused: unknown op {op!r}; use show or set")

        spec = args.get("spec") or {k: v for k, v in args.items() if k != "op"}
        if isinstance(spec, str):
            try:
                spec = json.loads(spec)
            except ValueError:
                return ToolResult(ok=False, error="refused: the tariff is not JSON")
        if not spec.get("rates"):
            return ToolResult(ok=False,
                              error="refused: a tariff needs at least one rate with a price")
        tariff = Tariff.from_dict(spec)
        path = self._tariff_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        gaps = tariff.gaps()
        body = (f"tariff {tariff.name!r} saved to {path} with {len(tariff.rates)} rate(s), "
                f"currency {tariff.currency}")
        if gaps:
            body += (f"\nWARNING: no rate covers hour(s) {gaps}. They will be priced at "
                     f"{tariff.default_price:.4f} -- add a band that covers them.")
        return ToolResult(ok=True, output=body, side_effects=(f"tariff written to {path}",),
                          metadata={"name": tariff.name, "rates": len(tariff.rates), "gaps": gaps})


def _hours_for(text: str) -> float | None:
    text = " ".join((text or "today").split()).strip().lower()
    table = {"today": 24.0, "yesterday": 48.0, "day": 24.0, "week": 168.0,
             "this week": 168.0, "month": 720.0, "this month": 720.0}
    if text in table:
        return table[text]
    parts = text.split()
    if parts and parts[0].replace(".", "", 1).isdigit():
        number = float(parts[0])
        if len(parts) > 1 and parts[1].startswith("h"):
            return number
        return number * 24
    return None


def _next_rate_change(tariff: Tariff, now: datetime):
    """When the price next changes, and to what. `None` for a flat
    tariff, where the honest answer is "it does not"."""
    current = tariff.rate_at(now)
    for ahead in range(1, 25):
        when = (now + timedelta(hours=ahead)).replace(minute=0, second=0, microsecond=0)
        upcoming = tariff.rate_at(when)
        if upcoming.name != current.name:
            return when, upcoming
    return None


def energy_tools(config, **kwargs) -> list:
    return [EnergyStatusTool(config, **kwargs), EnergyReportTool(config, **kwargs),
            EnergyTariffTool(config, **kwargs)]


__all__ = ["EnergyReportTool", "EnergyStatusTool", "EnergyTariffTool", "energy_tools"]
