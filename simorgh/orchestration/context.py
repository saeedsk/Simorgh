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

import asyncio

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

#: How many memories the similarity search contributes.
_MEMORY_MATCHED_K = 8

#: How many of the most RECENT episodic memories travel with every turn
#: regardless of what this particular line happens to be about.
#:
#: A CLI chat turn has no transcript of its own. `_handle_chat` mints a
#: fresh `session_id` per typed line (`interface/service.py`) and
#: `run_percept_chat` builds a throwaway `Session` from it, so the ONLY
#: thing standing in for "what we were just saying" is the similarity
#: search below -- which ranks by vocabulary overlap with the current
#: line, and is therefore exactly the wrong instrument for conversation.
#:
#: Measured in a real 22-turn CLI session (observer, 2026-09-10), against
#: the actual ledger it produced:
#:
#: * Turn 2 was "one mini PC called falcon ... a Raspberry Pi 4 called
#:   sparrow ... Please remember those two names, I'll use them
#:   constantly." Turns 14 and 19 -- and turn 3 of the NEXT run, after a
#:   restart -- all answered "I don't have your two machines' names ...
#:   they never made it into my notes." The record was in the store the
#:   whole time. Replaying the real query against the real ledger:
#:   `memory:episodic:2` is not in the top 8, and an unrelated
#:   autonomous code-patch record about deque eviction is.
#: * Turn 9 corrected a birthday from March 4th to March 6th and was
#:   acknowledged. Turns 10, 12, 14, 22 and (post-restart) 103 each
#:   volunteered "March 4th" -- not because the correction was outranked,
#:   but because for THOSE queries only the superseded record came back.
#:   Asked the question head-on, turns 13, 20 and 102 said "March 6th".
#:   The same question got two different answers two turns apart.
#:
#: Both are the same missing thing. Six is small enough to cost little
#: and enough to cover a correction plus the digression it survived.
_MEMORY_RECENT_K = 6

#: The memory block's own header. It says two things the bare "Relevant
#: memory:" could not: what order the lines are in, and what to do when
#: two of them disagree. Without the second sentence a superseded fact
#: and its correction arrive as peers and the model picks whichever is
#: stated more confidently -- which is reliably the original, since a
#: correction is short and the thing it corrects came with a full answer
#: restating it.
MEMORY_BLOCK_HEADER = (
    "Relevant memory, oldest first. Later lines are more recent: where two disagree, the "
    "later one is the current truth and the earlier one has been superseded -- say so rather "
    "than repeating the old value.\n"
)

#: Shown in place of the memory block when the store could not be
#: consulted, so "I have not seen this before" and "I could not look"
#: are different prompts. Addressed to the model, because the model is
#: the one about to reason as though it had checked.
MEMORY_UNAVAILABLE_NOTE = (
    "Your memory could not be consulted for this request ({why}), so treat anything "
    "you would expect to remember as unknown rather than absent. Say so if it matters."
)

#: How much of a subsystem's own `error.detail` may travel into the
#: prompt. It is our own text, not a user's, but a prompt is no place
#: for an unbounded string.
_REASON_MAX_CHARS = 120


