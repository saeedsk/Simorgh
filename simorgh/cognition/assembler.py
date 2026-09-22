"""Prompt assembly (docs/blueprint/subsystems/04-cognition.md section 5,
"Prompt assembly order"): ordered blocks, each `protected` (never
compacted -- principle 4.6) or `elastic`. `persona.voice`/`self.summary`
are requested with a short timeout; a missing block is omitted and
logged, never fatal -- Cognition must work correctly whether or not
Persona/World Model exist yet or are reachable (graceful degradation,
principle 4.5's spirit applied to *other subsystems* being absent, not
just providers).

There is no `user_profile` block any more (stage 6 item 4, 2026-09-22).
From 2026-09-08 the assembler asked World Model for ONE household-wide
profile ("call me X", "I prefer X", from `persona/user_model.py`) and put
it in every chat prompt as "What you know about the user" -- so whatever
Ira asked to be called was what Sim called her father. Those facts are a
person's `preferences` in the People store now, and showing the right
person's needs to know who is speaking, which a `cognition.think` does
not carry. Orchestration's context, which builds the per-turn blocks
with the session's speaker, renders them (`world.env.query{what:
"user_profile", args: {person, channel}}` answers with a ready `text`).
Showing nobody's is correct; showing the wrong person's is the bug."""

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

_WINDING_DOWN_STEPS = 3


class PromptAssembler:
    def __init__(self, bus: Bus, source: str, *, request_timeout: float, logger: Logger | None = None) -> None:
        self._bus = bus
        self._source = source
        self._timeout = request_timeout
        self._logger = logger

    async def assemble(
        self, *, purpose: str, messages: list[dict], task_rules: str = "", last_step: bool = False,
        steps_left: int | None = None, trace_id: str = "",
    ) -> AssembledContext:
        # `trace_id`: the think's own trace, carried onto the context
        # requests it makes (persona voice, self summary) so
        # they belong to the turn that caused them (stage 1 item 2). Passed
        # down, not stored: one assembler serves concurrent thinks.
        blocks: list[PromptBlock] = [self._block("constitution", CONSTITUTION_SUMMARY, protected=True)]

        voice = await self._try_request(topics.PERSONA_VOICE, {"context": "chat" if purpose == "chat" else "notice"}, trace_id)
        if voice is not None:
            blocks.append(self._block("voice", voice.get("style_block", ""), protected=True))

        summary = await self._try_request(topics.SELF_SUMMARY, {"budget_tokens": 300}, trace_id)
        if summary is not None:
            blocks.append(self._block("self_summary", summary.get("text", ""), protected=True))

        if task_rules:
            blocks.append(self._block("task_rules", task_rules, protected=True))

        conversation = "\n\n".join(f"[{m.get('role', 'user')}] {m.get('content', '')}" for m in messages)
        blocks.append(self._block("conversation", conversation, protected=False))

        # The step-budget hints change from step to step, so they ride at
        # the head of the latest user turn (`turn_note`) and the system
        # prefix stays byte-identical for a caching provider (stage 4 item 4).
        turn_note = ""
        if last_step:
            turn_note = ("This is your last step -- no more tool calls will be honored. "
                         "Write your final answer now, using whatever you've already learned.")
        elif steps_left is not None and steps_left <= _WINDING_DOWN_STEPS:
            # Told BEFORE the wall, not at it. A run that only learns its
            # budget on the final step has no chance to land what it was
            # doing -- it discovers the limit at the moment it can no
            # longer act on it, and blocks with the work half-written.
            # Live-caught 2026-09-09, three attempts in a row at the same
            # task, each ending "step budget exhausted with work still
            # pending" and each starting again from nothing.
            turn_note = (f"You have {steps_left} tool call(s) left before this attempt ends. "
                         "Get to a state you can hand over: save what you have to a file, then say "
                         "plainly what is done and what is left. Do not start anything new.")

        return AssembledContext(blocks=tuple(blocks), turn_note=turn_note)

    def _block(self, name: str, text: str, *, protected: bool) -> PromptBlock:
        return PromptBlock(name=name, text=text, protected=protected, tokens=estimate_tokens(text))

    async def _try_request(self, type_: str, payload: dict, trace_id: str = "") -> dict | None:
        try:
            message = Message.new(type_, source=self._source, payload=payload, trace_id=trace_id or None)
            reply = await self._bus.request(message, timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001 -- BusTimeout or "nobody answers this yet": omit, never fail assembly
            if self._logger is not None:
                self._logger.debug("cognition.assembly_block_omitted", block=type_, reason=repr(exc))
            return None
        if reply.payload.get("ok") is False:
            return None
        return reply.payload


__all__ = ["PromptAssembler"]
