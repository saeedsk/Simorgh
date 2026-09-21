"""Choosing an answer to an approval, with the arrow keys.

The creator, 2026-09-20: when Sim needs approval, the question and its
options belong in the prompt section -- the boxed area just above the
input line -- as bullets you move through with the arrows, mark with
space, and send with Enter; and then a second question in the same
place showing what you picked, so Enter twice is never an accident.

Why a state machine with no terminal in it: everything interesting
here is the order things happen in -- what is selected, what Enter
means right now, what happens when you change your mind -- and none
of that needs prompt_toolkit to be true. `tui.py` draws `rows()` and
feeds it keys; this decides. The TUI layer stays thin enough that
its absence (a pipe, a test, a detached session) costs only the
drawing.

An approval is not a menu. Two rules follow from that and both are
tested:

  * Nothing is preselected. A picker that opens on "yes" turns a
    stray Enter into an approval, and the whole reason this exists is
    that typing "yes" at the old prompt was too easy to get wrong.
  * The confirm step shows the ANSWER, not the position. "Submit
    'yes'?" is checkable; "Submit option 1?" is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: The escape hatch, always last. An approval whose only answers are
#: the ones Guardian thought of is how a person ends up approving
#: something they half-agree with.
SOMETHING_ELSE = "something else…"

CHOOSING = "choosing"
CONFIRMING = "confirming"
TYPING = "typing"      # "something else" was chosen: the input line takes it
DONE = "done"

SUBMIT = "submit"
REDO = "go back"


@dataclass
class Picker:
    """One approval, from asked to answered."""

    question: str
    options: tuple[str, ...]
    prompt_id: str = ""
    stage: str = CHOOSING
    cursor: int = 0
    #: What space marked. None until the person marks something --
    #: never a default, so Enter on an untouched picker asks rather
    #: than approves.
    chosen: str | None = None
    answer: str = ""
    _confirm: tuple[str, ...] = field(default=(SUBMIT, REDO), init=False)

    @classmethod
    def for_prompt(cls, payload: dict) -> "Picker":
        given = [str(o) for o in (payload.get("options") or []) if str(o).strip()]
        if not given:
            given = ["yes", "no"]
        return cls(question=str(payload.get("question") or "").strip(),
                   options=(*given, SOMETHING_ELSE),
                   prompt_id=str(payload.get("prompt_id") or ""))

    # -- what is on screen now ---------------------------------------------------------
    @property
    def rows(self) -> tuple[str, ...]:
        return self._confirm if self.stage == CONFIRMING else self.options

    @property
    def heading(self) -> str:
        if self.stage == CONFIRMING:
            return f"Submit {self.chosen!r}?"
        if self.stage == TYPING:
            return "Type your answer and press Enter:"
        return self.question

    def lines(self) -> list[tuple[str, bool, bool]]:
        """`(text, is_under_the_cursor, is_marked)` per bullet."""
        marked = self.chosen if self.stage == CHOOSING else None
        return [(row, i == self.cursor, row == marked) for i, row in enumerate(self.rows)]

    def render(self, *, bullet: str = "•", cursor: str = "❯", mark: str = "◉", blank: str = "○") -> str:
        """Plain text, for a terminal that cannot do better and for
        tests that would rather read one string."""
        out = [self.heading]
        if self.stage == TYPING:
            return "\n".join(out)
        for text, under, is_marked in self.lines():
            out.append(f" {cursor if under else ' '} {mark if is_marked else blank} {bullet} {text}")
        return "\n".join(out)

    # -- keys --------------------------------------------------------------------------
    def move(self, delta: int) -> None:
        """Up or down, and it stops at the ends rather than wrapping.

        Wrapping is right for a menu you are browsing and wrong for a
        list you are deciding from: the last thing you want, pressing
        down once too often on "no", is to arrive back at "yes".
        """
        if self.stage in (TYPING, DONE):
            return
        self.cursor = max(0, min(len(self.rows) - 1, self.cursor + delta))

    def space(self) -> None:
        """Mark what the cursor is on. Marking again unmarks it."""
        if self.stage != CHOOSING:
            return
        here = self.rows[self.cursor]
        self.chosen = None if self.chosen == here else here

    def enter(self) -> str:
        """Advance. Returns the new stage.

        On the choosing step with nothing marked, Enter takes what the
        cursor is on -- moving to a line and pressing Enter is what
        everybody does, and refusing it would be pedantry. It is still
        not the same as a default: the cursor starts on the first
        option and Enter there is a deliberate keypress on a specific
        line, where a preselected "yes" is a keypress on nothing.
        """
        if self.stage == CHOOSING:
            self.chosen = self.chosen or self.rows[self.cursor]
            if self.chosen == SOMETHING_ELSE:
                self.stage = TYPING
                return self.stage
            self.stage, self.cursor = CONFIRMING, 0
            return self.stage
        if self.stage == CONFIRMING:
            if self.rows[self.cursor] == SUBMIT:
                self.answer, self.stage = str(self.chosen or ""), DONE
            else:
                self.stage, self.cursor, self.chosen = CHOOSING, 0, None
            return self.stage
        return self.stage

    def typed(self, text: str) -> str:
        """The free-text answer for "something else". Empty text is a
        change of mind, not an answer."""
        if self.stage != TYPING:
            return self.stage
        text = " ".join(str(text or "").split())
        if not text:
            self.stage, self.cursor, self.chosen = CHOOSING, 0, None
            return self.stage
        self.chosen, self.stage, self.cursor = text, CONFIRMING, 0
        return self.stage

    def escape(self) -> None:
        """Back out one step; from the first step, back to nothing
        marked. Never answers, and never closes the picker: an
        approval that can be dismissed by a stray key is an approval
        that times out to its default without anybody deciding."""
        if self.stage == CONFIRMING:
            self.stage, self.cursor, self.chosen = CHOOSING, 0, None
        elif self.stage == TYPING:
            self.stage, self.chosen = CHOOSING, None
        else:
            self.chosen = None

    @property
    def done(self) -> bool:
        return self.stage == DONE


__all__ = ["CHOOSING", "CONFIRMING", "DONE", "Picker", "REDO", "SOMETHING_ELSE", "SUBMIT", "TYPING"]
