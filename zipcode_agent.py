"""
zipcode_agent.py  —  PREFERENDUM
Importa datos de código postal → mediana de arriendo desde APIs públicas.

US : Census Bureau ACS 5-year — B25064 (Median Gross Rent) por ZCTA
     ~33,000 ZIP codes, datos 2022, sin API key requerida.

Otros países: se irán agregando (ONS para UK, INE para ES, IBGE para BR, etc.)
"""

import requests
from commune_agent import get_se_tier, calculate_cpm, CPM_BASE_BY_COUNTRY

CENSUS_BASE = "https://api.census.gov/data/2022/acs/acs5"

# ── ESTADOS UNIDOS ─────────────────────────────────────────────

def fetch_us_zip_rents_by_state(state_fips: str) -> list[dict]:
    """Descarga mediana de arriendo por ZCTA para un estado.
    state_fips: '01'=Alabama ... '56'=Wyoming
    B25064_001E = Median gross rent (USD/mes)
    B01003_001E = Total population
    """
    r = requests.get(CENSUS_BASE, params={
        "get": "B25064_001E,B01003_001E",
        "for": "zip code tabulation area:*",
        "in":  f"state:{state_fips}",
    }, timeout=60)
    r.raise_for_status()
    rows = r.json()
    results = []
    for row in rows[1:]:
        rent_str, pop_str, _state, zcta = row
        rent = int(rent_str) if rent_str and rent_str not in ('-666666666', '-666666666.0', 'null') else 0
        pop  = int(pop_str)  if pop_str  and pop_str  not in ('-666666666', '-666666666.0', 'null') else 0
        if rent > 200:  # filtra ZCTAs sin datos reales
            results.append({'zip': zcta, 'rent_usd': rent, 'population': pop})
    return results

# FIPS codes para los 50 estados + DC
US_STATE_FIPS = [
    '01','02','04','05','06','08','09','10','11','12','13','15','16','17','18',
    '19','20','21','22','23','24','25','26','27','28','29','30','31','32','33',
    '34','35','36','37','38','39','40','41','42','44','45','46','47','48','49',
    '50','51','53','54','55','56',
]

def fetch_all_us_zips() -> list[dict]:
    """Descarga todos los ZCTAs de EEUU estado por estado."""
    all_results = []
    errors = []
    for fips in US_STATE_FIPS:
        try:
            rows = fetch_us_zip_rents_by_state(fips)
            all_results.extend(rows)
        except Exception as e:
            errors.append({'state': fips, 'error': str(e)})
    return all_results, errors

def process_us_zip_data(raw: list[dict]) -> list[dict]:
    """Convierte raw Census data → formato CommuneMarketData."""
    if not raw:
        return []
    # Referencia: ZIP más caro del país = índice 100
    max_rent = max(r['rent_usd'] for r in raw)
    cpm_base = CPM_BASE_BY_COUNTRY.get('US', 18.0)
    results = []
    for r in raw:
        index = round((r['rent_usd'] / max_rent) * 100, 1)
        tier  = get_se_tier(index)
        cpm   = calculate_cpm(index, cpm_base)
        results.append({
            'country':      'US',
            'commune':      r['zip'],
            'income_index': index,
            'cpm_usd':      cpm,
            'se_tier':      tier,
            'price_m2_avg': 0,      # evita que _recalculate_global_index lo sobreescriba
            'population':   r['population'],
            'updated_at':   None,
        })
    return results


# ── REINO UNIDO (pendiente) ─────────────────────────────────────
# ONS Income Estimates for Small Areas (MSOA → postcode district)
# https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/earningsandworkinghours

def fetch_uk_postcode_data():
    return [], [{'error': 'UK ONS import not yet implemented'}]


# ── ESPAÑA (pendiente) ──────────────────────────────────────────
# INE / Idealista por código postal

def fetch_es_postcode_data():
    return [], [{'error': 'ES postal import not yet implemented'}]


# ── DISPATCHER ─────────────────────────────────────────────────

def run_zip_import(country: str) -> dict:
    """Retorna {'data': [...], 'errors': [...], 'total': int}"""
    if country == 'US':
        raw, errors = fetch_all_us_zips()
        data = process_us_zip_data(raw)
        return {'data': data, 'errors': errors, 'total': len(data)}
    if country == 'GB':
        data, errors = fetch_uk_postcode_data()
        return {'data': data, 'errors': errors, 'total': len(data)}
    if country == 'ES':
        data, errors = fetch_es_postcode_data()
        return {'data': data, 'errors': errors, 'total': len(data)}
    return {'data': [], 'errors': [{'error': f'{country} not implemented'}], 'total': 0}
