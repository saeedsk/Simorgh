import unittest

from simorgh.contracts.security import (
    ReplayGuard,
    approval_token,
    canonical_args_sha256,
    new_run_secret,
    subsystem_token,
    verify_approval_token,
    verify_subsystem_token,
)


class TestApprovalToken(unittest.TestCase):
    def setUp(self):
        self.secret = new_run_secret()
        self.args = {"path": "src/x.py", "n": 1}
        self.digest = canonical_args_sha256(self.args)
        self.expires = 1_000_120.0
        self.token = approval_token(self.secret, "a1", "read_file", self.digest, self.expires)

    def _verify(self, **overrides):
        kwargs = dict(token=self.token, action_id="a1", tool="read_file", args_sha256=self.digest,
                      expires_at=self.expires, now=1_000_000.0)
        kwargs.update(overrides)
        return verify_approval_token(self.secret, **kwargs)

    def test_valid_token_verifies(self):
        self.assertTrue(self._verify())

    def test_forged_token_fails(self):
        self.assertFalse(self._verify(token="0" * 64))
        self.assertFalse(self._verify(token=""))

    def test_token_from_another_secret_fails(self):
        other = approval_token(new_run_secret(), "a1", "read_file", self.digest, self.expires)
        self.assertFalse(self._verify(token=other))

    def test_altered_action_tool_args_or_expiry_fails(self):
        self.assertFalse(self._verify(action_id="a2"))
        self.assertFalse(self._verify(tool="write_file"))
        self.assertFalse(self._verify(args_sha256=canonical_args_sha256({"path": "src/y.py"})))
        self.assertFalse(self._verify(expires_at=self.expires + 1))

    def test_expired_token_fails(self):
        self.assertFalse(self._verify(now=self.expires + 0.001))
        self.assertTrue(self._verify(now=self.expires))

    def test_canonical_args_hash_ignores_key_order(self):
        self.assertEqual(canonical_args_sha256({"a": 1, "b": 2}), canonical_args_sha256({"b": 2, "a": 1}))

    def test_replay_guard_rejects_second_use(self):
        guard = ReplayGuard(capacity=2)
        self.assertTrue(guard.consume("a1", now=1.0))
        self.assertFalse(guard.consume("a1", now=2.0))
        self.assertTrue(guard.consume("a2", now=3.0))
        self.assertTrue(guard.consume("a3", now=4.0))  # evicts a1 (oldest)
        self.assertTrue(guard.consume("a1", now=5.0))  # bounded memory; expiry covers the rest


class TestSubsystemToken(unittest.TestCase):
    def test_round_trip_and_forgery(self):
        secret = new_run_secret()
        token = subsystem_token(secret, "run-1", "guardian", "0")
        self.assertTrue(verify_subsystem_token(secret, token, run_id="run-1", name="guardian", instance_id="0"))
        self.assertFalse(verify_subsystem_token(secret, token, run_id="run-1", name="execution", instance_id="0"))
        self.assertFalse(verify_subsystem_token(secret, token, run_id="run-2", name="guardian", instance_id="0"))
        self.assertFalse(verify_subsystem_token(new_run_secret(), token, run_id="run-1", name="guardian", instance_id="0"))
        self.assertFalse(verify_subsystem_token(secret, "", run_id="run-1", name="guardian", instance_id="0"))


if __name__ == "__main__":
    unittest.main()
