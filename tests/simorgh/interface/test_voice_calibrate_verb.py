"""`voice calibrate` on the wire: what the typed verb sends, and that
`help voice` and the "unknown verb" line both name it."""

import asyncio
import unittest
from unittest import mock

from simorgh.interface import dispatch


def _sent(args: str) -> dict:
    seen: dict = {}

    async def fake(bus, topic, payload, **kw):
        seen.update(payload)
        seen["_topic"] = topic
        return None

    with mock.patch.object(dispatch, "_request", fake):
        asyncio.run(dispatch._voice(None, args))
    return seen


class TheVerb(unittest.TestCase):
    def test_bare_calibrate_starts_for_the_owner(self):
        from simorgh.contracts import topics

        seen = _sent("calibrate")
        self.assertEqual(seen.pop("_topic"), topics.VOICE_CONTROL_REQUEST)
        self.assertEqual(seen, {"action": "calibrate", "value": "start"},
                         "no name: the service picks the household's creator")

    def test_a_name_and_options(self):
        seen = _sent("calibrate Soodeh aloud short fa room=kitchen distance=2m")
        self.assertEqual(seen["name"], "Soodeh")
        self.assertEqual(seen["value"], "start aloud short fa room=kitchen distance=2m")

    def test_the_controls(self):
        for verb in ("status", "stop", "keep", "accept", "skip"):
            with self.subTest(verb=verb):
                seen = _sent(f"calibrate {verb}")
                self.assertEqual((seen["action"], seen["value"]), ("calibrate", verb))
                self.assertNotIn("name", seen)
        self.assertEqual(_sent("calibrate status Aran")["name"], "Aran")

    def test_the_action_is_one_the_wire_permits(self):
        import json
        from pathlib import Path

        schema = Path(dispatch.__file__).resolve().parents[1] / "contracts" / "schema" / "voice.control.request.v1.json"
        permitted = json.loads(schema.read_text())["properties"]["action"]["enum"]
        self.assertIn(_sent("calibrate")["action"], permitted)


class ItIsListed(unittest.TestCase):
    def test_help_voice_lists_it(self):
        from simorgh.interface.parser import SUBCOMMANDS

        entries = dict(SUBCOMMANDS["voice"])
        entry = next(k for k in entries if k.startswith("calibrate"))
        self.assertIn("status|stop", entries[entry])

    def test_the_unknown_verb_line_and_did_you_mean(self):
        with mock.patch.object(dispatch, "_request"):
            said = asyncio.run(dispatch._voice(None, "calibrat")).text
        self.assertIn("voice calibrate", said)
        said = asyncio.run(dispatch._voice(None, "zzzz")).text
        self.assertIn("calibrate [name]", said)


if __name__ == "__main__":
    unittest.main()
