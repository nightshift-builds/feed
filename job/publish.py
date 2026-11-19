"""Publishing the feed (spec 5.7): validation before a deploy, the atomic write of _site/, the daily history snapshot, and a check that
no account id reaches a published file."""
import os
import re
import shutil
from pathlib import Path

import config
import shape


def validate(stats, prev):
    """(ok, reasons). With a previous good run: the pool may not fall under half of it, and more than EMPTY_ETE_MAX heroes without an
    Eternus+ list fail only when that is a jump of more than EMPTY_ETE_JUMP (plan ruling 1: after the handover sparse lists are normal).
    The first run needs FIRST_POOL_MIN players and FIRST_HEROES_MIN heroes with lists."""
    reasons = []
    if not prev or "pool" not in prev:
        if stats["pool"] < config.FIRST_POOL_MIN:
            reasons.append("pool %d under %d on the first run" % (stats["pool"], config.FIRST_POOL_MIN))
        if stats["with_lists"] < config.FIRST_HEROES_MIN:
            reasons.append("%d heroes with lists, under %d on the first run" % (stats["with_lists"], config.FIRST_HEROES_MIN))
    else:
        if stats["pool"] < prev["pool"] / 2.0:
            reasons.append("pool %d under half of the last run's %d" % (stats["pool"], prev["pool"]))
        if stats["empty_ete"] > config.EMPTY_ETE_MAX and stats["empty_ete"] > int(prev.get("empty_ete", 0)) + config.EMPTY_ETE_JUMP:
            reasons.append("%d heroes without an Eternus+ list (last run %d)" % (stats["empty_ete"], int(prev.get("empty_ete", 0))))
    return not reasons, reasons


def write(out, site_dir, files, keep):
    """Write the whole site into <out>.tmp, then swap it in: the site's own files (relay.html, index.html), the kept files {rel: bytes}
    (the previous generation) and the new files {rel: JSON object}. A failure leaves the old <out> as it was."""
    out = Path(out)
    tmp = out.with_name(out.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    try:
        tmp.mkdir(parents=True)
        if site_dir and Path(site_dir).is_dir():
            for f in sorted(Path(site_dir).iterdir()):
                if f.is_file():
                    shutil.copyfile(f, tmp / f.name)
        for rel, data in keep.items():
            p = tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        for rel, obj in files.items():
            p = tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(shape.dumps(obj).encode("utf-8"))
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if out.exists():
        shutil.rmtree(out)
    os.replace(tmp, out)


def history(lists, day, gen):
    """The daily git snapshot: {day, gen, heroes: {id: [[build id, Eternus+ players, Eternus+ games], ... the top 10]}}; no account
    ids, no names (it keeps a public repository's schedule alive, spec 5.7)."""
    heroes = {}
    for hid in sorted(lists):
        rows = [r for r in lists[hid].get("builds") or () if "ete" in (r.get("use") or {})]
        rows.sort(key=lambda r: (r["use"]["ete"].get("n", 0) or 10 ** 6, -r["use"]["ete"].get("best", 0), -r["id"]))
        if rows:
            heroes[str(hid)] = [[r["id"], r["use"]["ete"].get("p", 0), r["use"]["ete"].get("g", 0)] for r in rows[:10]]
    return {"day": day, "gen": gen, "heroes": heroes}


_NUM = re.compile(r"\d+")


def no_ids(path, ids):
    """The files under path (relative, sorted) holding any of the given account ids as a number or inside a string."""
    want = {str(int(i)) for i in ids}
    hits = []
    root = Path(path)
    if not root.exists():
        return hits
    for p in sorted(root.rglob("*")):
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            if any(tok in want for tok in _NUM.findall(text)):
                hits.append(p.relative_to(root).as_posix())
    return hits
