# refute:correctness:Four ad-hoc session models and no identi

*Workflow: review · Phase: Refute · Agent id: `a2c1ce0563b5fc811` · Tool calls: 6*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "voice-interface-surfaces". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "Four ad-hoc session models and no identity contract: 'who is talking' exists only on the voice path",
    "kind": "wrong-design",
    "severity": "medium",
    "claim": "Each surface invents its own session id with different semantics (CLI: one uuid per typed line; HTTP: client-chosen per page load; Telegram/WhatsApp: one uuid per chat kept only in memory; Voice: one uuid per spoken turn plus `turn-N` in the ledger), and only Voice attaches a person; Telegram knows the username but drops it, the household roster has no handle field, and Persona never sees a speaker at all.",
    "evidence": [
      "simorgh/interface/service.py:943 `session_id = str(uuid.uuid4())` per typed line (and :162 a separate REPL `self.session_id`)",
      "simorgh/interface/httpapi.py:1121 `session_id = session_id or str(uuid.uuid4())` (client-supplied, validated only as a stream name at :1082)",
      "simorgh/interface/telegram.py:83-87, 190-194 and whatsapp.py:88-90, 211-215: `_sessions[chat_id] = str(uuid.uuid4())` in plain dicts, never persisted; telegram.py:177-181 `who = username or id` is used only for `channels.allowed()` and never placed on the percept",
      "simorgh/voice/pipeline.py:353 `session_id = session_id or str(uuid.uuid4())` per turn; session.py:1888 `VoiceTurn(session_id=f\"turn-{turn_id}\", ...)` records a different id for the same turn",
      "simorgh/orchestration/service.py:267 `session_id = message.payload.get(\"session_id\") or message.id`; worker.py:401 `Session(task_id=session_id, kind=\"chat\", ...)`; memory/service.py:245 tags episodic memories with `[session_id, person:<name>...]`",
      "simorgh/contracts/household.py:29-35 `Member(name, sex, say_as, age, relation, note)` has no handle/number field; `grep -c speaker simorgh/persona/*.py` -> 0 in every file"
    ],
    "why_it_matters": "The system already knows who Saeed is by voice, by Telegram username and by phone number, but there is no place where those are the same person, so memories tagged `person:Saeed` from the room are invisible to him on Telegram, a Telegram conversation forgets itself on every restart, and Persona's 'user model' is a single anonymous blob for a five-person household. Every future feature that needs 'the same person across surfaces' (reminders, preferences, language) will have to re-solve this.",
    "recommendation": "Add one small contract, `contracts/identity.py`: `Conversation(conversation_id, channel, person, language)` plus a `resolve(channel, address_or_voice) -> person` table that maps Telegram handles, WhatsApp numbers and speaker-book names onto `household.Member` names (config-driven, a dozen lines). Interface/Voice fill it, `percept.text.received` carries `person` and a stable `conversation_id` (persist the channel maps in a small JSON or a ledger stream so a restart does not forget), and Orchestration/Memory/Persona key on it. Keep the per-turn correlation uuid as `turn_id`, separate from `conversation_id`; the previous review's warning about the per-message uuid still holds for correlation, it just should not be called a session.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read cited lines in interface service and httpapi |  # automatically exactly when the REPL does, and stays off for # every headless boot (tests, `--self-check`, `status`, `trace`) # unless a caller explicitly ove |
