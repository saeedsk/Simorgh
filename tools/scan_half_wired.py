#!/usr/bin/env python3
"""Find declared slots with one side missing.

The dominant bug shape in this codebase is a slot that exists on paper
and is only half-connected: a topic published and never subscribed, a
ledger stream appended and never read, a dataclass field assigned and
never read (or read and never assigned), a config key parsed and never
applied, a metric named in a report that nothing sets.

Every one of those is a two-sided relation, so every one of them can be
checked mechanically. This script does that over the whole tree, by AST
rather than by grep, and prints one section per relation. It reports
*gaps*, not bugs -- some gaps are deliberate (a contract for a producer
that does not exist yet, an inbound-only topic from a human). Triage is
still a human's job; the point is that the list is complete and the
same list comes back next time.

Known limits, so a reader does not over-trust a row:

* A field whose value is a mutable container is filled with `.add(...)`
  / `.append(...)`, never assigned, so it reads as NO WRITER
  (`Session.uncommitted`, `Tariff.rates`). Check before believing.
* A config key read only through an accessor in its own `config.py`
  (`resolved_history_path`, `drive_weights`) reads as UNUSED, because
  uses inside the defining file are excluded on purpose -- the
  dataclass's own `from_mapping` would otherwise mask every real gap.
* Field and config names are matched globally by name, not resolved to
  their class, so a name shared by two dataclasses is credited to both.
* A `.reply` topic legitimately has no subscriber: replies route to the
  requester's private inbox. They are listed separately, not as gaps.

Usage:
    python tools/scan_half_wired.py            # everything
    python tools/scan_half_wired.py topics     # one section
    python tools/scan_half_wired.py --json
"""

from __future__ import annotations

import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so `from simorgh...` works when run as tools/...
PKG = ROOT / "simorgh"
TESTS = ROOT / "tests"


def _py_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------
# 1. topics: publishers vs subscribers
# --------------------------------------------------------------------------

def _topic_constants() -> dict[str, str]:
    """`TASK_CREATE` -> `task.create`, from contracts/topics.py."""
    tree = _parse(PKG / "contracts" / "topics.py")
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                for t in targets:
                    if isinstance(t, ast.Name) and t.id.isupper():
                        out[t.id] = value.value
    return out


