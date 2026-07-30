from __future__ import annotations
"""
scandinavia_wages_agent.py — Norway, Sweden, Denmark wage data para Preferendum
================================================================================
Fuente: Análisis comparativo 2026 (Emplosome, SCB, SSB, DST)
  Salarios mensuales brutos en moneda local y EUR para 10 ocupaciones.

Características clave:
  - Fuerte compresión salarial (menor brecha manager/obrero vs resto del mundo)
  - Dinamarca lidera en salarios nominales
  - Noruega tiene mínimos sectoriales muy altos (sindicatos)

Tipos de cambio EUR promedio 2026:
  1 EUR = 11.65 NOK   → 1 NOK = 0.08584 EUR
  1 EUR = 11.40 SEK   → 1 SEK = 0.08772 EUR
  1 EUR =  7.46 DKK   → 1 DKK = 0.13405 EUR
  1 EUR =  1.08 USD   → 1 USD = 0.92593 EUR

Tablas:
  - occupation_salary             : 9 grupos ISCO por país (tabla compartida)
  - scandinavia_occupation_wages  : 10 ocupaciones específicas × 3 países
"""

from sqlalchemy import text

EUR_TO_USD = 1.08  # tasa 2026

# ── Datos por ocupación (EUR/mes bruto 2026) ──────────────────────────────────
# (ocupacion, isco_group, no_eur, se_eur, dk_eur)
_OCCUPATIONS = [
    ('CEO / Director General',          1, 9300,  7550,  14750),
    ('Operations Manager',              1, 7050,  5600,   9900),
    ('Senior IT Engineer',              2, 5950,  4650,  10300),
    ('Specialist Doctor',               2, 7800,  6850,  16750),
    ('Secondary School Teacher',        2, 4250,  3680,   5500),
    ('Professional Nurse',              3, 4150,  3850,   4700),
    ('Administrative / Clerical',       4, 3800,  3150,   4550),
    ('Construction Worker',             7, 3750,  3100,   4500),
    ('Truck Driver / Logistics',        8, 3800,  2980,   4300),
    ('Cleaning / Service Staff',        9, 3200,  2550,   3600),
]

# ISCO 5 (Service & Sales): proxy basado en Cleaning como mínimo del sector servicios
# ISCO 6 (Agriculture): proxy basado en promedio trabajos manuales
# ISCO 9 ya cubierto por Cleaning

DDL_SCANDI_OCC = """
CREATE TABLE IF NOT EXISTS scandinavia_occupation_wages (
    id              SERIAL PRIMARY KEY,
    country_iso     TEXT NOT NULL,
    occupation      TEXT NOT NULL,
    isco_group      INTEGER,
    monthly_local   REAL,
    currency        TEXT,
    monthly_eur     REAL,
    monthly_usd     REAL,
    annual_usd      REAL,
    income_score    REAL,
    year            INTEGER DEFAULT 2026,
    source          TEXT,
    UNIQUE(country_iso, occupation, year)
);
CREATE INDEX IF NOT EXISTS idx_scandi_occ_name    ON scandinavia_occupation_wages(occupation);
CREATE INDEX IF NOT EXISTS idx_scandi_occ_country ON scandinavia_occupation_wages(country_iso);
"""

# Moneda y tasa local→EUR por país
_COUNTRY_META = {
    'NO': ('NOK', 1/11.65),
    'SE': ('SEK', 1/11.40),
    'DK': ('DKK', 1/7.46),
}


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


