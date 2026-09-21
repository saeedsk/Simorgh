"""World Model as a `Subsystem` -- env facets (real, this session) plus a
live-updating Self Model (identity real from boot; competence,
calibration, limitations, change history, and skills folded in real
time from Learning/Reflection events -- see `selfmodel.py`'s docstring
for exactly what's real vs. still an honest placeholder). Layer 1
(registry.py).
"""

from __future__ import annotations

import time
from dataclasses import replace

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message
from simorgh.contracts.people import may_check_in
from simorgh.contracts.protocols import Context, Health
from simorgh.contracts.registry import error_reply_payload
from simorgh.contracts.tone import split_tone

from .config import Config
from .facets.capability_map import CapabilityMapFacet
from .facets.file_index import FileIndexFacet
from .facets.git_state import GitStateFacet
from .facets.home import HomeFacet
from .facets.people import PeopleFacet
from .facets.registry_facets import ToolsFacet, UserProfileFacet
from .facets.wellbeing import WellbeingFacet
from .selfmodel import (
    add_change,
    add_limitation,
    add_skill,
    bump_restarts,
    update_goals,
    build_static_model,
    compute_gaps,
    mitigate_limitations,
    observe_tool,
    tools_snapshot,
    render_full_markdown,
    render_summary,
    replay,
    update_competence,
)

#: Where a change to what Sim knows about ITSELF is written down, so
#: the next boot can fold it back (stage 6 item 1). `self:` is this
#: subsystem's own prefix in `contracts/streamnames.py`.
SELF_CHANGES = "self:changes"

#: How many `action.result`s between tool-table snapshots. One
#: event per tool call would be a stream that grows as fast as
#: Sim works, which is the shape that produced 192,332 trace
#: streams in a day (stage 1).
TOOL_SNAPSHOT_EVERY = 50

NAME = "worldmodel"
VERSION = "0.1.0"