def _topic_of(node: ast.AST, consts: dict[str, str]) -> str | None:
    """The topic a first argument names, if it names one statically."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if "." in node.value or node.value in consts.values() else None
    if isinstance(node, ast.Attribute) and node.attr in consts:
        return consts[node.attr]
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    return None


# Publishing is rarely a bare `bus.publish(...)`: nearly every service
# wraps it (`self._publish`, `_emit`, `_announce`, `reply_to`), so match
# on the shape of the name, not an exact list, or the scan reports 66
# "subscribed but never published" topics that are published two frames
# down. `Event(type=..., ...)` construction counts too.
_PUBLISH_RE = ("publish", "emit", "announce", "notify", "broadcast", "reply", "send", "request")
_SUBSCRIBE_RE = ("subscribe",)
_EVENT_CTORS = {"Event", "Message", "make_event"}


# Helpers that take a topic as their first argument and do NOT produce
# one. Everything else that does is treated as a publisher: `Message.new
# (topics.X, ...)`, `self._publish(topics.X, ...)`, `define(t.X, ...)`
# are all real production sites and no name pattern covers all three.
_NOT_PUBLISH = {
    "matches", "domain_of", "is_reply", "reply_type_for", "may_publish", "may_subscribe",
    "get", "setdefault", "append", "add", "index", "count", "startswith", "endswith",
    "assertEqual", "assertIn", "assertNotIn", "join", "split", "format", "define",
}


def _is_publish(name: str) -> bool:
    n = name.lower()
    if name in _NOT_PUBLISH or _is_subscribe(name):
        return False
    return True


def _is_subscribe(name: str) -> bool:
    n = name.lower()
    return n.endswith("subscribe") and not n.endswith("unsubscribe")


class _TopicVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, consts: dict[str, str]) -> None:
        self.path = path
        self.consts = consts
        self.pub: list[tuple[str, str, int]] = []
        self.sub: list[tuple[str, str, int]] = []
        self.mentions: list[tuple[str, str, int]] = []
        # `for topic, handler in handlers.items(): subscribe(topic, ...)`
        # is how Benchmark and Curiosity wire themselves. The topic is
        # not a literal at the call site, so without this the scan calls
        # every topic they consume unsubscribed.
        self.dynamic_sub: list[int] = []
        self.dynamic_pub: list[int] = []
        self.handler_table: list[tuple[str, str, int]] = []
        self.topic_table: list[tuple[str, str, int]] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        name = node.func.attr if isinstance(node.func, ast.Attribute) else (
            node.func.id if isinstance(node.func, ast.Name) else "")
        # The topic is not always argument 0: Reflection's own wrapper is
        # `self._publish(cause_message, topics.X, payload)`, so a scan
        # that only looked at arg 0 called five real producers missing.
        found = False
        for arg in node.args[:2]:
            topic = self._first_topic(arg)
            if not topic:
                continue
            found = True
            if _is_subscribe(name):
                self.sub.append((topic, _rel(self.path), node.lineno))
            elif _is_publish(name) or name in _EVENT_CTORS:
                self.pub.append((topic, _rel(self.path), node.lineno))
            break
        if not found and node.args and _is_subscribe(name):
            self.dynamic_sub.append(node.lineno)
        # An Event(type=...) handed to publish() elsewhere still names a topic.
        for kw in node.keywords:
            if kw.arg in ("type", "topic", "event_type"):
                topic = self._first_topic(kw.value)
                if topic and (_is_publish(name) or name in _EVENT_CTORS):
                    self.pub.append((topic, _rel(self.path), node.lineno))
        self.generic_visit(node)

    def _first_topic(self, arg: ast.AST) -> str | None:
        return _topic_of(arg, self.consts)

    def visit_Dict(self, node: ast.Dict) -> None:  # noqa: N802
        """`{topics.X: self._on_x, ...}` fed to a subscribe loop."""
        for k, v in zip(node.keys, node.values):
            topic = _topic_of(k, self.consts) if k is not None else None
            if topic and isinstance(v, (ast.Attribute, ast.Name, ast.Lambda)):
                self.handler_table.append((topic, _rel(self.path), k.lineno))
            # The mirror image: `{"completed": topics.TASK_COMPLETED}`
            # picked at publish time (orchestration/worker.py:316). The
            # topic never appears at the call site at all.
            value_topic = _topic_of(v, self.consts)
            if value_topic:
                self.topic_table.append((value_topic, _rel(self.path), v.lineno))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if node.attr in self.consts:
            self.mentions.append((self.consts[node.attr], _rel(self.path), node.lineno))
        self.generic_visit(node)


def scan_topics() -> dict:
    consts = _topic_constants()
    pub: dict[str, list] = defaultdict(list)
    sub: dict[str, list] = defaultdict(list)
    mention: dict[str, list] = defaultdict(list)
    test_pub: dict[str, list] = defaultdict(list)
    test_sub: dict[str, list] = defaultdict(list)

    for path in _py_files(PKG):
        tree = _parse(path)
        if tree is None:
            continue
        v = _TopicVisitor(path, consts)
        v.visit(tree)
        for topic, f, line in v.pub:
            pub[topic].append(f"{f}:{line}")
        for topic, f, line in v.sub:
            sub[topic].append(f"{f}:{line}")
        for topic, f, line in v.topic_table:
            pub[topic].append(f"{f}:{line} (via table)")
        if v.dynamic_sub:
            # A subscribe whose topic is a loop variable. Anything this
            # file maps to a handler is reached by it.
            for topic, f, line in v.handler_table:
                sub[topic].append(f"{f}:{line} (via loop)")
        for topic, f, line in v.mentions:
            mention[topic].append(f"{f}:{line}")

    for path in _py_files(TESTS):
        tree = _parse(path)
        if tree is None:
            continue
        v = _TopicVisitor(path, consts)
        v.visit(tree)
        for topic, f, line in v.pub:
            test_pub[topic].append(f"{f}:{line}")
        for topic, f, line in v.sub:
            test_sub[topic].append(f"{f}:{line}")

    rows = []
    for const, topic in sorted(consts.items(), key=lambda kv: kv[1]):
        if "." not in topic:
            continue  # not a topic constant (DOMAINS entries etc.)
        rows.append({
            "const": const,
            "topic": topic,
            "publishers": sorted(set(pub.get(topic, []))),
            "subscribers": sorted(set(sub.get(topic, []))),
            "test_publishers": sorted(set(test_pub.get(topic, []))),
            "test_subscribers": sorted(set(test_sub.get(topic, []))),
            "mentions": sorted(set(mention.get(topic, []))),
        })
    return {"rows": rows, "consts": consts, "pub": pub, "sub": sub}


# --------------------------------------------------------------------------
# 1b. produces/consumes declarations vs actual subscribe()/publish() calls
# --------------------------------------------------------------------------

def scan_declarations(topic_scan: dict) -> list[dict]:
    consts = topic_scan["consts"]
    out: list[dict] = []
    for path in _py_files(PKG):
        tree = _parse(path)
        if tree is None:
            continue
        # module-level _CONSUMES / _PRODUCES tuples and class attributes
        declared: dict[str, list[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                key = target.id if isinstance(target, ast.Name) else (
                    target.attr if isinstance(target, ast.Attribute) else "")
                if key.upper().strip("_") in ("CONSUMES", "PRODUCES") and isinstance(
                        node.value, (ast.Tuple, ast.List, ast.Set)):
                    topics_ = [t for t in (_topic_of(e, consts) for e in node.value.elts) if t]
                    if topics_:
                        declared.setdefault(key.upper().strip("_"), []).extend(topics_)
        if not declared:
            continue
        v = _TopicVisitor(path, consts)
        v.visit(tree)
        actual_sub = {t for t, _, _ in v.sub}
        actual_pub = {t for t, _, _ in v.pub}
        out.append({
            "file": _rel(path),
            "declared_consumes": sorted(set(declared.get("CONSUMES", []))),
            "declared_produces": sorted(set(declared.get("PRODUCES", []))),
            "actually_subscribes": sorted(actual_sub),
            "actually_publishes": sorted(actual_pub),
            "declared_not_subscribed": sorted(set(declared.get("CONSUMES", [])) - actual_sub),
            "subscribed_not_declared": sorted(actual_sub - set(declared.get("CONSUMES", []))),
            "declared_not_published": sorted(set(declared.get("PRODUCES", [])) - actual_pub),
            "published_not_declared": sorted(actual_pub - set(declared.get("PRODUCES", []))),
        })
    return out


# --------------------------------------------------------------------------
# 2. ledger streams: appenders vs readers
# --------------------------------------------------------------------------

_APPEND = {"append", "snapshot", "put_blob"}
_READ = {"read", "head", "tail", "load_snapshot", "streams", "rebuild", "materialize"}


def _stream_literal(node: ast.AST) -> str | None:
    """A stream name if the expression starts from a literal prefix."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):  # f"task:{id}"
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            else:
                parts.append("*")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _stream_literal(node.left)
        return (left + "*") if left else None
    if isinstance(node, ast.Attribute):
        return None
    return None


