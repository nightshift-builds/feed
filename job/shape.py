"""The published JSON shapes (spec 6.2) and the size guard (5.7). Rows carry names only for the accounts they show, never account ids."""
import datetime
import json

import clean
import config


def dumps(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def ymd(t):
    return datetime.datetime.fromtimestamp(int(t), datetime.timezone.utc).strftime("%Y-%m-%d") if t else ""


def iso(t):
    return datetime.datetime.fromtimestamp(int(t), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def author(name, stand, chip, pos, plays):
    """{name, badge, ls?, region, pos, plays}: ls = the badge is last season's final (the 28-day handover)."""
    badge, _value, last = stand if stand else (0, 0, False)
    a = {"name": name or "", "badge": int(badge or 0)}
    if last:
        a["ls"] = 1
    a["region"] = chip or ""
    a["pos"] = int(pos or 0)
    a["plays"] = int(plays or 0)
    return a


def row(bid, m, auth, use, run, patch, site=False):
    r = {"id": int(bid), "ver": int(m.get("ver") or 0), "name": clean.clean_text(m.get("name"), config.NAME_MAX),
         "lang": clean.lang_code(m.get("lang")), "upd": ymd(m.get("upd"))}
    if site:
        r["site"] = 1
    r["author"] = auth
    r["use"] = use
    r["run"] = run
    r["patch"] = patch
    return r


def detail(full, items_up, slot_of):
    """One build's details: {v, id, ver, desc?, phases: [{n, i: [item class names], a?: {class: annotation}}], abil: [12 slots]}.
    Categories mapping to the same phase merge; items repeat once per phase; items the assets do not know are dropped."""
    d = full.get("details") or {}
    phases, by = [], {}
    for cat in d.get("mod_categories") or ():
        n = clean.phase_of(cat.get("name"))
        for mod in cat.get("mods") or ():
            try:
                e = items_up.get(int(mod.get("ability_id")))
            except (TypeError, ValueError):
                continue
            if not e:
                continue
            cls = e[0]
            ph = by.get(n)
            if ph is None:
                ph = by[n] = {"n": n, "i": []}
                phases.append(ph)
            if cls in ph["i"]:
                continue
            ph["i"].append(cls)
            note = clean.clean_text(mod.get("annotation"), config.NOTE_MAX)
            if note:
                ph.setdefault("a", {})[cls] = note
    out = {"v": 1, "id": int(full.get("hero_build_id") or 0), "ver": int(full.get("version") or 0)}
    desc = clean.clean_text(full.get("description"), config.DESC_MAX)
    if desc:
        out["desc"] = desc
    out["phases"] = phases
    out["abil"] = clean.ability_slots((d.get("ability_order") or {}).get("currency_changes"), slot_of)
    return out


def items_of(full, items_up):
    """The build's item class names, as a set (for duplicates) and the count of items gone from the shop (unknown or not shopable)."""
    names, gone = set(), set()
    for cat in (full.get("details") or {}).get("mod_categories") or ():
        for mod in cat.get("mods") or ():
            try:
                iid = int(mod.get("ability_id"))
            except (TypeError, ValueError):
                continue
            e = items_up.get(iid)
            if e:
                names.add(e[0])
            if not e or not e[1]:
                gone.add(iid)
    return frozenset(names), len(gone)


def mix_of(full, items_up):
    """[gun, vitality, spirit]: integer percents of the souls of the build's distinct items (each counted once), by the slot and cost
    the assets give (items_up[id] = [class name, shopable, slot g/v/s, cost]); largest remainder, so they sum to 100. None when no item
    of the build has a known slot and a cost (unknown items, assets of an older state without them)."""
    seen, tot = set(), {"g": 0, "v": 0, "s": 0}
    for cat in (full.get("details") or {}).get("mod_categories") or ():
        for mod in cat.get("mods") or ():
            try:
                iid = int(mod.get("ability_id"))
            except (TypeError, ValueError):
                continue
            e = items_up.get(iid)
            if iid in seen or not e or len(e) < 4 or e[2] not in tot:
                continue
            seen.add(iid)
            tot[e[2]] += max(0, int(e[3] or 0))
    total = sum(tot.values())
    if total <= 0:
        return None
    raw = [100.0 * tot[k] / total for k in ("g", "v", "s")]
    out = [int(x) for x in raw]
    for i in sorted(range(3), key=lambda i: -(raw[i] - out[i]))[:100 - sum(out)]:
        out[i] += 1
    return out


def _size(obj):
    return len(dumps(obj).encode("utf-8"))


def _rank(r):
    u = r.get("use") or {}
    bests = [v.get("best", 0) for v in u.values() if isinstance(v, dict) and "best" in v]
    if bests:
        return max(bests)
    return float((u.get("all") or {}).get("p", 0))


def fit_list(obj):
    """(obj, dropped): rows with the lowest score leave until the compact JSON is at most LIST_MAX bytes (never a failure)."""
    dropped = 0
    while obj.get("builds") and _size(obj) > config.LIST_MAX:
        rows = obj["builds"]
        low = min(range(len(rows)), key=lambda i: (_rank(rows[i]), -i))
        del rows[low]
        dropped += 1
    return obj, dropped


def fit_detail(obj):
    """(obj, how): annotations shortened to 60, then dropped, then the description shortened to 100, then dropped, until the detail is
    at most DETAIL_MAX bytes."""
    how = []
    if _size(obj) > config.DETAIL_MAX:
        for ph in obj.get("phases") or ():
            if "a" in ph:
                ph["a"] = {k: (v if len(v) <= 60 else v[:59] + "…") for k, v in ph["a"].items()}
        how.append("annotations shortened")
    if _size(obj) > config.DETAIL_MAX:
        for ph in obj.get("phases") or ():
            ph.pop("a", None)
        how.append("annotations dropped")
    if _size(obj) > config.DETAIL_MAX and obj.get("desc"):
        obj["desc"] = obj["desc"][:99] + "…" if len(obj["desc"]) > 100 else obj["desc"]
        how.append("description shortened")
    if _size(obj) > config.DETAIL_MAX and "desc" in obj:
        del obj["desc"]
        how.append("description dropped")
    return obj, ", ".join(how)


def public(r):
    """A row without its private fields (keys starting with '_': account ids kept while names are looked up)."""
    out = {k: v for k, v in r.items() if not k.startswith("_")}
    if isinstance(out.get("run"), list):
        out["run"] = [{k: v for k, v in x.items() if not k.startswith("_")} for x in out["run"]]
    if isinstance(out.get("author"), dict):
        out["author"] = {k: v for k, v in out["author"].items() if not k.startswith("_")}
    return out
