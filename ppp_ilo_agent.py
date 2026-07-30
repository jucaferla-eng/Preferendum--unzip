from __future__ import annotations
"""
ppp_ilo_agent.py — Importa curva salarial PPP ILOSTAT para 10 países
=====================================================================
Fuente: curva_salarial_ppp_10paises.csv (Perplexity 2026-07-29)
  Datos oficiales: ILOSTAT, BLS, Rosstat, NBS China, ONS, INSEE
  PPP ya calculado en dólares internacionales (no estimado)

10 países: BGD, BRA, CHN, COL, FRA, GBR, MEX, NOR, RUS, USA
  - 9 grupos ISCO (occupation_level 1-9)
  - CEO/Alta dirección (occupation_level 0) — nuevo nivel

Tabla de destino: occupation_salary (sobreescribe con datos PPP reales)
  + columna median_monthly_ppp_usd (valor PPP directo de ILOSTAT)
"""

import csv
from pathlib import Path
from sqlalchemy import text

# ISO3 → ISO2
_ISO3_TO_2: dict[str, str] = {
    'BGD': 'BD', 'BRA': 'BR', 'CHN': 'CN', 'COL': 'CO',
    'FRA': 'FR', 'GBR': 'GB', 'MEX': 'MX', 'NOR': 'NO',
    'RUS': 'RU', 'USA': 'US',
}

_ISCO_LABELS = {
    0: 'CEO / Alta Dirección',
    1: 'Managers / Directivos',
    2: 'Professionals / Profesionales',
    3: 'Technicians / Técnicos',
    4: 'Clerical / Administrativos',
    5: 'Service & Sales / Servicios',
    6: 'Agricultural / Agrícola',
    7: 'Craft trades / Artesanos',
    8: 'Machine operators / Operadores',
    9: 'Elementary / Ocupaciones básicas',
}

DDL_CEO_TABLE = """
CREATE TABLE IF NOT EXISTS occupation_salary_ceo (
    id                   SERIAL PRIMARY KEY,
    country_iso          TEXT NOT NULL,
    isco_group           INTEGER NOT NULL,
    isco_label           TEXT DEFAULT '',
    median_monthly_lcu   REAL,
    median_monthly_usd   REAL,
    median_monthly_ppp_usd REAL,
    currency             TEXT DEFAULT '',
    year                 INTEGER,
    source               TEXT DEFAULT '',
    source_url           TEXT DEFAULT '',
    updated_at           TIMESTAMP DEFAULT NOW(),
    UNIQUE (country_iso, isco_group)
);
"""


def _ensure_ppp_columns(db) -> None:
    db.execute(text("ALTER TABLE occupation_salary ADD COLUMN IF NOT EXISTS median_monthly_ppp_usd REAL"))
    db.execute(text("ALTER TABLE occupation_salary ADD COLUMN IF NOT EXISTS ppp_source TEXT DEFAULT ''"))
    db.commit()


