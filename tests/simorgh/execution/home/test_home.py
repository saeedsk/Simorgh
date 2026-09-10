"""The house: the shared Home Assistant client, the safety policy, the
entity registry, and the `home_*` tools.

Everything runs against `FakeHomeAssistant`, which lives in
`contracts/home/` rather than under `tests/` because Execution's tool
tests need it and may not import the test tree. It behaves like a real
house in the two ways that matter: a call on an unavailable device
succeeds and changes nothing, and an unknown service is refused."""

from __future__ import annotations

import unittest
from pathlib import Path

from simorgh.contracts.home.api import Entity, ServiceResult
from simorgh.contracts.home.client import HomeAssistantClient, HomeUnavailable
from simorgh.contracts.home.fakes import FakeHomeAssistant
from simorgh.contracts.home.policy import (
    CLIMATE_HARD_LIMITS,
    classify_call,
    reversibility_of,
)
from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.home.registry import Ambiguous, NotFound, Registry
from simorgh.execution.home.tools import home_tools


def _ctx() -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                       data_dir=Path("."), clock=None, logger=None, ledger=None)


class EntityTestCase(unittest.TestCase):
    def test_the_domain_and_object_id_come_out_of_the_entity_id(self):
        entity = Entity("light.kitchen_main", "on")
        self.assertEqual((entity.domain, entity.object_id), ("light", "kitchen_main"))

    def test_a_friendly_name_is_preferred_over_the_object_id(self):
        self.assertEqual(Entity("light.x", "on", {"friendly_name": "Kitchen main"}).name,
                         "Kitchen main")

    def test_unavailable_and_unknown_are_not_available(self):
        for state in ("unavailable", "unknown", ""):
            self.assertFalse(Entity("light.x", state).available, state)

    def test_a_numeric_state_is_offered_as_a_number(self):
        self.assertEqual(Entity("sensor.x", "9.5").numeric, 9.5)

    def test_a_non_numeric_state_is_not_a_number_rather_than_a_crash(self):
        self.assertIsNone(Entity("light.x", "on").numeric)


class ServiceResultTestCase(unittest.TestCase):
    def test_a_state_that_moved_is_reported_as_changed(self):
        result = ServiceResult("light.turn_on", ("light.a",),
                               {"light.a": Entity("light.a", "off")},
                               {"light.a": Entity("light.a", "on")})
        self.assertEqual(result.changed, ("light.a",))
        self.assertEqual(result.unchanged, ())

    def test_a_state_that_did_not_move_is_reported_as_unchanged(self):
        """Home Assistant answers 200 for a call on an unplugged
        device, so the call succeeding and the house doing something
        are different facts."""
        result = ServiceResult("light.turn_on", ("light.a",),
                               {"light.a": Entity("light.a", "off")},
                               {"light.a": Entity("light.a", "off")})
        self.assertEqual(result.changed, ())
        self.assertIn("nothing changed", result.render())

    def test_an_attribute_only_change_counts(self):
        result = ServiceResult("light.turn_on", ("light.a",),
                               {"light.a": Entity("light.a", "on", {"brightness": 10})},
                               {"light.a": Entity("light.a", "on", {"brightness": 200})})
        self.assertEqual(result.changed, ("light.a",))


