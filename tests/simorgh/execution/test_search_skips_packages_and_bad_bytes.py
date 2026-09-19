"""search_code, live 2026-09-19: it returned aiohttp from a venv under
workspace/ and failed outright on a non-UTF-8 byte in a skills/ file."""

import shutil
import tempfile
import unittest
from pathlib import Path

from simorgh.execution.config import Config
from simorgh.execution.tools import SearchCodeTool


class SearchSkipsPackagesAndSurvivesBadBytes(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "simorgh").mkdir()
        (self.root / "simorgh" / "mine.py").write_text("from .models import Thing\n")
        venv = self.root / "workspace" / "voice" / "venvs" / "x" / "lib" / "site-packages" / "aiohttp"
        venv.mkdir(parents=True)
        (venv / "reader.py").write_text("from .models import Other\n")
        (self.root / "skills").mkdir()
        (self.root / "skills" / "notes.md").write_bytes(b"from .models import \xff\xfe bad bytes\n")

    def tearDown(self):
        self._tmp.cleanup()

    async def _search(self, rg):
        tool = SearchCodeTool(Config(repo_root=self.root), ripgrep_path=rg)
        return await tool.run({"query": "from .models import"}, ctx=None)

    async def test_ripgrep(self):
        rg = shutil.which("rg")
        if not rg:
            self.skipTest("ripgrep not installed")
        result = await self._search(rg)
        self.assertTrue(result.ok, result.error)
        self.assertIn("simorgh/mine.py", result.output)
        self.assertNotIn("site-packages", result.output)
        self.assertIn("skills/notes.md", result.output)

    async def test_pure_python(self):
        result = await self._search("")
        self.assertTrue(result.ok, result.error)
        self.assertIn("mine.py", result.output)
        self.assertNotIn("site-packages", result.output)
