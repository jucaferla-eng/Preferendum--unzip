"""
market_data_agent.py — Preferendum
====================================
Agente mensual que recopila precio de arriendo por m² por comuna/barrio
desde portales inmobiliarios de cada país via Apify.

Construye el índice de ingreso relativo:
  - Mediana global = 100
  - Commune más cara > 100, más barata < 100
  - Mismo resultado que FB/Instagram pero sin datos personales — solo geo

Corre mensualmente. Triggerable via POST /admin/run-market-agent

En memoria de José Ignacio Fernández (1989–2024)
"""

import os, json, time, hashlib
import requests as _requests
from datetime import datetime

APIFY_TOKEN = os.getenv('APIFY_API_TOKEN')
APIFY_BASE  = 'https://api.apify.com/v2'

# ══════════════════════════════════════════════════════════════
# PORTALES POR PAÍS
# Cada entry define qué actor de Apify usar y cómo parsear
# ══════════════════════════════════════════════════════════════

PORTALS = [
    # ── Chile ──────────────────────────────────────────────────
    {
        'country': 'CL', 'country_name': 'Chile',
        'portal': 'Portal Inmobiliario',
        'actor': 'apify/web-scraper',
        'start_urls': [
            'https://www.portalinmobiliario.com/arriendo/departamento/region-metropolitana-metropolitana',
        ],
        'price_selector': '[class*="price"]',
        'area_selector':  '[class*="surface"], [class*="area"]',
        'location_selector': '[class*="location"], [class*="commune"]',
    },
    # ── Argentina ───────────────────────────────────────────────
    {
        'country': 'AR', 'country_name': 'Argentina',
        'portal': 'ZonaProp',
        'actor': 'apify/web-scraper',
        'start_urls': [
            'https://www.zonaprop.com.ar/departamentos-alquiler-capital-federal.html',
            'https://www.zonaprop.com.ar/departamentos-alquiler-rosario.html',
        ],
        'price_selector': '[data-qa="POSTING_CARD_PRICE"]',
        'area_selector':  '[data-qa="POSTING_CARD_FEATURES"]',
        'location_selector': '[data-qa="POSTING_CARD_LOCATION"]',
    },
    # ── México ──────────────────────────────────────────────────
    {
        'country': 'MX', 'country_name': 'México',
        'portal': 'Inmuebles24',
        'actor': 'apify/web-scraper',
        'start_urls': [
            'https://www.inmuebles24.com/propiedades-en-renta-en-ciudad-de-mexico.html',
            'https://www.inmuebles24.com/propiedades-en-renta-en-guadalajara.html',
            'https://www.inmuebles24.com/propiedades-en-renta-en-monterrey.html',
        ],
        'price_selector': '[class*="price"]',
        'area_selector':  '[class*="surface"]',
        'location_selector': '[class*="location"]',
    },
    # ── Colombia ────────────────────────────────────────────────
    {
        'country': 'CO', 'country_name': 'Colombia',
        'portal': 'Metrocuadrado',
        'actor': 'apify/web-scraper',
        'start_urls': [
            'https://www.metrocuadrado.com/apartamentos/arriendo/bogota/',
            'https://www.metrocuadrado.com/apartamentos/arriendo/medellin/',
        ],
        'price_selector': '[class*="price"], [class*="valor"]',
        'area_selector':  '[class*="area"], [class*="metros"]',
        'location_selector': '[class*="location"], [class*="sector"]',
    },
    # ── Brasil ──────────────────────────────────────────────────
    {
        'country': 'BR', 'country_name': 'Brasil',
        'portal': 'ZAP Imóveis',
        'actor': 'apify/web-scraper',
        'start_urls': [
            'https://www.zapimoveis.com.br/aluguel/apartamentos/sp+sao-paulo/',
            'https://www.zapimoveis.com.br/aluguel/apartamentos/rj+rio-de-janeiro/',
        ],
        'price_selector': '[class*="price"]',
        'area_selector':  '[class*="area"]',
        'location_selector': '[class*="address"]',
    },
    # ── USA ─────────────────────────────────────────────────────
    {
        'country': 'US', 'country_name': 'USA',
        'portal': 'Zillow',
        'actor': 'maxcopell/zillow-scraper',
        'start_urls': [
            'https://www.zillow.com/new-york-ny/rentals/',
            'https://www.zillow.com/los-angeles-ca/rentals/',
            'https://www.zillow.com/chicago-il/rentals/',
            'https://www.zillow.com/miami-fl/rentals/',
        ],
        'price_selector': '[data-test="property-card-price"]',
        'area_selector':  '[data-test="property-card-sqft"]',
        'location_selector': '[data-test="property-card-addr"]',
    },
    # ── España ──────────────────────────────────────────────────
    {
        'country': 'ES', 'country_name': 'España',
        'portal': 'Idealista',
        'actor': 'apify/web-scraper',
        'start_urls': [
            'https://www.idealista.com/alquiler-viviendas/madrid-madrid/',
            'https://www.idealista.com/alquiler-viviendas/barcelona-barcelona/',
        ],
        'price_selector': '[class*="price"]',
        'area_selector':  '[class*="surface"]',
        'location_selector': '[class*="item-link"]',
    },
    # ── UK ──────────────────────────────────────────────────────
    {
        'country': 'GB', 'country_name': 'United Kingdom',
        'portal': 'Rightmove',
        'actor': 'apify/web-scraper',
        'start_urls': [
            'https://www.rightmove.co.uk/property-to-rent/find.html?locationIdentifier=REGION%5E87490&propertyTypes=flat',
        ],
        'price_selector': '[class*="price"]',
        'area_selector':  '[class*="size"]',
        'location_selector': '[class*="address"]',
    },
]

