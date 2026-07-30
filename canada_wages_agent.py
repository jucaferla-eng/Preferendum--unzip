from __future__ import annotations
"""
canada_wages_agent.py — Canada wage data import para Preferendum
================================================================
Fuente: Statistics Canada — Table 14-10-0417-01 (2026-01-09)
  Employee wages by occupation, annual
  Median hourly wage rate, full-time employees, ages 25-54, 2024

Clasificación: NOC 2021 (National Occupational Classification)
Mapeo NOC major group → ISCO 08:
  Management (NOC 0)          → ISCO 1
  Professionals sciences/health/law/edu (NOC 2,3,4) → ISCO 2
  Technicians + admin supervisors (NOC 1,2 technical) → ISCO 3
  Administrative/clerical (NOC 1 admin)   → ISCO 4
  Sales and service (NOC 6)               → ISCO 5
  Natural resources/agriculture (NOC 8)   → ISCO 6
  Trades (NOC 7 technical)                → ISCO 7
  Machine operators (NOC 9 operators)     → ISCO 8
  Labourers/elementary (NOC 9 labourers)  → ISCO 9

Conversión: CAD/hora → USD/mes
  Horas/mes: 40 hrs/sem × 52 sem / 12 = 173.3 hrs/mes
  1 CAD = 0.735 USD (tasa nominal promedio 2024)
"""

from sqlalchemy import text

CAD_TO_USD   = 0.735   # tasa nominal promedio 2024
HOURS_MONTH  = 173.3   # horas de trabajo/mes (full-time)

# NOC 2021 → ISCO 08: (isco_group, isco_label, median_hourly_cad_2024)
# Fuente: Statistics Canada Table 14-10-0417-01, Canada national, 2024
# Se usa el valor más representativo de cada grupo ISCO
_ISCO_MAP = [
    # ISCO 1 — Managers
    # "Management occupations" (NOC 0): $55.90/hr
    (1, 'Managers / Directivos',
     55.90),

    # ISCO 2 — Professionals
    # Promedio: professional natural/applied sciences ($48.08) + health professionals ($46.00)
    # + professional law ($62.50) + education ($45.00) ÷ 4 = $50.40/hr
    (2, 'Professionals / Profesionales',
     50.40),

    # ISCO 3 — Technicians & Associate Professionals
    # Promedio: technical natural/applied sciences ($35.16) + technical health ($35.00) = $35.08/hr
    (3, 'Technicians / Técnicos',
     35.08),

    # ISCO 4 — Clerical Support
    # "Administrative occupations and transportation logistics" (NOC 14): $28.85/hr
    (4, 'Clerical / Administrativos',
     28.85),

    # ISCO 5 — Service & Sales
    # "Sales and service occupations, except management" (NOC 6): $23.08/hr
    (5, 'Service & Sales / Servicios y Ventas',
     23.08),

    # ISCO 6 — Agricultural & Fishery
    # "Workers and labourers in natural resources, agriculture" (NOC 84-85): $24.00/hr
    (6, 'Agricultural / Agrícola',
     24.00),

    # ISCO 7 — Craft & Related Trades
    # Promedio: technical trades/transport officers ($37.68) + general trades ($29.41) = $33.54/hr
    (7, 'Craft trades / Artesanos',
     33.54),

    # ISCO 8 — Machine Operators
    # "Machine operators, assemblers and inspectors in processing, manufacturing" (NOC 93): $25.00/hr
    (8, 'Machine operators / Operadores',
     25.00),

    # ISCO 9 — Elementary Occupations
    # "Labourers in processing, manufacturing and utilities" (NOC 95): $20.51/hr
    (9, 'Elementary / Ocupaciones básicas',
     20.51),
]

_MAX_HOURLY_CAD = 55.90  # Management = techo para score 100


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


def run_canada_wages_import(db) -> dict:
    _ensure_occupation_salary_table(db)
    inserted = 0

    for isco_grp, label, hourly_cad in _ISCO_MAP:
        monthly_cad = round(hourly_cad * HOURS_MONTH, 2)
        monthly_usd = round(monthly_cad * CAD_TO_USD, 2)
        score       = round(hourly_cad / _MAX_HOURLY_CAD * 100, 1)

        db.execute(text("""
            INSERT INTO occupation_salary
                (country_iso, isco_group, isco_label, median_monthly_local,
                 median_monthly_usd, currency, profession_score, year, source, updated_at)
            VALUES
                ('CA', :isco, :label, :local, :usd, 'CAD', :score, 2024,
                 'Statistics Canada Table 14-10-0417-01, median hourly 2024', NOW())
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
            'local': monthly_cad,
            'usd':   monthly_usd,
            'score': score,
        })
        inserted += 1

    db.commit()
    return {
        'occupation_salary_ca_rows': inserted,
        'status': 'ok',
        'source': 'Statistics Canada Table 14-10-0417-01 (2024)',
        'fx_rate': '1 CAD = 0.735 USD (nominal 2024)',
        'note': 'Median hourly wage × 173.3 hrs/month',
    }


# ── Lookup ────────────────────────────────────────────────────────────────────

def get_canada_income(isco_group: int, db) -> dict | None:
    """Retorna ingreso estimado para usuario en Canadá según grupo ISCO."""
    try:
        row = db.execute(text("""
            SELECT median_monthly_local, median_monthly_usd, profession_score, isco_label
            FROM occupation_salary
            WHERE country_iso = 'CA' AND isco_group = :ig
        """), {'ig': isco_group}).fetchone()

        if row and row[1]:
            monthly_usd = float(row[1])
            return {
                'isco_group':   isco_group,
                'isco_label':   row[3],
                'monthly_cad':  float(row[0]),
                'monthly_usd':  monthly_usd,
                'annual_usd':   round(monthly_usd * 12, 2),
                'score':        float(row[2]) if row[2] is not None else None,
                'source':       'Statistics Canada 2024',
            }
    except Exception:
        pass
    return None
