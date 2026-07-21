"""
commune_agent.py
================
PREFERENDUM — Agente de Optimización de Comunas

Proxy de ingreso: precio de ARRIENDO por m² en UF (no tamaño del depto)
Fuente: Portal Inmobiliario, Yapo, TocToc — datos 2025
Referencia: Vitacura = 0.40 UF/m² = índice 100
Todas las demás comunas son relativas a Vitacura.

Tiers SE:
  A  ≥ 80  — Alto ingreso         (Vitacura, Las Condes, Lo Barnechea, Providencia)
  B  55-79 — Medio-alto           (Ñuñoa, La Florida, Viña del Mar, Antofagasta)
  C  35-54 — Medio                (Maipú, Quilicura, Valparaíso, Concepción)
  D  < 35  — Popular              (La Pintana, Cerro Navia, El Bosque, San Ramón)

Actualización: anual (scheduler 2 enero). Los precios de arriendo son estables
salvo boom inmobiliario — en ese caso usar endpoint /admin/agent/update-rental-prices.

En memoria del Socio Fundador José Ignacio Fernández (1989–2024)
"""

import json
import math
from datetime import datetime

# ══════════════════════════════════════════════════════════════
# REFERENCIA: Vitacura = 0.40 UF/m² = índice 100
# Índice = (uf_m2 / 0.40) * 100
# ══════════════════════════════════════════════════════════════
REFERENCIA_UF_M2   = 0.40   # Vitacura 2025
REFERENCIA_COMMUNE = 'Vitacura'

# ══════════════════════════════════════════════════════════════
# DATOS BASE — precio arriendo UF/m² por comuna
# Fuente: Portal Inmobiliario / Yapo / TocToc 2025
# Formato: (nombre, región, uf_por_m2, población_estimada)
# ══════════════════════════════════════════════════════════════

COMUNAS_DATA = [
    # ── Región Metropolitana — Tier A (índice ≥ 80) ──────────
    ("Vitacura",         "RM", 0.40, 92000),    # índice 100 — referencia
    ("Las Condes",       "RM", 0.39, 310000),   # índice  97
    ("Lo Barnechea",     "RM", 0.38, 105000),   # índice  95 — La Dehesa, San Carlos
    ("Providencia",      "RM", 0.38, 150000),   # índice  95
    ("La Reina",         "RM", 0.32, 98000),    # índice  80

    # ── Región Metropolitana — Tier B (índice 55–79) ─────────
    ("Ñuñoa",            "RM", 0.28, 225000),   # índice  70
    ("Peñalolén",        "RM", 0.24, 240000),   # índice  60
    ("Macul",            "RM", 0.23, 130000),   # índice  57
    ("San Miguel",       "RM", 0.23, 110000),   # índice  57
    ("Huechuraba",       "RM", 0.21, 98000),    # índice  52 — mixto, baja a C
    ("Santiago",         "RM", 0.24, 520000),   # índice  60 — nuevo stock céntrico
    ("La Florida",       "RM", 0.22, 380000),   # índice  55

    # ── Región Metropolitana — Tier C (índice 35–54) ─────────
    ("Maipú",            "RM", 0.21, 620000),   # índice  52
    ("Quilicura",        "RM", 0.19, 235000),   # índice  47
    ("Estación Central", "RM", 0.19, 145000),   # índice  47
    ("Independencia",    "RM", 0.22, 105000),   # índice  55
    ("Recoleta",         "RM", 0.20, 175000),   # índice  50
    ("Cerrillos",        "RM", 0.17, 90000),    # índice  42
    ("Conchalí",         "RM", 0.17, 140000),   # índice  42
    ("Quinta Normal",    "RM", 0.18, 115000),   # índice  45
    ("Lo Prado",         "RM", 0.14, 110000),   # índice  35
    ("Pudahuel",         "RM", 0.16, 245000),   # índice  40
    ("Renca",            "RM", 0.15, 155000),   # índice  37

    # ── Región Metropolitana — Tier D (índice < 35) ──────────
    ("Lo Espejo",        "RM", 0.13, 115000),   # índice  32
    ("El Bosque",        "RM", 0.12, 185000),   # índice  30
    ("San Ramón",        "RM", 0.11, 100000),   # índice  27
    ("La Pintana",       "RM", 0.10, 225000),   # índice  25
    ("Cerro Navia",      "RM", 0.12, 145000),   # índice  30

    # ── Valparaíso ───────────────────────────────────────────
    ("Concón",           "V",  0.26, 52000),    # índice  65 — B
    ("Viña del Mar",     "V",  0.23, 390000),   # índice  57 — B
    ("Valparaíso",       "V",  0.18, 310000),   # índice  45 — C
    ("Quilpué",          "V",  0.17, 235000),   # índice  42 — C

    # ── Biobío ───────────────────────────────────────────────
    ("San Pedro de la Paz","VIII", 0.21, 135000), # índice 52 — C
    ("Concepción",       "VIII", 0.19, 245000),  # índice  47 — C
    ("Talcahuano",       "VIII", 0.16, 175000),  # índice  40 — C

    # ── Otras regiones ───────────────────────────────────────
    ("Antofagasta",      "II",  0.23, 420000),  # índice  57 — B (minería)
    ("Iquique",          "I",   0.20, 245000),  # índice  50 — C
    ("La Serena",        "IV",  0.20, 250000),  # índice  50 — C
    ("Coquimbo",         "IV",  0.17, 245000),  # índice  42 — C
    ("Rancagua",         "VI",  0.17, 245000),  # índice  42 — C
    ("Temuco",           "IX",  0.18, 360000),  # índice  45 — C
    ("Puerto Montt",     "X",   0.17, 275000),  # índice  42 — C
    ("Arica",            "XV",  0.16, 245000),  # índice  40 — C
    ("Punta Arenas",     "XII", 0.17, 145000),  # índice  42 — C
]


