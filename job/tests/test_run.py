"""The whole hourly run on the synthetic World (plan Task 4; spec 5, 6.2, 10)."""
import json
import tempfile
import unittest
from pathlib import Path

import config
import publish
import run
import shape
import state
from tests import build_harness_site
from tests.world import World, acct

NOW = 1794916800          # 2026-11-17T12:00:00Z
DAY = 86400
REPO = Path(__file__).resolve().parents[3]


def rows_of(obj):
    return obj.get("builds") or []


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, world, out="out", st="state", **kw):
        s = state.State(self.d / st).load()
        self.lines = []
        return run.run(world, s, self.d / out, world.now, site_url="https://x.test/", history_dir=self.d / "hist",
                       log=self.lines.append, **kw)

    def index(self, out="out"):
        return json.loads((self.d / out / "data" / "index.json").read_text(encoding="utf-8"))

    def hero(self, hid, out="out", popular=False):
        ix = self.index(out)
        p = self.d / out / "data" / ix["gen"] / ("popular" if popular else "") / ("%d.json" % hid)
        return json.loads(p.read_text(encoding="utf-8"))

    def all_rows(self, out="out"):
        ix = self.index(out)
        out_rows = {}
        for hid in ix["lists"]:
            out_rows[hid] = rows_of(self.hero(hid, out))
        return out_rows


