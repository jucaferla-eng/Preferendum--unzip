from __future__ import annotations
"""
budget_optimizer.py — Motor de Optimización de Presupuesto v2
==============================================================
Dado los parámetros de una campaña, calcula la distribución óptima del
presupuesto entre segmentos (país × edad × tamaño empresa).

Modelo estadístico:
  Cada cargo (ISCO) × tamaño empresa sigue distribución log-normal.
  Pesos por ISCO: proporcionales al empleo real (ILO KILM 2023) — no uniforme.
  Archetypes de producto definen qué ISCOs son audiencia objetivo.
  Para ISCO 1: datos CEO PPP reales por tamaño de empresa (Perplexity 2026,
  Tabla 1 — Eurostat SES + agencias nacionales de estadística).

Fórmula: qualified[segmento] = users × Σ_isco(w_isco × P(ingreso ≥ umbral))
Budget óptimo ∝ qualified[segmento] / sum(qualified[todos])

Fuentes:
  Sigmas log-normal:   JC Fernandez Lazo, 2026-08-01
  Pesos ISCO:          ILO KILM 2023
  Archetypes:          Perplexity/JC Budget Model, 2026-07-31
  CEO PPP por tamaño:  Perplexity Tabla 1 (Eurostat SES + institutos nacionales)
"""

import math
from sqlalchemy import text

# ── Pesos de empleo por ISCO (ILO KILM 2023, promedio global) ────────────────
# ISCO 5, 9 tienen 4x más trabajadores que ISCO 1 — afecta el cálculo de
# audiencia masiva. Para productos premium, este peso se normaliza dentro
# del archetype seleccionado.
_ISCO_EMPLOYMENT_WEIGHTS: dict[int, float] = {
    1: 0.04,   # Managers / Directivos
    2: 0.16,   # Professionals / Profesionales
    3: 0.10,   # Technicians / Técnicos
    4: 0.08,   # Clerical / Administrativos
    5: 0.18,   # Service & Sales / Servicios
    6: 0.11,   # Agriculture / Agrícola
    7: 0.11,   # Craft / Artesanos
    8: 0.07,   # Machine operators / Operadores
    9: 0.15,   # Elementary / Básico
}

# ── Archetypes: qué grupos ISCO integran la audiencia objetivo ────────────────
# Fuente: Perplexity Advertising Budget Model 2026-07-31 (adaptado a ISCO 1-9)
# ultra_premium → Porsche/Rolex equiv. (riqueza > $1M), solo ISCO 1 grandes
# premium       → BMW/Mercedes equiv. (ISCO 1-5, upper-middle)
# mid_premium   → Adidas equiv. (pure middle, excluye extremos)
# mass_market   → VW/Hyundai equiv. (middle and below)
# universal     → Coca-Cola (todos los segmentos)
ARCHETYPES: dict[str, list[int]] = {
    'ultra_premium': [1],
    'premium':       [1, 2, 3, 4, 5],
    'mid_premium':   [1, 2, 3, 4, 5, 7, 8],
    'mass_market':   [4, 5, 6, 7, 8, 9],
    'universal':     [1, 2, 3, 4, 5, 6, 7, 8, 9],
}

