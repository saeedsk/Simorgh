+++
name = "planner"
extends = "plan"
max_steps = 10
+++
<!--
Stage 7 item 2. The plan agent, addressable by name so a task can spawn a
planner as a helper (`task {"agent": "planner"}`) rather than only
reaching it through a plan-mode session. Same read-only tools and the
same answer format, which Planning's parser depends on -- see the note in
agents/plan.md about what happens when the producer and the parser have
not been told the same thing.
-->
