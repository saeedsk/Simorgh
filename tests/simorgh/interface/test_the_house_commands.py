"""`home` and `light`: the house in the words a person would use.

The creator asked for both (2026-09-20): a full family for the house,
and a deliberately redundant short one for the thing anybody types
twenty times a day. `light on kitchen` is three words; the
`tool home_call` form underneath it is a service name and a line of
JSON, which is the right interface for a model and the wrong one for
somebody standing in a dark kitchen.

Every verb resolves to a `home_*` tool call, which means it goes
through `action.proposed` and Guardian exactly as the model's own
call does. These tests assert the translation, because that is where
a sugar layer goes wrong: silently calling the wrong service, or
guessing at a name it should have refused.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest import mock

from simorgh.interface import dispatch


class _Ran(Exception):
    """Carries what `_run_tool` was asked for, out of the call.

    The payload is NOT called `args`: `BaseException.args` is a
    built-in that coerces whatever it is given into a tuple, so a dict
    assigned there comes back as a tuple of its keys -- which is how
    this test first failed, with `tuple indices must be integers`.
    """

    def __init__(self, tool: str, raw: str) -> None:
        super().__init__(tool)
        self.tool = tool
        self.payload = json.loads(raw) if raw.strip().startswith("{") else {"__raw__": raw}


def _call(line: str):
    """Run one command line; return `(tool, args)` or the text it printed."""
    verb, _, rest = line.partition(" ")

    async def _explode(*, bus, ledger, tool, raw, session_id, timeout=0.0, action_id=None):
        raise _Ran(tool, raw)

    handler = dispatch._home if verb == "home" else dispatch._light  # noqa: SLF001
    with mock.patch.object(dispatch, "_run_tool", _explode):
        try:
            outcome = asyncio.run(handler(rest, bus=None, ledger=None, session_id="t"))
        except _Ran as ran:
            return ran.tool, ran.payload
    return outcome.text


class TheHouseFamily(unittest.TestCase):
    def test_on_and_off_do_not_make_the_typist_name_the_domain(self):
        """`homeassistant.turn_on`, not `light.turn_on`: whether Home
        Assistant filed the kettle under `switch` or `light` is the
        entity's business, not the typist's."""
        tool, args = _call("home on kitchen table")
        self.assertEqual(tool, "home_call")
        self.assertEqual(args["service"], "homeassistant.turn_on")
        self.assertEqual(args["target"], "kitchen table")
        self.assertEqual(_call("home off pool")[1]["service"], "homeassistant.turn_off")

    def test_dim_takes_a_percentage_off_the_end(self):
        tool, args = _call("home dim family room 40")
        self.assertEqual((tool, args["service"]), ("home_call", "light.turn_on"))
        self.assertEqual((args["target"], args["brightness_pct"]), ("family room", 40))
        self.assertEqual(_call("home dim family room 40%")[1]["brightness_pct"], 40)

    def test_find_and_state_reach_the_read_only_tools(self):
        self.assertEqual(_call("home find battery")[0], "home_find")
        self.assertEqual(_call("home state light.pool_pool")[0], "home_state")

    def test_a_bare_home_asks_what_is_on(self):
        tool, args = _call("home")
        self.assertEqual(tool, "home_state")
        self.assertEqual(args["target"], "on")

    def test_call_is_the_escape_hatch_and_takes_json(self):
        tool, args = _call('home call fan.set_percentage office {"percentage": 60}')
        self.assertEqual((tool, args["service"]), ("home_call", "fan.set_percentage"))
        self.assertEqual((args["target"], args["percentage"]), ("office", 60))

    def test_bad_json_is_said_plainly_rather_than_sent(self):
        self.assertIn("did not parse", _call('home call fan.set office {nope}'))

    def test_undo_and_scene(self):
        self.assertEqual(_call("home undo light.pool_pool")[0], "home_undo")
        self.assertEqual(_call("home scene movie night")[1]["service"], "scene.turn_on")

    def test_an_unknown_verb_prints_the_family_rather_than_guessing(self):
        text = _call("home frobnicate the kitchen")
        self.assertIn("home find", text)
        self.assertIn("home dim", text)


class TheShortWay(unittest.TestCase):
    def test_both_word_orders_work(self):
        """`light on kitchen` and `light kitchen on` are the same
        sentence, and arguing with somebody about which is correct is
        not a feature."""
        for line in ("light on kitchen table", "light kitchen table on"):
            tool, args = _call(line)
            self.assertEqual((tool, args["service"]), ("home_call", "homeassistant.turn_on"), line)
            self.assertEqual(args["target"], "kitchen table", line)

    def test_off_either_way_round(self):
        for line in ("light off pool", "light pool off"):
            self.assertEqual(_call(line)[1]["service"], "homeassistant.turn_off", line)

    def test_a_number_on_the_end_is_brightness(self):
        tool, args = _call("light kitchen 40")
        self.assertEqual(args["service"], "light.turn_on")
        self.assertEqual((args["target"], args["brightness_pct"]), ("kitchen", 40))

    def test_a_name_alone_asks_what_it_is_doing(self):
        """Not an action. `light kitchen` is a question, and answering
        it by toggling something would be the worst possible guess."""
        tool, args = _call("light kitchen")
        self.assertEqual(tool, "home_state")
        self.assertEqual(args["target"], "kitchen")

    def test_bare_light_lists_them(self):
        tool, args = _call("light")
        self.assertEqual(tool, "home_find")
        self.assertIn("light", args["query"])


if __name__ == "__main__":
    unittest.main()


class WhoSimKnows(unittest.TestCase):
    """`people` (stage 10 item 4): who Sim knows, what they said yes
    to, and what they care about.

    The asymmetry is the design and these tests pin it: READING is a
    World Model query, and every CHANGE goes through the `people`
    tool, which is tier 3. Writing to the store from the terminal
    would be a back door around the one gate that makes consent mean
    anything -- a household gives consent, Sim never records it
    because somebody typed it convincingly.
    """

    def _people(self, line: str):
        asked = {}

        async def _requested(bus, topic, payload, *, timeout=0.0, render=None):
            asked.update({"topic": topic, "payload": payload})
            from simorgh.interface.dispatch import Outcome

            return Outcome("(read)")

        async def _explode(*, bus, ledger, tool, raw, session_id, timeout=0.0, action_id=None):
            raise _Ran(tool, raw)

        with mock.patch.object(dispatch, "_request", _requested), \
             mock.patch.object(dispatch, "_run_tool", _explode):
            try:
                text = asyncio.run(dispatch._people(line, bus=None, ledger=None, session_id="t")).text  # noqa: SLF001
            except _Ran as ran:
                return {"tool": ran.tool, "payload": ran.payload}
        return {"read": asked, "text": text}

    def test_listing_is_a_read_not_a_tool_call(self):
        out = self._people("")
        self.assertEqual(out["read"]["payload"]["what"], "people")

    def test_a_bare_name_asks_about_that_person(self):
        out = self._people("Mara")
        self.assertEqual(out["read"]["payload"]["args"]["name"], "Mara")

    def test_a_grant_goes_through_the_tier_three_tool(self):
        out = self._people("grant Mara wellbeing_checkins")
        self.assertEqual(out["tool"], "people")
        self.assertEqual(out["payload"], {"action": "grant", "name": "Mara",
                                          "permission": "wellbeing_checkins"})

    def test_a_revoke_does_too(self):
        self.assertEqual(self._people("revoke Mara interest_shares")["payload"]["action"], "revoke")

    def test_an_interest_is_added_by_asking(self):
        out = self._people("interest add Aran lego robotics")
        self.assertEqual(out["payload"], {"action": "add_interest", "name": "Aran",
                                          "interest": "lego robotics"})

    def test_a_grant_without_a_permission_lists_the_permissions(self):
        text = self._people("grant Mara")["text"]
        self.assertIn("wellbeing_checkins", text)
        self.assertIn("interest_shares", text)


class NobodyIsShownAsABlank(unittest.TestCase):
    """A person with no permissions says so in words.

    An empty space reads as an oversight, and the whole point is that
    nothing is the default: a fresh install grants nobody anything.
    """

    def test_a_person_who_said_yes_to_nothing_says_so(self):
        from simorgh.interface import peopleview

        text = peopleview.one({"person": {"name": "Otto", "role": "child"}})
        self.assertIn("said yes to: nothing", text)
        self.assertIn("cares about: nothing recorded", text)

    def test_a_permission_is_explained_in_a_persons_words(self):
        from simorgh.interface import peopleview

        text = peopleview.one({"person": {"name": "Mara", "role": "owner",
                                          "permissions": ["wellbeing_checkins"]}})
        self.assertIn("quieter than usual", text)

    def test_nobody_at_all_says_what_to_do_next(self):
        from simorgh.interface import peopleview

        self.assertIn("people link", peopleview.everybody({"people": []}))
