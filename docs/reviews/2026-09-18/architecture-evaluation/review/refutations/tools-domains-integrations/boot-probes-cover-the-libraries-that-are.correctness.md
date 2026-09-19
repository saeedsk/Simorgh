# refute:correctness:Boot probes cover the libraries that are

*Workflow: review · Phase: Refute · Agent id: `a51886e348ea3b647` · Tool calls: 11*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "tools-domains-integrations". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "Boot probes cover the libraries that are not used and skip the device SDKs and ffmpeg that carry 99% of calls",
    "kind": "missing",
    "severity": "low",
    "claim": "The capability floor is honest at boot (stdlib-only import, lazy find_spec guards), but proactive probing covers node/puppeteer/bandit/homeharvest/docker plus HA-style domain connectors, while reolink_aio, ring_doorbell, pychromecast, androidtvremote2, ffmpeg and osascript - the dependencies behind ~23,800 recorded calls - are only discovered by a refusal at call time.",
    "evidence": [
      "simorgh/execution/capabilities.py:154-158 PROBES = node, puppeteer, bandit, homeharvest, docker; simorgh/execution/domainstatus.py:211-215 connectors = knowledge, home, energy, media, security (pim per account)",
      "Lazy third-party imports found by grep in simorgh/execution: androidtvremote2 apprise docx fitz homeharvest openpyxl pdfminer pychromecast pypdf pytesseract ring_doorbell sentence_transformers zeroconf; binaries via shutil.which: docker(3) npm(2) node(2) git(2) tesseract rg osascript lsof ffmpeg",
      "simorgh/execution/home/cameras.py:56-61 and ring.py:60 `available()` are called per tool run, not registered as probes; requirements.txt lists none of the device libraries"
    ],
    "why_it_matters": "The 'refused by name' floor is a good pattern, but the status screen and the prompt's capability note (capabilities.py docstring: 'written into the prompt, so the model does not spend three of its steps discovering') only know about the rarely-used half. After a Python upgrade breaks reolink_aio, the first symptom is a refusal in the middle of a spoken request.",
    "recommendation": "Add one `Probe` per device backend using the existing `available()` functions (five lines each) and one for ffmpeg, all cost='free'; list the device libraries in requirements.txt under an `[house]` comment block so a fresh install of this particular house is reproducible.",
    "confidence": 0.7
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read capabilities probe definitions | """Which of Sim's capabilities actually work right now. Half of the toolset added on 2026-09-09 stands on something outside this repository: Node and a bundled  |
| 2 | Bash | Read domainstatus connectors, camera/ring available(), requirements, and probe usage |  except Exception as exc: # noqa: BLE001 return ConnectorStatus(False, f"the findings store could not be opened ({exc!r})") recorded = sum(n for status, n in co |
| 3 | Bash | Grep device SDK usage, probe registrations, available() functions, and connector classes | ----GREP simorgh/execution/home/cameras.py simorgh/execution/home/ring.py simorgh/execution/media/cast.py simorgh/execution/media/androidtv.py ----PROBEUSE simo |
| 4 | Bash | Read probe assembly in service.py, available() call sites, ledger layout | from .vision import CameraVision from .tools import RunTestsTool, SkillTool, builtin_tools from .worktree import WorktreeManager, worktree_tools from .verifier  |
| 5 | Bash | Check connector registrations, ledger stream files, probe names recorded in ledger | ----REGCONN ----CAM270 if value: return str(value) return str(self._env.get(name) or "") def _nvr(self): if self._given is not None: return self._given if self. |
| 6 | Bash | Count recorded tool calls by name in the ledger and list device tool names | TOTAL 20110 ----KINDS ----TOOLNAMES 485: name = "ring_setup" 544: name = "ring_list" 563: name = "ring_snapshot" 599: name = "ring_events" 643: name = "ring_lig |
| 7 | Bash | Count tool-call events by tool name in the execution:tools ledger stream | {"causation_id":null,"idempotency_key":null,"payload":{"name":"read_file","provider":"builtin","read_only":true,"reversibility":"read_only"},"seq":1,"stream":"e |
| 8 | Bash | Inventory ledger stream files by prefix and sample an action stream |  118215 26737 88356 trace 26737 action 2431 task 350 verify 310 reflect 5 memory 5 curiosity 5 cognition 3 persona 2 guardian 2 execution 1 voice 1 system.jsonl |
| 9 | Bash | Count recorded actions in the ledger by proposing tool name | actions 26737 device-prefixed 23963 22849 ring_live 721 cam_stream 570 run_shell 473 read_file 431 search_code 291 web_fetch 207 web_search 129 run_tests 114 ca |
| 10 | Bash | Check voice probe mechanism, prompt injection of capability detail, Probe fields, ring_live and ffmpeg use, and install docs | ----VOICEPROBE simorgh/voice/service.py:128: {"name": "audio-playback", "ok": bool(out), "detail": ", ".join(out) or "no playback path", ----PROMPT simorgh/cont |
| 11 | Bash | Trace where probe results reach the prompt or status screen | simorgh/contracts/messages/tool.py:19:ToolUnavailable = define(t.TOOL_UNAVAILABLE, [F("name", Str), F("reason", Str)]) simorgh/contracts/messages/tool.py:22:Too |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core claim holds against the code today. The boot probe table is exactly node/puppeteer/bandit/homeharvest/docker (simorgh/execution/capabilities.py:154-160), the connector probes are knowledge/home/energy/media/security plus per-account pim (simorgh/execution/domainstatus.py:203-218), and Execution assembles only PROBES + connector_probe(self._connectors) (simorgh/execution/service.py:325-326). `register_connector` (service.py:318-321) has zero callers anywhere in simorgh/. The device backends each have an `available()` (cameras.py:56, ring.py:58, cast.py:41, androidtv.py:57, musicapp.py:46) that is invoked only inside tool run paths (cameras.py:270,373; ring.py:352,503; cast.py:396; androidtv.py:135), never as a probe. The live ledger's capabilities stream confirms the runtime picture: the only probe names ever recorded are node, puppeteer, bandit, homeharvest, docker, connector:{energy,home,knowledge,media,security} and the voice subsystem's audio-playback/microphone/text-to-speech; no reolink, ring, cast, androidtv or ffmpeg probe has ever been written. requirements.txt lists none of reolink-aio, ring_doorbell, pychromecast, androidtvremote2. Counting the ledger's 26,737 action streams by proposing tool gives 23,963 device-prefixed actions (cam_/ring_/cast_/tv_/dash_), which matches the "~23,800" figure. The wiring behind "why it matters" is real too: orchestration subscribes to TOOL_PROBED (orchestration/service.py:108) and worldmodel to TOOL_UNAVAILABLE/TOOL_PROBED (worldmodel/service.py:114-115), so a probe that does not exist can never reach the prompt or the status screen.

Two corrections. First, the title's "99% of calls" is an overstatement: device tools are ~90% (23,963/26,737) of recorded actions, and 22,849 of those are a single tool, `ring_live`, proposed by `interface:dash` for WebRTC offer/keepalive signalling, not spoken requests; strip the dashboard's polling and device tools are ~1,100 of ~3,900 actions, still the largest group. Second, "libraries that are not used" is too strong: render_page (node+puppeteer) has 29 recorded calls and search_listings/run_container do exist in the registry; "rarely used" is the accurate word. The finding is not in the known list (the known camera item is about ffmpeg/HLS vs Home Assistant, not probe coverage); it is a fresh instance of the project's known "unconnected wire" shape (register_connector exists, nobody calls it; Probe.tools exists to name what breaks, no device Probe names cam_*/ring_*/cast_*/tv_*). Severity low is right: every device tool refuses cleanly with the pip line, so the cost is a late, badly placed diagnosis rather than a wrong action.

**corrected claim:** Boot probing covers node/puppeteer/bandit/homeharvest/docker and the HA-style domain connectors (capabilities.py:154-160, domainstatus.py:212-218, service.py:325-326), while the device backends behind ~90% of recorded actions (23,963 of 26,737 action streams are cam_/ring_/cast_/tv_/dash_ tools, dominated by the dashboard's 22,849 ring_live signalling calls) - reolink_aio, ring_doorbell, pychromecast, androidtvremote2, ffmpeg, osascript - have `available()` checks that run only inside a tool call, are never registered as probes (register_connector has no callers; the ledger's capabilities stream has never recorded one), and are absent from requirements.txt. The status screen and the TOOL_PROBED/TOOL_UNAVAILABLE consumers in orchestration and worldmodel therefore only ever learn about the rarely-used half.

### evidence

- simorgh/execution/capabilities.py:154-160 — PROBES = (node, puppeteer, bandit, homeharvest, docker); Probe dataclass at :60-66 has a `tools` field for naming what breaks
- simorgh/execution/domainstatus.py:203-218 — domain_connectors() returns Knowledge, Home, Energy, Media, Security connectors only
- simorgh/execution/service.py:325-326 — `probes = PROBES + tuple(connector_probe(c) for c in self._connectors)`; :318-321 register_connector defined; `grep -rn register_connector simorgh` shows no caller
- simorgh/execution/home/cameras.py:56-61, home/ring.py:58-63, media/cast.py:41, media/androidtv.py:57, media/musicapp.py:46 — available() via find_spec/shutil.which; call sites only in run paths: cameras.py:270,373; ring.py:352,503; cast.py:396; androidtv.py:135
- ~/.simorgh/ledger/streams/capabilities.jsonl (1.0 MB, last write Sep 17 19:57) — distinct probe names recorded: audio-playback, bandit, connector:energy, connector:home, connector:knowledge, connector:media, connector:security, docker, homeharvest, microphone, node, puppeteer, text-to-speech; none for reolink/ring/cast/androidtv/ffmpeg
- python3 count over ~/.simorgh/ledger/streams/action%3A*.jsonl first-line payload.proposal.tool: actions 26737, device-prefixed 23963; top: 22849 ring_live (proposed_by interface:dash, WebRTC offer), 721 cam_stream, 570 run_shell, 114 cast_show, 53 cast_play, 42 cast_devices, 42 dash_view, 29 render_page
- requirements.txt — lists google-genai, prompt-toolkit, pypdf, pytest-xdist, homeharvest, python-docx, openpyxl, Pillow, pytesseract, apprise; no reolink-aio, ring_doorbell, pychromecast or androidtvremote2
- simorgh/orchestration/service.py:108 subscribes TOOL_PROBED; simorgh/worldmodel/service.py:114-115 subscribes TOOL_UNAVAILABLE and TOOL_PROBED — the consumers that would carry a device probe into the prompt/status exist
- simorgh/voice/service.py:128 — the voice subsystem publishes its own probe rows (audio-playback etc.) into the same stream, showing a second path a device module could use but does not

**severity adjustment:** keep