| 2 | Bash | Read cited lines across telegram, whatsapp, voice, orchestration, memory, household, persona | ---tg name = channels.TELEGRAM def __init__(self, bus, *, token: str, allowed: tuple[str, ...] = (), poll_s: float = POLL_S, logger=None, clock=None) -> None: s |
| 3 | Bash | Check session dicts, percept speaker fields, orchestration speaker handling, identity mapping, and prior-review coverage | ---tg-sessions 29:whoever finds the address. `contracts/channels.allowed()` gates every 97: self._sessions: dict[int, str] = {} 183: who = str(sender.get("usern |
| 4 | Bash | Check percept schema fields, Telegram/WhatsApp publish payloads, voice who fields, household handle fields, persona user model keying, and p | ---schema { "channel": { "enum": [ "cli", "voice", "api", "chat", "command", "whatsapp", "telegram" ], "type": "string" }, "command": { "type": [ "string", "nul |
| 5 | Bash | Check who writes user_id/speaker on percepts, whether chat session maps persist, and config for identity mapping | ---user_id (eval):1: no matches found: --include=*.py ---tg-persist simorgh/interface/telegram.py:36:ledger, which keeps what it is given for good. simorgh/inte |
| 6 | Bash | Check user_id writers, identity config in toml, and that chat session maps are dict-only | ---user_id simorgh/contracts/messages/percept.py:14: O("user_id", Str), ---toml ---sessions-dict-only simorgh/interface/whatsapp.py:87: self._sessions: dict[str |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** Every substantive fact in the claim checks out against the code today, with two corrections. (1) Line numbers are off in two places: Telegram's session dict is at telegram.py:97 (not 83-87) and the voice `turn-{turn_id}` id is at voice/session.py:1859 (not 1888); the facts at those lines are as described. (2) "No identity contract" is overstated: the wire contract percept.text.received ALREADY has optional `speaker`, `speaker_relation`, `room` and `user_id` fields (schema/percept.text.received.v1.json; contracts/messages/percept.py:14 `O("user_id", Str)`). What is true is that only Voice fills `speaker` (session.py:993 `**who`), and `user_id` has exactly one reference in the whole tree, its declaration, so nobody writes it. That makes this an instance of the project's known "unconnected wire" shape rather than a missing contract, and the fix is smaller than the finding suggests: fill the existing slots plus add a resolve table, rather than invent `Conversation`. The identity-specific content is materially new: prior reviews (architecture-review-2026-09-18.html:198-199, architecture-audit-2026.md:30-31) cover only the CLI per-line uuid as a correlation key and the missing sliding buffer; neither mentions Telegram dropping the username, in-memory-only chat->session maps, the household roster lacking a handle field, or Persona keeping a single anonymous UserModel. Verified: Telegram computes `who` at :183, uses it only for `channels.allowed()` at :186, and publishes a payload with just channel/text/session_id at :207-208; WhatsApp identical at :197-205; `_sessions` in both files is a plain dict with no ledger/json persistence (grep shows only dict get/set); Member dataclass (household.py:29-35) has name/sex/say_as/age/relation/note only; `grep -c speaker simorgh/persona/*.py` is 0 in all nine files and persona/service.py:224-231 extracts facets into one `self._user_model` keyed by nothing; orchestration/context.py:256-290 keys memory recall on `session.speaker` and `person:<name>` tags, so a Telegram turn (speaker empty) can never see room memories tagged person:X. Classification: (b) right design (typed percept with speaker/user_id slots, per-person memory tags) undermined by implementation (surfaces other than Voice never fill them, no mapping table, no persistence of chat maps). Severity stays medium: for one family the restart amnesia on Telegram/WhatsApp and cross-surface memory invisibility are real but not blocking.

**corrected claim:** Each surface mints its own session id with different semantics (CLI: one uuid per typed line at interface/service.py:943 as a reply-correlation key, plus a separate REPL self.session_id at :162; HTTP: client-chosen or fresh uuid at httpapi.py:1121; Telegram/WhatsApp: one uuid per chat in an in-memory dict at telegram.py:97/201-204 and whatsapp.py:87/197-200, lost on restart; Voice: one uuid per turn at pipeline.py:353 and a different `turn-N` id on the VoiceTurn record at session.py:1859). The percept.text.received contract already carries optional `speaker`, `speaker_relation`, `room` and `user_id` fields, but only Voice fills `speaker` (session.py:993); `user_id` is written by nobody (its only reference is its declaration at contracts/messages/percept.py:14). Telegram computes `who = username or id` at :183 solely for the allow-list and publishes a payload without it (:207-208); household.Member (contracts/household.py:29-35) has no handle/number field; Persona has zero references to `speaker` and keeps one anonymous UserModel (persona/service.py:224-231); memory recall keys on `person:<speaker>` tags (orchestration/context.py:256-290), so non-voice turns can never see them. This is an unconnected-wire instance on an existing contract, not an absent contract: the fix is a resolve table (handle/number/voice-name -> Member.name), having Interface fill `speaker`/`user_id`, and persisting the chat->session maps.

### evidence

- simorgh/interface/service.py:162 `self.session_id = str(uuid.uuid4())`; :943 `session_id = str(uuid.uuid4())` per typed line, comment above explains it is a reply-correlation key
- simorgh/interface/httpapi.py:1121 `session_id = session_id or str(uuid.uuid4())`; :1082-1087 rejects only ids that fail stream_name_rule()
- simorgh/interface/telegram.py:97 `self._sessions: dict[int, str] = {}`; :183 `who = str(sender.get("username") or "") or str(sender.get("id") or "")`; :186 used only in `channels.allowed(who, self._allowed)`; :207-208 payload={"channel": channels.TELEGRAM, "text": text, "session_id": session_id} (no speaker/user_id); `grep -n _sessions` shows only dict get/set, no ledger or file persistence
- simorgh/interface/whatsapp.py:87 `self._sessions: dict[str, str] = {}`; :197-205 same shape, payload has only channel/text/session_id
- simorgh/voice/pipeline.py:353 `session_id = session_id or str(uuid.uuid4())`; simorgh/voice/session.py:993 publishes `**who` (speaker fields) on the transcript; :1859 `session_id=f"turn-{turn_id}"` on the VoiceTurn record (finding cited :1888, off by 29 lines)
- simorgh/contracts/schema/percept.text.received.v1.json properties include `speaker`, `speaker_relation`, `room`, `user_id` (all nullable, not required); required = ['channel','text','session_id']
- `grep -rn user_id simorgh | grep .py: | grep -v benchmark` -> single hit: simorgh/contracts/messages/percept.py:14 `O("user_id", Str)` (declared, never written or read)
- simorgh/orchestration/service.py:267 `session_id = message.payload.get("session_id") or message.id`; :277-280 forwards speaker/speaker_relation/room/speaker_before; worker.py:401-404 `Session(task_id=session_id, kind="chat", ..., speaker=speaker, ...)`
- simorgh/orchestration/context.py:256-290 recall keyed on `session.speaker` and `person:<name>` tags; memory/service.py:245 `tags = [session_id] + [f"person:{name}" for name in voices]`
- simorgh/contracts/household.py:29-35 `Member(name, sex, say_as, age, relation, note)`; grep for handle/telegram/phone in household.py -> no field hits
- `grep -c speaker simorgh/persona/*.py` -> 0 for all nine files; persona/service.py:224-231 `_on_percept_text` feeds one `self._user_model` with no person key
- Prior reviews: docs/architecture-review-2026-09-18.html:198-199 and docs/architecture-audit-2026.md:30-31 discuss only the CLI per-line uuid and sliding buffer; `grep -i telegram|whatsapp|household|identity` on both known-review docs -> no hits on cross-surface identity

**severity adjustment:** keep

