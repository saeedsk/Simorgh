"""Stage 6 item 3: the house fold reads `action.result` as Execution sends it.

The 2026-09-20 fold read `payload["metadata"]`. `action.result` has no
such field: Execution writes a tool's metadata to a Ledger blob and
sends `metadata_ref`. Its tests built a payload Execution cannot
produce, so they passed while Sim turned the kitchen light on and still
did not know it was on. Every payload here is validated against the
schema first, and its metadata goes through Execution's own
`metadata_for_blob`, so a test here cannot pass on a shape the live
path never sends.
"""

import json
import types
import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
import simorgh.contracts.messages.action  # noqa: F401 -- registers action.result
from simorgh.contracts.registry import get_spec
from simorgh.contracts.home.fakes import FakeHomeAssistant
from simorgh.domains.home.tools import home_tools
from simorgh.domains.media.tools import media_tools
from simorgh.execution.config import Config
from simorgh.execution.service import evidence_fields_of, metadata_for_blob
from simorgh.ledger.backends.memory import InMemoryBackend
from simorgh.ledger.client import LedgerClient
from simorgh.worldmodel.facets.home import FOLDED_TOOLS, NOT_FOLDED_PENDING, HomeFacet, folded_observations


class _Bus:
    def __init__(self) -> None:
        self.published: list = []
        self.source = "worldmodel"

    async def publish(self, message) -> None:
        self.published.append(message)


class _Clock:
    def __init__(self, t: float = 1_790_000_000.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


def _service(ledger=None):
    from simorgh.worldmodel.service import Service

    service = Service.__new__(Service)
    clock = _Clock()
    service._home = HomeFacet(clock=clock.now)      # noqa: SLF001
    service._ctx = types.SimpleNamespace(bus=_Bus(), clock=clock,  # noqa: SLF001
                                         ledger=ledger or LedgerClient(InMemoryBackend()))
    return service


async def _published(service, tool: str, metadata: dict, *, ok: bool = True, evidence_fields=()) -> Message:
    """The `action.result` Execution would publish for this tool call."""
    ref = await service._ctx.ledger.put_blob(  # noqa: SLF001
        json.dumps(metadata_for_blob(metadata, evidence_fields=evidence_fields), default=str).encode("utf-8"),
        content_type="application/json")
    payload = {"action_id": "a1", "ok": ok, "output_ref": "", "stdout_preview": "done",
               "duration_ms": 12, "side_effects": [], "metadata_ref": ref, "tool": tool}
    if not ok:
        payload.update(error="refused: no", error_kind="refused")
    problems = get_spec(topics.ACTION_RESULT).validate(payload)
    assert not problems, problems
    return Message.new(topics.ACTION_RESULT, source="execution", payload=payload)


class TheFoldReadsTheBlob(unittest.IsolatedAsyncioTestCase):
    async def test_a_light_sim_turned_on_is_known_from_the_blob(self):
        service = _service()
        await service._on_action_result(await _published(service, "home_call", {  # noqa: SLF001
            "service": "light.turn_on", "entities": ["light.kitchen_main"],
            "changed": ["light.kitchen_main"], "unchanged": [], "safety": "low", "undoable": True,
            "after": {"light.kitchen_main": "on"}}))
        entity = service._home.entities["light.kitchen_main"]  # noqa: SLF001
        self.assertEqual((entity.kind, entity.state, entity.detail["by"]), ("light", "on", "sim"))

    async def test_a_paused_player_is_paused(self):
        service = _service()
        await service._on_action_result(await _published(service, "media_control", {  # noqa: SLF001
            "op": "pause", "entities": ["media_player.family_room"],
            "changed": ["media_player.family_room"], "before": {}}))
        entity = service._home.entities["media_player.family_room"]  # noqa: SLF001
        self.assertEqual((entity.kind, entity.state), ("media_player", "paused"))
        self.assertEqual(entity.detail["state_from"], "op", "so nobody mistakes it for a reading")

    async def test_something_played_is_playing_with_its_title(self):
        service = _service()
        await service._on_action_result(await _published(service, "media_play", {  # noqa: SLF001
            "what": "http://radio.example/stream", "content_type": "music",
            "entities": ["media_player.kitchen"], "changed": ["media_player.kitchen"], "volume": None}))
        entity = service._home.entities["media_player.kitchen"]  # noqa: SLF001
        self.assertEqual(entity.state, "playing")
        self.assertEqual(entity.detail["title"], "http://radio.example/stream")

    async def test_a_player_the_house_did_not_move_is_not_recorded(self):
        """Home Assistant accepts a call on a player that is off. The
        tool says so (`changed` empty); the table must too."""
        service = _service()
        await service._on_action_result(await _published(service, "media_play", {  # noqa: SLF001
            "what": "x", "content_type": "music", "entities": ["media_player.kitchen"], "changed": []}))
        self.assertEqual(service._home.entities, {})  # noqa: SLF001

    async def test_a_failed_call_and_an_unreadable_blob_fold_nothing(self):
        service = _service()
        await service._on_action_result(await _published(service, "media_control", {  # noqa: SLF001
            "op": "pause", "changed": ["media_player.x"]}, ok=False))
        missing = Message.new(topics.ACTION_RESULT, source="execution", payload={
            "action_id": "a2", "ok": True, "output_ref": "", "stdout_preview": "", "duration_ms": 1,
            "side_effects": [], "metadata_ref": "sha256:nothing-here", "tool": "home_call"})
        await service._on_action_result(missing)  # noqa: SLF001
        self.assertEqual(service._home.entities, {})  # noqa: SLF001

    async def test_a_light_is_not_news(self):
        """Only a situation fact that flips is announced; a light is not one."""
        service = _service()
        service._home.changes()  # noqa: SLF001 -- the baseline, as boot leaves it
        await service._on_action_result(await _published(service, "home_call", {  # noqa: SLF001
            "service": "light.turn_on", "changed": ["light.hall"], "after": {"light.hall": "on"}}))
        self.assertIn("light.hall", service._home.entities)  # noqa: SLF001
        self.assertEqual(service._ctx.bus.published, [])  # noqa: SLF001


def _tool(name: str, house: FakeHomeAssistant):
    config = Config(home_settle_s=0.0)
    tools = {t.name: t for t in (*home_tools(config, client=house), *media_tools(config, client=house))}
    return tools[name]


def _tool_ctx():
    from pathlib import Path

    from simorgh.contracts.protocols import ToolContext

    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                       data_dir=Path("."), clock=None, logger=None, ledger=None)


