"""ContextAssembler (16 section 5): gathers the memory block and the
session transcript for one `cognition.think` call. The persona voice and
the self summary are deliberately *not* gathered here -- Cognition's own
assembler owns those as protected blocks, and fetching them here too sent
both twice in every prompt (see `assemble`). Every request uses `bus.request_or_error`
with a short timeout and degrades to simply omitting that block on a
timeout or error reply -- other Phase 1 subsystems may not exist yet in
this same build, and even once they do, a slow one must never stall a
session (01 section 4.5 guaranteed floor, 03 section 9 honest timeouts).
"""

from __future__ import annotations

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message

from .api import Session

DEFAULT_TIMEOUT_S = 0.25
# Live-caught (context_too_large, real use -- 07-post-cutover-review.md
# §3.4d/§3.3): a single migrated/long memory record could make the
# elastic "conversation" block too large for Cognition's layers 1-4 to
# shrink under budget even with layer 5 available (§3.2's own recorded
# residual gap). Bounding what's handed to Cognition in the first place
# is the more robust fix than relying entirely on downstream compaction
# to save an unbounded input -- these are deliberately generous (most
# real memory items are far smaller) so they bite only the rare outlier.
_MEMORY_ITEM_MAX_CHARS = 800
_MEMORY_BLOCK_MAX_CHARS = 4_000


class Assembler:
    def __init__(self, bus, *, clock=None, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self._bus = bus
        self._clock = clock
        self._timeout_s = timeout_s

    async def assemble(self, session: Session, purpose: str, user_text: str = "") -> list[dict]:
        """The messages for one `cognition.think`.

        Deliberately *not* the persona voice or the self summary. Both
        used to be fetched here and prepended, and Cognition's own
        assembler fetches and prepends them again as protected blocks (04
        section 5's prompt assembly order, which is their designed home).
        Measured 2026-09-07: every think call carried both twice -- 198 of
        819 prompt tokens were a verbatim second copy -- and paid for two
        extra bus round trips to Persona and Self per call. The second
        copy was also the worse-placed one, landing inside the user turn
        behind a literal "[system]" prefix.
        """
        blocks: list[dict] = []

        task = session.user_text or user_text
        mem = await self._memory_retrieve(task or session.task_id, session)
        if mem:
            blocks.append({"role": "system", "content": "Relevant memory:\n" + mem})

        # Live-caught by the same audit: this was sent on the *first* step
        # only (`session.py` clears `pending_user_text` after one use) and
        # never entered `session.messages`, so from step 2 of 8 the model
        # no longer had the request in front of it -- only its own tool
        # calls and their output. A patch session that applied a file and
        # then stopped had, by then, genuinely lost the instruction.
        if task:
            blocks.append({"role": "user", "content": task})

        blocks.extend(session.messages)
        return blocks

    async def _request(self, type_: str, payload: dict) -> Message | None:
        # `self._bus.source` (never a hardcoded literal): in `local-multi`
        # mode this Worker's own `BusClient` is bound to an instance-
        # qualified source (`orchestration@w1`), and `ReservedTopologyPolicy`
        # authenticates only the exact source `ContextFactory.build` issued
        # a token for -- a bare `"orchestration"` request would raise
        # `PolicyViolation` before ever reaching Memory/Self/World/Persona.
        req = Message.new(type_, source=self._bus.source, payload=payload, clock=self._clock)
        reply = await self._bus.request_or_error(req, timeout=self._timeout_s)
        if reply.payload.get("ok") is False:
            return None
        return reply

    async def _memory_retrieve(self, query: str, session: Session) -> str:
        reply = await self._request(
            topics.MEMORY_RETRIEVE,
            {"query": query, "kinds": ["episodic", "semantic"], "k": 8},
        )
        if not reply:
            return ""
        items = reply.payload.get("items", [])
        lines: list[str] = []
        total = 0
        for i in items[:8]:
            content = str(i.get("content", ""))
            if len(content) > _MEMORY_ITEM_MAX_CHARS:
                content = content[:_MEMORY_ITEM_MAX_CHARS] + "…"
            line = f"- {content}"
            if total + len(line) > _MEMORY_BLOCK_MAX_CHARS and lines:
                break  # keep the strongest (highest-ranked) matches, drop the rest honestly
            lines.append(line)
            total += len(line)
        return "\n".join(lines)

    async def world_facet(self, what: str, args: dict | None = None) -> dict | None:
        reply = await self._request(topics.WORLD_ENV_QUERY, {"what": what, "args": args or {}})
        return reply.payload if reply else None
