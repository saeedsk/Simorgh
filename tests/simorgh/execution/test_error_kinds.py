"""Tool results carry a typed `error_kind` (stage 2 item 8, review T9).

Before this, a failure's kind lived only in its words: about 200 sites
wrote `error="refused: ..."`, and three machine consumers read the text
back (`read_file`/`list_dir` checking for "[refused:", orchestration's
`was_denied`, verification's render/js checks matching "no `node`
executable"). These tests pin the replacement:

- no machine consumer in simorgh/ sniffs error text for "refused",
  outside an explicit allow-list that says why each one stays;
- no `ToolResult(ok=False, error="refused...")` is built without a kind;
- the helpers, the service and the wire all carry the kind.
"""

from __future__ import annotations

import ast
import asyncio
import re
import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.registry import ContractError, get_spec
from simorgh.contracts.protocols import ERROR_KINDS, ToolResult, ToolUnconfigured, error_kind_of
from simorgh.execution import pathsafety
from simorgh.execution.service import result_error_kind
from tests.simorgh.execution.test_service import _ExecutionServiceTestCase

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "simorgh"

# A consumer reading "refused" out of an error string: `x.startswith("refused`,
# `x.startswith(("refused", ...))`, `"refused:" in x`, and the bracketed
# "[refused:" spellings pathsafety writes.
_SNIFF = re.compile(r"""startswith\(\(?\s*["']\[?refused|["']\[?refused:?["']\s+in\b""")

#: file -> why the sniff stays. Every entry must still match (no stale rows).
ALLOWED = {
    "simorgh/execution/service.py": (
        "result_error_kind: the producer-side fallback that fills in a kind for a tool that set "
        "none (a skill Sim wrote, an MCP proxy, an external adapter). It runs once, where the "
        "result is made, so no consumer downstream reads the text."),
    "simorgh/interface/httpapi.py": (
        "the dashboard's command endpoint colours an Interface command's reply text "
        "(`dispatch.Outcome`), not an action.result; Interface commands have no kind field yet."),
}


def _sniffers() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if _SNIFF.search(line):
                found.setdefault(path.relative_to(ROOT).as_posix(), []).append(f"{number}: {line.strip()}")
    return found


