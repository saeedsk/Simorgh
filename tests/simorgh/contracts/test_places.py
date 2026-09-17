"""Where Sim is, and what this place is called (contracts/places.py).

Two live failures, one missing slot.

"Name Tamagamka as your house." Sim: "Done -- this house is Tamagamka
now." It was not done; there was nowhere to put it, and the name
survived only as one episodic record.

Driving, 2026-09-16: "voice environment everything is same you're still
in the car I'm driving". Sim: "There's no setting that stores it, so
please just tell me again next session" -- honest, and its own honesty
guard had just caught it promising otherwise. Twenty minutes later,
home: "good to be back on the house Wi-Fi", which it inferred from the
words alone. It cannot tell one network from another.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts import places


class PlacesTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "simorgh.toml"
        patch = mock.patch.dict(os.environ, {"SIMORGH_CONFIG": str(self.path)})
        patch.start()
        self.addCleanup(patch.stop)
        places._forget()                      # noqa: SLF001 -- the mtime cache
        self.addCleanup(places._forget)       # noqa: SLF001

    def test_nothing_told_says_nothing(self):
        self.assertEqual(places.place_line(), "")
        self.assertEqual(places.house_name(), "")
        self.assertEqual(places.networks(), {})

    def test_the_house_keeps_its_name_across_a_restart(self):
        """The Tamagamka failure: "Done" without a write."""
        places.remember_house_name("Tamagamka")
        places._forget()                      # noqa: SLF001 -- as a fresh process would
        self.assertEqual(places.house_name(), "Tamagamka")
        self.assertIn("Tamagamka", places.place_line())

    def test_a_network_name_means_a_place(self):
        places.remember_network("Aranet", "home")
        places.remember_network("Woody", "the car")
        self.assertEqual(places.networks(), {"Aranet": "home", "Woody": "the car"})

    def test_a_second_network_does_not_replace_the_first(self):
        """`persist` rewrites the whole table; the nested map has to
        survive that, which is why the TOML dumper had to recurse."""
        places.remember_network("Aranet", "home")
        places.remember_house_name("Tamagamka")
        places.remember_network("Woody", "the car")
        places._forget()                      # noqa: SLF001
        self.assertEqual(places.house_name(), "Tamagamka")
        self.assertEqual(sorted(places.networks()), ["Aranet", "Woody"])

    def test_the_line_refuses_to_pretend_it_can_see_the_network(self):
        """"Good to be back on the house Wi-Fi" was a guess dressed as
        knowledge. Nothing here reads an SSID."""
        places.remember_network("Aranet", "home")
        line = places.place_line()
        self.assertIn("Aranet means home", line)
        self.assertIn("cannot see which network", line)

    def test_one_can_be_forgotten(self):
        places.remember_network("Aranet", "home")
        self.assertTrue(places.forget_network("Aranet"))
        self.assertFalse(places.forget_network("Aranet"))
        self.assertEqual(places.networks(), {})

    def test_a_blank_name_changes_nothing(self):
        places.remember_house_name("Tamagamka")
        self.assertEqual(places.remember_house_name("   "), "")
        self.assertEqual(places.house_name(), "Tamagamka")
        self.assertEqual(places.remember_network("Aranet", ""), ("", ""))
        self.assertEqual(places.networks(), {})

    def test_a_new_value_is_visible_without_a_restart(self):
        """The whole point of fixing this: "tell me again next session"
        is the failure. The cache is keyed on the file's mtime."""
        self.assertEqual(places.house_name(), "")
        places.remember_house_name("Tamagamka")
        self.assertEqual(places.house_name(), "Tamagamka")

    def test_a_broken_settings_file_is_not_fatal(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("this is not valid toml [[[")
        self.assertEqual(places.place_line(), "")


if __name__ == "__main__":
    unittest.main()
