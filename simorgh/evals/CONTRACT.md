# evals -- contract

One-line status: harness (not a Subsystem) · 5 files · 2 test files · lock: `evals` in docs/modules/locks.toml

## Purpose

Evals answers one question -- *did this change make Sim better?* -- in
one format. Three harnesses used to answer it in three: `simorgh/benchmark`
(GAIA, BFCL, SWE-bench against a model, with its own history store),
`tools/trial_suite.py` (seven real tasks against the whole running system,
in a repo copy, with real money) and the household recall scenario (one
scripted conversation, probed for what the model actually saw). None of
their numbers could be compared with each other, or with the same number
last week.

This package is the single entry point over all three. A `Case` is one
thing to try, an `Outcome` is what happened on one attempt, and a
`Report` is a suite's outcomes over N repeats **with a 95% bootstrap
interval**. The interval is the point: the trial suite has scored 5, 6
and 7 out of 7 on the same commit, so a bless comparing single numbers is
comparing noise. `simloader.py bless` runs the free suite on every
commit and records what it got.

It is a harness, not a Subsystem: it has no `Service`, publishes nothing
on the Bus, and is not registered by the Kernel. It composes the system
from outside -- boots it, types at the Interface, reads the bus -- which
is why `evals` is in the boundary checker's `COMPOSITION_ROOTS` beside
`kernel`. Nothing in `simorgh/` imports it.

## Files

| File | For |
|---|---|
| `simorgh/evals/__init__.py` | re-exports `Case`, `Outcome`, `Report`, `run`, `table`, `record`, `last`, `find` |
| `simorgh/evals/api.py` | the three shapes, `bootstrap_ci`, `outcomes_from` |
| `simorgh/evals/suites.py` | the suite registry, and each suite's adapter |
| `simorgh/evals/runner.py` | repeats (one child process each), the table, the JSONL record |
| `simorgh/evals/scenario.py` | the household script and its probes (was `tools/recall_scenario.py`) |
| `simorgh/evals/__main__.py` | `python -m simorgh.evals run \| list \| scenario` |
| `simorgh/evals/house/` | the household simulator (stage 11): `sandbox.py`, `director.py`, `record.py`, `people.py`, `scene.py`, `script.py`, `hearing.py`, `timing.py`, `voicecache.py`, `run.py`, `scenarios/` |

## Suites

| Name | What it runs | Model | Cost |
|---|---|---|---|
| `household` | the scripted conversation (19 turns), 3 probes on the context the model would have seen | none (floor) | free, ~8 s |
| `trials` | the seven real tasks in a copy of the repo (`tools/trial_suite.py`) | real | dollars, minutes |
| `tooluse` | BFCL cases from `simorgh/benchmark` | real | dollars |
| `research` | GAIA cases from `simorgh/benchmark` | real | dollars |
| `code` | the SWE-bench Verified slice | real | dollars, Docker |

A paid suite refuses to start without `--paid`. `household` is the one
the bless runs: no model, no network, no money, and it measures the
failure that reached the creator most often -- whether what the family
said reaches the prompt.

The three benchmark-backed suites list their cases and report them as
`skipped` today: the scoring lives in `simorgh/benchmark`'s own runner
and is reached through `python -m simorgh.benchmark run`. What this
package adds to them so far is the case list and the shape.

## The household simulator (`house/`, stage 11)

A whole Sim, booted where it can do no harm, driven by a scenario. `Sandbox` boots the real Kernel -- Guardian, the bus, the ledger, memory, the speaker book, all real -- in a temporary data directory with the floor provider, `FakeHomeAssistant`, and the fake voice engines from `voice/fakes.py`. `Director` is the whole surface a scenario touches: `say(person, text)`, `type(text)`, `device(...)`, `advance(...)`, `restart()`, and `settle()`. `Record` is what it leaves behind: every bus message in order, every printed line, every piece the synthesiser was asked for, with a monotonic time on each, so latency comes out of the record rather than out of an instrument.

`say` drives the voice pipeline's own `ask`, which claims the session as a voice session -- that is what makes the reply Sim's to *say* rather than merely to write. Only the microphone and recogniser are skipped; the audio scene (item 3) puts them back, and a scenario written today keeps working then, because what it asserts is what Sim did rather than how the sound arrived.

The observer registers on the bus **backend**, not through a client. A client is policed and `action.proposed` is Guardian's alone -- which is the policy working -- but a sandbox that cannot watch the approval path cannot test the approval path. It only ever reads.

