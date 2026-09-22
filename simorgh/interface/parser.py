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
    ("forget", "[minutes] [words]", "forget what Sim remembered in the last minutes (default 2), optionally only records with those words"),
    ("improve", "[path] <description>", "change something, tested before it lands"),
    ("skill", "<topic>", "draft a new reusable skill, audited before it lands"),
    ("plan", "<goal>", "break a goal into tracked steps"),
    ("research", "<topic>", "investigate a question, no code written"),
    ("interests", "[topic]", "topics Sim is following, or add one"),
    ("benchmark", "[start|suites|load|run|stop|history|show]", "score this system on GAIA, BFCL or SWE-bench, and track it"),
    ("voice", "[status|on|off|mute|unmute|barge on|off|listen [s]|test <text>|enroll <name>|people|whois|forget <name>|forget all|pronounce <name> <as>|voices|devices|models [name]|set <key> <value>|bench]", "talk to Sim: speech in, speech out, local engines; it learns who is speaking"),
    ("people", "[<name>|grant <name> <permission>|revoke <name> <permission>|interest add|remove <name> <topic>|role <name> <role>|link <name> <identity>|unlink <identity>]", "who Sim knows, what they said yes to, and what they care about"),
    ("home", "[find <words>|state <thing>|on <thing>|off <thing>|dim <thing> <0-100>|toggle <thing>|scene <name>|call <service> <thing> [json]|undo <thing>]", "the house through Home Assistant: lights, switches, scenes, and anything else it exposes"),
    ("light", "[on <name>|<name> off|<name> <0-100>|list]", "the short way to a light: `light on kitchen`, `light kitchen 40`"),
    ("cameras", "[list|state [camera]|show <cameras> [grid|full|frame|stop]|snapshot <camera>|light <camera> on|off|ir <camera> on|off|siren <camera> [s]|ptz <camera> <move>|recordings <camera> [period]|watch on|off|setup <host> <user>]", "the Reolink cameras: live on the TV, pictures, lights, sirens, moves, recordings, events"),
    ("ring", "[list|snapshot <camera|all>|events [camera] [n]|light <camera> on|off|siren <camera> [s]|watch on|off|setup <email> [code]]", "the Ring cameras through Ring's cloud: stills for the dashboard, rings and motions, lights, sirens"),
    ("tv", "[setup|devices|use <device>|show [tv|dash] [device]|view <name>|rotate <s>|scale <f>|live <n>|quality <q>|sound on|off|remote|link|pair [code]|app <name>|key <key>|nav <key>|charts [kpop|us]|video <url> [full|frame]|stop [frame]|volume <0-100>]", "Sim on the TV over Chromecast: its terminal or its glass dashboard on screen, a video framed in it or full screen"),
    ("schedule", "[every] <15m> <label> | cancel <id>", "fire a reminder later, or on a repeat"),
    ("mcp", "[list|approve|deny]", "review external tools Sim has proposed"),
    ("skills", "[list|show <name>|review <folder>|install <git-url>|approve <name>|remove <name>]",
     "Agent Skills: folders of instructions Sim can load; a trusted org installs clean, anything else waits"),
    ("auto", "[on|off|now]", "control the idle self-improvement loop"),
    ("pause", "", "hold everything"),
    ("resume", "", "let it continue"),
    ("pronounce", "<name> [as] <how>", "how Sim says a name aloud: `pronounce Ira as Eye-raa` (also `voice pronounce`)"),
    ("next", "", "skip the track playing on the TV (also: skip; `tv pause` / `tv play` for the rest)"),
    ("help", "[command]", "list everything, or one command's words: help voice"),
    ("exit", "", "leave (Ctrl-D also detaches)"),
    ("restart", "", "come back up on the current source -- re-gated the same way `./sim.sh` gates a fresh boot"),
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
    ("Work", ("tasks", "cancel", "forget", "improve", "skill", "plan", "research", "interests", "benchmark")),
    ("The house and the people in it", ("home", "light", "people")),
    ("Voice, screen and cameras", ("voice", "pronounce", "tv", "next", "cameras", "ring")),
    ("Control", ("auto", "schedule", "mcp", "skills", "pause", "resume")),
    ("Session", ("help", "exit", "restart")),
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
    "benchmark": (("start [suite] [n]", "the quick way: GAIA level 1, 5 cases, unless you name others"),
                  ("suites", "the suites available and their sizes"), ("load <suite>", "fetch a suite's cases"),
                  ("run <suite> [n]", "score the system on it"), ("stop", "stop a run"),
                  ("history", "past runs, by model"),
                  ("clear <model|all>", "forget the recorded runs for one model, or for all of them"),
                  ("show <run>", "one run, one line per case"),
                  ("cases <run>", "one run in full: question, answer, true answer, time, tokens")),
    "voice": (("status", "engines, state, the last turn's timings"), ("on", "listen and speak"),
              ("off", "silent and deaf until `voice on`"), ("mute", "stop listening; keep the rest"),
              ("unmute", "listen again"), ("barge on|off", "whether talking over Sim stops it"),
              ("listen [s]", "one push-to-talk turn"), ("test <text>", "say something aloud"),
              ("enroll <name> [as <relation>]", "learn a person's voice from three sentences; Sim then knows who is speaking"),
              ("people", "who Sim knows by voice (also `voice family`)"), ("whois", "say something; Sim tells who it sounded like, with scores"),
              ("forget <name>", "drop a person's voice"),
              ("tidy <name>", "drop the learnt takes pulling a voice profile apart"),
              ("relearn <name>", "rebuild a voice profile from recordings already kept -- nobody re-records"),
              ("calibrate [name] [aloud] [short] [en|fa]",
               "read a script once (English + Farsi), kept forever, so Sim can be re-tuned later without asking "
               "again; resumes where it stopped -- `voice calibrate status|stop|skip|keep`; `voice calibrate apply` rebuilds the voice profile from the set"),
              ("pronounce <name> <as>", "how Sim says a name aloud (voice pronounce Saoirse Seer-sha); the screen keeps the spelling"),
              ("models chatterbox|miso", "install an expressive engine in its own environment; then `voice set tts chatterbox`"),
              ("voices", "the voices the engine has"), ("devices", "microphone, speaker, engines"),
              ("models [name]", "recogniser models on disk, or fetch one"),
              ("set <key> <value>", "change a setting live: tts_voice, tts_speed, volume, backchannel, ..."),
              ("bench", "measure the engines on this machine")),
    "people": (("", "everybody Sim knows: role, what they said yes to, what they care about"),
               ("<name>", "one person in detail, and what each permission actually lets Sim do"),
               ("grant <name> <permission>", "record that somebody said yes -- asks them, because consent is theirs to give"),
               ("revoke <name> <permission>", "withdraw it, and drop what was kept under it"),
               ("interest add|remove <name> <topic>", "what they care about, for interest shares"),
               ("role <name> <owner|adult|child|guest>", "what their role may ask for"),
               ("link <name> <identity>", "tie a handle or a voice to a person: telegram:x, voice:y"),
               ("unlink <identity>", "that handle is nobody's again"),
               ("wrong <ref> [why]", "that unprompted message was wrong or unwanted")),
    "home": (("", "what is on in the house right now"),
             ("find <words>", 'what matches: "kitchen", "anything with a battery"'),
             ("state <thing>", "one thing, as it is now"),
             ("on <thing>", "turn it on -- a lamp goes straight through, a lock asks you"),
             ("off <thing>", "turn it off"),
             ("dim <thing> <0-100>", "set a light's brightness"),
             ("toggle <thing>", "the other way from whatever it is"),
             ("scene <name>", "run a scene"),
             ("call <service> <thing> [json]", "any service at all, for what the words above do not cover"),
             ("undo <thing>", "put back what the last call changed")),
    "light": (("on <name>", "`light on kitchen` -- the short way, three words"),
              ("<name> off", "`light kitchen off` reads the same either way round"),
              ("<name> <0-100>", "`light kitchen 40` sets brightness"),
              ("list", "every light and what it is doing")),
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
                ("setup <host> <user>", "the NVR's address and login; the password is asked for hidden, never on the line")),
    "ring": (("list", "every Ring camera: kind, battery, light/siren"),
             ("snapshot <camera|all>", "a fresh still, saved under workspace/cameras/ring/ -- the dashboard shows it"),
             ("events [camera] [n]", "recent rings and motions, newest first"),
             ("light <camera> on|off", "the camera's light"),
             ("siren <camera> [seconds]", "sound the siren -- loud"),
             ("watch on|off [seconds]", "poll Ring: new events on screen, fresh stills for the dashboard"),
             ("setup <email> [code]", "log in once (the password is asked for hidden); Ring texts a code, run it again with the code")),
    "tv": (("setup [device]", "one-time: open Sim's API to the network with a token, remember the TV; then restart"),
           ("devices", "the Cast devices on this network; * marks the default"),
           ("use <device>", "remember one as the TV, by name; saved to simorgh.toml"),
           ("show [device]", "put the glass dashboard on the TV: home (news, discover and media all rotate through it), "
                              "cameras, markets, charts, ambient"),
           ("show tv", "the bare terminal replica instead of the dashboard"),
           ("view <name> [1D|1W|1M|1Y] [symbol]", "turn the dashboard to a view (the TV's remote cannot); a timeframe or symbol picks the chart"),
           ("rotate <seconds|off>", "cycle the dashboard's views on a timer"),
           ("scale <factor|auto>", "fix the dashboard's zoom on a TV that shows only part of it (try 0.5); auto fits"),
           ("live <n> [seconds]", "how many camera feeds play at once (3), and how often the live window slides one camera on (1 s); "
                                  "tiles keep their size either way"),
           ("quality light|full", "the embedded video's resolution; light is easier on the TV's browser"),
           ("sound on|off", "the embedded videos' sound on the dashboard, on by default; in a browser the first tap turns it up"),
           ("remote", "the phone remote's link -- open it on a phone on this Wi-Fi"),
           ("link", "the dashboard's link for a browser, token included (without it the Sim box shows only the banner)"),
           ("video <url>", "play a video framed inside Sim's page (a direct link or a YouTube page)"),
           ("video <url> full", "play it full screen on the TV itself"),
           ("stop", "stop the TV's playback and close its app (also: tv off)"),
           ("stop frame", "clear the framed video; Sim's page stays"),
           ("volume <0-100>", "the TV's volume, within the media limits"),
           ("pair [code]", "once: pair with the TV's own remote protocol -- the TV shows a code, `tv pair <code>` finishes; "
                           "then YouTube plays in the TV's own app at 4K"),
           ("app <name|url>", "open one of the TV's apps (youtube, netflix, disney, prime, spotify, plex) or a link in one"),
           ("key <key>", "press a key on the TV: home, back, ok, play, pause, next, mute, volume up, power"),
           ("nav <key> [times]", "a remote key on the dashboard page: left/right change tabs, ok opens a tab, a box "
                                 "or a video full screen, back steps out, playpause/next/prev; the phone remote's D-pad too"),
           ("next|pause|play|back|home|mute", "the same keys, shorter: `tv next` skips a track"),
           ("charts [kpop|us]", "play a music chart on the TV top to bottom -- K-pop (Korea's most played) or US pop; "
                                "the dashboard turns to its Charts view; `tv view charts` does the same")),
    "schedule": (("<15m> <label>", "a reminder later"), ("every <15m> <label>", "a reminder on a repeat"),
                 ("cancel <id>", "drop one")),
    "mcp": (("list", "external tools Sim has proposed"), ("approve <id>", "let one in"), ("deny <id>", "keep one out")),
    "skills": (("list", "the skills Sim has, bundled and installed"), ("show <name>", "one skill's card and where it lives"),
               ("review <folder>", "what a skill contains: licence, scripts, anything it does quietly"),
               ("install <git-url>", "clone at a commit, review it, enable it if the org is trusted"),
               ("approve <name>", "enable one that was waiting"), ("remove <name>", "delete an installed one")),
    "auto": (("", "is the idle loop on?"), ("on", "let Sim improve itself when idle"), ("off", "stop that"),
             ("now", "one round now")),
    "interests": (("", "topics Sim is following"), ("<topic>", "follow one more")),
    "improve": (("[path] <description>", "change something; tested before it lands; `steps=N` bounds one attempt"),),
}


