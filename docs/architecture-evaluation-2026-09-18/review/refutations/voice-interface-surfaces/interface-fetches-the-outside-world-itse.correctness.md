# refute:correctness:Interface fetches the outside world itse

*Workflow: review · Phase: Refute · Agent id: `a8ee4aa13a20fdecb` · Tool calls: 6*

## Task given to the agent

```text
You are reviewing the ARCHITECTURE of Simorgh, a self-improving personal AI agent written in Python (stdlib-first) at /Users/saeed/ws/Simorgh. The creator built it from scratch: ~87k lines in simorgh/, 18 subsystems (one package each) composed by a Kernel, talking only via typed messages on an async Bus, all state in an append-only Ledger of events, a Guardian that is the sole approver of every effect (HMAC token re-verified by Execution), worktree-isolated self-patching, a bootloader (simloader.py) that gates the checkout with the unit suite and rolls back. It chats (CLI/TUI/HTTP/Telegram/WhatsApp), talks (voice pipeline), controls the house (Home Assistant, Reolink cameras, Ring, Cast/Android TV), and runs benchmarks (GAIA/BFCL/SWE-bench).
  
  The creator asked: "review its architecture, evaluate it, tell me where I went wrong and how to improve it."
  
  Ground rules for you:
  - Read the CODE, not the docs, to establish what is true today. docs/EVOLUTION.md (5,254 lines) is a HISTORY; a bug it describes has very likely been fixed since. Do not report a historical finding as current state.
  - Previous reviews already exist and you must NOT simply repeat them. Already known (do not re-report unless you have something materially new to add): cameras use local ffmpeg/HLS instead of Home Assistant; self_patch.draft tool is named in learning/pipeline.py but not registered; Self Model capabilities["tools"] is never populated; no in-prompt sliding dialogue buffer for chat turns (orchestration/context.py); Ledger default backend is JSONL and ~1.4 GB; CHAT profile binds 34 tools; STT latency degrades under self-inflicted load; "unconnected wire" (designed slot, one side implemented, nobody writes it) is the project's dominant bug shape; test coverage thin in persona/learning/worldmodel; sim.sh auto-approve flips one boolean. Read docs/architecture-review-2026-09-18.html and docs/architecture-audit-2026.md quickly if you want the full list.
  - Useful orientation docs (read briefly, then go to code): docs/module-map.md, docs/architecture.md, docs/blueprint/02-system-architecture.md, docs/blueprint/03-contracts-and-messaging.md.
  - Every finding MUST cite file:line evidence you actually read, and where feasible a command whose output you quote. If a claim depends on runtime behaviour, try to establish it by a cheap command (python -c import + inspect, grep, wc, reading ~/.simorgh/simorgh.toml, listing ~/.simorgh/ledger). Do NOT boot the full system, do NOT run the full test suite, do NOT run anything that calls a paid model, do NOT modify any file in the repo.
  - Think like a senior systems architect. Distinguish (a) a design decision that is wrong or over-built for this system's real scale (one laptop, one family), (b) a design that is right but the implementation undermines it, (c) a genuine bug. Say which.
  - Your final text is data for an orchestrator, not a message to a human. Return only the structured output.
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "voice-interface-surfaces". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "Interface fetches the outside world itself (markets, news, YouTube search) outside Execution and Guardian",
    "kind": "wrong-design",
    "severity": "medium",
    "claim": "`dashfeeds.py` (1,110 lines, on by default) performs outbound HTTP with a spoofed browser User-Agent from a thread pool inside the surfaces layer, parses untrusted HTML/RSS/JSON, and its scraped YouTube ids are what `/api/dash/youtube` hands to `cast_play`; none of these calls is proposed to Guardian or visible in the ledger as actions.",
    "evidence": [
      "simorgh/interface/dashfeeds.py:73-79 `def fetch(url, ...)`: `urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 -- public read-only endpoints` with `USER_AGENT = \"Mozilla/5.0 (Macintosh ...) Safari/605.1.15\"`",
      "dashfeeds.py:122 `CNBC_BARS = \"https://ts-api.cnbc.com/harmony/...\"`; :792 `parse_youtube_results(f(YOUTUBE_SEARCH.format(...)))`; :925 `ThreadPoolExecutor(max_workers=self._concurrency, thread_name_prefix=\"dash-feeds\")`",
      "simorgh/interface/config.py:131 `dash_feeds: bool = True`; service.py:263-270 constructs `DashFeeds(...)` whenever the HTTP server is on",
      "httpapi.py:449-462 `_youtube_to_tv` -> `_run_for_page(\"cast_play\", {\"url\": f\"https://www.youtube.com/watch?v={video}\", \"mode\": \"full\"})`",
      "Creator's stated constraint (memory: reuse_open_source): 'only real constraint is Guardian must see every call'"
    ],
    "why_it_matters": "It is the one place in the system where network I/O happens without the action path, so the 'Guardian sees every effect' invariant is true of tools but not of the process. It also explains a third of Interface's size: a surfaces package that scrapes CNBC is a god-module by construction, and scraping code rots fastest.",
    "recommendation": "Move the fetchers into the execution/domains layer as read-only tools (`feeds_markets`, `feeds_news`, `media_search`) with their own cache and a `scope.network=True` proposal, and have a small scheduler task refresh them; Interface then reads a `dash:feeds` ledger stream or a bus reply and stays a renderer. If the creator consciously wants these to bypass Guardian as 'public reads', write that exception into contracts/topics.py or the blueprint so it is a decision rather than an accident.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read cited lines of dashfeeds.py |  1110 simorgh/interface/dashfeeds.py from datetime import datetime, timedelta, timezone from email.utils import parsedate_to_datetime from html.parser import HT |
