#!/usr/bin/env python3
"""
run_daily.py
=============
The one command you run each day:

    python run_daily.py

What it does, in order:
  1. Grades yesterday's pending recommendations (backtest/grader.py).
  2. Pulls today's MLB slate, odds, public splits, advanced stats, standings,
     situational context, moon phase/zodiac, and numerology.
  3. Scores every game through every grading factor (engine/grading_factors.py)
     into one edge % per game (engine/scoring.py).
  4. Applies the non-negotiable rules -- min edge, flat sizing, second-play,
     diversification, line movement (engine/strategy_rules.py).
  5. Runs the HR prop workflow (engine/hr_props.py) automatically.
  6. Maybe builds a bonus parlay (engine/parlay.py).
  7. Prints the terminal report and writes the HTML report.
  8. Logs everything to SQLite for tomorrow's grading + P&L tracking.

Flags:
  --date YYYY-MM-DD   run as if it were this date (backtesting / testing)
  --skip-grading      don't grade yesterday's picks first
  --auto              scheduled/unattended mode -- only publish once, timed
                      to ~1 hour before today's first pitch instead of
                      running immediately (see auto_gate.py). This is what
                      .github/workflows/daily.yml calls; a plain manual run
                      never needs it.
"""

import argparse
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import auto_gate
import config
from data.db import Database
from data.schedule_provider import get_todays_games
from data.odds_providers import get_odds_provider
from data.public_betting_provider import get_public_betting_provider
from data.stats_provider import get_stats_provider
from data.situational import park_and_situational_summary, ensure_injury_template, team_situational_summary
from data.standings import get_all_team_records
from data.rosters import get_team_batters
from data.celestial import celestial_signal_for, moon_phase_for, moon_sign_for
from data.numerology import numerology_signal_for, reduce_date

from engine.scoring import evaluate_game
from engine.strategy_rules import select_daily_plays, get_parlay_pool
from engine.hr_props import evaluate_hr_prop_candidates
from engine.parlay import maybe_build_parlay
from engine.models import DailyReport

from output.terminal_report import print_daily_report
from output.html_report import render_daily_report
from output.history_log import log_recommendations, bankroll_summary
from output.publish_github_pages import publish_latest_report

