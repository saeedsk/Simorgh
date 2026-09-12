"""The Ring cameras: doorbells and stick-up cams on Ring's cloud, next to
the Reolink NVR (cameras.py). The creator, 2026-09-12: "I have ring
camera in my home, add support for those camera and show them in dash."

    ring_setup      log in once (email, password, then the code Ring
                    texts); the token is kept in secrets.toml
    ring_list       every Ring camera: kind, battery, what it can do
    ring_snapshot   a fresh still from one camera or all of them, saved
                    under workspace/cameras/ring/ -- the dashboard's tiles
    ring_events     the recent rings and motions, newest first
    ring_light      a camera's light on or off
    ring_siren      the siren, for a few seconds -- loud
    ring_watch      poll Ring on a timer: new events go on the bus and on
                    screen, stills stay fresh for the dashboard

Ring has no public API. This goes through `ring_doorbell` (python-ring-
doorbell, LGPL, the library Home Assistant uses), which speaks the same
endpoints the Ring app does with the same OAuth login. Ring's terms
allow personal use of your own account through the app; a third-party
client is not something Ring supports, and a login from a new "device"
triggers their two-step code every time the token is lost. The token is
refreshed by the library and written back to secrets.toml so that
happens once. Live video is WebRTC and is not built here; the dashboard
shows stills, which is what Ring itself shows in its event history.

Optional dependency, refused by name when missing. Every call is a tool
call Guardian sees; the `ring` command in the CLI is sugar over them.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ToolContext, ToolResult

SECRET_TOKEN, SECRET_USER = "RING_TOKEN", "RING_USERNAME"
RING_DIR = Path("workspace/cameras/ring")
EVENTS_FILE = "events.json"
USER_AGENT = "Simorgh/1.0"
EVENTS_KEPT = 200


def available() -> tuple[bool, str]:
    import importlib.util

    if importlib.util.find_spec("ring_doorbell") is None:
        return False, "needs ring_doorbell (pip install ring_doorbell)"
    return True, ""


@dataclass
class RingCamera:
    id: str
    name: str
    kind: str = ""          # doorbot, stickup_cam, ...
    family: str = ""        # doorbots, stickup_cams, authorized_doorbots
    battery: int | None = None
    has_light: bool = False
    has_siren: bool = False
    online: bool = True

    @property
    def safe(self) -> str:
        return re.sub(r"[^A-Za-z0-9_-]+", "_", self.name).strip("_") or f"ring{self.id}"


class RingCloud:
    """Ring's cloud through `ring_doorbell`. One session per process;
    `on_token` is called with the refreshed token so it can be saved."""

    def __init__(self, token: dict, *, on_token=None) -> None:
        self._token = token
        self._on_token = on_token
        self._auth = None
        self._ring = None
        self._devices: dict[str, object] = {}

    @staticmethod
    async def login(email: str, password: str, code: str | None = None) -> dict:
        """The OAuth token for this account, or `RuntimeError("2fa")`
        when Ring wants the code it just sent."""
        try:
            from ring_doorbell import Auth
            from ring_doorbell.exceptions import AuthenticationError, Requires2FAError
        except ImportError as exc:
            raise RuntimeError(available()[1]) from exc

        auth = Auth(USER_AGENT)
        try:
            token = await auth.async_fetch_token(email, password, code or None)
        except Requires2FAError as exc:
            raise RuntimeError("2fa") from exc
        except AuthenticationError as exc:
            raise RuntimeError(f"Ring refused the login: {exc}") from exc
        finally:
            try:
                await auth.async_close()
            except Exception:  # noqa: BLE001
                pass
        return dict(token)

    async def connect(self) -> None:
        if self._ring is not None:
            return
        try:
            from ring_doorbell import Auth, Ring
        except ImportError as exc:
            raise RuntimeError(available()[1]) from exc

        self._auth = Auth(USER_AGENT, self._token, self._on_token)
        self._ring = Ring(self._auth)
        await self._ring.async_create_session()
        await self._ring.async_update_data()
        self._index()

    def _index(self) -> None:
        self._devices = {}
        devices = self._ring.devices()
        for family in ("doorbots", "authorized_doorbots", "stickup_cams", "other"):
            for dev in getattr(devices, family, []) or []:
                self._devices[str(dev.id)] = dev

    async def refresh(self) -> None:
        await self.connect()
        await self._ring.async_update_devices()
        self._index()

    async def cameras(self) -> list[RingCamera]:
        await self.connect()
        out = []
        for dev in self._devices.values():
            if getattr(dev, "family", "") == "chimes":
                continue
            battery = None
            try:
                raw = dev.battery_life
                battery = int(raw) if raw is not None else None
            except Exception:  # noqa: BLE001
                battery = None
            out.append(RingCamera(
                id=str(dev.id), name=str(dev.name), kind=str(getattr(dev, "kind", "") or ""),
                family=str(getattr(dev, "family", "") or ""), battery=battery,
                has_light=bool(_cap(dev, "light")), has_siren=bool(_cap(dev, "siren")),
            ))
        return out

    def _dev(self, cam_id: str):
        dev = self._devices.get(str(cam_id))
        if dev is None:
            raise RuntimeError(f"no Ring device {cam_id}")
        return dev

    async def snapshot(self, cam_id: str) -> bytes | None:
        await self.connect()
        return await self._dev(cam_id).async_get_snapshot(retries=3, delay=2)

    async def history(self, cam_id: str, *, limit: int = 20) -> list[dict]:
        await self.connect()
        rows = await self._dev(cam_id).async_history(limit=limit)
        out = []
        for row in rows or []:
            when = row.get("created_at")
            at = when.timestamp() if isinstance(when, datetime) else _when(str(when or ""))
            out.append({"id": str(row.get("id")), "kind": str(row.get("kind") or "motion"), "at": at,
                        "answered": bool(row.get("answered")), "camera_id": str(cam_id)})
        return out

    async def light(self, cam_id: str, on: bool) -> None:
        await self.connect()
        await self._dev(cam_id).async_set_lights("on" if on else "off")

    async def siren(self, cam_id: str, seconds: int) -> None:
        await self.connect()
        await self._dev(cam_id).async_set_siren(int(seconds))

    async def close(self) -> None:
        if self._auth is not None:
            try:
                await self._auth.async_close()
            except Exception:  # noqa: BLE001
                pass
        self._auth = self._ring = None


def _cap(dev, name: str) -> bool:
    try:
        return bool(dev.has_capability(name))
    except Exception:  # noqa: BLE001
        return False


def _when(text: str) -> float | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


@dataclass
class RingPreferences:
    cloud: object = None
    watcher: object = None
    cameras: list = field(default_factory=list)
    seen: set = field(default_factory=set)      # event ids already announced


class _RingTool:
    read_only = False
    reversibility = "reversible"

    def __init__(self, config, *, cloud=None, env=None, secrets=None, clock=time.time,
                 prefs: RingPreferences | None = None, settings_home: Path | None = None) -> None:
        self._config = config
        self._given = cloud
        self._env = env if env is not None else os.environ
        self._secrets = secrets
        self._clock = clock
        self._prefs = prefs or RingPreferences()
        self._settings_home = settings_home

    def _secret(self, name: str) -> str:
        if self._secrets is not None:
            try:
                value = self._secrets.get(name)
            except Exception:  # noqa: BLE001
                value = None
            if value:
                return str(value)
        return str(self._env.get(name) or "")

    def _cloud(self):
        if self._given is not None:
            return self._given
        if self._prefs.cloud is None:
            ok, why = available()
            if not ok:
                raise RuntimeError(why)
            raw = self._secret(SECRET_TOKEN)
            if not raw:
                raise RuntimeError("Ring is not set up: `ring setup <email> <password>` (then the code Ring sends)")
            try:
                token = json.loads(raw)
            except ValueError as exc:
                raise RuntimeError("the saved Ring token is not readable; `ring setup` again") from exc
            self._prefs.cloud = RingCloud(token, on_token=lambda t: _save_secrets(self._settings_home, {SECRET_TOKEN: json.dumps(t)}))
        return self._prefs.cloud

    async def _cameras(self, cloud) -> list[RingCamera]:
        cams = await cloud.cameras()
        self._prefs.cameras = cams
        return cams

    async def _camera(self, cloud, wanted: str) -> tuple[RingCamera | None, str]:
        wanted = (wanted or "").strip()
        cams = await self._cameras(cloud)
        if not cams:
            return None, "refused: this Ring account has no cameras"
        if not wanted:
            if len(cams) == 1:
                return cams[0], ""
            return None, f"refused: say which camera; ring_list names them ({', '.join(c.name for c in cams)})"
        low = wanted.lower()
        exact = [c for c in cams if c.name.lower() == low]
        loose = [c for c in cams if low in c.name.lower()] or [c for c in cams if all(w in c.name.lower() for w in low.split())]
        match = exact or loose
        if not match:
            return None, f"refused: no Ring camera called {wanted!r}; cameras: {', '.join(c.name for c in cams)}"
        if len(match) > 1:
            return None, f"refused: {wanted!r} could be {', '.join(c.name for c in match)}"
        return match[0], ""

    def _folder(self, ctx: ToolContext) -> Path:
        root = Path(getattr(ctx, "root", None) or getattr(ctx, "data_dir", ".") or ".")
        folder = root / RING_DIR
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    async def _save_still(self, cloud, cam: RingCamera, folder: Path) -> tuple[Path | None, str]:
        try:
            data = await cloud.snapshot(cam.id)
        except Exception as exc:  # noqa: BLE001
            return None, f"{cam.name}: {exc.__class__.__name__}: {exc}"
        if not data:
            return None, f"{cam.name}: Ring had no fresh still (a battery camera sleeps between events)"
        path = folder / f"{cam.safe}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(self._clock()))}.jpg"
        path.write_bytes(data)
        return path, ""

    def _write_events(self, folder: Path, events: list[dict], names: dict[str, str]) -> list[dict]:
        """Merge new events into `events.json` (newest first, capped) for
        the dashboard's Cameras view; returns the merged list."""
        path = folder / EVENTS_FILE
        existing: list[dict] = []
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8")) or []
            except (ValueError, OSError):
                existing = []
        by_id = {str(e.get("id")): e for e in existing if e.get("id")}
        for e in events:
            by_id[str(e["id"])] = {"id": str(e["id"]), "camera": names.get(e.get("camera_id", ""), e.get("camera", "Ring")),
                                   "kind": e.get("kind", "motion"), "at": e.get("at"), "answered": e.get("answered", False),
                                   "source": "ring"}
        merged = sorted(by_id.values(), key=lambda e: e.get("at") or 0, reverse=True)[:EVENTS_KEPT]
        tmp = path.with_suffix(".json.part")
        tmp.write_text(json.dumps(merged), encoding="utf-8")
        tmp.replace(path)
        return merged


