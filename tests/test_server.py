"""Unit tests for the parts of the TubeHaus server that don't need the network.

    python3 -m unittest discover -s tests
"""
import base64
import importlib.util
import os
import pathlib
import re
import tempfile
import time
import unittest
from unittest.mock import patch

STATE = tempfile.mkdtemp(prefix="tubehaus-test-")
os.environ.update(HT_STATE=STATE, HT_YT_PROXY="", HT_WARP_ROTATE="0")
spec = importlib.util.spec_from_file_location(
    "tubehaus_server", pathlib.Path(__file__).resolve().parent.parent / "server" / "tubehaus_server.py")
ts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ts)


class BotDetection(unittest.TestCase):
    def test_bot_wall(self):
        d = {"playabilityStatus": {"status": "LOGIN_REQUIRED",
                                   "reason": "Sign in to confirm you're not a bot"}}
        self.assertTrue(ts.yt_blocked(d))

    def test_login_required_without_reason_is_the_bot_wall(self):
        self.assertTrue(ts.yt_blocked({"playabilityStatus": {"status": "LOGIN_REQUIRED"}}))

    def test_age_gate_is_not_a_bot_wall(self):
        d = {"playabilityStatus": {"status": "LOGIN_REQUIRED",
                                   "reason": "Sign in to confirm your age"}}
        self.assertFalse(ts.yt_blocked(d))

    def test_unavailable_video_is_not_a_bot_wall(self):
        self.assertFalse(ts.yt_blocked({"playabilityStatus": {"status": "ERROR", "reason": "Video unavailable"}}))

    def test_html_body(self):
        self.assertTrue(ts.yt_blocked(body="Sign in to confirm you’re not a bot".encode()))
        self.assertFalse(ts.yt_blocked(body=b"<html>ok</html>"))


class LiveWindow(unittest.TestCase):
    def playlist(self, last):
        lines = ["#EXTM3U", "#EXT-X-MEDIA-SEQUENCE:%d" % (last - 2)]
        for sq in range(last - 2, last + 1):
            lines += ["#EXTINF:1.0,", "https://rr1.googlevideo.com/videoplayback/sq/%d/goap/x" % sq]
        return "\n".join(lines) + "\n"

    def decode(self, line):
        b64 = line[len(ts.LIVE_BASE):-len(".ts")]
        return base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode()

    def test_window_is_rebuilt_ending_at_the_newest_segment(self):
        out = ts.live_window(self.playlist(500))
        segs = [l for l in out.splitlines() if l.startswith(ts.LIVE_BASE)]
        self.assertEqual(len(segs), ts.LIVE_WINDOW)
        first = 500 - ts.LIVE_WINDOW + 1
        self.assertIn("#EXT-X-MEDIA-SEQUENCE:%d" % first, out)
        self.assertEqual([ts._sq(self.decode(s)) for s in segs], list(range(first, 501)))

    def test_window_never_goes_below_zero(self):
        out = ts.live_window(self.playlist(5))
        self.assertIn("#EXT-X-MEDIA-SEQUENCE:0", out)
        self.assertEqual(sum(1 for l in out.splitlines() if l.startswith(ts.LIVE_BASE)), 6)

    def test_playlist_without_sq_is_only_proxied(self):
        text = "#EXTM3U\n#EXTINF:1.0,\nhttps://example.com/seg1.ts\n"
        out = ts.live_window(text)
        seg = [l for l in out.splitlines() if l.startswith(ts.LIVE_BASE)]
        self.assertEqual([self.decode(s) for s in seg], ["https://example.com/seg1.ts"])


