"""Two scripted models, for the suite's offline check (stage 19 item 8).

Neither is a language model. Each answers every case by calling Sim's
REAL tools -- `mail_search`, `cal_list`, `read_file`, built over the
`World`'s fakes exactly as the Sim run wires them -- so running them
proves the fakes reach the tools, the tools reach the data, and the
expected answers and the scorer agree about it:

- `reader` does what Sim did on 2026-10-28: one call, then an answer
  worked out from the page it got back (`PAGE` rows, or what `read_file`
  shows before it truncates). It must score WRONG on every case, which
  is what makes each case one a page cannot answer.
- `computer` does what a program over the full data would: every
  message counted (`group_by=sender`), every event, every line of a log
  read range by range, one search per named sender. It reports its
  loop as one `run_analysis` action, the shape a workbench run has. It
  must score RIGHT on every case, through a different code path from
  the expected answers' own.

Each writes its answer the way a model might -- prose, a list, a table,
"12 h 30 m", "3 Oct 2026" -- so the tolerant parsing is exercised too.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path

from .cases import FILE_TYPES, WEEKDAYS
from .world import ACCOUNT, FILES_INDEX, QUARTER_DAYS, TELEMETRY_LOG, World

#: The rows one page shows a model: the plan's "one tool page".
PAGE = 200


@dataclass
class Attempt:
    """What a model answered and which tools it proposed, in order."""

    text: str
    tools: list[str] = field(default_factory=list)


class Bench:
    """Sim's real read tools over one `World`, in this process."""

    def __init__(self, world: World, root: str | Path) -> None:
        from simorgh.domains.pim.tools import pim_tools
        from simorgh.execution.config import Config
        from simorgh.execution.tools import ReadFileTool

        self.world = world
        self.root = Path(root)
        world.install(self.root)
        config = Config.from_mapping({"repo_root": str(self.root)})
        noon = datetime.combine(world.anchor, time(12, 0)).timestamp()
        connectors = {f"{ACCOUNT}-mail": world.mailbox(), f"{ACCOUNT}-calendar": world.calendar()}
        self.tools = {t.name: t for t in pim_tools(config, connectors=connectors, clock=lambda: noon)}
        self.tools["read_file"] = ReadFileTool(config)
        self.calls: list[str] = []

    async def call(self, tool: str, **args):
        from simorgh.contracts.protocols import ToolContext

        self.calls.append(tool)
        ctx = ToolContext(action_id=f"a{len(self.calls)}", task_id=None, scope={}, constraints={},
                          data_dir=self.root, clock=None, logger=None, ledger=None)
        result = await self.tools[tool].run(args, ctx=ctx)
        if not result.ok:
            raise RuntimeError(f"{tool} failed: {result.error}")
        return result

    async def read_all_lines(self, path: str, *, step: int = 300) -> list[str]:
        """Every line of a file, through `read_file`'s line ranges."""
        lines: list[str] = []
        start = 1
        while True:
            out = (await self.call("read_file", path=f"{path}:{start}-{start + step - 1}")).output
            header = re.match(r"\[lines (\d+)-(\d+) of (\d+)", out)
            if header is None:      # past the end: read_file shows the tail instead
                break
            got = [m.group(1) for m in re.finditer(r"^\s*\d+\| (.*)$", out, flags=re.MULTILINE)]
            lines.extend(got)
            last, total = int(header.group(2)), int(header.group(3))
            if last >= total or not got:
                break
            start = last + 1
        return lines


def _addr(header: str) -> str:
    return header.split("<")[1].rstrip(">") if "<" in header else header


def _name(world: World, addr: str) -> str:
    return next((s.name for s in world.senders if s.address == addr), addr)


def _utc_day(text: str) -> date:
    return datetime.fromisoformat(text).astimezone(timezone.utc).date()


# ------------------------------------------------------------------ the shared arithmetic
def _top_senders(world: World, rows: list[dict]) -> list[tuple[str, int]]:
    lo, hi = world.mail_since, world.mail_until
    counts = Counter(_addr(r["from"]) for r in rows if lo <= _utc_day(r["date"]) <= hi)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]


def _weekday_hours(world: World, rows: list[dict]) -> dict[str, float]:
    lo, hi = world.quarter
    minutes = {day: 0.0 for day in WEEKDAYS}
    for row in rows:
        start = datetime.fromisoformat(row["start"])
        if row.get("all_day") or not row.get("end") or not (lo <= start.date() <= hi):
            continue
        minutes[WEEKDAYS[start.weekday()]] += (datetime.fromisoformat(row["end"]) - start).total_seconds() / 60
    return {day: value / 60 for day, value in minutes.items()}


def _largest(lines: list[str]) -> dict[str, list[str]]:
    rows = []
    for line in lines:
        size, _, path = line.partition("\t")
        if size.isdigit() and path:
            rows.append((int(size), path))
    out = {}
    for ext in FILE_TYPES:
        mine = sorted((r for r in rows if r[1].endswith("." + ext)), key=lambda r: (-r[0], r[1]))[:10]
        out[ext] = [path.rsplit("/", 1)[1] for _size, path in mine]
    return out


