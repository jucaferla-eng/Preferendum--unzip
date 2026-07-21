"""
commune_agent.py
================
PREFERENDUM — Agente de Clasificación de Comunas/Ciudades por Ingreso

Proxy de ingreso: precio de ARRIENDO mensual por m² (UF para Chile, USD para el resto)
Chile: Vitacura = 0.40 UF/m² = índice 100 (referencia interna CL)
Otros países: ciudad más cara del país = índice 100 (referencia interna por país)

Tiers SE (socioeconómico):
  A  ≥ 80  — Alto ingreso         (zonas premium)
  B  55-79 — Medio-alto           (clase media profesional)
  C  35-54 — Medio                (trabajadores calificados)
  D  < 35  — Popular              (trabajadores generales)

En memoria del Socio Fundador José Ignacio Fernández (1989–2024)
"""

from datetime import datetime

# ══════════════════════════════════════════════════════════════
# CHILE — precio arriendo UF/m² (referencia: Vitacura = 0.40)
# ══════════════════════════════════════════════════════════════
REFERENCIA_UF_M2   = 0.40
REFERENCIA_COMMUNE = 'Vitacura'

COMUNAS_DATA = [
    # (nombre, región, uf_m2, población)
    ("Vitacura",           "RM",   0.40, 92000),
    ("Las Condes",         "RM",   0.39, 310000),
    ("Lo Barnechea",       "RM",   0.38, 105000),
    ("Providencia",        "RM",   0.38, 150000),
    ("La Reina",           "RM",   0.32, 98000),
    ("Ñuñoa",              "RM",   0.28, 225000),
    ("Peñalolén",          "RM",   0.24, 240000),
    ("Santiago",           "RM",   0.24, 520000),
    ("Macul",              "RM",   0.23, 130000),
    ("San Miguel",         "RM",   0.23, 110000),
    ("La Florida",         "RM",   0.22, 380000),
    ("Independencia",      "RM",   0.22, 105000),
    ("Huechuraba",         "RM",   0.21, 98000),
    ("Maipú",              "RM",   0.21, 620000),
    ("Recoleta",           "RM",   0.20, 175000),
    ("Quilicura",          "RM",   0.19, 235000),
    ("Estación Central",   "RM",   0.19, 145000),
    ("Quinta Normal",      "RM",   0.18, 115000),
    ("Temuco",             "IX",   0.18, 360000),
    ("Cerrillos",          "RM",   0.17, 90000),
    ("Conchalí",           "RM",   0.17, 140000),
    ("Quilpué",            "V",    0.17, 235000),
    ("Puerto Montt",       "X",    0.17, 275000),
    ("Rancagua",           "VI",   0.17, 245000),
    ("Punta Arenas",       "XII",  0.17, 145000),
    ("Pudahuel",           "RM",   0.16, 245000),
    ("Arica",              "XV",   0.16, 245000),
    ("Renca",              "RM",   0.15, 155000),
    ("Lo Prado",           "RM",   0.14, 110000),
    ("Lo Espejo",          "RM",   0.13, 115000),
    ("Cerro Navia",        "RM",   0.12, 145000),
    ("El Bosque",          "RM",   0.12, 185000),
    ("San Ramón",          "RM",   0.11, 100000),
    ("La Pintana",         "RM",   0.10, 225000),
    ("Concón",             "V",    0.26, 52000),
    ("Viña del Mar",       "V",    0.23, 390000),
    ("Valparaíso",         "V",    0.18, 310000),
    ("San Pedro de la Paz","VIII", 0.21, 135000),
    ("Concepción",         "VIII", 0.19, 245000),
    ("Talcahuano",         "VIII", 0.16, 175000),
    ("Antofagasta",        "II",   0.23, 420000),
    ("Iquique",            "I",    0.20, 245000),
    ("La Serena",          "IV",   0.20, 250000),
    ("Coquimbo",           "IV",   0.17, 245000),
]

