#!/usr/bin/env python3
"""Replay a person's calibration set through Sim's real listening path.

    python tools/voice_replay.py                  # the creator's set, every take
    python tools/voice_replay.py --person Saeed --limit 10
    python tools/voice_replay.py --json out.json  # the rows, for a findings entry

Why this exists (2026-09-22): a day of voice features passed their unit
tests -- fake microphones, scripted recognisers -- and every one of them
failed a different way the first time the creator used it: a profile
that did not match his voice, a pause line that split in two, Farsi
refused as somebody else, a misheard "Hey Sim" that left a stale request
to be acted on. Unit tests assert shape; only running the system asserts
behaviour. The calibration set is his real voice, in his real room,
with the words he actually said on record -- so it is the test.

Each take goes into a booted, sandboxed Sim exactly as a microphone
would deliver it: the real session (VAD, turn-taking), the REAL
recogniser (whisper, as configured live), a COPY of the real speaker
book, the live `[voice]` settings. Per take it records:

  heard       what whisper made of it, and its word error against the line
  who         whose voice the book named, and the score
  addressed   whether Sim took it as said to it (a `percept.text.received`)
  acted       any tool Sim proposed because of it

and it FAILS (exit 1) when the voice is not placed as the person often
enough, or when a line that names Sim is not taken as addressed often
enough -- the two things the family notices first. The model behind the
answers is the offline floor unless `--paid`: whether Sim ACTS is only
meaningful with a real model, and costs money.

Nothing here writes to the live data: the book is copied, the sandbox
has its own data directory, and the recordings are only read.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

#: A take whose voice is placed as the person at least this often passes.
MIN_IDENTIFIED = 0.9
#: Lines that name Sim, taken as said to Sim at least this often.
MIN_ADDRESSED = 0.9
#: How long a take may take to come back as a transcript.
TAKE_TIMEOUT_S = 45.0
NAMES_SIM = ("sim-start", "sim-middle", "sim-end")


def live_voice_settings() -> dict:
    """The live `[voice]` table, so the replay hears with the same ears."""
    path = Path(os.environ.get("SIMORGH_CONFIG") or Path.home() / ".simorgh" / "simorgh.toml")
    try:
        return dict(tomllib.loads(path.read_text()).get("voice") or {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _tags(line_id: str) -> tuple[str, ...]:
    from simorgh.voice.calibration_script import by_id

    try:
        return tuple(by_id(line_id).tags)
    except Exception:  # noqa: BLE001 -- a line from an older script has no tags to read
        return ()


async def replay(person: str, *, limit: int = 0, paid: bool = False, language: str = "") -> list[dict]:
    from simorgh.contracts import topics
    from simorgh.evals.house.director import Director
    from simorgh.evals.house.sandbox import Sandbox
    from simorgh.voice.api import Audio
    from simorgh.voice.calibration import load, wer
    from simorgh.voice.config import Config as VoiceConfig
    from simorgh.voice.stt import open_recogniser

    takes = load(person, language or None)
    if limit:
        takes = takes[:limit]
    if not takes:
        raise SystemExit(f"{person} has no calibration takes -- `voice calibrate {person}` records them")

    live = live_voice_settings()
    recogniser, why = open_recogniser(VoiceConfig.from_mapping(live), repo_root=REPO)
    if recogniser is None:
        raise SystemExit(f"no recogniser: {why}")

    book = Path(tempfile.mkdtemp(prefix="simorgh-replay-book-"))
    shutil.copytree(REPO / "workspace" / "voice" / "speakers", book, dirs_exist_ok=True)
    voice = {**live, "speakers_dir": str(book), "keep_audio": False, "speak_replies": False,
             "enabled": True, "auto_listen": True}
    config = {"voice": voice}
    secrets = dict(os.environ) if paid else None
    if paid:
        config["cognition"] = {"provider_order": ["together", "gemini", "floor"], "max_spend_usd": 1.0}

    rows: list[dict] = []
    try:
        async with Sandbox(config=config, recogniser=recogniser, secrets=secrets,
                           spend_cap_usd=1.0 if paid else 0.0) as box:
            director = Director(box)
            bus = box.kernel.bus
            seen: list[tuple[float, str, dict]] = []

            async def _keep(message):
                seen.append((time.monotonic(), message.type, dict(message.payload or {})))

            subs = [await bus.subscribe(t, _keep)
                    for t in (topics.VOICE_TRANSCRIPT, topics.PERCEPT_TEXT_RECEIVED, topics.TASK_STEP)]
            for n, take in enumerate(takes, 1):
                await director._ready_to_listen()  # noqa: SLF001 -- the director's own wait
                start = time.monotonic()
                box.microphone.feed(Audio(take.pcm, take.sample_rate))
                transcript = None
                while time.monotonic() - start < TAKE_TIMEOUT_S:
                    transcript = next((p for ts, kind, p in seen
                                       if ts >= start and kind == topics.VOICE_TRANSCRIPT and p.get("text") and not p.get("partial")), None)
                    if transcript is not None:
                        break
                    await asyncio.sleep(0.1)
                await asyncio.sleep(2.0)          # the turn's own decisions (addressed, acting) settle
                window = [(kind, p) for ts, kind, p in seen if ts >= start]
                heard = str((transcript or {}).get("text") or "")
                row = {
                    "line": take.line_id, "language": take.language, "tags": list(_tags(take.line_id)),
                    "reference": take.reference, "heard": heard,
                    "wer": round(wer(take.reference, heard), 3) if heard else 1.0,
                    "who": str((transcript or {}).get("speaker") or ""),
                    "score": (transcript or {}).get("speaker_score"),
                    "addressed": any(kind == topics.PERCEPT_TEXT_RECEIVED for kind, _ in window),
                    "acted": [str(p.get("tool")) for kind, p in window if kind == topics.TASK_STEP and p.get("tool")],
                }
                rows.append(row)
                mark = "ok " if row["who"] == person else "WHO"
                print(f"{n:3}/{len(takes)} {row['line']:7} {mark} {row['who'] or '-':7} "
                      f"{row['score'] if row['score'] is not None else '-':>6} "
                      f"{'addr' if row['addressed'] else '    '} wer={row['wer']:.2f}  {heard[:60]}",
                      flush=True)
            for sub in subs:
                await sub.unsubscribe()
    finally:
        shutil.rmtree(book, ignore_errors=True)
    return rows


def verdict(rows: list[dict], person: str) -> tuple[bool, list[str]]:
    lines = []
    ok = True
    placed = sum(1 for r in rows if r["who"] == person)
    share = placed / len(rows) if rows else 0.0
    lines.append(f"identified as {person}: {placed}/{len(rows)} ({share:.0%}, needs {MIN_IDENTIFIED:.0%})")
    ok &= share >= MIN_IDENTIFIED
    named = [r for r in rows if any(t in r["tags"] for t in NAMES_SIM)]
    if named:
        taken = sum(1 for r in named if r["addressed"])
        share = taken / len(named)
        lines.append(f"lines that name Sim taken as addressed: {taken}/{len(named)} ({share:.0%}, "
                     f"needs {MIN_ADDRESSED:.0%})")
        ok &= share >= MIN_ADDRESSED
    for lang in sorted({r["language"] for r in rows}):
        these = [r for r in rows if r["language"] == lang]
        lines.append(f"{lang}: mean take WER {sum(r['wer'] for r in these) / len(these):.1%} over {len(these)}")
    acted = [r for r in rows if r["acted"]]
    if acted:
        lines.append(f"proposed an action on {len(acted)} take(s): "
                     + ", ".join(f"{r['line']}->{'/'.join(r['acted'])}" for r in acted[:6]))
    return ok, lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--person", default="Saeed")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--language", default="", choices=["", "en", "fa"])
    ap.add_argument("--paid", action="store_true", help="a real model behind the answers (costs money)")
    ap.add_argument("--json", default="", metavar="PATH")
    args = ap.parse_args()
    rows = asyncio.run(replay(args.person, limit=args.limit, paid=args.paid, language=args.language))
    ok, lines = verdict(rows, args.person)
    print("\n" + "\n".join(lines))
    print("PASS" if ok else "FAIL")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
