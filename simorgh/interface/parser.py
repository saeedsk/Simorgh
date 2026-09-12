"""Command grammar -- a port of v1's `strip_command_slash` /
`autocorrect_command` (`src/main.py`). A leading `/` is optional; a
near-miss first word is corrected *and announced*, never silently
(spec section 3.3's closing note).
"""

from __future__ import annotations

import re

import difflib
from dataclasses import dataclass

#: Every command, once. `(name, argument hint, what it does)`.
#:
#: One table, because there were three: this module's name list, the
#: TUI's completion table, and the help panel's rows. Adding a command
#: meant remembering all three, and on 2026-09-09 four new commands were
#: added to two of them -- so `tool`, `domains`, `config` and `alerts`
#: worked when typed and did not autocomplete, which reads like the
#: command does not exist.
COMMANDS: tuple[tuple[str, str, str], ...] = (
    ("status", "", "health, vitals, posture and git in one panel"),
    ("domains", "[name]", "documents, mail, the house, energy, media, security: on? working?"),
    ("tool", "[name] [args]", "list every tool, or run one -- Guardian gates it as usual"),
    ("alerts", "[all]", "what the monitors have raised, and what is waiting for the digest"),
    ("config", "[section]", "the settings actually in force, and any nothing reads"),
    ("capabilities", "", "what Sim can actually reach: Node, Docker, optional packages"),
    ("tasks", "[all|work|clear]", "see the backlog (all of it), advance the next item, or wipe it"),
    ("cancel", "<task_id>", "stop a running task"),
    ("improve", "[path] <description>", "change something, tested before it lands"),
    ("skill", "<topic>", "draft a new reusable skill, audited before it lands"),
    ("plan", "<goal>", "break a goal into tracked steps"),
    ("research", "<topic>", "investigate a question, no code written"),
    ("interests", "[topic]", "topics Sim is following, or add one"),
    ("benchmark", "[suites|load|run|stop|history|show]", "score this system on GAIA, BFCL or SWE-bench, and track it"),
    ("voice", "[status|on|off|mute|unmute|barge on|off|listen [s]|test <text>|voices|devices|models [name]|set <key> <value>|bench]", "talk to Sim: speech in, speech out, local engines"),
    ("cameras", "[list|state [camera]|show <cameras> [grid|full|frame|stop]|snapshot <camera>|light <camera> on|off|ir <camera> on|off|siren <camera> [s]|ptz <camera> <move>|recordings <camera> [period]|watch on|off|setup <host> <user> <password>]", "the Reolink cameras: live on the TV, pictures, lights, sirens, moves, recordings, events"),
    ("ring", "[list|snapshot <camera|all>|events [camera] [n]|light <camera> on|off|siren <camera> [s]|watch on|off|setup <email> <password> [code]]", "the Ring cameras through Ring's cloud: stills for the dashboard, rings and motions, lights, sirens"),
    ("tv", "[setup|devices|use <device>|show [tv|dash] [device]|view <name>|rotate <s>|scale <f>|live <n>|quality <q>|remote|link|video <url> [full|frame]|stop [frame]|volume <0-100>]", "Sim on the TV over Chromecast: its terminal or its glass dashboard on screen, a video framed in it or full screen"),
    ("schedule", "[every] <15m> <label> | cancel <id>", "fire a reminder later, or on a repeat"),
    ("mcp", "[list|approve|deny]", "review external tools Sim has proposed"),
    ("auto", "[on|off|now]", "control the idle self-improvement loop"),
    ("pause", "", "hold everything"),
    ("resume", "", "let it continue"),
    ("help", "", "list everything"),
    ("exit", "", "leave (Ctrl-D also detaches)"),
)

COMMAND_NAMES: tuple[str, ...] = tuple(name for name, _, _ in COMMANDS)

