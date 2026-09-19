"""What Guardian knows about each tool, from `tool.registered` (stage 2 item 7).

Until 2026-09-19 Guardian judged a proposal by what the proposal said
about itself: its `reversibility` label was the class, and `read_only`
was derived from that label (evaluation S6). The proposer is the party
being judged. Execution announces every tool it registers -- its class,
whether it writes, and since stage 2 item 1 its argument schema -- and
this module keeps that announcement so the rules can read it instead.

Three things live here, all pure:

- `ToolRegistry`: name -> registration, fed by the live `tool.registered`
  messages and by a replay of Execution's `execution:tools` stream.
- `schema_errors`: a proposal's arguments against the tool's schema, as
  Guardian enforces it (see `enforced_schema` for exactly how much).
- `subject_keys`: the argument names that name a file, read off the schema
  rather than guessed.
"""

from __future__ import annotations

import re

from simorgh.contracts import toolargs
from simorgh.contracts.validation import validate

from .api import ToolInfo

_RANK = {"read_only": 0, "reversible": 1, "irreversible": 2}


def stricter(a: str, b: str) -> str:
    """The stricter of two reversibility classes; an unknown one counts
    as irreversible."""
    return a if _RANK.get(a, 2) >= _RANK.get(b, 2) else b


class ToolRegistry:
    """name -> {input_schema, reversibility, read_only}, as Execution
    registered it.

    A live `tool.registered` always wins; a replayed ledger record only
    fills a name nothing live has announced, because the stream spans
    earlier boots (30 d) and its records carry no schema."""

    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}
        self._live: set[str] = set()

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def note(self, payload: dict, *, live: bool = True) -> None:
        name = str(payload.get("name") or "")
        if not name:
            return
        if not live and name in self._live:
            return
        schema = payload.get("input_schema")
        entry = {
            "reversibility": str(payload.get("reversibility") or "irreversible"),
            "read_only": bool(payload.get("read_only", False)),
            "input_schema": schema if isinstance(schema, dict) else None,
        }
        if not live and entry["input_schema"] is None and name in self._tools:
            # An older record of the same tool: keep a schema we already have.
            entry["input_schema"] = self._tools[name]["input_schema"]
        self._tools[name] = entry
        if live:
            self._live.add(name)

    def get(self, name: str) -> dict | None:
        return self._tools.get(name)

    def info_for(self, tool: str, claimed: str) -> ToolInfo:
        """`ToolInfo` for a proposal of `tool` that claims `claimed`."""
        entry = self._tools.get(tool)
        if entry is None:
            return ToolInfo(
                name=tool, read_only=claimed == "read_only", reversibility=claimed, registered=False,
                notes=(f"{tool} is not registered with Guardian; its class is the proposal's own claim "
                       f"({claimed}) and its arguments were not checked against a schema",),
            )
        registered = entry["reversibility"]
        effective = stricter(registered, claimed)
        notes: tuple[str, ...] = ()
        if effective != claimed:
            notes = (f"the proposal claimed {claimed}; {tool} is registered {registered}, and the registration stands",)
        return ToolInfo(
            name=tool, read_only=entry["read_only"], reversibility=effective,
            input_schema=entry["input_schema"], registered=True, notes=notes,
        )


# -- the schema check ---------------------------------------------------------

#: A scalar the marker dialect wrote as text and the tool coerces itself
#: (`CAST_VOLUME: 35` arrives as `{"level": "35"}`; `CAM_WATCH: off` as
#: `{"on": "off"}`; a `key=value` line types `steps=40` as an int).
_WIDEN = {
    "string": ("number", "integer", "boolean", "null"),
    "number": ("string", "null"),
    "integer": ("string", "null"),
    "boolean": ("string", "null"),
    # `BROWSE_PAGE: <url>\n<plain text>` gives `actions` as text.
    "array": ("string", "null"),
    "object": ("null",),
    "null": (),
}


def _widen_type(declared) -> list[str] | None:
    names = [declared] if isinstance(declared, str) else list(declared or [])
    if not names:
        return None
    out: list[str] = []
    for name in names:
        for n in (name, *_WIDEN.get(name, ())):
            if n not in out:
                out.append(n)
    return out


def _lenient(schema) -> dict | bool:
    if not isinstance(schema, dict):
        return schema if isinstance(schema, bool) else {}
    out: dict = {}
    if "type" in schema:
        widened = _widen_type(schema["type"])
        if widened:
            out["type"] = widened
    if isinstance(schema.get("properties"), dict):
        out["properties"] = {k: _lenient(v) for k, v in schema["properties"].items()}
    if isinstance(schema.get("required"), list):
        out["required"] = list(schema["required"])
    if isinstance(schema.get("items"), dict):
        out["items"] = _lenient(schema["items"])
    if isinstance(schema.get("additionalProperties"), dict):
        out["additionalProperties"] = _lenient(schema["additionalProperties"])
    branches = [b for key in ("anyOf", "oneOf") for b in (schema.get(key) or []) if isinstance(b, (dict, bool))]
    if branches:
        # Widened branches may overlap, so "exactly one" becomes "any".
        out["anyOf"] = [_lenient(b) for b in branches]
    # Deliberately dropped: `enum`/`const` (the tool refuses a bad value
    # with its own, better message; not a safety question) and
    # `additionalProperties: false` (an extra argument is ignored by the
    # tool, and today's callers send some).
    return out


