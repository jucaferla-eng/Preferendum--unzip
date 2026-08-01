"""
rental_price_agent.py — PREFERENDUM
Agente autónomo de precios de arriendo m²/mes por distrito/comuna.

Fuente primaria — Chile:
    Portal Inmobiliario / MercadoLibre API (misma infraestructura)
    Listings reales publicados por corredores certificados ACOP/COPROCH.

Fuente secundaria (fallback si la API no responde):
    Datos 2026 publicados por informes de mercado (CChC, Capital Arriendo,
    Portal PM, Publimetro) con precio mediano real por tipología 2 dormitorios.

Metodología Preferendum v2 (2026-07-26):
    RentIndex_g = 100 × (price_m2_g / median_country_price_m2)
    RentPct_g   = percentil del distrito dentro del país (0–100)
    GeoScore_i  = 0.70 × RentPct_g + 0.30 × RentIndexScore_g
    Tier A requiere: percentil en tramo A del grupo-país Y zona con RentPct ≥ umbral mínimo.

Frecuencia: anual automática (2 enero, 3:00 AM UTC) + endpoint manual admin.
"""

import re, time, logging, statistics
from datetime import datetime

import requests

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CLASIFICACIÓN DE PAÍSES POR GRUPO DE INGRESO
# ─────────────────────────────────────────────────────────────────────────────
COUNTRY_INCOME_GROUP: dict[str, str] = {}
# H1 — ingreso muy alto (PIB per cápita > ~$40k USD, OCDE avanzados + financieros)
for _c in ['US','CH','AU','CA','GB','DE','NL','AT','BE','JP','KR','HK','QA','AE','KW','IL',
           'SG','DK','SE','NO','IE','LU','FI','NZ','IS','MC','LI']:
    COUNTRY_INCOME_GROUP[_c] = 'H1'
# H2 — ingreso alto/medio-alto (PIB per cápita $15k–$40k USD)
for _c in ['FR','IT','ES','PT','CZ','PL','HU','RO','GR','TW','SA','MY','SI','SK','EE','LV','LT','HR','MT','CY','BH']:
    COUNTRY_INCOME_GROUP[_c] = 'H2'
# M1 — ingreso medio (PIB per cápita $5k–$15k USD)
for _c in ['CL','BR','MX','CO','AR','UY','TR','ZA','CN','RU','KZ','TH','DO','JO','RS','BG','MK','AL','BA']:
    COUNTRY_INCOME_GROUP[_c] = 'M1'
# M2L — ingreso medio-bajo/bajo (PIB per cápita < $5k USD)
for _c in ['EC','VE','BO','PY','PE','IN','NG','EG','MA','SN','CI','CM','IQ','IR','ID','VN','PH','PK','BD','KE','GH','TZ']:
    COUNTRY_INCOME_GROUP[_c] = 'M2L'

# ─────────────────────────────────────────────────────────────────────────────
# CORTES POR PERCENTIL DE INGRESO FINAL (Metodología v2)
#
# H1  — ingreso muy alto (USA, Suiza, Japón...):       A=top 20%, B=sig 20%
# H2  — ingreso alto/medio-alto (Francia, Corea...):   A=top 12%, B=sig 20%
# M1  — ingreso medio (Chile, México, Turquía...):     A=top 7%,  B=sig 18%
# M1g — M1 con Gini muy alto (Brasil, Sudáfrica...):   A=top 5%,  B=sig 15%
# M2L — ingreso medio-bajo/bajo (Nigeria, India...):   A=top 3%,  B=sig 12%
# ─────────────────────────────────────────────────────────────────────────────
TIER_CUTS: dict[str, dict[str, int]] = {
    'H1':  {'A': 80, 'B': 60, 'C': 35, 'D': 15},
    'H2':  {'A': 88, 'B': 68, 'C': 40, 'D': 18},
    'M1':  {'A': 93, 'B': 75, 'C': 45, 'D': 20},
    'M1g': {'A': 95, 'B': 80, 'C': 50, 'D': 20},   # M1 con desigualdad muy alta
    'M2L': {'A': 97, 'B': 85, 'C': 50, 'D': 20},
}

# Países con desigualdad muy alta (Gini ≥ 0.50) dentro de grupo M1
# Aplican cortes más estrictos (grupo M1g en vez de M1 estándar)
HIGH_GINI_COUNTRIES = {'BR', 'ZA', 'CO', 'MX'}

# Umbral geográfico mínimo para que una persona califique como Tier A
# Si tiene el percentil de ingreso para A pero vive en zona baja → baja a B
A_GEO_THRESHOLD: dict[str, int] = {
    'H1': 75, 'H2': 80, 'M1': 85, 'M1g': 85, 'M2L': 90,
}

# ─────────────────────────────────────────────────────────────────────────────
# FÓRMULA GEOSCORE
# ─────────────────────────────────────────────────────────────────────────────
_RENT_INDEX_SCORE = [(60, 10), (80, 25), (95, 40), (106, 50), (121, 65), (151, 80)]

