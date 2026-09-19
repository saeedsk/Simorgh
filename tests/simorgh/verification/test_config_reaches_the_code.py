"""Two `[verification]` settings that used to change nothing.

- `review.require_real_provider` was parsed, and `_think` sent a literal
  `False` on every `cognition.think`, so a floor reply could stand in for
  a review whatever the file said.
- `action_timeout_seconds`, `think_timeout_seconds`,
  `isolated_suite_timeout_seconds` and `max_denied_actions` had no
  `from_mapping` branch, so simorgh.toml could not set them.

Found writing verification's CONTRACT.md, 2026-09-19.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from simorgh.verification.config import VerificationConfig
from simorgh.verification.service import VerificationService


class _Bus:
    def __init__(self) -> None:
        self.requests: list[tuple[dict, float]] = []

    def new(self, type_: str, payload: dict):
        return SimpleNamespace(type=type_, payload=payload)

    async def request_or_error(self, request, *, timeout: float):
        self.requests.append((request.payload, timeout))
        return SimpleNamespace(payload={"ok": True, "text": "fine", "floor": False})


class TestThinkHonoursTheConfig(unittest.IsolatedAsyncioTestCase):
    async def _think_with(self, config: VerificationConfig) -> tuple[dict, float]:
        service = VerificationService(config)
        bus = _Bus()
        service._ctx = SimpleNamespace(bus=bus)
        await service._think(purpose="verify", prompt="is this right?")
        self.assertEqual(len(bus.requests), 1)
        return bus.requests[0]

    async def test_the_default_requires_a_real_provider(self) -> None:
        payload, _ = await self._think_with(VerificationConfig())
        self.assertIs(payload["require_real_provider"], True)

    async def test_the_toml_can_turn_it_off(self) -> None:
        config = VerificationConfig.from_mapping({"review": {"require_real_provider": False}})
        payload, _ = await self._think_with(config)
        self.assertIs(payload["require_real_provider"], False)

    async def test_think_timeout_from_the_toml_bounds_the_call(self) -> None:
        config = VerificationConfig.from_mapping({"think_timeout_seconds": 42})
        _, timeout = await self._think_with(config)
        self.assertEqual(timeout, 42.0)


class TestTheFourFlatKeysAreSettable(unittest.TestCase):
    def test_each_key_is_read_and_typed(self) -> None:
        config = VerificationConfig.from_mapping({
            "action_timeout_seconds": "9",
            "think_timeout_seconds": 30,
            "isolated_suite_timeout_seconds": 60,
            "max_denied_actions": "4",
        })
        self.assertEqual(config.action_timeout_seconds, 9.0)
        self.assertEqual(config.think_timeout_seconds, 30.0)
        self.assertEqual(config.isolated_suite_timeout_seconds, 60.0)
        self.assertEqual(config.max_denied_actions, 4)
        self.assertIsInstance(config.max_denied_actions, int)

    def test_absent_keys_keep_the_defaults(self) -> None:
        self.assertEqual(VerificationConfig.from_mapping({}), VerificationConfig())


if __name__ == "__main__":
    unittest.main()
