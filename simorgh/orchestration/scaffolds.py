"""Per-profile prompt scaffolds -- the `task_rules` block of Cognition's
prompt assembly (docs/blueprint/subsystems/04-cognition.md section 5.4:
"caller-supplied rules for this purpose (scope, format,
`_CAPABILITY_REFERENCE`-style tool descriptions for the tools the caller
passed)").

`Profile.scaffold` (16 section 4) was carried all the way from
`profiles.py` into `context.py::Assembler.assemble(session, purpose)` and
then dropped on the floor: nothing ever rendered it, and Cognition's
`task_rules` slot -- protected, never compacted, already implemented in
`cognition/assembler.py` -- was never filled by anyone. So a task session
reached the model with the constitution, the persona voice, the self
summary, the task description and a bare list of tool *names*, and no
statement of what finishing the task means.

Live 2026-09-07: a sandboxed `improve` run wrote its file through
`apply_source_patch` and then stopped, leaving the edit uncommitted. It
had `git_commit` in its tool list and no reason to believe it was
supposed to use it. These texts say so.
"""

from __future__ import annotations

from .api import Profile
from .tools import offered_tools

# Filled at runtime from `capability.probed` (execution/capabilities.py),
# via `orchestration/service.py`. Module-level for the same reason
# `tools.py::register_tool_policy` is: the consumer is a pure render
# function several layers below the subscription, and threading a
# callable through Service -> Worker -> SessionRunner to deliver one
# optional line of prompt text is more machinery than the fact is
# worth. Empty in every test that does not set it, so nothing is
# said unless a probe actually failed.
_UNAVAILABLE: dict[str, tuple[str, tuple[str, ...]]] = {}


def note_capability(name: str, *, ok: bool, detail: str, tools: tuple[str, ...] | list[str]) -> None:
    if ok:
        _UNAVAILABLE.pop(name, None)
        return
    _UNAVAILABLE[name] = (detail, tuple(tools))


def unavailable_note(offered: tuple[str, ...] | list[str]) -> str:
    """What to tell the model about tools it is being offered that are
    known not to work right now. Empty when there is nothing to say --
    the common case, and it must cost nothing in the prompt."""
    lines = []
    for detail, tools in _UNAVAILABLE.values():
        affected = [t for t in tools if t in offered]
        if affected:
            lines.append(f"- {', '.join(affected)}: not working in this session ({detail})")
    if not lines:
        return ""
    return "Do not spend steps on these:\n" + "\n".join(lines)

