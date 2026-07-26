"""
campaign_projector.py — PREFERENDUM
Proyección de audiencia para campañas en mercados donde Preferendum aún está creciendo.

Metodología:
  1. Población digital adulta por país (WorldBank 2024 + ITU Internet penetration)
  2. Distribución de SE tiers por grupo de ingreso (H1/H2/M1/M1g/M2L)
  3. Distribución etaria del segmento objetivo
  4. CPM por tier × país (tabla real del sistema)
  5. Reach proyectado = población_digital × tier_pct × age_pct × adoption_rate

adoption_rate = % de la audiencia objetivo que adoptará Preferendum en horizonte dado.
Para demos/pitch: mostrar horizonte 12 meses con tasa conservadora (1-3%).
"""

from __future__ import annotations
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# DATOS DEMOGRÁFICOS POR PAÍS
# Fuente: WorldBank 2024, ITU 2024, UN Population Division 2024
# población_digital = población_total × internet_penetration
# ─────────────────────────────────────────────────────────────────────────────
# Formato: cc → (población_total_M, internet_penetration_pct, pct_18_26, pct_27_55)
# pct_18_26: % de la población total en rango universitario
# pct_27_55: % de la población total en rango familia/carrera
COUNTRY_DEMO: dict[str, tuple[float, float, float, float]] = {
    # H1
    'US': (335.0, 92, 11.5, 36.0),
    'GB': (68.0,  95, 10.5, 36.5),
    'DE': (84.0,  93, 9.5,  35.0),
    'FR': (68.0,  92, 10.0, 35.5),
    'AU': (27.0,  91, 11.0, 36.0),
    'CA': (40.0,  93, 10.5, 36.0),
    'JP': (125.0, 90, 8.5,  32.0),
    'KR': (52.0,  98, 9.0,  34.0),
    'NL': (17.9,  96, 10.5, 36.0),
    'CH': (8.8,   94, 9.5,  37.0),
    'SE': (10.5,  95, 10.0, 36.0),
    'NO': (5.4,   98, 10.0, 35.5),
    'DK': (5.9,   98, 10.0, 36.0),
    'AT': (9.1,   93, 9.5,  35.5),
    'BE': (11.6,  92, 10.0, 36.0),
    'IE': (5.1,   95, 11.0, 38.0),
    'FI': (5.5,   95, 9.5,  35.0),
    'SG': (6.0,   97, 10.5, 37.0),
    'HK': (7.5,   96, 9.0,  33.0),
    'NZ': (5.1,   93, 11.0, 36.0),
    'IL': (9.7,   90, 12.0, 37.0),
    'AE': (10.0,  99, 9.0,  45.0),  # expats jóvenes
    'QA': (3.0,   99, 8.0,  48.0),
    'LU': (0.67,  98, 10.0, 38.0),
    # H2
    'IT': (59.0,  85, 9.0,  34.0),
    'ES': (47.0,  90, 10.0, 35.5),
    'PT': (10.3,  88, 10.0, 35.0),
    'PL': (38.0,  85, 10.5, 36.0),
    'CZ': (10.8,  88, 9.5,  36.0),
    'GR': (10.7,  80, 10.0, 34.5),
    'HU': (9.7,   83, 9.5,  35.0),
    'TW': (23.6,  93, 9.0,  34.0),
    'SA': (36.0,  98, 14.0, 43.0),
    'MY': (33.0,  92, 13.0, 38.0),
    # M1
    'CL': (19.5,  90, 12.0, 37.0),
    'AR': (46.0,  85, 12.5, 36.0),
    'UY': (3.5,   88, 11.0, 36.0),
    'CN': (1412.0,75, 12.0, 37.0),
    'RU': (144.0, 85, 10.5, 36.0),
    'TR': (85.0,  82, 13.0, 38.0),
    'TH': (72.0,  85, 11.0, 38.0),
    'KZ': (19.0,  82, 13.0, 38.0),
    # M1g (Gini alto)
    'BR': (215.0, 84, 13.0, 37.0),
    'MX': (130.0, 78, 14.0, 38.0),
    'CO': (52.0,  75, 13.5, 37.0),
    'ZA': (60.0,  72, 14.0, 36.0),
    # M2L
    'IN': (1430.0,52, 17.0, 36.0),
    'ID': (278.0, 78, 16.0, 37.0),
    'PH': (115.0, 76, 17.0, 37.0),
    'VN': (98.0,  79, 14.0, 38.0),
    'NG': (225.0, 55, 20.0, 35.0),
    'EG': (105.0, 72, 18.0, 36.0),
    'PE': (33.0,  73, 14.0, 37.0),
    'MA': (37.0,  88, 16.0, 37.0),
    'EC': (18.0,  75, 14.5, 37.0),
}

