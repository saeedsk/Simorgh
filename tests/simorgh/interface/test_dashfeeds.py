"""The dashboard's collector (interface/dashfeeds.py): every parser is a
pure function over one endpoint's bytes, and the scheduler runs feeds
on their cadence, keeps the last good value through a failure, and
never lets one feed's error stop the others. The fixtures are trimmed
copies of what the real endpoints answered on 2026-09-12."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from simorgh.interface import dashfeeds as df

CNBC_QUOTES = json.dumps({"FormattedQuoteResult": {"FormattedQuote": [
    {"symbol": "NVDA", "code": 0, "name": "NVIDIA Corporation", "last": "218.29", "change": "-0.07", "change_pct": "-0.03%",
     "open": "221.24", "high": "222.00", "low": "218.15", "previous_day_closing": "218.36", "volume": "77,555,460",
     "volume_alt": "77.6M", "mktcapView": "5.261T", "pe": "27.59", "eps": "7.91", "dividendyield": "0.46%", "beta": "2.22",
     "yrhiprice": "236.54", "yrloprice": "164.27", "curmktstatus": "POST_MKT", "last_timedate": "09/11/26 EDT",
     "currencyCode": "USD", "type": "STOCK", "exchange": "NASDAQ"},
    {"symbol": "EUR=", "code": 0, "name": "EUR/USD", "last": "1.1598", "change": "UNCH", "change_pct": "UNCH", "curmktstatus": "REG_MKT"},
    {"symbol": "DXY", "code": 1, "name": None, "last": None},
]}}).encode()

CNBC_BARS = json.dumps({"barData": {"priceBars": [
    {"close": "223.1000", "tradeTime": "20260910040000", "tradeTimeinMills": 1789027200000},
    {"close": "222.0000", "tradeTime": "20260910093000", "tradeTimeinMills": 1789047000000},
    {"close": "221.0000", "tradeTime": "20260910100000", "tradeTimeinMills": 1789048800000},
    {"close": "220.0000", "tradeTime": "20260910103000", "tradeTimeinMills": 1789050600000},
    {"close": "219.0000", "tradeTime": "20260910110000", "tradeTimeinMills": 1789052400000},
    {"close": "219.5000", "tradeTime": "20260911040000", "tradeTimeinMills": 1789113600000},
    {"close": "218.9000", "tradeTime": "20260911093000", "tradeTimeinMills": 1789133400000},
    {"close": "218.7000", "tradeTime": "20260911100000", "tradeTimeinMills": 1789135200000},
    {"close": "218.4000", "tradeTime": "20260911103000", "tradeTimeinMills": 1789137000000},
    {"close": "218.2600", "tradeTime": "20260911195900", "tradeTimeinMills": 1789171140000},
    # a lone Saturday print, the kind S&P futures leave behind
    {"close": "218.3000", "tradeTime": "20260912071000", "tradeTimeinMills": 1789211400000},
]}}).encode()

RSS = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Bloomberg Markets</title>
<item><title>Energy Driven Inflation &amp; the Fed</title><link>https://b.com/1</link><pubDate>Sat, 12 Sep 2026 15:40:50 GMT</pubDate></item>
<item><title>Older story</title><link>https://b.com/2</link><pubDate>Fri, 11 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title></title><link>https://b.com/3</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title>
<entry><title>An Atom entry</title><link href="https://a.com/1"/><updated>2026-09-12T10:00:00Z</updated></entry></feed>"""

METEO = json.dumps({"timezone": "America/Los_Angeles", "current": {
    "time": "2026-09-12T10:15", "temperature_2m": 70.7, "apparent_temperature": 70.1, "weather_code": 0,
    "wind_speed_10m": 7.2, "relative_humidity_2m": 64, "uv_index": 4.1, "is_day": 1},
    "daily": {"time": ["2026-09-12", "2026-09-13"], "temperature_2m_max": [76.1, 73.0], "temperature_2m_min": [59.0, 58.0],
              "weather_code": [0, 2], "sunrise": ["2026-09-12T06:47", "2026-09-13T06:48"],
              "sunset": ["2026-09-12T19:19", "2026-09-13T19:18"], "precipitation_probability_max": [0, 1]},
    "hourly": {"time": ["2026-09-12T09:00", "2026-09-12T10:00", "2026-09-12T11:00"], "temperature_2m": [66, 70, 72],
               "weather_code": [0, 0, 1], "precipitation_probability": [0, 0, 0]}}).encode()
