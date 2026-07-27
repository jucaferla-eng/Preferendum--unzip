"""
nuts_income_agent.py
────────────────────
Importa ingreso disponible por región NUTS2 (Eurostat) a commune_market_data.

Fuente: Eurostat nama_10r_2hhinc — B6N BAL EUR_HAB (ingreso disponible neto
        por habitante en euros corrientes). ~240 regiones NUTS2, EU27.

Flujo:
  1. Descarga la serie via API JSON de Eurostat (sin registro, gratuito).
  2. Para cada región toma el año más reciente disponible (2024 > 2023 > 2022).
  3. Calcula percentil de ingreso dentro del grupo de ingreso del país
     (H1/H2/M1/M2L) usando la misma metodología de commune_agent.py.
  4. Asigna se_tier A/B/C/D con los mismos cortes que el resto del sistema.
  5. Upsert en commune_market_data: commune=NUTS_CODE, country=ISO2.
"""

import json
import urllib.request
import urllib.error
from typing import Optional

# ── Mapeo NUTS2-prefix → ISO2 ────────────────────────────────────────────────
# Eurostat usa EL (Grecia) y UK (RU pre-Brexit) — normalizamos a ISO estándar.
_NUTS_PREFIX_TO_ISO: dict[str, str] = {
    'AT': 'AT', 'BE': 'BE', 'BG': 'BG', 'CY': 'CY', 'CZ': 'CZ',
    'DE': 'DE', 'DK': 'DK', 'EE': 'EE', 'EL': 'GR', 'ES': 'ES',
    'FI': 'FI', 'FR': 'FR', 'HR': 'HR', 'HU': 'HU', 'IE': 'IE',
    'IT': 'IT', 'LT': 'LT', 'LU': 'LU', 'LV': 'LV', 'MT': 'MT',
    'NL': 'NL', 'PL': 'PL', 'PT': 'PT', 'RO': 'RO', 'SE': 'SE',
    'SI': 'SI', 'SK': 'SK', 'UK': 'GB',  # UK post-Brexit — mantenemos datos
}

# Grupo de ingreso por país (mismo que rental_price_agent.py)
_COUNTRY_GROUP: dict[str, str] = {}
for _c in ['AT','BE','DE','DK','FI','IE','LU','NL','SE','GB']:
    _COUNTRY_GROUP[_c] = 'H1'
for _c in ['CY','CZ','EE','ES','FR','GR','HR','HU','IT','LT','LV',
           'MT','PL','PT','RO','SI','SK','BG']:
    _COUNTRY_GROUP[_c] = 'H2'

# Cortes de tier (percentil dentro del grupo de ingreso)
_TIER_CUTS: dict[str, dict[str, int]] = {
    'H1': {'A': 80, 'B': 60, 'C': 35, 'D': 15},
    'H2': {'A': 88, 'B': 68, 'C': 40, 'D': 18},
}


def _fetch_nuts2_income() -> list[tuple[str, str, int]]:
    """Descarga ingreso disponible NUTS2 de Eurostat. Retorna [(nuts_code, iso2, eur_hab)]."""
    url = (
        'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'
        'nama_10r_2hhinc?format=JSON&lang=en&unit=EUR_HAB&sinceTimePeriod=2022'
    )
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        raise RuntimeError(f'Eurostat API error: {e}')

    dims   = data['dimension']
    size   = data['size']  # [1,1,3,13,390,3]
    values = data['value']

    geo_idx  = dims['geo']['category']['index']
    geo_lbl  = dims['geo']['category']['label']
    time_idx = dims['time']['category']['index']

    # Strides para [freq, unit, direct, na_item, geo, time]
    strides = [1]
    for sz in reversed(size[1:]):
        strides.insert(0, strides[0] * sz)

    # direct=BAL=2, na_item=B6N=2 (ingreso disponible neto, balance)
    d_bal  = dims['direct']['category']['index'].get('BAL', 2)
    n_b6n  = dims['na_item']['category']['index'].get('B6N', 2)

    # Por región: tomar el año más reciente con dato
    best: dict[str, tuple[str, int]] = {}  # nuts_code → (year, value)
    for geo_code, g_i in geo_idx.items():
        if len(geo_code) != 4:
            continue
        prefix = geo_code[:2]
        if prefix not in _NUTS_PREFIX_TO_ISO:
            continue
        for yr, t_i in time_idx.items():
            flat = (d_bal * strides[2] + n_b6n * strides[3]
                    + g_i * strides[4] + t_i * strides[5])
            val = values.get(str(flat))
            if val is None:
                continue
            prev = best.get(geo_code)
            if prev is None or yr > prev[0]:
                best[geo_code] = (yr, int(val))

    result = []
    for nuts_code, (yr, val) in best.items():
        iso2 = _NUTS_PREFIX_TO_ISO[nuts_code[:2]]
        result.append((nuts_code, iso2, val))
    return result


