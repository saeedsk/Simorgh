"""A calibration set recorded once and reused: `voice calibrate`.

The creator, 2026-09-22: "an option which later you can re-use to
calibrate the system, similar to voice enrolling. I don't want to repeat
this again if you find a bug. Record my voice, make the necessary
metadata, and later if the model needs retraining use that recording
instead of asking me again."

So a person reads the lines of `calibration_script.py` once, each take
is checked the moment it is heard (too short or cut off, too quiet,
clipped, too noisy, not their voice, or a gross misread) and re-asked
at once with the reason, and every accepted take is filed as a WAV plus
a `manifest.jsonl` row that says everything a later measurement needs
(`Row` below). A session can stop at any line and resume later: a line
that already has a take is never asked for again.

The set is reused by:
  * `load()` -- the takes as float samples plus their metadata, for any
    measurement (`tools/stt_calibration.py`: WER and latency per
    language, stage 3 item 6);
  * `voice relearn <name>` -- which prefers these clean, labelled takes
    over the ordinary kept turns (`service._relearn_from_kept`).

The folder is `[voice] calibration_dir` (default
`workspace/voice/calibration`), one sub-folder per person. It is NEVER
pruned: `session.prune_kept_audio` globs only the top level of
`audio_dir`, and nothing else deletes here. It belongs in backups.

Stdlib only, like the rest of the core: the levels are computed in
Python over int16 frames, which is milliseconds for a few seconds of
audio.
"""

from __future__ import annotations

import json
import math
import re
import time
import unicodedata
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from .calibration_script import LINES, SCRIPT_VERSION, Line, by_id

MANIFEST = "manifest.jsonl"

# ------------------------------------------------------------------ the bars
# What a take must clear to be kept. Every one of these is a reason a
# later measurement would be wrong, not a matter of taste: a clipped
# take measures the clipping, a take in a noisy room measures the room.

#: Calibrated against the creator's own 35 kept turns (2026-09-22): the
#: first estimates (-42 dBFS speech, -45 dBFS noise floor, 0.1% clipping)
#: rejected 17 of them, mostly "too noisy" at a -42..-45 dBFS floor whose
#: speech stood a median 20.7 dB above it. The set is meant to hold HIS
#: room, not a studio: the signal-to-noise bar does the real work, and
#: the absolute floor only turns away a genuinely loud room.
#: Too short: less speech than the line could possibly take to say.
MIN_SPEECH_S = 0.4
MIN_SPEECH_S_PER_WORD = 0.1
#: Too quiet: the loud end of the speech (90th percentile of 20 ms frame
#: levels) under this. A laptop microphone at a metre hears ordinary
#: speech around -35 to -25 dBFS.
MIN_SPEECH_DBFS = -48.0
#: Clipping: more than this fraction of samples at full scale.
CLIP_LEVEL = 32600
MAX_CLIP_RATIO = 0.01
#: Noise: the quiet end (10th percentile of frame levels) above this,
#: or the speech less than `MIN_SNR_DB` above it.
MAX_NOISE_DBFS = -35.0
MIN_SNR_DB = 12.0
#: Cut off: the take ran into the turn's length limit, or its last
#: 100 ms are still speech (the person was stopped mid-word).
CUT_TAIL_S = 0.1
CUT_TAIL_WITHIN_DB = 6.0
#: A gross misread: the recogniser's words this far from the line. Farsi
#: gets a looser bar because the recogniser is weaker there, and a take
#: must not be refused for the recogniser's failing -- measuring that
#: failing is what the set is FOR.
MAX_WER = {"en": 0.5, "fa": 0.75}
DEFAULT_MAX_WER = 0.6

FRAME_S = 0.02


# ------------------------------------------------------------------ WER
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_CHAR_VARIANTS = str.maketrans({
    "ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "ؤ": "و",
    "أ": "ا", "إ": "ا", "ٱ": "ا", "آ": "ا",
    "\u200c": "",   # ZWNJ: می‌خواهم / میخواهم are one word
    "\u200d": "", "\u200f": "", "\u200e": "", "\u0640": "",   # ZWJ, RLM, LRM, tatweel
})
_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED]")
#: Persian particles written joined, with a ZWNJ, or with a space: all
#: three spellings are the same word, so a detached one is re-attached.
_FA_PREFIXES = ("می", "نمی", "بی")
_FA_SUFFIXES = ("ی", "ها", "های", "هایی", "تر", "ترین", "ای", "ام", "ات", "اش", "ست")

