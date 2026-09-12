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
        # `narrate_autonomous=False` keeps this case's original
        # subject: narration of the turn *this* REPL is waiting on.
        # The new default (autonomous work narrated too) has its own
        # tests in test_activity.py.
        self.service = Service(
            InterfaceConfig(chat_reply_timeout_s=0.3, narrate_autonomous=False), run_repl=False,
        )
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

    async def test_benchmark_progress_is_narrated_one_line_per_case(self):
        """`benchmark run` prints "progress is narrated as it goes", and
        the benchmark service publishes `benchmark.progress` after every
        scored case -- to no subscriber at all, until 2026-09-10.
        Observer swe-01 watched a SWE-bench case get scored (142 tests
        passing in its container) through the terminal and saw nothing
        about it."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            await self.other.publish(self.other.new(topics.BENCHMARK_PROGRESS, {
                "run_id": "r1", "suite": "swebench-verified", "index": 1, "total": 2,
                "case_id": "astropy__astropy-14309", "level": "<15 min fix",
                "correct": 1, "attempted": 1, "elapsed_s": 612.0,
                "case_correct": True, "case_skipped": False, "case_seconds": 612.0, "case_error": "",
            }))
            await self._pump()
        text = out.getvalue()
        self.assertIn("benchmark 1/2", text)
        self.assertIn("astropy__astropy-14309", text)
        self.assertIn("resolved in 10m12s", text)
        self.assertIn("1/1 so far", text)

    async def test_a_voice_turn_shows_both_sides_on_the_console(self):
        """A spoken turn is not a typed line, so `_handle_chat` prints
        nothing for it and the reply resolves no pending turn. The
        creator, 2026-09-10, first evening with voice: "I don't see my
        recognized voice being typed in the console, also when sim talks
        I don't see the transcript." Both sides are on the bus."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            await self.other.publish(self.other.new(topics.VOICE_LISTENING, {"state": "listening", "device": "laptop"}))
            await self.other.publish(self.other.new(topics.VOICE_TRANSCRIPT, {
                "text": "turn on the kitchen lights", "confidence": 0.93, "seconds": 2.1,
                "engine": "whisper_cli:base.en", "device": "laptop"}))
            await self.other.publish(self.other.new(topics.VOICE_LISTENING, {"state": "idle", "device": "laptop"}))
            await self.other.publish(self.other.new(topics.VOICE_SPOKEN, {
                "text": "Kitchen lights are on.", "seconds": 1.4, "engine": "kokoro", "device": "laptop"}))
            await self._pump()
        text = out.getvalue()
        self.assertIn("listening", text)
        self.assertIn("you: turn on the kitchen lights", text)
        self.assertIn("93%", text)
        self.assertIn("sim: Kitchen lights are on.", text)
        self.assertEqual(text.count("listening"), 1, "the idle transition is not a line of its own")

    async def test_debug_level_notices_never_reach_the_human(self):
        """Live-caught: planning's own dedup bookkeeping ("duplicate
        candidate, matches task ...", `planning/service.py::_notice`)
        was printing straight into the chat transcript, interleaved with
        real replies -- a `debug`-level notice is internal telemetry,
        not something a person watching the REPL asked to see."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            await self.bus.publish(self.bus.new(
                topics.UI_NOTICE, {"level": "debug", "text": "duplicate candidate, matches task abc123", "source": "planning"},
            ))
            await self._pump()
        self.assertNotIn("duplicate candidate", out.getvalue())

    async def test_a_pending_prompt_is_answered_for_real_not_the_default(self):
        """Live-caught (the creator, real use: typed "yes" at a pending
        Guardian approval three separate times, worded three different
        ways, and each one was silently auto-answered "no" instead --
        `_on_prompt` used to print the question and *immediately*
        resolve it to `default` with no real window to answer). A typed
        line matching the prompt's own `options` now resolves it for
        real, bypassing dispatch/chat entirely.

        Calls `_on_prompt` directly rather than publish-then-pump: under
        `FakeClock`, the watchdog's own `clock.sleep(timeout_s)` resolves
        after a single tick regardless of `timeout_s`'s actual size (the
        fake clock's whole point is not to block wall-clock time), so
        any pump long enough to observe delivery is also long enough to
        let the watchdog "expire" the prompt first -- a test-environment
        race, not a real one (a real `Clock.sleep` genuinely waits).
        Calling the handler directly, then answering with no intervening
        `await`, proves the *answer path* deterministically; the
        watchdog's own real firing is covered separately below."""
        answers: list[dict] = []
        sub = await self.other.subscribe(topics.UI_PROMPT_ANSWERED, lambda m: answers.append(m.payload) or asyncio.sleep(0))
        await self.service._on_prompt(self.bus.new(topics.UI_PROMPT, {
            "prompt_id": "p1", "question": "Approve propose_mcp_server?",
            "options": ["yes", "no"], "timeout_s": 1800.0, "default": "no",
        }))
        out = await self._line("yes")
        await self._pump()
        await sub.unsubscribe()
        self.assertEqual(answers, [{"prompt_id": "p1", "answer": "yes"}])
        self.assertIn("answered 'yes'", out)

    async def test_a_bare_y_answers_a_yes_no_prompt(self):
        answers: list[dict] = []
        sub = await self.other.subscribe(topics.UI_PROMPT_ANSWERED, lambda m: answers.append(m.payload) or asyncio.sleep(0))
        await self.service._on_prompt(self.bus.new(topics.UI_PROMPT, {
            "prompt_id": "p2", "question": "Approve?", "options": ["yes", "no"], "timeout_s": 1800.0, "default": "no",
        }))
        await self._line("y")
        await self._pump()
        await sub.unsubscribe()
        self.assertEqual(answers, [{"prompt_id": "p2", "answer": "yes"}])

    async def test_a_line_that_doesnt_match_any_option_is_handled_normally(self):
        await self.bus.publish(self.bus.new(topics.UI_PROMPT, {
            "prompt_id": "p3", "question": "Approve?", "options": ["yes", "no"], "timeout_s": 1800.0, "default": "no",
        }))
        await self._pump()
        out = await self._line("status")  # a real command, not an answer -- must not be swallowed
        self.assertNotIn("answered", out)

    async def test_no_pending_prompt_means_a_bare_yes_is_ordinary_chat(self):
        out = await self._line("yes")
        self.assertNotIn("answered", out)

    async def test_the_watchdog_auto_answers_the_default_when_nobody_types_anything(self):
        answers: list[dict] = []
        sub = await self.other.subscribe(topics.UI_PROMPT_ANSWERED, lambda m: answers.append(m.payload) or asyncio.sleep(0))
        await self.bus.publish(self.bus.new(topics.UI_PROMPT, {
            "prompt_id": "p4", "question": "Approve?", "options": ["yes", "no"], "timeout_s": 0.05, "default": "no",
        }))
        await asyncio.sleep(0.15)
        await sub.unsubscribe()
        self.assertEqual(answers, [{"prompt_id": "p4", "answer": "no"}])

    async def test_pause_resume_exit_round_trip(self):
        """Flow 5: pause -> resume -> exit, all real `system.*` commands
        published by Interface (proven against a real bus; the full
        Kernel-lifecycle round trip is proven in
        tests/simorgh/integration/). `exit` absorbs `stop`/`quit`
        (07-post-cutover-review.md §3.8) -- it's the only command that
        both requests `system.stop` and leaves the REPL."""
        seen = []
        sub = await self.other.subscribe(topics.SYSTEM_PAUSE, lambda m: seen.append(m.type) or asyncio.sleep(0))
        sub2 = await self.other.subscribe(topics.SYSTEM_RESUME, lambda m: seen.append(m.type) or asyncio.sleep(0))
        sub3 = await self.other.subscribe(topics.SYSTEM_STOP, lambda m: seen.append(m.type) or asyncio.sleep(0))
        await self._line("pause")
        await self._line("resume")
        await self._line("exit")
        await self._pump()
        await sub.unsubscribe(); await sub2.unsubscribe(); await sub3.unsubscribe()
        self.assertEqual(seen, [topics.SYSTEM_PAUSE, topics.SYSTEM_RESUME, topics.SYSTEM_STOP])

    async def test_status_renders_a_real_reply(self):
        """07-post-cutover-review.md §3.8: `status` absorbs `vitals`/
        `budget`/`skills` into one panel -- health, posture, tools, and
        (2026-09-08, wiring `git_state`'s first real caller) git state,
        each answered by a separate real responder."""
        async def _status_responder(message: Message) -> None:
            await self.other.reply(message, type=topics.SYSTEM_STATUS_REPLY, payload={
                "state": "running", "mode": "single", "run_id": "test",
                "subsystems": [{"name": "kernel", "version": "0.1.0", "status": "ok"}],
                "uptime_seconds": 12.5,
            })

        async def _posture_responder(message: Message) -> None:
            await self.other.reply(message, type=topics.GUARDIAN_POSTURE_REPLY, payload={
                "mode": "guarded", "trust_score": 0.9, "tightened_by": [],
            })

        async def _world_responder(message: Message) -> None:
            if message.payload.get("what") == "git_state":
                await self.other.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload={
                    "facet": "git_state", "as_of": 0.0, "available": True, "branch": "main",
                    "head": "deadbeef12345678", "dirty": False, "changed_files": 0, "recent_commits": ["deadbee fix"],
                })
            else:
                await self.other.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload={
                    "facet": "tools", "as_of": 0.0, "tools": [{"name": "read_file"}],
                })

        subs = [
            await self.other.subscribe(topics.SYSTEM_STATUS_REQUEST, _status_responder),
            await self.other.subscribe(topics.GUARDIAN_POSTURE_REQUEST, _posture_responder),
            await self.other.subscribe(topics.WORLD_ENV_QUERY, _world_responder),
        ]
        out = await self._line("status")
        for sub in subs:
            await sub.unsubscribe()
        self.assertIn("running", out)
        self.assertIn("guarded", out)
        self.assertIn("git", out)
        self.assertIn("main @ deadbee", out)
        self.assertIn("clean", out)
        # The tool COUNT, not fifty names. The list was the longest
        # thing on the screen and the least read.
        self.assertIn("1 registered", out)
        self.assertNotIn("read_file", out)
        # A healthy subsystem is a glyph in the strip, not a line of its
        # own: fifteen lines saying "ok" is fifteen lines hiding the one
        # that does not.
        self.assertIn("1 ok", out)
        self.assertNotIn("kernel", out)

    async def test_status_git_piece_degrades_honestly_when_git_is_unavailable(self):
        async def _status_responder(message: Message) -> None:
            await self.other.reply(message, type=topics.SYSTEM_STATUS_REPLY, payload={
                "state": "running", "mode": "single", "run_id": "test", "subsystems": [], "uptime_seconds": 0.0,
            })

        async def _posture_responder(message: Message) -> None:
            await self.other.reply(message, type=topics.GUARDIAN_POSTURE_REPLY, payload={
                "mode": "guarded", "trust_score": 0.9, "tightened_by": [],
            })

        async def _world_responder(message: Message) -> None:
            if message.payload.get("what") == "git_state":
                await self.other.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload={
                    "facet": "git_state", "as_of": 0.0, "available": False,
                })
            else:
                await self.other.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload={
                    "facet": "tools", "as_of": 0.0, "tools": [],
                })

        subs = [
            await self.other.subscribe(topics.SYSTEM_STATUS_REQUEST, _status_responder),
            await self.other.subscribe(topics.GUARDIAN_POSTURE_REQUEST, _posture_responder),
            await self.other.subscribe(topics.WORLD_ENV_QUERY, _world_responder),
        ]
        out = await self._line("status")
        for sub in subs:
            await sub.unsubscribe()
        self.assertIn("no repository here", out)

    async def test_unwired_command_gives_an_honest_no_response(self):
        out = await self._line("research nothing will answer this")
        self.assertIn("no response", out)

    async def test_plain_chat_times_out_honestly_without_cognition(self):
        out = await self._line("hello there")
        self.assertIn("no reply within", out)

    async def test_pending_turn_is_narrated_live_and_other_tasks_stay_silent_when_asked(self):
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
            # An unrelated autonomous task. With `narrate_autonomous`
            # off (this service's config) it must stay silent; the
            # creator asked for the opposite default -- see
            # `test_autonomous_work_is_narrated_by_default`.
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

    async def test_a_dispatch_created_task_prints_its_real_completion(self):
        """Live-caught (the creator, real use): `improve web access`
        printed "task created: <id>" and then nothing -- the task really
        ran, stepped, and completed with a real `result_summary`, visible
        only by reading the Ledger directly. `_on_task_event` only ever
        narrated a `_pending_turns` chat turn; a `dispatch()`-created task
        (`plan`/`improve`/`research`/`tasks work`) was never registered
        anywhere it checked, so its `task.completed` fell on the floor.
        `Outcome.task_id` (set by `_request(..., watch=True)`) now lands
        in `_watched_tasks`, and this is the round trip end to end: the
        `improve` command's own `task created: ...` line prints first
        (synchronously, from `dispatch()`'s reply), then the task's real
        answer prints later once `task.completed` arrives -- unprompted,
        with nothing further typed into the REPL."""
        async def _responder(message: Message) -> None:
            await self.other.reply(message, type=topics.TASK_CREATE_REPLY, payload={
                "ok": True, "task_id": "wt1",
            })
            await asyncio.sleep(0)
            await self.other.publish(self.other.new(topics.TASK_STARTED, {"task_id": "wt1", "worker_id": "w1"}))
            await self.other.publish(self.other.new(topics.TASK_COMPLETED, {
                "task_id": "wt1", "result_summary": "here is the real answer", "artifacts": [],
                "verification_ref": "v1",
            }))

        sub = await self.other.subscribe(topics.TASK_CREATE, _responder)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            await self.service._handle_line("improve web access")
            # Bounded wait, not a fixed number of loop turns: under a
            # loaded machine (the loader's full gate, 2026-09-07) twenty
            # turns were not enough for the completion to be delivered.
            for _ in range(200):
                if "here is the real answer" in buf.getvalue():
                    break
                await asyncio.sleep(0.01)
        await sub.unsubscribe()
        out = buf.getvalue()
        self.assertIn("task created: wt1", out)
        self.assertIn("here is the real answer", out)
        self.assertNotIn("wt1", self.service._watched_tasks)  # cleaned up once printed

    async def test_a_deduplicated_task_create_says_so_and_is_not_watched(self):
        """The reply that used to print as "task created: <old id>"."""
        async def _responder(message: Message) -> None:
            await self.other.reply(message, type=topics.TASK_CREATE_REPLY, payload={
                "ok": True, "task_id": "old1", "deduplicated_against": "old1",
            })

        sub = await self.other.subscribe(topics.TASK_CREATE, _responder)
        out = await self._line("improve web access")
        await sub.unsubscribe()
        self.assertIn("not created", out)
        self.assertIn("old1", out)
        self.assertNotIn("task created", out)
        self.assertNotIn("old1", self.service._watched_tasks)

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
        self.assertNotIn("no reply within", out)

    async def test_status_reflects_recent_persona_state(self):
        """`vitals` folded into `status` (07-post-cutover-review.md
        §3.8) -- the vitals panel piece still updates from persona
        state, now inside the merged panel."""
        await self.bus.publish(self.bus.new(topics.PERSONA_STATE_CHANGED, {
            "valence": 0.4, "arousal": 0.1, "cognitive_load": 0.2, "source": "test",
            "previous": {"valence": 0.0, "arousal": 0.0, "cognitive_load": 0.0},
        }))
        await self._pump()
        out = await self._line("status")  # the other two panel pieces time out honestly with no responder here
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


