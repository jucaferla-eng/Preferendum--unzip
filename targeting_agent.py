"""
targeting_agent.py
==================
PREFERENDUM — Agente de Targeting Publicitario

Construye y mantiene la matriz de targeting:
  País → GNI per cápita (World Bank, actualización anual)
  País → Comuna → Precio m² → Tier de ingreso → CPM

Matching automático debate → campañas activas:
  Cuando un debate se crea o activa, el agente calcula el score
  de afinidad con cada campaña activa y ordena los ads.

Ciclos de actualización:
  - GNI por país: 1 vez por año (World Bank API)
  - Precios m² por comuna: 1 vez por mes (tablas curadas)
  - Matching debate→campaña: en tiempo real

En memoria del Socio Fundador José Ignacio Fernández (1989–2024)
"""

import os, json, requests, math
from datetime import datetime, timedelta
from typing import Optional

# ── Archivo de caché para la matriz ──────────────────────────
MATRIX_FILE = 'targeting_matrix.json'

# ══════════════════════════════════════════════════════════════
# TIER DE INGRESO POR GNI
# ══════════════════════════════════════════════════════════════

def gni_to_tier(gni: float) -> str:
    if gni >= 40000: return 'premium'
    if gni >= 15000: return 'mid'
    if gni >= 5000:  return 'growth'
    return 'volume'

def tier_to_cpm_base(tier: str) -> float:
    return {'premium': 12.0, 'mid': 6.0, 'growth': 3.0, 'volume': 1.5}.get(tier, 4.0)

# ══════════════════════════════════════════════════════════════
# PRECIOS M² POR PAÍS Y COMUNA
# Fuente: portales inmobiliarios locales, actualización mensual
# Índice 100 = Vitacura CL (~$3.500 USD/m²)
# ══════════════════════════════════════════════════════════════

