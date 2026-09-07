"""ContextAssembler (16 section 5): gathers memory/self/world/persona for
one `cognition.think` call. Every request uses `bus.request_or_error`
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
        blocks: list[dict] = []

        self_text = await self._self_summary()
        if self_text:
            blocks.append({"role": "system", "content": self_text})

        voice = await self._persona_voice()
        if voice:
            blocks.append({"role": "system", "content": voice})

        mem = await self._memory_retrieve(user_text or session.task_id, session)
        if mem:
            blocks.append({"role": "system", "content": "Relevant memory:\n" + mem})

        for m in session.messages:
            blocks.append(m)
        if user_text:
            blocks.append({"role": "user", "content": user_text})
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

    async def _self_summary(self) -> str:
        reply = await self._request(topics.SELF_SUMMARY, {"budget_tokens": 300})
        return reply.payload.get("text", "") if reply else ""

    async def _persona_voice(self) -> str:
        reply = await self._request(topics.PERSONA_VOICE, {"context": "chat"})
        if not reply:
            return ""
        style = reply.payload.get("style_block", "")
        mood = reply.payload.get("mood_phrase", "")
        return "\n".join(x for x in (style, mood) if x)

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
