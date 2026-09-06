# `simorgh/execution/`

The only subsystem the Bus/Kernel enforcement lets subscribe to
`action.approved`. Independently re-verifies every approval
(`verifier.ApprovalVerifier`) before dispatching to the tool registry --
defense in depth, since the Bus's own topic restriction is not a
cryptographic identity check in single-process mode. See
`docs/blueprint/subsystems/08-execution.md` for the full spec.

## Why re-verification fetches args from the Ledger, not the message

`action.approved` carries only `args_sha256`, never the original `args`
(`contracts/messages/action.py`). `_fetch_proposed_args` reads the real
args back from the durable `action:<action_id>` stream's own `received`
event -- the record Guardian appended before deciding -- and the verifier
recomputes the hash against those, not against anything a forger might
attach directly to a fabricated `action.approved`. This is the actual
mechanism that makes "an approval cannot be transferred to different
arguments" true; see `verifier.py`'s own docstring.

## Tools built this pass (ported from v1)

`read_file`, `list_dir` (path-safety bounded, `pathsafety.py`, ported from
`src/cognition/tool_protocol.py`), `run_python_sandboxed` (ported from
`src/sandboxing/sandbox.py`: `python -I`, empty env, temp cwd, rlimits --
deliberately no repo access), `apply_source_patch`, `git_commit` (ported
from `src/orchestrator/git_ops.py`, plus a `git status --porcelain`
pre-check that reports an explicit `nothing_to_commit` instead of a
buried edge case -- and, unlike a naive `git diff --quiet HEAD`, correctly
catches brand-new untracked files too), `git_revert`. Never pushes.

## Deliberate scope cuts (see 08-execution.md section 12 for the full list)

- `web_fetch`, `shell`, `relaunch`, `hot_swap`, `isolated_test_suite`, and
  skill-loading tools are NOT built this pass -- `relaunch`/`hot_swap`
  need a `KernelControl` contract that doesn't exist yet, and skill tools
  depend on Learning.
- The spec's suggested `registry.py`/`runner.py` split was not done;
  registry and dispatch are merged into `service.py` for this build. A
  natural follow-up once the tool count grows past what fits on one
  screen.
- The real, built `ToolContext` (`contracts/protocols.py`) has fields
  `action_id, task_id, scope, constraints, data_dir, clock, logger,
  ledger, bus`. The spec doc describes additional fields (`repo_root`,
  `blobs: BlobStore`, `channel`, `kernel_control: KernelControl`) that do
  not exist in the built contracts yet -- this package is built against
  the real contract, not the aspirational one; the gap is noted in
  08-execution.md section 12 rather than resolved by editing
  `simorgh/contracts/` unilaterally.