class Service:
    name = NAME
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.WORLD_ENV_QUERY, topics.SELF_SUMMARY, topics.SELF_GAPS,
        topics.TOOL_REGISTERED, topics.TOOL_UNAVAILABLE, topics.TOOL_PROBED,
        topics.PERSONA_USER_MODEL_UPDATED,
        topics.LEARN_COMPETENCE_UPDATED, topics.REFLECT_CALIBRATION_UPDATED, topics.SELF_OBSERVATION,
        topics.LEARN_SELF_PATCH_APPLIED, topics.LEARN_SELF_PATCH_REVERTED, topics.LEARN_SKILL_ACQUIRED,
        topics.SYSTEM_STARTED, topics.COGNITION_PROVIDER_STATUS,
        topics.TASK_CREATED, topics.TASK_COMPLETED, topics.TASK_FAILED, topics.TASK_BLOCKED,
        # The house (stage 6 item 3): the evidence the `home` facet folds.
        topics.CAMERA_EVENT, topics.TV_STATE, topics.VOICE_TRANSCRIPT, topics.ACTION_RESULT,
        # Who a person is, changed by a person (stage 6 item 4).
        topics.WORLD_PEOPLE_UPDATE,
        # How a consented person seems (stage 10 item 2): one trial per turn.
        topics.TURN_COMPLETED,
    )
    produces: tuple[str, ...] = (
        topics.WORLD_ENV_QUERY_REPLY, topics.SELF_SUMMARY_REPLY, topics.SELF_GAPS_REPLY, topics.SELF_MODEL_UPDATED,
        topics.WORLD_HOME_SITUATION_CHANGED, topics.WORLD_PEOPLE_UPDATE_REPLY, topics.WORLD_WELLBEING_CHANGED,
    )

    def __init__(self, config: Config | None = None) -> None:
        self._config_from_caller = config
        self.config = config or Config()
        self._ctx: Context | None = None
        self._subs: list = []
        self._restarts = 0
        self._model = None
        self._started_at = 0.0
        #: Results folded since the tool table was last written down.
        self._tool_writes = 0

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        # Live-caught as a class 2026-09-08: every service is handed its
        # own `[section]` from simorgh.toml (`kernel/context.py` builds
        # `ctx.config` for exactly this) and eleven of them never read
        # it. The settings existed, were documented, were parsed into a
        # Config dataclass with a `from_mapping` -- and nothing ever
        # called it, so changing the file changed nothing. The dominant
        # bug shape in this codebase: a designed slot with one side
        # implemented and nobody writing to it.
        #
        # A config passed by the caller still wins, so a test that
        # constructs the service with one is unaffected.
        if self._config_from_caller is None and ctx.config:
            self.config = Config.from_mapping(dict(ctx.config))
        self._started_at = ctx.clock.now()
        self._capability_map = CapabilityMapFacet(self.config.repo_root)
        self._file_index = FileIndexFacet(
            self.config.repo_root, max_files=self.config.file_index_max_files,
            refresh_seconds=self.config.file_index_refresh_seconds,
            # `scanned_at` has to be on the same clock as the `as_of`
            # `_on_env_query` stamps every reply with, or the one
            # subtraction the field exists for is meaningless.
            wall_clock=ctx.clock.now)
        self._git_state = GitStateFacet(self.config.repo_root)
        self._tools = ToolsFacet()
        self._booted = False
        self._user_profile = UserProfileFacet()
        # What the house is doing and who is in it (stage 6 item 3), folded
        # from the evidence Sim already sees.
        self._home = HomeFacet(clock=ctx.clock.now)
        # Who the people are (stage 6 item 4): one record per person, on
        # disk beside the rest of what Sim knows, seeded from the household.
        self._people = PeopleFacet(ctx.data_dir / "people.json")
        # How each consented adult seems against their own usual (stage
        # 10 item 2). The consent gate is the People store's answer, asked
        # on every observation, so a revoke takes effect on the next turn
        # -- and `_on_permission_revoked` drops what was kept.
        self._wellbeing = WellbeingFacet(ctx.data_dir / "wellbeing.json", clock=ctx.clock.now,
                                         consent=lambda name: may_check_in(self._people.by_name(name)))
        # The last spoken turn per speaker, so a `turn.completed` from the
        # voice channel can be scored with how fast it was said.
        self._spoken: dict[str, tuple[float, float]] = {}       # speaker -> (seconds, at)
        self._facets = {
            "capability_map": self._capability_map, "file_index": self._file_index,
            "git_state": self._git_state, "tools": self._tools, "user_profile": self._user_profile,
            "home": self._home, "people": self._people, "wellbeing": self._wellbeing,
        }
        self._model = build_static_model(
            soul_path=self.config.resolved_soul_path(), clock_now=self._started_at,
            areas=self._capability_map.areas(), continuity={"restarts": self._restarts},
        )
        # And then what has happened to it since (stage 6 item 1).
        await self._replay_self(ctx)
        try:
            (ctx.data_dir / "self").mkdir(parents=True, exist_ok=True)
            (ctx.data_dir / "self" / "SELF.md").write_text(render_full_markdown(self._model))
        except OSError as exc:
            ctx.logger.warning("worldmodel.self_render_failed", error=repr(exc))

        self._subs = [
            await ctx.bus.subscribe(topics.WORLD_ENV_QUERY, self._on_env_query),
            await ctx.bus.subscribe(topics.WORLD_PEOPLE_UPDATE, self._on_people_update),
            await ctx.bus.subscribe(topics.SELF_SUMMARY, self._on_self_summary),
            await ctx.bus.subscribe(topics.SELF_GAPS, self._on_self_gaps),
            await ctx.bus.subscribe(topics.TOOL_REGISTERED, self._on_tool_registered),
            await ctx.bus.subscribe(topics.TOOL_UNAVAILABLE, self._on_tool_unavailable),
            await ctx.bus.subscribe(topics.TOOL_PROBED, self._on_tool_probed),
            await ctx.bus.subscribe(topics.PERSONA_USER_MODEL_UPDATED, self._on_user_model_updated),
            await ctx.bus.subscribe(topics.LEARN_COMPETENCE_UPDATED, self._on_competence_updated),
            await ctx.bus.subscribe(topics.REFLECT_CALIBRATION_UPDATED, self._on_calibration_updated),
            await ctx.bus.subscribe(topics.SELF_OBSERVATION, self._on_self_observation),
            await ctx.bus.subscribe(topics.COGNITION_PROVIDER_STATUS, self._on_provider_status),
            await ctx.bus.subscribe(topics.LEARN_SELF_PATCH_APPLIED, self._on_self_patch_applied),
            await ctx.bus.subscribe(topics.LEARN_SELF_PATCH_REVERTED, self._on_self_patch_reverted),
            await ctx.bus.subscribe(topics.LEARN_SKILL_ACQUIRED, self._on_skill_acquired),
            await ctx.bus.subscribe(topics.SYSTEM_STARTED, self._on_system_started),
            await ctx.bus.subscribe(topics.TASK_CREATED, self._on_task_created),
            await ctx.bus.subscribe(topics.TASK_COMPLETED, self._on_task_finished),
            await ctx.bus.subscribe(topics.TASK_FAILED, self._on_task_finished),
            await ctx.bus.subscribe(topics.TASK_BLOCKED, self._on_task_blocked),
            await ctx.bus.subscribe(topics.CAMERA_EVENT, self._on_camera_event),
            await ctx.bus.subscribe(topics.ACTION_RESULT, self._on_action_result),
            await ctx.bus.subscribe(topics.TV_STATE, self._on_tv_state),
            await ctx.bus.subscribe(topics.VOICE_TRANSCRIPT, self._on_voice_transcript),
            await ctx.bus.subscribe(topics.TURN_COMPLETED, self._on_turn_completed),
        ]
        await self._ingest_loader_rollback(ctx)
        ctx.logger.info("worldmodel.started", areas=len(self._capability_map.areas()))

    async def _ingest_loader_rollback(self, ctx: Context) -> None:
        """If the Sim loader rolled this checkout back, make that a fact
        Sim knows about itself.

        `simloader.py` cannot write to the Ledger (it never imports this
        package; that independence is the whole point of a bootloader),
        so it leaves `last_rollback.json` where `SIMORGH_LOADER_NOTES`
        points and this reads it at boot. A rollback Sim never hears
        about is a regression it will make again.
        """
        import json
        import os
        from pathlib import Path

        notes = os.environ.get("SIMORGH_LOADER_NOTES")
        if not notes:
            return
        path = Path(notes).expanduser() / "last_rollback.json"
        if not path.exists():
            return
        try:
            note = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        seen = Path(notes).expanduser() / ".last_rollback_ingested"
        stamp = str(note.get("ts", ""))
        if seen.exists() and seen.read_text() == stamp:
            return  # already a limitation from a previous boot
        text = (
            f"The loader rolled me back from {note.get('from', '?')} to {note.get('to', '?')} "
            f"because: {note.get('reason', 'unknown')}. Whatever changed between those two "
            f"commits did not survive the gate; do not repeat it without a test that covers it."
        )
        now = ctx.clock.now()
        await self._record("limitation", {"text": text, "evidence": [], "since": now},
                           section="limitations", reason="loader.rollback")
        try:
            seen.write_text(stamp)
        except OSError:
            pass

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs = []

    async def health(self) -> Health:
        if self._ctx is None:
            return Health.down("not started")
        if not self.config.repo_root.is_dir():
            return Health.degraded(f"repo_root {self.config.repo_root} does not exist")
        return Health.ok()

    # -- the house (stage 6 item 3) --------------------------------------------------
    async def _on_camera_event(self, message: Message) -> None:
        p = message.payload
        camera = str(p.get("camera") or "")
        kinds = [str(k) for k in (p.get("kinds") or [])]
        if not camera:
            return
        self._home.observe(f"camera.{camera.lower().replace(' ', '_')}", kind="camera",
                           state=", ".join(kinds) or "event", area=camera, detail={"kinds": kinds})
        await self._announce_situation()

    async def _on_action_result(self, message: Message) -> None:
        """What Sim itself changed in the house.

        Every other source of the entity table is somebody else
        telling Sim what happened -- a camera, the TV, a voice in a
        room. Sim turning the kitchen light on was not evidence of
        anything until a camera saw it, so asked a minute later
        whether the light was on, Sim said it did not know. It had
        done it (stage 6 item 3).

        Only the entities the house reports as actually CHANGED, and
        only with the state they are now in: `home_call`'s metadata
        carries both, because Home Assistant answers 200 for a call
        on an unplugged bulb and "the call succeeded" is not "the
        house did something".
        """
        payload = message.payload or {}
        # Every result, before the home-specific part: how often each
        # tool works and how long it takes is the one thing Sim can
        # learn about itself from ordinary use, and it was being
        # thrown away on the line below (stage 6 item 1).
        tool = str(payload.get("tool") or "")
        # `_model` is None until `start()` has built it; a result that
        # arrives before then has nowhere to go and is not worth
        # crashing the handler over.
        if tool and getattr(self, "_model", None) is not None:
            self._model = observe_tool(
                self._model, tool=tool, ok=bool(payload.get("ok")),
                duration_ms=float(payload.get("duration_ms") or 0.0),
                updated_at=self._ctx.clock.now())
            # A snapshot every so often, not an event per call: one
            # `self:changes` entry per tool call is how this project
            # filled a disk with trace streams once already. The
            # aggregates are monotonic, so a snapshot lost to a crash
            # costs at most the calls since the last one.
            self._tool_writes += 1
            if self._tool_writes >= TOOL_SNAPSHOT_EVERY:
                self._tool_writes = 0
                await self._record("tool_stats", {"tool_stats": tools_snapshot(self._model)},
                                   section="tool_stats", reason="action.result")
        if not payload.get("ok") or tool not in ("home_call", "home_undo"):
            return
        metadata = payload.get("metadata") or {}
        after = metadata.get("after") or {}
        changed = [str(e) for e in (metadata.get("changed") or [])]
        for entity_id in changed:
            state = str(after.get(entity_id) or "")
            if not state:
                continue
            kind = entity_id.split(".", 1)[0]
            self._home.observe(entity_id, kind=kind, state=state,
                               detail={"by": "sim", "service": str(metadata.get("service") or "")})
        if changed:
            await self._announce_situation()

    async def _on_tv_state(self, message: Message) -> None:
        mode = str(message.payload.get("mode") or "none")
        self._home.observe("tv.family_room", kind="tv", state="playing" if mode != "none" else "idle",
                           area="family room", detail={"title": str(message.payload.get("title") or "")})
        await self._announce_situation()

    async def _on_voice_transcript(self, message: Message) -> None:
        """A placed voice is evidence of where that person is. A partial,
        an echo of Sim's own voice, or a voice nobody could place is not."""
        p = message.payload
        speaker = str(p.get("speaker") or "")
        if not speaker or p.get("partial") or p.get("echo"):
            return
        area = str(p.get("room") or p.get("device") or "") or "here"
        # A confident identification is worth more than a lean; the belief
        # is evidence, not a vote.
        confidence = float(p.get("confidence") or 0.0)
        strength = 0.9 if confidence >= 0.6 else 0.5
        # A lean is not an identification (stage 6 item 5): Guardian will
        # not let a voice approve anything that reaches outside the house
        # unless the speaker was actually recognised, and a 0.5 guess is
        # exactly the case where a television can be mistaken for Saeed.
        self._home.saw_person(speaker, area=area, strength=strength, verified=confidence >= 0.6)
        # How long the turn took to say, kept for the `turn.completed` that
        # follows it (stage 10 item 2). Only a verified voice: a lean is
        # not a person, and a person's baseline must be their own.
        if confidence >= 0.6 and float(p.get("seconds") or 0.0) > 0.0:
            self._spoken[speaker] = (float(p["seconds"]), self._ctx.clock.now())
        await self._announce_situation()

    # -- how each person seems (stage 10 item 2) ----------------------------------------
    async def _on_turn_completed(self, message: Message) -> None:
        """One trial per turn for the wellbeing facet. The facet refuses
        anybody `may_check_in` refuses, so a child's or a guest's turn is
        dropped here without a record. A turn with no known speaker is
        nobody's and is dropped too: a baseline must be one person's."""
        p = message.payload or {}
        speaker = str(p.get("speaker") or "").strip()
        user_text = str(p.get("user_text") or "")
        if not speaker or not user_text.strip():
            return
        tone, _rest = split_tone(str(p.get("text") or ""))
        seconds = None
        if str(p.get("channel") or "") == "voice":
            spoken = self._spoken.pop(speaker, None)
            if spoken is not None and self._ctx.clock.now() - spoken[1] <= 120.0:
                seconds = spoken[0]
        if self._wellbeing.observe(speaker, text=user_text, seconds=seconds, tone=tone):
            await self._announce_wellbeing()

    async def _announce_wellbeing(self) -> None:
        """Publish a state that moved (flips only), with the numbers it
        rests on and never the words it came from."""
        for person, est in self._wellbeing.changes():
            await self._ctx.bus.publish(Message.new(
                topics.WORLD_WELLBEING_CHANGED, source=self._ctx.bus.source,
                payload={"person": person, "state": est["state"], "mean": float(est["low"] or 0.0),
                         "evidence": float(est["evidence"] or 0.0), "since": self._ctx.clock.now()}))

    async def _announce_situation(self) -> None:
        """Publish the situation facts that have flipped (stage 6 item 7)."""
        for fact, value in self._home.changes():
            await self._ctx.bus.publish(Message.new(
                topics.WORLD_HOME_SITUATION_CHANGED, source=self._ctx.bus.source,
                payload={"fact": fact, "value": value, "people": self._home.situation().get("people") or {},
                         "since": self._ctx.clock.now()}))

    # -- handlers ------------------------------------------------------------------
    async def _on_env_query(self, message: Message) -> None:
        what = message.payload.get("what")
        facet = self._facets.get(what)
        if facet is None:
            payload = error_reply_payload("unknown_facet", f"{what!r} is not a known facet")
            payload.update(facet=what or "", as_of=self._ctx.clock.now())
            await self._ctx.bus.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload=payload)
            return
        try:
            data = await facet.get(message.payload.get("args") or {})
        except Exception as exc:  # noqa: BLE001 -- a facet error is a reply, never a crash
            payload = error_reply_payload("unavailable", repr(exc))
            payload.update(facet=what, as_of=self._ctx.clock.now())
            await self._ctx.bus.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload=payload)
            return
        payload = {"ok": True, "facet": what, "as_of": self._ctx.clock.now(), **data}
        await self._ctx.bus.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload=payload)

    async def _on_people_update(self, message: Message) -> None:
        """Link a handle to a person, unlink one, or set a role.

        The only write in this subsystem. It is a write because the
        alternative -- Sim inferring from "call me X" that a handle
        belongs to somebody -- is how an identity gets claimed by
        whoever says the right sentence. Guardian puts it at tier 3, so
        a person confirms each one, and what lands here has already
        been confirmed.
        """
        payload = message.payload or {}
        action = str(payload.get("action") or "")
        name = str(payload.get("name") or "").strip()
        identity = str(payload.get("identity") or "").strip()
        role = str(payload.get("role") or "").strip()
        try:
            if action == "link":
                if not name or not identity:
                    raise ValueError("a link needs both a name and an identity")
                person = self._people.link(name, identity, role=role)
                detail = f"{identity} is {person.name}"
            elif action == "unlink":
                person = self._people.unlink(identity)
                if person is None:
                    raise ValueError(f"nothing is linked to {identity!r}")
                detail = f"{identity} is nobody now"
            elif action == "set_role":
                person = self._people.set_role(name, role)
                if person is None:
                    raise ValueError(f"I do not know anybody called {name!r}")
                detail = f"{person.name} is {person.role}"
            elif action in ("grant", "revoke"):
                # What a person said yes to (stage 10). The grant arrives
                # here only after a person confirmed it (tier 3); the store
                # refuses a name that is not a permission.
                permission = str(payload.get("permission") or "").strip().lower()
                if not name or not permission:
                    raise ValueError(f"a {action} needs both a name and a permission")
                person = (self._people.grant if action == "grant" else self._people.revoke)(name, permission)
                if person is None:
                    raise ValueError(f"I do not know anybody called {name!r}")
                detail = (f"{person.name} said yes to {permission}" if action == "grant"
                          else f"{person.name} withdrew {permission}")
                if action == "revoke":
                    await self._on_permission_revoked(person.name, permission)
            elif action in ("add_interest", "remove_interest"):
                interest = str(payload.get("interest") or "").strip()
                if not name or not interest:
                    raise ValueError(f"{action} needs both a name and an interest")
                fn = self._people.add_interest if action == "add_interest" else self._people.remove_interest
                person = fn(name, interest)
                if person is None:
                    raise ValueError(f"I do not know anybody called {name!r}")
                detail = f"{person.name} cares about: {', '.join(person.interests) or 'nothing recorded'}"
            else:
                raise ValueError(f"{action!r} is not link, unlink, set_role, grant, revoke, "
                                 "add_interest or remove_interest")
        except Exception as exc:  # noqa: BLE001 -- a bad ask is a reply, never a crash
            await self._ctx.bus.reply(message, type=topics.WORLD_PEOPLE_UPDATE_REPLY,
                                      payload=error_reply_payload("refused", str(exc)))
            return
        await self._ctx.bus.reply(message, type=topics.WORLD_PEOPLE_UPDATE_REPLY,
                                  payload={"ok": True, "person": person.to_dict(), "detail": detail})

    async def _on_permission_revoked(self, name: str, permission: str) -> None:
        """Withdrawing a permission also drops what was kept under it
        (stage 10): a revoked `wellbeing_checkins` is not only a flag."""
        if permission == "wellbeing_checkins":
            self._wellbeing.forget(name)
            await self._announce_wellbeing()

    async def _on_provider_status(self, message: Message) -> None:
        """Record what is actually doing the thinking.

        `SelfModel.capabilities["providers"]` was declared when the self
        model was written and populated by nobody, and no section
        rendered it. So asked "which LLM are you using", Sim answered --
        honestly and correctly -- that it had no way to know: its own
        cognition backend was the one thing about itself it could not
        see. Live-caught by the creator, 2026-09-07.
        """
        p = message.payload
        name = p.get("provider")
        if not name:
            return
        providers = [x for x in self._model.capabilities.get("providers", []) if x.get("name") != name]
        providers.append({
            "name": name, "model": p.get("model", ""),
            "available": bool(p.get("available", False)), "selected": bool(p.get("selected", False)),
        })
        providers.sort(key=lambda x: (not x["selected"], x["name"]))
        self._model.capabilities["providers"] = providers

    async def _refresh_areas(self) -> None:
        """Re-read the code areas from the live capability map.

        They were read once at boot and baked into the model, while
        `capability_map` beside them has no cache and answers from the
        tree as it is. So the two disagreed the moment anything changed:
        an observer added a package mid-session and watched `self_map`
        report 19 subsystems including it, while the self summary --
        the protected block Cognition prepends to EVERY prompt --
        still said 18 and did not mention it (2026-09-10). The summary
        is what the model reads about itself when nobody asked a
        question, which makes stale worse there than anywhere.

        It goes through `_apply` like every other change to the model,
        rather than reaching into `capabilities` in place. Mutating it
        directly left the version at 1 while the rendered text changed
        underneath it -- two different `self.summary.reply`s both
        labelled `version: 1` -- and left the durable `SELF.md` on disk
        still listing an area that had been deleted (observer,
        2026-09-10). An empty scan is still ignored: a tree that reads
        as having no code at all is far likelier to be a transient than
        a system that has lost all of it."""
        areas = list(self._capability_map.areas())
        if not areas:
            return

        def _set_areas(model, now):
            if areas == model.capabilities.get("areas"):
                return model  # `_apply` treats an unchanged model as a no-op
            return replace(model, capabilities={**model.capabilities, "areas": areas}, updated_at=now)

        await self._apply(_set_areas, section="capabilities", reason="capability_map.rescan")

    async def _on_self_summary(self, message: Message) -> None:
        await self._refresh_areas()
        budget = message.payload.get("budget_tokens", 300)
        text, tokens = render_summary(self._model, budget)
        await self._ctx.bus.reply(message, type=topics.SELF_SUMMARY_REPLY,
                                   payload={"ok": True, "text": text, "version": self._model.version, "tokens": tokens})

    async def _on_self_gaps(self, message: Message) -> None:
        await self._refresh_areas()
        gaps, unexplored = compute_gaps(self._model, message.payload.get("k", 5))
        await self._ctx.bus.reply(message, type=topics.SELF_GAPS_REPLY,
                                   payload={"ok": True, "version": self._model.version, "gaps": gaps, "unexplored_areas": unexplored})

    async def _on_tool_registered(self, message: Message) -> None:
        self._tools.on_registered(message.payload.get("name", ""), message.payload)
        await self._sync_tools()

    async def _on_tool_unavailable(self, message: Message) -> None:
        self._tools.on_unavailable(message.payload.get("name", ""), message.payload.get("reason", ""))
        await self._sync_tools()

    async def _sync_tools(self) -> None:
        """`capabilities["tools"]` = the tools Execution has announced
        and not withdrawn. Declared in the model since Phase 0 and never
        written until 2026-09-19 (2026-09-18 evaluation): the Self Model
        could not say which tools Sim has while 98 were registered. Not
        folded during boot -- ~100 `tool.registered` arrive before
        `system.started`, and one version bump per tool would be noise;
        `_on_system_started` syncs once, and every change after that is
        its own entry."""
        if not self._booted:
            return
        names = self._tools.names()

        def _set_tools(model, now):
            if names == model.capabilities.get("tools"):
                return model
            return replace(model, capabilities={**model.capabilities, "tools": names}, updated_at=now)

        await self._apply(_set_tools, section="capabilities", reason="tool.registered")

    async def _on_tool_probed(self, message: Message) -> None:
        """The recovery half of `tool.unavailable`.

        Execution marks a tool unavailable when a free probe fails, and
        re-probes after an `install_package` -- so the very case the
        probes exist for (Sim installs what it was missing and carries
        on) would otherwise leave the Self Model saying the tool is
        still broken until the next boot. A passing probe puts every
        tool it covers back.
        """
        payload = message.payload
        if not payload.get("ok"):
            return
        for name in payload.get("tools") or []:
            self._tools.on_available(str(name))
        await self._sync_tools()

    async def _on_user_model_updated(self, message: Message) -> None:
        p = message.payload
        self._user_profile.on_updated(p.get("facet", ""), p.get("value"), p.get("confidence", 0.0))

    # -- dynamic Self Model: competence, calibration, limitations, change history --------------

    async def _on_competence_updated(self, message: Message) -> None:
        p = message.payload
        await self._record(
            "competence",
            {"task_type": p["task_type"], "success_rate": p.get("success_rate"),
             "samples": p.get("samples"), "calibration": p.get("calibration")},
            section="competence", reason=f"learn.competence.updated: {p['task_type']}",
        )

    async def _on_calibration_updated(self, message: Message) -> None:
        p = message.payload
        await self._record(
            "competence",
            {"task_type": p["task_type"], "stated_confidence": p.get("stated_confidence"),
             "empirical_accuracy": p.get("empirical_accuracy")},
            section="competence", reason=f"reflect.calibration.updated: {p['task_type']}",
        )

    async def _on_self_observation(self, message: Message) -> None:
        p = message.payload
        if p.get("kind") != "limitation":
            return  # restart/change/success/failure are handled by their real producers directly
        await self._record(
            "limitation", {"text": p["detail"], "evidence": [p["ref"]] if p.get("ref") else []},
            section="limitations", reason="self.observation{kind:limitation}",
        )

    async def _on_self_patch_applied(self, message: Message) -> None:
        p = message.payload
        await self._record(
            "change", {"kind": "self_patch", "subject": p["subject"], "commit": p.get("commit"),
                       "tests": p.get("tests"),
                       "summary": p.get("reason") or f"self-patch applied: {p['subject']}"},
            section="change_history", reason=f"learn.self_patch.applied: {p['subject']}")
        await self._record(
            "mitigate", {"subject": p["subject"]},
            section="limitations", reason=f"learn.self_patch.applied: {p['subject']}")

    async def _on_self_patch_reverted(self, message: Message) -> None:
        p = message.payload
        await self._record(
            "change", {"kind": "self_patch_reverted", "subject": p["subject"], "commit": p.get("commit"),
                       "summary": p.get("reason") or f"self-patch reverted: {p['subject']}"},
            section="change_history", reason=f"learn.self_patch.reverted: {p['subject']}",
        )

    async def _on_skill_acquired(self, message: Message) -> None:
        p = message.payload
        await self._record("skill", {"name": p["name"], "tests": p.get("tests", 0)},
                           section="capabilities", reason=f"learn.skill.acquired: {p['name']}")
        await self._record(
            "change", {"kind": "skill_acquired", "subject": p["name"],
                       "summary": f"skill acquired: {p['name']} ({p.get('tests', 0)} tests)"},
            section="change_history", reason=f"learn.skill.acquired: {p['name']}")

    async def _on_system_started(self, message: Message) -> None:
        self._restarts += 1
        self._booted = True
        await self._sync_tools()
        await self._apply(
            lambda m, now: bump_restarts(m, restarts=self._restarts, updated_at=now),
            section="continuity", reason=f"system.started (mode={message.payload.get('mode', '?')})",
        )

    # -- goals: task.* -> goals (06-worldmodel.md section 5) ------------------------------------
    # Live-caught (post-cutover review): nothing here consumed task events,
    # so `goals.pending_tasks` was a constant 0 and a chat "show your tasks"
    # right after `propose` had created one was answered "queue is empty".

    async def _on_task_created(self, message: Message) -> None:
        p = message.payload
        await self._apply(
            lambda m, now: update_goals(
                m, updated_at=now, task_id=p["task_id"], kind=p.get("kind", ""), status="pending",
                description=p.get("description", ""), area=_area_of(p.get("subject")),
            ),
            section="goals", reason=f"task.created: {p['task_id']}",
        )

    async def _on_task_finished(self, message: Message) -> None:
        p = message.payload
        status = "completed" if message.type == topics.TASK_COMPLETED else "failed"
        await self._apply(
            lambda m, now: update_goals(m, updated_at=now, task_id=p["task_id"], status=status),
            section="goals", reason=f"task.{status}: {p['task_id']}",
        )

    async def _on_task_blocked(self, message: Message) -> None:
        p = message.payload
        await self._apply(
            lambda m, now: update_goals(m, updated_at=now, task_id=p["task_id"], status="blocked"),
            section="goals", reason=f"task.blocked: {p['task_id']}",
        )

    # -- helpers --------------------------------------------------------------------------------

    async def _record(self, rule: str, args: dict, *, section: str, reason: str) -> None:
        """A change to what Sim knows about ITSELF: applied, and written
        down so the next boot has it too.

        `_apply` is for the sections re-derived at every start (the
        tools that registered, the tasks in the queue). This is for the
        ones that are history -- competence, limitations, the patches
        landed, the skills acquired -- which a restart used to drop on
        the floor. `SELF_CHANGES` is the stream and `selfmodel.replay`
        the fold; the module docstring promised this and left every
        mutator a pure function so it could be added without a
        redesign (stage 6 item 1).

        The event is written only when the mutation actually changed
        something, so a fuzzy-duplicate limitation does not grow the
        stream.
        """
        assert self._ctx is not None and self._model is not None
        before = self._model
        await self._apply(lambda m, now: replay(m, rule, args, now=now), section=section, reason=reason)
        if self._model is before:
            return
        event = Event(stream=SELF_CHANGES, type=rule, ts=self._ctx.clock.now(),
                      trace_id=SELF_CHANGES, causation_id=None,
                      payload={"rule": rule, "args": dict(args), "section": section, "reason": reason})
        try:
            await self._ctx.ledger.append(SELF_CHANGES, event)
        except Exception as exc:  # noqa: BLE001 -- a model that cannot be written down is still a model
            self._ctx.logger.warning("worldmodel.self_change_unwritten", rule=rule, error=repr(exc))

    async def _replay_self(self, ctx: Context) -> None:
        """Fold `self:changes` onto the static model at boot.

        Everything else in this package rebuilds its view from the log
        already; the Self Model was the one that said it did and did
        not. A bad stream degrades to the static model rather than
        failing the boot -- Sim starting without its history is worse
        than Sim not starting only in the second case.
        """
        try:
            events = await ctx.ledger.read(SELF_CHANGES)
        except Exception as exc:  # noqa: BLE001
            ctx.logger.warning("worldmodel.self_replay_failed", error=repr(exc))
            return
        model, applied = self._model, 0
        for event in events:
            payload = event.payload or {}
            rule = str(payload.get("rule") or event.type or "")
            after = replay(model, rule, dict(payload.get("args") or {}), now=float(event.ts or 0.0))
            if after is not model:
                applied += 1
            model = after
        if applied:
            self._model = replace(model, version=self._model.version + applied)
        ctx.logger.info("worldmodel.self_replayed", events=len(events), applied=applied,
                        version=self._model.version)

    async def _apply(self, mutate, *, section: str, reason: str) -> None:
        """Applies one mutator, and if it actually changed the model,
        bumps the version, re-renders `SELF.md`, and emits
        `self.model.updated` (06-worldmodel.md section 5: "every applied
        rule appends `section.updated`... `self.model.updated` is emitted
        once per version"). A no-op mutation (e.g. a fuzzy-duplicate
        limitation) never bumps the version or touches disk."""
        assert self._ctx is not None and self._model is not None
        now = self._ctx.clock.now()
        new_model = mutate(self._model, now)
        if new_model is self._model:
            return
        self._model = replace(new_model, version=self._model.version + 1)
        try:
            (self._ctx.data_dir / "self").mkdir(parents=True, exist_ok=True)
            (self._ctx.data_dir / "self" / "SELF.md").write_text(render_full_markdown(self._model))
        except OSError as exc:
            self._ctx.logger.warning("worldmodel.self_render_failed", error=repr(exc))
        await self._ctx.bus.publish(Message.new(
            topics.SELF_MODEL_UPDATED, source=self._ctx.source,
            payload={"version": self._model.version, "changed_sections": [section], "reason": reason},
        ))


def _area_of(subject: str | None) -> str | None:
    """`src/memory/store.py` -> `memory`; `simorgh/cognition/x.py` ->
    `cognition`; a bare name -> itself; nothing -> None. Feeds
    `goals.recent_focus_areas` (06-worldmodel.md section 4)."""
    if not subject:
        return None
    parts = [p for p in str(subject).replace("\\", "/").split("/") if p]
    if len(parts) >= 2 and parts[0] in ("src", "simorgh"):
        return parts[1]
    return parts[0] if parts else None


__all__ = ["Service", "NAME", "VERSION"]
