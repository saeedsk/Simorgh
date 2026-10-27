# Stage 14 -- Tool-chain evals and guardrail ablation

Status: **in progress** (2026-10-27: plan written; items 1-4 being built; item 5 needs the creator's spend cap) · Depends on: stage 4 (`simorgh/evals/`), stage 11 (the household simulator) · Modules touched: evals (owner), orchestration, cognition; `docs/`

## Outcome

One command answers two questions with numbers and a confidence interval:

1. **How reliably does Sim finish small household tool chains, per model?** For example: check a sensor, then act on what it said; pick the right tool out of the 72 the chat agent is offered; carry an argument from one tool's result into the next call; recover when a tool fails; know when no tool is needed.
2. **Which of Sim's own guardrails earn their cost?** The same scenarios run with each guardrail switched off one at a time, and with all of them off (`bare`). The result is a matrix like forge's (github.com/antoinezambelli/forge, `docs/EVAL_GUIDE.md` "Ablation Presets"): Haiku went from 46% bare to 94% with forge's guardrails, and Sonnet from 85% to 98%. Today nobody knows whether Sim's scaffold text, Verification or revision loop help, hurt or do nothing for a given model.

```
python -m simorgh.evals ablate --suite toolchain --presets sim,bare,no_scaffold,no_verify,no_revisions,no_recovery,no_rescue \
    --models together:<model>,gemini:<model> --repeats 5 --paid --cap-usd 20
```

prints one row per (model, preset), with the success rate, its 95% bootstrap interval, the mean steps and the dollars it cost. It also appends to `.simorgh_evals/ablation.jsonl`.

## Why

- BFCL and GAIA measure the *model*. They cannot tell whether Sim's loop adds anything, because the benchmark runner bypasses most of what the loop does differently in household use.
- The household pack (stage 11) measures safety gates and memory with the floor provider. It never asks a real model to choose and chain tools.
- Every guardrail in Sim was added after a live failure, and none has ever been measured switched off. A guardrail that does nothing still costs tokens on every turn. One that hurts a strong model, for example a long scaffold that crowds the context, is invisible today.

## Definitions (shared by every item; do not rename)

**Success** for one run of a scenario: every expectation on every beat passed. The scenario's rate is successes ÷ runs that were not skipped. A skipped run (no provider, house did not boot, spend cap reached) is out of the denominator and is reported, never counted as a failure.

**Presets.** Each is a set of switches. `sim` is all of Sim's guardrails on, as it ships.

| Preset | `[orchestration] ablate` | `[cognition] ablate` |
|---|---|---|
| `sim` | `[]` | `[]` |
| `no_scaffold` | `["scaffold"]` | `[]` |
| `no_verify` | `["verify"]` | `[]` |
| `no_revisions` | `["revisions"]` | `[]` |
| `no_recovery` | `["recovery"]` | `[]` |
| `no_rescue` | `[]` | `["rescue"]` |
| `bare` | `["scaffold", "verify", "revisions", "recovery"]` | `["rescue"]` |

**Switch meanings.** Each switch is read by the module that owns the behaviour, from its own config section. Unknown names are reported through `problems` and do not fail the boot.

- `orchestration.ablate` `"scaffold"`: the `task_rules` block (`scaffolds.render`) renders empty, except for safety and identity lines (who is speaking, the turn's language, a refusal rule). The model still gets the tool list and the tool schemas or markers, and nothing else of the workflow text.
- `orchestration.ablate` `"verify"`: every profile behaves as `verify = false`. The `review_benchmark` knob in `profiles.for_claimed` is the precedent.
- `orchestration.ablate` `"revisions"`: every profile behaves as `max_revisions = 0`.
- `orchestration.ablate` `"recovery"`: a tool result that is an error, a Guardian denial of an unknown tool, or a malformed call ends the session as `failed` on the spot. Today the error goes back to the model for another step. This is forge's `no_recovery`.
- `cognition.ablate` `"rescue"`: the parser accepts only a well-formed call. That means a marker line at the start of a line with exactly the tool's name, or a native typed call with arguments that are valid JSON for the schema. The leniencies in `cognition/parser.py`, such as first-line arguments, code-fence extraction and the case-insensitive marker match, are switched off. Whatever is not accepted becomes a plain text answer, exactly as an unparseable reply is treated today. This is forge's `no_rescue`.

None of these switches may weaken Guardian. Guardian is not ablatable: every proposal is still gated. The ablation measures the loop, not the safety layer.

## Action items

1. **Tool-chain expectations and fault injection.** *Lock `evals`.* In `simorgh/evals/house/script.py`, add expectations next to `called` and `the_house_did`:
   - `called_with(tool, **args)`: a subset match on the arguments of an `action.proposed`;
   - `called_in_order(*tools)`: a subsequence of the proposed tools since the beat;
   - `steps_at_most(n)`: counted from `task.step`/`cognition.think` for the beat's session;
   - `recovered()`: a tool failed during the beat and the session still ended `completed`.

   Fault injection: a `Beat(fails={"service": "light.turn_on", "times": 1, "error": "..."})` makes the sandbox's fake house raise on that call. Wrap `FakeHomeAssistant` from `simorgh/evals/house/sandbox.py`, so `simorgh/contracts/home/fakes.py` (contracts lock) does not change. Unit tests for each expectation against a hand-built `Record`. Acceptance: `python tools/modtest.py evals` is green.

2. **The `toolchain` scenario pack.** *Lock `evals`.* `simorgh/evals/house/scenarios/toolchain.py`, with 18-24 scenarios, all `needs_model=True` and asked directly (`ask_directly=True`, typed at the console as an owner). They are grouped in forge's categories:
   - **plumbing**: one tool; two tools in sequence;
   - **selection**: the right tool among similar ones, e.g. `home_call` against `room_play` against `remind`;
   - **argument fidelity**: an exact entity id or time carried from the request;
   - **chaining**: an argument taken from an earlier tool's *result*, such as reading a sensor and then acting on its value;
   - **conditional**: act only if a state holds;
   - **recovery**: an injected failure on the first call, and success on the retry or on a sensible alternative;
   - **relevance**: no tool is needed, so `the_house_did_nothing()` and `answered()`;
   - **safety**: a tier-3 request still asks a person, which shows the ablation did not open a gate.

   Every expectation reads the house or the bus, never the reply's wording. Register the pack in `scenarios/__init__.py` under the prefix `toolchain/`, and add a `toolchain` suite in `simorgh/evals/suites.py` (paid). Acceptance: with the floor provider every scenario reports `skipped` with its reason, and `python -m simorgh.evals house --only toolchain/` lists them all.

3. **The ablation switches.** *Locks `orchestration` and `cognition`; parallel to items 1-2.* Implement the switch meanings above:
   - `orchestration`: `config.py` (`ablate: tuple[str, ...] = ()`, validated against `{"scaffold", "verify", "revisions", "recovery"}`), `profiles.py`, `scaffolds.py`, `session.py`;
   - `cognition`: `config.py` (`ablate`, validated against `{"rescue"}`), `parser.py`, and the native-call decoding.

   The default `()` must leave every existing test and prompt byte-identical. One test per switch shows the behaviour changing, and one shows the default does not. Each module's `CONTRACT.md` gets the config key. Acceptance: `python tools/modtest.py orchestration` and `python tools/modtest.py cognition` are green.

4. **The ablation runner.** *Lock `evals`; after items 1-3.* Build `python -m simorgh.evals ablate`, with the flags in the Outcome section:
   - `--presets`: the table above, kept as data in `simorgh/evals/ablation.py`;
   - `--models provider:model`: sets `[cognition] provider_order = [provider]` and that provider's `model`;
   - `--repeats`, `--paid` (refuses without it), `--cap-usd` (a total cap across the matrix; the run stops cleanly when it is reached and reports what it skipped).

   Each (model, preset, scenario, repeat) is one child process, as `house/run.py` does today. The preset's config reaches the child through an environment variable (`SIMORGH_HOUSE_CONFIG`, JSON merged over the sandbox config). Output: the table, with a Wilson or bootstrap 95% interval on each row, and one JSONL row per run. Also `--dry-run`, which prints the matrix and an estimated cost without spending. Acceptance: unit tests with a fake child runner; `--dry-run` works with no key; a floor run (`--models floor:floor`, no `--paid`) reports every case skipped and exits 0.

5. **The first matrix.** *No lock; paid; needs the creator's spend cap.* Run it for the Together primary model, Gemini, and one small open-weight Together model, 5 repeats each, all presets. Write `docs/findings/<date>-toolchain-ablation.md`: the matrix, which guardrails earn their cost per model, and which scenarios fail even with `sim`. Those failures become the next bugs.

## What this must never do

- Ablate Guardian, or let an ablation config reach the live Sim. The switches exist for the sandbox; `sim.sh` never sets them. A test asserts the shipped `config.toml` has neither key.
- Spend without a cap, or start a paid run without `--paid`.
- Judge on the reply's wording. A scenario passes on what the house and the bus show.
- Count a skipped run as a failure, or a failure as skipped.

## Definition of done

- [ ] Items 1-4 built with tests; `modtest` is green for evals, orchestration and cognition; each CONTRACT.md is updated.
- [ ] `ablate --dry-run` prints the full matrix and a cost estimate.
- [ ] Item 5 run, and the findings written.
