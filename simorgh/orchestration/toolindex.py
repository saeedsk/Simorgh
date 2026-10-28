"""Tool awareness: every turn knows every tool it may load (2026-10-27).

Live 2026-10-27, by voice: asked to unsubscribe the creator from Temu,
Sim said it had no browser and he should click himself. `browse_page`
was registered all along; the voice agent's tool list did not name it,
and a tool a turn is not offered does not exist for the model. Told
outright "you have browse_page", it searched its own code for it.

Three pieces, all under `[orchestration] tool_index` (off by default):

- an INDEX, one line per tool the turn may load but was not given, in the
  turn note (never the cached prefix): `index_note`;
- `tool_more` widened from routing groups to single tools (`tool`) and
  to a plain-words search (`need`) over that same set: `search`;
- a CAPABILITY CHECK: a chat reply that says "I can't" while a tool that
  matches the request exists gets those tools loaded and one nudge,
  before the reply goes out: `claims_inability` + `search`.

Which tools a turn may load (`loadable`): everything Execution
registered, minus the build tools (what the patch and skill agents
carry) that the turn's own agent does not already carry -- the typed
chat agent has `apply_source_patch`, the voice agent on purpose does not:
a spoken turn is answered, not built, and `start_task` is how it gets code
written -- minus the offer's own machinery, and for a read-only agent
minus anything that is not read-only. Guardian still gates every
call; this decides only what the model is told exists.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable

from . import scaffolds
from .tools import is_read_only, known_tools, tool_description

#: The agents that build: their tools are loadable only by an agent that
#: already carries them.
BUILDING_AGENTS = ("patch", "skill")

#: The index's header, so a test and the model see the same words.
INDEX_HEADER = ("Other tools you have, not loaded this step. To use one, first call tool_more with "
                "{\"tool\": \"<name>\"} (or {\"need\": \"<what you need, in plain words>\"} to search); "
                "it is offered from your next step. Never tell the person you cannot do something "
                "one of these does.")

#: How many lines the index may hold; past it, the rest are counted.
MAX_LINES = 150
GIST_CHARS = 90

#: "I can't" in the shapes a reply takes. Kept to claims of lacking a
#: capability -- "I can't find anything" after a real search is a result,
#: so `find`/`see` are not here.
_CANNOT = re.compile(
    r"\b(?:i\s*(?:can'?t|cannot|can\s+not|am\s+unable\s+to|'m\s+unable\s+to|am\s+not\s+able\s+to|'m\s+not\s+able\s+to)"
    r"\s+(?:do|click|press|open|run|send|reach|access|use|control|unsubscribe|book|buy|play|turn|change|switch|set)"
    r"|i\s*(?:don'?t|do\s+not)\s+have\s+(?:a|an|any|the)\s+(?:way|tool|browser|access|ability)"
    r"|(?:isn'?t|is\s+not|aren'?t|are\s+not)\s+(?:loaded|available)\s+(?:here|in\s+this\s+session|to\s+me|right\s+now)"
    r"|without\s+a\s+(?:real\s+)?browser"
    r"|(?:needs?|requires?)\s+your\s+click"
    r"|you(?:'ll|\s+will)?\s+(?:need|have)\s+to\s+(?:click|do\s+it|open\s+it|press)"
    r"|(?:the\s+)?honest\s+limit\s+of\s+what\s+i\s+can)",
    re.IGNORECASE)
_CANNOT_FA = re.compile(r"نمی‌?(?:توانم|تونم)|امکانش\s+را\s+ندارم|دسترسی\s+ندارم")

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset("""a an the and or of to in on at for from with by is are was be it its this that these those
you your i me my we our can cant cannot do does not no yes please just then than so as into out up down over
one two all any some what which who how when where why there here have has had will would should could
tool tools use using used get got make let""".split())


def gist(name: str) -> str:
    """One short line about `name`: the scaffold's note when it has one,
    else the first sentence of the description Execution registered."""
    text = scaffolds._TOOL_NOTES.get(name) or tool_description(name) or ""  # noqa: SLF001 -- same package
    text = " ".join(str(text).split())
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return first if len(first) <= GIST_CHARS else first[:GIST_CHARS - 1].rstrip() + "…"


def _profile_tools(name: str, known: frozenset[str]) -> set[str]:
    from . import profiles

    profile = profiles.AGENTS.get(name)
    if profile is None:
        return set()
    out: set[str] = set()
    for pattern in profile.tools:
        out.update(fnmatch.filter(known, pattern) if any(c in pattern for c in "*?[") else {pattern})
    return out


def build_tools(known: frozenset[str]) -> frozenset[str]:
    """What the building agents carry."""
    return frozenset(set().union(*(_profile_tools(n, known) for n in BUILDING_AGENTS)))


def loadable(*, read_only: bool, own: Iterable[str] = (), exclude: Iterable[str] = (),
             known: frozenset[str] | None = None) -> tuple[str, ...]:
    """The registered tools a turn may load, sorted. `own` is the turn's
    agent's own tools (patterns allowed); `exclude` the offer's machinery
    (tool_more, the crew and wait built-ins, ...)."""
    known = known_tools() if known is None else known
    mine = set()
    for pattern in own:
        mine.update(fnmatch.filter(known, pattern) if any(c in pattern for c in "*?[") else {pattern})
    out = set(known) - (build_tools(known) - mine) - set(exclude)
    if read_only:
        out = {t for t in out if is_read_only(t)}
    return tuple(sorted(out))


def index_note(hidden: Iterable[str]) -> str:
    """The index of `hidden` tools, "" when there are none."""
    names = sorted(dict.fromkeys(hidden))
    if not names:
        return ""
    lines = [f"- {n}: {gist(n)}" if gist(n) else f"- {n}" for n in names[:MAX_LINES]]
    if len(names) > MAX_LINES:
        lines.append(f"- ... and {len(names) - MAX_LINES} more; ask tool_more with a need to search them")
    return INDEX_HEADER + "\n" + "\n".join(lines)


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if len(w) >= 3 and w not in _STOP]


def _stem(word: str) -> str:
    for suffix in ("ing", "ers", "er", "es", "ed", "s", "e"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def search(need: str, candidates: Iterable[str], *, limit: int = 4) -> list[str]:
    """The `candidates` whose name, note and description best match
    `need`, best first; a word of the tool's NAME counts double. Only a
    tool with a real match is returned: no match is an empty list."""
    wanted = {_stem(w) for w in _words(need)}
    if not wanted:
        return []
    scored = []
    for name in candidates:
        name_words = {_stem(w) for w in _words(name.replace("_", " "))}
        body_words = {_stem(w) for w in _words(f"{scaffolds._TOOL_NOTES.get(name, '')} {tool_description(name)}")}  # noqa: SLF001
        score = 2 * len(wanted & name_words) + len(wanted & body_words)
        if score >= 2:
            scored.append((-score, name))
    return [name for _, name in sorted(scored)[:limit]]


def capability_nudge(names: Iterable[str]) -> str:
    """What the model is told when it said it cannot and these can."""
    lines = "\n".join(f"- {n}: {gist(n)}" for n in names)
    return ("You were about to tell the person you cannot do this. These tools exist and are offered "
            f"to you now:\n{lines}\nIf one of them does what was asked, use it now instead of answering. "
            "If none does, give the answer you would have given, plainly.")


def claims_inability(text: str) -> bool:
    """Whether a reply tells the person Sim cannot do something."""
    return bool(_CANNOT.search(text or "") or _CANNOT_FA.search(text or ""))


__all__ = ["BUILDING_AGENTS", "INDEX_HEADER", "MAX_LINES", "build_tools", "capability_nudge",
           "claims_inability",
           "gist", "index_note", "loadable", "search"]