# ══════════════════════════════════════════════════════════════
# APIFY RUNNER
# ══════════════════════════════════════════════════════════════

def run_apify_scraper(portal: dict, max_items: int = 200) -> list:
    """Corre el actor de Apify y devuelve los items crudos."""
    if not APIFY_TOKEN:
        print(f'[Agent] Sin APIFY_API_TOKEN — devolviendo datos mock para {portal["country"]}')
        return []

    actor_id = portal['actor'].replace('/', '~')
    run_input = {
        'startUrls': [{'url': u} for u in portal['start_urls']],
        'maxRequestsPerCrawl': max_items,
        'pageFunction': _build_page_function(portal),
    }

    # Iniciar el run
    resp = _requests.post(
        f'{APIFY_BASE}/acts/{actor_id}/runs',
        params={'token': APIFY_TOKEN},
        json=run_input,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f'[Apify Error] {portal["portal"]}: {resp.status_code} {resp.text[:200]}')
        return []

    run_id = resp.json()['data']['id']
    print(f'[Apify] {portal["portal"]} run started: {run_id}')

    # Esperar hasta que termine (máx 10 min)
    for _ in range(60):
        time.sleep(10)
        status_resp = _requests.get(
            f'{APIFY_BASE}/actor-runs/{run_id}',
            params={'token': APIFY_TOKEN},
            timeout=10,
        )
        status = status_resp.json()['data']['status']
        if status == 'SUCCEEDED':
            break
        if status in ('FAILED', 'ABORTED', 'TIMED-OUT'):
            print(f'[Apify] {portal["portal"]} run {status}')
            return []

    # Obtener resultados
    dataset_id = status_resp.json()['data']['defaultDatasetId']
    items_resp = _requests.get(
        f'{APIFY_BASE}/datasets/{dataset_id}/items',
        params={'token': APIFY_TOKEN, 'format': 'json', 'limit': max_items},
        timeout=30,
    )
    return items_resp.json() if items_resp.status_code == 200 else []


def _build_page_function(portal: dict) -> str:
    """Genera el pageFunction JS para el web-scraper de Apify."""
    return f"""
async function pageFunction(context) {{
    const {{ $, request }} = context;
    const results = [];
    const priceEls  = $('{portal["price_selector"]}');
    const areaEls   = $('{portal["area_selector"]}');
    const locEls    = $('{portal["location_selector"]}');

    const count = Math.min(priceEls.length, 50);
    for (let i = 0; i < count; i++) {{
        const priceText = $(priceEls[i]).text().trim();
        const areaText  = i < areaEls.length  ? $(areaEls[i]).text().trim()  : '';
        const locText   = i < locEls.length   ? $(locEls[i]).text().trim()   : '';

        const priceNum = parseFloat(priceText.replace(/[^0-9.]/g, ''));
        const areaNum  = parseFloat(areaText.replace(/[^0-9.]/g, ''));

        if (priceNum > 0 && areaNum > 10) {{
            results.push({{
                price:    priceNum,
                area_m2:  areaNum,
                price_m2: Math.round(priceNum / areaNum),
                location: locText,
                url:      request.url,
            }});
        }}
    }}
    return results;
}}
"""


# ══════════════════════════════════════════════════════════════
# PROCESAMIENTO — construir tabla de comunas
# ══════════════════════════════════════════════════════════════

def parse_commune_from_location(location_text: str, country: str) -> str:
    """Extrae nombre de comuna del texto de ubicación."""
    if not location_text:
        return 'Desconocida'
    parts = [p.strip() for p in location_text.replace(',', '|').replace('-', '|').split('|')]
    # Tomar la parte más específica (primera o segunda)
    for p in parts[:2]:
        if len(p) > 2:
            return p.title()
    return parts[0].title() if parts else 'Desconocida'


