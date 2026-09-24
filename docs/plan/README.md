# The plan: from the system that runs to the architecture in the evaluation

This directory is the executable form of Part II of `../reviews/2026-09-18/architecture-evaluation.md`. One file per migration stage, each written so an agent that has never seen the repository can start at item 1: every action item names the files, the code shape, the acceptance test, the rollback, and the module lock it needs.

**How to use it.** Read `../AGENTS.md` once. Pick the lowest stage whose status is not `done`. Take its first unfinished item, lock the modules it names, do it, prove it with `python tools/modtest.py <module>`, commit with the module prefix, update the item's status line in the stage file, release. Items marked *parallel* may be taken by different agents at the same time; items on the same module run in order under one lock. A stage is done when its "Definition of done" checklist is all ticked and its "Measurements after" are recorded in `../findings/`.

**Order matters more than dates.** The stages are sequenced so that the system keeps running after every item, safety closes before capability opens, and every behaviour change lands behind a measurement. Do not start a later stage's behaviour items before the earlier stage's gate exists; file moves (stage 9) come last.

| Stage | File | Title | Depends on | Status |
|---|---|---|---|---|
| 0 | [stage-0-safety-gaps-wires-gate.md](stage-0-safety-gaps-wires-gate.md) | Close the safety gaps, wire what exists, promote the gate | — | in progress (2026-09-22: items 1-29, 31 and 32 done except V7 (28); 30 partly -- kill-and-resume met 2026-09-20, the rest as the file says) |
| 1 | [stage-1-telemetry-out-of-the-decision-log.md](stage-1-telemetry-out-of-the-decision-log.md) | Telemetry out of the decision log | 0 | in progress (items 1-5, 7-9, 11 done; 6 and 10 deferred, with the idle-CPU measurement written down) |
| 2 | [stage-2-native-tool-use.md](stage-2-native-tool-use.md) | Schemas to the model, then native tool use behind a capability flag | 0 | in progress (items 1-8 done; item 9's native switch built and measured, no provider flipped -- a tie is not a win) |
| 3 | [stage-3-streaming.md](stage-3-streaming.md) | Streaming end to end | 2 | in progress (2026-09-20: items 1-5, 7 and 8 done; item 6 waits on 50 recorded turns, item 9 on item 6) |
| 4 | [stage-4-session-stream-context-compaction-evals.md](stage-4-session-stream-context-compaction-evals.md) | Session stream, ContextBuilder, compaction, evals package | 1, 2 | in progress (2026-09-22: items 1-3 and 5-11 done; item 4 in part -- the stable prefix landed, the ContextBuilder move measured and deferred) |
| 5 | [stage-5-memory-tiers.md](stage-5-memory-tiers.md) | Memory tiers | 4 | **done** (2026-09-20: items 1-9; forgetting was already finished and the status line had not caught up) |
| 6 | [stage-6-self-world-people-tiers-initiative.md](stage-6-self-world-people-tiers-initiative.md) | Self and world projections, People, safety tiers, Initiative | 4, 5 | in progress (2026-09-22: items 1, 2, 6, 7 done; 4 mostly and 5 bar the per-person permission matrix; 3 in part -- the home-tool fold went live only 2026-09-22; 8 started -- tier 3 without a human is 0) |
| 7 | [stage-7-long-horizon.md](stage-7-long-horizon.md) | Long horizon: sub-agents, plans, waits, checkpoint critic | 4, 6 | in progress (2026-09-22: items 1-9 done, with deliberate gaps named in the file; 10 open -- the long-task suite not run) |
| 8 | [stage-8-growth-merge-policy-loop.md](stage-8-growth-merge-policy-loop.md) | Growth merge and the policy loop | 4, 6, 7 | in progress (2026-09-22: items 1-4, 6-8 done; 5 done for `rule` policies, off by default (paid) and never yet run live -- no policy has been proposed; 9 deferred; 10 has nothing to count yet) |
| 9 | [stage-9-consolidation-and-breadth.md](stage-9-consolidation-and-breadth.md) | Consolidation and breadth (package moves, HA, Frigate, MCP-first) | all | in progress (items 1 and 9 done; 5's SQLite default reverted, JSONL is the default; 11 started; 2-4, 6-8 not started, 10 has its agent definition only) |
| 10 | [stage-10-companion.md](stage-10-companion.md) | Companion: consent, a per-person wellbeing estimate, check-ins and interest shares, the creator's psychology corpus | 6 | in progress (2026-09-20: items 1-3, 5, 6, 7, 8 done; 4 done bar onboarding, which needs the creator's wording; 9 needs the corpus; 10's shadow mode is built, its two weeks not started) |
| 11 | [stage-11-household-simulator.md](stage-11-household-simulator.md) | The household simulator: personas with voices, an audio scene, a script engine, a scenario pack per stage, companion arcs, benchmarks and latency under one roof, an observer that hands over reproductions | 4, 6, 10 | **done** (2026-09-20: all twelve items; the pack is in the bless and has found five real bugs; the file's status line and definition of done caught up 2026-09-22) |
| 12 | [stage-12-phone-client.md](stage-12-phone-client.md) | The phone client: the console, Sim's own questions, live voice and the house, on a phone | 3, 10 | **designed, not started** (2026-09-24: the spine is that `ui.prompt` has no answer path but the terminal, so Sim's autonomy ends at the desk; `voice/remote.py` landed the transport; QR pairing and the native client both specified, the Developer Program approved) |

**The first month, if nothing else** (evaluation section 12): stage 0 in full, then stage 2 (native tools) and stage 3 (streaming), which are the two changes the family will feel.

**Decisions the creator has made** (2026-09-18/19), so no agent re-asks them:

- Home-automation heavy lifting moves to Home Assistant; camera monitoring may move to an external system (Frigate/go2rtc). The device-direct code stays until the hub is configured; stage 9 removes it.
- Sim's memory and ledger may be wiped for the rebirth; nothing in `~/.simorgh` is precious. Stage 1 and stage 4 say when to do that and how to keep an export.
- The full test suite is the bless gate and a nightly job, not a per-commit cost. Module-scoped runs are the norm (`../testing.md`).
- Several agents will work in parallel under module locks (`../AGENTS.md`).

**Decided by the creator on 2026-09-19:**

- Real-model runs for stage 0's gate are approved with a hard cap of **$25** for the gate as a whole.
- **Gemini** is the second native-tool provider for stage 2: the creator added `GEMINI_API_KEY` to `~/.simorgh/secrets.toml` (2026-09-19). Stage 2 item 4 builds Gemini function declarations first; an Anthropic adapter is optional later.
- **Home Assistant runs on this laptop** (Docker). Frigate/go2rtc follows the same choice unless CPU contention with voice says otherwise; measure before adding Frigate.
- Audio keeping stays on (7 days / 500 MB bound); the pre-rebirth ledger archive was deleted.

**Decisions still open for the creator** (collected from the stage files' "open questions"): listed at the bottom of each stage file; the coordinator should surface them before starting that stage.
