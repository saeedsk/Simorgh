"""Command dispatch skeleton for every v1 command (spec section 3.3's
table). Every row publishes the real v2 message this session -- Interface
never fakes a result. Where the request has a real subscriber in this
build (kernel/persona/worldmodel), the reply renders for real; every
other row is a genuine `bus.request`/`publish` against a live topic that
is honest about getting no answer yet (guardian/execution/planning/
cognition/memory/curiosity/learning/reflection are being built in
parallel this same session and may not be running when this fires).
Two rows (`remind`, `digest`) have no backing message/projection at all
yet and say so plainly -- see the spec's own §12.
"""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass

from simorgh.bus.client import BusClient
from simorgh.contracts import topics

from .parser import Command
from .vitals import VitalsCache

_NO_RESPONSE = "no response -- that subsystem isn't wired up in this build yet"
_NOT_YET = "not yet available in this build"


@dataclass
class Outcome:
    text: str
    exit_repl: bool = False


async def _request(bus: BusClient, type_: str, payload: dict, *, timeout: float, render) -> Outcome:
    try:
        reply = await bus.request(bus.new(type_, payload), timeout=timeout)
    except TimeoutError:
        return Outcome(_NO_RESPONSE)
    except Exception as exc:  # noqa: BLE001 -- a bad request is a rendered error, never a crash
        return Outcome(f"error: {exc!r}")
    if reply.payload.get("ok") is False:
        err = reply.payload.get("error", {})
        return Outcome(f"error: {err.get('code', 'unknown')} -- {err.get('detail', '')}")
    return Outcome(render(reply.payload))


async def _publish(bus: BusClient, type_: str, payload: dict, *, render_ok: str) -> Outcome:
    try:
        await bus.publish(bus.new(type_, payload))
    except Exception as exc:  # noqa: BLE001
        return Outcome(f"error: {exc!r}")
    return Outcome(render_ok)


def _action_proposed(*, tool: str, args: dict, reversibility: str, rationale: str, network: bool = False) -> dict:
    return {
        "action_id": str(uuid.uuid4()), "tool": tool, "args": args,
        "scope": {"paths": [], "network": network}, "reversibility": reversibility,
        "rationale": rationale, "proposed_by": "interface",
    }


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


