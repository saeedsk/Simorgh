"""Execution's own tool calls go through the action path (stage 1 item 7, S12).

The Ring and NVR watches and the TV dashboard at boot, the charts
autoplay, and the camera watcher's list and snapshot calls each used to
call `tool.run(...)` straight from the registry: a made-up action id, no
proposal, no Guardian decision, no token and no `action:` stream. Now
each one publishes `action.proposed` with `proposed_by="execution"` and
runs only when Guardian approves, through `Service._on_approved` like any
other approved action. A denial is logged and leaves the feature off.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ToolResult
from tests.simorgh.execution.test_service import _ExecutionServiceTestCase

_EXECUTION = Path(__file__).resolve().parents[3] / "simorgh" / "execution"


class _Tool:
    def __init__(self, name, *, reversibility="reversible", metadata=None, output="done") -> None:
        self.name = name
        self.reversibility = reversibility
        self.read_only = reversibility == "read_only"
        self.description = name
        self.args_schema = {}
        self.calls: list[tuple[dict, str]] = []
        self._metadata = metadata or {}
        self._output = output

    async def run(self, args, *, ctx):
        self.calls.append((dict(args), ctx.action_id))
        return ToolResult(ok=True, output=self._output, metadata=dict(self._metadata))


class _Logger:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, dict]] = []

    def debug(self, event, **f): self.lines.append(("debug", event, f))
    def info(self, event, **f): self.lines.append(("info", event, f))
    def warning(self, event, **f): self.lines.append(("warning", event, f))
    def error(self, event, **f): self.lines.append(("error", event, f))

    def events(self, level):
        return [event for lvl, event, _f in self.lines if lvl == level]


class _Case(_ExecutionServiceTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.logger = _Logger()
        import dataclasses

        self.ctx = dataclasses.replace(self.ctx, logger=self.logger)
        self.ctx.secrets["RING_TOKEN"] = '{"access_token": "x"}'


class TestTheBootWatchIsProposed(_Case):
    async def test_an_approved_watch_start_is_proposed_by_execution_and_runs_through_on_approved(self):
        await self._start()
        guardian = await self._guardian(approve=True)
        watch = _Tool("ring_watch", output="watching 2 Ring camera(s)")
        self.service._registry["ring_watch"] = watch  # noqa: SLF001

        ran = self.service._on_approved  # noqa: SLF001
        through: list[str] = []

        async def _spy(message: Message) -> None:
            through.append(message.payload["action_id"])
            await ran(message)

        self.service._on_approved = _spy  # noqa: SLF001 -- the subscription holds the bound method
        await self.service._subs[0].unsubscribe()  # noqa: SLF001
        self.service._subs[0] = await self.bus.subscribe(  # noqa: SLF001
            topics.ACTION_APPROVED, _spy, group="execution")

        self.assertTrue(await self.service._autostart_ring_watch(delay_s=0))  # noqa: SLF001

        self.assertEqual(len(guardian.proposals), 1)
        proposal = guardian.proposals[0]
        self.assertEqual(proposal["proposed_by"], "execution")
        self.assertEqual(proposal["tool"], "ring_watch")
        self.assertEqual(proposal["args"], {"on": True})
        self.assertEqual(through, [proposal["action_id"]], "it ran through _on_approved")
        self.assertEqual(watch.calls, [({"on": True}, proposal["action_id"])],
                         "the tool ran once, under the proposal's own action id")
        stream = [e.type for e in await self.ledger.read(f"action:{proposal['action_id']}")]
        self.assertIn("received", stream)
        self.assertIn("verified", stream, "Execution verified the token before running")
        self.assertIn("ring_watch_autostart", self.logger.events("info"))

    async def test_cam_watch_and_tv_show_are_proposed_too(self):
        import dataclasses

        await self._start()
        guardian = await self._guardian(approve=True)
        cam, show = _Tool("cam_watch"), _Tool("cast_show")
        self.service._registry.update({"cam_watch": cam, "cast_show": show})  # noqa: SLF001
        self.service._config = dataclasses.replace(  # noqa: SLF001
            self.service._config, cast_device="Family Room TV", tv_show_on_start=True)  # noqa: SLF001
        self.assertTrue(await self.service._autostart_cam_watch(delay_s=0))  # noqa: SLF001
        self.assertTrue(await self.service._autostart_tv_show(delay_s=0))  # noqa: SLF001
        self.assertEqual([p["tool"] for p in guardian.proposals], ["cam_watch", "cast_show"])
        self.assertTrue(all(p["proposed_by"] == "execution" for p in guardian.proposals))
        self.assertEqual(len(cam.calls), 1)
        self.assertEqual(len(show.calls), 1)

    async def test_the_charts_autoplay_is_proposed(self):
        await self._start()
        guardian = await self._guardian(approve=True)
        charts = _Tool("tv_charts")
        self.service._registry["tv_charts"] = charts  # noqa: SLF001
        await self.service._on_dash_state(Message.new(  # noqa: SLF001
            topics.DASH_STATE, source="interface", payload={"view": "charts", "chart": "billboard"}))
        for _ in range(200):
            if charts.calls:
                break
            await asyncio.sleep(0.01)
        self.assertEqual([p["tool"] for p in guardian.proposals], ["tv_charts"])
        self.assertEqual(charts.calls[0][0], {"chart": "billboard"})


class TestADeniedWatchStaysOff(_Case):
    async def test_a_denied_watch_start_runs_nothing_and_is_logged(self):
        await self._start()
        guardian = await self._guardian(approve=False)
        watch = _Tool("ring_watch")
        self.service._registry["ring_watch"] = watch  # noqa: SLF001

        self.assertFalse(await self.service._autostart_ring_watch(delay_s=0))  # noqa: SLF001

        self.assertEqual(len(guardian.proposals), 1, "it was asked")
        self.assertEqual(watch.calls, [], "and nothing ran")
        self.assertIn("ring_watch_autostart_denied", self.logger.events("warning"))
        self.assertNotIn("ring_watch_autostart", self.logger.events("info"))

    async def test_a_denied_snapshot_gives_the_watcher_no_stills(self):
        await self._start()
        await self._guardian(approve=False)
        snap = _Tool("cam_snapshot", metadata={"path": "workspace/cameras/front-1.jpg"})
        self.service._registry["cam_snapshot"] = snap  # noqa: SLF001
        stills = await self.service._vision._stills({"host": ""}, "Front")  # noqa: SLF001
        self.assertEqual(stills, [])
        self.assertEqual(snap.calls, [])


class TestTheCameraWatcherGetsItsResultBack(_Case):
    async def test_list_and_snapshot_metadata_come_back_through_action_result(self):
        import dataclasses

        await self._start()
        self.service._config = dataclasses.replace(self.service._config, camera_vision_gap_s=0.0)  # noqa: SLF001
        self.service._vision._config = self.service._config  # noqa: SLF001
        guardian = await self._guardian(approve=True)
        listing = _Tool("cam_list", reversibility="read_only", metadata={"cameras": ["Front", "Garden"]})
        snap = _Tool("cam_snapshot", metadata={"path": "workspace/cameras/front-1.jpg"})
        self.service._registry.update({"cam_list": listing, "cam_snapshot": snap})  # noqa: SLF001
        self.service._registry.pop("ring_list", None)  # noqa: SLF001 -- no Ring cloud in a test

        unlearned = await self.service._vision._unlearned()  # noqa: SLF001
        self.assertEqual(sorted(unlearned), [("Front", ""), ("Garden", "")])
        stills = await self.service._vision._stills({"host": ""}, "Front")  # noqa: SLF001
        self.assertTrue(stills)
        self.assertTrue(all(s.endswith("workspace/cameras/front-1.jpg") for s in stills))
        self.assertEqual({p["tool"] for p in guardian.proposals}, {"cam_list", "cam_snapshot"})
        self.assertTrue(all(p["proposed_by"] == "execution" for p in guardian.proposals))


def _parents(tree: ast.AST) -> dict:
    out = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def _enclosing(node, parents):
    """`(class name or None, function name or None)` of the nearest def."""
    func = cls = None
    cur = parents.get(node)
    while cur is not None:
        if func is None and isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = cur.name
        if isinstance(cur, ast.ClassDef):
            cls = cur.name
            break
        cur = parents.get(cur)
    return cls, func


def direct_tool_runs() -> list[str]:
    """Every place in `simorgh/execution/` that runs a tool, or mints the
    `ToolContext` a run needs, anywhere but:

    - `Service._on_approved` -- the one path an approved action takes;
    - a tool's own `run` method passing on the ctx it was given -- a
      composite tool (`camera_describe`, `cam_stream`'s cast) whose own
      call was already proposed and approved.
    """
    offenders = []
    for path in sorted(_EXECUTION.rglob("*.py")):
        rel = path.relative_to(_EXECUTION.parent.parent)
        offenders += _offenders_in(path.read_text(encoding="utf-8"), str(rel), is_service=path.name == "service.py")
    return offenders


def _offenders_in(source: str, rel: str, *, is_service: bool) -> list[str]:
    offenders = []
    tree = ast.parse(source)
    parents = _parents(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        mints = isinstance(func, ast.Name) and func.id == "ToolContext" or (
            isinstance(func, ast.Attribute) and func.attr == "ToolContext")
        runs = isinstance(func, ast.Attribute) and func.attr == "run" and any(
            kw.arg == "ctx" for kw in node.keywords)
        if not (mints or runs):
            continue
        cls, fn = _enclosing(node, parents)
        if is_service and cls == "Service" and fn == "_on_approved":
            continue
        if runs and fn == "run" and cls is not None:
            continue
        offenders.append(f"{rel}:{node.lineno} ({cls}.{fn}: {'ToolContext(' if mints else '.run(ctx=)'})")
    return offenders


class TestTheScan(_Case):
    async def asyncSetUp(self):  # no service needed; keep the harness's teardown happy
        await super().asyncSetUp()
        await self._start()

    async def test_no_tool_runs_outside_the_action_path(self):
        self.assertEqual(direct_tool_runs(), [],
                         "a tool run outside Service._on_approved bypasses Guardian (S12): propose it "
                         "with SelfActions.run instead")

    async def test_the_scan_would_catch_one(self):
        source = ("class Service:\n"
                  "    async def _autostart(self):\n"
                  "        ctx = ToolContext(action_id='x')\n"
                  "        await tool.run({}, ctx=ctx)\n"
                  "    async def _on_approved(self, message):\n"
                  "        ctx = ToolContext(action_id='y')\n"
                  "        await tool.run({}, ctx=ctx)\n"
                  "class ComposedTool:\n"
                  "    async def run(self, args, *, ctx):\n"
                  "        return await other.run(args, ctx=ctx)\n")
        hits = _offenders_in(source, "x.py", is_service=True)
        self.assertEqual(len(hits), 2, hits)
        self.assertTrue(all("Service._autostart" in h for h in hits))


class TestTheRealGuardianDecidesThem(_Case):
    """With the real Guardian: the boot-time camera watch and the TV
    dashboard are proposed, decided (PhysicalRule sees them: `cam_watch`
    is observe-only and abstains, `cast_show` is a reversible physical
    action left to the ordinary rules) and run in `guarded`; in `locked`
    the physical start is denied and nothing runs."""

    async def _real_guardian(self, mode: str):
        from simorgh.bus.factory import make_client
        from simorgh.contracts.protocols import Context
        from simorgh.guardian.config import Config as GuardianConfig
        from simorgh.guardian.service import Service as GuardianService

        bus = make_client(self.backend, source="guardian", ledger=self.ledger, clock=self.clock)
        await bus.start()
        ctx = Context(name="guardian", instance_id="", run_id="test", mode="single", bus=bus,
                      ledger=self.ledger, config={}, secrets={"__hmac__": self.ctx.secrets["__hmac__"]},
                      clock=self.clock, logger=_Logger(), data_dir=self.root / "guardian")
        guardian = GuardianService(config=GuardianConfig(mode=mode))
        await guardian.start(ctx)
        self.addAsyncCleanup(guardian.stop)
        return guardian

    async def _tv_on(self):
        import dataclasses

        self.service._config = dataclasses.replace(  # noqa: SLF001
            self.service._config, cast_device="Family Room TV", tv_show_on_start=True)  # noqa: SLF001

    async def test_guarded_approves_and_the_action_stream_records_it(self):
        await self._start()
        await self._real_guardian("guarded")
        cam, show = _Tool("cam_watch"), _Tool("cast_show")
        self.service._registry.update({"cam_watch": cam, "cast_show": show})  # noqa: SLF001
        await self._tv_on()
        self.assertTrue(await self.service._autostart_cam_watch(delay_s=0))  # noqa: SLF001
        self.assertTrue(await self.service._autostart_tv_show(delay_s=0))  # noqa: SLF001
        self.assertEqual(len(cam.calls), 1)
        self.assertEqual(len(show.calls), 1)
        action_id = cam.calls[0][1]
        types_ = [e.type for e in await self.ledger.read(f"action:{action_id}")]
        self.assertIn("received", types_)
        self.assertIn("verified", types_)

    async def test_locked_denies_the_physical_start_and_nothing_runs(self):
        await self._start()
        await self._real_guardian("locked")
        show = _Tool("cast_show")
        self.service._registry["cast_show"] = show  # noqa: SLF001
        await self._tv_on()
        self.assertFalse(await self.service._autostart_tv_show(delay_s=0))  # noqa: SLF001
        self.assertEqual(show.calls, [])
        self.assertIn("tv_show_autostart_denied", self.logger.events("warning"))