# ── CEO/ejecutivo PPP USD/mes por país × tamaño empresa (Tabla 1 Perplexity) ─
# Fuentes: Eurostat Structure of Earnings Survey, Gallagher CEO Comp 2024-2025,
# Page Executive, Docco/Levu/Caixin, Ambisjon.no, Rosstat 57-T, DGBAS, SSB.
# ISCO 1 nacional subestima a ejecutivos de grandes empresas por orden de
# magnitud (ej: México $1,523/mes promedio vs $47,900 empresa grande).
# Estos valores reemplazan el cálculo median × SIZE_MULT para ISCO 1.
_CEO_PPP: dict[str, dict[str, float]] = {
    'US': {'small':  17_202, 'medium':  250_500, 'large': 1_541_667},
    'GB': {'small':  12_540, 'medium':   56_467, 'large':   740_289},
    'UK': {'small':  12_540, 'medium':   56_467, 'large':   740_289},  # alias
    'FR': {'small':  10_397, 'medium':   18_960, 'large':   366_974},
    'BR': {'small':   8_759, 'medium':   21_138, 'large':   106_700},
    'RU': {'small':   7_881, 'medium':   39_610, 'large':    87_835},
    'CO': {'small':  22_516, 'medium':   49_684, 'large':    81_377},
    'BD': {'small':  11_729, 'medium':   21_754, 'large':    58_048},
    # MX: Levu Executives reporta $47,900 para empresa grande, pero ese dato
    # mezcla PEMEX (tope gubernamental) con América Móvil, CEMEX, FEMSA, Bimbo
    # (pay a precio Wall Street). Large corregido hacia privado puro. 130M hab.
    'MX': {'small':  27_228, 'medium':   36_304, 'large':   120_000},
    'CN': {'small':   1_508, 'medium':    3_392, 'large':    31_663},
    'NO': {'small':   7_293, 'medium':   11_394, 'large':    22_787},
    # Estimados para países sin dato directo — ratio promedio de los 10 anteriores
    # CL: Codelco, BHP, Anglo American, Antofagasta — ejecutivos pagados en USD
    # internacionales. Precio del cobre lo fija Londres; salario ejecutivo ídem.
    'CL': {'small':  18_000, 'medium':   35_000, 'large':   110_000},
    'AR': {'small':  12_000, 'medium':   22_000, 'large':    55_000},
    'PE': {'small':  14_000, 'medium':   28_000, 'large':    62_000},
    'EC': {'small':  10_000, 'medium':   19_000, 'large':    44_000},
    'DE': {'small':  12_000, 'medium':   60_000, 'large':   380_000},
    'ES': {'small':   9_500, 'medium':   18_000, 'large':   180_000},
    'IT': {'small':   8_500, 'medium':   16_000, 'large':   150_000},
    'CA': {'small':  15_000, 'medium':  180_000, 'large': 1_100_000},
    'AU': {'small':  14_000, 'medium':  140_000, 'large':   900_000},
    'JP': {'small':  10_000, 'medium':   40_000, 'large':   250_000},
    'KR': {'small':   9_000, 'medium':   35_000, 'large':   180_000},
    'IN': {'small':   4_000, 'medium':   12_000, 'large':    80_000},
    'SG': {'small':  18_000, 'medium':   80_000, 'large':   500_000},
    'HK': {'small':  14_000, 'medium':   60_000, 'large':   350_000},
    'TW': {'small':   8_000, 'medium':   25_000, 'large':   140_000},
    'CH': {'small':  20_000, 'medium':   80_000, 'large':   600_000},
    'IL': {'small':  16_000, 'medium':   55_000, 'large':   280_000},
    'AE': {'small':  18_000, 'medium':   65_000, 'large':   320_000},
    'SA': {'small':  15_000, 'medium':   45_000, 'large':   220_000},
    'QA': {'small':  18_000, 'medium':   60_000, 'large':   300_000},
    'ZA': {'small':   7_000, 'medium':   18_000, 'large':    80_000},
    'NG': {'small':   3_000, 'medium':    8_000, 'large':    35_000},
    'MY': {'small':   6_000, 'medium':   18_000, 'large':    85_000},
    'KZ': {'small':   3_500, 'medium':    9_000, 'large':    40_000},
    'TR': {'small':   4_000, 'medium':   10_000, 'large':    45_000},
}

