"""How `voice ...` replies read on the terminal."""

from __future__ import annotations


def _engines(payload: dict) -> str:
    stt, tts = payload.get("stt") or "-", payload.get("tts") or "-"
    return f"stt {stt} · tts {tts}"


def status(payload: dict) -> str:
    if not payload.get("enabled"):
        line = "voice is off"
        problems = payload.get("problems") or []
        if problems:
            line += "\n  " + "\n  ".join(problems)
        else:
            line += " -- `voice on` to start listening, `voice test hello` to hear it"
        return line
    state = "muted" if payload.get("muted") else ("speaking" if payload.get("speaking") else
                                                  ("listening" if payload.get("listening") else "on, between turns"))
    if payload.get("state") and not payload.get("muted"):
        state = str(payload["state"]).replace("_", " ")
    lines = [f"voice {state} · {_engines(payload)} · {payload.get('turns', 0)} turn(s) this session"]
    for day, counts in sorted((payload.get("breaches") or {}).items(), reverse=True)[:2]:
        # Stage 3 item 8: turns that ran over their budget (stt 2 s, first audio 2.5 s).
        lines.append("  over budget " + day + ": " + ", ".join(f"{stage} {n}" for stage, n in sorted(counts.items())))
    if payload.get("partial"):
        lines.append(f"  hearing: {payload['partial']} ...")
    if payload.get("last_heard"):
        lines.append(f"  heard: {payload['last_heard']}")
    if payload.get("last_said"):
        lines.append(f"  said:  {payload['last_said']}")
    m = payload.get("metrics") or {}
    if m:
        parts = [f"{k} {m[k]:.2f}s" for k in ("stt", "llm", "first_audio", "response") if isinstance(m.get(k), (int, float))]
        if m.get("interrupted"):
            parts.append(f"interrupted in {m.get('interruption', 0):.2f}s")
        if m.get("underruns"):
            parts.append(f"{m['underruns']} underrun(s)")
        if parts:
            lines.append("  last turn: " + " · ".join(parts))
    if payload.get("interruptions"):
        last = payload.get("last_interruption_s")
        tail = f" (last stop {last * 1000:.0f} ms)" if isinstance(last, (int, float)) and last >= 0 else ""
        lines.append(f"  interruptions: {payload['interruptions']}{tail}")
    for problem in payload.get("problems") or []:
        lines.append(f"  ! {problem}")
    return "\n".join(lines)


def controlled(payload: dict) -> str:
    if not payload.get("ok"):
        error = payload.get("error") or {}
        return f"voice: {payload.get('detail') or error.get('detail') or 'could not do that'}"
    detail = payload.get("detail") or ""
    from . import render as render_mod

    colour = render_mod.color_enabled()
    # The settings block and a single setting are panels, coloured like
    # `help`; everything else is one line with a `voice:` in front.
    if detail.startswith("voice settings"):
        return settings_panel(detail, enabled=colour)
    if " = " in detail.partition("\n")[0] and "\n" in detail:
        return one_setting(detail, enabled=colour)
    # Anything a handler actually SAID is shown. This was a whitelist
    # of opening words -- "barge-in", "forgot", "enrolling" and five
    # more -- and a verb whose message did not begin with one of them
    # had it silently swallowed and the status panel printed instead.
    #
    # Live, 2026-09-21: the creator typed `voice tidy Saeed`, the tidy
    # ran, and what came back was "voice agent speaking · stt
    # whisper_server · 0 turn(s) this session". He could not tell
    # whether it had done anything. Every new verb would have paid the
    # same toll, which is why the default is now the other way round:
    # the state verbs return an EMPTY detail (service.py), and that is
    # the honest signal for "there is nothing to say but the state".
    if detail:
        return f"voice: {detail}"
    return status(payload)


def settings_panel(detail: str, *, enabled: bool = True) -> str:
    """`voice set`'s block, coloured the way `help` is coloured.

    The creator, 2026-09-16: "you did a good job in organzeing `voice
    set` but the font color shoulw be same orange like as output of
    `help`". `help_panel` paints the command name "warm" (the muted tan
    at RGB 172,127,79), its section titles "bold" and its preamble
    "dim"; this gives the settings the same three.

    The colour goes on HERE and not where the text is built, because
    Voice may not import Interface's renderer -- no subsystem imports
    another -- so the block arrives as plain text and is painted by its
    own layout: four spaces is a setting row and its first word is the
    key, two spaces is a group heading, anything else is the header.
    A line that matches nothing is left exactly as it came.
    """
    from . import render as render_mod

    out = []
    for line in detail.splitlines():
        if not line.strip():
            out.append(line)
        elif line.startswith("    "):
            key, sep, rest = line[4:].partition(" ")
            out.append("    " + render_mod.style(key, "warm", enabled=enabled) + sep + rest)
        elif line.startswith("  "):
            out.append("  " + render_mod.style(line[2:], "bold", enabled=enabled))
        else:
            out.append(render_mod.style(line, "dim", enabled=enabled))
    return "\n".join(out)


