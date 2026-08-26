"""
eligibility.py — Preferendum CANONICAL eligibility evaluator (CHANGE-002)
=========================================================================

ONE place decides whether a user may see/vote a consultation, and whether a
campaign may be served to a user. Every discovery path, every direct-access
path, the vote endpoint and every ad-serving path consume this module.

Design constraints (from CHANGE-002 rules):

  * STDLIB ONLY. No fastapi / sqlalchemy / ORM imports. Callers pass plain
    snapshots (see UserProfile / ConsultationTarget / CampaignTarget), which
    are built from ORM rows by thin adapters. This keeps the evaluator unit
    testable without a database and impossible to accidentally couple to a
    request context.

  * ELIGIBILITY IS NOT RANKING. Nothing in this module reads cpm, budget,
    optimization_rank, specificity, frequency caps or weights. Those live in
    targeting_agent / the serving helper and may only reorder an already
    eligible set (rule 15).

  * FAIL CLOSED, BUT ONLY ON MATERIAL DATA. See MATERIAL SUFFICIENCY below.

  * GLOBAL means "no geographic restriction" — it does NOT switch off any
    other dimension (rule 1). That falls out of: an unset dimension does not
    constrain; set dimensions are ANDed.

MATERIAL SUFFICIENCY (rule 7)
-----------------------------
Neither "missing field => eligible" nor "missing field => ineligible".

A missing datum blocks only when it is MATERIAL to the condition actually
requested:

  * The consultation asks for tier B-or-above and the user's tier is already
    established as B. `company_size` is missing, but company size is only an
    INPUT to the tier computation — the requested condition is already
    proven. => ELIGIBLE.

  * The consultation asks for tier A and the user has no established tier at
    all. The inputs needed to derive it (occupation, cargo, company size,
    commune) are missing/incomplete, so A-vs-B cannot be decided.
    => UNRESOLVED.

  * The campaign explicitly filters on company_size and the user's company
    size is unknown. The requested condition is directly about that datum, so
    compliance is NOT PROVEN. => UNRESOLVED. (Never assume in the user's
    favour.)

UNRESOLVED is never treated as permission: `Decision.allowed` is True only for
ELIGIBLE. It is kept distinct from INELIGIBLE so the platform can tell "this
user fails your targeting" apart from "we still need to compute this user's
profile", which drives recalculation and honest audience reporting rather than
a silent denial.

TRI-STATE, NOT BOOLEAN
----------------------
Every dimension comparator returns PASS / FAIL / UNRESOLVED, and the
combinator is: any FAIL => INELIGIBLE (fail dominates, so a user who
genuinely mismatches is reported as mismatching even if some other datum is
also missing); else any UNRESOLVED => UNRESOLVED; else ELIGIBLE.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Optional

# ═══════════════════════════════════════════════════════════════════════
# VERDICTS
# ═══════════════════════════════════════════════════════════════════════

ELIGIBLE = 'eligible'
INELIGIBLE = 'ineligible'
UNRESOLVED = 'unresolved'

PASS = 'pass'
FAIL = 'fail'
UNKNOWN = 'unknown'          # per-dimension: material datum missing
NOT_CONSTRAINED = 'n/a'      # dimension not targeted at all


class Reason:
    """Why one dimension decided the way it did. Safe to log; safe to return
    to admins. Never returned to an ineligible end user (non-disclosure)."""

    __slots__ = ('dimension', 'outcome', 'user_value', 'target_value', 'detail')

    def __init__(self, dimension: str, outcome: str, user_value: Any = None,
                 target_value: Any = None, detail: str = ''):
        self.dimension = dimension
        self.outcome = outcome
        self.user_value = user_value
        self.target_value = target_value
        self.detail = detail

    def as_dict(self) -> dict:
        return {
            'dimension': self.dimension,
            'outcome': self.outcome,
            'user_value': self.user_value,
            'target_value': self.target_value,
            'detail': self.detail,
        }

    def __repr__(self) -> str:   # pragma: no cover - debugging aid
        return (f'<Reason {self.dimension}={self.outcome} '
                f'user={self.user_value!r} target={self.target_value!r}>')


class Decision:
    """Result of a canonical evaluation.

    `allowed` is the ONLY thing callers may gate on. It is True exclusively
    for ELIGIBLE — UNRESOLVED never grants access (rule 20: security wins).
    """

    __slots__ = ('verdict', 'reasons')

    def __init__(self, verdict: str, reasons: list):
        self.verdict = verdict
        self.reasons = reasons

    @property
    def allowed(self) -> bool:
        return self.verdict == ELIGIBLE

    @property
    def eligible(self) -> bool:
        return self.verdict == ELIGIBLE

    @property
    def unresolved(self) -> bool:
        return self.verdict == UNRESOLVED

    def failures(self) -> list:
        return [r for r in self.reasons if r.outcome == FAIL]

    def unknowns(self) -> list:
        return [r for r in self.reasons if r.outcome == UNKNOWN]

    def blocking_dimensions(self) -> list:
        return [r.dimension for r in self.reasons if r.outcome in (FAIL, UNKNOWN)]

    def as_dict(self) -> dict:
        return {
            'verdict': self.verdict,
            'allowed': self.allowed,
            'blocking': self.blocking_dimensions(),
            'reasons': [r.as_dict() for r in self.reasons],
        }

    def __repr__(self) -> str:   # pragma: no cover - debugging aid
        return f'<Decision {self.verdict} blocking={self.blocking_dimensions()}>'


def _combine(reasons: list) -> Decision:
    """FAIL dominates UNKNOWN dominates PASS."""
    if any(r.outcome == FAIL for r in reasons):
        return Decision(INELIGIBLE, reasons)
    if any(r.outcome == UNKNOWN for r in reasons):
        return Decision(UNRESOLVED, reasons)
    return Decision(ELIGIBLE, reasons)


# ═══════════════════════════════════════════════════════════════════════
# NORMALIZATION PRIMITIVES  (rule 18 — one definition, shared everywhere)
# ═══════════════════════════════════════════════════════════════════════

def _strip_accents(s: str) -> str:
    """NFKD fold so 'Ñuñoa' == 'Nunoa' and 'Conchalí' == 'Conchali'.

    Phase 0 found four different commune comparisons, none of which folded
    accents, so the same commune spelled two legitimate ways never matched.
    """
    return ''.join(c for c in unicodedata.normalize('NFKD', s)
                   if not unicodedata.combining(c))


def _base(v: Any) -> str:
    if v is None:
        return ''
    return str(v).strip()


def csv_set(v: Any) -> set:
    """Split a comma-separated targeting field into raw tokens.

    Empty / None => empty set => dimension NOT constrained (rule 1).
    """
    s = _base(v)
    if not s:
        return set()
    return {tok.strip() for tok in s.split(',') if tok.strip()}


# ── Country ────────────────────────────────────────────────────────────
# Preserved verbatim from main.py `_COUNTRY_CODES` / `_country_code`, which
# Phase 0 found was used by only 2 of 5 live paths — the other 3 compared
# raw `.upper()`, so a user registered as 'Chile' failed against 'CL'.

_COUNTRY_ALIASES = {
    'chile': 'CL', 'argentina': 'AR', 'brasil': 'BR', 'brazil': 'BR',
    'mexico': 'MX', 'colombia': 'CO', 'peru': 'PE',
    'espana': 'ES', 'spain': 'ES', 'usa': 'US', 'estados unidos': 'US',
    'united states': 'US', 'estados unidos de america': 'US',
    'todos': 'ALL', 'all': 'ALL', 'global': 'ALL',
}

# Values that mean "no geographic restriction" (rule 1).
UNRESTRICTED_GEO = {'', 'ALL', 'GLOBAL', 'GL', 'WORLD', 'WORLDWIDE'}


def norm_country(v: Any) -> str:
    """'Chile' / 'chile' / 'CL' / 'cl' -> 'CL'. '' stays ''."""
    s = _base(v)
    if not s:
        return ''
    folded = _strip_accents(s).lower()
    if folded in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[folded]
    if len(s) <= 3:
        return s.upper()
    return s.upper()


def norm_country_set(v: Any) -> set:
    out = {norm_country(t) for t in csv_set(v)}
    return {c for c in out if c}


def is_geo_unrestricted(values: set) -> bool:
    """A geography field that is empty, or that names ALL/GLOBAL, imposes no
    geographic restriction — but does NOT disable other dimensions (rule 1)."""
    if not values:
        return True
    return bool(values & UNRESTRICTED_GEO)


# ── Commune / region ───────────────────────────────────────────────────

def norm_commune(v: Any) -> str:
    """Casefold + accent-fold + collapse internal whitespace.

    'Las  Condes' / 'las condes' / 'LAS CONDES' all -> 'las condes'.
    'Ñuñoa' -> 'nunoa'.
    """
    s = _base(v)
    if not s:
        return ''
    s = _strip_accents(s).casefold()
    return re.sub(r'\s+', ' ', s)


def norm_commune_set(v: Any) -> set:
    out = {norm_commune(t) for t in csv_set(v)}
    return {c for c in out if c}


# ── National ID (closed lists) ─────────────────────────────────────────
# THE canonical national-ID normalization. There is exactly one, and the
# closed-list WRITE path, the closed-list READ path, any backfill and the
# tests all call it.
#
# CHANGE-002 remediation CRIT-1: previously the upload endpoint hashed the
# raw CSV line while membership lookup hashed a stripped/uppercased form, so
# a normally formatted RUT ("12.345.678-9") uploaded by an organizer could
# NEVER match the same person's profile. Every closed-list consultation
# denied every member. Two normalizations = a broken control.

def norm_national_id(v: Any) -> str:
    """Canonical form of a national identity document.

    Strips every character that is only presentation (dots, dashes, spaces,
    non-breaking spaces) and upper-cases the remainder, so that all ordinary
    renderings of the same Chilean RUT collapse together:

        '12.345.678-9' / '12345678-9' / '123456789' / ' 12.345.678-k '
            -> '123456789' / '123456789' / '123456789' / '12345678K'

    Deliberately conservative: it removes formatting only. It does NOT
    validate the check digit, pad, or otherwise reinterpret the value, so it
    can never merge two genuinely different documents.
    """
    s = _base(v)
    if not s:
        return ''
    return re.sub(r'[^0-9A-Za-z]', '', s).upper()


def national_id_variants(v: Any) -> list:
    """Ordinary renderings of ONE person's own document.

    Used only for backward compatibility with closed-list rows written by the
    legacy code path, which hashed the raw uploaded line. Those hashes are
    SHA-256 and cannot be reversed, so membership for an already-uploaded
    list can only be recovered by re-deriving the plausible source strings
    from the SAME user's own document and comparing hashes.

    Every variant here is generated from the caller's own national ID, so
    this can never admit somebody who is not on the list: an attacker would
    have to already hold the exact document of a listed person.

    Returns the canonical form first, then legacy renderings, de-duplicated
    and order-stable.
    """
    canon = norm_national_id(v)
    if not canon:
        return []
    raw = _base(v)
    out = [canon]

    body, dv = canon[:-1], canon[-1:]
    if body.isdigit() and dv:
        # 12345678-9
        out.append(f'{body}-{dv}')
        # 12.345.678-9  (thousands separators, right to left)
        grouped = ''
        for i, ch in enumerate(reversed(body)):
            if i and i % 3 == 0:
                grouped = '.' + grouped
            grouped = ch + grouped
        out.append(f'{grouped}-{dv}')
        out.append(f'{grouped}-{dv.lower()}')
        out.append(f'{body}-{dv.lower()}')
    out.append(canon.lower())
    if raw:
        out.append(raw)
        out.append(raw.strip())

    seen, uniq = set(), []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


# ── Gender ─────────────────────────────────────────────────────────────
# Promoted from main.py `_normalize_gender`, which existed but was reachable
# only from the admin diagnostic — never from a serving path.

_GENDER_F = {'f', 'female', 'mujer', 'femenino', 'femenina', 'w'}
_GENDER_M = {'m', 'male', 'hombre', 'masculino', 'masculina'}
_GENDER_ALL = {'all', 'todos', 'todas', 'any', 'cualquiera', 'ambos', '*'}


def norm_gender(v: Any) -> str:
    """-> 'F' | 'M' | 'all' | '' (unknown).

    NOTE the distinction Phase 0 conflated: 'all' means the TARGET does not
    restrict; '' means the USER's gender is unknown. Returning 'all' for an
    unset user value would silently assume the datum in the user's favour.
    """
    s = _strip_accents(_base(v)).lower()
    if not s:
        return ''
    if s in _GENDER_F:
        return 'F'
    if s in _GENDER_M:
        return 'M'
    if s in _GENDER_ALL:
        return 'all'
    return 'other'


def norm_gender_target(v: Any) -> str:
    """Target side: an unset gender target means 'all' (not constrained)."""
    g = norm_gender(v)
    return g if g else 'all'


# ── Age ────────────────────────────────────────────────────────────────

_DOB_FORMATS = ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d')


def parse_age(dob: Any, today=None) -> Optional[int]:
    """Calendar-correct age from a date-of-birth string.

    Accepts the four formats the repository actually writes (consolidated
    from main.py:3743). Returns None when genuinely unparseable — callers
    must treat None as UNKNOWN, never as "passes".
    """
    from datetime import date, datetime

    s = _base(dob)
    if not s:
        return None
    if today is None:
        today = date.today()
    born = None
    for fmt in _DOB_FORMATS:
        try:
            born = datetime.strptime(s[:10], fmt).date()
            break
        except ValueError:
            continue
    if born is None:
        return None
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    if age < 0 or age > 130:
        return None
    return age


def parse_age_ranges(v: Any) -> list:
    """'18-24,25-34,55+' -> [(18,24),(25,34),(55,130)]. Unparseable tokens are
    dropped; an all-unparseable field yields [] (= not constrained)."""
    out = []
    for tok in csv_set(v):
        t = tok.strip()
        if t.endswith('+'):
            try:
                out.append((int(t[:-1]), 130))
            except ValueError:
                continue
        elif '-' in t:
            lo, _, hi = t.partition('-')
            try:
                out.append((int(lo.strip()), int(hi.strip())))
            except ValueError:
                continue
        else:
            try:
                n = int(t)
                out.append((n, n))
            except ValueError:
                continue
    return out


# ── Socioeconomic tier ─────────────────────────────────────────────────
# Rule 8: tier A/B/C/D is THE consultant-facing economic segmentation for
# individuals. Raw income ranges are not the primary mechanism.

TIER_RANK = {'A': 4, 'B': 3, 'C': 2, 'D': 1}
TIER_LADDER = ['D', 'C', 'B', 'A']
ALL_TIERS = {'A', 'B', 'C', 'D'}


def norm_tier(v: Any) -> str:
    """'A' / 'a' / 'AAA' / 'BBC' -> 'A' / 'A' / 'A' / 'B'.

    The repository carries two historical tier vocabularies: single-letter
    A/B/C/D (current) and triples like 'AAA','BBC' (legacy). main.py
    `_tier_matches` already collapsed triples by first letter; that behaviour
    is preserved here as the single definition.
    """
    s = _base(v).upper()
    if not s:
        return ''
    if s[0] in TIER_RANK:
        return s[0]
    return ''


def norm_tier_set(v: Any) -> set:
    out = {norm_tier(t) for t in csv_set(v)}
    return {t for t in out if t}


def tier_rank(t: Any) -> int:
    return TIER_RANK.get(norm_tier(t), 0)


# ── Occupation / profession ────────────────────────────────────────────
# Rule 10: use the EXISTING catalogue, do not invent a taxonomy.
#
# Canonical identity = BLS SOC **major group** ('11-0000' ... '53-0000'),
# which is what `occupation_unified` is keyed on for country_iso='US' and
# what `bls_occupation_scores_2025.csv` (818 SOC rows) carries in its
# `major_group` column.
#
# Three representations exist in live data and all normalize to that:
#   1. a full SOC code, '29-1141'   -> major group '29-0000'
#   2. a Preferendum slug, 'medico' -> via _US_PROFESSION_SOC
#   3. a BLS major group already    -> itself
#
# _OCCUPATION_TO_MAJOR is copied from main.py `_US_PROFESSION_SOC` (line
# 3134) so the consultant-facing vocabulary and the economic pipeline agree.
# Additional aliases below are the Spanish slugs from
# occupation_salary_agent.PROFESSION_TO_ISCO that were NOT already present,
# mapped to the same major group as their _US_PROFESSION_SOC counterpart.

_OCCUPATION_TO_MAJOR = {
    # ── Current Preferendum codes (BLS major-group categories) ──
    'mgmt': '11-0000',
    'biz_fin': '13-0000',
    'computer': '15-0000',
    'engineering': '17-0000',
    'science': '19-0000',
    'social_svc': '21-0000',
    'legal': '23-0000',
    'education': '25-0000',
    'arts_media': '27-0000',
    'healthcare_pro': '29-0000',
    'healthcare_sup': '31-0000',
    'protective': '33-0000',
    'food_svc': '35-0000',
    'cleaning': '37-0000',
    'personal_care': '39-0000',
    'sales': '41-0000',
    'admin': '43-0000',
    'agriculture': '45-0000',
    'construction': '47-0000',
    'installation': '49-0000',
    'production': '51-0000',
    'transport': '53-0000',
    # ── Legacy Preferendum slugs (main.py _US_PROFESSION_SOC) ──
    'medico': '29-0000',
    'dentista': '29-0000',
    'abogado': '23-0000',
    'juez': '23-0000',
    'economista': '19-0000',
    'ing_civil': '17-0000',
    'ing_comercial': '11-0000',
    'empresario': '11-0000',
    'ejecutivo': '11-0000',
    'financiero': '13-0000',
    'farmaceutico': '29-0000',
    'psicologo': '19-0000',
    'contador': '13-0000',
    'ing_informatica': '15-0000',
    'arquitecto': '17-0000',
    'ing_otro': '17-0000',
    'consultor': '13-0000',
    'marketing': '11-0000',
    'profesor_univ': '25-0000',
    'cientifico': '19-0000',
    'periodista': '27-0000',
    'artista': '27-0000',
    'ventas': '41-0000',
    'profesor_escuela': '25-0000',
    'tecnico': '17-0000',
    'enfermero': '29-0000',
    'comercio': '41-0000',
    'mecanico': '49-0000',
    'construccion': '47-0000',
    'transporte': '53-0000',
    'servicios': '35-0000',
    'hogar': '37-0000',
    # ── Aliases only present in occupation_salary_agent.PROFESSION_TO_ISCO ──
    # Same major group as their _US_PROFESSION_SOC equivalent above.
    'gerente_general': '11-0000',
    'director': '11-0000',
    'veterinario': '29-0000',
    'quimico': '19-0000',
    'biologo': '19-0000',
    'matematico': '19-0000',
    'disenador': '27-0000',
    'programador': '15-0000',
    'recursos_humanos': '13-0000',
    'tecnico_lab': '19-0000',
    'administrativo': '43-0000',
    'secretario': '43-0000',
    'contador_aux': '43-0000',
    'vendedor': '41-0000',
    'cocinero': '35-0000',
    'camarero': '35-0000',
    'conductor': '53-0000',
    'policia': '33-0000',
    'bombero': '33-0000',
    'agricultor': '45-0000',
    'electricista': '47-0000',
    'carpintero': '47-0000',
    'plomero': '47-0000',
    'operador': '51-0000',
    'minero': '47-0000',
    'empleado_domestico': '37-0000',
    'guardia': '33-0000',
    'obrero': '51-0000',
}

_SOC_FULL_RE = re.compile(r'^(\d{2})-(\d{4})$')


def norm_occupation(v: Any) -> str:
    """Any supported occupation representation -> BLS major group, or ''.

    '' means the occupation is UNKNOWN/unrecognised — callers must treat it
    as UNKNOWN on a constrained dimension, never as a pass.
    """
    s = _base(v)
    if not s:
        return ''
    m = _SOC_FULL_RE.match(s)
    if m:
        return f'{m.group(1)}-0000'
    key = _strip_accents(s).casefold().replace(' ', '_').replace('-', '_')
    if key in _OCCUPATION_TO_MAJOR:
        return _OCCUPATION_TO_MAJOR[key]
    return ''


def norm_occupation_set(v: Any) -> set:
    """Target side. Unrecognised tokens are preserved in casefolded raw form
    so an unknown-but-intentional value can still match an identical raw user
    value rather than silently becoming 'unrestricted' (rule 18: do not
    silently collapse semantically different values)."""
    out = set()
    for tok in csv_set(v):
        norm = norm_occupation(tok)
        out.add(norm if norm else _strip_accents(tok).casefold())
    return {t for t in out if t}


def occupation_match_values(v: Any) -> set:
    """The set of tokens a USER's occupation can legitimately match against:
    its canonical major group plus its own casefolded raw form."""
    s = _base(v)
    if not s:
        return set()
    vals = {_strip_accents(s).casefold()}
    norm = norm_occupation(s)
    if norm:
        vals.add(norm)
    return vals


# ── Cargo / job role ───────────────────────────────────────────────────
# Distinct concept from occupation (rule 10). Canonical vocabulary is the
# key set of main.py `_CARGO_TIER` (line 3216).

_CARGO_ALIASES = {
    'ceo': 'ceo', 'dueno': 'ceo', 'fundador': 'ceo', 'founder': 'ceo',
    'owner': 'ceo', 'chairman': 'ceo', 'president': 'ceo', 'presidente': 'ceo',
    'gerente_general': 'gerente_general', 'general_manager': 'gerente_general',
    'director': 'director', 'socio': 'director', 'partner': 'director',
    'gerente': 'gerente', 'manager': 'gerente',
    'subgerente': 'subgerente', 'vp': 'subgerente', 'cfo': 'subgerente',
    'cto': 'subgerente', 'coo': 'subgerente',
    'jefe': 'jefe', 'head': 'jefe',
    'supervisor': 'supervisor', 'coordinador': 'supervisor',
    'profesional': 'profesional',
    'analista': 'analista', 'especialista': 'analista',
    'asistente': 'asistente',
    'tecnico_cargo': 'tecnico_cargo', 'operario': 'tecnico_cargo',
    'practicante': 'practicante', 'junior': 'practicante', 'intern': 'practicante',
    'independiente': 'independiente', 'freelance': 'independiente',
}


def norm_cargo(v: Any) -> str:
    s = _base(v)
    if not s:
        return ''
    key = _strip_accents(s).casefold().replace(' ', '_').replace('-', '_')
    return _CARGO_ALIASES.get(key, key)


def norm_cargo_set(v: Any) -> set:
    out = {norm_cargo(t) for t in csv_set(v)}
    return {c for c in out if c}


# ── Company size ───────────────────────────────────────────────────────
# Rule 11: company size materially affects economic inference and is also a
# first-class targeting dimension. Four incompatible vocabularies existed in
# the repository (Phase 0 F-10); this is the single reconciliation.

COMPANY_SIZE_ORDER = ['1-10', '11-50', '51-250', '251-1000', '+1000']

_COMPANY_SIZE_RANK = {
    # Canonical user-stored vocabulary (main.py:102)
    '1-10': 1, '11-50': 2, '51-250': 3, '251-1000': 4, '+1000': 5,
    # Legacy vocabulary found in _HNW_COMPANY_BIG / _HNW_COMPANY_MID
    '51-200': 3, '100-499': 3, '201-500': 4, '500+': 5,
    # Common free-text spellings
    'micro': 1, 'small': 2, 'pequena': 2, 'pyme': 2,
    'medium': 3, 'mediana': 3,
    'large': 4, 'grande': 4,
    'enterprise': 5, 'corporacion': 5, 'multinacional': 5,
}

# Bucket vocabulary the campaign side uses ('small,medium,large').
_COMPANY_BUCKET_RANKS = {
    'small': {1, 2},
    'medium': {3},
    'large': {4, 5},
}


def norm_company_size(v: Any) -> int:
    """-> ordinal 1..5, or 0 when unknown/unrecognised."""
    s = _base(v)
    if not s:
        return 0
    key = _strip_accents(s).casefold().replace(' ', '')
    return _COMPANY_SIZE_RANK.get(key, 0)


def company_size_target_ranks(v: Any) -> set:
    """Target side -> the set of acceptable ordinals.

    Accepts both bucket names ('small,medium,large') and explicit brackets
    ('251-1000,+1000'), because both appear in live campaign rows.
    """
    ranks = set()
    for tok in csv_set(v):
        key = _strip_accents(tok).casefold().replace(' ', '')
        if key in _COMPANY_BUCKET_RANKS:
            ranks |= _COMPANY_BUCKET_RANKS[key]
        else:
            r = _COMPANY_SIZE_RANK.get(key, 0)
            if r:
                ranks.add(r)
    return ranks


# ── Categories ─────────────────────────────────────────────────────────

def norm_category(v: Any) -> str:
    s = _base(v)
    if not s:
        return ''
    return _strip_accents(s).casefold()


def norm_category_set(v: Any) -> set:
    out = {norm_category(t) for t in csv_set(v)}
    return {c for c in out if c}


# Brand-safety keyword expansion, preserved verbatim from main.py:4628.
SENSITIVE_KEYWORDS = {
    'religion': {'religion', 'iglesia', 'church', 'dios', 'god', 'fe', 'faith',
                 'islam', 'cristian', 'catholic', 'budis', 'hindu', 'jewish', 'judio'},
    'politica': {'politica', 'election', 'eleccion', 'partido', 'gobierno',
                 'president', 'alcalde', 'senado', 'congreso', 'diputado'},
    'sexual': {'sexual', 'sexo', 'sex', 'genero', 'lgbt', 'trans', 'homosex',
               'hetero', 'gay', 'orientacion', 'aborto', 'abortion', 'reproductive'},
    'conflicto_armado': {'guerra', 'war', 'conflicto', 'conflict', 'armas',
                         'weapons', 'militar', 'military', 'ejercito', 'army',
                         'bomba', 'bomb', 'ataque', 'attack', 'terroris'},
    'sindicatos': {'sindicato', 'huelga', 'strike', 'laboral', 'gremio',
                   'union', 'trabajador', 'obrero'},
    'drogas': {'droga', 'drug', 'narcotico', 'narcotic', 'cannabis',
               'cocaina', 'alcohol', 'bebida', 'licor'},
    'apuestas': {'apuesta', 'casino', 'juego', 'gambling', 'loteria', 'lottery', 'bet'},
    'menores': {'menor', 'nino', 'infan', 'child', 'adolescen', 'escolar'},
    'litigios': {'juicio', 'tribunal', 'corte', 'demanda', 'lawsuit', 'litig', 'arbitraj'},
    'crisis': {'crisis', 'catastrofe', 'desastre', 'disaster', 'terremoto',
               'inundacion', 'refugee', 'refugiado'},
}


def derive_content_tags(category: Any, title: Any = '') -> set:
    """Canonical tags for a consultation's content, from its category plus
    title keywords. Used ONLY for campaign<->consultation brand-safety
    compatibility (rule 13 barrier 1) — never for user eligibility."""
    cat = norm_category(category)
    text = norm_category(title)
    tags = {cat} if cat else set()
    for tag, keywords in SENSITIVE_KEYWORDS.items():
        if any(kw in cat for kw in keywords) or any(kw in text for kw in keywords):
            tags.add(tag)
    return tags


def expand_excluded_tags(excluded: Any) -> set:
    """Map an advertiser's excluded-category tokens onto canonical tags,
    keeping the raw token too (preserved from main.py:4656-4661)."""
    tags = set()
    for excl in norm_category_set(excluded):
        for tag, keywords in SENSITIVE_KEYWORDS.items():
            if excl == tag or any(kw in excl for kw in keywords):
                tags.add(tag)
        tags.add(excl)
    return tags


# ═══════════════════════════════════════════════════════════════════════
# SNAPSHOTS
# ═══════════════════════════════════════════════════════════════════════

def _g(obj: Any, name: str, default=None):
    """Read from an ORM row, a plain object or a dict, uniformly."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class UserProfile:
    """Immutable snapshot of everything eligibility may read about a user.

    Built once per request by `profile_from_user`. Carrying a snapshot rather
    than the ORM row is deliberate: it makes it impossible for an evaluator to
    lazily trigger a query, and it makes the tri-state "is this datum known?"
    question explicit per field.
    """

    __slots__ = ('user_id', 'country', 'commune', 'gender', 'age',
                 'se_tier', 'tier_is_inherited', 'occupation', 'cargo',
                 'company_size_rank', 'estimated_income_usd',
                 'country_per_capita_ppp_usd', 'is_authenticated')

    def __init__(self, user_id=None, country='', commune='', gender='', age=None,
                 se_tier='', tier_is_inherited=False, occupation='', cargo='',
                 company_size_rank=0, estimated_income_usd=None,
                 country_per_capita_ppp_usd=None, is_authenticated=True):
        self.user_id = user_id
        self.country = country
        self.commune = commune
        self.gender = gender
        self.age = age
        self.se_tier = se_tier
        self.tier_is_inherited = tier_is_inherited
        self.occupation = occupation
        self.cargo = cargo
        self.company_size_rank = company_size_rank
        self.estimated_income_usd = estimated_income_usd
        # PPP/PPA per capita — NOT nominal GDP per capita. See
        # _check_market_per_capita for why the distinction is enforced.
        self.country_per_capita_ppp_usd = country_per_capita_ppp_usd
        self.is_authenticated = is_authenticated

    @property
    def has_established_tier(self) -> bool:
        """True when the platform has an economic classification for this
        user that was derived from the user's own data.

        `tier_pre_evaluated` marks a tier INHERITED from a referrer rather
        than computed (main.py:121, 2322-2325). It is a real classification,
        so it is not discarded, but it is flagged so callers/tests can see
        its provenance.
        """
        return bool(self.se_tier)

    def as_dict(self) -> dict:
        return {s: getattr(self, s) for s in self.__slots__}


