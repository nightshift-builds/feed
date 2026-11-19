"""The deadlock-api client, the sources and the job's private state (plan Task 3)."""
import gzip
import json
import os
import tempfile
import unittest
import urllib.parse

import api
import sources
import state


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


class FakeOpener:
    """Scripted answers: each item is (status, headers, body) or an exception to raise."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.reqs = []

    def __call__(self, req, timeout):
        self.reqs.append(req)
        a = self.answers.pop(0) if self.answers else (200, {}, b"{}")
        if isinstance(a, Exception):
            raise a
        st, hd, body = a
        return st, hd, body if isinstance(body, bytes) else json.dumps(body).encode()


def client(answers, key=None):
    c = FakeClock()
    o = FakeOpener(answers)
    return api.Api(base="https://x.test", ua="UA/1", key=key, opener=o, sleep=c.sleep, clock=c.clock), o, c


class Client(unittest.TestCase):
    def test_pacing(self):
        a, o, c = client([(200, {}, [1]), (200, {}, [2]), (200, {}, [3])])
        self.assertEqual([a.get("/p", {}) for _ in range(3)], [[1], [2], [3]])
        self.assertGreaterEqual(sum(c.sleeps), 1.0)
        self.assertEqual(a.count, 3)

    def test_retry_after(self):
        a, o, c = client([(429, {"Retry-After": "3"}, b""), (200, {}, {"ok": 1})])
        self.assertEqual(a.get("/p", {}), {"ok": 1})
        self.assertEqual(c.sleeps, [3])
        self.assertEqual(len(o.reqs), 2)
        a, o, c = client([(503, {}, b""), (200, {}, {"ok": 2})])
        self.assertEqual(a.get("/p", {}), {"ok": 2})
        self.assertEqual(c.sleeps, [1])

    def test_gives_up(self):
        a, o, c = client([(503, {}, b"")] * 4)
        with self.assertRaises(api.ApiError) as e:
            a.get("/p", {})
        self.assertEqual(e.exception.status, 503)
        self.assertEqual(len(o.reqs), 4)
        a, o, c = client([(504, {"Retry-After": "120"}, b"")])
        with self.assertRaises(api.ApiError) as e:
            a.get("/p", {})
        self.assertEqual((e.exception.status, len(o.reqs)), (504, 1))
        a, o, c = client([OSError("no route")])
        with self.assertRaises(api.ApiError) as e:
            a.get("/p", {})
        self.assertEqual(e.exception.status, 0)
        a, o, c = client([(200, {}, b"not json")])
        with self.assertRaises(api.ApiError):
            a.get("/p", {})

    def test_headers(self):
        a, o, c = client([(200, {}, {})])
        a.get("/p", {})
        h = {k.lower(): v for k, v in o.reqs[0].header_items()}
        self.assertEqual(h["user-agent"], "UA/1")
        self.assertNotIn("x-api-key", h)
        a, o, c = client([(200, {}, {})], key="k123")
        a.get("/p", {})
        h = {k.lower(): v for k, v in o.reqs[0].header_items()}
        self.assertEqual(h["x-api-key"], "k123")

    def test_list_params(self):
        a, o, c = client([(200, {}, {})])
        a.get("/x", {"account_ids": [1, 2], "a": "b", "flag": True, "none": None})
        u = urllib.parse.urlsplit(o.reqs[0].full_url)
        self.assertEqual(u.path, "/x")
        self.assertEqual(u.query, "account_ids=1,2&a=b&flag=true")

    def test_gql(self):
        a, o, c = client([(200, {}, {"data": {"x": [1]}})])
        self.assertEqual(a.gql("{ x }"), {"x": [1]})
        r = o.reqs[0]
        self.assertEqual(r.get_method(), "POST")
        self.assertEqual(json.loads(r.data.decode()), {"query": "{ x }"})
        self.assertTrue(r.full_url.endswith("/v1/graphql"))

    def test_gql_error_text_stays_out(self):
        # final review: the server's GraphQL error text could echo part of the query (account ids) into the public Actions log
        a, o, c = client([(200, {}, {"errors": [{"message": "parse failed near [9000123, 9000124]"}], "data": None})])
        with self.assertRaises(api.ApiError) as e:
            a.gql("{ x }")
        self.assertNotRegex(str(e.exception), r"\d{6,}")

    def test_gql_errors(self):
        a, o, c = client([(200, {}, {"errors": [{"message": "too complex"}], "data": None})])
        with self.assertRaises(api.ApiError) as e:
            a.gql("{ x }")
        self.assertEqual(e.exception.status, 200)


class FakeApi:
    def __init__(self, get=None, gql=None):
        self._get, self._gql = get, gql
        self.gets, self.gqls = [], []

    def get(self, path, params):
        self.gets.append((path, dict(params)))
        return self._get(path, params)

    def gql(self, q):
        self.gqls.append(q)
        return self._gql(q)


class Sources(unittest.TestCase):
    def test_scoreboard_pages(self):
        def page(path, p):
            if "start" not in p:      # the first page leaves start out: the URL the edge cache already knows
                return [{"account_id": i, "badge": 112 if i < 9999 else 102, "value": 70000 - i} for i in range(10000)]
            return [{"account_id": 20000 + i, "badge": 101, "value": 1} for i in range(3)]
        f = FakeApi(get=page)
        rows = sources.scoreboard(f, 1700000123, 1700100123)
        self.assertEqual(len(rows), 10003)
        self.assertEqual(len(f.gets), 2)
        p = f.gets[0][1]
        self.assertEqual((p["sort_by"], p["match_mode"], p["limit"], p["min_matches"]), ("rank", "ranked", 10000, 1))
        self.assertEqual((p["min_unix_timestamp"] % 3600, p["max_unix_timestamp"] % 3600), (0, 0))
        f = FakeApi(get=lambda path, p: [{"account_id": i, "badge": 99, "value": 1} for i in range(10000)])
        sources.scoreboard(f, 0, 7200)
        self.assertEqual(len(f.gets), 1)

    def test_hero_rows_pages(self):
        calls = []

        def g(q):
            calls.append(q)
            n = 10000 if len(calls) == 1 else 7
            return {"match_players": [{"account_id": 1, "hero_build_id": 5, "won": True, "start_time": 9}] * n}
        f = FakeApi(gql=g)
        rows = sources.hero_rows(f, 18, [3, 1, 2], 1000)
        self.assertEqual(len(rows), 10007)
        self.assertIn("account_id: {in: [1, 2, 3]}", calls[0])
        self.assertIn('game_mode: {eq: "Normal"}', calls[0])
        self.assertIn("hero_id: {eq: 18}", calls[0])
        self.assertIn("offset: 10000", calls[1])

    def test_details_batches(self):
        pairs = [(18, 1000 + i) for i in range(45)]

        def g(q):
            n = q.count("hero_builds(")
            if n > 1 and "build_id: 1020," in q:
                raise api.ApiError("too complex", 200)
            out = {}
            import re
            for alias, bid in re.findall(r"(b\d+): hero_builds\(where: \{hero_id: \d+, build_id: (\d+),", q):
                out[alias] = [{"hero_build": {"hero_build_id": int(bid), "hero_id": 18, "version": 3}}]
            return out
        f = FakeApi(gql=g)
        got = sources.details(f, pairs)
        self.assertEqual(sorted(got), [1000 + i for i in range(45)])
        sizes = [q.count("hero_builds(") for q in f.gqls]
        self.assertEqual(sizes[0], 20)
        self.assertIn("b19: hero_builds(", f.gqls[0])
        self.assertEqual(sizes, [20, 20] + [1] * 20 + [5])
        self.assertIn("ability_order { currency_changes { ability_id currency_type delta } }", f.gqls[0])

    def test_details_rate_limited_no_fanout(self):
        pairs = [(18, 1000 + i) for i in range(30)]

        def g(q):
            raise api.ApiError("http 429", 429)
        f = FakeApi(gql=g)
        failed = []
        self.assertEqual(sources.details(f, pairs, failed), {})
        self.assertEqual(len(f.gqls), 2)                      # two batches tried, no single calls after a rate limit
        self.assertEqual(sorted(failed), sorted(pairs))

    def test_names_and_regions(self):
        f = FakeApi(get=lambda path, p: [{"account_id": a, "personaname": "P%d" % a} for a in p["account_ids"] if a != 3])
        self.assertEqual(sources.names(f, [1, 2, 3]), {1: "P1", 2: "P2"})
        ids = list(range(1, 1502))
        f = FakeApi(get=lambda path, p: [{"account_id": a, "region": "eu_north" if a % 2 else "moon"} for a in p["account_ids"]])
        r = sources.regions(f, ids)
        self.assertEqual(len(f.gets), 2)
        self.assertEqual((r[1], r[2]), ("eu", None))

    def test_assets(self):
        def get(path, p):
            if path == "/v1/assets/heroes":
                return [{"id": 6, "class_name": "hero_atlas", "player_selectable": True, "disabled": False,
                         "items": {"signature1": "ab_heal", "signature2": "ab_charge", "signature3": "ab_beefy", "signature4": "ab_leap"}},
                        {"id": 99, "class_name": "hero_test", "player_selectable": False, "disabled": False, "items": {}}]
            if path.endswith("/upgrade"):
                return [{"id": 11, "class_name": "upgrade_clip_size", "shopable": True, "item_slot_type": "weapon", "cost": 800}, {"id": 12, "class_name": "upgrade_old", "shopable": False}]
            if path.endswith("/ability"):
                return [{"id": 21, "class_name": "ab_heal"}, {"id": 22, "class_name": "ab_charge"}, {"id": 23, "class_name": "ab_beefy"},
                        {"id": 24, "class_name": "ab_leap"}]
            if path == "/v1/patches/big-days":
                return ["2026-08-01T10:00:00Z", "2026-09-29T20:25:00Z"]
        a = sources.assets(FakeApi(get=get))
        self.assertEqual(a["heroes"][6]["key"], "atlas")
        self.assertEqual(a["heroes"][6]["slots"], {21: 1, 22: 2, 23: 3, 24: 4})
        self.assertNotIn(99, a["heroes"])
        self.assertEqual(a["items_up"][11], ["upgrade_clip_size", True, "g", 800])   # slot and cost: the style mix
        self.assertEqual(a["items_up"][12][2:], ["", 0])   # no slot or cost given
        self.assertEqual(a["items_ab"][24], "ab_leap")
        self.assertEqual(a["big_patch"], 1790713500)


class State(unittest.TestCase):
    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            s = state.State(d)
            s.load()
            s.meta["builds"]["5"] = {"hero": 1}
            s.names["7"] = ["Name", 100]
            s.stats = {"pool": 1200}
            s.save()
            with open(os.path.join(d, "meta.json.gz"), "rb") as f:
                raw = f.read()
            self.assertEqual(raw[:2], b"\x1f\x8b")
            json.loads(gzip.decompress(raw))
            t = state.State(d)
            t.load()
            self.assertEqual(t.meta["builds"]["5"], {"hero": 1})
            self.assertEqual(t.names["7"], ["Name", 100])
            self.assertEqual(t.stats, {"pool": 1200})
            s.save_lists({"data/g1/1.json": b"{}"})
            self.assertEqual(state.State(d).load_lists(), {"data/g1/1.json": b"{}"})

    def test_names_and_regions_due(self):
        with tempfile.TemporaryDirectory() as d:
            s = state.State(d)
            s.load()
            s.names = {"1": ["A", 1000], "2": ["B", 1000 - 90000]}
            have, missing = s.names_fresh([1, 2, 3], 1000)
            self.assertEqual((have, missing), ({1: "A"}, [2, 3]))
            s.regions = {"1": ["eu", 1000], "2": [None, 1000 - 8 * 86400]}
            self.assertEqual(s.regions_due([1, 2, 3, 4], 1000, 2), [2, 3])
            self.assertEqual(s.region_map(1000), {1: "eu"})

    def test_dirs_kept_apart(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                state.check_dirs(os.path.join(d, "state", "out"), os.path.join(d, "state"))
            with self.assertRaises(ValueError):
                state.check_dirs(os.path.join(d, "out"), os.path.join(d, "out", "state"))
            state.check_dirs(os.path.join(d, "out"), os.path.join(d, "state"))


if __name__ == "__main__":
    unittest.main()
