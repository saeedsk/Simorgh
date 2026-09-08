"""Command dispatch (07-post-cutover-review.md §3.8 / 15-interface.md
§12 q5, 2026-09-06: "the remaining commands from v1 are so scattered ...
I'd like to consolidate, simplify"). Consolidated from v1's inherited 38
names down to `status`, `tasks`, `improve`, `plan`, `research`,
`interests`, `auto`, `pause`, `resume`, `exit`, `mcp`, `help` --
absorbing near-duplicates (`vitals`/`budget`/`skills` into `status`;
`work` into `tasks`; `propose`/`patch`/`batch`/`evolve` into `improve`;
`project`/`plan <n>` into `plan`; `interest`/`curious` into `interests`;
`autonomous`/`discover`/`news`/`growth` into `auto`; `stop`/`quit` into
`exit`) and dropping five `_NOT_YET` stubs and four dev-path commands
the model's own Guardian-gated tools already cover
(`reflect`/`digest`/`pending`/`log`/`trace`/`remind`/`history`/`run`/
`use`/`fetch`/`sleep`) -- see 15-interface.md §12 q5/q6 for the full
before/after. Every row publishes the real v2 message this session --
Interface never fakes a result.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from simorgh.bus.client import BusClient
from simorgh.contracts import topics
from simorgh.contracts.envelope import Event
from simorgh.ledger.client import LedgerClient

from . import render as render_mod
from .parser import Command
from .vitals import VitalsCache

_NO_RESPONSE = "no response -- that subsystem isn't wired up in this build yet"
_NOT_YET = "not yet available in this build"

# Must match `execution/tools.py::MCP_PROPOSALS_STREAM` -- a plain string
# agreement, not a shared import, since `interface` may not import
# `execution` (`test_module_boundaries.py`'s subsystem-isolation rule);
# Ledger stream names aren't part of the typed contract catalog the way
# bus topics are, so this is the same kind of agreement `execution/
# service.py`'s own `INFLIGHT_STREAM`/`TOOLS_STREAM` constants are.
MCP_PROPOSALS_STREAM = "mcp:proposals"
# `simorgh.toml`'s primary search location (`kernel/config.py::find_
# config_path`'s first candidate, `./simorgh.toml`) -- this command
# targets the same file a normal `sim.sh` boot would read next, but
# doesn't replicate that function's full `$SIMORGH_CONFIG`/`${data_dir}`
# fallback search (kernel-only code `interface` may not import); `mcp
# approve` says exactly where it wrote, so a non-default setup is a
# visible, honest mismatch to notice and move by hand, not a silent one.
_SIMORGH_TOML_PATH = Path("simorgh.toml")


@dataclass
class Outcome:
    text: str
    exit_repl: bool = False
    # Set only by a `_request(..., watch=True)` call that created a real
    # task (`plan`/`improve`/`research`/`tasks work`) -- `service.py::
    # _handle_line` registers it in `_watched_tasks` so `_on_task_event`
    # narrates the eventual `task.completed` instead of it landing only
    # in the Ledger, unseen (live-caught: `improve web access` printed
    # "task created: <id>" and then nothing, ever, for a task that in
    # fact ran to completion with a real answer).
    task_id: str | None = None


def _render_created(label: str = "task"):
    """Live-caught: three different `improve` requests all printed
    "task created: 4cc3c407277b" -- Planning's intake had deduplicated
    each against the first (already-completed) task and replied with
    `deduplicated_against`, which this surface silently dropped, so the
    human saw a fresh task that never ran. Say so instead."""
    def _render(p: dict) -> str:
        if p.get("deduplicated_against"):
            return (f"not created -- too similar to existing {label} {p['task_id']}; "
                    f"rephrase, or `tasks` to see it")
        return f"{label} created: {p['task_id']}"
    return _render


async def _request(bus: BusClient, type_: str, payload: dict, *, timeout: float, render, watch: bool = False) -> Outcome:
    try:
        reply = await bus.request(bus.new(type_, payload), timeout=timeout)
    except TimeoutError:
        return Outcome(_NO_RESPONSE)
    except Exception as exc:  # noqa: BLE001 -- a bad request is a rendered error, never a crash
        return Outcome(f"error: {exc!r}")
    if reply.payload.get("ok") is False:
        err = reply.payload.get("error", {})
        return Outcome(f"error: {err.get('code', 'unknown')} -- {err.get('detail', '')}")
    # A deduplicated reply names an *existing* task -- often already
    # completed -- so there is no completion coming to watch for.
    task_id = reply.payload.get("task_id") if watch and not reply.payload.get("deduplicated_against") else None
    return Outcome(render(reply.payload), task_id=task_id)


async def _publish(bus: BusClient, type_: str, payload: dict, *, render_ok: str) -> Outcome:
    try:
        await bus.publish(bus.new(type_, payload))
    except Exception as exc:  # noqa: BLE001
        return Outcome(f"error: {exc!r}")
    return Outcome(render_ok)


async def run_shell(command: str, *, timeout: float) -> str:
    if not command:
        return "usage: !<shell command>"
    try:
        result = subprocess.run(  # noqa: S602 -- the human's own shell authority, run by Interface (spec section 7)
            command, shell=True, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"[shell timed out after {timeout}s]"
    except OSError as exc:
        return f"[shell error: {exc}]"
    out = (result.stdout or "") + (result.stderr or "")
    return out.rstrip() or f"[exit {result.returncode}, no output]"


async def dispatch(command: Command, *, bus: BusClient, clock, session_id: str, vitals: VitalsCache,
                    ledger: LedgerClient) -> Outcome:
    name, args = command.name, command.args
    now = clock.now()

    if name == "!":
        return Outcome(await run_shell(args, timeout=120.0))

    if name == "exit":
        await bus.publish(bus.new(topics.SYSTEM_STOP, {
            "reason": args or "user exit", "requested_by": f"cli:{session_id}",
        }, priority=9))
        return Outcome("stopping...", exit_repl=True)

    if name == "pause":
        await bus.publish(bus.new(topics.SYSTEM_PAUSE, {
            "reason": args or "user requested", "requested_by": f"cli:{session_id}", "scope": "all",
        }, priority=9))
        return Outcome("pause requested")

    if name == "resume":
        await bus.publish(bus.new(topics.SYSTEM_RESUME, {
            "reason": args or "user requested", "requested_by": f"cli:{session_id}", "scope": "all",
        }, priority=9))
        return Outcome("resume requested")

    if name == "status":
        return Outcome(await _status_panel(bus, vitals))

    if name == "help":
        from .parser import COMMAND_NAMES
        return Outcome("commands: " + ", ".join(sorted(COMMAND_NAMES)) + "  (or !<shell>, or plain chat text)")

    if name == "improve":
        args, steps = _pop_steps(args)
        if not args:
            return Outcome("usage: improve <path> <description> [steps=N]  |  improve <topic> [steps=N]")
        first, _, rest = args.partition(" ")
        if rest and _PATH_HINT.search(first):
            return await _request(bus, topics.TASK_CREATE, _with_steps({
                "kind": "patch", "description": rest.strip(), "subject": first, "origin": "human", "mode": "execute",
            }, steps), timeout=5.0, render=_render_created(), watch=True)
        return await _request(bus, topics.TASK_CREATE, _with_steps({
            "kind": "skill", "description": args, "origin": "human", "mode": "execute",
        }, steps), timeout=5.0, render=_render_created(), watch=True)

    if name == "plan":
        args, steps = _pop_steps(args)
        if not args:
            return Outcome("usage: plan <goal> [steps=N]")
        return await _request(bus, topics.TASK_CREATE, _with_steps({
            "kind": "project", "description": args, "origin": "human", "mode": "plan",
        }, steps), timeout=5.0, render=_render_created("project task"), watch=True)

    if name == "research":
        args, steps = _pop_steps(args)
        if not args:
            return Outcome("usage: research <topic> [steps=N]")
        return await _request(bus, topics.TASK_CREATE, _with_steps({
            "kind": "research", "description": args, "origin": "human",
        }, steps), timeout=5.0, render=_render_created(), watch=True)

    if name == "benchmark":
        return await _benchmark(bus, args)

    if name == "tasks":
        if args.strip() == "work":
            return await _request(bus, topics.TASK_WORK_NEXT_REQUEST, {}, timeout=5.0, render=lambda p: (
                f"working: {p['task_id']}" if p.get("task_id") else f"nothing to work on ({p.get('reason', 'idle')})"
            ), watch=True)
        # Live-caught (the creator, 2026-09-07): "it only show the total
        # number of tasks, not the tasks details". The reply has always
        # carried every field -- id, kind, status, origin, description --
        # and this rendered `len()` of it and dropped the rest, so a
        # backlog of 100 looked exactly like a backlog of 1.
        show_all = args.strip() == "all"
        return await _request(bus, topics.TASK_LIST_REQUEST, {}, timeout=3.0, render=lambda p: render_mod.task_list(
            p.get("tasks", []), p.get("projects", []), limit=1000 if show_all else 20,
        ))

    if name == "auto":
        mode = args.strip()
        if mode == "on":
            return await _publish(bus, topics.SYSTEM_RESUME, {
                "reason": "user enabled autonomy", "requested_by": f"cli:{session_id}", "scope": "autonomous",
            }, render_ok="autonomous mode: on")
        if mode == "off":
            return await _publish(bus, topics.SYSTEM_PAUSE, {
                "reason": "user disabled autonomy", "requested_by": f"cli:{session_id}", "scope": "autonomous",
            }, render_ok="autonomous mode: off")
        if mode == "now":
            return await _publish(bus, topics.SYSTEM_TICK_IDLE, {"idle_seconds": 0.0}, render_ok="idle tick requested")
        return await _request(bus, topics.SYSTEM_STATUS_REQUEST, {}, timeout=3.0, render=lambda p: f"state: {p['state']}")

    if name == "interests":
        if not args:
            return await _request(bus, topics.CURIOSITY_INTEREST_LIST_REQUEST, {}, timeout=3.0,
                                   render=lambda p: f"{len(p.get('interests', []))} interest(s)")
        return await _publish(bus, topics.CURIOSITY_INTEREST_ADD, {"topic": args}, render_ok=f"interest added: {args}")

    if name == "mcp":
        return await _mcp_command(args, bus=bus, ledger=ledger, clock=clock)

    # unrecognized after autocorrect failed, or plain chat text
    return Outcome("", exit_repl=False)


# A first token that looks like a real path (a slash, or a file
# extension) means `improve <path> <description>`'s patch shape;
# anything else is `improve <topic>`'s skill shape.
_PATH_HINT = re.compile(r"[\\/]|\.[A-Za-z0-9]{1,5}$")

# `steps=N` anywhere in an improve/plan/research line sets the step cap
# for one attempt at that task (the creator, 2026-09-07: a big task
# should be able to say it is big). Orchestration clamps it.
_STEPS_OPT = re.compile(r"(?:^|\s)steps=(\d{1,4})(?=\s|$)")


def _pop_steps(args: str) -> tuple[str, int | None]:
    match = _STEPS_OPT.search(args)
    if match is None:
        return args, None
    cleaned = (args[: match.start()] + " " + args[match.end():]).strip()
    return " ".join(cleaned.split()), int(match.group(1))


def _with_steps(payload: dict, steps: int | None) -> dict:
    if steps:
        payload["max_steps"] = steps
    return payload


_BENCHMARK_USAGE = (
    "benchmark                     the latest result for each suite\n"
    "benchmark suites              what can be run, and what is cached\n"
    "benchmark run <suite> [n] [level=L] [refresh]\n"
    "benchmark history [suite]     accuracy over time, per model\n"
    "benchmark show <run_id>       one run, case by case"
)


def _benchmark_word(args: str) -> tuple[str, str]:
    first, _, rest = args.strip().partition(" ")
    return first.lower(), rest.strip()


async def _benchmark(bus: BusClient, args: str) -> Outcome:
    from . import benchmarkview

    verb, rest = _benchmark_word(args)
    if verb in ("", "latest"):
        return await _request(bus, topics.BENCHMARK_HISTORY_REQUEST, {}, timeout=10.0,
                              render=benchmarkview.latest)
    if verb == "suites":
        return await _request(bus, topics.BENCHMARK_SUITES_REQUEST, {}, timeout=10.0,
                              render=benchmarkview.suites)
    if verb == "history":
        return await _request(bus, topics.BENCHMARK_HISTORY_REQUEST, {"suite": rest.strip()},
                              timeout=10.0, render=benchmarkview.history)
    if verb == "show":
        if not rest:
            return Outcome("usage: benchmark show <run_id>")
        return await _request(bus, topics.BENCHMARK_HISTORY_REQUEST, {"run_id": rest.strip()},
                              timeout=10.0, render=benchmarkview.detail)
    if verb == "run":
        payload, problem = benchmarkview.parse_run(rest)
        if problem:
            return Outcome(problem)
        # A run is minutes to hours; the reply says it started and the
        # progress narrates itself, the same shape as `improve`.
        return await _request(bus, topics.BENCHMARK_RUN_REQUEST, payload, timeout=60.0,
                              render=benchmarkview.started)
    return Outcome(_BENCHMARK_USAGE)


async def _panel_piece(bus: BusClient, type_: str, payload: dict, *, timeout: float, label: str, render) -> str:
    try:
        reply = await bus.request(bus.new(type_, payload), timeout=timeout)
    except TimeoutError:
        return f"{label}: unavailable (no response)"
    except Exception as exc:  # noqa: BLE001 -- one panel piece's failure never breaks the whole panel
        return f"{label}: error ({exc!r})"
    if reply.payload.get("ok") is False:
        err = reply.payload.get("error", {})
        return f"{label}: error ({err.get('code', 'unknown')})"
    return render(reply.payload)


async def _status_panel(bus: BusClient, vitals: VitalsCache) -> str:
    """07-post-cutover-review.md §3.8: `status` absorbs `vitals`/
    `budget`/`skills` into one panel, not sub-args -- health, vitals,
    posture, and registered tools together, each piece degrading
    honestly on its own if that subsystem doesn't answer in time."""
    from . import render as render_mod

    health = await _panel_piece(bus, topics.SYSTEM_STATUS_REQUEST, {}, timeout=3.0, label="state", render=lambda p: (
        f"state: {p['state']}   mode: {p['mode']}   uptime: {p['uptime_seconds']:.1f}s\n"
        + "\n".join(f"  {s['name']:14s} {s['status']}" for s in p.get("subsystems", []))
    ))
    posture = await _panel_piece(bus, topics.GUARDIAN_POSTURE_REQUEST, {}, timeout=3.0, label="posture", render=lambda p: (
        f"posture: {p.get('mode', 'unknown')}   trust: {p.get('trust_score', 0.0):.1f}"
        + (("\n  tightened by: " + "; ".join(p["tightened_by"])) if p.get("tightened_by") else "")
    ))
    skills = await _panel_piece(bus, topics.WORLD_ENV_QUERY, {"what": "tools", "args": {}}, timeout=3.0, label="skills",
                                 render=lambda p: (
        "skills: " + ", ".join(t["name"] for t in p.get("tools", [])) if p.get("tools") else "no tools registered yet"
    ))
    return "\n\n".join([health, render_mod.vitals(vitals.snapshot()), posture, skills])


