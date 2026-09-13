"""How a name is said: a respelling ("Ay-raa") or IPA ("sæˈiːd").

The creator, 2026-09-13: "Saeed's pronunciation is sæ'iːd" -- and,
typed straight into `voice pronounce`, Chatterbox read the symbols as
letters and produced chopped noise. So a pronunciation is one of two
kinds, told apart here:

  respelling  ASCII letters and hyphens; every engine reads it as words
  IPA         anything else (æ, ː, ˈ ...); Kokoro speaks it exactly, an
              engine that cannot gets a rough respelling made from it

The planner marks an IPA name in the spoken text as ⟦Saeed|sæˈiːd⟧; the
engine that speaks IPA reads the mark, every other engine and the
screen get `strip_marks(text)` -- the respelling for a voice, the name
for the eye.
"""

from __future__ import annotations

import re

MARK = re.compile(r"⟦([^|⟧]*)\|([^⟧]*)⟧")
_ASCII_RESPELLING = re.compile(r"^[A-Za-z][A-Za-z' -]*$")


def normalise(say_as: str) -> str:
    """`/sæ'iːd/` -> `sæˈiːd`: slashes off, the typewriter apostrophe
    that stands for primary stress made the real mark."""
    text = (say_as or "").strip().strip("/").strip()
    if is_ipa(text):
        text = text.replace("'", "ˈ").replace("`", "ˈ").replace(",", "ˌ")
    return text


def is_ipa(say_as: str) -> bool:
    text = (say_as or "").strip().strip("/")
    return bool(text) and not _ASCII_RESPELLING.match(text)


def mark(name: str, ipa: str) -> str:
    return f"⟦{name}|{ipa}⟧"


#: IPA -> letters an English reader says roughly right; longest first
_RESPELL = [
    ("tʃ", "ch"), ("dʒ", "j"), ("aɪ", "ai"), ("aʊ", "ow"), ("ɔɪ", "oy"), ("eɪ", "ay"), ("oʊ", "oh"), ("əʊ", "oh"),
    ("iː", "ee"), ("uː", "oo"), ("ɑː", "ah"), ("ɔː", "aw"), ("ɜː", "er"), ("ɪə", "eer"), ("eə", "air"),
    ("æ", "a"), ("ɑ", "ah"), ("ɒ", "o"), ("ʌ", "u"), ("ə", "uh"), ("ɜ", "er"), ("ɝ", "er"), ("ɚ", "er"),
    ("ɪ", "i"), ("ɛ", "e"), ("ʊ", "oo"), ("ɔ", "aw"), ("i", "ee"), ("u", "oo"), ("e", "e"), ("o", "oh"), ("a", "a"),
    ("ʃ", "sh"), ("ʒ", "zh"), ("θ", "th"), ("ð", "th"), ("ŋ", "ng"), ("j", "y"), ("ɹ", "r"), ("ɾ", "t"),
    ("x", "kh"), ("ɣ", "gh"), ("χ", "kh"), ("ʔ", ""), ("ɡ", "g"), ("ː", ""), ("ˈ", "-"), ("ˌ", "-"), (".", "-"),
]


def respell(ipa: str) -> str:
    """A rough ASCII respelling of `ipa` for an engine that reads only
    words: `sæˈiːd` -> `sa-eed`. Never exact; always sayable."""
    text = normalise(ipa)
    # One pass, longest symbol first -- replacing in turn would respell
    # the letters an earlier rule produced ("aɪ" -> "ai" -> "aee").
    table = dict(_RESPELL)
    pattern = re.compile("|".join(re.escape(sym) for sym in sorted(table, key=len, reverse=True)))
    out = pattern.sub(lambda m: table[m.group(0)], text)
    out = re.sub(r"[^A-Za-z-]", "", out)
    out = re.sub(r"-{2,}", "-", out).strip("-")
    return out or re.sub(r"[^A-Za-z]", "", text) or "?"


def strip_marks(text: str, *, for_voice: bool = True) -> str:
    """⟦Saeed|sæˈiːd⟧ -> `sa-eed` for a voice that reads letters, `Saeed`
    for the screen."""
    if "⟦" not in text:
        return text
    return MARK.sub(lambda m: respell(m.group(2)) if for_voice else m.group(1), text)


def phonemes_for(text: str, phonemize) -> str:
    """The whole of `text` as phonemes for an engine that takes them:
    each plain stretch through `phonemize`, each mark's IPA verbatim."""
    def _piece(plain: str) -> str:
        # The phonemizer trims; the spaces around a stretch are word
        # boundaries the engine needs ("həlˈoʊ sæˈiːd", not one word).
        if not plain.strip():
            return plain
        lead = " " if plain[:1].isspace() else ""
        trail = " " if plain[-1:].isspace() else ""
        return lead + phonemize(plain).strip() + trail

    out: list[str] = []
    last = 0
    for m in MARK.finditer(text):
        out.append(_piece(text[last:m.start()]))
        out.append(normalise(m.group(2)))
        last = m.end()
    out.append(_piece(text[last:]))
    return "".join(out).strip()


__all__ = ["MARK", "is_ipa", "mark", "normalise", "phonemes_for", "respell", "strip_marks"]
