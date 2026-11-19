"""Usage, scores and list selection (plan Task 2; spec 5.3-5.5)."""
import math
import unittest

import rank

DAY = 86400
NOW = 1794916800


def row(acct, bid, t, won=False):
    return {"account_id": acct, "hero_build_id": bid, "won": won, "start_time": t}


def meta(hero, author, upd, name="Build", desc="", dev=False, ver=1, lang=0):
    return {"hero": hero, "author": author, "upd": upd, "ver": ver, "lang": lang, "name": name, "desc": desc, "dev": dev}


class Aggregate(unittest.TestCase):
    def test_aggregate_counts(self):
        circ = {1: "ete", 2: "asc"}
        rows = [row(1, 10, NOW - 5 * DAY, True), row(1, 10, NOW - 4 * DAY, True), row(1, 10, NOW - 3 * DAY), row(1, 11, NOW - 2 * DAY),
                row(1, None, NOW - DAY), row(2, 10, NOW - 6 * DAY), row(2, 77, NOW - DAY), row(9, 10, NOW)]   # 9: not in the pool
        u = rank.aggregate(rows, circ, {}, NOW, {10, 11})
        self.assertEqual(u.runs[10][1], [3, 2, NOW - 3 * DAY, NOW - 5 * DAY])   # games, wins, last and first start_time
        self.assertEqual(u.main[1], 10)
        self.assertEqual(u.main[2], 77)        # one game each on 10 and 77: the later last game wins
        self.assertEqual(u.games, 7)
        self.assertEqual(u.known, 5)
        self.assertEqual(u.plays[1], 5)
        self.assertNotIn(9, u.plays)
        self.assertNotIn(77, u.runs)           # unpublished: counted only in the cover

    def test_aliased_usage_merges(self):
        circ = {4: "asc"}
        rows = [row(4, 20, NOW - DAY), row(4, 20, NOW - 2 * DAY), row(4, 21, NOW - 3 * DAY)]
        u = rank.aggregate(rows, circ, {20: 21}, NOW, {20, 21})
        self.assertEqual(u.runs[21][4][0], 3)
        self.assertNotIn(20, u.runs)
        self.assertEqual(u.main[4], 21)


class Trend(unittest.TestCase):
    def test_trend_halves(self):
        # tr = [players with a game on the build in the last 7 days, players with one in the 7 days before]: 1 played in both halves,
        # 2 only lately, 3 only before, 4 is Ascendant (not in Eternus+)
        circ = {1: "ete", 2: "ete", 3: "ete", 4: "asc"}
        rows = [row(1, 10, NOW - DAY), row(1, 10, NOW - 10 * DAY), row(2, 10, NOW - 2 * DAY), row(3, 10, NOW - 9 * DAY), row(4, 10, NOW - DAY)]
        u = rank.aggregate(rows, circ, {}, NOW, {10})
        self.assertEqual(rank.use_of(u, 10, "ete", circ, NOW)["tr"], [2, 2])
        self.assertEqual(rank.use_of(u, 10, "asc", circ, NOW)["tr"], [3, 2])
        self.assertEqual(rank.use_of(u, 99, "ete", circ, NOW)["tr"], [0, 0])


class Use(unittest.TestCase):
    def setUp(self):
        circ = {1: "top", 2: "ete", 3: "asc"}
        rows = [row(1, 10, NOW - DAY), row(2, 10, NOW - DAY), row(2, 11, NOW - DAY), row(2, 11, NOW - 2 * DAY), row(3, 10, NOW - 9 * DAY)]
        self.circ = circ
        self.u = rank.aggregate(rows, circ, {}, NOW, {10, 11})

    def test_use_exact(self):
        a = rank.use_of(self.u, 10, "asc", self.circ, NOW)
        self.assertAlmostEqual(a["use"], 3.25)
        self.assertEqual((a["p"], a["g"], a["last"]), (3, 3, NOW - DAY))
        e = rank.use_of(self.u, 10, "ete", self.circ, NOW)
        self.assertAlmostEqual(e["use"], 2.75)
        self.assertEqual(e["p"], 2)
        t = rank.use_of(self.u, 10, "top", self.circ, NOW)
        self.assertAlmostEqual(t["use"], 2.0)
        self.assertEqual(t["p"], 1)
        none = rank.use_of(self.u, 99, "asc", self.circ, NOW)
        self.assertEqual((none["use"], none["p"], none["g"], none["w"], none["last"]), (0, 0, 0, 0, 0))

    def test_region_use(self):
        reg = {1: "eu", 2: "na", 3: "eu"}
        eu = rank.use_of(self.u, 10, "asc", self.circ, NOW, region="eu", region_of_acct=reg)
        self.assertEqual(eu["p"], 2)
        self.assertAlmostEqual(eu["use"], 2.5)
        r = rank.regions_for(self.u, 11, "asc", self.circ, NOW, reg, author_chip="eu", author_pts=3, fresh_pts=0)
        self.assertEqual(set(r), {"na", "eu"})      # run in NA; written by an EU author
        self.assertEqual(r["eu"]["p"], 0)
        self.assertEqual(r["eu"]["best"], 3.0)
        self.assertEqual(r["na"]["p"], 1)
        r2 = rank.regions_for(self.u, 11, "asc", self.circ, NOW, reg, author_chip=None, author_pts=0, fresh_pts=0)
        self.assertEqual(set(r2), {"na"})            # run only in NA: absent from EU