class TransportStream(unittest.TestCase):
    @staticmethod
    def packet(pts):
        b = bytes([0x21 | ((pts >> 29) & 0x0E), (pts >> 22) & 0xFF, 0x01 | ((pts >> 14) & 0xFE),
                   (pts >> 7) & 0xFF, 0x01 | ((pts << 1) & 0xFE)])
        pes = b"\x00\x00\x01\xe0\x00\x00\x80\x80\x05" + b
        pk = bytes([0x47, 0x40, 0x100 >> 8 & 0x1F, 0x10]) + pes
        return pk + b"\xff" * (188 - len(pk))

    def test_first_video_pts(self):
        for pts in (0, 90000, 2**32 + 12345):
            self.assertEqual(ts.ts_first_pts(self.packet(pts)), pts)

    def test_no_video_packet(self):
        self.assertIsNone(ts.ts_first_pts(b"\x47" + b"\x00" * 187))


class Subtitles(unittest.TestCase):
    def test_vtt_cues(self):
        vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello\nworld\n\n00:00:03.000 --> 00:00:04.000\nBye\n"
        self.assertEqual(ts._vtt_cues(vtt), [("00:00:01.000 --> 00:00:02.000", ["Hello", "world"]),
                                             ("00:00:03.000 --> 00:00:04.000", ["Bye"])])

    def test_subtitle_cache_path_cannot_escape(self):
        for vid, tl in (("../../etc/x", "en"), ("jNQXAC9IVRw", "../../x"), ("jNQXAC9IVRw", "en/../..")):
            with self.assertRaises(ValueError):
                ts.sub_vtt(vid, tl)

    def test_cc_time(self):
        self.assertAlmostEqual(ts._cc_time("01:02:03.500"), 3723.5)


class Library(unittest.TestCase):
    def setUp(self):
        if os.path.exists(ts.YTLIB):
            os.remove(ts.YTLIB)

    def test_resume_position_and_history(self):
        meta = {"id": "jNQXAC9IVRw", "title": "Me at the zoo", "author": "jawed", "len": 19}
        code, _ = ts.ytlib_post("/api/p/yt/pos", {"id": "jNQXAC9IVRw", "t": 7, "len": 19, "meta": meta})
        self.assertEqual(code, 200)
        self.assertEqual(ts.ytlib_query("/api/p/yt/pos", {"ids": "jNQXAC9IVRw"}), {"jNQXAC9IVRw": [7, 19]})
        hist = ts.ytlib_query("/api/p/yt/hist", {})
        self.assertEqual(hist["total"], 1)
        self.assertEqual(hist["items"][0]["title"], "Me at the zoo")

    def test_bad_ids_are_rejected(self):
        self.assertEqual(ts.ytlib_post("/api/p/yt/pos", {"id": "../../etc", "t": 1})[0], 400)
        self.assertEqual(ts.ytlib_post("/api/p/yt/sub", {"id": "not-a-channel", "on": True})[0], 400)
        self.assertEqual(ts.ytlib_query("/api/p/yt/pos", {"ids": "bad,also bad"}), {})

    def test_history_search_and_delete(self):
        for vid, title in (("aaaaaaaaaaa", "Cooking pasta"), ("bbbbbbbbbbb", "Live news")):
            ts.ytlib_post("/api/p/yt/pos", {"id": vid, "t": 1, "len": 60, "meta": {"id": vid, "title": title}})
        self.assertEqual(ts.ytlib_query("/api/p/yt/hist", {"q": "pasta"})["total"], 1)
        ts.ytlib_post("/api/p/yt/hist/del", {"id": "aaaaaaaaaaa"})
        self.assertEqual([x["id"] for x in ts.ytlib_query("/api/p/yt/hist", {})["items"]], ["bbbbbbbbbbb"])


