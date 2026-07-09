"""
data/situational.py
====================
Situational factors: injuries (manual override), rest/travel fatigue (MLB
Stats API recent schedule), and park factors (static table). These feed the
"situational" grading factor and the HR prop park+motivation overlay.

TEAM_IDS here is the canonical abbr -> MLB Stats API numeric team id map,
reused by data/standings.py and data/rosters.py.
"""

import json
import logging
from datetime import datetime, timedelta

import requests

import config
from data.park_factors import park_factor_for

logger = logging.getLogger(__name__)

MLB_STATS_API = "https://statsapi.mlb.com/api/v1/schedule"

TEAM_IDS = {
    "ARI": 109, "ATL": 144, "BAL": 110, "BOS": 111, "CHC": 112, "CWS": 145,
    "CIN": 113, "CLE": 114, "COL": 115, "DET": 116, "HOU": 117, "KC": 118,
    "LAA": 108, "LAD": 119, "MIA": 146, "MIL": 158, "MIN": 142, "NYM": 121,
    "NYY": 147, "OAK": 133, "PHI": 143, "PIT": 134, "SD": 135, "SEA": 136,
    "SF": 137, "STL": 138, "TB": 139, "TEX": 140, "TOR": 141, "WSH": 120,
}


def get_injury_notes(team_abbr, date_str):
    """Reads manual_inputs/injuries_<date>.json (auto-scaffolded empty by
    ensure_injury_template). Format:
    {"NYY": [{"player":"...", "status":"OUT", "impact":"high"}], ...}
    Returns a list of dicts, [] if none on file for this team."""
    path = config.MANUAL_INPUTS_DIR / f"injuries_{date_str}.json"
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get(team_abbr, [])
    except Exception as exc:
        logger.warning("Couldn't read injuries file %s: %s", path, exc)
        return []


def ensure_injury_template(date_str):
    path = config.MANUAL_INPUTS_DIR / f"injuries_{date_str}.json"
    if path.exists():
        return
    config.MANUAL_INPUTS_DIR.mkdir(exist_ok=True)
    with open(path, "w") as f:
        json.dump({"_note": "team_abbr -> [{player, status: OUT/QUESTIONABLE, impact: high/medium/low}]"}, f, indent=2)


def get_rest_days(team_abbr, before_date_str, lookback_days=6):
    """Best-effort: how many days of rest has this team had, and how many of
    the last `lookback_days` did they play? Returns a neutral/unknown dict on
    any network failure rather than raising."""
    try:
        before = datetime.strptime(before_date_str, "%Y-%m-%d")
        start = (before - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        end = (before - timedelta(days=1)).strftime("%Y-%m-%d")
        resp = requests.get(
            MLB_STATS_API,
            params={"sportId": 1, "startDate": start, "endDate": end, "teamId": TEAM_IDS.get(team_abbr)},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        game_dates = sorted(d["date"] for d in payload.get("dates", []) if d.get("games"))
        games_played = len(game_dates)
        rest_days = (before - datetime.strptime(game_dates[-1], "%Y-%m-%d")).days if game_dates else None
        return {"games_last_n_days": games_played, "rest_days": rest_days, "data_quality": "ok"}
    except Exception as exc:
        logger.debug("rest-day lookup failed for %s: %s", team_abbr, exc)
        return {"games_last_n_days": None, "rest_days": None, "data_quality": "degraded"}


def park_and_situational_summary(home_team, away_team, date_str):
    """Bundles everything the GAME-level situational grading factor needs."""
    runs_pf, hr_pf = park_factor_for(home_team)
    return {
        "park_runs_factor": runs_pf,
        "park_hr_factor": hr_pf,
        "home_injuries": get_injury_notes(home_team, date_str),
        "away_injuries": get_injury_notes(away_team, date_str),
        "home_rest": get_rest_days(home_team, date_str),
        "away_rest": get_rest_days(away_team, date_str),
    }


def team_situational_summary(team_abbr, date_str):
    """Single-team bundle, used by the HR prop workflow's park+motivation overlay."""
    runs_pf, hr_pf = park_factor_for(team_abbr)
    rest = get_rest_days(team_abbr, date_str)
    return {
        "park_runs_factor": runs_pf,
        "park_hr_factor": hr_pf,
        "injuries": get_injury_notes(team_abbr, date_str),
        "rest_days": rest.get("rest_days"),
    }