COUNTRY_NAMES: dict[str, str] = {
    'US':'United States','GB':'United Kingdom','DE':'Germany','FR':'France',
    'AU':'Australia','CA':'Canada','JP':'Japan','KR':'South Korea','NL':'Netherlands',
    'CH':'Switzerland','SE':'Sweden','NO':'Norway','DK':'Denmark','AT':'Austria',
    'BE':'Belgium','IE':'Ireland','FI':'Finland','SG':'Singapore','HK':'Hong Kong',
    'NZ':'New Zealand','IL':'Israel','AE':'UAE','QA':'Qatar','LU':'Luxembourg',
    'IT':'Italy','ES':'Spain','PT':'Portugal','PL':'Poland','CZ':'Czech Republic',
    'GR':'Greece','HU':'Hungary','TW':'Taiwan','SA':'Saudi Arabia','MY':'Malaysia',
    'CL':'Chile','AR':'Argentina','UY':'Uruguay','CN':'China','RU':'Russia',
    'TR':'Turkey','TH':'Thailand','KZ':'Kazakhstan',
    'BR':'Brazil','MX':'Mexico','CO':'Colombia','ZA':'South Africa',
    'IN':'India','ID':'Indonesia','PH':'Philippines','VN':'Vietnam',
    'NG':'Nigeria','EG':'Egypt','PE':'Peru','MA':'Morocco','EC':'Ecuador',
}

# SE tier distribution por grupo (% de usuarios digitales en cada tier)
TIER_DIST: dict[str, dict[str, float]] = {
    'H1':  {'A': 20.0, 'B': 20.0, 'C': 25.0, 'D': 20.0, 'E': 15.0},
    'H2':  {'A': 12.0, 'B': 20.0, 'C': 28.0, 'D': 22.0, 'E': 18.0},
    'M1':  {'A':  7.0, 'B': 18.0, 'C': 25.0, 'D': 25.0, 'E': 25.0},
    'M1g': {'A':  5.0, 'B': 15.0, 'C': 25.0, 'D': 30.0, 'E': 25.0},
    'M2L': {'A':  3.0, 'B': 12.0, 'C': 25.0, 'D': 30.0, 'E': 30.0},
}

# CPM base por país (USD por 1,000 impresiones verificadas)
# Tier A = 3× base, Tier B = 1.5× base, Tier C = 0.8× base, Tier D = 0.4× base
CPM_BASE: dict[str, float] = {
    'US':18.0,'GB':14.0,'DE':12.0,'AU':13.0,'CA':11.0,'CH':15.0,'NL':11.0,
    'SE':10.0,'NO':10.0,'DK':10.0,'AT':10.0,'BE':9.5,'IE':11.0,'FI':9.0,
    'SG':12.0,'HK':11.0,'NZ':10.0,'IL':10.0,'AE':9.0,'QA':8.5,'LU':10.0,
    'FR':9.0,'IT':8.0,'ES':8.5,'PT':7.0,'PL':6.5,'CZ':7.0,'GR':6.0,
    'HU':6.0,'TW':7.5,'SA':8.0,'MY':5.5,'KR':9.0,'JP':10.0,
    'CL':8.0,'AR':5.5,'UY':6.0,'CN':6.0,'RU':5.0,'TR':5.0,'TH':5.5,'KZ':4.5,
    'BR':7.0,'MX':6.0,'CO':5.0,'ZA':5.5,
    'IN':3.5,'ID':4.0,'PH':4.5,'VN':4.0,'NG':3.0,'EG':3.5,'PE':4.0,
    'MA':3.5,'EC':3.5,
}

