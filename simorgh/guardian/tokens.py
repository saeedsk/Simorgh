"""Thin wrapper over `contracts.security` (09-guardian.md section 5.4):
Guardian's only job with the secret is to mint tokens; verification is
Execution's independent responsibility (defense in depth -- the approver
minting a token is not the same guarantee as the executor checking one).
"""

from __future__ import annotations

from simorgh.contracts import security


class TokenIssuer:
    def __init__(self, secret: bytes, *, ttl_s: float, clock) -> None:
        self._secret = secret
        self._ttl_s = ttl_s
        self._clock = clock

    def issue(self, action_id: str, tool: str, args: dict, *, ttl_s: float | None = None) -> tuple[str, float, str]:
        """Returns (token, expires_at, args_sha256)."""
        args_sha256 = security.canonical_args_sha256(args)
        expires_at = self._clock.now() + (ttl_s if ttl_s is not None else self._ttl_s)
        token = security.approval_token(self._secret, action_id, tool, args_sha256, expires_at)
        return token, expires_at, args_sha256