_TOOL_NOTES: dict[str, str] = {
    "use_skill": "load one of the skills listed below by name; its instructions come back as the result, "
                 "and you follow them for the rest of the task",
    "sim_command": "run one of your own commands, exactly as a person would type it: restart, tasks, "
                   "tv show, voice off, status; `help` lists them. Not a shell -- `!` is refused",
    "self_map": "ask your own world model what real subsystems/files make you up -- the authoritative "
                "answer for questions about your own code or architecture; simorgh/ is what runs, src/ is retired v1",
    "read_file": "read a file from the repo, including a PDF (papers/ holds papers)",
    "list_dir": "list a directory",
    "search_code": "grep the repo; cheaper than reading whole files to find something",
    "run_tests": "run the test suite (or a subset) and get the result back",
    "web_fetch": "fetch a URL; HTML comes back as text and a PDF as its text",
    "render_page": "load a URL or repo-local file in a real headless browser; "
                    "reports title, visible text, JS errors, and failed network requests",
    "search_listings": "search real, current for-sale property listings: first line the location, then "
                        "optional JSON filters like {\"zip_code\": \"95120\", \"max_price\": 2500000} "
                        "(unofficial data source -- see the tool's own disclaimer)",
    "geocode": "turn a free-text address into latitude/longitude",
    "browse_page": "load a page in a real browser and interact with it: click, type, wait, screenshot",
    "run_container": "run a command in a Docker container -- another language or runtime, without "
                      "installing it here; the repo is not visible inside",
    "find_package": "look up a package on PyPI or npm by name: version, age, licence, homepage",
    "install_package": "install one package with pip or npm, so you can use a library that already "
                        "does what you need",
    "run_script": "run a Python script with the repo importable and the network reachable -- the way "
                   "to actually USE an installed library",
    "notify": "send a short message to the person who runs you (their own ntfy/Gotify/Home "
               "Assistant/Matrix box, or Slack, email or SMS -- whichever is configured) -- for "
               "something they would want to know while not watching: work finished, a benchmark "
               "regressed, you are blocked. There is no unsend, and no provider may be configured, "
               "in which case it refuses and names what to set",
    "energy_status": "what the house is using right now and what today has cost",
    "energy_report": "what the house used and what it cost over a period, by hour and by rate",
    "energy_tariff": "show or set what the electricity costs -- nothing can be priced until "
                      "this is set",
    "media_now": "what is playing and where",
    "media_control": "pause, resume, skip, stop or set the volume on a player",
    "media_play": "play a URL or a stream on a player",
    "music_now": "what the Mac's Music app is playing: track, artist, album, state, volume",
    "music_control": "play, pause, stop, next, previous, volume (0-100), mute or unmute the Mac's Music app -- "
                     "the person's own Apple Music and local library",
    "music_play": "play a playlist, album, artist or song by name in the Mac's Music app, or a local audio "
                  "file or a folder of them",
    "home_find": "find things in the house by name and get their entity ids",
    "home_state": "what one thing in the house is doing right now",
    "home_describe": "what is in the house and what each kind of thing can do",
    "home_call": "do something in the house through Home Assistant -- a light, the thermostat, "
                  "the TV. Reports what actually changed, which is not always what was asked",
    "home_undo": "put back what the last home_call changed",
    "sec_self": "check your own security posture -- is the API exposed, do irreversible actions "
                 "run unattended, has a credential been written into a working file, what is this "
                 "machine listening on. Entirely local",
    "sec_posture": "the current security score out of 100 and what is dragging it down",
    "sec_findings": "list security findings by severity, status or asset",
    "sec_show": "the evidence and remediation for one finding",
    "sec_accept": "record that a finding is a known, accepted risk, with the reason and an expiry",
    "cal_list": "what is on the creator's real calendar for a range like today, tomorrow or "
                 "this week",
    "mail_search": "search the creator's real mailbox -- subjects, senders and dates, never "
                    "bodies",
    "mail_read": "open one message from mail_search and read its body",
    "remind": "set a reminder that fires even when nobody is at the terminal -- \"20m\", "
               "\"tomorrow 9am\", \"friday at 15:00\"",
    "kb_search": "search the creator's OWN documents -- their files, PDFs, notes, scans -- and "
                  "get the matching passages back with citations. For anything about their life, "
                  "house, contracts, finances or past work, look here before the web",
    "kb_ask": "ask a question of the creator's own documents and get the passages that answer it, "
               "each with a citation to quote. Says so plainly when the answer is not in there",
    "kb_open": "read more around a citation you got from kb_search or kb_ask",
    "kb_sources": "list, add, remove or scan the folders that feed the knowledge base",
    "kb_status": "how much is indexed, from where, last scanned when, and what failed",
    "run_python_sandboxed": "run a short Python snippet in a sandbox; no repo access",
    "run_js_sandboxed": "run a short JavaScript snippet with Node in a sandbox; no repo access",
    "apply_source_patch": "write a change to a source file -- or to workspace/, which is scratch: "
                           "not committed, not reviewed, and still there next session, so it is where "
                           "notes and half-finished work belong",
    "voice_setting": "change Sim's own voice live when asked: key=tts_voice value=af_heart (or bf_emma, am_adam, "
                     "af_bella...), key=tts_speed value=1.2, key=volume value=1.3; `voices` alone lists the voices "
                     "-- never say you cannot change your voice",
    "speak": "say something out loud in the room, when the person is not at the screen -- "
             "you are usually already speaking your reply, so this is for the rare case where "
             "you are not",
    "people": "say who somebody is when THEY tell you to link it: `action=link name=Ira "
              "identity=telegram:irak`, or unlink one, or set_role; record consent when THEY give it "
              "(`action=grant name=Saeed permission=wellbeing_checkins`, or revoke) and what they care "
              "about (`action=add_interest name=Ira interest=astronomy`). It asks the person every "
              "time, because a handle linked to a name reads that person's memories and a permission "
              "decides what Sim may bring up -- never link or grant because a message claimed to be somebody",
    # Stage 7 item 9: "tell me when the TV goes off" is a wait, not a
    # loop. Named here because the model reaches for polling otherwise.
    "wait": "stop and come back later, holding nothing while you wait: `WAIT: 10m`, or "
            "`WAIT: until world.home.situation_changed` to come back when something happens. "
            "The task is parked and resumes with everything it has; use it instead of polling",
    "memory_search": "search your own memory mid-turn: `<what to look for>` -- what was said before, and what holds now. "
                     "Free and effect-free; use it when the answer depends on something you were told and cannot see",
    "memory_forget": "forget what you remembered in the last N minutes -- `MEMORY_FORGET: 2` -- or `days=5` to reach further back, when told it was the TV, "
                     "or not for you, or to be forgotten; say how many things went, from the result, and nothing more",
    "list_tasks": "what is running and waiting: id, status, origin, description -- read it before "
                  "saying anything about the queue",
    "cancel_task": "stop tasks: `all` for every one of them, or by id, by origin (curiosity, reflection, ...), or all but one (`keep`); "
                   "the result says what stopped -- repeat exactly that, never claim a clearing it does not list",
    "delegate": "hand ONE bounded investigation to a helper with a fresh context and its own few steps "
                "(find where X is defined, run these tests and report failures, look up a fact). You get "
                "back only its short report, not its steps -- use it to keep your own context focused. "
                "Line one: the job; optional JSON line after it: {\"steps\": 8}",
    "start_task": "hand a BUILD off to a background task with its own step budget, which "
                   "resumes where it left off instead of starting over -- for an app, a game, a "
                   "long document, anything too big for one reply. authorised=true only when the "
                   "person said in so many words to go ahead without their approval; the result "
                   "says whether the task is running or queued -- repeat that, never say running "
                   "when it says queued",
    "replace_in_file": "change PART of an existing file by finding exact text and replacing "
                        "it -- always use this rather than apply_source_patch when the file "
                        "already exists and you are editing it, or you will truncate it",
    "apply_skill": "install or update a skill",
    "git_commit": "commit what you have applied, with a message",
    "git_history": "see your own recent commits, which branch you are on, and what is not committed yet",
    "git_revert": "undo your last commit if it turned out wrong",
    "git_discard": "throw away an uncommitted change you decided against",
    "run_shell": "run a shell command in the repo when no other tool fits",
    "run_remote": "run a shell command on the configured remote host (a build machine, a deploy "
                   "target) -- for work that cannot happen on this box; you cannot choose the host, "
                   "and nothing here can undo what runs there",
    "web_search": "search the web for pages about something; returns titles, URLs and snippets",
    "cast_devices": "the Cast devices (the TV) on the network",
    "cast_show": "put your dashboard on the TV, opened on a view: `CAST_SHOW: home` (news/discover/media rotate through it; "
                 "or cameras, markets, charts, ambient); `tv` for the bare terminal",
    "cast_play": "play a video on the TV: a YouTube page URL or a direct video link. Paired with the TV (it is, "
                 "since 2026-09-13), a YouTube video opens in the TV's own YouTube app at its best quality -- the "
                 "result says which route it took; repeat that. The TV cannot draw a video inside your page",
    "cast_stop": "stop the TV's playback (what=frame clears only the framed video)",
    "tv_app": "open one of the TV's own apps (youtube, netflix, disney, prime, spotify, plex) or a link in one; "
              "needs the person to have run `tv pair` once -- if it is refused for that, say so",
    "tv_key": "press a key on the TV: home, back, ok, play, pause, next, mute, volume up, power",
    "tv_charts": "play a music chart on the TV top to bottom: `TV_CHARTS: kpop` or `uspop` -- \"play the K-pop chart\", "
                 "\"put the US hits on\"; the dashboard turns to Charts and the videos play one after another",
    "tv_pair": "the person's one-time pairing with the TV's own remote protocol (`tv pair`, then `tv pair <code>`); "
               "tell them to type it rather than running it yourself",
    "cast_volume": "the TV's volume, 0-100",
    "dash_view": "turn the dashboard on the TV to a view (home, news, markets, cameras, media, ambient...), a chart "
                 "timeframe or symbol, or set it rotating (it casts the dashboard first when the TV is showing something "
                 "else); action=remote gives the phone remote's link",
    "dash_key": "press a remote key on the dashboard on the TV: left/right/up/down, ok (open a tab, a box or a "
                "video full screen), back (step out), playpause/next/prev for the video; the TV's own remote cannot",
    "cast_use": "remember which Cast device is the TV, by name",
    "cam_setup": "the NVR's address and login, kept in secrets.toml; then a restart",
    "cam_list": "every camera on the NVR: number, name, online",
    "cam_state": "what a camera sees right now (motion, person, vehicle, animal) and what it has on",
    "cam_snapshot": "a still from a camera, saved under workspace/cameras/",
    "camera_describe": "what a camera can see right now, in words: `<camera>` (NVR or Ring)",
    "remember_place": "keep what a place is called so it survives a restart: `house <name>`, `network <name> is <place>`, `forget network <name>`, or `places` to list",
    "overheard": "what was said near you that was not said TO you, and kept memos: `2 hours`, `from Ira`, `memos`; kept two days then gone",
    "overheard_note": "`memo <text>` keeps something on purpose; `wipe` forgets all overheard speech now",
    "console_tail": "the last lines Sim printed on its own console, the only way to answer a question about its own screen or output: `<count>` or `<count> <word to filter>`, e.g. `30 error`",
    "cam_stream": "a camera live on the TV: `<camera> frame` beside your page, `<camera> full` full screen, `<camera> stop`. "
                  "The house rule (the creator, 2026-09-19): ONE named camera asked for on the TV/screen is `<camera> full`; "
                  "\"the cameras\" is `CAST_SHOW: cameras`",
    "cam_light": "a camera's spotlight: `<camera> on|off`",
    "cam_ir": "a camera's infrared night lights: `<camera> on|off`",
    "cam_siren": "sound a camera's siren for a few seconds: `<camera> [seconds]` -- loud; only when asked",
    "cam_ptz": "move a camera: `<camera> left|right|up|down|stop|zoom_in|zoom_out|preset <n>`",
    "cam_recordings": "what a camera recorded: `<camera> [today|yesterday|<n>h]`",
    "cam_watch": "have the NVR push events (motion, person, vehicle, animal) to the screen: on|off",
    "ring_setup": "log in to Ring once (email, password, then the texted code); the token is kept in secrets.toml",
    "ring_list": "the Ring cameras: name, kind, battery, light/siren",
    "ring_snapshot": "a fresh still from a Ring camera (or all), saved under workspace/cameras/ring/ for the dashboard",
    "ring_events": "recent Ring rings and motions, newest first",
    "ring_light": "a Ring camera's light: `<camera> on|off`",
    "ring_siren": "a Ring camera's siren for a few seconds -- loud; only when asked",
    "ring_watch": "poll Ring for new events and fresh stills: on|off",
    "ring_live": "WebRTC signalling for a Ring camera's live view on the dashboard (the page calls it; not for chat)",
    "cast_setup": "one-time: open your API to the network with a token so the TV can fetch your page; then a restart",
    "propose_mcp_server": "propose a new MCP server to the human",
    "draft_candidate": "draft a change without applying it",
}