def _compute_percentiles(rows: list[tuple[str, str, int]]) -> list[tuple[str, str, int, float, str]]:
    """Calcula percentil de ingreso dentro del grupo del país y asigna tier."""
    from collections import defaultdict

    by_group: dict[str, list[int]] = defaultdict(list)
    for nuts_code, iso2, eur in rows:
        grp = _COUNTRY_GROUP.get(iso2, 'H2')
        by_group[grp].append(eur)

    # Percentiles dentro del grupo (misma metodología que commune_agent.py)
    group_sorted: dict[str, list[int]] = {
        g: sorted(vals) for g, vals in by_group.items()
    }

    def _pct(val: int, grp: str) -> float:
        arr = group_sorted.get(grp, [val])
        below = sum(1 for v in arr if v < val)
        return round(100.0 * below / len(arr), 1)

    def _tier(pct: float, grp: str) -> str:
        cuts = _TIER_CUTS.get(grp, _TIER_CUTS['H2'])
        if pct >= cuts['A']:
            return 'A'
        if pct >= cuts['B']:
            return 'B'
        if pct >= cuts['C']:
            return 'C'
        if pct >= cuts['D']:
            return 'D'
        return 'E'

    result = []
    for nuts_code, iso2, eur in rows:
        grp = _COUNTRY_GROUP.get(iso2, 'H2')
        pct = _pct(eur, grp)
        tier = _tier(pct, grp)
        result.append((nuts_code, iso2, eur, pct, tier))
    return result


def run_nuts_import(db) -> dict:
    """Importa datos NUTS2 Eurostat a commune_market_data. Llamar desde main.py."""
    from sqlalchemy import text

    print('[nuts_income_agent] Descargando datos Eurostat NUTS2...')
    try:
        raw = _fetch_nuts2_income()
    except Exception as e:
        return {'ok': False, 'error': str(e)}

    print(f'[nuts_income_agent] {len(raw)} regiones NUTS2 descargadas')
    enriched = _compute_percentiles(raw)

    # Referencia: ingreso máximo del grupo para normalizar income_index (0–100)
    from collections import defaultdict
    group_max: dict[str, int] = defaultdict(int)
    for _, iso2, eur, _, _ in enriched:
        grp = _COUNTRY_GROUP.get(iso2, 'H2')
        if eur > group_max[grp]:
            group_max[grp] = eur

    inserted = updated = errors = 0
    try:
        from main import CommuneMarketData  # import local para evitar circular
    except Exception:
        # Fallback: usar SQL directo
        CommuneMarketData = None

    for nuts_code, iso2, eur, pct, tier in enriched:
        grp = _COUNTRY_GROUP.get(iso2, 'H2')
        income_index = round(100.0 * eur / max(group_max[grp], 1), 1)
        try:
            if CommuneMarketData:
                from sqlalchemy.orm import Session
                existing = db.query(CommuneMarketData).filter(
                    CommuneMarketData.commune == nuts_code,
                    CommuneMarketData.country == iso2
                ).first()
                if existing:
                    existing.se_tier      = tier
                    existing.income_index = income_index
                    existing.income_pct   = pct
                    updated += 1
                else:
                    db.add(CommuneMarketData(
                        commune      = nuts_code,
                        country      = iso2,
                        se_tier      = tier,
                        income_index = income_index,
                        income_pct   = pct,
                    ))
                    inserted += 1
            else:
                db.execute(text('''
                    INSERT INTO commune_market_data (commune, country, se_tier, income_index, income_pct)
                    VALUES (:c, :co, :t, :ii, :ip)
                    ON CONFLICT (commune, country) DO UPDATE
                    SET se_tier=excluded.se_tier, income_index=excluded.income_index,
                        income_pct=excluded.income_pct
                '''), {'c': nuts_code, 'co': iso2, 't': tier, 'ii': income_index, 'ip': pct})
                inserted += 1
        except Exception as e:
            print(f'[nuts_income_agent] Error {nuts_code}: {e}')
            errors += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return {'ok': False, 'error': f'DB commit error: {e}'}

    print(f'[nuts_income_agent] Done: {inserted} inserted, {updated} updated, {errors} errors')
    return {
        'ok': True,
        'source': 'Eurostat nama_10r_2hhinc 2022-2024',
        'regions': len(enriched),
        'inserted': inserted,
        'updated': updated,
        'errors': errors,
    }


if __name__ == '__main__':
    # Test standalone: descarga y muestra las 10 regiones más ricas y 10 más pobres
    raw = _fetch_nuts2_income()
    enriched = _compute_percentiles(raw)
    enriched.sort(key=lambda x: -x[2])
    print(f'\n{len(enriched)} regiones NUTS2 — Top 10 más ricas:')
    for nuts, iso, eur, pct, tier in enriched[:10]:
        print(f'  {nuts} ({iso}) | EUR {eur:,}/hab | pct={pct:.1f} | tier={tier}')
    print('\nTop 10 más pobres:')
    for nuts, iso, eur, pct, tier in enriched[-10:]:
        print(f'  {nuts} ({iso}) | EUR {eur:,}/hab | pct={pct:.1f} | tier={tier}')
