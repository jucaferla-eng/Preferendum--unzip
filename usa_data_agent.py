"""
usa_data_agent.py — PREFERENDUM
Agente de datos oficiales USA para scoring socioeconómico.

Fuentes:
  BEA CAINC1 2024 — ingreso per cápita por condado (3,115 condados)
  BLS OES 2025    — salario mediano por ocupación SOC (818 ocupaciones)

Metodología: H1 (USA = ingreso muy alto)
  Tier A: top 20% (percentil ≥ 80) + zona con RentPct ≥ 75
  Tier B: percentil 60–79
  Tier C: percentil 35–59
  Tier D: percentil 15–34
  Tier E: percentil 0–14

Integración:
  - import_bea_to_db()  → carga condados en commune_market_data
  - get_occupation_score(title) → score 0–100 por título de trabajo
  - get_county_data(county, state) → datos del condado para lookup manual
"""

import csv, os, logging, statistics, re
from datetime import datetime
from typing import Optional, List, Dict

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BEA_CSV  = os.path.join(BASE_DIR, 'usa_counties_bea2024.csv')
BLS_CSV  = os.path.join(BASE_DIR, 'bls_occupation_scores_2025.csv')

# ─────────────────────────────────────────────────────────────────────────────
# CARGA DE DATOS EN MEMORIA
# ─────────────────────────────────────────────────────────────────────────────
_bea_counties: List[Dict] = []       # lista de condados BEA
_bea_by_county: Dict      = {}       # "county, STATE" → dict
_bea_by_fips: Dict        = {}       # "01001" → dict
_bls_by_soc: Dict         = {}       # "15-1252" → dict
_bls_by_title: Dict       = {}       # "software developers" → dict
_bls_title_list: List     = []       # para búsqueda fuzzy

_loaded = False

