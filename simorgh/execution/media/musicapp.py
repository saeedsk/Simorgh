"""The Mac's own Music app, as a media player Sim can drive.

The creator, 2026-09-11: "I'd like Sim to have access to my Apple Music
and my MacBook music folder, so I can ask Sim to play a music; Sim
should be able to change the volume, play, go to next or previous
song." The media domain drives Home Assistant players; this is the one
player that is not behind Home Assistant -- the laptop Sim is running
on -- and macOS already exposes it completely through AppleScript.
No dependency, no account: `osascript` talks to Music.app, which holds
the Apple Music subscription and the local library alike.

`play` searches the library by playlist, then album, then artist, then
track name; a POSIX path plays a file, or every audio file in a folder
(added to the library as a playlist named for the folder, so it is
there next time). Volume goes through the same quiet-hours policy the
Home Assistant players get (`_MediaTool._volume_verdict`).
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

from simorgh.contracts.protocols import ToolContext, ToolResult

from .tools import _MediaTool

AUDIO_SUFFIXES = (".mp3", ".m4a", ".aac", ".flac", ".wav", ".aiff", ".aif", ".alac", ".ogg")


def _quote(text: str) -> str:
    """A string literal for AppleScript."""
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


class MusicApp:
    """AppleScript over `osascript`. `run` is injectable for tests."""

    def __init__(self, run=None) -> None:
        self._run = run or self._osascript

    @staticmethod
    def available() -> tuple[bool, str]:
        if sys.platform != "darwin":
            return False, "the Music app is macOS only"
        if not shutil.which("osascript"):
            return False, "osascript is not available"
        return True, ""

    @staticmethod
    def _osascript(script: str) -> tuple[int, str]:
        done = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30,
                              stdin=subprocess.DEVNULL)
        return done.returncode, (done.stdout if done.returncode == 0 else done.stderr).strip()

    async def tell(self, body: str) -> str:
        code, out = await asyncio.to_thread(self._run, f'tell application "Music"\n{body}\nend tell')
        if code != 0:
            raise RuntimeError(out or f"osascript exited {code}")
        return out

    # ----------------------------------------------------------- reading
    async def state(self) -> dict:
        # `st` is a reserved word to the Music dictionary ("Expected
        # expression but found st"); plain names and explicit `as text`
        # coercions, and a `player position` that may be missing value.
        script = (
            'set playerState to (player state as text)\n'
            'set vol to sound volume\n'
            'set pos to ""\n'
            'try\n'
            '  set pos to (player position as text)\n'
            'end try\n'
            'set info to ""\n'
            'try\n'
            '  set t to current track\n'
            '  set info to (name of t) & "|" & (artist of t) & "|" & (album of t) & "|" & (duration of t as text)\n'
            'end try\n'
            'return playerState & "|" & (vol as text) & "|" & pos & "|" & info'
        )
        raw = await self.tell(script)
        parts = raw.split("|")
        state = {"state": parts[0] if parts else "unknown", "volume": int(float(parts[1])) if len(parts) > 1 and parts[1] else None,
                 "position": float(parts[2]) if len(parts) > 2 and parts[2] not in ("", "missing value") else None}
        if len(parts) >= 7:
            state.update({"title": parts[3], "artist": parts[4], "album": parts[5],
                          "duration": float(parts[6]) if parts[6] else None})
        return state

    # ---------------------------------------------------------- transport
    async def control(self, op: str) -> None:
        verb = {"play": "play", "resume": "play", "pause": "pause", "stop": "stop",
                "next": "next track", "previous": "previous track", "prev": "previous track",
                "playpause": "playpause"}[op]
        await self.tell(verb)

    async def set_volume(self, volume: int) -> None:
        await self.tell(f"set sound volume to {int(volume)}")

    async def set_mute(self, muted: bool) -> None:
        await self.tell(f"set mute to {'true' if muted else 'false'}")

    # ------------------------------------------------------------ playing
    async def play_query(self, query: str) -> str:
        """Play the first match for `query`, looking at playlists, then
        albums, then artists, then track names. Returns what was played."""
        q = _quote(query)
        script = (
            f'set q to {q}\n'
            'try\n'
            '  set pl to (first playlist whose name contains q)\n'
            '  play pl\n'
            '  return "playlist: " & (name of pl)\n'
            'end try\n'
            'set lib to library playlist 1\n'
            'try\n'
            '  set t to (first track of lib whose album contains q)\n'
            '  play (album of t)\n'
            'on error\n'
            '  try\n'
            '    set t to (first track of lib whose artist contains q)\n'
            '  on error\n'
            '    set t to (first track of lib whose name contains q)\n'
            '  end try\n'
            'end try\n'
            'play t\n'
            'return "track: " & (name of t) & " -- " & (artist of t)'
        )
        return await self.tell(script)

    async def play_path(self, path: Path) -> str:
        """Play a file, or every audio file in a folder (added to the
        library as a playlist named for the folder)."""
        path = path.expanduser()
        if path.is_dir():
            files = sorted(p for p in path.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES)
            if not files:
                raise FileNotFoundError(f"no audio files in {path}")
            name = _quote(f"Sim: {path.name}")
            listing = ", ".join(f"POSIX file {_quote(str(p))}" for p in files)
            script = (
                f'if not (exists playlist {name}) then make new playlist with properties {{name:{name}}}\n'
                f'set pl to playlist {name}\n'
                f'add {{{listing}}} to pl\n'
                'play pl\n'
                f'return "folder: " & (name of pl) & " (" & (count of tracks of pl) & " tracks)"'
            )
            return await self.tell(script)
        if not path.is_file():
            raise FileNotFoundError(f"{path} does not exist")
        script = (
            f'set t to add POSIX file {_quote(str(path))} to library playlist 1\n'
            'play t\n'
            'return "file: " & (name of t)'
        )
        return await self.tell(script)


class _MusicAppTool(_MediaTool):
    """Shared: availability, the app handle, and the volume policy."""

    def __init__(self, config, *, app: MusicApp | None = None, **kwargs) -> None:
        super().__init__(config, **kwargs)
        self._app = app or MusicApp()

    def _refusal(self) -> ToolResult | None:
        ok, why = MusicApp.available()
        return None if ok else ToolResult(ok=False, error=f"refused: {why}")


class MusicNowTool(_MusicAppTool):
    name = "music_now"
    description = "What the Mac's Music app is playing right now: track, artist, album, state, volume."
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "properties": {}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        if (refused := self._refusal()) is not None:
            return refused
        try:
            state = await self._app.state()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"could not read the Music app: {exc}")
        line = f"Music is {state.get('state')}"
        if state.get("title"):
            line += f": {state['title']} -- {state.get('artist') or '?'} ({state.get('album') or '?'})"
        if state.get("volume") is not None:
            line += f", volume {state['volume']}"
        return ToolResult(ok=True, output=line, metadata=state)


class MusicControlTool(_MusicAppTool):
    name = "music_control"
    description = (
        "Control the Mac's Music app: play, pause, stop, next, previous, volume (0-100 with `value`), "
        "mute, unmute. Volume follows the same quiet-hours limits as the home players."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {
        "type": "object", "required": ["op"],
        "properties": {"op": {"type": "string", "enum": ["play", "resume", "pause", "stop", "next", "previous",
                                                          "prev", "volume", "mute", "unmute"]},
                       "value": {"type": "number"}},
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        if (refused := self._refusal()) is not None:
            return refused
        op = str(args.get("op") or "").strip().lower()
        try:
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
                await self._app.set_volume(volume)
                done = f"volume {volume}"
            elif op in ("mute", "unmute"):
                await self._app.set_mute(op == "mute")
                done = op
            elif op in ("play", "resume", "pause", "stop", "next", "previous", "prev"):
                await self._app.control(op)
                done = op
            else:
                return ToolResult(ok=False, error=f"refused: unknown op {op!r}")
            state = await self._app.state()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"the Music app refused: {exc}")
        now = f"{state.get('title')} -- {state.get('artist')}" if state.get("title") else state.get("state", "")
        return ToolResult(ok=True, output=f"{done}; now {state.get('state')}: {now}",
                          side_effects=(f"music:{op}",), metadata={"op": op, **state})


class MusicPlayTool(_MusicAppTool):
    name = "music_play"
    description = (
        "Play something in the Mac's Music app: a playlist, album, artist or song by name (`query`), "
        "or a local audio file or folder of files (`path`)."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {"type": "object", "properties": {"query": {"type": "string"}, "path": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        if (refused := self._refusal()) is not None:
            return refused
        query = str(args.get("query") or "").strip()
        path = str(args.get("path") or "").strip()
        if not query and not path:
            return ToolResult(ok=False, error="refused: say what to play -- a name, or a file or folder path")
        # A marker call puts whatever the model wrote on the first line
        # into `query`; if that is a path that exists, it was a path.
        if query and not path and (query.startswith(("/", "~")) or query.startswith("./")):
            if Path(query).expanduser().exists():
                path, query = query, ""
        try:
            if path:
                played = await self._app.play_path(Path(path))
            else:
                played = await self._app.play_query(query)
        except FileNotFoundError as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "Can’t get" in msg or "Can't get" in msg or "-1728" in msg:
                return ToolResult(ok=False, error=f"nothing in the library matches {query or path!r}")
            return ToolResult(ok=False, error=f"the Music app refused: {msg}")
        return ToolResult(ok=True, output=f"playing {played}", side_effects=("music:play",),
                          metadata={"played": played, "query": query, "path": path})


def musicapp_tools(config, **kwargs) -> list:
    return [MusicNowTool(config, **kwargs), MusicControlTool(config, **kwargs), MusicPlayTool(config, **kwargs)]


__all__ = ["AUDIO_SUFFIXES", "MusicApp", "MusicControlTool", "MusicNowTool", "MusicPlayTool", "musicapp_tools"]
