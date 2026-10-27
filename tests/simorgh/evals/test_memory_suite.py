"""Stage 15 items 4, 5 and 5b: the memory suite and its two sidecars.

The suite is pinned on what it could get wrong without anybody noticing:
a corpus that cannot answer its own questions, a check that passes an
empty block, a sidecar that runs (or fails) when its package is absent,
one that spends past its cap, and telemetry left on. Neither sidecar's
package is installed here; both are driven through fake modules put in
`sys.modules`, which is also how a run without them is proved to skip.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import types
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from simorgh.evals.api import SKIPPED
from simorgh.evals.memory import corpus
from simorgh.evals.memory.corpus import CATEGORIES, QUESTIONS, Question, episodes
from simorgh.evals.memory.meter import CapReached, Meter, MeteredClient, metered
from simorgh.evals.memory.native import GRAPH_KEYS, Native, NativeGraph, block_lines
from simorgh.evals.memory.score import PAST, check, norm
from simorgh.evals.memory.sidecar import Settings
from simorgh.evals.memory.suite import dry_run, main, run_system
from simorgh.evals.suites import PAID, SUITES

_SETTINGS = Settings(api_key="test-key", model="m", base_url="http://127.0.0.1:9/v1", embed_model="e",
                     price_in=1.0, price_out=1.0, embed_api_key="embed-key")


def _usage(tokens_in: int, tokens_out: int = 0):
    return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=tokens_in, completion_tokens=tokens_out))


class TheCorpus(unittest.TestCase):
    def test_size_and_categories_are_the_plans(self):
        month = episodes()
        self.assertEqual(len(month), 150)
        self.assertTrue(40 <= len(QUESTIONS) <= 60, len(QUESTIONS))
        self.assertEqual({q.category for q in QUESTIONS}, set(CATEGORIES))
        self.assertEqual(len({q.id for q in QUESTIONS}), len(QUESTIONS))
        self.assertEqual(month, episodes(), "seeded: two runs are the same month")

    def test_people_are_invented(self):
        text = " ".join(e.text for e in episodes()) + " ".join(q.text for q in QUESTIONS)
        for real in ("Soodeh", "Aran", "Iris", "Saeed"):
            self.assertNotIn(real, text)

    def test_every_expected_value_was_said(self):
        said = norm(" ".join(e.text for e in episodes()))
        for q in QUESTIONS:
            for group in q.expect:
                for value in group:
                    self.assertIn(norm(value), said, q.id)

    def test_privacy_values_live_only_in_somebody_elses_private_episode(self):
        for q in (q for q in QUESTIONS if q.category == "privacy"):
            (value,) = q.forbid[0]
            holders = [e for e in episodes() if norm(value) in norm(e.text)]
            self.assertTrue(holders, q.id)
            for e in holders:
                self.assertTrue(e.private, q.id)
                self.assertNotEqual(e.speaker, q.asker, q.id)


class TheCheck(unittest.TestCase):
    Q = Question(id="q", category="temporal_now", asker="mara", text="?", expect=(("Wednesday",),),
                 stale=("Monday",))

    def test_an_empty_block_never_passes_an_expectation(self):
        self.assertEqual(check(self.Q, []), (False, "missing Wednesday"))

    def test_the_old_value_may_appear_only_as_past(self):
        self.assertTrue(check(self.Q, ["bins day Wednesday", f"{PAST}bins day Monday"])[0])
        self.assertFalse(check(self.Q, ["bins day Wednesday", "bins day Monday"])[0])

    def test_a_forbidden_group_needs_every_string_on_one_line(self):
        q = Question(id="n", category="negative", asker="mara", text="?", forbid=(("Otto", "Tuesday"),))
        self.assertTrue(check(q, ["Nellie swimming Tuesdays", "Otto best friend Felix"])[0])
        self.assertFalse(check(q, ["Otto swimming Tuesdays"])[0])

    def test_numbers_compare_without_punctuation(self):
        q = Question(id="p", category="alias", asker="mara", text="?", expect=(("0612 448 190",),))
        self.assertTrue(check(q, ["Bram's number is 0612-448-190"])[0])

    def test_a_native_block_puts_the_replaced_value_on_a_past_line(self):
        lines = block_lines([{"id": "1", "subject": "wifi", "predicate": "is", "object": "new", "person_scope": "*",
                              "was": "old"}, {"id": "2", "subject": "x", "predicate": "y", "object": "z",
                                              "person_scope": "mara", "hop": 2}])
        self.assertEqual(lines, ["wifi is new", f"{PAST}wifi is old", "mara: x y z [hop 2]"])


class NativeRunsFree(unittest.TestCase):
    def test_native_answers_from_the_real_memory_service(self):
        result = asyncio.run(run_system(Native(), episodes()))
        self.assertFalse(result.skipped)
        cats = result.by_category()
        self.assertEqual(result.report.total, len(QUESTIONS))
        # What a fact store keyed by (scope, subject, predicate) gives by
        # construction: corrections win, scopes hold, nothing is invented.
        for category in ("temporal_now", "temporal_before", "privacy", "negative"):
            self.assertEqual(cats[category]["passed"], cats[category]["total"], category)
        self.assertLess(result.report.seconds, 120)

    def test_native_graph_skips_by_name_until_the_keys_exist(self):
        from simorgh.memory.config import Config

        if all(k in Config.__dataclass_fields__ for k in GRAPH_KEYS):
            self.skipTest("stage 15 items 1-3 are merged; native_graph runs")
        result = asyncio.run(run_system(NativeGraph(), episodes()))
        self.assertIn("entities", result.skipped)
        self.assertTrue(all(o.status == SKIPPED for o in result.report.outcomes))
        self.assertEqual(GRAPH_KEYS, {"entities": True, "graph_hops": 2})


class TheMeter(unittest.TestCase):
    def test_every_create_is_charged_and_the_cap_stops_the_next_call(self):
        calls = []

        async def create(**kwargs):
            calls.append(kwargs)
            return _usage(600_000, 0)

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                                 base_url="http://x")
        meter = Meter(cap_usd=1.0, price_in=1.0, price_out=1.0)
        metered = MeteredClient(client, meter)
        self.assertEqual(metered.base_url, "http://x")
        asyncio.run(metered.chat.completions.create(model="m"))
        asyncio.run(metered.chat.completions.create(model="m"))
        self.assertEqual((meter.calls, meter.tokens_in), (2, 1_200_000))
        with self.assertRaises(CapReached):
            asyncio.run(metered.chat.completions.create(model="m"))
        self.assertEqual(len(calls), 2, "the call past the cap was never made")

    def test_a_cap_that_is_not_a_finite_positive_number_stops_the_first_call(self):
        # `nan` compares false with everything, so `usd >= nan` never stopped.
        for cap in (float("nan"), float("inf"), 0.0, -1.0):
            with self.subTest(cap=cap), self.assertRaises(CapReached):
                Meter(cap_usd=cap, price_in=1.0, price_out=1.0).check()

    def test_a_response_without_usage_is_charged_the_estimate(self):
        meter = Meter(cap_usd=0.01, price_in=1.0, price_out=1.0, reserve_in=4_000, reserve_out=1_000)
        create = metered(lambda **kw: SimpleNamespace(), meter)
        made = 0
        with self.assertRaises(CapReached):
            for _ in range(100):
                create()
                made += 1
        self.assertEqual(made, 2, "5,000 tokens a call at $1/M reaches a $0.01 cap on the second")
        self.assertEqual(meter.unmetered, 2)

    def test_calls_in_flight_count_against_the_cap(self):
        # A library that gathers twenty calls at once must not start all
        # twenty on a cap that pays for two.
        meter = Meter(cap_usd=2.0, price_in=1_000_000.0, price_out=0.0, reserve_in=1)
        started = []

        async def create(**kw):
            started.append(kw)
            await asyncio.sleep(0.01)
            return _usage(1)

        call = metered(create, meter)

        async def burst():
            return await asyncio.gather(*[call() for _ in range(20)], return_exceptions=True)

        results = asyncio.run(burst())
        self.assertEqual(len(started), 2)
        self.assertEqual(sum(isinstance(r, CapReached) for r in results), 18)
        self.assertEqual((meter.inflight, meter.usd), (0, 2.0))

    def test_a_sidecar_with_a_nan_cap_is_skipped_and_the_command_line_refuses_it(self):
        from simorgh.evals.memory.graphiti_side import GraphitiSide

        store: dict = {}
        with mock.patch.dict(sys.modules, _fake_graphiti_modules(store)), mock.patch.dict(os.environ, {}):
            side = GraphitiSide(paid=True, cap_usd=float("nan"), settings=_SETTINGS)
            result = asyncio.run(run_system(side, episodes()[:3]))
        self.assertIn("cap", result.skipped)
        self.assertNotIn("episodes", store)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--systems", "graphiti", "--paid", "--cap-usd", "nan"]), 2)


def _fake_graphiti_modules(store: dict) -> dict[str, types.ModuleType]:
    """Just enough of graphiti_core, openai and redislite to drive the sidecar."""

    class Graphiti:
        def __init__(self, *, graph_driver, llm_client, embedder, cross_encoder):
            self.llm_client = llm_client
            store["graphiti"] = self

        async def build_indices_and_constraints(self):
            pass

        async def add_episode(self, **kw):
            store.setdefault("episodes", []).append(kw)
            await self.llm_client.client.chat.completions.create(model="m")

        async def search(self, query, group_ids=None, num_results=10):
            store.setdefault("searches", []).append((query, group_ids))
            return [SimpleNamespace(fact="wifi password is copper-meadow-17", invalid_at=None, expired_at=None),
                    SimpleNamespace(fact="wifi password is heron-lantern-42", invalid_at="2026-03-27",
                                    expired_at=None)]

        async def close(self):
            store["closed"] = True

    class Holder:
        def __init__(self, *a, config=None, client=None, **kw):
            self.config, self.client = config, client

    async def create(**kw):
        return _usage(1_000, 100)

    def async_openai(**kw):
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                               embeddings=SimpleNamespace(create=create))

    def module(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        return m

    return {
        "graphiti_core": module("graphiti_core", Graphiti=Graphiti),
        "graphiti_core.cross_encoder": module("graphiti_core.cross_encoder"),
        "graphiti_core.cross_encoder.openai_reranker_client": module("x", OpenAIRerankerClient=Holder),
        "graphiti_core.driver": module("graphiti_core.driver"),
        "graphiti_core.driver.falkordb_driver": module("x", FalkorDriver=Holder),
        "graphiti_core.embedder": module("graphiti_core.embedder"),
        "graphiti_core.embedder.openai": module("x", OpenAIEmbedder=Holder,
                                                OpenAIEmbedderConfig=lambda **kw: SimpleNamespace(**kw)),
        "graphiti_core.llm_client": module("graphiti_core.llm_client"),
        "graphiti_core.llm_client.config": module("x", LLMConfig=lambda **kw: SimpleNamespace(**kw)),
        "graphiti_core.llm_client.openai_generic_client": module("x", OpenAIGenericClient=Holder),
        "graphiti_core.nodes": module("x", EpisodeType=SimpleNamespace(message="message")),
        "openai": module("openai", AsyncOpenAI=async_openai),
        "redislite": module("redislite"),
        "redislite.async_falkordb_client": module("x", AsyncFalkorDB=Holder),
    }


class GraphitiSidecar(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {})
        env.start()
        self.addCleanup(env.stop)

    def _side(self, *, paid=True, cap=5.0):
        from simorgh.evals.memory.graphiti_side import GraphitiSide

        return GraphitiSide(paid=paid, cap_usd=cap, settings=_SETTINGS)

    def test_absent_package_is_skipped_by_name_not_failed(self):
        with mock.patch.dict(sys.modules, {"graphiti_core": None}):
            result = asyncio.run(run_system(self._side(), episodes()[:3]))
        self.assertIn("graphiti", result.skipped)
        self.assertIn("graphiti-core[falkordblite]", result.skipped)
        self.assertTrue(result.report.outcomes)
        self.assertTrue(all(o.status == SKIPPED for o in result.report.outcomes))
        self.assertEqual(os.environ["GRAPHITI_TELEMETRY_ENABLED"], "false")

    def test_no_embedding_key_is_skipped_saying_which(self):
        from dataclasses import replace

        from simorgh.evals.memory.graphiti_side import GraphitiSide

        side = GraphitiSide(paid=True, cap_usd=5.0, settings=replace(_SETTINGS, embed_api_key=""))
        with mock.patch.dict(sys.modules, _fake_graphiti_modules({})):
            result = asyncio.run(run_system(side, episodes()[:3]))
        self.assertIn("GEMINI_API_KEY", result.skipped)

    def test_it_ingests_searches_by_group_and_counts_the_cost(self):
        store: dict = {}
        with mock.patch.dict(sys.modules, _fake_graphiti_modules(store)):
            result = asyncio.run(run_system(self._side(), episodes()))
        self.assertEqual(os.environ["GRAPHITI_TELEMETRY_ENABLED"], "false")
        self.assertEqual(len(store["episodes"]), 150)
        self.assertEqual({e["group_id"] for e in store["episodes"]},
                         {"household", "person_mara", "person_devin", "person_nell", "person_otto", "person_priya"})
        self.assertIn(("What's the wifi password?", ["household", "person_priya"]), store["searches"])
        outcome = {o.case.name: o for o in result.report.outcomes}
        self.assertEqual(outcome["now.wifi"].status, "passed", "an invalidated edge is a past line")
        self.assertEqual(outcome["before.wifi"].status, "passed")
        self.assertEqual(result.ingestion["episodes"], 150)
        self.assertEqual(result.ingestion["calls_per_episode"], 1.0)
        self.assertAlmostEqual(result.ingestion["total_usd"], 150 * 1_100 / 1_000_000, places=6)
        self.assertIn("group_id", result.notes["privacy"])
        self.assertTrue(store["closed"])

    def test_the_cap_stops_ingestion_and_skips_every_question(self):
        store: dict = {}
        with mock.patch.dict(sys.modules, _fake_graphiti_modules(store)):
            result = asyncio.run(run_system(self._side(cap=0.005), episodes()))
        self.assertLess(len(store["episodes"]), 10)
        self.assertIn("cap reached", result.ingestion["stopped"])
        self.assertTrue(all(o.status == SKIPPED and "cap reached" in o.why for o in result.report.outcomes))

    def test_without_paid_it_calls_nothing(self):
        store: dict = {}
        with mock.patch.dict(sys.modules, _fake_graphiti_modules(store)):
            result = asyncio.run(run_system(self._side(paid=False), episodes()))
        self.assertIn("--paid", result.skipped)
        self.assertNotIn("episodes", store)


def _fake_cognee_modules(store: dict) -> dict[str, types.ModuleType]:
    litellm = types.ModuleType("litellm")

    async def acompletion(**kw):
        store["completions"] = store.get("completions", 0) + 1
        return _usage(1_000, 100)

    litellm.acompletion = acompletion
    litellm.aembedding = acompletion
    litellm.max_budget = None

    cognee = types.ModuleType("cognee")

    async def add(text, dataset_name):
        store.setdefault("added", []).append((dataset_name, text))

    async def cognify(datasets):
        # As Cognee does: through the module attribute, at call time.
        await sys.modules["litellm"].acompletion(model="m")
        store["budget"] = sys.modules["litellm"].max_budget

    async def search(**kw):
        store.setdefault("searches", []).append(kw)
        return [{"context": "Nellie swimming lessons Tuesdays\nwifi password is copper-meadow-17"}]

    config = SimpleNamespace(**{name: (lambda *a, _n=name, **k: store.setdefault("config", []).append(_n))
                                for name in ("data_root_directory", "system_root_directory", "set_llm_config",
                                             "set_embedding_config")})
    cognee.add, cognee.cognify, cognee.search, cognee.config = add, cognify, search, config
    cognee.SearchType = SimpleNamespace(GRAPH_COMPLETION="GRAPH_COMPLETION")
    graph_config = types.ModuleType("cognee.infrastructure.databases.graph.config")
    graph_config.get_graph_config = lambda: SimpleNamespace(graph_database_provider=store.get("graph", "ladybug"))
    return {"litellm": litellm, "cognee": cognee,
            "cognee.infrastructure": types.ModuleType("cognee.infrastructure"),
            "cognee.infrastructure.databases": types.ModuleType("cognee.infrastructure.databases"),
            "cognee.infrastructure.databases.graph": types.ModuleType("cognee.infrastructure.databases.graph"),
            "cognee.infrastructure.databases.graph.config": graph_config}


class CogneeSidecar(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {})
        env.start()
        self.addCleanup(env.stop)

    def _side(self, *, cap=5.0):
        from simorgh.evals.memory.cognee_side import CogneeSide

        return CogneeSide(paid=True, cap_usd=cap, settings=_SETTINGS)

    def test_absent_package_is_skipped_by_name(self):
        with mock.patch.dict(sys.modules, {"cognee": None}):
            result = asyncio.run(run_system(self._side(), episodes()[:3]))
        self.assertIn("cognee", result.skipped)
        self.assertIn("pip install cognee", result.skipped)
        self.assertTrue(all(o.status == SKIPPED for o in result.report.outcomes))
        self.assertEqual(os.environ["TELEMETRY_DISABLED"], "1")

    def test_local_storage_metered_calls_and_the_meter_comes_off_after(self):
        store: dict = {}
        modules = _fake_cognee_modules(store)
        original = modules["litellm"].acompletion
        with mock.patch.dict(sys.modules, modules):
            result = asyncio.run(run_system(self._side(), episodes()))
        self.assertEqual(os.environ["TELEMETRY_DISABLED"], "1")
        self.assertEqual(os.environ["DB_PROVIDER"], "sqlite")
        self.assertEqual(os.environ["VECTOR_DB_PROVIDER"], "lancedb")
        self.assertFalse(os.path.exists(os.environ["DATA_ROOT_DIRECTORY"]), "the temporary directory is gone")
        self.assertEqual(store["budget"], 5.0)
        self.assertEqual(result.ingestion["calls"], 150)
        self.assertIn("ladybug", result.notes["store"])
        self.assertIs(modules["litellm"].acompletion, original)
        self.assertIsNone(modules["litellm"].max_budget)
        self.assertLessEqual({"household", "person_priya"}, {d for d, _ in store["added"]})
        outcome = {o.case.name: o for o in result.report.outcomes}
        self.assertEqual(outcome["now.wifi"].status, "passed")
        self.assertEqual(outcome["never.otto_swim"].status, "passed")
        self.assertTrue(all(kw["only_context"] for kw in store["searches"]))

    def test_a_graph_store_that_needs_a_server_is_refused(self):
        store: dict = {"graph": "neo4j"}
        with mock.patch.dict(sys.modules, _fake_cognee_modules(store)):
            result = asyncio.run(run_system(self._side(), episodes()[:3]))
        self.assertIn("neo4j", result.skipped)
        self.assertNotIn("added", store)


class TheCommandLine(unittest.TestCase):
    def test_dry_run_lists_the_matrix_and_a_cost_with_no_key(self):
        with mock.patch.dict(os.environ, {"TOGETHER_API_KEY": ""}), \
                mock.patch.dict(sys.modules, {"graphiti_core": None, "cognee": None}):
            plan = dry_run(["native", "native_graph", "graphiti", "cognee"], cap_usd=2.0)
        rows = {r["system"]: r for r in plan["systems"]}
        self.assertEqual(rows["native"]["cost"], "free")
        self.assertGreater(rows["graphiti"]["estimate"]["usd"], 0)
        self.assertGreater(rows["cognee"]["estimate"]["usd"], 0)
        self.assertIn("not installed", rows["graphiti"]["runnable"])
        self.assertEqual(sum(plan["categories"].values()), len(QUESTIONS))

    def test_native_runs_from_the_command_line(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["--systems", "native,native_graph", "--json"])
        self.assertEqual(code, 0)
        runs = json.loads(out.getvalue())
        self.assertEqual([r["system"] for r in runs], ["native", "native_graph"])
        self.assertEqual(set(runs[0]["by_category"]), set(CATEGORIES))

    def test_paid_without_a_cap_is_refused(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--systems", "graphiti", "--paid"]), 2)

    def test_the_free_suite_is_registered_and_free(self):
        self.assertIn("memory", SUITES)
        self.assertNotIn("memory", PAID)

    def test_memory_and_the_kernel_never_import_a_sidecar(self):
        from pathlib import Path

        import re

        root = Path(corpus.__file__).resolve().parents[2]
        sidecar = re.compile(r"^\s*(import|from)\s+(graphiti_core|cognee|litellm|simorgh\.evals)", re.M)
        for package in ("memory", "kernel"):
            for path in (root / package).rglob("*.py"):
                self.assertIsNone(sidecar.search(path.read_text(encoding="utf-8")), str(path))


if __name__ == "__main__":
    unittest.main()


class ALibraryFailure(unittest.TestCase):
    def test_an_ingestion_error_skips_the_rest_saying_why_and_does_not_raise(self):
        class Broken:
            name = "broken"
            meter = None

            def skip_reason(self):
                return ""

            async def open(self):
                pass

            async def ingest(self, episode):
                raise ModuleNotFoundError("No module named 's3fs'")

            async def context(self, question):
                raise AssertionError("never asked after a failed ingestion")

            async def close(self):
                pass

        result = asyncio.run(run_system(Broken(), episodes()[:3]))
        self.assertTrue(result.report.outcomes)
        self.assertTrue(all(o.status == SKIPPED for o in result.report.outcomes))
        self.assertIn("s3fs", result.report.outcomes[0].why)


class AnEmbeddingWithoutUsage(unittest.TestCase):
    def test_is_charged_its_input_not_a_chat_call(self):
        from simorgh.evals.memory.meter import Meter, metered

        meter = Meter(cap_usd=1.0, price_in=1.0, price_out=1.0, reserve_in=2_500, reserve_out=400)

        async def embed(**kwargs):
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.0])])

        asyncio.run(metered(embed, meter)(model="e", input=["Mara: the bins go out on Tuesday"]))
        self.assertEqual((meter.tokens_in, meter.tokens_out, meter.unmetered), (8, 0, 1))

        async def chat(**kwargs):
            return SimpleNamespace(choices=[])

        asyncio.run(metered(chat, meter)(model="m", messages=[{"role": "user", "content": "x"}]))
        self.assertEqual((meter.tokens_in, meter.tokens_out), (8 + 2_500, 400))


def _fake_mem0_modules(store: dict, *, seams: bool = True, filler: int = 0) -> dict[str, types.ModuleType]:
    """Just enough of mem0 to drive the sidecar: a Memory that, like the
    real one, owns a sync OpenAI client in its LLM and in its embedder."""

    def chat_create(**kw):
        store["chats"] = store.get("chats", 0) + 1
        return _usage(1_000, 100)

    def embed_create(**kw):
        # Gemini's endpoint sends no usage: charged its input's length.
        store["embeds"] = store.get("embeds", 0) + 1
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.0])])

    def openai_client():
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=chat_create)),
                               embeddings=SimpleNamespace(create=embed_create))

    class Memory:
        def __init__(self, config):
            self.config = config
            self.llm = SimpleNamespace(client=openai_client() if seams else None)
            self.embedding_model = SimpleNamespace(client=openai_client())
            self.vector_store = SimpleNamespace(client=SimpleNamespace(close=lambda: store.update(closed=True)))
            self.graph = None

        @classmethod
        def from_config(cls, config):
            store["config"] = config
            store["telemetry_at_open"] = os.environ.get("MEM0_TELEMETRY")
            store["openrouter_at_open"] = os.environ.get("OPENROUTER_API_KEY")
            return cls(config)

        def add(self, messages, *, user_id):
            # As Mem0 does: through the clients it built, looked up at call time.
            self.llm.client.chat.completions.create(model="m", messages=messages)
            self.embedding_model.client.embeddings.create(model="e", input=[messages[0]["content"]])
            store.setdefault("added", []).append((user_id, messages[0]["content"]))

        def search(self, query, *, user_id, limit=100):
            self.embedding_model.client.embeddings.create(model="e", input=[query])
            store.setdefault("searches", []).append((query, user_id))
            if filler:
                # A full page from each user_id, as a real store gives once it is fed.
                return {"results": [{"memory": f"{user_id} note {i}", "score": 0.5 - i / 100}
                                    for i in range(min(filler, limit))]}
            if user_id == "household":
                return {"results": [{"memory": "Nellie swimming lessons are on Tuesdays", "score": 0.4},
                                    {"memory": "wifi password is copper-meadow-17", "score": 0.9}]}
            return {"results": []}

    mem0 = types.ModuleType("mem0")
    mem0.Memory = Memory
    return {"mem0": mem0}


class Mem0Sidecar(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("MEM0_DIR", None)
        os.environ.pop("OPENROUTER_API_KEY", None)

    def _side(self, *, cap=5.0):
        from simorgh.evals.memory.mem0_side import Mem0Side

        return Mem0Side(paid=True, cap_usd=cap, settings=_SETTINGS)

    def test_absent_package_is_skipped_by_name_and_never_touches_home(self):
        with mock.patch.dict(sys.modules, {"mem0": None}):
            result = asyncio.run(run_system(self._side(), episodes()[:3]))
        self.assertIn("mem0", result.skipped)
        self.assertIn("pip install mem0ai", result.skipped)
        self.assertTrue(result.report.outcomes)
        self.assertTrue(all(o.status == SKIPPED for o in result.report.outcomes))
        self.assertEqual(os.environ["MEM0_TELEMETRY"], "False")
        self.assertNotEqual(os.environ["MEM0_DIR"], os.path.expanduser("~/.mem0"))

    def test_it_ingests_and_searches_by_user_and_counts_chat_and_embeddings(self):
        store: dict = {}
        with mock.patch.dict(sys.modules, _fake_mem0_modules(store)):
            result = asyncio.run(run_system(self._side(), episodes()))
        self.assertEqual(store["telemetry_at_open"], "False")
        config = store["config"]
        self.assertEqual(config["vector_store"]["provider"], "qdrant")
        self.assertFalse(os.path.exists(config["vector_store"]["config"]["path"]), "the temporary directory is gone")
        self.assertEqual(config["llm"]["config"]["openai_base_url"], _SETTINGS.base_url)
        self.assertEqual(config["embedder"]["config"]["api_key"], "embed-key")
        self.assertEqual(config["embedder"]["config"]["embedding_dims"], 768)
        self.assertNotIn("graph_store", config)
        self.assertEqual(len(store["added"]), 150)
        self.assertEqual({u for u, _ in store["added"]},
                         {"household", "person_mara", "person_devin", "person_nell", "person_otto", "person_priya"})
        self.assertIn(("What's the wifi password?", "household"), store["searches"])
        self.assertIn(("What's the wifi password?", "person_priya"), store["searches"])
        outcome = {o.case.name: o for o in result.report.outcomes}
        self.assertEqual(outcome["now.wifi"].status, "passed")
        self.assertEqual(outcome["never.otto_swim"].status, "passed")
        # Both clients metered: a chat and an embedding per episode, and an
        # embedding (without usage, charged its input) per search.
        self.assertEqual(result.ingestion["calls"], 300)
        self.assertEqual(store["embeds"], 150 + 2 * len(QUESTIONS))
        self.assertEqual(result.ingestion["unmetered_calls"], store["embeds"])
        self.assertGreater(result.ingestion["usd"], 150 * 1_100 / 1_000_000)
        self.assertIn("user_id", result.notes["privacy"])
        self.assertGreater(result.injected["p50"], 0)
        self.assertTrue(store["closed"])

    def test_the_cap_stops_ingestion_and_skips_every_question(self):
        store: dict = {}
        with mock.patch.dict(sys.modules, _fake_mem0_modules(store)):
            result = asyncio.run(run_system(self._side(cap=0.005), episodes()))
        self.assertLess(len(store["added"]), 10)
        self.assertIn("cap reached", result.ingestion["stopped"])
        self.assertTrue(all(o.status == SKIPPED and "cap reached" in o.why for o in result.report.outcomes))
        self.assertNotIn("searches", store)

    def test_a_memory_without_a_client_to_meter_is_refused(self):
        store: dict = {}
        with mock.patch.dict(sys.modules, _fake_mem0_modules(store, seams=False)):
            result = asyncio.run(run_system(self._side(), episodes()[:3]))
        self.assertIn("unmetered", result.skipped)
        self.assertNotIn("added", store)

    def test_a_question_gets_no_more_memories_than_graphiti_or_cognee(self):
        from simorgh.evals.memory.mem0_side import LIMIT

        side = self._side()

        async def ask():
            await side.open()
            try:
                return await side.context(QUESTIONS[0])
            finally:
                await side.close()

        with mock.patch.dict(sys.modules, _fake_mem0_modules({}, filler=50)):
            self.assertEqual(side.skip_reason(), "")
            lines = asyncio.run(ask())
        # Two user_ids, ten each, cut to Graphiti's num_results / Cognee's top_k.
        self.assertEqual(LIMIT, 10)
        self.assertEqual(len(lines), LIMIT)
        self.assertEqual(lines[0], "household note 0")

    def test_a_refused_memory_leaves_no_directory_and_the_openrouter_key_back(self):
        store: dict = {}
        os.environ["OPENROUTER_API_KEY"] = "or-key"
        with mock.patch.dict(sys.modules, _fake_mem0_modules(store, seams=False)):
            result = asyncio.run(run_system(self._side(), episodes()[:3]))
        self.assertIn("unmetered", result.skipped)
        self.assertEqual(os.environ["OPENROUTER_API_KEY"], "or-key")
        self.assertFalse(os.path.exists(os.path.dirname(store["config"]["history_db_path"])))
        self.assertTrue(store.get("closed"))

    def test_an_openrouter_key_is_set_aside_for_the_run(self):
        store: dict = {}
        os.environ["OPENROUTER_API_KEY"] = "or-key"
        with mock.patch.dict(sys.modules, _fake_mem0_modules(store)):
            asyncio.run(run_system(self._side(), episodes()[:3]))
        self.assertIsNone(store["openrouter_at_open"])
        self.assertEqual(os.environ["OPENROUTER_API_KEY"], "or-key")

    def test_the_dry_run_estimates_it(self):
        with mock.patch.dict(sys.modules, {"mem0": None}):
            plan = dry_run(["native", "mem0"], cap_usd=2.0)
        row = {r["system"]: r for r in plan["systems"]}["mem0"]
        self.assertGreater(row["estimate"]["usd"], 0)
        self.assertIn("pip install mem0ai", row["runnable"])


class InjectedTokens(unittest.TestCase):
    def test_every_system_reports_the_tokens_its_block_would_inject(self):
        from simorgh.evals.memory.suite import block_tokens

        self.assertEqual(block_tokens([]), 0)
        self.assertEqual(block_tokens(["abcd", "efg"]), 2)
        result = asyncio.run(run_system(Native(), episodes()))
        self.assertGreater(result.injected["mean"], 0)
        self.assertLessEqual(result.injected["p50"], result.injected["p95"])
        self.assertIn("injected", result.as_dict())


class Mem0SearchShapes(unittest.TestCase):
    def test_2x_gets_filters_and_1x_gets_user_id(self):
        from simorgh.evals.memory.mem0_side import LIMIT, search

        class Two:
            def search(self, query, *, top_k=20, filters=None, **kw):
                if kw:
                    raise ValueError(f"Top-level entity parameters {frozenset(kw)} are not supported")
                return {"results": [{"memory": query, "who": filters["user_id"], "k": top_k}]}

        class One:
            def search(self, query, *, user_id, limit=100):
                return [{"memory": query, "who": user_id, "k": limit}]

        self.assertEqual(search(Two(), "q", "household")["results"][0], {"memory": "q", "who": "household", "k": LIMIT})
        self.assertEqual(search(One(), "q", "person_mara")[0], {"memory": "q", "who": "person_mara", "k": LIMIT})
