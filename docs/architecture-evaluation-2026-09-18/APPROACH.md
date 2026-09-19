# How this evaluation was done, and how to continue it

*Written by Claude Code (Claude Fable 5.1) on 2026-09-18 for whoever picks this up next: the creator, a later Claude session, or Sim itself.*

This file is the operator's manual for the archive around it. `README.md` indexes every agent's file; this one explains the reasoning behind the design of the investigation, what was checked by hand and how, what the adversarial pass changed, where the method is weak, and exactly how to re-run or extend it against a later commit.

---

## 1. The question and the constraint

The creator asked two things on the evening of 2026-09-18, about `main` at `38a9049`:

1. Review and evaluate the architecture; say where it went wrong and how to improve it.
2. As an AI-agent scientist, say where it went right and how to re-architect Sim toward where agents are going: better reasoning, long tasks, environment and user interaction, module merges and additions, with an honest view of "AGI".

Three reviews already existed in `docs/` (an external Gemini audit, a Claude Code fact-check of it as HTML, and later that evening a third opinion from Opus via Antigravity). The fact-check had shown the earlier review's systematic weakness: reading `docs/EVOLUTION.md` (5,254 lines of history) as a description of the present. So the first design constraint was: **read code, not history; do not re-report what is already known; cite file and line; measure with commands where a claim is about runtime.**

The second constraint was the creator's working style, recorded in memory: hands-free, one person, delegates to coding agents, wants commits pushed. That set the proportionality frame every agent was given: one laptop, one family, one developer, cloud model as brain.

## 2. Timeline (all 2026-09-18, local time)

