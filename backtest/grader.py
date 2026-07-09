"""
backtest/grader.py
====================
Post-game review: fetch final scores for any game with pending moneyline
recommendations, mark each recommendation won/lost, and roll the result into
bankroll_log. run_daily.py calls this automatically at the start of each run
(it grades YESTERDAY's plays before making today's).

HR props are not auto-graded here -- there's no free, easy source for
per-player HR settlement by box score line alone without extra parsing, so
those stay "pending" for manual review (log your own results if you want
them counted in the bankroll).
"""

import logging
from datetime import datetime, timezone

import requests

import config

logger = logging.getLogger(__name__)


def grade_pending(db):
    pending = db.get_pending_recommendations()
    if not pending:
        return {"graded": 0}

    graded_count = 0
    by_date = {}
    for rec in pending:
        if rec["kind"] != "moneyline" or not rec["game_id"]:
            continue
        result = _get_final_score(rec["game_id"])
        if result is None:
            continue
        home_score, away_score = result
        if home_score == away_score:
            status = "push"
        else:
            winner_side = "home" if home_score > away_score else "away"
            status = "won" if rec["side_or_player"] == winner_side else "lost"
        db.set_recommendation_status(rec["id"], status)
        db.record_result(rec["game_id"], home_score, away_score, datetime.now(timezone.utc).isoformat())
        graded_count += 1

        day = by_date.setdefault(rec["date"], {"staked": 0.0, "won": 0.0, "d_staked": 0.0,
                                                 "d_won": 0.0, "wins": 0, "graded": 0})
        day["staked"] += rec["stake_units"] or 0
        day["d_staked"] += rec["stake_dollars"] or 0
        day["graded"] += 1
        if status == "won":
            day["won"] += _payout(rec["odds_american"], rec["stake_units"])
            day["d_won"] += _payout(rec["odds_american"], rec["stake_dollars"])
            day["wins"] += 1
        elif status == "push":
            day["won"] += rec["stake_units"] or 0
            day["d_won"] += rec["stake_dollars"] or 0

    for day, totals in sorted(by_date.items()):  # chronological, so bankroll chains correctly
        prior = db.get_bankroll_history(limit=1)
        prior_bankroll = prior[0]["running_bankroll"] if prior and prior[0].get("running_bankroll") is not None else config.STARTING_BANKROLL
        net_dollars = totals["d_won"] - totals["d_staked"]
        db.upsert_bankroll_day(
            day, units_staked=totals["staked"], units_won=totals["won"],
            dollars_staked=totals["d_staked"], dollars_won=totals["d_won"],
            running_bankroll=prior_bankroll + net_dollars,
            bets_graded=totals["graded"], wins=totals["wins"],
        )

    return {"graded": graded_count}


def _get_final_score(game_id):
    try:
        resp = requests.get(f"https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live", timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        linescore = payload.get("liveData", {}).get("linescore", {})
        status = payload.get("gameData", {}).get("status", {}).get("abstractGameState")
        if status != "Final":
            return None
        home = linescore.get("teams", {}).get("home", {}).get("runs")
        away = linescore.get("teams", {}).get("away", {}).get("runs")
        if home is None or away is None:
            return None
        return home, away
    except Exception as exc:
        logger.debug("final score fetch failed for game %s: %s", game_id, exc)
        return None


def _payout(odds_american, stake):
    if odds_american is None or stake is None:
        return 0.0
    odds_american = float(odds_american)
    if odds_american > 0:
        return stake * (1 + odds_american / 100.0)
    return stake * (1 + 100.0 / -odds_american)
