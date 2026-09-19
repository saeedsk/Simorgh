# refute:proportionality:Camera stills and live HLS of the house

*Workflow: review · Phase: Refute · Agent id: `a7059cb316bc9f262` · Tool calls: 4*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "voice-interface-surfaces". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "Camera stills and live HLS of the house are served without the token on a 0.0.0.0 bind",
    "kind": "wrong-design",
    "severity": "high",
    "claim": "With `http_host = \"0.0.0.0\"` live, any device on the LAN can list the cameras (`/api/dash/streams` is in `_OPEN_ROUTES`) and fetch the newest still of every camera and the live HLS video without the token, because those prefixes are open so the Cast receiver can fetch them header-less; the bearer token is also placed in URLs.",
    "evidence": [
      "simorgh/interface/httpapi.py:77-79 `_OPEN_ROUTES` includes \"/api/dash/streams\", \"/api/dash/data\", \"/api/dash/state\", \"/api/dash/keys\"",
      "httpapi.py:921 `open_ = prefix in (\"/tv/hls/\", \"/tv/media/\", \"/wallpapers/\", \"/cameras/snap/\")` ; httpapi.py:208-212 comment: 'Served on the LAN without the token: the Cast receiver fetches segments with no header and no query of its own'",
      "httpapi.py:540-562 `_snap` returns the newest JPEG for `/cameras/snap/<camera>`; httpapi.py:541-546 `_hls` returns `.m3u8`/`.ts` from workspace/cameras/hls; dashfeeds.py:985-986 builds `\"url\": prefix + urllib.parse.quote(safe)` into the open `/api/dash/streams` reply",
      "~/.simorgh/simorgh.toml: `[interface]\\nhttp_host = \"0.0.0.0\"`; ~/.simorgh/secrets.toml contains key `SIM_API_TOKEN` (value not read); `du -sh workspace/cameras` -> 3.8G",
      "Token in URL: httpapi.py:938-948 302-redirects a local viewer of `/dash` to `/dash?token=<token>`; httpapi.py:609-610 `_authorized` accepts `?token=`; the TV is handed a URL containing the token"
    ],
    "why_it_matters": "For one family on one LAN this is a modest exposure, but it is the single most sensitive data the system holds (the inside of the house, live) and it is the only class of data served with no check at all; guest Wi-Fi, a compromised IoT device or a child's friend's phone gets it. A bearer token in a URL also ends up in browser history and in the `Referer` of any link the dash page opens.",
    "recommendation": "Keep the Cast exception but make it a capability, not a public path: mint a per-boot random segment (`/tv/hls/<secret>/...`, `/cameras/snap/<secret>/...`) that only the token-gated `/api/dash/streams` reply and the TV URL carry, and 404 without it. Move `/api/dash/streams` (which enumerates cameras) behind the token. For browsers on this machine, set the token as an `HttpOnly; SameSite=Strict` cookie from `/dash` instead of a query redirect, and keep `?token=` only for the TV. Consider defaulting `http_host` back to loopback plus an explicit LAN opt-in that logs which peers fetched HLS.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read cited regions of httpapi.py | #: Routes that answer without a token even when one is configured. #: `/` is the page that *carries* the token to the browser, so gating it #: would make the da |