AIR = json.dumps({"current": {"us_aqi": 53, "pm2_5": 11.2}}).encode()

THE_NUMBERS = b"""<html><body><table class="chart-desktop"><tr><th>Rank</th><th>Prev</th><th>Title</th><th>Gross</th>
<th>WeeklyChange</th><th>Theaters</th><th>TheaterAverage</th><th>Total Gross</th><th>Days in Release</th></tr>
<tr><td>1</td><td>(1)</td><td><a href="/m/x">Spider-Man: Brand New Day</a></td><td>$18,178,872</td><td>-19%</td><td>3,520</td>
<td>$5,164</td><td>$917,941,367</td><td>38</td></tr>
<tr><td>2</td><td>(3)</td><td>The Odyssey</td><td>$13,095,130</td><td>-9%</td><td>2,312</td><td>$5,664</td><td>$584,872,095</td><td>52</td></tr>
</table><table class="chart-mobile"><tr><td>ignored</td></tr></table></body></html>"""

WIKI = json.dumps({
    "tfa": {"title": "United_States_v._Moore_(1973)", "displaytitle": "<i>United States v. Moore</i> (1973)",
            "extract": "A case.", "thumbnail": {"source": "https://u/t.jpg"}, "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/x"}}},
    "image": {"title": "File:Sigtuna.jpg", "image": {"source": "https://u/full.jpg"}, "thumbnail": {"source": "https://u/thumb.jpg"},
              "description": {"text": "Ruins of the <b>St. Olof</b> Church"}, "artist": {"text": "Someone"}},
    "onthisday": [{"year": 2015, "text": "An explosion."}],
    "mostread": {"articles": [{"title": "Special:Search", "views": 1}, {"title": "September_11_attacks", "normalizedtitle": "September 11 attacks", "views": 666000}]},
}).encode()


YT = ('<html><script>var ytInitialData = ' + json.dumps({"contents": [
    {"videoRenderer": {"videoId": "longone", "title": {"runs": [{"text": "Forest 4K "}, {"text": "Relaxation"}]},
                       "ownerText": {"runs": [{"text": "Relaxation Film"}]}, "lengthText": {"simpleText": "3:00:52"},
                       "viewCountText": {"simpleText": "22,371,240 views"},
                       "thumbnail": {"thumbnails": [{"url": "https://i/small.jpg"}, {"url": "https://i/hq720.jpg?sqp=x"}]}}},
    {"videoRenderer": {"videoId": "shortone", "title": {"runs": [{"text": "A 3 minute clip"}]}, "lengthText": {"simpleText": "3:12"}}},
    {"videoRenderer": {"videoId": "liveone", "title": {"runs": [{"text": "Live cam"}]},
                       "badges": [{"metadataBadgeRenderer": {"label": "LIVE"}}]}},
    {"videoRenderer": {"videoId": "longone", "title": {"runs": [{"text": "dup"}]}, "lengthText": {"simpleText": "5:00:00"}}},
]}) + ';</script></html>').encode()


