from __future__ import annotations
"""
new_zealand_wages_agent.py — New Zealand wage data import para Preferendum
==========================================================================
Fuentes:
  1. nz_wage_by_occupation_real.csv — Stats NZ LMSI Q2 2025
     - 8 grupos ANZSCO major, salario semanal NZD, median_weekly_earnings
  2. nz_income_by_region_real.csv — Stats NZ Census 2023
     - 16 regiones, ingreso personal anual NZD

Tablas:
  - occupation_salary : 9 grupos ISCO para NZ (tabla compartida)
  - nz_region_wages   : 16 consejos regionales + nacional

Conversión: NZD → USD 2025: 1 NZD = 0.61 USD
  Semanal → mensual: × (52 / 12)
"""

import csv
from pathlib import Path
from sqlalchemy import text

NZD_TO_USD  = 0.61
WEEKS_MONTH = 52 / 12  # = 4.3333...

# ANZSCO major → (isco_group, isco_label, nzd_weekly_2025)
# Fuente: Stats NZ LMSI Q2 2025, median_weekly_earnings
_ANZSCO_ISCO = [
    (1, 'Managers / Directivos',          1726),
    (2, 'Professionals / Profesionales',  1784),
    (3, 'Technicians / Técnicos',         1330),
    (4, 'Clerical / Administrativos',     1296),
    (5, 'Service & Sales / Servicios',     976),  # avg(Community 1002, Sales 950)
    (7, 'Craft trades / Artesanos',       1330),  # proxy = Technicians&Trades (mismo grupo)
    (8, 'Machine operators / Operadores', 1299),
    (9, 'Elementary / Ocupaciones básicas', 1040),
]
# ISCO 6 (Agriculture): proxy promedio ISCO 8 + ISCO 9
_ISCO6_NZD_WEEK = round((1299 + 1040) / 2, 0)

# Máximo para score: Professionals = 1784 NZD/week
_MAX_NZD_WEEK = 1784.0

_REGION_ALIASES: dict[str, str] = {
    'auckland':    'Auckland',
    'wellington':  'Wellington',
    'canterbury':  'Canterbury',
    'christchurch': 'Canterbury',
    'otago':       'Otago',
    'dunedin':     'Otago',
    'waikato':     'Waikato',
    'hamilton':    'Waikato',
    'bay of plenty': 'Bay of Plenty',
    'tauranga':    'Bay of Plenty',
    'northland':   'Northland',
    'manawatu':    'Manawatū-Whanganui',
    'palmerston':  'Manawatū-Whanganui',
    'taranaki':    'Taranaki',
    'new plymouth': 'Taranaki',
    'hawkes bay':  "Hawke's Bay",
    'southland':   'Southland',
    'invercargill': 'Southland',
    'nelson':      'Nelson',
    'marlborough': 'Marlborough',
    'tasman':      'Tasman',
    'west coast':  'West Coast',
    'gisborne':    'Gisborne',
}

DDL_NZ_REGION = """
CREATE TABLE IF NOT EXISTS nz_region_wages (
    id              SERIAL PRIMARY KEY,
    admin_code      TEXT NOT NULL,
    region_name_en  TEXT NOT NULL,
    annual_nzd      REAL,
    monthly_nzd     REAL,
    monthly_usd     REAL,
    annual_usd      REAL,
    income_score    REAL,
    income_type     TEXT,
    year            INTEGER DEFAULT 2023,
    source          TEXT,
    UNIQUE(admin_code, year)
);
CREATE INDEX IF NOT EXISTS idx_nz_region_name ON nz_region_wages(region_name_en);
"""


