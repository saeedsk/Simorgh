# refute:proportionality:The hand-maintained denylist is doing se

*Workflow: review · Phase: Refute · Agent id: `a10614bae37739379` · Tool calls: 15*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "safety-guardian-execution". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "The hand-maintained denylist is doing security work it cannot do, and the project keeps paying to patch it",
    "kind": "wrong-design",
    "severity": "medium",
    "claim": "Thirteen regexes (guardian/config.py:46-79) plus 32 shell refusals (shell.py:53-118) plus bandit HIGH-only are the code-payload boundary; the rules module has 9 commits since 2026-09-07, most of them closing an observer-found bypass, and the denylist still misses `os.execvp`, `os.spawn*`, `os.fork`, `asyncio.create_subprocess_*`, `multiprocessing`, `importlib.import_module`, `curl`/`ssh` in a shell, and any concatenated path.",
    "evidence": [
      "`git log --oneline --since=2026-09-07 -- simorgh/guardian/rules.py | wc -l` -> 9",
      "shell.py:17-27 'Not an attempt at a security boundary -- a shell has no such thing'; config.py:213-215 same admission for `shell_refusals`",
      "Offline pipeline with default Config and bandit on: `os.execvp` and `asyncio.create_subprocess_shell` payloads approved; `os.popen` denied (B605)",
      "`which shellcheck` -> not installed, so ShellcheckRule abstains on this machine (rules.py:589-590)"
    ],
    "why_it_matters": "The authors already know this; the finding is that the architecture leans on it anyway because there is no confinement layer beneath. Every observer wave will find another string.",
    "recommendation": "Treat the denylist as a linter for the model's habits (keep it, stop extending it) and put the security boundary in the OS: macOS `sandbox-exec` profiles per tool, or a dedicated user account for the subprocess-spawning tools. That single change makes findings 2, 4 and most of 3 moot.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read guardian config denylist regexes |  "simorgh/kernel/", "simorgh.toml", # The bootloader and its launcher. They are the mechanism that gates # a change and undoes a bad one, and an observer showed |
