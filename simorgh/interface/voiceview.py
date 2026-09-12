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
        return f"voice: {payload.get('detail') or 'could not do that'}"
    detail = payload.get("detail") or ""
    if detail.startswith(("barge-in", "echo cancellation", "settings you can change")) or " = " in detail:
        return f"voice: {detail}"
    return status(payload)


def bench(payload: dict) -> str:
    if not payload.get("ok"):
        return f"voice: {payload.get('detail') or 'could not run the benchmark'}"
    from simorgh.voice.bench import render

    return render(payload.get("result") or {})


def spoken(payload: dict) -> str:
    if not payload.get("ok"):
        return f"voice: {payload.get('detail') or 'could not speak'}"
    return f"spoken ({payload.get('engine') or 'tts'})"


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
    return f"{payload.get('engine')}: {shown}{more}\n  `[voice] tts_voice = \"<name>\"` to change it"


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
