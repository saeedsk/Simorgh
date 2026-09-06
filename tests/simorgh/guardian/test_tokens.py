"""`TokenIssuer.issue` round-trips against `contracts.security`'s real
verification (09-guardian.md section 5.4) -- the same functions Execution
uses independently in `verifier.py`."""

import unittest

from simorgh.contracts import security
from simorgh.guardian.tokens import TokenIssuer
from tests.simorgh.helpers import FakeClock


class TestTokenIssuer(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.secret = b"\x01" * 32
        self.issuer = TokenIssuer(self.secret, ttl_s=120.0, clock=self.clock)

    def test_issued_token_verifies(self):
        token, expires_at, args_sha256 = self.issuer.issue("a1", "read_file", {"path": "x"})
        self.assertEqual(expires_at, self.clock.now() + 120.0)
        self.assertEqual(args_sha256, security.canonical_args_sha256({"path": "x"}))
        self.assertTrue(security.verify_approval_token(
            self.secret, token, action_id="a1", tool="read_file",
            args_sha256=args_sha256, expires_at=expires_at, now=self.clock.now(),
        ))

    def test_a_different_secret_fails_verification(self):
        token, expires_at, args_sha256 = self.issuer.issue("a1", "read_file", {"path": "x"})
        self.assertFalse(security.verify_approval_token(
            b"\x02" * 32, token, action_id="a1", tool="read_file",
            args_sha256=args_sha256, expires_at=expires_at, now=self.clock.now(),
        ))

    def test_tampering_with_any_bound_field_fails_verification(self):
        token, expires_at, args_sha256 = self.issuer.issue("a1", "read_file", {"path": "x"})
        self.assertFalse(security.verify_approval_token(
            self.secret, token, action_id="a1", tool="git_commit",
            args_sha256=args_sha256, expires_at=expires_at, now=self.clock.now(),
        ))
        self.assertFalse(security.verify_approval_token(
            self.secret, token, action_id="a1", tool="read_file",
            args_sha256=security.canonical_args_sha256({"path": "y"}), expires_at=expires_at, now=self.clock.now(),
        ))

    def test_verification_after_expiry_fails(self):
        token, expires_at, args_sha256 = self.issuer.issue("a1", "read_file", {"path": "x"})
        self.assertFalse(security.verify_approval_token(
            self.secret, token, action_id="a1", tool="read_file",
            args_sha256=args_sha256, expires_at=expires_at, now=expires_at + 0.001,
        ))

    def test_an_explicit_ttl_overrides_the_configured_default(self):
        token, expires_at, _ = self.issuer.issue("a1", "read_file", {}, ttl_s=5.0)
        self.assertEqual(expires_at, self.clock.now() + 5.0)


if __name__ == "__main__":
    unittest.main()