def profile_from_user(user: Any, country_per_capita_ppp_usd=None, today=None) -> Optional[UserProfile]:
    """Adapter: ORM `User` row -> normalized snapshot.

    `country_per_capita_ppp_usd` is resolved by the caller and injected,
    keeping this module dependency free. It MUST be a PPP/PPA per-capita
    figure (World Bank NY.GNP.PCAP.PP.CD or equivalent), never nominal GDP
    per capita — the two differ by 2-3x for most emerging markets, so
    substituting one for the other silently changes who is eligible.
    """
    if user is None:
        return None
    return UserProfile(
        user_id=_g(user, 'id'),
        country=norm_country(_g(user, 'country', '')),
        commune=norm_commune(_g(user, 'county', '')),
        gender=norm_gender(_g(user, 'gender', '')),
        age=parse_age(_g(user, 'dob', ''), today=today),
        se_tier=norm_tier(_g(user, 'se_tier', '')),
        tier_is_inherited=bool(_g(user, 'tier_pre_evaluated', False)),
        occupation=_base(_g(user, 'profession', '')),
        cargo=norm_cargo(_g(user, 'cargo', '')),
        company_size_rank=norm_company_size(_g(user, 'company_size', '')),
        estimated_income_usd=_g(user, 'estimated_income_usd', None),
        country_per_capita_ppp_usd=country_per_capita_ppp_usd,
        is_authenticated=True,
    )


