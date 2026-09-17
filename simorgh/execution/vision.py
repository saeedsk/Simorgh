"""What the cameras saw.

A camera event says "channel 3, person". That is a fact, and it is not
what happened: a person at the side gate at two in the afternoon is the
postman, and the same event at two in the morning is worth getting up
for. The creator, 2026-09-15: "upon receving event from camra, take
couple of still images, do image processign and figure out what is
happneing and send a notification on screen with date and time,
describibg the vent, aslo announcing that with its voice".

So on `world.camera.event` -- from the Reolink NVR (home/cameras.py) or
from Ring (home/ring.py), both publish it -- Sim takes a couple of
stills a moment apart, asks a model that can actually see them what is
going on, and says so: on screen with the date and time, and out loud.

The looking happens in Cognition, over the bus (`cognition.think` with
`images`), because Cognition owns every model Sim has. Execution holds
the cameras and does the rest.

Two stills rather than one: a single frame cannot tell standing from
walking away, and the second frame is what turns "a car in the
driveway" into "a car pulling out of the driveway".
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ToolContext, ToolResult

# Kept short on purpose: this is spoken aloud, and a paragraph read out
# by a text-to-speech engine over a doorbell is worse than silence.
PROMPT = (
    "These are {count} still frames from the {camera} camera, taken a moment apart"
    "{kinds}. In one or two short sentences, say what is happening -- who or what is "
    "there and what they are doing. Plain words, no preamble, no markdown, no list. "
    "If the frames are too dark or too blurred to tell, say exactly that instead of guessing."
)

#: What the model answers when a camera event turned out to be nothing.
NOTHING = "NOTHING"

#: The creator, live 2026-09-16, after Sim announced "a residential street
#: with a driveway ... the street is quiet, with no visible movement or
#: people": "you are descbing my home, isntead i expect you to describe
#: the event ... you should laearn the camera statis elemenets and next
#: time you process the camer, avoide telling me imag estatis componenets
#: an djust tell me what happened".
#:
#: So the camera's own scene is given to the model as words and excluded
#: by name. Words rather than a reference frame on purpose: a baseline
#: image has to be matched against darkness, headlights, rain and a
#: moved bush, and "a driveway, a wooden trellis, a garden" survives all
#: of those unchanged.
EVENT_PROMPT = (
    "These are {count} still frames from the {camera} camera, taken a moment apart"
    "{kinds}.\n\n"
    "This camera normally shows: {baseline}\n\n"
    "Say ONLY what is happening that is NOT part of that normal scene -- a person, an "
    "animal, a vehicle arriving or leaving, a package left or taken, a child playing, a "
    "door or gate that has opened. One or two short sentences, plain words, no preamble.\n"
    "If the frames show only the normal scene -- however the light, weather or time of day "
    "differs -- answer with the single word {nothing}. Answer {nothing} rather than "
    "describing the house, the garden, the sky or the parked cars that are always there.\n"
    "If the frames are too dark or blurred to tell, say exactly that."
)

#: Learning the scene: asked of the frames Sim sees when nothing is
#: happening, once per camera, and reused until the camera is renamed or
#: the file is deleted.
BASELINE_PROMPT = (
    "These are {count} still frames from the {camera} camera"
    "{kinds}. List, in one sentence, only the FIXED things in view -- buildings, walls, "
    "paths, driveways, fences, gates, trees, garden beds, permanent outdoor furniture. "
    "Do NOT mention anything that could be moved or could leave: people, animals, "
    "vehicles, packages or parcels, bins, bicycles, toys, tools. "
    "Do NOT mention weather, the time of day, shadows or light levels. "
    "Plain words, no preamble."
)

#: The last of the samples is turned into the baseline by this, which
#: is the whole point of taking more than one: anything that moved
#: between the samples was never scenery.
#:
#: `permanently parked vehicles` used to be in the list above, and a
#: camera cannot tell permanent from parked-right-now in frames taken a
#: moment apart -- so one car in the drive at learning time became part
#: of the house forever. Packages were not excluded at all, which is
#: worse: a parcel on the step when the baseline was learnt makes every
#: later delivery "nothing new", and "was there a package today?" is the
#: question these cameras are actually asked (the creator, 2026-09-16).
CONFIRM_PROMPT = (
    "These are {count} still frames from the {camera} camera{kinds}.\n\n"
    "At other quiet moments, this camera was described as:\n{baseline}\n\n"
    "Reply with one sentence listing ONLY the fixed things that are in the frames now "
    "AND in every one of those descriptions. Leave out anything that appears in some but "
    "not others -- it moved, so it is not part of the scene. Leave out people, animals, "
    "vehicles, packages, bins and bicycles even if they appear every time. "
    "Plain words, no preamble."
)


BASELINE_FILE = Path("workspace/cameras/baselines.json")


def _baselines(root: Path) -> dict:
    try:
        return json.loads((root / BASELINE_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _baseline_record(root: Path, camera: str) -> dict:
    """`{"scene": str, "samples": [str]}` for one camera.

    Tolerates the older shape, where the value was the scene string
    itself: a baseline already learnt stays learnt across this change.
    """
    raw = _baselines(root).get(camera)
    if isinstance(raw, str):
        return {"scene": raw, "samples": []}
    if isinstance(raw, dict):
        return {"scene": str(raw.get("scene") or ""),
                "samples": [str(x) for x in (raw.get("samples") or []) if str(x).strip()]}
    return {"scene": "", "samples": []}


def _remember_baseline(root: Path, camera: str, scene: str = "", samples=()) -> None:
    """What this camera always shows, kept between restarts.

    A file rather than memory: learning the scene costs a model call, and
    paying it again every boot -- while announcing whatever the first
    event happened to be -- is the behaviour this replaces.
    """
    path = root / BASELINE_FILE
    known = _baselines(root)
    known[camera] = {"scene": scene, "samples": [str(x) for x in samples]}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(known, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


async def describe_stills(paths: list[str], *, camera: str, bus, kinds=(), timeout: float = 60.0,
                          template: str = "", baseline: str = "") -> tuple[str, str]:
    """`(description, problem)` for a few stills, through Cognition.

    A function, not a method, because two callers need it: the watcher
    below, and `camera_describe` -- the tool that lets a person ask.
    Without the tool the capability existed and the model did not know
    it: asked "do you have the ability to do image recognition for the
    ring cameras", Sim answered "no built-in image recognition on my
    side" while this very code was running (live 2026-09-15).
    """
    kinds = [str(k) for k in (kinds or []) if str(k).strip()]
    kinds_text = f" after the camera reported {', '.join(kinds)}" if kinds else ""
    prompt = (template or PROMPT).format(count=len(paths), camera=camera, kinds=kinds_text,
                                         baseline=baseline or "", nothing=NOTHING)
    request = Message.new(
        topics.COGNITION_THINK, source="execution",
        payload={
            "purpose": "chat",
            "messages": [{"role": "user", "content": prompt}],
            "budget": {"max_tokens": 200, "max_cost_usd": 0.02},
            "require_real_provider": True,
            "images": list(paths),
        },
    )
    reply = await bus.request_or_error(request, timeout=timeout)
    body = reply.payload or {}
    if body.get("ok") is False:
        return "", str(body.get("error") or "")[:200]
    # An empty answer is not a problem to report -- it is nothing to say.
    # Reporting it turned a dud reply into "Sim could not look" on screen,
    # which is the line reserved for having no eyes at all.
    return str(body.get("text") or "").strip(), ""


class CameraDescribeTool:
    """What a camera can see, asked for rather than waited for."""

    name = "camera_describe"
    # Not read_only: looking means taking stills, and a still is a file on
    # disk -- the same reason `cam_snapshot` is reversible rather than
    # read-only. Guardian trusts this label, so it has to be the true one.
    read_only = False
    reversibility = "reversible"
    description = ("What a camera can see right now, in words. `camera` is its name -- a Reolink camera on the "
                   "NVR or a Ring one. Takes a couple of stills and describes them; needs a vision model "
                   "([cognition.providers.ollama] vision_model).")
    args_schema = {"type": "object", "required": ["camera"],
                   "properties": {"camera": {"type": "string"}, "stills": {"type": "integer"}}}

    def __init__(self, config, **kwargs) -> None:
        self._config = config
        self._kwargs = {k: v for k, v in kwargs.items() if k in ("env", "secrets", "clock", "settings_home")}
        self._nvr_given = kwargs.get("nvr")
        self._ring_given = kwargs.get("cloud")

    def _snapshot_tools(self) -> list:
        from .home.cameras import CamSnapshotTool
        from .home.ring import RingSnapshotTool

        nvr = CamSnapshotTool(self._config, nvr=self._nvr_given, **self._kwargs)
        ring = RingSnapshotTool(self._config, cloud=self._ring_given, **self._kwargs)
        return [nvr, ring]

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        camera = str(args.get("camera") or "").strip()
        if not camera:
            return ToolResult(ok=False, error="which camera? name one, e.g. `camera_describe Front Door`")
        if ctx.bus is None:
            return ToolResult(ok=False, error="refused: no bus, so there is nothing to ask about the picture")
        try:
            wanted = max(1, min(4, int(args.get("stills") or self._config.camera_vision_stills)))
        except (TypeError, ValueError):
            wanted = 2
        gap = float(getattr(self._config, "camera_vision_gap_s", 1.5))
        root = Path(self._config.repo_root)

        paths: list[str] = []
        refusals: list[str] = []
        for tool in self._snapshot_tools():
            for index in range(wanted):
                if index:
                    await asyncio.sleep(gap)
                try:
                    result = await tool.run({"camera": camera}, ctx=ctx)
                except Exception as exc:  # noqa: BLE001 -- a camera that will not answer is not a crash
                    refusals.append(f"{tool.name}: {exc!r}"[:160])
                    break
                if not result.ok:
                    refusals.append(f"{tool.name}: {result.error or ''}"[:200])
                    break
                meta = result.metadata or {}
                rels = [meta["path"]] if meta.get("path") else list(meta.get("paths") or [])
                paths.extend(str(root / rel) for rel in rels)
            if paths:
                break
        if not paths:
            return ToolResult(ok=False, error="no picture from that camera: " + "; ".join(refusals or ["unknown"]))

        said, problem = await describe_stills(
            paths, camera=camera, bus=ctx.bus,
            timeout=float(getattr(self._config, "camera_vision_timeout_s", 60.0)))
        if problem or not said:
            why = problem or "the model returned nothing"
            return ToolResult(ok=False, error=f"took {len(paths)} still(s) but could not look at them: {why}")
        return ToolResult(ok=True, output=f"{camera}: {said}",
                          metadata={"camera": camera, "stills": len(paths), "description": said})


def vision_tools(config, **kwargs) -> list:
    return [CameraDescribeTool(config, **kwargs)]


class _NullLock:
    """`async with` that guards nothing -- the NVR answers concurrently."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


