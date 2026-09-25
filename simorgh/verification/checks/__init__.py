"""Verification checks for Simorgh's self-patch pipeline.

Checks in ALL_CHECKS are ordered cheapest/fastest first so the pipeline
fails fast: trivial syntactic and structural checks (syntax, narration,
did-anything) run before expensive ones (sandbox smoke tests, isolated
test suites, browser rendering). If an early cheap check fails, the
later costly checks are skipped entirely, saving time and compute on
patches that were never going to pass.
"""
from .denylist_immunity import DenylistImmunityCheck
from .didanything import DidAnythingCheck
from .docstring import DocstringCheck, docstring_regression_reason
from .fullsuiteran import FullSuiteRanCheck
from .invariants import InvariantsCheck, invariant_violations
from .isolated_suite import IsolatedSuiteCheck
from .js_syntax import JsSyntaxCheck
from .render import RenderCheck
from .sandbox_smoke import SandboxSmokeCheck
from .syntax import SyntaxCheck
from .trailing_narration import TrailingNarrationCheck

# Ordered fast/cheap first so we fail fast before expensive checks run.
ALL_CHECKS = [
    DidAnythingCheck(),
    SyntaxCheck(),
    TrailingNarrationCheck(),
    DocstringCheck(),
    DenylistImmunityCheck(),
    InvariantsCheck(),
    JsSyntaxCheck(),
    FullSuiteRanCheck(),
    SandboxSmokeCheck(),
    IsolatedSuiteCheck(),
    RenderCheck(),
]

__all__ = [
    "ALL_CHECKS",
    "DenylistImmunityCheck",
    "DidAnythingCheck",
    "DocstringCheck",
    "FullSuiteRanCheck",
    "InvariantsCheck",
    "IsolatedSuiteCheck",
    "JsSyntaxCheck",
    "RenderCheck",
    "SandboxSmokeCheck",
    "SyntaxCheck",
    "TrailingNarrationCheck",
    "docstring_regression_reason",
    "invariant_violations",
]