def one_setting(detail: str, *, enabled: bool = True) -> str:
    """`voice set tts` -- one setting, its key in the same warm as the
    settings block and as `help`."""
    from . import render as render_mod

    head, _, rest = detail.partition("\n")
    key, sep, value = head.partition(" = ")
    if not sep:
        return detail
    coloured = render_mod.style(key, "warm", enabled=enabled) + sep + value
    return coloured + ("\n" + rest if rest else "")


def bench(payload: dict) -> str:
    """The benchmark's numbers, rendered here: the interface reads the
    reply's payload and imports nothing from the voice package."""
    if not payload.get("ok"):
        return f"voice: {payload.get('detail') or 'could not run the benchmark'}"
    result = payload.get("result") or {}
    lines = [f"voice bench · tts {result.get('engine_tts') or '-'} · stt {result.get('engine_stt') or '-'}",
             f"  warm-up {result.get('warmup_s', 0):.2f}s · peak memory {result.get('peak_memory_mb', 0):.0f} MB"]
    for s in result.get("samples", []):
        rtf = f"{s['rtf']:.2f}x" if s.get("rtf") else "-"
        lines.append(f"  first audio {s['first_audio_s']:.2f}s · rtf {rtf} · {s['audio_s']:.1f}s of audio "
                     f"({s.get('engine', '')})  \"{s['text']}\"")
    if result.get("first_audio_s_median") is not None:
        rtf_median = result.get("rtf_median")
        lines.append(f"  median: first audio {result['first_audio_s_median']:.2f}s"
                     + (f" · rtf {rtf_median}x" if rtf_median is not None else ""))
    t = result.get("transcription")
    if t:
        if "error" in t:
            lines.append(f"  transcription: {t['error']}")
        else:
            lines.append(f"  transcription {t['latency_s']:.2f}s for {t['audio_s']:.1f}s of audio (rtf {t['rtf']}) "
                         f"[{t['engine']}]: \"{t['heard']}\"")
    i = result.get("interruption") or {}
    if i:
        stop = f", speaker stopped in {i['stop_s'] * 1000:.0f} ms" if "stop_s" in i else ""
        lines.append(f"  interruption: a person is noticed after {i['detect_ms']} ms of speech{stop}")
    return "\n".join(lines)


def spoken(payload: dict) -> str:
    if not payload.get("ok"):
        return f"voice: {payload.get('detail') or 'could not speak'}"
    engine = payload.get("engine") or "tts"
    # "+" means the pair, not one engine -- an older service that does
    # not send the engine it used. Say so rather than implying both spoke.
    return f"spoken ({engine})" if "+" not in engine else f"spoken (one of {engine})"


def listened(payload: dict) -> str:
    if not payload.get("ok"):
        return f"voice: {payload.get('detail') or 'could not listen'}"
    heard = payload.get("heard") or ""
    if not heard:
        return "heard nothing"
    conf = payload.get("confidence")
    line = f"heard: {heard}" + (f"  ({conf:.0%}, {payload.get('engine') or 'stt'})" if isinstance(conf, (int, float)) else "")
    if payload.get("said"):
        line += f"\nsaid:  {payload['said']}"
    return line


def voices(payload: dict) -> str:
    names = payload.get("voices") or []
    if not names:
        return f"no voices: {payload.get('detail') or 'no synthesiser'}"
    current = payload.get("current") or ""
    shown = ", ".join(f"*{n}" if n == current else n for n in names[:60])
    more = f" (+{len(names) - 60} more)" if len(names) > 60 else ""
    now = f" (now: {current})" if current else ""
    return f"{payload.get('engine')}: {shown}{more}\n  `voice set tts_voice <name>` to change it{now}"


def devices(payload: dict) -> str:
    lines = [
        f"microphone: {payload.get('microphone') or '-'}",
        f"speaker:    {payload.get('speaker') or '-'}",
        f"stt:        {payload.get('stt') or '-'}",
        f"tts:        {payload.get('tts') or '-'}",
        f"vad:        {payload.get('vad') or '-'}",
    ]
    for problem in payload.get("problems") or []:
        lines.append(f"  ! {problem}")
    return "\n".join(lines)


def models(payload: dict) -> str:
    if not payload.get("ok"):
        avail = ", ".join(payload.get("available") or [])
        return f"voice: {payload.get('detail') or 'could not fetch the model'}" + (f"\n  models: {avail}" if avail else "")
    mb = (payload.get("bytes") or 0) / 1e6
    return f"model ready: {payload.get('path')} ({mb:.0f} MB)\n  {payload.get('detail') or ''}".rstrip()
