"""Which language a reply is in, from its script alone.

Sim answered the creator in Farsi and Kokoro read the Persian letters
as English gibberish (2026-09-11). Kokoro has no Persian; Piper does,
and the two have to be told apart before anything is spoken. The
script is enough for that: a reply written in the Arabic script is
Farsi in this house (the creator's language), and the Latin script is
English. Detection by dictionary or model would cost a dependency and
a model call for a question three code-point ranges answer.
"""

from __future__ import annotations

# Arabic block, its supplement, and the two presentation-form blocks --
# Persian's letters, including the four it adds (پ چ ژ گ), live in the
# first two.
_ARABIC_SCRIPT = ((0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))

#: What a script is spoken as. Only Persian and English are wired; a
#: script with no entry is spoken by the default voice, which is the
#: behaviour before this existed.
FARSI = "fa"
ENGLISH = "en"

# Below this share of letters, the odd Persian word inside an English
# sentence stays with the English voice -- a quotation, a name.
_SCRIPT_MAJORITY = 0.4


def _is_arabic_script(char: str) -> bool:
    point = ord(char)
    return any(low <= point <= high for low, high in _ARABIC_SCRIPT)


def language_of(text: str) -> str:
    """`"fa"` when the letters of `text` are mostly Arabic-script,
    else `"en"`. Digits, punctuation and spaces do not vote."""
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return ENGLISH
    arabic = sum(1 for c in letters if _is_arabic_script(c))
    return FARSI if arabic / len(letters) >= _SCRIPT_MAJORITY else ENGLISH


__all__ = ["ENGLISH", "FARSI", "language_of"]
