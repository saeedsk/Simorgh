"""One Stop hook: a final answer that claims what no tool did bounces once.

Stage 4 item 8. Four claim guards grew up one incident at a time inside
`session.py`'s loop -- a commit nobody ran, a promise nothing keeps, a TV
that was never touched, a pronunciation never written -- each with its own
copy of "record a rejected step, hand the words back, try again". They
are rules of this one hook now, checked in order, and a turn bounces at
most once (`Session.claim_corrected`) whichever rule fires. The generic
rule, `claimed_effect`, covers what the specific ones did not name: a
chat reply saying something was turned, set, sent or scheduled when no
tool that changes anything succeeded this turn.

The hook names its rule on every bounce, as the step's text and as a
`orchestration.stop_hook` telemetry event, so each rule's rate is
countable before any is retired (plan: a rule goes when its counter
reads zero on native paths for a bless cycle).

False negatives are fine; a false positive costs the person a turn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .tools import is_read_only, offered_tools


_TV_CLAIM = re.compile(
    r"(?:\b(?:is|are|'s|it's|that's)\s+(?:now\s+|already\s+)?(?:playing|running|up|showing|on\s+(?:the\s+)?(?:tv|screen))\b"
    r"|\b(?:i(?:'ve|\s+have)?\s+)?(?:put|turned|switched|started|queued|cast|sent|opened|pulled|pushed)\b[^.!?]{0,60}"
    r"\b(?:tv|dashboard|chart|screen|video|song|youtube)\b"
    r"|\bplaying\s+(?:on|in)\s+(?:the\s+)?(?:tv|family room|youtube))", re.I)
_TV_TOOLS = ("cast_play", "cast_show", "tv_charts", "tv_app", "tv_key", "dash_view", "cast_stop")

#: Someone asking for the screen: "put the dashboard up", "play X on the TV",
#: "show me the cameras". Without one of these, nothing goes on the TV.
_TV_ASK = re.compile(
    r"\b(?:tv|television|screen|chromecast|cast|dashboard|dash)\b"
    r"|\b(?:play|show|put|turn|open|pull)\b[^.!?]{0,40}\b(?:up|on|screen|tv)\b"
    # Things that live nowhere but a screen: "show me the cameras".
    r"|\b(?:play|show|stream|open|cast|put)\b[^.!?]{0,30}"
    r"\b(?:camera|cameras|chart|charts|video|youtube|news|markets|wallpaper)\b", re.I)


def wanted_tv_act(session) -> bool:
    """Did they ask for anything on the TV this turn? The claim guard may
    correct Sim's words whenever it likes, but it may only ask Sim to
    *act* on the screen when someone asked for the screen.

    Live 2026-09-17, the creator: "dont auto cast dash on tv, unless it is
    being asked by user either from voice chat or tui". The guard below
    was handing the model `CAST_SHOW: home` after any loose sentence
    about the dashboard, and the model obliged -- a cast nobody wanted."""
    return bool(_TV_ASK.search((getattr(session, "user_text", "") or "")))



_DASH_ON_TV = re.compile(
    r"dashboard(?:'s| is)?\s+(?:\w+\s+){0,2}(?:on|up on|back on|showing on)\s+(?:the\s+)?(?:[\w ]{0,20})?(?:tv|screen)\b",
    re.IGNORECASE)


#: "the file is committed", with no tool run to commit it.
_COMMIT_CLAIM = re.compile(
    r"\b(?:committed|pushed|checked in|landed)\b[^.!?]{0,40}"
    r"\b(?:file|files|change|changes|code|skill|repo|repository|main|branch|git)\b"
    r"|\b(?:file|change|code|skill)\b[^.!?]{0,30}\b(?:is|was|has been)\s+(?:committed|pushed)\b", re.IGNORECASE)

#: "I'll stay quiet unless you address me" -- a standing change to how Sim
#: behaves, which no reply can make and nothing here stores.
#:
#: The first version listed the phrasings already seen, and missed three
#: more within minutes of shipping (2026-09-15/16): "Noted -- Majalli
#: Xilqat", "I'll keep that on file, Saeed", and "I'll treat those sounds
#: as my name from now on". Matching phrasings is the wrong shape; the
#: shape is a claim to RETAIN something, with nothing retaining it. So:
#: a first-person future plus a retention verb, OR a bare acknowledgement
#: that stands for one.
_PROMISED_BEHAVIOUR = re.compile(
    r"\b(?:i'?ll|i will|from now on|going forward|i'?m going to)\b[^.!?]{0,70}"
    r"\b(?:stay quiet|keep quiet|be quiet|stay silent|not respond|won'?t respond|not answer|"
    r"ignore (?:them|those|the tv)|remember (?:that|this|it)|keep (?:that|this|it) in mind|"
    r"bear (?:that|this) in mind|keep (?:that|this|it) on file|"
    r"(?:note|store|save|record|log) (?:that|this|it)|hold on to (?:that|this|it)|"
    # "treat those sounds as my name FROM NOW ON" is a standing change;
    # "I'll treat that as a yes and turn the lights off" is this turn.
    # Only the standing one is a promise nothing can keep.
    r"treat (?:those|that|it|them)\b[^.!?]{0,40}\bas\b[^.!?]{0,60}"
    r"\b(?:from now on|next time|in future|going forward|always|from here on)\b)"
    # "Noted -- X" says X was recorded. "Got it --" is how anyone opens a
    # sentence: live 2026-09-16 it fired on "Got it -- the kettle is on"
    # and "Got it -- playing the K-pop chart", burning a correction step
    # on turns that claimed nothing. The real case it was added for
    # ("Noted -- I've got it. I'll keep that on file") is caught by the
    # retention verbs above.
    r"|^\W*noted\b[^.!?]{0,60}?[-\u2014\u2013:]"
    r"|\b(?:i'?ve|i have)\s+(?:noted|stored|saved|recorded|written)\b", re.IGNORECASE)


def claimed_to_commit(text: str, session) -> str:
    """Words saying work was committed, when no tool ran -- or "".

    Live 2026-09-15: "The file is committed and callable the same way as
    my other skills", said in the same turn the runner recorded
    "finished with uncommitted changes". Nothing had been committed, and
    the claim was contradicted by Sim's own bookkeeping."""
    if not text or any(step.tool for step in session.steps):
        return ""
    match = _COMMIT_CLAIM.search(text)
    return match.group(0).strip() if match else ""


