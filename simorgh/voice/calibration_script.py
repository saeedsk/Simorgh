"""The lines `voice calibrate` asks a person to read, once.

Written for THIS household (the creator, 2026-09-22: "an option which
later you can re-use to calibrate the system, similar to voice enrolling.
I don't want to repeat this again if you find a bug"). So the set holds
what Sim actually hears here: the family's names in ordinary sentences
(Soodeh, Aran, Ira, Iris -- Whisper wrote Ira as "Aira" once), the
commands this house uses (charts and cameras on the TV, lights,
reminders for a named child, timers, weather, music), numbers, times
and dates, one-word commands and long questions, "Sim" at the start, in
the middle, at the end and absent (the name detector), and a few lines
with a natural pause in them (the endpointer). English and Farsi,
because this house speaks both (`[voice] stt_languages = "en,fa"`).

THE RULES FOR EDITING THIS FILE -- the recordings outlive it:

  * A line's `id` is forever. Never reuse an id for different words and
    never change the words under an existing id: a take on disk is
    matched to its line by id, and the manifest keeps the text it was
    read from (`script_text`) so a changed line is asked again rather
    than silently mislabelled.
  * Add lines with NEW ids and bump `SCRIPT_VERSION`. A resumed session
    then asks only for the new ones.
  * Farsi is written in Persian script (ی and ک, not the Arabic ي and ك;
    a zero-width non-joiner where Persian wants one) with a romanisation
    beside it for anyone who reads the manifest and not the script.
  * No placeholders. Every line is something a person here would say.

`short=True` marks the short set (about a fifth of the lines) for the
rest of the family to read later (`voice calibrate <name> short`).
`note` is shown under the line: how to read it, never part of the
reference text.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Bump when lines are ADDED. Existing ids never change meaning.
SCRIPT_VERSION = 1


@dataclass(frozen=True)
class Line:
    id: str
    language: str            # "en" | "fa"
    text: str                # what to read, and the WER reference
    romanisation: str = ""   # Farsi only
    tags: tuple[str, ...] = ()
    short: bool = False      # part of the short set
    note: str = ""           # how to read it; shown, never scored

    @property
    def language_name(self) -> str:
        return LANGUAGE_NAMES.get(self.language, self.language)


LANGUAGE_NAMES = {"en": "English", "fa": "Farsi"}

_PAUSE = "pause for a breath at the dots -- well under a second, or it becomes two turns"

ENGLISH: tuple[Line, ...] = (
    # -- the family, by name
    Line("en-001", "en", "Sim, remind Aran at six to take out the recycling.", tags=("names", "reminder", "sim-start", "time"), short=True),
    Line("en-002", "en", "Remind Soodeh tomorrow at nine thirty about the dentist.", tags=("names", "reminder", "time", "sim-absent")),
    Line("en-003", "en", "Sim, is Ira's swimming lesson on Thursday or Friday?", tags=("names", "calendar", "sim-start"), short=True),
    Line("en-004", "en", "Iris wants to know how many days are left until her birthday.", tags=("names", "numbers", "sim-absent")),
    Line("en-005", "en", "Tell Ira and Iris that dinner is ready in ten minutes.", tags=("names", "numbers", "sim-absent")),
    Line("en-006", "en", "Sim, what did Aran ask you this morning?", tags=("names", "question", "sim-start")),
    Line("en-007", "en", "Soodeh and I are going out tonight, and the girls are staying home with Aran.",
         tags=("names", "long", "sim-absent")),
    Line("en-008", "en", "Can you read Iris a short story before bed?", tags=("names", "question", "sim-absent"), short=True),
    # -- the TV
    Line("en-009", "en", "Sim, put the charts on the TV.", tags=("tv", "command", "sim-start"), short=True),
    Line("en-010", "en", "Put the cameras on the TV.", tags=("tv", "cameras", "command", "sim-absent")),
    Line("en-011", "en", "Sim, put the Bitcoin chart on the TV for the last week.", tags=("tv", "charts", "sim-start")),
    Line("en-012", "en", "Turn the TV off.", tags=("tv", "command", "short-command", "sim-absent")),
    Line("en-013", "en", "Put a cartoon on the TV for the girls.", tags=("tv", "command", "sim-absent")),
    # -- music
    Line("en-014", "en", "Play some quiet piano music in the family room.", tags=("music", "command", "sim-absent"), short=True),
    Line("en-015", "en", "Sim, pause the music.", tags=("music", "command", "sim-start")),
    Line("en-016", "en", "Turn the volume down a little.", tags=("music", "command", "sim-absent")),
    Line("en-017", "en", "Next song.", tags=("music", "short-command", "sim-absent")),
    Line("en-018", "en", "Louder, please.", tags=("music", "short-command", "sim-absent")),
    # -- cameras
    Line("en-019", "en", "Show me the front door camera.", tags=("cameras", "command", "sim-absent"), short=True),
    Line("en-020", "en", "Sim, who came to the front door this afternoon?", tags=("cameras", "question", "sim-start")),
    Line("en-021", "en", "Is anyone in the backyard right now?", tags=("cameras", "question", "sim-absent")),
    # -- lights
    Line("en-022", "en", "Turn off the kitchen lights.", tags=("lights", "command", "sim-absent"), short=True),
    Line("en-023", "en", "Sim, dim the family room lights to thirty percent.", tags=("lights", "numbers", "sim-start")),
    Line("en-024", "en", "Turn on the porch light at sunset.", tags=("lights", "command", "sim-absent")),
    # -- timers and reminders
    Line("en-025", "en", "Set a timer for twelve minutes.", tags=("timer", "numbers", "sim-absent"), short=True),
    Line("en-026", "en", "Sim, how much time is left on the timer?", tags=("timer", "question", "sim-start")),
    Line("en-027", "en", "Remind me on Monday the fourteenth at eight fifteen to call the bank.",
         tags=("reminder", "date", "time", "sim-absent")),
    Line("en-028", "en", "Cancel the reminder about the dentist.", tags=("reminder", "command", "sim-absent")),
    # -- weather
    Line("en-029", "en", "What's the weather like tomorrow morning?", tags=("weather", "question", "sim-absent"), short=True),
    Line("en-030", "en", "Sim, will it rain on Saturday?", tags=("weather", "question", "sim-start")),
    Line("en-031", "en", "How cold will it be tonight, in Celsius?", tags=("weather", "numbers", "sim-absent")),
    # -- numbers, times, dates
    Line("en-032", "en", "What is twenty-seven times forty-three?", tags=("numbers", "question", "sim-absent")),
    Line("en-033", "en", "The code is four eight one five, then press enter.", tags=("numbers", "digits", "sim-absent")),
    Line("en-034", "en", "Sim, what's the date three weeks from today?", tags=("date", "question", "sim-start")),
    Line("en-035", "en", "The meeting moved from two thirty to a quarter past four.", tags=("time", "sim-absent")),
    Line("en-036", "en", "We need three hundred and fifty grams of flour and two eggs.", tags=("numbers", "sim-absent")),
    Line("en-037", "en", "What year did the first iPhone come out?", tags=("numbers", "question", "sim-absent")),
    # -- short answers and thanks
    Line("en-038", "en", "Sim, thank you.", tags=("short-command", "sim-start")),
    Line("en-039", "en", "Yes, please.", tags=("short-command", "sim-absent"), short=True),
    Line("en-040", "en", "No, not that one.", tags=("short-command", "sim-absent")),
    # -- where the name falls
    Line("en-041", "en", "What's on my calendar tomorrow, Sim?", tags=("calendar", "sim-end"), short=True),
    Line("en-042", "en", "I think, Sim, that we should leave at seven.", tags=("sim-middle", "time")),
    Line("en-043", "en", "Can you check whether the garage door is closed?", tags=("question", "sim-absent")),
    Line("en-044", "en", "Hey Sim, good morning.", tags=("greeting", "sim-start")),
    Line("en-045", "en", "The kids call you Sim, but your full name is Simorgh.", tags=("sim-middle", "names")),
    # -- long questions
    Line("en-046", "en", "Sim, can you explain why the sky turns orange at sunset, in a way a nine-year-old would understand?",
         tags=("long", "question", "sim-start")),
    Line("en-047", "en", "What should we cook for dinner if we have rice, chicken, and a few tomatoes?",
         tags=("long", "question", "sim-absent")),
    Line("en-048", "en", "How long would it take to drive to Lake Tahoe if we leave at eight on Saturday morning?",
         tags=("long", "question", "time", "sim-absent")),
    # -- a natural pause inside the turn
    Line("en-049", "en", "Sim... what's the plan for tomorrow?", tags=("pause", "sim-start"), note=_PAUSE, short=True),
    Line("en-050", "en", "Put the charts on the TV... no, the cameras.", tags=("pause", "tv", "cameras"), note=_PAUSE),
    Line("en-051", "en", "Remind Aran... at six... to finish his homework.", tags=("pause", "names", "reminder"), note=_PAUSE),
)

FARSI: tuple[Line, ...] = (
    Line("fa-001", "fa", "سیم، ساعت چنده؟", "Sim, sā'at chande?", tags=("question", "sim-start", "time"), short=True),
    Line("fa-002", "fa", "سیم، هوای فردا چطوره؟", "Sim, havā-ye fardā chetore?", tags=("weather", "sim-start")),
    Line("fa-003", "fa", "چارت‌ها رو بذار روی تلویزیون.", "chārt-hā ro bezār ru-ye televiziun.", tags=("tv", "charts", "sim-absent"), short=True),
    Line("fa-004", "fa", "دوربین‌ها رو نشون بده.", "durbin-hā ro neshun bede.", tags=("cameras", "sim-absent")),
    Line("fa-005", "fa", "چراغ‌های آشپزخونه رو خاموش کن.", "cherāgh-hā-ye āshpazkhune ro khāmush kon.", tags=("lights", "sim-absent")),
    Line("fa-006", "fa", "ساعت شش به آران یادآوری کن.", "sā'at-e shish be Ārān yādāvari kon.", tags=("names", "reminder", "time"), short=True),
    Line("fa-007", "fa", "به سوده بگو شام آماده‌ست.", "be Sudeh begu shām āmāde-st.", tags=("names", "sim-absent")),
    Line("fa-008", "fa", "آیرا و آیریس کجان؟", "Āyrā va Āyris kojān?", tags=("names", "question", "sim-absent")),
    Line("fa-009", "fa", "یه تایمر ده دقیقه‌ای بذار.", "ye tāymer-e dah daqiqe-i bezār.", tags=("timer", "numbers"), short=True),
    Line("fa-010", "fa", "یه آهنگ آروم بذار.", "ye āhang-e ārum bezār.", tags=("music", "sim-absent")),
    Line("fa-011", "fa", "صدای تلویزیون رو کم کن.", "sedā-ye televiziun ro kam kon.", tags=("tv", "music", "sim-absent")),
    Line("fa-012", "fa", "فردا ساعت هفت و نیم صبح بیدارم کن.", "fardā sā'at-e haft o nim-e sobh bidāram kon.", tags=("time", "reminder")),
    Line("fa-013", "fa", "امروز چندمه؟", "emruz chandome?", tags=("date", "question", "short-command")),
    Line("fa-014", "fa", "سیم، ممنون، خیلی کمکم کردی.", "Sim, mamnun, kheyli komakam kardi.", tags=("sim-start",)),
    Line("fa-015", "fa", "بیست و پنج به علاوه‌ی هفده چند میشه؟", "bist o panj be alāve-ye hefdah chand mishe?", tags=("numbers", "question")),
    Line("fa-016", "fa", "فکر کنم، سیم، باید زودتر راه بیفتیم.", "fekr konam, Sim, bāyad zudtar rāh biyoftim.", tags=("sim-middle",)),
)

LINES: tuple[Line, ...] = ENGLISH + FARSI


def lines(*, language: str = "", short: bool = False) -> list[Line]:
    """The script in reading order, optionally one language or the short set."""
    return [line for line in LINES
            if (not language or line.language == language) and (not short or line.short)]


def by_id(line_id: str) -> Line | None:
    return next((line for line in LINES if line.id == line_id), None)


__all__ = ["ENGLISH", "FARSI", "LANGUAGE_NAMES", "LINES", "Line", "SCRIPT_VERSION", "by_id", "lines"]