_EN_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
_EN_ORDINAL_UNITS = {w: i for i, w in enumerate(
    "zeroth first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth "
    "fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth".split())}
_EN_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
            "ninety": 90, "twentieth": 20, "thirtieth": 30, "fortieth": 40, "fiftieth": 50}
_FA_UNITS = {"صفر": 0, "یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6, "شیش": 6, "هفت": 7,
             "هشت": 8, "نه": 9, "ده": 10, "یازده": 11, "دوازده": 12, "سیزده": 13, "چهارده": 14,
             "پانزده": 15, "پونزده": 15, "شانزده": 16, "شونزده": 16, "هفده": 17, "هجده": 18,
             "هیجده": 18, "نوزده": 19}
_FA_TENS = {"بیست": 20, "سی": 30, "چهل": 40, "پنجاه": 50, "شصت": 60, "هفتاد": 70, "هشتاد": 80, "نود": 90}
_ORDINAL_DIGITS = re.compile(r"^(\d+)(?:st|nd|rd|th)$")


def _number_value(word: str) -> tuple[str, int] | None:
    """(kind, value) for a number word: kind is unit, tens, hundred or thousand."""
    if word in _EN_UNITS:
        return "unit", _EN_UNITS[word]
    if word in _EN_ORDINAL_UNITS:
        return "unit", _EN_ORDINAL_UNITS[word]
    if word in _FA_UNITS:
        return "unit", _FA_UNITS[word]
    if word in _EN_TENS:
        return "tens", _EN_TENS[word]
    if word in _FA_TENS:
        return "tens", _FA_TENS[word]
    if word in ("hundred", "hundredth", "صد"):
        return "hundred", 100
    if word in ("thousand", "thousandth", "هزار"):
        return "thousand", 1000
    return None


def _numbers_to_digits(words: list[str]) -> list[str]:
    """"twenty seven" -> "27", "three hundred and fifty" -> "350",
    "بیست و پنج" -> "25", "nine thirty" -> "9 30" (a unit then a ten
    is two numbers, the way a time is said), "14th" -> "14"."""
    out: list[str] = []
    i = 0
    while i < len(words):
        word = words[i]
        match = _ORDINAL_DIGITS.match(word)
        if match:
            out.append(match.group(1))
            i += 1
            continue
        first = _number_value(word)
        if first is None:
            out.append(word)
            i += 1
            continue
        total, current, last = 0, 0, ""
        j = i
        while j < len(words):
            value = _number_value(words[j])
            joiner = words[j] in ("and", "و") and j + 1 < len(words) and _number_value(words[j + 1]) is not None
            if joiner and last in ("hundred", "thousand", "tens"):
                if last == "tens" and _number_value(words[j + 1])[0] != "unit":
                    break
                j += 1
                continue
            if value is None:
                break
            kind, v = value
            if kind == "unit":
                if last in ("unit",) or (last == "tens" and (current % 10 or v >= 10)):
                    break              # "six thirty" / "four eight": a new number
                current += v
            elif kind == "tens":
                if last in ("unit", "tens"):
                    break
                current += v
            elif kind == "hundred":
                if last == "hundred":
                    break
                current = max(current, 1) * 100
            else:
                if last == "thousand":
                    break
                total += max(current, 1) * 1000
                current = 0
            last = kind
            j += 1
        out.append(str(total + current))
        i = max(j, i + 1)
    return out


def normalise(text: str) -> list[str]:
    """The words of `text` for scoring: case, punctuation, Persian and
    Arabic letter variants (ي/ی, ك/ک, ...), diacritics, ZWNJ and detached
    Persian particles, Persian and Arabic-Indic digits, and number words
    folded, so a recogniser is scored on the words and not the typing."""
    text = unicodedata.normalize("NFKC", text or "").translate(_PERSIAN_DIGITS).translate(_CHAR_VARIANTS)
    text = _DIACRITICS.sub("", text).casefold()
    text = re.sub(r"(\d)[:.](\d)", r"\1 \2", text)          # 9:30, 8.15 -> 9 30
    text = text.replace("%", " percent ")
    text = re.sub(r"(?<=\w)['’.](?=\w)", "", text)           # what's, a.m., o'clock
    text = re.sub(r"[^\w\s]", " ", text)                     # the rest of the punctuation, both scripts
    words = text.split()
    joined: list[str] = []
    for word in words:
        if joined and word in _FA_SUFFIXES and re.match(r"[\u0600-\u06FF]", joined[-1]):
            joined[-1] += word
        elif joined and joined[-1] in _FA_PREFIXES and re.match(r"[\u0600-\u06FF]", word):
            joined[-1] += word
        else:
            joined.append(word)
    return _numbers_to_digits(joined)


