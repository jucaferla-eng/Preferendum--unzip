from __future__ import annotations
"""
russia_wages_agent.py — Russia wage data import para Preferendum
================================================================
Fuente: Rosstat 2024 (tab4-zpl-2025.xlsx)
  russia_wage_real.csv — salarios por sujeto federal, RUB/mes

85+ sujetos federales + distritos federales + dato nacional.
Conversión: RUB → USD nominal 2024: 1 USD = 90 RUB
"""

import csv
from pathlib import Path
from sqlalchemy import text

RUB_TO_USD = 1 / 90  # tasa nominal 2024

DDL_RUSSIA_WAGES = """
CREATE TABLE IF NOT EXISTS russia_wages (
    id               SERIAL PRIMARY KEY,
    admin_code       TEXT NOT NULL,
    region_name_en   TEXT NOT NULL,
    region_name_ru   TEXT,
    federal_district TEXT,
    admin_level      INTEGER,
    monthly_rub      REAL,
    monthly_usd      REAL,
    annual_usd       REAL,
    income_score     REAL,
    year             INTEGER DEFAULT 2024,
    source           TEXT,
    UNIQUE(admin_code, year)
);
CREATE INDEX IF NOT EXISTS idx_russia_wages_name ON russia_wages(region_name_en);
CREATE INDEX IF NOT EXISTS idx_russia_wages_dist ON russia_wages(federal_district);
"""

_NATIONAL_RUB_MONTH = 89069.3  # dato nacional 2024
# Techo para score = sujeto más alto (Chukotka ~170K+ RUB)
# Usamos 170000 como techo conservador para score 100
_MAX_RUB = 170000.0

# Aliases comunes para ciudades rusas que los usuarios podrían escribir
_CITY_TO_REGION: dict[str, str] = {
    'moscow':            'moscow city',
    'moscú':             'moscow city',
    'moskva':            'moscow city',
    'saint petersburg':  'saint petersburg',
    'san petersburgo':   'saint petersburg',
    'st. petersburg':    'saint petersburg',
    'petersburg':        'saint petersburg',
    'novosibirsk':       'novosibirsk oblast',
    'yekaterinburg':     'sverdlovsk oblast',
    'ekaterinburg':      'sverdlovsk oblast',
    'kazan':             'republic of tatarstan',
    'chelyabinsk':       'chelyabinsk oblast',
    'omsk':              'omsk oblast',
    'samara':            'samara oblast',
    'rostov':            'rostov oblast',
    'ufa':               'republic of bashkortostan',
    'volgograd':         'volgograd oblast',
    'krasnoyarsk':       'krasnoyarsk krai',
    'vladivostok':       'primorsky krai',
    'perm':              'perm krai',
    'voronezh':          'voronezh oblast',
    'krasnodar':         'krasnodar krai',
    'saratov':           'saratov oblast',
    'tyumen':            'tyumen oblast',
    'tolyatti':          'samara oblast',
    'izhevsk':           'udmurt republic',
    'irkutsk':           'irkutsk oblast',
    'khabarovsk':        'khabarovsk krai',
    'makhachkala':       'republic of dagestan',
    'ulyanovsk':         'ulyanovsk oblast',
    'yaroslavl':         'yaroslavl oblast',
    'vladikavkaz':       'republic of north ossetia',
    'tomsk':             'tomsk oblast',
    'kemerovo':          'kemerovo oblast',
}


# ── DDL + Import ──────────────────────────────────────────────────────────────

def _parse_admin_level(data_avail: str) -> int:
    da = data_avail.strip().lower()
    if 'national' in da:
        return 0
    if 'federal_district' in da:
        return 0
    if 'federal_subject' in da:
        return 1
    return 2


