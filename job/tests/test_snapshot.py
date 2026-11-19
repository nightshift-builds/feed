"""The baked snapshot of the mod (plan Task 9; spec 7.2): scripts/feed_snapshot.py turns a published site into sheets/feed_snapshot.json
and scripts/generate.py checks it before it bakes NS.FEED_SNAPSHOT. Runs only inside the mod's repository (scripts/ next to feed/)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "scripts"
HAVE = (SCRIPTS / "generate.py").exists()   # the mod's repository; feed_snapshot.py missing there is a failure, not a skip
if HAVE and str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def site(d, names):
    """A tiny published site: one hero (krill = 18) whose Eternus+ list holds rows named `names` in place order, each with details."""
    gen = "20261117T1200Z"
    rows = []
    for i, n in enumerate(names):
        rows.append({"id": 500 + i, "ver": 2, "name": n, "lang": "", "upd": "2026-11-10",
                     "author": {"name": "Somebody %d" % i, "badge": 113, "region": "eu", "pos": 4, "plays": 9},
                     "use": {"ete": {"p": 9 - i, "g": 20, "w": 11, "last": 1794900000, "best": 9.0 - i, "n": i + 1, "r": {"eu": {"p": 3, "g": 5, "w": 2, "best": 4.0, "n": 1}}}},
                     "run": [{"name": "Runner", "badge": 112, "g": 4}], "patch": {"old": 0, "gone": 0}})
    files = {"data/index.json": {"v": 1, "gen": gen, "made": "2026-11-17T12:00:00Z", "heroes": {"krill": 18}, "lists": [18]},
             "data/%s/18.json" % gen: {"v": 1, "hero": 18, "gen": gen, "builds": rows}}
    for r in rows:
        files["data/b/%d_2.json" % r["id"]] = {"v": 1, "id": r["id"], "ver": 2, "desc": "Rush it. " * 5,
                                               "phases": [{"n": "early", "i": ["upgrade_clip_size", "upgrade_close_range"], "a": {"upgrade_clip_size": "first"}},
                                                          {"n": "Core stuff", "i": ["upgrade_clip_size"]}], "abil": [1, 2, 3, 4] * 3}
    for rel, obj in files.items():
        p = Path(d) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj), encoding="utf-8")


@unittest.skipUnless(HAVE, "scripts/ of the mod's repository not here")
class Snapshot(unittest.TestCase):
    def test_drops_a_row_with_the_unnamed_word_and_takes_the_next(self):
        import feed_snapshot
        with tempfile.TemporaryDirectory() as d:
            site(d, ["One", "My " + "Q" + "oL build", "Three", "Four", "Five", "Six", "Seven"])   # the word the mod never names, built here
            snap = feed_snapshot.build(feed_snapshot.dir_reader(d))
        rows = snap["heroes"]["krill"]["rows"]
        self.assertEqual([r["name"] for r in rows], ["One", "Three", "Four", "Five", "Six"])
        self.assertNotIn("q" + "ol", json.dumps(snap).lower())

    def test_no_names_and_compact_details(self):
        import feed_snapshot
        with tempfile.TemporaryDirectory() as d:
            site(d, ["One", "Two"])
            snap = feed_snapshot.build(feed_snapshot.dir_reader(d))
        self.assertEqual((snap["v"], snap["made"], snap["gen"]), (1, "2026-11-17", "20261117T1200Z"))
        r = snap["heroes"]["krill"]["rows"][0]
        self.assertEqual(r["author"], {"name": "", "badge": 113})
        self.assertEqual(r["run"], [])
        self.assertEqual(set(r["use"]), {"ete"})
        self.assertNotIn("r", r["use"]["ete"])
        det = snap["heroes"]["krill"]["det"]["500_2"]
        self.assertEqual([p[0] for p in det["p"]], ["early", "Core stuff"])
        self.assertEqual([snap["items"][k] for k in det["p"][0][1]], ["upgrade_clip_size", "upgrade_close_range"])
        self.assertEqual(det["a"], [1, 2, 3, 4] * 3)
        self.assertNotIn("Somebody", json.dumps(snap))
        self.assertNotIn("Runner", json.dumps(snap))
        import generate
        self.assertEqual(generate.feed_snapshot_errors(snap), [])

    def test_generate_refuses_names_ids_and_size(self):
        import generate
        good = {"v": 1, "made": "2026-11-17", "gen": "g", "items": ["upgrade_a"], "heroes": {"krill": {
            "rows": [{"id": 5, "ver": 1, "name": "X", "author": {"name": "", "badge": 111}, "use": {"ete": {"p": 1, "n": 1}}, "run": [], "patch": {}}],
            "det": {"5_1": {"p": [["early", [0]]], "a": [], "d": ""}}}}}
        self.assertEqual(generate.feed_snapshot_errors(good), [])
        named = json.loads(json.dumps(good))
        named["heroes"]["krill"]["rows"][0]["author"]["name"] = "Somebody"
        self.assertTrue(generate.feed_snapshot_errors(named))
        runner = json.loads(json.dumps(good))
        runner["heroes"]["krill"]["rows"][0]["run"] = [{"name": "R", "badge": 1, "g": 1}]
        self.assertTrue(generate.feed_snapshot_errors(runner))
        ids = json.loads(json.dumps(good))
        ids["heroes"]["krill"]["rows"][0]["author"]["account_id"] = 9000001
        self.assertTrue(generate.feed_snapshot_errors(ids))
        stray = json.loads(json.dumps(good))
        stray["heroes"]["krill"]["det"]["6_1"] = {"p": [], "a": [], "d": ""}
        self.assertTrue(generate.feed_snapshot_errors(stray))
        big = json.loads(json.dumps(good))
        big["items"] = ["upgrade_%06d" % i for i in range(12000)]
        self.assertTrue(any("150" in e for e in generate.feed_snapshot_errors(big)))
        self.assertEqual(generate.feed_snapshot_errors({"v": 1, "made": "", "gen": "", "items": [], "heroes": {}}), [])


if __name__ == "__main__":
    unittest.main()
