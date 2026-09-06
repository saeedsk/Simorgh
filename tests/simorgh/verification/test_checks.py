"""Per-`Check` unit tests exercising `applies`/`run` in isolation via a
hand-built `CheckContext` (no real bus/ledger -- those are covered by the
integration tests)."""

import unittest

from simorgh.verification.api import ActionResult, CheckContext, ReviewReply, ThinkReply, VerifyRequest
from simorgh.verification.checks.denylist_immunity import DenylistImmunityCheck
from simorgh.verification.checks.isolated_suite import IsolatedSuiteCheck
from simorgh.verification.checks.sandbox_smoke import SandboxSmokeCheck
from simorgh.verification.checks.syntax import SyntaxCheck
from simorgh.verification.config import VerificationConfig


def _ctx(*, act=None, think=None, review=None, config=None) -> CheckContext:
    async def _unused(*a, **kw):
        raise AssertionError("not expected to be called")

    return CheckContext(act=act or _unused, think=think or _unused, review=review or _unused,
                        clock=None, config=config or VerificationConfig())


def _req(kind="task", **subject) -> VerifyRequest:
    return VerifyRequest(verification_id="v1", task_id="t1", kind=kind, subject=subject)


class TestSyntaxCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.check = SyntaxCheck()

    def test_does_not_apply_without_candidate(self):
        self.assertFalse(self.check.applies(_req()))

    def test_applies_with_candidate(self):
        self.assertTrue(self.check.applies(_req(candidate="x = 1")))

    async def test_valid_python_passes(self):
        result = await self.check.run(_req(candidate="x = 1"), _ctx())
        self.assertEqual(result.status, "passed")

    async def test_invalid_python_fails(self):
        result = await self.check.run(_req(candidate="def f(:\n"), _ctx())
        self.assertEqual(result.status, "failed")


class TestDenylistImmunityCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.check = DenylistImmunityCheck()

    async def test_approved_passes(self):
        async def review(subject, code, kind):
            return ReviewReply(approved=True)

        result = await self.check.run(_req(candidate="x = 1", path="a.py"), _ctx(review=review))
        self.assertEqual(result.status, "passed")

    async def test_denied_non_protected_is_retryable(self):
        async def review(subject, code, kind):
            return ReviewReply(approved=False, reasons=("matched denylist",), layers_run=("static",))

        result = await self.check.run(_req(candidate="x = 1"), _ctx(review=review))
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.feedback.retryable)

    async def test_denied_protected_is_not_retryable(self):
        async def review(subject, code, kind):
            return ReviewReply(approved=False, reasons=("protected",), layers_run=("protected",))

        result = await self.check.run(_req(candidate="x = 1"), _ctx(review=review))
        self.assertEqual(result.status, "failed")
        self.assertFalse(result.feedback.retryable)

    async def test_guardian_never_answers_is_insufficient(self):
        async def review(subject, code, kind):
            return ReviewReply(approved=False, ok=False)

        result = await self.check.run(_req(candidate="x = 1"), _ctx(review=review))
        self.assertEqual(result.status, "insufficient")


class TestSandboxSmokeCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.check = SandboxSmokeCheck()

    def test_applies_only_to_skill_by_default(self):
        self.assertTrue(self.check.applies(_req(kind="skill")))
        self.assertFalse(self.check.applies(_req(kind="task")))

    async def test_success(self):
        async def act(tool, args, *, timeout=None):
            return ActionResult(ok=True, output="ok")

        result = await self.check.run(_req(kind="skill", candidate="print(1)"), _ctx(act=act))
        self.assertEqual(result.status, "passed")

    async def test_timeout_is_insufficient_not_failed(self):
        async def act(tool, args, *, timeout=None):
            return ActionResult(ok=False, error="timeout")

        result = await self.check.run(_req(kind="skill", candidate="print(1)"), _ctx(act=act))
        self.assertEqual(result.status, "insufficient")

    async def test_real_failure_is_failed_and_retryable(self):
        async def act(tool, args, *, timeout=None):
            return ActionResult(ok=False, error="Traceback...")

        result = await self.check.run(_req(kind="skill", candidate="raise ValueError()"), _ctx(act=act))
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.feedback.retryable)

    async def test_non_default_config_skips_at_run_time(self):
        config = VerificationConfig(sandbox_smoke_kinds=())
        result = await self.check.run(_req(kind="skill", candidate="x=1"), _ctx(config=config))
        self.assertEqual(result.status, "skipped")


class TestIsolatedSuiteCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.check = IsolatedSuiteCheck()

    def test_does_not_apply_to_skill(self):
        self.assertFalse(self.check.applies(_req(kind="skill", candidate="x=1")))

    def test_applies_to_self_patch_with_candidate(self):
        self.assertTrue(self.check.applies(_req(kind="self_patch", candidate="x=1")))

    async def test_passed_count_at_or_above_baseline_passes(self):
        async def act(tool, args, *, timeout=None):
            return ActionResult(ok=True, metadata={"baseline": 3, "patched": 4, "passed": True})

        result = await self.check.run(_req(kind="self_patch", candidate="x=1"), _ctx(act=act))
        self.assertEqual(result.status, "passed")

    async def test_patched_count_below_baseline_fails_even_if_passed(self):
        async def act(tool, args, *, timeout=None):
            return ActionResult(ok=True, metadata={"baseline": 5, "patched": 3, "passed": True})

        result = await self.check.run(_req(kind="self_patch", candidate="x=1"), _ctx(act=act))
        self.assertEqual(result.status, "failed")

    async def test_zero_patched_tests_fails(self):
        async def act(tool, args, *, timeout=None):
            return ActionResult(ok=True, metadata={"baseline": 0, "patched": 0, "passed": True})

        result = await self.check.run(_req(kind="self_patch", candidate="x=1"), _ctx(act=act))
        self.assertEqual(result.status, "failed")

    async def test_timeout_is_insufficient(self):
        async def act(tool, args, *, timeout=None):
            return ActionResult(ok=False, error="timeout")

        result = await self.check.run(_req(kind="self_patch", candidate="x=1"), _ctx(act=act))
        self.assertEqual(result.status, "insufficient")


if __name__ == "__main__":
    unittest.main()
