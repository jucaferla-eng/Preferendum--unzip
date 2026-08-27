"""
simulate_socioeconomic_impact.py — CHANGE-003 dry-run impact analysis.

Answers, BEFORE anything touches production: if we apply the corrected policy
(real PPP, income as the primary signal, no promotion from age/title/company),
who changes tier and why?

Two modes:

    python3 simulate_socioeconomic_impact.py            # synthetic population
    python3 simulate_socioeconomic_impact.py --db X.db  # a LOCAL sqlite copy

NOTHING IS WRITTEN in either mode. This never connects to production.

The OLD algorithm is reimplemented here faithfully — including its two
defects — so the comparison is honest rather than flattering:

  * the PPP column read as if it were nominal GDP (median = value x 0.50,
    "low income country" threshold at <10,000)
  * `_tier_rank` (A=4..D=1, 1-based) indexed into `tier_ladder`
    (['D','C','B','A'], 0-based), which promoted C->A and D->B on age alone
"""

import argparse
import sqlite3
import sys

import socioeconomic as S


# ═══════════════════════════════════════════════════════════════════════
# The OLD algorithm, reproduced with its defects intact
# ═══════════════════════════════════════════════════════════════════════

_OLD_CARGO_TIER = {'ceo': 'A', 'director': 'A', 'gerente': 'B',
                   'jefe': 'C', 'analista': 'C', 'operario': 'D'}
_BIG_COMPANY = {'251-1000', '+1000'}


def _old_tier_rank(t):
    return {'A': 4, 'B': 3, 'C': 2, 'D': 1}.get(t, 0)


def old_algorithm(person, ppp_value):
    """Returns the tier the pre-CHANGE-003 code would have produced."""
    ladder = ['D', 'C', 'B', 'A']

    # DEFECT 1 — the PPP figure treated as nominal GDP.
    country_gdp = ppp_value
    is_low_gdp = bool(country_gdp and country_gdp < 10000)

    commune_tier = person.get('commune_tier')
    profession_tier = person.get('profession_tier')
    cargo_tier = _OLD_CARGO_TIER.get(person.get('cargo', ''), None)

    if cargo_tier and person.get('company_size') in _BIG_COMPANY:
        cargo_tier = ladder[min(_old_tier_rank(cargo_tier), 3)]

    if is_low_gdp and commune_tier:
        base = commune_tier
    else:
        cands = [t for t in (commune_tier, profession_tier) if t]
        base = max(cands, key=_old_tier_rank) if cands else None

    tier = None
    if base and cargo_tier:
        if _old_tier_rank(cargo_tier) > _old_tier_rank(base) + 1:
            cargo_tier = ladder[min(_old_tier_rank(base), 3)]
        tier = max(base, cargo_tier, key=_old_tier_rank)
    elif base:
        tier = base
    elif cargo_tier:
        tier = cargo_tier

    # DEFECT 2 — the 1-based rank indexed into the 0-based ladder.
    age = person.get('age')
    if tier and age:
        r = _old_tier_rank(tier)
        if age < 33:
            tier = ladder[max(r - 2, 0)]
        elif age > 45:
            tier = ladder[min(r + 1, 3)]
    return tier


def new_algorithm(person, ctx):
    obs = []
    if person.get('declared_income_usd') is not None:
        obs.append(S.IncomeObservation(
            amount=person['declared_income_usd'], currency='USD',
            period=S.PERIOD_ANNUAL,
            source=(S.DECLARED_CONFIRMED if person.get('income_confirmed')
                    else S.DECLARED)))
    if person.get('estimated_income_usd') is not None:
        obs.append(S.IncomeObservation(
            amount=person['estimated_income_usd'], currency='USD',
            period=S.PERIOD_ANNUAL, source=S.ESTIMATED_OCCUPATION))
    return S.classify(obs, ctx, {
        'cargo': person.get('cargo', ''),
        'company_size_rank': person.get('company_size_rank', 0),
    })


# ═══════════════════════════════════════════════════════════════════════
# Synthetic population
# ═══════════════════════════════════════════════════════════════════════

# PPP per capita (GNI PPP) for a spread of markets. Fixtures for simulation
# only — the running system reads its figures from the audited sources.
COUNTRIES = {
    'CL': 24013, 'US': 76400, 'NG': 5700, 'IN': 9200,
    'DE': 63200, 'BR': 17000, 'JP': 47000,
}

_CARGOS = ['', 'operario', 'analista', 'jefe', 'gerente', 'director', 'ceo']
_SIZES = ['', '1-10', '11-50', '51-250', '251-1000', '+1000']
_SIZE_RANK = {'': 0, '1-10': 1, '11-50': 2, '51-250': 3, '251-1000': 4, '+1000': 5}


