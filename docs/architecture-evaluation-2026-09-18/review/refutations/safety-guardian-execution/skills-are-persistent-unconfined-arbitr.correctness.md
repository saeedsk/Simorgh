# refute:correctness:Skills are persistent, unconfined arbitr

*Workflow: review · Phase: Refute · Agent id: `abd24bfaab3a8f196` · Tool calls: 9*

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
    "title": "Skills are persistent, unconfined arbitrary code labelled 'reversible', so they never reach the human even with auto-approve off",
    "kind": "wrong-design",
    "severity": "high",
    "claim": "`apply_skill` and every `skill:<name>` tool are `reversibility=\"reversible\"` and therefore auto-allowed in guarded mode regardless of `irreversible_requires_human`; the skill runs `python -I` with rlimits, empty env, cwd=repo_root and no filesystem or network confinement, and the denylist/bandit scan on `apply_skill` misses `os.execvp`, `asyncio.create_subprocess_shell` and `pathlib.write_text` to a concatenated path.",
    "evidence": [
      "simorgh/execution/tools.py:2385-2388 ApplySkillTool `reversibility = \"reversible\"`; tools.py:2775-2776 SkillTool `reversibility = \"reversible\"`; tools.py:2800-2815 subprocess.run with `cwd=str(self._config.repo_root), env={}` and the comment 'A skill already runs as arbitrary Python with no filesystem confinement'",
      "Offline pipeline with DEFAULT Config (irreversible_requires_human=True, bandit installed): `approved apply_skill {... os.execvp('/bin/sh', ['sh', '-c', text]) ...}`, `approved apply_skill {... asyncio.create_subprocess_shell(t) ...}`, `approved apply_skill {... pathlib.Path('simorgh/gu' + 'ardian/rules.py').write_text(text) ...}`, `approved skill:helper {'text': 'cat ~/.simorgh/secrets.toml'}`; only `os.popen` was caught (bandit B605)",
      "simorgh/execution/service.py:776-785 lazy-loads any `skill:<name>` from `simorgh_skills/<name>.py` on demand after a restart, and `_load_skill` re-reads the file from disk (service.py:634-650), so a `run_shell` edit to a skill file is executed on next call"
    ],
    "why_it_matters": "The 'reversible' label is what the pipeline actually gates on, and it is assigned by the tool author's guess, not by what the payload does. A skill is the one tool that survives restarts, so this is the persistence channel.",
    "recommendation": "Label `apply_skill` and `skill:*` irreversible (they are), and give SkillTool the same confinement as the rest (sandbox-exec profile, no network). Longer term, drop `reversibility` as a per-tool constant and make it a per-proposal function of (tool, args), which the home tools already do -- generalise `to_action_payload`'s `home_call` special case into a table of classifiers.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read ApplySkillTool and SkillTool definitions |  f"what to put there instead\n{_REPLACE_MARK}") for index, (find_text, _) in enumerate(blocks, start=1): if not find_text.strip(): return [], f"block {index}'s  |
