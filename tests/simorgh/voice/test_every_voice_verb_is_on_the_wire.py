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

    def test_the_cli_only_sends_permitted_actions(self):
        source = (_ROOT / "simorgh" / "interface" / "dispatch.py").read_text()
        sent = set(re.findall(r'VOICE_CONTROL_REQUEST, \{"action": "([a-z_]+)"', source))
        self.assertTrue(sent, "the dispatcher sends voice actions; this test found none")
        self.assertEqual(sorted(sent - _enum_actions()), [])


if __name__ == "__main__":
    unittest.main()
