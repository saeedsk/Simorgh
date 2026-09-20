# Simorgh documentation

Everything an agent or a person needs to work on Sim, and nothing that describes a system other than the one that runs. The old blueprint, evolution log, plans and knowledge base were removed on 2026-09-19 because they described intent and history and had started to mislead reviewers; they remain in git history at tag `pre-cleanup-2026-09-18`.

## Read in this order
- [adding-capability.md](adding-capability.md) — how a new capability arrives: an MCP server, not a tool class.


1. **[ARCHITECTURE.md](ARCHITECTURE.md)**: what runs today, from the code. Layers, the three enforced invariants, a turn end to end, one paragraph per module, how to run it, what is deliberately not built.
2. **[AGENTS.md](AGENTS.md)**: how several agents change Sim at once. Module locks, the edit loop, changing a contract, what not to do.
3. **[testing.md](testing.md)**: the test tiers (contract, module, core, full, live), the markers, what makes a test worth keeping, the speed/confidence trade-off, the measured baseline.
4. **`simorgh/<module>/CONTRACT.md`**: one per package. What it consumes and produces, its streams, config, public surface, invariants, the tests that pin them, its known issues and its planned changes. Read the one for the module you are about to touch.
5. **[plan/README.md](plan/README.md)** and `plan/stage-N-*.md`: the migration, stage by stage, with commit-sized action items, acceptance tests and rollbacks.
6. **[reviews/2026-09-18/](reviews/2026-09-18/)**: the evaluation the plan comes from, its evidence, and the two other reviews from the same day.

## Everything else

| Path | What |
|---|---|
| [SOUL.md](SOUL.md) | Sim's constitution: identity, directives, constraints. Read by Guardian (charter), Persona and the World Model at boot. Amended only by the creator, by hand. |
| [findings/](findings/) | Dated records of what was measured, what broke, what was fixed and what was decided. Add one after each substantial round; the plan's "Measurements after" go here. |
| [modules/locks.toml](modules/locks.toml) | The live module locks (see AGENTS.md). |
| [sourcebook.md](sourcebook.md) | Keyless public data endpoints. Read by the research scaffold at runtime (`orchestration/scaffolds.py`); keep it current. |
| [brand/](brand/) | Brand tokens for the dashboard and logo. |
| `../README.md` | How to run Sim and set up voice. |
| `../CLAUDE.md` | The seven rules an agent follows in this repository. |
| `../tools/` | `modtest.py` (test tiers), `modlock.py` (locks), `trial.py` / `trial_suite.py` (one watched real task in a repo copy), `observer_kit.py` (staged sandboxes for observer waves; its own notes are in its docstring), `bench_instance.py`, `voice_setup.py`. |

## reviews/2026-09-18

| File | What |
|---|---|
| `architecture-evaluation.md` | The full evaluation and re-architecture proposal (Claude Code, Fable 5.1). Section 13 is the findings catalogue with ids the contracts and plans cite. |
| `architecture-evaluation/` | The deep-dive archive behind it: every agent's task, tool trail and reply; `APPROACH.md` explains the method and how to re-run it. |
| `tests/` | Per-directory value analysis of the test suite: contract tier, merge and delete candidates, gaps. Input to the stage-0 test consolidation. |
| `gemini-audit.md` | The external second-opinion audit, as revised after fact-checking. |
| `claude-code-fact-check.html` | The fact-check of the original external review. |
| `third-opinion-opus.md` | An independent third opinion (Opus via Antigravity). |

## Conventions

- A document describes the present or a decision. History belongs in git and in `findings/`.
- A design lives in the `CONTRACT.md` of the module that owns it and in the plan stage that builds it, not in a separate design document.
- Line references are correct for the commit named at the top of the document; re-derive them before quoting from a later one.
- When a document and the code disagree, the code is right and the document gets fixed in the same commit as the next change to that module.
