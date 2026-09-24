"""`persist`: changing one setting must not lose the others.

There was no test here, which is how a two-level TOML writer survived in
a file that holds three-level tables. `persist` rewrites the whole file
to change one key, so anything the writer cannot express is destroyed by
an unrelated setting change.
"""

from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from simorgh.contracts.settings import persist

NESTED = """\
[voice]
tts = "chatterbox"

[execution]
secrets = ["vault:*", "SIM_API_TOKEN"]

[cognition.providers.ollama]
model = "qwen3:4b-instruct"
only_purposes = ["chat"]
num_ctx = 8192
timeout_seconds = 60.0
vision_model = "qwen2.5vl:3b"
"""


class PersistKeepsTheRest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "simorgh.toml"
        self.path.write_text(NESTED, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def _reread(self) -> dict:
        with self.path.open("rb") as handle:
            return tomllib.load(handle)

    def test_a_three_level_table_survives_an_unrelated_setting(self):
        """The creator's cameras went blind twice this way: a `voice set`
        rewrote `[cognition.providers.ollama]` as a quoted Python dict,
        the provider vanished from the order, and nothing could look at a
        picture."""
        persist(self.path, "tts_voice", "af_bella")
        ollama = self._reread()["cognition"]["providers"]["ollama"]
        self.assertIsInstance(ollama, dict, f"the table became {type(ollama).__name__}")
        self.assertEqual(ollama["model"], "qwen3:4b-instruct")
        self.assertEqual(ollama["vision_model"], "qwen2.5vl:3b")
        self.assertEqual(ollama["num_ctx"], 8192)
        self.assertEqual(ollama["only_purposes"], ["chat"])

    def test_the_setting_it_was_asked_to_write_is_written(self):
        persist(self.path, "tts_voice", "af_bella")
        self.assertEqual(self._reread()["voice"]["tts_voice"], "af_bella")
        self.assertEqual(self._reread()["voice"]["tts"], "chatterbox", "and the neighbours stay")

    def test_lists_and_other_sections_are_kept(self):
        persist(self.path, "cast_device", "Family Room TV", section="execution")
        data = self._reread()
        self.assertEqual(data["execution"]["secrets"], ["vault:*", "SIM_API_TOKEN"])
        self.assertEqual(data["execution"]["cast_device"], "Family Room TV")

    def test_types_come_back_as_themselves(self):
        persist(self.path, "speak_replies", True)
        persist(self.path, "barge_in_speech_ms", 350)
        data = self._reread()["voice"]
        self.assertIs(data["speak_replies"], True)
        self.assertEqual(data["barge_in_speech_ms"], 350)
        self.assertEqual(self._reread()["cognition"]["providers"]["ollama"]["timeout_seconds"], 60.0)

    def test_persisting_into_a_file_that_does_not_exist_yet(self):
        fresh = self.path.parent / "new.toml"
        persist(fresh, "tts", "kokoro")
        with fresh.open("rb") as handle:
            self.assertEqual(tomllib.load(handle)["voice"]["tts"], "kokoro")

    def test_repeated_writes_do_not_drift(self):
        for voice in ("a", "b", "c"):
            persist(self.path, "tts_voice", voice)
        data = self._reread()
        self.assertEqual(data["voice"]["tts_voice"], "c")
        self.assertEqual(data["cognition"]["providers"]["ollama"]["vision_model"], "qwen2.5vl:3b")


class AnArrayOfTablesSurvives(unittest.TestCase):
    """`[[execution.pim_accounts]]` is the same bug one shape along.

    `_dump` was taught about nested TABLES after the cameras went blind
    twice, but not about an ARRAY of tables. `_toml_value` on a list joins
    its elements, and a dict element falls through to `str(value)` -- so
    the moment any `voice set` rewrote the file, a working Gmail account
    became one string:

        pim_accounts = ["{'name': 'gmail', 'kind': 'imap', ...}"]

    Live 2026-09-24. Every `mail_search` then died on `ValueError:
    dictionary update sequence element #0 has length 1; 2 is required` --
    `parse_accounts` calling `dict()` on that string -- and Sim told the
    creator "it looks like a bug in my mail code, not the account", which
    was half right: the account was fine and the settings WRITER had eaten
    it. Nothing anywhere said the config had changed.
    """

    WITH_ACCOUNTS = "\n".join([
        '[voice]',
        'tts_voice = "af_heart"',
        '',
        '[execution]',
        'cast_device = "Family Room TV"',
        'pim_cloud_llm_may_see = ["public", "personal"]',
        '',
        '[[execution.pim_accounts]]',
        'name = "gmail"',
        'kind = "imap"',
        'url = "imap.gmail.com:993"',
        'username = "someone@example.com"',
        'folders = ["INBOX"]',
        '',
        '[[execution.pim_accounts]]',
        'name = "home"',
        'kind = "caldav"',
        'url = "https://caldav.example.com/dav/"',
        '',
    ])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "simorgh.toml"
        self.path.write_text(self.WITH_ACCOUNTS, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def _reread(self) -> dict:
        with self.path.open("rb") as handle:
            return tomllib.load(handle)

    def test_the_accounts_are_still_tables_after_an_unrelated_setting(self):
        persist(self.path, "tts_voice", "af_bella")
        rows = self._reread()["execution"]["pim_accounts"]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIsInstance(row, dict, f"an account became {type(row).__name__}")
        self.assertEqual(rows[0]["name"], "gmail")
        self.assertEqual(rows[0]["folders"], ["INBOX"])
        self.assertEqual(rows[1]["kind"], "caldav")

    def test_the_whole_file_round_trips_but_for_the_one_key(self):
        before = self._reread()
        persist(self.path, "tts_voice", "af_bella")
        after = self._reread()
        before["voice"]["tts_voice"] = "af_bella"
        self.assertEqual(after, before)

    def test_repeated_writes_do_not_drift(self):
        for voice in ("af_bella", "af_heart", "af_jessica"):
            persist(self.path, "tts_voice", voice)
        rows = self._reread()["execution"]["pim_accounts"]
        self.assertTrue(all(isinstance(r, dict) for r in rows))
        self.assertEqual([r["name"] for r in rows], ["gmail", "home"])

    def test_an_empty_list_is_still_written_as_a_value(self):
        """`[]` is a fine scalar. Only a NON-empty list of dicts is an array
        of tables; treating `[]` as one would silently drop the key."""
        persist(self.path, "pim_accounts", [], section="execution")
        self.assertEqual(self._reread()["execution"]["pim_accounts"], [])

    def test_a_malformed_row_is_skipped_rather_than_raising(self):
        """Defence in depth: even with the writer fixed, a row somebody
        typed by hand as a string must not take the mail tools down with a
        ValueError from `dict()`."""
        from simorgh.domains.pim.accounts import parse_accounts

        good = {"name": "gmail", "kind": "imap", "url": "imap.gmail.com:993"}
        accounts = parse_accounts(["{'name': 'gmail'}", None, 42, good])
        self.assertEqual([a.name for a in accounts], ["gmail"])


if __name__ == "__main__":
    unittest.main()
