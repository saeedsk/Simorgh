"""The sidecars' hard cap, counted from what the provider says it used.

A sidecar calls a model through a library Sim does not control, so the
cap cannot live in Cognition's budget. It lives at the one place every
call passes: the client object (Graphiti takes an `AsyncOpenAI` it is
handed) or the module function (Cognee calls `litellm.acompletion` and
`litellm.aembedding` by attribute). `Meter.check()` runs before each call
and raises `CapReached` once the dollars counted so far, plus a reserve
for every call still in flight, reach the cap; `charge` reads the
response's `usage` afterwards. Both libraries fan calls out concurrently
(Graphiti through a semaphore of up to 20), so without the reserve every
call already started when the cap was crossed would land on top of it;
with it, the overshoot is only what the in-flight calls cost beyond their
estimate. A response that carries no `usage` is charged the estimate,
never nothing, and counted in `unmetered`. A cap that is not a finite
positive number stops the first call.

Embedding tokens are charged at the chat input price: dearer than any
embedding model, so the count can only over-state the bill.
"""

from __future__ import annotations

import functools
import inspect
import math
from dataclasses import dataclass


class CapReached(RuntimeError):
    """The sidecar spent its `--cap-usd`; nothing more is called."""


@dataclass
class Meter:
    cap_usd: float
    price_in: float                    # dollars per million input tokens
    price_out: float                   # dollars per million output tokens
    #: What one call is assumed to cost: reserved while it is in flight,
    #: and charged when its response says nothing about usage.
    reserve_in: int = 0
    reserve_out: int = 0
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    inflight: int = 0
    unmetered: int = 0                 # responses with no usage, charged the reserve

    @property
    def usd(self) -> float:
        return (self.tokens_in * self.price_in + self.tokens_out * self.price_out) / 1_000_000

    @property
    def reserve_usd(self) -> float:
        return (self.reserve_in * self.price_in + self.reserve_out * self.price_out) / 1_000_000

    def check(self) -> None:
        if not (math.isfinite(self.cap_usd) and self.cap_usd > 0):
            raise CapReached(f"the cap is {self.cap_usd!r}; a sidecar needs a finite cap above zero")
        committed = self.usd + self.inflight * self.reserve_usd
        if committed >= self.cap_usd:
            raise CapReached(f"spent ${self.usd:.4f} (+{self.inflight} calls in flight) of a "
                             f"${self.cap_usd:.2f} cap after {self.calls} calls")

    def charge(self, response) -> None:
        self.calls += 1
        usage = _get(response, "usage")
        tokens_in = int(_get(usage, "prompt_tokens") or _get(usage, "input_tokens") or 0)
        tokens_out = int(_get(usage, "completion_tokens") or _get(usage, "output_tokens") or 0)
        if not (tokens_in or tokens_out):
            # Nothing said is not nothing spent: a cap fed zeros never stops.
            self.unmetered += 1
            tokens_in, tokens_out = self.reserve_in, self.reserve_out
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out

    def snapshot(self) -> tuple[int, int, int, float]:
        return self.calls, self.tokens_in, self.tokens_out, self.usd


def _get(obj, name: str):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def metered(fn, meter: Meter):
    """`fn` (sync or async) with the cap checked before and usage charged after."""
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def _async(*args, **kwargs):
            meter.check()
            meter.inflight += 1
            try:
                response = await fn(*args, **kwargs)
            finally:
                meter.inflight -= 1
            meter.charge(response)
            return response
        return _async

    @functools.wraps(fn)
    def _sync(*args, **kwargs):
        meter.check()
        meter.inflight += 1
        try:
            response = fn(*args, **kwargs)
        except BaseException:
            meter.inflight -= 1
            raise
        if inspect.isawaitable(response):
            async def _later():
                try:
                    result = await response
                finally:
                    meter.inflight -= 1
                meter.charge(result)
                return result
            return _later()
        meter.inflight -= 1
        meter.charge(response)
        return response
    return _sync


#: The methods an OpenAI-style client spends money through.
_SPENDING = frozenset({"create", "parse"})


class MeteredClient:
    """An OpenAI-style client whose every `...create`/`...parse` is metered.

    A proxy over attribute chains (`client.chat.completions.create`,
    `client.embeddings.create`, `client.beta.chat.completions.parse`,
    `client.responses.parse`), so whatever path the library takes to spend
    money, it passes `Meter.check` first.
    """

    def __init__(self, target, meter: Meter) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_meter", meter)

    def __getattr__(self, name: str):
        value = getattr(self._target, name)
        if name in _SPENDING and callable(value):
            return metered(value, self._meter)
        if isinstance(value, (str, bytes, int, float, bool, type(None))) or inspect.ismethod(value) \
                or inspect.isfunction(value) or isinstance(value, type):
            return value
        return MeteredClient(value, self._meter)


__all__ = ["CapReached", "Meter", "MeteredClient", "metered"]
