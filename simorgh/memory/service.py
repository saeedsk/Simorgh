"""`Service(Subsystem)` for Memory (docs/blueprint/subsystems/05-memory.md
sections 5, 9): wires `memory.retrieve`/`.store` and consolidation on
`system.tick.sleep`."""

from __future__ import annotations

import re as _re
import asyncio

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.messages.memory import EMBED_MAX_CHARS, EMBED_MAX_TEXTS
from simorgh.contracts.protocols import Context, Health

from .config import Config

#: How many facts a person's digest may carry into a prompt (stage 5 item
#: 4). Eight short lines is about 150 tokens, the budget the plan sets.
_DIGEST_FACTS = 8

#: The owner tag of a spoken turn whose voice nobody matched: it keeps the
#: turn out of every named person's recall (orchestration/context.py
#: `_theirs` treats only untagged turns -- typed ones -- as shared).
UNPLACED_VOICE_TAG = "person:unknown"

#: How long Memory waits for World Model's People store. Nobody waits on
#: the answer -- it runs in the background -- so this only bounds a task.
_PEOPLE_TIMEOUT_S = 5.0

from .consolidation import run_consolidation
from .embedders import HASHING
from .store import MemoryEngine

VERSION = "0.1.0"
DEFAULT_KEEP_PER_KIND = {"episodic": 2_000, "semantic": 2_000, "procedural": 500}


