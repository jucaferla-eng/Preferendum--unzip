from __future__ import annotations
"""
car_sales_agent.py — Ventas de autos por marca × país
======================================================
Fuente primaria: datos reales 2024-2026 de mercados clave.
- Car Sales Statistics (carsalesstatistics.com)
- Visual Capitalist Ranked: Top Car Brand in 61 Countries (May 2026)
- OICA / MARKLINES / SMMT / Focus2Move / Autotrader
- Datos compartidos por JC Fernandez, agosto 2026

Tabla: car_brand_sales
  brand         TEXT    — nombre normalizado (minúsculas, sin tildes)
  country_iso   TEXT    — ISO 3166-1 alpha-2
  year          INT
  units_sold    INT     — estimado: market_share_pct × total_market
  market_share_pct REAL — % del mercado nacional
  total_market  INT     — total de autos nuevos vendidos en ese país × año
  source        TEXT
"""

from sqlalchemy import text

# ── Ventas globales por marca 2025 — Top 25 ──────────────────────────────────
# Fuente: Car Industry Analysis 2025 (OEMs + estimaciones)
# Compartido por JC Fernandez, agosto 2026
# Nota: estas son MARCAS individuales, no grupos corporativos.
# Toyota Group (Toyota+Daihatsu+Lexus+Hino) ≈ 10.8% × 96M = ~10.4M
# VW Group (VW+Audi+Skoda+Seat+Porsche) ≈ 8.9% × 96M = ~8.5M
# Hyundai Group (Hyundai+Kia) = 3.89M + 3.14M = 7.03M ≈ 7.4%
GLOBAL_BRAND_UNITS_2025: dict[str, dict] = {
    'toyota':      {'rank': 1,  'units': 9_654_600, 'yoy_pct':  +4,  'chinese': False},
    'volkswagen':  {'rank': 2,  'units': 5_124_300, 'yoy_pct':  -2,  'chinese': False},
    'ford':        {'rank': 3,  'units': 4_235_000, 'yoy_pct':  -2,  'chinese': False},
    'byd':         {'rank': 4,  'units': 4_205_900, 'yoy_pct':  +3,  'chinese': True},
    'hyundai':     {'rank': 5,  'units': 3_887_200, 'yoy_pct':  -1,  'chinese': False},
    'honda':       {'rank': 6,  'units': 3_312_000, 'yoy_pct': -10,  'chinese': False},
    'suzuki':      {'rank': 7,  'units': 3_295_000, 'yoy_pct':  +1,  'chinese': False},
    'nissan':      {'rank': 8,  'units': 3_141_200, 'yoy_pct':  -4,  'chinese': False},
    'kia':         {'rank': 9,  'units': 3_135_800, 'yoy_pct':  +2,  'chinese': False},
    'chevrolet':   {'rank': 10, 'units': 2_825_000, 'yoy_pct':  -5,  'chinese': False},
    'geely':       {'rank': 11, 'units': 2_450_000, 'yoy_pct': +47,  'chinese': True},
    'bmw':         {'rank': 12, 'units': 2_169_800, 'yoy_pct':  -1,  'chinese': False},
    'mercedes-benz':{'rank':13, 'units': 2_159_900, 'yoy_pct': -10,  'chinese': False},
    'tesla':       {'rank': 14, 'units': 1_636_200, 'yoy_pct':  -9,  'chinese': False},
    'renault':     {'rank': 15, 'units': 1_628_000, 'yoy_pct':  +3,  'chinese': False},
    'audi':        {'rank': 16, 'units': 1_623_600, 'yoy_pct':  -3,  'chinese': False},
    'wuling':      {'rank': 17, 'units': 1_587_100, 'yoy_pct': +20,  'chinese': True},
    'changan':     {'rank': 18, 'units': 1_586_100, 'yoy_pct': +15,  'chinese': True},
    'chery':       {'rank': 19, 'units': 1_321_000, 'yoy_pct':  +3,  'chinese': True},
    'mazda':       {'rank': 20, 'units': 1_256_300, 'yoy_pct':  -2,  'chinese': False},
    'fiat':        {'rank': 21, 'units': 1_226_000, 'yoy_pct':  -2,  'chinese': False},
    'peugeot':     {'rank': 22, 'units': 1_085_000, 'yoy_pct':   0,  'chinese': False},
    'skoda':       {'rank': 23, 'units': 1_043_900, 'yoy_pct': +13,  'chinese': False},
    'tata':        {'rank': 24, 'units':   968_600, 'yoy_pct':  +8,  'chinese': False},
    'jeep':        {'rank': 25, 'units':   955_000, 'yoy_pct':   0,  'chinese': False},
}
# Total top-25: ~67.5M de 96M globales = 70% del mercado
GLOBAL_MARKET_2025 = {
    'total_units': 96_000_000,
    'year':        2025,
    'source':      'Car Industry Analysis 2025 (OEMs + estimaciones) — JC Aug 2026',
    'chinese_brands_top25': ['byd', 'geely', 'wuling', 'changan', 'chery'],
    'chinese_units_top25':  4_205_900 + 2_450_000 + 1_587_100 + 1_586_100 + 1_321_000,
    'note': (
        'Marcas chinas top-25: 11.15M unidades = 11.6% del mercado global. '
        'Geely +47%, Wuling +20%, Changan +15% — todas creciendo. '
        'Honda -10%, Mercedes -10%, Tesla -9%, Nissan -4% — todas cayendo.'
    ),
}