#: Commands that take nothing, derived from the table's own argument
#: hints rather than listed again -- a second list is a list that
#: drifts, and three of these hints were wrong until 2026-09-10.
#:
#: Words after one of these is a sentence, not a command with an
#: argument, and that difference had teeth: `exit strategy for the
#: company is unclear` shut the system down, and `pause for a moment and
#: think about it` paused every subsystem (observer, 2026-09-10). Both
#: read `args` as a free-text "reason", so nothing downstream could tell
#: a remark from an instruction.
NO_ARGUMENT_COMMANDS: frozenset[str] = frozenset(
    name for name, hint, _ in COMMANDS if not hint
)


#: How many rows the startup splash shows. The table is ordered most
#: useful first, so the splash is its head: twenty rows on the first
#: screen someone sees is a wall, and `help` is one word away.
SPLASH_COMMANDS = 8


#: The help screen's sections, in the order they read best, and what
#: each command's words mean. The creator, 2026-09-12: "make the help
#: screen more visually appealing and more informative, I'd like to see
#: subcommand options". A command not listed in a section goes under
#: "More"; a subcommand not listed here still completes (from the usage
#: hint) but has no line of its own.
SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Look around", ("status", "domains", "capabilities", "config", "alerts", "tool")),
    ("Work", ("tasks", "cancel", "improve", "skill", "plan", "research", "interests", "benchmark")),
    ("Voice, screen and cameras", ("voice", "tv", "cameras", "ring")),
    ("Control", ("auto", "schedule", "mcp", "pause", "resume")),
    ("Session", ("help", "exit")),
)
SUBCOMMANDS: dict[str, tuple[tuple[str, str], ...]] = {
    "tasks": (("", "the backlog: the twenty most recent, with status and origin"),
              ("all", "every task, not just the recent ones"),
              ("work", "advance the next item now"),
              ("clear", "wipe the backlog -- queued, running, done; the ledger keeps the history")),
    "alerts": (("", "what the monitors have raised"), ("all", "including what already went into a digest")),
    "domains": (("", "every domain: on? working?"), ("<name>", "one domain in detail")),
    "tool": (("", "list every tool"), ("<name> [args]", "run one -- Guardian gates it as usual")),
    "config": (("", "the settings in force"), ("<section>", "one section, and any setting nothing reads")),
    "benchmark": (("suites", "the suites available and their sizes"), ("load <suite>", "fetch a suite's cases"),
                  ("run <suite> [n]", "score the system on it"), ("stop", "stop a run"),
                  ("history", "past runs, by model"), ("show <run>", "one run in detail")),
    "voice": (("status", "engines, state, the last turn's timings"), ("on", "listen and speak"),
              ("off", "silent and deaf until `voice on`"), ("mute", "stop listening; keep the rest"),
              ("unmute", "listen again"), ("barge on|off", "whether talking over Sim stops it"),
              ("listen [s]", "one push-to-talk turn"), ("test <text>", "say something aloud"),
              ("voices", "the voices the engine has"), ("devices", "microphone, speaker, engines"),
              ("models [name]", "recogniser models on disk, or fetch one"),
              ("set <key> <value>", "change a setting live: tts_voice, tts_speed, volume, backchannel, ..."),
              ("bench", "measure the engines on this machine")),
    "cameras": (("list", "every camera: number, name, model, online"),
                ("state [camera]", "what a camera sees right now, and what it has on"),
                ("show <camera>", "one camera live, framed beside Sim's page"),
                ("show <a>, <b>, ... | all", "several cameras tiled across the TV"),
                ("show <camera> full", "one camera full screen on the TV"),
                ("show all dash", "every camera live in the dashboard's camera strip; the TV's page is left alone"),
                ("show stop", "end the live streams"),
                ("snapshot <camera>", "a still, saved under workspace/cameras/"),
                ("light <camera> on|off", "the spotlight"),
                ("ir <camera> on|off", "the infrared night lights (off = the camera decides)"),
                ("siren <camera> [seconds]", "sound the siren -- loud"),
                ("ptz <camera> <move>", "left, right, up, down, stop, zoom_in, zoom_out, preset <n>"),
                ("recordings <camera> [today|yesterday|<n>h]", "what the NVR recorded"),
                ("watch on|off", "events pushed from the NVR onto the screen as they happen"),
                ("setup <host> <user> <password>", "the NVR's address and login, kept in secrets.toml")),
    "ring": (("list", "every Ring camera: kind, battery, light/siren"),
             ("snapshot <camera|all>", "a fresh still, saved under workspace/cameras/ring/ -- the dashboard shows it"),
             ("events [camera] [n]", "recent rings and motions, newest first"),
             ("light <camera> on|off", "the camera's light"),
             ("siren <camera> [seconds]", "sound the siren -- loud"),
             ("watch on|off [seconds]", "poll Ring: new events on screen, fresh stills for the dashboard"),
             ("setup <email> <password> [code]", "log in once; Ring texts a code, run it again with the code")),
    "tv": (("setup [device]", "one-time: open Sim's API to the network with a token, remember the TV; then restart"),
           ("devices", "the Cast devices on this network; * marks the default"),
           ("use <device>", "remember one as the TV, by name; saved to simorgh.toml"),
           ("show [device]", "put the glass dashboard on the TV: home, discover, cameras, news, markets, media, ambient"),
           ("show tv", "the bare terminal replica instead of the dashboard"),
           ("view <name> [1D|1W|1M|1Y] [symbol]", "turn the dashboard to a view (the TV's remote cannot); a timeframe or symbol picks the chart"),
           ("rotate <seconds|off>", "cycle the dashboard's views on a timer"),
           ("scale <factor|auto>", "fix the dashboard's zoom on a TV that shows only part of it (try 0.5); auto fits"),
           ("live <n>", "how many camera feeds the dashboard plays at once (fewer if the TV stutters)"),
           ("quality light|full", "the embedded video's resolution; light is easier on the TV's browser"),
           ("remote", "the phone remote's link -- open it on a phone on this Wi-Fi"),
           ("link", "the dashboard's link for a browser, token included (without it the Sim box shows only the banner)"),
           ("video <url>", "play a video framed inside Sim's page (a direct link or a YouTube page)"),
           ("video <url> full", "play it full screen on the TV itself"),
           ("stop", "stop the TV's playback and close its app"),
           ("stop frame", "clear the framed video; Sim's page stays"),
           ("volume <0-100>", "the TV's volume, within the media limits")),
    "schedule": (("<15m> <label>", "a reminder later"), ("every <15m> <label>", "a reminder on a repeat"),
                 ("cancel <id>", "drop one")),
    "mcp": (("list", "external tools Sim has proposed"), ("approve <id>", "let one in"), ("deny <id>", "keep one out")),
    "auto": (("", "is the idle loop on?"), ("on", "let Sim improve itself when idle"), ("off", "stop that"),
             ("now", "one round now")),
    "interests": (("", "topics Sim is following"), ("<topic>", "follow one more")),
    "improve": (("[path] <description>", "change something; tested before it lands; `steps=N` bounds one attempt"),),
}