class Parts(unittest.TestCase):
    def test_author_part(self):
        self.assertEqual([rank.author_part("top", c) for c in ("top", "ete", "asc")], [4, 4, 4])
        self.assertEqual([rank.author_part("ete", c) for c in ("top", "ete", "asc")], [1, 3, 3])
        self.assertEqual([rank.author_part("asc", c) for c in ("top", "ete", "asc")], [1, 1, 2])
        self.assertEqual(rank.author_part(None, "asc"), 0)

    def test_fresh_part(self):
        patch = NOW - 30 * DAY
        self.assertEqual(rank.fresh_part(patch - DAY, patch, False, 0), -1)
        self.assertEqual(rank.fresh_part(patch - DAY, patch, True, 0), 0)
        self.assertEqual(rank.fresh_part(patch + DAY, patch, False, 1), -0.5)
        self.assertEqual(rank.fresh_part(patch + DAY, patch, False, 3), -1)
        self.assertEqual(rank.fresh_part(patch - DAY, patch, False, 2), -2)

    def test_best_formula(self):
        self.assertEqual(rank.best(3.25, 3, -0.5), round(3 * math.log2(4.25) + 2.5, 3))
        self.assertEqual(rank.best(0, 2, 0), 2.0)


class Candidates(unittest.TestCase):
    def test_candidates_rules(self):
        H = 13
        circ = {1: "ete", 2: "asc", 3: "asc"}
        m = {
            100: meta(H, 1, NOW - 10 * DAY),                    # ete author, fresh
            101: meta(H, 2, NOW - 10 * DAY),                    # asc author
            102: meta(H, 1, NOW - 91 * DAY),                    # ete author, too old, nobody ran it
            103: meta(H, 9, NOW - 10 * DAY),                    # outside author, run by an asc runner
            104: meta(H, 9, NOW - 10 * DAY, dev=True),          # dev build, run
            105: meta(H, 9, NOW - DAY, name="Tracklock auto [tracklock.gg]"),   # site build, run
            106: meta(H, 1, NOW - DAY, desc="made with tracklock data"),         # a pool author's: kept
            107: meta(6, 1, NOW - DAY),                         # another hero
        }
        rows = [row(3, 103, NOW - DAY), row(3, 104, NOW - DAY), row(3, 105, NOW - DAY), row(3, 555, NOW - DAY)]
        u = rank.aggregate(rows, circ, {}, NOW, set(m))
        self.assertEqual(rank.candidates(H, m, u, circ, "ete", NOW), [100, 106])
        self.assertEqual(rank.candidates(H, m, u, circ, "asc", NOW), [100, 101, 103, 106])

    def test_is_site(self):
        self.assertTrue(rank.is_site(meta(1, 9, 0, name="Fast [TRACKLOCK.GG]"), False))
        self.assertTrue(rank.is_site(meta(1, 9, 0, desc="from Mobalytics"), False))
        self.assertFalse(rank.is_site(meta(1, 9, 0, name="Fast [tracklock.gg]"), True))
        self.assertFalse(rank.is_site(meta(1, 9, 0, name="Fast lane"), False))


class Dupes(unittest.TestCase):
    def test_dupes(self):
        A = frozenset({"upgrade_a", "upgrade_b"})
        B = frozenset({"upgrade_c"})
        m = {
            5: meta(13, 1, NOW - 9 * DAY, name="Old"), 9: meta(13, 1, NOW - DAY, name="New"),      # same author, same items
            20: meta(13, 2, NOW - DAY, name="Fast"), 21: meta(13, 3, NOW, name="Copy of Fast"),   # copy with the same items
            22: meta(13, 4, NOW, name="copy of fast"),                                             # copy with other items
            30: meta(13, 5, NOW, name="Empty"), 31: meta(13, 5, NOW - DAY, name="Empty 2"),       # no items: never folded
        }
        items = {5: A, 9: A, 20: A | B, 21: A | B, 22: B, 30: frozenset(), 31: frozenset()}
        self.assertEqual(rank.dupes(items, m), {5: 9, 21: 20})


class Select(unittest.TestCase):
    def test_select_order_and_caps(self):
        sc = []
        for i in range(30):
            sc.append({"bid": 1000 + i, "best": 100 - i, "p": 0, "upd": 0, "author": 500 + i})
        for k, i in enumerate((0, 2, 4, 6, 7)):     # author A holds 5 builds within the first 8 places
            sc[i]["author"] = 1
        ids = rank.select(sc, "ete")
        self.assertEqual(len(ids), 25)
        first20 = ids[:20]
        self.assertEqual(sum(1 for b in first20 if sc[b - 1000]["author"] == 1), 3)
        self.assertEqual(ids[20:22], [1006, 1007])   # the two moved after place 20, in their own order
        tie = [{"bid": 1, "best": 5, "p": 2, "upd": 10, "author": 1}, {"bid": 2, "best": 5, "p": 3, "upd": 5, "author": 2},
               {"bid": 3, "best": 5, "p": 3, "upd": 9, "author": 3}, {"bid": 4, "best": 5, "p": 3, "upd": 9, "author": 4}]
        self.assertEqual(rank.select(tie, "asc"), [4, 3, 2, 1])


if __name__ == "__main__":
    unittest.main()
