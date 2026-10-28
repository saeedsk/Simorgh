"""Tool routing (stage 17 items 3 and 6,
docs/plan/stage-17-tool-routing-and-prompt-compression.md): which tool
*groups* a chat turn is offered, decided before the model is called.

Pure: no bus, no clock, no state. `route()` takes the turn's text, the
groups the conversation used in its last turns, the groups from
`agents/groups.toml`, and an embedding function, and returns group names.
The session (`session.py`) decides what to do with them by
`[orchestration] tool_routing`: `off` never calls this; `shadow` routes,
logs what it would have offered and offers everything; `on` offers only
the routed groups.

Routing decides what is OFFERED, never what is allowed. A tool not offered
is not a tool denied: Guardian still decides every call, the memory group
and `tool_more` are always offered (the core group), and a wrong route is
recoverable inside the same turn.

The embedding. The plan says Memory's configured embedder, so no second
model is loaded. Orchestration may not import `simorgh.memory`
(tests/simorgh/test_module_boundaries.py), so the function is injected:
the session asks Memory over the bus (`memory.embed`) for the groups'
utterances once and for each turn's text, and hands `route` a `Vectors`
table of the answers. When Memory refuses (its embedder is the hashing
floor, or a model is still loading) or does not answer in time, the
turn falls back to `lexical_embed` below: a hashed bag of words and
character trigrams, a few microseconds a turn, no model at all, and good
enough to tell "turn the kitchen light off" from "what's on today" in
English and in Farsi. It is not a semantic embedding, and the shadow
week is what says whether it is good enough.
"""

from __future__ import annotations

import fnmatch
import functools
import math
import re
import tomllib
import unicodedata
import zlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable, Sequence

#: `[orchestration] tool_routing`. `off` is the default and changes nothing.
MODES = ("off", "shadow", "on")
#: The meta tool that adds a group to the next step (Execution registers
#: it; Guardian gates it like any tool).
TOOL_MORE = "tool_more"
#: The "no tools" class (item 6, the bouncer): greetings, thanks, "say that
#: again". It has utterances and no tools.
CONVERSATIONAL = "conversational"
#: Where the groups live: beside the agent definitions, protected like them.
GROUPS_FILE = Path(__file__).resolve().parents[2] / "agents" / "groups.toml"

Embed = Callable[[str], Sequence[float]]


class GroupsFileError(ValueError):
    """A groups file that cannot be read, said with its file."""


@dataclass(frozen=True)
class Group:
    name: str
    description: str
    #: Tool names, or patterns (`cam_*`) matched the way `profiles.py`
    #: expands an agent file's.
    tools: tuple[str, ...]
    utterances: tuple[str, ...]
    #: Always offered, whatever the router says (`memory`, with `tool_more`).
    core: bool = False


_KEYS = {"description", "tools", "utterances", "core"}


def load_groups(path: Path = GROUPS_FILE) -> tuple[Group, ...]:
    """Every group in `path`, sorted by name -- the canonical order."""
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise GroupsFileError(f"{path}: {exc}") from exc
    out = []
    for name, table in sorted((data.get("groups") or {}).items()):
        if not isinstance(table, dict):
            raise GroupsFileError(f"{path}: groups.{name} is not a table")
        unknown = set(table) - _KEYS
        if unknown:
            # A key nothing reads is the unconnected wire this project keeps finding.
            raise GroupsFileError(f"{path}: groups.{name}: unknown keys {sorted(unknown)} (known: {sorted(_KEYS)})")
        out.append(Group(name=str(name), description=str(table.get("description") or ""),
                         tools=tuple(str(t) for t in table.get("tools") or ()),
                         utterances=tuple(str(u) for u in table.get("utterances") or ()),
                         core=bool(table.get("core", False))))
    named = {t for g in out for t in g.tools}
    extra = tuple(t for t in CORE_CODE_TOOLS if t not in named)
    if extra:
        # Code over the full data is how ANY data job is done (stage 19), so
        # it is offered on every turn, like recall: the core group gets it
        # unless the file has put it in a group itself.
        core = next((i for i, g in enumerate(out) if g.core), None)
        if core is not None:
            out[core] = replace(out[core], tools=out[core].tools + extra)
    return tuple(out)


#: Tools added to the core group when the groups file names them nowhere
#: (stage 19: Execution's workbench, `profiles.CODE_TOOLS`).
CORE_CODE_TOOLS = ("run_analysis",)


# -- the default embedding ---------------------------------------------------

