"""A verb the command offers must be one the wire accepts.

Twice on 2026-09-21 I added something to a handler and not to the
schema that carries it, and both reached the creator as a traceback
in his own session:

    ContractError: learn.competence.updated: $.payload.samples:
        expected type integer, got float
    ContractError: voice.control.request: $.payload.action:
        'tidy' not in enum [...]

The second is this one. `voice tidy` was written into the dispatcher,
the service and the completion menu, and the `action` enum on
`voice.control.request` still listed fourteen verbs. Every module
tier was green: they test the handler, and the handler was right.

Three lists have to agree -- what the CLI sends, what the service
answers to, and what the contract permits -- and nothing joined
them.
"""

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def _enum_actions() -> set[str]:
    """Read from the GENERATED schema, not the dataclass: that file is
    what the bus validates against, and the two have come apart."""
    import json

    path = _ROOT / "simorgh" / "contracts" / "schema" / "voice.control.request.v1.json"
    return set(json.loads(path.read_text())["properties"]["action"]["enum"])


def _service_actions() -> set[str]:
    """The verbs `_people_action` and `_on_control` actually answer."""
    source = (_ROOT / "simorgh" / "voice" / "service.py").read_text()
    found = set()
    for match in re.finditer(r'action (?:==|in) \(?((?:"[a-z_]+"(?:, )?)+)\)?', source):
        found |= set(re.findall(r'"([a-z_]+)"', match.group(1)))
    return found


class TheThreeListsAgree(unittest.TestCase):
    def test_tidy_is_on_the_wire(self):
        """The verb that found this."""
        self.assertIn("tidy", _enum_actions())

    def test_every_verb_the_service_answers_is_permitted(self):
        missing = sorted(_service_actions() - _enum_actions())
        self.assertEqual(missing, [],
                         f"the service answers these and the contract refuses them: {missing}")

    def test_every_permitted_verb_is_answered(self):
        """The other direction: an action the wire allows and nothing
        handles is a command that reports success and does nothing."""
        unhandled = sorted(_enum_actions() - _service_actions())
        self.assertEqual(unhandled, [],
                         f"the contract permits these and nothing answers them: {unhandled}")

    def test_the_usage_line_names_every_verb_that_takes_a_name(self):
        """A FOURTH list, and the one that caught me: the creator
        typed `voice relearn` and the "unknown verb" line listed
        fourteen verbs without `tidy`, which had shipped hours
        earlier. A verb nobody is told about is a verb nobody uses.
        """
        source = (_ROOT / "simorgh" / "interface" / "dispatch.py").read_text()
        usage = source[source.index('unknown verb {verb!r} -- status'):][:600]
        for verb in ("tidy", "relearn", "enroll", "forget", "pronounce", "whois", "people"):
            self.assertIn(verb, usage, f"`voice {verb}` exists and the usage line does not say so")

    def test_the_did_you_mean_list_knows_them_too(self):
        """`voice relerarn` should suggest `relearn`, not list
        everything."""
        source = (_ROOT / "simorgh" / "interface" / "dispatch.py").read_text()
        close = source[source.index("difflib.get_close_matches(verb"):][:400]
        for verb in ("tidy", "relearn"):
            self.assertIn(f'"{verb}"', close)

    def test_the_cli_only_sends_permitted_actions(self):
        source = (_ROOT / "simorgh" / "interface" / "dispatch.py").read_text()
        sent = set(re.findall(r'VOICE_CONTROL_REQUEST, \{"action": "([a-z_]+)"', source))
        self.assertTrue(sent, "the dispatcher sends voice actions; this test found none")
        self.assertEqual(sorted(sent - _enum_actions()), [])


if __name__ == "__main__":
    unittest.main()


class WhatAVerbSaysIsShown(unittest.TestCase):
    """A handler's message was shown only if it began with one of
    eight approved words.

    Live, 2026-09-21: the creator typed `voice tidy Saeed`, the tidy
    ran, and the console printed "voice agent speaking · stt
    whisper_server · 0 turn(s) this session". He could not tell
    whether anything had happened. `controlled` matched the detail
    against a whitelist of opening words -- "barge-in", "forgot",
    "enrolling" and five more -- and fell back to the status panel
    for everything else, so every new verb paid the same toll.
    """

    STATE = {"ok": True, "state": "listening", "stt": "whisper", "tts": "kokoro", "turns": 0}

    def _shown(self, detail: str) -> str:
        from simorgh.interface.voiceview import controlled

        return controlled({**self.STATE, "detail": detail})

    def test_a_message_with_no_blessed_prefix_is_shown(self):
        said = self._shown("dropped 7 learnt take(s) from Saeed: agreement 0.59 -> 0.76.")
        self.assertIn("dropped 7", said)

    def test_the_old_ones_still_are(self):
        self.assertIn("forgot every voice", self._shown("forgot every voice: Ira, Iris"))
        self.assertIn("is said", self._shown('Ira is said "Eye-ra" from now on'))

    def test_no_message_falls_back_to_the_state(self):
        """The state verbs return an empty detail, and that is the
        honest signal for "nothing to say but the state"."""
        self.assertNotIn("voice: ", self._shown(""))

    def test_a_settings_panel_is_still_a_panel(self):
        self.assertNotIn("voice: voice settings", self._shown("voice settings\n  a = b"))
