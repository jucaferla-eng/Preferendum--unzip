"""
zipcode_agent.py  —  PREFERENDUM
Mapea código postal → mediana de arriendo → SE tier.

Estrategia por país:
  US : Census Bureau ACS 5-year (API gratuita, ~33,000 ZCTAs exactos)
  Resto: mapeo por PREFIJO del código postal (2-4 chars)
         → provincia / área → income_index apróximado pero real.

Lookup en _assign_user_tier: prueba prefijos de longitud decreciente
hasta encontrar match. UK también prueba el área (letras iniciales).
"""

import requests
from commune_agent import get_se_tier, calculate_cpm, CPM_BASE_BY_COUNTRY

CENSUS_BASE = "https://api.census.gov/data/2022/acs/acs5"

# ══════════════════════════════════════════════════════════════
# ESTADOS UNIDOS — Census ACS (exacto, ~33,000 ZCTAs)
# ══════════════════════════════════════════════════════════════
US_STATE_FIPS = [
    '01','02','04','05','06','08','09','10','11','12','13','15','16','17','18',
    '19','20','21','22','23','24','25','26','27','28','29','30','31','32','33',
    '34','35','36','37','38','39','40','41','42','44','45','46','47','48','49',
    '50','51','53','54','55','56',
]

def fetch_us_zip_rents_by_state(state_fips: str) -> list[dict]:
    r = requests.get(CENSUS_BASE, params={
        "get": "B25064_001E,B01003_001E",
        "for": "zip code tabulation area:*",
        "in":  f"state:{state_fips}",
    }, timeout=60)
    r.raise_for_status()
    rows = r.json()
    results = []
    for row in rows[1:]:
        rent_str, pop_str, _state, zcta = row
        rent = int(float(rent_str)) if rent_str and rent_str not in ('-666666666', 'null') else 0
        pop  = int(float(pop_str))  if pop_str  and pop_str  not in ('-666666666', 'null') else 0
        if rent > 200:
            results.append({'zip': zcta, 'rent_usd': rent, 'population': pop})
    return results

def fetch_all_us_zips() -> tuple[list, list]:
    all_results, errors = [], []
    for fips in US_STATE_FIPS:
        try:
            all_results.extend(fetch_us_zip_rents_by_state(fips))
        except Exception as e:
            errors.append({'state': fips, 'error': str(e)})
    return all_results, errors

def process_us_zip_data(raw: list[dict]) -> list[dict]:
    if not raw:
        return []
    max_rent = max(r['rent_usd'] for r in raw)
    cpm_base = CPM_BASE_BY_COUNTRY.get('US', 18.0)
    return [{
        'country': 'US', 'commune': r['zip'],
        'income_index': round((r['rent_usd'] / max_rent) * 100, 1),
        'cpm_usd':   calculate_cpm(round((r['rent_usd']/max_rent)*100,1), cpm_base),
        'se_tier':   get_se_tier(round((r['rent_usd']/max_rent)*100,1)),
        'price_m2_avg': 0, 'population': r['population'], 'updated_at': None,
    } for r in raw]


# ══════════════════════════════════════════════════════════════
# DATOS DE PREFIJOS POR PAÍS
# Formato: (prefijo, income_index, población_estimada)
# Referencia: prefijo más caro del país = índice 100
#
# Cómo se usa:
#   UK  "SW1A 2AA" → prueba "SW1A", "SW1", "SW", área="SW"
#   ES  "28001"    → prueba "28001","2800","280","28"
#   DE  "80331"    → prueba "80331","8033","803","80"
#   CA  "M5V 3A8"  → prueba "M5V3","M5V","M5","M"
# ══════════════════════════════════════════════════════════════