#: Dimensions of the hashed vector. Collisions only blur, never break.
DIM = 1024
#: Words that say nothing about which tools a turn needs, in both
#: languages. Kept short on purpose: "what" and "چی" are not here, because
#: "what did you mean" is how the conversational class is recognised.
_STOP = frozenset("""
a an the is are am be was were to of on in at for with and or my me i you your it its this that
do does did please can could would will some any there here just now so
را رو و در به از که این آن با هست است من برایم برام یک می ها های
""".split())
#: What a word's trigrams weigh between them, against 1 for the word.
_GRAM_WEIGHT = 0.3
#: Arabic letter forms a Farsi keyboard sometimes produces, to their Persian ones.
_FOLD = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "‌": " "})


def _words(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", str(text or "")).translate(_FOLD).casefold()
    return [w for w in re.findall(r"\w+", text) if w not in _STOP]


def _slot(feature: str) -> int:
    # crc32, not hash(): the vector must be the same in every process.
    return zlib.crc32(feature.encode("utf-8")) % DIM


def lexical_embed(text: str) -> tuple[float, ...]:
    """A unit vector of hashed words and character trigrams. Each word
    counts once and its trigrams once between them, so "lights" still
    meets "light" and a Farsi suffix does not hide its stem."""
    vec = [0.0] * DIM
    for word in _words(text):
        vec[_slot("w:" + word)] += 1.0
        padded = f" {word} "
        grams = [padded[i:i + 3] for i in range(len(padded) - 2)]
        for gram in grams:
            vec[_slot("g:" + gram)] += _GRAM_WEIGHT / len(grams)
    norm = math.sqrt(sum(v * v for v in vec))
    return tuple(v / norm for v in vec) if norm else tuple(vec)


class Vectors:
    """An `Embed` over vectors computed elsewhere: Memory's, from
    `memory.embed`. `base` holds the groups' utterances, embedded once;
    `with_text` adds one turn's vector without copying them.

    Equal (and hashed alike) per (model, dimension, base), whatever turn
    text it carries, so `_examples` and `_centroids` -- cached per
    (groups, embedder) -- compute the centroids once per table, not once
    per turn. A text it was not given is a KeyError: `route` raising is
    the session's cue to fall back, never a silent zero vector."""

    __slots__ = ("model", "dimension", "_base", "_extra")

    def __init__(self, model: str, dimension: int, base: dict[str, tuple[float, ...]],
                 extra: dict[str, tuple[float, ...]] | None = None) -> None:
        self.model = str(model)
        self.dimension = int(dimension)
        self._base = base
        self._extra = extra or {}

    def __call__(self, text: str) -> tuple[float, ...]:
        hit = self._extra.get(text)
        return hit if hit is not None else self._base[text]

    def with_text(self, text: str, vector: Sequence[float]) -> "Vectors":
        return Vectors(self.model, self.dimension, self._base, {text: tuple(float(x) for x in vector)})

    def _key(self) -> tuple:
        return (self.model, self.dimension, id(self._base))

    def __hash__(self) -> int:
        return hash(self._key())

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Vectors) and self._key() == other._key()


def utterances(groups: Iterable[Group]) -> tuple[str, ...]:
    """Every utterance `route` embeds, once each, in file order: what a
    `Vectors` table must hold."""
    return tuple(dict.fromkeys(u for g in groups for u in g.utterances if u.strip()))


