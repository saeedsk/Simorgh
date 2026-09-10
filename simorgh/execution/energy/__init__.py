"""Domain 3: energy and climate
(`docs/plans/domains/03-energy-climate.md`).

What the house consumes and produces, what it costs by the hour, and
what that adds up to. This is the first domain where Sim saves money
rather than time.

Step 1 of the build order: meters, tariffs, `energy_status` and
`energy_report`. The planner, the thermal model and EMHASS are later
steps -- and each of them is only worth building once the cost figure
is trustworthy, because a plan that optimises the wrong number is
worse than no plan.

Everything reads through the same Home Assistant client the `home_*`
tools use. HA's Energy dashboard is the source of record for what the
house did; what it does not know is what any of it cost, which is the
part that lives here.
"""

from .api import Rate, Reading, Tariff

__all__ = ["Rate", "Reading", "Tariff"]
