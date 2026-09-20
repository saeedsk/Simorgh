"""Stage 6 item 3: what Sim itself changed in the house.

Every other source of the entity table is somebody else telling Sim
what happened -- a camera, the TV, a voice in a room. Sim turning the
kitchen light on was not evidence of anything, so asked a minute
later whether the light was on, Sim genuinely did not know. It had
done it.
"""

import types
import unittest

from simorgh.contracts.envelope import Message
from simorgh.contracts import topics


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


def _service():
    """The Service with just enough context to fold one result."""
    from simorgh.worldmodel.facets.home import HomeFacet
    from simorgh.worldmodel.service import Service

    service = Service.__new__(Service)
    clock = _Clock()
    service._home = HomeFacet(clock=clock.now)      # noqa: SLF001
    service._ctx = types.SimpleNamespace(bus=_Bus(), clock=clock)  # noqa: SLF001
    return service


def _result(**payload):
    body = {"ok": True, "tool": "home_call", "action_id": "a1"}
    body.update(payload)
    return Message.new(topics.ACTION_RESULT, source="execution", payload=body)


class SimKnowsWhatItDid(unittest.IsolatedAsyncioTestCase):
    async def test_a_light_sim_turned_on_is_a_light_sim_knows_about(self):
        service = _service()
        await service._on_action_result(_result(metadata={  # noqa: SLF001
            "service": "light.turn_on", "entities": ["light.kitchen_main"],
            "changed": ["light.kitchen_main"], "unchanged": [],
            "after": {"light.kitchen_main": "on"}}))
        entity = service._home.entities["light.kitchen_main"]  # noqa: SLF001
        self.assertEqual((entity.kind, entity.state), ("light", "on"))
        self.assertEqual(entity.detail.get("by"), "sim", "so a person can see who moved it")

    async def test_a_call_the_house_accepted_and_ignored_changes_nothing(self):
        """Home Assistant answers 200 for an unplugged bulb. "The call
        succeeded" and "the house did something" are different facts,
        and recording the first as the second is the failure somebody
        walks into the room and sees."""
        service = _service()
        await service._on_action_result(_result(metadata={  # noqa: SLF001
            "service": "light.turn_on", "entities": ["light.kitchen_main"],
            "changed": [], "unchanged": ["light.kitchen_main"],
            "after": {"light.kitchen_main": "off"}}))
        self.assertEqual(service._home.entities, {})  # noqa: SLF001

    async def test_a_failed_call_and_another_tool_are_both_ignored(self):
        service = _service()
        await service._on_action_result(_result(ok=False, metadata={  # noqa: SLF001
            "service": "light.turn_on", "changed": ["light.kitchen_main"],
            "after": {"light.kitchen_main": "on"}}))
        await service._on_action_result(_result(tool="read_file", metadata={  # noqa: SLF001
            "changed": ["light.kitchen_main"], "after": {"light.kitchen_main": "on"}}))
        self.assertEqual(service._home.entities, {})  # noqa: SLF001

    async def test_an_undo_is_folded_the_same_way(self):
        service = _service()
        await service._on_action_result(_result(tool="home_undo", metadata={  # noqa: SLF001
            "service": "light.turn_off", "entities": ["light.kitchen_main"],
            "changed": ["light.kitchen_main"], "after": {"light.kitchen_main": "off"}}))
        self.assertEqual(service._home.entities["light.kitchen_main"].state, "off")  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
