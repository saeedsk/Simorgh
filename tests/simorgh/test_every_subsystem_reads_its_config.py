"""A setting written in simorgh.toml has to reach the subsystem.

The dominant bug shape in this codebase is a designed slot with one
side implemented and nobody writing to it, and configuration was the
largest instance of it. Every service is handed its own `[section]` --
`kernel/context.py` builds `ctx.config` for exactly that purpose -- and
on 2026-09-08 eleven of the sixteen never read it. The settings
existed, were documented, were parsed into a Config dataclass with a
`from_mapping`, and nothing ever called it. Editing the file changed
nothing at all, silently.

The most expensive instance was `[ledger] retention`: the section was
read at boot, but only into the mapping that builds the ledger
*client*. The Service that owns the retention policy -- the thing that
actually deletes anything -- was constructed with no config, so every
retention rule was ignored and the defaults ran. Unbounded trace
retention is what produced 192,332 trace streams in one day.

This file is the assertion that was missing: not "the service has a
config attribute" but "a value in the section arrives in it".
"""

from __future__ import annotations

import unittest
from unittest import mock

from simorgh.kernel.context import Context
from tests.simorgh.helpers import FakeClock


def _ctx(section: dict) -> Context:
    """A Context carrying nothing but the section under test. Every
    service here reads `ctx.config` before it touches anything else."""
    return mock.MagicMock(spec=Context, config=section, clock=FakeClock())


class TestASettingReachesItsSubsystem(unittest.IsolatedAsyncioTestCase):
    async def _started(self, service, section: dict):
        ctx = _ctx(section)
        try:
            await service.start(ctx)
        except Exception:  # noqa: BLE001 -- the rest of start() needs a real bus; the adopt is first
            pass
        return service

    async def test_cognition_reads_its_section(self) -> None:
        from simorgh.cognition.service import Service

        service = await self._started(Service(), {"tool_result_max_tokens": 4321})
        self.assertEqual(service._config.tool_result_max_tokens, 4321)  # noqa: SLF001

    async def test_planning_reads_its_section(self) -> None:
        from simorgh.planning.service import Service

        service = await self._started(Service(), {"lease_seconds": 123.0})
        self.assertEqual(service.config.lease_seconds, 123.0)

    async def test_persona_reads_its_section(self) -> None:
        from simorgh.persona.service import Service

        service = await self._started(Service(), {"history_limit": 7})
        self.assertEqual(service.config.history_limit, 7)

    async def test_verification_reads_its_section(self) -> None:
        from simorgh.verification.service import VerificationService

        service = await self._started(
            VerificationService(), {"checklist": {"max_items": 9, "min_answered_fraction": 0.5}})
        self.assertEqual(service._config.checklist_max_items, 9)  # noqa: SLF001

    async def test_voice_reads_its_section(self) -> None:
        from simorgh.voice.service import Service

        service = await self._started(Service(), {"endpoint_silence_ms": 321})
        self.assertEqual(service.config.endpoint_silence_ms, 321)

    async def test_a_config_passed_by_the_caller_still_wins(self) -> None:
        """Tests construct services with an explicit config. Adopting
        the section over the top of that would break every one of them,
        and would be wrong: the caller was more specific."""
        from simorgh.persona.config import Config
        from simorgh.persona.service import Service

        service = await self._started(Service(Config(history_limit=3)), {"history_limit": 99})
        self.assertEqual(service.config.history_limit, 3)


class TestTheLedgerRetentionPolicy(unittest.IsolatedAsyncioTestCase):
    """The instance that cost the most. `retention` is not just stored:
    it is parsed into the policy that decides what gets deleted, so the
    test has to reach the policy, not the config."""

    async def test_a_retention_rule_reaches_the_policy(self) -> None:
        from simorgh.ledger.factory import make_ledger
        from simorgh.ledger.service import Service

        client = make_ledger({"backend": "memory"})
        service = Service(client)
        default_keep_tail = service.config.keep_tail

        ctx = _ctx({"retention": {"trace:": "1d", "keep_tail": default_keep_tail + 500}})
        try:
            await service.start(ctx)
        except Exception:  # noqa: BLE001 -- no real bus here
            pass

        self.assertEqual(service.config.keep_tail, default_keep_tail + 500)
        self.assertNotEqual(service.config.retention, {},
                            "a retention rule written in simorgh.toml must reach the service")
        self.assertIsNotNone(service.policy)


if __name__ == "__main__":
    unittest.main()