async def _mcp_pending_proposals(ledger: LedgerClient) -> dict[str, dict]:
    """The latest event per `proposal_id`, filtered to still-`pending`
    (an `approved`/`rejected` event for the same id supersedes it) --
    `execution/tools.py::ProposeMcpServerTool`'s own docstring has the
    full design: this stream is the one durable record of what Sim has
    asked for and what a human has decided."""
    events = await ledger.read(MCP_PROPOSALS_STREAM)
    latest: dict[str, dict] = {}
    for event in events:
        proposal_id = event.payload.get("proposal_id")
        if proposal_id:
            latest[proposal_id] = event.payload
    return {pid: p for pid, p in latest.items() if p.get("status") == "pending"}


async def _mcp_active_tools_line(bus: BusClient) -> str:
    try:
        reply = await bus.request(bus.new(topics.WORLD_ENV_QUERY, {"what": "tools", "args": {}}), timeout=3.0)
    except TimeoutError:
        return "active MCP tools: unavailable (no response)"
    except Exception as exc:  # noqa: BLE001 -- a status line reporting its own failure, never a crash
        return f"active MCP tools: error ({exc!r})"
    names = sorted(t["name"] for t in reply.payload.get("tools", []) if t.get("provider") == "mcp")
    return "active MCP tools: " + (", ".join(names) if names else "none configured")


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _toml_string_array(items: list[str]) -> str:
    return "[" + ", ".join(_toml_string(item) for item in items) + "]"


