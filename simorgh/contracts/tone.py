"""The feeling a spoken reply is delivered with, named by the model in one
tag at the head of its answer -- `[warm] It's three o'clock.` -- and
never spoken. Shared by the voice subsystem (which turns it into speed,
loudness and pauses), by memory (which stores the words without it) and
by anything that prints the reply.

The creator, 2026-09-13: "I prefer to add emotion to Sim's voice." The
engines this runs on (Kokoro, Piper) have no emotion control of their
own, so the feeling is carried by delivery -- how fast, how loud, how
long the pauses -- and, when an expressive engine is present, by it.
"""

from __future__ import annotations

import re

#: tone -> (what it means; the delivery table in voice/delivery.py keys on these)
TONES: dict[str, str] = {
    "neutral": "plain and even",
    "warm": "gentle, close, unhurried -- for a hurt, a worry, good news shared quietly",
    "bright": "lively, quick, smiling -- for good news, a joke landing, enthusiasm",
    "calm": "slow and steady -- for reassurance, for a child at bedtime, for instructions",
    "serious": "measured, deliberate -- for a warning, a correction, something that matters",
    "playful": "light, quick, a little teasing -- for banter",
    "sorry": "soft and slow -- for an apology, a refusal, bad news",
}
_ALIASES = {"happy": "bright", "excited": "bright", "cheerful": "bright", "gentle": "warm", "kind": "warm",
            "soft": "warm", "sad": "sorry", "apologetic": "sorry", "grave": "serious", "stern": "serious",
            "urgent": "serious", "relaxed": "calm", "soothing": "calm", "fun": "playful", "teasing": "playful",
            "joking": "playful", "plain": "neutral", "flat": "neutral",
            # Farsi: the family speaks it, and the model answers in it. Without
            # these the tag is only dropped; with them it is also understood.
            "گرم": "warm", "آرام": "calm", "جدی": "serious", "شاد": "bright",
            "متاسف": "sorry", "خنثی": "neutral"}
#: The separators a model puts between words inside one tag. The em dash was
#: missing, so "[loud and clear -- calm, warm] [calm] Loud and clear." had its
#: first tag read out (live 2026-09-15).
#:
#: Letters in ANY script. It used to be `[A-Za-z]`, which matched the "c"
#: of "[código is wrong]" and then died on the "o" with an accent -- so the
#: tag never matched at all and was read out word for word (live
#: 2026-09-16). The Farsi "[گرم]" never stood a chance either, and Farsi is
#: a language this house actually speaks. `[^\W\d_]` is a word character
#: that is neither a digit nor an underscore: a letter, anywhere.
#:
#: The trailing full stop is allowed because a model wrote "[loud and
#: clear.]" and, the tag being unmatchable, said it out loud.
#: A `.` or `:` INSIDE the token, so "[c.playful]" matches at all. It
#: did not, so the whole tag fell through untouched and was printed
#: and then spoken -- "[c.bright] Still the same answer, Saeed" (live
#: 2026-09-21, twice in one conversation). Whether the thing is a tone
#: is still decided by `_split_one`, which only accepts it when the
#: last part names a feeling Sim knows.
#: The dot and colon are allowed only in a SINGLE-token tag, not in
#: the multi-word form. "[c.playful]" has to match at all -- it did
#: not, so the whole tag fell through untouched and was printed and
#: then spoken, "[c.bright] Still the same answer, Saeed" (live
#: 2026-09-21, twice in one conversation). Allowing dots in the
#: multi-word form too would swallow "[see the file.txt]" at the head
#: of a reply, and ordinary prose in brackets stays untouched.
_TAG = re.compile(r"^\s*[\[(<]\s*(?:tone\s*[:=]\s*)?([^\W\d_][\w-]{0,24}(?:[ ,/&+\-–—;]+[^\W\d_][\w-]{0,24}){0,5}|[^\W\d_][\w-]{0,12}[.:][\w-]{1,24})\s*\.?\s*[\])>]\s*[:\-–—]?\s*", re.I | re.U)


#: A bracketed block at the head that is plainly not a feeling: it carries
#: digits or colons. GLM, asked to open with "[warm]", wrote
#: "[sd:0.55, sv:0.45] Sah-EED." and the scores were read aloud, decimal
#: point and all (live 2026-09-15).
_META_TAG = re.compile(r"^\s*[\[(<][^\]\)>\n]{0,60}[\])>]\s*")


