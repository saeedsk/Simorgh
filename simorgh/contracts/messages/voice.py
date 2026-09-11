"""`voice.*` -- speech in, speech out (docs/plans/voice-design.md).

A spoken turn itself is not a voice message: it is
`percept.text.received{channel: "voice"}`, so the rest of the system
never learns that a request was spoken except by looking. These are the
CLI's commands to the voice subsystem, and what the pipeline announces.
"""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, List, O, Str
from ..registry import define
from .. import topics as t

_STATE = (
    F("enabled", Bool), F("listening", Bool), F("muted", Bool), F("speaking", Bool),
    F("stt", Str), F("tts", Str), F("device", Str), F("turns", Int),
    O("last_heard", Str), O("last_said", Str), O("problems", List(Str)),
)

VoiceStatusRequest = define(t.VOICE_STATUS_REQUEST, [])
VoiceStatusReply = define(t.VOICE_STATUS_REPLY, [*_STATE])
VoiceControlRequest = define(t.VOICE_CONTROL_REQUEST, [
    F("action", Enum("on", "off", "mute", "unmute", "barge_on", "barge_off", "aec_on", "aec_off"))])
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
VoiceListening = define(t.VOICE_LISTENING, [F("state", Enum("listening", "idle", "muted", "speaking")), F("device", Str)])
VoiceTranscript = define(t.VOICE_TRANSCRIPT, [
    F("text", Str), F("confidence", Float), F("seconds", Float), F("engine", Str), F("device", Str),
    O("session_id", Str), O("echo", Bool),
], doc="echo=true: the words were Sim's own reply coming back through the microphone; not a turn.")
VoiceSpoken = define(t.VOICE_SPOKEN, [F("text", Str), F("seconds", Float), F("engine", Str), F("device", Str),
                                       O("session_id", Str), O("interrupted", Bool)])
