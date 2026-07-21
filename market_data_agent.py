"""
market_data_agent.py
====================
Wrapper around commune_agent.py that exposes the interface expected by main.py.
Provides m² / CPM data for Chile and other LATAM markets.
"""

from commune_agent import (
    COMUNAS_DATA,
    calculate_cpm,
    get_se_tier,
    calculate_commune_table,
    allocate_budget,
)
import os

APIFY_TOKEN = os.getenv('APIFY_API_TOKEN', '')
APIFY_BASE  = 'https://api.apify.com/v2'
PORTALS     = []   # external scrapers — filled when APIFY_TOKEN is set


def get_fallback_table():
    """Return commune table in the format expected by main.py.
    income_index: Vitacura = 100 (basado en precio arriendo UF/m²)
    """
    communes = calculate_commune_table()
    result = []
    for c in communes:
        result.append({
            'country':      'CL',
            'commune':      c['nombre'],
            'income_index': c['income_index'],   # Vitacura=100, relativo a UF/m²
            'cpm_usd':      c['cpm_usd'],
            'se_tier':      c['se_tier'],
            'price_m2_avg': 0,  # 0 = excluye de _recalculate_global_index (índice ya viene correcto)
            'population':   c['poblacion'],
            'updated_at':   None,
        })
    return result


def calculate_cpm_from_index(income_index: float) -> float:
    return calculate_cpm(income_index)


def run_apify_scraper(portal, country='CL'):
    return []


def aggregate_by_commune(raw_listings, country='CL'):
    return []


def run_full_agent():
    """Run the full market agent — uses fallback data when Apify is unavailable."""
    fallback = get_fallback_table()
    return {
        'ok': True,
        'total_communes': len(fallback),
        'communes': fallback,
        'countries': ['CL'],
        'source': 'commune_agent_builtin',
        'errors': [],
    }


def run_uk_land_registry():
    return {'ok': False, 'error': 'UK Land Registry not configured'}
