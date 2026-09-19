# refute:correctness:Camera stills and live HLS of the house

*Workflow: review · Phase: Refute · Agent id: `abb4655fd5869f9a2` · Tool calls: 3*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "voice-interface-surfaces". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Read the cited httpapi.py regions | _STATIC_DIR = Path(__file__).resolve().parent / "static" _REASONS = { 200: "OK", 206: "Partial Content", 302: "Found", 400: "Bad Request", 401: "Unauthorized",  |
| 2 | Bash | Check remaining evidence: streams route, dashfeeds URL, config, disk size, default host | 77:_OPEN_ROUTES: frozenset[str] = frozenset({"/", "/api/status", "/tv", "/dash", "/api/wallpapers", "/api/dash/data", 230: `auth=True` (the default, and the onl |
| 3 | Bash | Read streams/snap handlers, service warning, and check prior reviews for overlap |  return 400, b'{"error": "action is start or stop"}', "application/json" camera = str(asked["camera"]).strip()[:80] args = {"camera": camera, "mode": "dash" if  |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line is true of the code today. `/api/dash/streams` is registered with `auth=False` (httpapi.py:474) and is in `_OPEN_ROUTES` (httpapi.py:77-79); its handler returns `self._feeds.streams()`, `cameras()` and `ring_cameras()` with per-camera `url` fields built by dashfeeds.py:985-986, so an unauthenticated LAN peer gets the full camera inventory plus the exact still/HLS URLs. The prefix dispatcher sets `auth=not open_` where `open_` is true for `/tv/hls/`, `/tv/media/`, `/wallpapers/`, `/cameras/snap/` (httpapi.py:921-923), and `_snap` (httpapi.py:557-579) returns the newest JPEG bytes with no other gate; `_hls` is registered at httpapi.py:540 the same way. The only check the token gate performs is `_authorized` (httpapi.py:603-612), which is skipped when `route.auth` is False. The live config binds `http_host = "0.0.0.0"` (~/.simorgh/simorgh.toml:16) and a SIM_API_TOKEN exists, so the token path is the one in force; `workspace/cameras` is 3.8G with HLS channel dirs present. The `/dash` 302 (httpapi.py:938-948) really does append `token=<token>` to the Location, and `_local_viewer` correctly limits that redirect to loopback peers with a loopback Host header, but the token still lands in the browser URL/history and is the URL the TV is handed. service.py:296-302 warns only for a no-token off-loopback bind; a token-set LAN bind with open camera prefixes logs nothing. Not in the known-findings list: prior reviews (architecture-audit-2026.md:19, architecture-review-2026-09-18.html:93-97, third-opinion:124) discuss the local ffmpeg/HLS relay purely as a "Sim speaks to Home Assistant" boundary violation, not as an unauthenticated exposure. Classification as wrong-design is fair: the Cast receiver's header-less fetch is a real constraint, but the code chose a public path prefix rather than an unguessable capability, and the comment at httpapi.py:208-212 shows this was deliberate. One small nuance the reader did not stress: `/api/dash/data` and `/api/dash/state` are also open, so more than camera data is exposed, which if anything strengthens the finding.

### evidence

- simorgh/interface/httpapi.py:77-79 `_OPEN_ROUTES` frozenset contains "/api/dash/data", "/api/dash/state", "/api/dash/keys", "/api/dash/streams"
- simorgh/interface/httpapi.py:242 `auth=auth and not (path in _OPEN_ROUTES and method == "GET")`; line 474 `self.register_route("GET", "/api/dash/streams", _streams, auth=False)`
- simorgh/interface/httpapi.py:464-472 `_streams` returns `self._feeds.streams()`, `cameras()`, `ring_cameras()` with no token check
- simorgh/interface/httpapi.py:921-923 `open_ = prefix in ("/tv/hls/", "/tv/media/", "/wallpapers/", "/cameras/snap/")` ... `auth=not open_`
- simorgh/interface/httpapi.py:557-579 `_snap` returns `newest.read_bytes(), "image/jpeg"` for `/cameras/snap/<camera>`; line 540 `self._prefixes.append(("GET", "/tv/hls/", _hls))`
- simorgh/interface/httpapi.py:208-212 comment: 'Served on the LAN without the token: the Cast receiver fetches segments with no header and no query of its own'
- simorgh/interface/httpapi.py:938-948: local viewer of `/dash` without token gets 302 to `/dash?token=<token>`; line 611-612 `_authorized` accepts `?token=` query
- simorgh/interface/dashfeeds.py:985-986 `"url": prefix + urllib.parse.quote(safe)` in the cameras list returned by the open streams route
- simorgh/interface/config.py:89 default `http_host: str = "127.0.0.1"`; `grep http_host ~/.simorgh/simorgh.toml` -> `http_host = "0.0.0.0"`; `grep -c SIM_API_TOKEN ~/.simorgh/secrets.toml` -> 1
- `du -sh workspace/cameras` -> 3.8G; `ls workspace/cameras/hls` -> channel dirs 1, 1-main, 10, 10-main, 11, 11-main, 5, 5-main, 6, 6-main
- simorgh/interface/service.py:296-302 warns `http_api_unauthenticated` only when no token AND off-loopback; open camera prefixes on a token-set LAN bind are never logged
- Prior reviews (docs/architecture-audit-2026.md:19, docs/architecture-review-2026-09-18.html:93-97, docs/architecture-third-opinion-2026-09-18.md:124) mention HLS only as a Home-Assistant-boundary violation, not the missing auth

**severity adjustment:** keep

