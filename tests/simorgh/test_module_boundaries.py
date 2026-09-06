"""The import-boundary rules from docs/blueprint/02-system-architecture.md
section 4, enforced by AST rather than convention:

1. A subsystem package (`simorgh.<x>`, any package other than the four
   below) may import `simorgh.contracts.*`, `simorgh.bus.client`,
   `simorgh.ledger.client`, the standard library, and itself.
2. `simorgh.contracts` imports only the standard library (and itself).
3. `simorgh.bus` and `simorgh.ledger` import only `simorgh.contracts`,
   the standard library, and themselves.
4. `simorgh.kernel` -- the composition root -- and the top-level
   `simorgh/__init__.py` / `simorgh/__main__.py` may import any
   `simorgh.*`.
5. No third-party import anywhere under `simorgh/`, except one guarded
   by `try: ... except ImportError` (an optional adapter).

`violations()` is parameterized on a root directory so the checker can
be exercised against a temporary tree (see `TestCheckerSelfTest`) --
a boundary test that has never been seen to fail is not evidence of
anything.
"""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "simorgh"
SUBSTRATE_CLIENTS = ("bus.client", "ledger.client")  # relative to the package
COMPOSITION_ROOTS = {"kernel", "__init__", "__main__"}
STDLIB = set(sys.stdlib_module_names) | set(sys.builtin_module_names)


def _module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _top_package(module: str) -> str:
    """`simorgh.planning.service` -> `planning`; `simorgh` -> `__init__`."""
    parts = module.split(".")
    if len(parts) == 1:
        return "__init__"
    if parts[1] == "__main__":
        return "__main__"
    return parts[1]


def _is_allowed(importer: str, target: str) -> bool:
    top = target.split(".")[0]
    if top in STDLIB:
        return True
    if top != PACKAGE:
        return False  # third-party (unless guarded; handled by caller)
    importer_pkg = _top_package(importer)
    target_pkg = _top_package(target)
    if importer_pkg in COMPOSITION_ROOTS:
        return True
    if target_pkg == importer_pkg or target == PACKAGE:
        return True
    if target_pkg == "contracts":
        return True  # everyone may import contracts (contracts itself was handled above)
    if importer_pkg in {"contracts", "bus", "ledger"}:
        return False  # contracts: stdlib only; bus/ledger: contracts + self only
    # any other subsystem: the substrate's type-level clients only
    return target in {f"{PACKAGE}.{client}" for client in SUBSTRATE_CLIENTS}


