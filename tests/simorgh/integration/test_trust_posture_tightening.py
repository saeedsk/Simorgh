"""Trust posture tightening, end to end through a real Kernel running
real Guardian (docs/blueprint/subsystems/09-guardian.md section 5.3,
Phase 4 roadmap item 5: "automatic tightening from failure streaks/
budget pressure; `trusted` mode only via config").

Before this fork, `Service.consumes` only had `action.proposed`,
`system.state.changed`, `task.created`, `task.completed`, `task.failed`
-- the failure-streak trigger (`_on_task_outcome`) was the only one of
section 5.3's four tightening triggers actually wired to a real event.
`reflect.drift.detected`, `reflect.health.finding{severity:critical}`,
and budget pressure via `cognition.provider.status` were named in the
spec and in `Posture`'s own docstring but nothing published them into
`Service`, and `self._budgets` (read by `rules.BudgetRule`) was always
an empty dict -- `BudgetRule` abstained on every proposal regardless of
real spend. All four triggers are exercised here, plus the one
loosening path (`system.resume` -> `baseline_posture`, a human action
only -- `SYSTEM_RESUME`'s publisher allow-list already restricts it to
interface/kernel).
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest import mock

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.guardian.config import Config as GuardianConfig
from simorgh.guardian.service import Service as GuardianService
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING
from tests.simorgh.helpers import FakeClock


def _patched_build_factories(fixture_guardian_config: GuardianConfig):
    real = kernel_registry.build_factories

    # `_build`'s own `guardian_config` parameter has to keep that exact
    # name -- `Kernel.boot` calls it as a keyword arg -- so it inevitably
    # shadows this closure's `fixture_guardian_config`; renamed the
    # closure's own fixture rather than risk `_build`'s body silently
    # reading whatever `Kernel.boot` computed instead of the config this
    # test actually wants to exercise.
    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None, guardian_config=None):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
        factories = {name: factories[name] for name in ("bus", "ledger")}
        factories["guardian"] = lambda: GuardianService(config=fixture_guardian_config)
        return factories

    return _build


async def _pump(n: int = 20) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


class _Collector:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def __call__(self, message: Message) -> None:
        self.messages.append(message)


class _TrustPostureTestCase(unittest.IsolatedAsyncioTestCase):
    async def _boot(self, guardian_config: GuardianConfig) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = LoadedConfig({"runtime": {"data_dir": tmp.name}}, None)
        # Injected clock (not `_WallClock`): Guardian's lock-TTL expiry
        # sleeps through `ctx.clock`, so a real clock would make
        # `TestLockExpiresOnItsOwn` wait the full `lock_ttl_s` for real.
        kernel = Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock())
        patch = mock.patch("simorgh.kernel.service.build_factories", new=_patched_build_factories(guardian_config))
        patch.start()
        self.addCleanup(patch.stop)
        await kernel.boot()
        self.assertEqual(kernel.state.state, RUNNING)
        self.assertEqual(kernel._supervisor.services["guardian"].status, "ok")  # noqa: SLF001
        self.addAsyncCleanup(kernel.shutdown)
        return kernel


class TestDriftDetectedTightensPosture(_TrustPostureTestCase):
    async def test_reflect_drift_detected_tightens_from_trusted_to_guarded(self) -> None:
        kernel = await self._boot(GuardianConfig(mode="trusted", baseline_posture="trusted"))
        bus = kernel.bus
        changed = _Collector()
        await bus.subscribe(topics.GUARDIAN_POSTURE_CHANGED, changed)

        await bus.publish(Message.new(
            topics.REFLECT_DRIFT_DETECTED, source="reflection",
            payload={"kind": "goal", "evidence": "off-goal touches rising", "recommendation": "reground", "task_id": "t1"},
        ))
        await _pump()

        self.assertEqual(len(changed.messages), 1)
        payload = changed.messages[0].payload
        self.assertEqual(payload["mode"], "guarded")
        self.assertIn("drift detected", payload["reason"])


class TestCriticalHealthFindingLocksPosture(_TrustPostureTestCase):
    async def test_critical_health_finding_tightens_to_guarded_by_default(self) -> None:
        """2026-09-07 (guardian/config.py's own note): a critical health
        finding used to hard-lock the whole system until a human typed
        `resume` -- live-caught turning a budget-driven floor reply into
        an hours-long stall. Default is `guarded` now; `locked` stays
        available by config (next test)."""
        kernel = await self._boot(GuardianConfig(mode="trusted", baseline_posture="trusted"))
        bus = kernel.bus
        changed = _Collector()
        await bus.subscribe(topics.GUARDIAN_POSTURE_CHANGED, changed)
        await bus.publish(Message.new(
            topics.REFLECT_HEALTH_FINDING, source="reflection",
            payload={"severity": "critical", "detail": "valence pinned at -1.0"},
        ))
        await _pump()
        self.assertEqual(len(changed.messages), 1)
        self.assertEqual(changed.messages[0].payload["mode"], "guarded")

    async def test_critical_health_finding_locks_but_a_warn_finding_does_not(self) -> None:
        kernel = await self._boot(GuardianConfig(mode="trusted", baseline_posture="trusted",
                                                 health_critical_tightens_to="locked", lock_ttl_s=0.0))
        bus = kernel.bus
        changed = _Collector()
        await bus.subscribe(topics.GUARDIAN_POSTURE_CHANGED, changed)

        await bus.publish(Message.new(
            topics.REFLECT_HEALTH_FINDING, source="reflection",
            payload={"severity": "warn", "detail": "mild oscillation"},
        ))
        await _pump()
        self.assertEqual(changed.messages, [])  # a non-critical finding never tightens

        await bus.publish(Message.new(
            topics.REFLECT_HEALTH_FINDING, source="reflection",
            payload={"severity": "critical", "detail": "valence pinned at -1.0"},
        ))
        await _pump()
        self.assertEqual(len(changed.messages), 1)
        self.assertEqual(changed.messages[0].payload["mode"], "locked")


class TestLockExpiresOnItsOwn(_TrustPostureTestCase):
    async def test_a_lock_returns_to_baseline_after_lock_ttl_s(self) -> None:
        """2026-09-07: a lock is a circuit breaker, not a verdict -- it
        expires back to baseline on its own (`lock_ttl_s`) instead of
        waiting for a human to type `resume`. `FakeClock.sleep` advances
        instantly, so the expiry lands on the next pump."""
        kernel = await self._boot(GuardianConfig(
            mode="trusted", baseline_posture="trusted", health_critical_tightens_to="locked", lock_ttl_s=60.0,
        ))
        bus = kernel.bus
        changed = _Collector()
        await bus.subscribe(topics.GUARDIAN_POSTURE_CHANGED, changed)
        await bus.publish(Message.new(
            topics.REFLECT_HEALTH_FINDING, source="reflection",
            payload={"severity": "critical", "detail": "valence pinned at -1.0"},
        ))
        await _pump(40)
        modes = [m.payload["mode"] for m in changed.messages]
        self.assertEqual(modes, ["locked", "trusted"])
        self.assertIn("lock expired", changed.messages[-1].payload["reason"])

    async def test_lock_ttl_zero_keeps_the_old_wait_for_resume_behavior(self) -> None:
        kernel = await self._boot(GuardianConfig(
            mode="trusted", baseline_posture="trusted", health_critical_tightens_to="locked", lock_ttl_s=0.0,
        ))
        bus = kernel.bus
        changed = _Collector()
        await bus.subscribe(topics.GUARDIAN_POSTURE_CHANGED, changed)
        await bus.publish(Message.new(
            topics.REFLECT_HEALTH_FINDING, source="reflection",
            payload={"severity": "critical", "detail": "valence pinned at -1.0"},
        ))
        await _pump(40)
        self.assertEqual([m.payload["mode"] for m in changed.messages], ["locked"])


class TestBudgetPressureTightensAndFeedsBudgetRule(_TrustPostureTestCase):
    async def test_provider_status_over_the_pressure_threshold_tightens_posture(self) -> None:
        kernel = await self._boot(GuardianConfig(mode="trusted", baseline_posture="trusted", budget_pressure_tighten_at=0.8))
        bus = kernel.bus
        changed = _Collector()
        await bus.subscribe(topics.GUARDIAN_POSTURE_CHANGED, changed)

        # Below the pressure threshold: no tightening.
        await bus.publish(Message.new(
            topics.COGNITION_PROVIDER_STATUS, source="cognition",
            payload={"provider": "claude_code_cli", "available": True,
                     "budget": {"window_seconds": 3600.0, "calls": 1, "max_calls": None,
                                "spend_usd": 1.0, "max_spend_usd": 10.0, "exhausted": False}},
        ))
        await _pump()
        self.assertEqual(changed.messages, [])

        # 95% of the window's cap: over budget_pressure_tighten_at (0.8).
        await bus.publish(Message.new(
            topics.COGNITION_PROVIDER_STATUS, source="cognition",
            payload={"provider": "claude_code_cli", "available": True,
                     "budget": {"window_seconds": 3600.0, "calls": 9, "max_calls": None,
                                "spend_usd": 9.5, "max_spend_usd": 10.0, "exhausted": False}},
        ))
        await _pump()
        self.assertEqual(len(changed.messages), 1)
        payload = changed.messages[0].payload
        self.assertEqual(payload["mode"], "guarded")
        self.assertIn("claude_code_cli", payload["reason"])

    async def test_exhausted_provider_status_also_denies_a_real_model_costing_proposal(self) -> None:
        # Closes the other half of the same gap: `rules.BudgetRule` reads
        # `ctx.budgets`, which `Service` previously never populated --
        # `cognition.provider.status` now feeds it for real.
        kernel = await self._boot(GuardianConfig(mode="guarded", baseline_posture="guarded"))
        bus = kernel.bus
        denied = _Collector()
        await bus.subscribe(topics.ACTION_DENIED, denied)

        await bus.publish(Message.new(
            topics.COGNITION_PROVIDER_STATUS, source="cognition",
            payload={"provider": "claude_code_cli", "available": True,
                     "budget": {"window_seconds": 3600.0, "calls": 10, "max_calls": 10,
                                "spend_usd": 0.0, "max_spend_usd": None, "exhausted": True}},
        ))
        await _pump()

        await bus.publish(Message.new(
            topics.ACTION_PROPOSED, source="test",
            payload={"action_id": "a1", "tool": "draft_patch", "args": {}, "scope": {"network": False},
                     "reversibility": "reversible", "rationale": "test", "proposed_by": "test"},
        ))
        await _pump()
        self.assertEqual(len(denied.messages), 1)
        self.assertEqual(denied.messages[0].payload["layer"], "budget")


class TestSystemResumeIsTheOnlyLooseningPath(_TrustPostureTestCase):
    async def test_resume_resets_a_tightened_posture_to_baseline(self) -> None:
        kernel = await self._boot(GuardianConfig(mode="trusted", baseline_posture="trusted"))
        bus = kernel.bus
        changed = _Collector()
        await bus.subscribe(topics.GUARDIAN_POSTURE_CHANGED, changed)

        await bus.publish(Message.new(
            topics.REFLECT_DRIFT_DETECTED, source="reflection",
            payload={"kind": "goal", "evidence": "e", "recommendation": "reground", "task_id": "t1"},
        ))
        await _pump()
        self.assertEqual(changed.messages[-1].payload["mode"], "guarded")

        await bus.publish(Message.new(
            topics.SYSTEM_RESUME, source="interface",
            payload={"reason": "operator resumed after review", "requested_by": "human"},
        ))
        await _pump()
        self.assertEqual(changed.messages[-1].payload["mode"], "trusted")
        self.assertEqual(changed.messages[-1].payload["reason"], "system.resume")


class TestTightenAtTheBaselineLevelStillRecordsTheReason(_TrustPostureTestCase):
    """Live-caught (observer, 2026-09-09) with a real Kernel: the default
    `baseline_posture` is `"guarded"` (`guardian/config.py`), and a
    critical health finding's default target is also `"guarded"`
    (`health_critical_tightens_to`) -- so from a fresh boot, the very
    first real critical health finding a running system sees tightens
    to the level it is already at. Every existing test in this file
    boots with `baseline_posture="trusted"` specifically so this
    equal-levels case never comes up; none of them would have caught
    `_tighten`'s `if self._posture.level == to: return` swallowing the
    reason (and therefore `trust_score`) whole. This test boots with the
    real production default instead."""

    async def test_critical_health_finding_at_default_baseline_still_records_the_reason(self) -> None:
        kernel = await self._boot(GuardianConfig())  # real defaults: mode/baseline_posture both "guarded"
        bus = kernel.bus
        changed = _Collector()
        await bus.subscribe(topics.GUARDIAN_POSTURE_CHANGED, changed)

        reply_before = await bus.request(Message.new(topics.GUARDIAN_POSTURE_REQUEST, source="test", payload={}))
        self.assertEqual(reply_before.payload["trust_score"], 1.0)
        self.assertEqual(reply_before.payload["tightened_by"], [])

        await bus.publish(Message.new(
            topics.REFLECT_HEALTH_FINDING, source="reflection",
            payload={"severity": "critical", "detail": "valence pinned at -1.0"},
        ))
        await _pump()

        # No level change (guarded -> guarded), so no posture-changed
        # announcement -- that part of the old behavior is correct and
        # stays as-is.
        self.assertEqual(changed.messages, [])

        # But the reason must not vanish: it drives `trust_score` and the
        # `budget` command's `tightened_by` list, both read from
        # `guardian.posture.reply` (`_on_posture_request`).
        reply_after = await bus.request(Message.new(topics.GUARDIAN_POSTURE_REQUEST, source="test", payload={}))
        self.assertEqual(reply_after.payload["trust_score"], 0.0)
        self.assertEqual(len(reply_after.payload["tightened_by"]), 1)
        self.assertIn("critical health finding", reply_after.payload["tightened_by"][0])


if __name__ == "__main__":
    unittest.main()