def _failures(world: World, lines: list[str]) -> dict[str, int]:
    lo, hi = world.telemetry_window
    out: Counter = Counter()
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        day = datetime.strptime(row["ts"], "%Y-%m-%dT%H:%M:%SZ").date()
        if lo <= day <= hi and not row["ok"]:
            out[row["tool"]] += 1
    return dict(out.most_common())


# ------------------------------------------------------------------ writing it down
def _say_top(world: World, ranked: list[tuple[str, int]]) -> str:
    lines = [f"{i}. {_name(world, a)} <{a}> -- {n} messages" for i, (a, n) in enumerate(ranked, 1)]
    return "Your top senders in that range:\n" + "\n".join(lines)


def _say_hours(per_day: dict[str, float]) -> str:
    def hm(value: float) -> str:
        whole, minutes = divmod(round(value * 60), 60)
        return f"{whole} h {minutes} m" if minutes else f"{whole} hours"
    return "Meeting time by weekday:\n" + "\n".join(f"- {day}: {hm(v)}" for day, v in per_day.items())


def _say_files(largest: dict[str, list[str]]) -> str:
    return "\n".join(f"{ext.upper()}: {', '.join(names)}" for ext, names in largest.items())


def _say_failures(failures: dict[str, int]) -> str:
    rows = "\n".join(f"| {tool} | {n} |" for tool, n in failures.items() if n)
    return "| tool | failures |\n|---|---|\n" + rows


def _say_latest(world: World, latest: dict[str, date | None]) -> str:
    out = []
    for sender in world.named:
        day = latest.get(sender.address)
        out.append(f"{sender.name}: {day.day} {day:%b %Y}" if day else f"{sender.name}: no message found")
    return "\n".join(out)


# ------------------------------------------------------------------ the two models
async def reader(case_id: str, bench: Bench) -> Attempt:
    """One page, then an answer from it."""
    world = bench.world
    if case_id == "mail/top-senders-30-days":
        rows = (await bench.call("mail_search", since=world.mail_since.isoformat(), limit=PAGE)).metadata["rows"]
        text = _say_top(world, _top_senders(world, rows[:PAGE]))
    elif case_id == "calendar/hours-per-weekday":
        rows = (await bench.call("cal_list", range=f"{QUARTER_DAYS + 1} days")).metadata["rows"]
        text = _say_hours(_weekday_hours(world, rows[:PAGE]))
    elif case_id == "files/largest-per-type":
        shown = (await bench.call("read_file", path=FILES_INDEX)).output
        text = _say_files(_largest(shown.splitlines()))
    elif case_id == "telemetry/failures-per-tool":
        shown = (await bench.call("read_file", path=TELEMETRY_LOG)).output
        text = _say_failures(_failures(world, shown.splitlines()))
    elif case_id == "mail/latest-per-sender":
        rows = (await bench.call("mail_search", limit=PAGE)).metadata["rows"]
        latest: dict[str, date | None] = {}
        for row in rows[:PAGE]:
            addr, day = _addr(row["from"]), _utc_day(row["date"])
            latest[addr] = max(day, latest.get(addr) or day)
        text = _say_latest(world, latest)
    else:
        raise KeyError(case_id)
    return Attempt(text=text, tools=list(bench.calls))


async def computer(case_id: str, bench: Bench) -> Attempt:
    """Every item, then the arithmetic over all of them."""
    world = bench.world
    if case_id == "mail/top-senders-30-days":
        rows = (await bench.call("mail_search", since=world.mail_since.isoformat(), group_by="sender",
                                 top=100)).metadata["rows"]
        ranked = sorted(((_addr(r["sender"]), int(r["messages"])) for r in rows), key=lambda kv: (-kv[1], kv[0]))[:5]
        text = _say_top(world, ranked)
    elif case_id == "calendar/hours-per-weekday":
        rows = (await bench.call("cal_list", range=f"{QUARTER_DAYS + 1} days")).metadata["rows"]
        text = _say_hours(_weekday_hours(world, rows))
    elif case_id == "files/largest-per-type":
        text = _say_files(_largest(await bench.read_all_lines(FILES_INDEX)))
    elif case_id == "telemetry/failures-per-tool":
        text = _say_failures(_failures(world, await bench.read_all_lines(TELEMETRY_LOG)))
    elif case_id == "mail/latest-per-sender":
        latest: dict[str, date | None] = defaultdict(lambda: None)
        for sender in world.named:
            rows = (await bench.call("mail_search", query=sender.address, limit=1)).metadata["rows"]
            latest[sender.address] = _utc_day(rows[0]["date"]) if rows else None
        text = _say_latest(world, latest)
    else:
        raise KeyError(case_id)
    return Attempt(text=text, tools=[*bench.calls, "run_analysis"])


MODELS = {"reader": reader, "computer": computer}

__all__ = ["Attempt", "Bench", "MODELS", "PAGE", "computer", "reader"]
