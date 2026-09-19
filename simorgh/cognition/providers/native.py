"""Native tool-calling dialects (stage 2 item 4).

The marker protocol (`cognition/parser.py`) stays the fallback for providers
without tool support. These helpers turn Sim's tool specs -- `{name,
description, input_schema}` from `tool.registered` -- into a provider's own
request shape, and its tool calls back into Sim's `{id, tool, args}`.

Nothing here decides WHEN native calling is used: that is the per-provider
`tool_dialect` switch (stage 2 item 9). Until it is flipped, no provider is
handed `tools`, and these paths are exercised by their fixtures only.
"""

from __future__ import annotations

import json
import re
from typing import Any

_ALLOWED = re.compile(r"[^A-Za-z0-9_-]")


def wire_name(tool: str) -> str:
    """A function name providers accept (`^[A-Za-z0-9_-]{1,64}$`). Sim's
    names carry `:` (`skill:greet`, `mcp:server:tool`); `:` becomes `__`."""
    return _ALLOWED.sub("_", tool.replace(":", "__"))[:64]


def names_back(tools: list[dict] | None) -> dict[str, str]:
    """wire name -> Sim's tool name, for decoding a reply."""
    return {wire_name(t["name"]): t["name"] for t in tools or () if t.get("name")}


def _schema(tool: dict) -> dict:
    schema = tool.get("input_schema") or {"type": "object"}
    return schema if schema.get("type") == "object" else {"type": "object"}


def openai_tools(tools: list[dict] | None) -> list[dict]:
    return [{"type": "function", "function": {"name": wire_name(t["name"]),
                                             "description": str(t.get("description") or "")[:1024],
                                             "parameters": _schema(t)}}
            for t in tools or () if t.get("name")]


def openai_calls(message: dict, back: dict[str, str]) -> tuple[dict, ...]:
    """`choices[0].message.tool_calls` as Sim's calls. Arguments that are
    not a JSON object come back as a call carrying `error`, never a crash:
    the session turns that into an error tool result the model can fix."""
    calls = []
    for raw in message.get("tool_calls") or ():
        fn = raw.get("function") or {}
        name = back.get(fn.get("name", ""), fn.get("name", ""))
        call: dict[str, Any] = {"id": raw.get("id") or "", "tool": name, "args": {}}
        text = fn.get("arguments")
        if isinstance(text, dict):
            call["args"] = text
        else:
            try:
                parsed = json.loads(text or "{}")
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                call["args"] = parsed
            else:
                call["error"] = f"malformed arguments for {name}: {str(text)[:200]!r}"
        calls.append(call)
    return tuple(calls)


def openai_messages(messages: list[dict]) -> list[dict]:
    """Chat messages as OpenAI wants them, keeping typed tool turns: an
    assistant message with `tool_calls`, and `tool` messages keyed by
    `tool_call_id` (stage 2 item 5 sends these)."""
    out = []
    for m in messages:
        role = m.get("role", "user")
        if role == "tool":
            out.append({"role": "tool", "tool_call_id": m.get("tool_call_id", ""), "content": str(m.get("content", ""))})
        elif m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": [
                {"id": c.get("id", ""), "type": "function",
                 "function": {"name": wire_name(c["tool"]), "arguments": json.dumps(c.get("args") or {})}}
                for c in m["tool_calls"]]})
        elif m.get("content"):
            out.append({"role": role, "content": m["content"]})
    return out or [{"role": "user", "content": ""}]


def gemini_declarations(tools: list[dict] | None) -> list[dict]:
    """Gemini `function_declarations`. Gemini's parameter schema is an
    OpenAPI subset; keys it rejects are dropped."""
    keep = ("type", "description", "properties", "required", "items", "enum", "format", "nullable")

    def clean(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        out = {}
        for key, value in node.items():
            if key not in keep:
                continue
            if key == "properties" and isinstance(value, dict):
                # Its keys are property NAMES, not schema keywords: keep every
                # one and clean each schema (filtering the names dropped
                # `path`, and Gemini refused `required: [path]`).
                out[key] = {name: clean(sub) for name, sub in value.items()}
            elif key == "items":
                out[key] = clean(value)
            else:
                out[key] = value
        return out

    decls = [{"name": wire_name(t["name"]), "description": str(t.get("description") or "")[:1024],
              "parameters": clean(_schema(t))} for t in tools or () if t.get("name")]
    return [{"function_declarations": decls}] if decls else []


def gemini_calls(response: Any, back: dict[str, str]) -> tuple[dict, ...]:
    calls = []
    for index, fc in enumerate(getattr(response, "function_calls", None) or ()):
        name = back.get(getattr(fc, "name", "") or "", getattr(fc, "name", "") or "")
        args = getattr(fc, "args", None)
        call: dict[str, Any] = {"id": getattr(fc, "id", None) or f"call_{index}", "tool": name,
                                "args": dict(args) if isinstance(args, dict) else {}}
        if args is not None and not isinstance(args, dict):
            call["error"] = f"malformed arguments for {name}"
        calls.append(call)
    return tuple(calls)


__all__ = ["gemini_calls", "gemini_declarations", "names_back", "openai_calls", "openai_messages", "openai_tools",
           "wire_name"]