# income_index referencia: área más cara del país = 100
POSTAL_PREFIX_DATA: dict[str, list] = {

    # ── REINO UNIDO — área de código postal (letras iniciales) ──
    # Referencia: Kensington & Chelsea (W8, SW3, SW7) = 100
    'GB': [
        # Inner London premium
        ('SW3',  100,   30_000), ('SW7',  100,   30_000),
        ('W8',    98,   30_000), ('W1',    95,  180_000),
        ('WC1',   92,   80_000), ('WC2',   90,   40_000),
        ('EC1',   88,   50_000), ('EC2',   86,   10_000),
        ('EC3',   84,   10_000), ('EC4',   82,    8_000),
        # SW zone (Fulham, Battersea, Wimbledon...)
        ('SW1',   90,  120_000), ('SW6',   78,  110_000),
        ('SW10',  80,   30_000), ('SW4',   72,   60_000),
        ('SW11',  68,  110_000), ('SW12',  62,   45_000),
        ('SW13',  65,   35_000), ('SW15',  62,   55_000),
        ('SW18',  60,   70_000), ('SW19',  58,   90_000),
        ('SW20',  55,   50_000),
        # W zone (Notting Hill, Shepherd's Bush, Ealing...)
        ('W11',   88,   35_000), ('W2',    86,   50_000),
        ('W9',    76,   40_000), ('W10',   68,   50_000),
        ('W12',   64,   70_000), ('W3',    58,   80_000),
        ('W4',    65,   45_000), ('W5',    60,   90_000),
        ('W6',    72,   50_000), ('W7',    54,   50_000),
        ('W13',   55,   60_000), ('W14',   78,   30_000),
        # NW zone (Hampstead, St John's Wood...)
        ('NW3',   86,   40_000), ('NW8',   84,   30_000),
        ('NW1',   74,  100_000), ('NW6',   66,   70_000),
        ('NW2',   60,   80_000), ('NW4',   58,   65_000),
        ('NW5',   68,   40_000), ('NW7',   56,   60_000),
        ('NW9',   52,   75_000), ('NW10',  48,   90_000),
        ('NW11',  70,   35_000),
        # N zone (Islington, Highgate, Finsbury...)
        ('N1',    72,   80_000), ('N6',    74,   25_000),
        ('N2',    68,   30_000), ('N10',   64,   30_000),
        ('N8',    62,   50_000), ('N4',    58,   50_000),
        ('N5',    60,   40_000), ('N7',    58,   45_000),
        ('N19',   55,   40_000), ('N3',    56,   40_000),
        ('N11',   50,   60_000), ('N12',   50,   60_000),
        ('N13',   46,   55_000), ('N14',   46,   50_000),
        ('N15',   44,   60_000), ('N16',   52,   50_000),
        ('N17',   40,   70_000), ('N18',   38,   40_000),
        ('N20',   52,   40_000), ('N21',   50,   50_000),
        ('N22',   48,   60_000),
        # SE zone (Southwark, Greenwich...)
        ('SE1',   72,  100_000), ('SE10',  62,   70_000),
        ('SE3',   58,   45_000), ('SE7',   50,   50_000),
        ('SE8',   52,   40_000), ('SE9',   46,   55_000),
        ('SE11',  64,   30_000), ('SE13',  50,   65_000),
        ('SE14',  50,   45_000), ('SE15',  48,   60_000),
        ('SE16',  58,   50_000), ('SE17',  56,   40_000),
        ('SE18',  42,   70_000), ('SE19',  48,   50_000),
        ('SE20',  44,   55_000), ('SE21',  56,   25_000),
        ('SE22',  60,   30_000), ('SE23',  52,   45_000),
        ('SE24',  62,   30_000), ('SE25',  42,   55_000),
        ('SE26',  48,   45_000), ('SE27',  50,   40_000),
        ('SE28',  36,   35_000),
        # E zone (Hackney, Tower Hamlets, Stratford...)
        ('E1',    56,   80_000), ('E2',    60,   50_000),
        ('E3',    52,   50_000), ('E5',    52,   40_000),
        ('E8',    58,   35_000), ('E9',    54,   35_000),
        ('E10',   46,   50_000), ('E11',   50,   70_000),
        ('E14',   62,   80_000), ('E15',   52,   70_000),
        ('E16',   50,   60_000), ('E17',   46,   65_000),
        ('E18',   50,   45_000),
        # Outer London / Home Counties
        ('EN',    42, 330_000), ('HA',    40, 250_000),
        ('IG',    40, 200_000), ('RM',    36, 340_000),
        ('DA',    34, 180_000), ('BR',    38, 310_000),
        ('CR',    38, 360_000), ('SM',    40, 200_000),
        ('KT',    46, 280_000), ('TW',    44, 280_000),
        ('UB',    38, 300_000), ('SL',    46, 500_000),
        ('RH',    42, 350_000), ('GU',    48, 500_000),
        ('RG',    42, 440_000), ('OX',    54, 280_000),
        ('CB',    54, 250_000), ('AL',    44, 180_000),
        ('HP',    40, 250_000), ('LU',    34, 220_000),
        ('SG',    38, 270_000), ('CM',    34, 400_000),
        ('SS',    30, 390_000), ('CO',    30, 300_000),
        ('IP',    28, 360_000), ('NR',    26, 440_000),
        ('PE',    28, 360_000), ('NN',    28, 720_000),
        ('MK',    34, 280_000), ('LU',    32, 220_000),
        # Major cities outside London
        ('EH',    40, 520_000), ('G',     38, 630_000),
        ('AB',    36, 230_000), ('DD',    28, 150_000),
        ('KY',    28, 360_000), ('PA',    26, 140_000),
        ('FK',    28, 300_000), ('ML',    26, 320_000),
        ('KA',    26, 370_000),
        ('BS',    40, 460_000), ('BA',    40, 180_000),
        ('GL',    34, 300_000), ('HR',    26, 200_000),
        ('WR',    28, 570_000), ('CV',    28, 370_000),
        ('B',     28, 1_100_000), ('WS',  26, 300_000),
        ('WV',    26, 260_000), ('DY',    24, 330_000),
        ('ST',    24, 460_000), ('SK',    32, 480_000),
        ('CW',    30, 380_000), ('CH',    30, 350_000),
        ('WA',    28, 340_000), ('WN',    24, 330_000),
        ('BL',    24, 280_000), ('OL',    22, 230_000),
        ('HX',    22, 200_000), ('BD',    20, 540_000),
        ('LS',    28, 790_000), ('WF',    24, 360_000),
        ('HG',    30, 160_000), ('YO',    28, 400_000),
        ('DN',    22, 310_000), ('S',     24, 580_000),
        ('DE',    26, 540_000), ('NG',    26, 330_000),
        ('LE',    26, 350_000), ('MK',    34, 270_000),
        ('M',     36, 550_000), ('L',     26, 490_000),
        ('PR',    24, 340_000), ('FY',    22, 320_000),
        ('BB',    22, 300_000), ('LA',    26, 240_000),
        ('CA',    24, 510_000), ('DL',    24, 530_000),
        ('HG',    30, 160_000), ('TS',    22, 570_000),
        ('NE',    24, 880_000), ('DH',    20, 520_000),
        ('SR',    20, 280_000), ('TD',    22, 120_000),
        ('EX',    28, 320_000), ('PL',    24, 340_000),
        ('TQ',    26, 140_000), ('TR',    26, 190_000),
        ('PO',    32, 410_000), ('SO',    32, 500_000),
        ('BN',    38, 320_000), ('TN',    36, 360_000),
        ('ME',    30, 530_000), ('CT',    28, 360_000),
        ('CF',    30, 360_000), ('SA',    26, 370_000),
        ('LL',    22, 310_000), ('SY',    22, 440_000),
        ('NP',    24, 230_000), ('LD',    20,  70_000),
        ('BT',    24, 700_000),
    ],

    # ── ESPAÑA — 2 primeros dígitos = código de provincia ─────────
    # Referencia: 08 (Barcelona) = 24 EUR/m² = 100
    'ES': [
        ('08', 100,  5_500_000), # Barcelona
        ('28',  92, 6_600_000), # Madrid
        ('20',  83,   720_000), # Gipuzkoa (Donostia)
        ('07',  83,  1_100_000), # Baleares
        ('48',  67,  1_150_000), # Bizkaia (Bilbao)
        ('29',  75,  1_680_000), # Málaga
        ('46',  63,  2_550_000), # Valencia
        ('35',  58,  1_090_000), # Las Palmas
        ('38',  54,  1_060_000), # Santa Cruz Tenerife
        ('31',  54,   660_000), # Navarra
        ('39',  50,   591_000), # Cantabria
        ('17',  50,   767_000), # Girona
        ('43',  46,   826_000), # Tarragona
        ('41',  54,  1_950_000), # Sevilla
        ('15',  46,  1_120_000), # A Coruña
        ('25',  42,   445_000), # Lleida
        ('03',  50,  1_850_000), # Alicante
        ('11',  46,  1_240_000), # Cádiz
        ('30',  42,  1_510_000), # Murcia
        ('04',  38,   730_000), # Almería
        ('18',  38,   920_000), # Granada
        ('36',  42,   950_000), # Pontevedra
        ('33',  40,  1_010_000), # Asturias
        ('47',  38,   516_000), # Valladolid
        ('50',  38,   967_000), # Zaragoza
        ('01',  42,   335_000), # Álava (Vitoria)
        ('14',  38,   794_000), # Córdoba
        ('23',  29,   636_000), # Jaén
        ('06',  29,  1_100_000), # Badajoz
        ('10',  28,   397_000), # Cáceres
        ('02',  29,   401_000), # Albacete
        ('13',  29,   497_000), # Ciudad Real
        ('16',  29,   195_000), # Cuenca
        ('19',  29,   256_000), # Guadalajara
        ('44',  25,   133_000), # Teruel
        ('05',  25,   163_000), # Ávila
        ('09',  29,   357_000), # Burgos
        ('24',  29,   448_000), # León
        ('37',  33,   335_000), # Salamanca
        ('40',  29,   155_000), # Segovia
        ('42',  25,    89_000), # Soria
        ('49',  25,   180_000), # Zamora
        ('22',  29,   220_000), # Huesca
        ('26',  33,   322_000), # La Rioja
        ('27',  25,   331_000), # Lugo
        ('32',  25,   305_000), # Ourense
        ('34',  25,   158_000), # Palencia
        ('45',  33,   703_000), # Toledo
        ('12',  38,   589_000), # Castellón
        ('21',  33,   523_000), # Huelva
    ],

    # ── ALEMANIA — 2 primeros dígitos del PLZ ─────────────────────
    # Referencia: 80 (München) = 30 EUR/m² = 100
    'DE': [
        ('80', 100,   950_000), # München centro
        ('81',  95,   480_000), # München este
        ('82',  85,   350_000), # München sur (Starnberg)
        ('83',  75,   240_000), # Rosenheim
        ('85',  78,   420_000), # München norte (Ebersberg)
        ('60',  83,   380_000), # Frankfurt centro
        ('61',  75,   280_000), # Frankfurt norte (Hochtaunus)
        ('63',  72,   420_000), # Frankfurt este (Offenbach)
        ('64',  68,   300_000), # Frankfurt sur (Darmstadt)
        ('65',  70,   280_000), # Wiesbaden
        ('20',  80,   350_000), # Hamburg centro
        ('21',  72,   330_000), # Hamburg sur
        ('22',  78,   550_000), # Hamburg norte (Blankenese)
        ('68',  70,   230_000), # Mannheim
        ('69',  73,   280_000), # Heidelberg
        ('70',  73,   310_000), # Stuttgart centro
        ('71',  68,   260_000), # Stuttgart norte
        ('72',  62,   250_000), # Stuttgart sud (Tübingen)
        ('73',  58,   240_000), # Göppingen
        ('74',  58,   220_000), # Heilbronn
        ('75',  55,   150_000), # Pforzheim
        ('76',  60,   260_000), # Karlsruhe
        ('77',  55,   200_000), # Offenburg
        ('78',  55,   210_000), # Konstanz
        ('79',  65,   350_000), # Freiburg
        ('10',  73,   650_000), # Berlín Mitte/Prenzlauer Berg
        ('12',  62,   550_000), # Berlín Tempelhof/Neukölln
        ('13',  62,   380_000), # Berlín Reinickendorf
        ('14',  60,   330_000), # Berlín Charlottenburg
        ('40',  67,   320_000), # Düsseldorf
        ('41',  58,   250_000), # Mönchengladbach
        ('42',  55,   380_000), # Wuppertal
        ('44',  50,   300_000), # Dortmund
        ('45',  48,   580_000), # Essen
        ('47',  45,   500_000), # Duisburg
        ('50',  67,   540_000), # Köln centro
        ('51',  58,   230_000), # Bergisch Gladbach
        ('52',  52,   250_000), # Aachen
        ('53',  60,   330_000), # Bonn
        ('55',  52,   210_000), # Mainz
        ('56',  48,   200_000), # Koblenz
        ('28',  50,   570_000), # Bremen
        ('30',  55,   270_000), # Hannover
        ('38',  45,   260_000), # Braunschweig
        ('39',  42,   240_000), # Magdeburg
        ('90',  57,   260_000), # Nürnberg
        ('91',  52,   200_000), # Fürth/Erlangen
        ('86',  62,   200_000), # Augsburg
        ('87',  52,   180_000), # Kempten
        ('01',  47,   280_000), # Dresden
        ('04',  47,   300_000), # Leipzig
        ('06',  38,   230_000), # Halle
        ('07',  38,   200_000), # Erfurt
        ('08',  35,   200_000), # Zwickau
        ('09',  35,   250_000), # Chemnitz
        ('18',  38,   110_000), # Rostock
        ('17',  33,   100_000), # Schwerin
        ('19',  33,   100_000), # Schwerin nord
        ('23',  38,   210_000), # Lübeck
        ('24',  42,   290_000), # Kiel
        ('25',  38,   160_000), # Heide
        ('26',  40,   160_000), # Oldenburg
        ('27',  38,   160_000), # Bremerhaven
        ('29',  42,   180_000), # Celle
        ('31',  38,   130_000), # Hildesheim
        ('32',  38,   170_000), # Herford
        ('33',  40,   340_000), # Bielefeld
        ('34',  38,   240_000), # Kassel
        ('35',  40,   260_000), # Marburg
        ('36',  33,   150_000), # Fulda
        ('37',  42,   200_000), # Göttingen
        ('57',  35,   270_000), # Siegen
        ('58',  35,   380_000), # Hagen
        ('59',  38,   440_000), # Dortmund sur
        ('66',  38,   330_000), # Saarbrücken
        ('67',  42,   520_000), # Ludwigshafen
        ('84',  55,   140_000), # Landshut
        ('88',  50,   200_000), # Ravensburg
        ('89',  55,   125_000), # Ulm
        ('92',  42,   100_000), # Amberg
        ('93',  42,   400_000), # Regensburg
        ('94',  38,   200_000), # Passau
        ('95',  40,   150_000), # Hof
        ('96',  40,   220_000), # Bamberg
        ('97',  42,   340_000), # Würzburg
        ('98',  33,   100_000), # Suhl
        ('99',  40,   200_000), # Erfurt nord
    ],

    # ── FRANCIA — 2 primeros dígitos = departamento ───────────────
    # Referencia: 75 (Paris) = 35 EUR/m² = 100
    'FR': [
        ('75', 100, 2_150_000), # Paris
        ('92',  80,   600_000), # Hauts-de-Seine (Neuilly, Boulogne)
        ('06',  69,   340_000), # Alpes-Maritimes (Nice, Cannes)
        ('77',  49,   160_000), # Seine-et-Marne
        ('78',  63,  1_450_000), # Yvelines (Versailles)
        ('91',  51,  1_300_000), # Essonne
        ('93',  51, 1_600_000), # Seine-Saint-Denis
        ('94',  63, 1_380_000), # Val-de-Marne
        ('95',  51, 1_230_000), # Val-d'Oise
        ('83',  54,  1_080_000), # Var (Toulon)
        ('13',  46,  2_050_000), # Bouches-du-Rhône (Marseille)
        ('69',  57,  1_870_000), # Rhône (Lyon)
        ('33',  51,  1_620_000), # Gironde (Bordeaux)
        ('34',  46,  1_160_000), # Hérault (Montpellier)
        ('67',  46,  1_130_000), # Bas-Rhin (Strasbourg)
        ('31',  46,  1_400_000), # Haute-Garonne (Toulouse)
        ('44',  49,  1_430_000), # Loire-Atlantique (Nantes)
        ('35',  46,  1_060_000), # Ille-et-Vilaine (Rennes)
        ('59',  43,  2_600_000), # Nord (Lille)
        ('38',  43,  1_260_000), # Isère (Grenoble)
        ('76',  37,  1_280_000), # Seine-Maritime (Rouen)
        ('14',  37,   690_000), # Calvados (Caen)
        ('57',  40,   760_000), # Moselle (Metz)
        ('54',  40,   730_000), # Meurthe-et-Moselle (Nancy)
        ('40',  37,   420_000), # Landes
        ('64',  43,   690_000), # Pyrénées-Atlantiques (Pau/Biarritz)
        ('74',  57,   880_000), # Haute-Savoie (Annecy)
        ('73',  46,   430_000), # Savoie (Chambéry)
        ('63',  37,   650_000), # Puy-de-Dôme (Clermont-Ferrand)
        ('76',  37,  1_280_000), # Seine-Maritime
        ('60',  37,   820_000), # Oise (Beauvais)
        ('62',  34,  1_470_000), # Pas-de-Calais (Lens)
        ('80',  34,   570_000), # Somme (Amiens)
        ('51',  37,   580_000), # Marne (Reims)
        ('21',  40,   530_000), # Côte-d'Or (Dijon)
        ('25',  37,   540_000), # Doubs (Besançon)
        ('37',  37,   610_000), # Indre-et-Loire (Tours)
        ('49',  34,   800_000), # Maine-et-Loire (Angers)
        ('85',  34,   680_000), # Vendée (La Roche)
        ('86',  31,   440_000), # Vienne (Poitiers)
        ('87',  31,   375_000), # Haute-Vienne (Limoges)
        ('29',  34,   910_000), # Finistère (Brest)
        ('56',  37,   750_000), # Morbihan (Vannes)
        ('22',  31,   600_000), # Côtes-d'Armor
        ('66',  43,   470_000), # Pyrénées-Orientales (Perpignan)
        ('11',  31,   370_000), # Aude (Carcassonne)
        ('30',  40,   745_000), # Gard (Nîmes)
        ('84',  43,   560_000), # Vaucluse (Avignon)
        ('13',  46,  2_050_000), # Bouches-du-Rhône
        ('04',  31,   162_000), # Alpes-de-Haute-Provence
        ('05',  34,   140_000), # Hautes-Alpes
        ('2A',  46,   330_000), # Corse-du-Sud
        ('2B',  40,   200_000), # Haute-Corse
        ('971', 40,   400_000), # Guadeloupe
        ('972', 40,   350_000), # Martinique
        ('973', 31,   270_000), # Guyane
        ('974', 37,   870_000), # Réunion
        ('976', 25,   270_000), # Mayotte
    ],

    # ── ITALIA — 2 primeros dígitos del CAP ──────────────────────
    # Referencia: 20 (Milano) = 28 EUR/m² = 100
    'IT': [
        ('20', 100, 1_400_000), # Milano
        ('21',  64,   900_000), # Varese
        ('22',  57,   600_000), # Como
        ('23',  50,   180_000), # Sondrio
        ('24',  57,   1_100_000), # Bergamo
        ('25',  54,   1_250_000), # Brescia
        ('27',  50,   540_000), # Pavia
        ('00',  79, 2_800_000), # Roma
        ('01',  43,   320_000), # Viterbo
        ('02',  36,   150_000), # Rieti
        ('03',  39,   490_000), # Frosinone
        ('04',  43,   570_000), # Latina
        ('06',  50,   670_000), # Perugia
        ('05',  36,   220_000), # Terni
        ('07',  39,   500_000), # Sassari
        ('08',  36,   340_000), # Nuoro
        ('09',  36,   400_000), # Cagliari
        ('10',  50,   870_000), # Torino
        ('11',  43,   130_000), # Aosta
        ('12',  43,   580_000), # Cuneo
        ('13',  46,   190_000), # Vercelli
        ('14',  43,   220_000), # Asti
        ('15',  43,   430_000), # Alessandria
        ('16',  43,   580_000), # Genova
        ('17',  39,   290_000), # Savona
        ('18',  50,   290_000), # Imperia (Riviera)
        ('19',  43,   230_000), # La Spezia
        ('30',  71,   260_000), # Venezia
        ('31',  54,   890_000), # Treviso
        ('32',  43,   210_000), # Belluno
        ('33',  50,   540_000), # Udine
        ('34',  43,   230_000), # Trieste
        ('35',  50,   940_000), # Padova
        ('36',  50,   330_000), # Vicenza
        ('37',  50,   920_000), # Verona
        ('38',  50,   540_000), # Trento
        ('39',  57,   520_000), # Bolzano (BZ)
        ('40',  57,   1_010_000), # Bologna
        ('41',  46,   700_000), # Modena
        ('42',  43,   530_000), # Reggio Emilia
        ('43',  43,   445_000), # Parma
        ('44',  43,   350_000), # Ferrara
        ('47',  43,   390_000), # Forlì-Cesena
        ('48',  43,   340_000), # Ravenna
        ('47',  43,   130_000), # Rimini
        ('50',  64,   370_000), # Firenze
        ('51',  46,   290_000), # Pistoia
        ('52',  43,   340_000), # Arezzo
        ('53',  46,   270_000), # Siena
        ('54',  43,   200_000), # Massa
        ('55',  50,   390_000), # Lucca
        ('56',  50,   430_000), # Pisa
        ('57',  43,   230_000), # Livorno
        ('58',  43,   220_000), # Grosseto
        ('59',  50,   250_000), # Prato
        ('60',  39,   480_000), # Ancona
        ('61',  36,   340_000), # Pesaro
        ('62',  33,   320_000), # Macerata
        ('63',  33,   320_000), # Ascoli Piceno
        ('64',  33,   310_000), # Teramo
        ('65',  33,   310_000), # Pescara
        ('66',  29,   370_000), # Chieti
        ('67',  29,   300_000), # L'Aquila
        ('70',  36,   930_000), # Bari
        ('71',  29,   650_000), # Foggia
        ('72',  33,   800_000), # Brindisi/Taranto
        ('73',  33,   800_000), # Lecce
        ('74',  29,   580_000), # Taranto
        ('75',  25,   390_000), # Matera
        ('76',  29,   450_000), # BAT
        ('80',  43, 3_100_000), # Napoli
        ('81',  33,   940_000), # Caserta
        ('82',  25,   285_000), # Benevento
        ('83',  25,   430_000), # Avellino
        ('84',  29,   1_100_000), # Salerno
        ('85',  25,   365_000), # Potenza
        ('86',  25,   300_000), # Campobasso
        ('87',  29,   700_000), # Cosenza
        ('88',  25,   560_000), # Catanzaro
        ('89',  25,   560_000), # Reggio Calabria
        ('90',  36,   680_000), # Palermo
        ('91',  29,   430_000), # Trapani
        ('92',  25,   440_000), # Agrigento
        ('93',  25,   280_000), # Caltanissetta
        ('94',  25,   170_000), # Enna
        ('95',  32,   310_000), # Catania
        ('96',  25,   400_000), # Siracusa
        ('97',  25,   340_000), # Ragusa
        ('98',  29,   650_000), # Messina
    ],

    # ── AUSTRALIA — 4 primeros dígitos del postcode ───────────────
    # Referencia: 2027 (Woollahra/Point Piper) = 100
    'AU': [
        # Sydney premium (2000-2099)
        ('2000', 86,   30_000), # Sydney CBD
        ('2006', 78,   30_000), # The University
        ('2010', 82,   30_000), # Surry Hills
        ('2011', 88,   30_000), # Potts Point
        ('2021', 86,   20_000), # Paddington
        ('2022', 84,   15_000), # Randwick
        ('2023', 88,   10_000), # Bellevue Hill
        ('2025', 92,   15_000), # Edgecliff
        ('2026', 90,   25_000), # Bondi
        ('2027', 100,  20_000), # Woollahra
        ('2028', 96,   15_000), # Double Bay
        ('2029', 90,   10_000), # Rose Bay
        ('2030', 88,   20_000), # Vaucluse
        ('2031', 84,   25_000), # Coogee
        ('2060', 80,   20_000), # North Sydney
        ('2061', 82,   15_000), # Kirribilli
        ('2065', 76,   40_000), # St Leonards
        ('2066', 78,   35_000), # Lane Cove
        ('2067', 80,   30_000), # Chatswood
        ('2068', 80,   25_000), # Willoughby
        ('2071', 78,   20_000), # Killara
        ('2073', 76,   20_000), # Pymble
        ('2074', 74,   25_000), # Turramurra
        ('2075', 72,   25_000), # St Ives
        ('2076', 70,   30_000), # Wahroonga
        # Sydney mid (20xx)
        ('2040', 72,   40_000), # Leichhardt
        ('2041', 72,   30_000), # Balmain
        ('2042', 68,   30_000), # Newtown
        ('2043', 66,   20_000), # Erskineville
        ('2044', 64,   25_000), # St Peters
        ('2045', 62,   20_000), # Strathfield
        ('2046', 62,   30_000), # Concord
        ('2047', 60,   20_000), # Drummoyne
        ('2048', 58,   30_000), # Marrickville
        ('2050', 56,   20_000), # Glebe
        ('2100', 66,   40_000), # Manly
        ('2101', 64,   35_000), # Narrabeen
        ('2102', 60,   30_000), # Dee Why
        ('2110', 62,   30_000), # Hunters Hill
        ('2111', 62,   25_000), # Ryde
        # Sydney outer/west
        ('2000', 86,   30_000), # Sydney CBD
        ('2150', 46,  100_000), # Parramatta
        ('2155', 42,   80_000), # Blacktown-North
        ('2148', 40,  120_000), # Blacktown
        ('2164', 36,   50_000), # Wetherill Park
        ('2170', 36,   60_000), # Liverpool
        ('2196', 40,   40_000), # Lakemba
        ('2200', 38,   40_000), # Bankstown
        ('2560', 34,   80_000), # Campbelltown
        ('2750', 38,   60_000), # Penrith
        # Melbourne premium (3xxx)
        ('3002',  82,  10_000), # East Melbourne
        ('3004',  80,  10_000), # South Yarra
        ('3006',  80,  15_000), # Southbank
        ('3141', 100,  20_000), # Toorak
        ('3142',  88,  20_000), # Prahran
        ('3143',  86,  15_000), # Armadale
        ('3144',  84,  15_000), # Malvern
        ('3145',  80,  30_000), # Caulfield
        ('3146',  82,  15_000), # Glen Iris
        ('3162',  72,  20_000), # Elsternwick
        ('3181',  76,  10_000), # Prahran
        ('3182',  72,  15_000), # St Kilda
        ('3101',  78,  20_000), # Kew
        ('3102',  74,  20_000), # Kew East
        ('3103',  72,  25_000), # Balwyn
        ('3104',  70,  25_000), # Balwyn North
        ('3126',  70,  20_000), # Camberwell
        ('3127',  68,  20_000), # Box Hill
        ('3128',  66,  25_000), # Box Hill South
        ('3130',  64,  20_000), # Nunawading
        ('3000',  76,  30_000), # Melbourne CBD
        ('3051',  68,  20_000), # Flemington
        ('3052',  70,  15_000), # Parkville
        ('3053',  70,  15_000), # Carlton
        ('3054',  68,  15_000), # Carlton North
        ('3055',  66,  20_000), # Brunswick South
        ('3056',  64,  25_000), # Brunswick
        ('3057',  62,  25_000), # Brunswick East
        ('3058',  60,  25_000), # Coburg
        # Melbourne outer
        ('3150',  54,  30_000), # Glen Waverley
        ('3166',  52,  25_000), # Oakleigh
        ('3175',  44,  35_000), # Dandenong North
        ('3168',  50,  30_000), # Clayton
        ('3029',  40,  50_000), # Hoppers Crossing
        ('3030',  38,  60_000), # Werribee
        # Other capitals
        ('4000',  64,  30_000), # Brisbane CBD
        ('4101',  62,  20_000), # South Brisbane
        ('4059',  56,  20_000), # Paddington QLD
        ('4151',  60,  20_000), # Coorparoo
        ('4152',  58,  20_000), # Camp Hill
        ('2600',  62,  10_000), # Canberra (ACT)
        ('6000',  58,  20_000), # Perth CBD
        ('6005',  66,  10_000), # West Perth
        ('6009',  80,  15_000), # Nedlands
        ('6010',  82,  15_000), # Cottesloe
        ('6011',  78,  10_000), # Claremont
        ('6012',  76,  10_000), # Mount Claremont
        ('5000',  52,  20_000), # Adelaide CBD
        ('5041',  54,  15_000), # Unley
        ('5065',  60,  15_000), # Burnside
        ('7000',  58,  10_000), # Hobart CBD
        ('7005',  60,   8_000), # Battery Point Hobart
        ('0800',  52,  10_000), # Darwin CBD
    ],

    # ── CANADÁ — FSA (primeros 3 chars) ──────────────────────────
    # Referencia: V7W (West Vancouver) = 100
    'CA': [
        # BC (V prefix) — Vancouver Metro
        ('V7W', 100,  50_000), # West Vancouver premium
        ('V7V',  96,  40_000), # West Van norte
        ('V7T',  90,  35_000), # North Vancouver premium
        ('V7N',  84,  40_000), # North Vancouver mid
        ('V7M',  82,  45_000), # North Vancouver east
        ('V7L',  80,  40_000), # North Vancouver Lonsdale
        ('V6E',  82,  30_000), # Vancouver West End
        ('V6J',  86,  35_000), # Vancouver Kitsilano
        ('V6K',  82,  30_000), # Vancouver Kitsilano
        ('V6R',  90,  25_000), # Vancouver Point Grey
        ('V6S',  92,  20_000), # Vancouver UBC area
        ('V6T',  80,  35_000), # UBC campus
        ('V6B',  74,  35_000), # Vancouver downtown
        ('V6C',  76,  20_000), # Vancouver downtown
        ('V6H',  78,  25_000), # Vancouver Fairview
        ('V6M',  80,  25_000), # Vancouver South Granville
        ('V6N',  76,  25_000), # Vancouver Marpole
        ('V5K',  64,  30_000), # Vancouver East
        ('V5L',  66,  25_000), # Vancouver East Grandview
        ('V5M',  62,  30_000), # Vancouver East Renfrew
        ('V5N',  68,  25_000), # Vancouver East Commercial
        ('V5P',  60,  30_000), # Vancouver East Victoria
        ('V5V',  66,  25_000), # Vancouver East Fraser
        ('V5W',  58,  30_000), # Vancouver East Sunset
        ('V5X',  56,  30_000), # Vancouver East Collingwood
        ('V5Y',  68,  25_000), # Vancouver Mount Pleasant
        ('V5Z',  72,  25_000), # Vancouver Fairview East
        ('V3M',  60,  50_000), # New Westminster
        ('V3N',  56,  40_000), # Burnaby South
        ('V5A',  60,  50_000), # Burnaby North
        ('V5B',  58,  40_000), # Burnaby East
        ('V5C',  60,  40_000), # Burnaby Heights
        ('V5E',  56,  35_000), # Burnaby South East
        ('V5G',  58,  40_000), # Burnaby Edmonds
        ('V5H',  56,  40_000), # Burnaby South Central
        ('V5J',  54,  40_000), # Burnaby Metrotown
        ('V6A',  62,  30_000), # East Van/Strathcona
        ('V6G',  72,  30_000), # Vancouver West End English Bay
        ('V6P',  64,  40_000), # Vancouver SW Marine
        ('V6V',  52,  60_000), # Richmond North
        ('V6X',  50,  60_000), # Richmond Central
        ('V6Y',  52,  50_000), # Richmond South
        ('V6Z',  66,  25_000), # Vancouver Yaletown
        ('V7A',  62,  30_000), # Richmond East
        ('V7B',  54,  20_000), # Richmond Airport
        ('V7C',  60,  35_000), # Richmond Southwest
        ('V7E',  62,  35_000), # Richmond Steveston
        ('V7G',  74,  35_000), # North Vancouver Deep Cove
        ('V7H',  76,  25_000), # North Van Lynn Valley
        ('V7J',  72,  30_000), # North Van Upper Lonsdale
        ('V7K',  70,  35_000), # North Van Lynn Valley mid
        ('V7P',  70,  40_000), # North Van Princess Park
        ('V7R',  88,  30_000), # North Van premium
        ('V7S',  86,  25_000), # West Van Caulfeild
        ('V7X',  74,  10_000), # Vancouver downtown east
        ('V7Y',  74,  10_000), # Vancouver downtown
        ('V8W',  62,  10_000), # Victoria downtown
        ('V8V',  66,  15_000), # Victoria James Bay
        ('V8P',  58,  20_000), # Saanich East
        ('V8R',  56,  20_000), # Saanich North
        ('V8S',  60,  15_000), # Oak Bay
        ('V8T',  56,  20_000), # Saanich West
        ('V8X',  54,  25_000), # Saanich Central
        ('V8Y',  58,  25_000), # Saanich Gordon Head
        ('V8Z',  52,  25_000), # Saanich SW
        ('V9A',  48,  20_000), # Esquimalt
        ('V3R',  44,  60_000), # Surrey North
        ('V3S',  42,  70_000), # Surrey Central
        ('V3T',  46,  60_000), # Surrey Newton
        ('V3V',  44,  60_000), # Surrey Cloverdale
        ('V3W',  42,  70_000), # Surrey Fleetwood
        ('V3X',  40,  65_000), # Surrey South
        ('V3Y',  40,  55_000), # Langley
        ('V3Z',  44,  55_000), # Port Coquitlam
        ('V4A',  38,  55_000), # Surrey White Rock
        # ON (M prefix) — Toronto
        ('M5V',  78,  35_000), # King West / Liberty Village
        ('M5J',  76,  15_000), # Harbourfront
        ('M4W',  86,  25_000), # Rosedale
        ('M5R',  84,  20_000), # Annex
        ('M4T',  80,  20_000), # Moore Park
        ('M5P',  80,  25_000), # Forest Hill
        ('M4V',  82,  20_000), # Deer Park
        ('M4N',  78,  25_000), # Lawrence Park
        ('M2K',  72,  30_000), # Bayview Village
        ('M2P',  74,  20_000), # St Andrews
        ('M2N',  70,  30_000), # Willowdale
        ('M3C',  66,  25_000), # Don Mills
        ('M4B',  60,  30_000), # East York
        ('M4C',  58,  35_000), # East York Wood
        ('M4E',  62,  25_000), # The Beach
        ('M4G',  66,  25_000), # Leaside
        ('M4H',  62,  25_000), # Thorncliffe
        ('M4J',  62,  30_000), # East Danforth
        ('M4K',  66,  25_000), # Danforth East
        ('M4L',  60,  30_000), # East End Danforth
        ('M4M',  62,  30_000), # South Riverdale
        ('M4P',  76,  20_000), # Davisville
        ('M4R',  74,  20_000), # North Toronto
        ('M4S',  72,  20_000), # Davisville Village
        ('M4X',  70,  15_000), # Cabbagetown
        ('M4Y',  72,  20_000), # Church-Wellesley
        ('M5A',  64,  20_000), # St Lawrence/Regent Park
        ('M5B',  62,  20_000), # Garden District
        ('M5C',  72,  10_000), # St James Town
        ('M5E',  70,  10_000), # Berczy Village
        ('M5G',  66,  10_000), # Discovery District
        ('M5H',  68,  10_000), # Bay Street
        ('M5K',  68,   5_000), # Design Exchange
        ('M5L',  66,   5_000), # Commerce Court
        ('M5N',  78,  20_000), # Roselawn
        ('M5S',  72,  25_000), # University of Toronto
        ('M5T',  68,  25_000), # Kensington Market
        ('M5W',  70,   5_000), # Stn A
        ('M5X',  72,   5_000), # First Canadian Place
        ('M6A',  60,  25_000), # Lawrence Heights
        ('M6B',  62,  20_000), # Glencairn
        ('M6C',  64,  20_000), # Humewood-Cedarvale
        ('M6G',  62,  25_000), # Christie Pits
        ('M6H',  60,  30_000), # Dufferin Grove
        ('M6J',  64,  25_000), # Trinity Bellwoods
        ('M6K',  62,  25_000), # Brockton Village
        ('M6M',  54,  30_000), # Mt. Dennis
        ('M6N',  52,  30_000), # Junction Area
        ('M6P',  62,  30_000), # High Park North
        ('M6R',  66,  25_000), # Roncesvalles
        ('M6S',  66,  25_000), # Swansea
        ('M8V',  60,  30_000), # New Toronto
        ('M8W',  56,  25_000), # Alderwood
        ('M8X',  68,  20_000), # Kingsway
        ('M8Y',  64,  25_000), # Old Mill
        ('M8Z',  60,  25_000), # Stonegate
        ('M9A',  64,  20_000), # Islington Ave
        ('M9B',  62,  30_000), # West Deane Park
        ('M9C',  60,  30_000), # Eringate
        ('M9M',  54,  30_000), # Humber Summit
        ('M9N',  52,  25_000), # Weston
        ('M9P',  56,  25_000), # Willowridge
        ('M9R',  54,  30_000), # Kingsview Village
        ('M9V',  50,  35_000), # Thistletown
        ('M9W',  48,  35_000), # Clairville
        ('M1B',  46,  40_000), # Malvern
        ('M1C',  48,  30_000), # Rouge Hill
        ('M1E',  46,  35_000), # West Hill
        ('M1G',  46,  35_000), # Woburn
        ('M1H',  46,  30_000), # Scarborough Village
        ('M1J',  44,  30_000), # Scarborough Village W
        ('M1K',  46,  30_000), # Kennedy Park
        ('M1L',  46,  30_000), # Clairlea
        ('M1M',  48,  30_000), # Cliffcrest
        ('M1N',  48,  25_000), # Birchcliffe
        ('M1P',  46,  35_000), # Dorset Park
        ('M1R',  46,  35_000), # Wexford
        ('M1S',  46,  35_000), # Agincourt
        ('M1T',  46,  30_000), # Clarks Corners
        ('M1V',  44,  40_000), # Milliken
        ('M1W',  44,  35_000), # L'Amoreaux
        ('M1X',  42,  30_000), # Upper Rouge
        ('L4B',  52,  40_000), # Richmond Hill
        ('L4C',  52,  45_000), # Richmond Hill South
        ('L4E',  50,  35_000), # Oak Ridges
        ('L4J',  54,  45_000), # Thornhill
        ('L4K',  52,  50_000), # Vaughan
        ('L4L',  50,  50_000), # Woodbridge
        ('L6A',  48,  50_000), # Maple
        ('L6B',  46,  30_000), # Markham East
        ('L3R',  50,  50_000), # Markham
        ('L3S',  48,  50_000), # Markham South
        ('L3T',  52,  30_000), # Thornhill Markham
        # Montreal
        ('H2Y',  62,  10_000), # Old Montreal
        ('H3G',  64,  20_000), # Concordia
        ('H2X',  60,  25_000), # Plateau Sud
        ('H2T',  62,  30_000), # Plateau Mont-Royal
        ('H2V',  64,  25_000), # Outremont
        ('H2W',  60,  20_000), # Milton-Parc
        ('H3T',  66,  20_000), # Côte-des-Neiges
        ('H3U',  64,  15_000), # Notre-Dame-de-Grâce West
        ('H3W',  62,  20_000), # Notre-Dame-de-Grâce
        ('H3X',  60,  20_000), # Snowdon
        ('H3Y',  68,  15_000), # Westmount Central
        ('H3Z',  72,  10_000), # Westmount premium
        ('H4A',  64,  20_000), # Notre-Dame-de-Grâce East
        ('H4B',  58,  20_000), # Verdun
        ('H4C',  56,  25_000), # Saint-Henri
        ('H4E',  54,  25_000), # Ville-Émard
        ('H4G',  52,  30_000), # LaSalle
        ('H4H',  50,  25_000), # Verdun South
        ('H4J',  48,  30_000), # LaSalle East
        ('H4K',  46,  30_000), # Pierrefonds
        ('H4L',  48,  30_000), # Saint-Laurent
        ('H4M',  50,  25_000), # Saint-Laurent Est
        ('H4N',  46,  30_000), # Saint-Michel
        ('H4P',  52,  20_000), # Côte-Saint-Luc
        ('H4R',  50,  25_000), # Cartierville
        ('H4S',  44,  25_000), # Bois-Franc
        ('H4T',  50,  25_000), # Mont-Royal
        ('H4V',  56,  20_000), # Hampstead
        ('H4W',  54,  20_000), # Côte-Saint-Luc
        ('H4X',  52,  20_000), # Lachine
        ('H4Y',  46,  15_000), # Dorval
        ('H4Z',  56,  10_000), # Montréal downtown
        ('H1A',  40,  35_000), # Pointe-aux-Trembles
        ('H1B',  42,  30_000), # Rivière-des-Prairies
        ('H1C',  42,  25_000), # Pointe-aux-Trembles North
        ('H1E',  42,  30_000), # Montréal-Est
        ('H1G',  42,  30_000), # Anjou
        ('H1H',  44,  30_000), # Montréal-Nord
        ('H1J',  44,  30_000), # Saint-Léonard
        ('H1K',  44,  30_000), # Saint-Léonard East
        ('H1L',  44,  30_000), # Villeray
        ('H1M',  44,  30_000), # Rosemont
        ('H1N',  42,  30_000), # Hochelaga
        ('H1P',  42,  30_000), # Saint-Léonard
        ('H1R',  44,  30_000), # Villeray North
        ('H1S',  44,  30_000), # Rosemont North
        ('H1T',  46,  30_000), # Rosemont East
        ('H1V',  48,  25_000), # Rosemont Village
        ('H1W',  48,  25_000), # Hochelaga-Maisonneuve
        ('H1X',  50,  25_000), # Maisonneuve
        ('H1Y',  52,  25_000), # Rosemont East premium
        ('H1Z',  46,  25_000), # Villeray East
        ('H2A',  44,  25_000), # Rosemont
        ('H2B',  42,  25_000), # Ahuntsic
        ('H2C',  44,  25_000), # Ahuntsic East
        ('H2E',  46,  20_000), # Villeray
        ('H2G',  48,  25_000), # Rosemont
        ('H2H',  50,  20_000), # Plateau West
        ('H2J',  54,  25_000), # Plateau
        ('H2K',  52,  25_000), # Plateau East
        ('H2L',  56,  25_000), # Plateau premium
        ('H2M',  44,  25_000), # Ahuntsic premium
        ('H2N',  44,  25_000), # Ahuntsic North
        ('H2P',  44,  25_000), # Park-Extension
        ('H2R',  46,  25_000), # Park-Extension premium
        ('H2S',  50,  20_000), # Mile End
        ('H2Z',  60,  10_000), # downtown Montreal
        ('H3A',  62,  15_000), # McGill
        ('H3B',  60,  10_000), # downtown Montreal
        ('H3C',  56,  15_000), # Griffintown
        ('H3E',  54,  20_000), # Verdun Sud premium
        ('H3H',  62,  20_000), # Westmount East
        ('H3J',  58,  20_000), # Saint-Henri premium
        ('H3K',  52,  20_000), # Saint-Henri East
        ('H3L',  44,  30_000), # Cartierville South
        ('H3M',  44,  25_000), # Ville Saint-Laurent
        ('H3N',  46,  25_000), # Côte-des-Neiges
        ('H3P',  50,  20_000), # Snowdon East
        ('H3R',  54,  20_000), # Hampstead South
        ('H3S',  56,  20_000), # Côte-des-Neiges premium
        ('H3V',  58,  15_000), # Outremont premium
        ('J3H',  38,  30_000), # Longueuil
        ('J4G',  38,  30_000), # Longueuil West
        ('J4H',  38,  30_000), # Longueuil East
        ('J4K',  40,  25_000), # Greenfield Park
        ('H7A',  42,  30_000), # Laval East
        ('H7B',  44,  25_000), # Laval South
        ('H7C',  44,  30_000), # Laval Central
        ('H7E',  44,  30_000), # Laval North
        ('H7G',  46,  30_000), # Laval premium
        ('H7H',  42,  25_000), # Laval West
        ('H7J',  44,  25_000), # Laval Central
        ('H7K',  46,  25_000), # Laval premium
        ('H7L',  44,  30_000), # Laval North
        ('H7M',  42,  30_000), # Laval East
        ('H7N',  42,  30_000), # Laval East
        ('H7P',  44,  25_000), # Laval
        ('H7R',  46,  25_000), # Laval premium
        ('H7S',  44,  20_000), # Laval
        ('H7T',  46,  20_000), # Laval
        ('H7V',  44,  20_000), # Laval
        ('H7W',  44,  20_000), # Laval
        ('H7X',  46,  15_000), # Laval premium
        ('H7Y',  48,  10_000), # Laval premium
        ('T2P',  52,  20_000), # Calgary downtown
        ('T2E',  48,  30_000), # Calgary NE
        ('T3A',  50,  35_000), # Calgary NW
        ('T3B',  52,  30_000), # Calgary NW premium
        ('T3C',  56,  20_000), # Calgary SW
        ('T3E',  54,  25_000), # Calgary SW mid
        ('T3G',  50,  30_000), # Calgary NW
        ('T3H',  62,  30_000), # Calgary SW premium
        ('T3J',  46,  35_000), # Calgary NE
        ('T3K',  48,  30_000), # Calgary N
        ('T3L',  52,  30_000), # Calgary NW
        ('T3M',  50,  35_000), # Calgary SE
        ('T3N',  46,  30_000), # Calgary N
        ('T3P',  48,  25_000), # Calgary N
        ('T3R',  46,  25_000), # Calgary N
        ('T3Z',  58,  15_000), # Calgary SW premium
        ('T2A',  40,  30_000), # Calgary E
        ('T2B',  42,  30_000), # Calgary E
        ('T2C',  42,  25_000), # Calgary SE
        ('T2G',  44,  15_000), # Calgary SE
        ('T2H',  50,  25_000), # Calgary S
        ('T2J',  52,  25_000), # Calgary S premium
        ('T2K',  48,  25_000), # Calgary N
        ('T2L',  50,  25_000), # Calgary NW
        ('T2M',  48,  25_000), # Calgary NW
        ('T2N',  60,  20_000), # Calgary NW premium
        ('T2R',  54,  20_000), # Calgary SW
        ('T2S',  58,  20_000), # Calgary SW premium
        ('T2T',  62,  20_000), # Calgary SW premium
        ('T2V',  56,  20_000), # Calgary S
        ('T2W',  54,  25_000), # Calgary SW
        ('T2X',  50,  30_000), # Calgary SE
        ('T2Y',  52,  30_000), # Calgary S
        ('T2Z',  48,  30_000), # Calgary SE
    ],

    # ── BRASIL — primeros 5 dígitos del CEP ──────────────────────
    # Referencia: 01310 (Jardins SP) = 100
    'BR': [
        # São Paulo premium
        ('01310', 100,  30_000), # Jardins / Paulista
        ('01401', 100,  20_000), # Jardins
        ('01422', 96,   20_000), # Jardins / Cerqueira César
        ('01452', 92,   15_000), # Pinheiros
        ('01310',  98,  25_000), # Av Paulista
        ('04535',  94,  20_000), # Itaim Bibi premium
        ('04552',  90,  20_000), # Itaim Bibi
        ('04551',  90,  20_000), # Vila Olímpia
        ('04101',  84,  25_000), # Vila Nova Conceição
        ('04543',  82,  15_000), # Jardim Europa
        ('01419',  82,  20_000), # Bela Vista
        ('01013',  78,  25_000), # República
        ('01046',  74,  20_000), # Consolação
        ('04039',  72,  25_000), # Moema
        ('04023',  70,  25_000), # Planalto Paulista
        ('04002',  68,  25_000), # Vila Mariana
        ('01303',  70,  30_000), # Centro
        ('03310',  52,  50_000), # Tatuapé
        ('02210',  46,  60_000), # Santana
        ('08210',  40,  80_000), # São Mateus
        ('07750',  36,  80_000), # Guarulhos
        ('09210',  40,  60_000), # Santo André
        # Rio premium
        ('22411',  86,  15_000), # Leblon
        ('22421',  86,  15_000), # Leblon
        ('22430',  84,  20_000), # Ipanema
        ('22450',  82,  20_000), # Ipanema
        ('22461',  80,  15_000), # Copacabana premium
        ('22070',  76,  20_000), # Botafogo
        ('22281',  74,  20_000), # Flamengo
        ('22411',  86,  15_000), # Leblon
        ('22620',  66,  30_000), # Barra da Tijuca
        ('22793',  62,  40_000), # Barra da Tijuca
        ('20040',  60,  30_000), # Centro Rio
        ('20050',  58,  30_000), # Centro Rio
        ('21040',  38,  60_000), # São Cristóvão
        ('21770',  36,  70_000), # Complexo do Alemão
        # Brasília
        ('70910',  54,  30_000), # Lago Sul
        ('71635',  52,  25_000), # Lago Norte
        ('70200',  48,  40_000), # Asa Sul
        ('70712',  46,  40_000), # Asa Norte
        ('72220',  36,  60_000), # Ceilândia
        # Outras
        ('88015',  48,  30_000), # Florianópolis Centro
        ('88048',  52,  15_000), # Florianópolis premium
        ('30130',  44,  50_000), # Belo Horizonte Centro
        ('30140',  46,  40_000), # BH Savassi
        ('90010',  44,  40_000), # Porto Alegre Centro
        ('80010',  44,  40_000), # Curitiba Centro
        ('80420',  48,  30_000), # Curitiba Batel
        ('74000',  40,  60_000), # Goiânia
        ('50000',  38,  60_000), # Recife
        ('60000',  36,  80_000), # Fortaleza
        ('40000',  38,  80_000), # Salvador
        ('69000',  36,  70_000), # Manaus
        ('66000',  34,  60_000), # Belém
    ],

    # ── ARGENTINA — prefijo postal (2 dígitos numéricos para GBA, letras para interior)
    # Referencia: C1425 (Palermo Buenos Aires) = 100
    'AR': [
        # Buenos Aires Ciudad (código "C")
        ('C142', 100, 120_000), # Palermo / Colegiales
        ('C118', 94,  80_000), # Recoleta / Retiro
        ('C108', 96,  40_000), # Puerto Madero
        ('C140', 98,  60_000), # Palermo / Villa Crespo
        ('C138', 90,  60_000), # Belgrano
        ('C136', 92,  70_000), # Nuñez / Saavedra
        ('C127', 84,  90_000), # Caballito
        ('C141', 82,  70_000), # Villa Crespo / Almagro
        ('C113', 78,  80_000), # Almagro / Balvanera
        ('C110', 76,  70_000), # San Cristóbal
        ('C112', 72,  80_000), # Parque Patricios
        ('C123', 68,  90_000), # Flores
        ('C146', 62,  80_000), # Mataderos / Liniers
        ('C143', 56,  80_000), # Villa del Parque
        ('C147', 50,  90_000), # Villa Lugano
        # GBA Norte (códigos B)
        ('B161', 68, 150_000), # San Isidro premium
        ('B160', 64, 140_000), # San Isidro
        ('B162', 62, 140_000), # Vicente López
        ('B163', 58, 140_000), # Vicente López Sur
        ('B166', 46, 180_000), # Tigre
        ('B167', 42, 120_000), # San Fernando
        ('B167', 46, 150_000), # Pilar
        # GBA Oeste/Sur
        ('B171', 44, 250_000), # Morón
        ('B172', 42, 150_000), # Ituzaingó
        ('B170', 44, 180_000), # Tres de Febrero
        ('B176', 44, 160_000), # Avellaneda
        ('B184', 42, 220_000), # Lomas de Zamora
        ('B187', 40, 280_000), # Quilmes
        ('B186', 38, 280_000), # Almirante Brown
        ('B179', 36, 800_000), # La Matanza
        # Interior — primeras letras
        ('X500', 54, 700_000), # Córdoba Capital
        ('X510', 48, 200_000), # Córdoba Noroeste
        ('M553', 54, 125_000), # Mendoza Capital
        ('S200', 46, 500_000), # Rosario Centro
        ('S211', 42, 200_000), # Rosario Sur
        ('R838', 46, 170_000), # Neuquén
        ('B760', 46,  90_000), # Mar del Plata
        ('P956', 44, 100_000), # Comodoro Rivadavia
        ('B800', 40, 155_000), # Bahía Blanca
        ('S300', 38, 260_000), # Santa Fe Capital
        ('A420', 38, 300_000), # Salta Capital
        ('B190', 38, 430_000), # La Plata
        ('W380', 34, 195_000), # Corrientes
        ('N354', 34, 160_000), # Posadas
        ('T400', 34, 275_000), # Tucumán
        ('X580', 38,  90_000), # Río Cuarto
        ('J521', 34,  60_000), # San Juan
        ('H350', 28, 195_000), # Resistencia
        ('G360', 24, 140_000), # Formosa
    ],

    # ── MÉXICO — 2 primeros dígitos del CP = estado ──────────────
    # Referencia: 11 (Miguel Hidalgo CDMX) = 100
    'MX': [
        # CDMX (00-16)
        ('11', 100, 370_000), # Miguel Hidalgo (Polanco, Lomas)
        ('03',  90, 430_000), # Benito Juárez (Narvarte, Del Valle)
        ('05',  80, 200_000), # Cuajimalpa (Santa Fe)
        ('01',  78, 280_000), # Álvaro Obregón (Lomas Plateros)
        ('04',  72, 620_000), # Coyoacán
        ('06',  62, 530_000), # Cuauhtémoc (Juárez, Roma)
        ('02',  54, 400_000), # Azcapotzalco
        ('09',  50, 680_000), # Tlalpan
        ('07',  46, 390_000), # Iztacalco
        ('08',  42, 1_200_000), # Gustavo A. Madero
        ('10',  38, 1_200_000), # Iztapalapa
        ('13',  34, 450_000), # Xochimilco / Tláhuac
        # Estado de México
        ('52',  60, 280_000), # Huixquilucan (Santa Fe / Interlomas)
        ('53',  54, 870_000), # Naucalpan
        ('50',  46, 700_000), # Tlalnepantla
        ('54',  46, 520_000), # Atizapán
        ('55',  36, 1_700_000), # Ecatepec
        ('57',  34, 1_100_000), # Nezahualcóyotl
        ('56',  36, 1_000_000), # Chimalhuacán / Los Reyes
        # Nuevo León (Monterrey 6x)
        ('66',  86, 130_000), # San Pedro Garza García
        ('64',  60, 1_100_000), # Monterrey
        ('67',  48, 700_000), # Guadalupe / San Nicolás
        ('65',  46, 600_000), # Apodaca
        ('68',  44, 450_000), # Santa Catarina / General Escobedo
        # Jalisco (Guadalajara 4x)
        ('45',  54, 1_400_000), # Zapopan
        ('44',  50, 1_500_000), # Guadalajara
        ('46',  42, 700_000), # Tlaquepaque / Tonalá
        ('48',  36, 700_000), # Puerto Vallarta y zona jal
        # Baja California (Tijuana 2x)
        ('22',  50, 1_800_000), # Tijuana
        ('21',  46, 950_000), # Mexicali
        # Quintana Roo (Cancún 7x)
        ('77',  54, 930_000), # Cancún
        ('76',  48, 800_000), # Querétaro
        ('97',  46, 960_000), # Mérida
        ('83',  40, 850_000), # Hermosillo
        ('31',  40, 880_000), # Chihuahua
        ('32',  40, 1_500_000), # Ciudad Juárez
        ('58',  40, 760_000), # Morelia
        ('50',  38, 870_000), # Toluca
        ('72',  38, 1_500_000), # Puebla
        ('20',  38, 800_000), # Aguascalientes
        ('78',  36, 840_000), # San Luis Potosí
        ('25',  36, 860_000), # Saltillo
        ('27',  36, 670_000), # Torreón
        ('80',  36, 900_000), # Culiacán
        ('68',  30, 290_000), # Oaxaca
        ('21',  30, 700_000), # Mexicali interior
        ('90',  28, 520_000), # Tlaxcala / Hidalgo
        ('39',  26, 700_000), # Acapulco
        ('91',  30, 520_000), # Veracruz
        ('96',  26, 400_000), # Coatzacoalcos / Tabasco
        ('86',  26, 600_000), # Villahermosa (Tabasco)
        ('29',  24, 400_000), # Tuxtla Gutiérrez (Chiapas)
        ('01',  26, 300_000), # Tapachula
    ],

    # ── COLOMBIA — primeros 2 dígitos ────────────────────────────
    # Referencia: 11 (Bogotá) = 100
    'CO': [
        # Bogotá (11xxxx)
        ('11001', 100,  50_000), # Chapinero / Chicó
        ('11022',  90,  80_000), # Usaquén
        ('11011',  78,  60_000), # Teusaquillo
        ('11050',  66,  90_000), # Suba premium
        ('11028',  60, 100_000), # Barrios Unidos / Engativá
        ('11071',  52, 120_000), # Kennedy
        ('11081',  44, 110_000), # Bosa
        ('11001',  78, 200_000), # Bogotá Centro
        # Medellín (05xxxx)
        ('05001',  84,  60_000), # El Poblado / Laureles
        ('05030',  72,  80_000), # Envigado / Sabaneta
        ('05001',  60, 200_000), # Medellín general
        ('05021',  50, 120_000), # Bello / Copacabana
        ('05045',  44, 140_000), # Itagüí / La Estrella
        # Cali (76xxxx)
        ('76001',  64, 150_000), # Cali norte
        ('76054',  52, 100_000), # Cali sur
        # Barranquilla (08xxxx)
        ('08001',  60, 120_000), # Barranquilla norte
        ('08433',  44, 100_000), # Soledad
        # Cartagena (13xxxx)
        ('13001',  72,  80_000), # Cartagena premium
        ('13430',  48,  60_000), # Cartagena popular
        # Bucaramanga (68xxxx)
        ('68001',  52,  60_000), # Bucaramanga
        # Santa Marta (47xxxx)
        ('47001',  56,  50_000), # Santa Marta
        # Pereira (66xxxx)
        ('66001',  52,  50_000), # Pereira
        # Manizales (17xxxx)
        ('17001',  52,  45_000), # Manizales
        # Cúcuta (54xxxx)
        ('54001',  40,  70_000), # Cúcuta
        # Ibagué (73xxxx)
        ('73001',  44,  55_000), # Ibagué
        # Villavicencio (50xxxx)
        ('50001',  46,  55_000), # Villavicencio
        # Armenia (63xxxx)
        ('63001',  44,  30_000), # Armenia
        # Pasto (52xxxx)
        ('52001',  36,  35_000), # Pasto
        # Montería (23xxxx)
        ('23001',  36,  45_000), # Montería
    ],

    # ── PERÚ — primeros 2 dígitos del CP ─────────────────────────
    # Referencia: 15 (Lima premium) = 100
    'PE': [
        ('15036', 100, 15_000), # Miraflores premium
        ('15048',  96, 20_000), # San Isidro
        ('15063',  92, 10_000), # Barranco
        ('15012',  88, 25_000), # La Molina
        ('15038',  82, 50_000), # Surco
        ('15035',  80, 30_000), # San Borja
        ('15081',  72, 40_000), # Jesús María
        ('15084',  70, 25_000), # Magdalena
        ('15083',  70, 30_000), # Pueblo Libre
        ('15082',  68, 50_000), # San Miguel
        ('15046',  68, 20_000), # Lince
        ('15085',  64, 30_000), # Breña
        ('15047',  62, 35_000), # Surquillo
        ('15001',  58, 80_000), # Lima Cercado
        ('15013',  52, 60_000), # La Victoria
        ('15304',  46, 100_000), # Los Olivos
        ('15317',  36, 120_000), # Carabayllo
        ('15824',  32, 150_000), # Villa El Salvador
        ('15088',  28, 350_000), # SJL
        ('15816',  28, 150_000), # Villa María del Triunfo
        # Provincias
        ('08001',  58, 100_000), # Cusco
        ('04001',  50, 200_000), # Arequipa
        ('04013',  64,  10_000), # Yanahuara/Cayma (Arequipa premium)
        ('13001',  42, 300_000), # Trujillo
        ('14001',  42, 200_000), # Chiclayo
        ('20001',  38, 300_000), # Piura
        ('16001',  36, 180_000), # Iquitos
        ('12001',  38, 150_000), # Huancayo
        ('06001',  42, 110_000), # Tacna
        ('07001',  36,  90_000), # Ica
        ('21001',  26,  90_000), # Juliaca
        ('22001',  26,  50_000), # Puno
        ('25001',  26, 140_000), # Pucallpa
        ('25031',  26,  80_000), # Huánuco
        ('06006',  36,  75_000), # Moquegua
    ],

    # ── INDIA — primeros 3 dígitos del PIN ───────────────────────
    # Referencia: 400 (South Mumbai) = 100
    'IN': [
        # Mumbai (400xxx)
        ('400001',  84,  60_000), # Fort / CST
        ('400005',  90,  30_000), # Colaba
        ('400006',  92,  15_000), # Malabar Hill
        ('400007',  88,  25_000), # Grant Road
        ('400008',  80,  40_000), # Byculla
        ('400010',  76,  50_000), # Mazagon
        ('400011',  72,  50_000), # Chunabhatti
        ('400012',  68,  55_000), # Dadar
        ('400013',  64,  60_000), # Sion
        ('400014',  60,  60_000), # Matunga
        ('400016',  94,  30_000), # Mahim
        ('400017',  88,  30_000), # Dharavi (gentrifying)
        ('400018',  86,  25_000), # Worli
        ('400019',  84,  30_000), # Prabhadevi
        ('400022',  78,  30_000), # Chembur
        ('400025',  98, 100_000), # Pali Hill / Bandra West
        ('400026',  90,  30_000), # Bandra
        ('400028',  94,  25_000), # Juhu
        ('400029',  90,  20_000), # Santacruz West
        ('400049',  86,  40_000), # Andheri West premium
        ('400051',  80,  50_000), # Andheri West
        ('400053',  76,  60_000), # Andheri East
        ('400058',  72,  70_000), # Goregaon West
        ('400063',  70,  80_000), # Borivali West
        ('400070',  72,  60_000), # Chembur East
        ('400072',  68,  80_000), # Powai
        ('400076',  70,  70_000), # Andheri East premium
        ('400080',  66,  80_000), # Mulund
        ('400086',  64,  80_000), # Ghatkopar
        ('400088',  60,  80_000), # Vikhroli
        ('400601',  72, 100_000), # Thane West
        ('400606',  68,  80_000), # Thane East
        ('400614',  62, 100_000), # Navi Mumbai premium
        ('400705',  60, 100_000), # Panvel
        # Delhi (110xxx)
        ('110001',  82,  20_000), # Connaught Place
        ('110003',  80,  25_000), # Lodi Estate
        ('110010',  88,  10_000), # Lutyens
        ('110011',  76,  30_000), # Karol Bagh
        ('110016',  80,  30_000), # Hauz Khas / GK
        ('110017',  82,  30_000), # Green Park
        ('110019',  78,  30_000), # Kalkaji / GK
        ('110020',  80,  25_000), # Lajpat Nagar
        ('110021',  82,  20_000), # South Extension
        ('110022',  78,  30_000), # CR Park
        ('110024',  80,  25_000), # Jangpura / Bhogal
        ('110025',  76,  30_000), # Patel Nagar
        ('110026',  72,  30_000), # Patparganj
        ('110029',  80,  25_000), # Greater Kailash
        ('110030',  84,  15_000), # Vasant Vihar
        ('110048',  86,  20_000), # Saket / DLF
        ('110049',  82,  25_000), # Mehrauli / Saket
        ('110065',  76,  30_000), # Dwarka premium
        ('110075',  72,  40_000), # Dwarka
        ('110091',  60,  50_000), # Shahdara
        # Bangalore (560xxx)
        ('560001',  72,  20_000), # MG Road
        ('560008',  88,  20_000), # Indiranagar
        ('560034',  86,  20_000), # Koramangala
        ('560037',  80,  25_000), # Jayanagar
        ('560047',  76,  25_000), # JP Nagar
        ('560066',  82,  30_000), # Whitefield premium
        ('560103',  78,  30_000), # Whitefield
        ('560076',  72,  35_000), # Electronic City premium
        ('560100',  68,  40_000), # Electronic City
        # Hyderabad (500xxx)
        ('500034',  92,  20_000), # Banjara Hills
        ('500033',  86,  20_000), # Jubilee Hills
        ('500082',  84,  30_000), # Gachibowli
        ('500019',  78,  30_000), # Kondapur
        ('500032',  72,  25_000), # Madhapur / Hi-Tech City
        ('500073',  68,  30_000), # Kukatpally
        ('500062',  62,  40_000), # Secunderabad
        ('500003',  58,  60_000), # Hyderabad Old City
        # Chennai (600xxx)
        ('600002',  78,  30_000), # Anna Nagar
        ('600004',  76,  20_000), # Nungambakkam
        ('600006',  82,  20_000), # Adyar
        ('600014',  74,  25_000), # Gopalapuram
        ('600017',  78,  25_000), # Alwarpet
        ('600041',  72,  30_000), # Velachery
        # Kolkata (700xxx)
        ('700019',  64,  20_000), # Park Street
        ('700016',  60,  25_000), # Ballygunge
        ('700001',  56,  30_000), # Kolkata CBD
        ('700032',  52,  35_000), # Behala
        # Pune (411xxx)
        ('411001',  68,  30_000), # Pune central
        ('411006',  86,  20_000), # Koregaon Park
        ('411028',  74,  25_000), # Aundh
        ('411045',  72,  25_000), # Baner
        # Others
        ('380001',  42,  60_000), # Ahmedabad
        ('380054',  52,  30_000), # Ahmedabad premium
        ('395001',  36,  80_000), # Surat
        ('302001',  40,  60_000), # Jaipur
        ('226001',  36,  80_000), # Lucknow
        ('682001',  56,  30_000), # Kochi
        ('462001',  34,  50_000), # Bhopal
        ('440001',  38,  60_000), # Nagpur
        ('208001',  32,  80_000), # Kanpur
    ],

    # ── SUDÁFRICA — primeros 1-2 dígitos ─────────────────────────
    # Referencia: 80 (Ciudad del Cabo premium) = 100
    'ZA': [
        # Ciudad del Cabo (7xxx)
        ('7800', 100,  20_000), # Clifton / Fresnaye
        ('7806',  92,  25_000), # Camps Bay
        ('7708',  88,  25_000), # Constantia
        ('7700',  84,  30_000), # Cape Town City Bowl / Gardens
        ('7441',  80,  20_000), # Sea Point / Green Point
        ('7550',  74,  40_000), # Claremont / Newlands
        ('7530',  70,  50_000), # Bellville premium
        ('7580',  62,  40_000), # Southern Suburbs
        ('7460',  50,  30_000), # Milnerton
        ('7490',  44,  40_000), # Stellenbosch
        ('7800',  86,  15_000), # Bantry Bay
        ('7945',  38,  50_000), # Cape Town South
        ('7780',  32,  80_000), # Mitchells Plain / Khayelitsha
        # Johannesburgo (21xx)
        ('2196',  86,  40_000), # Sandton / Rosebank
        ('2196',  92,  30_000), # Sandhurst
        ('2193',  78,  30_000), # Hyde Park / Dunkeld
        ('2198',  72,  25_000), # Morningside
        ('2195',  76,  30_000), # Parktown
        ('2000',  62,  30_000), # Johannesburg CBD
        ('2092',  68,  35_000), # Craighall
        ('2135',  60,  40_000), # Bryanston
        ('2157',  64,  40_000), # Fourways
        ('1685',  70,  30_000), # Midrand premium
        ('2090',  56,  50_000), # Randburg
        ('1709',  46,  60_000), # Northriding / Roodepoort
        ('1804',  36, 100_000), # Soweto
        ('1430',  44,  80_000), # Boksburg
        # Pretoria (0xxx)
        ('0081',  68,  40_000), # Waterkloof / Centurion
        ('0157',  66,  40_000), # Menlyn / Moreleta
        ('0001',  52,  40_000), # Pretoria CBD
        ('0082',  58,  40_000), # Hatfield / Arcadia
        ('0028',  44,  50_000), # Lynnwood / Faerie Glen
        # Durban (4xxx)
        ('4001',  52,  30_000), # Durban CBD
        ('4320',  76,  20_000), # Umhlanga Rocks
        ('4093',  68,  25_000), # Durban North
        ('4091',  62,  30_000), # Berea
        ('4052',  46,  40_000), # Pinetown
        # Otras
        ('6001',  38,  30_000), # Port Elizabeth / Gqeberha
        ('1244',  34,  40_000), # Nelspruit / Mbombela
        ('9301',  32,  40_000), # Bloemfontein
        ('5201',  32,  30_000), # East London
        ('0699',  32,  25_000), # Polokwane
        ('8301',  28,  30_000), # Kimberley
    ],

    # ── VENEZUELA — primeros 4 dígitos ───────────────────────────
    # Referencia: 1060 (Chacao-Las Mercedes) = 100
    'VE': [
        ('1060', 100,  80_000), # Chacao / Las Mercedes
        ('1080',  88,  60_000), # Baruta / El Hatillo
        ('1070',  80, 100_000), # Chacao / Altamira
        ('1040',  66, 200_000), # Caracas Centro-Norte
        ('1050',  62, 150_000), # Caracas Libertador premium
        ('1020',  52, 300_000), # Caracas Libertador
        ('1030',  46, 400_000), # Caracas Libertador Sur
        ('1010',  42, 500_000), # Caracas Centro histórico
        ('1015',  38, 400_000), # Petare
        ('2001',  50, 300_000), # Valencia premium
        ('2005',  44, 200_000), # Valencia popular
        ('2101',  50, 180_000), # Maracay
        ('4001',  42, 500_000), # Maracaibo
        ('3001',  42, 220_000), # Barquisimeto
        ('8001',  42, 160_000), # Ciudad Guayana
        ('6001',  42,  80_000), # Barcelona / Anzoátegui
        ('6101',  34, 120_000), # Maturín
        ('5101',  34, 130_000), # San Cristóbal
        ('6301',  34,  70_000), # Cumaná
    ],

    # ── URUGUAY — primeros 4 dígitos ─────────────────────────────
    # Referencia: 1300 (Pocitos/Carrasco) = 100
    'UY': [
        ('11300', 100,  30_000), # Pocitos premium
        ('11500',  88,  25_000), # Carrasco
        ('11400',  84,  30_000), # Malvín / Punta Gorda
        ('11600',  80,  20_000), # Buceo / Parque Rodó
        ('11200',  76,  30_000), # Cordón premium
        ('11100',  72,  35_000), # Centro Montevideo
        ('11000',  68,  50_000), # Montevideo Central
        ('11800',  62,  40_000), # Sayago / Casavalle
        ('12000',  54, 100_000), # Montevideo Sur
        ('20100',  88,  20_000), # Punta del Este
        ('20000',  72,  50_000), # Maldonado
        ('97000',  42,  30_000), # Colonia del Sacramento
        ('15000',  38,  80_000), # Las Piedras
        ('16000',  36, 200_000), # Canelones
        ('50000',  32,  40_000), # Salto
        ('60000',  32,  35_000), # Paysandú
        ('40000',  26,  30_000), # Rivera
        ('45000',  26,  25_000), # Tacuarembó
        ('30000',  24,  20_000), # Artigas
    ],

    # ── ECUADOR — primeros 2 dígitos ─────────────────────────────
    # Referencia: 17 (Quito Norte) = 100
    'EC': [
        ('170',  100,  60_000), # Quito Norte premium
        ('171',   88,  80_000), # Quito Norte
        ('172',   76, 100_000), # Quito Centro-Norte
        ('173',   62, 120_000), # Quito Centro
        ('174',   50, 150_000), # Quito Sur
        ('090',   90,  60_000), # Samborondón / Guayaquil Norte
        ('091',   74, 200_000), # Guayaquil Norte
        ('092',   58, 300_000), # Guayaquil Centro
        ('093',   44, 400_000), # Guayaquil Sur
        ('010',   78,  80_000), # Cuenca Norte
        ('011',   62, 100_000), # Cuenca
        ('130',   50,  80_000), # Manta
        ('180',   44, 100_000), # Ambato
        ('070',   44,  80_000), # Machala
        ('230',   44,  80_000), # Santo Domingo
        ('110',   44,  60_000), # Loja
        ('130',   38,  80_000), # Portoviejo
    ],

    # ── BOLIVIA — primeros 4 dígitos ─────────────────────────────
    # Referencia: 0700 (Zona Sur Santa Cruz) = 100
    'BO': [
        ('0700', 100,  80_000), # Santa Cruz Zona Sur
        ('0705',  88, 200_000), # Santa Cruz 2do anillo
        ('0710',  72, 300_000), # Santa Cruz 3er anillo
        ('0720',  56, 500_000), # Santa Cruz anillos ext
        ('0900',  88,  80_000), # La Paz Zona Sur / Calacoto
        ('0901',  76, 100_000), # La Paz Sopocachi
        ('0902',  62, 150_000), # La Paz Miraflores
        ('0910',  44, 300_000), # La Paz Centro
        ('0920',  28, 300_000), # El Alto
        ('0600',  52, 100_000), # Cochabamba premium
        ('0601',  44, 200_000), # Cochabamba popular
        ('1000',  44,  60_000), # Sucre
        ('0400',  36,  80_000), # Oruro
        ('0500',  44,  60_000), # Tarija
        ('0800',  28,  80_000), # Potosí
    ],

    # ── PARAGUAY — primeros 4 dígitos ────────────────────────────
    # Referencia: 1209 (Asunción premium) = 100
    'PY': [
        ('1209', 100,  20_000), # Asunción premium (Villa Morra)
        ('1204',  88,  25_000), # Asunción Manorá
        ('1202',  78,  30_000), # Asunción Centro-Norte
        ('1201',  66,  50_000), # Asunción Centro
        ('1227',  56,  80_000), # Asunción Sur
        ('3900',  50,  60_000), # Ciudad del Este premium
        ('3901',  44, 100_000), # Ciudad del Este popular
        ('2760',  44,  80_000), # San Lorenzo
        ('2300',  44,  80_000), # Luque
        ('2310',  38,  80_000), # Fernando de la Mora
        ('2323',  38,  80_000), # Lambaré
        ('2780',  38,  80_000), # Capiatá
        ('2000',  42,  60_000), # Encarnación
        ('2300',  36,  60_000), # Mariano Roque Alonso
    ],

    # ── NIGERIA — primeros 3 dígitos ─────────────────────────────
    # Referencia: 101 (Ikoyi Lagos) = 100
    'NG': [
        ('101',  100,  60_000), # Ikoyi
        ('101',   88, 100_000), # Victoria Island
        ('105',   78, 150_000), # Lekki phase 1
        ('100',   58, 200_000), # Ikeja GRA
        ('101',   70, 100_000), # Oniru / Lekki
        ('106',   56, 150_000), # Ajah
        ('102',   44, 250_000), # Surulere
        ('103',   36, 400_000), # Ikeja popular
        ('100',   34, 800_000), # Lagos Mainland
        ('234',  100,  60_000), # Maitama Abuja
        ('900',   84, 100_000), # Maitama
        ('902',   72, 100_000), # Wuse II
        ('901',   60, 150_000), # Garki
        ('903',   50, 200_000), # Abuja popular
        ('500',   60,  60_000), # Port Harcourt GRA
        ('500',   44, 200_000), # Port Harcourt popular
        ('200',   30, 400_000), # Ibadan
        ('700',   28, 500_000), # Kano
        ('400',   32, 100_000), # Enugu
        ('460',   30, 100_000), # Owerri
        ('960',   26, 200_000), # Kaduna
        ('930',   24, 200_000), # Jos
        ('810',   22, 100_000), # Benin City
        ('600',   22, 100_000), # Aba
        ('640',   18, 150_000), # Maiduguri
        ('840',   18, 100_000), # Zaria
    ],
}


