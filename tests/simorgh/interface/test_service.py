"""Interface Service over a real (memory-backend) Bus/Ledger and Context
(see tests/simorgh/worldmodel/test_service.py for the pattern rationale).
`run_repl=False` here -- the REPL thread itself (readline/stdin) is
exercised by `_handle_line` directly instead, so these tests don't
depend on a tty or piped stdin."""

import asyncio
import contextlib
import io
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context
from simorgh.interface.config import Config as InterfaceConfig
from simorgh.interface.service import Service
from simorgh.ledger.factory import make_ledger

from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class InterfaceTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(self.backend, source="interface", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()

        self.ctx = Context(
            name="interface", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=_Logger(), data_dir=Path(self._tmp.name) / "data",
        )
        self.service = Service(InterfaceConfig(chat_reply_timeout_s=0.3), run_repl=False)
        await self.service.start(self.ctx)

        self.other = make_client(self.backend, source="other", ledger=self.ledger, clock=self.clock.now)
        await self.other.start()

    async def asyncTearDown(self):
        await self.service.stop()
        await self.other.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _pump(self, n: int = 10) -> None:
        for _ in range(n):
            await asyncio.sleep(0)

    async def _line(self, text: str) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            await self.service._handle_line(text)
        return buf.getvalue()

    async def test_ui_notice_renders(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            await self.bus.publish(self.bus.new(topics.UI_NOTICE, {"level": "info", "text": "hi there", "source": "test"}))
            await self._pump()
        self.assertIn("hi there", out.getvalue())

    async def test_pause_resume_stop_round_trip(self):
        """Flow 5: pause -> resume -> stop, all real `system.*` commands
        published by Interface (proven against a real bus; the full
        Kernel-lifecycle round trip is proven in
        tests/simorgh/integration/)."""
        seen = []
        sub = await self.other.subscribe(topics.SYSTEM_PAUSE, lambda m: seen.append(m.type) or asyncio.sleep(0))
        sub2 = await self.other.subscribe(topics.SYSTEM_RESUME, lambda m: seen.append(m.type) or asyncio.sleep(0))
        sub3 = await self.other.subscribe(topics.SYSTEM_STOP, lambda m: seen.append(m.type) or asyncio.sleep(0))
        await self._line("pause")
        await self._line("resume")
        await self._line("stop")
        await self._pump()
        await sub.unsubscribe(); await sub2.unsubscribe(); await sub3.unsubscribe()
        self.assertEqual(seen, [topics.SYSTEM_PAUSE, topics.SYSTEM_RESUME, topics.SYSTEM_STOP])

    async def test_status_renders_a_real_reply(self):
        async def _responder(message: Message) -> None:
            await self.other.reply(message, type=topics.SYSTEM_STATUS_REPLY, payload={
                "state": "running", "mode": "single", "run_id": "test",
                "subsystems": [{"name": "kernel", "version": "0.1.0", "status": "ok"}],
                "uptime_seconds": 12.5,
            })
        sub = await self.other.subscribe(topics.SYSTEM_STATUS_REQUEST, _responder)
        out = await self._line("status")
        await sub.unsubscribe()
        self.assertIn("running", out)
        self.assertIn("kernel", out)

    async def test_unwired_command_gives_an_honest_no_response(self):
        out = await self._line("research nothing will answer this")
        self.assertIn("no response", out)

    async def test_plain_chat_times_out_honestly_without_cognition(self):
        out = await self._line("hello there")
        self.assertIn("no response", out)

    async def test_pending_turn_is_narrated_live_and_other_tasks_stay_silent(self):
        """07-post-cutover-review.md §3.9: while a reply is pending, each
        task.started/step/completed for *this* session prints a dim line
        (the creator watched "thinking" for a long time with no sign of
        what Sim was doing); events for any other task stay silent."""
        seen_session: dict = {}

        async def _responder(message: Message) -> None:
            sid = message.payload["session_id"]
            seen_session["id"] = sid
            await self.other.publish(self.other.new(topics.TASK_STARTED, {"task_id": sid, "worker_id": "w1"}))
            await self.other.publish(self.other.new(topics.TASK_STEP, {
                "task_id": sid, "step_no": 1, "phase": "act", "summary": "read docs/SOUL.md",
                "tool": "read_file", "ok": True,
            }))
            # An unrelated autonomous task -- must NOT be narrated.
            await self.other.publish(self.other.new(topics.TASK_STEP, {
                "task_id": "autonomous-9", "step_no": 3, "phase": "gather", "summary": "final answer",
            }))
            await asyncio.sleep(0)
            await self.other.publish(self.other.new(topics.TURN_COMPLETED, {
                "session_id": sid, "task_id": sid, "text": "the reply", "floor": False, "tool_steps": 1,
            }))

        sub = await self.other.subscribe(topics.PERCEPT_TEXT_RECEIVED, _responder)
        out = await self._line("what does SOUL.md say?")
        await sub.unsubscribe()
        self.assertIn("thinking...", out)
        self.assertIn("step 1 (act) read_file: read docs/SOUL.md ok", out)
        self.assertNotIn("final answer", out)  # the other task's step
        self.assertIn("the reply", out)
        self.assertLess(out.index("thinking..."), out.index("the reply"))

    async def test_a_diff_shaped_step_summary_renders_as_a_real_diff_block(self):
        """07-post-cutover-review.md §3.11: `execution/tools.py` now embeds
        a unified diff in a successful apply_source_patch's own output,
        which travels through as this step's `summary`. The CLI should
        render it with `render.diff_block` (colored +/- lines), not dump
        the raw "--- a/..." text inline in the one-line dim narration."""
        diff_summary = (
            "wrote src/foo.py\n\n"
            "--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
        )

        async def _responder(message: Message) -> None:
            sid = message.payload["session_id"]
            await self.other.publish(self.other.new(topics.TASK_STEP, {
                "task_id": sid, "step_no": 1, "phase": "act", "summary": diff_summary,
                "tool": "apply_source_patch", "ok": True,
            }))
            await asyncio.sleep(0)
            await self.other.publish(self.other.new(topics.TURN_COMPLETED, {
                "session_id": sid, "task_id": sid, "text": "done", "floor": False, "tool_steps": 1,
            }))

        sub = await self.other.subscribe(topics.PERCEPT_TEXT_RECEIVED, _responder)
        out = await self._line("please patch src/foo.py")
        await sub.unsubscribe()
        self.assertIn("step 1 (act) apply_source_patch: wrote src/foo.py ok", out)
        self.assertNotIn("--- a/src/foo.py", out.split("\n")[0])  # not squeezed into the one-line narration
        self.assertIn("--- a/src/foo.py", out)
        self.assertIn("+++ b/src/foo.py", out)
        self.assertIn("-old", out)
        self.assertIn("+new", out)

    async def test_plain_chat_gets_a_real_turn_completed(self):
        async def _responder(message: Message) -> None:
            await asyncio.sleep(0)
            await self.other.publish(self.other.new(topics.TURN_COMPLETED, {
                "session_id": message.payload["session_id"], "task_id": "t1",
                "text": "hi back", "floor": True, "tool_steps": 0,
            }))
        sub = await self.other.subscribe(topics.PERCEPT_TEXT_RECEIVED, _responder)
        out = await self._line("hello")
        await sub.unsubscribe()
        self.assertIn("hi back", out)

    async def test_two_chats_in_flight_at_once_never_cross_wire_their_replies(self):
        """`_handle_chat` used to key `_pending_turns` by the REPL's own
        fixed `self.session_id`, not a fresh id per turn -- two chats truly
        overlapping (concurrent dashboard/API callers, still a real
        possibility even now that `_repl_main` itself serializes one line
        at a time -- see `ReplThreadOrderingTestCase`) would silently
        overwrite the first call's dict entry, so whichever turn.completed
        happened to land first resolved the *second* call's future
        regardless of content, and the first call's own future was
        orphaned until it timed out with a false "no response". Reproduced
        here without any real timing race: both `_handle_line` calls are
        fired concurrently, exercising the collision directly rather than
        depending on real overlap actually happening."""
        replies = {"first message": "reply to first", "second message": "reply to second"}

        async def _responder(message: Message) -> None:
            await asyncio.sleep(0)
            text = message.payload["text"]
            await self.other.publish(self.other.new(topics.TURN_COMPLETED, {
                "session_id": message.payload["session_id"], "task_id": "t",
                "text": replies[text], "floor": True, "tool_steps": 0,
            }))

        sub = await self.other.subscribe(topics.PERCEPT_TEXT_RECEIVED, _responder)

        # One shared buffer, not one per task: `contextlib.redirect_stdout`
        # mutates `sys.stdout` globally, so two overlapping `with` blocks
        # on separate buffers would fight over it -- both calls run on the
        # same thread/event loop, so their individual `print()`s are each
        # atomic even while interleaved.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            await asyncio.gather(
                self.service._handle_line("first message"),
                self.service._handle_line("second message"),
            )
        await sub.unsubscribe()

        out = buf.getvalue()
        self.assertIn("reply to first", out)
        self.assertIn("reply to second", out)
        self.assertNotIn("no response", out)

    async def test_vitals_updates_from_persona_state(self):
        await self.bus.publish(self.bus.new(topics.PERSONA_STATE_CHANGED, {
            "valence": 0.4, "arousal": 0.1, "cognitive_load": 0.2, "source": "test",
            "previous": {"valence": 0.0, "arousal": 0.0, "cognitive_load": 0.0},
        }))
        await self._pump()
        out = await self._line("vitals")
        self.assertIn("mood", out)
        self.assertNotIn("no data", out)

    async def test_prompt_defaults_honestly_on_timeout(self):
        seen = []
        sub = await self.other.subscribe(topics.UI_PROMPT_ANSWERED, lambda m: seen.append(m.payload) or asyncio.sleep(0))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            await self.bus.publish(self.bus.new(topics.UI_PROMPT, {
                "prompt_id": "p1", "question": "approve?", "options": ["approve", "reject"],
                "timeout_s": 5.0, "default": "reject",
            }))
            await self._pump()
        await sub.unsubscribe()
        self.assertIn("approve?", out.getvalue())
        self.assertEqual(seen[0]["answer"], "reject")

    async def test_shell_passthrough_runs_locally(self):
        out = await self._line("!echo hello-from-shell")
        self.assertIn("hello-from-shell", out)

    async def test_health_ok(self):
        health = await self.service.health()
        self.assertEqual(health.status, "ok")


class ReplThreadOrderingTestCase(unittest.IsolatedAsyncioTestCase):
    """Live-caught (the creator's own real use, via a real terminal):
    `_repl_main` used to schedule each line's handling with
    `call_soon_threadsafe(asyncio.ensure_future, ...)` and immediately
    loop back to the *next* `input("> ")` without waiting -- so the next
    prompt could (and, per the creator's report, reliably did) appear,
    and re-block this thread inside a fresh `input()` call, before the
    previous line's reply had even started printing. The reply usually
    became invisible or badly garbled once printed from another thread
    while this one sat inside `input()`, reading as a total hang. This
    exercises the *real* REPL thread (`run_repl=True`), not `_handle_line`
    called directly, since the bug was specifically in how the thread
    loops, not in `_handle_line` itself."""

    async def test_next_prompt_never_requested_before_the_previous_replys_printed(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        clock = FakeClock()
        ledger = make_ledger({"backend": "memory"}, clock=clock.now)
        await ledger.start()
        self.addAsyncCleanup(ledger.stop)
        backend = make_backend(BusConfig(backend="memory"), clock=clock.now)
        bus = make_client(backend, source="interface", ledger=ledger, clock=clock.now)
        await bus.start()
        self.addAsyncCleanup(bus.stop)
        other = make_client(backend, source="other", ledger=ledger, clock=clock.now)
        await other.start()
        self.addAsyncCleanup(other.stop)

        events: list[str] = []
        real_print = print

        def _tracking_print(*args, **kwargs):
            if args and "reply to" in str(args[0]):
                events.append(f"printed:{args[0]}")
            real_print(*args, **kwargs)

        async def _responder(message: Message) -> None:
            # A real delay -- long enough that the old fire-and-forget
            # code would have already requested the next input() well
            # before this resolves.
            await asyncio.sleep(0.05)
            await other.publish(other.new(topics.TURN_COMPLETED, {
                "session_id": message.payload["session_id"], "task_id": "t",
                "text": f"reply to {message.payload['text']}", "floor": True, "tool_steps": 0,
            }))

        sub = await other.subscribe(topics.PERCEPT_TEXT_RECEIVED, _responder)
        self.addAsyncCleanup(sub.unsubscribe)

        lines = iter(["first", "second"])

        def _fake_input(prompt: str = "") -> str:
            try:
                line = next(lines)
            except StopIteration:
                raise EOFError from None
            events.append(f"input_requested:{line}")
            return line

        ctx = Context(
            name="interface", instance_id="", run_id="test", mode="single",
            bus=bus, ledger=ledger, config={}, secrets={}, clock=clock,
            logger=_Logger(), data_dir=Path(tmp.name) / "data",
        )
        service = Service(InterfaceConfig(chat_reply_timeout_s=2.0), run_repl=True, http_enabled=False)
        with unittest.mock.patch("builtins.input", side_effect=_fake_input), \
             unittest.mock.patch("builtins.print", side_effect=_tracking_print):
            await service.start(ctx)
            # The REPL runs on its own daemon thread; give it a real
            # moment to actually finish both turns rather than a fixed
            # asyncio.sleep(0), since it's genuinely OS-thread-scheduled.
            for _ in range(50):
                if len(events) >= 4:
                    break
                await asyncio.sleep(0.02)
            await service.stop()

        self.assertEqual(
            events,
            ["input_requested:first", "printed:reply to first",
             "input_requested:second", "printed:reply to second"],
        )


class ReadlineWiringTestCase(unittest.IsolatedAsyncioTestCase):
    """Live-caught (the creator's own real `sim.sh` use, right after the
    chat itself finally worked): pressing the Up arrow typed a literal
    `^[[A` into the line, because nothing ever imported `readline` --
    without it, `input()` has no line editing or history at all, and raw
    arrow-key escape bytes land in the buffer as text. Importing it is
    the whole fix for the garbling; the history file is the persistence
    on top. These pin the wiring, not libedit/readline's own behavior
    (which needs a real tty and is platform-dependent)."""

    def test_readline_is_imported_on_this_platform(self):
        from simorgh.interface import service as service_module

        # macOS/Linux CPython ships readline (or libedit behind the same
        # module name); only Windows' stock build lacks it.
        if sys.platform.startswith("win"):
            self.skipTest("readline is not available on stock Windows CPython")
        self.assertIsNotNone(service_module.readline)

    def test_history_helpers_are_safe_before_start_and_with_a_real_data_dir(self):
        service = Service(InterfaceConfig(), run_repl=False)
        # Before start(): no ctx, so no path -- must be a quiet no-op, never a crash.
        service._load_readline_history()  # noqa: SLF001
        service._save_readline_history()  # noqa: SLF001
        self.assertIsNone(service._history_path())  # noqa: SLF001

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data_dir = Path(tmp.name) / "interface"

        class _Ctx:
            pass

        ctx = _Ctx()
        ctx.data_dir = data_dir
        service._ctx = ctx  # noqa: SLF001
        self.assertEqual(service._history_path(), data_dir / "cli_history")  # noqa: SLF001
        # Missing file on load is fine; save creates the parent dir and the file.
        service._load_readline_history()  # noqa: SLF001
        service._save_readline_history()  # noqa: SLF001
        if service_module_readline_available():
            self.assertTrue((data_dir / "cli_history").exists())

    def test_explicit_history_path_override_wins_over_the_data_dir_default(self):
        # `[interface] history_path` existed before the readline wiring did
        # and was silently ignored by the first version of it; an explicit
        # setting must be honored (e.g. to share one history across runs),
        # while the default stays inside the per-run data dir so an
        # isolated/test run never touches the creator's real ~/.simorgh.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        explicit = Path(tmp.name) / "shared" / "history"
        service = Service(InterfaceConfig(history_path=explicit), run_repl=False)
        self.assertEqual(service._history_path(), explicit)  # noqa: SLF001

        class _Ctx:
            data_dir = Path(tmp.name) / "interface"

        service._ctx = _Ctx()  # noqa: SLF001
        self.assertEqual(service._history_path(), explicit)  # noqa: SLF001 -- still the override, not data_dir


def service_module_readline_available() -> bool:
    from simorgh.interface import service as service_module

    return service_module.readline is not None


class HttpEnabledWiringTestCase(unittest.IsolatedAsyncioTestCase):
    """`http_enabled` follows `run_repl` by default (the dashboard is for
    a human watching a `simorgh run` session, so it comes up exactly
    when the REPL does) unless a caller overrides it either way -- kept
    separate from `InterfaceTestCase` above so the other 28 tests there
    never each pay for a real bound socket they don't need."""

    def test_defaults_to_following_run_repl_true(self):
        service = Service(run_repl=True)
        self.assertTrue(service._http_enabled)  # noqa: SLF001

    def test_defaults_to_following_run_repl_false(self):
        service = Service(run_repl=False)
        self.assertFalse(service._http_enabled)  # noqa: SLF001

    def test_explicit_override_wins_over_run_repl(self):
        self.assertTrue(Service(run_repl=False, http_enabled=True)._http_enabled)  # noqa: SLF001
        self.assertFalse(Service(run_repl=True, http_enabled=False)._http_enabled)  # noqa: SLF001

    async def test_boot_with_http_enabled_actually_serves_the_dashboard(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        clock = FakeClock()
        ledger = make_ledger({"backend": "memory"}, clock=clock.now)
        await ledger.start()
        self.addAsyncCleanup(ledger.stop)
        backend = make_backend(BusConfig(backend="memory"), clock=clock.now)
        bus = make_client(backend, source="interface", ledger=ledger, clock=clock.now)
        await bus.start()
        self.addAsyncCleanup(bus.stop)

        ctx = Context(
            name="interface", instance_id="", run_id="test", mode="single",
            bus=bus, ledger=ledger, config={}, secrets={}, clock=clock,
            logger=_Logger(), data_dir=Path(tmp.name) / "data",
        )
        service = Service(InterfaceConfig(http_port=0), run_repl=False, http_enabled=True)
        await service.start(ctx)
        self.addAsyncCleanup(service.stop)

        self.assertIsNotNone(service._http)  # noqa: SLF001

        # Blocking socket I/O must run off the event loop -- the loop
        # itself has to keep running for the asyncio HTTP server to
        # accept and answer the connection.
        def _get() -> int:
            import http.client

            conn = http.client.HTTPConnection("127.0.0.1", service._http.port, timeout=5)  # noqa: SLF001
            conn.request("GET", "/")
            status = conn.getresponse().status
            conn.close()
            return status

        status = await asyncio.to_thread(_get)
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
