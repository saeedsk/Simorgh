#!/usr/bin/env python3
"""recall_scenario: does the model get to SEE what the family told Sim?

Boots the real system in a temporary data directory (every subsystem,
the same composition the boot test proves healthy), types a scripted
household conversation into the CLI exactly as a person would, and for
each probe turn inspects the `cognition.think` request Orchestration puts
on the bus -- which is the context the model would reason over. No model
is called: Cognition answers from its floor. What is measured is context
assembly, which is where the live failures were.

The script is built from two failures in the ledger (orchestration/
context.py documents both):

- the machine names: told once at turn 1, asked about at turn 14 and 19
  in different words ("which of my computers...") -- the fact never
  reached the prompt;
- the birthday correction: March 4th, then corrected to March 6th, then
  asked about -- the superseded value came back more often than the
  correction.

    python tools/recall_scenario.py            # table on stdout
    python tools/recall_scenario.py --json     # machine-readable, for docs/findings
    python tools/recall_scenario.py --verbose  # also print each probe's context

A probe scores: `seen` (every expected fact appears somewhere in the
context), `where` (working window, memory block, or both), and for a
correction `order_ok` (the correction appears after what it corrects, or
the old value is absent). Stage 5 (memory tiers) is what should move
these numbers; record them in docs/findings before and after.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

FILLER = [
    "What is a good way to store basil so it lasts longer?",
    "Can you explain how compound interest works in one paragraph?",
    "What's the difference between a latte and a flat white?",
    "Give me three ideas for a rainy Sunday with kids.",
    "How long should I boil an egg for a runny yolk?",
    "What does a heat pump actually do in winter?",
    "Suggest a short stretching routine for after a run.",
    "Why is the sky blue, simply put?",
    "What's a polite way to decline a meeting invite?",
    "How do I get candle wax out of a tablecloth?",
    "What are the rules of pétanque?",
    "Recommend a board game for four players under an hour.",
]

# (turn text, probe) -- a probe is (name, expected substrings, superseded substrings or None)
SCRIPT: list[tuple[str, tuple | None]] = [
    ("I have one mini PC called falcon and a Raspberry Pi 4 called sparrow. Please remember those two names, "
     "I'll use them constantly.", None),
    *[(f, None) for f in FILLER[:6]],
    ("My birthday is March 4th.", None),
    *[(f, None) for f in FILLER[6:8]],
    ("Sorry, I got that wrong earlier: my birthday is actually March 6th.", None),
    *[(f, None) for f in FILLER[8:10]],
    ("Which of my computers should run the nightly backups?", ("machines@14", ("falcon", "sparrow"), None)),
    ("What date should we put the party on, the day of my birthday?", ("birthday@15", ("March 6th",), ("March 4th",))),
    *[(f, None) for f in FILLER[10:12]],
    ("Remind me what I named the little Pi?", ("machines@18", ("sparrow",), None)),
]


def _context_text(payload: dict) -> tuple[str, str, str]:
    """(everything, the conversation-window block, the memory block)."""
    messages = payload.get("messages") or []
    whole, working, memory = [], "", ""
    for m in messages:
        content = str(m.get("content", ""))
        whole.append(content)
        if content.startswith("The conversation so far with this person"):
            working = content
        elif content.startswith("Relevant memory"):
            memory = content
    return "\n".join(whole), working, memory


async def run(verbose: bool = False) -> dict:
    from simorgh.contracts import topics
    from simorgh.kernel.config import LoadedConfig
    from simorgh.kernel.secrets import EnvSecretStore
    from simorgh.kernel.service import Kernel

    tmp = tempfile.TemporaryDirectory(prefix="simorgh-recall-")
    # Floor only. Without this the Claude Code CLI failover answers
    # whenever the `claude` binary is on PATH -- a real, billed model
    # call per turn, and a slower, noisier measurement.
    config = {"runtime": {"data_dir": tmp.name}, "cognition": {"provider_order": ["floor"]}}
    kernel = Kernel(LoadedConfig(config, None), secrets=EnvSecretStore({}))
    await kernel.boot()
    interface = kernel._supervisor.services["interface"].service  # noqa: SLF001
    printed: list[str] = []
    interface._out = printed.append  # noqa: SLF001
    thinks: list[dict] = []

    async def _see(message) -> None:
        thinks.append(message.payload)

    sub = await kernel.bus.subscribe(topics.COGNITION_THINK, _see)
    completed: list[dict] = []

    async def _done(message) -> None:
        completed.append(message.payload)

    sub2 = await kernel.bus.subscribe(topics.TURN_COMPLETED, _done)
    results = []
    started = time.monotonic()
    try:
        for index, (text, probe) in enumerate(SCRIPT):
            before_thinks, before_done = len(thinks), len(completed)
            await interface._handle_line(text)  # noqa: SLF001
            deadline = time.monotonic() + 20
            while len(completed) <= before_done and time.monotonic() < deadline:
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.05)  # Memory's turn.completed handler runs concurrently
            if probe is None:
                continue
            name, expected, superseded = probe
            turn_thinks = thinks[before_thinks:]
            payload = turn_thinks[0] if turn_thinks else {}
            whole, working, memory = _context_text(payload)
            seen = all(e in whole for e in expected)
            where = sorted({label for label, block in (("working", working), ("memory", memory))
                            if any(e in block for e in expected)})
            order_ok = None
            if superseded:
                old = [whole.rfind(s) for s in superseded]
                new = [whole.rfind(e) for e in expected]
                order_ok = all(o < 0 for o in old) or (min(n for n in new) > max(old) if all(n >= 0 for n in new) else False)
            results.append({"probe": name, "turn": index, "seen": seen, "where": where, "order_ok": order_ok,
                            "context_chars": len(whole)})
            if verbose:
                print(f"--- {name} (turn {index}) ---\n{whole}\n")
    finally:
        await sub.unsubscribe()
        await sub2.unsubscribe()
        await kernel.shutdown()
        tmp.cleanup()
    score = sum(1 for r in results if r["seen"] and r["order_ok"] in (None, True))
    return {"probes": results, "score": score, "of": len(results), "turns": len(SCRIPT),
            "seconds": round(time.monotonic() - started, 1)}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    # The Interface narrates each turn to the terminal; keep that out of
    # the report (and out of --json) unless asked for.
    import contextlib
    import io

    sink = io.StringIO()
    with contextlib.redirect_stdout(sys.stdout if args.verbose else sink):
        report = asyncio.run(run(verbose=args.verbose))
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print(f"recall scenario: {report['score']}/{report['of']} probes pass ({report['turns']} turns, {report['seconds']} s)")
        print(f"{'probe':<14} {'turn':>4}  {'seen':<5} {'where':<18} {'order_ok':<8} context")
        for r in report["probes"]:
            print(f"{r['probe']:<14} {r['turn']:>4}  {str(r['seen']):<5} {','.join(r['where']) or '-':<18} "
                  f"{str(r['order_ok']):<8} {r['context_chars']} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