TIER_CPM_MULT = {'A': 3.0, 'B': 1.5, 'C': 0.8, 'D': 0.4}

# Grupos de ingreso (importado de rental_price_agent en runtime)
_GROUP_CACHE: dict[str, str] = {}
def _get_group(cc: str) -> str:
    if not _GROUP_CACHE:
        try:
            from rental_price_agent import COUNTRY_INCOME_GROUP, HIGH_GINI_COUNTRIES
            for c, g in COUNTRY_INCOME_GROUP.items():
                grp = g
                if g == 'M1' and c in HIGH_GINI_COUNTRIES:
                    grp = 'M1g'
                _GROUP_CACHE[c] = grp
        except Exception:
            pass
    return _GROUP_CACHE.get(cc, 'M1')


# ─────────────────────────────────────────────────────────────────────────────
# NÚCLEO: PROYECCIÓN DE AUDIENCIA
# ─────────────────────────────────────────────────────────────────────────────
def project_audience(
    country: str,
    tiers: list[str],
    age_min: int = 18,
    age_max: int = 65,
    adoption_months: int = 12,
    adoption_rate_pct: Optional[float] = None,
) -> dict:
    """
    Proyecta la audiencia alcanzable en un país dado para un segmento objetivo.

    Returns dict con: potential_market, tier_audience, cpm_usd,
                      projected_reach_12m, cost_per_1000, total_reach
    """
    cc = country.upper()
    demo = COUNTRY_DEMO.get(cc)
    if not demo:
        return {'error': f'País {cc} no en base de datos demográficos'}

    pop_M, inet_pct, pct_1826, pct_2755 = demo
    group = _get_group(cc)
    tier_dist = TIER_DIST.get(group, TIER_DIST['M1'])
    cpm_base = CPM_BASE.get(cc, 5.0)

    # Población digital total
    digital_pop = pop_M * 1_000_000 * (inet_pct / 100)

    # Segmento por edad
    if age_min <= 26 and age_max <= 27:
        age_pct = pct_1826 / 100
    elif age_min >= 27:
        age_pct = pct_2755 / 100
    else:
        # Rango mixto: interpolación lineal simple
        span = age_max - age_min
        age_pct = ((pct_1826 + pct_2755) / 2) / 100 * min(span / 30, 1.0)

    digital_age_pop = digital_pop * age_pct

    # Audiencia por tier
    tier_audience = 0
    weighted_cpm = 0.0
    tier_breakdown: dict[str, int] = {}
    for t in tiers:
        t = t.upper()
        pct = tier_dist.get(t, 0) / 100
        users = int(digital_age_pop * pct)
        tier_breakdown[t] = users
        tier_audience += users
        weighted_cpm += users * cpm_base * TIER_CPM_MULT.get(t, 1.0)

    cpm_usd = round(weighted_cpm / tier_audience, 2) if tier_audience else 0

    # Adoption rate: tasa conservadora por grupo de ingreso
    if adoption_rate_pct is None:
        adoption_rate_pct = {
            'H1': 2.5, 'H2': 2.0, 'M1': 1.5, 'M1g': 1.2, 'M2L': 0.8,
        }.get(group, 1.5)

    projected_reach = int(tier_audience * (adoption_rate_pct / 100))

    return {
        'country':           cc,
        'country_name':      COUNTRY_NAMES.get(cc, cc),
        'income_group':      group,
        'digital_population': int(digital_pop),
        'digital_age_segment': int(digital_age_pop),
        'age_range':         f'{age_min}–{age_max}',
        'tiers_targeted':    tiers,
        'tier_breakdown':    tier_breakdown,
        'total_tier_audience': tier_audience,
        'adoption_rate_pct': adoption_rate_pct,
        'projected_reach_12m': projected_reach,
        'cpm_usd':           cpm_usd,
        'verification':      'Biométrico (rostro + cédula + dispositivo) — 100% humanos verificados',
    }


