"""Reading the house's meters out of Home Assistant, and costing them.

The trap this module exists for: **HA energy sensors are cumulative.**
A `state_class: total_increasing` sensor reports a lifetime total, so
"the house used 1234.5" is not a number anyone wants -- the difference
between two readings is. Treating the raw value as consumption
overstates a day's use by several years of it, and the result looks
plausible enough on a dashboard to go unnoticed.

Meter resets are the other half of it. A `total_increasing` sensor is
allowed to go back to zero when a device is replaced or a firmware
update loses its counter; HA signals that with `last_reset`, and a
naive subtraction across one produces a large negative number that
turns into a large negative bill.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .api import CostLine, CostReport, Reading, Tariff

#: Which config key feeds which role.
ROLES = ("grid_import", "grid_export", "solar", "battery_soc", "house_power")


def reading_from(entity, *, role: str, at: float = 0.0) -> Reading | None:
    """One HA entity as a meter reading, or None when it is not a
    number. An unavailable sensor is not a zero -- pricing it as zero
    would quietly report a day with no electricity used."""
    if entity is None:
        return None
    value = entity.numeric
    if value is None:
        return None
    return Reading(entity_id=entity.entity_id, role=role, value=value,
                   unit=entity.unit or "kWh", at=at, label=entity.name,
                   state_class=str(entity.attributes.get("state_class") or ""))


def consumed(first: Reading | None, last: Reading | None) -> float:
    """kWh between two readings of the same meter.

    Returns 0 rather than a negative number when the meter has gone
    backwards. A counter reset is not negative consumption, and a bill
    that goes down because a device was replaced is worse than one that
    misses an hour.
    """
    if last is None:
        return 0.0
    if not last.cumulative:
        # A `measurement` sensor already reports the quantity for the
        # period, so it needs no earlier reading -- and requiring one
        # made every non-cumulative meter report zero.
        return max(last.value, 0.0)
    if first is None:
        return 0.0
    delta = last.value - first.value
    return delta if delta >= 0 else 0.0


def cost_of(hourly, tariff: Tariff, *, exported=None) -> CostReport:
    """Cost a series of `(hour, kWh)` pairs.

    Hour by hour rather than by a daily average, because that is the
    whole point of a time-of-use tariff and averaging is exactly the
    error it is designed to punish. It also makes a day containing a
    daylight-saving change come out right: the hours are whatever the
    local calendar actually had, and one of them is counted twice or
    not at all without any special case here.
    """
    report = CostReport(currency=tariff.currency)
    for hour, kwh in hourly:
        rate = tariff.rate_at(hour)
        cost = kwh * rate.price
        report.lines.append(CostLine(hour=hour, kwh=kwh, rate=rate.name, price=rate.price,
                                     cost=cost))
        report.imported_kwh += kwh
        report.import_cost += cost
    for hour, kwh in (exported or ()):
        credit = kwh * tariff.export_price_at(hour)
        report.exported_kwh += kwh
        report.export_credit += credit
    return report


def add_standing_charge(report: CostReport, tariff: Tariff, *, days: float) -> CostReport:
    """Most suppliers add a daily fee regardless of use. Leaving it out
    makes every projection wrong by a fixed amount, which reads as a
    modelling failure rather than a missing constant."""
    report.import_cost += tariff.standing_charge_per_day * days
    return report


def project_bill(report: CostReport, *, elapsed_days: float, cycle_days: float = 30.0) -> float:
    """What the cycle looks like at this rate. Linear on purpose: a
    fancier projection over four days of data is false precision, and
    the number is for noticing a doubling, not for accounting."""
    if elapsed_days <= 0:
        return 0.0
    return report.net / elapsed_days * cycle_days


def hourly_from_history(rows, *, cumulative: bool) -> list[tuple[datetime, float]]:
    """HA history rows -> `(hour, kWh)`.

    HA returns a row per state change, not per hour, so this buckets by
    hour and differences within each bucket for a cumulative meter.
    """
    parsed: list[tuple[datetime, float]] = []
    for row in rows or ():
        value = _number(row.get("state"))
        when = _time(row.get("last_changed") or row.get("last_updated"))
        if value is None or when is None:
            continue
        parsed.append((when, value))
    if not parsed:
        return []
    parsed.sort()

    buckets: dict[datetime, list[float]] = {}
    for when, value in parsed:
        hour = when.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(hour, []).append(value)

    out: list[tuple[datetime, float]] = []
    hours = sorted(buckets)
    if not cumulative:
        for hour in hours:
            values = buckets[hour]
            out.append((hour, sum(values) / len(values)))
        return out

    for index, hour in enumerate(hours):
        values = buckets[hour]
        start = values[0]
        end = buckets[hours[index + 1]][0] if index + 1 < len(hours) else values[-1]
        delta = end - start
        out.append((hour, delta if delta >= 0 else 0.0))
    return out


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _time(value) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone().replace(tzinfo=None)


__all__ = ["ROLES", "add_standing_charge", "consumed", "cost_of", "hourly_from_history",
           "project_bill", "reading_from"]
