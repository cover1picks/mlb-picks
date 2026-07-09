"""
data/public_betting_provider.py
================================
Ticket %/handle % splits. This is the one input in the whole system with NO
free, legal, programmatic source -- sportsbettingdime.com, Action Network,
etc. are websites for humans to read, not APIs. Three modes
(config.PUBLIC_BETTING_MODE):

- "manual" (default): you read today's split off a site like
  sportsbettingdime.com yourself and drop the numbers into
  manual_inputs/public_betting_<date>.json. run_daily.py auto-creates that
  file with neutral 50/50 placeholders + every game listed, so you're just
  editing numbers, not writing JSON from scratch.
- "mock": synthetic split, for demoing the pipeline only.
- "api": stub for you to wire up a paid data feed you have access to.
"""

import json
import logging
import random
from dataclasses import dataclass

import config

logger = logging.getLogger(__name__)


@dataclass
class PublicSplit:
    tickets_pct_home: float   # 0..100, % of TICKETS (bet count) on the home team
    handle_pct_home: float    # 0..100, % of HANDLE ($) on the home team
    source: str
    data_quality: str         # "manual" | "mock" | "api" | "missing"


class PublicBettingProvider:
    def get_splits(self, games, date_str):
        """Returns dict game_id -> PublicSplit."""
        raise NotImplementedError


class ManualPublicBettingProvider(PublicBettingProvider):
    def get_splits(self, games, date_str):
        ensure_manual_template(games, date_str)
        path = config.MANUAL_INPUTS_DIR / f"public_betting_{date_str}.json"
        try:
            with open(path) as f:
                raw = json.load(f)
        except Exception as exc:
            logger.warning("Couldn't read %s (%s) -- treating all games as 50/50.", path, exc)
            raw = {}

        out = {}
        for game in games:
            entry = raw.get(game.game_id)
            if entry is None:
                out[game.game_id] = PublicSplit(50.0, 50.0, "manual", "missing")
            else:
                out[game.game_id] = PublicSplit(
                    tickets_pct_home=float(entry.get("tickets_pct_home", 50.0)),
                    handle_pct_home=float(entry.get("handle_pct_home", 50.0)),
                    source=entry.get("source", "manual"),
                    data_quality="manual",
                )
        return out


class MockPublicBettingProvider(PublicBettingProvider):
    def get_splits(self, games, date_str):
        out = {}
        for game in games:
            rng = random.Random(f"{game.game_id}-{date_str}-public")
            tickets = round(rng.uniform(30, 70), 1)
            # handle usually diverges a bit from tickets -- that gap IS the "sharp" signal
            handle = round(max(5, min(95, tickets + rng.uniform(-20, 20))), 1)
            out[game.game_id] = PublicSplit(tickets, handle, "mock", "mock")
        return out


class ApiPublicBettingProvider(PublicBettingProvider):
    """BYO paid feed. Wire your provider's request/parse logic in here -- the
    rest of the engine only ever talks to the PublicSplit dataclass above, so
    nothing else needs to change once you do."""

    def get_splits(self, games, date_str):
        raise NotImplementedError(
            "Plug in your paid public-betting-splits feed here (see docstring)."
        )


def ensure_manual_template(games, date_str):
    """Writes manual_inputs/public_betting_<date>.json with every game listed
    at a neutral 50/50 split, IF that file doesn't already exist. Never
    overwrites a file you've already started filling in."""
    path = config.MANUAL_INPUTS_DIR / f"public_betting_{date_str}.json"
    if path.exists():
        return
    config.MANUAL_INPUTS_DIR.mkdir(exist_ok=True)
    template = {}
    for game in games:
        template[game.game_id] = {
            "_matchup": f"{game.away_team} @ {game.home_team}",
            "tickets_pct_home": 50.0,
            "handle_pct_home": 50.0,
            "source": "sportsbettingdime.com",
        }
    with open(path, "w") as f:
        json.dump(template, f, indent=2)
    logger.info("Wrote %s -- fill in real tickets/handle %% before you trust today's edges.", path)


def get_public_betting_provider():
    if config.PUBLIC_BETTING_MODE == "mock":
        return MockPublicBettingProvider()
    if config.PUBLIC_BETTING_MODE == "api":
        return ApiPublicBettingProvider()
    return ManualPublicBettingProvider()