class ConsultationTarget:
    """Normalized targeting of a consultation (debates row)."""

    __slots__ = ('debate_id', 'is_closed_list', 'countries', 'communes',
                 'gender', 'age_min', 'age_max', 'tiers', 'occupations',
                 'cargos', 'company_size_ranks', 'min_per_capita_usd',
                 'income_min_usd', 'income_max_usd')

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))


def consultation_target_from_debate(debate: Any) -> ConsultationTarget:
    """Adapter: ORM `Debate` row -> normalized targeting snapshot.

    `scope` is deliberately NOT used as a gate. Phase 0 (F-12) found that
    targeting only applied when `scope` happened to equal 'commune'/'country',
    so a consultation with scope='global' and scope_commune='Las Condes' was
    completely unrestricted. Under rule 1 a set targeting field is a
    constraint; `scope` is descriptive metadata only.
    """
    return ConsultationTarget(
        debate_id=_g(debate, 'id'),
        is_closed_list=bool(_g(debate, 'is_closed_list', False)),
        countries=norm_country_set(_g(debate, 'scope_country', '')),
        communes=norm_commune_set(_g(debate, 'scope_commune', '')),
        gender=norm_gender_target(_g(debate, 'target_gender', 'all')),
        age_min=_g(debate, 'target_age_min', None),
        age_max=_g(debate, 'target_age_max', None),
        tiers=norm_tier_set(_g(debate, 'target_se_tiers', '')),
        occupations=norm_occupation_set(_g(debate, 'target_professions', '')),
        cargos=norm_cargo_set(_g(debate, 'target_cargos', '')),
        company_size_ranks=company_size_target_ranks(_g(debate, 'target_company_sizes', '')),
        min_per_capita_usd=_g(debate, 'min_per_capita_usd', None),
        income_min_usd=_g(debate, 'income_min_usd', None),
        income_max_usd=_g(debate, 'income_max_usd', None),
    )


