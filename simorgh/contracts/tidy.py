"""Reading through typos and mishearings, before a message is answered.

The creator, 2026-09-12: "when typing or talking to sim, it happens
that user makes typo mistakes or in talking sim doesn't correctly
understand the spelling of the word; in this case I expect sim to do
auto correction, fix the spelling and find the most relevant word
according to context and chat recent history." Their examples: the
recogniser hears "Seem do something" or "C do something" for "Sim do
something"; and a typed "Sim let sdo somethin gfunnty tday, ther isan
even onlne called agencon" should be read as "Sim lets do something
funny today, there is an event online called agentcon".

Two layers, cheapest first:

- `fix_name` is local and instant: the ways a recogniser writes "Sim"
  at the start of an utterance ("Seem", "C", "Shin", "Sym") become
  "Sim". Nothing else is guessed at locally -- a spell-checker with no
  context turns "agencon" into "agency", which is worse than leaving it.
- `tidy` asks the model, but only when `garbled` says the message
  looks broken: two or more words that are in no dictionary, not in
  the recent conversation, and not a path, a number or code. A clean
  message never costs a call; a garbled one costs one short call
  (~200 tokens) before the real turn, and the screen shows what it
  was read as. The reply is checked before it is trusted: an answer
  instead of a rewrite, or a rewrite that is not recognisably the same
  message, is dropped and the original stands.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from simorgh.contracts import topics

# What whisper (and a fast typist) makes of "Sim" at the start of a
# sentence. "Seem" and "sin" are only Sim in that position -- "they
# seem fine" is English.
_NAME_LEAD = re.compile(
    r"^(\s*(?:hey|hi|hello|ok|okay|yo|so|and|now|please)?[\s,]*)"
    r"(?:seem|seems|c|si|sym|sim's|simm|sims|cim|zim|shin|sheen|sem|seam|asim|assim)"
    r"(?=[\s,.!?:]|$)([,.!:]?)", re.I)
_NAME_VOCATIVE = re.compile(r"([,;]\s*)(?:seem|sym|simm|cim|zim|shin|sheen|seam|asim|assim)(?=[\s.!?]|$)", re.I)

_WORD = re.compile(r"[A-Za-z']+")
_CODEISH = re.compile(r"[/\\_.@:#`{}\[\]()<>=|~^$%&*+0-9]")
_DICT_PATHS = ("/usr/share/dict/words", "/usr/dict/words")
# Words the 1934 dictionary on macOS lacks, and contractions.
_ALWAYS_KNOWN = frozenset("""
online offline email internet website web app apps ok okay hey hi yeah yep nope thanks wifi bluetooth
laptop desktop smartphone iphone android mac linux windows github git python repo repos json api apis
sim simorgh alexa voice mic stt tts llm ai agent agents agentcon benchmark benchmarks gaia dev devs
todo tv url urls pdf mp3 mp4 png jpg wav zoom slack discord youtube google amazon chatgpt claude gpt
i'm i've i'll i'd you're you've you'll you'd we're we've we'll he's she's it's they're they've they'll
isn't aren't wasn't weren't don't doesn't didn't can't couldn't won't wouldn't shouldn't haven't hasn't
hadn't let's that's there's here's what's who's where's when's how's why's lets gonna wanna gotta
""".split())
MIN_UNKNOWN = 2
MAX_TIDY_CHARS = 600
TIDY_TIMEOUT_S = 4.0


@lru_cache(maxsize=1)
def dictionary() -> frozenset[str]:
    """The system word list, lower-cased, or an empty set where there
    is none -- then nothing is ever called garbled and no call is made."""
    for path in _DICT_PATHS:
        try:
            words = Path(path).read_text(encoding="utf-8", errors="ignore").split()
        except OSError:
            continue
        return frozenset(w.lower() for w in words)
    return frozenset()


def fix_name(text: str) -> str:
    """`Seem do something` -> `Sim, do something`; `hey c, stop` ->
    `hey Sim, stop`; `okay, shin, ...` -> `okay, Sim, ...`."""
    if not text:
        return text
    out = _NAME_LEAD.sub(lambda m: f"{m.group(1)}Sim{m.group(2) or ','}", text, count=1)
    out = _NAME_VOCATIVE.sub(lambda m: f"{m.group(1)}Sim", out)
    return out


def unknown_words(text: str, *, known: frozenset[str] | set[str] = frozenset()) -> list[str]:
    """Words in `text` that no dictionary, the recent conversation, or
    the always-known list has -- lower-case only: a capitalised word is
    a name until proven otherwise, and code-ish tokens are not words."""
    words = dictionary()
    if not words:
        return []
    out = []
    for token in text.split():
        if _CODEISH.search(token):
            continue
        for word in _WORD.findall(token):
            if word[:1].isupper() or len(word) < 3:
                continue
            low = word.lower()
            if low in _ALWAYS_KNOWN or low in known or _in_dictionary(low, words):
                continue
            out.append(word)
    return out


_SUFFIXES = ("s", "es", "ed", "d", "ing", "ly", "er", "est", "ies", "ied", "ier", "iest", "ness", "ment", "ers")


def _in_dictionary(low: str, words: frozenset[str]) -> bool:
    """The word, or a plain inflection of one: the macOS list is the
    1934 Webster's and has "call" but not "called", "run" but not
    "running"."""
    if low in words:
        return True
    for suffix in _SUFFIXES:
        if low.endswith(suffix) and len(low) - len(suffix) >= 3:
            stem = low[: -len(suffix)]
            if stem in words or stem + "e" in words:
                return True
            if suffix.startswith("i") and stem + "y" in words:  # tries -> try
                return True
            if len(stem) > 3 and stem[-1] == stem[-2] and stem[:-1] in words:  # running -> run
                return True
    return False


def recent_vocabulary(recent: list[str]) -> frozenset[str]:
    return frozenset(w.lower() for line in recent for w in _WORD.findall(line or ""))


def garbled(text: str, *, recent: list[str] | None = None) -> bool:
    """Whether `text` is worth a tidy call: `MIN_UNKNOWN` or more words
    nobody knows. One odd word is a name or a term; the model reads
    through that on its own."""
    if not text or len(text) > MAX_TIDY_CHARS:
        return False
    return len(unknown_words(text, known=recent_vocabulary(recent or []))) >= MIN_UNKNOWN


def tidy_messages(text: str, *, recent: list[str]) -> list[dict]:
    context = "\n".join(f"- {line[:200]}" for line in recent[-6:] if line.strip())
    return [
        {"role": "system", "content": (
            "You clean up one message a person typed fast or spoke through a speech recogniser, "
            "for an assistant named Sim. Fix spelling; split words that ran together and join "
            "letters that broke off; restore 'Sim' where the recogniser wrote Seem, See, C, Shin, Sym "
            "or the like for the assistant's name; use the recent conversation to recover names and "
            "terms. Keep the person's meaning, wording, tone, language and length. Do NOT answer the "
            "message, do not add or remove anything, do not comment. Reply with the corrected message "
            "only." + (f"\n\nRecent conversation, for names and terms:\n{context}" if context else "")
        )},
        {"role": "user", "content": text},
    ]


def accept(original: str, candidate: str) -> str | None:
    """The corrected text, or None when the reply is not a rewrite of
    the original: empty, an answer (much longer, several paragraphs,
    a question back), or nothing like the same words."""
    cleaned = (candidate or "").strip().strip('"').strip()
    if not cleaned or "\n\n" in cleaned or len(cleaned) > len(original) * 1.6 + 20:
        return None
    if cleaned.lower().startswith(("sure", "here", "i ", "the corrected", "corrected:")):
        return None
    before = set(w.lower() for w in _WORD.findall(original))
    after = set(w.lower() for w in _WORD.findall(cleaned))
    if before and not (before & after) and len(before) > 2:
        return None
    return cleaned


@dataclass(frozen=True)
class Tidied:
    text: str
    original: str

    @property
    def changed(self) -> bool:
        return self.text != self.original


async def tidy(bus, text: str, *, recent: list[str] | None = None, timeout_s: float = TIDY_TIMEOUT_S) -> Tidied:
    """The message as Sim should read it. Always the local name fix;
    the model only for a message `garbled` says is worth it, and only
    when a real provider answers in time. Never raises."""
    original = text
    text = fix_name(text)
    if bus is None or not garbled(text, recent=recent):
        return Tidied(text=text, original=original)
    try:
        request = bus.new(topics.COGNITION_THINK, {
            "purpose": "chat", "messages": tidy_messages(text, recent=recent or []),
            "budget": {"max_tokens": 200, "max_cost_usd": 0.01}, "require_real_provider": False,
        })
        reply = await asyncio.wait_for(bus.request(request, timeout=timeout_s), timeout=timeout_s + 0.5)
    except Exception:  # noqa: BLE001 -- a tidy that fails is a message read as typed
        return Tidied(text=text, original=original)
    payload = getattr(reply, "payload", None) or {}
    if payload.get("floor") or payload.get("error"):
        return Tidied(text=text, original=original)
    accepted = accept(text, str(payload.get("text") or ""))
    return Tidied(text=accepted or text, original=original)


__all__ = ["MIN_UNKNOWN", "Tidied", "accept", "dictionary", "fix_name", "garbled", "recent_vocabulary", "tidy",
           "tidy_messages", "unknown_words"]