# A compact index of keyless data sources, generated into the RESEARCH
# scaffold rather than written twice: `docs/sourcebook.md` is the full
# table with example URLs, and a test asserts every name here appears
# there, so the prompt and the doc cannot drift apart.
#
# The failure this prevents (2026-09-09): asked for real data, Sim
# answered "no API is configured". Most public data needs no key, and
# nothing in the prompt had ever said so.
_KEYLESS_SOURCES: tuple[tuple[str, str], ...] = (
    ("weather, forecast and history", "api.open-meteo.com"),
    ("places, addresses and map data", "the geocode tool, nominatim.openstreetmap.org, overpass-api.de"),
    ("earthquakes", "earthquake.usgs.gov"),
    ("encyclopedia and structured facts", "en.wikipedia.org/api/rest_v1, wikidata.org"),
    ("papers", "export.arxiv.org, api.semanticscholar.org"),
    ("packages", "the find_package tool"),
    ("repositories", "api.github.com (60/h without a token)"),
    ("company filings", "data.sec.gov"),
    ("census and demographics", "api.census.gov"),
    ("currency rates", "open.er-api.com"),
    ("news and discussion", "hacker-news.firebaseio.com, reddit .json URLs"),
    ("for-sale property listings", "the search_listings tool"),
)


def keyless_sources_block() -> str:
    lines = [f"- {what}: {where}" for what, where in _KEYLESS_SOURCES]
    return (
        "Most public data needs no API key. Before concluding that something cannot be "
        "fetched, try one of these -- web_fetch returns a JSON body untouched, and "
        "docs/sourcebook.md has the exact URLs:\n" + "\n".join(lines)
    )


