"""Meters, tariffs and what they add up to."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Rate:
    """A price for one slice of time."""

    name: str
    #: Price per kWh, in `currency`. Import price; export is separate,
    #: because net metering is not symmetric anywhere worth modelling.
    price: float
    export_price: float = 0.0
    #: Hours this rate applies, as [start, end) in local time. A window
    #: that wraps midnight is written (22, 7).
    hours: tuple[int, int] = (0, 24)
    #: Months it applies, 1-12. Empty means every month.
    months: tuple[int, ...] = ()
    #: Weekdays it applies, 0=Monday. Empty means every day.
    weekdays: tuple[int, ...] = ()

    def covers(self, when: datetime) -> bool:
        if self.months and when.month not in self.months:
            return False
        if self.weekdays and when.weekday() not in self.weekdays:
            return False
        start, end = self.hours
        if start == end:
            return True
        hour = when.hour
        return start <= hour < end if start < end else (hour >= start or hour < end)


@dataclass(frozen=True)
class Reading:
    """One meter, read once."""

    entity_id: str
    role: str                  # grid_import | grid_export | solar | battery | circuit
    value: float
    unit: str = "kWh"
    at: float = 0.0
    label: str = ""
    #: HA's `state_class`. `total_increasing` means the number is a
    #: lifetime total and only its DIFFERENCE means anything.
    state_class: str = ""

    @property
    def cumulative(self) -> bool:
        return self.state_class in ("total", "total_increasing")


@dataclass
class CostLine:
    hour: datetime
    kwh: float
    rate: str
    price: float
    cost: float


@dataclass
class CostReport:
    currency: str = "USD"
    lines: list[CostLine] = field(default_factory=list)
    imported_kwh: float = 0.0
    exported_kwh: float = 0.0
    import_cost: float = 0.0
    export_credit: float = 0.0

    @property
    def net(self) -> float:
        return self.import_cost - self.export_credit

    def by_rate(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for line in self.lines:
            out[line.rate] = out.get(line.rate, 0.0) + line.cost
        return out


__all__ = ["CostLine", "CostReport", "Rate", "Reading", "Tariff"]


@dataclass(frozen=True)
class Tariff:
    """What the electricity costs.

    Time-of-use with seasons and weekday rules covers nearly every
    domestic tariff; a flat tariff is one rate with no restrictions,
    which falls out of the same structure rather than needing its own.

    `standing_charge` is the daily fee most suppliers add regardless of
    use. Leaving it out makes every bill projection wrong by a fixed
    amount, which is the kind of error that looks like a modelling
    failure rather than a missing constant.
    """

    name: str = "flat"
    currency: str = "USD"
    rates: tuple[Rate, ...] = ()
    standing_charge_per_day: float = 0.0
    #: Used when no rate covers an hour. A tariff with a gap in it is a
    #: misconfiguration, and pricing that hour at zero would hide it.
    default_price: float = 0.0

    def rate_at(self, when: datetime) -> Rate:
        """The most specific rate covering `when`.

        Most specific rather than first: a rule with a season and a
        weekday restriction is a deliberate exception to a general one,
        and declaration order should not decide which wins.
        """
        candidates = [rate for rate in self.rates if rate.covers(when)]
        if not candidates:
            return Rate("unpriced", self.default_price)
        return max(candidates, key=lambda rate: (len(rate.months) > 0) + (len(rate.weekdays) > 0)
                   + (rate.hours != (0, 24)))

    def price_at(self, when: datetime) -> float:
        return self.rate_at(when).price

    def export_price_at(self, when: datetime) -> float:
        return self.rate_at(when).export_price

    def gaps(self) -> list[int]:
        """Hours of a plain weekday no rate covers. `energy_tariff show`
        reports these: a tariff with a hole in it silently prices part
        of the day at zero."""
        from datetime import datetime as _dt

        missing = []
        for hour in range(24):
            probe = _dt(2026, 6, 17, hour)      # a Wednesday, mid-year
            if not any(rate.covers(probe) for rate in self.rates):
                missing.append(hour)
        return missing

    @classmethod
    def from_dict(cls, data: dict) -> "Tariff":
        rates = []
        for row in data.get("rates") or ():
            rates.append(Rate(
                name=str(row.get("name") or "rate"),
                price=float(row.get("price") or 0.0),
                export_price=float(row.get("export_price") or 0.0),
                hours=tuple(row.get("hours") or (0, 24))[:2],
                months=tuple(int(m) for m in (row.get("months") or ())),
                weekdays=tuple(int(d) for d in (row.get("weekdays") or ())),
            ))
        return cls(
            name=str(data.get("name") or "flat"),
            currency=str(data.get("currency") or "USD"),
            rates=tuple(rates),
            standing_charge_per_day=float(data.get("standing_charge_per_day") or 0.0),
            default_price=float(data.get("default_price") or 0.0),
        )
