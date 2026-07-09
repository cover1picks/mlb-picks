"""
config.py
=========
Single source of truth for every tunable in the system. Nothing else in this
project should hard-code a threshold, weight, or dollar amount -- import it
from here so the whole engine can be retuned from one file.

Secrets (API keys) come from environment variables (.env). Copy .env.example
to .env and fill in what you have. Everything works with zero keys in MOCK
mode so you can see the full pipeline run today.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # reads .env if present; does nothing if it's missing

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_STORE_DIR = BASE_DIR / "data_store"
REPORTS_DIR = DATA_STORE_DIR / "reports"
DB_PATH = DATA_STORE_DIR / "betting_engine.db"
MANUAL_INPUTS_DIR = BASE_DIR / "manual_inputs"

DATA_STORE_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
MANUAL_INPUTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Data source modes
# ---------------------------------------------------------------------------
# "mock"  -> synthetic-but-realistic data, zero setup, safe to demo today
# "api"   -> real network calls (needs the matching API key/config below)
ODDS_MODE = os.getenv("ODDS_MODE", "mock")            # mock | api
STATS_MODE = os.getenv("STATS_MODE", "api")           # pybaseball is free & public, so "api" is the sane default

# Public tickets/handle % is NOT available from any free API. sportsbettingdime
# .com and Action Network are websites for humans, not APIs. Pick how you want
# to supply it:
#   "manual" -> you fill in manual_inputs/public_betting_<date>.json each day (default)
#   "mock"   -> synthetic split, for demoing the pipeline only
#   "api"    -> you've wired in a paid feed yourself in data/public_betting_provider.py
PUBLIC_BETTING_MODE = os.getenv("PUBLIC_BETTING_MODE", "manual")  # manual | mock | api

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_API_BOOKMAKER = "fanduel"          # primary book chosen for this build
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"

# ---------------------------------------------------------------------------
# Bankroll & staking (Section: Risk Management)
# ---------------------------------------------------------------------------
UNIT_SIZE_DOLLARS = float(os.getenv("UNIT_SIZE_DOLLARS", "100"))   # $ value of 1 unit
STARTING_BANKROLL = float(os.getenv("STARTING_BANKROLL", "0"))     # 0 = track in units only
FLAT_STAKE_UNITS = 1.0             # non-negotiable: every play is exactly 1 unit

# ---------------------------------------------------------------------------
# Strategy engine thresholds (Section: Core Rules)
# ---------------------------------------------------------------------------
MIN_EDGE = 0.05                     # never recommend below a 5% model-vs-market edge
MAX_PLAYS_PER_DAY = 2               # primary + (optional) second play of equal strength
SECOND_PLAY_TOLERANCE = 0.0         # 2nd play must have edge >= primary edge - tolerance

# Team diversification (Section: Grading Factors -> team diversification)
DIVERSIFICATION_LOOKBACK_DAYS = 3   # don't play the same team 3x running without extra confirmation
DIVERSIFICATION_EXTRA_EDGE = 0.03   # +3 points of required edge on the 3rd+ consecutive day
DIVERSIFICATION_MIN_STRONG_FACTORS = 4  # require at least this many strongly-positive factors too

# Line movement drop rule (Section: Grading Factors -> line movement)
LINE_MOVE_DROP_CENTS = 15           # moneyline drift ("cents") considered "significant"
LINE_MOVE_REQUIRES_SHARP_CONFIRM = True   # only drop if the move is ALSO backed by heavy money on the other side
HEAVY_MONEY_HANDLE_THRESHOLD = 0.65  # handle% on one side above this = "heavy" money

# ---------------------------------------------------------------------------
# HR Prop workflow (Section: HR Prop Workflow) -- runs automatically every day
# ---------------------------------------------------------------------------
HR_PROPS_ENABLED = True
HR_PROP_MIN_SCORE = 70              # 0-100 composite score floor; "only strongest signals"
HR_PROP_MAX_PER_DAY = 5             # show up to the best 4-5 each day, not just one
HR_PROP_ROSTER_LIMIT = 9            # cap batters evaluated per team (perf -- see data/rosters.py)

# ---------------------------------------------------------------------------
# Optional parlay (Section: Output Layer)
# ---------------------------------------------------------------------------
PARLAY_ENABLED = True
PARLAY_MAX_LEGS = 4
PARLAY_MIN_LEGS = 2
# Only ever built from plays that already independently cleared MIN_EDGE;
# gated additionally on a celestial/numerology "green light" (see engine/parlay.py)

# ---------------------------------------------------------------------------
# Grading factor weights (Section: Strategy Engine -> Grading Factors)
# ---------------------------------------------------------------------------
# Each weight is the MAX percentage points a factor can swing the model's win
# probability away from the fair market number, in either direction. They
# intentionally sum to a modest total (0.30) so the model nudges the market
# rather than replacing it -- you have no historical calibration yet (you
# told us to start logging fresh), so start conservative and retune these
# once backtest/grader.py has a few weeks of graded results behind it.
FACTOR_WEIGHTS = {
    "public_sharp_split": 0.07,   # heavily weighted per your rules
    "matchup_pitching": 0.06,
    "advanced_analytics": 0.05,
    "talent_gap": 0.03,
    "situational": 0.03,
    "motivation": 0.03,
    "moon_zodiac": 0.015,
    "numerology": 0.015,
}
assert abs(sum(FACTOR_WEIGHTS.values()) - 0.30) < 1e-9

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
# DAILY_RUN_HOUR/MINUTE is now also the fallback publish time for the cloud
# auto-scheduler on days with no games to anchor to (see auto_gate.py) --
# on a normal game day, the real trigger is "first pitch minus
# AUTO_RUN_LEAD_MINUTES" instead, computed fresh every day from the actual
# schedule (see .github/workflows/daily.yml).
DAILY_RUN_HOUR = int(os.getenv("DAILY_RUN_HOUR", "10"))   # local time, 24h clock
DAILY_RUN_MINUTE = int(os.getenv("DAILY_RUN_MINUTE", "0"))
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")
AUTO_RUN_LEAD_MINUTES = int(os.getenv("AUTO_RUN_LEAD_MINUTES", "60"))  # publish this long before first pitch

# ---------------------------------------------------------------------------
# GitHub Pages publishing (optional) -- see output/publish_github_pages.py
# ---------------------------------------------------------------------------
# Turns "latest.html" into a real phone-reachable link: https://<user>.github.io/<repo>/
GITHUB_PAGES_ENABLED = os.getenv("GITHUB_PAGES_ENABLED", "false").lower() == "true"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")            # fine-grained PAT, "Contents: Read and write" on the repo below
GITHUB_REPO = os.getenv("GITHUB_REPO", "")               # "your-username/your-repo"
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_PAGES_PATH = os.getenv("GITHUB_PAGES_PATH", "index.html")  # path IN the repo Pages serves from

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
MIN_SLATE_SIZE = 3        # if fewer than N games on the slate, trust the numbers less (still allowed, just flagged)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