It never touches `~/.simorgh`, never reaches a device, keeps its **speaker book inside its own data directory** (it read and wrote the live one until 2026-09-20), and defaults to a provider that costs nothing.

**Running it**: `python -m simorgh.evals house` plays the whole pack, `--fast` the five the bless runs, `--one <id>` a single scenario in this process. Each scenario gets its own child process, because booting the whole system more than three times in one interpreter segfaults on the torch models. The pack is about five minutes, the bless subset about three; nearly all of it is Kernel boots, which is why the subset is five scenarios chosen for what they would CATCH rather than for coverage.

A scenario marked `needs_model=True` is **skipped** unless `SIMORGH_HOUSE_PAID` is set, and says why. For a voice Sim has placed, "were these words for me?" is the model's judgement, not a rule -- so the floor provider, which answers everything, cannot judge those at all.

**The people** (`house/people.py`) are five personas -- an owner, an adult, two children and a guest, so every gate has somebody to exercise it -- and deliberately not the creator's family: cloning a household member's voice needs that person to say so. Each has a Kokoro voice, and `enrol()` puts three synthesised sentences through the same sherpa CAM++ embedder the house uses into the sandbox's own book, so identification in a scenario is tested with the numbers a real voice gets.

**The scene** (`house/scene.py`) is the room between a person and the microphone: distance as attenuation plus an early reflection, a seeded room bed at a named SNR, a television or music bed that is itself *speech*, Sim's own last utterance folded back at the gain a laptop's speaker really has, and overlapping talkers. Plain arithmetic on 16-bit PCM, because the point is a repeatable room rather than a convincing one.

What it measured is in `docs/findings/2026-09-20-house-simulator.md`. The short version: identification degrades gracefully with distance and noise (0.90 near, 0.71-0.81 at 3 m / 10 dB, 0.57-0.68 at 6 m in a party), the hiss bed does not trouble whisper at all (WER 0.00 even at -6 dB), and a talking television at 0.6 gain makes the recogniser return a clean transcript of *the television* instead of the person. Speech-on-speech is the regime that matters; louder hiss is not.

**A scenario** (`house/script.py`) is beats and expectations. A beat says who spoke, from where, over what; an expectation says what a person in the room would have accepted -- `answered()`, `quiet()`, `did_not_call("home_call")`, `asked_a_person()`, `first_audio_under(2.5)`, `remembered("March 6")` -- rather than naming the string the model must produce, because a test that pins the words fails when the model improves. Each expectation yields one `Outcome`, so a run reports per expectation with the beat that failed.

A beat can reach Sim two ways, and the difference matters. `say()` drives `Pipeline.ask`, which asks Sim directly -- right for "what did it answer", useless for "what did it ignore". `into_the_room()` synthesises the persona's voice, puts it through the scene and hands it to the microphone, so the **listening loop** decides: is this speech, whose voice is it, was it addressed to me, was it my own echo. Every live failure the pack reproduces was decided there. The words are scripted (`hearing.ScriptedRecogniser`) while the audio is real, because whether Sim stayed out of a conversation should not depend on whether whisper heard every syllable -- word error is measured on its own.

**Where a turn's seconds go** (`house/timing.py`, `--timing`): `hear` (somebody started speaking → Sim understood them: VAD, the recogniser, the speaker book), `think`, `first_audio`, `reply`. Measured from the moment a **person** spoke, not from the percept -- a percept appears only once the listening path is done, so measuring from it hides the part with stage 3's two-second budget in it. Every number is a difference between two things already recorded, so no instrument is added to Sim and the table cannot drift from what happened. The budgets are stage 3's own. On the floor provider `think` is ~0.08 s and the real figure is `hear`: 2.84 s for a spoken beat, over its budget.

**The terminal grammar** (`script.tui_is_sane`) is an expectation every scenario can carry, and it is not a style check: each rule is something that reached the creator's screen and told him nothing or told him something untrue -- a stack trace, a library's progress bar, a raw payload, an empty answer line, the same line twice in a row, a line wider than a terminal, and a task rendered `? · ? · (no description)`. It reads the line with its colour codes stripped, because every real line carries them.

**The pack** (`house/scenarios/`) starts with `live.py`: the five evenings that actually went wrong on 2026-09-19 and 2026-09-20, each carrying the commit that broke it. A harness anchored in bugs that happened is worth more than one anchored in bugs somebody imagined.

