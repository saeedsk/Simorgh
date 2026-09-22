# The growth merge's leftovers: trials ran with autonomy on for two days (2026-09-22)

Learning, Reflection and Curiosity became one `growth` subsystem on
2026-09-20 (`4fe9ee1`, `2026-09-20-stage-8-growth-merge.md`). The topics
and streams were kept on purpose; the config sections moved
(`[curiosity]` to `[growth.explore]`, `[reflection]` to
`[growth.monitors]`, and so on). A sweep two days later found what still
read or wrote the old names. Two commits: `efa116a` (tools) and
`9b500b2` (everything else).

## Trials and benchmarks ran with autonomy ON

`tools/trial.py`, `tools/trial_suite.py`, `tools/bench_instance.py` and
`tools/kill_resume_trial.py` all set `[curiosity] autonomy_on_boot =
false`, because the point of a trial is that nothing self-directed
competes with the task being measured. After the merge nothing read
`[curiosity]`, so **every trial and benchmark run through those tools
since the merge ran with Sim's autonomy on**. The benchmark harness's
`[reflection]` switches (distillation off -- in the 2026-09-14 benchmark
copies it queued skill tasks that ran the machine out of memory) had
moved to `[growth.monitors]` the same way and were ignored too.

Found from the `config.section_moved` warning printed in a trial's own
output. A new test reads every harness tool against `RENAMED_SECTIONS`.

What it touches, without re-measuring anything: the runs behind
`2026-09-20-kill-and-resume.md` and `2026-09-21-sim-on-the-benchmark.md`
used these tools after the merge, so self-directed work could have been
running beside them. Neither finding's conclusion depends on quiet
background -- one is about a resumed task not repeating a step, the other
records four different failure paths -- but neither run was as isolated
as its harness claimed. Whether autonomy actually started anything during
those runs was not checked.

## Eleven tests booted with autonomy ON

The same stale key sat in eleven tests (`[curiosity] autonomy_on_boot =
false`), so they too booted with autonomy on. The guard test that checks
for renamed sections now scans `tests/` as well as the source.

## Config typos in the live sections were never reported

`kernel/configcheck` keyed its probes by the dead section names, so a
typo in `[growth.explore]`, `[growth.estimate]` or `[growth.monitors]`
was silently accepted. Probes are keyed by the dotted tables now, and a
stray key in `[growth]` is reported too.

## Smaller ones

- `ledger/streams` `KNOWN_PREFIXES` named owners that no longer exist
  and lacked `growth:` and `reflection:`, so `scan_half_wired` skipped
  `growth:policies`, `growth:candidates` and `reflection:alerts`.
- `tools/contract_skeleton` kept its own copy of the layer table, in
  which `growth` rendered as `?`; it reads `kernel/registry.LAYERS` now.
- The three part CONTRACT.md files told an agent to claim and modtest
  modules that no longer exist. `modtest --tier contract growth` now also
  runs the parts' own contract-test lists: 23 files, previously none.
- `explore` filed its interests gauge under subsystem `curiosity`; it is
  `growth` now (vitals reads `growth.interests`), as are the part names,
  log events and `proposed_by`.

Kept on purpose: the `learn.*`, `reflect.*`, `curiosity.*` topics and
their stream names (renaming would orphan history), and the task origins
"curiosity" and "reflection", which label where a task came from.

Full tier after the sweep: 7,225 passed.

## Pending

A trial started from a checkout that has `efa116a` runs with autonomy
off. The trial rounds under way on 2026-09-22 had not reported when this
was written; their results belong in their own entry.
