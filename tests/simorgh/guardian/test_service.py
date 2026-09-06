"""`simorgh/guardian/service.py`'s pure helper(s). The trust-posture
wiring these feed (`_on_drift_detected`, `_on_health_finding`,
`_on_provider_status`, `_on_resume`) is exercised end to end, through a
real Kernel, in
`tests/simorgh/integration/test_trust_posture_tightening.py` -- this
file covers only `_fraction_used`'s own branches in isolation, since a
full Kernel boot is overkill for a pure function of a dict.
"""

from __future__ import annotations

import unittest

from simorgh.guardian.service import _fraction_used


class TestFractionUsed(unittest.TestCase):
    def test_exhausted_flag_wins_regardless_of_spend(self) -> None:
        self.assertEqual(_fraction_used({"exhausted": True, "spend_usd": 0.0, "max_spend_usd": 100.0}, True), 1.0)

    def test_unavailable_provider_is_treated_as_fully_used(self) -> None:
        self.assertEqual(_fraction_used({}, False), 1.0)

    def test_spend_over_max_spend_is_the_fraction(self) -> None:
        self.assertAlmostEqual(_fraction_used({"spend_usd": 4.5, "max_spend_usd": 10.0}, True), 0.45)

    def test_falls_back_to_calls_over_max_calls_when_no_spend_cap(self) -> None:
        self.assertAlmostEqual(_fraction_used({"calls": 7, "max_calls": 10}, True), 0.7)

    def test_no_configured_cap_is_zero_pressure_not_fabricated(self) -> None:
        self.assertEqual(_fraction_used({"spend_usd": 4.5, "max_spend_usd": None}, True), 0.0)

    def test_empty_budget_object_is_zero_pressure(self) -> None:
        self.assertEqual(_fraction_used({}, True), 0.0)


if __name__ == "__main__":
    unittest.main()
