"""Who is speaking, in the live session: a turn's audio is embedded and
named, the name rides on the transcript and into the ask, `voice
enroll` takes three sentences instead of asking, and `voice whois`
reports the scores."""

from __future__ import annotations

import asyncio
import math
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.voice.fakes import FakeMicrophone, FakeRecogniser, FakeSpeaker, FakeSynthesiser, silence
from simorgh.voice.pipeline import Pipeline
from simorgh.voice.session import VoiceSession
from simorgh.voice.speakers import SpeakerBook

from tests.simorgh.voice.test_session import _Bus, _Script, _config, _run_until


def _vec(angle: float, dim: int = 8) -> list[float]:
    v = [0.0] * dim
    v[0], v[1] = math.cos(angle), math.sin(angle)
    return v


class _Embedder:
    """Returns whatever vector the test set last; records the audio length."""

    dim = 8

    def __init__(self) -> None:
        self.vector = _vec(0.0)
        self.seconds: list[float] = []

    def embed(self, pcm, sample_rate):
        self.seconds.append(len(pcm) / sample_rate)
        return list(self.vector)


class _Replies:
    def __init__(self, reply: str = "Hello there.") -> None:
        self.reply = reply
        self.asked: list[tuple[str, str]] = []
        self.calls: list[dict] = []

    async def ask(self, text, *, session_id=None, speaker_name: str = "", confidence: float = 1.0,
                  speaker_relation: str = "", room: str = "", speaker_before: str = "") -> str:
        self.asked.append((text, speaker_name))
        self.calls.append({"text": text, "speaker": speaker_name, "relation": speaker_relation, "room": room,
                           "before": speaker_before})
        return self.reply


def _session(config, script, replies, embedder, book):
    bus = _Bus()
    mic = FakeMicrophone(silence(0.03), frame_delay=0.0005)
    speaker, stt, tts = FakeSpeaker(), FakeRecogniser("what time is it", 0.95), FakeSynthesiser()
    pipeline = Pipeline(bus=bus, clock=None, logger=None, ledger=None, config=config, microphone=mic, speaker=speaker,
                        recogniser=stt, synthesiser=tts, detector_factory=lambda: script)
    pipeline.ask = replies.ask  # type: ignore[method-assign]
    session = VoiceSession(pipeline=pipeline, config=config, microphone=mic, speaker=speaker, recogniser=stt,
                           synthesiser=tts, detector_factory=lambda: script, embedder=embedder, speakers=book)
    # The fake microphone runs sixty times faster than the clock the echo
    # tracker keeps, so Sim's last words would "still be audible" for the
    # whole of the next scripted turn and no speech frame would be kept
    # for the speaker's voice. Real rooms keep real time; the tests do not.
    session._echo.active = lambda now: False  # type: ignore[method-assign]  # noqa: SLF001
    return session, bus, tts


class SpeakerSessionTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = SpeakerBook(Path(self.tmp.name), threshold=0.5, margin=0.06)
        self.embedder = _Embedder()

    def tearDown(self):
        self.tmp.cleanup()

    async def test_an_enrolled_voice_is_named_on_the_transcript_and_in_the_ask(self):
        self.book.enroll("Ira", _vec(0.0)); self.book.enroll("Saeed", _vec(2.0))
        self.embedder.vector = _vec(0.05)
        script = _Script((True, 60), (False, 110), (False, 10_000))   # 1.8 s of speech: enough voice to judge
        replies = _Replies()
        session, bus, tts = _session(_config(), script, replies, self.embedder, self.book)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=6.0)
        self.assertEqual(replies.asked[0][1], "Ira", "the ask carries the speaker")
        finals = [p for p in bus.of(topics.VOICE_TRANSCRIPT) if p.get("session_id")]
        self.assertEqual(finals[0]["speaker"], "Ira"); self.assertGreater(finals[0]["speaker_score"], 0.9)
        self.assertGreaterEqual(self.embedder.seconds[0], 1.5, "the turn's speech frames were embedded")
        self.assertEqual(self.book.get("Ira").heard, 1)
        self.assertEqual(session.last_speaker, "Ira")

    async def test_an_unknown_voice_stays_you_with_the_reason(self):
        self.book.enroll("Ira", _vec(0.0))
        self.embedder.vector = _vec(1.5)
        script = _Script((True, 60), (False, 110), (False, 10_000))
        replies = _Replies()
        session, bus, tts = _session(_config(), script, replies, self.embedder, self.book)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=6.0)
        self.assertEqual(replies.asked[0][1], "")
        final = [p for p in bus.of(topics.VOICE_TRANSCRIPT) if p.get("session_id")][0]
        self.assertEqual(final["speaker"], ""); self.assertIn("under the threshold", final["speaker_note"])

    async def test_a_short_turn_is_not_judged(self):
        self.book.enroll("Ira", _vec(0.0))
        script = _Script((True, 12), (False, 15), (False, 10_000))   # 360 ms
        replies = _Replies()
        session, bus, tts = _session(_config(), script, replies, self.embedder, self.book)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=6.0)
        self.assertEqual(self.embedder.seconds, [], "too little voice: no embedding, no guess")
        self.assertEqual(replies.asked[0][1], "")

    async def test_enrolment_takes_three_sentences_instead_of_asking(self):
        script = _Script(*[(True, 60), (False, 110)] * 3, (False, 10_000))
        replies = _Replies()
        session, bus, tts = _session(_config(), script, replies, self.embedder, self.book)
        self.assertEqual(session.enroll("Ira", relation="daughter", takes=3), "")
        await _run_until(session, lambda: self.book.get("Ira") is not None and len(self.book.get("Ira").embeddings) >= 3, timeout=8.0)
        self.assertEqual(replies.asked, [], "takes are not questions")
        self.assertIsNone(session._enrolling)  # noqa: SLF001
        said = " ".join(tts.spoken)
        self.assertIn("Take 1 of 3", said); self.assertIn("Take 2 of 3", said); self.assertIn("know your voice", said)
        takes = [p for p in bus.of(topics.VOICE_TRANSCRIPT) if p.get("enrolling")]
        self.assertEqual(len(takes), 3); self.assertEqual(takes[0]["enrolling"], "Ira")
        self.assertEqual(self.book.get("Ira").relation, "daughter")

    async def test_whois_reports_the_scores_aloud_and_does_not_ask(self):
        self.book.enroll("Ira", _vec(0.0)); self.book.enroll("Saeed", _vec(2.0))
        self.embedder.vector = _vec(0.02)
        script = _Script((True, 60), (False, 110), (False, 10_000))
        replies = _Replies()
        session, bus, tts = _session(_config(), script, replies, self.embedder, self.book)
        self.assertEqual(session.whois_next(), "")
        await _run_until(session, lambda: any("sounded like" in s for s in tts.spoken), timeout=6.0)
        self.assertEqual(replies.asked, [])
        self.assertTrue(any("Ira" in s and "Scores" in s for s in tts.spoken))
        note = [p for p in bus.of(topics.VOICE_TRANSCRIPT) if p.get("speaker_note", "").startswith("scores")][0]
        self.assertIn("Ira", note["speaker_note"])

    async def test_an_unknown_voice_heard_twice_is_asked_its_name_and_enrolled_by_conversation(self):
        self.book.enroll("Ira", _vec(0.0))
        self.embedder.vector = _vec(2.0)                      # somebody new, every time
        # five turns: question, question (asked who), "my name is Aran", "his son", one more sentence
        script = _Script(*[(True, 60), (False, 110)] * 5, (False, 10_000))
        replies = _Replies("It is three o'clock.")
        stt = FakeRecogniser("what time is it", 0.95)
        session, bus, tts = _session(_config(introduce_after_turns=2), script, replies, self.embedder, self.book)
        heard = iter(["what time is it", "and the date", "my name is Aran", "I am his son", "the pool is warm tonight"])
        original = session._stt._inner.transcribe if hasattr(session._stt, "_inner") else None  # noqa: SLF001

        async def _transcribe(audio, *, language=""):
            from simorgh.voice.api import Utterance
            return Utterance(text=next(heard, "hello"), confidence=0.95, seconds=1.2, engine="fake")
        inner = getattr(session._stt, "_inner", None) or getattr(session._stt, "_recogniser", None)  # noqa: SLF001
        self.assertIsNotNone(inner, "the incremental recogniser wraps the fake")
        inner.transcribe = _transcribe  # type: ignore[method-assign]
        await _run_until(session, lambda: self.book.get("Aran") is not None and len(self.book.get("Aran").embeddings) >= 3, timeout=12.0)
        said = " ".join(tts.spoken)
        self.assertIn("What is your name", said, "asked after the second unknown turn, appended to the answer")
        self.assertIn("Nice to meet you, Aran", said); self.assertIn("know your voice", said)
        self.assertEqual(len(replies.asked), 2, "the two questions were answered; the introduction turns were not asked")
        self.assertEqual(self.book.get("Aran").relation, "his son")
        self.assertIsNone(session._intro)  # noqa: SLF001

    async def test_learn_someones_voice_by_saying_so(self):
        self.book.enroll("Saeed", _vec(2.0))
        self.embedder.vector = _vec(2.0)
        script = _Script(*[(True, 60), (False, 110)] * 4, (False, 10_000))
        replies = _Replies()
        session, bus, tts = _session(_config(), script, replies, self.embedder, self.book)
        heard = iter(["Sim, learn Iris's voice", "hello Sim", "the garden lights are on", "and the pool is warm"])

        async def _transcribe(audio, *, language=""):
            from simorgh.voice.api import Utterance
            return Utterance(text=next(heard, "hello"), confidence=0.95, seconds=1.2, engine="fake")
        inner = getattr(session._stt, "_inner", None) or getattr(session._stt, "_recogniser", None)  # noqa: SLF001
        inner.transcribe = _transcribe  # type: ignore[method-assign]
        self.embedder.vector = _vec(1.0)   # Iris's takes come from a different voice than Saeed's request
        await _run_until(session, lambda: self.book.get("Iris") is not None and len(self.book.get("Iris").embeddings) >= 3, timeout=12.0)
        self.assertEqual(replies.asked, [], "none of it was a question for the model")
        self.assertIn("Iris, say a sentence", " ".join(tts.spoken))

    async def test_two_people_talking_to_each_other_are_heard_not_answered_and_the_room_reaches_the_next_ask(self):
        self.book.enroll("Ira", _vec(0.0), relation="daughter, 9"); self.book.enroll("Saeed", _vec(2.0), relation="the creator")
        voices = iter([_vec(0.02), _vec(2.02), _vec(2.03), _vec(0.03)])
        heard = iter(["what time is it", "I think it is late", "we should go to bed", "Sim, what did we decide"])
        script = _Script(*[(True, 60), (False, 110)] * 4, (False, 10_000))
        replies = _Replies("It is nine.")
        session, bus, tts = _session(_config(), script, replies, self.embedder, self.book)

        async def _transcribe(audio, *, language=""):
            from simorgh.voice.api import Utterance
            self.embedder.vector = next(voices, _vec(0.0))
            return Utterance(text=next(heard, "hello"), confidence=0.95, seconds=1.2, engine="fake")
        session._stt._inner.transcribe = _transcribe  # type: ignore[method-assign]  # noqa: SLF001
        await _run_until(session, lambda: len(replies.asked) >= 2, timeout=12.0)
        # Ira's question was asked; Saeed's two statements to her, right after Sim answered her, were not
        self.assertEqual([a[1] for a in replies.asked], ["Ira", "Ira"])
        self.assertEqual(replies.calls[0]["relation"], "daughter, 9")
        quiet = [p for p in bus.of(topics.VOICE_SPOKEN) if p.get("quiet")]
        self.assertEqual(len(quiet), 2); self.assertIn("Saeed and Ira are talking to each other", quiet[0]["reason"])
        # ...and when Ira names Sim, what was said in the room comes along as context
        self.assertIn("Saeed: I think it is late", replies.calls[1]["room"]); self.assertIn("Saeed: we should go to bed", replies.calls[1]["room"])
        self.assertNotIn("what did we decide", replies.calls[1]["room"])
        # ...and each ask says who Sim answered before it: nobody, then Ira again
        self.assertEqual([c["before"] for c in replies.calls], ["", "Ira"])

    async def test_an_unknown_voice_that_keeps_talking_is_background_until_it_names_sim(self):
        """An interview on the TV (2026-09-14): the model rightly stayed
        quiet on two fragments, then answered the third aloud. After two
        quiet turns on a voice Sim cannot place, the rest is background --
        not even asked -- until Sim is named; a guest who names Sim is
        answered, and their follow-up still is."""
        self.book.enroll("Saeed", _vec(2.0))
        self.embedder.vector = _vec(0.0)          # nowhere near Saeed: a voice Sim cannot place
        heard = iter(["the economy crumbles", "and taxes go up", "provide the creation of that money",
                      "the transition is the hard part", "Sim, what time is it", "and tomorrow"])
        script = _Script(*[(True, 60), (False, 110)] * 6, (False, 10_000))

        class _TvAware(_Replies):
            async def ask(self, text, **kw) -> str:
                await super().ask(text, **kw)
                return "It is nine." if "Sim" in text or text == "and tomorrow" else "QUIET"

        replies = _TvAware()
        session, bus, tts = _session(_config(), script, replies, self.embedder, self.book)

        async def _transcribe(audio, *, language=""):
            from simorgh.voice.api import Utterance
            return Utterance(text=next(heard, "hello"), confidence=0.95, seconds=1.2, engine="fake")
        session._stt._inner.transcribe = _transcribe  # type: ignore[method-assign]  # noqa: SLF001
        await _run_until(session, lambda: len(replies.asked) >= 4, timeout=15.0)
        self.assertEqual([a[0] for a in replies.asked],
                         ["the economy crumbles", "and taxes go up", "Sim, what time is it", "and tomorrow"])
        quiet = [p for p in bus.of(topics.VOICE_SPOKEN) if p.get("quiet") and "unknown voice" in p.get("reason", "")]
        self.assertEqual(len(quiet), 2, "the third and fourth fragments were background, never asked")
        self.assertIn("It is nine", " ".join(tts.spoken))

    async def test_a_thank_you_to_someone_else_is_not_answered(self):
        """2026-09-14, live: "Thank you." from across the room got "You're
        welcome." again and again. Courtesy words that name nobody are not
        asked; "Sim, thank you" still is."""
        self.book.enroll("Saeed", _vec(0.0))
        self.embedder.vector = _vec(0.02)
        heard = iter(["- Thank you. - Thank you.", "Sim, thank you"])
        script = _Script(*[(True, 60), (False, 110)] * 2, (False, 10_000))
        replies = _Replies("You're welcome.")
        session, bus, tts = _session(_config(), script, replies, self.embedder, self.book)

        async def _transcribe(audio, *, language=""):
            from simorgh.voice.api import Utterance
            return Utterance(text=next(heard, "hello"), confidence=0.95, seconds=1.0, engine="fake")
        session._stt._inner.transcribe = _transcribe  # type: ignore[method-assign]  # noqa: SLF001
        await _run_until(session, lambda: len(replies.asked) >= 1, timeout=15.0)
        self.assertEqual([a[0] for a in replies.asked], ["Sim, thank you"])
        quiet = [p for p in bus.of(topics.VOICE_SPOKEN) if p.get("quiet") and "courtesy" in p.get("reason", "")]
        self.assertEqual(len(quiet), 1)

    async def test_a_half_heard_aside_is_not_asked_back_but_a_half_heard_ask_is(self):
        """2026-09-14, live: the creator talking Farsi across the room, heard
        at low confidence, got "I'm not sure I heard that right. Did you say:
        ...?" read back after every sentence. Only a turn that names Sim (or
        continues an exchange) is worth asking about."""
        self.book.enroll("Saeed", _vec(0.0))
        self.embedder.vector = _vec(0.02)
        heard = iter(["and the accessories need image processing", "Sim, what time is it"])
        script = _Script(*[(True, 60), (False, 110)] * 2, (False, 10_000))
        replies = _Replies("It is nine.")
        session, bus, tts = _session(_config(), script, replies, self.embedder, self.book)

        async def _transcribe(audio, *, language=""):
            from simorgh.voice.api import Utterance
            return Utterance(text=next(heard, "hello"), confidence=0.3, seconds=1.2, engine="fake")
        session._stt._inner.transcribe = _transcribe  # type: ignore[method-assign]  # noqa: SLF001
        await _run_until(session, lambda: any("Sim, what time" in t for t in tts.spoken), timeout=15.0)
        said = " ".join(tts.spoken)
        self.assertNotIn("accessories", said, "the aside was not asked back")
        self.assertIn("Did you say: Sim, what time is it", said)
        self.assertEqual(replies.asked, [], "neither half-heard turn reached the model")

    async def test_a_feeling_named_by_the_model_shapes_the_voice_and_is_not_spoken(self):
        self.book.enroll("Ira", _vec(0.0))
        self.embedder.vector = _vec(0.02)
        script = _Script((True, 60), (False, 110), (False, 10_000))
        replies = _Replies("[sorry] I cannot open the pool gate at night.")
        session, bus, tts = _session(_config(), script, replies, self.embedder, self.book)
        await _run_until(session, lambda: session.stats.turns >= 1 and bool(bus.of(topics.VOICE_SPOKEN)), timeout=6.0)
        said = " ".join(tts.spoken)
        self.assertNotIn("[sorry]", said); self.assertIn("I cannot open the pool gate", said)
        spoken = [p for p in bus.of(topics.VOICE_SPOKEN) if not p.get("quiet")][0]
        self.assertEqual(spoken["metrics"]["tone"], "sorry"); self.assertEqual(spoken["metrics"]["register"], "sorry")
        self.assertNotIn("[sorry]", spoken["text"])
        self.assertLess(tts.speeds[-1], 1.0, "sorry is slower than plain")
        self.assertEqual(tts.tones[-1], "sorry", "the engine is told the feeling")

    async def test_without_an_engine_enrolment_says_what_is_missing(self):
        script = _Script((False, 10_000))
        replies = _Replies()
        session, bus, tts = _session(_config(speaker_id="off", model_dir=self.tmp.name), script, replies, None, None)
        self.assertIn("off", session.enroll("Ira"))
        session, bus, tts = _session(_config(speaker_id="auto", model_dir=self.tmp.name, speakers_dir=self.tmp.name), script, replies, None, None)
        self.assertIn("needs", session.enroll("Ira"), "with the book but no model: says what is missing")