def _save_secrets(settings_home: Path | None, values: dict[str, str]) -> Path:
    """Write `values` into secrets.toml (owner-only, atomic) and make sure
    `[execution] secrets` lets Execution read them -- adding to the list
    that is there, not replacing it."""
    import tomllib

    from ..media.cast import settings_paths
    from simorgh.voice.settings import persist

    config_path, secrets_path = settings_paths(settings_home)
    existing: dict = {}
    if secrets_path.is_file():
        with secrets_path.open("rb") as handle:
            existing = tomllib.load(handle)
    existing.update(values)
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = secrets_path.with_suffix(".toml.part")
    tmp.write_text("".join(f"{k} = {json.dumps(str(v))}\n" for k, v in existing.items()))
    tmp.chmod(0o600)
    tmp.replace(secrets_path)
    secrets_path.chmod(0o600)
    scope: list[str] = []
    if config_path.is_file():
        try:
            with config_path.open("rb") as handle:
                scope = list((tomllib.load(handle).get("execution") or {}).get("secrets") or [])
        except Exception:  # noqa: BLE001
            scope = []
    for needed in ("vault:*", "SIM_API_TOKEN", *values):
        if needed not in scope:
            scope.append(needed)
    persist(config_path, "secrets", scope, section="execution")
    return secrets_path


