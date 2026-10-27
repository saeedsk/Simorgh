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
not one the model made. So is a block whose close never came (a reply cut
off mid-thought: from the open tag to the end) and one whose open tag the
chat template wrote (everything up to a lone close tag).

Two rules forge leaves to its caller are enforced here: a call is accepted
only for a tool offered to this session, and only when its arguments are
(or, for an OpenAI-style string, parse to) a JSON object. Prose that names
a tool without one of these shapes is never a call.

Differences from forge, all narrowing or robustness: the brace scan
respects JSON strings (forge's strategy 1 and 2 did not), so a `}` inside
an argument cannot end the object early; a tool name matches the offered
one case-insensitively and is returned as offered; an object with no
`args`/`arguments` is a call with no arguments only when it holds nothing
else (`{"name": "fetch", "city": "Paris"}` is not `fetch({})`); an
unclosed think block is thinking too; and the work is bounded -- a
degenerate reply that repeats an opening `{` or `<function=` thousands of
times (small models loop) gives up after a few unclosed scans instead of
rescanning to the end from every one. Stdlib only.
"""

from __future__ import annotations

import json
import re

THINK_TAG_RE = re.compile(r"\[THINK\](.*?)\[/THINK\]|<think>(.*?)</think>", re.DOTALL)
_THINK_CLOSE_RE = re.compile(r"\[/THINK\]|</think>")
_THINK_OPEN_RE = re.compile(r"\[THINK\]|<think>")

# Scans from an opening brace that never closes, per strategy, before the
# strategy stops looking: each one reads to the end of the reply, so without
# a cap a reply of N unclosed braces costs N times its length.
_MAX_UNCLOSED = 16
# Keys a JSON call may carry besides its name when it has no `args`.
_CALL_KEYS = frozenset({"tool", "name", "type", "id"})

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?")
_REHEARSAL_RE = re.compile(r"(\w+)\[ARGS\]\s*(?=\{)")
# Pattern adapted (by forge) from Qwen's reference parser:
# huggingface.co/Qwen/Qwen3-Coder-480B-A35B-Instruct/blob/main/qwen3coder_tool_parser.py
_QWEN_FUNCTION_RE = re.compile(r"<function=([^>\s]+)>(.*?)</function>", re.DOTALL)
_QWEN_PARAMETER_RE = re.compile(
    r"<parameter=([^>\s]+)>(.*?)(?:</parameter>|(?=<parameter=)|(?=</function>)|$)", re.DOTALL)
_MISTRAL_BRACKET_RE = re.compile(r"\[TOOL_CALLS\](\w+)\s*(?=\{)")
# `whole=True`: one fence around the entire reply, and what may sit
# between the calls of a reply that is nothing else.
_WHOLE_FENCE_RE = re.compile(r"^```[\w-]*[ \t]*\n?(.*?)\n?[ \t]*```$", re.DOTALL)
_GLUE_RE = re.compile(r"</?tool_call>|[\s,\[\]]")


def strip_think(text: str) -> str:
    """`text` without its think blocks, stripped. A lone close tag ends
    thinking the template opened (everything before it goes); an open tag
    that never closes is thinking to the end."""
    text = THINK_TAG_RE.sub("", text)
    closes = list(_THINK_CLOSE_RE.finditer(text))
    if closes:
        text = text[closes[-1].end():]
    opened = _THINK_OPEN_RE.search(text)
    if opened:
        text = text[:opened.start()]
    return text.strip()


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


# Each strategy returns `(text it scanned, [(call, start, end)])`, the span
# being where the call sits in that text, so `whole=True` can tell a reply
# that is only calls from one that quotes a call inside prose.
_Found = list[tuple[dict, int, int]]


def _json_calls(text: str, offered: dict[str, str]) -> tuple[str, _Found]:
    """Strategy 1: JSON objects naming an offered tool (fences removed)."""
    cleaned = _FENCE_RE.sub("", text).replace("```", "")
    found: _Found = []
    unclosed = 0
    i = 0
    while i < len(cleaned):
        if cleaned[i] != "{":
            i += 1
            continue
        data, end = _json_object(cleaned, i)
        if end is None:
            unclosed += 1
            if unclosed >= _MAX_UNCLOSED:
                break
            i += 1
            continue
        if data is not None:
            name = data.get("tool") or data.get("name")
            tool = offered.get(name.lower()) if isinstance(name, str) else None
            if "args" in data or "arguments" in data:
                raw = data["args"] if "args" in data else data["arguments"]
                args = _as_object(raw if raw is not None else {})
            else:
                # No arguments named: a no-argument call only when nothing
                # else is in the object, or its other keys would be lost.
                args = {} if set(data) <= _CALL_KEYS else None
            if tool and args is not None:
                found.append((_call(tool, args), i, end))
                i = end
                continue
        # Not a call (or not valid JSON): forge steps over the whole object,
        # so a call nested in someone else's object is not lifted out.
        i = end
    return cleaned, found


def _bracketed_calls(pattern: re.Pattern, text: str, offered: dict[str, str]) -> tuple[str, _Found]:
    """Strategies 2 and 4: `name` from `pattern`, then one JSON object."""
    found: _Found = []
    unclosed = 0
    for match in pattern.finditer(text):
        tool = offered.get(match.group(1).lower())
        if not tool:
            continue
        args, end = _json_object(text, match.end())
        if end is None:
            unclosed += 1
            if unclosed >= _MAX_UNCLOSED:
                break
        if args is not None:
            found.append((_call(tool, args), match.start(), end))
    return text, found


def _qwen_calls(text: str, offered: dict[str, str]) -> tuple[str, _Found]:
    """Strategy 3: Qwen Coder XML. One leading and one trailing newline
    are stripped from each value, as Qwen's reference parser does."""
    found: _Found = []
    # Only up to the last close tag: an open tag after it can never match,
    # and searching from each one to the end is quadratic.
    last = text.rfind("</function>")
    if last < 0:
        return text, found
    for fn in _QWEN_FUNCTION_RE.finditer(text, 0, last + len("</function>")):
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
        found.append((_call(tool, args), fn.start(), fn.end()))
    return text, found


def _unfence(text: str) -> str:
    """`text` without one code fence around the whole of it."""
    match = _WHOLE_FENCE_RE.match(text)
    return match.group(1).strip() if match else text


def _only_calls(scanned: str, found: _Found) -> bool:
    """Whether `scanned` is nothing but the calls in `found`: what is
    left between them is whitespace, `<tool_call>` tags, or the commas
    and brackets of a JSON list of calls."""
    rest, at = [], 0
    for _, start, end in sorted(found, key=lambda f: f[1]):
        rest.append(scanned[at:start])
        at = max(at, end)
    rest.append(scanned[at:])
    return not _GLUE_RE.sub("", "".join(rest))


def rescue_tool_calls(text: str, offered, *, whole: bool = False) -> tuple[dict, ...]:
    """The tool calls in `text` for tools in `offered`, first one first, or
    () when there are none. Each is `{"tool", "args", "rescued": True}`:
    the shape a native call has, without an `id`, because the model never
    issued one (a session keeps an id-less call in the text transcript).

    `whole=True` is a conversation's rule (a `purpose: "chat"` think, which
    is the chat and voice_chat agents): the reply, without its think blocks
    and one code fence around all of it, must be nothing but the call(s).
    "Sure, I'd run {...}" there is an answer that quotes a call -- the
    person asked what it would do, or is being shown -- not a request to
    run one. A task's reply keeps forge's rule: a call inside prose counts."""
    names = {str(n).lower(): str(n) for n in offered or () if n}
    if not names or not text:
        return ()
    cleaned = strip_think(text)
    if whole:
        cleaned = _unfence(cleaned)
    if not cleaned:
        return ()
    scanned, found = _json_calls(cleaned, names)
    for strategy in (lambda t, n: _bracketed_calls(_REHEARSAL_RE, t, n), _qwen_calls,
                     lambda t, n: _bracketed_calls(_MISTRAL_BRACKET_RE, t, n)):
        if found:
            break
        scanned, found = strategy(cleaned, names)
    if whole and found and not _only_calls(scanned, found):
        return ()
    return tuple(call for call, _, _ in found)


__all__ = ["THINK_TAG_RE", "rescue_tool_calls", "strip_think"]
