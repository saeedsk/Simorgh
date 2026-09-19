# refute:proportionality:Skills are persistent, unconfined arbitr

*Workflow: review · Phase: Refute · Agent id: `acc265f7490f51355` · Tool calls: 16*

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
| 2 | Bash | Read skill loading and guardian reversibility gating |  tool's captured source: `apply_skill` rewrites a skill's file in place and then calls right back in here (`_on_approved`'s `LEARN_SKILL_ACQUIRED` re-publish, s |
| 3 | Bash | Read guardian rules relevant to skills and reversibility |  r"\|open\([^)]*['\"][waxWAX][+b]?['\"]" r"\|\.write\w*\(\|\.writelines\(\|\.unlink\(\|\.remove\(\|shutil\.(move\|copy\|rmtree)" r"\|os\.(remove\|unlink\|rename\|replace)"  |
| 4 | Bash | Read ProtectedRule, DenylistRule, StaticAnalysisRule and pipeline order | class ProtectedRule: name = "protected" layer = "protected" async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision: # Protection is abou |
| 5 | Bash | Locate pipeline runner, proposal types, and to_action_payload reversibility logic | simorgh/guardian/api.py:20:class Proposal: simorgh/guardian/api.py:37:class ToolInfo: simorgh/guardian/api.py:50:class DecisionContext: simorgh/guardian/rules.p |
| 6 | Bash | Read pipeline runner, posture, default denylist, and orchestration tool policy | @dataclass(frozen=True) class Decision: kind: str # allow \| deny \| escalate \| abstain layer: str reasons: tuple[str, ...] = () @dataclass(frozen=True) class Ver |
| 7 | Bash | Read pipeline decide, guardian home_call recompute, skill pipeline proposal, and skill dir contents |  async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision: ... ---- ---- 4:132: apply_tool = "apply_source_patch" if self.kind == "patch"  |
| 8 | Bash | Find Pipeline class, candidate_ref handling, and existing skill | simorgh/guardian/pipeline.py:15:class Pipeline: ---- def run(path="."): """List a directory's entries. Returns a dict with name, dirs, files, and errors. Never  |
| 9 | Bash | Read Pipeline.decide | """Runs `rules.DEFAULT_PIPELINE` in order and folds the per-rule Decisions into one Verdict (09-guardian.md section 5.1): the first deny wins outright; otherwis |
| 10 | Bash | Run Guardian pipeline offline against the claimed skill payloads | Traceback (most recent call last): File "/private/tmp/claude-501/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/scratchpad/repro.py", line 3, in < |
| 11 | Bash | Run repro with repo on PYTHONPATH | irreversible_requires_human = True mode = guarded bandit = True execvp rev=reversible -> approved () execvp rev=irreversible -> needs_human reversibility ('irre |
| 12 | Bash | Compare skill tools against sandbox tools, confinement, and live auto-approve config | 15: "apply_skill": ("reversible", False), 16: "git_commit": ("reversible", False), 24: "run_shell": ("irreversible", True), 25: # Each changes this machine and  |
| 13 | Bash | Read full tool policy table, auto-approve wiring, sandbox tool labels, and skill profile binding |  # Guardian auto-allows them in guarded posture; ProtectedRule and # DenylistRule still run first and still deny outright. "apply_source_patch": ("reversible",  |
| 14 | Bash | Check run_python label, auto-approve wiring, and skill exposure to profiles |  "self_map": ("read_only", False), "web_fetch": ("read_only", True), "web_search": ("read_only", True), "render_page": ("read_only", True), "browse_page": ("rev |
| 15 | Bash | Check auto-approve default in sim.sh, protected subjects, candidate_ref wiring, and whether run_python_sandboxed approves the same payloads | ---- 87: protected_subjects: tuple[str, ...] = DEFAULT_PROTECTED_SUBJECTS 88- denylist: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_DENYLIST) |
| 16 | Bash | Check live auto-approve state, guardian toml, tests touching apply_skill reversibility, and the code-arg key list | ---- ---- tests/simorgh/interface/test_live_status.py tests/simorgh/learning/test_pipeline.py tests/simorgh/verification/test_replace_in_file_is_a_write.py test |

## Structured reply

**refuted:** False

**verdict:** partly-true

**corrected claim:** `apply_skill` and every `skill:<name>` tool are hard-coded `reversibility = "reversible"` and are auto-allowed in the default guarded posture; the Guardian's install-time scan (denylist + bandit) misses os.execvp, asyncio.create_subprocess_shell and concatenated-path writes, and a skill's invocation arguments are never scanned at all. This is a real label inconsistency (run_shell is gated as irreversible, a skill wrapping a shell is not), but it is NOT the unique persistence channel and not a wrong design: `run_python_sandboxed` is also "reversible", in the CHAT profile, equally unconfined, and approves the identical payloads including a direct write of simorgh_skills/evil.py and a LaunchAgent plist. The root problem is the already-known absence of OS-level confinement for all three code runners; relabelling skills alone would gate nothing that run_python_sandboxed does not already give away, and "the same confinement as the rest" cannot be applied because no sandbox-exec/seatbelt confinement exists anywhere in simorgh/execution.

**reasoning:** The factual core reproduces exactly. Running Guardian's DEFAULT_PIPELINE offline with `Config()` defaults (irreversible_requires_human=True, mode=guarded, bandit 1.9.4 installed) against apply_skill proposals: os.execvp -> approved, asyncio.create_subprocess_shell -> approved, pathlib.Path('simorgh/gu'+'ardian/rules.py').write_text -> approved, os.popen -> denied (bandit B605), plain 'simorgh/guardian/rules.py' -> denied (protected). A `skill:helper` call with text='cat ~/.simorgh/secrets.toml' -> approved (skill args are not in _CODE_ARG_KEYS=("code","command"), rules.py:116, so invocation is never inspected). The labels are constants (tools.py:2388, 2776); SkillTool runs `python -I` with env={}, cwd=repo_root, rlimits only (tools.py:2800-2815, and the code's own comment admits "no filesystem confinement"). Lazy load from simorgh_skills/<name>.py after restart is at service.py:776-785; _load_skill re-reads disk at 634-650. ~/.simorgh/simorgh.toml has no [guardian] table and sim.sh does not set SIMORGH_GUARDIAN_AUTO_APPROVE, so defaults are the live posture.

Where the skeptic lens cuts it down: (1) Uniqueness is overstated. orchestration/tools.py:48 labels run_python_sandboxed "reversible"; profiles.py:20 binds it in CHAT; rules.py:219-228 states it has "NO filesystem confinement". My second repro shows run_python_sandboxed approves os.execvp, a direct write of simorgh_skills/evil.py (no apply_skill needed, and offered_tools at orchestration/tools.py:626 then exposes that skill to every profile), and writing ~/Library/LaunchAgents/x.plist. So persistence and shell-out are already available without skills; the skill channel adds no capability an unconfined sandbox lacks. (2) The recommendation "give SkillTool the same confinement as the rest (sandbox-exec profile, no network)" is inapplicable: grep for sandbox-exec/seatbelt/unshare/firejail across simorgh/execution returns nothing. The rest have no confinement to match. (3) Relabelling apply_skill/skill:* irreversible with the default config would make every skill install and call a human prompt while run_python_sandboxed stays auto-approved; a model will just route through the sandbox tool. To be consistent you would have to relabel run_python_sandboxed/run_js_sandboxed too, which amounts to "no autonomous code execution without a human" and contradicts the creator's explicit loosening (guardian/config.py:90-92) and the self-improving goal. (4) The "wrong-design" framing is off: per-proposal, args-inspecting classification already exists (ProtectedRule/DenylistRule/StaticAnalysisRule), reversibility is documented as a floor, and the code is honest that static scanning of arbitrary Python is unwinnable (rules.py:308 "A path assembled from pieces already defeats the scan"). This is a known limitation of an unconfined sandbox, not a per-tool-constant design error. What remains genuinely new and cheap: skill:* is functionally run_shell (arbitrary code, arbitrary args, offered to every profile) but is labelled below it; labelling skill:* like run_shell ("irreversible", network=True) is a one-line consistency fix. Also worth noting: learning/pipeline.py:134 proposes apply_skill with `candidate_ref` and no `code`, and nothing in simorgh/ outside pipeline.py resolves candidate_ref, so that path is scanned by neither DenylistRule nor bandit (but that pipeline is already flagged as unconnected). Severity should drop from high to medium: the real risk is the shared non-confinement of all code runners, already on record from the 2026-09-08 observer wave, and the skill-specific delta is an inconsistency, not a new attack surface.

### evidence

- simorgh/execution/tools.py:2388 `reversibility = "reversible"` on ApplySkillTool; :2776 same on SkillTool; :2800-2815 subprocess.run([sys.executable, "-I", driver, json], cwd=str(self._config.repo_root), env={}, preexec_fn=rlimits) with comment 'A skill already runs as arbitrary Python with no filesystem confinement'
- simorgh/execution/service.py:776-785 lazy `_load_skill(skill_name, path=f"{skill_dir}/{skill_name}.py")` when approved tool starts with 'skill:'; :634-650 re-reads source from disk via pathsafety.read_source
- Repro (PYTHONPATH=repo python3 scratchpad/repro.py, Config() defaults: irreversible_requires_human=True mode=guarded bandit=True): apply_skill execvp -> approved; asyncio_shell -> approved; pathlib_concat -> approved; popen -> denied static_analysis B605; plain protected path -> denied protected; skill:helper {'text': 'cat ~/.simorgh/secrets.toml'} -> approved
- Repro 2 (scratchpad/repro2.py) run_python_sandboxed with reversibility='reversible': execvp -> approved; write_text('simorgh_skills/evil.py', <execvp skill>) -> approved; write ~/Library/LaunchAgents/x.plist -> approved
- simorgh/orchestration/tools.py:48 `"run_python_sandboxed": ("reversible", False)`; :74 `"apply_skill": ("reversible", False)`; :24 `"run_shell": ("irreversible", True)`; :626 offered_tools appends every registered `skill:*` to every profile
- simorgh/orchestration/profiles.py:20 CHAT profile includes run_python_sandboxed and run_js_sandboxed
- simorgh/guardian/rules.py:116 `_CODE_ARG_KEYS = ("code", "command")` -- skill invocation args (e.g. `text`) are never scanned; :219-228 comment: sandbox 'has rlimits and a temp cwd and NO filesystem confinement'; :308 'A path assembled from pieces already defeats the scan above'
- grep -rn 'sandbox-exec|sandbox_exec|seatbelt|unshare|firejail' simorgh/execution/*.py -> no matches (no confinement exists for 'the rest' to match)
- simorgh/guardian/config.py:103-104 defaults irreversible_requires_human=True, reversible_auto_in_guarded=True; :90-92 creator quote 'more freedom in autonomously working and evolving without too much gate'; ~/.simorgh/simorgh.toml has no [guardian] table; sim.sh contains no AUTO_APPROVE setting
- simorgh/guardian/rules.py:720-741 ReversibilityRule: 'reversible' -> allow in guarded; irreversible -> escalate when irreversible_requires_human
- simorgh/learning/pipeline.py:132-136 proposes apply_skill with args={subject, candidate_ref} and reversibility='reversible' -- no `code` arg, so DenylistRule/StaticAnalysisRule have nothing to scan on that path; grep for candidate_ref elsewhere in simorgh/ finds no resolver

**severity adjustment:** lower

