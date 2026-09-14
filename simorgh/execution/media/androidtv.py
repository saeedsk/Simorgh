"""The TV's own apps, over the Android TV remote protocol.

The creator, 2026-09-13: "I like to see content on my TV, specially the
YouTube video I ask Sim to play, at 4K plus resolution. Sim can
communicate with the apps on the TV and ask them to play the content."

The Cast paths could not: YouTube's embedded player is blank inside a
Cast receiver, its own receiver app rejects requests now ("400
screen_ids"), and a file Sim fetches is 1080p at best. The TV (a Sony
Bravia on Android TV) also speaks the remote protocol the Google TV
phone app uses -- port 6467 to pair once with a code the TV shows, port
6466 for everything after: launch an app by deep link (the YouTube app
opens a video and plays it at the best quality it has, 4K included),
press keys, ask which app is up. `androidtvremote2` (Apache-2.0, the
library Home Assistant uses) does the protocol; a certificate Sim
generates is the pairing, kept under ~/.simorgh/tv/.

Pairing is the person's: `tv pair` makes the TV show a code, `tv pair
<code>` finishes. Nothing here pairs on its own.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

CLIENT_NAME = "Simorgh"
#: what the TV's apps open when handed these links (deep links the
#: Android TV remote protocol launches by URL)
APPS: dict[str, str] = {
    "youtube": "https://www.youtube.com/",
    "netflix": "https://www.netflix.com/",
    "disney": "https://www.disneyplus.com/",
    "disney+": "https://www.disneyplus.com/",
    "prime": "https://app.primevideo.com/",
    "prime video": "https://app.primevideo.com/",
    "spotify": "spotify://",
    "plex": "plex://",
    "apple tv": "https://tv.apple.com/",
    "twitch": "https://www.twitch.tv/",
    "home": "market://",       # not an app; `tv key HOME` is the way home
}
#: keys the remote protocol knows, spelt the way a person would say them
KEYS: dict[str, str] = {
    "home": "HOME", "back": "BACK", "up": "DPAD_UP", "down": "DPAD_DOWN", "left": "DPAD_LEFT",
    "right": "DPAD_RIGHT", "ok": "DPAD_CENTER", "select": "DPAD_CENTER", "enter": "ENTER", "play": "MEDIA_PLAY",
    "pause": "MEDIA_PAUSE", "play pause": "MEDIA_PLAY_PAUSE", "stop": "MEDIA_STOP", "next": "MEDIA_NEXT",
    "previous": "MEDIA_PREVIOUS", "rewind": "MEDIA_REWIND", "forward": "MEDIA_FAST_FORWARD", "mute": "MUTE",
    "volume up": "VOLUME_UP", "volume down": "VOLUME_DOWN", "power": "POWER", "sleep": "SLEEP", "wake": "WAKEUP",
    "menu": "MENU", "settings": "SETTINGS", "info": "INFO", "search": "SEARCH", "captions": "CAPTIONS",
}

#: pairings under way: host -> the remote holding the pairing connection
_PENDING: dict[str, object] = {}


def available() -> tuple[bool, str]:
    try:
        import androidtvremote2  # noqa: F401
    except ImportError:
        return False, "the Android TV remote library is not installed: `pip install androidtvremote2`"
    try:
        try:
            from google.protobuf.internal import api_implementation
        except ImportError:  # no protobuf internals to ask: not the cpp build
            return True, ""

        if api_implementation.Type() == "cpp":
            # Live 2026-09-13: pairing died with "'FieldDescriptor' object
            # has no attribute 'is_repeated'" under anaconda's C++ protobuf.
            return False, ("protobuf is running its C++ implementation, which the remote library cannot use; start Sim "
                           "with PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=upb (sim.sh and `python -m simorgh` set it)")
    except Exception:  # noqa: BLE001 -- no api_implementation module: not the cpp build then
        pass
    return True, ""


def youtube_link(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def app_link(name_or_url: str) -> str:
    """A deep link for an app named the way a person names it, or the
    URL itself when it already is one."""
    text = (name_or_url or "").strip()
    low = text.lower()
    if "://" in text:
        return text
    return APPS.get(low, "")


def key_code(name: str) -> str:
    text = (name or "").strip()
    return KEYS.get(text.lower(), text.upper().replace(" ", "_") if text else "")


class AndroidTv:
    """One TV, by host. `remote_cls` is the library's `AndroidTVRemote`,
    or a fake in tests."""

    def __init__(self, host: str, *, certs_dir: Path, client_name: str = CLIENT_NAME, remote_cls=None) -> None:
        self.host = host
        self._certs = Path(certs_dir)
        self._client_name = client_name
        self._remote_cls = remote_cls

    @property
    def certfile(self) -> Path:
        return self._certs / "androidtv-cert.pem"

    @property
    def keyfile(self) -> Path:
        return self._certs / "androidtv-key.pem"

    @property
    def marker(self) -> Path:
        return self._certs / f"paired-{self.host}"

    def paired(self) -> bool:
        return self.certfile.is_file() and self.keyfile.is_file() and self.marker.is_file()

    def _remote(self):
        cls = self._remote_cls
        if cls is None:
            try:
                from androidtvremote2 import AndroidTVRemote
            except ImportError as exc:
                raise RuntimeError("needs androidtvremote2 (pip install androidtvremote2)") from exc
            cls = AndroidTVRemote
        self._certs.mkdir(parents=True, exist_ok=True)
        return cls(self._client_name, str(self.certfile), str(self.keyfile), self.host)

    async def pair_start(self) -> str:
        """Ask the TV to show its code. Returns a problem, or ""."""
        ok, why = available()
        if not ok and self._remote_cls is None:
            return why
        try:
            remote = self._remote()
            await remote.async_generate_cert_if_missing()
            await remote.async_start_pairing()
        except Exception as exc:  # noqa: BLE001
            return f"the TV at {self.host} did not start pairing ({exc.__class__.__name__}: {exc})"
        _PENDING[self.host] = remote
        return ""

    async def pair_finish(self, pin: str) -> str:
        """The code the TV shows, typed by the person. "" when paired."""
        remote = _PENDING.get(self.host)
        if remote is None:
            return "no pairing is under way: `tv pair` first, and the TV shows a code"
        code = "".join(ch for ch in str(pin or "") if ch.isalnum()).upper()
        if not code:
            return "the code is the six characters on the TV's screen"
        try:
            await remote.async_finish_pairing(code)
        except Exception as exc:  # noqa: BLE001
            name = exc.__class__.__name__
            if name == "InvalidAuth":
                return "the code did not match what the TV showed; `tv pair` again for a fresh one"
            _PENDING.pop(self.host, None)
            return f"pairing failed ({name}: {exc}); `tv pair` again"
        _PENDING.pop(self.host, None)
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text("paired\n")
        return ""

    async def _connected(self):
        remote = self._remote()
        await remote.async_connect()
        return remote

    async def _with(self, action) -> str:
        """Connect, do `action(remote)`, disconnect; a problem or ""."""
        if not self.paired():
            return f"not paired with the TV at {self.host}: `tv pair` shows a code on the TV, `tv pair <code>` finishes"
        try:
            remote = await asyncio.wait_for(self._connected(), timeout=15.0)
        except asyncio.TimeoutError:
            return f"the TV at {self.host} did not answer in 15s (is it on?)"
        except Exception as exc:  # noqa: BLE001
            name = exc.__class__.__name__
            if name == "InvalidAuth":
                self.marker.unlink(missing_ok=True)
                return "the TV no longer accepts Sim's pairing; `tv pair` again"
            return f"could not reach the TV at {self.host} ({name}: {exc})"
        try:
            result = action(remote)
            if asyncio.iscoroutine(result):
                result = await result
            await asyncio.sleep(0.3)     # the command is buffered; let it go out
            return str(result or "")
        except Exception as exc:  # noqa: BLE001
            return f"the TV refused ({exc.__class__.__name__}: {exc})"
        finally:
            try:
                remote.disconnect()
            except Exception:  # noqa: BLE001
                pass

    async def launch(self, link: str) -> str:
        """Open an app by deep link; the app decides what to show."""
        if not link:
            return "nothing to open"
        return await self._with(lambda remote: remote.send_launch_app_command(link))

    async def key(self, name: str) -> str:
        code = key_code(name)
        if not code:
            return "which key?"
        return await self._with(lambda remote: remote.send_key_command(code))

    async def current_app(self) -> str:
        found: dict = {}

        def _read(remote):
            found["app"] = str(getattr(remote, "current_app", "") or "")
            return ""
        problem = await self._with(_read)
        return problem or found.get("app", "")


__all__ = ["APPS", "AndroidTv", "CLIENT_NAME", "KEYS", "app_link", "available", "key_code", "youtube_link"]
