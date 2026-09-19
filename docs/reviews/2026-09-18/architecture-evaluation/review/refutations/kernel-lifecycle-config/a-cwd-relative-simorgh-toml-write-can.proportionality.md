# refute:proportionality:A cwd-relative `simorgh.toml` write can

*Workflow: review · Phase: Refute · Agent id: `aa0398d9b15ce3d5e` · Tool calls: 6*

## Task given to the agent

```text
You are reviewing the ARCHITECTURE of Simorgh, a self-improving personal AI agent written in Python (stdlib-first) at /Users/saeed/ws/Simorgh. The creator built it from scratch: ~87k lines in simorgh/, 18 subsystems (one package each) composed by a Kernel, talking only via typed messages on an async Bus, all state in an append-only Ledger of events, a Guardian that is the sole approver of every effect (HMAC token re-verified by Execution), worktree-isolated self-patching, a bootloader (simloader.py) that gates the checkout with the unit suite and rolls back. It chats (CLI/TUI/HTTP/Telegram/WhatsApp), talks (voice pipeline), controls the house (Home Assistant, Reolink cameras, Ring, Cast/Android TV), and runs benchmarks (GAIA/BFCL/SWE-bench).
  
  The creator asked: "review its architecture, evaluate it, tell me where I went wrong and how to improve it."
  
  Ground rules for you:
  - Read the CODE, not the docs, to establish what is true today. docs/EVOLUTION.md (5,254 lines) is a HISTORY; a bug it describes has very likely been fixed since. Do not report a historical finding as current state.
  - Previous reviews already exist and you must NOT simply repeat them. Already known (do not re-report unless you have something materially new to add): cameras use local ffmpeg/HLS instead of Home Assistant; self_patch.draft tool is named in learning/pipeline.py but not registered; Self Model capabilities["tools"] is never populated; no in-prompt sliding dialogue buffer for chat turns (orchestration/context.py); Ledger default backend is JSONL and ~1.4 GB; CHAT profile binds 34 tools; STT latency degrades under self-inflicted load; "unconnected wire" (designed slot, one side implemented, nobody writes it) is the project's dominant bug shape; test coverage thin in persona/learning/worldmodel; sim.sh auto-approve flips one boolean. Read docs/architecture-review-2026-09-18.html and docs/architecture-audit-2026.md quickly if you want the full list.
  - Useful orientation docs (read briefly, then go to code): docs/module-map.md, docs/architecture.md, docs/blueprint/02-system-architecture.md, docs/blueprint/03-contracts-and-messaging.md.
  - Every finding MUST cite file:line evidence you actually read, and where feasible a command whose output you quote. If a claim depends on runtime behaviour, try to establish it by a cheap command (python -c import + inspect, grep, wc, reading ~/.simorgh/simorgh.toml, listing ~/.simorgh/ledger). Do NOT boot the full system, do NOT run the full test suite, do NOT run anything that calls a paid model, do NOT modify any file in the repo.
  - Think like a senior systems architect. Distinguish (a) a design decision that is wrong or over-built for this system's real scale (one laptop, one family), (b) a design that is right but the implementation undermines it, (c) a genuine bug. Say which.
  - Your final text is data for an orchestrator, not a message to a human. Return only the structured output.
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "kernel-lifecycle-config". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "A cwd-relative `simorgh.toml` write can silently shadow the real config on the next boot",
    "kind": "bug",
    "severity": "high",
    "claim": "interface/dispatch.py appends MCP approvals to `Path(\"simorgh.toml\")` relative to the process cwd, which under sim.sh/simloader is the repo root where no simorgh.toml exists; the Kernel's search order prefers ./simorgh.toml over ~/.simorgh/simorgh.toml, so after one `mcp approve` and the advertised restart the entire live configuration ([voice], [interface], [execution] secrets, [cognition]) is replaced by a file containing one MCP block, with no warning.",
    "evidence": [
      "simorgh/interface/dispatch.py:79 `_SIMORGH_TOML_PATH = Path(\"simorgh.toml\")`; :2167-2173 `with _SIMORGH_TOML_PATH.open(\"a\", ...)` then `return Outcome(f\"approved: wrote ... to {_SIMORGH_TOML_PATH} -- restart Sim to load it\")`.",
      "simorgh/kernel/config.py:44-50: `cwd_candidate = Path(\"simorgh.toml\"); if cwd_candidate.is_file(): return cwd_candidate` before the data_dir candidate.",
      "sim.sh:13 `cd \"$REPO_ROOT\"`; simloader.py:1057 `subprocess.run([...\"-m\", \"simorgh\", \"run\"...], cwd=repo, ...)`; `ls /Users/saeed/ws/Simorgh/simorgh.toml` -> 'No such file or directory'; the live config is ~/.simorgh/simorgh.toml.",
      "A second, independent config path exists: simorgh/contracts/settings.py:162-170 re-implements the search order 'without importing' the kernel (ignores --config and SIMORGH_RUNTIME_DATA_DIR) and :185 is a TOML writer; contracts/places.py:57-62 reads the TOML directly with a module-level `_cache`."
    ],
    "why_it_matters": "Configuration has one reader in the kernel but at least three independent locators/writers outside it. The failure is silent and total: configcheck cannot warn because the shadow file parses fine, and `config` will happily report the new path. It also means a `--config other.toml` run has tools persisting settings into a different file from the one being read.",
    "recommendation": "Make the path a single fact: add `config_path` to Context (ContextFactory already holds LoadedConfig.path) and have every writer (settings.py, places.py, dispatch.py) use it; delete the cwd candidate from find_config_path (a daemon launched from a repo root should not read a repo-relative config); have contracts/settings.py call kernel.config.find_config_path instead of copying it.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read cited lines in dispatch.py and kernel/config.py | # And `kernel/service.py::Kernel.CONFIG_STREAM`. CONFIG_STREAM = "config:effective" # `simorgh.toml`'s primary search location (`kernel/config.py::find_ # confi |
| 2 | Bash | Check config file presence, launcher cwd, and the other config locators | ls: simorgh.toml: No such file or directory -rw-r--r-- 1 saeed staff 670 Sep 18 15:04 /Users/saeed/.simorgh/simorgh.toml 12:REPO_ROOT="$(cd "$(dirname "${BASH_S |
| 3 | Bash | Check loader cwd, kernel config load site, live config sections, MCP proposal producers and tests |  return returncode def launch_sim(repo: Path, notes: Path, sim_args: list[str]) -> int: """Run Sim in the foreground until it exits. Its own function so a test  |
| 4 | Bash | Check MCP proposal producer, boot config path resolution, and whether the boot reports the config path | Exit code 1 unanswerable at the time this was first written (`interface/ service.py`'s own docstring on the `_on_prompt` fix has the story -- `action.needs_huma |
| 5 | Bash | Check launcher env, boot-time config path reporting, tool registration, and whether prior reviews knew this | Exit code 1 --- config:effective 464: CONFIG_STREAM = "config:effective" 513: "path": str(self.config.path) if self.config.path else "", 521: await self.ledger. |
| 6 | Bash | Check tool registration, prior review coverage, and sim.sh environment exports | simorgh/interface/live_status.py simorgh/cognition/service.py simorgh/cognition/parser.py simorgh/contracts/toolargs.py simorgh/execution/service.py simorgh/exe |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line is accurate and the mechanism is complete end to end. (1) dispatch.py:79 hardcodes `Path("simorgh.toml")` and :2167-2173 appends to it on `mcp approve`, reporting the bare relative path. (2) kernel/config.py:44-46 checks `Path("simorgh.toml").is_file()` before the data_dir candidate, so a repo-root file wins over ~/.simorgh/simorgh.toml. (3) sim.sh:13 `cd "$REPO_ROOT"` and simloader.py:1057 `cwd=repo` make the process cwd the repo root; `ls simorgh.toml` there fails, while ~/.simorgh/simorgh.toml (670 bytes, [voice]/[interface]/[execution] incl. `secrets` and `cast_device`/[cognition.providers.*]) is the live config. sim.sh exports no SIMORGH_CONFIG, so nothing short-circuits the cwd candidate. (4) The trigger is reachable: `propose_mcp_server` is a registered, profile-bound tool (execution/tools.py:935, orchestration/profiles.py:64) that appends to `mcp:proposals`; the human then types `mcp approve <id>`. (5) The failure is silent at the terminal: the only place the chosen path is recorded is a `config:effective` ledger event (kernel/service.py:513-522); boot prints nothing. dispatch.py's own docstring (:72-78) admits it does not replicate the search and calls a mismatch "visible, honest" -- but the creator's setup is the DEFAULT one, and the only visibility is a relative filename in the Outcome text. dispatch.py:1693-1697 records that a bad `mcp approve` already broke "the file Sim reads at its next boot" once (2026-09-08), so this code path has been exercised live. (6) The independent locators are real: contracts/settings.py:161-170 re-implements the order, hardcoding `~/.simorgh` (ignores SIMORGH_RUNTIME_DATA_DIR and --config), and places.py:52/85/98/109 read and `persist()` through it; `persist` rewrites the whole file, so once a shadow exists at cwd, every `voice set`/place write also lands in the shadow and compounds the divergence. Not present in either prior review (grep for cwd/shadow/find_config_path in docs/architecture-audit-2026.md and the 2026-09-18 HTML returns nothing). Skeptic lens on proportionality: this is a genuine bug (kind c), not an over-built design; the fix is small (drop the cwd candidate or resolve it against data_dir, and have the three writers take the path from LoadedConfig/Context), so the recommendation is proportionate. Trigger frequency is low (human-initiated, rare), which is the one argument for medium rather than high, but the blast radius is total and confusing to diagnose (secrets path, voice, providers, cast device all vanish after a restart the tool itself told the user to do), so I keep the severity.

### evidence

- simorgh/interface/dispatch.py:79 `_SIMORGH_TOML_PATH = Path("simorgh.toml")`; :2167-2168 `with _SIMORGH_TOML_PATH.open("a", encoding="utf-8") as fh: fh.write(_mcp_server_toml_block(proposal))`; :2173 `return Outcome(f"approved: wrote {proposal['name']!r} to {_SIMORGH_TOML_PATH} -- restart Sim to load it")`
- simorgh/interface/dispatch.py:72-78 docstring: "doesn't replicate that function's full `$SIMORGH_CONFIG`/`${data_dir}` fallback search ... a non-default setup is a visible, honest mismatch" -- but the creator's setup IS the default data_dir one
- simorgh/kernel/config.py:44-50: `cwd_candidate = Path("simorgh.toml"); if cwd_candidate.is_file(): return cwd_candidate` precedes `data_dir / "simorgh.toml"`; :157-160 load_config passes data_dir=~/.simorgh
- sim.sh:12-13 `REPO_ROOT=...; cd "$REPO_ROOT"`; sim.sh exports only SIMORGH_EXECUTION_REPO_ROOT and PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION (no SIMORGH_CONFIG); simloader.py:1057 `subprocess.run([sys.executable, "-m", "simorgh", "run", *sim_args], cwd=repo, env=env)`
- `ls -la /Users/saeed/ws/Simorgh/simorgh.toml` -> `No such file or directory`; `ls -la ~/.simorgh/simorgh.toml` -> `-rw-r--r-- 670 Sep 18 15:04`; sections: [voice] [interface] [execution] (keys `secrets`, `cast_device`) [cognition] [cognition.providers] [cognition.providers.ollama]
- simorgh/kernel/service.py:513 `"path": str(self.config.path) if self.config.path else ""` inside the config:effective ledger event (:521-522) -- the only record of which file was read; no terminal print
- simorgh/interface/dispatch.py:1693-1694 comment: "one committed to `simorgh.toml` by `mcp approve` broke the file Sim reads at its next boot (observer, 2026-09-08)" -- path exercised live
- simorgh/execution/tools.py:935 `name = "propose_mcp_server"`, :968-969 appends to MCP_PROPOSALS_STREAM; simorgh/orchestration/profiles.py:64 binds "propose_mcp_server"; orchestration/tools.py:238 marks it reversible (Guardian auto-allows)
- simorgh/contracts/settings.py:161-170 `config_path()` re-implements the order with `Path("~/.simorgh").expanduser()` hardcoded (ignores SIMORGH_RUNTIME_DATA_DIR/--config); :216 `def persist(path, key, value, *, section="voice")` rewrites the whole file; simorgh/contracts/places.py:52 `target = path or config_path()`, :85/:98/:109 `persist(path or config_path(), ...)`
- `grep -n -i 'cwd|shadow|find_config_path|settings.py' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html` -> no output (not previously reported)

**severity adjustment:** keep

