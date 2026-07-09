"""
engine/strategy_rules.py
=========================
Non-negotiable rules layered on top of raw edge numbers:
  - never below MIN_EDGE
  - flat 1-unit sizing
  - at most MAX_PLAYS_PER_DAY, and a 2nd play only if it's as strong as the 1st
  - team diversification: don't play the same team 3+ days running without
    stricter re-confirmation
  - line movement: only drop a play on significant adverse movement AND
    heavy smart money confirming it

select_daily_plays() is the single entry point run_daily.py calls.
"""

import config
from engine.models import Recommendation


def select_daily_plays(evaluations, db, public_splits, run_date_str):
    candidates = [e for e in evaluations if e.recommended_side and e.edge_pct >= config.MIN_EDGE]
    candidates.sort(key=lambda e: e.edge_pct, reverse=True)

    recent_picks = {p["team"] for p in db.get_recent_team_picks(run_date_str, config.DIVERSIFICATION_LOOKBACK_DAYS)}

    plays = []
    dropped_notes = []
    for ev in candidates:
        if len(plays) >= config.MAX_PLAYS_PER_DAY:
            break
        if plays and ev.edge_pct < plays[0].edge_pct - config.SECOND_PLAY_TOLERANCE:
            break  # 2nd play must be at least as strong as the primary, or we stop here

        team = ev.game.home_team if ev.recommended_side == "home" else ev.game.away_team

        diversification_flag = None
        if team in recent_picks:
            strong_factors = sum(1 for fs in ev.factor_scores if abs(fs.signal) >= 0.5)
            required_edge = config.MIN_EDGE + config.DIVERSIFICATION_EXTRA_EDGE
            if ev.edge_pct < required_edge or strong_factors < config.DIVERSIFICATION_MIN_STRONG_FACTORS:
                dropped_notes.append(f"{team}: skipped -- played recently and didn't clear the stricter re-confirmation bar.")
                continue
            diversification_flag = (f"{team} played within the last {config.DIVERSIFICATION_LOOKBACK_DAYS} days -- "
                                     f"needed {required_edge:.1%}+ edge and {config.DIVERSIFICATION_MIN_STRONG_FACTORS}+ "
                                     f"strong factors, and it cleared both.")

        split = public_splits.get(ev.game.game_id) if public_splits else None
        line_flag, dropped = _check_line_movement(ev, db, split)
        if dropped:
            dropped_notes.append(f"{team}: {line_flag}")
            continue

        odds_american = ev.odds.home_ml if ev.recommended_side == "home" else ev.odds.away_ml
        plays.append(Recommendation(
            game=ev.game, side=ev.recommended_side, team=team,
            odds_american=odds_american, edge_pct=ev.edge_pct,
            model_prob=ev.model_prob_home if ev.recommended_side == "home" else ev.model_prob_away,
            market_prob=ev.market_prob_home if ev.recommended_side == "home" else ev.market_prob_away,
            stake_units=config.FLAT_STAKE_UNITS,
            stake_dollars=config.FLAT_STAKE_UNITS * config.UNIT_SIZE_DOLLARS,
            reasoning=[fs.reasoning for fs in ev.factor_scores],
            factor_scores=ev.factor_scores,
            diversification_flag=diversification_flag,
            line_movement_flag=line_flag,
        ))
        recent_picks.add(team)  # don't recommend the same team twice in one slate either

    return plays, dropped_notes


def get_parlay_pool(evaluations):
    """All games that independently cleared MIN_EDGE, sorted by edge desc --
    used ONLY for the optional parlay (engine/parlay.py). Deliberately NOT
    capped at MAX_PLAYS_PER_DAY and not run through diversification/line-
    movement -- the parlay is a separate, smaller-stakes bonus action (up to
    PARLAY_MAX_LEGS), not the disciplined 1-2 straight plays, so it draws
    from the full qualifying pool instead of just the official picks."""
    candidates = [e for e in evaluations if e.recommended_side and e.edge_pct >= config.MIN_EDGE]
    candidates.sort(key=lambda e: e.edge_pct, reverse=True)
    pool = []
    for ev in candidates:
        team = ev.game.home_team if ev.recommended_side == "home" else ev.game.away_team
        odds_american = ev.odds.home_ml if ev.recommended_side == "home" else ev.odds.away_ml
        model_prob = ev.model_prob_home if ev.recommended_side == "home" else ev.model_prob_away
        market_prob = ev.market_prob_home if ev.recommended_side == "home" else ev.market_prob_away
        pool.append(Recommendation(
            game=ev.game, side=ev.recommended_side, team=team, odds_american=odds_american,
            edge_pct=ev.edge_pct, model_prob=model_prob, market_prob=market_prob,
            stake_units=config.FLAT_STAKE_UNITS, stake_dollars=config.FLAT_STAKE_UNITS * config.UNIT_SIZE_DOLLARS,
            reasoning=[fs.reasoning for fs in ev.factor_scores], factor_scores=ev.factor_scores,
        ))
    return pool


def american_prob(ml):
    ml = float(ml)
    if ml > 0:
        return 100.0 / (ml + 100.0)
    return -ml / (-ml + 100.0)


def _check_line_movement(ev, db, split):
    """Returns (note_or_None, dropped_bool)."""
    opening = db.get_opening_line(ev.game.game_id)
    if not opening:
        return None, False

    side = ev.recommended_side
    open_ml = opening["home_ml"] if side == "home" else opening["away_ml"]
    current_ml = ev.odds.home_ml if side == "home" else ev.odds.away_ml
    if open_ml is None or current_ml is None:
        return None, False

    cents_moved = abs(current_ml - open_ml)
    adverse = american_prob(current_ml) > american_prob(open_ml)

    if not adverse or cents_moved < config.LINE_MOVE_DROP_CENTS:
        return None, False

    if not config.LINE_MOVE_REQUIRES_SHARP_CONFIRM:
        return (f"Line moved {cents_moved:.0f} cents against the play (open {open_ml:+.0f} -> "
                f"now {current_ml:+.0f}) -- dropped."), True

    other_side_handle = None
    if split:
        other_side_handle = (100 - split.handle_pct_home) if side == "home" else split.handle_pct_home
    if other_side_handle is not None and other_side_handle >= config.HEAVY_MONEY_HANDLE_THRESHOLD * 100:
        return (f"Line moved {cents_moved:.0f} cents against the play AND {other_side_handle:.0f}% of handle is "
                f"on the other side -- dropped (smart money confirmed)."), True

    return (f"Line moved {cents_moved:.0f} cents against the play (open {open_ml:+.0f} -> now "
            f"{current_ml:+.0f}) but not confirmed by heavy money -- kept, watch closely."), False