COMMUNE_DATA = {
    "CL": [
        # (nombre, región, m2_index, población)
        ("Vitacura",         "RM", 100, 92000),
        ("Las Condes",       "RM",  96, 310000),
        ("Lo Barnechea",     "RM",  90, 105000),
        ("Providencia",      "RM",  85, 150000),
        ("La Reina",         "RM",  80,  98000),
        ("Ñuñoa",            "RM",  72, 225000),
        ("Peñalolén",        "RM",  68, 240000),
        ("Macul",            "RM",  62, 130000),
        ("San Miguel",       "RM",  60, 110000),
        ("La Florida",       "RM",  58, 380000),
        ("Santiago",         "RM",  52, 520000),
        ("Maipú",            "RM",  50, 620000),
        ("Quilicura",        "RM",  48, 235000),
        ("Recoleta",         "RM",  44, 175000),
        ("Renca",            "RM",  40, 155000),
        ("El Bosque",        "RM",  36, 185000),
        ("La Pintana",       "RM",  30, 225000),
        ("Cerro Navia",      "RM",  28, 145000),
        ("Viña del Mar",     "V",   72, 390000),
        ("Concón",           "V",   85,  52000),
        ("Valparaíso",       "V",   45, 310000),
        ("Concepción",       "VIII",55, 230000),
        ("Temuco",           "IX",  48, 280000),
        ("Antofagasta",      "II",  60, 420000),
    ],
    "AR": [
        ("Palermo",          "CABA", 95, 230000),
        ("Belgrano",         "CABA", 92, 180000),
        ("Recoleta",         "CABA", 90, 190000),
        ("Núñez",            "CABA", 85, 120000),
        ("Caballito",        "CABA", 72, 250000),
        ("Villa del Parque", "CABA", 65, 160000),
        ("San Telmo",        "CABA", 60, 100000),
        ("Flores",           "CABA", 50, 300000),
        ("La Boca",          "CABA", 35, 120000),
        ("Nordelta",         "GBA",  88,  80000),
        ("Pilar",            "GBA",  65, 280000),
        ("Tigre",            "GBA",  58, 370000),
        ("Rosario Centro",   "SF",   68, 400000),
        ("Córdoba Nueva",    "CB",   65, 380000),
    ],
    "PE": [
        ("Miraflores",       "LIM", 92, 120000),
        ("San Isidro",       "LIM", 98, 90000),
        ("Barranco",         "LIM", 85, 45000),
        ("San Borja",        "LIM", 82, 115000),
        ("La Molina",        "LIM", 80, 180000),
        ("Surco",            "LIM", 75, 380000),
        ("San Miguel",       "LIM", 58, 160000),
        ("Lince",            "LIM", 52, 80000),
        ("Comas",            "LIM", 30, 620000),
        ("Villa El Salvador","LIM", 22, 480000),
        ("Arequipa Centro",  "ARE", 55, 280000),
        ("Cusco",            "CUS", 48, 130000),
    ],
    "MX": [
        ("Polanco",          "CDMX", 98, 120000),
        ("Santa Fe",         "CDMX", 92,  80000),
        ("Lomas Chapultepec","CDMX", 95,  60000),
        ("Condesa",          "CDMX", 85, 110000),
        ("Roma Norte",       "CDMX", 82, 150000),
        ("Coyoacán",         "CDMX", 68, 280000),
        ("Tlalpan",          "CDMX", 50, 720000),
        ("Iztapalapa",       "CDMX", 28, 2000000),
        ("Monterrey Centro", "NLE",  70, 380000),
        ("San Pedro Garza",  "NLE",  90, 150000),
        ("Zapopan",          "JAL",  72, 560000),
        ("Puerto Vallarta",  "JAL",  75, 180000),
    ],
    "CO": [
        ("El Poblado",       "ANT",  92, 120000),
        ("Laureles",         "ANT",  75, 180000),
        ("Envigado",         "ANT",  80, 230000),
        ("Chía",             "CUN",  72,  80000),
        ("Rosales",          "BOG",  90,  80000),
        ("Chapinero",        "BOG",  78, 150000),
        ("Suba",             "BOG",  50, 1200000),
        ("Bosa",             "BOG",  28, 800000),
        ("Barranquilla Norte","ATL",  65, 200000),
    ],
    "BR": [
        ("Jardins",          "SP",   98, 120000),
        ("Itaim Bibi",       "SP",   92, 180000),
        ("Moema",            "SP",   85, 130000),
        ("Pinheiros",        "SP",   80, 160000),
        ("Leblon",           "RJ",   98,  60000),
        ("Ipanema",          "RJ",   95,  80000),
        ("Barra da Tijuca",  "RJ",   80, 250000),
        ("Lapa",             "RJ",   50, 120000),
        ("Meireles",         "CE",   78, 120000),
        ("Batel",            "PR",   82, 180000),
        ("Savassi",          "MG",   75, 140000),
    ],
    "ES": [
        ("Salamanca",        "MAD",  95, 150000),
        ("Chamberí",         "MAD",  90, 170000),
        ("Retiro",           "MAD",  88, 130000),
        ("Carabanchel",      "MAD",  45, 280000),
        ("Eixample",         "BCN",  92, 280000),
        ("Sarrià",           "BCN",  88, 130000),
        ("Gràcia",           "BCN",  78, 120000),
        ("Nou Barris",       "BCN",  35, 180000),
    ],
    "US": [
        ("Manhattan",        "NY",   98, 1600000),
        ("Brooklyn Heights", "NY",   88, 280000),
        ("Beverly Hills",    "CA",   98,  35000),
        ("Santa Monica",     "CA",   90, 92000),
        ("Palo Alto",        "CA",   95,  68000),
        ("Miami Beach",      "FL",   88,  90000),
        ("Coral Gables",     "FL",   85,  50000),
        ("Highland Park",    "TX",   92,  48000),
        ("River Oaks",       "TX",   95,  28000),
        ("Lincoln Park",     "IL",   85, 170000),
    ],
    "DE": [
        ("Mitte",            "BER",  82, 380000),
        ("Prenzlauer Berg",  "BER",  78, 160000),
        ("Schwabing",        "MUN",  92, 110000),
        ("Maxvorstadt",      "MUN",  88,  90000),
        ("Sachsenhausen",    "FRA",  80, 120000),
        ("HafenCity",        "HAM",  90,  80000),
        ("Winterhude",       "HAM",  82, 100000),
    ],
    "GB": [
        ("Kensington",       "LON",  98,  80000),
        ("Chelsea",          "LON",  96,  65000),
        ("Shoreditch",       "LON",  82, 180000),
        ("Hackney",          "LON",  62, 280000),
        ("Clifton",          "BRS",  78,  40000),
        ("Didsbury",         "MCR",  72,  60000),
    ],
    "FR": [
        ("16ème",            "PAR",  98, 170000),
        ("7ème",             "PAR",  95, 60000),
        ("Marais",           "PAR",  85, 30000),
        ("Belleville",       "PAR",  48, 80000),
        ("Uccle",            "LYO",  72, 80000),
    ],
    "IT": [
        ("Parioli",          "ROM",  92, 80000),
        ("Trastevere",       "ROM",  78, 60000),
        ("Brera",            "MIL",  95, 80000),
        ("Navigli",          "MIL",  75, 120000),
        ("Chiaia",           "NAP",  80, 90000),
    ],
}