def _stream_key(name: str) -> str:
    head, sep, _ = name.partition(":")
    return head + sep if sep else head.rstrip("*")


def scan_streams() -> list[dict]:
    appends: dict[str, list[str]] = defaultdict(list)
    reads: dict[str, list[str]] = defaultdict(list)
    try:
        from simorgh.ledger import streams as _s  # noqa: PLC0415
        known_prefixes = set(_s.KNOWN_PREFIXES)
    except Exception:  # noqa: BLE001
        known_prefixes = set()
    for path in _py_files(PKG):
        tree = _parse(path)
        if tree is None:
            continue
        # `_TICKS_STREAM = "curiosity:ticks"` then `append(_TICKS_STREAM, ...)`
        consts: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                consts[node.targets[0].id] = node.value.value
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Name) and arg.id in consts:
                name = consts[arg.id]
            else:
                name = _stream_literal(arg)
            if not name:
                continue
            key = _stream_key(name)
            # `list.append("some prose")` is not a ledger append. A real
            # stream name obeys the grammar and starts with a registered
            # prefix; anything else here is a false positive.
            if not key or key not in known_prefixes:
                continue
            where = f"{_rel(path)}:{node.lineno}"
            if node.func.attr in _APPEND:
                appends[key].append(where)
            elif node.func.attr in _READ:
                reads[key].append(where)
    keys = sorted(set(appends) | set(reads))
    known = set()
    try:
        from simorgh.ledger import streams as _s  # noqa: PLC0415
        known = set(_s.KNOWN_PREFIXES)
    except Exception:  # noqa: BLE001
        pass
    return [{
        "stream": k,
        "known_prefix": k in known,
        "appenders": sorted(set(appends.get(k, []))),
        "readers": sorted(set(reads.get(k, []))),
    } for k in keys]


