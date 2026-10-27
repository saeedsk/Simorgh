"""Whose core memory block a `memory_core_edit` may touch (stage 15 item 8).

A core block is a note Sim reads before every chat turn -- "Soodeh: prefers
Farsi" -- so writing one is writing what Sim believes about a person every
time they speak. The plan's rule, checked here against the proposal's own
requester rather than anything the model wrote:

- a person's block only on behalf of that same person;
- the `household` block by anyone in the household (owner, adult, child);
- nothing for a voice Sim cannot place, for nobody at all (Sim's own idea,
  a plan node), or from an outside channel (`a2a`).

The tool checks the same again before it sends (execution/tools.py
`_core_edit_refusal`) and Memory a third time before it writes; this is
the one that says no with a reason before anything runs.
"""

from __future__ import annotations

from simorgh.contracts.coreblocks import CORE_EDIT_TOOL, block_for, is_household, is_outside, is_unplaced

from .api import Decision, Proposal
from .tiers import role_of

#: Roles that make somebody one of the household, for its block.
HOUSEHOLD_ROLES = frozenset({"owner", "adult", "child"})


def _owner() -> str:
    """The owner's name from the household file: whose block "me" on the
    console is. "" when nobody is marked the creator."""
    from simorgh.contracts.household import HOUSEHOLD

    for member in HOUSEHOLD:
        if member.relation == "Sim's creator":
            return member.name
    return ""


class CoreMemoryRule:
    """`memory_core_edit`'s `block` against who asked (stage 15 item 8).

    Abstains on every other tool, and on an edit the requester may make --
    the rules after it still decide (it is reversible, so ordinarily it is
    allowed). Denies, never escalates: the answer to "may Ira rewrite
    Soodeh's notes" is not a question for a parent, it is that the note is
    Soodeh's."""

    name = "core_memory"
    layer = "core_memory"

    async def evaluate(self, proposal: Proposal, ctx) -> Decision:
        if proposal.tool != CORE_EDIT_TOOL:
            return Decision("abstain", self.layer)
        channel = getattr(proposal, "requester_channel", "") or ""
        if is_outside(channel):
            return Decision("deny", self.layer,
                            (f"core memory is not edited from outside the house ({channel})",))
        requester = (getattr(proposal, "requester", "") or "").strip()
        if requester and is_unplaced(requester):
            return Decision("deny", self.layer, ("a voice I cannot place may not edit core memory",))
        stored = None
        if requester and getattr(ctx, "role", None) is not None:
            # The People store first, as `PersonRule` reads it.
            try:
                stored = await ctx.role(requester)
            except Exception:  # noqa: BLE001 -- no answer falls back to the household file
                stored = None
        role = stored or role_of(requester, channel=channel)
        if role in ("unknown", "sim"):
            who = "my own idea" if role == "sim" else "nobody I can place"
            return Decision("deny", self.layer, (f"{who}: no core block is theirs to edit",))
        asked = str((proposal.args or {}).get("block") or "")
        if is_household(asked):
            if role in HOUSEHOLD_ROLES:
                return Decision("abstain", self.layer)
            return Decision("deny", self.layer,
                            (f"{requester or 'whoever asked'} is not one of the household, "
                             "so the household's block is not theirs to edit",))
        # The console names nobody: it is the owner's, so their block.
        person = requester or _owner()
        if not person:
            # The console with no owner on file: only "me" can be known to be
            # theirs, and Memory resolves that against its People registry.
            if block_for(asked, "owner"):
                return Decision("abstain", self.layer)
            return Decision("deny", self.layer, (f"{asked!r} is not the console's own block",))
        if block_for(asked, person):
            return Decision("abstain", self.layer)
        return Decision("deny", self.layer,
                        (f"{asked!r} is not {person}'s to edit: a person edits only their own core block "
                         "or the household's",))


__all__ = ["CoreMemoryRule", "HOUSEHOLD_ROLES"]