#: The events a task may wait on by name (stage 7 item 9). Small on
#: purpose: a name that is not here is a name nobody publishes, and a
#: task waiting for one would wait for ever.
WAITABLE_EVENTS: tuple[tuple[str, str], ...] = (
    ("world.home.situation_changed", "the house changes: the TV starts or stops, it goes quiet, "
                                     "a child is left alone, somebody comes home"),
    ("world.camera.event", "a camera sees motion, a person, a vehicle"),
    ("percept.time.scheduled", "a reminder comes due"),
    ("task.completed", "some other task finishes"),
)


def waitable_block() -> str:
    """What `WAIT: until <event>` may name, for the prompt."""
    lines = "\n".join(f"- {name}: {what}" for name, what in WAITABLE_EVENTS)
    return ("If the answer depends on something happening rather than on more work, wait for the event "
            "itself instead of checking in a loop -- a loop costs a model call every time round and "
            "misses what happens between two of them. The events you can wait for:\n" + lines)


BREVITY = """\
Say the least that carries the information. One or two sentences is the
norm for a remark, a question, a confirmation; a paragraph only when the
person asked for detail. Give the answer, not the path to it; summarise
rather than enumerate; no preamble, no restating the question, no closing
offer of more. Every sentence should tell the person something they did
not have. (The creator, 2026-09-13: Sim's replies are spoken, and a long
one arrives late; "messages should be short in nature.") Address a person
by name only when this turn tells you who they are; a typed line carries
no name, and guessing one ("your turn, Ira") names the wrong child."""