class PostureSeedTestCase(unittest.IsolatedAsyncioTestCase):
    """Live-caught (observer, 2026-09-08): `VitalsCache.on_guardian_posture`
    only ever ran off `guardian.posture.changed`, which Guardian publishes
    only on an actual tighten/loosen -- never once at boot. A fresh,
    perfectly healthy, untightened boot therefore showed `posture:
    unknown` in the vitals line of `status`/`vitals` forever, right next
    to `status`'s *other* posture line (a live `guardian.posture.request`)
    correctly saying `guarded` -- the same panel contradicting itself.
    `Service.start` now fires one best-effort `guardian.posture.request`
    to seed the cache (fired, not awaited, same reasoning as
    `_seed_activity`: a missing Guardian must never hold `start()`)."""

    async def test_start_seeds_vitals_posture_from_a_live_guardian_query(self):
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
        guardian = make_client(backend, source="guardian", ledger=ledger, clock=clock.now)
        await guardian.start()
        self.addAsyncCleanup(guardian.stop)

        async def _posture_responder(message: Message) -> None:
            await guardian.reply(message, type=topics.GUARDIAN_POSTURE_REPLY, payload={
                "mode": "guarded", "trust_score": 1.0, "tightened_by": [],
            })

        # Subscribed before `start()`, exactly as Guardian (an earlier
        # boot layer, kernel/registry.py) is already up before Interface.
        posture_sub = await guardian.subscribe(topics.GUARDIAN_POSTURE_REQUEST, _posture_responder)
        self.addAsyncCleanup(posture_sub.unsubscribe)

        ctx = Context(
            name="interface", instance_id="", run_id="test", mode="single",
            bus=bus, ledger=ledger, config={}, secrets={}, clock=clock,
            logger=_Logger(), data_dir=Path(tmp.name) / "data",
        )
        service = Service(InterfaceConfig(), run_repl=False)
        await service.start(ctx)
        self.addAsyncCleanup(service.stop)

        self.assertEqual(service.vitals.snapshot().posture, "unknown")  # honest until the reply lands
        for _ in range(200):
            if service.vitals.snapshot().posture != "unknown":
                break
            await asyncio.sleep(0.01)
        self.assertEqual(service.vitals.snapshot().posture, "guarded")

    async def test_start_never_blocks_when_nobody_answers_the_posture_query(self):
        """No Guardian responder at all: `start()` must return promptly
        (fired, not awaited) and the cache must stay honestly `unknown`,
        never fabricate or hang."""
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
        service = Service(InterfaceConfig(), run_repl=False)
        loop = asyncio.get_running_loop()
        started = loop.time()
        await service.start(ctx)
        self.addAsyncCleanup(service.stop)
        self.assertLess(loop.time() - started, 1.0, "start() waited on the posture query instead of firing it")
        self.assertEqual(service.vitals.snapshot().posture, "unknown")


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
            ["input_requested:first", "printed:● reply to first",
             "input_requested:second", "printed:● reply to second"],
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