def _mcp_server_toml_block(proposal: dict) -> str:
    """A standalone `[[execution.mcp_servers]]` block, appended to the
    end of the file rather than parsing-and-rewriting the whole
    document -- TOML's array-of-tables syntax allows a new element
    anywhere, so this never touches (or risks corrupting/reformatting)
    anything already in `simorgh.toml`, comments included."""
    lines = ["", "[[execution.mcp_servers]]",
             f"name = {_toml_string(proposal['name'])}",
             f"command = {_toml_string(proposal['command'])}"]
    if proposal.get("args"):
        lines.append(f"args = {_toml_string_array(proposal['args'])}")
    if proposal.get("read_only_tools"):
        lines.append(f"read_only_tools = {_toml_string_array(proposal['read_only_tools'])}")
    if proposal.get("env_keys"):
        # Never a real value -- Sim only ever proposes the variable
        # *names* a server needs (`ProposeMcpServerTool`'s own
        # validation); the human adds an `env` table by hand if the
        # server actually needs one.
        lines.append(f"# env vars this server needs (add real values yourself): {', '.join(proposal['env_keys'])}")
    lines.append(f"# approved via `mcp approve` -- Sim's own reason: {proposal.get('reason', '')}")
    return "\n".join(lines) + "\n"


async def _mcp_command(args: str, *, bus: BusClient, ledger: LedgerClient, clock) -> Outcome:
    parts = args.split(None, 1)
    sub = parts[0] if parts else ""

    if sub == "approve":
        if len(parts) < 2 or not parts[1].strip():
            return Outcome("usage: mcp approve <proposal_id>")
        proposal_id = parts[1].strip()
        pending = await _mcp_pending_proposals(ledger)
        proposal = pending.get(proposal_id)
        if proposal is None:
            return Outcome(f"no pending proposal {proposal_id!r} -- see `mcp` for the current list")
        with _SIMORGH_TOML_PATH.open("a", encoding="utf-8") as fh:
            fh.write(_mcp_server_toml_block(proposal))
        await ledger.append(MCP_PROPOSALS_STREAM, Event(
            stream=MCP_PROPOSALS_STREAM, type="approved", ts=clock.now(), trace_id="", causation_id=None,
            payload={**proposal, "status": "approved"},
        ))
        return Outcome(f"approved: wrote {proposal['name']!r} to {_SIMORGH_TOML_PATH} -- restart Sim to load it")

    if sub == "reject":
        if len(parts) < 2 or not parts[1].strip():
            return Outcome("usage: mcp reject <proposal_id> [reason]")
        rest = parts[1].split(None, 1)
        proposal_id, reason = rest[0], (rest[1] if len(rest) > 1 else "")
        pending = await _mcp_pending_proposals(ledger)
        proposal = pending.get(proposal_id)
        if proposal is None:
            return Outcome(f"no pending proposal {proposal_id!r} -- see `mcp` for the current list")
        await ledger.append(MCP_PROPOSALS_STREAM, Event(
            stream=MCP_PROPOSALS_STREAM, type="rejected", ts=clock.now(), trace_id="", causation_id=None,
            payload={**proposal, "status": "rejected", "rejection_reason": reason},
        ))
        return Outcome(f"rejected: {proposal['name']!r}" + (f" -- {reason}" if reason else ""))

    # bare `mcp`: what's pending, and what's already running
    pending = await _mcp_pending_proposals(ledger)
    lines: list[str] = []
    if pending:
        lines.append(f"{len(pending)} pending MCP server proposal(s):")
        for proposal_id, proposal in pending.items():
            command_line = " ".join([proposal.get("command", ""), *proposal.get("args", [])])
            lines.append(f"  {proposal_id}  {proposal.get('name', '')}  ({command_line})")
            lines.append(f"    reason: {proposal.get('reason', '')}")
        lines.append("  `mcp approve <id>` or `mcp reject <id> [reason]`")
    else:
        lines.append("no pending MCP server proposals")
    lines.append(await _mcp_active_tools_line(bus))
    return Outcome("\n".join(lines))


__all__ = ["dispatch", "run_shell", "Outcome"]