def subcommands(name: str) -> tuple[str, ...]:
    """The words a command takes next, read off its own usage hint --
    `[all|work|clear]` gives all, work, clear; `<topic>` gives nothing,
    a free argument is not a word to offer. What Tab shows after a
    command (the creator, 2026-09-12: "if I type tasks and press tab
    at least I expect to see all")."""
    listed = SUBCOMMANDS.get(name.lstrip("/"))
    if listed:
        words = tuple(dict.fromkeys(sub.split(" ", 1)[0] for sub, _m in listed
                                    if sub and not sub.startswith(("<", "["))))
        if words:
            return words
    for command, hint, _desc in COMMANDS:
        if command != name.lstrip("/"):
            continue
        # `[name]` alone is a placeholder for a free argument; `[all]`
        # alone is the one literal word; `a|b|c` are literal words.
        if "|" not in hint and hint.strip() != "[all]":
            return ()
        words: list[str] = []
        for alternative in re.split(r"\s*\|\s*", hint.strip().strip("[]")):
            first = alternative.strip().split(" ", 1)[0].strip("[]")
            if first and not first.startswith("<") and first.isalpha() and first not in words:
                words.append(first)
        return tuple(words)
    return ()


def command_help(limit: int | None = None) -> tuple[tuple[str, str], ...]:
    """`(usage, description)` for the help panel and the completion
    menu, derived rather than kept in step by hand."""
    rows = tuple((f"{name} {args}".strip(), description) for name, args, description in COMMANDS)
    return rows[:limit] if limit else rows