def _why_not(error: dict) -> str:
    """Why a request produced no usable reply, in the words of the reply
    itself.

    This used to say "it did not answer in time" for every failure,
    because `_request` collapses a timeout and a real error reply to the
    same `None`. Live-caught by an observer (2026-09-10): Memory
    replying instantly with `unavailable: store backend is down` put "it
    did not answer in time" into the prompt -- the one note whose entire
    reason to exist is telling the model the truth about what it can
    see, saying something false about why. A slow store and a broken one
    are also different things to whoever reads the transcript afterwards.
    """
    code = str(error.get("code") or "").strip()
    if code == "timeout":
        return "it did not answer in time"
    detail = " ".join(str(error.get("detail") or "").split())
    if len(detail) > _REASON_MAX_CHARS:
        detail = detail[:_REASON_MAX_CHARS] + "…"
    if code and detail:
        return f"it answered with an error: {code} -- {detail}"
    if code:
        return f"it answered with an error: {code}"
    return "it answered with an error"


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
            blocks.append({"role": "system", "content": MEMORY_BLOCK_HEADER + mem})
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
        reply, _why = await self._request_with_reason(type_, payload, trace_id=trace_id)
        return reply

    async def _request_with_reason(self, type_: str, payload: dict, *,
                                   trace_id: str | None = None) -> tuple[Message | None, str]:
        """`(reply, why not)`. The reason exists because dropping a
        block in silence is indistinguishable from having nothing to
        put in it -- and it is read off the reply, not assumed, because
        a wrong reason is its own kind of silence (see `_why_not`)."""
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
            return None, _why_not(reply.payload.get("error") or {})
        return reply, ""

    async def _memory_block(self, query: str, session: Session) -> tuple[str, str]:
        """`(what to show, why there is nothing)`.

        Two recalls, not one, and they answer different questions.

        The **matched** recall is the old behaviour: what in the store
        looks like this request. The **recent** recall (`query=""`,
        which scores every record equally and lets the recency bonus do
        the ordering -- see `MemoryEngine.retrieve`) is what we were just
        saying. A chat turn has no transcript of its own to fall back on
        (see `_MEMORY_RECENT_K`), so without the second one a fact told
        two turns ago is only remembered if the current sentence happens
        to share vocabulary with it.

        They are issued together, so this still costs one `_timeout_s`
        rather than two: the point of that budget is that a slow Memory
        never stalls a session, and gathering keeps that true.

        A successful recall that matched nothing returns `("", "")` --
        silence is right there, because "I have no memory of this" is
        already what an absent block means."""
        matched_call = self._request_with_reason(
            topics.MEMORY_RETRIEVE,
            {"query": query, "kinds": ["episodic", "semantic"], "k": _MEMORY_MATCHED_K},
            trace_id=session.task_id,
        )
        recent_call = self._request_with_reason(
            topics.MEMORY_RETRIEVE,
            {"query": "", "kinds": ["episodic"], "k": _MEMORY_RECENT_K},
            trace_id=session.task_id,
        )
        (matched, why), (recent, _recent_why) = await asyncio.gather(matched_call, recent_call)
        if matched is None and recent is None:
            return "", why
        matched_items = list(matched.payload.get("items", [])) if matched is not None else []
        recent_items = list(recent.payload.get("items", [])) if recent is not None else []

        # Recent first in the *selection* order, because those are the
        # ones nothing else can bring back: a matched item that gets
        # dropped here was found by similarity and will be found again
        # next turn, while a recent one that gets dropped is simply gone
        # until it happens to become lexically relevant.
        chosen: dict[str, dict] = {}
        for item in [*recent_items[:_MEMORY_RECENT_K], *matched_items[:_MEMORY_MATCHED_K]]:
            ref = str(item.get("ref", ""))
            key = ref or f"anon:{len(chosen)}"
            if key not in chosen:
                chosen[key] = item

        # ...but chronological in the *rendering* order, which is the
        # half that makes a correction win. See `MEMORY_BLOCK_HEADER`.
        # The aggregate cap is applied in PRIORITY order (the order
        # `chosen` was built in), not in the rendered one: what has to go
        # when the block is full is the least valuable memory, and that
        # is a question about rank and recoverability, not about date.
        kept: list[dict] = []
        total = 0
        for item in chosen.values():
            content = str(item.get("content", ""))
            if len(content) > _MEMORY_ITEM_MAX_CHARS:
                content = content[:_MEMORY_ITEM_MAX_CHARS] + "…"
            item = {**item, "content": content}
            if total + len(content) + 2 > _MEMORY_BLOCK_MAX_CHARS and kept:
                break  # keep the strongest, drop the rest honestly
            kept.append(item)
            total += len(content) + 2

        # ...and only now chronologically, which is the half that makes a
        # correction beat the thing it corrects. See MEMORY_BLOCK_HEADER.
        kept.sort(key=lambda i: float(i.get("ts") or 0.0))
        return "\n".join(f"- {i['content']}" for i in kept), ""

    async def world_facet(self, what: str, args: dict | None = None, *, trace_id: str | None = None) -> dict | None:
        reply = await self._request(topics.WORLD_ENV_QUERY, {"what": what, "args": args or {}}, trace_id=trace_id)
        return reply.payload if reply else None
