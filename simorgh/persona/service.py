"""Persona as a `Subsystem` (docs/blueprint/subsystems/14-persona.md):
continuous mood, a rule-based emotion floor, voice composition, the user
model, and proactive-sharing pacing. Persona never calls Cognition --
it only reacts to events and answers `persona.voice` requests. Layer 5
(registry.py).
"""

from __future__ import annotations

import hashlib
import re
import uuid

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message
from simorgh.contracts.protocols import Context, Health

from .config import Config
from .emotion import react
from .mood import EmotionalState, MoodEngine
from .sharing import SharePolicy
from .user_model import UserModel
from .voice import VoiceComposer, mood_phrase

VERSION = "0.1.0"

_IDENTITY_HEADING_RE = re.compile(r"^##\s*Identity\s*$", re.IGNORECASE | re.MULTILINE)
_SIGNIFICANT_DELTA = 1e-4


def _load_identity_summary(soul_path) -> str:
    """A small, self-contained SOUL.md reader -- Persona does not import
    worldmodel (subsystems talk only through the bus/contracts), so this
    intentionally duplicates a sliver of `worldmodel.selfmodel`'s logic
    rather than reaching across a package boundary."""
    try:
        text = soul_path.read_text(encoding="utf-8")
    except OSError:
        return "You are Simorgh."
    match = _IDENTITY_HEADING_RE.search(text)
    if not match:
        return "You are Simorgh."
    rest = text[match.end():].lstrip("\n")
    paragraph = rest.split("\n\n", 1)[0].strip()
    return paragraph or "You are Simorgh."


