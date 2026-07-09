"""
engine/hr_props.py
===================
HR Prop Workflow (runs automatically every day alongside moneyline, per your
build choice):
  1. Barrel Signal Check       -- batter's own barrel%/recent trend
  2. Pitcher Vulnerability     -- opposing SP's barrel%/hard-hit%/HR-9 allowed
  3. Park + Motivation Overlay -- HR park factor + motivation context
  4. Public Lean Filter        -- fade extremely public props unless every
                                   other signal is elite (no free public-prop
                                   split source exists, so this only engages
                                   if you wire one into public_prop_splits)
  5. Final Selection           -- only the strongest signals survive

Composite score is 0-100; only scores >= config.HR_PROP_MIN_SCORE make the
report, capped at config.HR_PROP_MAX_PER_DAY (best 4-5/day) for the whole
slate. "Only the strongest signals" is enforced by that floor -- on a thin
slate or a day with nothing good, this can still return fewer than the cap,
including [].
"""

import config
from data.park_factors import park_factor_for


def evaluate_hr_prop_candidates(games, rosters, stats_provider, public_prop_splits, situational_by_team):
    """
    rosters: dict team_abbr -> list[str] batter names (active roster, batters only)
    public_prop_splits: dict (team_abbr, batter_name) -> pct_public_on_over (0-100), optional
    situational_by_team: dict team_abbr -> summary dict from data.situational.team_situational_summary
    """
    candidates = []
    for game in games:
        for batting_team, opp_pitcher in (
            (game.home_team, game.away_pitcher),
            (game.away_team, game.home_pitcher),
        ):
            if not opp_pitcher:
                continue
            pitcher_profile = stats_provider.get_pitcher_profile(opp_pitcher.name)
            hr_park_factor = park_factor_for(game.home_team)[1]
            motivation = _motivation_note(situational_by_team.get(batting_team, {}))

            for batter_name in rosters.get(batting_team, []):
                batter_profile = stats_provider.get_batter_profile(batter_name, batting_team)
                score, reasoning, quality = _score_candidate(
                    batter_name, batter_profile, pitcher_profile, hr_park_factor, motivation
                )
                if score is None:
                    continue

                public_lean = public_prop_splits.get((batting_team, batter_name)) if public_prop_splits else None
                if public_lean is not None and public_lean >= 80:
                    if score < 90:
                        continue  # step 4: fade an overwhelmingly public prop unless it's otherwise elite
                    reasoning.append(f"Public is {public_lean:.0f}% on the OVER -- kept only because every other signal is elite.")

                candidates.append({
                    "player_name": batter_name,
                    "team": batting_team,
                    "game_id": game.game_id,
                    "opponent_pitcher": opp_pitcher.name,
                    "score": score,
                    "reasoning": reasoning,
                    "data_quality": quality,
                })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    strongest = [c for c in candidates if c["score"] >= config.HR_PROP_MIN_SCORE]
    return strongest[: config.HR_PROP_MAX_PER_DAY]


def _score_candidate(batter_name, batter, pitcher, hr_park_factor, motivation_note):
    if batter.data_quality in ("degraded", "not_found") or batter.barrel_pct is None:
        return None, None, batter.data_quality

    score = 50.0
    reasoning = []

    # 1. Barrel signal check
    if batter.barrel_pct >= 12:
        score += 12
        reasoning.append(f"{batter_name}: strong barrel rate ({batter.barrel_pct:.1f}%).")
    elif batter.barrel_pct < 6:
        score -= 10
    if batter.recent_barrel_trend and batter.recent_barrel_trend > 2:
        score += 8
        reasoning.append(f"{batter_name} trending up: barrel% +{batter.recent_barrel_trend:.1f} pts over last 15 days.")

    # 2. Pitcher vulnerability
    if pitcher and pitcher.barrel_pct_allowed is not None:
        if pitcher.barrel_pct_allowed >= 9:
            score += 12
            reasoning.append(f"{pitcher.name} allows a high barrel rate ({pitcher.barrel_pct_allowed:.1f}%).")
        elif pitcher.barrel_pct_allowed < 5:
            score -= 10
    if pitcher and pitcher.hr_per_9 is not None:
        if pitcher.hr_per_9 >= 1.4:
            score += 8
            reasoning.append(f"{pitcher.name} is running a {pitcher.hr_per_9:.2f} HR/9.")
        elif pitcher.hr_per_9 < 0.9:
            score -= 8

    # 3. Park + motivation overlay
    if hr_park_factor >= 108:
        score += 10
        reasoning.append(f"Park HR factor {hr_park_factor} boosts homer probability.")
    elif hr_park_factor <= 92:
        score -= 10
    if motivation_note:
        reasoning.append(motivation_note)

    return round(max(0, min(100, score)), 1), reasoning, "ok"


def _motivation_note(situational):
    if situational and situational.get("park_runs_factor", 100) >= 110:
        return "Hitter-friendly conditions today."
    return None
