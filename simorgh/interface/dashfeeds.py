"""The dashboard's collector: what the TV page shows that is not Sim
itself (interface/static/dash.html, served at `/dash`).

Until 2026-09-12 every panel but the terminal was a JavaScript array:
made-up headlines, a seeded random walk labelled "sample series", a
weather tile that always said 72 degrees. The creator asked for the
real thing -- "scrape Bloomberg and replicate it" for markets, and
"more elements" everywhere. This module is that collector: a set of
feeds, each a pure parser over the bytes one public endpoint returns,
run on its own cadence by one background task, merged into one JSON
snapshot the page polls at `/api/dash/data`.

Sources (all keyless, all reachable from the creator's LAN on
2026-09-12; each is named in the snapshot so the page can credit it):

    markets    CNBC's quote service (stocks, indices, rates, FX,
               commodities, crypto -- one call) and its bar API for the
               price history; Nasdaq's API is a second opinion nobody
               needs yet. Bloomberg itself answers every request with
               "Are you a robot?", so what is Bloomberg's here is its
               own RSS: the markets, technology, business, economics and
               politics headline feeds at feeds.bloomberg.com.
    news       Bloomberg (above), BBC World, Ars Technica, ScienceDaily,
               NASA, Variety, Deadline -- RSS, one parser.
    weather    Open-Meteo forecast + air quality for the configured
               place ([interface] dash_place / dash_latitude /
               dash_longitude; San Jose by default).
    charts     Apple's most-played songs, the iTunes top movies, The
               Numbers' weekend box office table (Box Office Mojo sends
               a page with no table to anything that is not a browser).
    wiki       Wikipedia's featured feed: today's article, the picture
               of the day, "on this day", the most-read pages.
    apod       NASA's Astronomy Picture of the Day (DEMO_KEY, once a day).
    hn         Hacker News top stories.
    jokes      icanhazdadjoke.
    quote      ZenQuotes' quote of the day.
    ambient    long 4K relaxation films from YouTube's results page, for
               the Home view's big frame when nothing is playing.

Every fetch runs in a worker thread with a timeout; a feed that fails
keeps its last good value and records the error in `feeds[name]`, so
the page can say "stale since ..." instead of inventing numbers. This
is a collector, not a tool: it acts on nothing, and it is not offered
to the model -- Guardian's "see every call" rule covers actions, and a
GET of a public quote page that no model chose is not one. It is off
with `[interface] dash_feeds = false`.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

Fetcher = Callable[..., bytes]   # fetch(url, *, accept="...") -> bytes

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) "
              "Version/17.5 Safari/605.1.15")


def fetch(url: str, *, timeout: float = 12.0, accept: str = "*/*") -> bytes:
    """One GET, browser-shaped headers, a hard timeout. Follows redirects
    (Bloomberg's feed host answers 301 first)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept,
                                                   "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- public read-only endpoints
        return response.read(8_000_000)


# -- the watchlist -----------------------------------------------------------------------------------

#: The creator's 15-name tech watchlist (2026-09-12), each with its
#: business in a few words. Symbols not in this table still work: the
#: quote service supplies a name and the description stays blank.
WATCHLIST: dict[str, tuple[str, str]] = {
    "NVDA": ("NVIDIA", "AI infrastructure & graphics chips"),
    "AAPL": ("Apple", "Consumer electronics, software & services"),
    "MSFT": ("Microsoft", "Cloud, enterprise software & AI"),
    "GOOGL": ("Alphabet", "Search, cloud & AI platforms"),
    "AMZN": ("Amazon", "E-commerce & AWS cloud"),
    "AVGO": ("Broadcom", "Semiconductors & infrastructure software"),
    "META": ("Meta Platforms", "Social networks & advertising"),
    "MU": ("Micron", "Memory & storage"),
    "AMD": ("AMD", "Processors, graphics & adaptive computing"),
    "INTC": ("Intel", "Semiconductor manufacturing & processors"),
    "CSCO": ("Cisco", "Networking & telecom equipment"),
    "ORCL": ("Oracle", "Databases & enterprise cloud"),
    "TSM": ("TSMC", "The world's largest chip foundry"),
    "TXN": ("Texas Instruments", "Analog & embedded chips"),
    "QCOM": ("Qualcomm", "Wireless technology & mobile processors"),
}
DEFAULT_WATCHLIST: tuple[str, ...] = tuple(WATCHLIST)
#: The five that get the big charts; the rest tile beneath them.
DEFAULT_MAJORS: tuple[str, ...] = ("NVDA", "AAPL", "MSFT", "GOOGL", "AMZN")

INDICES = ((".SPX", "S&P 500"), (".IXIC", "Nasdaq"), (".DJI", "Dow"), (".RUT", "Russell 2000"), (".VIX", "VIX"),
           (".FTSE", "FTSE 100"), (".GDAXI", "DAX"), (".STOXX50E", "Euro Stoxx 50"), (".N225", "Nikkei 225"),
           (".HSI", "Hang Seng"))
RATES = (("US2Y", "US 2Y"), ("US10Y", "US 10Y"), ("US30Y", "US 30Y"))
FX = (("EUR=", "EUR/USD"), ("GBP=", "GBP/USD"), ("JPY=", "USD/JPY"), ("CHF=", "USD/CHF"), ("CAD=", "USD/CAD"),
      ("CNY=", "USD/CNY"))
COMMODITIES = (("@CL.1", "WTI Crude"), ("@BZ.1", "Brent"), ("@GC.1", "Gold"), ("@SI.1", "Silver"),
               ("@NG.1", "Nat Gas"), ("@HG.1", "Copper"))
CRYPTO = (("BTC.CM=", "Bitcoin"), ("ETH.CM=", "Ether"), ("SOL.CM=", "Solana"))
#: Index and crypto series the Home ticker sparks.
SPARK_EXTRA: tuple[str, ...] = (".SPX", ".IXIC", ".DJI", "BTC.CM=")

CNBC_QUOTE = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols={symbols}"
              "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json")
