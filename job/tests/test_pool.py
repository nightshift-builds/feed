"""Season windows, standings and circles (plan Task 1; spec 5.2)."""
import unittest

import pool

S1 = (1785430800, 1793908800)
S2 = (1793908800, 1804802400)
SEASONS = [
    {"class_name": "season_1", "name": "Beta Season 1", "intervals": [{"interval": 1, "start_timestamp": S1[0], "end_timestamp": S1[1]}]},
    {"class_name": "season_2", "name": "Beta Season 2", "intervals": [{"interval": 2, "start_timestamp": S2[0], "end_timestamp": S2[1]}]},
]
NOW = 1794916800   # 2026-11-17T12:00:00Z
DAY = 86400


class SeasonWindows(unittest.TestCase):
    def test_season_windows(self):
        w = pool.season_windows(SEASONS, NOW)
        self.assertEqual(w["cur"], (S2[0], S2[1], "Beta Season 2"))
        self.assertEqual(w["prev"], (S1[0], S1[1], "Beta Season 1"))
        self.assertTrue(w["handover"])
        self.assertEqual(w["until"], S2[0] + 28 * DAY)
        later = pool.season_windows(SEASONS, S2[0] + 29 * DAY)
        self.assertFalse(later["handover"])
        self.assertEqual(later["prev"], (S1[0], S1[1], "Beta Season 1"))

    def test_first_season_has_no_prev(self):
        w = pool.season_windows(SEASONS[:1], S1[0] + DAY)
        self.assertIsNone(w["prev"])
        self.assertFalse(w["handover"])

    def test_after_the_last_end_keeps_the_last(self):
        w = pool.season_windows(SEASONS, S2[1] + DAY)
        self.assertEqual(w["cur"][2], "Beta Season 2")


class Standings(unittest.TestCase):
    def test_standings(self):
        cur = [(1, 101, 58600), (2, 111, 65100), (3, 105, 60000)]
        prev = [(1, 112, 71000), (2, 105, 64000), (4, 113, 72000)]
        st = pool.standings(cur, prev, True)
        self.assertEqual(st[1], (112, 71000, True))
        self.assertEqual(st[2], (111, 65100, False))
        self.assertEqual(st[3], (105, 60000, False))
        self.assertEqual(st[4], (113, 72000, True))
        st = pool.standings(cur, prev, False)
        self.assertEqual(st[1], (101, 58600, False))
        self.assertNotIn(4, st)

    def test_missing_badge_is_zero(self):
        st = pool.standings([(5, None, None)], [], False)
        self.assertEqual(st[5], (0, 0, False))


def strong(n, start, badge=115):
    """n accounts above everyone else (badge 115, big values): they fill the global top 300."""
    return {start + i: (badge, 90000 - i, False) for i in range(n)}


class Circles(unittest.TestCase):
    def test_circles_badges(self):
        st = strong(300, 1000)
        st.update({1: (100, 1, False), 2: (101, 1, False), 3: (110, 1, False), 4: (111, 1, False)})
        c = pool.circles(st, {})
        self.assertNotIn(1, c)
        self.assertEqual((c[2], c[3], c[4]), ("asc", "asc", "ete"))
        self.assertEqual(c[1000], "top")
        self.assertEqual(sum(1 for v in c.values() if v == "top"), 300)

    def test_circles_regions(self):
        st, reg = {}, {}
        for i in range(150):   # EU: 150 at Eternus, values 1..150
            st[2000 + i] = (111, 1 + i, False)
            reg[2000 + i] = "eu"
        for i in range(20):    # NA: 20 at Ascendant: Top 100 needs Eternus+ (the circles nest)
            st[3000 + i] = (101, 1 + i, False)
            reg[3000 + i] = "na"
        st[4000] = (120, 99999, False)   # the best of all, region unknown: never a regional top 100
        reg[4000] = None
        c = pool.circles(st, reg)
        eu_top = [a for a in range(2000, 2150) if c[a] == "top"]
        self.assertEqual(len(eu_top), 100)
        self.assertEqual(min(eu_top), 2050)          # the 100 best by (badge, value)
        self.assertEqual(c[2049], "ete")             # the 101st: Eternus
        self.assertTrue(all(c[3000 + i] == "asc" for i in range(20)))
        self.assertEqual(c[4000], "ete")

    def test_small_region_bar(self):
        st, reg = {}, {}
        for r, base in (("na", 5000), ("eu", 6000)):
            for i in range(120):                     # NA and EU: 120 Eternus each; their 100th sits at value 21 / 1021
                st[base + i] = (111, (0 if r == "na" else 1000) + 1 + i, False)
                reg[base + i] = r
        for i in range(30):                          # Asia: 30 Eternus, values 1..30: only those at NA's 100th (21) or above
            st[7000 + i] = (111, 1 + i, False)
            reg[7000 + i] = "asia"
        c = pool.circles(st, reg)
        self.assertEqual([a for a in range(7000, 7030) if c[a] == "top"], list(range(7020, 7030)))
        self.assertEqual(c[7019], "ete")

    def test_circles_regions_mostly_unknown(self):
        st, reg = {}, {}
        for i in range(400):
            st[5000 + i] = (111, 1 + i, False)
            reg[5000 + i] = "eu" if i < 100 else None   # 25 % known: the global top 300
        c = pool.circles(st, reg)
        self.assertEqual(sum(1 for v in c.values() if v == "top"), 300)
        self.assertEqual(c[5399], "top")
        self.assertEqual(c[5000], "ete")


if __name__ == "__main__":
    unittest.main()
