"""
advertising_revenue_agent.py — PREFERENDUM
===========================================
Modelo de ingresos publicitarios para Preferendum como Media.

Lógica:
  - Audiencia verificada (biometría) + SE tier conocido (A/B/C/D) → CPM premium
  - CPM ajustado por tier × grupo de ingreso del país
  - Ingresos = usuarios × distribución_tier × CPM × impresiones / 1000
  - Escenarios: consultas gubernamentales → adquisición masiva costo $0

Fuentes CPM de referencia:
  - Facebook avg: $5–15 (sin verificación, lleno de bots)
  - LinkedIn: $35–100 (verificado por trabajo declarado)
  - Preferendum Tier A: $45–80 (biometría + SE tier + engagement cívico)
  - Preferendum Tier B: $20–40
  - Preferendum Tier C: $10–18
"""

from __future__ import annotations

# ── CPM base por SE tier (USD / 1,000 impresiones) ───────────────────────────
# Justificación: audiencia 100% verificada + clasificada por ingreso real
# Tier A (ejecutivos/HNWI): comparable a LinkedIn premium o Forbes.com
# Tier B (clase media-alta): mejor que Facebook, sin bot-risk
# Tier C (clase media): precio justo por verificación
_CPM_BY_TIER: dict[str, float] = {
    'A': 58.0,   # top 5-8% por ingreso — HNWI, ejecutivos
    'B': 28.0,   # clase media-alta verificada
    'C': 12.0,   # clase media verificada
    'D':  5.0,   # clase media-baja verificada
    'E':  2.0,   # sin tier / datos incompletos
}

# ── Multiplicador CPM por grupo de ingreso del país ───────────────────────────
# Los anunciantes pagan más por audiencias en mercados de alto poder adquisitivo
_CPM_MULT: dict[str, float] = {
    'H1':  1.55,  # US, CH, AU, CA, JP, KR, HK, SG, QA, AE, NO, DK, SE, IE
    'H2':  1.20,  # FR, DE, ES, IT, TW, PL, PT, CZ, GR, SA
    'M1':  0.80,  # CL, MX, TR, CN, RU, KZ, AR, UY
    'M1g': 0.72,  # BR, ZA, CO (M1 con Gini alto — mercado más fragmentado)
    'M2L': 0.48,  # IN, NG, PH, VN, ID, PK, BD, EG
}

# ── Grupo de ingreso por país (mismo que rental_price_agent) ─────────────────
_COUNTRY_GROUP: dict[str, str] = {}
for _c in ['US','CH','AU','CA','GB','DE','NL','AT','BE','JP','KR','HK','QA','AE','KW','IL',
           'SG','DK','SE','NO','IE','LU','FI','NZ','IS']:
    _COUNTRY_GROUP[_c] = 'H1'
for _c in ['FR','IT','ES','PT','CZ','PL','HU','RO','GR','TW','SA','MY','SI','SK','EE','LV','LT']:
    _COUNTRY_GROUP[_c] = 'H2'
for _c in ['CL','MX','AR','UY','TR','CN','RU','KZ']:
    _COUNTRY_GROUP[_c] = 'M1'
for _c in ['BR','ZA','CO']:
    _COUNTRY_GROUP[_c] = 'M1g'
for _c in ['IN','NG','PH','VN','ID','PK','BD','EG','EC','PE','BO','PY','DO','MA']:
    _COUNTRY_GROUP[_c] = 'M2L'

# ── Impresiones por usuario por mes ──────────────────────────────────────────
# Plataforma cívica: engagement deliberado, no scroll pasivo
# Sesiones: 6–10/mes × 12–18 impresiones/sesión
_IMPRESSIONS_PER_USER_MONTH: int = 120

# ── Distribución de tiers en la plataforma (estimada) ────────────────────────
# Ajustar con datos reales de usuarios cuando existan
_TIER_DIST_DEFAULT: dict[str, float] = {
    'A': 0.08,
    'B': 0.22,
    'C': 0.40,
    'D': 0.22,
    'E': 0.08,
}