def consultation_is_targeted(debate: Any) -> bool:
    """Is this consultation restricted to a subset of the population?

    CHANGE-002 remediation, JC final rule: PUBLIC RESULTS MUST NOT BECOME A
    BACK DOOR INTO A RESTRICTED CONSULTATION.

    Results publication (`results_visibility`) and consultation-content
    authorization are separate concepts. A consultation that is genuinely
    open to everyone can publish its content with its results, exactly as
    before. One that is restricted — by closed list or by ANY targeting
    dimension — must not hand its protected content to somebody who fails
    canonical consultation authorization just because its results happen to
    be publishable.

    True means "somebody could be excluded from this consultation", so
    results routes must additionally require canonical access.

    Deliberately uses the SAME normalized snapshot the evaluator uses, so a
    dimension can never be considered targeting here and not there.
    """
    t = (debate if isinstance(debate, ConsultationTarget)
         else consultation_target_from_debate(debate))
    if t.is_closed_list:
        return True
    if not is_geo_unrestricted(t.countries):
        return True
    if t.communes:
        return True
    if t.gender and t.gender != 'all':
        return True
    if _age_constrained(t.age_min, t.age_max):
        return True
    if t.tiers and not (t.tiers >= ALL_TIERS):
        return True
    if t.occupations or t.cargos or t.company_size_ranks:
        return True
    try:
        if float(t.min_per_capita_usd or 0) > 0:
            return True
    except (TypeError, ValueError):
        return True
    if t.income_min_usd is not None or t.income_max_usd is not None:
        return True
    return False


