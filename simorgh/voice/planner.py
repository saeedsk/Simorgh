"""The spoken-response planner: the layer between the model's text and
the synthesiser, and the one this design makes mandatory.

Naturalness is mostly phrasing, timing and turn-taking, not the voice
model. Written text is not speakable text: markdown, links, code,
tables and citations are for a screen; a long answer is for reading;
"24.5" is for the eye. So every reply passes through here first and
comes out as a `SpokenPlan`: speakable chunks cut at semantic
boundaries (the first one short, so audio starts promptly), each with
its language, plus at most one small conversational connector when --
and only when -- the conversation calls for it.

Nothing here paraphrases. What is removed is named in `omitted`, and
the speaker offers the exact text on screen instead of reading it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .lang import ENGLISH, FARSI, language_of

# -- what the planner produces -------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    """One speakable unit. `pause_ms` follows it: a sentence boundary
    breathes, a clause boundary barely, the last chunk not at all."""

    text: str
    language: str = ENGLISH
    pause_ms: int = 0


@dataclass(frozen=True)
class Context:
    """What the planner may know about the conversation."""

    user_text: str = ""
    language: str = ""            # the user's, when known; "" = judge from the reply
    turns: int = 0                # turns so far in this session
    turns_since_connector: int = 99
    previous_connector: str = ""
    reply_seconds: float = 0.0    # how long the answer took
    is_error: bool = False        # an error or refusal: never a connector
    urgent: bool = False          # safety / urgent: never a connector, never trimmed


@dataclass(frozen=True)
class SpokenPlan:
    chunks: tuple[Chunk, ...]
    connector: str = ""           # the one lead-in chosen, already the first chunk's opening
    omitted: tuple[str, ...] = ()  # kinds of content left unspoken: link, code, table, citation, more
    language: str = ENGLISH

    @property
    def text(self) -> str:
        return " ".join(c.text for c in self.chunks)


# -- speakable text -----------------------------------------------------------------------------

_CODE_BLOCK = re.compile(r"```.*?```", re.S)
_TABLE = re.compile(r"(?m)^\s*\|.*\|\s*$(?:\n^\s*\|.*\|\s*$)+")
_URL = re.compile(r"(?:https?://|www\.)\S+")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_CITATION = re.compile(r"\s?\[(?:\d+|[a-zA-Z]+\d*)\]|\s?\((?:source|src|ref|see)s?:[^)]*\)", re.I)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_HEADING = re.compile(r"(?m)^\s*#+\s*")
_BOLD = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_ITALIC = re.compile(r"(?<!\w)[*_]([^*_\n]+)[*_](?!\w)")
_BULLET = re.compile(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+")
# A path: two or more segments ending in a file with an extension, or
# three or more segments. "and/or" and "24/7" are not paths.
_PATHISH = re.compile(r"(?<![\w/])(?:~|\.{0,2}/)?(?:[\w.-]+/){2,}[\w.-]*|(?<![\w/])(?:~|\.{0,2}/)?[\w-]+/[\w-]+\.[a-z]{1,5}\b")
_SPACES = re.compile(r"[ \t]+")

_ABBREVIATIONS = (
    (re.compile(r"\be\.g\.", re.I), "for example"),
    (re.compile(r"\bi\.e\.", re.I), "that is"),
    (re.compile(r"\betc\.", re.I), "and so on"),
    (re.compile(r"\bvs\.", re.I), "versus"),
    (re.compile(r"\bw/o\b", re.I), "without"),
    (re.compile(r"\bw/\b", re.I), "with"),
)

_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")
_ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
         "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def _int_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else "-" + _ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return _ONES[n // 100] + " hundred" + ("" if rest == 0 else " " + _int_words(rest))
    for value, name in ((10**9, "billion"), (10**6, "million"), (1000, "thousand")):
        if n >= value:
            head, rest = divmod(n, value)
            return _int_words(head) + f" {name}" + ("" if rest == 0 else " " + _int_words(rest))
    return str(n)


# Units and currency read as a person reads them, not letter by letter.
# The creator, 2026-09-12: "120ms" came out as "one twenty em es", and
# "$104.32/bbl" as "dollar ... slash be be el". A number followed by a
# unit is the number and the unit's name, singular for one; a currency
# sign before a number is the amount in dollars and cents; "/unit"
# after an amount is "per unit". Nothing here guesses at a bare letter
# with no number in front of it.
_UNITS: dict[str, tuple[str, str]] = {
    "ms": ("millisecond", "milliseconds"), "µs": ("microsecond", "microseconds"), "us": ("microsecond", "microseconds"),
    "ns": ("nanosecond", "nanoseconds"), "s": ("second", "seconds"), "sec": ("second", "seconds"),
    "secs": ("second", "seconds"), "min": ("minute", "minutes"), "mins": ("minute", "minutes"),
    "h": ("hour", "hours"), "hr": ("hour", "hours"), "hrs": ("hour", "hours"),
    "kb": ("kilobyte", "kilobytes"), "mb": ("megabyte", "megabytes"), "gb": ("gigabyte", "gigabytes"),
    "tb": ("terabyte", "terabytes"), "kib": ("kibibyte", "kibibytes"), "mib": ("mebibyte", "mebibytes"),
    "gib": ("gibibyte", "gibibytes"), "hz": ("hertz", "hertz"), "khz": ("kilohertz", "kilohertz"),
    "mhz": ("megahertz", "megahertz"), "ghz": ("gigahertz", "gigahertz"),
    "km": ("kilometre", "kilometres"), "cm": ("centimetre", "centimetres"), "mm": ("millimetre", "millimetres"),
    "kg": ("kilogram", "kilograms"), "mg": ("milligram", "milligrams"), "lb": ("pound", "pounds"),
    "lbs": ("pound", "pounds"), "mph": ("miles per hour", "miles per hour"), "kph": ("kilometres per hour",) * 2,
    "fps": ("frames per second",) * 2, "px": ("pixel", "pixels"), "bps": ("bits per second",) * 2,
    "kbps": ("kilobits per second",) * 2, "mbps": ("megabits per second",) * 2, "gbps": ("gigabits per second",) * 2,
    "bbl": ("barrel", "barrels"), "°c": ("degrees Celsius",) * 2, "°f": ("degrees Fahrenheit",) * 2,
    "°": ("degrees",) * 2, "x": ("times", "times"), "k": ("thousand", "thousand"),
}
_PER: dict[str, str] = {
    "bbl": "per barrel", "kg": "per kilogram", "g": "per gram", "lb": "per pound", "h": "per hour", "hr": "per hour",
    "s": "per second", "sec": "per second", "min": "per minute", "mo": "per month", "month": "per month",
    "yr": "per year", "year": "per year", "day": "per day", "d": "per day", "km": "per kilometre",
    "mile": "per mile", "mi": "per mile", "gal": "per gallon", "l": "per litre", "oz": "per ounce",
    "unit": "per unit", "user": "per user", "seat": "per seat", "share": "per share", "ton": "per ton",
    "tonne": "per tonne", "mwh": "per megawatt hour", "kwh": "per kilowatt hour", "token": "per token",
}
_CURRENCY = {"$": ("dollar", "dollars", "cent", "cents"), "€": ("euro", "euros", "cent", "cents"),
             "£": ("pound", "pounds", "penny", "pence")}
_UNIT_NAMES = "|".join(sorted((re.escape(u) for u in _UNITS), key=len, reverse=True))
_PER_NAMES = "|".join(sorted((re.escape(u) for u in _PER), key=len, reverse=True))
_NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_MONEY = re.compile(rf"([$€£])\s?({_NUMBER})\s*([kKmMbB](?![A-Za-z]))?(?:\s*/\s*({_PER_NAMES}))?(?![A-Za-z0-9_])", re.I)
_QUANTITY = re.compile(rf"(?<![\w.$€£])({_NUMBER})\s?({_UNIT_NAMES})(?:\s*/\s*({_PER_NAMES}))?(?![A-Za-z0-9_])", re.I)
_MIN_SEC = re.compile(r"(?<![\w.])(\d+)m\s+(\d+)s(?![\w.])")
_SCALE = {"k": "thousand", "m": "million", "b": "billion"}


def _plural(count: str, names: tuple[str, str]) -> str:
    one, many = names[0], names[-1]
    return one if count in ("1", "1.0") else many


def speak_units(text: str) -> str:
    """`120ms` -> `120 milliseconds`; `$104.32/bbl` -> `104 dollars and
    32 cents per barrel`; `5m 13s` -> `5 minutes 13 seconds`; `2.8x`
    -> `2.8 times`; `14.5k` -> `14.5 thousand`. The number itself is
    left for `speak_numbers`."""

    def _money(match: re.Match) -> str:
        sign, amount, scale, per = match.group(1), match.group(2).replace(",", ""), match.group(3), match.group(4)
        one, many, cent, cents = _CURRENCY[sign]
        if scale:
            spoken = f"{amount} {_SCALE[scale.lower()]} {many}"
        elif "." in amount:
            whole, frac = amount.split(".", 1)
            frac = (frac + "0")[:2]
            spoken = f"{whole} {_plural(whole, (one, many))}"
            if int(frac):
                spoken += f" and {int(frac)} {_plural(str(int(frac)), (cent, cents))}"
        else:
            spoken = f"{amount} {_plural(amount, (one, many))}"
        return spoken + (f" {_PER[per.lower()]}" if per else "")

    def _quantity(match: re.Match) -> str:
        amount, unit, per = match.group(1), match.group(2), match.group(3)
        names = _UNITS.get(unit.lower()) or _UNITS.get(unit)
        if names is None:
            return match.group(0)
        spoken = f"{amount} {_plural(amount.replace(',', ''), names)}"
        return spoken + (f" {_PER[per.lower()]}" if per else "")

    text = _MIN_SEC.sub(lambda m: f"{m.group(1)} {_plural(m.group(1), ('minute', 'minutes'))} "
                                  f"{m.group(2)} {_plural(m.group(2), ('second', 'seconds'))}", text)
    text = _MONEY.sub(_money, text)
    return _QUANTITY.sub(_quantity, text)


_DECIMAL = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})*|\d+)\.(\d+)(?![\w.])")
_PERCENT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?%")


def speak_numbers(text: str) -> str:
    """Decimals and percentages in words, so "24.5" is heard as
    "twenty-four point five" and not as a date or a version. Integers
    are left to the synthesiser, which reads them well; years,
    versions and identifiers must not be turned into prose."""
    def _decimal(match: re.Match) -> str:
        whole = int(match.group(1).replace(",", ""))
        digits = " ".join(_ONES[int(d)] for d in match.group(2))
        return f"{_int_words(whole)} point {digits}"

    def _percent(match: re.Match) -> str:
        return f"{match.group(1)} percent"

    text = _PERCENT.sub(_percent, text)
    return _DECIMAL.sub(_decimal, text)


def speakable(text: str) -> tuple[str, tuple[str, ...]]:
    """Written text made speakable, and what was left out.

    Code, tables, links and citations are named, not read: the speaker
    says what is on screen and offers it. Lists become a spoken
    enumeration. Numbers stay intelligible. Meaning is never changed."""
    omitted: list[str] = []
    out = text or ""

    def _drop(pattern: re.Pattern, kind: str, replacement: str) -> None:
        nonlocal out
        if pattern.search(out):
            omitted.append(kind)
            out = pattern.sub(replacement, out)

    _drop(_CODE_BLOCK, "code", " There's a code sample on screen. ")
    _drop(_TABLE, "table", " There's a table on screen. ")
    _drop(_MD_LINK, "link", r"\1")
    _drop(_URL, "link", " a link that's on screen ")
    _drop(_CITATION, "citation", "")
    out = _HEADING.sub("", out)
    out = _BOLD.sub(lambda m: m.group(1) or m.group(2) or "", out)
    out = _ITALIC.sub(r"\1", out)
    # Inline code: a short token is a term the listener needs (a flag, a
    # name); a long one is a command, and commands are for the screen.
    def _inline(match: re.Match) -> str:
        token = match.group(1).strip()
        if len(token) <= 24 and " " not in token.strip():
            return token
        omitted.append("code")
        return " the exact command is on screen "
    out = _INLINE_CODE.sub(_inline, out)
    if _PATHISH.search(out):
        omitted.append("path")
        out = _PATHISH.sub(" a file path that's on screen ", out)
    for pattern, spoken in _ABBREVIATIONS:
        out = pattern.sub(spoken, out)
    out = _enumerate_lists(out)
    out = speak_units(out)
    out = speak_numbers(out)
    out = _SPACES.sub(" ", out)
    lines = [line.strip() for line in out.splitlines()]
    out = " ".join(line for line in lines if line)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"([.!?])\s*\1+", r"\1", out)
    return out.strip(), tuple(dict.fromkeys(omitted))


def _enumerate_lists(text: str) -> str:
    """Bulleted or numbered lines become "first, ... second, ...", up to
    ten items; longer lists keep their items as plain sentences."""
    lines = text.splitlines()
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if not run:
            return
        if len(run) <= len(_ORDINALS):
            for index, item in enumerate(run):
                item = item.rstrip(".;")
                out.append(f"{_ORDINALS[index].capitalize()}, {item}.")
        else:
            out.extend(item if item.endswith((".", "!", "?")) else item + "." for item in run)
        run.clear()

    for line in lines:
        match = _BULLET.match(line)
        if match:
            run.append(line[match.end():].strip())
            continue
        flush()
        out.append(line)
    flush()
    return "\n".join(out)


# -- chunking -------------------------------------------------------------------------------------

_ABBREV_TAIL = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|No|U\.S|e\.g|i\.e)\.$", re.I)
_SENTENCE_END = re.compile(r"(?<=[.!?؟۔])\s+|(?<=[.!?؟۔])$")
_CLAUSE_BREAK = re.compile(r"(?<=[,;:،؛])\s+|\s+(?:—|–|-)\s+")

MAX_CHUNK_CHARS = 140
MIN_CHUNK_CHARS = 18
FIRST_CHUNK_CHARS = 90
SENTENCE_PAUSE_MS = 220
CLAUSE_PAUSE_MS = 90


def sentences(text: str) -> list[str]:
    """Split at sentence ends, never after an abbreviation, inside a
    number ("24.5"), or inside a quoted string."""
    out: list[str] = []
    start = 0
    quote_depth = 0
    for index, char in enumerate(text):
        if char in "\"“”":
            quote_depth ^= 1
            prev = text[index - 1] if index > 0 else " "
            nxt = text[index + 1] if index + 1 < len(text) else " "
            if not quote_depth and prev in ".!?؟۔" and (nxt.isspace() or index + 1 == len(text)):
                # A sentence that ends inside its closing quote ends there.
                candidate = text[start:index + 1].strip()
                if candidate:
                    out.append(candidate)
                start = index + 1
            continue
        if char in ".!?؟۔" and not quote_depth:
            nxt = text[index + 1] if index + 1 < len(text) else " "
            prev = text[index - 1] if index > 0 else " "
            if char == "." and prev.isdigit() and nxt.isdigit():
                continue  # 24.5
            if nxt.isspace() or index + 1 == len(text):
                candidate = text[start:index + 1].strip()
                if char == "." and _ABBREV_TAIL.search(candidate):
                    continue
                if candidate:
                    out.append(candidate)
                start = index + 1
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def _split_long(sentence: str, limit: int) -> list[str]:
    if len(sentence) <= limit:
        return [sentence]
    pieces: list[str] = []
    current = ""
    for part in _CLAUSE_BREAK.split(sentence):
        if not part:
            continue
        candidate = f"{current} {part}".strip() if current else part
        if current and len(candidate) > limit:
            pieces.append(current)
            current = part
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def chunk(text: str, *, max_chars: int = MAX_CHUNK_CHARS, min_chars: int = MIN_CHUNK_CHARS,
          first_chars: int = FIRST_CHUNK_CHARS) -> list[Chunk]:
    """Speakable chunks at semantic boundaries: sentences, then clauses
    for a long sentence. Short fragments merge forward so prosody is not
    choppy; the first chunk is kept short when a boundary allows, so
    audio can start before the rest is synthesised."""
    units: list[tuple[str, bool]] = []  # (text, ends a sentence)
    for sentence in sentences(text):
        parts = _split_long(sentence, max_chars)
        for index, part in enumerate(parts):
            units.append((part, index == len(parts) - 1))
    merged: list[tuple[str, bool]] = []
    for unit_text, ends in units:
        if merged and len(merged[-1][0]) < min_chars:
            # "Yes." alone is a choppy chunk; it rides with what follows.
            prev_text, _prev_ends = merged[-1]
            merged[-1] = (f"{prev_text} {unit_text}", ends)
        else:
            merged.append((unit_text, ends))
    if merged and len(merged[0][0]) > first_chars:
        head, ends = merged[0]
        parts = _split_long(head, first_chars)
        if len(parts) > 1 and len(parts[0]) >= min_chars:
            merged = [(parts[0], False), (" ".join(parts[1:]), ends), *merged[1:]]
    out: list[Chunk] = []
    for index, (unit_text, ends) in enumerate(merged):
        last = index == len(merged) - 1
        pause = 0 if last else (SENTENCE_PAUSE_MS if ends else CLAUSE_PAUSE_MS)
        out.append(Chunk(text=unit_text, language=language_of(unit_text), pause_ms=pause))
    return out


# -- connectors -----------------------------------------------------------------------------------

CONNECTORS: dict[str, dict[str, str]] = {
    "okay": {ENGLISH: "Okay,", FARSI: "باشه،"},
    "yeah": {ENGLISH: "Yes,", FARSI: "آره،"},  # "Yeah" comes out of Kokoro as "yaw ho" (2026-09-12)
    "right": {ENGLISH: "Right,", FARSI: "درسته،"},
    "hmm": {ENGLISH: "Hmm,", FARSI: "هوم،"},
    "ah": {ENGLISH: "Ah,", FARSI: "آها،"},
}
_ALREADY_LEADS = re.compile(r"^\s*(?:okay|ok|yeah|yes|yep|right|hmm|ah|oh|sure|well|no|alright|got it|"
                            r"باشه|آره|درسته|هوم|آها|بله|خب)\b[,.!]?", re.I)
_REQUEST = re.compile(r"^\s*(?:please\s+)?(?:can|could|would|will)\s+you\b|^\s*(?:please\s+)?"
                      r"(?:make|create|add|write|run|open|start|stop|set|send|show|find|check|fix|build|"
                      r"turn|play|remind|book|search|look)\b|\bلطفا\b|^\s*(?:می‌?تونی|میشه)\b", re.I)
_ACTION_REPLY = re.compile(r"^\s*(?:i(?:'ll| will| am| have| can|'ve)\b|done\b|on it\b|starting\b|"
                           r"running\b|created?\b|added\b|opened?\b|set\b|sent\b|انجام|دارم|می‌?کنم)", re.I)
_AGREES = re.compile(r"^\s*(?:that'?s right|correct|exactly|true|agreed|that makes sense|"
                     r"you'?re right|good point|درسته|دقیقا|بله)\b", re.I)
_REFERS_BACK = re.compile(r"\b(?:as you (?:said|mentioned|noted)|like you said|your (?:point|earlier)|"
                          r"you mentioned|going back to|همون‌?طور که گفتی)\b", re.I)
_UNCERTAIN = re.compile(r"^\s*(?:i'?m not (?:fully |entirely |completely )?(?:sure|certain)|"
                        r"it'?s hard to say|i can'?t be sure|hard to tell|مطمئن نیستم)", re.I)
_RECOGNISES = re.compile(r"^\s*(?:i see|found it|that explains|now i see|that'?s it|there it is|got it|"
                         r"that'?s why|پیدا کردم|فهمیدم|همینه)\b", re.I)

# One small connector at most, and usually none: a lead-in on every
# turn is the mechanical tic this exists to avoid. Two turns of rest
# between them keeps the rate under a third of turns.
CONNECTOR_REST_TURNS = 2


def choose_connector(reply: str, context: Context) -> str:
    """The connector kind that fits, or "". Deterministic, from the
    words themselves: nothing here rolls dice."""
    if context.is_error or context.urgent or not reply.strip():
        return ""
    if _ALREADY_LEADS.match(reply):
        return ""
    if context.turns_since_connector < CONNECTOR_REST_TURNS:
        return ""
    if _RECOGNISES.match(reply):
        kind = "ah"
    elif _UNCERTAIN.match(reply):
        kind = "hmm"
    elif _AGREES.match(reply):
        kind = "yeah"
    elif _REFERS_BACK.search(reply[:200]):
        kind = "right"
    elif _REQUEST.search(context.user_text or "") and _ACTION_REPLY.match(reply):
        kind = "okay"
    else:
        return ""
    return "" if kind == context.previous_connector else kind


def _lowered_lead(text: str, language: str) -> str:
    """After "Okay," the sentence continues in lower case -- except "I",
    a name, or anything but English, which are left as they are."""
    if language != ENGLISH or not text or text.startswith(("I ", "I'")):
        return text
    first = text.split(None, 1)[0].rstrip(".,;:!?")
    if first[:1].isupper() and (len(first) > 1 and first[1:].islower()) and first.lower() in _COMMON_STARTS:
        return text[0].lower() + text[1:]
    return text


_COMMON_STARTS = frozenset((
    "the", "that", "this", "it", "there", "here", "we", "you", "your", "let's", "let", "so", "then",
    "first", "next", "now", "just", "one", "sure", "found", "done", "on", "running", "starting", "checking",
    "adding", "creating", "opening", "setting", "sending", "looking", "yes", "no", "not", "a", "an", "in",
    "for", "to", "if", "when", "as", "my", "our", "its", "these", "those", "he", "she", "they", "done",
    "all", "everything", "nothing", "that's", "it's", "there's", "here's", "sounds", "looks", "good",
))


# -- the plan -------------------------------------------------------------------------------------

MORE_ON_SCREEN = {ENGLISH: "There's more on screen if you want it.", FARSI: "بقیه‌اش روی صفحه هست، اگر خواستی."}
NOTHING_TO_SAY = {ENGLISH: "I have nothing to say to that.", FARSI: "چیزی برای گفتن ندارم."}


class SpokenResponsePlanner:
    """`plan(text, context)`: what to say, in what pieces, in which
    language, with which lead-in -- the whole decision in one place,
    so it can be tested without a synthesiser."""

    def __init__(self, *, max_sentences: int = 6, connectors: bool = True,
                 max_chars: int = MAX_CHUNK_CHARS, first_chars: int = FIRST_CHUNK_CHARS) -> None:
        self._max_sentences = max(1, max_sentences)
        self._connectors = connectors
        self._max_chars = max_chars
        self._first_chars = first_chars

    def plan(self, text: str, context: Context | None = None) -> SpokenPlan:
        context = context or Context()
        clean, omitted = speakable(text)
        language = context.language or language_of(clean)
        if not clean:
            return SpokenPlan(chunks=(Chunk(NOTHING_TO_SAY[language], language),), language=language)
        kept = sentences(clean)
        omitted_list = list(omitted)
        if not context.urgent and len(kept) > self._max_sentences:
            clean = " ".join(kept[:self._max_sentences]) + " " + MORE_ON_SCREEN[language]
            omitted_list.append("more")
        connector = ""
        if self._connectors:
            kind = choose_connector(clean, context)
            if kind:
                connector = CONNECTORS[kind][language if language in CONNECTORS[kind] else ENGLISH]
                clean = f"{connector} {_lowered_lead(clean, language)}"
        chunks = chunk(clean, max_chars=self._max_chars, first_chars=self._first_chars)
        return SpokenPlan(chunks=tuple(chunks), connector=connector, omitted=tuple(dict.fromkeys(omitted_list)),
                          language=language)


__all__ = ["CONNECTORS", "Chunk", "Context", "SpokenPlan", "SpokenResponsePlanner", "choose_connector", "speak_units",
           "chunk", "sentences", "speak_numbers", "speakable"]