# ══════════════════════════════════════════════════════════════
# DATOS GLOBALES — precio arriendo USD/m²/mes por ciudad
# Referencia por país: ciudad más cara = índice 100
# Fuente: Numbeo, Global Property Guide, datos 2024-2025
# (nombre_ciudad, usd_m2, población_estimada)
# ══════════════════════════════════════════════════════════════

# CPM base USD por país (Meta/Google ARPU benchmark 2024)
CPM_BASE_BY_COUNTRY = {
    'CL': 8.0,
    'US': 18.0,
    'GB': 14.0,
    'AU': 12.0,
    'CA': 12.0,
    'DE': 12.0,
    'FR': 10.0,
    'IT':  9.0,
    'ES':  9.0,
    'BR':  7.0,
    'MX':  6.0,
    'CO':  5.0,
    'AR':  5.0,
    'ZA':  4.0,
    'UY':  5.0,
    'EC':  4.0,
    'VE':  3.0,
    'BO':  3.0,
    'PY':  3.0,
    'PE':  4.0,
    'IN':  3.0,
    'NG':  2.0,
}

GLOBAL_RENT_DATA: dict[str, list] = {

    'AR': [
        # (nombre, usd_m2_mes, población)
        ("Buenos Aires",       15.0, 3_075_000),
        ("General San Martín", 10.0,   430_000),
        ("Quilmes",             9.0,   580_000),
        ("Lanús",               9.0,   460_000),
        ("Lomas de Zamora",     9.0,   630_000),
        ("Neuquén",             7.0,   340_000),
        ("Comodoro Rivadavia",  7.0,   185_000),
        ("Mendoza",             8.0,   125_000),
        ("Córdoba",             8.0, 1_391_000),
        ("Mar del Plata",       7.0,   650_000),
        ("Rosario",             7.0,   948_000),
        ("Río Cuarto",          6.0,   183_000),
        ("Bahía Blanca",        6.0,   310_000),
        ("Santa Fe",            6.0,   525_000),
        ("Salta",               6.0,   618_000),
        ("La Plata",            6.0,   860_000),
        ("Corrientes",          5.0,   390_000),
        ("Posadas",             5.0,   325_000),
        ("San Luis",            5.0,   200_000),
        ("Tucumán",             5.0,   550_000),
        ("Paraná",              5.0,   247_000),
        ("San Juan",            5.0,   120_000),
        ("Santiago del Estero", 4.0,   330_000),
        ("Formosa",             3.0,   280_000),
        ("Resistencia",         4.0,   390_000),
    ],

    'PE': [
        ("Lima",          12.0, 10_850_000),
        ("Cusco",          7.0,    430_000),
        ("Arequipa",       6.0,  1_008_000),
        ("Tacna",          5.0,    320_000),
        ("Trujillo",       5.0,    900_000),
        ("Chiclayo",       5.0,    600_000),
        ("Ica",            5.0,    390_000),
        ("Moquegua",       5.0,    170_000),
        ("Piura",          4.0,    860_000),
        ("Iquitos",        4.0,    500_000),
        ("Chimbote",       4.0,    360_000),
        ("Huancayo",       4.0,    390_000),
        ("Ayacucho",       4.0,    100_000),
        ("Cajamarca",      4.0,    230_000),
        ("Sullana",        3.0,    310_000),
        ("Tumbes",         4.0,    110_000),
        ("Juliaca",        3.0,    260_000),
        ("Huánuco",        3.0,    280_000),
        ("Puno",           3.0,    150_000),
        ("Pucallpa",       3.0,    400_000),
    ],

    'MX': [
        ("Ciudad de México", 18.0, 9_200_000),
        ("Monterrey",        12.0, 1_100_000),
        ("Tijuana",          10.0, 1_800_000),
        ("Zapopan",          10.0, 1_400_000),
        ("Guadalajara",      10.0, 1_500_000),
        ("Cancún",           10.0,   930_000),
        ("Querétaro",         9.0,   800_000),
        ("Mérida",            8.0,   960_000),
        ("Hermosillo",        7.0,   850_000),
        ("Chihuahua",         7.0,   880_000),
        ("Ciudad Juárez",     7.0, 1_500_000),
        ("Morelia",           7.0,   760_000),
        ("Toluca",            7.0,   870_000),
        ("Puebla",            7.0, 1_500_000),
        ("Oaxaca",            7.0,   290_000),
        ("Aguascalientes",    7.0,   800_000),
        ("San Luis Potosí",   6.0,   840_000),
        ("Saltillo",          6.0,   860_000),
        ("Torreón",           6.0,   670_000),
        ("Mexicali",          7.0,   950_000),
        ("Culiacán",          6.0,   900_000),
        ("Acapulco",          5.0,   700_000),
        ("Veracruz",          6.0,   520_000),
        ("León",              6.0, 1_600_000),
    ],

    'CO': [
        ("Bogotá",        12.0, 7_400_000),
        ("Medellín",      10.0, 2_570_000),
        ("Bello",          7.0,   520_000),
        ("Cartagena",      9.0, 1_000_000),
        ("Santa Marta",    7.0,   530_000),
        ("Cali",           7.0, 2_200_000),
        ("Barranquilla",   7.0, 1_200_000),
        ("Soledad",        6.0,   660_000),
        ("Bucaramanga",    6.0,   590_000),
        ("Pereira",        6.0,   480_000),
        ("Manizales",      6.0,   430_000),
        ("Villavicencio",  5.0,   530_000),
        ("Ibagué",         5.0,   560_000),
        ("Armenia",        5.0,   310_000),
        ("Neiva",          5.0,   350_000),
        ("Cúcuta",         4.0,   710_000),
        ("Montería",       4.0,   450_000),
        ("Sincelejo",      4.0,   310_000),
        ("Valledupar",     4.0,   440_000),
        ("Pasto",          4.0,   360_000),
    ],

    'BR': [
        ("São Paulo",      20.0, 12_000_000),
        ("Rio de Janeiro", 18.0,  6_700_000),
        ("Brasília",       12.0,  3_000_000),
        ("Guarulhos",      12.0,  1_400_000),
        ("Osasco",         12.0,    700_000),
        ("Campinas",       10.0,  1_200_000),
        ("Belo Horizonte",  9.0,  2_500_000),
        ("Porto Alegre",    9.0,  1_400_000),
        ("Curitiba",        9.0,  1_900_000),
        ("Ribeirão Preto",  9.0,    700_000),
        ("Contagem",        8.0,    650_000),
        ("Sorocaba",        8.0,    700_000),
        ("Goiânia",         8.0,  1_500_000),
        ("Recife",          8.0,  1_650_000),
        ("Salvador",        8.0,  2_900_000),
        ("Natal",           7.0,    880_000),
        ("João Pessoa",     7.0,    820_000),
        ("Maceió",          7.0,    960_000),
        ("Campo Grande",    7.0,    900_000),
        ("Fortaleza",       7.0,  2_600_000),
        ("Manaus",          7.0,  2_200_000),
        ("Uberlândia",      7.0,    700_000),
        ("Teresina",        5.0,    870_000),
        ("Belém",           6.0,  1_500_000),
        ("São Luís",        6.0,  1_100_000),
    ],

    'US': [
        ("New York",       50.0, 8_300_000),
        ("San Francisco",  45.0,   870_000),
        ("Los Angeles",    35.0, 3_900_000),
        ("Boston",         35.0,   675_000),
        ("Seattle",        30.0,   750_000),
        ("Washington DC",  28.0,   690_000),
        ("Miami",          28.0,   440_000),
        ("San Diego",      32.0, 1_400_000),
        ("Chicago",        22.0, 2_700_000),
        ("Austin",         22.0, 1_000_000),
        ("Denver",         22.0,   750_000),
        ("Nashville",      18.0,   690_000),
        ("Phoenix",        18.0, 1_600_000),
        ("Las Vegas",      18.0,   660_000),
        ("Dallas",         18.0, 1_300_000),
        ("Philadelphia",   20.0, 1_600_000),
        ("Charlotte",      16.0,   900_000),
        ("Houston",        16.0, 2_300_000),
        ("Fort Worth",     15.0,   940_000),
        ("Jacksonville",   14.0,   950_000),
        ("Columbus",       14.0,   900_000),
        ("Indianapolis",   13.0,   870_000),
        ("San Antonio",    13.0, 1_400_000),
        ("Oklahoma City",  12.0,   680_000),
        ("El Paso",        12.0,   680_000),
    ],

    'ES': [
        ("Barcelona",             24.0, 1_600_000),
        ("Madrid",                22.0, 3_200_000),
        ("Palma",                 20.0,   410_000),
        ("Málaga",                18.0,   570_000),
        ("Bilbao",                15.0,   350_000),
        ("Valencia",              15.0,   800_000),
        ("Sevilla",               14.0,   690_000),
        ("Alicante",              14.0,   330_000),
        ("Las Palmas",            14.0,   380_000),
        ("Santa Cruz de Tenerife",13.0,   200_000),
        ("Pamplona",              13.0,   200_000),
        ("Granada",               13.0,   230_000),
        ("Vitoria",               12.0,   250_000),
        ("Zaragoza",              11.0,   670_000),
        ("Vigo",                  11.0,   300_000),
        ("Valladolid",             9.0,   300_000),
        ("Murcia",                 9.0,   450_000),
        ("Córdoba",               10.0,   325_000),
        ("Gijón",                 10.0,   270_000),
        ("La Coruña",             10.0,   245_000),
    ],

    'GB': [
        ("London",      42.0, 8_900_000),
        ("Oxford",      28.0,   160_000),
        ("Cambridge",   28.0,   125_000),
        ("Bristol",     22.0,   460_000),
        ("Edinburgh",   22.0,   520_000),
        ("Manchester",  20.0,   550_000),
        ("Southampton", 16.0,   250_000),
        ("Portsmouth",  16.0,   205_000),
        ("Birmingham",  17.0, 1_100_000),
        ("Glasgow",     15.0,   630_000),
        ("Leeds",       15.0,   790_000),
        ("Cardiff",     14.0,   360_000),
        ("Leicester",   14.0,   350_000),
        ("Coventry",    14.0,   370_000),
        ("Liverpool",   14.0,   490_000),
        ("Nottingham",  14.0,   330_000),
        ("Newcastle",   13.0,   300_000),
        ("Sheffield",   13.0,   580_000),
        ("Belfast",     12.0,   340_000),
        ("Bradford",    11.0,   540_000),
    ],

    'DE': [
        ("Múnich",     30.0, 1_550_000),
        ("Frankfurt",  25.0,   750_000),
        ("Hamburgo",   24.0, 1_850_000),
        ("Berlín",     22.0, 3_700_000),
        ("Stuttgart",  22.0,   630_000),
        ("Bonn",       18.0,   330_000),
        ("Karlsruhe",  18.0,   310_000),
        ("Núremberg",  17.0,   520_000),
        ("Düsseldorf", 20.0,   620_000),
        ("Colonia",    20.0, 1_080_000),
        ("Hanóver",    16.0,   540_000),
        ("Bremen",     15.0,   570_000),
        ("Dortmund",   15.0,   590_000),
        ("Bochum",     14.0,   365_000),
        ("Essen",      14.0,   580_000),
        ("Leipzig",    14.0,   600_000),
        ("Dresde",     14.0,   560_000),
        ("Bielefeld",  13.0,   340_000),
        ("Duisburgo",  13.0,   500_000),
        ("Wuppertal",  13.0,   350_000),
    ],

    'FR': [
        ("París",          35.0, 2_150_000),
        ("Niza",           24.0,   340_000),
        ("Lyon",           20.0,   500_000),
        ("Villeurbanne",   19.0,   150_000),
        ("Bordeaux",       18.0,   250_000),
        ("Nantes",         17.0,   300_000),
        ("Strasbourg",     16.0,   280_000),
        ("Montpellier",    16.0,   280_000),
        ("Toulouse",       16.0,   470_000),
        ("Rennes",         16.0,   215_000),
        ("Marseille",      16.0,   870_000),
        ("Marsella",       16.0,   870_000),
        ("Grenoble",       15.0,   160_000),
        ("Lille",          15.0,   230_000),
        ("Dijon",          13.0,   155_000),
        ("Angers",         14.0,   150_000),
        ("Toulon",         14.0,   175_000),
        ("Reims",          12.0,   180_000),
        ("Nîmes",          12.0,   150_000),
        ("Saint-Étienne",  10.0,   170_000),
        ("Le Havre",       12.0,   170_000),
    ],

    'IT': [
        ("Milán",            28.0, 1_400_000),
        ("Venecia",          20.0,   260_000),
        ("Florencia",        18.0,   370_000),
        ("Roma",             22.0, 2_800_000),
        ("Bolonia",          16.0,   400_000),
        ("Turín",            14.0,   870_000),
        ("Verona",           14.0,   260_000),
        ("Padua",            14.0,   210_000),
        ("Brescia",          13.0,   200_000),
        ("Módena",           13.0,   180_000),
        ("Génova",           12.0,   580_000),
        ("Trieste",          12.0,   200_000),
        ("Nápoles",          12.0, 3_100_000),
        ("Prato",            12.0,   195_000),
        ("Palermo",          10.0,   680_000),
        ("Bari",             10.0,   310_000),
        ("Catania",           9.0,   310_000),
        ("Taranto",           8.0,   200_000),
        ("Reggio Calabria",   8.0,   180_000),
        ("Mesina",            8.0,   230_000),
    ],

    'AU': [
        ("Sídney",         35.0, 5_300_000),
        ("Melbourne",      28.0, 5_000_000),
        ("Brisbane",       22.0, 2_500_000),
        ("Canberra",       22.0,   450_000),
        ("Perth",          20.0, 2_100_000),
        ("Gold Coast",     20.0,   700_000),
        ("Hobart",         20.0,   230_000),
        ("Wollongong",     20.0,   320_000),
        ("Adelaida",       18.0, 1_300_000),
        ("Newcastle",      18.0,   170_000),
        ("Sunshine Coast", 18.0,   350_000),
        ("Geelong",        18.0,   170_000),
        ("Darwin",         18.0,   140_000),
        ("Townsville",     14.0,   180_000),
        ("Cairns",         14.0,   150_000),
    ],

    'CA': [
        ("Vancouver",  35.0, 2_600_000),
        ("Toronto",    32.0, 2_900_000),
        ("Victoria",   26.0,   400_000),
        ("Montreal",   20.0, 2_000_000),
        ("Ottawa",     20.0, 1_000_000),
        ("Calgary",    20.0, 1_300_000),
        ("Hamilton",   18.0,   580_000),
        ("Kitchener",  18.0,   240_000),
        ("Quebec",     16.0,   540_000),
        ("Edmonton",   16.0, 1_000_000),
        ("London",     16.0,   380_000),
        ("Halifax",    16.0,   440_000),
        ("Winnipeg",   14.0,   780_000),
        ("Saskatoon",  13.0,   260_000),
        ("Regina",     13.0,   220_000),
    ],

    'IN': [
        ("Bombay",          12.0, 12_400_000),
        ("Thane",           10.0, 1_900_000),
        ("Pimpri",           8.0, 1_700_000),
        ("Delhi",           10.0, 11_000_000),
        ("Pune",             8.0, 3_100_000),
        ("Bangalore",        9.0, 8_400_000),
        ("Hyderabad",        7.0, 6_800_000),
        ("Chennai",          7.0, 7_100_000),
        ("Kolkata",          6.0, 4_500_000),
        ("Visakhapatnam",    5.0, 2_000_000),
        ("Surat",            5.0, 6_000_000),
        ("Nagpur",           5.0, 2_400_000),
        ("Ahmedabad",        5.0, 5_600_000),
        ("Indore",           5.0, 2_200_000),
        ("Vadodara",         5.0, 1_700_000),
        ("Jaipur",           5.0, 3_000_000),
        ("Lucknow",          5.0, 3_400_000),
        ("Bhopal",           4.0, 1_800_000),
        ("Kanpur",           4.0, 3_000_000),
        ("Patna",            4.0, 2_000_000),
    ],

    'ZA': [
        ("Ciudad del Cabo",  12.0, 4_600_000),
        ("Johannesburgo",    10.0, 5_600_000),
        ("Pretoria",          8.0, 2_900_000),
        ("Durban",            7.0, 3_700_000),
        ("Nelspruit",         6.0,   280_000),
        ("Port Elizabeth",    5.0, 1_200_000),
        ("Bloemfontein",      5.0,   750_000),
        ("East London",       5.0,   270_000),
        ("Polokwane",         5.0,   160_000),
        ("Kimberley",         4.0,   260_000),
    ],

    'VE': [
        ("Caracas",       10.0, 3_000_000),
        ("Valencia",       6.0, 1_400_000),
        ("Maracay",        6.0,   900_000),
        ("Maracaibo",      5.0, 2_500_000),
        ("Barquisimeto",   5.0, 1_100_000),
        ("Ciudad Guayana", 5.0,   800_000),
        ("Barcelona",      5.0,   420_000),
        ("San Cristóbal",  4.0,   650_000),
        ("Cumaná",         4.0,   350_000),
        ("Maturín",        4.0,   600_000),
    ],

    'UY': [
        ("Montevideo",  12.0, 1_380_000),
        ("Maldonado",    9.0,   170_000),
        ("Las Piedras",  7.0,   170_000),
        ("Salto",        5.0,   105_000),
        ("Paysandú",     5.0,    80_000),
        ("Rivera",       4.0,    70_000),
        ("Tacuarembó",   4.0,    60_000),
        ("Mercedes",     4.0,    45_000),
        ("Melo",         3.0,    55_000),
        ("Artigas",      3.0,    45_000),
    ],

    'EC': [
        ("Quito",          9.0, 1_900_000),
        ("Guayaquil",      8.0, 2_700_000),
        ("Cuenca",         7.0,   600_000),
        ("Manta",          6.0,   250_000),
        ("Durán",          5.0,   300_000),
        ("Santo Domingo",  5.0,   450_000),
        ("Ambato",         5.0,   330_000),
        ("Machala",        5.0,   240_000),
        ("Loja",           5.0,   190_000),
        ("Portoviejo",     4.0,   290_000),
    ],

    'BO': [
        ("Santa Cruz",   8.0, 1_600_000),
        ("La Paz",       7.0,   900_000),
        ("Cochabamba",   6.0,   630_000),
        ("Sucre",        5.0,   290_000),
        ("Tarija",       5.0,   210_000),
        ("Cobija",       4.0,    55_000),
        ("Oruro",        4.0,   260_000),
        ("Trinidad",     3.0,   120_000),
        ("Potosí",       3.0,   230_000),
        ("Riberalta",    3.0,    90_000),
    ],

    'PY': [
        ("Asunción",            8.0,   530_000),
        ("Ciudad del Este",     6.0,   300_000),
        ("San Lorenzo",         5.0,   270_000),
        ("Luque",               5.0,   280_000),
        ("Fernando de la Mora", 5.0,   130_000),
        ("Lambaré",             5.0,   130_000),
        ("Encarnación",         5.0,   120_000),
        ("Capiatá",             4.0,   220_000),
        ("Ñemby",               4.0,   110_000),
        ("Limpio",              4.0,   110_000),
    ],

    'NG': [
        ("Lagos",        12.0, 14_800_000),
        ("Abuja",        10.0, 3_000_000),
        ("Port Harcourt", 7.0, 1_900_000),
        ("Ibadan",        4.0, 3_600_000),
        ("Kano",          4.0, 3_900_000),
        ("Aba",           4.0,   680_000),
        ("Benin City",    4.0,   800_000),
        ("Jos",           4.0,   900_000),
        ("Zaria",         3.0,   820_000),
        ("Maiduguri",     3.0, 1_200_000),
    ],
}


