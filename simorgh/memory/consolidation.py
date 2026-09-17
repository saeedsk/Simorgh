"""Consolidation on `system.tick.sleep` (docs/blueprint/subsystems/05-
memory.md section 4): flag contradictions, prune each durable kind, and
-- if a real Cognition is reachable -- ask for a distilled semantic
summary of the window's episodic activity (`cognition.think`,
`purpose=consolidate`). Degrades honestly: no real provider answering is
a `floor:true` reply, never a fabricated distillation (principle 4.5)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Bus

from .store import MemoryEngine


#: What consolidation asks Cognition for, and the reason this constant
#: exists at all.
#:
#: The request used to carry ONE message -- the episodic window pasted
#: in as `role: "user"` with nothing said about what to do with it.
#: `purpose="consolidate"` only picks a budget (`cognition/config.py`),
#: so nothing anywhere told the model this was a transcript to summarise
#: rather than a question to answer. It answered it. Live-caught by an
#: observer on 2026-09-10, in a 22-turn CLI conversation whose window
#: happened to end on home-lab talk: the first consolidation pass stored
#:
#:   "Good question -- and it's one of the most important decisions for
#:    a home lab, because remote access is the most common thing people
#:    get wrong. ... **1. Tailscale (easiest, and what I'd suggest
#:    first)** ..."
#:
#: as `memory:semantic:1`, tagged `consolidation`. Recall then handed
#: that back as a *memory*, and Sim reported it as history. Asked "Did I
#: ever ask you about remote access or Tailscale? Be precise", it
#: answered "Yes -- precisely once ... That's the only exchange we've had
#: on the topic." The human had never said either word.
#:
#: This is the honesty rule (docs: "a tool must never succeed while
#: saying nothing true") failing at the worst possible place: a
#: fabrication written into durable memory is indistinguishable from a
#: real one forever after. The module docstring's promise -- "never a
#: fabricated distillation" -- was only ever enforced for the *floor*
#: path; a real provider was free to invent whatever it liked because
#: nobody asked it not to.
DISTILL_INSTRUCTION = (
    "You are consolidating memory. The text below is a transcript of past exchanges, "
    "NOT a question addressed to you. Do not answer it, do not advise, do not continue "
    "the conversation. Write only a short factual summary of what was actually said and "
    "what was actually learned, in the third person. Every statement must be traceable to "
    "the transcript -- add nothing, recommend nothing, and never write anything that would "
    "read as the human having said something they did not. If there is nothing worth "
    "recording, reply with exactly: NOTHING"
)

#: Prepended to the window itself, so the framing survives a provider or
#: an assembler that drops or reorders system messages.
DISTILL_PREFIX = "Transcript to summarise (do not answer it):\n\n"

#: The distillation's own opt-out. A model with nothing to record used to
#: have no way to say so and padded instead.
NOTHING = "NOTHING"


#: Specifics a distillation may not invent: a source path, a commit sha,
#: a dotted/underscored identifier in backticks. Prose is not checked --
#: summarising is the job, and paraphrase is not fabrication.
_SPECIFIC = re.compile(
    r"\b[\w./-]+\.py\b"            # simorgh/memory.py
    r"|\b[0-9a-f]{7,40}\b"          # abc1234
    r"|`([\w./]*[._/][\w./]*)`"      # `prune_old`, `tests/x.py`
)


def untraceable(text: str, window: str) -> list[str]:
    """Specifics in `text` that appear nowhere in `window`.

    `DISTILL_INSTRUCTION` already says "every statement must be
    traceable to the transcript -- add nothing". It was not enough. It
    landed 2026-09-10 (`4c2f59d`, "Sim remembered a conversation that
    never happened") and on 2026-09-16 a distillation still wrote, into
    durable memory and in the confident register of a fact:

        "A code note records that `prune_old` in `simorgh/memory.py` was
         reworked ... Four tests pass in `tests/simorgh/test_memory.py`,
         committed as `abc1234`/`abc1235`."

    None of it exists. There is no `simorgh/memory.py` (memory is a
    package), no `prune_old` anywhere in the tree, no
    `tests/simorgh/test_memory.py`, and neither sha is a valid object.
    The task it claimed to describe had in fact reported, correctly,
    "nothing in the source tree was changed, so there is nothing to
    commit" -- the honest record was the input, and the summary of it
    was the lie.

    An instruction is a request; this is a check. The asymmetry is
    deliberate: a name the transcript never mentioned is never a
    summary of it, whatever else the sentence around it is doing.
    """
    seen = window.lower()
    missing: list[str] = []
    for match in _SPECIFIC.finditer(text):
        token = (match.group(1) or match.group(0)).strip()
        if len(token) < 4 or token.lower() in seen:
            continue
        if token not in missing:
            missing.append(token)
    return missing


@dataclass(frozen=True)
class ConsolidationReport:
    contradictions: list[tuple[str, str, str]]
    pruned: dict[str, int] = field(default_factory=dict)
    distilled: bool = False
    #: Specifics a distillation invented, when one was refused for it.
    #: Non-empty means nothing was stored this cycle, on purpose.
    refused: list[str] = field(default_factory=list)


async def run_consolidation(
    engine: MemoryEngine, *, bus: Bus, source: str, keep_per_kind: dict[str, int],
    since: float | None = None, cognition_timeout: float = 30.0,
) -> ConsolidationReport:
    flagged = await engine.flag_contradictions(kind="semantic")
    pruned = {kind: await engine.prune(kind=kind, keep=keep) for kind, keep in keep_per_kind.items()}

    distilled = False
    refused: list[str] = []
    filters = {"since": since} if since is not None else None
    episodic_items, _ = await engine.retrieve(query="", kinds=["episodic"], k=20, filters=filters)
    if episodic_items:
        window = "\n".join(i.content for i in episodic_items)
        request = Message.new(topics.COGNITION_THINK, source=source, payload={
            "purpose": "consolidate",
            "messages": [
                {"role": "system", "content": DISTILL_INSTRUCTION},
                {"role": "user", "content": DISTILL_PREFIX + window},
            ],
            "budget": {"max_tokens": 2_000, "max_cost_usd": 0.1},
            "require_real_provider": False,
        })
        try:
            reply = await bus.request(request, timeout=cognition_timeout)
        except Exception:  # noqa: BLE001 -- cognition unreachable: skip distillation this cycle, never fabricate one
            reply = None
        if reply is not None and reply.payload.get("ok") is not False and not reply.payload.get("floor", True):
            text = str(reply.payload.get("text", "")).strip()
            # `NOTHING` is a real answer, and storing it would be the same
            # class of mistake as storing the essay: filling durable
            # memory with something that was never said.
            invented = untraceable(text, window) if text else []
            if invented:
                # Storing it is the unrecoverable step: a fabrication in
                # durable memory is indistinguishable from a real memory
                # forever after, and recall hands it back as history.
                # Dropping the whole distillation is the right trade --
                # a lost summary costs one cycle, and the next one runs
                # over the same window.
                refused = invented
            elif text and text.upper().strip(".!") != NOTHING:
                await engine.store(
                    kind="semantic", content=text,
                    # A reader of this record -- recall, a later
                    # consolidation, a human -- must be able to tell a
                    # distillation from a thing that happened. It could
                    # not before: `memory:semantic:1` looked exactly like
                    # a remembered exchange.
                    tags=["consolidation", "distilled"], source_ref="", confidence=None,
                )
                distilled = True

    return ConsolidationReport(contradictions=flagged, pruned=pruned, distilled=distilled,
                               refused=refused)


__all__ = ["DISTILL_INSTRUCTION", "DISTILL_PREFIX", "NOTHING", "untraceable",
           "ConsolidationReport", "run_consolidation"]