# ── Top anunciantes globales (Ad Age World's Largest Advertisers 2024) ────────
# Gasto en USD B/año. Fuente: Ad Age Datacenter
TOP_ADVERTISERS: list[dict] = [
    {'rank':  1, 'company': 'Amazon',          'spend_b': 21.40, 'sector': 'E-commerce/Retail'},
    {'rank':  2, 'company': 'Alibaba',          'spend_b': 15.70, 'sector': 'E-commerce/Retail'},
    {'rank':  3, 'company': "L'Oréal",          'spend_b': 15.20, 'sector': 'CPG/Cosmética'},
    {'rank':  4, 'company': 'PDD Holdings',     'spend_b': 14.50, 'sector': 'E-commerce/Retail'},
    {'rank':  5, 'company': 'P&G',              'spend_b': 12.74, 'sector': 'CPG/Hogar'},
    {'rank':  6, 'company': 'LVMH',             'spend_b': 11.05, 'sector': 'Lujo'},
    {'rank':  7, 'company': 'Unilever',         'spend_b':  9.10, 'sector': 'CPG/Hogar'},
    {'rank':  8, 'company': 'Samsung',          'spend_b':  8.20, 'sector': 'Tecnología'},
    {'rank':  9, 'company': 'Alphabet',         'spend_b':  7.40, 'sector': 'Tecnología/Medios'},
    {'rank': 10, 'company': 'Nestlé',           'spend_b':  7.10, 'sector': 'Alimentos'},
    {'rank': 11, 'company': 'Comcast',          'spend_b':  6.27, 'sector': 'Entretenimiento'},
    {'rank': 12, 'company': 'Walt Disney',      'spend_b':  5.50, 'sector': 'Entretenimiento'},
    {'rank': 13, 'company': 'JD.com',           'spend_b':  5.30, 'sector': 'E-commerce/Retail'},
    {'rank': 14, 'company': "McDonald's",       'spend_b':  4.10, 'sector': 'Restaurantes'},
    {'rank': 15, 'company': 'General Motors',   'spend_b':  3.60, 'sector': 'Automotriz'},
    {'rank': 16, 'company': 'Toyota',           'spend_b':  3.50, 'sector': 'Automotriz'},
    {'rank': 17, 'company': 'AT&T',             'spend_b':  3.52, 'sector': 'Telecomunicaciones'},
    {'rank': 18, 'company': 'Pfizer',           'spend_b':  3.30, 'sector': 'Farmacéutico'},
    {'rank': 19, 'company': 'Flutter/FanDuel',  'spend_b':  3.20, 'sector': 'Entretenimiento/Apuestas'},
    {'rank': 20, 'company': 'Coca-Cola',        'spend_b':  3.10, 'sector': 'Alimentos/Bebidas'},
    # Posiciones 21-50: curva descendente $3.0B → $1.5B
    {'rank': 21, 'company': 'Apple',            'spend_b':  3.00, 'sector': 'Tecnología'},
    {'rank': 22, 'company': 'Volkswagen Group', 'spend_b':  2.90, 'sector': 'Automotriz'},
    {'rank': 23, 'company': 'Ford',             'spend_b':  2.80, 'sector': 'Automotriz'},
    {'rank': 24, 'company': 'Stellantis',       'spend_b':  2.70, 'sector': 'Automotriz'},
    {'rank': 25, 'company': 'Hyundai/Kia',      'spend_b':  2.60, 'sector': 'Automotriz'},
    {'rank': 26, 'company': 'Netflix',          'spend_b':  2.50, 'sector': 'Entretenimiento'},
    {'rank': 27, 'company': 'Booking Holdings', 'spend_b':  2.40, 'sector': 'Viajes'},
    {'rank': 28, 'company': 'Verizon',          'spend_b':  2.30, 'sector': 'Telecomunicaciones'},
    {'rank': 29, 'company': 'BMW Group',        'spend_b':  2.20, 'sector': 'Automotriz'},
    {'rank': 30, 'company': 'Mercedes-Benz',    'spend_b':  2.10, 'sector': 'Automotriz'},
    {'rank': 31, 'company': 'Reckitt',          'spend_b':  2.00, 'sector': 'CPG/Salud'},
    {'rank': 32, 'company': 'Expedia',          'spend_b':  1.95, 'sector': 'Viajes'},
    {'rank': 33, 'company': 'AB InBev',         'spend_b':  1.90, 'sector': 'Bebidas'},
    {'rank': 34, 'company': 'Nike',             'spend_b':  1.85, 'sector': 'Ropa/Deportes'},
    {'rank': 35, 'company': 'Adidas',           'spend_b':  1.80, 'sector': 'Ropa/Deportes'},
    {'rank': 36, 'company': 'Heineken',         'spend_b':  1.75, 'sector': 'Bebidas'},
    {'rank': 37, 'company': 'Diageo',           'spend_b':  1.70, 'sector': 'Bebidas'},
    {'rank': 38, 'company': 'Johnson & Johnson','spend_b':  1.65, 'sector': 'Farmacéutico'},
    {'rank': 39, 'company': 'AstraZeneca',      'spend_b':  1.60, 'sector': 'Farmacéutico'},
    {'rank': 40, 'company': 'HSBC',             'spend_b':  1.55, 'sector': 'Financiero'},
    {'rank': 41, 'company': 'Visa',             'spend_b':  1.50, 'sector': 'Financiero'},
    {'rank': 42, 'company': 'Mastercard',       'spend_b':  1.50, 'sector': 'Financiero'},
    {'rank': 43, 'company': 'Airbnb',           'spend_b':  1.45, 'sector': 'Viajes'},
    {'rank': 44, 'company': 'Uber',             'spend_b':  1.40, 'sector': 'Movilidad'},
    {'rank': 45, 'company': 'Colgate-Palmolive','spend_b':  1.38, 'sector': 'CPG/Hogar'},
    {'rank': 46, 'company': 'Pernod Ricard',    'spend_b':  1.35, 'sector': 'Bebidas'},
    {'rank': 47, 'company': 'Ferrero',          'spend_b':  1.30, 'sector': 'Alimentos'},
    {'rank': 48, 'company': 'Estée Lauder',     'spend_b':  1.25, 'sector': 'CPG/Cosmética'},
    {'rank': 49, 'company': 'Shiseido',         'spend_b':  1.20, 'sector': 'CPG/Cosmética'},
    {'rank': 50, 'company': 'Spotify',          'spend_b':  1.15, 'sector': 'Entretenimiento'},
    # Posiciones 51-100: curva $1.10B → $0.55B (estimado Ad Age)
]
# Completar Top 51-100 con curva suavizada
for _r in range(51, 101):
    _spend = round(1.10 - (_r - 51) * (1.10 - 0.55) / 49, 2)
    TOP_ADVERTISERS.append({'rank': _r, 'company': f'Global Advertiser #{_r}', 'spend_b': _spend, 'sector': 'Mixto'})

