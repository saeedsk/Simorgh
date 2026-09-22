# Gemini refuses a deadline under ten seconds, and one review call benched it for the day (2026-09-22)

## What happened

Cognition gives its `review` purpose an 8 s slice of the call deadline
and passed that to the Gemini SDK as the server deadline. Gemini refuses
such a request outright:

    400 INVALID_ARGUMENT: Manually set deadline 8s is too short.
    Minimum allowed deadline is 10s.

The Router treats a failed call as a provider problem and rests the
provider. So the first review call that went to Gemini failed, Gemini was
rested, and every later call that day that would have gone to it fell
through -- in a benchmark that pins Gemini, to the floor. Found when a
Gemini-only benchmark answered two cases and then nothing. The same thing
happened to live Sim whenever Gemini took a review call.

## The fix (`d8306cd`)

`providers/gemini.py::MIN_SERVER_DEADLINE_S = 10.0`: the server is always
told at least 10 s. The Router still waits only its own slice, so a slow
call is still cut off where it was; what changed is that a short slice no
longer makes the request invalid.

| five cases, Gemini only | answered |
|---|---|
| before | 2, then the floor |
| after | 5 of 5 |

## A benchmark measures only the provider it names (`6c4b938`)

Found on the way. With the library's order (together, gemini,
claude_code_cli), a call Gemini refused fell through to the next provider
without a word, so a "Gemini" run could score another model's answers.
`python -m simorgh.evals run ... --providers NAMES` now pins a paid run
to the named providers, followed only by the floor, whose answers are
skipped. A dead provider shows as skipped cases rather than as someone
else's score.

## Pending

Stage 2 item 9's comparison on Gemini, over BFCL, is the run this was fixed for. It had not finished when this was written,
and neither had the GAIA run; no numbers from either are reported here.
