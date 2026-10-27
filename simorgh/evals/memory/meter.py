"""The sidecars' hard cap, counted from what the provider says it used.

A sidecar calls a model through a library Sim does not control, so the
cap cannot live in Cognition's budget. It lives at the one place every
call passes: the client object (Graphiti takes an `AsyncOpenAI` it is
handed) or the module function (Cognee calls `litellm.acompletion` and
`litellm.aembedding` by attribute). `Meter.check()` runs before each call
and raises `CapReached` once the dollars counted so far reach the cap;
`charge` reads the response's `usage` afterwards. So the overshoot is at
most one call -- the one already in flight when the cap was crossed.

Embedding tokens are charged at the chat input price: dearer than any
embedding model, so the count can only over-state the bill.
"""

from __future__ import annotations

import functools
import inspect
from dataclasses import dataclass


class CapReached(RuntimeError):
    """The sidecar spent its `--cap-usd`; nothing more is called."""


@dataclass
class Meter:
    cap_usd: float
    price_in: float                    # dollars per million input tokens
    price_out: float                   # dollars per million output tokens
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def usd(self) -> float:
        return (self.tokens_in * self.price_in + self.tokens_out * self.price_out) / 1_000_000

    def check(self) -> None:
        if self.usd >= self.cap_usd:
            raise CapReached(f"spent ${self.usd:.4f} of a ${self.cap_usd:.2f} cap after {self.calls} calls")

    def charge(self, response) -> None:
        self.calls += 1
        usage = _get(response, "usage")
        if usage is None:
            return
        self.tokens_in += int(_get(usage, "prompt_tokens") or _get(usage, "input_tokens") or 0)
        self.tokens_out += int(_get(usage, "completion_tokens") or _get(usage, "output_tokens") or 0)

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
            response = await fn(*args, **kwargs)
            meter.charge(response)
            return response
        return _async

    @functools.wraps(fn)
    def _sync(*args, **kwargs):
        meter.check()
        response = fn(*args, **kwargs)
        if inspect.isawaitable(response):
            async def _later():
                result = await response
                meter.charge(result)
                return result
            return _later()
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
