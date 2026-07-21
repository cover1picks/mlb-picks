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

Composite score is 0-100. Ranking + the config.HR_PROP_MAX_PER_DAY cap is
what decides quality now, not a hard score floor -- mirrors the same change
made to the moneyline side (MIN_EDGE). As long as there's at least one MLB
game today with a confirmed starter and usable batter data, this returns
real picks; it only comes back empty on a day with truly no computable data.
Anything scoring below config.HR_PROP_STRONG_SCORE is still shown but flagged
in its reasoning as a thinner-signal day.

Note: HR props are inherently MLB-only, so on any day with zero MLB games
this returns [] regardless -- that's the bet type, not a gap in the system.
"""

import config
from data.park_factors import park_factor_for


def evaluate_hr_prop_candidates(games, rosters, stats_provider, public_prop_splits,
                                 situational_by_team, lineup_source=None):
    """
    rosters: dict team_abbr -> list[str] batter names (confirmed lineup when
             posted, else active roster -- see lineup_source)
    public_prop_splits: dict (team_abbr, batter_name) -> pct_public_on_over (0-100), optional
    situational_by_team: dict team_abbr -> summary dict from data.situational.team_situational_summary
    lineup_source: dict team_abbr -> "confirmed" | "roster"; when "roster",
                   the pick is flagged as not-yet-confirmed so the report is
                   honest that the player might end up benched.
    """
    lineup_source = lineup_source or {}
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

                if score < config.HR_PROP_STRONG_SCORE:
                    reasoning.append(
                        f"Below our normal high-confidence bar ({config.HR_PROP_STRONG_SCORE}+) -- "
                        f"thinner signal day, shown as the best available rather than a slam-dunk."
                    )

                lineup_flag = lineup_source.get(batting_team, "confirmed")
                if lineup_flag == "roster":
                    reasoning.append(
                        "NOTE: starting lineup not posted yet -- confirm this player is actually "
                        "in today's lineup before betting."
                    )

                candidates.append({
                    "player_name": batter_name,
                    "team": batting_team,
                    "game_id": game.game_id,
                    "opponent_pitcher": opp_pitcher.name,
                    "score": score,
                    "reasoning": reasoning,
                    "data_quality": "roster_unconfirmed" if lineup_flag == "roster" else quality,
                })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    strongest = [c for c in candidates if c["score"] >= config.HR_PROP_MIN_SCORE]
    return strongest[: config.HR_PROP_MAX_PER_DAY]


def _score_candidate(batter_name, batter, pitcher, hr_park_factor, motivation_note):
    if batter.data_quality in ("degraded", "not_found") or batter.barrel_pct is None:
        return None, None, batter.data_quality

    score = 50.0
    reasoning = []
    reasoning.append(f"Starting score: 50 (baseline). Every factor below adds or subtracts points.")

    # 1. Barrel signal check -- the batter's own power-contact quality
    if batter.barrel_pct >= 12:
        score += 12
        reasoning.append(f"[Barrel Signal +12] {batter_name} has an ELITE barrel rate of {batter.barrel_pct:.1f}% "
                         f"(12%+ is top-tier power contact -- how often he squares a ball up for max damage).")
    elif batter.barrel_pct < 6:
        score -= 10
        reasoning.append(f"[Barrel Signal -10] {batter_name}'s barrel rate is only {batter.barrel_pct:.1f}% "
                         f"(under 6% -- weak power contact, drags this down).")
    else:
        reasoning.append(f"[Barrel Signal +0] {batter_name}'s barrel rate is {batter.barrel_pct:.1f}% (average range, neutral).")
    if batter.recent_barrel_trend and batter.recent_barrel_trend > 2:
        score += 8
        reasoning.append(f"[Hot Streak +8] Trending UP: barrel% is +{batter.recent_barrel_trend:.1f} points over the "
                         f"last 15 days -- he's heating up right now.")

    # 2. Pitcher vulnerability -- how hittable the opposing starter is for HRs
    if pitcher and pitcher.barrel_pct_allowed is not None:
        if pitcher.barrel_pct_allowed >= 9:
            score += 12
            reasoning.append(f"[Pitcher Vulnerability +12] Opposing SP {pitcher.name} allows a HIGH barrel rate of "
                             f"{pitcher.barrel_pct_allowed:.1f}% (9%+ -- gives up hard, square contact often).")
        elif pitcher.barrel_pct_allowed < 5:
            score -= 10
            reasoning.append(f"[Pitcher Vulnerability -10] {pitcher.name} only allows {pitcher.barrel_pct_allowed:.1f}% "
                             f"barrels (under 5% -- tough to square up, works against this pick).")
        else:
            reasoning.append(f"[Pitcher Vulnerability +0] {pitcher.name} allows {pitcher.barrel_pct_allowed:.1f}% barrels (average).")
    if pitcher and pitcher.hr_per_9 is not None:
        if pitcher.hr_per_9 >= 1.4:
            score += 8
            reasoning.append(f"[HR Rate Allowed +8] {pitcher.name} is running a {pitcher.hr_per_9:.2f} HR/9 "
                             f"(1.4+ -- he serves up homers at a high clip).")
        elif pitcher.hr_per_9 < 0.9:
            score -= 8
            reasoning.append(f"[HR Rate Allowed -8] {pitcher.name} only allows {pitcher.hr_per_9:.2f} HR/9 "
                             f"(under 0.9 -- stingy with the long ball).")
        else:
            reasoning.append(f"[HR Rate Allowed +0] {pitcher.name} allows {pitcher.hr_per_9:.2f} HR/9 (average).")

    # 3. Park + motivation overlay -- does the ballpark help homers today
    if hr_park_factor >= 108:
        score += 10
        reasoning.append(f"[Park Factor +10] This park's HR factor is {hr_park_factor} (108+ -- a hitter's park that "
                         f"inflates home runs).")
    elif hr_park_factor <= 92:
        score -= 10
        reasoning.append(f"[Park Factor -10] This park's HR factor is {hr_park_factor} (92 or below -- a pitcher's park "
                         f"that suppresses home runs).")
    else:
        reasoning.append(f"[Park Factor +0] This park's HR factor is {hr_park_factor} (roughly neutral for homers).")
    if motivation_note:
        reasoning.append(f"[Overlay] {motivation_note}")

    final = round(max(0, min(100, score)), 1)
    reasoning.append(f"FINAL HR SCORE: {final}/100. Higher = stronger homer spot; today's picks are the highest scores on the slate.")
    return final, reasoning, "ok"


def _motivation_note(situational):
    if situational and situational.get("park_runs_factor", 100) >= 110:
        return "Hitter-friendly conditions today."
    return None
