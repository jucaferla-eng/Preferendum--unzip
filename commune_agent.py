"""
commune_agent.py
================
PREFERENDUM — Agente de Optimización de Comunas

Este agente:
1. Recopila datos de comunas chilenas (m² promedio de vivienda)
2. Calcula el CPM por comuna según proxy de ingreso
3. Genera la tabla de allocation para el motor de ads
4. Se puede ejecutar periódicamente para mantener datos actualizados

Fuente de datos: INE Chile, SII, datos municipales públicos
En memoria del Socio Fundador José Ignacio Fernández (1989–2024)
"""

import json
import math
from datetime import datetime

# ══════════════════════════════════════════════════════════════
# DATOS BASE — Comunas Chile con m² promedio de vivienda
# Fuente: INE Censo 2017 + estimaciones SII 2023
# ══════════════════════════════════════════════════════════════

COMUNAS_DATA = [
    # (nombre, región, m2_promedio, población_estimada)
    # Región Metropolitana — Alto ingreso
    ("Vitacura",           "RM", 142, 92000),
    ("Las Condes",         "RM", 128, 310000),
    ("Lo Barnechea",       "RM", 118, 105000),
    ("Providencia",        "RM", 112, 150000),
    ("La Reina",           "RM", 108, 98000),
    ("Ñuñoa",              "RM", 92,  225000),
    ("Peñalolén",          "RM", 88,  240000),
    ("Macul",              "RM", 82,  130000),
    ("San Miguel",         "RM", 80,  110000),
    ("La Florida",         "RM", 76,  380000),
    # Región Metropolitana — Medio
    ("Santiago",           "RM", 68,  520000),
    ("Independencia",      "RM", 65,  105000),
    ("Recoleta",           "RM", 62,  175000),
    ("Quinta Normal",      "RM", 60,  115000),
    ("Renca",              "RM", 58,  155000),
    ("Lo Espejo",          "RM", 54,  115000),
    ("El Bosque",          "RM", 52,  185000),
    ("San Ramón",          "RM", 50,  100000),
    ("La Pintana",         "RM", 48,  225000),
    ("Pudahuel",           "RM", 56,  245000),
    ("Cerro Navia",        "RM", 46,  145000),
    ("Lo Prado",           "RM", 52,  110000),
    ("Cerrillos",          "RM", 60,  90000),
    ("Estación Central",   "RM", 58,  145000),
    ("Maipú",              "RM", 72,  620000),
    ("Quilicura",          "RM", 70,  235000),
    ("Huechuraba",         "RM", 74,  98000),
    ("Conchalí",           "RM", 58,  140000),
    # Otras regiones — ciudades principales
    ("Valparaíso",         "V",  62,  310000),
    ("Viña del Mar",       "V",  78,  390000),
    ("Concón",             "V",  92,  52000),
    ("Quilpué",            "V",  68,  235000),
    ("Concepción",         "VIII", 70, 245000),
    ("Talcahuano",         "VIII", 64, 175000),
    ("San Pedro de la Paz","VIII", 76, 135000),
    ("Antofagasta",        "II",  72,  420000),
    ("La Serena",          "IV",  74,  250000),
    ("Coquimbo",           "IV",  62,  245000),
    ("Rancagua",           "VI",  66,  245000),
    ("Temuco",             "IX",  68,  360000),
    ("Puerto Montt",       "X",   64,  275000),
    ("Iquique",            "I",   70,  245000),
    ("Arica",              "XV",  60,  245000),
    ("Punta Arenas",       "XII", 68,  145000),
]

# ══════════════════════════════════════════════════════════════
# MODELO DE PRICING — CPM según m² promedio
# Calibrado con benchmark Facebook/Meta ARPU Q4 2024
# ══════════════════════════════════════════════════════════════