CNBC_BARS = "https://ts-api.cnbc.com/harmony/app/bars/{symbol}/{interval}/{start}/{end}/adjusted/EST5EDT.json"
#: timeframe -> (bar interval, how far back, most points kept)
TIMEFRAMES: dict[str, tuple[str, timedelta, int]] = {
    "1D": ("5M", timedelta(days=4), 240),
    "1W": ("30M", timedelta(days=8), 240),
    "1M": ("1H", timedelta(days=32), 240),
    "1Y": ("1D", timedelta(days=366), 260),
}

RSS_SOURCES: dict[str, tuple[str, str]] = {
    # name: (label, url)
    "bloomberg_markets": ("Bloomberg", "https://feeds.bloomberg.com/markets/news.rss"),
    "bloomberg_technology": ("Bloomberg", "https://feeds.bloomberg.com/technology/news.rss"),
    "bloomberg_business": ("Bloomberg", "https://feeds.bloomberg.com/business/news.rss"),
    "bloomberg_economics": ("Bloomberg", "https://feeds.bloomberg.com/economics/news.rss"),
    "bloomberg_politics": ("Bloomberg", "https://feeds.bloomberg.com/politics/news.rss"),
    "bbc_world": ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    "ars": ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    "sciencedaily": ("ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml"),
    "nasa": ("NASA", "https://www.nasa.gov/feed/"),
    "variety": ("Variety", "https://variety.com/feed/"),
    "deadline": ("Deadline", "https://deadline.com/feed/"),
}

OPEN_METEO = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
              "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m,uv_index,is_day"
              "&daily=temperature_2m_max,temperature_2m_min,weather_code,sunrise,sunset,precipitation_probability_max"
              "&hourly=temperature_2m,weather_code,precipitation_probability"
              "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto&forecast_days=7")
OPEN_METEO_AIR = ("https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}"
                  "&current=us_aqi,pm2_5")
APPLE_SONGS = "https://rss.applemarketingtools.com/api/v2/us/music/most-played/10/songs.json"
ITUNES_MOVIES = "https://itunes.apple.com/us/rss/topmovies/limit=10/json"
BOX_OFFICE = "https://www.the-numbers.com/weekend-box-office-chart"
WIKI_FEATURED = "https://en.wikipedia.org/api/rest_v1/feed/featured/{yyyy}/{mm}/{dd}"
APOD = "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY&thumbs=true"
HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
DAD_JOKES = "https://icanhazdadjoke.com/search?limit=12&page={page}"
ZEN_TODAY = "https://zenquotes.io/api/today"
#: What the Home view's big frame plays when nobody has asked for
#: anything: long, high-resolution relaxation films found on YouTube's
#: own results page (its data is inline; no key). `sp=EgIQAQ` = videos.
YOUTUBE_SEARCH = "https://www.youtube.com/results?search_query={query}&sp=EgIQAQ%253D%253D"
AMBIENT_QUERIES: tuple[str, ...] = ("4k relaxing nature scenery ambient film", "meditation music 4k calm",
                                    "4k travel walking tour scenic", "aerial drone film 4k relaxing music")
AMBIENT_MIN_SECONDS = 30 * 60

#: WMO weather codes -> (short text, glyph)
WMO: dict[int, tuple[str, str]] = {
    0: ("Clear", "☀"), 1: ("Mostly clear", "🌤"), 2: ("Partly cloudy", "⛅"), 3: ("Overcast", "☁"),
    45: ("Fog", "🌫"), 48: ("Rime fog", "🌫"), 51: ("Light drizzle", "🌦"), 53: ("Drizzle", "🌦"), 55: ("Heavy drizzle", "🌧"),
    56: ("Freezing drizzle", "🌧"), 57: ("Freezing drizzle", "🌧"), 61: ("Light rain", "🌦"), 63: ("Rain", "🌧"),
    65: ("Heavy rain", "🌧"), 66: ("Freezing rain", "🌧"), 67: ("Freezing rain", "🌧"), 71: ("Light snow", "🌨"),
    73: ("Snow", "🌨"), 75: ("Heavy snow", "❄"), 77: ("Snow grains", "🌨"), 80: ("Showers", "🌦"), 81: ("Showers", "🌧"),
    82: ("Violent showers", "⛈"), 85: ("Snow showers", "🌨"), 86: ("Snow showers", "❄"), 95: ("Thunderstorm", "⛈"),
    96: ("Thunderstorm, hail", "⛈"), 99: ("Thunderstorm, hail", "⛈"),
}


# -- parsers (pure: bytes in, JSON-able out) -----------------------------------------------------------

