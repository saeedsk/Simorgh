# initiative — when Sim speaks first

## Purpose

Initiative owns one decision: is this worth interrupting these people, here, now — and if so, through which channel. Four things used to make that decision separately and badly (Curiosity's growth notes, Persona's news sharing, the camera announcer, reminder delivery), each unaware of the others and none of them aware of the room. It must never reach a device itself: every delivery is an `action.proposed{tool: speak|notify}`, because Sim saying something unprompted is an effect and Guardian gates effects. It must never assume an empty house from silence; with no evidence the speaker is expensive and the phone is cheap, which is the safe direction. The shaping decision: the answer is a *channel*, not a yes/no — most notices are worth recording and not worth saying, and the ones worth saying at 02:00 are worth saying to a phone.

## Files

| File | For |
|---|---|
| `simorgh/initiative/api.py` | `Notice`, `Situation`, `Delivery` and `decide`: urgency × relevance − interruption cost, cooldowns, the daily cap, do-not-disturb |
| `simorgh/initiative/service.py` | The Subsystem: listens for camera events, reminders and share proposals; asks World Model what the house is doing; proposes the delivery |

## Consumes

| Type | Schema | Where | Why |
|---|---|---|---|
| `world.camera.event` | `messages/world.py::CameraEvent` | service.py `_on_camera_event` | a person at the front door is a safety alert; anything else is an FYI |
| `percept.time.scheduled` | `messages/percept.py::PerceptTimeScheduled` | service.py `_on_schedule_fired` | a reminder is for its person, wherever they are |
| `curiosity.share.proposed` | `messages/curiosity.py` | service.py `_on_share_proposed` | growth and news, which wait for a cheap moment |
| `world.env.query.reply` | `messages/world.py` | service.py `_situation` | who is where, and what the house is doing |

## Produces

| Type | Where | Payload |
|---|---|---|
| `action.proposed` | service.py `offer` | `speak` (the room) or `notify` (a person's phone), with the utility reasoning as the rationale |
| `initiative.suppressed` | service.py `offer` | what was held back and why — a decision to stay quiet is a decision |

## Invariants

1. Every delivery is proposed to Guardian; nothing here speaks or notifies directly.
2. A safety alert is never dropped for cost: when no channel clears the bar it goes to the owner's phone.
3. The speaker is never used for a notice addressed to somebody who is not in that room.
4. Quiet hours, someone asleep or an empty house make the speaker expensive; the phone is unaffected.
5. Cooldowns are per class and the daily cap is `DAILY_CAP` (12); neither applies to a safety alert.
6. Do-not-disturb holds for everything except a safety alert.
7. With no answer from World Model the situation is empty, which suppresses the speaker rather than assuming an empty house.

## Config

None yet: the numbers are constants in `api.py` (`URGENCY`, `CHANNEL_COST`, `WORTH_IT`, `COOLDOWN`, `DAILY_CAP`) until the household has told us which of them are wrong.

## Contract tests

- `tests/simorgh/initiative/test_when_to_speak.py` — the plan's own acceptance (a camera event at 02:00 with a child asleep goes to the phone), the cooldowns, the cap, do-not-disturb, and the rule that a reminder is not announced in a room its person is not in.

## Planned changes (roadmap)

- Stage 6 item 6, still open: merging `curiosity/sharing.py`, `persona/sharing.py` and the announce step in `execution/vision.py` into this module (they still run today); a HOLD state in the voice turn manager so a proactive utterance waits for the floor; per-person do-not-disturb from the People store rather than a set; the daily digest.

## Working on this module

Lock it first (`python tools/modlock.py claim initiative --by <you> --task "..."`), commit the lock, edit only `simorgh/initiative/`, `tests/simorgh/initiative/` and this file. Run `python tools/modtest.py initiative`; commit subject `initiative: <what changed>`.
