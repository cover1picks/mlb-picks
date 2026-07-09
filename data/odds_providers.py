"""
data/odds_providers.py
=======================
Moneyline/spread/total odds. Two implementations behind one interface:

- MockOddsProvider   : deterministic-per-day synthetic odds, zero setup.
- TheOddsApiProvider : real odds from https://the-odds-api.com, FanDuel book
  (your chosen sportsbook). Needs ODDS_API_KEY in .env.

config.ODDS_MODE picks which one get_odds_provider() hands back. Every
network path falls back to mock data on failure so a bad API response never
crashes the daily run -- it just degrades to synthetic odds for that game
(and logs a warning).
"""

import logging
import random
from datetime import datetime, timezone

import requests

import config
from engine.models import MoneylineOdds
from data.teams import normalize_team

logger = logging.getLogger(__name__)


class OddsProvider:
    def get_odds(self, games):
        """games: list[Game]. Returns dict game_id -> MoneylineOdds (latest)."""
        raise NotImplementedError


class MockOddsProvider(OddsProvider):
    """Deterministic-per-game-per-day synthetic odds so the whole pipeline is
    runnable with zero setup. Odds drift slightly within the same day (seeded
    by the hour) so the line-movement drop rule has something to see when you
    run the tool more than once on the same slate."""

    def get_odds(self, games):
        out = {}
        now = datetime.now(timezone.utc)
        for game in games:
            seed = f"{game.game_id}-{now:%Y-%m-%d}"
            rng = random.Random(seed)
            favorite_strength = rng.uniform(0.08, 0.35)
            home_is_favorite = rng.random() > 0.45
            drift = (now.hour - 12) * rng.uniform(-1.5, 1.5)

            if home_is_favorite:
                home_ml = -_prob_to_american(0.5 + favorite_strength) + drift
                away_ml = _prob_to_american(0.5 - favorite_strength) + drift
            else:
                away_ml = -_prob_to_american(0.5 + favorite_strength) + drift
                home_ml = _prob_to_american(0.5 - favorite_strength) + drift

            out[game.game_id] = MoneylineOdds(
                book="mock",
                home_ml=int(home_ml),
                away_ml=int(away_ml),
                captured_at=now.isoformat(),
                total=round(rng.uniform(7.5, 9.5) * 2) / 2,
            )
        return out


class TheOddsApiProvider(OddsProvider):
    """Real odds via The Odds API, FanDuel bookmaker, moneyline+spread+total."""

    def __init__(self, api_key=None, bookmaker=None):
        self.api_key = api_key or config.ODDS_API_KEY
        self.bookmaker = bookmaker or config.ODDS_API_BOOKMAKER

    def get_odds(self, games):
        if not self.api_key:
            logger.warning("ODDS_API_KEY missing -- falling back to mock odds for this run.")
            return MockOddsProvider().get_odds(games)

        url = f"{config.ODDS_API_BASE_URL}/sports/baseball_mlb/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "bookmakers": self.bookmaker,
            "oddsFormat": "american",
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.error("The Odds API request failed (%s) -- falling back to mock odds.", exc)
            return MockOddsProvider().get_odds(games)

        by_teams = {}
        for event in payload:
            home = normalize_team(event.get("home_team", ""))
            away = normalize_team(event.get("away_team", ""))
            by_teams[(home, away)] = event

        out = {}
        now = datetime.now(timezone.utc).isoformat()
        for game in games:
            event = by_teams.get((game.home_team, game.away_team))
            if not event:
                logger.warning("No odds found for %s @ %s -- using mock for this game only.",
                               game.away_team, game.home_team)
                out[game.game_id] = MockOddsProvider().get_odds([game])[game.game_id]
                continue
            out[game.game_id] = _parse_odds_event(event, self.bookmaker, game, now)
        return out


def _parse_odds_event(event, bookmaker, game, captured_at):
    home_ml = away_ml = None
    home_spread = away_spread = None
    total = None
    for bm in event.get("bookmakers", []):
        if bm.get("key") != bookmaker:
            continue
        for market in bm.get("markets", []):
            if market["key"] == "h2h":
                for outcome in market["outcomes"]:
                    if normalize_team(outcome["name"]) == game.home_team:
                        home_ml = outcome["price"]
                    elif normalize_team(outcome["name"]) == game.away_team:
                        away_ml = outcome["price"]
            elif market["key"] == "spreads":
                for outcome in market["outcomes"]:
                    if normalize_team(outcome["name"]) == game.home_team:
                        home_spread = outcome["point"]
                    elif normalize_team(outcome["name"]) == game.away_team:
                        away_spread = outcome["point"]
            elif market["key"] == "totals":
                if market["outcomes"]:
                    total = market["outcomes"][0].get("point")
    return MoneylineOdds(
        book=bookmaker, home_ml=home_ml, away_ml=away_ml, captured_at=captured_at,
        home_spread=home_spread, away_spread=away_spread, total=total,
    )


def _prob_to_american(p):
    """implied prob -> American odds magnitude (unsigned), helper for mock data."""
    if p >= 0.5:
        return round(100 * p / (1 - p))
    return round(100 * (1 - p) / p)


def get_odds_provider():
    if config.ODDS_MODE == "api":
        return TheOddsApiProvider()
    return MockOddsProvider()