async def _ran(service, house: FakeHomeAssistant, name: str, args: dict) -> Message:
    """Run the REAL tool against the fake house and publish its result
    the way Execution does: through `metadata_for_blob` with the
    tool's own declared `evidence_fields`."""
    tool = _tool(name, house)
    result = await tool.run(args, ctx=_tool_ctx())
    assert result.ok, result.error
    return await _published(service, name, result.metadata, evidence_fields=evidence_fields_of(tool))


class ReadsAreEvidence(unittest.IsolatedAsyncioTestCase):
    """What Sim READ about the house is folded too (2026-09-22). Until
    Execution kept a bounded copy of the rows in the blob, the only
    record of a `home_state` reading was a file named in the output."""

    async def test_a_state_sim_read_is_in_the_table_as_a_read(self):
        service = _service()
        await service._on_action_result(await _ran(service, FakeHomeAssistant(), "home_state",  # noqa: SLF001
                                                   {"target": "light.living_room"}))
        entity = service._home.entities["light.living_room"]  # noqa: SLF001
        self.assertEqual((entity.kind, entity.state), ("light", "on"))
        self.assertEqual(entity.detail["source"], "read")
        self.assertNotIn("by", entity.detail, "a read is not something Sim did")
        self.assertEqual(entity.at, service._ctx.clock.now(), "seen now, not whenever")  # noqa: SLF001

    async def test_every_player_media_now_read_is_in_the_table(self):
        service = _service()
        await service._on_action_result(await _ran(service, FakeHomeAssistant(), "media_now", {}))  # noqa: SLF001
        tv = service._home.entities["media_player.living_room_tv"]  # noqa: SLF001
        echo = service._home.entities["media_player.kitchen_echo"]  # noqa: SLF001
        self.assertEqual((tv.state, tv.detail["title"], tv.detail["volume"]), ("playing", "The Bear", 25))
        self.assertEqual(echo.state, "idle")
        self.assertEqual(tv.detail["source"], "read")

    async def test_a_read_after_a_change_is_the_newer_word(self):
        """Sim turned the light on; a later read says it is off (a
        person flicked it). The read wins, because it is newer."""
        service = _service()
        await service._on_action_result(await _published(service, "home_call", {  # noqa: SLF001
            "service": "light.turn_on", "changed": ["light.hall"], "after": {"light.hall": "on"}}))
        service._ctx.clock.t += 60  # noqa: SLF001
        await service._on_action_result(await _published(  # noqa: SLF001
            service, "home_state", {"rows": [{"entity_id": "light.hall", "state": "off"}]},
            evidence_fields=("entity_id", "state")))
        entity = service._home.entities["light.hall"]  # noqa: SLF001
        self.assertEqual((entity.state, entity.detail["source"]), ("off", "read"))

    async def test_without_kept_rows_a_read_folds_nothing(self):
        """The old blob shape (rows as a pointer string, nothing kept)
        is no evidence, not a crash."""
        service = _service()
        await service._on_action_result(await _published(  # noqa: SLF001
            service, "home_state", {"rows": [{"entity_id": "light.hall", "state": "off"}]}))
        self.assertEqual(service._home.entities, {})  # noqa: SLF001

    async def test_calendar_reads_are_not_folded_pending_the_creators_decision(self):
        """`cal_list` would put calendar text in every chat prompt,
        the children's included. That is the creator's call, pending."""
        self.assertIn("cal_list", NOT_FOLDED_PENDING)
        self.assertNotIn("cal_list", FOLDED_TOOLS)
        service = _service()
        await service._on_action_result(await _published(  # noqa: SLF001
            service, "cal_list", {"rows": [{"entity_id": "calendar.family", "state": "on",
                                            "title": "dentist"}]},
            evidence_fields=("entity_id", "state", "title")))
        self.assertEqual(service._home.entities, {})  # noqa: SLF001


