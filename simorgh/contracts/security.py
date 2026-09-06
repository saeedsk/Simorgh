"""Approval tokens and subsystem tokens (docs/blueprint/03 section 10;
02 section 3).

An approval token binds a Guardian decision to the *exact* action it
approved -- id, tool, canonical args hash, and expiry -- under a per-run
secret only the Kernel, Guardian, and Execution ever hold. Execution
recomputes it before running anything; a forged, altered, expired, or
replayed approval fails closed. This is the structural half of "nothing
executes because a model decided it should": the reasoning that
proposed an action cannot mint the token that lets it run.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets as _secrets
from typing import Any

from .envelope import canonical_json

DEFAULT_TOKEN_TTL_SECONDS = 120.0


def new_run_secret(nbytes: int = 32) -> bytes:
    return _secrets.token_bytes(nbytes)


def canonical_args_sha256(args: Any) -> str:
    return hashlib.sha256(canonical_json(args).encode("utf-8")).hexdigest()


def _canonical_expiry(expires_at: float) -> str:
    # A fixed textual form so producer and verifier can never disagree on
    # float formatting (repr vs str, trailing zeros).
    return f"{float(expires_at):.6f}"


def approval_token(secret: bytes, action_id: str, tool: str, args_sha256: str, expires_at: float) -> str:
    material = "|".join((action_id, tool, args_sha256, _canonical_expiry(expires_at))).encode("utf-8")
    return hmac.new(secret, material, hashlib.sha256).hexdigest()


def verify_approval_token(
    secret: bytes,
    token: str,
    *,
    action_id: str,
    tool: str,
    args_sha256: str,
    expires_at: float,
    now: float,
) -> bool:
    """Constant-time comparison plus expiry. Replay protection is a
    separate concern (see `ReplayGuard`) because a token is legitimately
    verified once per approval, and only the verifier knows what it has
    already run."""
    if not isinstance(token, str) or not token:
        return False
    if now > float(expires_at):
        return False
    expected = approval_token(secret, action_id, tool, args_sha256, expires_at)
    return hmac.compare_digest(expected, token)


class ReplayGuard:
    """Remembers action ids whose approval has already been consumed so
    the same `action.approved` cannot run twice (at-least-once delivery
    makes duplicates routine, not hypothetical). Bounded: the oldest
    entries are dropped once `capacity` is exceeded, which is safe
    because every token also carries an expiry."""

    def __init__(self, capacity: int = 10_000) -> None:
        self._seen: dict[str, float] = {}
        self._capacity = capacity

    def consume(self, action_id: str, *, now: float) -> bool:
        """True the first time an action id is seen; False on replay."""
        if action_id in self._seen:
            return False
        self._seen[action_id] = now
        if len(self._seen) > self._capacity:
            oldest = min(self._seen, key=self._seen.__getitem__)
            del self._seen[oldest]
        return True


def subsystem_token(secret: bytes, run_id: str, name: str, instance_id: str) -> str:
    material = "|".join((run_id, name, instance_id)).encode("utf-8")
    return hmac.new(secret, material, hashlib.sha256).hexdigest()


def verify_subsystem_token(secret: bytes, token: str, *, run_id: str, name: str, instance_id: str) -> bool:
    if not isinstance(token, str) or not token:
        return False
    return hmac.compare_digest(subsystem_token(secret, run_id, name, instance_id), token)


__all__ = [
    "DEFAULT_TOKEN_TTL_SECONDS",
    "ReplayGuard",
    "approval_token",
    "canonical_args_sha256",
    "new_run_secret",
    "subsystem_token",
    "verify_approval_token",
    "verify_subsystem_token",
]
