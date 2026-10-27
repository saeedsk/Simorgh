# Stage 15 -- Entity-graph memory (native), measured against Graphiti as a sidecar

Status: **in progress** (2026-10-27: items 1-3 and 7 merged, entities off by default; items 4, 5, 5b and 6 run (findings `docs/findings/2026-10-27-guardrails-sidecars-and-tokens.md`: native_graph 40/46, Graphiti 41/46, Cognee 32/46); item 5c (Mem0) built; its first paid run ingested all 150 episodes ($0.27) and then hit a Mem0 2.x API change on search (fixed, not rerun: the day's $2 cap); item 8 built (core memory blocks, `memory:core`, `memory_core_edit`), off by default (`[memory] core_blocks = false`) until the suite runs with them on and off -- the edit has its own declared topic `memory.core.edit` (execution alone may publish it) and Guardian's `CoreMemoryRule` denies an edit of any block but the requester's own or, for a household member, the household block (a2a and unknown speakers denied) Contract follow-ups done: `Person.relations` (written by `world.people.update{set_relation}`, the tier-3 `people` tool and the console's `people relation <name> <word> [<other>]`; read by Memory over the `people` query, so "my son" from Saeed resolves to Aran); `memory.summary`/`memory.reconcile` purposes with rolling-day budget rows; `hop`/`via`/`summary`/`entity` declared on `MemoryRetrieveReply.facts`; `_fact_lines` renders hop facts "(via X)" and summaries under `[orchestration] memory_graph_lines`) · Depends on: stage 5 (memory tiers), stage 4 (`simorgh/evals/`), stage 14 item 4's runner shape · Modules touched: memory (owner), evals; `docs/`

## Outcome

Sim's semantic memory knows **entities**, not just strings. "Soo", "Soodeh" and "my wife" resolve to one `person:soodeh`. Recall follows facts one or two hops: "who fixed the boiler last time, and what's their number?" joins `boiler → fixed_by → Reza` with `Reza → phone → ...`. Each entity carries a short summary that is rebuilt while Sim sleeps. All of this is stdlib, inside `simorgh/memory`, on the ledger.

The same questions are also answered by **Graphiti** (github.com/getzep/graphiti) as a sidecar. It is fed the same episodes, and runs only inside the eval harness, never in the live Sim. One table then says whether the native version is good enough, or whether Graphiti is worth its dependencies, its graph database and its 5-10 model calls per episode:

```
python -m simorgh.evals memory --systems native,native_graph,graphiti,cognee --paid --cap-usd 2
```

## Why

- Sim already has Graphiti's bi-temporal core: `Fact{valid_from, valid_to, superseded_by, source_refs}`, supersession instead of deletion, contradictions on a stream, BM25 fused with dense vectors (`memory/CONTRACT.md`). What it lacks is entity resolution, multi-hop recall and entity summaries.
- Fact subjects and objects are free strings today. A fact stored as "Soo likes tea" and a question about "Soodeh" do not meet.
- The live ledger holds about 1,800 episodes and 280 fact events (2026-10-27). That is household scale: an in-memory join is trivial, and a graph database is not needed to *use* a graph.
- Graphiti is a credible reference implementation (temporal context graph, arXiv 2501.13956). Measuring against it tells us what we leave on the table, which is cheaper than guessing.

## Definitions (shared by every item; do not rename)

- **Entity**: `Entity{id, type, name, aliases, summary, person_scope, source_refs}` on a new stream `memory:entities`. Each one is an event (`entity.created`, `entity.alias_added`, `entity.merged`, `entity.summary`), never an edit. `type` is one of `person | place | device | organisation | thing | event`.
  - `id` is `person:<slug>` for a person the People registry knows (`contracts/people.py`), and `<type>:<slug>` otherwise.
  - A merge is a new event naming the surviving id. Facts keep their ids, and resolution maps old ids to the surviving one.
- **Resolution**: string → entity id. In order:
  1. exact alias;
  2. the People registry and the speaker book;
  3. normalised fuzzy match (casefold, strip possessives and articles, edit distance ≤ 1 for names of five or more characters);
  4. otherwise a new entity.

  A model is consulted only on the sleep tick, and only for candidate pairs that step 3 flagged as close but not certain. "My wife", "my son" and similar kinship words resolve through the speaker's People record (`relations`). They never create an entity named "my wife".
- **Multi-hop recall**: for each entity a query resolves to, the live facts where it is subject or object (hop 1). Then, for each object entity reached, its live facts (hop 2), capped at `graph_max_facts` (default 12). The cap counts every fact added, and hop-1 facts outrank hop-2. Results go into the same `facts` block of `memory.retrieve.reply`, marked `hop: 1 | 2`.
- **Systems compared**:
  - `native`: today's memory, with no entity layer;
  - `native_graph`: items 1-3;
  - `graphiti`: the sidecar of item 5.

## Action items

