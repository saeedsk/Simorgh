"""How far an action reaches: tiers 0 to 3 (stage 6 item 5).

    0  reads something                      allow, log
    1  changes something, reversibly        allow while guarded, deny when locked
    2  irreversible, local and bounded      the ordinary irreversible path
    3  reaches outside the house, or is     a person, in every posture
       physical-`human`, or costs money

The tier is computed from what the tool IS -- the registry's
reversibility (never the proposer's claim, evaluation S6), whether it
touches the network, and a small override table for the ones whose reach
their class does not show.

It lives in `contracts` because two subsystems need the same answer and
may not import each other: Guardian decides with it (`guardian/tiers.py`),
and Orchestration checkpoints an action that reached tier 2 or more so a
crash-resume never repeats it (stage 7 item 7).
"""

from __future__ import annotations


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

#: Tier 3 by name for a different reason than reach: these change who
#: Sim trusts (stage 6 item 4). Linking a handle to a name decides whose
#: memories that handle reads and what its role may ask for, and an
#: identity nobody confirmed is an identity claimed by whoever says the
#: right sentence. Reversible, and still a person's call.
CHANGES_WHO_SIM_TRUSTS: frozenset[str] = frozenset({"people"})

#: Calls that only make the house quieter: the tool, the argument that
#: says what it does, and the values that stop, pause or mute. Tier 0,
#: so anyone may -- a voice too short to recognise, a guest, a child.
#: Live, 2026-09-27: "Stop the music." at the satellite was 0.66 s of
#: speech, too short to place, and Guardian refused it as "a voice I
#: cannot place"; the music played on. Starting, resuming or turning it up
#: stays where the tool's class puts it.
QUIETS: dict[str, tuple[str, frozenset[str]]] = {
    "media_control": ("op", frozenset({"stop", "pause", "mute"})),
    "music_control": ("op", frozenset({"stop", "pause", "mute"})),
    "room_play": ("what", frozenset({"stop", "pause"})),
}
#: Whole tools that only ever stop something playing.
ONLY_STOPS: frozenset[str] = frozenset({"cast_stop"})

TIER_NAMES = {0: "read", 1: "reversible", 2: "local irreversible", 3: "reaches outside"}


def tier_of(proposal: Proposal, info=None, *, network: bool | None = None) -> tuple[int, str]:
    """`(tier, why)` for one proposal."""
    tool = proposal.tool or ""
    if tool in REACHES_OUTSIDE:
        return 3, f"{tool} reaches outside the house"
    if tool in CHANGES_WHO_SIM_TRUSTS:
        return 3, f"{tool} changes who I trust"
    if tool in ONLY_STOPS:
        return 0, f"{tool} only makes it quieter"
    quiet = QUIETS.get(tool)
    if quiet is not None:
        key, values = quiet
        said = str((getattr(proposal, "args", None) or {}).get(key) or "").strip().lower()
        if said in values:
            return 0, f"{tool} {said} only makes it quieter"
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



__all__ = ["CHANGES_WHO_SIM_TRUSTS", "LOCAL_IRREVERSIBLE", "ONLY_STOPS", "QUIETS", "REACHES_OUTSIDE", "TIER_NAMES",
           "tier_of"]