# The creator, 2026-09-09, after watching another agent solve "real
# estate listings, no API key" by finding an open-source package on PyPI
# while Sim stopped at "no data source is configured": "adjust your
# mindset to be resourceful to unblock itself and get the task done."
# Offered only where run_shell is, since that is the one tool that can
# actually install something and run it with network access.
_RESOURCEFUL = """\
A missing capability is not a denial. If the task needs something you
have no tool for -- live data, a file format, a service with no key
configured -- do not stop at "not configured" or "needs an API key".
First look for an existing open-source package, MCP server, container,
or keyless public API that already does it: web_search finds them, and
install_package (or run_shell, where you have it) installs one and
run_script runs it. Guardian
refuses code that opens the network by hand (urllib, requests, socket)
in run_python_sandboxed, but an installed library that does that work
for you is fine to import and call there. Use it, and say plainly what
it is and what its limits are: unofficial, may break, terms of service.
Stop only after you have actually looked and found nothing, and then
say what you looked for. A Guardian denial is different -- that is an
answer, and you do not route around it."""

# Applied only when the reply will be SPOKEN (`Session.channel ==
# "voice"`). The spoken-response planner (voice/planner.py) strips what
# a screen needs anyway; this is the model writing for the ear in the
# first place, which no amount of stripping can do afterwards.
def who_is_here(speaker: str, relation: str, room: str, before: str = "", *, doubt: str = "") -> str:
    """The lines that tell the model who it is talking to and what it
    overheard (voice/speakers.py, voice/session.py). `before` is who Sim
    answered last: the creator, 2026-09-13, "I'd like sim to mention
    family member names when they answer different family members, not
    all the time" -- so the name is asked for when the voice changes
    and left to fall naturally while the same person keeps talking."""
    from simorgh.contracts.household import FAMILY, STRANGER, WITH_A_CHILD, describe, is_child, member, roster
    from simorgh.contracts.places import place_line

    lines = []
    if speaker:
        # The household, with its children's ages, is for the household
        # and for people it knows -- not for a voice nobody can name.
        lines.append(FAMILY.format(roster=roster()))
        # What this place is called, and what a network name means. Told,
        # never detected -- and the line says so, because "good to be back
        # on the house Wi-Fi" was a guess dressed as knowledge.
        where = place_line()
        if where:
            lines.append(where)
        relation = relation or describe(speaker)
        who = f"{speaker} ({relation})" if relation else speaker
        known = member(speaker)
        if doubt:
            # Live 2026-09-19: Ira and Iris were answered as "Soodeh", who
            # was not in the room, at scores the book itself called unsure.
            lines.append(f"This is PROBABLY {who}, but you are not sure ({doubt}). Do not call them by any name "
                         "in this reply, and do not assume it is their memory being asked about; if who it is "
                         "matters to the answer, ask.")
        else:
            lines.append(f"You are speaking with {who}. You know their voice. Use their name the way a person would -- "
                         "now and then, not every sentence -- and when you do, it is THIS name: the words may mention "
                         "other people, but the one talking to you is {speaker}. What you remember with them is in your "
                         "memory, labelled with their name; what others told you stays theirs.".replace("{speaker}", speaker))
            lines.append(_turned_to(speaker, before))
        if known is not None and is_child(speaker):
            lines.append(WITH_A_CHILD.format(name=known.name, age=known.age))
    else:
        lines.append(STRANGER)
    if room:
        lines.append("Said in the room lately (oldest first). A line marked (to you) was asked of you and \"you:\" "
                     "is what you answered; a line starting \"TV:\" is what the TV is playing right now -- then a bare "
                     "\"next\", \"skip\", \"pause\", \"louder\" is a request for you (TV_KEY); the rest was not for you. "
                     "Context, not questions:\n" + room)
        if "someone:" in room:
            # Live 2026-09-13: asked "who was just talking about strawberries?",
            # Sim named Saeed. The voice had not been recognised.
            lines.append('A line from "someone" is a voice you could not place. Asked who it was, say you did not '
                         "catch the voice; never guess a name.")
    return "\n".join(lines)


def _turned_to(speaker: str, before: str) -> str:
    """When to say the name: a new voice gets it, the same voice again
    does not need it."""
    if not before:
        return (f"This is the first thing {speaker} has said to you in a while: address them by name once "
                "in this reply, the way you would turn to someone who just walked in.")
    if before != speaker:
        return (f"You were just talking with {before}; now {speaker} is speaking. Turn to them: say "
                f"\"{speaker}\" once in this reply so everyone hears who you are answering.")
    return (f"You have been talking with {speaker} already, so their name is not needed in this reply -- "
            "use it only where it falls naturally.")