| 2 | Bash | Read config, service, and httpapi cited lines |  logs_max_limit: int = 500 # The glass dashboard's collector (interface/dashfeeds.py): markets, # headlines, weather, charts, Wikipedia, jokes for `/dash`. Off, |
| 3 | Bash | Check Guardian/ledger touch, known-findings overlap, other HTTP in interface, network scope | == dashfeeds refs to bus/ledger/guardian/propose == 21: own RSS: the markets, technology, business, economics and 44:to the model -- Guardian's "see every call" |
| 4 | Bash | Read dashfeeds docstring, trace youtube id to route, check action scope | == dashfeeds docstring == """The dashboard's collector: what the TV page shows that is not Sim itself (interface/static/dash.html, served at `/dash`). Until 202 |
| 5 | Bash | Check other non-Guardian HTTP, page JS route usage, cast_play validation, config | == urlopen/http outside execution == simorgh/benchmark/datasets.py simorgh/cognition/providers/ollama.py simorgh/cognition/providers/together.py simorgh/contrac |
| 6 | Bash | Inspect GitHub fetch in dispatch, dash page video source, sizes, cast url handling | == dispatch.py github fetch context == The creator, live 2026-09-15: "why the sill doesn't show up in skills list". Because there are two unrelated things calle |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The mechanical facts check out and the finding is not in the known list (grep for dashfeeds/dash_feeds/cnbc/scrap across docs/architecture-review-2026-09-18.html, docs/architecture-audit-2026.md, docs/architecture-third-opinion-2026-09-18.md returns nothing). dashfeeds.py is 1,110 lines, on by default, does urlopen with a Safari User-Agent from a ThreadPoolExecutor, scrapes youtube.com/results, and contains zero references to bus/ledger/Guardian/proposal; the page's ambientPick() id is POSTed to /api/dash/youtube which calls cast_play. Three parts of the claim are wrong or overstated, though. (1) "the one place in the system where network I/O happens without the action path" is false: interface/dispatch.py:1785-1793 `_fetch_tree` hits api.github.com from the same surfaces layer, telegram.py:146 and whatsapp.py:228 poll/send over HTTP, and cognition providers, voice STT/TTS servers, memory/embedders and contracts/home/client.py all do network outside Guardian. dashfeeds is only unique in being a third-party HTML/RSS content scraper. (2) "a decision rather than an accident": the module docstring (dashfeeds.py:41-46) explicitly records the creator's decision and rationale ("This is a collector, not a tool: it acts on nothing, and it is not offered to the model -- Guardian's 'see every call' rule covers actions, and a GET of a public quote page that no model chose is not one"). It is a conscious exception documented in the module rather than in contracts/blueprint, so the recommendation's second half is largely already met. (3) "a third of Interface's size": 1110 / 10747 lines of simorgh/interface/*.py is ~10%, not a third. Also, the cast_play hop is itself proposed to Guardian via _run_tool (httpapi.py:387-403) and the video id is regex-constrained to 11 chars and forced into a youtube.com URL (httpapi.py:454-457), so the untrusted-input blast radius is "which YouTube video plays on the TV", not arbitrary URL casting. What survives: a deliberate, module-local exception to the "Guardian sees every call" invariant that is not recorded at the contracts/blueprint level, untrusted HTML parsed in the main process, and scraping code that will rot; that is a defensible design note at low severity, not a medium wrong-design.

### evidence

- simorgh/interface/dashfeeds.py:69-79 USER_AGENT = Mozilla/5.0 ... Safari/605.1.15; `with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- public read-only endpoints` returning response.read(8_000_000)
- simorgh/interface/dashfeeds.py:41-46 docstring: 'This is a collector, not a tool: it acts on nothing, and it is not offered to the model -- Guardian's "see every call" rule covers actions, and a GET of a public quote page that no model chose is not one. It is off with `[interface] dash_feeds = false`.' (the bypass is a documented decision, not an accident)
- grep -n -i 'bus|ledger|guardian|propos|action' simorgh/interface/dashfeeds.py -> only docstring/comment hits at lines 21, 44, 85, 135; no bus publish, no ledger append, no proposal
- simorgh/interface/dashfeeds.py:180-181 YOUTUBE_SEARCH = https://www.youtube.com/results?search_query=...; :790-792 _run_ambient calls parse_youtube_results(f(YOUTUBE_SEARCH.format(...))); :925 ThreadPoolExecutor(max_workers=self._concurrency, thread_name_prefix="dash-feeds")
- simorgh/interface/config.py:131 dash_feeds: bool = True; ~/.simorgh/simorgh.toml has no dash_feeds override; simorgh/interface/service.py:264-270 builds DashFeeds(...) whenever _http_enabled and config.dash_feeds
- simorgh/interface/static/dash.html:808-815 homeVideo() -> ambientPick() id; ytToTv POSTs {video:v.id,title} to /api/dash/youtube
- simorgh/interface/httpapi.py:449-459 _youtube_to_tv validates re.fullmatch(r"[A-Za-z0-9_-]{11}", video) then _run_for_page("cast_play", {url: youtube.com/watch?v=..., mode: full}); httpapi.py:387-403 _run_for_page goes through dispatch._run_tool with bus+ledger (Guardian sees the cast, not the scrape)
- REFUTES 'one place': grep -rln 'urlopen|http.client.HTTPSConnection|aiohttp' simorgh/ excluding execution/domains -> benchmark/datasets.py, cognition/providers/ollama.py, cognition/providers/together.py, contracts/home/client.py, contracts/skills.py, interface/dashfeeds.py, interface/dispatch.py, interface/telegram.py, interface/whatsapp.py, memory/embedders.py, voice/stt/whisper_cli.py, voice/stt/whisper_server.py, voice/tts/kokoro.py, voice/tts/piper.py
- simorgh/interface/dispatch.py:1785-1793 _fetch_tree: urlopen('https://api.github.com/repos/{org_repo}/git/trees/HEAD?recursive=1') # noqa: S310 -- github API over https (a second non-Guardian outbound fetch in the same surfaces layer)
- REFUTES 'a third of Interface': wc -l simorgh/interface/*.py -> 10747 total; dashfeeds.py 1110 lines = ~10%
- Not already known: grep -n -i 'dashfeeds|dash_feeds|cnbc|scrap' docs/architecture-review-2026-09-18.html docs/architecture-audit-2026.md docs/architecture-third-opinion-2026-09-18.md -> no matches

**severity adjustment:** lower

**corrected claim:** simorgh/interface/dashfeeds.py (1,110 lines, ~10% of interface/*.py, on by default via config.py:131) fetches CNBC, RSS feeds, Open-Meteo, Wikipedia, YouTube search results, etc. over urllib with a browser User-Agent from a thread pool, parses the untrusted HTML/RSS/JSON in-process, and never touches the bus, ledger or Guardian; the scraped YouTube ids are what dash.html posts to /api/dash/youtube, which then proposes a regex-constrained cast_play through Guardian. This is a conscious, documented exception (dashfeeds.py:41-46 argues a public GET no model chose is not an 'action'), recorded only in the module docstring rather than in contracts/blueprint. It is not the only non-Guardian network I/O in the process: interface/dispatch.py:1785-1793 fetches api.github.com from the same layer, Telegram/WhatsApp transports, LLM providers, STT/TTS servers, embedders and the Home Assistant client all do network outside the action path; dashfeeds is merely the only third-party content scraper. The remaining architectural point is a low-severity one: untrusted-content parsing and scraping rot live in the surfaces package, and the exception to 'Guardian sees every call' should be stated at the contract/blueprint level.

