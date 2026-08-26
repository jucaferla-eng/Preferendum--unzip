"""
matching_diagnostics.py — CHANGE-002 Phase 2 read-only diagnostics.

Two questions JC needs answered BEFORE deploy, neither of which may be
answered by guessing or by writing to production:

  1. Is any country's market thermometer actually holding a NOMINAL GDP per
     capita figure where PPP/PPA is required? (`classify_ppp_row`)

  2. Which campaign/consultation rows carry ambiguous legacy income targeting,
     and can the original unit be PROVEN from authoritative data?
     (`classify_income_row`)

Stdlib only, pure functions over plain values, so both the admin endpoints and
the offline impact simulation share exactly one implementation and it is unit
testable without a database.

NOTHING HERE WRITES. Every function returns a report.
"""

from __future__ import annotations

from typing import Any, Optional

# ═══════════════════════════════════════════════════════════════════════
# 1. PPP vs NOMINAL
# ═══════════════════════════════════════════════════════════════════════

PPP_OK = 'ppp_ok'
PPP_SUSPECTED_NOMINAL = 'suspected_nominal'
PPP_MISSING = 'missing'
PPP_NO_REFERENCE = 'no_reference'

# For most countries PPP per capita EXCEEDS nominal, often by 2-3x (India
# ~3x, Nigeria ~2.5x, Brazil ~1.6x). A stored value far BELOW the known PPP
# reference is therefore the signature of a nominal figure having been loaded
# into the column.
#
# 0.70 is deliberately permissive: World Bank vintages differ year to year by
# well under 30%, so a value inside 70-130% of the 2023 reference is normal
# drift, while anything under 70% is the shape of a unit error. This flags for
# REVIEW; it never rewrites data and never changes an eligibility decision.
NOMINAL_SUSPICION_RATIO = 0.70


def classify_ppp_row(iso2: str, stored_value, reference_value) -> dict:
    """Classify one country's market-thermometer value.

    Returns a report dict; never mutates anything.
    """
    out = {
        'iso2': iso2,
        'stored': stored_value,
        'reference_ppp': reference_value,
        'ratio': None,
        'status': PPP_MISSING,
        'note': '',
    }
    if stored_value is None:
        out['note'] = ('no value stored; the resolver falls back to the PPP '
                       'reference table, so eligibility still uses PPP')
        if reference_value is None:
            out['status'] = PPP_NO_REFERENCE
            out['note'] = ('no stored value AND no PPP reference; the market '
                           'threshold resolves to UNKNOWN, which DENIES')
        return out
    if reference_value is None:
        out['status'] = PPP_NO_REFERENCE
        out['note'] = ('stored value cannot be cross-checked: country absent '
                       'from the PPP reference table')
        return out
    try:
        ratio = float(stored_value) / float(reference_value)
    except (TypeError, ValueError, ZeroDivisionError):
        out['status'] = PPP_NO_REFERENCE
        out['note'] = 'stored or reference value not numeric'
        return out
    out['ratio'] = round(ratio, 3)
    if ratio < NOMINAL_SUSPICION_RATIO:
        out['status'] = PPP_SUSPECTED_NOMINAL
        out['note'] = (f'stored value is {ratio:.0%} of the known PPP reference — '
                       'consistent with a NOMINAL GDP per-capita figure having '
                       'been loaded into this column. Requires review before '
                       'relying on market thresholds for this country.')
    else:
        out['status'] = PPP_OK
        out['note'] = 'consistent with the PPP reference (normal vintage drift)'
    return out


def ppp_audit(stored_by_iso: dict, reference_by_iso: dict) -> dict:
    """Full PPP audit over every country in either source."""
    isos = sorted(set(stored_by_iso) | set(k for k in reference_by_iso if k != 'default'))
    rows = [classify_ppp_row(i, stored_by_iso.get(i), reference_by_iso.get(i)) for i in isos]
    counts = {}
    for r in rows:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    return {
        'total_countries': len(rows),
        'counts': counts,
        'requires_review': [r for r in rows if r['status'] == PPP_SUSPECTED_NOMINAL],
        'rows': rows,
    }


# ═══════════════════════════════════════════════════════════════════════
# 2. AMBIGUOUS LEGACY INCOME TARGETING
# ═══════════════════════════════════════════════════════════════════════

INCOME_NOT_TARGETED = 'not_targeted'
INCOME_INDEX_DOMAIN = 'ambiguous_index_domain'
INCOME_USD_DOMAIN = 'usd_domain'
INCOME_REQUIRES_REVIEW = 'requires_review'

# ad_campaigns documents these as an index (0-9999) but the only code that
# ever read them compared against annual USD. Bounds inside the index domain
# are therefore unprovable without knowing the advertiser's intent.
INDEX_DOMAIN_CEILING = 9999.0

# Schema defaults meaning "no income targeting at all".
DEFAULT_MIN = 0.0
DEFAULT_MAX = 9999.0


def classify_income_row(row_id, lo, hi, *, kind='campaign', label='') -> dict:
    """Classify one row's income targeting WITHOUT guessing its unit.

    We never decide that an old value "means" index / annual USD / monthly /
    PPP. We report only what is provable from the value itself:

      * both bounds at their schema defaults -> not targeted at all
      * any bound above the index ceiling    -> can only be a currency amount
      * otherwise                            -> ambiguous, requires review
    """
    out = {
        'kind': kind,
        'id': row_id,
        'label': label,
        'min': lo,
        'max': hi,
        'status': INCOME_NOT_TARGETED,
        'evidence': '',
        'action': '',
    }

    def _num(v):
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    lo_f, hi_f = _num(lo), _num(hi)

    lo_set = lo_f is not None and lo_f > DEFAULT_MIN
    hi_set = hi_f is not None and hi_f != DEFAULT_MAX and hi_f > 0

    if not lo_set and not hi_set:
        out['evidence'] = 'both bounds at schema defaults'
        out['action'] = 'none — income is not targeted on this row'
        return out

    bounds = [b for b in (lo_f if lo_set else None, hi_f if hi_set else None) if b is not None]

    if max(bounds) > INDEX_DOMAIN_CEILING:
        out['status'] = INCOME_USD_DOMAIN
        out['evidence'] = (f'bound {max(bounds):,.0f} exceeds the documented index '
                           f'ceiling {INDEX_DOMAIN_CEILING:,.0f}, so it cannot be an '
                           'index value')
        out['action'] = ('evaluated against annual USD estimated income; consider '
                         're-expressing as a socioeconomic tier (rule 8)')
        return out

    out['status'] = INCOME_INDEX_DOMAIN
    out['evidence'] = (f'bounds [{lo}, {hi}] sit entirely inside the documented '
                       f'index domain (0-{INDEX_DOMAIN_CEILING:,.0f}); the schema '
                       'calls this an index while the only live comparison was '
                       'against annual USD. The original unit is NOT provable '
                       'from the stored value.')
    out['action'] = ('REQUIRES REVIEW before deploy. Eligibility currently '
                     'resolves to UNRESOLVED (denies, and is reported) rather '
                     'than silently reinterpreting the value. Re-express the '
                     'intent as a socioeconomic tier A/B/C/D.')
    return out


def income_audit(rows) -> dict:
    """rows: iterable of (kind, id, label, min, max)."""
    reports = [classify_income_row(rid, lo, hi, kind=kind, label=label)
               for kind, rid, label, lo, hi in rows]
    counts = {}
    for r in reports:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    return {
        'total_rows': len(reports),
        'counts': counts,
        'requires_review': [r for r in reports if r['status'] == INCOME_INDEX_DOMAIN],
        'rows': reports,
    }