1. **Entities and resolution.** *Lock `memory`.*
   - New `simorgh/memory/entities.py`: `Entity`, `EntityIndex` (a fold of `memory:entities`, as `FactIndex` folds `memory:facts`), and `resolve(text, *, speaker, people) -> id | None`.
   - Fact writes (`facts.py`, `store_fact`, consolidation's fact pass) record `subject_id` and `object_id` beside the strings. The strings stay, so old facts and every existing reader still work.
   - A one-off backfill on the sleep tick resolves existing live facts.
   - Config: `[memory] entities = true`, the default once item 4 shows no regression.

   Acceptance:
   - unit tests for each resolution rule, and for a merge leaving old fact ids resolvable;
   - an existing fact stored as "Soo" is found by a query about "Soodeh";
   - `python tools/modtest.py memory` is green.

2. **Multi-hop recall.** *Lock `memory`; after item 1.* In `recall.py`, after the existing scoring, add the facts reached by the definition above, deduplicated against what is already in the block, with `graph_max_facts` and `graph_hops` (default 2, 0 disables) in `[memory]`.

   Acceptance:
   - a test with "the boiler was fixed by Reza" and "Reza's number is 0912…" answers "number of whoever fixed the boiler" with both facts in the block;
   - `graph_hops = 0` reproduces today's block byte for byte;
   - `CONTRACT.md` documents the new `hop` field in the reply.

3. **Entity summaries.** *Lock `memory`; after item 1.* On the sleep tick, an entity with new facts since its last summary gets a 1-3 sentence summary through `cognition.think` (purpose `memory.summary`, within Cognition's budget, never a direct provider call). The summary is checked by `consolidation.py::untraceable` (no specifics absent from its facts) and stored as an `entity.summary` event. Recall adds the summary of each entity the query resolved to, one line each.

   Acceptance:
   - an untraceable summary is dropped, with a test;
   - the floor provider writes none and reports skipped.

4. **The memory eval suite.** *Lock `evals`; after stage 14 releases `evals`.*
   - A scripted household corpus of about 150 episodes over a simulated month, invented people only, as in `house/people.py`.
   - 40-60 questions in six categories:
     - **alias** (same person, other name);
     - **multi-hop**;
     - **temporal now** (current value after a change);
     - **temporal before** ("what was the plumber's number before he changed it");
     - **privacy** (person A asks for person B's private fact and must not get it);
     - **negative** (never said, so answer unknown).
   - Each question is scored on whether the **facts block** contains the right fact, and for privacy and negative, on whether it does not. This is a deterministic check on the context, as the household probes already do (`evals/scenario.py`). An optional paid mode also asks the model and judges the answer by the expected value.
   - `python -m simorgh.evals memory --systems native,native_graph` is free, using the floor provider and the hashing embedder.

   Acceptance: the suite runs free in under two minutes, and reports per category with a 95% interval.

5. **Graphiti as a sidecar.** *Lock `evals`; after item 4.*
   - `simorgh/evals/memory/graphiti_side.py`, with `graphiti_core` imported under `try/except ImportError`. When it is absent, the `graphiti` system reports every case skipped, by name. It never runs inside the Kernel; Memory does not import it.
   - It ingests the same corpus episode by episode with `add_episode`, into **FalkorDBLite** (embedded, no server) in a temporary directory.
   - It uses an OpenAI-compatible client pointed at the same Together model Sim uses, with the key from the environment and a hard `--cap-usd` counted from the client's usage fields.
   - `GRAPHITI_TELEMETRY_ENABLED=false` is forced before import.
   - For each question it calls `graphiti.search(question)` and maps the returned edges to the same "does the block contain the right fact" check.
   - Graphiti's `group_id` is set per person for the privacy category, which is the closest it has to `person_scope`. The report says so.
   - The sidecar also records ingestion calls, tokens, dollars and wall-clock per episode. These are half of the comparison.
   - `pip install "graphiti-core[falkordblite]"` goes in a `[eval-graphiti]` optional extra, never the core.

   Acceptance:
   - a dry run with no key lists the matrix and an estimated cost;
   - with the package absent, the run reports `graphiti` skipped with the reason, not failed.

5b. **Cognee as a second sidecar.** *Lock `evals`; parallel to item 5.* `simorgh/evals/memory/cognee_side.py`, built with the same rules as item 5:
   - an import guarded by `ImportError`, and every case reported skipped by name when the package is absent;
   - a hard `--cap-usd`, telemetry forced off (cognee reads `TELEMETRY_DISABLED`);
   - its **local-first** storage only: SQLite for relational data, LanceDB for vectors, and its embedded graph store (check which one the installed version defaults to, and say so in the report), all in a temporary directory, with no server;
   - the LLM through an OpenAI-compatible endpoint at the same Together model.

   It runs the same corpus through `cognee.add` then `cognee.cognify`, and answers each question with `cognee.search` in its graph-completion mode, scored by the same "does the context contain the right fact" check. Cognee has no per-person scope that maps to `person_scope`, so it uses one dataset per person for the privacy category, and the report says so. It records the same ingestion cost and time numbers. `pip install cognee` goes in an `[eval-cognee]` extra, never the core. Systems name: `cognee`.

5c. **Mem0 as a third sidecar.** *Lock `evals`; after 5 and 5b, reusing their shape.* `simorgh/evals/memory/mem0_side.py`, using the `mem0ai` open-source package in local mode:
   - an embedded vector store (its Chroma/FAISS-style local option, in a temporary directory) and SQLite history;
   - no graph store, because Mem0 Graph needs Neo4j, which this stage refuses;
   - the same OpenAI-compatible Together endpoint;
   - a guarded import, telemetry forced off (`MEM0_TELEMETRY=False`), and a hard cap.

   Ingest each episode with `Memory.add(messages, user_id=<person>)`, and answer with `Memory.search(question, user_id=<asker>)`. `user_id` is Mem0's per-person scope, so the privacy category maps cleanly. The sidecar also records **tokens injected per question**, to test Mem0's "80-90% fewer tokens" claim against Sim's own facts block. Systems name: `mem0`.

6. **The comparison.** *No lock; paid, within the creator's cap.* Run all five systems on the suite and write `docs/findings/<date>-entity-graph-vs-graphiti.md`:
   - accuracy per category with intervals;
   - ingestion cost and time per episode;
   - recall latency p50/p95;
   - dependencies added;
   - **tokens of memory injected per turn**, for every system;
   - a recommendation.

   Graphiti moves into Sim (as an optional `[memory] graph = "graphiti"` projection, rebuilt from the ledger, with LLM calls routed through Cognition) only if it beats `native_graph` by a margin outside both intervals in a category the family actually hits, and the cost per episode fits the night budget.

7. **Mem0's update decision in consolidation.** *Lock `memory`; after item 1.*

   **Why.** Today a new fact supersedes an old one only when the normalised `(person_scope, subject, predicate)` key matches *exactly*. So "Reza lives in Shiraz" followed by "Reza moved to Tehran" leaves two live facts. Mem0's core idea fixes this: compare each new fact with the top-k *similar* live facts and decide `ADD | UPDATE | DELETE | NOOP`.

   **What.** In consolidation's fact pass, for each extracted fact:
   - take the k = 5 most similar live facts with the same `person_scope` and the same subject entity (from item 1), by the existing BM25-plus-dense score;
   - ask `cognition.think` (purpose `memory.reconcile`, within the budget) for one decision per candidate, as a typed reply;
   - `UPDATE` and `DELETE` become supersession events (`valid_to`, `superseded_by`). Nothing is deleted.
   - with the floor provider, or when the reply does not parse, fall back to today's exact-key rule, never to a guess.

   **Acceptance.**
   - the Shiraz→Tehran pair leaves one live fact and one superseded;
   - a fact about a *different* Reza is left alone;
   - the memory suite's "temporal now" category does not regress.

8. **Letta's core memory blocks.** *Locks `memory`, `orchestration`, `execution` (a new tool); after item 7.*

   **Why.** Sim already has Letta's other half: the model edits its own memory through Guardian-gated tools (`remember`, `memory_search`, `memory_forget`, `remember_place` in `agents/chat.md`), and there are working, episodic and semantic tiers and compaction. What it lacks is Letta's *core* tier: a few small, labelled blocks that are always in context and that the model itself keeps current, for example "about Soodeh: prefers Farsi, tea not coffee, works Tuesdays".

   **What.**
   - Per-person blocks and one `household` block, each at most `core_block_chars` (default 600), on a new `memory:core` stream. Each edit is an event, with the previous text kept.
   - A tool `memory_core_edit{block, old, new}` (replace-in-block, as Letta's `core_memory_replace` does), reversible, gated by Guardian. A person may only edit their own block or `household`, which Guardian checks against `person_scope`.
   - The asking person's block and `household` are rendered **after** the cacheable prefix, so an edit never invalidates the stage 4 prefix cache.

   **Acceptance.** Run the memory suite with the blocks on and off. Keep them only if the blocks raise accuracy, or keep it level while cutting injected tokens. Block edits are visible in `memory:core` with their source turn.

## What this must never do

- Make anything other than the ledger the store. Entities are a stream; Graphiti's database is a throwaway in a temporary directory.
- Let Graphiti call a model outside a hard cap, send telemetry, or run inside the live Sim.
- Use Graphiti's reference MCP or REST servers. Upstream says they have no authentication and no prompt-injection protection.
- Leak a fact across `person_scope` through a hop. A hop follows only facts the asking person may see; a test pins it.
- Use the creator's family's real conversations as the eval corpus. The corpus is synthetic.

## Definition of done

- [ ] Items 1-3 built with tests; `modtest memory` is green; `memory/CONTRACT.md` is updated (new stream, config keys, reply field).
- [ ] Item 4's suite runs free and is recorded.
- [ ] Item 5's sidecar runs, or reports skipped cleanly.
- [ ] Item 6's findings are written, with a decision.
