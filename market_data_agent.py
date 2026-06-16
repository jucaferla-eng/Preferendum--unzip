"""
market_data_agent.py — Preferendum
====================================
Agente semestral que recopila precio de arriendo por m² por comuna/barrio
desde portales inmobiliarios de cada país via Apify.

Construye el índice de ingreso relativo:
  - Mediana global = 100
  - Commune más cara > 100, más barata < 100
  - Mismo resultado que FB/Instagram pero sin datos personales — solo geo

Corre cada 6 meses (precios m² cambian lento). Triggerable via POST /admin/run-market-agent

En memoria de José Ignacio Fernández (1989–2024)
"""

import os, json, time, hashlib, csv, io
import requests as _requests
from datetime import datetime

APIFY_TOKEN = os.getenv('APIFY_API_TOKEN')
APIFY_BASE  = 'https://api.apify.com/v2'

# ══════════════════════════════════════════════════════════════
# FUENTE SII — Avalúo fiscal por comuna (Chile)
# CSV público actualizado semestralmente por el SII
# Captura casas grandes que el precio de arriendo subestima
# ══════════════════════════════════════════════════════════════

SII_CSV_URLS = {
    'RM':  'https://www.sii.cl/sobre_el_sii/data/No_Agricolas/Reg_Metropolitana.csv',
    'V':   'https://www.sii.cl/sobre_el_sii/data/No_Agricolas/Reg_Valparaiso.csv',
    'VIII':'https://www.sii.cl/sobre_el_sii/data/No_Agricolas/Reg_Bio_Bio.csv',
    'IX':  'https://www.sii.cl/sobre_el_sii/data/No_Agricolas/Reg_Araucania.csv',
    'X':   'https://www.sii.cl/sobre_el_sii/data/No_Agricolas/Reg_Los_Lagos.csv',
    'II':  'https://www.sii.cl/sobre_el_sii/data/No_Agricolas/Reg_Antofagasta.csv',
    'NAC': 'https://www.sii.cl/sobre_el_sii/data/No_Agricolas/Resumen_NAC_No_Agricolas.csv',
}


def fetch_sii_avaluo_by_commune(region: str = 'RM') -> dict:
    """
    Descarga el CSV del SII y devuelve {comuna: avaluo_promedio_M$}
    Variable: avalúo total / número de predios = valor promedio por propiedad
    Captura casas grandes (Lo Barnechea) que el precio de arriendo ignora.
    """
    url = SII_CSV_URLS.get(region, SII_CSV_URLS['RM'])
    try:
        resp = _requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        if resp.status_code != 200:
            print(f'[SII] Error {resp.status_code} para región {region}')
            return {}
        content = resp.content.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content), delimiter=';')
        result = {}
        for row in reader:
            try:
                comuna = row['NOMBRE COMUNA'].strip().title()
                if 'Total' in comuna or 'Region' in comuna.lower():
                    continue
                predios = int(row['PREDIOS TOTALES'].replace('.', '').replace(',', ''))
                avaluo  = int(row['AVALÚO TOTAL (3)'].replace('.', '').replace(',', ''))
                if predios > 0:
                    result[comuna] = round(avaluo / predios / 1_000, 2)  # en miles de pesos (M$)
            except Exception:
                continue
        print(f'[SII] {region}: {len(result)} comunas descargadas')
        return result
    except Exception as e:
        print(f'[SII] Error: {e}')
        return {}


