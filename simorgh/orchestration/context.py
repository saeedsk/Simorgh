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
#: what Sim remembers with the person who is speaking (tag person:<name>)
_MEMORY_PERSON_K = 5
#: How many recent turns of THIS conversation (channel + person) travel
#: with a chat turn, rendered before the memory block. Fed by Memory
#: from `turn.completed` (2026-09-19); the similarity recall below is
#: the wrong instrument for "what we were just saying" and this is the
#: right one.
_WORKING_K = 6
#: The conversation from its session stream (stage 4 item 3): up to this
#: many exchanges, within this many characters. It is durable and ordered,
#: so it can hold far more than Memory's six-turn window: the recall
#: scenario's machine names, told at turn 1 and asked at turn 14, were out
#: of a six-turn window and reached the prompt only by similarity search.
_CONVERSATION_K = 30
_CONVERSATION_CHARS = 6000

WORKING_BLOCK_HEADER = (
    "The conversation so far with this person, oldest first (the memory below is older than this):\n"
)

#: The memory block's own header. It says two things the bare "Relevant
#: memory:" could not: what order the lines are in, and what to do when
#: two of them disagree. Without the second sentence a superseded fact
#: and its correction arrive as peers and the model picks whichever is
#: stated more confidently -- which is reliably the original, since a
#: correction is short and the thing it corrects came with a full answer
#: restating it.
#: What HOLDS now, ahead of what was said (stage 5 items 3-4). A fact and
#: an episode disagree only when a correction has not been folded into the
#: episodes, and the fact is the one that was superseded deliberately.
FACTS_BLOCK_HEADER = (
    "What you know to be true right now (each was told to you; the current value first, and "
    "what it replaced where it replaced something). These are more reliable than the "
    "conversation lines below, which include things that have since changed:\n"
)


def _fact_lines(facts: list[dict]) -> str:
    """The facts as lines: the current value, and what it replaced."""
    lines = []
    for fact in facts[:8]:
        line = " ".join(str(fact.get(part) or "") for part in ("subject", "predicate", "object")).strip()
        if not line:
            continue
        who = str(fact.get("person_scope") or "*")
        if who and who != "*":
            line = f"{who}: {line}"
        if fact.get("was"):
            line += f" (was {fact['was']}, until you were told otherwise)"
        lines.append(f"- {line}")
    return "\n".join(lines)


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


