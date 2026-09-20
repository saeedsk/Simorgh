# Adding a capability

Sim has 98 tools. Roughly a dozen of them exist because somebody needed a
thing once and wrote a tool class for it; each one carries its own
argument parsing, its own error strings, its own credentials handling, and
its own way of being wrong. That is the cost this page exists to stop.

**The rule: a new capability arrives as an MCP server, not as a tool class.**

## Why

An MCP server brings its own schemas, so the model sees argument shapes
rather than a hand-written hint table; it runs as its own process, so a
hung integration cannot stall the event loop; it is configured by a
person, so a credential never arrives with the code; and it can be
removed by deleting a config entry. A tool class inside `execution/` is
the opposite of all four, and `execution/` is Guardian-protected, so every
addition widens the part of the system Sim may not change.

## How

1. **Find or write the server.** Prefer one that exists. It must declare
   an `inputSchema` per tool; a server without schemas is a server that
   will be called wrongly.
2. **Configure it, by hand, as a person.** `mcp add <name> <command>` or
   the `[execution.mcp]` section. The credentials live where the operator
   put them, not in the repo. Sim may *propose* a server
   (`propose_mcp_server`); a person approves it.
3. **Let Guardian see it.** MCP tools go through the same
   `action.proposed` path as everything else: the tier comes from the
   tool's own reversibility and reach (`contracts/tiers.py`), and anything
   that leaves the house is tier 3 and asks a person.
4. **Give it to an agent, by name.** Add the tool to the agent file that
   should have it (`agents/*.md`). An unlisted tool is not offered, and a
   glob (`weather_*`) is allowed.
5. **Write the one test that matters**: the tool is offered to the agent
   you meant, and a refusal reads as a refusal rather than as an empty
   success.

## When a tool class is still right

- It touches the machine Sim runs on in a way no server should
  (`run_shell`, the sandboxes, the worktree tools).
- It is part of the safety mechanism itself (anything Guardian reads).
- It has no external service behind it at all: `read_file`, `search_code`.

Everything else — a new home device, a calendar, a music service, a
shopping site, a weather API — is a server.

## What this does not change

Sim still writes **skills** for things it can do with the tools it has:
a skill is a folder of instructions, not a new capability
(`simorgh_skills/`, `use_skill`). The line is: a skill composes what
exists, a server adds something new from outside.
