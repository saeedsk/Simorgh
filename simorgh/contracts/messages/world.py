"""`world.*` -- the environment model's query/observation surface
(section 4.10). World Model reads the repository and git state directly
as observation; it never writes."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, List, O, Obj, Str
from ..registry import define
from .. import topics as t

WorldEnvQuery = define(t.WORLD_ENV_QUERY, [
    # `home`: what the house is doing and who is in it (stage 6 item 3).
    F("what", Enum("capability_map", "file_index", "tools", "user_profile", "git_state", "home", "people")),
    O("args", Obj()),
], doc="file_index accepts args {path, max_chars} for a bounded content preview.")
WorldEnvQueryReply = define(t.WORLD_ENV_QUERY_REPLY, [
    F("facet", Str),
    F("as_of", Float),
], doc="Open: the facet's own fields follow (additionalProperties true).")
WorldPeopleUpdate = define(t.WORLD_PEOPLE_UPDATE, [
    # grant/revoke and add_interest/remove_interest: what a person said yes
    # to and what they care about (stage 10). The same write, the same
    # tier: consent is never inferred from a turn.
    F("action", Enum("link", "unlink", "set_role", "grant", "revoke", "add_interest", "remove_interest")),
    O("name", Str),        # the household name; required for everything but unlink
    O("identity", Str),    # "telegram:irak", "whatsapp:1555...", "voice:ira"
    O("role", Str),        # owner | adult | child | guest | unknown
    O("permission", Str),  # of contracts.people.PERMISSIONS; for grant and revoke
    O("interest", Str),    # a short topic; for add_interest and remove_interest
], doc="Change who a person is as far as Sim is concerned (stage 6 item 4), what they said yes to and "
       "what they care about (stage 10). A write: tier 3 on the way in, so a person confirms it.")
WorldPeopleUpdateReply = define(t.WORLD_PEOPLE_UPDATE_REPLY, [
    # `ok`/`error` are admitted on every reply by the registry.
    O("person", Obj()),
    O("detail", Str),
])
WorldEnvObserved = define(t.WORLD_ENV_OBSERVED, [
    F("facet", Str),
    F("summary", Str),
    F("ref", Str),
])
WorldHomeSituationChanged = define(t.WORLD_HOME_SITUATION_CHANGED, [
    F("fact", Str), F("value", Bool), O("people", Obj()), O("since", Float),
], doc="One situation fact of world:home changed value: quiet_hours, tv_playing, someone_asleep, "
       "child_alone, nobody_home. An open session is told, so it can act on the house it is in.")
CameraEvent = define(t.CAMERA_EVENT, [F("channel", Int), F("camera", Str), F("kinds", List(Str)), O("host", Str)],
                     doc="kinds: motion, person, vehicle, pet, face, package -- whatever the NVR reported.")
