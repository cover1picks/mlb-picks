"""
data/standings.py
===================
Team records (wins/losses, run differential, games back, current streak)
from the MLB Stats API standings endpoint. Powers the "talent gap" and
"motivation" grading factors.
"""

import logging
from datetime import datetime

import requests

from data.situational import TEAM_IDS

logger = logging.getLogger(__name__)

STANDINGS_API = "https://statsapi.mlb.com/api/v1/standings"


def get_all_team_records(season=None):
    """Returns dict team_abbr -> {wins, losses, runs_scored, runs_allowed,
    games_back, streak, division_rivals}. Never raises; returns {} on
    failure so callers degrade gracefully (talent/motivation factors just
    go neutral for the day)."""
    season = season or datetime.now().year
    try:
        resp = requests.get(
            STANDINGS_API,
            params={"leagueId": "103,104", "season": season, "standingsTypes": "regularSeason"},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        logger.warning("Standings fetch failed: %s", exc)
        return {}

    id_to_abbr = {v: k for k, v in TEAM_IDS.items()}
    records = {}
    for record_block in payload.get("records", []):
        division_teams = []
        for team_record in record_block.get("teamRecords", []):
            team_id = team_record.get("team", {}).get("id")
            abbr = id_to_abbr.get(team_id)
            if not abbr:
                continue
            division_teams.append(abbr)
            streak_block = team_record.get("streak", {}) or {}
            streak_number = streak_block.get("streakNumber", 0) or 0
            streak = streak_number if streak_block.get("streakType") == "wins" else -streak_number
            records[abbr] = {
                "wins": team_record.get("wins"),
                "losses": team_record.get("losses"),
                "runs_scored": team_record.get("runsScored"),
                "runs_allowed": team_record.get("runsAllowed"),
                "games_back": _parse_games_back(team_record.get("gamesBack")),
                "streak": streak,
            }
        for abbr in division_teams:
            if abbr in records:
                records[abbr]["division_rivals"] = [t for t in division_teams if t != abbr]
    return records


def _parse_games_back(gb):
    if gb in (None, "-", ""):
        return 0.0
    try:
        return float(gb)
    except ValueError:
        return 0.0
