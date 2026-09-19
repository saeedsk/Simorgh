# Working in this repository

Simorgh ("Sim") is a self-improving personal agent for one household: 19 Python
packages under `simorgh/` composed by a Kernel, talking only through typed
messages on a Bus, with every effect gated by Guardian. Stdlib-only at the core.

**Read first, in this order:** `docs/README.md` (the map), `docs/ARCHITECTURE.md`
(what runs today), `docs/AGENTS.md` (how agents work here in parallel), then the
`CONTRACT.md` inside the package you are about to change.

**Sources of truth.** The code, then each package's `CONTRACT.md`, then
`docs/reviews/2026-09-18/architecture-evaluation.md` for known issues (catalogue
ids like S1, L2, C1), then `docs/plan/` for what changes next and in what order.
`docs/findings/` holds dated measurements. There is no other design record:
the old blueprint, evolution log and plans were removed on 2026-09-19 and live
only in git history (tag `pre-cleanup-2026-09-18`).

**Rules that are not negotiable**
1. Lock before you edit: `python tools/modlock.py claim <module> --by <you> --task "..."`,
   commit `docs/modules/locks.toml`, then work. Release when done.
2. Stay inside your lock: the package, its `tests/simorgh/<module>`, and its `CONTRACT.md`.
   A change to `simorgh/contracts/` needs the `contracts` lock and a note in every
   consumer's `CONTRACT.md` "Consumes" table.
3. Prove it before you commit: `python tools/modtest.py <module>` green (module tier);
   `--tier core` when you touched bus/ledger/kernel/contracts; `--tier full` before a bless.
   `python tools/modlock.py check --by <you>` must pass.
4. Commit messages start with the module name: `memory: persist vectors at store time`.
   Explicit paths, `git commit -F <msgfile>`. Push often.
5. Never edit `docs/SOUL.md` (the creator amends it by hand). Guardian-protected paths
   (`simorgh/guardian/`, `simorgh/execution/`, `simorgh/contracts/`, `simorgh/kernel/`,
   `simloader.py`, `sim.sh`) may be edited by a human-run agent with a lock, never by Sim's own tasks.
6. Do not run the full suite casually; it is the bless gate. Do not boot Sim from this checkout
   while another agent holds locks; use `tools/trial.py` in a repo copy.
7. Update `CONTRACT.md` in the same commit as any change to a topic, schema, stream, config key
   or public symbol. A contract change without a doc change is the "unconnected wire" bug this
   project keeps finding.

Every plan stage in `docs/plan/` is written to be executed by an agent that has never seen
the repo. Start at item 1 of the lowest unfinished stage unless the creator says otherwise.
