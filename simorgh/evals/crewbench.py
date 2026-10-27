"""`crew-bench`: what a crew costs Sim itself, with no model (stage 18 item 6).

The crew scenarios (`house/scenarios/toolchain.py`, `toolchain/crew/`)
need a real model and real money. This does not: it boots Orchestration's
real `SessionRunner` on the real in-memory Bus and Ledger, with a fake
Cognition that answers every think after a fixed delay and a fake
Guardian+Execution that approves and "runs" every proposal at once -- the
shape `tests/simorgh/orchestration/test_crews.py` uses -- and measures the
four numbers the plan asks for:

- **message latency**: `Crew.send` -> the recipient awake in
  `Crew.wait_until`, through the same two writes `session._crew_record`
  makes (the `crew:<id>` ledger append and the bus publish). The plan's
  target is under 50 ms.
- **spawn overhead**: `crew.spawned` -> that member's first
  `cognition.think`. Everything between a parent deciding to start a
  member and the member starting to work: carving, the slot, context
  assembly, the request.
- **fan-out speedup**: N members (`spawn` x N, `await_agents all`)
  against the same N jobs done one after another (`delegate` x N), with
  every think taking `delay_s`. Item 2's acceptance was under 0.6 x
  serial for three.
- **memory per member**: traced Python allocation at the peak of a run
  with `crew_max_members` members, less a run with one, per extra member
  (`tracemalloc`; Python objects only, so it is a floor, not the RSS).

Free and offline. Each run appends one JSON row to `DEFAULT_LOG`, so the
numbers are recorded rather than scrolled past (the item's acceptance:
"runs free and records its numbers").
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
import tracemalloc
import uuid
from dataclasses import replace
from pathlib import Path

#: Where each run's numbers go: beside the ablation's log, gitignored.
DEFAULT_LOG = Path(__file__).resolve().parents[2] / ".simorgh_evals" / "crew-bench.jsonl"
#: The plan's message-latency target (stage 18, "Inbox delivery").
MESSAGE_TARGET_MS = 50.0


class _Quiet:
    def debug(self, event, **fields): pass
    def info(self, event, **fields): pass
    def warning(self, event, **fields): pass
    def error(self, event, **fields): pass


class _Clock:
    """Wall time, in the shape the bus and the ledger take (`now()` and
    callable)."""

    def now(self) -> float:
        return time.time()

    def __call__(self) -> float:
        return time.time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class _House:
    """One in-memory Bus backend and Ledger, a client per subsystem --
    how the Kernel wires them, minus everything that is not a crew."""

    def __init__(self) -> None:
        from simorgh.bus.config import Config as BusConfig
        from simorgh.bus.factory import make_backend
        from simorgh.ledger.factory import make_ledger

        self.clock = _Clock()
        self._config = BusConfig(backend="memory", max_deliveries=3, metrics_interval_seconds=0)
        self.backend = make_backend(self._config, clock=self.clock)
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        self._clients: dict = {}
        self._subs: list = []
        #: (topic, monotonic time, payload) for crew and think traffic.
        self.seen: list[tuple[str, float, dict, str]] = []

    async def start(self) -> "_House":
        await self.ledger.start()
        return self

    def client(self, source: str):
        from simorgh.bus.factory import make_client

        if source not in self._clients:
            self._clients[source] = make_client(self.backend, source=source, config=self._config,
                                                ledger=self.ledger, clock=self.clock)
        return self._clients[source]

    async def stop(self) -> None:
        import contextlib

        for sub in self._subs:
            with contextlib.suppress(Exception):
                await sub.unsubscribe()
        # Each client runs a trace writer; left running, every run ends
        # in "Task was destroyed but it is pending!".
        for client in self._clients.values():
            with contextlib.suppress(Exception):
                await client.stop()
        with contextlib.suppress(Exception):
            await self.backend.stop()


async def _fakes(house: _House, scripts: dict, delay_s: dict) -> None:
    """Cognition, Guardian+Execution and Memory, each a real subscriber
    speaking the real message shapes."""
    from simorgh.contracts import topics

    cognition, guardian, memory = house.client("cognition"), house.client("guardian"), house.client("memory")
    calls: dict[str, int] = {}

    def pick(table: dict, task_id: str, default):
        return table.get(task_id, table.get("*", default))

    async def think(message) -> None:
        task_id = message.trace_id
        house.seen.append((topics.COGNITION_THINK, time.monotonic(), {}, task_id))
        calls[task_id] = calls.get(task_id, 0) + 1
        delay = float(pick(delay_s, task_id, 0.0))
        if delay:
            await asyncio.sleep(delay)
        script = pick(scripts, task_id, [{"text": "done\n- nothing to add"}])
        step = script[min(calls[task_id] - 1, len(script) - 1)]
        await cognition.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
            "text": step.get("text", ""), "tool_calls": step.get("tool_calls", []), "provider": "fake",
            "cost_usd": 0.0, "tokens": 10, "floor": False, "non_answer": False})

    async def act(message) -> None:
        await guardian.publish(message.caused(topics.ACTION_RESULT, {
            "action_id": message.payload["action_id"], "ok": True, "output_ref": "",
            "stdout_preview": f"ran {message.payload['tool']}", "duration_ms": 1, "side_effects": [],
        }, source="execution"))

    async def recall(message) -> None:
        await memory.reply(message, type=topics.MEMORY_RETRIEVE_REPLY,
                           payload={"items": [], "facts": [], "truncated": False})

    async def crew(message) -> None:
        house.seen.append((message.type, time.monotonic(), dict(message.payload or {}), ""))

    for client, topic, handler in ((cognition, topics.COGNITION_THINK, think),
                                   (guardian, topics.ACTION_PROPOSED, act),
                                   (memory, topics.MEMORY_RETRIEVE, recall),
                                   (memory, topics.CREW_SPAWNED, crew)):
        house._subs.append(await client.subscribe(topic, handler))  # noqa: SLF001


def _root(task_id: str, max_steps: int = 12):
    from simorgh.orchestration import profiles
    from simorgh.orchestration.api import Budget, Session

    return Session(task_id=task_id, kind="research", mode="execute", user_text="the crew bench",
                   profile=replace(profiles.RESEARCH, verify=False, max_steps=max_steps),
                   budget=Budget(max_steps=max_steps))


#: A member's work: one tool call, then its typed answer.
_MEMBER = [{"tool_calls": [{"tool": "read_file", "args": {"path": "notes.md"}}]},
           {"text": "It costs 500.\n- notes.md says 500"}]


def _call(i: int, tool: str, **args) -> dict:
    return {"id": f"c{i}", "tool": tool, "args": args}


async def _one_run(parent_script: list, *, delay_s: float, crew_max_members: int = 8) -> tuple[float, _House, str]:
    """One root session over a fresh house; (wall seconds, house, root id)."""
    from simorgh.orchestration.session import SessionRunner

    house = await _House().start()
    root_id = f"bench-{uuid.uuid4().hex[:8]}"
    await _fakes(house, {root_id: parent_script, "*": _MEMBER}, {root_id: 0.0, "*": delay_s})
    runner = SessionRunner(house.client("orchestration"), house.ledger, clock=house.clock.now,
                           assemble_timeout_s=0.05, delegation=True, think_timeout_s=30.0,
                           crew_max_members=crew_max_members, max_children=crew_max_members)
    root = _root(root_id)
    started = time.monotonic()
    outcome = await asyncio.wait_for(runner.run(root, user_text=root.user_text), timeout=120)
    wall = time.monotonic() - started
    await house.stop()
    if outcome.kind != "completed":
        raise RuntimeError(f"the bench's root session ended {outcome.kind}: {outcome.reason}")
    return wall, house, root_id


def _spawning(n: int) -> list:
    return [{"tool_calls": [_call(i, "spawn", brief=f"price of item {i}") for i in range(n)]},
            {"tool_calls": [_call(99, "await_agents", mode="all", timeout_s=60)]},
            {"text": "All of them cost 500."}]


def _delegating(n: int) -> list:
    return [{"tool_calls": [_call(i, "delegate", job=f"price of item {i}") for i in range(n)]},
            {"text": "All of them cost 500."}]


async def fan_out(members: int, delay_s: float) -> dict:
    crew_wall, _, _ = await _one_run(_spawning(members), delay_s=delay_s)
    serial_wall, _, _ = await _one_run(_delegating(members), delay_s=delay_s)
    return {"members": members, "think_delay_s": delay_s, "crew_s": round(crew_wall, 3),
            "serial_s": round(serial_wall, 3), "ratio": round(crew_wall / serial_wall, 3) if serial_wall else None,
            "speedup": round(serial_wall / crew_wall, 2) if crew_wall else None}


async def spawn_overhead(members: int) -> dict:
    """`crew.spawned` -> the member's first think, with thinks that cost
    nothing, so what is left is the crew's own machinery."""
    from simorgh.contracts import topics

    _, house, _ = await _one_run(_spawning(members), delay_s=0.0)
    spawned = {p["handle"]: at for topic, at, p, _ in house.seen if topic == topics.CREW_SPAWNED}
    first: dict[str, float] = {}
    for topic, at, _, task in house.seen:
        if topic == topics.COGNITION_THINK and task in spawned and task not in first:
            first[task] = at
    gaps = [1000.0 * (first[h] - spawned[h]) for h in spawned if h in first]
    return {"members": len(gaps), **_percentiles(gaps)}


