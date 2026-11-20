"""Nightshift builds feed: one hourly run (spec docs/superpowers/specs/2026-11-17-builds-feed-design.md, section 5).

  python job/run.py --out _site --state state --site-url https://<org>.github.io/<repo>/ [--history data/history]

Reads deadlock-api (sources.py), computes per hero the builds high-rank players run (14 days) and write (90 days), and writes the
static site (_site: relay.html, data/index.json, data/<gen>/<hero>.json, data/<gen>/popular/<hero>.json, data/b/<build>_<ver>.json).
The job's private state (metadata, names, regions, the last lists) stays in --state (the Actions cache), never in --out. Exit codes:
0 written, 1 validation failed (nothing written: the last deploy stays live), 2 could not run. The log names no player and no build.
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import api as api_mod  # noqa: E402
import clean  # noqa: E402
import config  # noqa: E402
import lake  # noqa: E402
import pool  # noqa: E402
import publish  # noqa: E402
import rank  # noqa: E402
import shape  # noqa: E402
import sources  # noqa: E402
import state as state_mod  # noqa: E402

DAY = 86_400
SITE_SRC = HERE.parent / "site"
MIN_PUBLISHED_ID = 2000     # lower ids are personal build slots and Valve's defaults (1001-1046): never published
UNKNOWN_MAX = 200           # builds a hero's players ran that the metadata does not know: at most this many looked up a run
MISSING_TTL = DAY           # an id that came back empty is not asked again for a day


def gen_of(now):
    return datetime.datetime.fromtimestamp(int(now), datetime.timezone.utc).strftime("%Y%m%dT%H%MZ")


class Live:
    """The job's sources over HTTP (tests use tests/world.py with the same methods)."""

    def __init__(self, api, site_url):
        self.api = api
        self.site_url = site_url

    @property
    def count(self):
        return self.api.count

    @property
    def read_bytes(self):
        return self.api.read_bytes

    def seasons(self):
        return sources.seasons(self.api)

    def scoreboard(self, t0, t1):
        return sources.scoreboard(self.api, t0, t1)

    def pool_lake(self, ids, since, lk):
        return lake.pool_games(ids, since, lk, self.api.ua)

    def popular(self, since, until):
        return sources.popular(self.api, since, until)

    def meta_seed(self, hero, since):
        return sources.meta_seed(self.api, hero, since)

    def meta_since(self, since):
        return sources.meta_since(self.api, since)

    def details(self, pairs, failed=None):
        return sources.details(self.api, pairs, failed)

    def names(self, ids):
        return sources.names(self.api, ids)

    def regions(self, ids):
        return sources.regions(self.api, ids)

    def assets(self):
        return sources.assets(self.api)

    def site_get(self, rel):
        """A file of our own live site (the previous generation, plan ruling 7), or None."""
        if not self.site_url:
            return None
        url = self.site_url.rstrip("/") + "/" + rel + "?t=" + str(int(time.time()) // 60)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": self.api.ua})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read() if r.status == 200 else None
        except Exception:
            return None


def _ints(d):
    return {int(k): v for k, v in (d or {}).items()}


def _pool_games(src, st, pool_ids, now, log):
    """{hero: [{account_id, hero_build_id, won, start_time}]}: the pool's Normal games of the window. They live in the state with the
    data lake's watermark (lake.py): a run reads the lake files that came since the last one, the whole window when the state has no
    watermark yet (20 Nov: about 160 files, 470 MB of the six columns asked for; then a few MB an hour). The pool is the current one:
    a player new to it counts from the games read since. A failed read keeps the batches that came (the next run goes on from there)
    and uses the games while the watermark is under ROWS_STALE old; older (or none), the state is saved and the error stops the run:
    the last deploy stays live."""
    since = now - config.WINDOW_DAYS * DAY
    have = st.rows or {}
    games = {(r[0], r[1]): r for r in have.get("rows") or () if r[5] >= since}
    lk = dict(have.get("lake") or {})
    got, n0 = 0, len(games)

    def keep():
        st.rows = {"until": int(lk.get("wm") or 0), "lake": lk, "rows": sorted(games.values(), key=lambda r: (r[5], r[0], r[1]))}

    try:
        for rows, lk2 in src.pool_lake(pool_ids, since, lk):
            for r in rows:
                b = r.get("hero_build_id")
                k = (int(r["match_id"]), int(r["account_id"]))
                games[k] = [k[0], k[1], int(r["hero_id"]), int(b) if b else None, 1 if r.get("won") else 0, int(r["start_time"])]
                got += 1
            lk = dict(lk2)
            keep()
    except api_mod.ApiError as e:
        keep()
        wm = int(lk.get("wm") or 0)
        if wm < now - config.ROWS_STALE:
            st.save()
            raise
        log("feed: pool games not read after %.1f h ago (%s): the games up to then are used" % ((now - wm) / 3600.0, e))
    else:
        keep()
        log("feed: pool games: %d read from %d lake files (%s), %d new, %d in the window, lake %.1f h behind" % (
            got, int(lk.get("files") or 0), "the whole window" if not int((have.get("lake") or {}).get("wm") or 0) else "since the last run", len(games) - n0, len(games),
            (now - int(lk.get("wm") or now)) / 3600.0))
    pool = set(pool_ids)
    by = {}
    for r in games.values():
        if r[1] in pool:
            by.setdefault(r[2], []).append({"account_id": r[1], "hero_build_id": r[3], "won": bool(r[4]), "start_time": r[5]})
    return by


def _assets(src, st, now):
    a = st.assets or {}
    if a.get("data") and a.get("v") == sources.ASSETS_V and now - int(a.get("at") or 0) < config.ASSETS_TTL:
        d = a["data"]
    else:
        d = src.assets()
        st.assets = {"at": now, "v": sources.ASSETS_V, "data": d}
    heroes = {int(h): {"key": v["key"], "slots": _ints(v.get("slots"))} for h, v in d["heroes"].items()}
    return heroes, _ints(d["items_up"]), _ints(d["items_ab"]), int(d.get("big_patch") or 0)


def _prev_season(src, st, w, log):
    """Last season's final standings for the handover. They no longer change, so the first full read is kept in the state for the
    whole handover. deadlock-api answers 504 when a query runs into its time limit (and fails at once for a few minutes after): then
    the last 90 days of that season are read instead and kept until a full read works."""
    start, end = w["prev"][0], w["prev"][1]
    season = "%d-%d" % (start, end)
    ps = st.prevseason or {}
    cached = [tuple(r) for r in ps.get("rows") or ()] if ps.get("season") == season else []
    if cached and ps.get("full"):
        return cached
    for t0, full in ((start, True), (max(start, end - 90 * DAY), False)):
        if not full and cached:
            return cached
        try:
            rows = src.scoreboard(t0, end)
        except api_mod.ApiError as e:
            log("feed: last season's standings from %s not read (%s)" % (shape.ymd(t0), e))
            continue
        st.prevseason = {"season": season, "full": full, "rows": [list(r) for r in rows]}
        return rows
    return cached


def _cur_season(src, w, now, log):
    """This season's standings; a 504 on the whole season narrows the window to the last 30 days (a second failure stops the run)."""
    try:
        return src.scoreboard(w["cur"][0], now)
    except api_mod.ApiError as e:
        if w["cur"][0] >= now - 30 * DAY:
            raise
        log("feed: this season's standings not read whole (%s), the last 30 days instead" % e)
        return src.scoreboard(now - 30 * DAY, now)


def _prev_lists(src, st, gen, log):
    """({rel: bytes}, prev gen): the last good run's list files from the state, else fetched back from the live site."""
    keep = st.load_lists()
    if not keep:
        raw = src.site_get("data/index.json")
        try:
            ix = json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            ix = None
        if ix and ix.get("gen"):
            g = str(ix["gen"])
            for hid in sorted(set(int(x) for x in (ix.get("heroes") or {}).values())):
                for rel in ("data/%s/%d.json" % (g, hid), "data/%s/popular/%d.json" % (g, hid)):
                    b = src.site_get(rel)
                    if b:
                        keep[rel] = b
            if keep:
                log("feed: previous generation fetched back from the site (%d files)" % len(keep))
    gens = sorted({rel.split("/")[1] for rel in keep if rel.startswith("data/") and rel.count("/") >= 2})
    prev = gens[-1] if gens else None
    if prev == gen:
        return {}, None
    return {rel: b for rel, b in keep.items() if rel.startswith("data/%s/" % prev)} if prev else {}, prev


def run(src, st, out, now, site_url="", history_dir=None, log=print, validate=True, site_dir=SITE_SRC):
    t_start = time.monotonic()
    now = int(now)
    gen = gen_of(now)
    heroes, items_up, items_ab, big_patch = _assets(src, st, now)

    # ---- who counts (5.2)
    w = pool.season_windows(src.seasons(), now)
    cur = _cur_season(src, w, now, log)
    prev_rows = _prev_season(src, st, w, log) if w["handover"] else []
    stand = pool.standings(cur, prev_rows, w["handover"])
    pool_ids = sorted(a for a, s in stand.items() if s[0] >= config.BADGE_ASC)
    due = st.regions_due(pool_ids, now)
    if due:
        try:
            st.put_regions(due, src.regions(due), now)
        except api_mod.ApiError as e:
            log("feed: regions not refreshed this run (%s)" % e)
    rmap = st.region_map(now)
    region_by = {a: rmap[a] for a in pool_ids if a in rmap}
    circle_of = pool.circles(stand, region_by)
    regions_on = bool(pool_ids) and len(region_by) >= config.REGIONS_KNOWN_SHARE * len(pool_ids)
    rby = region_by if regions_on else {}
    chips = [c for c in config.CHIPS if c in set(rby.values())]
    places = pool.region_places(stand, circle_of, rby)
    counts = {c: sum(1 for v in circle_of.values() if rank.RANK[v] >= rank.RANK[c]) for c in config.CIRCLES}
    log("feed: gen %s, pool %d (top %d, ete %d, asc %d), regions known %d%%%s, handover %s" % (
        gen, len(pool_ids), counts["top"], counts["ete"], counts["asc"], round(100 * len(region_by) / max(1, len(pool_ids))),
        (" (chips " + " ".join(chips) + ")") if chips else " (no chips yet)", "on" if w["handover"] else "off"))
    games_of = _pool_games(src, st, pool_ids, now, log)

    # ---- build metadata (5.1): a seed per hero when missing or a week old, else what changed since the last run
    meta = {int(k): v for k, v in st.meta["builds"].items()}
    missing = {int(k): int(v) for k, v in (st.meta.get("missing") or {}).items() if now - int(v) < MISSING_TTL}
    seeded, since = st.meta["seeded"], int(st.meta.get("since") or 0)
    n_seed = 0
    for h in sorted(heroes):
        s = int(seeded.get(str(h)) or 0)
        if s and now - s <= config.SEED_MAX_AGE:
            continue
        try:
            got = src.meta_seed(h, now - config.AUTHOR_DAYS * DAY)
        except api_mod.ApiError as e:
            log("feed: hero %d metadata seed failed (%s)" % (h, e))
            continue
        for b in [b for b, m in meta.items() if m.get("hero") == h]:
            del meta[b]
        meta.update({int(b): m for b, m in got.items()})
        seeded[str(h)] = now
        n_seed += 1
    if since:
        try:
            meta.update({int(b): m for b, m in src.meta_since(since - 3600).items()})
        except api_mod.ApiError as e:
            log("feed: metadata update failed (%s)" % e)
    st.meta["since"] = now
    fetched = [0]

    def ensure(pairs):
        need = [(h, b) for h, b in pairs if b in meta and "%d_%d" % (b, meta[b]["ver"]) not in st.details]
        if not need:
            return
        got = src.details(need)
        fetched[0] += len(got)
        for b, full in got.items():
            st.details["%d_%d" % (int(b), int(full.get("version") or 0))] = full
            meta[int(b)] = sources.slim(full)

    def det(b):
        return st.details.get("%d_%d" % (b, meta[b]["ver"])) if b in meta else None

    def lookup(h, ids):
        """Metadata and details of builds the metadata does not know, by id. An id the API answered without is remembered as
        unpublished for a day; one whose call failed (a rate limit, an outage) is asked again next run."""
        failed = []
        got = src.details([(h, b) for b in ids], failed)
        fetched[0] += len(got)
        lost = {int(b) for _, b in failed}
        for b in ids:
            if b in got:
                meta[b] = sources.slim(got[b])
                st.details["%d_%d" % (b, meta[b]["ver"])] = got[b]
            elif b not in lost:
                missing[b] = now

    # ---- popular (secondary, all ranks)
    pop_failed = False
    try:
        pop_all = src.popular(now - config.WINDOW_DAYS * DAY, now)
    except api_mod.ApiError as e:
        log("feed: popular not read this run (%s), the previous Popular lists are carried" % e)
        pop_all, pop_failed = [], True
    pop_by = {}
    for r in pop_all:
        pop_by.setdefault(int(r.get("hero_id") or 0), []).append(r)

    keep, prev_gen = _prev_lists(src, st, gen, log)
    lists, pops, carried, raw = {}, {}, [], {}
    games = known = empty_ete = 0
    working = set()     # detail keys of every build looked at this run (kept in the state, so the next run does not fetch them again)

    for h in sorted(heroes):
        key = heroes[h]["key"]
        slot_of = heroes[h]["slots"]
        rows = games_of.get(h, [])
        # builds this hero's players ran that the metadata does not know yet (older than the seed window): looked up by id
        unknown = sorted({int(r["hero_build_id"]) for r in rows if r.get("hero_build_id") and int(r["hero_build_id"]) >= MIN_PUBLISHED_ID
                          and int(r["hero_build_id"]) not in meta and int(r["hero_build_id"]) not in missing})[:UNKNOWN_MAX]
        if unknown:
            lookup(h, unknown)
        meta_h = {b: m for b, m in meta.items() if m.get("hero") == h}
        published = set(meta_h)

        def score(b, C, u, gone):
            m = meta[b]
            s = rank.use_of(u, b, C, circle_of, now)
            a_pts = rank.author_part(circle_of.get(m.get("author")), C)
            f = rank.fresh_part(int(m.get("upd") or 0), big_patch, s["last"] >= now - config.RECENT_DAYS * DAY, gone)
            return {"bid": b, "best": rank.best(s["use"], a_pts, f), "p": s["p"], "g": s["g"], "w": s["w"], "last": s["last"],
                    "tr": s["tr"], "upd": int(m.get("upd") or 0), "author": m.get("author"), "a_pts": a_pts, "fresh": f}

        # preliminary order without item penalties, then details for the top PRELIM of each circle (plan ruling 5)
        u0 = rank.aggregate(rows, circle_of, {}, now, published)
        top = set()
        for C in config.CIRCLES:
            sc = [score(b, C, u0, 0) for b in rank.candidates(h, meta_h, u0, circle_of, C, now)]
            sc.sort(key=lambda s: (s["best"], s["p"], s["upd"], s["bid"]), reverse=True)
            top.update(s["bid"] for s in sc[: config.PRELIM])
        prow = sorted((r for r in pop_by.get(h, ()) if int(r.get("hero_build_id") or 0) >= MIN_PUBLISHED_ID),
                      key=lambda r: (-int(r.get("players") or 0), -int(r.get("matches") or 0), int(r["hero_build_id"])))
        pop_ids = [int(r["hero_build_id"]) for r in prow[: config.POPULAR_CAP * 2]]
        unk = [b for b in pop_ids if b not in meta and b not in missing]
        if unk:
            lookup(h, unk)
        ensure([(h, b) for b in sorted(top | set(b for b in pop_ids if b in meta))])
        working.update("%d_%d" % (b, meta[b]["ver"]) for b in top | set(pop_ids) if b in meta)
        items, gone, mixes = {}, {}, {}
        for b in top:
            full = det(b)
            if full:
                items[b], gone[b] = shape.items_of(full, items_up)
                mixes[b] = shape.mix_of(full, items_up)
        alias = rank.dupes(items, meta)
        u = rank.aggregate(rows, circle_of, alias, now, published)
        games += u.games
        known += u.known
        order, scored = {}, {}
        for C in config.CIRCLES:
            cands = [b for b in rank.candidates(h, meta_h, u, circle_of, C, now) if b in items and b not in alias]
            sc = [score(b, C, u, gone[b]) for b in cands]
            order[C] = rank.select(sc, C)
            scored[C] = {s["bid"]: s for s in sc}
        listed = set().union(*order.values())
        out_rows = []
        for b in listed:
            m = meta[b]
            a = m.get("author")
            use = {}
            for C in config.CIRCLES:
                if b in order[C]:
                    s = scored[C][b]
                    e = {"p": s["p"], "g": s["g"], "w": s["w"], "last": s["last"], "best": s["best"], "n": order[C].index(b) + 1}
                    if s["p"]:
                        e["tr"] = s["tr"]   # [players in the last 7 days, in the 7 days before]: the circle's trend (not per region)
                    if chips:
                        e["r"] = rank.regions_for(u, b, C, circle_of, now, rby, rby.get(a), s["a_pts"], s["fresh"])
                    use[C] = e
            run_by = []
            for C in config.CIRCLES:
                rs = [(acc, x[0]) for acc, x in (u.runs.get(b) or {}).items() if rank._in(circle_of.get(acc), C)]
                if rs:
                    rs.sort(key=lambda t: (-t[1], t[0]))
                    run_by = [{"_a": acc, "badge": stand[acc][0], "g": g} for acc, g in rs[:3]]
                    break
            r = shape.row(b, m, shape.author("", stand.get(a), rby.get(a), places.get(a, 0), u.plays.get(a, 0)), use, run_by,
                          {"old": 1 if int(m.get("upd") or 0) < big_patch else 0, "gone": gone.get(b, 0)})
            if mixes.get(b):
                r["mix"] = mixes[b]   # [gun, vitality, spirit] percents of the build's souls
            r["author"]["_a"] = a
            out_rows.append(r)
        # places within each region view, with the same author cap as the all-region list
        for C in config.CIRCLES:
            for chip in chips:
                sc = [{"bid": r["id"], "best": r["use"][C]["r"][chip]["best"], "p": r["use"][C]["r"][chip]["p"], "upd": int(meta[r["id"]]["upd"]),
                       "author": meta[r["id"]].get("author")} for r in out_rows if C in r["use"] and chip in r["use"][C].get("r", {})]
                for n, b in enumerate(rank.select(sc, C, cap=None)):
                    next(r for r in out_rows if r["id"] == b)["use"][C]["r"][chip]["n"] = n + 1
        out_rows.sort(key=lambda r: (-max(v["best"] for v in r["use"].values()), -r["id"]))
        if not any("ete" in r["use"] for r in out_rows):
            empty_ete += 1
        head = {"v": 1, "hero": h, "key": key, "gen": gen, "made": shape.iso(now), "season": {"name": w["cur"][2], "handover": w["handover"]},
                "circles": counts, "cover": round(u.known / u.games, 3) if u.games else 0, "regions": chips}
        if big_patch:
            head["bigpatch"] = shape.ymd(big_patch)   # the last big patch's day: the pane's patch mark says since when
        lists[h] = dict(head, builds=out_rows)
        # Popular: the most played published builds of every rank, site builds tagged
        prows = []
        for r in prow:
            b = int(r["hero_build_id"])
            m = meta.get(b)
            if not m or m.get("dev") or m.get("hero") != h or not det(b):
                continue
            a = m.get("author")
            _, g_n = shape.items_of(det(b), items_up)
            pr = shape.row(b, m, shape.author("", stand.get(a), rby.get(a), places.get(a, 0), u.plays.get(a, 0)),
                           {"all": {"p": int(r.get("players") or 0), "g": int(r.get("matches") or 0), "w": int(r.get("wins") or 0)}}, [],
                           {"old": 1 if int(m.get("upd") or 0) < big_patch else 0, "gone": g_n}, site=rank.is_site(m, a in circle_of))
            pr["author"]["_a"] = a
            prows.append(pr)
            if len(prows) >= config.POPULAR_CAP:
                break
        prel = "data/%s/popular/%d.json" % (prev_gen, h)
        if pop_failed and prev_gen and prel in keep:   # the Popular source failed: the previous list stays rather than an empty one
            raw["data/%s/popular/%d.json" % (gen, h)] = keep[prel]
        else:
            pops[h] = dict(head, builds=prows)
        log("feed: hero %d %s: %d games, %d listed (ete %d), popular %d" % (
            h, key, u.games, len(out_rows), sum(1 for r in out_rows if "ete" in r["use"]), len(prows)))

    # ---- names, only for the accounts the rows show
    shown = set()
    for obj in list(lists.values()) + list(pops.values()):
        for r in obj["builds"]:
            shown.add(r["author"]["_a"])
            shown.update(x["_a"] for x in r["run"])
    shown.discard(None)
    have, ask = st.names_fresh(sorted(shown), now)
    if ask:
        try:
            got = src.names(ask)
            st.put_names(ask, got, now)
            have.update(got)
        except api_mod.ApiError as e:
            log("feed: names not refreshed this run (%s), the cached ones are used" % e)
            have.update(st.names_stale(ask))
    # a Steam name is free text: cleaned like every feed text (a leading '#', markup, {...}, control and direction characters);
    # a name that cleans to nothing is shown as no name
    names = {a: clean.clean_text(n, config.PLAYER_NAME_MAX) for a, n in have.items()}
    for obj in list(lists.values()) + list(pops.values()):
        for i, r in enumerate(obj["builds"]):
            r["author"]["name"] = names.get(r["author"].get("_a"), "")
            r["run"] = [{"name": names[x["_a"]], "badge": x["badge"], "g": x["g"]} for x in r["run"] if names.get(x["_a"])]
            obj["builds"][i] = shape.public(r)

    # ---- files
    files = {}
    refs = {}
    for h, obj in lists.items():
        obj, dropped = shape.fit_list(obj)
        if dropped:
            log("feed: hero %d list trimmed by %d rows (size guard)" % (h, dropped))
        files["data/%s/%d.json" % (gen, h)] = obj
        for r in obj["builds"]:
            refs[(r["id"], r["ver"])] = h
    for h, obj in pops.items():
        obj, dropped = shape.fit_list(obj)
        files["data/%s/popular/%d.json" % (gen, h)] = obj
        for r in obj["builds"]:
            refs[(r["id"], r["ver"])] = h
    for rel, b in list(keep.items()) + list(raw.items()):
        try:
            obj = json.loads(b.decode("utf-8"))
        except ValueError:
            continue
        for r in obj.get("builds") or ():
            refs.setdefault((int(r["id"]), int(r["ver"])), int(obj.get("hero") or 0))
    n_det = 0
    for (b, ver), h in sorted(refs.items()):
        full = st.details.get("%d_%d" % (b, ver))
        if not full:
            continue
        d, how = shape.fit_detail(shape.detail(full, items_up, (heroes.get(h) or {}).get("slots") or {}))
        if how:
            log("feed: build %d details trimmed (%s)" % (b, how))
        files["data/b/%d_%d.json" % (b, ver)] = d
        n_det += 1
    with_lists = sorted(h for h in heroes if lists.get(h, {}).get("builds")) + [h for h in carried]
    files["data/index.json"] = {
        "v": 1, "gen": gen, "prev": prev_gen, "made": shape.iso(now),
        "season": {"name": w["cur"][2], "handover": w["handover"], "until": shape.iso(w["until"])},
        "circles": counts, "cover": round(known / games, 3) if games else 0, "regions": chips,
        "heroes": {heroes[h]["key"]: h for h in sorted(heroes)}, "lists": sorted(set(with_lists)), "carried": carried}

    # ---- validate, write, keep the state
    stats = {"pool": len(pool_ids), "empty_ete": empty_ete, "with_lists": len(set(with_lists)), "gen": gen}
    st.meta["builds"] = {str(b): m for b, m in meta.items()}
    st.meta["missing"] = {str(b): t for b, t in missing.items()}
    st.drop_old_names(now)
    if validate:
        ok, reasons = publish.validate(stats, st.stats)
        if not ok:
            # a failure heals (final review): HEAL_RUNS failing runs in a row at one steady level (after a good run) are the new level
            last = st.stats or {}
            streak = last.get("streak") or {}
            steady = bool(streak) and abs(int(streak.get("pool", 0)) - stats["pool"]) <= config.HEAL_POOL * max(1, int(streak.get("pool", 0))) \
                and abs(int(streak.get("empty_ete", 0)) - stats["empty_ete"]) <= config.EMPTY_ETE_JUMP
            count = int(streak.get("count", 0)) + 1 if steady else 1
            if "pool" not in last or count < config.HEAL_RUNS:
                log("feed: validation failed (%d/%d at this level), nothing written: %s" % (count, config.HEAL_RUNS, "; ".join(reasons)))
                if "pool" in last:
                    st.stats = dict(last, streak={"count": count, "pool": int(streak.get("pool", stats["pool"])) if steady else stats["pool"],
                                                  "empty_ete": stats["empty_ete"]})
                st.save()
                return 1
            log("feed: validation failed %d runs in a row at one steady level, taken as the new level: %s" % (count, "; ".join(reasons)))
    publish.write(out, site_dir, files, dict(keep, **raw))
    used = {"%d_%d" % k for k in refs} | working
    st.details = {k: v for k, v in st.details.items() if k in used}
    cur_lists = {rel: shape.dumps(obj).encode("utf-8") for rel, obj in files.items() if rel.startswith("data/%s/" % gen)}
    cur_lists.update(raw)
    st.save_lists(cur_lists)
    st.stats = stats
    st.save()
    if history_dir:
        day = shape.ymd(now)
        p = Path(history_dir) / ("%s.json" % day)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(shape.dumps(publish.history(lists, day, gen)).encode("utf-8"))
    log("feed: wrote %d files (%d build details, %d fetched), %d carried, %d seeds, %d requests, %.0f MB read by GraphQL, %.1f s" % (
        len(files) + len(keep) + len(raw), n_det, fetched[0], len(carried), n_seed, src.count, getattr(src, "read_bytes", 0) / 1e6,
        time.monotonic() - t_start))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Nightshift builds feed: one hourly run")
    p.add_argument("--out", required=True, help="the site folder to write (published)")
    p.add_argument("--state", required=True, help="the job's private state folder (never published)")
    p.add_argument("--site-url", default="", help="the live site's root URL (User-Agent; the previous generation's fallback)")
    p.add_argument("--history", default=None, help="folder for the daily snapshot data/history/YYYY-MM-DD.json")
    p.add_argument("--now", type=int, default=None, help=argparse.SUPPRESS)
    p.add_argument("--api", default=config.API, help=argparse.SUPPRESS)
    p.add_argument("--offline-world", action="store_true", help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    try:
        state_mod.check_dirs(a.out, a.state)
    except ValueError as e:
        print("feed: " + str(e))
        return 2
    now = a.now or int(time.time())
    st = state_mod.State(a.state).load()
    if a.offline_world:
        from tests.world import World
        src = World(now)
    else:
        ua = "NightshiftBuilds/1 (+%s)" % (a.site_url or "https://github.com/")
        src = Live(api_mod.Api(base=a.api, ua=ua, key=os.environ.get("DEADLOCK_API_KEY") or None), a.site_url)
    try:
        return run(src, st, a.out, now, a.site_url, a.history, print)
    except api_mod.ApiError as e:
        print("feed: stopped, deadlock-api answered %s" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
