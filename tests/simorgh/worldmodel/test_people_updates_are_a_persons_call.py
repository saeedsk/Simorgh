"""Stage 6 item 4: changing who somebody is, is a person's call.

Sim used to learn identities by inference -- `persona/user_model.py`
scraped "call me X" out of sentences. An inferred identity is an
identity claimed by whoever says the right sentence, and linking a
handle to a name decides whose memories that handle reads and what its
role may ask for.

So it is a tool, and the tool is tier 3: Guardian asks a person every
time, in every posture. These tests pin the tier (the part that makes
it safe) and the store's own refusals (the part that makes it honest).
"""

import unittest

from simorgh.contracts.tiers import tier_of
from simorgh.guardian.api import Proposal
from simorgh.worldmodel.facets.people import PeopleFacet


def _proposal(tool: str, reversibility: str = "reversible") -> Proposal:
    return Proposal(action_id="a1", tool=tool, args={}, scope={}, reversibility=reversibility,
                    rationale="", proposed_by="orchestration")


class TheTier(unittest.TestCase):
    def test_changing_who_sim_trusts_needs_a_person(self):
        tier, why = tier_of(_proposal("people"))
        self.assertEqual(tier, 3)
        self.assertIn("trust", why)

    def test_being_reversible_does_not_lower_it(self):
        """A link can be unlinked. That is not the point: between the
        two, the handle reads somebody's memories."""
        self.assertEqual(tier_of(_proposal("people", "reversible"))[0], 3)


class TheStore(unittest.TestCase):
    def setUp(self):
        self.people = PeopleFacet()

    def test_a_link_makes_a_handle_resolve_to_the_person(self):
        self.people.link("Ira", "telegram:irak")
        person = self.people.resolve("telegram:irak")
        self.assertIsNotNone(person)
        self.assertEqual(person.name, "Ira")

    def test_an_unlink_leaves_nobody_rather_than_the_handle(self):
        self.people.link("Ira", "telegram:irak")
        self.people.unlink("telegram:irak")
        self.assertIsNone(self.people.resolve("telegram:irak"))

    def test_unlinking_something_nobody_linked_says_so(self):
        self.assertIsNone(self.people.unlink("telegram:nobody"))

    def test_a_role_on_somebody_unknown_says_so(self):
        self.assertIsNone(self.people.set_role("Nobody At All", "adult"))

    def test_one_identity_one_spelling(self):
        """A second spelling is a second person as far as a lookup is
        concerned, so they are normalised on the way in."""
        self.people.link("Ira", "Telegram:@Irak")
        self.assertIsNotNone(self.people.resolve("telegram:irak"))


if __name__ == "__main__":
    unittest.main()
