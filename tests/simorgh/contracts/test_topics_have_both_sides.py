"""Every topic in the catalogue has a publisher and a subscriber in
`simorgh/`, or is on the allow-list with a reason.

The "unconnected wire" is this project's dominant bug shape: a slot
designed on both sides, one side implemented, nobody writes it, nothing
fails (2026-09-18 evaluation, W7: 25 of 137 non-reply topics had one side
or none). This test makes it fail. Detection is textual and deliberately
generous: a topic constant referenced next to a publish/reply/request
call counts as published; one referenced next to a subscribe call, a
handler table or a `consumes` tuple counts as subscribed. A false "both"
is possible; a false "one-sided" is what the allow-list is for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from simorgh.contracts import topics as T

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "simorgh"

#: Topics allowed to have one side, each with the reason. Add an entry
#: only with a reason a reader can check; remove it when the wire is
#: connected. `reply` types are checked through their request.
ALLOWED_ONE_SIDED: dict[str, str] = {
    # published for the dashboard/HTTP feed and the ledger, no in-process consumer by design
    T.BENCHMARK_RUN_COMPLETED: "consumed by the dashboard over HTTP, not on the bus",
    T.CURIOSITY_INTEREST_UPDATED: "consumed by the dashboard over HTTP, not on the bus",
    T.SELF_MODEL_UPDATED: "an announcement; consumers read the self:model projection instead",
    T.WORLD_ENV_OBSERVED: "an announcement; consumers query world.env.query instead",
    T.TOOL_INVOKED: "audit event for the ledger and the dashboard",
    T.REFLECT_ALERT_RAISED: "surfaced through ui.notice; kept for the ledger",
    T.REFLECT_ALERT_CLEARED: "surfaced through ui.notice; kept for the ledger",
    T.SYSTEM_SCHEDULE_ADDED: "audit event for the ledger",
    T.TASK_DEPENDENCY_SATISFIED: "Planning's own DAG reads task.completed; this is an audit event",
    T.PLAN_APPROVED: "Planning both publishes and folds it from its own stream (stage 7 gives it a bus consumer)",
    # subscribed, published only by an operator command or a test today
    T.MEMORY_FORGET: "operator-initiated (`memory forget`); no autonomous publisher by design",
    T.COGNITION_COMPACT_REQUEST: "published by the orchestration Compactor in stage 4",
    T.CURIOSITY_DISCOVER_REQUEST: "operator-initiated (`auto discover`)",
    T.CURIOSITY_SHARE_REQUEST: "operator-initiated",
    T.CURIOSITY_INTEREST_FOLLOW_UP_REQUEST: "operator-initiated",
    T.REFLECT_REVIEW_REQUEST: "operator-initiated (`reflect`)",
    T.RESEARCH_FINDING_RECORDED: "published by the research scaffold in stage 7",
    T.TASK_PROGRESS: "read from the ledger by resume.py; published by the progress note in stage 4",
    # declared for the roadmap, referenced nowhere yet: delete or connect by stage 4
    T.LEARN_STRATEGY_SUGGEST: "Learning answers it; the routing consumer arrives in stage 8",
    T.TASK_EDITS_KEPT: "named in session.py's docstring; stage 4 publishes it",
    T.LEARN_EXPERIMENT_RESULT: "stage 8 (policy loop)",
    T.PERCEPT_FILE_CHANGED: "stage 6 (environment events)",
    T.PLAN_REGROUND: "stage 7 (re-planning)",
    T.SYSTEM_RELOAD: "reserved for the loader",
    T.UI_RENDERED: "stage 4 (session deltas)",
}

_NAME = re.compile(r"\btopics\.([A-Z_][A-Z0-9_]+)\b")
_PUB = re.compile(r"publish|request\(|request_or_error|Message\.new|reply\(|reply_to|produces|_emit|emit\(|announce|Message\(")
_SUB = re.compile(r"subscribe\s*\(|consumes|_on_[a-z_]+|handlers?\[|case\s+topics\.|==\s*topics\.|in\s*[\(\{\[][^)\]}]*topics\.")


def _catalogue() -> dict[str, str]:
    return {n: v for n, v in vars(T).items()
            if n.isupper() and isinstance(v, str) and "." in v and n not in ("DOMAINS", "SUBSYSTEMS", "WILDCARD_ALL")}


def _scan() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    consts = _catalogue()
    pub: dict[str, set[str]] = {v: set() for v in consts.values()}
    sub: dict[str, set[str]] = {v: set() for v in consts.values()}
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("simorgh/contracts/") or "__pycache__" in rel:
            continue
        lines = path.read_text(errors="replace").split("\n")
        for i, line in enumerate(lines):
            for m in _NAME.finditer(line):
                name = m.group(1)
                if name not in consts:
                    continue
                value = consts[name]
                window = "\n".join(lines[max(0, i - 6): i + 2])
                if _SUB.search(window):
                    sub[value].add(rel)
                if _PUB.search(window):
                    pub[value].add(rel)
    return pub, sub


def _one_sided() -> dict[str, str]:
    pub, sub = _scan()
    out: dict[str, str] = {}
    for value in sorted(pub):
        if value.endswith(".reply"):
            continue
        p, s = bool(pub[value]), bool(sub[value])
        if p and s:
            continue
        out[value] = "pub-only" if p else ("sub-only" if s else "unreferenced")
    return out


class TestTopicsHaveBothSides:
    def test_every_topic_has_a_publisher_and_a_subscriber_or_a_reason(self):
        one_sided = _one_sided()
        unexplained = {v: k for v, k in one_sided.items() if v not in ALLOWED_ONE_SIDED}
        assert not unexplained, (
            "topics with one side and no allow-list reason (connect the other side, delete the topic, "
            f"or add a reason to ALLOWED_ONE_SIDED): {unexplained}"
        )

    def test_the_allow_list_is_not_stale(self):
        one_sided = _one_sided()
        stale = sorted(v for v in ALLOWED_ONE_SIDED if v not in one_sided)
        assert not stale, f"these topics now have both sides; remove them from ALLOWED_ONE_SIDED: {stale}"

    def test_the_allow_list_only_names_catalogue_topics(self):
        values = set(_catalogue().values())
        assert set(ALLOWED_ONE_SIDED) <= values
