from __future__ import annotations
"""
ppp_agent.py — Factores PPP para ajuste de salarios en Preferendum
===================================================================
Fuente: World Bank ICP 2022 + IMF WEO 2024
  Price Level Index (PLI): qué tan caro es vivir en ese país vs USA = 1.0
    PLI > 1.0 → país MÁS CARO que USA → ingreso PPP < nominal
    PLI < 1.0 → país MÁS BARATO que USA → ingreso PPP > nominal

  PPP_USD = Nominal_USD / PLI

  Referencia: World Bank "Price level ratio of PPP conversion factor
  to market exchange rate" (PA.NUS.PPPC.RF), 2022.
"""

from sqlalchemy import text

# Price Level Index por país (US = 1.0, 2022-2024)
# Fuente: World Bank ICP 2022, IMF WEO 2024, OECD PPP 2023
PLI: dict[str, float] = {
    # ── Europa Occidental (caros) ──────────────────────────
    'LU': 1.14,   # Luxemburgo
    'NO': 1.40,   # Noruega — el más caro de Europa
    'DK': 1.17,   # Dinamarca
    'SE': 1.06,   # Suecia
    'FI': 1.05,   # Finlandia
    'IE': 1.11,   # Irlanda
    'NL': 1.04,   # Países Bajos
    'BE': 1.01,   # Bélgica
    'AT': 0.99,   # Austria
    'DE': 0.97,   # Alemania
    'FR': 0.98,   # Francia
    'GB': 0.97,   # Reino Unido
    'CH': 1.62,   # Suiza (el más caro del mundo)
    'IT': 0.87,   # Italia
    'ES': 0.81,   # España
    'PT': 0.75,   # Portugal
    'GR': 0.78,   # Grecia
    'SI': 0.80,   # Eslovenia
    # ── Europa del Este ────────────────────────────────────
    'CZ': 0.66,
    'SK': 0.64,
    'HU': 0.60,
    'PL': 0.57,
    'HR': 0.69,
    'RO': 0.56,
    'RS': 0.51,
    'MD': 0.38,
    # ── Ex-Soviéticos / Cáucaso ───────────────────────────
    'RU': 0.52,
    'AM': 0.47,
    'MN': 0.44,
    # ── Medio Oriente / Norte de África ───────────────────
    'TR': 0.48,
    'EG': 0.30,
    'TN': 0.43,
    # ── África Subsahariana ───────────────────────────────
    'NG': 0.38,
    'GH': 0.44,
    'KE': 0.40,
    'TZ': 0.31,
    'ET': 0.26,
    'ZA': 0.45,
    # ── Oceanía ───────────────────────────────────────────
    'AU': 0.90,
    'NZ': 0.87,
    # ── Asia-Pacífico ─────────────────────────────────────
    'SG': 0.85,
    'HK': 0.93,
    'JP': 0.78,
    'KR': 0.72,
    'TW': 0.69,
    'CN': 0.56,
    'TH': 0.52,
    'ID': 0.44,
    'PH': 0.44,
    'VN': 0.40,
    'KH': 0.35,
    'IN': 0.29,
    'BD': 0.33,
    'PK': 0.28,
    'LK': 0.40,
    # ── Norte América ─────────────────────────────────────
    'US': 1.00,
    'CA': 0.88,
    'MX': 0.46,
    # ── Caribe / Centroamérica ────────────────────────────
    'DO': 0.46,
    'GT': 0.43,
    'HN': 0.38,
    # ── Sudamérica ────────────────────────────────────────
    'BR': 0.47,
    'AR': 0.36,   # Argentina: complejidad cambiaria, valor estimado
    'CL': 0.56,
    'CO': 0.44,
    'PE': 0.48,
    'UY': 0.74,
    'PY': 0.38,
}

DDL_PPP_FACTORS = """
ALTER TABLE occupation_salary
    ADD COLUMN IF NOT EXISTS median_monthly_ppp_usd REAL,
    ADD COLUMN IF NOT EXISTS ppp_price_level_index  REAL;
"""


def run_ppp_import(db) -> dict:
    """
    Aplica factores PPP a occupation_salary:
    - Agrega columnas median_monthly_ppp_usd y ppp_price_level_index
    - median_monthly_ppp_usd = median_monthly_usd / PLI
    """
    db.execute(text(DDL_PPP_FACTORS))
    db.commit()

    updated = skipped = 0
    rows = db.execute(text(
        "SELECT id, country_iso, median_monthly_usd FROM occupation_salary WHERE median_monthly_usd > 0"
    )).fetchall()

    for row_id, cc, nominal in rows:
        pli = PLI.get(cc)
        if not pli or not nominal:
            skipped += 1
            continue
        ppp_usd = round(float(nominal) / pli, 2)
        db.execute(text("""
            UPDATE occupation_salary
            SET median_monthly_ppp_usd = :ppp,
                ppp_price_level_index  = :pli
            WHERE id = :id
        """), {'ppp': ppp_usd, 'pli': pli, 'id': row_id})
        updated += 1

    db.commit()

    # También actualizar ilo_wages si tiene columna ppp
    try:
        db.execute(text("ALTER TABLE ilo_wages ADD COLUMN IF NOT EXISTS monthly_ppp_usd REAL"))
        db.execute(text("ALTER TABLE ilo_wages ADD COLUMN IF NOT EXISTS ppp_price_level_index REAL"))
        db.commit()
        ilo_rows = db.execute(text(
            "SELECT id, country_iso2, monthly_usd FROM ilo_wages WHERE monthly_usd > 0"
        )).fetchall()
        ilo_updated = 0
        for row_id, cc, nominal in ilo_rows:
            pli = PLI.get(cc)
            if not pli or not nominal:
                continue
            ppp_usd = round(float(nominal) / pli, 2)
            db.execute(text("""
                UPDATE ilo_wages SET monthly_ppp_usd = :ppp, ppp_price_level_index = :pli
                WHERE id = :id
            """), {'ppp': ppp_usd, 'pli': pli, 'id': row_id})
            ilo_updated += 1
        db.commit()
    except Exception as e:
        ilo_updated = f'error: {e}'

    return {
        'occupation_salary_updated': updated,
        'occupation_salary_skipped': skipped,
        'ilo_wages_updated': ilo_updated,
        'countries_with_pli': len(PLI),
        'status': 'ok',
        'source': 'World Bank ICP 2022 + IMF WEO 2024',
        'note': 'PPP_USD = Nominal_USD / PLI. PLI > 1 = más caro que USA.',
    }


def get_pli(country_iso: str) -> float | None:
    """Retorna el Price Level Index para un país. None si no disponible."""
    return PLI.get(country_iso)


def to_ppp(nominal_usd: float, country_iso: str) -> float | None:
    """Convierte ingreso nominal USD a PPP USD para un país."""
    pli = PLI.get(country_iso)
    if not pli:
        return None
    return round(nominal_usd / pli, 2)
