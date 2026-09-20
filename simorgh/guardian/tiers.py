"""Safety tiers 0 to 3 (stage 6 item 5), and who may reach them.

Guardian already decided per rule: protected paths, scopes, denylists,
reversibility, the physical class. What it could not say, in one word, is
*how far* an action reaches -- and that is the question a person asks of
an assistant that lives in their house. A tier answers it:

    0  reads something                      allow, log
    1  changes something, reversibly        allow while guarded, deny when locked
    2  irreversible, local and bounded      the ordinary irreversible path
    3  reaches outside the house, or is     a person, in every posture
       physical-`human`, or costs money

The tier is computed from what the tool IS -- the registry's reversibility
(never the proposer's claim, evaluation S6), whether it touches the
network, and a small override table for the ones whose reach their class
does not show -- so a new tool is tiered by its own registration rather
than by being remembered here.

`PersonRule` is the other half. A house has children in it. The permission
matrix is deliberately small and refuses upward: an adult may do anything
the posture allows, a child may read and ask, a voice Sim cannot place may
only read. It is not a security boundary against a determined adult -- it
is what stops a nine-year-old unlocking the door by asking nicely, which
is the failure a household actually has.
"""

from __future__ import annotations

from simorgh.contracts.tiers import LOCAL_IRREVERSIBLE, REACHES_OUTSIDE, TIER_NAMES, tier_of  # noqa: F401

from .api import Decision, Proposal

#: What each role may reach, at most. A role absent here is `unknown`.
CEILING: dict[str, int] = {"owner": 3, "adult": 3, "child": 1, "guest": 1, "unknown": 0}


def role_of(person: str, *, channel: str = "") -> str:
    """The requester's role: owner, adult, child, guest or unknown.

    The typed console is the owner's: it is the machine's own keyboard,
    and treating it as a stranger would lock the creator out of his own
    system. Every other channel has to name somebody.
    """
    from simorgh.contracts.household import CHILD_AGE, member

    name = (person or "").strip()
    if not name:
        return "owner" if channel in ("", "cli") else "unknown"
    known = member(name)
    if known is None:
        return "guest"
    if known.age is not None and known.age < CHILD_AGE:
        return "child"
    return "owner" if known.relation == "Sim's creator" else "adult"


class PersonRule:
    """Who is asking, against what their role may reach (stage 6 item 5).

    Above the ceiling the answer depends on who they are: a child or a
    guest asking for something bigger is escalated to the owner (it may
    well be reasonable -- "turn the oven off" -- and a person can say yes),
    while a voice Sim cannot place is refused outright, because there is
    nobody to hold responsible for it.
    """

    name = "person"
    layer = "person"

    async def evaluate(self, proposal: Proposal, ctx) -> Decision:
        role = role_of(getattr(proposal, "requester", "") or "",
                       channel=getattr(proposal, "requester_channel", "") or "")
        tier, why = tier_of(proposal, getattr(ctx, "tool", None))
        if tier <= CEILING.get(role, 0):
            return Decision("abstain", self.layer)
        who = getattr(proposal, "requester", "") or "a voice I cannot place"
        if role == "unknown":
            return Decision("deny", self.layer,
                            (f"{who} is not someone I know, and this {why}",))
        return Decision("escalate", self.layer,
                        (f"{who} is a {role} here, and this {why}: an adult should say yes",))


#: How sure Sim must be that somebody is in the house before their
#: voice may approve a human-class action (stage 6 item 5).
PRESENT_ENOUGH = 0.8


class PresenceRule:
    """A voice may only approve what a present, recognised person said.

    The house's biggest hole is not a stranger typing at the console --
    it is a voice. A television, a phone on speaker, a recording, or a
    guest in the hallway can all say "yes, unlock the door", and until
    now the only question asked was whether the words sounded like
    approval.

    So for an action that needs a person (tier 3, or a human-class
    physical action), arriving by voice: the person Sim thinks is
    asking must be somewhere in the house with belief above
    `PRESENT_ENOUGH`, and the voice must have been speaker-verified
    rather than guessed. Otherwise the voice path is refused and the
    answer has to come the other way -- the phone, the console -- which
    is a channel somebody has to hold in their hand.

    Nothing to ask means not present. A World Model that does not answer
    is not evidence that the room is full, and the failure this rule
    exists to stop is exactly the one where nobody is there.
    """

    name = "presence"
    layer = "presence"

    async def evaluate(self, proposal: Proposal, ctx) -> Decision:
        if (getattr(proposal, "requester_channel", "") or "") != "voice":
            return Decision("abstain", self.layer)
        tier, why = tier_of(proposal, getattr(ctx, "tool", None))
        if tier < 3:
            return Decision("abstain", self.layer)
        who = (getattr(proposal, "requester", "") or "").strip()
        if not who:
            return Decision("deny", self.layer,
                            (f"a voice I cannot place asked for this, and it {why}",))
        ask = getattr(ctx, "presence", None)
        belief, verified = (0.0, False)
        if ask is not None:
            try:
                belief, verified = await ask(who)
            except Exception:  # noqa: BLE001 -- no answer is not a yes
                belief, verified = (0.0, False)
        if belief >= PRESENT_ENOUGH and verified:
            return Decision("abstain", self.layer)
        unsure = ("I am not sure that was really you" if not verified
                  else f"I cannot tell that {who} is here")
        return Decision("deny", self.layer,
                        (f"{unsure}, and this {why}: say yes from your phone instead",))


class TierRule:
    """Tier 3 needs a person, in every posture (stage 6 item 5).

    `PhysicalRule` already does this for the house; this is the rest of
    the reach -- a message to somebody else, a command on another machine,
    money. `locked` denies it, as it denies everything that changes.
    """

    name = "tier"
    layer = "tier"

    async def evaluate(self, proposal: Proposal, ctx) -> Decision:
        tier, why = tier_of(proposal, getattr(ctx, "tool", None))
        if tier < 3:
            return Decision("abstain", self.layer)
        if ctx.posture.level == "locked" or ctx.config.mode == "locked":
            return Decision("deny", self.layer, (f"locked: {why}",))
        return Decision("escalate", self.layer, (f"tier 3 needs a person: {why}",))


__all__ = ["CEILING", "LOCAL_IRREVERSIBLE", "PRESENT_ENOUGH", "PersonRule", "PresenceRule", "REACHES_OUTSIDE",
           "TIER_NAMES", "TierRule", "role_of", "tier_of"]
