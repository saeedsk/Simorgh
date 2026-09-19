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
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.messages.ui import DASH_KEYS
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
        import threading

        self._discovery_s = discovery_s
        self._zconf = None
        self._browser = None
        self._casts: dict[str, object] = {}
        # One socket per TV, one writer at a time. Every tool call runs in
        # its own worker thread, and two writing the same TLS socket at
        # once corrupted it -- "BAD_WRITE_RETRY", "CIPHER_OPERATION_FAILED",
        # then "EOF occurred in violation of protocol" on every write
        # after, and the video never came (the creator's terminal,
        # 2026-09-13, while the idle watchers polled beside a play).
        self._lock = threading.RLock()

    def _start(self) -> None:
        if self._browser is not None:
            return
        try:
            import zeroconf
            from pychromecast.discovery import CastBrowser, SimpleCastListener
        except ImportError as exc:
            raise RuntimeError("needs pychromecast (pip install pychromecast)") from exc

        import logging

        # A broken socket logged one line per write to the terminal, over
        # the conversation; the tool result says what failed.
        logging.getLogger("pychromecast.socket_client").setLevel(logging.CRITICAL)
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
        try:
            import pychromecast
        except ImportError as exc:
            raise RuntimeError("needs pychromecast (pip install pychromecast)") from exc

        self._start()
        cast = self._casts.get(name)
        if cast is not None and not self._alive(cast):
            # A dead socket stays dead: drop it and connect afresh.
            self._casts.pop(name, None)
            try:
                cast.disconnect(timeout=2)
            except Exception:  # noqa: BLE001
                pass
            cast = None
        if cast is None:
            info = next((i for i in self._browser.devices.values() if i.friendly_name == name), None)
            if info is None:
                raise LookupError(name)
            cast = pychromecast.get_chromecast_from_cast_info(info, self._zconf)
            self._casts[name] = cast
        cast.wait(timeout=10)
        return cast

    @staticmethod
    def _alive(cast) -> bool:
        client = getattr(cast, "socket_client", None)
        if client is None:
            return True
        connected = getattr(client, "is_connected", True)
        stopped = getattr(getattr(client, "stop", None), "is_set", lambda: False)()
        return bool(connected) and not stopped

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
        with self._lock:
            try:
                from pychromecast.controllers.dashcast import DashCastController
            except ImportError as exc:
                raise RuntimeError("needs pychromecast (pip install pychromecast)") from exc

            cast = self._cast(name)
            # The dashboard's receiver may still be "running" in the
            # background after the TV went to its home screen or another app
            # took over (the K-pop chart in the YouTube app): loading a URL
            # into that session changes nothing on screen, and `tv show`
            # reported the dashboard up on a TV showing its launcher, three
            # times (the creator, 2026-09-14). Close it first, so the load
            # launches the receiver again -- in front.
            try:
                from pychromecast.config import APP_DASHCAST
            except ImportError:  # an older pychromecast: the id it has always had
                APP_DASHCAST = "84912283"
            if getattr(cast, "app_id", None) == APP_DASHCAST:
                try:
                    cast.quit_app()
                    deadline = time.monotonic() + 3.0
                    while getattr(cast, "app_id", None) == APP_DASHCAST and time.monotonic() < deadline:
                        time.sleep(0.2)
                except Exception:  # noqa: BLE001 -- a failed quit still leaves the load to try
                    pass
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
        with self._lock:
            cast = self._cast(name)
            cast.media_controller.play_media(url, content_type, title=title or None)
            cast.media_controller.block_until_active(timeout=10)

    def media_state(self, name: str) -> str:
        """The device's player state: PLAYING, PAUSED, BUFFERING, IDLE,
        STOPPED, UNKNOWN -- for knowing when a video has ended."""
        with self._lock:
            cast = self._cast(name)
            try:
                cast.media_controller.update_status()
            except Exception:  # noqa: BLE001 -- the last known status is the answer then
                pass
            status = cast.media_controller.status
            state = str(getattr(status, "player_state", "") or "UNKNOWN").upper()
            if state == "IDLE":
                reason = str(getattr(status, "idle_reason", "") or "").upper()
                # FINISHED is the video ending; CANCELLED / INTERRUPTED / ERROR
                # is somebody else's doing and not a cue to put the dashboard back
                return "IDLE" if reason in ("", "FINISHED") else "STOPPED"
            return state

    def play_youtube(self, name: str, video_id: str) -> None:
        """YouTube full screen through the Cast protocol's own YouTube
        receiver -- which answers "400 screen_ids parameter error" since
        2026-09; kept for the day it works again."""
        with self._lock:
            try:
                from pychromecast.controllers.youtube import YouTubeController
            except ImportError as exc:
                raise RuntimeError("needs pychromecast (pip install pychromecast)") from exc

            cast = self._cast(name)
            controller = YouTubeController()
            cast.register_handler(controller)
            controller.play_video(video_id)

    def stop(self, name: str) -> None:
        with self._lock:
            cast = self._cast(name)
            cast.media_controller.stop()
            cast.quit_app()

    def volume(self, name: str, level: float) -> None:
        with self._lock:
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
    #: bumped by every show/play/stop; a watcher from an earlier video
    #: that sees it changed stands down (live 2026-09-13: four such
    #: watchers, and one put the dashboard over a video just started)
    generation: int = 0


