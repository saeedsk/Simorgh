"""`ApprovalVerifier.verify` (08-execution.md section 5.1): Execution's
own, independent recomputation of the HMAC before running anything. Six
cases: ok, missing args (no matching `received` event), hash mismatch,
expired, bad signature, replayed."""

import unittest

from simorgh.contracts import security
from simorgh.execution.verifier import ApprovalVerifier


def _approved(secret: bytes, *, action_id="a1", tool="read_file", args=None, ttl=120.0, now=0.0) -> tuple[dict, dict]:
    args = args if args is not None else {"path": "x"}
    args_sha256 = security.canonical_args_sha256(args)
    expires_at = now + ttl
    token = security.approval_token(secret, action_id, tool, args_sha256, expires_at)
    return {
        "action_id": action_id, "tool": tool, "args_sha256": args_sha256,
        "expires_at": expires_at, "approval_token": token, "mode_at_approval": "guarded",
    }, args


class TestApprovalVerifier(unittest.TestCase):
    def setUp(self):
        self.secret = b"\x03" * 32
        self.verifier = ApprovalVerifier(self.secret)

    def test_a_valid_approval_verifies(self):
        approved, args = _approved(self.secret)
        outcome = self.verifier.verify(approved, args, now=0.0)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.reason, "")

    def test_missing_args_fails_closed_as_mismatch(self):
        approved, _ = _approved(self.secret)
        outcome = self.verifier.verify(approved, None, now=0.0)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, "mismatch")

    def test_args_that_dont_hash_to_args_sha256_fail_as_mismatch(self):
        approved, _ = _approved(self.secret, args={"path": "x"})
        outcome = self.verifier.verify(approved, {"path": "a different path"}, now=0.0)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, "mismatch")

    def test_an_expired_approval_fails_as_expired(self):
        approved, args = _approved(self.secret, ttl=10.0, now=0.0)
        outcome = self.verifier.verify(approved, args, now=10.001)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, "expired")

    def test_a_token_signed_with_a_different_secret_fails_as_bad_signature(self):
        approved, args = _approved(b"\x04" * 32)
        outcome = self.verifier.verify(approved, args, now=0.0)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, "bad_signature")

    def test_a_replayed_action_id_fails_the_second_time(self):
        approved, args = _approved(self.secret)
        first = self.verifier.verify(approved, args, now=0.0)
        second = self.verifier.verify(approved, args, now=0.0)
        self.assertTrue(first.ok)
        self.assertFalse(second.ok)
        self.assertEqual(second.reason, "replayed")


if __name__ == "__main__":
    unittest.main()