def aggregate_by_commune(items: list, country: str) -> dict:
    """Agrupa items por comuna y calcula precio promedio por m²."""
    communes = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        price_m2 = item.get('price_m2', 0)
        location = item.get('location', '')
        if price_m2 <= 0:
            continue
        commune = parse_commune_from_location(location, country)
        if commune not in communes:
            communes[commune] = []
        communes[commune].append(price_m2)

    return {
        commune: round(sum(prices) / len(prices), 2)
        for commune, prices in communes.items()
        if len(prices) >= 3  # mínimo 3 muestras para ser válido
    }


def build_global_index(all_country_data: list) -> list:
    """
    Construye el índice relativo global.
    Mediana de todos los precios por m² = índice 100.
    Cada comuna recibe un índice proporcional.
    """
    # Recolectar todos los precios para calcular la mediana global
    all_prices = [d['price_m2_avg'] for d in all_country_data if d['price_m2_avg'] > 0]
    if not all_prices:
        return all_country_data

    all_prices.sort()
    median_price = all_prices[len(all_prices) // 2]

    for d in all_country_data:
        if d['price_m2_avg'] > 0:
            d['income_index'] = round((d['price_m2_avg'] / median_price) * 100, 1)
        else:
            d['income_index'] = 100.0

    return all_country_data


def calculate_cpm_from_index(income_index: float) -> float:
    """
    CPM en USD según índice de ingreso.
    Índice 100 (mediana global) = CPM $6.00
    Escala logarítmica para no penalizar demasiado a mercados pobres.
    """
    base_cpm = 6.0
    cpm = base_cpm * (income_index / 100.0) ** 0.65
    return round(max(1.5, min(20.0, cpm)), 2)


def get_se_tier(income_index: float) -> str:
    if income_index >= 160: return 'A'
    if income_index >= 110: return 'B'
    if income_index >= 70:  return 'C'
    return 'D'


# ══════════════════════════════════════════════════════════════
# RUNNER PRINCIPAL
# ══════════════════════════════════════════════════════════════

def run_full_agent() -> dict:
    """
    Corre el agente completo para todos los países.
    Devuelve la tabla global lista para guardar en BD.
    """
    print(f'\n[MarketAgent] Iniciando — {datetime.utcnow().isoformat()}')
    all_communes = []
    errors = []

    for portal in PORTALS:
        print(f'\n[MarketAgent] Scraping {portal["portal"]} ({portal["country"]})...')
        try:
            items = run_apify_scraper(portal, max_items=300)
            commune_prices = aggregate_by_commune(items, portal['country'])

            for commune, price_m2 in commune_prices.items():
                all_communes.append({
                    'country':      portal['country'],
                    'country_name': portal['country_name'],
                    'commune':      commune,
                    'portal':       portal['portal'],
                    'price_m2_avg': price_m2,
                    'income_index': 100.0,  # se recalcula después
                    'cpm_usd':      6.0,
                    'se_tier':      'C',
                    'sample_count': len(items),
                    'scraped_at':   datetime.utcnow().isoformat(),
                })
            print(f'[MarketAgent] {portal["portal"]}: {len(commune_prices)} comunas procesadas')

        except Exception as e:
            print(f'[MarketAgent] Error en {portal["portal"]}: {e}')
            errors.append({'portal': portal['portal'], 'error': str(e)})

    # Calcular índice global y CPM
    all_communes = build_global_index(all_communes)
    for c in all_communes:
        c['cpm_usd']  = calculate_cpm_from_index(c['income_index'])
        c['se_tier']  = get_se_tier(c['income_index'])

    # Ordenar por índice descendente
    all_communes.sort(key=lambda x: x['income_index'], reverse=True)

    result = {
        'total_communes': len(all_communes),
        'countries':      list({c['country'] for c in all_communes}),
        'generated_at':   datetime.utcnow().isoformat(),
        'errors':         errors,
        'communes':       all_communes,
    }

    print(f'\n[MarketAgent] Completado: {len(all_communes)} comunas en {len(result["countries"])} países')
    return result


def get_fallback_table() -> list:
    """
    Tabla hardcodeada de respaldo para cuando Apify no está disponible.
    Basada en datos INE/SII Chile + estimaciones regionales.
    Índice 100 = La Florida (mediana RM Santiago).
    """
    return [
        # Chile RM
        {'country':'CL','commune':'Vitacura',       'income_index':210,'cpm_usd':14.50,'se_tier':'A'},
        {'country':'CL','commune':'Las Condes',      'income_index':185,'cpm_usd':12.80,'se_tier':'A'},
        {'country':'CL','commune':'Lo Barnechea',    'income_index':170,'cpm_usd':11.90,'se_tier':'A'},
        {'country':'CL','commune':'Providencia',     'income_index':160,'cpm_usd':11.20,'se_tier':'A'},
        {'country':'CL','commune':'La Reina',        'income_index':150,'cpm_usd':10.50,'se_tier':'A'},
        {'country':'CL','commune':'Ñuñoa',           'income_index':125,'cpm_usd': 8.40,'se_tier':'B'},
        {'country':'CL','commune':'Macul',           'income_index':115,'cpm_usd': 7.60,'se_tier':'B'},
        {'country':'CL','commune':'San Miguel',      'income_index':110,'cpm_usd': 7.20,'se_tier':'B'},
        {'country':'CL','commune':'La Florida',      'income_index':100,'cpm_usd': 6.00,'se_tier':'C'},
        {'country':'CL','commune':'Santiago',        'income_index': 92,'cpm_usd': 5.20,'se_tier':'C'},
        {'country':'CL','commune':'Recoleta',        'income_index': 80,'cpm_usd': 4.40,'se_tier':'C'},
        {'country':'CL','commune':'Maipú',           'income_index': 88,'cpm_usd': 5.60,'se_tier':'C'},
        {'country':'CL','commune':'La Pintana',      'income_index': 52,'cpm_usd': 3.20,'se_tier':'D'},
        {'country':'CL','commune':'El Bosque',       'income_index': 55,'cpm_usd': 3.40,'se_tier':'D'},
        {'country':'CL','commune':'Cerro Navia',     'income_index': 48,'cpm_usd': 3.00,'se_tier':'D'},
        # USA
        {'country':'US','commune':'Beverly Hills',   'income_index':520,'cpm_usd':19.80,'se_tier':'A'},
        {'country':'US','commune':'Manhattan',       'income_index':480,'cpm_usd':19.20,'se_tier':'A'},
        {'country':'US','commune':'Palo Alto',       'income_index':450,'cpm_usd':18.50,'se_tier':'A'},
        {'country':'US','commune':'Brooklyn',        'income_index':220,'cpm_usd':14.20,'se_tier':'A'},
        {'country':'US','commune':'Chicago Loop',    'income_index':180,'cpm_usd':12.20,'se_tier':'A'},
        {'country':'US','commune':'South Side',      'income_index': 70,'cpm_usd': 4.20,'se_tier':'C'},
        # India
        {'country':'IN','commune':'Bandra West',     'income_index':190,'cpm_usd':12.80,'se_tier':'A'},
        {'country':'IN','commune':'Connaught Place',  'income_index':160,'cpm_usd':11.00,'se_tier':'A'},
        {'country':'IN','commune':'Dharavi',         'income_index': 18,'cpm_usd': 1.80,'se_tier':'D'},
        {'country':'IN','commune':'New Delhi Centre', 'income_index':120,'cpm_usd': 7.80,'se_tier':'B'},
        # Nigeria
        {'country':'NG','commune':'Victoria Island', 'income_index':175,'cpm_usd':11.80,'se_tier':'A'},
        {'country':'NG','commune':'Ikoyi',           'income_index':200,'cpm_usd':13.20,'se_tier':'A'},
        {'country':'NG','commune':'Ajegunle',        'income_index': 15,'cpm_usd': 1.60,'se_tier':'D'},
        {'country':'NG','commune':'Lagos Island',    'income_index': 95,'cpm_usd': 5.80,'se_tier':'C'},
        # UK
        {'country':'GB','commune':'Kensington',      'income_index':480,'cpm_usd':19.20,'se_tier':'A'},
        {'country':'GB','commune':'Chelsea',         'income_index':450,'cpm_usd':18.50,'se_tier':'A'},
        {'country':'GB','commune':'Tower Hamlets',   'income_index':130,'cpm_usd': 8.60,'se_tier':'B'},
        {'country':'GB','commune':'Hackney',         'income_index':150,'cpm_usd':10.20,'se_tier':'A'},
    ]


if __name__ == '__main__':
    result = run_full_agent()
    if result['total_communes'] == 0:
        print('\n[MarketAgent] Sin datos de Apify — usando tabla de respaldo')
        communes = get_fallback_table()
    else:
        communes = result['communes']

    print(f'\n{"COMUNA":<25} {"PAÍS":<5} {"ÍNDICE":>8} {"CPM":>8} {"TIER"}')
    print('─' * 55)
    for c in communes[:20]:
        print(f'{c["commune"]:<25} {c["country"]:<5} {c["income_index"]:>8.1f} ${c["cpm_usd"]:>7.2f} SE-{c["se_tier"]}')
    print(f'\nTotal: {len(communes)} comunas')
    print('\nEn memoria de José Ignacio Fernández (1989–2024)')