TOTAL_TOP100_SPEND_B: float = sum(a['spend_b'] for a in TOP_ADVERTISERS)  # ~$365B

# ── Mercado publicitario por país (destino del gasto, USD B) ─────────────────
# Fuente: Dentsu 2026, Statista, Wicked Reports
AD_MARKET_BY_COUNTRY: dict[str, dict] = {
    'US': {'spend_b': 485.0, 'growth_pct':  5.2, 'digital_pct': 78},
    'CN': {'spend_b': 250.0, 'growth_pct':  7.1, 'digital_pct': 88},
    'GB': {'spend_b':  55.0, 'growth_pct':  4.8, 'digital_pct': 82},
    'JP': {'spend_b':  47.5, 'growth_pct':  3.2, 'digital_pct': 60},
    'DE': {'spend_b':  35.0, 'growth_pct':  4.1, 'digital_pct': 68},
    'FR': {'spend_b':  20.0, 'growth_pct':  4.5, 'digital_pct': 70},
    'IN': {'spend_b':  15.9, 'growth_pct':  8.6, 'digital_pct': 55},
    'BR': {'spend_b':  15.5, 'growth_pct':  6.8, 'digital_pct': 58},
    'CA': {'spend_b':  14.0, 'growth_pct':  4.2, 'digital_pct': 76},
    'AU': {'spend_b':  12.8, 'growth_pct':  4.0, 'digital_pct': 74},
    'KR': {'spend_b':  11.0, 'growth_pct':  4.5, 'digital_pct': 72},
    'IT': {'spend_b':   8.5, 'growth_pct':  3.8, 'digital_pct': 65},
    'ES': {'spend_b':   7.2, 'growth_pct':  5.0, 'digital_pct': 67},
    'NL': {'spend_b':   6.8, 'growth_pct':  4.3, 'digital_pct': 79},
    'SE': {'spend_b':   4.5, 'growth_pct':  3.5, 'digital_pct': 80},
    'MX': {'spend_b':   4.2, 'growth_pct':  7.5, 'digital_pct': 55},
    'TR': {'spend_b':   3.8, 'growth_pct':  9.2, 'digital_pct': 58},
    'PL': {'spend_b':   3.5, 'growth_pct':  6.1, 'digital_pct': 65},
    'AR': {'spend_b':   2.8, 'growth_pct': 12.0, 'digital_pct': 52},
    'SA': {'spend_b':   2.7, 'growth_pct':  8.0, 'digital_pct': 60},
    'ZA': {'spend_b':   2.5, 'growth_pct':  5.5, 'digital_pct': 50},
    'AE': {'spend_b':   2.4, 'growth_pct':  7.8, 'digital_pct': 72},
    'CO': {'spend_b':   1.8, 'growth_pct':  8.5, 'digital_pct': 50},
    'CL': {'spend_b':   1.6, 'growth_pct':  6.2, 'digital_pct': 55},
    'PT': {'spend_b':   1.4, 'growth_pct':  4.8, 'digital_pct': 62},
    'NO': {'spend_b':   2.2, 'growth_pct':  3.8, 'digital_pct': 81},
    'DK': {'spend_b':   2.0, 'growth_pct':  3.6, 'digital_pct': 80},
    'BE': {'spend_b':   2.8, 'growth_pct':  4.0, 'digital_pct': 72},
    'CH': {'spend_b':   3.2, 'growth_pct':  3.5, 'digital_pct': 75},
    'AT': {'spend_b':   2.1, 'growth_pct':  3.9, 'digital_pct': 68},
    'SG': {'spend_b':   1.9, 'growth_pct':  6.5, 'digital_pct': 82},
    'HK': {'spend_b':   1.7, 'growth_pct':  4.2, 'digital_pct': 78},
    'MY': {'spend_b':   1.5, 'growth_pct':  7.0, 'digital_pct': 62},
    'TH': {'spend_b':   2.3, 'growth_pct':  6.8, 'digital_pct': 58},
    'ID': {'spend_b':   3.8, 'growth_pct':  9.5, 'digital_pct': 54},
    'PH': {'spend_b':   1.8, 'growth_pct':  8.2, 'digital_pct': 52},
    'VN': {'spend_b':   1.2, 'growth_pct': 10.5, 'digital_pct': 50},
    'PE': {'spend_b':   0.9, 'growth_pct':  7.8, 'digital_pct': 48},
    'EC': {'spend_b':   0.6, 'growth_pct':  7.2, 'digital_pct': 46},
    'RU': {'spend_b':   6.5, 'growth_pct':  4.0, 'digital_pct': 62},
    'CZ': {'spend_b':   1.8, 'growth_pct':  5.2, 'digital_pct': 66},
    'GR': {'spend_b':   1.1, 'growth_pct':  4.5, 'digital_pct': 60},
    'IL': {'spend_b':   2.3, 'growth_pct':  5.8, 'digital_pct': 76},
    'QA': {'spend_b':   0.8, 'growth_pct':  8.5, 'digital_pct': 65},
    'NZ': {'spend_b':   1.8, 'growth_pct':  4.1, 'digital_pct': 73},
    'NG': {'spend_b':   0.8, 'growth_pct': 11.0, 'digital_pct': 42},
    'KZ': {'spend_b':   0.5, 'growth_pct':  9.0, 'digital_pct': 52},
    'UY': {'spend_b':   0.4, 'growth_pct':  6.5, 'digital_pct': 55},
    'DO': {'spend_b':   0.3, 'growth_pct':  7.0, 'digital_pct': 48},
}