def settings_paths(home: Path | None = None) -> tuple[Path, Path]:
    """`(simorgh.toml, secrets.toml)` -- the files the Kernel actually
    reads, found the way it finds them (kernel/config.py: `--config`,
    `$SIMORGH_CONFIG`, `./simorgh.toml`, `~/.simorgh/simorgh.toml`).
    Deriving them from a tool's `data_dir` wrote `[execution]
    cast_device` into /Users/<x>/ws/simorgh.toml, a file nothing reads
    (the creator's screen, 2026-09-12)."""
    if home is not None:
        return home / "simorgh.toml", home / "secrets.toml"
    from simorgh.contracts.settings import config_path as kernel_config_path

    config_path = kernel_config_path()
    return config_path, config_path.parent / "secrets.toml"


class _CastTool:
    #: How long a cast with no PLAYING state yet may sit IDLE before the
    #: watcher decides it is over. A class attribute so a test can shorten
    #: it (it was an inline 30.0 that made one test take 30 s).
    IDLE_GRACE_S = 30.0

    read_only = False
    reversibility = "reversible"
    #: seconds between waking the TV and casting to it
    _WAKE_SETTLE_S = 1.0

    def __init__(self, config, *, cast=None, env=None, secrets=None, clock=time.time, reachable=None,
                 prefs: CastPreferences | None = None, settings_home: Path | None = None, fetch=None,
                 media_dir: Path | None = None, remote_cls=None, certs_dir: Path | None = None,
                 charts_source=None) -> None:
        self._config = config
        # the dashboard's charts (interface/dashfeeds.py), read over Sim's
        # own API; a callable returning the same dict in tests
        self._charts_source = charts_source
        # tvmedia.fetch, or a fake: a YouTube video as a file for the TV
        self._fetch = fetch
        self._media_dir = media_dir
        self._fetches: set[asyncio.Task] = set()
        # the Android TV remote protocol (media/androidtv.py): the library's
        # class or a fake, and where the pairing certificate lives
        self._remote_cls = remote_cls
        self._certs_dir = certs_dir
        self._given = cast
        self._env = env
        self._secrets = secrets
        self._clock = clock
        self._reachable = reachable
        self._prefs = prefs or CastPreferences(device=str(getattr(config, "cast_device", "") or ""))
        self._settings_home = settings_home

    def _bump(self) -> int:
        self._prefs.generation += 1
        return self._prefs.generation

    def _androidtv(self, host: str):
        from .androidtv import AndroidTv

        certs = self._certs_dir or settings_paths(self._settings_home)[0].parent / "tv"
        return AndroidTv(host, certs_dir=certs, remote_cls=self._remote_cls)

    async def _wake(self, backend, name: str, *, timeout_s: float = 6.0) -> bool:
        """Wake the TV before casting to it. A cast to a TV sitting in its
        screensaver loaded behind it and the screen stayed dark (the
        creator, 2026-09-14). The Android TV remote's WAKEUP key dismisses
        the screensaver without toggling power. Best effort: an unpaired or
        silent TV never holds up the cast. Returns whether it woke."""
        host = await asyncio.to_thread(self._host_of, backend, name)
        if not host:
            return False
        try:
            tv = self._androidtv(host)
            if not tv.paired():
                return False
            problem = await asyncio.wait_for(tv.key("wake"), timeout=timeout_s)
        except Exception:  # noqa: BLE001 -- asyncio.TimeoutError included: the cast goes ahead
            return False
        if problem:
            return False
        await asyncio.sleep(self._WAKE_SETTLE_S)  # let the screensaver close before the page loads over it
        return True

    def _host_of(self, backend, name: str) -> str:
        try:
            for device in backend.devices():
                if device.name == name:
                    return str(device.host or "")
        except Exception:  # noqa: BLE001
            pass
        return ""

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

    def _page_url(self, page: str = "tv") -> str:
        """Where the TV fetches Sim's page: `/tv` (the terminal replica) or
        `/dash` (the glass dashboard), `/remote` (the phone's remote)."""
        configured = str(getattr(self._config, "cast_page_url", "") or "").strip()
        base = configured or f"http://{lan_address()}:{int(getattr(self._config, 'cast_page_port', 8765))}/tv"
        if page != "tv":
            base = base.rsplit("/tv", 1)[0] + "/" + page if "/tv" in base else base.rstrip("/") + "/" + page
        token = self._token()
        if token and "token=" not in base:
            base += ("&" if "?" in base else "?") + "token=" + token
        return base

    def _page_reachable(self, url: str) -> str:
        """"" when the TV will be able to fetch the page, else why not."""
        if self._reachable is not None:
            return "" if self._reachable(url) else "the page did not answer"
        # Whatever page the URL names, liveness is the API's own route on the same host.
        parts = urllib.parse.urlsplit(url)
        status = f"{parts.scheme}://{parts.netloc}/api/status"
        try:
            with urllib.request.urlopen(status, timeout=3.0) as response:  # noqa: S310 -- our own server
                response.read(64)
            return ""
        except Exception as exc:  # noqa: BLE001
            return f"{exc.__class__.__name__}: {exc}"

    async def _publish_state(self, ctx: ToolContext, mode: str, *, url: str = "", title: str = "", **extra) -> None:
        bus = getattr(ctx, "bus", None)
        if bus is None:
            return
        payload = {"mode": mode}
        if url:
            payload["url"] = url
        if title:
            payload["title"] = title
        payload.update({k: v for k, v in extra.items() if v not in ("", None, False)})
        await bus.publish(Message.new(topics.TV_STATE, source="execution", payload=payload))

    async def _native_youtube(self, ctx: ToolContext, backend, name: str, video: str, url: str,
                              title: str) -> ToolResult | None:
        """The TV's own YouTube app, when Sim is paired with the TV
        (media/androidtv.py): it plays at the best quality the video has,
        4K included, which no Cast path can. None when not paired or the
        TV would not take it -- the caller falls back to the file."""
        from .androidtv import youtube_link

        host = self._host_of(backend, name)
        if not host:
            return None
        tv = self._androidtv(host)
        if not tv.paired():
            return None
        problem = await tv.launch(youtube_link(video))
        if problem:
            await self._publish_state(ctx, "full", url=url, title=title, problem=problem)
            return None
        self._bump()
        await self._publish_state(ctx, "full", url=url, title=title, native="YouTube")
        return ToolResult(ok=True, output=(f"playing in {name}'s own YouTube app, at the best quality the video has "
                                           f"(4K when it is there): {title or url}. Say \"show your dashboard\" to come back"),
                          side_effects=(f"cast_play:{name}",), metadata={"mode": "full", "url": url, "device": name,
                                                                         "video": video, "native": "YouTube"})

    def _charts(self) -> dict:
        """`{"kpop": {"label", "sub", "songs": [...]}, "uspop": {...}}` from
        the dashboard's feeds, over Sim's API (the tool and the page are
        one process apart on purpose)."""
        if self._charts_source is not None:
            return dict(self._charts_source() or {})
        import json as _json
        import urllib.request
        from urllib.parse import urlsplit

        parts = urlsplit(self._page_url("dash"))
        url = f"{parts.scheme}://{parts.netloc}/api/dash/data" + (f"?{parts.query}" if parts.query else "")
        with urllib.request.urlopen(url, timeout=8) as response:
            return dict((_json.loads(response.read().decode("utf-8")) or {}).get("charts") or {})

    async def _start_chart(self, ctx: ToolContext, chart: str, device: str = "") -> ToolResult:
        """Play a chart on the TV, top to bottom: the TV's own YouTube app
        when paired (YouTube rolls on from the first), else the files
        one after another, full screen, the dashboard back at the end.
        The dashboard turns to the Charts view either way."""
        key = CHART_NAMES.get((chart or "kpop").strip().lower(), "")
        if not key:
            return ToolResult(ok=False, error=f"refused: no chart called {chart!r}; the charts are kpop and uspop")
        try:
            backend = self._backend()
            name, problem = await asyncio.to_thread(self._device, backend, device)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if problem:
            return ToolResult(ok=False, error=problem)
        try:
            charts = await asyncio.to_thread(self._charts)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: could not read the charts from the dashboard ({exc})")
        entry = charts.get(key) or {}
        songs = [s for s in (entry.get("songs") or []) if s.get("video")]
        if not songs:
            return ToolResult(ok=False, error=f"refused: the {entry.get('label') or key} chart has not been fetched yet; "
                                              "the dashboard fills it within a few minutes of starting")
        label = str(entry.get("label") or key)
        bus = getattr(ctx, "bus", None)
        if bus is not None:
            await bus.publish(Message.new(topics.DASH_STATE, source="execution", payload={"view": "charts"}))
        items = [(str(s["video"]), f"{s['name']} — {s['artist']}") for s in songs]
        host = self._host_of(backend, name)
        tv = self._androidtv(host) if host else None
        first = items[0]
        if tv is not None and tv.paired():
            from .androidtv import youtube_link

            problem = await tv.launch(youtube_link(first[0]))
            if not problem:
                self._bump()
                await self._publish_state(ctx, "full", url=youtube_link(first[0]), title=first[1], native="YouTube",
                                          queue=[t for _v, t in items])
                return ToolResult(ok=True, output=(f"the {label} chart is playing in {name}'s YouTube app, from #1: "
                                                   f"{first[1]}; YouTube rolls on from there. Say \"next\" to skip"),
                                  side_effects=(f"tv_charts:{name}",),
                                  metadata={"chart": key, "device": name, "native": "YouTube", "count": len(items)})
        task = asyncio.create_task(self._play_queue(ctx, backend, name, items, label))
        self._fetches.add(task)
        task.add_done_callback(self._fetches.discard)
        return ToolResult(ok=True, output=(f"playing the {label} chart on {name}, full screen, one after another from #1: "
                                           f"{first[1]} -- the first starts in a few seconds; the dashboard comes back "
                                           "after the last"),
                          side_effects=(f"tv_charts:{name}",), metadata={"chart": key, "device": name, "count": len(items)})

    async def _play_queue(self, ctx: ToolContext, backend, device: str, items: list[tuple[str, str]], label: str) -> None:
        from . import tvmedia

        fetch = self._fetch or tvmedia.fetch
        for index, (video, title) in enumerate(items):
            await self._publish_state(ctx, "full", url=f"https://www.youtube.com/watch?v={video}", title=title,
                                      fetching=True, queue=[t for _v, t in items[index:]])
            try:
                path, problem = await asyncio.to_thread(fetch, video, self._media_dir)
            except Exception as exc:  # noqa: BLE001
                path, problem = None, f"the fetch failed: {exc}"
            if path is None:
                continue        # a song without a fetchable video: the next one
            generation = self._bump()
            try:
                await asyncio.to_thread(backend.play, device, self._media_url(path.name), content_type="video/mp4",
                                        title=title)
            except Exception as exc:  # noqa: BLE001
                await self._publish_state(ctx, "full", url=f"https://www.youtube.com/watch?v={video}", title=title,
                                          problem=f"{device} would not play it ({exc})")
                return
            await self._publish_state(ctx, "full", url=f"https://www.youtube.com/watch?v={video}", title=title,
                                      stream=f"/tv/media/{path.name}", queue=[t for _v, t in items[index:]])
            if not await self._wait_finished(backend, device, generation):
                return          # somebody else drove the TV: the chart stops here
        await self._dashboard_back(ctx, backend, device)

    def _media_url(self, name: str) -> str:
        """Where the TV fetches a cached video from: Sim's API, the same
        host the page comes from; the route is open on the LAN."""
        from urllib.parse import urlsplit

        parts = urlsplit(self._page_url("tv"))
        return f"{parts.scheme}://{parts.netloc}/tv/media/{name}"

    async def _fetch_for_tv(self, ctx: ToolContext, video: str, url: str, title: str, *, mode: str = "frame",
                            device: str = "", backend=None) -> None:
        """Fetch the YouTube video as a file (tvmedia); then either tell
        the page where it is (frame) or cast the file to the TV's plain
        media player (full). Or say why not. Runs after `cast_play` has
        answered, so the person is not kept waiting on the download."""
        from . import tvmedia

        fetch = self._fetch or tvmedia.fetch
        try:
            path, problem = await asyncio.to_thread(fetch, video, self._media_dir)
        except Exception as exc:  # noqa: BLE001
            path, problem = None, f"the fetch failed: {exc}"
        if path is None:
            await self._publish_state(ctx, mode, url=url, title=title, problem=problem)
            return
        stream = f"/tv/media/{path.name}"
        if mode == "frame" and backend is None:
            # No TV to speak of: the page is in a browser and plays the file itself.
            try:
                backend = self._backend()
                device, problem = await asyncio.to_thread(self._device, backend, "")
            except Exception:  # noqa: BLE001
                backend, device, problem = None, "", "no TV"
            if problem or backend is None:
                await self._publish_state(ctx, "frame", url=url, title=title, stream=stream)
                return
            # The TV's browser draws a framed video white (the creator,
            # 2026-09-13: "it plays but it shows as a white screen"), so
            # on the TV a framed video is full screen, and the dashboard
            # comes back when it ends.
            mode = "full"
        generation = self._bump()
        try:
            await asyncio.to_thread(backend.play, device, self._media_url(path.name), content_type="video/mp4",
                                    title=title)
        except Exception as exc:  # noqa: BLE001
            await self._publish_state(ctx, "full", url=url, title=title, problem=f"{device} would not play it ({exc})")
            return
        await self._publish_state(ctx, "full", url=url, title=title, stream=stream)
        await self._dashboard_back_after(ctx, backend, device, generation)

    #: how often the TV is asked whether the video has ended
    IDLE_POLL_S = 10.0
    #: give up watching after this long (a film, and then some)
    WATCH_MAX_S = 4 * 3600.0

    async def _dashboard_back_after(self, ctx: ToolContext, backend, device: str, generation: int) -> None:
        """When the video ends the plain player sits on its idle card;
        the dashboard is put back."""
        if await self._wait_finished(backend, device, generation):
            await self._dashboard_back(ctx, backend, device)

    async def _wait_finished(self, backend, device: str, generation: int) -> bool:
        """True when the video on `device` has ended of itself. False
        when another show/play/stop has happened since (`generation`),
        when it was stopped rather than finished -- somebody else is
        driving the TV then -- or when the TV went away. Polls the
        device's player state."""
        if not hasattr(backend, "media_state"):
            return False
        started = time.monotonic()
        seen_playing = False
        while time.monotonic() - started < self.WATCH_MAX_S:
            await asyncio.sleep(self.IDLE_POLL_S)
            if self._prefs.generation != generation:
                return False
            try:
                state = await asyncio.to_thread(backend.media_state, device)
            except Exception:  # noqa: BLE001
                return False
            if state in ("PLAYING", "PAUSED", "BUFFERING"):
                seen_playing = True
                continue
            if state == "STOPPED":
                return False
            if state in ("IDLE", "UNKNOWN") and (seen_playing or time.monotonic() - started > self.IDLE_GRACE_S):
                return self._prefs.generation == generation
        return False

    async def _dashboard_back(self, ctx: ToolContext, backend, device: str) -> None:
        self._bump()
        try:
            await asyncio.to_thread(backend.show_page, device, self._page_url("dash"))
        except Exception:  # noqa: BLE001
            return
        await self._publish_state(ctx, "none")


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


