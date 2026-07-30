from __future__ import annotations
"""
japan_wages_agent.py — Japan wage data import para Preferendum
==============================================================
Fuentes:
  1. japan_wage_real.csv — e-Stat MHLW Japan 2024
     a. Datos por prefectura (47 prefecturas, contractual_cash_earnings)
     b. 144 ocupaciones detalladas JSOC a nivel nacional (JP-NAT, JSOC_DETAILED)
     c. 11 grupos mayores JSOC a nivel nacional (JP-NAT, JSOC_MAJOR)

Tablas:
  - japan_wages          : prefectura × ingreso mensual JPY/USD
  - japan_occupation_wages: ocupación específica × ingreso mensual JPY/USD

Conversión: JPY → USD nominal 2024: 1 USD = 150 JPY
  wage_value está en thousand_yen_per_month → × 1000 para JPY real
"""

import csv
from pathlib import Path
from sqlalchemy import text

JPY_TO_USD  = 1 / 150   # tasa nominal 2024
TOKYO_JPY_K = 434.3     # techo para score regional
NAT_JPY_K   = 359.6     # nacional contractual 2024

DDL_JAPAN_WAGES = """
CREATE TABLE IF NOT EXISTS japan_wages (
    id              SERIAL PRIMARY KEY,
    admin_code      TEXT NOT NULL,
    region_name_en  TEXT NOT NULL,
    region_name_ja  TEXT,
    region_block    TEXT,
    monthly_jpy     REAL,
    monthly_usd     REAL,
    annual_usd      REAL,
    income_score    REAL,
    year            INTEGER DEFAULT 2024,
    wage_measure    TEXT,
    source          TEXT,
    UNIQUE(admin_code, year, wage_measure)
);
CREATE INDEX IF NOT EXISTS idx_japan_wages_region ON japan_wages(region_name_en);
"""

DDL_JAPAN_OCC = """
CREATE TABLE IF NOT EXISTS japan_occupation_wages (
    id                  SERIAL PRIMARY KEY,
    occupation_category TEXT NOT NULL,
    occupation_code     TEXT,
    occupation_level    TEXT,
    monthly_jpy         REAL,
    monthly_usd         REAL,
    annual_usd          REAL,
    income_score        REAL,
    year                INTEGER DEFAULT 2024,
    wage_measure        TEXT,
    classification      TEXT,
    source              TEXT,
    UNIQUE(occupation_category, year, wage_measure)
);
CREATE INDEX IF NOT EXISTS idx_japan_occ_name ON japan_occupation_wages(occupation_category);
CREATE INDEX IF NOT EXISTS idx_japan_occ_level ON japan_occupation_wages(occupation_level);
"""

# Techo para score de ocupaciones: Pilotos = 1268.4 K JPY/mes (el más alto)
_MAX_OCC_JPY_K = 1268.4

# Aliases prefecturas
_PREFECTURE_ALIASES: dict[str, list[str]] = {
    'tokyo':     ['tokyo', 'tokio', 'tōkyō'],
    'osaka':     ['osaka', 'ōsaka'],
    'kyoto':     ['kyoto', 'kioto'],
    'hokkaido':  ['hokkaido'],
    'aichi':     ['aichi', 'nagoya'],
    'kanagawa':  ['kanagawa', 'yokohama'],
    'hyogo':     ['hyogo', 'kobe'],
    'hiroshima': ['hiroshima'],
    'miyagi':    ['miyagi', 'sendai'],
    'fukuoka':   ['fukuoka'],
    'okinawa':   ['okinawa'],
}


# ── Import prefectures ────────────────────────────────────────────────────────

