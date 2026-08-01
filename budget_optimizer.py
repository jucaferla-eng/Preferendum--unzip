from __future__ import annotations
"""
budget_optimizer.py — Motor de Optimización de Presupuesto
===========================================================
Dado los parámetros de una campaña (países, edad, tamaño empresa, ingreso mínimo),
calcula la distribución óptima del presupuesto entre segmentos.

Modelo estadístico (JC Fernandez Lazo, 2026-08-01):
  Cada cargo (ISCO) × tamaño empresa sigue distribución log-normal.
  La media es el salario PPP del sistema (occupation_salary/ilo_wages).
  El sigma varía: grande en cargos altos de empresas grandes,
  pequeño en cargos bajos de empresas pequeñas.

Salida: {segmento: pct_optimo} proporcional a audiencia_calificada_esperada.
"""

import math
from sqlalchemy import text

# ── Sigmas log-normal por (bucket_empresa, isco_group) ───────────────────────
# Fuente: modelo JC (dibujos 2026-08-01). σ ≈ 0.8 para managers empresa grande.
# Empresa grande → wider; empresa pequeña → compressed.
_SIGMA: dict[tuple[str, int], float] = {
    # Empresa grande (500+ empleados)
    ('large', 1): 0.80, ('large', 2): 0.65, ('large', 3): 0.55,
    ('large', 4): 0.45, ('large', 5): 0.40, ('large', 6): 0.35,
    ('large', 7): 0.42, ('large', 8): 0.42, ('large', 9): 0.28,
    # Empresa mediana (50-500)
    ('medium', 1): 0.52, ('medium', 2): 0.42, ('medium', 3): 0.36,
    ('medium', 4): 0.30, ('medium', 5): 0.27, ('medium', 6): 0.24,
    ('medium', 7): 0.28, ('medium', 8): 0.28, ('medium', 9): 0.20,
    # Empresa pequeña (<50)
    ('small', 1): 0.32, ('small', 2): 0.26, ('small', 3): 0.22,
    ('small', 4): 0.19, ('small', 5): 0.17, ('small', 6): 0.15,
    ('small', 7): 0.19, ('small', 8): 0.19, ('small', 9): 0.13,
}

# Mapeo company_size DB → bucket
_SIZE_BUCKET = {
    '1-10': 'small', '11-50': 'small',
    '51-250': 'medium',
    '251-1000': 'large', '+1000': 'large',
}

# Salarios mediana PPP (fallback si no hay dato en DB) ISCO 1-9 por bucket
# Base: promedios mundiales ILOSTAT 2023
_FALLBACK_PPP: dict[tuple[str, int], float] = {
    ('large', 1): 8000, ('large', 2): 5500, ('large', 3): 3800,
    ('large', 4): 2800, ('large', 5): 2400, ('large', 6): 2000,
    ('large', 7): 2800, ('large', 8): 3000, ('large', 9): 1800,
    ('medium', 1): 3500, ('medium', 2): 2500, ('medium', 3): 1800,
    ('medium', 4): 1300, ('medium', 5): 1100, ('medium', 6): 950,
    ('medium', 7): 1300, ('medium', 8): 1400, ('medium', 9): 850,
    ('small', 1): 1600, ('small', 2): 1200, ('small', 3): 900,
    ('small', 4): 700,  ('small', 5): 600,  ('small', 6): 520,
    ('small', 7): 680,  ('small', 8): 720,  ('small', 9): 480,
}

# Multiplicadores SIZE_MULT para pasar de mediana nacional a bucket
_SIZE_MULT = {'small': 0.45, 'medium': 1.00, 'large': 2.30}


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def p_income_above(mu_ppp: float, sigma: float, threshold: float) -> float:
    """P(ingreso ≥ threshold) con distribución log-normal(mu, sigma)."""
    if mu_ppp <= 0 or threshold <= 0:
        return 1.0 if mu_ppp >= threshold else 0.0
    if sigma <= 0:
        return 1.0 if mu_ppp >= threshold else 0.0
    mu_log  = math.log(mu_ppp)
    thr_log = math.log(threshold)
    z = (thr_log - mu_log) / sigma
    return 1.0 - _normal_cdf(z)


def _get_country_wages(db, country_iso: str) -> dict[int, float]:
    """Retorna mediana PPP USD/mes por ISCO 1-9 para un país."""
    rows = db.execute(text("""
        SELECT isco_group,
               COALESCE(median_monthly_ppp_usd, median_monthly_usd) as ppp
        FROM occupation_salary
        WHERE country_iso = :cc AND isco_group BETWEEN 1 AND 9
          AND COALESCE(median_monthly_ppp_usd, median_monthly_usd) > 0
    """), {'cc': country_iso}).fetchall()
    if rows:
        return {int(r[0]): float(r[1]) for r in rows}

    # Fallback ilo_wages
    rows = db.execute(text("""
        SELECT isco_group,
               COALESCE(monthly_ppp_usd, monthly_usd) as ppp
        FROM ilo_wages
        WHERE country_iso2 = :cc AND monthly_usd > 0
    """), {'cc': country_iso}).fetchall()
    return {int(r[0]): float(r[1]) for r in rows if r[1]}


