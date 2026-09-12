"""Per-kind Profiles (16 section 5). v1 kept its own per-agent step
ceilings (`DEFAULT_MAX_TOOL_STEPS` in `self_patch.py`/`research_task.py`);
these are the same numbers, generalized to one table.
"""

from __future__ import annotations

from dataclasses import replace

from .api import Profile

CHAT = Profile(
    name="chat",
    # `self_map` first: a self-knowledge question ("where does your code
    # live", "what subsystems make you up") has a direct, correct answer
    # through it (world.env.query's capability_map facet) -- without it
    # the model fell back to list_dir and could wander into src/, the
    # retired v1 tree left readable for reference (observer, 2026-09-08).
    tools=("self_map", "read_file", "list_dir", "search_code", "web_search", "web_fetch",
           "render_page", "search_listings", "geocode", "run_python_sandboxed", "run_js_sandboxed",
           # "what does my policy say about flood cover" is the
           # archetypal chat question, and answering it from the web is
           # the archetypal wrong answer. Read-only and entirely local.
           "kb_search", "kb_ask", "kb_open",
           # "what's on today", "did the plumber reply", "remind me at
           # 8" -- all chat questions, and all unanswerable from the web.
           "cal_list", "mail_search", "mail_read", "remind",
           # "am I exposed?" is a question a person asks in chat.
           "sec_posture", "sec_findings", "sec_show",
           # "turn the kitchen light off" is the most ordinary chat
           # request there is.
           "home_find", "home_state", "home_describe", "home_call", "home_undo",
           # "what's it costing me" and "pause the telly" are the same
           # kind of question as "turn the light off".
           "energy_status", "energy_report", "media_now", "media_control", "media_play",
           "music_now", "music_control", "music_play",
           # Chat could turn the kitchen light on and read the mail, and
           # could not save a text file. Asked for a PowerPoint deck,
           # Sim correctly reported that it had no way to write one and
           # handed back a script to paste and run -- honest, and a
           # hopeless answer to "make me a deck" (creator, 2026-09-09:
           # "I expect sim to have write access to its workspace
           # directory ... and perform the requested file creation ...
           # including installing necessary packages by itself").
           #
           # `apply_source_patch` writes, and `workspace/` is in its
           # write scopes; `install_package` and `run_script` are how a
           # library that does the job gets used rather than described.
           # Guardian still sees every one of them, and the package
           # tool keeps its own daily cap.
           "apply_source_patch", "replace_in_file", "install_package", "run_script",
           # The escape hatch from a one-shot reply into work that
           # resumes. Chat only: a task that starts tasks is a fork
           # bomb, and the tool refuses from inside one anyway.
           "start_task",
           "propose_mcp_server",
           # The TV (execution/media/cast.py): "put yourself on the TV",
           # "play this on the TV" are chat requests too.
           "cast_devices", "cast_show", "cast_play", "cast_stop", "cast_volume"),
    # 6 was right for a profile that could only read. Writing a file
    # costs a step, installing what it needs costs another, running it a
    # third, and checking the result a fourth -- before a single wrong
    # turn, and with the last step spent on the forced final answer.
    # 12 was still not enough for "build me a game": three attempts in a
    # row ended with work pending. Matched to the patch profile, which
    # is what a chat turn now IS once it can write, install and run.
    read_only=False, max_steps=20, max_revisions=0, scaffold="chat", verify=False,
    # 2000 was a reply budget, from when chat could only talk. The
    # moment it could also WRITE FILES that number became a content
    # shredder: a 150-line document is well over 2000 tokens, so every
    # `apply_source_patch` truncated part-way and the file came out
    # shorter than it went in. Live-caught 2026-09-09 rebuilding a voxel
    # game -- 147 lines became 131, then 129, then 76, then 54, each
    # write a sincere attempt at the whole file that ran out of room.
    # Matched to the patch profile, which writes files for a living.
    max_output_tokens=16_000,
)
# The creator, 2026-09-07: "gives sim more freedom in autonomously
# working and evolving without too much gate". Until then the patch/
# skill profiles could only `draft_candidate` -- and the draft->verify->
# apply loop that was supposed to land a draft was never built, so Sim
# literally could not change its own code. The model may now apply and
# commit directly; Guardian still sees every call (ProtectedRule keeps
# guardian/kernel/contracts/execution/SOUL.md/simorgh.toml off-limits,
# DenylistRule still rejects raw sockets/subprocesses in drafted code),
# and `run_tests` is there so it can check itself before committing.
PATCH = Profile(
    name="patch",
    # `run_shell` is offered here and only registered by Execution when
    # `[execution] shell = true`; an unregistered tool is simply refused,
    # so the offer costs nothing when it is off.
    tools=("read_file", "list_dir", "search_code", "run_tests", "apply_source_patch",
           "replace_in_file",
           "git_commit", "git_revert", "git_discard", "run_shell", "render_page",
           # A task that builds something data-backed needs the data; both
           # are read-only and Guardian-gated, and run_shell (already here)
           # is far broader than either.
           "web_search", "web_fetch", "search_listings", "geocode",
           # The creator's own documents are context a build task often
           # needs and cannot get anywhere else.
           "kb_search", "kb_ask", "kb_open",
           # A missing capability is not a denial: find a library, install it, use it.
           "find_package", "install_package", "run_script", "browse_page", "run_container",
           # The one profile that runs unattended for a long time is the
           # one that needs a way to reach a person. Registered whether
           # or not any provider is configured: an absent credential
           # makes the tool refuse and say which variable to set, which
           # is a far better answer than the tool not existing on the
           # day somebody adds the key.
           "notify",
           # Offered but registered only when `[execution] remote = true`
           # AND a host is configured -- an unregistered tool is simply
           # refused, so the offer costs nothing when it is off (the same
           # bargain `run_shell` above already makes).
           "run_remote"),
    # 8 left no room: read, apply, run_tests, git_commit is already four
    # tool calls before a single wrong turn, and the last step is spent
    # on the forced final answer. Live-caught 2026-09-07.
    read_only=False, max_steps=20, max_revisions=2, scaffold="patch", max_output_tokens=16_000,
)
RESEARCH = Profile(
    # `run_shell` is here because "go and find out X" is exactly the
    # kind that needs it, and it had no way to count, sort or aggregate
    # anything -- a trial burned its whole budget substituting list_dir
    # (observer, 2026-09-08). Guardian gates it the same as anywhere.
    name="research",
    tools=("self_map", "read_file", "list_dir", "search_code", "web_search", "web_fetch",
           "search_listings", "geocode", "find_package", "run_tests", "run_shell",
           # "go and find out X" about the creator's own life is a
           # research question whose sources are on this machine.
           # `kb_sources` is here and nowhere else: research is the one
           # profile that may reasonably need to index something first.
           "kb_search", "kb_ask", "kb_open", "kb_status", "kb_sources",
           "cal_list", "mail_search", "mail_read",
           # The one profile that should be able to actually run the
           # check, not just read what it found.
           "sec_self", "sec_posture", "sec_findings", "sec_show", "sec_accept",
           "home_find", "home_state", "home_describe",
           "energy_status", "energy_report", "energy_tariff", "media_now"),
    # 6 predates web_search/web_fetch. A question with a repo half and a
    # web half needs search + fetch + two repo steps + an answer, and
    # died on step 6 every time (observer, 2026-09-08).
    read_only=False, max_steps=14, max_revisions=0, scaffold="research", verify=True,
)
PLAN = Profile(
    name="plan",
    tools=("read_file", "list_dir", "search_code", "web_search", "web_fetch",
           # Read-only, so the searching three but not `kb_sources`.
           "kb_search", "kb_ask", "kb_open",
           # Planning around what is actually in the diary.
           "cal_list"),
    # `verify=False`: a plan session's product is a plan, and the task
    # verifier asks "was the change implemented?" -- to which the honest
    # answer is always no. With `max_revisions=0` that `fail` blocked the
    # session before its plan text was ever handed to Planning, so no
    # child task could exist. Found by a watched trial 2026-09-07. The
    # plan itself is reviewed downstream (`plan.proposed` -> Verification's
    # plan review), which is the right gate for it.
    read_only=True, max_steps=8, max_revisions=0, scaffold="plan", verify=False,
)
SKILL = Profile(
    name="skill",
    # `run_python_sandboxed` because `run_tests` on a brand-new skill
    # reports "no tests cover this target" -- so Sim never executed the
    # skill it had just written, and verification correctly called it
    # asserted-not-verified (observer, 2026-09-08).
    tools=("read_file", "list_dir", "search_code", "run_tests", "run_python_sandboxed",
           "apply_skill", "replace_in_file", "git_commit", "git_discard"),
    read_only=False, max_steps=20, max_revisions=2, scaffold="skill", max_output_tokens=16_000,
)

# A SPOKEN chat turn. The creator's screen, 2026-09-11: "you're not
# responding" became a 25-step exploration -- self_map, search_code,
# read_file, and finally `replace_in_file` on the live voice config --
# while the person waited in silence. A spoken remark is answered from
# what the model knows, quickly; a spoken REQUEST for work becomes a
# task (`start_task`) that runs on its own and reports back. No tool
# here writes a file, and four steps is room for one lookup, not a
# dig.
VOICE_CHAT = replace(
    CHAT,
    tools=("self_map", "read_file", "search_code", "web_search", "web_fetch", "start_task",
           "cast_devices", "cast_show", "cast_play", "cast_stop", "cast_volume"),
    # Eight: a search, a cast, a retry, and the answer (the creator,
    # 2026-09-12: "cast something on TV" ran out at five). The silence
    # a longer spoken turn used to mean is covered now: the backchannel
    # says "still on it" while the work goes on.
    max_steps=8,
)


def for_percept(channel: str) -> Profile:
    """The profile for a conversational percept on `channel`."""
    return VOICE_CHAT if channel == "voice" else CHAT


BY_KIND: dict[str, Profile] = {
    "chat": CHAT,
    "patch": PATCH,
    "research": RESEARCH,
    "project": PLAN,  # mode=plan sessions use the plan profile regardless of task kind
    "skill": SKILL,
}


def for_task(kind: str, mode: str) -> Profile:
    if mode == "plan":
        return PLAN
    return BY_KIND.get(kind, CHAT)