class ShortsRecommender(unittest.TestCase):
    CAT, DOG = "UC" + "c" * 22, "UC" + "d" * 22

    def setUp(self):
        if os.path.exists(ts.SHORTS):
            os.remove(ts.SHORTS)

    def watch(self, vid, ch, watched, length=30, **kw):
        body = {"id": vid, "authorId": ch, "author": ch[-1], "title": kw.pop("title", ""), "watched": watched, "len": length}
        body.update(kw)
        return ts.shorts_signal(body)

    def test_engagement_order(self):
        e = ts._sh_engagement
        self.assertLess(e(1, 30), 0)                      # swiped away
        self.assertLess(e(10, 30), e(30, 30))             # partial < full
        self.assertLess(e(30, 30), e(90, 30))             # watched < looped
        self.assertLess(e(30, 30), e(30, 30, liked=True))
        self.assertLess(e(30, 30, disliked=True), e(1, 30))

    def test_tokens(self):
        t = ts._sh_tokens("Funny cat #CatsOfInstagram #shorts", ["Cat", "kitten", "viral"], "Pets & Animals")
        self.assertEqual(t, ["cat", "kitten", "catsofinstagram", "genre:pets & animals"])

    def test_signals_build_channel_and_keyword_taste(self):
        self.watch("aaaaaaaaaaa", self.CAT, 60, keywords=["cat"])
        self.watch("bbbbbbbbbbb", self.DOG, 1, keywords=["dog"])
        d = ts._sh_load()
        self.assertGreater(d["ch"][self.CAT], 0)
        self.assertLess(d["ch"][self.DOG], 0)
        self.assertGreater(d["kw"]["cat"], 0)
        self.assertIn("aaaaaaaaaaa", d["seen"])
        self.assertEqual(self.watch("../etc/pass", self.CAT, 1)[0], 400)

    def test_ranking_prefers_taste_skips_seen_and_diversifies(self):
        import random
        for i, vid in enumerate(("aaaaaaaaaaa", "aaaaaaaaaab")):
            self.watch(vid, self.CAT, 90, liked=True)
        for vid in ("ddddddddddd", "dddddddddde", "ddddddddddf"):
            self.watch(vid, self.DOG, 0.5, disliked=True)
        d = ts._sh_load()
        items = [{"id": "c%010d" % i, "title": "", "authorId": self.CAT, "views": 10, "src": "kw"} for i in range(5)]
        items += [{"id": "d%010d" % i, "title": "", "authorId": self.DOG, "views": 10**7, "src": "kw"} for i in range(5)]
        items += [{"id": "aaaaaaaaaaa", "title": "", "authorId": self.CAT, "views": 1, "src": "kw"}]
        out = ts.shorts_rank(d, items, 5, rnd=random.Random(1))
        ids = [v["id"] for v in out]
        self.assertNotIn("aaaaaaaaaaa", ids)                               # already seen
        self.assertTrue(all(v["authorId"] != self.DOG for v in out))       # swiped away + disliked
        self.assertLessEqual(sum(v["authorId"] == self.CAT for v in out), 2)  # at most 2 per channel

    def test_reset(self):
        self.watch("aaaaaaaaaaa", self.CAT, 60)
        ts.shorts_reset()
        self.assertEqual(ts._sh_load()["ch"], {})


