import unittest

import api as api_mod
import lake


def base(p, i, hi):
    return {"key": "v1/tables/match_player/g3/base/part-%d/x-%d.parquet" % (p, i), "kind": "base", "partition": p, "hi": hi}


def delta(lo, hi, kind="delta"):
    return {"key": "v1/tables/match_player/g3/%s/%d-%d.parquet" % (kind, lo, hi), "kind": kind, "lo": lo, "hi": hi}


class FakeReader:
    def __init__(self, latest, rows_of=None, fail_at=None):
        self.latest = latest            # {key: latest start_time}
        self.rows_of = rows_of or {}    # {key: [game]}
        self.fail_at = fail_at          # the batch number that raises
        self.probed, self.batches = [], []

    def latest_start(self, key):
        self.probed.append(key)
        return self.latest[key]

    def games(self, keys, ids, since):
        self.batches.append(list(keys))
        if self.fail_at is not None and len(self.batches) > self.fail_at:
            raise RuntimeError("http")
        return [g for k in keys for g in self.rows_of.get(k, ()) if g["account_id"] in ids and g["start_time"] >= since]


class TestPartitions(unittest.TestCase):
    def setUp(self):
        # partitions 10..14, each 2 files; partition p's games run up to day p (in units of 100)
        self.files = [base(p, i, 5000) for p in range(10, 15) for i in (1, 2)]
        self.latest = {f["key"]: f["partition"] * 100 + (50 if f["key"].endswith("-2.parquet") else 0) for f in self.files}

    def test_last_files_by_index(self):
        self.assertTrue(lake.last_files(self.files)[12].endswith("x-2.parquet"))

    def test_first_partition_from_the_top(self):
        rd = FakeReader(self.latest)
        self.assertEqual(lake.first_partition(self.files, 1220, rd.latest_start), 12)     # 12's last file reaches 1250
        self.assertEqual(lake.first_partition(self.files, 1251, rd.latest_start), 13)

    def test_first_partition_moves_up_from_the_hint(self):
        rd = FakeReader(self.latest)
        self.assertEqual(lake.first_partition(self.files, 1320, rd.latest_start, hint=11), 13)
        self.assertEqual(len(rd.probed), 3)     # 11, 12, 13

    def test_no_partition_reaches_the_window(self):
        rd = FakeReader(self.latest)
        self.assertIsNone(lake.first_partition(self.files, 9999, rd.latest_start))
        self.assertIsNone(lake.first_partition([delta(1, 2)], 0, rd.latest_start))


class TestSelect(unittest.TestCase):
    def test_select_and_order(self):
        files = [base(11, 1, 900), base(12, 1, 700), base(12, 2, 950), delta(100, 200), delta(600, 800), delta(800, 900, "residual")]
        got = lake.select(files, since=500, wm=0, p0=12)
        self.assertEqual([f["hi"] for f in got], [700, 800, 900, 950])     # partition 11 and the delta before the window left out
        self.assertEqual([f["hi"] for f in lake.select(files, since=500, wm=800, p0=12)], [900, 950])
        self.assertEqual([f["hi"] for f in lake.select(files, since=500, wm=0, p0=None)], [800, 900])

    def test_wm_after(self):
        todo = [{"hi": 10}, {"hi": 20}, {"hi": 20}, {"hi": 30}]
        self.assertEqual(lake.wm_after(todo, 4, 5), 30)
        self.assertEqual(lake.wm_after(todo, 1, 5), 19)       # the two files of hi 20 are read together or not at all
        self.assertEqual(lake.wm_after(todo, 2, 5), 19)
        self.assertEqual(lake.wm_after(todo, 0, 15), 15)
        self.assertEqual(lake.wm_after([], 0, 7), 7)


class TestPoolGames(unittest.TestCase):
    def man(self, files, gen=3):
        return {"tables": {"match_player": {"generation": gen, "files": files}}}

    def game(self, m, a, t):
        return {"match_id": m, "account_id": a, "hero_id": 1, "hero_build_id": 5, "won": True, "start_time": t}

    def test_batches_and_state(self):
        files = [delta(i * 10, i * 10 + 10) for i in range(1, 60)]
        rows = {f["key"]: [self.game(f["hi"], 7, f["hi"]), self.game(f["hi"], 8, f["hi"])] for f in files}
        rd = FakeReader({}, rows)
        out = list(lake.pool_games({7}, 100, {}, "t", reader=rd, man=self.man(files)))
        self.assertEqual(len(rd.batches), -(-51 // lake.BATCH))     # 51 files in the window (hi 100..600)
        self.assertEqual(sum(len(g) for g, _ in out), 51)     # account 8 is not in the pool
        self.assertEqual(out[-1][1], {"gen": 3, "wm": 600, "p0": None, "files": 51})

    def test_a_failed_batch_keeps_the_ones_before(self):
        files = [delta(i * 10, i * 10 + 10) for i in range(1, 60)]
        rd = FakeReader({}, {}, fail_at=1)
        got = []
        with self.assertRaises(api_mod.ApiError):
            for g, st in lake.pool_games({7}, 100, {}, "t", reader=rd, man=self.man(files)):
                got.append(st)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["wm"], files[8 + lake.BATCH]["hi"] - 1)     # the first batch read, the second not

    def test_a_new_generation_reads_the_window_again(self):
        files = [delta(i * 10, i * 10 + 10) for i in range(1, 60)]
        rd = FakeReader({}, {})
        out = list(lake.pool_games({7}, 100, {"gen": 2, "wm": 580}, "t", reader=rd, man=self.man(files)))
        self.assertEqual(out[-1][1]["files"], 51)
        out = list(lake.pool_games({7}, 100, {"gen": 3, "wm": 580}, "t", reader=rd, man=self.man(files)))
        self.assertEqual(out[-1][1]["files"], 2)


if __name__ == "__main__":
    unittest.main()
