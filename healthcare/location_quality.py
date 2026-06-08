"""
Location data-quality filtering.

A production audit found `healthcare_location` rows with malformed city values
that must not generate public city pages (they render things like
"Botox Prices in Hollywood FL, FL"). Rather than delete rows (providers attach
to them) or add a schema column (no migrations this session), we exclude them at
the QUERY level via a single source of truth used by the cash views and the city
listing.

The precise rule (102 rows in prod) deliberately AVOIDS over-matching. The
original audit regex ` [A-Za-z]{2}$` also caught legitimate cities such as
"Santa Fe, NM" — we do NOT exclude those. Three categories are excluded:

  1. state-doubling   — city ends in a space + 2 letters EQUAL to the state
                        (e.g. "Hollywood FL"/FL, "Auburn Ca"/CA)
  2. street-address   — city starts with a digit ("2500 Alhambra Avenue", "11978")
  3. military APO/FPO  — city starts with APO/FPO/DPO ("Apo Ae", "Fpo Ap")
"""
import re

from django.db.models import F, Q
from django.db.models.functions import Right, Upper

_TWO_LETTER_SUFFIX = re.compile(r' [A-Za-z]{2}$')
_STARTS_DIGIT = re.compile(r'^\s*\d')
_MILITARY = re.compile(r'^\s*(apo|fpo|dpo)[ ,]', re.IGNORECASE)


def is_malformed_location(city, state):
    """Pure-Python predicate — true if this city/state should not get a page."""
    if not city or not city.strip():
        return True
    c = city.strip()
    if _STARTS_DIGIT.match(c):
        return True
    if _MILITARY.match(c):
        return True
    if _TWO_LETTER_SUFFIX.search(c) and state and c[-2:].upper() == state.strip().upper():
        return True
    return False


def exclude_malformed_locations(qs, prefix=''):
    """
    Exclude malformed locations from a queryset.

    For a Location queryset use prefix=''. For a queryset joined to Location use
    e.g. prefix='provider__location__'. Mirrors is_malformed_location() in SQL.
    """
    cf = prefix + 'city'
    sf = prefix + 'state'
    # 1. street address (starts with a digit, allowing leading space)
    qs = qs.exclude(**{cf + '__regex': r'^\s*[0-9]'})
    # 2. military APO/FPO/DPO
    qs = qs.exclude(**{cf + '__iregex': r'^\s*(apo|fpo|dpo)[ ,]'})
    # 3. state-doubling: city ends in ' XX' where XX == state (case-insensitive)
    qs = qs.annotate(
        _city_suffix=Upper(Right(F(cf), 2)),
        _state_up=Upper(F(sf)),
    ).exclude(Q(**{cf + '__iregex': r' [A-Za-z]{2}$'}) & Q(_city_suffix=F('_state_up')))
    return qs
