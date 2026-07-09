"""
engine/grading_factors.py
==========================
One function per grading factor from the strategy spec. Every function takes
a GradingContext and returns an engine.models.FactorScore:
    signal   : -1..+1, positive leans HOME, negative leans AWAY
    weight   : pulled from config.FACTOR_WEIGHTS
    reasoning: one readable sentence for the report
    data_quality: "ok" | "mock" | "manual" | "missing" | "degraded" | "partial"

Keeping every factor's math in ONE small function each is what makes the
system auditable -- the daily report prints every one of these reasoning
strings so you can see exactly why a play cleared (or didn't).

IMPORTANT convention note: celestial_signal / numerology_signal on the
context are already converted to the home/away convention by
engine/scoring.py before this module ever sees them (their native convention
is favorite/underdog).
"""

from dataclasses import dataclass

import config
from engine.models import FactorScore


@dataclass
class GradingContext:
    game: object
    home_pitcher_profile: object
    away_pitcher_profile: object
    home_offense: object
    away_offense: object
    home_record: dict           # {wins, losses, runs_scored, runs_allowed, games_back, streak}
    away_record: dict
    public_split: object
    situational: dict
    celestial_signal: float     # already home/away convention (see module docstring)
    celestial_reasoning: str
    numerology_signal: float    # already home/away convention
    numerology_reasoning: str


def _clip(x):
    return max(-1.0, min(1.0, x))


def score_talent_gap(ctx):
    hr = ctx.home_record or {}
    ar = ctx.away_record or {}
    home_pyth = _pyth_win_pct(hr.get("runs_scored"), hr.get("runs_allowed"))
    away_pyth = _pyth_win_pct(ar.get("runs_scored"), ar.get("runs_allowed"))
    if home_pyth is None or away_pyth is None:
        return FactorScore("talent_gap", "Talent gap / better team", 0.0,
                            config.FACTOR_WEIGHTS["talent_gap"],
                            "Not enough season data yet to separate these teams on talent.",
                            "degraded")
    diff = home_pyth - away_pyth
    signal = _clip(diff * 4)  # a 10-point pyth-win% gap -> full-strength signal
    reasoning = (f"Pythagorean win%: home {home_pyth:.3f} vs away {away_pyth:.3f} "
                 f"({'home' if diff > 0 else 'away'} the deeper team)")
    return FactorScore("talent_gap", "Talent gap / better team", signal,
                        config.FACTOR_WEIGHTS["talent_gap"], reasoning, "ok")


def score_matchup_pitching(ctx):
    hp, ap = ctx.home_pitcher_profile, ctx.away_pitcher_profile
    if not hp or not ap or hp.fip is None or ap.fip is None:
        return FactorScore("matchup_pitching", "Matchup advantage (pitching)", 0.0,
                            config.FACTOR_WEIGHTS["matchup_pitching"],
                            "Probable starters' FIP unavailable -- neutral until confirmed.",
                            "degraded")
    fip_gap = ap.fip - hp.fip  # positive => home starter better (lower FIP)
    signal = _clip(fip_gap / 2.0)  # a full run of FIP gap = full-strength signal
    better = "home" if fip_gap > 0 else "away"
    home_name = ctx.game.home_pitcher.name if ctx.game.home_pitcher else "TBD"
    away_name = ctx.game.away_pitcher.name if ctx.game.away_pitcher else "TBD"
    reasoning = f"Starter FIP: {home_name} {hp.fip:.2f} vs {away_name} {ap.fip:.2f} -> edge to {better} starter"
    return FactorScore("matchup_pitching", "Matchup advantage (pitching)", signal,
                        config.FACTOR_WEIGHTS["matchup_pitching"], reasoning, "ok")


def score_advanced_analytics(ctx):
    hp, ap = ctx.home_pitcher_profile, ctx.away_pitcher_profile
    ho, ao = ctx.home_offense, ctx.away_offense
    parts = []
    total = 0.0
    n = 0
    if hp and ap and hp.hard_hit_pct_allowed is not None and ap.hard_hit_pct_allowed is not None:
        gap = ap.hard_hit_pct_allowed - hp.hard_hit_pct_allowed  # positive => home SP allows less hard contact
        total += _clip(gap / 10.0)
        n += 1
        parts.append(f"hard-hit% allowed: home SP {hp.hard_hit_pct_allowed:.1f} vs away SP {ap.hard_hit_pct_allowed:.1f}")
    if ho and ao and ho.woba is not None and ao.woba is not None:
        gap = ho.woba - ao.woba
        total += _clip(gap / 0.05)
        n += 1
        parts.append(f"team wOBA: home {ho.woba:.3f} vs away {ao.woba:.3f}")
    if n == 0:
        return FactorScore("advanced_analytics", "Advanced analytics (FIP/xERA/barrel/hard-hit)", 0.0,
                            config.FACTOR_WEIGHTS["advanced_analytics"],
                            "Statcast/FanGraphs data unavailable today -- neutral.", "degraded")
    signal = _clip(total / n)
    return FactorScore("advanced_analytics", "Advanced analytics (FIP/xERA/barrel/hard-hit)", signal,
                        config.FACTOR_WEIGHTS["advanced_analytics"], "; ".join(parts), "ok")


