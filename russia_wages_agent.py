from __future__ import annotations
"""
russia_wages_agent.py — Russia wage data import para Preferendum
================================================================
Fuentes:
  1. russia_wage_real.csv — Rosstat 2024 (tab4-zpl-2025.xlsx)
     - Salarios por sujeto federal (85+ regiones), RUB/mes
  2. russia_wage_real.csv — Rosstat biennial_occupation_survey_57T 2023
     - 155 ocupaciones OKZ (ISCO-compatible) a nivel nacional

Tablas:
  - russia_wages           : región × ingreso mensual RUB/USD
  - russia_occupation_wages: ocupación específica × ingreso mensual RUB/USD

Conversión: RUB → USD nominal 2024: 1 USD = 90 RUB
"""

import csv
from pathlib import Path
from sqlalchemy import text

RUB_TO_USD = 1 / 90
_MAX_RUB   = 228821.0  # CEOs = techo score (dato ocupación 2023)

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
"""

DDL_RUSSIA_OCC = """
CREATE TABLE IF NOT EXISTS russia_occupation_wages (
    id                  SERIAL PRIMARY KEY,
    occupation_category TEXT NOT NULL,
    occupation_code     TEXT,
    monthly_rub         REAL,
    monthly_usd         REAL,
    annual_usd          REAL,
    income_score        REAL,
    year                INTEGER DEFAULT 2023,
    survey_type         TEXT,
    source              TEXT,
    UNIQUE(occupation_category, year)
);
CREATE INDEX IF NOT EXISTS idx_russia_occ_name ON russia_occupation_wages(occupation_category);
"""

_CITY_TO_REGION: dict[str, str] = {
    'moscow':           'moscow city',
    'moscú':            'moscow city',
    'saint petersburg': 'saint petersburg',
    'san petersburgo':  'saint petersburg',
    'petersburg':       'saint petersburg',
    'novosibirsk':      'novosibirsk oblast',
    'yekaterinburg':    'sverdlovsk oblast',
    'ekaterinburg':     'sverdlovsk oblast',
    'kazan':            'republic of tatarstan',
    'chelyabinsk':      'chelyabinsk oblast',
    'omsk':             'omsk oblast',
    'samara':           'samara oblast',
    'rostov':           'rostov oblast',
    'ufa':              'republic of bashkortostan',
    'krasnoyarsk':      'krasnoyarsk krai',
    'vladivostok':      'primorsky krai',
    'perm':             'perm krai',
    'krasnodar':        'krasnodar krai',
    'tyumen':           'tyumen oblast',
    'irkutsk':          'irkutsk oblast',
    'khabarovsk':       'khabarovsk krai',
    'yaroslavl':        'yaroslavl oblast',
    'tomsk':            'tomsk oblast',
    'kemerovo':         'kemerovo oblast',
}


def _parse_admin_level(da: str) -> int:
    da = da.strip().lower()
    if 'federal_subject' in da:
        return 1
    if 'municipality' in da:
        return 2
    return 0


# ── Import regions ────────────────────────────────────────────────────────────

def _import_regions(db) -> dict:
    csv_path = Path(__file__).parent / 'russia_wage_schema' / 'real_data' / 'russia_wage_real.csv'
    if not csv_path.exists():
        return {'error': f'CSV no encontrado: {csv_path}'}

    inserted = skipped = 0
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('year', '').strip() != '2024':
                continue
            # Solo filas regionales (no ocupaciones)
            measure = row.get('wage_measure', '').strip()
            if 'october_survey' in measure:
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
                VALUES (:code, :name_en, :name_ru, :district,
                     :level, :rub, :usd, :annual, :score, 2024, 'Rosstat tab4-zpl-2025 2024')
                ON CONFLICT (admin_code, year) DO UPDATE SET
                    monthly_rub=EXCLUDED.monthly_rub, monthly_usd=EXCLUDED.monthly_usd,
                    annual_usd=EXCLUDED.annual_usd, income_score=EXCLUDED.income_score,
                    admin_level=EXCLUDED.admin_level
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
    return {'regions_inserted': inserted, 'regions_skipped': skipped}


# ── Import occupations ────────────────────────────────────────────────────────

def _import_occupations(db) -> dict:
    csv_path = Path(__file__).parent / 'russia_wage_schema' / 'real_data' / 'russia_wage_real.csv'
    if not csv_path.exists():
        return {'error': f'CSV no encontrado: {csv_path}'}

    inserted = skipped = 0
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Filas de encuesta bienal de ocupaciones
            if 'october_survey' not in row.get('wage_measure', ''):
                continue
            if row.get('admin_code', '').strip() != 'RU-NAT':
                continue
            occ = row.get('occupation_category', '').strip()
            if not occ:
                skipped += 1
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
            year_raw    = row.get('year', '2023').strip()
            try:
                year = int(year_raw)
            except ValueError:
                year = 2023

            db.execute(text("""
                INSERT INTO russia_occupation_wages
                    (occupation_category, occupation_code, monthly_rub, monthly_usd,
                     annual_usd, income_score, year, survey_type, source)
                VALUES (:occ, :code, :rub, :usd, :annual, :score, :year, :survey,
                     'Rosstat biennial_occupation_survey_57T')
                ON CONFLICT (occupation_category, year) DO UPDATE SET
                    monthly_rub=EXCLUDED.monthly_rub, monthly_usd=EXCLUDED.monthly_usd,
                    annual_usd=EXCLUDED.annual_usd, income_score=EXCLUDED.income_score
            """), {
                'occ':    occ,
                'code':   row.get('occupation_code', '').strip() or None,
                'rub':    monthly_rub,
                'usd':    monthly_usd,
                'annual': annual_usd,
                'score':  score,
                'year':   year,
                'survey': row.get('survey_type', '').strip() or None,
            })
            inserted += 1

    db.commit()
    return {'russia_occupations_inserted': inserted, 'russia_occupations_skipped': skipped}


def run_russia_wages_import(db) -> dict:
    db.execute(text(DDL_RUSSIA_WAGES))
    db.execute(text(DDL_RUSSIA_OCC))
    db.commit()
    reg_r = _import_regions(db)
    occ_r = _import_occupations(db)
    return {
        **reg_r, **occ_r,
        'status': 'ok',
        'source': 'Rosstat Russia 2024 (regiones) + 2023 (155 ocupaciones OKZ)',
        'fx_rate': '1 USD = 90 RUB (nominal 2024)',
    }


# ── Lookups ───────────────────────────────────────────────────────────────────

def get_russia_income(region: str | None, db) -> dict | None:
    search_names = []
    if region:
        norm = region.strip().lower()
        search_names.append(norm)
        mapped = _CITY_TO_REGION.get(norm)
        if mapped:
            search_names.append(mapped)

    for name in search_names:
        row = db.execute(text("""
            SELECT region_name_en, monthly_usd, annual_usd, income_score
            FROM russia_wages
            WHERE LOWER(region_name_en) LIKE '%' || LOWER(:name) || '%' AND year=2024
            ORDER BY admin_level ASC LIMIT 1
        """), {'name': name}).fetchone()
        if row and row[1]:
            return {'region': row[0], 'monthly_usd': float(row[1]),
                    'annual_usd': float(row[2]), 'score': float(row[3]) if row[3] else None,
                    'source': 'Rosstat Russia 2024'}

    row = db.execute(text(
        "SELECT region_name_en, monthly_usd, annual_usd, income_score FROM russia_wages WHERE admin_code='RU-NAT' AND year=2024 LIMIT 1"
    )).fetchone()
    if row and row[1]:
        return {'region': row[0], 'monthly_usd': float(row[1]),
                'annual_usd': float(row[2]), 'score': float(row[3]) if row[3] else None,
                'source': 'Rosstat Russia 2024 (national)'}
    return None


def get_russia_occupation_income(profession: str, db) -> dict | None:
    """Busca salario en Rusia por nombre de ocupación OKZ."""
    if not profession:
        return None

    for query in [
        "SELECT occupation_category, monthly_usd, annual_usd, income_score FROM russia_occupation_wages WHERE LOWER(occupation_category) = LOWER(:p) LIMIT 1",
        "SELECT occupation_category, monthly_usd, annual_usd, income_score FROM russia_occupation_wages WHERE LOWER(occupation_category) LIKE '%' || LOWER(:p) || '%' LIMIT 1",
    ]:
        row = db.execute(text(query), {'p': profession.strip()}).fetchone()
        if row and row[1]:
            return {
                'occupation':  row[0],
                'monthly_usd': float(row[1]),
                'annual_usd':  float(row[2]),
                'score':       float(row[3]) if row[3] else None,
                'source':      'Rosstat Russia 2023 (occupation-specific)',
            }
    return None


def get_russia_summary(db) -> dict:
    try:
        r = db.execute(text("SELECT COUNT(*) FROM russia_wages WHERE year=2024 AND admin_level=1")).fetchone()
        o = db.execute(text("SELECT COUNT(*) FROM russia_occupation_wages")).fetchone()
        return {'federal_subjects': r[0] if r else 0, 'occupation_rows': o[0] if o else 0,
                'fx_rate': '1 USD = 90 RUB (nominal 2024)'}
    except Exception as e:
        return {'error': str(e)}