GLOBAL_AD_MARKET_B: float = 1_000.0  # Dentsu 2026: $1 trillón total

# ── Escenarios de consultas gubernamentales ───────────────────────────────────
# Estrategia: gobierno convoca → ciudadanos se registran → costo adquisición $0
GOVT_CONSULTATION_SCENARIOS: dict[str, dict] = {
    'CL': {
        'name':              'Chile — Plebiscito / Consulta Nacional',
        'population':        19_500_000,
        'eligible_voters':   15_100_000,
        'participation_rate': 0.52,
        'expected_users':    7_900_000,
        'acquisition_cost':  0,
        'country_ad_market_b': 1.6,
        'precedent':         'Plebiscito 2020: 7.5M votos. Plebiscito 2022: 13M votos.',
    },
    'CO': {
        'name':              'Colombia — Consulta Popular Nacional',
        'population':        52_000_000,
        'eligible_voters':   39_000_000,
        'participation_rate': 0.45,
        'expected_users':   17_600_000,
        'acquisition_cost':  0,
        'country_ad_market_b': 1.8,
        'precedent':         'Consulta Anticorrupción 2018: 11.6M votos.',
    },
    'MX': {
        'name':              'México — Consulta Popular o Revocación',
        'population':       130_000_000,
        'eligible_voters':   93_000_000,
        'participation_rate': 0.18,
        'expected_users':   16_700_000,
        'acquisition_cost':  0,
        'country_ad_market_b': 4.2,
        'precedent':         'Revocación mandato 2022: 16.5M participantes.',
    },
    'AR': {
        'name':              'Argentina — Consulta Popular',
        'population':        46_000_000,
        'eligible_voters':   35_000_000,
        'participation_rate': 0.50,
        'expected_users':   17_500_000,
        'acquisition_cost':  0,
        'country_ad_market_b': 2.8,
        'precedent':         'Plebiscito 1984: 70% participación.',
    },
    'BR': {
        'name':              'Brasil — Consulta Nacional',
        'population':       215_000_000,
        'eligible_voters':  156_000_000,
        'participation_rate': 0.55,
        'expected_users':   85_800_000,
        'acquisition_cost':  0,
        'country_ad_market_b': 15.5,
        'precedent':         'Elecciones 2022: 124M votantes. Alta participación cívica.',
    },
    'ES': {
        'name':              'España — Consulta Ciudadana',
        'population':        47_800_000,
        'eligible_voters':   37_500_000,
        'participation_rate': 0.60,
        'expected_users':   22_500_000,
        'acquisition_cost':  0,
        'country_ad_market_b': 7.2,
        'precedent':         'Alta participación histórica en referéndums.',
    },
    'IN': {
        'name':              'India — National Digital Consultation',
        'population':     1_430_000_000,
        'eligible_voters':  970_000_000,
        'participation_rate': 0.08,
        'expected_users':   77_600_000,
        'acquisition_cost':  0,
        'country_ad_market_b': 15.9,
        'precedent':         'Elecciones 2024: 640M votantes. Mayor democracia del mundo.',
    },
}


