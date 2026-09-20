"""Stage 10 item 1: what a person said yes to is an explicit field, granted
by a person and never inferred; the gates that read it refuse a child, a
guest and an unknown voice whatever the record says."""

from __future__ import annotations

import json
import unittest

import pytest

from simorgh.contracts.people import (
    CHECK_IN_ROLES,
    INTEREST_SHARE_ROLES,
    PERMISSIONS,
    Person,
    from_dict,
    household_people,
    may_check_in,
    may_share_interest,
    normalise_interest,
)

pytestmark = pytest.mark.contract


class Permissions(unittest.TestCase):
    def test_a_fresh_install_grants_nothing_to_anybody(self):
        for person in household_people():
            with self.subTest(person=person.name):
                self.assertEqual(person.permissions, ())
                self.assertEqual(person.interests, ())

    def test_a_grant_is_explicit_and_idempotent(self):
        person = Person("soodeh", "Soodeh", "adult").with_permission("wellbeing_checkins")
        self.assertTrue(person.grants("wellbeing_checkins"))
        self.assertFalse(person.grants("interest_shares"))
        self.assertEqual(person.with_permission("wellbeing_checkins").permissions, ("wellbeing_checkins",))
        self.assertEqual(person.without_permission("wellbeing_checkins").permissions, ())

    def test_a_name_that_is_not_a_permission_is_refused_not_ignored(self):
        with self.assertRaises(ValueError):
            Person("x", "X", "adult").with_permission("wellbeing_checkin")     # a typo grants nothing, loudly

    def test_a_permission_is_not_a_preference(self):
        """`preferences["wellbeing_checkins"] = True` is what the model
        reads, not what the gate reads."""
        person = Person("x", "X", "adult", preferences={"wellbeing_checkins": True})
        self.assertFalse(person.grants("wellbeing_checkins"))
        self.assertEqual(may_check_in(person), (False, "X has not said yes to check-ins"))

    def test_the_record_round_trips_and_an_older_file_reads_as_nothing_granted(self):
        person = (Person("a", "Aran", "child").with_permission("interest_shares")
                  .with_interest("Lego robotics"))
        again = from_dict(json.loads(json.dumps(person.to_dict())))
        self.assertEqual(again, person)
        older = from_dict({"person_id": "s", "name": "Soodeh", "role": "adult", "identities": ["voice:soodeh"]})
        self.assertEqual(older.permissions, ())
        self.assertEqual(older.interests, ())
        # A file edited by hand with a permission that does not exist reads
        # as nothing granted rather than as an unknown grant.
        odd = from_dict({"person_id": "s", "name": "S", "role": "adult", "permissions": ["everything", "interest_shares"]})
        self.assertEqual(odd.permissions, ("interest_shares",))

    def test_the_vocabulary_is_short_and_named(self):
        self.assertEqual(PERMISSIONS, ("wellbeing_checkins", "interest_shares"))
        self.assertEqual(CHECK_IN_ROLES, ("owner", "adult"))
        self.assertEqual(INTEREST_SHARE_ROLES, ("owner", "adult", "child"))


class TheCheckInGate(unittest.TestCase):
    def test_nobody_known_is_refused(self):
        ok, why = may_check_in(None)
        self.assertFalse(ok)
        self.assertIn("nobody", why)

    def test_a_guest_or_unknown_is_refused_even_with_the_flag(self):
        for role in ("guest", "unknown"):
            with self.subTest(role=role):
                person = Person("b", "Bobby", role).with_permission("wellbeing_checkins")
                ok, why = may_check_in(person)
                self.assertFalse(ok)
                self.assertIn(role, why)

    def test_a_child_is_refused_even_with_the_flag(self):
        """A child who seems low is a parent's call, not a setting."""
        ira = Person("ira", "Ira", "child").with_permission("wellbeing_checkins")
        ok, why = may_check_in(ira)
        self.assertFalse(ok)
        self.assertIn("child", why)

    def test_an_adult_without_the_grant_is_refused(self):
        ok, why = may_check_in(Person("s", "Soodeh", "adult"))
        self.assertFalse(ok)
        self.assertIn("not said yes", why)

    def test_an_adult_who_said_yes_may_be_checked_in_on(self):
        self.assertEqual(may_check_in(Person("s", "Soodeh", "adult").with_permission("wellbeing_checkins")), (True, ""))
        self.assertEqual(may_check_in(Person("s", "Saeed", "owner").with_permission("wellbeing_checkins")), (True, ""))


class TheShareGate(unittest.TestCase):
    def test_a_child_may_have_something_shared_when_a_parent_said_yes(self):
        aran = Person("aran", "Aran", "child").with_permission("interest_shares")
        self.assertEqual(may_share_interest(aran), (True, ""))

    def test_a_guest_is_refused_even_with_the_flag(self):
        ok, why = may_share_interest(Person("b", "Bobby", "guest").with_permission("interest_shares"))
        self.assertFalse(ok)
        self.assertIn("guest", why)

    def test_without_the_grant_the_family_is_refused_too(self):
        ok, why = may_share_interest(Person("s", "Soodeh", "adult"))
        self.assertFalse(ok)
        self.assertIn("not said yes", why)


class Interests(unittest.TestCase):
    def test_one_spelling_one_line_bounded(self):
        self.assertEqual(normalise_interest("  Lego\nRobotics  "), "lego robotics")
        self.assertEqual(len(normalise_interest("x" * 200)), 60)
        self.assertEqual(normalise_interest("   "), "")

    def test_an_interest_is_added_once_and_can_be_removed(self):
        person = Person("a", "Aran", "child").with_interest("Lego").with_interest("lego").with_interest("chess")
        self.assertEqual(person.interests, ("lego", "chess"))
        self.assertEqual(person.without_interest("LEGO").interests, ("chess",))
        self.assertEqual(person.with_interest("").interests, ("lego", "chess"), "an empty topic is not an interest")


if __name__ == "__main__":
    unittest.main()