# ══════════════════════════════════════════════════════════════
# ÍNDICE Y TIER
# ══════════════════════════════════════════════════════════════

def uf_to_index(uf_m2: float) -> float:
    """Convierte precio UF/m² a índice relativo (Vitacura = 100)."""
    return round((uf_m2 / REFERENCIA_UF_M2) * 100, 1)

def get_se_tier(income_index: float) -> str:
    if income_index >= 80: return "A"
    if income_index >= 55: return "B"
    if income_index >= 35: return "C"
    return "D"

def get_se_description(tier: str) -> str:
    return {
        "A": "Alto — Profesionales y ejecutivos",
        "B": "Medio-alto — Clase media profesional",
        "C": "Medio — Trabajadores calificados",
        "D": "Popular — Trabajadores y estudiantes",
    }.get(tier, "")


# ══════════════════════════════════════════════════════════════
# CPM — escala con el índice de ingreso
# Benchmark: Meta/Google ARPU Q4 2024 por país/región
# CPM = CPM_base × (índice / 100) ^ 0.65
# ══════════════════════════════════════════════════════════════
CPM_BASE_CL = 8.0   # USD — CPM base para Chile (equivalente a BR premium)

def calculate_cpm(income_index: float) -> float:
    cpm = CPM_BASE_CL * (income_index / 100.0) ** 0.65
    return round(max(2.0, min(16.0, cpm)), 2)


# ══════════════════════════════════════════════════════════════
# TABLA COMPLETA
# ══════════════════════════════════════════════════════════════

def calculate_commune_table() -> list:
    communes = []
    for nombre, region, uf_m2, poblacion in COMUNAS_DATA:
        index = uf_to_index(uf_m2)
        tier  = get_se_tier(index)
        cpm   = calculate_cpm(index)
        votantes_est = int(poblacion * 0.75 * 0.35)
        communes.append({
            "nombre":         nombre,
            "region":         region,
            "uf_m2":          uf_m2,          # precio arriendo UF/m²
            "income_index":   index,           # índice relativo (Vitacura=100)
            "se_tier":        tier,
            "se_descripcion": get_se_description(tier),
            "cpm_usd":        cpm,
            "poblacion":      poblacion,
            "votantes_est":   votantes_est,
            "m2_promedio":    index,           # alias para compatibilidad con código existente
        })
    communes.sort(key=lambda x: x["income_index"], reverse=True)
    return communes


