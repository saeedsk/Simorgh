# refute:proportionality:Boot probes cover the libraries that are

*Workflow: review · Phase: Refute · Agent id: `a05b54cd03bbe5ff0` · Tool calls: 11*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "tools-domains-integrations". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/execution/capabilities.py | 1 """Which of Sim's capabilities actually work right now. 2 3 Half of the toolset added on 2026-09-09 stands on something outside 4 this repository: Node and a  |
| 2 | Bash | Show cited code in domainstatus, cameras, ring and requirements |  from .security.findings import FindingStore with FindingStore(path) as store: counts = store.counts() open_now = len(store.open_findings()) except Exception as |
| 3 | Bash | Read domain connector probes and where probes are wired at boot | """Is each domain switched on, and does it actually work? `capabilities` answers that for Node and Docker. It could not answer it for the six domains, because a |
| 4 | Bash | Find where boot assembles the probe list | (eval):1: no matches found: --include=*.py |
| 5 | Bash | List available() functions and device-lib guards across execution | Exit code 1 (eval):1: no matches found: --include=*.py |
| 6 | Bash | Count recorded tool calls per tool in the ledger to check the '23,800 calls' claim | Exit code 1 benchmark benchmark-waves benchmarks bus cognition curiosity execution guardian interface learning ledger memory orchestration persona planning refl |
| 7 | Bash | Find probe wiring, available() functions, device guards and ledger streams | simorgh/execution/service.py:55:from .capabilities import CAPABILITIES_STREAM, PROBES, connector_probe, degraded_detail, run_probes simorgh/execution/service.py |
| 8 | Bash | Read boot probe wiring, per-call availability gates, ffmpeg guards, non-action ledger streams | from .vision import CameraVision from .tools import RunTestsTool, SkillTool, builtin_tools from .worktree import WorktreeManager, worktree_tools from .verifier  |
| 9 | Bash | Count recorded tool calls per tool and show the last capability probe results |  20110 /Users/saeed/.simorgh/ledger/streams/execution%3Atools.jsonl 3477 /Users/saeed/.simorgh/ledger/streams/capabilities.jsonl 23587 total lines 20110 kinds [ |
| 10 | Bash | Check for device connectors, which device libs are installed now, camera/TV config, and how status reads probe results | ---REGISTER_CONNECTOR--- simorgh/execution/service.py:317: def register_connector(self, connector) -> None: simorgh/execution/pim/connectors/caldav.py:81:class  |
| 11 | Bash | Confirm what execution:tools records, whether voice probes ffmpeg, and how a camera tool refuses | {"causation_id":null,"idempotency_key":null,"payload":{"name":"read_file","provider":"builtin","read_only":true,"reversibility":"read_only"},"seq":1,"stream":"e |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The structural gap is real but the headline numbers are wrong. Verified: simorgh/execution/capabilities.py:153-159 defines exactly five PROBES (node, puppeteer, bandit, homeharvest, docker); simorgh/execution/service.py:325 assembles `PROBES + connector_probe(c) for c in self._connectors`, and the only connectors ever registered are the five domain connectors from domainstatus.py:211-215 plus per-account pim connectors (service.py:297-313); grep shows no other class registers via `register_connector`. The device modules each have a free `available()` (home/cameras.py:56, home/ring.py:58, media/cast.py:41, media/androidtv.py:57, media/musicapp.py:46) that is only called inside tool execution (cameras.py:270,373; ring.py:352,503; cast.py:396; androidtv.py:135; musicapp.py:170), raising/refusing at call time. requirements.txt names none of reolink-aio, ring_doorbell, pychromecast, androidtvremote2. So "discovered only by refusal at call time" is correct for the four device SDKs and osascript. ffmpeg is partially covered: voice/service.py:113-114 folds it into the `microphone` probe (ok if sounddevice OR ffmpeg), so a missing ffmpeg would not show as a camera-HLS failure — the finding is right that it is not probed for cameras. However the load-bearing claim "the dependencies behind ~23,800 recorded calls" / "99% of calls" is false. The 23,587 figure is `wc -l` of execution:tools.jsonl (20,110) + capabilities.jsonl (3,477). Every one of the 20,110 execution:tools events is type "registered" (service.py:173,454,661 — one event per tool per boot); counting by name gives 251 per builtin tool (=251 boots) and 102-226 per device tool, i.e. device tools are 5,460/20,110 = 27% of REGISTRATIONS, not 99% of calls. No invocation counts were examined. Also, all four device libs are currently installed and REOLINK_*/RING_* secrets and cast_device are configured (~/.simorgh/simorgh.toml:19-20), so the failure scenario is hypothetical today. Scale lens: for one laptop the recommendation is proportionate — five Probe entries reusing existing `available()` plus a requirements block is ~30 lines that fit the existing pattern exactly and fix a textbook "unconnected wire". It is a low-severity gap, not an architectural error; the design (probe table + refuse-by-name floor) is right, the implementation just left the newest half of the toolset out of the table.

### evidence

- simorgh/execution/capabilities.py:153-159 — PROBES tuple: node, puppeteer, bandit, homeharvest, docker only
- simorgh/execution/service.py:325-326 — `probes = PROBES + tuple(connector_probe(c) for c in self._connectors)`; connectors come only from domainstatus.domain_connectors (service.py:297-299) and pim build_all (service.py:307-313)
- simorgh/execution/domainstatus.py:211-217 — domain_connectors = Knowledge, Home, Energy, Media, Security; Media/Home both go through Home Assistant, none touches reolink/ring/cast/androidtv
- grep 'register_connector\|class .*Connector' simorgh → only pim/connectors/caldav.py:81 and imap.py:93 define extra connectors
- grep 'def available(' simorgh/execution → home/ring.py:58, home/cameras.py:56, media/androidtv.py:57, media/cast.py:41, media/musicapp.py:46; each called only inside tool paths (cameras.py:270,373; ring.py:352,503; cast.py:396; androidtv.py:135; musicapp.py:170)
- simorgh/execution/home/cameras.py:268-272 — `ok, why = available(); if not ok: raise RuntimeError(why)` at first NVR use, i.e. refusal at call time
- simorgh/voice/service.py:113-114 — ffmpeg is only a fallback inside the 'microphone' probe; `mic.append('ffmpeg')` alongside sounddevice, so a missing ffmpeg does not fail any probe while sounddevice is present
- requirements.txt — full read: lists google-genai, prompt-toolkit, pypdf, pytest-xdist, homeharvest, python-docx, openpyxl, Pillow, pytesseract, apprise; no reolink-aio, ring_doorbell, pychromecast, androidtvremote2
- wc -l ~/.simorgh/ledger/streams/execution%3Atools.jsonl capabilities.jsonl → 20110 + 3477 = 23587 (the finding's '~23,800')
- python count of execution:tools.jsonl → all 20110 events have type 'registered'; 251 per builtin tool, device tools 102-226 each; device-tool registrations total 5460 (27%), so '99% of calls' is a misread of registration events (service.py:173,454,661 write 'registered' on every boot)
- python -c find_spec → reolink_aio True, ring_doorbell True, pychromecast True, androidtvremote2 True; shutil.which ffmpeg=/opt/homebrew/bin/ffmpeg, osascript=/usr/bin/osascript — nothing is missing today
- ~/.simorgh/simorgh.toml:19-20 — REOLINK_*/RING_* secrets and cast_device = 'Family Room TV' configured
- tail of capabilities.jsonl (last boot) — probes recorded: docker, connector:knowledge/home/energy/media/security, speech-to-text, text-to-speech, microphone, audio-playback, node, puppeteer, bandit, homeharvest; no cameras/ring/cast/tv row

**corrected claim:** The boot probe table (capabilities.py:153-159 plus the five HA-centric domain connectors in domainstatus.py:211-217) covers node/puppeteer/bandit/homeharvest/docker and Home Assistant, but not the four device SDKs (reolink_aio, ring_doorbell, pychromecast, androidtvremote2) nor osascript, whose `available()` checks exist but run only inside tool execution; ffmpeg is probed only as an alternative microphone path (voice/service.py:113-114), not for camera HLS. requirements.txt omits all four device libraries. The '~23,800 recorded calls' figure is not call volume: it is 20,110 tool-*registration* events (one per tool per boot, ~251 boots) plus 3,477 capability-probe lines; device tools are ~27% of registrations and no call counts were measured. All the libraries are installed and configured on this machine today, so the gap is latent, not a live fault.

**severity adjustment:** keep

