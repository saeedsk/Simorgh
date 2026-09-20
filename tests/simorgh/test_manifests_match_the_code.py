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

pytestmark = [pytest.mark.contract, pytest.mark.integration]

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ("bus", "ledger", "cognition", "memory", "worldmodel", "planning", "guardian", "execution",
            "verification", "growth", "persona", "benchmark", "voice", "interface",
            "orchestration")
_CONSTS = {n: v for n, v in vars(T).items() if n.isupper() and isinstance(v, str) and "." in v}
_SUBSCRIBE = re.compile(r"subscribe\(\s*topics\.([A-Z_][A-Z0-9_]*)")
_REFERENCE = re.compile(r"\btopics\.([A-Z_][A-Z0-9_]*)\b")


#: Code that runs under a subsystem's Context without being that
#: package: the product domains are Execution's `extra_tools` (stage 9
#: item 1) and publish as `execution`, so their topics are Execution's
#: to declare and count as Execution's uses.
_ALSO_RUNS_AS: dict[str, tuple[str, ...]] = {"execution": ("domains",)}


def _sources(package: str) -> list[str]:
    roots = [ROOT / "simorgh" / package] + [ROOT / "simorgh" / extra for extra in _ALSO_RUNS_AS.get(package, ())]
    return [p.read_text(errors="replace") for root in roots for p in root.rglob("*.py")
            if "__pycache__" not in p.parts]


def _service(package: str):
    module = importlib.import_module(f"simorgh.{package}.service")
    return getattr(module, "Service", None) or getattr(module, "VerificationService")


_RUNTIME: dict[str, set[str]] | None = None


def _runtime_subscriptions() -> dict[str, set[str]]:
    """source -> topics it subscribed to, read from the bus of a booted
    system. Catches subscriptions made through a handler table, which the
    `subscribe(topics.X` regex cannot see (curiosity and benchmark both
    subscribe from a dict)."""
    global _RUNTIME
    if _RUNTIME is None:
        import asyncio
        import tempfile

        from simorgh.kernel.config import LoadedConfig
        from simorgh.kernel.secrets import EnvSecretStore
        from simorgh.kernel.service import Kernel

        async def boot() -> dict[str, set[str]]:
            with tempfile.TemporaryDirectory() as tmp:
                kernel = Kernel(LoadedConfig({"runtime": {"data_dir": tmp},
                                              "cognition": {"provider_order": ["floor"]}}, None),
                                secrets=EnvSecretStore({}))
                await kernel.boot()
                try:
                    out: dict[str, set[str]] = {}
                    for r in kernel._bus_backend._registered:  # noqa: SLF001
                        out.setdefault(r.spec.source.split("@", 1)[0], set()).add(r.spec.pattern)
                    return out
                finally:
                    await kernel.shutdown()

        _RUNTIME = asyncio.run(boot())
    return _RUNTIME


@pytest.mark.parametrize("package", PACKAGES)
def test_every_subscription_is_declared(package):
    static = {_CONSTS[n] for text in _sources(package) for n in _SUBSCRIBE.findall(text) if n in _CONSTS}
    catalogue = set(_CONSTS.values())
    runtime = {t for t in _runtime_subscriptions().get(package, set()) if t in catalogue}
    subscribed = static | runtime
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
