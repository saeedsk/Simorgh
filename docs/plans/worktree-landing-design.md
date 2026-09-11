# One worktree per task: how Sim changes its own code

Design and build, 2026-09-11 (Fable). Built in the same pass; this
document records what exists and the decisions behind it, so the next
person does not have to re-derive them from the code.

## Why

Until this change a patch or skill task edited the live checkout: the
tree the running process was imported from, shared with every other
task and with the creator's own uncommitted work. Three costs came
with that, all seen in observer waves:

1. **Collisions.** Two tasks editing at once shared one working tree.
   `git_commit` stages one path, so task A could commit task B's
   half-written file, and cleanup for one attempt could discard the
   other's edit.
2. **A process standing on a moving floor.** A half-written module
   sat under a process that might import it (a skill announce, a test
   subprocess), and a bad edit was live before any gate saw it.
3. **No whole-suite gate before a commit.** Verification asks whether
   the model *ran* the suite; nothing ran it mechanically before the
   change reached main. "Nothing gates a commit on the whole suite"
   was an open blocker since wave 5.

The creator's framing: the assistant that maintains Sim works on a
copy, tests there, and commits only when green. Sim should do the same
for its own code, and for any other project it works on.

## The shape

```
open   git worktree add -b sim/task-<id> <data_dir>/execution/worktrees/<id> HEAD
work   every path tool resolves against the worktree (ToolContext.root)
land   refuse a dirty tree -> rebase onto main -> whole suite in a copy of
       the rebased tree -> git merge --ff-only -> remove the worktree
close  remove the worktree and branch (a task that failed or gave up)
```

A **git worktree**, not a copy. It shares the object store, costs
milliseconds, and every commit made in it is already in the same
repository, so landing is a fast-forward rather than a copy back. The
copy approach the observer harness uses (`tools/observer_kit.py`)
exists because an observer must not own the repo it tests; Sim owns
its repo.

Worktrees live under the runtime data directory, never under the
repository. A checkout nested inside the tree it came from is the
mistake `fast_copy_repo` already guards against, and the isolated test
copy would otherwise copy every worktree into every run.

## Who does what

| step | who | where |
|---|---|---|
| decide a task gets a worktree | `orchestration/session.py::_uses_worktree` | patch and skill kinds, execute mode, `[orchestration] worktrees` on |
| open | `SessionRunner.run` proposes `worktree_open` before the first think | `execution/worktree.py::WorktreeManager.open` |
| bind every later call to the tree | `execution/service.py::_on_approved` sets `ToolContext.root` from the **recorded proposal's task id** | `execution/tools.py::tool_root` |
| land | `SessionRunner.run` proposes `worktree_land` after verification passes and the claims and uncommitted checks hold | `WorktreeManager.land`, serialised by a lock |
| gate | `RunTestsTool.gate(root)`: the same isolated run the model gets, on the rebased tree | `[execution] landing_gate` |
| keep or close | a continuing block (steps, verification, landing) keeps the tree; anything else closes it | `SessionRunner._continues`, `_close_worktree` |
| read files for the checks | `verify.requested` subject carries `repo_root` | `verification/checks/_files.py::repo_root_of` |
| prune | at Execution start, trees untouched for `worktree_max_age_days` | `WorktreeManager.prune` |

Guardian sees every one of these calls: the three worktree tools are
ordinary actions with ordinary policies (`orchestration/tools.py::
_TOOL_POLICY`). `worktree_land` is the one marked irreversible, since
it is the one that changes main, so an approval mode that asks about
irreversible actions asks about landing and nothing else.

The model never asks for a worktree. The tools have no marker, are in
no profile, and the task id that selects a tree comes from the
proposal the session runner wrote, not from arguments. A task can only
ever touch its own tree.

## Decisions

**Scratch stays on the live tree.** `workspace/` is the one place a
long piece of work keeps notes across tasks; a worktree is removed the
moment its task lands. `tool_root` sends scratch paths to the repo
whichever tree the task edits. The same rule keeps a materialised
SWE-bench checkout (`workspace/swebench/<id>/`) where the container
wire expects it.

**A retry resumes the same tree.** The worktree path is a pure
function of the task id, so `worktree_open` on attempt 2 finds attempt
1's tree with its uncommitted edits and its commits. A worktree whose
directory was lost (a crash, a pruned temp dir) resumes on its branch:
the commits are real work. `task.edits_kept` and `resume.py` are
unchanged; they still tell the next attempt what was left in the tree.

**Landing failures are continuations, not failures.** A rebase
conflict, a red gate, or a live checkout in the way blocks the attempt
with `landing failed: <reason>`, keeps the tree, and the next attempt
starts from it with the reason in its carried memory. The conflict is
the model's to resolve against the current main; guessing at a merge
is exactly what a landing step must never do. `KEEP_EDITS_UNTIL_ATTEMPT`
still bounds the chain.

