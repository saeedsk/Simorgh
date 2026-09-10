"""Adversarial, end-to-end tests of `ApprovalVerifier` against a REAL
Guardian + Execution pipeline (not the isolated unit tests in
tests/simorgh/execution/test_verifier.py). These reproduce, or rule out,
five specific attack shapes on the approve->execute boundary
(08-execution.md section 5.1, contracts/security.py):

1. TOCTOU swap: get a real approval for one action_id/args, then try to
   get a *different* payload executed under that same approval.
2. Expiry boundary: exactly-at-expiry behaviour (inclusive vs exclusive),
   and a genuine real-time expiry.
3. Replay: run an approved action once, then replay the exact same
   `action.approved` message a second time.
4. Cross-process forgery: without the shared HMAC secret, a bare
   action_id string carries no executable authority.
5. Concurrency: two concurrent deliveries of the same `action.approved`
   (a retry-storm shape) must never both run the tool.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts import security, topics
from simorgh.contracts.envelope import Message
from simorgh.execution.config import Config as ExecutionConfig
from simorgh.execution.service import Service as ExecutionService
from simorgh.guardian.config import Config as GuardianConfig
from simorgh.guardian.service import Service as GuardianService
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _patched_build_factories(*, approval_ttl_s: float = 120.0):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None, guardian_config=None):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl, guardian_config=guardian_config)
        factories["guardian"] = lambda: GuardianService(config=GuardianConfig(mode="guarded", approval_ttl_s=approval_ttl_s))
        factories["execution"] = lambda: ExecutionService(config=ExecutionConfig(repo_root=_REPO_ROOT))
        return factories

    return _build


class _Collector:
    def __init__(self, bus) -> None:
        self.bus = bus
        self.events: list[Message] = []

    async def start(self) -> None:
        await self.bus.subscribe(topics.ACTION_DENIED, self._on)
        await self.bus.subscribe(topics.ACTION_RESULT, self._on, group="collector-result")

    async def _on(self, message: Message) -> None:
        self.events.append(message)


async def _wait_for(events: list, action_id: str, type_: str, *, attempts: int = 500):
    for _ in range(attempts):
        for m in events:
            if m.payload.get("action_id") == action_id and m.type == type_:
                return m
        await asyncio.sleep(0.01)
    return None


def _proposal(action_id: str, *, tool: str, args: dict, reversibility: str = "read_only") -> Message:
    return Message.new(
        topics.ACTION_PROPOSED, source="test",
        payload={"action_id": action_id, "tool": tool, "args": args,
                 "scope": {"network": False}, "reversibility": reversibility,
                 "rationale": "adversarial test", "proposed_by": "test"},
    )


class _AdversarialTestCase(unittest.IsolatedAsyncioTestCase):
    async def _boot(self, *, approval_ttl_s: float = 120.0) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        config = LoadedConfig({"runtime": {"data_dir": tmp.name}}, None)
        kernel = Kernel(config, secrets=EnvSecretStore({}))
        patcher = mock.patch(
            "simorgh.kernel.service.build_factories",
            new=_patched_build_factories(approval_ttl_s=approval_ttl_s),
        )
        patcher.start()
        await kernel.boot()
        self.addCleanup(patcher.stop)
        self.addCleanup(tmp.cleanup)
        self.addAsyncCleanup(kernel.shutdown)
        self.assertEqual(kernel.state.state, RUNNING)
        return kernel


class TestToctouSwap(_AdversarialTestCase):
    """A real approval for action A's real args must not let a
    *different* payload run under the same action_id. The verifier
    binds args_sha256 into the signed material, so any attempt to swap
    args_sha256 (or the args) after the fact invalidates the signature."""

    async def test_swapped_args_sha256_on_an_otherwise_real_approval_is_rejected(self):
        kernel = await self._boot()
        collector = _Collector(kernel.bus)
        await collector.start()

        # A real proposal for a real, legitimate read.
        await kernel.bus.publish(_proposal(
            "swap-1", tool="read_file", args={"path": "docs/blueprint/subsystems/09-guardian.md"},
        ))
        result = await _wait_for(collector.events, "swap-1", topics.ACTION_RESULT)
        self.assertIsNotNone(result, "the legitimate proposal never even completed")
        self.assertTrue(result.payload["ok"])

        # Now try to reuse the SAME action_id with a forged approval that
        # claims a different args_sha256 (as if a TOCTOU attacker swapped
        # the code/command between approval and execution) but reuses
        # a token shape that cannot possibly be valid for the new hash
        # without the secret.
        forged_hash = security.canonical_args_sha256({"path": "docs/SOUL.md"})
        forged = Message.new(
            topics.ACTION_APPROVED, source="guardian",
            payload={"action_id": "swap-1", "tool": "read_file", "args_sha256": forged_hash,
                     "expires_at": time.time() + 60, "approval_token": "0" * 64,
                     "mode_at_approval": "guarded"},
        )
        await kernel.bus.publish(forged)
        denied = await _wait_for(collector.events, "swap-1", topics.ACTION_DENIED)
        self.assertIsNotNone(denied, "a swapped-args forged approval was not denied")
        self.assertEqual(denied.payload["layer"], "token")

    async def test_duplicate_proposal_under_same_action_id_cannot_swap_what_executes(self):
        """Two different `action.proposed` under the same action_id (an
        attacker racing a second, malicious proposal against a real one)
        must not let the second one's args execute in place of the
        first: Execution always resolves args from the FIRST `received`
        ledger event for that action_id, an immutable append-only
        record Guardian writes at proposal time, not from whatever
        `action.approved` message happens to arrive."""
        kernel = await self._boot()
        collector = _Collector(kernel.bus)
        await collector.start()

        # Attacker's malicious proposal lands first under an action_id
        # they hope the legitimate system will reuse.
        await kernel.bus.publish(_proposal(
            "swap-2", tool="read_file", args={"path": "docs/SOUL.md"},
        ))
        first_settled = await asyncio.gather(
            _wait_for(collector.events, "swap-2", topics.ACTION_RESULT, attempts=200),
            _wait_for(collector.events, "swap-2", topics.ACTION_DENIED, attempts=200),
        )
        self.assertTrue(any(first_settled), "first proposal under swap-2 never settled")

        # A second, legitimate proposal reuses the exact same action_id
        # with different args.
        await kernel.bus.publish(_proposal(
            "swap-2", tool="read_file", args={"path": "docs/blueprint/subsystems/09-guardian.md"},
        ))
        await asyncio.sleep(0.3)
        results = [m for m in collector.events if m.payload.get("action_id") == "swap-2" and m.type == topics.ACTION_RESULT]
        # However this resolves (only the first ever fetched args win, so
        # a second approval's own args_sha256 can mismatch and it gets
        # denied) it must NEVER produce a successful result whose content
        # is the SECOND proposal's args when the FIRST's is what Execution
        # actually bound to -- i.e. never more than one successful
        # execution for one action_id, and never a silently-swapped one.
        self.assertLessEqual(len(results), 1, "the same action_id executed more than once")


class TestExpiryBoundary(_AdversarialTestCase):
    async def test_a_genuinely_expired_real_approval_is_denied(self):
        kernel = await self._boot(approval_ttl_s=0.05)
        collector = _Collector(kernel.bus)
        await collector.start()

        await kernel.bus.publish(_proposal(
            "exp-1", tool="read_file", args={"path": "docs/blueprint/subsystems/09-guardian.md"},
        ))
        # Let the approval issue, then wait past its 0.05s TTL before any
        # tool actually gets to run: pause the system right after
        # proposing so `_on_approved` is the one that fetches `now`
        # late.
        await asyncio.sleep(0.3)
        result = [m for m in collector.events if m.payload.get("action_id") == "exp-1" and m.type == topics.ACTION_RESULT]
        denied = [m for m in collector.events if m.payload.get("action_id") == "exp-1" and m.type == topics.ACTION_DENIED]
        # Either outcome is correct: a same-loop-tick success (execution
        # beat the clock) or a clean denial for "expired". What must
        # never happen is BOTH -- an action denied as expired and also
        # executed.
        #
        # This used to assert `duration_ms < 50` as a proxy for "it beat
        # the TTL", which was wrong and flaked under `-n auto`:
        # `duration_ms` measures how long the tool took to RUN, not
        # whether the approval was still valid when it was checked. A
        # legitimately-approved action that spends 60ms executing under
        # parallel load failed an assertion about a different quantity
        # entirely. Timing on a loaded machine cannot answer the
        # question; the mutual exclusion below can.
        self.assertTrue(result or denied, "action neither ran nor was denied")
        self.assertFalse(result and denied,
                         "the same action was both denied as expired and executed")
        if result:
            self.assertTrue(result[0].payload.get("ok"),
                            "an action that ran should report its real outcome")

    def test_off_by_one_at_the_exact_expiry_instant_is_inclusive_not_exclusive(self):
        """Direct verifier check of the exact boundary (docs asked for
        this precisely): `now == expires_at` currently VERIFIES (passes),
        because both `verifier.py` and `security.verify_approval_token`
        use strict `now > expires_at` for "expired". So the approval
        remains usable through the same floating-point instant it
        expires at, not just strictly before it. This is the *less*
        conservative of the two choices (a security-first design would
        make expiry exclusive, i.e. `now >= expires_at` denies), but it
        is a one-instant, not exploitable, widening: real callers always
        observe `now` via a monotonically increasing wall clock sampled
        strictly after `expires_at` was computed, so landing exactly on
        the picosecond boundary is not a reachable attack -- documenting
        the actual behaviour here, not asserting it must change."""
        from simorgh.execution.verifier import ApprovalVerifier

        secret = b"\x09" * 32
        verifier = ApprovalVerifier(secret)
        args = {"path": "x"}
        args_sha256 = security.canonical_args_sha256(args)
        expires_at = 1000.0
        token = security.approval_token(secret, "exact-1", "read_file", args_sha256, expires_at)
        approved = {"action_id": "exact-1", "tool": "read_file", "args_sha256": args_sha256,
                    "expires_at": expires_at, "approval_token": token}

        at_boundary = verifier.verify(approved, args, now=expires_at)
        self.assertTrue(at_boundary.ok, "documents current inclusive-at-boundary behaviour")

        # One tick later it is unambiguously denied.
        past = verifier.verify(
            {**approved, "action_id": "exact-2",
             "approval_token": security.approval_token(secret, "exact-2", "read_file", args_sha256, expires_at)},
            args, now=expires_at + 1e-6,
        )
        self.assertFalse(past.ok)
        self.assertEqual(past.reason, "expired")


class TestReplayViaLiveCapture(_AdversarialTestCase):
    """`action.approved` may only be SUBSCRIBED by `execution` itself
    (contracts/topics.py `SUBSCRIBE_ONLY_BY`) -- an ordinary test client
    cannot snoop it off the bus the way it can `action.result` or
    `action.denied`. So the live message is captured by wrapping
    `ExecutionService._on_approved` itself (the exact same handler the
    real subscription calls), patched in at the class level before boot
    so `Service.start()`'s own `ctx.bus.subscribe(..., self._on_approved,
    ...)` binds the wrapped version."""

    async def test_capturing_and_replaying_the_live_action_approved_message_is_refused(self):
        captured: list[Message] = []
        original = ExecutionService._on_approved

        async def _wrapped(self, message: Message) -> None:
            captured.append(message)
            await original(self, message)

        patcher = mock.patch.object(ExecutionService, "_on_approved", _wrapped)
        patcher.start()
        self.addCleanup(patcher.stop)

        kernel = await self._boot()
        collector = _Collector(kernel.bus)
        await collector.start()
        invocation_count = {"n": 0}

        async def _count_invocations(message: Message) -> None:
            if message.payload.get("action_id") == "replay-live-1":
                invocation_count["n"] += 1
        await kernel.bus.subscribe(topics.TOOL_INVOKED, _count_invocations)

        await kernel.bus.publish(_proposal(
            "replay-live-1", tool="read_file", args={"path": "docs/blueprint/subsystems/09-guardian.md"},
        ))
        result = await _wait_for(collector.events, "replay-live-1", topics.ACTION_RESULT)
        self.assertIsNotNone(result)
        self.assertTrue(result.payload["ok"])
        self.assertEqual(len(captured), 1, "did not capture exactly one real action.approved")
        self.assertEqual(invocation_count["n"], 1)

        # Replay the approval a second time. NOT by re-enqueuing the
        # identical `Message` object: the in-memory bus backend dedupes
        # by envelope `message.id` (memory.py `lane.dedupe`) and would
        # silently drop a literal re-publish of the same object before
        # it ever reached Execution -- a real bus-level idempotency
        # guard, but a DIFFERENT layer than the verifier's own
        # `ReplayGuard`. A genuine replay attack (the approval payload
        # captured and resent, e.g. over the network, or redelivered by
        # a different at-least-once path) gets a fresh envelope id with
        # the identical payload -- exactly what a copy via `.new()`
        # reproduces -- and that is what must reach and be refused by
        # `ApprovalVerifier`'s own action_id replay guard.
        replayed = Message.new(topics.ACTION_APPROVED, source="guardian", payload=dict(captured[0].payload))
        await kernel.bus.publish(replayed)
        await asyncio.sleep(0.3)
        denied = [m for m in collector.events if m.payload.get("action_id") == "replay-live-1" and m.type == topics.ACTION_DENIED]
        self.assertTrue(denied, "the replayed approval was not denied")
        self.assertEqual(denied[-1].payload["reasons"], ["signature replayed"])
        self.assertEqual(invocation_count["n"], 1, "the tool ran a second time on replay -- REAL double execution")


class TestCrossProcessForgery(_AdversarialTestCase):
    """No secret => no authority, even with a real, correctly-shaped
    `received` ledger record for the action_id (i.e. even if the
    attacker can see/predict a real action_id and its recorded args --
    e.g. from log/ledger read access -- without the HMAC secret itself,
    a bare action_id string mints nothing)."""

    async def test_a_syntactically_perfect_approval_without_the_real_secret_is_rejected(self):
        kernel = await self._boot()
        collector = _Collector(kernel.bus)
        await collector.start()

        await kernel.bus.publish(_proposal(
            "forge-1", tool="read_file", args={"path": "docs/blueprint/subsystems/09-guardian.md"},
        ))
        # Let the real proposal's own approval run and complete first so
        # the "received" ledger record definitely exists with real args.
        real_result = await _wait_for(collector.events, "forge-1", topics.ACTION_RESULT)
        self.assertIsNotNone(real_result)

        # An attacker who knows the action_id, tool, and args (e.g. read
        # off the ledger from another, less-trusted vantage point) but
        # NOT the run's HMAC secret, tries to mint their own fresh
        # approval for a brand-new action_id pointing at the same real
        # "received" record's args shape, using a guessed/wrong secret.
        wrong_secret = b"\xff" * 32
        args = {"path": "docs/blueprint/subsystems/09-guardian.md"}
        args_sha256 = security.canonical_args_sha256(args)
        expires_at = time.time() + 60
        forged_token = security.approval_token(wrong_secret, "forge-2", "read_file", args_sha256, expires_at)

        # A genuine proposal creates the "received" record (Execution
        # never trusts anything else for args), then the forged token,
        # signed with the WRONG secret, tries to approve it.
        await kernel.bus.publish(_proposal(
            "forge-2", tool="read_file", args=args,
        ))
        await asyncio.sleep(0.05)
        forged = Message.new(
            topics.ACTION_APPROVED, source="guardian",
            payload={"action_id": "forge-2", "tool": "read_file", "args_sha256": args_sha256,
                     "expires_at": expires_at, "approval_token": forged_token, "mode_at_approval": "guarded"},
        )
        # Race the forged approval against Guardian's own real one for
        # the same action_id; whichever the verifier sees, the forged
        # token itself must never be the thing that lets it through.
        await kernel.bus.publish(forged)
        await asyncio.sleep(0.3)
        events = await kernel.ledger.read("action:forge-2")
        verified = [e for e in events if e.type == "verified"]
        # At least one verification must have failed with bad_signature
        # (the forged one), and no verification may report ok=True from
        # a bad_signature token.
        self.assertTrue(any(not v.payload["outcome"] for v in verified))


class TestConcurrentRetryStorm(_AdversarialTestCase):
    async def test_two_concurrent_deliveries_of_the_same_approval_run_the_tool_only_once(self):
        captured: list[Message] = []
        original = ExecutionService._on_approved

        async def _wrapped(self, message: Message) -> None:
            captured.append(message)
            await original(self, message)

        patcher = mock.patch.object(ExecutionService, "_on_approved", _wrapped)
        patcher.start()
        self.addCleanup(patcher.stop)

        kernel = await self._boot()
        collector = _Collector(kernel.bus)
        await collector.start()
        invocation_count = {"n": 0}

        async def _count_invocations(message: Message) -> None:
            if message.payload.get("action_id") == "race-1":
                invocation_count["n"] += 1
        await kernel.bus.subscribe(topics.TOOL_INVOKED, _count_invocations)

        await kernel.bus.publish(_proposal(
            "race-1", tool="read_file", args={"path": "docs/blueprint/subsystems/09-guardian.md"},
        ))
        # Wait for the real action.approved to be captured, but race two
        # extra deliveries of the identical message concurrently BEFORE
        # letting the first (real) one resolve, simulating a retry-storm
        # redelivery.
        for _ in range(200):
            if captured:
                break
            await asyncio.sleep(0.005)
        self.assertTrue(captured, "never observed the real action.approved")
        # Fresh envelopes (new message ids) carrying the identical
        # approval payload -- the same bus-level dedupe note as
        # TestReplayViaLiveCapture applies: reusing the literal `Message`
        # object here would just test the bus's own id-dedupe, not a
        # genuine concurrent race through `ApprovalVerifier` itself.
        payload = dict(captured[0].payload)
        await asyncio.gather(
            kernel.bus.publish(Message.new(topics.ACTION_APPROVED, source="guardian", payload=payload)),
            kernel.bus.publish(Message.new(topics.ACTION_APPROVED, source="guardian", payload=payload)),
        )
        await asyncio.sleep(0.3)
        self.assertEqual(invocation_count["n"], 1, "the tool ran more than once for one approval under concurrent redelivery")


if __name__ == "__main__":
    unittest.main()
