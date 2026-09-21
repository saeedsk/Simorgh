# initiative — when Sim speaks first

## Purpose

Initiative owns one decision: is this worth interrupting these people, here, now — and if so, through which channel. Four things used to make that decision separately and badly (Curiosity's growth notes, Persona's news sharing, the camera announcer, reminder delivery), each unaware of the others and none of them aware of the room. It must never reach a device itself: every delivery is an `action.proposed{tool: speak|notify}`, because Sim saying something unprompted is an effect and Guardian gates effects. It must never assume an empty house from silence; with no evidence the speaker is expensive and the phone is cheap, which is the safe direction. The shaping decision: the answer is a *channel*, not a yes/no — most notices are worth recording and not worth saying, and the ones worth saying at 02:00 are worth saying to a phone.

Since stage 10 item 3 it also owns the companion's two reasons to speak first: a `check_in` when the World Model's posterior says an adult who said yes seems quieter than their usual, and an `interest_share` when something turned up about what a family member cares about. Both are gated on consent and role here as well as in the World Model, both are private (the speaker only when the person is alone in their area), and both are composed: the notice carries a *state note*, one `cognition.think` call writes the words, and the model may answer `NOTHING`. Initiative decides *whether*; the model decides *how*.

## Files

| File | For |
|---|---|
| `simorgh/initiative/api.py` | `Notice`, `Situation`, `Delivery` and `decide`: urgency × relevance × weight [× reach] − interruption cost, cooldowns (per person for the personal classes), the daily cap, do-not-disturb; the digest classes `DIGESTIBLE`/`DIGEST_MAX`; the companion helpers `companion_gate`, `alone`, `matches_interest`, `state_note`, `compose_prompt`, `acceptable_line` |
| `simorgh/initiative/service.py` | The Subsystem: listens for camera events, reminders, share proposals and wellbeing flips; asks World Model what the house is doing and who a person is; composes the personal classes through Cognition; proposes the delivery; holds what was not worth interrupting for (`_hold`) and offers it together on idle (`_digest`) |

## Consumes

| Type | Schema | Where | Why |
|---|---|---|---|
| `world.camera.event` | `messages/world.py::CameraEvent` | service.py `_on_camera_event` | a person at the front door is a safety alert; anything else is an FYI |
| `world.camera.described` | `messages/world.py::CameraDescribed` | service.py `_on_camera_described` | the vision model's own words about the same event, weighed the same way and better than "Front Door: person". Execution published these straight to `voice.speak.request` until 2026-09-20, so a camera described the street aloud at any hour, past Guardian and past this module; the `event_fyi` cooldown also makes the raw event and its description one interruption rather than two |
| `percept.time.scheduled` | `messages/percept.py::PerceptTimeScheduled` | service.py `_on_schedule_fired` | a reminder is for its person, wherever they are |
| `curiosity.share.proposed` | `messages/curiosity.py` | service.py `_on_share_proposed` | growth and news, which wait for a cheap moment; a share whose `summary` is about a consented family member's interests goes to them as an `interest_share` instead (stage 10). The message carries `summary` since 2026-09-20 -- the scheduler always computed it and the publisher dropped it, so every share was suppressed with `why: "the share carried no summary to say"` -- and Initiative is now the only path for one: Persona's parallel pacing and its `ui.notice` were removed the same day |
| `world.wellbeing.changed` | `messages/world.py::WorldWellbeingChanged` | service.py `_on_wellbeing_changed` | `state: low` for a person is weighed as a `check_in` with `weight = mean`; any other state is not a reason to speak (stage 10 item 3) |
| `turn.completed` | `messages/turn.py::TurnCompleted` | service.py `_on_turn_completed` | what the person said in the ten minutes after Sim asked how they were. "Not now" / "I'm fine" holds check-ins with them for `NOT_NOW_HOLD_S` (24 h); "stop asking me" proposes `people revoke wellbeing_checkins` at tier 3, because Sim withdraws consent on nobody's behalf. Outside that window the same words are an ordinary sentence (stage 10 item 6) |
| `memory.fact.stored` | `messages/memory.py::MemoryFactStored` | service.py `_on_fact_stored` | a fact with the predicate `interest` about somebody Sim knows becomes a tier-3 `people add_interest` PROPOSAL, with the sentence Sim heard in the rationale. Knowing what somebody likes and being allowed to bring it up unprompted are different things, and the second is theirs to grant; nothing reaches `Person.interests` without that yes. Skipped for an interest already held, and for a fact about nobody Sim knows (stage 10 item 7) |
| `system.tick.idle` | `messages/system.py` | service.py `_on_idle` | nothing is happening and somebody who granted `interest_shares` is in the room with an interest recorded: one bounded research task about it, at most `RESEARCH_PER_DAY` (2) a day and one at a time (stage 10 item 8). The topic was declared in this manifest and subscribed by nothing until 2026-09-20 |
| `task.completed` | `messages/task.py::TaskCompleted` | service.py `_on_task_completed` | a task Initiative sought comes back and is OFFERED, through `offer()` like everything else, so the hour, the room and the channel are weighed the same way; an empty answer is suppressed with why |
| `world.env.query.reply` | `messages/world.py` | service.py `_situation`, `_person`, `_people` | who is where and what the house is doing (`home`); who a person is, their role, permissions and interests (`people`) |
| `cognition.think.reply` | `messages/cognition.py` | service.py `_compose` | the words for a composed class, or `NOTHING` |