# ── Tamaño total de mercado por país (unidades nuevas, año referencia) ────────
# Fuente: OICA 2024-2025 + estimaciones regionales JC
_TOTAL_MARKET: dict[str, tuple[int, int]] = {
    # iso2: (total_units, year)
    # ── Mercados grandes ──────────────────────────────────────────────────────
    'US': (16_200_000, 2025),   # Autopunditz: best since 2019
    'CN': (30_000_000, 2025),   # China: mayor mercado mundial
    'DE': ( 2_800_000, 2025),   # MarkLines H1 2026 × 2
    'GB': ( 1_950_000, 2025),   # SMMT
    'FR': ( 1_500_000, 2025),
    'ES': ( 1_100_000, 2025),
    'IT': ( 1_600_000, 2025),
    'JP': ( 4_500_000, 2025),   # JAMA
    'BR': ( 2_200_000, 2025),   # ANFAVEA
    'MX': ( 1_300_000, 2025),   # AMIA
    # ── Mercados secundarios ──────────────────────────────────────────────────
    'IN': ( 4_400_000, 2025),   # India: 3er mercado mundial y creciendo
    'CA': ( 1_850_000, 2025),   # Canadá
    'AU': ( 1_100_000, 2025),   # Australia
    'KR': ( 1_700_000, 2025),   # Corea del Sur
    'ID': ( 1_000_000, 2025),   # Indonesia
    'TH': (   700_000, 2025),   # Tailandia (hub manufacturero Toyota)
    'TR': ( 1_000_000, 2025),   # Turquía
    'PL': (   600_000, 2025),   # Polonia
    'AR': (   500_000, 2025),   # Argentina
    'ZA': (   360_000, 2025),   # Sudáfrica
    'SA': (   600_000, 2025),   # Arabia Saudita
    'SE': (   350_000, 2025),   # Suecia
    'NL': (   450_000, 2025),   # Países Bajos
    'BE': (   450_000, 2025),   # Bélgica
    'CH': (   330_000, 2025),   # Suiza
    'CL': (   220_000, 2025),   # Chile
    'CO': (   200_000, 2025),   # Colombia
    'NO': (   180_000, 2025),   # Noruega (alto share EV)
    'AE': (   300_000, 2025),   # Emiratos Árabes
    'RU': ( 1_500_000, 2025),   # Rusia (reducido post-sanciones, marcas chinas dominan)
    'PH': (   400_000, 2025),   # Filipinas
    'MY': (   700_000, 2025),   # Malasia
    'VN': (   300_000, 2025),   # Vietnam
    'EG': (   200_000, 2025),   # Egipto
    'NG': (    50_000, 2025),   # Nigeria
    'PT': (   250_000, 2025),   # Portugal
    'CZ': (   270_000, 2025),   # República Checa
    'AT': (   330_000, 2025),   # Austria
}