def _unit(vec: Sequence[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(v * v for v in vec))
    return tuple(v / norm for v in vec) if norm else tuple(vec)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


#: How a group's examples are scored against a turn. `centroid` is the
#: plan's: cosine to the mean of the group's utterance vectors, which is
#: right for a semantic embedder, where examples of one intent sit close
#: together. `nearest` is cosine to the closest single example (semantic-
#: router's own aggregation): with the lexical default, examples of one
#: intent share few words, so their mean is diluted by how many there are
#: -- 23 greetings left "hello" at 0.15 from its centroid against 0.71
#: from "hello Sim" -- and no margin could be set for it. The session uses
#: `nearest` with `lexical_embed` and `centroid` with an injected embedder.
AGGREGATES = ("centroid", "nearest")


@functools.lru_cache(maxsize=16)
def _examples(groups: tuple[Group, ...], embed: Embed) -> dict[str, tuple[tuple[tuple[float, ...], float], ...]]:
    """Each group's utterance vectors with their norms, once per (groups, embedder)."""
    out = {}
    for group in groups:
        vectors = tuple(tuple(embed(u)) for u in group.utterances if u.strip())
        if vectors:
            out[group.name] = tuple((v, math.sqrt(sum(x * x for x in v))) for v in vectors)
    return out


@functools.lru_cache(maxsize=16)
def _centroids(groups: tuple[Group, ...], embed: Embed) -> dict[str, tuple[tuple[float, ...], float]]:
    """Each group's utterance centroid (a unit vector), once per (groups, embedder)."""
    out = {}
    for name, rows in _examples(groups, embed).items():
        width = len(rows[0][0])
        out[name] = (_unit([sum(v[i] for v, _ in rows) / len(rows) for i in range(width)]), 1.0)
    return out


def scores(text: str, groups: Iterable[Group], embed: Embed = lexical_embed, *,
           aggregate: str = "centroid") -> dict[str, float]:
    """Cosine of the turn's text to every group, by name (`AGGREGATES`)."""
    groups = tuple(groups)
    # The turn's vector is sparse under the lexical default: the dot
    # product runs over its non-zero entries only, which is what keeps
    # `nearest` (one cosine per example) to about a millisecond.
    nonzero = [(i, x) for i, x in enumerate(embed(text)) if x]
    norm = math.sqrt(sum(x * x for _, x in nonzero))
    if not norm:
        return {g.name: 0.0 for g in groups if g.utterances}

    def cos(row: tuple[tuple[float, ...], float]) -> float:
        vector, length = row
        return sum(x * vector[i] for i, x in nonzero) / (norm * length) if length else 0.0

    if aggregate == "nearest":
        return {name: max(cos(row) for row in rows) for name, rows in _examples(groups, embed).items()}
    return {name: cos(row) for name, row in _centroids(groups, embed).items()}


def _candidates(groups: Iterable[Group]) -> list[str]:
    """The groups the router chooses among: every group with tools, except core."""
    return [g.name for g in groups if g.tools and not g.core and g.name != CONVERSATIONAL]


def conversational(scored: dict[str, float], groups: Iterable[Group], margin: float) -> bool:
    """Whether the conversational class wins by `margin` over the best
    tool group (item 6). No conversational group, never."""
    if CONVERSATIONAL not in scored:
        return False
    best = max((scored.get(n, 0.0) for n in _candidates(groups)), default=0.0)
    return scored[CONVERSATIONAL] > 0.0 and scored[CONVERSATIONAL] - best >= margin


def route(text: str, history: Iterable[Iterable[str]], groups: Iterable[Group], embed: Embed = lexical_embed, *,
          top_k: int = 3, sticky_turns: int = 3, none_margin: float = 0.15,
          aggregate: str = "centroid") -> tuple[str, ...]:
    """The groups this turn is offered, sorted by name.

    - the core group(s), always;
    - the `top_k` tool groups closest to `text`, among those that score
      above zero -- when none does there is no evidence to narrow on, and
      every tool group is offered;
    - every group used in the last `sticky_turns` turns of `history`
      (oldest first, one iterable of group names per turn), so "and the
      bedroom one?" after a light keeps the lights.

    When the conversational class wins by `none_margin`, only the core
    group: a "thanks" is offered no tools but memory and `tool_more`.
    `aggregate` is how a group is scored (`AGGREGATES`).
    """
    groups = tuple(groups)
    known = {g.name for g in groups}
    core = {g.name for g in groups if g.core}
    scored = scores(text, groups, embed, aggregate=aggregate)
    if conversational(scored, groups, none_margin):
        return tuple(sorted(core))
    ranked = sorted(((scored.get(n, 0.0), n) for n in _candidates(groups)), key=lambda p: (-p[0], p[1]))
    picked = {n for s, n in ranked[:max(0, int(top_k))] if s > 0.0}
    if not picked:
        picked = set(_candidates(groups))
    turns = list(history or ())
    sticky = set()
    if sticky_turns > 0:
        for turn in turns[-int(sticky_turns):]:
            sticky.update(str(n) for n in turn or ())
    sticky &= known - {CONVERSATIONAL}
    return tuple(sorted(core | picked | sticky))


# -- from groups to tools ----------------------------------------------------

def group_of(tool: str, groups: Iterable[Group]) -> str | None:
    """The group `tool` belongs to, or None."""
    for group in groups:
        if any(fnmatch.fnmatchcase(tool, pattern) for pattern in group.tools):
            return group.name
    return None


def tools_for(names: Iterable[str], groups: Iterable[Group], available: Sequence[str]) -> tuple[str, ...]:
    """The `available` tools the groups `names` hold, in the canonical
    order: groups sorted by name, each group's tools in its file's order
    (a pattern's matches sorted). Then every available tool that belongs
    to no group (a skill Sim wrote), in the order given, so routing never
    hides a tool nobody has placed.

    Two turns routed to the same groups get the same tuple, whatever order
    `names` came in: the tool block, and the provider's cached prefix with
    it, stay byte-identical."""
    groups = tuple(groups)
    wanted = set(names)
    have = list(dict.fromkeys(available))
    out: list[str] = []
    for group in sorted(groups, key=lambda g: g.name):
        if group.name not in wanted:
            continue
        for pattern in group.tools:
            matches = sorted(t for t in have if fnmatch.fnmatchcase(t, pattern)) if any(
                c in pattern for c in "*?[") else ([pattern] if pattern in have else [])
            out.extend(t for t in matches if t not in out)
    out.extend(t for t in have if t not in out and group_of(t, groups) is None)
    return tuple(out)