## Produces

| Type | Where | Payload |
|---|---|---|
| `action.proposed` | service.py `offer` | `speak` (the room) or `notify` (a person's phone), with the utility reasoning as the rationale; `requester: ""`, `requester_channel: "initiative"` |
| `initiative.offered` | service.py `offer` | the decision to deliver, published just before the `action.proposed` that carries it out: `kind`, `tool`, `person`, `to`, `why`, `ref`. A proposal for `speak` looks the same whoever asked for it, so without this a household -- or anything measuring how often Sim gets a check-in right -- could see every notice held back and not one that went out. Written before the words are composed, so it is the judgement rather than the wording |
| `initiative.suppressed` | service.py `_suppress` | what was held back and why — a decision to stay quiet is a decision. Reasons include the gate that refused (`... is child; a check-in is for an adult who said yes`, `nobody Sim knows`, `... has not said yes to check-ins`), `the model had nothing worth saying`, `the line named a condition (...)`, `the model did not answer`, `the share carried no summary to say` |
| `cognition.think` | service.py `_compose` | `purpose: chat`, one user message from `compose_prompt`, `max_tokens` 120, `max_cost_usd` 0.01, `require_real_provider: false` |
| `world.env.query` | service.py `_world` | `what: home` (the situation) and `what: people` (one person by name, or everybody) |
| `task.create` | service.py `_seek_for` | `kind: research`, `origin: curiosity`, bounded to 6 steps -- one interesting thing about one person's interest, with its source. The sourcebook and web search are fine here: this is news about lego robotics, not advice about a person |

## Invariants

1. Every delivery is proposed to Guardian; nothing here speaks or notifies directly.
2. A safety alert is never dropped for cost: when no channel clears the bar it goes to the owner's phone.
3. The speaker is never used for a notice addressed to somebody who is not in that room.
4. Quiet hours, someone asleep or an empty house make the speaker expensive; the phone is unaffected.
5. Cooldowns are per class (per class *and person* for `check_in` and `interest_share`, `cooldown_key`) and the daily cap is `DAILY_CAP` (12); neither applies to a safety alert.
6. Do-not-disturb holds for everything except a safety alert.
7. With no answer from World Model the situation is empty, which suppresses the speaker rather than assuming an empty house.
8. A `check_in` is offered only to a person `contracts.people.may_check_in` admits (owner or adult, with `wellbeing_checkins` granted) and an `interest_share` only to one `may_share_interest` admits (family, with `interest_shares`); a child, a guest, an unknown voice, an adult without the grant or a notice with no person is suppressed with the gate's reason before the model is asked, whatever the posterior and whoever sent the notice.
9. A person's own words end a check-in: within ten minutes of one, "not now" or "I'm fine" holds check-ins with them for 24 hours (recorded as `initiative.suppressed`), and "stop asking me" is proposed as a `people revoke` at tier 3 and never acted on here -- consent is withdrawn by the person, exactly as it was granted. The phrases are deliberately narrow: an ordinary answer to "how are you" must not read as a refusal, or the one time somebody actually talks is the time Sim stops listening.
10. A second `check_in` about the same person waits until either they have been seen `usual` or `high` again (the stretch ended) or `CHECK_IN_AGAIN_S` (72 h) has passed. `unknown` is not a recovery -- overnight the evidence decays below the threshold and the state reads `unknown` until the person speaks again -- and treating it as one made Sim ask on each of three consecutive quiet days, every one of them legally inside the 24-hour cooldown (found by the stage 11 companion arcs, 2026-09-20). Recall and precision both read 100% for that behaviour; a person on the receiving end would have called it nagging.
11. A private word (`PRIVATE`) is never said through the speaker unless the person is alone in their area (`alone`; somebody the house cannot place is not alone); it is cheaper on the speaker then (`ALONE_DISCOUNT`), and weighed by how much of it reaches the person through each channel (`REACH`: speaker 1.0, phone 0.6, screen 0.5), so a word to somebody alone in the room is spoken rather than sent to their phone.
12. A composed class never speaks the notice's text: the words come from one `cognition.think` call, and a reply that is empty, `NOTHING`, longer than `LINE_MAX_CHARS`, or contains a `FORBIDDEN_WORDS` fragment (diagnos, depress, anxi, disorder, therap, medicat, clinical, mental health, bipolar, trauma) is suppressed, not proposed. No model, no words.
13. A check-in's state note and prompt carry the person's name and what Sim noticed in words; never a word the person said and never raw counts or percentages.

## Config

None yet: the numbers are constants in `api.py` (`URGENCY`, `CHANNEL_COST`, `REACH`, `ALONE_DISCOUNT`, `WORTH_IT`, `COOLDOWN`, `DAILY_CAP`, `FORBIDDEN_WORDS`, `LINE_MAX_CHARS`, `DIGESTIBLE`, `DIGEST_MAX`) and `service.py` (`COMPOSE_TIMEOUT_S`, `COMPOSE_MAX_TOKENS`, `COMPOSE_MAX_COST_USD`) until the household has told us which of them are wrong; stage 10 item 10's shadow mode is how they will.

## Contract tests

- `tests/simorgh/initiative/test_when_to_speak.py` — the plan's own acceptance (a camera event at 02:00 with a child asleep goes to the phone), the cooldowns, the cap, do-not-disturb, and the rule that a reminder is not announced in a room its person is not in.
- `tests/simorgh/initiative/test_companion.py` — stage 10 item 3: a consented adult alone in the kitchen in the evening with a 0.75 posterior is asked aloud in the model's words; at night, or with somebody else in the room, by phone; a weak reading stays quiet; the cooldown is per person; a child, a guest, an unknown voice and an ungranted adult never get a check-in and the model is not asked; the model may say `NOTHING`; a line naming a condition never becomes a proposal; a share about what Aran cares about goes to Aran and one about nothing anybody cares about stays news; a share with no summary says so.

## Planned changes (roadmap)

- Stage 6 item 6, still open: merging `curiosity/sharing.py`, `persona/sharing.py` and the announce step in `execution/vision.py` into this module (they still run today); a HOLD state in the voice turn manager so a proactive utterance waits for the floor; per-person do-not-disturb from the People store rather than a set. The daily digest is done (2026-09-20): a notice of a `DIGESTIBLE` class that `decide` turns down is held rather than dropped, and offered together on `system.tick.idle` as one `digest` notice -- through `offer()`, so the hour, the room, the cap and the cooldown all still apply. `URGENCY["digest"]` is 0.5, above every class it collects and below the speaker's 0.45 + `WORTH_IT`, so a digest can reach the phone or the screen and never the room; a list read aloud is the interruption it exists to avoid, and the arithmetic keeps it out rather than a special case. The held list clears only when a digest is actually offered.
- Stage 10 item 6: the composition prompt as a protected block with Persona's voice and SOUL's constraints; "not now" as a 24 h per-person hold and "stop" as a proposed `people revoke`; the reply guard widened from a word list to the creator's corpus.
- Stage 10 item 8: sought interest shares (a bounded research task per consented person per day, under a cap) and follow-through on a person's own mentions as standing intents; Growth sending a `summary` on `curiosity.share.proposed`.
- Stage 10 item 9: one `kb_ask` over the creator's corpus in the composition step, with its citation in the rationale; a URL outside the corpus in the rationale refused.
- Stage 10 item 10: shadow mode (`companion_shadow`: every check-in to the owner's phone only) for two weeks before anything is spoken.

## Working on this module

Lock it first (`python tools/modlock.py claim initiative --by <you> --task "..."`), commit the lock, edit only `simorgh/initiative/`, `tests/simorgh/initiative/` and this file. Run `python tools/modtest.py initiative`; commit subject `initiative: <what changed>`.
