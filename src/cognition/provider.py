"""Multi-provider cognition layer with a starvation-proof fallback.

The emotion and logic sub-agents already don't depend on any LLM -- they're
small, fast, rule-based, and always available. That's Simorgh's guaranteed
floor. CognitionRouter exists for agents that want richer reasoning on top
of that floor: it holds an ordered list of LLMProviders and fails over
between them, always keeping a DeterministicFallbackProvider last in line
so `complete()` is guaranteed to return something rather than raise or
hang -- Simorgh cannot be fully "starved" of the ability to respond, only
degraded to a simpler response.

On top of that failover, CapabilityRegistry gives the orchestrator a
provider-agnostic negotiation layer: providers declare which Capabilities
they support (tool use, streaming, long context, ...), TaskType maps a
kind of work to the Capability it needs, and `complete_for(task_type, ...)`
picks whichever registered provider (e.g. Claude vs. Gemini) currently
supports and is available for that capability -- mid-session, per call --
before falling back to the router's normal ordering. This lets the
orchestrator switch providers based on what a task needs rather than a
single static provider choice.

No real networked provider is wired in here (no credentials exist in this
environment, and this project doesn't fake integrations it can't run or
test). Adding one is a matter of implementing LLMProvider and registering
it ahead of the fallback in a CognitionRouter -- see docs/EVOLUTION.md,
"Resilience Doctrine."
"""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass, field
from typing import Any


class ProviderUnavailable(Exception):
    """Raised by an LLMProvider that cannot currently serve a request
    (network error, rate limit, missing credentials, etc.). CognitionRouter
    catches this and tries the next provider.
    """


class Capability(enum.Enum):
    """A named ability a cognition backend may or may not support, so the
    orchestrator can route tasks to a provider that actually supports what
    a task needs instead of discovering a mismatch at call time.
    """

    TOOL_USE = "tool_use"
    STREAMING = "streaming"
    LONG_CONTEXT = "long_context"


class TaskType(enum.Enum):
    """A category of work the orchestrator wants performed, mapped to the
    Capability a provider must have to serve it well. This is the seam
    that lets the orchestrator ask for e.g. "long-context reflection" or
    "fast tool use" and get routed to whichever registered provider
    actually supports that, without hardcoding provider names or relying
    on static priority order.
    """

    TOOL_USE = "tool_use"
    LONG_CONTEXT_REFLECTION = "long_context_reflection"
    STREAMING_RESPONSE = "streaming_response"

    @property
    def required_capability(self) -> Capability:
        return _TASK_TYPE_CAPABILITY[self]