class Service:
    name = "persona"
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.PERCEPT_TEXT_RECEIVED, topics.TASK_COMPLETED, topics.TASK_FAILED,
        topics.REFLECT_HEALTH_FINDING, topics.SYSTEM_TICK_SECOND, topics.SYSTEM_STATE_CHANGED,
        topics.PERSONA_VOICE, topics.UI_PROMPT_ANSWERED, topics.CURIOSITY_SHARE_PROPOSED,
    )
    produces: tuple[str, ...] = (
        topics.PERSONA_STATE_CHANGED, topics.PERSONA_VOICE_REPLY, topics.PERSONA_USER_MODEL_UPDATED,
        topics.UI_NOTICE, topics.SYSTEM_HEALTH,
    )

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self._ctx: Context | None = None
        self._subs: list = []
        self._last_decay_ts = 0.0

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        baseline = EmotionalState(valence=self.config.baseline_valence, arousal=self.config.baseline_arousal)
        self._mood = MoodEngine(clock=ctx.clock, history_limit=self.config.history_limit, baseline=baseline)
        self._user_model = UserModel()
        self._share_policy = SharePolicy(
            growth_cooldown_s=self.config.growth_cooldown_s, news_cooldown_s=self.config.news_cooldown_s,
            quiet_when_active_s=self.config.quiet_when_active_s, max_per_hour=self.config.max_shares_per_hour,
        )
        identity_summary = _load_identity_summary(self.config.resolved_soul_path())
        self._voice = VoiceComposer(identity_summary)
        self._last_decay_ts = ctx.clock.now()

        self._subs = [
            await ctx.bus.subscribe(topics.PERCEPT_TEXT_RECEIVED, self._on_percept_text),
            await ctx.bus.subscribe(topics.TASK_COMPLETED, self._on_task_completed),
            await ctx.bus.subscribe(topics.TASK_FAILED, self._on_task_failed),
            await ctx.bus.subscribe(topics.REFLECT_HEALTH_FINDING, self._on_health_finding),
            await ctx.bus.subscribe(topics.SYSTEM_TICK_SECOND, self._on_tick_second),
            await ctx.bus.subscribe(topics.SYSTEM_STATE_CHANGED, self._on_state_changed),
            await ctx.bus.subscribe(topics.PERSONA_VOICE, self._on_voice_request),
            await ctx.bus.subscribe(topics.UI_PROMPT_ANSWERED, self._on_prompt_answered),
            await ctx.bus.subscribe(topics.CURIOSITY_SHARE_PROPOSED, self._on_share_proposed),
        ]
        ctx.logger.info("persona.started", identity_chars=len(identity_summary))

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs = []

    async def health(self) -> Health:
        if self._ctx is None:
            return Health.down("not started")
        return Health.ok()

    # -- mood plumbing ---------------------------------------------------------
    async def _apply_and_announce(self, *, valence: float = 0.0, arousal: float = 0.0,
                                   cognitive_load: float = 0.0, source: str) -> None:
        previous, new = self._mood.apply_delta(
            valence=valence, arousal=arousal, cognitive_load=cognitive_load, source=source,
        )
        if (abs(new.valence - previous.valence) < _SIGNIFICANT_DELTA
                and abs(new.arousal - previous.arousal) < _SIGNIFICANT_DELTA
                and abs(new.cognitive_load - previous.cognitive_load) < _SIGNIFICANT_DELTA):
            return
        await self._publish_state_changed(previous, new, source)

    async def _publish_state_changed(self, previous: EmotionalState, new: EmotionalState, source: str) -> None:
        payload = {
            "valence": new.valence, "arousal": new.arousal, "cognitive_load": new.cognitive_load,
            "source": source,
            "previous": {"valence": previous.valence, "arousal": previous.arousal, "cognitive_load": previous.cognitive_load},
        }
        await self._ctx.bus.publish(Message.new(topics.PERSONA_STATE_CHANGED, source=self._ctx.source, payload=payload))
        await self._persist("persona:state", topics.PERSONA_STATE_CHANGED, payload)

    async def _persist(self, stream: str, type_: str, payload: dict) -> None:
        event = Event(stream=stream, type=type_, ts=self._ctx.clock.now(), trace_id=str(uuid.uuid4()), causation_id=None, payload=payload)
        await self._ctx.ledger.append(stream, event)

    # -- handlers ----------------------------------------------------------------
    async def _on_percept_text(self, message: Message) -> None:
        text = message.payload.get("text", "")
        now = self._ctx.clock.now()
        self._share_policy.note_user_activity(now)
        delta = react(text, lexicon_weight=self.config.lexicon_weight, exclamation_arousal=self.config.exclamation_arousal)
        await self._apply_and_announce(valence=delta.valence, arousal=delta.arousal, source="percept.text")

        session_id = message.payload.get("session_id", "")
        source_ref = hashlib.sha256(f"{message.id}:{session_id}".encode()).hexdigest()[:16] if message.id else session_id
        for facet, value in self._user_model.extract_from_text(text, ts=now, source_ref=source_ref):
            record = self._user_model.facets()[facet]
            payload = {"facet": facet, "value": value, "confidence": record.confidence}
            await self._ctx.bus.publish(Message.new(topics.PERSONA_USER_MODEL_UPDATED, source=self._ctx.source, payload=payload))
            await self._persist("persona:user_model", topics.PERSONA_USER_MODEL_UPDATED, payload)

    async def _on_task_completed(self, message: Message) -> None:
        await self._apply_and_announce(valence=self.config.outcome_nudge_success, source="task.completed")

    async def _on_task_failed(self, message: Message) -> None:
        await self._apply_and_announce(valence=self.config.outcome_nudge_failure, source="task.failed")

    async def _on_health_finding(self, message: Message) -> None:
        if message.payload.get("severity") != "critical" or message.payload.get("action_taken") != "request_reset":
            return
        previous = self._mood.current()
        _, new = self._mood.set_state(
            valence=self.config.baseline_valence, arousal=self.config.baseline_arousal, cognitive_load=0.0,
            source="health.reset",
        )
        await self._publish_state_changed(previous, new, "health.reset")

    async def _on_tick_second(self, message: Message) -> None:
        now = self._ctx.clock.now()
        elapsed = now - self._last_decay_ts
        if elapsed < self.config.decay_interval_s:
            return
        self._last_decay_ts = now
        previous, new = self._mood.decay_toward_baseline(elapsed, half_life_s=self.config.decay_half_life_s)
        if (abs(new.valence - previous.valence) >= _SIGNIFICANT_DELTA
                or abs(new.arousal - previous.arousal) >= _SIGNIFICANT_DELTA):
            await self._publish_state_changed(previous, new, "decay")

    async def _on_state_changed(self, message: Message) -> None:
        self._share_policy.suspend(message.payload.get("state") != "running")

    async def _on_voice_request(self, message: Message) -> None:
        context = message.payload.get("context", "chat")
        voice = self._voice.compose(self._mood.current(), register=context, max_chars=self.config.voice_max_chars)
        await self._ctx.bus.reply(message, type=topics.PERSONA_VOICE_REPLY,
                                   payload={"style_block": voice.style_block, "mood_phrase": voice.mood_phrase})

    async def _on_prompt_answered(self, message: Message) -> None:
        self._share_policy.note_user_activity(self._ctx.clock.now())

    async def _on_share_proposed(self, message: Message) -> None:
        """Proactive-sharing plumbing (ported pacing from
        `src/orchestrator/socializing.py`). Nothing publishes
        `curiosity.share.proposed` yet this phase -- this subscriber and
        its cooldown/quiet-period/hourly-cap logic exist and are tested,
        ready for Curiosity to drive once it lands."""
        kind = message.payload.get("kind", "growth")
        content_ref = message.payload.get("content_ref", "")
        now = self._ctx.clock.now()
        decision = self._share_policy.decide(kind, now)
        if not decision.share:
            return
        self._share_policy.note_shared(kind, now)
        phrase = mood_phrase(self._mood.current())
        payload = {"level": "info", "text": f"({phrase}) I found something ({kind}): {content_ref}", "source": self._ctx.source}
        await self._ctx.bus.publish(Message.new(topics.UI_NOTICE, source=self._ctx.source, payload=payload))
        await self._persist("persona:shares", topics.UI_NOTICE, {"kind": kind, "content_ref": content_ref})


__all__ = ["Service", "VERSION"]
