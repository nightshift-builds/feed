"""Publishing: validation, the atomic write, the previous generation and the daily history (plan Task 4; spec 5.7)."""
import json
import os
import tempfile
import unittest
from pathlib import Path

import publish


class Validate(unittest.TestCase):
    def test_validate(self):
        prev = {"pool": 4000, "empty_ete": 7, "with_lists": 40}
        self.assertFalse(publish.validate({"pool": 1500, "empty_ete": 0, "with_lists": 44}, prev)[0])
        self.assertTrue(publish.validate({"pool": 3000, "empty_ete": 8, "with_lists": 44}, prev)[0])
        self.assertFalse(publish.validate({"pool": 3000, "empty_ete": 8, "with_lists": 44}, dict(prev, empty_ete=2))[0])
        self.assertFalse(publish.validate({"pool": 900, "empty_ete": 0, "with_lists": 44}, None)[0])
        self.assertFalse(publish.validate({"pool": 1000, "empty_ete": 0, "with_lists": 29}, {})[0])
        self.assertTrue(publish.validate({"pool": 1000, "empty_ete": 0, "with_lists": 30}, None)[0])
        ok, reasons = publish.validate({"pool": 1, "empty_ete": 0, "with_lists": 0}, None)
        self.assertEqual(len(reasons), 2)

    def test_validate_eight_empty_two_runs_in_a_row_deploys(self):
        # "validate: 8 empty Eternus+ heroes two runs in a row -> deploys" (plan Review Focus 5)
        self.assertTrue(publish.validate({"pool": 3000, "empty_ete": 8, "with_lists": 44}, {"pool": 3100, "empty_ete": 8})[0])


class Write(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.site = self.d / "site"
        self.site.mkdir()
        (self.site / "relay.html").write_text("<html>relay</html>", encoding="utf-8")
        (self.site / "index.html").write_text("<html>note</html>", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_atomic(self):
        out = self.d / "out"
        publish.write(out, self.site, {"data/index.json": {"v": 1}}, {})
        self.assertEqual(json.loads((out / "data" / "index.json").read_text(encoding="utf-8")), {"v": 1})
        self.assertTrue((out / "relay.html").exists())
        self.assertFalse((self.d / "out.tmp").exists())
        with self.assertRaises(TypeError):
            publish.write(out, self.site, {"data/index.json": {"v": object()}}, {})
        self.assertEqual(json.loads((out / "data" / "index.json").read_text(encoding="utf-8")), {"v": 1})
        self.assertFalse((self.d / "out.tmp").exists())

    def test_keep_prev_gen(self):
        out = self.d / "out"
        keep = {"data/20261117T1100Z/13.json": b'{"v":1,"gen":"20261117T1100Z"}'}
        publish.write(out, self.site, {"data/20261117T1200Z/13.json": {"v": 1}}, keep)
        self.assertEqual((out / "data" / "20261117T1100Z" / "13.json").read_bytes(), keep["data/20261117T1100Z/13.json"])
        self.assertTrue((out / "data" / "20261117T1200Z" / "13.json").exists())

    def test_history_no_ids(self):
        lists = {13: {"gen": "g", "builds": [{"id": 5, "use": {"ete": {"p": 3, "g": 9, "best": 2.0}}, "author": {"name": "A"}},
                                             {"id": 6, "use": {"ete": {"p": 4, "g": 1, "best": 3.0}}},
                                             {"id": 7, "use": {"asc": {"p": 9, "g": 9, "best": 9.0}}}]}}
        h = publish.history(lists, "2026-11-17", "g")
        self.assertEqual(h, {"day": "2026-11-17", "gen": "g", "heroes": {"13": [[6, 4, 1], [5, 3, 9]]}})
        self.assertNotIn("account", json.dumps(h))

    def test_no_ids(self):
        out = self.d / "out"
        publish.write(out, self.site, {"data/a.json": {"n": 9000123, "s": "x"}, "data/b.json": {"s": "id 9000124 here"}, "data/c.json": {"n": 1}}, {})
        self.assertEqual(sorted(publish.no_ids(out, {9000123, 9000124})), ["data/a.json", "data/b.json"])


if __name__ == "__main__":
    unittest.main()