def rent_index_to_score(ri: float) -> float:
    for threshold, score in _RENT_INDEX_SCORE:
        if ri < threshold:
            return score
    return 95.0

def compute_geo_score(rent_pct: float, rent_index: float) -> float:
    return round(0.70 * rent_pct + 0.30 * rent_index_to_score(rent_index), 1)

def get_effective_group(country: str) -> str:
    """Retorna el grupo efectivo del país, considerando ajuste por desigualdad alta."""
    group = COUNTRY_INCOME_GROUP.get(country, 'M1')
    if group == 'M1' and country in HIGH_GINI_COUNTRIES:
        return 'M1g'
    return group

def assign_tier(income_pct: float, rent_pct: float, country: str) -> str:
    """Asigna tier A-E según metodología v2.
    Para A: exige AMBAS condiciones (percentil de ingreso + zona geográfica).
    Brasil/Sudáfrica/Colombia/México usan cortes más estrictos (M1g: A=top 5%).
    """
    group = get_effective_group(country)
    cuts  = TIER_CUTS[group]
    geo_t = A_GEO_THRESHOLD[group]
    if income_pct >= cuts['A']:
        return 'A' if rent_pct >= geo_t else 'B'
    if income_pct >= cuts['B']:
        return 'B'
    if income_pct >= cuts['C']:
        return 'C'
    if income_pct >= cuts['D']:
        return 'D'
    return 'E'