def promised_behaviour(text: str, session) -> str:
    """A promise to behave differently from now on, with nothing to keep
    it -- or "".

    Live 2026-09-15, told the voices it heard were the television: "Right
    -- those are TV voices ... so I'll stay quiet unless you address me
    directly." Nothing was stored, no setting changed, and the next
    unaddressed utterance was answered exactly as before. A promise the
    next turn cannot honour is worse than a refusal: it looks handled."""
    if not text or any(step.tool for step in session.steps):
        return ""
    match = _PROMISED_BEHAVIOUR.search(text)
    return match.group(0).strip() if match else ""


def claimed_tv_act(text: str, session) -> str:
    """The words in `text` that say the TV is doing something, when no
    tool ran this turn and the TV tools were offered -- or "".

    Live 2026-09-13: "Sim played the K-pop chart" (whisper's past tense
    for "play") got "The K-pop chart's running on the TV now" and no
    tool call; the TV sat idle. A claim of an act is checked against
    the acts."""
    if not text or not any(tool in session.profile.tools for tool in _TV_TOOLS):
        return ""
    asked = (getattr(session, "user_text", "") or "").strip()
    if asked.endswith("?") and re.search(r"\b(?:tv|television|screen|casting|playing|dashboard)\b", asked, re.I) \
            and not re.search(r"\b(?:can|could|would|will) you\b|\bplay\b.*\bon\b", asked, re.I):
        # "Are you casting that on the TV?" asks about the state; "yes, it is
        # on" is an answer, not an act (live 2026-09-13: the guard forced a
        # needless re-cast). "Can you play X on the TV?" is still a request.
        return ""
    if "cast_show" in session.profile.tools and not any(step.tool == "cast_show" for step in session.steps):
        # Putting the dashboard ON the TV is cast_show's act alone; dash_view
        # only turns the page of a dashboard that may not be on screen at all.
        # Live 2026-09-14: "The dashboard's back on the TV now -- home view",
        # twice, with only dash_view run, and the TV on its home screen.
        on_tv = _DASH_ON_TV.search(text)
        if on_tv:
            return on_tv.group(0).strip()
    if any(step.tool for step in session.steps):
        return ""
    match = _TV_CLAIM.search(text)
    return match.group(0).strip() if match else ""