# ══════════════════════════════════════════════════════════════
# ACTUALIZACIÓN GNI — WORLD BANK API
# ══════════════════════════════════════════════════════════════

def fetch_gni_from_worldbank(country_iso: str) -> Optional[float]:
    """Fetches latest GNI PPP per capita from World Bank API."""
    try:
        url = f"https://api.worldbank.org/v2/country/{country_iso}/indicator/NY.GNP.PCAP.PP.CD?format=json&mrv=1"
        r = requests.get(url, timeout=10)
        data = r.json()
        if len(data) > 1 and data[1]:
            for entry in data[1]:
                if entry.get('value'):
                    return float(entry['value'])
    except Exception as e:
        print(f"[TargetingAgent] World Bank API error for {country_iso}: {e}")
    return None

def update_gni_data(matrix: dict) -> dict:
    """Updates GNI per capita from World Bank for all countries in matrix."""
    print("[TargetingAgent] Updating GNI per capita from World Bank...")
    updated = 0
    for iso in matrix:
        gni = fetch_gni_from_worldbank(iso)
        if gni:
            old = matrix[iso].get('gni_per_capita', 0)
            matrix[iso]['gni_per_capita'] = gni
            matrix[iso]['gni_tier'] = gni_to_tier(gni)
            matrix[iso]['cpm_base'] = tier_to_cpm_base(gni_to_tier(gni))
            matrix[iso]['gni_updated_at'] = datetime.utcnow().isoformat()
            print(f"  {iso}: ${old:,.0f} → ${gni:,.0f} [{matrix[iso]['gni_tier']}]")
            updated += 1
    print(f"[TargetingAgent] GNI updated for {updated} countries")
    return matrix


# ══════════════════════════════════════════════════════════════
# CÁLCULO DE CPM POR COMUNA
# CPM = CPM_base_país × (income_index / 100)^0.6
# ══════════════════════════════════════════════════════════════

def calc_commune_cpm(gni_tier: str, income_index: int) -> float:
    base = tier_to_cpm_base(gni_tier)
    multiplier = (income_index / 100) ** 0.6
    return round(base * multiplier, 2)

def income_index_to_tier(index: int) -> str:
    if index >= 85: return 'A'
    if index >= 65: return 'B'
    if index >= 45: return 'C'
    return 'D'


# ══════════════════════════════════════════════════════════════
# CONSTRUCCIÓN DE LA MATRIZ
# ══════════════════════════════════════════════════════════════

def build_matrix() -> dict:
    """
    Builds the full targeting matrix for all countries.
    Structure:
      matrix[iso] = {
        gni_per_capita, gni_tier, cpm_base,
        communes: {name: {income_index, income_tier, cpm, population, region}}
      }
    """
    from marketer_table_v2 import GNI_PER_CAPITA

    matrix = {}
    for iso, communes in COMMUNE_DATA.items():
        gni = GNI_PER_CAPITA.get(iso, GNI_PER_CAPITA['default'])
        tier = gni_to_tier(gni)
        cpm_base = tier_to_cpm_base(tier)

        commune_dict = {}
        for entry in communes:
            name, region, income_index, population = entry
            income_tier = income_index_to_tier(income_index)
            cpm = calc_commune_cpm(tier, income_index)
            commune_dict[name] = {
                'region':       region,
                'income_index': income_index,
                'income_tier':  income_tier,
                'cpm':          cpm,
                'population':   population,
            }

        matrix[iso] = {
            'gni_per_capita':   gni,
            'gni_tier':         tier,
            'cpm_base':         cpm_base,
            'communes':         commune_dict,
            'communes_updated': datetime.utcnow().isoformat(),
            'gni_updated_at':   datetime.utcnow().isoformat(),
        }

    return matrix


