"""Interface as a `Subsystem` (docs/blueprint/subsystems/15-interface.md):
the CLI REPL, command dispatch, vitals, and console rendering. Layer 5
(registry.py).

**Honest about this session's scope** (see the spec header and its own
§12): the general Phase 5 HTTP/WebSocket API and notice mid-line
queueing did not land this session. One narrow slice of that Phase 5
item *did* land here, pulled forward: a read-only live-status dashboard
(`httpapi.py`), because the creator asked to actually see the running
system -- which subsystems are loaded, bus/worker activity -- while
first working with v2, not just infer it from REPL scrollback.

**Interactive `ui.prompt` answer collection, added later, live-caught**
(the creator, real use: typed "yes" at a pending Guardian approval
question -- three separate times, worded three different ways -- and
each time it was silently auto-answered "no" instead, because `_on_
prompt` printed the question and *immediately* resolved it to the
default with no window for a real answer, and the model was never shown
the pending question at all since it's a local `print()`, not part of
`session.messages`). `_handle_line` now checks a typed line against any
pending prompt's `options` *before* command parsing or chat -- a match
resolves that prompt directly, bypassing dispatch and the model
entirely, since an approval answer is not a conversational act. A
background watchdog still auto-answers with `default` at `timeout_s` so
a prompt nobody is watching (the HTTP API, a detached session) never
hangs forever -- "always resolves," just no longer "resolves
immediately no matter what gets typed."

The readline history file (originally also descoped) landed later,
live-caught: without importing `readline` at all, `input()` has no
concept of arrow-key line editing -- pressing Up/Down/Left/Right sends
the raw escape bytes (`^[[A` etc.) straight into the line as literal
text instead of moving a cursor or recalling history, corrupting
whatever the creator was mid-typing. Muscle-memory terminal habits
(history recall, in-line editing) are not optional polish once a human
is actually typing into this REPL for real.

**Redraw-in-place status footer, 2026-09-06** (the creator's own
explicit call, after being shown the tradeoff against `render.py`'s
"scrolling blocks only" rule -- see `live_status.py`'s module docstring
for the full design and why that rule still holds byte-for-byte
whenever stdout isn't a real interactive terminal). `self._out()` is
the one gate every scrolling line in this file passes through, so the
footer and ordinary output never interleave mid-line; `_on_task_event`
and `_handle_chat`'s heartbeat update the footer in place for an
in-flight step instead of printing a fresh dim line each tick (the
creator: "a couple of dots" -- the direct fix, not a style pass), and
fold a step with a real outcome into one permanent ✅/❌-iconed
scrolling line.
"""

from __future__ import annotations

import asyncio
from collections import deque
import sys
import threading
import time
import uuid
from pathlib import Path

try:
    import readline  # noqa: F401 -- imported for its side effect: input() gains
    # arrow-key editing, backspace/word-editing, and (once history is loaded
    # below) up/down recall. Not available on Windows' stock CPython.
except ImportError:  # pragma: no cover -- platform-dependent
    readline = None

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context, Health

from . import activity as activity_mod
from . import panel as panel_mod
from . import render as render_mod
from . import tui
from .config import Config
from .dispatch import dispatch
from .httpapi import HttpApi
from .live_status import LiveStatus, clear_current_line, live_status_enabled, verb_for
from .parser import parse
from .vitals import VitalsCache

VERSION = "0.1.0"

_YES_NO_SHORTHAND = {"y": "yes", "n": "no"}


def _match_pending_answer(typed: str, options: list[str]) -> str | None:
    """A typed line that exactly names one of the pending prompt's own
    `options` (case-insensitive) answers it -- `y`/`n` also work when
    the options are literally yes/no, the overwhelmingly common case.
    Anything else (a real chat message, an unrelated command) is left
    alone; `None` means "not an answer, handle normally."""
    lowered = typed.lower()
    for option in options:
        if lowered == option.lower():
            return option
    if {o.lower() for o in options} == {"yes", "no"} and lowered in _YES_NO_SHORTHAND:
        return _YES_NO_SHORTHAND[lowered]
    return None