def _expected_qualified(
    user_count: int,
    country_wages: dict[int, float],
    size_buckets: list[str],        # buckets de empresa a considerar
    min_income_ppp: float,          # umbral mínimo PPP USD/mes
    se_tiers_filter: set[str],      # tiers permitidos (vacío = todos)
    isco_weights: dict[int, float], # distribución de cargos (1-9 → weight)
) -> float:
    """Audiencia calificada esperada = Σ weight_isco × P(income ≥ min) × user_count."""
    if user_count == 0:
        return 0.0
    if min_income_ppp <= 0:
        return float(user_count)

    total_prob = 0.0
    total_weight = 0.0

    for isco in range(1, 10):
        w = isco_weights.get(isco, 1.0 / 9)
        mu_national = country_wages.get(isco, 0)

        # Promedio entre buckets de empresa seleccionados
        bucket_probs = []
        for bucket in size_buckets:
            mult = _SIZE_MULT.get(bucket, 1.0)
            mu_bucket = mu_national * mult if mu_national > 0 else _FALLBACK_PPP.get((bucket, isco), 1000)
            sigma = _SIGMA.get((bucket, isco), 0.35)
            bucket_probs.append(p_income_above(mu_bucket, sigma, min_income_ppp))

        avg_prob = sum(bucket_probs) / len(bucket_probs) if bucket_probs else 0.0
        total_prob   += w * avg_prob
        total_weight += w

    avg_p = total_prob / total_weight if total_weight else 0.0
    return user_count * avg_p


def optimize_budget(
    db,
    countries: list[str],
    age_segments: list[dict],       # [{"min":18,"max":35,"pct":50}, ...]  (de nc-age-weights)
    se_tiers: list[str],            # ['A','B','C','D']
    company_sizes: list[str],       # ['small','medium','large'] o vacío
    min_income_ppp: float,          # umbral PPP USD/mes (0 = sin restricción)
    budget_usd: float,
) -> dict:
    """
    Calcula la distribución óptima del presupuesto entre segmentos.
    Retorna lista de segmentos con pct y budget_usd recomendados.
    """
    if not countries:
        return {'error': 'No hay países seleccionados'}

    size_buckets = company_sizes if company_sizes else ['small', 'medium', 'large']

    # Distribución de cargos ISCO uniforme si no hay info específica
    isco_weights = {i: 1.0/9 for i in range(1, 10)}

    # ── Conteo real de usuarios por segmento en DB ────────────────────────────
    # Segmento = país × age_range
    segments = []

    # Si no hay age_segments definidos, usar un único bloque global
    if not age_segments:
        age_segments = [{'min': 13, 'max': 99, 'pct': 100, 'label': 'Todas las edades'}]

    tiers_set = set(se_tiers) if se_tiers else {'A','B','C','D','E'}

    for cc in countries:
        wages = _get_country_wages(db, cc)

        for seg in age_segments:
            age_min = seg.get('min', 13)
            age_max = seg.get('max', 99)
            label_age = seg.get('label') or f"{age_min}-{age_max} años"

            # Contar usuarios reales
            try:
                tier_filter = "AND se_tier = ANY(:tiers)" if tiers_set != {'A','B','C','D','E'} else ""
                q = f"""
                    SELECT COUNT(*) FROM users
                    WHERE country = :cc
                      AND age BETWEEN :amin AND :amax
                      AND se_tier IS NOT NULL
                      {tier_filter}
                """
                params: dict = {'cc': cc, 'amin': age_min, 'amax': age_max}
                if tiers_set != {'A','B','C','D','E'}:
                    params['tiers'] = list(tiers_set)
                row = db.execute(text(q), params).fetchone()
                user_count = int(row[0]) if row else 0
            except Exception:
                user_count = 0

            qualified = _expected_qualified(
                user_count=max(user_count, 1),  # mínimo 1 para no perder países con pocos usuarios
                country_wages=wages,
                size_buckets=size_buckets,
                min_income_ppp=min_income_ppp,
                se_tiers_filter=tiers_set,
                isco_weights=isco_weights,
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
        # Sin datos suficientes: distribución uniforme
        eq = round(100.0 / len(segments), 1) if segments else 0
        for s in segments:
            s['pct']        = eq
            s['budget_usd'] = round(budget_usd * eq / 100, 2)
        return {
            'segments': segments,
            'total_qualified': 0,
            'note': 'Sin datos de usuarios suficientes — distribución uniforme',
            'optimization': 'uniform_fallback',
        }

    for s in segments:
        s['pct']        = round(s['qualified'] / total_q * 100, 1)
        s['budget_usd'] = round(budget_usd * s['pct'] / 100, 2)

    # Ajustar redondeo para que sume exacto 100%
    diff = round(100.0 - sum(s['pct'] for s in segments), 1)
    if segments and diff != 0:
        segments[0]['pct'] = round(segments[0]['pct'] + diff, 1)
        segments[0]['budget_usd'] = round(budget_usd * segments[0]['pct'] / 100, 2)

    return {
        'segments':        segments,
        'total_qualified': round(total_q, 0),
        'budget_usd':      budget_usd,
        'optimization':    'proportional_to_expected_qualified_audience',
        'model':           'log-normal sigma JC 2026-08-01',
        'note':            (
            f"Audiencia calificada total estimada: {int(total_q):,} usuarios. "
            f"Presupuesto óptimo según densidad de audiencia × P(ingreso ≥ umbral)."
        ),
    }