def _num(raw: Any) -> float | None:
    """'1,204.50' -> 1204.5; '+2.4%' -> 2.4; 'UNCH' -> 0.0; '' / None -> None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(",", "").replace("%", "").replace("$", "")
    if not text:
        return None
    if text.upper() == "UNCH":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def parse_cnbc_quotes(raw: bytes) -> dict[str, dict]:
    """The quote service's `FormattedQuote` list, keyed by symbol, numbers
    as numbers. A symbol the service does not know (`code != 0`) is
    left out rather than shown as a row of Nones."""
    data = json.loads(raw.decode("utf-8", errors="replace"))
    quotes = data.get("FormattedQuoteResult", {}).get("FormattedQuote", [])
    if isinstance(quotes, dict):
        quotes = [quotes]
    out: dict[str, dict] = {}
    for q in quotes:
        symbol = str(q.get("symbol") or "")
        if not symbol or str(q.get("code", "0")) != "0" or q.get("last") in (None, ""):
            continue
        out[symbol] = {
            "symbol": symbol, "name": str(q.get("name") or q.get("altName") or symbol),
            "last": _num(q.get("last")), "change": _num(q.get("change")), "change_pct": _num(q.get("change_pct")),
            "open": _num(q.get("open")), "high": _num(q.get("high")), "low": _num(q.get("low")),
            "prev_close": _num(q.get("previous_day_closing")), "volume": str(q.get("volume_alt") or q.get("volume") or ""),
            "market_cap": str(q.get("mktcapView") or ""), "pe": _num(q.get("pe")), "eps": _num(q.get("eps")),
            "dividend_yield": str(q.get("dividendyield") or ""), "beta": _num(q.get("beta")),
            "year_high": _num(q.get("yrhiprice")), "year_low": _num(q.get("yrloprice")),
            "status": str(q.get("curmktstatus") or ""), "as_of": str(q.get("last_timedate") or ""),
            "currency": str(q.get("currencyCode") or ""), "type": str(q.get("type") or ""),
            "exchange": str(q.get("exchange") or ""),
        }
    return out


def parse_cnbc_bars(raw: bytes, *, timeframe: str) -> list[list[float]]:
    """`[[epoch_ms, close], ...]`, oldest first, thinned to the timeframe's
    cap. `1D` keeps only the most recent session present (the request
    spans a few days so a Monday morning still shows Friday)."""
    data = json.loads(raw.decode("utf-8", errors="replace"))
    bars = data.get("barData", {}).get("priceBars", []) or []
    points: list[list[float]] = []
    for bar in bars:
        close = _num(bar.get("close"))
        ms = bar.get("tradeTimeinMills")
        if close is None or ms is None:
            continue
        points.append([float(ms), close])
    points.sort(key=lambda p: p[0])
    if timeframe == "1D" and points:
        # The bar API stamps EST5EDT session days; the last day's bars
        # are those sharing the final bar's tradeTime date prefix.
        # ... and not a stray Saturday bar: the last day with a
        # session's worth of them (S&P futures print one at 07:10).
        per_day: dict[str, int] = {}
        for bar in bars:
            stamp = str(bar.get("tradeTime") or "")
            if len(stamp) >= 8:
                per_day[stamp[:8]] = per_day.get(stamp[:8], 0) + 1
        full = [d for d, n in per_day.items() if n >= 5] or list(per_day)
        last_day = max(full) if full else None
        if last_day:
            keep = {float(b["tradeTimeinMills"]) for b in bars
                    if str(b.get("tradeTime") or "")[:8] == last_day and b.get("tradeTimeinMills") is not None}
            points = [p for p in points if p[0] in keep]
    cap = TIMEFRAMES.get(timeframe, ("", timedelta(), 240))[2]
    # Whole seconds and four decimals: the page draws, it does not settle trades.
    return [[int(p[0] // 1000), round(p[1], 4)] for p in thin(points, cap)]


def thin(points: list[list[float]], cap: int) -> list[list[float]]:
    """At most `cap` points, evenly spaced, always keeping the last one."""
    if cap <= 0 or len(points) <= cap:
        return points
    step = (len(points) - 1) / (cap - 1)
    out = [points[round(i * step)] for i in range(cap - 1)]
    out.append(points[-1])
    return out


def parse_rss(raw: bytes, *, source: str, limit: int = 12) -> list[dict]:
    """`[{title, link, at, source}]` newest first, from RSS 2.0 or Atom.
    HTML entities in titles are unescaped; a title that is empty is
    skipped."""
    text = raw.decode("utf-8", errors="replace")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    items: list[dict] = []
    ns_atom = "{http://www.w3.org/2005/Atom}"
    for item in list(root.iter("item")) + list(root.iter(f"{ns_atom}entry")):
        title = item.findtext("title") or item.findtext(f"{ns_atom}title") or ""
        title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        if not title:
            continue
        link = (item.findtext("link") or "").strip()
        if not link:
            atom_link = item.find(f"{ns_atom}link")
            link = atom_link.get("href", "") if atom_link is not None else ""
        when = item.findtext("pubDate") or item.findtext(f"{ns_atom}updated") or item.findtext(f"{ns_atom}published") or ""
        at = _when(when)
        thumb = ""
        media = item.find("{http://search.yahoo.com/mrss/}thumbnail")
        if media is None:
            media = item.find("{http://search.yahoo.com/mrss/}content")
        if media is not None:
            thumb = media.get("url", "")
        items.append({"title": title, "link": link, "at": at, "source": source, "thumb": thumb})
    items.sort(key=lambda it: it["at"] or 0, reverse=True)
    return items[:limit]


def _when(text: str) -> float | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_open_meteo(raw: bytes, air: bytes | None, *, place: str) -> dict:
    data = json.loads(raw.decode("utf-8", errors="replace"))
    cur = data.get("current", {}) or {}
    daily = data.get("daily", {}) or {}
    hourly = data.get("hourly", {}) or {}
    code = int(cur.get("weather_code") or 0)
    text, glyph = WMO.get(code, ("", "·"))
    days = []
    for i, day in enumerate(daily.get("time", []) or []):
        dcode = int((daily.get("weather_code") or [0] * 99)[i] or 0)
        days.append({"date": day, "high": (daily.get("temperature_2m_max") or [None] * 99)[i],
                     "low": (daily.get("temperature_2m_min") or [None] * 99)[i],
                     "code": dcode, "text": WMO.get(dcode, ("", "·"))[0], "glyph": WMO.get(dcode, ("", "·"))[1],
                     "rain": (daily.get("precipitation_probability_max") or [None] * 99)[i]})
    hours = []
    now_iso = str(cur.get("time") or "")
    for i, stamp in enumerate(hourly.get("time", []) or []):
        if stamp < now_iso[:13]:
            continue
        hcode = int((hourly.get("weather_code") or [0] * 999)[i] or 0)
        hours.append({"time": stamp, "temp": (hourly.get("temperature_2m") or [None] * 999)[i], "code": hcode,
                      "glyph": WMO.get(hcode, ("", "·"))[1], "rain": (hourly.get("precipitation_probability") or [None] * 999)[i]})
        if len(hours) >= 24:
            break
    out = {
        "place": place, "time": now_iso, "timezone": data.get("timezone", ""),
        "temp": cur.get("temperature_2m"), "feels": cur.get("apparent_temperature"), "code": code, "text": text,
        "glyph": glyph, "wind": cur.get("wind_speed_10m"), "humidity": cur.get("relative_humidity_2m"),
        "uv": cur.get("uv_index"), "is_day": bool(cur.get("is_day", 1)),
        "sunrise": (daily.get("sunrise") or [""])[0], "sunset": (daily.get("sunset") or [""])[0],
        "daily": days, "hourly": hours, "aqi": None, "pm25": None,
    }
    if air:
        try:
            acur = json.loads(air.decode("utf-8", errors="replace")).get("current", {}) or {}
            out["aqi"] = acur.get("us_aqi")
            out["pm25"] = acur.get("pm2_5")
        except (ValueError, AttributeError):
            pass
    return out


def parse_apple_songs(raw: bytes) -> list[dict]:
    data = json.loads(raw.decode("utf-8", errors="replace"))
    out = []
    for i, r in enumerate(data.get("feed", {}).get("results", []) or [], start=1):
        out.append({"rank": i, "name": str(r.get("name") or ""), "artist": str(r.get("artistName") or ""),
                    "art": str(r.get("artworkUrl100") or ""), "url": str(r.get("url") or "")})
    return out


def parse_itunes_movies(raw: bytes) -> list[dict]:
    data = json.loads(raw.decode("utf-8", errors="replace"))
    out = []
    for i, e in enumerate(data.get("feed", {}).get("entry", []) or [], start=1):
        images = e.get("im:image") or []
        art = str(images[-1].get("label", "")) if images else ""
        out.append({"rank": i, "name": str((e.get("im:name") or {}).get("label", "")),
                    "genre": str(((e.get("category") or {}).get("attributes") or {}).get("label", "")),
                    "released": str(((e.get("im:releaseDate") or {}).get("attributes") or {}).get("label", "")),
                    "art": art.replace("60x60", "300x300").replace("100x100", "300x300"),
                    "summary": str((e.get("summary") or {}).get("label", ""))[:220]})
    return out


class _TableRows(HTMLParser):
    """Every `<tr>` of the first `<table>` as a list of cell texts."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._tables = 0
        self._done = False

    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        if tag == "table":
            self._tables += 1
        elif tag == "tr" and self._tables == 1:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if self._done:
            return
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag == "table" and self._tables == 1:
            self._done = True

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_box_office(raw: bytes, limit: int = 10) -> list[dict]:
    """A weekend box office table (The Numbers; Box Office Mojo's has the
    same shape when it sends one): rank, title, weekend gross, total,
    time in release, distributor -- by header name, so a moved column
    does not put a distributor where a gross should be."""
    parser = _TableRows()
    parser.feed(raw.decode("utf-8", errors="replace"))
    rows = parser.rows
    if len(rows) < 2:
        return []
    header = [h.lower() for h in rows[0]]

    def col(*names: str) -> int | None:
        for i, h in enumerate(header):
            if any(n in h for n in names):
                return i
        return None

    c_rank, c_title, c_gross = col("rank"), col("title", "release"), col("gross")
    c_total, c_weeks, c_dist = col("total gross"), col("weeks", "days"), col("distributor")
    c_theaters, c_pct = col("theaters"), col("change", "%± lw", "% lw", "%±")
    age_unit = "days" if c_weeks is not None and "day" in header[c_weeks] else "weeks"
    if c_title is None or c_gross is None:
        return []
    out = []
    for row in rows[1:]:
        if len(row) <= max(c_title, c_gross):
            continue
        title = row[c_title].strip()
        if not title:
            continue
        out.append({
            "rank": row[c_rank].strip() if c_rank is not None and c_rank < len(row) else str(len(out) + 1),
            "title": title, "weekend": row[c_gross].strip(),
            "total": row[c_total].strip() if c_total is not None and c_total < len(row) else "",
            "age": (f"{row[c_weeks].strip()} {age_unit}" if c_weeks is not None and c_weeks < len(row) and row[c_weeks].strip() else ""),
            "theaters": row[c_theaters].strip() if c_theaters is not None and c_theaters < len(row) else "",
            "change": row[c_pct].strip() if c_pct is not None and c_pct < len(row) else "",
            "distributor": row[c_dist].strip() if c_dist is not None and c_dist < len(row) else "",
        })
        if len(out) >= limit:
            break
    return out