class LiveStatusIntegrationTestCase(unittest.IsolatedAsyncioTestCase):
    """`live_status="on"` forced explicitly (the real "auto" default
    always resolves False under a captured, non-tty stdout -- see
    `InterfaceTestCase`'s own class docstring and `live_status.py`'s
    `live_status_enabled`) -- proves `_on_task_event`/`_handle_chat`
    actually take the redraw-in-place branch, not just the unchanged
    fallback every other test in this file exercises."""

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
        self.service = Service(
            InterfaceConfig(chat_reply_timeout_s=0.3, live_status="on", narrate_heartbeat_s=1000.0),
            run_repl=False,
        )
        await self.service.start(self.ctx)
        self.other = make_client(self.backend, source="other", ledger=self.ledger, clock=self.clock.now)
        await self.other.start()

    async def asyncTearDown(self):
        await self.service.stop()
        await self.other.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _line(self, text: str) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            await self.service._handle_line(text)  # noqa: SLF001
        return buf.getvalue()

    async def _pump(self, n: int = 10) -> None:
        for _ in range(n):
            await asyncio.sleep(0)

    async def test_a_pending_chat_turn_renders_a_footer_not_a_scrolling_line(self):
        async def _responder(message):
            sid = message.payload["session_id"]
            await self.other.publish(self.other.new(topics.TASK_STARTED, {"task_id": sid, "worker_id": "w1"}))
            await asyncio.sleep(0)
            await self.other.publish(self.other.new(topics.TURN_COMPLETED, {
                "session_id": sid, "task_id": sid, "text": "the reply", "floor": False, "tool_steps": 0,
            }))

        sub = await self.other.subscribe(topics.PERCEPT_TEXT_RECEIVED, _responder)
        out = await self._line("hello")
        await sub.unsubscribe()
        # The footer's own escape sequences must appear (proof the live
        # branch really ran)...
        self.assertIn("\x1b[2K", out)
        self.assertIn("Thinking", out)
        # ...but the old scrolling "... thinking... [Ns]" dim line must not.
        self.assertNotIn("... thinking...", out)
        self.assertIn("the reply", out)

    async def test_a_completed_step_folds_into_one_permanent_iconed_line(self):
        async def _responder(message):
            sid = message.payload["session_id"]
            await self.other.publish(self.other.new(topics.TASK_STEP, {
                "task_id": sid, "step_no": 1, "phase": "act", "summary": "read docs/SOUL.md",
                "tool": "read_file", "ok": True,
            }))
            await asyncio.sleep(0)
            await self.other.publish(self.other.new(topics.TURN_COMPLETED, {
                "session_id": sid, "task_id": sid, "text": "done", "floor": False, "tool_steps": 1,
            }))

        sub = await self.other.subscribe(topics.PERCEPT_TEXT_RECEIVED, _responder)
        out = await self._line("what does SOUL.md say?")
        await sub.unsubscribe()
        # One branch of the task's tree (`panel.py`): the tool, what it
        # touched, and the outcome mark -- ASCII here because tests run
        # with unicode off.
        self.assertIn("* read_file(read docs/SOUL.md)", out)
        self.assertRegex(out, r"read docs/SOUL.md\)\s+ok")
        self.assertNotIn("step 1 (act)", out)

    async def test_a_failed_step_folds_into_a_permanent_line_with_the_failure_icon(self):
        async def _responder(message):
            sid = message.payload["session_id"]
            await self.other.publish(self.other.new(topics.TASK_STEP, {
                "task_id": sid, "step_no": 1, "phase": "act", "summary": "denied: nope",
                "tool": "propose_mcp_server", "ok": False,
            }))
            await asyncio.sleep(0)
            await self.other.publish(self.other.new(topics.TURN_COMPLETED, {
                "session_id": sid, "task_id": sid, "text": "done", "floor": False, "tool_steps": 1,
            }))

        sub = await self.other.subscribe(topics.PERCEPT_TEXT_RECEIVED, _responder)
        out = await self._line("propose something")
        await sub.unsubscribe()
        self.assertIn("* propose_mcp_server(denied: nope)", out)
        self.assertRegex(out, r"denied: nope\)\s+FAILED")

    async def test_an_in_flight_step_updates_the_footer_with_a_breathing_verb(self):
        async def _responder(message):
            sid = message.payload["session_id"]
            await self.other.publish(self.other.new(topics.TASK_STEP, {
                "task_id": sid, "step_no": 1, "phase": "act", "summary": "",
                "tool": "read_file",
                # no "ok" key at all -- an in-flight/announced step, not a completed one
            }))
            await asyncio.sleep(0)
            await self.other.publish(self.other.new(topics.TURN_COMPLETED, {
                "session_id": sid, "task_id": sid, "text": "done", "floor": False, "tool_steps": 1,
            }))

        sub = await self.other.subscribe(topics.PERCEPT_TEXT_RECEIVED, _responder)
        out = await self._line("read something")
        await sub.unsubscribe()
        self.assertIn("Reading", out)  # verb_for("act", "read_file")
        self.assertNotIn("step 1", out)  # never folded into a permanent line -- no "ok" means no outcome yet

    async def test_a_notice_clears_and_restores_the_footer_around_itself(self):
        async def _responder(message):
            sid = message.payload["session_id"]
            await self.other.publish(self.other.new(topics.TASK_STARTED, {"task_id": sid, "worker_id": "w1"}))
            await asyncio.sleep(0)
            await self.other.publish(self.other.new(topics.UI_NOTICE, {
                "level": "info", "text": "a real notice", "source": "test",
            }))
            await asyncio.sleep(0)
            await self.other.publish(self.other.new(topics.TURN_COMPLETED, {
                "session_id": sid, "task_id": sid, "text": "done", "floor": False, "tool_steps": 0,
            }))

        sub = await self.other.subscribe(topics.PERCEPT_TEXT_RECEIVED, _responder)
        out = await self._line("hello")
        await sub.unsubscribe()
        self.assertIn("a real notice", out)
        self.assertIn("Thinking", out)  # the footer reappears after the notice


