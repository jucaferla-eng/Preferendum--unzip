from __future__ import annotations
"""
japan_wages_agent.py — Japan wage data import para Preferendum
==============================================================
Fuente: e-Stat Japan (Ministry of Health, Labour and Welfare) 2024
  japan_wage_real.csv — salarios por prefectura, JPY miles/mes
  wage_measure = contractual_cash_earnings (salario contractual total)

47 prefecturas + dato nacional.
Conversión: JPY → USD nominal 2024: 1 USD = 150 JPY
"""

import csv
from pathlib import Path
from sqlalchemy import text

JPY_TO_USD = 1 / 150  # tasa nominal 2024

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

# Nombre normalizado → variaciones que podría escribir un usuario
_PREFECTURE_ALIASES: dict[str, list[str]] = {
    'tokyo':      ['tokyo', 'tokio', 'tōkyō'],
    'osaka':      ['osaka', 'ōsaka'],
    'kyoto':      ['kyoto', 'kioto', 'kyōto'],
    'hokkaido':   ['hokkaido', 'hokkaidō'],
    'okinawa':    ['okinawa'],
    'fukuoka':    ['fukuoka'],
    'aichi':      ['aichi', 'nagoya'],
    'kanagawa':   ['kanagawa', 'yokohama'],
    'saitama':    ['saitama'],
    'chiba':      ['chiba'],
    'hyogo':      ['hyogo', 'hyōgo', 'kobe'],
    'hiroshima':  ['hiroshima'],
    'miyagi':     ['miyagi', 'sendai'],
    'niigata':    ['niigata'],
    'shizuoka':   ['shizuoka'],
}

_NATIONAL_JPY_THOUSAND = 359.6  # contractual_cash_earnings 2024


# ── DDL + Import ──────────────────────────────────────────────────────────────

def _import_csv(db) -> dict:
    csv_path = Path(__file__).parent / 'japan_wage_schema' / 'real_data' / 'japan_wage_real.csv'
    if not csv_path.exists():
        return {'error': f'CSV no encontrado: {csv_path}'}

    # Dato nacional para calcular score relativo
    nat_monthly_usd = round(_NATIONAL_JPY_THOUSAND * 1000 * JPY_TO_USD, 2)
    # Techo de score = Tokyo (434.3 K JPY/mes, el más alto)
    tokyo_jpy_k = 434.3
    max_monthly_usd = round(tokyo_jpy_k * 1000 * JPY_TO_USD, 2)

    inserted = skipped = 0
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('wage_measure', '').strip() != 'contractual_cash_earnings':
                continue
            if row.get('year', '').strip() != '2024':
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
                     2024, 'contractual_cash_earnings',
                     'e-Stat MHLW Japan 2024')
                ON CONFLICT (admin_code, year, wage_measure) DO UPDATE SET
                    monthly_jpy   = EXCLUDED.monthly_jpy,
                    monthly_usd   = EXCLUDED.monthly_usd,
                    annual_usd    = EXCLUDED.annual_usd,
                    income_score  = EXCLUDED.income_score
            """), {
                'code':    row.get('admin_code', '').strip(),
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
    return {'csv_inserted': inserted, 'csv_skipped': skipped}


def run_japan_wages_import(db) -> dict:
    db.execute(text(DDL_JAPAN_WAGES))
    db.commit()
    result = _import_csv(db)
    result['status'] = 'ok'
    result['source'] = 'e-Stat MHLW Japan 2024'
    result['fx_rate'] = '1 USD = 150 JPY (nominal 2024)'
    return result


# ── Lookup ────────────────────────────────────────────────────────────────────

def get_japan_income(prefecture: str | None, db) -> dict | None:
    """
    Retorna ingreso estimado mensual/anual para usuario en Japón.
    Busca por nombre de prefectura; si no encuentra, usa dato nacional.
    """
    candidates = []

    if prefecture:
        norm = prefecture.strip().lower()
        # Directo por nombre
        candidates.append(norm)
        # Expandir aliases
        for pref_key, aliases in _PREFECTURE_ALIASES.items():
            if norm in aliases or norm == pref_key:
                candidates.append(pref_key.capitalize())
                break

    # Siempre agregar fallback nacional
    candidates.append('JP-NAT')

    for candidate in candidates:
        row = db.execute(text("""
            SELECT region_name_en, monthly_usd, annual_usd, income_score
            FROM japan_wages
            WHERE (LOWER(region_name_en) = LOWER(:name) OR admin_code = :code)
              AND wage_measure = 'contractual_cash_earnings'
              AND year = 2024
            LIMIT 1
        """), {'name': candidate, 'code': candidate}).fetchone()

        if row and row[1]:
            return {
                'region':      row[0],
                'monthly_usd': float(row[1]),
                'annual_usd':  float(row[2]),
                'score':       float(row[3]) if row[3] is not None else None,
                'source':      'e-Stat MHLW Japan 2024',
            }

    return None


def get_japan_summary(db) -> dict:
    try:
        row = db.execute(text("""
            SELECT COUNT(*), MIN(monthly_usd), MAX(monthly_usd), AVG(monthly_usd)
            FROM japan_wages WHERE year = 2024 AND wage_measure = 'contractual_cash_earnings'
        """)).fetchone()
        return {
            'rows': row[0] if row else 0,
            'min_monthly_usd': round(row[1], 2) if row and row[1] else None,
            'max_monthly_usd': round(row[2], 2) if row and row[2] else None,
            'avg_monthly_usd': round(row[3], 2) if row and row[3] else None,
            'fx_rate': '1 USD = 150 JPY (nominal 2024)',
        }
    except Exception as e:
        return {'error': str(e)}
