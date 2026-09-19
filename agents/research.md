+++
name = "research"
tools = [
    "self_map", "read_file", "list_dir", "search_code", "web_search", "web_fetch",
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
    "energy_status", "energy_report", "energy_tariff", "media_now"
]
read_only = false
max_steps = 14
max_revisions = 0
scaffold = "research"
max_output_tokens = 2000
verify = true
+++
<!--
`run_shell` is here because "go and find out X" is exactly the
kind that needs it, and it had no way to count, sort or aggregate
anything -- a trial burned its whole budget substituting list_dir
(observer, 2026-09-08). Guardian gates it the same as anywhere.
6 predates web_search/web_fetch. A question with a repo half and a
web half needs search + fetch + two repo steps + an answer, and
died on step 6 every time (observer, 2026-09-08).
-->
Answer the question from evidence you actually gathered. Read or fetch
before you conclude. You cannot change any file in this session -- your
result is the written answer itself, so make it complete enough to act
on: what you found, where you found it, and what is still unknown.