| When | What |
|---|---|
| ~18:40 | Scouting by hand (section 3). |
| 18:42 | Review workflow launched: 9 readers → 2 skeptics per finding → completeness critic. |
| 19:0x | Panel workflow launched in parallel: 4 architects → 3 judges → 1 synthesis (the creator's second question arrived mid-run). |
| 19:02 | Readers done (93 findings + strengths + measurements); refuters running. Part I drafted from my own verification plus the readers. |
| 19:29 | Panel done (8 agents, 1.37M tokens, 242 tool uses, 27 min). Part II drafted from the synthesis and the judges. |
| 19:35 onward | Usage limit reached; session continued at low priority. Refuters slowed; 7 of 192 plus the critic still pending when the report was committed (`0e75718`). |
| after | Workflow resumed (`resumeFromRunId`), archive exported, this file written. |

## 3. Scouting by hand (what I read before delegating)

The point of scouting was to know the hot path well enough to write reader prompts that ask the right questions, and to have independent ground truth to check the readers against. In order:

1. `docs/architecture.md`, `docs/module-map.md`, `docs/architecture-audit-2026.md`, the text of `docs/architecture-review-2026-09-18.html`, `docs/SOUL.md` head, blueprint and findings listings, `EVOLUTION.md` headings.
2. The import graph: a Python one-liner over every `simorgh/<pkg>` for `from simorgh.X` lines. Result: only `kernel` imports other subsystems; everyone else imports `contracts`, `bus`, `ledger`. This is why the whole re-architecture can be incremental.
3. `kernel/registry.py` `LAYERS`; `~/.simorgh/simorgh.toml` (secrets redacted); `sim.sh`; `simloader.py` gate selection (`CORE_TESTS`, `CORE_IGNORE`).
4. The hot path of one chat turn: `orchestration/session.py::_run` (lines 875 to 1200, read in full), `_propose_and_await`, `_bound_for_model`, `_ACTION_TIMEOUTS`; `orchestration/context.py` (read in full); `cognition/parser.py` outline; `grep tools` across `cognition/providers/*.py` (the `tools=` argument is accepted and never sent); `cognition/assembler.py:60-82`; `cognition/service.py:322-345`.
5. Bus and ledger outlines; `du`/`ls` of `~/.simorgh/ledger` (1.4 GB, 118,215 stream files, kinds counted); the five largest streams.
6. `guardian/rules.py` `DEFAULT_PIPELINE`; `guardian/config.py` `DEFAULT_PROTECTED_SUBJECTS`.
7. `memory/embed.py`, `memory/config.py` (hashing is the default and why), `memory/store.py::retrieve` (full scan by design).
8. Test layout counts; `tests/test_*.py` importing `src/` (39 of 40); `contracts/topics.py` count (175); the envelope fields; sizes of `src/`, `workspace/`, `voice/session.py`; count of dated incident comments (1,118); no `pyproject.toml`/`ruff`/`mypy`.

Everything in section 2 of the report came from this pass. The single most consequential discovery was made here, not by an agent: every provider ignores `tools=`, so the whole tool protocol is text markers, which explains the seven regex families in `session.py`.

## 4. Why the workflows were shaped the way they were

### 4.1 The review workflow (`scripts/simorgh-architecture-review-*.js`)

**Nine readers, one concern each.** A single agent cannot hold 87k lines. Concerns were cut along the seams where a senior architect would expect independent failure modes: substrate (bus, ledger, event-sourcing claim); kernel and lifecycle and config; the agent loop; safety; the cognitive core and growth loop; surfaces; the tool layer; verification and process; and one reader told to measure the whole codebase first (lines, topics with both sides, backends, tools, config keys) before reading anything, so at least one view was quantitative rather than narrative.

**Every reader got the same ground rules** (the `CONTEXT` string in the script): code over docs; the list of already-known findings not to repeat; orientation docs to skim then leave; file:line evidence mandatory; cheap commands allowed, booting the system, running the suite, calling a paid model or modifying a file forbidden; classify each finding as wrong design vs right design undermined vs bug vs over-engineering vs missing; return structured output only. The structured schema (`FINDINGS_SCHEMA`) forced a claim, evidence list, why-it-matters, recommendation and confidence per finding, plus strengths and measurements, so that nothing came back as prose I would have to interpret.

**Two skeptics per finding, different lenses.** Redundant refuters catch fabrication; diverse refuters catch different failure modes. The correctness skeptic asked "is this true of the code today, does the evidence support it, is it already known?" and was told to default to refuted if it could not verify the claim itself. The proportionality skeptic asked "even if true, is this a problem at one-laptop scale, or is the recommendation disproportionate?" Both were allowed cheap commands and forbidden the same things as readers. The pipeline ran per reader (no barrier), so refutation of the first reader's findings began while later readers were still reading.

**A completeness critic** was given the survivors and a list of cross-cutting concerns the readers' boundaries could miss (data ownership, identity, schema versioning, secrets, v1, git as runtime state, disk, external binaries, packaging, stray files) and asked to investigate four to eight of them with the same rigour.

**Effort levels:** readers and critic at `xhigh`, skeptics at `high`. Model inherited from the session (Fable 5.1).

### 4.2 The panel workflow (`scripts/simorgh-rearchitecture-panel-*.js`)

The forward question is a design question, so the shape is a judge panel, not a review: independent attempts from different angles, scored, synthesised. Four lenses were chosen to span the space where agents are being pushed: the modern harness (how the best coding and computer-use agents are built), cognitive architecture (memory, planning, world models, continual learning), production systems (substrate, telemetry, evals, routing, safety tiers), and the embodied household agent (voice, presence, people, devices, proactive behaviour).

Every architect received the same `FACTS` block: the verified state of the code from scouting and the readers, so no proposal could rest on a stale assumption, and the same rules: read to confirm, do not re-audit; be concrete about module, algorithm and measurement; ground "where agents are going" in patterns well established by 2026 and flag uncertainty; be honest about AGI; stay incremental and preserve the Guardian invariant and corrigibility. The proposal schema forced: what Sim got right and why it matters for the future; where it diverges; a module table; merges, additions, deletions; five capability programs with method, measurement and first increment; a staged migration; an AGI paragraph; the proposal's own biggest risk.

Three judges with different mandates (a sceptical maintainer; a researcher judging depth and future alignment; the creator's advocate wanting compounding capability without a rewrite) scored all four on five criteria and were required to resolve every contradiction between proposals with reasoning, verifying any code claim a score depended on. The synthesiser then produced one architecture from the winning spine with the best-scored grafts, stating which side of each disagreement it took.

This workflow used a barrier (`parallel`) between propose and judge because judges genuinely need all proposals at once; the review workflow used a pipeline because it did not.

## 5. What I verified by hand before writing

Agent findings are evidence, not truth. Before a claim went into Part I it was checked against the tree by me. The list, with the command or file:

| Claim | How verified |
|---|---|
| Every provider ignores `tools=` | `grep -n tools simorgh/cognition/providers/*.py`; `grep -n 'tools=None' cognition/service.py` (:358, :419) |
| Transcript flattened to one user message | read `cognition/compaction.py:140-165` and `cognition/service.py:322-345` |
| Clock first in `task_rules` | `grep -n 'Right now it is' orchestration/scaffolds.py` (:638) |
| Auto-approve is the live default, set by the Kernel | read `kernel/service.py:196-210`; `grep guardian ~/.simorgh/simorgh.toml` (no section) |
| `run_shell` on by default | `grep -n 'shell.*bool' execution/config.py` (:193 `shell: bool = True`) |
| Camera routes open without token | read `interface/httpapi.py:915-928` |
| Direct `tool.run()` sites | `grep -rn 'tool\.run(' execution/service.py` (:484, :517, :543, :561) |
| Self-patch feedback topic never fired by the landing path | `grep -rn LEARN_SELF_PATCH_APPLIED simorgh` (one publisher, `learning/pipeline.py:196`); `grep -rn LEARN_PIPELINE_RUN simorgh` (no publisher); `sed -n 790,810p session.py` (no publish) |
| CHAT binds 72 tools | `python3 -c "from simorgh.orchestration import profiles as p; print(len(p.CHAT.tools))"` |
| Supervisor never ticks | `grep -rn 'poll_once\|health_every_s' simorgh` (no caller) |
| 85% of actions are `ring_live` | `grep -l '"ring_live"' ~/.simorgh/ledger/streams/action%3A* \| wc -l` → 22,849 of 26,737 |
| Ledger shape | `du -sh`, `ls \| wc -l`, kind counts, five largest streams |
| Loader gate is a curated core set | read `simloader.py:529-575` |

Where a skeptic corrected a reader (section 6), I re-read the cited lines before accepting the correction.

## 6. What the adversarial pass changed

Of the 96 findings (93 from eight readers plus 10 from the proportionality reader, minus overlaps), none was refuted outright. The skeptics:

- **Lowered severity on about 40**, mostly because a cost turned out to be disk, audit noise or design debt rather than latency or safety: an fsync'd JSONL append measured 0.031 ms; the 5 ms wake-all ticker is under 1% of the machine; the lease protocol is 0.4% of the ledger.
- **Sharpened claims on about 30.** The ones that changed the report: flattening happens in the compactor (`compaction.py:153`), not only the assembler; the clock is first in the `task_rules` block, with four small stable blocks before it; the 0.25 s recall budget does not force the hashing embedder (a warm MiniLM is 47 ms), the cold start and absent persisted vectors do; `full_suite_ran`'s 56 of 62 failures are mostly the check working as designed; the direct `tool.run()` sites are six and the TV one is off by default; the broadcast drop-on-error is the documented bus contract.
- **Re-framed two as the project's own "unconnected wire" shape** rather than wrong design (the open growth loop; Guardian trusting the proposer's label). That frame is right and it points at the fix: contract checks that fail the build, not more discipline.

Each skeptic's file in `review/refutations/<concern>/` has the verdict, the reasoning, the corrected claim and the evidence it read.

## 7. Where this method is weak

- **Nothing was run.** Runtime facts come from the ledger, the config and cheap imports. No agent booted Sim, ran the suite or called a paid model. Latency numbers are the project's own from the same day.
- **The ledger window is nine days** and dominated by dashboard and benchmark traffic. "Never called" means "not in that window".
- **Readers can share blind spots** because they shared a `CONTEXT` block. The known-findings list told them what not to repeat; it may also have anchored them. The completeness critic and the quantitative reader were the mitigation.
- **Skeptics were the same model as readers.** They were prompted adversarially and defaulted to refuted, but a shared model can share a misreading. Hand verification of the headline claims was the mitigation; it does not cover all 96.
- **The panel's view of the field is pattern-level.** Architects were told to cite a system or paper only when sure it exists and otherwise describe the pattern. Treat any specific external reference in `panel/` as something to check, not as established.
- **Line numbers drift.** They are correct for `38a9049`. Re-derive them before quoting from a later commit.
- **The migration weeks are order-of-magnitude** for one developer working through coding agents. The order is the recommendation; the calendar is not.

## 8. How to re-run, audit or continue this

### 8.1 Rebuild the archive from the session transcripts

```
python3 docs/architecture-evaluation-2026-09-18/tools/export_deepdive.py
```

It reads the two workflow directories under the Claude Code session named in `raw/manifest.json`, writes one Markdown file per agent (task, tool trail, structured reply) and refreshes `README.md`. It is idempotent and picks up agents that finished since the last run. The full per-agent JSONL transcripts (about 76 MB) are not committed; the manifest gives their filenames if the session directory still exists.

### 8.2 Resume the review workflow if agents are still pending

```
Workflow({scriptPath: '<session>/workflows/scripts/simorgh-architecture-review-wf_07270914-dd5.js',
          resumeFromRunId: 'wf_07270914-dd5'})
```

Completed agents return cached results; only unfinished ones run. Then re-run the export and append the critic's findings as section 13.11 of the report.

### 8.3 Run the same review against a later commit

Copy `scripts/simorgh-architecture-review-*.js`, update the `CONTEXT` block's known-findings list with what this report established (so the next round does not re-report it), update the commit hash, and launch it as a new workflow. The reader prompts are reusable as they stand; their `Questions:` lists are the places to add what the last round left open. Expect roughly 200 agents and about an hour at normal priority.

To reuse the panel, update the `FACTS` block first: every architect reasons from it, and a stale fact there becomes a stale proposal.

### 8.4 Audit a single finding

Each catalogue row in the report (section 13) names the concern and the finding title. Open `review/readers/<concern>.md` for the reader's evidence and `review/refutations/<concern>/<title>.correctness.md` and `.proportionality.md` for the two skeptics. The tool trail in each file lists every file read and command run, with the first 160 characters of each result, so a claim can be re-checked without re-reading the whole subsystem.

### 8.5 Continue the analysis into the code

The open threads, in the order the report recommends:

1. **Stage 0 of the migration** (report section 12): each item is small and independently verifiable. Before changing anything, build the gate it names (trial suite + benchmark + the 30-turn recall scenario + kill-and-resume, three repeats) so every change has a number.
2. **The critic's addendum** (section 13.11) if it was not yet appended.
3. **Findings marked "measure first"** in section 13: tool-calling quality of the cheap Together model on BFCL before any native-tool flip; prompt-cache hit rate before and after prefix reordering; the 200-case household request set.
4. **Contract checks that fail the build**: a test that every subscribed topic has a publisher and every published topic a subscriber (allow-list the externally triggered ones); a test forbidding `getattr(config, ...)`; a manifest-vs-code test for `consumes`/`produces`. These retire the unconnected-wire class rather than individual instances.
5. **A findings entry** in `docs/findings/` after each stage, per the project's convention, and freezing this evaluation once its items are issues.

### 8.6 Prompt patterns that worked, for reuse

- "Read the CODE, not the docs; EVOLUTION.md is history" removed the failure mode that broke the earlier external review.
- Listing already-known findings and forbidding their repetition pushed readers to new material; nine readers produced 96 findings with almost no overlap with the three prior reviews.
- Requiring `file:line` plus a quoted command made every finding checkable and made the skeptics' job mechanical.
- "Default to refuted if you cannot verify it yourself" produced skeptics that actually read the code; the proportionality lens produced the severity corrections that made the report fair.
- Giving architects a verified `FACTS` block and a schema with "first increment" and "how to measure" per capability produced proposals that were concrete enough to judge and to schedule.
- Forbidding booting, the suite, paid calls and file writes kept 209 agents from touching the live system; two agents still created stray files at the repo root with a mis-redirected `echo`, which were removed. Add "do not use shell redirection into the repository" next time.