def run_scandinavia_wages_import(db) -> dict:
    db.execute(text(DDL_SCANDI_OCC))
    db.commit()
    _ensure_occupation_salary_table(db)

    # Construir datos por país
    countries = {
        'NO': {'eur_vals': {}, 'max_eur': 0},
        'SE': {'eur_vals': {}, 'max_eur': 0},
        'DK': {'eur_vals': {}, 'max_eur': 0},
    }

    # Insertar ocupaciones específicas y acumular por ISCO
    occ_inserted = 0
    for occ_name, isco_grp, no_eur, se_eur, dk_eur in _OCCUPATIONS:
        for country, eur_val in [('NO', no_eur), ('SE', se_eur), ('DK', dk_eur)]:
            currency, local_rate = _COUNTRY_META[country]
            monthly_local = round(eur_val / local_rate, 0)
            monthly_usd   = round(eur_val * EUR_TO_USD, 2)
            annual_usd    = round(monthly_usd * 12, 2)

            db.execute(text("""
                INSERT INTO scandinavia_occupation_wages
                    (country_iso, occupation, isco_group, monthly_local, currency,
                     monthly_eur, monthly_usd, annual_usd, year, source)
                VALUES (:cc, :occ, :isco, :local, :cur,
                     :eur, :usd, :annual, 2026,
                     'Emplosome/SCB/SSB/DST 2026 comparative analysis')
                ON CONFLICT (country_iso, occupation, year) DO UPDATE SET
                    monthly_local = EXCLUDED.monthly_local,
                    monthly_eur   = EXCLUDED.monthly_eur,
                    monthly_usd   = EXCLUDED.monthly_usd,
                    annual_usd    = EXCLUDED.annual_usd
            """), {
                'cc': country, 'occ': occ_name, 'isco': isco_grp,
                'local': monthly_local, 'cur': currency,
                'eur': float(eur_val), 'usd': monthly_usd, 'annual': annual_usd,
            })
            occ_inserted += 1

            # Acumular para ISCO groups
            if isco_grp not in countries[country]['eur_vals']:
                countries[country]['eur_vals'][isco_grp] = []
            countries[country]['eur_vals'][isco_grp].append(eur_val)
            countries[country]['max_eur'] = max(countries[country]['max_eur'], eur_val)

    db.commit()

    # Calcular ISCO 5 y 6 (sin datos directos → proxy)
    # ISCO 5 (Service&Sales): 90% del valor de Cleaning (ISCO 9) — sector mixto
    # ISCO 6 (Agriculture): promedio Construction + Truck Driver (trabajo manual similar)
    _PROXY = {
        'NO': {5: 3200 * 0.95, 6: (3750 + 3800) / 2},
        'SE': {5: 2550 * 0.95, 6: (3100 + 2980) / 2},
        'DK': {5: 3600 * 0.95, 6: (4500 + 4300) / 2},
    }
    for country in ['NO', 'SE', 'DK']:
        for isco_grp, eur_val in _PROXY[country].items():
            if isco_grp not in countries[country]['eur_vals']:
                countries[country]['eur_vals'][isco_grp] = []
            countries[country]['eur_vals'][isco_grp].append(eur_val)

    # Insertar en occupation_salary (promedio por ISCO group)
    isco_labels = {
        1: 'Managers / Directivos', 2: 'Professionals / Profesionales',
        3: 'Technicians / Técnicos', 4: 'Clerical / Administrativos',
        5: 'Service & Sales / Servicios', 6: 'Agricultural / Agrícola',
        7: 'Craft trades / Artesanos', 8: 'Machine operators / Operadores',
        9: 'Elementary / Ocupaciones básicas',
    }

    sal_inserted = 0
    for country in ['NO', 'SE', 'DK']:
        currency, local_rate = _COUNTRY_META[country]
        max_eur = countries[country]['max_eur']

        for isco_grp, eur_list in countries[country]['eur_vals'].items():
            avg_eur     = sum(eur_list) / len(eur_list)
            monthly_usd = round(avg_eur * EUR_TO_USD, 2)
            monthly_local = round(avg_eur / local_rate, 0)
            score       = round(avg_eur / max_eur * 100, 1) if max_eur else 0

            db.execute(text("""
                INSERT INTO occupation_salary
                    (country_iso, isco_group, isco_label, median_monthly_local,
                     median_monthly_usd, currency, profession_score, year, source, updated_at)
                VALUES (:cc, :isco, :label, :local, :usd, :cur, :score, 2026,
                     'Emplosome/SCB/SSB/DST 2026 comparative analysis', NOW())
                ON CONFLICT (country_iso, isco_group) DO UPDATE SET
                    isco_label=EXCLUDED.isco_label, median_monthly_local=EXCLUDED.median_monthly_local,
                    median_monthly_usd=EXCLUDED.median_monthly_usd, profession_score=EXCLUDED.profession_score,
                    year=EXCLUDED.year, source=EXCLUDED.source, updated_at=NOW()
            """), {
                'cc': country, 'isco': isco_grp,
                'label': isco_labels.get(isco_grp, ''),
                'local': monthly_local, 'usd': monthly_usd,
                'cur': currency, 'score': score,
            })
            sal_inserted += 1

    db.commit()
    return {
        'scandinavia_occupations_inserted': occ_inserted,
        'occupation_salary_rows': sal_inserted,
        'countries': ['NO', 'SE', 'DK'],
        'status': 'ok',
        'source': 'Emplosome/SCB/SSB/DST 2026',
        'fx_rate': '1 EUR = 1.08 USD | 11.65 NOK | 11.40 SEK | 7.46 DKK',
    }


# ── Lookup ────────────────────────────────────────────────────────────────────

def get_scandinavia_occupation_income(country: str, profession: str, db) -> dict | None:
    """Busca salario específico en NO/SE/DK por nombre de ocupación."""
    if not profession or country not in ('NO', 'SE', 'DK'):
        return None

    for query in [
        "SELECT occupation, monthly_usd, annual_usd, isco_group FROM scandinavia_occupation_wages WHERE country_iso=:cc AND LOWER(occupation) LIKE '%' || LOWER(:p) || '%' AND year=2026 LIMIT 1",
    ]:
        row = db.execute(text(query), {'cc': country, 'p': profession.strip()}).fetchone()
        if row and row[1]:
            return {
                'occupation':  row[0],
                'monthly_usd': float(row[1]),
                'annual_usd':  float(row[2]),
                'isco_group':  row[3],
                'source':      f'Scandinavia wages 2026 ({country})',
            }
    return None