# ── CEO PPP bucket "multinational" — empresas globales con sede en países
# "pequeños" pero que operan en múltiples mercados y pagan a precio Nasdaq.
# Solo aplica a países con presencia exportadora real. Representa ~3-5% del
# ISCO 1 local pero con pay muy superior al bucket "large" doméstico.
# Ejemplos: Falabella/Cencosud/LATAM (CL), América Móvil/CEMEX/FEMSA (MX),
# Vale/Petrobras/Itaú (BR), Ecopetrol/Grupo Aval (CO), Equinor/Telenor (NO).
_CEO_PPP_MULTINATIONAL: dict[str, float] = {
    # LatAm — retailers, mineras, telcos, energía con cotización internacional
    'CL':  400_000,   # Falabella, Cencosud, LATAM Airlines (NYSE: LTM), SQM, Antofagasta, Colbún
    'MX':  500_000,   # América Móvil, CEMEX, FEMSA, Grupo Bimbo — Nasdaq-listed
    'BR':  350_000,   # Vale, Petrobras, Itaú, BTG Pactual, Embraer
    'CO':  180_000,   # Ecopetrol, Grupo Aval, Bancolombia — NYSE-listed
    'PE':  150_000,   # Southern Copper, Credicorp, Hochschild — NYSE
    'AR':  130_000,   # MercadoLibre (Nasdaq), YPF, Globant — aunque economía volátil
    'EC':   80_000,   # Menor base multinacional; Banco Pichincha, Corporación Favorita
    # Europa pequeña con multinationales
    'NO':  250_000,   # Equinor (ex-Statoil), Telenor, Aker — pagan a precio global
    'CH':  700_000,   # Nestlé, Novartis, Roche, UBS, ABB — algunos de los más altos
    'NL':  450_000,   # Shell, Unilever, ASML, ING, Philips
    'SE':  300_000,   # Ericsson, Volvo, H&M, Spotify, Ikea
    'IL':  350_000,   # Check Point, Mobileye, NICE, Amdocs — Nasdaq
    'SG':  600_000,   # DBS, Grab, Sea Ltd, ST Engineering — APAC hub
    'HK':  500_000,   # HSBC, AIA, CK Hutchison — multinacional Asia-Pacífico
    'AE':  400_000,   # Emirates, DP World, ADNOC, Mubadala — sovereign-linked
    'QA':  350_000,   # QatarEnergy, Qatar Airways — sovereign wealth
    'SA':  300_000,   # Aramco — mayor empresa del mundo por market cap
    # Asia emergente con multinationales
    'KR':  350_000,   # Samsung, Hyundai, LG, SK, POSCO — chaebols globales
    'TW':  300_000,   # TSMC, Foxconn, MediaTek — cadena global semiconductores
    'IN':  200_000,   # Infosys, TCS, Reliance, HCL — TI global + conglomerados
    'CN':  250_000,   # Alibaba, Tencent, Huawei, CATL — tech y manufactura global
    'JP':  400_000,   # Toyota, Sony, SoftBank, Mitsubishi — multinationales históricas
    'MY':  180_000,   # Petronas, CIMB, Axiata, Top Glove
    'TH':  150_000,   # PTT, Bangkok Bank, Charoen Pokphand Group
    # Africa/resto
    'ZA':  200_000,   # Anglo American, Naspers/Prosus, Standard Bank
    'NG':   80_000,   # Dangote Group, MTN Nigeria — Nigeria Stock Exchange
}

# ── Sigmas log-normal por (bucket_empresa, isco_group) ───────────────────────
# Fuente: modelo JC (2026-08-01). σ ≈ 0.8 para managers empresa grande.
# 'multinational': σ alto (0.85) porque dispersión entre CEO de Falabella vs
# gerente de planta en Cencosud es máxima dentro del mismo bucket.
_SIGMA: dict[tuple[str, int], float] = {
    ('multinational', 1): 0.85, ('multinational', 2): 0.70, ('multinational', 3): 0.60,
    ('multinational', 4): 0.50, ('multinational', 5): 0.45, ('multinational', 6): 0.40,
    ('multinational', 7): 0.48, ('multinational', 8): 0.48, ('multinational', 9): 0.32,
    ('large', 1): 0.80, ('large', 2): 0.65, ('large', 3): 0.55,
    ('large', 4): 0.45, ('large', 5): 0.40, ('large', 6): 0.35,
    ('large', 7): 0.42, ('large', 8): 0.42, ('large', 9): 0.28,
    ('medium', 1): 0.52, ('medium', 2): 0.42, ('medium', 3): 0.36,
    ('medium', 4): 0.30, ('medium', 5): 0.27, ('medium', 6): 0.24,
    ('medium', 7): 0.28, ('medium', 8): 0.28, ('medium', 9): 0.20,
    ('small', 1): 0.32, ('small', 2): 0.26, ('small', 3): 0.22,
    ('small', 4): 0.19, ('small', 5): 0.17, ('small', 6): 0.15,
    ('small', 7): 0.19, ('small', 8): 0.19, ('small', 9): 0.13,
}

