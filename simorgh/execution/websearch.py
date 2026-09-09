"""`web_search`: the tool that finds a page worth fetching.

The creator, 2026-09-08: *"add web search engine tool ability to sim"*.
It was the missing half of `web_fetch`. Sim could read any URL and had
no way to discover one, so every question whose answer lives on the open
web was unanswerable unless the URL was already in the prompt -- which
is exactly why GAIA, a benchmark built on tool-using web questions, was
expected to score badly.

**Backends.** One tool, several providers, chosen by whichever key is
present:

| provider | key | notes |
|---|---|---|
| `duckduckgo` | none | the default: no key, no account, no quota to run out mid-run |
| `brave` | `BRAVE_API_KEY` | a real search API with a free tier |
| `tavily` | `TAVILY_API_KEY` | built for agents; returns snippets already summarised |
| `serper` | `SERPER_API_KEY` | Google results |

`[execution] web_search_provider = "auto"` picks the best key that is
actually set, falling back to DuckDuckGo. Naming a provider explicitly
means "this one or fail", because silently degrading to a weaker engine
would show up as a mysterious drop in benchmark scores rather than as an
error.

**What it returns** is a short ranked list of `title / url / snippet` --
never page bodies. Fetching a result is `web_fetch`'s job, and keeping
the two separate is what lets Guardian see "it searched" and "it read
that page" as different decisions.

The tool is read-only and network-using. It cannot reach a private
address: results are URLs the model may then ask `web_fetch` for, and
`web_fetch` does its own SSRF check on each one.
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover -- import cycle: config imports this module
    from .config import Config

from simorgh.contracts.protocols import ToolContext, ToolResult

DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
TAVILY_URL = "https://api.tavily.com/search"
SERPER_URL = "https://google.serper.dev/search"

# Provider -> the environment variable that switches it on, best first.
PROVIDER_KEYS: tuple[tuple[str, str], ...] = (
    ("tavily", "TAVILY_API_KEY"),
    ("brave", "BRAVE_API_KEY"),
    ("serper", "SERPER_API_KEY"),
)
DEFAULT_PROVIDER = "duckduckgo"
_SNIPPET_CHARS = 300
_TITLE_CHARS = 120


class SearchUnavailable(RuntimeError):
    """The search could not run, with the reason a human can act on."""


@dataclass(frozen=True)
class Result:
    title: str
    url: str
    snippet: str

    def render(self, index: int) -> str:
        return f"{index}. {self.title}\n   {self.url}\n   {self.snippet}" if self.snippet else \
               f"{index}. {self.title}\n   {self.url}"


def choose_provider(configured: str, env) -> str:
    """Which backend to use. `auto` takes the best key actually set."""
    configured = (configured or "auto").strip().lower()
    if configured != "auto":
        return configured
    for provider, key in PROVIDER_KEYS:
        if (env.get(key) or "").strip():
            return provider
    return DEFAULT_PROVIDER


# ------------------------------------------------------------- parsing
_RESULT_BLOCK = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'(?P<rest>.*?)(?=<a[^>]+class="[^"]*result__a|\Z)',
    re.S | re.I,
)
_SNIPPET = re.compile(r'class="[^"]*result__snippet[^"]*"[^>]*>(?P<snippet>.*?)</a>', re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", fragment or "")).split())


def _real_url(href: str) -> str:
    """DuckDuckGo's HTML endpoint wraps every result in a redirect."""
    href = html.unescape(href or "")
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if "duckduckgo.com" in (parsed.netloc or "") and parsed.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


# The keyless endpoint answers a throttled request with HTTP 200 and a
# page that simply has no results on it -- indistinguishable from a
# genuine "nothing found" unless you look for the difference. Live,
# 2026-09-08: two searches back to back, the first fine, the second
# silently empty; the same query alone returned eight. A search that
# reports "no results" when it was really refused is the kind of quiet
# lie that makes a benchmark number meaningless.
_NO_RESULTS_MARKERS = ("no results", "not many great matches", "no-results")
_BLOCKED_MARKERS = ("anomaly", "unusual traffic", "captcha", "are you a robot")


def duckduckgo_problem(body: str) -> str:
    """`""` when the page is a real answer; otherwise why it is not."""
    lowered = (body or "").lower()
    if "result__a" in lowered:
        return ""
    for marker in _BLOCKED_MARKERS:
        if marker in lowered:
            return "the search engine refused the request (rate limited or challenged)"
    if any(marker in lowered for marker in _NO_RESULTS_MARKERS):
        return ""  # a genuine empty result
    return "the search engine returned a page with no results and no explanation, which usually means throttling"


