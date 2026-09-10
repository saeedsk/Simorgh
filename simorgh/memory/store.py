"""The memory engine (docs/blueprint/subsystems/05-memory.md sections 4-5):
episodic/semantic/procedural records as one-event-per-item Ledger streams
(`memory:episodic`, `memory:semantic`, `memory:procedural`), retrieval by
lexical+embedding similarity times confidence plus a recency term,
confidence decay ported from v1 `score_confidence`, and forgetting as a
tombstone stream rather than a physical delete -- append-only stays
append-only (principle 4.4) even for "pruning."

Working memory is deliberately NOT a Ledger stream: it is a bounded,
non-durable rolling window per session, exactly like v1's
`ShortTermMemory` -- it resets with the process, the way working memory
doesn't survive the way consolidated long-term memory does.
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
from dataclasses import replace

from simorgh.contracts.envelope import Event
from simorgh.contracts.protocols import Clock, Ledger

from .api import MemoryItem, Turn
from .config import Config
from .embed import cosine_similarity, embed_text
from .embedders import Embedder, comparable

KINDS = ("episodic", "semantic", "procedural")
TOMBSTONE_STREAM = "memory:tombstones"
CONTRADICTION_STREAM = "memory:contradictions"


def stream_for(kind: str) -> str:
    return f"memory:{kind}"


#: Appended to a memory that came back shorter than it was stored.
#: Said in the content itself because that is the only part of a recall
#: that reaches the model.
#: A PREFIX, not a suffix. On the tail it never survived: the only
#: consumer (`orchestration/context.py`) trims each recalled item to 800
#: characters, so the notice was cut off the end of every memory long
#: enough to need it -- the fix was invisible exactly where it mattered
#: (observer, 2026-09-10, on the fix from the same morning).
TRUNCATION_NOTICE = ("[memory truncated: {have} of {want} characters recovered; "
                     "the rest is not available]\n\n")


class WorkingMemory:
    """Per-session bounded rolling window -- the working-memory kind,
    kept in-process (never durable), ported from v1 `ShortTermMemory`.

    Both sides Memory owns are done: `Service._on_store` special-cases
    `kind="working"` to call `.add` instead of appending to a Ledger
    stream, and `MemoryEngine.retrieve` answers `kinds=["working"]`
    from here. What is still missing is a producer -- 2026-09-08
    observer audit found nothing in the codebase publishes
    `memory.store{kind:"working"}` outside tests, so `working_max_turns`
    /`working_max_chars` bound a window that never receives real data.

    The plausible producer -- the current task's own scratch state, so
    a multi-step attempt does not repeat itself -- is deliberately not
    wired here. `orchestration/api.py`'s `Session` already carries that
    exact state in-process (`session.steps`, `session.messages`, and
    `carried` for what a *retry* already tried) and hands it straight
    to `cognition.think`; routing the same data through a
    publish/subscribe round trip into this class would duplicate it,
    not connect a missing wire. Making within-task scratch state
    durable/shared (e.g. visible to Guardian or Reflection via
    `memory.retrieve`) is a real product decision -- whether the
    Session's private state should become cross-subsystem-visible, and
    at what per-step publish-volume cost -- not a low-risk wiring fix,
    so it is left to whoever owns that call."""

    def __init__(self, *, max_turns: int, max_chars: int) -> None:
        self._max_turns = max_turns
        self._max_chars = max_chars
        self._sessions: dict[str, deque[Turn]] = defaultdict(deque)

    def add(self, session_id: str, request_text: str, response_text: str, *, ts: float) -> None:
        turns = self._sessions[session_id]
        turns.append(Turn(request_text, response_text, ts))
        while len(turns) > self._max_turns:
            turns.popleft()
        while len(turns) > 1 and self._total_chars(turns) > self._max_chars:
            turns.popleft()

    def recent(self, session_id: str, limit: int | None = None) -> list[Turn]:
        turns = list(self._sessions.get(session_id, ()))
        return turns[-limit:] if limit is not None else turns

    def _total_chars(self, turns: deque[Turn]) -> int:
        return sum(len(t.request_text) + len(t.response_text) for t in turns)


class MemoryEngine:
    def __init__(self, ledger: Ledger, config: Config, *, clock: Clock, embedder=None) -> None:
        self._ledger = ledger
        self._config = config
        self._clock = clock
        # `embed.py`'s hashing trick unless something better is
        # configured (`embedders.py`). Constructed once: choosing the
        # provider reads the environment, and the instance holds the
        # cache that stops one `retrieve` re-embedding the whole store.
        self._embedder = embedder or Embedder(config.embedder)
        self.working = WorkingMemory(max_turns=config.working_max_turns, max_chars=config.working_max_chars)
        # ref -> blob ref, for items whose content was too long to sit
        # inline. Filled while scanning, read only for what is returned.
        self._content_refs: dict[str, str] = {}
        # How long each blobbed memory really is, by ref. Read back at
        # recall so a partial recovery can say so -- see
        # `_resolve_content`.
        self._content_chars: dict[str, int] = {}

    # -- store -----------------------------------------------------------------------
    #: The Ledger refuses any string longer than this inline
    #: (`ledger/client.py::inline_threshold`). A little under it, so a
    #: preview plus the other payload fields still fits.
    _INLINE_CONTENT_MAX = 3500

    async def store(self, *, kind: str, content: str, tags: list[str], source_ref: str, confidence: float | None) -> str:
        """Remember one item, however long it is.

        Long content goes to a blob and the payload keeps a preview plus
        a `content_ref`. Before this, `store` appended the whole string
        inline and the Ledger refused anything over 4096 characters --
        so **the longer and more useful an answer was, the more certain
        it was to be forgotten**, and the refusal surfaced as an
        unhandled `ValidationError` out of the `turn.completed` handler
        rather than as anything a person could act on. Caught live
        2026-09-09 on a 5,165-character reply.

        The preview is kept inline on purpose rather than blobbing
        everything: `retrieve` scores every candidate by its text, and
        fetching a blob per candidate would turn one recall into
        hundreds of reads. Score on the preview, return the whole thing.
        """
        stream = stream_for(kind)
        payload = {"tags": list(tags), "source_ref": source_ref,
                   "confidence": confidence if confidence is not None else 1.0}
        if len(content) > self._INLINE_CONTENT_MAX:
            try:
                payload["content_ref"] = await self._ledger.put_blob(content.encode("utf-8"))
                payload["content"] = content[: self._INLINE_CONTENT_MAX]
                payload["content_chars"] = len(content)
            except Exception:  # noqa: BLE001 -- a truncated memory beats a lost one
                payload["content"] = content[: self._INLINE_CONTENT_MAX]
                payload["content_chars"] = len(content)
        else:
            payload["content"] = content
        seq = await self._ledger.append(stream, Event(
            stream=stream, type="item.stored", ts=self._clock.now(), trace_id="", causation_id=None,
            idempotency_key=f"{stream}:{uuid.uuid4().hex}",
            payload=payload,
        ))
        return f"{stream}:{seq}"

    async def _resolve_content(self, items: list) -> list:
        """Swap each item's preview for its full text, and say so when
        only part of it came back.

        Only for the items actually being returned. Doing it during
        scoring would mean a blob read per candidate, which is a
        hundred reads to answer one question.

        `content_chars` has been written at store time since the blob
        split landed and nothing ever read it, so both partial paths --
        a blob that could not be written, and a blob that cannot now be
        read -- returned a 3,500-character prefix cut mid-sentence and
        indistinguishable from a memory that was genuinely that short.
        A memory system that quietly shortens what it remembers is the
        "succeeds while saying nothing true" failure in the one place it
        is hardest to notice (observer, 2026-09-10).
        """
        out = []
        for item in items:
            truncated_bytes = False
            ref = self._content_refs.get(item.ref)
            full = None
            if ref:
                try:
                    raw = await self._ledger.get_blob(ref)
                except Exception:  # noqa: BLE001 -- the preview is still worth returning
                    raw = None
                full = None
                if raw is not None:
                    try:
                        # Strictly first: `errors="replace"` turns a blob
                        # cut mid-character into a same-length string
                        # with a replacement char in it, so the length
                        # check below saw nothing wrong and the memory
                        # came back looking whole, ending in a "?"
                        # (observer, 2026-09-10).
                        full = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        full = raw.decode("utf-8", "replace")
                        truncated_bytes = True
            content = full if full is not None else item.content
            expected = self._content_chars.get(item.ref, 0)
            if truncated_bytes or (expected and len(content) < expected):
                content = TRUNCATION_NOTICE.format(
                    have=len(content), want=expected or len(content)) + content
            out.append(replace(item, content=content) if content != item.content else item)
        return out

    # -- retrieve --------------------------------------------------------------------
    async def retrieve(self, *, query: str, kinds: list[str], k: int, filters: dict | None) -> tuple[list[MemoryItem], bool]:
        filters = filters or {}
        tombstoned = await self._tombstoned_refs()
        penalties = await self._contradiction_penalties()
        # `(provider, vector)`, because a vector is only comparable to
        # another from the same embedder -- see `_score`.
        query_pair = (*self._embedder.embed(query), query) if query else None
        candidates: list[tuple[float, MemoryItem]] = []
        now = self._clock.now()

        for kind in kinds:
            if kind == "working":
                session_id = filters.get("session_id")
                if session_id:
                    for i, turn in enumerate(self.working.recent(session_id)):
                        content = f"{turn.request_text}\n{turn.response_text}"
                        item = MemoryItem(ref=f"working:{session_id}:{i}", kind="working", content=content,
                                          tags=(), confidence=1.0, ts=turn.ts)
                        candidates.append((self._score(query_pair, content, item, now, penalties.get(item.ref, 1.0)), item))
                continue
            for event in await self._ledger.read(stream_for(kind)):
                ref = f"{stream_for(kind)}:{event.seq}"
                if ref in tombstoned:
                    continue
                tags = tuple(event.payload.get("tags", []))
                # `filters["tags"]` is a MUST-HAVE-ALL set, not "any of" --
                # an intersection check here let a shared tag (every skill's
                # procedural record carries "skill" alongside its own name)
                # pass the filter for every OTHER skill's record too, so a
                # caller doing `filters={"tags": ["skill", name]}` to pick
                # out ONE skill's record got the whole "skill"-tagged pool
                # back instead (live-caught, 2026-09-08: two skills
                # acquired in one session, `_skill_description("greet")`
                # returned `farewell`'s record because it happened to be
                # the more recent one and lexical similarity was a tie).
                if filters.get("tags") and not set(filters["tags"]) <= set(tags):
                    continue
                if filters.get("since") is not None and event.ts < filters["since"]:
                    continue
                content_ref = event.payload.get("content_ref")
                if content_ref:
                    self._content_refs[ref] = str(content_ref)
                if event.payload.get("content_chars"):
                    self._content_chars[ref] = int(event.payload["content_chars"])
                item = MemoryItem(ref=ref, kind=kind, content=event.payload.get("content", ""), tags=tags,
                                  confidence=float(event.payload.get("confidence", 1.0)), ts=event.ts,
                                  source_ref=event.payload.get("source_ref", ""))
                candidates.append((self._score(query_pair, item.content, item, now, penalties.get(ref, 1.0)), item))

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        truncated = len(candidates) > k
        # The relevance number travels with the item. Computing it and
        # throwing it away was why the reply had to report something
        # else under the name "score".
        chosen = [replace(item, score=score) for score, item in candidates[:k]]
        return await self._resolve_content(chosen), truncated

    def _score(self, query_pair, content: str, item: MemoryItem, now: float, penalty: float) -> float:
        similarity = self._similarity(query_pair, content) if query_pair is not None else 1.0
        confidence = item.score_confidence(now=now, half_life_seconds=self._config.half_life_seconds, penalty=penalty)
        age_days = max(0.0, now - item.ts) / 86400.0
        recency_bonus = 1.0 / (1.0 + age_days)
        return similarity * confidence + self._config.recency_weight * recency_bonus

    def _similarity(self, query_pair, content: str) -> float:
        """Cosine similarity, but only ever between two vectors from the
        SAME embedder.

        The trap this exists for: a provider is allowed to fail one call
        and fall back to hashing (`Embedder.embed` degrades rather than
        raising, because a memory subsystem that throws is worse than
        one that recalls poorly). So within a single `retrieve`, the
        query can be a 1536-dim OpenAI vector while one item's content
        falls back to a 256-dim hashed one. `zip()` would compare them
        happily, over the first 256 components, and return a number that
        means nothing -- silently wrong recall rather than an error.

        When the two disagree, both sides are re-embedded with hashing.
        That is the one embedder guaranteed to be available and
        deterministic, so the comparison is at worst crude, never
        meaningless.
        """
        query_provider, query_vec, query_text = query_pair
        content_provider, content_vec = self._embedder.embed(content)
        if not comparable(query_provider, content_provider):
            return cosine_similarity(embed_text(query_text), embed_text(content))
        return cosine_similarity(query_vec, content_vec)

    # -- contradiction / forgetting ----------------------------------------------------
    async def flag_contradictions(self, *, kind: str = "semantic") -> list[tuple[str, str, str]]:
        """Groups records by their first tag (the closest analog to v1's
        `metadata["subject"]`); for any group with more than one distinct
        content, flags the two most recent as contradicting -- append-only
        (a durable `contradictions` event), never a mutation of the
        original records (05 section 5, "confidence/decay")."""
        by_tag: dict[str, list[tuple[str, Event]]] = defaultdict(list)
        for event in await self._ledger.read(stream_for(kind)):
            tags = event.payload.get("tags", [])
            if not tags:
                continue
            ref = f"{stream_for(kind)}:{event.seq}"
            by_tag[tags[0]].append((ref, event))

        flagged: list[tuple[str, str, str]] = []
        for tag, items in by_tag.items():
            distinct = {e.payload.get("content") for _, e in items}
            if len(distinct) < 2:
                continue
            items.sort(key=lambda pair: pair[1].ts, reverse=True)
            (ref_a, ev_a), (ref_b, ev_b) = items[0], items[1]
            if ev_a.payload.get("content") == ev_b.payload.get("content"):
                continue
            evidence = f"both tagged {tag!r}: {ev_a.payload.get('content')!r} vs {ev_b.payload.get('content')!r}"
            await self._ledger.append(CONTRADICTION_STREAM, Event(
                stream=CONTRADICTION_STREAM, type="flagged", ts=self._clock.now(), trace_id="", causation_id=None,
                idempotency_key=f"contradiction:{ref_a}:{ref_b}",
                payload={"ref_a": ref_a, "ref_b": ref_b, "evidence": evidence},
            ))
            flagged.append((ref_a, ref_b, evidence))
        return flagged

    async def forget(self, refs: list[str], *, reason: str) -> None:
        await self._ledger.append(TOMBSTONE_STREAM, Event(
            stream=TOMBSTONE_STREAM, type="forgotten", ts=self._clock.now(), trace_id="", causation_id=None,
            payload={"refs": list(refs), "reason": reason},
        ))

    async def prune(self, *, kind: str, keep: int) -> int:
        """v1 `_prune_kind`: tombstone every record of `kind` past the
        most recent `keep` (by score-confidence, not just insertion
        order) -- a "forgotten" event, never a physical delete."""
        now = self._clock.now()
        penalties = await self._contradiction_penalties()
        scored = []
        for event in await self._ledger.read(stream_for(kind)):
            ref = f"{stream_for(kind)}:{event.seq}"
            item = MemoryItem(ref=ref, kind=kind, content=event.payload.get("content", ""),
                              tags=tuple(event.payload.get("tags", [])), confidence=float(event.payload.get("confidence", 1.0)),
                              ts=event.ts)
            scored.append((item.score_confidence(now=now, half_life_seconds=self._config.half_life_seconds, penalty=penalties.get(ref, 1.0)), ref))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        stale = [ref for _, ref in scored[keep:]] if keep >= 0 else []
        if stale:
            await self.forget(stale, reason=f"pruned below top {keep} of kind={kind}")
        return len(stale)

    async def counts(self) -> dict[str, int]:
        """Live (non-tombstoned) record count per durable kind -- a
        dashboard's "what does Sim remember" view (02-system-architecture.md
        section 6.2), not anything `retrieve()`'s own scoring/truncation
        needs, so kept as its own cheap pass over each kind's stream."""
        tombstoned = await self._tombstoned_refs()
        counts: dict[str, int] = {}
        for kind in KINDS:
            stream = stream_for(kind)
            events = await self._ledger.read(stream)
            counts[kind] = sum(1 for e in events if f"{stream}:{e.seq}" not in tombstoned)
        return counts

    async def _tombstoned_refs(self) -> set[str]:
        refs: set[str] = set()
        for event in await self._ledger.read(TOMBSTONE_STREAM):
            refs.update(event.payload.get("refs", []))
        return refs

    async def _contradiction_penalties(self) -> dict[str, float]:
        penalties: dict[str, float] = {}
        for event in await self._ledger.read(CONTRADICTION_STREAM):
            penalties[event.payload["ref_a"]] = penalties.get(event.payload["ref_a"], 1.0) * 0.5
            penalties[event.payload["ref_b"]] = penalties.get(event.payload["ref_b"], 1.0) * 0.5
        return penalties


__all__ = ["CONTRADICTION_STREAM", "KINDS", "MemoryEngine", "TOMBSTONE_STREAM", "WorkingMemory", "stream_for"]
