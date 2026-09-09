"""`execution/external.py`: open-source toolset adapters behind the Tool
protocol. No real LangChain/pydantic_ai/Composio here -- the fakes below
have exactly the attribute shapes the adapters read (`name`/`description`/
`run`, `.tools`/`.function`, `get_tools()`), which is the whole contract;
the real packages are optional imports resolved by string at runtime."""

from __future__ import annotations

import unittest
from pathlib import Path

from simorgh.execution.config import Config
from simorgh.execution.external import ExternalToolSpec, adapt, load_external_tools


def _ctx():
    from simorgh.contracts.protocols import ToolContext
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={}, data_dir=Path.cwd(),
                       clock=None, logger=None, ledger=None)


# -- fakes with the real frameworks' attribute shapes ------------------------------

def word_count(text: str) -> int:
    """Count words."""
    return len(text.split())


def add(a: int, b: int) -> int:
    """Add two numbers (multi-arg callable: takes a JSON object input)."""
    return a + b


async def shout(text: str) -> str:
    return text.upper()


class FakeLangChainTool:
    name = "duckduckgo_search"
    description = "Search the web."

    def run(self, tool_input: str) -> str:
        return f"results for {tool_input}"


class FakeLangChainInvokeOnly:
    name = "Wikipedia Query"
    description = "Look things up."

    def invoke(self, tool_input: str) -> str:
        return f"wiki:{tool_input}"


class _PaiTool:
    def __init__(self, fn, description):
        self.function = fn
        self.description = description


class FakePydanticToolset:
    def __init__(self):
        self.tools = {"count": _PaiTool(word_count, "count words"), "add": _PaiTool(add, "add")}


class FakeComposioToolSet:
    def get_tools(self, actions=()):
        return [FakeLangChainTool()]


class Exploding:
    name = "boom"
    description = "always fails"

    def run(self, tool_input: str) -> str:
        raise RuntimeError("upstream down")


_HERE = "tests.simorgh.execution.test_external"