def parse_duckduckgo(body: str, limit: int) -> list[Result]:
    results: list[Result] = []
    for match in _RESULT_BLOCK.finditer(body or ""):
        url = _real_url(match.group("href"))
        if not url.startswith(("http://", "https://")):
            continue
        snippet = _SNIPPET.search(match.group("rest") or "")
        results.append(Result(
            title=_text(match.group("title"))[:_TITLE_CHARS],
            url=url,
            snippet=_text(snippet.group("snippet") if snippet else "")[:_SNIPPET_CHARS],
        ))
        if len(results) >= limit:
            break
    return results


def parse_brave(payload: dict, limit: int) -> list[Result]:
    items = ((payload.get("web") or {}).get("results") or [])[:limit]
    return [Result(title=_text(i.get("title"))[:_TITLE_CHARS], url=i.get("url", ""),
                   snippet=_text(i.get("description"))[:_SNIPPET_CHARS]) for i in items if i.get("url")]


def parse_tavily(payload: dict, limit: int) -> list[Result]:
    items = (payload.get("results") or [])[:limit]
    return [Result(title=_text(i.get("title"))[:_TITLE_CHARS], url=i.get("url", ""),
                   snippet=_text(i.get("content"))[:_SNIPPET_CHARS]) for i in items if i.get("url")]


def parse_serper(payload: dict, limit: int) -> list[Result]:
    items = (payload.get("organic") or [])[:limit]
    return [Result(title=_text(i.get("title"))[:_TITLE_CHARS], url=i.get("link", ""),
                   snippet=_text(i.get("snippet"))[:_SNIPPET_CHARS]) for i in items if i.get("link")]


_STOPWORDS = {
    "what", "when", "where", "which", "while", "about", "with", "from", "this",
    "that", "there", "their", "would", "could", "should", "does", "did",
}


def _significant_tokens(query: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) >= 4 and t not in _STOPWORDS}


def results_look_unrelated(query: str, results: list[Result]) -> bool:
    """True when none of the query's significant words appear anywhere in the
    results -- DuckDuckGo's keyless endpoint answers gibberish/unmatched
    queries with generic filler (YouTube, Wikipedia, google.com) on a real
    HTTP 200 page instead of a genuine empty-result page, so `duckduckgo_
    problem` sees real `result__a` blocks and reports a confident match.
    Live-caught 2026-09-09 (wave-18 observer W18-02): a nonsense query got
    "8 results" back, none topically related.
    """
    tokens = _significant_tokens(query)
    if not tokens or not results:
        return False
    haystack = " ".join(f"{r.title} {r.snippet}" for r in results).lower()
    return not any(token in haystack for token in tokens)


def render(results: list[Result], query: str, provider: str, *, low_confidence: bool = False) -> str:
    if not results:
        return f"no results for {query!r} (via {provider})"
    body = "\n".join(result.render(index) for index, result in enumerate(results, start=1))
    header = f"{len(results)} results for {query!r} (via {provider})"
    if low_confidence:
        header += (
            " -- results may be unrelated to the query "
            "(no significant search term appears in any title or snippet)"
        )
    return f"{header}:\n{body}"


