"""Every topic in the catalogue has a publisher and a subscriber in
`simorgh/`, or is on the allow-list with a reason.

The "unconnected wire" is this project's dominant bug shape: a slot
designed on both sides, one side implemented, nobody writes it, nothing
fails (2026-09-18 evaluation, W7: 25 of 137 non-reply topics had one side
or none). This test makes it fail. Detection is textual and deliberately
exact where it can be: "subscribed" is read from the bus of a booted
system (every registration, by pattern), "published" is any use of the
constant in simorgh/ other than a manifest listing or a subscribe call.
(Until 2026-09-19 both sides were guessed from keywords within six lines
of a mention, and inserting a comment into a manifest flipped four topics'
verdicts.) A false "both" is still possible on the publish side; a false
"one-sided" is what the allow-list is for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from simorgh.contracts import topics as T

pytestmark = [pytest.mark.contract, pytest.mark.integration]

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
    T.COGNITION_COMPACT_PRE: "an announcement for the ledger; the stage-4 Compactor's PreCompact hook consumes it",
    T.COGNITION_COMPACT_DONE: "an announcement for the ledger",
    T.MEMORY_STORED: "an announcement for the ledger and the dashboard",
    T.MEMORY_CONSOLIDATED: "an announcement for the ledger and the dashboard",
    T.MEMORY_CONTRADICTION_FLAGGED: "superseded by the stage-5 fact store; kept for the ledger until then",
    T.MEMORY_FORGOTTEN: "an announcement for the ledger",
    T.PERCEPT_WEB_FETCHED: "an announcement; the stage-6 world model folds it",
    T.LEARN_SELF_PATCH_REVERTED: "World Model and Reflection subscribe; nothing publishes it since the PatchPipeline was retired. The loader's rollback should (stage 8)",
    T.PLAN_APPROVED: "Planning both publishes and folds it from its own stream (stage 7 gives it a bus consumer)",
    # subscribed, published only by an operator command or a test today
    T.MEMORY_FORGET: "operator-initiated (`memory forget`); no autonomous publisher by design",
    T.COGNITION_COMPACT_REQUEST: "published by the orchestration Compactor in stage 4",
    T.REFLECT_REVIEW_REQUEST: "operator-initiated (`reflect`)",
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

_REF = re.compile(r"\btopics\.([A-Z_][A-Z0-9_]*)\b")
_SUBSCRIBE = re.compile(r"subscribe\(\s*topics\.([A-Z_][A-Z0-9_]*)")
_MANIFEST = re.compile(r"^\s*(consumes|produces|_CONSUMES|_PRODUCES)\b[^=\n]*=\s*(frozenset\()?\(", re.M)


def _catalogue() -> dict[str, str]:
    return {n: v for n, v in vars(T).items()
            if n.isupper() and isinstance(v, str) and "." in v and n not in ("DOMAINS", "SUBSYSTEMS", "WILDCARD_ALL")}


def _manifest_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for m in _MANIFEST.finditer(text):
        j = text.index("(", m.end() - 1)
        depth, k = 0, j
        while True:
            depth += (text[k] == "(") - (text[k] == ")")
            k += 1
            if depth == 0:
                break
        spans.append((j, k))
    return spans


def _published() -> dict[str, set[str]]:
    """Topic -> files that use it for something other than listing it in a
    manifest or subscribing to it: building, publishing, requesting,
    replying. Static and deliberately generous (a comparison counts too)."""
    consts = _catalogue()
    pub: dict[str, set[str]] = {v: set() for v in consts.values()}
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("simorgh/contracts/") or "__pycache__" in rel:
            continue
        text = path.read_text(errors="replace")
        spans = _manifest_spans(text)
        sub_at = {m.start(1) for m in _SUBSCRIBE.finditer(text)}
        for m in _REF.finditer(text):
            name = m.group(1)
            if name not in consts or m.start(1) in sub_at or any(a <= m.start() < b for a, b in spans):
                continue
            pub[consts[name]].add(rel)
    return pub


_SUBSCRIBED: set[str] | None = None


def _subscribed() -> set[str]:
    """What the RUNNING system subscribes to: boot every subsystem (floor
    cognition, a temp data dir) and read the bus's registrations. Static
    detection missed subscriptions made in a loop over a handler table;
    the bus does not."""
    global _SUBSCRIBED
    if _SUBSCRIBED is None:
        import asyncio
        import tempfile

        from simorgh.kernel.config import LoadedConfig
        from simorgh.kernel.secrets import EnvSecretStore
        from simorgh.kernel.service import Kernel

        async def boot() -> set[str]:
            with tempfile.TemporaryDirectory() as tmp:
                kernel = Kernel(LoadedConfig({"runtime": {"data_dir": tmp},
                                              "cognition": {"provider_order": ["floor"]}}, None),
                                secrets=EnvSecretStore({}))
                await kernel.boot()
                try:
                    return {r.spec.pattern for r in kernel._bus_backend._registered}  # noqa: SLF001
                finally:
                    await kernel.shutdown()

        _SUBSCRIBED = asyncio.run(boot())
    return _SUBSCRIBED


def _static_subscriptions() -> set[str]:
    """`subscribe(topics.X` call sites: covers subscriptions a bare boot
    does not make (the dashboard's and the TV's, opened when those
    features start)."""
    consts = _catalogue()
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for name in _SUBSCRIBE.findall(path.read_text(errors="replace")):
            if name in consts:
                found.add(consts[name])
    return found


def _one_sided() -> dict[str, str]:
    pub, sub = _published(), _subscribed() | _static_subscriptions()
    out: dict[str, str] = {}
    for value in sorted(pub):
        if value.endswith(".reply"):
            continue
        p, s = bool(pub[value]), value in sub
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
