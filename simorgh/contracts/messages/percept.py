"""`percept.*` -- inputs entering the system (section 4.2)."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, O, Str
from ..registry import define
from .. import channels
from .. import topics as t

PerceptTextReceived = define(t.PERCEPT_TEXT_RECEIVED, [
    F("channel", Enum(*channels.ALL)),
    F("text", Str),
    F("session_id", Str),
    O("user_id", Str),
    O("command", Str),
    O("steer", Bool),
    # A spoken turn (docs/plans/voice-design.md section 4.1): where it
    # was heard, who said it, and how sure the recogniser was.
    O("device", Str),
    O("speaker", Str),
    O("confidence", Float),
    # Who the speaker is to the household ("daughter, 9"), and what was
    # said in the room lately that was not for Sim (voice/session.py),
    # so the reply can know who it is talking to and what it overheard.
    O("speaker_relation", Str),
    O("room", Str),
    # Who Sim answered last, and why the speaker's name is not certain
    # ("Iris sounds almost the same"; "" when it is): voice/speakers.py.
    O("speaker_before", Str),
    O("speaker_doubt", Str),
    # How well this turn's voice matched the speaker's enrolled profile,
    # as Voice words it ("0.47 against a bar of 0.30"). Without it the
    # model, asked "what's my score?", said enrolment had never happened
    # to an enrolled person, turn after turn (live, 2026-09-21).
    O("speaker_score", Str),
], doc="channel=command + command for routed commands; steer=true marks a mid-task correction; "
       "channel=voice carries device/speaker/confidence from the voice pipeline, plus the speaker's relation "
       "and the room's recent lines that were not addressed to Sim.")
PerceptFileChanged = define(t.PERCEPT_FILE_CHANGED, [
    F("path", Str),
    F("change", Enum("created", "modified", "deleted")),
    O("sha256", Str),
])
PerceptWebFetched = define(t.PERCEPT_WEB_FETCHED, [
    F("url", Str),
    F("status", Int),
    F("content_ref", Str),
    F("sha256", Str),
    F("fetched_at", Float),
])
PerceptTimeScheduled = define(t.PERCEPT_TIME_SCHEDULED, [
    F("schedule_id", Str),
    F("label", Str),
    O("person", Str),
], doc="A durable timer went off. `person` is whose reminder it is, from the schedule's own "
       "payload, and empty means the household. Initiative has read it since it was written "
       "and nothing put one there until 2026-09-20, so the `reminder` class -- specified to "
       "reach \"its person wherever they are\" -- could only ever be announced to the room.")