def _import_prefectures(db) -> dict:
    csv_path = Path(__file__).parent / 'japan_wage_schema' / 'real_data' / 'japan_wage_real.csv'
    if not csv_path.exists():
        return {'error': f'CSV no encontrado: {csv_path}'}

    max_monthly_usd = round(TOKYO_JPY_K * 1000 * JPY_TO_USD, 2)
    inserted = skipped = 0

    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('wage_measure', '').strip() != 'contractual_cash_earnings':
                continue
            if row.get('year', '').strip() != '2024':
                continue
            # Solo filas de prefectura o nacional (occupation_category = Total o vacío)
            occ = row.get('occupation_category', '').strip()
            if occ and occ != 'Total':
                continue
            admin_code = row.get('admin_code', '').strip()
            # Solo nivel prefectura (admin_level=1) o nacional (JP-NAT)
            level = row.get('admin_level', '').strip()
            if level not in ('0', '1'):
                continue
            wage_raw = (row.get('wage_value') or '').strip()
            if not wage_raw:
                skipped += 1
                continue
            try:
                wage_jpy_k = float(wage_raw)
            except ValueError:
                skipped += 1
                continue

            monthly_jpy = round(wage_jpy_k * 1000, 2)
            monthly_usd = round(monthly_jpy * JPY_TO_USD, 2)
            annual_usd  = round(monthly_usd * 12, 2)
            score       = min(100, round(monthly_usd / max_monthly_usd * 100, 1))

            db.execute(text("""
                INSERT INTO japan_wages
                    (admin_code, region_name_en, region_name_ja, region_block,
                     monthly_jpy, monthly_usd, annual_usd, income_score,
                     year, wage_measure, source)
                VALUES
                    (:code, :name_en, :name_ja, :block,
                     :jpy, :usd, :annual, :score,
                     2024, 'contractual_cash_earnings', 'e-Stat MHLW Japan 2024')
                ON CONFLICT (admin_code, year, wage_measure) DO UPDATE SET
                    monthly_jpy  = EXCLUDED.monthly_jpy,
                    monthly_usd  = EXCLUDED.monthly_usd,
                    annual_usd   = EXCLUDED.annual_usd,
                    income_score = EXCLUDED.income_score
            """), {
                'code':    admin_code,
                'name_en': row.get('region_name_en', '').strip(),
                'name_ja': row.get('region_name_ja', '').strip() or None,
                'block':   row.get('region_block', '').strip() or None,
                'jpy':     monthly_jpy,
                'usd':     monthly_usd,
                'annual':  annual_usd,
                'score':   score,
            })
            inserted += 1

    db.commit()
    return {'prefectures_inserted': inserted, 'prefectures_skipped': skipped}


# ── Import occupations ────────────────────────────────────────────────────────

def _import_occupations(db) -> dict:
    csv_path = Path(__file__).parent / 'japan_wage_schema' / 'real_data' / 'japan_wage_real.csv'
    if not csv_path.exists():
        return {'error': f'CSV no encontrado: {csv_path}'}

    max_monthly_usd = round(_MAX_OCC_JPY_K * 1000 * JPY_TO_USD, 2)
    inserted = skipped = 0

    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('wage_measure', '').strip() != 'contractual_cash_earnings':
                continue
            if row.get('year', '').strip() != '2024':
                continue
            # Solo filas nacionales con ocupación específica
            if row.get('admin_code', '').strip() != 'JP-NAT':
                continue
            occ = row.get('occupation_category', '').strip()
            if not occ or occ == 'Total':
                continue
            wage_raw = (row.get('wage_value') or '').strip()
            if not wage_raw:
                skipped += 1
                continue
            try:
                wage_jpy_k = float(wage_raw)
            except ValueError:
                skipped += 1
                continue

            monthly_jpy = round(wage_jpy_k * 1000, 2)
            monthly_usd = round(monthly_jpy * JPY_TO_USD, 2)
            annual_usd  = round(monthly_usd * 12, 2)
            score       = min(100, round(monthly_usd / max_monthly_usd * 100, 1))

            db.execute(text("""
                INSERT INTO japan_occupation_wages
                    (occupation_category, occupation_code, occupation_level,
                     monthly_jpy, monthly_usd, annual_usd, income_score,
                     year, wage_measure, classification, source)
                VALUES
                    (:occ, :code, :level,
                     :jpy, :usd, :annual, :score,
                     2024, 'contractual_cash_earnings', :cls, 'e-Stat MHLW Japan 2024')
                ON CONFLICT (occupation_category, year, wage_measure) DO UPDATE SET
                    monthly_jpy  = EXCLUDED.monthly_jpy,
                    monthly_usd  = EXCLUDED.monthly_usd,
                    annual_usd   = EXCLUDED.annual_usd,
                    income_score = EXCLUDED.income_score
            """), {
                'occ':   occ,
                'code':  row.get('occupation_code', '').strip() or None,
                'level': row.get('occupation_level', '').strip() or None,
                'jpy':   monthly_jpy,
                'usd':   monthly_usd,
                'annual': annual_usd,
                'score': score,
                'cls':   row.get('classification_system', '').strip() or None,
            })
            inserted += 1

    db.commit()
    return {'occupations_inserted': inserted, 'occupations_skipped': skipped}