# Multiplicadores SIZE_MULT para ISCO 2-9 (ISCO 1 usa _CEO_PPP/_CEO_PPP_MULTINATIONAL)
# Derived from Eurostat SES + ILO enterprise-size wage differentials
_SIZE_MULT_BY_ISCO: dict[tuple[str, int], float] = {
    # Multinational — salarios internacionales para todos los ISCO
    ('multinational', 2): 4.0, ('multinational', 3): 2.8, ('multinational', 4): 2.0,
    ('multinational', 5): 1.8, ('multinational', 6): 1.4, ('multinational', 7): 2.2,
    ('multinational', 8): 2.0, ('multinational', 9): 1.5,
    # Large vs medium
    ('large', 2): 2.5,  ('large', 3): 1.8,  ('large', 4): 1.4,
    ('large', 5): 1.3,  ('large', 6): 1.15, ('large', 7): 1.5,
    ('large', 8): 1.45, ('large', 9): 1.2,
    # Medium = 1.0 baseline
    ('medium', 2): 1.0, ('medium', 3): 1.0, ('medium', 4): 1.0,
    ('medium', 5): 1.0, ('medium', 6): 1.0, ('medium', 7): 1.0,
    ('medium', 8): 1.0, ('medium', 9): 1.0,
    # Small vs medium
    ('small', 2): 0.55, ('small', 3): 0.70, ('small', 4): 0.78,
    ('small', 5): 0.80, ('small', 6): 0.85, ('small', 7): 0.75,
    ('small', 8): 0.78, ('small', 9): 0.82,
}

# Distribución real de trabajadores por tamaño de empresa (ILO Enterprise Survey 2023)
# multinational es ~4% del empleo total pero con salarios Nasdaq — no debe recibir
# peso 25% cuando se promedia con small/medium/large.
_BUCKET_WEIGHTS: dict[str, float] = {
    'small':         0.55,
    'medium':        0.30,
    'large':         0.11,
    'multinational': 0.04,
}

# Fuerza laboral total (ILO KILM 2023) — usada como base de población cuando
# no hay usuarios reales en BD para ese país. Da escala correcta al mercado:
# CN=800M trabajadores ≠ NO=2.8M, independiente de usuarios registrados.
_ILO_LABOR_FORCE: dict[str, int] = {
    'CN': 800_000_000, 'IN': 560_000_000, 'US': 168_000_000,
    'ID': 140_000_000, 'BR': 100_000_000, 'RU':  68_000_000,
    'VN':  55_000_000, 'MX':  55_000_000, 'BD':  72_000_000,
    'NG':  63_000_000, 'JP':  67_000_000, 'PH':  48_000_000,
    'TH':  38_000_000, 'EG':  32_000_000, 'GB':  32_000_000,
    'KR':  27_000_000, 'CO':  22_000_000, 'DE':  42_000_000,
    'TR':  31_000_000, 'ZA':  22_000_000, 'AR':  19_000_000,
    'CA':  19_000_000, 'ES':  21_000_000, 'UA':  18_000_000,
    'PE':  17_000_000, 'PL':  17_000_000, 'FR':  26_000_000,
    'AU':  13_000_000, 'SA':  12_000_000, 'TW':  11_000_000,
    'MY':  15_000_000, 'NL':   9_200_000, 'CL':   9_000_000,
    'KZ':   8_500_000, 'RO':   8_400_000, 'EC':   7_500_000,
    'AE':   5_000_000, 'CH':   4_600_000, 'HK':   3_800_000,
    'SG':   3_500_000, 'NO':   2_800_000, 'SK':   2_800_000,
    'IL':   4_200_000, 'AT':   4_400_000, 'PT':   4_800_000,
    'BE':   4_900_000, 'FI':   2_600_000, 'SE':   5_500_000,
    'DK':   3_000_000, 'CZ':   5_300_000, 'HU':   4_600_000,
    'QA':   2_100_000, 'HR':   1_700_000, 'GR':   4_100_000,
}