_SOURCE = 'CarSalesStatistics/VisualCapitalist/OICA_2024-2026_JC-Aug2026'

# ── Market share por país → marca (top 10 por país) ──────────────────────────
# Fuente: JC Aug 2026 (imágenes compartidas en sesión)
_MARKET_SHARE: dict[str, list[tuple[str, float]]] = {
    'US': [
        ('toyota',      13.5),
        ('ford',        12.0),
        ('chevrolet',   10.9),
        ('honda',        7.2),
        ('hyundai',      5.4),
        ('kia',          5.1),
        ('nissan',       4.9),
        ('gmc',          3.6),
        ('subaru',       3.5),
        ('jeep',         3.4),
    ],
    'CN': [
        ('byd',         15.8),
        ('volkswagen',   9.2),
        ('geely',        6.4),
        ('changan',      5.3),
        ('toyota',       5.1),
        ('chery',        4.3),
        ('wuling',       3.8),
        ('honda',        3.5),
        ('tesla',        3.1),
        ('nissan',       2.9),
    ],
    'DE': [
        ('volkswagen',  18.4),
        ('skoda',        8.6),
        ('bmw',          8.5),
        ('mercedes-benz',8.5),
        ('audi',         7.4),
        ('seat',         5.9),
        ('opel',         4.8),
        ('ford',         3.3),
        ('hyundai',      3.1),
        ('toyota',       2.4),
    ],
    'GB': [
        ('volkswagen',   8.8),
        ('bmw',          7.1),
        ('kia',          5.5),
        ('audi',         5.2),
        ('ford',         5.1),
        ('hyundai',      4.8),
        ('nissan',       4.6),
        ('toyota',       4.5),
        ('mercedes-benz',4.4),
        ('mg',           4.3),
    ],
    'FR': [
        ('renault',     16.2),
        ('peugeot',     14.1),
        ('dacia',        8.9),
        ('citroen',      6.5),
        ('volkswagen',   6.1),
        ('toyota',       5.8),
        ('bmw',          3.9),
        ('mercedes-benz',3.4),
        ('audi',         3.1),
        ('kia',          2.8),
    ],
    'ES': [
        ('toyota',       8.5),
        ('volkswagen',   6.9),
        ('seat',         6.4),
        ('hyundai',      6.2),
        ('renault',      6.1),
        ('kia',          6.0),
        ('dacia',        5.4),
        ('peugeot',      5.2),
        ('mercedes-benz',4.7),
        ('bmw',          4.5),
    ],
    'IT': [
        ('fiat',        10.8),
        ('volkswagen',   7.6),
        ('toyota',       6.8),
        ('dacia',        5.7),
        ('renault',      5.4),
        ('peugeot',      5.1),
        ('jeep',         4.3),
        ('ford',         4.1),
        ('audi',         4.0),
        ('bmw',          3.7),
    ],
    'JP': [
        ('toyota',      32.4),
        ('suzuki',      13.5),
        ('honda',       12.1),
        ('daihatsu',     9.8),
        ('nissan',       9.4),
        ('mazda',        4.2),
        ('subaru',       2.5),
        ('mitsubishi',   2.2),
        ('lexus',        1.9),
        ('mercedes-benz',1.3),
    ],
    'BR': [
        ('fiat',        21.2),
        ('volkswagen',  15.7),
        ('chevrolet',   11.8),
        ('byd',          7.8),
        ('hyundai',      7.6),
        ('toyota',       7.1),
        ('jeep',         4.5),
        ('renault',      4.2),
        ('honda',        3.1),
        ('gwm',          2.5),
    ],
    'MX': [
        ('nissan',      17.1),
        ('chevrolet',   12.4),
        ('volkswagen',   8.9),
        ('toyota',       8.2),
        ('kia',          7.4),
        ('mazda',        5.6),
        ('chrysler',     4.8),
        ('hyundai',      3.8),
        ('ford',         3.4),
        ('mg',           3.2),
    ],
    # ── Mercados secundarios ─────────────────────────────────────────────────
    # Fuente: OICA 2025 / marklines / estimaciones sectoriales JC
    'IN': [   # India: Maruti-Suzuki domina, Toyota débil
        ('maruti',      40.9),
        ('hyundai',     14.1),
        ('tata',        13.2),
        ('mahindra',     8.3),
        ('kia',          5.9),
        ('toyota',       4.5),
        ('honda',        2.4),
        ('skoda',        1.6),
        ('volkswagen',   1.4),
        ('byd',          0.8),  # creciendo rápido
    ],
    'CA': [   # Canadá: similar a USA
        ('ford',        14.2),
        ('chevrolet',   11.8),
        ('toyota',      10.1),
        ('honda',        8.4),
        ('ram',          7.6),
        ('hyundai',      6.9),
        ('kia',          5.8),
        ('gmc',          5.3),
        ('nissan',       4.7),
        ('mazda',        4.1),
    ],
    'AU': [   # Australia: Toyota #1 dominante
        ('toyota',      22.3),
        ('mazda',        9.8),
        ('hyundai',      8.6),
        ('kia',          7.9),
        ('ford',         6.8),
        ('mitsubishi',   5.7),
        ('volkswagen',   4.2),
        ('subaru',       4.1),
        ('mercedes-benz',3.3),
        ('bmw',          3.1),
    ],
    'KR': [   # Corea del Sur: marcas locales dominan 95%+
        ('hyundai',     46.8),
        ('kia',         30.2),
        ('genesis',      5.1),
        ('chevrolet',    3.4),
        ('renault',      2.8),
        ('mercedes-benz',2.1),
        ('bmw',          1.9),
        ('toyota',       1.0),
        ('audi',         0.8),
        ('volkswagen',   0.7),
    ],
    'ID': [   # Indonesia: Toyota + Daihatsu (grupo Toyota) ~50%
        ('toyota',      34.1),
        ('honda',       18.3),
        ('daihatsu',    16.2),  # subsidiaria Toyota
        ('suzuki',       9.4),
        ('mitsubishi',   7.8),
        ('wuling',       4.3),  # GM-SAIC China
        ('nissan',       2.1),
        ('hyundai',      1.9),
        ('byd',          1.8),  # creciendo
        ('chery',        1.1),
    ],
    'TH': [   # Tailandia: hub manufactura Toyota/pickup
        ('toyota',      32.0),
        ('isuzu',       17.8),
        ('honda',       12.1),
        ('mitsubishi',   8.4),
        ('mazda',        5.3),
        ('ford',         4.2),
        ('suzuki',       3.8),
        ('mg',           3.4),  # SAIC China
        ('byd',          3.2),  # fuerte crecimiento EV
        ('nissan',       2.9),
    ],
    'TR': [   # Turquía: Fiat+Renault+VW fuertes (manufactura local)
        ('fiat',        10.8),
        ('renault',     10.4),
        ('volkswagen',   8.9),
        ('toyota',       8.1),
        ('hyundai',      7.6),
        ('peugeot',      6.3),
        ('ford',         5.9),
        ('dacia',        5.4),
        ('kia',          4.8),
        ('citroen',      4.1),
    ],
    'PL': [   # Polonia: VW Group domina (Skoda fabricado en PL)
        ('skoda',       11.2),
        ('volkswagen',  10.1),
        ('toyota',       9.3),
        ('kia',          7.8),
        ('hyundai',      7.4),
        ('bmw',          5.1),
        ('ford',         4.9),
        ('peugeot',      4.7),
        ('opel',         4.3),
        ('mercedes-benz',4.1),
    ],
    'AR': [   # Argentina: fuerte presencia Peugeot/Renault/Toyota (fabrican ahí)
        ('peugeot',     14.3),
        ('renault',     12.8),
        ('toyota',      11.2),
        ('volkswagen',   9.7),
        ('chevrolet',    9.4),
        ('fiat',         8.1),
        ('ford',         6.8),
        ('jeep',         4.3),
        ('citroen',      3.9),
        ('hyundai',      3.4),
    ],
    'ZA': [   # Sudáfrica: Toyota #1 histórico
        ('toyota',      25.1),
        ('volkswagen',  16.8),
        ('hyundai',      8.9),
        ('ford',         8.3),
        ('renault',      6.1),
        ('chevrolet',    4.8),
        ('nissan',       4.2),
        ('mercedes-benz',3.4),
        ('bmw',          3.1),
        ('kia',          2.9),
    ],
    'SA': [   # Arabia Saudita: Toyota + Hyundai dominan
        ('toyota',      31.8),
        ('hyundai',     13.4),
        ('kia',          9.8),
        ('nissan',       9.1),
        ('chevrolet',    6.3),
        ('ford',         4.8),
        ('mitsubishi',   4.1),
        ('mercedes-benz',3.6),
        ('bmw',          3.0),
        ('honda',        2.7),
    ],
    'SE': [   # Suecia: Volvo nacional, alto share premium
        ('volvo',       17.2),
        ('volkswagen',  10.8),
        ('toyota',       9.7),
        ('kia',          7.3),
        ('hyundai',      6.9),
        ('bmw',          5.8),
        ('tesla',        5.4),
        ('skoda',        5.1),
        ('ford',         4.3),
        ('mercedes-benz',4.1),
    ],
    'NO': [   # Noruega: mayor penetración EV del mundo (~90% ventas)
        ('tesla',       19.8),
        ('toyota',      12.1),
        ('volkswagen',   9.4),
        ('bmw',          7.8),
        ('hyundai',      6.9),
        ('kia',          6.4),
        ('volvo',        5.7),
        ('audi',         4.8),
        ('mercedes-benz',4.2),
        ('byd',          3.9),  # creciendo rápido en Europa
    ],
    'NL': [   # Países Bajos: fuerte share EV + Tesla
        ('volkswagen',   8.9),
        ('toyota',       8.3),
        ('tesla',        7.1),
        ('kia',          6.8),
        ('peugeot',      6.4),
        ('ford',         5.9),
        ('hyundai',      5.7),
        ('bmw',          5.3),
        ('opel',         4.8),
        ('mercedes-benz',4.4),
    ],
    'BE': [
        ('volkswagen',   9.8),
        ('peugeot',      8.7),
        ('toyota',       7.4),
        ('renault',      6.8),
        ('bmw',          6.1),
        ('kia',          5.9),
        ('audi',         5.4),
        ('skoda',        5.1),
        ('mercedes-benz',4.8),
        ('hyundai',      4.6),
    ],
    'CH': [   # Suiza: premium dominante
        ('volkswagen',   8.4),
        ('bmw',          8.1),
        ('mercedes-benz',7.8),
        ('skoda',        7.3),
        ('toyota',       7.1),
        ('audi',         6.8),
        ('hyundai',      5.3),
        ('kia',          4.9),
        ('ford',         4.1),
        ('volvo',        4.0),
    ],
    'CL': [   # Chile: Toyota líder, mercado premium LatAm
        ('toyota',      17.4),
        ('chevrolet',   10.1),
        ('hyundai',      9.3),
        ('kia',          8.8),
        ('nissan',       7.6),
        ('volkswagen',   5.9),
        ('ford',         5.1),
        ('suzuki',       4.7),
        ('peugeot',      4.2),
        ('byd',          3.8),  # creciendo fuerte en Chile
    ],
    'CO': [   # Colombia
        ('renault',     16.1),
        ('chevrolet',   13.8),
        ('kia',         12.4),
        ('toyota',       9.8),
        ('hyundai',      8.3),
        ('mazda',        7.1),
        ('nissan',       5.4),
        ('volkswagen',   4.8),
        ('byd',          4.1),
        ('ford',         3.2),
    ],
    'AE': [   # Emiratos: Toyota + premium alemán
        ('toyota',      28.4),
        ('nissan',      11.2),
        ('mercedes-benz',8.9),
        ('bmw',          7.4),
        ('honda',        6.8),
        ('mitsubishi',   5.9),
        ('chevrolet',    5.4),
        ('audi',         4.8),
        ('hyundai',      4.1),
        ('kia',          3.7),
    ],
    'RU': [   # Rusia: post-sanciones dominan marcas chinas y Lada
        ('lada',        26.3),
        ('haval',        9.8),  # Great Wall China
        ('chery',        8.4),
        ('geely',        7.1),
        ('byd',          6.8),
        ('changan',      5.9),
        ('omoda',        4.3),  # Chery sub-brand
        ('exeed',        3.8),  # Chery sub-brand
        ('volkswagen',   2.1),  # reducido
        ('toyota',       1.8),  # reducido
    ],
    'PH': [   # Filipinas: Toyota #1
        ('toyota',      38.2),
        ('mitsubishi',  14.6),
        ('ford',         8.3),
        ('hyundai',      7.1),
        ('honda',        6.4),
        ('suzuki',       5.8),
        ('geely',        4.2),  # China creciendo
        ('mg',           3.9),
        ('nissan',       3.4),
        ('kia',          2.8),
    ],
    'MY': [   # Malasia: Perodua+Proton (locales) dominan
        ('perodua',     38.1),  # marca nacional malaya
        ('proton',      16.4),  # nacional (ahora Geely-Zhejiang)
        ('honda',        9.8),
        ('toyota',       8.4),
        ('nissan',       4.8),
        ('mazda',        4.1),
        ('mitsubishi',   3.7),
        ('byd',          3.4),
        ('kia',          2.9),
        ('hyundai',      2.4),
    ],
    'PT': [
        ('volkswagen',   8.9),
        ('peugeot',      8.4),
        ('renault',      8.1),
        ('toyota',       7.8),
        ('kia',          6.9),
        ('hyundai',      6.4),
        ('dacia',        5.9),
        ('citroen',      5.4),
        ('bmw',          4.8),
        ('mercedes-benz',4.3),
    ],
    'CZ': [   # República Checa: Skoda fabricado ahí
        ('skoda',       23.4),  # fabricado en Mlada Boleslav
        ('volkswagen',   9.1),
        ('toyota',       7.8),
        ('kia',          6.9),
        ('hyundai',      6.4),
        ('ford',         5.8),
        ('peugeot',      5.1),
        ('dacia',        4.8),
        ('bmw',          4.1),
        ('mercedes-benz',3.8),
    ],
    'AT': [   # Austria: premium dominante (mercado rico)
        ('volkswagen',  10.1),
        ('skoda',        8.9),
        ('bmw',          8.4),
        ('mercedes-benz',7.8),
        ('audi',         7.1),
        ('toyota',       6.8),
        ('hyundai',      5.4),
        ('seat',         4.9),
        ('ford',         4.3),
        ('kia',          4.1),
    ],
}

