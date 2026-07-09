"""
engine/parlay.py
=================
Optional small parlay (config.PARLAY_MIN_LEGS..PARLAY_MAX_LEGS legs), built
ONLY from plays that already independently cleared MIN_EDGE on their own,
and only surfaced when the day's combined moon+numerology signal is a clear
"green light". Most days this returns None -- that's by design ("optional...
when moon/numerology supports it"), not a bug.
"""

import config
from engine.models import ParlayRecommendation

GREEN_LIGHT_THRESHOLD = 0.35  # avg |signal| across celestial+numerology must clear this


def maybe_build_parlay(plays, celestial_signal, numerology_signal):
    if not config.PARLAY_ENABLED:
        return None
    if len(plays) < config.PARLAY_MIN_LEGS:
        return None  # simply not enough independently-qualified legs today

    combined_energy = (abs(celestial_signal) + abs(numerology_signal)) / 2
    if combined_energy < GREEN_LIGHT_THRESHOLD:
        return None  # no green light today -- straight plays only

    legs = plays[: config.PARLAY_MAX_LEGS]
    combined_prob = 1.0
    combined_decimal_odds = 1.0
    for leg in legs:
        combined_prob *= leg.model_prob
        combined_decimal_odds *= _american_to_decimal(leg.odds_american)

    combined_american = _decimal_to_american(combined_decimal_odds)
    reasoning = (f"Moon/numerology green light today (combined energy {combined_energy:.2f} >= "
                 f"{GREEN_LIGHT_THRESHOLD}) -- every leg already clears MIN_EDGE on its own; "
                 f"this parlay is a bonus, not a substitute for the straight plays.")

    return ParlayRecommendation(
        legs=legs, combined_odds_american=combined_american,
        combined_prob=combined_prob, stake_units=config.FLAT_STAKE_UNITS,
        reasoning=reasoning,
    )


def _american_to_decimal(ml):
    ml = float(ml)
    return 1 + (ml / 100.0 if ml > 0 else 100.0 / -ml)


def _decimal_to_american(decimal_odds):
    if decimal_odds >= 2.0:
        return round((decimal_odds - 1) * 100)
    return round(-100 / (decimal_odds - 1))
