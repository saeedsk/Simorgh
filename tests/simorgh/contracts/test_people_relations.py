"""Stage 15 follow-up: `Person.relations`, a person's kin by name, which
memory reads to resolve "my son" for whoever is speaking. Learnt, never
assumed: a fresh install and a record from before the field know none."""

from __future__ import annotations

import unittest

import pytest

from simorgh.contracts.people import RELATION_MAX_CHARS, Person, from_dict, household_people, normalise_relation

pytestmark = pytest.mark.contract


class Relations(unittest.TestCase):
    def test_one_spelling_per_relation(self):
        self.assertEqual(normalise_relation("  My  Son. "), "son")
        self.assertEqual(normalise_relation("our Step Mother"), "step mother")
        self.assertEqual(normalise_relation("x" * (RELATION_MAX_CHARS + 1)), "")

    def test_a_relation_round_trips(self):
        saeed = Person(person_id="saeed", name="Saeed").with_relation("My Son", "  Aran ")
        self.assertEqual(saeed.relations, {"son": "Aran"})
        self.assertEqual(saeed.relation("SON"), "Aran")
        self.assertEqual(saeed.relation("wife"), "")
        self.assertEqual(from_dict(saeed.to_dict()).relations, {"son": "Aran"})
        self.assertEqual(saeed.without_relation("my son").relations, {})

    def test_nonsense_is_refused_not_stored(self):
        saeed = Person(person_id="saeed", name="Saeed")
        for word, name in (("", "Aran"), ("son", ""), ("son", "x" * (RELATION_MAX_CHARS + 1))):
            with self.subTest(word=word, name=name[:5]), self.assertRaises(ValueError):
                saeed.with_relation(word, name)
        on_disk = {"person_id": "saeed", "name": "Saeed", "relations": {"son": "Aran", "": "x", "wife": ""}}
        self.assertEqual(from_dict(on_disk).relations, {"son": "Aran"}, "what could not be written is not read")

    def test_a_record_from_before_relations_knows_nobody(self):
        self.assertEqual(from_dict({"person_id": "saeed", "name": "Saeed"}).relations, {})

    def test_a_fresh_install_assumes_no_relation(self):
        # The creator (contracts/household.py): how the family is related
        # is learnt, not assumed.
        self.assertTrue(all(not p.relations for p in household_people()))