class TestAdapters(unittest.IsolatedAsyncioTestCase):
    async def test_a_plain_callable_becomes_a_single_input_tool(self):
        tools = adapt(ExternalToolSpec(import_path=f"{_HERE}:word_count", kind="callable"))
        self.assertEqual([t.name for t in tools], ["word_count"])
        self.assertEqual(tools[0].description, "Count words.")
        self.assertEqual(tools[0].provider, "external")
        result = await tools[0].run({"input": "one two three"}, ctx=_ctx())
        self.assertTrue(result.ok)
        self.assertEqual(result.output, "3")

    async def test_a_multi_arg_callable_takes_a_json_object_input(self):
        tools = adapt(ExternalToolSpec(import_path=f"{_HERE}:add"))
        result = await tools[0].run({"input": '{"a": 2, "b": 3}'}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output, "5")

    async def test_an_async_callable_is_awaited(self):
        tools = adapt(ExternalToolSpec(import_path=f"{_HERE}:shout"))
        result = await tools[0].run({"input": "hi"}, ctx=_ctx())
        self.assertEqual(result.output, "HI")

    async def test_a_langchain_tool_class_is_instantiated_and_run(self):
        tools = adapt(ExternalToolSpec(import_path=f"{_HERE}:FakeLangChainTool", kind="langchain"))
        self.assertEqual(tools[0].name, "duckduckgo_search")
        self.assertEqual(tools[0].description, "Search the web.")
        result = await tools[0].run({"input": "amazon"}, ctx=_ctx())
        self.assertEqual(result.output, "results for amazon")

    async def test_a_langchain_tool_with_only_invoke_and_an_unsafe_name(self):
        tools = adapt(ExternalToolSpec(import_path=f"{_HERE}:FakeLangChainInvokeOnly"))  # kind=auto
        self.assertEqual(tools[0].name, "wikipedia_query")
        result = await tools[0].run({"input": "attar"}, ctx=_ctx())
        self.assertEqual(result.output, "wiki:attar")

    async def test_a_pydantic_ai_toolset_expands_into_one_tool_per_function(self):
        tools = adapt(ExternalToolSpec(import_path=f"{_HERE}:FakePydanticToolset", kind="pydantic_ai"))
        self.assertEqual(sorted(t.name for t in tools), ["add", "count"])
        by_name = {t.name: t for t in tools}
        self.assertEqual((await by_name["count"].run({"input": "a b"}, ctx=_ctx())).output, "2")
        self.assertEqual((await by_name["add"].run({"input": '{"a": 1, "b": 1}'}, ctx=_ctx())).output, "2")

    async def test_a_composio_toolset_is_unwrapped_through_get_tools(self):
        tools = adapt(ExternalToolSpec(import_path=f"{_HERE}:FakeComposioToolSet", kind="composio",
                                       kwargs={"actions": ["X"]}))
        self.assertEqual(tools[0].name, "duckduckgo_search")

    async def test_spec_reversibility_and_read_only_flow_onto_the_tool(self):
        tools = adapt(ExternalToolSpec(import_path=f"{_HERE}:word_count", reversibility="read_only", read_only=True))
        self.assertEqual(tools[0].reversibility, "read_only")
        self.assertTrue(tools[0].read_only)

    async def test_default_reversibility_is_the_fail_safe_irreversible_tier(self):
        """Live-caught, 2026-09-08: the default used to be "reversible",
        so any `[[execution.external_tools]]` entry with no explicit
        `reversibility` got Guardian's `ReversibilityRule` auto-allow in
        guarded mode with no human in the loop -- proven end to end with
        a `kind="callable"` wrapper around `os.remove` that deleted a
        real file with zero escalation. `mcp.py` already defaults new
        tools to "irreversible" unless explicitly allowlisted read_only;
        external.py must match that fail-safe posture, since an
        unconfigured external tool is, by definition, one nobody has
        vetted yet."""
        spec = ExternalToolSpec(import_path=f"{_HERE}:word_count")
        self.assertEqual(spec.reversibility, "irreversible")
        self.assertFalse(spec.read_only)
        tools = adapt(spec)
        self.assertEqual(tools[0].reversibility, "irreversible")

        mapped = ExternalToolSpec.from_mapping({"import_path": f"{_HERE}:word_count"})
        self.assertEqual(mapped.reversibility, "irreversible")

    async def test_an_upstream_exception_is_a_result_not_a_crash(self):
        tools = adapt(ExternalToolSpec(import_path=f"{_HERE}:Exploding", kind="langchain"))
        result = await tools[0].run({"input": "x"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("upstream down", result.error)


class TestLoading(unittest.TestCase):
    def test_a_missing_package_is_skipped_with_a_warning_not_a_boot_failure(self):
        warnings: list = []

        class _Log:
            def warning(self, event, **f):
                warnings.append((event, f))

        tools = load_external_tools((
            ExternalToolSpec(import_path="langchain_community_definitely_not_installed.tools:X"),
            ExternalToolSpec(import_path=f"{_HERE}:word_count"),
        ), logger=_Log())
        self.assertEqual([t.name for t in tools], ["word_count"])
        self.assertEqual(warnings[0][0], "external_tool_load_failed")

    def test_config_from_mapping_parses_external_tools(self):
        config = Config.from_mapping({"external_tools": [
            {"import_path": f"{_HERE}:word_count", "kind": "callable", "reversibility": "read_only"},
        ]})
        self.assertEqual(len(config.external_tools), 1)
        self.assertEqual(config.external_tools[0].reversibility, "read_only")

    def test_an_unknown_kind_is_rejected_at_config_time(self):
        with self.assertRaises(ValueError):
            ExternalToolSpec.from_mapping({"import_path": "x:y", "kind": "magic"})


if __name__ == "__main__":
    unittest.main()
