"""Execution's own, independent verification of an `action.approved`
message (08-execution.md section 5.1): token verification at the
executor, not only at the approver, is what makes the safety guarantee
end-to-end (AGI-04 section 9) -- a Guardian that only *emits* approvals
is bypassable by anything that can publish on the topic; recomputing the
HMAC where the side effect actually happens closes that gap regardless
of what the Bus's own topic restriction does or doesn't catch.

`action.approved` carries only `args_sha256`, not the args themselves
(03-contracts-and-messaging.md section 4.6) -- Execution fetches the real
args from the durable `action:<action_id>` stream's own `received` event
(the same record Guardian appended before deciding) and verifies the hash
matches, rather than trusting any args a forger might attach directly to
a fabricated `action.approved`. A message with no matching `received`
event (a truly fabricated action_id) fails closed the same as a hash
mismatch.
"""

from __future__ import annotations

from dataclasses import dataclass

from simorgh.contracts import security


@dataclass(frozen=True)
class VerifyOutcome:
    ok: bool
    reason: str = ""  # "" | expired | replayed | mismatch | bad_signature


class ApprovalVerifier:
    def __init__(self, secret: bytes, *, replay_guard: security.ReplayGuard | None = None) -> None:
        self._secret = secret
        self._replay = replay_guard or security.ReplayGuard()

    def verify(self, approved: dict, args: dict | None, *, now: float) -> VerifyOutcome:
        action_id = approved["action_id"]
        tool = approved["tool"]
        expires_at = approved["expires_at"]
        token = approved["approval_token"]

        if args is None:
            return VerifyOutcome(False, "mismatch")
        recomputed_args_sha256 = security.canonical_args_sha256(args)
        if recomputed_args_sha256 != approved["args_sha256"]:
            return VerifyOutcome(False, "mismatch")
        if now > float(expires_at):
            return VerifyOutcome(False, "expired")
        if not security.verify_approval_token(
            self._secret, token, action_id=action_id, tool=tool,
            args_sha256=approved["args_sha256"], expires_at=expires_at, now=now,
        ):
            return VerifyOutcome(False, "bad_signature")
        if not self._replay.consume(action_id, now=now):
            return VerifyOutcome(False, "replayed")
        return VerifyOutcome(True)
