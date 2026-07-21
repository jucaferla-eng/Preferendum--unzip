"""
market_data_agent.py
====================
Wrapper de commune_agent.py. Expone la interfaz que espera main.py.
Retorna datos de arriendo m² y CPM para todos los países de la app.
"""

from commune_agent import (
    COMUNAS_DATA,
    GLOBAL_RENT_DATA,
    calculate_cpm,
    calculate_commune_table,
    calculate_all_communes_table,
    get_se_tier,
    allocate_budget,
)
import os

APIFY_TOKEN = os.getenv('APIFY_API_TOKEN', '')


def get_fallback_table():
    """Tabla completa: todos los países y sus ciudades.
    income_index: ciudad más cara de cada país = 100 (referencia por país)
    price_m2_avg = 0 → excluye de _recalculate_global_index (índice ya viene correcto)
    """
    all_communes = calculate_all_communes_table()
    result = []
    for c in all_communes:
        result.append({
            'country':      c['country'],
            'commune':      c['nombre'],
            'income_index': c['income_index'],
            'cpm_usd':      c['cpm_usd'],
            'se_tier':      c['se_tier'],
            'price_m2_avg': 0,
            'population':   c['poblacion'],
            'updated_at':   None,
        })
    return result


def calculate_cpm_from_index(income_index: float, country: str = 'CL') -> float:
    from commune_agent import CPM_BASE_BY_COUNTRY, calculate_cpm as _cpm
    base = CPM_BASE_BY_COUNTRY.get(country, 5.0)
    return _cpm(income_index, base)


def run_apify_scraper(portal, country='CL'):
    return []

def aggregate_by_commune(raw_listings, country='CL'):
    return []

def run_full_agent():
    fallback = get_fallback_table()
    countries = list({r['country'] for r in fallback})
    return {
        'ok': True,
        'total_communes': len(fallback),
        'communes': fallback,
        'countries': sorted(countries),
        'source': 'commune_agent_builtin',
        'errors': [],
    }

def run_uk_land_registry():
    return {'ok': False, 'error': 'UK Land Registry not configured'}
