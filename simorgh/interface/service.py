"""Interface as a `Subsystem` (docs/blueprint/subsystems/15-interface.md):
the CLI REPL, command dispatch, vitals, and console rendering. Layer 5
(registry.py).

**Honest about this session's scope** (see the spec header and its own
§12): the general Phase 5 HTTP/WebSocket API, notice mid-line queueing,
and interactive `ui.prompt` answer collection via the REPL's own stdin
did not land this session -- `ui.prompt` is rendered and always
resolves to its default on timeout (never silently proceeds), which is
the safe half of the spec's S2 behavior without the full interactive
half. One narrow slice of that Phase 5 item *did* land here, pulled
forward: a read-only live-status dashboard (`httpapi.py`), because the
creator asked to actually see the running system -- which subsystems
are loaded, bus/worker activity -- while first working with v2, not
just infer it from REPL scrollback.

The readline history file (originally also descoped) landed later,
live-caught: without importing `readline` at all, `input()` has no
concept of arrow-key line editing -- pressing Up/Down/Left/Right sends
the raw escape bytes (`^[[A` etc.) straight into the line as literal
text instead of moving a cursor or recalling history, corrupting
whatever the creator was mid-typing. Muscle-memory terminal habits
(history recall, in-line editing) are not optional polish once a human
is actually typing into this REPL for real.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
import uuid

try:
    import readline  # noqa: F401 -- imported for its side effect: input() gains
    # arrow-key editing, backspace/word-editing, and (once history is loaded
    # below) up/down recall. Not available on Windows' stock CPython.
except ImportError:  # pragma: no cover -- platform-dependent
    readline = None

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
        topics.TASK_STARTED, topics.TASK_STEP, topics.TASK_COMPLETED,
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
        self._turn_started: dict[str, float] = {}  # session_id -> monotonic start, for narration timing
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
            await ctx.bus.subscribe(topics.TASK_STARTED, self._on_task_event),
            await ctx.bus.subscribe(topics.TASK_STEP, self._on_task_event),
            await ctx.bus.subscribe(topics.TASK_COMPLETED, self._on_task_event),
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
                chat_timeout_s=self.config.http_chat_timeout_s,
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
            self._save_readline_history()
        if self._http is not None:
            await self._http.stop()
            self._http = None

    async def health(self) -> Health:
        if self._ctx is None:
            return Health.down("not started")
        return Health.ok()

    def _history_path(self):
        explicit = self.config.resolved_history_path()
        if explicit is not None:
            return explicit
        if self._ctx is None:
            return None
        return self._ctx.data_dir / "cli_history"

    def _load_readline_history(self) -> None:
        if readline is None:
            return
        path = self._history_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            readline.read_history_file(path)
        except (FileNotFoundError, OSError):
            pass
        readline.set_history_length(self.config.history_length)

    def _save_readline_history(self) -> None:
        if readline is None:
            return
        path = self._history_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            readline.write_history_file(path)
        except OSError:
            pass

    # -- REPL thread (readline blocks; bridged to asyncio via run_coroutine_threadsafe) --
    def _repl_main(self) -> None:
        self._load_readline_history()
        print(render_mod.banner(enabled=self._color, unicode=render_mod.unicode_mode(self.config.unicode)))
        print("Ctrl-D to detach the REPL.")
        while not self._stop_repl.is_set():
            try:
                line = input("> ")
            except EOFError:
                break
            except KeyboardInterrupt:
                continue
            # Live-caught (creator's own real use, twice -- once before the
            # think_timeout_s fix, again after it): this used to be
            # `call_soon_threadsafe(asyncio.ensure_future, ...)`, a true
            # fire-and-forget that let this thread's `input("> ")` loop
            # right back around and re-block on the *next* line before
            # `_handle_line` (running on the asyncio loop's own thread) had
            # even started -- let alone printed a reply. A print from that
            # other thread while this one is already inside a new blocking
            # `input()` call routinely never became visible, or only
            # showed up once the user pressed Enter again to force a
            # redraw -- indistinguishable from the process being hung,
            # which is exactly what got reported. `run_coroutine_threadsafe
            # (...).result()` blocks this thread until the turn (including
            # every print inside it) is actually done, so the next "> "
            # prompt can never race ahead of the reply it belongs after.
            try:
                asyncio.run_coroutine_threadsafe(self._handle_line(line), self._loop).result()
            except Exception as exc:  # noqa: BLE001 -- mirrors _handle_line's own
                # crash boundary; a failure bridging threads must not kill
                # this loop either (spec section 8).
                print(render_mod.notice("error", f"[render error] {exc!r}", "interface", enabled=self._color))

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
        self._turn_started[session_id] = time.monotonic()
        await self._ctx.bus.publish(self._ctx.bus.new(topics.PERCEPT_TEXT_RECEIVED, {
            "channel": "cli", "text": text, "session_id": session_id,
        }))

        async def _heartbeat() -> None:
            # Silence never lasts longer than narrate_heartbeat_s: the
            # step narration (_on_task_event) covers *what* is happening;
            # this covers "still alive" between steps (a long model call).
            while True:
                await asyncio.sleep(self.config.narrate_heartbeat_s)
                elapsed = time.monotonic() - self._turn_started.get(session_id, time.monotonic())
                print(render_mod.style(f"  ... still thinking  [{elapsed:.0f}s]", "dim", enabled=self._color))

        beat = asyncio.ensure_future(_heartbeat()) if self.config.narrate else None
        try:
            reply_text = await asyncio.wait_for(fut, timeout=self.config.chat_reply_timeout_s)
            if reply_text:
                print(reply_text)
            else:
                # An honest-floor completion (no real provider answered in
                # time) resolves the future with "", same as a real reply
                # -- printing nothing here was indistinguishable from a
                # hung REPL, live-caught by the creator's own first
                # interactive use (see Worker's own think_timeout_s note,
                # the actual root cause of the floor this was masking).
                print(render_mod.notice(
                    "warn", "(no real answer this turn -- floor reply, try again)", "cognition", enabled=self._color,
                ))
        except asyncio.TimeoutError:
            print("no response -- the reasoning subsystem isn't built yet this session")
        finally:
            if beat is not None:
                beat.cancel()
            self._pending_turns.pop(session_id, None)
            self._turn_started.pop(session_id, None)

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

    async def _on_task_event(self, message: Message) -> None:
        """Live narration (07-post-cutover-review.md §3.9): the creator
        watched "thinking" for a long time with no sign of what Sim was
        doing. The Ledger already records every step of a turn as it
        happens; this prints the ones for a turn *this REPL* is waiting
        on -- a chat turn's task_id IS its session_id (`worker.py::
        run_percept_chat`) -- as dim one-liners, and stays silent for
        every other task (autonomous ticks, other sessions)."""
        if not self.config.narrate:
            return
        p = message.payload
        task_id = p.get("task_id", "")
        if task_id not in self._pending_turns:
            return
        elapsed = time.monotonic() - self._turn_started.get(task_id, time.monotonic())
        if message.type == topics.TASK_STARTED:
            text = "thinking..."
        elif message.type == topics.TASK_STEP:
            phase, summary, tool = p.get("phase", ""), p.get("summary", ""), p.get("tool")
            ok = p.get("ok")
            mark = "" if ok is None else (" ok" if ok else " FAILED")
            what = f"{tool}: {summary}" if tool else summary
            text = f"step {p.get('step_no', '?')} ({phase}) {what}{mark}"
        else:  # task.completed -- the reply itself prints from _handle_chat
            text = "done"
        print(render_mod.style(f"  ... {text}  [{elapsed:.1f}s]", "dim", enabled=self._color))

    async def _on_turn_completed(self, message: Message) -> None:
        p = message.payload
        fut = self._pending_turns.get(p.get("session_id", ""))
        if fut is not None and not fut.done():
            fut.set_result(p.get("text", ""))


__all__ = ["Service", "VERSION"]