def marker_guaranteed(tool: str) -> set[str] | None:
    """The argument names the marker dialect always supplies for `tool`,
    or None when the tool has no marker shape (then the schema's own
    `required` list stands in full).

    A marker call carries what its one line can: `CAM_PTZ: front left`
    is `{"camera": "front left"}` and the tool reads the command out of
    that text; `MEDIA_PLAY: jazz` has no `where` and the tool picks the
    default player. Both schemas declare the second argument required,
    and both calls work today. So for a tool with a marker shape only
    the part of `required` that shape guarantees is enforced."""
    if tool in toolargs.MARKER_NO_ARGS or tool in toolargs.MARKER_KEY_VALUES:
        return set()
    if tool in toolargs.MARKER_SPLIT_FIRST_LINE:
        first, second = toolargs.MARKER_SPLIT_FIRST_LINE[tool]
        return {first} if tool in toolargs.MARKER_JSON_REST else {first, second}
    if tool in toolargs.MARKER_ARG_KEY:
        return {toolargs.MARKER_ARG_KEY[tool]}
    return None


def enforced_schema(tool: str, schema: dict) -> dict:
    """The part of a tool's schema Guardian enforces.

    Enforced: that the arguments are an object; every required argument
    is present (narrowed by `marker_guaranteed`); and no argument is a
    different KIND of value than declared -- a list or object where a
    string is expected is refused, which is what matters here, because a
    rule that reads a path reads a string and a `path: ["docs/SOUL.md"]`
    would slip past it. Tolerated: extra arguments, a scalar written as
    text (and a number where text is expected), text where a list is
    expected, null for anything, and enum/const values."""
    out = _lenient(schema)
    if not isinstance(out, dict):
        return {"type": ["object"]}
    out["type"] = ["object"]
    guaranteed = marker_guaranteed(tool)
    if guaranteed is not None and "required" in out:
        out["required"] = [name for name in out["required"] if name in guaranteed]
    return out


def schema_errors(tool: str, args, schema: dict | None) -> tuple[list[str], str | None]:
    """`(errors, note)`: why `args` fail `tool`'s schema as Guardian
    enforces it ([] when they pass or there is no schema), and a note
    when the schema itself could not be read. A malformed schema is
    Execution's bug, not the proposer's, so it is said on the decision
    rather than refusing every call to the tool."""
    if not isinstance(schema, dict):
        return [], None
    if not isinstance(args, dict):
        return [f"$: arguments must be an object, got {type(args).__name__}"], None
    try:
        return validate(args, enforced_schema(tool, schema)), None
    except (ValueError, TypeError) as exc:
        return [], f"{tool}'s input_schema could not be checked: {exc}"


# -- which arguments name a file ----------------------------------------------

_PATH_NAMES = ("subject", "path", "file", "file_path", "filepath", "filename", "target",
               "source", "src", "dest", "destination", "dst", "directory", "dir", "paths", "files")
_PATHISH_NAME = re.compile(r"(^|_)(path|file|dir|directory|dest|destination)s?$")


def _declares(prop: dict, kind: str) -> bool:
    declared = prop.get("type")
    names = [declared] if isinstance(declared, str) else list(declared or [])
    return kind in names


def schema_subject_keys(schema: dict | None) -> tuple[str, ...]:
    """The properties of `schema` that name a file, in preference order:
    a string (or list-of-strings) property called `subject`, `path`,
    `file_path`, `target`, `destination`, ... or anything ending in
    `_path`/`_file`/`_dir`. Empty when the schema declares none."""
    if not isinstance(schema, dict) or not isinstance(schema.get("properties"), dict):
        return ()
    props = schema["properties"]
    found: list[str] = []
    candidates = [n for n in _PATH_NAMES if n in props] + sorted(
        n for n in props if n not in _PATH_NAMES and _PATHISH_NAME.search(n))
    for name in candidates:
        prop = props[name] if isinstance(props[name], dict) else {}
        is_string = _declares(prop, "string") or "type" not in prop
        is_list = _declares(prop, "array") and isinstance(prop.get("items"), dict) and _declares(prop["items"], "string")
        if is_string or is_list:
            found.append(name)
    return tuple(found)


def _is_web_url(value: str) -> bool:
    """An http(s) URL that cannot also be read as a path reaching a
    protected file. `browse_page`'s `target` is a URL, and the creator's
    repository URL contains `simorgh/kernel/`; reading it as a path
    would refuse browsing Sim's own code on GitHub. But a tool handed
    `https://../docs/SOUL.md` as a path resolves it to `docs/SOUL.md`
    (the `https:` part is just a directory name), so anything with a
    `..` segment is still a path."""
    if not re.match(r"(?i)^https?://[^/]", value):
        return False
    return ".." not in value.split("/")


def subject_values(args: dict, keys) -> list[str]:
    """The file names `args` carries under `keys` (a string, or each
    string of a list); web URLs skipped (`_is_web_url`)."""
    out: list[str] = []
    for key in keys:
        value = args.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, str) or not item or _is_web_url(item):
                continue
            if item not in out:
                out.append(item)
    return out
