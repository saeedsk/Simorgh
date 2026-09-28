"""A phone says whose it is when it pairs; the book re-reads its file.

2026-09-27, the creator, from the app outside the house: "the app needs
an owner -- when I install the app on my phone, I identify who I am."
Every paired phone had `person: ""`, so Guardian judged every request
from the app as a stranger's, and lights and music were refused."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from simorgh.interface.devices import DeviceBook, household_member


class APhoneSaysWhoseItIs(unittest.TestCase):
    def setUp(self):
        self.book = DeviceBook(Path(tempfile.mkdtemp()) / "devices.json")

    def _pair(self, *, terminal="", phone=""):
        self.book.begin_pairing(name="phone", person=terminal)
        got = self.book.redeem(self.book.pending().code, person=phone)
        self.assertNotIsInstance(got, str, got)
        return got

    def test_the_phone_names_its_owner(self):
        device, _ = self._pair(phone="saeed")
        self.assertEqual(device.person, "Saeed")

    def test_only_someone_in_the_household(self):
        device, _ = self._pair(phone="Mallory")
        self.assertEqual(device.person, "")
        self.assertEqual(household_member("mallory"), "")

    def test_the_terminal_wins(self):
        device, _ = self._pair(terminal="Iris", phone="Saeed")
        self.assertEqual(device.person, "Iris")

    def test_an_outside_change_is_read_not_overwritten(self):
        device, token = self._pair()
        raw = json.loads(self.book.path.read_text())
        raw["devices"][0]["person"] = "Saeed"
        self.book.path.write_text(json.dumps(raw))
        later = time.time() + 5
        os.utime(self.book.path, (later, later))
        self.assertEqual(self.book.resolve(token).person, "Saeed")
        self.assertEqual(json.loads(self.book.path.read_text())["devices"][0]["person"], "Saeed",
                         "the save after resolve keeps it")


if __name__ == "__main__":
    unittest.main()
