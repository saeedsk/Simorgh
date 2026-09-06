"""Multi-provider cognition layer with a starvation-proof fallback.

The emotion and logic sub-agents already don't depend on any LLM -- they're
small, fast, rule-based, and always available. That's Simorgh's guaranteed
floor. CognitionRouter exists for agents that want richer reasoning on top
of that floor: it holds an ordered list of LLMProviders and fails over
between them, always keeping a DeterministicFallbackProvider last in line
so `complete()` is guaranteed to return something rather than raise or
hang -- Simorgh cannot be fully "starved" of the ability to respond, only
degraded to a simpler response.

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