async def _nothing() -> str:
    return ""


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
    def __init__(self, bus, *, clock=None, timeout_s: float = DEFAULT_TIMEOUT_S, ledger=None) -> None:
        self._bus = bus
        self._clock = clock
        self._timeout_s = timeout_s
        # Where the conversation's session stream is read (stage 4 item 3).
        self._ledger = ledger

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
        (mem, unavailable, facts), working = await asyncio.gather(
            self._memory_block(task or session.task_id, session),
            self._working_block(session) if getattr(session.profile, "scaffold", "") == "chat" else _nothing(),
        )
        if working:
            blocks.append({"role": "system", "content": working})
        if facts:
            blocks.append({"role": "system", "content": FACTS_BLOCK_HEADER + facts})
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
            # A chat turn's text is no longer repeated in `task_rules` (it
            # changed the system prefix every turn, stage 4 item 4), so this
            # message is its only copy: protected, so Cognition's compactor
            # never snips the question away under a long run of results.
            chat = getattr(session.profile, "scaffold", "") == "chat"
            blocks.append({"role": "user", "content": task, **({"protected": True} if chat else {})})
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

    async def _memory_block(self, query: str, session: Session) -> tuple[str, str, str]:
        """`(what to show, why there is nothing, the facts block)`.

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
        # A task also recalls procedural memory: Reflection's critiques of
        # earlier tasks, the lessons a patch or research session should
        # not have to relearn. A chat turn does not -- those are about
        # Sim's work, not about the person (2026-09-18 evaluation, C7).
        chat = getattr(session.profile, "scaffold", "") == "chat"
        matched_kinds = ["episodic", "semantic"] if chat else ["episodic", "semantic", "procedural"]
        matched_call = self._request_with_reason(
            topics.MEMORY_RETRIEVE,
            {"query": query, "kinds": matched_kinds, "k": _MEMORY_MATCHED_K},
            trace_id=session.trace,
        )
        recent_call = self._request_with_reason(
            topics.MEMORY_RETRIEVE,
            {"query": "", "kinds": ["episodic"], "k": _MEMORY_RECENT_K},
            trace_id=session.trace,
        )
        speaker = str(getattr(session, "speaker", "") or "")
        calls = [matched_call, recent_call]
        if speaker:
            # A third recall, for a spoken turn whose speaker is known: what
            # was said with this person, whatever the topic -- a family of
            # several is several histories, not one (2026-09-13).
            calls.append(self._request_with_reason(
                topics.MEMORY_RETRIEVE,
                {"query": query, "kinds": ["episodic", "semantic"], "k": _MEMORY_PERSON_K,
                 "filters": {"tags": [f"person:{speaker}"]}},
                trace_id=session.trace,
            ))
        results = await asyncio.gather(*calls)
        (matched, why), (recent, _recent_why) = results[0], results[1]
        person = results[2][0] if speaker else None
        # The facts the query mentions ride back with the matched recall
        # (stage 5 item 3): `memory.retrieve.reply.facts`.
        facts = _fact_lines(matched.payload.get("facts") or []) if matched is not None else ""
        if matched is None and recent is None and person is None:
            return "", why, ""
        matched_items = list(matched.payload.get("items", [])) if matched is not None else []
        recent_items = list(recent.payload.get("items", [])) if recent is not None else []
        person_items = list(person.payload.get("items", [])) if person is not None else []

        # Recent first in the *selection* order, because those are the
        # ones nothing else can bring back: a matched item that gets
        # dropped here was found by similarity and will be found again
        # next turn, while a recent one that gets dropped is simply gone
        # until it happens to become lexically relevant.
        # A turn spoken by one person is theirs: it comes back for them
        # (the third recall) and for nobody else -- not for another
        # family member, not for a voice Sim does not know. Until this an
        # observer found the block for Ira, Aran and a stranger byte-
        # identical, Ira's "secret hideout" line included (2026-09-13).
        # Typed turns carry no person tag and stay shared.
        def _theirs(item: dict) -> bool:
            owners = [t[len("person:"):] for t in (item.get("tags") or []) if str(t).startswith("person:")]
            return not owners or (bool(speaker) and speaker in owners)

        if str(getattr(session, "channel", "") or "") == "voice":
            recent_items = [i for i in recent_items if _theirs(i)]
            matched_items = [i for i in matched_items if _theirs(i)]
        chosen: dict[str, dict] = {}
        for item in [*recent_items[:_MEMORY_RECENT_K], *person_items[:_MEMORY_PERSON_K], *matched_items[:_MEMORY_MATCHED_K]]:
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
        return "\n".join(f"- {i['content']}" for i in kept), "", facts

    @staticmethod
    def _fact_lines(facts: list[dict]) -> str:
        return _fact_lines(facts)

    async def _working_block(self, session: Session) -> str:
        """The last `_WORKING_K` turns of this (channel, person)
        conversation, from Memory's working window, oldest first."""
        from simorgh.contracts.settings import conversation_key

        if self._ledger is not None:
            # The conversation's own session stream first (stage 4 item 3):
            # durable, where Memory's window lives in process memory.
            from .transcript import conversation_id, recent_lines

            try:
                lines = await recent_lines(self._ledger, conversation_id(getattr(session, "channel", ""),
                                                                         getattr(session, "speaker", "")),
                                           _CONVERSATION_K)
            except Exception:  # noqa: BLE001 -- fall back to Memory's window
                lines = []
            if lines:
                # Newest first into the budget, then back in order: a long
                # conversation keeps its latest turns whole.
                kept, used = [], 0
                for line in reversed(lines):
                    if used + len(line) > _CONVERSATION_CHARS and kept:
                        break
                    kept.append(line)
                    used += len(line) + 1
                return WORKING_BLOCK_HEADER + "\n".join(reversed(kept))
        key = conversation_key(getattr(session, "channel", ""), getattr(session, "speaker", ""))
        reply, _why = await self._request_with_reason(
            topics.MEMORY_RETRIEVE,
            {"query": "", "kinds": ["working"], "k": _WORKING_K, "filters": {"session_id": key}},
            trace_id=session.trace,
        )
        if reply is None:
            return ""
        items = sorted(reply.payload.get("items", []), key=lambda i: float(i.get("ts") or 0.0))
        lines = [str(i.get("content", "")).strip() for i in items[-_WORKING_K:]]
        lines = [line for line in lines if line]
        return WORKING_BLOCK_HEADER + "\n".join(lines) if lines else ""

    async def world_facet(self, what: str, args: dict | None = None, *, trace_id: str | None = None) -> dict | None:
        reply = await self._request(topics.WORLD_ENV_QUERY, {"what": what, "args": args or {}}, trace_id=trace_id)
        return reply.payload if reply else None