def run_ppp_ilo_import(db) -> dict:
    csv_path = Path(__file__).parent / 'ppp_wage_schema' / 'real_data' / 'curva_salarial_ppp_10paises.csv'
    if not csv_path.exists():
        return {'error': f'CSV no encontrado: {csv_path}'}

    _ensure_ppp_columns(db)
    db.execute(text(DDL_CEO_TABLE))
    db.commit()

    inserted_main = inserted_ceo = skipped = 0

    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            iso3  = row.get('country_iso', '').strip()
            cc    = _ISO3_TO_2.get(iso3)
            if not cc:
                skipped += 1
                continue

            try:
                isco_grp = int(row.get('occupation_level', '').strip())
            except ValueError:
                skipped += 1
                continue

            ppp_raw = (row.get('wage_value_ppp_intl_usd_monthly') or '').strip()
            lcu_raw = (row.get('wage_value_lcu') or '').strip()
            if not ppp_raw:
                skipped += 1
                continue
            try:
                ppp_usd = round(float(ppp_raw), 2)
                lcu_val = float(lcu_raw) if lcu_raw else None
            except ValueError:
                skipped += 1
                continue

            year_raw = (row.get('year') or '').strip().split('/')[0][:4]
            try:
                year = int(year_raw)
            except ValueError:
                year = 2024

            source     = row.get('source', '').strip()
            source_url = row.get('source_url', '').strip()
            label      = _ISCO_LABELS.get(isco_grp, '')

            if isco_grp == 0:
                # CEO/Alta dirección → tabla separada
                db.execute(text("""
                    INSERT INTO occupation_salary_ceo
                        (country_iso, isco_group, isco_label, median_monthly_lcu,
                         median_monthly_ppp_usd, year, source, source_url, updated_at)
                    VALUES (:cc, :isco, :label, :lcu, :ppp, :year, :src, :url, NOW())
                    ON CONFLICT (country_iso, isco_group) DO UPDATE SET
                        median_monthly_lcu=EXCLUDED.median_monthly_lcu,
                        median_monthly_ppp_usd=EXCLUDED.median_monthly_ppp_usd,
                        year=EXCLUDED.year, source=EXCLUDED.source,
                        source_url=EXCLUDED.source_url, updated_at=NOW()
                """), {'cc': cc, 'isco': isco_grp, 'label': label, 'lcu': lcu_val,
                       'ppp': ppp_usd, 'year': year, 'src': source, 'url': source_url})
                inserted_ceo += 1
            else:
                # ISCO 1-9 → actualiza occupation_salary con PPP real
                db.execute(text("""
                    INSERT INTO occupation_salary
                        (country_iso, isco_group, isco_label, median_monthly_local,
                         median_monthly_usd, median_monthly_ppp_usd,
                         currency, profession_score, year, source, ppp_source, updated_at)
                    VALUES (:cc, :isco, :label, :lcu, :ppp, :ppp, 'PPP_INTL', 0, :year,
                         :src, 'ILOSTAT PPP direct', NOW())
                    ON CONFLICT (country_iso, isco_group) DO UPDATE SET
                        isco_label=EXCLUDED.isco_label,
                        median_monthly_ppp_usd=EXCLUDED.median_monthly_ppp_usd,
                        ppp_source='ILOSTAT PPP direct',
                        year=EXCLUDED.year, source=EXCLUDED.source, updated_at=NOW()
                """), {'cc': cc, 'isco': isco_grp, 'label': label, 'lcu': lcu_val,
                       'ppp': ppp_usd, 'year': year, 'src': source})
                inserted_main += 1

    db.commit()

    # Recalcular profession_score para ISCO 1-9 de cada país (basado en PPP)
    countries = list(_ISO3_TO_2.values())
    for cc in countries:
        try:
            max_row = db.execute(text("""
                SELECT MAX(median_monthly_ppp_usd) FROM occupation_salary
                WHERE country_iso=:cc AND isco_group BETWEEN 1 AND 9
                  AND median_monthly_ppp_usd IS NOT NULL
            """), {'cc': cc}).fetchone()
            if max_row and max_row[0]:
                max_ppp = float(max_row[0])
                db.execute(text("""
                    UPDATE occupation_salary
                    SET profession_score = LEAST(100, ROUND(median_monthly_ppp_usd / :max * 100, 1))
                    WHERE country_iso=:cc AND isco_group BETWEEN 1 AND 9
                      AND median_monthly_ppp_usd IS NOT NULL
                """), {'cc': cc, 'max': max_ppp})
        except Exception:
            pass
    db.commit()

    return {
        'occupation_salary_ppp_updated': inserted_main,
        'ceo_rows_inserted': inserted_ceo,
        'skipped': skipped,
        'countries': list(_ISO3_TO_2.values()),
        'status': 'ok',
        'source': 'ILOSTAT + BLS + Rosstat + NBS China + ONS + INSEE (PPP directo)',
        'note': 'PPP en dólares internacionales, no estimado. median_monthly_ppp_usd actualizado.',
    }