class ParsersTestCase(unittest.TestCase):
    def test_youtube_results_keep_long_films_and_live_streams_once(self):
        videos = df.parse_youtube_results(YT)
        self.assertEqual([v["id"] for v in videos], ["longone", "liveone"])
        first = videos[0]
        self.assertEqual((first["title"], first["channel"], first["seconds"], first["thumb"]),
                         ("Forest 4K Relaxation", "Relaxation Film", 10852, "https://i/hq720.jpg"))
        self.assertTrue(videos[1]["live"]); self.assertEqual(videos[1]["length"], "LIVE")
        self.assertEqual(df.parse_youtube_results(b"<html>consent</html>"), [])

    def test_cnbc_quotes_become_numbers_and_unknown_symbols_are_dropped(self):
        quotes = df.parse_cnbc_quotes(CNBC_QUOTES)
        self.assertEqual(sorted(quotes), ["EUR=", "NVDA"])
        nvda = quotes["NVDA"]
        self.assertEqual((nvda["last"], nvda["change"], nvda["change_pct"]), (218.29, -0.07, -0.03))
        self.assertEqual((nvda["market_cap"], nvda["volume"], nvda["status"]), ("5.261T", "77.6M", "POST_MKT"))
        self.assertEqual((nvda["year_high"], nvda["year_low"], nvda["prev_close"]), (236.54, 164.27, 218.36))
        self.assertEqual((quotes["EUR="]["change"], quotes["EUR="]["change_pct"]), (0.0, 0.0), "UNCH is zero, not None")

    def test_1d_bars_keep_the_last_full_session_not_a_stray_saturday_print(self):
        pts = df.parse_cnbc_bars(CNBC_BARS, timeframe="1D")
        self.assertEqual([p[1] for p in pts], [219.5, 218.9, 218.7, 218.4, 218.26])
        self.assertEqual(pts[0][0], 1789113600, "epoch seconds, not milliseconds")

    def test_longer_timeframes_keep_every_bar_thinned_to_the_cap(self):
        self.assertEqual(len(df.parse_cnbc_bars(CNBC_BARS, timeframe="1Y")), 11)
        thinned = df.thin([[i, float(i)] for i in range(1000)], 240)
        self.assertEqual(len(thinned), 240)
        self.assertEqual(thinned[-1], [999, 999.0], "the last point always survives")

    def test_rss_and_atom_give_titles_newest_first_and_skip_the_empty(self):
        items = df.parse_rss(RSS, source="Bloomberg")
        self.assertEqual([i["title"] for i in items], ["Energy Driven Inflation & the Fed", "Older story"])
        self.assertEqual(items[0]["source"], "Bloomberg")
        self.assertGreater(items[0]["at"], items[1]["at"])
        atom = df.parse_rss(ATOM, source="A")
        self.assertEqual((atom[0]["title"], atom[0]["link"]), ("An Atom entry", "https://a.com/1"))
        self.assertEqual(df.parse_rss(b"<html>Are you a robot?</html>", source="x"), [])

    def test_open_meteo_is_summarised_with_glyphs_sun_and_air(self):
        w = df.parse_open_meteo(METEO, AIR, place="San Jose, CA")
        self.assertEqual((w["temp"], w["text"], w["glyph"], w["aqi"]), (70.7, "Clear", "☀", 53))
        self.assertEqual(w["sunrise"], "2026-09-12T06:47")
        self.assertEqual(len(w["daily"]), 2)
        self.assertEqual(w["daily"][1]["text"], "Partly cloudy")
        self.assertEqual([h["time"] for h in w["hourly"]], ["2026-09-12T10:00", "2026-09-12T11:00"], "past hours dropped")
        self.assertIsNone(df.parse_open_meteo(METEO, None, place="x")["aqi"])

    def test_the_box_office_table_is_read_by_header_name(self):
        rows = df.parse_box_office(THE_NUMBERS)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["title"], "Spider-Man: Brand New Day")
        self.assertEqual((rows[0]["weekend"], rows[0]["total"], rows[0]["age"], rows[0]["change"]),
                         ("$18,178,872", "$917,941,367", "38 days", "-19%"))
        self.assertEqual(df.parse_box_office(b"<html><body>no table here</body></html>"), [])

    def test_wikipedia_featured_strips_markup_and_special_pages(self):
        w = df.parse_wiki_featured(WIKI)
        self.assertEqual(w["featured"]["title"], "United States v. Moore (1973)")
        self.assertEqual(w["potd"]["description"], "Ruins of the St. Olof Church")
        self.assertEqual(w["potd"]["thumb"], "https://u/thumb.jpg")
        self.assertEqual([a["title"] for a in w["mostread"]], ["September 11 attacks"])
        self.assertEqual(w["onthisday"][0]["year"], 2015)

    def test_the_small_parsers(self):
        self.assertEqual(df.parse_dad_jokes(b'{"results":[{"joke":"A"},{"joke":""}]}'), ["A"])
        self.assertEqual(df.parse_zen(b'[{"q":"Go.","a":"Me"}]'), {"text": "Go.", "author": "Me"})
        self.assertEqual(df.parse_hn_item(b'{"title":"T","url":"https://x","score":5,"by":"u","descendants":2,"time":1}')["score"], 5)
        self.assertIsNone(df.parse_hn_item(b'{"deleted":true}'))
        songs = df.parse_apple_songs(b'{"feed":{"results":[{"name":"S","artistName":"A","artworkUrl100":"https://i/1.jpg"}]}}')
        self.assertEqual(songs, [{"rank": 1, "name": "S", "artist": "A", "art": "https://i/1.jpg", "url": ""}])
        movies = df.parse_itunes_movies(b'{"feed":{"entry":[{"im:name":{"label":"M"},"im:image":[{"label":"https://i/60x60bb.jpg"}],'
                                        b'"category":{"attributes":{"label":"Action"}},"im:releaseDate":{"attributes":{"label":"Aug 1"}},"summary":{"label":"s"}}]}}')
        self.assertEqual((movies[0]["name"], movies[0]["genre"], movies[0]["art"]), ("M", "Action", "https://i/300x300bb.jpg"))
        apod = df.parse_apod(b'{"title":"Moon","media_type":"image","url":"https://n/m.jpg","explanation":"x","date":"2026-09-12"}')
        self.assertEqual((apod["title"], apod["thumb"]), ("Moon", "https://n/m.jpg"))


