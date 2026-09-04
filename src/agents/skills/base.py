"""Skills sub-agent: runs skill code through a SandboxExecutor, isolated
from the persona's core cognitive state. See project_simorgh_groundwork.md
(Phase 3).
"""

from __future__ import annotations

from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.router import AgentRequest, AgentResponse, SubAgent
from src.sandboxing.sandbox import SandboxExecutor, SubprocessSandbox


class SkillsAgent(SubAgent):
    """Executes the code carried in an AgentRequest inside a sandbox and
    reports the result back to the orchestrator.

    The sandboxed code itself never receives the SharedMemoryBus or
    PersonaState -- only this agent (running in-process and trusted)
    touches those. That keeps a misbehaving or malicious skill from
    reading or corrupting the persona's cognitive state; the only way
    sandbox output reaches the persona is through this agent's own,
    deliberate `bus.publish_delta` call below.
    """

    name = "skills"

    def __init__(
        self, executor: SandboxExecutor | None = None, timeout: float = 5.0
    ) -> None:
        self._executor = executor or SubprocessSandbox()
        self._timeout = timeout

    def handle(self, request: AgentRequest, bus: SharedMemoryBus) -> AgentResponse:
        result = self._executor.run(request.text, timeout=self._timeout)

        bus.publish_delta(
            self.name, cognitive_load=0.05 if result.succeeded else 0.1
        )

        output = (
            result.stdout
            if result.succeeded
            else result.stderr or "sandboxed skill failed"
        )
        return AgentResponse(
            agent=self.name,
            output=output,
            metadata={
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "duration_seconds": result.duration_seconds,
            },
        )