def _import_csv(db) -> dict:
    csv_path = Path(__file__).parent / 'russia_wage_schema' / 'real_data' / 'russia_wage_real.csv'
    if not csv_path.exists():
        return {'error': f'CSV no encontrado: {csv_path}'}

    inserted = skipped = 0
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('year', '').strip() != '2024':
                continue
            wage_raw = (row.get('wage_value') or '').strip()
            if not wage_raw:
                skipped += 1
                continue
            try:
                monthly_rub = float(wage_raw)
            except ValueError:
                skipped += 1
                continue

            monthly_usd = round(monthly_rub * RUB_TO_USD, 2)
            annual_usd  = round(monthly_usd * 12, 2)
            score       = min(100, round(monthly_rub / _MAX_RUB * 100, 1))
            da          = row.get('data_availability', '').strip()
            admin_level = _parse_admin_level(da)

            db.execute(text("""
                INSERT INTO russia_wages
                    (admin_code, region_name_en, region_name_ru, federal_district,
                     admin_level, monthly_rub, monthly_usd, annual_usd, income_score,
                     year, source)
                VALUES
                    (:code, :name_en, :name_ru, :district,
                     :level, :rub, :usd, :annual, :score,
                     2024, 'Rosstat tab4-zpl-2025 2024')
                ON CONFLICT (admin_code, year) DO UPDATE SET
                    monthly_rub    = EXCLUDED.monthly_rub,
                    monthly_usd    = EXCLUDED.monthly_usd,
                    annual_usd     = EXCLUDED.annual_usd,
                    income_score   = EXCLUDED.income_score,
                    admin_level    = EXCLUDED.admin_level
            """), {
                'code':     row.get('admin_code', '').strip(),
                'name_en':  row.get('region_name_en', '').strip(),
                'name_ru':  row.get('region_name_ru', '').strip() or None,
                'district': row.get('federal_district', '').strip() or None,
                'level':    admin_level,
                'rub':      monthly_rub,
                'usd':      monthly_usd,
                'annual':   annual_usd,
                'score':    score,
            })
            inserted += 1

    db.commit()
    return {'csv_inserted': inserted, 'csv_skipped': skipped}


def run_russia_wages_import(db) -> dict:
    db.execute(text(DDL_RUSSIA_WAGES))
    db.commit()
    result = _import_csv(db)
    result['status'] = 'ok'
    result['source'] = 'Rosstat Russia 2024'
    result['fx_rate'] = '1 USD = 90 RUB (nominal 2024)'
    return result


# ── Lookup ────────────────────────────────────────────────────────────────────

def get_russia_income(region: str | None, db) -> dict | None:
    """
    Retorna ingreso estimado para usuario en Rusia.
    Busca por nombre de región/ciudad; si no encuentra, usa dato nacional.
    """
    search_names = []

    if region:
        norm = region.strip().lower()
        search_names.append(norm)
        # Resolver ciudad → región
        mapped = _CITY_TO_REGION.get(norm)
        if mapped:
            search_names.append(mapped)

    # Fallback: dato nacional
    for name in search_names:
        row = db.execute(text("""
            SELECT region_name_en, monthly_usd, annual_usd, income_score
            FROM russia_wages
            WHERE LOWER(region_name_en) LIKE '%' || LOWER(:name) || '%'
              AND year = 2024
            ORDER BY admin_level ASC
            LIMIT 1
        """), {'name': name}).fetchone()

        if row and row[1]:
            return {
                'region':      row[0],
                'monthly_usd': float(row[1]),
                'annual_usd':  float(row[2]),
                'score':       float(row[3]) if row[3] is not None else None,
                'source':      'Rosstat Russia 2024',
            }

    # Fallback nacional
    row = db.execute(text("""
        SELECT region_name_en, monthly_usd, annual_usd, income_score
        FROM russia_wages
        WHERE admin_code = 'RU-NAT' AND year = 2024
        LIMIT 1
    """)).fetchone()

    if row and row[1]:
        return {
            'region':      row[0],
            'monthly_usd': float(row[1]),
            'annual_usd':  float(row[2]),
            'score':       float(row[3]) if row[3] is not None else None,
            'source':      'Rosstat Russia 2024 (national)',
        }

    return None


def get_russia_summary(db) -> dict:
    try:
        row = db.execute(text("""
            SELECT COUNT(*), MIN(monthly_usd), MAX(monthly_usd), AVG(monthly_usd)
            FROM russia_wages WHERE year = 2024 AND admin_level = 1
        """)).fetchone()
        return {
            'federal_subjects': row[0] if row else 0,
            'min_monthly_usd':  round(row[1], 2) if row and row[1] else None,
            'max_monthly_usd':  round(row[2], 2) if row and row[2] else None,
            'avg_monthly_usd':  round(row[3], 2) if row and row[3] else None,
            'fx_rate':          '1 USD = 90 RUB (nominal 2024)',
        }
    except Exception as e:
        return {'error': str(e)}