class CampaignTarget:
    """Normalized targeting of an ad campaign (ad_campaigns row)."""

    __slots__ = ('campaign_id', 'countries', 'communes', 'gender',
                 'age_min', 'age_max', 'age_ranges', 'tiers', 'occupations',
                 'cargos', 'company_size_ranks', 'min_per_capita_usd',
                 'income_min_usd', 'income_max_usd', 'hnw_only',
                 'min_hnw_score', 'categories', 'excluded_categories')

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))


# Sentinel defaults that mean "not constrained" in ad_campaigns.
_CAMPAIGN_INCOME_MIN_SENTINEL = 0.0
_CAMPAIGN_INCOME_MAX_SENTINEL = 9999.0


def campaign_target_from_campaign(campaign: Any) -> CampaignTarget:
    """Adapter: ORM `AdCampaign` row -> normalized targeting snapshot.

    `target_debate_ids` is intentionally ABSENT. Phase 0 (G-8) found it was
    used as a total targeting bypass; rule 13 makes it a placement/ranking
    input only, so it must not be reachable from an eligibility snapshot.
    """
    inc_max = _g(campaign, 'target_income_max', None)
    # The 9999.0 default is the documented "no limit" sentinel. Phase 0 (F-7)
    # found the old guard was `inc_max < 9999.0`, which silently ignored ANY
    # maximum above the sentinel (e.g. 50000). Treat only the exact sentinel
    # (and non-positive values) as "unset"; honour every real maximum.
    if inc_max is not None:
        try:
            inc_max = float(inc_max)
            if inc_max == _CAMPAIGN_INCOME_MAX_SENTINEL or inc_max <= 0:
                inc_max = None
        except (TypeError, ValueError):
            inc_max = None

    inc_min = _g(campaign, 'target_income_min', None)
    if inc_min is not None:
        try:
            inc_min = float(inc_min)
            if inc_min <= _CAMPAIGN_INCOME_MIN_SENTINEL:
                inc_min = None
        except (TypeError, ValueError):
            inc_min = None

    return CampaignTarget(
        campaign_id=_g(campaign, 'id'),
        countries=norm_country_set(_g(campaign, 'target_country', '')),
        communes=norm_commune_set(_g(campaign, 'target_communes', '')),
        gender=norm_gender_target(_g(campaign, 'target_gender', 'all')),
        age_min=_g(campaign, 'target_age_min', None),
        age_max=_g(campaign, 'target_age_max', None),
        age_ranges=parse_age_ranges(_g(campaign, 'target_age_ranges', '')),
        tiers=norm_tier_set(_g(campaign, 'target_se_tiers', '')),
        occupations=norm_occupation_set(_g(campaign, 'target_professions', '')),
        cargos=norm_cargo_set(_g(campaign, 'target_cargos', '')),
        company_size_ranks=company_size_target_ranks(_g(campaign, 'target_company_sizes', '')),
        min_per_capita_usd=_g(campaign, 'min_per_capita_usd', None),
        income_min_usd=inc_min,
        income_max_usd=inc_max,
        hnw_only=bool(_g(campaign, 'target_hnw_only', False)),
        min_hnw_score=float(_g(campaign, 'min_hnw_score', 0.0) or 0.0),
        categories=norm_category_set(_g(campaign, 'target_categories', '')),
        excluded_categories=_g(campaign, 'excluded_categories', ''),
    )


