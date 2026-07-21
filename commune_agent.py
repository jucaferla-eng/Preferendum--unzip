"""
commune_agent.py  —  PREFERENDUM
Clasificación socioeconómica por precio de arriendo m²/mes.
Chile: UF/m² (Vitacura = 0.40 = índice 100)
Otros: USD/m² (ciudad/county más caro del país = índice 100)
Tiers: A ≥80 | B 55-79 | C 35-54 | D <35
En memoria del Socio Fundador José Ignacio Fernández (1989–2024)
"""

from datetime import datetime

REFERENCIA_UF_M2   = 0.40
REFERENCIA_COMMUNE = 'Vitacura'

# ── CHILE (UF/m²) ─────────────────────────────────────────────
COMUNAS_DATA = [
    ("Vitacura",           "RM",   0.40, 92_000),
    ("Las Condes",         "RM",   0.39, 310_000),
    ("Lo Barnechea",       "RM",   0.38, 105_000),
    ("Providencia",        "RM",   0.38, 150_000),
    ("La Reina",           "RM",   0.32, 98_000),
    ("Ñuñoa",              "RM",   0.28, 225_000),
    ("Peñalolén",          "RM",   0.24, 240_000),
    ("Santiago",           "RM",   0.24, 520_000),
    ("Macul",              "RM",   0.23, 130_000),
    ("San Miguel",         "RM",   0.23, 110_000),
    ("Antofagasta",        "II",   0.23, 420_000),
    ("La Florida",         "RM",   0.22, 380_000),
    ("Independencia",      "RM",   0.22, 105_000),
    ("Huechuraba",         "RM",   0.21, 98_000),
    ("Maipú",              "RM",   0.21, 620_000),
    ("San Pedro de la Paz","VIII", 0.21, 135_000),
    ("Recoleta",           "RM",   0.20, 175_000),
    ("Iquique",            "I",    0.20, 245_000),
    ("La Serena",          "IV",   0.20, 250_000),
    ("Quilicura",          "RM",   0.19, 235_000),
    ("Estación Central",   "RM",   0.19, 145_000),
    ("Concepción",         "VIII", 0.19, 245_000),
    ("Quinta Normal",      "RM",   0.18, 115_000),
    ("Temuco",             "IX",   0.18, 360_000),
    ("Valparaíso",         "V",    0.18, 310_000),
    ("Cerrillos",          "RM",   0.17, 90_000),
    ("Conchalí",           "RM",   0.17, 140_000),
    ("Quilpué",            "V",    0.17, 235_000),
    ("Puerto Montt",       "X",    0.17, 275_000),
    ("Rancagua",           "VI",   0.17, 245_000),
    ("Punta Arenas",       "XII",  0.17, 145_000),
    ("Coquimbo",           "IV",   0.17, 245_000),
    ("Pudahuel",           "RM",   0.16, 245_000),
    ("Arica",              "XV",   0.16, 245_000),
    ("Talcahuano",         "VIII", 0.16, 175_000),
    ("Renca",              "RM",   0.15, 155_000),
    ("Lo Prado",           "RM",   0.14, 110_000),
    ("Lo Espejo",          "RM",   0.13, 115_000),
    ("Cerro Navia",        "RM",   0.12, 145_000),
    ("El Bosque",          "RM",   0.12, 185_000),
    ("San Ramón",          "RM",   0.11, 100_000),
    ("La Pintana",         "RM",   0.10, 225_000),
    ("Concón",             "V",    0.26, 52_000),
    ("Viña del Mar",       "V",    0.23, 390_000),
]

# CPM base USD por país (Meta/Google ARPU benchmark 2024)
CPM_BASE_BY_COUNTRY = {
    'CL': 8.0,  'US': 18.0, 'GB': 14.0, 'AU': 12.0, 'CA': 12.0,
    'DE': 12.0, 'FR': 10.0, 'IT':  9.0, 'ES':  9.0, 'BR':  7.0,
    'MX':  6.0, 'CO':  5.0, 'AR':  5.0, 'ZA':  4.0, 'UY':  5.0,
    'EC':  4.0, 'VE':  3.0, 'BO':  3.0, 'PY':  3.0, 'PE':  4.0,
    'IN':  3.0, 'NG':  2.0,
}

