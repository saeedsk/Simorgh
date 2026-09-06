"""Interface Service over a real (memory-backend) Bus/Ledger and Context
(see tests/simorgh/worldmodel/test_service.py for the pattern rationale).
`run_repl=False` here -- the REPL thread itself (readline/stdin) is
exercised by `_handle_line` directly instead, so these tests don't
depend on a tty or piped stdin."""

import asyncio
import contextlib
import io
import tempfile
import unittest
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
        fixed `self.session_id`, not a fresh id per turn -- sending a
        second message before the first one's reply arrived (exactly
        what the real REPL thread does: it never waits for one line's
        reply before reading the next) silently overwrote the first
        call's dict entry, so whichever turn.completed happened to land
        first resolved the *second* call's future regardless of content,
        and the first call's own future was orphaned until it timed out
        with a false "no response". Reproduced here without any real
        timing race: both `_handle_line` calls are fired concurrently,
        just like the REPL thread fires them, before either's percept is
        answered."""
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