def parse_wiki_featured(raw: bytes) -> dict:
    data = json.loads(raw.decode("utf-8", errors="replace"))
    tfa = data.get("tfa") or {}
    image = data.get("image") or {}
    out = {
        "featured": {
            "title": html.unescape(re.sub(r"<[^>]+>", "", str(tfa.get("displaytitle") or tfa.get("title") or ""))),
            "extract": str(tfa.get("extract") or "")[:600],
            "thumb": str(((tfa.get("thumbnail") or {}).get("source")) or ""),
            "url": str(((tfa.get("content_urls") or {}).get("desktop") or {}).get("page", "")),
        },
        "potd": {
            "title": str(image.get("title") or "").replace("File:", ""),
            "url": str(((image.get("image") or {}).get("source")) or ""),
            "thumb": str(((image.get("thumbnail") or {}).get("source")) or ""),
            "description": html.unescape(re.sub(r"<[^>]+>", "", str(((image.get("description") or {}).get("text")) or "")))[:300],
            "artist": html.unescape(re.sub(r"<[^>]+>", "", str(((image.get("artist") or {}).get("text")) or ""))),
        },
        "onthisday": [{"year": e.get("year"), "text": str(e.get("text") or "")[:200]}
                      for e in (data.get("onthisday") or [])[:8]],
        "mostread": [{"title": str(a.get("normalizedtitle") or a.get("title") or "").replace("_", " "),
                      "views": a.get("views"), "extract": str(a.get("extract") or "")[:160],
                      "thumb": str(((a.get("thumbnail") or {}).get("source")) or "")}
                     for a in ((data.get("mostread") or {}).get("articles") or [])[:10]
                     if not str(a.get("title") or "").startswith("Special:")],
    }
    return out