# ═══════════════════════════════════════════════════════════════════════
# DIMENSION COMPARATORS  (each returns a Reason; tri-state)
# ═══════════════════════════════════════════════════════════════════════

def _check_country(user_country: str, target_countries: set) -> Reason:
    if is_geo_unrestricted(target_countries):
        # GLOBAL / empty: no geographic restriction. Other dimensions still
        # apply — that is handled by the caller ANDing every dimension.
        return Reason('country', NOT_CONSTRAINED, user_country, 'GLOBAL')
    if not user_country:
        return Reason('country', UNKNOWN, '', sorted(target_countries),
                      'user country unknown and country is explicitly targeted')
    if user_country in target_countries:
        return Reason('country', PASS, user_country, sorted(target_countries))
    return Reason('country', FAIL, user_country, sorted(target_countries))


def _check_commune(user_commune: str, target_communes: set) -> Reason:
    if not target_communes:
        return Reason('commune', NOT_CONSTRAINED, user_commune, None)
    if not user_commune:
        return Reason('commune', UNKNOWN, '', sorted(target_communes),
                      'user commune unknown and commune is explicitly targeted')
    if user_commune in target_communes:
        return Reason('commune', PASS, user_commune, sorted(target_communes))
    return Reason('commune', FAIL, user_commune, sorted(target_communes))


def _check_gender(user_gender: str, target_gender: str) -> Reason:
    if target_gender == 'all':
        return Reason('gender', NOT_CONSTRAINED, user_gender, 'all')
    if not user_gender:
        return Reason('gender', UNKNOWN, '', target_gender,
                      'user gender unknown and gender is explicitly targeted')
    if user_gender == target_gender:
        return Reason('gender', PASS, user_gender, target_gender)
    return Reason('gender', FAIL, user_gender, target_gender)


# Schema defaults for the full permitted age span (main.py:204-205, 389-390).
AGE_MIN_DEFAULT = 13
AGE_MAX_DEFAULT = 99


def _age_constrained(age_min, age_max) -> bool:
    lo = AGE_MIN_DEFAULT if age_min is None else age_min
    hi = AGE_MAX_DEFAULT if age_max is None else age_max
    return not (lo <= AGE_MIN_DEFAULT and hi >= AGE_MAX_DEFAULT)


def _check_age(user_age, age_min, age_max) -> Reason:
    """Bounds are INCLUSIVE (preserved from every live path; Phase 0 F-5).

    NOTE the deliberate change from the legacy `if target_age_min and ...`
    idiom: 0 now means "minimum age 0", not "check disabled".
    """
    if not _age_constrained(age_min, age_max):
        return Reason('age', NOT_CONSTRAINED, user_age, None)
    lo = AGE_MIN_DEFAULT if age_min is None else age_min
    hi = AGE_MAX_DEFAULT if age_max is None else age_max
    if user_age is None:
        return Reason('age', UNKNOWN, None, [lo, hi],
                      'user date of birth missing/unparseable and age is explicitly targeted')
    if user_age < lo or user_age > hi:
        return Reason('age', FAIL, user_age, [lo, hi])
    return Reason('age', PASS, user_age, [lo, hi])


def _check_age_ranges(user_age, ranges: list) -> Reason:
    """Multi-bracket age inclusion ('18-24,35-44'): OR within the dimension."""
    if not ranges:
        return Reason('age_ranges', NOT_CONSTRAINED, user_age, None)
    if user_age is None:
        return Reason('age_ranges', UNKNOWN, None, ranges,
                      'user date of birth missing/unparseable and age ranges are targeted')
    for lo, hi in ranges:
        if lo <= user_age <= hi:
            return Reason('age_ranges', PASS, user_age, ranges)
    return Reason('age_ranges', FAIL, user_age, ranges)


def _check_tier(profile: UserProfile, target_tiers: set) -> Reason:
    """Socioeconomic tier — the consultant-facing economic segmentation (rule 8).

    This is where MATERIAL SUFFICIENCY (rule 7) bites. The requested condition
    is about the TIER, not about the raw inputs that produced it. So:

      * tier established and inside the target set  -> PASS, regardless of
        which individual inputs (company size, cargo, ...) happen to be
        missing. They are not material: the requested condition is already
        proven.
      * tier established and outside the set        -> FAIL.
      * no tier established at all                  -> UNKNOWN. Now the
        missing economic inputs ARE material, because the requested condition
        cannot be decided without them.
    """
    if not target_tiers or target_tiers >= ALL_TIERS:
        return Reason('se_tier', NOT_CONSTRAINED, profile.se_tier, 'A,B,C,D')
    if not profile.has_established_tier:
        return Reason('se_tier', UNKNOWN, '', sorted(target_tiers),
                      'user has no established socioeconomic tier; economic '
                      'inputs are material to this condition and must be computed')
    if profile.se_tier in target_tiers:
        detail = 'tier inherited from referrer' if profile.tier_is_inherited else ''
        return Reason('se_tier', PASS, profile.se_tier, sorted(target_tiers), detail)
    return Reason('se_tier', FAIL, profile.se_tier, sorted(target_tiers))


def _check_occupation(user_occupation: str, target_occupations: set) -> Reason:
    if not target_occupations:
        return Reason('occupation', NOT_CONSTRAINED, user_occupation, None)
    user_values = occupation_match_values(user_occupation)
    if not user_values:
        return Reason('occupation', UNKNOWN, '', sorted(target_occupations),
                      'user occupation unknown and occupation is explicitly targeted')
    if user_values & target_occupations:
        return Reason('occupation', PASS, sorted(user_values), sorted(target_occupations))
    return Reason('occupation', FAIL, sorted(user_values), sorted(target_occupations))


def _check_cargo(user_cargo: str, target_cargos: set) -> Reason:
    if not target_cargos:
        return Reason('cargo', NOT_CONSTRAINED, user_cargo, None)
    if not user_cargo:
        return Reason('cargo', UNKNOWN, '', sorted(target_cargos),
                      'user cargo unknown and cargo is explicitly targeted')
    if user_cargo in target_cargos:
        return Reason('cargo', PASS, user_cargo, sorted(target_cargos))
    return Reason('cargo', FAIL, user_cargo, sorted(target_cargos))


