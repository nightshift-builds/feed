"""The job's private state between runs (spec 5.7): build metadata, build details, player names and regions, the last run's stats
and list files. It lives in the Actions cache, never in the published site (it holds account ids and names of accounts no row shows)."""
import gzip
import json
import os
from pathlib import Path

import config


def check_dirs(out, state_dir):
    """The published folder and the state folder never nest (a state file must never be published)."""
    o, s = Path(out).resolve(), Path(state_dir).resolve()
    if o == s or s in o.parents or o in s.parents:
        raise ValueError("the output and state folders must be apart: %s / %s" % (o, s))


def _read(p):
    if not p.exists():
        return None
    raw = p.read_bytes()
    if p.suffix == ".gz":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _write(p, obj):
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if p.suffix == ".gz":
        raw = gzip.compress(raw, 6)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, p)


class State:
    def __init__(self, d):
        self.dir = Path(d)
        self.meta = {"seeded": {}, "since": 0, "builds": {}}   # seeded: {hero id: unix}; builds: {bid: slim}
        self.details = {}                                      # {"bid_ver": full hero_build}
        self.names = {}                                        # {acct: [name, t]}
        self.regions = {}                                      # {acct: [chip | None, t]}
        self.stats = {}                                        # the last good run: pool, empty_ete, with_lists, gen
        self.assets = {}                                       # {"at": t, "data": sources.assets() with string keys}
        self.prevseason = {}                                   # {"season": "start-end", "full": bool, "rows": [[acct, badge, value]]}

    FILES = (("meta", "meta.json.gz"), ("details", "details.json.gz"), ("names", "names.json"), ("regions", "regions.json"),
             ("stats", "stats.json"), ("assets", "assets.json.gz"), ("prevseason", "prevseason.json.gz"))

    def load(self):
        for attr, name in self.FILES:
            v = _read(self.dir / name)
            if v is not None:
                setattr(self, attr, v)
        self.meta.setdefault("seeded", {})
        self.meta.setdefault("since", 0)
        self.meta.setdefault("builds", {})
        return self

    def save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        for attr, name in self.FILES:
            _write(self.dir / name, getattr(self, attr))

    # the last run's list files {relative path: bytes}, kept so the next deploy can carry the previous generation (plan ruling 7)
    def save_lists(self, files):
        d = self.dir / "lists"
        if d.exists():
            for p in sorted(d.rglob("*"), reverse=True):
                p.unlink() if p.is_file() else p.rmdir()
        for rel, data in files.items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    def load_lists(self):
        d = self.dir / "lists"
        if not d.exists():
            return {}
        return {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob("*") if p.is_file()}

    def names_fresh(self, ids, now):
        """({acct: name} cached within NAME_TTL, [accts to ask])."""
        have, missing = {}, []
        for a in ids:
            e = self.names.get(str(a))
            if e and now - int(e[1]) < config.NAME_TTL:
                if e[0]:
                    have[int(a)] = e[0]
            else:
                missing.append(int(a))
        return have, missing

    def put_names(self, asked, got, now):
        for a in asked:
            self.names[str(a)] = [got.get(int(a), ""), now]

    def regions_due(self, ids, now, limit=config.REGION_BATCH):
        """The accounts whose region is unknown or older than REGION_TTL, at most `limit` (plan ruling 2)."""
        due = []
        for a in sorted(int(x) for x in ids):
            e = self.regions.get(str(a))
            if not e or now - int(e[1]) >= config.REGION_TTL:
                due.append(a)
                if len(due) >= limit:
                    break
        return due

    def put_regions(self, asked, got, now):
        for a in asked:
            self.regions[str(a)] = [got.get(int(a)), now]

    def region_map(self, now):
        """{acct: chip} of the regions known within REGION_TTL (None and stale entries left out)."""
        out = {}
        for a, e in self.regions.items():
            if e and e[0] and now - int(e[1]) < config.REGION_TTL:
                out[int(a)] = e[0]
        return out

    def names_stale(self, ids):
        """{acct: name} of the cached names, however old (the fallback when a refresh fails)."""
        out = {}
        for a in ids:
            e = self.names.get(str(a))
            if e and e[0]:
                out[int(a)] = e[0]
        return out

    def drop_old_names(self, now):
        """Names older than NAME_KEEP go; younger ones stay as the fallback of a failed refresh."""
        for a in [a for a, e in self.names.items() if now - int(e[1]) >= config.NAME_KEEP]:
            del self.names[a]
