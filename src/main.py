"""CLI entry point: reads user input, routes it through the orchestrator to
the emotion and logic sub-agents, and synthesizes their output -- using the
persona's mood on the shared bus -- into one human-like reply.

Every dispatch is also recorded through OutcomeLog (src/orchestrator/
reflection.py), so the feedback loop has real data instead of only being
exercised by tests -- see docs/EVOLUTION.md, "Learning From Mistakes."
"""

from __future__ import annotations

from pathlib import Path

from src.agents.emotion.base import EmotionAgent
from src.agents.logic.base import LogicAgent
from src.memory.long_term import JSONFileMemoryStore, MemoryStore
from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.reflection import Outcome, OutcomeLog, ReflectionAgent
from src.orchestrator.router import AgentRequest, Router

EXIT_COMMANDS = {"exit", "quit"}
REFLECT_COMMAND = "reflect"
DEFAULT_MEMORY_PATH = Path.home() / ".simorgh" / "memory.jsonl"


def build_router() -> Router:
    router = Router(SharedMemoryBus())
    router.register(EmotionAgent())
    router.register(LogicAgent())
    return router


def build_outcome_log(store: MemoryStore | None = None) -> OutcomeLog:
    return OutcomeLog(store or JSONFileMemoryStore(DEFAULT_MEMORY_PATH))


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
    router = build_router()
    outcome_log = build_outcome_log()
    reflection_agent = ReflectionAgent(outcome_log)
    print("Simorgh -- type 'exit'/'quit' to leave, 'reflect' to review recent outcomes.")
    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input.lower() in EXIT_COMMANDS:
            break
        if user_input.lower() == REFLECT_COMMAND:
            _print_reflection(reflection_agent)
            continue
        print(handle_turn(router, user_input, outcome_log))


def _print_reflection(reflection_agent: ReflectionAgent) -> None:
    proposals = reflection_agent.reflect()
    if not proposals:
        print("[no concerning patterns in recent outcomes]")
        return
    for proposal in proposals:
        print(f"[proposal] {proposal.rationale}")


if __name__ == "__main__":
    run_cli()
