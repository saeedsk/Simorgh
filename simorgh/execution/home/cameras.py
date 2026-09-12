"""The cameras: a Reolink NVR and every camera on it, through
`reolink_aio` (open source, what Home Assistant uses; optional, refused
by name when absent).

The creator, 2026-09-12: "I have 12 IP video cameras and a recording
NVR system in my home ... interface Sim with that system, where Sim has
full control: live stream, recording, events, alarms, controlling them,
turning the camera lights on and off, sirens, listening to voice".
Discovered on the network as ONVIF hardware "NVS16" at 192.168.50.42 --
the RLN16-410 with twelve 4K+ cameras.

    cam_setup        the NVR's address and login, kept in secrets.toml
    cam_list         every camera: channel, name, model, online
    cam_state        what a camera sees and has on right now
    cam_snapshot     a still, saved under workspace/cameras/
    cam_stream       live on the TV -- framed beside Sim's page or full screen -- or stopped
    cam_light        the spotlight on or off
    cam_ir           the infrared night lights on, off or auto
    cam_siren        the siren, for a few seconds
    cam_ptz          pan, tilt, zoom, a preset
    cam_recordings   what the NVR recorded on a camera in a period
    cam_watch        events pushed from the NVR: motion, person, vehicle, animal, on the bus and on screen

Live video reaches the TV as HLS: ffmpeg copies the camera's H.264 sub
stream from RTSP into segments under workspace/cameras/hls/<channel>/,
which the interface serves at /tv/hls/... on the LAN; the TV page plays
it in its box, or the Cast receiver plays it full screen. Every call is
a tool call, so Guardian sees it -- the siren above all.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ToolContext, ToolResult

SECRET_HOST, SECRET_USER, SECRET_PASSWORD = "REOLINK_HOST", "REOLINK_USERNAME", "REOLINK_PASSWORD"
HLS_DIR = Path("workspace/cameras/hls")
SNAPSHOT_DIR = Path("workspace/cameras")
_PTZ = {"left": "Left", "right": "Right", "up": "Up", "down": "Down", "stop": "Stop", "zoom_in": "ZoomInc",
        "zoom_out": "ZoomDec", "in": "ZoomInc", "out": "ZoomDec", "home": "ToPos", "preset": "ToPos"}
_AI_KINDS = ("person", "vehicle", "dog_cat", "face", "package")


def available() -> tuple[bool, str]:
    import importlib.util

    if importlib.util.find_spec("reolink_aio") is None:
        return False, "needs reolink-aio (pip install reolink-aio)"
    return True, ""


@dataclass
class Camera:
    channel: int
    name: str
    model: str = ""
    online: bool = True


class ReolinkNvr:
    """The real NVR, behind a seam the tests replace."""

    def __init__(self, host: str, username: str, password: str, *, port: int | None = None) -> None:
        self._args = (host, username, password, port)
        self._host = None
        self.host_name = host

    async def _api(self):
        if self._host is None:
            from reolink_aio.api import Host

            host, user, password, port = self._args
            self._host = Host(host, user, password, port=port, stream="sub")
            await self._host.get_host_data()
            await self._host.get_states()
        return self._host

    async def connect(self) -> dict:
        api = await self._api()
        return {"name": api.nvr_name, "model": api.model, "firmware": api.sw_version, "cameras": api.num_cameras}

    async def channels(self) -> list[Camera]:
        api = await self._api()
        return [Camera(channel=ch, name=api.camera_name(ch), model=api.camera_model(ch), online=api.camera_online(ch))
                for ch in api.channels]

    async def state(self, ch: int) -> dict:
        api = await self._api()
        await api.get_states()
        out = {"motion": bool(api.motion_detected(ch)), "recording": bool(api.recording_enabled(ch))}
        for kind in _AI_KINDS:
            try:
                if api.ai_supported(ch, kind):
                    out[kind] = bool(api.ai_detected(ch, kind))
            except Exception:  # noqa: BLE001
                pass
        for key, getter in (("light", "whiteled_state"), ("ir", "ir_enabled"), ("siren_armed", "audio_alarm_enabled")):
            try:
                out[key] = bool(getattr(api, getter)(ch))
            except Exception:  # noqa: BLE001
                pass
        return out

    async def snapshot(self, ch: int) -> bytes:
        api = await self._api()
        data = await api.get_snapshot(ch)
        if not data:
            raise RuntimeError("the camera returned no picture")
        return data

    async def stream_url(self, ch: int, stream: str = "sub") -> str:
        api = await self._api()
        url = await api.get_rtsp_stream_source(ch, stream)
        if not url:
            raise RuntimeError("no RTSP stream for that camera")
        return url

    async def light(self, ch: int, on: bool) -> None:
        await (await self._api()).set_whiteled(ch, state=on)

    async def ir(self, ch: int, on: bool) -> None:
        await (await self._api()).set_ir_lights(ch, on)

    async def siren(self, ch: int, seconds: int) -> None:
        await (await self._api()).set_siren(ch, enable=True, duration=seconds)

    async def ptz(self, ch: int, command: str, *, preset: int | None = None, speed: int | None = None) -> None:
        await (await self._api()).set_ptz_command(ch, command=command, preset=preset, speed=speed)

    async def recordings(self, ch: int, start: datetime, end: datetime) -> list[dict]:
        api = await self._api()
        _statuses, files = await api.request_vod_files(ch, start, end)
        return [{"start": str(getattr(f, "start_time", "")), "end": str(getattr(f, "end_time", "")),
                 "file": str(getattr(f, "file_name", "")), "seconds": float(getattr(f, "duration", 0) or 0)
                 if not hasattr(getattr(f, "duration", None), "total_seconds") else f.duration.total_seconds(),
                 "kinds": sorted(getattr(getattr(f, "triggers", None), "name", "") and [f.triggers.name] or [])}
                for f in files]

    async def subscribe(self, webhook_url: str) -> None:
        await (await self._api()).subscribe(webhook_url)

    async def renew(self) -> None:
        await (await self._api()).renew()

    async def unsubscribe(self) -> None:
        if self._host is not None:
            await self._host.unsubscribe()

    async def close(self) -> None:
        if self._host is not None:
            try:
                await self._host.logout()
            except Exception:  # noqa: BLE001
                pass
            self._host = None

    def events(self, body: str) -> list[int]:
        if self._host is None:
            return []
        return list(self._host.ONVIF_event_callback(body) or [])

    async def kinds_for(self, ch: int) -> list[str]:
        api = await self._api()
        kinds = ["motion"] if api.motion_detected(ch) else []
        for kind in _AI_KINDS:
            try:
                if api.ai_supported(ch, kind) and api.ai_detected(ch, kind):
                    kinds.append("animal" if kind == "dog_cat" else kind)
            except Exception:  # noqa: BLE001
                pass
        return kinds or ["motion"]


@dataclass
class CameraPreferences:
    """Shared by every camera tool: the one NVR connection, the live
    streams running, the event watcher."""

    nvr: object = None
    streams: dict = field(default_factory=dict)   # channel -> subprocess.Popen (ffmpeg)
    watcher: object = None                         # asyncio.Task renewing the NVR's push subscription
    renew_every_s: float = 240.0


def lan_address() -> str:
    from ..media.cast import lan_address as _lan

    return _lan()


class _CameraTool:
    read_only = False
    reversibility = "reversible"

    def __init__(self, config, *, nvr=None, env=None, secrets=None, clock=time.time, prefs: CameraPreferences | None = None,
                 settings_home: Path | None = None, ffmpeg: str | None = None) -> None:
        self._config = config
        self._given = nvr
        self._env = env if env is not None else os.environ
        self._secrets = secrets
        self._clock = clock
        self._prefs = prefs or CameraPreferences()
        self._settings_home = settings_home
        self._ffmpeg = ffmpeg

    def _secret(self, name: str) -> str:
        if self._secrets is not None:
            try:
                value = self._secrets.get(name)
            except Exception:  # noqa: BLE001
                value = None
            if value:
                return str(value)
        return str(self._env.get(name) or "")

    def _nvr(self):
        if self._given is not None:
            return self._given
        if self._prefs.nvr is None:
            ok, why = available()
            if not ok:
                raise RuntimeError(why)
            host, user, password = self._secret(SECRET_HOST), self._secret(SECRET_USER), self._secret(SECRET_PASSWORD)
            if not (host and user and password):
                raise RuntimeError("the NVR is not set up: `cameras setup <host> <username> <password>`")
            self._prefs.nvr = ReolinkNvr(host, user, password)
        return self._prefs.nvr

    async def _camera(self, nvr, wanted: str) -> tuple[Camera | None, str]:
        """`(camera, problem)`: by channel number, exact name, or a name
        that contains the words given."""
        wanted = (wanted or "").strip()
        cameras = await nvr.channels()
        if not cameras:
            return None, "refused: the NVR lists no cameras"
        if wanted.isdigit():
            for cam in cameras:
                if cam.channel == int(wanted) or cam.channel + 1 == int(wanted):
                    return cam, ""
            return None, f"refused: no channel {wanted}; there are {len(cameras)}"
        if not wanted:
            return None, "refused: say which camera; cam_list names them"
        low = wanted.lower()
        exact = [c for c in cameras if c.name.lower() == low]
        loose = [c for c in cameras if low in c.name.lower()] or [c for c in cameras if all(w in c.name.lower() for w in low.split())]
        match = exact or loose
        if not match:
            return None, f"refused: no camera called {wanted!r}; cameras: {', '.join(c.name for c in cameras)}"
        if len(match) > 1:
            return None, f"refused: {wanted!r} could be {', '.join(c.name for c in match)}"
        return match[0], ""

    async def _publish(self, ctx: ToolContext, topic: str, payload: dict) -> None:
        bus = getattr(ctx, "bus", None)
        if bus is not None:
            await bus.publish(Message.new(topic, source="execution", payload=payload))

    def _page_base(self) -> str:
        """Where the TV (and the NVR's event push) reach Sim's API: the
        configured page address when there is one, else this machine's
        LAN address on the page's port."""
        configured = str(getattr(self._config, "cast_page_url", "") or "").strip()
        if configured:
            return configured.split("/tv", 1)[0].rstrip("/")
        port = int(getattr(self._config, "cast_page_port", 8765))
        return f"http://{lan_address()}:{port}"

    def _token(self) -> str:
        return self._secret("SIM_API_TOKEN")


class CamSetupTool(_CameraTool):
    name = "cam_setup"
    description = ("Set the NVR's address and login (kept in secrets.toml, owner-only), then check the connection "
                   "and list the cameras. `host` may be an address or address:port.")
    args_schema = {"type": "object", "required": ["host", "username", "password"],
                   "properties": {"host": {"type": "string"}, "username": {"type": "string"},
                                  "password": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        host, user, password = (str(args.get(k) or "").strip() for k in ("host", "username", "password"))
        if not (host and user and password):
            return ToolResult(ok=False, error="refused: host, username and password are all needed")
        from ..media.cast import settings_paths
        from simorgh.voice.settings import persist

        config_path, secrets_path = settings_paths(self._settings_home)
        import tomllib

        existing: dict = {}
        if secrets_path.is_file():
            try:
                with secrets_path.open("rb") as handle:
                    existing = tomllib.load(handle)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(ok=False, error=f"refused: {secrets_path} could not be read ({exc})")
        existing.update({SECRET_HOST: host, SECRET_USER: user, SECRET_PASSWORD: password})
        try:
            secrets_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = secrets_path.with_suffix(".toml.part")
            tmp.write_text("".join(f"{k} = {json.dumps(str(v))}\n" for k, v in existing.items()))
            tmp.chmod(0o600)
            tmp.replace(secrets_path)
            secrets_path.chmod(0o600)
            scope = ["vault:*", "SIM_API_TOKEN", SECRET_HOST, SECRET_USER, SECRET_PASSWORD]
            persist(config_path, "secrets", scope, section="execution")
        except OSError as exc:
            return ToolResult(ok=False, error=f"refused: could not write {secrets_path} ({exc})")
        self._prefs.nvr = None
        if self._given is None:
            ok, why = available()
            if not ok:
                return ToolResult(ok=True, output=f"login saved to {secrets_path}; {why} before it can be used")
            self._prefs.nvr = ReolinkNvr(host, user, password)
        try:
            info = await self._nvr().connect()
            cameras = await self._nvr().channels()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"login saved to {secrets_path}, but the NVR did not answer: {exc}")
        lines = [f"connected to {info.get('name') or host} ({info.get('model', '')} {info.get('firmware', '')}): "
                 f"{len(cameras)} camera(s)"] + [f"  {c.channel + 1:2d}. {c.name}  {c.model}  {'online' if c.online else 'OFFLINE'}"
                                                for c in cameras]
        lines.append("restart Sim so every tool can read the login; then `cameras list`")
        return ToolResult(ok=True, output="\n".join(lines), side_effects=("cam_setup",),
                          metadata={"cameras": [c.name for c in cameras]})


class CamListTool(_CameraTool):
    name = "cam_list"
    description = "Every camera on the NVR: number, name, model, online or not."
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "properties": {}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        try:
            nvr = self._nvr()
            cameras = await nvr.channels()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if not cameras:
            return ToolResult(ok=True, output="the NVR lists no cameras")
        lines = [f"{c.channel + 1:2d}. {c.name}  {c.model}  {'online' if c.online else 'OFFLINE'}" for c in cameras]
        return ToolResult(ok=True, output="\n".join(lines), metadata={"cameras": [c.name for c in cameras]})


class CamStateTool(_CameraTool):
    name = "cam_state"
    description = ("What a camera sees and has switched on right now: motion, a person, a vehicle, an animal; "
                   "recording, spotlight, infrared, siren armed. `camera` empty = every camera.")
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "properties": {"camera": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        try:
            nvr = self._nvr()
            cameras = await nvr.channels()
            wanted = str(args.get("camera") or "").strip()
            if wanted:
                cam, problem = await self._camera(nvr, wanted)
                if problem:
                    return ToolResult(ok=False, error=problem)
                cameras = [cam]
            lines = []
            for cam in cameras:
                state = await nvr.state(cam.channel)
                seen = [k for k in ("motion", "person", "vehicle", "dog_cat", "face", "package") if state.get(k)]
                on = [k for k in ("recording", "light", "ir", "siren_armed") if state.get(k)]
                lines.append(f"{cam.name}: " + (", ".join("animal" if k == "dog_cat" else k for k in seen) or "quiet")
                             + (f"  [{', '.join(on)}]" if on else ""))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        return ToolResult(ok=True, output="\n".join(lines))


class CamSnapshotTool(_CameraTool):
    name = "cam_snapshot"
    description = "A still from a camera, saved as a JPEG under workspace/cameras/; says the path."
    args_schema = {"type": "object", "required": ["camera"], "properties": {"camera": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        try:
            nvr = self._nvr()
            cam, problem = await self._camera(nvr, str(args.get("camera") or ""))
            if problem:
                return ToolResult(ok=False, error=problem)
            data = await nvr.snapshot(cam.channel)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        root = Path(getattr(ctx, "root", None) or getattr(ctx, "data_dir", ".") or ".")
        folder = root / SNAPSHOT_DIR
        folder.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", cam.name).strip("_") or f"channel{cam.channel + 1}"
        path = folder / f"{safe}-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
        path.write_bytes(data)
        rel = str(SNAPSHOT_DIR / path.name)
        return ToolResult(ok=True, output=f"{cam.name}: {rel} ({len(data) // 1024} KB)", side_effects=(f"file_create:{rel}",),
                          metadata={"path": rel, "camera": cam.name})


class CamStreamTool(_CameraTool):
    name = "cam_stream"
    description = ("Live video on the TV. `camera` is one camera, several separated by commas, or `all`; `mode` "
                   "frame (one camera inside Sim's page), grid (the cameras tiled across the TV), full (one camera "
                   "full screen), dash (live in the dashboard's camera strip, the TV's page untouched), or stop. "
                   "Uses ffmpeg to relay each camera's stream as HLS.")
    args_schema = {"type": "object", "required": ["camera"],
                   "properties": {"camera": {"type": "string"},
                                  "mode": {"type": "string", "enum": ["frame", "grid", "full", "dash", "stop"]}}}

    def _binary(self) -> str:
        return self._ffmpeg or shutil.which("ffmpeg") or ""

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        words = str(args.get("camera") or "").split()
        mode = str(args.get("mode") or "").lower()
        if words and words[-1].lower() in ("frame", "grid", "full", "stop", "tiled", "tile", "dash", "dashboard", "background") and not mode:
            mode, words = words[-1].lower(), words[:-1]
        mode = {"tiled": "grid", "tile": "grid", "dashboard": "dash", "background": "dash"}.get(mode, mode) or "frame"
        wanted = " ".join(words)
        if mode == "stop":
            stopped = self._stop(None)
            await self._publish(ctx, topics.TV_STATE, {"mode": "none"})
            return ToolResult(ok=True, output=f"stopped {stopped} live stream(s)", side_effects=("cam_stream:stop",))
        binary = self._binary()
        if not binary:
            return ToolResult(ok=False, error="refused: ffmpeg is not installed (brew install ffmpeg)")
        try:
            nvr = self._nvr()
            cameras = await self._pick(nvr, wanted)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if isinstance(cameras, str):
            return ToolResult(ok=False, error=cameras)
        if len(cameras) > 1 and mode == "frame":
            mode = "grid"
        if len(cameras) > 1 and mode == "full":
            return ToolResult(ok=False, error="refused: full screen takes one camera; use grid for several")
        if mode not in ("grid", "dash"):
            self._stop(None)
        root = Path(getattr(ctx, "root", None) or getattr(ctx, "data_dir", ".") or ".")
        started: list[tuple[Camera, str]] = []
        failures: list[str] = []
        for cam in cameras:
            try:
                rtsp = await nvr.stream_url(cam.channel, "sub")
                url = await self._relay(binary, root, cam, rtsp)
                started.append((cam, url))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{cam.name}: {exc}")
        if not started:
            return ToolResult(ok=False, error="refused: " + "; ".join(failures))
        if mode == "full":
            from ..media.cast import CastPlayTool

            cam, url = started[0]
            play = CastPlayTool(self._config, secrets=self._secrets, env=self._env)
            result = await play.run({"url": url, "mode": "full", "title": cam.name}, ctx=ctx)
            if not result.ok:
                return result
        elif mode == "grid":
            await self._publish(ctx, topics.TV_STATE, {"mode": "grid", "urls": [u for _c, u in started],
                                                       "titles": [c.name for c, _u in started]})
        elif mode == "dash":
            pass   # the dashboard's camera strip finds the playlists itself (interface/dashfeeds.py)
        else:
            cam, url = started[0]
            await self._publish(ctx, topics.TV_STATE, {"mode": "frame", "url": url, "title": cam.name})
        names = ", ".join(c.name for c, _u in started)
        tail = f"; could not start {'; '.join(failures)}" if failures else ""
        where = "live in the dashboard's camera strip" if mode == "dash" else f"live on the TV ({mode})"
        return ToolResult(ok=True, output=f"{where}: {names}{tail}; `cam_stream all stop` ends it",
                          side_effects=tuple(f"cam_stream:{c.channel}" for c, _u in started),
                          metadata={"cameras": [c.name for c, _u in started], "urls": [u for _c, u in started], "mode": mode})

    async def _pick(self, nvr, wanted: str):
        """The cameras named: `all` (every online one), a comma list, or one."""
        if wanted.strip().lower() in ("all", "every", "everything", "*"):
            cameras = [c for c in await nvr.channels() if c.online]
            return cameras or "refused: no camera is online"
        out = []
        for part in [w for w in re.split(r"\s*(?:,|\band\b)\s*", wanted) if w.strip()]:
            cam, problem = await self._camera(nvr, part)
            if problem:
                return problem
            if cam.channel not in {c.channel for c in out}:
                out.append(cam)
        return out or "refused: say which camera; cam_list names them"

    async def _relay(self, binary: str, root: Path, cam: Camera, rtsp: str) -> str:
        folder = root / HLS_DIR / str(cam.channel)
        self._stop(cam.channel)
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True, exist_ok=True)
        # The folder is named by channel; the dashboard wants the name.
        (folder / "camera.json").write_text(json.dumps({"channel": cam.channel, "name": cam.name, "model": cam.model}),
                                            encoding="utf-8")
        cmd = [binary, "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", rtsp,
               "-c:v", "copy", "-c:a", "aac", "-ac", "1", "-f", "hls", "-hls_time", "2", "-hls_list_size", "6",
               "-hls_flags", "delete_segments+omit_endlist", "-y", str(folder / "index.m3u8")]
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self._prefs.streams[cam.channel] = proc
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline and not (folder / "index.m3u8").exists():
            if proc.poll() is not None:
                err = (proc.stderr.read().decode(errors="ignore") if proc.stderr else "").strip()[-200:]
                raise RuntimeError(f"ffmpeg could not open the stream ({err or 'no detail'})")
            await asyncio.sleep(0.25)
        if not (folder / "index.m3u8").exists():
            self._stop(cam.channel)
            raise RuntimeError("the stream did not start within 12 s")
        return f"{self._page_base()}/tv/hls/{cam.channel}/index.m3u8"

    def _stop(self, which) -> int:
        count = 0
        for ch, proc in list(self._prefs.streams.items()):
            if which is not None and ch != which:
                continue
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                pass
            self._prefs.streams.pop(ch, None)
            count += 1
        return count


class CamLightTool(_CameraTool):
    name = "cam_light"
    description = "A camera's spotlight (white LED) on or off."
    args_schema = {"type": "object", "required": ["camera"],
                   "properties": {"camera": {"type": "string"}, "on": {"type": "boolean"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        wanted, on = _camera_and_switch(args, "on")
        try:
            nvr = self._nvr()
            cam, problem = await self._camera(nvr, wanted)
            if problem:
                return ToolResult(ok=False, error=problem)
            await nvr.light(cam.channel, on)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        return ToolResult(ok=True, output=f"{cam.name}: spotlight {'on' if on else 'off'}",
                          side_effects=(f"cam_light:{cam.channel}",))


class CamIrTool(_CameraTool):
    name = "cam_ir"
    description = "A camera's infrared night lights on or off (off = the camera decides by itself)."
    args_schema = {"type": "object", "required": ["camera"],
                   "properties": {"camera": {"type": "string"}, "on": {"type": "boolean"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        wanted, on = _camera_and_switch(args, "on")
        try:
            nvr = self._nvr()
            cam, problem = await self._camera(nvr, wanted)
            if problem:
                return ToolResult(ok=False, error=problem)
            await nvr.ir(cam.channel, on)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        return ToolResult(ok=True, output=f"{cam.name}: infrared {'on' if on else 'auto'}",
                          side_effects=(f"cam_ir:{cam.channel}",))


class CamSirenTool(_CameraTool):
    name = "cam_siren"
    description = "Sound a camera's siren for a few seconds (default 5, at most 30). Loud, and it wakes people."
    reversibility = "irreversible"
    args_schema = {"type": "object", "required": ["camera"],
                   "properties": {"camera": {"type": "string"}, "seconds": {"type": "integer"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        words = str(args.get("camera") or "").split()
        seconds = args.get("seconds")
        if words and words[-1].isdigit() and seconds is None:
            seconds, words = int(words[-1]), words[:-1]
        try:
            seconds = max(1, min(30, int(seconds or 5)))
        except (TypeError, ValueError):
            seconds = 5
        try:
            nvr = self._nvr()
            cam, problem = await self._camera(nvr, " ".join(words))
            if problem:
                return ToolResult(ok=False, error=problem)
            await nvr.siren(cam.channel, seconds)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        return ToolResult(ok=True, output=f"{cam.name}: siren for {seconds}s", side_effects=(f"cam_siren:{cam.channel}",))


class CamPtzTool(_CameraTool):
    name = "cam_ptz"
    description = ("Move a camera: left, right, up, down, stop, zoom_in, zoom_out, or `preset <n>`. "
                   "Only a camera that can move obeys.")
    args_schema = {"type": "object", "required": ["camera", "command"],
                   "properties": {"camera": {"type": "string"}, "command": {"type": "string"}, "preset": {"type": "integer"},
                                  "speed": {"type": "integer"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        words = str(args.get("camera") or "").split()
        command = str(args.get("command") or "").strip().lower()
        preset = args.get("preset")
        if not command and words:
            if words[-1].isdigit() and len(words) >= 2 and words[-2].lower() == "preset":
                preset, command, words = int(words[-1]), "preset", words[:-2]
            elif words[-1].lower() in _PTZ:
                command, words = words[-1].lower(), words[:-1]
        if command not in _PTZ:
            return ToolResult(ok=False, error=f"refused: command is one of {', '.join(sorted(_PTZ))}")
        try:
            nvr = self._nvr()
            cam, problem = await self._camera(nvr, " ".join(words))
            if problem:
                return ToolResult(ok=False, error=problem)
            await nvr.ptz(cam.channel, _PTZ[command], preset=int(preset) if preset is not None else None,
                          speed=int(args["speed"]) if args.get("speed") is not None else None)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        return ToolResult(ok=True, output=f"{cam.name}: {command}" + (f" {preset}" if preset is not None else ""),
                          side_effects=(f"cam_ptz:{cam.channel}",))


class CamRecordingsTool(_CameraTool):
    name = "cam_recordings"
    description = ("What the NVR recorded on a camera: `period` today (default), yesterday, or `<hours>h` back; "
                   "start and end times and what triggered each clip.")
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "required": ["camera"],
                   "properties": {"camera": {"type": "string"}, "period": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        words = str(args.get("camera") or "").split()
        period = str(args.get("period") or "").lower()
        if words and not period and (words[-1].lower() in ("today", "yesterday") or re.fullmatch(r"\d+h", words[-1].lower())):
            period, words = words[-1].lower(), words[:-1]
        now = datetime.fromtimestamp(self._clock())
        if period == "yesterday":
            start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif re.fullmatch(r"\d+h", period or ""):
            start, end = now - timedelta(hours=int(period[:-1])), now
        else:
            start, end = now.replace(hour=0, minute=0, second=0, microsecond=0), now
        try:
            nvr = self._nvr()
            cam, problem = await self._camera(nvr, " ".join(words))
            if problem:
                return ToolResult(ok=False, error=problem)
            clips = await nvr.recordings(cam.channel, start, end)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if not clips:
            return ToolResult(ok=True, output=f"{cam.name}: nothing recorded {period or 'today'}")
        lines = [f"{cam.name}: {len(clips)} clip(s) {period or 'today'}"]
        for clip in clips[:40]:
            kinds = ", ".join(clip.get("kinds") or []) or "recording"
            lines.append(f"  {clip['start'][11:16] if len(clip['start']) > 16 else clip['start']} -> "
                         f"{clip['end'][11:16] if len(clip['end']) > 16 else clip['end']}  {kinds}")
        if len(clips) > 40:
            lines.append(f"  … +{len(clips) - 40} more")
        return ToolResult(ok=True, output="\n".join(lines), metadata={"count": len(clips)})


class CamWatchTool(_CameraTool):
    name = "cam_watch"
    description = ("Have the NVR push events -- motion, a person, a vehicle, an animal -- to Sim as they happen: "
                   "each one goes on the bus and on screen. `on` or `off`.")
    args_schema = {"type": "object", "properties": {"on": {"type": "boolean"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        raw = args.get("on")
        on = raw if isinstance(raw, bool) else str(raw or "on").strip().lower() not in ("off", "false", "no", "0", "stop")
        bus = getattr(ctx, "bus", None)
        if not on:
            task = self._prefs.watcher
            if task is not None and not task.done():
                task.cancel()
            self._prefs.watcher = None
            try:
                await self._nvr().unsubscribe()
            except Exception:  # noqa: BLE001
                pass
            return ToolResult(ok=True, output="not watching the cameras", side_effects=("cam_watch:off",))
        if bus is None:
            return ToolResult(ok=False, error="refused: no bus to deliver events on")
        try:
            nvr = self._nvr()
            cameras = await nvr.channels()
            webhook = f"{self._page_base()}/api/hooks/reolink"
            token = self._token()
            if token:
                webhook += f"?token={token}"
            await nvr.subscribe(webhook)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: the NVR would not subscribe ({exc})")
        names = {c.channel: c.name for c in cameras}
        task = self._prefs.watcher
        if task is not None and not task.done():
            task.cancel()
        self._prefs.watcher = asyncio.create_task(self._watch(bus, nvr, names), name="camera-watch")
        return ToolResult(ok=True, output=f"watching {len(cameras)} camera(s); events show on screen as they happen",
                          side_effects=("cam_watch:on",))

    async def _watch(self, bus, nvr, names: dict) -> None:
        """Handle the NVR's pushes (`ui.hook.received` name=reolink) and
        keep the subscription alive."""
        async def _on_hook(message) -> None:
            if str(message.payload.get("name")) != "reolink":
                return
            try:
                channels = nvr.events(str(message.payload.get("body") or ""))
            except Exception:  # noqa: BLE001
                return
            for ch in channels:
                try:
                    kinds = await nvr.kinds_for(ch)
                except Exception:  # noqa: BLE001
                    kinds = ["motion"]
                camera = names.get(ch, f"channel {ch + 1}")
                await bus.publish(Message.new(topics.CAMERA_EVENT, source="execution",
                                              payload={"channel": ch, "camera": camera, "kinds": kinds}))
                await bus.publish(Message.new(topics.UI_NOTICE, source="execution", payload={
                    "level": "info", "source": "cameras", "text": f"📷 {camera}: {', '.join(kinds)}"}))

        sub = await bus.subscribe(topics.UI_HOOK_RECEIVED, _on_hook)
        try:
            while True:
                await asyncio.sleep(self._prefs.renew_every_s)
                try:
                    await nvr.renew()
                except Exception:  # noqa: BLE001
                    try:
                        await nvr.subscribe(None)
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            await sub.unsubscribe()


def _camera_and_switch(args: dict, key: str) -> tuple[str, bool]:
    words = str(args.get("camera") or "").split()
    value = args.get(key)
    if value is None and words and words[-1].lower() in ("on", "off", "auto"):
        value, words = words[-1].lower() == "on", words[:-1]
    if isinstance(value, str):
        value = value.strip().lower() in ("on", "true", "yes", "1")
    return " ".join(words), bool(value) if value is not None else True


def cameras_tools(config, **kwargs) -> list:
    kwargs = {k: v for k, v in kwargs.items() if k in ("nvr", "env", "secrets", "clock", "settings_home", "ffmpeg")}
    prefs = CameraPreferences()
    return [cls(config, prefs=prefs, **kwargs) for cls in (
        CamSetupTool, CamListTool, CamStateTool, CamSnapshotTool, CamStreamTool, CamLightTool, CamIrTool, CamSirenTool,
        CamPtzTool, CamRecordingsTool, CamWatchTool)]


__all__ = ["Camera", "CameraPreferences", "ReolinkNvr", "available", "cameras_tools"]