# ------------------------------------------------------------ the tool
class WebSearchTool:
    name = "web_search"
    description = "Search the web and get back a ranked list of title/url/snippet."
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}}

    def __init__(self, config: "Config", *, opener=None, env=None) -> None:
        self._config = config
        self._opener = opener or urllib.request.urlopen
        self._env = env if env is not None else os.environ
        self._recent_calls: list[float] = []
        self._last_call = 0.0

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        query = str(args.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="refused: an empty search query")
        try:
            self._enforce_rate_limit(ctx)
        except SearchUnavailable as exc:
            return ToolResult(ok=False, error=str(exc))
        provider = choose_provider(self._config.web_search_provider, self._env)
        limit = max(1, int(self._config.web_search_max_results))
        try:
            results = await self._search(provider, query, limit)
        except SearchUnavailable as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")
        except Exception as exc:  # noqa: BLE001 -- a network failure is a result, never a crash
            return ToolResult(ok=False, error=f"search failed via {provider}: {exc!r}")
        low_confidence = provider == "duckduckgo" and results_look_unrelated(query, results)
        return ToolResult(
            ok=True, output=render(results, query, provider, low_confidence=low_confidence),
            metadata={"provider": provider, "query": query, "count": len(results),
                      "urls": [r.url for r in results], "low_confidence": low_confidence},
        )

    async def _search(self, provider: str, query: str, limit: int) -> list[Result]:
        import asyncio

        return await asyncio.to_thread(self._search_sync, provider, query, limit)

    def _search_sync(self, provider: str, query: str, limit: int) -> list[Result]:
        timeout = self._config.web_search_timeout_s
        if provider == "duckduckgo":
            problem = ""
            for attempt in range(self._config.web_search_attempts):
                self._space_out()
                body = self._post(DUCKDUCKGO_URL, urllib.parse.urlencode({"q": query}).encode(),
                                  {"Content-Type": "application/x-www-form-urlencoded"}, timeout)
                problem = duckduckgo_problem(body)
                if not problem:
                    return parse_duckduckgo(body, limit)
                self._last_call = 0.0  # force the next attempt to wait out the throttle
            raise SearchUnavailable(
                f"{problem}. Set BRAVE_API_KEY, TAVILY_API_KEY or SERPER_API_KEY for a search API "
                "with a real quota, or try again in a moment"
            )
        if provider == "brave":
            key = self._require("BRAVE_API_KEY", provider)
            url = f"{BRAVE_URL}?{urllib.parse.urlencode({'q': query, 'count': limit})}"
            return parse_brave(json.loads(self._get(url, {"X-Subscription-Token": key,
                                                          "Accept": "application/json"}, timeout)), limit)
        if provider == "tavily":
            key = self._require("TAVILY_API_KEY", provider)
            body = json.dumps({"api_key": key, "query": query, "max_results": limit}).encode()
            return parse_tavily(json.loads(self._post(TAVILY_URL, body,
                                                      {"Content-Type": "application/json"}, timeout)), limit)
        if provider == "serper":
            key = self._require("SERPER_API_KEY", provider)
            body = json.dumps({"q": query, "num": limit}).encode()
            return parse_serper(json.loads(self._post(SERPER_URL, body, {
                "X-API-KEY": key, "Content-Type": "application/json"}, timeout)), limit)
        raise SearchUnavailable(
            f"unknown search provider {provider!r}; known: duckduckgo, brave, tavily, serper"
        )

    def _space_out(self) -> None:
        """Leave a gap between keyless searches. Wall-clock, not the
        injected clock: this is about the remote service's patience, not
        about anything this system measures."""
        import time

        gap = self._config.web_search_min_interval_s
        if gap <= 0:
            return
        waited = time.monotonic() - self._last_call
        if self._last_call and waited < gap:
            time.sleep(gap - waited)
        self._last_call = time.monotonic()

    def _require(self, key: str, provider: str) -> str:
        value = (self._env.get(key) or "").strip()
        if not value:
            raise SearchUnavailable(f"{provider} needs {key} in the environment")
        return value

    def _headers(self, extra: dict) -> dict:
        return {"User-Agent": self._config.web_fetch_user_agent, "Accept-Encoding": "identity", **extra}

    def _get(self, url: str, headers: dict, timeout: float) -> str:
        request = urllib.request.Request(url, headers=self._headers(headers))
        return self._read(request, timeout)

    def _post(self, url: str, data: bytes, headers: dict, timeout: float) -> str:
        request = urllib.request.Request(url, data=data, headers=self._headers(headers))
        return self._read(request, timeout)

    def _read(self, request, timeout: float) -> str:
        with self._opener(request, timeout=timeout) as response:  # noqa: S310 -- fixed https endpoints
            raw = response.read(self._config.web_search_max_bytes + 1)
        return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)

    def _enforce_rate_limit(self, ctx: ToolContext) -> None:
        """Its own budget, separate from `web_fetch`'s.

        A search is one call where a fetch is many, and sharing a window
        would let a burst of reading starve the searching that found
        those pages."""
        now = ctx.clock.now()
        cutoff = now - self._config.web_search_window_s
        while self._recent_calls and self._recent_calls[0] < cutoff:
            self._recent_calls.pop(0)
        if len(self._recent_calls) >= self._config.web_search_max_calls:
            raise SearchUnavailable(
                f"refused: {self._config.web_search_max_calls} searches already in the last "
                f"{self._config.web_search_window_s / 60:.0f} minutes"
            )
        self._recent_calls.append(now)


__all__ = [
    "DEFAULT_PROVIDER", "PROVIDER_KEYS", "Result", "SearchUnavailable", "WebSearchTool",
    "choose_provider", "duckduckgo_problem", "parse_brave", "parse_duckduckgo", "parse_serper",
    "parse_tavily", "render",
]