def synthetic_population(n_per_country=120):
    """Deterministic spread — no RNG, so the report is reproducible."""
    people = []
    for ci, (cc, ppp) in enumerate(COUNTRIES.items()):
        median = ppp * S.DERIVED_MEDIAN_FROM_PPP_RATIO
        for i in range(n_per_country):
            age = 20 + (i * 7) % 50
            cargo = _CARGOS[i % len(_CARGOS)]
            size = _SIZES[(i // 3) % len(_SIZES)]
            # income spread from 0.2x to ~4x the country median
            income = median * (0.2 + ((i % 20) * 0.2))
            has_declared = (i % 3) != 0
            people.append({
                'id': f'{cc}-{i}',
                'country': cc,
                'age': age,
                'cargo': cargo,
                'company_size': size,
                'company_size_rank': _SIZE_RANK[size],
                'declared_income_usd': round(income) if has_declared else None,
                'income_confirmed': (i % 6) == 0,
                'estimated_income_usd': round(income * 1.1),
                # what the OLD algorithm would have had available
                'commune_tier': ['D', 'C', 'B', 'A'][(i // 5) % 4],
                'profession_tier': ['D', 'C', 'B', 'A'][(i // 7) % 4],
            })
    return people


# ═══════════════════════════════════════════════════════════════════════
# Report
# ═══════════════════════════════════════════════════════════════════════

def run(people, ppp_by_country):
    rows, old_dist, new_dist, promo_removed = [], {}, {}, 0
    for p in people:
        ppp = ppp_by_country.get(p['country'])
        ctx = S.CountryEconomicContext(
            country=p['country'], ppp_per_capita_usd=ppp,
            ppp_source='test_fixture_ppp')
        old = old_algorithm(p, ppp)
        cls = new_algorithm(p, ctx)
        rows.append((p['id'], old, cls))
        old_dist[old or '-'] = old_dist.get(old or '-', 0) + 1
        new_dist[cls.tier or '-'] = new_dist.get(cls.tier or '-', 0) + 1
        if old and cls.resolved and S.tier_index(old) > S.tier_index(cls.tier):
            promo_removed += 1

    rep = S.impact_report(rows)

    print('=' * 78)
    print('CHANGE-003 SOCIOECONOMIC RECLASSIFICATION — DRY RUN')
    print('=' * 78)
    print(f'policy version : {rep["policy_version"]}')
    print(f'population     : {rep["evaluable"]}')
    print()
    print('OUTCOMES')
    for k, v in rep['counts'].items():
        print(f'  {k:20} {v:6}')
    print(f'  {"WOULD CHANGE TIER":20} {rep["would_change"]:6}')
    print(f'  {"unresolved":20} {rep["unresolved"]:6}')
    print()
    print('TIER DISTRIBUTION           old -> new')
    for t in ('A', 'B', 'C', 'D', '-'):
        o, n = old_dist.get(t, 0), new_dist.get(t, 0)
        if o or n:
            print(f'  {t:3} {o:8} -> {n:8}   ({n - o:+d})')
    print()
    print('TRANSITIONS (old -> proposed)')
    for k, v in sorted(rep['transitions'].items(), key=lambda kv: -kv[1])[:15]:
        print(f'  {k:12} {v:6}')
    if rep['unresolved_reasons']:
        print()
        print('UNRESOLVED REASONS')
        for k, v in rep['unresolved_reasons'].items():
            print(f'  {v:6}  {k}')
    print()
    print(f'Users the old code had promoted ABOVE what their income supports: {promo_removed}')
    print()
    print(rep['note'])
    print()
    print('NOTHING WAS WRITTEN. Applying this requires explicit authorization.')
    return rep


def load_from_sqlite(path):
    """Read-only, enforced by the OS/SQLite — not merely by convention.

    CHANGE-003 remediation (finding G): a prior version opened the copy with
    a plain `sqlite3.connect(path)` despite the module's own docstring
    claiming read-only access. A plain connection can write; nothing here
    actually stopped it. `file:<path>?mode=ro` with uri=True is the same
    genuinely-read-only pattern simulate_matching_impact.py (CHANGE-002)
    already uses: SQLite itself refuses any write against the connection,
    so a mistake in THIS script cannot mutate the copy — let alone
    production, which this tool never contacts either way.
    """
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    people = []
    for r in conn.execute('SELECT * FROM users'):
        d = {k: r[k] for k in r.keys()}
        people.append({
            'id': d.get('id'),
            'country': (d.get('country') or '').upper()[:2],
            'age': None,
            'cargo': d.get('cargo') or '',
            'company_size': d.get('company_size') or '',
            'company_size_rank': _SIZE_RANK.get(d.get('company_size') or '', 0),
            'declared_income_usd': d.get('declared_income_annual_usd'),
            'income_confirmed': bool(d.get('declared_income_confirmed')),
            'estimated_income_usd': d.get('estimated_income_usd'),
            'commune_tier': d.get('se_tier'),
            'profession_tier': None,
        })
    conn.close()
    return people


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', help='LOCAL sqlite copy only — never production')
    args = ap.parse_args()
    if args.db:
        print(f'Using local sqlite: {args.db} (read-only)')
        people = load_from_sqlite(args.db)
        if not people:
            print('No users found.')
            return 0
    else:
        print('No --db given; using the synthetic population.')
        people = synthetic_population()
    run(people, COUNTRIES)
    return 0


if __name__ == '__main__':
    sys.exit(main())