def parse_apod(raw: bytes) -> dict:
    data = json.loads(raw.decode("utf-8", errors="replace"))
    return {"title": str(data.get("title") or ""), "date": str(data.get("date") or ""),
            "media_type": str(data.get("media_type") or ""), "url": str(data.get("url") or ""),
            "hdurl": str(data.get("hdurl") or ""), "thumb": str(data.get("thumbnail_url") or data.get("url") or ""),
            "explanation": str(data.get("explanation") or "")[:700], "copyright": str(data.get("copyright") or "").strip()}


def parse_hn_item(raw: bytes) -> dict | None:
    data = json.loads(raw.decode("utf-8", errors="replace")) or {}
    if not data.get("title"):
        return None
    return {"title": str(data["title"]), "url": str(data.get("url") or f"https://news.ycombinator.com/item?id={data.get('id')}"),
            "score": data.get("score"), "by": str(data.get("by") or ""), "comments": data.get("descendants"),
            "at": data.get("time")}


def parse_dad_jokes(raw: bytes) -> list[str]:
    data = json.loads(raw.decode("utf-8", errors="replace"))
    return [str(r.get("joke") or "").strip() for r in data.get("results", []) or [] if r.get("joke")]


def parse_zen(raw: bytes) -> dict:
    data = json.loads(raw.decode("utf-8", errors="replace"))
    first = data[0] if isinstance(data, list) and data else {}
    return {"text": str(first.get("q") or ""), "author": str(first.get("a") or "")}