async def message_latency(messages: int) -> dict:
    """`Crew.send` -> the recipient awake, `messages` times, each through
    a ledger append and a bus publish as `session._crew_record` does."""
    from simorgh.contracts.envelope import Event, Message
    from simorgh.contracts.messages.crew import MemberBudget
    from simorgh.contracts.streamnames import crew_stream
    from simorgh.orchestration.crew import Crew

    house = await _House().start()
    bus = house.client("orchestration")
    crew_id = "bench-crew"
    stream = crew_stream(crew_id)

    async def append(type_: str, payload: dict) -> None:
        msg = Message.new(type_, source=bus.source, payload=payload, partition_key=stream,
                          trace_id=crew_id, clock=house.clock)
        await house.ledger.append(stream, Event.from_message(msg, stream))
        await bus.publish(msg)

    crew = Crew(crew_id, append=append, max_usd=0.0, max_wall_s=0.0)
    member = await crew.admit(parent=crew_id, agent="research", brief="listen", depth=1, budget=MemberBudget(steps=5))
    inbox = crew.inboxes[member.handle]
    gaps = []
    for i in range(messages):
        woke = asyncio.get_running_loop().create_future()

        async def recipient() -> None:
            await crew.wait_until(lambda: len(inbox) > 0, timeout_s=5.0)
            woke.set_result(time.monotonic())

        waiting = asyncio.create_task(recipient())
        await asyncio.sleep(0)  # the recipient is suspended before the send
        sent = time.monotonic()
        await crew.send(crew_id, member.handle, "steer", f"message {i}")
        gaps.append(1000.0 * (await woke - sent))
        await waiting
        inbox.drain()
    await house.stop()
    out = {"messages": len(gaps), **_percentiles(gaps)}
    out["under_target"] = out["p95_ms"] is not None and out["p95_ms"] < MESSAGE_TARGET_MS
    return out