def project_campaign(
    countries: list[str],
    tiers: list[str],
    age_min: int,
    age_max: int,
    budget_usd: float,
    campaign_name: str = '',
    brand: str = '',
    adoption_months: int = 12,
) -> dict:
    """
    Genera análisis completo de campaña multi-país.
    Distribuye el presupuesto proporcionalmente al reach proyectado por país.
    """
    country_results = []
    total_reach = 0
    total_audience = 0

    for cc in countries:
        r = project_audience(cc, tiers, age_min, age_max, adoption_months)
        if 'error' not in r:
            country_results.append(r)
            total_reach    += r['projected_reach_12m']
            total_audience += r['total_tier_audience']

    # Ordenar por reach proyectado
    country_results.sort(key=lambda x: x['projected_reach_12m'], reverse=True)

    # Distribución de presupuesto proporcional al reach
    for r in country_results:
        share = r['projected_reach_12m'] / total_reach if total_reach else 0
        r['budget_allocated_usd'] = round(budget_usd * share, 0)
        r['impressions_bought']   = int((r['budget_allocated_usd'] / r['cpm_usd']) * 1000) if r['cpm_usd'] else 0

    # Resumen global
    total_impressions = sum(r['impressions_bought'] for r in country_results)
    avg_cpm = round(budget_usd / total_impressions * 1000, 2) if total_impressions else 0

    return {
        'campaign': {
            'name':          campaign_name or f'Campaña {brand}',
            'brand':         brand,
            'tiers':         tiers,
            'age_range':     f'{age_min}–{age_max}',
            'countries':     len(country_results),
            'budget_usd':    budget_usd,
        },
        'global_summary': {
            'total_addressable_audience': total_audience,
            'total_projected_reach_12m':  total_reach,
            'total_impressions':          total_impressions,
            'avg_cpm_usd':               avg_cpm,
            'budget_usd':                budget_usd,
            'verification':              '100% humanos verificados (biometría + ID oficial)',
            'vs_meta_note':              'Meta/Google no verifica identidad ni tier socioeconómico real',
        },
        'by_country': country_results,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ESCENARIOS PEUGEOT PRE-CONFIGURADOS
# ─────────────────────────────────────────────────────────────────────────────
PEUGEOT_COUNTRIES = [
    'FR','ES','PT','IT','PL','DE','BE','NL','GB','AT',  # Europa
    'BR','AR','CL','MX','CO',                             # Latinoamérica
    'MA','ZA',                                             # África
    'TR',                                                  # Turquía
]

def peugeot_students(budget_usd: float = 500_000) -> dict:
    """
    Peugeot 208 / e-208 — Estudiantes universitarios.
    Segmento: 18-26 años, SE tier B+C (poder adquisitivo propio o familia).
    Peugeot pequeño: accesible, urbano, primer auto.
    """
    return project_campaign(
        countries=PEUGEOT_COUNTRIES,
        tiers=['B', 'C'],
        age_min=18,
        age_max=26,
        budget_usd=budget_usd,
        campaign_name='Peugeot 208 — Estudiantes Universitarios',
        brand='Peugeot',
    )


def peugeot_families(budget_usd: float = 750_000) -> dict:
    """
    Peugeot Rifter / Traveller — Familias grandes.
    Segmento: 28-55 años, SE tier A+B (capacidad de compra de van familiar).
    Van premium: espacio, seguridad, tecnología.
    """
    return project_campaign(
        countries=PEUGEOT_COUNTRIES,
        tiers=['A', 'B'],
        age_min=28,
        age_max=55,
        budget_usd=budget_usd,
        campaign_name='Peugeot Rifter/Traveller — Familias',
        brand='Peugeot',
    )


def brazil_ab_25plus(budget_usd: float = 200_000) -> dict:
    """Análisis específico: Brasil, tier A+B, mayores de 25."""
    r = project_audience('BR', ['A', 'B'], age_min=25, age_max=65)
    share = budget_usd / (r['cpm_usd'] / 1000) if r['cpm_usd'] else 0
    r['budget_usd'] = budget_usd
    r['impressions_at_budget'] = int(share)
    r['scenario'] = 'Brasil — Tier A+B — 25+ años'
    return r