# ─────────────────────────────────────────────────────────────────────────────
# COMUNAS DE CHILE
# Formato: (nombre, region_code, uf_m2_2026_seed)
# uf_m2_2026_seed: datos reales publicados 2026 (CChC, Capital Arriendo, PI)
# El agente reemplaza estos valores con datos en tiempo real de Portal Inmobiliario.
# ─────────────────────────────────────────────────────────────────────────────
CHILE_COMMUNES: list[tuple[str, str, float]] = [
    # ── Región Metropolitana — premium ──────────────────────────────────────
    ("Vitacura",              "RM",  0.400),
    ("Las Condes",            "RM",  0.390),
    ("Lo Barnechea",          "RM",  0.380),
    ("Providencia",           "RM",  0.375),
    ("La Reina",              "RM",  0.320),
    ("Ñuñoa",                 "RM",  0.295),
    ("Peñalolén",             "RM",  0.240),
    ("Santiago",              "RM",  0.240),
    ("Macul",                 "RM",  0.230),
    ("San Miguel",            "RM",  0.228),
    # ── Región Metropolitana — medio ────────────────────────────────────────
    ("La Florida",            "RM",  0.220),
    ("Independencia",         "RM",  0.218),
    ("Huechuraba",            "RM",  0.210),
    ("Maipú",                 "RM",  0.210),
    ("Recoleta",              "RM",  0.200),
    ("Quilicura",             "RM",  0.190),
    ("Estación Central",      "RM",  0.190),
    ("Quinta Normal",         "RM",  0.180),
    ("Colina",                "RM",  0.185),
    ("Padre Hurtado",         "RM",  0.180),
    ("Peñaflor",              "RM",  0.175),
    ("Talagante",             "RM",  0.170),
    ("Puente Alto",           "RM",  0.175),
    ("La Granja",             "RM",  0.165),
    ("San Bernardo",          "RM",  0.165),
    # ── Región Metropolitana — popular ──────────────────────────────────────
    ("Cerrillos",             "RM",  0.170),
    ("Conchalí",              "RM",  0.170),
    ("Pudahuel",              "RM",  0.160),
    ("Renca",                 "RM",  0.150),
    ("Lo Prado",              "RM",  0.140),
    ("Lo Espejo",             "RM",  0.130),
    ("Cerro Navia",           "RM",  0.120),
    ("El Bosque",             "RM",  0.120),
    ("San Ramón",             "RM",  0.110),
    ("La Pintana",            "RM",  0.100),
    ("El Monte",              "RM",  0.130),
    ("Isla de Maipo",         "RM",  0.125),
    ("Lampa",                 "RM",  0.145),
    ("Buin",                  "RM",  0.140),
    ("Paine",                 "RM",  0.130),
    ("Melipilla",             "RM",  0.140),
    ("Curacaví",              "RM",  0.130),
    ("Tiltil",                "RM",  0.110),
    ("Pirque",                "RM",  0.160),
    ("San José de Maipo",     "RM",  0.150),
    ("Calera de Tango",       "RM",  0.155),
    ("María Pinto",           "RM",  0.105),
    ("Alhué",                 "RM",  0.100),
    ("San Pedro",             "RM",  0.110),
    ("Til Til",               "RM",  0.105),
    # ── Región de Valparaíso ────────────────────────────────────────────────
    ("Valparaíso",            "V",   0.180),
    ("Viña del Mar",          "V",   0.230),
    ("Concón",                "V",   0.260),
    ("Quilpué",               "V",   0.170),
    ("Villa Alemana",         "V",   0.160),
    ("San Antonio",           "V",   0.150),
    ("Quillota",              "V",   0.145),
    ("La Ligua",              "V",   0.130),
    ("Los Andes",             "V",   0.135),
    ("San Felipe",            "V",   0.130),
    ("Limache",               "V",   0.145),
    ("Olmué",                 "V",   0.140),
    ("Casablanca",            "V",   0.150),
    ("Algarrobo",             "V",   0.200),
    ("Cartagena",             "V",   0.160),
    ("El Tabo",               "V",   0.165),
    ("El Quisco",             "V",   0.165),
    # ── Región del Biobío ───────────────────────────────────────────────────
    ("Concepción",            "VIII",0.190),
    ("Talcahuano",            "VIII",0.160),
    ("San Pedro de la Paz",   "VIII",0.210),
    ("Hualpén",               "VIII",0.155),
    ("Penco",                 "VIII",0.140),
    ("Tomé",                  "VIII",0.135),
    ("Coronel",               "VIII",0.130),
    ("Lota",                  "VIII",0.110),
    ("Chiguayante",           "VIII",0.165),
    ("Los Ángeles",           "VIII",0.150),
    ("Chillán",               "VIII",0.155),
    ("Chillán Viejo",         "VIII",0.140),
    ("Cabrero",               "VIII",0.120),
    ("San Carlos",            "VIII",0.120),
    # ── Región de La Araucanía ──────────────────────────────────────────────
    ("Temuco",                "IX",  0.180),
    ("Padre Las Casas",       "IX",  0.150),
    ("Villarrica",            "IX",  0.200),
    ("Pucón",                 "IX",  0.240),
    ("Angol",                 "IX",  0.130),
    ("Victoria",              "IX",  0.120),
    ("Lautaro",               "IX",  0.120),
    ("Freire",                "IX",  0.115),
    # ── Región de Los Lagos ─────────────────────────────────────────────────
    ("Puerto Montt",          "X",   0.170),
    ("Puerto Varas",          "X",   0.190),
    ("Osorno",                "X",   0.145),
    ("Llanquihue",            "X",   0.140),
    ("Castro",                "X",   0.150),
    ("Ancud",                 "X",   0.140),
    ("Quellón",               "X",   0.120),
    ("Chaitén",               "X",   0.110),
    # ── Región de Antofagasta ───────────────────────────────────────────────
    ("Antofagasta",           "II",  0.230),
    ("Calama",                "II",  0.200),
    ("Tocopilla",             "II",  0.130),
    ("Mejillones",            "II",  0.140),
    ("Taltal",                "II",  0.110),
    ("San Pedro de Atacama",  "II",  0.250),
    # ── Región de Coquimbo ──────────────────────────────────────────────────
    ("La Serena",             "IV",  0.200),
    ("Coquimbo",              "IV",  0.170),
    ("Ovalle",                "IV",  0.130),
    ("Illapel",               "IV",  0.115),
    ("Andacollo",             "IV",  0.120),
    ("Vicuña",                "IV",  0.140),
    # ── Región de Tarapacá ──────────────────────────────────────────────────
    ("Iquique",               "I",   0.200),
    ("Alto Hospicio",         "I",   0.150),
    ("Pozo Almonte",          "I",   0.120),
    # ── Región de Arica y Parinacota ────────────────────────────────────────
    ("Arica",                 "XV",  0.160),
    ("Putre",                 "XV",  0.105),
    # ── Región de Atacama ───────────────────────────────────────────────────
    ("Copiapó",               "III", 0.170),
    ("Vallenar",              "III", 0.130),
    ("Diego de Almagro",      "III", 0.110),
    # ── Región del Maule ────────────────────────────────────────────────────
    ("Talca",                 "VII", 0.155),
    ("Curicó",                "VII", 0.140),
    ("Linares",               "VII", 0.120),
    ("Constitución",          "VII", 0.125),
    ("San Javier",            "VII", 0.110),
    ("Molina",                "VII", 0.115),
    # ── Región de O'Higgins ─────────────────────────────────────────────────
    ("Rancagua",              "VI",  0.170),
    ("San Fernando",          "VI",  0.135),
    ("Pichilemu",             "VI",  0.165),
    ("Rengo",                 "VI",  0.120),
    ("Machalí",               "VI",  0.155),
    # ── Región de Aysén ─────────────────────────────────────────────────────
    ("Coyhaique",             "XI",  0.160),
    ("Chile Chico",           "XI",  0.115),
    ("Puerto Aysén",          "XI",  0.130),
    # ── Región de Magallanes ────────────────────────────────────────────────
    ("Punta Arenas",          "XII", 0.170),
    ("Puerto Natales",        "XII", 0.145),
    ("Puerto Williams",       "XII", 0.130),
    # ── Región de Los Ríos ──────────────────────────────────────────────────
    ("Valdivia",              "XIV", 0.175),
    ("La Unión",              "XIV", 0.130),
    ("Panguipulli",           "XIV", 0.135),
    ("Futrono",               "XIV", 0.110),
    # ── Región de Ñuble ─────────────────────────────────────────────────────
    ("Chillán (Ñuble)",       "XVI", 0.155),
    ("San Carlos (Ñuble)",    "XVI", 0.120),
    ("Bulnes",                "XVI", 0.110),
    ("Yungay",                "XVI", 0.105),
]