def combine_indices(price_m2_index: float, sii_index: float,
                    weight_price: float = 0.6, weight_sii: float = 0.4) -> float:
    """
    Combina arriendo m² (variable principal) con avalúo SII (corrección patrimonial).

    Lógica:
    - Arriendo m² es la variable correcta: el banco presta hasta 25% del valor
      de la vivienda, el dueño fija el arriendo para cubrir el dividendo, el
      dividendo refleja el precio de compra, que refleja el ingreso del comprador.
      O sea: arriendo m² = ingreso del consumidor, no un proxy sino la variable real.
    - SII corrige barrios patrimoniales (Ñuñoa, Lo Barnechea) donde hay casas
      antiguas grandes que no se arriendan y el arriendo subestima el nivel real.
    - Para el resto del mundo: solo arriendo (weight_sii=0), captura todo.

    Ponderación Chile: 60% arriendo + 40% SII
    Ponderación global: 100% arriendo
    """
    if price_m2_index <= 0 and sii_index <= 0:
        return 100.0
    if price_m2_index <= 0:
        return sii_index
    if sii_index <= 0:
        return price_m2_index
    return round(price_m2_index * weight_price + sii_index * weight_sii, 1)

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
    """
    Escala extendida de 6 niveles.
    Mediana global = 100 (índice base).
    """
    if income_index >= 195: return 'AAA'  # Vitacura, Lo Barnechea
    if income_index >= 155: return 'AAB'  # Las Condes, La Reina
    if income_index >= 115: return 'ABB'  # Providencia, Ñuñoa
    if income_index >= 80:  return 'BBB'  # La Florida, San Miguel
    if income_index >= 55:  return 'BBC'  # Maipú, Santiago, Recoleta
    return 'BCC'                           # La Pintana, El Bosque, Cerro Navia


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
    Tabla global de 300+ comunas para los 10 idiomas de Preferendum.
    Índice 100 = mediana global (equivalente a Santiago RM).
    Fuente: INE/SII Chile, Zillow US, Land Registry UK, estimaciones portales
    inmobiliarios por país — actualizado semestralmente con run_full_agent().
    """
    def _r(country, commune, idx):
        cpm = round(max(1.5, min(20.0, 6.0 * (idx / 100.0) ** 0.65)), 2)
        if idx >= 195: tier = 'AAA'
        elif idx >= 155: tier = 'AAB'
        elif idx >= 115: tier = 'ABB'
        elif idx >= 80:  tier = 'BBB'
        elif idx >= 55:  tier = 'BBC'
        else:            tier = 'BCC'
        return {'country': country, 'commune': commune,
                'income_index': idx, 'cpm_usd': cpm, 'se_tier': tier}

    return [
        # ── CHILE (es) ─────────────────────────────────────────────────────────
        # Fuente: INE Censo + SII avalúo fiscal + Portal Inmobiliario
        _r('CL','Lo Barnechea',         259),
        _r('CL','La Reina',             206),
        _r('CL','Vitacura',             201),
        _r('CL','Las Condes',           156),
        _r('CL','Providencia',          127),
        _r('CL','Peñalolén',             99),
        _r('CL','Ñuñoa',                 99),
        _r('CL','La Florida',            97),
        _r('CL','Maipú',                 96),
        _r('CL','Santiago',              93),
        _r('CL','Macul',                 91),
        _r('CL','Quilicura',             88),
        _r('CL','Recoleta',              88),
        _r('CL','Huechuraba',            86),
        _r('CL','San Miguel',            85),
        _r('CL','Independencia',         82),
        _r('CL','Estación Central',      80),
        _r('CL','Pudahuel',              78),
        _r('CL','Puente Alto',           76),
        _r('CL','San Bernardo',          74),
        _r('CL','Cerrillos',             75),
        _r('CL','Conchalí',              72),
        _r('CL','Lo Prado',              70),
        _r('CL','Renca',                 68),
        _r('CL','Quinta Normal',         66),
        _r('CL','Pedro Aguirre Cerda',   62),
        _r('CL','El Bosque',             59),
        _r('CL','Lo Espejo',             58),
        _r('CL','San Ramón',             56),
        _r('CL','La Pintana',            51),
        _r('CL','Cerro Navia',           51),
        _r('CL','Viña del Mar',         110),
        _r('CL','Concón',               118),
        _r('CL','Valparaíso',            72),
        _r('CL','Concepción',            82),
        _r('CL','San Pedro de la Paz',   90),
        _r('CL','Antofagasta',           85),
        _r('CL','La Serena',             88),
        _r('CL','Temuco',                80),
        _r('CL','Puerto Montt',          76),
        _r('CL','Rancagua',              78),
        _r('CL','Iquique',               82),
        _r('CL','Arica',                 72),

        # ── ESPAÑA (es) ────────────────────────────────────────────────────────
        # Fuente: Idealista precio m² por distrito
        _r('ES','Salamanca (Madrid)',    210),
        _r('ES','Retiro (Madrid)',       195),
        _r('ES','Chamberí (Madrid)',     185),
        _r('ES','Moncloa (Madrid)',      175),
        _r('ES','Ciudad Lineal (Madrid)',118),
        _r('ES','Carabanchel (Madrid)',   82),
        _r('ES','Vallecas (Madrid)',      72),
        _r('ES','Villaverde (Madrid)',    58),
        _r('ES','Sarrià (Barcelona)',    210),
        _r('ES','Eixample (Barcelona)',  175),
        _r('ES','Gràcia (Barcelona)',    160),
        _r('ES','Sant Martí (Barcelona)',130),
        _r('ES','Nou Barris (Barcelona)', 68),
        _r('ES','Eixample (Valencia)',   130),
        _r('ES','Benimaclet (Valencia)',  92),
        _r('ES','Nervión (Sevilla)',     115),
        _r('ES','Triana (Sevilla)',       98),
        _r('ES','Abando (Bilbao)',       155),
        _r('ES','Gros (San Sebastián)', 165),
        _r('ES','Centro (Málaga)',       120),
        _r('ES','El Palo (Málaga)',       82),

        # ── MÉXICO (es) ────────────────────────────────────────────────────────
        # Fuente: Inmuebles24 / SHF índice SHF de precios
        _r('MX','Bosques de las Lomas',  185),
        _r('MX','Polanco',               162),
        _r('MX','Santa Fe',              155),
        _r('MX','Lomas de Chapultepec',  175),
        _r('MX','Condesa',               138),
        _r('MX','Roma Norte',            125),
        _r('MX','Coyoacán',              108),
        _r('MX','Del Valle',             100),
        _r('MX','Benito Juárez',          95),
        _r('MX','Iztapalapa',             48),
        _r('MX','Ecatepec',               38),
        _r('MX','Tepito',                 42),
        _r('MX','San Pedro Garza García', 190),
        _r('MX','San Nicolás de los Garza',98),
        _r('MX','Zapopan',               122),
        _r('MX','Tlaquepaque',            78),
        _r('MX','Zona Hotelera Cancún',  145),
        _r('MX','Centro Histórico Oaxaca',72),

        # ── ARGENTINA (es) ─────────────────────────────────────────────────────
        # Fuente: ZonaProp / INDEC
        _r('AR','Puerto Madero',         175),
        _r('AR','Recoleta',              145),
        _r('AR','Palermo',               132),
        _r('AR','Belgrano',              120),
        _r('AR','Núñez',                 112),
        _r('AR','Caballito',              95),
        _r('AR','Villa Crespo',           88),
        _r('AR','Flores',                 75),
        _r('AR','La Matanza',             52),
        _r('AR','Villa Soldati',          42),
        _r('AR','Nueva Córdoba',          92),
        _r('AR','Palermo (Córdoba)',       80),
        _r('AR','Puerto Norte (Rosario)', 88),
        _r('AR','Luján de Cuyo (Mendoza)',82),

        # ── COLOMBIA (es) ──────────────────────────────────────────────────────
        # Fuente: Metrocuadrado / DANE
        _r('CO','El Poblado (Medellín)',  118),
        _r('CO','Laureles (Medellín)',     95),
        _r('CO','Belén (Medellín)',        75),
        _r('CO','Castilla (Medellín)',     52),
        _r('CO','Usaquén (Bogotá)',       122),
        _r('CO','Chapinero (Bogotá)',     112),
        _r('CO','Teusaquillo (Bogotá)',    98),
        _r('CO','Kennedy (Bogotá)',        58),
        _r('CO','Bosa (Bogotá)',           45),
        _r('CO','El Prado (Barranquilla)', 82),
        _r('CO','Ciudad Jardín (Cali)',    88),

        # ── PERÚ (es) ──────────────────────────────────────────────────────────
        # Fuente: Urbania / BCRP
        _r('PE','San Isidro (Lima)',      142),
        _r('PE','Miraflores (Lima)',      128),
        _r('PE','La Molina (Lima)',       118),
        _r('PE','Surco (Lima)',           108),
        _r('PE','Lince (Lima)',            88),
        _r('PE','San Juan de Lurigancho',  42),
        _r('PE','Villa María del Triunfo', 38),
        _r('PE','Cayma (Arequipa)',        78),
        _r('PE','Centro (Cusco)',          72),

        # ── OTROS HISPANOS (es) ────────────────────────────────────────────────
        _r('EC','González Suárez (Quito)', 92),
        _r('EC','Chillogallo (Quito)',      45),
        _r('EC','Urdesa (Guayaquil)',       82),
        _r('UY','Punta Carretas (Mdeo)',   122),
        _r('UY','Pocitos (Montevideo)',    112),
        _r('UY','Peñarol (Montevideo)',     52),
        _r('DO','Piantini (Sto. Domingo)', 105),
        _r('DO','Los Alcarrizos',           42),
        _r('VE','Las Mercedes (Caracas)',   88),
        _r('VE','Petare (Caracas)',         28),
        _r('BO','Calacoto (La Paz)',        88),
        _r('PY','Villa Morra (Asunción)',   92),

        # ── USA (en) ───────────────────────────────────────────────────────────
        # Fuente: Zillow Rent Index / ACS Census
        _r('US','Beverly Hills',          520),
        _r('US','Palo Alto',              490),
        _r('US','Manhattan (Upper East)', 480),
        _r('US','San Francisco (Pacific Heights)', 460),
        _r('US','Boston (Back Bay)',       420),
        _r('US','Seattle (Queen Anne)',    390),
        _r('US','Washington DC (Georgetown)', 380),
        _r('US','Miami (Coral Gables)',    355),
        _r('US','Los Angeles (Santa Monica)', 400),
        _r('US','Austin (West Austin)',    285),
        _r('US','Denver (Cherry Creek)',   270),
        _r('US','Brooklyn (Williamsburg)', 235),
        _r('US','Chicago Loop',            195),
        _r('US','Philadelphia (Center City)', 205),
        _r('US','Manhattan (Harlem)',       180),
        _r('US','Los Angeles (Compton)',     78),
        _r('US','Detroit (Downtown)',        92),
        _r('US','Baltimore (Sandtown)',      58),
        _r('US','South Side Chicago',        68),
        _r('US','The Bronx',                 75),

        # ── UK (en) ────────────────────────────────────────────────────────────
        # Fuente: HM Land Registry House Price Index
        _r('GB','Kensington and Chelsea',  480),
        _r('GB','City of Westminster',     450),
        _r('GB','Mayfair',                 510),
        _r('GB','Camden',                  235),
        _r('GB','Hackney',                 175),
        _r('GB','City of London',          185),
        _r('GB','Southwark',               162),
        _r('GB','Lambeth',                 155),
        _r('GB','Tower Hamlets',           148),
        _r('GB','Newham',                  112),
        _r('GB','Barking and Dagenham',     95),
        _r('GB','Northern Quarter (Mcr)',   108),
        _r('GB','Moss Side (Manchester)',    52),
        _r('GB','Edgbaston (Birmingham)',   115),
        _r('GB','Handsworth (Birmingham)',   58),
        _r('GB','New Town (Edinburgh)',     162),
        _r('GB','Wester Hailes (Edinb.)',    62),
        _r('GB','Merchant City (Glasgow)',  105),
        _r('GB','Drumchapel (Glasgow)',      48),

        # ── AUSTRALIA (en) ─────────────────────────────────────────────────────
        # Fuente: CoreLogic / Domain
        _r('AU','Mosman (Sydney)',          365),
        _r('AU','Double Bay (Sydney)',      420),
        _r('AU','Manly (Sydney)',           310),
        _r('AU','Surry Hills (Sydney)',     245),
        _r('AU','Parramatta (Sydney)',      138),
        _r('AU','Bankstown (Sydney)',        92),
        _r('AU','Campbelltown (Sydney)',     72),
        _r('AU','Toorak (Melbourne)',        380),
        _r('AU','South Yarra (Melbourne)',   285),
        _r('AU','Footscray (Melbourne)',      88),
        _r('AU','Dandenong (Melbourne)',      72),
        _r('AU','New Farm (Brisbane)',       262),
        _r('AU','Logan (Brisbane)',           75),
        _r('AU','Cottesloe (Perth)',         295),
        _r('AU','Armadale (Perth)',           72),
        _r('AU','Norwood (Adelaide)',        185),
        _r('AU','Davoren Park (Adelaide)',    65),

        # ── CANADA (en) ────────────────────────────────────────────────────────
        # Fuente: CMHC / CREA
        _r('CA','Rosedale (Toronto)',        395),
        _r('CA','Forest Hill (Toronto)',     365),
        _r('CA','Downtown Toronto',         262),
        _r('CA','Scarborough (Toronto)',     135),
        _r('CA','West Vancouver',           440),
        _r('CA','Kerrisdale (Vancouver)',    330),
        _r('CA','Surrey (Vancouver)',        122),
        _r('CA','Westmount (Montreal)',      308),
        _r('CA','Plateau (Montreal)',        168),
        _r('CA','Saint-Michel (Montreal)',    78),
        _r('CA','Elbow Park (Calgary)',      290),
        _r('CA','Forest Lawn (Calgary)',      82),
        _r('CA','Glenora (Edmonton)',        228),
        _r('CA','Osborne Village (Winnipeg)',158),

        # ── INDIA (en) ─────────────────────────────────────────────────────────
        # Fuente: NHB Residex / MagicBricks
        _r('IN','Bandra West (Mumbai)',      195),
        _r('IN','Juhu (Mumbai)',             175),
        _r('IN','Dharavi (Mumbai)',           18),
        _r('IN','Connaught Place (Delhi)',   165),
        _r('IN','Lutyens Delhi',            250),
        _r('IN','New Delhi Centre',         122),
        _r('IN','Paharganj (Delhi)',          35),
        _r('IN','Koramangala (Bangalore)',   145),
        _r('IN','Whitefield (Bangalore)',    128),
        _r('IN','KR Puram (Bangalore)',       55),
        _r('IN','Alwarpet (Chennai)',        125),
        _r('IN','Royapuram (Chennai)',        42),
        _r('IN','Ballygunge (Kolkata)',      108),
        _r('IN','Maniktala (Kolkata)',        38),
        _r('IN','Banjara Hills (Hyderabad)', 138),
        _r('IN','Charminar (Hyderabad)',      35),

        # ── NIGERIA (en) ───────────────────────────────────────────────────────
        # Fuente: Propertypro.ng / EFInA
        _r('NG','Ikoyi (Lagos)',             210),
        _r('NG','Victoria Island (Lagos)',   182),
        _r('NG','Lekki Phase 1 (Lagos)',     148),
        _r('NG','Surulere (Lagos)',           78),
        _r('NG','Mushin (Lagos)',             35),
        _r('NG','Ajegunle (Lagos)',           15),
        _r('NG','Maitama (Abuja)',           168),
        _r('NG','Garki (Abuja)',             108),
        _r('NG','Karu (Abuja)',               42),
        _r('NG','GRA (Port Harcourt)',       118),
        _r('NG','Diobu (Port Harcourt)',      38),

        # ── SOUTH AFRICA (en) ──────────────────────────────────────────────────
        # Fuente: Lightstone / Propstats SA
        _r('ZA','Sandton (Joburg)',          168),
        _r('ZA','Soweto (Joburg)',            35),
        _r('ZA','Rosebank (Joburg)',         142),
        _r('ZA','Atlantic Seaboard (CPT)',   195),
        _r('ZA','Mitchell\'s Plain (CPT)',    28),
        _r('ZA','Umhlanga (Durban)',         148),
        _r('ZA','Umlazi (Durban)',            30),

        # ── ALEMANIA (de) ──────────────────────────────────────────────────────
        # Fuente: empirica-systeme / IVD
        _r('DE','Bogenhausen (München)',     295),
        _r('DE','Schwabing (München)',       265),
        _r('DE','Au-Haidhausen (München)',   235),
        _r('DE','Neuperlach (München)',      135),
        _r('DE','Zehlendorf (Berlin)',       232),
        _r('DE','Mitte (Berlin)',            188),
        _r('DE','Prenzlauer Berg (Berlin)',  178),
        _r('DE','Friedrichshain (Berlin)',   152),
        _r('DE','Marzahn (Berlin)',           85),
        _r('DE','Blankenese (Hamburg)',      252),
        _r('DE','Altona (Hamburg)',          158),
        _r('DE','Veddel (Hamburg)',           68),
        _r('DE','Westend (Frankfurt)',       232),
        _r('DE','Sachsenhausen (Frankfurt)', 175),
        _r('DE','Griesheim (Frankfurt)',      88),
        _r('DE','Lindenthal (Köln)',         190),
        _r('DE','Chorweiler (Köln)',          72),
        _r('DE','Oberkassel (Düsseldorf)',   218),
        _r('DE','Degerloch (Stuttgart)',     208),
        _r('DE','Nürnberg Südstadt',        135),
        _r('DE','Gohlis (Leipzig)',          105),

        # ── AUSTRIA (de) ───────────────────────────────────────────────────────
        # Fuente: IMMOunited / WKÖ
        _r('AT','Innere Stadt (Wien)',       252),
        _r('AT','Döbling (Wien)',            218),
        _r('AT','Hietzing (Wien)',           208),
        _r('AT','Mariahilf (Wien)',          165),
        _r('AT','Favoriten (Wien)',           92),
        _r('AT','Simmering (Wien)',           80),
        _r('AT','Altstadt (Salzburg)',       208),
        _r('AT','Geidorf (Graz)',            158),
        _r('AT','Innsbruck Pradl',          168),

        # ── SUIZA (de/fr/it) ───────────────────────────────────────────────────
        # Fuente: Swiss National Bank / Comparis
        _r('CH','Altstadt (Zürich)',         365),
        _r('CH','Seefeld (Zürich)',          340),
        _r('CH','Aussersihl (Zürich)',       188),
        _r('CH','Schwamendingen (Zürich)',   125),
        _r('CH','Champel (Genève)',          332),
        _r('CH','Les Grottes (Genève)',      188),
        _r('CH','Ouchy (Lausanne)',          262),
        _r('CH','Kirchenfeld (Bern)',        228),
        _r('CH','Gundeldingen (Basel)',      205),

        # ── JAPÓN (ja) ─────────────────────────────────────────────────────────
        # Fuente: MLIT Land Price Survey / SUUMO
        _r('JP','Minato-ku (Tokyo)',         332),
        _r('JP','Chiyoda-ku (Tokyo)',        318),
        _r('JP','Shibuya-ku (Tokyo)',        305),
        _r('JP','Meguro-ku (Tokyo)',         275),
        _r('JP','Setagaya-ku (Tokyo)',       248),
        _r('JP','Shinjuku-ku (Tokyo)',       228),
        _r('JP','Nerima-ku (Tokyo)',         158),
        _r('JP','Adachi-ku (Tokyo)',         122),
        _r('JP','Edogawa-ku (Tokyo)',        118),
        _r('JP','Nishiku (Osaka)',           182),
        _r('JP','Chuo-ku (Osaka)',           205),
        _r('JP','Higashinari-ku (Osaka)',     88),
        _r('JP','Sakyo-ku (Kyoto)',          208),
        _r('JP','Fushimi-ku (Kyoto)',        125),
        _r('JP','Chuo-ku (Fukuoka)',         165),
        _r('JP','Higashi-ku (Fukuoka)',       95),
        _r('JP','Chuo-ku (Sapporo)',         148),
        _r('JP','Shiroishi-ku (Sapporo)',     82),
        _r('JP','Nishi-ku (Yokohama)',       185),
        _r('JP','Tsurumi-ku (Yokohama)',     108),
        _r('JP','Naka-ku (Nagoya)',          178),

        # ── ARABIA SAUDITA (ar) ────────────────────────────────────────────────
        # Fuente: Saudi RERA / Bayut.sa
        _r('SA','Al-Malqa (Riyadh)',         272),
        _r('SA','Al Olaya (Riyadh)',         258),
        _r('SA','Al Salam (Riyadh)',         138),
        _r('SA','Al-Batha (Riyadh)',          78),
        _r('SA','Al Hamra (Jeddah)',         248),
        _r('SA','Al Rawdah (Jeddah)',        185),
        _r('SA','Al Aziziyah (Jeddah)',       88),
        _r('SA','Al-Shati (Jeddah)',         158),
        _r('SA','Dhahran',                   205),

        # ── EMIRATOS ÁRABES (ar) ───────────────────────────────────────────────
        # Fuente: REIDIN / Property Finder UAE
        _r('AE','Palm Jumeirah (Dubai)',     445),
        _r('AE','DIFC (Dubai)',              395),
        _r('AE','Downtown Dubai',            368),
        _r('AE','Jumeirah (Dubai)',           295),
        _r('AE','Deira (Dubai)',              122),
        _r('AE','Bur Dubai',                 100),
        _r('AE','Al Karama (Dubai)',          88),
        _r('AE','Al Khalidiyah (Abu Dhabi)', 208),
        _r('AE','Al Mushrif (Abu Dhabi)',    158),
        _r('AE','Mussafah (Abu Dhabi)',       78),

        # ── EGIPTO (ar) ────────────────────────────────────────────────────────
        # Fuente: Aqarmap / CAPMAS
        _r('EG','Zamalek (Cairo)',            88),
        _r('EG','Garden City (Cairo)',        82),
        _r('EG','Maadi (Cairo)',              78),
        _r('EG','Heliopolis (Cairo)',         68),
        _r('EG','Mohandessin (Cairo)',        72),
        _r('EG','Imbaba (Cairo)',             35),
        _r('EG','Shubra (Cairo)',             30),
        _r('EG','Ain Shams (Cairo)',          25),
        _r('EG','Stanley (Alexandria)',       65),
        _r('EG','Smouha (Alexandria)',        60),
        _r('EG','Sidi Gaber (Alexandria)',    52),

        # ── MARRUECOS (ar/fr) ──────────────────────────────────────────────────
        # Fuente: Mubawab / HCP Maroc
        _r('MA','Ain Diab (Casablanca)',      85),
        _r('MA','Anfa (Casablanca)',          78),
        _r('MA','Maarif (Casablanca)',        68),
        _r('MA','Sidi Moumen (Casablanca)',   32),
        _r('MA','Hay Mohammadi (Casablanca)', 28),
        _r('MA','Souissi (Rabat)',            80),
        _r('MA','Agdal (Rabat)',              72),
        _r('MA','Yacoub el-Mansour (Rabat)',  45),
        _r('MA','Gueliz (Marrakech)',         70),
        _r('MA','Médina (Fès)',               38),

        # ── JORDANIA (ar) ──────────────────────────────────────────────────────
        _r('JO','Abdoun (Amman)',            145),
        _r('JO','Sweifiyeh (Amman)',         122),
        _r('JO','Nuzha (Amman)',              82),
        _r('JO','Zarqa',                      52),

        # ── KUWAIT / QATAR (ar) ────────────────────────────────────────────────
        _r('KW','Rumaithiya (Kuwait)',        208),
        _r('KW','Salmiya (Kuwait)',           165),
        _r('KW','Farwaniya (Kuwait)',          82),
        _r('QA','West Bay (Doha)',            352),
        _r('QA','The Pearl (Doha)',           395),
        _r('QA','Al Wakra (Doha)',             88),

        # ── BRASIL (pt) ────────────────────────────────────────────────────────
        # Fuente: FIPE ZAP / Secovi-SP
        _r('BR','Leblon (Rio de Janeiro)',   195),
        _r('BR','Ipanema (Rio de Janeiro)',  185),
        _r('BR','Barra da Tijuca (Rio)',     165),
        _r('BR','Copacabana (Rio)',          148),
        _r('BR','Complexo do Alemão (Rio)',   28),
        _r('BR','Rocinha (Rio)',              25),
        _r('BR','Jardins (São Paulo)',        185),
        _r('BR','Itaim Bibi (São Paulo)',     175),
        _r('BR','Moema (São Paulo)',          162),
        _r('BR','Vila Mariana (São Paulo)',   132),
        _r('BR','Capão Redondo (São Paulo)',   45),
        _r('BR','Heliopolis (São Paulo)',      32),
        _r('BR','Asa Sul (Brasília)',         145),
        _r('BR','Ceilândia (Brasília)',        52),
        _r('BR','Barra (Salvador)',           105),
        _r('BR','Liberdade (Salvador)',        38),
        _r('BR','Meireles (Fortaleza)',        92),
        _r('BR','Bom Jardim (Fortaleza)',      35),
        _r('BR','Boa Viagem (Recife)',        105),
        _r('BR','Ibura (Recife)',              35),
        _r('BR','Savassi (Belo Horizonte)',   115),
        _r('BR','Venda Nova (BH)',             48),
        _r('BR','Moinhos de Vento (Porto Alegre)', 122),
        _r('BR','Restinga (Porto Alegre)',     42),
        _r('BR','Batel (Curitiba)',           115),
        _r('BR','Adrianópolis (Manaus)',       78),

        # ── PORTUGAL (pt) ──────────────────────────────────────────────────────
        # Fuente: Confidencial Imobiliário / Idealista.pt
        _r('PT','Chiado (Lisboa)',            168),
        _r('PT','Parque das Nações (Lisboa)', 158),
        _r('PT','Cascais',                    175),
        _r('PT','Amadora (Lisboa)',            78),
        _r('PT','Setúbal',                     88),
        _r('PT','Foz do Douro (Porto)',       145),
        _r('PT','Campanhã (Porto)',            68),
        _r('PT','Braga Centro',                92),
        _r('PT','Quinta do Lago (Algarve)',   182),
        _r('PT','Funchal (Madeira)',           102),

        # ── FRANCIA (fr) ───────────────────────────────────────────────────────
        # Fuente: INSEE / MeilleursAgents
        _r('FR','16ème arrondissement (Paris)', 335),
        _r('FR','7ème arrondissement (Paris)',  308),
        _r('FR','8ème arrondissement (Paris)',  288),
        _r('FR','11ème arrondissement (Paris)', 185),
        _r('FR','18ème arrondissement (Paris)', 145),
        _r('FR','20ème arrondissement (Paris)', 122),
        _r('FR','Aubervilliers (Seine-Saint-Denis)', 72),
        _r('FR','Saint-Denis (Seine-Saint-Denis)',   68),
        _r('FR','Lyon 6ème',                   208),
        _r('FR','Lyon 4ème',                   175),
        _r('FR','Vénissieux (Lyon)',             78),
        _r('FR','7ème-8ème (Marseille)',        165),
        _r('FR','3ème (Marseille)',              68),
        _r('FR','Les Chartrons (Bordeaux)',     188),
        _r('FR','Lormont (Bordeaux)',            78),
        _r('FR','Côte Pavée (Toulouse)',        175),
        _r('FR','Cimiez (Nice)',                208),
        _r('FR','Vieux Lille',                  155),
        _r('FR','Orangerie (Strasbourg)',        165),

        # ── BÉLGICA (fr/de) ────────────────────────────────────────────────────
        # Fuente: Statbel / Immoweb
        _r('BE','Ixelles (Bruxelles)',          238),
        _r('BE','Woluwe-Saint-Pierre (BXL)',    258),
        _r('BE','Etterbeek (Bruxelles)',        195),
        _r('BE','Molenbeek (Bruxelles)',         78),
        _r('BE','Anderlecht (Bruxelles)',        82),
        _r('BE','Zurenborg (Antwerpen)',        185),
        _r('BE','Dam (Antwerpen)',               72),
        _r('BE','Patershol (Gent)',             165),

        # ── SENEGAL (fr) ───────────────────────────────────────────────────────
        # Fuente: Expat-Dakar / ANSD Sénégal
        _r('SN','Almadies (Dakar)',              72),
        _r('SN','Plateau (Dakar)',               65),
        _r('SN','Médina (Dakar)',                32),
        _r('SN','Grand-Yoff (Dakar)',            25),
        _r('SN','Pikine',                        18),

        # ── COSTA DE MARFIL (fr) ───────────────────────────────────────────────
        # Fuente: Portail immobilier CI / INS
        _r('CI','Cocody (Abidjan)',              78),
        _r('CI','Plateau (Abidjan)',             82),
        _r('CI','Marcory (Abidjan)',             52),
        _r('CI','Abobo (Abidjan)',               28),

        # ── CAMERÚN (fr) ───────────────────────────────────────────────────────
        _r('CM','Bastos (Yaoundé)',              68),
        _r('CM','Mvan (Yaoundé)',                30),
        _r('CM','Akwa (Douala)',                 62),
        _r('CM','Bonabéri (Douala)',             28),

        # ── INDONESIA (id) ─────────────────────────────────────────────────────
        # Fuente: Rumah123 / BPS Indonesia
        _r('ID','Menteng (Jakarta)',              92),
        _r('ID','Kemang (Jakarta Selatan)',       95),
        _r('ID','Kebayoran Baru (Jakarta)',       88),
        _r('ID','Tebet (Jakarta Selatan)',        70),
        _r('ID','Pluit (Jakarta Utara)',          72),
        _r('ID','Tanah Abang (Jakarta Pusat)',    58),
        _r('ID','Tambora (Jakarta Barat)',        38),
        _r('ID','Penjaringan (Jakarta Utara)',    42),
        _r('ID','Gubeng (Surabaya)',              68),
        _r('ID','Tambaksari (Surabaya)',          42),
        _r('ID','Coblong (Bandung)',              65),
        _r('ID','Andir (Bandung)',                40),
        _r('ID','Medan Baru (Medan)',             62),
        _r('ID','Medan Labuhan (Medan)',          32),
        _r('ID','Gondokusuman (Yogyakarta)',       58),
        _r('ID','Semarang Tengah',                60),
        _r('ID','Sanur (Denpasar)',               72),
        _r('ID','Pemogan (Denpasar)',              42),
        _r('ID','Panakkukang (Makassar)',          55),
        _r('ID','Adrianópolis (Manaus)',           52),

        # ── ITALIA (it) ────────────────────────────────────────────────────────
        # Fuente: Tecnocasa / Idealista.it
        _r('IT','Brera (Milano)',               292),
        _r('IT','Porta Venezia (Milano)',       228),
        _r('IT','Navigli (Milano)',             195),
        _r('IT','Corvetto (Milano)',             100),
        _r('IT','Quarto Oggiaro (Milano)',        68),
        _r('IT','Parioli (Roma)',               228),
        _r('IT','Prati (Roma)',                 185),
        _r('IT','Trastevere (Roma)',            168),
        _r('IT','Tor Bella Monaca (Roma)',        72),
        _r('IT','Primavalle (Roma)',              80),
        _r('IT','Oltrarno (Firenze)',            188),
        _r('IT','San Frediano (Firenze)',        158),
        _r('IT','Posillipo (Napoli)',            168),
        _r('IT','Secondigliano (Napoli)',         42),
        _r('IT','Crocetta (Torino)',             165),
        _r('IT','Barriera di Milano (Torino)',    68),
        _r('IT','Navile (Bologna)',              152),
        _r('IT','Carignano (Genova)',            122),
        _r('IT','Libertà (Palermo)',              88),
        _r('IT','Borgo (Catania)',                80),

        # ── CHINA (zh) ─────────────────────────────────────────────────────────
        # Fuente: CRIC / National Bureau of Statistics CN
        _r('CN','Jing\'an District (Shanghai)',  178),
        _r('CN','Lujiazui-Pudong (Shanghai)',    195),
        _r('CN','Xuhui District (Shanghai)',     165),
        _r('CN','Putuo District (Shanghai)',     112),
        _r('CN','Baoshan District (Shanghai)',    80),
        _r('CN','Xicheng District (Beijing)',    208),
        _r('CN','Chaoyang District (Beijing)',   185),
        _r('CN','Haidian District (Beijing)',    172),
        _r('CN','Tongzhou District (Beijing)',    88),
        _r('CN','Daxing District (Beijing)',      80),
        _r('CN','Futian District (Shenzhen)',    198),
        _r('CN','Nanshan District (Shenzhen)',   178),
        _r('CN','Longhua District (Shenzhen)',   102),
        _r('CN','Tianhe District (Guangzhou)',   162),
        _r('CN','Yuexiu District (Guangzhou)',   142),
        _r('CN','Haizhu District (Guangzhou)',   130),
        _r('CN','Baiyun District (Guangzhou)',    98),
        _r('CN','Jinjiang District (Chengdu)',   130),
        _r('CN','Wuhou District (Chengdu)',      120),
        _r('CN','Yuzhong District (Chongqing)',  122),
        _r('CN','Gulou District (Nanjing)',      142),
        _r('CN','Hongshan District (Wuhan)',     112),
        _r('CN','Tianxin District (Changsha)',   100),
        _r('CN','Yanta District (Xi\'an)',       100),

        # ── TAIWAN (zh) ────────────────────────────────────────────────────────
        # Fuente: 內政部實價登錄 / 信義房屋
        _r('TW','Xinyi District (Taipei)',      258),
        _r('TW','Da\'an District (Taipei)',     228),
        _r('TW','Zhongzheng District (Taipei)', 188),
        _r('TW','Wanhua District (Taipei)',     102),
        _r('TW','Neihu District (Taipei)',      148),
        _r('TW','Xindian (New Taipei)',         142),
        _r('TW','Zhubei (Hsinchu)',             165),
        _r('TW','East District (Taichung)',     142),
        _r('TW','East District (Tainan)',       100),
        _r('TW','Zuoying (Kaohsiung)',          100),

        # ── HONG KONG (zh) ─────────────────────────────────────────────────────
        # Fuente: HKSAR Rating and Valuation Dept
        _r('HK','Central and Western',         510),
        _r('HK','Wan Chai',                    420),
        _r('HK','Eastern (Tai Koo)',           308),
        _r('HK','Kowloon City',                228),
        _r('HK','Kwun Tong',                   165),
        _r('HK','Tsuen Wan',                   148),
        _r('HK','Sham Shui Po',                122),
        _r('HK','Yuen Long',                   100),
        _r('HK','Tuen Mun',                     90),
    ]


def run_sii_chile() -> list:
    """
    Descarga y combina datos SII para todas las regiones de Chile.
    Se puede correr sin Apify — fuente oficial gratuita.
    Devuelve lista de comunas con índice basado solo en avalúo SII.
    """
    all_communes = []
    for region, url in SII_CSV_URLS.items():
        if region == 'NAC':
            continue
        avaluos = fetch_sii_avaluo_by_commune(region)
        for commune, avaluo_m in avaluos.items():
            all_communes.append({
                'country': 'CL', 'commune': commune,
                'price_m2_avg': 0.0,
                'sii_avaluo_M': avaluo_m,
                'income_index': 100.0,
                'cpm_usd': 6.0, 'se_tier': 'BBB',
                'portal': 'SII-Chile',
            })

    # Normalizar: mediana SII = índice 100
    if not all_communes:
        return []
    avaluos = sorted([c['sii_avaluo_M'] for c in all_communes if c['sii_avaluo_M'] > 0])
    median_avaluo = avaluos[len(avaluos) // 2] if avaluos else 1.0
    for c in all_communes:
        sii_idx = round((c['sii_avaluo_M'] / median_avaluo) * 100, 1) if c['sii_avaluo_M'] > 0 else 100.0
        c['income_index'] = sii_idx
        c['cpm_usd']      = calculate_cpm_from_index(sii_idx)
        c['se_tier']      = get_se_tier(sii_idx)
    return all_communes


# ══════════════════════════════════════════════════════════════
# FUENTE HM LAND REGISTRY — UK House Price Index (Reino Unido)
# API gratuita y oficial del gobierno británico — sin Apify, sin
# scraping, sin selectores que se rompan. Mismo principio que el
# avalúo SII: el precio de vivienda de un borough es un proxy
# estable del poder adquisitivo del área (cambia lento — la
# posición relativa de un borough tarda años en moverse).
# ══════════════════════════════════════════════════════════════

UK_LAND_REGISTRY_BASE = 'https://landregistry.data.gov.uk/data/ukhpi/region'

UK_LONDON_BOROUGHS = {
    'kensington-and-chelsea': 'Kensington and Chelsea',
    'camden':                 'Camden',
    'city-of-london':         'City of London',
    'hackney':                'Hackney',
    'southwark':              'Southwark',
    'lambeth':                'Lambeth',
    'tower-hamlets':          'Tower Hamlets',
    'newham':                 'Newham',
    'barking-and-dagenham':   'Barking and Dagenham',
}


def run_uk_land_registry() -> list:
    """
    Descarga el UK House Price Index oficial (HM Land Registry, gov.uk)
    para los boroughs de Londres y construye el índice relativo —
    misma fórmula que SII Chile: mediana = índice 100.
    Fuente pública gratuita, no requiere token, no depende de Apify.
    """
    all_communes = []
    for slug, display_name in UK_LONDON_BOROUGHS.items():
        try:
            list_resp = _requests.get(f'{UK_LAND_REGISTRY_BASE}/{slug}.json',
                                       headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            if list_resp.status_code != 200:
                continue
            items = list_resp.json().get('result', {}).get('items', [])
            if not items:
                continue
            latest_month_url = items[0]  # la API los lista del más reciente al más antiguo
            data_resp = _requests.get(f'{latest_month_url}.json',
                                       headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            if data_resp.status_code != 200:
                continue
            topic = data_resp.json().get('result', {}).get('primaryTopic', {})
            avg_price = topic.get('averagePrice')
            if not avg_price:
                continue
            all_communes.append({
                'country': 'GB', 'commune': display_name,
                'price_m2_avg': 0.0,
                'avg_house_price_gbp': avg_price,
                'income_index': 100.0,
                'cpm_usd': 6.0, 'se_tier': 'BBB',
                'portal': 'HM-Land-Registry',
            })
        except Exception as e:
            print(f'[UK-LandRegistry] Error con {slug}: {e}')
            continue

    if not all_communes:
        return []
    prices = sorted([c['avg_house_price_gbp'] for c in all_communes if c['avg_house_price_gbp'] > 0])
    median_price = prices[len(prices) // 2] if prices else 1.0
    for c in all_communes:
        idx = round((c['avg_house_price_gbp'] / median_price) * 100, 1)
        c['income_index'] = idx
        c['cpm_usd']      = calculate_cpm_from_index(idx)
        c['se_tier']      = get_se_tier(idx)
    return all_communes


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
