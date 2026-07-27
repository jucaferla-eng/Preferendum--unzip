"""
BLS OEWS MSA Agent — Salarios por ocupación × área metropolitana USA
=====================================================================
Fuente: BLS Occupational Employment and Wage Statistics (OEWS)
URL:    https://www.bls.gov/oes/tables.htm
Archivo: oesm23ma.zip → alldata_M_2023.xlsx (o similar)

Tabla resultante: bls_oews_msa
  ~350,000 filas (818 ocupaciones × 411 MSAs + estados + national)
"""

import io, os, zipfile
import pandas as pd
from sqlalchemy import text

# ── DDL ───────────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS bls_oews_msa (
    id               SERIAL PRIMARY KEY,
    area_code        TEXT,                      -- FIPS code del MSA (7 dígitos)
    area_name        TEXT,                      -- ej. "San Jose-Sunnyvale-Santa Clara, CA"
    area_type        TEXT,                      -- 'MSA', 'State', 'National'
    soc_code         TEXT,                      -- ej. "17-2051"
    occ_title        TEXT,
    total_employment INTEGER,
    median_annual_usd REAL,                     -- A_MEDIAN en BLS
    mean_annual_usd   REAL,                     -- A_MEAN en BLS
    pct_25_annual_usd REAL,                     -- A_PCT25
    pct_75_annual_usd REAL,                     -- A_PCT75
    year             INTEGER DEFAULT 2023,
    updated_at       TIMESTAMP DEFAULT NOW(),
    UNIQUE(area_code, soc_code, year)
);

