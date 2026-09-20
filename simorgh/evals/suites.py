"""The suites, and how a suite is found (stage 4 item 9).

A suite is a name and an async function that yields `Outcome`s. That is
deliberately the whole interface: the three harnesses this package
merges are wildly different underneath -- one boots the system and types
at it, one runs real tasks in a repo copy, one asks a model questions
from a dataset -- and the only thing they usefully share is what they
report. Anything richer here would be a framework that each of them
fights.

Registered today:

    household     the scripted conversation, probed for what the model saw
    ledger        SQLite as the default: migration, boot, latency, kill (free)
    trials        the seven real tasks (`tools/trial_suite.py`), real money
    tooluse       BFCL, through `simorgh/benchmark`
    research      GAIA, through `simorgh/benchmark`
    code          the SWE-bench Verified slice, through `simorgh/benchmark`

`household` is the one the loader's bless runs: it needs no model, no
network and no money, it takes about two seconds, and it measures the
thing that broke most often in the live system -- whether what the
family said reaches the prompt.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from .api import Case, FAILED, Outcome, PASSED, SKIPPED

#: name -> runner. A runner takes no arguments and returns outcomes.
Runner = Callable[[], Awaitable[list[Outcome]]]

#: Suites that cost real money. `run` refuses them without `--paid`,
#: because "I ran the evals" should never be a surprise on a bill.
PAID: frozenset[str] = frozenset({"trials", "tooluse", "research", "code"})


async def household() -> list[Outcome]:
    """The scripted household conversation, one case per probe.

    A probe passes when every fact it expects is in the context the
    model would have reasoned over, and -- for the correction probe --
    the correction is there without the superseded value winning.
    """
    from .scenario import run as run_scenario

    report = await run_scenario()
    outcomes: list[Outcome] = []
    per_probe = report["seconds"] / max(1, len(report["probes"]))
    for probe in report["probes"]:
        name = str(probe["probe"])
        seen, order_ok = bool(probe["seen"]), probe["order_ok"]
        passed = seen and order_ok in (None, True)
        why = ""
        if not seen:
            why = "the fact never reached the prompt"
        elif order_ok is False:
            why = "the superseded value outranked the correction"
        outcomes.append(Outcome(
            case=Case(name=name, kind="probe", level="recall",
                      detail={"turn": probe["turn"], "where": probe["where"]}),
            status=PASSED if passed else FAILED, seconds=round(per_probe, 2), why=why))
    return outcomes


async def trials() -> list[Outcome]:
    """The seven real tasks, in a copy of the repo, against a real model.

    Each trial is a case; a trial that failed for a reason that is the
    harness's fault rather than the system's (`_OUR_FAULT`: a timeout,
    an oversized context, no provider) is skipped, not counted, because
    a provider outage is not a regression in Sim.
    """
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "tools"))
    try:
        # `tools/` is a directory of scripts, not a package, and it is
        # not there in an installed copy. The harness itself stays put:
        # it is how every real bug in this system has been found, and
        # moving 500 lines of it on a day nobody can afford a paid run
        # to re-verify would be trading a working thing for a tidier
        # import. This package owns the *reporting*; that move is noted
        # in CONTRACT.md as still to do.
        from trial_suite import TRIALS, _OUR_FAULT, make_lab, run_one  # noqa: PLC0415, SLF001
    except ImportError as exc:
        return [Outcome(case=Case(name="trials", kind="trial"), status=SKIPPED,
                        why=f"the trial harness is not importable from here: {exc}")]

    root = make_lab(str(repo))
    outcomes: list[Outcome] = []
    for trial in TRIALS:
        result = await run_one(trial, root, timeout_s=900.0)
        ours = any(fault in problem for problem in result.problems for fault in _OUR_FAULT)
        outcomes.append(Outcome(
            case=Case(name=trial.name, kind="trial", level=trial.kind),
            status=SKIPPED if ours else (PASSED if result.ok else FAILED),
            seconds=round(result.seconds, 1), cost_usd=result.cost_usd,
            why="; ".join(result.problems)[:300]))
    return outcomes


def _benchmark_suite(suite: str, level: str = "") -> Runner:
    """A `simorgh/benchmark` suite as an evals suite.

    The benchmark unit already scores each case and keeps its own
    history per model; what it does not do is report an interval over
    repeats, which is the whole reason this package exists. So the
    cases come from there and the statistics from here.
    """

    async def runner() -> list[Outcome]:
        from .house.bench import score  # noqa: PLC0415

        # Scored through a sandboxed Sim since stage 11 item 7. Before
        # that every case came back `skipped: needs a model run` --
        # the benchmark unit could score and this package could report
        # intervals, and the two were never connected.
        # `--paid` reaches here through the environment rather than
        # the signature: a `Runner` takes no arguments by design, and
        # `__main__` has already refused a paid suite without the flag.
        import os  # noqa: PLC0415

        return await score(suite, level=level, paid=bool(os.environ.get("SIMORGH_EVALS_PAID")))

    return runner


async def ledger() -> list[Outcome]:
    """Is SQLite fit to be the ledger's default (stage 9 item 5)?

    Four cases, on a COPY of the live ledger (`SIMORGH_LEDGER_EVAL_SOURCE`,
    default `~/.simorgh/ledger`; a small seeded ledger when there is
    none): the migration round-trips with nothing lost; the Kernel boots
    on SQLite no slower than on JSONL by more than half again; appends
    are fast; and a process killed mid-append loses nothing it acked.
    No model, no network, no money.
    """
    import os
    import shutil
    import sqlite3
    import subprocess
    import sys
    import tempfile
    import time
    from pathlib import Path

    from simorgh.ledger.migrate import SQLITE_NAME, compare, jsonl_to_sqlite, sqlite_to_jsonl

    outcomes: list[Outcome] = []
    source = Path(os.environ.get("SIMORGH_LEDGER_EVAL_SOURCE") or "~/.simorgh/ledger").expanduser()
    with tempfile.TemporaryDirectory(prefix="simorgh-ledger-eval-") as tmp:
        work = Path(tmp)
        jsonl_dir = work / "jsonl" / "ledger"
        if (source / "streams").is_dir():
            shutil.copytree(source, jsonl_dir, ignore=shutil.ignore_patterns("LOCK"))
            where = f"copy of {source}"
        else:
            jsonl_dir.mkdir(parents=True)
            from simorgh.ledger.backends.jsonl import JsonlBackend
            from simorgh.contracts.envelope import Event

            seeded = JsonlBackend(jsonl_dir, fsync=False)
            await seeded.start()
            for i in range(200):
                await seeded.append(Event(stream=f"task:{i % 7}", type="t", ts=float(i), trace_id="t",
                                          causation_id=None, payload={"i": i}), expected_seq=None)
            await seeded.stop()
            where = "a seeded ledger (no live one found)"

        # 1. round trip
        started = time.monotonic()
        sqlite_dir = work / "sqlite" / "ledger"
        shutil.copytree(jsonl_dir, sqlite_dir)
        report = jsonl_to_sqlite(sqlite_dir, sqlite_dir / SQLITE_NAME)
        problems = list(report.problems) + compare(jsonl_dir, sqlite_dir / SQLITE_NAME)
        back = sqlite_to_jsonl(sqlite_dir / SQLITE_NAME, work / "back")
        problems += back.problems + compare(work / "back", sqlite_dir / SQLITE_NAME)
        outcomes.append(Outcome(case=Case(name="migrate_roundtrip", kind="ledger", level="migration",
                                          detail={"streams": report.streams, "events": report.events, "blobs": report.blobs}),
                                status=PASSED if not problems else FAILED, seconds=round(time.monotonic() - started, 2),
                                why="; ".join(problems)[:300] if problems else
                                f"{report.streams} streams, {report.events} events, {report.blobs} blobs, {where}"))

        # 2. boot time, both backends
        async def _boot(data_dir: Path, backend: str) -> float:
            from simorgh.kernel.config import LoadedConfig
            from simorgh.kernel.secrets import EnvSecretStore
            from simorgh.kernel.service import Kernel

            kernel = Kernel(LoadedConfig({"runtime": {"data_dir": str(data_dir)},
                                          "cognition": {"provider_order": ["floor"]},
                                          "ledger": {"backend": backend}}, None), secrets=EnvSecretStore({}))
            t0 = time.monotonic()
            await kernel.boot()
            seconds = time.monotonic() - t0
            await kernel.shutdown()
            return seconds

        # Each Kernel in its own process: two boots in one interpreter
        # segfault on the torch models (the evals runner learnt this).
        def _boot_in_child(data_dir: Path, backend: str) -> float:
            code = ("import asyncio,sys,time\n"
                    "from simorgh.kernel.config import LoadedConfig\n"
                    "from simorgh.kernel.secrets import EnvSecretStore\n"
                    "from simorgh.kernel.service import Kernel\n"
                    "async def main():\n"
                    "    k=Kernel(LoadedConfig({'runtime':{'data_dir':sys.argv[1]},'cognition':{'provider_order':['floor']},"
                    "'ledger':{'backend':sys.argv[2]}},None),secrets=EnvSecretStore({}))\n"
                    "    t=time.monotonic(); await k.boot(); s=time.monotonic()-t; await k.shutdown(); print('BOOT',s)\n"
                    "asyncio.run(main())\n")
            proc = subprocess.run([sys.executable, "-c", code, str(data_dir), backend], capture_output=True,
                                  text=True, timeout=300, cwd=str(Path(__file__).resolve().parents[2]))
            for line in proc.stdout.splitlines():
                if line.startswith("BOOT "):
                    return float(line.split()[1])
            raise RuntimeError((proc.stderr or proc.stdout)[-400:])

        boots: dict[str, float] = {}
        for backend, data_dir in (("jsonl", work / "jsonl"), ("sqlite", work / "sqlite")):
            try:
                boots[backend] = _boot_in_child(data_dir, backend)
            except Exception as exc:  # noqa: BLE001 -- a boot that fails is the finding
                outcomes.append(Outcome(case=Case(name=f"boot_{backend}", kind="ledger", level="boot"),
                                        status=FAILED, why=f"did not boot: {exc}"[:300]))
        if "jsonl" in boots and "sqlite" in boots:
            ok = boots["sqlite"] <= boots["jsonl"] * 1.5 + 0.5
            outcomes.append(Outcome(case=Case(name="boot_sqlite_vs_jsonl", kind="ledger", level="boot"),
                                    status=PASSED if ok else FAILED, seconds=round(boots["sqlite"], 2),
                                    why=f"sqlite {boots['sqlite']:.2f} s, jsonl {boots['jsonl']:.2f} s"))

        # 3. append latency
        from simorgh.contracts.envelope import Event
        from simorgh.ledger.backends.sqlite import SqliteBackend

        sq = SqliteBackend(work / "latency.sqlite3")
        await sq.start()
        samples = []
        try:
            for i in range(300):
                t0 = time.perf_counter()
                await sq.append(Event(stream="eval:latency", type="t", ts=float(i), trace_id="t", causation_id=None,
                                      payload={"i": i}), expected_seq=None)
                samples.append((time.perf_counter() - t0) * 1000.0)
        finally:
            await sq.stop()
        samples.sort()
        p50, p95 = samples[len(samples) // 2], samples[int(len(samples) * 0.95)]
        outcomes.append(Outcome(case=Case(name="append_latency", kind="ledger", level="latency"),
                                status=PASSED if p95 < 20.0 else FAILED,
                                why=f"p50 {p50:.2f} ms, p95 {p95:.2f} ms over 300 appends"))

        # 4. resume after kill: a child appends and prints each acked seq;
        # it is killed mid-stream; everything it acked must be there.
        db = work / "kill.sqlite3"
        code = ("import asyncio,sys\n"
                "from simorgh.contracts.envelope import Event\n"
                "from simorgh.ledger.backends.sqlite import SqliteBackend\n"
                "async def main():\n"
                "    b=SqliteBackend(sys.argv[1]); await b.start(); i=0\n"
                "    while True:\n"
                "        i+=1; s=await b.append(Event(stream='eval:kill',type='t',ts=float(i),trace_id='t',causation_id=None,payload={'i':i}),expected_seq=None)\n"
                "        print(s, flush=True)\n"
                "asyncio.run(main())\n")
        child = subprocess.Popen([sys.executable, "-c", code, str(db)], stdout=subprocess.PIPE, text=True,
                                 cwd=str(Path(__file__).resolve().parents[2]))
        acked = []
        deadline = time.monotonic() + 8.0
        while len(acked) < 50 and time.monotonic() < deadline:
            line = child.stdout.readline()
            if not line:
                break
            acked.append(int(line.strip()))
        child.kill()
        child.wait(timeout=10)
        reopened = SqliteBackend(db)
        await reopened.start()
        try:
            head = await reopened.head("eval:kill")
            present = {e.seq for e in await reopened.read("eval:kill", from_seq=1, limit=None)}
        finally:
            await reopened.stop()
        lost = [s for s in acked if s not in present]
        ok = bool(acked) and not lost and head >= max(acked)
        outcomes.append(Outcome(case=Case(name="resume_after_kill", kind="ledger", level="durability"),
                                status=PASSED if ok else FAILED,
                                why=(f"{len(acked)} acked before SIGKILL, head {head} after; lost {lost[:5]}" if acked
                                     else "the child never acked an append")))
    return outcomes


SUITES: dict[str, Runner] = {
    "ledger": ledger,
    "household": household,
    "trials": trials,
    # The dataset names, not the friendly ones: `bfcl` and `swebench`
    # are not datasets and every case came back "no such benchmark"
    # from behind a `skipped`, which read as "needs a model run" and
    # hid the typo for as long as nothing scored (stage 11 item 7).
    "tooluse": _benchmark_suite("bfcl-parallel"),
    "research": _benchmark_suite("gaia", level="1"),
    "code": _benchmark_suite("swebench-verified", level="<15 min fix"),
}


def find(name: str) -> Runner:
    """The suite by name, or a `KeyError` naming the ones that exist."""
    try:
        return SUITES[name]
    except KeyError:
        raise KeyError(f"no suite {name!r}; there is {', '.join(sorted(SUITES))}") from None


async def timed(runner: Runner) -> tuple[list[Outcome], float]:
    started = time.monotonic()
    outcomes = await runner()
    return outcomes, time.monotonic() - started


__all__ = ["PAID", "Runner", "SUITES", "find", "household", "timed", "trials"]
