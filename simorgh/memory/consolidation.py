"""Consolidation on `system.tick.sleep` (docs/blueprint/subsystems/05-
memory.md section 4): flag contradictions, prune each durable kind, and
-- if a real Cognition is reachable -- ask for a distilled semantic
summary of the window's episodic activity (`cognition.think`,
`purpose=consolidate`). Degrades honestly: no real provider answering is
a `floor:true` reply, never a fabricated distillation (principle 4.5)."""

from __future__ import annotations

import hashlib
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
    #: The facts extracted this cycle (stage 5 item 3).
    facts: list = field(default_factory=list)
    #: Live facts given entity ids by the backfill this pass (stage 15).
    linked: int = 0
    #: `(merged id, surviving id)` for each pair the model said was one.
    merged: list = field(default_factory=list)
    #: The entity summary pass (stage 15 item 3); None when it did not run.
    summaries: "SummaryReport | None" = None


async def run_consolidation(
    engine: MemoryEngine, *, bus: Bus, source: str, keep_per_kind: dict[str, int],
    since: float | None = None, cognition_timeout: float = 30.0,
) -> ConsolidationReport:
    # `flag_contradictions` is retired (stage 5 item 3): it halved BOTH
    # sides of a disagreement, so a correction was buried with what it
    # corrected. A correction now wins by structure in the fact store, and
    # `memory:contradictions` is kept read-only for what is already there.
    flagged: list[tuple[str, str, str]] = []
    pruned = {kind: await engine.prune(kind=kind, keep=keep) for kind, keep in keep_per_kind.items()}

    distilled = False
    refused: list[str] = []
    stored_facts: list = []
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

        stored_facts = await extract_facts(engine, bus=bus, source=source, window=window,
                                           refs=[i.ref for i in episodic_items], timeout=cognition_timeout)
    # Stage 15 item 1: the facts written before entities get their ids
    # (idempotent, so a no-op once done), and the names resolution found
    # close but not certain are put to the model, which is the only place
    # one is consulted about identity.
    linked = await engine.link_facts()
    merged = await review_uncertain(engine, bus=bus, source=source, timeout=cognition_timeout)
    summaries = await summarise_entities(engine, bus=bus, source=source, timeout=cognition_timeout)
    return ConsolidationReport(contradictions=flagged, pruned=pruned, distilled=distilled,
                               refused=refused, facts=stored_facts, linked=linked, merged=merged,
                               summaries=summaries)


SUMMARY_INSTRUCTION = (
    "Below are facts a household has told its assistant about one person, place or thing. Write a "
    "summary of it in one to three short sentences, in the third person, using ONLY these facts. "
    "Add nothing: no number, name, date or detail that is not in the facts, and no advice. If the "
    "facts say nothing worth summarising, reply with exactly: NOTHING"
)
#: How many entities one pass may summarise: each is a model call.
MAX_SUMMARIES = 8
#: A summary longer than this is not one to three short sentences.
SUMMARY_MAX_CHARS = 400


@dataclass
class SummaryReport:
    """What the summary pass did (stage 15 item 3)."""

    written: list = field(default_factory=list)     # entity ids given a new summary
    skipped: int = 0                                # due, but no real provider answered
    refused: dict = field(default_factory=dict)     # entity id -> what the summary invented


async def summarise_entities(engine: MemoryEngine, *, bus: Bus, source: str, timeout: float) -> SummaryReport:
    """Give each entity with facts new since its last summary a 1-3
    sentence one, as an `entity.summary` event.

    Written only from facts scoped to the household (`*`), and stored with
    that scope: a summary is one line anybody's recall may carry, so a fact
    private to somebody must never be folded into it. Held to its facts by
    the same check as a distillation (`untraceable`): one that names a
    specific its facts do not is dropped whole. A floor or failed reply
    writes nothing and is counted as skipped -- the next pass tries again.
    """
    from .entities import SUMMARY
    from .facts import EVERYONE

    report = SummaryReport()
    if not engine._config.entities:  # noqa: SLF001
        return report
    facts = await engine._facts_synced()  # noqa: SLF001
    entities = await engine._entities_synced()  # noqa: SLF001
    about: dict[str, list] = {}
    for fact in facts.live_facts():
        if fact.person_scope != EVERYONE:
            continue
        for end in set(engine.fact_ends(fact, entities)) - {""}:
            about.setdefault(end, []).append(fact)
    due = []
    for entity_id in sorted(about):
        entity = entities.get(entity_id)
        if entity is None or entity.id != entity_id:
            continue
        ids = frozenset(f.id for f in about[entity_id])
        if ids <= entities.summarised.get(entity_id, (frozenset(), ""))[0]:
            continue    # nothing new since the last summary
        due.append((entity, sorted(about[entity_id], key=lambda f: (f.valid_from, f.id)), ids))
    for entity, its_facts, ids in due[:MAX_SUMMARIES]:
        window = "\n".join(f"- {fact.sentence()}" for fact in its_facts)
        request = Message.new(topics.COGNITION_THINK, source=source, payload={
            # `memory.summary` is the purpose the stage 15 plan names; the
            # contracts enum does not have it yet, so this rides on
            # `consolidate`'s budget, as the other sleep-tick calls do.
            "purpose": "consolidate",
            "messages": [{"role": "system", "content": SUMMARY_INSTRUCTION},
                         {"role": "user", "content": f"About: {entity.name}\nFacts:\n{window}"}],
            "budget": {"max_tokens": 200, "max_cost_usd": 0.02},
            "require_real_provider": False,
        })
        try:
            reply = await bus.request(request, timeout=timeout)
        except Exception:  # noqa: BLE001 -- no cognition: no summary this pass, never an invented one
            reply = None
        if reply is None or reply.payload.get("ok") is False or reply.payload.get("floor", True):
            report.skipped += 1
            continue
        text = " ".join(str(reply.payload.get("text") or "").split())
        if not text or text.upper().strip(".!") == NOTHING:
            continue
        source_text = f"{entity.name}\n{window}"
        invented = untraceable(text, source_text)
        # `untraceable` holds code-shaped specifics to their source; in a
        # summary of household facts the specific most worth inventing is a
        # number (a phone, a date), so every digit run is held the same way.
        invented += [n for n in re.findall(r"\d+", text) if n not in source_text and n not in invented]
        if len(text) > SUMMARY_MAX_CHARS:
            invented = invented or [f"{len(text)} characters"]
        if invented:
            report.refused[entity.id] = invented
            continue
        await engine._entity_event(SUMMARY, {  # noqa: SLF001
            "id": entity.id, "summary": text, "person_scope": EVERYONE, "fact_ids": sorted(ids)},
            f"{entity.id}:summary:{hashlib.sha1('-'.join(sorted(ids)).encode()).hexdigest()[:16]}")
        report.written.append(entity.id)
    return report


SAME_INSTRUCTION = (
    "Two names were used in one household's conversations. Say whether they name the same person, "
    "place or thing. Reply with exactly YES or NO and nothing else. If you are not sure, reply NO."
)
#: How many close pairs one pass may ask about.
MAX_SAME_QUESTIONS = 5


async def review_uncertain(engine: MemoryEngine, *, bus: Bus, source: str, timeout: float) -> list[tuple[str, str]]:
    """Ask about the pairs resolution flagged as close but not certain;
    merge on a plain YES from a real provider. Returns `(merged, into)`.

    Anything else -- a floor reply, no Cognition, a hedge -- leaves both
    entities as they are: a missed merge costs a hop, a wrong one files
    one person's facts under another's name."""
    if not engine._config.entities:  # noqa: SLF001
        return []
    index = await engine._entities_synced()  # noqa: SLF001
    merged: list[tuple[str, str]] = []
    from .entities import normalise

    answered: set[str] = set()
    for text, candidate in sorted(index.uncertain)[:MAX_SAME_QUESTIONS]:
        index.uncertain.discard((text, candidate))
        if text in answered:
            continue   # one name merges once: a second yes would chain two other entities together
        mine = index.alias.get(normalise(text))
        theirs = index.get(candidate)
        if not mine or theirs is None or index.canonical(mine) == theirs.id:
            continue
        request = Message.new(topics.COGNITION_THINK, source=source, payload={
            "purpose": "consolidate",
            "messages": [{"role": "system", "content": SAME_INSTRUCTION},
                         {"role": "user", "content": f"First: {text}\nSecond: {theirs.name}"}],
            "budget": {"max_tokens": 5, "max_cost_usd": 0.01},
            "require_real_provider": False,
        })
        try:
            reply = await bus.request(request, timeout=timeout)
        except Exception:  # noqa: BLE001 -- no answer is not a yes
            continue
        if reply.payload.get("ok") is False or reply.payload.get("floor", True):
            continue
        if str(reply.payload.get("text") or "").strip().strip(".!").upper() == "YES":
            answered.add(text)
            old = index.canonical(mine)
            merged.append((old, await engine.merge_entities(old, theirs.id, reason="model: same")))
    return merged