# ── Aliases de marcas para normalizar nombres alternativos ───────────────────
_BRAND_ALIASES: dict[str, str] = {
    'vw':            'volkswagen',
    'chevy':         'chevrolet',
    'gm':            'chevrolet',
    'mercedes':      'mercedes-benz',
    'benz':          'mercedes-benz',
    'merc':          'mercedes-benz',
    'citroen':       'citroen',
    'citroën':       'citroen',
    'daimler':       'mercedes-benz',
    'stellantis':    'chrysler',
    'fca':           'fiat',
    'byd auto':      'byd',
    'general motors':'chevrolet',
}


def normalize_brand(name: str) -> str:
    n = name.lower().strip()
    return _BRAND_ALIASES.get(n, n)


def _create_table(db) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS car_brand_sales (
            id               SERIAL PRIMARY KEY,
            brand            TEXT NOT NULL,
            country_iso      TEXT NOT NULL,
            year             INT  NOT NULL,
            units_sold       INT,
            market_share_pct REAL,
            total_market     INT,
            yoy_pct          REAL,   -- variación año anterior %
            source           TEXT,
            updated_at       TIMESTAMP DEFAULT NOW(),
            UNIQUE (brand, country_iso, year)
        )
    """))
    # Agregar columna yoy_pct si ya existe la tabla sin ella
    try:
        db.execute(text(
            'ALTER TABLE car_brand_sales ADD COLUMN IF NOT EXISTS yoy_pct REAL'
        ))
    except Exception:
        pass
    db.commit()


def run_car_sales_import(db) -> dict:
    """Importa/actualiza ventas de autos por marca × país en BD."""
    _create_table(db)
    inserted = 0

    for country_iso, brand_list in _MARKET_SHARE.items():
        total_market, year = _TOTAL_MARKET.get(country_iso, (0, 2024))

        for brand, share_pct in brand_list:
            units = int(total_market * share_pct / 100) if total_market > 0 else None
            db.execute(text("""
                INSERT INTO car_brand_sales
                    (brand, country_iso, year, units_sold, market_share_pct,
                     total_market, source, updated_at)
                VALUES (:brand, :cc, :year, :units, :share, :total, :src, NOW())
                ON CONFLICT (brand, country_iso, year) DO UPDATE SET
                    units_sold       = EXCLUDED.units_sold,
                    market_share_pct = EXCLUDED.market_share_pct,
                    total_market     = EXCLUDED.total_market,
                    source           = EXCLUDED.source,
                    updated_at       = NOW()
            """), {
                'brand': brand,
                'cc':    country_iso,
                'year':  year,
                'units': units,
                'share': share_pct,
                'total': total_market,
                'src':   _SOURCE,
            })
            inserted += 1

    # ── Ranking global 2025 (country_iso='GLOBAL') ──────────────────────────
    global_total = GLOBAL_MARKET_2025['total_units']
    for brand, meta in GLOBAL_BRAND_UNITS_2025.items():
        global_share = round(meta['units'] / global_total * 100, 3)
        db.execute(text("""
            INSERT INTO car_brand_sales
                (brand, country_iso, year, units_sold, market_share_pct,
                 total_market, yoy_pct, source, updated_at)
            VALUES (:brand, 'GLOBAL', :year, :units, :share, :total, :yoy, :src, NOW())
            ON CONFLICT (brand, country_iso, year) DO UPDATE SET
                units_sold       = EXCLUDED.units_sold,
                market_share_pct = EXCLUDED.market_share_pct,
                total_market     = EXCLUDED.total_market,
                yoy_pct          = EXCLUDED.yoy_pct,
                source           = EXCLUDED.source,
                updated_at       = NOW()
        """), {
            'brand': brand,
            'year':  2025,
            'units': meta['units'],
            'share': global_share,
            'total': global_total,
            'yoy':   meta.get('yoy_pct'),
            'src':   _SOURCE,
        })
        inserted += 1

    db.commit()

    brands_covered = sorted({b for brands in _MARKET_SHARE.values() for b, _ in brands})
    return {
        'status':          'ok',
        'inserted_updated': inserted,
        'countries':       list(_MARKET_SHARE.keys()) + ['GLOBAL'],
        'brands':          brands_covered,
        'global_brands':   list(GLOBAL_BRAND_UNITS_2025.keys()),
        'chinese_brands':  GLOBAL_MARKET_2025['chinese_brands_top25'],
        'table':           'car_brand_sales',
        'source':          _SOURCE,
        'note': (
            'Top 10 marcas por país (35 mercados, 2024-2026) + '
            'ranking global Top 25 2025 (country_iso=GLOBAL, Car Industry Analysis). '
            'Chinese brands Top 25: 11.15M units = 11.6% del mercado global.'
        ),
    }


def get_brand_sales(db, brand: str, year: int = None) -> dict[str, int]:
    """
    Retorna {country_iso: units_sold} para una marca dada.
    Usado por optimize_budget_strategic como brand_sales_by_country.
    """
    brand_norm = normalize_brand(brand)
    try:
        q = """
            SELECT country_iso, units_sold
            FROM car_brand_sales
            WHERE brand = :brand
        """
        params: dict = {'brand': brand_norm}
        if year:
            q += ' AND year = :year'
            params['year'] = year
        else:
            q += ' ORDER BY year DESC'

        rows = db.execute(text(q), params).fetchall()
        # Si hay múltiples años, tomar el más reciente por país
        seen: dict[str, int] = {}
        for cc, units in rows:
            if cc not in seen and units:
                seen[cc] = int(units)
        return seen
    except Exception:
        return {}


def list_brands(db) -> list[str]:
    """Lista todas las marcas disponibles en BD."""
    try:
        rows = db.execute(text(
            'SELECT DISTINCT brand FROM car_brand_sales ORDER BY brand'
        )).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []
