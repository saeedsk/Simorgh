"""Who said which words of one turn.

The creator, 2026-09-13: "Sim will be engaged with multi-person
conversation where several family members say something during the
conversation; when Sim listens, it should know that each chunk of a
sentence, or even each word, may come from a different person."

One turn's audio and its timed words (whisper's, one segment per word)
come in; out come stretches of text, each with the person the voice
book puts there. The method is plain: a window slides over the audio
(1.2 s, every 0.6 s), each window is embedded and identified, each word
takes the verdict of the window centred nearest its own middle, runs of
one speaker are merged, and a run too short to mean anything (one word
between two stretches of somebody else) is given to its neighbours.
Pure: `embed` and `identify` are handed in, so this is tested with
fakes and costs nothing until the session decides a turn is long enough
to be worth it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

WINDOW_S = 1.2
HOP_S = 0.6
#: a run of fewer words than this, between two runs of the same other
#: speaker, is theirs
MIN_RUN_WORDS = 2


@dataclass(frozen=True)
class Attributed:
    speaker: str        # "" for a voice nobody in the book matches
    text: str
    start: float
    end: float
    probable: bool = False

    def as_dict(self) -> dict:
        return {"speaker": self.speaker, "text": self.text, "start": round(self.start, 2), "end": round(self.end, 2),
                "probable": self.probable}


def windows(seconds: float, *, window_s: float = WINDOW_S, hop_s: float = HOP_S) -> list[tuple[float, float]]:
    """(start, end) of each window over `seconds` of audio; the last one
    ends at the end. One window when the audio is shorter than one."""
    if seconds <= window_s:
        return [(0.0, seconds)]
    out = []
    start = 0.0
    while start + window_s < seconds:
        out.append((start, start + window_s))
        start += hop_s
    out.append((max(0.0, seconds - window_s), seconds))
    return out


def attribute(pcm: bytes, rate: int, words: Sequence, embed: Callable, identify: Callable, *,
              window_s: float = WINDOW_S, hop_s: float = HOP_S) -> list[Attributed]:
    """The turn's words grouped by who said them. `words` have `.text`,
    `.start`, `.end` in seconds of `pcm`; `embed(samples, rate)` gives a
    vector; `identify(vector)` gives something with `.name` and
    `.probable`. Words without timing come back as one stretch of
    nobody, so a caller can fall back to the whole-turn verdict."""
    timed = [w for w in words if getattr(w, "text", "").strip() and w.end > w.start]
    if not timed:
        return []
    seconds = len(pcm) / (2 * rate)
    if seconds <= 0:
        return []
    samples = [x / 32768.0 for x in memoryview(pcm).cast("h")]
    verdicts: list[tuple[float, str, bool]] = []          # (centre, speaker, probable)
    for start, end in windows(seconds, window_s=window_s, hop_s=hop_s):
        chunk = samples[int(start * rate):int(end * rate)]
        if len(chunk) < rate // 2:
            continue
        try:
            who = identify(embed(chunk, rate))
        except Exception:  # noqa: BLE001 -- one window that fails is a window of nobody
            who = None
        name = getattr(who, "name", "") if who is not None else ""
        verdicts.append(((start + end) / 2, name, bool(getattr(who, "probable", False)) if who is not None else False))
    if not verdicts:
        return []
    labelled: list[tuple[str, bool, object]] = []
    for word in timed:
        middle = (word.start + word.end) / 2
        centre, name, probable = min(verdicts, key=lambda v: abs(v[0] - middle))
        labelled.append((name, probable, word))
    runs = _merge(labelled)
    runs = _absorb_short(runs)
    return [Attributed(speaker=name, probable=probable, text=_join(ws), start=ws[0].start, end=ws[-1].end)
            for name, probable, ws in runs]


def _merge(labelled):
    runs: list[list] = []
    for name, probable, word in labelled:
        if runs and runs[-1][0] == name:
            runs[-1][2].append(word)
            runs[-1][1] = runs[-1][1] or probable   # one guessed word makes the run a guess
        else:
            runs.append([name, probable, [word]])
    return runs


#: a run of nobody longer than this stays "someone": a guest between two
#: stretches of one voice is not that voice (observer, 2026-09-13)
MAX_NOBODY_ABSORB_S = 1.0
#: a one-word run this long, heard confidently, is its own voice's ("Okay.")
MIN_LONE_WORD_S = 0.45


def _seconds(words) -> float:
    return max(0.0, float(words[-1].end) - float(words[0].start)) if words else 0.0


def _absorb_short(runs):
    """A one-word run between two runs of the same speaker is theirs. A
    run of nobody -- the window that straddled the change of voice hears
    both and matches neither -- is split between the two named
    neighbours, or joins its one neighbour at an edge."""
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, run in enumerate(runs):
            # a lone word heard confidently and long enough to be one is a
            # second person's "Okay.", not noise
            short = len(run[2]) < MIN_RUN_WORDS and (run[1] or _seconds(run[2]) < MIN_LONE_WORD_S or not run[0])
            before = runs[i - 1] if i > 0 else None
            after = runs[i + 1] if i + 1 < len(runs) else None
            if short and before is not None and after is not None and before[0] == after[0] and before[0] != run[0]:
                before[2].extend(run[2]); before[2].extend(after[2])
                before[1] = before[1] or after[1] or run[1]
                del runs[i:i + 2]
                changed = True
                break
            straddles = (run[0] == "" and before is not None and after is not None and before[0] and after[0]
                         and before[0] != after[0] and _seconds(run[2]) <= WINDOW_S + HOP_S)
            if run[0] == "" and (straddles or (_seconds(run[2]) <= MAX_NOBODY_ABSORB_S
                                               and (before is not None or after is not None))):
                if before is not None and after is not None:
                    half = len(run[2]) // 2
                    before[2].extend(run[2][:half])
                    after[2][0:0] = run[2][half:]
                elif before is not None:
                    before[2].extend(run[2])
                else:
                    after[2][0:0] = run[2]
                del runs[i]
                changed = True
                break
    return runs


def _join(words) -> str:
    return " ".join(w.text.strip() for w in words if w.text.strip()).strip()


def speakers_in(segments: Sequence[Attributed]) -> list[str]:
    """The distinct named speakers, in order of first word."""
    out: list[str] = []
    for seg in segments:
        if seg.speaker and seg.speaker not in out:
            out.append(seg.speaker)
    return out


def lines(segments: Sequence[Attributed]) -> str:
    """`Saeed: ... / Soodeh: ...` for the model and the screen."""
    return "\n".join(f"{seg.speaker or 'someone'}: {seg.text}" for seg in segments if seg.text)


__all__ = ["Attributed", "HOP_S", "MIN_RUN_WORDS", "WINDOW_S", "attribute", "lines", "speakers_in", "windows"]
