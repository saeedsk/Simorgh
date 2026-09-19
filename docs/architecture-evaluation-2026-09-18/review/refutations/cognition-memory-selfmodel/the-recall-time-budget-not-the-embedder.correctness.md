# refute:correctness:The recall time budget, not the embedder

*Workflow: review · Phase: Refute · Agent id: `a3ce364837400d736` · Tool calls: 5*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "cognition-memory-selfmodel". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "The recall time budget, not the embedder, is the wrong constant: hashing is forced by a 0.25 s limit on a path whose STT alone takes seconds",
    "kind": "wrong-design",
    "severity": "medium",
    "claim": "Embeddings are a 256-bucket sha256 bag of words with no paraphrase ability (measured 0.000 for 'stop the loop' vs 'halting a runaway iteration'), chosen because `orchestration/context.py` gives the whole recall 0.25 s and a local sentence-transformer costs 47 ms warm; that budget is arbitrary next to 1.8-6.8 s of STT and 1.3-9.5 s of LLM per turn, and it is what keeps the memory that every prompt depends on at vocabulary-match quality.",
    "evidence": [
      "simorgh/memory/embed.py:23-32 (hashing trick), simorgh/memory/config.py:64 `embedder: str = \"hashing\"`; ~/.simorgh/simorgh.toml has no `[memory]` section, so production runs hashing",
      "simorgh/memory/embedders.py:6-16: '\"how do I stop the loop\" vs \"halting a runaway iteration\" -> 0.000'; memory/config.py:51-63: local MiniLM '24.9 SECONDS on the first call ... warm it is still 47 ms against 3 ms' and 'orchestration/context.py allows recall 0.25 s'",
      "simorgh/orchestration/context.py:21 `DEFAULT_TIMEOUT_S = 0.25`; docs/module-map.md section 3: 'stt 1.8-6.8 s ... llm 1.3-9.5 s'",
      "simorgh/memory/store.py:175-187 `warm()` already builds the index at boot, so the 24.9 s cold cost is boot-time, not first-turn time"
    ],
    "why_it_matters": "Memory is the only cross-turn context (see the session finding), so recall quality bounds conversation quality. The current choice optimises a latency that is a rounding error on the voice path while accepting that a fact phrased differently last week is unfindable.",
    "recommendation": "Raise the recall timeout to ~1 s, opt in `[memory] embedder = \"local\"` (warm at boot via `warm()`), and keep hashing as the fallback the code already has. Separately, consider embedding distilled facts ('Saeed's mini PC is called falcon') rather than raw turn transcripts, which is where paraphrase matters most.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read memory embed, config and embedders sources | """A dependency-free semantic embedding via the hashing trick, ported verbatim from v1 `src/memory/long_term.py::embed_text` (docs/blueprint/ subsystems/05-memo |
| 2 | Bash | Read context.py timeout, store.warm, toml, module-map, timeout callers | ----CONTEXT """ContextAssembler (16 section 5): gathers the memory block and the session transcript for one `cognition.think` call. The persona voice and the se |
| 3 | Bash | Check warm callers, timeout wiring, and how embedder flows into index and recall | ----WARM-CALLERS (eval):1: no matches found: --include=*.py ----ASSEMBLE-TIMEOUT-WIRING (eval):1: no matches found: --include=*.py ----INDEX-EMBEDDER ugrep: war |
| 4 | Bash | Check timeout wiring, known-findings docs, and recall index sync path | ----WARM-CALLERS simorgh/memory/service.py:75: records = await self.engine.warm() ----ASSEMBLE-TIMEOUT-WIRING simorgh/orchestration/worker.py:30:from .context i |
| 5 | Bash | Measure hashing similarity, check sentence-transformers presence, config wiring, and context assemble path | ----MEASURE stop-loop vs halting: 0.0 lights on vs off: 0.75 ----ST-INSTALLED sentence_transformers 6.0.1 ----ORCH-CONFIG-ASSEMBLE ----VOICE-PATH simorgh/interf |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The factual substrate checks out: production runs the 256-bucket sha256 hashing embedder (simorgh/memory/embed.py:23-32, config.py:64 `embedder: str = "hashing"`, and ~/.simorgh/simorgh.toml has no [memory] section), I reproduced the 0.000 paraphrase score live, DEFAULT_TIMEOUT_S = 0.25 is hard-coded (context.py:21) with no config knob (orchestration/config.py has no assemble key; only constructor defaults at session.py:607 and worker.py:136), and docs/module-map.md:171-172 records STT 1.8-6.8 s and LLM 1.3-9.5 s. None of this is in the known-findings list (the third-opinion doc mentions the 250 ms query only as the sole cross-turn context, not as a wrong constant).

The causal thesis, however, is overstated. The finding says hashing is "forced by" the 0.25 s budget. The code's own record (config.py:51-63) gives two reasons for rejecting `auto`/local, and the budget is only half of one of them: (1) the 24.9 s first-call cost, which bites only inside the boot window, and (2) a measured quality verdict that the local MiniLM gave "better ranking among related memories, no fix for the case it was chosen for" (paraphrases 0.000 -> 0.197/0.329 while "lights on" vs "off" rose to 0.893 and stayed top). At steady state the same comment measures local at 47 ms per recall; three recalls per turn is ~141 ms, inside 0.25 s. So once warm, the budget does not force hashing at all, and raising it to 1 s would not change the embedder choice on its own. The finding's evidence item 4 also slightly misreads warm(): service.py:68 spawns it as an un-awaited background task, so turns in the first ~25 s after boot still lose the memory block (recall waits on the index lock, then the 0.25 s request times out); the cold cost overlaps boot but is not removed from the first turns.

What survives: the constant is arbitrary and unconfigurable, sentence-transformers 6.0.1 is installed so `local` is available, and the recommendation to embed distilled facts rather than raw turn text is the genuinely useful part. The finding is better framed as "memory quality is bounded by a tiny model over raw transcripts, and the creator's own measurement shows a bigger/better embedder or distilled facts is the lever, not the timeout".

### evidence

- simorgh/memory/embed.py:23-32: `bucket = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % dim` with EMBED_DIM = 256 -- hashing trick confirmed
- simorgh/memory/config.py:64 `embedder: str = "hashing"`; `grep -n memory ~/.simorgh/simorgh.toml` returns nothing (sections present: voice, interface, execution, cognition, cognition.providers, cognition.providers.ollama) -- production runs hashing
- python3 -c 'from simorgh.memory.embed import embed_text, cosine_similarity as c; ...' -> 'stop-loop vs halting: 0.0', 'lights on vs off: 0.75' -- paraphrase blindness reproduced
- simorgh/orchestration/context.py:21 `DEFAULT_TIMEOUT_S = 0.25`; context.py:220 `reply = await self._bus.request_or_error(req, timeout=self._timeout_s)`; `grep -n assemble simorgh/orchestration/config.py` returns nothing -- the budget is not configurable from the toml
- simorgh/memory/config.py:51-63 (comment): local costs '24.9 SECONDS on the first call ... warm it is still 47 ms against 3 ms, three recalls to a turn' AND 'paraphrase pairs that scored 0.000 became findable (0.197, 0.329), but "turn the lights on" vs "off" went 0.750 -> 0.893 and stayed the highest score in the set. Better ranking among related memories, no fix for the case it was chosen for.' -- quality, not only the budget, drove the decision; 3 x 47 ms = ~141 ms fits inside 0.25 s once warm
- simorgh/memory/service.py:64-68: `self._warm = asyncio.create_task(self._warm_index(), ...)` with comment 'Not awaited ... A recall that arrives first simply waits on the same work' -- warm() runs at boot but concurrently, so first-window turns still time out at 0.25 s
- simorgh/memory/store.py:175-187 warm() docstring: index build '640 ms measured at that size -- and orchestration/context.py allows 0.25 s'
- simorgh/memory/recall.py:45-48: a real embedder is 'embedded once ever, instead of once per retrieve' via the index -- supports the 47 ms warm figure
- python3 -c 'import sentence_transformers' -> 'sentence_transformers 6.0.1' -- `local` is importable on this machine
- docs/module-map.md:171-172: 'Latencies, measured live on 2026-09-18: `stt` 1.8–6.8 s ... `llm` 1.3–9.5 s'
- docs/architecture-third-opinion-2026-09-18.md:95 mentions the '250ms memory query' only as the sole recall mechanism; no prior review frames the constant or the embedder choice as the finding

**severity adjustment:** lower

**corrected claim:** Production memory recall uses a 256-bucket sha256 bag-of-words embedder (memory/embed.py:23-32; config.py:64 default, no [memory] override in ~/.simorgh/simorgh.toml) that scores 0.000 on paraphrases (reproduced), and every prompt's memory block is fetched under a hard-coded, non-configurable 0.25 s budget (orchestration/context.py:21) that is two orders of magnitude below the turn's STT (1.8-6.8 s) and LLM (1.3-9.5 s) costs. But the budget is not what keeps hashing in place: config.py:51-63 records that the local MiniLM was measured at 47 ms warm (about 141 ms for the three recalls of a turn, inside 0.25 s) and was rejected because of the 24.9 s cold re-embed, now moved to an un-awaited boot task (memory/service.py:68, so turns in the first ~25 s still lose the block), and because its quality gain was marginal (paraphrases only reached 0.197/0.329 while 'lights on' vs 'off' scored 0.893). The real design weakness is embedding raw turn transcripts with a tiny model; the fixes are distilled-fact records and a stronger embedder warmed at boot, with the timeout made configurable as a secondary cleanup.

