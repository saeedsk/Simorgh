# refute:correctness:Competence learning records every chat t

*Workflow: review · Phase: Refute · Agent id: `ac50cd4251b8f0329` · Tool calls: 12*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "big-picture-proportionality". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "Competence learning records every chat turn as `unknown`, so 91% of the learning signal is noise",
    "kind": "bug",
    "severity": "high",
    "claim": "learning/outcomes.py derives task_type from the first event of `task:<task_id>`; chat turns get a task_id and a `task.completed` but no created event in a task stream, so 2,466 of 2,714 outcome rows are `unknown` with `succeeded=True`, and the Self Model's competence section reports 'unknown 97%'.",
    "evidence": [
      "simorgh/learning/outcomes.py:84-94 -- `task_type = \"unknown\"` then `kind = p.get(\"kind\", \"unknown\")` from `self._ledger.read(f\"task:{task_id}\")`; :119-124 on_task_completed records `succeeded=True, weight=1.0` regardless",
      "grep -o '\"task_type\":\"[a-z_:]*\"' ~/.simorgh/ledger/streams/learn%3Aoutcomes.jsonl | sort | uniq -c -> \"2466 unknown / 125 research / 81 patch / 3 skill / 1 project\" of 2714 rows",
      "task streams: 103 `created` events vs 2334 `task.completed` events (ls | grep '^task%3A' | xargs cat | grep -o '\"type\":\"...\"') -- the difference is chat turns",
      "~/.simorgh/worldmodel/self/SELF.md -> \"## How well I do it\\n- unknown 97% (2466)\"",
      "docs/blueprint/07-post-cutover-review.md:100-103 named the same defect on 2026-09-06 (\"a floor reply and a great reply score identically\"); it is still current"
    ],
    "why_it_matters": "Curiosity's competence-gap drive, Reflection's calibration and the Self Model's 'how well I do it' all read this table. With 91% of rows typed `unknown` and always successful, every downstream 'learned' number is arithmetic on noise, and the creator cannot tell whether Sim is getting better.",
    "recommendation": "Do not record chat turns as competence outcomes at all (they have no verdict), or record them under kind `chat` only when a `verify.result` exists for the turn. Make OutcomeRecorder refuse to write a row whose task_type is `unknown` and count refusals in health. One assertion in the existing integration suite: after a chat turn, learn:outcomes gains no `unknown` row.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/learning/outcomes.py | 1 """`OutcomeRecorder`: turns `task.completed` / `task.failed` / `task.blocked` 2 (the terminal, or not-yet-terminal-but-informative, facts about a task) 3 into |
