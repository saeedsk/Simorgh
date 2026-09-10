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

#: Shown in place of the memory block when the store could not be
#: consulted, so "I have not seen this before" and "I could not look"
#: are different prompts. Addressed to the model, because the model is
#: the one about to reason as though it had checked.
MEMORY_UNAVAILABLE_NOTE = (
    "Your memory could not be consulted for this request ({why}), so treat anything "
    "you would expect to remember as unknown rather than absent. Say so if it matters."
)


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
        mem, unavailable = await self._memory_block(task or session.task_id, session)
        if mem:
            blocks.append({"role": "system", "content": "Relevant memory:\n" + mem})
        elif unavailable:
            # Say so. A prompt that lost its memory block was
            # byte-identical to one where the store was read and nothing
            # matched, and the difference matters: the second means "you
            # have not seen this before", the first means "you cannot
            # see". An observer measured when this starts happening --
            # `retrieve` reads and embeds EVERY record of each kind, so
            # at ~1,000 records under load it crosses the 0.25s timeout
            # here, and consolidation's own steady state is 2,000 per
            # kind (2026-09-10). This is the normal case, not an edge.
            blocks.append({"role": "system", "content": MEMORY_UNAVAILABLE_NOTE.format(
                why=unavailable)})

        # Live-caught by the same audit: this was sent on the *first* step
        # only (`session.py` clears `pending_user_text` after one use) and
        # never entered `session.messages`, so from step 2 of 8 the model
        # no longer had the request in front of it -- only its own tool
        # calls and their output. A patch session that applied a file and
        # then stopped had, by then, genuinely lost the instruction.
        if task:
            blocks.append({"role": "user", "content": task})
        if session.carried:
            # A retry continues; it does not start over. Without this the
            # model re-did the first N steps every attempt (2026-09-07).
            if session.uncommitted:
                tree = (
                    "Their uncommitted edits to " + ", ".join(sorted(session.uncommitted))
                    + " are STILL IN THE TREE: do not re-apply them -- run the tests and commit them."
                )
            else:
                tree = "Edits they left uncommitted were discarded; anything they committed is in the tree."
            blocks.append({"role": "user", "content": (
                f"This is attempt {session.attempt} at the task. Earlier attempts ran out of steps or "
                f"were blocked; here is what they did, so you continue rather than repeat it. {tree}\n\n"
                + session.carried
            )})

        blocks.extend(session.messages)
        return blocks

    async def _request(self, type_: str, payload: dict, *, trace_id: str | None = None) -> Message | None:
        # `self._bus.source` (never a hardcoded literal): in `local-multi`
        # mode this Worker's own `BusClient` is bound to an instance-
        # qualified source (`orchestration@w1`), and `ReservedTopologyPolicy`
        # authenticates only the exact source `ContextFactory.build` issued
        # a token for -- a bare `"orchestration"` request would raise
        # `PolicyViolation` before ever reaching Memory/Self/World/Persona.
        #
        # `trace_id` (caller-supplied, usually `session.task_id`): without
        # it `Message.new` mints a fresh uuid4 per call and every message
        # gets its own `trace:<uuid>` ledger stream (`bus/trace.py`), so a
        # single task's memory-retrieve/world-facet requests each spawned
        # their own 1-2-event stream instead of joining the task's.
        # Measured 2026-09-08: 3 trivial chat tasks produced 74 such
        # fragments. This closes this module's two call sites (and
        # `session.py`/`worker.py`'s own internal `Message.new` calls got
        # the same treatment alongside this) -- Cognition's and
        # Execution's internal requests still mint their own; threading a
        # trace_id through those ~15 remaining call sites needs its own
        # pass (they don't uniformly have a task id in scope the way every
        # orchestration call site already does via `session`).
        req = Message.new(type_, source=self._bus.source, payload=payload, trace_id=trace_id, clock=self._clock)
        reply = await self._bus.request_or_error(req, timeout=self._timeout_s)
        if reply.payload.get("ok") is False:
            return None
        return reply

    async def _request_with_reason(self, type_: str, payload: dict, *,
                                   trace_id: str | None = None) -> tuple[Message | None, str]:
        """`(reply, why not)`. The reason exists because dropping a
        block in silence is indistinguishable from having nothing to
        put in it."""
        reply = await self._request(type_, payload, trace_id=trace_id)
        if reply is not None:
            return reply, ""
        return None, "it did not answer in time"

    async def _memory_block(self, query: str, session: Session) -> tuple[str, str]:
        """`(what to show, why there is nothing)`.

        A successful recall that matched nothing returns `("", "")` --
        silence is right there, because "I have no memory of this" is
        already what an absent block means."""
        reply, why = await self._request_with_reason(
            topics.MEMORY_RETRIEVE,
            {"query": query, "kinds": ["episodic", "semantic"], "k": 8},
            trace_id=session.task_id,
        )
        if reply is None:
            return "", why
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
        return "\n".join(lines), ""

    async def world_facet(self, what: str, args: dict | None = None, *, trace_id: str | None = None) -> dict | None:
        reply = await self._request(topics.WORLD_ENV_QUERY, {"what": what, "args": args or {}}, trace_id=trace_id)
        return reply.payload if reply else None
