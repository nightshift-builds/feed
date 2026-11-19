"""Which builds high-rank players run and write, and in what order (spec 5.3-5.5). Pure functions: no I/O, now is passed in."""
import math

import config

DAY = 86_400
RANK = config.CIRCLE_RANK


class Usage:
    """One hero's games of pool players in the window.

    runs[bid][acct] = [games, wins, last start_time] for published builds; main[acct] = the account's most-played build on this hero
    (any build id, published or not; ties: the later last game); games / known = pool games and those whose build is published (the
    cover); plays[acct] = the account's games on this hero."""

    def __init__(self):
        self.runs = {}
        self.main = {}
        self.games = 0
        self.known = 0
        self.plays = {}


def aggregate(rows, circle_of, alias, now, published):
    """rows: Normal games of one hero within the window, {account_id, hero_build_id, won, start_time}; only pool accounts (circle_of)
    count. alias maps a folded duplicate's id to the build it folds into; published: the published build ids."""
    u = Usage()
    per = {}
    alias = alias or {}
    for r in rows:
        try:
            a = int(r["account_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if a not in circle_of:
            continue
        u.games += 1
        u.plays[a] = u.plays.get(a, 0) + 1
        bid = r.get("hero_build_id")
        if not bid:
            continue
        bid = int(bid)
        bid = alias.get(bid, bid)
        t = int(r.get("start_time") or 0)
        m = per.setdefault(a, {}).setdefault(bid, [0, 0])
        m[0] += 1
        m[1] = max(m[1], t)
        if bid in published:
            u.known += 1
            x = u.runs.setdefault(bid, {}).setdefault(a, [0, 0, 0, 0])
            x[0] += 1
            x[1] += 1 if r.get("won") else 0
            x[2] = max(x[2], t)
            x[3] = t if not x[3] else min(x[3], t)
    for a, d in per.items():
        u.main[a] = max(d.items(), key=lambda kv: (kv[1][0], kv[1][1], -kv[0]))[0]
    return u


def _in(c, C):
    return bool(c) and RANK[c] >= RANK[C]


def use_of(usage, bid, C, circle_of, now, region=None, region_of_acct=None):
    """{use, p, g, w, last} of build bid in circle C (runners: players whose circle is C or higher), optionally only the players of a
    region chip. use = sum of W[circle] * (1 if the build is the runner's main build here, else MAIN_OTHER) * (1 if their last game on
    it is within RECENT_DAYS, else RECENT_OLD)."""
    use, p, g, w, last, n7, b7 = 0.0, 0, 0, 0, 0, 0, 0
    half = now - config.RECENT_DAYS * DAY
    for a, x in (usage.runs.get(bid) or {}).items():
        ga, wa, la = x[0], x[1], x[2]
        fa = x[3] if len(x) > 3 and x[3] else la
        c = circle_of.get(a)
        if not _in(c, C):
            continue
        if region is not None and (region_of_acct or {}).get(a) != region:
            continue
        use += config.W[c] * (1.0 if usage.main.get(a) == bid else config.MAIN_OTHER) * \
            (1.0 if now - la <= config.RECENT_DAYS * DAY else config.RECENT_OLD)
        p += 1
        g += ga
        w += wa
        last = max(last, la)
        # the trend: players with a game in the last 7 days, and with one in the 7 days before (a player can count in both)
        if la >= half:
            n7 += 1
        if fa < half:
            b7 += 1
    return {"use": round(use, 6), "p": p, "g": g, "w": w, "last": last, "tr": [n7, b7]}


def author_part(author_circle, C):
    """2 + 1 (Eternus+ or Top 100) + 1 (Top 100) when the author is in C; 1 when the author is Ascendant+ but not in C; else 0."""
    if not author_circle:
        return 0
    if _in(author_circle, C):
        return 2 + (1 if RANK[author_circle] >= RANK["ete"] else 0) + (1 if author_circle == "top" else 0)
    return 1


def fresh_part(upd, big_patch, ran_7d, gone):
    """-1 when not updated since the last big patch and nobody in the circle played it in 7 days; -0.5 per item gone from the shop, at
    most -1."""
    f = 0.0
    if big_patch and upd < big_patch and not ran_7d:
        f -= 1
    f -= min(1.0, 0.5 * max(0, gone))
    return f


def best(use, author, fresh):
    return round(3 * math.log2(1 + use) + author + fresh, 3)


def is_site(m, in_pool):
    """A site build: by an author outside the Ascendant+ pool with a site marker in its name or description, or by a site account."""
    if m.get("author") in config.SITE_ACCOUNTS:
        return True
    if in_pool:
        return False
    text = (str(m.get("name") or "") + " " + str(m.get("desc") or "")).lower()
    return any(k in text for k in config.SITE_MARKERS)


def candidates(hero_id, meta_by_id, usage, circle_of, C, now):
    """Published builds of the hero that enter circle C's list: written by a player in C and updated within AUTHOR_DAYS, or run by at
    least one player in C. Out: dev builds, ids without metadata, site builds."""
    out = set()
    cutoff = now - config.AUTHOR_DAYS * DAY
    for bid, m in meta_by_id.items():
        if m.get("hero") == hero_id and _in(circle_of.get(m.get("author")), C) and int(m.get("upd") or 0) >= cutoff:
            out.add(bid)
    for bid, runners in usage.runs.items():
        m = meta_by_id.get(bid)
        if m and m.get("hero") == hero_id and any(_in(circle_of.get(a), C) for a in runners):
            out.add(bid)
    keep = []
    for bid in sorted(out):
        m = meta_by_id[bid]
        if m.get("dev") or is_site(m, m.get("author") in circle_of):
            continue
        keep.append(bid)
    return keep


def dupes(items_by_id, meta_by_id):
    """The alias map {duplicate id: kept id} among builds with item sets (items_by_id: bid -> frozenset of item class names).

    The same author, hero and item set keep the newest (update time, then id). "Copy of <X>" with X's exact name (any case), the same
    hero and the same item set folds into X. Builds without items are never folded."""
    alias = {}
    groups = {}
    for bid, items in items_by_id.items():
        m = meta_by_id.get(bid)
        if not m or not items:
            continue
        groups.setdefault((m.get("author"), m.get("hero"), items), []).append(bid)
    for bids in groups.values():
        if len(bids) < 2:
            continue
        keep = max(bids, key=lambda b: (int(meta_by_id[b].get("upd") or 0), b))
        for b in bids:
            if b != keep:
                alias[b] = keep
    by_name = {}
    for bid, items in items_by_id.items():
        m = meta_by_id.get(bid)
        if m and items and bid not in alias:
            by_name.setdefault((str(m.get("name") or "").strip().lower(), m.get("hero"), items), []).append(bid)
    for bid, items in items_by_id.items():
        m = meta_by_id.get(bid)
        if not m or not items or bid in alias:
            continue
        name = str(m.get("name") or "").strip()
        if name.lower().startswith("copy of "):
            orig = by_name.get((name[8:].strip().lower(), m.get("hero"), items))
            orig = [b for b in orig or () if b != bid]
            if orig:
                alias[bid] = max(orig, key=lambda b: (int(meta_by_id[b].get("upd") or 0), b))
    return alias


def select(scored, C, cap=config.CAP):
    """Build ids in list order: best desc, then runners, then update time, then id, all desc; at most AUTHOR_CAP builds of one author
    within the first AUTHOR_CAP_TOP places (later ones move after them, in their own order); at most `cap` builds (None: all, for the
    places inside a region view)."""
    order = sorted(scored, key=lambda s: (s["best"], s["p"], s["upd"], s["bid"]), reverse=True)
    head, deferred, rest, cnt = [], [], [], {}
    for s in order:
        if len(head) < config.AUTHOR_CAP_TOP:
            a = s.get("author")
            if cnt.get(a, 0) >= config.AUTHOR_CAP:
                deferred.append(s)
                continue
            cnt[a] = cnt.get(a, 0) + 1
            head.append(s)
        else:
            rest.append(s)
    ids = [s["bid"] for s in head + deferred + rest]
    return ids if cap is None else ids[:cap]


def regions_for(usage, bid, C, circle_of, now, region_of_acct, author_chip, author_pts, fresh_pts):
    """{chip: {p, g, w, best}} for build bid in circle C: every chip whose players in C ran it, plus the author's own chip (a build
    written there stays in that view with p 0). best uses the region's own use with the build's author and fresh parts."""
    chips = set()
    for a in (usage.runs.get(bid) or {}):
        if _in(circle_of.get(a), C) and (region_of_acct or {}).get(a):
            chips.add(region_of_acct[a])
    if author_chip:
        chips.add(author_chip)
    out = {}
    for chip in sorted(chips):
        u = use_of(usage, bid, C, circle_of, now, region=chip, region_of_acct=region_of_acct)
        out[chip] = {"p": u["p"], "g": u["g"], "w": u["w"], "best": best(u["use"], author_pts, fresh_pts)}
    return out
