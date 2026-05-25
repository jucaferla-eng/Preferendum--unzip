"""
marketer_table_v2.py
====================
PREFERENDUM - Tabla del Marketer con Reglas de Targeting Global

LOGICA DE LAS DOS REGLAS:

  Regla 1 — Paises ricos (GNI per capita > umbral_pais):
    Entrar en TODAS las comunas del pais.
    El pais completo es target.

  Regla 2 — Paises en desarrollo (GNI per capita < umbral_pais):
    Entrar SOLO en comunas donde el proxy de ingreso
    supera el umbral_comuna definido por el marketer.
    Solo la elite local es target.

EJEMPLO ROLEX:
  umbral_pais   = $30,000 GNI PPP
  umbral_comuna = $4,000 USD/mes ingreso estimado (indice m2 > 85)

  Noruega  ($66k) → todas las comunas
  Chile    ($24k) → solo Las Condes, Vitacura, Lo Barnechea
  Brasil   ($14k) → solo Jardins, Leblon, Itaim Bibi
  Nigeria  ($5k)  → solo Ikoyi, Victoria Island

EJEMPLO APPLE:
  umbral_pais   = $10,000 GNI PPP
  umbral_comuna = top 40% de ingresos (indice m2 > 55)

  USA      ($65k) → todas las comunas
  Chile    ($24k) → Las Condes, Providencia, Nunoa, La Florida...
  Brasil   ($14k) → Jardins, Moema, Pinheiros, Copacabana...
  India    ($7k)  → solo Bandra, Juhu, Worli...

En memoria de Jose Ignacio Fernandez (1989-2024)
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


# ══════════════════════════════════════════════════════════════
# GNI PER CAPITA PPP (USD 2023) — FMI / UNDP / World Bank
# Fuente: https://data.worldbank.org/indicator/NY.GNP.PCAP.PP.CD
# ══════════════════════════════════════════════════════════════

GNI_PER_CAPITA = {
    # Tier 1 — Premium (> $40,000)
    "NO": 66494, "CH": 72000, "US": 64765, "DK": 58662,
    "NL": 57707, "DE": 54534, "SE": 54508, "AU": 48085,
    "CA": 48527, "AT": 55000, "FI": 51000, "IE": 89000,
    "SG": 88000, "HK": 62000, "GB": 45225, "FR": 43518,
    "BE": 52000, "JP": 42274, "KR": 44501, "SA": 45653,
    "AE": 69000, "NZ": 42000, "IL": 42000, "IT": 38985,
    "ES": 40340, "PT": 32000,
    # Tier 2 — Mid Market ($10,000 - $40,000)
    "CL": 24013, "AR": 22443, "TR": 27663, "MX": 19311,
    "BR": 14307, "RU": 27000, "MA": 9500,  "ZA": 13109,
    "TH": 17781, "MY": 28000, "CN": 17000, "PL": 33000,
    "CZ": 41000, "HU": 32000, "RO": 28000, "GR": 28000,
    "HR": 27000, "BG": 22000, "RS": 18000, "UA": 13000,
    "CO": 14257, "PE": 12252, "EC": 11000, "DO": 17000,
    "CR": 20000, "PA": 27000, "UY": 20000, "PY": 12000,
    "BO": 8500,  "GT": 8000,
    # Tier 3 — Growth ($3,000 - $10,000)
    "ID": 12222, "PH": 9539,  "VN": 7866,  "IN": 6951,
    "EG": 12000, "MA": 8000,  "DZ": 11000, "TN": 10000,
    "NG": 5240,  "GH": 5500,  "KE": 4600,  "TZ": 2800,
    "ET": 2200,  "SN": 3200,  "CI": 4200,  "CM": 3500,
    "PK": 5500,  "BD": 6500,  "LK": 12000, "NP": 3500,
    "KH": 4200,  "MM": 4000,  "LA": 7000,
    # Tier 4 — Volume (< $3,000)
    "MZ": 1200,  "MG": 1600,  "ML": 2100,  "BF": 2100,
    "NE": 1300,  "TD": 1500,  "SD": 2000,  "YE": 1700,
    "AF": 1500,  "HT": 2700,
    # Default
    "default": 10000,
}


def get_gni(country: str) -> int:
    return GNI_PER_CAPITA.get(country, GNI_PER_CAPITA["default"])


def get_country_tier(country: str) -> str:
    gni = get_gni(country)
    if gni >= 40000: return "premium"
    if gni >= 10000: return "mid_market"
    if gni >= 3000:  return "growth"
    return "volume"


# ══════════════════════════════════════════════════════════════
# INGRESO ESTIMADO POR INDICE M2
# La cadena logica:
#   arriendo = dividendo del propietario
#   banco exige: dividendo <= 25% del ingreso
#   → ingreso = 4 × arriendo
#   → indice m2 alto = barrio de alto ingreso
#
# Conversion: indice 0-100 → ingreso estimado USD/mes
# Basado en pais (el mismo indice 80 vale distinto en Noruega que en Nigeria)
# ══════════════════════════════════════════════════════════════

def index_to_income_usd(index: int, country: str) -> float:
    """
    Converts commune index (0-100) to estimated monthly income USD.

    Formula:
      max_income = GNI_per_capita / 12 × premium_multiplier
      income = max_income × (index / 100) ^ 0.7

    The 0.7 exponent compresses the curve slightly —
    even low-index communes have some income.
    """
    gni_monthly = get_gni(country) / 12
    # Premium multiplier: top commune is ~3x the national average
    max_income = gni_monthly * 3.5
    if index == 0:
        return gni_monthly * 0.2  # even poorest areas have some income
    income = max_income * ((index / 100) ** 0.7)
    return round(income, 0)


def income_to_index_threshold(income_usd: float, country: str) -> int:
    """
    Reverse: given target income in USD, what minimum index do we need?
    Used by the optimizer to find which communes qualify.
    """
    gni_monthly = get_gni(country) / 12
    max_income = gni_monthly * 3.5
    if max_income == 0:
        return 100
    ratio = income_usd / max_income
    # Inverse of (index/100)^0.7
    index = (ratio ** (1/0.7)) * 100
    return min(100, max(0, int(round(index))))


# ══════════════════════════════════════════════════════════════
# MARKETER TABLE V2
# ══════════════════════════════════════════════════════════════

class ObjetivoCampana(str, Enum):
    ADQUISICION = "adquisicion"
    AWARENESS   = "awareness"
    RETENCION   = "retencion"
    CONVERSION  = "conversion"
    VALIDACION  = "validacion_mercado"


class Prioridad(str, Enum):
    ALTA  = "alta"
    MEDIA = "media"
    BAJA  = "baja"


class TipoAudiencia(str, Enum):
    ESTUDIANTES   = "estudiantes"
    PROFESIONALES = "profesionales"
    FAMILIAS      = "familias"
    JOVENES       = "jovenes"
    ADULTOS       = "adultos"
    SENIORS       = "seniors"
    TODOS         = "todos"


@dataclass
class GlobalTargetingRules:
    """
    THE CORE INNOVATION — Two-rule global targeting system.

    Rule 1 — Rich countries (GNI > umbral_pais_usd):
      Enter ALL communes in the country.
      The whole country is the target.

    Rule 2 — Developing countries (GNI < umbral_pais_usd):
      Enter ONLY communes where estimated income > umbral_ingreso_usd.
      Only the local elite is target.

    This lets Rolex say:
      "In countries above $30k GNI: reach everyone.
       In countries below $30k GNI: reach only people
       earning more than $4,000/month."

    And lets Apple say:
      "In countries above $10k GNI: reach everyone.
       In countries below $10k GNI: reach the top 40%."
    """

    # Rule 1 threshold — countries above this: target all communes
    umbral_pais_usd: int = 10000   # GNI per capita PPP

    # Rule 2 threshold — in poorer countries, min income to target
    umbral_ingreso_usd: float = 2000  # estimated monthly income USD

    # Optional: explicit country list (overrides rules if set)
    paises_incluidos: List[str] = field(default_factory=list)   # [] = use rules
    paises_excluidos: List[str] = field(default_factory=list)   # always exclude

    def evaluate_country(self, country: str) -> dict:
        """
        Determine targeting strategy for a specific country.

        Returns:
          {
            'enters': bool,
            'strategy': 'all_communes' | 'elite_only' | 'excluded',
            'min_index': int,   # minimum commune index to target
            'min_income': float, # minimum estimated income USD
            'gni': int,
            'reason': str
          }
        """
        # Explicit exclusion
        if country in self.paises_excluidos:
            return {
                'enters': False,
                'strategy': 'excluded',
                'min_index': 100,
                'min_income': 0,
                'gni': get_gni(country),
                'reason': f'{country} explicitly excluded'
            }

        # Explicit inclusion list
        if self.paises_incluidos and country not in self.paises_incluidos:
            return {
                'enters': False,
                'strategy': 'excluded',
                'min_index': 100,
                'min_income': 0,
                'gni': get_gni(country),
                'reason': f'{country} not in included list'
            }

        gni = get_gni(country)

        # Rule 1: Rich country — all communes
        if gni >= self.umbral_pais_usd:
            return {
                'enters': True,
                'strategy': 'all_communes',
                'min_index': 0,
                'min_income': 0,
                'gni': gni,
                'reason': f'GNI ${gni:,} >= threshold ${self.umbral_pais_usd:,} → all communes'
            }

        # Rule 2: Developing country — elite only
        min_index = income_to_index_threshold(self.umbral_ingreso_usd, country)
        return {
            'enters': True,
            'strategy': 'elite_only',
            'min_index': min_index,
            'min_income': self.umbral_ingreso_usd,
            'gni': gni,
            'reason': (
                f'GNI ${gni:,} < threshold ${self.umbral_pais_usd:,} → '
                f'elite only (index >= {min_index}, '
                f'income >= ${self.umbral_ingreso_usd:,.0f}/month)'
            )
        }


@dataclass
class MarketerTable:
    """
    Complete marketer campaign definition.
    Includes the dual-rule global targeting system.
    """

    # Identity
    campaign_id:    int
    brand_name:     str
    campaign_title: str
    objetivo:       ObjetivoCampana

    # GLOBAL TARGETING RULES — the core innovation
    global_rules:   GlobalTargetingRules = field(
        default_factory=GlobalTargetingRules
    )

    # Demographic
    edad_min:       int = 18
    edad_max:       int = 99
    gender:         str = "todos"

    # Audience profile
    tipo_audiencia: List[TipoAudiencia] = field(
        default_factory=lambda: [TipoAudiencia.TODOS]
    )

    # Content
    debate_categorias:   List[str] = field(default_factory=list)
    categorias_excluidas:List[str] = field(default_factory=list)
    marcas_excluidas:    List[str] = field(default_factory=list)

    # Budget
    presupuesto_total: float   = 0.0
    presupuesto_usado: float   = 0.0
    costo_por_imp:     float   = 0.02
    daily_cap:         float   = 0.0

    # Status
    prioridad: Prioridad = Prioridad.MEDIA
    activa:    bool      = True

    # Creative
    creative_url: Optional[str] = None
    cta_url:      Optional[str] = None

    # Reward (Nike loop)
    discount_pct:  Optional[int] = None
    discount_code: Optional[str] = None
    store_url:     Optional[str] = None

    @property
    def presupuesto_disponible(self) -> float:
        return round(self.presupuesto_total - self.presupuesto_usado, 2)

    @property
    def is_budget_ok(self) -> bool:
        return self.presupuesto_disponible > self.costo_por_imp

    def targeting_for_country(self, country: str) -> dict:
        """Get targeting strategy for a specific country."""
        return self.global_rules.evaluate_country(country)

    def summary(self) -> dict:
        return {
            'campaign_id':      self.campaign_id,
            'brand':            self.brand_name,
            'objetivo':         self.objetivo.value,
            'umbral_pais':      f"GNI > ${self.global_rules.umbral_pais_usd:,}",
            'umbral_ingreso':   f">${self.global_rules.umbral_ingreso_usd:,.0f}/mes en paises pobres",
            'edad':             f'{self.edad_min}-{self.edad_max}',
            'gender':           self.gender,
            'audiencia':        [t.value for t in self.tipo_audiencia],
            'presupuesto':      self.presupuesto_total,
            'disponible':       self.presupuesto_disponible,
            'prioridad':        self.prioridad.value,
        }


# ══════════════════════════════════════════════════════════════
# EJEMPLOS DE CAMPANAS
# ══════════════════════════════════════════════════════════════

EXAMPLE_CAMPAIGNS = {

    "rolex": MarketerTable(
        campaign_id=1,
        brand_name="Rolex",
        campaign_title="Oyster Perpetual 2026",
        objetivo=ObjetivoCampana.AWARENESS,
        global_rules=GlobalTargetingRules(
            umbral_pais_usd=30000,      # Rule 1: paises > $30k → todas las comunas
            umbral_ingreso_usd=8000,    # Rule 2: paises < $30k → solo > $8,000/mes
            paises_excluidos=["KP","CU","IR","SY"],
        ),
        edad_min=30, edad_max=70,
        gender="todos",
        tipo_audiencia=[TipoAudiencia.PROFESIONALES, TipoAudiencia.SENIORS],
        debate_categorias=["cultura","economia","lifestyle","deporte","lujo"],
        categorias_excluidas=["politica","religion","militar"],
        presupuesto_total=50000.0,
        costo_por_imp=0.05,
        prioridad=Prioridad.ALTA,
    ),

    "apple": MarketerTable(
        campaign_id=2,
        brand_name="Apple",
        campaign_title="iPhone 17 — disponible ahora",
        objetivo=ObjetivoCampana.CONVERSION,
        global_rules=GlobalTargetingRules(
            umbral_pais_usd=10000,      # Rule 1: paises > $10k → todas las comunas
            umbral_ingreso_usd=2500,    # Rule 2: paises < $10k → solo > $2,500/mes
            paises_excluidos=["KP","CU","IR"],
        ),
        edad_min=18, edad_max=55,
        gender="todos",
        tipo_audiencia=[TipoAudiencia.PROFESIONALES, TipoAudiencia.JOVENES],
        debate_categorias=["tecnologia","cultura","economia","educacion"],
        categorias_excluidas=["politica","religion"],
        marcas_excluidas=["Samsung","Huawei","Xiaomi"],
        presupuesto_total=100000.0,
        costo_por_imp=0.03,
        prioridad=Prioridad.ALTA,
        discount_pct=10,
    ),

    "nike": MarketerTable(
        campaign_id=3,
        brand_name="Nike",
        campaign_title="Cual zapatilla prefieres para 2026?",
        objetivo=ObjetivoCampana.VALIDACION,
        global_rules=GlobalTargetingRules(
            umbral_pais_usd=8000,       # Rule 1: paises > $8k → todas las comunas
            umbral_ingreso_usd=1000,    # Rule 2: paises < $8k → solo > $1,000/mes
        ),
        edad_min=16, edad_max=45,
        gender="todos",
        tipo_audiencia=[TipoAudiencia.JOVENES, TipoAudiencia.ESTUDIANTES],
        debate_categorias=["deporte","cultura","educacion"],
        categorias_excluidas=["politica","religion","militar"],
        marcas_excluidas=["Adidas","Puma","New Balance"],
        presupuesto_total=30000.0,
        costo_por_imp=0.02,
        prioridad=Prioridad.ALTA,
        discount_pct=20,
        discount_code="CSV",
    ),

    "banco_bci": MarketerTable(
        campaign_id=4,
        brand_name="Banco BCI",
        campaign_title="Credito universitario — tasa preferencial",
        objetivo=ObjetivoCampana.ADQUISICION,
        global_rules=GlobalTargetingRules(
            umbral_pais_usd=999999,     # Rule 1: umbral muy alto → Rule 2 siempre aplica
            umbral_ingreso_usd=1500,    # solo comunas con ingreso > $1,500/mes
            paises_incluidos=["CL"],    # solo Chile
        ),
        edad_min=18, edad_max=30,
        gender="todos",
        tipo_audiencia=[TipoAudiencia.ESTUDIANTES],
        debate_categorias=["educacion","economia","gov"],
        categorias_excluidas=["politica","religion"],
        marcas_excluidas=["Santander","Itau","Scotiabank"],
        presupuesto_total=5000.0,
        costo_por_imp=0.02,
        prioridad=Prioridad.ALTA,
    ),

    "samsung": MarketerTable(
        campaign_id=5,
        brand_name="Samsung Galaxy",
        campaign_title="Galaxy S26 — disponible ahora",
        objetivo=ObjetivoCampana.AWARENESS,
        global_rules=GlobalTargetingRules(
            umbral_pais_usd=5000,       # Rule 1: paises > $5k → todas las comunas
            umbral_ingreso_usd=500,     # Rule 2: paises < $5k → solo > $500/mes
        ),
        edad_min=18, edad_max=50,
        gender="todos",
        tipo_audiencia=[TipoAudiencia.TODOS],
        debate_categorias=[],           # todas las categorias
        categorias_excluidas=["politica"],
        marcas_excluidas=["Apple","Huawei"],
        presupuesto_total=200000.0,
        costo_por_imp=0.02,
        prioridad=Prioridad.MEDIA,
    ),
}
