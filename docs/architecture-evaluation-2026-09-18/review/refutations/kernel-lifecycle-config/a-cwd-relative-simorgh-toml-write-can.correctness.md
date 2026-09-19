# refute:correctness:A cwd-relative `simorgh.toml` write can

*Workflow: review · Phase: Refute · Agent id: `aaaa9f6593b0b77f1` · Tool calls: 1*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "kernel-lifecycle-config". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Read cited dispatch.py and config.py regions | # And `kernel/service.py::Kernel.CONFIG_STREAM`. CONFIG_STREAM = "config:effective" # `simorgh.toml`'s primary search location (`kernel/config.py::find_ # confi |

## Structured reply

_No result recorded (agent still running, skipped, or failed)._

## Final text

I'll verify the cited evidence directly.