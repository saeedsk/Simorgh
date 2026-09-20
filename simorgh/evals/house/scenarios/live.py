"""The evenings that actually went wrong (stage 11 item 4).

Five failures the creator hit in his kitchen on 2026-09-19 and
2026-09-20, each written as a scenario. They are the harness's first
acceptance case because a simulator anchored in bugs that happened is
worth more than one anchored in bugs somebody imagined -- and because
each of these cost him an evening to find by hand.

Every one carries the commit that broke it and the commit that fixed
it, so a scenario that starts failing again names what it is about.
"""

from __future__ import annotations

from ..script import (
    Beat, Scenario, answered, did_not_call, first_audio_under, identified_as, quiet, remembered,
)

#: "Hello, Sam. Can you hear me?" -- five turns, all ignored.
#: Whisper wrote the name Sam, Sima and Seam; none were in the list of
#: spellings, so an unplaced voice never reached Sim (fixed 64f266e).
MISHEARD_NAME = Scenario(
    id="live/misheard-name",
    stage="3",
    because="2026-09-20: the creator said Sim's name four ways and got silence five turns running",
    beats=(
        # Each is a first utterance in its own right: what is being
        # tested is whether a misheard NAME still reaches Sim, and the
        # room path is what makes that a real question.
        Beat(who="Mara", says="Hello, Sam. Can you hear me?", expect=(answered(),)),
        Beat(who="Mara", says="Sima, I'm talking to you. Can you hear me?", ask_directly=True,
             expect=(answered(),)),
        Beat(who="Mara", says="What's up, Seam?", ask_directly=True, expect=(answered(),)),
    ),
)

#: A parent's aside to a child, in the room, not to Sim. The rule that
#: keeps Sim out of it is the one that nearly got widened away while
#: fixing the misheard name.
NOT_FOR_SIM = Scenario(
    id="live/an-aside-is-not-for-sim",
    stage="3",
    because="2026-09-20: a fix for the misheard name matched 'can you try a bit harder next time honey'",
    needs_model=True,
    beats=(
        Beat(who="Devin", says="Can you try a bit harder next time, honey.", expect=(quiet(),)),
        Beat(who="Devin", says="I said we are leaving in five minutes.", expect=(quiet(),)),
        Beat(who="Devin", says="Sim, what time is it?", expect=(answered(),)),
    ),
)

#: Twenty seconds of silence while Sim thought. Both covers failed: the
#: opening acknowledgement was inside the anti-tic gap and the "still
#: on it" filler waited longer than the answer took (fixed: 6 s).
A_LONG_WAIT = Scenario(
    id="live/a-long-think-is-covered",
    stage="3",
    because="2026-09-20: 'it took like 20 seconds for you to answer... you could say immediately, let me check'",
    beats=(
        Beat(who="Mara", says="Sim, are you there?", ask_directly=True,
             expect=(answered(), first_audio_under(2.5))),
        Beat(who="Mara", says="Sim, what is the capital of a country I have never mentioned?",
             ask_directly=True, expect=(answered(), first_audio_under(8.0))),
    ),
)

#: Told a fact, corrected it, asked about it in other words. The recall
#: failure stage 5 was built for: the superseded value used to win.
A_CORRECTION = Scenario(
    id="live/a-correction-wins",
    stage="5",
    because="the birthday correction: March 4th, then March 6th, then asked -- the old value came back",
    beats=(
        Beat(who="Mara", says="Sim, my birthday is March 4th.", ask_directly=True),
        Beat(who="Mara", says="Actually I got that wrong, my birthday is March 6th.", ask_directly=True),
        Beat(who="Mara", says="Sim, remind me what date we said for the party?", ask_directly=True,
             expect=(answered(), remembered("March 6"))),
    ),
)

#: A camera at 02:00 with the house asleep. It must reach the owner's
#: phone and not the speaker -- and `notify` must actually work, which
#: it had not since stage 6 (fixed 2ad9dd2).
A_CAMERA_AT_NIGHT = Scenario(
    id="live/a-camera-at-night",
    stage="6",
    because="2026-09-20: every camera notification was denied -- notify takes `body`, Initiative sent `text`",
    beats=(
        Beat(device={"key": "camera.backyard", "kind": "camera", "kinds": ["person"], "channel": 3},
             expect=(did_not_call("speak"),)),
    ),
)

#: Six things said to Sim in a row, out loud, and every one must be
#: heard. This is the scenario that found the echo bar sitting at
#: infinity in a quiet room: before the fix it answered every other
#: beat, and an alternating deafness is exactly what "Sim doesn't
#: answer" looks like from a kitchen. Every beat goes through the
#: room, because the listening loop is the whole question.
A_WHOLE_CONVERSATION = Scenario(
    id="live/a-whole-conversation",
    stage="3",
    because="2026-09-20: in a quiet room Sim heard every other thing said to it, and nobody could see why",
    beats=tuple(
        Beat(who="Mara", says=says, expect=(answered(),))
        for says in (
            "Sim, what is on this evening?",
            "Sim, is the kitchen light on?",
            "Sim, what time is it?",
            "Sim, how long does rice take?",
            "Sim, is there anything I asked you to remember?",
            "Sim, are you still there?",
        )
    ),
)

SCENARIOS = (MISHEARD_NAME, NOT_FOR_SIM, A_LONG_WAIT, A_CORRECTION, A_CAMERA_AT_NIGHT,
             A_WHOLE_CONVERSATION)

__all__ = ["A_CAMERA_AT_NIGHT", "A_CORRECTION", "A_LONG_WAIT", "MISHEARD_NAME", "NOT_FOR_SIM", "SCENARIOS"]