class EndToEnd(Base):
    @classmethod
    def setUpClass(cls):
        cls.world = World(NOW)

    def test_run_end_to_end(self):
        w = World(NOW)
        self.assertEqual(self.go(w), 0, "\n".join(self.lines))
        ix = self.index()
        for k, v in {"inferno": 1, "atlas": 6, "haze": 13, "krill": 18, "mirage": 52}.items():
            self.assertEqual(ix["heroes"][k], v)
        self.assertEqual(ix["gen"], "20261117T1200Z")
        self.assertIsNone(ix["prev"])
        self.assertEqual(ix["made"], "2026-11-17T12:00:00Z")
        self.assertTrue(ix["season"]["handover"])
        self.assertGreaterEqual(len(ix["lists"]), 30)
        self.assertEqual(ix["regions"], ["na", "eu", "asia", "sa", "oce"])
        self.assertGreater(ix["circles"]["asc"], ix["circles"]["ete"])
        self.assertGreater(ix["circles"]["ete"], ix["circles"]["top"])
        for hid in ix["lists"]:
            lst = self.hero(hid)
            self.assertEqual(lst["v"], 1)
            self.assertEqual(lst["gen"], ix["gen"])
            for r in rows_of(lst) + rows_of(self.hero(hid, popular=True)):
                self.assertTrue((self.d / "out" / "data" / "b" / ("%d_%d.json" % (r["id"], r["ver"]))).exists(), r["id"])
        names = {w.name_of(acct(i)) for i in range(1600)}
        self.assertFalse([l for l in self.lines if any(n in l for n in names)])

    def test_style_trend_and_patch_date(self):
        # the ledger's data: bigpatch on every hero list, mix on rows whose items the assets know (sums to 100), tr = [last 7 days,
        # the 7 before] on each circle a row is in (never inside the region views, never on Popular)
        w = World(NOW)
        self.assertEqual(self.go(w), 0, "\n".join(self.lines))
        ix = self.index()
        mixed = trended = 0
        for hid in ix["lists"]:
            lst = self.hero(hid)
            self.assertEqual(lst.get("bigpatch"), shape.ymd(w.big_patch))
            for r in rows_of(lst):
                if "mix" in r:
                    mixed += 1
                    self.assertEqual((len(r["mix"]), sum(r["mix"])), (3, 100), r["id"])
                for C, e in r["use"].items():
                    if e.get("p"):
                        self.assertEqual(len(e["tr"]), 2, (r["id"], C))
                        self.assertLessEqual(max(e["tr"]), e["p"])
                        trended += 1
                    self.assertFalse([x for x in (e.get("r") or {}).values() if "tr" in x])
            for r in rows_of(self.hero(hid, popular=True)):
                self.assertNotIn("tr", (r.get("use") or {}).get("all") or {})
        self.assertGreater(mixed, 0)
        self.assertGreater(trended, 0)

    def test_rules_in_output(self):
        w = World(NOW)
        self.assertEqual(self.go(w), 0)
        rows = self.all_rows()
        ids = {h: {r["id"] for r in rs} for h, rs in rows.items()}
        haze = {r["id"]: r for r in rows[13]}
        self.assertTrue(all(413901 not in s for s in ids.values()))               # the site build: never in High rank
        pop = {r["id"]: r for r in rows_of(self.hero(13, popular=True))}
        self.assertEqual(pop[413901].get("site"), 1)
        self.assertTrue(all(413903 not in s for s in ids.values()))               # the copy: folded into Fast Haze
        self.assertEqual(haze[413902]["use"]["ete"]["p"], 16)
        self.assertEqual(haze[413920]["patch"]["old"], 1)
        self.assertEqual(haze[413921]["patch"]["gone"], 1)
        self.assertEqual(haze[413922]["lang"], "ru")
        self.assertEqual(haze[413923]["name"], "Citadel_HeroBuilds_EarlyGame")
        self.assertEqual(haze[413924]["name"], "Bold line")
        self.assertEqual(haze[413925]["name"], "Curly")
        for rs in rows.values():
            for r in rs:
                self.assertFalse(r["name"].startswith("#") or "<" in r["name"] or "{" in r["name"], r["name"])
                self.assertLessEqual(len(r["run"]), 3)
        self.assertEqual(haze[413926]["author"]["name"], "")                       # protected author
        self.assertNotIn(413927, haze)                                              # dev build
        self.assertTrue(all(1016 not in s for s in ids.values()))
        self.assertLess(sum(1 for r in rows[52] if "ete" in r["use"] and r["use"]["ete"]["p"] > 0), 8)
        five = w.name_of(acct(41))
        ete = sorted((r for r in rows[13] if "ete" in r["use"]), key=lambda r: r["use"]["ete"]["n"])
        self.assertLessEqual(sum(1 for r in ete[:20] if r["author"]["name"] == five), 3)
        self.assertEqual(sum(1 for r in ete if r["author"]["name"] == five), 5)
        eu = [r for r in rows[13] if "eu" in r["use"].get("ete", {}).get("r", {})]
        self.assertTrue(eu)

    def test_no_account_ids_published(self):
        w = World(NOW)
        self.assertEqual(self.go(w), 0)
        self.assertEqual(publish.no_ids(self.d / "out", w.account_ids()), [])
        self.assertEqual(publish.no_ids(self.d / "hist", w.account_ids()), [])

    def test_state_private(self):
        w = World(NOW)
        self.assertEqual(self.go(w), 0)
        names = {p.name for p in (self.d / "out").rglob("*")}
        for f in ("meta.json.gz", "details.json.gz", "names.json", "regions.json", "stats.json", "assets.json.gz"):
            self.assertNotIn(f, names)
        self.assertTrue((self.d / "state" / "meta.json.gz").exists())

    def test_history(self):
        w = World(NOW)
        self.assertEqual(self.go(w), 0)
        h = json.loads((self.d / "hist" / "2026-11-17.json").read_text(encoding="utf-8"))
        self.assertEqual(h["day"], "2026-11-17")
        self.assertIn("13", h["heroes"])
        self.assertLessEqual(len(h["heroes"]["13"]), 10)


