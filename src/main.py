"""CLI entry point: reads user input, routes it through the orchestrator to
the emotion and logic sub-agents, and synthesizes their output -- using the
persona's mood on the shared bus -- into one human-like reply.

Every dispatch is also recorded through OutcomeLog (src/orchestrator/
reflection.py), so the feedback loop has real data instead of only being
exercised by tests -- see docs/EVOLUTION.md, "Learning From Mistakes." A
'propose <topic>' command drafts a skill via SkillResearchAgent and runs it
through AuditGate; anything that passes automated checks is logged as
pending, never merged automatically -- 'pending' lists what's awaiting the
creator's actual review. See docs/EVOLUTION.md milestone 10.
"""

from __future__ import annotations

from pathlib import Path

from src.agents.emotion.base import EmotionAgent
from src.agents.interests import InterestTracker
from src.agents.logic.base import LogicAgent
from src.agents.skills.research import SkillResearchAgent
from src.memory.long_term import JSONFileMemoryStore, MemoryStore
from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.audit import REJECTED_KIND, AuditGate
from src.orchestrator.consolidation import run_consolidation
from src.orchestrator.reflection import Outcome, OutcomeLog, ReflectionAgent
from src.orchestrator.router import AgentRequest, Router

EXIT_COMMANDS = {"exit", "quit"}
REFLECT_COMMAND = "reflect"
PENDING_COMMAND = "pending"
PROPOSE_PREFIX = "propose "
PENDING_KIND = "pending_approval"
INTEREST_PREFIX = "interest "
INTERESTS_COMMAND = "interests"
CURIOUS_COMMAND = "curious"
SLEEP_COMMAND = "sleep"
DEFAULT_MEMORY_PATH = Path.home() / ".simorgh" / "memory.jsonl"


def build_router() -> Router:
    router = Router(SharedMemoryBus())
    router.register(EmotionAgent())
    router.register(LogicAgent())
    return router


def build_memory_store(path: Path = DEFAULT_MEMORY_PATH) -> MemoryStore:
    return JSONFileMemoryStore(path)


def build_outcome_log(store: MemoryStore | None = None) -> OutcomeLog:
    return OutcomeLog(store or build_memory_store())


def synthesize(reaction: str, response: str, bus: SharedMemoryBus) -> str:
    """Combine the emotion agent's reaction and the logic agent's response
    into one reply, checking the persona's live mood on the shared bus to
    decide whether to flag that it's under heavy cognitive load.
    """
    parts = [reaction]
    if bus.read().cognitive_load >= 0.6:
        parts.append("(taking a moment to think this through.)")
    parts.append(response)
    return " ".join(parts)


def handle_turn(
    router: Router, text: str, outcome_log: OutcomeLog | None = None
) -> str:
    request = AgentRequest(text=text)
    reaction = _dispatch_and_record(router, "emotion", request, outcome_log)
    response = _dispatch_and_record(router, "logic", request, outcome_log)
    return synthesize(reaction, response, router.bus)


def _dispatch_and_record(
    router: Router, name: str, request: AgentRequest, outcome_log: OutcomeLog | None
) -> str:
    try:
        response = router.dispatch(name, request)
    except Exception as exc:  # noqa: BLE001 -- a failing sub-agent must not
        # crash the CLI turn; it becomes a recorded, visible failure instead
        if outcome_log is not None:
            outcome_log.record(
                Outcome(
                    agent=name,
                    request_text=request.text,
                    output="",
                    succeeded=False,
                    note=repr(exc),
                )
            )
        return f"[{name} agent failed: {exc}]"

    if outcome_log is not None:
        outcome_log.record(
            Outcome(
                agent=name,
                request_text=request.text,
                output=response.output,
                succeeded=True,
            )
        )
    return response.output


