# Native tool calls against markers, on Gemini and on Together (2026-09-22)

Stage 2 item 9 asks for a recorded win before any provider is switched to
native tool calls. On 2026-09-20 Together's GLM-5.3-Flash tied (23 of 24
either way). The same question, asked of a second provider with a
different native implementation, on three times the cases.

Suite: BFCL parallel (`simorgh.evals run tooluse --paid --cases 40 --repeats 3`),
`--providers` pinning the provider so no case could fall through to another
model (added the same day, `6c4b938`).

| provider · dialect | scored | 95% CI | skipped | wall |
|---|---|---|---|---|
| Gemini · markers | 102/110 (93%) | 87-97% | 10 | 2,623 s |
| Gemini · native | 101/108 (94%) | 89-97% | 12 | 2,744 s |
| Together · markers | 51/57 (89%) | 81-96% | 63 | 1,475 s |
| Together · native | 98/115 (85%) | 78-91% | 5 | 2,933 s |

## What it says

**Gemini: a tie.** One point apart with overlapping intervals, and the
failures are largely the SAME cases in both dialects (`parallel_multiple_55`
and `parallel_multiple_80` fail under both), which makes them properties of
those cases, not of the dialect. Nothing is flipped; the rule is a recorded
win, and this is the second provider to show none.

**Together: not comparable yet.** The markers run lost 63 of 120 cases to
the floor partway through -- Together stopped answering, most likely its day
cap after a day of trials and benchmarks -- so its 51/57 rests on half the
set. Rerun it after the cap resets before reading anything into 89 vs 85.

## What it took to get a Gemini number at all

Two bugs, each of which made Gemini useless and each silent until a run
pinned to Gemini alone:

- Gemini refuses a request deadline under 10 s; Cognition's `review` slice
  is 8 s, so the first review call failed and the Router rested Gemini for
  the rest of the day (`d8306cd`). This affected live Sim.
- Gemini refuses the whole native request if any tool's schema has an
  `array` without `items`; `energy_tariff`'s `rates` did, so every native
  Gemini call failed (`9201292`). The first native run skipped 120 of 120
  cases in 13 seconds.

## Next

- Rerun Together markers once its cap resets.
- If a difference is wanted, count model turns per case: markers may cost
  more turns even at equal accuracy, which is a token bill and a latency risk
  the pass rate does not show. The spans are recorded; nobody has counted.