def _check_company_size(user_rank: int, target_ranks: set) -> Reason:
    """Rule 7, explicit case: an explicitly filtered company size with an
    unknown user value is NOT PROVEN -> UNKNOWN (never assumed favourably)."""
    if not target_ranks:
        return Reason('company_size', NOT_CONSTRAINED, user_rank, None)
    if not user_rank:
        return Reason('company_size', UNKNOWN, 0, sorted(target_ranks),
                      'user company size unknown and company size is explicitly '
                      'targeted; compliance is not proven')
    if user_rank in target_ranks:
        return Reason('company_size', PASS, user_rank, sorted(target_ranks))
    return Reason('company_size', FAIL, user_rank, sorted(target_ranks))


# Provenance labels for the market thermometer, so a decision can always say
# WHERE its PPP figure came from.
PPP_SOURCE_DB = 'world_countries.gdp_per_capita_usd (World Bank NY.GNP.PCAP.PP.CD)'
PPP_SOURCE_REFERENCE = 'marketer_table_v2.GNI_PER_CAPITA (GNI per capita PPP, 2023)'


def _check_market_per_capita(country_per_capita_ppp_usd, minimum) -> Reason:
    """Country/market economic thermometer (rule 9) — PPP/PPA per capita.

    JC's final decision: this MUST be per-capita PPP/PPA, never nominal GDP
    per capita. The two diverge by 2-3x across emerging markets (Chile PPP
    ~$24k vs nominal ~$15k; India PPP ~$7k vs nominal ~$2.4k), so silently
    substituting one for the other would change who is eligible for every
    market-thresholded consultation and campaign.

    Three axes are deliberately kept apart and must never be conflated:
      * this one   — the COUNTRY/market thermometer (PPP per capita)
      * se_tier    — the INDIVIDUAL's socioeconomic tier (rule 8)
      * income     — the INDIVIDUAL's estimated income (legacy only)

    The value is injected by the caller; main._country_per_capita_ppp_usd
    resolves it from the authoritative PPP sources (see PPP_SOURCE_*).
    """
    try:
        minimum = float(minimum or 0)
    except (TypeError, ValueError):
        minimum = 0.0
    if minimum <= 0:
        return Reason('market_per_capita', NOT_CONSTRAINED, country_per_capita_ppp_usd, None)
    if country_per_capita_ppp_usd is None:
        return Reason('market_per_capita', UNKNOWN, None, minimum,
                      "user country's PPP per-capita figure unavailable and a market "
                      'threshold is explicitly targeted')
    try:
        value = float(country_per_capita_ppp_usd)
    except (TypeError, ValueError):
        return Reason('market_per_capita', UNKNOWN, country_per_capita_ppp_usd, minimum,
                      'PPP per-capita figure not numeric')
    if value >= minimum:
        return Reason('market_per_capita', PASS, value, minimum)
    return Reason('market_per_capita', FAIL, value, minimum)


# AdCampaign.target_income_min/max are documented in the schema as an *index*
# (0-9999, main.py:385-386), but the only code that ever read them compared
# them against `estimated_income_usd` — an ANNUAL NOMINAL USD figure. Live rows
# may therefore hold either unit, and the row itself does not say which.
#
# A band whose bounds both sit inside the documented index domain cannot be
# meaningfully compared to an annual-USD income: read as USD it excludes
# everyone (a $9,999/yr ceiling), read as an index it is not comparable at all.
# Neither reading can PROVE compliance, so such a band resolves to UNRESOLVED
# with an explicit reason rather than silently denying the whole audience.
#
# This is a diagnosis, not a relaxation: UNRESOLVED still denies delivery
# (Decision.allowed is False). It exists so the ambiguity surfaces in
# /admin/debug-ads and the impact simulation instead of looking like a
# correctly-targeted campaign that simply has no matching users.
LEGACY_INCOME_INDEX_CEILING = 9999.0


def _check_income_band(user_income, lo, hi) -> Reason:
    """Legacy raw-income band.

    Rule 8: raw individual income is NOT the primary consultant-facing
    mechanism (tier is). This comparator exists solely to keep honouring
    bands already stored on live rows; nothing new should target it.
    Bounds inclusive, matching every legacy path.
    """
    has_lo = lo is not None
    has_hi = hi is not None
    if not has_lo and not has_hi:
        return Reason('income_band', NOT_CONSTRAINED, user_income, None)

    # Ambiguous legacy unit — see the note above.
    bounds = [float(b) for b in (lo, hi) if b is not None]
    if bounds and max(bounds) <= LEGACY_INCOME_INDEX_CEILING:
        return Reason('income_band', UNKNOWN, user_income, [lo, hi],
                      'income band is stored in the legacy index domain (0-9999) '
                      'and cannot be compared to annual USD income; re-express '
                      'this targeting as a socioeconomic tier (rule 8)')

    if user_income is None:
        return Reason('income_band', UNKNOWN, None, [lo, hi],
                      'user estimated income unavailable and an income band is targeted')
    try:
        value = float(user_income)
    except (TypeError, ValueError):
        return Reason('income_band', UNKNOWN, user_income, [lo, hi], 'income not numeric')
    if has_lo and value < float(lo):
        return Reason('income_band', FAIL, value, [lo, hi])
    if has_hi and value > float(hi):
        return Reason('income_band', FAIL, value, [lo, hi])
    return Reason('income_band', PASS, value, [lo, hi])


def _check_closed_list(is_member: Optional[bool]) -> Reason:
    """Rule 6: THE LIST IS THE AUDIENCE."""
    if is_member is None:
        return Reason('closed_list', UNKNOWN, None, 'member required',
                      'closed-list membership was not resolved by the caller')
    if is_member:
        return Reason('closed_list', PASS, True, 'member required')
    return Reason('closed_list', FAIL, False, 'member required')


# ═══════════════════════════════════════════════════════════════════════
# CANONICAL CONSULTATION EVALUATOR
# ═══════════════════════════════════════════════════════════════════════

def evaluate_consultation(profile: Optional[UserProfile], debate: Any,
                          closed_list_member: Optional[bool] = None) -> Decision:
    """THE canonical consultation eligibility decision.

    Every listing path, the direct-access path and the vote endpoint call
    this and gate on `.allowed`. There is no other legitimate way to decide
    whether a user may see or vote a consultation.

    Rule 2: an unauthenticated caller has no profile, and eligibility cannot
    be determined without one, so there is nothing to grant.

    Rule 6: when the consultation is explicitly closed-list, the list IS the
    audience — demographic/economic targeting neither shrinks nor expands it.
    """
    if profile is None or not profile.is_authenticated:
        return Decision(INELIGIBLE, [
            Reason('authentication', FAIL, None, 'authenticated user required',
                   'unauthenticated callers cannot be evaluated for eligibility')
        ])

    target = (debate if isinstance(debate, ConsultationTarget)
              else consultation_target_from_debate(debate))

    if target.is_closed_list:
        # THE LIST IS THE AUDIENCE. Ordinary targeting is deliberately not
        # evaluated: it must not shrink the list (a listed user stays
        # eligible) and it must not expand it (an unlisted user stays out).
        return _combine([_check_closed_list(closed_list_member)])

    reasons = [
        _check_country(profile.country, target.countries),
        _check_commune(profile.commune, target.communes),
        _check_gender(profile.gender, target.gender),
        _check_age(profile.age, target.age_min, target.age_max),
        _check_tier(profile, target.tiers),
        _check_occupation(profile.occupation, target.occupations),
        _check_cargo(profile.cargo, target.cargos),
        _check_company_size(profile.company_size_rank, target.company_size_ranks),
        _check_market_per_capita(profile.country_per_capita_ppp_usd, target.min_per_capita_usd),
        _check_income_band(profile.estimated_income_usd,
                           target.income_min_usd, target.income_max_usd),
    ]
    return _combine(reasons)


