from __future__ import annotations
"""
korea_wages_agent.py — Korea wage data import para Preferendum
==============================================================
Fuente: Ministry of Employment and Labor (MOEL) 2024
  kr_wage_by_occupation_real.csv — KSCO 7th Edition
  - 9 grupos mayores (major)
  - 51 categorías medianas (medium)
  - 131 categorías finas (minor)
  Total: 192 filas de ocupación

Tablas:
  - occupation_salary       : 9 grupos ISCO (tabla compartida)
  - korea_occupation_wages  : 192 ocupaciones KSCO detalladas

Conversión: KRW (miles) → USD nominal 2024
  1 USD = 1,350 KRW — wage_value en KRW_thousand → × 1000
"""

import csv
from pathlib import Path
from sqlalchemy import text

KRW_TO_USD      = 1 / 1350
_MAX_KRW_THOUSAND = 12223  # Managers = techo score 100

# KSCO major code → (isco_group, isco_label, krw_thousand_month)
_KSCO_ISCO = {
    1: (1, 'Managers / Directivos',                   12223),
    2: (2, 'Professionals / Profesionales',            4996),
    3: (4, 'Clerical / Administrativos',               4825),
    4: (5, 'Service & Sales / Servicios y Ventas',     3091),
    5: (5, 'Service & Sales / Servicios y Ventas',     3091),
    6: (6, 'Agricultural / Agrícola',                  3034),
    7: (7, 'Craft trades / Artesanos',                 4011),
    8: (8, 'Machine operators / Operadores',           4119),
    9: (9, 'Elementary / Ocupaciones básicas',         2593),
}

DDL_KOREA_OCC = """
CREATE TABLE IF NOT EXISTS korea_occupation_wages (
    id                  SERIAL PRIMARY KEY,
    occupation_category TEXT NOT NULL,
    occupation_code     TEXT,
    occupation_level    TEXT,
    parent_code         TEXT,
    monthly_krw         REAL,
    monthly_usd         REAL,
    annual_usd          REAL,
    income_score        REAL,
    year                INTEGER DEFAULT 2024,
    classification      TEXT,
    source              TEXT,
    UNIQUE(occupation_category, occupation_code, year)
);
CREATE INDEX IF NOT EXISTS idx_korea_occ_name  ON korea_occupation_wages(occupation_category);
CREATE INDEX IF NOT EXISTS idx_korea_occ_level ON korea_occupation_wages(occupation_level);
CREATE INDEX IF NOT EXISTS idx_korea_occ_code  ON korea_occupation_wages(occupation_code);
"""


# ── Import occupation_salary (9 ISCO groups) ─────────────────────────────────

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
    isco_rows: dict[int, tuple] = {}
    for _, (isco_grp, label, krw_k) in _KSCO_ISCO.items():
        if isco_grp not in isco_rows:
            isco_rows[isco_grp] = (label, krw_k)
    if 3 not in isco_rows:
        isco_rows[3] = ('Technicians / Técnicos', 4996)

    inserted = 0
    for isco_grp, (label, krw_k) in sorted(isco_rows.items()):
        monthly_krw = float(krw_k) * 1000
        monthly_usd = round(monthly_krw * KRW_TO_USD, 2)
        score       = round(krw_k / _MAX_KRW_THOUSAND * 100, 1)
        db.execute(text("""
            INSERT INTO occupation_salary
                (country_iso, isco_group, isco_label, median_monthly_local,
                 median_monthly_usd, currency, profession_score, year, source, updated_at)
            VALUES ('KR', :isco, :label, :local, :usd, 'KRW', :score, 2024,
                 'MOEL Korea 2024 — KSCO 7th Edition', NOW())
            ON CONFLICT (country_iso, isco_group) DO UPDATE SET
                isco_label=EXCLUDED.isco_label, median_monthly_local=EXCLUDED.median_monthly_local,
                median_monthly_usd=EXCLUDED.median_monthly_usd, profession_score=EXCLUDED.profession_score,
                year=EXCLUDED.year, source=EXCLUDED.source, updated_at=NOW()
        """), {'isco': isco_grp, 'label': label,
               'local': monthly_krw, 'usd': monthly_usd, 'score': score})
        inserted += 1
    db.commit()
    return {'occupation_salary_kr_rows': inserted}


# ── Import detailed KSCO occupations ─────────────────────────────────────────