class ImportExport(unittest.TestCase):
    A, B = "UC" + "a" * 22, "UC" + "b" * 22

    def setUp(self):
        for f in (ts.YTLIB, ts.SHORTS):
            if os.path.exists(f):
                os.remove(f)
        ts._yt_import_fill = lambda *a: None          # no network in tests

    def parse(self, text):
        return ts.ytlib_parse_import(text)

    def test_takeout_csv(self):
        p = self.parse("﻿Channel Id,Channel Url,Channel Title\n"
                       f"{self.A},http://www.youtube.com/channel/{self.A},Cat Channel\n"
                       f"{self.B},http://www.youtube.com/channel/{self.B},\"Dogs, Inc\"\n")
        self.assertEqual(p["format"], "csv")
        self.assertEqual(p["subs"][self.A]["name"], "Cat Channel")
        self.assertEqual(p["subs"][self.B]["name"], "Dogs, Inc")

    def test_invidious_export(self):
        import json
        p = self.parse(json.dumps({"subscriptions": [self.A, self.B], "watch_history": ["jNQXAC9IVRw"],
                                   "playlists": [{"title": "Mix", "videos": ["jNQXAC9IVRw", "bad"]}]}))
        self.assertEqual(p["format"], "invidious")
        self.assertEqual(set(p["subs"]), {self.A, self.B})
        self.assertEqual([h["id"] for h in p["hist"]], ["jNQXAC9IVRw"])
        self.assertEqual([x["id"] for x in p["playlists"][0]["items"]], ["jNQXAC9IVRw"])

    def test_newpipe(self):
        import json
        p = self.parse(json.dumps({"app_version": "0.27", "subscriptions": [
            {"service_id": 0, "url": f"https://www.youtube.com/channel/{self.A}", "name": "Cat Channel"},
            {"service_id": 1, "url": "https://soundcloud.com/x", "name": "Not YouTube"}]}))
        self.assertEqual(p["format"], "newpipe")
        self.assertEqual(p["subs"], {self.A: {"name": "Cat Channel", "thumb": ""}})

    def test_freetube_profiles(self):
        import json
        lines = [json.dumps({"name": "All Channels", "subscriptions": [{"id": self.A, "name": "Cat", "thumbnail": "t"}]}),
                 json.dumps({"name": "Music", "subscriptions": [{"id": self.B, "name": "Dog", "thumbnail": ""}]})]
        p = self.parse("\n".join(lines))
        self.assertEqual(p["format"], "freetube")
        self.assertEqual(set(p["subs"]), {self.A, self.B})

    def test_opml(self):
        p = self.parse('<?xml version="1.0"?><opml version="1.1"><body><outline text="YouTube">'
                       f'<outline text="Cats &amp; Co" title="Cats &amp; Co" type="rss" '
                       f'xmlUrl="https://www.youtube.com/feeds/videos.xml?channel_id={self.A}"/></outline></body></opml>')
        self.assertEqual(p["format"], "opml")
        self.assertEqual(p["subs"][self.A]["name"], "Cats & Co")

    def test_takeout_watch_history(self):
        import json
        p = self.parse(json.dumps([{"header": "YouTube", "title": "Watched Me at the zoo",
                                    "titleUrl": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
                                    "subtitles": [{"name": "jawed", "url": f"https://www.youtube.com/channel/{self.A}"}],
                                    "time": "2024-05-01T10:00:00.000Z"}]))
        self.assertEqual(p["format"], "takeout-history")
        h = p["hist"][0]
        self.assertEqual((h["id"], h["title"], h["author"], h["authorId"]), ("jNQXAC9IVRw", "Me at the zoo", "jawed", self.A))
        self.assertGreater(h["at"], 1700000000)

    def test_garbage_is_rejected(self):
        self.assertEqual(ts.ytlib_import({"text": "hello world"})[0], 400)
        self.assertEqual(ts.ytlib_import({"text": "{\"a\": 1}"})[0], 400)

    def test_backup_round_trip(self):
        ts.ytlib_post("/api/p/yt/sub", {"id": self.A, "name": "Cat Channel", "on": True})
        ts.ytlib_post("/api/p/yt/pos", {"id": "jNQXAC9IVRw", "t": 7, "len": 19,
                                         "meta": {"id": "jNQXAC9IVRw", "title": "Me at the zoo"}})
        ts.ytlib_post("/api/p/yt/pl/new", {"title": "Mix", "video": {"id": "jNQXAC9IVRw", "title": "Me at the zoo"}})
        name, ctype, data = ts.ytlib_export("tubehaus")
        self.assertTrue(name.startswith("tubehaus-backup-"))
        os.remove(ts.YTLIB)
        code, n = ts.ytlib_import({"text": data.decode()})
        self.assertEqual((code, n["format"], n["subs"], n["hist"], n["playlists"]), (200, "tubehaus", 1, 1, 1))
        lib = ts.ytlib_get()
        self.assertEqual(lib["subs"][self.A]["name"], "Cat Channel")
        self.assertEqual(ts.ytlib_query("/api/p/yt/pos", {"ids": "jNQXAC9IVRw"}), {"jNQXAC9IVRw": [7, 19]})
        # importing the same file again adds nothing
        self.assertEqual(ts.ytlib_import({"text": data.decode()})[1]["playlists"], 0)

    def test_other_export_formats(self):
        ts.ytlib_post("/api/p/yt/sub", {"id": self.A, "name": "Cats & \"Co\"", "on": True})
        for fmt in ("invidious", "csv", "opml"):
            _, _, data = ts.ytlib_export(fmt)
            p = self.parse(data.decode())
            self.assertIn(self.A, p["subs"], fmt)
            if fmt != "invidious":
                self.assertEqual(p["subs"][self.A]["name"], "Cats & \"Co\"", fmt)


