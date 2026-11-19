"""One function per deadlock-api source the job reads (spec 5.1), with its parsing. Each takes the Api first."""
import datetime
import json

import api as api_mod
import clean
import config

GAME_NORMAL = "Normal"
SLIM = "hero_build_id hero_id author_account_id name description language version last_updated_timestamp development_build"
FULL = SLIM + (" details { mod_categories { name mods { ability_id annotation } }"
               " ability_order { currency_changes { ability_id currency_type delta } } }")


def hour(t):
    return int(t) // 3600 * 3600


def _ids(ids):
    return sorted({int(x) for x in ids})


def seasons(api):
    return api.get("/v1/assets/ranked-seasons", {}) or []


def scoreboard(api, t0, t1):
    """[(acct, badge, value)] of ranked players in [t0, t1], best first: pages of 10,000 while a full page still ends at Ascendant+
    (at most 3 pages). Hour-rounded times, so the edge cache serves repeats."""
    out, start = [], 0
    for _ in range(3):
        params = {"sort_by": "rank", "sort_direction": "desc", "match_mode": "ranked", "min_matches": 1, "limit": 10000,
                  "min_unix_timestamp": hour(t0), "max_unix_timestamp": hour(t1)}
        if start:
            params["start"] = start        # the first page leaves it out: the URL shape the edge cache already holds
        rows = api.get("/v1/analytics/scoreboards/players", params) or []
        for r in rows:
            out.append((int(r["account_id"]), int(r.get("badge") or 0), int(r.get("value") or 0)))
        if len(rows) < 10000 or int(rows[-1].get("badge") or 0) < config.BADGE_ASC:
            break
        start += 10000
    return out


def hero_rows(api, hero_id, ids, since):
    """Normal games of the given accounts on one hero since `since`: [{account_id, hero_build_id, won, start_time}] (GraphQL
    match_players, pages of 10,000, at most 5)."""
    idl = ", ".join(str(i) for i in _ids(ids))
    out = []
    for page in range(5):
        q = ("{ match_players(where: {account_id: {in: [%s]}, hero_id: {eq: %d}, start_time: {gte: %d}, game_mode: {eq: %s}}, "
             "order_by: START_TIME, order_direction: DESC, limit: 10000, offset: %d) "
             "{ account_id hero_build_id won start_time } }") % (idl, int(hero_id), int(since), json.dumps(GAME_NORMAL), page * 10000)
        rows = (api.gql(q) or {}).get("match_players") or []
        out.extend(rows)
        if len(rows) < 10000:
            break
    return out


def popular(api, since, until):
    """hero-build-stats over every hero (all ranks), builds with at least 20 games: [{hero_id, hero_build_id, players, matches, wins}]."""
    return api.get("/v1/analytics/hero-build-stats", {
        "min_unix_timestamp": hour(since), "max_unix_timestamp": hour(until), "min_matches": 20}) or []


def slim(hb):
    """A build's slim metadata from a GraphQL hero_build object."""
    return {"hero": int(hb.get("hero_id") or 0), "author": int(hb.get("author_account_id") or 0),
            "upd": int(hb.get("last_updated_timestamp") or 0), "ver": int(hb.get("version") or 0), "lang": int(hb.get("language") or 0),
            "name": str(hb.get("name") or "")[:200], "desc": str(hb.get("description") or "")[:300], "dev": bool(hb.get("development_build"))}


def _meta(api, where):
    out = {}
    for page in range(10):
        q = ("{ hero_builds(where: {%s, only_latest: true}, order_by: UPDATED_AT, order_direction: DESC, limit: 5000, offset: %d) "
             "{ hero_build { %s } } }") % (where, page * 5000, SLIM)
        rows = (api.gql(q) or {}).get("hero_builds") or []
        for r in rows:
            hb = r.get("hero_build") or {}
            if hb.get("hero_build_id"):
                out[int(hb["hero_build_id"])] = slim(hb)
        if len(rows) < 5000:
            break
    return out


def meta_seed(api, hero_id, since):
    """{bid: slim} of one hero's published builds (latest versions) updated since `since`."""
    return _meta(api, "hero_id: %d, min_unix_timestamp: %d" % (int(hero_id), int(since)))