EXTRACT_INSTRUCTION = (
    "You are reading a transcript of things a household said, to record what HOLDS -- a "
    "fact that is still true afterwards, not an event. Reply with ONLY a JSON array, no "
    "prose. Each element is "
    '{"subject": "...", "predicate": "...", "object": "...", "person": "<name or empty for the household>", '
    '"quote": "<the exact sentence from the transcript that says it>"}. '
    "The quote must be copied from the transcript word for word. Record a fact only when the "
    "transcript states it; record nothing you inferred, guessed or would like to be true. A "
    "correction replaces what it corrects: record the corrected value, with the sentence that "
    "corrected it as the quote. "
    # Stage 10 item 7. An interest is a fact like any other and is
    # recorded like one; what it is NOT is permission to bring the
    # subject up, which is a separate thing a person says yes to.
    "When somebody says what they care about -- a hobby, a subject they follow, something they "
    "are working on -- record it with the predicate \"interest\": "
    '{"subject": "Aran", "predicate": "interest", "object": "lego robotics", "person": "Aran", '
    '"quote": "..."}. Only from what they said about themselves, never from what somebody else '
    "said about them. "
    "If nothing in the transcript holds, reply with []"
)
#: How many facts one cycle may record. A window of 20 exchanges that
#: yields more than this is a model writing an essay, not reading facts.
MAX_FACTS = 12


def parse_facts(text: str, window: str) -> tuple[list[dict], list[str]]:
    """`(facts, rejected quotes)` from a model's JSON array.

    The same rule as `untraceable`, per triple: a fact is kept only when
    its quote really appears in the transcript. A fact nobody said is worse
    than no fact, because recall hands it back as history for ever.
    """
    import json
    import re as _re

    match = _re.search(r"\[.*\]", text or "", _re.S)
    if not match:
        return [], []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return [], []
    flat = " ".join(window.split()).lower()
    kept, rejected = [], []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        subject, predicate = str(entry.get("subject") or "").strip(), str(entry.get("predicate") or "").strip()
        object_ = str(entry.get("object") or "").strip()
        quote = " ".join(str(entry.get("quote") or "").split())
        if not (subject and predicate and object_):
            continue
        if not quote or quote.lower() not in flat:
            rejected.append(quote or f"{subject} {predicate} {object_}")
            continue
        kept.append({"subject": subject, "predicate": predicate, "object": object_,
                     "person": str(entry.get("person") or "").strip(), "quote": quote})
        if len(kept) >= MAX_FACTS:
            break
    return kept, rejected


async def extract_facts(engine: MemoryEngine, *, bus: Bus, source: str, window: str, refs: list[str],
                        timeout: float) -> list:
    """Read the window for facts and store them; the ones stored.

    Nothing here is fatal: cognition unreachable, a floor answer or
    unparseable JSON all mean "no facts this cycle", never a wrong one.
    """
    request = Message.new(topics.COGNITION_THINK, source=source, payload={
        "purpose": "consolidate",
        "messages": [
            {"role": "system", "content": EXTRACT_INSTRUCTION},
            {"role": "user", "content": DISTILL_PREFIX + window},
        ],
        "budget": {"max_tokens": 1_500, "max_cost_usd": 0.1},
        "require_real_provider": False,
    })
    try:
        reply = await bus.request(request, timeout=timeout)
    except Exception:  # noqa: BLE001 -- no cognition, no facts this cycle
        return []
    if reply.payload.get("ok") is False or reply.payload.get("floor", True):
        return []
    kept, _rejected = parse_facts(str(reply.payload.get("text") or ""), window)
    stored = []
    for entry in kept:
        stored.append(await engine.store_fact(
            subject=entry["subject"], predicate=entry["predicate"], object=entry["object"],
            person_scope=entry["person"], source_refs=tuple(refs[:3])))
    return stored


__all__ = ["DISTILL_INSTRUCTION", "DISTILL_PREFIX", "EXTRACT_INSTRUCTION", "MAX_FACTS", "NOTHING", "untraceable",
           "ConsolidationReport", "MAX_SAME_QUESTIONS", "MAX_SUMMARIES", "SAME_INSTRUCTION", "SUMMARY_INSTRUCTION",
           "SUMMARY_MAX_CHARS", "SummaryReport", "extract_facts", "parse_facts", "review_uncertain",
           "run_consolidation", "summarise_entities"]