def parse_youtube_results(raw: bytes, *, min_seconds: int = AMBIENT_MIN_SECONDS, limit: int = 12) -> list[dict]:
    """The videos on a YouTube results page (`ytInitialData`), long ones
    only: id, title, channel, length, views, thumbnail. Live streams
    count as long."""
    text = raw.decode("utf-8", errors="replace")
    match = re.search(r"var ytInitialData = (\{.*?\});</script>", text, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return []
    out: list[dict] = []
    seen: set[str] = set()

    def runs(node: dict) -> str:
        if not isinstance(node, dict):
            return ""
        if "simpleText" in node:
            return str(node["simpleText"])
        return "".join(str(r.get("text", "")) for r in node.get("runs", []) or [])

    def walk(node) -> None:
        if isinstance(node, dict):
            video = node.get("videoRenderer")
            if isinstance(video, dict) and video.get("videoId") and video["videoId"] not in seen:
                seen.add(video["videoId"])
                length = runs(video.get("lengthText") or {})
                live = not length or any(runs(b.get("metadataBadgeRenderer", {}).get("label", {})) == "LIVE"
                                         for b in video.get("badges", []) or [] if isinstance(b, dict))
                seconds = _hms(length)
                if live or seconds >= min_seconds:
                    thumbs = (video.get("thumbnail") or {}).get("thumbnails") or []
                    out.append({"id": str(video["videoId"]), "title": runs(video.get("title") or {}),
                                "channel": runs(video.get("ownerText") or {}), "length": length or "LIVE",
                                "seconds": seconds, "live": bool(live), "views": runs(video.get("viewCountText") or {}),
                                "thumb": str((thumbs[-1] if thumbs else {}).get("url", "")).split("?")[0]})
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return out[:limit]


def _hms(text: str) -> int:
    parts = [p for p in (text or "").strip().split(":") if p.strip().isdigit()]
    if not parts:
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


# -- the feeds ---------------------------------------------------------------------------------------

@dataclass
class Feed:
    name: str
    every_s: float
    run: Callable[[Fetcher], Any]
    #: the snapshot key this feed writes (several feeds share "markets")
    part: str = ""
    merge: Callable[[dict, Any], None] | None = None


@dataclass
class FeedState:
    at: float = 0.0          # last attempt
    ok_at: float = 0.0       # last success
    error: str = ""
    took_s: float = 0.0
    runs: int = 0
    failures: int = 0


class DashFeeds:
    """The collector. `snapshot()` is what `/api/dash/data` serves;
    `start()` runs the loop; `refresh(now)` runs whatever is due (the
    tests drive it directly with a fake fetcher and clock)."""

    def __init__(self, *, place: str = "San Jose, CA", latitude: float = 37.34, longitude: float = -121.89,
                 watchlist: tuple[str, ...] = DEFAULT_WATCHLIST, majors: tuple[str, ...] = DEFAULT_MAJORS,
                 fetcher: Fetcher | None = None, clock: Callable[[], float] = time.time, logger=None,
                 tick_s: float = 20.0, concurrency: int = 4, snapshot_root: Path | None = None,
                 start_delay_s: float = 3.0) -> None:
        self._place = place
        self._lat, self._lon = float(latitude), float(longitude)
        self._watchlist = tuple(dict.fromkeys(s.upper() for s in watchlist if s.strip()))
        self._majors = tuple(s.upper() for s in majors if s.upper() in self._watchlist) or self._watchlist[:5]
        self._fetch = fetcher or fetch
        self._clock = clock
        self._logger = logger
        self._tick_s = tick_s
        # A short delay before the first fetch: a process that starts
        # and stops at once (a test booting the interface, `sim --check`)
        # never touches the network. The pool is this collector's own,
        # so stopping never waits on a fetch that is mid-flight -- the
        # loop's default executor would.
        self._start_delay_s = start_delay_s
        self._concurrency = max(1, concurrency)
        self._pool: ThreadPoolExecutor | None = None
        self._sem = asyncio.Semaphore(self._concurrency)
        self._data: dict[str, Any] = {"markets": {"quotes": {}, "history": {}}, "news": {}}
        self._state: dict[str, FeedState] = {}
        self._task: asyncio.Task | None = None
        self._running: set[str] = set()
        # Camera stills (execution/home/cameras.py, ring.py) are files:
        # `workspace/cameras/<name>-<stamp>.jpg`, Ring's under ring/.
        self._snapshot_root = (snapshot_root or Path.cwd() / "workspace" / "cameras").resolve()
        self._feeds: list[Feed] = self._build()
        for feed in self._feeds:
            self._state[feed.name] = FeedState()

    # -- what to fetch

    def _build(self) -> list[Feed]:
        feeds: list[Feed] = [
            Feed("quotes", 60.0, self._run_quotes, part="markets", merge=self._merge_quotes),
        ]
        for tf, every in (("1D", 300.0), ("1W", 3600.0), ("1M", 3600.0), ("1Y", 6 * 3600.0)):
            feeds.append(Feed(f"history_{tf}", every, lambda f, tf=tf: self._run_history(f, tf), part="markets",
                              merge=lambda d, v, tf=tf: self._merge_history(d, v, tf)))
        for name, (label, url) in RSS_SOURCES.items():
            feeds.append(Feed(name, 600.0, lambda f, url=url, label=label: parse_rss(f(url), source=label),
                              part="news", merge=lambda d, v, name=name: d["news"].__setitem__(name, v)))
        feeds += [
            Feed("weather", 900.0, self._run_weather, part="weather"),
            Feed("songs", 3 * 3600.0, lambda f: parse_apple_songs(f(APPLE_SONGS)), part="songs"),
            Feed("movies", 6 * 3600.0, lambda f: parse_itunes_movies(f(ITUNES_MOVIES)), part="movies"),
            Feed("boxoffice", 6 * 3600.0, lambda f: parse_box_office(f(BOX_OFFICE)), part="boxoffice"),
            Feed("wiki", 3600.0, self._run_wiki, part="wiki"),
            Feed("apod", 6 * 3600.0, lambda f: parse_apod(f(APOD)), part="apod"),
            Feed("hn", 900.0, self._run_hn, part="hn"),
            Feed("jokes", 1800.0, self._run_jokes, part="jokes"),
            Feed("quote", 6 * 3600.0, lambda f: parse_zen(f(ZEN_TODAY)), part="quote"),
            Feed("ambient", 6 * 3600.0, self._run_ambient, part="ambient"),
        ]
        return feeds

    def _symbols(self) -> list[str]:
        return list(self._watchlist) + [s for s, _ in INDICES + RATES + FX + COMMODITIES + CRYPTO]

    def _run_quotes(self, f: Fetcher) -> dict[str, dict]:
        symbols = self._symbols()
        out: dict[str, dict] = {}
        # The service caps a request at a few dozen symbols; two calls.
        for i in range(0, len(symbols), 24):
            chunk = "|".join(urllib.parse.quote(s, safe="@.=|") for s in symbols[i:i + 24])
            out.update(parse_cnbc_quotes(f(CNBC_QUOTE.format(symbols=chunk))))
        return out

    def _run_history(self, f: Fetcher, tf: str) -> dict[str, list[list[float]]]:
        interval, span, _cap = TIMEFRAMES[tf]
        end = datetime.fromtimestamp(self._clock(), tz=timezone.utc) + timedelta(days=1)
        start = end - span
        symbols = list(self._watchlist) + (list(SPARK_EXTRA) if tf in ("1D", "1W") else [])
        out: dict[str, list[list[float]]] = {}
        errors: list[str] = []
        for symbol in symbols:
            url = CNBC_BARS.format(symbol=urllib.parse.quote(symbol, safe="@.="), interval=interval,
                                   start=start.strftime("%Y%m%d000000"), end=end.strftime("%Y%m%d000000"))
            try:
                pts = parse_cnbc_bars(f(url), timeframe=tf)
            except Exception as exc:  # noqa: BLE001 -- one symbol's failure must not lose the others
                errors.append(f"{symbol}: {exc.__class__.__name__}")
                continue
            if pts:
                out[symbol] = pts
        if not out and errors:
            raise RuntimeError("; ".join(errors[:3]))
        return out

    def _run_weather(self, f: Fetcher) -> dict:
        raw = f(OPEN_METEO.format(lat=self._lat, lon=self._lon))
        try:
            air = f(OPEN_METEO_AIR.format(lat=self._lat, lon=self._lon))
        except Exception:  # noqa: BLE001 -- air quality is a garnish
            air = None
        return parse_open_meteo(raw, air, place=self._place)

    def _run_wiki(self, f: Fetcher) -> dict:
        now = datetime.fromtimestamp(self._clock(), tz=timezone.utc)
        return parse_wiki_featured(f(WIKI_FEATURED.format(yyyy=now.year, mm=f"{now.month:02d}", dd=f"{now.day:02d}")))

    def _run_hn(self, f: Fetcher) -> list[dict]:
        ids = json.loads(f(HN_TOP).decode("utf-8", errors="replace"))[:10]
        out = []
        for id_ in ids:
            try:
                item = parse_hn_item(f(HN_ITEM.format(id=id_)))
            except Exception:  # noqa: BLE001
                continue
            if item:
                out.append(item)
        return out

    def _run_ambient(self, f: Fetcher) -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()
        errors: list[str] = []
        for query in AMBIENT_QUERIES:
            try:
                found = parse_youtube_results(f(YOUTUBE_SEARCH.format(query=urllib.parse.quote_plus(query)),
                                                accept="text/html"))
            except Exception as exc:  # noqa: BLE001 -- one query's failure must not lose the others
                errors.append(f"{query}: {exc.__class__.__name__}")
                continue
            for video in found:
                if video["id"] not in seen:
                    seen.add(video["id"])
                    out.append({**video, "query": query})
        if not out and errors:
            raise RuntimeError("; ".join(errors[:2]))
        return out

    def _run_jokes(self, f: Fetcher) -> list[str]:
        page = 1 + int(self._clock() // 1800) % 40
        return parse_dad_jokes(f(DAD_JOKES.format(page=page), accept="application/json"))

    # -- merging

    def _merge_quotes(self, data: dict, quotes: dict[str, dict]) -> None:
        data["markets"]["quotes"] = quotes
        data["markets"]["quotes_at"] = self._clock()

    def _merge_history(self, data: dict, series: dict[str, list[list[float]]], tf: str) -> None:
        hist = data["markets"]["history"]
        for symbol, pts in series.items():
            hist.setdefault(symbol, {})[tf] = pts
        data["markets"].setdefault("history_at", {})[tf] = self._clock()

    # -- the loop

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="dash-feeds")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    async def _loop(self) -> None:
        await asyncio.sleep(self._start_delay_s)
        while True:
            try:
                await self.refresh(self._clock())
            except Exception as exc:  # noqa: BLE001 -- the loop outlives any one tick
                self._log("dash_feeds_tick_failed", error=f"{exc.__class__.__name__}: {exc}")
            await asyncio.sleep(self._tick_s)

    def due(self, now: float) -> list[Feed]:
        out = []
        for feed in self._feeds:
            st = self._state[feed.name]
            if feed.name in self._running:
                continue
            # A failed feed retries sooner than its cadence, but never
            # hammers: a minute, doubling with each failure, capped at
            # the cadence itself.
            wait = feed.every_s if not st.error or st.ok_at >= st.at else min(feed.every_s, 60.0 * (2 ** min(st.failures - 1, 6)))
            if st.at == 0.0 or now - st.at >= wait:
                out.append(feed)
        return out

    async def refresh(self, now: float, *, only: tuple[str, ...] | None = None) -> list[str]:
        """Run every feed that is due (or the named ones), bounded by the
        semaphore, in worker threads. Returns the names that ran."""
        feeds = [f for f in self._feeds if f.name in only] if only else self.due(now)
        if not feeds:
            return []
        await asyncio.gather(*(self._run_one(feed) for feed in feeds))
        return [f.name for f in feeds]

    async def _run_one(self, feed: Feed) -> None:
        st = self._state[feed.name]
        self._running.add(feed.name)
        started = self._clock()
        st.at = started
        st.runs += 1
        try:
            async with self._sem:
                if self._pool is None:
                    self._pool = ThreadPoolExecutor(max_workers=self._concurrency, thread_name_prefix="dash-feeds")
                value = await asyncio.get_running_loop().run_in_executor(self._pool, feed.run, self._fetch)
            if feed.merge is not None:
                feed.merge(self._data, value)
            else:
                self._data[feed.part or feed.name] = value
            st.ok_at = self._clock()
            st.error = ""
            st.failures = 0
        except Exception as exc:  # noqa: BLE001 -- recorded, shown, retried
            st.error = f"{exc.__class__.__name__}: {exc}"[:200]
            st.failures += 1
            self._log("dash_feed_failed", feed=feed.name, error=st.error)
        finally:
            st.took_s = round(self._clock() - started, 3)
            self._running.discard(feed.name)

    def _log(self, event: str, **fields) -> None:
        if self._logger is None:
            return
        try:
            self._logger.info(event, **fields)
        except Exception:  # noqa: BLE001
            pass

    # -- the snapshot

    _STAMP = re.compile(r"-\d{8}-\d{6}$")
    #: A still older than this is not shown: a poster from this morning
    #: under a live feed reads as the feed (the creator, 2026-09-12).
    STILL_MAX_AGE_S = 12 * 3600.0

    def cameras(self) -> list[dict]:
        """Every camera that has a still on disk, newest first: name,
        kind (reolink | ring), the still's age, and the URL the HTTP API
        serves the newest one at."""
        out: list[dict] = []
        for kind, folder, prefix in (("reolink", self._snapshot_root, "/cameras/snap/"),
                                     ("ring", self._snapshot_root / "ring", "/cameras/snap/ring/")):
            if not folder.is_dir():
                continue
            newest: dict[str, float] = {}
            try:
                files = list(folder.iterdir())
            except OSError:
                continue
            for f in files:
                if f.suffix.lower() not in (".jpg", ".jpeg"):
                    continue
                safe = self._STAMP.sub("", f.stem)
                try:
                    at = f.stat().st_mtime
                except OSError:
                    continue
                if at > newest.get(safe, 0.0):
                    newest[safe] = at
            now = self._clock()
            for safe, at in newest.items():
                if now - at > self.STILL_MAX_AGE_S:
                    continue
                out.append({"name": safe.replace("_", " "), "safe": safe, "kind": kind, "at": at,
                            "url": prefix + urllib.parse.quote(safe)})
        out.sort(key=lambda c: c["at"], reverse=True)
        return out

    LIVE_WITHIN_S = 20.0

    def streams(self) -> list[dict]:
        """The camera relays running now (execution/home/cameras.py writes
        `hls/<channel>/index.m3u8` and `camera.json`): channel, name, the
        playlist's URL on this API, and whether it is live -- a playlist
        untouched for `LIVE_WITHIN_S` is a relay that has stopped."""
        root = self._snapshot_root / "hls"
        if not root.is_dir():
            return []
        now = self._clock()
        out: list[dict] = []
        for folder in sorted(root.iterdir(), key=lambda f: f.name):
            playlist = folder / "index.m3u8"
            if not folder.name.isdigit() or not playlist.is_file():
                continue
            try:
                at = playlist.stat().st_mtime
            except OSError:
                continue
            name = f"Camera {int(folder.name) + 1}"
            try:
                meta = json.loads((folder / "camera.json").read_text(encoding="utf-8"))
                name = str(meta.get("name") or name)
            except (OSError, ValueError):
                pass
            out.append({"channel": int(folder.name), "name": name, "url": f"/tv/hls/{folder.name}/index.m3u8",
                        "live": (now - at) <= self.LIVE_WITHIN_S, "at": at})
        return out

    def ring_cameras(self) -> list[dict]:
        """The Ring cameras the ring tools last saw (`ring/cameras.json`),
        so the strip can offer their live view before any still exists."""
        path = self._snapshot_root / "ring" / "cameras.json"
        try:
            rows = json.loads(path.read_text(encoding="utf-8")) or []
        except (OSError, ValueError):
            return []
        return [{"name": str(r.get("name") or ""), "kind": str(r.get("kind") or ""), "battery": r.get("battery"),
                 "safe": re.sub(r"[^A-Za-z0-9_-]+", "_", str(r.get("name") or "")).strip("_")}
                for r in rows if isinstance(r, dict) and r.get("name")]

    def events(self) -> list[dict]:
        """Camera events the Ring tools keep in `ring/events.json`
        (execution/home/ring.py), newest first; [] when there are none."""
        path = self._snapshot_root / "ring" / "events.json"
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return []
        cached = getattr(self, "_events_cache", None)
        if cached and cached[0] == stamp:
            return cached[1]
        try:
            rows = json.loads(path.read_text(encoding="utf-8")) or []
        except (OSError, ValueError):
            rows = []
        rows = [r for r in rows if isinstance(r, dict)][:60]
        self._events_cache = (stamp, rows)
        return rows

    def snapshot(self) -> dict:
        now = self._clock()
        quotes = self._data["markets"].get("quotes", {})
        history = self._data["markets"].get("history", {})

        def rows(table: tuple[tuple[str, str], ...]) -> list[dict]:
            out = []
            for symbol, label in table:
                q = quotes.get(symbol)
                if q:
                    out.append({**q, "label": label, "spark": (history.get(symbol) or {}).get("1D"),
                                "week": (history.get(symbol) or {}).get("1W")})
            return out

        stocks = []
        for symbol in self._watchlist:
            q = quotes.get(symbol) or {"symbol": symbol, "name": WATCHLIST.get(symbol, (symbol, ""))[0]}
            name, desc = WATCHLIST.get(symbol, (q.get("name", symbol), ""))
            stocks.append({**q, "symbol": symbol, "short": name, "description": desc,
                           "major": symbol in self._majors, "history": history.get(symbol) or {}})
        status = ""
        for symbol in self._watchlist:
            if quotes.get(symbol, {}).get("status"):
                status = quotes[symbol]["status"]
                break
        return {
            "now": now,
            "feeds": {name: {"at": st.at, "ok_at": st.ok_at, "error": st.error, "took_s": st.took_s, "runs": st.runs,
                             "stale_s": (round(now - st.ok_at) if st.ok_at else None)}
                      for name, st in self._state.items()},
            "markets": {
                "as_of": self._data["markets"].get("quotes_at", 0.0), "status": status, "majors": list(self._majors),
                "stocks": stocks, "indices": rows(INDICES), "rates": rows(RATES), "fx": rows(FX),
                "commodities": rows(COMMODITIES), "crypto": rows(CRYPTO),
                "history_at": self._data["markets"].get("history_at", {}),
                "source": "CNBC quotes & bars; headlines: Bloomberg",
            },
            "news": self._data.get("news", {}),
            "weather": self._data.get("weather"),
            "songs": self._data.get("songs", []),
            "movies": self._data.get("movies", []),
            "boxoffice": self._data.get("boxoffice", []),
            "wiki": self._data.get("wiki"),
            "apod": self._data.get("apod"),
            "hn": self._data.get("hn", []),
            "jokes": self._data.get("jokes", []),
            "quote": self._data.get("quote"),
            "ambient": self._data.get("ambient", []),
            "cameras": self.cameras(),
            "streams": self.streams(),
            "ring_cameras": self.ring_cameras(),
            "events": self.events(),
        }


__all__ = ["DashFeeds", "Feed", "FeedState", "DEFAULT_MAJORS", "DEFAULT_WATCHLIST", "WATCHLIST", "fetch",
           "parse_apod", "parse_apple_songs", "parse_box_office", "parse_cnbc_bars", "parse_cnbc_quotes",
           "parse_dad_jokes", "parse_hn_item", "parse_itunes_movies", "parse_open_meteo", "parse_rss",
           "parse_wiki_featured", "parse_youtube_results", "parse_zen", "thin"]