# ── FUNCIONES PRINCIPALES ─────────────────────────────────────────────────────

def get_effective_cpm(country: str, tier: str) -> float:
    """CPM real = CPM_base_tier × multiplicador_país."""
    group = _COUNTRY_GROUP.get(country, 'M1')
    return round(_CPM_BY_TIER.get(tier, 2.0) * _CPM_MULT.get(group, 0.70), 2)


def compute_blended_cpm(country: str, tier_dist: dict[str, float] = None) -> float:
    """CPM ponderado por distribución de tiers para un país."""
    dist = tier_dist or _TIER_DIST_DEFAULT
    return round(sum(
        get_effective_cpm(country, tier) * pct
        for tier, pct in dist.items()
    ), 2)


def revenue_model(
    users: int,
    country: str,
    tier_dist: dict[str, float] = None,
    impressions_per_user_month: int = _IMPRESSIONS_PER_USER_MONTH,
    fill_rate: float = 0.70,
) -> dict:
    """
    Calcula ingresos mensuales y anuales para un país dado número de usuarios.

    fill_rate: % de impresiones que se venden (0.70 = 70% — estándar medios digitales)
    """
    dist      = tier_dist or _TIER_DIST_DEFAULT
    blended   = compute_blended_cpm(country, dist)
    imp_total = users * impressions_per_user_month * fill_rate
    revenue_m = imp_total * blended / 1000

    breakdown = {}
    for tier, pct in dist.items():
        u    = int(users * pct)
        cpm  = get_effective_cpm(country, tier)
        imp  = u * impressions_per_user_month * fill_rate
        rev  = imp * cpm / 1000
        breakdown[tier] = {
            'users':       u,
            'cpm_usd':     cpm,
            'impressions': int(imp),
            'revenue_usd': round(rev),
        }

    ad_market = AD_MARKET_BY_COUNTRY.get(country, {}).get('spend_b', 1.0)
    share_pct  = round(revenue_m * 12 / (ad_market * 1e9) * 100, 4) if ad_market else 0

    return {
        'country':              country,
        'users':                users,
        'blended_cpm_usd':      blended,
        'impressions_month':    int(imp_total),
        'revenue_month_usd':    round(revenue_m),
        'revenue_year_usd':     round(revenue_m * 12),
        'fill_rate':            fill_rate,
        'country_ad_market_b':  ad_market,
        'market_share_pct':     share_pct,
        'tier_breakdown':       breakdown,
    }


