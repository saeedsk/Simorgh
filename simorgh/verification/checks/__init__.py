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

ALL_CHECKS = [
    DidAnythingCheck(),
    FullSuiteRanCheck(),
    SyntaxCheck(),
    TrailingNarrationCheck(),
    DenylistImmunityCheck(),
    DocstringCheck(),
    InvariantsCheck(),
    SandboxSmokeCheck(),
    JsSyntaxCheck(),
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
