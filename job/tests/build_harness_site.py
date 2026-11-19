"""Write tools/harness/fixtures/feed_site/ from the synthetic World (plan Task 4): the files a deploy publishes under data/, for the
in-game harness suites (run_feed_relay.js, run_builds_feed.js). Made-up data only; the relay page itself is read from feed/site.

  python -I feed/job/tests/build_harness_site.py

test_run.Fixture.test_harness_fixture_current fails until this is re-run after a change of the published shapes."""
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOB = HERE.parent
REPO = JOB.parents[1]
if str(JOB) not in sys.path:
    sys.path.insert(0, str(JOB))

import run  # noqa: E402
import state  # noqa: E402
from tests.world import World  # noqa: E402

FIXED_NOW = 1794916800    # 2026-11-17T12:00:00Z
DEST = REPO / "tools" / "harness" / "fixtures" / "feed_site"


def build(dest=DEST):
    dest = Path(dest)
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "site").mkdir()
        st = state.State(d / "state").load()
        rc = run.run(World(FIXED_NOW, fillers=0), st, d / "out", FIXED_NOW, site_url="", history_dir=None, log=lambda m: None,
                     validate=False, site_dir=d / "site")
        if rc != 0:
            raise SystemExit("the fixture run failed (%d)" % rc)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(d / "out", dest)
    return dest


if __name__ == "__main__":
    print("wrote", build())