class AnUndoIsFoldedFromWhatTheToolReports(unittest.IsolatedAsyncioTestCase):
    async def test_a_light_sim_put_back_is_known_to_be_back(self):
        house = FakeHomeAssistant()
        service = _service()
        called = await _tool("home_call", house).run(
            {"service": "light.turn_on", "target": "kitchen lights"}, ctx=_tool_ctx())
        await service._on_action_result(await _published(service, "home_call", called.metadata))  # noqa: SLF001
        self.assertEqual(service._home.entities["light.kitchen_main"].state, "on")  # noqa: SLF001
        await service._on_action_result(await _ran(service, house, "home_undo",  # noqa: SLF001
                                                   {"before": called.metadata["before"]}))
        entity = service._home.entities["light.kitchen_main"]  # noqa: SLF001
        self.assertEqual((entity.state, entity.detail["by"], entity.detail["service"]), ("off", "sim", "undo"))


class WhatEachToolSays(unittest.TestCase):
    def test_ops_that_change_an_attribute_or_land_unpredictably_fold_nothing(self):
        for op in ("volume", "mute", "unmute", "next", "previous", "on", "stop"):
            self.assertEqual(folded_observations("media_control", {"op": op, "changed": ["media_player.a"]}), [],
                             op)

    def test_a_tool_outside_the_house_is_never_folded(self):
        self.assertEqual(folded_observations("read_file", {"changed": ["light.a"], "after": {"light.a": "on"}}), [])

    def test_a_home_call_without_an_after_state_says_nothing(self):
        self.assertEqual(folded_observations("home_call", {"changed": ["light.a"], "after": {}}), [])
        self.assertEqual(folded_observations("home_call", {"changed": ["light.a"], "after": "on"}), [])


if __name__ == "__main__":
    unittest.main()
