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
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context, Health
from simorgh.contracts.registry import error_reply_payload

from .config import Config
from .facets.capability_map import CapabilityMapFacet
from .facets.file_index import FileIndexFacet
from .facets.git_state import GitStateFacet
from .facets.registry_facets import ToolsFacet, UserProfileFacet
from .selfmodel import (
    add_change,
    add_limitation,
    add_skill,
    bump_restarts,
    build_static_model,
    compute_gaps,
    mitigate_limitations,
    render_full_markdown,
    render_summary,
    update_competence,
)

NAME = "worldmodel"
VERSION = "0.1.0"


class Service:
    name = NAME
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.WORLD_ENV_QUERY, topics.SELF_SUMMARY, topics.SELF_GAPS,
        topics.TOOL_REGISTERED, topics.TOOL_UNAVAILABLE, topics.PERSONA_USER_MODEL_UPDATED,
        topics.LEARN_COMPETENCE_UPDATED, topics.REFLECT_CALIBRATION_UPDATED, topics.SELF_OBSERVATION,
        topics.LEARN_SELF_PATCH_APPLIED, topics.LEARN_SELF_PATCH_REVERTED, topics.LEARN_SKILL_ACQUIRED,
        topics.SYSTEM_STARTED,
    )
    produces: tuple[str, ...] = (
        topics.WORLD_ENV_QUERY_REPLY, topics.SELF_SUMMARY_REPLY, topics.SELF_GAPS_REPLY,
        topics.WORLD_ENV_OBSERVED, topics.SELF_MODEL_UPDATED, topics.SYSTEM_HEALTH,
    )

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self._ctx: Context | None = None
        self._subs: list = []
        self._restarts = 0
        self._model = None
        self._started_at = 0.0

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        self._started_at = ctx.clock.now()
        self._capability_map = CapabilityMapFacet(self.config.repo_root)
        self._file_index = FileIndexFacet(self.config.repo_root, max_files=self.config.file_index_max_files)
        self._git_state = GitStateFacet(self.config.repo_root)
        self._tools = ToolsFacet()
        self._user_profile = UserProfileFacet()
        self._facets = {
            "capability_map": self._capability_map, "file_index": self._file_index,
            "git_state": self._git_state, "tools": self._tools, "user_profile": self._user_profile,
        }
        self._model = build_static_model(
            soul_path=self.config.resolved_soul_path(), clock_now=self._started_at,
            areas=self._capability_map.areas(), continuity={"restarts": self._restarts},
        )
        try:
            (ctx.data_dir / "self").mkdir(parents=True, exist_ok=True)
            (ctx.data_dir / "self" / "SELF.md").write_text(render_full_markdown(self._model))
        except OSError as exc:
            ctx.logger.warning("worldmodel.self_render_failed", error=repr(exc))

        self._subs = [
            await ctx.bus.subscribe(topics.WORLD_ENV_QUERY, self._on_env_query),
            await ctx.bus.subscribe(topics.SELF_SUMMARY, self._on_self_summary),
            await ctx.bus.subscribe(topics.SELF_GAPS, self._on_self_gaps),
            await ctx.bus.subscribe(topics.TOOL_REGISTERED, self._on_tool_registered),
            await ctx.bus.subscribe(topics.TOOL_UNAVAILABLE, self._on_tool_unavailable),
            await ctx.bus.subscribe(topics.PERSONA_USER_MODEL_UPDATED, self._on_user_model_updated),
            await ctx.bus.subscribe(topics.LEARN_COMPETENCE_UPDATED, self._on_competence_updated),
            await ctx.bus.subscribe(topics.REFLECT_CALIBRATION_UPDATED, self._on_calibration_updated),
            await ctx.bus.subscribe(topics.SELF_OBSERVATION, self._on_self_observation),
            await ctx.bus.subscribe(topics.LEARN_SELF_PATCH_APPLIED, self._on_self_patch_applied),
            await ctx.bus.subscribe(topics.LEARN_SELF_PATCH_REVERTED, self._on_self_patch_reverted),
            await ctx.bus.subscribe(topics.LEARN_SKILL_ACQUIRED, self._on_skill_acquired),
            await ctx.bus.subscribe(topics.SYSTEM_STARTED, self._on_system_started),
        ]
        ctx.logger.info("worldmodel.started", areas=len(self._capability_map.areas()))

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

    async def _on_self_summary(self, message: Message) -> None:
        budget = message.payload.get("budget_tokens", 300)
        text, tokens = render_summary(self._model, budget)
        await self._ctx.bus.reply(message, type=topics.SELF_SUMMARY_REPLY,
                                   payload={"ok": True, "text": text, "version": self._model.version, "tokens": tokens})

    async def _on_self_gaps(self, message: Message) -> None:
        gaps, unexplored = compute_gaps(self._model, message.payload.get("k", 5))
        await self._ctx.bus.reply(message, type=topics.SELF_GAPS_REPLY,
                                   payload={"ok": True, "version": self._model.version, "gaps": gaps, "unexplored_areas": unexplored})

    async def _on_tool_registered(self, message: Message) -> None:
        self._tools.on_registered(message.payload.get("name", ""), message.payload)

    async def _on_tool_unavailable(self, message: Message) -> None:
        self._tools.on_unavailable(message.payload.get("name", ""), message.payload.get("reason", ""))

    async def _on_user_model_updated(self, message: Message) -> None:
        p = message.payload
        self._user_profile.on_updated(p.get("facet", ""), p.get("value"), p.get("confidence", 0.0))

    # -- dynamic Self Model: competence, calibration, limitations, change history --------------

    async def _on_competence_updated(self, message: Message) -> None:
        p = message.payload
        await self._apply(
            lambda m, now: update_competence(
                m, p["task_type"], updated_at=now, success_rate=p.get("success_rate"),
                samples=p.get("samples"), calibration=p.get("calibration"),
            ),
            section="competence", reason=f"learn.competence.updated: {p['task_type']}",
        )

    async def _on_calibration_updated(self, message: Message) -> None:
        p = message.payload
        await self._apply(
            lambda m, now: update_competence(
                m, p["task_type"], updated_at=now,
                stated_confidence=p.get("stated_confidence"), empirical_accuracy=p.get("empirical_accuracy"),
            ),
            section="competence", reason=f"reflect.calibration.updated: {p['task_type']}",
        )

    async def _on_self_observation(self, message: Message) -> None:
        p = message.payload
        if p.get("kind") != "limitation":
            return  # restart/change/success/failure are handled by their real producers directly
        await self._apply(
            lambda m, now: add_limitation(m, text=p["detail"], evidence=[p["ref"]] if p.get("ref") else [], since=now, updated_at=now),
            section="limitations", reason="self.observation{kind:limitation}",
        )

    async def _on_self_patch_applied(self, message: Message) -> None:
        p = message.payload
        def _mutate(m, now):
            m = add_change(
                m, ts=now, kind="self_patch", updated_at=now, subject=p["subject"], commit=p.get("commit"),
                tests=p.get("tests"), summary=p.get("reason") or f"self-patch applied: {p['subject']}",
            )
            return mitigate_limitations(m, subject=p["subject"], updated_at=now)
        await self._apply(_mutate, section="change_history", reason=f"learn.self_patch.applied: {p['subject']}")

    async def _on_self_patch_reverted(self, message: Message) -> None:
        p = message.payload
        await self._apply(
            lambda m, now: add_change(
                m, ts=now, kind="self_patch_reverted", updated_at=now, subject=p["subject"], commit=p.get("commit"),
                summary=p.get("reason") or f"self-patch reverted: {p['subject']}",
            ),
            section="change_history", reason=f"learn.self_patch.reverted: {p['subject']}",
        )

    async def _on_skill_acquired(self, message: Message) -> None:
        p = message.payload
        def _mutate(m, now):
            m = add_skill(m, name=p["name"], tests=p.get("tests", 0), updated_at=now)
            return add_change(m, ts=now, kind="skill_acquired", updated_at=now, subject=p["name"],
                               summary=f"skill acquired: {p['name']} ({p.get('tests', 0)} tests)")
        await self._apply(_mutate, section="capabilities", reason=f"learn.skill.acquired: {p['name']}")

    async def _on_system_started(self, message: Message) -> None:
        self._restarts += 1
        await self._apply(
            lambda m, now: bump_restarts(m, restarts=self._restarts, updated_at=now),
            section="continuity", reason=f"system.started (mode={message.payload.get('mode', '?')})",
        )

    # -- helpers --------------------------------------------------------------------------------

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


__all__ = ["Service", "NAME", "VERSION"]