def _starts_refused(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.startswith("refused")
    if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
        return str(node.values[0].value).startswith("refused")
    if isinstance(node, ast.BinOp) and isinstance(node.left, ast.Constant):
        return str(node.left.value).startswith("refused")
    if isinstance(node, ast.IfExp):
        return _starts_refused(node.body)
    return False


class NoConsumerSniffsErrorText(unittest.TestCase):
    def test_only_the_allow_listed_sniffs_remain(self):
        found = _sniffers()
        unexpected = {path: lines for path, lines in found.items() if path not in ALLOWED}
        self.assertEqual(unexpected, {}, "read `error_kind` instead of the error text (or allow-list it with a reason)")

    def test_the_allow_list_has_no_stale_rows(self):
        found = _sniffers()
        self.assertEqual(sorted(p for p in ALLOWED if p not in found), [])

    def test_no_refusal_is_built_without_a_kind(self):
        offenders = []
        for path in sorted(PACKAGE.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ToolResult"):
                    continue
                kw = {k.arg: k.value for k in node.keywords}
                if "error" in kw and "error_kind" not in kw and _starts_refused(kw["error"]):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(offenders, [], "use ToolResult.refused/unconfigured/transient/failed(...)")


class TheKindTravels(unittest.TestCase):
    def test_helpers_set_ok_false_and_the_kind(self):
        for kind in ERROR_KINDS:
            result = getattr(ToolResult, kind)("why", output="o")
            self.assertEqual((result.ok, result.error, result.error_kind, result.output), (False, "why", kind, "o"))

    def test_an_exception_carries_its_kind(self):
        self.assertEqual(error_kind_of(ToolUnconfigured("pip install x")), "unconfigured")
        self.assertEqual(error_kind_of(ValueError("x")), "failed")
        self.assertEqual(error_kind_of(ValueError("x"), "transient"), "transient")
        self.assertEqual(ToolResult.from_exception(ToolUnconfigured("x"), "refused: x").error_kind, "unconfigured")

    def test_home_assistant_says_which_kind_of_unavailable(self):
        from simorgh.contracts.home.client import HomeUnavailable  # noqa: PLC0415
        from simorgh.contracts.home.fakes import FakeHomeAssistant  # noqa: PLC0415
        with self.assertRaises(HomeUnavailable) as caught:
            asyncio.run(FakeHomeAssistant(configured=False).states())
        self.assertEqual(error_kind_of(caught.exception), "unconfigured")
        with self.assertRaises(HomeUnavailable) as caught:
            asyncio.run(FakeHomeAssistant().call("light.no_such_service"))
        self.assertEqual(error_kind_of(caught.exception), "refused")

    def test_execution_fills_in_a_missing_kind(self):
        self.assertEqual(result_error_kind(ToolResult(ok=True, output="x")), "")
        self.assertEqual(result_error_kind(ToolResult.transient("timeout")), "transient")
        # A tool that predates the field (a skill, an MCP proxy):
        self.assertEqual(result_error_kind(ToolResult(ok=False, error="refused: no")), "refused")
        self.assertEqual(result_error_kind(ToolResult(ok=False, error="[refused: no]")), "refused")
        self.assertEqual(result_error_kind(ToolResult(ok=False, error="it broke")), "failed")

    def test_action_result_takes_the_kind_and_older_records_without_it(self):
        base = {"action_id": "a", "ok": False, "output_ref": "", "stdout_preview": "", "duration_ms": 0,
                "side_effects": [], "error": "refused: x"}
        spec = get_spec(topics.ACTION_RESULT)
        spec.check(dict(base, error_kind="refused"))
        spec.check(base)
        with self.assertRaises(ContractError):
            spec.check(dict(base, error_kind="nope"))

    def test_pathsafety_says_a_refusal_apart_from_content(self):
        content, refusal = pathsafety.read_file_checked(ROOT, "../etc/passwd", readable_roots=("simorgh",))
        self.assertEqual(content, "")
        self.assertTrue(refusal.startswith("[refused:"))
        content, refusal = pathsafety.read_file_checked(ROOT, "simorgh/__init__.py", readable_roots=("simorgh",))
        self.assertEqual(refusal, "")
        listing, refusal = pathsafety.list_dir_checked(ROOT, "nope/../..", readable_roots=("simorgh",))
        self.assertEqual(listing, "")
        self.assertTrue(refusal)


class _Tool:
    def __init__(self, name, run) -> None:
        self.name, self.description, self.args_schema = name, name, {}
        self.read_only, self.reversibility = True, "read_only"
        self._run = run

    async def run(self, args, *, ctx):
        return await self._run()


class TheServicePutsTheKindOnTheWire(_ExecutionServiceTestCase):
    """Through `_on_approved` and a real `action.result`: what a tool
    reports, raises, or leaves out, as the kind a consumer reads."""

    async def _kind_of(self, name, run) -> tuple[str, dict]:
        self.service._registry[name] = _Tool(name, run)  # noqa: SLF001
        seen: list[dict] = []

        async def _on(message):
            if message.payload.get("tool") == name:
                seen.append(message.payload)

        sub = await self.bus.subscribe(topics.ACTION_RESULT, _on)
        self.addAsyncCleanup(sub.unsubscribe)
        result = await self.service._self_actions.run(name, {}, rationale="test", timeout=5)  # noqa: SLF001
        self.assertEqual(len(seen), 1)
        return result.error_kind, seen[0]

    async def test_each_way_a_tool_can_fail(self):
        await self._start()
        await self._guardian(approve=True)

        async def unconfigured():
            return ToolResult.unconfigured("refused: no `node` executable found on this machine")

        async def raises_unconfigured():
            raise ToolUnconfigured("needs pychromecast (pip install pychromecast)")

        async def crashes():
            raise ValueError("a bug")

        async def old_style_refusal():
            return ToolResult(ok=False, error="refused: an old skill's own convention")

        async def ok():
            return ToolResult(ok=True, output="fine")

        for name, run, kind in (("t_unconf", unconfigured, "unconfigured"),
                                ("t_raise", raises_unconfigured, "unconfigured"),
                                ("t_crash", crashes, "failed"),
                                ("t_old", old_style_refusal, "refused")):
            got, payload = await self._kind_of(name, run)
            self.assertEqual((got, payload["error_kind"], payload["ok"]), (kind, kind, False), name)
        got, payload = await self._kind_of("t_ok", ok)
        self.assertEqual(got, "")
        self.assertNotIn("error_kind", payload)


if __name__ == "__main__":
    unittest.main()