#: The dashboard's views and the words people use for them (dash.html).
DASH_VIEWS = ("home", "cameras", "markets", "charts", "ambient")
# News, Discover, Terminal and Media were folded into Home (the creator, 2026-09-14)
DASH_ALIASES = {"deck": "home", "start": "home", "news": "home", "headlines": "home", "discover": "home",
                "world": "home", "media": "home", "video": "home", "stocks": "markets", "market": "markets",
                "camera": "cameras", "cams": "cameras", "clock": "ambient", "screensaver": "ambient",
                "chart": "charts", "kpop": "charts", "k-pop": "charts", "music charts": "charts",
                "top songs": "charts", "hits": "charts"}
#: the charts the dashboard carries (interface/dashfeeds.py CHARTS) and how people name them
CHART_NAMES = {"kpop": "kpop", "k-pop": "kpop", "korea": "kpop", "korean": "kpop", "us": "uspop", "uspop": "uspop",
               "us pop": "uspop", "pop": "uspop", "american": "uspop", "america": "uspop", "usa": "uspop"}


def _dash_view(word: str) -> str:
    """The dashboard view `word` names, or ""; "terminal" is the bare
    terminal page and not a view here."""
    low = (word or "").strip().lower()
    low = DASH_ALIASES.get(low, low)
    return low if low in DASH_VIEWS else ""