def run_japan_wages_import(db) -> dict:
    db.execute(text(DDL_JAPAN_WAGES))
    db.execute(text(DDL_JAPAN_OCC))
    db.commit()
    pref_r = _import_prefectures(db)
    occ_r  = _import_occupations(db)
    return {
        **pref_r, **occ_r,
        'status': 'ok',
        'source': 'e-Stat MHLW Japan 2024 (prefectures + 144 occupations)',
        'fx_rate': '1 USD = 150 JPY (nominal 2024)',
    }


# ── Lookup por prefectura ─────────────────────────────────────────────────────

def get_japan_income(prefecture: str | None, db) -> dict | None:
    candidates = []
    if prefecture:
        norm = prefecture.strip().lower()
        candidates.append(norm)
        for key, aliases in _PREFECTURE_ALIASES.items():
            if norm in aliases or norm == key:
                candidates.append(key.capitalize())
                break
    candidates.append('JP-NAT')

    for candidate in candidates:
        row = db.execute(text("""
            SELECT region_name_en, monthly_usd, annual_usd, income_score
            FROM japan_wages
            WHERE (LOWER(region_name_en) = LOWER(:name) OR admin_code = :code)
              AND wage_measure = 'contractual_cash_earnings' AND year = 2024
            LIMIT 1
        """), {'name': candidate, 'code': candidate}).fetchone()
        if row and row[1]:
            return {
                'region': row[0], 'monthly_usd': float(row[1]),
                'annual_usd': float(row[2]), 'score': float(row[3]) if row[3] else None,
                'source': 'e-Stat MHLW Japan 2024',
            }
    return None


# ── Lookup por ocupación específica ──────────────────────────────────────────

def get_japan_occupation_income(profession: str, db) -> dict | None:
    """
    Busca salario en Japan por nombre de ocupación.
    Primero búsqueda exacta, luego parcial.
    """
    if not profession:
        return None

    for query in [
        "SELECT occupation_category, monthly_usd, annual_usd, income_score FROM japan_occupation_wages WHERE LOWER(occupation_category) = LOWER(:p) AND year = 2024 LIMIT 1",
        "SELECT occupation_category, monthly_usd, annual_usd, income_score FROM japan_occupation_wages WHERE LOWER(occupation_category) LIKE '%' || LOWER(:p) || '%' AND year = 2024 ORDER BY occupation_level DESC LIMIT 1",
    ]:
        row = db.execute(text(query), {'p': profession.strip()}).fetchone()
        if row and row[1]:
            return {
                'occupation': row[0],
                'monthly_usd': float(row[1]),
                'annual_usd':  float(row[2]),
                'score':       float(row[3]) if row[3] else None,
                'source':      'e-Stat MHLW Japan 2024 (occupation-specific)',
            }
    return None


def get_japan_summary(db) -> dict:
    try:
        r = db.execute(text("SELECT COUNT(*) FROM japan_wages WHERE year=2024 AND wage_measure='contractual_cash_earnings'")).fetchone()
        o = db.execute(text("SELECT COUNT(*), COUNT(DISTINCT occupation_level) FROM japan_occupation_wages WHERE year=2024")).fetchone()
        return {
            'prefecture_rows': r[0] if r else 0,
            'occupation_rows': o[0] if o else 0,
            'occupation_levels': o[1] if o else 0,
            'fx_rate': '1 USD = 150 JPY (nominal 2024)',
        }
    except Exception as e:
        return {'error': str(e)}
