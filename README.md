# Nightshift HUD builds feed

The data behind the Builds card's High rank and Popular lists: for every hero, the published builds high-rank players run (their
games of the last 14 days) and write (updated in the last 90 days). Design: `docs/superpowers/specs/2026-11-17-builds-feed-design.md`
in the mod's repository. This folder is the future organization repository: its root becomes that repository's root.

## What runs where

- `job/` (Python 3.12: the standard library and pyarrow, for the data lake) runs every hour in GitHub Actions (`.github/workflows/feed.yml`), started at :23 by an
  outside scheduler (cron-job.org) through the API's `workflow_dispatch`, also by hand. The scheduler holds a fine-grained token
  (this repository, Actions: read and write) that expires after a year: renew it there. It reads deadlock-api (api.deadlock-api.com)
  only, and writes the static site `_site/`:
  - `relay.html`, the page the mod loads in a hidden in-game browser panel;
  - `data/index.json`: the generation, the season, the circles' sizes, `heroes` {key: id};
  - `data/<gen>/<hero id>.json`: a hero's list;
  - `data/<gen>/popular/<hero id>.json`: its Popular list;
  - `data/b/<build id>_<version>.json`: a build's details.

  Each deploy keeps the previous generation's lists too.
- The job's private state (build metadata, player names and regions, the pool's games of the last 14 days, the last run's lists
  and stats) lives in the Actions cache (`state/`). It is never published: it holds account ids.
- The pool's games come from deadlock-api's data lake (data.deadlock-api.com: match_player as hourly parquet files), read with pyarrow
  over HTTP range requests: only the column chunks asked for travel (a 4.7 GB file gives 25 MB), and the lake has no request or read budget. GraphQL is charged by the data it
  reads since 19 Nov (10 GB an hour per IP), which the 14-day games query could not stay under. The job keeps the pool's games in
  its state with the lake's watermark and reads only the files that came since the last run (a few MB); the first fill reads the
  whole window once (20 Nov: about 160 files, 470 MB, carried on by the next run if it is cut short). The lake runs an hour or two
  behind the games. Build metadata and details still come from GraphQL (small queries); the run's last log line says how much it read.
- Once a day the job writes `data/history/YYYY-MM-DD.json` (build ids and counts, no names) and the workflow commits it.
- A run that looks broken deploys nothing, and the last good deploy stays live:
  - the high-rank pool falls under half of the last run's;
  - or many more heroes lose their Eternus+ list than last time;
  - or, on the first run, fewer than 1,000 players or fewer than 30 heroes with lists.

## Who counts

- Circles go by each player's own rank, never a match average: Ascendant+ (badge 101+), Eternus+ (111+), and Top 100 (the 100 best
  Eternus+ players of a region; outside NA and EU only those at the level of NA's and EU's 100th).
- For 28 days into a season, a player's standing is the better of this season's and last season's final badge.
- The list order (`Best`):
  - the weighted high-rank players who run the build;
  - plus the author's own rank;
  - minus staleness (not updated since the last big patch and not played for a week) and items gone from the shop.
- At most 3 builds of one author in the first 20 places.
- Builds a statistics site generated (Tracklock and the like: a site marker by an author outside the pool) never enter High rank; they
  show in Popular with a "Site" tag.

## Request budget

The first run makes about 450 requests in about 6 minutes: the metadata seed and every listed build's details. Later runs make about
60-100 requests in 1-3 minutes, at most 2 requests a second, with retries on 429/503. Regions are filled 1,000 accounts a run. The
region chips appear once half the pool has a region, a few hours after the first deploy.

## Publishing (the user's steps)

1. Create a free GitHub organization and name it; it becomes `<org>.github.io`. Do not use your own account: every github.io project
   page of one owner shares the settings bridge's origin and its storage.
2. Create a public repository in it (for example `feed`), copy this folder's contents to its root, and push.
3. Settings > Pages > Source: GitHub Actions. Optional: Settings > Secrets > `DEADLOCK_API_KEY` (a deadlock-api key gets its own rate
   bucket).
4. Run the workflow once by hand (Actions > feed > Run workflow). The site is then `https://<org>.github.io/<repo>/`.
5. In the mod, `NS.FEED_URL` in `src/js/features/hero_builds_feed.js` becomes `https://<org>.github.io/<repo>/relay.html`. Then rebuild
   the baked list: `python scripts/feed_snapshot.py --from-url https://<org>.github.io/<repo>/`, then `python scripts/generate.py`.
6. Before a public release:
   - move the site to a domain you own (the URL is compiled into the mod). A `.com` at Cloudflare Registrar costs about $11 a year.
   - check that the site loads from Russia and Eastern Europe.
   - pin the workflow's actions to the majors current then.

## Notes

- Coverage: deadlock-api's records carry the selected build for about half of the high-rank games. Better Builds adds live reads of
  matches, so its player counts run higher. The top builds largely agree:
  - the first live run, 2026-11-17, against Better Builds' lists of that morning: Eternus+ top-10 overlap 9/10 (Abrams), 7/10
    (Infernus), 5/10 (Mo & Krill);
  - that was before Better Builds moved to Season 2 ranks.
- The job sends a User-Agent naming the project and the site.
- Tests: `python -I -m unittest discover -s job/tests -t job` (synthetic data only; no real player names or ids are ever stored in this
  repository).