# HNWIs (patrimonio neto > $1M USD) por país — Capgemini World Wealth Report 2023
# Para archetype ultra_premium (Porsche/Rolex): el comprador es patrimonial,
# no asalariado. Un ejecutivo con $20K/mes no compra un Porsche de $200K de sueldo.
# Lo compra quien tiene $2M+ en activos. Fuente: Capgemini WWR 2023 + Credit Suisse
# Global Wealth Report 2023.
_HNWI: dict[str, int] = {
    'US': 5_540_000, 'JP': 3_440_000, 'GB': 2_525_000, 'FR': 2_786_000,
    'DE': 1_468_000, 'CA': 1_248_000, 'AU': 1_155_000, 'CN': 1_082_000,
    'CH':   770_000, 'IT':   726_000, 'KR':   560_000, 'NL':   450_000,
    'SE':   380_000, 'ES':   370_000, 'NO':   360_000, 'DK':   340_000,
    'SG':   320_000, 'HK':   310_000, 'BE':   270_000, 'AT':   260_000,
    'TW':   240_000, 'FI':   220_000, 'IE':   200_000, 'PT':   180_000,
    'IL':   170_000, 'AE':   160_000, 'MX':   202_000, 'BR':   340_000,
    'RU':   408_000, 'IN':   330_000, 'ZA':   100_000, 'SA':   130_000,
    'QA':    90_000, 'KW':    75_000, 'CL':    45_000, 'CO':    42_000,
    'AR':    35_000, 'TH':   120_000, 'MY':    85_000, 'ID':   170_000,
    'PE':    18_000, 'EC':     8_000, 'BD':    12_000, 'NG':    25_000,
    'PH':    50_000, 'VN':    28_000, 'TR':    96_000, 'CZ':    75_000,
    'PL':    80_000, 'HU':    35_000, 'RO':    22_000, 'GR':    50_000,
    'KZ':    18_000, 'UA':    22_000, 'HR':    12_000, 'SK':    18_000,
}

# Fallback PPP mediana mundial si país no está en occupation_salary (ILOSTAT 2023)
_FALLBACK_PPP: dict[int, float] = {
    1: 4_200, 2: 2_800, 3: 1_900,
    4: 1_300, 5: 1_100, 6: 950,
    7: 1_300, 8: 1_400, 9: 780,
}


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def p_income_above(mu_ppp: float, sigma: float, threshold: float) -> float:
    """P(ingreso ≥ threshold) con distribución log-normal(mu, sigma)."""
    if threshold <= 0:
        return 1.0
    if mu_ppp <= 0 or sigma <= 0:
        return 1.0 if mu_ppp >= threshold else 0.0
    z = (math.log(threshold) - math.log(mu_ppp)) / sigma
    return 1.0 - _normal_cdf(z)


def _get_country_wages(db, country_iso: str) -> dict[int, float]:
    """Retorna mediana PPP USD/mes por ISCO 1-9 para un país."""
    try:
        rows = db.execute(text("""
            SELECT isco_group,
                   COALESCE(median_monthly_ppp_usd, median_monthly_usd) as ppp
            FROM occupation_salary
            WHERE country_iso = :cc AND isco_group BETWEEN 1 AND 9
              AND COALESCE(median_monthly_ppp_usd, median_monthly_usd) > 0
        """), {'cc': country_iso}).fetchall()
        if rows:
            return {int(r[0]): float(r[1]) for r in rows}

        # Fallback → ilo_wages
        rows = db.execute(text("""
            SELECT isco_group, COALESCE(monthly_ppp_usd, monthly_usd) as ppp
            FROM ilo_wages
            WHERE country_iso2 = :cc AND monthly_usd > 0
        """), {'cc': country_iso}).fetchall()
        if rows:
            return {int(r[0]): float(r[1]) for r in rows if r[1]}
    except Exception:
        pass
    return {}


