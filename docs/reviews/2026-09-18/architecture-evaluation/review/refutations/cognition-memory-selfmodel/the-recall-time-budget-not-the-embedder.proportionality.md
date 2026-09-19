# refute:proportionality:The recall time budget, not the embedder

*Workflow: review · Phase: Refute · Agent id: `a2b33c4ebe9aab694` · Tool calls: 6*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "cognition-memory-selfmodel". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Read embed, embedders and memory config | """A dependency-free semantic embedding via the hashing trick, ported verbatim from v1 `src/memory/long_term.py::embed_text` (docs/blueprint/ subsystems/05-memo |
| 2 | Bash | Read context.py timeouts, store warm, toml and module-map latencies | """ContextAssembler (16 section 5): gathers the memory block and the session transcript for one `cognition.think` call. The persona voice and the self summary a |
| 3 | Bash | Read recall path, warm wiring, timeout configurability, index embedder usage |  return f"it answered with an error: {code}" return "it answered with an error" class Assembler: def __init__(self, bus, *, clock=None, timeout_s: float = DEFAU |
| 4 | Bash | Check timeout wiring, warm at boot, local embedder caching, findings docs | ----ASSEMBLER_CTOR simorgh/cognition/service.py:212: self._assembler = PromptAssembler( simorgh/orchestration/session.py:652: self._assembler = Assembler(bus, c |
| 5 | Bash | Check timeout config plumbing, sentence-transformers availability, the commit that chose hashing, and doc latencies | ----ASSEMBLE_TIMEOUT simorgh/orchestration/worker.py:136: assemble_timeout_s: float = DEFAULT_TIMEOUT_S, think_timeout_s: float \| None = None, simorgh/orchestra |
| 6 | Bash | Check whether recall applies a similarity threshold | ---- 1:238: async def retrieve(self, *, query: str, kinds: list[str], k: int, filters: dict \| None) -> tuple[list[MemoryItem], bool]: 5:242- Every live record o |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The facts cited all check out: the default embedder is the 256-bucket sha256 hashing trick (simorgh/memory/embed.py:14-32), `embedder: str = "hashing"` (simorgh/memory/config.py:64), ~/.simorgh/simorgh.toml has no `[memory]` section (grep shows only [voice]/[interface]/[execution]/[cognition*]), the 0.000 paraphrase measurement is in embedders.py:6-14, `DEFAULT_TIMEOUT_S = 0.25` is at orchestration/context.py:21, and docs/module-map.md:171-173 gives stt 1.8-6.8 s / llm 1.3-9.5 s. `sentence_transformers` is importable on this machine (find_spec -> True), so the switch from `auto` to `hashing` was a real decision, not a fallback.

The CAUSAL claim is where the finding goes wrong. (1) The 0.25 s timeout does not force hashing: the warm local cost is 47 ms, five times inside the budget, and the three recalls per turn are gathered concurrently so they share one timeout (context.py:233-262). Raising the timeout to 1 s changes nothing on the warm path and does not cover the 24.9 s cold path either. (2) The cold cost is already moved to boot: memory/service.py:68-75 spawns `warm()` as a background task and a recall arriving first waits on the same work (store.py:175-187). (3) The deciding reason recorded in commit 664d811 ("Recall stays on the hashing embedder") and config.py:51-63 is a QUALITY measurement, not latency: on the creator's own 2,422-record store, MiniLM-L6 moved the 0.000 paraphrase pairs only to 0.197/0.329 while "turn the lights on" vs "turn the lights off" rose 0.750 -> 0.893 and stayed the top score. Recall is pure top-k with no similarity threshold (store.py:238-258, no threshold in memory/*.py), so a 0.2 score is findable but easily outranked. The finding's recommendation to "raise the timeout and opt in local" ignores that the creator tried exactly this and measured that it did not fix the case it was chosen for. The actual mitigation the code chose for the cross-turn problem is the recency recall (`_MEMORY_RECENT_K = 6`, context.py:34-71) and the per-speaker recall, which address the falcon/sparrow and birthday cases without any embedder change.

Scale lens: on one laptop for one family, the paraphrase gap is real but the design decision was measured and reasoned, and the proposed fix is disproportionate to its measured benefit. The second recommendation (embed distilled facts rather than raw turn transcripts) is sound and independent of the timeout, and is the part worth keeping. What remains true and unreported: `assemble_timeout_s` is a constructor parameter (session.py:607, worker.py:136) never read from simorgh.toml, so the budget is not operator-tunable; and the weakness is the embedding target (raw transcripts) and MiniLM-L6's small size, not the 0.25 s constant.

### evidence

- simorgh/memory/embed.py:14-32 -- EMBED_DIM=256, sha256 bucket hashing, L2-normalised; the hashing trick as claimed
- simorgh/memory/config.py:51-64 -- `embedder: str = "hashing"`; comment records BOTH the 24.9 s cold / 47 ms warm cost AND the quality result: paraphrase pairs 0.000 -> 0.197/0.329, 'lights on' vs 'off' 0.750 -> 0.893 'stayed the highest score in the set. Better ranking among related memories, no fix for the case it was chosen for.'
- git log -S"24.9 SECONDS" -> commit 664d811 'Recall stays on the hashing embedder': same two reasons; the quality result is what 'did not pay for that'
- simorgh/orchestration/context.py:21 `DEFAULT_TIMEOUT_S = 0.25`; context.py:233-262 the matched/recent/speaker recalls are gathered concurrently ('this still costs one `_timeout_s` rather than two')
- simorgh/memory/service.py:68-75 -- `self._warm = asyncio.create_task(self._warm_index(), name="memory-index-warm")` at start(); 'A recall that arrives first simply waits on the same work.' So the cold cost is boot-time, as the finding itself concedes
- simorgh/memory/store.py:175-187 `warm()`; store.py:238-258 `retrieve` scores every record and returns top-k; `grep -rn "threshold\|min_sim\|min_score" simorgh/memory/*.py` -> no matches (no similarity floor)
- simorgh/orchestration/session.py:607,652 and worker.py:136,176 -- `assemble_timeout_s` is a constructor default only; not plumbed from simorgh.toml
- `python3 -c` find_spec('sentence_transformers') -> True on this machine; `grep -n '^\[' ~/.simorgh/simorgh.toml` -> no [memory] section
- docs/module-map.md:171-173 -- 'stt 1.8-6.8 s ... llm 1.3-9.5 s ... full response 4-17 s' (2026-09-18)
- simorgh/orchestration/context.py:34-71 -- `_MEMORY_RECENT_K = 6` recency recall added specifically for the falcon/sparrow and birthday-correction cases, i.e. the cross-turn fix the code actually chose

**severity adjustment:** lower

**corrected claim:** Production recall uses a 256-bucket hashing embedder (memory/config.py:64, no [memory] section in simorgh.toml) that scores true paraphrases at 0.000 (embedders.py:6-14). But it is not "forced by" the 0.25 s recall budget: a warm local MiniLM costs 47 ms, well inside 0.25 s, the three per-turn recalls share one timeout, and the 24.9 s cold cost is already paid at boot by a background `warm()` (memory/service.py:68-75). The creator switched from `auto` to `hashing` (commit 664d811) chiefly because the local model, measured on the real 2,422-record store, lifted paraphrase pairs only to 0.197-0.329 while making "lights on" vs "lights off" MORE similar (0.893, top of the set). Raising the timeout would therefore not buy the claimed paraphrase ability. The real limitation is what gets embedded (raw turn transcripts) and the weakness of MiniLM-L6 on this data; embedding distilled facts is the worthwhile part of the recommendation. Minor: `assemble_timeout_s` is a constructor default not exposed in simorgh.toml.

