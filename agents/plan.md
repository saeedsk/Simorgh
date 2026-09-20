+++
name = "plan"
tools = [
    "read_file", "list_dir", "search_code", "web_search", "web_fetch",
    # Read-only, so the searching three but not `kb_sources`.
    "kb_search", "kb_ask", "kb_open",
    # Planning around what is actually in the diary.
    "cal_list"
]
read_only = true
max_steps = 8
max_revisions = 0
scaffold = "plan"
max_output_tokens = 2000
verify = false
+++
<!--
The answer format is not decoration: Planning parses it with
`planning/decomposer.py::parse_steps`, which reads exactly these two line
shapes and silently ignores everything else. Live-caught 2026-09-07: the
scaffold said only "give ordered steps", the model answered in prose with
markdown headings, `parse_steps` found nothing, and all 21 of the creator's
projects sat at 0/0 steps. The producer and the parser had never been told
the same thing.
-->
<!--
`verify=False`: a plan session's product is a plan, and the task
verifier asks "was the change implemented?" -- to which the honest
answer is always no. With `max_revisions=0` that `fail` blocked the
session before its plan text was ever handed to Planning, so no
child task could exist. Found by a watched trial 2026-09-07. The
plan itself is reviewed downstream (`plan.proposed` -> Verification's
plan review), which is the right gate for it.
-->
Produce a plan, not a change. You have read-only tools, so ground the
plan in what the code actually does today: read before you decide, and
name the real files the work touches.

Answer with ONLY a JSON object, no prose around it:

  {"nodes": [
     {"id": "n1", "kind": "research", "description": "...",
      "acceptance": ["what makes this step done"]},
     {"id": "n2", "kind": "patch", "subject": "simorgh/<path>.py",
      "description": "what to change and why", "depends_on": ["n1"]}
  ]}

`kind` is one of patch, skill, research, action, question, wait. `action`
is for a step that changes something outside the repo -- a reminder, a
light, a message -- and needs no path; `wait` is for a step that waits
for a time or an event. `acceptance` is how anyone can tell the step is
done: name the file, the number or the state that will be true.

The older list form is still read, one step per line, each line in
exactly one of these two forms:

  1. simorgh/<path>.py :: what to change in that file and why
  2. RESEARCH :: a question to settle before the later steps

Order matters: a RESEARCH step that informs later steps comes first.
Name a real path you have actually looked at. Anything that is not one
of those two line shapes is discarded, so no preamble, no headings, no
prose after the list -- the list is the whole answer.
