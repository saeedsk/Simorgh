"""Every Service's `consumes`/`produces` manifest matches its code
(2026-09-18 evaluation, V4: Interface declared 16 topics and subscribed to
29; 25 subscriptions across six packages were undeclared and 3 declared
topics were used nowhere).

Two directions are pinned exactly, because both can be checked exactly:

- every `subscribe(topics.X` in a package is in its `consumes`;
- every topic in `consumes` or `produces` is referenced somewhere in the
  package (a declaration nothing uses is a wire nobody connected).

"Every publish is declared" is NOT pinned: publishing happens through
too many helpers (`_publish`, `reply`, `request`, `Message.new` passed
around) to detect without false positives. `tools/contract_skeleton.py`
reports it heuristically for the CONTRACT.md tables.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from simorgh.contracts import topics as T

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ("bus", "ledger", "cognition", "memory", "worldmodel", "planning", "guardian", "execution",
            "verification", "learning", "reflection", "curiosity", "persona", "benchmark", "voice", "interface",
            "orchestration")
_CONSTS = {n: v for n, v in vars(T).items() if n.isupper() and isinstance(v, str) and "." in v}
_SUBSCRIBE = re.compile(r"subscribe\(\s*topics\.([A-Z_][A-Z0-9_]*)")
_REFERENCE = re.compile(r"\btopics\.([A-Z_][A-Z0-9_]*)\b")


def _sources(package: str) -> list[str]:
    return [p.read_text(errors="replace") for p in (ROOT / "simorgh" / package).rglob("*.py")
            if "__pycache__" not in p.parts]


def _service(package: str):
    module = importlib.import_module(f"simorgh.{package}.service")
    return getattr(module, "Service", None) or getattr(module, "VerificationService")


@pytest.mark.parametrize("package", PACKAGES)
def test_every_subscription_is_declared(package):
    subscribed = {_CONSTS[n] for text in _sources(package) for n in _SUBSCRIBE.findall(text) if n in _CONSTS}
    declared = set(getattr(_service(package), "consumes", ()) or ())
    missing = sorted(subscribed - declared)
    assert not missing, f"simorgh/{package} subscribes to {missing} but its Service.consumes does not declare them"


@pytest.mark.parametrize("package", PACKAGES)
def test_every_declared_topic_is_used(package):
    svc = _service(package)
    declared = set(getattr(svc, "consumes", ()) or ()) | set(getattr(svc, "produces", ()) or ())
    # A manifest's own `topics.X` lines count as references, so count references
    # outside the manifest: at least two mentions means it is used beyond the list.
    counts: dict[str, int] = {}
    for text in _sources(package):
        for name in _REFERENCE.findall(text):
            if name in _CONSTS:
                counts[_CONSTS[name]] = counts.get(_CONSTS[name], 0) + 1
    unused = sorted(t for t in declared if counts.get(t, 0) < 2)
    assert not unused, f"simorgh/{package} declares {unused} but never uses them outside the manifest"
