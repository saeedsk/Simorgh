"""`voice.*` -- speech in, speech out (docs/plans/voice-design.md).

A spoken turn itself is not a voice message: it is
`percept.text.received{channel: "voice"}`, so the rest of the system
never learns that a request was spoken except by looking. These are the
CLI's commands to the voice subsystem, and what the pipeline announces.
"""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, List, O, Obj, Str
from ..registry import define
from .. import topics as t

_STATE = (
    F("enabled", Bool), F("listening", Bool), F("muted", Bool), F("speaking", Bool),
    F("stt", Str), F("tts", Str), F("device", Str), F("turns", Int),
    O("last_heard", Str), O("last_said", Str), O("problems", List(Str)),
    # The conversation (voice/session.py): the turn state machine's state,
    # the last turn's latencies, and the session's counts.
    O("state", Str), O("metrics", Obj()), O("interruptions", Int), O("warmup_s", Float),
    O("last_interruption_s", Float), O("partial", Str),
)

VoiceStatusRequest = define(t.VOICE_STATUS_REQUEST, [])
VoiceStatusReply = define(t.VOICE_STATUS_REPLY, [*_STATE])
VoiceControlRequest = define(t.VOICE_CONTROL_REQUEST, [
    F("action", Enum("on", "off", "mute", "unmute", "barge_on", "barge_off", "aec_on", "aec_off", "set")),
    O("key", Str), O("value", Str)],
    doc="set: change one safe setting (voice/settings.py) live and persist it; key/value travel with it.")
VoiceControlReply = define(t.VOICE_CONTROL_REPLY, [O("detail", Str), *_STATE])
VoiceSpeakRequest = define(t.VOICE_SPEAK_REQUEST, [F("text", Str), O("voice", Str)])
VoiceSpeakReply = define(t.VOICE_SPEAK_REPLY, [O("seconds", Float), O("engine", Str), O("detail", Str)])
VoiceListenRequest = define(t.VOICE_LISTEN_REQUEST, [O("seconds", Float), O("respond", Bool)],
                            doc="respond=false transcribes only; the default asks Sim and speaks the reply.")
VoiceListenReply = define(t.VOICE_LISTEN_REPLY, [
    O("heard", Str), O("confidence", Float), O("seconds", Float), O("said", Str),
    O("engine", Str), O("detail", Str),
])
VoiceVoicesRequest = define(t.VOICE_VOICES_REQUEST, [])
VoiceVoicesReply = define(t.VOICE_VOICES_REPLY, [F("engine", Str), F("voices", List(Str)), O("current", Str), O("detail", Str)])
VoiceDevicesRequest = define(t.VOICE_DEVICES_REQUEST, [])
VoiceDevicesReply = define(t.VOICE_DEVICES_REPLY, [
    F("microphone", Str), F("speaker", Str), F("stt", Str), F("tts", Str), F("vad", Str), O("problems", List(Str)),
])
VoiceModelsRequest = define(t.VOICE_MODELS_REQUEST, [O("name", Str)],
                            doc="name: a whisper.cpp model (tiny.en, base.en, small.en, large-v3-turbo); default base.en")
VoiceModelsReply = define(t.VOICE_MODELS_REPLY, [O("path", Str), O("bytes", Int), O("detail", Str), O("available", List(Str))])
VoiceListening = define(t.VOICE_LISTENING, [
    F("state", Enum("listening", "idle", "muted", "speaking",
                    "user_speaking", "thinking", "agent_speaking", "interrupted", "error")),
    F("device", Str), O("turn", Int)])
VoiceBenchRequest = define(t.VOICE_BENCH_REQUEST, [O("play", Bool)],
                           doc="play=false skips the one audible step (measuring how fast the speaker stops).")
VoiceBenchReply = define(t.VOICE_BENCH_REPLY, [O("detail", Str), O("result", Obj())])
VoiceTranscript = define(t.VOICE_TRANSCRIPT, [
    F("text", Str), F("confidence", Float), F("seconds", Float), F("engine", Str), F("device", Str),
    O("session_id", Str), O("echo", Bool), O("partial", Bool), O("turn", Int), O("corrected", Bool),
], doc="echo=true: the words were Sim's own reply coming back through the microphone; not a turn. "
       "corrected=true: the same turn, read through the recogniser's mistakes (cognition/tidy.py). "
       "partial=true: provisional, replaced by the next transcript for the same turn.")
VoiceSpoken = define(t.VOICE_SPOKEN, [F("text", Str), F("seconds", Float), F("engine", Str), F("device", Str),
                                       O("session_id", Str), O("interrupted", Bool), O("turn", Int), O("register", Str),
                                       O("response", Int), O("metrics", Obj()), O("first_audio_s", Float),
                                       O("underruns", Int)])