class Robustness(Base):
    def test_player_names_cleaned(self):
        w = World(NOW, odd_names=True)
        self.assertEqual(self.go(w), 0)
        names = []
        for rs in self.all_rows().values():
            for r in rs:
                names.append(r["author"]["name"])
                names += [x["name"] for x in r["run"]]
        odd = [n for n in names if n.startswith("#") or "<" in n or "{" in n or "‮" in n or n != n.strip()]
        self.assertEqual(odd, [])
        self.assertIn("Citadel_Foo", names)
        self.assertNotIn("", [x["name"] for rs in self.all_rows().values() for r in rs for x in r["run"]])

    def test_popular_failure_carried(self):
        self.assertEqual(self.go(World(NOW)), 0)
        before = rows_of(self.hero(13, popular=True))
        self.assertEqual(self.go(World(NOW + 3600, fail_popular=True)), 0)
        self.assertEqual([r["id"] for r in rows_of(self.hero(13, popular=True))], [r["id"] for r in before])

    def test_names_failure_keeps_old_names(self):
        self.assertEqual(self.go(World(NOW)), 0)
        self.assertEqual(self.go(World(NOW + 25 * 3600, fail_names=True)), 0)
        named = [r["author"]["name"] for r in rows_of(self.hero(13)) if r["author"]["name"]]
        self.assertGreater(len(named), 10)

    def test_details_failure_not_remembered_as_missing(self):
        self.assertEqual(self.go(World(NOW, fail_details=True), validate=False), 0)
        self.assertEqual(self.go(World(NOW + 3600)), 0)
        self.assertIn(600001, [r["id"] for r in rows_of(self.hero(200))])

    def test_validation_heals_after_a_steady_new_level(self):
        # final review: a failure never healed; six failing runs at one steady level are taken as the new normal
        self.assertEqual(self.go(World(NOW, s2_age=40)), 0)
        gen1 = self.index()["gen"]
        rcs = [self.go(World(NOW + k * 3600, pool_share=0.4, s2_age=40)) for k in range(1, 7)]
        self.assertEqual(rcs, [1, 1, 1, 1, 1, 0])
        self.assertNotEqual(self.index()["gen"], gen1)
        self.assertTrue(any("new level" in l for l in self.lines))
        self.assertEqual(self.go(World(NOW + 8 * 3600, pool_share=0.4, s2_age=40)), 0)