# ══════════════════════════════════════════════════════════════
# FUNCIONES DE CLASIFICACIÓN
# ══════════════════════════════════════════════════════════════

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
    cpm = cpm_base * (income_index / 100.0) ** 0.65
    return round(max(1.5, min(cpm_base * 1.5, cpm)), 2)


# ══════════════════════════════════════════════════════════════
# TABLA POR PAÍS
# ══════════════════════════════════════════════════════════════

def calculate_commune_table(country: str = 'CL') -> list:
    """Retorna tabla de comunas/ciudades clasificadas para un país."""
    if country == 'CL':
        cpm_base = CPM_BASE_BY_COUNTRY.get('CL', 8.0)
        communes = []
        for nombre, region, uf_m2, poblacion in COMUNAS_DATA:
            index = uf_to_index(uf_m2)
            tier  = get_se_tier(index)
            cpm   = calculate_cpm(index, cpm_base)
            communes.append({
                "nombre":         nombre,
                "region":         region,
                "uf_m2":          uf_m2,
                "income_index":   index,
                "se_tier":        tier,
                "se_descripcion": get_se_description(tier),
                "cpm_usd":        cpm,
                "poblacion":      poblacion,
                "votantes_est":   int(poblacion * 0.75 * 0.35),
                "country":        "CL",
            })
        communes.sort(key=lambda x: x["income_index"], reverse=True)
        return communes

    data = GLOBAL_RENT_DATA.get(country, [])
    if not data:
        return []

    prices = [row[1] for row in data]
    reference_usd = max(prices)
    cpm_base = CPM_BASE_BY_COUNTRY.get(country, 5.0)

    communes = []
    for nombre, usd_m2, poblacion in data:
        index = usd_to_index(usd_m2, reference_usd)
        tier  = get_se_tier(index)
        cpm   = calculate_cpm(index, cpm_base)
        communes.append({
            "nombre":         nombre,
            "region":         country,
            "usd_m2":         usd_m2,
            "income_index":   index,
            "se_tier":        tier,
            "se_descripcion": get_se_description(tier),
            "cpm_usd":        cpm,
            "poblacion":      poblacion,
            "votantes_est":   int(poblacion * 0.75 * 0.35),
            "country":        country,
        })
    communes.sort(key=lambda x: x["income_index"], reverse=True)
    return communes