def word_errors(reference: str, hypothesis: str) -> tuple[int, int]:
    """(substitutions + deletions + insertions, reference words), after
    `normalise`: the pieces of a corpus WER."""
    ref, hyp = normalise(reference), normalise(hypothesis)
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        row = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            row[j] = min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + (r != h))
        previous = row
    return previous[-1], len(ref)


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate of `hypothesis` against `reference` (word-level
    Levenshtein over `normalise`d words). An empty reference scores 0.0
    against an empty hypothesis and 1.0 against anything else."""
    errors, words = word_errors(reference, hypothesis)
    if not words:
        return 0.0 if errors == 0 else 1.0
    return errors / words


# ------------------------------------------------------------------ levels
@dataclass(frozen=True)
class Levels:
    """What a take sounds like, measured from its samples alone."""

    duration_s: float
    speech_s: float
    speech_dbfs: float
    noise_dbfs: float
    clipping: float
    tail_dbfs: float

    @property
    def snr_db(self) -> float:
        return self.speech_dbfs - self.noise_dbfs


def _dbfs(rms: float) -> float:
    return 20.0 * math.log10(rms / 32768.0) if rms > 0 else -120.0


def measure(pcm: bytes, sample_rate: int = 16000) -> Levels:
    """Levels of little-endian int16 mono `pcm`, in 20 ms frames."""
    if len(pcm) % 2:
        pcm = pcm[:-1]
    samples = memoryview(bytes(pcm)).cast("h")
    n = len(samples)
    if not n:
        return Levels(0.0, 0.0, -120.0, -120.0, 0.0, -120.0)
    size = max(1, int(sample_rate * FRAME_S))
    levels = []
    for start in range(0, n, size):
        frame = samples[start:start + size]
        levels.append(_dbfs(math.sqrt(sum(x * x for x in frame) / len(frame))))
    ranked = sorted(levels)
    noise = ranked[int(0.1 * (len(ranked) - 1))]
    speech = ranked[int(0.9 * (len(ranked) - 1))]
    bar = max(noise + 10.0, -55.0)
    speech_frames = sum(1 for level in levels if level > bar)
    tail = levels[-max(1, int(CUT_TAIL_S / FRAME_S)):]
    clipped = sum(1 for x in samples if x >= CLIP_LEVEL or x <= -CLIP_LEVEL)
    return Levels(duration_s=n / float(sample_rate), speech_s=speech_frames * size / float(sample_rate),
                  speech_dbfs=speech, noise_dbfs=noise, clipping=clipped / n,
                  tail_dbfs=max(tail) if tail else -120.0)


def level_problems(levels: Levels, *, words: int, max_utterance_s: float = 0.0) -> list[str]:
    """Why these levels make a bad take, in words for the person; [] if none."""
    problems = []
    need = max(MIN_SPEECH_S, MIN_SPEECH_S_PER_WORD * max(1, words))
    if levels.speech_s < need:
        problems.append(f"too short ({levels.speech_s:.1f} s of speech; the line needs at least {need:.1f} s)")
    if max_utterance_s and levels.duration_s >= max_utterance_s - 0.3:
        problems.append("cut off at the turn's length limit")
    elif (levels.snr_db >= MIN_SNR_DB and levels.duration_s > 1.0
          and levels.tail_dbfs >= levels.speech_dbfs - CUT_TAIL_WITHIN_DB):
        problems.append("cut off -- it ends mid-word")
    if levels.speech_dbfs < MIN_SPEECH_DBFS:
        problems.append(f"too quiet (speech at {levels.speech_dbfs:.0f} dBFS, needs {MIN_SPEECH_DBFS:.0f}) "
                        "-- a little closer or a little louder")
    if levels.clipping > MAX_CLIP_RATIO:
        problems.append(f"clipping ({levels.clipping:.1%} of samples at full scale) -- a little further away")
    if levels.noise_dbfs > MAX_NOISE_DBFS:
        problems.append(f"the room is too noisy (noise floor {levels.noise_dbfs:.0f} dBFS, needs under "
                        f"{MAX_NOISE_DBFS:.0f})")
    elif levels.speech_dbfs >= MIN_SPEECH_DBFS and levels.snr_db < MIN_SNR_DB:
        problems.append(f"too little voice over the room ({levels.snr_db:.0f} dB, needs {MIN_SNR_DB:.0f})")
    return problems


# ------------------------------------------------------------------ the files
def safe_person(name: str) -> str:
    """The folder name for a person: their household spelling, filesystem-safe."""
    from simorgh.contracts.household import member

    known = member(name)
    name = known.name if known is not None else (name or "").strip()
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name).strip("_") or "person"


def person_folder(folder: Path | str, person: str) -> Path:
    return Path(folder) / safe_person(person)


def read_rows(folder: Path | str, person: str | None = None) -> list[dict]:
    """Every manifest row under `folder` (one person, or everybody).
    A malformed line is skipped, never fatal: the set is years of work."""
    base = Path(folder)
    people = [person_folder(base, person)] if person else sorted(p for p in base.glob("*") if p.is_dir())
    rows: list[dict] = []
    for place in people:
        path = place / MANIFEST
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in text.splitlines():
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if isinstance(row, dict):
                row.setdefault("_folder", str(place))
                rows.append(row)
    return rows


def append_row(folder: Path | str, person: str, row: dict) -> None:
    """One take's row, appended and flushed: a crash between two takes
    loses at most the take in hand."""
    place = person_folder(folder, person)
    place.mkdir(parents=True, exist_ok=True)
    with (place / MANIFEST).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({k: v for k, v in row.items() if not k.startswith("_")}, ensure_ascii=False) + "\n")
        handle.flush()


def done_ids(folder: Path | str, person: str) -> set[str]:
    """The script lines this person already has a take for -- read from
    the same text they are scripted with today, so a line whose words
    ever changed is asked again rather than silently mislabelled."""
    done = set()
    for row in read_rows(folder, person):
        line = by_id(str(row.get("line_id") or ""))
        if line is not None and row.get("script_text", line.text) == line.text:
            done.add(line.id)
    return done


@dataclass(frozen=True)
class Take:
    """One recorded line: float samples in [-1, 1) and its manifest row."""

    person: str
    line_id: str
    language: str
    reference: str
    samples: list[float]
    sample_rate: int
    path: Path
    romanisation: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def seconds(self) -> float:
        return len(self.samples) / float(self.sample_rate or 16000)

    @property
    def pcm(self) -> bytes:
        """The samples back as int16 bytes, for an engine that wants `Audio`."""
        import array

        return array.array("h", (max(-32768, min(32767, int(round(x * 32768.0)))) for x in self.samples)).tobytes()


def read_samples(path: Path | str) -> tuple[list[float], int]:
    """A 16-bit mono WAV as float samples (the `/32768.0` the embedder
    and every recogniser want -- raw bytes raise inside `np.asarray`)."""
    with wave.open(str(path)) as handle:
        pcm = handle.readframes(handle.getnframes())
        rate = handle.getframerate()
        width = handle.getsampwidth()
    if width != 2:
        raise ValueError(f"{path}: {8 * width}-bit audio; calibration takes are 16-bit")
    if len(pcm) % 2:
        pcm = pcm[:-1]
    return [x / 32768.0 for x in memoryview(pcm).cast("h")], rate


def load(person: str | None = None, language: str | None = None, *,
         folder: Path | str | None = None) -> list[Take]:
    """The calibration set: every accepted take (one person, one
    language, or all), as float samples plus metadata, in manifest order.
    A row whose WAV is missing or unreadable is skipped."""
    if folder is None:
        from .config import Config

        folder = Config().calibration_dir
    takes: list[Take] = []
    for row in read_rows(folder, person):
        if language and str(row.get("language") or "") != language:
            continue
        path = Path(row["_folder"]) / str(row.get("file") or "")
        try:
            samples, rate = read_samples(path)
        except (OSError, ValueError, EOFError, wave.Error):
            continue
        takes.append(Take(person=str(row.get("person") or ""), line_id=str(row.get("line_id") or ""),
                          language=str(row.get("language") or ""), reference=str(row.get("reference") or ""),
                          romanisation=str(row.get("romanisation") or ""), samples=samples, sample_rate=rate,
                          path=path, meta={k: v for k, v in row.items() if not k.startswith("_")}))
    return takes


# ------------------------------------------------------------------ spoken controls
_CONTROLS = {
    "keep": ("keep it", "keep that", "keep that one", "keep what i said", "i meant that", "that is what i meant",
             "thats what i meant", "i said it that way on purpose"),
    "accept": ("that was right", "i read it right", "i said it right", "it was right", "accept it",
               "accept that", "i said it correctly"),
    "skip": ("skip", "skip it", "skip this", "skip this one", "skip that", "skip that one", "next line",
             "rad kon", "رد کن", "بعدی"),
    "stop": ("stop calibrating", "stop calibration", "pause calibration", "that is enough for today",
             "thats enough for today", "stop recording", "بسه"),
}
_CONTROL_LOOKUP = {" ".join(normalise(p)): kind for kind, phrases in _CONTROLS.items() for p in phrases}


def control_word(text: str) -> str:
    """"keep", "accept", "skip", "stop" when `text` is one of the few
    things a person says to the calibration itself; "" otherwise."""
    words = [w for w in normalise(text) if w not in ("sim", "please", "ok", "okay")]
    kind = _CONTROL_LOOKUP.get(" ".join(words), "")
    if kind:
        return kind
    from .commands import OFF, MUTE, STOP, spoken_command

    return "stop" if spoken_command(text) in (STOP, OFF, MUTE) else ""


# ------------------------------------------------------------------ one session
@dataclass
class Verdict:
    """What became of one utterance during calibration."""

    kind: str                   # accepted | rejected | kept | skipped | stopped | finished | ignored
    message: str                # for the screen
    reasons: list[str] = field(default_factory=list)
    row: dict = field(default_factory=dict)
    spoken: str = ""            # the short version, when the run speaks


class CalibrationRun:
    """One person reading the script: which line is next, whether a take
    is good enough, and where it is filed. Synchronous and free of the
    session, so every rule is testable with bytes and a vector.

    `book` is the speaker book (or None); `score_bar` the threshold a
    take must score against the person's enrolled profile.
    """

    def __init__(self, person: str, folder: Path | str, *, script: Sequence[Line] = LINES, book=None,
                 score_bar: float | None = None, device: str = "", microphone: str = "", room: str = "",
                 distance: str = "", aloud: bool = False, max_utterance_s: float = 0.0,
                 measure_fn: Callable[[bytes, int], Levels] = measure, clock: Callable[[], float] = time.time) -> None:
        self.person = person
        self.folder = Path(folder)
        self.script = list(script)
        self.book = book
        self.score_bar = score_bar if score_bar is not None else float(getattr(book, "threshold", 0.5) or 0.5)
        self.device = device
        self.microphone = microphone
        self.room = room
        self.distance = distance
        self.aloud = aloud
        self.max_utterance_s = max_utterance_s
        self._measure = measure_fn
        self._clock = clock
        done = done_ids(self.folder, person)
        self.done_before = sum(1 for line in self.script if line.id in done)
        self.todo: list[Line] = [line for line in self.script if line.id not in done]
        self.skipped: list[str] = []
        self.accepted = 0
        self.rejected = 0
        self.tries = 0                  # rejections of the current line
        #: The last rejected take, while the person may still say it was right.
        self.pending: dict | None = None

    # -- where we are
    @property
    def current(self) -> Line | None:
        return self.todo[0] if self.todo else None

    @property
    def finished(self) -> bool:
        return not self.todo

    def done_count(self) -> int:
        return self.done_before + self.accepted

    def progress(self) -> str:
        """"12/67, English" -- the position of the line on screen now."""
        line = self.current
        total = len(self.script)
        if line is None:
            return f"{self.done_count()}/{total} done"
        return f"{self.done_count() + 1}/{total}, {line.language_name}"

    def prompt(self) -> str:
        """The current line as the screen shows it."""
        line = self.current
        if line is None:
            return f"calibration for {self.person} is complete: {self.done_count()}/{len(self.script)} lines."
        text = f"calibrate {self.person} {self.progress()} ({line.id}) -- read:\n    {line.text}"
        if line.romanisation:
            text += f"\n    ({line.romanisation})"
        if line.note:
            text += f"\n    [{line.note}]"
        return text

    def summary(self) -> str:
        return summary(self.folder, self.person, self.script)

    # -- judging a take
    def judge(self, pcm: bytes, *, transcript: str, vector=None, engine: str = "", heard_language: str = "",
              confidence: float = 0.0, sample_rate: int = 16000) -> tuple[list[str], dict]:
        """(reasons to refuse, the manifest row it would get)."""
        line = self.current
        assert line is not None, "nothing left to read"
        levels = self._measure(pcm, sample_rate)
        reasons = level_problems(levels, words=len(normalise(line.text)), max_utterance_s=self.max_utterance_s)
        score, coherence_now, profile_takes = None, None, 0
        person = self.book.get(self.person) if self.book is not None else None
        if person is not None and person.embeddings and vector is not None:
            from .speakers import coherence

            score = float(self.book.score(vector, person))
            coherence_now = float(coherence(person.embeddings))
            profile_takes = len(person.embeddings)
            if score < self.score_bar:
                reasons.append(f"that did not sound like {person.name} ({score:.2f} against a bar of "
                               f"{self.score_bar:.2f})")
        error = wer(line.text, transcript)
        cut = "cut off -- it ends mid-word"
        if cut in reasons:
            # The tail test alone refused a clean read twice, live: a line
            # ending on a held sound ("...home with Aran." -- the final /n/)
            # is still loud when the take ends (2026-09-22, en-007). A take
            # really cut mid-word loses its last word, so it stands only
            # when the recogniser did NOT hear the line's last word.
            said, wanted = normalise(transcript), normalise(line.text)
            if said and wanted and said[-1] == wanted[-1]:
                reasons.remove(cut)
        bar = MAX_WER.get(line.language, DEFAULT_MAX_WER)
        misread = error > bar
        if misread:
            reasons.append(f"I heard \"{transcript.strip() or '(nothing)'}\" -- {error:.0%} of the words differ")
        row = {
            "line_id": line.id, "script_version": SCRIPT_VERSION, "script_text": line.text,
            "reference": line.text, "romanisation": line.romanisation, "language": line.language,
            "tags": list(line.tags), "person": self.person, "recorded_at": self._clock(),
            "device": self.device, "microphone": self.microphone, "sample_rate": int(sample_rate),
            "duration_s": round(levels.duration_s, 3), "speech_s": round(levels.speech_s, 3),
            "speech_dbfs": round(levels.speech_dbfs, 1), "noise_dbfs": round(levels.noise_dbfs, 1),
            "snr_db": round(levels.snr_db, 1), "clipping": round(levels.clipping, 5),
            "speaker_score": None if score is None else round(score, 3),
            "speaker_bar": round(self.score_bar, 3),
            "profile_coherence": None if coherence_now is None else round(coherence_now, 3),
            "profile_takes": profile_takes,
            "stt_engine": engine, "stt_transcript": transcript, "stt_language": heard_language,
            "stt_confidence": round(float(confidence), 4), "wer": round(error, 3),
            "room": self.room, "distance": self.distance, "aloud": self.aloud,
        }
        return reasons, row

    def consider(self, pcm: bytes, *, transcript: str, vector=None, engine: str = "", heard_language: str = "",
                 confidence: float = 0.0, sample_rate: int = 16000) -> Verdict:
        """One utterance heard while calibrating: a take, a control, or a refusal."""
        line = self.current
        if line is None:
            return Verdict("finished", self.prompt())
        close = wer(line.text, transcript) <= MAX_WER.get(line.language, DEFAULT_MAX_WER)
        control = "" if close else control_word(transcript)
        if control == "stop":
            return Verdict("stopped", self.stopped_message())
        if control == "skip":
            return self.skip()
        if control in ("keep", "accept"):
            return self.keep_pending(control)
        reasons, row = self.judge(pcm, transcript=transcript, vector=vector, engine=engine,
                                  heard_language=heard_language, confidence=confidence, sample_rate=sample_rate)
        if reasons:
            self.rejected += 1
            self.tries += 1
            only_misread = len(reasons) == 1 and row["wer"] > MAX_WER.get(line.language, DEFAULT_MAX_WER)
            self.pending = {"pcm": bytes(pcm), "row": row, "sample_rate": sample_rate} if only_misread else None
            how = ("say it again" + (", or say \"keep it\" if you changed the words on purpose (your words become "
                                     "the reference), or \"that was right\" if you read it as written"
                                     if only_misread else "")
                   + (", or \"skip\" to leave this line for another day" if self.tries >= 2 else ""))
            message = f"not kept, {'; '.join(reasons)} -- {how}.\n" + self.prompt()
            spoken = f"Not kept: {reasons[0].split(' (')[0].split(' --')[0]}. Once more, please."
            return Verdict("rejected", message, reasons=reasons, row=row, spoken=spoken)
        return self._accept(bytes(pcm), row, sample_rate)

    # -- filing
    def _accept(self, pcm: bytes, row: dict, sample_rate: int, *, note: str = "") -> Verdict:
        from .api import Audio
        from .audio import write_wav

        line = self.current
        stamp = int(self._clock() * 1000)
        name = f"{line.id}-{stamp}.wav"
        place = person_folder(self.folder, self.person)
        write_wav(place / name, Audio(bytes(pcm), int(sample_rate)))
        row = {**row, "file": name}
        append_row(self.folder, self.person, row)
        self.todo.pop(0)
        self.accepted += 1
        self.tries = 0
        self.pending = None
        kept = f"kept {line.id}{note} (speech {row['speech_dbfs']:.0f} dBFS, noise {row['noise_dbfs']:.0f}, " \
               f"wer {row['wer']:.2f}" + (f", voice {row['speaker_score']:.2f}" if row.get("speaker_score") is not None else "") + ")"
        if self.finished:
            return Verdict("finished", f"{kept}.\n{self.prompt()} Filed in {place}.", row=row,
                           spoken=f"That is every line, {self.person}. Thank you.")
        return Verdict("accepted", f"{kept}.\n{self.prompt()}", row=row, spoken="")

    def keep_pending(self, how: str = "keep") -> Verdict:
        """The person says the refused take was right: "keep" (they changed
        the words on purpose -- their words become the reference) or
        "accept" (they read it as written; the recogniser was wrong)."""
        if self.pending is None or self.current is None:
            return Verdict("ignored", "nothing to keep -- only a take refused for its words can be kept "
                                      "as it was.\n" + self.prompt())
        pending, self.pending = self.pending, None
        row = dict(pending["row"])
        if how == "keep":
            row["reference"] = row["stt_transcript"]
            row["reference_from"] = "speaker"       # a deliberate variation, in their own words
            row["wer"] = 0.0
            note = ", with your words as the reference"
        else:
            row["reference_from"] = "script"
            row["misread_overridden"] = True        # the recogniser was wrong, not the reader
            note = ", as read (the recogniser was wrong)"
        return self._accept(pending["pcm"], row, pending["sample_rate"], note=note)

    def skip(self) -> Verdict:
        """Leave the current line for another session. Not recorded, so a
        resume asks for it again."""
        line = self.current
        if line is None:
            return Verdict("finished", self.prompt())
        self.todo.pop(0)
        self.skipped.append(line.id)
        self.tries = 0
        self.pending = None
        if self.finished:
            return Verdict("finished", f"skipped {line.id}.\n{self.stopped_message()}")
        return Verdict("skipped", f"skipped {line.id}; it will be asked again next time.\n{self.prompt()}")

    def stopped_message(self) -> str:
        left = len(self.todo) + len(self.skipped)
        return (f"calibration for {self.person} paused at {self.done_count()}/{len(self.script)} "
                f"({self.accepted} kept this session, {left} still to read). "
                f"`voice calibrate {self.person}` carries on from here -- nothing already kept is asked again.")


def summary(folder: Path | str, person: str, script: Sequence[Line] = LINES) -> str:
    """"Saeed: 12/67 lines -- English 10/51, Farsi 2/16", from the manifest."""
    done = done_ids(folder, person)
    parts = []
    for code in dict.fromkeys(line.language for line in script):
        of = [line for line in script if line.language == code]
        parts.append(f"{of[0].language_name} {sum(1 for line in of if line.id in done)}/{len(of)}")
    total = sum(1 for line in script if line.id in done)
    return f"{safe_person(person)}: {total}/{len(script)} lines -- " + ", ".join(parts)


__all__ = ["CalibrationRun", "Levels", "MANIFEST", "MAX_WER", "Take", "Verdict", "append_row", "control_word",
           "done_ids", "level_problems", "load", "measure", "normalise", "person_folder", "read_rows",
           "read_samples", "summary", "wer", "word_errors"]
