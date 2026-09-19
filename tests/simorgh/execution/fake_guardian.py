"""A stand-in Guardian for Execution's tests: it answers every
`action.proposed` with a real, signed `action.approved` (or with an
`action.denied`), and records the proposal in `action:<id>` the way the
real one does, because `_on_approved` reads the arguments back from
there before it verifies the token."""

from __future__ import annotations

from simorgh.bus.factory import make_client
from simorgh.contracts import security, topics
from simorgh.contracts.envelope import Event, Message


class FakeGuardian:
    def __init__(self, backend, *, ledger, clock, secret_hex: str, approve: bool = True) -> None:
        self._bus = make_client(backend, source="guardian", ledger=ledger, clock=clock)
        self._ledger = ledger
        self._clock = clock
        self._secret = bytes.fromhex(secret_hex)
        self.approve = approve
        self.proposals: list[dict] = []
        self._sub = None

    async def start(self) -> None:
        await self._bus.start()
        self._sub = await self._bus.subscribe(topics.ACTION_PROPOSED, self._on_proposed, group="guardian")

    async def stop(self) -> None:
        if self._sub is not None:
            await self._sub.unsubscribe()

    async def _on_proposed(self, message: Message) -> None:
        p = dict(message.payload)
        self.proposals.append(p)
        action_id = p["action_id"]
        stream = f"action:{action_id}"
        await self._ledger.append(stream, Event(stream=stream, type="received", ts=self._clock.now(),
                                                trace_id="", causation_id=None, payload={"proposal": p}))
        if not self.approve:
            await self._bus.publish(message.caused(
                topics.ACTION_DENIED,
                {"action_id": action_id, "reasons": ["test guardian says no"], "layer": "policy",
                 "tool": p["tool"]},
                source="guardian"))
            return
        args_sha = security.canonical_args_sha256(p["args"])
        expires_at = self._clock.now() + 60.0
        await self._bus.publish(message.caused(
            topics.ACTION_APPROVED,
            {"action_id": action_id, "tool": p["tool"], "args_sha256": args_sha, "expires_at": expires_at,
             "approval_token": security.approval_token(self._secret, action_id, p["tool"], args_sha, expires_at),
             "mode_at_approval": "guarded"},
            source="guardian"))
