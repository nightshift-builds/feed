"""A synthetic deadlock-api for the job's tests and the harness fixture site (plan Task 4).

Every id and name here is made up (account ids from 9,000,001; build ids 400,000+): nothing was recorded from the API, so no real
player's name or account id ever lands in git. Answers are plain dicts shaped like the live answers (field names and types only).
World(now) implements the job's source interface (see run.Live); `calls` records each call."""
import api as api_mod

DAY = 86_400

# real class names from sheets/items.json (so the card finds their icons), one the card does not know and one the shop dropped
ITEMS = ["upgrade_close_range", "upgrade_clip_size", "upgrade_headshot_booster", "upgrade_high_velocity_mag", "upgrade_non_player_bonus",
         "upgrade_rapid_rounds", "upgrade_medic_bullets", "upgrade_active_reload", "upgrade_fleetfoot_boots", "upgrade_intensifying_clip",
         "upgrade_kinetic_sash", "upgrade_long_range", "upgrade_melee_charge", "upgrade_crackshot", "upgrade_pristine_emblem",
         "upgrade_rechargingbullets", "upgrade_slowing_bullets", "upgrade_split_shot", "upgrade_blitz_bullets", "upgrade_titan_round",
         "upgrade_berserker", "upgrade_burst_fire", "upgrade_express_shot", "upgrade_headhunter", "upgrade_hollow_point_rounds",
         "upgrade_sharpshooter", "upgrade_toxic_bullets", "upgrade_glass_cannon", "upgrade_ricochet", "upgrade_infinite_rounds",
         "upgrade_health", "upgrade_endurance", "upgrade_improved_stamina", "upgrade_grit", "upgrade_future_thing", "upgrade_retired_relic"]
ITEM_ID = {c: 50_000 + i for i, c in enumerate(ITEMS)}
UNSHOPABLE = "upgrade_retired_relic"
UNKNOWN_ITEM_ID = 59_999   # in some builds, missing from the assets (dropped by the job)

MAIN = [(1, "inferno"), (6, "atlas"), (13, "haze"), (18, "krill"), (52, "mirage")]
POOL0, N_POOL = 9_000_001, 1600
LOW0 = 9_100_001          # below Ascendant: never in the pool
OUT0 = 9_200_001          # authors who are not ranked players
SITE_AUTHOR = 9_300_001
SYL = ["Ka", "Zo", "Mi", "Ru", "Te", "Va", "Ne", "Lo"]
SERVER = {"eu": ("eu_north", "eu_west", "dpkt-frankfurt", "london"), "na": ("us_east", "us_southeast", "us_north_central"),
          "asia": ("hong_kong",), "sa": ("south_america",), "oce": ("australia",)}


def chip_of(i):
    k = i % 20
    return "eu" if k < 8 else "na" if k < 15 else "asia" if k < 17 else "sa" if k == 17 else "oce" if k == 18 else None


class Rng:
    def __init__(self, seed):
        self.x = (seed * 2654435761 + 12345) % 2 ** 32

    def next(self):
        self.x = (1103515245 * self.x + 12345) % 2 ** 31
        return self.x

    def n(self, k):
        return self.next() % k


def acct(i):
    return POOL0 + i