if __name__ == "__main__":
    unittest.main()


class ApiTokenWiringTestCase(unittest.IsolatedAsyncioTestCase):
    """The seam between `SIM_API_TOKEN` in the Context and the gate in
    `HttpApi` -- the half of a feature that is usually left unconnected
    (a designed slot, one side implemented, nobody writes it). Asserted
    end to end over a real socket, because that is the only thing that
    proves the token actually arrived."""

    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(backend, source="interface", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()
        self.warnings: list = []

    async def asyncTearDown(self):
        await self.service.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _start(self, *, secrets: dict, host: str = "127.0.0.1"):
        recorder = self

        class _RecordingLogger(_Logger):
            def warning(self, event, **fields):
                recorder.warnings.append((event, fields))

        ctx = Context(
            name="interface", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets=secrets, clock=self.clock,
            logger=_RecordingLogger(), data_dir=Path(self._tmp.name) / "data",
        )
        self.service = Service(
            InterfaceConfig(http_host=host, http_port=0, narrate_autonomous=False),
            run_repl=False, http_enabled=True,
        )
        await self.service.start(ctx)
        return self.service._http

    async def _status_of(self, api, path: str, token: str | None = None) -> int:
        import http.client

        headers = {"Authorization": "Bearer " + token} if token else {}

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            resp.read()
            conn.close()
            return resp.status

        return await asyncio.to_thread(_do)

    async def test_the_token_from_the_context_actually_gates_the_server(self):
        api = await self._start(secrets={"SIM_API_TOKEN": "from-the-vault"})
        self.assertTrue(api.requires_token)
        self.assertEqual(await self._status_of(api, "/api/streams"), 401)
        self.assertEqual(await self._status_of(api, "/api/streams", "from-the-vault"), 200)

    async def test_no_token_leaves_the_local_dashboard_exactly_as_it_was(self):
        api = await self._start(secrets={})
        self.assertFalse(api.requires_token)
        self.assertEqual(await self._status_of(api, "/api/streams"), 200)

    async def test_an_off_loopback_bind_with_no_token_warns_and_still_starts(self):
        api = await self._start(secrets={}, host="0.0.0.0")
        self.assertEqual(await self._status_of(api, "/api/status"), 200)
        events = [event for event, _ in self.warnings]
        self.assertIn("http_api_unauthenticated", events)

    async def test_an_off_loopback_bind_with_a_token_does_not_warn(self):
        await self._start(secrets={"SIM_API_TOKEN": "t"}, host="0.0.0.0")
        self.assertNotIn("http_api_unauthenticated", [event for event, _ in self.warnings])
