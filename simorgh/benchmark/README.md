# benchmark

Measures this system against standard benchmarks, and keeps the results
so movement is visible.

The creator, 2026-09-07: *"create a benchmarking unit that can benchmark
system against different standard benchmark systems and keep track of
historical benchmark results per model and show them on web ui through a
graph and on cli."*

## What it measures

The whole system, not the model. Each case is asked exactly the way a
human's `research <question>` is asked — a `task.create` on the bus,
answered through Planning, the Worker, Guardian and the tool loop. A
harness that called Cognition directly would measure the model, and the
model is not the part that has been failing.

## The suites

| name | dataset | scoring |
|---|---|---|
| `gaia`, `gaia-l1` | `gaia-benchmark/GAIA` (gated) | quasi-exact match on a `FINAL ANSWER:` line, per GAIA's own scorer |
| `bfcl-parallel` | `OpenMLRL/BFCL-V4-Parallel-Native` | the chosen function calls and their arguments, order-free |
| `swebench-verified` | `SWE-bench/SWE-bench_Verified` | **load-only**: real scoring means running FAIL_TO_PASS tests in the instance's container |

A suite we cannot score honestly is refused rather than given an invented
number. That is the whole discipline: a scorer looser than the published
one produces a figure nobody can compare to anyone else's.

Rows come from Hugging Face's datasets-server over plain HTTPS, so no
`datasets`, `huggingface_hub` or `pyarrow` is needed, and are cached
0600 under `~/.simorgh/benchmarks/` — outside the repository, because
GAIA's terms forbid resharing the set.

**GAIA needs a token with gated access.** Set `HF_TOKEN`, accept the
terms on the dataset page, and in the token's fine-grained settings tick
*Read access to contents of all public gated repos you can access*.
Without that last part the server answers "does not exist, or is not
accessible" for a dataset you can see in a browser.

## Using it

```
benchmark                            the latest result per suite and model
benchmark suites                     what can be run, and what is cached
benchmark run gaia 20 level=1        run a sample
benchmark history [suite]            accuracy over time, braille chart
benchmark show <run_id>              one run, case by case
```

The dashboard draws the same numbers at `/api/benchmarks`.

## What is honest about the numbers

- A case whose question needs an attachment we did not download is
  **skipped**, never scored wrong.
- A run cut short is stored and labelled `partial`, so nobody compares
  five cases against fifty as equals.
- Every run records its suite *version* (the dataset revision), because
  two runs are only comparable when both match.
- Time and cost per case are recorded but not scored: a system can pass
  by brute force and still be unusable.

## Not done

- SWE-bench scoring (containers, `FAIL_TO_PASS`).
- GAIA attachments: fetching the files a question refers to.
- Cost per case is a field with no writer yet; Cognition knows the
  number, nothing forwards it here.