def calculate_cpm(m2_promedio: float) -> float:
    """
    Calcula el CPM (USD) según m² promedio de vivienda.
    
    Lógica:
    - >120 m²  = SE A = CPM $12-15 (comparable a US tier 2)
    - 80-120   = SE B = CPM $7-11  (comparable a BR premium)
    - 55-80    = SE C = CPM $4-6   (comparable a MX estándar)
    - <55      = SE D = CPM $2-3   (comparable a mercado masivo)
    
    Fórmula: CPM = base_cpm * (m2 / 80) ^ 0.7
    """
    BASE_CPM = 8.0
    normalized = (m2_promedio / 80.0) ** 0.7
    cpm = BASE_CPM * normalized
    return round(max(2.0, min(16.0, cpm)), 2)


def get_se_tier(m2: float) -> str:
    if m2 >= 120: return "A"
    if m2 >= 80:  return "B"
    if m2 >= 55:  return "C"
    return "D"


def get_se_description(tier: str) -> str:
    descriptions = {
        "A": "Alto — Profesionales y ejecutivos",
        "B": "Medio-alto — Clase media profesional",
        "C": "Medio — Trabajadores calificados",
        "D": "Popular — Trabajadores y estudiantes",
    }
    return descriptions.get(tier, "")


# ══════════════════════════════════════════════════════════════
# MOTOR DE ALLOCATION
# ══════════════════════════════════════════════════════════════

def calculate_commune_table() -> list:
    """
    Genera la tabla completa de comunas con CPM y métricas.
    """
    communes = []
    for nombre, region, m2, poblacion in COMUNAS_DATA:
        cpm = calculate_cpm(m2)
        tier = get_se_tier(m2)
        # Estimación de votantes activos (penetración smartphone ~75%)
        votantes_est = int(poblacion * 0.75 * 0.35)  # 35% usa app
        communes.append({
            "nombre":          nombre,
            "region":          region,
            "m2_promedio":     m2,
            "se_tier":         tier,
            "se_descripcion":  get_se_description(tier),
            "cpm_usd":         cpm,
            "poblacion":       poblacion,
            "votantes_est":    votantes_est,
            "costo_1000_imp":  cpm,
        })
    # Sort by CPM descending
    communes.sort(key=lambda x: x["cpm_usd"], reverse=True)
    return communes


def allocate_budget(
    budget_usd: float,
    target_se: list = None,       # e.g. ["A", "B"] for premium
    target_region: str = None,    # e.g. "RM"
    max_communes: int = None,
) -> dict:
    """
    Distribuye el presupuesto del marketer entre comunas.
    
    Args:
        budget_usd:     Total en USD
        target_se:      Lista de tiers SE a incluir (None = todos)
        target_region:  Filtrar por región (None = Chile completo)
        max_communes:   Máximo de comunas (None = sin límite)
    
    Returns:
        Dict con allocation optimizada
    """
    communes = calculate_commune_table()
    
    # Filtrar
    if target_se:
        communes = [c for c in communes if c["se_tier"] in target_se]
    if target_region:
        communes = [c for c in communes if c["region"] == target_region]
    if max_communes:
        communes = communes[:max_communes]
    
    if not communes:
        return {"error": "No communes match the criteria"}
    
    # Calcular peso por votantes disponibles y CPM
    # Más presupuesto a comunas con más votantes y mayor CPM
    total_weight = sum(c["votantes_est"] for c in communes)
    
    allocation = []
    total_votantes = 0
    total_impressions = 0
    
    for c in communes:
        weight = c["votantes_est"] / total_weight
        budget_commune = budget_usd * weight
        impressions = int((budget_commune / c["cpm_usd"]) * 1000)
        votantes_alcanzados = min(impressions, c["votantes_est"])
        
        allocation.append({
            "comuna":              c["nombre"],
            "region":              c["region"],
            "se_tier":             c["se_tier"],
            "m2_promedio":         c["m2_promedio"],
            "cpm_usd":             c["cpm_usd"],
            "presupuesto_usd":     round(budget_commune, 2),
            "presupuesto_pct":     round(weight * 100, 1),
            "impresiones_est":     impressions,
            "votantes_alcanzados": votantes_alcanzados,
        })
        
        total_votantes    += votantes_alcanzados
        total_impressions += impressions
    
    costo_por_votante = round(budget_usd / total_votantes, 4) if total_votantes > 0 else 0
    
    return {
        "budget_total_usd":      budget_usd,
        "total_communes":        len(allocation),
        "total_votantes_est":    total_votantes,
        "total_impresiones_est": total_impressions,
        "costo_por_votante_usd": costo_por_votante,
        "cpm_promedio":          round(budget_usd / (total_impressions / 1000), 2) if total_impressions > 0 else 0,
        "allocation":            allocation,
        "generated_at":          datetime.utcnow().isoformat(),
    }