async def memory_per_member(members: int) -> dict:
    """Peak traced allocation of a crew of `members` less a crew of one,
    per extra member."""
    async def peak(n: int) -> int:
        tracemalloc.start()
        try:
            await _one_run(_spawning(n), delay_s=0.0)
            return tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

    one, many = await peak(1), await peak(members)
    extra = max(1, members - 1)
    return {"members": members, "peak_one_kib": round(one / 1024, 1), "peak_many_kib": round(many / 1024, 1),
            "per_member_kib": round(max(0, many - one) / extra / 1024, 1)}


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {"p50_ms": None, "p95_ms": None, "max_ms": None}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return {"p50_ms": round(statistics.median(ordered), 3), "p95_ms": round(p95, 3), "max_ms": round(ordered[-1], 3)}


async def run(*, members: int = 3, delay_s: float = 0.15, messages: int = 200, crew_size: int = 8) -> dict:
    """Every measurement once; the row `main` records."""
    started = time.monotonic()
    row = {
        "ts": round(time.time(), 3),
        "message_latency": await message_latency(messages),
        "spawn_overhead": await spawn_overhead(members),
        "fan_out": await fan_out(members, delay_s),
        "memory": await memory_per_member(crew_size),
    }
    row["seconds"] = round(time.monotonic() - started, 2)
    return row


def table(row: dict) -> str:
    m, s, f, mem = row["message_latency"], row["spawn_overhead"], row["fan_out"], row["memory"]
    target = "under" if m.get("under_target") else "OVER"
    return "\n".join([
        f"message latency   p50 {m['p50_ms']} ms  p95 {m['p95_ms']} ms  max {m['max_ms']} ms "
        f"over {m['messages']} messages ({target} the {MESSAGE_TARGET_MS:.0f} ms target)",
        f"spawn overhead    p50 {s['p50_ms']} ms  p95 {s['p95_ms']} ms  over {s['members']} members "
        "(crew.spawned -> the member's first think)",
        f"fan-out           {f['members']} members {f['crew_s']} s against {f['serial_s']} s serial "
        f"(x{f['ratio']} of serial, {f['speedup']}x faster; each think {f['think_delay_s']} s)",
        f"memory            {mem['per_member_kib']} KiB per member "
        f"(traced peak {mem['peak_many_kib']} KiB for {mem['members']}, {mem['peak_one_kib']} KiB for one)",
        f"took {row['seconds']} s; no model was called",
    ])


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m simorgh.evals crew-bench",
                                     description="Crew micro-benchmark with fake providers (free).")
    parser.add_argument("--members", type=int, default=3, help="members for fan-out and spawn overhead")
    parser.add_argument("--delay", type=float, default=0.15, help="seconds each fake think takes in fan-out")
    parser.add_argument("--messages", type=int, default=200, help="messages for the latency measurement")
    parser.add_argument("--crew-size", type=int, default=8, help="members for the memory measurement")
    parser.add_argument("--json", action="store_true", help="print the row instead of the table")
    parser.add_argument("--log", default=str(DEFAULT_LOG), help="JSONL to append the row to ('' for none)")
    args = parser.parse_args(argv)
    if min(args.members, args.messages, args.crew_size) < 1 or args.delay < 0:
        parser.error("--members, --messages and --crew-size must be at least 1, --delay not negative")
    row = asyncio.run(run(members=args.members, delay_s=args.delay, messages=args.messages,
                          crew_size=args.crew_size))
    if args.log:
        path = Path(args.log)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    print(json.dumps(row, indent=2) if args.json else table(row))
    return 0


__all__ = ["DEFAULT_LOG", "MESSAGE_TARGET_MS", "fan_out", "main", "memory_per_member", "message_latency",
           "run", "spawn_overhead", "table"]
