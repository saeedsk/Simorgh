# refute:proportionality:Five of eleven mechanical checks can nev

*Workflow: review · Phase: Refute · Agent id: `a346fcf952fefdaec` · Tool calls: 7*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "testing-observability-process". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 2 | Bash | Read check applies() conditions, rigor, config and service | === invariants 28: def applies(self, req: VerifyRequest) -> bool: 29- return bool(req.subject.get("path")) and ( 30- req.subject.get("candidate") or req.subject |
| 3 | Bash | Find all verify-request publishers, check registry, and tests | === publishers of VERIFY_REQUESTED (eval):1: no matches found: --include=*.py === kind read in service 46:def _guardian_kind(kind: str) -> str: 47: # guardian.r |
| 4 | Bash | Find verify publishers, reversibility senders, and probe live ledger verify streams | === publishers of VERIFY_REQUESTED simorgh/learning/service.py:40: topics.LEARN_SKILL_ACQUIRED, topics.ACTION_PROPOSED, topics.VERIFY_REQUESTED, topics.MEMORY_S |
| 5 | Bash | Inspect learning verify publisher, live stream shapes, and rigor test | === learning service verify publish reversibility: str, rationale: str, task_id: str) -> None: await self._publish(topics.ACTION_PROPOSED, { "action_id": action |
| 6 | Bash | Extract mechanical check names from live verify result events | topics Counter({None: 350}) keys Counter({'checklist': 350, 'mechanical': 350, 'task_id': 350, 'trajectory': 350, 'verdict': 350, 'verification_id': 350, 'feedb |
| 7 | Bash | Confirm mechanical check names in live results and whether prior reviews already covered the sibling checks | shapes Counter({'dict': 350}) names Counter({'ledger': 350, 'did_anything': 122, 'trailing_narration': 90, 'syntax': 83, 'full_suite_ran': 62, 'js_syntax': 7, ' |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line was read and matches. The only orchestration-side publisher of VERIFY_REQUESTED is simorgh/orchestration/session.py:1737-1742 and it hardcodes "kind": "task"; the subject blob at session.py:1885-1891 carries description/result/kind/steps/complete_log/subject/written_paths/base_ref/repo_root and nothing else -- grep for "candidate"/"original"/"code:"/"path:" in session.py hits only the git_discard arg at line 864. The other publisher (learning/service.py:204) is the Learning pipeline already known to be unreachable. The five checks' applies() gates require exactly the missing keys or kind=="skill" (invariants.py:28-31, docstring.py:45-48, denylist_immunity.py:21-22, isolated_suite.py:18-19, sandbox_smoke.py:23-28), so none can fire on any real task. rigor.py:22-25 looks up req.kind ("task", absent from _DEFAULT_RIGOR_BY_KIND at config.py:14-22) and req.reversibility (service.py:162 reads subject["reversibility"], which the subject never contains; zero of 350 live verify streams mention it), so max(STANDARD, STANDARD)=STANDARD every time. A probe of the 350 verify:* streams in ~/.simorgh/ledger/streams reproduces the finding exactly: mechanical keys seen are only did_anything 122, trailing_narration 90, syntax 83, full_suite_ran 62, js_syntax 7, render 7 (plus a 'ledger' key); verdicts fail 220 / pass 109 / insufficient_evidence 21. The isolated_suite half is already documented in-code at checks/fullsuiteran.py:1-13 (and a replacement check was built for it), but the four sibling content checks and the inert rigor table are not mentioned in that note or in docs/architecture-audit-2026.md / architecture-review-2026-09-18.html, so this is materially new. On the skeptic lens: this is not over-engineering for one laptop -- the dead checks are the ones that matter most for a self-patching agent (invariants guarding simorgh/guardian/ and simorgh/execution/, Guardian denylist review of candidate code), and the recommendation is proportionate: either a small subject-shape change plus one integration assertion, or deleting ~5 checks, a table and their tests. The cost side is also real at this scale: research tasks configured LIGHT still pay a paid-model checklist at STANDARD. Classification as right-design-undermined is correct; severity kept because a self-modifying system whose only code-content checks never execute is the exact failure class the project's own notes flag.

### evidence

- simorgh/orchestration/session.py:1737-1742 -- VERIFY_REQUESTED payload is {verification_id, task_id, "kind": "task", subject_ref}; session.kind is not sent as the wire kind.
- simorgh/orchestration/session.py:1885-1891 -- subject blob keys: description, result, kind, steps, complete_log, subject, written_paths, base_ref, repo_root; no candidate/code/original/path/reversibility.
- grep -n '"candidate"\|"code":\|"original"\|"path":\|"candidates"\|"reversibility"' simorgh/orchestration/session.py -> only line 864 (git_discard args).
- grep -rn VERIFY_REQUESTED simorgh -> publishers are session.py:1738 and learning/service.py:204 only (Learning pipeline is the already-known dead path).
- simorgh/verification/checks/invariants.py:28-31, docstring.py:45-48, denylist_immunity.py:21-22, isolated_suite.py:18-19 all gate on subject.get("candidate") or subject.get("code"); sandbox_smoke.py:28 `return req.kind == "skill"`.
- simorgh/verification/rigor.py:22-25 `rigor_by_kind.get(req.kind, STANDARD)` / `rigor_by_reversibility.get(req.reversibility, STANDARD)`; config.py:14-22 table has no "task" entry; service.py:162 `reversibility=subject.get("reversibility", "reversible")`.
- simorgh/verification/service.py:171-174 -- FULL rigor only adds isolated_suite, which cannot apply.
- simorgh/verification/checks/__init__.py:13-25 -- ALL_CHECKS has 11 entries.
- Live ledger probe (python over ~/.simorgh/ledger/streams/verify*, 350 streams): mechanical keys = ledger 350, did_anything 122, trailing_narration 90, syntax 83, full_suite_ran 62, js_syntax 7, render 7; verdicts fail 220 / pass 109 / insufficient_evidence 21; `grep -l reversibility` over verify streams -> 0 files.
- simorgh/verification/checks/fullsuiteran.py:1-13 documents only IsolatedSuiteCheck's unreachability; grep for DenylistImmunity/InvariantsCheck/DocstringCheck in docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html, docs/architecture-third-opinion-2026-09-18.md -> no hits.
- tests/simorgh/verification/test_rigor.py:14-40 exercises kinds chat/self_patch/research/plan/mystery with hand-built VerifyRequest objects, never the wire kind orchestration sends.

**severity adjustment:** keep

