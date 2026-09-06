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

## Skill acquisition as procedural memory (Phase 4 roadmap item 4.7)

`apply_skill` (writes a drafted skill's module source, confined to
`write_scopes_skills`/`simorgh_skills/` -- the write half `apply_source_
patch` already had, scoped to the skill directory instead of the source
tree) and `skill:<name>` tools (`SkillTool`) are built this pass.
`SkillTool` runs the acquired module's own source inside the same
throwaway subprocess sandbox `run_python_sandboxed` uses, invoking its
`run(**args)` entrypoint (imported under a name other than `__main__` so
a drafted skill's own `if __name__ == "__main__":` footer never fires a
second time).

Never registered at boot -- `Service` subscribes to `learn.skill.
acquired` and loads exactly the one newly-acquired skill (`_load_skill`),
which is what makes this "on demand" rather than a directory scan of
`simorgh_skills/` at `start()`. A second path lives in `_on_approved`:
an approved action naming an as-yet-unregistered `skill:<name>` tool
(e.g. a skill acquired in a previous process) triggers the same
`_load_skill` lazily, reconstructing its path from the `skill_dir/
<name>.py` convention `apply_skill`/`SkillPipeline` both already use --
no fresh `learn.skill.acquired` required. Either path best-effort
enriches the registered tool's `description` via a `memory.retrieve
{kinds:[procedural]}` request against the procedural record Learning
writes on acquisition (`learning/pipeline.py`) -- the "discoverable by
description" half of the roadmap item; a Memory that never answers (not
booted, or nothing stored yet) degrades to a synthesized description
rather than blocking the load.

## Deliberate scope cuts (see 08-execution.md section 12 for the full list)

- `web_fetch`, `shell`, `relaunch`, and `hot_swap` are NOT built this
  pass -- they need a `KernelControl` contract that doesn't exist yet.
  `isolated_test_suite` and the `skill.draft`/`self_patch.draft`
  Cognition-backed drafting-loop tools are also not built -- Learning's
  `PatchPipeline` proposes them, but they depend on Cognition composing
  a multi-step read/draft/test loop, which is out of this build's scope
  (see `simorgh/learning/README.md`'s own open questions for the
  consequence: a skill/patch pipeline run against a real Guardian +
  Execution currently rejects at the first draft attempt with "unknown
  tool", since nothing in this build implements `*.draft`).
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
