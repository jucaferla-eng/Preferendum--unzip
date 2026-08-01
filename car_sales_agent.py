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

# ── Tamaño total de mercado por país (unidades nuevas, año referencia) ────────
# Fuente: OICA 2024 + SMMT H1 2026 × 2 + estimaciones JC
_TOTAL_MARKET: dict[str, tuple[int, int]] = {
    # iso2: (total_units, year)
    'US': (16_200_000, 2025),   # Autopunditz: 16.2-16.3M, best since 2019
    'CN': (30_000_000, 2024),   # China: ~30M unidades (mayor mercado mundial)
    'DE': (  2_800_000, 2026),  # MarkLines H1 2026 × 2 ≈ 2.8M
    'GB': (  1_950_000, 2026),  # SMMT H1 2026 × 2
    'FR': (  1_500_000, 2025),  # Focus2Move estimado
    'ES': (  1_100_000, 2025),  # ANFAC estimado
    'IT': (  1_600_000, 2025),  # ANFIA estimado
    'JP': (  4_500_000, 2024),  # JAMA 2024
    'BR': (  2_200_000, 2024),  # ANFAVEA 2024
    'MX': (  1_300_000, 2024),  # AMIA 2024
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
            source           TEXT,
            updated_at       TIMESTAMP DEFAULT NOW(),
            UNIQUE (brand, country_iso, year)
        )
    """))
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

    db.commit()

    # Resumen de marcas y países cubiertos
    brands_covered = sorted({b for brands in _MARKET_SHARE.values() for b, _ in brands})
    return {
        'status':          'ok',
        'inserted_updated': inserted,
        'countries':       list(_MARKET_SHARE.keys()),
        'brands':          brands_covered,
        'table':           'car_brand_sales',
        'source':          _SOURCE,
        'note': (
            'Top 10 marcas por país para 10 mercados clave (2024-2026). '
            'Unidades estimadas = market_share_pct × total_market_nacional.'
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