class World:
    def __init__(self, now, fillers=30, pool_share=1.0, fail_rows=(), bump=None, sb_fail_wide=False, base=1794916800, s2_age=12,
                 fail_popular=False, fail_names=False, fail_details=False, odd_names=False):
        self.now = now
        self.base = base      # every time of the made-up data hangs on this fixed moment, so a later run sees the same world
        self.calls = []
        self.fail_rows = set(fail_rows)
        self.sb_fail_wide = sb_fail_wide     # a scoreboard over more than 100 days answers 504 (deadlock-api's time limit)
        self.fail_popular, self.fail_names, self.fail_details = fail_popular, fail_names, fail_details   # that source answers 504
        self.odd_names = odd_names           # some Steam names carry Panorama-special text (a leading '#', markup, {s:..}, bidi)
        self.n_pool = int(N_POOL * pool_share)
        self.heroes = list(MAIN) + [(200 + i, "filler%02d" % i) for i in range(fillers)]
        self.big_patch = base - 49 * DAY
        self.s2 = base - s2_age * DAY   # Season 2 started this many days before base (28-day handover)
        self.builds = {}      # bid -> full hero_build dict
        self.rows = {}        # hero -> [rows]
        self.protected = {acct(42)}
        self.site = {}        # relative path -> bytes (the live site, for the previous generation)
        self._make()
        if bump:              # (bid, seconds after now): a new version of that build
            bid, dt = bump
            b = self.builds[bid]
            b["version"] += 1
            b["last_updated_timestamp"] = now + dt

    # ---- the made-up world
    def badge(self, i):
        return 116 if i < 30 else 111 + i % 5 if i < 220 else 101 + i % 10

    def _build(self, hero, key, bid, author, k, name=None, upd=None, lang=0, items=None, dev=False, ver=None, cats=None):
        r = Rng(bid)
        its = items or [ITEMS[(k * 5 + j * 3) % 34] for j in range(12)]
        names = cats or ["#Citadel_HeroBuilds_EarlyGame", "Mid", "Late game", ("flex stuff", "CORE", "green spike 4800 800s maybe")[k % 3]]
        mods = []
        for c, cname in enumerate(names):
            part = its[c * 3:(c + 1) * 3] if c < 3 else its[9:]
            ms = [{"ability_id": ITEM_ID[x], "annotation": ("buy first" if j == 0 and c == 0 else "<b>rush</b> it" if j == 1 and c == 1 else None)}
                  for j, x in enumerate(part)]
            if c == 3 and k % 4 == 0:
                ms.append({"ability_id": UNKNOWN_ITEM_ID, "annotation": None})
            mods.append({"name": cname, "mods": ms})
        changes = [{"ability_id": hero * 100 + s, "currency_type": 2, "delta": -1} for s in (1, 2, 3, 4)]
        seen = {}
        for j in range(12 + (k % 3) * 8):
            s = 1 + (r.n(4) if j >= 4 else j)
            seen[s] = seen.get(s, 0) + 1
            changes.append({"ability_id": hero * 100 + s, "currency_type": 1, "delta": (-1, -2, -5)[min(seen[s], 3) - 1]})
        self.builds[bid] = {
            "hero_build_id": bid, "hero_id": hero, "author_account_id": author,
            "name": name if name is not None else "%s %s %d" % (key.title(), ("spirit", "gun", "tank", "hybrid")[k % 4], k),
            "description": "Made-up build %d for tests. Rush the first item." % k, "language": lang,
            "version": ver if ver is not None else 1 + k % 7,
            "last_updated_timestamp": upd if upd is not None else self.base - (k * 3 % 80) * DAY - 3600,
            "development_build": dev,
            "details": {"mod_categories": mods, "ability_order": {"currency_changes": changes}},
        }

    def _games(self, hero, a, bid, n, days_ago=0.5, step=0.6, won_every=2):
        for j in range(n):
            self.rows[hero].append({"account_id": a, "hero_build_id": bid, "won": j % won_every == 0,
                                    "start_time": int(self.base - (days_ago + j * step) * DAY)})

    def _make(self):
        for hero, key in self.heroes:
            self.rows[hero] = []
            main = hero < 200
            nb = 36 if main else 3
            ids = []
            for k in range(nb):
                bid = 400_000 + hero * 1000 + k
                pick = k % 4
                author = acct((k * 37 + hero) % 220) if pick == 0 else acct(220 + (k * 53 + hero) % 1000) if pick == 1 else \
                    OUT0 + k if pick == 2 else acct((k * 11 + hero * 7) % 400)
                if not main:
                    author = acct(50 + k + hero % 7)
                self._build(hero, key, bid, author, k, upd=self.base - (k % 30) * DAY - 3600 if not main else None)
                ids.append(bid)
            if hero == 200:                                      # outside the 90-day seed: found only by an id lookup
                self._build(hero, key, 600_001, acct(57), 9, name="Old but run", upd=self.base - 120 * DAY)
                for i in range(50, 58):
                    self._games(hero, acct(i), 600_001, 2)
            players = [i for i in range(self.n_pool) if (i * 7 + hero) % 5 == 0] if main else [50 + j for j in range(12)]
            if hero == 52:                                       # Mirage: only three Eternus+ players, each on one build
                players = [i for i in players if i >= 220 and not 1500 <= i < 1550]
                for j, i in enumerate((0, 1, 2)):
                    self._games(hero, acct(i), ids[j], 3)
            for i in players:
                r = Rng(i * 131 + hero)
                g = 1 + (i + hero) % 6
                mainb = ids[(i * 3 + hero) % (30 if hero == 6 else 20 if main else nb)]
                for j in range(g):
                    roll = r.n(10)
                    bid = None if roll < 3 else (500 + r.n(400)) if roll == 3 else 1016 if roll == 4 and hero == 13 else \
                        mainb if roll < 8 else ids[r.n(len(ids))]
                    self.rows[hero].append({"account_id": acct(i), "hero_build_id": bid, "won": r.n(2) == 0,
                                            "start_time": int(self.base - (0.3 + r.n(130) / 10.0) * DAY)})
            for i in range(300):                                 # players below the pool play too: never counted
                if (i + hero) % 9 == 0:
                    self.rows[hero].append({"account_id": LOW0 + i, "hero_build_id": ids[0], "won": True, "start_time": self.base - DAY})
        self._haze()

    def _haze(self):
        h, key = 13, "haze"
        fast = ["upgrade_close_range", "upgrade_clip_size", "upgrade_headshot_booster", "upgrade_rapid_rounds", "upgrade_medic_bullets",
                "upgrade_active_reload", "upgrade_split_shot", "upgrade_blitz_bullets", "upgrade_titan_round", "upgrade_ricochet",
                "upgrade_glass_cannon", "upgrade_express_shot"]
        b = self._build
        b(h, key, 413901, SITE_AUTHOR, 1, name="Tracklock auto [tracklock.gg]", upd=self.base - DAY, ver=1860)
        b(h, key, 413902, acct(40), 2, name="Fast Haze", items=fast, upd=self.base - 3 * DAY)
        b(h, key, 413903, acct(600), 3, name="Copy of Fast Haze", items=fast, upd=self.base - 2 * DAY)
        for k in range(5):
            b(h, key, 413910 + k, acct(41), 10 + k, name="Author five %d" % k, upd=self.base - (k + 1) * DAY)
        b(h, key, 413920, acct(43), 20, name="Before the patch", upd=self.big_patch - 10 * DAY)
        relic = [ITEMS[j] for j in range(11)] + [UNSHOPABLE]
        b(h, key, 413921, acct(44), 21, name="Relic build", items=relic, upd=self.base - 4 * DAY)
        b(h, key, 413922, acct(45), 22, name="Сборка Хейз", lang=8, upd=self.base - 5 * DAY)
        b(h, key, 413923, acct(46), 23, name="#Citadel_HeroBuilds_EarlyGame", upd=self.base - 6 * DAY)
        b(h, key, 413924, acct(47), 24, name="<b>Bold</b> line", upd=self.base - 6 * DAY)
        b(h, key, 413925, acct(48), 25, name="{s:x} Curly", upd=self.base - 6 * DAY)
        b(h, key, 413926, acct(42), 26, name="Quiet author", upd=self.base - 7 * DAY)
        b(h, key, 413927, acct(49), 27, name="Dev build", dev=True, upd=self.base - DAY)
        g = self._games
        for i in range(100, 140):
            g(h, acct(i), 413901, 3)
        for i in range(140, 150):
            g(h, acct(i), 413902, 3)
        for i in range(150, 156):
            g(h, acct(i), 413903, 3)
        for k in range(5):
            for i in range(160 + k * 12, 172 + k * 12):
                g(h, acct(i), 413910 + k, 4)
        for i in range(30, 35):
            g(h, acct(i), 413920, 2, days_ago=9)
        for i in range(35, 40):
            g(h, acct(i), 413921, 2)
            g(h, acct(i), 413922, 1)
            g(h, acct(i), 413923, 1)
            g(h, acct(i), 413924, 1)
            g(h, acct(i), 413925, 1)
            g(h, acct(i), 413926, 1)
            g(h, acct(i), 413927, 2)

    # ---- helpers for the tests
    def account_ids(self):
        out = {acct(i) for i in range(N_POOL)} | {LOW0 + i for i in range(300)} | {SITE_AUTHOR}
        out |= {b["author_account_id"] for b in self.builds.values()}
        return out

    ODD = ("#Citadel_Foo", "<b>bold</b> one", "{s:x} curly", "ok‮evil", "# #tok", "##")

    def name_of(self, a):
        i = a - POOL0
        if self.odd_names and i % 5 == 0:
            return self.ODD[(i // 5) % len(self.ODD)]
        return "%s%s %d" % (SYL[i % 8], SYL[(i // 8) % 8].lower(), i % 97)

    def _call(self, name, *args):
        self.calls.append((name,) + args)

    @property
    def count(self):
        return len(self.calls)

    # ---- the source interface (run.Live has the same methods over HTTP)
    def seasons(self):
        self._call("seasons")
        return [{"name": "Beta Season 1", "intervals": [{"interval": 1, "start_timestamp": self.base - 200 * DAY, "end_timestamp": self.s2}]},
                {"name": "Beta Season 2", "intervals": [{"interval": 2, "start_timestamp": self.s2, "end_timestamp": self.base + 120 * DAY}]}]

    def scoreboard(self, t0, t1):
        self._call("scoreboard", t0, t1)
        if self.sb_fail_wide and t1 - t0 > 100 * DAY:
            raise api_mod.ApiError("http 504", 504)
        if t1 <= self.s2:     # last season's finals: 50 players were Eternus then
            return [(acct(i), 112 if 1500 <= i < 1550 else self.badge(i), 80000 - i) for i in range(self.n_pool)]
        out = [(acct(i), self.badge(i) if not 1500 <= i < 1550 else 101, 70000 - i * 3) for i in range(self.n_pool)]
        return out + [(LOW0 + i, 95, 30000 - i) for i in range(300)]

    def hero_rows(self, hero, ids, since):
        self._call("hero_rows", hero)
        if hero in self.fail_rows:
            raise api_mod.ApiError("http 504", 504)
        ids = set(ids)
        return [r for r in self.rows.get(hero, ()) if r["account_id"] in ids and r["start_time"] >= since]

    def popular(self, since, until):
        self._call("popular")
        if self.fail_popular:
            raise api_mod.ApiError("http 504", 504)
        out = []
        for bid, b in sorted(self.builds.items()):
            if b["development_build"]:
                continue
            p = 900 if bid == 413901 else 20 + bid % 50
            out.append({"hero_id": b["hero_id"], "hero_build_id": bid, "players": p, "matches": p * 3, "wins": p * 3 // 2})
        return out

    def _slim(self, b):
        return {k: b[k] for k in ("hero_build_id", "hero_id", "author_account_id", "name", "description", "language", "version",
                                  "last_updated_timestamp", "development_build")}

    def meta_seed(self, hero, since):
        self._call("meta_seed", hero)
        import sources
        return {bid: sources.slim(self._slim(b)) for bid, b in self.builds.items() if b["hero_id"] == hero and b["last_updated_timestamp"] >= since}

    def meta_since(self, since):
        self._call("meta_since", since)
        import sources
        return {bid: sources.slim(self._slim(b)) for bid, b in self.builds.items() if b["last_updated_timestamp"] >= since}

    def details(self, pairs, failed=None):
        pairs = list(pairs)
        self._call("details", len(pairs))
        if self.fail_details:              # every batch errors: the pairs are reported failed, not missing
            if failed is not None:
                failed.extend(pairs)
            return {}
        out = {}
        for h, bid in pairs:
            b = self.builds.get(int(bid))
            if b and b["hero_id"] == int(h):
                out[int(bid)] = b
        return out

    def names(self, ids):
        self._call("names", len(list(ids)))
        if self.fail_names:
            raise api_mod.ApiError("http 504", 504)
        return {a: self.name_of(a) for a in ids if POOL0 <= a < POOL0 + N_POOL and a not in self.protected}

    def regions(self, ids):
        self._call("regions", len(list(ids)))
        import clean
        out = {}
        for a in ids:
            if POOL0 <= a < POOL0 + N_POOL:
                c = chip_of(a - POOL0)
                out[a] = clean.region_of(SERVER[c][(a - POOL0) % len(SERVER[c])]) if c else None
        return out

    def assets(self):
        self._call("assets")
        heroes = {h: {"key": k, "slots": {h * 100 + s: s for s in (1, 2, 3, 4)}} for h, k in self.heroes}
        up = {ITEM_ID[c]: [c, c != UNSHOPABLE] for c in ITEMS}
        ab = {h * 100 + s: "ab_%s_%d" % (k, s) for h, k in self.heroes for s in (1, 2, 3, 4)}
        return {"heroes": heroes, "items_up": up, "items_ab": ab, "big_patch": self.big_patch}

    def site_get(self, rel):
        self._call("site_get", rel)
        return self.site.get(rel)