**The live checkout is respected.** `git merge --ff-only` refuses if
the creator's working tree has uncommitted changes in a file the
branch touches, and the refusal reaches the task as a plain reason.
Nothing ever stashes, resets, or overwrites the creator's work.

**A worktree is only ever made of a repository somebody named.**
`[execution] repo_root`, or the `SIMORGH_EXECUTION_REPO_ROOT` that
`sim.sh` now exports (`kernel/service.py` applies `SIMORGH_<SECTION>_
<KEY>` overrides to the execution section, which `kernel/config.py`
had promised for every section and delivered for `[runtime]` alone).
A root merely inferred from the working directory means in-place
edits, as before. The first version of this feature learned why the
hard way: the integration tests boot a real Kernel from the real
checkout with a temp data directory and no repository named, and one
suite run put 45 stray `sim/task-*` branches on the live repository
(nothing landed; the stray branches were deleted). Inferring "which
repository" from where the process happens to stand is exactly the
mistake the sandbox-isolation lesson in the project memory describes,
and branching is where it stops being harmless.
`tests/simorgh/integration/test_a_patch_lands_through_a_worktree.py`
proves both halves: a named temporary repository receives the landed
commit, and an unnamed one is never branched.

**Off means the old behaviour.** `[execution] worktrees = false`, a
repository without `.git`, or a harness without Execution's worktree
tools: the session records "working in the live tree; no worktree:
<why>" as its first step and edits in place, as before. `SessionRunner`
defaults the switch off so the existing session tests ask for nothing
new; `orchestration/config.py` defaults it on, so the Kernel, `sim.sh`
and every trial run with it.

**The loader is unchanged.** Landing fast-forwards main, which is what
an in-place commit did before; `simloader.py` still gates the next boot
and tags it known-good. The difference is that main now only ever
receives commits whose whole suite passed on the rebased tree.

## What the first live runs found

Two watched trials with the real model (tools/trial.py, 2026-09-11)
went open -> edit -> test -> two commits on the branch -> verification
-> landing, and each stopped one seam short:

1. **The bus deadline cut the landing gate.** Execution's
   `action.approved` subscription had the bus's default 300s
   per-handler guard; the whole-suite gate ran past it on a loaded
   machine, the handler was cancelled mid-land, the approval was
   redelivered, and Guardian refused the redelivery as an expired
   token: "landing failed: denied: signature expired" over a green,
   verified branch. The subscription is `UNBOUNDED` now, as the
   Worker's already was and for the same reason: every tool is bounded
   by its own timeout, and the bus was cutting from outside.
2. **Attribution blamed load on the change.** The whole-suite run under
   load failed a known-flaky interface test and two real-browser
   tests; the base run, a few tests alone, passed them; and the change
   -- one standalone module -- was told it "made tests fail that pass
   without it". `_baseline.attribute` now re-runs the candidates
   quietly on the changed tree too, and a test that is green there is
   reported as flaky, not introduced.

## What this does not do yet

- **Foreign projects.** `WorktreeManager` takes any repository, but a
  task has no field naming one, so every task's worktree is of Sim's
  own repo. A project under `workspace/` still uses the nested-repo
  wire (`nested_git_root`, `find_enclosing`). Giving a task a `repo`
  and opening its worktree from that is the next slice.
- **Relaxing `full_suite_ran`.** The landing gate runs the whole suite
  mechanically, so the verification check that asks the model to run
  it is now a second run of the same suite. It stays for this slice:
  two changes to what verification demands at once would make a
  regression in either one hard to attribute.
- **Guardian's protected-file diff** still reads the "before" text
  from the live tree. Protected paths are repo-relative and identical
  in every worktree, so the decision is the same; only the diff shown
  in a denial could be stale.

## Tests

`tests/simorgh/execution/test_worktree.py` runs the manager and tools
against a real git repository: open, resume, lost-tree resume, patch
and commit landing in the worktree and not main, green landing,
dirty-tree refusal, red-gate refusal, conflict refusal with the rebase
aborted, clean rebase onto a moved main, nothing-to-land, a live
checkout in the way, close, prune, and the task id coming from the
context rather than arguments.

`tests/simorgh/orchestration/test_worktree_flow.py` runs a real
`SessionRunner` over fakes: open before the first step and land after
verification, a refused landing that blocks and keeps the tree, the
switch off, a chat session, no worktree available, and a cancelled
task closing its tree.

`tests/simorgh/verification/test_files_follow_the_repo_root.py`: the
file-reading checks read from the worktree the subject names.

`tests/simorgh/integration/test_a_patch_lands_through_a_worktree.py`
boots the real Kernel (real Guardian, Execution, Verification,
Orchestration, Ledger; scripted Cognition and Planning) against a named
temporary repository: the patch is written in the worktree, the suite
runs, the commit lands on that repository's main with the whole-suite
gate in between, and no branch or worktree is left behind. Its sibling
boots the same Kernel with no repository named and shows no worktree
is asked for and the live checkout gains no branch.