class PolicyTestCase(unittest.TestCase):
    """The pure function Guardian and the tool both use, so the label
    proposed and the label enforced cannot drift."""

    def test_a_light_is_unattended(self):
        self.assertEqual(classify_call("light.turn_on", "light.kitchen"), "unattended")

    def test_unlocking_a_door_always_waits_for_a_person(self):
        self.assertEqual(classify_call("lock.unlock", "lock.front_door"), "human")

    def test_disarming_the_alarm_always_waits_for_a_person(self):
        self.assertEqual(classify_call("alarm_control_panel.alarm_disarm", "alarm.house"), "human")

    def test_opening_a_garage_always_waits_for_a_person(self):
        self.assertEqual(classify_call("cover.open_cover", "cover.garage"), "human")

    def test_turning_a_camera_off_always_waits_for_a_person(self):
        self.assertEqual(classify_call("camera.turn_off", "camera.front"), "human")

    def test_a_security_word_in_the_entity_id_escalates_whatever_the_domain(self):
        self.assertEqual(classify_call("switch.turn_off", "switch.alarm_siren"), "human")

    def test_nothing_is_routine_while_the_alarm_is_armed(self):
        """The house is in security mode; only a person changes
        anything."""
        self.assertEqual(classify_call("light.turn_on", "light.kitchen",
                                        alarm_state="armed_away"), "human")

    def test_a_thermostat_inside_the_safe_range_is_unattended(self):
        self.assertEqual(classify_call("climate.set_temperature", "climate.hall",
                                        data={"temperature": 20}), "unattended")

    def test_a_thermostat_above_the_hard_limit_waits_for_a_person(self):
        self.assertEqual(classify_call("climate.set_temperature", "climate.hall",
                                        data={"temperature": CLIMATE_HARD_LIMITS[1] + 1}), "human")

    def test_a_thermostat_below_the_freeze_limit_waits_for_a_person(self):
        self.assertEqual(classify_call("climate.set_temperature", "climate.hall",
                                        data={"temperature": CLIMATE_HARD_LIMITS[0] - 1}), "human")

    def test_a_temperature_that_is_not_a_number_waits_for_a_person(self):
        self.assertEqual(classify_call("climate.set_temperature", "climate.hall",
                                        data={"temperature": "warm"}), "human")

    def test_an_unrecognised_domain_is_pessimistic(self):
        """A new HA integration must not be able to widen what Sim may
        do unattended just by existing."""
        self.assertEqual(classify_call("newthing.do_it", "newthing.x"), "human")

    def test_extra_services_can_be_named_in_config(self):
        self.assertEqual(
            classify_call("light.turn_on", "light.x", always_human=("light.turn_on",)), "human")

    def test_human_maps_to_the_label_guardian_escalates_on(self):
        self.assertEqual(reversibility_of("human"), "irreversible")
        self.assertEqual(reversibility_of("unattended"), "reversible")


class ClientTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_construction_never_raises_without_a_token(self):
        client = HomeAssistantClient()
        self.assertFalse(client.configured)

    async def test_probe_names_both_variables_when_neither_is_set(self):
        """`detail` says what is true and `fix` says what to do. They
        used to be one run-on string, which left every renderer able
        only to print the whole thing."""
        status = await HomeAssistantClient().probe()
        self.assertFalse(status.ok)
        self.assertTrue(status.unconfigured, "not set up is not the same as broken")
        self.assertIn("HOME_ASSISTANT_URL", status.fix)
        self.assertIn("HOME_ASSISTANT_TOKEN", status.fix)
        self.assertEqual(set(status.missing), {"HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN"})

    async def test_a_refused_token_says_where_to_get_one(self):
        import urllib.error

        def _opener(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

        status = await HomeAssistantClient(url="http://ha", token="t", opener=_opener).probe()
        self.assertFalse(status.ok)
        self.assertIn("long-lived access token", status.detail)

    async def test_an_unreachable_host_is_a_status_not_an_exception(self):
        import urllib.error

        def _opener(request, timeout=None):
            raise urllib.error.URLError("connection refused")

        status = await HomeAssistantClient(url="http://ha", token="t", opener=_opener).probe()
        self.assertFalse(status.ok)
        self.assertIn("could not reach", status.detail)

    async def test_the_token_never_appears_in_an_error(self):
        import urllib.error

        def _opener(request, timeout=None):
            raise urllib.error.URLError("connection refused")

        status = await HomeAssistantClient(url="http://ha?x=1", token="SUPERSECRET",
                                            opener=_opener).probe()
        self.assertNotIn("SUPERSECRET", status.detail)


class FakeHouseTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_calling_a_service_changes_the_state(self):
        house = FakeHomeAssistant()
        result = await house.call("light.turn_on", entity_ids=("light.kitchen_main",))
        self.assertEqual(result.changed, ("light.kitchen_main",))

    async def test_an_unavailable_device_accepts_the_call_and_does_nothing(self):
        house = FakeHomeAssistant(unavailable=("light.kitchen_main",))
        result = await house.call("light.turn_on", entity_ids=("light.kitchen_main",))
        self.assertEqual(result.changed, ())
        self.assertEqual(result.unchanged, ("light.kitchen_main",))

    async def test_an_unknown_service_is_refused(self):
        with self.assertRaises(HomeUnavailable):
            await FakeHomeAssistant().call("light.explode", entity_ids=("light.kitchen_main",))

    async def test_dry_run_records_the_call_and_changes_nothing(self):
        house = FakeHomeAssistant(dry_run=True)
        result = await house.call("light.turn_on", entity_ids=("light.kitchen_main",))
        self.assertTrue(result.dry_run)
        self.assertEqual((await house.state("light.kitchen_main")).state, "off")


class RegistryTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.house = FakeHomeAssistant()
        self.registry = await Registry.load(
            self.house, aliases={"downstairs": ("light.kitchen_main", "light.living_room")})

    def test_an_entity_id_resolves_to_itself(self):
        self.assertEqual(self.registry.resolve("light.living_room"), ["light.living_room"])

    def test_a_name_resolves(self):
        self.assertEqual(self.registry.resolve("kitchen lights"), ["light.kitchen_main"])

    def test_an_article_does_not_break_a_name(self):
        self.assertEqual(self.registry.resolve("the thermostat"), ["climate.hallway"])

    def test_a_domain_word_is_also_a_name_hint(self):
        """"tv" means the television, not every media player."""
        self.assertEqual(self.registry.resolve("tv"), ["media_player.living_room_tv"])

    def test_an_alias_resolves_to_a_group(self):
        self.assertEqual(self.registry.resolve("downstairs"),
                         ["light.kitchen_main", "light.living_room"])

    def test_a_whole_group_of_one_kind_is_a_legitimate_answer(self):
        self.assertEqual(self.registry.resolve("lights"),
                         ["light.kitchen_main", "light.living_room"])

    def test_a_name_matching_different_kinds_is_refused_with_the_candidates(self):
        """Picking one is a coin flip that turns the wrong thing on."""
        with self.assertRaises(Ambiguous) as caught:
            self.registry.resolve("kitchen")
        self.assertIn("light.kitchen_main", caught.exception.candidates)
        self.assertIn("media_player.kitchen_echo", caught.exception.candidates)

    def test_a_domain_hint_disambiguates(self):
        self.assertEqual(self.registry.resolve("kitchen", domain="light"),
                         ["light.kitchen_main"])

    def test_nothing_matching_says_what_is_nearest(self):
        with self.assertRaises(NotFound) as caught:
            self.registry.resolve("the flux capacitor")
        self.assertIsInstance(caught.exception.nearest, list)

    def test_an_alias_naming_something_absent_is_refused(self):
        registry = Registry(entities=self.registry.entities, aliases={"ghost": ("light.gone",)})
        with self.assertRaises(NotFound):
            registry.resolve("ghost")

    def test_an_empty_target_is_not_found_rather_than_everything(self):
        with self.assertRaises(NotFound):
            self.registry.resolve("  ")

    def test_search_never_raises_because_it_is_for_browsing(self):
        self.assertTrue(self.registry.search("kitchen"))
        self.assertEqual(self.registry.search("zzzz nothing at all"), [])

    def test_domains_are_counted(self):
        self.assertEqual(self.registry.domains()["light"], 2)


class _ToolCase(unittest.IsolatedAsyncioTestCase):
    def _tools(self, *, house=None, **overrides) -> dict:
        self.house = house if house is not None else FakeHomeAssistant()
        config = Config(home_aliases={"downstairs": ["light.kitchen_main", "light.living_room"]},
                        home_settle_s=0.0, **overrides)
        return {tool.name: tool for tool in home_tools(config, client=self.house, env={})}


class UnconfiguredTestCase(unittest.IsolatedAsyncioTestCase):
    """The state this ships in. A house that is not set up must not stop
    Sim booting, and every tool must say exactly what to set."""

    def _tools(self) -> dict:
        return {t.name: t for t in home_tools(Config(), env={})}

    async def test_every_tool_refuses_and_names_both_variables(self):
        for name in ("home_find", "home_state", "home_describe", "home_call"):
            with self.subTest(tool=name):
                args = {"query": "x", "target": "x", "service": "light.turn_on"}
                result = await self._tools()[name].run(args, ctx=_ctx())
                self.assertFalse(result.ok)
                self.assertIn("HOME_ASSISTANT_URL", result.error)
                self.assertIn("HOME_ASSISTANT_TOKEN", result.error)

    async def test_the_refusal_explains_the_architecture(self):
        result = await self._tools()["home_find"].run({"query": "x"}, ctx=_ctx())
        self.assertIn("Home Assistant", result.error)


class HomeReadingToolTestCase(_ToolCase):
    async def test_find_lists_matching_entities(self):
        result = await self._tools()["home_find"].run({"query": "kitchen"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("light.kitchen_main", result.output)
        self.assertTrue(result.metadata["rows"])

    async def test_find_with_no_match_is_an_honest_success(self):
        result = await self._tools()["home_find"].run({"query": "zzzz"}, ctx=_ctx())
        self.assertTrue(result.ok)
        self.assertIn("nothing in the house", result.output)

    async def test_state_reports_the_interesting_attributes(self):
        result = await self._tools()["home_state"].run({"target": "the thermostat"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("temperature", result.output)

    async def test_state_refuses_an_ambiguous_name_with_the_candidates(self):
        result = await self._tools()["home_state"].run({"target": "kitchen"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("light.kitchen_main", result.error)

    async def test_describe_counts_the_house_and_names_the_services(self):
        result = await self._tools()["home_describe"].run({}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("light", result.output)
        self.assertIn("turn_on", result.output)
        self.assertGreater(result.metadata["entities"], 5)

    async def test_describe_names_what_is_unavailable(self):
        house = FakeHomeAssistant()
        house.set_state("light.kitchen_main", "unavailable")
        result = await self._tools(house=house)["home_describe"].run({}, ctx=_ctx())
        self.assertIn("unavailable right now", result.output)


class HomeCallTestCase(_ToolCase):
    async def test_it_turns_a_light_on_and_says_what_changed(self):
        result = await self._tools()["home_call"].run(
            {"service": "light.turn_on", "target": "kitchen lights"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("off -> on", result.output)
        self.assertEqual(result.metadata["changed"], ["light.kitchen_main"])

    async def test_it_says_when_nothing_actually_changed(self):
        """The failure a person can walk into the room and see."""
        house = FakeHomeAssistant(unavailable=("light.kitchen_main",))
        result = await self._tools(house=house)["home_call"].run(
            {"service": "light.turn_on", "target": "kitchen lights"}, ctx=_ctx())
        self.assertTrue(result.ok)
        self.assertIn("Nothing actually changed", result.output)
        self.assertEqual(result.metadata["changed"], [])

    async def test_a_service_home_assistant_does_not_have_is_refused_before_calling(self):
        result = await self._tools()["home_call"].run(
            {"service": "light.explode", "target": "kitchen lights"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("has no", result.error)
        self.assertEqual(self.house.calls, [], "a refusal must not have called anything")

    async def test_something_that_is_not_a_service_name_is_refused(self):
        result = await self._tools()["home_call"].run(
            {"service": "turn on the light", "target": "kitchen"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("light.turn_on", result.error)

    async def test_an_ambiguous_target_is_refused_with_the_candidates(self):
        result = await self._tools()["home_call"].run(
            {"service": "homeassistant.turn_on", "target": "kitchen"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertEqual(self.house.calls, [])

    async def test_data_reaches_home_assistant(self):
        await self._tools()["home_call"].run(
            {"service": "climate.set_temperature", "target": "the thermostat",
             "data": {"temperature": 21}}, ctx=_ctx())
        self.assertEqual(self.house.calls[0][2], {"temperature": 21})

    async def test_the_safety_class_travels_in_the_metadata(self):
        result = await self._tools()["home_call"].run(
            {"service": "lock.unlock", "target": "front door"}, ctx=_ctx())
        self.assertEqual(result.metadata["safety"], "human")

    async def test_a_target_matching_too_many_things_is_refused_as_a_likely_typo(self):
        entities = [(f"light.l{n}", "off", {"friendly_name": f"Lamp {n}"}) for n in range(30)]
        house = FakeHomeAssistant(entities)
        result = await self._tools(house=house, home_max_entities_per_call=5)["home_call"].run(
            {"service": "light.turn_on", "target": "lights"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("over the limit", result.error)

    async def test_all_true_overrides_the_limit(self):
        entities = [(f"light.l{n}", "off", {"friendly_name": f"Lamp {n}"}) for n in range(8)]
        house = FakeHomeAssistant(entities)
        result = await self._tools(house=house, home_max_entities_per_call=5)["home_call"].run(
            {"service": "light.turn_on", "target": "lights", "all": True}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)

    async def test_dry_run_says_what_it_would_do_and_sends_nothing(self):
        house = FakeHomeAssistant(dry_run=True)
        result = await self._tools(house=house, home_dry_run=True)["home_call"].run(
            {"service": "light.turn_on", "target": "kitchen lights"}, ctx=_ctx())
        self.assertTrue(result.ok)
        self.assertTrue(result.metadata["dry_run"])
        self.assertIn("would call", result.output)
        self.assertEqual((await house.state("light.kitchen_main")).state, "off")

    async def test_the_before_snapshot_comes_back_for_undo(self):
        result = await self._tools()["home_call"].run(
            {"service": "light.turn_on", "target": "kitchen lights"}, ctx=_ctx())
        self.assertIn("light.kitchen_main", result.metadata["before"])
        self.assertEqual(result.metadata["before"]["light.kitchen_main"]["state"], "off")


class HomeUndoTestCase(_ToolCase):
    async def test_it_puts_a_light_back(self):
        tools = self._tools()
        called = await tools["home_call"].run(
            {"service": "light.turn_on", "target": "kitchen lights"}, ctx=_ctx())
        self.assertEqual((await self.house.state("light.kitchen_main")).state, "on")

        undone = await tools["home_undo"].run({"before": called.metadata["before"]}, ctx=_ctx())
        self.assertTrue(undone.ok, undone.error)
        self.assertEqual((await self.house.state("light.kitchen_main")).state, "off")

    async def test_undoing_nothing_says_why_there_is_no_hidden_slot(self):
        result = await self._tools()["home_undo"].run({}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("before", result.error)

    async def test_a_domain_with_no_restorable_state_is_reported_not_silently_skipped(self):
        result = await self._tools()["home_undo"].run(
            {"before": {"lock.front_door": {"state": "locked", "attributes": {}}}}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("no restorable state", result.error)


class UndoSaysWhatActuallyWentBackTestCase(unittest.IsolatedAsyncioTestCase):
    """"The call did not raise" and "the thing went back" are different
    facts, and this is the tool whose entire job is the second one.

    Home Assistant answers 200 for a service call on a device that is
    unplugged. Until 2026-09-10 `home_undo` appended to `restored` on
    the absence of an exception and threw the `ServiceResult` away, so
    an observer watched it report `put back: light.living_room -> off`
    with `ok=True` while the bulb was still on. Dry-run mode counted
    every entity as restored too, having sent nothing at all.
    """

    def _undo(self, house: FakeHomeAssistant, config: Config | None = None):
        tools = {t.name: t for t in home_tools(config or Config(), client=house)}
        return tools["home_undo"]

    async def test_a_device_that_did_not_come_back_is_not_called_restored(self):
        import json

        house = FakeHomeAssistant(unavailable=("light.living_room",))
        result = await self._undo(house).run(
            {"op": "undo", "before": json.dumps({"light.living_room": {"state": "off"}})},
            ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertTrue((result.output or "").startswith("could not put back:"))
        self.assertIn("still", result.output or "")
        self.assertEqual(result.metadata["restored"], 0)

    async def test_a_device_that_did_come_back_still_reports_restored(self):
        import json

        house = FakeHomeAssistant()
        await house.call("light.turn_on", entity_ids=("light.living_room",))
        result = await self._undo(house).run(
            {"op": "undo", "before": json.dumps({"light.living_room": {"state": "off"}})},
            ctx=_ctx())
        self.assertTrue(result.ok)
        self.assertIn("put back:", result.output or "")
        self.assertEqual(result.metadata["restored"], 1)

    async def test_a_dry_run_restores_nothing_and_says_so(self):
        """Dry run sends nothing, so nothing went back -- counting those
        as restored is the same lie with the network unplugged."""
        import json

        house = FakeHomeAssistant()

        class _DryRun:
            configured = True

            def __getattr__(self_inner, name):
                return getattr(house, name)

            async def call(self_inner, service, *, entity_ids=(), data=None, settle_s=0.0):
                result = await house.call(service, entity_ids=entity_ids, data=data)
                return ServiceResult(service=service, entities=tuple(entity_ids),
                                     before=result.before, after=result.after, dry_run=True)

        result = await self._undo(_DryRun()).run(
            {"op": "undo", "before": json.dumps({"light.living_room": {"state": "off"}})},
            ctx=_ctx())
        self.assertEqual(result.metadata["restored"], 0)
        self.assertIn("dry run", result.output or "")