# ═══════════════════════════════════════════════════════════════════════
# CANONICAL CAMPAIGN EVALUATOR
# ═══════════════════════════════════════════════════════════════════════

def evaluate_campaign(profile: Optional[UserProfile], campaign: Any,
                      hnw_score: float = 0.0, hnw_verified: bool = False) -> Decision:
    """THE canonical user<->campaign eligibility decision (rule 13 barrier 2).

    `hnw_score` / `hnw_verified` are passed in rather than read off the
    profile because they are an advertiser-facing luxury signal, not part of
    the core economic profile.

    Rule 15: nothing here reads weights, cpm, budget or frequency caps.
    """
    if profile is None:
        # Anonymous ad serving. A campaign that targets nothing user-specific
        # may still be served; one that does cannot, because compliance is
        # unproven (rule 7, rule 20). This falls out naturally: every
        # user-specific comparator returns UNKNOWN for an empty profile.
        profile = UserProfile(is_authenticated=False)

    target = (campaign if isinstance(campaign, CampaignTarget)
              else campaign_target_from_campaign(campaign))

    reasons = [
        _check_country(profile.country, target.countries),
        _check_commune(profile.commune, target.communes),
        _check_gender(profile.gender, target.gender),
        _check_age(profile.age, target.age_min, target.age_max),
        _check_age_ranges(profile.age, target.age_ranges),
        _check_tier(profile, target.tiers),
        _check_occupation(profile.occupation, target.occupations),
        _check_cargo(profile.cargo, target.cargos),
        _check_company_size(profile.company_size_rank, target.company_size_ranks),
        _check_market_per_capita(profile.country_per_capita_ppp_usd, target.min_per_capita_usd),
        _check_income_band(profile.estimated_income_usd,
                           target.income_min_usd, target.income_max_usd),
    ]

    # ── HNW (luxury) targeting ──
    if target.hnw_only:
        if hnw_verified:
            reasons.append(Reason('hnw_verified', PASS, True, True))
        else:
            reasons.append(Reason('hnw_verified', FAIL, bool(hnw_verified), True))
    if target.min_hnw_score and target.min_hnw_score > 0:
        try:
            score = float(hnw_score or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if score >= target.min_hnw_score:
            reasons.append(Reason('hnw_score', PASS, score, target.min_hnw_score))
        else:
            reasons.append(Reason('hnw_score', FAIL, score, target.min_hnw_score))

    return _combine(reasons)


# ═══════════════════════════════════════════════════════════════════════
# CAMPAIGN <-> CONSULTATION COMPATIBILITY  (rule 13 barrier 1)
# ═══════════════════════════════════════════════════════════════════════

def campaign_consultation_compatible(campaign: Any, debate: Any) -> Decision:
    """Barrier 1: may this campaign run alongside this consultation at all?

    Content/brand-safety and audience-envelope compatibility. Deliberately
    SEPARATE from user eligibility (barrier 2) — passing this never
    authorizes delivery to any particular user.

    Association (target_debate_ids) is NOT consulted here and cannot appear:
    it is a placement hint only (rule 13).
    """
    if debate is None:
        # No consultation context (e.g. /ads/featured). There is nothing to
        # be incompatible with; user eligibility still applies in full.
        return Decision(ELIGIBLE, [Reason('consultation_context', NOT_CONSTRAINED)])

    target = (campaign if isinstance(campaign, CampaignTarget)
              else campaign_target_from_campaign(campaign))

    debate_category = _g(debate, 'category', '')
    debate_title = _g(debate, 'title', '')
    debate_countries = norm_country_set(_g(debate, 'scope_country', ''))

    reasons = []

    # ── Brand safety: excluded categories (exclusion precedes inclusion) ──
    content_tags = derive_content_tags(debate_category, debate_title)
    excluded_tags = expand_excluded_tags(target.excluded_categories)
    overlap = content_tags & excluded_tags
    if excluded_tags:
        if overlap:
            reasons.append(Reason('excluded_categories', FAIL,
                                  sorted(content_tags), sorted(excluded_tags)))
        else:
            reasons.append(Reason('excluded_categories', PASS,
                                  sorted(content_tags), sorted(excluded_tags)))
    else:
        reasons.append(Reason('excluded_categories', NOT_CONSTRAINED))

    # ── Positive category targeting ──
    if target.categories:
        cat = norm_category(debate_category)
        if cat and cat in target.categories:
            reasons.append(Reason('target_categories', PASS, cat, sorted(target.categories)))
        else:
            reasons.append(Reason('target_categories', FAIL, cat, sorted(target.categories)))
    else:
        reasons.append(Reason('target_categories', NOT_CONSTRAINED))

    # ── Geographic envelope ──
    # A campaign restricted to countries that the consultation's own scope
    # can never contain is incompatible. A GLOBAL consultation or a GLOBAL
    # campaign imposes no restriction here (rule 1).
    if is_geo_unrestricted(target.countries) or is_geo_unrestricted(debate_countries):
        reasons.append(Reason('country_envelope', NOT_CONSTRAINED,
                              sorted(debate_countries), sorted(target.countries)))
    elif target.countries & debate_countries:
        reasons.append(Reason('country_envelope', PASS,
                              sorted(debate_countries), sorted(target.countries)))
    else:
        reasons.append(Reason('country_envelope', FAIL,
                              sorted(debate_countries), sorted(target.countries)))

    # ── Audience envelope: gender ──
    debate_gender = norm_gender_target(_g(debate, 'target_gender', 'all'))
    if target.gender != 'all' and debate_gender != 'all' and target.gender != debate_gender:
        reasons.append(Reason('gender_envelope', FAIL, debate_gender, target.gender))
    else:
        reasons.append(Reason('gender_envelope', PASS, debate_gender, target.gender))

    # ── Audience envelope: age overlap ──
    d_lo = _g(debate, 'target_age_min', None)
    d_hi = _g(debate, 'target_age_max', None)
    d_lo = AGE_MIN_DEFAULT if d_lo is None else d_lo
    d_hi = AGE_MAX_DEFAULT if d_hi is None else d_hi
    c_lo = AGE_MIN_DEFAULT if target.age_min is None else target.age_min
    c_hi = AGE_MAX_DEFAULT if target.age_max is None else target.age_max
    if max(c_lo, d_lo) > min(c_hi, d_hi):
        reasons.append(Reason('age_envelope', FAIL, [d_lo, d_hi], [c_lo, c_hi]))
    else:
        reasons.append(Reason('age_envelope', PASS, [d_lo, d_hi], [c_lo, c_hi]))

    return _combine(reasons)


def evaluate_campaign_for_user_in_consultation(
    profile: Optional[UserProfile], campaign: Any, debate: Any,
    hnw_score: float = 0.0, hnw_verified: bool = False,
) -> Decision:
    """Both barriers, in the order rule 13 mandates:

        campaign <-> consultation compatibility
                        THEN
        user <-> applicable eligibility

    Association may affect placement/ranking; it can never authorize an
    otherwise ineligible user.
    """
    compat = campaign_consultation_compatible(campaign, debate)
    if not compat.allowed:
        return compat
    user_dec = evaluate_campaign(profile, campaign,
                                 hnw_score=hnw_score, hnw_verified=hnw_verified)
    return Decision(user_dec.verdict, compat.reasons + user_dec.reasons)
