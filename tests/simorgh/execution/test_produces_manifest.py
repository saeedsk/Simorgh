"""Execution's `Service.produces` is exactly the set of topics the package
builds a message on.

The shared manifest test (`tests/simorgh/test_manifests_match_the_code.py`)
cannot pin the publish direction for every package; Execution builds every
outgoing message with `Message.new(topics.X`, `message.caused(topics.X`,
`bus.new(topics.X` or a `_publish(ctx, topics.X` helper, so here it can.
The manifest listed ten of 26 topics until 2026-09-19."""

import re
from pathlib import Path

from simorgh.contracts import topics
from simorgh.execution.service import Service

_PACKAGE = Path(__file__).resolve().parents[3] / "simorgh" / "execution"
# Comment lines between the call and its topic are allowed: one publish
# carries a fourteen-line comment there.
_BUILDS = re.compile(r"(?:\.new|\.caused|_publish)\((?:\s*#[^\n]*)*\s*(?:ctx,\s*)?topics\.([A-Z_][A-Z0-9_]*)")


def _built_topics() -> set[str]:
    names: set[str] = set()
    for path in _PACKAGE.rglob("*.py"):
        names.update(_BUILDS.findall(path.read_text(errors="replace")))
    return {getattr(topics, name) for name in names}


def test_every_topic_the_package_builds_is_declared():
    missing = sorted(_built_topics() - set(Service.produces))
    assert not missing, f"execution publishes {missing} but Service.produces does not declare them"


def test_every_declared_topic_is_built_somewhere():
    extra = sorted(set(Service.produces) - _built_topics())
    assert not extra, f"Service.produces declares {extra} but nothing in execution publishes them"


def test_no_aliased_topics_import_hides_a_publish():
    # `from simorgh.contracts import topics as _topics` hid seven requests
    # from every `topics.X` scan, the shared manifest test's included.
    offenders = [p.name for p in _PACKAGE.rglob("*.py") if "topics as _" in p.read_text(errors="replace")]
    assert not offenders, offenders