def _mu_for_isco_bucket(country_iso: str, isco: int, bucket: str,
                         national_wages: dict[int, float]) -> float:
    """
    Media log-normal para un segmento (país, ISCO, tamaño empresa).
    Buckets: 'small' | 'medium' | 'large' | 'multinational'
    ISCO 1 multinational: usa _CEO_PPP_MULTINATIONAL (Falabella, CEMEX, Vale…)
    ISCO 1 large/medium/small: usa _CEO_PPP por país.
    ISCO 2-9: escala mediana nacional con _SIZE_MULT_BY_ISCO.
    """
    if isco == 1:
        if bucket == 'multinational':
            mn = _CEO_PPP_MULTINATIONAL.get(country_iso)
            if mn:
                return float(mn)
            # Fallback: 3× large company del mismo país
            ceo = _CEO_PPP.get(country_iso, {})
            return float(ceo.get('large', _FALLBACK_PPP[1])) * 3.0

        ceo = _CEO_PPP.get(country_iso, {})
        if ceo:
            return float(ceo.get(bucket, ceo.get('medium', 4_200)))
        nat   = national_wages.get(1, _FALLBACK_PPP[1])
        ratio = {'large': 5.5, 'medium': 1.0, 'small': 0.15}.get(bucket, 1.0)
        return nat * ratio

    # ISCO 2-9
    nat  = national_wages.get(isco, _FALLBACK_PPP.get(isco, 1_000))
    mult = _SIZE_MULT_BY_ISCO.get((bucket, isco), 1.0)
    return nat * mult


def _normalized_isco_weights(isco_groups: list[int]) -> dict[int, float]:
    """Pesos de empleo normalizados al subconjunto ISCO del archetype."""
    raw = {i: _ISCO_EMPLOYMENT_WEIGHTS.get(i, 0.1) for i in isco_groups}
    total = sum(raw.values())
    if total <= 0:
        return {i: 1.0 / len(isco_groups) for i in isco_groups}
    return {i: w / total for i, w in raw.items()}


def _expected_qualified(
    user_count: int,
    country_iso: str,
    national_wages: dict[int, float],
    size_buckets: list[str],
    min_income_ppp: float,
    isco_groups: list[int],          # del archetype
) -> float:
    """Audiencia calificada esperada = users × Σ_isco(w_isco × P(ingreso ≥ min))."""
    if user_count == 0:
        return 0.0
    if min_income_ppp <= 0:
        return float(user_count)

    isco_weights = _normalized_isco_weights(isco_groups)
    total_prob = 0.0

    for isco, w in isco_weights.items():
        # Promedio ponderado entre buckets por distribución real de empleo
        # (multinational = 4%, no 25% — evita sobre-representar CEOs de Nasdaq)
        bucket_wsum = 0.0
        prob_wsum   = 0.0
        for bucket in size_buckets:
            mu    = _mu_for_isco_bucket(country_iso, isco, bucket, national_wages)
            sigma = _SIGMA.get((bucket, isco), 0.30)
            bw    = _BUCKET_WEIGHTS.get(bucket, 0.25)
            prob_wsum   += bw * p_income_above(mu, sigma, min_income_ppp)
            bucket_wsum += bw

        avg_prob = prob_wsum / bucket_wsum if bucket_wsum > 0 else 0.0
        total_prob += w * avg_prob

    return user_count * total_prob


