from .denylist_immunity import DenylistImmunityCheck
from .docstring import DocstringCheck, docstring_regression_reason
from .invariants import InvariantsCheck, invariant_violations
from .isolated_suite import IsolatedSuiteCheck
from .sandbox_smoke import SandboxSmokeCheck
from .syntax import SyntaxCheck

ALL_CHECKS = [
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
    "DocstringCheck",
    "InvariantsCheck",
    "IsolatedSuiteCheck",
    "SandboxSmokeCheck",
    "SyntaxCheck",
    "docstring_regression_reason",
    "invariant_violations",
]