def help_topics() -> tuple[str, ...]:
    """What `help <topic>` accepts: every command, and each section's
    first word (`help work`, `help control`)."""
    words = [name for name, _h, _d in COMMANDS if name != "help"]
    for title, _names in SECTIONS:
        first = title.split(",")[0].split()[0].lower()
        if first not in words:
            words.append(first)
    return tuple(words)


def subcommands(name: str) -> tuple[str, ...]:
    """The words a command takes next, read off its own usage hint --
    `[all|work|clear]` gives all, work, clear; `<topic>` gives nothing,
    a free argument is not a word to offer. What Tab shows after a
    command (the creator, 2026-09-12: "if I type tasks and press tab
    at least I expect to see all")."""
    if name.lstrip("/") == "help":
        return help_topics()
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
    if stripped in ("?", "/?"):
        # A lone question mark is asking for the commands, not asking the
        # model something: `?` went to chat and got "I'm here -- what would
        # you like?" (the creator, 2026-09-14).
        return Command(name="help", args="", raw=raw)
    head, _, topic = stripped.lstrip("/").partition(" ")
    topic = topic.strip().strip("'\"`").lower()
    if head == "?" and topic.split(" ", 1)[0] in COMMAND_NAMES:
        # `? interests` is `help interests`. It went to chat twice on the
        # creator's screen (2026-09-19), 30 s each, and the model explained
        # its own source code instead of listing the command's words.
        return Command(name="help", args=topic, raw=raw)

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
    if name == "help":
        # `help voice` asks for one command's words, and so does `help
        # voice set`; `help me plan the week` is a sentence (the creator,
        # 2026-09-13: "when I type 'help voice' it shows all the sub
        # commands related to voice").
        words = rest.split()
        if words and words[0].lower() in ("me", "us", "him", "her", "them", "with", "please"):
            return True
        return len(words) > 1 and words[0].lower().lstrip("/") not in COMMAND_NAMES
    if name == "pronounce":
        # `pronounce Ira as Eye-raa` or `pronounce Ira Eye-raa` is the
        # command (the creator typed exactly that twice, 2026-09-19, and
        # the model only answered "EYE-ra."); anything longer is a person
        # talking about pronunciation, which the model should hear.
        words = rest.split()
        is_command = len(words) == 2 or (3 <= len(words) <= 4 and words[1].lower() == "as")
        return not is_command
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