#: "I've noted it", said of a name's pronunciation, with nothing written.
_NOTED_PRONUNCIATION = re.compile(
    # "Ira's pronunciation is set to EYE-ra", "is now pronounced": live
    # 2026-09-19, said after a tool that only LISTED voices had run.
    r"\b(?:pronunciation|pronounced)\b[^.!?]{0,40}\b(?:is|was|has been)\s+(?:now\s+)?(?:set|saved|stored|updated)\b"
    r"|\b(?:is|are)\s+now\s+pronounced\b"
    r"|\b(?:noted|noting|saved|stored|recorded|written it down|writing it down|made a note|keep saying|"
    r"i'?ll say it|i'?ll pronounce)\b[^.!?]{0,80}\b(?:name|pronunciation|pronounce|say it)\b"
    r"|\b(?:pronunciation|how to say (?:your|his|her|their) name)\b[^.!?]{0,80}\b"
    r"(?:noted|saved|stored|recorded|written down)\b", re.IGNORECASE)


def _stored_a_pronunciation(step) -> bool:
    """Only a step that wrote one backs the claim. Any tool used to count,
    so listing the voices (live 2026-09-19) let "Ira's pronunciation is set
    to EYE-ra" through with nothing written."""
    summary = str(getattr(step, "summary", "") or "")
    return bool(getattr(step, "tool", None) and getattr(step, "ok", False) and " is said " in summary)


def claimed_to_note_a_pronunciation(text: str, session) -> str:
    """The words that say a pronunciation was written down, when nothing
    ran this turn -- or "".

    Live 2026-09-15: told "the correct pronunciation of my name is Said",
    Sim answered "I've noted it so I keep saying your name right" and wrote
    nothing; the spelling the creator later saw was the one built into
    `contracts/household.py` all along. `voice pronounce <name> <how>` is
    what stores it, and until `sim_command` there was no way for the model
    to reach it at all."""
    if not text or any(_stored_a_pronunciation(step) for step in session.steps):
        return ""
    match = _NOTED_PRONUNCIATION.search(text)
    return match.group(0).strip() if match else ""


#: "I've turned the lights off", "the reminder is set" -- an effect claimed
#: in the first person or as a new state. Past or perfect tense only: "I'll
#: set a reminder" is a plan, and "I set it up yesterday" is rare enough.
_EFFECT_CLAIM = re.compile(
    r"\b(?:i(?:'ve| have)?|i just|i've just|i have just)\s+"
    # Not "added", "created" or "put": "I've added some context below" and
    # "I put together a summary" are how an answer describes itself.
    r"(?:turned|switched|set(?!\s+out)|sent|scheduled|booked|deleted|removed|saved|started|stopped|paused|"
    r"resumed|played|renamed|installed|dimmed|brightened|locked|unlocked|emailed|messaged|texted|"
    r"cancell?ed|muted|unmuted|armed|disarmed|ordered|reminded)\b[^.!?]{0,60}"
    r"|\b(?:is|are)\s+now\s+(?:on|off|set|locked|unlocked|playing|paused|muted|scheduled|saved|armed|disarmed)\b"
    r"|\b(?:reminder|alarm|timer)\s+(?:is\s+|has been\s+)?set\b", re.IGNORECASE)


def _changed_something(session) -> bool:
    return any(getattr(step, "tool", None) and getattr(step, "ok", False) and not is_read_only(step.tool)
               for step in session.steps)


