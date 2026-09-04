"""CLI entry point: reads user input, routes it through the orchestrator to
the emotion and logic sub-agents, and synthesizes their output -- using the
persona's mood on the shared bus -- into one human-like reply.
"""

from __future__ import annotations

from src.agents.emotion.base import EmotionAgent
from src.agents.logic.base import LogicAgent
from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.router import AgentRequest, Router

EXIT_COMMANDS = {"exit", "quit"}


def build_router() -> Router:
    router = Router(SharedMemoryBus())
    router.register(EmotionAgent())
    router.register(LogicAgent())
    return router


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


def handle_turn(router: Router, text: str) -> str:
    request = AgentRequest(text=text)
    reaction = router.dispatch("emotion", request).output
    response = router.dispatch("logic", request).output
    return synthesize(reaction, response, router.bus)


def run_cli() -> None:
    router = build_router()
    print("Simorgh -- type 'exit' or 'quit' to leave.")
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
        print(handle_turn(router, user_input))


if __name__ == "__main__":
    run_cli()