# ══════════════════════════════════════════════════════════════
# FASTAPI ROUTES — agregar a main.py
# ══════════════════════════════════════════════════════════════

ADS_ROUTES_CODE = '''
# ── AD OPTIMIZATION ROUTES ────────────────────────────────────

from commune_agent import calculate_commune_table, allocate_budget

class CampaignRequest(BaseModel):
    budget_usd:     float
    target_se:      list = None
    target_region:  str  = None
    debate_id:      int  = None

@app.get("/ads/communes")
def get_communes():
    """Get all communes with CPM pricing."""
    return {"communes": calculate_commune_table()}

@app.post("/ads/allocate")
def allocate_campaign(data: CampaignRequest):
    """
    Optimize budget allocation across communes.
    Called when marketer creates a campaign.
    """
    result = allocate_budget(
        budget_usd=data.budget_usd,
        target_se=data.target_se,
        target_region=data.target_region,
    )
    return result

@app.get("/ads/communes/rm")
def get_rm_communes():
    """Get Santiago Metro communes only."""
    all_c = calculate_commune_table()
    rm = [c for c in all_c if c["region"] == "RM"]
    return {"communes": rm, "region": "Región Metropolitana"}
'''

# ══════════════════════════════════════════════════════════════
# DEMO — run directly to see the output
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("PREFERENDUM — Agente de Optimización de Comunas")
    print("=" * 60)
    
    # 1. Show commune table (top 10)
    print("\n📍 TOP 10 COMUNAS POR CPM:\n")
    communes = calculate_commune_table()
    print(f"{'Comuna':<20} {'SE':<4} {'m²':<6} {'CPM':<8} {'Votantes'}")
    print("-" * 55)
    for c in communes[:10]:
        print(f"{c['nombre']:<20} {c['se_tier']:<4} {c['m2_promedio']:<6} ${c['cpm_usd']:<7} {c['votantes_est']:,}")
    
    # 2. Simulate Nike campaign $10,000
    print("\n\n💰 SIMULACIÓN: Nike Chile — $10,000 USD\n")
    result = allocate_budget(
        budget_usd=10000,
        target_se=["A", "B"],
        target_region="RM"
    )
    print(f"  Total comunas:      {result['total_communes']}")
    print(f"  Votantes estimados: {result['total_votantes_est']:,}")
    print(f"  Impresiones est.:   {result['total_impresiones_est']:,}")
    print(f"  Costo/votante:      ${result['costo_por_votante_usd']}")
    print(f"  CPM promedio:       ${result['cpm_promedio']}")
    print(f"\n  ALLOCATION:\n")
    
    for a in result["allocation"][:8]:
        print(f"  {a['comuna']:<20} SE{a['se_tier']} ${a['presupuesto_usd']:>8,.0f} ({a['presupuesto_pct']}%) → {a['votantes_alcanzados']:,} votantes")
    
    # 3. Save to JSON
    all_communes = calculate_commune_table()
    with open("communes_cpm_table.json", "w", encoding="utf-8") as f:
        json.dump(all_communes, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Tabla guardada en communes_cpm_table.json ({len(all_communes)} comunas)")
    print("\nEn memoria del Socio Fundador José Ignacio Fernández (1989–2024)")

