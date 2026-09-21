"""`tools/house.py`: one scenario in the foreground (stage 11 item 11).

The gate runs the pack and prints a verdict. This runs ONE and prints
the conversation, because a red expectation tells you a rule is wrong
and only the transcript tells you what the room sounded like when it
went wrong.

Only the selection is tested here. Actually playing a scenario boots a
Kernel, which the evals suite already does and which has no business
happening twice.
"""

import importlib.util
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[3] / "tools" / "house.py"
_spec = importlib.util.spec_from_file_location("house_tool", _PATH)
house = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(house)


class PickingAScenario(unittest.TestCase):
    def test_an_exact_id_wins_over_the_prefixes_it_contains(self):
        """`stage9/a-lamp-is-not-a-decision` must not become ambiguous
        the day somebody adds `...-decision-2`."""
        found = house._matching("stage9/a-lamp-is-not-a-decision")
        self.assertEqual([s.id for s in found], ["stage9/a-lamp-is-not-a-decision"])

    def test_a_prefix_finds_the_one_it_names(self):
        found = house._matching("stage9/a-lamp")
        self.assertEqual([s.id for s in found], ["stage9/a-lamp-is-not-a-decision"])

    def test_a_prefix_matching_several_returns_them_all_to_be_refused(self):
        found = house._matching("stage9/")
        self.assertGreater(len(found), 1)

    def test_nothing_matches_nothing(self):
        self.assertEqual(house._matching("stage99/nope"), [])

    def test_an_ambiguous_prefix_is_refused_rather_than_run(self):
        """Running six scenarios in the foreground when one was asked
        for wastes the minutes this tool exists to save."""
        self.assertEqual(house.main(["stage9/"]), 2)

    def test_nothing_matching_is_an_error_not_an_empty_pass(self):
        self.assertEqual(house.main(["stage99/nope"]), 2)

    def test_listing_needs_no_scenario_and_succeeds(self):
        self.assertEqual(house.main(["--list"]), 0)
        self.assertEqual(house.main([]), 0)

    def test_every_scenario_is_reachable_by_its_own_id(self):
        """A scenario nobody can name is a scenario nobody debugs."""
        for scenario in house._scenarios():
            self.assertEqual([s.id for s in house._matching(scenario.id)], [scenario.id], scenario.id)


if __name__ == "__main__":
    unittest.main()