# ── DATOS GLOBALES — (nombre, usd_m2_mes, población) ──────────
# Nombre debe coincidir EXACTAMENTE con voter_portal.html
GLOBAL_RENT_DATA: dict[str, list] = {

    # ═══ ESTADOS UNIDOS — counties y áreas metro ══════════════
    'US': [
        # NYC Metro
        ("Manhattan",             55, 1_629_000),
        ("Brooklyn",              32, 2_576_000),
        ("Queens",                26, 2_271_000),
        ("Staten Island",         22,   476_000),
        ("Bronx",                 20, 1_427_000),
        ("Westchester County",    35,   968_000),
        ("Nassau County",         28, 1_360_000),
        ("Hudson County NJ",      30,   724_000),
        # LA Metro
        ("Los Angeles County",    32, 9_800_000),
        ("Orange County CA",      30, 3_200_000),
        ("Ventura County",        22,   843_000),
        ("Riverside County",      18, 2_400_000),
        ("San Bernardino County", 15, 2_200_000),
        # SF Bay Area
        ("San Francisco",         50,   873_000),
        ("Silicon Valley",        48, 1_900_000),
        ("San Mateo County",      42,   766_000),
        ("Marin County",          40,   260_000),
        ("Alameda County",        35, 1_671_000),
        ("Boulder County",        30,   325_000),
        ("Contra Costa County",   28, 1_150_000),
        # Greater DC
        ("Washington DC",         35,   689_000),
        ("Arlington County",      32,   238_000),
        ("Alexandria VA",         30,   160_000),
        ("Fairfax County",        28, 1_150_000),
        ("Loudoun County",        26,   430_000),
        ("Montgomery County MD",  26, 1_050_000),
        # Greater Boston
        ("Cambridge MA",          42,   118_000),
        ("Brookline MA",          38,    60_000),
        ("Boston",                38,   675_000),
        ("Newton MA",             35,    88_000),
        ("Somerville MA",         34,    82_000),
        ("Norfolk County MA",     26,   700_000),
        ("Middlesex County MA",   26, 1_600_000),
        # Seattle Metro
        ("Bellevue WA",           38,   150_000),
        ("Seattle",               32,   750_000),
        ("Kirkland WA",           30,   130_000),
        ("Snohomish County",      20,   830_000),
        ("Tacoma",                16,   218_000),
        # Chicago Metro
        ("Evanston IL",           24,    78_000),
        ("Chicago",               22, 2_700_000),
        ("DuPage County",         20,   932_000),
        ("Lake County IL",        18,   703_000),
        ("Will County",           15,   700_000),
        # Miami Metro
        ("Miami Beach",           35,    90_000),
        ("Palm Beach County",     26, 1_500_000),
        ("Miami-Dade County",     26, 2_700_000),
        ("Broward County",        22, 1_944_000),
        # Dallas Metro
        ("Collin County",         20, 1_064_000),
        ("Rockwall County",       20,   100_000),
        ("Dallas County",         18, 2_613_000),
        ("Denton County",         17,   906_000),
        ("Tarrant County",        15, 2_110_000),
        # Houston Metro
        ("Fort Bend County",      16,   800_000),
        ("Galveston County",      16,   340_000),
        ("Harris County",         15, 4_718_000),
        ("Montgomery County TX",  14,   620_000),
        # Denver Metro
        ("Douglas County CO",     22,   360_000),
        ("Denver",                22,   750_000),
        ("Jefferson County CO",   20,   582_000),
        ("Arapahoe County",       20,   655_000),
        ("Adams County CO",       16,   520_000),
        # Philadelphia Metro
        ("Chester County PA",     22,   528_000),
        ("Montgomery County PA",  22,   830_000),
        ("Bucks County PA",       20,   625_000),
        ("Delaware County PA",    20,   564_000),
        ("Philadelphia",          18, 1_600_000),
        # Atlanta Metro
        ("Fulton County",         20, 1_066_000),
        ("Cobb County",           18,   763_000),
        ("Gwinnett County",       16,   957_000),
        ("DeKalb County",         16,   764_000),
        # Nashville Metro
        ("Williamson County TN",  22,   242_000),
        ("Davidson County",       18,   689_000),
        # Minneapolis
        ("Hennepin County",       18, 1_273_000),
        ("Ramsey County",         16,   552_000),
        # Portland Metro
        ("Washington County OR",  22,   600_000),
        ("Multnomah County",      22,   815_000),
        ("Clackamas County",      18,   420_000),
        # Austin Metro
        ("Williamson County TX",  22,   700_000),
        ("Travis County",         22, 1_250_000),
        # Phoenix Metro
        ("Scottsdale",            22,   241_000),
        ("Maricopa County",       18, 4_420_000),
        ("Pima County",           14, 1_043_000),
        # Charlotte
        ("Mecklenburg County",    16, 1_100_000),
        # San Diego
        ("San Diego County",      32, 3_300_000),
        # Las Vegas
        ("Clark County",          18, 2_227_000),
        # San Antonio
        ("Bexar County",          13, 2_009_000),
        # Indianapolis
        ("Hamilton County IN",    17,   343_000),
        ("Marion County",         13,   964_000),
        # Columbus
        ("Delaware County OH",    17,   200_000),
        ("Franklin County",       14, 1_316_000),
        # Jacksonville
        ("St Johns County FL",    18,   264_000),
        ("Duval County",          14,   949_000),
        # Baltimore
        ("Howard County MD",      26,   330_000),
        ("Baltimore County",      18,   854_000),
        ("Baltimore City",        14,   585_000),
        # Other
        ("Salt Lake County",      18, 1_160_000),
        ("Honolulu County",       35,   350_000),
        ("Multnomah County OR",   22,   815_000),
        ("Oklahoma County",       12,   793_000),
        ("El Paso County TX",     12,   865_000),
        ("Allegheny County",      14, 1_223_000),
        ("Hamilton County OH",    14,   830_000),
        ("Cuyahoga County",       12, 1_264_000),
        ("Milwaukee County",      12,   950_000),
        ("Memphis Shelby County", 10,   936_000),
    ],

    # ═══ REINO UNIDO — London Boroughs + ciudades ══════════════
    'GB': [
        # Inner London (premium)
        ("Kensington & Chelsea",    65,   140_000),
        ("Westminster",             58,   250_000),
        ("City of London",          55,    10_000),
        ("Camden",                  50,   270_000),
        ("Islington",               47,   230_000),
        ("Hammersmith & Fulham",    45,   190_000),
        ("Richmond upon Thames",    42,   200_000),
        ("Wandsworth",              40,   330_000),
        # Inner London (mid)
        ("Hackney",                 38,   280_000),
        ("Southwark",               36,   310_000),
        ("Tower Hamlets",           35,   340_000),
        ("Lambeth",                 35,   330_000),
        ("Haringey",                30,   280_000),
        # Outer London
        ("Merton",                  30,   210_000),
        ("Kingston upon Thames",    30,   170_000),
        ("Barnet",                  30,   400_000),
        ("Waltham Forest",          28,   280_000),
        ("Newham",                  27,   350_000),
        ("Redbridge",               26,   300_000),
        ("Brent",                   26,   330_000),
        ("Ealing",                  26,   340_000),
        ("Hounslow",                24,   280_000),
        ("Lewisham",                26,   300_000),
        ("Greenwich",               25,   290_000),
        ("Bromley",                 24,   330_000),
        ("Hillingdon",              22,   300_000),
        ("Enfield",                 22,   330_000),
        ("Sutton",                  22,   210_000),
        ("Croydon",                 22,   380_000),
        ("Havering",                20,   240_000),
        ("Barking & Dagenham",      18,   210_000),
        # Fuera de Londres
        ("Oxford",                  35,   160_000),
        ("Cambridge",               34,   125_000),
        ("Bristol",                 26,   460_000),
        ("Edinburgh",               26,   520_000),
        ("Surrey",                  28, 1_200_000),
        ("Hertfordshire",           24, 1_200_000),
        ("Essex",                   20, 1_800_000),
        ("Manchester",              22,   550_000),
        ("Salford",                 16,   260_000),
        ("Birmingham",              18, 1_100_000),
        ("Solihull",                20,   215_000),
        ("Leeds",                   16,   790_000),
        ("Sheffield",               14,   580_000),
        ("Liverpool",               14,   490_000),
        ("Newcastle",               14,   300_000),
        ("Glasgow",                 16,   630_000),
        ("Cardiff",                 15,   360_000),
        ("Belfast",                 13,   340_000),
        ("Nottingham",              14,   330_000),
        ("Leicester",               14,   350_000),
        ("Coventry",                14,   370_000),
        ("Southampton",             16,   250_000),
        ("Portsmouth",              16,   205_000),
        ("Bradford",                11,   540_000),
    ],

    # ═══ ESPAÑA — distritos Madrid/Barcelona + municipios ══════
    'ES': [
        # Madrid — distritos
        ("Salamanca Madrid",        30, 148_000),
        ("Chamartín Madrid",        28, 148_000),
        ("Retiro Madrid",           26, 120_000),
        ("Chamberí Madrid",         26, 148_000),
        ("Moncloa-Aravaca Madrid",  24, 120_000),
        ("Hortaleza Madrid",        20, 188_000),
        ("Pozuelo de Alarcón",      22, 850_000),
        ("Las Rozas",               19, 100_000),
        ("Majadahonda",             18,  72_000),
        ("Alcobendas",              17, 120_000),
        ("Boadilla del Monte",      18,  55_000),
        ("Ciudad Lineal Madrid",    18, 236_000),
        ("Latina Madrid",           14, 278_000),
        ("Carabanchel Madrid",      14, 280_000),
        ("Vallecas Madrid",         13, 310_000),
        ("Móstoles",                12, 210_000),
        ("Leganés",                 12, 190_000),
        ("Alcorcón",                12, 172_000),
        ("Getafe",                  12, 180_000),
        ("Fuenlabrada",             11, 200_000),
        # Barcelona — distritos
        ("Sarrià-Sant Gervasi",     30, 148_000),
        ("Les Corts Barcelona",     28, 120_000),
        ("Eixample Barcelona",      27, 270_000),
        ("Gràcia Barcelona",        24, 122_000),
        ("Pedralbes",               28,  30_000),
        ("Sant Martí Barcelona",    22, 234_000),
        ("Sants-Montjuïc",          20, 185_000),
        ("Horta-Guinardó",          18, 170_000),
        ("Sant Andreu Barcelona",   17, 148_000),
        ("Nou Barris Barcelona",    15, 168_000),
        ("Ciutat Vella Barcelona",  22,  97_000),
        # Otras ciudades
        ("Sant Cugat del Vallès",   22,  92_000),
        ("Sitges",                  22,  30_000),
        ("Palma",                   22, 410_000),
        ("Málaga",                  18, 570_000),
        ("Marbella",                22, 145_000),
        ("Bilbao",                  16, 350_000),
        ("Donostia-San Sebastián",  20, 188_000),
        ("Valencia",                16, 800_000),
        ("Sevilla",                 14, 690_000),
        ("Alicante",                14, 330_000),
        ("Las Palmas",              14, 380_000),
        ("Vitoria-Gasteiz",         12, 250_000),
        ("Zaragoza",                11, 670_000),
        ("Vigo",                    11, 300_000),
        ("Granada",                 13, 230_000),
        ("Valladolid",               9, 300_000),
        ("Murcia",                   9, 450_000),
        ("Córdoba ES",              10, 325_000),
    ],

    # ═══ ALEMANIA — Stadtteile y Kreise ════════════════════════
    'DE': [
        # Munich
        ("Schwabing-Freimann",      38, 180_000),
        ("Bogenhausen München",     36, 110_000),
        ("Maxvorstadt München",     34,  60_000),
        ("Altstadt München",        34,  30_000),
        ("Neuhausen München",       32, 120_000),
        ("Schwabing München",       32, 110_000),
        ("Landkreis München",       28, 360_000),
        # Frankfurt y alrededores
        ("Frankfurt Westend",       30,  60_000),
        ("Frankfurt Sachsenhausen", 26,  70_000),
        ("Frankfurt",               25, 750_000),
        ("Hochtaunuskreis",         24, 240_000),
        ("Main-Taunus-Kreis",       22, 240_000),
        # Hamburgo
        ("Hamburg Blankenese",      28,  45_000),
        ("Hamburg Eimsbüttel",      26, 260_000),
        ("Hamburgo",                24, 1_850_000),
        ("Hamburg Harburg",         18, 160_000),
        # Berlín
        ("Berlin Mitte",            26, 380_000),
        ("Berlin Prenzlauer Berg",  26, 160_000),
        ("Berlin Charlottenburg",   25, 340_000),
        ("Berlín",                  22, 3_700_000),
        ("Berlin Neukölln",         20, 330_000),
        ("Berlin Marzahn",          16, 260_000),
        # Stuttgart y región
        ("Stuttgart",               22, 630_000),
        ("Böblingen",               20, 390_000),
        # Otras ciudades
        ("Düsseldorf",              20, 620_000),
        ("Colonia",                 20, 1_080_000),
        ("Bonn",                    18, 330_000),
        ("Karlsruhe",               18, 310_000),
        ("Núremberg",               17, 520_000),
        ("Hanóver",                 16, 540_000),
        ("Bremen",                  15, 570_000),
        ("Dortmund",                15, 590_000),
        ("Bochum",                  14, 365_000),
        ("Essen",                   14, 580_000),
        ("Leipzig",                 14, 600_000),
        ("Dresde",                  14, 560_000),
        ("Bielefeld",               13, 340_000),
        ("Duisburgo",               13, 500_000),
        ("Wuppertal",               13, 350_000),
        ("Augsburgo",               18, 300_000),
        ("Mannheim",                16, 310_000),
        ("Freiburg",                22, 230_000),
        ("Heidelberg",              22, 160_000),
    ],

    # ═══ FRANCIA — zones Paris + villes ════════════════════════
    'FR': [
        # París — zonas agrupadas (arrondissements)
        ("París 6°-7° Rive Gauche",  48,  55_000),
        ("París 1°-4° Centre",       45,  80_000),
        ("París 8°-16°-17° Ouest",   44, 260_000),
        ("París 5°-13° Latin",       38, 200_000),
        ("París 9°-10°-11° Nord",    35, 270_000),
        ("París 12°-14°-15° Sud",    34, 430_000),
        ("París 18°-19°-20° Est",    28, 450_000),
        # Île-de-France premium
        ("Neuilly-sur-Seine",        40,  61_000),
        ("Saint-Cloud",              32,  30_000),
        ("Boulogne-Billancourt",     36, 120_000),
        ("Levallois-Perret",         35,  64_000),
        ("Versailles",               28, 140_000),
        ("Hauts-de-Seine Nord",      28, 600_000),
        ("Seine-Saint-Denis",        18, 1_600_000),
        ("Val-de-Marne",             22,  1_380_000),
        ("Essonne",                  18, 1_300_000),
        ("Seine-et-Marne",           16, 1_430_000),
        # Otras ciudades
        ("Niza",                     24, 340_000),
        ("Antibes-Juan-les-Pins",    22,  77_000),
        ("Lyon 2°-6°",               22,  90_000),
        ("Lyon",                     20, 500_000),
        ("Villeurbanne",             19, 150_000),
        ("Bordeaux",                 18, 250_000),
        ("Strasbourg",               16, 280_000),
        ("Nantes",                   17, 300_000),
        ("Montpellier",              16, 280_000),
        ("Toulouse",                 16, 470_000),
        ("Rennes",                   16, 215_000),
        ("Marsella",                 16, 870_000),
        ("Grenoble",                 15, 160_000),
        ("Lille",                    15, 230_000),
        ("Dijon",                    13, 155_000),
        ("Angers",                   14, 150_000),
        ("Toulon",                   14, 175_000),
        ("Reims",                    12, 180_000),
        ("Le Havre",                 12, 170_000),
        ("Saint-Étienne",            10, 170_000),
    ],

    # ═══ ITALIA — quartieri + comuni ═══════════════════════════
    'IT': [
        # Milano — quartieri
        ("Brera-Duomo Milano",       35, 100_000),
        ("Porta Venezia Milano",     30,  90_000),
        ("Navigli Milano",           28,  70_000),
        ("CityLife-Portello",        28,  60_000),
        ("Milán",                    22, 1_400_000),
        ("Monza",                    18, 120_000),
        ("Bergamo",                  16, 120_000),
        ("Brescia",                  15, 200_000),
        # Roma — quartieri
        ("Parioli Roma",             28,  55_000),
        ("Prati Roma",               26,  70_000),
        ("Trastevere Roma",          24,  14_000),
        ("Roma",                     22, 2_800_000),
        ("EUR Roma",                 20,  80_000),
        ("Ostia",                    16,  90_000),
        # Otras ciudades
        ("Venecia",                  22, 260_000),
        ("Florencia",                20, 370_000),
        ("Bolonia",                  18, 400_000),
        ("Turín",                    16, 870_000),
        ("Génova",                   14, 580_000),
        ("Verona",                   14, 260_000),
        ("Padua",                    14, 210_000),
        ("Módena",                   13, 180_000),
        ("Trieste",                  12, 200_000),
        ("Nápoles",                  12, 3_100_000),
        ("Palermo",                  10, 680_000),
        ("Bari",                     10, 310_000),
        ("Catania",                   9, 310_000),
        ("Taranto",                   8, 200_000),
        ("Reggio Calabria",           8, 180_000),
        ("Mesina",                    8, 230_000),
    ],

    # ═══ AUSTRALIA — LGAs ═════════════════════════════════════
    'AU': [
        # Sydney
        ("Woollahra",               48,  56_000),
        ("Mosman",                  46,  30_000),
        ("North Sydney",            44, 220_000),
        ("Lane Cove",               40,  38_000),
        ("Waverley",                42,  75_000),
        ("Ku-ring-gai",             38, 125_000),
        ("Willoughby",              38, 180_000),
        ("Eastern Suburbs Sydney",  42, 170_000),
        ("Lower North Shore",       40, 180_000),
        ("Inner West Sydney",       36, 250_000),
        ("Sídney",                  35, 5_300_000),
        ("Northern Beaches",        35, 270_000),
        ("Parramatta",              26, 250_000),
        ("Blacktown",               20, 370_000),
        ("Penrith",                 18, 220_000),
        ("Liverpool NSW",           16, 250_000),
        # Melbourne
        ("Stonnington",             36, 112_000),
        ("Boroondara",              35, 176_000),
        ("Port Phillip",            34, 115_000),
        ("Bayside VIC",             32,  98_000),
        ("Melbourne",               28, 5_000_000),
        ("Whitehorse",              26, 180_000),
        ("Monash",                  24, 200_000),
        ("Greater Dandenong",       16, 170_000),
        # Brisbane y otros
        ("Brisbane",                22, 2_500_000),
        ("Gold Coast",              22,   700_000),
        ("Sunshine Coast",          20,   350_000),
        ("Canberra",                22,   450_000),
        ("Perth",                   20, 2_100_000),
        ("Adelaida",                18, 1_300_000),
        ("Hobart",                  20,   230_000),
        ("Geelong",                 18,   170_000),
        ("Townsville",              14,   180_000),
        ("Cairns",                  14,   150_000),
        ("Darwin",                  18,   140_000),
        ("Newcastle NSW",           18,   170_000),
        ("Wollongong",              20,   320_000),
    ],

    # ═══ CANADÁ — counties/regions ════════════════════════════
    'CA': [
        # Toronto Metro
        ("York Region ON",          36, 1_200_000),
        ("Peel Region ON",          28, 1_500_000),
        ("Toronto",                 32, 2_900_000),
        ("Halton Region ON",        26,   600_000),
        ("Durham Region ON",        22,   700_000),
        # Vancouver Metro
        ("West Vancouver",          45,   48_000),
        ("North Vancouver",         38,  90_000),
        ("Vancouver",               35, 2_600_000),
        ("Burnaby",                 30, 250_000),
        ("Richmond BC",             28, 220_000),
        ("Surrey BC",               24, 570_000),
        ("Langley BC",              22, 150_000),
        ("Coquitlam",               26, 155_000),
        # Victoria
        ("Saanich",                 30, 120_000),
        ("Victoria BC",             28, 400_000),
        # Ottawa
        ("Ottawa",                  22, 1_000_000),
        # Calgary
        ("Calgary",                 20, 1_300_000),
        # Montreal
        ("Côte-des-Neiges",        22,  97_000),
        ("Plateau Mont-Royal",      22,  73_000),
        ("Montreal",                20, 2_000_000),
        ("Laval",                   18, 430_000),
        ("Longueuil",               16, 250_000),
        # Edmonton
        ("Edmonton",                16, 1_000_000),
        # Otras
        ("Winnipeg",                14,   780_000),
        ("Quebec City",             16,   540_000),
        ("Hamilton ON",             18,   580_000),
        ("Kitchener-Waterloo",      18,   240_000),
        ("London ON",               16,   380_000),
        ("Halifax",                 16,   440_000),
        ("Saskatoon",               13,   260_000),
        ("Regina",                  13,   220_000),
    ],

    # ═══ BRASIL — municípios ═══════════════════════════════════
    'BR': [
        # São Paulo Metro
        ("Jardins-Itaim SP",        28,  80_000),
        ("Pinheiros SP",            24, 130_000),
        ("Vila Olímpia SP",         26,  50_000),
        ("Lapa SP",                 20, 280_000),
        ("São Paulo",               20, 12_000_000),
        ("Campinas",                14, 1_200_000),
        ("Guarulhos",               14, 1_400_000),
        ("Santo André",             14,   720_000),
        ("São Bernardo do Campo",   14,   840_000),
        ("Osasco",                  14,   700_000),
        ("São José dos Campos",     14,   720_000),
        ("Ribeirão Preto",          12,   700_000),
        ("Sorocaba",                11,   700_000),
        ("Jundiaí",                 14,   430_000),
        # Rio de Janeiro Metro
        ("Leblon-Ipanema RJ",       28,  80_000),
        ("Barra da Tijuca RJ",      22, 160_000),
        ("Flamengo-Botafogo RJ",    20, 130_000),
        ("Rio de Janeiro",          18, 6_700_000),
        ("Niterói",                 16,   510_000),
        # Brasília
        ("Lago Sul DF",             22,  50_000),
        ("Brasília",                16, 3_000_000),
        # Otras capitales
        ("Belo Horizonte",          13, 2_500_000),
        ("Porto Alegre",            13, 1_400_000),
        ("Curitiba",                13, 1_900_000),
        ("Goiânia",                 12, 1_500_000),
        ("Recife",                  11, 1_650_000),
        ("Fortaleza",               10, 2_600_000),
        ("Salvador",                11, 2_900_000),
        ("Manaus",                  10, 2_200_000),
        ("Belém",                    9, 1_500_000),
        ("Natal",                   10,   880_000),
        ("João Pessoa",             10,   820_000),
        ("Maceió",                  10,   960_000),
        ("Florianópolis",           15,   500_000),
        ("Campo Grande",            10,   900_000),
        ("Teresina",                 7,   870_000),
        ("São Luís",                 9, 1_100_000),
        ("Uberlândia",              10,   700_000),
        ("Contagem",                11,   650_000),
    ],

    # ═══ ARGENTINA — partidos GBA + ciudades ══════════════════
    'AR': [
        # Buenos Aires Ciudad — barrios
        ("Palermo Buenos Aires",    18, 230_000),
        ("Belgrano Buenos Aires",   16, 160_000),
        ("Recoleta Buenos Aires",   17, 190_000),
        ("Núñez Buenos Aires",      15, 100_000),
        ("San Telmo-Puerto Madero", 18,  30_000),
        ("Caballito Buenos Aires",  14, 220_000),
        ("Villa Crespo BA",         14, 100_000),
        ("Flores Buenos Aires",     12, 200_000),
        ("Mataderos Buenos Aires",   9, 110_000),
        ("Villa Lugano BA",          7, 120_000),
        # GBA Norte
        ("San Isidro",              15, 290_000),
        ("Vicente López",           14, 290_000),
        ("Tigre",                   10, 370_000),
        ("San Fernando BA",          9, 160_000),
        ("Pilar",                   10, 300_000),
        # GBA Oeste/Sur
        ("La Matanza",               8, 1_750_000),
        ("Morón",                    9,   330_000),
        ("Ituzaingó",                9,   170_000),
        ("Tres de Febrero",          9,   340_000),
        ("Lanús",                    9,   460_000),
        ("Lomas de Zamora",          9,   630_000),
        ("Quilmes",                  8,   580_000),
        ("Avellaneda BA",            9,   340_000),
        ("General San Martín BA",    9,   430_000),
        ("Almirante Brown",          7,   570_000),
        ("Esteban Echeverría",       7,   350_000),
        # Interior
        ("Córdoba Capital",          8, 1_391_000),
        ("Neuquén",                  7,   340_000),
        ("Mendoza",                  8,   125_000),
        ("Rosario",                  7,   948_000),
        ("Mar del Plata",            7,   650_000),
        ("Comodoro Rivadavia",       7,   185_000),
        ("Bahía Blanca",             6,   310_000),
        ("Santa Fe Capital",         6,   525_000),
        ("Salta Capital",            6,   618_000),
        ("La Plata",                 6,   860_000),
        ("Corrientes Capital",       5,   390_000),
        ("Posadas",                  5,   325_000),
        ("Tucumán",                  5,   550_000),
        ("Río Cuarto",               6,   183_000),
        ("San Juan",                 5,   120_000),
        ("Resistencia",              4,   390_000),
        ("Formosa Capital",          3,   280_000),
    ],

    # ═══ MÉXICO — alcaldías CDMX + municipios ═════════════════
    'MX': [
        # CDMX — alcaldías
        ("Miguel Hidalgo CDMX",     22, 370_000),
        ("Benito Juárez CDMX",      20, 430_000),
        ("Cuauhtémoc CDMX",         18, 530_000),
        ("Álvaro Obregón CDMX",     16, 740_000),
        ("Coyoacán CDMX",           16, 620_000),
        ("Azcapotzalco CDMX",       14, 400_000),
        ("Tlalpan CDMX",            14, 680_000),
        ("Iztacalco CDMX",          13, 390_000),
        ("Gustavo A. Madero CDMX",  12, 1_200_000),
        ("Iztapalapa CDMX",         10, 1_815_000),
        ("Xochimilco CDMX",          9, 450_000),
        # Estado de México
        ("Naucalpan",               14, 870_000),
        ("Huixquilucan",            15, 280_000),
        ("Atizapán de Zaragoza",    12, 520_000),
        ("Tlalnepantla",            12, 700_000),
        ("Ecatepec",                 9, 1_700_000),
        ("Nezahualcóyotl",           9, 1_100_000),
        # Monterrey Metro
        ("San Pedro Garza García",  18, 130_000),
        ("Monterrey",               12, 1_100_000),
        ("Guadalupe NL",            10, 700_000),
        ("San Nicolás NL",          10, 450_000),
        ("Apodaca NL",              10, 600_000),
        # Guadalajara Metro
        ("Zapopan",                 11, 1_400_000),
        ("Guadalajara",             10, 1_500_000),
        ("Tlaquepaque",              9, 700_000),
        # Otras ciudades
        ("Tijuana",                 10, 1_800_000),
        ("Cancún",                  11,   930_000),
        ("Querétaro",               10,   800_000),
        ("Mérida",                   9,   960_000),
        ("Hermosillo",               8,   850_000),
        ("Chihuahua City",           8,   880_000),
        ("Ciudad Juárez",            8, 1_500_000),
        ("Morelia",                  8,   760_000),
        ("Toluca",                   8,   870_000),
        ("Puebla",                   8, 1_500_000),
        ("Aguascalientes",           8,   800_000),
        ("San Luis Potosí",          7,   840_000),
        ("Saltillo",                 7,   860_000),
        ("Torreón",                  7,   670_000),
        ("Culiacán",                 7,   900_000),
        ("Oaxaca",                   7,   290_000),
        ("Mexicali",                 7,   950_000),
        ("León",                     7, 1_600_000),
        ("Acapulco",                 5,   700_000),
        ("Veracruz",                 6,   520_000),
    ],

    # ═══ COLOMBIA — localidades Bogotá + municipios ════════════
    'CO': [
        # Bogotá — localidades
        ("Chapinero Bogotá",        14,  130_000),
        ("Usaquén Bogotá",          13,  500_000),
        ("Teusaquillo Bogotá",      12,  150_000),
        ("Barrios Unidos Bogotá",   10,  180_000),
        ("Kennedy Bogotá",           9,  1_160_000),
        ("Engativá Bogotá",          9,   870_000),
        ("Suba Bogotá",             10,  1_200_000),
        ("Fontibón Bogotá",          9,   380_000),
        ("Rafael Uribe Bogotá",      8,   370_000),
        ("Bosa Bogotá",              7,   800_000),
        ("Ciudad Bolívar Bogotá",    6,   800_000),
        # Medellín — comunas
        ("El Poblado Medellín",     12,  130_000),
        ("Laureles-Estadio",        10,  200_000),
        ("Envigado",                10,  250_000),
        ("Sabaneta",                10,  100_000),
        ("Medellín",                 8, 2_570_000),
        ("Bello",                    7,   520_000),
        ("Itagüí",                   8,   280_000),
        # Otras ciudades
        ("Cartagena",               10, 1_000_000),
        ("Santa Marta",              8,   530_000),
        ("Barranquilla",             8, 1_200_000),
        ("Soledad",                  7,   660_000),
        ("Cali",                     8, 2_200_000),
        ("Bucaramanga",              7,   590_000),
        ("Pereira",                  7,   480_000),
        ("Manizales",                7,   430_000),
        ("Villavicencio",            6,   530_000),
        ("Ibagué",                   6,   560_000),
        ("Armenia",                  6,   310_000),
        ("Neiva",                    6,   350_000),
        ("Cúcuta",                   5,   710_000),
        ("Montería",                 5,   450_000),
        ("Pasto",                    5,   360_000),
    ],

    # ═══ PERÚ — distritos Lima + ciudades ══════════════════════
    'PE': [
        # Lima — distritos
        ("Miraflores Lima",         14,  82_000),
        ("San Isidro Lima",         14,  55_000),
        ("Barranco Lima",           12,  30_000),
        ("La Molina Lima",          11,  170_000),
        ("Surco Lima",              10,  350_000),
        ("San Borja Lima",          10,  113_000),
        ("Jesús María Lima",         9,   72_000),
        ("Magdalena Lima",           9,   56_000),
        ("Pueblo Libre Lima",        9,   78_000),
        ("San Miguel Lima",          8,  137_000),
        ("Lince Lima",               9,   52_000),
        ("Breña Lima",               8,   78_000),
        ("Surquillo Lima",           8,   91_000),
        ("Lima Cercado",             7,   280_000),
        ("La Victoria Lima",         7,   175_000),
        ("Los Olivos Lima",          7,   400_000),
        ("Carabayllo Lima",          5,   310_000),
        ("Villa El Salvador Lima",   5,   470_000),
        ("San Juan de Lurigancho",   5,   1_100_000),
        ("Villa María del Triunfo",  4,   470_000),
        # Otras ciudades
        ("Cusco",                    7,   430_000),
        ("Arequipa",                 6, 1_008_000),
        ("Miraflores Arequipa",      8,   30_000),
        ("Trujillo",                 5,   900_000),
        ("Chiclayo",                 5,   600_000),
        ("Piura",                    4,   860_000),
        ("Ica",                      5,   390_000),
        ("Tacna",                    5,   320_000),
        ("Iquitos",                  4,   500_000),
        ("Huancayo",                 4,   390_000),
        ("Cajamarca",                4,   230_000),
        ("Pucallpa",                 3,   400_000),
        ("Juliaca",                  3,   260_000),
        ("Puno",                     3,   150_000),
    ],

    # ═══ INDIA — distritos / zonas ════════════════════════════
    'IN': [
        # Mumbai
        ("South Mumbai",            14, 500_000),
        ("Bandra-Khar Mumbai",      12, 300_000),
        ("Juhu-Versova Mumbai",     11, 200_000),
        ("Powai Mumbai",             9, 350_000),
        ("Andheri West Mumbai",      9, 600_000),
        ("Andheri East Mumbai",      7, 700_000),
        ("Thane",                    8, 1_900_000),
        ("Navi Mumbai",              8, 1_100_000),
        ("Panvel",                   6, 400_000),
        ("Mira-Bhayander",           6, 800_000),
        # Delhi NCR
        ("South Delhi",             10, 600_000),
        ("Lutyens Delhi",           12, 100_000),
        ("Dwarka Delhi",             8, 700_000),
        ("Noida",                    8, 1_600_000),
        ("Gurugram",                10, 1_000_000),
        ("Faridabad",                6, 1_400_000),
        ("Ghaziabad",                6, 2_400_000),
        # Bangalore
        ("Koramangala Bangalore",    9, 120_000),
        ("Indiranagar Bangalore",    9, 100_000),
        ("Whitefield Bangalore",     8, 300_000),
        ("Bangalore",                9, 8_400_000),
        ("Électronique City",        6, 400_000),
        # Hyderabad
        ("Banjara Hills Hyd",        9, 100_000),
        ("Gachibowli Hyd",           8, 250_000),
        ("Hyderabad",                7, 6_800_000),
        ("Secunderabad",             7, 1_200_000),
        # Chennai
        ("Anna Nagar Chennai",       8, 300_000),
        ("Adyar Chennai",            8, 200_000),
        ("Chennai",                  7, 7_100_000),
        # Otras
        ("Kolkata",                  6, 4_500_000),
        ("Pune Koregaon Park",      10, 100_000),
        ("Pune",                     8, 3_100_000),
        ("Surat",                    5, 6_000_000),
        ("Ahmedabad",                5, 5_600_000),
        ("Jaipur",                   5, 3_000_000),
        ("Lucknow",                  5, 3_400_000),
        ("Kochi",                    7,   700_000),
        ("Bhopal",                   4, 1_800_000),
        ("Nagpur",                   5, 2_400_000),
        ("Kanpur",                   4, 3_000_000),
    ],

    # ═══ SUDÁFRICA ════════════════════════════════════════════
    'ZA': [
        # Cape Town
        ("Atlantic Seaboard CPT",   18,  50_000),
        ("City Bowl Cape Town",     16, 100_000),
        ("Southern Suburbs CPT",    14, 200_000),
        ("Northern Suburbs CPT",    12, 500_000),
        ("Cape Town",               12, 4_600_000),
        ("Stellenbosch",            12, 185_000),
        # Johannesburg
        ("Sandton-Rosebank",        14, 300_000),
        ("Johannesburgo",           12, 5_600_000),
        ("Midrand",                 10, 400_000),
        ("Soweto",                   6, 1_300_000),
        # Otras
        ("Pretoria East",           10, 500_000),
        ("Pretoria",                 9, 2_900_000),
        ("Durban North",            10, 200_000),
        ("Durban",                   9, 3_700_000),
        ("Umhlanga",                12,  60_000),
        ("Port Elizabeth",           6, 1_200_000),
        ("Nelspruit",                6,   280_000),
        ("Bloemfontein",             5,   750_000),
        ("East London ZA",           5,   270_000),
        ("Polokwane",                5,   160_000),
    ],

    # ═══ VENEZUELA ════════════════════════════════════════════
    'VE': [
        ("Chacao Caracas",          12,  80_000),
        ("Baruta Caracas",          11, 300_000),
        ("El Hatillo Caracas",      10, 100_000),
        ("Caracas",                 10, 3_000_000),
        ("Sucre Caracas",            7, 700_000),
        ("Libertador Caracas",       6, 2_000_000),
        ("Valencia VE",              6, 1_400_000),
        ("Maracay",                  6,   900_000),
        ("Maracaibo",                5, 2_500_000),
        ("Barquisimeto",             5, 1_100_000),
        ("Ciudad Guayana",           5,   800_000),
        ("Barcelona VE",             5,   420_000),
        ("San Cristóbal VE",         4,   650_000),
        ("Maturín",                  4,   600_000),
        ("Cumaná",                   4,   350_000),
    ],

    # ═══ URUGUAY ══════════════════════════════════════════════
    'UY': [
        ("Carrasco Montevideo",     16,  30_000),
        ("Pocitos Montevideo",      14,  60_000),
        ("Punta Carretas Montevideo",13, 40_000),
        ("Palermo Montevideo",      11,  50_000),
        ("Centro Montevideo",       10, 130_000),
        ("Montevideo",              12, 1_380_000),
        ("Maldonado-Punta del Este",12, 170_000),
        ("Colonia del Sacramento",   9,  26_000),
        ("Las Piedras",              7,  170_000),
        ("Canelones",                7,  550_000),
        ("Salto",                    5,  105_000),
        ("Paysandú",                 5,   80_000),
        ("Rivera",                   4,   70_000),
        ("Tacuarembó",               4,   60_000),
        ("Artigas",                  3,   45_000),
    ],

    # ═══ ECUADOR ══════════════════════════════════════════════
    'EC': [
        ("González Suárez Quito",   11,  20_000),
        ("La Carolina Quito",       10,  60_000),
        ("Quito Norte",             10, 400_000),
        ("Quito",                    9, 1_900_000),
        ("Quito Sur",                7, 600_000),
        ("Los Ceibos Guayaquil",    10,  60_000),
        ("Urdesa Guayaquil",         9,  80_000),
        ("Guayaquil",                8, 2_700_000),
        ("Samborondón",             10, 100_000),
        ("Durán",                    5, 300_000),
        ("Cuenca",                   7, 600_000),
        ("Manta",                    6, 250_000),
        ("Ambato",                   5, 330_000),
        ("Machala",                  5, 240_000),
        ("Santo Domingo EC",         5, 450_000),
        ("Loja",                     5, 190_000),
        ("Portoviejo",               4, 290_000),
    ],

    # ═══ BOLIVIA ══════════════════════════════════════════════
    'BO': [
        ("Zona Sur Santa Cruz",     10,  80_000),
        ("Santa Cruz de la Sierra", 8, 1_600_000),
        ("La Paz Zona Sur",          9,  80_000),
        ("La Paz",                   7,   900_000),
        ("El Alto",                  4,   900_000),
        ("Cochabamba",               6,   630_000),
        ("Quillacollo",              5,   140_000),
        ("Sucre",                    5,   290_000),
        ("Tarija",                   5,   210_000),
        ("Oruro",                    4,   260_000),
        ("Potosí",                   3,   230_000),
        ("Cobija",                   4,    55_000),
        ("Trinidad BO",              3,   120_000),
        ("Riberalta",                3,    90_000),
    ],

    # ═══ PARAGUAY ═════════════════════════════════════════════
    'PY': [
        ("Barrio Las Mercedes PY",  10,  20_000),
        ("Manorá Asunción",          9,  15_000),
        ("Asunción",                 8,  530_000),
        ("Ciudad del Este",          6,  300_000),
        ("Luque",                    5,  280_000),
        ("San Lorenzo PY",           5,  270_000),
        ("Fernando de la Mora",      5,  130_000),
        ("Lambaré",                  5,  130_000),
        ("Encarnación",              5,  120_000),
        ("Capiatá",                  4,  220_000),
        ("Ñemby",                    4,  110_000),
        ("Limpio",                   4,  110_000),
        ("Mariano Roque Alonso",     5,  100_000),
        ("Hernandarias",             5,   60_000),
    ],

    # ═══ NIGERIA ══════════════════════════════════════════════
    'NG': [
        ("Ikoyi Lagos",             18,  60_000),
        ("Victoria Island Lagos",   16, 100_000),
        ("Lekki Lagos",             14, 300_000),
        ("Ikeja Lagos",             10, 320_000),
        ("Lagos",                   12, 14_800_000),
        ("Surulere Lagos",           8, 500_000),
        ("Mushin Lagos",             5, 800_000),
        ("Maitama Abuja",           14, 100_000),
        ("Wuse Abuja",              12, 150_000),
        ("Abuja",                   10, 3_000_000),
        ("Garki Abuja",              9, 100_000),
        ("Port Harcourt",            7, 1_900_000),
        ("GRA Port Harcourt",       10,  60_000),
        ("Ibadan",                   4, 3_600_000),
        ("Kano",                     4, 3_900_000),
        ("Aba NG",                   4,   680_000),
        ("Benin City NG",            4,   800_000),
        ("Jos",                      4,   900_000),
        ("Kaduna",                   4, 1_600_000),
        ("Zaria",                    3,   820_000),
        ("Maiduguri",                3, 1_200_000),
        ("Enugu",                    5,   900_000),
        ("Owerri",                   5,   500_000),
    ],
}


