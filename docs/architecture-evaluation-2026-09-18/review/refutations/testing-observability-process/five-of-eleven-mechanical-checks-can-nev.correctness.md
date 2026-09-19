# refute:correctness:Five of eleven mechanical checks can nev

*Workflow: review · Phase: Refute · Agent id: `adcac94d2e41f641e` · Tool calls: 9*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "testing-observability-process". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "Five of eleven mechanical checks can never run on the real path, and the rigor table is inert",
    "kind": "right-design-undermined",
    "severity": "high",
    "claim": "Orchestration's verify subject never carries candidate/code/original and always sends wire kind 'task', so denylist_immunity, docstring, invariants, isolated_suite and sandbox_smoke are dead for every human or trial task, and select_rigor resolves every task to STANDARD regardless of the configured patch=FULL / research=LIGHT / skill=FULL table.",
    "evidence": [
      "simorgh/orchestration/session.py:1885-1890 subject keys: `\"description\", \"result\", \"kind\", \"steps\", \"complete_log\", \"subject\", \"written_paths\", \"base_ref\", \"repo_root\"`; grep for '\"candidate\"|\"code\":|\"original\"|\"path\":' in session.py returns only an unrelated git_discard arg at line 864.",
      "simorgh/orchestration/session.py:1741: `\"kind\": \"task\", \"subject_ref\": subject_ref` -- session.kind (patch/skill/research) is not the wire kind.",
      "checks/invariants.py:28-31, checks/docstring.py:45-48, checks/denylist_immunity.py:21-22, checks/isolated_suite.py:18-19 all require `req.subject.get(\"candidate\") or req.subject.get(\"code\")`; checks/sandbox_smoke.py:28 `return req.kind == \"skill\"`.",
      "verification/rigor.py:22-25 with config.py:14-26: `rigor_by_kind.get(\"task\", Rigor.STANDARD)` -- 'task' is not in the table; service.py:162 `reversibility=subject.get(\"reversibility\", \"reversible\")` -- never sent, so STANDARD both ways; service.py:172-174 FULL only adds isolated_suite, which cannot apply.",
      "Live ledger probe over 349 verify streams: only ('did_anything','full_suite_ran','js_syntax','render','syntax','trailing_narration') ever appear as mechanical results; verdicts `fail 220 / pass 109 / insufficient_evidence 21`.",
      "checks/fullsuiteran.py:5-13 already documents that IsolatedSuiteCheck never fires for this reason; the four siblings with the same applies() condition were not noticed."
    ],
    "why_it_matters": "This is the verification-side consequence of the already-known dead Learning pipeline, and it is materially larger than 'one tool is not registered': the subsystem's design (11 checks, cheapest-first, reversibility-weighted rigor) is what the docs and the tests describe, but the running system is 6 checks at one rigor. Research tasks pay a model call for a checklist they were configured to skip; skills never get the sandbox smoke; and tests/simorgh/verification/test_invariants.py and test_docstring.py assert the shape of code the system never executes -- the exact failure mode the project's own notes describe.",
    "recommendation": "Pick one of two honest states. Either (a) make the checks reachable: have _put_verify_subject send session.kind as the wire kind and, for each written path, read the worktree file into subject['candidates'][path] (the worktree is already at session.worktree), and rewrite the four content checks to iterate written paths; or (b) delete the five dead checks, the rigor table and their tests, leaving the six that run. Add one integration assertion that every check in ALL_CHECKS has fired at least once against the subject shape orchestration actually sends.",
    "confidence": 0.92
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read the verify subject construction in session.py |  # the way it is honoured between ordinary steps. if self._is_cancelled(session.task_id): return Outcome("failed", reason=CANCELLED_REASON, result_summary=text) |
| 2 | Bash | Read the applies() conditions of the five checks | == grep session.py candidate/code/original == 864: call = {"tool": "git_discard", "args": {"path": path, "created": path in session.created}} == checks applies( |
| 3 | Bash | Read rigor, config, service, and find all verify publishers | Exit code 1 == rigor.py == """`select_rigor` (docs/blueprint/subsystems/10-verification.md section 5.2): `max(by_kind[kind], by_reversibility[reversibility])`,  |
| 4 | Bash | Check ALL_CHECKS, other publishers, config sources, and session.kind usage | == ALL_CHECKS list == from .denylist_immunity import DenylistImmunityCheck from .didanything import DidAnythingCheck from .docstring import DocstringCheck, docs |
| 5 | Bash | Check prior reviews, service kind fallback, env override, Learning publisher | == prior reviews mention? == docs/architecture-audit-2026.md:11:4. **Decoupled Asynchronous Bus:** Communication via `simorgh/bus/` using strongly-typed message |
| 6 | Bash | Locate ledger and read applies() of the six live checks | blobs heads idem index.json LOCK snapshots streams == verify result files == == sandbox_smoke_kinds default == 53: sandbox_smoke_kinds: tuple[str, ...] = ("skil |
| 7 | Bash | Probe ledger verify streams for check names and request kinds | 350 verify%3A00a322a83957.jsonl verify%3A01a1a3cfc223.jsonl verify%3A01e4fa17b7d0.jsonl == mechanical check names across verify streams == streams 350 results 0 |
| 8 | Bash | Inspect the shape of one verify stream record | {"causation_id":null,"idempotency_key":null,"payload":{"checklist":[{"answer":"yes","evidence":"YES\n\nThe extracted assignment list pairs \"Fred Rebecca,\" sho |
| 9 | Bash | Recount ledger verdicts by record type and find real task kinds | streams 350 verdict records 350 types {'verdict': 350} verdicts {'fail': 220, 'pass': 109, 'insufficient_evidence': 21} mechanical names [('did_anything', 122), |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line was read and matches. (1) simorgh/orchestration/session.py:1741 publishes VERIFY_REQUESTED with the literal wire kind "task"; session.kind (patch/skill/research from interface/dispatch.py:266-296, planning/intake.py, reflection/service.py:387) only travels inside the subject blob (session.py:1885), and verification/service.py:141,160 builds VerifyRequest from payload["kind"], never from subject["kind"] (grep for subject.get("kind") in service.py returns nothing). (2) The subject blob (session.py:1885-1890) carries description/result/kind/steps/complete_log/subject/written_paths/base_ref/repo_root only; grep for "candidate"/"code":/"original"/"path": in session.py hits only the git_discard arg at line 864. (3) applies() in invariants.py:28-31, docstring.py:45-48, denylist_immunity.py:21-22, isolated_suite.py:18-19 all require subject candidate/code (and path/original), so they are false for every orchestration-sent request; sandbox_smoke.py:28 requires req.kind == "skill", which the wire never says. (4) rigor.py:22-25 does rigor_by_kind.get("task", STANDARD) and config.py:14-26 has no "task" key; service.py:162 reads reversibility from the subject with default "reversible" -> STANDARD; service.py:172-174 at non-FULL only removes isolated_suite, which cannot apply anyway. Net: rigor selection has no observable effect on any orchestration-driven task. (5) Live ledger probe over ~/.simorgh/ledger/streams/verify* (350 streams, 350 verdict records) reproduces the numbers exactly: verdicts fail 220 / pass 109 / insufficient_evidence 21; mechanical names seen are only did_anything, full_suite_ran, js_syntax, render, syntax, trailing_narration (plus a non-check 'ledger' key). None of the five checks has ever fired. (6) checks/fullsuiteran.py:1-13 documents this for isolated_suite alone. The only other VERIFY_REQUESTED publisher is learning/service.py:204 via the PatchPipeline, which is unreachable (self_patch.draft never registered — in the known list). The known-findings list covers the dead Learning tool but not the verification-side consequence (five dead checks, inert rigor table); prior review docs do not mention rigor, isolated_suite, denylist_immunity, sandbox_smoke or invariants. The 'right-design-undermined' classification is apt: the check/rigor design is coherent, but the one live producer sends a subject shape the design never anticipated. Minor imprecision: 350 verify streams, not 349.

### evidence

- simorgh/orchestration/session.py:1738-1742 — payload {"verification_id":..., "task_id":..., "kind": "task", "subject_ref": subject_ref}
- simorgh/orchestration/session.py:1884-1890 — subject blob keys: description, result, kind, steps, complete_log, subject, written_paths, base_ref, repo_root
- grep -nE '"candidate"|"code":|"original"|"path":|"reversibility"' simorgh/orchestration/session.py -> only line 864 (git_discard args)
- simorgh/verification/service.py:141 kind = payload["kind"]; :158-162 VerifyRequest(kind=kind, reversibility=subject.get("reversibility", "reversible")); grep for subject.get("kind") in service.py -> no hits
- simorgh/verification/rigor.py:22-25 by_kind = config.rigor_by_kind.get(req.kind, Rigor.STANDARD); simorgh/verification/config.py:14-27 table has chat/research/project_child_readonly/skill/patch/self_patch/plan, no 'task'
- simorgh/verification/service.py:171-174 applicable = [c for c in ALL_CHECKS if c.applies(req)]; at none/light/standard only isolated_suite is filtered
- simorgh/verification/checks/invariants.py:28-31, docstring.py:45-48, denylist_immunity.py:21-22, isolated_suite.py:18-19 — applies() all require req.subject candidate or code; sandbox_smoke.py:28 return req.kind == "skill"
- simorgh/verification/checks/fullsuiteran.py:4-13 — docstring: IsolatedSuiteCheck never fires because _put_verify_subject never populates candidate/code
- Ledger probe (python over ~/.simorgh/ledger/streams/verify*): streams 350, verdict records 350; verdicts {'fail': 220, 'pass': 109, 'insufficient_evidence': 21}; mechanical names [did_anything 122, full_suite_ran 62, js_syntax 7, ledger 350, render 7, syntax 83, trailing_narration 90]
- grep -rn VERIFY_REQUESTED simorgh --include='*.py' -> only publishers: orchestration/session.py:1738 and learning/service.py:204 (PatchPipeline, unreachable: self_patch.draft not registered)
- grep -i 'rigor|isolated_suite|denylist_immunity|sandbox_smoke|invariants' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md -> no matches (not previously reported)
- simorgh/interface/dispatch.py:266,280,296 — human tasks are submitted with kind patch/skill/research, which orchestration then relabels 'task' on the verify wire

**severity adjustment:** keep

