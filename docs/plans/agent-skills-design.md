# Agent Skills for Sim: load on demand, install from open repositories

The creator, 2026-09-15, after seeing Claude Code load a skill to do a job: "it was a question of Sim supporting skills, and later on finding open-source skill repos and making them available to Sim to load on demand." And: "does it make sense that we download lots of skills that Anthropic created and released and make them available to Sim by default?"

This document is written so the next session can build from it without re-deriving anything.

## 1. What stands today

**Sim's current "skills" are Python tools, not instructions.** A skill is a file in `simorgh_skills/<name>.py` (`[execution] skill_dir`). Execution announces each file as `skill:<name>` without loading it, and loads it on first use (`execution/service.py::_announce_skills_on_disk`, `_load_skill`). Reflection's distillation proposes new ones from solved tasks, capped at 3 a day. The directory is empty in the live checkout. Memory has a `procedural` kind (`memory/store.py`), written by the learning pipeline and queried when a skill loads.

**Nothing in Sim reads written instructions on demand.** A task's context is the scaffold for its profile, the memory block and its own transcript. There is no place for "here is how to do X well" that Sim can pull in when X comes up.

## 2. The format: Agent Skills

Agent Skills are an open format, originally developed by Anthropic and released as a standard now adopted by several agent products. The specification lives at [agentskills/agentskills](https://github.com/agentskills/agentskills).

**Shape.**
- A skill is a folder containing `SKILL.md`: YAML frontmatter with at least `name` and `description`, then Markdown instructions.
- The folder may bundle scripts, reference documents and templates.

**Progressive disclosure.** The agent keeps only each skill's name and description in context. When a task matches, it reads the full `SKILL.md`, and it opens bundled files only when the instructions point to them ([Strapi](https://strapi.io/blog/what-are-agent-skills-and-how-to-use-them), [Microsoft Learn](https://learn.microsoft.com/en-us/agent-framework/agents/skills)). Many skills cost little until one is used.

Sim should adopt this format as-is, so a skill written for any compatible agent works in Sim without rewriting. The Python `skill:` tools stay, as a separate and older mechanism.

## 3. Design

### 3.1 Where skills live

| Source | Path | Who puts them there |
|---|---|---|
| Bundled | `skills/<name>/SKILL.md` in the repo | committed; open licences only (§5) |
| Installed | `~/.simorgh/skills/<source>/<name>/SKILL.md` | `skills install`, per machine, never committed |
| Written by Sim | `~/.simorgh/skills/sim/<name>/SKILL.md` | distillation (§3.7), reviewed like an install |

`contracts/skills.py` (pure) parses `SKILL.md` (frontmatter and body) into a `SkillCard{name, description, source, path, allowed_profiles?, sha256}`. It validates the name (`[a-z0-9-]{1,64}`) and caps the description at 1,024 characters. Invalid skills are listed with the reason and not offered.

### 3.2 The catalog in every task

A new `skills` block in `task_rules`, rendered by `scaffolds.render`, lists the enabled skills as `- name: description`. It gets a token cap (`[orchestration] skills_catalog_max_chars`, default 3,000), because every THINK pays for it (§5.2).

**Where the settings live (built 2026-09-15).** Not a `[skills]` section: the module-boundary rule is that no subsystem imports another, so a `simorgh/skills/` package could not be read by Orchestration, which is what renders the catalog and runs `use_skill`. The parser stays in `contracts/skills.py` (subsystems may import contracts) and the settings are `[orchestration] skills_enabled`, `skills_catalog_max_chars`, `skills_roots`.

Skills can be filtered per profile:
- a skill's optional `allowed_profiles` (a Sim extension, ignored by other agents);
- `[skills] profiles`, for example `research = ["pdf", "xlsx"]`.

Voice chat offers none by default.

### 3.3 `use_skill(name)`

A model-visible tool, orchestration-local like `delegate`, since it touches no outside system.
1. It returns the skill's `SKILL.md` body, capped at 12,000 characters, as the tool result, with a header naming the skill folder.
2. The session records `step{tool:"use_skill", summary:name}`.
3. Re-grounding (`orchestration/progress.py`) keeps "using skill X" in the progress note, so the instructions are not silently lost.

Bundled files are read with `read_file` on the skill's path: `skills/` is in Execution's `readable_roots` and in no write scope (step 3). Installed skills under `~/.simorgh/skills` are outside the repo bound that `pathsafety` enforces, so reading their bundled files waits for the installer (step 4); `use_skill` returns their instructions either way.

### 3.4 Tool names inside skills

Skills written for Claude Code refer to its tools: `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`. `use_skill` prepends a fixed mapping note:

| Claude Code | Sim |
|---|---|
| Read | `read_file` |
| Write, Edit | `apply_source_patch` / `replace_in_file` |
| Bash | `run_shell` / `run_script` |
| Grep, Glob | `search_code` / `list_dir` |

It adds a warning that tools Sim lacks are unavailable. This is text, not a rewrite of the skill, so the skill's hash still matches its source.

### 3.5 Scripts run only through Guardian

A bundled script never runs because a skill loaded. The model asks for it like any command: `run_script` or `run_python_sandboxed` with the script's path. Guardian applies the same policy as for any other command, `irreversible` unless sandboxed. A skill's missing dependencies (`python-docx`, `openpyxl`, LibreOffice) are reported, not installed silently. Installing goes through `install_package`, which Guardian also gates.

### 3.6 Installing, updating and removing

`skills install <git-url>[#path] [--ref <commit|tag>]` does the following:
1. Clones to a temporary directory at an exact commit (`git clone --depth 1` then checkout). The commit is recorded.
2. Finds every `SKILL.md` under the path and parses them.
3. Runs the **review**, deterministic first:
   - the licence file and SPDX id;
   - scripts and their languages;
   - network use (`curl`, `requests`, `urllib`, sockets);
   - destructive commands (`rm -rf`, `git push`, `chmod`), credential or environment access, and `sudo`;
   - hidden or obfuscated text (zero-width characters, base64 blobs);
   - instructions aimed at the agent's rules ("ignore previous", "you are now", "do not tell the user").

   Then an optional model summary, purpose `review`.
4. Applies the source's trust tier (§3.9). A skill from a trusted org is enabled with no approval step, but the review still runs and anything it flags is held back. A skill from any other source is shown to the creator as a summary, and nothing is enabled until approved (`skills approve <name>`).
5. Copies the approved skill to `~/.simorgh/skills/<source>/<name>/` and writes `~/.simorgh/skills/lock.json` with source, commit, sha256 per file, licence and approval time.

**Update.** `skills update <name>` re-fetches, diffs against the lock, and needs approval again if any script or instruction changed. A trusted-org skill moves its pinned commit only by an explicit `skills update`; it is never auto-pulled.

Built 2026-09-15. Two things the implementation forced:

- The lock stores the **whole** `Source` (host, org, repo, `#path`) beside the commit. `Source.name` is only `org/repo`, so a record holding just the name has no URL to re-fetch from -- an install written before the lock existed cannot be updated, and `update` says so rather than guessing.
- The lock hashes **every file**, not `SkillCard.sha256`, which covers `SKILL.md` alone. Diffing against that hash would have missed a changed script entirely -- the one change this section says must stop for approval.
- What changed decides what happens: a changed script or changed `SKILL.md` drops the skill back to waiting and names the files; a documentation-only change on a trusted org with a clean review updates in place.

**Other commands.** `skills remove <name>`, `skills list` (enabled, pending, invalid), `skills show <name>`.

This review exists because published work documents real attacks and specification violations in skills ([a threat taxonomy](https://arxiv.org/pdf/2604.02837), [semantic fuzzing](https://arxiv.org/pdf/2605.13044), [SkillTester](https://arxiv.org/pdf/2603.28815)).

### 3.7 Skills Sim writes itself

Distillation (`reflection/distillation.py`) gains a second output: a `SKILL.md` procedure drafted from a solved task's steps. It is written to `~/.simorgh/skills/sim/<name>/` as *pending*, and approved the same way. It is safer to generate than new Python, because it is advice the model follows through tools Guardian already gates.

### 3.9 Trust tiers (agreed 2026-09-15)

Trust belongs to the **GitHub organisation that maintains a repository**, never to a directory or marketplace that lists it.

| Tier | Sources | On install | Default |
|---|---|---|---|
| Trusted org | `anthropics`, `google`, `microsoft`, `huggingface`, `trailofbits` (`[skills] trusted_orgs`) | pinned commit, licence check, deterministic review; enabled unless the review flags something | enabled when relevant to Sim |
| Reviewed | any other repository | pinned commit, sha256 per file, review, creator approval | pending until approved |
| Discovery only | marketplaces and aggregators (SkillsMP, ClawHub, "awesome" lists) | never installed from directly; a skill found there counts as trusted only if it lives in a trusted org's repo | n/a |

For every tier:
- **Licence at install.** Apache/MIT-style skills may be bundled; source-available ones (Anthropic's `docx`/`pdf`/`pptx`/`xlsx`) are installed locally on first use and never committed.
- **Environment fit.** Vendor skills assume their own CLI, MCP server or Claude's tool names. Each is checked against Sim's tools (§3.4) before it is enabled.
- **Relevance.** Trust does not put a skill in the catalog. Only skills Sim will use are enabled (§5.5). Relevant trusted repos today: `anthropics/skills`; `google/skills` (Gmail, Drive, Docs, Sheets, Calendar, YouTube; Apache-2.0); `trailofbits/skills` (security review for self-patches); `microsoft/playwright-cli`; `huggingface/skills` (model scouting). Product-specific vendor repos (Vercel, Cloudflare, Stripe, Supabase, Neon, PlanetScale, Redis, HashiCorp) are trusted but off-mission. `openai/skills` is deprecated.

### 3.8 Finding skills

`skills search <topic>` queries a short, configured list of sources:
- the trusted orgs' skill repositories (§3.9);
- the `agentskills` examples;
- any repository the creator adds under `[skills] sources`.

It matches names and descriptions and shows licence and source for each. Nothing is installed without `skills install`.

## 4. Anthropic's public skills

[github.com/anthropics/skills](https://github.com/anthropics/skills) holds more than 50 skills ([The Decoder](https://the-decoder.com/github-repository-offers-more-than-50-customizable-claude-skills/)) under two licences:

- **Example skills** (algorithmic-art, brand-guidelines, internal-comms and others): **Apache 2.0**, open source.
- **Document skills** (`docx`, `pdf`, `pptx`, `xlsx`): **source-available, not open source**, shared as a reference.

## 5. Should Sim ship many skills by default? No: a small curated default, the rest on demand

### 5.1 Licences

- Apache-2.0 example skills may be bundled in the repo, keeping their `LICENSE` and a `NOTICE`.
- The document skills may **not** be redistributed in Sim's repository. The creator can still install them locally with `skills install` for personal use on this machine, after reading the terms.

### 5.2 Context cost on every call

The catalog is paid on every THINK of every task:
- about 50 skills × about 60 tokens per name and description is roughly 3,000 tokens per call;
- a 20-step task spends about 60,000 tokens reading a menu it mostly never uses.

At GLM-5.3-Flash prices that is cheap in dollars, but it dilutes the context the long-run work (docs/plans/long-run-context-design.md) is trying to keep clean.

### 5.3 A weaker model picks the wrong skill

Skills in `anthropics/skills` were written for Claude, and many descriptions overlap. A long menu invites a mismatched `use_skill`, and a skill's instructions then pull the task off course. That is the "drift" re-grounding was built to fight.

### 5.4 Environment mismatch

- Many skills assume Claude Code's tool names and a Python toolchain with LibreOffice, Node or Playwright present.
- Unreviewed, their scripts are the riskiest code Sim would run.

### 5.5 Most are off-mission

Brand guidelines, internal communications and algorithmic art are not what a home assistant's day looks like.

### 5.6 Recommendation

1. **Bundle a small default set (5-8 skills) from trusted orgs, chosen for Sim's actual work, enabled by default.** Candidates, each checked for licence and dependencies before bundling:
   - `skill-creator`, so Sim can draft good skills;
   - `webapp-testing`, for the dashboard;
   - `mcp-builder`, for Sim's MCP proposals;
   - a home-document skill (reading bills and PDFs, written for Sim);
   - a research-report skill for GAIA-style questions.
2. **Install the document skills locally, on request**, since household paperwork (PDFs, spreadsheets) is real Sim work. Keep them out of the repo.
3. **Everything else stays one `skills search`/`skills install` away**, per need, with the review.
4. **Filter the catalog per profile** so a voice turn never sees a spreadsheet skill.
5. **Measure it:** run the benchmark slice (docs/plans/long-run-context-design.md §9) with no skills, the default set, and the default set plus document skills. Keep a skill only if it moves a score or clearly serves a household job.

## 6. Build plan

| # | Deliverable | Done when |
|---|---|---|
| 1 ✅ (ee89c39) | `contracts/skills.py` parser plus loader for the three roots | parses the spec's examples; invalid skills listed with a reason |
| 2 ✅ (ebbae74) | Catalog block in `task_rules` (capped, per-profile) and the `use_skill` tool with the tool-name mapping note | a scripted session loads a skill and its instructions reach the model; the catalog is absent when `[skills] enabled = false` |
| 3 ✅ (7e5a94f) | Guardian read-only path rule for skill roots; scripts only through `run_script` | a skill script is not run without a gated call |
| 4 | `skills list/show/remove`; `install` from git at a commit, with the deterministic review, trust tiers (§3.9), `approve`, and `lock.json` | a hostile fixture skill is flagged and not enabled; an approved skill appears in the catalog |
| 5 ◐ | `skills update` with diff and re-approval **done**; `skills search` over configured sources still open | a changed script needs re-approval |
| 6 | Default bundled set (licence-checked) | `skills/` committed with `LICENSE`/`NOTICE` |
| 7 | Distillation writes pending `SKILL.md` | a solved task yields a pending skill for approval |
| 8 | Benchmark arms: none / default / default+document | results appended to `docs/benchmark-analysis-2026-09-14.md` |

**Deploy.** `[orchestration] skills_enabled` defaults to true once the bundled set lands (step 6); the catalog then holds only the bundled trusted-org set, and installed skills follow their tier (§3.9). Step 8 confirms the catalog does not cost benchmark score; if it does, the default flips back to false. Each step is pushed when its tests pass, and the live Sim picks it up on `restart`.