# ── FUNCIONES ─────────────────────────────────────────────────

def uf_to_index(uf_m2: float) -> float:
    return round((uf_m2 / REFERENCIA_UF_M2) * 100, 1)

def usd_to_index(usd_m2: float, reference_usd: float) -> float:
    return round((usd_m2 / reference_usd) * 100, 1)

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
        "D": "Popular — Trabajadores generales",
    }.get(tier, "")

def calculate_cpm(income_index: float, cpm_base: float = 8.0) -> float:
    import math
    cpm = cpm_base * (income_index / 100.0) ** 0.65
    return round(max(1.5, min(cpm_base * 1.5, cpm)), 2)

def calculate_commune_table(country: str = 'CL') -> list:
    if country == 'CL':
        cpm_base = CPM_BASE_BY_COUNTRY.get('CL', 8.0)
        communes = []
        for nombre, region, uf_m2, poblacion in COMUNAS_DATA:
            index = uf_to_index(uf_m2)
            tier  = get_se_tier(index)
            communes.append({
                "nombre":       nombre, "region": region,
                "uf_m2":        uf_m2,  "income_index": index,
                "se_tier":      tier,   "se_descripcion": get_se_description(tier),
                "cpm_usd":      calculate_cpm(index, cpm_base),
                "poblacion":    poblacion,
                "votantes_est": int(poblacion * 0.75 * 0.35),
                "country":      "CL",
            })
        communes.sort(key=lambda x: x["income_index"], reverse=True)
        return communes

    data = GLOBAL_RENT_DATA.get(country, [])
    if not data:
        return []
    reference_usd = max(row[1] for row in data)
    cpm_base = CPM_BASE_BY_COUNTRY.get(country, 5.0)
    communes = []
    for nombre, usd_m2, poblacion in data:
        index = usd_to_index(usd_m2, reference_usd)
        tier  = get_se_tier(index)
        communes.append({
            "nombre":       nombre, "region": country,
            "usd_m2":       usd_m2, "income_index": index,
            "se_tier":      tier,   "se_descripcion": get_se_description(tier),
            "cpm_usd":      calculate_cpm(index, cpm_base),
            "poblacion":    poblacion,
            "votantes_est": int(poblacion * 0.75 * 0.35),
            "country":      country,
        })
    communes.sort(key=lambda x: x["income_index"], reverse=True)
    return communes