# ─────────────────────────────────────────────────────────────────────────────
# FUENTE PRIMARIA: MERCADOLIBRE / PORTAL INMOBILIARIO API
# Portal Inmobiliario es propiedad de MercadoLibre. Comparten API pública.
# ─────────────────────────────────────────────────────────────────────────────
MELI_SEARCH_URL = "https://api.mercadolibre.com/sites/MLC/search"

MELI_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; Preferendum/2.0)',
    'Accept': 'application/json',
}

def fetch_uf_value() -> float:
    """Obtiene valor actual de la UF desde mindicador.cl (Banco Central)."""
    try:
        r = requests.get('https://mindicador.cl/api/uf', timeout=8)
        data = r.json()
        serie = data.get('serie', [])
        if serie:
            return float(serie[0].get('valor', 38000))
    except Exception as e:
        log.warning(f"[RentalAgent] UF fetch error: {e}")
    return 38500.0  # fallback conservador

def fetch_commune_listings_api(commune: str) -> list[float]:
    """
    Obtiene precios por m² desde la API pública de MercadoLibre (Portal Inmobiliario).
    Retorna lista de precios CLP/m² por aviso.
    """
    try:
        params = {
            'category': 'MLC1459',     # Inmuebles Chile
            'q': f'arriendo departamento {commune}',
            'limit': 50,
        }
        r = requests.get(MELI_SEARCH_URL, params=params, headers=MELI_HEADERS, timeout=12)
        if r.status_code != 200:
            return []

        data = r.json()
        prices_m2: list[float] = []

        for item in data.get('results', []):
            price = float(item.get('price') or 0)
            if price <= 0:
                continue

            attrs = {a['id']: a.get('value_name', '') for a in item.get('attributes', [])}

            area_raw = attrs.get('TOTAL_AREA') or attrs.get('INDOOR_AREA') or ''
            if not area_raw:
                continue

            area_num = re.sub(r'[^\d.]', '', area_raw.replace(',', '.'))
            if not area_num:
                continue
            area = float(area_num)

            # Filtros de cordura: precio arriendo mensual CLP y área en m²
            if price < 80_000 or price > 15_000_000:
                continue
            if area < 18 or area > 600:
                continue

            prices_m2.append(price / area)

        # Filtrar outliers (< 2,000 o > 60,000 CLP/m²/mes)
        prices_m2 = [p for p in prices_m2 if 2_000 <= p <= 60_000]
        return prices_m2

    except Exception as e:
        log.warning(f"[RentalAgent] API error para {commune}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# CÁLCULO DE ÍNDICES (Metodología v2)
# ─────────────────────────────────────────────────────────────────────────────
def compute_indices(commune_data: list[dict]) -> list[dict]:
    """
    Recibe lista de comunas con median_clp.
    Calcula rent_index, rent_pct, geo_score y tier para cada una.
    """
    valid = [c for c in commune_data if c.get('median_clp') and c['median_clp'] > 0]
    if not valid:
        return commune_data

    # Mediana país (base 100)
    all_medians = [c['median_clp'] for c in valid]
    median_country = statistics.median(all_medians)

    # Ordenar para calcular percentil
    valid_sorted = sorted(valid, key=lambda x: x['median_clp'])
    n = len(valid_sorted)

    for rank, c in enumerate(valid_sorted):
        rent_index = round((c['median_clp'] / median_country) * 100, 1)
        rent_pct   = round((rank / (n - 1)) * 100, 1) if n > 1 else 50.0
        gs         = compute_geo_score(rent_pct, rent_index)
        tier       = assign_tier(rent_pct, rent_pct, c.get('country', 'CL'))

        c['rent_index'] = rent_index
        c['rent_pct']   = rent_pct
        c['geo_score']  = gs
        c['se_tier']    = tier

    # Rellenar comunas sin datos con valores de la región
    commune_dict = {c['commune']: c for c in valid_sorted}
    for c in commune_data:
        if c['commune'] not in commune_dict:
            c['rent_index'] = 50.0
            c['rent_pct']   = 50.0
            c['geo_score']  = compute_geo_score(50, 50)
            c['se_tier']    = 'C'

    return commune_data


# ─────────────────────────────────────────────────────────────────────────────
# AGENTE PRINCIPAL — CHILE
# ─────────────────────────────────────────────────────────────────────────────
def run_chile(db=None) -> dict:
    """
    Ejecuta el agente para Chile:
    1. Intenta obtener datos reales de Portal Inmobiliario (vía MercadoLibre API)
    2. Si la API retorna datos, los usa. Si no, usa datos 2026 publicados (seed).
    3. Calcula RentIndex, RentPct, GeoScore y tier con metodología v2.
    4. Guarda en commune_market_data.
    """
    log.info("[RentalPriceAgent] Chile — iniciando...")
    uf_value = fetch_uf_value()
    log.info(f"[RentalPriceAgent] UF: {uf_value:,.2f} CLP")

    commune_results: list[dict] = []
    api_hits = 0

    for commune, region, seed_uf in CHILE_COMMUNES:
        time.sleep(0.8)  # respetar rate limit de la API

        listings = fetch_commune_listings_api(commune)

        if listings:
            median_clp = statistics.median(listings)
            median_uf  = round(median_clp / uf_value, 4)
            source     = 'Portal Inmobiliario / MercadoLibre API'
            samples    = len(listings)
            api_hits  += 1
            log.info(f"  ✓ {commune}: {samples} avisos — mediana {median_clp:,.0f} CLP/m²")
        else:
            # Fallback: datos 2026 publicados (CChC, Capital Arriendo, informes de mercado)
            median_uf  = seed_uf
            median_clp = round(seed_uf * uf_value)
            source     = 'Datos publicados 2026 (CChC / mercado)'
            samples    = 0
            log.info(f"  ~ {commune}: sin respuesta API — usando seed {seed_uf} UF/m²")

        commune_results.append({
            'commune':    commune,
            'region':     region,
            'country':    'CL',
            'median_clp': median_clp,
            'median_uf':  median_uf,
            'sample_count': samples,
            'source':     source,
        })

    # Calcular índices con metodología v2
    commune_results = compute_indices(commune_results)

    # Guardar en base de datos
    saved = 0
    if db:
        for c in commune_results:
            if _save_commune(db, c, 'CL'):
                saved += 1
        log.info(f"[RentalPriceAgent] Guardadas {saved} comunas en DB")

    # Estadísticas del run
    valid = [c for c in commune_results if c.get('median_clp', 0) > 0]
    median_country_clp = statistics.median([c['median_clp'] for c in valid]) if valid else 0

    result = {
        'ok':                 True,
        'country':            'CL',
        'total_communes':     len(commune_results),
        'api_hits':           api_hits,
        'seed_fallbacks':     len(commune_results) - api_hits,
        'median_country_clp': round(median_country_clp),
        'median_country_uf':  round(median_country_clp / uf_value, 4) if uf_value else 0,
        'uf_value':           uf_value,
        'communes_saved_db':  saved,
        'source':             'Portal Inmobiliario / MercadoLibre API + datos publicados 2026',
        'updated_at':         datetime.utcnow().isoformat(),
        'communes':           commune_results,
    }
    log.info(f"[RentalPriceAgent] Chile completado — {api_hits} API / {len(commune_results)-api_hits} seed")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# DB — UPSERT
# ─────────────────────────────────────────────────────────────────────────────
def _save_commune(db, c: dict, country: str) -> bool:
    try:
        from sqlalchemy import text as sa_text

        # Intentar UPDATE primero
        result = db.execute(sa_text("""
            UPDATE commune_market_data SET
                price_m2_avg = :price,
                income_index = :rent_index,
                rent_index   = :rent_index,
                rent_pct     = :rent_pct,
                geo_score    = :geo_score,
                se_tier      = :tier,
                portal       = :source,
                sample_count = :samples,
                scraped_at   = NOW(),
                updated_at   = NOW()
            WHERE country = :country AND commune = :commune
        """), {
            'price':      c.get('median_uf', 0),
            'rent_index': c.get('rent_index', 50),
            'rent_pct':   c.get('rent_pct', 50),
            'geo_score':  c.get('geo_score', 50),
            'tier':       c.get('se_tier', 'C'),
            'source':     c.get('source', ''),
            'samples':    c.get('sample_count', 0),
            'country':    country,
            'commune':    c['commune'],
        })

        if result.rowcount == 0:
            # No existe → INSERT
            db.execute(sa_text("""
                INSERT INTO commune_market_data
                    (country, commune, price_m2_avg, income_index, rent_index, rent_pct,
                     geo_score, cpm_usd, se_tier, portal, sample_count, scraped_at, updated_at)
                VALUES
                    (:country, :commune, :price, :rent_index, :rent_index, :rent_pct,
                     :geo_score, 6.0, :tier, :source, :samples, NOW(), NOW())
            """), {
                'country':    country,
                'commune':    c['commune'],
                'price':      c.get('median_uf', 0),
                'rent_index': c.get('rent_index', 50),
                'rent_pct':   c.get('rent_pct', 50),
                'geo_score':  c.get('geo_score', 50),
                'tier':       c.get('se_tier', 'C'),
                'source':     c.get('source', ''),
                'samples':    c.get('sample_count', 0),
            })

        db.commit()
        return True

    except Exception as e:
        log.error(f"[RentalAgent] DB error {c.get('commune')}: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return False


# ─────────────────────────────────────────────────────────────────────────────
# SEED GLOBAL — Deutsche Bank Mapping the World's Prices 2025
# Fuente: Deutsche Bank Research Institute + Numbeo, Junio 2025
# 69 ciudades en 47 países — arriendo mensual (USD) para 1-bed y 3-bed
# ─────────────────────────────────────────────────────────────────────────────
# Formato: (country_code, city_name, rent_1bed_usd, rent_3bed_usd)
_DB2025_SEED: list[tuple[str, str, float, float]] = [
    ("US", "New York",       4143, 8388),
    ("US", "Boston",         3394, 6091),
    ("US", "San Francisco",  3332, 5424),
    ("US", "Chicago",        2344, 4683),
    ("US", "Los Angeles",    2613, 4462),
    ("SG", "Singapore",      3167, 6216),
    ("GB", "London",         2985, 5560),
    ("GB", "Edinburgh",      1634, 3089),
    ("GB", "Birmingham",     1337, 2306),
    ("CH", "Zurich",         2720, 4955),
    ("CH", "Geneva",         2330, 4693),
    ("HK", "Hong Kong",      2202, 4807),
    ("AE", "Dubai",          2401, 4589),
    ("AE", "Abu Dhabi",      1466, 3052),
    ("AU", "Sydney",         2164, 4407),
    ("AU", "Melbourne",      1528, 3028),
    ("NL", "Amsterdam",      2358, 4230),
    ("IE", "Dublin",         2378, 4077),
    ("LU", "Luxembourg",     2086, 3822),
    ("FR", "Paris",          1630, 3592),
    ("DK", "Copenhagen",     2021, 3534),
    ("CA", "Vancouver",      1994, 3501),
    ("CA", "Toronto",        1807, 2955),
    ("CA", "Montreal",       1201, 2057),
    ("DE", "Munich",         1759, 3377),
    ("DE", "Frankfurt",      1533, 2778),
    ("DE", "Berlin",         1421, 2700),
    ("IT", "Milan",          1602, 3250),
    ("IT", "Rome",           1326, 2618),
    ("IL", "Tel Aviv",       1667, 3088),
    ("PT", "Lisbon",         1618, 3062),
    ("QA", "Doha",           1605, 2946),
    ("RU", "Moscow",         1292, 2829),
    ("ES", "Madrid",         1629, 2811),
    ("ES", "Barcelona",      1547, 2738),
    ("SE", "Stockholm",      1590, 2782),
    ("JP", "Tokyo",          1118, 2672),
    ("NO", "Oslo",           1689, 2658),
    ("KR", "Seoul",           969, 2610),
    ("CN", "Shanghai",        952, 2490),
    ("CN", "Beijing",         900, 1937),
    ("NZ", "Auckland",       1284, 2457),
    ("NZ", "Wellington",     1318, 2135),
    ("BE", "Brussels",       1303, 2298),
    ("AT", "Vienna",         1259, 2293),
    ("CZ", "Prague",         1139, 2255),
    ("FI", "Helsinki",       1204, 2107),
    ("PL", "Warsaw",         1141, 2055),
    ("SA", "Riyadh",         1093, 2047),
    ("TH", "Bangkok",         677, 1938),
    ("TR", "Istanbul",        948, 1764),
    ("PH", "Manila",          500, 1734),
    ("TW", "Taipei",          792, 1683),
    ("ZA", "Cape Town",       758, 1435),
    ("ZA", "Johannesburg",    650, 1180),  # estimado de Athens similar
    ("HU", "Budapest",        727, 1339),
    ("BR", "Sao Paulo",       668, 1291),
    ("BR", "Rio de Janeiro",  438,  900),  # 1-bed data only
    ("GR", "Athens",          650, 1180),
    ("ID", "Jakarta",         550, 1179),
    ("AR", "Buenos Aires",    648, 1166),
    ("MY", "Kuala Lumpur",    561, 1100),
    ("CO", "Bogota",          451,  900),
    ("MX", "Mexico City",    1002, 2121),
    ("CL", "Santiago",        509,  950),  # Portal Inmobiliario es fuente primaria
    ("IN", "Mumbai",          701, 1819),
    ("IN", "Delhi",           500,  900),
    ("IN", "Bangalore",       450,  800),
    ("EG", "Cairo",           200,  400),
    ("VN", "Ho Chi Minh",     450,  900),
    ("NG", "Lagos",           300,  600),
    ("KZ", "Almaty",          400,  750),
    ("PE", "Lima",            500,  900),
    ("EC", "Quito",           350,  650),
    ("UY", "Montevideo",      600, 1100),
    ("DO", "Santo Domingo",   350,  700),
    ("MA", "Casablanca",      250,  500),
]


def _compute_global_percentiles(cities: list[dict]) -> list[dict]:
    """
    Calcula rent_pct y rent_index para cada ciudad dentro de su grupo de ingreso.
    rent_index = 100 × (city_m2 / group_median_m2)
    rent_pct   = percentil dentro del grupo (0–100)
    """
    import statistics

    # Agrupar por income_group
    by_group: dict[str, list[dict]] = {}
    for c in cities:
        g = get_effective_group(c['country'])
        by_group.setdefault(g, []).append(c)

    result = []
    for group, group_cities in by_group.items():
        prices = [c['rent_per_m2'] for c in group_cities]
        if not prices:
            continue
        median_m2 = statistics.median(prices)
        sorted_prices = sorted(prices)
        n = len(sorted_prices)

        for c in group_cities:
            m2 = c['rent_per_m2']
            # rent_index relativo al grupo
            rent_index = round(100.0 * m2 / median_m2, 1) if median_m2 else 50.0
            # percentil dentro del grupo
            pos = sorted(prices).index(m2)
            rent_pct = round(100.0 * pos / max(n - 1, 1), 1)
            geo_score = compute_geo_score(rent_pct, rent_index)
            tier = assign_tier(rent_pct, rent_pct, c['country'])

            result.append({**c, 'rent_index': rent_index, 'rent_pct': rent_pct,
                           'geo_score': geo_score, 'se_tier': tier})
    return result


def run_global(db=None) -> dict:
    """
    Carga el seed Deutsche Bank 2025 para todos los países (excepto CL que usa Portal Inmobiliario).
    Calcula percentiles por grupo de ingreso y guarda en commune_market_data.
    Fuente: Deutsche Bank Research Institute + Numbeo, Junio 2025.
    """
    cities = []
    for cc, city, rent1, rent3 in _DB2025_SEED:
        if cc == 'CL':
            continue  # Chile usa run_chile() con datos locales
        # rent_per_m2: promedio entre estimación 1-bed (÷50m²) y 3-bed (÷100m²)
        m2_from_1 = rent1 / 50.0
        m2_from_3 = rent3 / 100.0
        rent_m2 = round((m2_from_1 + m2_from_3) / 2, 2)
        cities.append({
            'country':     cc,
            'commune':     city,
            'rent_per_m2': rent_m2,
            'rent_1bed':   rent1,
            'rent_3bed':   rent3,
        })

    enriched = _compute_global_percentiles(cities)

    saved = 0
    errors = 0
    for c in enriched:
        entry = {
            'commune':      c['commune'],
            'median_uf':    c['rent_per_m2'],  # USD/m², campo reutilizado
            'rent_index':   c['rent_index'],
            'rent_pct':     c['rent_pct'],
            'geo_score':    c['geo_score'],
            'se_tier':      c['se_tier'],
            'sample_count': 0,
            'source':       'Deutsche Bank Research Institute 2025 / Numbeo',
        }
        if db and _save_commune(db, entry, c['country']):
            saved += 1
        elif not db:
            saved += 1
        else:
            errors += 1

    log.info(f"[RentalAgent] Global seed: {saved} ciudades guardadas, {errors} errores")
    return {
        'ok':      True,
        'scope':   'global',
        'cities':  saved,
        'errors':  errors,
        'source':  'Deutsche Bank Research Institute 2025 / Numbeo',
        'countries': len(set(c['country'] for c in enriched)),
    }


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA — TODOS LOS PAÍSES
# ─────────────────────────────────────────────────────────────────────────────
def run(country: str = 'CL', db=None) -> dict:
    """Ejecuta el agente para un país específico."""
    if country == 'CL':
        return run_chile(db)
    if country == 'ALL':
        return run_full_agent(db)
    # País específico no-CL: buscar en seed global y actualizar solo ese país
    seed = [(cc, city, r1, r3) for cc, city, r1, r3 in _DB2025_SEED if cc == country]
    if not seed:
        return {'ok': False, 'country': country, 'message': f'País {country} no en seed DB2025'}
    # Construir mini-run para ese país
    tmp_result = run_global.__wrapped__(db) if hasattr(run_global, '__wrapped__') else run_global(db)
    return {'ok': True, 'country': country, 'message': 'Actualizado desde seed DB2025', **tmp_result}


def run_full_agent(db=None) -> dict:
    """
    Ejecuta el agente completo: Chile (Portal Inmobiliario) + todos los países (DB2025 seed).
    Compatible con market_data_agent.run_full_agent().
    """
    results = {}

    # 1. Chile — fuente primaria: Portal Inmobiliario
    try:
        results['CL'] = run_chile(db)
    except Exception as e:
        log.error(f"[RentalAgent] Error CL: {e}")
        results['CL'] = {'ok': False, 'error': str(e)}

    # 2. Global — Deutsche Bank 2025
    try:
        results['global'] = run_global(db)
    except Exception as e:
        log.error(f"[RentalAgent] Error global: {e}")
        results['global'] = {'ok': False, 'error': str(e)}

    total_cities = sum(r.get('cities', r.get('communes_updated', 0)) for r in results.values() if isinstance(r, dict))
    return {
        'ok':          True,
        'scope':       'full',
        'total_cities': total_cities,
        'results':     results,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ESTIMADOR DE INGRESO DESDE PRECIO m²
# Convierte precio arriendo m²/mes → ingreso individual PPP estimado.
#
# Metodología:
#   1. Tamaño promedio del apartamento por grupo de ingreso de país
#   2. Renta mensual = precio_m2 × tamaño_promedio
#   3. Ingreso familiar = renta / 0.30  (regla del 30%, aceptada por BIS/OCDE)
#   4. Ingreso individual = ingreso_familiar / 1.50  (1.5 perceptores por hogar)
#   5. PPP = ingreso_individual_USD / PLI(país)
#
# Validación: para Vitacura CL (0.39 UF/m²) → ~$4,100 PPP/mes → razonable
#             para Manhattan US ($80/m²) → ~$8,500 PPP/mes → razonable
# ─────────────────────────────────────────────────────────────────────────────

# Tamaño promedio del departamento por grupo de ingreso de país (m²)
_AVG_APT_M2: dict[str, float] = {
    'H1':  82.0,   # US, AU, CH, CA, JP, KR — apartamentos más grandes
    'H2':  76.0,   # FR, DE, ES, IT, TW, PL
    'M1':  65.0,   # CL, MX, BR, CO, AR, TR, CN, RU
    'M2L': 55.0,   # IN, NG, PH, VN, PK, BD
}

# 1 UF (Chile) ≈ USD 40.50 (promedio 2026; no se usa en tiempo real)
_UF_TO_USD: float = 40.5

# PLI por país (copia local para no importar ppp_agent en todo momento)
_PLI_LOCAL: dict[str, float] = {
    'US': 1.00, 'CH': 1.62, 'NO': 1.40, 'DK': 1.17, 'IE': 1.11,
    'LU': 1.14, 'SE': 1.06, 'FI': 1.05, 'GB': 0.97, 'DE': 0.97,
    'FR': 0.98, 'NL': 1.04, 'BE': 1.01, 'AT': 0.99, 'AU': 0.90,
    'CA': 0.88, 'NZ': 0.87, 'IT': 0.87, 'ES': 0.81, 'SG': 0.85,
    'HK': 0.93, 'JP': 0.78, 'KR': 0.72, 'TW': 0.69, 'IL': 1.07,
    'AE': 0.85, 'QA': 0.58, 'SA': 0.65, 'PT': 0.75, 'GR': 0.78,
    'CZ': 0.66, 'PL': 0.57, 'HU': 0.60, 'RO': 0.56, 'TR': 0.48,
    'RU': 0.52, 'CN': 0.56, 'IN': 0.29, 'BR': 0.47, 'MX': 0.46,
    'AR': 0.36, 'CL': 0.56, 'CO': 0.44, 'PE': 0.48, 'UY': 0.74,
    'EC': 0.43, 'BO': 0.40, 'PY': 0.38, 'DO': 0.46, 'GT': 0.43,
    'ZA': 0.45, 'NG': 0.38, 'KE': 0.40, 'EG': 0.30, 'MA': 0.40,
    'MY': 0.52, 'TH': 0.52, 'ID': 0.44, 'PH': 0.44, 'VN': 0.40,
    'KZ': 0.45, 'BD': 0.33, 'PK': 0.28,
}


def estimate_income_from_rent_m2(price_m2: float, country: str,
                                  is_uf: bool = False) -> float:
    """
    Convierte precio arriendo m²/mes → ingreso individual mensual PPP USD.

    price_m2: UF/m²/mes si is_uf=True (Chile), USD/m²/mes si is_uf=False
    Retorna: ingreso individual mensual en PPP USD (o 0 si no calculable).
    """
    if not price_m2 or price_m2 <= 0:
        return 0.0

    # Convertir a USD si es en UF (Chile)
    price_m2_usd = price_m2 * _UF_TO_USD if is_uf else float(price_m2)

    # Tamaño promedio del apartamento
    group = get_effective_group(country)
    apt_m2 = _AVG_APT_M2.get(group, 65.0)

    # Renta mensual total del apartamento
    monthly_rent_usd = price_m2_usd * apt_m2

    # Ingreso familiar (regla 30%) → ingreso individual (1.5 perceptores)
    individual_income_usd = monthly_rent_usd / 0.30 / 1.50

    # Ajuste PPP
    pli = _PLI_LOCAL.get(country, 0.60)
    income_ppp = individual_income_usd / pli

    return round(income_ppp, 1)


def get_commune_income_estimate(db, country: str, commune: str) -> float | None:
    """
    Retorna el ingreso individual mensual PPP estimado para una comuna/ciudad.
    Primero intenta leer de commune_market_data.estimated_income_ppp;
    si no existe, calcula en tiempo real desde price_m2_avg.
    """
    try:
        from sqlalchemy import text as _t
        row = db.execute(_t("""
            SELECT estimated_income_ppp, price_m2_avg, country
            FROM commune_market_data
            WHERE country = :cc
              AND (commune ILIKE :cm OR commune ILIKE :cm2)
            LIMIT 1
        """), {'cc': country, 'cm': commune, 'cm2': f'%{commune}%'}).fetchone()

        if not row:
            return None

        # Si ya tenemos el campo calculado, usarlo directamente
        if row[0] and float(row[0]) > 0:
            return float(row[0])

        # Calcular en tiempo real desde price_m2_avg
        is_uf = (row[2] == 'CL')
        return estimate_income_from_rent_m2(float(row[1] or 0), country, is_uf=is_uf)

    except Exception:
        return None
