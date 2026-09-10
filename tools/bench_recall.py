"""Recall scaling benchmark. Same shape as the wave-3 measurement:
N records per kind in a real jsonl ledger, then time MemoryEngine.retrieve.

  python bench_recall.py [--counts 1000,2000,6000,10000] [--label before]
"""
from __future__ import annotations

import argparse, asyncio, json, random, statistics, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simorgh.ledger.factory import make_ledger
from simorgh.ledger.config import Config as LedgerConfig
from simorgh.memory.config import Config
from simorgh.memory.store import MemoryEngine, stream_for
from simorgh.contracts.envelope import Event

WORDS = ("deploy ledger kernel guardian curiosity reflection persona embedding vector prune "
         "tombstone consolidation session skill patch commit branch timeout budget observer "
         "recall memory episodic semantic procedural sandbox trial wave scoring latency").split()


class RealClock:
    def now(self) -> float:
        return time.time()


async def seed(ledger, n: int, kinds=("episodic", "semantic")) -> None:
    rng = random.Random(7)
    now = time.time()
    for kind in kinds:
        stream = stream_for(kind)
        for i in range(n):
            body = " ".join(rng.choice(WORDS) for _ in range(30))
            await ledger.append(stream, Event(
                stream=stream, type="item.stored", ts=now - (n - i) * 60.0,
                trace_id="", causation_id=None, idempotency_key=f"{stream}:{i}",
                payload={"tags": [f"s{i % 17}"], "source_ref": "", "confidence": 1.0,
                         "content": f"record {i}: {body}"},
            ))


async def timed(engine, query, kinds, k=8, repeats=5):
    times = []
    tops = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        items, _ = await engine.retrieve(query=query, kinds=kinds, k=k, filters=None)
        times.append((time.perf_counter() - t0) * 1000.0)
        tops.append([i.ref for i in items])
    return times, tops


class Burner:
    """A competing CPU-bound coroutine, so 'under load' means something
    specific: one asyncio task doing work in 5 ms slices, yielding between."""
    def __init__(self):
        self.stop = False

    async def run(self):
        while not self.stop:
            end = time.perf_counter() + 0.005
            x = 0
            while time.perf_counter() < end:
                x += 1
            await asyncio.sleep(0)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--counts", default="1000,2000,6000,10000")
    ap.add_argument("--label", default="run")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    rows = []
    for n in [int(c) for c in args.counts.split(",")]:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = make_ledger(LedgerConfig(backend="jsonl", data_dir=tmp, fsync=False))
            await ledger.start()
            await seed(ledger, n)
            engine = MemoryEngine(ledger, Config(), clock=RealClock())
            q = "how do I prune the ledger after a failed deploy"
            # idle
            t_idle, tops = await timed(engine, q, ["episodic", "semantic"])
            # under load
            burner = Burner()
            task = asyncio.create_task(burner.run())
            t_load, _ = await timed(engine, q, ["episodic", "semantic"])
            burner.stop = True
            await task
            # cold engine, first call only (cache-empty path)
            engine2 = MemoryEngine(ledger, Config(), clock=RealClock())
            t_cold, tops2 = await timed(engine2, q, ["episodic", "semantic"], repeats=2)
            rows.append({
                "n": n,
                "idle_first_ms": round(t_idle[0], 1),
                "idle_warm_ms": round(statistics.median(t_idle[1:]), 1),
                "load_ms": round(statistics.median(t_load), 1),
                "cold_first_ms": round(t_cold[0], 1),
                "cold_second_ms": round(t_cold[1], 1),
                "top": tops[0][:3],
            })
            print(json.dumps(rows[-1]), flush=True)
            await ledger.stop()
    if args.out:
        Path(args.out).write_text(json.dumps({"label": args.label, "rows": rows}, indent=2))


asyncio.run(main())