# --------------------------------------------------------------------------
# 3. dataclass fields in */api.py: writers vs readers
# --------------------------------------------------------------------------

def _dataclass_fields(tree: ast.Module) -> dict[str, list[tuple[str, int]]]:
    out: dict[str, list[tuple[str, int]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        decorated = any(
            (isinstance(d, ast.Name) and d.id == "dataclass")
            or (isinstance(d, ast.Attribute) and d.attr == "dataclass")
            or (isinstance(d, ast.Call) and (
                (isinstance(d.func, ast.Name) and d.func.id == "dataclass")
                or (isinstance(d.func, ast.Attribute) and d.func.attr == "dataclass")))
            for d in node.decorator_list)
        if not decorated:
            continue
        fields = [(n.target.id, n.lineno) for n in node.body
                  if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
                  and not n.target.id.startswith("_")]
        if fields:
            out[node.name] = fields
    return out


def scan_api_fields() -> list[dict]:
    # Where is each name written (kwarg or attribute assignment) and read?
    writes: dict[str, set[str]] = defaultdict(set)
    reads: dict[str, set[str]] = defaultdict(set)
    for base in (PKG, TESTS):
        for path in _py_files(base):
            tree = _parse(path)
            if tree is None:
                continue
            is_test = base is TESTS
            for node in ast.walk(tree):
                where = f"{_rel(path)}:{getattr(node, 'lineno', 0)}"
                if is_test:
                    where = "TEST " + where
                if isinstance(node, ast.keyword) and node.arg:
                    writes[node.arg].add(where)
                elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
                    writes[node.attr].add(where)
                elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                    reads[node.attr].add(where)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    pass
                elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                        and isinstance(node.slice.value, str):
                    # d["field"] counts as both, conservatively as a read
                    reads[node.slice.value].add(where)
    rows: list[dict] = []
    for path in sorted(PKG.rglob("api.py")):
        if "__pycache__" in path.parts:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for cls, fields in _dataclass_fields(tree).items():
            for field, lineno in fields:
                w = sorted(x for x in writes.get(field, set()) if not x.startswith(f"{_rel(path)}:"))
                r = sorted(x for x in reads.get(field, set()) if not x.startswith(f"{_rel(path)}:"))
                rows.append({
                    "where": f"{_rel(path)}:{lineno}",
                    "class": cls,
                    "field": field,
                    "writers": [x for x in w if not x.startswith("TEST ")],
                    "readers": [x for x in r if not x.startswith("TEST ")],
                    "test_writers": [x for x in w if x.startswith("TEST ")],
                    "test_readers": [x for x in r if x.startswith("TEST ")],
                })
    return rows


# --------------------------------------------------------------------------
# 4. config keys in */config.py: where used
# --------------------------------------------------------------------------

def scan_config() -> list[dict]:
    uses: dict[str, set[str]] = defaultdict(set)
    for base in (PKG, TESTS):
        for path in _py_files(base):
            tree = _parse(path)
            if tree is None:
                continue
            prefix = "TEST " if base is TESTS else ""
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                    uses[node.attr].add(f"{prefix}{_rel(path)}:{node.lineno}")
                elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                        and isinstance(node.slice.value, str):
                    uses[node.slice.value].add(f"{prefix}{_rel(path)}:{node.lineno}")
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    uses[node.value].add(f"{prefix}{_rel(path)}:{node.lineno}")
    rows: list[dict] = []
    for path in sorted(PKG.rglob("config.py")):
        if "__pycache__" in path.parts:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        own = _rel(path)
        for cls, fields in _dataclass_fields(tree).items():
            for field, lineno in fields:
                sites = sorted(x for x in uses.get(field, set()) if not x.startswith(own + ":"))
                prod = [x for x in sites if not x.startswith("TEST ")]
                rows.append({
                    "where": f"{own}:{lineno}",
                    "class": cls,
                    "key": field,
                    "uses": prod,
                    "test_uses": [x for x in sites if x.startswith("TEST ")],
                })
    return rows


# --------------------------------------------------------------------------
# 5. metrics published on system.metrics
# --------------------------------------------------------------------------

def scan_metrics() -> list[dict]:
    """Keys carried in a `system.metrics` payload, and who reads them.

    A metric is only useful if something downstream looks at it. The
    producer side is `Message.new(topics.SYSTEM_METRICS, payload={...})`;
    the consumer side is any `["key"]` / `.get("key")` in a file that
    subscribes to `system.metrics`.
    """
    consts = _topic_constants()
    produced: dict[str, set[str]] = defaultdict(set)
    consumer_files: list[Path] = []
    for path in _py_files(PKG):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                node.func.id if isinstance(node.func, ast.Name) else "")
            first = _topic_of(node.args[0], consts) if node.args else None
            if first != "system.metrics":
                continue
            if _is_subscribe(name):
                consumer_files.append(path)
                continue
            for kw in node.keywords:
                if kw.arg == "payload":
                    for d in ast.walk(kw.value):
                        if isinstance(d, ast.Dict):
                            for k in d.keys:
                                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                                    produced[k.value].add(f"{_rel(path)}:{d.lineno}")
    readers: dict[str, set[str]] = defaultdict(set)
    for base in (PKG, TESTS):
        for path in _py_files(base):
            # A subscriber hands the payload on (`vitals.on_system_metrics
            # (payload)`, `self._metrics.record(message)`), so the file
            # that actually indexes the key is a sibling. The consuming
            # side is the whole package of any subscriber.
            if base is PKG and path.parent not in {f.parent for f in consumer_files}:
                continue
            tree = _parse(path)
            if tree is None:
                continue
            prefix = "TEST " if base is TESTS else ""
            for node in ast.walk(tree):
                key = None
                if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                        and isinstance(node.slice.value, str):
                    key = node.slice.value
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr == "get" and node.args \
                        and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str):
                    key = node.args[0].value
                if key:
                    readers[key].add(f"{prefix}{_rel(path)}:{node.lineno}")
    return [{"metric": k, "published_by": sorted(v),
             "read_by": sorted(x for x in readers.get(k, set()) if not x.startswith("TEST ")),
             "test_read_by": sorted(x for x in readers.get(k, set()) if x.startswith("TEST "))}
            for k, v in sorted(produced.items())]


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def _p(s: str = "") -> None:
    print(s)