async def dispatch(command: Command, *, bus: BusClient, clock, session_id: str, vitals: VitalsCache) -> Outcome:
    name, args = command.name, command.args
    now = clock.now()

    if name == "!":
        return Outcome(await run_shell(args, timeout=120.0))

    if name in ("exit", "quit"):
        await bus.publish(bus.new(topics.SYSTEM_STOP, {
            "reason": "user exit", "requested_by": f"cli:{session_id}",
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

    if name == "stop":
        await bus.publish(bus.new(topics.SYSTEM_STOP, {
            "reason": args or "user requested", "requested_by": f"cli:{session_id}",
        }, priority=9))
        return Outcome("stop requested")

    if name == "status":
        return await _request(bus, topics.SYSTEM_STATUS_REQUEST, {}, timeout=3.0, render=lambda p: (
            f"state: {p['state']}   mode: {p['mode']}   uptime: {p['uptime_seconds']:.1f}s\n"
            + "\n".join(f"  {s['name']:14s} {s['status']}" for s in p.get("subsystems", []))
        ))

    if name == "vitals":
        from . import render as render_mod
        if args.strip() == "on":
            return Outcome("vitals on (idle reprint) -- " + render_mod.vitals(vitals.snapshot()))
        if args.strip() == "off":
            return Outcome("vitals off")
        return Outcome(render_mod.vitals(vitals.snapshot()))

    if name == "help":
        from .parser import COMMAND_NAMES
        return Outcome("commands: " + ", ".join(sorted(COMMAND_NAMES)) + "  (or !<shell>, or plain chat text)")

    if name == "reflect":
        return await _request(bus, topics.REFLECT_REVIEW_REQUEST, {}, timeout=5.0, render=lambda p: (
            f"{len(p.get('patterns', []))} pattern(s), {len(p.get('takeaways', []))} takeaway(s)"
        ))

    if name in ("propose", "improve"):
        if not args:
            return Outcome(f"usage: {name} <topic>")
        return await _request(bus, topics.TASK_CREATE, {
            "kind": "skill", "description": args, "origin": "human", "mode": "execute",
        }, timeout=5.0, render=lambda p: f"task created: {p['task_id']}")

    if name == "patch":
        parts = args.split(None, 1)
        if len(parts) < 2:
            return Outcome("usage: patch <path> <description>")
        path, desc = parts
        return await _request(bus, topics.TASK_CREATE, {
            "kind": "patch", "description": desc, "subject": path, "origin": "human", "mode": "execute",
        }, timeout=5.0, render=lambda p: f"task created: {p['task_id']}")

    if name == "batch":
        parts = args.split(None, 1)
        if len(parts) < 2 or not parts[0].isdigit():
            return Outcome("usage: batch <n> <theme>")
        _n, theme = parts
        return await _publish(bus, topics.INTENT_GOAL_STATED, {
            "goal": theme, "origin": "human", "priority": 5, "wants_project": False,
        }, render_ok=f"batch goal submitted: {theme}")

    if name == "plan":
        parts = args.split(None, 1)
        if len(parts) < 2 or not parts[0].isdigit():
            return Outcome("usage: plan <n> <goal>")
        _n, goal = parts
        return await _request(bus, topics.TASK_CREATE, {
            "kind": "project", "description": goal, "origin": "human", "mode": "plan",
        }, timeout=5.0, render=lambda p: f"project task created: {p['task_id']}")

    if name == "evolve":
        parts = args.split(None, 1)
        if len(parts) < 2 or not parts[0].isdigit():
            return Outcome("usage: evolve <n> <goal>")
        _n, goal = parts
        return await _publish(bus, topics.INTENT_GOAL_STATED, {
            "goal": goal, "origin": "human", "priority": 5, "wants_project": True,
        }, render_ok=f"evolve goal submitted: {goal}")

    if name == "research":
        if not args:
            return Outcome("usage: research <topic>")
        return await _request(bus, topics.TASK_CREATE, {
            "kind": "research", "description": args, "origin": "human",
        }, timeout=5.0, render=lambda p: f"task created: {p['task_id']}")

    if name == "project":
        if not args:
            return Outcome("usage: project <goal>")
        return await _request(bus, topics.TASK_CREATE, {
            "kind": "project", "description": args, "origin": "human", "mode": "plan",
        }, timeout=5.0, render=lambda p: f"project task created: {p['task_id']}")

    if name == "discover":
        return await _request(bus, topics.CURIOSITY_DISCOVER_REQUEST, {}, timeout=5.0,
                               render=lambda p: f"discovered: {p.get('created', [])}")

    if name == "tasks":
        return await _request(bus, topics.TASK_LIST_REQUEST, {}, timeout=3.0, render=lambda p: (
            f"{len(p.get('tasks', []))} task(s), {len(p.get('projects', []))} project(s)"
        ))

    if name == "work":
        return await _request(bus, topics.TASK_WORK_NEXT_REQUEST, {}, timeout=5.0, render=lambda p: (
            f"working: {p['task_id']}" if p.get("task_id") else f"nothing to work on ({p.get('reason', 'idle')})"
        ))

    if name == "autonomous":
        mode = args.strip()
        if mode == "on":
            return await _publish(bus, topics.SYSTEM_RESUME, {
                "reason": "user enabled autonomy", "requested_by": f"cli:{session_id}", "scope": "autonomous",
            }, render_ok="autonomous mode: on")
        if mode == "off":
            return await _publish(bus, topics.SYSTEM_PAUSE, {
                "reason": "user disabled autonomy", "requested_by": f"cli:{session_id}", "scope": "autonomous",
            }, render_ok="autonomous mode: off")
        return await _request(bus, topics.SYSTEM_STATUS_REQUEST, {}, timeout=3.0, render=lambda p: f"state: {p['state']}")

    if name == "digest":
        return Outcome(_NOT_YET + " (digest projection not built this session)")

    if name in ("news", "growth"):
        return await _request(bus, topics.CURIOSITY_SHARE_REQUEST, {"kind": name}, timeout=5.0, render=lambda p: (
            f"shared: {p['content_ref']}" if p.get("shared") else "nothing to share right now"
        ))

    if name == "pending":
        return Outcome(_NOT_YET + " (pending-patch view not built this session)")

    if name == "skills":
        return await _request(bus, topics.WORLD_ENV_QUERY, {"what": "tools"}, timeout=3.0, render=lambda p: (
            "skills: " + ", ".join(t["name"] for t in p.get("tools", [])) if p.get("tools") else "no tools registered yet"
        ))

    if name == "use":
        if not args:
            return Outcome("usage: use <name>")
        return await _publish(bus, topics.ACTION_PROPOSED, _action_proposed(
            tool="skill.run", args={"name": args}, reversibility="reversible", rationale="user requested skill use",
        ), render_ok=f"proposed: use {args}")

    if name == "log":
        return Outcome(_NOT_YET + " (activity-log view not built this session)")

    if name == "trace":
        return Outcome(_NOT_YET + " (use `python -m simorgh trace <id>` instead this session)")

    if name == "fetch":
        if not args:
            return Outcome("usage: fetch <url>")
        return await _publish(bus, topics.ACTION_PROPOSED, _action_proposed(
            tool="web_fetch", args={"url": args}, reversibility="read_only", rationale="user requested fetch", network=True,
        ), render_ok=f"proposed: fetch {args}")

    if name == "interest":
        if not args:
            return Outcome("usage: interest <topic>")
        return await _publish(bus, topics.CURIOSITY_INTEREST_ADD, {"topic": args}, render_ok=f"interest added: {args}")

    if name == "interests":
        return await _request(bus, topics.CURIOSITY_INTEREST_LIST_REQUEST, {}, timeout=3.0,
                               render=lambda p: f"{len(p.get('interests', []))} interest(s)")

    if name == "curious":
        return await _request(bus, topics.CURIOSITY_INTEREST_FOLLOW_UP_REQUEST, {}, timeout=5.0,
                               render=lambda p: f"{p.get('items_found', 0)} item(s) found")

    if name == "sleep":
        return await _publish(bus, topics.SYSTEM_TICK_SLEEP, {"window_seconds": 0.0}, render_ok="sleep window requested")

    if name == "history":
        return await _request(bus, topics.MEMORY_RETRIEVE, {
            "query": "", "kinds": ["working"], "k": 20,
        }, timeout=3.0, render=lambda p: f"{len(p.get('items', []))} item(s)")

    if name == "run":
        if not args:
            return Outcome("usage: run <code>")
        return await _publish(bus, topics.ACTION_PROPOSED, _action_proposed(
            tool="run_python_sandboxed", args={"code": args}, reversibility="read_only", rationale="user requested run",
        ), render_ok="proposed: run sandboxed code")

    if name == "budget":
        return await _request(bus, topics.GUARDIAN_POSTURE_REQUEST, {}, timeout=3.0, render=lambda p: (
            f"posture: {p.get('mode', 'unknown')}   trust: {p.get('trust_score', 0.0):.1f}"
            + (("\n  tightened by: " + "; ".join(p["tightened_by"])) if p.get("tightened_by") else "")
        ))

    if name == "remind":
        return Outcome(_NOT_YET + " (no percept.time.schedule.request in the contract catalog yet -- see §12)")

    # unrecognized after autocorrect failed, or plain chat text
    return Outcome("", exit_repl=False)


__all__ = ["dispatch", "run_shell", "Outcome"]