class LaterRuns(Base):
    def test_second_run_uses_caches(self):
        w1 = World(NOW)
        self.assertEqual(self.go(w1), 0)
        gen1 = self.index()["gen"]
        w2 = World(NOW + 3600, bump=(413902, 1800))
        self.assertEqual(self.go(w2), 0, "\n".join(self.lines))
        kinds = [c[0] for c in w2.calls]
        self.assertNotIn("meta_seed", kinds)
        self.assertIn("meta_since", kinds)
        self.assertEqual(sum(c[1] for c in w2.calls if c[0] == "details"), 1)
        self.assertNotIn("assets", kinds)
        self.assertLess(w2.count, w1.count)
        ix = self.index()
        self.assertEqual(ix["prev"], gen1)
        self.assertTrue((self.d / "out" / "data" / gen1 / "13.json").exists())
        haze = {r["id"]: r for r in rows_of(self.hero(13))}
        self.assertEqual(haze[413902]["ver"], w2.builds[413902]["version"])

    def test_assets_of_an_older_shape_are_fetched_again(self):
        # 19 Nov: assets cached before the items carried their slot and cost were kept for the day they live, so no row had a mix
        self.assertEqual(self.go(World(NOW)), 0)
        s = state.State(self.d / "state").load()
        d = s.assets["data"]
        s.assets = {"at": s.assets["at"], "data": dict(d, items_up={k: v[:2] for k, v in d["items_up"].items()})}
        s.save()
        w2 = World(NOW + 3600)
        self.assertEqual(self.go(w2), 0, "\n".join(self.lines))
        self.assertIn("assets", [c[0] for c in w2.calls])
        self.assertTrue(any(r.get("mix") for r in rows_of(self.hero(13))))

    def test_rows_carry_all_ranks(self):
        w = World(NOW)
        self.assertEqual(self.go(w), 0, "\n".join(self.lines))
        ans = {int(x["hero_build_id"]): (x["matches"], x["wins"]) for x in World(NOW).popular(0, 0)}
        rows = rows_of(self.hero(13))
        seen = 0
        for r in rows:
            self.assertFalse(any("ar" in e for e in r["use"].values()), r["id"])
            if r["id"] in ans:
                self.assertEqual(r["ar"], {"g": ans[r["id"]][0], "w": ans[r["id"]][1]}, r["id"])
                seen += 1
            else:
                self.assertNotIn("ar", r)
        self.assertTrue(seen)
        self.assertEqual(self.go(World(NOW, fail_popular=True), out="out2", st="state2"), 0, "\n".join(self.lines))
        for hid in self.index("out2")["lists"]:
            for r in rows_of(self.hero(hid, "out2")):
                self.assertNotIn("ar", r)

    def test_prev_season_kept_in_state(self):
        w1 = World(NOW)
        self.assertEqual(self.go(w1), 0)
        ete1 = self.index()["circles"]["ete"]
        prev = [c for c in w1.calls if c[0] == "scoreboard" and c[2] <= w1.s2]
        self.assertEqual(len(prev), 1)
        w2 = World(NOW + 3600)
        self.assertEqual(self.go(w2), 0)
        self.assertEqual([c for c in w2.calls if c[0] == "scoreboard" and c[2] <= w2.s2], [])   # last season's finals: from the state
        self.assertEqual(self.index()["circles"]["ete"], ete1)

    def test_prev_season_narrowed_on_504(self):
        w = World(NOW, sb_fail_wide=True)
        self.assertEqual(self.go(w), 0, "\n".join(self.lines))
        prev = [c for c in w.calls if c[0] == "scoreboard" and c[2] <= w.s2]
        self.assertEqual(len(prev), 2)
        self.assertEqual(prev[1][2] - prev[1][1], 90 * 86400)
        self.assertEqual(self.index()["circles"]["ete"], 270)      # the 50 lifted by last season still count
        w2 = World(NOW + 3600)                                     # the full window answers again: read once, then kept
        self.assertEqual(self.go(w2), 0)
        self.assertEqual(len([c for c in w2.calls if c[0] == "scoreboard" and c[2] <= w2.s2]), 1)
        w3 = World(NOW + 7200)
        self.assertEqual(self.go(w3), 0)
        self.assertEqual([c for c in w3.calls if c[0] == "scoreboard" and c[2] <= w3.s2], [])

    def test_validation_failure_writes_nothing(self):
        # outside the handover (Season 2 40 days old): a source answering a shrunk pool fails the run
        self.assertEqual(self.go(World(NOW, s2_age=40)), 0)
        gen1 = self.index()["gen"]
        self.assertEqual(self.go(World(NOW + 3600, pool_share=0.4, s2_age=40)), 1)
        self.assertEqual(self.index()["gen"], gen1)
        self.assertTrue(any("validation" in l for l in self.lines))

    def test_pool_games_kept_between_runs(self):
        # 20 Nov: the pool's games of the window live in the state with the data lake's watermark; a later run reads only the lake
        # files that came since, never the whole window again
        w1 = World(NOW)
        self.assertEqual(self.go(w1), 0)
        first = [c for c in w1.calls if c[0] == "pool_lake"]
        self.assertEqual(first, [("pool_lake", NOW - config.WINDOW_DAYS * DAY, {})])
        kept = state.State(self.d / "state").load().rows
        self.assertEqual((kept["until"], kept["lake"]["wm"]), (NOW, NOW))
        self.assertGreater(len(kept["rows"]), 1000)
        w2 = World(NOW + 3600)
        self.assertEqual(self.go(w2), 0, "\n".join(self.lines))
        second = [c for c in w2.calls if c[0] == "pool_lake"]
        self.assertEqual(second[0][2]["wm"], NOW)
        rows = state.State(self.d / "state").load().rows["rows"]
        self.assertEqual(len({(r[0], r[1]) for r in rows}), len(rows))
        self.assertTrue(all(r[5] >= NOW + 3600 - config.WINDOW_DAYS * DAY for r in rows))
        self.assertTrue(any("since the last run" in l for l in self.lines), "\n".join(self.lines))

    def test_pool_games_from_the_state_when_the_fetch_fails(self):
        self.assertEqual(self.go(World(NOW)), 0)
        gen1 = self.index()["gen"]
        self.assertEqual(self.go(World(NOW + 3600, fail_pool_rows=True)), 0, "\n".join(self.lines))
        ix = self.index()
        self.assertNotEqual(ix["gen"], gen1)
        self.assertEqual(ix["carried"], [])
        self.assertTrue(any("pool games not read" in l for l in self.lines), "\n".join(self.lines))
        self.assertEqual(state.State(self.d / "state").load().rows["lake"]["wm"], NOW)

    def test_whole_window_read_goes_on_from_where_it_stopped(self):
        # the first fill reads the whole window (about 160 lake files): batches that came are kept, so a run cut short leaves the
        # next one only the rest
        w1 = World(NOW, fail_pool_rows_after=10)
        with self.assertRaises(run.api_mod.ApiError):
            self.go(w1)
        since = NOW - config.WINDOW_DAYS * DAY
        kept = state.State(self.d / "state").load().rows
        self.assertEqual(kept["lake"]["wm"], since - 1 + 10 * 6 * 3600)
        w2 = World(NOW)
        self.assertEqual(self.go(w2), 0, "\n".join(self.lines))
        self.assertEqual([c[2]["wm"] for c in w2.calls if c[0] == "pool_lake"], [since - 1 + 10 * 6 * 3600])

    def test_stale_pool_games_stop_the_run(self):
        # games older than ROWS_STALE (or none) and a failed fetch: nothing is rebuilt, the last deploy stays live (main: exit 2)
        self.assertEqual(self.go(World(NOW)), 0)
        gen1 = self.index()["gen"]
        with self.assertRaises(run.api_mod.ApiError):
            self.go(World(NOW + config.ROWS_STALE + 3600, fail_pool_rows=True))
        self.assertEqual(self.index()["gen"], gen1)
        with self.assertRaises(run.api_mod.ApiError):
            self.go(World(NOW, fail_pool_rows=True), out="out2", st="s2")

    def test_prev_gen_from_site(self):
        self.assertEqual(self.go(World(NOW), out="out1", st="s1"), 0)
        gen1 = self.index("out1")["gen"]
        w2 = World(NOW + 3600)
        for p in (self.d / "out1").rglob("*.json"):
            w2.site[p.relative_to(self.d / "out1").as_posix()] = p.read_bytes()
        self.assertEqual(self.go(w2, out="out2", st="s2"), 0)
        self.assertEqual(self.index("out2")["prev"], gen1)
        self.assertTrue((self.d / "out2" / "data" / gen1 / "13.json").exists())
        self.assertEqual(self.go(World(NOW + 3600), out="out3", st="s3"), 0)    # the site answers nothing
        self.assertIsNone(self.index("out3")["prev"])


class Fixture(unittest.TestCase):
    # the harness fixture lives in the mod's repository; the organization's repository (feed/ at its root) has no tools/harness
    @unittest.skipUnless((REPO / "tools" / "harness").is_dir(), "the mod's harness is not here (the organization's repository)")
    def test_harness_fixture_current(self):
        with tempfile.TemporaryDirectory() as d:
            build_harness_site.build(Path(d))
            want = {p.relative_to(d).as_posix(): p.read_bytes() for p in Path(d).rglob("*") if p.is_file()}
        fix = REPO / "tools" / "harness" / "fixtures" / "feed_site"
        have = {p.relative_to(fix).as_posix(): p.read_bytes() for p in fix.rglob("*") if p.is_file()}
        self.assertEqual(sorted(have), sorted(want))
        self.assertEqual([k for k in want if have.get(k) != want[k]], [])


if __name__ == "__main__":
    unittest.main()
