"""`interface.dispatch`'s `mcp` command: the human half of "propose a
server, one human approval" (`execution/tools.py::ProposeMcpServerTool`'s
own docstring has the full design). Real (memory-backend) Bus/Ledger, a
real `dispatch()` call -- `_SIMORGH_TOML_PATH` is patched to a temp file
for `approve` so this test never touches the real repo's own
`simorgh.toml`."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Event
from simorgh.interface import dispatch as dispatch_module
from simorgh.interface.dispatch import dispatch
from simorgh.interface.parser import Command
from simorgh.interface.vitals import VitalsCache
from simorgh.ledger.factory import make_ledger

from tests.simorgh.helpers import FakeClock


class _McpDispatchTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(self.backend, source="interface", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()
        self.vitals = VitalsCache()
        self.other = make_client(self.backend, source="other", ledger=self.ledger, clock=self.clock.now)
        await self.other.start()

        async def _answer_tools(message) -> None:
            await self.other.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload={
                "facet": "tools", "as_of": self.clock.now(), "tools": [],
            })

        self._tools_sub = await self.other.subscribe(topics.WORLD_ENV_QUERY, _answer_tools)

    async def asyncTearDown(self):
        await self._tools_sub.unsubscribe()
        await self.other.stop()
        await self.bus.stop()
        await self.ledger.stop()

    async def _append_proposal(self, **overrides) -> str:
        payload = {
            "proposal_id": "abc123", "name": "ddg_search", "command": "npx",
            "args": ["-y", "ddg-search-mcp"], "read_only_tools": ["ddg_search"],
            "env_keys": [], "reason": "free web search, no API key", "status": "pending",
        }
        payload.update(overrides)
        await self.ledger.append(dispatch_module.MCP_PROPOSALS_STREAM, Event(
            stream=dispatch_module.MCP_PROPOSALS_STREAM, type="proposed", ts=self.clock.now(),
            trace_id="", causation_id=None, payload=payload,
        ))
        return payload["proposal_id"]

    async def _mcp(self, args: str) -> str:
        outcome = await dispatch(
            Command(name="mcp", args=args, raw=f"mcp {args}"),
            bus=self.bus, clock=self.clock, session_id="s1", vitals=self.vitals, ledger=self.ledger,
        )
        return outcome.text


class TestMcpBareList(_McpDispatchTestCase):
    async def test_no_pending_proposals_says_so(self):
        out = await self._mcp("")
        self.assertIn("no pending", out)

    async def test_lists_a_pending_proposal_with_its_reason(self):
        await self._append_proposal()
        out = await self._mcp("")
        self.assertIn("abc123", out)
        self.assertIn("ddg_search", out)
        self.assertIn("free web search, no API key", out)
        self.assertIn("npx -y ddg-search-mcp", out)

    async def test_an_approved_proposal_no_longer_appears_as_pending(self):
        await self._append_proposal(status="approved")
        out = await self._mcp("")
        self.assertIn("no pending", out)

    async def test_a_later_event_for_the_same_id_supersedes_the_earlier_one(self):
        await self._append_proposal()
        await self._append_proposal(status="rejected")
        out = await self._mcp("")
        self.assertIn("no pending", out)


class TestMcpApprove(_McpDispatchTestCase):
    async def test_usage_message_without_an_id(self):
        out = await self._mcp("approve")
        self.assertIn("usage", out)

    async def test_unknown_id_is_a_clear_error(self):
        out = await self._mcp("approve nope")
        self.assertIn("no pending proposal", out)

    async def test_approve_writes_a_real_toml_block_and_marks_approved(self):
        await self._append_proposal()
        with tempfile.TemporaryDirectory() as tmp:
            toml_path = Path(tmp) / "simorgh.toml"
            with unittest.mock.patch.object(dispatch_module, "_SIMORGH_TOML_PATH", toml_path):
                out = await self._mcp("approve abc123")
            self.assertIn("approved", out)
            self.assertIn("restart", out)
            content = toml_path.read_text()
        self.assertIn("[[execution.mcp_servers]]", content)
        self.assertIn('name = "ddg_search"', content)
        self.assertIn('command = "npx"', content)
        self.assertIn('args = ["-y", "ddg-search-mcp"]', content)
        pending_out = await self._mcp("")
        self.assertIn("no pending", pending_out)

    async def test_approve_appends_without_disturbing_existing_content(self):
        await self._append_proposal()
        with tempfile.TemporaryDirectory() as tmp:
            toml_path = Path(tmp) / "simorgh.toml"
            toml_path.write_text('[runtime]\nmode = "single"  # a human comment\n')
            with unittest.mock.patch.object(dispatch_module, "_SIMORGH_TOML_PATH", toml_path):
                await self._mcp("approve abc123")
            content = toml_path.read_text()
        self.assertIn('mode = "single"  # a human comment', content)
        self.assertIn("[[execution.mcp_servers]]", content)

    async def test_env_keys_are_noted_as_names_never_written_as_values(self):
        await self._append_proposal(env_keys=["BRAVE_API_KEY"])
        with tempfile.TemporaryDirectory() as tmp:
            toml_path = Path(tmp) / "simorgh.toml"
            with unittest.mock.patch.object(dispatch_module, "_SIMORGH_TOML_PATH", toml_path):
                await self._mcp("approve abc123")
            content = toml_path.read_text()
        self.assertIn("BRAVE_API_KEY", content)
        self.assertNotIn("env =", content)  # noted in a comment, no env table Sim could have filled in

    async def test_approving_twice_the_second_time_is_an_unknown_id(self):
        await self._append_proposal()
        with tempfile.TemporaryDirectory() as tmp:
            toml_path = Path(tmp) / "simorgh.toml"
            with unittest.mock.patch.object(dispatch_module, "_SIMORGH_TOML_PATH", toml_path):
                await self._mcp("approve abc123")
                second = await self._mcp("approve abc123")
        self.assertIn("no pending proposal", second)


class TestMcpReject(_McpDispatchTestCase):
    async def test_usage_message_without_an_id(self):
        out = await self._mcp("reject")
        self.assertIn("usage", out)

    async def test_reject_marks_it_no_longer_pending_and_never_touches_toml(self):
        await self._append_proposal()
        with tempfile.TemporaryDirectory() as tmp:
            toml_path = Path(tmp) / "simorgh.toml"
            with unittest.mock.patch.object(dispatch_module, "_SIMORGH_TOML_PATH", toml_path):
                out = await self._mcp("reject abc123 too risky")
            self.assertFalse(toml_path.exists())
        self.assertIn("rejected", out)
        self.assertIn("ddg_search", out)
        pending_out = await self._mcp("")
        self.assertIn("no pending", pending_out)


class TestCancel(_McpDispatchTestCase):
    """`cancel` used to publish `TASK_CANCEL` and unconditionally claim
    "asked X to stop" -- true only when the id happened to name a live
    task. Planning's `_on_task_cancel` silently no-ops on an unknown or
    already-terminal id, so a typo or a stale id from an old `tasks`
    listing was told a cancellation was in flight that never happened
    (observer, 2026-09-08). `cancel` now looks the task up via
    `TASK_LIST_REQUEST` first and only claims what will actually
    happen."""

    async def _answer_task_list(self, tasks: list[dict]) -> None:
        async def _reply(message) -> None:
            await self.other.reply(message, type=topics.TASK_LIST_REPLY,
                                    payload={"tasks": tasks, "projects": []})

        self._task_list_sub = await self.other.subscribe(topics.TASK_LIST_REQUEST, _reply)

    async def _cancel(self, args: str) -> str:
        outcome = await dispatch(
            Command(name="cancel", args=args, raw=f"cancel {args}"),
            bus=self.bus, clock=self.clock, session_id="s1", vitals=self.vitals, ledger=self.ledger,
        )
        return outcome.text

    async def test_no_task_id_is_a_usage_message(self):
        out = await self._cancel("")
        self.assertIn("usage", out)

    async def test_whitespace_only_is_a_usage_message(self):
        out = await self._cancel("   ")
        self.assertIn("usage", out)

    async def test_surrounding_whitespace_around_a_real_id_is_stripped(self):
        await self._answer_task_list([{"task_id": "t1", "status": "available"}])
        out = await self._cancel("  t1  ")
        self.assertIn("asked t1 to stop", out)

    async def test_an_unknown_task_id_is_told_honestly_not_a_false_success(self):
        await self._answer_task_list([{"task_id": "other", "status": "available"}])
        out = await self._cancel("nope-does-not-exist")
        self.assertIn("no such task", out)
        self.assertNotIn("asked", out)

    async def test_an_already_terminal_task_is_told_honestly_not_a_false_success(self):
        await self._answer_task_list([{"task_id": "t1", "status": "completed"}])
        out = await self._cancel("t1")
        self.assertIn("already completed", out)
        self.assertNotIn("asked", out)

    async def test_a_live_task_gets_the_real_stop_message_and_a_real_publish(self):
        await self._answer_task_list([{"task_id": "t1", "status": "in_progress"}])
        seen = []

        async def _watch(message) -> None:
            seen.append(message.payload)

        sub = await self.other.subscribe(topics.TASK_CANCEL, _watch)
        try:
            out = await self._cancel("t1")
            await asyncio.sleep(0.05)  # memory bus delivery is async
        finally:
            await sub.unsubscribe()
        self.assertIn("asked t1 to stop", out)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["task_id"], "t1")


if __name__ == "__main__":
    unittest.main()


class StepsOptionTestCase(unittest.TestCase):
    """`steps=N` anywhere in an improve/plan/research line becomes the
    task's own step cap; the rest of the line is the description."""

    def test_pops_the_option_wherever_it_is(self):
        pop = dispatch_module._pop_steps  # noqa: SLF001
        self.assertEqual(pop("simorgh/x.py add a constant steps=40"), ("simorgh/x.py add a constant", 40))
        self.assertEqual(pop("steps=12 web access"), ("web access", 12))
        self.assertEqual(pop("what does memory export"), ("what does memory export", None))

    def test_a_lookalike_inside_a_word_is_left_alone(self):
        pop = dispatch_module._pop_steps  # noqa: SLF001
        self.assertEqual(pop("count footsteps=3 things"), ("count footsteps=3 things", None))

    def test_it_lands_in_the_payload_only_when_given(self):
        self.assertEqual(dispatch_module._with_steps({"kind": "patch"}, 40), {"kind": "patch", "max_steps": 40})  # noqa: SLF001
        self.assertEqual(dispatch_module._with_steps({"kind": "patch"}, None), {"kind": "patch"})  # noqa: SLF001


class VoiceSetSpellingsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_key_equals_value_is_the_same_ask(self):
        from simorgh.interface import dispatch as dispatch_mod

        seen = []

        async def _request(bus, topic, payload, **kw):
            seen.append(payload)
            return dispatch_mod.Outcome("ok")
        original = dispatch_mod._request
        dispatch_mod._request = _request
        try:
            for spelling in ("tts_voice af_kore", "tts_voice = af_kore", "tts_voice=af_kore"):
                await dispatch_mod._voice(None, f"set {spelling}")
        finally:
            dispatch_mod._request = original
        self.assertEqual(seen, [{"action": "set", "key": "tts_voice", "value": "af_kore"}] * 3)

    def test_a_refused_setting_shows_its_reason(self):
        from simorgh.interface.voiceview import controlled
        out = controlled({"ok": False, "error": {"code": "refused", "detail": "did you mean tts_voice?", "retryable": False}})
        self.assertIn("did you mean tts_voice?", out)


class _Clock:
    def now(self) -> float:
        return 0.0


class TasksClearTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_clear_and_its_aliases_ask_planning_to_wipe_the_backlog(self):
        from simorgh.interface import dispatch as dispatch_mod

        seen = []

        async def _request(bus, topic, payload, **kw):
            seen.append((topic, payload))
            return dispatch_mod.Outcome(kw["render"]({"cleared": 56, "cancelled": 2}))
        original = dispatch_mod._request
        dispatch_mod._request = _request
        try:
            from simorgh.interface.parser import parse
            for word in ("clear", "clean", "erase"):
                out = await dispatch_mod.dispatch(parse(f"tasks {word}"), bus=None, clock=_Clock(), session_id="s1",
                                                  vitals=None, ledger=None)
                self.assertIn("cleared 56 task(s); 2 running were told to stop", out.text)
        finally:
            dispatch_mod._request = original
        self.assertTrue(all(topic == topics.TASK_CLEAR_REQUEST for topic, _p in seen))
        self.assertEqual(len(seen), 3)


class TvCommandTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_every_verb_is_a_cast_tool_call(self):
        from simorgh.interface import dispatch as dispatch_mod
        from simorgh.interface.parser import parse
        import json as _json

        calls = []

        async def _run_tool(*, bus, ledger, tool, raw, session_id, timeout=300.0):
            calls.append((tool, _json.loads(raw)))
            return dispatch_mod.Outcome("ok")
        original = dispatch_mod._run_tool
        dispatch_mod._run_tool = _run_tool
        try:
            for line in ("tv setup", "tv devices", "tv use Living Room TV", "tv show", "tv show Bedroom", "tv", "tv video https://x/clip.mp4",
                         "tv video https://x/clip.mp4 full Living Room TV", "tv stop", "tv stop frame", "tv volume 35",
                         "tv show dash", "tv dash", "tv show tv", "tv view markets 1W amd", "tv rotate 45", "tv rotate off", "tv remote"):
                await dispatch_mod.dispatch(parse(line), bus=None, clock=_Clock(), session_id="s1", vitals=None,
                                            ledger=None)
        finally:
            dispatch_mod._run_tool = original
        self.assertEqual(calls, [
            ("cast_setup", {}), ("cast_devices", {}), ("cast_use", {"device": "Living Room TV"}), ("cast_show", {}),
            ("cast_show", {"device": "Bedroom"}), ("cast_show", {}),
            ("cast_play", {"url": "https://x/clip.mp4", "mode": "frame"}),
            ("cast_play", {"url": "https://x/clip.mp4", "mode": "full", "device": "Living Room TV"}),
            ("cast_stop", {}), ("cast_stop", {"what": "frame"}), ("cast_volume", {"level": 35.0}),
            ("cast_show", {"page": "dash"}), ("cast_show", {"page": "dash"}), ("cast_show", {"page": "tv"}),
            ("dash_view", {"view": "markets", "timeframe": "1W", "symbol": "AMD"}),
            ("dash_view", {"rotate_s": 45.0}), ("dash_view", {"rotate_s": 0.0}), ("dash_view", {"action": "remote"}),
        ])


class RingCommandTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_every_verb_is_a_ring_tool_call(self):
        from simorgh.interface import dispatch as dispatch_mod
        from simorgh.interface.parser import parse
        import json as _json

        calls = []

        async def _run_tool(*, bus, ledger, tool, raw, session_id, timeout=300.0):
            calls.append((tool, _json.loads(raw)))
            return dispatch_mod.Outcome("ok")
        original = dispatch_mod._run_tool
        dispatch_mod._run_tool = _run_tool
        try:
            for line in ("ring", "ring list", "ring snapshot", "ring snapshot front door", "ring events", "ring events back yard 5",
                         "ring light back yard on", "ring siren back yard 15", "ring watch", "ring watch off", "ring watch on 60",
                         "ring setup a@b.c pw", "ring setup a@b.c pw 123456"):
                await dispatch_mod.dispatch(parse(line), bus=None, clock=_Clock(), session_id="s1", vitals=None, ledger=None)
        finally:
            dispatch_mod._run_tool = original
        self.assertEqual(calls, [
            ("ring_list", {}), ("ring_list", {}), ("ring_snapshot", {"camera": "all"}), ("ring_snapshot", {"camera": "front door"}),
            ("ring_events", {}), ("ring_events", {"camera": "back yard", "limit": 5}),
            ("ring_light", {"camera": "back yard", "on": True}), ("ring_siren", {"camera": "back yard", "seconds": 15}),
            ("ring_watch", {"on": True}), ("ring_watch", {"on": False}), ("ring_watch", {"on": True, "every_s": 60.0}),
            ("ring_setup", {"email": "a@b.c", "password": "pw"}), ("ring_setup", {"email": "a@b.c", "password": "pw", "code": "123456"}),
        ])


class CamerasCommandTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_every_verb_is_a_camera_tool_call(self):
        from simorgh.interface import dispatch as dispatch_mod
        from simorgh.interface.parser import parse
        import json as _json

        calls = []

        async def _run_tool(*, bus, ledger, tool, raw, session_id, timeout=300.0):
            calls.append((tool, _json.loads(raw)))
            return dispatch_mod.Outcome("ok")
        original = dispatch_mod._run_tool
        dispatch_mod._run_tool = _run_tool
        try:
            for line in ("cameras", "cameras show office", "cameras show front, office grid", "cameras show all",
                         "cameras show pool full", "cameras show stop", "cameras light office on", "cameras siren pool 5",
                         "cameras ptz office preset 2", "cameras recordings front yesterday", "cameras watch off"):
                await dispatch_mod.dispatch(parse(line), bus=None, clock=_Clock(), session_id="s1", vitals=None, ledger=None)
        finally:
            dispatch_mod._run_tool = original
        self.assertEqual(calls, [
            ("cam_list", {}), ("cam_stream", {"camera": "office", "mode": "frame"}),
            ("cam_stream", {"camera": "front, office", "mode": "grid"}), ("cam_stream", {"camera": "all", "mode": "frame"}),
            ("cam_stream", {"camera": "pool", "mode": "full"}), ("cam_stream", {"camera": "all", "mode": "stop"}),
            ("cam_light", {"camera": "office", "on": True}), ("cam_siren", {"camera": "pool", "seconds": 5}),
            ("cam_ptz", {"camera": "office", "command": "preset", "preset": 2}),
            ("cam_recordings", {"camera": "front", "period": "yesterday"}), ("cam_watch", {"on": False}),
        ])
