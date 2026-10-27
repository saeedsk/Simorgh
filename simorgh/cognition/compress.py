"""Compression of long tool results with LLMLingua-2 (stage 17 item 4;
docs/plan/stage-17-tool-routing-and-prompt-compression.md, "Compression").

An experiment, off by default (`[cognition] compress_tool_results =
false`). When on, the text of a tool result longer than
`compress_min_chars` -- a `web_fetch` page, a file read -- is shortened
by LLMLingua-2 (`llmlingua`, Microsoft, MIT; an XLM-RoBERTa token
classifier that drops low-information tokens) to about `compress_rate`
of its tokens before the main model sees it.

What it never touches:

- any message that is not a tool result (`tokens.is_result`: a `tool`
  message, or a user turn that starts "Result of"/"Results of"), so the
  constitution, persona, memory blocks, the question, tool schemas and
  the model's own calls (tool names, arguments) are never sent to it;
- a `protected` or `load_bearing` result;
- inside a result: the "Result of <tool>:" header lines, fenced code
  (``` or ~~~, an unclosed fence to the end), indented code, a body that
  is a JSON document, and any paragraph with Arabic-script letters
  (Farsi: LLMLingua's classifier was not trained on it, and Sim reads
  Farsi back aloud). Digits are kept (`force_reserve_digit`).

It never blocks or fails a turn: the work runs in its own worker thread
and is waited for at most `timeout_s`; on a timeout, an error, or a
result no shorter than the original, the original text is sent. The
first call loads the model (seconds), so it times out and warms the
thread for the next one.

`llmlingua` is an optional dependency, imported under `try/except
ImportError` in the worker. Absent, `unavailable()` names it and the
Service reports the `compress` switch unavailable (config problems and
health) and changes nothing.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
import importlib.util
import json
import re
import sys
import threading
import time
from dataclasses import dataclass

from .tokens import is_result

#: The LLMLingua-2 checkpoint (multilingual, XLM-RoBERTa large, MeetingBank).
MODEL = "microsoft/llmlingua-2-xlm-roberta-large-meetingbank"

#: How long one think waits for compression before sending the original.
TIMEOUT_S = 1.5

#: A prose run shorter than this is left as it is: not worth a model call.
MIN_RUN_CHARS = 200

_FENCE = re.compile(r"(?ms)^[ \t]*(```|~~~)[^\n]*\n.*?(?:^[ \t]*\1[ \t]*$|\Z)")
# A blank-line paragraph break, or a "Result(s) of <tool>:" header line.
_BREAK = re.compile(r"(\n[ \t]*\n|^Results? of [^\n]*(?:\n|$))", re.M)
_ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")


@dataclass(frozen=True)
class Stats:
    """What one think's compression did, for the `cognition.provider_call`
    span (`compress` attr) so item 5 can measure it."""

    outcome: str = "skipped"   # compressed | unchanged | timeout | error | skipped
    results: int = 0           # tool results long enough to be tried
    chars_in: int = 0          # chars of prose handed to the compressor
    chars_out: int = 0         # what came back for them (== chars_in unless compressed)
    ms: float = 0.0            # wall-clock this think waited for it

    def as_attr(self) -> dict:
        return {"outcome": self.outcome, "results": self.results, "chars_in": self.chars_in,
                "chars_out": self.chars_out, "ms": round(self.ms, 1)}


def has_farsi(text: str) -> bool:
    return bool(_ARABIC_SCRIPT.search(text))


def _is_code(paragraph: str) -> bool:
    lines = [ln for ln in paragraph.split("\n") if ln.strip()]
    return bool(lines) and all(ln.startswith(("    ", "\t")) for ln in lines)


def _is_json(text: str) -> bool:
    body = text.strip()
    if not body or body[0] not in "{[":
        return False
    try:
        json.loads(body)
    except ValueError:
        return False
    return True


def segments(text: str) -> list[tuple[str, bool]]:
    """`text` cut into pieces, each `(piece, compressible)`, whose
    concatenation is `text` exactly. Adjacent compressible paragraphs
    (with the blank lines between them) are one run, so the model is
    called once per run, not once per paragraph."""
    pieces: list[tuple[str, bool]] = []
    pos = 0
    for fence in _FENCE.finditer(text):
        pieces += _prose(text[pos:fence.start()])
        pieces.append((fence.group(0), False))
        pos = fence.end()
    pieces += _prose(text[pos:])
    merged: list[tuple[str, bool]] = []
    for piece, ok in pieces:
        if not piece:
            continue
        if merged and ok and merged[-1][1]:
            merged[-1] = (merged[-1][0] + piece, True)
        elif (merged and merged[-1][1] and not ok and not piece.strip()):
            # A blank separator inside a run joins it, pending the next piece.
            merged[-1] = (merged[-1][0] + piece, True)
        else:
            merged.append((piece, ok))
    # A run may have swallowed trailing blank separators; hand them back.
    out: list[tuple[str, bool]] = []
    for piece, ok in merged:
        if ok:
            body = piece.rstrip()
            tail = piece[len(body):]
            if len(body.strip()) < MIN_RUN_CHARS:
                out.append((piece, False))
                continue
            out.append((body, True))
            if tail:
                out.append((tail, False))
        else:
            out.append((piece, False))
    return out


def _prose(chunk: str) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []
    for i, part in enumerate(_BREAK.split(chunk)):
        if i % 2:          # a separator or a header line: verbatim
            out.append((part, False))
        elif part:
            ok = bool(part.strip()) and not has_farsi(part) and not _is_code(part) and not _is_json(part)
            out.append((part, ok))
    return out


class Compressor:
    """LLMLingua-2 over long tool results, bounded in time.

    `factory` builds the compressor object (anything with
    `compress_prompt(text, rate=..., ...) -> {"compressed_prompt": str}`);
    by default it is `llmlingua.PromptCompressor(MODEL, use_llmlingua2=True)`,
    built lazily in the worker thread on first use."""

    def __init__(self, *, rate: float = 0.5, min_chars: int = 4_000, timeout_s: float | None = None,
                 factory=None) -> None:
        self.rate = float(rate)
        self.min_chars = int(min_chars)
        self.timeout_s = float(TIMEOUT_S if timeout_s is None else timeout_s)
        self._factory = factory
        self._model = None
        self._load_lock = threading.Lock()
        # One worker of its own: a hung model can only queue its own later
        # calls (each then times out), never starve the default executor.
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="compress")

    def unavailable(self) -> str:
        """Why the switch cannot work here, or "" when it can."""
        if self._factory is not None:
            return ""
        if sys.modules.get("llmlingua") is not None:
            return ""
        try:
            found = importlib.util.find_spec("llmlingua") is not None
        except (ImportError, ValueError):
            found = False
        return "" if found else "compress: unavailable -- the llmlingua package is not installed"

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -- the worker side ------------------------------------------------------
    def _load(self):
        with self._load_lock:
            if self._model is None:
                if self._factory is not None:
                    self._model = self._factory()
                else:
                    try:
                        llmlingua = importlib.import_module("llmlingua")
                    except ImportError as exc:  # absent: the caller sends the original
                        raise RuntimeError("llmlingua is not installed") from exc
                    self._model = llmlingua.PromptCompressor(
                        model_name=MODEL, use_llmlingua2=True, device_map="cpu")
            return self._model

    def _compress_text(self, model, text: str) -> tuple[str, int, int]:
        out: list[str] = []
        chars_in = chars_out = 0
        for piece, ok in segments(text):
            if not ok:
                out.append(piece)
                continue
            result = model.compress_prompt(piece, rate=self.rate, force_tokens=["\n"],
                                           force_reserve_digit=True, drop_consecutive=True)
            short = str((result or {}).get("compressed_prompt") or "") if isinstance(result, dict) else ""
            if not short.strip() or len(short) >= len(piece):
                short = piece
            chars_in += len(piece)
            chars_out += len(short)
            out.append(short)
        return "".join(out), chars_in, chars_out

    def _run(self, messages: list[dict], targets: list[int]) -> tuple[dict[int, str], int, int]:
        model = self._load()
        new: dict[int, str] = {}
        chars_in = chars_out = 0
        for i in targets:
            text, cin, cout = self._compress_text(model, messages[i]["content"])
            chars_in += cin
            chars_out += cout
            if cout < cin:
                new[i] = text
        return new, chars_in, chars_out

    # -- the think side ---------------------------------------------------------
    def targets(self, messages: list[dict]) -> list[int]:
        """The indexes of the tool results this think may compress."""
        return [i for i, m in enumerate(messages)
                if is_result(m) and isinstance(m.get("content"), str)
                and len(m["content"]) > self.min_chars
                and not m.get("protected") and not m.get("load_bearing")]

    async def compress_messages(self, messages: list[dict]) -> tuple[list[dict], Stats]:
        """`messages` with long tool results compressed, and what was done.
        Never raises; on any failure returns `messages` itself."""
        targets = self.targets(messages)
        if not targets:
            return messages, Stats()
        started = time.perf_counter()
        future = self._executor.submit(self._run, list(messages), targets)
        try:
            new, chars_in, chars_out = await asyncio.wait_for(asyncio.wrap_future(future), self.timeout_s)
        except asyncio.TimeoutError:
            future.cancel()
            return messages, Stats("timeout", len(targets), ms=(time.perf_counter() - started) * 1000)
        except Exception:  # noqa: BLE001 -- compression may never fail a turn
            return messages, Stats("error", len(targets), ms=(time.perf_counter() - started) * 1000)
        ms = (time.perf_counter() - started) * 1000
        if not new:
            return messages, Stats("unchanged", len(targets), chars_in, chars_in, ms)
        out = [({**m, "content": new[i]} if i in new else m) for i, m in enumerate(messages)]
        return out, Stats("compressed", len(targets), chars_in, chars_out, ms)


__all__ = ["Compressor", "MODEL", "MIN_RUN_CHARS", "Stats", "TIMEOUT_S", "has_farsi", "segments"]
