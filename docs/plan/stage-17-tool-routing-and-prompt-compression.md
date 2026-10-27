# Stage 17 -- Tool routing and prompt compression, measured first

Status: **planned** (2026-10-27: plan written; item 1 is the gate for the rest) · Depends on: stage 14 (ablation runner, `toolchain/` selection scenarios), stage 4 (cacheable prefix), stage 2 (tool schemas to the model) · Modules touched: orchestration (owner), cognition, telemetry, evals; `docs/`

## Outcome

Sim offers the model only the tools a turn plausibly needs, and we know, with numbers, whether that and prompt compression make answers better, faster or cheaper. The ideas come from semantic-router (aurelio-labs) and the vLLM Semantic Router: a fast local embedding decides which tool *groups* a turn gets before the model is called. They also come from LLMLingua (Microsoft): a small model drops low-information tokens before the main model sees them.

## Why, and why measure first

- The chat agent is offered about 72 tools (`agents/chat.md`, with `cam_*` and similar patterns expanded), every turn, as schemas or marker descriptions. Two costs are claimed: tokens, and the model choosing the wrong tool among near neighbours.
- **Tokens may already be mostly paid for.** Stage 4 put the tool instructions in the stable system prefix, and Together and Gemini report `tokens_cached` on every `cognition.provider_call` span (`cognition/CONTRACT.md`). A routed tool list that changes per turn *breaks* that prefix, so routing can cost more than it saves. That is the trade nobody has measured.
- **Selection confusion is measurable now.** Stage 14's `toolchain/` pack has a *selection* category, and its runner gives a rate with an interval.
- **Latency matters for voice.** Fewer input tokens means a sooner first token, inside stage 3's two-second budget. A local embedding costs a few milliseconds, but a compression model costs much more.

## Definitions (shared by every item; do not rename)

- **Tool group**: a named set of tools in `agents/groups.toml` (orchestration lock, Guardian-protected like `agents/`). Example groups are `home`, `media`, `cameras`, `calendar_mail`, `memory`, `web`, `code`, `files`, `system` and `knowledge`. Each has a one-line description and 5-15 example utterances in English and Farsi. Every tool in a profile belongs to exactly one group, and a test pins that.
- **Core group**: always offered whatever the router says: `memory` (`remember`, `memory_search`, `memory_forget`), `tool_more`, and the answer path.
- **`tool_more{group}`**: a read-only meta tool that adds a group to the *next* step of this session. The model uses it when the router guessed wrong. It is gated by Guardian like any tool, and is recorded so misses can be counted.
- **Router**: embed the turn's text (and, for a task, its description) with Memory's configured embedder, the same one, so no new model is loaded. Take cosine similarity to each group's utterance centroid, and offer the top `route_top_k` groups (default 3) plus the core group. Also offer any group used in the last `route_sticky_turns` (default 3) turns of this conversation.
- **Stable order**: offered tools are always rendered in one canonical order, groups sorted by name, so two turns that route to the same groups share a byte-identical prefix and the provider's cache still hits.
- **Compression**: LLMLingua-2 (`llmlingua`, an XLM-RoBERTa token classifier, so it is not English-only), applied **only** to the text of long tool results (over `compress_min_chars`, default 4,000), such as `web_fetch` pages and file reads. It is never applied to the constitution, the persona, schemas, tool names, arguments, code, or anything a later step must quote exactly.
- **Config**:
  - `[orchestration] tool_routing = "off" | "shadow" | "on"`, default `off`. `shadow` routes, logs what it would have offered, and still offers everything.
  - `route_top_k`, `route_sticky_turns`.
  - `[cognition] compress_tool_results = false`, `compress_min_chars`, `compress_rate` (default 0.5).
  - Ablation names: `orchestration.ablate "routing"` and `cognition.ablate "compress"`; stage 14 presets `routed` and `compressed`.

## Action items

1. **Measure where a turn's tokens go.** *Lock `telemetry`, `cognition`.* For every think, record input tokens split by block: prefix (constitution, persona, self), tool schemas or markers, memory block, conversation window, tool results, and the question. Also record `tokens_cached`.
   - `python -m simorgh.telemetry tokens --since 7d` prints the split and the cache hit rate per provider and per purpose (chat, voice, task).
   - Write `docs/findings/<date>-where-the-tokens-go.md` from the live ledger, reading only token counts, never content.

   **Gate**: items 3 and 4 go ahead only if tool schemas are more than 20% of *uncached* input tokens on chat or voice turns, or if item 2 shows a selection or latency problem that routing can fix. Otherwise this stage closes with the finding.

2. **A selection-stress scenario set.** *Lock `evals`; after stage 14 merges.* Add 10 scenarios to `toolchain/` with near-neighbour tools: `home_call` vs `room_play` vs `media_control`, `remind` vs a calendar tool, `memory_search` vs `kb_search` vs `web_search`, `cam_snapshot` vs `look_at_image`. Each has an English and a Farsi variant. They run in the stage 14 matrix as they are; items 3 and 4 add presets to it.

3. **Tool groups and the router, shadow first.** *Lock `orchestration` (with `agents/`); after the item 1 gate.*
   - Add `agents/groups.toml` and `orchestration/routing.py`. The router is pure: `route(text, history, groups, embed) -> tuple[str, ...]`.
   - Add the `tool_more` tool (registered through Execution's extra-tools seam; `execution` lock, or ask the creator).
   - In `shadow` mode, log `routing.shadow{offered, used}` per turn. After a week of live shadow, the **miss rate** is the share of turns where the model used a tool the router would not have offered. Turn routing `on` only if the miss rate is under 3% and the selection category does not regress.

   **Acceptance**: unit tests for routing, stickiness, stable order (two turns routed alike give a byte-identical tool block), and `tool_more` adding a group; with `off`, the prompt is byte-identical to today.

4. **Compression of long tool results, as an experiment.** *Lock `cognition`; after the item 1 gate; parallel to item 3.*
   - Add `cognition/compress.py`, with `llmlingua` imported under `try/except ImportError`. When it is absent, the `compress` switch reports itself unavailable by name.
   - It runs in a worker thread with a timeout. On timeout or error, the original text is sent; compression may never block or fail a turn.
   - It is measured on the stage 14 research cases (GAIA level 1 via `simorgh/benchmark`) and the `toolchain/` pack: accuracy, tokens, and added wall-clock.

   **Acceptance**: it is kept only if tokens fall by at least 40% on long-result turns with accuracy inside the `sim` interval, and the added latency is under 300 ms p95 on this laptop. Otherwise the module stays, off, with the finding.

5. **Decide.** Write the findings for items 3-4: per model, the tokens saved, the cache hit rate before and after, selection accuracy, first-token latency on voice, and the miss rate. Then flip the defaults or leave them off.

## What this must never do

- Hide a tool from Guardian, or let routing decide what is *allowed*. Routing decides what is *offered*; Guardian still decides every call. A tool not offered is not a tool denied.
- Route away the memory tools or `tool_more`. A wrong route must always be recoverable inside the same turn.
- Compress anything the model must quote exactly: names, numbers, paths, code, arguments, Farsi text in a reply the model will read back aloud, or the safety and identity lines.
- Break the cacheable prefix silently. Every routing change is measured with `tokens_cached` beside it.
- Load a second embedding model for routing. It uses Memory's.

## Definition of done

- [ ] Item 1's finding is written and the gate decided.
- [ ] If the gate opens: items 2-4 built with tests, shadow run for a week, the item 5 findings written, and the defaults set by the numbers.
