"""Sim on the TV: Chromecast through `pychromecast` (open source, an
optional dependency, refused by name when absent).

    cast_devices   the Cast devices on this network
    cast_show      put Sim's page -- a replica of its terminal -- on the TV
    cast_play      a video: framed inside that page, or full screen on the device
    cast_stop      back to the page, or off the device
    cast_volume    the device's volume, with the media domain's own limits

The TV page is served by the interface's HTTP API (`/tv`, static/tv.html)
and reads the live activity from `/api/activity`; the tools here only
tell the device where to look (DashCast, a receiver that shows a URL)
and publish `tv.state` so the page knows what to frame. Every call is a
tool call, so Guardian sees it like any other.

The page must be reachable FROM THE TV, which means the API must not be
bound to loopback. `cast_show` checks that before it casts and says
what to change if it is not.
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ToolContext, ToolResult

_DASHCAST_TIMEOUT_S = 15.0


def available() -> tuple[bool, str]:
    import importlib.util

    if importlib.util.find_spec("pychromecast") is None:
        return False, "needs pychromecast (pip install pychromecast)"
    return True, ""


def lan_address() -> str:
    """This machine's address on the local network, found by asking the
    OS which interface would route to the internet; no packet is sent."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


@dataclass
class Device:
    name: str
    model: str
    host: str


class PyChromecast:
    """The real thing, behind a seam the tests replace.

    One zeroconf instance and one cast browser, started on first use and
    kept for the life of this object: `stop_discovery()` closes the
    zeroconf it was given, and a device found through it cannot connect
    afterwards -- "Zeroconf instance loop must be running, was it
    already stopped?" from the socket thread, and `wait` timing out
    (the creator's screen, 2026-09-12). Discovery is paid once; later
    calls read the browser's live table.
    """

    def __init__(self, *, discovery_s: float = 5.0) -> None:
        self._discovery_s = discovery_s
        self._zconf = None
        self._browser = None
        self._casts: dict[str, object] = {}

    def _start(self) -> None:
        if self._browser is not None:
            return
        import zeroconf
        from pychromecast.discovery import CastBrowser, SimpleCastListener

        self._zconf = zeroconf.Zeroconf()
        self._browser = CastBrowser(SimpleCastListener(), self._zconf)
        self._browser.start_discovery()
        deadline = time.monotonic() + self._discovery_s
        while time.monotonic() < deadline:
            time.sleep(0.25)
            if self._browser.devices and time.monotonic() > deadline - self._discovery_s / 2:
                break

    def devices(self) -> list[Device]:
        self._start()
        out = []
        for info in list(self._browser.devices.values()):
            out.append(Device(name=info.friendly_name, model=str(getattr(info, "model_name", "") or ""),
                              host=str(getattr(info, "host", "") or "")))
        return sorted(out, key=lambda d: d.name.lower())

    def _cast(self, name: str):
        import pychromecast

        self._start()
        cast = self._casts.get(name)
        if cast is None:
            info = next((i for i in self._browser.devices.values() if i.friendly_name == name), None)
            if info is None:
                raise LookupError(name)
            cast = pychromecast.get_chromecast_from_cast_info(info, self._zconf)
            self._casts[name] = cast
        cast.wait(timeout=10)
        return cast

    def close(self) -> None:
        for cast in self._casts.values():
            try:
                cast.disconnect(timeout=2)
            except Exception:  # noqa: BLE001
                pass
        self._casts.clear()
        if self._browser is not None:
            try:
                self._browser.stop_discovery()
            except Exception:  # noqa: BLE001
                pass
        self._browser = self._zconf = None

    def show_page(self, name: str, url: str) -> None:
        from pychromecast.controllers.dashcast import DashCastController

        cast = self._cast(name)
        controller = DashCastController()
        cast.register_handler(controller)
        done = {}

        def _cb(ok, *_rest):  # the library hands (ok, data)
            done["ok"] = ok
        # `force`: the receiver navigates to the page itself instead of
        # framing it. The receiver runs over HTTPS and Sim's page is plain
        # HTTP on the LAN, and a framed HTTP page inside an HTTPS receiver
        # is mixed content Chromium refuses -- the TV showed DashCast's
        # own splash and nothing else (the creator, 2026-09-12).
        controller.load_url(url, force=True, callback_function=_cb)
        # A forced load navigates the receiver away, so no callback ever
        # comes back: a couple of seconds for the command to land is all
        # there is to wait for.
        deadline = time.monotonic() + 2.5
        while "ok" not in done and time.monotonic() < deadline:
            time.sleep(0.2)
        if done.get("ok") is False:
            raise RuntimeError("the device did not load the page")

    def play(self, name: str, url: str, *, content_type: str, title: str) -> None:
        cast = self._cast(name)
        cast.media_controller.play_media(url, content_type, title=title or None)
        cast.media_controller.block_until_active(timeout=10)

    def play_youtube(self, name: str, video_id: str) -> None:
        """YouTube full screen: the Cast protocol has its own YouTube
        receiver, driven by video id -- a YouTube page URL is not a media
        file the media controller could play."""
        from pychromecast.controllers.youtube import YouTubeController

        cast = self._cast(name)
        controller = YouTubeController()
        cast.register_handler(controller)
        controller.play_video(video_id)

    def stop(self, name: str) -> None:
        cast = self._cast(name)
        cast.media_controller.stop()
        cast.quit_app()

    def volume(self, name: str, level: float) -> None:
        self._cast(name).set_volume(level)


