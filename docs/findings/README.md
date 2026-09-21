# Findings

Dated records of what was measured, what broke, what was fixed and what was decided, so a later session can start from evidence instead of rediscovering it. Each file is self-contained and cites its commits.

Design documents live in `docs/plans/`; benchmark analyses in `docs/benchmark-analysis-*.md`.

| Date | File | Covers |
|---|---|---|
| 2026-09-20 | [2026-09-20-home-assistant-os-in-utm.md](2026-09-20-home-assistant-os-in-utm.md) | The move to HA OS in a UTM VM: why bridging over Wi-Fi is not the sure thing the Docker note called it, the evidence either way, the install and migration steps, the disk cost, and `tools/haos.py` |
| 2026-09-20 | [2026-09-20-home-assistant-on-the-mac.md](2026-09-20-home-assistant-on-the-mac.md) | How to run Home Assistant on this MacBook: container vs venv vs VM, why the container wins here, where the URL and token go so Sim's `home_*` tools see them, and `tools/ha.py` |
| 2026-09-19 | [2026-09-19-contract-writing.md](2026-09-19-contract-writing.md) | What writing the 19 CONTRACT.md files found: ~45 uncatalogued problems, 16 fixed the same night, the rest indexed by risk |
| 2026-09-19 | [2026-09-19-stage-0.md](2026-09-19-stage-0.md) | The cleanup and the rebirth: v1 and the old docs removed, test tiers and module locks, stage 0 items 1-16 with before/after numbers (suite 16:40 -> 1:34) |
| 2026-09-16 | [2026-09-16-voice-cameras-task-quality.md](2026-09-16-voice-cameras-task-quality.md) | A write-only console and the answer it invented, camera baselines learnt from one motion frame, the speech lock, tone tags in any script, recognition flicker, invented task subjects defeating dedupe, two dead wires in Planning, overheard speech built twice and reachable neither time |
| 2026-09-14 | [2026-09-14-benchmark-analysis.md](2026-09-14-benchmark-analysis.md) | Benchmark analysis |
| 2026-09-14/15 | [2026-09-15-benchmarks-long-runs-models-skills.md](2026-09-15-benchmarks-long-runs-models-skills.md) | Benchmark waves and their harness bugs, comparison arms, long-run changes A-H, model tiers and Together, Ollama fallback, Agent Skills trust, parallel lookups, web search spacing, voice/TV fixes |
