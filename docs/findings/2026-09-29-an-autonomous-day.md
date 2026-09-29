# An autonomous day: four benchmark Sims, the first proposed policy, and what running them found (2026-09-29)

The creator, 08:00: "go ahead do all those tasks, additionally run 4 sim
instances in sandbox, give different benchmark task to them, monitor,
detect bugs and improve sim. continue this effort for next 8 hours" --
and then "make decisions by yourself, don't stop". This is the record.

## The morning's rollback, first

The live Sim booted OLD code: `voice set satellite_lead_in_level` was
"not a setting". The loader's core gate had failed on one test
(`test_a_brand_new_package_needs_allow_new`) and rolled the checkout back
to `sim-good-0054`. The test's fake PyPI payload hard-coded its latest
upload at 2026-08-30, so "first release 3 days ago" became "30 days ago"
once the calendar passed 2026-09-29 (`8d2abd67`). I had called that
failure "unrelated" the evening before. Rule since: run the loader's exact
gate before saying "restart", and fix anything red.

Later the same shape again: at 15 GB free the ledger called itself
degraded (5% of a 460 GB disk is 23 GB), four boot tests failed, and a
restart would have rolled code back for a disk problem. The ledger's
floor is now 5 GB (`ff8ab474`). A timing-only watchdog test failed the
gate once under load; it now waits for its answer (`ce9e349d`).

## Found by running Sim, fixed

| What | Found how | Commit |
|---|---|---|
| English questions answered in Farsi for two days: facts stored on the 27th ("language_preference: Farsi only", "Sim only speak Farsi") sat after the language line | live `voice:turns` | `f4c8df30` |
| The speaker's name opened almost every reply: an unplaced turn reset "who Sim was talking with" | the creator | `1ddaccef` |
| GAIA attachments landed in the LIVE checkout: a bench copy imports `simorgh` from the main repo and the runner rooted files at the package | a GAIA case: "absent across all 8 attempts", then `find /` | `367430d1` |
| A `RUN_SHELL:` payload carried the model's invented next turns ("[user] Result of run_shell: / find: '/proc/1/...'") and all of it ran as one command | the same case's action stream | `f6700915` |
| No tool could look at an image file; only cameras had eyes ("without a vision tool in this session I cannot classify") | a GAIA video case | `056122bd` |
| 57 of 113 growth candidates (`patch:simorgh/growth`, ...) could never become a policy: "no agent named" | the first paid growth night | `17fd9495` |
| The pattern miner forgot everything at each restart, so a night had nothing to diagnose | same | `23bdec9e` |
| The config check called `propose_policies`/`measure_policies`/`held_out` "nothing reads them" while growth read each one | same | `9ef27e19` |
| SWE-bench pulled ~3 GB images with no disk check outside `bench_instance` | the growth night filled the disk to 10 GB | `c170f9d4` |
| Chatterbox said عصرت "asrat": vowel marks did not move it; an alef spelling did (whisper forced to English: "Asrat" x6 vs "Asred"/"Astrid") | the creator, then measured | `1ef5dc5c` |
| `look_at_image` failed its schema on every call, and `people` (roles, consent, the matrix) had never worked from a marker reply: several fields, no mapping, JSON passed on as `{"argument": ...}` | the GAIA copy's verifier: "all three look_at_image attempts failed with schema validation errors" | `56d307d7` |
| From the phone: "I can't reach the MacBook's processes from here" and "Tailscale isn't installed on this host" -- nothing told the model where it runs, and the Tailscale CLI lives inside its app | the creator's phone conversation | `1c741fbc` |
| The full tier (every landing gate) was red on `main`: a missing live-status verb (mine), 135 `getattr(config)` reads against a ratchet of 127, four contradicting fallbacks, and an undeclared `voice.room.speech` subscription | a trial landing listed them as "also fail on main" | `e7af3f2f`, `df7b8896` |
| Gemini could never see: the Router asked for an attribute Gemini did not have, and Gemini's `complete` dropped pictures. Fixed with `[cognition.providers.gemini] images` (default off -- camera stills would otherwise go to the cloud) | a GAIA copy: "nothing here can look at a picture (tried: together, gemini, floor)" | `b8437bb9` |
| A red boot gate rolled back even for a failure that passes alone; two such load flakes seen today | the gate under load | `712fd967` |

The creator's phone voice lagged ("something is hogging the CPU"): four
benchmark copies, the trial suite and my gates had the load average near
30. The wave was cut to two copies. My own scratch gate script also
exited 0 on a red run, so one commit went in on a (flaky) red gate; the
script is fixed.

Blessed `sim-good-0055` at 09:30 (core 4450 green, household 3/3, house
10/10) so a rollback no longer lands on the morning's old tag.

Also done: the per-person permission matrix, the last open piece of stage 6
item 5 (`bb3a437e`); stage 12's status line brought up to the code, and
stage 3 item 6 decided (`69c8e4c3`).

## Decided, not built

- **Streaming STT primary (stage 3 item 6):** declined as written. On 212
  live turns STT final p50 is 1.85 s (turbo) / 3.16 s (large-v3); one
  whisper-server call is a flat 1.2 s (forced English) or 1.8 s (language
  detected) regardless of clip length -- the fixed 30 s encoder window.
  No streaming model speaks Farsi. Per-request `audio_ctx=768` cut 46
  calls from 89 s to 68 s but changed 37 transcripts, better and worse;
  without a labelled set it stays off.
- **Stage 1 item 10, stage 4 item 4, stage 9 items 2-4:** left. Each was
  measured or reasoned about before (WorkerKernel backs a working mode;
  context assembly is ~5 ms of a 4.5 s think), and a structural refactor
  of a checkout the live Sim boots from buys nothing measurable today.
- **Stage 12 item 4 (push an unanswered prompt):** no push channel is
  configured (no ntfy, Gotify or Home Assistant notify key); building it
  would be a wire with nothing on the other end. Needs the creator's
  choice of channel.

## The first policy Sim ever proposed

A paid growth night (approved run s8#5) in a repo copy, on a copy of the
live ledger, with `propose_policies` and `measure_policies` on and a
7-day pattern window: 4 candidates, 4 drafts, one proposal --

> Before finalizing any patch, re-read the failing test's exact assertions
> and trace your change against them line by line -- most of these
> failures come from fixing the surface symptom rather than the cause.

It was not measured. The held-out suite for `patch` is the SWE-bench
slice, and five cases need ~15 GB of images on a disk with 10 GB free;
the night was stopped before it filled the disk under the live Sim. The
policy lives only in the copy's ledger. To measure one for real: free
~20 GB, or give `patch` a held-out suite that needs no containers.

## The benchmark wave

Four headless copies (`tools/bench_instance.py`), Together GLM-5.3-Flash:

| Suite | Correct / attempted |
|---|---|
| BFCL parallel (several slices) | 299 / 384 (78%) |
| GAIA level 1 | 15 / 20 |
| GAIA level 2 | 13 / 20 |

BFCL misses are the model's judgement (splitting one call into two,
"large pepperoni pizza" where the size is its own argument) -- no Sim
fault found in them. The SWE-bench instance was stopped within minutes:
this disk cannot hold its images today.

## The trial suite, abandoned

Four of five trials "blocked", and the reason was me: the landing gate
of each trial ran its pytest beside my own loader-gate runs, and whole
directories came back ERROR -- the same tests are green on `main` and in
a clean worktree. The rule in memory ("never beside another pytest")
held; I broke it. The watched `create-a-file` trial passed on its own
(wrote, tested, committed, landed). The suite is to be re-run on a quiet
machine.
