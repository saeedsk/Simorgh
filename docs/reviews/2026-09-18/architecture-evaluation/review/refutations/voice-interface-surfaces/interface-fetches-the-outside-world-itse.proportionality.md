# refute:proportionality:Interface fetches the outside world itse

*Workflow: review · Phase: Refute · Agent id: `ae214417e8b74da89` · Tool calls: 5*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "voice-interface-surfaces". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Inspect dashfeeds fetch, UA, and thread pool |  1110 simorgh/interface/dashfeeds.py from datetime import datetime, timedelta, timezone from email.utils import parsedate_to_datetime from html.parser import HT |
| 2 | Bash | Read config default, service wiring, youtube cast path, and DashFeeds class | --- config.py logs_max_limit: int = 500 # The glass dashboard's collector (interface/dashfeeds.py): markets, # headlines, weather, charts, Wikipedia, jokes for  |
| 3 | Bash | Find other outbound network sites and prior mentions of dashfeeds | --- urlopen / http clients outside execution/ (per top-level package) (eval):1: no matches found: --include=*.py --- in execution/ (eval):1: no matches found: - |
| 4 | Bash | Survey other network sites, prior review coverage, dashfeeds header, and cast path | --- outbound HTTP outside execution/, per file simorgh/benchmark/datasets.py simorgh/cognition/providers/ollama.py simorgh/cognition/providers/together.py simor |
| 5 | Bash | Confirm Guardian path, log sink, package size, and other network sites | --- _run_tool in dispatch.py 7:`work` into `tasks`; `propose`/`patch`/`batch`/`evolve` into `improve`; 1161: `action.proposed` exactly as a Worker does, so Guar |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The mechanical facts are verified: dashfeeds.py fetches with a Safari User-Agent from its own ThreadPoolExecutor, is on by default, parses untrusted HTML/RSS/JSON, and its scraped YouTube ids are what /api/dash/youtube passes to cast_play. Feed failures go to the logger, not the ledger, so they are not ledger-visible. But three of the finding's framing claims fail against the code. (1) "The one place in the system where network I/O happens without the action path" is false: fourteen other non-execution files do outbound HTTP (LLM providers, Telegram/WhatsApp long-poll, the Home Assistant client, embedders, voice engines, dispatch's GitHub call), and the blueprint explicitly carves out direct observation outside Execution for World Model and Memory. The Guardian invariant has always been about model-chosen actions, not process-level egress. (2) "A decision rather than an accident" is already the case: the module docstring (dashfeeds.py:47-52) states the exception in so many words. It is not written into contracts/topics.py or the blueprint, which is the one legitimate residue of the recommendation. (3) The cast_play effect IS Guardian-gated: _run_for_page goes through dispatch._run_tool, which publishes ACTION_PROPOSED; the video id is regex-validated to 11 URL-safe chars; and the trigger is a human POST from the dashboard, not the model. Scraped-id taint reaches only a youtube.com URL, which is the intended behaviour. (4) "A third of Interface's size" is 10% (1,110 of 10,747 lines). Scale lens: turning ~14 keyless public-feed parsers polling every 60s-6h into Guardian-proposed tools plus a scheduler task would add a bus round-trip and a Guardian evaluation per poll and pour thousands of read-only action events per day into a ledger that is already known to be 1.4 GB, for reads no model chose and that act on nothing. That is more work and more noise than it saves on one laptop for one family. The valid kernel is small: scraping code that rots fast lives in the surfaces package, and the exception is documented only in a docstring. That warrants a low-severity placement note (move dashfeeds to a sibling package, or write the 'public keyless read' exception into the blueprint), not a redesign through the action path.

### evidence

- simorgh/interface/dashfeeds.py:69-79: USER_AGENT Safari string; fetch() uses urllib.request.urlopen with # noqa: S310 -- public read-only endpoints (confirmed)
- simorgh/interface/dashfeeds.py:925: ThreadPoolExecutor(max_workers=self._concurrency, thread_name_prefix="dash-feeds") (confirmed); :792 parse_youtube_results(f(YOUTUBE_SEARCH.format(...))) (confirmed)
- simorgh/interface/config.py:131 dash_feeds: bool = True; service.py:264-270 constructs DashFeeds when HTTP is on (confirmed)
- simorgh/interface/dashfeeds.py:942-948 _log() writes to self._logger.info, not the ledger; feed failures are log lines, not ledger events (the ledger-invisibility part stands)
- simorgh/interface/dashfeeds.py:47-52 docstring: 'This is a collector, not a tool: it acts on nothing, and it is not offered to the model -- Guardian's "see every call" rule covers actions, and a GET of a public quote page that no model chose is not one.' -- the exception is a stated decision, not an accident
- grep -rl urlopen|http.client|websockets simorgh (excluding execution/) lists 15 files: benchmark/datasets.py, cognition/providers/ollama.py, cognition/providers/together.py, contracts/home/client.py, contracts/skills.py, interface/dispatch.py:1792 (GitHub API), interface/telegram.py:146, interface/whatsapp.py, memory/embedders.py:224, voice/stt/whisper_cli.py, voice/stt/whisper_server.py, voice/tts/kokoro.py, voice/tts/piper.py, interface/dashfeeds.py -- refutes 'the one place'
- docs/blueprint/02-system-architecture.md:73-76: 'World Model observes the repository tree and git state directly (read-only) rather than through Execution tools, the same way Memory reads its own index' -- the blueprint already allows read-only observation outside Execution
- simorgh/interface/httpapi.py:387-389, 401-402: _run_for_page -> dispatch._run_tool; dispatch.py:1330 bus.publish(topics.ACTION_PROPOSED ...) with proposed_by 'interface:dash' -- the cast_play effect is Guardian-gated
- simorgh/interface/httpapi.py:452: re.fullmatch(r"[A-Za-z0-9_-]{11}", video) -- scraped id is validated before it becomes a youtube.com URL; route is a POST a human sends from the page
- wc -l simorgh/interface/*.py: dashfeeds.py 1110 of 10747 total = 10%, not 'a third of Interface's size'
- grep -i dashfeeds|dash_feeds|cnbc|scrap docs/architecture-review-2026-09-18.html docs/architecture-audit-2026.md docs/architecture-third-opinion-2026-09-18.md -> no matches; the finding is new, not a repeat

**severity adjustment:** lower

**corrected claim:** Interface's dashboard collector (dashfeeds.py, 1,110 lines, on by default) polls ~14 keyless public endpoints with a browser User-Agent from its own thread pool and parses untrusted HTML/RSS/JSON; its fetches and failures are logged, not ledgered, and the exception to 'Guardian sees every call' is stated only in the module docstring, not in contracts or the blueprint. It is not the only network I/O outside the action path (LLM providers, chat channel polling, the Home Assistant client, embedders and voice engines all fetch directly, and the blueprint permits direct read-only observation), the scraped YouTube ids only reach the TV through a regex-validated, Guardian-proposed cast_play that a human triggers from the page, and the module is 10% of Interface, not a third. The real issue is placement and documentation (fast-rotting scraper code living in the surfaces package; an undocumented exception), not a breach of the action-path invariant; routing these polls through Guardian would add ledger noise and latency for reads no model chose.

