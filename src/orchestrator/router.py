"""Central routing and delegation engine.

Defines the common interface every orchestrator sub-agent (emotion, logic,
skills, ...) implements, and the Router that dispatches requests to
registered agents by name. See project_simorgh_groundwork.md (Phase 3).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from src.memory.shared_bus import SharedMemoryBus


@dataclass
class AgentRequest:
    """A unit of work handed to a sub-agent."""

    text: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    """A sub-agent's result, handed back to the orchestrator."""

    agent: str
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)


class SubAgent(abc.ABC):
    """Common interface every sub-agent must implement.

    A sub-agent receives a request plus the shared memory bus (to read the
    persona's current mood and publish changes to it) and returns a
    response. The orchestrator only ever talks to sub-agents through this
    interface, never their internals.
    """

    name: str

    @abc.abstractmethod
    def handle(self, request: AgentRequest, bus: SharedMemoryBus) -> AgentResponse:
        """Process `request` and return a response. Implementations may call
        `bus.read()` for the current mood and `bus.publish_delta` /
        `bus.publish_state` to report changes, identifying themselves with
        `self.name` as the publish `source`.
        """
        raise NotImplementedError


class Router:
    """Registers sub-agents by name and dispatches requests to them.

    The router owns no cognitive state itself -- that lives in the shared
    memory bus -- it only knows how to reach each registered agent.
    """

    def __init__(self, bus: SharedMemoryBus | None = None) -> None:
        self._bus = bus or SharedMemoryBus()
        self._agents: dict[str, SubAgent] = {}

    @property
    def bus(self) -> SharedMemoryBus:
        return self._bus

    def register(self, agent: SubAgent) -> None:
        if not agent.name:
            raise ValueError("agent.name must be a non-empty string")
        self._agents[agent.name] = agent

    def unregister(self, name: str) -> None:
        self._agents.pop(name, None)

    def agent_names(self) -> list[str]:
        return list(self._agents)

    def dispatch(self, name: str, request: AgentRequest) -> AgentResponse:
        """Send `request` to the single named agent and return its response."""
        try:
            agent = self._agents[name]
        except KeyError:
            raise KeyError(f"no sub-agent registered under name {name!r}") from None
        return agent.handle(request, self._bus)

    def dispatch_many(
        self, names: list[str], request: AgentRequest
    ) -> dict[str, AgentResponse]:
        """Send the same request to several named agents; return their
        responses keyed by agent name. Used by the orchestrator's synthesis
        step (e.g. querying "emotion" and "logic" for one input).
        """
        return {name: self.dispatch(name, request) for name in names}
