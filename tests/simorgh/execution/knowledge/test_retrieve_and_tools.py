"""Hybrid retrieval and the `kb_*` tools.

The tools are driven through their real `run()` against a real sqlite
index over a real (tiny) corpus on disk. Nothing is mocked except the
embedder choice, because the thing worth testing is whether a question
actually finds the passage that answers it."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.knowledge.api import SourceSpec
from simorgh.execution.knowledge.embed import (
    Embedder,
    cosine,
    hashing_vector,
    normalise,
)
from simorgh.execution.knowledge.index import Index
from simorgh.execution.knowledge.retrieve import most_privileged, render_passages, search
from simorgh.execution.knowledge.sources import scan_source
from simorgh.execution.knowledge.tools import knowledge_tools


def _ctx(tmp: Path) -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                       data_dir=tmp, clock=None, logger=None, ledger=None)


class EmbedTestCase(unittest.TestCase):
    def test_a_hashing_vector_is_normalised(self):
        vector = hashing_vector("some words here")
        self.assertAlmostEqual(sum(v * v for v in vector) ** 0.5, 1.0, places=5)

    def test_shared_words_score_higher_than_none(self):
        a = hashing_vector("flood cover for the house")
        b = hashing_vector("flood cover limit")
        c = hashing_vector("entirely different subject matter")
        self.assertGreater(cosine(a, b), cosine(a, c))

    def test_an_empty_text_does_not_divide_by_zero(self):
        self.assertEqual(cosine(hashing_vector(""), hashing_vector("")), 0.0)

    def test_mismatched_dimensions_score_zero_rather_than_raising(self):
        self.assertEqual(cosine(normalise([1.0, 0.0]), normalise([1.0, 0.0, 0.0])), 0.0)

    def test_the_hashing_embedder_reports_that_it_is_not_semantic(self):
        """A retrieval system that quietly is not doing what it claims
        is the failure this project keeps calling out."""
        embedder = Embedder("hashing")
        self.assertFalse(embedder.semantic)

    def test_asking_for_the_local_model_without_the_package_degrades_and_says_so(self):
        import unittest.mock

        with unittest.mock.patch("simorgh.execution.knowledge.embed.local_model_available",
                                 lambda: False):
            embedder = Embedder("local")
        self.assertEqual(embedder.provider, "hashing")
        self.assertIn("sentence-transformers", embedder.degraded)

    def test_a_stub_model_is_used_when_one_is_injected(self):
        class _Model:
            def encode(self, text):
                return [1.0, 2.0, 3.0]

        embedder = Embedder("local", model=_Model())
        provider, vector = embedder.embed("anything")
        self.assertEqual(provider, "local")
        self.assertTrue(embedder.semantic)
        self.assertAlmostEqual(sum(v * v for v in vector) ** 0.5, 1.0, places=5)

    def test_a_model_that_raises_degrades_instead_of_breaking_the_index(self):
        class _Broken:
            def encode(self, text):
                raise RuntimeError("cuda is on fire")

        embedder = Embedder("local", model=_Broken())
        provider, vector = embedder.embed("text")
        self.assertEqual(provider, "hashing")
        self.assertTrue(vector)
        self.assertIn("failed", embedder.degraded)


class _IndexedCorpus(unittest.IsolatedAsyncioTestCase):
    """A small, real corpus: a home policy, a car policy, and a receipt."""

    PRIVACY = "personal"

    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.docs = self.root / "docs"
        self.docs.mkdir()
        (self.docs / "home.md").write_text(
            "# Home Insurance Policy\n\n"
            "## Cover\n\nFlood damage is covered up to 5000 pounds each year.\n\n"
            "## Excess\n\nThe excess is 250 pounds on every household claim.\n",
            encoding="utf-8")
        (self.docs / "car.md").write_text(
            "# Car Insurance\n\n## Excess\n\nThe car excess is 500 pounds.\n", encoding="utf-8")
        (self.docs / "receipt.md").write_text(
            "# Boiler service receipt\n\nPaid 180 pounds to Wrenfield Heating on 4 March.\n",
            encoding="utf-8")
        self.index_path = self.root / "index.db"
        self.embedder = Embedder("hashing")
        index = Index(self.index_path)
        spec = SourceSpec(kind="files", path=str(self.docs), privacy=self.PRIVACY)
        index.add_source(spec)
        scan_source(index, spec, embedder=self.embedder)
        index.close()

    async def asyncTearDown(self):
        self._tmp.cleanup()

    def _config(self, **overrides) -> Config:
        return Config(repo_root=self.root, knowledge_index_path=str(self.index_path),
                      knowledge_embedder="hashing", **overrides)

    def _tools(self, **overrides) -> dict:
        return {tool.name: tool for tool in knowledge_tools(
            self._config(**overrides), embedder=self.embedder)}

    def _index(self) -> Index:
        return Index(self.index_path)


class RetrieveTestCase(_IndexedCorpus):
    async def test_a_term_only_in_one_document_finds_it(self):
        with self._index() as index:
            found = search(index, "Wrenfield", embedder=self.embedder)
        self.assertTrue(found.hits)
        self.assertIn("Wrenfield", found.hits[0].chunk.text)

    async def test_every_hit_carries_a_citation_with_a_page(self):
        with self._index() as index:
            found = search(index, "excess", embedder=self.embedder)
        for hit in found.hits:
            self.assertTrue(hit.citation.doc_id)
            self.assertTrue(hit.citation.render().startswith("["))
            self.assertGreaterEqual(hit.citation.page, 1)

    async def test_a_passage_both_retrievers_found_says_so(self):
        with self._index() as index:
            found = search(index, "flood damage covered", embedder=self.embedder)
        self.assertIn(("lexical", "vector"), [hit.found_by for hit in found.hits])

    async def test_lexical_only_when_no_embedder_is_given(self):
        with self._index() as index:
            found = search(index, "excess", embedder=None)
        self.assertTrue(found.hits)
        self.assertEqual({hit.found_by for hit in found.hits}, {("lexical",)})
        self.assertIn("exact-term", found.note)

    async def test_the_hashing_embedder_is_disclosed_in_the_note(self):
        with self._index() as index:
            found = search(index, "excess", embedder=self.embedder)
        self.assertIn("hashing embedder", found.note)

    async def test_an_empty_query_matches_nothing(self):
        with self._index() as index:
            self.assertEqual(search(index, "   ", embedder=self.embedder).hits, [])

    async def test_a_query_matching_nothing_says_so(self):
        with self._index() as index:
            found = search(index, "zygomorphic thaumaturgy", embedder=self.embedder)
        self.assertEqual(found.hits, [])

    async def test_the_order_is_stable_across_identical_searches(self):
        with self._index() as index:
            first = [h.citation.render() for h in search(index, "excess", embedder=self.embedder).hits]
            second = [h.citation.render() for h in search(index, "excess", embedder=self.embedder).hits]
        self.assertEqual(first, second)

    async def test_k_bounds_the_result_count(self):
        with self._index() as index:
            self.assertLessEqual(len(search(index, "pounds", embedder=self.embedder, k=2).hits), 2)

    async def test_vectors_from_a_different_provider_are_not_compared(self):
        """A corpus embedded with one provider and queried with another
        is a real situation -- someone installed the model after
        indexing -- and the honest answer is "not comparable", not a
        ranking built from noise."""
        class _Model:
            def encode(self, text):
                return [0.1] * 384

        with self._index() as index:
            found = search(index, "excess", embedder=Embedder("local", model=_Model()))
        for hit in found.hits:
            self.assertNotIn("vector", hit.found_by)

    async def test_the_strictest_privacy_governs_a_mixed_set(self):
        from simorgh.execution.knowledge.api import Chunk, Citation, Hit

        hits = [Hit(Chunk("d", 0, "x"), Citation("d", "t", "p"), 1.0, privacy="personal"),
                Hit(Chunk("d", 1, "y"), Citation("d", "t", "p"), 0.9, privacy="sensitive")]
        self.assertEqual(most_privileged(hits), "sensitive")

    async def test_rendered_passages_put_the_citation_before_the_text(self):
        with self._index() as index:
            found = search(index, "excess", embedder=self.embedder)
        rendered = render_passages(found.hits)
        self.assertTrue(rendered.startswith("["), "a truncated prompt must still carry the label")

    async def test_rendering_respects_its_character_budget(self):
        with self._index() as index:
            found = search(index, "pounds", embedder=self.embedder)
        self.assertLessEqual(len(render_passages(found.hits, max_chars=300)), 400)


class KbSearchToolTestCase(_IndexedCorpus):
    async def test_it_finds_and_cites(self):
        result = await self._tools()["kb_search"].run({"query": "flood"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.error)
        self.assertIn("Flood damage is covered", result.output)
        self.assertGreater(result.metadata["hits"], 0)

    async def test_results_are_rows_so_query_data_can_aggregate_them(self):
        result = await self._tools()["kb_search"].run({"query": "excess"}, ctx=_ctx(self.root))
        rows = result.metadata["rows"]
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(set(row) >= {"doc_id", "title", "path", "page", "score"}, True)

    async def test_an_empty_query_is_refused(self):
        result = await self._tools()["kb_search"].run({"query": "  "}, ctx=_ctx(self.root))
        self.assertFalse(result.ok)

    async def test_no_match_is_an_honest_success_not_an_error(self):
        result = await self._tools()["kb_search"].run(
            {"query": "zygomorphic thaumaturgy"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok)
        self.assertIn("nothing in your documents", result.output)
        self.assertEqual(result.metadata["hits"], 0)

    async def test_k_is_clamped_to_the_configured_ceiling(self):
        result = await self._tools(knowledge_max_results=2)["kb_search"].run(
            {"query": "pounds", "k": 500}, ctx=_ctx(self.root))
        self.assertLessEqual(result.metadata["hits"], 2)


class KbAskToolTestCase(_IndexedCorpus):
    async def test_it_returns_passages_and_the_instruction_to_cite(self):
        result = await self._tools()["kb_ask"].run(
            {"question": "what is my household excess"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.error)
        self.assertIn("250 pounds", result.output)
        self.assertIn("citation", result.output.lower())
        self.assertFalse(result.metadata["withheld"])

    async def test_with_no_match_it_tells_the_model_not_to_invent_one(self):
        result = await self._tools()["kb_ask"].run(
            {"question": "zygomorphic thaumaturgy"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok)
        self.assertIn("not in your documents", result.output)
        self.assertFalse(result.metadata["answerable"])

    async def test_an_empty_question_is_refused(self):
        result = await self._tools()["kb_ask"].run({"question": ""}, ctx=_ctx(self.root))
        self.assertFalse(result.ok)


class SensitivePrivacyTestCase(_IndexedCorpus):
    """The gate that makes `kb_ask` more than `kb_search`: a passage out
    of a `sensitive` document handed to a caller running on a cloud
    model is exactly the exposure section 10 exists to prevent."""

    PRIVACY = "sensitive"

    async def test_sensitive_passages_are_not_returned_by_default(self):
        result = await self._tools()["kb_ask"].run(
            {"question": "what is my excess"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok)
        self.assertTrue(result.metadata["withheld"])
        self.assertNotIn("250 pounds", result.output)

    async def test_it_says_where_the_answer_is_rather_than_refusing_outright(self):
        result = await self._tools()["kb_ask"].run(
            {"question": "what is my excess"}, ctx=_ctx(self.root))
        self.assertIn("home.md", result.output)
        self.assertIn("knowledge_cloud_llm_may_see", result.output)

    async def test_naming_the_class_in_config_lets_it_through(self):
        tools = self._tools(knowledge_cloud_llm_may_see=("public", "personal", "sensitive"))
        result = await tools["kb_ask"].run({"question": "what is my excess"}, ctx=_ctx(self.root))
        self.assertFalse(result.metadata["withheld"])
        self.assertIn("250 pounds", result.output)

    async def test_kb_search_still_reports_the_class_it_found(self):
        result = await self._tools()["kb_search"].run({"query": "excess"}, ctx=_ctx(self.root))
        self.assertEqual(result.metadata["privacy"], "sensitive")


class KbOpenToolTestCase(_IndexedCorpus):
    async def _a_citation(self) -> str:
        result = await self._tools()["kb_search"].run({"query": "flood"}, ctx=_ctx(self.root))
        row = result.metadata["rows"][0]
        return f"{row['doc_id']}:{row['page']}"

    async def test_it_opens_the_passage_a_citation_points_at(self):
        citation = await self._a_citation()
        result = await self._tools()["kb_open"].run({"citation": citation}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.error)
        self.assertIn("Home Insurance Policy", result.output)

    async def test_brackets_around_the_citation_are_accepted(self):
        citation = await self._a_citation()
        result = await self._tools()["kb_open"].run({"citation": f"[{citation}]"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.error)

    async def test_a_bare_document_id_works_too(self):
        citation = (await self._a_citation()).split(":")[0]
        result = await self._tools()["kb_open"].run({"citation": citation}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.error)

    async def test_an_unknown_citation_says_what_a_citation_looks_like(self):
        result = await self._tools()["kb_open"].run({"citation": "nope"}, ctx=_ctx(self.root))
        self.assertFalse(result.ok)
        self.assertIn("kb_search", result.error)

    async def test_it_shows_neighbours_and_says_how_many_there_are(self):
        citation = await self._a_citation()
        result = await self._tools()["kb_open"].run(
            {"citation": citation, "around": 5}, ctx=_ctx(self.root))
        self.assertGreaterEqual(result.metadata["passages"], 1)
        self.assertGreaterEqual(result.metadata["of"], result.metadata["passages"])


class KbSourcesToolTestCase(_IndexedCorpus):
    async def test_list_shows_the_source_and_when_it_was_scanned(self):
        result = await self._tools()["kb_sources"].run({"op": "list"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.error)
        self.assertIn(str(self.docs), result.output)
        self.assertEqual(len(result.metadata["rows"]), 1)

    async def test_add_says_that_nothing_has_been_read_yet(self):
        other = self.root / "other"
        other.mkdir()
        (other / "note.md").write_text("# Note\n\nsomething\n", encoding="utf-8")
        result = await self._tools()["kb_sources"].run(
            {"op": "add", "path": str(other)}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.error)
        self.assertIn("Nothing has been read yet", result.output)

    async def test_adding_a_path_that_does_not_exist_is_refused(self):
        result = await self._tools()["kb_sources"].run(
            {"op": "add", "path": str(self.root / "nowhere")}, ctx=_ctx(self.root))
        self.assertFalse(result.ok)
        self.assertIn("does not exist", result.error)

    async def test_an_unknown_privacy_class_is_refused(self):
        result = await self._tools()["kb_sources"].run(
            {"op": "add", "path": str(self.docs), "privacy": "topsecret"}, ctx=_ctx(self.root))
        self.assertFalse(result.ok)

    async def test_scan_reports_what_it_did(self):
        result = await self._tools()["kb_sources"].run({"op": "scan"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.error)
        self.assertIn("file(s) seen", result.output)

    async def test_remove_takes_the_documents_with_it(self):
        tools = self._tools()
        result = await tools["kb_sources"].run(
            {"op": "remove", "name": f"files:{self.docs}"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.metadata["documents_removed"], 3)
        after = await tools["kb_search"].run({"query": "flood"}, ctx=_ctx(self.root))
        self.assertEqual(after.metadata["hits"], 0)

    async def test_removing_something_that_is_not_a_source_lists_what_is(self):
        result = await self._tools()["kb_sources"].run(
            {"op": "remove", "name": "not-a-source"}, ctx=_ctx(self.root))
        self.assertFalse(result.ok)
        self.assertIn("known:", result.error)

    async def test_an_unknown_op_is_refused_with_the_real_ones(self):
        result = await self._tools()["kb_sources"].run({"op": "obliterate"}, ctx=_ctx(self.root))
        self.assertFalse(result.ok)
        self.assertIn("list, add, remove or scan", result.error)


class KbStatusToolTestCase(_IndexedCorpus):
    async def test_it_reports_counts_sources_and_the_embedder(self):
        result = await self._tools()["kb_status"].run({}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.error)
        self.assertIn("3 document(s)", result.output)
        self.assertIn("embedder: hashing", result.output)
        self.assertIn("matches shared words, not meaning", result.output)

    async def test_it_says_when_a_source_was_last_scanned(self):
        result = await self._tools()["kb_status"].run({}, ctx=_ctx(self.root))
        self.assertIn(str(self.docs), result.output)
        self.assertNotIn("last scan: never", result.output)


class EmptyIndexTestCase(unittest.IsolatedAsyncioTestCase):
    """The state the feature ships in. An unconfigured knowledge base
    must say what to add -- a tool that answers "0 results" to someone
    who never pointed it at anything has told them nothing."""

    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    async def asyncTearDown(self):
        self._tmp.cleanup()

    def _tools(self) -> dict:
        config = Config(repo_root=self.root, knowledge_index_path=str(self.root / "kb.db"),
                        knowledge_embedder="hashing")
        return {tool.name: tool for tool in knowledge_tools(config)}

    async def test_search_says_how_to_add_a_source(self):
        result = await self._tools()["kb_search"].run({"query": "anything"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok)
        self.assertIn("KB_SOURCES: add", result.output)

    async def test_ask_says_how_to_add_a_source(self):
        result = await self._tools()["kb_ask"].run({"question": "anything"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok)
        self.assertIn("KB_SOURCES", result.output)

    async def test_status_works_on_an_empty_index(self):
        result = await self._tools()["kb_status"].run({}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.error)
        self.assertIn("0 document(s)", result.output)

    async def test_the_index_file_is_created_on_demand_not_at_boot(self):
        tools = self._tools()
        self.assertFalse((self.root / "kb.db").exists(), "constructing a tool must not litter")
        await tools["kb_status"].run({}, ctx=_ctx(self.root))
        self.assertTrue((self.root / "kb.db").exists())


class ScanOffTheEventLoopTestCase(_IndexedCorpus):
    """A scan parses and embeds every file in a folder, so it runs in a
    worker thread. sqlite connections are thread-bound by default, and
    every real scan raised "SQLite objects created in a thread can only
    be used in that same thread" until the connection said otherwise --
    a bug no amount of testing the scanner directly could find, because
    the scanner is not the thing that crosses the thread."""

    async def test_a_scan_through_the_tool_actually_completes(self):
        (self.docs / "new.md").write_text("# New\n\ndistinct-scan-token\n", encoding="utf-8")
        tools = self._tools()
        result = await tools["kb_sources"].run({"op": "scan"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.error)
        self.assertGreaterEqual(result.metadata["added"], 1)
        found = await tools["kb_search"].run({"query": "distinct-scan-token"}, ctx=_ctx(self.root))
        self.assertGreater(found.metadata["hits"], 0)

    async def test_two_scans_in_a_row_do_not_leave_the_connection_broken(self):
        tools = self._tools()
        for _ in range(2):
            result = await tools["kb_sources"].run({"op": "scan"}, ctx=_ctx(self.root))
            self.assertTrue(result.ok, result.error)
