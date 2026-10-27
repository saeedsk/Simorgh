"""The two native systems: Sim's own Memory, with and without the entity layer.

Each is a real `memory.Service` on a real in-memory Ledger and Bus -- the
shape `tests/simorgh/memory/test_service.py` uses -- with the hashing
embedder and a clock that walks through the simulated month. No Kernel,
no model, no network: the whole suite is a few seconds.

Episodes go in as episodic records tagged `person:<speaker>`, and their
facts through `store_fact`, at the episode's own time, so supersession
happens in the order things were said. Questions go out the way
Orchestration asks (`orchestration/context.py`): one `memory.retrieve`
for the query and one carrying the asker's `person:` tag, and the facts
block is the union of both replies' `facts`.

`native_graph` is the same with `[memory] entities = true` and
`graph_hops = 2` (stage 15 items 1-3). Until those keys exist on
`memory.config.Config` it reports every case skipped and says why, so this
suite can merge before the memory branch does.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from .corpus import ASKED_AT, MONTH_START, Episode, Question
from .score import PAST

#: The `[memory]` keys `native_graph` needs; named by the stage 15 plan.
GRAPH_KEYS: dict[str, object] = {"entities": True, "graph_hops": 2}

#: What Orchestration asks for in a chat turn (`context.py`): k=8 matched.
_K = 8


class MonthClock:
    """A clock the suite sets: `now()` is wherever the month has got to."""

    def __init__(self, start: float = MONTH_START) -> None:
        self.t = float(start)

    def now(self) -> float:
        return self.t

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        # Real time: a background loop that sleeps must not spin.
        await asyncio.sleep(seconds)


class _Quiet:
    def debug(self, event, **fields): pass
    def info(self, event, **fields): pass
    def warning(self, event, **fields): pass
    def error(self, event, **fields): pass


def graph_skip_reason() -> str:
    """Why `native_graph` cannot run here, or "" when it can."""
    from simorgh.memory.config import Config

    missing = [key for key in GRAPH_KEYS if key not in Config.__dataclass_fields__]
    if missing:
        return (f"[memory] {', '.join(missing)} not recognised by simorgh.memory.config.Config "
                "(stage 15 items 1-3 are not merged into this checkout)")
    return ""


class Native:
    """Sim's Memory, booted on its own."""

    name = "native"
    #: Extra `[memory]` keys; `NativeGraph` sets the entity layer's.
    extra: dict[str, object] = {}

    def __init__(self) -> None:
        self._tmp: tempfile.TemporaryDirectory | None = None

    def skip_reason(self) -> str:
        return ""

    async def open(self) -> None:
        from simorgh.bus.config import Config as BusConfig
        from simorgh.bus.factory import make_backend, make_client
        from simorgh.contracts.protocols import Context
        from simorgh.ledger.factory import make_ledger
        from simorgh.memory.config import Config as MemoryConfig
        from simorgh.memory.service import Service

        self._tmp = tempfile.TemporaryDirectory(prefix="simorgh-memory-eval-")
        self.clock = MonthClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="memory", ledger=self.ledger, clock=self.clock)
        await self.bus.start()
        ctx = Context(name="memory", instance_id="", run_id="memory-eval", mode="single", bus=self.bus,
                      ledger=self.ledger, config={}, secrets={}, clock=self.clock, logger=_Quiet(),
                      data_dir=Path(self._tmp.name) / "data")
        # Hashing, not auto: free, offline, and the same on every machine.
        # A month-long half-life, so decay does not decide what is recalled.
        config = MemoryConfig(embedder="hashing", consolidate_after_start_s=0.0,
                              half_life_seconds=365 * 86_400.0, **self.extra)
        self.service = Service(config=config)
        await self.service.start(ctx)

    async def close(self) -> None:
        try:
            await self.service.stop()
            await self.bus.stop()
        finally:
            if self._tmp is not None:
                self._tmp.cleanup()

    async def ingest(self, episode: Episode) -> None:
        self.clock.t = episode.ts
        engine = self.service.engine
        ref = await engine.store(kind="episodic", content=f"{episode.speaker.title()}: {episode.text}",
                                 tags=[f"person:{episode.speaker}"], source_ref="", confidence=None)
        for fact in episode.facts:
            await engine.store_fact(subject=fact.subject, predicate=fact.predicate, object=fact.object,
                                    person_scope=fact.scope, source_refs=[ref])

    async def context(self, question: Question) -> list[str]:
        from simorgh.contracts import topics
        from simorgh.contracts.envelope import Message

        self.clock.t = max(self.clock.t, ASKED_AT)
        kinds = ["episodic", "semantic"]
        asks = [{"query": question.text, "kinds": kinds, "k": _K},
                {"query": question.text, "kinds": kinds, "k": _K,
                 "filters": {"tags": [f"person:{question.asker}"]}}]
        facts: list[dict] = []
        seen: set[str] = set()
        for payload in asks:
            reply = await self.bus.request(
                Message.new(topics.MEMORY_RETRIEVE, source="memory", payload=payload), timeout=10.0)
            for fact in reply.payload.get("facts") or []:
                if fact.get("id") not in seen:
                    seen.add(fact.get("id"))
                    facts.append(fact)
        return block_lines(facts)


class NativeGraph(Native):
    """The same Memory with the entity layer on (stage 15 items 1-3)."""

    name = "native_graph"
    extra = dict(GRAPH_KEYS)

    def skip_reason(self) -> str:
        return graph_skip_reason()


def block_lines(facts: list[dict]) -> list[str]:
    """`memory.retrieve.reply.facts` as lines, one fact a line.

    The current value on its own line; what it replaced on a `PAST` line,
    so "what was it before" can find it and "what is it now" cannot take it
    for the answer. A `hop` (stage 15 item 2) is kept as a marker.
    """
    lines: list[str] = []
    for fact in facts:
        text = " ".join(str(fact.get(part) or "") for part in ("subject", "predicate", "object")).strip()
        if not text:
            continue
        scope = str(fact.get("person_scope") or "*")
        prefix = "" if scope == "*" else f"{scope}: "
        hop = f" [hop {fact['hop']}]" if fact.get("hop") else ""
        lines.append(f"{prefix}{text}{hop}")
        if fact.get("was"):
            lines.append(f"{PAST}{prefix}{fact.get('subject', '')} {fact.get('predicate', '')} {fact['was']}")
    return lines


__all__ = ["GRAPH_KEYS", "MonthClock", "Native", "NativeGraph", "block_lines", "graph_skip_reason"]
