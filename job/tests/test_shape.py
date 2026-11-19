"""The published JSON shapes and the size guard (plan Task 4; spec 6.2)."""
import json
import unittest

import config
import shape

UP = {1: ["upgrade_a", True], 2: ["upgrade_b", True], 3: ["upgrade_c", True], 4: ["upgrade_d", False]}
SLOTS = {91: 1, 92: 2, 93: 3, 94: 4}


def full(cats, changes=None, desc="Rush <b>a</b>. {s:x}"):
    return {"hero_build_id": 7, "hero_id": 1, "version": 3, "description": desc,
            "details": {"mod_categories": cats, "ability_order": {"currency_changes": changes or []}}}


class Row(unittest.TestCase):
    def test_row_keys(self):
        m = {"ver": 4, "name": "<b>Fast</b> one", "lang": 8, "upd": 1794916800}
        author = shape.author("Nova", (112, 70000, True), "eu", 37, 12)
        use = {"ete": {"p": 3, "g": 9, "w": 5, "last": 1794900000, "best": 7.25, "r": {"eu": {"p": 2, "g": 6, "w": 3, "best": 6.0}}}}
        r = shape.row(77, m, author, use, [{"name": "Kite", "badge": 113, "g": 4}], {"old": 0, "gone": 1}, site=False)
        self.assertEqual(set(r), {"id", "ver", "name", "lang", "upd", "author", "use", "run", "patch"})
        self.assertEqual((r["id"], r["ver"], r["name"], r["lang"], r["upd"]), (77, 4, "Fast one", "ru", "2026-11-17"))
        self.assertEqual(r["author"], {"name": "Nova", "badge": 112, "ls": 1, "region": "eu", "pos": 37, "plays": 12})
        self.assertEqual(set(r["run"][0]), {"name", "badge", "g"})
        self.assertEqual(shape.row(77, m, author, use, [], {"old": 0, "gone": 0}, site=True)["site"], 1)
        a2 = shape.author("", (105, 1, False), None, 0, 0)
        self.assertEqual(a2, {"name": "", "badge": 105, "region": "", "pos": 0, "plays": 0})

    def test_detail(self):
        cats = [{"name": "#Citadel_HeroBuilds_EarlyGame", "mods": [{"ability_id": 1, "annotation": "buy <b>first</b>"}, {"ability_id": 1},
                                                                   {"ability_id": 999}, {"ability_id": 2}]},
                {"name": "Mid", "mods": [{"ability_id": 3, "annotation": "{s:x}"}]},
                {"name": "early extras", "mods": [{"ability_id": 4}]},
                {"name": "Empty", "mods": []}]
        ch = [{"ability_id": 90 + s, "currency_type": 1, "delta": -1} for s in (1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4, 1)]
        d = shape.detail(full(cats, ch), UP, SLOTS)
        self.assertEqual(d["v"], 1)
        self.assertEqual((d["id"], d["ver"]), (7, 3))
        self.assertEqual(d["desc"], "Rush a.")
        self.assertEqual([p["n"] for p in d["phases"]], ["early", "mid"])
        self.assertEqual(d["phases"][0]["i"], ["upgrade_a", "upgrade_b", "upgrade_d"])   # same-name phases merged, repeats and unknowns gone
        self.assertEqual(d["phases"][0]["a"], {"upgrade_a": "buy first"})
        self.assertNotIn("a", d["phases"][1])
        self.assertEqual(len(d["abil"]), 12)


class Fit(unittest.TestCase):
    def test_fit_list(self):
        rows = []
        for i in range(200):
            rows.append({"id": i, "name": "x" * 40, "author": {"name": "y" * 30}, "run": [{"name": "z" * 30, "badge": 111, "g": 3}] * 3,
                         "use": {"asc": {"p": 1, "g": 1, "w": 1, "last": 1, "best": float(i), "r": {"eu": {"p": 1, "g": 1, "w": 1, "best": 1.0}}}}})
        obj = {"v": 1, "builds": rows}
        fitted, dropped = shape.fit_list(obj)
        self.assertLessEqual(len(shape.dumps(fitted).encode("utf-8")), config.LIST_MAX)
        self.assertGreater(dropped, 0)
        kept = {r["id"] for r in fitted["builds"]}
        self.assertIn(199, kept)
        self.assertNotIn(0, kept)          # the lowest best goes first
        small = {"v": 1, "builds": rows[:3]}
        self.assertEqual(shape.fit_list(small)[1], 0)

    def test_fit_detail(self):
        phases = [{"n": "early", "i": ["upgrade_a"] * 1, "a": {"upgrade_a%d" % k: "w" * 120 for k in range(300)}}]
        d = {"v": 1, "id": 1, "ver": 1, "desc": "d" * 300, "phases": phases, "abil": [1] * 12}
        self.assertGreater(len(shape.dumps(d)), 40_000)
        fitted, how = shape.fit_detail(d)
        self.assertLessEqual(len(shape.dumps(fitted).encode("utf-8")), config.DETAIL_MAX)
        self.assertEqual(fitted["desc"], "d" * 300)                # annotations went first
        self.assertIn("annotations", how)
        huge = {"v": 1, "id": 1, "ver": 1, "desc": "d" * 300, "phases": [{"n": "early", "i": ["u%05d" % k for k in range(2000)]}], "abil": []}
        fitted, how = shape.fit_detail(huge)
        self.assertNotIn("desc", fitted)


if __name__ == "__main__":
    unittest.main()
