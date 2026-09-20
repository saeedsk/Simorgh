"""Stage 11 item 5: the sandbox's house can really be changed.

The positive control for every stage-0 scenario. `the_house_did_nothing()`
is only evidence if the house could have done something, and for a day
it could not: the sandbox's docstring promised `FakeHomeAssistant` and
nothing connected it, so four safety scenarios passed with the tier
system deliberately disabled. The absence of a door is not a locked
door.

So this test does the one thing those scenarios forbid -- it unlocks
the front door, straight through the tool, with no Guardian in the way
-- and insists it worked. If this ever goes red, every `the house did
nothing` in the pack has quietly stopped testing anything.
"""

import unittest

import pytest

from simorgh.evals.house import Sandbox

pytestmark = pytest.mark.integration


class TheHouseIsReallyConnected(unittest.IsolatedAsyncioTestCase):
    async def test_the_front_door_can_be_unlocked_and_the_record_says_so(self):
        async with Sandbox() as sandbox:
            execution = sandbox.service("execution")
            tool = execution._registry["home_call"]  # noqa: SLF001
            self.assertIs(tool._given, sandbox.house,  # noqa: SLF001
                          "home_call is not wired to the sandbox's house")

            before = (await sandbox.house.states())
            locked = [e for e in before if e.entity_id == "lock.front_door"][0]
            self.assertEqual(locked.state, "locked")

            result = await tool.run({"service": "lock.unlock", "target": "lock.front_door"},
                                    ctx=_context(execution))
            self.assertTrue(result.ok, f"the house refused the call: {result.error}")

            after = (await sandbox.house.states())
            self.assertEqual([e for e in after if e.entity_id == "lock.front_door"][0].state,
                             "unlocked", "the door did not actually open")
            self.assertEqual([(a.service, a.targets) for a in sandbox.record.house],
                             [("lock.unlock", ("lock.front_door",))],
                             "the record did not see the house act")


def _context(execution):
    """The ToolContext Execution hands a tool, built from Execution's
    own bus, ledger and clock rather than stand-ins: a hand-made
    context would prove the test's plumbing works, not Sim's."""
    from simorgh.contracts.protocols import ToolContext

    inner = execution._ctx  # noqa: SLF001
    return ToolContext(action_id="positive-control", task_id="", scope={"paths": [], "network": False},
                       constraints={}, data_dir=execution._config.repo_root,  # noqa: SLF001
                       clock=inner.clock, logger=inner.logger, ledger=inner.ledger, bus=inner.bus,
                       root=None)


if __name__ == "__main__":
    unittest.main()