class RingSetupTool(_RingTool):
    name = "ring_setup"
    description = ("Log in to Ring once: `email` and `password`, then -- when Ring texts a code -- the same call with "
                   "`code`. The token is kept in secrets.toml (owner-only); the password is not.")
    args_schema = {"type": "object", "required": ["email", "password"],
                   "properties": {"email": {"type": "string"}, "password": {"type": "string"}, "code": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        email, password, code = (str(args.get(k) or "").strip() for k in ("email", "password", "code"))
        if not (email and password):
            return ToolResult(ok=False, error="refused: email and password are both needed")
        if self._given is None:
            ok, why = available()
            if not ok:
                return ToolResult(ok=False, error=f"refused: {why}")
        try:
            login = self._given.login if self._given is not None and hasattr(self._given, "login") else RingCloud.login
            token = await login(email, password, code or None)
        except RuntimeError as exc:
            if str(exc) == "2fa":
                return ToolResult(ok=False, error=("Ring sent a verification code to this account's phone or email. Run "
                                                   "`ring setup <email> <password> <code>` with it within a few minutes."))
            return ToolResult(ok=False, error=f"refused: {exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: Ring did not answer ({exc.__class__.__name__}: {exc})")
        try:
            secrets_path = _save_secrets(self._settings_home, {SECRET_TOKEN: json.dumps(token), SECRET_USER: email})
        except OSError as exc:
            return ToolResult(ok=False, error=f"refused: could not write the token ({exc})")
        self._prefs.cloud = None
        if self._given is None:
            self._prefs.cloud = RingCloud(token, on_token=lambda t: _save_secrets(self._settings_home, {SECRET_TOKEN: json.dumps(t)}))
        try:
            cams = await self._cameras(self._cloud())
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"token saved to {secrets_path}, but Ring did not list the cameras: {exc}")
        lines = [f"logged in to Ring as {email}: {len(cams)} camera(s)"] + [_line(c) for c in cams]
        lines.append("restart Sim so every tool can read the token; then `ring list`, and `ring watch on` for the dashboard")
        return ToolResult(ok=True, output="\n".join(lines), side_effects=("ring_setup",),
                          metadata={"cameras": [c.name for c in cams]})


def _line(c: RingCamera) -> str:
    bits = [c.kind or c.family]
    if c.battery is not None:
        bits.append(f"battery {c.battery}%")
    caps = [n for n, on in (("light", c.has_light), ("siren", c.has_siren)) if on]
    if caps:
        bits.append("+".join(caps))
    return f"  {c.name}  ({', '.join(b for b in bits if b)})"


class RingListTool(_RingTool):
    name = "ring_list"
    read_only = True
    reversibility = "read_only"
    description = "The Ring cameras on the account: name, kind, battery, and whether each has a light or a siren."
    args_schema = {"type": "object", "properties": {}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        try:
            cams = await self._cameras(self._cloud())
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if not cams:
            return ToolResult(ok=True, output="this Ring account has no cameras", metadata={"cameras": []})
        return ToolResult(ok=True, output="\n".join([f"{len(cams)} Ring camera(s):"] + [_line(c) for c in cams]),
                          metadata={"cameras": [{"name": c.name, "kind": c.kind, "battery": c.battery,
                                                 "light": c.has_light, "siren": c.has_siren} for c in cams]})


class RingSnapshotTool(_RingTool):
    name = "ring_snapshot"
    description = ("A fresh still from a Ring camera (`camera`, or `all`), saved under workspace/cameras/ring/ -- the "
                   "dashboard's camera tiles show the newest one. A battery camera may have none until it wakes.")
    args_schema = {"type": "object", "properties": {"camera": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        wanted = str(args.get("camera") or "").strip()
        try:
            cloud = self._cloud()
            if wanted.lower() in ("all", "*", "every"):
                cams = await self._cameras(cloud)
                problem = "" if cams else "refused: this Ring account has no cameras"
            else:
                cam, problem = await self._camera(cloud, wanted)
                cams = [cam] if cam else []
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if problem:
            return ToolResult(ok=False, error=problem)
        folder = self._folder(ctx)
        saved, misses = [], []
        for cam in cams:
            path, why = await self._save_still(cloud, cam, folder)
            if path is not None:
                saved.append((cam, path))
            else:
                misses.append(why)
        if not saved:
            return ToolResult(ok=False, error="no still: " + "; ".join(misses))
        rels = [str(RING_DIR / p.name) for _c, p in saved]
        lines = [f"{c.name}: {RING_DIR / p.name} ({p.stat().st_size // 1024} KB)" for c, p in saved] + misses
        return ToolResult(ok=True, output="\n".join(lines), side_effects=tuple(f"file_create:{r}" for r in rels),
                          metadata={"paths": rels, "cameras": [c.name for c, _p in saved]})


class RingEventsTool(_RingTool):
    name = "ring_events"
    read_only = True
    reversibility = "read_only"
    description = ("Recent Ring events -- rings (`ding`), motion, live views -- newest first, for one `camera` or all; "
                   "`limit` per camera (default 10). Also kept in workspace/cameras/ring/events.json for the dashboard.")
    args_schema = {"type": "object", "properties": {"camera": {"type": "string"}, "limit": {"type": "integer"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        wanted = str(args.get("camera") or "").strip()
        try:
            limit = max(1, min(50, int(args.get("limit") or 10)))
        except (TypeError, ValueError):
            limit = 10
        try:
            cloud = self._cloud()
            if wanted and wanted.lower() not in ("all", "*"):
                cam, problem = await self._camera(cloud, wanted)
                if problem:
                    return ToolResult(ok=False, error=problem)
                cams = [cam]
            else:
                cams = await self._cameras(cloud)
            events: list[dict] = []
            for cam in cams:
                for e in await cloud.history(cam.id, limit=limit):
                    events.append({**e, "camera": cam.name})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        events.sort(key=lambda e: e.get("at") or 0, reverse=True)
        self._write_events(self._folder(ctx), events, {c.id: c.name for c in cams})
        if not events:
            return ToolResult(ok=True, output="no recent Ring events", metadata={"events": []})
        lines = [f"{len(events)} event(s):"] + [
            f"  {_stamp(e.get('at'))}  {e['camera']}: {e['kind']}" + ("  (answered)" if e.get("answered") else "") for e in events[:30]]
        return ToolResult(ok=True, output="\n".join(lines), metadata={"events": events[:100]})


def _stamp(at: float | None) -> str:
    if not at:
        return "        "
    return time.strftime("%a %H:%M", time.localtime(at))


class RingLightTool(_RingTool):
    name = "ring_light"
    description = "A Ring camera's light: `camera` and `on` (true/false). Only cameras that have one."
    args_schema = {"type": "object", "required": ["camera"],
                   "properties": {"camera": {"type": "string"}, "on": {"type": "boolean"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        wanted, on = _camera_and_switch(args, "on")
        try:
            cloud = self._cloud()
            cam, problem = await self._camera(cloud, wanted)
            if problem:
                return ToolResult(ok=False, error=problem)
            if not cam.has_light:
                return ToolResult(ok=False, error=f"refused: {cam.name} has no light")
            await cloud.light(cam.id, on)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        return ToolResult(ok=True, output=f"{cam.name}: light {'on' if on else 'off'}", side_effects=(f"ring_light:{cam.safe}",),
                          metadata={"camera": cam.name, "on": on})


class RingSirenTool(_RingTool):
    name = "ring_siren"
    reversibility = "irreversible"
    description = "Sound a Ring camera's siren for `seconds` (default 10, at most 60). Loud; only when plainly asked."
    args_schema = {"type": "object", "required": ["camera"],
                   "properties": {"camera": {"type": "string"}, "seconds": {"type": "integer"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        wanted = str(args.get("camera") or "").strip()
        try:
            seconds = max(1, min(60, int(args.get("seconds") or 10)))
        except (TypeError, ValueError):
            seconds = 10
        try:
            cloud = self._cloud()
            cam, problem = await self._camera(cloud, wanted)
            if problem:
                return ToolResult(ok=False, error=problem)
            if not cam.has_siren:
                return ToolResult(ok=False, error=f"refused: {cam.name} has no siren")
            await cloud.siren(cam.id, seconds)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        return ToolResult(ok=True, output=f"{cam.name}: siren for {seconds}s", side_effects=(f"ring_siren:{cam.safe}",),
                          metadata={"camera": cam.name, "seconds": seconds})


class RingWatchTool(_RingTool):
    name = "ring_watch"
    description = ("Poll Ring on a timer (`on`/`off`): new rings and motions go on the bus and on screen as they arrive, "
                   "and a fresh still per camera is saved for the dashboard. `every_s` between polls (default from config).")
    args_schema = {"type": "object", "properties": {"on": {"type": "boolean"}, "every_s": {"type": "number"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        raw = args.get("on")
        on = raw if isinstance(raw, bool) else str(raw or "on").strip().lower() not in ("off", "false", "no", "0", "stop")
        task = self._prefs.watcher
        if not on:
            if task is not None and not task.done():
                task.cancel()
            self._prefs.watcher = None
            return ToolResult(ok=True, output="not watching Ring", side_effects=("ring_watch:off",))
        bus = getattr(ctx, "bus", None)
        if bus is None:
            return ToolResult(ok=False, error="refused: no bus to deliver events on")
        try:
            every = float(args.get("every_s") or getattr(self._config, "ring_poll_s", 120.0))
        except (TypeError, ValueError):
            every = 120.0
        every = max(30.0, every)
        try:
            cloud = self._cloud()
            cams = await self._cameras(cloud)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: {exc}")
        if task is not None and not task.done():
            task.cancel()
        folder = self._folder(ctx)
        self._prefs.watcher = asyncio.create_task(self._watch(bus, cloud, folder, every), name="ring-watch")
        return ToolResult(ok=True, output=f"watching {len(cams)} Ring camera(s) every {every:.0f}s; events show on screen, "
                                          f"stills land in {RING_DIR}/", side_effects=("ring_watch:on",),
                          metadata={"cameras": [c.name for c in cams], "every_s": every})

    async def tick(self, bus, cloud, folder: Path, *, first: bool = False) -> int:
        """One poll: new events announced (none on the first pass, which
        only learns what is already there), stills refreshed. Returns
        how many events were announced."""
        cams = await self._cameras(cloud)
        names = {c.id: c.name for c in cams}
        fresh: list[dict] = []
        for cam in cams:
            try:
                for e in await cloud.history(cam.id, limit=10):
                    fresh.append({**e, "camera": cam.name})
            except Exception:  # noqa: BLE001
                continue
        announced = 0
        for e in sorted(fresh, key=lambda e: e.get("at") or 0):
            if e["id"] in self._prefs.seen:
                continue
            self._prefs.seen.add(e["id"])
            if first:
                continue
            index = next((i for i, c in enumerate(cams) if c.id == e.get("camera_id")), 0)
            await bus.publish(Message.new(topics.CAMERA_EVENT, source="execution",
                                          payload={"channel": index, "camera": e["camera"], "kinds": [e["kind"]], "host": "ring"}))
            glyph = "🔔" if e["kind"] == "ding" else "📷"
            await bus.publish(Message.new(topics.UI_NOTICE, source="execution", payload={
                "level": "info", "source": "ring", "text": f"{glyph} {e['camera']}: {e['kind']}"}))
            announced += 1
        if len(self._prefs.seen) > 5000:
            self._prefs.seen = set(list(self._prefs.seen)[-2000:])
        if fresh:
            self._write_events(folder, fresh, names)
        snap_every = float(getattr(self._config, "ring_snapshot_every_s", 300.0))
        now = self._clock()
        last = getattr(self._prefs, "_last_snap", 0.0)
        if first or now - last >= snap_every:
            for cam in cams:
                await self._save_still(cloud, cam, folder)
            self._prefs._last_snap = now  # noqa: SLF001
        return announced

    async def _watch(self, bus, cloud, folder: Path, every: float) -> None:
        first = True
        while True:
            try:
                await self.tick(bus, cloud, folder, first=first)
            except Exception:  # noqa: BLE001 -- the loop outlives Ring's bad minute
                pass
            first = False
            await asyncio.sleep(every)


def _camera_and_switch(args: dict, key: str) -> tuple[str, bool]:
    camera = str(args.get("camera") or "").strip()
    raw = args.get(key)
    if isinstance(raw, bool):
        return camera, raw
    words = camera.split()
    if words and words[-1].lower() in ("on", "off") and raw is None:
        return " ".join(words[:-1]), words[-1].lower() == "on"
    return camera, str(raw if raw is not None else "on").strip().lower() in ("on", "true", "1", "yes")


def ring_tools(config, **kwargs) -> list:
    kwargs = {k: v for k, v in kwargs.items() if k in ("cloud", "env", "secrets", "clock", "settings_home")}
    prefs = RingPreferences()
    return [RingSetupTool(config, prefs=prefs, **kwargs), RingListTool(config, prefs=prefs, **kwargs),
            RingSnapshotTool(config, prefs=prefs, **kwargs), RingEventsTool(config, prefs=prefs, **kwargs),
            RingLightTool(config, prefs=prefs, **kwargs), RingSirenTool(config, prefs=prefs, **kwargs),
            RingWatchTool(config, prefs=prefs, **kwargs)]


__all__ = ["RingCamera", "RingCloud", "RingEventsTool", "RingLightTool", "RingListTool", "RingPreferences",
           "RingSetupTool", "RingSirenTool", "RingSnapshotTool", "RingWatchTool", "available", "ring_tools"]
