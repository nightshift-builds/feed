"""The pool's games from deadlock-api's data lake (data.deadlock-api.com): match_player as parquet files, listed in a manifest and read
with pyarrow over HTTP range requests. Only the columns asked for travel (20 Nov: an hour of every game's six columns was 1.5 MB of a 250 MB file),
and the lake has no request or read budget, unlike GraphQL (charged by the data it reads since 19 Nov).

The manifest's files: "base" files hold a match_id range each ("partition" = match_id // 1,000,000; a partition's files in match_id
order), "delta" and "residual" files hold what came in a time span. Every file has "hi", the latest created_at in it. A game of the
window was created after it started, so it lies in a base file of a partition the window reaches, or in a delta / residual file whose
hi is in the window. A run reads the files whose hi is past the last one read (the state's "wm"); a game read twice keeps one row
(the caller keys games by match and account). A new generation of the lake reads the window again."""
import io
import json
import re
import time
import urllib.request

import api as api_mod

LAKE = "https://data.deadlock-api.com"
MANIFEST = LAKE + "/v1/manifest.json"
TABLE = "match_player"
BATCH = 6           # files per batch: a failed read loses at most this many, the ones before it are kept
GAME_NORMAL = "Normal"


def _part_index(key):
    m = re.search(r"-(\d+)\.parquet$", key)
    return int(m.group(1)) if m else 0


def files_of(manifest):
    """(generation, [file]) of match_player in a manifest."""
    t = (manifest.get("tables") or {}).get(TABLE) or {}
    return int(t.get("generation") or 0), list(t.get("files") or ())


def last_files(files):
    """{partition: the key of its base file with the highest match_ids}."""
    out = {}
    for f in files:
        if f.get("kind") == "base" and f.get("partition") is not None:
            p = int(f["partition"])
            if p not in out or _part_index(f["key"]) > _part_index(out[p]):
                out[p] = f["key"]
    return out


def first_partition(files, since, probe, hint=None):
    """The lowest partition holding a game that started at `since` or later. probe(key) = the latest start_time in that file (read
    from its footer); only each partition's last file is probed, starting at the hint (the last run's answer) and moving up or down.
    None when no base file reaches the window."""
    last = last_files(files)
    parts = sorted(last)
    if not parts:
        return None
    i = parts.index(hint) if hint in last else len(parts) - 1
    if probe(last[parts[i]]) < since:
        while i + 1 < len(parts):
            i += 1
            if probe(last[parts[i]]) >= since:
                return parts[i]
        return None
    while i > 0 and probe(last[parts[i - 1]]) >= since:
        i -= 1
    return parts[i]


def select(files, since, wm, p0):
    """The files to read, oldest hi first: base files of partition p0 and up, delta / residual files with hi in the window; all with
    hi past wm."""
    out = []
    for f in files:
        hi = int(f.get("hi") or 0)
        if hi <= wm:
            continue
        if f.get("kind") == "base":
            if p0 is not None and f.get("partition") is not None and int(f["partition"]) >= p0:
                out.append(f)
        elif hi >= since:
            out.append(f)
    out.sort(key=lambda f: (int(f.get("hi") or 0), f["key"]))
    return out


def wm_after(todo, done, wm):
    """The watermark once `done` files of `todo` (both oldest hi first) were read: every file with hi up to it was read. All read: the
    highest hi; else just under the oldest unread one (files sharing a hi are never split), never below the old wm."""
    if not todo:
        return wm
    if done >= len(todo):
        return max(wm, int(todo[-1].get("hi") or 0))
    return max(wm, int(todo[done].get("hi") or 0) - 1)


def manifest(ua, timeout=60):
    req = urllib.request.Request(MANIFEST, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        raise api_mod.ApiError("lake manifest: " + type(e).__name__, 0)


class HttpFile(io.RawIOBase):
    """A lake file read by HTTP range requests: pyarrow asks for the footer and then for each column chunk it needs (coalescing only
    ranges a few KB apart), so a residual file's 25 MB of the six columns come without its 4.7 GB."""

    def __init__(self, url, ua, timeout=60, tries=3):
        super().__init__()
        self.url, self.ua, self.timeout, self.tries = url, ua, timeout, tries
        self.pos, self.got, self.calls = 0, 0, 0
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            self.size = int(r.headers["Content-Length"])

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=io.SEEK_SET):
        self.pos = off if whence == io.SEEK_SET else self.pos + off if whence == io.SEEK_CUR else self.size + off
        return self.pos

    def readinto(self, b):
        n = min(len(b), self.size - self.pos)
        if n <= 0:
            return 0
        req = urllib.request.Request(self.url, headers={"User-Agent": self.ua, "Range": "bytes=%d-%d" % (self.pos, self.pos + n - 1)})
        for attempt in range(self.tries):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    if r.status != 206:
                        raise OSError("range answered %d" % r.status)
                    data = r.read()
                break
            except OSError:
                if attempt + 1 == self.tries:
                    raise
                time.sleep(2 ** attempt)
        b[:len(data)] = data
        self.pos += len(data)
        self.got += len(data)
        self.calls += 1
        return len(data)


COLS = ["match_id", "account_id", "hero_id", "hero_build_id", "won", "start_time", "game_mode"]


