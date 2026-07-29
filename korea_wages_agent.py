from __future__ import annotations
"""
korea_wages_agent.py — Korea wage data import para Preferendum
==============================================================
Fuente: Ministry of Employment and Labor (MOEL) 2024
  kr_wage_by_occupation_real.csv — salarios por grupo ocupacional KSCO 7th edition

Mapeo KSCO → ISCO:
  KSCO 1 (Managers)               → ISCO 1
  KSCO 2 (Professionals)          → ISCO 2 + ISCO 3 (técnicos incluidos)
  KSCO 3 (Clerks)                 → ISCO 4
  KSCO 4+5 avg (Service+Sales)    → ISCO 5
  KSCO 6 (Agricultural)           → ISCO 6
  KSCO 7 (Craft)                  → ISCO 7
  KSCO 8 (Machine operators)      → ISCO 8
  KSCO 9 (Elementary)             → ISCO 9

Conversión: KRW (miles) → USD nominal 2024
  1 USD = 1,350 KRW (tasa spot 2024 promedio)
  wage_value está en KRW_thousand → multiplicar × 1000 para valor real
"""

import csv
from pathlib import Path
from sqlalchemy import text

KRW_TO_USD = 1 / 1350  # tasa nominal 2024

# KSCO code → (isco_group, isco_label, krw_thousand_month)
# Fuente: kr_wage_by_occupation_real.csv, year=2024
_KSCO_DATA = {
    1: (1, 'Managers / Directivos',                      12223),
    2: (2, 'Professionals / Profesionales',               4996),
    3: (4, 'Clerical / Administrativos',                  4825),
    4: (5, 'Service & Sales / Servicios y Ventas',        3091),  # avg(2226, 3956)
    5: (5, 'Service & Sales / Servicios y Ventas',        3091),  # mismo ISCO 5
    6: (6, 'Agricultural / Agrícola',                     3034),
    7: (7, 'Craft trades / Artesanos',                    4011),
    8: (8, 'Machine operators / Operadores',              4119),
    9: (9, 'Elementary / Ocupaciones básicas',            2593),
}

# ISCO 3 (Technicians): usa datos de ISCO 2 (Professionals) — KSCO los agrupa juntos
_ISCO3_KRW = 4996

_MAX_KRW_THOUSAND = 12223  # ISCO 1 Managers = techo para score


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


def _import_to_occupation_salary(db) -> dict:
    _ensure_occupation_salary_table(db)

    # Construir el mapa ISCO → datos KR (algunos ISCO comparten KSCO group)
    isco_rows = {}
    for ksco_code, (isco_grp, label, krw_k) in _KSCO_DATA.items():
        if isco_grp not in isco_rows:
            isco_rows[isco_grp] = (label, krw_k)

    # Agregar ISCO 3 (Technicians) con datos del KSCO 2
    if 3 not in isco_rows:
        isco_rows[3] = ('Technicians / Técnicos', _ISCO3_KRW)

    inserted = 0
    for isco_grp, (label, krw_k) in sorted(isco_rows.items()):
        monthly_krw  = float(krw_k) * 1000  # KRW real
        monthly_usd  = round(monthly_krw * KRW_TO_USD, 2)
        score        = round(krw_k / _MAX_KRW_THOUSAND * 100, 1)

        db.execute(text("""
            INSERT INTO occupation_salary
                (country_iso, isco_group, isco_label, median_monthly_local,
                 median_monthly_usd, currency, profession_score, year, source, updated_at)
            VALUES
                ('KR', :isco, :label, :local, :usd, 'KRW', :score, 2024,
                 'MOEL Korea 2024 — KSCO 7th Edition (laborstat.moel.go.kr)', NOW())
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
            'local': monthly_krw,
            'usd':   monthly_usd,
            'score': score,
        })
        inserted += 1

    db.commit()
    return {'occupation_salary_kr_rows': inserted}


def run_korea_wages_import(db) -> dict:
    result = _import_to_occupation_salary(db)
    result['status'] = 'ok'
    result['source'] = 'MOEL Korea 2024, KSCO 7th Edition'
    result['fx_rate'] = '1 USD = 1,350 KRW (nominal 2024)'
    return result


# ── Lookup ────────────────────────────────────────────────────────────────────

def get_korea_income(isco_group: int, db) -> dict | None:
    """Retorna ingreso estimado para usuario en Korea según grupo ISCO."""
    try:
        row = db.execute(text("""
            SELECT median_monthly_local, median_monthly_usd, profession_score, isco_label
            FROM occupation_salary
            WHERE country_iso = 'KR' AND isco_group = :ig
        """), {'ig': isco_group}).fetchone()

        if row and row[1]:
            monthly_usd = float(row[1])
            return {
                'isco_group':   isco_group,
                'isco_label':   row[3],
                'monthly_usd':  monthly_usd,
                'annual_usd':   round(monthly_usd * 12, 2),
                'score':        float(row[2]) if row[2] is not None else None,
                'source':       'MOEL Korea 2024',
            }
    except Exception:
        pass
    return None