class PublicMode(unittest.TestCase):
    def setUp(self):
        ts.PUBLIC_MODE = True
        for f in (ts.YTLIB, ts.SHORTS):
            if os.path.exists(f):
                os.remove(f)

    def tearDown(self):
        ts.PUBLIC_MODE = False

    def test_only_stateless_endpoints_are_open(self):
        b = ts.public_blocked
        for m, p in (("GET", "/api/p/yt/lib"), ("POST", "/api/p/yt/sub"), ("POST", "/api/p/yt/pos"),
                     ("GET", "/api/p/yt/hist"), ("GET", "/api/p/yt/cast/devices"), ("POST", "/api/p/yt/cast/send"),
                     ("POST", "/api/p/yt/dl"), ("GET", "/api/p/yt/export"), ("POST", "/api/p/yt/shorts/sig"),
                     ("GET", "/latest_version")):
            self.assertTrue(b(m, p), (m, p))
        for m, p in (("GET", "/api/p/yt/feed"), ("GET", "/api/p/yt/shorts/next"), ("POST", "/api/p/yt/import"),
                     ("POST", "/api/p/yt/export"), ("GET", "/api/v1/videos/jNQXAC9IVRw"), ("GET", "/api/p/health"),
                     ("GET", "/api/p/live/abc/cc.json")):
            self.assertFalse(b(m, p), (m, p))
        ts.PUBLIC_MODE = False
        self.assertFalse(b("GET", "/api/p/yt/lib"))

    def test_import_is_only_parsed_never_stored(self):
        code, p = ts.ytlib_import({"text": "Channel Id,Channel Url,Channel Title\nUC" + "a" * 22 + ",x,Cats\n"})
        self.assertEqual((code, p["dry"], p["format"]), (200, True, "csv"))
        self.assertIn("UC" + "a" * 22, p["subs"])
        self.assertFalse(os.path.exists(ts.YTLIB))

    def test_export_converts_the_visitors_library(self):
        lib = {"subs": {"UC" + "a" * 22: {"name": "Cats"}}, "hist": [], "playlists": {}}
        name, _, data = ts.ytlib_export("csv", lib)
        self.assertIn(b"Cats", data)
        _, _, data = ts.ytlib_export("tubehaus", lib)
        import json
        self.assertEqual(json.loads(data)["shorts"], {})

    def test_health_says_public(self):
        self.assertTrue(ts.health()["public"])


class LoadLimits(unittest.TestCase):
    def setUp(self):
        self.saved = (ts.MAX_VIEWERS, ts.RATE_PER_MIN, ts.vid_fetch)
        ts.viewers.clear()
        ts.rate.clear()

    def tearDown(self):
        ts.MAX_VIEWERS, ts.RATE_PER_MIN, ts.vid_fetch = self.saved
        ts.viewers.clear()
        ts.rate.clear()

    def test_empty_env_means_default(self):
        for v, want in (("", 7), ("  ", 7), ("abc", 7), ("12", 12)):
            os.environ["HT_TEST_INT"] = v
            self.assertEqual(ts.env_int("HT_TEST_INT", 7), want)
        del os.environ["HT_TEST_INT"]
        self.assertEqual(ts.env_int("HT_TEST_INT", 7), 7)

    def test_viewer_cap_lets_current_viewers_stay(self):
        ts.MAX_VIEWERS = 2
        self.assertTrue(ts.viewer_admit("1.1.1.1"))
        self.assertTrue(ts.viewer_admit("2.2.2.2"))
        self.assertFalse(ts.viewer_admit("3.3.3.3"))      # full
        self.assertTrue(ts.viewer_admit("1.1.1.1"))       # already watching
        ts.viewers["1.1.1.1"] -= 600                      # left a while ago
        self.assertTrue(ts.viewer_admit("3.3.3.3"))

    def test_rate_limit_per_ip(self):
        ts.RATE_PER_MIN = 5
        self.assertEqual([ts.rate_ok("9.9.9.9") for _ in range(7)], [True] * 5 + [False] * 2)
        self.assertTrue(ts.rate_ok("8.8.8.8"))            # someone else is unaffected

    def test_same_cold_video_is_fetched_once(self):
        import threading
        calls = []

        def slow_fetch(key):
            calls.append(key)
            time.sleep(0.3)
            body = b'{"videoId": "jNQXAC9IVRw"}'
            ts.vid_store(key, 200, body)
            return 200, body
        ts.vid_fetch = slow_fetch
        key = "/api/v1/videos/jNQXAC9IVRw?test=once"
        out = []
        threads = [threading.Thread(target=lambda: out.append(ts.vid_fetch_once(key))) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(out), 8)
        self.assertTrue(all(code == 200 for code, _ in out))


class VideoPrefetch(unittest.TestCase):
    def test_prefetch_configuration(self):
        # Import fresh configuration with isolated process-environment values.
        for value, want in ((None, 0), ("", 0), ("bad", 0), ("-2", 0), ("2", 2)):
            with self.subTest(value=value), patch.dict(os.environ):
                if value is None:
                    os.environ.pop("HT_VID_PREFETCH", None)
                else:
                    os.environ["HT_VID_PREFETCH"] = value
                cfg_spec = importlib.util.spec_from_file_location("prefetch_config", ts.__file__)
                cfg = importlib.util.module_from_spec(cfg_spec)
                cfg_spec.loader.exec_module(cfg)
                self.assertEqual(cfg.VID_PREFETCH, want)

    def test_disabled_prefetch_makes_no_lookup(self):
        recommended = {"recommendedVideos": [{"videoId": "jNQXAC9IVRw"}]}
        for public, limit in ((False, 0), (True, 2)):
            with self.subTest(public=public), patch.object(ts, "PUBLIC_MODE", public), \
                    patch.object(ts, "VID_PREFETCH", limit), patch.object(ts, "vid_fetch_once") as fetch:
                ts.vid_bg(None, recommended)
                fetch.assert_not_called()

    def test_disabled_prefetch_still_refreshes_requested_video(self):
        key = "/api/v1/videos/jNQXAC9IVRw?test=refresh"
        with patch.object(ts, "VID_PREFETCH", 0), patch.object(ts, "vid_fetch") as fetch:
            ts.vid_busy.add(key)
            ts.vid_bg(key, {"recommendedVideos": [{"videoId": "aqz-KE-bpKQ"}]})
            fetch.assert_called_once_with(key)
            self.assertNotIn(key, ts.vid_busy)

    def test_opt_in_prefetch_skips_cached_and_respects_limit(self):
        hot, cold, extra = "jNQXAC9IVRw", "aqz-KE-bpKQ", "M7lc1UVf-VE"
        recommendations = {"recommendedVideos": [{"videoId": v} for v in ("bad", hot, cold, extra)]}
        with patch.object(ts, "PUBLIC_MODE", False), patch.object(ts, "VID_PREFETCH", 1), \
                patch.object(ts, "vid_cache", {"/api/v1/videos/" + hot: (time.time(), 200, b"{}")}), \
                patch.object(ts, "vid_fetch_once") as fetch, patch.object(ts.time, "sleep"):
            ts.vid_bg(None, recommendations)
            fetch.assert_called_once_with("/api/v1/videos/" + cold)


