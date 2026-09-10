"""Test-session isolation from the ambient environment.

`kernel/config.py::_apply_env_overrides` lets `SIMORGH_<SECTION>_<KEY>`
override a config value -- which is right for a config *file*, and wrong
for a value a caller passed in code. `LoadedConfig.__init__` runs those
overrides unconditionally, so `SIMORGH_RUNTIME_DATA_DIR` beats the
explicit temp directory that ~40 integration tests hand it:

    LoadedConfig({"runtime": {"data_dir": tmp.name}}, None)

Live-caught by an observer on 2026-09-10. Sim was running with a
non-default `data_dir` exported in its environment; its own autonomous
patch work calls the `run_tests` tool, pytest inherited that variable,
and `tests/simorgh/integration` wrote a real jsonl Ledger straight into
the LIVE store -- 84 `memory:semantic` records in one session, several
of them the literal test fixture string "the real answer", tagged
`consolidation` and timestamped by a `FakeClock` (so they read as
memories from 1970-ish and from the future, in the same stream). Those
are indistinguishable from real memories afterwards, and recall serves
them like any other. With `data_dir` left at its default the same run
would write into `~/.simorgh`.

Stripping the variables for the whole session is the fix that needs no
change to any test and cannot be forgotten by the next one: a test suite
has no business reading the operator's environment in the first place.
A test that genuinely wants to exercise the override sets it itself with
`monkeypatch.setenv`, which still works -- this only clears what leaked
in from outside.
"""

from __future__ import annotations

import os

import pytest

#: Every env override `kernel/config.py` recognises shares this prefix.
_PREFIX = "SIMORGH_"

#: ...except these, which select behaviour rather than redirect state,
#: and which a caller may legitimately set for a whole run.
_KEEP = frozenset({"SIMORGH_OBSERVER_RUN_ID"})


@pytest.fixture(autouse=True, scope="session")
def _no_ambient_simorgh_env():
    stashed = {k: v for k, v in os.environ.items() if k.startswith(_PREFIX) and k not in _KEEP}
    for key in stashed:
        del os.environ[key]
    try:
        yield
    finally:
        os.environ.update(stashed)
