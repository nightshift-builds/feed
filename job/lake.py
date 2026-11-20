"""The pool's games from deadlock-api's data lake (data.deadlock-api.com): match_player as parquet files, listed in a manifest and read
with DuckDB over HTTP. Only the columns asked for travel (20 Nov: an hour of every game's six columns was 1.5 MB of a 250 MB file),
and the lake has no request or read budget, unlike GraphQL (charged by the data it reads since 19 Nov).

The manifest's files: "base" files hold a match_id range each ("partition" = match_id // 1,000,000; a partition's files in match_id
order), "delta" and "residual" files hold what came in a time span. Every file has "hi", the latest created_at in it. A game of the
window was created after it started, so it lies in a base file of a partition the window reaches, or in a delta / residual file whose
hi is in the window. A run reads the files whose hi is past the last one read (the state's "wm"); a game read twice keeps one row
(the caller keys games by match and account). A new generation of the lake reads the window again."""
import json
import re
import urllib.request

import api as api_mod

LAKE = "https://data.deadlock-api.com"
MANIFEST = LAKE + "/v1/manifest.json"
TABLE = "match_player"
BATCH = 24          # files per query: a failed query loses at most this many, the ones before it are kept
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


class Reader:
    """DuckDB over HTTP (imported here only: the job's tests run without it)."""

    def __init__(self):
        import duckdb
        self.con = duckdb.connect()
        self.con.execute("INSTALL httpfs")
        self.con.execute("LOAD httpfs")

    def url(self, key):
        return LAKE + "/" + key

    def latest_start(self, key):
        r = self.con.execute("SELECT max(stats_max_value) FROM parquet_metadata(?) WHERE path_in_schema = 'start_time'",
                             [self.url(key)]).fetchone()
        if not r or not r[0]:
            return 0
        t = self.con.execute("SELECT epoch(?::TIMESTAMPTZ)::BIGINT", [r[0]]).fetchone()
        return int(t[0]) if t and t[0] is not None else 0

    def games(self, keys, ids, since):
        """[{match_id, account_id, hero_id, hero_build_id, won, start_time}] of the pool's Normal games from `since` in these files."""
        self.con.execute("CREATE OR REPLACE TEMP TABLE pool AS SELECT unnest(?::BIGINT[]) AS id", [sorted(int(i) for i in ids)])
        rows = self.con.execute(
            "SELECT match_id, account_id, hero_id, hero_build_id, won, epoch(start_time)::BIGINT FROM read_parquet(?, union_by_name = true) "
            "WHERE game_mode = ? AND start_time >= to_timestamp(?) AND account_id IN (SELECT id FROM pool)",
            [[self.url(k) for k in keys], GAME_NORMAL, int(since)]).fetchall()
        return [{"match_id": int(r[0]), "account_id": int(r[1]), "hero_id": int(r[2]), "hero_build_id": int(r[3]) if r[3] else None,
                 "won": bool(r[4]), "start_time": int(r[5])} for r in rows]


def pool_games(ids, since, lk, ua, reader=None, man=None):
    """Yields (games, lake state) after each batch of files, so a run cut short keeps what came. lk / the lake state: {gen, wm, p0}.
    Raises api.ApiError when the manifest or a file cannot be read."""
    man = man if man is not None else manifest(ua)
    gen, files = files_of(man)
    lk = dict(lk or {})
    wm = int(lk.get("wm") or 0) if int(lk.get("gen") or 0) == gen else 0
    rd = reader or Reader()
    try:
        p0 = first_partition(files, since, rd.latest_start, lk.get("p0"))
        todo = select(files, since, wm, p0)
        state = {"gen": gen, "wm": wm, "p0": p0, "files": len(todo)}
        if not todo:
            yield [], state
            return
        for k in range(0, len(todo), BATCH):
            got = rd.games([f["key"] for f in todo[k:k + BATCH]], ids, since)
            state = dict(state, wm=wm_after(todo, min(len(todo), k + BATCH), wm))
            yield got, state
    except api_mod.ApiError:
        raise
    except Exception as e:      # duckdb's errors (HTTP, a file gone after a fold) end the fetch the way an API error does
        raise api_mod.ApiError("lake: " + type(e).__name__, 0)
