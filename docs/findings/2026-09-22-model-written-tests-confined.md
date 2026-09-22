# A model's tests run confined, and a pause holds a verification (2026-09-22)

Stage 0 item 32 had two safety gaps left from contract writing
(`2026-09-19-contract-writing.md`). Both closed in `449b596`.

## The tests the model just wrote ran outside Guardian

Verification's `checks/_baseline.py` runs pytest three times on a code
task: collect at the base revision, run at the base revision, and a quiet
re-run on the task's own tree -- code the model wrote minutes earlier. All
three went through `subprocess.run` with the environment scrubbed and
rlimits set, and nothing else. A test file is code, so a model that wrote
a test that opened a socket or wrote into `$HOME` had that code executed
with the user's rights, past the gate every other effect goes through.

Now all three run through `_confined`. On macOS that wraps the command in
`sandbox-exec` with a profile that denies outbound network and every file
write outside the run's own temporary directory (`TMPDIR` is pointed into
it, so pytest's scratch still works).

Measured in the commit's tests:

| test body | result under `_confined` |
|---|---|
| opens a socket | fails, `EPERM` |
| writes to `$HOME` | fails, `EPERM` |
| an ordinary test | passes |

Limits, stated plainly: this is macOS only. Where `/usr/bin/sandbox-exec`
does not exist the run is exactly as it was before (`_confined` returns
the argv unchanged). `sandbox-exec` is deprecated as a command, though it
is still what the OS uses to confine children. Linux would need its own
mechanism; there is none yet.

## A pause did not pause Verification

`_paused` was set by the pause command and read by nothing in
Verification, so a paused Sim went on judging tasks. Now a verification
waits for the resume and never answers early; Orchestration checks the
pause before a verify round, and a verify wait that runs out while paused
parks the task instead of recording it as "accepted unverified". Both
Orchestration tests fail on the code before the change.

## What this changes

Stage 0's item 32 is done. The stage stays open on item 28 (V7, the echo
canceller, which needs the creator at the microphone) and item 30 (the
gate's paid round). Nothing here was run live; the evidence is the tests
named above.