class CastShowTool(_CastTool):
    name = "cast_show"
    description = ("Put Sim's page on a Cast device (the TV). page dash (the default) is the glass dashboard -- home "
                   "(news, discover and media all rotate through it), cameras, markets, charts, ambient, with Sim's "
                   "terminal in it; page tv is the bare terminal replica with room for a video. `url` shows another "
                   "page instead. `device` names the TV when there are several.")
    args_schema = {"type": "object", "properties": {"device": {"type": "string"}, "url": {"type": "string"},
                                                    "page": {"type": "string", "enum": ["tv", "dash"]},
                                                    "view": {"type": "string", "enum": list(DASH_VIEWS)}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        target = str(args.get("target") or "").strip()  # the marker form: a URL, a page name or a device name
        if target and "=" in target:
            # `CAST_SHOW: page=home` -- live 2026-09-13, read as a TV called "page=home".
            from simorgh.contracts.toolargs import key_values

            pairs = {k: str(v) for k, v in key_values(target).items() if k in ("page", "device", "url", "view")}
            if pairs:
                args, target = {**args, **pairs}, ""
        if target and not args.get("url") and not args.get("device") and not args.get("page") and not args.get("view"):
            low = target.lower()
            if low.startswith(("http://", "https://")):
                key = "url"
            elif low in ("tv", "terminal", "tui", "dash", "dashboard") or _dash_view(low):
                key = "page"
            else:
                key = "device"
            args = {**args, key: target}
        page = str(args.get("page") or "dash").strip().lower()
        view = _dash_view(str(args.get("view") or ""))
        if page not in ("tv", "terminal", "tui", "dash", "dashboard") and _dash_view(page):
            # `cast_show home`, `cast_show cameras`: the dashboard, opened
            # on that view -- live 2026-09-13 "home" was taken for a TV.
            view, page = _dash_view(page), "dash"
        page = "tv" if page in ("tv", "terminal", "tui") else "dash"
        url = str(args.get("url") or "").strip() or self._page_url(page)
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
        woke = await self._wake(backend, name)
        self._bump()
        try:
            await asyncio.to_thread(backend.show_page, name, url)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {name} would not show the page ({exc})")
        await self._publish_state(ctx, "none")
        bus = getattr(ctx, "bus", None)
        if view and page == "dash" and bus is not None:
            await bus.publish(Message.new(topics.DASH_STATE, source="execution", payload={"view": view}))
        shown = url if args.get("url") else (f"Sim's dashboard ({view})" if view and page == "dash"
                                             else "Sim's dashboard" if page == "dash" else "Sim's page")
        return ToolResult(ok=True, output=f"{shown} is on {name}" + (" (woke the TV)" if woke else ""),
                          side_effects=(f"cast_show:{name}",),
                          metadata={"device": name, "url": url.split("?")[0], "page": page, "woke": woke,
                                    **({"view": view} if view else {})})


class CastPlayTool(_CastTool):
    name = "cast_play"
    description = ("Play a video or a stream on the TV. `mode` full plays it on the device itself, "
                   "full screen; frame plays it inside Sim's page, beside the terminal (show the page first). "
                   "`url` must be reachable by the TV: a direct mp4/webm/HLS link, or a YouTube page for frame mode.")
    args_schema = {"type": "object", "required": ["url"],
                   "properties": {"url": {"type": "string"}, "mode": {"type": "string", "enum": ["full", "frame"]},
                                  "title": {"type": "string"}, "device": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        words = str(args.get("url") or "").split()
        url = words[0].strip("<>'\"") if words else ""
        extra = [w for w in words[1:]]
        if extra and not args.get("mode") and extra[0].lower() in ("full", "fullscreen", "frame", "framed", "box"):
            args = {**args, "mode": "full" if extra[0].lower() in ("full", "fullscreen") else "frame"}
            extra = extra[1:]
        if extra and not args.get("device"):
            args = {**args, "device": " ".join(extra)}
        if not url.lower().startswith(("http://", "https://")):
            return ToolResult(ok=False, error=(
                "refused: `url` must be a link -- a YouTube page URL (web_search '<topic> youtube' and take the "
                "first youtube.com/watch result) or a direct video link. Do not look for an mp4 file."))
        mode = str(args.get("mode") or "frame").strip().lower()
        title = str(args.get("title") or "")
        if mode == "frame":
            video = youtube_id(url)
            if video:
                try:
                    backend = self._backend()
                    name, problem = await asyncio.to_thread(self._device, backend, str(args.get("device") or ""))
                except Exception:  # noqa: BLE001
                    backend, name, problem = None, "", "no TV"
                if backend is not None and not problem:
                    native = await self._native_youtube(ctx, backend, name, video, url, title)
                    if native:
                        return native
                # YouTube's embedded player is blank and silent inside a
                # Cast receiver (the creator's TV, 2026-09-13): the page
                # gets the video as a file instead, fetched now.
                await self._publish_state(ctx, "frame", url=url, title=title, fetching=True)
                task = asyncio.create_task(self._fetch_for_tv(ctx, video, url, title))
                self._fetches.add(task)
                task.add_done_callback(self._fetches.discard)
                return ToolResult(ok=True, output=(f"playing on the TV: {title or url} -- fetching the video first; it "
                                                   "starts full screen in a few seconds, with sound, and the dashboard "
                                                   "comes back when it ends (the TV cannot draw a video inside the page)"),
                                  side_effects=("cast_play:frame",), metadata={"mode": mode, "url": url, "video": video})
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
        if video:
            native = await self._native_youtube(ctx, backend, name, video, url, title)
            if native:
                return native
            # YouTube's Cast receiver stopped taking Sim's requests ("400
            # screen_ids parameter error", the creator's TV, 2026-09-13):
            # the video goes to the TV as a file through its plain media
            # player instead -- the same fetch the framed page uses.
            await self._publish_state(ctx, "full", url=url, title=title, fetching=True)
            task = asyncio.create_task(self._fetch_for_tv(ctx, video, url, title, mode="full", device=name,
                                                          backend=backend))
            self._fetches.add(task)
            task.add_done_callback(self._fetches.discard)
            return ToolResult(ok=True, output=(f"playing full screen on {name}: {title or url} -- fetching the video "
                                               "for the TV first; it starts in a few seconds"),
                              side_effects=(f"cast_play:{name}",), metadata={"mode": mode, "url": url, "device": name,
                                                                             "video": video})
        try:
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
            self._bump()
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
        raw = args.get("level")
        if isinstance(raw, str) and raw.split()[1:] and not args.get("device"):
            args = {**args, "device": " ".join(raw.split()[1:])}
            raw = raw.split()[0]
        try:
            level = int(float(str(raw).rstrip("%")))
        except (TypeError, ValueError):
            return ToolResult(ok=False, error="refused: `level` is a number from 0 to 100")
        if level < 0 or level > 100:
            return ToolResult(ok=False, error=f"refused: `level` is a number from 0 to 100, not {level}")
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


class DashViewTool(_CastTool):
    """Steer the glass dashboard on the TV. A Cast receiver never sees the
    TV remote's keys, so the dashboard is turned from here: by voice or
    the CLI (`tv view markets`), or from the phone page whose link this
    tool hands out (`action=remote`). Publishes `ui.dash.state`; the
    HTTP API keeps it and the page polls it."""

    name = "dash_view"
    read_only = False
    reversibility = "reversible"
    description = ("Change what Sim's dashboard on the TV shows: `view` is one of home, cameras, markets, charts, "
                   "ambient (news, discover, media and terminal all live inside home now); `timeframe` 1D/1W/1M/1Y and "
                   "`symbol` pick the markets chart; `rotate_s` cycles the views every N seconds (0 stops); `scale` "
                   "fixes the page's zoom on a TV that misreports its size (0 = fit); `live_max` caps how many camera "
                   "feeds play at once, `live_step_s` how often the live window slides one camera on; `video_quality` "
                   "light|full and `video_sound` on/off for the embedded video. `action` remote answers the phone "
                   "remote's link; link, the dashboard's own link for a browser (with the token).")
    args_schema = {"type": "object", "properties": {
        "view": {"type": "string"}, "timeframe": {"type": "string"}, "symbol": {"type": "string"},
        "rotate_s": {"type": "number"}, "scale": {"type": "number"}, "live_max": {"type": "integer"},
        "live_step_s": {"type": "number"}, "video_sound": {"type": "boolean"},
        "video_quality": {"type": "string", "enum": ["light", "full"]}, "action": {"type": "string", "enum": ["view", "remote", "link"]}}}
    VIEWS = DASH_VIEWS
    ALIASES = {**DASH_ALIASES, "tv": "home", "terminal": "home"}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        action = str(args.get("action") or "").strip().lower()
        if action == "remote":
            url = self._page_url("remote")
            return ToolResult(ok=True, output=f"the remote for the TV dashboard, for a phone on this Wi-Fi: {url}",
                              metadata={"url": url})
        if action == "link":
            # The dashboard for a browser: with the token, or the live
            # activity is withheld and the Sim box shows only the banner
            # (the creator's Mac, 2026-09-12).
            url = self._page_url("dash")
            return ToolResult(ok=True, output=f"the dashboard, for a browser on this Wi-Fi (the token is in the link): {url}",
                              metadata={"url": url})
        view = str(args.get("view") or "").strip().lower()
        view = self.ALIASES.get(view, view)
        payload: dict = {}
        if view:
            if view not in self.VIEWS:
                return ToolResult(ok=False, error=f"refused: no view called {view!r}; the views are {', '.join(self.VIEWS)}")
            payload["view"] = view
        tf = str(args.get("timeframe") or "").strip().upper()
        if tf:
            if tf not in ("1D", "1W", "1M", "1Y"):
                return ToolResult(ok=False, error="refused: `timeframe` is one of 1D, 1W, 1M, 1Y")
            payload["timeframe"] = tf
            payload.setdefault("view", "markets")
        if args.get("symbol"):
            payload["symbol"] = str(args["symbol"]).strip().upper()[:12]
            payload.setdefault("view", "markets")
        if "rotate_s" in args and args["rotate_s"] is not None:
            try:
                payload["rotate_s"] = max(0, min(3600, int(float(args["rotate_s"]))))
            except (TypeError, ValueError):
                return ToolResult(ok=False, error="refused: `rotate_s` is a number of seconds (0 stops)")
        if "scale" in args and args["scale"] is not None:
            try:
                payload["scale"] = max(0.0, min(4.0, float(args["scale"])))
            except (TypeError, ValueError):
                return ToolResult(ok=False, error="refused: `scale` is a factor like 0.5, or 0 to fit the screen")
        if "live_max" in args and args["live_max"] is not None:
            try:
                payload["live_max"] = max(0, min(16, int(float(args["live_max"]))))
            except (TypeError, ValueError):
                return ToolResult(ok=False, error="refused: `live_max` is a count, 0-16")
        if "live_step_s" in args and args["live_step_s"] is not None:
            try:
                payload["live_step_s"] = max(0.5, min(600.0, float(args["live_step_s"])))
            except (TypeError, ValueError):
                return ToolResult(ok=False, error="refused: `live_step_s` is seconds, 0.5-600")
        quality = str(args.get("video_quality") or "").strip().lower()
        if quality:
            if quality not in ("light", "full"):
                return ToolResult(ok=False, error="refused: `video_quality` is light or full")
            payload["video_quality"] = quality
        if "video_sound" in args and args["video_sound"] is not None:
            raw = args["video_sound"]
            payload["video_sound"] = raw if isinstance(raw, bool) else str(raw).strip().lower() in ("1", "true", "on", "yes")
        if not payload:
            return ToolResult(ok=False, error="refused: say a `view` (home, cameras, markets, charts, ambient), a "
                                              "`timeframe`, a `symbol`, `rotate_s`, `scale`, `live_max`, `live_step_s`, "
                                              "`video_quality` or `video_sound`")
        bus = getattr(ctx, "bus", None)
        if bus is None:
            return ToolResult(ok=False, error="refused: no bus to reach the dashboard")
        await bus.publish(Message.new(topics.DASH_STATE, source="execution", payload=payload))
        said = []
        if payload.get("view") == "charts" and len(payload) == 1:
            # The Charts view auto-plays (the creator, 2026-09-13): K-pop first.
            started = await self._start_chart(ctx, "kpop")
            if started.ok:
                return ToolResult(ok=True, output=f"the dashboard shows charts; {started.output}",
                                  side_effects=started.side_effects, metadata=started.metadata)
            said.append(f"the dashboard shows charts (not playing: {started.error})")
        elif "view" in payload:
            said.append(f"the dashboard shows {payload['view']}")
        if "timeframe" in payload or "symbol" in payload:
            said.append(" ".join(x for x in (payload.get("symbol", ""), payload.get("timeframe", "")) if x) + " on the chart")
        if "rotate_s" in payload:
            said.append(f"rotating every {payload['rotate_s']}s" if payload["rotate_s"] else "rotation off")
        if "scale" in payload:
            said.append(f"scale fixed at {payload['scale']:g}" if payload["scale"] else "scale fits the screen")
        if "live_max" in payload:
            said.append(f"up to {payload['live_max']} camera feeds play at once")
        if "live_step_s" in payload:
            said.append(f"the live window slides one camera every {payload['live_step_s']:g}s")
        if "video_sound" in payload:
            said.append("the videos play with sound" if payload["video_sound"] else "the videos play muted")
        if "video_quality" in payload:
            said.append(f"embedded video {payload['video_quality']}")
        return ToolResult(ok=True, output="; ".join(said), side_effects=("dash_view",), metadata=payload)


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
        from simorgh.contracts.settings import persist

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
        from simorgh.contracts.settings import persist

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


class TvPairTool(_CastTool):
    """`tv pair` / `tv pair <code>`: pair Sim with the TV's own remote
    protocol, once. The person's to run: the code is on the TV."""

    name = "tv_pair"
    description = ("Pair with the TV's own remote protocol (Android TV), once: without a `pin` the TV shows a code; "
                   "with the `pin` the pairing finishes. Unlocks the TV's own apps -- YouTube at 4K, Netflix -- and its "
                   "keys. `device` names the TV when there are several.")
    args_schema = {"type": "object", "properties": {"pin": {"type": "string"}, "device": {"type": "string"},
                                                   "again": {"type": "boolean"}}}
    reversibility = "reversible"

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        try:
            backend = self._backend()
            name, problem = await asyncio.to_thread(self._device, backend, str(args.get("device") or ""))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if problem:
            return ToolResult(ok=False, error=problem)
        host = self._host_of(backend, name)
        if not host:
            return ToolResult(ok=False, error=f"refused: no address known for {name}")
        tv = self._androidtv(host)
        pin = str(args.get("pin") or "").strip()
        if not pin:
            # `paired()` is Sim's own files, not the TV's memory. A TV that
            # forgot Sim still read "already paired", and with no way to get a
            # code on screen the hint (`tv pair <code>`) was a dead end: the
            # creator ran `tv pair` twice and got nowhere (2026-09-14).
            if tv.paired() and not args.get("again"):
                return ToolResult(ok=True, output=f"already paired with {name} ({host}); `tv pair again` if the TV forgot Sim",
                                  metadata={"device": name, "host": host, "paired": True})
            problem = await tv.pair_start()
            if problem:
                return ToolResult(ok=False, error=f"refused: {problem}")
            return ToolResult(ok=True, output=f"{name} is showing a code on its screen; type `tv pair <code>` to finish",
                              metadata={"device": name, "host": host, "paired": False})
        problem = await tv.pair_finish(pin)
        if problem:
            return ToolResult(ok=False, error=f"refused: {problem}")
        return ToolResult(ok=True, output=(f"paired with {name}: Sim can open its apps (\"play ... on YouTube\" now uses "
                                           "the TV's own app, at 4K) and press its keys"),
                          side_effects=(f"tv_pair:{name}",), metadata={"device": name, "host": host, "paired": True})


class TvAppTool(_CastTool):
    name = "tv_app"
    description = ("Open one of the TV's own apps, or a deep link in one: `app` youtube, netflix, disney, prime, spotify, "
                   "plex, or `url` such as https://www.youtube.com/watch?v=... (the YouTube app plays it at its best "
                   "quality). Needs `tv pair` once. `device` names the TV when there are several.")
    args_schema = {"type": "object", "properties": {"app": {"type": "string"}, "url": {"type": "string"},
                                                    "device": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        from .androidtv import APPS, app_link

        target = str(args.get("url") or args.get("app") or "").strip()
        link = app_link(target)
        if not link:
            return ToolResult(ok=False, error=f"refused: no app called {target!r}; the apps are {', '.join(sorted(k for k in APPS if k != 'home'))}, or give a link")
        try:
            backend = self._backend()
            name, problem = await asyncio.to_thread(self._device, backend, str(args.get("device") or ""))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if problem:
            return ToolResult(ok=False, error=problem)
        host = self._host_of(backend, name)
        tv = self._androidtv(host)
        problem = await tv.launch(link)
        if problem:
            return ToolResult(ok=False, error=f"refused: {problem}")
        self._bump()
        await self._publish_state(ctx, "full", url=link, title=target, native=target)
        return ToolResult(ok=True, output=f"opened on {name}: {target}. Say \"show your dashboard\" to come back",
                          side_effects=(f"tv_app:{name}",), metadata={"device": name, "link": link})


class TvKeyTool(_CastTool):
    name = "tv_key"
    description = ("Press a key on the TV as its remote would: home, back, up/down/left/right, ok, play, pause, stop, "
                   "next, previous, mute, volume up/down, power. Needs `tv pair` once.")
    args_schema = {"type": "object", "required": ["key"], "properties": {"key": {"type": "string"}, "device": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        from .androidtv import KEYS, key_code

        key = str(args.get("key") or "").strip()
        if not key_code(key):
            return ToolResult(ok=False, error=f"refused: which key? one of {', '.join(sorted(KEYS))}")
        try:
            backend = self._backend()
            name, problem = await asyncio.to_thread(self._device, backend, str(args.get("device") or ""))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if problem:
            return ToolResult(ok=False, error=problem)
        tv = self._androidtv(self._host_of(backend, name))
        problem = await tv.key(key)
        if problem:
            return ToolResult(ok=False, error=f"refused: {problem}")
        return ToolResult(ok=True, output=f"pressed {key} on {name}", side_effects=(f"tv_key:{name}",),
                          metadata={"device": name, "key": key_code(key)})


class TvChartsTool(_CastTool):
    name = "tv_charts"
    description = ("Play a music chart on the TV, top to bottom: `chart` kpop (Korea's most played) or uspop "
                   "(America's). The dashboard turns to its Charts view; the videos play full screen one after "
                   "another (in the TV's own YouTube app when paired). `device` names the TV when there are several.")
    args_schema = {"type": "object", "properties": {"chart": {"type": "string"}, "device": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        return await self._start_chart(ctx, str(args.get("chart") or "kpop"), str(args.get("device") or ""))


class DashKeyTool(_CastTool):
    """Press a remote-control key on the dashboard page. The TV's own
    remote never reaches a Cast receiver, so Sim relays keys: this tool
    publishes `ui.dash.key`, the HTTP API keeps it, the page polls it."""

    name = "dash_key"
    read_only = False
    reversibility = "reversible"
    ALIASES = {"enter": "ok", "select": "ok", "center": "ok", "open": "ok", "escape": "back", "esc": "back",
               "return": "back", "exit": "back", "play": "playpause", "pause": "playpause", "play pause": "playpause",
               "previous": "prev", "skip": "next", "forward": "next"}
    description = ("Press a remote-control key on Sim's dashboard on the TV (the TV's own remote cannot reach it): "
                   "`key` left/right/up/down moves (on the top ribbon left/right changes tabs), ok opens a tab or a "
                   "box full screen or takes control of its video, back steps out one level, playpause/next/prev "
                   "control the video. `times` repeats the key (1-10).")
    args_schema = {"type": "object", "required": ["key"],
                   "properties": {"key": {"type": "string"}, "times": {"type": "integer"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        raw = str(args.get("key") or args.get("target") or "").strip().lower()
        key = self.ALIASES.get(raw, raw)
        if key not in DASH_KEYS:
            return ToolResult(ok=False, error=f"refused: no dashboard key {raw!r}; the keys are {', '.join(DASH_KEYS)}")
        try:
            times = max(1, min(10, int(args.get("times") or 1)))
        except (TypeError, ValueError):
            times = 1
        bus = getattr(ctx, "bus", None)
        if bus is None:
            return ToolResult(ok=False, error="refused: no bus to reach the dashboard on")
        for _ in range(times):
            await bus.publish(Message.new(topics.UI_DASH_KEY, source="execution", payload={"key": key}))
        return ToolResult(ok=True, output=f"pressed {key} on the dashboard" + (f" {times} times" if times > 1 else ""),
                          side_effects=(f"dash_key:{key}",), metadata={"key": key, "times": times})


def cast_tools(config, **kwargs) -> list:
    kwargs = {k: v for k, v in kwargs.items()
              if k in ("cast", "env", "secrets", "clock", "reachable", "settings_home", "fetch", "media_dir",
                       "remote_cls", "certs_dir", "charts_source")}
    prefs = CastPreferences(device=str(getattr(config, "cast_device", "") or ""))
    return [CastDevicesTool(config, prefs=prefs, **kwargs), CastShowTool(config, prefs=prefs, **kwargs),
            CastPlayTool(config, prefs=prefs, **kwargs), CastStopTool(config, prefs=prefs, **kwargs),
            CastVolumeTool(config, prefs=prefs, **kwargs), CastUseTool(config, prefs=prefs, **kwargs),
            CastSetupTool(config, prefs=prefs, **kwargs), DashViewTool(config, prefs=prefs, **kwargs), DashKeyTool(config, prefs=prefs, **kwargs),
            TvPairTool(config, prefs=prefs, **kwargs), TvAppTool(config, prefs=prefs, **kwargs),
            TvKeyTool(config, prefs=prefs, **kwargs), TvChartsTool(config, prefs=prefs, **kwargs)]


__all__ = ["CastDevicesTool", "CastPlayTool", "CastPreferences", "CastSetupTool", "CastShowTool", "CastStopTool", "CastUseTool",
           "CastVolumeTool", "DashKeyTool", "DashViewTool", "Device", "settings_paths", "youtube_id",
           "PyChromecast", "available", "cast_tools", "lan_address"]
