"""`web_search` (execution/websearch.py).

Every test here is offline: the HTTP opener is injected. The one thing
that must not be faked is the parsing, so the DuckDuckGo fixture is a
real fragment of the endpoint's own markup.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.websearch import (
    DEFAULT_PROVIDER, Result, SearchUnavailable, WebSearchTool, choose_provider,
    duckduckgo_problem, parse_brave, parse_duckduckgo, parse_serper, parse_tavily, render,
    results_look_unrelated,
)

DDG_PAGE = """
<div class="links_main links_deep result__body">
  <h2 class="result__title">
    <a rel="nofollow" class="result__a" href="https://arxiv.org/abs/2311.12983">GAIA: a benchmark for &amp; General AI Assistants</a>
  </h2>
  <a class="result__snippet" href="x">We introduce <b>GAIA</b>, a benchmark for General AI Assistants.</a>
</div>
<div class="links_main links_deep result__body">
  <h2 class="result__title">
    <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fpage&amp;rut=x">Example</a>
  </h2>
  <a class="result__snippet" href="x">A second result.</a>
</div>
"""


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t


def _ctx(clock=None) -> ToolContext:
    return ToolContext(action_id="a", task_id=None, scope={}, constraints={},
                       data_dir=Path.cwd(), clock=clock or _Clock(), logger=None, ledger=None)


class _Response:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=None):
        return self._body[:n] if n else self._body


def _opener(body: str, seen: list | None = None):
    def open_it(request, timeout=None):
        if seen is not None:
            seen.append(request)
        return _Response(body)
    return open_it


class ProviderChoiceTestCase(unittest.TestCase):
    def test_no_key_means_the_keyless_engine(self):
        self.assertEqual(choose_provider("auto", {}), DEFAULT_PROVIDER)

    def test_a_key_upgrades_it_without_configuration(self):
        self.assertEqual(choose_provider("auto", {"BRAVE_API_KEY": "k"}), "brave")
        self.assertEqual(choose_provider("auto", {"SERPER_API_KEY": "k"}), "serper")

    def test_the_best_key_wins_when_several_are_set(self):
        self.assertEqual(choose_provider("auto", {"BRAVE_API_KEY": "k", "TAVILY_API_KEY": "k"}), "tavily")

    def test_an_explicit_provider_is_obeyed_even_with_other_keys(self):
        """Naming one means that one or an error: silently falling back
        would look like a mysterious score drop, not a misconfiguration."""
        self.assertEqual(choose_provider("brave", {"TAVILY_API_KEY": "k"}), "brave")

    def test_an_empty_key_does_not_count(self):
        self.assertEqual(choose_provider("auto", {"BRAVE_API_KEY": "   "}), DEFAULT_PROVIDER)


class ParsingTestCase(unittest.TestCase):
    def test_duckduckgo_results_carry_title_url_and_snippet(self):
        results = parse_duckduckgo(DDG_PAGE, 8)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].url, "https://arxiv.org/abs/2311.12983")
        self.assertEqual(results[0].title, "GAIA: a benchmark for & General AI Assistants")
        self.assertIn("We introduce GAIA", results[0].snippet)

    def test_the_redirect_wrapper_is_unwrapped(self):
        self.assertEqual(parse_duckduckgo(DDG_PAGE, 8)[1].url, "https://example.org/page")

    def test_the_limit_is_honoured(self):
        self.assertEqual(len(parse_duckduckgo(DDG_PAGE, 1)), 1)

    def test_an_empty_page_yields_nothing_rather_than_raising(self):
        self.assertEqual(parse_duckduckgo("", 8), [])

    def test_brave_tavily_and_serper_shapes(self):
        self.assertEqual(parse_brave({"web": {"results": [{"title": "T", "url": "u", "description": "d"}]}}, 8),
                         [Result("T", "u", "d")])
        self.assertEqual(parse_tavily({"results": [{"title": "T", "url": "u", "content": "c"}]}, 8),
                         [Result("T", "u", "c")])
        self.assertEqual(parse_serper({"organic": [{"title": "T", "link": "u", "snippet": "s"}]}, 8),
                         [Result("T", "u", "s")])

    def test_a_result_without_a_url_is_dropped(self):
        self.assertEqual(parse_brave({"web": {"results": [{"title": "T", "description": "d"}]}}, 8), [])


class ThrottleDetectionTestCase(unittest.TestCase):
    """A throttled request comes back HTTP 200 with an empty page. Read
    as "no results" it is a quiet lie -- live, 2026-09-08."""

    def test_a_page_with_results_has_no_problem(self):
        self.assertEqual(duckduckgo_problem(DDG_PAGE), "")

    def test_a_genuine_empty_result_is_not_a_problem(self):
        self.assertEqual(duckduckgo_problem("<div>No results found for that query.</div>"), "")

    def test_a_challenge_page_is_named_as_a_refusal(self):
        self.assertIn("refused", duckduckgo_problem("<div>please solve this CAPTCHA</div>"))

    def test_a_silently_empty_page_is_called_throttling(self):
        self.assertIn("throttling", duckduckgo_problem("<html><body></body></html>"))


class ToolTestCase(unittest.IsolatedAsyncioTestCase):
    def _tool(self, body=DDG_PAGE, env=None, seen=None, **config):
        settings = {"repo_root": Path.cwd(), "web_search_min_interval_s": 0.0}
        settings.update(config)
        return WebSearchTool(Config(**settings), opener=_opener(body, seen), env=env or {})

    async def test_it_returns_a_ranked_list_and_the_urls_in_metadata(self):
        result = await self._tool().run({"query": "gaia benchmark"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("1. GAIA", result.output)
        self.assertEqual(result.metadata["provider"], "duckduckgo")
        self.assertEqual(result.metadata["count"], 2)
        self.assertEqual(result.metadata["urls"][1], "https://example.org/page")

    async def test_a_query_unrelated_to_the_results_is_flagged_low_confidence(self):
        result = await self._tool().run(
            {"query": "asdkjqhwoieuqhwoiuehqoiwuehwqoiuehasdkjfhalksjdfh zzqqxxvv123456"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertTrue(result.metadata["low_confidence"])
        self.assertIn("may be unrelated to the query", result.output)

    async def test_a_matching_query_is_not_flagged_low_confidence(self):
        result = await self._tool().run({"query": "gaia benchmark"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertFalse(result.metadata["low_confidence"])
        self.assertNotIn("may be unrelated", result.output)

    async def test_an_empty_query_is_refused(self):
        result = await self._tool().run({"query": "   "}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("empty search query", result.error)

    async def test_a_throttled_page_is_an_error_not_an_empty_result(self):
        result = await self._tool(body="<html></html>", web_search_attempts=2).run(
            {"query": "x"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("throttling", result.error)
        self.assertIn("BRAVE_API_KEY", result.error)

    async def test_a_provider_without_its_key_says_which_key(self):
        result = await self._tool(web_search_provider="brave").run({"query": "x"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("BRAVE_API_KEY", result.error)

    async def test_an_unknown_provider_names_the_real_ones(self):
        result = await self._tool(web_search_provider="bing").run({"query": "x"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("duckduckgo", result.error)

    async def test_a_key_provider_sends_its_credential_and_nothing_else_does(self):
        seen: list = []
        payload = json.dumps({"web": {"results": [{"title": "T", "url": "https://x", "description": "d"}]}})
        tool = self._tool(body=payload, env={"BRAVE_API_KEY": "secret"}, seen=seen)
        result = await tool.run({"query": "x"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.metadata["provider"], "brave")
        self.assertEqual(seen[0].headers.get("X-subscription-token"), "secret")

    async def test_a_network_failure_is_a_result_not_a_crash(self):
        def boom(request, timeout=None):
            raise OSError("no route to host")

        tool = WebSearchTool(Config(repo_root=Path.cwd()), opener=boom, env={})
        result = await tool.run({"query": "x"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("no route to host", result.error)

    async def test_its_rate_limit_is_its_own_and_refuses_past_the_cap(self):
        clock = _Clock()
        tool = self._tool(web_search_max_calls=2, web_search_window_s=3600.0)
        for _ in range(2):
            self.assertTrue((await tool.run({"query": "x"}, ctx=_ctx(clock))).ok)
        blocked = await tool.run({"query": "x"}, ctx=_ctx(clock))
        self.assertFalse(blocked.ok)
        self.assertIn("2 searches already", blocked.error)

    async def test_the_window_lets_it_search_again_later(self):
        clock = _Clock()
        tool = self._tool(web_search_max_calls=1, web_search_window_s=60.0)
        self.assertTrue((await tool.run({"query": "x"}, ctx=_ctx(clock))).ok)
        self.assertFalse((await tool.run({"query": "x"}, ctx=_ctx(clock))).ok)
        clock.t = 61.0
        self.assertTrue((await tool.run({"query": "x"}, ctx=_ctx(clock))).ok)


class RenderTestCase(unittest.TestCase):
    def test_results_are_numbered_with_their_urls(self):
        text = render([Result("T", "https://x", "s")], "q", "duckduckgo")
        self.assertIn("1. T", text)
        self.assertIn("https://x", text)
        self.assertIn("via duckduckgo", text)

    def test_nothing_found_says_so_with_the_provider(self):
        self.assertIn("no results for 'q' (via brave)", render([], "q", "brave"))

    def test_low_confidence_flag_adds_a_caveat_to_the_header(self):
        text = render([Result("T", "https://x", "s")], "q", "duckduckgo", low_confidence=True)
        self.assertIn("may be unrelated to the query", text)

    def test_no_caveat_by_default(self):
        text = render([Result("T", "https://x", "s")], "q", "duckduckgo")
        self.assertNotIn("may be unrelated", text)


class ResultsLookUnrelatedTestCase(unittest.TestCase):
    def test_gibberish_query_with_off_topic_filler_is_flagged(self):
        # Live-caught, wave-18 observer W18-02: DuckDuckGo's keyless endpoint
        # answered a nonsense query with real result__a blocks pointing at
        # YouTube/Wikipedia/Google -- a genuine HTTP 200 "match" that has
        # nothing to do with the query.
        results = [
            Result("YouTube", "https://youtube.com", "Enjoy the videos"),
            Result("Phonics Song | ABC", "https://youtube.com/x", "Official Video"),
            Result("Wordle", "https://nytimes.com/wordle", "Play today's Wordle"),
        ]
        self.assertTrue(results_look_unrelated(
            "asdkjqhwoieuqhwoiuehqoiwuehwqoiuehasdkjfhalksjdfhqwoiuehqasdkjfh zzqqxxvv123456",
            results,
        ))

    def test_a_real_match_is_not_flagged(self):
        results = [Result("GAIA benchmark", "https://arxiv.org/x", "a benchmark for general AI assistants")]
        self.assertFalse(results_look_unrelated("GAIA benchmark", results))

    def test_no_results_is_not_flagged_here_render_handles_that_case(self):
        self.assertFalse(results_look_unrelated("anything", []))

    def test_a_query_with_only_short_or_stopword_tokens_is_never_flagged(self):
        self.assertFalse(results_look_unrelated("what is it", [Result("T", "u", "s")]))


class WiringTestCase(unittest.TestCase):
    def test_it_is_a_builtin_tool_and_read_only(self):
        from simorgh.execution.tools import builtin_tools

        tool = next(t for t in builtin_tools(Config(repo_root=Path.cwd())) if t.name == "web_search")
        self.assertTrue(tool.read_only)
        self.assertEqual(tool.reversibility, "read_only")

    def test_the_profiles_that_may_reach_the_network_offer_it(self):
        from simorgh.orchestration import profiles

        for profile in (profiles.RESEARCH, profiles.CHAT, profiles.PLAN):
            self.assertIn("web_search", profile.tools, profile.name)

    def test_the_router_knows_its_policy_and_its_argument(self):
        from simorgh.orchestration.tools import _MARKER_ARG_KEY, _TOOL_POLICY, marker_hint

        self.assertEqual(_TOOL_POLICY["web_search"], ("read_only", True))
        self.assertEqual(_MARKER_ARG_KEY["web_search"], "query")
        self.assertIn("WEB_FETCH", marker_hint("web_search"))


if __name__ == "__main__":
    unittest.main()


class RepoRootTestCase(unittest.TestCase):
    """Self-knowledge must not depend silently on the launch directory.

    `repo_root` was `Path.cwd()` alone. Started from anywhere else, every
    readable root pointed at nothing and Sim answered questions about
    itself from imagination -- it invented five subsystems and denied
    having a Guardian while `status` printed `guardian ok`, with no error
    ever (observer, 2026-09-08).
    """

    def test_it_finds_the_repo_from_a_subdirectory(self):
        from simorgh.execution.config import find_repo_root

        here = Path(__file__).resolve()
        root = find_repo_root(here.parent)
        self.assertTrue((root / "simorgh" / "kernel" / "service.py").is_file())

    def test_it_finds_the_repo_from_outside_it(self):
        from simorgh.execution.config import find_repo_root

        root = find_repo_root(Path("/tmp"))
        self.assertTrue((root / "simorgh" / "kernel" / "service.py").is_file(),
                        "must fall back to the package's own location")

    def test_the_default_config_points_at_a_real_repo(self):
        config = Config()
        self.assertTrue((config.repo_root / "simorgh" / "kernel" / "service.py").is_file())
