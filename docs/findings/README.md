# Findings

Dated records of what was measured, what broke, what was fixed and what was decided, so a later session can start from evidence instead of rediscovering it. Each file is self-contained and cites its commits.

What changes next, and in what order, lives in `docs/plan/`. The 2026-09-14 benchmark analysis is `2026-09-14-benchmark-analysis.md` below; the separate `docs/benchmark-analysis-*.md` files this index once pointed to were removed on 2026-09-18 (`bdf4a69`) and live in version history.

| Date | File | Covers |
|---|---|---|
| 2026-09-22 | [2026-09-22-model-written-tests-confined.md](2026-09-22-model-written-tests-confined.md) | Stage 0 item 32: the three pytest runs over a model's own tests confined by `sandbox-exec` (socket and `$HOME` write fail with EPERM; macOS only), and a pause that now holds a verification |
| 2026-09-22 | [2026-09-22-context-assembly-is-not-the-cost.md](2026-09-22-context-assembly-is-not-the-cost.md) | Stage 4 item 4 measured and deferred (about 5 ms of bus round trips per think against a 4,460 ms provider call, over 1,548 thinks; `world.env.query` about 37,000 a day, poller unknown); item 8, retries judged on the whole task stream |
| 2026-09-22 | [2026-09-22-people-store-and-the-house-fold.md](2026-09-22-people-store-and-the-house-fold.md) | Stage 6: the house fold that never ran live (`metadata` vs `metadata_ref`) until 2026-09-22; roles from the People store; linked handles admitted; preferences per person; item 1 closed; item 8 unchanged |
| 2026-09-22 | [2026-09-22-stage-7-fork-acceptance-container.md](2026-09-22-stage-7-fork-acceptance-container.md) | Stage 7 items 1, 4, 8: `isolation: fork`, acceptance criteria as required checklist items, `run_container` killed on cancel; the long-task suite (item 10) not yet run |
| 2026-09-22 | [2026-09-22-stage-8-measure-adopt-land.md](2026-09-22-stage-8-measure-adopt-land.md) | Stage 8 item 5: measure at night, adopt on no regression, Guardian asks before `rules/`, the agent reads it; item 10: no `growth:policies` stream exists yet on the live ledger |
| 2026-09-22 | [2026-09-22-growth-merge-leftovers.md](2026-09-22-growth-merge-leftovers.md) | The merge sweep: trials and benchmarks ran with autonomy ON from the 2026-09-20 merge to `efa116a`; eleven tests likewise; config typos in the live sections went unreported |
| 2026-09-22 | [2026-09-22-gemini-ten-second-deadline.md](2026-09-22-gemini-ten-second-deadline.md) | Gemini refuses a server deadline under 10 s; the 8 s review slice rested it for the day (2 answered, then the floor; 5/5 after); `--providers` pins a benchmark to the provider it names |
| 2026-09-21 | [2026-09-21-sim-on-the-benchmark.md](2026-09-21-sim-on-the-benchmark.md) | Four trials asking Sim to fix a benchmark bug: none landed, four different failure paths, three of them closed |
| 2026-09-20 | [2026-09-20-stage-1-after-numbers.md](2026-09-20-stage-1-after-numbers.md) | Stage 1's after-numbers on the live data dir, with the two rows that are not what they look like |
| 2026-09-20 | [2026-09-20-the-action-stream-flood.md](2026-09-20-the-action-stream-flood.md) | 962 gated actions in the busiest hour, 640 of them a keep-alive, against a target of under 10 `action:` streams |
| 2026-09-20 | [2026-09-20-stage-6-safety-numbers.md](2026-09-20-stage-6-safety-numbers.md) | Tier-3 actions without a human: 0 of 1,823 decisions; unprompted utterances and presence accuracy not yet countable |
| 2026-09-20 | [2026-09-20-stage-8-growth-merge.md](2026-09-20-stage-8-growth-merge.md) | The growth merge (18 to 16 subsystems), what an estimate rests on, clustering, Thompson exploration, the night |
| 2026-09-20 | [2026-09-20-house-simulator.md](2026-09-20-house-simulator.md) | Stage 11 items 1-3: identification and WER by distance and noise; a talking television transcribed instead of the person |
| 2026-09-20 | [2026-09-20-house-pack.md](2026-09-20-house-pack.md) | Stage 11 items 4-12: the scenario pack turned on a whole Sim, the falsifiability finding, arcs, benchmarks, latency |
| 2026-09-20 | [2026-09-20-house.md](2026-09-20-house.md) | An observer run of the house pack (10/10 expectations) |
| 2026-09-20 | [2026-09-20-what-a-scenario-was-paying-for.md](2026-09-20-what-a-scenario-was-paying-for.md) | Stage 11 item 8's `--profile` and the first thing it found |
| 2026-09-20 | [2026-09-20-the-television-answered-as-a-person.md](2026-09-20-the-television-answered-as-a-person.md) | A documentary's narration answered as the creator, live |
| 2026-09-20 | [2026-09-20-kill-and-resume.md](2026-09-20-kill-and-resume.md) | Stage 0 item 30's kill-and-resume drill with a real model: nothing that had succeeded ran again |
| 2026-09-20 | [2026-09-20-native-versus-markers.md](2026-09-20-native-versus-markers.md) | Native tool calls against markers on the same twelve cases; the claimed 15x win that the repeat did not show |
| 2026-09-20 | [2026-09-20-gaia-l1-second-run.md](2026-09-20-gaia-l1-second-run.md) | gaia-l1 twice in one evening, same five cases |
| 2026-09-20 | [2026-09-20-the-disk.md](2026-09-20-the-disk.md) | The disk under 5% free and two boot tests going red |
| 2026-09-20 | [2026-09-20-home-assistant-os-in-utm.md](2026-09-20-home-assistant-os-in-utm.md) | The move to HA OS in a UTM VM: why bridging over Wi-Fi is not the sure thing the Docker note called it, the evidence either way, the install and migration steps, the disk cost, and `tools/haos.py` |
| 2026-09-20 | [2026-09-20-home-assistant-on-the-mac.md](2026-09-20-home-assistant-on-the-mac.md) | How to run Home Assistant on this MacBook: container vs venv vs VM, why the container wins here, where the URL and token go so Sim's `home_*` tools see them, and `tools/ha.py` |
| 2026-09-19 | [2026-09-19-stage-4-live-fixes-and-stage-5-recall.md](2026-09-19-stage-4-live-fixes-and-stage-5-recall.md) | The rest of stage 4 (stable prefix cache hit, compaction, agents as files, the Stop hook), a live voice session's bugs, the first stage 5 items |
| 2026-09-19 | [2026-09-19-stage-0-gate.md](2026-09-19-stage-0-gate.md) | The stage-0 gate with a real model, and stage 1 in one night |
| 2026-09-19 | [2026-09-19-contract-writing.md](2026-09-19-contract-writing.md) | What writing the 19 CONTRACT.md files found: ~45 uncatalogued problems, 16 fixed the same night, the rest indexed by risk |
| 2026-09-19 | [2026-09-19-stage-0.md](2026-09-19-stage-0.md) | The cleanup and the rebirth: v1 and the old docs removed, test tiers and module locks, stage 0 items 1-16 with before/after numbers (suite 16:40 -> 1:34) |
| 2026-09-17 | [2026-09-17-words-as-they-are-said.md](2026-09-17-words-as-they-are-said.md) | Re-architecting interactive voice around words as they are recognised |
| 2026-09-17 | [2026-09-17-the-threshold-that-was-not-the-problem.md](2026-09-17-the-threshold-that-was-not-the-problem.md) | The voice-match threshold question: keep 0.5, and what was actually wrong |
| 2026-09-16 | [2026-09-16-channels-and-the-expressive-engine.md](2026-09-16-channels-and-the-expressive-engine.md) | External channels, and why MisoTTS never made a sound |
| 2026-09-16 | [2026-09-16-voice-cameras-task-quality.md](2026-09-16-voice-cameras-task-quality.md) | A write-only console and the answer it invented, camera baselines learnt from one motion frame, the speech lock, tone tags in any script, recognition flicker, invented task subjects defeating dedupe, two dead wires in Planning, overheard speech built twice and reachable neither time |
| 2026-09-14/15 | [2026-09-15-benchmarks-long-runs-models-skills.md](2026-09-15-benchmarks-long-runs-models-skills.md) | Benchmark waves and their harness bugs, comparison arms, long-run changes A-H, model tiers and Together, Ollama fallback, Agent Skills trust, parallel lookups, web search spacing, voice/TV fixes |
| 2026-09-14 | [2026-09-14-benchmark-analysis.md](2026-09-14-benchmark-analysis.md) | Benchmark analysis |

**Pending on 2026-09-22, not yet written up:** the trial rounds under way that day, the BFCL comparison on Gemini (stage 2 item 9), and a GAIA run.