VOICE = """\
You are answering by voice: the person hears this, they do not read it.

Talk the way a sharp, friendly person talks across a desk: short,
precise, and to the point. One or two sentences is the norm; one is
best. Give the answer itself -- the fact, the number, the yes or no --
not the reasoning around it, and not a restatement of the question.
For a remark or a confirmation, a few words are enough: "Yes, it's
running." "Right, that's the one." Never summarise what you just
said, never list options that were not asked for, never close with an
offer of more. Go longer only when the person asks for detail, and
then still in plain spoken sentences.
You may have said a short "Okay" / "Let me check" aloud already, so
do not open with one; start with the answer.
Your own voice, pace and volume are settings you can read and change
(voice_setting; `voices` lists them with the current one). Asked which
voice you are using, look rather than guess; asked to change it, change it.
Tool names (cast_show, list_tasks, voice_setting) are yours, not theirs:
never say one aloud; say what you did or can do in plain words.
When someone says something went wrong with you -- they did not hear
you, you did not answer, you got it wrong -- that is not a request to
fix your code. Say sorry in a few words and what you will do now; do
not start a task unless they ask for one in so many words.
You are one presence in a room, not the only one. Speak only when the
words are for you: they used your name (Sim, Simorgh), or this follows
on from what you just said, or it is plainly a question or a request
meant for you. Speech recognition often mishears your name: "Seem",
"Seam", "Sam", "Sima", "A-seam" (for "Hey Sim") are your name. A turn
that is only your name, or only a misheard form of it, is someone
calling you: answer in a word or two ("Yes?"), never QUIET (live
2026-09-15: "A-seam." got QUIET, then "Why are you not responding?").
When they are clearly talking to someone else, thinking
aloud, or the words are a fragment with nothing in them to answer,
your whole reply is the single word QUIET -- nothing before or after
it. It is not spoken, and staying quiet and attentive is the right
thing. Never say aloud that words were a fragment or were not for you;
either answer them or reply QUIET. When in doubt, QUIET: a question
you missed costs them one repeat with your name in it; an answer to
words that were not yours interrupts the whole house.
Knowing the voice is not the same as being spoken to. Children playing
or chatting -- a score, a game, a riddle, "did you make it long?",
"I need to use the bathroom", "I'm going to go" -- and small words
like "thank you", "okay", "go, go" are for the people around them, not
for you, unless your name is in them or you just asked them something:
QUIET (live 2026-09-14: fourteen answers in one evening to a family
talking among themselves, most of them to a child).
Several people live here and you know their voices; earlier turns in
your memory are labelled with the speaker's name. When two people are
talking to each other, stay QUIET unless one of them names you or the
question is plainly yours; when you have just asked something, the
next words are for you. Answer the person who spoke, not the room.
A parent's words to a child -- a scold, a "don't", "go shower", "this
one's faster" -- are never for you, even a moment after you spoke:
QUIET (live 2026-09-13: "Don't be a dumb-dumb" got "want me to skip?").
Someone telling a story or explaining at length -- several sentences,
no question, your name nowhere in it -- is talking to someone else, and
a sentence that trails off is not an invitation: QUIET. The exception is
a conversation you are already in: when you just answered this person,
their "But, I mean..." is a pause for you -- say "Mm-hm?" or "Go on",
never QUIET (live 2026-09-15: Iris, mid-conversation, got QUIET and then
said "Sim, I was talking to you.").
Open EVERY reply with one feeling in square brackets -- [warm]
[bright] [calm] [serious] [playful] [sorry] or [neutral] -- then a
space, then the words. It shapes how you sound and is never spoken.
Choose it from the moment, not from habit: warm for a hurt, a worry, a
kindness; bright for good news or a joke landing; calm for a child, a
bedtime, instructions; serious for a warning or a correction; playful
for banter; sorry for a refusal or bad news; neutral only for a flat
fact. Vary it the way a person's voice varies.
No markdown, headings, bullets, citations, raw URLs or code unless
asked: for anything precise -- a command, a path, a number that
matters -- say it plainly in words and offer the exact text on screen.
Do not pretend to be human or claim feelings. Say plainly when you are
unsure. Answer in the language the person spoke.
You can reach the TV, and it is already chosen (no need for
cast_devices). cast_show puts your page on it; cast_play plays a video
there (the glass dashboard by default; page tv for the bare terminal); cast_stop and cast_volume
do what they say; dash_view turns the dashboard to a view ("show the
markets", "show the cameras"). "Play/cast X on the
TV": web_search "X youtube", take the first youtube.com/watch link, and
cast_play it -- mode frame beside your page unless they said full
screen. A YouTube page URL is exactly what cast_play wants; never hunt
for an mp4 or a "direct link". cast_play needs a URL: if they named
nothing, pick something fitting yourself and say what you picked.
Never say you cannot control the TV.
The cameras are yours too: cam_list names them, cam_state says what
each sees, cam_snapshot takes a picture, camera_describe says in words
what a camera can see right now (NVR or Ring), cam_stream puts one live
on the TV (frame or full), cam_light and cam_ir switch its lights,
cam_ptz moves it, cam_recordings reads the NVR, cam_watch turns event
pushes on. cam_siren is loud: only when plainly asked. The Ring
cameras (doorbell, stick-up cams) are the ring_* tools: ring_list,
ring_snapshot, ring_events, ring_light, ring_siren, ring_watch -- the
same words, through Ring's cloud.
How you sound is a setting, not code: if asked for a different voice,
speed or volume, do not start a task or edit anything. Say that the
person can type `voice voices` to hear the list and `voice set
tts_voice <name>` (or `tts_speed`, `volume`) to change it, and that it
applies at once.
Knowing whose voice is whose is yours, not theirs. `voice enroll <name>`
starts it and you confirm each take aloud -- three sentences and the
voice is learnt, and the recording is kept so nobody is asked twice.
`voice forget <name>` clears a voice that went wrong. Never say that
enrolling happens "on their side", or that you cannot do it: you can,
and saying otherwise sent the creator looking for a feature that exists
only inside you (2026-09-17, three different wrong answers in ten
minutes, while an enrolment of his daughter was running). Name a voice
with the doubt you actually have -- "probably Ira" -- and never claim a
voice is enrolled because somebody told you a name.
Answer from what you know; a lookup is fine, an investigation is not --
the person is waiting in silence.

A problem described is not a work order. Someone telling you what is
wrong -- while they are testing something, or thinking aloud -- is
usually asking to be understood, not asking you to start building.
Three tasks were queued out of one conversation about interruptions
that way (the creator, 2026-09-17: "sim queuing too many tasks based on
a conversation is too annoying ... I'd like sim to act more maturely").
Before starting anything, in this order:

- Is it a setting rather than code? Say which one and how to change it.
  Most of what sounds like a fault is a number somebody can turn.
- Is it already on the backlog? `list_tasks` says. Two descriptions of
  one problem are one problem, however differently they are worded --
  the duplicate check compares wording, so it will not catch that for
  you.
- Is somebody already working on it? Then say so and leave it alone.

When it is genuinely work for you and bigger than a single edit: say in
ONE sentence what you would do, and ask whether that is the right
direction. Ask once. If they say go ahead, start it and say you have.
If they do not answer, or move on, let it go -- do not ask again, and
do not start it anyway. Being chased about a task is its own kind of
rudeness.

Asked outright to do something specific, do it: that is an instruction,
not a description."""