def _ensure_occupation_salary_table(db) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS occupation_salary (
            id                   SERIAL PRIMARY KEY,
            country_iso          TEXT NOT NULL,
            isco_group           INTEGER NOT NULL,
            isco_label           TEXT DEFAULT '',
            median_monthly_local REAL,
            median_monthly_usd   REAL,
            currency             TEXT DEFAULT '',
            profession_score     REAL DEFAULT 0,
            year                 INTEGER,
            source               TEXT DEFAULT '',
            updated_at           TIMESTAMP DEFAULT NOW(),
            UNIQUE (country_iso, isco_group)
        )
    """))
    db.commit()


def _import_occupation_salary(db) -> dict:
    _ensure_occupation_salary_table(db)
    all_rows = list(_ANZSCO_ISCO) + [(6, 'Agricultural / Agrícola', _ISCO6_NZD_WEEK)]
    inserted = 0
    for isco_grp, label, nzd_week in sorted(all_rows, key=lambda x: x[0]):
        monthly_nzd = round(nzd_week * WEEKS_MONTH, 2)
        monthly_usd = round(monthly_nzd * NZD_TO_USD, 2)
        score       = round(nzd_week / _MAX_NZD_WEEK * 100, 1)
        db.execute(text("""
            INSERT INTO occupation_salary
                (country_iso, isco_group, isco_label, median_monthly_local,
                 median_monthly_usd, currency, profession_score, year, source, updated_at)
            VALUES ('NZ', :isco, :label, :local, :usd, 'NZD', :score, 2025,
                 'Stats NZ LMSI Q2 2025', NOW())
            ON CONFLICT (country_iso, isco_group) DO UPDATE SET
                isco_label=EXCLUDED.isco_label, median_monthly_local=EXCLUDED.median_monthly_local,
                median_monthly_usd=EXCLUDED.median_monthly_usd, profession_score=EXCLUDED.profession_score,
                year=EXCLUDED.year, source=EXCLUDED.source, updated_at=NOW()
        """), {'isco': isco_grp, 'label': label,
               'local': monthly_nzd, 'usd': monthly_usd, 'score': score})
        inserted += 1
    db.commit()
    return {'occupation_salary_nz_rows': inserted}


def _import_nz_regions(db) -> dict:
    csv_path = Path(__file__).parent / 'new_zealand_wage_schema' / 'real_data' / 'nz_income_by_region_real.csv'
    if not csv_path.exists():
        return {'error': f'CSV no encontrado: {csv_path}'}

    # Max for score: Wellington 48700 NZD/year
    max_annual_nzd = 48700.0
    inserted = skipped = 0

    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            income_type = row.get('income_type', '').strip()
            if income_type != 'median_personal_income_census':
                continue
            val_raw = (row.get('income_value') or '').strip()
            if not val_raw:
                skipped += 1
                continue
            try:
                annual_nzd = float(val_raw)
            except ValueError:
                skipped += 1
                continue

            monthly_nzd = round(annual_nzd / 12, 2)
            monthly_usd = round(monthly_nzd * NZD_TO_USD, 2)
            annual_usd  = round(annual_nzd * NZD_TO_USD, 2)
            score       = min(100, round(annual_nzd / max_annual_nzd * 100, 1))

            db.execute(text("""
                INSERT INTO nz_region_wages
                    (admin_code, region_name_en, annual_nzd, monthly_nzd,
                     monthly_usd, annual_usd, income_score, income_type, year, source)
                VALUES (:code, :name, :annual_nzd, :monthly_nzd,
                     :usd, :annual_usd, :score, :itype, 2023, 'Stats NZ Census 2023')
                ON CONFLICT (admin_code, year) DO UPDATE SET
                    annual_nzd=EXCLUDED.annual_nzd, monthly_nzd=EXCLUDED.monthly_nzd,
                    monthly_usd=EXCLUDED.monthly_usd, annual_usd=EXCLUDED.annual_usd,
                    income_score=EXCLUDED.income_score
            """), {
                'code':       row.get('admin_code', '').strip(),
                'name':       row.get('region_name_en', '').strip(),
                'annual_nzd': annual_nzd,
                'monthly_nzd': monthly_nzd,
                'usd':        monthly_usd,
                'annual_usd': annual_usd,
                'score':      score,
                'itype':      income_type,
            })
            inserted += 1

    db.commit()
    return {'nz_regions_inserted': inserted, 'nz_regions_skipped': skipped}


def run_new_zealand_wages_import(db) -> dict:
    db.execute(text(DDL_NZ_REGION))
    db.commit()
    sal_r = _import_occupation_salary(db)
    reg_r = _import_nz_regions(db)
    return {
        **sal_r, **reg_r,
        'status': 'ok',
        'source': 'Stats NZ LMSI Q2 2025 (8 ANZSCO groups) + Census 2023 (16 regions)',
        'fx_rate': '1 NZD = 0.61 USD (2025) | weekly × 52/12 = monthly',
    }


# ── Lookups ───────────────────────────────────────────────────────────────────

def get_new_zealand_income(region: str | None, db) -> dict | None:
    """Busca ingreso regional en NZ. Fallback: nacional."""
    candidates = []
    if region:
        norm = region.strip().lower()
        candidates.append(norm)
        mapped = _REGION_ALIASES.get(norm)
        if mapped:
            candidates.append(mapped)

    for name in candidates:
        row = db.execute(text("""
            SELECT region_name_en, monthly_usd, annual_usd, income_score
            FROM nz_region_wages
            WHERE LOWER(region_name_en) LIKE '%' || LOWER(:name) || '%' AND year=2023
            LIMIT 1
        """), {'name': name}).fetchone()
        if row and row[1]:
            return {'region': row[0], 'monthly_usd': float(row[1]),
                    'annual_usd': float(row[2]), 'score': float(row[3]) if row[3] else None,
                    'source': 'Stats NZ Census 2023'}

    row = db.execute(text(
        "SELECT region_name_en, monthly_usd, annual_usd, income_score FROM nz_region_wages WHERE admin_code='NZ-NAT' AND year=2023 LIMIT 1"
    )).fetchone()
    if row and row[1]:
        return {'region': row[0], 'monthly_usd': float(row[1]),
                'annual_usd': float(row[2]), 'score': float(row[3]) if row[3] else None,
                'source': 'Stats NZ Census 2023 (national)'}
    return None
