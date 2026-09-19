"""Stage 3 item 4: sentences out of a reply being written."""

import asyncio
import unittest

from simorgh.voice.streamreply import SentenceStream


def _drain(stream):
    async def go():
        out = []
        while True:
            item = await stream.queue.get()
            if item is None:
                return out
            out.append(item[0])
    return asyncio.run(go())


class SentencesFromAStream(unittest.TestCase):
    def test_a_sentence_is_queued_as_soon_as_it_is_complete(self):
        stream = SentenceStream()
        stream.feed("It is three o'clock ")
        self.assertFalse(stream.started.is_set())
        stream.feed("now. The sun")
        self.assertTrue(stream.started.is_set())

    def test_the_spoken_cap_and_the_tone_tag_are_kept(self):
        stream = SentenceStream(max_sentences=2)
        stream.feed("[warm] First sentence here. Second sentence here. Third one too. ")
        stream.finish("[warm] First sentence here. Second sentence here. Third one too. Fourth.")
        said = _drain(stream)
        self.assertEqual(said[:2], ["First sentence here.", "Second sentence here."])
        self.assertIn("more on screen", said[2])
        self.assertEqual(len(said), 3)
        self.assertEqual(stream.tone, "warm")

    def test_a_reset_keeps_what_was_said_and_the_answer_follows(self):
        stream = SentenceStream()
        stream.feed("Let me check that for you.\n")
        stream.feed("", reset=True)
        stream.feed("It is sunny today. ")
        stream.finish("It is sunny today. Twenty degrees.")
        self.assertEqual(_drain(stream), ["Let me check that for you.", "It is sunny today.", "Twenty degrees."])

    def test_a_reply_that_never_streamed_is_said_whole(self):
        stream = SentenceStream()
        stream.finish("No stream at all here. Just the reply.")
        self.assertEqual(_drain(stream), ["No stream at all here.", "Just the reply."])

    def test_pronunciation_reaches_the_synthesiser_and_not_the_echo_guard(self):
        heard = []
        stream = SentenceStream(on_sentence=heard.append, transform=lambda t: t.replace("Ira", "Ay-raa"))
        stream.finish("Hello there, Ira, good to see you.")
        self.assertEqual(_drain(stream), ["Hello there, Ay-raa, good to see you."])
        self.assertEqual(heard, ["Hello there, Ira, good to see you."])
