from __future__ import annotations
"""
australia_wages_agent.py — Australia wage data import para Preferendum
======================================================================
Fuente: Australian Bureau of Statistics (ABS)
  Employee Earnings and Hours, Australia — May 2025

Datos usados:
  - "All employees, average weekly total cash earnings — by occupation (ANZSCO)"
  - AUD/semana → USD/mes

Mapeo ANZSCO → ISCO 08:
  ANZSCO 1 (Managers)                          → ISCO 1
  ANZSCO 2 (Professionals)                     → ISCO 2
  ANZSCO 3 (Technicians and trades workers)    → ISCO 3 + ISCO 7
  ANZSCO 4 (Community and personal service)    → ISCO 5 (parcial)
  ANZSCO 5 (Clerical and administrative)       → ISCO 4
  ANZSCO 6 (Sales workers)                     → ISCO 5 (parcial)
  ANZSCO 7 (Machinery operators and drivers)   → ISCO 8
  ANZSCO 8 (Labourers)                         → ISCO 9

Conversión:
  AUD → USD: 1 AUD = 0.645 USD (promedio 2025)
  Semana → mes: × (52/12) = × 4.333
"""

from sqlalchemy import text

AUD_TO_USD   = 0.645   # tasa nominal promedio 2025
WEEKS_MONTH  = 52 / 12  # 4.333 semanas/mes

# ANZSCO group → (isco_group, isco_label, weekly_aud)
# Fuente: ABS Employee Earnings and Hours, May 2025 — All employees
_ANZSCO_DATA = {
    'Managers':                              (1, 'Managers / Directivos',             2800.90),
    'Professionals':                         (2, 'Professionals / Profesionales',      2049.60),
    'Technicians and trades workers':        (3, 'Technicians / Técnicos',             1756.90),
    'Community and personal service':        (5, 'Service & Sales / Servicios',         963.15),  # avg(1048.10, 878.20)
    'Clerical and administrative workers':   (4, 'Clerical / Administrativos',         1370.60),
    'Machinery operators and drivers':       (8, 'Machine operators / Operadores',     1695.70),
    'Labourers':                             (9, 'Elementary / Ocupaciones básicas',   1067.70),
}

# ISCO 6 (Agriculture) y ISCO 7 (Craft) — no tienen grupo propio en ANZSCO a este nivel
# ISCO 7 (Craft trades): incluido en ANZSCO 3 "Technicians and trades" — usar dato directo
# ISCO 6 (Agriculture): labourers como proxy (trabajo rural/agrícola en AU)
_EXTRA_ISCO = {
    6: ('Agricultural / Agrícola',     1067.70),  # proxy: labourers AUD/week
    7: ('Craft trades / Artesanos',    1756.90),  # mismo ANZSCO 3 (incluye trades)
}

_MAX_WEEKLY_AUD = 2800.90  # Managers = techo score 100


# ── Import ────────────────────────────────────────────────────────────────────

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


def run_australia_wages_import(db) -> dict:
    _ensure_occupation_salary_table(db)

    # Construir mapa ISCO → (label, weekly_aud) sin duplicados
    isco_rows: dict[int, tuple[str, float]] = {}
    for _, (isco_grp, label, weekly_aud) in _ANZSCO_DATA.items():
        if isco_grp not in isco_rows:
            isco_rows[isco_grp] = (label, weekly_aud)

    # Agregar ISCO 6 y 7
    for isco_grp, (label, weekly_aud) in _EXTRA_ISCO.items():
        if isco_grp not in isco_rows:
            isco_rows[isco_grp] = (label, weekly_aud)

    inserted = 0
    for isco_grp, (label, weekly_aud) in sorted(isco_rows.items()):
        monthly_aud = round(weekly_aud * WEEKS_MONTH, 2)
        monthly_usd = round(monthly_aud * AUD_TO_USD, 2)
        score       = round(weekly_aud / _MAX_WEEKLY_AUD * 100, 1)

        db.execute(text("""
            INSERT INTO occupation_salary
                (country_iso, isco_group, isco_label, median_monthly_local,
                 median_monthly_usd, currency, profession_score, year, source, updated_at)
            VALUES
                ('AU', :isco, :label, :local, :usd, 'AUD', :score, 2025,
                 'ABS Employee Earnings and Hours Australia May 2025', NOW())
            ON CONFLICT (country_iso, isco_group) DO UPDATE SET
                isco_label           = EXCLUDED.isco_label,
                median_monthly_local = EXCLUDED.median_monthly_local,
                median_monthly_usd   = EXCLUDED.median_monthly_usd,
                profession_score     = EXCLUDED.profession_score,
                year                 = EXCLUDED.year,
                source               = EXCLUDED.source,
                updated_at           = NOW()
        """), {
            'isco':  isco_grp,
            'label': label,
            'local': monthly_aud,
            'usd':   monthly_usd,
            'score': score,
        })
        inserted += 1

    db.commit()
    return {
        'occupation_salary_au_rows': inserted,
        'status': 'ok',
        'source': 'ABS Employee Earnings and Hours, Australia May 2025',
        'fx_rate': '1 AUD = 0.645 USD (nominal 2025)',
        'note': 'Average weekly cash earnings × 4.333 weeks/month',
    }


# ── Lookup ────────────────────────────────────────────────────────────────────

def get_australia_income(isco_group: int, db) -> dict | None:
    """Retorna ingreso estimado para usuario en Australia según grupo ISCO."""
    try:
        row = db.execute(text("""
            SELECT median_monthly_local, median_monthly_usd, profession_score, isco_label
            FROM occupation_salary
            WHERE country_iso = 'AU' AND isco_group = :ig
        """), {'ig': isco_group}).fetchone()

        if row and row[1]:
            monthly_usd = float(row[1])
            return {
                'isco_group':   isco_group,
                'isco_label':   row[3],
                'monthly_aud':  float(row[0]),
                'monthly_usd':  monthly_usd,
                'annual_usd':   round(monthly_usd * 12, 2),
                'score':        float(row[2]) if row[2] is not None else None,
                'source':       'ABS Australia 2025',
            }
    except Exception:
        pass
    return None
