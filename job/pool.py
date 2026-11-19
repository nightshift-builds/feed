"""Who counts: season windows, each player's standing and their circle (spec 5.2). All by the player's own rank, never a match average."""
import config

DAY = 86_400


def season_windows(seasons, now):
    """{cur: (start, end, name), prev: (start, end, name) | None, handover, until} from /v1/assets/ranked-seasons. cur is the interval
    that holds now (else the last one started); prev the interval before it; handover while now < cur start + HANDOVER_DAYS."""
    iv = []
    for s in seasons or ():
        for i in s.get("intervals") or ():
            try:
                iv.append((int(i["start_timestamp"]), int(i["end_timestamp"]), str(s.get("name") or s.get("class_name") or "")))
            except (KeyError, TypeError, ValueError):
                continue
    iv.sort()
    if not iv:
        raise ValueError("no ranked season intervals")
    started = [x for x in iv if x[0] <= now]
    cur = next((x for x in started if now < x[1]), None) or (started[-1] if started else iv[0])
    k = iv.index(cur)
    prev = iv[k - 1] if k > 0 else None
    until = cur[0] + config.HANDOVER_DAYS * DAY
    return {"cur": cur, "prev": prev, "handover": prev is not None and now < until, "until": until}


def _rows(rows):
    out = {}
    for acct, badge, value in rows or ():
        out[int(acct)] = (int(badge or 0), int(value or 0))
    return out


def standings(cur_rows, prev_rows, handover):
    """acct -> (badge, value, last_season). Rows are (acct, badge, value) from the scoreboard. During the handover a player's standing
    is the better of this season's badge and last season's final badge (last_season True when last season's is used)."""
    cur = _rows(cur_rows)
    out = {a: (b, v, False) for a, (b, v) in cur.items()}
    if handover:
        for a, (b, v) in _rows(prev_rows).items():
            if a not in out or b > out[a][0]:
                out[a] = (b, v, True)
    return out


def circles(stand, region_by_acct):
    """acct -> the highest circle ("top" | "ete" | "asc") of every player at Ascendant I or higher.

    Top 100 (plan Task 1 ruling): Eternus+ players only, so the circles nest (Top 100 within Eternus+ within Ascendant+). With regions
    known for at least REGIONS_KNOWN_SHARE of the pool: the 100 best by (badge, value) in each region chip; in a region other than NA
    and EU only those at or above the lower of NA's and EU's 100th (a small region's 100 best are not all top players). Without
    regions: the global 300 best."""
    elig = {a: s for a, s in stand.items() if s[0] >= config.BADGE_ASC}
    out = {a: ("ete" if s[0] >= config.BADGE_ETE else "asc") for a, s in elig.items()}
    if not elig:
        return out
    region_by_acct = region_by_acct or {}
    ete = [a for a in elig if elig[a][0] >= config.BADGE_ETE]
    known = [a for a in elig if region_by_acct.get(a)]
    key = lambda a: (elig[a][0], elig[a][1], -a)
    if len(known) >= config.REGIONS_KNOWN_SHARE * len(elig):
        by = {}
        for a in ete:
            if region_by_acct.get(a):
                by.setdefault(region_by_acct[a], []).append(a)
        tops = {r: sorted(accts, key=key, reverse=True)[: config.TOP_REGION] for r, accts in by.items()}
        bars = [elig[tops[r][-1]][:2] for r in ("na", "eu") if len(tops.get(r) or ()) >= config.TOP_REGION]
        bar = min(bars) if bars else None
        for r, accts in tops.items():
            for a in accts:
                if r in ("na", "eu") or bar is None or elig[a][:2] >= bar:
                    out[a] = "top"
    else:
        for a in sorted(ete, key=key, reverse=True)[: config.TOP_GLOBAL]:
            out[a] = "top"
    return out


def region_places(stand, circle_of, region_by_acct):
    """acct -> place (1-based) in their region by (badge, value), for the accounts of the pool with a known region."""
    by = {}
    for a in circle_of:
        r = (region_by_acct or {}).get(a)
        if r:
            by.setdefault(r, []).append(a)
    out = {}
    for accts in by.values():
        for i, a in enumerate(sorted(accts, key=lambda a: (stand[a][0], stand[a][1], -a), reverse=True)):
            out[a] = i + 1
    return out