class WhoSaidTestCase(unittest.TestCase):
    def test_who_said_is_answered_from_the_room_not_guessed(self):
        # Live 2026-09-13: "Sim, who said I don't care?" -- nobody had -- got "That was Ira".
        from collections import deque
        from simorgh.voice.session import VoiceSession, _WHO_SAID
        fake = VoiceSession.__new__(VoiceSession)
        fake._room = deque(); fake._now = lambda: 1000.0  # noqa: SLF001
        self.assertTrue(_WHO_SAID.search("Sim, who said I don't care?"))
        self.assertEqual(_WHO_SAID.search("who said \"the pool is cold\"?").group(1), "the pool is cold")
        self.assertIn("didn't catch anyone", fake._who_said("I don't care"))  # noqa: SLF001
        fake._room.append(("Ira", "I honestly don't care about that", 990.0, "aside"))  # noqa: SLF001
        self.assertEqual(fake._who_said("I don't care"), "That was Ira.")  # noqa: SLF001
        fake._room.append(("someone", "the pool is cold today", 995.0, "asked"))  # noqa: SLF001
        self.assertIn("couldn't place the voice", fake._who_said("the pool is cold"))  # noqa: SLF001
        fake._room.append(("Sim", "I don't care for that either", 999.0, "reply"))  # noqa: SLF001
        self.assertEqual(fake._who_said("I don't care"), "That was Ira.", "Sim's own words are not the answer")  # noqa: SLF001