def _import_korea_occupations(db) -> dict:
    csv_path = Path(__file__).parent / 'korea_wage_schema' / 'real_data' / 'kr_wage_by_occupation_real.csv'
    if not csv_path.exists():
        return {'error': f'CSV no encontrado: {csv_path}'}

    max_krw_k = _MAX_KRW_THOUSAND
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
                krw_k = float(wage_raw)
            except ValueError:
                skipped += 1
                continue

            monthly_krw = round(krw_k * 1000, 2)
            monthly_usd = round(monthly_krw * KRW_TO_USD, 2)
            annual_usd  = round(monthly_usd * 12, 2)
            score       = min(100, round(krw_k / max_krw_k * 100, 1))
            occ         = row.get('occupation_category', '').strip()
            code        = row.get('occupation_code', '').strip()

            if not occ:
                skipped += 1
                continue

            db.execute(text("""
                INSERT INTO korea_occupation_wages
                    (occupation_category, occupation_code, occupation_level, parent_code,
                     monthly_krw, monthly_usd, annual_usd, income_score,
                     year, classification, source)
                VALUES
                    (:occ, :code, :level, :parent,
                     :krw, :usd, :annual, :score,
                     2024, :cls, 'MOEL Korea 2024')
                ON CONFLICT (occupation_category, occupation_code, year) DO UPDATE SET
                    monthly_krw  = EXCLUDED.monthly_krw,
                    monthly_usd  = EXCLUDED.monthly_usd,
                    annual_usd   = EXCLUDED.annual_usd,
                    income_score = EXCLUDED.income_score
            """), {
                'occ':    occ,
                'code':   code or None,
                'level':  row.get('occupation_level', '').strip() or None,
                'parent': row.get('parent_occupation_code', '').strip() or None,
                'krw':    monthly_krw,
                'usd':    monthly_usd,
                'annual': annual_usd,
                'score':  score,
                'cls':    row.get('classification_system', '').strip() or None,
            })
            inserted += 1

    db.commit()
    return {'korea_occupations_inserted': inserted, 'korea_occupations_skipped': skipped}


def run_korea_wages_import(db) -> dict:
    db.execute(text(DDL_KOREA_OCC))
    db.commit()
    occ_sal = _import_occupation_salary(db)
    korea_r = _import_korea_occupations(db)
    return {
        **occ_sal, **korea_r,
        'status': 'ok',
        'source': 'MOEL Korea 2024, KSCO 7th Edition (9 ISCO + 192 ocupaciones detalladas)',
        'fx_rate': '1 USD = 1,350 KRW (nominal 2024)',
    }


# ── Lookup por ocupación específica ──────────────────────────────────────────

def get_korea_occupation_income(profession: str, db) -> dict | None:
    """Busca salario en Korea por nombre de ocupación KSCO."""
    if not profession:
        return None

    for query in [
        "SELECT occupation_category, monthly_usd, annual_usd, income_score, occupation_level FROM korea_occupation_wages WHERE LOWER(occupation_category) = LOWER(:p) AND year=2024 ORDER BY occupation_level DESC LIMIT 1",
        "SELECT occupation_category, monthly_usd, annual_usd, income_score, occupation_level FROM korea_occupation_wages WHERE LOWER(occupation_category) LIKE '%' || LOWER(:p) || '%' AND year=2024 ORDER BY occupation_level DESC LIMIT 1",
    ]:
        row = db.execute(text(query), {'p': profession.strip()}).fetchone()
        if row and row[1]:
            return {
                'occupation':  row[0],
                'monthly_usd': float(row[1]),
                'annual_usd':  float(row[2]),
                'score':       float(row[3]) if row[3] else None,
                'level':       row[4],
                'source':      'MOEL Korea 2024 (occupation-specific)',
            }
    return None


def get_korea_income(isco_group: int, db) -> dict | None:
    """Retorna ingreso estimado para usuario en Korea según grupo ISCO."""
    try:
        row = db.execute(text("""
            SELECT median_monthly_local, median_monthly_usd, profession_score, isco_label
            FROM occupation_salary WHERE country_iso='KR' AND isco_group=:ig
        """), {'ig': isco_group}).fetchone()
        if row and row[1]:
            return {
                'isco_group': isco_group, 'isco_label': row[3],
                'monthly_usd': float(row[1]), 'annual_usd': round(float(row[1]) * 12, 2),
                'score': float(row[2]) if row[2] is not None else None,
                'source': 'MOEL Korea 2024',
            }
    except Exception:
        pass
    return None
