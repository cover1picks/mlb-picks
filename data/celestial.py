"""
data/celestial.py
==================
Pure-math moon phase + MOON SIGN for a given date. No API needed -- both are
computed directly from a real lunar-position formula, so there's nothing to
scrape and nothing that can go stale.

IMPORTANT: "zodiac" here means the sign the MOON is currently transiting
(what mooncalendar.astro-seek.com and every daily-moon-sign calendar show),
NOT your sun/birth sign. The Moon changes sign every ~2.25 days as it moves
around the whole zodiac in ~27.3 days -- it is NOT the same as the calendar
sun-sign date ranges (Jun 21-Jul 22 = Cancer, etc.) that a birthday horoscope
uses. An earlier version of this file made exactly that mistake (bucketing
by calendar date -> sun sign). Fixed by computing the Moon's real ecliptic
longitude and reading the sign off of that, same underlying astronomy any
moon-sign calendar uses.

The math: `_moon_ecliptic_longitude` is the Meeus "Astronomical Algorithms"
low-precision lunar theory (truncated ELP2000 series) -- a standard, public
formula, accurate to a fraction of a degree. That's precise enough to place
the Moon in the correct 30-degree zodiac slice except within roughly an hour
of an exact sign change, same edge case any source has right at an ingress
moment. Verified against mooncalendar.astro-seek.com for the date this fix
shipped (Moon in Taurus, Jul 9 2026) and several days around it.

The BIAS TABLES below (MOON_PHASE_BIAS, ZODIAC_ELEMENT_BIAS) are what turn
"it's a Full Moon with the Moon in Scorpio" into an actual number the
scoring engine can use. Nobody but you knows your real belief system here,
so these are starting placeholders -- edit them freely. They're
intentionally kept small (see FACTOR_WEIGHTS["moon_zodiac"] in config.py)
so they nudge, not drive, the model.

Signal convention: -1.0 .. +1.0, positive = leans toward the market FAVORITE,
negative = leans toward the market UNDERDOG. engine/scoring.py converts this
onto home/away using the moneyline before it reaches the grading factors.
"""

import math
from datetime import datetime, timezone

SYNODIC_MONTH = 29.53058867
REFERENCE_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)

# Phase name by phase ANGLE (0deg = New, 90 = First Quarter, 180 = Full,
# 270 = Last Quarter). The four PRINCIPAL phases only get a narrow +/-12deg
# window (~1 day) around their exact instant; everything else is a
# crescent/gibbous. An earlier version gave the principal phases a huge
# +-0.0625-of-cycle (~1.85 day) band, which mislabeled e.g. an 8.5-day-old
# 62%-illuminated Moon (clearly Waxing Gibbous) as "First Quarter". This
# matches moongiant / theskylive / astro-seek day labels.
PRINCIPAL_HALF_WINDOW = 12.0   # degrees on each side of 0/90/180/270
MOON_PHASE_ANGLE_BANDS = [
    (12.0,  "New Moon"),          # 348..360 wraps to here too (handled in code)
    (78.0,  "Waxing Crescent"),
    (102.0, "First Quarter"),
    (168.0, "Waxing Gibbous"),
    (192.0, "Full Moon"),
    (258.0, "Waning Gibbous"),
    (282.0, "Last Quarter"),
    (348.0, "Waning Crescent"),
    (360.0, "New Moon"),
]

# EDIT ME: your real read on how each phase should lean.
MOON_PHASE_BIAS = {
    "New Moon": 0.25,          # fresh-start energy -> favors the favorite / chalk
    "Waxing Crescent": 0.1,
    "First Quarter": 0.0,
    "Waxing Gibbous": -0.1,
    "Full Moon": -0.3,         # folklore: chaos/upsets peak at full moon
    "Waning Gibbous": -0.1,
    "Last Quarter": 0.0,
    "Waning Crescent": 0.15,
}

# Tropical zodiac slices, 30 degrees of ecliptic longitude each, starting at
# the vernal equinox point (0 deg = Aries). This is astronomical geometry,
# not a calendar table -- which sign the Moon is "in" depends on where it
# actually is along this ring, not what today's date is.
ZODIAC_SIGN_ORDER = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

ZODIAC_ELEMENT = {
    "Aries": "fire", "Leo": "fire", "Sagittarius": "fire",
    "Taurus": "earth", "Virgo": "earth", "Capricorn": "earth",
    "Gemini": "air", "Libra": "air", "Aquarius": "air",
    "Cancer": "water", "Scorpio": "water", "Pisces": "water",
}

# EDIT ME: your real read on how each element should lean.
ZODIAC_ELEMENT_BIAS = {
    "fire": 0.2,     # aggressive energy -> favors the favorite
    "earth": 0.15,   # steady energy -> mildly favors the favorite
    "air": -0.05,    # unpredictable -> mild lean underdog
    "water": -0.2,   # emotional/volatile -> favors the underdog / upset
}


