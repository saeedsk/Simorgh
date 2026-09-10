"""Media: what is playing, and running it.

Volume is what gets the attention. A model that means well and sends
full volume at two in the morning has done something a person cannot
undo by being told it was a mistake, so the limits are enforced before
the call rather than reported after it."""

from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

from simorgh.contracts.home.fakes import FakeHomeAssistant
from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.media.tools import media_tools

AFTERNOON = datetime(2026, 6, 17, 14, 30)
MIDDLE_OF_THE_NIGHT = datetime(2026, 6, 17, 2, 30)


def _ctx() -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                       data_dir=Path("."), clock=None, logger=None, ledger=None)


class _ToolCase(unittest.IsolatedAsyncioTestCase):
    def _tools(self, *, house=None, now: datetime = AFTERNOON, **overrides) -> dict:
        self.house = house if house is not None else FakeHomeAssistant()
        config = Config(home_settle_s=0.0, **overrides)
        return {tool.name: tool for tool in media_tools(
            config, client=self.house, env={}, clock=lambda: now.timestamp())}


class MediaNowTestCase(_ToolCase):
    async def test_it_lists_every_player(self):
        result = await self._tools()["media_now"].run({}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("Kitchen Echo", result.output)
        self.assertIn("Living room TV", result.output)

    async def test_it_says_what_is_playing_and_at_what_volume(self):
        result = await self._tools()["media_now"].run({}, ctx=_ctx())
        self.assertIn("The Bear", result.output)
        self.assertIn("volume 25", result.output)
        self.assertEqual(result.metadata["playing"], 1)

    async def test_a_room_narrows_it(self):
        result = await self._tools()["media_now"].run({"where": "kitchen echo"}, ctx=_ctx())
        self.assertEqual(len(result.metadata["rows"]), 1)

    async def test_a_house_with_no_players_says_so(self):
        house = FakeHomeAssistant([("light.a", "on", {})])
        result = await self._tools(house=house)["media_now"].run({}, ctx=_ctx())
        self.assertTrue(result.ok)
        self.assertIn("no media players", result.output)

    async def test_an_unconfigured_house_says_what_to_set(self):
        tools = {t.name: t for t in media_tools(Config(), env={})}
        result = await tools["media_now"].run({}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("HOME_ASSISTANT_URL", result.error)


class MediaControlTestCase(_ToolCase):
    async def test_pause_pauses(self):
        result = await self._tools()["media_control"].run(
            {"op": "pause", "where": "tv"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual((await self.house.state("media_player.living_room_tv")).state, "paused")

    async def test_resume_plays(self):
        tools = self._tools()
        await tools["media_control"].run({"op": "pause", "where": "tv"}, ctx=_ctx())
        await tools["media_control"].run({"op": "resume", "where": "tv"}, ctx=_ctx())
        self.assertEqual((await self.house.state("media_player.living_room_tv")).state, "playing")

    async def test_volume_is_sent_as_a_fraction(self):
        await self._tools()["media_control"].run(
            {"op": "volume", "where": "tv", "value": 40}, ctx=_ctx())
        self.assertAlmostEqual(self.house.calls[0][2]["volume_level"], 0.4, places=6)

    async def test_an_unknown_op_lists_the_real_ones(self):
        result = await self._tools()["media_control"].run({"op": "explode"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("pause", result.error)

    async def test_volume_without_a_value_is_refused(self):
        result = await self._tools()["media_control"].run(
            {"op": "volume", "where": "tv"}, ctx=_ctx())
        self.assertFalse(result.ok)

    async def test_a_volume_outside_the_scale_is_refused(self):
        result = await self._tools()["media_control"].run(
            {"op": "volume", "where": "tv", "value": 150}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("0-100", result.error)

    async def test_it_says_when_nothing_actually_changed(self):
        house = FakeHomeAssistant(unavailable=("media_player.living_room_tv",))
        result = await self._tools(house=house)["media_control"].run(
            {"op": "pause", "where": "tv"}, ctx=_ctx())
        self.assertIn("Nothing actually changed", result.output)

    async def test_the_before_snapshot_comes_back(self):
        result = await self._tools()["media_control"].run(
            {"op": "pause", "where": "tv"}, ctx=_ctx())
        self.assertIn("media_player.living_room_tv", result.metadata["before"])


class VolumeSafetyTestCase(_ToolCase):
    async def test_loud_is_refused_unattended(self):
        result = await self._tools(media_max_volume_unattended=60)["media_control"].run(
            {"op": "volume", "where": "tv", "value": 90}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("unattended limit", result.error)
        self.assertEqual(self.house.calls, [], "a refusal must not have called anything")

    async def test_moderate_is_allowed(self):
        result = await self._tools(media_max_volume_unattended=60)["media_control"].run(
            {"op": "volume", "where": "tv", "value": 45}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)

    async def test_quiet_hours_cap_much_lower(self):
        """An Echo at full volume at 3am is not a policy question."""
        result = await self._tools(now=MIDDLE_OF_THE_NIGHT,
                                    media_quiet_hours="22:00-07:00",
                                    media_quiet_hours_max_volume=20)["media_control"].run(
            {"op": "volume", "where": "tv", "value": 45}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("quiet hours", result.error)

    async def test_quiet_and_within_the_cap_is_allowed(self):
        result = await self._tools(now=MIDDLE_OF_THE_NIGHT,
                                    media_quiet_hours="22:00-07:00",
                                    media_quiet_hours_max_volume=20)["media_control"].run(
            {"op": "volume", "where": "tv", "value": 15}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)

    async def test_with_no_quiet_hours_set_only_the_unattended_cap_applies(self):
        result = await self._tools(now=MIDDLE_OF_THE_NIGHT, media_quiet_hours="",
                                    media_max_volume_unattended=60)["media_control"].run(
            {"op": "volume", "where": "tv", "value": 45}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)

    async def test_a_malformed_quiet_hours_does_not_disable_the_check(self):
        """Falling silently back to "no quiet hours" would turn the
        stereo up at 3am precisely because someone tried to stop it."""
        result = await self._tools(now=MIDDLE_OF_THE_NIGHT, media_quiet_hours="late",
                                    media_max_volume_unattended=60)["media_control"].run(
            {"op": "volume", "where": "tv", "value": 90}, ctx=_ctx())
        self.assertFalse(result.ok)

    async def test_the_same_cap_applies_to_media_play(self):
        result = await self._tools(media_max_volume_unattended=60)["media_play"].run(
            {"what": "http://stream.example/radio.mp3", "where": "tv", "volume": 95}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertEqual(self.house.calls, [])


class MediaPlayTestCase(_ToolCase):
    async def test_it_plays_a_stream(self):
        result = await self._tools()["media_play"].run(
            {"what": "http://stream.example/radio.mp3", "where": "kitchen echo"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.house.calls[0][0], "media_player.play_media")
        self.assertEqual(self.house.calls[0][2]["media_content_id"],
                         "http://stream.example/radio.mp3")

    async def test_a_content_type_is_supplied_because_ha_rejects_a_call_without_one(self):
        await self._tools()["media_play"].run(
            {"what": "http://stream.example/live", "where": "kitchen echo"}, ctx=_ctx())
        self.assertTrue(self.house.calls[0][2]["media_content_type"])

    async def test_a_video_url_is_recognised(self):
        result = await self._tools()["media_play"].run(
            {"what": "http://x.example/film.mp4", "where": "tv"}, ctx=_ctx())
        self.assertEqual(result.metadata["content_type"], "video")

    async def test_an_explicit_content_type_wins(self):
        await self._tools()["media_play"].run(
            {"what": "x", "where": "tv", "content_type": "playlist"}, ctx=_ctx())
        self.assertEqual(self.house.calls[0][2]["media_content_type"], "playlist")

    async def test_the_volume_is_set_before_playing_not_after(self):
        """Setting it afterwards means the first second comes out at
        whatever the last person left it at."""
        await self._tools()["media_play"].run(
            {"what": "x", "where": "tv", "volume": 30}, ctx=_ctx())
        self.assertEqual([call[0] for call in self.house.calls],
                         ["media_player.volume_set", "media_player.play_media"])

    async def test_nothing_to_play_is_refused(self):
        result = await self._tools()["media_play"].run({"what": " ", "where": "tv"}, ctx=_ctx())
        self.assertFalse(result.ok)

    async def test_an_ambiguous_room_is_refused_with_the_candidates(self):
        result = await self._tools()["media_play"].run(
            {"what": "x", "where": "nonexistent room"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertEqual(self.house.calls, [])
