from __future__ import annotations
"""
singapore_wages_agent.py — Singapore wage data import para Preferendum
======================================================================
Fuentes:
  1. sg_wage_by_occupation_real.csv — MOM Singapore 2025
     a. 9 major SSOC categories → ISCO groups en occupation_salary
     b. ~530 detailed SSOC occupations → sg_occupation_wages

Tablas:
  - occupation_salary    : 9 grupos ISCO para SG (tabla compartida)
  - sg_occupation_wages  : ocupaciones detalladas SSOC 2024

Conversión: SGD → USD 2025: 1 SGD = 0.74 USD
Nota: Singapore ciudad-estado, sin datos regionales significativos.
"""

import csv
from pathlib import Path
from sqlalchemy import text

SGD_TO_USD = 0.74   # tasa 2025
_MAX_SGD   = 17053.0  # Commercial airline pilot = techo score 100

# SSOC major group → (isco_group, isco_label, sgd_month_gross_incl_cpf)
# Fuente: MOM LFR 2025 SectionC, median_gross_monthly_income_incl_employer_cpf
_SSOC_ISCO = {
    'Managers & Administrators (incl. working proprietors)': (1, 'Managers / Directivos',           11445),
    'Professionals':                                          (2, 'Professionals / Profesionales',    8758),
    'Associate Professionals & Technicians':                  (3, 'Technicians / Técnicos',           4853),
    'Clerical Support Workers':                               (4, 'Clerical / Administrativos',       3510),
    'Service & Sales Workers':                                (5, 'Service & Sales / Servicios',      3315),
    'Craftsmen & Related Trades Workers':                     (7, 'Craft trades / Artesanos',         3270),
    'Plant & Machine Operators & Assemblers':                 (8, 'Machine operators / Operadores',   2993),
    'Cleaners, Labourers & Related Workers':                  (9, 'Elementary / Ocupaciones básicas', 2239),
}
# ISCO 6 (Agriculture) proxy: Singapore ciudad-estado, promedio artesanos + operadores
_ISCO6_SGD = round((3270 + 2993) / 2, 0)

