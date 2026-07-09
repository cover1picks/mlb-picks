"""
engine/models.py
=================
Plain dataclasses shared across the pipeline. Keeping these in one file
means data/, engine/, and output/ all speak the same shapes without
importing each other in a tangle.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class ProbablePitcher:
    name: str
    player_id: Optional[int] = None
    throws: Optional[str] = None  # 'L' or 'R'


@dataclass
class Game:
    game_id: str
    date: str
    home_team: str
    away_team: str
    game_time_utc: Optional[str]
    home_pitcher: Optional[ProbablePitcher] = None
    away_pitcher: Optional[ProbablePitcher] = None


@dataclass
class MoneylineOdds:
    book: str
    home_ml: Optional[int]
    away_ml: Optional[int]
    captured_at: str
    home_spread: Optional[float] = None
    away_spread: Optional[float] = None
    total: Optional[float] = None


@dataclass
class FactorScore:
    key: str
    label: str
    signal: float          # -1..+1, positive leans HOME, negative leans AWAY
    weight: float
    reasoning: str
    data_quality: str = "ok"   # ok | mock | manual | missing | degraded | partial | not_found


@dataclass
class SideEvaluation:
    game: Game
    odds: MoneylineOdds
    factor_scores: List[FactorScore]
    market_prob_home: Optional[float]
    market_prob_away: Optional[float]
    model_prob_home: Optional[float]
    model_prob_away: Optional[float]
    recommended_side: Optional[str]  # "home" | "away" | None
    edge_pct: float
    dropped_reason: Optional[str] = None


@dataclass
class Recommendation:
    game: Game
    side: str             # "home" | "away"
    team: str
    odds_american: int
    edge_pct: float
    model_prob: float
    market_prob: float
    stake_units: float
    stake_dollars: float
    reasoning: List[str]
    factor_scores: List[FactorScore]
    diversification_flag: Optional[str] = None
    line_movement_flag: Optional[str] = None


@dataclass
class ParlayRecommendation:
    legs: List[Recommendation]
    combined_odds_american: int
    combined_prob: float
    stake_units: float
    reasoning: str


@dataclass
class DailyReport:
    date: str
    slate_size: int
    plays: List[Recommendation]
    hr_props: List[dict]
    parlay: Optional[ParlayRecommendation]
    dropped_notes: List[str]
    celestial: dict
    numerology: dict
    bankroll_summary: dict
    data_warnings: List[str]