# ══════════════════════════════════════════════════════════════
# ALLOCATION DE PRESUPUESTO
# ══════════════════════════════════════════════════════════════

def allocate_budget(
    budget_usd: float,
    target_se: list = None,
    target_region: str = None,
    max_communes: int = None,
) -> dict:
    communes = calculate_commune_table()
    if target_se:
        communes = [c for c in communes if c["se_tier"] in target_se]
    if target_region:
        communes = [c for c in communes if c["region"] == target_region]
    if max_communes:
        communes = communes[:max_communes]
    if not communes:
        return {"error": "No communes match the criteria"}

    total_weight = sum(c["votantes_est"] for c in communes)
    allocation = []
    total_votantes = 0
    total_impressions = 0

    for c in communes:
        weight         = c["votantes_est"] / total_weight
        budget_commune = budget_usd * weight
        impressions    = int((budget_commune / c["cpm_usd"]) * 1000)
        votantes_alc   = min(impressions, c["votantes_est"])
        allocation.append({
            "comuna":              c["nombre"],
            "region":              c["region"],
            "se_tier":             c["se_tier"],
            "uf_m2":               c["uf_m2"],
            "income_index":        c["income_index"],
            "cpm_usd":             c["cpm_usd"],
            "presupuesto_usd":     round(budget_commune, 2),
            "presupuesto_pct":     round(weight * 100, 1),
            "impresiones_est":     impressions,
            "votantes_alcanzados": votantes_alc,
        })
        total_votantes    += votantes_alc
        total_impressions += impressions

    return {
        "budget_total_usd":      budget_usd,
        "total_communes":        len(allocation),
        "total_votantes_est":    total_votantes,
        "total_impresiones_est": total_impressions,
        "costo_por_votante_usd": round(budget_usd / total_votantes, 4) if total_votantes else 0,
        "cpm_promedio":          round(budget_usd / (total_impressions / 1000), 2) if total_impressions else 0,
        "allocation":            allocation,
        "referencia":            f"{REFERENCIA_COMMUNE} = {REFERENCIA_UF_M2} UF/m² = índice 100",
        "generated_at":          datetime.utcnow().isoformat(),
    }


# ══════════════════════════════════════════════════════════════
# DEMO
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 65)
    print("PREFERENDUM — Clasificación de Comunas por Precio Arriendo m²")
    print(f"Referencia: {REFERENCIA_COMMUNE} = {REFERENCIA_UF_M2} UF/m² = índice 100")
    print("=" * 65)

    communes = calculate_commune_table()
    print(f"\n{'Comuna':<22} {'SE':<4} {'UF/m²':<7} {'Índice':<8} {'CPM USD'}")
    print("-" * 55)
    for c in communes:
        print(f"{c['nombre']:<22} {c['se_tier']:<4} {c['uf_m2']:<7.2f} {c['income_index']:<8.1f} ${c['cpm_usd']}")

    print("\n\n💰 SIMULACIÓN: Porsche Chile — $10,000 USD (solo tier A)\n")
    result = allocate_budget(budget_usd=10000, target_se=["A"])
    print(f"  Comunas tier A:     {result['total_communes']}")
    print(f"  Votantes estimados: {result['total_votantes_est']:,}")
    print(f"  CPM promedio:       ${result['cpm_promedio']}")
    print(f"\n  ALLOCATION:\n")
    for a in result["allocation"]:
        print(f"  {a['comuna']:<22} índice {a['income_index']:<6} ${a['presupuesto_usd']:>7,.0f} → {a['votantes_alcanzados']:,} personas")

    print("\nEn memoria del Socio Fundador José Ignacio Fernández (1989–2024)")
