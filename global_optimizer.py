"""
global_optimizer.py
===================
PREFERENDUM - Optimizador Global de Presupuesto

Toma el mandato del marketer (dos reglas) y:
1. Evalua cada pais — entra o no entra, con que estrategia
2. Para los paises que entran, evalua cada comuna
3. Calcula score de matching por comuna
4. Asigna presupuesto proporcional al score
5. Reporta donde va cada dolar

MANDATO DE ROLEX:
  Paises > $30k GNI → todas las comunas
  Paises < $30k GNI → solo comunas con ingreso > $8,000/mes

RESULTADO:
  Noruega  → 100% comunas | presupuesto × 1.0
  Chile    → Las Condes, Vitacura, Lo Barnechea | presupuesto × 0.4
  Brasil   → Jardins, Leblon, Itaim Bibi | presupuesto × 0.6
  Nigeria  → Ikoyi, Victoria Island | presupuesto × 0.2

En memoria de Jose Ignacio Fernandez (1989-2024)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from marketer_table_v2 import (
    MarketerTable, GlobalTargetingRules,
    GNI_PER_CAPITA, get_gni, get_country_tier,
    index_to_income_usd, income_to_index_threshold,
    EXAMPLE_CAMPAIGNS
)

# ── Proxy income tables (same as consultation_table) ──────────
PROXY_INGRESO = {
    "CL": {
        "Lo Barnechea": 100, "Las Condes": 95, "Vitacura": 95,
        "Providencia": 88,  "La Reina": 80,   "Nunoa": 75,
        "Macul": 72,        "La Florida": 60,  "San Miguel": 58,
        "Maipu": 55,        "Santiago Centro": 52, "Quinta Normal": 50,
        "Pudahuel": 38,     "Quilicura": 35,   "Conchali": 32,
        "Renca": 30,        "El Bosque": 28,   "La Pintana": 25,
        "Lo Espejo": 20,    "Vina del Mar": 70, "Valparaiso": 52,
        "Concepcion": 55,   "Temuco": 48,      "Antofagasta": 58,
    },
    "AR": {
        "Puerto Madero": 100, "Recoleta": 95, "Palermo": 90,
        "Belgrano": 88,    "Nunez": 80,    "Caballito": 70,
        "Almagro": 60,     "Flores": 55,   "Villa Lugano": 28,
        "La Matanza": 20,  "San Isidro": 85, "Cordoba": 60,
        "Rosario": 58,     "Mendoza": 58,
    },
    "BR": {
        "Jardins": 100,  "Itaim Bibi": 95, "Leblon": 98,
        "Ipanema": 92,   "Moema": 82,      "Pinheiros": 75,
        "Botafogo": 72,  "Copacabana": 70, "Lapa": 55,
        "Tatuape": 52,   "Diadema": 28,    "Rocinha": 10,
        "Brasilia": 70,  "Curitiba": 65,   "Porto Alegre": 62,
    },
    "MX": {
        "Polanco": 100, "Lomas de Chapultepec": 95, "Santa Fe": 88,
        "Condesa": 78,  "Roma Norte": 75, "Coyoacan": 72,
        "Tlalpan": 52,  "Ecatepec": 25,   "Neza": 18,
        "San Pedro Garza Garcia": 88, "Guadalajara": 62,
    },
    "CO": {
        "Rosales": 100, "El Nogal": 92, "El Poblado": 90,
        "Chapinero": 75, "Usaquen": 78, "Kennedy": 50,
        "Bosa": 28,     "Ciudad Bolivar": 18, "Barranquilla": 55,
    },
    "PE": {
        "Miraflores": 100, "San Isidro": 95, "La Molina": 88,
        "Surco": 82,       "Jesus Maria": 60, "Surquillo": 55,
        "San Juan de Lurigancho": 25, "Villa El Salvador": 15,
    },
    "US": {
        "Upper East Side": 100, "Beverly Hills": 98, "Pacific Heights": 92,
        "Santa Monica": 88,     "Brooklyn Heights": 78, "Williamsburg": 60,
        "Bronx": 22,            "Compton": 15, "Coral Gables": 80,
        "South Beach": 85,      "Nob Hill": 90, "Gold Coast Chicago": 88,
    },
    "ES": {
        "Salamanca Madrid": 100, "Sarria Sant Gervasi": 95,
        "Chamberi": 88,          "Eixample": 75,
        "Gracia Barcelona": 70,  "Vallecas": 32, "Nou Barris": 28,
    },
    "ZA": {
        "Sandton": 100, "Camps Bay": 92, "Rosebank": 80,
        "Umhlanga": 78, "Woodstock": 45, "Soweto": 12, "Khayelitsha": 8,
    },
    "NO": {
        "Frogner": 100, "Ullern": 90, "Nordstrand": 82,
        "Sagene": 72,   "Grorud": 55, "Stovner": 45,
    },
    "DE": {
        "Bogenhausen Munich": 100, "Blankenese Hamburg": 95,
        "Mitte Berlin": 80,        "Prenzlauer Berg": 72,
        "Neukolln": 45,            "Marzahn": 35,
    },
    "JP": {
        "Minato": 100, "Shibuya": 92, "Shinjuku": 80,
        "Suginami": 70, "Adachi": 42, "Katsushika": 38,
    },
    "GB": {
        "Kensington Chelsea": 100, "Westminster": 92,
        "Camden": 75,              "Hackney": 60,
        "Newham": 38,              "Barking": 32,
    },
    "NG": {
        "Ikoyi": 100, "Victoria Island": 92, "Lekki": 80,
        "Ikeja": 55,  "Surulere": 40,        "Mushin": 20,
        "Ajegunle": 10,
    },
    "IN": {
        "Bandra Mumbai": 100, "Worli": 90, "Juhu": 85,
        "Andheri": 60,        "Dharavi": 8, "Govandi": 10,
        "Golf Links Delhi": 95, "Vasant Vihar": 85,
    },
    "KR": {
        "Gangnam": 100, "Seocho": 92, "Mapo": 72,
        "Nowon": 48,    "Dobong": 42,
    },
}


# ══════════════════════════════════════════════════════════════
# DATACLASSES
# ══════════════════════════════════════════════════════════════

@dataclass
class CommuneDecision:
    country:        str
    commune:        str
    index:          int
    income_est_usd: float
    enters:         bool
    reason:         str
    budget_share:   float = 0.0   # fraction of country budget


@dataclass
class CountryDecision:
    country:        str
    gni:            int
    tier:           str
    strategy:       str    # 'all_communes' | 'elite_only' | 'excluded'
    enters:         bool
    min_index:      int
    min_income:     float
    communes_total: int
    communes_enter: int
    coverage_pct:   float
    reason:         str
    communes:       List[CommuneDecision] = field(default_factory=list)
    budget_assigned:float = 0.0


@dataclass
class GlobalAllocation:
    campaign_id:     int
    brand_name:      str
    presupuesto:     float
    countries:       List[CountryDecision] = field(default_factory=list)
    total_communes:  int   = 0
    entered_communes:int   = 0
    total_countries: int   = 0
    entered_countries:int  = 0


# ══════════════════════════════════════════════════════════════
# GLOBAL OPTIMIZER
# ══════════════════════════════════════════════════════════════

class GlobalOptimizer:
    """
    Executes the marketer's dual-rule targeting mandate
    across all countries and communes.

    For each country:
      1. Apply Rule 1 or Rule 2 based on GNI
      2. Filter communes that qualify
      3. Assign budget proportional to commune index

    Budget allocation logic:
      - Countries weighted by GNI × qualifying commune count
      - Within country: proportional to commune index score
    """

    def optimize(
        self,
        marketer:  MarketerTable,
        countries: List[str] = None,
        verbose:   bool = True
    ) -> GlobalAllocation:

        target_countries = countries or list(PROXY_INGRESO.keys())

        allocation = GlobalAllocation(
            campaign_id=marketer.campaign_id,
            brand_name=marketer.brand_name,
            presupuesto=marketer.presupuesto_disponible,
        )

        if verbose:
            self._print_header(marketer)

        # Step 1: Evaluate each country
        country_results = []
        for country in target_countries:
            result = self._evaluate_country(marketer, country)
            country_results.append(result)
            allocation.countries.append(result)

        # Step 2: Assign budget across countries
        self._assign_budget(allocation)

        # Step 3: Totals
        allocation.total_countries    = len(country_results)
        allocation.entered_countries  = sum(1 for c in country_results if c.enters)
        allocation.total_communes     = sum(c.communes_total for c in country_results)
        allocation.entered_communes   = sum(c.communes_enter for c in country_results)

        if verbose:
            self._print_results(allocation)

        return allocation

    def _evaluate_country(
        self,
        marketer: MarketerTable,
        country:  str
    ) -> CountryDecision:

        # Apply the two rules
        rule = marketer.global_rules.evaluate_country(country)
        communes_data = PROXY_INGRESO.get(country, {})
        communes_total = len(communes_data)

        if not rule['enters']:
            return CountryDecision(
                country=country,
                gni=rule['gni'],
                tier=get_country_tier(country),
                strategy=rule['strategy'],
                enters=False,
                min_index=100,
                min_income=0,
                communes_total=communes_total,
                communes_enter=0,
                coverage_pct=0.0,
                reason=rule['reason'],
            )

        min_index  = rule['min_index']
        min_income = rule['min_income']
        strategy   = rule['strategy']

        # Evaluate each commune
        commune_decisions = []
        for commune, index in communes_data.items():
            income_est = index_to_income_usd(index, country)
            enters = index >= min_index

            commune_decisions.append(CommuneDecision(
                country=country,
                commune=commune,
                index=index,
                income_est_usd=income_est,
                enters=enters,
                reason="OK" if enters else (
                    f"Index {index} < min {min_index} "
                    f"(income ${income_est:,.0f} < ${min_income:,.0f}/month)"
                )
            ))

        entering = [c for c in commune_decisions if c.enters]
        coverage = len(entering) / communes_total * 100 if communes_total > 0 else 0

        return CountryDecision(
            country=country,
            gni=rule['gni'],
            tier=get_country_tier(country),
            strategy=strategy,
            enters=True,
            min_index=min_index,
            min_income=min_income,
            communes_total=communes_total,
            communes_enter=len(entering),
            coverage_pct=round(coverage, 1),
            reason=rule['reason'],
            communes=commune_decisions,
        )

    def _assign_budget(self, allocation: GlobalAllocation):
        """
        Assign budget across countries and communes.

        Country weight = GNI × communes_entering
        (richer countries with more qualifying communes get more budget)

        Within country: proportional to commune index
        """
        entering = [c for c in allocation.countries if c.enters and c.communes_enter > 0]
        if not entering:
            return

        # Country weights
        weights = {
            c.country: (c.gni / 1000) * c.communes_enter
            for c in entering
        }
        total_weight = sum(weights.values())
        if total_weight == 0:
            return

        presupuesto = allocation.presupuesto

        for country_dec in entering:
            w = weights.get(country_dec.country, 0)
            country_budget = presupuesto * (w / total_weight) * 0.05  # 5% pace rate
            country_dec.budget_assigned = round(country_budget, 2)

            # Within country: proportional to index
            entering_communes = [c for c in country_dec.communes if c.enters]
            total_index = sum(c.index for c in entering_communes)
            if total_index > 0:
                for commune in entering_communes:
                    commune.budget_share = round(
                        country_budget * (commune.index / total_index), 4
                    )

    def _print_header(self, marketer: MarketerTable):
        r = marketer.global_rules
        print(f"\n{'='*70}")
        print(f"PREFERENDUM GLOBAL OPTIMIZER")
        print(f"Campaign: {marketer.brand_name} — {marketer.campaign_title}")
        print(f"{'='*70}")
        print(f"MANDATO:")
        print(f"  Regla 1: Paises con GNI > ${r.umbral_pais_usd:,}")
        print(f"           → Entrar en TODAS las comunas")
        print(f"  Regla 2: Paises con GNI < ${r.umbral_pais_usd:,}")
        print(f"           → Solo comunas con ingreso estimado > ${r.umbral_ingreso_usd:,.0f}/mes")
        if r.paises_incluidos:
            print(f"  Paises incluidos: {r.paises_incluidos}")
        if r.paises_excluidos:
            print(f"  Paises excluidos: {r.paises_excluidos}")
        print(f"  Presupuesto: ${marketer.presupuesto_disponible:,.2f} USD")
        print(f"{'='*70}\n")

    def _print_results(self, allocation: GlobalAllocation):
        print(f"\n{'='*70}")
        print(f"RESULTADO — {allocation.brand_name}")
        print(f"{'='*70}")
        print(f"\n{'Pais':<6} {'GNI':>8} {'Tier':<12} {'Estrategia':<14} {'Comunas':>10} {'Cobertura':>10} {'Budget':>10}")
        print(f"{'-'*70}")

        for c in sorted(allocation.countries, key=lambda x: x.gni, reverse=True):
            if not c.enters:
                print(f"  {c.country:<6} ${c.gni:>7,} {c.tier:<12} {'EXCLUIDO':<14} {'—':>10} {'—':>10} {'—':>10}")
            else:
                communes_str = f"{c.communes_enter}/{c.communes_total}"
                print(f"  {c.country:<6} ${c.gni:>7,} {c.tier:<12} {c.strategy:<14} "
                      f"{communes_str:>10} {c.coverage_pct:>9.0f}% ${c.budget_assigned:>9.2f}")

                # Show qualifying communes
                entering = [cm for cm in c.communes if cm.enters]
                for cm in sorted(entering, key=lambda x: x.index, reverse=True)[:5]:
                    print(f"    → {cm.commune:<28} idx:{cm.index:>3} "
                          f"~${cm.income_est_usd:>6,.0f}/mes  "
                          f"budget:${cm.budget_share:.4f}")
                if len(entering) > 5:
                    print(f"    → ... y {len(entering)-5} comunas mas")

        print(f"\n{'='*70}")
        print(f"RESUMEN FINAL:")
        print(f"  Paises evaluados:  {allocation.total_countries}")
        print(f"  Paises que entran: {allocation.entered_countries}")
        print(f"  Comunas evaluadas: {allocation.total_communes}")
        print(f"  Comunas que entran:{allocation.entered_communes}")
        pct = allocation.entered_communes/allocation.total_communes*100 if allocation.total_communes else 0
        print(f"  Cobertura global:  {pct:.1f}% de comunas")
        print(f"{'='*70}\n")


# ══════════════════════════════════════════════════════════════
# DEMO
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    optimizer = GlobalOptimizer()

    print("\nPREFERENDUM — GLOBAL OPTIMIZER DEMO")
    print("En memoria de Jose Ignacio Fernandez (1989-2024)")

    for name, campaign in EXAMPLE_CAMPAIGNS.items():
        result = optimizer.optimize(campaign, verbose=True)

        # Detailed commune breakdown for Chile
        cl = next((c for c in result.countries if c.country == "CL"), None)
        if cl and cl.enters:
            print(f"\nDetalle Chile para {campaign.brand_name}:")
            print(f"  Estrategia: {cl.strategy}")
            print(f"  Indice minimo: {cl.min_index}")
            print(f"  Ingreso minimo: ~${cl.min_income:,.0f}/mes")
            for cm in sorted(cl.communes, key=lambda x: x.index, reverse=True):
                status = "✓ ENTRA" if cm.enters else "✗ NO"
                income = f"~${cm.income_est_usd:,.0f}/mes"
                print(f"    {status}  {cm.commune:<28} idx:{cm.index:>3}  {income}")
            print()

        print("\n" + "="*70 + "\n")
