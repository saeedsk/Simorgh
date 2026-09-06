"""World Model as a `Subsystem` -- env facets (real, this session) plus a
static Self Model (identity only; competence/limitations/etc. are Phase
3 -- see `selfmodel.py`'s own docstring). Layer 1 (registry.py).
"""

from __future__ import annotations

import time

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context, Health
from simorgh.contracts.registry import error_reply_payload

from .config import Config
from .facets.capability_map import CapabilityMapFacet
from .facets.file_index import FileIndexFacet
from .facets.git_state import GitStateFacet
from .facets.registry_facets import ToolsFacet, UserProfileFacet
from .selfmodel import build_static_model, compute_gaps, render_full_markdown, render_summary

NAME = "worldmodel"
VERSION = "0.1.0"


class Service:
    name = NAME
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.WORLD_ENV_QUERY, topics.SELF_SUMMARY, topics.SELF_GAPS,
        topics.TOOL_REGISTERED, topics.TOOL_UNAVAILABLE, topics.PERSONA_USER_MODEL_UPDATED,
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


__all__ = ["Service", "NAME", "VERSION"]