def load_matrix() -> dict:
    """Loads matrix from cache file, builds if missing."""
    if os.path.exists(MATRIX_FILE):
        try:
            with open(MATRIX_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    matrix = build_matrix()
    save_matrix(matrix)
    return matrix


def save_matrix(matrix: dict):
    with open(MATRIX_FILE, 'w') as f:
        json.dump(matrix, f, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# SCHEDULED UPDATES
# ══════════════════════════════════════════════════════════════

def run_annual_gni_update():
    """Run once per year — updates GNI from World Bank API."""
    print("[TargetingAgent] === ANNUAL GNI UPDATE ===")
    matrix = load_matrix()
    matrix = update_gni_data(matrix)
    save_matrix(matrix)
    print("[TargetingAgent] Annual GNI update complete.")
    return matrix

def run_monthly_commune_update():
    """
    Run once per month — rebuilds commune tables.
    In future: scrape real estate portals per country.
    Currently: uses curated static tables (updated here manually each month).
    """
    print("[TargetingAgent] === MONTHLY COMMUNE UPDATE ===")
    matrix = build_matrix()
    # Preserve GNI data already updated from World Bank
    existing = load_matrix()
    for iso in matrix:
        if iso in existing and existing[iso].get('gni_updated_at'):
            matrix[iso]['gni_per_capita'] = existing[iso]['gni_per_capita']
            matrix[iso]['gni_tier']       = existing[iso]['gni_tier']
            matrix[iso]['cpm_base']       = existing[iso]['cpm_base']
            matrix[iso]['gni_updated_at'] = existing[iso]['gni_updated_at']
            # Recalculate CPMs with preserved GNI
            for name in matrix[iso]['communes']:
                idx = matrix[iso]['communes'][name]['income_index']
                matrix[iso]['communes'][name]['cpm'] = calc_commune_cpm(
                    matrix[iso]['gni_tier'], idx
                )
    save_matrix(matrix)
    print("[TargetingAgent] Monthly commune update complete.")
    return matrix


# ══════════════════════════════════════════════════════════════
# MOTOR DE OPTIMIZACIÓN — Minimiza costo por contacto
# ══════════════════════════════════════════════════════════════
#
# La COMUNA es la variable central del sistema:
#   - Determina el ingreso real del votante (via income_index)
#   - Fija el CPM del debate (cuánto cobra Preferendum)
#   - Define si la campaña aplica (gate por income_tier)
#   - Calcula la audiencia efectiva (población × precisión)
#
# Fórmula de costo por contacto (perspectiva del anunciante):
#   cost_per_contact = CPM / (precision × 1000)
#   donde precision = fracción de impresiones que llegan
#                     a contactos realmente calificados
#
# Fórmula de CPM efectivo (perspectiva de Preferendum):
#   effective_cpm = CPM × precision
#   (lo que realmente vale el espacio para el anunciante)
#
# El agente rankea por effective_cpm: maximiza ingresos de
# Preferendum Y minimiza costo por contacto del anunciante
# al mismo tiempo — ambos ganan con mejor targeting.
# ══════════════════════════════════════════════════════════════

TIER_ORDER = {'A': 4, 'B': 3, 'C': 2, 'D': 1}


def _get_se_tier(income_index: float) -> str:
    if income_index >= 80: return 'A'
    if income_index >= 55: return 'B'
    if income_index >= 35: return 'C'
    return 'D'


def _aggregate_communes(communes_map: dict, commune_names: list, default_tier: str, default_cpm: float) -> dict:
    """Combines several communes into one population-weighted profile, for
    debates targeted at more than one commune at once (scope_commune as a
    comma-separated list, same convention as AdCampaign.target_communes)."""
    rows = [communes_map[name] for name in commune_names if name in communes_map]
    if not rows:
        return {'income_tier': default_tier, 'income_index': 50, 'population': 50000, 'cpm': default_cpm}
    total_pop = sum(r.get('population', 50000) for r in rows) or 1
    weighted_index = sum(r.get('income_index', 50) * r.get('population', 50000) for r in rows) / total_pop
    weighted_cpm   = sum(r.get('cpm', default_cpm) * r.get('population', 50000) for r in rows) / total_pop
    return {
        'income_tier':  _get_se_tier(weighted_index),
        'income_index': round(weighted_index, 1),
        'population':   total_pop,
        'cpm':          round(weighted_cpm, 2),
    }


def _gender_precision(camp_gender: str, debate_gender: str) -> float:
    """Returns fraction of debate audience matching campaign gender target."""
    if camp_gender in ('all', '', None):
        return 1.0   # campaign accepts everyone
    if debate_gender in ('all', '', None):
        return 0.5   # debate open to all, ~half match a specific gender
    return 1.0 if camp_gender == debate_gender else 0.0


def _age_precision(camp_min: int, camp_max: int, debate_min: int, debate_max: int) -> float:
    """Returns fraction of debate age range that overlaps campaign age target."""
    overlap_lo = max(camp_min, debate_min)
    overlap_hi = min(camp_max, debate_max)
    if overlap_hi < overlap_lo:
        return 0.0
    debate_range = max(debate_max - debate_min, 1)
    return min((overlap_hi - overlap_lo) / debate_range, 1.0)


def _commune_precision(
    camp_communes: list,
    camp_min_tier: str,
    commune_tier: str,
    commune_income_index: int,
) -> float:
    """
    Returns precision score (0.0–1.0) for how well the commune matches
    the campaign's geographic/income targeting.

    Cases:
      1. Exact commune match              → 1.0  (best possible)
      2. No commune filter + tier met     → 0.85 (broad but relevant)
      3. Commune filter but different commune, tier met   → 0.5
      4. No commune filter, tier below target by 1 level → 0.3
      5. Commune in filter but below tier                → 0.0 (hard gate)
    """
    tier_val         = TIER_ORDER.get(commune_tier, 1)
    camp_tier_val    = TIER_ORDER.get(camp_min_tier or 'D', 1)
    tier_gap         = camp_tier_val - tier_val   # positive = commune below target

    # Hard gate: commune income tier is below campaign minimum
    if tier_gap > 1:
        return 0.0

    # Exact commune match
    if camp_communes and commune_income_index is not None:
        # Will be evaluated against the actual commune name outside this fn
        pass

    # Income index boost: within a tier, higher index = better match
    # Maps income_index 0-100 to a within-tier quality 0.0-1.0
    within_tier_quality = commune_income_index / 100.0 if commune_income_index else 0.5

    if tier_gap <= 0:
        # Commune meets or exceeds the required tier
        if not camp_communes:
            return 0.75 + 0.25 * within_tier_quality   # broad targeting, tier ok → 0.75–1.0
        else:
            return 0.40 + 0.10 * within_tier_quality   # commune filter exists but not exact → 0.40–0.50
    else:
        # tier_gap == 1: one level below target (e.g. campaign wants B, commune is C)
        return 0.20 + 0.10 * within_tier_quality        # partial relevance → 0.20–0.30


def score_and_optimize(campaign: dict, debate: dict, matrix: dict) -> Optional[dict]:
    """
    Core optimization function. Returns None if campaign is ineligible.
    Returns a dict with:
      affinity_score       — 0-100, how well campaign matches debate audience
      precision_rate       — 0.0-1.0, fraction of impressions to qualified contacts
      effective_audience   — estimated # of qualified people who see the ad
      cpm                  — what the advertiser pays per 1000 impressions
      effective_cpm        — Preferendum's real revenue per 1000 impressions
      cost_per_contact_usd — advertiser's cost per qualified contact
      optimization_rank    — sort key: higher = better (effective_cpm)
    """
    debate_country    = debate.get('scope_country', '')
    debate_commune    = debate.get('scope_commune', '')
    debate_gender     = debate.get('target_gender', 'all')
    debate_age_min    = int(debate.get('target_age_min') or 13)
    debate_age_max    = int(debate.get('target_age_max') or 99)
    debate_pop        = int(debate.get('estimated_audience') or 0)

    camp_country      = campaign.get('target_country', '')
    camp_communes_raw = campaign.get('target_communes') or ''
    camp_communes     = [c.strip() for c in camp_communes_raw.split(',') if c.strip()] if camp_communes_raw else []
    camp_gender       = campaign.get('target_gender', 'all')
    camp_age_min      = int(campaign.get('target_age_min') or 13)
    camp_age_max      = int(campaign.get('target_age_max') or 99)
    camp_min_tier     = campaign.get('min_income_tier') or 'D'
    camp_min_gni      = float(campaign.get('min_gni_country') or 0)

    # ── GATE 1: Country ──────────────────────────────────────────
    # Global debates accept any campaign; campaigns with no country target also match all
    if camp_country and camp_country not in ('ALL', 'GLOBAL'):
        if debate_country not in ('ALL', 'GLOBAL', '') and camp_country != debate_country:
            return None

    # ── GATE 2: GNI floor ───────────────────────────────────────
    country_data = matrix.get(debate_country, {})
    country_gni  = country_data.get('gni_per_capita', 10000)
    if camp_min_gni and country_gni < camp_min_gni:
        return None

    # ── COMMUNE DATA (central variable) ──────────────────────────
    # scope_commune may hold one commune or a comma-separated list (same
    # convention as AdCampaign.target_communes) — multiple communes are
    # combined into one population-weighted profile.
    communes_map    = country_data.get('communes', {})
    debate_communes = [c.strip() for c in debate_commune.split(',') if c.strip()] if debate_commune else []
    if len(debate_communes) <= 1:
        commune_data   = communes_map.get(debate_communes[0]) if debate_communes else None
        commune_tier   = commune_data.get('income_tier', 'C')      if commune_data else 'C'
        commune_index  = commune_data.get('income_index', 50)      if commune_data else 50
        commune_pop    = commune_data.get('population', 50000)     if commune_data else 50000
        commune_cpm    = commune_data.get('cpm', country_data.get('cpm_base', 4.0)) if commune_data else country_data.get('cpm_base', 4.0)
    else:
        agg = _aggregate_communes(communes_map, debate_communes, 'C', country_data.get('cpm_base', 4.0))
        commune_tier, commune_index, commune_pop, commune_cpm = (
            agg['income_tier'], agg['income_index'], agg['population'], agg['cpm']
        )

    # ── GATE 3: Income tier hard cutoff (>1 tier below = exclude) ─
    tier_val      = TIER_ORDER.get(commune_tier, 1)
    camp_tier_val = TIER_ORDER.get(camp_min_tier, 1)
    if camp_tier_val - tier_val > 1:
        return None

    # ── Commune precision ────────────────────────────────────────
    exact_commune_match = bool(set(debate_communes) & set(camp_communes)) if camp_communes and debate_communes else False
    if exact_commune_match:
        commune_prec = 1.0
    else:
        commune_prec = _commune_precision(camp_communes, camp_min_tier, commune_tier, commune_index)

    # ── Gender precision ─────────────────────────────────────────
    gender_prec = _gender_precision(camp_gender, debate_gender)
    if gender_prec == 0.0:
        return None   # hard mismatch

    # ── Age precision ────────────────────────────────────────────
    age_prec = _age_precision(camp_age_min, camp_age_max, debate_age_min, debate_age_max)
    if age_prec == 0.0:
        return None   # zero overlap

    # ── CPM for this slot ────────────────────────────────────────
    # Use campaign's negotiated CPM if set, otherwise commune rate
    cpm = float(campaign.get('cpm') or 0) or commune_cpm

    # ── Precision rate (combined, commune-weighted) ───────────────
    # Commune precision is the primary driver (40%), then gender (35%), age (25%)
    precision_rate = commune_prec * 0.40 + gender_prec * 0.35 + age_prec * 0.25

    # ── Affinity score 0-100 (for display) ───────────────────────
    affinity_score = round(precision_rate * 100, 1)

    # ── Effective audience (# of qualified contacts this debate delivers) ─
    audience = debate_pop or commune_pop
    effective_audience = round(audience * gender_prec * age_prec)

    # ── Economics ────────────────────────────────────────────────
    effective_cpm        = round(cpm * precision_rate, 3)
    cost_per_contact_usd = round(cpm / max(precision_rate * 1000, 1), 5)

    return {
        'affinity_score':       affinity_score,
        'precision_rate':       round(precision_rate, 4),
        'commune':              debate_commune,
        'commune_tier':         commune_tier,
        'commune_income_index': commune_index,
        'exact_commune_match':  exact_commune_match,
        'gender_precision':     round(gender_prec, 3),
        'age_precision':        round(age_prec, 3),
        'effective_audience':   effective_audience,
        'cpm':                  cpm,
        'effective_cpm':        effective_cpm,
        'cost_per_contact_usd': cost_per_contact_usd,
        'optimization_rank':    effective_cpm,   # sort key
    }


def optimize_campaigns_for_debate(debate: dict, campaigns: list, matrix: dict, max_ads: int = 5) -> list:
    """
    Selects and ranks campaigns for a debate using cost-per-contact optimization.

    Ranking criterion: effective_cpm (= CPM × precision_rate)
    This simultaneously:
      - Maximizes Preferendum revenue per impression
      - Minimizes advertiser cost per qualified contact
      - Rewards precise targeting over broad spray-and-pray

    Returns list of campaigns with full optimization metrics, capped at max_ads.
    Each campaign in the output has a unique advertiser (no duplicates per debate).
    """
    scored = []
    seen_advertisers = set()

    for camp in campaigns:
        result = score_and_optimize(camp, debate, matrix)
        if result is None:
            continue

        advertiser = camp.get('advertiser_name') or camp.get('id')

        # Deduplicate: only keep the best-ranked ad per advertiser
        if advertiser in seen_advertisers:
            # Replace if this one scores better
            for i, existing in enumerate(scored):
                if (existing.get('advertiser_name') or existing.get('id')) == advertiser:
                    if result['optimization_rank'] > existing.get('optimization_rank', 0):
                        scored[i] = {**camp, **result}
                    break
        else:
            seen_advertisers.add(advertiser)
            scored.append({**camp, **result})

    scored.sort(key=lambda x: x['optimization_rank'], reverse=True)
    return scored[:max_ads]


def match_campaigns_to_debate(debate: dict, db=None, max_ads: int = 5) -> list:
    """
    Main entry point: loads active campaigns from DB and runs optimization.
    Returns up to max_ads campaigns with full optimization metrics.
    """
    matrix = load_matrix()

    campaigns = []
    if db is not None:
        from sqlalchemy import text
        try:
            rows = db.execute(text(
                "SELECT id, advertiser_name, title, ad_type, banner_url, ad_text, "
                "target_country, target_communes, target_gender, target_age_min, "
                "target_age_max, min_income_tier, min_gni_country, cpm "
                "FROM ad_campaigns WHERE is_active=1 AND status='active' "
                "AND start_date <= datetime('now') AND end_date >= datetime('now') "
                "AND remaining_budget > 0"
            )).fetchall()
            campaigns = [dict(r._mapping) for r in rows]
        except Exception as e:
            print(f"[TargetingAgent] DB error: {e}")

    return optimize_campaigns_for_debate(debate, campaigns, matrix, max_ads)


def get_commune_info(country: str, commune: str) -> dict:
    """Returns income tier, CPM, population and income index for a commune."""
    matrix = load_matrix()
    country_data = matrix.get(country, {})
    commune_data = country_data.get('communes', {}).get(commune)
    if commune_data:
        return {
            'income_tier':    commune_data['income_tier'],
            'income_index':   commune_data['income_index'],
            'cpm':            commune_data['cpm'],
            'population':     commune_data['population'],
            'gni_tier':       country_data.get('gni_tier', 'mid'),
            'gni_per_capita': country_data.get('gni_per_capita', 10000),
        }
    return {
        'income_tier':    'C',
        'income_index':   50,
        'cpm':            country_data.get('cpm_base', 4.0),
        'population':     50000,
        'gni_tier':       country_data.get('gni_tier', 'mid'),
        'gni_per_capita': country_data.get('gni_per_capita', 10000),
    }


def get_matrix_summary() -> dict:
    """Returns a summary of the current targeting matrix."""
    matrix = load_matrix()
    summary = {}
    for iso, data in matrix.items():
        total_pop = sum(c['population'] for c in data['communes'].values())
        communes_by_tier = {'A': 0, 'B': 0, 'C': 0, 'D': 0}
        for c in data['communes'].values():
            communes_by_tier[c['income_tier']] = communes_by_tier.get(c['income_tier'], 0) + 1
        summary[iso] = {
            'gni_per_capita': data['gni_per_capita'],
            'gni_tier':       data['gni_tier'],
            'cpm_base':       data['cpm_base'],
            'communes_total': len(data['communes']),
            'communes_by_tier': communes_by_tier,
            'total_population': total_pop,
        }
    return summary


# ── Auto-build matrix on first import ────────────────────────
if not os.path.exists(MATRIX_FILE):
    print("[TargetingAgent] Building targeting matrix for first time...")
    save_matrix(build_matrix())
    print("[TargetingAgent] Matrix ready.")
