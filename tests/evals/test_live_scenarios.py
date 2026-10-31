"""Live scenarios must be well-formed at import time, so a malformed
one fails the suite instead of silently passing through the harness."""

import re

from simorgh.evals.house.scenarios.live import SCENARIOS

_SLUG = re.compile(r"^live/[a-z0-9]+(-[a-z0-9]+)*$")


def test_live_scenarios_are_well_formed():
    assert SCENARIOS, "no live scenarios at all"
    for scenario in SCENARIOS:
        assert scenario.because, f"{scenario.id}: empty because"
        assert scenario.stage, f"{scenario.id}: empty stage"
        assert _SLUG.match(scenario.id), f"bad id pattern: {scenario.id!r}"