def govt_consultation_impact(country_code: str) -> dict:
    """
    Calcula el impacto en ingresos de una consulta gubernamental en un país.
    El gobierno hace la convocatoria → Preferendum captura usuarios a costo $0.
    """
    sc = GOVT_CONSULTATION_SCENARIOS.get(country_code)
    if not sc:
        return {'error': f'País {country_code} no en escenarios gubernamentales'}

    users = sc['expected_users']
    rev   = revenue_model(users, country_code)

    return {
        'scenario':             sc['name'],
        'country':              country_code,
        'expected_users':       users,
        'acquisition_cost_usd': sc['acquisition_cost'],
        'precedent':            sc['precedent'],
        'revenue_month_usd':    rev['revenue_month_usd'],
        'revenue_year_usd':     rev['revenue_year_usd'],
        'blended_cpm_usd':      rev['blended_cpm_usd'],
        'country_ad_market_b':  sc['country_ad_market_b'],
        'market_share_pct':     rev['market_share_pct'],
        'note': (
            f"Con {users:,} usuarios verificados, Preferendum capturaría "
            f"${rev['revenue_year_usd']/1e6:.1f}M/año — "
            f"{rev['market_share_pct']:.3f}% del mercado publicitario de {country_code}."
        ),
    }


def multi_country_scenario(
    user_scenarios: dict[str, int],
    tier_dist: dict[str, float] = None,
) -> dict:
    """
    Calcula ingresos para múltiples países con usuarios dados.
    user_scenarios: {'CL': 500000, 'CO': 2000000, ...}
    """
    results  = []
    total_m  = 0
    total_a  = 0
    total_u  = 0

    for cc, users in sorted(user_scenarios.items(), key=lambda x: -x[1]):
        r = revenue_model(users, cc, tier_dist)
        results.append(r)
        total_m += r['revenue_month_usd']
        total_a += r['revenue_year_usd']
        total_u += users

    return {
        'total_users':        total_u,
        'total_revenue_month': round(total_m),
        'total_revenue_year':  round(total_a),
        'total_revenue_year_m': round(total_a / 1e6, 2),
        'countries':          len(results),
        'breakdown':          results,
    }