def meta_since(api, since):
    """{bid: slim} of every hero's builds updated since `since` (the hourly incremental update)."""
    return _meta(api, "min_unix_timestamp: %d" % int(since))


def _batch(api, pairs):
    q = "{ " + " ".join("b%d: hero_builds(where: {hero_id: %d, build_id: %d, only_latest: true}, limit: 1, offset: 0) { hero_build { %s } }"
                        % (i, int(h), int(b), FULL) for i, (h, b) in enumerate(pairs)) + " }"
    data = api.gql(q) or {}
    out = {}
    for i in range(len(pairs)):
        for r in data.get("b%d" % i) or ():
            hb = r.get("hero_build") or {}
            if hb.get("hero_build_id"):
                out[int(hb["hero_build_id"])] = hb
    return out


def details(api, pairs, failed=None):
    """{bid: full hero_build} for (hero_id, build_id) pairs, 20 aliased queries a call. A batch refused otherwise (for example as too
    complex) is tried again one by one; after a rate limit or an overload (429 / 503, already retried by the client) it is not. Pairs
    whose call failed go to `failed`, so the caller does not take them for unpublished builds."""
    pairs = list(pairs)
    out = {}
    lost = failed if failed is not None else []
    for k in range(0, len(pairs), 20):
        chunk = pairs[k:k + 20]
        try:
            out.update(_batch(api, chunk))
        except api_mod.ApiError as e:
            if e.status in (429, 503) or len(chunk) == 1:
                lost.extend(chunk)
                continue
            for p in chunk:
                try:
                    out.update(_batch(api, [p]))
                except api_mod.ApiError:
                    lost.append(p)
    return out


def names(api, ids):
    """{acct: Steam name} for up to 1000 accounts a call; protected accounts are absent."""
    ids = _ids(ids)
    out = {}
    for k in range(0, len(ids), 1000):
        for r in api.get("/v1/players/steam", {"account_ids": ids[k:k + 1000]}) or ():
            if r.get("account_id") is not None and r.get("personaname"):
                out[int(r["account_id"])] = str(r["personaname"])
    return out


def regions(api, ids):
    """{acct: region chip | None} for up to 1000 accounts a call (/v1/players/region gives a server region; protected accounts are
    absent)."""
    ids = _ids(ids)
    out = {}
    for k in range(0, len(ids), 1000):
        for r in api.get("/v1/players/region", {"account_ids": ids[k:k + 1000]}) or ():
            if r.get("account_id") is not None:
                out[int(r["account_id"])] = clean.region_of(r.get("region"))
    return out


def _when(s):
    s = str(s).strip()
    if not s:
        return 0
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.datetime.fromisoformat(s)
    except ValueError:
        return 0
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return int(d.timestamp())


def assets(api):
    """{heroes: {id: {key, slots: {ability item id: 1-4}}}, items_up: {id: [class_name, shopable]}, items_ab: {id: class_name}, big_patch}.
    Heroes: the player-selectable ones that are not disabled (in-development heroes such as Baba included)."""
    up = {int(i["id"]): [str(i.get("class_name") or ""), bool(i.get("shopable"))]
          for i in api.get("/v1/assets/items/by-type/upgrade", {}) or () if i.get("id") is not None}
    ab = {int(i["id"]): str(i.get("class_name") or "") for i in api.get("/v1/assets/items/by-type/ability", {}) or () if i.get("id") is not None}
    ab_id = {c: i for i, c in ab.items()}
    heroes = {}
    for h in api.get("/v1/assets/heroes", {}) or ():
        cls = str(h.get("class_name") or "")
        if not h.get("player_selectable") or h.get("disabled") or not cls.startswith("hero_"):
            continue
        items = h.get("items") or {}
        slots = {}
        for s in (1, 2, 3, 4):
            c = items.get("signature%d" % s)
            if c in ab_id:
                slots[ab_id[c]] = s
        heroes[int(h["id"])] = {"key": cls[5:], "slots": slots}
    days = [_when(d) for d in api.get("/v1/patches/big-days", {}) or ()]
    return {"heroes": heroes, "items_up": up, "items_ab": ab, "big_patch": max(days) if days else 0}