def calculate_all_communes_table() -> list:
    result = calculate_commune_table('CL')
    for cc in GLOBAL_RENT_DATA:
        result.extend(calculate_commune_table(cc))
    return result

def allocate_budget(budget_usd, target_se=None, target_region=None,
                    max_communes=None, country='CL'):
    communes = calculate_commune_table(country)
    if target_se:     communes = [c for c in communes if c["se_tier"] in target_se]
    if target_region: communes = [c for c in communes if c["region"] == target_region]
    if max_communes:  communes = communes[:max_communes]
    if not communes:  return {"error": "No communes match"}
    total_w = sum(c["votantes_est"] for c in communes)
    alloc, tv, ti = [], 0, 0
    for c in communes:
        w = c["votantes_est"] / total_w
        bu = budget_usd * w
        imp = int((bu / c["cpm_usd"]) * 1000)
        va  = min(imp, c["votantes_est"])
        alloc.append({"ciudad": c["nombre"], "country": c["country"],
                      "se_tier": c["se_tier"], "income_index": c["income_index"],
                      "cpm_usd": c["cpm_usd"], "presupuesto_usd": round(bu, 2),
                      "impresiones_est": imp, "votantes_alcanzados": va})
        tv += va; ti += imp
    return {"budget_total_usd": budget_usd, "total_communes": len(alloc),
            "total_votantes_est": tv, "total_impresiones_est": ti,
            "cpm_promedio": round(budget_usd/(ti/1000), 2) if ti else 0,
            "allocation": alloc, "generated_at": datetime.utcnow().isoformat()}


if __name__ == "__main__":
    for cc in ['CL'] + list(GLOBAL_RENT_DATA.keys()):
        t = calculate_commune_table(cc)
        tiers = {}
        for c in t: tiers[c['se_tier']] = tiers.get(c['se_tier'], 0) + 1
        print(f"{cc}: {len(t):3d} zonas — {dict(sorted(tiers.items()))}")
    total = sum(len(calculate_commune_table(cc)) for cc in ['CL']+list(GLOBAL_RENT_DATA.keys()))
    print(f"\nTotal: {total} zonas en {1+len(GLOBAL_RENT_DATA)} países")
