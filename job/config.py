"""Every constant of the builds feed job (spec docs/superpowers/specs/2026-11-17-builds-feed-design.md, section 5).

Tunables are pinned by tests (feed/job/tests). Times are in seconds.
"""

API = "https://api.deadlock-api.com"

# windows (5.1-5.4)
WINDOW_DAYS = 14          # runs counted: a player's Normal games in the last 14 days
RECENT_DAYS = 7           # recent(r): the runner's last game on the build within 7 days
AUTHOR_DAYS = 90          # authored builds count while updated within 90 days
HANDOVER_DAYS = 28        # a new season: the better of this season's and last season's final badge for 28 days

# circles (5.2): badge = tier * 10 + subtier
BADGE_ASC = 101           # Ascendant I
BADGE_ETE = 111           # Eternus I
TOP_REGION = 100          # Top 100 per region ...
TOP_GLOBAL = 300          # ... else the global top 300
REGIONS_KNOWN_SHARE = 0.5  # regions count once half of the pool has one

CIRCLES = ("top", "ete", "asc")           # highest first
CIRCLE_RANK = {"top": 3, "ete": 2, "asc": 1}
CHIPS = ("na", "eu", "asia", "sa", "oce")

# score (5.4)
W = {"top": 2.0, "ete": 1.5, "asc": 1.0}   # runner weight by the runner's highest circle
MAIN_OTHER = 0.5          # the build is not the runner's most-played build on this hero
RECENT_OLD = 0.5          # the runner's last game on it is older than RECENT_DAYS

# lists (5.3)
CAP = 25                  # builds per circle list
AUTHOR_CAP = 3            # at most 3 builds of one author ...
AUTHOR_CAP_TOP = 20       # ... within the first 20 places
PRELIM = 40               # details are fetched for the preliminary top 40 of each circle (plan ruling 5)
POPULAR_CAP = 25

# size guard (5.7), bytes of compact JSON
LIST_MAX = 60_000
DETAIL_MAX = 16_000

# text (6.2)
NAME_MAX = 40
PLAYER_NAME_MAX = 32       # an author's or runner's Steam name
DESC_MAX = 300
NOTE_MAX = 120            # an item annotation
LABEL_MAX = 24            # a category name used as a phase label

# requests (5.6)
PACE = 0.5                # at most 2 requests a second
TRIES = 4
RETRY_AFTER_MAX = 60
TIMEOUT = 60

# job state (5.7)
NAME_TTL = 86_400
NAME_KEEP = 7 * 86_400    # a name older than a day is asked again; kept a week as the fallback of a failed refresh
REGION_TTL = 7 * 86_400   # plan ruling 2: about 26 KB per account, so a 7-day cache filled 1000 accounts a run
REGION_BATCH = 1000
SEED_MAX_AGE = 7 * 86_400
ASSETS_TTL = 86_400

# validation (5.7, plan ruling 1)
FIRST_POOL_MIN = 1000
FIRST_HEROES_MIN = 30
EMPTY_ETE_MAX = 5
EMPTY_ETE_JUMP = 2
HEAL_RUNS = 6             # this many failing runs in a row at one steady level are taken as the new level (deployed)
HEAL_POOL = 0.1           # steady: the pool within 10 % of the streak's first failing run, empty Eternus+ heroes within EMPTY_ETE_JUMP

# site builds (5.5): a name or description with one of these words, by an author outside the Ascendant+ pool
SITE_MARKERS = ("tracklock", "lockbuilds", "mobalytics", "statlocker", "deadlocked", "deadlocklabs", "deadlock labs",
                "deadlock-labs", "deadlockbuilds")
SITE_ACCOUNTS = ()        # site accounts kept by hand (account ids; never published)
