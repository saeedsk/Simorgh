"""Reserved-topology enforcement (docs/blueprint/03 section 3 and section
10; 02 section 3). The Kernel wires this policy into every BusClient;
the bus only asks it two questions:

- `check_subscribe(source, pattern)`: may this subsystem receive
  messages that this pattern could match? A pattern is refused if it
  would match *any* restricted type the subsystem is not on the list for
  -- `curiosity` subscribing to `action.#` is refused even though it
  never named `action.proposed`, because the subscription would still
  deliver it.
- `check_publish(source, type, payload)`: may this subsystem emit this
  type, with this payload? (`execution` may publish `action.denied`
  only with `layer: token`.)

Identity is the hard part in multi-process modes: a process could claim
`source="guardian"` in an envelope. `IdentityRegistry` verifies the
per-run subsystem token the Kernel issued at `start()`; the backend
stamps the *verified* source on every message, so the envelope's own
`source` is never trusted for policy on the `sqlite`/`aws` backends.
In `single` mode identity is the in-process client object, whose
`source` is fixed at construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from simorgh.contracts import security, topics

from .api import PolicyViolation


@dataclass
class IdentityRegistry:
    """Per-run subsystem tokens (03 section 10)."""

    secret: bytes
    run_id: str
    _known: dict[str, str] = field(default_factory=dict)  # "name@instance" -> token

    def issue(self, name: str, instance_id: str = "") -> str:
        token = security.subsystem_token(self.secret, self.run_id, name, instance_id)
        self._known[f"{name}@{instance_id}" if instance_id else name] = token
        return token

    def verify(self, source: str, token: str) -> bool:
        name, _, instance = source.partition("@")
        return security.verify_subsystem_token(
            self.secret, token, run_id=self.run_id, name=name, instance_id=instance
        )


class ReservedTopologyPolicy:
    """The `03` section 3 table, enforced. `identities` is optional: when
    given (multi-process modes), `authenticate()` must have succeeded
    for a source before it may subscribe or publish at all."""

    def __init__(self, identities: IdentityRegistry | None = None) -> None:
        self._identities = identities
        self._authenticated: set[str] = set()

    # -- identity --------------------------------------------------------
    def authenticate(self, source: str, token: str) -> None:
        if self._identities is None:
            self._authenticated.add(source)
            return
        if not self._identities.verify(source, token):
            raise PolicyViolation(f"identity: {source!r} presented an invalid subsystem token")
        self._authenticated.add(source)

    def _require_identity(self, source: str) -> None:
        if self._identities is not None and source not in self._authenticated:
            raise PolicyViolation(f"identity: {source!r} is not authenticated on this bus")

    # -- policy ----------------------------------------------------------
    def check_subscribe(self, source: str, pattern: str) -> None:
        self._require_identity(source)
        for restricted in topics.SUBSCRIBE_ONLY_BY:
            if topics.matches(pattern, restricted) and not topics.may_subscribe(source, restricted):
                raise PolicyViolation(
                    f"policy: {topics.source_name(source)} may not subscribe {restricted} "
                    f"(pattern {pattern!r})"
                )

    def check_publish(self, source: str, type: str, payload: dict) -> None:
        self._require_identity(source)
        if not topics.may_publish(source, type, payload):
            raise PolicyViolation(f"policy: {topics.source_name(source)} may not publish {type}")


__all__ = ["IdentityRegistry", "PolicyViolation", "ReservedTopologyPolicy"]