class Accounts(unittest.TestCase):
    def setUp(self):
        for f in (ts.USERS, ts.SESSION_KEY):
            if os.path.exists(f):
                os.remove(f)
        ts.auth_tries.clear()

    def test_signup_then_session(self):
        code, d = ts.auth_signup({"username": "Alice_1", "password": "correct horse"}, "1.1.1.1")
        self.assertEqual((code, d["user"]), (200, "alice_1"))
        self.assertEqual(ts.session_user(d["cookie"]), "alice_1")
        self.assertNotIn("correct horse", open(ts.USERS).read())          # only a hash is stored

    def test_bad_input_and_duplicates(self):
        sign = lambda u, p, **kw: ts.auth_signup(dict(username=u, password=p, **kw), "2.2.2.2")[0]
        self.assertEqual(sign("ab", "password123"), 400)                    # too short a name
        self.assertEqual(sign("bad name!", "password123"), 400)
        self.assertEqual(sign("bob", "short"), 400)
        self.assertEqual(sign("bob", "12345678"), 400)                      # too guessable
        self.assertEqual(sign("bob", "a fine password", website="spam"), 400)   # honeypot
        self.assertEqual(sign("bob", "a fine password"), 200)
        ts.auth_tries.clear()
        self.assertEqual(sign("bob", "another password"), 409)

    def test_login_and_wrong_password(self):
        ts.auth_signup({"username": "carol", "password": "carol's secret"}, "3.3.3.3")
        self.assertEqual(ts.auth_login({"username": "carol", "password": "nope nope"}, "3.3.3.3")[0], 401)
        self.assertEqual(ts.auth_login({"username": "nobody", "password": "nope nope"}, "3.3.3.3")[0], 401)
        code, d = ts.auth_login({"username": "Carol", "password": "carol's secret"}, "3.3.3.3")
        self.assertEqual((code, ts.session_user(d["cookie"])), (200, "carol"))

    def test_signup_rate_limit_per_network(self):
        codes = [ts.auth_signup({"username": f"user{i}", "password": "a fine password"}, "4.4.4.4")[0] for i in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])
        self.assertEqual(ts.auth_signup({"username": "user9", "password": "a fine password"}, "5.5.5.5")[0], 200)

    def test_tampered_or_expired_sessions_are_rejected(self):
        _, d = ts.auth_signup({"username": "dave", "password": "dave's secret"}, "6.6.6.6")
        user, exp, gen, sig = d["cookie"].split(".")
        self.assertIsNone(ts.session_user(f"mallory.{exp}.{gen}.{sig}"))      # other user, same signature
        self.assertIsNone(ts.session_user(f"{user}.{int(exp) + 999}.{gen}.{sig}"))
        self.assertIsNone(ts.session_user(f"{user}.1.{gen}.{sig}"))
        self.assertIsNone(ts.session_user("garbage"))
        old = ts.session_make("dave", 1)
        import json
        users = json.load(open(ts.USERS))
        users["dave"]["gen"] = 2                                            # password changed / sessions revoked
        json.dump(users, open(ts.USERS, "w"))
        self.assertIsNone(ts.session_user(old))


class Health(unittest.TestCase):
    def test_health(self):
        h = ts.health()
        self.assertTrue(h["ok"])
        self.assertFalse(h["warp_proxy"])


if __name__ == "__main__":
    unittest.main()
