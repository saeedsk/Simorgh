"""Rescue parsing (stage 16 item 1): tool calls a model wrote as text in a
syntax other than the one it was asked for.

Ported from forge (github.com/antoinezambelli/forge, MIT licence,
copyright 2025-2026 Antoine Zambelli): `src/forge/prompts/templates.py`
(`rescue_tool_call`, `extract_tool_call`, `_parse_qwen_xml_tool_calls`,
`_parse_mistral_bracket_tool_calls`) and `src/forge/prompts/think_tags.py`.
On forge's own suite this layer, with its validator and nudges, is part of
what took small models from roughly half their scenarios to nearly all.

A reply reaches here only when nothing the dialect recognises was found:
no typed call from a native provider and no marker line (`parser.py`).
The strategies, tried in order, each only when the earlier ones found
nothing (forge's precedence, so one reply is never counted twice):

1. a JSON object `{"tool": name, "args": {...}}` or `{"name": name,
   "arguments": {...}}`, bare, inside a code fence, inside
   `<tool_call>...</tool_call>`, or embedded in a sentence;
2. the rehearsal syntax reasoning models write in their thinking,
   `name[ARGS]{...}`;
3. Qwen Coder's XML, `<function=name><parameter=key>value</parameter>
   </function>` (values are strings, as Qwen's reference parser leaves
   them; the tool's schema coerces);
4. Mistral's bracket tag, `[TOOL_CALLS]name{...}`.

Think blocks (`<think>...</think>`, `[THINK]...[/THINK]`) are removed
first: the call may sit after them, and a call rehearsed inside them is
not one the model made.

Two rules forge leaves to its caller are enforced here: a call is accepted
only for a tool offered to this session, and only when its arguments are
(or, for an OpenAI-style string, parse to) a JSON object. Prose that names
a tool without one of these shapes is never a call.

Differences from forge, all narrowing or robustness: the brace scan
respects JSON strings (forge's strategy 1 and 2 did not), so a `}` inside
an argument cannot end the object early; a tool name matches the offered
one case-insensitively and is returned as offered. Stdlib only.
"""

from __future__ import annotations

import json
import re

THINK_TAG_RE = re.compile(r"\[THINK\](.*?)\[/THINK\]|<think>(.*?)</think>", re.DOTALL)

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?")
_REHEARSAL_RE = re.compile(r"(\w+)\[ARGS\]\s*(?=\{)")
# Pattern adapted (by forge) from Qwen's reference parser:
# huggingface.co/Qwen/Qwen3-Coder-480B-A35B-Instruct/blob/main/qwen3coder_tool_parser.py
_QWEN_FUNCTION_RE = re.compile(r"<function=([^>\s]+)>(.*?)</function>", re.DOTALL)
_QWEN_PARAMETER_RE = re.compile(
    r"<parameter=([^>\s]+)>(.*?)(?:</parameter>|(?=<parameter=)|(?=</function>)|$)", re.DOTALL)
_MISTRAL_BRACKET_RE = re.compile(r"\[TOOL_CALLS\](\w+)\s*(?=\{)")


def strip_think(text: str) -> str:
    """`text` without its think blocks, stripped."""
    return THINK_TAG_RE.sub("", text).strip()


def _object_end(text: str, start: int) -> int | None:
    """The index just past the `}` closing the `{` at `start`, skipping
    braces inside JSON strings; None when it never closes."""
    depth = 0
    in_string = escape = False
    for j in range(start, len(text)):
        ch = text[j]
        if escape:
            escape = False
        elif ch == "\\":
            escape = in_string
        elif ch == '"':
            in_string = not in_string
        elif in_string:
            continue
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return j + 1
    return None


def _as_object(value) -> dict | None:
    """`value` as a dict: itself, or a JSON string that holds an object
    (OpenAI's `arguments` is often one). Anything else is None."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def _json_object(text: str, start: int) -> tuple[dict | None, int | None]:
    end = _object_end(text, start)
    if end is None:
        return None, None
    try:
        data = json.loads(text[start:end])
    except ValueError:
        return None, end
    return (data if isinstance(data, dict) else None), end


def _call(name: str, args: dict) -> dict:
    return {"tool": name, "args": args, "rescued": True}


def _json_calls(text: str, offered: dict[str, str]) -> list[dict]:
    """Strategy 1: JSON objects naming an offered tool (fences removed)."""
    cleaned = _FENCE_RE.sub("", text).replace("```", "")
    found: list[dict] = []
    i = 0
    while i < len(cleaned):
        if cleaned[i] != "{":
            i += 1
            continue
        data, end = _json_object(cleaned, i)
        if end is None:
            i += 1
            continue
        if data is not None:
            name = data.get("tool") or data.get("name")
            tool = offered.get(name.lower()) if isinstance(name, str) else None
            raw = data["args"] if "args" in data else data.get("arguments", {})
            args = _as_object(raw if raw is not None else {})
            if tool and args is not None:
                found.append(_call(tool, args))
                i = end
                continue
        # Not a call (or not valid JSON): forge steps over the whole object,
        # so a call nested in someone else's object is not lifted out.
        i = end
    return found


def _bracketed_calls(pattern: re.Pattern, text: str, offered: dict[str, str]) -> list[dict]:
    """Strategies 2 and 4: `name` from `pattern`, then one JSON object."""
    found: list[dict] = []
    for match in pattern.finditer(text):
        tool = offered.get(match.group(1).lower())
        if not tool:
            continue
        args, _end = _json_object(text, match.end())
        if args is not None:
            found.append(_call(tool, args))
    return found


def _qwen_calls(text: str, offered: dict[str, str]) -> list[dict]:
    """Strategy 3: Qwen Coder XML. One leading and one trailing newline
    are stripped from each value, as Qwen's reference parser does."""
    found: list[dict] = []
    for fn in _QWEN_FUNCTION_RE.finditer(text):
        tool = offered.get(fn.group(1).strip().lower())
        if not tool:
            continue
        args: dict[str, str] = {}
        for param in _QWEN_PARAMETER_RE.finditer(fn.group(2)):
            value = param.group(2)
            if value.startswith("\n"):
                value = value[1:]
            if value.endswith("\n"):
                value = value[:-1]
            args[param.group(1).strip()] = value
        found.append(_call(tool, args))
    return found


def rescue_tool_calls(text: str, offered) -> tuple[dict, ...]:
    """The tool calls in `text` for tools in `offered`, first one first, or
    () when there are none. Each is `{"tool", "args", "rescued": True}`:
    the shape a native call has, without an `id`, because the model never
    issued one (a session keeps an id-less call in the text transcript)."""
    names = {str(n).lower(): str(n) for n in offered or () if n}
    if not names or not text:
        return ()
    cleaned = strip_think(text)
    if not cleaned:
        return ()
    found = _json_calls(cleaned, names)
    if not found:
        found = _bracketed_calls(_REHEARSAL_RE, cleaned, names)
    if not found:
        found = _qwen_calls(cleaned, names)
    if not found:
        found = _bracketed_calls(_MISTRAL_BRACKET_RE, cleaned, names)
    return tuple(found)


__all__ = ["THINK_TAG_RE", "rescue_tool_calls", "strip_think"]