_TASK_TYPE_CAPABILITY: dict[TaskType, Capability] = {
    TaskType.TOOL_USE: Capability.TOOL_USE,
    TaskType.LONG_CONTEXT_REFLECTION: Capability.LONG_CONTEXT,
    TaskType.STREAMING_RESPONSE: Capability.STREAMING,
}


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMProvider(abc.ABC):
    """Interface every cognition backend implements."""

    name: str
    capabilities: frozenset[Capability] = frozenset()

    @abc.abstractmethod
    def available(self) -> bool:
        """Cheap, local check of whether this provider is worth trying
        right now (e.g. an API key is configured). Does not guarantee the
        following `complete()` call will succeed.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """Return a completion for `prompt`, or raise ProviderUnavailable."""
        raise NotImplementedError

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities


class DeterministicFallbackProvider(LLMProvider):
    """Always available, makes no network call, and cannot fail. This is
    the floor CognitionRouter always keeps under every real provider: a
    response Simorgh can always produce regardless of connectivity, quota,
    or credentials.
    """

    name = "deterministic_fallback"
    capabilities: frozenset[Capability] = frozenset()

    def available(self) -> bool:
        return True

    def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        text = (
            "[offline reasoning -- no LLM provider was reachable] "
            f"Noted: {prompt.strip()}"
        )
        return LLMResponse(text=text, provider_name=self.name, metadata={"degraded": True})


class CognitionRouter:
    """Tries each registered provider in order, falling back on the next
    when one is unavailable or raises. Tracks simple health stats so a
    caller (e.g. HealthMonitor) can see which providers are actually
    reachable right now.
    """

    def __init__(self, providers: list[LLMProvider] | None = None) -> None:
        self._providers = providers or [DeterministicFallbackProvider()]
        self._successes: dict[str, int] = {}
        self._failures: dict[str, int] = {}

    @property
    def providers(self) -> list[LLMProvider]:
        """Registered providers in priority order (read-only view)."""
        return list(self._providers)

    def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        last_error: Exception | None = None
        for provider in self._providers:
            if not provider.available():
                continue
            try:
                response = provider.complete(prompt, **kwargs)
            except ProviderUnavailable as exc:
                last_error = exc
                self._failures[provider.name] = self._failures.get(provider.name, 0) + 1
                continue
            self._successes[provider.name] = self._successes.get(provider.name, 0) + 1
            return response

        raise ProviderUnavailable(
            "no provider could serve this request "
            f"(last error: {last_error!r}); this should be unreachable if a "
            "DeterministicFallbackProvider is registered"
        )

    def health(self) -> dict[str, dict[str, int]]:
        names = {p.name for p in self._providers}
        return {
            name: {
                "successes": self._successes.get(name, 0),
                "failures": self._failures.get(name, 0),
            }
            for name in names
        }

    def providers_with_capability(self, capability: Capability) -> list[LLMProvider]:
        """Return registered providers that declare support for `capability`,
        in priority order, so a caller can route a task to one that can
        actually handle it (e.g. tool-use or long-context reasoning) instead
        of discovering the mismatch after a failed `complete()` call.
        """
        return [p for p in self._providers if p.supports(capability)]


class CapabilityRegistry:
    """Provider-agnostic index over a CognitionRouter's providers, keyed by
    Capability, so an orchestrator can ask "which backends support tool-use,
    streaming, or long-context reasoning" without depending on
    CognitionRouter's internals or provider priority order.
    """

    def __init__(self, router: CognitionRouter) -> None:
        self._router = router

    def providers_for(self, capability: Capability) -> list[LLMProvider]:
        """Providers (in priority order) that support `capability`."""
        return self._router.providers_with_capability(capability)

    def best_for(self, capability: Capability) -> LLMProvider | None:
        """Highest-priority available provider that supports `capability`,
        or None if no registered provider currently supports and is
        available for it.
        """
        for provider in self.providers_for(capability):
            if provider.available():
                return provider
        return None

    def supported_capabilities(self) -> frozenset[Capability]:
        """Union of all capabilities declared by any registered provider."""
        caps: set[Capability] = set()
        for provider in self._router.providers:
            caps |= provider.capabilities
        return frozenset(caps)

    def best_for_task(self, task_type: TaskType) -> LLMProvider | None:
        """Highest-priority available provider that currently supports
        `task_type`, without invoking it -- lets the orchestrator inspect
        which provider would be chosen (e.g. Claude vs. Gemini) before
        committing to a completion, so it can query and switch mid-session
        based on the kind of work rather than a static provider choice.
        """
        return self.best_for(task_type.required_capability)

    def complete_for(self, task_type: TaskType, prompt: str, **kwargs: Any) -> LLMResponse:
        """Negotiate a provider for `task_type` mid-session: try the
        highest-priority available provider that supports the capability
        the task requires, and fall back to the router's normal
        starvation-proof ordering (ending in DeterministicFallbackProvider)
        if none currently qualifies or the chosen provider fails.
        """
        provider = self.best_for(task_type.required_capability)
        if provider is not None:
            try:
                return provider.complete(prompt, **kwargs)
            except ProviderUnavailable:
                pass
        return self._router.complete(prompt, **kwargs)