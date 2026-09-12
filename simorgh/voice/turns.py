"""The turn manager: who has the floor, and when it changes hands.

A voice session is a small state machine --

    idle -> listening -> user_speaking -> thinking -> agent_speaking -> listening
                              ^                            |
                              +--------- interrupted <-----+

-- and every transition is decided here, from three kinds of event and
nothing else: what the VAD says about the last frame, what the
recogniser has heard, and what the player is doing. The session
(`session.py`) owns the audio and the model; this owns the decisions,
so they can be tested with a list of events and no microphone.

End of turn is a hybrid, never silence alone: enough silence after
enough speech, the silence shortened a little when the partial
transcript already reads as a finished sentence, and a ceiling past
which the turn is finalised regardless. Turn and response ids only go
up, so a reply to an old turn, or audio from an old reply, is
recognisable as stale and dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .api import PlaybackState, TranscriptEvent, VadEvent

IDLE = "idle"
LISTENING = "listening"
USER_SPEAKING = "user_speaking"
THINKING = "thinking"
AGENT_SPEAKING = "agent_speaking"
INTERRUPTED = "interrupted"
ERROR = "error"
STATES = (IDLE, LISTENING, USER_SPEAKING, THINKING, AGENT_SPEAKING, INTERRUPTED, ERROR)

_SENTENCE_END = (".", "!", "?", "؟", "۔")


@dataclass(frozen=True)
class Policy:
    end_of_turn_silence_ms: int = 700
    min_speech_ms: int = 250
    max_turn_ms: int = 30_000
    # A partial that already reads as a complete sentence needs this
    # fraction of the silence: 0.6 turns 700 ms into 420 ms.
    semantic_silence_factor: float = 0.6
    interrupt_on_user_speech: bool = True
    # How much continuous speech over Sim's own voice counts as a person
    # cutting in (the level gate and echo cancellation sit in the VAD).
    barge_in_speech_ms: int = 650


@dataclass(frozen=True)
class Action:
    kind: str                  # see `Actions` below
    turn_id: int = 0
    response_id: int = 0
    text: str = ""
    reason: str = ""


class Actions:
    CAPTURE_START = "capture_start"    # a turn began: start feeding the recogniser
    FINALISE = "finalise"              # end of turn: close the recogniser stream
    DISCARD = "discard"                # too short to be a turn: drop the capture
    ASK = "ask"                        # a final transcript: send it to the model
    STOP_PLAYBACK = "stop_playback"    # a person cut in: stop the speaker now
    CANCEL_TTS = "cancel_tts"          # ... and stop synthesising the rest
    SPEAK = "speak"                    # a reply is ready: play it
    DROP_REPLY = "drop_reply"          # a reply arrived for a turn that is over


@dataclass
class TurnManager:
    policy: Policy = field(default_factory=Policy)
    auto_listen: bool = True
    state: str = IDLE
    turn_id: int = 0
    response_id: int = 0
    partial: str = ""
    speech_ms: int = 0
    speaking_response: int = 0
    _awaiting_final: bool = False
    _asked_turn: int = 0
    transitions: list[tuple[str, str, str]] = field(default_factory=list)

    # -- helpers --------------------------------------------------------------------------------

    def _go(self, state: str, why: str) -> None:
        if state != self.state:
            self.transitions.append((self.state, state, why))
            self.state = state

    def start(self) -> None:
        """`voice on`: from idle to listening."""
        if self.state in (IDLE, ERROR):
            self._go(LISTENING, "start")

    def stop(self) -> None:
        self._go(IDLE, "stop")

    def fail(self, reason: str) -> None:
        self._go(ERROR, reason)

    def _new_turn(self, why: str) -> list[Action]:
        self.turn_id += 1
        self.partial = ""
        self.speech_ms = 0
        self._awaiting_final = False
        self._go(USER_SPEAKING, why)
        return [Action(Actions.CAPTURE_START, turn_id=self.turn_id)]

    def _required_silence_ms(self) -> int:
        base = self.policy.end_of_turn_silence_ms
        if self.partial.rstrip().endswith(_SENTENCE_END):
            return int(base * self.policy.semantic_silence_factor)
        return base

    # -- events ---------------------------------------------------------------------------------

    def handle_vad(self, event: VadEvent) -> list[Action]:
        if self.state in (IDLE, ERROR):
            return []
        if self.state == LISTENING:
            if event.kind == "speech_start":
                return self._new_turn("speech")
            return []
        if self.state == THINKING:
            if event.kind == "speech_start":
                # The person went on before the answer came. The answer,
                # when it comes, is to a turn that is over.
                return self._new_turn("speech while thinking")
            return []
        if self.state == AGENT_SPEAKING:
            if not self.policy.interrupt_on_user_speech:
                return []
            if event.kind in ("speech_start", "speech") and event.speech_ms >= self.policy.barge_in_speech_ms:
                response = self.speaking_response
                self._go(INTERRUPTED, "barge-in")
                actions = [Action(Actions.STOP_PLAYBACK, response_id=response, reason="barge-in"),
                           Action(Actions.CANCEL_TTS, response_id=response, reason="barge-in")]
                actions += self._new_turn("barge-in")
                self.speech_ms = event.speech_ms
                return actions
            return []
        if self.state == INTERRUPTED:
            return []
        # USER_SPEAKING
        if self._awaiting_final:
            return []
        if event.kind in ("speech_start", "speech"):
            self.speech_ms = max(self.speech_ms, event.speech_ms)
            total_ms = self.speech_ms + event.silence_ms
            if total_ms >= self.policy.max_turn_ms:
                return self._finalise("max turn length")
            return []
        # silence or speech_end
        if self.speech_ms < self.policy.min_speech_ms and event.silence_ms >= self.policy.end_of_turn_silence_ms:
            turn = self.turn_id
            self._go(LISTENING, "too short")
            return [Action(Actions.DISCARD, turn_id=turn, reason="too short to be a turn")]
        if self.speech_ms >= self.policy.min_speech_ms and event.silence_ms >= self._required_silence_ms():
            return self._finalise("end of turn")
        return []

    def _finalise(self, why: str) -> list[Action]:
        self._awaiting_final = True
        return [Action(Actions.FINALISE, turn_id=self.turn_id, reason=why)]

    def handle_transcript(self, event: TranscriptEvent) -> list[Action]:
        if event.turn_id != self.turn_id:
            return []  # a recogniser still talking about an old turn
        if event.kind == "partial":
            self.partial = event.text
            return []
        # final
        self.partial = event.text
        if self.state != USER_SPEAKING:
            return []
        text = event.text.strip()
        if not text:
            self._awaiting_final = False
            self._go(LISTENING, "heard nothing")
            return []
        self._asked_turn = self.turn_id
        self._go(THINKING, "final transcript")
        return [Action(Actions.ASK, turn_id=self.turn_id, text=text)]

    def reply_ready(self, turn_id: int) -> list[Action]:
        """The model answered `turn_id`. If that turn is still the current
        one, a new response id is minted and the reply may be spoken;
        otherwise the reply is stale and dropped."""
        if turn_id != self.turn_id or self.state != THINKING:
            return [Action(Actions.DROP_REPLY, turn_id=turn_id, reason="the turn is over")]
        self.response_id += 1
        self.speaking_response = self.response_id
        return [Action(Actions.SPEAK, turn_id=turn_id, response_id=self.response_id)]

    def handle_playback_state(self, state: PlaybackState) -> list[Action]:
        if state.state == "started":
            if self.state == THINKING:
                self._go(AGENT_SPEAKING, "playback started")
            return []
        if state.state in ("finished", "stopped"):
            if self.state == AGENT_SPEAKING:
                self._go(LISTENING if self.auto_listen else IDLE, f"playback {state.state}")
            elif self.state == INTERRUPTED:
                # The person who cut in is talking; their turn is under way.
                self._go(USER_SPEAKING, "playback stopped after barge-in")
            return []
        return []


__all__ = ["AGENT_SPEAKING", "Action", "Actions", "ERROR", "IDLE", "INTERRUPTED", "LISTENING", "Policy",
           "STATES", "THINKING", "TurnManager", "USER_SPEAKING"]