CREATE INDEX IF NOT EXISTS idx_oews_msa_soc   ON bls_oews_msa(soc_code);
CREATE INDEX IF NOT EXISTS idx_oews_msa_area  ON bls_oews_msa(area_code);
CREATE INDEX IF NOT EXISTS idx_oews_msa_name  ON bls_oews_msa(area_name);
"""

# ── Mapeo tipo de área ────────────────────────────────────────────────────────

def _area_type(code: str) -> str:
    """FIPS area code → tipo de área."""
    if not code:
        return 'Unknown'
    code = str(code).strip()
    if code == '0000000':
        return 'National'
    if len(code) == 2 or (len(code) == 7 and code[2:] == '00000'):
        return 'State'
    return 'MSA'


# ── Descarga y parseo ─────────────────────────────────────────────────────────

def _download_oews_zip(year: int = 2023) -> bytes:
    """Descarga el ZIP de OEWS MSA desde BLS. Puede fallar si BLS bloquea la IP."""
    import urllib.request
    url = f'https://www.bls.gov/oes/special.requests/oesm{str(year)[2:]}ma.zip'
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; research-bot)',
        'Referer': 'https://www.bls.gov/oes/tables.htm',
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def parse_oews_zip(zip_bytes: bytes, year: int = 2023) -> pd.DataFrame:
    """
    Parsea el ZIP de OEWS MSA de BLS.
    El archivo Excel tiene columnas: AREA, AREA_TITLE, OCC_CODE, OCC_TITLE,
    TOT_EMP, A_MEAN, A_MEDIAN, A_PCT25, A_PCT75, etc.
    """
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    # Buscar el archivo Excel principal
    xlsx_name = None
    for name in z.namelist():
        if name.endswith('.xlsx') and ('alldata' in name.lower() or 'MSA' in name.upper() or 'msa' in name.lower()):
            xlsx_name = name
            break
    if not xlsx_name:
        # Fallback: primer xlsx
        for name in z.namelist():
            if name.endswith('.xlsx'):
                xlsx_name = name
                break
    if not xlsx_name:
        raise ValueError(f"No se encontró archivo .xlsx en el ZIP. Archivos: {z.namelist()}")

    print(f"  Parseando: {xlsx_name}")
    df = pd.read_excel(io.BytesIO(z.read(xlsx_name)), dtype=str)
    print(f"  Filas raw: {len(df)}, columnas: {list(df.columns[:10])}")
    return df, year


def _safe_float(val) -> float | None:
    """Convierte valor BLS a float — maneja '*', '**', '#', NaN."""
    if pd.isna(val):
        return None
    s = str(val).strip().replace(',', '')
    if s in ('*', '**', '#', '-', '', 'nan'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _safe_int(val) -> int | None:
    f = _safe_float(val)
    return int(f) if f is not None else None


# ── Import principal ──────────────────────────────────────────────────────────

def run_oews_msa_import(db, zip_bytes: bytes, year: int = 2023) -> dict:
    """
    Crea la tabla bls_oews_msa e importa los datos del ZIP de BLS.

    Args:
        db:        SQLAlchemy session
        zip_bytes: contenido del archivo oesm23ma.zip (descargado o subido manualmente)
        year:      año de los datos (default 2023)

    Returns:
        dict con estadísticas del import
    """
    # DDL
    db.execute(text(DDL))
    db.commit()
    print("Tabla bls_oews_msa lista.")

    # Parsear
    df, year = parse_oews_zip(zip_bytes, year)

    # Normalizar nombres de columnas (BLS usa mayúsculas)
    df.columns = [c.strip().upper() for c in df.columns]

    # Columnas requeridas — nombres posibles según versión BLS
    col_map = {
        'AREA':       ['AREA', 'AREA_CODE'],
        'AREA_TITLE': ['AREA_TITLE', 'AREA_NAME'],
        'OCC_CODE':   ['OCC_CODE'],
        'OCC_TITLE':  ['OCC_TITLE'],
        'TOT_EMP':    ['TOT_EMP'],
        'A_MEAN':     ['A_MEAN'],
        'A_MEDIAN':   ['A_MEDIAN'],
        'A_PCT25':    ['A_PCT25'],
        'A_PCT75':    ['A_PCT75'],
    }
    resolved = {}
    for key, candidates in col_map.items():
        for c in candidates:
            if c in df.columns:
                resolved[key] = c
                break
        if key not in resolved and key in ('AREA', 'OCC_CODE', 'OCC_TITLE'):
            raise ValueError(f"Columna requerida no encontrada: {key}. Columnas disponibles: {list(df.columns)}")

    inserted = skipped = errors = 0

    for _, row in df.iterrows():
        area_code  = str(row.get(resolved.get('AREA', ''), '') or '').strip().zfill(7)
        area_name  = str(row.get(resolved.get('AREA_TITLE', ''), '') or '').strip()
        soc_code   = str(row.get(resolved.get('OCC_CODE', ''), '') or '').strip()
        occ_title  = str(row.get(resolved.get('OCC_TITLE', ''), '') or '').strip()

        if not soc_code or not area_code:
            skipped += 1
            continue
        # Solo ocupaciones detalladas (no grupos: XX-0000)
        if soc_code.endswith('-0000') or soc_code.endswith('0000'):
            skipped += 1
            continue

        a_median = _safe_float(row.get(resolved.get('A_MEDIAN', ''), None))
        a_mean   = _safe_float(row.get(resolved.get('A_MEAN', ''), None))
        a_pct25  = _safe_float(row.get(resolved.get('A_PCT25', ''), None))
        a_pct75  = _safe_float(row.get(resolved.get('A_PCT75', ''), None))
        tot_emp  = _safe_int(row.get(resolved.get('TOT_EMP', ''), None))

        try:
            db.execute(text("""
                INSERT INTO bls_oews_msa
                    (area_code, area_name, area_type, soc_code, occ_title,
                     total_employment, median_annual_usd, mean_annual_usd,
                     pct_25_annual_usd, pct_75_annual_usd, year)
                VALUES (:ac, :an, :at, :sc, :ot, :te, :med, :mean, :p25, :p75, :yr)
                ON CONFLICT (area_code, soc_code, year) DO UPDATE SET
                    median_annual_usd  = EXCLUDED.median_annual_usd,
                    mean_annual_usd    = EXCLUDED.mean_annual_usd,
                    pct_25_annual_usd  = EXCLUDED.pct_25_annual_usd,
                    pct_75_annual_usd  = EXCLUDED.pct_75_annual_usd,
                    total_employment   = EXCLUDED.total_employment,
                    occ_title          = EXCLUDED.occ_title,
                    area_name          = EXCLUDED.area_name,
                    updated_at         = NOW()
            """), {
                'ac': area_code, 'an': area_name,
                'at': _area_type(area_code),
                'sc': soc_code,  'ot': occ_title,
                'te': tot_emp,   'med': a_median,
                'mean': a_mean,  'p25': a_pct25,
                'p75': a_pct75,  'yr': year,
            })
            inserted += 1
            if inserted % 10000 == 0:
                db.commit()
                print(f"  {inserted:,} filas insertadas...")
        except Exception as e:
            errors += 1
            if errors < 5:
                print(f"  ERROR en {soc_code}/{area_code}: {e}")

    db.commit()

    # Estadísticas finales
    stats = db.execute(text("""
        SELECT
            COUNT(*) as total,
            COUNT(DISTINCT soc_code) as occupations,
            COUNT(DISTINCT area_code) as areas,
            COUNT(DISTINCT CASE WHEN area_type='MSA' THEN area_code END) as msas,
            COUNT(DISTINCT CASE WHEN area_type='State' THEN area_code END) as states
        FROM bls_oews_msa
        WHERE year = :yr
    """), {'yr': year}).fetchone()

    return {
        'inserted': inserted,
        'skipped':  skipped,
        'errors':   errors,
        'total_db': stats[0],
        'occupations': stats[1],
        'areas':    stats[2],
        'msas':     stats[3],
        'states':   stats[4],
        'year':     year,
    }


# ── Lookup: salario por SOC + área del usuario ────────────────────────────────

def get_msa_salary(soc_code: str, commune: str, db) -> dict | None:
    """
    Devuelve el salario de una ocupación en el área más cercana a la commune del usuario.
    Estrategia: busca por nombre de ciudad en el MSA_name (substring match).
    """
    if not soc_code or not commune:
        return None

    # Extraer parte útil del commune (ciudad o condado)
    # commune puede ser "94025" (ZIP), "Santa Clara, CA", "Palo Alto", etc.
    search_term = commune.strip()
    # Si es ZIP puro, no podemos hacer substring match directo
    if search_term.isdigit():
        return None

    # Quitar ", CA" / ", NY" etc. para hacer match más amplio
    city = search_term.split(',')[0].strip()

    row = db.execute(text("""
        SELECT area_name, median_annual_usd, mean_annual_usd,
               pct_25_annual_usd, pct_75_annual_usd, area_type
        FROM bls_oews_msa
        WHERE soc_code = :soc
          AND area_name ILIKE :city
          AND median_annual_usd IS NOT NULL
        ORDER BY
            CASE area_type WHEN 'MSA' THEN 1 WHEN 'State' THEN 2 ELSE 3 END
        LIMIT 1
    """), {'soc': soc_code, 'city': f'%{city}%'}).fetchone()

    if row:
        return {
            'area_name':        row[0],
            'median_annual_usd': row[1],
            'mean_annual_usd':   row[2],
            'pct_25_annual_usd': row[3],
            'pct_75_annual_usd': row[4],
            'area_type':         row[5],
        }
    return None


def get_oews_summary(db) -> dict:
    """Resumen de datos en bls_oews_msa."""
    row = db.execute(text("""
        SELECT COUNT(*), COUNT(DISTINCT soc_code), COUNT(DISTINCT area_code),
               MIN(year), MAX(year)
        FROM bls_oews_msa
    """)).fetchone()
    if not row or not row[0]:
        return {'status': 'empty'}

    top = db.execute(text("""
        SELECT area_name, soc_code, occ_title, median_annual_usd
        FROM bls_oews_msa
        WHERE area_type='MSA' AND median_annual_usd IS NOT NULL
        ORDER BY median_annual_usd DESC LIMIT 5
    """)).fetchall()

    return {
        'total_rows':   row[0],
        'occupations':  row[1],
        'areas':        row[2],
        'year_min':     row[3],
        'year_max':     row[4],
        'top_salaries': [{'area': r[0], 'soc': r[1], 'title': r[2], 'median': r[3]} for r in top],
    }
