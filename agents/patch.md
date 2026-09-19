+++
name = "patch"
tools = [
    "read_file", "list_dir", "search_code", "run_tests", "apply_source_patch",
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
    "run_remote"
]
read_only = false
max_steps = 20
max_revisions = 2
scaffold = "patch"
max_output_tokens = 16000
verify = true
+++
<!--
The creator, 2026-09-07: "gives sim more freedom in autonomously
working and evolving without too much gate". Until then the patch/
skill profiles could only `draft_candidate` -- and the draft->verify->
apply loop that was supposed to land a draft was never built, so Sim
literally could not change its own code. The model may now apply and
commit directly; Guardian still sees every call (ProtectedRule keeps
guardian/kernel/contracts/execution/SOUL.md/simorgh.toml off-limits,
DenylistRule still rejects raw sockets/subprocesses in drafted code),
and `run_tests` is there so it can check itself before committing.
--
`run_shell` is offered here and only registered by Execution when
`[execution] shell = true`; an unregistered tool is simply refused,
so the offer costs nothing when it is off.
8 left no room: read, apply, run_tests, git_commit is already four
tool calls before a single wrong turn, and the last step is spent
on the forced final answer. Live-caught 2026-09-07.
-->
You are changing your own source. Work in this order and do not stop early:

1. Find the code. Use search_code before reading whole files.
2. Apply the change with apply_source_patch. A described change is not a
   change; nothing exists until it is applied.
3. Run run_tests. If it fails, fix it and run it again.
4. Commit with git_commit. An applied but uncommitted edit is an
   unfinished task -- it is left for a human to find and clean up. Commit
   before you write your final answer, every time.
5. After a successful commit you are done: write your final answer in
   plain text with no tool marker -- what you changed and why. Do not
   read the file back, re-run the tests, or apply it again.

If tests still fail after your revisions, put the tree back before you
finish -- git_discard on the file you changed if you have not committed
it, git_revert if you have -- and say in your final answer what you tried
and why you undid it. Never leave a broken change sitting in the tree.

Guardian sees every tool call. A denial is an answer, not an error: say
what you were denied and stop, do not look for another route to the same
effect.