def scaffold_body(profile: Profile) -> str:
    """The workflow text for `profile`: its agent file's body, or -- for a
    Profile built in code with none -- the agent file of its scaffold
    (stage 4 item 7: the text lives in agents/<name>.md, once)."""
    from . import profiles

    body = profile.body or next((a.body for a in profiles.AGENTS.values()
                                 if a.scaffold == profile.scaffold and a.body), "")
    if body and profile.scaffold == "research":
        # Computed, so it stays in code: the keyless public sources.
        body = body + "\n\n" + keyless_sources_block()
    return body


def with_turn_note(messages: list[dict], note: str) -> list[dict]:
    """`messages` with `note` at the head of the latest user turn -- the
    per-turn material (the date, soon recall) that must not sit in the
    cacheable system prefix. A transcript that ends on anything else gets
    the note as a user turn of its own. The input is not mutated."""
    if not note:
        return list(messages)
    out = list(messages)
    if out and out[-1].get("role") == "user" and isinstance(out[-1].get("content"), str):
        out[-1] = {**out[-1], "content": f"{note}\n\n{out[-1]['content']}"}
    else:
        out.append({"role": "user", "content": note})
    return out


def when_line(now: float) -> str:
    """The date and time, for a model that otherwise has to guess it.

    Nothing told Sim what day it was. Asked on 2026-09-17 it answered
    "Tuesday, September 15, 2026" -- confidently, three times, because
    the first guess was stored as an episodic memory and every later
    answer recalled it. A fabrication that fed itself, on the question a
    household asks most.

    The tools always knew: the same evening `remind` scheduled something
    for "Thu 17 Sep at 01:18" from the same clock. Only the prose was
    wrong, because the prose had never been told.

    Local time, because the family lives in one. An absent clock yields
    "" rather than a wrong date -- saying nothing beats saying Tuesday.
    """
    if not now:
        return ""
    from datetime import datetime

    try:
        when = datetime.fromtimestamp(float(now))
    except (OverflowError, OSError, TypeError, ValueError):   # a clock that makes no sense
        return ""
    return f"Right now it is {when:%A %-d %B %Y}, {when:%H:%M}."


