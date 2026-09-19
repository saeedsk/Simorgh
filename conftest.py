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
_KEEP = frozenset({"SIMORGH_OBSERVER_RUN_ID", "SIMORGH_LEDGER_WRITER_AUDIT"})

#: The operator's model keys. With them in the environment, every test
#: that booted a real Kernel made a paid, networked Together call (a second
#: or more each, 2026-09-14). A test of a provider passes its own key.
_MODEL_CREDENTIALS = frozenset({
    "TOGETHER_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "VOYAGE_API_KEY",
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
})

#: Without a key Cognition would fall through to the `claude` CLI, when
#: it is installed -- slower and still billed. Booted services answer from
#: the offline floor instead (cognition/service.py reads this).
_FLOOR_ONLY = "SIMORGH_COGNITION_PROVIDER_ORDER"


def pytest_configure(config):
    # The loader's gate runs with `-m "not live"`: a boot must not fail
    # because the network, Docker or a browser is not there.
    config.addinivalue_line(
        "markers", "live: needs a real network service, Docker, a browser or this machine's tools")


@pytest.fixture(autouse=True, scope="session")
def _no_ambient_simorgh_env():
    stashed = {k: v for k, v in os.environ.items()
               if (k.startswith(_PREFIX) and k not in _KEEP) or k in _MODEL_CREDENTIALS}
    for key in stashed:
        del os.environ[key]
    os.environ[_FLOOR_ONLY] = "floor"
    try:
        yield
    finally:
        os.environ.pop(_FLOOR_ONLY, None)
        os.environ.update(stashed)