Which voices those are is a **measurement**, kept in `tools/house_voices.py`. The first hand-picked set had `af_heart` and `af_bella` at 0.77 against each other -- two personas the embedder could not tell apart, which would have read as Sim misidentifying people in every scenario. The measured set (`af_river`, `bm_lewis`, `bf_isabella`, `am_puck`, `af_nicole`) has a worst pair of 0.24, and each persona identifies itself at 0.89-0.95 with a profile coherence of 0.86-0.92.

## Public Python surface

- `simorgh.evals.run(suite, *, repeats=1, isolate=None) -> Report`
- `simorgh.evals.table(report) -> str`, `record(report, data_dir=...) -> Path`, `last(data_dir, suite="") -> dict | None`
- `simorgh.evals.api`: `Case`, `Outcome`, `Report`, `bootstrap_ci`, `outcomes_from`, `PASSED`/`FAILED`/`SKIPPED`
- `simorgh.evals.suites`: `SUITES`, `PAID`, `find`
- `simorgh.evals.scenario`: `run`, `SCRIPT`, `main` -- `tools/recall_scenario.py` is a shim onto it
- Read by `simloader.py::run_evals` (the bless gate) and `tools/recall_scenario.py`. Nothing else imports it.

## Command line

```
python -m simorgh.evals run household --repeats 3        # the acceptance case
python -m simorgh.evals run household --json --record ~/.simorgh/loader
python -m simorgh.evals run trials --paid                # real money
python -m simorgh.evals list
python -m simorgh.evals scenario --verbose               # per-probe context
```

Exit code 0 only when every counted case passed.

## Record

`<data_dir>/evals.jsonl`, appended, one report per line:
`{at, suite, passed, total, rate, ci95, skipped, repeats, seconds, cost_usd, by_level, failures, cases}`.
Appended and never rewritten, for the reason the Ledger is: the
interesting question about an eval is what it did last week.
`simloader` writes it under its notes directory, beside `decisions.jsonl`.

## Invariants

- A `skipped` case is never in the denominator, and a report says how
  many were skipped. A case whose reply came from the floor provider, a
  trial that failed for the harness's own reasons (`_OUR_FAULT`: a
  timeout, an oversized context, no provider), and a suite that could
  not load its dataset are all skipped, not failed: a provider outage is
  not a regression in Sim.
- A suite that could not start reports one skipped case saying why. It
  never reports 0/0 as a pass or an empty suite as a zero.
- Each repeat runs in its own child process (`runner._one_in_a_child`).
  Booting the whole system twice in one interpreter segfaults on the
  torch models, and a repeat is supposed to be a fresh start anyway.
- A child that dies becomes one skipped case carrying its stderr tail --
  never a silently smaller denominator.
- `bootstrap_ci` is seeded (`seed=20260919`), so the same outcomes print
  the same interval; a single value reports (0, 1) rather than inventing
  a tight interval around itself.
- A paid suite does not run without `--paid`.
- `simloader`'s bless refuses when `household` scores **below the last
  recorded run**. A failure with no earlier run to compare against warns
  and records the baseline: refusing every bless until somebody
  hand-edits a file is how a gate gets switched off.

## Contract tests

- `tests/simorgh/evals/test_evals.py` -- the arithmetic and the wiring: skipped cases out of the denominator, a suite that could not start, per-level reporting, a stable interval, the JSON round trip, the record, the table, a dead repeat.
- `tests/simorgh/evals/test_scenario.py` -- the household scenario against the real booted system: 3 of 3 probes (integration mark).

## Known issues

- The physical merge item 9 asks for is half done: `tools/recall_scenario.py`
  moved in (and is a shim), but `tools/trial_suite.py`, `tools/observer_kit.py`
  and `tools/bench_instance.py` are still where they were and are imported as
  an optional adapter. That harness is how every real bug in this system has
  been found; moving 500 lines of it needs a paid run to re-verify, so it is
  deliberately deferred rather than done blind.
- `tooluse`, `research` and `code` list cases but do not score them here;
  scoring stays in `simorgh/benchmark`'s runner.
- Not built from item 9's list: the conversation, long-task (60 turns,
  kill -9 and resume) and voice (50 recorded turns) suites, the replay
  tier with a `FixtureProvider` keyed by session turn seq and tool_use
  id, and the post-handoff watch counting SLO breaches.

## Working on this module

Lock `evals` (and `simloader` if you touch the bless gate), edit
`simorgh/evals/`, `tests/simorgh/evals/` and this file. Run
`python tools/modtest.py evals`; `python -m simorgh.evals run household`
is the live check and takes about eight seconds. Commit subject
`evals: <what changed>`.
