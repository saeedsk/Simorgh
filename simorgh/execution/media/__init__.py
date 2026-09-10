"""Domain 5: media (`docs/plans/domains/05-media.md`).

What is playing where, and running it. Step 1 of the build order: the
player table from `home`, plus `media_now`, `media_play` and
`media_control`.

Jellyfin, Music Assistant and the library half are later steps. They
are worth building on top of this rather than instead of it: every one
of them ends up calling a `media_player` service through Home Assistant
anyway, so the control surface is the same and only the resolution of
"the jazz playlist" into something playable changes.

The two safety rules from section 5 are enforced here rather than left
to Guardian, because they are about volume and time of day and both are
knowable at the tool edge: nothing goes above
`media_max_volume_unattended` without a person, and nothing goes above
`media_quiet_hours_max_volume` during quiet hours at all. An Echo at
full volume at 3am is not a policy question.
"""

from .tools import media_tools

__all__ = ["media_tools"]
