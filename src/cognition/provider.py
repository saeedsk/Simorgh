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

CapabilityRegistry also tracks an OutcomeStore of empirical
successes/failures per (provider, TaskType), so ties among providers that
support the same capability are broken by which one has actually performed
best for that kind of task rather than static registration order. The
default OutcomeStore is in-process only; a caller can substitute one backed
by long_term memory to make that history persist across sessions.

No real networked provider is wired in here (no credentials exist in this
environment, and this project doesn't fake integrations it can't run or
test). Adding one is a matter of implementing LLMProvider and registering
it ahead of the fallback in a CognitionRouter -- see docs/EVOLUTION.md,
"Resilience Doctrine."
"""

from __future__ import annotations

import abc
import concurrent.futures
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


@dataclass(frozen=True)
class EnsembleResponse:
    """Result of querying multiple providers concurrently for a single
    high-stakes decision (see CapabilityRegistry.complete_ensemble). `text`
    /`provider_name` are the reconciled answer a caller can use exactly
    like an LLMResponse; `responses` and `agreement` are kept alongside it
    so a caller that cares can inspect what each provider actually said
    and whether they agreed, rather than only seeing the reconciled
    outcome.
    """

    text: str
    provider_name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    responses: tuple[LLMResponse, ...] = field(default_factory=tuple)
    agreement: bool = True


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

    def register(self, provider: LLMProvider) -> None:
        """Add a provider at runtime, ahead of any existing fallback, so
        the orchestrator can bring a new backend (e.g. Gemini becoming
        reachable) into rotation mid-session without rebuilding the
        router from scratch.
        """
        insert_at = max(len(self._providers) - 1, 0)
        self._providers.insert(insert_at, provider)

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


class OutcomeStore(abc.ABC):
    """Tracks empirical success/failure outcomes per (provider, TaskType),
    so routing can be informed by observed performance rather than a
    static registration order. Implementations may persist this data in
    long_term memory so it survives across sessions; the default provided
    here (InMemoryOutcomeStore) does not.
    """

    @abc.abstractmethod
    def record(self, provider_name: str, task_type: TaskType, success: bool) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def confidence(self, provider_name: str, task_type: TaskType) -> float:
        """Empirical confidence in [0, 1] that `provider_name` succeeds at
        `task_type`. Pairs with no recorded outcomes should return a
        neutral prior (0.5) rather than 0, so an untried provider isn't
        permanently starved of a chance to prove itself.
        """
        raise NotImplementedError


class InMemoryOutcomeStore(OutcomeStore):
    """Default OutcomeStore: process-local counts, reset on restart. A
    persistent implementation (e.g. backed by long_term memory) can be
    substituted via CapabilityRegistry(outcome_store=...) without changing
    any routing logic.
    """

    def __init__(self) -> None:
        self._stats: dict[tuple[str, TaskType], tuple[int, int]] = {}

    def record(self, provider_name: str, task_type: TaskType, success: bool) -> None:
        successes, failures = self._stats.get((provider_name, task_type), (0, 0))
        if success:
            successes += 1
        else:
            failures += 1
        self._stats[(provider_name, task_type)] = (successes, failures)

    def confidence(self, provider_name: str, task_type: TaskType) -> float:
        successes, failures = self._stats.get((provider_name, task_type), (0, 0))
        total = successes + failures
        if total == 0:
            return 0.5
        return successes / total


class CapabilityRegistry:
    """Provider-agnostic index over a CognitionRouter's providers, keyed by
    Capability, so an orchestrator can ask "which backends support tool-use,
    streaming, or long-context reasoning" without depending on
    CognitionRouter's internals or provider priority order.
    """

    def __init__(self, router: CognitionRouter, outcome_store: OutcomeStore | None = None) -> None:
        self._router = router
        self._outcome_store = outcome_store or InMemoryOutcomeStore()

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
        """Available provider that currently supports `task_type`, chosen
        by empirical confidence for that task type (successes / total
        recorded outcomes, tracked via `record_outcome` / an OutcomeStore),
        with registration priority as the tiebreak for untried or equally
        confident providers. Does not invoke the provider -- lets the
        orchestrator inspect which one would be chosen (e.g. Claude vs.
        Gemini) before committing to a completion.
        """
        candidates = [p for p in self.providers_for(task_type.required_capability) if p.available()]
        if not candidates:
            return None
        return max(candidates, key=lambda p: self._outcome_store.confidence(p.name, task_type))

    def leaderboard(self, task_type: TaskType) -> list[tuple[LLMProvider, float]]:
        """All available providers that support `task_type`, ranked by
        empirical confidence (highest first) -- the full ranking
        `best_for_task` picks its winner from, so a caller (e.g. the
        orchestrator or a monitor backed by long_term memory) can see why
        a given provider was chosen instead of only the outcome.
        """
        candidates = [p for p in self.providers_for(task_type.required_capability) if p.available()]
        return sorted(
            ((p, self._outcome_store.confidence(p.name, task_type)) for p in candidates),
            key=lambda pair: pair[1],
            reverse=True,
        )

    def record_outcome(self, provider_name: str, task_type: TaskType, success: bool) -> None:
        """Record an empirical outcome for `provider_name` at `task_type`,
        so future `best_for_task` / `complete_for` calls route to whichever
        provider has actually performed best -- not just registration
        order. Callers (e.g. the orchestrator, informed by long_term
        memory) may also report outcomes judged after the fact, not just
        the ones `complete_for` records itself.
        """
        self._outcome_store.record(provider_name, task_type, success)

    def confidence_for(self, provider_name: str, task_type: TaskType) -> float:
        """Empirical confidence in [0, 1] for `provider_name` at `task_type`."""
        return self._outcome_store.confidence(provider_name, task_type)

    def complete_for(self, task_type: TaskType, prompt: str, **kwargs: Any) -> LLMResponse:
        """Negotiate a provider for `task_type` mid-session: try whichever
        available provider is empirically strongest for `task_type` (see
        `best_for_task`), recording the outcome so future calls can learn
        from it, and fall back to the router's normal starvation-proof
        ordering (ending in DeterministicFallbackProvider) if none
        currently qualifies or the chosen provider fails.
        """
        provider = self.best_for_task(task_type)
        if provider is not None:
            try:
                response = provider.complete(prompt, **kwargs)
            except ProviderUnavailable:
                self._outcome_store.record(provider.name, task_type, success=False)
            else:
                self._outcome_store.record(provider.name, task_type, success=True)
                return response
        return self._router.complete(prompt, **kwargs)

    def complete_ensemble(self, task_type: TaskType, prompt: str, **kwargs: Any) -> EnsembleResponse:
        """Query every available provider that supports `task_type` (e.g.
        Claude and Gemini both registered for LONG_CONTEXT_REFLECTION)
        concurrently, via threads, for a single high-stakes decision --
        instead of trusting whichever one provider `best_for_task` would
        have picked alone. If every provider's answer agrees, returns that
        answer. If they disagree, reconciles by empirical confidence (see
        OutcomeStore): the provider with the strongest track record for
        this TaskType wins, but the disagreement itself is preserved on
        the returned EnsembleResponse (`.agreement`, `.responses`) so a
        caller can escalate, log, or ask a human rather than silently
        trusting the tiebreak. Falls back to the router's normal
        starvation-proof `complete()` if no provider currently qualifies
        or all of them fail.
        """
        candidates = [p for p in self.providers_for(task_type.required_capability) if p.available()]
        if not candidates:
            response = self._router.complete(prompt, **kwargs)
            return EnsembleResponse(
                text=response.text,
                provider_name=response.provider_name,
                metadata=response.metadata,
                responses=(response,),
                agreement=True,
            )

        results: list[LLMResponse] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(candidates)) as executor:
            future_to_provider = {executor.submit(p.complete, prompt, **kwargs): p for p in candidates}
            for future in concurrent.futures.as_completed(future_to_provider):
                provider = future_to_provider[future]
                try:
                    results.append(future.result())
                except ProviderUnavailable:
                    self._outcome_store.record(provider.name, task_type, success=False)

        if not results:
            response = self._router.complete(prompt, **kwargs)
            return EnsembleResponse(
                text=response.text,
                provider_name=response.provider_name,
                metadata=response.metadata,
                responses=(response,),
                agreement=True,
            )

        for result in results:
            self._outcome_store.record(result.provider_name, task_type, success=True)

        texts = {result.text.strip() for result in results}
        agreement = len(texts) == 1
        if agreement:
            winner = results[0]
        else:
            winner = max(results, key=lambda r: self._outcome_store.confidence(r.provider_name, task_type))

        metadata = dict(winner.metadata)
        metadata["ensemble_agreement"] = agreement
        metadata["ensemble_providers"] = [result.provider_name for result in results]
        return EnsembleResponse(
            text=winner.text,
            provider_name=winner.provider_name,
            metadata=metadata,
            responses=tuple(results),
            agreement=agreement,
        )