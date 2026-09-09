from .denylist_immunity import DenylistImmunityCheck
from .didanything import DidAnythingCheck
from .docstring import DocstringCheck, docstring_regression_reason
from .fullsuiteran import FullSuiteRanCheck
from .invariants import InvariantsCheck, invariant_violations
from .isolated_suite import IsolatedSuiteCheck
from .sandbox_smoke import SandboxSmokeCheck
from .syntax import SyntaxCheck

ALL_CHECKS = [
    DidAnythingCheck(),
    FullSuiteRanCheck(),
    SyntaxCheck(),
    DenylistImmunityCheck(),
    DocstringCheck(),
    InvariantsCheck(),
    SandboxSmokeCheck(),
    IsolatedSuiteCheck(),
]

__all__ = [
    "ALL_CHECKS",
    "DenylistImmunityCheck",
    "DidAnythingCheck",
    "DocstringCheck",
    "FullSuiteRanCheck",
    "InvariantsCheck",
    "IsolatedSuiteCheck",
    "SandboxSmokeCheck",
    "SyntaxCheck",
    "docstring_regression_reason",
    "invariant_violations",
]
