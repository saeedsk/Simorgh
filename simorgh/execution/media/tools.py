"""`media_now`, `media_control`, `media_play`.

Everything goes through Home Assistant's `media_player` domain, which
is already uniform across Sonos, Chromecast, Kodi, an Echo via
`alexa_media_player`, and a TV. That uniformity is the reason this
domain is small: the hard part was solved by whoever wrote the
integration.

Volume is the part worth being careful about. A model that means well
and sends `volume_level: 1.0` at two in the morning has done something
a person cannot undo by being told it was a mistake.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from simorgh.contracts.home.client import HomeUnavailable
from simorgh.contracts.protocols import ToolContext, ToolResult

from ..home.registry import Ambiguous, NotFound
from ..home.tools import _HomeTool

#: What `media_control` accepts, and the service each maps to.
_OPERATIONS = {
    "play": "media_player.media_play",
    "resume": "media_player.media_play",
    "pause": "media_player.media_pause",
    "stop": "media_player.media_stop",
    "next": "media_player.media_next_track",
    "previous": "media_player.media_previous_track",
    "prev": "media_player.media_previous_track",
    "volume": "media_player.volume_set",
    "mute": "media_player.volume_mute",
    "unmute": "media_player.volume_mute",
    "off": "media_player.turn_off",
    "on": "media_player.turn_on",
}


class _MediaTool(_HomeTool):
    def _quiet_hours(self) -> tuple[int, int] | None:
        from simorgh.contracts.timewindow import parse_quiet_hours

        try:
            return parse_quiet_hours(str(getattr(self._config, "media_quiet_hours", "")))
        except ValueError:
            return None

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self._clock())

    def _volume_verdict(self, volume: int) -> str:
        """"" when the volume is fine, otherwise why it is not.

        Enforced here rather than in Guardian because it is a question
        about a number and a clock, both of which are known at this
        edge -- and because an Echo at full volume at 3am is not a
        policy question.
        """
        from simorgh.contracts.timewindow import in_quiet_hours

        quiet = self._quiet_hours()
        if quiet is not None and in_quiet_hours(self._now().hour, quiet):
            cap = int(getattr(self._config, "media_quiet_hours_max_volume", 20))
            if volume > cap:
                return (f"it is quiet hours ({quiet[0]:02d}:00-{quiet[1]:02d}:00) and {volume} is "
                        f"over the limit of {cap}. Ask the person, or use {cap} or less.")
        cap = int(getattr(self._config, "media_max_volume_unattended", 60))
        if volume > cap:
            return (f"{volume} is over the unattended limit of {cap}. Ask the person before "
                    f"going louder than that.")
        return ""

    async def _players(self, client, target: str = ""):
        """Resolve `target` to media players, or every one of them."""
        registry = await self._registry(client)
        if not target:
            return registry, [e.entity_id for e in registry.entities
                              if e.domain == "media_player"]
        return registry, registry.resolve(target, domain="media_player")


class MediaNowTool(_MediaTool):
    name = "media_now"
    description = "What is playing, and where. Give a room or player name, or leave it empty for all."
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "properties": {"where": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        client = self._client()
        if not client.configured:
            return self._unconfigured(client)
        try:
            registry, entity_ids = await self._players(client, str(args.get("where") or ""))
        except HomeUnavailable as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")
        except (Ambiguous, NotFound) as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")

        if not entity_ids:
            return ToolResult(ok=True, output="there are no media players in the house",
                              metadata={"rows": []})
        lines, rows = [], []
        for entity_id in entity_ids:
            entity = registry.by_id(entity_id)
            if entity is None:
                continue
            volume = entity.attributes.get("volume_level")
            title = entity.attributes.get("media_title") or ""
            line = f"  {entity.name}: {entity.state}"
            if title:
                line += f" -- {title}"
            if volume is not None:
                line += f"  (volume {int(float(volume) * 100)})"
            lines.append(line)
            rows.append({"entity_id": entity_id, "name": entity.name, "state": entity.state,
                         "title": title,
                         "volume": int(float(volume) * 100) if volume is not None else None})
        playing = [r for r in rows if r["state"] == "playing"]
        header = (f"{len(playing)} of {len(rows)} player(s) playing:"
                  if playing else "nothing is playing:")
        return ToolResult(ok=True, output=header + "\n" + "\n".join(lines),
                          metadata={"rows": rows, "playing": len(playing)})


class MediaControlTool(_MediaTool):
    name = "media_control"
    description = (
        "Pause, resume, skip, stop, or set the volume on a player. Volume is 0-100. "
        "Refuses to go loud unattended, and refuses to go loud at all during quiet hours."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {
        "type": "object", "required": ["op"],
        "properties": {"op": {"type": "string", "enum": sorted(_OPERATIONS)},
                       "where": {"type": "string"}, "value": {"type": "number"}},
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        op = str(args.get("op") or "").strip().lower()
        if op not in _OPERATIONS:
            return ToolResult(ok=False,
                              error=f"refused: unknown op {op!r}; one of "
                                    f"{', '.join(sorted(_OPERATIONS))}")
        client = self._client()
        if not client.configured:
            return self._unconfigured(client)
        try:
            registry, entity_ids = await self._players(client, str(args.get("where") or ""))
        except HomeUnavailable as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")
        except (Ambiguous, NotFound) as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")
        if not entity_ids:
            return ToolResult(ok=False, error="refused: no media player matched")

        data: dict = {}
        if op == "volume":
            raw = args.get("value")
            if raw is None:
                return ToolResult(ok=False, error="refused: volume needs a value from 0 to 100")
            try:
                volume = int(float(raw))
            except (TypeError, ValueError):
                return ToolResult(ok=False, error=f"refused: {raw!r} is not a volume")
            if not 0 <= volume <= 100:
                return ToolResult(ok=False, error=f"refused: {volume} is outside 0-100")
            verdict = self._volume_verdict(volume)
            if verdict:
                return ToolResult(ok=False, error=f"refused: {verdict}")
            data["volume_level"] = volume / 100.0
        elif op in ("mute", "unmute"):
            data["is_volume_muted"] = op == "mute"

        try:
            result = await client.call(_OPERATIONS[op], entity_ids=tuple(entity_ids), data=data,
                                       settle_s=float(getattr(self._config, "home_settle_s", 1.0)))
        except HomeUnavailable as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")

        body = f"{op} on {len(entity_ids)} player(s):\n{result.render()}"
        if result.unchanged and not result.changed:
            body += ("\n\nNothing actually changed -- Home Assistant accepted the call, so the "
                     "player is most likely off or unavailable.")
        return ToolResult(
            ok=True, output=body,
            side_effects=tuple(f"media:{op}:{entity_id}" for entity_id in entity_ids),
            metadata={"op": op, "entities": list(entity_ids), "changed": list(result.changed),
                      "before": {e: {"state": v.state, "attributes": v.attributes}
                                 for e, v in result.before.items()}})


class MediaPlayTool(_MediaTool):
    name = "media_play"
    description = (
        "Play something on a player: a URL, a radio stream, or a media id your media server "
        "understands. Give `what` and `where`."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {
        "type": "object", "required": ["what", "where"],
        "properties": {"what": {"type": "string"}, "where": {"type": "string"},
                       "content_type": {"type": "string"}, "volume": {"type": "number"}},
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        what = str(args.get("what") or "").strip()
        if not what:
            return ToolResult(ok=False, error="refused: nothing to play")
        client = self._client()
        if not client.configured:
            return self._unconfigured(client)
        try:
            registry, entity_ids = await self._players(client, str(args.get("where") or ""))
        except HomeUnavailable as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")
        except (Ambiguous, NotFound) as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")
        if not entity_ids:
            return ToolResult(ok=False, error="refused: no media player matched")

        volume = args.get("volume")
        if volume is not None:
            try:
                volume = int(float(volume))
            except (TypeError, ValueError):
                return ToolResult(ok=False, error=f"refused: {volume!r} is not a volume")
            verdict = self._volume_verdict(volume)
            if verdict:
                return ToolResult(ok=False, error=f"refused: {verdict}")

        content_type = str(args.get("content_type") or _guess_type(what))
        data = {"media_content_id": what, "media_content_type": content_type}
        try:
            if volume is not None:
                await client.call("media_player.volume_set", entity_ids=tuple(entity_ids),
                                  data={"volume_level": volume / 100.0}, settle_s=0.0)
            result = await client.call("media_player.play_media", entity_ids=tuple(entity_ids),
                                       data=data,
                                       settle_s=float(getattr(self._config, "home_settle_s", 1.0)))
        except HomeUnavailable as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")

        body = f"playing {what!r} on {len(entity_ids)} player(s):\n{result.render()}"
        if result.unchanged and not result.changed:
            body += ("\n\nNothing actually changed. Home Assistant accepted it, so the player may "
                     "be off, or may not understand this kind of content -- "
                     f"media_content_type was {content_type!r}.")
        return ToolResult(
            ok=True, output=body,
            side_effects=tuple(f"media:play:{entity_id}" for entity_id in entity_ids),
            metadata={"what": what, "content_type": content_type, "entities": list(entity_ids),
                      "changed": list(result.changed), "volume": volume})


def _guess_type(what: str) -> str:
    """HA needs a `media_content_type` and rejects a call without one.
    The mapping differs by integration, which is exactly why the design
    put it in one place rather than at every call site."""
    lowered = what.lower()
    if lowered.startswith(("http://", "https://")):
        if any(lowered.endswith(ext) for ext in (".mp3", ".aac", ".flac", ".m4a", ".ogg", ".wav")):
            return "music"
        if any(lowered.endswith(ext) for ext in (".mp4", ".mkv", ".mov", ".webm")):
            return "video"
        return "music"          # a stream URL is almost always radio
    if lowered.startswith("media-source://"):
        return "music"
    if lowered.startswith("spotify:"):
        return "music"
    return "music"


def media_tools(config, **kwargs) -> list:
    from .cast import cast_tools
    from .musicapp import musicapp_tools

    return [MediaNowTool(config, **kwargs), MediaControlTool(config, **kwargs),
            MediaPlayTool(config, **kwargs), *musicapp_tools(config, **kwargs), *cast_tools(config, **kwargs)]


__all__ = ["MediaControlTool", "MediaNowTool", "MediaPlayTool", "media_tools"]