_NO_LOCK = _NullLock()


class CameraVision:
    """The camera-event watcher. One instance per Execution service."""

    def __init__(self, *, config, registry, ctx) -> None:
        self._config = config
        self._registry = registry
        self._ctx = ctx
        # When each camera was last looked at, so a person walking past a
        # driveway camera is one description rather than one per motion
        # event for as long as they are in frame.
        self._last_look: dict[str, float] = {}
        self._busy: set[str] = set()
        self._tasks: set[asyncio.Task] = set()
        # Built lazily: a Semaphore binds to the loop it is made on,
        # and this object is constructed before there is one.
        self._looking: asyncio.Semaphore | None = None
        # "Sim cannot see" is worth saying once, not once per event.
        self._said_blind = False
        # One Ring snapshot at a time across every camera (see `_stills`).
        self._ring_lock = asyncio.Lock()
        #: The background sweep that learns a scene without being asked.
        self._sweep: asyncio.Task | None = None

    # -- the handler ------------------------------------------------------
    async def on_camera_event(self, message: Message) -> None:
        """Never blocks the bus: looking takes a model call, and the
        events keep coming while it runs."""
        if not getattr(self._config, "camera_vision", True):
            return
        payload = message.payload or {}
        camera = str(payload.get("camera") or "").strip() or "a camera"
        now = self._ctx.clock.now()
        cooldown = float(getattr(self._config, "camera_vision_cooldown_s", 90.0))
        if camera in self._busy or now - self._last_look.get(camera, 0.0) < cooldown:
            return
        self._last_look[camera] = now
        self._busy.add(camera)
        task = asyncio.create_task(self._look(payload, camera), name=f"camera-vision:{camera}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _gate(self) -> asyncio.Semaphore:
        if self._looking is None:
            width = max(1, int(getattr(self._config, "camera_vision_concurrency", 1) or 1))
            self._looking = asyncio.Semaphore(width)
        return self._looking

    async def _look(self, payload: dict, camera: str) -> None:
        # Queued, not dropped: a camera that tripped waits its turn
        # while staying in `_busy`, so its own repeats are still
        # suppressed and the burst is answered one good answer at a
        # time rather than seven bad ones at once.
        try:
            async with self._gate():
                await self._look_now(payload, camera)
        finally:
            self._busy.discard(camera)

    async def _look_now(self, payload: dict, camera: str) -> None:
        try:
            stills = await self._stills(payload, camera)
            if not stills:
                return
            root = Path(self._config.repo_root)
            record = _baseline_record(root, camera)
            baseline = record["scene"]
            if not baseline:
                # Nothing confirmed about this camera yet. These frames are
                # the WORST evidence for "what is always here": the camera
                # fired because something moved, so whatever triggered it is
                # in shot. One sample makes that thing part of the house.
                # So sample several separate events and keep only what
                # survives all of them.
                samples = record["samples"]
                want = max(1, int(getattr(self._config, "camera_vision_baseline_samples", 3)))
                if len(samples) + 1 >= want:
                    if samples:
                        prior = "\n".join(f"- {text}" for text in samples)
                        scene, problem = await self._ask(stills, camera, payload, CONFIRM_PROMPT,
                                                         baseline=prior)
                    else:
                        # `want` of 1: one look is all that was asked for.
                        scene, problem = await self._ask(stills, camera, payload, BASELINE_PROMPT)
                    if scene and not problem:
                        _remember_baseline(root, camera, scene)
                        self._ctx.logger.info("camera_vision_baseline_learnt", camera=camera,
                                              scene=scene[:160], samples=len(samples) + 1)
                    return
                sample, problem = await self._ask(stills, camera, payload, BASELINE_PROMPT)
                if sample and not problem:
                    _remember_baseline(root, camera, samples=[*samples, sample])
                    self._ctx.logger.info("camera_vision_baseline_sample", camera=camera,
                                          have=len(samples) + 1, want=want)
                return
            said, problem = await self._ask(stills, camera, payload, EVENT_PROMPT, baseline=baseline)
            if problem:
                if not self._said_blind:
                    self._said_blind = True
                    await self._notice(f"📷 {camera}: something happened, but Sim could not look ({problem[:120]}).")
                self._ctx.logger.warning("camera_vision_no_answer", camera=camera, detail=problem[:200])
                return
            if not said or said.strip().strip(".").upper() == NOTHING:
                # The camera fired and there was nothing in it but the
                # camera's own view. Saying so out loud is the noise this
                # exists to remove.
                self._ctx.logger.info("camera_vision_nothing", camera=camera)
                return
            await self._announce(said, camera)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- a camera is not worth crashing Execution over
            self._ctx.logger.warning("camera_vision_failed", camera=camera, error=repr(exc))
        finally:
            self._busy.discard(camera)


    # -- learning a scene without being asked ------------------------------
    async def start(self) -> None:
        """Go and learn what each camera always shows.

        A baseline used to advance only when motion fired a camera, so a
        quiet camera never learnt one and the first real event on it was
        judged against nothing. Worse, it made the person responsible for
        a machine's job: on 2026-09-16 the creator was asked to choose
        between seeding by hand, walking past each camera, and changing a
        sample count -- "camera baselining should happen automatically,
        user should not get bothered with this kind of details, this are
        machine's job."

        Bounded by construction. Only cameras with no confirmed scene are
        visited and each visit adds one sample, so the whole cost is
        `cameras x camera_vision_baseline_samples` model calls, once, on
        the local vision model -- and the sweep returns for good the
        moment every camera knows its scene.
        """
        if not getattr(self._config, "camera_vision", True):
            return
        if not getattr(self._config, "camera_vision_baseline_sweep", True):
            return
        if self._sweep is None or self._sweep.done():
            self._sweep = asyncio.create_task(self._learn_baselines(), name="camera-vision:baselines")

    async def stop(self) -> None:
        task, self._sweep = self._sweep, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _learn_baselines(self) -> None:
        """One sample per unlearned camera, then wait, then again.

        The waiting is the point: three samples taken seconds apart are
        three views of the same moment, and a parked car would survive
        all of them. Spread across `camera_vision_baseline_every_s` they
        are three different moments, which is what makes "only what
        survives every sample" mean anything.
        """
        every = max(30.0, float(getattr(self._config, "camera_vision_baseline_every_s", 300.0)))
        # No floor here: `every` is floored at 30s, so the loop cannot spin,
        # and a setting that accepts 0 should mean 0 rather than quietly 1.
        await asyncio.sleep(max(0.0, float(getattr(self._config, "camera_vision_baseline_first_s", 30.0))))
        while True:
            try:
                todo = await self._unlearned()
                if not todo:
                    self._ctx.logger.info("camera_vision_baselines_complete")
                    return
                for camera, host in todo:
                    if camera in self._busy:
                        continue
                    self._busy.add(camera)          # `_look` discards it in its own `finally`
                    await self._look({"host": host, "camera": camera, "kinds": []}, camera)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- a camera is not worth crashing Execution over
                self._ctx.logger.warning("camera_vision_sweep_failed", error=repr(exc))
            await asyncio.sleep(every)

    async def _unlearned(self) -> list[tuple[str, str]]:
        """`(camera, host)` for every camera with no confirmed scene.

        Names come from `metadata["cameras"]`, never from the printed
        lines: the NVR lists plain strings and Ring lists dicts, and
        scraping either would break the first time a model changed.
        """
        root = Path(self._config.repo_root)
        out: list[tuple[str, str]] = []
        for tool_name, host in (("cam_list", ""), ("ring_list", "ring")):
            tool = self._registry.get(tool_name)
            if tool is None:
                continue
            ctx = ToolContext(
                action_id=f"camera-baseline-{int(self._ctx.clock.now())}", task_id=None, scope={},
                constraints={}, data_dir=root, clock=self._ctx.clock, logger=self._ctx.logger,
                ledger=self._ctx.ledger, bus=self._ctx.bus,
            )
            try:
                result = await tool.run({}, ctx=ctx)
            except Exception as exc:  # noqa: BLE001 -- a camera source that will not answer is skipped
                self._ctx.logger.warning("camera_vision_list_failed", source=tool_name, error=repr(exc))
                continue
            if not result.ok:
                continue
            for entry in (result.metadata or {}).get("cameras") or []:
                name = str(entry.get("name") if isinstance(entry, dict) else entry or "").strip()
                if name and not _baseline_record(root, name)["scene"]:
                    out.append((name, host))
        return out

    # -- the pictures -----------------------------------------------------
    async def _stills(self, payload: dict, camera: str) -> list[str]:
        """A couple of frames, a moment apart, as absolute paths."""
        ring = str(payload.get("host") or "").lower() == "ring"
        tool = self._registry.get("ring_snapshot" if ring else "cam_snapshot")
        if tool is None:
            return []
        root = Path(self._config.repo_root)
        wanted = max(1, int(getattr(self._config, "camera_vision_stills", 2)))
        gap = float(getattr(self._config, "camera_vision_gap_s", 1.5))
        if ring:
            # Ring throttles. Three cameras firing at once, two stills each,
            # is six snapshot calls in a few seconds and every one of them
            # came back empty all day (2026-09-16) -- while the same cameras
            # answered in 2.4s when asked one at a time. One frame, and one
            # caller at a time.
            wanted = 1
        paths: list[str] = []
        async with (self._ring_lock if ring else _NO_LOCK):
            for index in range(wanted):
                if index:
                    await asyncio.sleep(gap)
                ctx = ToolContext(
                    action_id=f"camera-vision-{int(self._ctx.clock.now())}-{index}", task_id=None, scope={},
                    constraints={}, data_dir=root, clock=self._ctx.clock, logger=self._ctx.logger,
                    ledger=self._ctx.ledger, bus=self._ctx.bus,
                )
                try:
                    result = await tool.run({"camera": camera}, ctx=ctx)
                except Exception as exc:  # noqa: BLE001 -- a camera that will not answer is one fewer frame
                    self._ctx.logger.warning("camera_vision_snapshot_failed", camera=camera, error=repr(exc))
                    continue
                if not result.ok:
                    self._ctx.logger.warning("camera_vision_snapshot_refused", camera=camera,
                                             detail=(result.error or "")[:160])
                    continue
                # `cam_snapshot` saves one file and says `path`; `ring_snapshot`
                # may save several and says `paths`. Both are relative to the root.
                meta = result.metadata or {}
                rels = [meta["path"]] if meta.get("path") else list(meta.get("paths") or [])
                paths.extend(str(root / rel) for rel in rels)
        return paths

    # -- the looking ------------------------------------------------------
    async def _ask(self, stills: list[str], camera: str, payload: dict, template: str,
                   *, baseline: str = "") -> tuple[str, str]:
        # No floor answer anywhere on this path: a canned sentence about a
        # camera nobody looked at is exactly the "succeeded while saying
        # nothing true" shape Sim is not allowed to have.
        return await describe_stills(
            stills, camera=camera, bus=self._ctx.bus, kinds=payload.get("kinds") or (),
            timeout=float(getattr(self._config, "camera_vision_timeout_s", 60.0)),
            template=template, baseline=baseline)

    # -- the telling ------------------------------------------------------
    async def _announce(self, said: str, camera: str) -> None:
        stamp = time.strftime("%a %d %b %H:%M", time.localtime(self._ctx.clock.now()))
        await self._notice(f"📷 {stamp} — {camera}: {said}")
        if not getattr(self._config, "camera_vision_speak", True):
            return
        # Spoken without the date: a person standing in the room already
        # knows what day it is, and the screen line carries it anyway.
        await self._ctx.bus.publish(Message.new(
            topics.VOICE_SPEAK_REQUEST, source="execution", payload={"text": f"{camera}: {said}"},
        ))

    async def _notice(self, text: str) -> None:
        await self._ctx.bus.publish(Message.new(
            topics.UI_NOTICE, source="execution",
            payload={"level": "info", "text": text, "source": "cameras"},
        ))


__all__ = ["BASELINE_PROMPT", "CONFIRM_PROMPT", "CameraDescribeTool", "CameraVision", "EVENT_PROMPT", "NOTHING",
           "PROMPT", "describe_stills", "vision_tools"]
