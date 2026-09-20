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

from .api import Decision, Proposal

#: Tools whose reach is not visible in their reversibility class.
#: Everything here is tier 3: it leaves the house, tells somebody, spends
#: money, or is loud in the night.
REACHES_OUTSIDE: frozenset[str] = frozenset({
    "notify",           # tells a person somewhere else, through a third party
    "run_remote",       # a command on another machine
    "mail_send",        # writes to somebody else, as the household
    "cam_siren", "ring_siren",          # loud, outside, at any hour
    "publish_page", "post_message",     # anything that puts words in public
})

#: Tier 2 by name: irreversible, but local and bounded -- the class the
#: ordinary irreversible path already handles well.
LOCAL_IRREVERSIBLE: frozenset[str] = frozenset({
    "git_commit", "worktree_land", "apply_source_patch", "apply_skill", "replace_in_file",
    "install_package", "run_shell", "run_script", "run_container", "git_revert", "git_discard",
})

TIER_NAMES = {0: "read", 1: "reversible", 2: "local irreversible", 3: "reaches outside"}


def tier_of(proposal: Proposal, info=None, *, network: bool | None = None) -> tuple[int, str]:
    """`(tier, why)` for one proposal."""
    tool = proposal.tool or ""
    if tool in REACHES_OUTSIDE:
        return 3, f"{tool} reaches outside the house"
    reversibility = getattr(info, "reversibility", None) or proposal.reversibility or "irreversible"
    if reversibility == "read_only":
        return 0, f"{tool} only reads"
    if reversibility == "reversible":
        return 1, f"{tool} can be undone"
    if network is True and tool not in LOCAL_IRREVERSIBLE:
        # An irreversible tool that talks to the network may be doing
        # either; say so rather than guessing it is local.
        return 3, f"{tool} is irreversible and uses the network"
    return 2, f"{tool} is irreversible, locally"


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


__all__ = ["CEILING", "LOCAL_IRREVERSIBLE", "PersonRule", "REACHES_OUTSIDE", "TIER_NAMES", "TierRule",
           "role_of", "tier_of"]