def run_cli() -> None:
    store = build_memory_store()
    router = build_router()
    outcome_log = OutcomeLog(store)
    reflection_agent = ReflectionAgent(outcome_log)
    audit_gate = AuditGate(memory=store)
    skill_research = SkillResearchAgent()
    interests = InterestTracker(store)
    print(
        "Simorgh -- 'exit'/'quit' to leave, 'reflect' for outcome review, "
        "'propose <topic>' to draft a skill, 'pending' for unmerged proposals, "
        "'interest <topic>'/'interests'/'curious' for world-awareness, "
        "'sleep' for maintenance."
    )
    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        lowered = user_input.lower()
        if lowered in EXIT_COMMANDS:
            break
        if lowered == REFLECT_COMMAND:
            _print_reflection(reflection_agent)
            continue
        if lowered == PENDING_COMMAND:
            _print_pending(store)
            continue
        if lowered.startswith(PROPOSE_PREFIX):
            propose_skill(
                skill_research, audit_gate, store, user_input[len(PROPOSE_PREFIX):].strip()
            )
            continue
        if lowered.startswith(INTEREST_PREFIX):
            note_interest(interests, user_input[len(INTEREST_PREFIX):].strip())
            continue
        if lowered == INTERESTS_COMMAND:
            _print_interests(interests)
            continue
        if lowered == CURIOUS_COMMAND:
            _follow_up(interests)
            continue
        if lowered == SLEEP_COMMAND:
            _run_sleep(store, reflection_agent)
            continue
        print(handle_turn(router, user_input, outcome_log))


def _print_reflection(reflection_agent: ReflectionAgent) -> None:
    proposals = reflection_agent.reflect()
    if not proposals:
        print("[no concerning patterns in recent outcomes]")
        return
    for proposal in proposals:
        print(f"[proposal] {proposal.rationale}")


def propose_skill(
    skill_research: SkillResearchAgent,
    audit_gate: AuditGate,
    store: MemoryStore,
    topic: str,
) -> str:
    """Draft a skill on `topic`, run it through the audit gate, and -- if it
    passes automated checks -- log it as pending the creator's actual
    review. Nothing is ever merged here; this only ever produces something
    for a human to look at. Returns the message printed, for testability.
    """
    if not topic:
        message = "[usage: propose <topic>]"
        print(message)
        return message

    proposal = skill_research.draft_skill(topic)
    verdict = audit_gate.review(proposal)

    if not verdict.approved_by_automation:
        message = f"[rejected] {'; '.join(verdict.reasons)}"
        print(message)
        return message

    store.remember(
        PENDING_KIND, proposal.subject, code=proposal.code, rationale=proposal.rationale
    )
    message = (
        f"[PENDING YOUR APPROVAL] {proposal.subject} -- {proposal.rationale} "
        "(automated checks passed; nothing merges without your review)"
    )
    print(message)
    return message


def _print_pending(store: MemoryStore) -> None:
    records = store.query(kind=PENDING_KIND)
    if not records:
        print("[no proposals pending approval]")
        return
    for record in records:
        print(f"[pending] {record.content} -- {record.metadata.get('rationale', '')}")


def note_interest(tracker: InterestTracker, topic: str) -> str:
    """Start tracking `topic`. Returns the message printed, for testability."""
    if not topic:
        message = "[usage: interest <topic>]"
        print(message)
        return message
    tracker.note_interest(topic, why="noted by the creator")
    message = f"[noted] now tracking interest in {topic!r}"
    print(message)
    return message


def _print_interests(tracker: InterestTracker) -> None:
    interests = tracker.list_interests()
    if not interests:
        print("[no tracked interests yet -- try 'interest <topic>']")
        return
    for interest in interests:
        status = "never followed up" if interest.last_followed_up is None else "followed up"
        print(f"[interest] {interest.topic} ({status}) -- {interest.why}")


def _follow_up(tracker: InterestTracker) -> None:
    overdue = tracker.least_recently_followed_up()
    if overdue is None:
        print("[nothing to be curious about yet -- try 'interest <topic>' first]")
        return
    items = tracker.follow_up(overdue.topic)
    if not items:
        print(
            f"[curious about {overdue.topic!r}] no updates available "
            "(no real WorldFeed configured yet -- see src/agents/interests.py)"
        )
        return
    for item in items:
        print(f"[{overdue.topic}] {item.title}: {item.summary}")


def _run_sleep(store: MemoryStore, reflection_agent: ReflectionAgent) -> None:
    report = run_consolidation(
        store, reflection_agent, keep_per_kind={"outcome": 200, REJECTED_KIND: 200}
    )
    pruned = ", ".join(f"{kind}: {count}" for kind, count in report.pruned_counts.items())
    print(f"[sleep] pruned -- {pruned or 'nothing to prune'}")
    if not report.proposals:
        print("[sleep] no concerning patterns in recent outcomes")
        return
    for proposal in report.proposals:
        print(f"[sleep proposal] {proposal.rationale}")


if __name__ == "__main__":
    run_cli()
