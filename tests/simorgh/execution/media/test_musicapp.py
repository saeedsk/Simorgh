"""The Mac's Music app as a player Sim can drive, on a fake osascript."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.media import musicapp
from simorgh.execution.media.musicapp import MusicApp, MusicControlTool, MusicNowTool, MusicPlayTool


def _ctx() -> ToolContext:
    return ToolContext(action_id="a", task_id=None, scope={}, constraints={}, data_dir=Path("."),
                       clock=None, logger=None, ledger=None)


class _Osascript:
    """Records every script; answers state queries with a canned line."""

    def __init__(self, state="playing|42|12.5|Blue Train|John Coltrane|Blue Train|643.0", fail_on=None):
        self.scripts: list[str] = []
        self.state = state
        self.fail_on = fail_on

    def __call__(self, script: str):
        self.scripts.append(script)
        if self.fail_on and self.fail_on in script:
            return 1, "execution error: Can’t get track 1 whose name contains \"zzz\". (-1728)"
        if "player state" in script:
            return 0, self.state
        return 0, "track: Blue Train -- John Coltrane"


def _tools(run, clock=None):
    app = MusicApp(run=run)
    kw = {"app": app}
    if clock is not None:
        kw["clock"] = clock
    cfg = Config()
    return MusicNowTool(cfg, **kw), MusicControlTool(cfg, **kw), MusicPlayTool(cfg, **kw)


@unittest.skipUnless(sys.platform == "darwin", "the Music app is macOS only")
class MusicAppTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_now_reads_the_player(self):
        osa = _Osascript()
        now, _, _ = _tools(osa)
        result = await now.run({}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("Blue Train -- John Coltrane", result.output)
        self.assertEqual(result.metadata["volume"], 42)

    async def test_transport_ops_send_the_right_verbs(self):
        osa = _Osascript()
        _, control, _ = _tools(osa)
        for op, verb in (("pause", "pause"), ("next", "next track"), ("previous", "previous track"), ("play", "play")):
            result = await control.run({"op": op}, ctx=_ctx())
            self.assertTrue(result.ok, result.error)
            self.assertTrue(any(f"\n{verb}\n" in s for s in osa.scripts), (op, osa.scripts[-2:]))

    async def test_volume_is_set_and_policed(self):
        osa = _Osascript()
        # 13:00 is outside the default quiet hours; 60 is the unattended cap
        _, control, _ = _tools(osa, clock=lambda: 1789000000.0 + 13 * 3600 - 7 * 3600)  # local hour varies; use a wide margin below
        ok = await control.run({"op": "volume", "value": 20}, ctx=_ctx())
        self.assertTrue(ok.ok, ok.error)
        self.assertTrue(any("set sound volume to 20" in s for s in osa.scripts))
        too_loud = await control.run({"op": "volume", "value": 95}, ctx=_ctx())
        self.assertFalse(too_loud.ok)
        self.assertIn("limit", too_loud.error)
        self.assertFalse(any("set sound volume to 95" in s for s in osa.scripts), "never sent")

    async def test_play_by_name_searches_the_library(self):
        osa = _Osascript()
        _, _, play = _tools(osa)
        result = await play.run({"query": "Blue Train"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("Blue Train", osa.scripts[-1])
        self.assertIn("first playlist whose name contains", osa.scripts[-1])
        self.assertIn("playing track: Blue Train", result.output)

    async def test_no_match_is_said_plainly(self):
        osa = _Osascript(fail_on='"zzz"')
        _, _, play = _tools(osa)
        result = await play.run({"query": "zzz"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("nothing in the library matches", result.error)

    async def test_a_folder_becomes_a_playlist_of_its_audio_files(self):
        osa = _Osascript()
        _, _, play = _tools(osa)
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("01.mp3", "02.m4a", "notes.txt"):
                (Path(tmp) / name).write_bytes(b"x")
            result = await play.run({"path": tmp}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        script = osa.scripts[-1]
        self.assertIn("01.mp3", script)
        self.assertIn("02.m4a", script)
        self.assertNotIn("notes.txt", script)
        self.assertIn("make new playlist", script)

    async def test_a_missing_path_is_refused(self):
        _, _, play = _tools(_Osascript())
        result = await play.run({"path": "/nowhere/at/all"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("does not exist", result.error)

    async def test_nothing_to_play_is_refused(self):
        _, _, play = _tools(_Osascript())
        self.assertFalse((await play.run({}, ctx=_ctx())).ok)


class NotAMacTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_elsewhere_it_refuses_by_name(self):
        with mock.patch.object(musicapp.sys, "platform", "linux"):
            result = await MusicNowTool(Config(), app=MusicApp(run=_Osascript())).run({}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("macOS only", result.error)


class RegisteredTestCase(unittest.TestCase):
    def test_the_three_tools_are_registered_with_the_media_domain(self):
        from simorgh.execution.media.tools import media_tools
        names = {t.name for t in media_tools(Config())}
        self.assertTrue({"music_now", "music_control", "music_play"} <= names)


if __name__ == "__main__":
    unittest.main()
