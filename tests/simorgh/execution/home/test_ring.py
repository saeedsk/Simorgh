"""The Ring cameras (execution/home/ring.py) against a fake cloud: the
two-step login, listing, stills saved where the dashboard looks,
events kept for it, lights, the siren, and the watch loop announcing
only what is new."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.home.ring import RingCamera, ring_tools


class _Bus:
    def __init__(self) -> None:
        self.published = []

    async def publish(self, message) -> None:
        self.published.append(message)


class _FakeCloud:
    def __init__(self, *, twofa_first: bool = True) -> None:
        self.cams = [RingCamera("11", "Front Door", "doorbot", "doorbots", 87, has_light=False, has_siren=False),
                     RingCamera("22", "Back Yard", "stickup_cam", "stickup_cams", 45, has_light=True, has_siren=True)]
        self.calls: list[tuple] = []
        self.events = {"11": [{"id": "e1", "kind": "ding", "at": 1_789_200_000.0, "answered": True, "camera_id": "11"}],
                       "22": [{"id": "e2", "kind": "motion", "at": 1_789_200_100.0, "answered": False, "camera_id": "22"}]}
        self.logins: list[tuple] = []
        self.twofa_first = twofa_first
        self.stills = True

    async def login(self, email, password, code=None):
        self.logins.append((email, password, code))
        if self.twofa_first and not code:
            raise RuntimeError("2fa")
        return {"access_token": "acc", "refresh_token": "ref"}

    async def cameras(self):
        return list(self.cams)

    async def snapshot(self, cam_id):
        self.calls.append(("snapshot", cam_id))
        return b"\xff\xd8ring" + cam_id.encode() if self.stills else None

    async def history(self, cam_id, *, limit=20):
        return list(self.events.get(cam_id, []))[:limit]

    async def light(self, cam_id, on):
        self.calls.append(("light", cam_id, on))

    async def siren(self, cam_id, seconds):
        self.calls.append(("siren", cam_id, seconds))


def _ctx(bus=None, root: Path | None = None) -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={}, data_dir=root or Path("."), clock=None,
                       logger=None, ledger=None, bus=bus)


class RingTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _tools(self, **kw):
        cloud = _FakeCloud(**kw)
        tools = {t.name: t for t in ring_tools(Config(), cloud=cloud, env={}, settings_home=self.home, clock=lambda: 1_789_200_500.0)}
        return tools, cloud, _Bus()

    async def test_setup_asks_for_the_code_then_saves_the_token_and_widens_the_scope(self):
        tools, cloud, bus = self._tools()
        first = await tools["ring_setup"].run({"email": "a@b.c", "password": "pw"}, ctx=_ctx(bus))
        self.assertFalse(first.ok); self.assertIn("code", first.error)
        self.assertFalse((self.home / "secrets.toml").exists())
        second = await tools["ring_setup"].run({"email": "a@b.c", "password": "pw", "code": "123456"}, ctx=_ctx(bus))
        self.assertTrue(second.ok, second.error)
        self.assertIn("Front Door", second.output); self.assertNotIn("pw", second.output)
        import tomllib
        secrets = tomllib.loads((self.home / "secrets.toml").read_text())
        self.assertEqual(json.loads(secrets["RING_TOKEN"])["access_token"], "acc")
        self.assertEqual(secrets["RING_USERNAME"], "a@b.c")
        self.assertNotIn("pw", (self.home / "secrets.toml").read_text(), "the password is never written")
        config = tomllib.loads((self.home / "simorgh.toml").read_text())
        self.assertIn("RING_TOKEN", config["execution"]["secrets"])
        self.assertIn("vault:*", config["execution"]["secrets"])
        self.assertEqual(cloud.logins, [("a@b.c", "pw", None), ("a@b.c", "pw", "123456")])

    async def test_setup_keeps_other_secrets_and_the_existing_scope(self):
        (self.home / "secrets.toml").write_text('REOLINK_HOST = "192.168.50.42"\n')
        (self.home / "simorgh.toml").write_text('[execution]\nsecrets = ["vault:*", "REOLINK_HOST"]\n')
        tools, cloud, bus = self._tools(twofa_first=False)
        result = await tools["ring_setup"].run({"email": "a@b.c", "password": "pw"}, ctx=_ctx(bus))
        self.assertTrue(result.ok, result.error)
        import tomllib
        self.assertEqual(tomllib.loads((self.home / "secrets.toml").read_text())["REOLINK_HOST"], "192.168.50.42")
        scope = tomllib.loads((self.home / "simorgh.toml").read_text())["execution"]["secrets"]
        self.assertEqual(scope[:2], ["vault:*", "REOLINK_HOST"]); self.assertIn("RING_TOKEN", scope)

    async def test_list_names_kind_battery_and_capabilities(self):
        tools, cloud, bus = self._tools()
        result = await tools["ring_list"].run({}, ctx=_ctx(bus))
        self.assertTrue(result.ok)
        self.assertIn("Back Yard  (stickup_cam, battery 45%, light+siren)", result.output)
        self.assertEqual(result.metadata["cameras"][0]["name"], "Front Door")

    async def test_a_still_lands_where_the_dashboard_looks_and_all_means_every_camera(self):
        tools, cloud, bus = self._tools()
        result = await tools["ring_snapshot"].run({"camera": "back"}, ctx=_ctx(bus, self.root))
        self.assertTrue(result.ok, result.error)
        path = self.root / result.metadata["paths"][0]
        self.assertTrue(path.is_file()); self.assertTrue(path.name.startswith("Back_Yard-"))
        self.assertEqual(path.parent, self.root / "workspace" / "cameras" / "ring")
        self.assertEqual(path.read_bytes(), b"\xff\xd8ring22")
        result = await tools["ring_snapshot"].run({"camera": "all"}, ctx=_ctx(bus, self.root))
        self.assertEqual(sorted(result.metadata["cameras"]), ["Back Yard", "Front Door"])
        cloud.stills = False
        result = await tools["ring_snapshot"].run({"camera": "front"}, ctx=_ctx(bus, self.root))
        self.assertFalse(result.ok); self.assertIn("no fresh still", result.error)

    async def test_events_are_listed_newest_first_and_kept_for_the_dashboard(self):
        tools, cloud, bus = self._tools()
        result = await tools["ring_events"].run({}, ctx=_ctx(bus, self.root))
        self.assertTrue(result.ok, result.error)
        self.assertEqual([e["camera"] for e in result.metadata["events"]], ["Back Yard", "Front Door"])
        self.assertIn("Front Door: ding  (answered)", result.output)
        kept = json.loads((self.root / "workspace" / "cameras" / "ring" / "events.json").read_text())
        self.assertEqual([(e["camera"], e["kind"], e["source"]) for e in kept], [("Back Yard", "motion", "ring"), ("Front Door", "ding", "ring")])
        result = await tools["ring_events"].run({"camera": "front", "limit": 5}, ctx=_ctx(bus, self.root))
        self.assertEqual(len(result.metadata["events"]), 1)

    async def test_light_and_siren_respect_what_a_camera_has(self):
        tools, cloud, bus = self._tools()
        self.assertTrue((await tools["ring_light"].run({"camera": "back yard", "on": True}, ctx=_ctx(bus))).ok)
        self.assertTrue((await tools["ring_light"].run({"camera": "back yard off"}, ctx=_ctx(bus))).ok)
        result = await tools["ring_light"].run({"camera": "front", "on": True}, ctx=_ctx(bus))
        self.assertFalse(result.ok); self.assertIn("no light", result.error)
        siren = await tools["ring_siren"].run({"camera": "back", "seconds": 500}, ctx=_ctx(bus))
        self.assertTrue(siren.ok); self.assertEqual(tools["ring_siren"].reversibility, "irreversible")
        self.assertEqual(cloud.calls, [("light", "22", True), ("light", "22", False), ("siren", "22", 60)])

    async def test_an_unknown_or_ambiguous_camera_is_refused_by_name(self):
        tools, cloud, bus = self._tools()
        result = await tools["ring_snapshot"].run({"camera": "garage"}, ctx=_ctx(bus, self.root))
        self.assertFalse(result.ok); self.assertIn("Front Door", result.error)
        cloud.cams.append(RingCamera("33", "Back Gate", "stickup_cam", "stickup_cams"))
        result = await tools["ring_light"].run({"camera": "back", "on": True}, ctx=_ctx(bus))
        self.assertFalse(result.ok); self.assertIn("could be", result.error)

    async def test_the_watch_loop_learns_first_then_announces_only_new_events_and_refreshes_stills(self):
        tools, cloud, bus = self._tools()
        watch = tools["ring_watch"]
        folder = self.root / "workspace" / "cameras" / "ring"
        folder.mkdir(parents=True)
        announced = await watch.tick(bus, cloud, folder, first=True)
        self.assertEqual(announced, 0, "what is already in the history is not news")
        self.assertEqual(len([c for c in cloud.calls if c[0] == "snapshot"]), 2, "a still per camera on the first pass")
        self.assertTrue(any(p.name.startswith("Front_Door-") for p in folder.iterdir()))
        cloud.events["11"].insert(0, {"id": "e3", "kind": "ding", "at": 1_789_200_400.0, "answered": False, "camera_id": "11"})
        announced = await watch.tick(bus, cloud, folder)
        self.assertEqual(announced, 1)
        kinds = [m.type for m in bus.published]
        self.assertEqual(kinds, [topics.CAMERA_EVENT, topics.UI_NOTICE])
        self.assertEqual(bus.published[0].payload, {"channel": 0, "camera": "Front Door", "kinds": ["ding"], "host": "ring"})
        self.assertIn("🔔 Front Door: ding", bus.published[1].payload["text"])
        self.assertEqual(len([c for c in cloud.calls if c[0] == "snapshot"]), 2, "stills are not re-taken every poll")
        kept = json.loads((folder / "events.json").read_text())
        self.assertEqual(kept[0]["id"], "e3")
        self.assertEqual(await watch.tick(bus, cloud, folder), 0, "announced once")

    async def test_watch_on_and_off_hold_one_task(self):
        tools, cloud, bus = self._tools()
        result = await tools["ring_watch"].run({"on": True, "every_s": 5}, ctx=_ctx(bus, self.root))
        self.assertTrue(result.ok, result.error); self.assertIn("every 30s", result.output, "never faster than half a minute")
        task = tools["ring_watch"]._prefs.watcher  # noqa: SLF001
        self.assertIsNotNone(task)
        result = await tools["ring_watch"].run({"on": False}, ctx=_ctx(bus, self.root))
        self.assertTrue(result.ok)
        self.assertIsNone(tools["ring_watch"]._prefs.watcher)  # noqa: SLF001
        await __import__("asyncio").sleep(0)
        self.assertTrue(task.cancelled() or task.done())

    async def test_without_a_token_every_tool_says_how_to_set_up(self):
        tools = {t.name: t for t in ring_tools(Config(), env={}, settings_home=self.home)}
        result = await tools["ring_list"].run({}, ctx=_ctx(_Bus()))
        self.assertFalse(result.ok)
        self.assertTrue("ring setup" in result.error or "ring_doorbell" in result.error, result.error)