def report_topics(scan: dict) -> None:
    _p("=" * 74)
    _p("1. TOPICS -- one side empty")
    _p("=" * 74)
    no_sub, no_pub, neither = [], [], []
    for row in scan["rows"]:
        p, s = row["publishers"], row["subscribers"]
        if not p and not s:
            neither.append(row)
        elif not s:
            no_sub.append(row)
        elif not p:
            no_pub.append(row)
    # A `.reply` is delivered point-to-point to the requester's private
    # inbox (`bus/router.py::INBOX_PREFIX`), never by topic
    # subscription, so "nobody subscribes" is how request/reply is
    # SUPPOSED to look. Kept, but apart, so they cannot bury the rest.
    replies = [r for r in no_sub if r["topic"].endswith(".reply")]
    no_sub = [r for r in no_sub if not r["topic"].endswith(".reply")]
    _p(f"\n-- reply topics with no subscriber ({len(replies)}) -- "
       "EXPECTED: replies route to a private inbox --")
    _p("  " + ", ".join(r["topic"] for r in replies))
    _p(f"\n-- published, NOT subscribed ({len(no_sub)}) --")
    for r in no_sub:
        _p(f"  {r['topic']:<34} pub {r['publishers'][0]}"
           + (f" (+{len(r['publishers']) - 1})" if len(r['publishers']) > 1 else "")
           + (f"  [tests subscribe: {len(r['test_subscribers'])}]" if r["test_subscribers"] else ""))
    _p(f"\n-- subscribed, NOT published ({len(no_pub)}) --")
    for r in no_pub:
        _p(f"  {r['topic']:<34} sub {r['subscribers'][0]}"
           + (f"  [tests publish: {len(r['test_publishers'])}]" if r["test_publishers"] else ""))
    _p(f"\n-- neither published nor subscribed in simorgh/ ({len(neither)}) --")
    for r in neither:
        extra = f"  mentions: {len(r['mentions'])}" if r["mentions"] else "  (constant only)"
        _p(f"  {r['topic']:<34}{extra}")


