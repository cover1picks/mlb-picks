"""
output/history_log.py
=======================
Writes today's recommendations into the recommendations table, and computes
the rolling bankroll/P&L summary shown in both reports. Grading (deciding
win/loss per recommendation) happens the NEXT run, in backtest/grader.py --
today's picks start out "pending".
"""

from datetime import datetime, timezone


def log_recommendations(db, date_str, plays, hr_props):
    now = datetime.now(timezone.utc).isoformat()
    for play in plays:
        db.insert_recommendation(
            date=date_str, game_id=play.game.game_id, kind="moneyline",
            side_or_player=play.side, team=play.team, odds_american=play.odds_american,
            edge_pct=play.edge_pct, model_prob=play.model_prob, market_prob=play.market_prob,
            stake_units=play.stake_units, stake_dollars=play.stake_dollars,
            reasoning=play.reasoning,
            factor_scores=[{"key": fs.key, "signal": fs.signal, "weight": fs.weight,
                            "reasoning": fs.reasoning, "data_quality": fs.data_quality}
                           for fs in play.factor_scores],
            created_at=now,
        )
    for prop in hr_props:
        db.insert_recommendation(
            date=date_str, game_id=prop.get("game_id"), kind="hr_prop",
            side_or_player=prop["player_name"], team=prop["team"], odds_american=None,
            edge_pct=None, model_prob=None, market_prob=None,
            stake_units=1.0, stake_dollars=0.0, reasoning=prop["reasoning"], factor_scores=[],
            created_at=now,
        )


def bankroll_summary(db):
    history = db.get_bankroll_history(limit=10000)
    if not history:
        return {"wins": 0, "losses": 0, "units_net": 0.0, "dollars_net": 0.0, "running_bankroll": 0.0}
    wins = sum(h.get("wins", 0) or 0 for h in history)
    graded = sum(h.get("bets_graded", 0) or 0 for h in history)
    units_net = sum((h.get("units_won") or 0) - (h.get("units_staked") or 0) for h in history)
    dollars_net = sum((h.get("dollars_won") or 0) - (h.get("dollars_staked") or 0) for h in history)
    latest_bankroll = history[0].get("running_bankroll")
    return {
        "wins": wins, "losses": graded - wins,
        "units_net": units_net, "dollars_net": dollars_net,
        "running_bankroll": latest_bankroll if latest_bankroll is not None else 0.0,
    }
