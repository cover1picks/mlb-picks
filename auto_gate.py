"""
auto_gate.py
=============
Decides WHEN the automatic (cloud) daily run should actually publish a fresh
report, so a single frequent cron schedule (e.g. every 30 min) can still
produce "update ~1 hour before today's first pitch" behavior on both a
noon-start slate and a 6pm-start slate -- without hard-coding either time.

Used by run_daily.py's `--auto` flag (see .github/workflows/daily.yml, which
is what actually calls it on a schedule). A plain `python run_daily.py` with
no `--auto` ignores all of this and just runs immediately, same as always --
this file only changes behavior for the unattended/scheduled path.

How it decides:
  1. Already published today? (data_store/last_published.txt) -> skip.
  2. Otherwise, pull today's schedule and find the EARLIEST game time.
     Target publish time = that time minus AUTO_RUN_LEAD_MINUTES (config.py).
     No games today -> fall back to config.DAILY_RUN_HOUR/MINUTE instead,
     so an off-day still gets a single "no games" report.
  3. If local now (config.TIMEZONE) is at/past the target -> run + publish.
     Otherwise -> skip; the next scheduled check (e.g. 30 min later) will
     re-evaluate. Nothing is lost by checking often -- a skip does almost no
     work (one schedule fetch, no odds/stats/scoring).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config

MARKER_PATH = config.DATA_STORE_DIR / "last_published.txt"


def already_published_today(date_str):
    if not MARKER_PATH.exists():
        return False
    return MARKER_PATH.read_text().strip() == date_str


def mark_published(date_str):
    MARKER_PATH.write_text(date_str)


def _local_now():
    return datetime.now(ZoneInfo(config.TIMEZONE))


def _parse_game_time_utc(iso_str):
    if iso_str.endswith("Z"):
        iso_str = iso_str[:-1] + "+00:00"
    return datetime.fromisoformat(iso_str)


def compute_target_publish_time(run_date, games):
    """Earliest game today minus the configured lead time, in config.TIMEZONE.
    Falls back to the fixed DAILY_RUN_HOUR/MINUTE when there's no schedule to
    anchor to (off day, or a game missing its time)."""
    tz = ZoneInfo(config.TIMEZONE)
    fallback = datetime(run_date.year, run_date.month, run_date.day,
                         config.DAILY_RUN_HOUR, config.DAILY_RUN_MINUTE, tzinfo=tz)

    game_times = [_parse_game_time_utc(g.game_time_utc) for g in games if g.game_time_utc]
    if not game_times:
        return fallback

    earliest_local = min(game_times).astimezone(tz)
    return earliest_local - timedelta(minutes=config.AUTO_RUN_LEAD_MINUTES)


def should_run_now(run_date, date_str, games):
    """Returns (should_run: bool, reason: str)."""
    if already_published_today(date_str):
        return False, f"Already published today's report ({date_str})."

    target = compute_target_publish_time(run_date, games)
    now = _local_now()
    target_str = target.strftime("%-I:%M %p %Z")

    if now >= target:
        return True, f"Publishing now -- past target time of {target_str}."
    return False, f"Not yet time -- will publish at {target_str} (next scheduled check)."