| 2 | Bash | List ledger stream files | action%3A00058d0478bb.jsonl action%3A00069b23741c.jsonl action%3A000730a414ea.jsonl action%3A00085e844cff.jsonl action%3A0009062c07cc.jsonl 118215 -rw-r--r--@ 1 |
| 3 | Bash | Count task_type distribution in learn:outcomes |  2714 learn%3Aoutcomes.jsonl 2466 "task_type":"unknown" 125 "task_type":"research" 81 "task_type":"patch" 9 "task_type":"patch:simorgh/persona" 7 "task_type":"p |
| 4 | Bash | Count event types across task streams (sample) | 2431 452 "type":"task.step" 303 "type":"task.started" 285 "type":"task.completed" 202 "type":"lease_refreshed" 38 "type":"status_changed" 14 "type":"claimed" 12 |
| 5 | Bash | Check SELF.md competence, chat task_id origin, and created event writers | 9:## How well I do it 10-- unknown 97% (2466) 11- 12-## What I know I'm bad at 13-(none recorded yet) 14- 15-## What I've changed about myself (last 10) --- sim |
| 6 | Bash | Read run_percept_chat in worker.py |  async def run(self, session: Session, *, user_text: str = "") -> Outcome: self.current_task_id, self.current_kind = session.task_id, session.kind try: return a |
| 7 | Bash | Find who writes to task streams and whether kind is included | simorgh/orchestration/resume.py:112: events = await ledger.read(f"task:{session.task_id}") simorgh/orchestration/worker.py:277: partition_key=f"task:{task_id}", |
| 8 | Bash | Inspect first event and kind of task streams behind unknown rows | unknown succeeded/verdict: Counter({(True, 'unknown'): 2403, (False, 'failed'): 39, (False, 'blocked'): 24}) first event type of last 60 unknown streams: Counte |
| 9 | Bash | Read task.started publish and kind payload sites in worker/session | Exit code 1 if outcome.floor: payload["floor"] = True elif outcome.kind == "failed": payload = {"task_id": session.task_id, "reason": outcome.reason, "terminal" |
| 10 | Bash | Show the newest unknown row's task stream head and last edit dates | last unknown row ts: Fri Sep 18 17:09:29 2026 {"causation_id":null,"idempotency_key":"4734dda8-890f-45ac-9dcf-8df79cf971ed","payload":{"task_id":"2de3c380-35cf- |
| 11 | Bash | Read task.started payload and check prior reviews for this finding | Exit code 1 subject_ref = await self._put_verify_subject(session, text) msg = Message.new( topics.VERIFY_REQUESTED, source=self._bus.source, payload={ "verifica |
| 12 | Bash | Read worker kind payload, grep prior reviews, and find task.started publish |  # Who this reply is to. A typed turn is `channel == "cli"`, # a spoken one "voice", a task's own chat "" -- and only # the first is for the voice subsystem to  |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** The claim is true of the code today and the ledger reproduces it exactly. simorgh/learning/outcomes.py:84-94 sets task_type="unknown" and only overrides it from `events[0].payload.get("kind")` of the `task:<id>` stream; :123-125 records `succeeded=True, weight=1.0` on every task.completed with verdict "unknown" unless a cached verify result exists. Chat turns are built in simorgh/orchestration/worker.py:387-403 with `kind="chat"` on an in-memory Session but Planning never creates a `created` event for them (the docstring at :389-391 says so explicitly), so the first event on their stream is `task.started`, which session.py:876 appends with only `{task_id, worker_id}` -- no `kind`. The `kind` IS put on the bus at worker.py:544, but on the turn.completed message, not on the task stream outcomes.py reads. Live ledger: 2466 of 2714 learn:outcomes rows are `unknown` (90.9%); of those 2403 are succeeded=True/verdict=unknown; sampling the last 60 unknown rows, all 60 task streams begin with `task.started` and none carry a `kind`. The newest unknown row was written today 2026-09-18 17:09, and worker.py/outcomes.py were last changed 2026-09-16, so this is current state, not history. ~/.simorgh/worldmodel/self/SELF.md:9-10 reads "## How well I do it / - unknown 97% (2466)". docs/blueprint/07-post-cutover-review.md:100-103 did name the same defect in 2026-09-06. Neither docs/architecture-audit-2026.md nor docs/architecture-review-2026-09-18.html nor the third-opinion doc mention competence or the unknown type, and it is not in the known-findings list given to me. Classification: the creator knowingly routes chat turns into the outcome table (outcomes.py:63-83 docstring designs the per-run idempotency key around it), so recording chat is a design choice; but the type resolution silently failing to `unknown` because nobody writes `kind` to the stream is a genuine bug of the project's "unconnected wire" shape, and it makes the competence, calibration and Self Model numbers meaningless. Severity high is justified: this table feeds the learning loop the whole project exists for.

### evidence

- simorgh/learning/outcomes.py:84-94 -- task_type = "unknown"; kind = p.get("kind", "unknown") read from events[0] of self._ledger.read(f"task:{task_id}")
- simorgh/learning/outcomes.py:119-125 -- on_task_completed: verdict="unknown" unless verification_ref in cache; _record(succeeded=True, weight=1.0)
- simorgh/orchestration/worker.py:389-391 docstring: "a plain conversational percept has no Planning task behind it"; :402-403 Session(task_id=session_id, kind="chat", ...) -- kind lives only in memory
- simorgh/orchestration/session.py:876 -- self._append(session, topics.TASK_STARTED, {"task_id": session.task_id, "worker_id": self._worker_id}) -- first stream event for a chat turn carries no kind
- simorgh/orchestration/worker.py:544 -- "kind": session.kind is published on the turn.completed bus message, not appended to the task stream outcomes.py reads
- wc -l ~/.simorgh/ledger/streams/learn%3Aoutcomes.jsonl -> 2714; grep -o '"task_type":"[^"]*"' | sort | uniq -c -> 2466 unknown, 125 research, 81 patch, 9 patch:simorgh/persona, 7 patch:simorgh/interface, 3 skill, ...
- python3 over learn:outcomes: unknown rows split succeeded/verdict = {(True,'unknown'): 2403, (False,'failed'): 39, (False,'blocked'): 24}
- python3 over the task streams of the last 60 unknown rows: first event type = task.started x60; kind in first event payload = <none> x60
- newest unknown row ts = Fri Sep 18 17:09:29 2026; its stream task:2de3c380... begins {"payload":{"task_id":...,"worker_id":"orchestration-0"},"type":"task.started"}; git log -1 on worker.py/outcomes.py -> 2026-09-16 4f69dc9 (code unchanged since)
- sample of 300 task streams: 11 "created" vs 285 "task.completed" -- same ratio the finding reports for the full set
- ~/.simorgh/worldmodel/self/SELF.md:9-10 -> "## How well I do it\n- unknown 97% (2466)"
- docs/blueprint/07-post-cutover-review.md:100-103 -> "Chat completions feed learn.outcome.recorded{succeeded: True} unconditionally -- a floor reply and a great reply score identically"
- grep -i 'unknown 97|"unknown"|competence' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md -> no matches (not previously reported)

**severity adjustment:** keep

