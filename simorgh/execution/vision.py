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
import time
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ToolContext

# Kept short on purpose: this is spoken aloud, and a paragraph read out
# by a text-to-speech engine over a doorbell is worse than silence.
PROMPT = (
    "These are {count} still frames from the {camera} camera, taken a moment apart"
    "{kinds}. In one or two short sentences, say what is happening -- who or what is "
    "there and what they are doing. Plain words, no preamble, no markdown, no list. "
    "If the frames are too dark or too blurred to tell, say exactly that instead of guessing."
)


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
        # "Sim cannot see" is worth saying once, not once per event.
        self._said_blind = False

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

    async def _look(self, payload: dict, camera: str) -> None:
        try:
            stills = await self._stills(payload, camera)
            if not stills:
                return
            said = await self._describe(stills, camera, payload)
            if said:
                await self._announce(said, camera)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- a camera is not worth crashing Execution over
            self._ctx.logger.warning("camera_vision_failed", camera=camera, error=repr(exc))
        finally:
            self._busy.discard(camera)

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
        paths: list[str] = []
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
    async def _describe(self, stills: list[str], camera: str, payload: dict) -> str:
        kinds = [str(k) for k in (payload.get("kinds") or []) if str(k).strip()]
        kinds_text = f" after the camera reported {', '.join(kinds)}" if kinds else ""
        prompt = PROMPT.format(count=len(stills), camera=camera, kinds=kinds_text)
        request = Message.new(
            topics.COGNITION_THINK, source="execution",
            payload={
                "purpose": "chat",
                "messages": [{"role": "user", "content": prompt}],
                "budget": {"max_tokens": 200, "max_cost_usd": 0.02},
                # No floor answer: a canned sentence about a camera nobody
                # looked at is exactly the "succeeded while saying nothing
                # true" shape Sim is not allowed to have.
                "require_real_provider": True,
                "images": stills,
            },
        )
        timeout = float(getattr(self._config, "camera_vision_timeout_s", 60.0))
        reply = await self._ctx.bus.request_or_error(request, timeout=timeout)
        body = reply.payload or {}
        if body.get("ok") is False:
            detail = str(body.get("error") or {})
            if not self._said_blind:
                self._said_blind = True
                await self._notice(f"📷 {camera}: something happened, but Sim could not look "
                                   f"({detail[:120]}).")
            self._ctx.logger.warning("camera_vision_no_answer", camera=camera, detail=detail[:200])
            return ""
        return str(body.get("text") or "").strip()

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


__all__ = ["CameraVision", "PROMPT"]
