# refute:proportionality:Four ad-hoc session models and no identi

*Workflow: review · Phase: Refute · Agent id: `a014f0e1f8dd8fe5b` · Tool calls: 6*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "voice-interface-surfaces". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Read cited CLI and HTTP session-id lines |  # automatically exactly when the REPL does, and stays off for # every headless boot (tests, `--self-check`, `status`, `trace`) # unless a caller explicitly ove |
| 2 | Bash | Read cited Telegram, WhatsApp, voice, orchestration, memory, household and persona lines | ---TG name = channels.TELEGRAM def __init__(self, bus, *, token: str, allowed: tuple[str, ...] = (), poll_s: float = POLL_S, logger=None, clock=None) -> None: s |
| 3 | Bash | Check remaining citations, percept contract speaker field, persona user model, and identity mapping | simorgh/interface/telegram.py:51:import uuid simorgh/interface/telegram.py:97: self._sessions: dict[int, str] = {} simorgh/interface/telegram.py:201: session_id |
| 4 | Bash | Check Telegram percept payload, percept schema speaker field, context recall by person, persona user-model keying, and config sections | ---TGPERCEPT session_id = self._sessions.get(chat_id) if session_id is None: session_id = str(uuid.uuid4()) self._sessions[chat_id] = session_id self._chats[ses |
| 5 | Bash | Check Persona percept handler, recall filters, interface config, roster source, and what session_id continuity actually feeds | ---PERSONA async def _on_percept_text(self, message: Message) -> None: text = message.payload.get("text", "") now = self._ctx.clock.now() self._share_policy.not |
| 6 | Bash | Check voice session-id continuity, VoiceTurn field meaning, whether anyone recalls by session_id, and where the roster and speaker consumers | ---VOICESESS relation = "" if speaker and self._speakers is not None: person = self._speakers.get(speaker) relation = person.relation if person is not None else |

## Structured reply

**refuted:** False

**verdict:** partly-true

**severity adjustment:** lower

**reasoning:** The observable facts check out (with several line numbers off by ~10-30 lines), but the framing "no identity contract" is wrong and the "why it matters" is half overstated. (1) An identity slot ALREADY exists on the wire: `percept.text.received` declares optional `speaker` and `speaker_relation` (simorgh/contracts/messages/percept.py:20-25), the worker threads them into `Session(speaker=..., speaker_relation=..., room=...)` (orchestration/worker.py:387-405), Memory tags episodes `person:<name>` (memory/service.py:245) and context recall filters by `person:{speaker}` (orchestration/context.py:265). So the cross-surface identity problem is not a missing contract but the project's known dominant bug shape, an unconnected wire: Telegram computes `who` from username/id and uses it only for the allowlist (telegram.py:177-181) then publishes `{"channel","text","session_id"}` with no `speaker` (telegram.py:206-209); WhatsApp does the same. The proportionate fix is a config map `handle -> Member.name` plus one `payload["speaker"] = ...` line per channel, not a new `contracts/identity.py` with a `Conversation` object and persisted channel maps. (2) "A Telegram conversation forgets itself on every restart" is not a real loss: nothing in orchestration or cognition ever recalls by `session_id` (`grep -rn '"session_id"' simorgh/orchestration simorgh/cognition | grep filter` -> empty; context.py filters only on `person:` tags), and the reply-routing dicts are repopulated on the next message. A stable Telegram `session_id` would feed nothing today; the actual continuity gap is the already-known "no sliding dialogue buffer" finding (context.py:36-45 documents it). Persisting channel->session maps would be work with no consumer. (3) Persona truly never sees a speaker (`grep -c speaker simorgh/persona/*.py` -> 0 in all 9 files; service.py:219-232 extracts facets from bare text), so in a five-person household "call me X" from a child overwrites the creator's facet. That is a genuine design gap, but the user model is two regexes (`_PREFER_RE`, `_CALL_ME_RE`, user_model.py:15-16), so the blast radius is small and the fix is keying facets by the `speaker` the percept already carries. (4) CLI per-line uuid is explicitly already-known; HTTP client-chosen session id is a reasonable design for a dashboard tab, not a defect; the voice `VoiceTurn.session_id = "turn-N"` (session.py:1859) is a field on the `voice:turns` ledger record, a naming inconsistency rather than a second semantics on the bus. Net: right-design-undermined-by-implementation for Telegram/WhatsApp speaker (real, cheap), design gap in Persona (real, small), the rest is known or overstated, and the recommended new identity layer is disproportionate for one laptop and one family.

**corrected claim:** The bus already has an identity contract (`percept.text.received.speaker`/`speaker_relation`, threaded through Session, Memory `person:` tags and context recall), but only Voice fills it: Telegram and WhatsApp identify the sender for the allowlist and then drop it from the percept, so memories tagged `person:Saeed` from the room are not recalled for the same person on Telegram; Persona's user-model facets ignore `speaker` entirely and are one shared blob. The per-surface session-id differences are mostly cosmetic: nothing recalls by `session_id`, so restart-forgetting of Telegram/WhatsApp session ids loses nothing; the real conversation-continuity gap is the already-known missing dialogue buffer. Fix: a config map from Telegram handle / WhatsApp number to `household.Member.name`, set `speaker` on those percepts, and key Persona facets by speaker.

### evidence

- simorgh/contracts/messages/percept.py:20-25 `O("speaker", Str)` / `O("speaker_relation", Str)` -- the identity slot already exists on the wire
- simorgh/orchestration/worker.py:387-405 `run_percept_chat(..., speaker="", speaker_relation="", room="", speaker_before="")` -> `Session(task_id=session_id, kind="chat", ..., speaker=speaker, ...)`
- simorgh/memory/service.py:245 `tags = [payload.get("session_id", "")] + [f"person:{name}" for name in voices]`; simorgh/orchestration/context.py:265 `"filters": {"tags": [f"person:{speaker}"]}` -- recall keys on person, never on session_id
- `grep -rn '"session_id"' simorgh/orchestration/*.py simorgh/cognition/*.py | grep -i filter` -> (empty): no consumer of a stable session id exists
- simorgh/interface/telegram.py:177-181 `who = str(sender.get("username") or "") or str(sender.get("id") or "")` used only in `channels.allowed(who, ...)`; telegram.py:201-209 publishes `payload={"channel": channels.TELEGRAM, "text": text, "session_id": session_id}` with no speaker (finding cited :83-87/:190-194; actual :97/:201-204)
- simorgh/interface/whatsapp.py:87, :197-200 `_sessions` dict, uuid per wa_id, in memory only (finding cited :88-90/:211-215)
- simorgh/voice/pipeline.py:353-366 `session_id = session_id or str(uuid.uuid4())`, `payload["speaker"] = speaker_name` -- voice is the one surface that fills the slot; simorgh/voice/session.py:1859 `VoiceTurn(session_id=f"turn-{turn_id}", ...)` (finding cited :1888); voice/api.py:58-60 shows it is the `voice:turns` ledger record's field, not the bus id
- simorgh/persona/service.py:219-232 `_on_percept_text` reads only `text` and `session_id`; `grep -c speaker simorgh/persona/*.py` -> 0 for all 9 files; simorgh/persona/user_model.py:15-16 the whole facet extractor is `_PREFER_RE` and `_CALL_ME_RE`
- simorgh/contracts/household.py:29-35 `Member(name, sex, say_as, age, relation, note)` -- no handle field, confirmed; simorgh/interface/config.py:107,115 `telegram_allowed` / `whatsapp_allowed` tuples are where a handle->name map would naturally sit
- simorgh/interface/service.py:162 `self.session_id = str(uuid.uuid4())` and :943 per-line `session_id = str(uuid.uuid4())`; simorgh/orchestration/context.py:36-45 already documents the per-line uuid and its consequence (known finding)
- simorgh/interface/httpapi.py:1082-1085 rejects a session_id unusable as a stream name; :1121 `session_id = session_id or str(uuid.uuid4())` -- client-chosen id is deliberate for the dashboard tab

