"""Tool-call tag and JSON argument parser for raw model output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


class ToolCallParseError(ValueError):
    """Raised when strict tool call parsing fails."""
    pass


@dataclass
class ToolCall:
    """Represents a single parsed tool call."""
    name: str
    arguments: Dict[str, Any]
    id: Optional[str] = None
    raw: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result: Dict[str, Any] = {
            "name": self.name,
            "arguments": self.arguments,
        }
        if self.id is not None:
            result["id"] = self.id
        return result


@dataclass
class ParseResult:
    """Result of parsing raw model output."""
    text: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        """True if any tool calls were successfully parsed."""
        return len(self.tool_calls) > 0

    @property
    def has_errors(self) -> bool:
        """True if any parsing errors occurred."""
        return len(self.errors) > 0


DEFAULT_TAGS = (
    "tool_call",
    "tool_calls",
    "tool_use",
    "tool_uses",
    "function_call",
    "function_calls",
    "invoke",
    "action",
    "call",
    "tool",
)


def _strip_markdown_fences(content: str) -> str:
    """Remove markdown code block fences if present."""
    s = content.strip()
    fence_pattern = re.compile(
        r"^```(?:[a-zA-Z0-9_-]+)?\s*\n?(.*?)\n?```$",
        re.DOTALL
    )
    m = fence_pattern.match(s)
    if m:
        return m.group(1).strip()
    return s


def _repair_json_text(text: str) -> str:
    """Apply common heuristics to fix slightly malformed JSON from LLMs."""
    s = text.strip()
    # Remove single-line comments // ...
    s = re.sub(r"(?m)^\s*//.*?$", "", s)
    # Remove trailing commas before } or ]
    s = re.sub(r",\s*([\]}])", r"\1", s)
    # Replace python booleans/None if unquoted
    s = re.sub(r"\bTrue\b", "true", s)
    s = re.sub(r"\bFalse\b", "false", s)
    s = re.sub(r"\bNone\b", "null", s)
    return s


def _clean_and_parse_json(text: str) -> Any:
    """Parse JSON with multiple fallback repair strategies."""
    cleaned = _strip_markdown_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    repaired = _repair_json_text(cleaned)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Try single-to-double quote conversion if it looks like Python dict
    if ("'" in repaired and '"' not in repaired) or re.search(r"'(?:[a-zA-Z0-9_]+)'\s*:", repaired):
        converted = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", r'"\1"', repaired)
        try:
            return json.loads(converted)
        except json.JSONDecodeError:
            pass

    # Try raw_decode
    try:
        decoder = json.JSONDecoder()
        stripped = cleaned.lstrip()
        obj, _ = decoder.raw_decode(stripped)
        return obj
    except json.JSONDecodeError:
        pass

    raise json.JSONDecodeError("Failed to parse JSON", text, 0)


def _extract_balanced_json(text: str, start_pos: int) -> Optional[Tuple[str, int]]:
    """Extract balanced JSON object or array starting at or after start_pos."""
    idx = start_pos
    while idx < len(text) and text[idx] in " \t\r\n":
        idx += 1

    # Check for optional markdown code fence
    fence_match = re.match(r"```(?:[a-zA-Z0-9_-]+)?\s*", text[idx:])
    has_fence = False
    if fence_match:
        has_fence = True
        idx += fence_match.end()

    if idx >= len(text) or text[idx] not in "{[":
        return None

    stack: List[str] = []
    in_string = False
    escape = False
    start_json = idx

    for i in range(idx, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            if in_string:
                escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if not stack or stack[-1] != c:
                return None
            stack.pop()
            if not stack:
                end_pos = i + 1
                if has_fence:
                    trailing_fence = re.match(r"\s*```", text[end_pos:])
                    if trailing_fence:
                        end_pos += trailing_fence.end()
                return text[start_json:i+1], end_pos

    return None


def _parse_xml_attributes(attr_str: str) -> Dict[str, str]:
    """Extract key-value attributes from tag attribute string."""
    attrs: Dict[str, str] = {}
    if not attr_str:
        return attrs

    # Format 1: =name or :name (e.g. <function=get_weather> or <call:get_weather>)
    bare_match = re.match(r"^\s*[:=]\s*([a-zA-Z0-9_.-]+)", attr_str)
    if bare_match:
        attrs["name"] = bare_match.group(1)

    # Format 2: key="value" or key='value' or key=value
    pattern = re.compile(
        r'([a-zA-Z0-9_:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))'
    )
    for m in pattern.finditer(attr_str):
        k = m.group(1)
        v = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
        attrs[k] = v

    return attrs


def _parse_xml_key_values(body: str) -> Dict[str, Any]:
    """Extract simple <key>value</key> tags as a dictionary."""
    result: Dict[str, Any] = {}
    tag_pattern = re.compile(r"<([a-zA-Z0-9_]+)>(.*?)</\1>", re.DOTALL)
    for m in tag_pattern.finditer(body):
        k = m.group(1)
        v = m.group(2).strip()
        if v.lower() == "true":
            result[k] = True
        elif v.lower() == "false":
            result[k] = False
        elif v.lower() in ("null", "none"):
            result[k] = None
        elif re.match(r"^-?\d+$", v):
            result[k] = int(v)
        elif re.match(r"^-?\d+\.\d+$", v):
            result[k] = float(v)
        else:
            try:
                result[k] = json.loads(v)
            except Exception:
                result[k] = v
    return result


def _normalize_arguments(args: Any) -> Dict[str, Any]:
    """Ensure arguments is a dict; parse string arguments if necessary."""
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        s = args.strip()
        if not s:
            return {}
        try:
            parsed = _clean_and_parse_json(s)
            if isinstance(parsed, dict):
                return parsed
            return {"_arg": parsed}
        except Exception:
            return {"_raw": args}
    if args is None:
        return {}
    if isinstance(args, (list, int, float, bool)):
        return {"_arg": args}
    return dict(args) if hasattr(args, "items") else {}


def _extract_tool_calls_from_data(
    data: Any,
    default_name: Optional[str] = None,
    default_id: Optional[str] = None,
    raw: str = "",
) -> List[ToolCall]:
    """Convert parsed JSON / structure into one or more ToolCall instances."""
    results: List[ToolCall] = []

    if isinstance(data, list):
        for item in data:
            results.extend(_extract_tool_calls_from_data(item, default_name, default_id, raw))
        return results

    if not isinstance(data, dict):
        if default_name:
            results.append(ToolCall(
                name=default_name,
                arguments=_normalize_arguments(data),
                id=default_id,
                raw=raw,
            ))
        return results

    # Check for nested OpenAI style: {"function": {"name": ..., "arguments": ...}}
    if "function" in data and isinstance(data["function"], dict):
        fn = data["function"]
        name = fn.get("name") or default_name or ""
        raw_args = fn.get("arguments", fn.get("parameters", {}))
        call_id = data.get("id") or default_id
        if name:
            results.append(ToolCall(
                name=str(name),
                arguments=_normalize_arguments(raw_args),
                id=str(call_id) if call_id is not None else None,
                raw=raw,
            ))
            return results

    # Determine tool name
    name = (
        data.get("name")
        or data.get("function")
        or data.get("tool")
        or data.get("action")
        or default_name
    )

    # Determine arguments
    raw_args = None
    for arg_key in ("arguments", "parameters", "args", "params", "input", "action_input"):
        if arg_key in data:
            raw_args = data[arg_key]
            break

    if name and raw_args is not None:
        call_id = data.get("id") or data.get("call_id") or default_id
        results.append(ToolCall(
            name=str(name),
            arguments=_normalize_arguments(raw_args),
            id=str(call_id) if call_id is not None else None,
            raw=raw,
        ))
    elif default_name:
        call_id = data.get("id") or default_id
        filtered_args = {k: v for k, v in data.items() if k not in ("id", "call_id")}
        results.append(ToolCall(
            name=str(default_name),
            arguments=_normalize_arguments(filtered_args),
            id=str(call_id) if call_id is not None else None,
            raw=raw,
        ))

    return results


def _parse_tag_body(
    body: str,
    attrs: Dict[str, str],
    tag_name: str,
    raw_span: str,
) -> Tuple[List[ToolCall], Optional[str]]:
    """Parse the content inside a tool call tag."""
    content = _strip_markdown_fences(body)
    tool_name = attrs.get("name") or attrs.get("tool") or attrs.get("function")
    tool_id = attrs.get("id") or attrs.get("call_id")

    if ":" in tag_name and not tool_name:
        tool_name = tag_name.split(":", 1)[1]
    elif "=" in tag_name and not tool_name:
        tool_name = tag_name.split("=", 1)[1]

    # Check for sub-tags like <name>...</name> and <arguments>...</arguments>
    name_subtag = re.search(r"<(?P<tag>name|function)>(.*?)</(?P=tag)>", content, re.DOTALL)
    if name_subtag:
        tool_name = name_subtag.group(2).strip()

    id_subtag = re.search(r"<(?P<tag>id|call_id)>(.*?)</(?P=tag)>", content, re.DOTALL)
    if id_subtag:
        tool_id = id_subtag.group(2).strip()

    args_subtag = re.search(r"<(?P<tag>arguments|parameters|input)>(.*?)</(?P=tag)>", content, re.DOTALL)
    if args_subtag:
        inner_content = args_subtag.group(2).strip()
    else:
        inner_content = content

    if not inner_content and tool_name:
        return [ToolCall(name=tool_name, arguments={}, id=tool_id, raw=raw_span)], None

    # Try parsing JSON
    try:
        data = _clean_and_parse_json(inner_content)
        calls = _extract_tool_calls_from_data(data, default_name=tool_name, default_id=tool_id, raw=raw_span)
        if calls:
            return calls, None
    except Exception:
        pass

    # Try XML key-values fallback
    xml_dict = _parse_xml_key_values(inner_content)
    if xml_dict and tool_name:
        return [ToolCall(name=tool_name, arguments=xml_dict, id=tool_id, raw=raw_span)], None

    # Try stream of multiple JSON objects
    stream_calls: List[ToolCall] = []
    cleaned = _repair_json_text(_strip_markdown_fences(inner_content))
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(cleaned):
        while idx < len(cleaned) and cleaned[idx] in " \t\n\r,":
            idx += 1
        if idx >= len(cleaned):
            break
        try:
            obj, end_idx = decoder.raw_decode(cleaned, idx)
            stream_calls.extend(_extract_tool_calls_from_data(obj, default_name=tool_name, default_id=tool_id, raw=raw_span))
            idx = end_idx
        except Exception:
            break

    if stream_calls:
        return stream_calls, None

    if tool_name:
        return [ToolCall(name=tool_name, arguments={"_raw": inner_content}, id=tool_id, raw=raw_span)], (
            f"Could not fully parse arguments for tool '{tool_name}': {inner_content[:50]}"
        )

    return [], f"Failed to parse tool call content: {inner_content[:50]}"


def parse_tool_calls(
    text: str,
    tag_names: Optional[Sequence[str]] = None,
    allow_bare_json: bool = True,
    strict: bool = False,
) -> ParseResult:
    """Parse tool-call tags and JSON arguments from raw model output.

    Args:
        text: Raw output string from language model.
        tag_names: Optional sequence of custom XML tag names to search for.
                   Defaults to common tags like 'tool_call', 'tool_use', etc.
        allow_bare_json: If True and no tags are found, attempt to parse bare
                         JSON tool calls or arrays from the text.
        strict: If True, raise ToolCallParseError on parsing failures.

    Returns:
        ParseResult containing clean conversational text, parsed ToolCall items,
        and any parsing error messages.
    """
    if not text or not isinstance(text, str):
        return ParseResult(text=text or "", tool_calls=[], errors=[])

    valid_tags = list(tag_names) if tag_names else list(DEFAULT_TAGS)
    tag_re_str = "|".join(re.escape(t) for t in valid_tags)

    all_tool_calls: List[ToolCall] = []
    errors: List[str] = []
    spans_to_remove: List[Tuple[int, int]] = []

    # 1. Closed XML tags: <base_tag[:=func]? ...>body</base_tag[:=func]?>
    xml_pattern = re.compile(
        r"<(?P<tag>" + tag_re_str + r")(?P<suffix>[:=][a-zA-Z0-9_.-]+)?"
        r"(?P<attrs>[^>]*)>"
        r"(?P<body>.*?)"
        r"</\s*(?P=tag)(?:[:=][a-zA-Z0-9_.-]+)?\s*>",
        re.DOTALL | re.IGNORECASE,
    )

    for m in xml_pattern.finditer(text):
        tag_base = m.group("tag")
        suffix = m.group("suffix") or ""
        tag = f"{tag_base}{suffix}"
        attrs_str = m.group("attrs")
        body = m.group("body")
        raw_span = m.group(0)

        attrs = _parse_xml_attributes(attrs_str)
        if suffix.startswith(":") or suffix.startswith("="):
            attrs.setdefault("name", suffix[1:])

        calls, err = _parse_tag_body(body, attrs, tag, raw_span)
        if calls:
            all_tool_calls.extend(calls)
            spans_to_remove.append((m.start(), m.end()))
        if err:
            errors.append(err)
            if strict:
                raise ToolCallParseError(err)

    # 2. Square bracket pattern: [TAG[:=func]? attrs] body [/TAG]
    bracket_tags = [t.upper() for t in valid_tags] + [t.lower() for t in valid_tags]
    bracket_re_str = "|".join(re.escape(t) for t in set(bracket_tags))
    bracket_pattern = re.compile(
        r"\[(?P<tag>" + bracket_re_str + r")(?P<suffix>[:=][a-zA-Z0-9_.-]+)?"
        r"(?P<attrs>[^\]]*)\]"
        r"(?P<body>.*?)"
        r"\[/\s*(?P=tag)(?:[:=][a-zA-Z0-9_.-]+)?\s*\]",
        re.DOTALL | re.IGNORECASE,
    )

    for m in bracket_pattern.finditer(text):
        start, end = m.start(), m.end()
        if any(s <= start and end <= e for s, e in spans_to_remove):
            continue
        tag_base = m.group("tag")
        suffix = m.group("suffix") or ""
        tag = f"{tag_base}{suffix}"
        attrs_str = m.group("attrs")
        body = m.group("body")
        raw_span = m.group(0)

        attrs = _parse_xml_attributes(attrs_str)
        if suffix.startswith(":") or suffix.startswith("="):
            attrs.setdefault("name", suffix[1:])

        calls, err = _parse_tag_body(body, attrs, tag, raw_span)
        if calls:
            all_tool_calls.extend(calls)
            spans_to_remove.append((start, end))
        if err:
            errors.append(err)
            if strict:
                raise ToolCallParseError(err)

    # 3. Self-closing tags: <tool_call name="foo" arguments='...' />
    self_closing_pattern = re.compile(
        r"<(?P<tag>" + tag_re_str + r")(?P<attrs>[^>]*?)\s*/>",
        re.IGNORECASE,
    )
    for m in self_closing_pattern.finditer(text):
        start, end = m.start(), m.end()
        if any(s <= start and end <= e for s, e in spans_to_remove):
            continue
        attrs = _parse_xml_attributes(m.group("attrs"))
        tool_name = attrs.get("name") or attrs.get("tool") or attrs.get("function")
        if tool_name:
            args_str = attrs.get("arguments") or attrs.get("parameters") or attrs.get("args") or "{}"
            try:
                args = _clean_and_parse_json(args_str)
            except Exception:
                args = {"_raw": args_str}
            all_tool_calls.append(ToolCall(
                name=tool_name,
                arguments=_normalize_arguments(args),
                id=attrs.get("id"),
                raw=m.group(0),
            ))
            spans_to_remove.append((start, end))

    # 4. Unclosed tag fallback (e.g. [TOOL_CALLS] [...] without [/TOOL_CALLS], or truncated output)
    unclosed_pattern = re.compile(
        r"(?:<|\[)(?P<tag>(?:" + tag_re_str + r"|" + bracket_re_str + r"))"
        r"(?P<suffix>[:=][a-zA-Z0-9_.-]+)?"
        r"(?P<attrs>[^>\]]*?)(?:>|\])",
        re.IGNORECASE,
    )
    for m in unclosed_pattern.finditer(text):
        start = m.start()
        # Skip if this opening tag was already inside a parsed span
        if any(s <= start < e for s, e in spans_to_remove):
            continue
        tag_base = m.group("tag")
        suffix = m.group("suffix") or ""
        tag = f"{tag_base}{suffix}"
        attrs_str = m.group("attrs")
        attrs = _parse_xml_attributes(attrs_str)
        if suffix.startswith(":") or suffix.startswith("="):
            attrs.setdefault("name", suffix[1:])

        balanced = _extract_balanced_json(text, m.end())
        if balanced:
            json_str, end_pos = balanced
            raw_span = text[start:end_pos]
            calls, err = _parse_tag_body(json_str, attrs, tag, raw_span)
            if calls:
                all_tool_calls.extend(calls)
                spans_to_remove.append((start, end_pos))
            if err:
                errors.append(err)
                if strict:
                    raise ToolCallParseError(err)

    # If tool calls were found, excise them from text
    if spans_to_remove:
        # Merge overlapping/adjacent spans
        spans_to_remove.sort(key=lambda x: x[0])
        merged_spans: List[Tuple[int, int]] = []
        for s, e in spans_to_remove:
            if not merged_spans:
                merged_spans.append((s, e))
            else:
                prev_s, prev_e = merged_spans[-1]
                if s <= prev_e:
                    merged_spans[-1] = (prev_s, max(prev_e, e))
                else:
                    merged_spans.append((s, e))

        clean_parts: List[str] = []
        last_idx = 0
        for start, end in merged_spans:
            clean_parts.append(text[last_idx:start])
            last_idx = end
        clean_parts.append(text[last_idx:])

        clean_text = "".join(clean_parts).strip()
        clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)
        return ParseResult(text=clean_text, tool_calls=all_tool_calls, errors=errors)

    # 5. Fallback: Bare JSON if allowed and no tags found
    if allow_bare_json and not all_tool_calls:
        trimmed = _strip_markdown_fences(text)
        if (trimmed.startswith("{") and trimmed.endswith("}")) or (trimmed.startswith("[") and trimmed.endswith("]")):
            try:
                data = _clean_and_parse_json(trimmed)
                calls = _extract_tool_calls_from_data(data, raw=text)
                if calls:
                    return ParseResult(text="", tool_calls=calls, errors=[])
            except Exception as e:
                if strict:
                    raise ToolCallParseError(f"Bare JSON parse error: {e}") from e

    return ParseResult(text=text.strip(), tool_calls=[], errors=errors)


def extract_tool_calls(
    text: str,
    tag_names: Optional[Sequence[str]] = None,
    allow_bare_json: bool = True,
) -> List[ToolCall]:
    """Convenience function to extract only the tool calls from model output."""
    return parse_tool_calls(text, tag_names=tag_names, allow_bare_json=allow_bare_json).tool_calls


def format_tool_call(
    name: str,
    arguments: Dict[str, Any],
    call_id: Optional[str] = None,
    tag_name: str = "tool_call",
) -> str:
    """Format a function name and arguments into a tool-call tag string."""
    payload: Dict[str, Any] = {"name": name, "arguments": arguments}
    if call_id is not None:
        payload["id"] = call_id
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"<{tag_name}>\n{body}\n</{tag_name}>"