from backtest.grader import grade_pending

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO),
                     format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_daily")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run today's MLB betting recommendation pipeline.")
    parser.add_argument("--date", default=None, help="Run as if it were this date (YYYY-MM-DD).")
    parser.add_argument("--skip-grading", action="store_true", help="Skip grading yesterday's picks first.")
    parser.add_argument("--auto", action="store_true",
                         help="Scheduled mode: only publish once, ~1 hour before first pitch.")
    args = parser.parse_args(argv)

    run_date = (datetime.strptime(args.date, "%Y-%m-%d").date() if args.date
                else datetime.now(ZoneInfo(config.TIMEZONE)).date())  # "today" in config.TIMEZONE,
                # not the machine's local date -- matters on a UTC cloud runner (see auto_gate.py)
    date_str = run_date.strftime("%Y-%m-%d")

    games = get_todays_games(date_str)

    if args.auto:
        should_run, reason = auto_gate.should_run_now(run_date, date_str, games)
        logger.info("Auto-run check: %s", reason)
        if not should_run:
            return

    db = Database()

    if not args.skip_grading:
        result = grade_pending(db)
        if result.get("graded"):
            logger.info("Graded %s pending recommendation(s) from prior days.", result["graded"])

    data_warnings = []

    if not games:
        logger.info("No MLB games found for %s.", date_str)
        report = DailyReport(date=date_str, slate_size=0, plays=[], hr_props=[], parlay=None,
                              dropped_notes=[], celestial=_celestial_dict(run_date),
                              numerology=_numerology_dict(run_date),
                              bankroll_summary=bankroll_summary(db),
                              data_warnings=["No games on today's MLB schedule."])
        _emit(report)
        if args.auto:
            auto_gate.mark_published(date_str)
        return

    if len(games) < config.MIN_SLATE_SIZE:
        data_warnings.append(f"Small slate today ({len(games)} games) -- confidence in every edge is lower.")

    for game in games:
        db.upsert_game(game)

    odds_provider = get_odds_provider()
    odds_by_game = odds_provider.get_odds(games)
    now_iso = datetime.now(timezone.utc).isoformat()
    for game in games:
        odds = odds_by_game.get(game.game_id)
        if not odds:
            continue
        is_opening = db.get_opening_line(game.game_id) is None
        db.record_odds_snapshot(game.game_id, odds, now_iso, is_opening=is_opening)

    ensure_injury_template(date_str)
    public_splits = get_public_betting_provider().get_splits(games, date_str)
    for game in games:
        split = public_splits.get(game.game_id)
        if not split:
            continue
        db.record_public_split(game.game_id, split, now_iso)
        if split.data_quality in ("missing", "mock"):
            data_warnings.append(
                f"{game.away_team} @ {game.home_team}: public betting % is "
                f"{'simulated' if split.data_quality == 'mock' else 'not yet filled in'} -- "
                f"edit manual_inputs/public_betting_{date_str}.json for a sharper read."
            )

    stats_provider = get_stats_provider()
    team_records = get_all_team_records()
    if not team_records:
        data_warnings.append("Standings unavailable today -- talent gap & motivation factors are running blind.")

    evaluations = []
    for game in games:
        odds = odds_by_game.get(game.game_id)
        if not odds:
            continue
        home_pitcher_profile = stats_provider.get_pitcher_profile(game.home_pitcher.name if game.home_pitcher else None)
        away_pitcher_profile = stats_provider.get_pitcher_profile(game.away_pitcher.name if game.away_pitcher else None)
        home_offense = stats_provider.get_team_offense_profile(game.home_team)
        away_offense = stats_provider.get_team_offense_profile(game.away_team)
        situational = park_and_situational_summary(game.home_team, game.away_team, date_str)
        ev = evaluate_game(
            game, odds, home_pitcher_profile, away_pitcher_profile, home_offense, away_offense,
            team_records.get(game.home_team, {}), team_records.get(game.away_team, {}),
            public_splits.get(game.game_id), situational, run_date=run_date,
        )
        evaluations.append(ev)

    plays, dropped_notes = select_daily_plays(evaluations, db, public_splits, date_str)

    rosters = {}
    situational_by_team = {}
    for game in games:
        for team in (game.home_team, game.away_team):
            if team not in rosters:
                rosters[team] = get_team_batters(team)
                situational_by_team[team] = team_situational_summary(team, date_str)

    hr_props = []
    if config.HR_PROPS_ENABLED:
        hr_props = evaluate_hr_prop_candidates(games, rosters, stats_provider, {}, situational_by_team)

    raw_celestial, _, _ = celestial_signal_for(run_date)
    raw_numerology, _, _ = numerology_signal_for(run_date)
    parlay_pool = get_parlay_pool(evaluations)
    parlay = maybe_build_parlay(parlay_pool, raw_celestial, raw_numerology)

    log_recommendations(db, date_str, plays, hr_props)

    report = DailyReport(
        date=date_str, slate_size=len(games), plays=plays, hr_props=hr_props, parlay=parlay,
        dropped_notes=dropped_notes, celestial=_celestial_dict(run_date),
        numerology=_numerology_dict(run_date), bankroll_summary=bankroll_summary(db),
        data_warnings=data_warnings,
    )
    _emit(report)
    if args.auto:
        auto_gate.mark_published(date_str)


def _celestial_dict(run_date):
    phase, illum = moon_phase_for(run_date)
    return {"phase": phase, "illumination": illum, "sign": moon_sign_for(run_date)}


def _numerology_dict(run_date):
    return {"number": reduce_date(run_date)}


def _emit(report):
    print_daily_report(report)
    path, html = render_daily_report(report)
    logger.info("HTML report written to %s", path)
    publish_result = publish_latest_report(html)
    if publish_result.get("published"):
        logger.info("Live at %s", publish_result["url"])


if __name__ == "__main__":
    main()
