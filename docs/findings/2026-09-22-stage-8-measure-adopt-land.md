# Stage 8: a policy is measured before adoption and lands after a person says yes (2026-09-22)

Stage 8 item 5, in two commits, and what the live ledger says about item
10's numbers.

## The chain, end to end

Before today a policy could be proposed and stored (items 3-4, 6) but
never adopted by evidence, and an adopted rule would have changed nothing:
no code read `rules/`.

1. **Measure** (`3efa243`, `growth/evaluate.py`). A candidate runs on its
   task type's held-out cases beside the same cases without it, 3 repeats
   each, majority per case. Any case it breaks refuses it even when the
   mean is flat (`PolicyStore.refuse`); otherwise adoption keeps its two
   conditions, no regression and at least one motivating case fixed.
2. **Run it at night** (`53e2c2b`, `growth/measure.py`). Nothing called
   `measure_and_decide`, so no policy could ever be adopted. The night now
   has a `measure:<id>` step per PROPOSED rule: the task type's held-out
   suite (`[growth] held_out`) runs in a fresh copy of the committed HEAD,
   with and without the candidate appended to the copy's
   `rules/<task_type>.md`, as `python -m simorgh.evals run <suite> --json`
   in a child whose cwd and `PYTHONPATH` are the copy.
3. **Ask a person** (`3efa243`). The creator decided on 2026-09-22: "let
   Guardian ask me before a rule is written into rules/".
   `guardian/config.py::ask_subjects = ("rules/",)` makes `ProtectedRule`
   escalate there instead of deny; every other protected path still
   refuses, and `protected` joined the person-only layers so no classifier
   settles it.
4. **Land** (`3efa243`). `execution/policyadopt.py` appends the rule to
   `rules/<task_type>.md` and commits that one file; any other path is
   refused.
5. **Take effect** (`3efa243`). `orchestration/profiles.py` renders
   `rules/<agent>.md` after the agent's body.

Guards on cost, from `53e2c2b`: the step is off unless
`[growth] measure_policies = true`, because the suites are paid. It is
priced at 2 x repeats x `measure_usd_per_run` (the sandbox's $0.50 cap)
and skipped before anything is spent when the night's budget cannot cover
it; the default $0.50 night never covers one, on purpose. A task type with
no held-out suite is recorded as skipped and left proposed, never adopted.
A run in which no case counted decides nothing (it used to refuse the
policy for good). The night's day budget now resets on the Context
clock's day.

The acceptance cases (`tests/simorgh/growth/test_a_policy_is_measured_before_it_is_adopted.py`)
use fakes. No paid run was made, because there was nothing to run it on.

## Item 10: what the live ledger holds

Checked on the live data dir (`~/.simorgh/ledger/streams`, 2026-09-22
04:43):

| | count |
|---|---|
| `growth:policies` stream | does not exist |
| policies proposed, adopted or retired | 0 |
| `growth:candidates` entries | 6 |

The six candidates are all the pattern miner's review prompts ("'chat'
tasks failed 3/4 recent outcomes", "'research' tasks failed 5/10", and so
on), not policies. So item 10's numbers -- adopted vs retired, surviving
30 days, eval delta per adoption, regressions attributed to a policy,
exploration yield, nightly cost -- still cannot be taken: the loop is
complete and has never had an input. The next thing to watch is the first
`growth.policy.proposed` on the live system, then a night with
`measure_policies` on and a budget that covers it.

## Not done

Only `rule` policies land. Skills, routing changes and patches (the other
kinds item 5 names) have no landing path yet. Item 9 (routine mining) is
deferred by the plan until four weeks of Home Assistant history exist.