def claimed_effect(text: str, session) -> tuple[str, tuple[str, ...]]:
    """`(the words, the tools that could have done it)` when a chat reply
    claims an effect and no tool that changes anything succeeded -- or
    `("", ())`. Only for chat: a task's claims are checked against its whole
    step log by `claims.unsupported_claims` at verification."""
    if not text or getattr(session.profile, "scaffold", "") != "chat" or _changed_something(session):
        return "", ()
    could = tuple(t for t in offered_tools(session.profile.tools) if not is_read_only(t))
    if not could:
        return "", ()
    match = _EFFECT_CLAIM.search(text)
    return (match.group(0).strip(), could) if match else ("", ())


@dataclass(frozen=True)
class Bounce:
    rule: str       # "pronunciation" | "commit" | "promise" | "tv" | "effect"
    quote: str      # the words that made the claim
    step: str       # the rejected step's text, for the log
    reply: str      # the turn handed back to the model


def check(text: str, session) -> Bounce | None:
    """The first rule `text` breaks, as a bounce; None when it breaks none.
    The caller bounces only once per turn and never on the last step."""
    noted = claimed_to_note_a_pronunciation(text, session)
    if noted:
        how = ("Write it for real with SIM_COMMAND: voice pronounce <name> <how to say it> "
               "-- IPA or a respelling, e.g. voice pronounce Saoirse Seer-sha."
               if "sim_command" in offered_tools(session.profile.tools)
               else "You have no tool that can store it, so say plainly that they should type "
                    "`voice pronounce <name> <how to say it>`.")
        return Bounce("pronunciation", noted, f"rejected a claim no tool backs: \"{noted}\"", (
            f"You said \"{noted}\", but nothing was written: a pronunciation lives on the person's "
            f"voice profile and only a tool puts it there. {how} Do not say it is noted when it is not."))
    committed = claimed_to_commit(text, session)
    if committed:
        return Bounce("commit", committed, f"rejected a claim no tool backs: \"{committed}\"", (
            f"You said \"{committed}\", but you called no tool this turn, so nothing was committed. "
            "Either run the tool that commits (git_commit, or worktree_land for a task's own branch) "
            "now, or say plainly that the change is written but not committed. Do not describe a commit "
            "that did not happen."))
    promised = promised_behaviour(text, session)
    if promised:
        return Bounce("promise", promised, f"rejected a promise nothing keeps: \"{promised}\"", (
            f"You said \"{promised}\", but nothing carries that to your next turn -- you have no memory "
            "of this instruction unless a tool stores it. If a setting can hold it, set it now "
            "(SIM_COMMAND: voice set <key> <value>). Otherwise say plainly that they should set it, "
            "rather than promising behaviour you cannot keep."))
    claimed = claimed_tv_act(text, session)
    if claimed:
        return Bounce("tv", claimed, f"rejected a claim no tool backs: \"{claimed}\"", (
            f"You said \"{claimed}\", but you called no tool this turn, so nothing happened on the TV. "
            "Write the marker on a line of its own now (TV_CHARTS: kpop, CAST_PLAY: <url>, "
            "CAST_SHOW: home, TV_KEY: next), or answer plainly without saying it is done."
        ) if wanted_tv_act(session) else (
            f"You said \"{claimed}\", but you called no tool this turn, so nothing happened on the TV -- "
            "and nobody asked for the TV. Do not put anything on it. Say what you meant without "
            "claiming anything is on the screen."))
    effect, could = claimed_effect(text, session)
    if effect:
        shown = ", ".join(could[:8]) + (", ..." if len(could) > 8 else "")
        return Bounce("effect", effect, f"rejected a claim no tool backs: \"{effect}\"", (
            f"You said \"{effect}\", but no tool that changes anything ran this turn, so it did not happen. "
            f"If it should, call the tool now (the ones that could: {shown}). Otherwise say plainly what "
            "you did and did not do."))
    return None


__all__ = ["Bounce", "check", "claimed_effect", "claimed_to_commit", "claimed_to_note_a_pronunciation",
           "claimed_tv_act", "promised_behaviour", "wanted_tv_act"]