DDL_SG_OCC = """
CREATE TABLE IF NOT EXISTS sg_occupation_wages (
    id                  SERIAL PRIMARY KEY,
    occupation_category TEXT NOT NULL,
    occupation_code     TEXT,
    monthly_sgd         REAL,
    monthly_usd         REAL,
    annual_usd          REAL,
    income_score        REAL,
    year                INTEGER DEFAULT 2025,
    wage_measure        TEXT,
    source              TEXT,
    UNIQUE(occupation_category, year, wage_measure)
);
CREATE INDEX IF NOT EXISTS idx_sg_occ_name ON sg_occupation_wages(occupation_category);
CREATE INDEX IF NOT EXISTS idx_sg_occ_code ON sg_occupation_wages(occupation_code);
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
    rows = []
    for _, (isco_grp, label, sgd) in _SSOC_ISCO.items():
        if not any(r[0] == isco_grp for r in rows):
            rows.append((isco_grp, label, sgd))
    # ISCO 6 proxy
    rows.append((6, 'Agricultural / Agrícola', _ISCO6_SGD))

    inserted = 0
    for isco_grp, label, sgd in sorted(rows, key=lambda x: x[0]):
        monthly_usd = round(sgd * SGD_TO_USD, 2)
        score       = round(sgd / _MAX_SGD * 100, 1)
        db.execute(text("""
            INSERT INTO occupation_salary
                (country_iso, isco_group, isco_label, median_monthly_local,
                 median_monthly_usd, currency, profession_score, year, source, updated_at)
            VALUES ('SG', :isco, :label, :local, :usd, 'SGD', :score, 2025,
                 'MOM Singapore LFR 2025', NOW())
            ON CONFLICT (country_iso, isco_group) DO UPDATE SET
                isco_label=EXCLUDED.isco_label, median_monthly_local=EXCLUDED.median_monthly_local,
                median_monthly_usd=EXCLUDED.median_monthly_usd, profession_score=EXCLUDED.profession_score,
                year=EXCLUDED.year, source=EXCLUDED.source, updated_at=NOW()
        """), {'isco': isco_grp, 'label': label, 'local': float(sgd),
               'usd': monthly_usd, 'score': score})
        inserted += 1
    db.commit()
    return {'occupation_salary_sg_rows': inserted}


def _import_sg_occupations(db) -> dict:
    csv_path = Path(__file__).parent / 'singapore_wage_schema' / 'real_data' / 'sg_wage_by_occupation_real.csv'
    if not csv_path.exists():
        return {'error': f'CSV no encontrado: {csv_path}'}

    inserted = skipped = 0
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('year', '').strip() != '2025':
                continue
            if row.get('occupation_level', '').strip() != 'detailed':
                continue
            if row.get('wage_measure', '').strip() != 'median_gross_monthly_wage':
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
                monthly_sgd = float(wage_raw)
            except ValueError:
                skipped += 1
                continue

            monthly_usd = round(monthly_sgd * SGD_TO_USD, 2)
            annual_usd  = round(monthly_usd * 12, 2)
            score       = min(100, round(monthly_sgd / _MAX_SGD * 100, 1))

            db.execute(text("""
                INSERT INTO sg_occupation_wages
                    (occupation_category, occupation_code, monthly_sgd, monthly_usd,
                     annual_usd, income_score, year, wage_measure, source)
                VALUES (:occ, :code, :sgd, :usd, :annual, :score, 2025,
                     'median_gross_monthly_wage', 'MOM Singapore Wages 2025')
                ON CONFLICT (occupation_category, year, wage_measure) DO UPDATE SET
                    monthly_sgd=EXCLUDED.monthly_sgd, monthly_usd=EXCLUDED.monthly_usd,
                    annual_usd=EXCLUDED.annual_usd, income_score=EXCLUDED.income_score
            """), {
                'occ':   occ,
                'code':  row.get('occupation_code', '').strip() or None,
                'sgd':   monthly_sgd,
                'usd':   monthly_usd,
                'annual': annual_usd,
                'score': score,
            })
            inserted += 1

    db.commit()
    return {'sg_occupations_inserted': inserted, 'sg_occupations_skipped': skipped}


def run_singapore_wages_import(db) -> dict:
    db.execute(text(DDL_SG_OCC))
    db.commit()
    sal_r = _import_occupation_salary(db)
    occ_r = _import_sg_occupations(db)
    return {
        **sal_r, **occ_r,
        'status': 'ok',
        'source': 'MOM Singapore 2025 (9 ISCO groups + ~530 SSOC detailed occupations)',
        'fx_rate': '1 SGD = 0.74 USD (2025)',
    }


# ── Lookup ────────────────────────────────────────────────────────────────────

def get_singapore_occupation_income(profession: str, db) -> dict | None:
    """Busca salario en Singapore por nombre de ocupación SSOC."""
    if not profession:
        return None

    for query in [
        "SELECT occupation_category, monthly_usd, annual_usd, income_score FROM sg_occupation_wages WHERE LOWER(occupation_category) = LOWER(:p) AND year=2025 LIMIT 1",
        "SELECT occupation_category, monthly_usd, annual_usd, income_score FROM sg_occupation_wages WHERE LOWER(occupation_category) LIKE '%' || LOWER(:p) || '%' AND year=2025 LIMIT 1",
    ]:
        row = db.execute(text(query), {'p': profession.strip()}).fetchone()
        if row and row[1]:
            return {
                'occupation':  row[0],
                'monthly_usd': float(row[1]),
                'annual_usd':  float(row[2]),
                'score':       float(row[3]) if row[3] else None,
                'source':      'MOM Singapore 2025 (occupation-specific)',
            }
    return None