| 2 | Bash | Find guardian gating on reversibility and skill lazy-load in service | simorgh/guardian/api.py:25: reversibility: str simorgh/guardian/api.py:40: reversibility: str simorgh/guardian/config.py:103: irreversible_requires_human: bool  |
| 3 | Bash | Inspect guardian rules for skill handling, denylist and bandit scanning |  r"\|open\([^)]*['\"][waxWAX][+b]?['\"]" r"\|\.write\w*\(\|\.writelines\(\|\.unlink\(\|\.remove\(\|shutil\.(move\|copy\|rmtree)" r"\|os\.(remove\|unlink\|rename\|replace)"  |
| 4 | Bash | Read pipeline evaluator, denylist defaults, and check known-findings docs for skill mentions |  ModeRule(), ProtectedRule(), ScopeRule(), DenylistRule(), StaticAnalysisRule(), ShellcheckRule(), PackageRule(), GrantRule(), ImmunityRule(), BudgetRule(), Rev |
| 5 | Bash | Find pipeline entry point, Proposal/DecisionContext shapes, denylist defaults, and bandit availability | simorgh/guardian/pipeline.py:1:"""Runs `rules.DEFAULT_PIPELINE` in order and folds the per-rule simorgh/guardian/pipeline.py:19: async def decide(self, proposal |
| 6 | Bash | Read pipeline test fixtures and Posture shape to build an offline reproduction | """`Pipeline.decide`'s own control flow (09-guardian.md section 5.1): deny always wins and short-circuits; an escalate is remembered but evaluation continues; c |
| 7 | Bash | Reproduce the offline guardian pipeline verdicts for the cited payloads; check how reversibility is set per proposal and live config | Traceback (most recent call last): File "/private/tmp/claude-501/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/scratchpad/repro.py", line 2, in < |
| 8 | Bash | Run the offline reproduction with the repo on the path; check how skill:* proposals get their reversibility and the live auto-approve settin | irreversible_requires_human True bandit True approved apply_skill [] import os \| def run(text): \| os.execvp('/bin/sh',['sh','-c', approved apply_skill [] import |
| 9 | Bash | Check whether Guardian trusts the proposal's reversibility and how home_call gets per-call classification |  # (`security.ReplayGuard` beside it evicts at 10,000). if len(self._decided) >= _MAX_DECIDED: for stale in list(self._decided)[: max(1, _MAX_DECIDED // 10)]: s |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line was read and matches the claim as of today's checkout. ApplySkillTool (simorgh/execution/tools.py:2385-2388) and SkillTool (tools.py:2775-2776) both declare `reversibility = "reversible"`, and the orchestration-side `_TOOL_POLICY` table (simorgh/orchestration/tools.py:74) tags `apply_skill` reversible too; a loaded skill re-registers itself as reversible through `tool.registered` (execution/service.py:646-650), which `register_tool_policy` (orchestration/tools.py:630-636) copies into the same table. Guardian builds `ToolInfo` from the proposal's own declared reversibility (guardian/service.py:520-525), and `ReversibilityRule` (guardian/rules.py:721-740) allows anything "reversible" in guarded mode unconditionally, so `irreversible_requires_human` (guardian/config.py:103, default True) is never consulted for these tools. SkillTool.run (tools.py:2800-2815) spawns `python -I` with `cwd=repo_root`, `env={}`, rlimits only, and the in-code comment explicitly says "no filesystem confinement". `_load_skill` re-reads the file from disk on each call (service.py:634-650) and the executor lazy-loads any `skill:<name>` from `skill_dir/<name>.py` after a restart (service.py:776-785). I reproduced the offline pipeline claim with `Pipeline(DEFAULT_PIPELINE)` under default `Config()` with bandit 1.9.4 installed: the `os.execvp`, `asyncio.create_subprocess_shell`, and concatenated-path `pathlib.write_text` payloads to `apply_skill` were all `approved`, `skill:helper {'text': 'cat ~/.simorgh/secrets.toml'}` was `approved`, and only the `os.popen` payload was denied (bandit B605). The recommendation's premise about `home_call` is also true: orchestration/tools.py:122-131 and to_action_payload (tools.py:693-694) special-case `home_call` to compute reversibility per call. This is not in the known-findings list (the closest known item, the internal comment at guardian/rules.py:219-228, concerns `run_python_sandboxed`'s code argument being text-scanned; the `skill:*` invocation path carries only args, not code, so that mitigation never applies to it). Classification as wrong-design is fair: the per-tool constant label is the design flaw, and the persistence-across-restart property of skills is what makes it high rather than medium.

### evidence

- simorgh/execution/tools.py:2385-2388: `name = "apply_skill"` ... `reversibility = "reversible"`
- simorgh/execution/tools.py:2775-2776: SkillTool `read_only = False` / `reversibility = "reversible"`
- simorgh/execution/tools.py:2800-2815: `[sys.executable, "-I", str(driver), json.dumps(args)] ... cwd=str(self._config.repo_root), env={}, timeout=timeout, preexec_fn=preexec` with comment 'A skill already runs as arbitrary Python with no filesystem confinement beyond the CPU/memory rlimits below'
- simorgh/guardian/rules.py:721-740 ReversibilityRule: `if r == "reversible": ... return Decision("allow", self.layer)` before `irreversible_requires_human` is ever checked
- simorgh/guardian/service.py:502-525: Proposal built with `reversibility=p["reversibility"]` and `ToolInfo(... reversibility=proposal.reversibility)` -- Guardian trusts the declared label
- simorgh/orchestration/tools.py:74 `"apply_skill": ("reversible", False)`; tools.py:630-636 register_tool_policy copies a skill's registered reversibility into _TOOL_POLICY
- simorgh/execution/service.py:646-650: tool.registered payload `"reversibility": tool.reversibility` for every loaded skill; service.py:776-785 lazy-loads `skill:<name>` from `{skill_dir}/{name}.py` on an approved action; service.py:634-650 `_load_skill` re-reads source from disk each time
- Command: `PYTHONPATH=/Users/saeed/ws/Simorgh python3 scratchpad/repro.py` (Pipeline(DEFAULT_PIPELINE), Config(), posture guarded) output: `irreversible_requires_human True bandit True` / `approved  apply_skill [] import os | def run(text): |     os.execvp('/bin/sh',['sh','-c',` / `approved  apply_skill [] import asyncio | ... asyncio.cr` / `approved  apply_skill [] import pathlib | ... pathlib.Path('simorgh/gu'+` / `denied static_analysis apply_skill ['denied: bandit B605 (high severity, line 3): Starting a process with a shell...']` (os.popen) / `approved  skill:helper [] cat ~/.simorgh/secrets.toml`
- simorgh/guardian/config.py:46-71 DEFAULT_DENYLIST has patterns for os.system, subprocess.(Popen|run|call), eval, exec, __import__('os'), ctypes -- none for os.exec*, asyncio.create_subprocess_*, or pathlib write_text
- simorgh/orchestration/tools.py:122-131 and 693-694: `home_call`'s class 'is computed PER CALL by contracts/home/policy.py' and `to_action_payload` raises it to irreversible -- confirms the recommendation's premise that per-proposal classification already exists for one tool
- python3 -c 'import bandit; print(bandit.__version__)' -> 1.9.4 (bandit is installed, so the bypass is not a missing-dependency artefact)

**severity adjustment:** keep