| 2 | Bash | Check config, dashfeeds URL build, bind default, headers | 16:http_host = "0.0.0.0" 19:secrets = ["vault:*", "SIM_API_TOKEN", "REOLINK_HOST", "REOLINK_USERNAME", "REOLINK_PASSWORD", "RING_TOKEN", "RING_USERNAME"] 1 ---- |
| 3 | Bash | Check streams route, LAN warning, dash page links |  self.register_route("POST", "/api/dash/cameras/main", _cameras_main, max_body=1024, rate=(30, 60.0)) self.register_route("POST", "/api/dash/youtube", _youtube_ |
| 4 | Bash | Check tests, dash data contents, referrer policy, cast URL | (eval):1: no matches found: --include=*.py ---- 77:_OPEN_ROUTES: frozenset[str] = frozenset({"/", "/api/status", "/tv", "/dash", "/api/wallpapers", "/api/dash/d |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core facts check out against the code as it is today. `_OPEN_ROUTES` (httpapi.py:77-79) lists `/api/dash/streams`, `/api/dash/data`, `/api/dash/state`, `/api/dash/keys`; `_streams` is registered with `auth=False` (httpapi.py:474) and returns `self._feeds.streams()` plus `cameras()` and `ring_cameras()`, i.e. an enumeration of every camera with a ready URL. The prefix dispatcher marks `/tv/hls/`, `/tv/media/`, `/wallpapers/`, `/cameras/snap/` as `open_` (httpapi.py:921), so `_snap` (httpapi.py:557-576) hands back the newest JPEG of any named camera and `_hls` serves the live playlist and segments with no check. `/api/dash/data` is also open and its body includes the same `cameras`/`streams`/`ring_cameras` lists (dashfeeds.py:1100-1102). The live config binds `http_host = "0.0.0.0"` and a `SIM_API_TOKEN` exists, so the token gate is on for everything except exactly this class of data. The comments at httpapi.py:208-212 and :559-561 show it is a deliberate choice made for the Cast receiver, not an accident, and service.py:296-301 only warns for the no-token-off-loopback case, never for "token set but camera paths open". The one piece of the claim that is overstated is the Referer leak: the dash page's only cross-origin loads are Google Fonts (default browser policy strict-origin-when-cross-origin strips the query) and a YouTube iframe that explicitly sets `referrerpolicy="strict-origin-when-cross-origin"` (dash.html:339), so the `?token=` does not travel in Referer under a current browser; it does land in browser history and the local-viewer 302 (httpapi.py:938-948) is real. On the scale lens: this is a one-LAN exposure, but it is the interior of the house live, it is the only data class with zero check, and the cheap part of the recommendation (a per-boot random path segment carried only by the token-gated URLs, which relative HLS segment URLs inherit for free) is a few lines and costs nothing at runtime. Moving `/api/dash/streams` behind the token is also cheap because the TV page is already handed `?token=` and its own JS fetches could carry it. The cookie/HttpOnly part and the loopback-default-plus-peer-logging part are disproportionate for one laptop and one family and would add more surface than they remove; the finding should be trimmed to the secret-path-segment fix. Severity is better placed at medium: deliberate, documented, LAN-only, and mitigated in under an hour.

### evidence

- simorgh/interface/httpapi.py:77-79 `_OPEN_ROUTES` contains "/api/dash/data", "/api/dash/state", "/api/dash/keys", "/api/dash/streams"
- simorgh/interface/httpapi.py:474 `self.register_route("GET", "/api/dash/streams", _streams, auth=False)`; :467-470 the body includes `self._feeds.streams()`, `self._feeds.cameras()`, `self._feeds.ring_cameras()`
- simorgh/interface/httpapi.py:921 `open_ = prefix in ("/tv/hls/", "/tv/media/", "/wallpapers/", "/cameras/snap/")` and :922 `auth=not open_`
- simorgh/interface/httpapi.py:557-576 `_snap` returns the newest `<safe>-*.jpg` from workspace/cameras for any camera name, no auth; :208-212 comment 'Served on the LAN without the token: the Cast receiver fetches segments with no header and no query of its own'
- simorgh/interface/dashfeeds.py:1017 streams entries carry `"url": f"/tv/hls/{folder.name}/index.m3u8"`; :985-986 stills carry `"url": prefix + urllib.parse.quote(safe)`; :1100-1102 `/api/dash/data` snapshot also includes cameras/streams/ring_cameras
- grep ~/.simorgh/simorgh.toml -> line 16 `http_host = "0.0.0.0"`; `grep -c SIM_API_TOKEN ~/.simorgh/secrets.toml` -> 1; simorgh/interface/config.py:89 default is `http_host: str = "127.0.0.1"` (the LAN bind is the creator's explicit opt-in)
- simorgh/interface/service.py:296-301 warns `http_api_unauthenticated` only when there is NO token off-loopback; no warning covers the token-set-but-camera-paths-open state
- simorgh/interface/httpapi.py:938-948 302 to `/dash?token=<token>` for a loopback viewer; :609-610 `_authorized` accepts `?token=`
- Referer overstated: simorgh/interface/static/dash.html:339 YouTube iframe sets `referrerpolicy="strict-origin-when-cross-origin"`; only other cross-origin loads are Google Fonts (dash.html:3-5), which under the browser default policy receive origin only, not the query
- `du -sh workspace/cameras` -> 3.8G; directory holds per-camera stills like `Backyard_Door_Left-20260916-203917.jpg`

**corrected claim:** With `http_host = "0.0.0.0"` and a token set, every route is gated except the camera class: `/api/dash/streams` and `/api/dash/data` (both in `_OPEN_ROUTES`) enumerate every camera with ready URLs, and `/cameras/snap/<camera>` and `/tv/hls/...` serve the newest still and the live HLS video to any LAN peer with no check, by a deliberate, commented choice made so the Cast receiver can fetch header-less. The bearer token is also placed in the `/dash?token=` URL (browser history), though it does not leak via Referer because the page's cross-origin loads use strict-origin-when-cross-origin. The proportionate fix is a per-boot random path segment on the HLS/snap prefixes carried only by token-gated replies and the TV URL, plus gating `/api/dash/streams`; the cookie and loopback-default parts of the original recommendation are more than this scale needs.

**severity adjustment:** lower