_AUTOCORRECT_CUTOFF = 0.75


@dataclass(frozen=True)
class Command:
    name: str | None  # None means "plain chat text", not a recognized command
    args: str
    raw: str
    guessed_from: str | None = None


def parse(line: str) -> Command | None:
    raw = line
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("!"):
        return Command(name="!", args=stripped[1:].strip(), raw=raw)

    explicit = stripped.startswith("/")
    body = stripped[1:] if explicit else stripped
    first, _, rest = body.partition(" ")
    # A trailing full stop or comma is typing, not syntax: `status.` is
    # still `status`. But only when the punctuation is all that stood in
    # the way -- `benchmark, how did it go?` is a question about the
    # benchmark, not a request to run one.
    lowered = first.lower()
    if lowered in COMMAND_NAMES and (explicit or not _swallows_a_sentence(lowered, rest)):
        return Command(name=lowered, args=rest.strip(), raw=raw)
    trimmed = lowered.rstrip(_SENTENCE_PUNCTUATION)
    if (trimmed in COMMAND_NAMES and (explicit or not _looks_like_prose(first, rest))
            and (explicit or not _swallows_a_sentence(trimmed, rest))):
        return Command(name=trimmed, args=rest.strip(), raw=raw)
    lowered = trimmed

    if (len(lowered) >= 4 and (explicit or not _looks_like_prose(first, rest))
            and (explicit or not _swallows_a_sentence(lowered, rest))):
        match = difflib.get_close_matches(lowered, COMMAND_NAMES, n=1, cutoff=_AUTOCORRECT_CUTOFF)
        if match:
            return Command(name=match[0], args=rest.strip(), raw=raw, guessed_from=first)

    return Command(name=None, args=stripped, raw=raw)


#: Punctuation a command never ends in, and a sentence often does.
_SENTENCE_PUNCTUATION = ",.;:!?"


def _swallows_a_sentence(name: str, rest: str) -> bool:
    """Whether treating `name` as a command would eat a sentence.

    A command that takes no arguments, followed by words, is somebody
    talking. `exit strategy for the company is unclear` stopped the
    system and `pause for a moment and think about it` paused every
    subsystem, because both commands accept `args` as a free-text
    reason and neither could tell a remark from an instruction
    (observer, 2026-09-10).

    Typing the slash overrides this, as it does everywhere else here:
    `/exit the meeting overran` is a person saying "this is a command",
    reason and all."""
    return bool(rest.strip()) and name in NO_ARGUMENT_COMMANDS


def _looks_like_prose(first: str, rest: str) -> bool:
    """Whether a near-miss first word is a typo or just a sentence.

    Live-caught 2026-09-09. The creator typed

        improvment, now the game works for one second, then it freezes

    meaning it as a remark. `improvment,` is close enough to `improve`
    to clear the cutoff, so it became `improve <topic>` -- which, with
    no path in it, creates a *skill* task. A bug report about a game
    became "write a skill", and three rounds of verification then asked
    whether a skill had been produced.

    An exact command is still a command however it is punctuated. This
    only holds back the GUESS, and only without a leading `/`: typing
    the slash is a person saying "this is a command", and their typo
    should still be corrected.
    """
    if not rest.strip():
        # A word on its own is not a sentence, whatever it ends in.
        # `status.` is somebody typing `status` and a full stop.
        return False
    if first.rstrip(_SENTENCE_PUNCTUATION) != first:
        # `improve` never ends in a comma. A sentence often does.
        return True
    # A guessed command carrying a comma'd clause after it is a sentence
    # far more often than an argument: real arguments are paths, ids and
    # topics, not prose with punctuation in the middle.
    return "," in rest
