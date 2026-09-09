"""Prompt assembly (docs/blueprint/subsystems/04-cognition.md section 5,
"Prompt assembly order"): ordered blocks, each `protected` (never
compacted -- principle 4.6) or `elastic`. `persona.voice`/`self.summary`
are requested with a short timeout; a missing block is omitted and
logged, never fatal -- Cognition must work correctly whether or not
Persona/World Model exist yet or are reachable (graceful degradation,
principle 4.5's spirit applied to *other subsystems* being absent, not
just providers).

For `purpose="chat"` a `user_profile` block is also requested, from World
Model's `user_profile` facet (fed by Persona's `persona.user_model.updated`
-- "call me X", "I prefer X" statements extracted by
`persona/user_model.py`). Before this, nothing ever read that facet back:
Persona wrote it and forgot it, so a user who said "call me Al" got no
different a reply than one who never had. `_MIN_FACET_CONFIDENCE` mirrors
`persona.config.Config.user_model_min_confidence`'s default (0.5) --
Cognition does not import Persona's config, so this is restated rather
than shared, same reasoning as `persona/service.py`'s own
`_load_identity_summary`."""

from __future__ import annotations

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Bus, Logger

from .api import AssembledContext, PromptBlock
from .tokens import estimate_tokens

CONSTITUTION_SUMMARY = (
    "Core directives, priority order: Safety > Lawfulness > Loyalty > "
    "Corrigibility > Restraint > Stability > Growth > Transparency."
)

_MIN_FACET_CONFIDENCE = 0.5


class PromptAssembler:
    def __init__(self, bus: Bus, source: str, *, request_timeout: float, logger: Logger | None = None) -> None:
        self._bus = bus
        self._source = source
        self._timeout = request_timeout
        self._logger = logger

    async def assemble(
        self, *, purpose: str, messages: list[dict], task_rules: str = "", last_step: bool = False,
    ) -> AssembledContext:
        blocks: list[PromptBlock] = [self._block("constitution", CONSTITUTION_SUMMARY, protected=True)]

        voice = await self._try_request(topics.PERSONA_VOICE, {"context": "chat" if purpose == "chat" else "notice"})
        if voice is not None:
            blocks.append(self._block("voice", voice.get("style_block", ""), protected=True))

        summary = await self._try_request(topics.SELF_SUMMARY, {"budget_tokens": 300})
        if summary is not None:
            blocks.append(self._block("self_summary", summary.get("text", ""), protected=True))

        if purpose == "chat":
            profile_text = await self._user_profile_text()
            if profile_text:
                blocks.append(self._block("user_profile", profile_text, protected=True))

        if task_rules:
            blocks.append(self._block("task_rules", task_rules, protected=True))

        conversation = "\n\n".join(f"[{m.get('role', 'user')}] {m.get('content', '')}" for m in messages)
        blocks.append(self._block("conversation", conversation, protected=False))

        if last_step:
            blocks.append(self._block(
                "final_turn_hint",
                "This is your last step -- no more tool calls will be honored. "
                "Write your final answer now, using whatever you've already learned.",
                protected=True,
            ))

        return AssembledContext(blocks=tuple(blocks))

    async def _user_profile_text(self) -> str:
        reply = await self._try_request(topics.WORLD_ENV_QUERY, {"what": "user_profile", "args": {}})
        if reply is None:
            return ""
        facets = reply.get("facets", {})
        known = [
            f"{name}: {facet.get('value')}" for name, facet in facets.items()
            if facet.get("confidence", 0.0) >= _MIN_FACET_CONFIDENCE
        ]
        if not known:
            return ""
        return "What you know about the user: " + "; ".join(sorted(known))

    def _block(self, name: str, text: str, *, protected: bool) -> PromptBlock:
        return PromptBlock(name=name, text=text, protected=protected, tokens=estimate_tokens(text))

    async def _try_request(self, type_: str, payload: dict) -> dict | None:
        try:
            message = Message.new(type_, source=self._source, payload=payload)
            reply = await self._bus.request(message, timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001 -- BusTimeout or "nobody answers this yet": omit, never fail assembly
            if self._logger is not None:
                self._logger.debug("cognition.assembly_block_omitted", block=type_, reason=repr(exc))
            return None
        if reply.payload.get("ok") is False:
            return None
        return reply.payload


__all__ = ["PromptAssembler"]
