"""`world.*` -- the environment model's query/observation surface
(section 4.10). World Model reads the repository and git state directly
as observation; it never writes."""

from __future__ import annotations

from ..fields import Enum, F, Float, O, Obj, Str
from ..registry import define
from .. import topics as t

WorldEnvQuery = define(t.WORLD_ENV_QUERY, [
    F("what", Enum("capability_map", "file_index", "tools", "user_profile", "git_state")),
    O("args", Obj()),
], doc="file_index accepts args {path, max_chars} for a bounded content preview.")
WorldEnvQueryReply = define(t.WORLD_ENV_QUERY_REPLY, [
    F("facet", Str),
    F("as_of", Float),
], doc="Open: the facet's own fields follow (additionalProperties true).")
WorldEnvObserved = define(t.WORLD_ENV_OBSERVED, [
    F("facet", Str),
    F("summary", Str),
    F("ref", Str),
])
