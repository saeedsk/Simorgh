# Sourcebook: data you can get without a key

Written 2026-09-09, from the post-mortem in
`docs/plans/resourcefulness-toolset.md`. The failure it exists to
prevent: asked for real data, Sim answered "no API is configured" and
built the page against placeholder rows. Most public data needs no key
at all, and Sim had no way to know that -- `web_search` finds pages,
not endpoints, and nothing in the prompt said "these exist".

Every row below is a real, keyless HTTP endpoint. `web_fetch` returns a
JSON body verbatim (it only extracts text from HTML), so a `GET` here
is one tool call away from usable data. For anything that needs
parsing, filtering or maths, fetch it in `run_script`, where pandas is
importable and the repo is on the path.

**The honesty rule applies to all of it.** Say where a number came
from and when you fetched it. An unofficial endpoint (marked below)
can break or rate-limit without warning -- that is a caveat to
disclose, not a reason to refuse.

## Geography and places

| what | endpoint | notes |
|---|---|---|
| Address -> lat/lng | use the `geocode` tool | Nominatim, already wired; ~1 req/s |
| Reverse geocode | `https://nominatim.openstreetmap.org/reverse?lat=37.3&lon=-121.9&format=json` | send a real User-Agent |
| Arbitrary OSM features | `https://overpass-api.de/api/interpreter?data=[out:json];node(37.2,-121.9,37.3,-121.8)[amenity=cafe];out;` | heavy queries are throttled |
| Elevation | `https://api.open-elevation.com/api/v1/lookup?locations=37.3,-121.9` | |

## Weather and environment

| what | endpoint | notes |
|---|---|---|
| Forecast | `https://api.open-meteo.com/v1/forecast?latitude=37.3&longitude=-121.9&hourly=temperature_2m` | no key, generous limits |
| History | `https://archive-api.open-meteo.com/v1/archive?latitude=37.3&longitude=-121.9&start_date=2026-01-01&end_date=2026-01-31&daily=temperature_2m_max` | |
| Air quality | `https://air-quality-api.open-meteo.com/v1/air-quality?latitude=37.3&longitude=-121.9&hourly=pm2_5` | |
| Earthquakes | `https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2026-09-01&minmagnitude=4` | |

## Reference and research

| what | endpoint | notes |
|---|---|---|
| Wikipedia summary | `https://en.wikipedia.org/api/rest_v1/page/summary/San_Jose,_California` | |
| Wikipedia search | `https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=X&format=json` | |
| Wikidata entity | `https://www.wikidata.org/wiki/Special:EntityData/Q16553.json` | |
| arXiv | `http://export.arxiv.org/api/query?search_query=all:transformer&max_results=5` | Atom XML, not JSON |
| Semantic Scholar | `https://api.semanticscholar.org/graph/v1/paper/search?query=llm+agents&fields=title,year,abstract` | keyless tier is rate-limited |
| Open Library | `https://openlibrary.org/search.json?q=the+idiot` | |

## Software and packages

| what | endpoint | notes |
|---|---|---|
| PyPI / npm | use the `find_package` tool | already wired |
| GitHub REST | `https://api.github.com/repos/psf/requests` | 60 req/h unauthenticated |
| GitHub code search | needs a token (`GITHUB_TOKEN`) | not keyless |

## Government, civic and financial

| what | endpoint | notes |
|---|---|---|
| SEC filings | `https://data.sec.gov/submissions/CIK0000320193.json` | User-Agent with contact required |
| US Census | `https://api.census.gov/data/2020/dec/pl?get=NAME,P1_001N&for=county:085&in=state:06` | keyless for small queries |
| FX rates | `https://open.er-api.com/v6/latest/USD` | |
| Stock/quote data | `yfinance` (pip) | **unofficial**: reads Yahoo's own backend; can break |

## Consumer and misc

| what | endpoint | notes |
|---|---|---|
| Hacker News | `https://hacker-news.firebaseio.com/v0/topstories.json` | |
| Reddit | append `.json` to any listing URL | User-Agent required; rate-limited |
| Open Food Facts | `https://world.openfoodfacts.org/api/v2/product/737628064502.json` | |
| NASA | `https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY` | DEMO_KEY works, heavily limited |

## Not keyless, and not scrapeable either

Worth knowing so you do not spend steps discovering it:

- **Zillow** has no public API and a well-defended backend. `search_listings`
  is Realtor.com-derived and explicitly not Zillow; if someone asks for
  Zillow parity, say that plainly.
- **Google Search / Maps** need billing-backed keys.
- **LinkedIn, Instagram, X** actively block automated reads.

For real-estate listings use the `search_listings` tool, which already
wraps `homeharvest` and discloses its own limits in every result.