class Service:
    name = "interface"
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.UI_NOTICE, topics.UI_PROMPT, topics.ACTION_NEEDS_HUMAN, topics.ACTION_DENIED,
        topics.PERSONA_STATE_CHANGED, topics.SYSTEM_STATE_CHANGED, topics.SYSTEM_METRICS,
        topics.SYSTEM_HEALTH, topics.GUARDIAN_POSTURE_CHANGED, topics.TURN_COMPLETED,
        topics.TASK_STARTED, topics.TASK_STEP, topics.TASK_COMPLETED, topics.COGNITION_PROVIDER_STATUS,
        topics.PERCEPT_TIME_SCHEDULED,
    )
    produces: tuple[str, ...] = (
        topics.PERCEPT_TEXT_RECEIVED, topics.INTENT_GOAL_STATED, topics.SYSTEM_PAUSE,
        topics.SYSTEM_RESUME, topics.SYSTEM_STOP, topics.UI_PROMPT_ANSWERED, topics.SYSTEM_HEALTH,
        topics.BENCHMARK_RUN_REQUEST, topics.BENCHMARK_HISTORY_REQUEST, topics.BENCHMARK_SUITES_REQUEST,
        topics.BENCHMARK_LOAD_REQUEST, topics.BENCHMARK_STOP_REQUEST,
    )

    def __init__(self, config: Config | None = None, *, run_repl: bool = True,
                 http_enabled: bool | None = None, wait_for_boot: bool = False) -> None:
        self._config_from_caller = config
        self.config = config or Config()
        self._run_repl = run_repl
        # The REPL thread starts during the `persona, interface` boot
        # layer, so without this the splash and the "> " prompt printed
        # on top of the Kernel's own boot progress, and the later layers
        # reported themselves underneath an already-live prompt. Set only
        # by the Kernel's factory: a Service constructed directly (tests,
        # an embedding) has no Kernel to wait for and must not block.
        self._wait_for_boot = wait_for_boot
        self._booted = threading.Event()
        self._dashboard_line = ""
        self._tui = None            # the prompt_toolkit prompt, when available
        self._last_done = None      # (word, elapsed, clock) of the turn that just finished, until the next line
        self._recent_text: deque = deque(maxlen=12)  # what was said lately, for tidy's names and terms
        self._tui_task = None
        self._footer = ""           # what the sticky footer under the prompt shows
        # What every task actually is, so a narration line can name the
        # topic instead of an id (`activity.py`).
        self._book = activity_mod.TaskBook()
        self._seed_task = None
        self._posture_seed_task = None
        # For the bottom panel's status row (`panel.py`): whether the
        # idle loop may start work, and which model is answering.
        self._auto = "?"
        self._model = ""
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
        # task_ids `dispatch()` created (`plan`/`improve`/`research`/`tasks
        # work`) that this REPL fired off but isn't blocking on -- narrated
        # the same as a `_pending_turns` chat turn (`_on_task_event`), but
        # their `task.completed` prints the real `result_summary` instead
        # of resolving an awaited future (nothing's awaiting these).
        self._watched_tasks: set[str] = set()
        # What the Kernel last said its state was. A chat typed while
        # paused has nothing to wait for (`_handle_chat`).
        self._system_state = "running"
        self._pending_prompts: dict[str, dict] = {}  # prompt_id -> payload, oldest-first (dict preserves insertion order)
        self._prompt_timeouts: dict[str, asyncio.Task] = {}  # prompt_id -> its own timeout watchdog
        self._color = render_mod.color_enabled(self.config.color)
        self._live = LiveStatus(enabled=live_status_enabled(self.config.live_status))
        # True only while `_repl_main`'s thread is genuinely blocked
        # inside `input("> ")` -- the one window where a bus-handler's
        # `_out()` (running on the asyncio loop's own thread, for work
        # this REPL didn't start: an autonomous tick, a background
        # `dispatch()`ed task) can print straight over a bare prompt with
        # no footer to protect it. Plain bool, not a Lock: CPython's GIL
        # makes a single assignment atomic, and the one real race (an
        # `_out()` call landing in the few instructions around the flag
        # flip) costs at most one skipped/extra cosmetic redisplay, never
        # a correctness bug.
        self._input_pending = False
        self._http: HttpApi | None = None

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        self._loop = asyncio.get_running_loop()
        # A config passed by the caller still wins, so a test that
        # constructs the service with one is unaffected (same pattern as
        # `persona.Service.start` / `curiosity.Service.start`).
        if self._config_from_caller is None and ctx.config:
            self.config = Config.from_mapping(dict(ctx.config))
            self._color = render_mod.color_enabled(self.config.color)
            self._live = LiveStatus(enabled=live_status_enabled(self.config.live_status))
        self._subs = [
            await ctx.bus.subscribe(topics.UI_NOTICE, self._on_notice),
            # `benchmark run` prints "progress is narrated as it goes",
            # and the benchmark service does publish a message per
            # scored case -- to nobody, until 2026-09-10. Observer
            # swe-01 watched case 1 of a SWE-bench run get scored (142
            # tests passing in its container) and the terminal say
            # nothing at all about it.
            await ctx.bus.subscribe(topics.BENCHMARK_PROGRESS, self._on_benchmark_progress),
            # A reminder that fires and tells nobody is not a reminder.
            # `percept.time.scheduled` was published by the Scheduler and
            # subscribed to by NOTHING -- the whole point of `remind` and
            # `schedule` is to say something at a time, and the saying
            # never happened. Live-caught by an observer, 2026-09-10: the
            # schedule was added, the event fired, the terminal stayed
            # empty.
            await ctx.bus.subscribe(topics.PERCEPT_TIME_SCHEDULED, self._on_schedule_fired),
            await ctx.bus.subscribe(topics.UI_PROMPT, self._on_prompt),
            await ctx.bus.subscribe(topics.ACTION_NEEDS_HUMAN, self._on_needs_human),
            await ctx.bus.subscribe(topics.ACTION_DENIED, self._on_action_denied),
            await ctx.bus.subscribe(topics.PERSONA_STATE_CHANGED, self._on_persona_state),
            await ctx.bus.subscribe(topics.SYSTEM_STATE_CHANGED, self._on_state_changed),
            await ctx.bus.subscribe(topics.SYSTEM_METRICS, self._on_metrics),
            await ctx.bus.subscribe(topics.GUARDIAN_POSTURE_CHANGED, self._on_posture),
            await ctx.bus.subscribe(topics.COGNITION_PROVIDER_STATUS, self._on_provider_status),
            await ctx.bus.subscribe(topics.TURN_COMPLETED, self._on_turn_completed),
            await ctx.bus.subscribe(topics.VOICE_TRANSCRIPT, self._on_voice_transcript),
            await ctx.bus.subscribe(topics.VOICE_SPOKEN, self._on_voice_spoken),
            await ctx.bus.subscribe(topics.VOICE_LISTENING, self._on_voice_listening),
            await ctx.bus.subscribe(topics.TASK_CREATED, self._on_task_event),
            await ctx.bus.subscribe(topics.TASK_STARTED, self._on_task_event),
            await ctx.bus.subscribe(topics.TASK_STEP, self._on_task_event),
            await ctx.bus.subscribe(topics.TASK_COMPLETED, self._on_task_event),
            await ctx.bus.subscribe(topics.TASK_FAILED, self._on_task_event),
            await ctx.bus.subscribe(topics.TASK_BLOCKED, self._on_task_event),
        ]
        self._live.start()
        if self._run_repl:
            self._stop_repl.clear()
            if self._use_tui():
                # The prompt runs as a task on this same loop, so a typed
                # line is handled where the bus already is -- no thread to
                # bridge back from, and the buffer stays live while a turn
                # is in flight.
                self._tui_task = asyncio.ensure_future(self._tui_main())
            else:
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
                token=(ctx.secrets.get("SIM_API_TOKEN") or ""),
                max_body_bytes=self.config.api_max_body_bytes,
                logger=ctx.logger,
            )
            # A dashboard on 127.0.0.1 is reachable only by this
            # machine's own user, which is the posture this server was
            # written for. A non-loopback bind with no token is a
            # different thing entirely: every route, including the one
            # that starts a real tool-using turn, answers anyone who can
            # route to this host. That is a choice a person may make, so
            # it is not refused -- but it is never made silently.
            if not self._http.requires_token and self.config.http_host not in ("127.0.0.1", "localhost", "::1"):
                ctx.logger.warning(
                    "http_api_unauthenticated",
                    host=self.config.http_host, port=self.config.http_port,
                    detail="the dashboard is bound off-loopback with no SIM_API_TOKEN set; "
                           "anyone who can reach this host can start a turn",
                )
            try:
                await self._http.start()
                line = f"dashboard: {self._http.url}"
                # Same reason as the splash: printing this from `start()`
                # lands it in the middle of the Kernel's boot progress.
                if self._run_repl and self._wait_for_boot:
                    self._dashboard_line = line
                else:
                    print(line)
            except OSError as exc:
                print(f"dashboard: could not bind {self.config.http_host}:{self.config.http_port} ({exc})")
                self._http = None
        # Fired, not awaited: a missing Planning would otherwise hold
        # every start() for the full request timeout, and the feed is
        # perfectly usable while this is still in flight.
        self._seed_task = asyncio.ensure_future(self._seed_activity())
        # Same reasoning: a missing/not-yet-started Guardian would
        # otherwise hold start() for the full request timeout.
        self._posture_seed_task = asyncio.ensure_future(self._seed_posture(ctx))
        ctx.logger.info("interface.started", session_id=self.session_id)

    async def stop(self) -> None:
        self._stop_repl.set()
        if self._seed_task is not None:
            self._seed_task.cancel()
            try:
                await self._seed_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 -- shutdown must not raise
                pass
            self._seed_task = None
        if self._posture_seed_task is not None:
            self._posture_seed_task.cancel()
            try:
                await self._posture_seed_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 -- shutdown must not raise
                pass
            self._posture_seed_task = None
        if self._tui is not None:
            self._tui.stop()
            self._tui = None
        if self._tui_task is not None:
            self._tui_task.cancel()
            try:
                await self._tui_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 -- shutdown must not raise from the prompt
                pass
            self._tui_task = None
        self._live.redirect(None)
        self._live.stop()
        for task in self._prompt_timeouts.values():
            if not task.done():
                task.cancel()
        self._prompt_timeouts.clear()
        self._pending_prompts.clear()
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

    def _out(self, text: str) -> None:
        """The one gate every scrolling line in this REPL passes
        through (`live_status.py`'s own module docstring has the full
        design): clears the live-status footer first so a `print()`
        from here never lands interleaved with it, prints normally, then
        restores the footer if a turn is still actively rendering one.
        A no-op-footer (non-interactive stdout) makes this exactly a
        plain `print()`.

        Live-caught (the creator, real use, twice): the footer isn't the
        only thing that can be on screen when this fires from a bus
        handler -- a bare `input("> ")` prompt has no footer to clear,
        so a notice/denial for work the REPL didn't itself start (an
        autonomous tick, a background `dispatch()`ed task like
        `improve`) printed straight onto the same line as "> ",
        indistinguishable from the process hanging or answering its own
        prompt. `_input_pending` is only True in that exact window, so
        this branch never fires mid-turn (the REPL thread is blocked in
        `run_coroutine_threadsafe(...).result()`, not `input()`, while a
        turn it started is in flight) -- `readline.redisplay()` restores
        the prompt *and* any not-yet-submitted text the human was typing,
        which a naive reprinted `"> "` would have silently dropped."""
        self._live.clear()
        if self._input_pending:
            clear_current_line()
        print(text)
        self._live.restore()
        if self._input_pending and readline is not None and sys.stdout.isatty():
            try:
                readline.redisplay()
            except Exception:  # noqa: BLE001 -- best-effort cosmetic redraw only
                pass

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
    def _wait_for_boot_or_stop(self) -> bool:
        """Hold the splash until the Kernel reports `running`. Returns
        False if the REPL was told to stop first, so a failed boot or an
        immediate shutdown does not leave this thread parked for the full
        timeout. Bounded either way: a system that never reaches `running`
        still gets a usable prompt rather than a silent terminal."""
        deadline = time.monotonic() + self.config.boot_wait_s
        while time.monotonic() < deadline:
            if self._stop_repl.is_set():
                return False
            if self._booted.wait(timeout=0.05):
                return True
        return True

    # -- prompt_toolkit prompt (same loop as the bus) -----------------------
    def _use_tui(self) -> bool:
        """Whether to run the prompt_toolkit prompt rather than the
        readline REPL. Off when the config says so, when the dependency is
        absent, or when stdin is not a terminal -- a full-screen-capable
        prompt has nothing to attach to in a pipe, and the readline path
        handles that case correctly already."""
        if not self.config.rich_prompt:
            return False
        if not tui.available():
            return False
        try:
            return sys.stdin.isatty() and sys.stdout.isatty()
        except (AttributeError, ValueError):
            return False

    async def _tui_main(self) -> None:
        if self._wait_for_boot:
            await self._await_boot()
        print(render_mod.banner(enabled=self._color, unicode=render_mod.unicode_mode(self.config.unicode)))
        if self._dashboard_line:
            print(self._dashboard_line)
        print("Enter sends  ·  Ctrl-J newline  ·  / commands  ·  @ files  ·  Ctrl-C cancels, twice exits")
        # The live-status footer and this prompt cannot both own the
        # bottom line. prompt_toolkit's toolbar wins: it redraws with the
        # prompt instead of racing it, which is the whole reason
        # `live_status.py` had to clear and restore around every print.
        # Redirecting rather than silencing keeps every "Thinking... [4s]"
        # call site working, now rendered in the toolbar.
        self._live.redirect(self._set_footer)
        self._tui = tui.Tui(
            on_line=self._handle_line_guarded,
            on_interrupt=self._cancel_current_turn,
            footer_text=self._panel_text,
            live_text=self._live_text,
            history_path=self._history_path(),
            root=Path.cwd(),
        )
        try:
            await self._tui.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- the prompt dying must not take the process with it
            print(render_mod.notice("error", f"[prompt error] {exc!r}", "interface", enabled=self._color))
        finally:
            self._stop_repl.set()
            await self._request_stop()

    def _set_footer(self, text: str) -> None:
        self._footer = text
        self._invalidate()

    def _invalidate(self) -> None:
        # Nudge the prompt so a footer change shows without waiting for
        # the next keystroke.
        session = getattr(self._tui, "_session", None)
        app = getattr(session, "app", None)
        if app is not None and app.is_running:
            app.invalidate()

    def _panel_text(self) -> list[tuple[str, str]]:
        """The ribbon at the very bottom (`panel.footer_rows`): the
        running tasks, the queue, and the status row."""
        snap = self.vitals.snapshot()
        unicode = render_mod.unicode_mode(self.config.unicode) != "off"
        rows = panel_mod.footer_rows(
            self._book, now=time.monotonic(), auto=self._auto, posture=snap.posture, model=self._model,
            budget=panel_mod.budget_summary(snap.budget), hint="Ctrl-C cancels", unicode=unicode,
        )
        return panel_mod.flatten(rows)

    def _live_text(self) -> list[tuple[str, str]]:
        """The live section above the prompt (`panel.live_rows`): the call
        in flight, drawn in place, and the breathing line; the one-line
        `_footer` that `LiveStatus` redirects here when the book has
        nothing running; what just finished, until the next line."""
        unicode = render_mod.unicode_mode(self.config.unicode) != "off"
        rows = panel_mod.live_rows(self._book, now=time.monotonic(), footer_text=self._footer,
                                   last_done=self._last_done, unicode=unicode)
        return panel_mod.flatten(rows)

    async def _await_boot(self) -> None:
        deadline = time.monotonic() + self.config.boot_wait_s
        while time.monotonic() < deadline and not self._booted.is_set() and not self._stop_repl.is_set():
            await asyncio.sleep(0.05)

    async def _handle_line_guarded(self, line: str) -> None:
        """`_handle_line` already has its own crash boundary; this one
        covers the prompt's own call path so a raising handler can never
        end the session (spec section 8)."""
        self._last_done = None
        try:
            await self._handle_line(line)
        except Exception as exc:  # noqa: BLE001
            self._out(render_mod.notice("error", f"[render error] {exc!r}", "interface", enabled=self._color))

    def _cancel_current_turn(self) -> None:
        """Ctrl-C on an empty buffer: ask the system to stop what it is
        doing rather than killing the session."""
        if not self._watched_tasks and not self._pending_turns:
            self._out("nothing running")
            return
        self._out("interrupt: asking the current work to pause (`resume` to continue)")
        asyncio.ensure_future(self._ctx.bus.publish(self._ctx.bus.new(
            topics.SYSTEM_PAUSE, {"reason": "interrupt", "requested_by": "human"},
        )))

    async def _request_stop(self) -> None:
        """Leaving the prompt ends the run, the same way Ctrl-D did."""
        if self._ctx is None:
            return
        try:
            await self._ctx.bus.publish(self._ctx.bus.new(
                topics.SYSTEM_STOP, {"reason": "repl_exit", "requested_by": "human"},
            ))
        except Exception:  # noqa: BLE001 -- shutting down anyway
            pass

    def _repl_main(self) -> None:
        self._load_readline_history()
        if self._wait_for_boot and not self._wait_for_boot_or_stop():
            return  # asked to stop before the system ever came up
        print(render_mod.banner(enabled=self._color, unicode=render_mod.unicode_mode(self.config.unicode)))
        if self._dashboard_line:
            print(self._dashboard_line)
        print("Ctrl-D to detach the REPL.")
        while not self._stop_repl.is_set():
            self._input_pending = True
            try:
                line = input("❯ " if render_mod.unicode_mode(self.config.unicode) != "off" else "> ")
            except EOFError:
                break
            except KeyboardInterrupt:
                continue
            finally:
                self._input_pending = False
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
        stripped = line.strip()
        if self._pending_prompts and stripped:
            # The oldest pending prompt wins if more than one is somehow
            # queued at once (dict preserves insertion order) -- multiple
            # concurrent approvals disambiguated by id ("yes <id>") is a
            # real gap, not attempted here; the one-action-per-step design
            # (session.py's own module docstring) makes it rare in
            # practice.
            prompt_id, payload = next(iter(self._pending_prompts.items()))
            match = _match_pending_answer(stripped, payload.get("options", []))
            if match is not None:
                await self._resolve_prompt(prompt_id, match)
                return
        command = parse(line)
        if command is None:
            return
        try:
            if command.guessed_from:
                self._out(f"[guessing '{command.guessed_from}' -> '{command.name}']")

            if command.name is None:
                await self._handle_chat(command.args)
                return

            outcome = await dispatch(command, bus=self._ctx.bus, clock=self._ctx.clock,
                                      session_id=self.session_id, vitals=self.vitals, ledger=self._ctx.ledger)
            if outcome.text:
                self._out(outcome.text)
            if outcome.task_id:
                self._watched_tasks.add(outcome.task_id)
                self._turn_started[outcome.task_id] = time.monotonic()
            if outcome.exit_repl:
                self._stop_repl.set()
        except Exception as exc:  # noqa: BLE001 -- the REPL must survive a handler crash (spec section 8)
            self._out(render_mod.notice("error", f"[render error] {exc!r}", "interface", enabled=self._color))

    async def _seed_activity(self) -> None:
        """Ask Planning what already exists, so the feed can name it.

        A restart inherits the whole backlog, and none of it was created
        while this session was listening -- so without this the first
        thing on screen is `? · ? · (no description)` for tasks whose
        topics Planning has had all along. Never fatal: no Planning, or a
        slow one, just means the feed names ids until each task next
        moves."""
        if self._ctx is None:
            return
        try:
            reply = await self._ctx.bus.request(
                self._ctx.bus.new(topics.TASK_LIST_REQUEST, {}), timeout=3.0,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- Planning absent or slow: not this REPL's problem
            return
        adopted = self._book.seed(reply.payload.get("tasks") or [])
        if adopted:
            self._refresh_activity_footer()

    def _narrating(self, task_id: str, *, origin: str | None) -> bool:
        """Whether work this REPL did not start should still be spoken.

        The creator, 2026-09-07: "i want full visibility ... these thing
        should tell me what they are doing, what is in queue and what is
        the topic of research or skill". Before this, `_on_task_event`
        returned early for anything not in `_pending_turns` or
        `_watched_tasks`, so every autonomous task -- nearly all of them
        -- ran completely silently."""
        if task_id in self._pending_turns or task_id in self._watched_tasks:
            return True
        return bool(self.config.narrate_autonomous)

    def _narrate_autonomous(self, message: Message, record, took: float | None = None) -> None:
        """Work this REPL did not start -- a spoken turn, Sim's own
        curiosity -- drawn as the same tree a typed turn gets
        (`panel.py`): the root, a branch per finished tool call with its
        timing, a coloured excerpt of any diff inside the rail, and the
        corner that closes it. Until 2026-09-12 these printed the older
        flat `→` lines while typed turns got the tree, and the creator's
        spoken sessions saw only the flat kind."""
        unicode = render_mod.unicode_mode(self.config.unicode) != "off"
        p = message.payload
        if message.type == topics.TASK_STARTED:
            self._out(render_mod.style(panel_mod.tree_start(record, unicode=unicode), "cyan", enabled=self._color))
            return
        if message.type == topics.TASK_STEP:
            if not self.config.narrate_steps or p.get("ok") is None:
                return  # a step in flight breathes in the footer; the branch prints when it lands
            head, sep, diff_body = str(p.get("summary", "")).partition("\n\n--- a/")
            line = panel_mod.tree_step(tool=p.get("tool"), head=head, ok=p.get("ok"), took=took, unicode=unicode)
            self._out(render_mod.style(line, "green" if p.get("ok") else "red", enabled=self._color))
            if sep:
                block = render_mod.diff_block((sep[2:] + diff_body).splitlines(), label=head,
                                              enabled=self._color).splitlines()
                self._out("\n".join(panel_mod.tree_note(block, unicode=unicode)))
            return
        elapsed = None
        if record.started_at is not None:
            elapsed = time.monotonic() - record.started_at
        detail = p.get("result_summary") or p.get("reason") or ""
        colour = "green" if record.status == "completed" else "yellow"
        self._out(render_mod.style(panel_mod.tree_end(record, elapsed=elapsed, detail=detail, unicode=unicode),
                                   colour, enabled=self._color))

    def _refresh_activity_footer(self) -> None:
        """Keep the line under the prompt current: what is running, and
        how much is waiting. Only when nothing more urgent owns it -- a
        turn in flight renders its own "Thinking..." there.

        With the prompt_toolkit prompt the toolbar composes itself from
        the book on every redraw (`_panel_text`), so here it only needs
        a nudge."""
        if self._tui is not None:
            self._invalidate()
            return
        if self._pending_turns:
            return
        self._set_footer(activity_mod.footer(self._book, now=time.monotonic()))

    async def _tidy(self, text: str) -> str:
        """The line as Sim reads it: typos fixed, run-together words
        split, "Seem" made "Sim" -- shown as `↳ read as:` when anything
        changed, so the person sees what was understood."""
        if not self.config.tidy_input or self._ctx is None:
            return text
        from simorgh.cognition.tidy import tidy

        tidied = await tidy(self._ctx.bus, text, recent=list(self._recent_text))
        self._recent_text.append(tidied.text)
        if tidied.changed:
            self._out(render_mod.style(f"  ↳ read as: {tidied.text}", "dim", enabled=self._color))
        return tidied.text

    async def _handle_chat(self, text: str) -> None:
        # A paused system runs no sessions, so no answer is coming. This
        # used to publish the percept and then wait `chat_reply_timeout_s`
        # (420s) for a reply that could not arrive -- and because the REPL
        # thread blocks on the turn, the whole prompt was frozen for seven
        # minutes with the one command that would fix it, `resume`, queued
        # behind the block. An observer typed `resume` and `auto now` and
        # got nothing but the echo; only Ctrl-C escaped, which stops the
        # system (2026-09-08).
        if self._system_state in ("paused", "stopping"):
            self._out(render_mod.notice(
                "warn", f"the system is {self._system_state} -- nothing will answer until you type `resume`",
                "interface", enabled=self._color,
            ))
            return

        # A fresh id per turn, not `self.session_id` (the REPL's own
        # stable per-instance identity, still used elsewhere e.g.
        # `dispatch()`'s session_id= for plan/batch commands): reusing one
        # fixed key here let a second chat message sent before the first
        # one's reply arrived silently overwrite `_pending_turns[key]`,
        # cross-wiring which reply resolved which prompt's future and
        # leaving the other one to time out with a false "no response" --
        # a real bug live-caught only once `run_repl=True` actually ran
        # (milestone 106).
        text = await self._tidy(text)
        session_id = str(uuid.uuid4())
        fut: asyncio.Future = self._loop.create_future()
        self._pending_turns[session_id] = fut
        self._turn_started[session_id] = time.monotonic()
        # A chat turn's task is its session id and no `task.created`
        # ever announces it, so the book -- and the panel -- knew it
        # only as "? · ? · (no description)" (observer round, 2026-09-07).
        self._book.on_created({"task_id": session_id, "kind": "chat", "origin": "human", "description": text})
        if self._live.enabled:
            self._live.render("⏺ Thinking...  [0s]")
        await self._ctx.bus.publish(self._ctx.bus.new(topics.PERCEPT_TEXT_RECEIVED, {
            "channel": "cli", "text": text, "session_id": session_id,
        }))

        async def _heartbeat() -> None:
            # Silence never lasts longer than narrate_heartbeat_s: the
            # step narration (_on_task_event) covers *what* is happening;
            # this covers "still alive" between steps (a long model call).
            # Live footer: updates the same line in place instead of a
            # fresh scrolling line each tick (the creator: "a couple of
            # dots" -- this is the direct fix, not just a style pass).
            while True:
                await asyncio.sleep(self.config.narrate_heartbeat_s)
                elapsed = time.monotonic() - self._turn_started.get(session_id, time.monotonic())
                if self._live.enabled:
                    self._live.render(f"⏺ Thinking...  [{elapsed:.0f}s]")
                else:
                    print(render_mod.style(f"  ... still thinking  [{elapsed:.0f}s]", "dim", enabled=self._color))

        beat = asyncio.ensure_future(_heartbeat()) if self.config.narrate else None
        try:
            reply_text = await asyncio.wait_for(fut, timeout=self.config.chat_reply_timeout_s)
            self._live.clear()
            if reply_text:
                self._recent_text.append(reply_text[:300])
                unicode = render_mod.unicode_mode(self.config.unicode) != "off"
                print(render_mod.reply_block(reply_text, enabled=self._color, unicode=unicode))
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
            self._live.clear()
            print(render_mod.notice(
                "warn", f"no reply within {self.config.chat_reply_timeout_s:g}s -- the turn is still running;"
                " its answer will show up as a notice if it finishes", "interface", enabled=self._color,
            ))
        finally:
            self._live.clear()
            if beat is not None:
                beat.cancel()
            self._pending_turns.pop(session_id, None)
            self._turn_started.pop(session_id, None)

    # -- bus handlers -----------------------------------------------------------------
    # -- voice: the spoken conversation, on the screen ---------------------
    # A voice turn is `percept.text.received{channel: "voice"}` from the
    # voice subsystem, not a line typed here, so nothing in `_handle_chat`
    # prints it -- and the reply resolves nobody's `_pending_turns`. The
    # creator, 2026-09-10, first evening with it: "I don't see my
    # recognized voice being typed in the console, also when sim talks I
    # don't see the transcript." Both sides are announced on the bus for
    # exactly this; the REPL just had to listen.
    async def _on_voice_transcript(self, message: Message) -> None:
        p = message.payload
        text = str(p.get("text") or "").strip()
        if p.get("partial"):
            # What is being heard so far, provisional: dim, and never
            # mistakable for a turn (the creator's screen, 2026-09-11,
            # showed three "you:" lines for one sentence).
            if text:
                self._out(render_mod.style(f"  🎤 hearing: {text[:80]}{'…' if len(text) > 80 else ''} …",
                                           "dim", enabled=self._color))
            return
        if not text:
            self._out(render_mod.style("  🎤 (heard nothing)", "dim", enabled=self._color))
            return
        if p.get("echo"):
            self._out(render_mod.style(f"  🎤 (my own voice, ignored: {text[:60]}{'...' if len(text) > 60 else ''})",
                                       "dim", enabled=self._color))
            return
        if p.get("corrected"):
            self._out(render_mod.style(f"  ↳ read as: {text}", "dim", enabled=self._color))
            return
        conf = p.get("confidence")
        tail = f"  ({conf:.0%})" if isinstance(conf, (int, float)) and conf < 0.999 else ""
        self._out(render_mod.style(f"🎤 you: {text}{tail}", "cyan", enabled=self._color))
        session_id = str(p.get("session_id") or "")
        if session_id:
            # Otherwise the activity feed narrates the turn as
            # `? · ? · (no description)` (the creator's screen, 2026-09-10).
            self._book.on_created({"task_id": session_id, "kind": "chat", "origin": "voice", "description": text})

    async def _on_voice_spoken(self, message: Message) -> None:
        text = str(message.payload.get("text") or "").strip()
        if message.payload.get("quiet"):
            self._out(render_mod.style("  🤫 not for me -- staying quiet", "dim", enabled=self._color))
            return
        if message.payload.get("command"):
            what = {"stop": "stopped", "off": "voice off", "mute": "muted"}.get(message.payload["command"], "stopped")
            self._out(render_mod.style(f"  ⏹ {what} -- you said so", "dim", enabled=self._color))
            return
        if message.payload.get("dropped"):
            reason = str(message.payload.get("reason") or "you had moved on")
            self._out(render_mod.style(f"  🔇 that answer came too late and was not spoken ({reason})", "dim",
                                       enabled=self._color))
            return
        if text:
            tail = "  (interrupted)" if message.payload.get("interrupted") else ""
            if message.payload.get("aside"):
                # The "Aha." / "Let me check." said the moment a turn ends
                # -- a beat, not a reply.
                self._out(render_mod.style(f"  🔊 {text}", "dim", enabled=self._color))
                return
            self._out(render_mod.style(f"🔊 sim: {text}{tail}", "green", enabled=self._color))

    async def _on_voice_listening(self, message: Message) -> None:
        # Only the moment the mic opens; `idle` and `speaking` would be
        # one line of noise per turn, and the transcript already marks
        # both.
        if message.payload.get("state") == "listening":
            self._out(render_mod.style("  🎤 listening...", "dim", enabled=self._color))

    async def _on_notice(self, message: Message) -> None:
        p = message.payload
        level = p.get("level", "info")
        if level == "debug":
            # Live-caught: internal bookkeeping (planning's own dedup
            # notices -- "duplicate candidate, matches task ...") was
            # printing straight into the human's chat transcript,
            # interleaved with real replies -- information for a log,
            # not a conversation. `debug` is the level a subsystem uses
            # for exactly that: never meant for this surface.
            return
        self._out(render_mod.notice(level, p.get("text", ""), p.get("source", ""), enabled=self._color))

    async def _on_benchmark_progress(self, message: Message) -> None:
        from . import benchmarkview

        self._out(render_mod.notice("info", benchmarkview.progress_line(message.payload), "benchmark",
                                    enabled=self._color))

    async def _on_schedule_fired(self, message: Message) -> None:
        # Somebody else's text, echoed to a terminal: escape codes,
        # newlines and length all have to be taken out of it first.
        label = render_mod.one_safe_line(str(message.payload.get("label") or ""))
        if not label:
            # A schedule with nothing to say is bookkeeping, not a
            # reminder; printing a blank line would be worse than
            # silence.
            return
        self._out(render_mod.notice("info", label, "reminder", enabled=self._color))

    async def _on_prompt(self, message: Message) -> None:
        """Live-caught (the creator, real use: typed "yes" twice at a
        pending Guardian approval and both times it was silently
        answered "no" instead, since this printed the question then
        *immediately* auto-answered with the default -- there was never
        a window for a real answer to land). Now genuinely interactive:
        stores the prompt as pending and answers it for real the next
        time `_handle_line` sees input that matches its `options`; a
        background watchdog still auto-answers with `default` at
        `timeout_s` so a prompt from a channel with nobody watching (the
        HTTP API, a detached session) never hangs forever -- "always
        resolves," just no longer "resolves immediately no matter what
        gets typed."
        """
        p = message.payload
        prompt_id = p.get("prompt_id", "")
        if not prompt_id:
            return
        options = p.get("options", [])
        default = p.get("default") or (options[0] if options else "")
        self._pending_prompts[prompt_id] = p
        banner = render_mod.prompt_banner(p.get("question", ""), options, enabled=self._color)
        self._out(f"{banner}\nreply here, or waits {p.get('timeout_s', 0):.0f}s then defaults to {default!r}")

        async def _watchdog() -> None:
            await self._ctx.clock.sleep(p.get("timeout_s", 0) or 0)  # injected Clock, not raw asyncio.sleep -- FakeClock-testable
            if prompt_id in self._pending_prompts:
                await self._resolve_prompt(prompt_id, default, note="(timed out)")

        self._prompt_timeouts[prompt_id] = asyncio.ensure_future(_watchdog())

    async def _resolve_prompt(self, prompt_id: str, answer: str, *, note: str = "") -> None:
        self._pending_prompts.pop(prompt_id, None)
        task = self._prompt_timeouts.pop(prompt_id, None)
        if task is not None and not task.done():
            task.cancel()
        await self._ctx.bus.publish(self._ctx.bus.new(topics.UI_PROMPT_ANSWERED, {
            "prompt_id": prompt_id, "answer": answer,
        }))
        self._out(f"[prompt] answered {answer!r} {note}".rstrip())

    async def _on_needs_human(self, message: Message) -> None:
        # `_on_prompt` (`ui.prompt`, fired by Guardian for the exact same
        # escalation) already renders the real, answerable question --
        # this raw-dict line used to print alongside it, unformatted and
        # redundant (the same raw-structure-on-screen issue already fixed
        # elsewhere this session for `status`). A short, clean marker is
        # still worth keeping for anyone scrolling back through a log.
        p = message.payload
        self._out(render_mod.notice("warn", f"action {p.get('action_id', '')} needs approval", "guardian", enabled=self._color))

    async def _on_action_denied(self, message: Message) -> None:
        p = message.payload
        self._out(render_mod.notice("warn", f"\U0001f6ab denied ({p.get('layer', '')}): {p.get('reasons', p)}", "guardian", enabled=self._color))

    async def _on_persona_state(self, message: Message) -> None:
        self.vitals.on_persona_state(message.payload)

    async def _on_state_changed(self, message: Message) -> None:
        state = message.payload.get("state")
        self._system_state = str(state or self._system_state)
        if state == "running":
            self._booted.set()  # releases the REPL thread's splash
        if "autonomous_paused" in message.payload:
            self._auto = "off" if message.payload.get("autonomous_paused") else "on"
        self._out(render_mod.notice("info", f"system state: {state}", "kernel", enabled=self._color))
        self._refresh_activity_footer()

    async def _on_provider_status(self, message: Message) -> None:
        p = message.payload
        if p.get("selected") or not self._model:
            self._model = str(p.get("model") or p.get("provider") or "")
            self._refresh_activity_footer()

    async def _on_metrics(self, message: Message) -> None:
        self.vitals.on_system_metrics(message.payload)

    async def _on_posture(self, message: Message) -> None:
        self.vitals.on_guardian_posture(message.payload)

    async def _seed_posture(self, ctx: Context) -> None:
        """`VitalsCache.on_guardian_posture` only ever runs off
        `guardian.posture.changed`, which Guardian publishes only when a
        rule actually tightens/loosens (`guardian/service.py`) -- never
        once at boot. So a fresh boot's `status`/`vitals` panel showed
        `posture: unknown` all session even on a perfectly healthy,
        untightened Guardian, while `guardian.posture.request/reply`
        (wired for the `budget` command) answered the real posture the
        whole time (observer, 2026-09-08). One best-effort query here
        seeds the cache with that same real answer; a timeout or missing
        Guardian just leaves it "unknown", same as today, honestly."""
        try:
            reply = await ctx.bus.request(
                Message.new(topics.GUARDIAN_POSTURE_REQUEST, source=ctx.source, payload={}), timeout=2.0,
            )
        except Exception:  # noqa: BLE001 -- BusTimeout or "nobody answers this yet": leave posture unknown
            return
        self.vitals.on_guardian_posture(reply.payload)

    async def _on_task_event(self, message: Message) -> None:
        """Live narration (07-post-cutover-review.md §3.9): the creator
        watched "thinking" for a long time with no sign of what Sim was
        doing. The Ledger already records every step of a turn as it
        happens; this narrates the ones for a turn *this REPL* is
        waiting on -- a chat turn's task_id IS its session_id
        (`worker.py::run_percept_chat`) -- or one it fired off and is
        still watching for (`_watched_tasks`, populated by `_handle_line`
        from `Outcome.task_id` -- `plan`/`improve`/`research`/`tasks
        work`) -- and stays silent for every other task (autonomous
        ticks, other sessions).

        Live-caught (the creator, real use: `improve web access` printed
        "task created: c30b6e3360c3" and then nothing -- the task really
        ran, stepped, and completed with a real, useful answer, visible
        only by reading the Ledger directly, because this handler's own
        `_pending_turns` filter treated a task the REPL itself just
        created exactly like a stranger's autonomous tick: intentional
        silence, aimed at the wrong case). A watched task's `task.
        completed` now prints its `result_summary` through `_out()` --
        same footer/prompt-safe gate as everything else in this file --
        instead of the placeholder "done" a chat-driven completion
        already replaces with the model's real answer over in
        `_handle_chat`.

        On a real interactive terminal (`self._live.enabled`), an
        in-flight step (`ok` absent -- the pre-think announcement, or
        any other "still working" signal) updates the redraw-in-place
        footer with a "breathing verb" (`live_status.verb_for`) instead
        of adding a scrolling line -- this is the actual fix for "a
        couple of dots," not just a style pass. A step with a real
        outcome folds into one permanent scrolling line with a
        ✅/❌ icon (Claude Code's own convention, the creator's
        reference) so the transcript reads as a clean history, not a
        wall of identical dim lines. Anything without a live terminal
        (redirected/piped/headless, every existing test) gets the exact
        prior scrolling-dim-line behavior, unchanged."""
        if not self.config.narrate:
            return
        p = message.payload
        task_id = p.get("task_id", "")

        # The book is kept for *every* task regardless of what is printed:
        # the footer's "what is running / what is queued" needs the whole
        # picture, and a task only names its topic if `task.created` was
        # recorded when it went past.
        if message.type == topics.TASK_CREATED:
            self._book.on_created(p)
            self._refresh_activity_footer()
            if self._narrating(task_id, origin=p.get("origin")):
                self._out(render_mod.style(
                    "  queued  " + self._book.get(task_id).short_topic(), "dim", enabled=self._color,
                ))
            return

        record = self._book.get(task_id)
        now = time.monotonic()
        took: float | None = None
        if message.type == topics.TASK_STARTED:
            self._book.on_started(task_id, now=now)
        elif message.type == topics.TASK_STEP:
            in_flight = p.get("ok") is None
            if not in_flight:
                took = self._book.step_took(task_id, now=now)
            head = str(p.get("summary", "")).partition("\n\n--- a/")[0]
            self._book.on_step(
                task_id, now=now, phase=p.get("phase", ""), verb=verb_for(p.get("phase", ""), p.get("tool")),
                in_flight=in_flight, tool=str(p.get("tool") or ""), detail=head,
            )
        elif message.type in (topics.TASK_COMPLETED, topics.TASK_FAILED, topics.TASK_BLOCKED):
            finished = self._book.on_finished(task_id, {
                topics.TASK_COMPLETED: "completed",
                topics.TASK_FAILED: "failed",
                topics.TASK_BLOCKED: "blocked",
            }[message.type])
            if task_id in self._pending_turns or task_id in self._watched_tasks:
                elapsed = now - finished.started_at if finished.started_at is not None else 0.0
                self._last_done = (panel_mod.breath_word(task_id, elapsed).replace("ing", "ed"), elapsed,
                                   time.strftime("%H:%M"))
        self._refresh_activity_footer()

        watched = task_id in self._watched_tasks
        mine = task_id in self._pending_turns or watched
        if not mine and not self._narrating(task_id, origin=record.origin):
            return
        if not mine:
            # Autonomous work: a start and an outcome always, steps only
            # when asked for. Told as a short, complete story rather than
            # folded into the footer, which only ever shows one thing.
            self._narrate_autonomous(message, record, took)
            return
        elapsed = time.monotonic() - self._turn_started.get(task_id, time.monotonic())

        if message.type == topics.TASK_STEP:
            phase, summary, tool = p.get("phase", ""), p.get("summary", ""), p.get("tool")
            ok = p.get("ok")
            step_no = p.get("step_no", "?")
            # Live-caught (the creator: "I'd like ... code diffs ...
            # similar UI experience as claude code cli" -- 07-post-
            # cutover-review.md §3.11): a real diff now travels in this
            # step's own `summary` (up to 2000 chars -- see session.py's
            # `_propose_and_await`, which keeps the *model's* own copy
            # short separately); render it as a real diff block, not
            # squeezed into one dim narration line.
            head, sep, diff_body = summary.partition("\n\n--- a/")
            what = f"{tool}: {head}" if tool else head

            if self._live.enabled:
                if ok is None:
                    verb = verb_for(phase, tool)
                    detail = f" {head}" if head else ""
                    self._live.render(f"⏺ {verb}...{detail}  [{elapsed:.0f}s]")
                    return
                # One branch of the task's tree (`panel.py`): the tool,
                # what it touched, ✓/✗, and how long it took.
                unicode = render_mod.unicode_mode(self.config.unicode) != "off"
                line = panel_mod.tree_step(tool=tool, head=head, ok=ok, took=took, unicode=unicode)
                self._out(render_mod.style(line, "green" if ok else "red", enabled=self._color))
                if sep:
                    lines = (sep[2:] + diff_body).splitlines()
                    block = render_mod.diff_block(lines, label=head, enabled=self._color).splitlines()
                    self._out("\n".join(panel_mod.tree_note(block, unicode=unicode)))
                self._live.render(f"⏺ Thinking...  [{elapsed:.0f}s]")
                return

            mark = "" if ok is None else (" ok" if ok else " FAILED")
            text = f"step {step_no} ({phase}) {what}{mark}"
            print(render_mod.style(f"  ... {text}  [{elapsed:.1f}s]", "dim", enabled=self._color))
            if sep:
                # `sep` is the matched separator "\n\n--- a/"; strip its two
                # leading newlines to put back the "--- a/..." diff header.
                lines = (sep[2:] + diff_body).splitlines()
                print(render_mod.diff_block(lines, label=head, enabled=self._color))
            return

        if message.type == topics.TASK_STARTED:
            if self._live.enabled:
                unicode = render_mod.unicode_mode(self.config.unicode) != "off"
                self._out(render_mod.style(panel_mod.tree_start(record, unicode=unicode), "cyan", enabled=self._color))
                self._live.render(f"⏺ Thinking...  [{elapsed:.0f}s]")
                return
            text = "thinking..."
        else:  # task.completed
            self._live.clear()
            if self._live.enabled:
                unicode = render_mod.unicode_mode(self.config.unicode) != "off"
                detail = p.get("reason") or "" if message.type != topics.TASK_COMPLETED else ""
                self._out(render_mod.style(
                    panel_mod.tree_end(record, elapsed=elapsed, detail=detail, unicode=unicode),
                    "green" if record.status == "completed" else "yellow", enabled=self._color,
                ))
            if watched:
                # `task.blocked` (planning/service.py::_retry_or_block) is
                # never the last word on a task: it is the ONLY event that
                # publisher emits for an attempt Planning is about to retry
                # with a fresh budget on this same task_id (the terminal
                # give-up case is a *different* topic, `task.failed` with
                # `terminal: true`). Saying "task <id> ended blocked" here
                # reads as final when it is not, and discarding the task
                # from `_watched_tasks` made it worse: the retry's own
                # steps and its eventual answer fell through to
                # `_narrate_autonomous` (a truncated one-line summary,
                # capped to fit the terminal width) instead of this
                # personalised "finished" block with the model's real,
                # untruncated answer -- so a human who typed `improve ...`
                # and watched it get blocked would see their own request's
                # real completion rendered as though it were someone else's
                # unrelated background task (observer, 2026-09-08).
                retrying = message.type == topics.TASK_BLOCKED
                if not retrying:
                    self._watched_tasks.discard(task_id)
                    self._turn_started.pop(task_id, None)
                # Only a COMPLETED task has an answer. A blocked or
                # failed one has a `result_summary` too -- and when the
                # claims guard rejects a fabrication, that summary IS
                # the fabrication, which this printed under the word
                # "finished" as though it were the reply.
                #
                # Observed 2026-09-08, and the observer called it the
                # worst moment in their session and a trust event: the
                # system caught the model claiming a commit it never
                # made, discarded the edit, marked the task blocked --
                # and then read the lie out to the human as the answer.
                # They only learned the truth by running `git log`.
                # `record.status` was on the line above, used to pick a
                # colour.
                finished = record.status == "completed"
                reply_text = p.get("result_summary", "") if finished else ""
                if retrying:
                    retry_after = p.get("retry_after")
                    when = f" in {retry_after:.0f}s" if isinstance(retry_after, (int, float)) else ""
                    what = f"blocked -- retrying{when}"
                elif finished:
                    what = "finished"
                else:
                    what = f"ended {record.status}"
                header = render_mod.notice(
                    "info" if finished else "warn", f"task {task_id} {what}", "orchestration",
                    enabled=self._color,
                )
                if not finished:
                    why = " ".join((p.get("reason") or "").split())
                    if why:
                        header = f"{header}\n  {render_mod.style(why, 'yellow', enabled=self._color)}"
                unicode = render_mod.unicode_mode(self.config.unicode) != "off"
                self._out(f"{header}\n{render_mod.reply_block(reply_text, enabled=self._color, unicode=unicode)}"
                          if reply_text else header)
                return
            if self._live.enabled:  # the reply itself prints from _handle_chat
                return
            text = "done"
        print(render_mod.style(f"  ... {text}  [{elapsed:.1f}s]", "dim", enabled=self._color))

    async def _on_turn_completed(self, message: Message) -> None:
        p = message.payload
        fut = self._pending_turns.get(p.get("session_id", ""))
        if fut is not None and not fut.done():
            fut.set_result(p.get("text", ""))


__all__ = ["Service", "VERSION"]