def moon_phase_for(d):
    """Returns (phase_name, illumination_fraction 0..1) for date `d`."""
    dt = datetime(d.year, d.month, d.day, 12, 0, tzinfo=timezone.utc)
    days_since = (dt - REFERENCE_NEW_MOON).total_seconds() / 86400.0
    phase_frac = (days_since % SYNODIC_MONTH) / SYNODIC_MONTH  # 0..1 (0 = new, 0.5 = full)
    illumination = (1 - math.cos(2 * math.pi * phase_frac)) / 2
    angle = phase_frac * 360.0
    for upper, name in MOON_PHASE_ANGLE_BANDS:
        if angle < upper:
            return name, round(illumination, 3)
    return "New Moon", round(illumination, 3)


def _julian_day(y, m, d, hour=12.0):
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + hour / 24.0 + b - 1524.5


def _norm_deg(deg):
    return deg % 360.0


def moon_ecliptic_longitude(d):
    """Geocentric ecliptic longitude of the Moon (0-360 deg) at 12:00 UTC on
    date `d`, via Meeus' low-precision lunar theory (truncated ELP2000
    series -- the top ~20 amplitude terms). Accurate to a fraction of a
    degree, which is all that's needed to place it in the right 30-degree
    zodiac slice."""
    jd = _julian_day(d.year, d.month, d.day, 12.0)
    t = (jd - 2451545.0) / 36525.0  # Julian centuries since J2000.0

    Lp = _norm_deg(218.3164477 + 481267.88123421 * t - 0.0015786 * t**2 + t**3 / 538841 - t**4 / 65194000)
    D = _norm_deg(297.8501921 + 445267.1114034 * t - 0.0018819 * t**2 + t**3 / 545868 - t**4 / 113065000)
    M = _norm_deg(357.5291092 + 35999.0502909 * t - 0.0001536 * t**2 + t**3 / 24490000)
    Mp = _norm_deg(134.9633964 + 477198.8675055 * t + 0.0087414 * t**2 + t**3 / 69699 - t**4 / 14712000)
    F = _norm_deg(93.2720950 + 483202.0175233 * t - 0.0036539 * t**2 - t**3 / 3526000 + t**4 / 863310000)

    d_, m_, mp_, f_ = math.radians(D), math.radians(M), math.radians(Mp), math.radians(F)

    delta_l = (
        6.288774 * math.sin(mp_)
        + 1.274027 * math.sin(2 * d_ - mp_)
        + 0.658314 * math.sin(2 * d_)
        + 0.213618 * math.sin(2 * mp_)
        - 0.185116 * math.sin(m_)
        - 0.114332 * math.sin(2 * f_)
        + 0.058793 * math.sin(2 * d_ - 2 * mp_)
        + 0.057066 * math.sin(2 * d_ - m_ - mp_)
        + 0.053322 * math.sin(2 * d_ + mp_)
        + 0.045758 * math.sin(2 * d_ - m_)
        - 0.040923 * math.sin(m_ - mp_)
        - 0.034720 * math.sin(d_)
        - 0.030383 * math.sin(m_ + mp_)
        + 0.015327 * math.sin(2 * d_ - 2 * f_)
        - 0.012528 * math.sin(mp_ + 2 * f_)
        + 0.010980 * math.sin(mp_ - 2 * f_)
        + 0.010675 * math.sin(4 * d_ - mp_)
        + 0.010034 * math.sin(3 * mp_)
        + 0.008548 * math.sin(4 * d_ - 2 * mp_)
        - 0.007888 * math.sin(2 * d_ + m_ - mp_)
    )

    return _norm_deg(Lp + delta_l)


def moon_sign_for(d):
    """The zodiac sign the MOON is currently transiting on date `d` (not the
    sun-sign for the calendar date -- see module docstring)."""
    longitude = moon_ecliptic_longitude(d)
    return ZODIAC_SIGN_ORDER[int(longitude // 30) % 12]


def celestial_signal_for(d):
    """Single -1..+1 signal blending moon phase (60%) + Moon-sign element (40%)."""
    phase_name, illum = moon_phase_for(d)
    sign = moon_sign_for(d)
    element = ZODIAC_ELEMENT[sign]
    moon_bias = MOON_PHASE_BIAS.get(phase_name, 0.0)
    element_bias = ZODIAC_ELEMENT_BIAS.get(element, 0.0)
    signal = max(-1.0, min(1.0, 0.6 * moon_bias + 0.4 * element_bias))
    reasoning = (f"{phase_name} ({illum:.0%} illuminated), Moon in {sign} ({element} sign) -> "
                 f"{'favorite' if signal > 0 else 'underdog'} lean")
    return signal, reasoning, {"phase": phase_name, "illumination": illum, "sign": sign, "element": element}
