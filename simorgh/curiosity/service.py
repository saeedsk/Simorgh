"""`Service`: wires drives, sampling, idea/project proposal, interests,
and sharing into the real `Subsystem` protocol (spec section 5). One
exploration tick at a time -- a tick still awaiting Cognition when the
next `system.tick.idle` arrives is skipped and recorded, never re-entered
or queued, so ticks can never pile up behind a slow provider.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import time
import uuid
from dataclasses import dataclass

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event
from simorgh.contracts.protocols import Context, Health

from .api import Area, DriveContext, Gap, Interest, Target
from .config import Config
from .drives import DriveEngine
from .idea import TargetedIdeaProposer
from .interests import InterestService, is_feed_url, parse_feed_items
from .projectproposal import OpenEndedProjectProposer
from .projections import ActiveProject, AreaStaleness, BacklogCounter, RecentCandidates
from .sampler import DriveWeightedSampler

_CONSUMES = (
    topics.SYSTEM_TICK_IDLE, topics.SYSTEM_TICK_SLEEP, topics.SYSTEM_STATE_CHANGED,
    topics.TASK_CREATED, topics.TASK_COMPLETED, topics.TASK_FAILED, topics.TASK_BLOCKED,
    topics.PROJECT_COMPLETED, topics.PROJECT_FAILED,
    topics.LEARN_COMPETENCE_UPDATED, topics.LEARN_SELF_PATCH_APPLIED, topics.LEARN_SKILL_ACQUIRED,
    topics.REFLECT_CALIBRATION_UPDATED, topics.COGNITION_PROVIDER_STATUS, topics.PERSONA_STATE_CHANGED,
    topics.ACTION_RESULT, topics.ACTION_DENIED, topics.PERCEPT_TEXT_RECEIVED,
    topics.CURIOSITY_DISCOVER_REQUEST, topics.CURIOSITY_SHARE_REQUEST, topics.CURIOSITY_INTEREST_ADD,
    topics.CURIOSITY_INTEREST_LIST_REQUEST, topics.CURIOSITY_INTEREST_FOLLOW_UP_REQUEST,
)
_PRODUCES = (
    topics.CURIOSITY_CANDIDATE, topics.INTENT_GOAL_STATED, topics.CURIOSITY_INTEREST_UPDATED,
    topics.CURIOSITY_SHARE_PROPOSED, topics.ACTION_PROPOSED, topics.MEMORY_STORE,
    topics.CURIOSITY_DISCOVER_REPLY, topics.CURIOSITY_SHARE_REPLY,
    topics.CURIOSITY_INTEREST_LIST_REPLY, topics.CURIOSITY_INTEREST_FOLLOW_UP_REPLY,
)

_TICKS_STREAM = "curiosity:ticks"
_CANDIDATES_STREAM = "curiosity:candidates"
_INTERESTS_STREAM = "curiosity:interests"
_SHARES_STREAM = "curiosity:shares"
_PROJECTS_STREAM = "curiosity:projects"


@dataclass
class _BudgetState:
    worst_remaining: float | None = None
    any_free: bool = False


class Service:
    name = "curiosity"
    version = "0.1.0"
    consumes = _CONSUMES
    produces = _PRODUCES

    def __init__(self, *, config: Config | None = None, seed: int | None = None) -> None:
        self._config = config or Config()
        self._engine = DriveEngine(self._config)
        self._sampler = DriveWeightedSampler(self._engine)
        self._idea_proposer = TargetedIdeaProposer()
        self._project_proposer = OpenEndedProjectProposer()
        self._interests = InterestService(follow_up_cooldown_seconds=self._config.interest_follow_up_cooldown_seconds)
        from .sharing import ShareScheduler

        self._sharing = ShareScheduler(
            growth_cooldown_seconds=self._config.share_growth_cooldown_seconds,
            news_cooldown_seconds=self._config.share_news_cooldown_seconds,
        )
        self._backlog = BacklogCounter()
        self._staleness = AreaStaleness()
        self._active_project = ActiveProject(self._config.active_project_confirm_timeout)
        self._recent = RecentCandidates(maxlen=self._config.recent_subjects)
        self._rng = random.Random(seed)
        self._tick_lock = asyncio.Lock()
        self._state = "running"
        self._mood = {"valence": 0.0, "arousal": 0.0}
        self._budget = _BudgetState()
        self._pending_web_fetches: dict[str, str] = {}  # action_id -> topic
        self._areas_cache: tuple[Area, ...] = ()
        self._subs: list = []
        self._ctx: Context | None = None
        self._last_tick_record: dict = {}
        self._cognition_attempted = False

    # -- Subsystem protocol ---------------------------------------------------------------
    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        self._bus = ctx.bus
        self._ledger = ctx.ledger
        self._clock = ctx.clock
        if not self._interests.list_interests():
            for url, label in self._config.interest_default_topics:
                self._interests.note(url, why=f"seeded: {label}")
        handlers = {
            topics.SYSTEM_TICK_IDLE: self._on_tick_idle,
            topics.SYSTEM_TICK_SLEEP: self._on_tick_sleep,
            topics.SYSTEM_STATE_CHANGED: self._on_state_changed,
            topics.TASK_CREATED: self._on_task_created,
            topics.TASK_COMPLETED: self._on_task_completed,
            topics.TASK_FAILED: self._on_task_failed,
            topics.TASK_BLOCKED: self._on_task_blocked,
            topics.PROJECT_COMPLETED: self._on_project_finished,
            topics.PROJECT_FAILED: self._on_project_finished,
            topics.COGNITION_PROVIDER_STATUS: self._on_provider_status,
            topics.PERSONA_STATE_CHANGED: self._on_persona_state,
            topics.ACTION_RESULT: self._on_action_result,
            topics.ACTION_DENIED: self._on_action_denied,
            topics.PERCEPT_TEXT_RECEIVED: self._on_percept,
            topics.LEARN_SELF_PATCH_APPLIED: self._on_growth_event,
            topics.LEARN_SKILL_ACQUIRED: self._on_growth_event,
            topics.CURIOSITY_DISCOVER_REQUEST: self._on_discover_request,
            topics.CURIOSITY_SHARE_REQUEST: self._on_share_request,
            topics.CURIOSITY_INTEREST_ADD: self._on_interest_add,
            topics.CURIOSITY_INTEREST_LIST_REQUEST: self._on_interest_list_request,
            topics.CURIOSITY_INTEREST_FOLLOW_UP_REQUEST: self._on_interest_follow_up_request,
        }
        for topic, handler in handlers.items():
            self._subs.append(await self._bus.subscribe(topic, handler))

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs.clear()
        if self._tick_lock.locked():
            await self._append(_TICKS_STREAM, "tick", {"ts": self._now(), "skipped_reason": "shutdown"})

    async def health(self) -> Health:
        return Health.ok()

    # -- bookkeeping handlers ---------------------------------------------------------------
    def _now(self) -> float:
        return self._clock.now() if self._ctx is not None else time.time()

    async def _on_state_changed(self, message) -> None:
        self._state = message.payload["state"]

    async def _on_task_created(self, message) -> None:
        self._backlog.on_created(message.payload["task_id"])
        if message.payload.get("kind") == "project":
            self._active_project.confirm()

    async def _on_task_completed(self, message) -> None:
        self._backlog.on_completed(message.payload["task_id"])

    async def _on_task_failed(self, message) -> None:
        self._backlog.on_failed(message.payload["task_id"], terminal=message.payload.get("terminal", True))

    async def _on_task_blocked(self, message) -> None:
        self._backlog.on_blocked(
            message.payload["task_id"], retry_after=message.payload.get("retry_after"), now=self._now(),
        )

    async def _on_project_finished(self, message) -> None:
        self._active_project.on_project_finished()

    async def _on_provider_status(self, message) -> None:
        budget = message.payload.get("budget") or {}
        remaining = budget.get("remaining_fraction")
        free = bool(budget.get("free", False))
        if free:
            self._budget.any_free = True
        if remaining is not None and not free:
            self._budget.worst_remaining = remaining if self._budget.worst_remaining is None else min(self._budget.worst_remaining, remaining)

    async def _on_persona_state(self, message) -> None:
        self._mood = {"valence": message.payload["valence"], "arousal": message.payload["arousal"]}

    async def _on_action_result(self, message) -> None:
        action_id = message.payload["action_id"]
        topic = self._pending_web_fetches.pop(action_id, None)
        if topic is None:
            return
        ok = message.payload.get("ok", False)
        items = []
        if ok:
            body = message.payload.get("stdout_preview", "")
            items = parse_feed_items(body, source=topic, limit=self._config.interest_max_items_per_follow_up)
        interest = self._interests.record_follow_up(topic, items, now=self._now(), denied=not ok)
        await self._append(_INTERESTS_STREAM, "followed_up", {"topic": topic, "score": interest.score, "items": len(items)})
        await self._publish(topics.CURIOSITY_INTEREST_UPDATED, {
            "topic": topic, "last_followed_up": interest.last_followed_up or self._now(), "items_found": len(items),
        })
        for item in items:
            await self._publish(topics.MEMORY_STORE, {
                "kind": "semantic", "content": f"{item.title} -- {item.summary}",
                "tags": ["news", topic], "source_ref": f"feed:{topic}",
            })
        if items:
            self._sharing.offer_news(ref=f"feed:{topic}", summary=items[0].title, at=self._now())

    async def _on_action_denied(self, message) -> None:
        action_id = message.payload["action_id"]
        topic = self._pending_web_fetches.pop(action_id, None)
        if topic is None:
            return
        interest = self._interests.record_follow_up(topic, [], now=self._now(), denied=True)
        await self._append(_INTERESTS_STREAM, "followed_up", {"topic": topic, "score": interest.score, "items": 0, "denied": True})
        await self._publish(topics.CURIOSITY_INTEREST_UPDATED, {
            "topic": topic, "last_followed_up": interest.last_followed_up or self._now(), "items_found": 0,
        })

    async def _on_growth_event(self, message) -> None:
        ref = f"{message.type}:{message.id}"
        summary = message.payload.get("subject") or message.payload.get("name") or message.type
        self._sharing.offer_growth(ref=ref, summary=str(summary), at=self._now())

    async def _on_percept(self, message) -> None:
        if message.payload.get("channel") != "command":
            return
        command = (message.payload.get("command") or "").strip()
        if command.startswith("interest "):
            await self._handle_interest_command(command[len("interest "):].strip())
        elif command in ("interests", "curious"):
            await self._handle_curious_command()
        elif command == "news":
            await self._offer_share("news")
        elif command == "growth":
            await self._offer_share("growth")

    async def _handle_interest_command(self, topic: str) -> None:
        if not topic:
            return
        self._interests.note(topic)
        await self._append(_INTERESTS_STREAM, "noted", {"topic": topic})

    async def _handle_curious_command(self) -> None:
        await self._follow_up_least_recent()

    async def _offer_share(self, kind: str) -> None:
        decision = self._sharing.maybe_share(self._now())
        if decision is not None and decision.kind == kind:
            await self._append(_SHARES_STREAM, "proposed", {"kind": decision.kind, "content_ref": decision.content_ref})
            await self._publish(topics.CURIOSITY_SHARE_PROPOSED, {"kind": decision.kind, "content_ref": decision.content_ref})

    # -- request/reply handlers -------------------------------------------------------------
    async def _on_discover_request(self, message) -> None:
        created = await self._run_tick(force=True)
        await self._bus.reply(message, type=topics.CURIOSITY_DISCOVER_REPLY, payload={"created": created})

    async def _on_share_request(self, message) -> None:
        kind = message.payload["kind"]
        decision = self._sharing.maybe_share(self._now())
        shared = decision is not None and decision.kind == kind
        if shared:
            await self._append(_SHARES_STREAM, "proposed", {"kind": decision.kind, "content_ref": decision.content_ref})
            await self._publish(topics.CURIOSITY_SHARE_PROPOSED, {"kind": decision.kind, "content_ref": decision.content_ref})
        await self._bus.reply(message, type=topics.CURIOSITY_SHARE_REPLY, payload={
            "shared": shared, **({"content_ref": decision.content_ref} if shared else {}),
        })

    async def _on_interest_add(self, message) -> None:
        topic = message.payload.get("topic") or message.payload.get("feed_url")
        if topic:
            self._interests.note(topic)
            await self._append(_INTERESTS_STREAM, "noted", {"topic": topic})

    async def _on_interest_list_request(self, message) -> None:
        interests = [
            {"topic": i.topic, "score": i.score, "last_followed_up": i.last_followed_up} for i in self._interests.list_interests()
        ]
        await self._bus.reply(message, type=topics.CURIOSITY_INTEREST_LIST_REPLY, payload={"interests": interests})

    async def _on_interest_follow_up_request(self, message) -> None:
        topic = message.payload.get("topic")
        interest = None
        if topic:
            self._interests.note(topic)
            interest = self._interests.least_recently_followed(now=self._now())
        found = await self._follow_up_least_recent(topic=topic) if topic else await self._follow_up_least_recent()
        await self._bus.reply(message, type=topics.CURIOSITY_INTEREST_FOLLOW_UP_REPLY, payload={"items_found": found})

    async def _follow_up_least_recent(self, topic: str | None = None) -> int:
        target = self._interests.least_recently_followed(now=self._now()) if topic is None else Interest(topic=topic, why="", created_at=self._now())
        if target is None or not is_feed_url(target.topic):
            return 0
        action_id = f"web_fetch-{hashlib.sha256(target.topic.encode()).hexdigest()[:12]}-{int(self._now())}"
        self._pending_web_fetches[action_id] = target.topic
        await self._publish(topics.ACTION_PROPOSED, {
            "action_id": action_id, "tool": "web_fetch", "args": {"url": target.topic},
            "scope": {"paths": [], "network": True}, "reversibility": "read_only",
            "rationale": f"following up on tracked interest {target.topic!r}", "proposed_by": "curiosity",
        })
        return 0  # async: the count arrives later via action.result -> curiosity.interest.updated

    # -- ticks ------------------------------------------------------------------------------
    async def _on_tick_idle(self, message) -> None:
        await self._run_tick(idle_seconds=message.payload["idle_seconds"])
        decision = self._sharing.maybe_share(self._now())
        if decision is not None:
            await self._append(_SHARES_STREAM, "proposed", {"kind": decision.kind, "content_ref": decision.content_ref})
            await self._publish(topics.CURIOSITY_SHARE_PROPOSED, {"kind": decision.kind, "content_ref": decision.content_ref})

    async def _on_tick_sleep(self, message) -> None:
        self._interests.decay(self._now(), elapsed_days=message.payload["window_seconds"] / 86400.0)

    async def _run_tick(self, idle_seconds: float = 0.0, force: bool = False) -> list[str]:
        if self._tick_lock.locked():
            await self._record_tick(skipped_reason="already_running")
            return []
        async with self._tick_lock:
            return await self._run_tick_locked(idle_seconds, force=force)

    async def _run_tick_locked(self, idle_seconds: float, *, force: bool) -> list[str]:
        self._cognition_attempted = False
        if not force and self._state in ("paused", "stopping"):
            await self._record_tick(skipped_reason="paused")
            return []
        if not force and self._backlog.effective_count > 0:
            await self._record_tick(skipped_reason="backlog_nonempty")
            return []
        boredom = min(1.0, idle_seconds / self._config.boredom_after_seconds) if self._config.boredom_after_seconds > 0 else 0.0
        rate = self._exploration_rate()
        if rate <= 0.0 and not self._budget.any_free and not force:
            await self._record_tick(skipped_reason="budget")
            return []

        created: list[str] = []
        if not self._active_project.is_active(self._now()) and self._rng.random() < self._config.project_chance * max(rate, 0.0):
            # `_cognition_attempted` is OR-accumulated across every `_think`
            # call this tick, never reset by a later call (v1 milestone 96:
            # a rare project attempt followed by the per-target fallback
            # must not let the fallback's own outcome silently overwrite
            # whether cognition was actually invoked by the *first* call).
            goal = await self._try_project_proposal()
            if goal is not None:
                await self._record_tick(picked=[], proposed=[], project=goal, cognition_attempted=self._cognition_attempted)
                return created

        ctx = await self._build_drive_context(boredom)
        if ctx is None:
            await self._record_tick(skipped_reason="no_world_model", cognition_attempted=self._cognition_attempted)
            return created

        picked: list[str] = []
        if force or rate >= 1.0 or self._budget.any_free:
            count = self._config.candidates_per_tick
        else:
            count = round(self._config.candidates_per_tick * rate)
        for _ in range(max(0, count)):
            temperature = self._engine.temperature(self._mood["arousal"])
            recent = self._recent.recent_subjects(self._config.recent_subjects)
            target = self._sampler.pick(ctx, recent, rng=self._rng, temperature=temperature)
            if target is None:
                break
            picked.append(target.subject)
            preview = await self._preview(target)
            idea = await self._idea_proposer.propose(target, preview, self._think)
            if idea is None or self._recent.similar(idea.description):
                continue
            candidate_id = self._candidate_id(target.subject, idea.description)
            await self._emit_candidate(candidate_id, target, idea)
            self._recent.add(target.subject, idea.description)
            created.append(candidate_id)

        await self._record_tick(
            picked=picked, proposed=created, scores=self._sampler.score_table(ctx),
            cognition_attempted=self._cognition_attempted,
        )
        return created

    def _exploration_rate(self) -> float:
        remaining = self._budget.worst_remaining
        if remaining is None:
            return 1.0
        if remaining <= self._config.budget_stop_below_remaining:
            return 0.0
        if remaining <= self._config.budget_backoff_below_remaining:
            return 0.5
        return 1.0

    async def _build_drive_context(self, boredom: float) -> DriveContext | None:
        reply = await self._bus.request_or_error(
            self._bus.new(topics.WORLD_ENV_QUERY, {"what": "capability_map"}), timeout=self._config.world_query_timeout,
        )
        if reply.payload.get("ok") is False:
            if self._areas_cache:
                areas = self._areas_cache
            else:
                return None
        else:
            names = reply.payload.get("areas") or []
            modules_by_area = reply.payload.get("modules_by_area") or {}
            areas = tuple(Area(name=n, modules=tuple(modules_by_area.get(n, []))) for n in names)
            self._areas_cache = areas
        if not areas:
            return None

        gaps_reply = await self._bus.request_or_error(
            self._bus.new(topics.SELF_GAPS, {"k": 10}), timeout=self._config.world_query_timeout,
        )
        gaps: tuple[Gap, ...] = ()
        if gaps_reply.payload.get("ok") is not False:
            gaps = tuple(
                Gap(competence=g["competence"], task_type=g["task_type"], score=g["score"], samples=g["samples"])
                for g in gaps_reply.payload.get("gaps", [])
            )

        now = self._now()
        staleness_by_area = self._staleness.snapshot([a.name for a in areas], now)
        return DriveContext(
            areas=areas, gaps=gaps, interests=self._interests.topics_lower(), boredom=boredom,
            staleness_by_area=staleness_by_area, staleness_horizon=self._config.staleness_horizon_seconds,
        )

    async def _preview(self, target: Target) -> str:
        reply = await self._bus.request_or_error(
            self._bus.new(topics.WORLD_ENV_QUERY, {"what": "file_index", "args": {"path": target.subject, "max_chars": 4000}}),
            timeout=self._config.world_query_timeout,
        )
        if reply.payload.get("ok") is False:
            return ""
        return str(reply.payload.get("content", "") or reply.payload.get("preview", ""))

    async def _try_project_proposal(self) -> str | None:
        files_reply = await self._bus.request_or_error(
            self._bus.new(topics.WORLD_ENV_QUERY, {"what": "file_index", "args": {}}),
            timeout=self._config.world_query_timeout,
        )
        files: list[str] = []
        if files_reply.payload.get("ok") is not False:
            files = [f["path"] for f in files_reply.payload.get("files", []) if "path" in f]
        goal = await self._project_proposer.propose(files, self._think)
        if goal is None:
            await self._append(_PROJECTS_STREAM, "skipped", {"reason": "no_goal"})
            return None
        self._active_project.mark_proposed(self._now())
        await self._append(_PROJECTS_STREAM, "proposed", {"goal": goal})
        await self._publish(topics.INTENT_GOAL_STATED, {
            "goal": goal, "origin": "curiosity", "priority": 5, "wants_project": True,
        })
        return goal

    async def _emit_candidate(self, candidate_id: str, target: Target, idea) -> None:
        novelty = 0.0 if self._recent.similar(idea.description) else 1.0
        await self._append(_CANDIDATES_STREAM, "proposed", {
            "candidate_id": candidate_id, "kind": idea.kind, "subject": target.subject,
            "description": idea.description, "area": target.area,
        })
        await self._publish(topics.CURIOSITY_CANDIDATE, {
            "kind": idea.kind, "subject": target.subject, "description": idea.description,
            "area": target.area, "why_this_area": f"drive-weighted sample (area={target.area})",
            "novelty_score": novelty,
        })

    def _candidate_id(self, subject: str, description: str) -> str:
        return hashlib.sha256(f"{subject}|{description}".encode()).hexdigest()[:16]

    async def _record_tick(
        self, *, picked: list | None = None, proposed: list | None = None, skipped_reason: str | None = None,
        scores: dict | None = None, project: str | None = None, cognition_attempted: bool | None = None,
    ) -> None:
        payload = {
            "ts": self._now(), "backlog": self._backlog.effective_count,
            "picked": picked or [], "proposed": proposed or [],
        }
        if skipped_reason is not None:
            payload["skipped_reason"] = skipped_reason
        if scores is not None:
            payload["drives"] = scores
        if project is not None:
            payload["project"] = project
        if cognition_attempted is not None:
            payload["cognition_attempted"] = cognition_attempted
        self._last_tick_record = payload
        await self._append(_TICKS_STREAM, "tick", payload)

    async def _think(self, purpose: str, prompt: str, *, expected: str | None = None):
        self._cognition_attempted = True
        payload = {
            "purpose": purpose, "messages": [{"role": "user", "content": prompt}],
            "budget": {"max_tokens": 1024, "max_cost_usd": 0.5}, "require_real_provider": False,
        }
        if expected is not None:
            payload["expected"] = expected
        reply = await self._bus.request_or_error(self._bus.new(topics.COGNITION_THINK, payload), timeout=self._config.cognition_timeout)
        if reply.payload.get("ok") is False:
            return "", True, "none"
        return reply.payload.get("text", ""), reply.payload.get("floor", False), reply.payload.get("provider", "")

    async def _publish(self, type_: str, payload: dict) -> None:
        await self._bus.publish(self._bus.new(type_, payload))

    async def _append(self, stream: str, event_type: str, payload: dict) -> None:
        if self._ctx is None:
            return
        event = Event(
            stream=stream, type=event_type, ts=self._now(),
            trace_id=str(uuid.uuid4()), causation_id=None, payload=payload,
        )
        await self._ledger.append(stream, event)