# ══════════════════════════════════════════════════════════════
# FUNCIONES PRINCIPALES
# ══════════════════════════════════════════════════════════════

def process_prefix_data(country: str) -> list[dict]:
    """Convierte POSTAL_PREFIX_DATA → formato CommuneMarketData."""
    entries = POSTAL_PREFIX_DATA.get(country, [])
    if not entries:
        return []
    max_index = max(e[1] for e in entries)
    cpm_base  = CPM_BASE_BY_COUNTRY.get(country, 5.0)
    seen = set()
    results = []
    for prefix, income_index, population in entries:
        if prefix in seen:
            continue
        seen.add(prefix)
        tier = get_se_tier(income_index)
        cpm  = calculate_cpm(income_index, cpm_base)
        results.append({
            'country':      country,
            'commune':      prefix,
            'income_index': float(income_index),
            'cpm_usd':      cpm,
            'se_tier':      tier,
            'price_m2_avg': 0,
            'population':   population,
            'updated_at':   None,
        })
    return results


def run_zip_import(country: str) -> dict:
    """Dispatcher principal. Llama Census API para US, prefijo para el resto."""
    if country == 'US':
        raw, errors = fetch_all_us_zips()
        data = process_us_zip_data(raw)
        return {'data': data, 'errors': errors, 'total': len(data)}

    if country in POSTAL_PREFIX_DATA:
        data = process_prefix_data(country)
        return {'data': data, 'errors': [], 'total': len(data)}

    return {'data': [], 'errors': [{'error': f'{country} not implemented'}], 'total': 0}


def run_all_countries_import() -> dict:
    """Importa todos los países disponibles."""
    all_data, all_errors, total = [], [], 0
    all_countries = ['US'] + list(POSTAL_PREFIX_DATA.keys())
    for cc in all_countries:
        result = run_zip_import(cc)
        all_data.extend(result['data'])
        all_errors.extend(result['errors'])
        total += result['total']
    return {'data': all_data, 'errors': all_errors, 'total': total,
            'countries': all_countries}