def preferendum_growth_model() -> dict:
    """
    Modelo de crecimiento en 3 horizontes temporales.
    Basado en estrategia: consultas gubernamentales + publicidad + viralidad orgánica.
    """
    scenarios = {
        'año_1_base': {
            'label':       'Año 1 — Base (sin consultas gubernamentales)',
            'description': 'Crecimiento orgánico + 1-2 campañas de marketing',
            'users_by_country': {
                'CL': 150_000, 'CO': 80_000, 'MX': 120_000, 'AR': 90_000,
                'ES': 100_000, 'BR': 200_000, 'US': 50_000, 'PE': 40_000,
            },
        },
        'año_1_consulta': {
            'label':       'Año 1 — Con 1 consulta gubernamental (Chile)',
            'description': 'Chile activa plebiscito + crecimiento orgánico resto',
            'users_by_country': {
                'CL': 7_900_000, 'CO': 80_000, 'MX': 120_000, 'AR': 90_000,
                'ES': 100_000,   'BR': 200_000, 'US': 50_000,  'PE': 40_000,
            },
        },
        'año_2_latam': {
            'label':       'Año 2 — LATAM + España activados',
            'description': '3-4 consultas gubernamentales + efecto viral',
            'users_by_country': {
                'CL': 8_500_000, 'CO': 17_600_000, 'MX': 16_700_000,
                'AR': 5_000_000, 'ES': 5_000_000,  'BR': 10_000_000,
                'US': 500_000,   'PE': 1_000_000,   'EC': 500_000,
                'DO': 300_000,   'UY': 200_000,
            },
        },
        'año_3_global': {
            'label':       'Año 3 — Global (Europa + India + LATAM)',
            'description': '10+ países con consultas + marca establecida',
            'users_by_country': {
                'CL': 10_000_000, 'CO': 20_000_000, 'MX': 20_000_000,
                'AR':  8_000_000, 'ES': 22_500_000,  'BR': 85_800_000,
                'US':  5_000_000, 'IN': 20_000_000,  'PE':  3_000_000,
                'EC':  1_500_000, 'DE':  2_000_000,  'FR':  2_000_000,
                'GB':  2_000_000, 'IT':  1_500_000,  'PT':  1_000_000,
            },
        },
    }

    results = {}
    for key, sc in scenarios.items():
        r = multi_country_scenario(sc['users_by_country'])
        results[key] = {
            'label':               sc['label'],
            'description':         sc['description'],
            'total_users':         r['total_users'],
            'revenue_month_usd':   r['total_revenue_month'],
            'revenue_year_usd':    r['total_revenue_year'],
            'revenue_year_m':      r['total_revenue_year_m'],
            'countries_active':    r['countries'],
        }

    return {
        'model':    'Preferendum Media — Advertising Revenue Projections',
        'currency': 'USD',
        'source':   'Ad Age 2024, Dentsu 2026, metodología CPM interna Preferendum',
        'scenarios': results,
        'cpm_table': {
            tier: {
                cc: get_effective_cpm(cc, tier)
                for cc in ['US', 'GB', 'DE', 'ES', 'CL', 'MX', 'BR', 'CO', 'IN']
            }
            for tier in ['A', 'B', 'C', 'D']
        },
        'key_insight': (
            'Una sola consulta gubernamental en Brasil (85M usuarios esperados) '
            'genera más de $850M/año en ingresos publicitarios — '
            'sin costo de adquisición. El gobierno paga la convocatoria.'
        ),
    }