def _guarded_by_import_error(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    current = parents.get(id(node))
    while current is not None:
        if isinstance(current, ast.Try):
            for handler in current.handlers:
                names: list[str] = []
                if handler.type is None:
                    continue
                if isinstance(handler.type, ast.Name):
                    names = [handler.type.id]
                elif isinstance(handler.type, ast.Tuple):
                    names = [e.id for e in handler.type.elts if isinstance(e, ast.Name)]
                if "ImportError" in names or "ModuleNotFoundError" in names:
                    return True
        current = parents.get(id(current))
    return False


def _resolve_relative(module: str, is_package: bool, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    base = module.split(".")
    if not is_package:
        base = base[:-1]
    if node.level > 1:
        base = base[: len(base) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def violations(root: Path, package: str = PACKAGE) -> list[str]:
    """Every rule-breaking import under `root/<package>/`, as
    `"<module>: <target>"` strings."""
    global PACKAGE
    previous, PACKAGE = PACKAGE, package
    try:
        found: list[str] = []
        pkg_root = root / package
        for path in sorted(pkg_root.rglob("*.py")):
            module = _module_name(root, path)
            is_package = path.name == "__init__.py"
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            parents: dict[int, ast.AST] = {}
            for parent in ast.walk(tree):
                for child in ast.iter_child_nodes(parent):
                    parents[id(child)] = parent
            for node in ast.walk(tree):
                targets: list[str] = []
                if isinstance(node, ast.Import):
                    targets = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    resolved = _resolve_relative(module, is_package, node)
                    targets = [resolved] if resolved else []
                for target in targets:
                    if _is_allowed(module, target):
                        continue
                    if target.split(".")[0] not in (package,) and _guarded_by_import_error(node, parents):
                        continue  # optional third-party adapter
                    found.append(f"{module}: {target}")
        return found
    finally:
        PACKAGE = previous


class TestRepositoryBoundaries(unittest.TestCase):
    def test_no_subsystem_imports_another(self):
        self.assertEqual(violations(REPO_ROOT), [])


class TestCheckerSelfTest(unittest.TestCase):
    def _tree(self, files: dict[str, str]) -> Path:
        tmp = Path(tempfile.mkdtemp())
        for rel, text in files.items():
            path = tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return tmp

    def test_detects_a_subsystem_importing_another(self):
        root = self._tree({
            "pkg/__init__.py": "",
            "pkg/contracts/__init__.py": "",
            "pkg/planning/__init__.py": "",
            "pkg/planning/service.py": "from pkg.contracts import Message\nimport pkg.execution\n",
            "pkg/execution/__init__.py": "",
        })
        self.assertEqual(violations(root, "pkg"), ["pkg.planning.service: pkg.execution"])

    def test_relative_imports_are_resolved(self):
        root = self._tree({
            "pkg/__init__.py": "",
            "pkg/contracts/__init__.py": "",
            "pkg/planning/__init__.py": "",
            "pkg/planning/service.py": "from . import api\nfrom ..contracts import topics\nfrom ..execution import x\n",
            "pkg/planning/api.py": "",
            "pkg/execution/__init__.py": "",
        })
        self.assertEqual(violations(root, "pkg"), ["pkg.planning.service: pkg.execution"])

    def test_contracts_may_not_import_a_subsystem_or_third_party(self):
        root = self._tree({
            "pkg/__init__.py": "",
            "pkg/contracts/__init__.py": "import json\nimport pkg.bus\nimport requests\n",
            "pkg/bus/__init__.py": "",
        })
        self.assertEqual(sorted(violations(root, "pkg")), ["pkg.contracts: pkg.bus", "pkg.contracts: requests"])

    def test_bus_may_import_contracts_only(self):
        root = self._tree({
            "pkg/__init__.py": "",
            "pkg/contracts/__init__.py": "",
            "pkg/bus/__init__.py": "from pkg.contracts import Message\nfrom pkg.ledger.client import L\n",
            "pkg/ledger/__init__.py": "",
            "pkg/ledger/client.py": "",
        })
        self.assertEqual(violations(root, "pkg"), ["pkg.bus: pkg.ledger.client"])

    def test_subsystem_may_use_substrate_clients_and_kernel_may_import_anything(self):
        root = self._tree({
            "pkg/__init__.py": "",
            "pkg/__main__.py": "from pkg.kernel import main\n",
            "pkg/contracts/__init__.py": "",
            "pkg/bus/client.py": "",
            "pkg/ledger/client.py": "",
            "pkg/memory/service.py": "from pkg.bus.client import BusClient\nfrom pkg.ledger.client import LedgerClient\nfrom pkg.contracts import topics\n",
            "pkg/kernel/__init__.py": "import pkg.memory.service\nimport pkg.bus\n",
        })
        self.assertEqual(violations(root, "pkg"), [])

    def test_third_party_allowed_only_when_guarded(self):
        root = self._tree({
            "pkg/__init__.py": "",
            "pkg/bus/__init__.py": "",
            "pkg/bus/aws.py": "try:\n    import boto3\nexcept ImportError:\n    boto3 = None\nimport requests\n",
        })
        self.assertEqual(violations(root, "pkg"), ["pkg.bus.aws: requests"])


if __name__ == "__main__":
    unittest.main()