def report_declarations(rows: list[dict]) -> None:
    _p()
    _p("=" * 74)
    _p("1b. produces/consumes DECLARATIONS vs actual calls")
    _p("=" * 74)
    for r in rows:
        problems = {k: v for k, v in r.items() if k.endswith("declared") or k.startswith("declared_not")}
        problems = {k: v for k, v in problems.items() if v}
        if not problems:
            _p(f"  {r['file']}: consistent")
            continue
        _p(f"  {r['file']}:")
        for k, v in problems.items():
            _p(f"      {k}: {', '.join(v)}")


def report_streams(rows: list[dict]) -> None:
    _p()
    _p("=" * 74)
    _p("2. LEDGER STREAMS -- appended vs read")
    _p("=" * 74)
    for r in rows:
        if r["appenders"] and r["readers"]:
            continue
        side = "NO READER " if not r["readers"] else "NO APPENDER"
        sites = r["appenders"] or r["readers"]
        _p(f"  {side}  {r['stream']:<22} {sites[0]}"
           + (f" (+{len(sites) - 1})" if len(sites) > 1 else ""))


def report_api(rows: list[dict]) -> None:
    _p()
    _p("=" * 74)
    _p("3. */api.py DATACLASS FIELDS -- no writer or no reader (outside api.py)")
    _p("=" * 74)
    for r in rows:
        if r["writers"] and r["readers"]:
            continue
        what = []
        if not r["writers"]:
            what.append("NO WRITER")
        if not r["readers"]:
            what.append("NO READER")
        note = ""
        if not r["writers"] and r["test_writers"]:
            note += f" [tests write: {len(r['test_writers'])}]"
        if not r["readers"] and r["test_readers"]:
            note += f" [tests read: {len(r['test_readers'])}]"
        _p(f"  {'+'.join(what):<20} {r['class']}.{r['field']:<26} {r['where']}{note}")


def report_config(rows: list[dict]) -> None:
    _p()
    _p("=" * 74)
    _p("4. */config.py KEYS -- never used outside their own config.py")
    _p("=" * 74)
    for r in rows:
        if r["uses"]:
            continue
        note = f" [tests only: {len(r['test_uses'])}]" if r["test_uses"] else ""
        _p(f"  UNUSED  {r['class']}.{r['key']:<32} {r['where']}{note}")


def report_metrics(rows: list[dict]) -> None:
    _p()
    _p("=" * 74)
    _p("5. system.metrics KEYS -- published, nothing that subscribes reads them")
    _p("=" * 74)
    for r in rows:
        mark = "READ    " if r["read_by"] else "NO READER"
        note = f"  [tests read: {len(r['test_read_by'])}]" if not r["read_by"] and r["test_read_by"] else ""
        if r["read_by"]:
            continue
        _p(f"  {mark}  {r['metric']:<28} published {r['published_by'][0]}"
           + (f" (+{len(r['published_by']) - 1})" if len(r["published_by"]) > 1 else "") + note)


def main(argv: list[str]) -> int:
    want = {a for a in argv if not a.startswith("-")}
    as_json = "--json" in argv
    topics_scan = scan_topics()
    result = {
        "topics": topics_scan["rows"],
        "declarations": scan_declarations(topics_scan),
        "streams": scan_streams(),
        "api": scan_api_fields(),
        "config": scan_config(),
        "metrics": scan_metrics(),
    }
    if as_json:
        print(json.dumps(result, indent=2))
        return 0
    if not want or "topics" in want:
        report_topics(topics_scan)
        report_declarations(result["declarations"])
    if not want or "streams" in want:
        report_streams(result["streams"])
    if not want or "api" in want:
        report_api(result["api"])
    if not want or "config" in want:
        report_config(result["config"])
    if not want or "metrics" in want:
        report_metrics(result["metrics"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
