"""
data/schedule_provider.py
==========================
Today's MLB schedule from the MLB Stats API -- free, public, no API key.
This is the one external data source in the whole project you never need to
configure: it's what tells the rest of the pipeline which games exist today.
"""

import logging
import requests

from engine.models import Game, ProbablePitcher
from data.teams import normalize_team

logger = logging.getLogger(__name__)

MLB_STATS_API = "https://statsapi.mlb.com/api/v1/schedule"


def get_todays_games(date_str):
    """date_str: 'YYYY-MM-DD'. Returns a list of engine.models.Game.
    Never raises -- on any network/parsing problem it logs and returns []
    so the rest of the daily run can still produce a (empty-slate) report
    instead of crashing."""
    params = {
        "sportId": 1,
        "date": date_str,
        "hydrate": "probablePitcher,team,linescore",
    }
    try:
        resp = requests.get(MLB_STATS_API, params=params, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        logger.error("Failed to fetch MLB schedule for %s: %s", date_str, exc)
        return []

    games = []
    for date_block in payload.get("dates", []):
        for g in date_block.get("games", []):
            try:
                games.append(_parse_game(g, date_str))
            except Exception as exc:
                logger.warning("Skipping one game we couldn't parse: %s", exc)
    return games


def _parse_game(g, date_str):
    teams = g["teams"]
    home = teams["home"]["team"]["name"]
    away = teams["away"]["team"]["name"]

    home_pitcher = _parse_pitcher(teams["home"].get("probablePitcher"))
    away_pitcher = _parse_pitcher(teams["away"].get("probablePitcher"))

    return Game(
        game_id=str(g["gamePk"]),
        date=date_str,
        home_team=normalize_team(home),
        away_team=normalize_team(away),
        game_time_utc=g.get("gameDate"),
        home_pitcher=home_pitcher,
        away_pitcher=away_pitcher,
    )


def _parse_pitcher(p):
    if not p:
        return None
    return ProbablePitcher(name=p.get("fullName", "TBD"), player_id=p.get("id"))
