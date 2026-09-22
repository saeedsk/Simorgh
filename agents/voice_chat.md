+++
name = "chat"
extends = "chat"
tools = [
    "self_map", "read_file", "search_code", "web_search", "web_fetch", "start_task", "list_tasks", "cancel_task", "memory_forget", "memory_search",
    # The Mac's own Music app. "Play jazz on the Mac on Apple Music" by
    # voice got "I can't start Apple Music on your Mac from here" -- true
    # of this profile and of nothing else: the typed chat had these all
    # along (the creator, 2026-09-15).
    "music_now", "music_control", "music_play", "sim_command",
    # Its own console: the only place "was there an error just now?" can
    # be answered from (see agents/chat.md).
    "console_tail",
    "voice_setting", "cast_devices", "cast_show", "cast_play", "cast_stop", "cast_volume", "dash_view", "dash_key", "tv_app", "tv_key", "tv_charts",
    "cam_list", "cam_state", "cam_snapshot", "cam_stream", "cam_light", "cam_ir", "cam_siren", "cam_ptz", "cam_recordings", "cam_watch",
    "ring_list", "ring_snapshot", "ring_events", "ring_light", "ring_siren", "ring_watch",
    # The things people say OUT LOUD, which this list did not have.
    # "Remind me in 5 minutes" (the creator, 2026-09-16) found no
    # `remind` here, so the model reached for `start_task` -- the only
    # tool it had that could wait -- and the reminder sat behind `auto
    # off` instead of firing. `CHAT` has had all of these all along.
    # The same drift was found once before, for the Music tools, and
    # patched for those alone (2026-09-15, above); this is the rest.
    #
    # Answer-shaped only. `apply_source_patch`, `install_package`,
    # `run_script` and the sandboxes stay out on purpose: a six-step
    # spoken turn is answered, not built.
    "remind", "cal_list", "mail_search", "mail_read",
    "home_find", "home_state", "home_describe", "home_call", "home_undo",
    "energy_status", "energy_report",
    "media_now", "media_control", "media_play",
    "kb_search", "kb_ask", "kb_open",
    "git_history"
]
max_steps = 6
+++
<!--
A SPOKEN chat turn. The creator's screen, 2026-09-11: "you're not
responding" became a 25-step exploration -- self_map, search_code,
read_file, and finally `replace_in_file` on the live voice config --
while the person waited in silence. A spoken remark is answered from
what the model knows, quickly; a spoken REQUEST for work becomes a
task (`start_task`) that runs on its own and reports back. No tool
here writes a file, and four steps is room for one lookup, not a
dig.
--
Six: a search, a cast, a retry, and the answer (the creator,
2026-09-12: "cast something on TV" ran out at five, having listed
devices it did not need and hunted for an mp4 -- the rule now says
not to). Still short on purpose: a spoken turn is answered, not
investigated; a longer job is a task.
-->