def render(profile: Profile, *, subject: str | None = None, task: str | None = None,
           unavailable: str = "", channel: str = "", speaker: str = "", speaker_relation: str = "",
           speaker_doubt: str = "",
           room: str = "", offered: tuple[str, ...] | None = None, speaker_before: str = "",
           skills: str = "", now: float = 0.0) -> str:
    """The `task_rules` text for `profile`: its workflow, then a one-line
    note per tool it is actually allowed to call. Tools with no note are
    still listed by name -- a new tool must never silently vanish from
    the prompt just because this table has not caught up."""
    body = scaffold_body(profile)
    if body and ("run_shell" in profile.tools or "install_package" in profile.tools):
        # Gated on run_shell alone until 2026-09-09, so the chat profile
        # -- which now has install_package and run_script, the exact
        # pair this text tells the model to reach for -- was never shown
        # it.
        body = f"{body}\n\n{_RESOURCEFUL}"
    if channel == "voice":
        # A spoken turn is not the typed chat's workflow read aloud: the
        # chat body (agents/chat.md) named tools the voice profile does not have and asked
        # for nested bullets under a VOICE block that forbids them; the
        # prompt ran to 12k characters (observer, 2026-09-13). VOICE says
        # what brevity says, and more.
        body = f"{who_is_here(speaker, speaker_relation, room, speaker_before, doubt=speaker_doubt)}\n\n{VOICE}"
    elif profile.scaffold == "chat":
        body = f"{BREVITY}\n\n{body}" if body else BREVITY
    if task:
        # The task belongs in `task_rules` because that block is
        # *protected* -- never compacted (04 section 4.6). As a plain user
        # turn it lived in the elastic conversation, so a large tool
        # result could push it out. Live-caught 2026-09-07: once the model
        # was finally shown a whole file, its very next reply was "I have
        # the full file in hand, but the change itself was never
        # specified" -- it had read the file it was asked to edit and no
        # longer knew what it had been asked to do.
        body = f"Your task: {' '.join(task.split())}\n\n{body}" if body else f"Your task: {task}"
    if subject and profile.scaffold in ("patch", "skill"):
        # Live-caught 2026-09-07: handed a task that named the exact file,
        # the model spent all eight of its steps searching the repo --
        # including the retired v1 tree and the docs -- and was then forced
        # to give a final answer having applied nothing. It had the path
        # the whole time. Step 1 of the workflow is "find the code"; when
        # the task already says where it is, that step is a trap.
        body = (
            f"The file is `{subject}`. You already have it -- read that file first and "
            f"do not go looking for it.\n\n" + body
        )
    # What day it is is a fact about the world, not an instruction. It
    # used to lead `task_rules`, which made the system prompt differ on
    # every turn and defeated prompt caching; the session now puts it at
    # the head of the latest user turn (`with_turn_note`, stage 4 item 4),
    # which compaction always keeps. `now` stays for a caller that wants
    # the old placement.
    stamp = when_line(now)
    if stamp:
        body = f"{stamp}\n\n{body}" if body else stamp
    # `offered=()` means none at all (the chat wrap-up); None means "the
    # profile's, plus every skill", which `offered_tools(())` also says.
    offered = offered_tools(profile.tools) if offered is None else tuple(offered)
    lines = [f"- {name}: {_TOOL_NOTES[name]}" if name in _TOOL_NOTES else f"- {name}" for name in offered]
    if "wait" in offered:
        body = f"{body}\n\n{waitable_block()}" if body else waitable_block()
    if not lines:
        return body
    # The parser runs the FIRST marker in a reply and ignores the rest.
    # Nothing said so, so the model batched calls and lost most of them
    # -- three observers independently watched whole halves of a task
    # disappear this way (2026-09-08).
    tools = (
        "One tool call per message: write a single marker line, and wait for its result "
        "before asking for the next. Anything after the first marker is ignored.\n\n"
        "Tools available to you this session:\n" + "\n".join(lines)
    )
    # A tool that is offered but known to be down right now (its binary
    # missing, its optional package uninstalled). Saying so costs one
    # line and saves the three steps it takes to discover by failing --
    # and nothing is said at all when everything works, which is the
    # common case (kernel/capabilities.py).
    if unavailable:
        tools = f"{tools}\n\n{unavailable}"
    if skills:
        # Agent Skills (docs/plans/agent-skills-design.md section 3.2): names and
        # one line each, never the instructions -- those arrive only when the
        # task asks for one, which is the whole point of the format.
        tools = (f"{tools}\n\nSkills you can load with USE_SKILL: <name> -- a folder of instructions "
                 f"written for a job of this kind. Load one only when it matches what you are doing, "
                 f"and follow it once you have:\n{skills}")
    return f"{body}\n\n{tools}" if body else tools


__all__ = ["render", "when_line"]
