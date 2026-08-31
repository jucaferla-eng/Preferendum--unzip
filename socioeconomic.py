"""
socioeconomic.py — CHANGE-003 canonical socioeconomic classification.

CHANGE-002 built the canonical MATCHING evaluator (eligibility.py). It can only
be as accurate as the socioeconomic data it consumes. This module produces that
data, and like eligibility.py it is deliberately DEPENDENCY-FREE: pure functions
over plain values, no fastapi, no sqlalchemy, no database. Adapters in main.py
translate ORM rows into these snapshots.

═══════════════════════════════════════════════════════════════════════
THE RULES THIS MODULE ENCODES  (JC, CHANGE-003)
═══════════════════════════════════════════════════════════════════════

R1. INCOME IS THE PRIMARY A/B/C/D SIGNAL.
    Occupation, job title and company size are a PROFESSIONAL PROFILE. They
    describe what someone does, not what they earn. They may never promote a
    person above the tier their KNOWN income supports.

R2. A/B/C/D IS A POSITION IN THE LOCAL MARKET.
    The same USD income is a different socioeconomic position in Santiago and
    in Zurich, so the tier is computed RELATIVE to the person's own country.

R3. COUNTRY PURCHASING POWER IS A SEPARATE, PRESERVED DIMENSION.
    Tier does not absorb it. A global campaign can ask for
    "PPP per capita >= 5,000 AND tier = A" precisely because the two numbers
    stay distinct. Collapsing them into one opaque score would destroy that.

R4. THE COUNTRY THERMOMETER IS PPP/PPA PER CAPITA — NEVER NOMINAL GDP.
    This module will not accept a figure that is not declared PPP. See
    CountryEconomicContext and the PPP_* provenance constants.

R5. INDIVIDUAL AND HOUSEHOLD INCOME ARE DIFFERENT THINGS.
    Individual income drives the tier. Household income is its own targeting
    dimension and is NEVER silently substituted for the individual figure.

R6. DECLARED BEATS ESTIMATED.
    A statistical estimate must never overwrite a recently confirmed real
    income. Precedence is explicit and testable (see IncomeSource).

R7. MISSING DATA STAYS MISSING.
    Unknown company size is UNKNOWN, not "small". An unresolvable tier is
    UNRESOLVED, and CHANGE-002 already treats UNKNOWN as denying. Nothing here
    invents an economic value to make a decision possible.

R8. NOTHING IS DESTROYED BY NORMALIZATION.
    The original declared amount, currency and period are preserved alongside
    the normalized figure.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Optional

# Policy version. Bump when a threshold or rule below changes, so a stored
# classification can always be traced to the rules that produced it.
POLICY_VERSION = 'change-003.v1'


# ═══════════════════════════════════════════════════════════════════════
# VERDICTS
# ═══════════════════════════════════════════════════════════════════════

RESOLVED = 'resolved'
UNRESOLVED = 'unresolved'

TIERS = ('A', 'B', 'C', 'D')
_TIER_INDEX = {t: i for i, t in enumerate(('D', 'C', 'B', 'A'))}   # D=0 … A=3


def tier_index(t: Any) -> int:
    """0..3 with D lowest. Returns -1 for an unknown/empty tier.

    NOTE the deliberate single indexing scheme. main.py historically carried
    TWO: `_tier_rank` returning A=4..D=1 (1-based) alongside a 0-indexed
    `tier_ladder = ['D','C','B','A']`. Mixing them made the age adjustment
    promote C->A and D->B — two tiers, from age alone. One scheme, one place.
    """
    return _TIER_INDEX.get(_norm_tier(t), -1)


def _norm_tier(t: Any) -> str:
    s = (str(t) if t is not None else '').strip().upper()
    return s[:1] if s[:1] in _TIER_INDEX else ''


def tier_from_index(i: int) -> str:
    return ('D', 'C', 'B', 'A')[max(0, min(int(i), 3))]


# ═══════════════════════════════════════════════════════════════════════
# INCOME PROVENANCE AND PRECEDENCE  (R6)
# ═══════════════════════════════════════════════════════════════════════

# Higher rank wins. A source may only overwrite a stored value of STRICTLY
# LOWER rank, or the same rank when the new observation is newer.
DECLARED_CONFIRMED = 'declared_confirmed'
DECLARED = 'declared'
ESTIMATED_OCCUPATION = 'estimated_occupation'
ESTIMATED_COMMUNE = 'estimated_commune'
ESTIMATED_COUNTRY = 'estimated_country'

_SOURCE_RANK = {
    DECLARED_CONFIRMED:   50,
    DECLARED:             40,
    ESTIMATED_OCCUPATION: 30,
    ESTIMATED_COMMUNE:    20,
    ESTIMATED_COUNTRY:    10,
}

ESTIMATED_SOURCES = frozenset(
    {ESTIMATED_OCCUPATION, ESTIMATED_COMMUNE, ESTIMATED_COUNTRY})
DECLARED_SOURCES = frozenset({DECLARED_CONFIRMED, DECLARED})


def source_rank(source: Any) -> int:
    return _SOURCE_RANK.get(source, 0)


def is_estimate(source: Any) -> bool:
    return source in ESTIMATED_SOURCES


def may_overwrite(existing_source: Any, existing_asof: Any,
                  new_source: Any, new_asof: Any) -> bool:
    """R6: may a new observation replace the stored one?

    An ESTIMATE MAY NEVER REPLACE A DECLARED FIGURE — that is the whole point
    of the rule. Same-rank replacement is allowed only when strictly newer, so
    re-running the estimator does not churn a stored value.
    """
    if existing_source is None:
        return True
    er, nr = source_rank(existing_source), source_rank(new_source)
    if nr > er:
        return True
    if nr < er:
        return False
    if existing_asof is None:
        return True
    if new_asof is None:
        return False
    return new_asof > existing_asof


# ═══════════════════════════════════════════════════════════════════════
# INCOME REPRESENTATION  (R8 — normalize without destroying)
# ═══════════════════════════════════════════════════════════════════════

PERIOD_ANNUAL = 'annual'
PERIOD_MONTHLY = 'monthly'
PERIOD_WEEKLY = 'weekly'
PERIOD_DAILY = 'daily'
PERIOD_HOURLY = 'hourly'

# Multipliers to ANNUAL. Hourly/daily/weekly use conventional full-time
# equivalences; they are declared here rather than scattered as magic numbers.
_PERIOD_TO_ANNUAL = {
    PERIOD_ANNUAL:  1.0,
    PERIOD_MONTHLY: 12.0,
    PERIOD_WEEKLY:  52.0,
    PERIOD_DAILY:   260.0,     # 52 weeks x 5 working days
    PERIOD_HOURLY:  2080.0,    # 40 h/week x 52
}


def normalize_period(v: Any) -> str:
    s = (str(v) if v is not None else '').strip().lower()
    if s in _PERIOD_TO_ANNUAL:
        return s
    aliases = {
        'year': PERIOD_ANNUAL, 'yr': PERIOD_ANNUAL, 'anual': PERIOD_ANNUAL,
        'ano': PERIOD_ANNUAL, 'año': PERIOD_ANNUAL, 'yearly': PERIOD_ANNUAL,
        'month': PERIOD_MONTHLY, 'mo': PERIOD_MONTHLY, 'mensual': PERIOD_MONTHLY,
        'mes': PERIOD_MONTHLY, 'monthly': PERIOD_MONTHLY,
        'week': PERIOD_WEEKLY, 'semanal': PERIOD_WEEKLY,
        'day': PERIOD_DAILY, 'diario': PERIOD_DAILY,
        'hour': PERIOD_HOURLY, 'hr': PERIOD_HOURLY, 'hora': PERIOD_HOURLY,
    }
    return aliases.get(s, '')


# Public, canonical form for callers (e.g. main.py's income-declaration
# routes) that need to tell a caller which period values are accepted,
# without reaching into the private _PERIOD_TO_ANNUAL mapping.
ACCEPTED_PERIODS = tuple(sorted(_PERIOD_TO_ANNUAL))


class IncomeObservation:
    """One income figure, with everything needed to audit it later.

    The ORIGINAL declaration is kept verbatim (`amount`, `currency`, `period`,
    and for a band `amount_max`). `annual_usd` is a DERIVED convenience. R8:
    normalization adds a field, it never replaces the source of truth.

    CHANGE-003 remediation B1: `currency` and `period` are NEVER defaulted to
    a specific value when the caller does not supply one. A prior version
    defaulted a missing currency to 'USD' — including when a caller explicitly
    passed '' — so a user row with a blank `declared_income_currency` column
    (the column's own SQL default) was silently priced as USD. A $20,000,000
    figure with no currency attached is not "$20,000,000 USD"; it is unknown,
    and R7 says unknown data stays unknown rather than being guessed into a
    tier. The same applies to `period`: an unrecognised period string must not
    silently become 'annual'.

    A caller that means USD must say so explicitly (`currency='USD'`). There
    is no country-implied-currency rule anywhere in this codebase, and this
    module does not invent one (an approved business rule would have to
    define that mapping explicitly, elsewhere).
    """

    __slots__ = ('amount', 'amount_max', 'currency', 'period', 'source',
                 'as_of', 'country', 'fx_rate_to_usd', 'note')

    def __init__(self, amount=None, currency=None, period=None,
                 source=DECLARED, as_of=None, country='', amount_max=None,
                 fx_rate_to_usd=None, note=''):
        self.amount = amount
        self.amount_max = amount_max        # set => the declaration was a RANGE
        # '' means UNKNOWN. Never coerced to 'USD' — see class docstring (B1).
        self.currency = (currency or '').strip().upper()
        # '' means UNRECOGNISED. Never coerced to 'annual' — normalize_period
        # itself returns '' (not a fallback) for anything it cannot
        # positively identify, including None.
        self.period = normalize_period(period)
        self.source = source
        self.as_of = as_of                  # date/datetime/ISO string
        self.country = country
        self.fx_rate_to_usd = fx_rate_to_usd
        self.note = note

    @property
    def is_range(self) -> bool:
        return self.amount_max is not None

    @property
    def is_declared(self) -> bool:
        return self.source in DECLARED_SOURCES

    def _num(self, v):
        """A finite float, or None.

        Remediation (re-audit finding): NaN and +/-Infinity used to pass
        through here — `nan <= 0` and `nan > 0` are both False, so the
        `if not rate or rate <= 0` guard in annual_usd never caught a NaN
        fx_rate_to_usd, and the resulting NaN annual_usd was *resolved* by
        tier_from_income into tier 'D' (ratio=nan) instead of UNRESOLVED, for
        BOTH the amount and the FX rate this method feeds. A non-finite
        number is not a number the platform actually knows — same principle
        as a blank currency (R7): stays unusable, never silently coerced
        into a decision.
        """
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if math.isfinite(f) else None

    @property
    def representative_amount(self) -> Optional[float]:
        """For a band, the MIDPOINT — chosen because it is the least
        favourable-to-nobody reading. Using the top of a band would inflate
        every ranged declaration into a higher tier."""
        lo, hi = self._num(self.amount), self._num(self.amount_max)
        if lo is None:
            return hi
        if hi is None:
            return lo
        return (lo + hi) / 2.0

    @property
    def annual_usd(self) -> Optional[float]:
        """Normalized annual USD, or None when it cannot be computed.

        B1: a BLANK currency (unset, whitespace-only, or explicitly '') is
        UNKNOWN, never USD — checked before anything else so a stray
        fx_rate_to_usd attached to an unknown currency cannot smuggle a
        number through either. An unrecognised period (`self.period == ''`)
        fails the same way via the `_PERIOD_TO_ANNUAL` lookup below. A
        non-USD amount without a positive FX rate also returns None rather
        than being silently treated as USD — that would be inventing
        economic data (R7).
        """
        if not self.currency:
            return None
        amt = self.representative_amount
        if amt is None:
            return None
        mult = _PERIOD_TO_ANNUAL.get(self.period)
        if mult is None:
            return None
        if self.currency != 'USD':
            rate = self._num(self.fx_rate_to_usd)
            if not rate or rate <= 0:
                return None
            amt = amt * rate
        return amt * mult

    def as_dict(self) -> dict:
        d = {s: getattr(self, s) for s in self.__slots__}
        d['annual_usd'] = self.annual_usd
        d['is_range'] = self.is_range
        return d

    def __repr__(self) -> str:   # pragma: no cover - debugging aid
        return (f'<Income {self.amount}{"-" + str(self.amount_max) if self.is_range else ""} '
                f'{self.currency}/{self.period} src={self.source} annual_usd={self.annual_usd}>')


# ═══════════════════════════════════════════════════════════════════════
# COUNTRY ECONOMIC CONTEXT  (R3, R4)
# ═══════════════════════════════════════════════════════════════════════

PPP_SOURCE_REQUIRED = (
    'PPP/PPA per capita only (e.g. World Bank NY.GNP.PCAP.PP.CD). '
    'Nominal GDP per capita is NOT acceptable.')

# Accepted provenance labels for a PPP figure. A value whose provenance is not
# in this set is REFUSED — this is the guard against the CHANGE-002-era bug
# where nominal GDP was read into a PPP-typed slot.
PPP_ACCEPTED_SOURCES = frozenset({
    'world_bank_ny_gnp_pcap_pp_cd',
    'marketer_table_v2_gni_per_capita_ppp',
    'test_fixture_ppp',
})

# Explicitly REFUSED provenance labels. Named so that a future caller wiring a
# nominal series in gets a loud failure instead of a silently wrong tier.
PPP_REFUSED_SOURCES = frozenset({
    'world_bank_ny_gdp_pcap_cd',
    'nominal_gdp_per_capita',
    'nominal',
})

# Ratio used ONLY when a country has no measured median personal income.
# GNI per capita counts corporate profit and government spending, so median
# PERSONAL income is materially lower. 0.50 is the working assumption the
# platform already used; what changes here is that it is (a) applied to a
# figure we have verified is PPP, and (b) flagged `derived=True` so a
# classification built on it is auditable as an assumption rather than a
# measurement.
DERIVED_MEDIAN_FROM_PPP_RATIO = 0.50


class CountryEconomicContext:
    """A country's economic anchor. PPP per capita is mandatory and typed.

    `median_personal_income_usd` is preferred when measured. When absent it is
    DERIVED from PPP and marked as such, so `derived_median` travels with every
    decision that relied on it.
    """

    __slots__ = ('country', 'ppp_per_capita_usd', 'ppp_source', 'ppp_year',
                 'median_personal_income_usd', 'median_source', 'median_year',
                 'derived_median', 'rejected_reason')

    def __init__(self, country='', ppp_per_capita_usd=None, ppp_source='',
                 ppp_year=None, median_personal_income_usd=None,
                 median_source='', median_year=None):
        self.country = (country or '').strip().upper()
        self.ppp_source = ppp_source
        self.ppp_year = ppp_year
        self.median_source = median_source
        self.median_year = median_year
        self.rejected_reason = ''

        ppp = self._num(ppp_per_capita_usd)
        # R4: refuse anything not positively identified as PPP.
        if ppp is not None and ppp_source in PPP_REFUSED_SOURCES:
            self.rejected_reason = (
                f'refused PPP source {ppp_source!r}: {PPP_SOURCE_REQUIRED}')
            ppp = None
        elif ppp is not None and ppp_source not in PPP_ACCEPTED_SOURCES:
            self.rejected_reason = (
                f'unrecognised PPP provenance {ppp_source!r}; '
                f'{PPP_SOURCE_REQUIRED}')
            ppp = None
        elif ppp is not None and ppp <= 0:
            self.rejected_reason = 'PPP per capita must be positive'
            ppp = None
        self.ppp_per_capita_usd = ppp

        med = self._num(median_personal_income_usd)
        if med is not None and med > 0:
            self.median_personal_income_usd = med
            self.derived_median = False
        elif self.ppp_per_capita_usd is not None:
            self.median_personal_income_usd = (
                self.ppp_per_capita_usd * DERIVED_MEDIAN_FROM_PPP_RATIO)
            self.derived_median = True
        else:
            self.median_personal_income_usd = None
            self.derived_median = False

    @staticmethod
    def _num(v):
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    @property
    def resolved(self) -> bool:
        return self.median_personal_income_usd is not None

    def as_dict(self) -> dict:
        return {s: getattr(self, s) for s in self.__slots__}

    def __repr__(self) -> str:   # pragma: no cover
        return (f'<CountryEconomicContext {self.country} '
                f'ppp={self.ppp_per_capita_usd} median={self.median_personal_income_usd} '
                f'derived={self.derived_median}>')


# ═══════════════════════════════════════════════════════════════════════
# A/B/C/D FROM INCOME  (R1, R2)
# ═══════════════════════════════════════════════════════════════════════

# Tier boundaries as MULTIPLES OF THE COUNTRY'S MEDIAN PERSONAL INCOME.
# Country-relative by construction (R2): the same USD figure lands in a
# different tier in a different market, which is what A/B/C/D is supposed to
# express. Ordered high -> low; first match wins.
#
# ═══════════════════════════════════════════════════════════════════════
# PROVISIONAL — NOT YET APPROVED BY BUSINESS (JC)
# ═══════════════════════════════════════════════════════════════════════
# These specific multiples (3.0x / 1.5x / 0.7x) were chosen by the
# implementer to make the CORRECTED mechanism (income-relative-to-local-
# median, no promotion by age/title/company) testable end to end. They are
# NOT a business decision JC has signed off on. Do not treat a passing test
# suite as approval of these numbers — the tests verify the MECHANISM
# (declared beats estimated, no promotion, PPP never nominal, etc.), not
# that 3.0x specifically is the right cut for tier A.
#
# THIS IS THE ONLY PLACE these numbers are defined. `tier_from_income` reads
# them from here and nowhere else; nothing else in this codebase restates
# them. Changing the actual boundaries requires editing exactly this tuple
# AND bumping POLICY_VERSION, so every stored Classification.policy_version
# stays traceable to the exact rules that produced it.
#
# THRESHOLDS_APPROVED_BY_BUSINESS below travels with every classification
# and every impact report specifically so nothing downstream can present
# these numbers as final without that travelling alongside them. Flip it to
# True (and bump POLICY_VERSION) only once JC has actually approved the
# bands — never as a drive-by edit alongside an unrelated change.
TIER_BANDS = (
    ('A', 3.00),
    ('B', 1.50),
    ('C', 0.70),
    ('D', 0.00),
)

THRESHOLDS_APPROVED_BY_BUSINESS = False


def tier_from_income(annual_usd, context: CountryEconomicContext):
    """THE tier decision. Income in, tier out. Nothing else participates.

    Returns (tier, ratio) or (None, None) when it cannot be decided — the
    caller surfaces that as UNRESOLVED rather than guessing (R7).
    """
    if context is None or not context.resolved:
        return None, None
    try:
        income = float(annual_usd)
    except (TypeError, ValueError):
        return None, None
    if income < 0:
        return None, None
    median = context.median_personal_income_usd
    if not median or median <= 0:
        return None, None
    ratio = income / median
    for tier, floor in TIER_BANDS:
        if ratio >= floor:
            return tier, ratio
    return 'D', ratio


# ═══════════════════════════════════════════════════════════════════════
# AGE / OCCUPATION INCOME PROGRESSION  (R1 — adjusts INCOME, never the tier)
# ═══════════════════════════════════════════════════════════════════════

# Career earnings curve, indexed to the 35-44 peak = 1.00. Applied ONLY to an
# occupational ESTIMATE, to answer "engineer at 24 vs engineer at 30".
#
# It multiplies an estimated INCOME. It never touches the tier directly. The
# previous implementation shifted the TIER by age (and, through a 1-based rank
# indexed into a 0-based ladder, promoted C->A and D->B on age alone). Age is
# an input to an income estimate; it is not a socioeconomic class.
#
# PROVENANCE (FINAL SOCIOECONOMIC ASSIGNMENT HARDENING Phase 5 audit) — these
# exact bracket boundaries and multiplier values (0.55/0.72/0.87/1.00/1.08/
# 1.05/0.85) are an APPROVED, PRE-EXISTING Preferendum business rule, not
# copied or invented by CHANGE-003 or this hardening pass: they were authored
# by this project a month before CHANGE-003 existed (commit 89254eb5,
# "Complete income estimation system: company size + age multipliers +
# low-GDP logic", 2026-07-27) and CHANGE-003 (37ca88b9) carried them forward
# byte-for-byte when it moved them from main.py into this canonical module
# (see TestNoPromotionWiring.test_income_estimate_multipliers_have_exactly_
# one_implementation in test_socioeconomic_wiring.py). No commit, docstring,
# or comment anywhere in this repository's history cites a specific external
# dataset (BLS, Census, ILO, or otherwise) for these particular numbers — do
# not present them as such. The general SHAPE (rising to a mid-career peak,
# a gentle plateau and decline approaching typical retirement age) matches
# widely-documented general age-earnings patterns in labor economics, but
# the specific multiplier values here are this project's own approximation
# of that shape, not a citation. Preserved as-is (an approved existing
# business rule), documented as exactly that — not external empirical
# evidence — per this hardening task's explicit instruction.
AGE_INCOME_CURVE = (
    ((0, 24), 0.55),
    ((25, 29), 0.72),
    ((30, 34), 0.87),
    ((35, 44), 1.00),
    ((45, 54), 1.08),
    ((55, 64), 1.05),
    ((65, 200), 0.85),
)

# Company size affects PAY for the same role (a finance manager at an
# IBM-scale employer out-earns one at a 5-person firm). It is applied to the
# estimate, never as a tier promotion.
COMPANY_SIZE_INCOME_MULT = {
    1: 0.72,   # 1-10
    2: 0.85,   # 11-50
    3: 1.00,   # 51-250
    4: 1.13,   # 251-1000
    5: 1.22,   # 1000+
}


def age_income_multiplier(age) -> float:
    """1.00 when age is unknown — an unknown age must not move the estimate."""
    try:
        a = int(age)
    except (TypeError, ValueError):
        return 1.0
    if a < 0:
        return 1.0
    for (lo, hi), m in AGE_INCOME_CURVE:
        if lo <= a <= hi:
            return m
    return 1.0


def company_size_income_multiplier(rank) -> float:
    """1.00 for UNKNOWN (rank 0/None). R7: unknown is not 'small'."""
    try:
        r = int(rank or 0)
    except (TypeError, ValueError):
        return 1.0
    return COMPANY_SIZE_INCOME_MULT.get(r, 1.0)


def estimate_occupation_income(base_annual_usd, age=None, company_size_rank=None):
    """Occupational base pay adjusted for experience and employer scale."""
    try:
        base = float(base_annual_usd)
    except (TypeError, ValueError):
        return None
    if base <= 0:
        return None
    return base * age_income_multiplier(age) * company_size_income_multiplier(company_size_rank)


# ═══════════════════════════════════════════════════════════════════════
# OCCUPATION TITLE RESOLUTION  (audit finding G — free-text -> canonical SOC)
# GLOBAL OCCUPATION RESOLUTION HARDENING — consolidated, internationalized.
# ═══════════════════════════════════════════════════════════════════════
#
# CHANGE-003 remediation originally found occupation resolution fragmented
# across three incompatible vocabularies in main.py (SOC-code regex,
# _US_PROFESSION_SOC legacy slugs, occupation_salary_agent.
# PROFESSION_TO_ISCO legacy slugs), none of which recognised a
# natural-language title like "Ingeniero Industrial" even though the
# underlying reference catalog (bls_occupation_scores_2025.csv) has a real
# row for it. GLOBAL OCCUPATION RESOLUTION HARDENING extends that same
# single mechanism — it does NOT create a second, parallel estimator.
#
# CANONICAL_OCCUPATIONS is the source of truth: one entry per occupation
# ALREADY present in the tracked BLS CSV (never invented), each carrying
# its aliases grouped by ISO 639-1 language code. Adding a language later
# (pt, fr, ...) means adding a key to an existing entry's `aliases` dict —
# it never touches income estimation, matching, or any other
# economic-calculation code, all of which only ever see the resulting SOC
# code. _OCCUPATION_TITLE_ALIASES (the flat normalized-alias -> SOC map
# resolve_occupation_soc actually does lookups against) is DERIVED from
# this registry at import time, not maintained separately.
#
# Deliberately NOT fuzzy/automatic translation — an occupation not listed
# here returns '' (unresolved), exactly like an occupation absent from any
# other catalog in this codebase; it is never guessed. Every SOC code below
# was verified present in bls_occupation_scores_2025.csv before being
# added — the alias only lets another spelling of an occupation THAT
# ALREADY HAS real reference data reach it; it never invents a salary.
#
# A bare/generic term that names a FAMILY of occupations with materially
# different pay (e.g. "ingeniero" — industrial? civil? mechanical?
# software?) is handled by AMBIGUOUS_OCCUPATION_TERMS below, NOT by
# guessing one member of the family here.
CANONICAL_OCCUPATIONS = (
    {'soc': '17-2112', 'title_en': 'Industrial Engineers', 'aliases': {
        'es': ['ingeniero industrial', 'ingeniera industrial'],
        'en': ['industrial engineer', 'industrial engineers']}},
    {'soc': '29-1215', 'title_en': 'Family Medicine Physicians', 'aliases': {
        'es': ['medico', 'medica', 'medico general', 'medica general'],
        'en': ['physician', 'general practitioner', 'family physician']}},
    {'soc': '29-1141', 'title_en': 'Registered Nurses', 'aliases': {
        'es': ['enfermero', 'enfermera'],
        'en': ['registered nurse', 'nurse']}},
    {'soc': '23-1011', 'title_en': 'Lawyers', 'aliases': {
        'es': ['abogado', 'abogada'],
        'en': ['lawyer', 'attorney']}},
    {'soc': '13-2011', 'title_en': 'Accountants and Auditors', 'aliases': {
        'es': ['contador', 'contadora', 'contador publico', 'contadora publica'],
        'en': ['accountant']}},
    {'soc': '17-1011', 'title_en': 'Architects, Except Landscape and Naval', 'aliases': {
        'es': ['arquitecto', 'arquitecta'],
        'en': ['architect']}},
    {'soc': '25-2031', 'title_en': 'Secondary School Teachers', 'aliases': {
        # "profesor/profesora" is listed WITHOUT the "only when
        # unambiguous" caveat this task gave "maestro/tecnico/disenador/
        # conductor" — treated as a deliberate, documented choice to
        # resolve, not left ambiguous like those.
        'es': ['profesor', 'profesora', 'profesor de secundaria', 'profesora de secundaria'],
        'en': ['teacher', 'secondary school teacher']}},
    {'soc': '25-2021', 'title_en': 'Elementary School Teachers', 'aliases': {
        # Bare "maestro/maestra" stays AMBIGUOUS (see below) — this entry
        # only covers the QUALIFIED form, the "sufficiently specific" case
        # this task's own instruction allows.
        'es': ['maestro de primaria', 'maestra de primaria',
              'maestro de escuela', 'maestra de escuela'],
        'en': ['elementary school teacher']}},
    {'soc': '17-2051', 'title_en': 'Civil Engineers', 'aliases': {
        'es': ['ingeniero civil', 'ingeniera civil'],
        'en': ['civil engineer']}},
    {'soc': '17-2141', 'title_en': 'Mechanical Engineers', 'aliases': {
        'es': ['ingeniero mecanico', 'ingeniera mecanica'],
        'en': ['mechanical engineer']}},
    {'soc': '17-2071', 'title_en': 'Electrical Engineers', 'aliases': {
        'es': ['ingeniero electrico', 'ingeniera electrica'],
        'en': ['electrical engineer']}},
    {'soc': '15-1252', 'title_en': 'Software Developers', 'aliases': {
        'es': ['ingeniero de software', 'ingeniera de software',
              'desarrollador de software', 'desarrolladora de software'],
        'en': ['software developer', 'software developers', 'software engineer']}},
    {'soc': '15-1251', 'title_en': 'Computer Programmers', 'aliases': {
        'es': ['programador', 'programadora'],
        'en': ['computer programmer', 'programmer']}},
    {'soc': '19-3033', 'title_en': 'Clinical and Counseling Psychologists', 'aliases': {
        'es': ['psicologo', 'psicologa'],
        'en': ['psychologist']}},
    {'soc': '29-1021', 'title_en': 'Dentists, General', 'aliases': {
        'es': ['dentista'],
        'en': ['dentist']}},
    {'soc': '29-1051', 'title_en': 'Pharmacists', 'aliases': {
        'es': ['farmaceutico', 'farmaceutica'],
        'en': ['pharmacist']}},
    {'soc': '29-1131', 'title_en': 'Veterinarians', 'aliases': {
        'es': ['veterinario', 'veterinaria'],
        'en': ['veterinarian']}},
    {'soc': '19-3011', 'title_en': 'Economists', 'aliases': {
        'es': ['economista'],
        'en': ['economist']}},
    {'soc': '11-1021', 'title_en': 'General and Operations Managers', 'aliases': {
        'es': ['administrador de empresas', 'administradora de empresas'],
        'en': ['business administrator']}},
    {'soc': '27-1024', 'title_en': 'Graphic Designers', 'aliases': {
        # Bare "disenador/disenadora" stays AMBIGUOUS — only the qualified
        # "grafico/grafica" form is sufficiently specific.
        'es': ['disenador grafico', 'disenadora grafica'],
        'en': ['graphic designer']}},
    {'soc': '47-2111', 'title_en': 'Electricians', 'aliases': {
        'es': ['electricista'],
        'en': ['electrician']}},
    {'soc': '49-3023', 'title_en': 'Automotive Service Technicians and Mechanics', 'aliases': {
        'es': ['mecanico', 'mecanica'],
        'en': ['mechanic', 'auto mechanic']}},
    {'soc': '27-3023', 'title_en': 'News Analysts, Reporters, and Journalists', 'aliases': {
        'es': ['periodista'],
        'en': ['journalist', 'reporter']}},
    {'soc': '35-1011', 'title_en': 'Chefs and Head Cooks', 'aliases': {
        'es': ['chef', 'cocinero', 'cocinera'],
        'en': ['chef', 'cook']}},
    {'soc': '53-3032', 'title_en': 'Heavy and Tractor-Trailer Truck Drivers', 'aliases': {
        # Bare "conductor/conductora" stays AMBIGUOUS — only the qualified
        # "de camion" form is sufficiently specific.
        'es': ['conductor de camion', 'conductora de camion'],
        'en': ['truck driver']}},
)

# Bare/generic terms that name a FAMILY of occupations with materially
# different pay, not one occupation — must never resolve to a guess.
# Each maps to the set of canonical SOC codes it could plausibly mean, for
# a future disambiguation UI (resolve_occupation_candidates below) —
# resolve_occupation_soc itself still returns '' for every one of these,
# exactly like any other unrecognised input. An empty set means the term
# is too broad even to enumerate a defensible candidate list.
AMBIGUOUS_OCCUPATION_TERMS = {
    'ingeniero':  frozenset({'17-2112', '17-2051', '17-2141', '17-2071', '15-1252'}),
    'ingeniera':  frozenset({'17-2112', '17-2051', '17-2141', '17-2071', '15-1252'}),
    'doctor':     frozenset({'29-1215'}),
    'doctora':    frozenset({'29-1215'}),
    'tecnico':    frozenset({'17-3021', '17-3022', '17-3023', '17-3026'}),
    'tecnica':    frozenset({'17-3021', '17-3022', '17-3023', '17-3026'}),
    'manager':    frozenset({'11-1021'}),
    'analista':   frozenset(),
    'analyst':    frozenset(),
    'conductor':  frozenset({'53-3032', '53-3033', '53-3031'}),
    'conductora': frozenset({'53-3032', '53-3033', '53-3031'}),
    'disenador':  frozenset({'27-1024'}),
    'disenadora': frozenset({'27-1024'}),
    'maestro':    frozenset({'25-2021'}),
    'maestra':    frozenset({'25-2021'}),
}


def _normalize_occupation_key(s: str) -> str:
    """Case/whitespace/accent-insensitive normalization, shared by every
    consumer of CANONICAL_OCCUPATIONS/AMBIGUOUS_OCCUPATION_TERMS so the
    registry and the resolver can never silently drift apart."""
    key = ''.join(c for c in unicodedata.normalize('NFKD', s.casefold())
                 if not unicodedata.combining(c))
    return ' '.join(key.split())


def _build_occupation_title_aliases() -> dict:
    out = {}
    for occ in CANONICAL_OCCUPATIONS:
        out[_normalize_occupation_key(occ['title_en'])] = occ['soc']
        for aliases in occ['aliases'].values():
            for alias in aliases:
                out[_normalize_occupation_key(alias)] = occ['soc']
    return out


# The flat map resolve_occupation_soc actually looks up against —
# generated from CANONICAL_OCCUPATIONS above, not maintained by hand.
_OCCUPATION_TITLE_ALIASES = _build_occupation_title_aliases()

_SOC_CODE_RE = re.compile(r'^\d{2}-\d{4}$')


def resolve_occupation_soc(v: Any) -> str:
    """Any supported occupation representation -> its canonical SOC code,
    or '' if unrecognised OR genuinely ambiguous.

    Accepts: a bare SOC code (returned as-is), or one of the explicit
    multilingual titles/aliases in CANONICAL_OCCUPATIONS, matched
    case/whitespace/accent-insensitively. A bare/generic term listed in
    AMBIGUOUS_OCCUPATION_TERMS (e.g. "ingeniero") deliberately returns ''
    here too — never silently picks one member of the family. Does NOT
    attempt to resolve a Preferendum legacy slug (e.g. 'ing_civil') —
    those already have their own established resolution path (main.py's
    _US_PROFESSION_SOC / eligibility.norm_occupation) at the coarser
    BLS-major-group level; this function is specifically for titles
    precise enough to identify ONE SOC occupation, which a major-group
    slug is not.
    """
    s = _base(v)
    if not s:
        return ''
    if _SOC_CODE_RE.match(s):
        return s
    key = _normalize_occupation_key(s)
    if key in AMBIGUOUS_OCCUPATION_TERMS:
        return ''
    return _OCCUPATION_TITLE_ALIASES.get(key, '')


class OccupationResolution:
    """Richer result for UI/diagnostic consumers (registration
    autocomplete, admin unresolved-occupation review) that need to tell
    "never heard of it" apart from "heard of it, but it's ambiguous" and
    offer real candidates — WITHOUT changing what feeds income estimation.
    resolve_occupation_soc (above) remains the ONLY function the estimator
    calls; this is a read-only view for everything else, kept separate per
    this task's instruction not to hard-wire alias resolution into
    economic-calculation code."""

    __slots__ = ('status', 'soc', 'candidates')

    RESOLVED = 'RESOLVED'
    AMBIGUOUS = 'AMBIGUOUS'
    UNRESOLVED = 'UNRESOLVED'

    def __init__(self, status: str, soc: str = '', candidates=()):
        self.status = status
        self.soc = soc
        self.candidates = tuple(candidates)

    def __repr__(self) -> str:   # pragma: no cover - debugging aid
        return f'<OccupationResolution {self.status} soc={self.soc!r} candidates={self.candidates!r}>'


def resolve_occupation_candidates(v: Any) -> 'OccupationResolution':
    """Same input contract as resolve_occupation_soc, but distinguishes
    RESOLVED / AMBIGUOUS / UNRESOLVED and surfaces candidate SOC codes for
    an ambiguous term. Never used by income estimation (see class
    docstring) — for registration UX and diagnostics only."""
    s = _base(v)
    if not s:
        return OccupationResolution(OccupationResolution.UNRESOLVED)
    if _SOC_CODE_RE.match(s):
        return OccupationResolution(OccupationResolution.RESOLVED, soc=s)
    key = _normalize_occupation_key(s)
    if key in AMBIGUOUS_OCCUPATION_TERMS:
        return OccupationResolution(OccupationResolution.AMBIGUOUS,
                                    candidates=sorted(AMBIGUOUS_OCCUPATION_TERMS[key]))
    soc = _OCCUPATION_TITLE_ALIASES.get(key, '')
    if soc:
        return OccupationResolution(OccupationResolution.RESOLVED, soc=soc)
    return OccupationResolution(OccupationResolution.UNRESOLVED)


def occupation_title_for_soc(soc: str) -> str:
    """Canonical English title for a SOC code, or '' if not in the
    registry (a valid SOC from the wider 818-row CSV that simply has no
    alias entry yet is not an error — this only covers the ones with
    declared aliases)."""
    for occ in CANONICAL_OCCUPATIONS:
        if occ['soc'] == soc:
            return occ['title_en']
    return ''


def occupation_aliases_for_soc(soc: str, lang: str = '') -> list:
    """Declared aliases for a SOC code, as originally spelled (accents
    kept) — for display in a search UI. `lang` filters to one ISO 639-1
    code ('es', 'en'); omit for every declared language. Empty list for a
    SOC code with no registry entry, exactly like occupation_title_for_soc
    — this is a read-only view for UX/diagnostics, never consulted by
    income estimation (see OccupationResolution's docstring)."""
    for occ in CANONICAL_OCCUPATIONS:
        if occ['soc'] != soc:
            continue
        if lang:
            return list(occ['aliases'].get(lang, []))
        out = []
        for aliases in occ['aliases'].values():
            out.extend(aliases)
        return out
    return []


def _base(v: Any) -> str:
    if v is None:
        return ''
    return str(v).strip()


# ═══════════════════════════════════════════════════════════════════════
# THE CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════

class Classification:
    """Result of classifying one person. Auditable by construction."""

    __slots__ = ('verdict', 'tier', 'ratio_to_country_median', 'income_used',
                 'income_source', 'income_as_of', 'context', 'professional',
                 'reasons', 'policy_version', 'unresolved_reason')

    def __init__(self, verdict, tier=None, ratio=None, income_used=None,
                 income_source=None, income_as_of=None, context=None,
                 professional=None, reasons=None, unresolved_reason=''):
        self.verdict = verdict
        self.tier = tier
        self.ratio_to_country_median = ratio
        self.income_used = income_used
        self.income_source = income_source
        self.income_as_of = income_as_of
        self.context = context
        self.professional = professional or {}
        self.reasons = reasons or []
        self.policy_version = POLICY_VERSION
        self.unresolved_reason = unresolved_reason

    @property
    def resolved(self) -> bool:
        return self.verdict == RESOLVED

    @property
    def based_on_declared_income(self) -> bool:
        return self.income_source in DECLARED_SOURCES

    def as_dict(self) -> dict:
        return {
            'verdict': self.verdict,
            'tier': self.tier,
            'ratio_to_country_median': self.ratio_to_country_median,
            'income_source': self.income_source,
            'income_as_of': self.income_as_of,
            'policy_version': self.policy_version,
            # Threshold-policy transparency (audit finding J): every
            # classification carries whether the TIER_BANDS it was computed
            # against have actually been approved by the business, so a
            # consumer can never mistake "the mechanism works" for "these
            # specific cut points are final."
            'thresholds_approved_by_business': THRESHOLDS_APPROVED_BY_BUSINESS,
            'derived_country_median': bool(
                self.context.derived_median) if self.context else None,
            'unresolved_reason': self.unresolved_reason,
            'reasons': list(self.reasons),
            # `income_used` is deliberately EXCLUDED from the dict form: it is
            # the person's actual income. See redact_for_api / main.py.
        }

    def __repr__(self) -> str:   # pragma: no cover
        return f'<Classification {self.verdict} tier={self.tier} src={self.income_source}>'


def select_income(observations) -> Optional[IncomeObservation]:
    """Pick the governing INDIVIDUAL income observation (R6).

    Highest precedence wins; ties break on recency. Household observations are
    never candidates — that is R5 and it is enforced by the caller passing only
    individual figures, plus a defensive check here.
    """
    best = None
    for obs in observations or []:
        if obs is None or obs.annual_usd is None:
            continue
        if getattr(obs, 'note', '') == 'household':
            continue
        if best is None:
            best = obs
            continue
        if may_overwrite(best.source, best.as_of, obs.source, obs.as_of):
            best = obs
    return best


def classify(individual_income_observations,
             context: CountryEconomicContext,
             professional: Optional[dict] = None) -> Classification:
    """THE canonical A/B/C/D decision.

    `professional` (occupation, cargo, company_size_rank) is carried through
    for targeting and diagnostics but DOES NOT influence the tier (R1).
    """
    professional = dict(professional or {})
    reasons = []

    if context is None or not context.resolved:
        why = (context.rejected_reason if context and context.rejected_reason
               else 'country economic context unavailable (PPP per capita missing)')
        return Classification(UNRESOLVED, context=context, professional=professional,
                              reasons=[f'context: {why}'], unresolved_reason=why)

    chosen = select_income(individual_income_observations)
    if chosen is None:
        why = 'no usable individual income observation'
        return Classification(UNRESOLVED, context=context, professional=professional,
                              reasons=[f'income: {why}'], unresolved_reason=why)

    income = chosen.annual_usd
    tier, ratio = tier_from_income(income, context)
    if tier is None:
        why = 'income could not be compared to the country median'
        return Classification(UNRESOLVED, context=context, professional=professional,
                              reasons=[f'tier: {why}'], unresolved_reason=why)

    reasons.append(f'income source: {chosen.source}')
    reasons.append(f'ratio to country median: {ratio:.2f}')
    if context.derived_median:
        reasons.append(
            'country median DERIVED from PPP per capita '
            f'(x{DERIVED_MEDIAN_FROM_PPP_RATIO}), not measured')
    if is_estimate(chosen.source):
        reasons.append('tier rests on an ESTIMATE, not a declared income')
    if professional:
        reasons.append('professional profile recorded but not used for tier (R1)')

    return Classification(RESOLVED, tier=tier, ratio=ratio, income_used=income,
                          income_source=chosen.source, income_as_of=chosen.as_of,
                          context=context, professional=professional, reasons=reasons)


# ═══════════════════════════════════════════════════════════════════════
# PRIVACY  (income is sensitive — R13 of the brief)
# ═══════════════════════════════════════════════════════════════════════

SENSITIVE_FIELDS = ('income_used', 'annual_usd', 'amount', 'amount_max',
                    'individual_income_usd', 'household_income_usd',
                    'estimated_income_usd', 'estimated_income_ppp')


def redact_for_api(payload: dict, include_income: bool = False) -> dict:
    """Strip exact income from anything crossing an API boundary.

    The TIER is the shareable abstraction; the underlying figure is not. Even
    the owner's own endpoints should opt in explicitly rather than leak by
    default.
    """
    out = dict(payload or {})
    if not include_income:
        for k in SENSITIVE_FIELDS:
            out.pop(k, None)
    return out


def safe_log_summary(c: Classification) -> str:
    """Log line that is useful for debugging and carries no income figure."""
    if c is None:
        return 'classification=<none>'
    return (f'classification verdict={c.verdict} tier={c.tier or "-"} '
            f'src={c.income_source or "-"} policy={c.policy_version} '
            f'derived_median={bool(c.context.derived_median) if c.context else "-"}')


# ═══════════════════════════════════════════════════════════════════════
# ECONOMIC REFERENCE DATA — PROPOSE -> VALIDATE -> VERSION -> APPROVE
# ═══════════════════════════════════════════════════════════════════════

PROPOSAL_PENDING = 'pending'
PROPOSAL_REJECTED = 'rejected'
PROPOSAL_APPROVED = 'approved'

# A single update may not move a country's PPP by more than this without a
# human looking at it. Real year-on-year movement is a few percent; a 40% jump
# is the signature of a unit error or a nominal series being loaded.
MAX_UNREVIEWED_RELATIVE_CHANGE = 0.40


class ReferenceProposal:
    """A proposed change to economic reference data.

    Agents PROPOSE. They never write production classifications directly. Every
    proposal carries its source, the year the datum refers to, and the version
    it would create.
    """

    __slots__ = ('country', 'field', 'old_value', 'new_value', 'source',
                 'data_year', 'proposed_at', 'version', 'status',
                 'validation_errors', 'requires_review', 'review_reasons')

    def __init__(self, country, field, new_value, source, data_year,
                 old_value=None, proposed_at=None, version=None):
        self.country = (country or '').strip().upper()
        self.field = field
        self.old_value = old_value
        self.new_value = new_value
        self.source = source
        self.data_year = data_year
        self.proposed_at = proposed_at
        self.version = version
        self.status = PROPOSAL_PENDING
        self.validation_errors = []
        self.requires_review = False
        self.review_reasons = []

    def as_dict(self) -> dict:
        return {s: getattr(self, s) for s in self.__slots__}


def validate_proposal(p: ReferenceProposal, *, current_year: Optional[int] = None) -> ReferenceProposal:
    """VALIDATE stage. Rejects outright; flags for review; never auto-applies.

    Deliberately conservative: everything it cannot positively justify is
    escalated to a human rather than allowed through.
    """
    errs, review = [], []

    if not p.country or len(p.country) != 2:
        errs.append('country must be a 2-letter ISO code')

    if p.field == 'ppp_per_capita_usd':
        if p.source in PPP_REFUSED_SOURCES:
            errs.append(f'source {p.source!r} is a NOMINAL series; {PPP_SOURCE_REQUIRED}')
        elif p.source not in PPP_ACCEPTED_SOURCES:
            errs.append(f'source {p.source!r} is not an accepted PPP provenance')
    elif p.field not in ('median_personal_income_usd',):
        errs.append(f'unknown reference field {p.field!r}')

    try:
        nv = float(p.new_value)
        if nv <= 0:
            errs.append('value must be positive')
    except (TypeError, ValueError):
        errs.append('value is not numeric')
        nv = None

    if p.data_year is None:
        errs.append('data_year is required — a figure without a year is unauditable')
    elif current_year is not None:
        try:
            if int(p.data_year) > int(current_year):
                errs.append('data_year is in the future')
            elif int(current_year) - int(p.data_year) > 5:
                review.append(f'stale: data_year {p.data_year} is more than 5 years old')
        except (TypeError, ValueError):
            errs.append('data_year is not an integer')

    if not p.source:
        errs.append('source is required')

    if nv is not None and p.old_value not in (None, ''):
        try:
            ov = float(p.old_value)
            if ov > 0:
                rel = abs(nv - ov) / ov
                if rel > MAX_UNREVIEWED_RELATIVE_CHANGE:
                    review.append(
                        f'moves {rel:.0%} vs stored value — beyond the '
                        f'{MAX_UNREVIEWED_RELATIVE_CHANGE:.0%} unreviewed limit; '
                        'possible unit error or nominal series')
        except (TypeError, ValueError):
            review.append('stored value not numeric; cannot bound the change')

    p.validation_errors = errs
    p.review_reasons = review
    p.requires_review = bool(review)
    p.status = PROPOSAL_REJECTED if errs else PROPOSAL_PENDING
    return p


def approve_proposal(p: ReferenceProposal, *, approver: str,
                     approved_at=None, force: bool = False) -> ReferenceProposal:
    """APPROVE stage — an explicit human act.

    A proposal flagged `requires_review` needs `force=True`, so overriding the
    safety bound is a recorded, deliberate decision rather than a default.
    """
    if p.validation_errors:
        p.status = PROPOSAL_REJECTED
        return p
    if p.requires_review and not force:
        p.status = PROPOSAL_PENDING
        p.review_reasons.append('awaiting explicit review: approve with force=True')
        return p
    if not approver:
        p.status = PROPOSAL_PENDING
        p.review_reasons.append('approver required')
        return p
    p.status = PROPOSAL_APPROVED
    p.proposed_at = p.proposed_at or approved_at
    return p


# ═══════════════════════════════════════════════════════════════════════
# DRY-RUN IMPACT DIAGNOSTIC  (never mutates)
# ═══════════════════════════════════════════════════════════════════════

def diff_classification(old_tier: Any, new: Classification) -> str:
    """One of: unchanged | changed | newly_resolved | became_unresolved | still_unresolved"""
    old = _norm_tier(old_tier)
    if not new.resolved:
        return 'became_unresolved' if old else 'still_unresolved'
    if not old:
        return 'newly_resolved'
    return 'unchanged' if old == new.tier else 'changed'


def impact_report(rows) -> dict:
    """rows: iterable of (user_id, old_tier, Classification). Read-only.

    Answers the question that must be answered BEFORE any mass
    reclassification: who actually moves, and why.
    """
    counts = {'unchanged': 0, 'changed': 0, 'newly_resolved': 0,
              'became_unresolved': 0, 'still_unresolved': 0}
    transitions, reasons, evaluable, changed_ids = {}, {}, 0, []

    for user_id, old_tier, c in rows:
        evaluable += 1
        outcome = diff_classification(old_tier, c)
        counts[outcome] = counts.get(outcome, 0) + 1
        if outcome in ('changed', 'newly_resolved'):
            key = f'{_norm_tier(old_tier) or "-"}->{c.tier}'
            transitions[key] = transitions.get(key, 0) + 1
        if outcome == 'changed':
            changed_ids.append(user_id)
        if not c.resolved and c.unresolved_reason:
            reasons[c.unresolved_reason] = reasons.get(c.unresolved_reason, 0) + 1

    return {
        'policy_version': POLICY_VERSION,
        'thresholds_approved_by_business': THRESHOLDS_APPROVED_BY_BUSINESS,
        'tier_bands': list(TIER_BANDS),
        'evaluable': evaluable,
        'counts': counts,
        'would_change': counts['changed'],
        'unresolved': counts['became_unresolved'] + counts['still_unresolved'],
        'transitions': dict(sorted(transitions.items())),
        'unresolved_reasons': dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        'changed_user_ids_sample': changed_ids[:50],
        'note': 'DRY RUN — nothing was written. Mass reclassification requires '
                'explicit separate authorization. The tier_bands above are '
                'PROVISIONAL (see thresholds_approved_by_business) — business '
                'has not yet approved these specific cut points.',
    }