class Reader:
    """pyarrow over HTTP range requests (imported here only: the job's tests run without it). Row groups whose start_time
    statistics end before the window are skipped without being read."""

    def __init__(self, ua="NightshiftBuilds/1"):
        import pyarrow  # noqa: F401  (fails here, before any file, when it is missing)
        self.ua = ua
        self.bytes = 0
        self.calls = 0

    def _open(self, key):
        import pyarrow.parquet as pq
        f = HttpFile(LAKE + "/" + key, self.ua)
        return f, pq.ParquetFile(f, pre_buffer=True)

    def _done(self, f):
        self.bytes += f.got
        self.calls += f.calls

    @staticmethod
    def _col(md, name):
        for i in range(md.num_columns):
            if md.schema.column(i).path == name:
                return i
        return None

    @staticmethod
    def _epoch(v):
        """A statistics value (a datetime, or an integer in the column's unit) in unix seconds."""
        if v is None:
            return None
        if hasattr(v, "timestamp"):
            return int(v.timestamp())
        v = int(v)
        return v // 1_000_000 if v > 10 ** 14 else v // 1000 if v > 10 ** 11 else v

    def _row_groups(self, md, since):
        c = self._col(md, "start_time")
        out = []
        for g in range(md.num_row_groups):
            st = md.row_group(g).column(c).statistics if c is not None else None
            mx = self._epoch(st.max_raw) if st is not None and st.has_min_max else None
            if mx is None or mx >= since:
                out.append(g)
        return out

    @staticmethod
    def _secs(col):
        """A timestamp column in unix seconds (int64)."""
        import pyarrow as pa
        import pyarrow.compute as pc
        unit = getattr(col.type, "unit", "s")
        raw = pc.cast(col, pa.int64())
        return raw if unit == "s" else pc.divide(raw, {"ms": 1000, "us": 10 ** 6, "ns": 10 ** 9}[unit])

    def latest_start(self, key):
        f, pf = self._open(key)
        try:
            md, best = pf.metadata, 0
            c = self._col(md, "start_time")
            for g in range(md.num_row_groups):
                st = md.row_group(g).column(c).statistics if c is not None else None
                if st is not None and st.has_min_max:
                    best = max(best, self._epoch(st.max_raw) or 0)
            return best
        finally:
            self._done(f)

    def games(self, keys, ids, since):
        """[{match_id, account_id, hero_id, hero_build_id, won, start_time}] of the pool's Normal games from `since` in these files."""
        import pyarrow as pa
        import pyarrow.compute as pc
        pool = pa.array(sorted(int(i) for i in ids), type=pa.int64())
        out = []
        for key in keys:
            f, pf = self._open(key)
            try:
                groups = self._row_groups(pf.metadata, since)
                if not groups:
                    continue
                t = pf.read_row_groups(groups, columns=COLS)
                gm = t["game_mode"]
                if pa.types.is_dictionary(gm.type):
                    gm = gm.cast(pa.string())
                mask = pc.and_(pc.and_(pc.equal(gm, GAME_NORMAL), pc.greater_equal(self._secs(t["start_time"]), int(since))),
                               pc.is_in(pc.cast(t["account_id"], pa.int64()), value_set=pool))
                t = t.filter(mask)
                st = self._secs(t["start_time"]).to_pylist()
                cols = {c: t[c].to_pylist() for c in ("match_id", "account_id", "hero_id", "hero_build_id", "won")}
                for i in range(t.num_rows):
                    b = cols["hero_build_id"][i]
                    out.append({"match_id": int(cols["match_id"][i]), "account_id": int(cols["account_id"][i]),
                                "hero_id": int(cols["hero_id"][i]), "hero_build_id": int(b) if b else None,
                                "won": bool(cols["won"][i]), "start_time": int(st[i])})
            finally:
                self._done(f)
        return out


def pool_games(ids, since, lk, ua, reader=None, man=None):
    """Yields (games, lake state) after each batch of files, so a run cut short keeps what came. lk / the lake state: {gen, wm, p0}.
    Raises api.ApiError when the manifest or a file cannot be read."""
    man = man if man is not None else manifest(ua)
    gen, files = files_of(man)
    lk = dict(lk or {})
    wm = int(lk.get("wm") or 0) if int(lk.get("gen") or 0) == gen else 0
    rd = reader or Reader(ua)
    try:
        p0 = first_partition(files, since, rd.latest_start, lk.get("p0"))
        todo = select(files, since, wm, p0)
        state = {"gen": gen, "wm": wm, "p0": p0, "files": len(todo)}
        if not todo:
            yield [], state
            return
        for k in range(0, len(todo), BATCH):
            got = rd.games([f["key"] for f in todo[k:k + BATCH]], ids, since)
            state = dict(state, wm=wm_after(todo, min(len(todo), k + BATCH), wm), mb=round(getattr(rd, "bytes", 0) / 1e6, 1))
            yield got, state
    except api_mod.ApiError:
        raise
    except Exception as e:      # HTTP errors, a file gone after a fold, pyarrow's errors: they end the read the way an API error does
        # its text names a file, a size or a setting, never a player: kept short for the log
        raise api_mod.ApiError("lake: %s: %s" % (type(e).__name__, " ".join(str(e).split())[:240]), 0)