class Service:
    name = "memory"
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.MEMORY_RETRIEVE, topics.MEMORY_STORE, topics.SYSTEM_TICK_SLEEP, topics.TURN_COMPLETED,
        topics.SYSTEM_TICK_SECOND,
        # Subscribed in code, missing from this manifest until 2026-09-19 (evaluation V4):
        topics.MEMORY_FORGET,
        # Stage 15 item 8: `memory_core_edit`'s edit of a core block.
        topics.MEMORY_CORE_EDIT,
        # Stage 17: the tool router embeds with Memory's embedder, never its own.
        topics.MEMORY_EMBED,
    )
    produces: tuple[str, ...] = (
        topics.MEMORY_RETRIEVE_REPLY, topics.MEMORY_STORED, topics.MEMORY_CONTRADICTION_FLAGGED,
        topics.MEMORY_CONSOLIDATED, topics.MEMORY_FORGOTTEN, topics.SYSTEM_METRICS,
        topics.MEMORY_CORE_EDIT_REPLY,
        topics.MEMORY_EMBED_REPLY,
    )

    def __init__(self, *, config: Config | None = None, keep_per_kind: dict[str, int] | None = None) -> None:
        self._config_from_caller = config
        self._config = config or Config()
        self._keep_per_kind = keep_per_kind or dict(DEFAULT_KEEP_PER_KIND)
        self._tick_seconds = 0
        self._first_consolidation: asyncio.Task | None = None
        self._warm: asyncio.Task | None = None
        self._people_task: asyncio.Task | None = None

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        # Live-caught as a class 2026-09-08: every service is handed its
        # own `[section]` from simorgh.toml (`kernel/context.py` builds
        # `ctx.config` for exactly this) and eleven of them never read
        # it. The settings existed, were documented, were parsed into a
        # Config dataclass with a `from_mapping` -- and nothing ever
        # called it, so changing the file changed nothing. The dominant
        # bug shape in this codebase: a designed slot with one side
        # implemented and nobody writing to it.
        #
        # A config passed by the caller still wins, so a test that
        # constructs the service with one is unaffected.
        if self._config_from_caller is None and ctx.config:
            self._config = Config.from_mapping(dict(ctx.config))
        self.engine = MemoryEngine(ctx.ledger, self._config, clock=ctx.clock)
        self.engine._on_fact = self._announce_fact  # noqa: SLF001 -- the Service owns the bus, the engine the store
        self._sub_retrieve = await ctx.bus.subscribe(topics.MEMORY_RETRIEVE, self._on_retrieve)
        self._sub_store = await ctx.bus.subscribe(topics.MEMORY_STORE, self._on_store)
        self._sub_forget = await ctx.bus.subscribe(topics.MEMORY_FORGET, self._on_forget)
        self._sub_core_edit = await ctx.bus.subscribe(topics.MEMORY_CORE_EDIT, self._on_core_edit)
        self._sub_embed = await ctx.bus.subscribe(topics.MEMORY_EMBED, self._on_embed)
        self._sub_sleep = await ctx.bus.subscribe(topics.SYSTEM_TICK_SLEEP, self._on_sleep)
        self._sub_turn = await ctx.bus.subscribe(topics.TURN_COMPLETED, self._on_turn_completed)
        self._sub_tick = await ctx.bus.subscribe(topics.SYSTEM_TICK_SECOND, self._on_tick)
        # Boot is the right place to pay for the recall index -- see
        # `MemoryEngine.warm`. Not awaited: a large store takes a
        # noticeable moment and start() must not hold the Kernel up for
        # it. A recall that arrives first simply waits on the same work.
        self._warm = asyncio.create_task(self._warm_index(), name="memory-index-warm")
        if self._config.entities and self._config.people_refresh_s > 0:
            # Who the people are, for "my son" (stage 15); see `learn_people`.
            self._learn_people_soon()
        if self._config.consolidate_after_start_s > 0:
            self._first_consolidation = asyncio.create_task(
                self._consolidate_after_start(), name="memory-first-consolidation")

    async def _warm_index(self) -> None:
        try:
            records = await self.engine.warm()
            self._ctx.logger.info("memory.index_warmed", records=records)
            # A local model loads here, in a thread, after the index (stage 5
            # item 1): recall answers from hashing meanwhile, then what was
            # hashed is re-embedded and persisted.
            seconds = await self.engine.warm_embedder()
            if seconds:
                self._ctx.logger.info("memory.embedder_warmed", seconds=round(seconds, 1))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- an unwarmed index is slow, not broken
            self._ctx.logger.warning("memory.index_warm_failed", error=repr(exc))

    async def stop(self) -> None:
        if self._people_task is not None:
            self._people_task.cancel()
            try:
                await self._people_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._people_task = None
        if self._warm is not None:
            self._warm.cancel()
            try:
                await self._warm
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._warm = None
        if self._first_consolidation is not None:
            self._first_consolidation.cancel()
            try:
                await self._first_consolidation
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 -- shutdown must not raise from a background pass
                pass
            self._first_consolidation = None
        for sub in (self._sub_retrieve, self._sub_store, self._sub_forget, self._sub_core_edit, self._sub_embed, self._sub_sleep,
                    self._sub_turn, self._sub_tick):
            await sub.unsubscribe()

    async def _consolidate_after_start(self) -> None:
        """One consolidation pass shortly after boot.

        `DEFAULT_KEEP_PER_KIND` describes a steady state of 2,000
        records per kind, and `retrieve`'s cost is a function of exactly
        that number -- but nothing reached it. The only caller of
        `run_consolidation` was `system.tick.sleep`, and the Kernel's
        sleep loop waits a full `sleep_every_s` (6 hours, `kernel/api.py`)
        before its first tick and then `continue`s past it if the system
        is not RUNNING at that moment. Every session shorter than six
        hours -- which is nearly all of them -- pruned nothing and
        flagged no contradictions, so memory only ever grew. The Ledger
        hit the identical bug on 2026-09-07 (190,865 expired streams
        still on disk) and fixed it with `compact_after_start_s`; this
        is the same fix for the same reason.

        Deliberately not inside `start()`: the pass reads every durable
        stream and may ask Cognition for a distillation, and boot is not
        the place to wait for either. A failure is logged and dropped --
        memory that cannot consolidate still recalls.
        """
        try:
            await asyncio.sleep(self._config.consolidate_after_start_s)
            await self._consolidate(window=None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._ctx.logger.warning("memory.first_consolidation_failed", error=repr(exc))

    async def health(self) -> Health:
        return Health.ok()

    async def _on_forget(self, message: Message) -> None:
        """`memory.forget{minutes | since, until, kinds, containing, reason}`
        -> `memory.forget.reply{forgotten, refs}`; a `memory.forgotten`
        event when anything went."""
        payload = message.payload or {}
        now = self._ctx.clock.now()
        if payload.get("since") is not None:
            since = float(payload["since"])
        else:
            minutes = max(0.0, float(payload.get("minutes") or 0.0))
            since = now - minutes * 60.0
        until = float(payload["until"]) if payload.get("until") is not None else None
        kinds = tuple(str(k) for k in (payload.get("kinds") or ["episodic"]))
        reason = str(payload.get("reason") or "forgotten on request")
        refs = await self.engine.forget_window(since=since, until=until, kinds=kinds,
                                               containing=str(payload.get("containing") or ""), reason=reason)
        if refs:
            await self._ctx.bus.publish(Message.new(topics.MEMORY_FORGOTTEN, source=self._ctx.source,
                                                    payload={"refs": refs, "reason": reason}))
        await self._ctx.bus.reply(message, type=topics.MEMORY_FORGET_REPLY,
                                  payload={"forgotten": len(refs), "refs": refs, "since": since})

    async def _on_embed(self, message: Message) -> None:
        """`memory.embed{texts}` -> `memory.embed.reply{vectors, model,
        dimension, refused?}`: the configured embedder, lent to another
        subsystem (stage 17's tool router), so nothing loads a second model.

        Refused -- no vectors, `refused` saying why -- when the embedder is
        the hashing floor (configured, or degraded to it): a caller with
        its own stand-in (the router's lexical one knows Farsi stems and
        character trigrams) does better without it. Refused too while a
        local model is loading, when a text came back hashed mid-batch (a
        provider that failed for one text: a mixed batch is not comparable),
        for an empty text, and past `EMBED_MAX_TEXTS`. Each text is cut to
        `EMBED_MAX_CHARS`. The batch runs in a thread (`embed_many`: one
        model call for a local model), so the loop is never held."""
        texts = [str(t or "").strip()[:EMBED_MAX_CHARS] for t in (message.payload or {}).get("texts") or ()]
        embedder = self.engine.embedder
        model = str(getattr(embedder, "provider", "") or "")
        dimension = int(embedder.dimension())
        refused = ""
        if len(texts) > EMBED_MAX_TEXTS:
            refused = f"{len(texts)} texts; at most {EMBED_MAX_TEXTS} a request"
        elif model == HASHING:
            degraded = getattr(embedder, "degraded", "")
            refused = "the embedder is hashing" + (f" ({degraded})" if degraded else "")
        elif not getattr(embedder, "ready", True):
            refused = f"the {model} model is still loading"
        elif any(not t for t in texts):
            refused = "an empty text"
        vectors: list[list[float]] = []
        if not refused and texts:
            pairs = await asyncio.to_thread(embedder.embed_many, texts)
            if any(provider != model for provider, _ in pairs):
                refused = f"the {model} embedder fell back to hashing for part of the batch"
            else:
                vectors = [[float(x) for x in vector] for _, vector in pairs]
                dimension = len(vectors[0]) if vectors else dimension
        payload = {"vectors": vectors, "model": model, "dimension": dimension}
        if refused:
            payload["refused"] = refused
        await self._ctx.bus.reply(message, type=topics.MEMORY_EMBED_REPLY, payload=payload)

    async def _announce_fact(self, fact, superseded_id: str, *, also=()) -> None:
        """A fact that now holds, and the one it replaced (stage 5 item 3);
        `also`, the facts under other keys the reconcile pass ended with it
        (stage 15 item 7)."""
        await self._ctx.bus.publish(Message.new(topics.MEMORY_FACT_STORED, source=self._ctx.bus.source, payload={
            "id": fact.id, "subject": fact.subject, "predicate": fact.predicate, "object": fact.object,
            "person_scope": fact.person_scope, "valid_from": fact.valid_from, "confidence": fact.confidence,
            "source_refs": list(fact.source_refs)}))
        if superseded_id:
            await self._ctx.bus.publish(Message.new(
                topics.MEMORY_FACT_SUPERSEDED, source=self._ctx.bus.source,
                payload={"id": superseded_id, "valid_to": fact.valid_from, "superseded_by": fact.id}))
        for other_id in also:
            await self._ctx.bus.publish(Message.new(
                topics.MEMORY_FACT_SUPERSEDED, source=self._ctx.bus.source,
                payload={"id": other_id, "valid_to": fact.valid_from, "superseded_by": fact.id}))

    async def _on_retrieve(self, message: Message) -> None:
        payload = message.payload
        person = ""
        for tag in (payload.get("filters") or {}).get("tags") or ():
            if str(tag).startswith("person:"):
                person = str(tag)[len("person:"):]
        facts = []
        pairs = await self.engine.facts_for(payload.get("query", ""), person=person)
        if person:
            # The per-person digest (stage 5 item 4): what holds about the
            # person speaking, whether or not this sentence mentions it.
            # Built from the facts themselves, so it is current by
            # construction -- no sleep job, nothing to regenerate.
            seen = {fact.id for fact, _was in pairs}
            index = await self.engine._facts_synced()  # noqa: SLF001
            for fact in index.live_facts(person=person):
                if fact.id not in seen and fact.person_scope != "*":
                    pairs.append((fact, index.previous(fact)))
                if len(pairs) >= _DIGEST_FACTS:
                    break
        hop_of: dict[str, int] = {}
        via: dict[str, str] = {}
        if self._config.entities and self._config.graph_hops > 0:
            # Stage 15: the facts about whatever the query names, under any
            # of its names ("Soodeh" finds what was said of "Soo"), and one
            # hop further ("whoever fixed the boiler" -> Reza -> his number).
            # After everything above, never instead of it, and each marked
            # with its hop; `graph_hops = 0` leaves the block as it was.
            for fact, was, hop in await self.engine.graph_facts(
                    payload.get("query", ""), person=person, hops=self._config.graph_hops,
                    limit=self._config.graph_max_facts, exclude={fact.id for fact, _was in pairs}, via=via):
                pairs.append((fact, was))
                hop_of[fact.id] = hop
        for fact, was in pairs:
            entry = {"id": fact.id, "subject": fact.subject, "predicate": fact.predicate, "object": fact.object,
                     "person_scope": fact.person_scope, "confidence": fact.confidence,
                     "valid_from": fact.valid_from, "source_refs": list(fact.source_refs)}
            if was is not None:
                # What it replaced, so a reply can say "March 6th (was March
                # 4th)" rather than leaving the old value to resurface.
                entry["was"], entry["was_until"] = was.object, float(was.valid_to or 0.0)
            if fact.id in hop_of:
                entry["hop"] = hop_of[fact.id]
                if via.get(fact.id):
                    entry["via"] = via[fact.id]
            facts.append(entry)
        if self._config.entities and self._config.graph_hops > 0:
            # Stage 15 item 3: one line per entity the query names, from the
            # summary the sleep tick wrote. In the facts block because that
            # is what Orchestration renders; `summary: true` and `entity` say
            # it is not a fact, and the predicate reads as one line there.
            for entity, summary in await self.engine.entity_summaries(payload.get("query", ""), person=person):
                facts.append({"id": f"{entity.id}#summary", "subject": entity.name, "predicate": "in short:",
                              "object": summary, "person_scope": "*", "confidence": 1.0,
                              "summary": True, "entity": entity.id})
        items, truncated = await self.engine.retrieve(
            query=payload.get("query", ""), kinds=payload.get("kinds", []),
            k=payload.get("k", self._config.default_k), filters=payload.get("filters"),
        )
        await self._ctx.bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload={
            "items": [
                # `score` is how well this matched the query; the decayed
                # confidence is reported beside it under a name that says
                # what it is. Until 2026-09-10 `score` WAS the decay, so a
                # no-hit query answered with two identical 1.0000s and
                # nothing downstream could tell relevant from recent.
                {"ref": i.ref, "kind": i.kind, "content": i.content, "tags": list(getattr(i, "tags", ()) or ()),
                 "score": i.score,
                 "confidence_now": i.score_confidence(
                     now=self._ctx.clock.now(), half_life_seconds=self._config.half_life_seconds),
                 "confidence": i.confidence, "ts": i.ts}
                for i in items
            ],
            "truncated": truncated,
            **({"facts": facts} if facts else {}),
            **(await self._core_for(payload)),
        })

    async def _core_for(self, payload: dict) -> dict:
        """`{"core": [...]}` for a recall that asks (`core_for`, the speaker,
        "" the console) while `core_blocks` is on -- the list empty when no
        block is written, which still says the blocks are on, so the turn
        is offered `memory_core_edit`. Nothing at all when off or not asked:
        the reply, and so the prompt, is what it was (stage 15 item 8)."""
        if not self._config.core_blocks or "core_for" not in payload:
            return {}
        blocks = await self.engine.core_blocks(str(payload.get("core_for") or ""))
        return {"core": [{"block": block, "label": label, "text": text} for block, label, text in blocks]}

    async def _on_core_edit(self, message: Message) -> None:
        """`memory.core.edit{block, old?, new?, requester, requester_channel?,
        source_ref?, action_id?}` -> `memory.core.edit.reply{edited, block,
        text, reason}` (`edit_core`'s `ok`/`error` under the reply's names):
        `memory_core_edit`'s edit of one core block. Only
        Execution may publish the request (`topics.PUBLISH_ONLY_BY`), and
        Guardian has already checked the block against the requester
        (`guardian/corememory.py`); `edit_core` checks it again.

        Until 2026-10-27 the edit rode on `memory.retrieve` as an
        undeclared `core_edit` key. Nothing kept those requests -- a
        request is answered and gone, and the `memory:core` events never
        carried the key -- so there is no old shape left to read."""
        edit = message.payload
        if not self._config.core_blocks:
            result = {"ok": False, "block": "", "text": "", "error": "core memory blocks are off ([memory] core_blocks)"}
        else:
            result = await self.engine.edit_core(
                block=str(edit.get("block") or ""), old=str(edit.get("old") or ""), new=str(edit.get("new") or ""),
                requester=str(edit.get("requester") or ""),
                requester_channel=str(edit.get("requester_channel") or ""),
                source_ref=str(edit.get("source_ref") or ""), action_id=str(edit.get("action_id") or ""))
        await self._ctx.bus.reply(message, type=topics.MEMORY_CORE_EDIT_REPLY, payload={
            "edited": bool(result["ok"]), "block": result["block"], "text": result["text"],
            "reason": result["error"]})

    async def _on_store(self, message: Message) -> None:
        payload = message.payload
        if payload["kind"] == "working":
            # working memory is a session-scoped rolling window, not a
            # durable item -- `content` is treated as the response half
            # of a turn; a bare store with no paired request is still
            # recorded (empty request) so nothing is silently dropped.
            session_id = (payload.get("tags") or [None])[0] or "default"
            self.engine.working.add(session_id, "", payload["content"], ts=self._ctx.clock.now())
            return
        ref = await self.engine.store(
            kind=payload["kind"], content=payload["content"], tags=payload.get("tags", []),
            source_ref=payload.get("source_ref", ""), confidence=payload.get("confidence"),
        )
        await self._ctx.bus.publish(Message.new(
            topics.MEMORY_STORED, source=self._ctx.source, payload={"ref": ref, "kind": payload["kind"]},
        ))

    async def _on_turn_completed(self, message: Message) -> None:
        """Flow 1's own episodic-write arrow (02 section 5), closing the
        gap milestone 104 left open: `turn.completed` didn't carry the
        human's own words until that same milestone added `user_text`
        (optional, so an older producer still validates) -- with nothing
        said this turn there is nothing worth remembering, so an empty
        pair is skipped rather than filling episodic memory with blanks
        from the honest-floor path (`floor: true`, `text: ""`)."""
        payload = message.payload
        user_text = payload.get("user_text", "")
        reply_text = payload.get("text", "")
        if not user_text and not reply_text:
            return
        if payload.get("cancelled"):
            return   # the person moved on before an answer; nothing was said
        from simorgh.contracts.settings import is_quiet_reply

        if is_quiet_reply(reply_text):
            # Sim heard words that were not for it and stayed silent. Silence
            # is not a conversation to remember: 446 of 2,422 episodic
            # records were these, a work meeting among them (2026-09-16).
            return
        if str(payload.get("kind") or "chat") != "chat":
            # A task's own model session ends with turn.completed too; its
            # description is not something a person said (the creator's
            # memory, 2026-09-13, held "User: add five funny Unicode
            # cartoon splash screens ..." as a conversation).
            return
        from simorgh.contracts.tone import strip_tone

        speaker = str(payload.get("speaker") or "").strip()
        reply_text = strip_tone(reply_text)
        who = speaker or "User"
        from simorgh.contracts.settings import conversation_key

        # The conversation window: what was just said, per (channel,
        # person). `WorkingMemory` had both halves built and no producer
        # since 2026-09-08; Orchestration renders it before the memory
        # block, so "what did I just say" no longer depends on a
        # similarity search (2026-09-18 evaluation, C8).
        self.engine.working.add(
            conversation_key(payload.get("channel"), speaker),
            f"{who}: {user_text}" if user_text else "", f"Sim: {reply_text}" if reply_text else "",
            ts=self._ctx.clock.now(),
        )
        # A turn two people spoke arrives already as "Saeed: ... / Soodeh: ..."
        # (voice/diarize.py); a prefix on top of that named one of them twice.
        # (voice/diarize.py writes `someone:` for a voice nobody matched, so
        # the first letter may be lower case.)
        named = [ln for ln in (user_text or "").splitlines() if _re.match(r"^[A-Za-z][\w' -]{0,30}: ", ln)]
        named_lines = len(named) >= 2 and len(named) == len([ln for ln in user_text.splitlines() if ln.strip()])
        content = (f"{user_text}\nSim: {reply_text}" if named_lines else f"{who}: {user_text}\nSim: {reply_text}") \
            if user_text else (f"Sim: {reply_text}" if reply_text else "")
        voices = [speaker] if speaker else []
        if named_lines:
            # Every named voice in the turn can find it again under their own name.
            for line in user_text.splitlines():
                m = _re.match(r"^([A-Za-z][\w' -]{0,30}): ", line)
                if m and m.group(1) not in ("someone", "User", "Sim") and m.group(1) not in voices:
                    voices.append(m.group(1))
        # The person's name is a tag as well as a label, so a recall can
        # ask for "what I remember with Ira" (orchestration/context.py).
        tags = [payload.get("session_id", "")] + [f"person:{name}" for name in voices]
        if not voices and str(payload.get("channel") or "") == "voice":
            # A voice nobody placed is somebody, not everybody. Untagged, the
            # turn read as a typed one -- shared -- and recall handed it to
            # the next named speaker: a stranger's "I can't start music for
            # a voice I don't have enrolled" came back on Saeed's own "play
            # music", and he got the same refusal, twice (2026-09-27).
            tags.append(UNPLACED_VOICE_TAG)
        ref = await self.engine.store(kind="episodic", content=content, tags=tags,
                                      source_ref=payload.get("task_id", ""), confidence=None)
        await self._ctx.bus.publish(Message.new(
            topics.MEMORY_STORED, source=self._ctx.source, payload={"ref": ref, "kind": "episodic"},
        ))

    async def _on_tick(self, message: Message) -> None:
        # A dashboard's "what does Sim remember" view (02-system-
        # architecture.md section 6.2), on the same `system.metrics`
        # channel every other subsystem's own gauges already use --
        # every 30s, matching Cognition's own tick throttle, not every
        # second tick (a stream read per kind is cheap but not free).
        self._tick_seconds += 1
        every = int(self._config.people_refresh_s or 0)
        if self._config.entities and every > 0 and self._tick_seconds % every == 0:
            self._learn_people_soon()
        if self._tick_seconds % 30 != 0:
            return
        counts = await self.engine.counts()
        await self._ctx.bus.publish(Message.new(
            topics.SYSTEM_METRICS, source=self._ctx.source,
            payload={"subsystem": "memory", "counters": {}, "gauges": {"records": counts}},
        ))

    def _learn_people_soon(self) -> None:
        """Ask who the people are, in the background; one ask at a time."""
        if self._people_task is not None and not self._people_task.done():
            return
        self._people_task = asyncio.create_task(self.learn_people(), name="memory-learn-people")

    async def learn_people(self) -> bool:
        """Who the people are, from World Model's People store, for entity
        resolution (stage 15): their names, voices and `relations`.

        Over the bus, because Memory may not import the subsystem that
        keeps the store. Whatever goes wrong -- no World Model, a timeout,
        an error reply, an empty list -- the records Memory already has
        stay: forgetting the family because one ask failed would turn
        "my son" back into nobody. True when the records were replaced."""
        from simorgh.contracts.people import from_dict

        try:
            reply = await self._ctx.bus.request(Message.new(
                topics.WORLD_ENV_QUERY, source=self._ctx.source, payload={"what": "people", "args": {}}),
                timeout=_PEOPLE_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- see above: keep what we had
            return False
        body = (reply.payload if reply is not None else None) or {}
        rows = body.get("people") if body.get("ok") is not False else None
        people = tuple(p for p in (from_dict(r) for r in (rows or ()) if isinstance(r, dict)) if p.name)
        if not people:
            return False
        self.engine.people = people
        return True

    async def _on_sleep(self, message: Message) -> None:
        await self._consolidate(window=message.payload.get("window_seconds"))

    async def _consolidate(self, *, window: float | None) -> None:
        since = self._ctx.clock.now() - window if window else None
        report = await run_consolidation(
            self.engine, bus=self._ctx.bus, source=self._ctx.source, keep_per_kind=self._keep_per_kind, since=since,
            cognition_timeout=self._config.consolidate_timeout_s,
        )
        for ref_a, ref_b, evidence in report.contradictions:
            await self._ctx.bus.publish(Message.new(
                topics.MEMORY_CONTRADICTION_FLAGGED, source=self._ctx.source,
                payload={"ref_a": ref_a, "ref_b": ref_b, "evidence": evidence, "confidence_after": 0.5},
            ))
        if report.refused:
            # A refusal that tells nobody is the bare `except` this
            # codebase keeps being bitten by. The distillation that was
            # thrown away named things the transcript never did, and
            # that is worth a line: it is the difference between "the
            # model had nothing to say" and "the model invented".
            self._ctx.logger.warning("memory.distillation_refused",
                                     invented=", ".join(report.refused[:10]), count=len(report.refused))
        from .consolidation import SummaryReport

        summaries = getattr(report, "summaries", None)
        if isinstance(summaries, SummaryReport) and (summaries.written or summaries.skipped or summaries.refused):
            # Skipped is not failed: no real provider answered, so nothing
            # was written and the next pass asks again.
            self._ctx.logger.info("memory.entity_summaries", written=len(summaries.written),
                                  skipped=summaries.skipped, refused=len(summaries.refused))
            for entity_id, invented in summaries.refused.items():
                self._ctx.logger.warning("memory.entity_summary_refused", entity=entity_id,
                                         invented=", ".join(invented[:10]))
        await self._ctx.bus.publish(Message.new(
            topics.MEMORY_CONSOLIDATED, source=self._ctx.source,
            payload={"window": window or 0.0, "distilled": 1 if report.distilled else 0,
                     "pruned": sum(report.pruned.values()), "refused": len(report.refused)},
        ))
        pruned_total = sum(report.pruned.values())
        if pruned_total:
            await self._ctx.bus.publish(Message.new(
                topics.MEMORY_FORGOTTEN, source=self._ctx.source,
                payload={"refs": [], "reason": f"consolidation pruned {pruned_total} record(s) across {len(report.pruned)} kind(s)"},
            ))


__all__ = ["Service", "UNPLACED_VOICE_TAG", "VERSION"]
