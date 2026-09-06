"""Interface as a `Subsystem` (docs/blueprint/subsystems/15-interface.md):
the CLI REPL, command dispatch, vitals, and console rendering. Layer 5
(registry.py).

**Honest about this session's scope** (see the spec header and its own
§12): the readline history file, the general Phase 5 HTTP/WebSocket API,
notice mid-line queueing, and interactive `ui.prompt` answer collection
via the REPL's own stdin did not land this session -- `ui.prompt` is
rendered and always resolves to its default on timeout (never silently
proceeds), which is the safe half of the spec's S2 behavior without the
full interactive half. One narrow slice of that Phase 5 item *did* land
here, pulled forward: a read-only live-status dashboard (`httpapi.py`),
because the creator asked to actually see the running system -- which
subsystems are loaded, bus/worker activity -- while first working with
v2, not just infer it from REPL scrollback.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import uuid

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context, Health

from . import render as render_mod
from .config import Config
from .dispatch import dispatch
from .httpapi import HttpApi
from .parser import parse
from .vitals import VitalsCache

VERSION = "0.1.0"


class Service:
    name = "interface"
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.UI_NOTICE, topics.UI_PROMPT, topics.ACTION_NEEDS_HUMAN, topics.ACTION_DENIED,
        topics.PERSONA_STATE_CHANGED, topics.SYSTEM_STATE_CHANGED, topics.SYSTEM_METRICS,
        topics.SYSTEM_HEALTH, topics.GUARDIAN_POSTURE_CHANGED, topics.TURN_COMPLETED,
    )
    produces: tuple[str, ...] = (
        topics.PERCEPT_TEXT_RECEIVED, topics.INTENT_GOAL_STATED, topics.SYSTEM_PAUSE,
        topics.SYSTEM_RESUME, topics.SYSTEM_STOP, topics.UI_PROMPT_ANSWERED, topics.SYSTEM_HEALTH,
    )

    def __init__(self, config: Config | None = None, *, run_repl: bool = True, http_enabled: bool | None = None) -> None:
        self.config = config or Config()
        self._run_repl = run_repl
        # Follows `run_repl` by default: the dashboard is for a human
        # actually watching a `simorgh run` session, so it comes up
        # automatically exactly when the REPL does, and stays off for
        # every headless boot (tests, `--self-check`, `status`, `trace`)
        # unless a caller explicitly overrides it either way.
        self._http_enabled = run_repl if http_enabled is None else http_enabled
        self._ctx: Context | None = None
        self._subs: list = []
        self.vitals = VitalsCache()
        self.session_id = str(uuid.uuid4())
        self._repl_thread: threading.Thread | None = None
        self._stop_repl = threading.Event()
        self._pending_turns: dict[str, asyncio.Future] = {}
        self._color = render_mod.color_enabled(self.config.color)
        self._http: HttpApi | None = None

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        self._loop = asyncio.get_running_loop()
        self._subs = [
            await ctx.bus.subscribe(topics.UI_NOTICE, self._on_notice),
            await ctx.bus.subscribe(topics.UI_PROMPT, self._on_prompt),
            await ctx.bus.subscribe(topics.ACTION_NEEDS_HUMAN, self._on_needs_human),
            await ctx.bus.subscribe(topics.ACTION_DENIED, self._on_action_denied),
            await ctx.bus.subscribe(topics.PERSONA_STATE_CHANGED, self._on_persona_state),
            await ctx.bus.subscribe(topics.SYSTEM_STATE_CHANGED, self._on_state_changed),
            await ctx.bus.subscribe(topics.SYSTEM_METRICS, self._on_metrics),
            await ctx.bus.subscribe(topics.GUARDIAN_POSTURE_CHANGED, self._on_posture),
            await ctx.bus.subscribe(topics.TURN_COMPLETED, self._on_turn_completed),
        ]
        if self._run_repl:
            self._stop_repl.clear()
            self._repl_thread = threading.Thread(target=self._repl_main, name="interface-repl", daemon=True)
            self._repl_thread.start()
        if self._http_enabled:
            self._http = HttpApi(
                ctx.bus, ledger=ctx.ledger, host=self.config.http_host, port=self.config.http_port,
                clock=ctx.clock.now if hasattr(ctx.clock, "now") else None,
                status_timeout_s=self.config.http_status_timeout_s,
                history_stream=self.config.history_stream,
                history_default_minutes=self.config.history_default_minutes,
                history_max_points=self.config.history_max_points,
                logs_default_limit=self.config.logs_default_limit,
                logs_max_limit=self.config.logs_max_limit,
            )
            try:
                await self._http.start()
                print(f"dashboard: {self._http.url}")
            except OSError as exc:
                print(f"dashboard: could not bind {self.config.http_host}:{self.config.http_port} ({exc})")
                self._http = None
        ctx.logger.info("interface.started", session_id=self.session_id)

    async def stop(self) -> None:
        self._stop_repl.set()
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs = []
        if self._repl_thread is not None:
            self._repl_thread.join(timeout=1.0)
            self._repl_thread = None
        if self._http is not None:
            await self._http.stop()
            self._http = None

    async def health(self) -> Health:
        if self._ctx is None:
            return Health.down("not started")
        return Health.ok()

    # -- REPL thread (readline blocks; bridged to asyncio via call_soon_threadsafe) ----
    def _repl_main(self) -> None:
        print("simorgh> type a command, plain text to chat, or `help`. Ctrl-D to detach the REPL.")
        while not self._stop_repl.is_set():
            try:
                line = input("> ")
            except EOFError:
                break
            except KeyboardInterrupt:
                continue
            self._loop.call_soon_threadsafe(asyncio.ensure_future, self._handle_line(line))

    async def _handle_line(self, line: str) -> None:
        command = parse(line)
        if command is None:
            return
        try:
            if command.guessed_from:
                print(f"[guessing '{command.guessed_from}' -> '{command.name}']")

            if command.name is None:
                await self._handle_chat(command.args)
                return

            outcome = await dispatch(command, bus=self._ctx.bus, clock=self._ctx.clock,
                                      session_id=self.session_id, vitals=self.vitals)
            if outcome.text:
                print(outcome.text)
            if outcome.exit_repl:
                self._stop_repl.set()
        except Exception as exc:  # noqa: BLE001 -- the REPL must survive a handler crash (spec section 8)
            print(render_mod.notice("error", f"[render error] {exc!r}", "interface", enabled=self._color))

    async def _handle_chat(self, text: str) -> None:
        # A fresh id per turn, not `self.session_id` (the REPL's own
        # stable per-instance identity, still used elsewhere e.g.
        # `dispatch()`'s session_id= for plan/batch commands): reusing one
        # fixed key here let a second chat message sent before the first
        # one's reply arrived silently overwrite `_pending_turns[key]`,
        # cross-wiring which reply resolved which prompt's future and
        # leaving the other one to time out with a false "no response" --
        # a real bug live-caught only once `run_repl=True` actually ran
        # (milestone 106).
        session_id = str(uuid.uuid4())
        fut: asyncio.Future = self._loop.create_future()
        self._pending_turns[session_id] = fut
        await self._ctx.bus.publish(self._ctx.bus.new(topics.PERCEPT_TEXT_RECEIVED, {
            "channel": "cli", "text": text, "session_id": session_id,
        }))
        try:
            reply_text = await asyncio.wait_for(fut, timeout=self.config.chat_reply_timeout_s)
            print(reply_text)
        except asyncio.TimeoutError:
            print("no response -- the reasoning subsystem isn't built yet this session")
        finally:
            self._pending_turns.pop(session_id, None)

    # -- bus handlers -----------------------------------------------------------------
    async def _on_notice(self, message: Message) -> None:
        p = message.payload
        print(render_mod.notice(p.get("level", "info"), p.get("text", ""), p.get("source", ""), enabled=self._color))

    async def _on_prompt(self, message: Message) -> None:
        """Renders the prompt and its default; always resolves on
        timeout rather than blocking on the REPL's own stdin (see this
        module's docstring -- interactive answer collection isn't
        wired to the shared input stream this session)."""
        p = message.payload
        options = p.get("options", [])
        default = p.get("default") or (options[0] if options else "")
        print(f"[prompt] {p.get('question', '')} (options: {options}; defaulting to {default!r})")
        await self._ctx.bus.publish(self._ctx.bus.new(topics.UI_PROMPT_ANSWERED, {
            "prompt_id": p.get("prompt_id", ""), "answer": default,
        }))

    async def _on_needs_human(self, message: Message) -> None:
        p = message.payload
        print(render_mod.notice("warn", f"needs human: {p}", "guardian", enabled=self._color))

    async def _on_action_denied(self, message: Message) -> None:
        p = message.payload
        print(render_mod.notice("warn", f"\U0001f6ab denied ({p.get('layer', '')}): {p.get('reasons', p)}", "guardian", enabled=self._color))

    async def _on_persona_state(self, message: Message) -> None:
        self.vitals.on_persona_state(message.payload)

    async def _on_state_changed(self, message: Message) -> None:
        print(render_mod.notice("info", f"system state: {message.payload.get('state')}", "kernel", enabled=self._color))

    async def _on_metrics(self, message: Message) -> None:
        self.vitals.on_system_metrics(message.payload)

    async def _on_posture(self, message: Message) -> None:
        self.vitals.on_guardian_posture(message.payload)

    async def _on_turn_completed(self, message: Message) -> None:
        p = message.payload
        fut = self._pending_turns.get(p.get("session_id", ""))
        if fut is not None and not fut.done():
            fut.set_result(p.get("text", ""))


__all__ = ["Service", "VERSION"]