def calculate_all_communes_table() -> list:
    """Retorna tabla completa para todos los países."""
    all_communes = calculate_commune_table('CL')
    for country_code in GLOBAL_RENT_DATA:
        all_communes.extend(calculate_commune_table(country_code))
    return all_communes


# ══════════════════════════════════════════════════════════════
# ALLOCATION DE PRESUPUESTO (Chile — backward compat)
# ══════════════════════════════════════════════════════════════

def allocate_budget(
    budget_usd: float,
    target_se: list = None,
    target_region: str = None,
    max_communes: int = None,
    country: str = 'CL',
) -> dict:
    communes = calculate_commune_table(country)
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
            "ciudad":              c["nombre"],
            "country":             c["country"],
            "se_tier":             c["se_tier"],
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
        "generated_at":          datetime.utcnow().isoformat(),
    }


# ══════════════════════════════════════════════════════════════
# DEMO
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    all_countries = ['CL'] + list(GLOBAL_RENT_DATA.keys())
    total = 0
    for cc in all_countries:
        table = calculate_commune_table(cc)
        total += len(table)
        tiers = {}
        for c in table:
            tiers[c['se_tier']] = tiers.get(c['se_tier'], 0) + 1
        print(f"{cc}: {len(table)} ciudades — {tiers}")
    print(f"\nTotal global: {total} ciudades en {len(all_countries)} países")