| 2 | Bash | Read shell tool refusal list | (eval):1: no matches found: simorgh/*/*/shell.py |
| 3 | Bash | Check rules.py commit history and tool availability | fb48ab3 Make Guardian see a command it was blind to, and a sink a patch reaches around 73193c8 Guardian rules for the new tool surface, and files that are not p |
| 4 | Bash | Locate shell.py and read the refusal list | simorgh/execution/config.py simorgh/execution/remote.py simorgh/execution/shell.py ---- simorgh/execution/shell.py is worth saying plainly rather than pretendin |
| 5 | Bash | Check for any OS-level confinement in the codebase | (eval):1: no matches found: --include=*.py ---- (eval):1: no matches found: --include=*.py ---- (eval):1: no matches found: --include=*.py |
| 6 | Bash | Look for OS-level confinement and the sandbox implementation | ---- sandboxed impl simorgh/execution/tools.py:1003: (getattr(resource, "RLIMIT_CPU", None), cpu_seconds), simorgh/execution/tools.py:1004: (getattr(resource, " |
| 7 | Bash | Test the cited bypass payloads against the two denylists offline | denylist entries: 13 shell refusals: 32 os.execvp -> passes denylist os.spawnlp -> passes denylist os.fork -> passes denylist asyncio.create_subprocess_shell -> |
| 8 | Bash | Inspect each rules.py commit and the bandit severity setting | == fb48ab3 2026-09-09 1 file changed, 85 insertions(+), 11 deletions(-) == 73193c8 2026-09-09 1 file changed, 141 insertions(+) == 6cf3baf 2026-09-09 1 file cha |
| 9 | Bash | Read the stated threat model in the design docs and guardian package | docs/blueprint/02-system-architecture.md:59:\| 08 \| Execution \| `simorgh/execution/` \| 2 \| Tool registry and invocation, sandboxes, file/git/shell/web adapters;  |
| 10 | Bash | Read the run_python_sandboxed implementation |  exactly that (loader gate, 2026-09-08). Across 12 cores the same suite takes 57s with the identical pass/fail result. It is a separate-process split, not threa |
| 11 | Bash | Run bandit on the bypass payloads to see severity levels | a.py B606 LOW Starting a process without a shell. a.py B607 LOW Starting a process with a partial executable path d.py B605 LOW Starting a process with a shell: |
| 12 | Bash | Count denylist commits, list secret key names on the machine, check auto-approve wiring | == config.py (denylist home) 94f1267 A task Sim starts from a chat is Sim's, not the person's 73193c8 Guardian rules for the new tool surface, and files that ar |
| 13 | Bash | Check how shell proposals get approved and whether untrusted inputs reach the model | 15: architectural constraint. It is declared `irreversible`, so 16: `ReversibilityRule` decides: with `irreversible_requires_human` set 187: reversibility = "ir |
| 14 | Bash | Check denylist scope, shell environment inheritance, and which secret names live on the machine | 6:376- code = _code_text(proposal) 7:377- if code is None: 9:379- scan_text = code 10:380- # `run_shell`/`run_python_sandboxed` also carry `code`, but name 13:3 |
| 15 | Bash | Confirm shell env inheritance, which proposals the denylist scans, and where secrets live | 7: env = _child_env() 10: env["GIT_TERMINAL_PROMPT"] = "0" 11: env["DEBIAN_FRONTEND"] = "noninteractive" 26: timeout=timeout, stdin=subprocess.DEVNULL, env=env, |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The factual core holds and is in one place actually understated; the framing and the recommendation are where it goes wrong.

VERIFIED: 13 denylist regexes and 32 shell refusals (counted by importing DEFAULT_DENYLIST and DEFAULT_SHELL_REFUSALS). An offline re.search of every payload the finding names -- os.execvp, os.spawnlp, os.fork, asyncio.create_subprocess_shell, multiprocessing, importlib.import_module, a chr/concat getattr -- passes all 13 regexes; curl, ssh and `python3 -c "import os; os.system(...)"` pass all 32 shell refusals. Bandit (installed) rates every one of those payloads LOW (B606/B607/B605/B602/B404) and the floor is HIGH (config.py:114, rules.py:518), so none is denied. The finding's own evidence "os.popen denied (B605)" is wrong for a literal argument: B605 is LOW when the string is a literal, so os.popen passes too -- the gap is slightly wider than claimed. 9 commits on rules.py since 2026-09-07 is exact; about 5 of them close observer-found bypasses (f28ae3d, 571d62e, 6025bfe, 6919616, fb48ab3), two add new rules (6cf3baf bandit, 73193c8 new tool surface). config.py's denylist table has two more dedicated gap-closing commits (ad11e07, f28ae3d). shellcheck is not installed, so ShellcheckRule abstains (rules.py:589-590). There is no OS confinement anywhere: grep for sandbox-exec/seatbelt/firejail/bwrap in simorgh/ returns nothing, and run_python_sandboxed (tools.py:1017-1051) is `python -I`, env={}, temp cwd, rlimits -- no filesystem or network restriction, so it can read ~/.ssh/id_rsa and ~/.simorgh/secrets.toml (which names REOLINK_PASSWORD, RING_TOKEN, SIM_API_TOKEN) and open a socket. run_shell inherits the user's environment (_child_env, shell.py:206-225).

WHERE THE FINDING IS WRONG OR DISPROPORTIONATE: (1) It argues against a claim nobody makes. shell.py:17-27 and the RunPythonSandboxedTool docstring state the threat model is the model's accidents (typo'd rm -rf, hallucinated loops), and the actual gate for run_shell is ReversibilityRule escalating to a human (rules.py:738-739). For that threat model, a short regex list as a linter is proportionate and does its job; the extension treadmill was ~5 commits inside a 3-day observer wave, which is this project's chosen QA method, not an ongoing tax. (2) The recommendation -- sandbox-exec profiles per tool, or a separate user account -- would move the maintenance treadmill into a worse place. sandbox-exec is deprecated by Apple with an undocumented profile language, and the tools that spawn subprocesses legitimately need HA/RTSP/Cast network, git worktrees, npm/pip, ffmpeg and the repo checkout; per-tool profiles across ~50 tools is far more work than the 13 regexes, and a wrong profile fails silently (EPERM inside a child), which is exactly the unconnected-wire bug shape the project already suffers from. (3) "Makes findings 2, 4 and most of 3 moot" is unverifiable from here.

WHAT SURVIVES, and why the severity should stay medium rather than drop: the accident-only threat model is undermined by two facts the finding does not spell out. Untrusted text reaches the code-authoring model through web_fetch/websearch and the Telegram/WhatsApp channels (interface/config.py:98-115), so prompt injection is a real path; and sim.sh auto-approve (config.py:155-157, default since 2026-09-07) removes the human gate that the shell tool's own docstring names as the thing making it "a tool rather than a hole". With both true, a single injected snippet can exfiltrate the family's camera, Ring and ssh credentials with no rule in the way. That is category (b): the design (Guardian sees every call, a human approves the irreversible) is right; the implementation as configured today has no boundary under it. The proportionate fix is far smaller than the finding's: give the one tool whose contract literally promises isolation ("isolated ... no repo access", tools.py:1019-1024) a single seatbelt profile around its one exec (deny default, read the temp workdir, no network) -- roughly 20 lines -- and either restore irreversible_requires_human for run_shell alone or allowlist run_shell to a fixed set of commands. Keep the denylist as the linter it already says it is.

### evidence

- simorgh/guardian/config.py:46-79 -- DEFAULT_DENYLIST, 13 entries (verified: `python3 -c` import prints `denylist entries: 13 shell refusals: 32`)
- simorgh/execution/shell.py:53-118 -- DEFAULT_SHELL_REFUSALS, 32 entries; shell.py:17-27 docstring: 'Not an attempt at a security boundary -- a shell has no such thing ... a guard against the specific class of accident'
- Offline regex test of the payloads against DEFAULT_DENYLIST: os.execvp, os.spawnlp, os.fork, asyncio.create_subprocess_shell, multiprocessing, importlib.import_module, os.popen, concat-getattr -> all 'passes denylist'; curl -o && exec, ssh, `python3 -c "import os; os.system('id')"`, rm -rf /opt|/Library|/Volumes/x -> all 'passes refusals'
- `bandit -q -f json -r <payload dir>` output: a.py B606 LOW, a.py B607 LOW, d.py B605 LOW (os.popen with a literal), e.py B602 LOW (subprocess shell=True literal), e.py B404 LOW; floor is HIGH -- simorgh/guardian/config.py:114 and simorgh/guardian/rules.py:518 `_SEVERITY_RANK.get(...static_analysis_min_severity..., 3)` -- so none denied, including os.popen, contrary to the finding's 'os.popen denied' line
- `git log --oneline --since=2026-09-07 -- simorgh/guardian/rules.py | wc -l` -> 9; messages: fb48ab3 'Make Guardian see a command it was blind to', 6025bfe 'Fix three Guardian bypasses', 6919616 'Close a Guardian write-detection gap', f28ae3d 'Close the sandbox escape', 571d62e 'Fix two bugs in fixes I shipped this morning', b8adbf7 'Round 6', vs additions 6cf3baf 'Add bandit', 73193c8 'rules for the new tool surface'; config.py (denylist home) also has ad11e07 'Close two DenylistRule gaps: bare exec() and os.setuid/setgid family'
- `which shellcheck bandit sandbox-exec` -> shellcheck not found; /opt/homebrew/anaconda3/bin/bandit; /usr/bin/sandbox-exec. rules.py:589-590 `if not shellcheck_available(): return Decision('abstain', ...)`
- `grep -rn 'sandbox-exec\|seatbelt\|firejail\|bwrap' simorgh/ --include='*.py'` -> no output: no OS confinement layer exists
- simorgh/execution/tools.py:1017-1051 RunPythonSandboxedTool: docstring promises 'isolated ... no repo access'; implementation is `[sys.executable, '-I', script]`, `cwd=workdir, env={}`, `preexec_fn=_apply_rlimits(...)` (RLIMIT_CPU/AS/CORE only, tools.py:1000-1012) -- no filesystem or network restriction
- simorgh/execution/shell.py:206-225 -- `env = _child_env()` then `subprocess.run(..., env=env)`: run_shell inherits the user's environment; reversibility = 'irreversible' (shell.py:187)
- simorgh/guardian/rules.py:738-739 -- `if ctx.config.irreversible_requires_human: return Decision('escalate', ...)`; simorgh/guardian/config.py:155-157 -- SIMORGH_GUARDIAN_AUTO_APPROVE env flips irreversible_requires_human; memory notes sim.sh sets it since 2026-09-07
- ~/.simorgh/simorgh.toml:19 `secrets = ["vault:*", "SIM_API_TOKEN", "REOLINK_HOST", "REOLINK_USERNAME", "REOLINK_PASSWORD", "RING_TOKEN", "RING_USERNAME"]`; ~/.simorgh/secrets.toml exists; ~/.ssh/id_rsa exists -- readable by any unconfined child
- simorgh/interface/config.py:98-115 -- telegram_allowed / whatsapp_allowed channels feed the model; web_fetch/websearch tools exist in simorgh/execution/ -- untrusted text reaches the code-authoring model
- simorgh/guardian/rules.py:352-366 _code_text docstring -- the 2026-09-08 bypass where run_shell's `command` arg was invisible to DenylistRule/ImmunityRule, confirming the pattern of observer-found string gaps

**severity adjustment:** keep

**corrected claim:** The 13 regexes (guardian/config.py:46-79), 32 shell refusals (execution/shell.py:53-118) and bandit-at-HIGH do not form a code-payload boundary and were never claimed to: every payload the finding names passes them, and so does os.popen with a literal (bandit B605 LOW), curl/ssh, and `python3 -c` through run_shell. About five of the nine rules.py commits since 2026-09-07 closed observer-found string gaps. The list is proportionate for the accident-only threat model its authors wrote down, and per-tool sandbox-exec profiles or a separate user account would cost more upkeep than the regexes for ~50 tools that legitimately need network, git and the repo. What is genuinely wrong is narrower and category (b): run_python_sandboxed promises isolation (tools.py:1019-1024) but delivers only rlimits and env={} -- it can read ~/.ssh/id_rsa and ~/.simorgh/secrets.toml and open sockets -- and sim.sh's auto-approve removes the human gate that shell.py:17-27 names as the thing making run_shell a tool rather than a hole, while Telegram/WhatsApp/web_fetch feed untrusted text to the same model. Fix the one isolating tool with a single deny-default seatbelt profile and restore human approval (or a command allowlist) for run_shell; keep the denylist as the linter it already says it is and stop extending it.

