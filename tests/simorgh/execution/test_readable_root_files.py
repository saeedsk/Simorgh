"""`[execution] readable_root_files` reaches the read tools.

`pathsafety` used to check root files against its own hardcoded
`ROOT_FILES`, so the config key parsed and changed nothing
(docs/findings/2026-09-19-contract-writing.md). These pin both
directions: a file the config adds is readable, and a default root file
the config leaves out is refused."""

import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.tools import ReadFileTool


def _ctx(config: Config) -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                       data_dir=config.repo_root, clock=None, logger=None, ledger=None)


class TestReadableRootFiles(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "NOTES.md").write_text("configured root file")
        (self.root / "README.md").write_text("default root file")

    def tearDown(self):
        self._tmp.cleanup()

    def _config(self, files):
        return Config.from_mapping({"repo_root": str(self.root), "readable_root_files": files})

    async def test_a_root_file_named_in_config_is_readable(self):
        config = self._config(["NOTES.md"])
        result = await ReadFileTool(config).run({"path": "NOTES.md"}, ctx=_ctx(config))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output, "configured root file")

    async def test_a_line_range_read_honours_the_config_too(self):
        config = self._config(["NOTES.md"])
        result = await ReadFileTool(config).run({"path": "NOTES.md:1-1"}, ctx=_ctx(config))
        self.assertTrue(result.ok, result.error)
        self.assertIn("configured root file", result.output)

    async def test_a_default_root_file_left_out_of_config_is_refused(self):
        config = self._config(["NOTES.md"])
        result = await ReadFileTool(config).run({"path": "README.md"}, ctx=_ctx(config))
        self.assertFalse(result.ok)
        self.assertIn("outside the readable areas", result.error)
        self.assertIn("NOTES.md", result.error)

    async def test_the_default_config_still_reads_readme(self):
        config = Config.from_mapping({"repo_root": str(self.root)})
        result = await ReadFileTool(config).run({"path": "README.md"}, ctx=_ctx(config))
        self.assertTrue(result.ok, result.error)


if __name__ == "__main__":
    unittest.main()
