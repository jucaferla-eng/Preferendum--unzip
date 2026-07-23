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

    # ── ESTADOS UNIDOS — primeros 3 dígitos del ZIP (prefijos SCF) ──
    # Referencia: Tribeca/SoHo NYC (100) = 100
    'US': [
        # Nueva York — Manhattan
        ('100', 100,  1_629_000), # Tribeca / SoHo / Financial District
        ('101',  92,    400_000), # Midtown / Upper East Side
        ('102',  88,    300_000), # Upper West Side / Harlem sur
        ('103',  60,    500_000), # Staten Island
        ('104',  45,  1_427_000), # Bronx
        # Nueva York — outer boroughs
        ('110',  65,  2_271_000), # Queens centro
        ('111',  72,    400_000), # Forest Hills / Jamaica Estates
        ('112',  70,  2_576_000), # Brooklyn Prospect Park / Park Slope
        ('113',  58,    500_000), # Brooklyn outer
        ('114',  58,    400_000), # Queens outer
        ('115',  75,    800_000), # Long Island Nassau
        ('116',  65,    400_000), # Long Island central
        ('117',  70,    600_000), # Long Island south shore
        ('118',  68,    400_000), # Long Island Hempstead
        ('119',  95,    200_000), # Hamptons / East End
        # Nueva Jersey
        ('070',  55,    280_000), # Newark
        ('071',  58,    200_000), # NJ Hudson
        ('072',  65,    300_000), # NJ central
        ('073',  70,    400_000), # NJ Middlesex
        ('074',  68,    300_000), # NJ Monmouth
        ('075',  72,    200_000), # NJ shore
        ('077',  75,    300_000), # NJ Shore premium
        ('079',  80,    200_000), # NJ Bergen/Morris (suburbs NYC)
        ('085',  78,    400_000), # NJ Princeton / Mercer
        ('086',  82,    200_000), # NJ Somerset premium
        # Washington DC área
        ('200',  88,    689_000), # Washington DC
        ('201',  85,    200_000), # DC Metro norte
        ('202',  85,    200_000), # DC central
        ('203',  80,    200_000), # DC sureste
        ('204',  75,    200_000), # DC outer
        ('205',  78,    200_000), # DC Metro
        ('220',  88,    238_000), # Arlington VA
        ('221',  85,    160_000), # Alexandria VA
        ('222',  82,    300_000), # Fairfax VA
        ('223',  80,    400_000), # Fairfax outer VA
        ('240',  45,    200_000), # Virginia occidental
        # Boston área
        ('021',  88,    675_000), # Boston
        ('022',  92,    118_000), # Cambridge / Brookline
        ('023',  85,     88_000), # Newton MA
        ('024',  80,    300_000), # Boston suburbios premium
        ('025',  70,    300_000), # Boston outer
        ('026',  65,    200_000), # Framingham / Natick
        ('027',  75,    200_000), # Quincy / Braintree
        # Los Angeles
        ('900',  78,  3_900_000), # LA Central
        ('901',  95,     35_000), # Beverly Hills
        ('902',  90,    100_000), # Santa Monica / Culver City
        ('903',  82,    200_000), # Inglewood / Hawthorne
        ('904',  78,    400_000), # Torrance / South Bay
        ('905',  72,    400_000), # Long Beach
        ('906',  30,    500_000), # Compton / Watts
        ('907',  55,    400_000), # Carson / Gardena
        ('908',  65,    300_000), # San Pedro
        ('910',  85,    300_000), # Pasadena
        ('911',  80,    300_000), # Alhambra / Arcadia
        ('912',  70,    400_000), # El Monte
        ('913',  88,    200_000), # Burbank / Glendale premium
        ('914',  90,    200_000), # Glendale
        ('915',  75,    400_000), # Covina / West Covina
        ('916',  70,    300_000), # Pomona
        ('917',  68,    300_000), # Ontario / Rancho Cucamonga
        ('918',  85,    200_000), # Malibu / Ventura premium
        ('919',  92,    100_000), # San Diego La Jolla premium
        ('920',  80,    500_000), # San Diego Mission Valley
        ('921',  75,    400_000), # San Diego outer
        ('922',  72,    300_000), # San Diego east
        # San Francisco Bay Area
        ('940',  88,    450_000), # SF Mission / Castro
        ('941', 100,    422_000), # SF Pac Heights / Marina / Nob Hill
        ('942',  90,    200_000), # SF SoMa / Potrero
        ('943',  85,    200_000), # Palo Alto / Menlo Park
        ('944',  95,    100_000), # Silicon Valley (Mountain View/Sunnyvale)
        ('945',  65,    440_000), # Oakland
        ('946',  72,    300_000), # Fremont / Hayward
        ('947',  80,    200_000), # Berkeley
        ('948',  82,    300_000), # San Mateo / Redwood City
        ('949',  95,     80_000), # Marin County (Sausalito/Mill Valley)
        ('950',  78,    200_000), # San Jose norte
        ('951',  75,    400_000), # San Jose sur
        ('952',  70,    300_000), # Santa Clara
        # Chicago
        ('606',  90,  2_700_000), # Chicago Lincoln Park / Gold Coast
        ('607',  78,    500_000), # Chicago norte (Lakeview/Wicker Park)
        ('608',  65,    400_000), # Chicago west
        ('609',  55,    400_000), # Chicago south
        ('600',  82,    200_000), # Chicago Loop
        ('601',  72,    300_000), # Chicago outer norte
        ('602',  60,    300_000), # Chicago outer sur
        ('603',  88,    400_000), # Evanston / North Shore
        ('604',  82,    200_000), # Oak Park / River Forest
        ('605',  78,    300_000), # Naperville / Downers Grove
        # Houston
        ('770',  65,  2_300_000), # Houston
        ('771',  78,    200_000), # Houston Heights / Montrose
        ('772',  60,    400_000), # Houston south
        ('773',  55,    300_000), # Houston outer
        ('774',  70,    200_000), # Pasadena TX / Pearland
        ('775',  82,    200_000), # The Woodlands / Sugar Land premium
        # Dallas / Fort Worth
        ('750',  72,  1_300_000), # Dallas
        ('751',  85,    200_000), # Dallas Highland Park / Preston Hollow
        ('752',  65,    400_000), # Dallas outer
        ('753',  78,    200_000), # Plano / Allen
        ('754',  60,    300_000), # Garland / Mesquite
        ('760',  65,    900_000), # Fort Worth
        ('761',  70,    200_000), # Fort Worth north
        ('762',  78,    200_000), # Arlington TX
        # Atlanta
        ('303',  85,    500_000), # Atlanta Buckhead / Midtown
        ('300',  75,    500_000), # Atlanta
        ('301',  65,    300_000), # Atlanta south
        ('302',  60,    300_000), # Atlanta east
        ('304',  82,    200_000), # Marietta / Cobb County premium
        ('305',  78,    300_000), # Alpharetta / Johns Creek
        # Miami / South Florida
        ('331',  88,    200_000), # Miami Beach / Brickell
        ('330',  82,    500_000), # Miami
        ('333',  75,    200_000), # Ft Lauderdale
        ('334',  70,    300_000), # Palm Beach
        ('337',  80,    100_000), # Palm Beach premium
        # Seattle
        ('980',  88,    750_000), # Seattle
        ('981',  85,    200_000), # Seattle Bellevue
        ('982',  80,    200_000), # Bellevue / Redmond (Microsoft/Amazon)
        ('983',  72,    300_000), # Tacoma
        ('984',  78,    200_000), # Olympia
        # Denver / Colorado
        ('802',  82,    700_000), # Denver
        ('803',  90,    100_000), # Boulder
        ('804',  78,    200_000), # Denver Cherry Creek
        ('805',  72,    300_000), # Denver outer
        ('806',  88,     50_000), # Aspen / ski resorts
        ('809',  75,    200_000), # Colorado Springs
        # Phoenix
        ('850',  72,  1_600_000), # Phoenix
        ('851',  78,    200_000), # Scottsdale
        ('852',  65,    300_000), # Phoenix west
        ('853',  68,    300_000), # Tempe / Chandler
        ('854',  82,    100_000), # Scottsdale premium (Paradise Valley)
        # Minneapolis / Twin Cities
        ('554',  80,    300_000), # Minneapolis
        ('551',  82,    200_000), # St Paul
        ('553',  78,    200_000), # Bloomington / Eden Prairie
        # Portland Oregon
        ('972',  80,    650_000), # Portland
        ('970',  82,    100_000), # Portland west hills
        ('971',  75,    200_000), # Portland outer
        ('974',  72,    200_000), # Salem OR
        # Las Vegas
        ('891',  65,  2_200_000), # Las Vegas Strip
        ('890',  60,    400_000), # Las Vegas outer
        ('889',  72,    100_000), # Henderson NV
        # Otras ciudades importantes
        ('191',  82,    600_000), # Philadelphia
        ('192',  78,    300_000), # Philadelphia suburbs Main Line
        ('193',  80,    200_000), # Philadelphia premium suburbs
        ('432',  72,    800_000), # Columbus OH
        ('441',  70,    380_000), # Cleveland
        ('442',  78,    100_000), # Cleveland Heights / Shaker
        ('481',  80,    700_000), # Detroit
        ('482',  75,    200_000), # Detroit Royal Oak / Birmingham
        ('532',  78,    600_000), # Milwaukee
        ('372',  75,    700_000), # Nashville
        ('282',  80,    500_000), # Charlotte
        ('271',  75,    300_000), # Raleigh
        ('275',  80,    200_000), # Chapel Hill / Research Triangle
        ('023',  82,    200_000), # Providence RI
        ('063',  88,    100_000), # Greenwich CT (premium)
        ('064',  82,    200_000), # Stamford CT
        ('065',  78,    300_000), # Hartford CT
        ('011',  75,    650_000), # Springfield MA
        ('012',  80,    175_000), # Northampton / Pioneer Valley
        ('489',  72,    300_000), # Ann Arbor MI
        ('430',  78,    800_000), # Columbus OH premium
        ('452',  75,    300_000), # Cincinnati
        ('462',  72,    900_000), # Indianapolis
        ('531',  80,    600_000), # Madison WI
        ('671',  72,    500_000), # Kansas City MO
        ('631',  78,    300_000), # St Louis
        ('701',  75,    400_000), # New Orleans
        ('730',  72,    600_000), # Oklahoma City
        ('741',  75,    200_000), # Tulsa
        ('787',  82,    950_000), # Austin TX
        ('782',  78,    200_000), # San Antonio TX
        ('799',  65,    700_000), # El Paso TX
        ('871',  72,    900_000), # Albuquerque NM
        ('841',  80,    200_000), # Salt Lake City
        ('967',  75,    100_000), # Honolulu HI
        ('998',  65,    300_000), # Anchorage AK
        ('320',  70,    500_000), # Jacksonville FL
        ('321',  75,    300_000), # Orlando FL
        ('322',  72,    200_000), # Gainesville FL
        ('326',  65,    400_000), # Tallahassee FL
        ('341',  80,    400_000), # Naples / Sarasota FL premium
        ('342',  78,    300_000), # Sarasota FL
        ('346',  75,    200_000), # Tampa FL
        ('335',  80,    300_000), # Tampa premium
        ('298',  72,    400_000), # Columbia SC
        ('292',  75,    400_000), # Charleston SC
        ('288',  70,    300_000), # Greensboro NC
        ('244',  68,    300_000), # Richmond VA
        ('245',  72,    100_000), # Charlottesville VA
        ('212',  78,    600_000), # Baltimore
        ('210',  82,    100_000), # Baltimore premium (Roland Park)
        ('015',  72,    200_000), # Worcester MA
        ('030',  75,    400_000), # Manchester NH
        ('040',  72,    200_000), # Portland ME
        ('058',  80,    100_000), # Burlington VT
        ('014',  70,    200_000), # Lowell MA
        ('028',  75,    300_000), # New Haven CT
        ('069',  78,    100_000), # Bridgeport CT
    ],

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
        ('7001',  42,  90_000), # Barquisimeto Norte
        ('3201',  38, 100_000), # Puerto Ordaz premium
        ('3001',  38, 130_000), # Barquisimeto Sur
        ('4601',  30,  80_000), # Maturín interior
        ('1011',  95,  30_000), # Caracas Los Palos Grandes (premium)
        ('1012',  90,  40_000), # Caracas La Florida / San Román
        ('1013',  75,  80_000), # Caracas Chacao Norte
        ('1025',  35, 200_000), # Caracas Catia / Caricuao
        ('2101',  48, 180_000), # Maracay El Bosque
        ('2105',  38, 120_000), # Maracay Las Delicias
        ('4005',  38, 200_000), # Maracaibo Este
        ('4002',  30, 300_000), # Maracaibo popular
        ('1016',  42, 300_000), # Caracas populares (oeste)
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
        ('11700',  68,  40_000), # Montevideo Brazo Oriental
        ('11900',  65,  50_000), # Montevideo Prado / Casabó
        ('13000',  50, 100_000), # Ciudad de la Costa
        ('14000',  48,  80_000), # Progreso / Canelones Interior
        ('17000',  36,  80_000), # Florida
        ('65000',  34,  30_000), # Melo / Cerro Largo
        ('70000',  32,  40_000), # Fray Bentos / Rio Negro
        ('50100',  38,  50_000), # Salto Centro
        ('75000',  28,  30_000), # Minas / Lavalleja
        ('20100',  90,  15_000), # Punta del Este Premium (Cantegril)
        ('20200',  80,  20_000), # Maldonado Ciudad
        ('97000',  40,  25_000), # Colonia del Sacramento Centro
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
        ('0601',  44, 200_000), # Cochabamba Norte
        ('0602',  38, 150_000), # Quillacollo / Sacaba
        ('0603',  32, 150_000), # Cochabamba rural
        ('0501',  40,  60_000), # Tarija suburbios
        ('0401',  30,  80_000), # Oruro Norte
        ('0301',  35,  50_000), # Trinidad (Beni)
        ('0901',  70,  80_000), # Calacoto premium (La Paz)
        ('0903',  55, 120_000), # La Paz El Alto Sur
        ('0921',  22, 250_000), # El Alto Ciudad
        ('0200',  62,  60_000), # Cobija (Pando)
        ('0911',  58,  60_000), # La Paz Zona Norte
        ('1001',  40,  50_000), # Sucre Norte
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
        ('2950',  40,  50_000), # Areguá
        ('2200',  38,  50_000), # Ypacaraí
        ('2910',  42,  50_000), # Itauguá
        ('2160',  36,  50_000), # Limpio
        ('3310',  38,  60_000), # Coronel Oviedo
        ('4210',  35,  50_000), # Caazapá
        ('6000',  36,  60_000), # Villarrica
        ('7000',  32,  50_000), # Concepción
        ('8000',  30,  50_000), # Pilar
        ('6810',  35,  60_000), # Caaguazú
        ('1906',  38,  30_000), # Asunción Sajonia
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

    # ══════════════════════════════════════════════════════════════
    # EMIRATOS ÁRABES UNIDOS — AE
    # ══════════════════════════════════════════════════════════════
    'AE': [
        ('10', 100, 100_000), # Downtown Dubai / Palm Jumeirah / DIFC
        ('20',  92, 120_000), # Dubai Marina / JBR / JLT
        ('30',  82,  90_000), # Business Bay / Jumeirah
        ('40',  88, 100_000), # Abu Dhabi Corniche / Al Reem Island
        ('50',  80,  80_000), # Abu Dhabi Yas Island / Saadiyat
        ('60',  55, 200_000), # Sharjah premium
        ('61',  42, 300_000), # Sharjah general
        ('70',  35, 250_000), # Ajman
        ('71',  40, 150_000), # Ras Al Khaimah
        ('72',  30, 100_000), # Fujairah
        ('73',  28,  80_000), # Umm Al Quwain
    ],

    # ══════════════════════════════════════════════════════════════
    # AUSTRIA — AT
    # ══════════════════════════════════════════════════════════════
    'AT': [
        ('10', 100, 400_000), # Viena distritos interiores (1.-9. Bezirk)
        ('11',  75, 300_000), # Viena distritos exteriores
        ('20',  50, 150_000), # Baja Austria cerca de Viena
        ('21',  45, 100_000), # Baja Austria general
        ('30',  45, 200_000), # Alta Austria norte
        ('40',  55, 200_000), # Linz
        ('50',  82, 150_000), # Salzburgo ciudad
        ('51',  65, 100_000), # Salzburgo Land
        ('52',  55,  80_000), # Salzburgo rural
        ('60',  72, 130_000), # Innsbruck / Tirol
        ('61',  88,  50_000), # Kitzbühel y resorts de Tirol
        ('62',  58,  80_000), # Tirol medio
        ('63',  65,  90_000), # Vorarlberg (Bregenz/Dornbirn)
        ('64',  58,  60_000), # Vorarlberg medio
        ('70',  38,  80_000), # Burgenland
        ('80',  60, 180_000), # Graz / Estiria
        ('81',  42, 100_000), # Estiria media
        ('82',  35,  80_000), # Estiria rural
        ('90',  52, 100_000), # Klagenfurt / Carintia
        ('91',  40,  80_000), # Carintia general
    ],

    # ══════════════════════════════════════════════════════════════
    # CHINA — CN
    # ══════════════════════════════════════════════════════════════
    'CN': [
        ('100', 100, 5_000_000), # Beijing centro (Dongcheng/Xicheng)
        ('101',  72, 3_000_000), # Beijing suburbios
        ('102',  55, 2_000_000), # Beijing outer
        ('200', 100, 5_000_000), # Shanghai Huangpu/Jing'an
        ('201',  75, 4_000_000), # Shanghai Pudong/Changning
        ('202',  55, 2_000_000), # Shanghai lejano
        ('310',  68, 1_500_000), # Hangzhou
        ('315',  65, 1_000_000), # Ningbo
        ('350',  55,   800_000), # Fuzhou
        ('361',  70,   800_000), # Xiamen
        ('370',  60,   900_000), # Qingdao
        ('410',  45, 1_200_000), # Zhengzhou
        ('420',  52, 1_500_000), # Wuhan
        ('430',  50, 1_000_000), # Changsha
        ('510',  78, 2_500_000), # Guangzhou
        ('511',  62, 1_500_000), # Foshan
        ('518',  95, 2_000_000), # Shenzhen Futian/Nanshan
        ('519',  75, 1_500_000), # Shenzhen outer
        ('520',  55,   800_000), # Dongguan
        ('530',  45,   800_000), # Nanning
        ('570',  60,   500_000), # Hainan/Sanya
        ('610',  58, 1_800_000), # Chengdu
        ('550',  35,   600_000), # Guiyang
        ('650',  40,   700_000), # Kunming
        ('710',  48, 1_200_000), # Xi'an
        ('730',  35,   500_000), # Lanzhou
        ('830',  38,   400_000), # Urumqi
        ('750',  32,   300_000), # Yinchuan
    ],

    # ══════════════════════════════════════════════════════════════
    # CHEQUIA — CZ
    # ══════════════════════════════════════════════════════════════
    'CZ': [
        ('10', 100, 600_000), # Praga 1-4 (centro)
        ('11',  80, 400_000), # Praga 5-8
        ('12',  68, 300_000), # Praga 9-12
        ('14',  58, 200_000), # Praga outer
        ('15',  52, 150_000), # Praga farther
        ('16',  48, 150_000), # Praga suburbios
        ('25',  50, 200_000), # Bohemia Central (cerca de Praga)
        ('27',  35, 150_000), # Bohemia Norte oeste
        ('36',  55, 180_000), # Bohemia Oeste / Plzeň
        ('46',  42, 100_000), # Liberec
        ('50',  45, 150_000), # Hradec Králové
        ('58',  40, 100_000), # Bohemia Este / Jihlava
        ('60',  72, 400_000), # Brno centro
        ('61',  58, 200_000), # Brno suburbios
        ('62',  50, 150_000), # Brno outer
        ('70',  48, 300_000), # Ostrava
        ('71',  38, 150_000), # Ostrava suburbios
        ('75',  45, 150_000), # Zlín
        ('79',  45, 150_000), # Olomouc
    ],

    # ══════════════════════════════════════════════════════════════
    # GRECIA — GR
    # ══════════════════════════════════════════════════════════════
    'GR': [
        ('10', 100, 500_000), # Atenas centro (Kolonaki/Syntagma)
        ('11',  85, 300_000), # Atenas norte premium (Kifisia)
        ('12',  45, 400_000), # Atenas oeste (Peristeri)
        ('14',  80, 250_000), # Atenas Marousi/Kifisia
        ('15',  75, 200_000), # Atenas norte suburbio
        ('16',  88, 150_000), # Atenas sur premium (Glyfada/Vouliagmeni)
        ('17',  55, 300_000), # Atenas sur (Kallithea)
        ('18',  62, 400_000), # Pireo premium
        ('19',  78, 150_000), # Attica este (Vari/Voula)
        ('54',  70, 300_000), # Tesalónica centro
        ('55',  62, 200_000), # Tesalónica este
        ('56',  42, 200_000), # Tesalónica oeste
        ('57',  48, 150_000), # Tesalónica suburbios
        ('26',  45, 200_000), # Patras
        ('41',  40, 150_000), # Larissa
        ('71',  50, 180_000), # Heraklion Creta
        ('85',  55, 100_000), # Rodas
        ('49',  52,  80_000), # Corfú
        ('82',  40,  80_000), # Lesbos
    ],

    # ══════════════════════════════════════════════════════════════
    # HUNGRÍA — HU
    # ══════════════════════════════════════════════════════════════
    'HU': [
        ('10', 100, 300_000), # Budapest 1.-4. distritos
        ('11',  88, 400_000), # Budapest 5.-9.
        ('12',  72, 300_000), # Budapest 10.-14.
        ('13',  60, 250_000), # Budapest 15.-19.
        ('14',  52, 200_000), # Budapest 20.-23.
        ('20',  55, 400_000), # Suburbios Budapest (Pest county)
        ('21',  45, 200_000), # Suburbios más lejanos
        ('22',  40, 150_000), # Pest county sur
        ('23',  38, 100_000), # Pest county este
        ('27',  30, 100_000), # Nógrád
        ('36',  42, 100_000), # Eger
        ('40',  55, 200_000), # Debrecen
        ('42',  40, 150_000), # Debrecen outer
        ('43',  35, 120_000), # Nyíregyháza
        ('44',  32, 180_000), # Miskolc
        ('50',  35, 150_000), # Szolnok
        ('60',  45, 150_000), # Kecskemét
        ('70',  48, 180_000), # Pécs
        ('80',  52, 130_000), # Győr
        ('84',  40, 100_000), # Veszprém
        ('90',  62,  80_000), # Sopron (cerca de Austria)
        ('94',  35, 100_000), # Zalaegerszeg
    ],

    # ══════════════════════════════════════════════════════════════
    # ISRAEL — IL
    # ══════════════════════════════════════════════════════════════
    'IL': [
        ('60', 100, 450_000), # Tel Aviv Rothschild/Neve Tzedek
        ('61',  90, 400_000), # Tel Aviv centro
        ('62',  88, 150_000), # Tel Aviv norte (Ramat Aviv)
        ('63',  70, 200_000), # Tel Aviv sur
        ('66',  95,  50_000), # Herzliya Pituah (premium)
        ('52',  80, 150_000), # Givatayim / Ramat Gan premium
        ('67',  72, 200_000), # Ramat Gan general
        ('68',  45, 200_000), # Bnei Brak
        ('46',  65, 200_000), # Hod HaSharon / Kfar Saba
        ('40',  60, 200_000), # Netanya
        ('32',  70, 100_000), # Haifa Carmel
        ('33',  55, 200_000), # Haifa centro
        ('35',  45, 150_000), # Hadera
        ('74',  45, 200_000), # Ashdod
        ('77',  38, 250_000), # Beer Sheva
        ('90',  72, 300_000), # Jerusalén centro
        ('91',  65, 200_000), # Jerusalén norte
        ('92',  45, 150_000), # Jerusalén sur
    ],

    # ══════════════════════════════════════════════════════════════
    # IRAK — IQ
    # ══════════════════════════════════════════════════════════════
    'IQ': [
        ('10', 100, 300_000), # Bagdad Karrada/Mansour premium
        ('11',  80, 400_000), # Bagdad Zayouna/Jadriya
        ('12',  70, 500_000), # Bagdad Karada
        ('13',  50, 600_000), # Bagdad oeste
        ('14',  45, 500_000), # Bagdad este
        ('15',  35, 400_000), # Bagdad outer
        ('16',  28, 300_000), # Bagdad suburbios
        ('36',  60, 200_000), # Basra ciudad
        ('37',  55, 150_000), # Basra zonas petroleras
        ('38',  30, 200_000), # Basra rural
        ('44',  75, 200_000), # Erbil (Kurdistan)
        ('45',  62, 150_000), # Sulaymaniyah
        ('46',  50, 100_000), # Dohuk
        ('56',  35, 300_000), # Mosul
        ('60',  42, 200_000), # Kirkuk
        ('61',  38, 150_000), # Najaf
        ('54',  38, 150_000), # Karbala
    ],

    # ══════════════════════════════════════════════════════════════
    # IRÁN — IR
    # ══════════════════════════════════════════════════════════════
    'IR': [
        ('11', 100, 500_000), # Teherán norte (Shemiran/Zafaraniyeh)
        ('13',  90, 300_000), # Teherán Elahiyeh/Jordan
        ('12',  85, 400_000), # Teherán centro premium
        ('14',  80, 300_000), # Teherán Saadat Abad
        ('15',  65, 500_000), # Teherán oeste
        ('16',  55, 600_000), # Teherán este
        ('17',  45, 600_000), # Teherán sur
        ('18',  40, 500_000), # Teherán suroeste
        ('19',  32, 400_000), # Teherán sur lejano
        ('38',  55, 500_000), # Karaj
        ('31',  65, 600_000), # Isfahan
        ('32',  48, 300_000), # Isfahan outer
        ('51',  60, 700_000), # Mashhad
        ('52',  42, 300_000), # Mashhad outer
        ('71',  55, 500_000), # Shiraz
        ('72',  40, 300_000), # Shiraz outer
        ('41',  52, 600_000), # Tabriz
        ('76',  78, 100_000), # Kish Island (zona libre)
        ('79',  45, 200_000), # Bandar Abbas
    ],

    # ══════════════════════════════════════════════════════════════
    # JAPÓN — JP
    # ══════════════════════════════════════════════════════════════
    'JP': [
        ('100', 100, 100_000), # Tokyo Chiyoda (zona imperial/financiera)
        ('106', 98,   80_000), # Tokyo Minato Azabu/Roppongi
        ('107', 95,   80_000), # Tokyo Akasaka/Roppongi Hills
        ('105', 92,  100_000), # Tokyo Minato
        ('108', 88,  100_000), # Tokyo Shiba/Takanawa
        ('150', 88,  200_000), # Tokyo Shibuya
        ('153', 85,  150_000), # Tokyo Meguro
        ('145', 80,  200_000), # Tokyo Shinagawa
        ('160', 82,  200_000), # Tokyo Shinjuku
        ('155', 78,  250_000), # Tokyo Setagaya premium
        ('141', 78,  150_000), # Tokyo Shinagawa estación
        ('135', 75,  200_000), # Tokyo Koto (Toyosu/Ariake)
        ('167', 75,  150_000), # Tokyo Suginami premium
        ('171', 70,  250_000), # Tokyo Toshima/Ikebukuro
        ('180', 72,  300_000), # Tokyo Nerima/Suginami
        ('130', 65,  300_000), # Tokyo Sumida
        ('111', 62,  200_000), # Tokyo Taito/Asakusa
        ('110', 62,  200_000), # Tokyo Taito
        ('125', 50,  300_000), # Tokyo Katsushika
        ('120', 48,  400_000), # Tokyo Adachi
        ('190', 58,  400_000), # Tokyo oeste (Tachikawa)
        ('194', 45,  300_000), # Tokyo lejano oeste
        ('220', 78,  300_000), # Yokohama Nishi
        ('231', 72,  200_000), # Yokohama centro
        ('221', 65,  300_000), # Yokohama Kanagawa
        ('530', 82,  200_000), # Osaka Kita (Umeda/Nakanoshima)
        ('540', 70,  300_000), # Osaka centro
        ('542', 68,  200_000), # Osaka Namba
        ('550', 65,  200_000), # Osaka Fukushima
        ('600', 72,  200_000), # Kyoto centro
        ('603', 65,  150_000), # Kyoto norte
        ('460', 72,  200_000), # Nagoya Naka
        ('450', 70,  300_000), # Nagoya estación
        ('464', 68,  200_000), # Nagoya Chikusa
        ('810', 62,  300_000), # Fukuoka Chuo
        ('812', 60,  300_000), # Fukuoka Hakata
    ],

    # ══════════════════════════════════════════════════════════════
    # COREA DEL SUR — KR
    # ══════════════════════════════════════════════════════════════
    'KR': [
        ('06', 100, 600_000), # Seúl Gangnam/Seocho (premium)
        ('05',  88, 500_000), # Seúl Songpa/Gwangjin
        ('13',  88, 400_000), # Seongnam/Bundang (Gyeonggi premium)
        ('07',  85, 400_000), # Seúl Mapo/Yongsan
        ('03',  80, 300_000), # Seúl Jongno/Jung
        ('04',  72, 300_000), # Seúl Jung/Seongdong
        ('08',  65, 500_000), # Seúl Yangcheon/Gangseo
        ('01',  55, 500_000), # Seúl Dobong/Nowon
        ('02',  58, 400_000), # Seúl Seongbuk/Jungnang
        ('16',  62, 500_000), # Suwon
        ('10',  55, 400_000), # Gyeonggi norte
        ('14',  52, 300_000), # Gyeonggi este
        ('17',  55, 400_000), # Gyeonggi sur
        ('38',  65, 300_000), # Sejong City (nueva capital)
        ('21',  58, 300_000), # Incheon centro
        ('22',  45, 300_000), # Incheon outer
        ('35',  60, 400_000), # Daejeon centro
        ('41',  58, 400_000), # Daegu centro
        ('46',  82, 200_000), # Busan Haeundae (premium)
        ('47',  65, 400_000), # Busan centro
        ('48',  48, 300_000), # Busan Saha/outer
        ('63',  62, 200_000), # Jeju Island
    ],

    # ══════════════════════════════════════════════════════════════
    # KAZAJISTÁN — KZ
    # ══════════════════════════════════════════════════════════════
    'KZ': [
        ('010', 100, 400_000), # Astana/Nur-Sultan centro
        ('011',  72, 300_000), # Astana outer
        ('050',  95, 500_000), # Almaty centro premium (Medeu/Bostandyk)
        ('051',  80, 400_000), # Almaty inner
        ('052',  60, 300_000), # Almaty outer
        ('053',  45, 200_000), # Almaty suburbios
        ('040',  58, 200_000), # Atyrau (ciudad petrolera)
        ('060',  45, 150_000), # Aktau
        ('071',  48, 300_000), # Shymkent
        ('080',  42, 200_000), # Aktobe
        ('100',  40, 400_000), # Karaganda
        ('110',  35, 200_000), # Pavlodar
        ('120',  32, 150_000), # Semey
        ('130',  38, 150_000), # Ust-Kamenogorsk
        ('140',  30, 150_000), # Petropavl
        ('090',  32, 150_000), # Oral
        ('070',  28, 200_000), # Kyzylorda
    ],

    # ══════════════════════════════════════════════════════════════
    # MALASIA — MY
    # ══════════════════════════════════════════════════════════════
    'MY': [
        ('50', 100, 300_000), # KL Bukit Bintang / KLCC
        ('51',  88, 200_000), # KL centro
        ('47',  80, 400_000), # Subang Jaya / Damansara
        ('52',  75, 300_000), # KL norte
        ('41',  72, 600_000), # Petaling Jaya
        ('53',  65, 300_000), # KL outer
        ('40',  70, 400_000), # Shah Alam
        ('54',  60, 250_000), # KL oeste
        ('55',  58, 250_000), # KL sur
        ('56',  55, 300_000), # KL Cheras
        ('57',  50, 300_000), # KL Kepong
        ('68',  60, 300_000), # Ampang / Hulu Langat
        ('10', 78, 300_000), # Penang George Town
        ('11',  65, 200_000), # Penang sur
        ('12',  60, 150_000), # Penang inner
        ('13',  50, 100_000), # Penang outer
        ('80',  70, 400_000), # Johor Bahru centro
        ('81',  58, 300_000), # Johor Bahru este
        ('82',  48, 200_000), # Johor inner
        ('88',  55, 200_000), # Kota Kinabalu (Sabah)
        ('93',  50, 200_000), # Kuching (Sarawak)
        ('25',  42, 200_000), # Kuantan
        ('30',  48, 300_000), # Ipoh
        ('15',  35, 200_000), # Kota Bharu (Kelantan)
    ],

    # ══════════════════════════════════════════════════════════════
    # POLONIA — PL
    # ══════════════════════════════════════════════════════════════
    'PL': [
        ('00', 100, 400_000), # Varsovia centro (Śródmieście)
        ('02',  88, 300_000), # Varsovia Mokotów premium
        ('01',  82, 250_000), # Varsovia norte
        ('04',  72, 300_000), # Varsovia sur
        ('05',  68, 400_000), # Varsovia suburbios oeste
        ('06',  60, 300_000), # Varsovia outer
        ('07',  52, 200_000), # Varsovia suburbial
        ('30',  88, 300_000), # Cracovia centro (Stare Miasto)
        ('31',  82, 250_000), # Cracovia premium
        ('32',  55, 200_000), # Cracovia norte
        ('33',  48, 150_000), # Cracovia outer
        ('50',  78, 300_000), # Wroclaw centro
        ('51',  65, 200_000), # Wroclaw norte
        ('52',  55, 200_000), # Wroclaw outer
        ('60',  72, 300_000), # Poznan centro
        ('61',  68, 250_000), # Poznan inner
        ('62',  55, 200_000), # Poznan outer
        ('80',  75, 250_000), # Gdansk centro
        ('81',  78, 150_000), # Gdynia (premium)
        ('82',  58, 200_000), # Gdansk outer
        ('83',  48, 150_000), # Tricity outer
        ('40',  55, 300_000), # Katowice
        ('70',  60, 250_000), # Szczecin centro
        ('20',  50, 200_000), # Lublin
        ('10',  45, 150_000), # Olsztyn
        ('15',  48, 200_000), # Białystok
    ],

    # ══════════════════════════════════════════════════════════════
    # CATAR — QA
    # ══════════════════════════════════════════════════════════════
    'QA': [
        ('20', 100, 100_000), # Doha West Bay / Pearl Qatar
        ('21',  95,  50_000), # Doha Diplomatic Zone
        ('22',  90,  80_000), # Lusail City
        ('23',  80, 150_000), # Doha centro
        ('24',  70, 200_000), # Doha residencial
        ('25',  58, 150_000), # Doha sur
        ('26',  48, 100_000), # Doha outer
        ('30',  55, 150_000), # Al Rayyan
        ('27',  45, 100_000), # Al Wakrah
        ('28',  38,  80_000), # Al Khor
        ('29',  42,  60_000), # Mesaieed
        ('31',  40,  80_000), # Umm Slal
        ('32',  30,  50_000), # Al Shamal
    ],

    # ══════════════════════════════════════════════════════════════
    # RUMANÍA — RO
    # ══════════════════════════════════════════════════════════════
    'RO': [
        ('01', 100, 300_000), # Bucarest sector 1 (Floreasca/Dorobanți)
        ('02',  85, 350_000), # Bucarest sector 2 (Herăstrău)
        ('03',  65, 350_000), # Bucarest sector 3
        ('04',  55, 350_000), # Bucarest sector 4 sur
        ('05',  48, 350_000), # Bucarest sector 5 sur
        ('06',  58, 350_000), # Bucarest sector 6
        ('07',  60, 300_000), # Ilfov county (suburbios)
        ('30',  72, 300_000), # Timișoara centro
        ('31',  55, 200_000), # Timișoara outer
        ('40',  80, 300_000), # Cluj-Napoca centro
        ('41',  62, 200_000), # Cluj-Napoca outer
        ('50',  68, 250_000), # Brașov centro
        ('51',  50, 150_000), # Brașov outer
        ('60',  58, 200_000), # Sibiu
        ('70',  55, 300_000), # Iași centro
        ('71',  42, 200_000), # Iași outer
        ('23',  55, 250_000), # Constanța
        ('90',  62, 100_000), # Costa del Mar Negro
        ('20',  48, 200_000), # Ploiești
        ('10',  45, 180_000), # Pitești
        ('80',  38, 250_000), # Galați/Brăila
    ],

    # ══════════════════════════════════════════════════════════════
    # RUSIA — RU
    # ══════════════════════════════════════════════════════════════
    'RU': [
        ('121', 100, 300_000), # Moscú Fili/Khamovniki (premium oeste)
        ('123',  95, 300_000), # Moscú Presnensky/Patriarshiye Prudy
        ('117',  90, 400_000), # Moscú suroeste premium (Lomonosovskiy)
        ('119',  88, 300_000), # Moscú Lomonosovskiy/MGU
        ('101',  85, 200_000), # Moscú centro (Kitai-Gorod)
        ('103',  82, 200_000), # Moscú Tverskoy
        ('115',  72, 300_000), # Moscú Donskoy/Zamoskvorechye
        ('109',  78, 300_000), # Moscú Taganka
        ('105',  80, 300_000), # Moscú Sokolniki
        ('107',  75, 300_000), # Moscú Baumanskaya
        ('125',  70, 400_000), # Moscú norte
        ('127',  65, 400_000), # Moscú Dmitrovsky
        ('129',  68, 300_000), # Moscú Ostankino
        ('113',  60, 300_000), # Moscú Nagatino
        ('111',  65, 400_000), # Moscú Perovo
        ('354',  65, 300_000), # Sochi
        ('199',  80, 200_000), # San Petersburgo Petrogradsky
        ('197',  72, 200_000), # San Petersburgo Vasilievsky Island
        ('190',  78, 300_000), # San Petersburgo centro
        ('191',  72, 250_000), # San Petersburgo centro este
        ('194',  65, 300_000), # San Petersburgo norte
        ('192',  60, 300_000), # San Petersburgo sur
        ('196',  50, 250_000), # San Petersburgo sur outer
        ('620',  52, 500_000), # Ekaterinburg
        ('630',  48, 600_000), # Novosibirsk
        ('350',  48, 600_000), # Krasnodar
        ('344',  45, 500_000), # Rostov-on-Don
        ('420',  52, 400_000), # Kazán
        ('443',  48, 400_000), # Samara
        ('450',  45, 400_000), # Ufá
        ('454',  42, 400_000), # Cheliábinsk
        ('660',  42, 400_000), # Krasnoyarsk
        ('690',  45, 200_000), # Vladivostok
        ('614',  42, 300_000), # Perm
        ('400',  40, 500_000), # Volgogrado
        ('664',  38, 200_000), # Irkutsk
        ('670',  30, 200_000), # Ulán Udé
    ],

    # ══════════════════════════════════════════════════════════════
    # ARABIA SAUDITA — SA
    # ══════════════════════════════════════════════════════════════
    'SA': [
        ('11', 100, 800_000), # Riad centro / Al Olaya / King Fahd Road
        ('32',  90, 100_000), # Dhahran Aramco
        ('12',  92, 600_000), # Yeda (Jeddah) centro / Al Hamra
        ('13',  88, 300_000), # Al Khobar premium
        ('21',  85, 400_000), # Yeda Corniche
        ('22',  68, 300_000), # Yeda este
        ('23',  55, 300_000), # Yeda sur
        ('31',  78, 400_000), # Dammam
        ('33',  72, 200_000), # Jubail industrial premium
        ('24',  65, 500_000), # Medina
        ('14',  70, 500_000), # La Meca
        ('25',  45, 200_000), # Tabuk
        ('26',  50, 150_000), # Yanbu
        ('28',  42, 200_000), # Abha
        ('34',  38, 200_000), # Hafar Al-Batin
        ('35',  45, 150_000), # Qatif
    ],

    # ══════════════════════════════════════════════════════════════
    # TAILANDIA — TH
    # ══════════════════════════════════════════════════════════════
    'TH': [
        ('10', 100, 800_000), # Bangkok Sukhumvit / Silom / Sathon
        ('11',  85, 600_000), # Bangkok centro
        ('12',  65, 500_000), # Bangkok norte
        ('13',  55, 400_000), # Bangkok este
        ('14',  45, 400_000), # Bangkok outer
        ('15',  55, 300_000), # Pathum Thani
        ('76',  80, 200_000), # Phuket
        ('83',  72, 100_000), # Phuket ciudad
        ('20',  58, 300_000), # Chonburi / Pattaya
        ('21',  45, 200_000), # Chonburi inner
        ('77',  65, 200_000), # Surat Thani / Koh Samui
        ('50',  65, 300_000), # Chiang Mai
        ('52',  50, 200_000), # Chiang Mai outer
        ('51',  42, 150_000), # Chiang Rai
        ('53',  35, 100_000), # Chiang Mai rural
        ('73',  50, 150_000), # Nakhon Pathom
        ('74',  48, 150_000), # Samut Sakhon
        ('40',  42, 200_000), # Khon Kaen
        ('41',  38, 200_000), # Udon Thani
        ('80',  38, 200_000), # Nakhon Si Thammarat
        ('84',  45, 150_000), # Surat Thani
        ('90',  45, 200_000), # Songkhla / Hat Yai
        ('25',  40, 200_000), # Ayutthaya
        ('57',  28,  80_000), # Mae Hong Son
        ('94',  28, 100_000), # Pattani
    ],

    # ══════════════════════════════════════════════════════════════
    # TURQUÍA — TR
    # ══════════════════════════════════════════════════════════════
    'TR': [
        ('34', 100, 3_000_000), # Estambul (ambos lados)
        ('35',  88, 800_000),   # İzmir Konak / Alsancak
        ('48',  82, 300_000),   # Muğla / Bodrum / Marmaris
        ('61',  80, 400_000),   # Trabzon (alto turismo)
        ('06',  78, 800_000),   # Ankara Çankaya / Kavaklidere
        ('07',  72, 500_000),   # Antalya centro
        ('09',  68, 400_000),   # Aydın / Bodrum interior
        ('77',  55, 200_000),   # Yalova
        ('59',  52, 200_000),   # Tekirdağ
        ('41',  65, 400_000),   # Kocaeli / İzmit
        ('16',  60, 500_000),   # Bursa centro
        ('26',  52, 400_000),   # Eskişehir
        ('42',  50, 500_000),   # Konya
        ('33',  48, 400_000),   # Mersin
        ('27',  45, 500_000),   # Gaziantep
        ('38',  45, 300_000),   # Kayseri
        ('71',  38, 200_000),   # Kırıkkale
        ('54',  48, 300_000),   # Sakarya / Adapazarı
        ('55',  42, 300_000),   # Samsun
        ('45',  42, 250_000),   # Manisa
        ('44',  38, 200_000),   # Malatya
        ('31',  38, 200_000),   # Hatay
        ('78',  35, 100_000),   # Karabük
        ('67',  35, 200_000),   # Zonguldak
        ('22',  38, 150_000),   # Edirne
        ('52',  32, 150_000),   # Ordu
        ('53',  35, 150_000),   # Rize
        ('70',  32, 100_000),   # Karaman
        ('60',  28, 150_000),   # Tokat
        ('58',  32, 150_000),   # Sivas
        ('46',  35, 200_000),   # Kahramanmaraş
        ('47',  28, 150_000),   # Mardin
        ('43',  35, 100_000),   # Kütahya
        ('25',  28, 200_000),   # Erzurum
        ('36',  22, 100_000),   # Kars
        ('63',  28, 200_000),   # Şanlıurfa
        ('65',  25, 200_000),   # Van
        ('56',  22, 100_000),   # Siirt
        ('73',  18, 100_000),   # Şırnak
        ('49',  20, 100_000),   # Muş
        ('75',  18,  80_000),   # Ardahan
        ('76',  20,  80_000),   # Iğdır
        ('69',  20,  60_000),   # Bayburt
    ],

    # ══════════════════════════════════════════════════════════════
    # PORTUGAL — PT  (primeros 2 dígitos del CP de 4 dígitos, 1000-9999)
    # ══════════════════════════════════════════════════════════════
    'PT': [
        # Lisboa (1xxx)
        ('12', 100,  80_000), # Lisboa Chiado / Bairro Alto
        ('11',  90,  80_000), # Lisboa Campo de Ourique / Estrela
        ('10',  85,  60_000), # Lisboa Centro / Alfama
        ('13',  80,  70_000), # Lisboa Belém / Ajuda
        ('14',  75,  80_000), # Lisboa Penha de França / Areeiro
        ('15',  68,  90_000), # Lisboa Benfica / Carnide
        ('16',  70,  90_000), # Lisboa Lumiar / Telheiras
        ('17',  74,  80_000), # Lisboa Alvalade
        ('18',  60,  80_000), # Lisboa Sacavém / Loures
        ('19',  62,  80_000), # Lisboa Olivais / Oriente
        # Arredores de Lisboa (2xxx)
        ('26',  68,  80_000), # Sintra / Queluz
        ('27',  72,  80_000), # Amadora / Cascais
        ('28',  70, 150_000), # Almada / Seixal
        ('29',  55, 150_000), # Setúbal
        # Centro (3xxx)
        ('30',  68, 130_000), # Coimbra Centro
        ('31',  56,  80_000), # Pombal / Cantanhede
        ('32',  52,  80_000), # Leiria
        ('33',  48,  60_000), # Figueira da Foz
        ('34',  45,  70_000), # Viseu
        ('35',  42,  50_000), # Guarda
        # Porto / Norte (4xxx)
        ('41', 100, 130_000), # Porto Foz / Boavista Premium
        ('40',  88, 150_000), # Porto Baixa / Ribeira
        ('42',  80, 200_000), # Porto Gondomar / Campanhã
        ('43',  82, 100_000), # Matosinhos / Leça
        ('44',  78, 200_000), # Vila Nova de Gaia
        ('45',  70, 100_000), # Espinho / Santa Maria da Feira
        ('46',  68, 130_000), # Aveiro
        ('47',  74, 180_000), # Braga Centro
        ('48',  66, 130_000), # Guimarães
        ('49',  58,  90_000), # Viana do Castelo
        # Interior Norte (5xxx)
        ('50',  40,  70_000), # Lamego / Régua
        ('51',  36,  50_000), # Peso da Régua
        ('52',  33,  45_000), # Bragança
        ('53',  36,  55_000), # Chaves
        ('54',  38,  60_000), # Vila Real
        # Beiras Interiores (6xxx)
        ('60',  36,  45_000), # Covilhã
        ('61',  33,  35_000), # Fundão
        ('62',  38,  50_000), # Castelo Branco
        ('63',  30,  28_000), # Portalegre
        # Alentejo (7xxx)
        ('70',  40,  70_000), # Évora
        ('71',  33,  50_000), # Beja
        ('72',  35,  40_000), # Santiago do Cacém / Sines
        ('73',  36,  45_000), # Elvas
        # Algarve (8xxx)
        ('80',  70,  90_000), # Faro
        ('81',  78, 100_000), # Loulé / Vilamoura
        ('82',  82,  90_000), # Albufeira
        ('83',  78,  80_000), # Portimão / Lagos
        ('84',  70,  60_000), # Tavira / Olhão
        # Açores e Madeira (9xxx)
        ('90',  60,  40_000), # Ponta Delgada (Açores)
        ('91',  50,  25_000), # Angra do Heroísmo (Açores)
        ('94',  65,  70_000), # Funchal (Madeira)
        ('95',  55,  40_000), # Santa Cruz (Madeira)
    ],

    # ══════════════════════════════════════════════════════════════
    # SUIZA — CH  (primeros 2 dígitos del CP de 4 dígitos, 1000-9999)
    # ══════════════════════════════════════════════════════════════
    'CH': [
        # Zúrich (8xxx)
        ('80', 100, 200_000), # Zúrich Seefeld / Enge / Altstadt
        ('81',  88, 100_000), # Zúrich Fluntern / Witikon
        ('82',  85, 120_000), # Küsnacht / Zollikon (orilla lago)
        ('83',  78, 100_000), # Richterswil / Wädenswil
        ('84',  82,  80_000), # Meilen / Herrliberg (lago premium)
        ('85',  76, 130_000), # Winterthur Centro
        ('86',  64,  80_000), # Winterthur Norte
        ('87',  60,  60_000), # Winterthur Töss
        ('88',  70,  80_000), # Rapperswil-Jona
        ('89',  68,  60_000), # Uster / Pfäffikon (Zürichsee)
        # Ginebra (12xx-13xx)
        ('12', 100, 200_000), # Ginebra Centro / Eaux-Vives
        ('13',  80, 100_000), # Ginebra Carouge / Plan-les-Ouates
        # Lausana / Vaud (10xx-11xx)
        ('10',  95, 150_000), # Lausana / Pully
        ('11',  76, 100_000), # Morges / Nyon / Vaud Norte
        # Berna (30xx-34xx)
        ('30',  88, 130_000), # Berna Centro / Kirchenfeld
        ('31',  76, 150_000), # Berna Köniz / Muri
        ('32',  64,  90_000), # Biel / Bienne
        ('33',  58,  80_000), # Thun
        ('34',  54,  70_000), # Langnau / Burgdorf
        ('36',  56,  50_000), # Interlaken / Grindelwald
        # Basilea (40xx-42xx)
        ('40',  88, 180_000), # Basilea Centro / Gundeldingen
        ('41',  74, 100_000), # Basilea Riehen / Bettingen
        ('42',  62,  80_000), # Liestal / Arlesheim
        # Argovia (50xx-53xx)
        ('45',  60,  80_000), # Solothurn / Olten
        ('50',  68,  90_000), # Aarau
        ('53',  70,  80_000), # Baden
        # Lucerna / Suiza Central (60xx-69xx)
        ('60',  76, 180_000), # Lucerna Centro
        ('61',  64,  90_000), # Emmen / Kriens
        ('62',  52,  70_000), # Sursee / Willisau
        ('63',  82,  60_000), # Zug (premium)
        ('64',  66,  50_000), # Schwyz / Brunnen
        # Grisones (70xx-72xx)
        ('70',  74,  70_000), # Chur / Graubünden
        ('71',  78,  40_000), # Davos
        ('72',  80,  30_000), # St. Moritz / Engadina Alta
        # Valais / Neuchâtel / Friburgo
        ('17',  64,  80_000), # Friburgo / Freiburg
        ('19',  60,  80_000), # Sion / Sierre (Valais)
        ('20',  64,  80_000), # Neuchâtel
        # Ticino (65xx-69xx)
        ('65',  76,  90_000), # Lugano
        ('66',  62,  60_000), # Bellinzona / Locarno
        # San Galo (90xx-94xx)
        ('90',  68, 130_000), # San Galo / St. Gallen Centro
        ('91',  58,  80_000), # Rorschach / Gossau
        ('94',  54,  60_000), # Appenzell / Herisau
    ],

    # ══════════════════════════════════════════════════════════════
    # BÉLGICA — BE  (primeros 2 dígitos del CP de 4 dígitos, 1000-9999)
    # ══════════════════════════════════════════════════════════════
    'BE': [
        # Bruselas (10xx-19xx)
        ('10', 100, 200_000), # Bruselas Ixelles / Etterbeek / Pentagone
        ('11',  88, 150_000), # Bruselas Uccle / Woluwe-Saint-Pierre
        ('12',  80, 100_000), # Brabante Valón / Waterloo
        ('13',  74, 100_000), # Ottignies / Louvain-la-Neuve
        ('14',  68,  80_000), # Nivelles / Braine-l'Alleud
        ('15',  65,  60_000), # Halle / Braine-le-Château
        ('16',  62,  50_000), # Rhode-Saint-Genèse
        ('18',  70,  80_000), # Vilvoorde / Machelen
        ('19',  66,  60_000), # Grimbergen / Diegem
        # Amberes (20xx-29xx)
        ('20',  92, 200_000), # Amberes Centro / Eilandje
        ('21',  76, 150_000), # Amberes Norte / Merksem
        ('22',  64, 150_000), # Mechelen Ciudad
        ('23',  56, 120_000), # Turnhout / Mol interior
        ('24',  52,  80_000), # Mol / Geel (Kempen)
        # Lovaina y Limburgo (30xx-39xx)
        ('30',  86,  90_000), # Lovaina / Leuven Centro
        ('31',  70,  80_000), # Lovaina Este / Tervuren
        ('32',  58,  70_000), # Tienen
        ('33',  52,  60_000), # Diest
        ('35',  60,  80_000), # Hasselt Centro
        ('36',  52,  70_000), # Genk
        ('37',  48,  60_000), # Tongeren
        ('38',  46,  60_000), # Sint-Truiden
        # Lieja (40xx-49xx)
        ('40',  78, 180_000), # Lieja Centro / Guillemins
        ('41',  64, 130_000), # Lieja Seraing / Ans
        ('42',  50,  90_000), # Herstal / Visé
        ('43',  46,  70_000), # Huy
        ('44',  43,  60_000), # Waremme / Hannut
        # Namur (50xx-59xx)
        ('50',  64,  90_000), # Namur Centro
        ('51',  50,  60_000), # Namur Este / Gembloux
        ('52',  44,  50_000), # Dinant
        ('53',  40,  40_000), # Philippeville / Couvin
        # Hainaut / Charleroi (60xx-79xx)
        ('60',  68, 180_000), # Charleroi Centro
        ('61',  54, 120_000), # Charleroi Este / Fleurus
        ('62',  43,  90_000), # Thuin / Beaumont
        ('67',  50,  40_000), # Arlon / Luxemburgo belga
        ('68',  43,  40_000), # Bastogne / La Roche-en-Ardenne
        ('70',  64,  90_000), # Mons Centro
        ('71',  50,  90_000), # La Louvière
        ('72',  44,  70_000), # Soignies
        ('73',  40,  60_000), # Ath / Enghien
        # Flandes Occidental (80xx-89xx — Brujas / Bélgica Costa)
        ('80',  80, 130_000), # Brujas / Brugge Centro
        ('81',  68,  80_000), # Brujas Este / Beernem
        ('82',  62,  70_000), # Torhout / Tielt
        ('83',  70,  70_000), # Ieper / Ypres
        ('84',  68,  80_000), # Kortrijk Centro
        ('85',  62,  60_000), # Roeselare
        ('86',  58,  60_000), # Ostende
        ('87',  54,  50_000), # Veurne / De Panne (Costa)
        # Flandes Oriental (90xx-99xx — Gante)
        ('90',  86, 220_000), # Gante / Gent Centro
        ('91',  73, 100_000), # Gante Este / Wetteren
        ('92',  64,  80_000), # Lokeren / Sint-Niklaas
        ('93',  58,  70_000), # Oudenaarde
        ('94',  60,  70_000), # Aalst Centro
        ('95',  53,  80_000), # Dendermonde
        ('96',  50,  60_000), # Geraardsbergen
    ],

    # ══════════════════════════════════════════════════════════════
    # PAÍSES BAJOS — NL  (primeros 2 dígitos del CP de 4 dígitos, 1000-9999)
    # ══════════════════════════════════════════════════════════════
    'NL': [
        # Ámsterdam (10xx-11xx)
        ('10', 100, 130_000), # Ámsterdam Centrum / Jordaan / Oud-Zuid
        ('11',  70,  90_000), # Ámsterdam Zuidoost / Bijlmer
        # Noord-Holland
        ('12',  82,  70_000), # Hilversum / Laren / 't Gooi
        ('13',  65, 200_000), # Almere (Flevoland)
        ('14',  70,  50_000), # Bussum / Naarden
        ('20',  84,  90_000), # Haarlem
        ('21',  72,  60_000), # Haarlem suburbios / Heemstede
        # Zuid-Holland
        ('22',  70,  80_000), # Katwijk / Noordwijk
        ('23',  78,  90_000), # Leiden Centro
        ('24',  74,  60_000), # Alphen aan den Rijn
        ('25',  88, 180_000), # Den Haag Centrum / Statenkwartier
        ('26',  76, 100_000), # Delft
        ('27',  68,  80_000), # Zoetermeer / Leidschendam
        ('28',  60,  80_000), # Gouda
        ('30',  78, 120_000), # Rotterdam Centrum / Kralingen
        ('31',  62, 100_000), # Rotterdam Noord / Schiedam
        ('32',  54,  90_000), # Spijkenisse / Barendrecht
        ('33',  58,  90_000), # Dordrecht
        ('34',  52,  60_000), # Gorinchem
        # Utrecht
        ('35',  82, 170_000), # Utrecht Centrum
        ('36',  70, 100_000), # Nieuwegein / IJsselstein
        ('37',  64,  80_000), # Veenendaal / Zeist
        ('38',  68, 100_000), # Amersfoort
        # Noord-Brabant
        ('42',  66, 120_000), # 's-Hertogenbosch área
        ('44',  54,  80_000), # Waalwijk
        ('46',  54,  80_000), # Bergen op Zoom
        ('47',  56,  80_000), # Helmond
        ('48',  64, 170_000), # Breda
        ('49',  52,  80_000), # Roosendaal
        ('50',  62, 180_000), # Tilburg Centro
        ('52',  68, 120_000), # 's-Hertogenbosch / Den Bosch
        ('55',  72, 180_000), # Eindhoven área
        ('56',  76, 180_000), # Eindhoven Centrum
        ('57',  62,  80_000), # Veldhoven / Waalre
        ('58',  56,  80_000), # Weert
        ('59',  60,  80_000), # Venlo
        # Limburg / Gelderland
        ('62',  74,  90_000), # Maastricht
        ('63',  62,  80_000), # Nijmegen área
        ('65',  70, 130_000), # Nijmegen Centrum
        ('68',  62, 130_000), # Arnhem
        # Overijssel / Gelderland
        ('73',  65, 130_000), # Apeldoorn
        ('74',  62,  80_000), # Deventer
        ('75',  60, 130_000), # Enschede
        ('76',  54,  80_000), # Almelo
        # Overijssel / Drenthe
        ('80',  68,  90_000), # Zwolle
        ('83',  55,  60_000), # Hoogeveen / Drenthe Sur
        # Friesland / Groningen
        ('89',  55,  70_000), # Leeuwarden
        ('97',  68, 180_000), # Groningen Centrum
    ],

    # ══════════════════════════════════════════════════════════════
    # INDONESIA — ID  (primeros 2 dígitos del CP de 5 dígitos, 10000-99999)
    # ══════════════════════════════════════════════════════════════
    'ID': [
        # Jakarta (10xxx-14xxx)
        ('10', 100, 400_000), # Jakarta Pusat (Menteng / Gambir premium)
        ('12',  90, 500_000), # Jakarta Selatan (Kebayoran Baru / Setiabudi)
        ('11',  68, 600_000), # Jakarta Barat
        ('13',  62, 600_000), # Jakarta Timur
        ('14',  55, 500_000), # Jakarta Utara
        # Jabodetabek
        ('15',  74, 800_000), # Tangerang Selatan / BSD City / Serpong
        ('16',  62, 700_000), # Bogor / Depok
        ('17',  68, 700_000), # Bekasi
        ('18',  58, 400_000), # Tangerang Kota
        # Sumatra
        ('20',  68, 400_000), # Medan Centro (Medan Baru / Petisah)
        ('25',  48, 200_000), # Padang (Sumatra Barat)
        ('28',  58, 250_000), # Pekanbaru (Riau)
        ('29',  70, 200_000), # Batam (Kepulauan Riau — zona libre)
        ('30',  52, 400_000), # Palembang
        # Java Barat
        ('40',  78, 300_000), # Bandung Centro (Dago / Coblong premium)
        ('42',  55, 200_000), # Serang / Cilegon (Banten)
        ('43',  48, 200_000), # Sukabumi
        ('45',  44, 200_000), # Cirebon
        # Jawa Tengah / DIY
        ('50',  62, 350_000), # Semarang Centro
        ('51',  50, 250_000), # Salatiga / Semarang suburbios
        ('55',  58, 250_000), # Yogyakarta
        ('57',  52, 250_000), # Solo / Surakarta
        # Jawa Timur
        ('60',  82, 500_000), # Surabaya Centro (Gubeng / Genteng premium)
        ('61',  65, 600_000), # Surabaya Norte / Gresik
        ('62',  58, 500_000), # Surabaya Sur / Sidoarjo
        ('65',  58, 300_000), # Malang
        # Kalimantan
        ('75',  52, 200_000), # Samarinda (Kalimantan Timur)
        ('76',  62, 200_000), # Balikpapan (Kalimantan Timur)
        ('78',  46, 200_000), # Pontianak (Kalimantan Barat)
        # Bali / Nusa Tenggara
        ('80',  86, 300_000), # Denpasar / Bali Sur (Kuta / Seminyak)
        ('83',  52, 150_000), # Mataram / Lombok
        # Sulawesi / Papua
        ('90',  62, 400_000), # Makassar Centro (Sulawesi Selatan)
        ('91',  48, 300_000), # Makassar Norte / Maros
        ('95',  48, 150_000), # Manado (Sulawesi Utara)
        ('99',  38, 150_000), # Jayapura (Papua)
    ],

    # ══════════════════════════════════════════════════════════════
    # EGIPTO — EG  (primeros 2 dígitos del CP de 5 dígitos, 11000-92999)
    # ══════════════════════════════════════════════════════════════
    'EG': [
        # El Cairo y Gran Cairo (11xxx-12xxx)
        ('11',  70, 800_000), # El Cairo Zamalek / Heliopolis / Maadi / Nasr City
        ('12',  65, 600_000), # Giza / Mohandessin / Dokki / 6th October
        # Alejandría (21xxx)
        ('21',  58, 500_000), # Alejandría Centro / Smouha / Sidi Bishr
        # Canal de Suez
        ('41',  48, 150_000), # Ismailia
        ('42',  52, 200_000), # Port Said
        ('43',  45, 150_000), # Suez
        # Delta del Nilo
        ('31',  42, 400_000), # Tanta / Gharbiya
        ('33',  36, 300_000), # Damietta / Kafr el-Sheikh Norte
        ('34',  38, 400_000), # Mahalla el-Kobra / Kafr el-Sheikh
        ('35',  40, 500_000), # Mansoura / Dakahlia
        ('36',  35, 300_000), # Benha / Qalyubiya
        # Sinai
        ('44',  45, 150_000), # El-Arish / Sinai Norte
        ('46',  55, 100_000), # Sharm El Sheikh / Sinai Sur
        # Marsa Matruh / Costero Norte
        ('51',  30, 100_000), # Marsa Matruh
        # Medio Egipto
        ('25',  36, 300_000), # El Fayum
        ('62',  35, 300_000), # Beni Suef
        ('71',  38, 400_000), # Asiut
        # Mar Rojo
        ('84',  52, 150_000), # Hurghada / Mar Rojo
        # Alto Egipto
        ('81',  40, 300_000), # Aswan
        ('82',  42, 300_000), # Luxor
        ('85',  32, 200_000), # Qena
        ('92',  30, 150_000), # Sohag
    ],

    # ══════════════════════════════════════════════════════════════
    # MARRUECOS — MA  (primeros 2 dígitos del CP de 5 dígitos, 10000-93000)
    # ══════════════════════════════════════════════════════════════
    'MA': [
        # Rabat / Salé (10xxx-11xxx)
        ('10',  92, 300_000), # Rabat Agdal / Hassan / Hay Riad
        ('11',  78, 200_000), # Rabat Salé / Témara
        # Casablanca (20xxx-22xxx)
        ('20', 100, 800_000), # Casablanca Centro / Maarif / Anfa
        ('21',  82, 500_000), # Casablanca Norte / Sidi Maarouf
        ('22',  68, 400_000), # Casablanca Sur / Aïn Sebaâ
        # Beni Mellal / El Jadida / Settat
        ('23',  44, 150_000), # Beni Mellal / Khouribga
        ('24',  48, 150_000), # El Jadida / Azemmour
        ('26',  40, 100_000), # Settat
        # Fès (30xxx-31xxx)
        ('30',  62, 300_000), # Fès Ville Nouvelle / Agdal
        ('31',  48, 200_000), # Fès Médina / Saïss
        # Kenitra
        ('14',  55, 200_000), # Kenitra / Sidi Slimane
        # Marrakech (40xxx-42xxx)
        ('40',  82, 400_000), # Marrakech Guéliz / Hivernage
        ('41',  65, 300_000), # Marrakech Médina
        ('42',  56, 200_000), # Marrakech afueras / Menara
        # Essaouira / Safi
        ('44',  42,  80_000), # Essaouira
        ('46',  40, 120_000), # Safi
        # Meknès (50xxx-51xxx)
        ('50',  52, 250_000), # Meknès Centro
        ('51',  40, 150_000), # Meknès rural / Ifrane
        # Interior / Sahara
        ('52',  28,  80_000), # Errachidia / Midelt
        # Oujda / Oriental (60xxx-62xxx)
        ('60',  50, 200_000), # Oujda
        ('62',  40, 150_000), # Nador
        # Laayoune / Sahara Occidental
        ('70',  36,  80_000), # Laayoune
        ('73',  30,  50_000), # Dakhla
        # Agadir / Souss (80xxx-81xxx)
        ('80',  70, 200_000), # Agadir Centro / Talborjt
        ('81',  62, 150_000), # Agadir afueras / Inezgane
        # Tánger / Norte (90xxx-93xxx)
        ('90',  76, 300_000), # Tánger Centro / Marchane
        ('91',  62, 200_000), # Tánger Malabata / Achakar
        ('93',  58, 200_000), # Tétouan
    ],

    # ══════════════════════════════════════════════════════════════
    # TAIWÁN — TW  (primeros 3 dígitos del CP de 3 o 5 dígitos)
    # ══════════════════════════════════════════════════════════════
    'TW': [
        # Taipéi (100-116) — prefijo 3 dígitos
        ('106', 100, 120_000), # Taipéi Da'an (más premium)
        ('110',  92,  80_000), # Taipéi Xinyi (Taipei 101 / Xinyi Dist)
        ('104',  85,  80_000), # Taipéi Zhongshan
        ('105',  88,  80_000), # Taipéi Songshan
        ('100',  80,  80_000), # Taipéi Zhongzheng (gobierno/histórico)
        ('114',  82, 100_000), # Taipéi Neihu (parque tecnológico)
        ('111',  70, 120_000), # Taipéi Shilin
        ('112',  68,  80_000), # Taipéi Beitou
        ('115',  72,  60_000), # Taipéi Nangang
        ('116',  65, 100_000), # Taipéi Wenshan
        ('103',  62,  80_000), # Taipéi Datong
        ('108',  52,  80_000), # Taipéi Wanhua
        # Nueva Taipéi (22x-25x)
        ('220',  78, 400_000), # Nueva Taipéi Banqiao
        ('231',  72, 250_000), # Nueva Taipéi Xindian
        ('235',  70, 250_000), # Nueva Taipéi Zhonghe / Yonghe
        ('241',  68, 200_000), # Nueva Taipéi Sanchong
        ('251',  75, 150_000), # Nueva Taipéi Tamsui / Danshui
        # Keelung (200-206)
        ('200',  65, 150_000), # Keelung Ciudad
        # Taoyuan (320-338)
        ('320',  72, 400_000), # Taoyuan Ciudad
        ('330',  65, 200_000), # Taoyuan Zhongli
        # Hsinchu (300-315)
        ('300',  80, 200_000), # Hsinchu Ciudad (hub tecnológico)
        ('302',  70, 100_000), # Hsinchu County
        # Taichung (400-439)
        ('404',  82, 400_000), # Taichung Xitun / Nantun (premium)
        ('408',  75, 300_000), # Taichung Beitun / Norte
        ('401',  68, 200_000), # Taichung Centro
        ('413',  55, 200_000), # Taichung Dali
        # Tainan (700-745)
        ('700',  70, 500_000), # Tainan Centro / Anping
        ('704',  62, 300_000), # Tainan Norte / Rende
        ('708',  55, 200_000), # Tainan Sur / Yongkang
        # Kaohsiung (800-852)
        ('800',  82, 600_000), # Kaohsiung Xinxing / Lingya
        ('806',  78, 300_000), # Kaohsiung Zuoying (premium)
        ('830',  65, 300_000), # Kaohsiung Fengshan
        ('802',  58, 250_000), # Kaohsiung Qianzhen / Nanzih
        # Sur / Este
        ('900',  44, 200_000), # Pingtung Ciudad
        ('970',  42,  80_000), # Hualien Ciudad
        ('950',  38,  80_000), # Taitung Ciudad
    ],

    # ══════════════════════════════════════════════════════════════
    # HONG KONG — HK  (distritos 01-18, sin CP estándar)
    # ══════════════════════════════════════════════════════════════
    'HK': [
        # Hong Kong Island
        ('01', 100,  80_000), # Central y Western (CBD premium — Hong Kong Island)
        ('02',  92,  60_000), # Wan Chai
        ('03',  75, 100_000), # Eastern / Quarry Bay
        ('04',  65,  80_000), # Southern / Aberdeen
        # Kowloon
        ('05',  88, 100_000), # Yau Tsim Mong (Tsim Sha Tsui / Jordan)
        ('06',  65, 130_000), # Sham Shui Po
        ('07',  70,  80_000), # Kowloon City
        ('08',  60,  80_000), # Wong Tai Sin
        ('09',  58, 150_000), # Kwun Tong
        # Nuevos Territorios
        ('10',  65, 120_000), # Kwai Tsing
        ('11',  70,  80_000), # Tsuen Wan
        ('12',  55, 150_000), # Tuen Mun
        ('13',  60, 200_000), # Yuen Long
        ('14',  42,  80_000), # New Territories Norte
        ('15',  52,  90_000), # Tai Po
        ('16',  68, 150_000), # Sha Tin
        ('17',  74,  80_000), # Sai Kung / Clearwater Bay
        # Islas
        ('18',  52,  50_000), # Isla Lantau / Outlying Islands
    ],

    # ══════════════════════════════════════════════════════════════
    # REPÚBLICA DOMINICANA — DO  (primeros 2 dígitos del CP de 5 dígitos)
    # ══════════════════════════════════════════════════════════════
    'DO': [
        # Santo Domingo (10xxx)
        ('10', 100, 200_000), # Santo Domingo Piantini / Naco (premium)
        # Santo Domingo Este / Norte
        ('11',  75, 400_000), # Santo Domingo Norte / Villa Mella
        ('14',  60, 200_000), # Santo Domingo Este / Boca Chica
        # Interior / Este
        ('21',  48, 100_000), # San Pedro de Macorís
        ('22',  55, 100_000), # La Romana / Casa de Campo
        ('23',  70,  80_000), # Punta Cana / Bávaro (turismo)
        ('31',  36, 100_000), # San Francisco de Macorís
        ('41',  38,  80_000), # La Vega
        ('42',  33,  60_000), # Bonao
        ('48',  36,  60_000), # Moca
        # Norte / Cibao
        ('51',  62, 200_000), # Santiago Centro
        ('57',  45, 100_000), # Puerto Plata
        # Sur
        ('81',  30,  60_000), # Barahona
    ],

    # ══════════════════════════════════════════════════════════════
    # JORDANIA — JO  (primeros 2 dígitos del CP de 5 dígitos)
    # ══════════════════════════════════════════════════════════════
    'JO': [
        # Ammán (11xxx)
        ('11',  75, 800_000), # Ammán (Abdoun / Shmaisani / Jabal Amman)
        # Principales ciudades
        ('13',  42, 500_000), # Zarqa
        ('17',  46,  80_000), # Madaba
        ('19',  52, 100_000), # Salt / Balqa
        ('21',  50, 400_000), # Irbid
        ('25',  36, 150_000), # Mafraq
        ('26',  40,  80_000), # Ajloun / Jerash
        # Sur
        ('61',  33, 100_000), # Karak
        ('66',  30,  60_000), # Tafilah
        ('71',  28,  60_000), # Ma'an / Wadi Rum
        # Aqaba (77xxx)
        ('77',  62,  80_000), # Aqaba
    ],

    # ══════════════════════════════════════════════════════════════
    # KUWAIT — KW  (primeros 2 dígitos del CP de 5 dígitos)
    # ══════════════════════════════════════════════════════════════
    'KW': [
        # Kuwait City
        ('13', 100, 100_000), # Kuwait City Centro / Sharq (premium)
        ('22',  72,  60_000), # Salmiya / Salwa
        ('25',  65,  60_000), # Rumaithiya / Bayan
        # Hawalli
        ('32',  75, 200_000), # Hawalli
        ('43',  68,  50_000), # Bayan / Mishref
        # Al Jahra
        ('42',  44, 200_000), # Al Jahra
        # Ahmadi (61xxx-64xxx)
        ('47',  70,  40_000), # Sabah Al-Ahmad (nueva ciudad)
        ('61',  65, 200_000), # Ahmadi (zona petrolera)
        ('62',  46, 150_000), # Fahaheel
        ('63',  52,  60_000), # Abu Halifa
        ('64',  50,  60_000), # Mahboula
        # Mubarak Al-Kabeer
        ('77',  62,  80_000), # Mubarak Al-Kabeer
        # Farwaniya
        ('81',  56, 400_000), # Farwaniya
    ],

    # ══════════════════════════════════════════════════════════════
    # SENEGAL — SN  (prefijos de área — Dakar 10xxx, regiones 2x-6xxx)
    # ══════════════════════════════════════════════════════════════
    'SN': [
        # Dakar (10xxx-15xxx)
        ('10', 100,  80_000), # Dakar Plateau / Almadies (premium)
        ('11',  85, 100_000), # Dakar Mermoz / Fann / Point E
        ('12',  70, 200_000), # Dakar Médina / Liberté
        ('13',  55, 400_000), # Dakar Pikine
        ('14',  42, 500_000), # Guédiawaye
        ('15',  40, 200_000), # Rufisque / Diamniadio
        # Interior y Ciudades Medianas
        ('18',  36, 200_000), # Touba (ciudad santa)
        ('20',  35, 300_000), # Thiès
        ('22',  30, 150_000), # Saint-Louis
        ('23',  25, 100_000), # Diourbel
        ('30',  32, 200_000), # Kaolack
        ('40',  28,  80_000), # Ziguinchor
        # Interior profundo
        ('50',  18,  80_000), # Kolda / Sédhiou
        ('60',  16,  80_000), # Tambacounda / Kédougou
    ],

    # ══════════════════════════════════════════════════════════════
    # COSTA DE MARFIL — CI  (prefijos de distrito de Abidján 01-08, interior 20-70)
    # ══════════════════════════════════════════════════════════════
    'CI': [
        # Abidján (comunas)
        ('01', 100, 200_000), # Abidján Plateau / Zone 4 (CBD premium)
        ('02',  86, 200_000), # Abidján Cocody / Riviera
        ('03',  70, 400_000), # Abidján Marcory / Treichville
        ('04',  52, 600_000), # Abidján Yopougon
        ('05',  42, 700_000), # Abidján Abobo
        ('06',  55, 300_000), # Abidján Koumassi / Port-Bouët
        ('07',  62, 150_000), # Abidján Deux Plateaux / Angré
        ('08',  45, 200_000), # Abidján Adjamé / Attécoubé
        # Interior del país
        ('20',  36, 400_000), # Bouaké
        ('30',  30, 200_000), # Daloa
        ('40',  33, 200_000), # San-Pédro
        ('41',  26, 150_000), # Korhogo / Savanes
        ('50',  24, 100_000), # Man / Ouest
        ('60',  22, 100_000), # Abengourou
        ('70',  20, 100_000), # Odienné / Nord-Ouest
    ],

    # ══════════════════════════════════════════════════════════════
    # CAMERÚN — CM  (prefijos de área — Douala 40xxx, Yaundé 30xxx)
    # ══════════════════════════════════════════════════════════════
    'CM': [
        # Douala (40xxx-43xxx)
        ('40', 100, 400_000), # Douala Akwa / Bonanjo (CBD premium)
        ('41',  76, 400_000), # Douala Bali / Bonabéri
        ('42',  60, 500_000), # Douala Makepe / Logbaba
        ('43',  45, 600_000), # Douala New Bell / Nkongmamba
        # Yaundé (30xxx-33xxx)
        ('30',  86, 300_000), # Yaundé Bastos / Nlongkak (premium)
        ('31',  70, 300_000), # Yaundé Centro / Mvog-Mbi
        ('32',  52, 400_000), # Yaundé Messa / Tsinga
        ('33',  40, 500_000), # Yaundé Essos / Mimboman
        # Interior
        ('20',  36, 200_000), # Bafoussam / Ouest
        ('21',  30, 150_000), # Bamenda / Nord-Ouest
        ('50',  25, 150_000), # Garoua / Nord
        ('60',  22, 100_000), # Ngaoundéré / Adamawa
        ('70',  18, 100_000), # Maroua / Extrême-Nord
        ('10',  32, 100_000), # Bertoua / Est
        ('11',  28,  80_000), # Ebolowa / Sud
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
    """Dispatcher principal. Usa POSTAL_PREFIX_DATA para todos los países incluyendo US."""
    if country in POSTAL_PREFIX_DATA:
        data = process_prefix_data(country)
        return {'data': data, 'errors': [], 'total': len(data)}

    return {'data': [], 'errors': [{'error': f'{country} not implemented'}], 'total': 0}


def run_all_countries_import() -> dict:
    """Importa todos los países disponibles."""
    all_data, all_errors, total = [], [], 0
    all_countries = list(POSTAL_PREFIX_DATA.keys())
    for cc in all_countries:
        result = run_zip_import(cc)
        all_data.extend(result['data'])
        all_errors.extend(result['errors'])
        total += result['total']
    return {'data': all_data, 'errors': all_errors, 'total': total,
            'countries': all_countries}
