"""
simulate_matching_impact.py — CHANGE-002 zero-intersection / audience impact.

READ-ONLY. Touches no database, no network, no production. Stdlib only.

Purpose (rule 17): before approving canonicalization, find configurations that
would move to a zero or unexpectedly tiny audience, and DIAGNOSE the cause,
without weakening security to preserve them.

Two modes:

  1. Synthetic (default). Builds a population whose data-quality distribution
     mirrors what Phase 0 found in the live schema — legacy country spellings,
     missing se_tier, unparseable dob, blank company_size, SOC-coded vs
     slug-coded occupation — and runs every representative consultation and
     campaign configuration against it.

  2. Against a real SQLite snapshot:
         python3 simulate_matching_impact.py --db /path/to/copy.db
     Uses a READ-ONLY URI connection. Never point this at production; take a
     copy. Postgres is not supported here by design (no driver, and no reason
     to hold a production credential in this tool).

Usage:
    python3 simulate_matching_impact.py
    python3 simulate_matching_impact.py --db ./snapshot.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date

import eligibility as E

TODAY = date(2026, 8, 26)

ZERO = 'ZERO AUDIENCE'
TINY = 'TINY AUDIENCE'
OK = 'ok'
TINY_THRESHOLD_PCT = 5.0


class Obj:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# ═══════════════════════════════════════════════════════════════════════
# Synthetic population — mirrors the data-quality mix Phase 0 documented
# ═══════════════════════════════════════════════════════════════════════

def synthetic_population():
    """A population that spans every value each dimension can legitimately
    take, so that a ZERO result is evidence about the CODE or the DATA rather
    than an artifact of a one-sided fixture.

    Each `add()` fans the requested count across gender, birth year, cargo,
    company size and occupation, so no dimension is accidentally empty.
    """
    GENDERS = ['M', 'F']
    DOBS = ['2006-03-01', '2001-07-14', '1994-11-02',
            '1988-05-10', '1979-02-20', '1962-09-30']       # 20,25,31,38,47,63
    CARGOS = ['ceo', 'gerente_general', 'director', 'gerente', 'jefe',
              'analista', 'asistente', 'practicante']
    SIZES = ['1-10', '11-50', '51-250', '251-1000', '+1000']
    OCCS = ['healthcare_pro', 'legal', 'computer', 'admin', 'sales',
            'engineering', 'education', 'construction']

    pop = []

    def add(n, **kw):
        for i in range(n):
            base = dict(country='CL', county='Santiago',
                        gender=GENDERS[i % len(GENDERS)],
                        dob=DOBS[i % len(DOBS)],
                        se_tier='C', tier_pre_evaluated=False,
                        profession=OCCS[i % len(OCCS)],
                        cargo=CARGOS[i % len(CARGOS)],
                        company_size=SIZES[i % len(SIZES)],
                        estimated_income_usd=25000.0,
                        hnw_score=0.0, verified_hnw=False,
                        per_capita=17000.0)
            base.update(kw)
            pop.append(base)

    # ── Well-formed Chilean users across communes and tiers ──
    add(120, county='Las Condes',  se_tier='A', estimated_income_usd=90000)
    add(90,  county='Vitacura',    se_tier='A', estimated_income_usd=110000)
    add(150, county='Conchali',    se_tier='D', estimated_income_usd=11000)
    add(140, county='Maipu',       se_tier='C', estimated_income_usd=18000)
    add(110, county='Providencia', se_tier='B', estimated_income_usd=45000)
    add(80,  county='Nunoa',       se_tier='B', estimated_income_usd=40000)

    # ── Legacy country spelling (Phase 0 F-11: used to be mis-excluded) ──
    add(60, country='Chile', county='Las Condes', se_tier='B')

    # ── Partial / missing profile data (Phase 0 F-1) ──
    add(70, se_tier='', profession='', cargo='', company_size='')  # no tier yet
    add(50, dob='', se_tier='B')                                   # no age
    add(40, dob='garbage', se_tier='C')                            # unparseable dob
    add(45, company_size='', se_tier='B')                          # no company size
    add(35, gender='', se_tier='C')                                # no gender
    add(30, profession='29-1141', se_tier='B')                     # SOC-coded occupation
    add(25, se_tier='BBB')                                         # legacy triple tier
    add(20, se_tier='B', tier_pre_evaluated=True)                  # inherited tier

    # ── A verified-HNW cohort (exists only once /admin/recalculate-hnw runs) ──
    add(25, county='Vitacura', se_tier='A', cargo='ceo', company_size='+1000',
        estimated_income_usd=400000, hnw_score=82.0, verified_hnw=True)

    # ── Non-Chilean users ──
    add(40, country='AR', county='Palermo', se_tier='B', per_capita=13000)
    add(30, country='US', county='10001', se_tier='A',
        estimated_income_usd=120000, per_capita=76000)
    add(20, country='NG', county='Lagos', se_tier='C',
        estimated_income_usd=4000, per_capita=2200)

    out = []
    for i, u in enumerate(pop):
        per_capita = u.pop('per_capita')
        row = Obj(id=i + 1, national_id=f'ID{i:06d}', **u)
        prof = E.profile_from_user(row, country_per_capita_ppp_usd=per_capita, today=TODAY)
        # UserProfile uses __slots__; HNW is an advertiser-facing luxury signal
        # kept outside the core economic profile, so it travels alongside it.
        out.append((prof, float(u.get('hnw_score') or 0.0), bool(u.get('verified_hnw'))))
    return out


# ═══════════════════════════════════════════════════════════════════════
# Representative configurations
# ═══════════════════════════════════════════════════════════════════════

def consultation_configs():
    d = lambda **kw: Obj(**{
        'id': 1, 'title': 'Consulta', 'category': 'general',
        'scope': 'country', 'scope_country': 'CL', 'scope_commune': '',
        'target_gender': 'all', 'target_age_min': 13, 'target_age_max': 99,
        'target_se_tiers': 'A,B,C,D', 'income_min_usd': None, 'income_max_usd': None,
        'target_professions': '', 'target_cargos': '', 'target_company_sizes': '',
        'min_per_capita_usd': 0.0, 'is_closed_list': False, **kw})
    return [
        ('schema-default (CL, everything else open)', d()),
        ('GLOBAL, no other targeting', d(scope_country='GLOBAL')),
        ('GLOBAL + tier A', d(scope_country='GLOBAL', target_se_tiers='A')),
        ('GLOBAL + per-capita>=5000 + tier A',
         d(scope_country='GLOBAL', target_se_tiers='A', min_per_capita_usd=5000)),
        ('commune Las Condes', d(scope_commune='Las Condes')),
        ('commune Conchali', d(scope_commune='Conchali')),
        ('gender F', d(target_gender='F')),
        ('age 18-55', d(target_age_min=18, target_age_max=55)),
        ('tier A,B', d(target_se_tiers='A,B')),
        ('legacy scope=global + commune set (was unrestricted)',
         d(scope='global', scope_commune='Las Condes')),
        ('occupation healthcare_pro', d(target_professions='healthcare_pro')),
        ('cargo ceo', d(target_cargos='ceo')),
        ('company size large', d(target_company_sizes='large')),
        ('income band 50k-200k', d(income_min_usd=50000, income_max_usd=200000)),
        ('narrow stack: Las Condes + A + male + 25-45',
         d(scope_commune='Las Condes', target_se_tiers='A', target_gender='M',
           target_age_min=25, target_age_max=45)),
        ('over-narrow: Vitacura + A + ceo + large + healthcare',
         d(scope_commune='Vitacura', target_se_tiers='A', target_cargos='ceo',
           target_company_sizes='large', target_professions='healthcare_pro')),
    ]


def campaign_configs():
    c = lambda **kw: Obj(**{
        'id': 1, 'advertiser_name': 'Acme', 'title': 'C',
        'target_country': '', 'target_communes': '', 'target_gender': 'all',
        'target_age_min': 13, 'target_age_max': 99, 'target_age_ranges': '',
        'target_se_tiers': 'A,B,C,D', 'target_income_min': 0.0,
        'target_income_max': 9999.0, 'target_professions': '', 'target_cargos': '',
        'target_company_sizes': '', 'target_categories': '', 'excluded_categories': '',
        'min_per_capita_usd': 0.0, 'target_hnw_only': False, 'min_hnw_score': 0.0, **kw})
    return [
        ('schema-default (no targeting at all)', c()),
        ('country CL', c(target_country='CL')),
        ('communes Las Condes,Vitacura', c(target_communes='Las Condes,Vitacura')),
        ('tier A,B', c(target_se_tiers='A,B')),
        ('gender F', c(target_gender='F')),
        ('age_ranges 18-24,55+', c(target_age_ranges='18-24,55+')),
        ('LEGACY income band as INDEX (0-9999)',
         c(target_income_min=200.0, target_income_max=800.0)),
        ('income band as USD 50k-200k',
         c(target_income_min=50000.0, target_income_max=200000.0)),
        ('company sizes large', c(target_company_sizes='large')),
        ('professions healthcare_pro', c(target_professions='healthcare_pro')),
        ('cargos ceo,director', c(target_cargos='ceo,director')),
        ('HNW only', c(target_hnw_only=True)),
        ('min_hnw_score 50', c(min_hnw_score=50.0)),
        ('per-capita >= 30000', c(min_per_capita_usd=30000)),
        ('luxury stack: Vitacura + A + large + ceo',
         c(target_communes='Vitacura', target_se_tiers='A',
           target_company_sizes='large', target_cargos='ceo')),
    ]


# ═══════════════════════════════════════════════════════════════════════
# Evaluation
# ═══════════════════════════════════════════════════════════════════════

def _tally(population, evaluate):
    eligible = unresolved = ineligible = 0
    blocking = {}
    details = {}
    for p, hnw_score, hnw_verified in population:
        dec = evaluate(p, hnw_score, hnw_verified)
        if dec.verdict == E.ELIGIBLE:
            eligible += 1
            continue
        if dec.verdict == E.UNRESOLVED:
            unresolved += 1
        else:
            ineligible += 1
        for dim in dec.blocking_dimensions():
            blocking[dim] = blocking.get(dim, 0) + 1
        for r in dec.reasons:
            if r.outcome == E.UNKNOWN and r.detail:
                details[r.detail] = details.get(r.detail, 0) + 1
    return eligible, unresolved, ineligible, blocking, details


def _classify(eligible, total):
    if eligible == 0:
        return ZERO
    if (eligible / total) * 100 < TINY_THRESHOLD_PCT:
        return TINY
    return OK


def _diagnose(blocking, unresolved, details):
    """Explain WHY an audience collapsed — never a reason to relax targeting."""
    notes = []
    for dim, n in sorted(blocking.items(), key=lambda kv: -kv[1])[:3]:
        notes.append(f'{dim} blocks {n}')
    if unresolved:
        notes.append(f'{unresolved} UNRESOLVED (denied; compliance unproven)')
    for detail, n in sorted(details.items(), key=lambda kv: -kv[1])[:2]:
        notes.append(f'cause: {detail} [{n}]')
    return '; '.join(notes) if notes else 'no blocking dimensions'


def run(population):
    total = len(population)
    print(f'\nPopulation under simulation: {total} users\n')
    findings = []

    print('=' * 78)
    print('CONSULTATIONS')
    print('=' * 78)
    for label, cfg in consultation_configs():
        member = True if getattr(cfg, 'is_closed_list', False) else None
        el, un, inel, blk, det = _tally(
            population,
            lambda p, s, v, cfg=cfg, m=member: E.evaluate_consultation(
                p, cfg, closed_list_member=m))
        status = _classify(el, total)
        pct = el / total * 100
        print(f'  [{status:>13}] {label:<52} {el:>4}/{total} ({pct:5.1f}%)')
        if status != OK:
            note = _diagnose(blk, un, det)
            print(f'{"":18}  -> {note}')
            findings.append(('consultation', label, status, el, note))

    print()
    print('=' * 78)
    print('CAMPAIGNS (user<->campaign barrier)')
    print('=' * 78)
    for label, cfg in campaign_configs():
        el, un, inel, blk, det = _tally(
            population,
            lambda p, s, v, cfg=cfg: E.evaluate_campaign(
                p, cfg, hnw_score=s, hnw_verified=v))
        status = _classify(el, total)
        pct = el / total * 100
        print(f'  [{status:>13}] {label:<52} {el:>4}/{total} ({pct:5.1f}%)')
        if status != OK:
            note = _diagnose(blk, un, det)
            print(f'{"":18}  -> {note}')
            findings.append(('campaign', label, status, el, note))

    print()
    print('=' * 78)
    print('SUMMARY')
    print('=' * 78)
    if not findings:
        print('  No zero-intersection or tiny-audience configurations found.')
    else:
        for kind, label, status, el, note in findings:
            print(f'  {status:<13} {kind:<13} {label}')
            print(f'                              {note}')
    print(f'\n  {len(findings)} configuration(s) need review. '
          f'Security is NOT relaxed to preserve any of them.\n')
    return findings


# ═══════════════════════════════════════════════════════════════════════
# Optional: real SQLite snapshot (READ-ONLY)
# ═══════════════════════════════════════════════════════════════════════

def population_from_sqlite(path, limit=5000):
    uri = f'file:{path}?mode=ro'
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    gni = {}
    try:
        for r in conn.execute('SELECT iso2, gdp_per_capita_usd FROM world_countries'):
            if r['gdp_per_capita_usd'] is not None:
                gni[r['iso2']] = float(r['gdp_per_capita_usd'])
    except sqlite3.Error:
        print('  (world_countries unavailable — market threshold will be UNRESOLVED)')
    out = []
    for r in conn.execute(f'SELECT * FROM users LIMIT {int(limit)}'):
        row = Obj(**{k: r[k] for k in r.keys()})
        cc = E.norm_country(getattr(row, 'country', '') or '')
        prof = E.profile_from_user(row, country_per_capita_ppp_usd=gni.get(cc), today=TODAY)
        out.append((prof,
                    float(getattr(row, 'hnw_score', 0.0) or 0.0),
                    bool(getattr(row, 'verified_hnw', False))))
    conn.close()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', help='path to a READ-ONLY SQLite snapshot (never production)')
    ap.add_argument('--limit', type=int, default=5000)
    args = ap.parse_args()

    if args.db:
        print(f'Loading population from SQLite snapshot: {args.db} (read-only)')
        pop = population_from_sqlite(args.db, args.limit)
    else:
        print('No --db given; using the synthetic population.')
        pop = synthetic_population()

    findings = run(pop)
    return 0 if not any(f[2] == ZERO for f in findings) else 1


if __name__ == '__main__':
    sys.exit(main())