_YOUTUBE = re.compile(r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/))([\w-]{6,})")


def youtube_id(url: str) -> str:
    match = _YOUTUBE.search(url or "")
    return match.group(1) if match else ""


def _content_type(url: str) -> str:
    low = url.lower().split("?", 1)[0]
    for ext, kind in ((".mp4", "video/mp4"), (".webm", "video/webm"), (".m3u8", "application/x-mpegURL"),
                      (".mp3", "audio/mp3"), (".wav", "audio/wav"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg"),
                      (".png", "image/png"), (".gif", "image/gif")):
        if low.endswith(ext):
            return kind
    return "video/mp4"


@dataclass
class CastPreferences:
    """What the cast tools remember between calls: the TV to use when a
    call names none. Seeded from `[execution] cast_device`, changed live
    by `cast_use`, and written back to simorgh.toml so it survives a
    restart (the creator, 2026-09-12: "I'd like Sim to remember the
    default TV ... but configurable ... auto discover and allow the user
    to choose")."""

    device: str = ""
    backend: object = None   # the one PyChromecast every cast tool shares, once started


def settings_paths(home: Path | None = None) -> tuple[Path, Path]:
    """`(simorgh.toml, secrets.toml)` -- the files the Kernel actually
    reads, found the way it finds them (kernel/config.py: `--config`,
    `$SIMORGH_CONFIG`, `./simorgh.toml`, `~/.simorgh/simorgh.toml`).
    Deriving them from a tool's `data_dir` wrote `[execution]
    cast_device` into /Users/<x>/ws/simorgh.toml, a file nothing reads
    (the creator's screen, 2026-09-12)."""
    if home is not None:
        return home / "simorgh.toml", home / "secrets.toml"
    default_home = Path("~/.simorgh").expanduser()
    try:
        from simorgh.kernel.config import find_config_path

        found = find_config_path(data_dir=default_home)
    except Exception:  # noqa: BLE001 -- the default is the right answer when the loader cannot say
        found = None
    config_path = found or default_home / "simorgh.toml"
    return config_path, config_path.parent / "secrets.toml"


class _CastTool:
    read_only = False
    reversibility = "reversible"

    def __init__(self, config, *, cast=None, env=None, secrets=None, clock=time.time, reachable=None,
                 prefs: CastPreferences | None = None, settings_home: Path | None = None) -> None:
        self._config = config
        self._given = cast
        self._env = env
        self._secrets = secrets
        self._clock = clock
        self._reachable = reachable
        self._prefs = prefs or CastPreferences(device=str(getattr(config, "cast_device", "") or ""))
        self._settings_home = settings_home

    def _backend(self):
        if self._given is not None:
            return self._given
        ok, why = available()
        if not ok:
            raise RuntimeError(why)
        if self._prefs.backend is None:
            self._prefs.backend = PyChromecast(discovery_s=float(getattr(self._config, "cast_discovery_s", 5.0)))
        return self._prefs.backend

    def _device(self, backend, requested: str) -> tuple[str, str]:
        """`(name, problem)`: the device asked for, the configured one, or
        the only one there is."""
        name = (requested or "").strip() or self._prefs.device
        devices = backend.devices()
        if not devices:
            return "", "refused: no Cast device found on this network (same Wi-Fi as the TV?)"
        names = [d.name for d in devices]
        if name:
            match = [n for n in names if n.lower() == name.lower()] or [n for n in names if name.lower() in n.lower()]
            if not match:
                return "", f"refused: no Cast device called {name!r}; found {', '.join(names)} -- `tv use <name>` picks one"
            return match[0], ""
        if len(names) == 1:
            return names[0], ""
        return "", (f"refused: several Cast devices ({', '.join(names)}); say which, or `tv use <name>` to "
                    f"remember one")

    def _token(self) -> str:
        if self._secrets is not None:
            try:
                value = self._secrets.get("SIM_API_TOKEN")
            except Exception:  # noqa: BLE001
                value = None
            if value:
                return str(value)
        import os

        return str((self._env or os.environ).get("SIM_API_TOKEN") or "")

    def _page_url(self) -> str:
        configured = str(getattr(self._config, "cast_page_url", "") or "").strip()
        base = configured or f"http://{lan_address()}:{int(getattr(self._config, 'cast_page_port', 8765))}/tv"
        token = self._token()
        if token and "token=" not in base:
            base += ("&" if "?" in base else "?") + "token=" + token
        return base

    def _page_reachable(self, url: str) -> str:
        """"" when the TV will be able to fetch the page, else why not."""
        if self._reachable is not None:
            return "" if self._reachable(url) else "the page did not answer"
        status = url.split("/tv", 1)[0] + "/api/status"
        try:
            with urllib.request.urlopen(status, timeout=3.0) as response:  # noqa: S310 -- our own server
                response.read(64)
            return ""
        except Exception as exc:  # noqa: BLE001
            return f"{exc.__class__.__name__}: {exc}"

    async def _publish_state(self, ctx: ToolContext, mode: str, *, url: str = "", title: str = "") -> None:
        bus = getattr(ctx, "bus", None)
        if bus is None:
            return
        payload = {"mode": mode}
        if url:
            payload["url"] = url
        if title:
            payload["title"] = title
        await bus.publish(Message.new(topics.TV_STATE, source="execution", payload=payload))


class CastDevicesTool(_CastTool):
    name = "cast_devices"
    description = "The Cast (Chromecast, Google TV, Nest) devices on this network, by name."
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "properties": {}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        try:
            backend = self._backend()
            devices = await asyncio.to_thread(backend.devices)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if not devices:
            return ToolResult(ok=True, output="no Cast device found on this network")
        default = self._prefs.device
        lines = [f"{'* ' if d.name.lower() == default.lower() else '  '}{d.name}  "
                 f"({d.model or 'Cast'}{', ' + d.host if d.host else ''})" for d in devices]
        tail = ("\n* = the default; `tv use <name>` changes it" if default else
                "\n`tv use <name>` remembers one as the default")
        return ToolResult(ok=True, output="\n".join(lines) + tail,
                          metadata={"devices": [d.name for d in devices], "default": default})


class CastShowTool(_CastTool):
    name = "cast_show"
    description = ("Put Sim's page -- a live replica of its terminal, with room for a video -- on a Cast "
                   "device (the TV). `url` shows another page instead. `device` names the TV when there are several.")
    args_schema = {"type": "object", "properties": {"device": {"type": "string"}, "url": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        url = str(args.get("url") or "").strip() or self._page_url()
        try:
            backend = self._backend()
            name, problem = await asyncio.to_thread(self._device, backend, str(args.get("device") or ""))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if problem:
            return ToolResult(ok=False, error=problem)
        if not args.get("url"):
            why = await asyncio.to_thread(self._page_reachable, url)
            if why:
                return ToolResult(ok=False, error=(
                    f"refused: the TV could not fetch Sim's page at {url.split('?')[0]} ({why}). "
                    "Sim's API is probably bound to loopback: set [interface] http_host = \"0.0.0.0\" and a "
                    "SIM_API_TOKEN, then restart."))
        try:
            await asyncio.to_thread(backend.show_page, name, url)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {name} would not show the page ({exc})")
        await self._publish_state(ctx, "none")
        shown = "Sim's page" if not args.get("url") else url
        return ToolResult(ok=True, output=f"{shown} is on {name}", side_effects=(f"cast_show:{name}",),
                          metadata={"device": name, "url": url.split("?")[0]})


class CastPlayTool(_CastTool):
    name = "cast_play"
    description = ("Play a video or a stream on the TV. `mode` full plays it on the device itself, "
                   "full screen; frame plays it inside Sim's page, beside the terminal (show the page first). "
                   "`url` must be reachable by the TV: a direct mp4/webm/HLS link, or a YouTube page for frame mode.")
    args_schema = {"type": "object", "required": ["url"],
                   "properties": {"url": {"type": "string"}, "mode": {"type": "string", "enum": ["full", "frame"]},
                                  "title": {"type": "string"}, "device": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        url = str(args.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return ToolResult(ok=False, error=(
                "refused: `url` must be a link -- a YouTube page URL (web_search '<topic> youtube' and take the "
                "first youtube.com/watch result) or a direct video link. Do not look for an mp4 file."))
        mode = str(args.get("mode") or "frame").strip().lower()
        title = str(args.get("title") or "")
        if mode == "frame":
            await self._publish_state(ctx, "frame", url=url, title=title)
            return ToolResult(ok=True, output=f"framed inside Sim's page: {title or url}",
                              side_effects=("cast_play:frame",), metadata={"mode": mode, "url": url})
        try:
            backend = self._backend()
            name, problem = await asyncio.to_thread(self._device, backend, str(args.get("device") or ""))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if problem:
            return ToolResult(ok=False, error=problem)
        video = youtube_id(url)
        try:
            if video:
                await asyncio.to_thread(backend.play_youtube, name, video)
            else:
                await asyncio.to_thread(backend.play, name, url, content_type=_content_type(url), title=title)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {name} would not play it ({exc})")
        await self._publish_state(ctx, "full", url=url, title=title)
        return ToolResult(ok=True, output=f"playing full screen on {name}: {title or url}",
                          side_effects=(f"cast_play:{name}",), metadata={"mode": mode, "url": url, "device": name})


class CastStopTool(_CastTool):
    name = "cast_stop"
    description = ("Stop what the TV is playing. `what` frame clears the framed video and leaves Sim's page; "
                   "device (the default) stops the device's own playback and closes its app.")
    args_schema = {"type": "object", "properties": {"what": {"type": "string", "enum": ["frame", "device"]},
                                                    "device": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        what = str(args.get("what") or "device").strip().lower()
        if what == "frame":
            await self._publish_state(ctx, "none")
            return ToolResult(ok=True, output="the framed video is gone; Sim's page stays", side_effects=("cast_stop:frame",))
        try:
            backend = self._backend()
            name, problem = await asyncio.to_thread(self._device, backend, str(args.get("device") or ""))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if problem:
            return ToolResult(ok=False, error=problem)
        try:
            await asyncio.to_thread(backend.stop, name)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {name} would not stop ({exc})")
        await self._publish_state(ctx, "none")
        return ToolResult(ok=True, output=f"{name} stopped", side_effects=(f"cast_stop:{name}",), metadata={"device": name})


class CastVolumeTool(_CastTool):
    name = "cast_volume"
    description = "Set the TV's volume, 0-100. The media domain's limits apply: not loud unattended, not loud in quiet hours."
    args_schema = {"type": "object", "required": ["level"],
                   "properties": {"level": {"type": "number"}, "device": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        try:
            level = int(float(args.get("level")))
        except (TypeError, ValueError):
            return ToolResult(ok=False, error="refused: `level` is a number from 0 to 100")
        level = max(0, min(100, level))
        from .tools import _MediaTool

        verdict = _MediaTool(self._config, secrets=self._secrets, env=self._env, clock=self._clock)._volume_verdict(level)
        if verdict:
            return ToolResult(ok=False, error=f"refused: {verdict}")
        try:
            backend = self._backend()
            name, problem = await asyncio.to_thread(self._device, backend, str(args.get("device") or ""))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if problem:
            return ToolResult(ok=False, error=problem)
        try:
            await asyncio.to_thread(backend.volume, name, level / 100.0)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {name} would not change volume ({exc})")
        return ToolResult(ok=True, output=f"{name} volume {level}", side_effects=(f"cast_volume:{name}",),
                          metadata={"device": name, "level": level})


class CastUseTool(_CastTool):
    name = "cast_use"
    description = ("Remember which Cast device is the TV: the name must be one found on the network "
                   "(cast_devices lists them). Applies at once and is saved to simorgh.toml.")
    args_schema = {"type": "object", "required": ["device"], "properties": {"device": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        wanted = str(args.get("device") or "").strip()
        if not wanted:
            return ToolResult(ok=False, error="refused: say which device; cast_devices lists them")
        try:
            backend = self._backend()
            name, problem = await asyncio.to_thread(self._device, backend, wanted)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if problem:
            return ToolResult(ok=False, error=problem)
        self._prefs.device = name
        from simorgh.voice.settings import persist

        path, _secrets_path = settings_paths(self._settings_home)
        try:
            persist(path, "cast_device", name, section="execution")
            where = f"; saved to {path}"
        except OSError as exc:
            where = f"; NOT saved ({exc})"
        return ToolResult(ok=True, output=f"the TV is {name}{where}", side_effects=("cast_use",),
                          metadata={"device": name})


class CastSetupTool(_CastTool):
    name = "cast_setup"
    description = ("Make the TV able to reach Sim: bind Sim's API to the network, mint a SIM_API_TOKEN if there "
                   "is none, let the interface and execution read it, and remember the TV. Says what changed; "
                   "takes effect at the next restart.")
    args_schema = {"type": "object", "properties": {"device": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        from simorgh.voice.settings import persist

        config_path, secrets_path = settings_paths(self._settings_home)
        changed: list[str] = []
        try:
            persist(config_path, "http_host", "0.0.0.0", section="interface")
            changed.append('[interface] http_host = "0.0.0.0"  (the API answers on the network, not only this machine)')
            persist(config_path, "secrets", ["vault:*", "SIM_API_TOKEN"], section="execution")
            changed.append("[execution] secrets includes SIM_API_TOKEN  (so the cast tools can put it in the page URL)")
        except OSError as exc:
            return ToolResult(ok=False, error=f"refused: could not write {config_path} ({exc})")
        import tomllib

        existing: dict = {}
        if secrets_path.is_file():
            try:
                with secrets_path.open("rb") as handle:
                    existing = tomllib.load(handle)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(ok=False, error=f"refused: {secrets_path} could not be read ({exc})")
        # The file, not the store: a token minted a moment ago is in the
        # file and not yet in the store this process was booted with.
        if not self._token() and not existing.get("SIM_API_TOKEN"):
            import secrets as _secrets

            existing["SIM_API_TOKEN"] = _secrets.token_urlsafe(24)
            try:
                secrets_path.parent.mkdir(parents=True, exist_ok=True)
                body = "".join(f"{k} = {json.dumps(str(v))}\n" for k, v in existing.items())
                tmp = secrets_path.with_suffix(".toml.part")
                tmp.write_text(body)
                tmp.chmod(0o600)
                tmp.replace(secrets_path)
                secrets_path.chmod(0o600)
            except OSError as exc:
                return ToolResult(ok=False, error=f"refused: could not write {secrets_path} ({exc})")
            changed.append(f"SIM_API_TOKEN minted in {secrets_path}  (mode 600; the page URL carries it)")
        else:
            changed.append("SIM_API_TOKEN already set; kept")
        wanted = str(args.get("device") or "").strip()
        device_note = ""
        try:
            backend = self._backend()
            devices = await asyncio.to_thread(backend.devices)
        except Exception as exc:  # noqa: BLE001
            devices, device_note = [], f"could not look for TVs ({exc})"
        names = [d.name for d in devices]
        if wanted or len(names) == 1:
            name, problem = await asyncio.to_thread(self._device, backend, wanted or names[0])
            if problem:
                device_note = problem
            else:
                self._prefs.device = name
                persist(config_path, "cast_device", name, section="execution")
                changed.append(f"[execution] cast_device = {name!r}")
        elif names:
            device_note = f"found {', '.join(names)}: `tv use <name>` picks the TV"
        elif not device_note:
            device_note = "no Cast device found on this network yet"
        lines = ["set up for the TV:"] + [f"  - {c}" for c in changed]
        if device_note:
            lines.append(f"  - {device_note}")
        lines.append("restart Sim, then `tv show`")
        return ToolResult(ok=True, output="\n".join(lines), side_effects=("cast_setup",),
                          metadata={"changed": changed, "device": self._prefs.device})


def cast_tools(config, **kwargs) -> list:
    kwargs = {k: v for k, v in kwargs.items() if k in ("cast", "env", "secrets", "clock", "reachable", "settings_home")}
    prefs = CastPreferences(device=str(getattr(config, "cast_device", "") or ""))
    return [CastDevicesTool(config, prefs=prefs, **kwargs), CastShowTool(config, prefs=prefs, **kwargs),
            CastPlayTool(config, prefs=prefs, **kwargs), CastStopTool(config, prefs=prefs, **kwargs),
            CastVolumeTool(config, prefs=prefs, **kwargs), CastUseTool(config, prefs=prefs, **kwargs),
            CastSetupTool(config, prefs=prefs, **kwargs)]


__all__ = ["CastDevicesTool", "CastPlayTool", "CastPreferences", "CastSetupTool", "CastShowTool", "CastStopTool", "CastUseTool",
           "CastVolumeTool", "Device", "settings_paths", "youtube_id",
           "PyChromecast", "available", "cast_tools", "lan_address"]