class _Fetcher:
    """URL substring -> bytes or an exception; counts calls."""

    def __init__(self, table: dict) -> None:
        self.table = table
        self.calls: list[str] = []

    def __call__(self, url: str, **_kw) -> bytes:
        self.calls.append(url)
        for key, value in self.table.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise RuntimeError(f"no fixture for {url}")


class _Clock:
    def __init__(self, t: float = 1_789_200_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class SchedulerTestCase(unittest.IsolatedAsyncioTestCase):
    def _feeds(self, table: dict, **kw) -> tuple[df.DashFeeds, _Fetcher, _Clock]:
        fetcher, clock = _Fetcher(table), _Clock()
        feeds = df.DashFeeds(fetcher=fetcher, clock=clock, watchlist=("NVDA",), majors=("NVDA",), concurrency=2,
                             start_delay_s=0.0, **kw)
        return feeds, fetcher, clock

    async def test_every_feed_is_due_at_first_and_runs_on_its_own_cadence_after(self):
        # matched in order: the specific hosts first, the RSS catch-alls last
        feeds, fetcher, clock = self._feeds({"restQuote": CNBC_QUOTES, "bars/": CNBC_BARS,
                                             "air-quality": AIR, "open-meteo": METEO, "songs.json": b'{"feed":{"results":[]}}',
                                             "topmovies": b'{"feed":{"entry":[]}}', "the-numbers": THE_NUMBERS,
                                             "featured": WIKI, "apod": b'{"title":"Moon","media_type":"image","url":"u"}',
                                             "topstories": b"[1]", "item/1": b'{"title":"T","url":"u"}',
                                             "icanhazdadjoke": b'{"results":[{"joke":"J"}]}', "zenquotes": b'[{"q":"Q","a":"A"}]',
                                             "youtube.com/results": YT, "arstechnica": RSS, "rss": RSS, "feed/": RSS})
        ran = await feeds.refresh(clock())
        self.assertEqual(len(ran), len(feeds._feeds))  # noqa: SLF001
        snap = feeds.snapshot()
        self.assertTrue(all(not st["error"] for st in snap["feeds"].values()), snap["feeds"])
        nvda = snap["markets"]["stocks"][0]
        self.assertEqual((nvda["symbol"], nvda["last"], nvda["major"], nvda["short"]), ("NVDA", 218.29, True, "NVIDIA"))
        self.assertEqual(sorted(nvda["history"]), ["1D", "1M", "1W", "1Y"])
        self.assertEqual(snap["markets"]["status"], "POST_MKT")
        self.assertEqual(snap["markets"]["fx"][0]["label"], "EUR/USD")
        self.assertEqual(snap["news"]["bloomberg_markets"][0]["source"], "Bloomberg")
        self.assertEqual(snap["weather"]["aqi"], 53)
        self.assertEqual((snap["jokes"], snap["quote"]["author"], snap["hn"][0]["title"]), (["J"], "A", "T"))
        self.assertEqual([v["id"] for v in snap["ambient"]], ["longone", "liveone"], "the same film from four queries, once")
        self.assertEqual(len(feeds._data["markets"]["history"][".SPX"]["1W"]), 11, "indices carry a 5-day series for Home")  # noqa: SLF001
        # 30 seconds later nothing is due; a minute later only the quotes.
        clock.t += 30
        self.assertEqual(await feeds.refresh(clock()), [])
        clock.t += 31
        self.assertEqual(await feeds.refresh(clock()), ["quotes"])
        clock.t += 300
        self.assertIn("history_1D", await feeds.refresh(clock()))
        self.assertNotIn("history_1Y", [f.name for f in feeds.due(clock())])

    async def test_a_failing_feed_keeps_its_last_value_records_the_error_and_retries_sooner(self):
        table = {"restQuote": CNBC_QUOTES, "bars/": CNBC_BARS}
        feeds, fetcher, clock = self._feeds(table)
        await feeds.refresh(clock(), only=("quotes", "bloomberg_markets"))
        snap = feeds.snapshot()
        self.assertEqual(snap["markets"]["stocks"][0]["last"], 218.29)
        self.assertIn("RuntimeError", snap["feeds"]["bloomberg_markets"]["error"])
        self.assertEqual(snap["feeds"]["bloomberg_markets"]["ok_at"], 0.0)
        # the good feed is untouched by the bad one's failure
        self.assertEqual(snap["feeds"]["quotes"]["error"], "")
        # the quotes fail next time: the last good numbers stay on the page
        table["restQuote"] = RuntimeError("503")
        clock.t += 61
        await feeds.refresh(clock(), only=("quotes",))
        snap = feeds.snapshot()
        self.assertEqual(snap["markets"]["stocks"][0]["last"], 218.29)
        self.assertIn("503", snap["feeds"]["quotes"]["error"])
        self.assertEqual(snap["feeds"]["quotes"]["stale_s"], 61)
        # a failed 10-minute feed is retried after a minute, not ten
        clock.t += 61
        self.assertIn("bloomberg_markets", [f.name for f in feeds.due(clock())])

    async def test_history_survives_one_symbol_failing(self):
        feeds, fetcher, clock = self._feeds({"bars/NVDA": CNBC_BARS, "bars/.SPX": RuntimeError("no"), "bars/": CNBC_BARS})
        await feeds.refresh(clock(), only=("history_1D",))
        snap = feeds.snapshot()
        self.assertEqual(snap["feeds"]["history_1D"]["error"], "")
        self.assertEqual(len(snap["markets"]["stocks"][0]["history"]["1D"]), 5)

    async def test_the_watchlist_and_majors_come_from_config_and_unknown_symbols_still_work(self):
        feeds = df.DashFeeds(fetcher=_Fetcher({}), clock=_Clock(), watchlist=("nvda", "ZZZZ", "nvda"), majors=("zzzz", "QQQ"))
        snap = feeds.snapshot()
        self.assertEqual([s["symbol"] for s in snap["markets"]["stocks"]], ["NVDA", "ZZZZ"])
        self.assertEqual(snap["markets"]["majors"], ["ZZZZ"], "a major not on the watchlist is ignored")
        self.assertEqual(snap["markets"]["stocks"][1]["short"], "ZZZZ")

    async def test_camera_stills_on_disk_become_tiles_newest_per_camera(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Front_Door-20260912-090000.jpg").write_bytes(b"1")
            (root / "Front_Door-20260912-100000.jpg").write_bytes(b"2")
            (root / "Office-20260912-080000.jpg").write_bytes(b"3")
            (root / "notes.txt").write_bytes(b"x")
            (root / "ring").mkdir()
            (root / "ring" / "Porch-20260912-110000.jpg").write_bytes(b"4")
            (root / "Garage-20260901-100000.jpg").write_bytes(b"5")
            import os
            now = 2_000_000_000
            os.utime(root / "Front_Door-20260912-100000.jpg", (now, now))
            for name in ("Front_Door-20260912-090000.jpg", "Office-20260912-080000.jpg", "ring/Porch-20260912-110000.jpg"):
                os.utime(root / name, (now - 600, now - 600))
            os.utime(root / "Garage-20260901-100000.jpg", (now - 3 * 86400, now - 3 * 86400))   # days old: not a poster
            feeds = df.DashFeeds(fetcher=_Fetcher({}), clock=_Clock(float(now)), snapshot_root=root)
            cams = feeds.cameras()
            self.assertEqual([c["name"] for c in cams][:1], ["Front Door"])
            self.assertEqual({c["name"] for c in cams}, {"Front Door", "Office", "Porch"})
            porch = next(c for c in cams if c["name"] == "Porch")
            self.assertEqual((porch["kind"], porch["url"]), ("ring", "/cameras/snap/ring/Porch"))
            self.assertEqual(next(c for c in cams if c["name"] == "Front Door")["url"], "/cameras/snap/Front_Door")
            self.assertEqual(feeds.snapshot()["cameras"], cams)

    async def test_live_relays_are_listed_by_name_and_go_stale_when_the_playlist_stops_moving(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for ch, name in ((1, "Front Window"), (7, "Office")):
                folder = root / "hls" / str(ch)
                folder.mkdir(parents=True)
                (folder / "index.m3u8").write_text("#EXTM3U\n")
                (folder / "camera.json").write_text(json.dumps({"channel": ch, "name": name}))
            (root / "hls" / "3").mkdir(); (root / "hls" / "3" / "index.m3u8").write_text("#EXTM3U\n")   # no camera.json
            (root / "hls" / "junk").mkdir()
            import os, time as _t
            now = _t.time()
            os.utime(root / "hls" / "7" / "index.m3u8", (now - 300, now - 300))
            feeds = df.DashFeeds(fetcher=_Fetcher({}), clock=lambda: now, snapshot_root=root)
            streams = feeds.streams()
            self.assertEqual([(s["channel"], s["name"], s["live"], s["url"]) for s in streams],
                             [(1, "Front Window", True, "/tv/hls/1/index.m3u8"), (3, "Camera 4", True, "/tv/hls/3/index.m3u8"),
                              (7, "Office", False, "/tv/hls/7/index.m3u8")])
            self.assertEqual(feeds.snapshot()["streams"], streams)

    async def test_start_and_stop_run_the_loop_once(self):
        feeds, fetcher, clock = self._feeds({"restQuote": CNBC_QUOTES, "bars/": CNBC_BARS})
        feeds._tick_s = 0.01  # noqa: SLF001
        await feeds.start()
        for _ in range(50):
            await asyncio.sleep(0.01)
            if feeds.snapshot()["feeds"]["quotes"]["runs"]:
                break
        await feeds.stop()
        self.assertGreaterEqual(feeds.snapshot()["feeds"]["quotes"]["runs"], 1)
        self.assertIn("restQuote", "".join(fetcher.calls))


if __name__ == "__main__":
    unittest.main()
