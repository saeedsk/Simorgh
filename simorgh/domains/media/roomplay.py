"""Music in the room you asked from: a room satellite's speaker.

Stage 13 item 8 (docs/plan/stage-13-room-satellites.md). The creator,
2026-09-27: "when I ask the satellite board to play something, I expect
it to play the audio on the board by default." Voice owns the boards
(voice/satellite.py), so this tool asks it over the bus
(`voice.room.play.request`); with no room named, Voice plays on the
satellite whose wake word was heard last -- the room the person is
standing in.

What it can play: a stream or file URL, or internet radio found by
genre or station name in radio-browser.info's open directory (no key,
community-run -- stations come and go). MP3 streams only: the board
decodes MP3 and FLAC, and refused WAV in testing; AAC is unproven.
Apple Music and Spotify cannot be sent to a board.
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request

from simorgh.contracts import topics
from simorgh.contracts.protocols import ToolContext, ToolResult

#: radio-browser.info asks clients to pick a server from its list; these
#: are tried in order when the list itself cannot be fetched.
RADIO_SERVERS = ("de1.api.radio-browser.info", "de2.api.radio-browser.info", "fi1.api.radio-browser.info")
_UA = "Simorgh/1.0 (household assistant)"
_STOP_WORDS = {"stop", "pause", "off", "quiet", "silence"}


def _get_json(url: str, timeout: float = 8.0):
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def find_station(query: str) -> dict | None:
    """The best-voted working MP3 station for a genre (`jazz`) or, failing
    that, a station name (`Groove Salad`). Blocking: run in a thread."""
    try:
        servers = [s["name"] for s in _get_json("https://all.api.radio-browser.info/json/servers", 5.0)] or []
    except Exception:  # noqa: BLE001 -- the fallback list is fine
        servers = []
    servers = list(dict.fromkeys([*servers, *RADIO_SERVERS]))
    q = urllib.parse.quote(query.strip().lower())
    for server in servers:
        base = f"https://{server}/json/stations/search?codec=MP3&hidebroken=true&order=votes&reverse=true&limit=5"
        try:
            for field in ("tag", "name"):
                found = _get_json(f"{base}&{field}={q}")
                found = [s for s in found if s.get("url_resolved")]
                if found:
                    return found[0]
            return None
        except Exception:  # noqa: BLE001 -- the next server
            continue
    raise RuntimeError("the radio directory (radio-browser.info) did not answer")


class RoomPlayTool:
    name = "room_play"
    description = (
        "Play music on a room satellite's speaker -- the default when someone asks a satellite (a room's "
        "speaker, e.g. `sim-room-1`) to play something: `what` is a genre or station name for internet radio "
        "(`jazz`, `classical`, `Groove Salad`), a stream/file URL, or `stop`; `room` optional -- empty plays "
        "in the room whose wake word was just heard. `volume` 0-100 sets the level. Not Apple Music or "
        "Spotify (use music_play for the Mac)."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {"type": "object", "properties": {
        "what": {"type": "string"}, "room": {"type": "string"}, "volume": {"type": "string"}}}

    def __init__(self, config=None, **_kwargs) -> None:
        self._config = config
        #: `find_station`, replaceable in tests; it reaches the internet.
        self.find_station = find_station

    async def _ask_voice(self, ctx: ToolContext, payload: dict) -> dict:
        from simorgh.contracts.envelope import Message

        reply = await ctx.bus.request(Message.new(topics.VOICE_ROOM_PLAY_REQUEST, source="execution",
                                                  payload=payload), timeout=15.0)
        return getattr(reply, "payload", {}) or {}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        if ctx.bus is None:
            return ToolResult(ok=False, error="playing in a room needs the bus, which this session has not got")
        what = str(args.get("what") or "").strip()
        room = str(args.get("room") or "").strip()
        volume = str(args.get("volume") or "").strip().rstrip("%")
        if volume:
            try:
                level = max(0.0, min(100.0, float(volume))) / 100.0
            except ValueError:
                return ToolResult.refused(f"refused: volume is 0-100, not {volume!r}")
            answer = await self._ask_voice(ctx, {"action": "volume", "volume": level, "room": room})
            if not what:
                return self._result(answer, "room:volume")
        if not what:
            return ToolResult.refused("refused: say what to play -- a genre, a station, a URL -- or `stop`")
        if what.lower() in _STOP_WORDS:
            return self._result(await self._ask_voice(ctx, {"action": "stop", "room": room}), "room:stop")
        if what.startswith(("http://", "https://")):
            url, title = what, what
        else:
            try:
                station = await asyncio.to_thread(self.find_station, what)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(ok=False, error=str(exc))
            if station is None:
                return ToolResult(ok=False, error=f"no working MP3 radio station for {what!r} in the directory")
            url = str(station["url_resolved"])
            title = f"{station.get('name', what).strip()} ({what})"
        answer = await self._ask_voice(ctx, {"action": "play", "url": url, "title": title, "room": room})
        return self._result(answer, "room:play", url=url)

    @staticmethod
    def _result(answer: dict, effect: str, **meta) -> ToolResult:
        detail = str(answer.get("detail") or "")
        if not answer.get("ok", False):
            return ToolResult(ok=False, error=detail or "the room's satellite did not play it")
        return ToolResult(ok=True, output=detail, side_effects=(effect,),
                          metadata={"room": str(answer.get("room") or ""), **meta})


def roomplay_tools(config, **kwargs) -> list:
    return [RoomPlayTool(config, **kwargs)]


__all__ = ["RoomPlayTool", "find_station", "roomplay_tools"]