def _load():
    global _bea_counties, _bea_by_county, _bea_by_fips
    global _bls_by_soc, _bls_by_title, _bls_title_list, _loaded

    if _loaded:
        return

    # ── BEA counties ────────────────────────────────────────────
    if os.path.exists(BEA_CSV):
        with open(BEA_CSV, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                try:
                    row['per_capita_usd_2024'] = int(row['per_capita_usd_2024'])
                    row['income_pct']           = float(row['income_pct'])
                    row['income_index']         = float(row['income_index'])
                    _bea_counties.append(row)
                    key = f"{row['county'].lower()}, {row['state'].lower()}"
                    _bea_by_county[key] = row
                    _bea_by_fips[row['fips']] = row
                except Exception:
                    pass
        log.info(f"[USADataAgent] BEA cargado: {len(_bea_counties)} condados")
    else:
        log.warning(f"[USADataAgent] BEA CSV no encontrado: {BEA_CSV}")

    # ── BLS occupations ─────────────────────────────────────────
    if os.path.exists(BLS_CSV):
        with open(BLS_CSV, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                try:
                    row['national_median_salary_usd'] = int(row['national_median_salary_usd'])
                    row['profession_score']            = float(row['profession_score'])
                    soc = row['soc_code']
                    title_key = row['title'].lower().strip()
                    _bls_by_soc[soc]         = row
                    _bls_by_title[title_key] = row
                    _bls_title_list.append((title_key, row))
                except Exception:
                    pass
        log.info(f"[USADataAgent] BLS cargado: {len(_bls_by_soc)} ocupaciones")
    else:
        log.warning(f"[USADataAgent] BLS CSV no encontrado: {BLS_CSV}")

    _loaded = True


# ─────────────────────────────────────────────────────────────────────────────
# LOOKUP DE CONDADO
# ─────────────────────────────────────────────────────────────────────────────
def get_county_data(county_name: str, state: str = '') -> Optional[Dict]:
    """
    Busca un condado en los datos BEA.
    county_name: nombre del condado (ej: 'Marin', 'New York', 'Los Angeles County')
    state: código o nombre del estado (ej: 'CA', 'NY', 'California')
    Retorna dict con: fips, county, state, per_capita_usd_2024, income_pct, income_index, se_tier
    """
    _load()
    if not _bea_counties:
        return None

    county_clean = re.sub(r'\s*(county|parish|borough|census area)\s*$', '', county_name, flags=re.IGNORECASE).strip().lower()
    state_clean  = state.strip().lower()

    # 1. Búsqueda exacta county + state
    key = f"{county_clean}, {state_clean}"
    if key in _bea_by_county:
        return _bea_by_county[key]

    # 2. Solo por nombre de condado (sin state)
    matches = [c for c in _bea_counties if c['county'].lower() == county_clean]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1 and state_clean:
        for m in matches:
            if state_clean in m['state'].lower():
                return m
        return matches[0]

    # 3. Búsqueda parcial
    matches = [c for c in _bea_counties if county_clean in c['county'].lower()]
    if matches:
        if state_clean:
            state_matches = [m for m in matches if state_clean in m['state'].lower()]
            if state_matches:
                return state_matches[0]
        return matches[0]

    return None


def get_county_by_fips(fips: str) -> Optional[Dict]:
    """Busca condado por código FIPS (ej: '06037' = Los Angeles County, CA)."""
    _load()
    return _bea_by_fips.get(fips.zfill(5))


# ─────────────────────────────────────────────────────────────────────────────
# LOOKUP DE OCUPACIÓN
# ─────────────────────────────────────────────────────────────────────────────
def get_occupation_score(title_or_soc: str) -> Optional[Dict]:
    """
    Retorna datos BLS para una ocupación.
    Acepta: SOC code ('15-1252') o título ('Software Developers', 'Médico', etc.)
    Retorna dict con: soc_code, title, national_median_salary_usd, profession_score (0-100)
    """
    _load()
    if not _bls_by_soc:
        return None

    query = title_or_soc.strip()

    # 1. Exacto por SOC code
    if re.match(r'^\d{2}-\d{4}$', query):
        return _bls_by_soc.get(query)

    # 2. Exacto por título
    query_lower = query.lower()
    if query_lower in _bls_by_title:
        return _bls_by_title[query_lower]

    # 3. Búsqueda parcial (contiene)
    matches = [(t, d) for t, d in _bls_title_list if query_lower in t]
    if matches:
        # Preferir el match más corto (más específico)
        return min(matches, key=lambda x: len(x[0]))[1]

    # 4. Palabras clave individuales
    words = [w for w in query_lower.split() if len(w) > 3]
    for word in words:
        matches = [(t, d) for t, d in _bls_title_list if word in t]
        if matches:
            return min(matches, key=lambda x: len(x[0]))[1]

    return None


def profession_score_to_tier(score: float) -> str:
    """Convierte score BLS (0-100) a tier H1 (USA)."""
    if score >= 80: return 'A'
    if score >= 60: return 'B'
    if score >= 35: return 'C'
    if score >= 15: return 'D'
    return 'E'


# ─────────────────────────────────────────────────────────────────────────────
# IMPORTACIÓN A BASE DE DATOS
# ─────────────────────────────────────────────────────────────────────────────
def import_bea_to_db(db) -> dict:
    """
    Importa todos los condados BEA 2024 a commune_market_data.
    Usa la metodología H1: percentil = income_pct ya calculado.
    GeoScore = 0.70 × income_pct + 0.30 × RentIndexScore (aproximado con BEA)
    """
    _load()
    if not _bea_counties:
        return {'ok': False, 'error': 'BEA CSV no cargado', 'inserted': 0}

    from sqlalchemy import text as sa_text
    from commune_agent import CPM_BASE_BY_COUNTRY, calculate_cpm

    cpm_base = CPM_BASE_BY_COUNTRY.get('US', 18.0)
    inserted = 0
    errors   = 0

    # RentIndexScore lookup (misma tabla que rental_price_agent)
    def _ris(ri):
        for thr, sc in [(60,10),(80,25),(95,40),(106,50),(121,65),(151,80)]:
            if ri < thr: return sc
        return 95

    for c in _bea_counties:
        try:
            income_pct = c['income_pct']
            income_idx = c['income_index']
            geo_score  = round(0.70 * income_pct + 0.30 * _ris(income_idx), 1)
            cpm        = calculate_cpm(income_pct, cpm_base)
            tier       = c['se_tier']
            commune    = f"{c['county']}, {c['state']}"

            result = db.execute(sa_text("""
                UPDATE commune_market_data SET
                    income_index = :idx, rent_index = :idx, rent_pct = :pct,
                    geo_score = :gs, se_tier = :tier, cpm_usd = :cpm,
                    portal = :src, sample_count = 0, updated_at = NOW()
                WHERE country = 'US' AND commune = :commune
            """), {'idx': income_idx, 'pct': income_pct, 'gs': geo_score,
                   'tier': tier, 'cpm': cpm, 'src': 'BEA CAINC1 2024',
                   'commune': commune})

            if result.rowcount == 0:
                db.execute(sa_text("""
                    INSERT INTO commune_market_data
                        (country, commune, price_m2_avg, income_index, rent_index,
                         rent_pct, geo_score, cpm_usd, se_tier, portal, sample_count,
                         scraped_at, updated_at)
                    VALUES ('US', :commune, 0, :idx, :idx, :pct, :gs, :cpm,
                            :tier, 'BEA CAINC1 2024', 0, NOW(), NOW())
                """), {'commune': commune, 'idx': income_idx, 'pct': income_pct,
                       'gs': geo_score, 'cpm': cpm, 'tier': tier})

            inserted += 1
            if inserted % 500 == 0:
                db.commit()
                log.info(f"[USADataAgent] Importados {inserted} condados...")

        except Exception as e:
            errors += 1
            log.error(f"[USADataAgent] Error {c.get('county')}: {e}")
            try: db.rollback()
            except: pass

    try:
        db.commit()
    except Exception:
        pass

    log.info(f"[USADataAgent] BEA import completo: {inserted} condados, {errors} errores")
    return {
        'ok':      True,
        'country': 'US',
        'inserted': inserted,
        'errors':   errors,
        'source':   'BEA CAINC1 2024',
        'updated_at': datetime.utcnow().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# IMPORTACIÓN BLS SOC -> occupation_unified (FINAL SOCIOECONOMIC ASSIGNMENT
# HARDENING, Phase 3)
# ─────────────────────────────────────────────────────────────────────────────
#
# SOC major_group (2-digit BLS prefix, e.g. '17-0000') -> ISCO-08 major group.
# Derived, not invented: cross-referenced from the two ALREADY-APPROVED
# legacy mapping dicts in main.py (_US_PROFESSION_SOC: category -> major_group,
# _OCC_TO_ISCO: category -> isco_group) via their shared category keys. For
# 19 of the 21 major groups every category key sharing that major_group
# agrees on a single ISCO value, so the value is unambiguous. Two major
# groups carry a genuine internal split in that pre-existing mapping:
#   '17-0000' (Architecture & Engineering): engineering/ing_civil/arquitecto/
#     ing_otro -> 2 (Professionals), but tecnico -> 3 (Technicians) — SOC's
#     17-0000 spans both 17-2xxx (engineers) and 17-3xxx (eng. technicians),
#     a distinction the 2-digit major_group cannot resolve.
#   '29-0000' (Healthcare Practitioners & Technical): medico/dentista/
#     farmaceutico/healthcare_pro -> 2, but enfermero -> 3.
# For both, the majority (4 of 5 keys) and the major group's own predominant
# occupations resolve to 2 (Professionals); that value is used for the BLS
# import below. This is a documented DATA LIMITATION inherited from the
# pre-existing mapping, not a new approximation invented by this import —
# see the final hardening report. It affects only occupation_unified.isco_group
# (the fallback path a NON-US user takes when submitting a raw US SOC code),
# never occupation_code/title/profession_score/median_annual_usd, which come
# straight from the tracked BLS CSV with no interpretation.
_BLS_MAJOR_GROUP_TO_ISCO: dict[str, int] = {
    '11-0000': 1, '13-0000': 2, '15-0000': 2, '17-0000': 2, '19-0000': 2,
    '21-0000': 2, '23-0000': 2, '25-0000': 2, '27-0000': 2, '29-0000': 2,
    '31-0000': 3, '33-0000': 5, '35-0000': 5, '37-0000': 9, '39-0000': 5,
    '41-0000': 5, '43-0000': 4, '45-0000': 6, '47-0000': 7, '49-0000': 7,
    '51-0000': 8, '53-0000': 8,
}


def import_bls_occupations_to_db(db) -> dict:
    """Importa las 818 ocupaciones BLS OES May 2025 (bls_occupation_scores_2025.csv,
    ya trackeado en el repo) a occupation_unified: una fila por SOC code,
    country_iso='US', occupation_type='SOC'.

    Idempotente / re-ejecutable: hace SELECT por (occupation_code, country_iso)
    y UPDATE si ya existe, INSERT si no — sin duplicados sin importar cuántas
    veces se corra, y sin depender de un UNIQUE constraint en el schema (no
    lo tiene). No fabrica ocupación ni salario: occupation_code/title/
    profession_score/median_annual_usd vienen directo del CSV tracked;
    isco_group viene de _BLS_MAJOR_GROUP_TO_ISCO (ver comentario arriba).
    """
    _load()
    if not _bls_by_soc:
        return {'ok': False, 'error': 'BLS CSV no cargado', 'inserted': 0, 'updated': 0}

    from sqlalchemy import text as sa_text

    inserted = updated = 0
    for soc_code, row in _bls_by_soc.items():
        major_group = row.get('major_group', '')
        isco_grp = _BLS_MAJOR_GROUP_TO_ISCO.get(major_group)
        title = row.get('title', '')
        score = row.get('profession_score')
        median = row.get('national_median_salary_usd')
        try:
            existing = db.execute(sa_text("""
                SELECT id FROM occupation_unified
                WHERE occupation_code=:code AND country_iso='US'
            """), {'code': soc_code}).fetchone()
            if existing:
                db.execute(sa_text("""
                    UPDATE occupation_unified
                    SET occupation_type='SOC', isco_group=:ig, title=:t,
                        profession_score=:sc, median_annual_usd=:med
                    WHERE id=:id
                """), {'ig': isco_grp, 't': title, 'sc': score, 'med': median, 'id': existing[0]})
                updated += 1
            else:
                db.execute(sa_text("""
                    INSERT INTO occupation_unified
                      (occupation_code, country_iso, occupation_type, isco_group,
                       isco_label, title, profession_score, median_annual_usd)
                    VALUES (:code, 'US', 'SOC', :ig, NULL, :t, :sc, :med)
                """), {'code': soc_code, 'ig': isco_grp, 't': title, 'sc': score, 'med': median})
                inserted += 1
        except Exception as e:
            log.error(f"[USADataAgent] Error importando SOC {soc_code}: {e}")

    try:
        db.commit()
    except Exception:
        pass

    log.info(f"[USADataAgent] BLS SOC import completo: {inserted} nuevas, {updated} actualizadas")
    return {
        'ok':        True,
        'inserted':  inserted,
        'updated':   updated,
        'total':     len(_bls_by_soc),
        'source':    'BLS OES May 2025 (bls_occupation_scores_2025.csv)',
        'updated_at': datetime.utcnow().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# ESTADÍSTICAS
# ─────────────────────────────────────────────────────────────────────────────
def get_stats() -> dict:
    """Retorna estadísticas de los datos cargados."""
    _load()
    tiers = {}
    for c in _bea_counties:
        t = c.get('se_tier', '?')
        tiers[t] = tiers.get(t, 0) + 1

    salaries = [d['national_median_salary_usd'] for d in _bls_by_soc.values()]

    return {
        'bea_counties':      len(_bea_counties),
        'bea_tiers':         tiers,
        'bea_median_income': statistics.median(c['per_capita_usd_2024'] for c in _bea_counties) if _bea_counties else 0,
        'bls_occupations':   len(_bls_by_soc),
        'bls_median_salary': statistics.median(salaries) if salaries else 0,
        'bls_top_salary':    max(salaries) if salaries else 0,
        'source_bea':        'BEA CAINC1 2024 (oficial, Gobierno USA)',
        'source_bls':        'BLS OES May 2025 (oficial, Gobierno USA)',
    }