def optimize_budget(
    db,
    countries: list[str],
    age_segments: list[dict],       # [{"min":18,"max":35,"pct":50}, ...]
    se_tiers: list[str],            # ['A','B','C','D'] — vacío = todos
    company_sizes: list[str],       # ['small','medium','large'] — vacío = todos
    min_income_ppp: float,          # umbral PPP USD/mes (0 = sin restricción)
    budget_usd: float,
    archetype: str = 'universal',   # del dict ARCHETYPES
) -> dict:
    """
    Calcula la distribución óptima del presupuesto entre segmentos.
    Retorna lista de segmentos con pct y budget_usd recomendados.
    """
    if not countries:
        return {'error': 'No hay países seleccionados'}

    # 'multinational' siempre incluido cuando no hay filtro — representa 3-5% de
    # la fuerza laboral en países con multinationales pero con pay muy superior.
    size_buckets = company_sizes if company_sizes else ['small', 'medium', 'large', 'multinational']
    isco_groups  = ARCHETYPES.get(archetype, ARCHETYPES['universal'])

    if not age_segments:
        age_segments = [{'min': 13, 'max': 99, 'label': 'Todas las edades'}]

    tiers_set = set(se_tiers) if se_tiers else {'A', 'B', 'C', 'D', 'E'}

    # ── ultra_premium: usa HNWI patrimonial (Perplexity BD) no ingreso mensual ──
    # Un Porsche vale $150-300K — no se compra de sueldo, se compra de patrimonio.
    # Perplexity calculó la distribución real usando HNWI > $1M (Capgemini WWR 2023).
    if archetype == 'ultra_premium':
        hnwi_rows = {}
        try:
            rows = db.execute(text("""
                SELECT country_iso, budget_pct FROM perplexity_budget_benchmarks
                WHERE brand = 'porsche_rolex' AND country_iso = ANY(:ccs)
            """), {'ccs': countries}).fetchall()
            hnwi_rows = {r[0]: float(r[1]) for r in rows}
        except Exception:
            pass

        if hnwi_rows:
            # BD tiene los datos Perplexity — usarlos directamente
            total_pct_covered = sum(hnwi_rows.values())
            # Normalizar al subconjunto de países solicitados
            total_q = sum(hnwi_rows.values())
            segs_out = []
            for cc in countries:
                pct_raw = hnwi_rows.get(cc, 0.0)
                pct = round(pct_raw / total_q * 100, 1) if total_q > 0 else 0.0
                hnwi = _HNWI.get(cc, 0)
                segs_out.append({
                    'country':    cc,
                    'label':      f"{cc} — Todas las edades",
                    'users_real': 0,
                    'qualified':  hnwi,
                    'pct':        pct,
                    'budget_usd': round(budget_usd * pct / 100, 2),
                    'model_note': 'HNWI_wealth_gt_1M_USD (Perplexity Capgemini 2023)',
                })
            return {
                'segments':        segs_out,
                'total_qualified': sum(s['qualified'] for s in segs_out),
                'budget_usd':      budget_usd,
                'archetype':       archetype,
                'archetype_label': 'Ultra-premium (HNWI patrimonio > $1M — Porsche/Rolex)',
                'isco_groups':     [1],
                'optimization':    'hnwi_wealth_perplexity',
                'model_version':   'v2 — Perplexity 2026-07-31 HNWI Capgemini WWR 2023',
                'note': (
                    'E1 Ultra-premium usa riqueza patrimonial (HNWI > $1M net worth), '
                    'no ingreso mensual. Fuente: Capgemini World Wealth Report 2023 '
                    'vía Perplexity. BMW/Mercedes (E2) sí usa ingreso ejecutivo ISCO.'
                ),
            }
        # Sin datos en BD: fallback a _HNWI local
        hnwi_rows = {cc: float(_HNWI.get(cc, 1)) for cc in countries}
        total_q = sum(hnwi_rows.values())
        segs_out = []
        for cc in countries:
            pct = round(hnwi_rows[cc] / total_q * 100, 1) if total_q > 0 else 0.0
            segs_out.append({
                'country': cc, 'label': f"{cc} — Todas las edades",
                'users_real': 0, 'qualified': int(hnwi_rows[cc]),
                'pct': pct, 'budget_usd': round(budget_usd * pct / 100, 2),
                'model_note': 'HNWI_fallback_Capgemini2023',
            })
        return {
            'segments': segs_out, 'total_qualified': int(total_q),
            'budget_usd': budget_usd, 'archetype': archetype,
            'archetype_label': 'Ultra-premium (HNWI fallback local)',
            'optimization': 'hnwi_wealth_local', 'isco_groups': [1],
            'model_version': 'v2 — HNWI Capgemini WWR 2023 (local)',
            'note': 'HNWI local — importar perplexity_budget_benchmarks para mayor precisión.',
        }

    segments = []

    for cc in countries:
        wages = _get_country_wages(db, cc)

        for seg in age_segments:
            age_min   = seg.get('min', 13)
            age_max   = seg.get('max', 99)
            label_age = seg.get('label') or f"{age_min}-{age_max} años"

            # Conteo real de usuarios en DB
            try:
                use_tier_filter = tiers_set not in ({'A','B','C','D','E'}, set())
                q_str = """
                    SELECT COUNT(*) FROM users
                    WHERE country = :cc
                      AND age BETWEEN :amin AND :amax
                      AND se_tier IS NOT NULL
                """
                params: dict = {'cc': cc, 'amin': age_min, 'amax': age_max}
                if use_tier_filter:
                    q_str += " AND se_tier = ANY(:tiers)"
                    params['tiers'] = list(tiers_set)
                row = db.execute(text(q_str), params).fetchone()
                user_count = int(row[0]) if row else 0
            except Exception:
                user_count = 0

            # Cuando no hay usuarios reales, usa fuerza laboral ILO como base de
            # población. Da la escala correcta al mercado: CN=800M ≠ NO=2.8M.
            # Sin esto, todos los países sin usuarios obtienen 1 usuario → distribución
            # uniforme sin importar el tamaño real del mercado.
            if user_count == 0:
                user_count = _ILO_LABOR_FORCE.get(cc, 100_000)

            qualified = _expected_qualified(
                user_count=user_count,
                country_iso=cc,
                national_wages=wages,
                size_buckets=size_buckets,
                min_income_ppp=min_income_ppp,
                isco_groups=isco_groups,
            )

            segments.append({
                'country':    cc,
                'age_min':    age_min,
                'age_max':    age_max,
                'label':      f"{cc} — {label_age}",
                'users_real': user_count,
                'qualified':  round(qualified, 1),
                'pct':        0.0,
                'budget_usd': 0.0,
            })

    # ── Asignación proporcional ───────────────────────────────────────────────
    total_q = sum(s['qualified'] for s in segments)

    if total_q <= 0:
        eq = round(100.0 / len(segments), 1) if segments else 0
        for s in segments:
            s['pct']        = eq
            s['budget_usd'] = round(budget_usd * eq / 100, 2)
        return {
            'segments': segments, 'total_qualified': 0, 'budget_usd': budget_usd,
            'note': 'Sin usuarios suficientes — distribución uniforme.',
            'optimization': 'uniform_fallback',
            'archetype': archetype,
        }

    for s in segments:
        s['pct']        = round(s['qualified'] / total_q * 100, 1)
        s['budget_usd'] = round(budget_usd * s['pct'] / 100, 2)

    # Corrección de redondeo para que sume 100%
    diff = round(100.0 - sum(s['pct'] for s in segments), 1)
    if segments and diff != 0:
        segments[0]['pct']        = round(segments[0]['pct'] + diff, 1)
        segments[0]['budget_usd'] = round(budget_usd * segments[0]['pct'] / 100, 2)

    archetype_labels = {
        'ultra_premium': 'Ultra-premium (ISCO 1 — directivos)',
        'premium':       'Premium (ISCO 1-5 — profesionales y ejecutivos)',
        'mid_premium':   'Medio-premium (ISCO 1-5,7,8 — clase media profesional)',
        'mass_market':   'Masivo (ISCO 4-9 — clase media y trabajadores)',
        'universal':     'Universal (todos los segmentos)',
    }

    return {
        'segments':        segments,
        'total_qualified': round(total_q, 0),
        'budget_usd':      budget_usd,
        'archetype':       archetype,
        'archetype_label': archetype_labels.get(archetype, archetype),
        'isco_groups':     isco_groups,
        'optimization':    'proportional_to_expected_qualified_audience',
        'model_version':   'v2 — Perplexity 2026-07-31 + JC sigma 2026-08-01',
        'note': (
            f"Audiencia calificada: {int(total_q):,} (fuerza laboral ILO × P(ingreso ≥ umbral)). "
            f"Archetype: {archetype_labels.get(archetype, archetype)}. "
            f"Pesos ISCO: empleo real (ILO KILM 2023). "
            f"ISCO 1: CEO PPP por tamaño empresa (Perplexity Tabla 1 + multinational JC 2026)."
        ),
    }
