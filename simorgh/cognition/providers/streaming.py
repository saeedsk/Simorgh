"""Streaming replies (stage 3 item 1).

A provider's `stream()` yields `Delta`s: text as it is generated, the start
of a tool call as soon as its name is known (so Voice can say "let me look"
before the arguments arrive), and -- once a call's arguments are complete --
the arguments, parsed. Malformed arguments are an `error` delta, never an
exception. The last delta is always `stop`, carrying usage when the
provider reports it.

`complete()` stays as it is: streaming is additive, and `collect()` turns a
stream back into a `ProviderResponse` for any caller that wants one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import AsyncIterator

from simorgh.contracts.protocols import ProviderResponse

TEXT, TOOL_START, TOOL_INPUT, STOP, ERROR = "text", "tool_use_start", "tool_use_input_json", "stop", "error"


@dataclass(frozen=True)
class Delta:
    kind: str
    text: str = ""
    tool_id: str = ""
    tool: str = ""
    args: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)


class ToolCallBuffer:
    """OpenAI-style streamed tool calls arrive as fragments keyed by index:
    an id and a name first, then pieces of the JSON arguments. This holds
    them until the stream says the reply is done."""

    def __init__(self, names_back: dict[str, str] | None = None) -> None:
        self._back = names_back or {}
        self._calls: dict[int, dict] = {}

    def feed(self, fragment: dict) -> Delta | None:
        index = int(fragment.get("index") or 0)
        call = self._calls.setdefault(index, {"id": "", "name": "", "args": "", "announced": False})
        fn = fragment.get("function") or {}
        call["id"] = fragment.get("id") or call["id"]
        call["name"] = fn.get("name") or call["name"]
        call["args"] += fn.get("arguments") or ""
        if call["name"] and not call["announced"]:
            call["announced"] = True
            return Delta(TOOL_START, tool_id=call["id"], tool=self._back.get(call["name"], call["name"]))
        return None

    def finish(self) -> list[Delta]:
        out = []
        for index in sorted(self._calls):
            call = self._calls[index]
            tool = self._back.get(call["name"], call["name"])
            try:
                args = json.loads(call["args"] or "{}")
            except ValueError:
                args = None
            if isinstance(args, dict):
                out.append(Delta(TOOL_INPUT, tool_id=call["id"], tool=tool, args=args))
            else:
                out.append(Delta(ERROR, tool_id=call["id"], tool=tool,
                                 text=f"malformed arguments for {tool}: {call['args'][:200]!r}"))
        return out


async def collect(stream: AsyncIterator[Delta], provider: str) -> ProviderResponse:
    """A whole reply from a stream: the text joined, tool calls as
    `{id, tool, args}` (or `error`), usage from the `stop` delta."""
    text: list[str] = []
    calls: list[dict] = []
    usage: dict = {}
    async for delta in stream:
        if delta.kind == TEXT:
            text.append(delta.text)
        elif delta.kind == TOOL_INPUT:
            calls.append({"id": delta.tool_id, "tool": delta.tool, "args": delta.args})
        elif delta.kind == ERROR and delta.tool:
            calls.append({"id": delta.tool_id, "tool": delta.tool, "args": {}, "error": delta.text})
        elif delta.kind == STOP:
            usage = delta.usage
    return ProviderResponse(text="".join(text), provider=provider, tool_calls=tuple(calls),
                            input_tokens=int(usage.get("input_tokens") or 0),
                            output_tokens=int(usage.get("output_tokens") or 0),
                            cost_usd=usage.get("cost_usd"))


__all__ = ["Delta", "ToolCallBuffer", "collect", "TEXT", "TOOL_START", "TOOL_INPUT", "STOP", "ERROR"]