def score_motivation(ctx):
    hr = ctx.home_record or {}
    ar = ctx.away_record or {}
    signal = 0.0
    notes = []
    h_gb, a_gb = hr.get("games_back"), ar.get("games_back")
    if h_gb is not None and a_gb is not None:
        motivation_gap = (a_gb - h_gb) / 10.0  # closer to first place = more motivated in-season
        signal += _clip(motivation_gap) * 0.6
        notes.append(f"games back: home {h_gb} vs away {a_gb}")
    h_streak, a_streak = hr.get("streak") or 0, ar.get("streak") or 0
    signal += _clip((h_streak - a_streak) / 5.0) * 0.4
    notes.append(f"streak: home {h_streak:+d} vs away {a_streak:+d}")
    signal = _clip(signal)
    quality = "ok" if h_gb is not None else "degraded"
    return FactorScore("motivation", "Motivation (playoffs/revenge/tanking/streak)", signal,
                        config.FACTOR_WEIGHTS["motivation"], "; ".join(notes), quality)


def score_public_sharp_split(ctx):
    split = ctx.public_split
    if not split:
        return FactorScore("public_sharp_split", "Public vs. sharp money", 0.0,
                            config.FACTOR_WEIGHTS["public_sharp_split"],
                            "No public betting data available today.", "degraded")
    tickets_home = split.tickets_pct_home
    handle_home = split.handle_pct_home
    # reverse-line-style indicator: handle skews harder than tickets -> sharp money
    sharp_gap = (handle_home - tickets_home) / 100.0
    signal = _clip(sharp_gap * 3.0)
    lean = "sharp money on home" if sharp_gap > 0 else "sharp money on away" if sharp_gap < 0 else "no split"
    reasoning = f"Tickets {tickets_home:.0f}% home / Handle {handle_home:.0f}% home -> {lean}"
    if split.data_quality in ("mock", "missing"):
        reasoning += "  [SIMULATED/PLACEHOLDER DATA -- fill in manual_inputs/public_betting_*.json]"
    return FactorScore("public_sharp_split", "Public vs. sharp money", signal,
                        config.FACTOR_WEIGHTS["public_sharp_split"], reasoning, split.data_quality)


def score_situational(ctx):
    sit = ctx.situational or {}
    signal = 0.0
    notes = [f"park run factor {sit.get('park_runs_factor', 100)}"]
    home_injuries = sit.get("home_injuries", [])
    away_injuries = sit.get("away_injuries", [])
    signal += _clip(_injury_score(away_injuries) - _injury_score(home_injuries))
    if home_injuries or away_injuries:
        notes.append(f"injuries: home {len(home_injuries)}, away {len(away_injuries)}")
    home_rest = (sit.get("home_rest") or {}).get("rest_days")
    away_rest = (sit.get("away_rest") or {}).get("rest_days")
    if home_rest is not None and away_rest is not None:
        signal += _clip((home_rest - away_rest) / 3.0) * 0.3
        notes.append(f"rest: home {home_rest}d, away {away_rest}d")
    signal = _clip(signal)
    return FactorScore("situational", "Situational (injuries/rest/park)", signal,
                        config.FACTOR_WEIGHTS["situational"], "; ".join(notes), "ok")


def _injury_score(injuries):
    weight = {"high": 1.0, "medium": 0.5, "low": 0.2}
    return sum(weight.get(i.get("impact", "low"), 0.2) for i in injuries)


def score_moon_zodiac(ctx):
    return FactorScore("moon_zodiac", "Moon phase + zodiac energy", ctx.celestial_signal,
                        config.FACTOR_WEIGHTS["moon_zodiac"], ctx.celestial_reasoning, "ok")


def score_numerology(ctx):
    return FactorScore("numerology", "Numerology of the date", ctx.numerology_signal,
                        config.FACTOR_WEIGHTS["numerology"], ctx.numerology_reasoning, "ok")


ALL_FACTOR_SCORERS = [
    score_talent_gap,
    score_matchup_pitching,
    score_advanced_analytics,
    score_motivation,
    score_public_sharp_split,
    score_situational,
    score_moon_zodiac,
    score_numerology,
]


def score_all_factors(ctx):
    return [scorer(ctx) for scorer in ALL_FACTOR_SCORERS]


def _pyth_win_pct(runs_scored, runs_allowed, exponent=1.83):
    if not runs_scored or not runs_allowed:
        return None
    try:
        rs, ra = float(runs_scored), float(runs_allowed)
        if rs <= 0 or ra <= 0:
            return None
        return rs ** exponent / (rs ** exponent + ra ** exponent)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