#: A tone tag opening a LATER line, with only a short note before it.
_AFTER_NOTE = re.compile(r"\A(?P<pre>[^\n]{0,160}(?:\n[^\n]{0,160})?)\n\s*(?=[\[(<]\s*(?:tone\s*[:=]\s*)?[A-Za-z])", re.S)


def split_tone(text: str) -> tuple[str, str]:
    """`("warm", "It's three o'clock.")` for `"[warm] It's three o'clock."`;
    `("", text)` when there is no tag or the word is not a tone. Two
    stacked tags ("[ciallo_3052e5_audio][calm] No") give the real one.

    A short note before the tag is the model talking to itself and is
    dropped: "Calm answer, then compress offer.\n\n[calm] Mostly our
    conversations..." was spoken aloud, plan and all, and the tag that
    followed it was ignored (live 2026-09-15). Only when a real tone tag
    follows -- ordinary prose with brackets in it is untouched."""
    text = _drop_meta_tag(text or "")
    first, _ = _split_one(text)
    if not first:
        match = _AFTER_NOTE.match(text or "")
        if match:
            tail = (text or "")[match.end():]
            if _split_one(tail)[0]:
                text = tail
    tone, rest = _split_one(text or "")
    for _ in range(3):
        again, rest2 = _split_one(rest)
        if rest2 == rest:
            break
        tone, rest = (tone or again), rest2
    return tone, rest


def _drop_meta_tag(text: str) -> str:
    """A head tag with numbers in it is the model talking to itself."""
    match = _META_TAG.match(text)
    if not match:
        return text
    inside = match.group(0).strip()[1:-1]
    if _split_one(text)[0]:
        return text                      # a real feeling: leave it to `_split_one`
    if any(ch.isdigit() for ch in inside) or ":" in inside:
        return text[match.end():]
    return text


def _split_one(text: str) -> tuple[str, str]:
    match = _TAG.match(text or "")
    if not match:
        return "", text or ""
    word = match.group(1).lower()
    tone = word if word in TONES else _ALIASES.get(word, "")
    if not tone and ("." in word or ":" in word):
        # A namespaced tag: "[c.playful]", "[voice.warm]", "[tone:calm]".
        # Live 2026-09-21, twice in one conversation -- "[c.bright] Still
        # the same answer, Saeed" reached the screen AND the speaker,
        # which said the tag out loud. The prefix is the model's own
        # invention and there is no list of them to keep; what settles
        # it is whether the last part is a tone Sim knows, so ordinary
        # prose in brackets is still untouched.
        tail = re.split(r"[.:]", word)[-1].strip()
        tone = tail if tail in TONES else _ALIASES.get(tail, "")
    if not tone and not word.replace("_", "").replace("-", "").isalnum():
        # "[loud and warm]" (live 2026-09-13, spoken aloud): the feeling is
        # whichever word in it is one, and the tag goes whole.
        parts = [w for w in re.split(r"[ ,/&+]+", word) if w]
        known = [w if w in TONES else _ALIASES.get(w, "") for w in parts]
        known = [k for k in known if k]
        if match.group(1) == match.group(1).lower():
            return (known[0] if known else ""), (text or "")[match.end():].lstrip()
        return "", text or ""
    if not tone:
        import difflib

        # "[cialm]" is calm; "[normal]", "[ciallo_05]" are invented tags the
        # model opened with, not words for the person -- off they come, as
        # neutral. "[NVDA]" and other upper-case brackets stay: a ticker
        # is text (the creator's screen, 2026-09-13).
        near = difflib.get_close_matches(word, sorted(TONES), n=1, cutoff=0.75)
        if near and match.group(1) == match.group(1).lower():
            return near[0], (text or "")[match.end():]
        if match.group(1) == match.group(1).lower() and word.replace("_", "").replace("-", "").isalnum() and len(word) <= 24:
            return "", (text or "")[match.end():].lstrip()
        return "", text or ""
    return tone, (text or "")[match.end():]


def strip_tone(text: str) -> str:
    return split_tone(text)[1]


__all__ = ["TONES", "split_tone", "strip_tone"]
