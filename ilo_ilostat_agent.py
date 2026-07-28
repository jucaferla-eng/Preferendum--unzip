from __future__ import annotations

"""
ilo_ilostat_agent.py
════════════════════
Descarga datos reales de salario por ocupación (ISCO-08) de ILO ILOSTAT.

Indicador: EAR_4MTH_SEX_OCU_CUR_NB_A
  = Mean nominal monthly earnings of employees
    by sex × occupation (ISCO-08), en moneda local, frecuencia anual.

Fuente: https://ilostat.ilo.org/data/
Bulk:   https://www.ilo.org/ilostat-files/WEB_bulk_download/indicator/

Tabla resultante: ilo_wages
  ~100 países × 9 grupos ISCO = ~900 filas (datos reales, no semillas)
"""

import gzip
import io
import urllib.request
from sqlalchemy import text

# ── Indicador ILO ────────────────────────────────────────────────────────────
_ILO_INDICATOR = 'EAR_4MTH_SEX_OCU_CUR_NB_A'
_BULK_URL = (
    'https://webapps.ilo.org/ilostat-files/WEB_bulk_download/indicator/'
    f'{_ILO_INDICATOR}.csv.gz'
)

# ── DDL ───────────────────────────────────────────────────────────────────────
_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS ilo_wages (
        id              SERIAL PRIMARY KEY,
        country_iso2    TEXT NOT NULL,
        country_name    TEXT,
        isco_group      INTEGER NOT NULL,
        isco_label      TEXT,
        monthly_local   REAL,
        monthly_usd     REAL,
        currency        TEXT,
        year            INTEGER,
        source          TEXT DEFAULT 'ILO ILOSTAT EAR_4MTH_SEX_OCU_CUR_NB_A',
        updated_at      TIMESTAMP DEFAULT NOW(),
        UNIQUE (country_iso2, isco_group)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ilo_wages_iso2 ON ilo_wages(country_iso2)",
    "CREATE INDEX IF NOT EXISTS idx_ilo_wages_isco ON ilo_wages(isco_group)",
]

# ── ISCO labels ───────────────────────────────────────────────────────────────
ISCO_LABELS = {
    1: 'Managers',
    2: 'Professionals',
    3: 'Technicians & Associate Professionals',
    4: 'Clerical Support Workers',
    5: 'Service & Sales Workers',
    6: 'Agricultural Workers',
    7: 'Craft & Related Trades',
    8: 'Plant & Machine Operators',
    9: 'Elementary Occupations',
}

# ── Tasas de cambio → USD (promedio 2023-2024, para conversión en import) ─────
# Formato: 1 unidad de moneda local = N USD
_FX_USD: dict[str, float] = {
    'AED': 0.272,  'AFN': 0.0113, 'ALL': 0.0105, 'AMD': 0.00258,
    'ANG': 0.558,  'AOA': 0.00122,'ARS': 0.00111,'AUD': 0.654,
    'AWG': 0.559,  'AZN': 0.588,  'BAM': 0.551,  'BBD': 0.500,
    'BDT': 0.00909,'BGN': 0.551,  'BHD': 2.659,  'BMD': 1.000,
    'BND': 0.745,  'BOB': 0.145,  'BRL': 0.200,  'BSD': 1.000,
    'BTN': 0.0120, 'BWP': 0.0744, 'BYN': 0.312,  'BZD': 0.496,
    'CAD': 0.739,  'CDF': 0.000356,'CHF': 1.110, 'CLP': 0.00103,
    'CNY': 0.138,  'COP': 0.000244,'CRC': 0.00192,'CUP': 0.0417,
    'CVE': 0.00919,'CZK': 0.0432, 'DJF': 0.00562,'DKK': 0.143,
    'DOP': 0.0174, 'DZD': 0.00742,'EGP': 0.0206, 'ERN': 0.0667,
    'ETB': 0.0174, 'EUR': 1.083,  'FJD': 0.447,  'GBP': 1.270,
    'GEL': 0.375,  'GHS': 0.0680, 'GMD': 0.0148, 'GNF': 0.000118,
    'GTQ': 0.129,  'GYD': 0.00476,'HKD': 0.128,  'HNL': 0.0404,
    'HRK': 0.144,  'HTG': 0.00758,'HUF': 0.00274,'IDR': 0.0000640,
    'ILS': 0.272,  'INR': 0.0120, 'IQD': 0.000763,'IRR': 0.0000238,
    'ISK': 0.00728,'JMD': 0.00645,'JOD': 1.411,  'JPY': 0.00667,
    'KES': 0.00767,'KGS': 0.0115, 'KHR': 0.000245,'KMF': 0.00220,
    'KPW': 0.00111,'KRW': 0.000750,'KWD': 3.254, 'KYD': 1.199,
    'KZT': 0.00222,'LAK': 0.0000476,'LBP': 0.0000666,'LKR': 0.00309,
    'LRD': 0.00518,'LSL': 0.0541, 'LYD': 0.206,  'MAD': 0.0986,
    'MDL': 0.0553, 'MGA': 0.000224,'MKD': 0.0175,'MMK': 0.000476,
    'MNT': 0.000296,'MOP': 0.124, 'MRU': 0.0250, 'MUR': 0.0213,
    'MVR': 0.0649, 'MWK': 0.000597,'MXN': 0.0571,'MYR': 0.213,
    'MZN': 0.0156, 'NAD': 0.0541, 'NGN': 0.000649,'NIO': 0.0272,
    'NOK': 0.0938, 'NPR': 0.00750,'NZD': 0.610,  'OMR': 2.597,
    'PAB': 1.000,  'PEN': 0.266,  'PGK': 0.267,  'PHP': 0.0172,
    'PKR': 0.00357,'PLN': 0.246,  'PYG': 0.000135,'QAR': 0.275,
    'RON': 0.218,  'RSD': 0.00920,'RUB': 0.0110, 'RWF': 0.000813,
    'SAR': 0.267,  'SBD': 0.118,  'SCR': 0.0735, 'SDG': 0.00169,
    'SEK': 0.0948, 'SGD': 0.745,  'SLL': 0.0000485,'SOS': 0.00175,
    'SRD': 0.0278, 'STN': 0.0443, 'SVC': 0.114,  'SYP': 0.0000793,
    'SZL': 0.0541, 'THB': 0.0277, 'TJS': 0.0916, 'TMT': 0.286,
    'TND': 0.321,  'TOP': 0.425,  'TRY': 0.0307, 'TTD': 0.148,
    'TWD': 0.0314, 'TZS': 0.000386,'UAH': 0.0241,'UGX': 0.000269,
    'USD': 1.000,  'UYU': 0.0254, 'UZS': 0.0000790,'VES': 0.0000274,
    'VND': 0.0000400,'VUV': 0.00836,'WST': 0.363,'XAF': 0.00165,
    'XCD': 0.370,  'XOF': 0.00165,'XPF': 0.00906,'YER': 0.00399,
    'ZAR': 0.0541, 'ZMW': 0.0398, 'ZWL': 0.00311,
}

# ── ILO ref_area → ISO2 ────────────────────────────────────────────────────────
# ILO usa mayormente ISO3; incluimos el subset más relevante con su ISO2
_ILO_TO_ISO2: dict[str, str] = {
    'AFG': 'AF', 'ALB': 'AL', 'DZA': 'DZ', 'AND': 'AD', 'AGO': 'AO',
    'ARG': 'AR', 'ARM': 'AM', 'AUS': 'AU', 'AUT': 'AT', 'AZE': 'AZ',
    'BHS': 'BS', 'BHR': 'BH', 'BGD': 'BD', 'BLR': 'BY', 'BEL': 'BE',
    'BLZ': 'BZ', 'BEN': 'BJ', 'BTN': 'BT', 'BOL': 'BO', 'BIH': 'BA',
    'BWA': 'BW', 'BRA': 'BR', 'BRN': 'BN', 'BGR': 'BG', 'BFA': 'BF',
    'BDI': 'BI', 'CPV': 'CV', 'KHM': 'KH', 'CMR': 'CM', 'CAN': 'CA',
    'CAF': 'CF', 'TCD': 'TD', 'CHL': 'CL', 'CHN': 'CN', 'COL': 'CO',
    'COM': 'KM', 'COD': 'CD', 'COG': 'CG', 'CRI': 'CR', 'CIV': 'CI',
    'HRV': 'HR', 'CUB': 'CU', 'CYP': 'CY', 'CZE': 'CZ', 'DNK': 'DK',
    'DJI': 'DJ', 'DOM': 'DO', 'ECU': 'EC', 'EGY': 'EG', 'SLV': 'SV',
    'GNQ': 'GQ', 'ERI': 'ER', 'EST': 'EE', 'SWZ': 'SZ', 'ETH': 'ET',
    'FJI': 'FJ', 'FIN': 'FI', 'FRA': 'FR', 'GAB': 'GA', 'GMB': 'GM',
    'GEO': 'GE', 'DEU': 'DE', 'GHA': 'GH', 'GRC': 'GR', 'GTM': 'GT',
    'GIN': 'GN', 'GNB': 'GW', 'GUY': 'GY', 'HTI': 'HT', 'HND': 'HN',
    'HUN': 'HU', 'ISL': 'IS', 'IND': 'IN', 'IDN': 'ID', 'IRN': 'IR',
    'IRQ': 'IQ', 'IRL': 'IE', 'ISR': 'IL', 'ITA': 'IT', 'JAM': 'JM',
    'JPN': 'JP', 'JOR': 'JO', 'KAZ': 'KZ', 'KEN': 'KE', 'PRK': 'KP',
    'KOR': 'KR', 'KWT': 'KW', 'KGZ': 'KG', 'LAO': 'LA', 'LVA': 'LV',
    'LBN': 'LB', 'LSO': 'LS', 'LBR': 'LR', 'LBY': 'LY', 'LIE': 'LI',
    'LTU': 'LT', 'LUX': 'LU', 'MDG': 'MG', 'MWI': 'MW', 'MYS': 'MY',
    'MDV': 'MV', 'MLI': 'ML', 'MLT': 'MT', 'MRT': 'MR', 'MUS': 'MU',
    'MEX': 'MX', 'MDA': 'MD', 'MNG': 'MN', 'MNE': 'ME', 'MAR': 'MA',
    'MOZ': 'MZ', 'MMR': 'MM', 'NAM': 'NA', 'NPL': 'NP', 'NLD': 'NL',
    'NZL': 'NZ', 'NIC': 'NI', 'NER': 'NE', 'NGA': 'NG', 'MKD': 'MK',
    'NOR': 'NO', 'OMN': 'OM', 'PAK': 'PK', 'PAN': 'PA', 'PNG': 'PG',
    'PRY': 'PY', 'PER': 'PE', 'PHL': 'PH', 'POL': 'PL', 'PRT': 'PT',
    'QAT': 'QA', 'ROU': 'RO', 'RUS': 'RU', 'RWA': 'RW', 'SAU': 'SA',
    'SEN': 'SN', 'SRB': 'RS', 'SLE': 'SL', 'SGP': 'SG', 'SVK': 'SK',
    'SVN': 'SI', 'SOM': 'SO', 'ZAF': 'ZA', 'SSD': 'SS', 'ESP': 'ES',
    'LKA': 'LK', 'SDN': 'SD', 'SUR': 'SR', 'SWE': 'SE', 'CHE': 'CH',
    'SYR': 'SY', 'TWN': 'TW', 'TJK': 'TJ', 'TZA': 'TZ', 'THA': 'TH',
    'TLS': 'TL', 'TGO': 'TG', 'TON': 'TO', 'TTO': 'TT', 'TUN': 'TN',
    'TUR': 'TR', 'TKM': 'TM', 'UGA': 'UG', 'UKR': 'UA', 'ARE': 'AE',
    'GBR': 'GB', 'USA': 'US', 'URY': 'UY', 'UZB': 'UZ', 'VUT': 'VU',
    'VEN': 'VE', 'VNM': 'VN', 'YEM': 'YE', 'ZMB': 'ZM', 'ZWE': 'ZW',
    # ILO also uses some custom codes
    'XKX': 'XK',  # Kosovo
}

# ── País → moneda local (para conversión FX) ─────────────────────────────────
# Usado cuando ILO no especifica currency en el CSV (ILO siempre usa moneda local)
_ISO2_CURRENCY: dict[str, str] = {
    'AR': 'ARS', 'AU': 'AUD', 'BR': 'BRL', 'CA': 'CAD', 'CL': 'CLP',
    'CN': 'CNY', 'CO': 'COP', 'CZ': 'CZK', 'DK': 'DKK', 'EG': 'EGP',
    'ET': 'ETB', 'GB': 'GBP', 'GH': 'GHS', 'HU': 'HUF', 'ID': 'IDR',
    'IN': 'INR', 'JP': 'JPY', 'KE': 'KES', 'KR': 'KRW', 'MX': 'MXN',
    'MY': 'MYR', 'NG': 'NGN', 'NO': 'NOK', 'NZ': 'NZD', 'PE': 'PEN',
    'PH': 'PHP', 'PK': 'PKR', 'PL': 'PLN', 'RO': 'RON', 'RU': 'RUB',
    'SA': 'SAR', 'SE': 'SEK', 'SG': 'SGD', 'TH': 'THB', 'TR': 'TRY',
    'TZ': 'TZS', 'UA': 'UAH', 'UG': 'UGX', 'US': 'USD', 'UY': 'UYU',
    'VE': 'VES', 'VN': 'VND', 'ZA': 'ZAR', 'ZM': 'ZMW',
    # Euro zone
    'AT': 'EUR', 'BE': 'EUR', 'CY': 'EUR', 'EE': 'EUR', 'FI': 'EUR',
    'FR': 'EUR', 'DE': 'EUR', 'GR': 'EUR', 'IE': 'EUR', 'IT': 'EUR',
    'LV': 'EUR', 'LT': 'EUR', 'LU': 'EUR', 'MT': 'EUR', 'NL': 'EUR',
    'PT': 'EUR', 'SK': 'EUR', 'SI': 'EUR', 'ES': 'EUR', 'HR': 'EUR',
}


# ── Descarga ──────────────────────────────────────────────────────────────────

def download_ilo_csv() -> bytes:
    """Descarga el bulk CSV.GZ de ILO ILOSTAT (~30-80 MB comprimido)."""
    print(f'[ilo_ilostat] Descargando {_BULK_URL} ...')
    req = urllib.request.Request(_BULK_URL, headers={
        'User-Agent': 'Mozilla/5.0 (research/data pipeline)',
        'Accept-Encoding': 'gzip, deflate',
    })
    with urllib.request.urlopen(req, timeout=300) as resp:
        compressed = resp.read()
    print(f'[ilo_ilostat] Descargado: {len(compressed):,} bytes comprimidos')
    return compressed


# ── Parseo ────────────────────────────────────────────────────────────────────

def parse_ilo_csv(compressed: bytes) -> list[dict]:
    """
    Parsea el CSV.GZ de ILO y devuelve lista de dicts listos para DB.
    Filtra: sex=SEX_T, classif1=OCU_ISCO08_1-9, valor no nulo.
    Toma el año más reciente por (country, isco_group).
    """
    import csv

    raw_csv = gzip.decompress(compressed).decode('utf-8', errors='replace')
    reader = csv.DictReader(io.StringIO(raw_csv))

    # country+isco → {year, value, currency, country_name}
    best: dict[tuple, dict] = {}

    for row in reader:
        sex = row.get('sex', '').strip()
        if sex not in ('SEX_T', 'T'):
            continue

        classif1 = row.get('classif1', '').strip()
        # Acepta OCU_ISCO08_1 … OCU_ISCO08_9
        isco_num = None
        for prefix in ('OCU_ISCO08_', 'ISCO08_', 'OCU_ISCO_08_'):
            if classif1.startswith(prefix):
                suffix = classif1[len(prefix):]
                if suffix.isdigit() and 1 <= int(suffix) <= 9:
                    isco_num = int(suffix)
                break
        if isco_num is None:
            continue

        val_str = row.get('obs_value', '').strip()
        if not val_str or val_str in ('', 'nan', 'NA', 'N/A'):
            continue
        try:
            val = float(val_str)
        except ValueError:
            continue
        if val <= 0:
            continue

        # Omitir filas con obs_status que indica dato no confiable
        status = row.get('obs_status', '').strip()
        if status in ('B', 'P', 'U'):  # break, preliminary, unreliable
            continue

        ref_area = row.get('ref_area', '').strip()
        iso2 = _ILO_TO_ISO2.get(ref_area)
        if not iso2:
            continue

        try:
            year = int(row.get('time', '0').strip())
        except ValueError:
            continue

        country_name = row.get('ref_area.label', '').strip()

        # Moneda: ILO a veces tiene columna 'currency'; si no, usamos dict
        currency = (row.get('currency', '') or '').strip() or _ISO2_CURRENCY.get(iso2, '')

        key = (iso2, isco_num)
        prev = best.get(key)
        if prev is None or year > prev['year']:
            best[key] = {
                'country_iso2': iso2,
                'country_name': country_name,
                'isco_group':   isco_num,
                'isco_label':   ISCO_LABELS.get(isco_num, ''),
                'monthly_local': round(val, 2),
                'currency':     currency,
                'year':         year,
            }

    # Agregar conversión USD
    rows = []
    for (iso2, isco_num), d in best.items():
        cur = d['currency']
        fx  = _FX_USD.get(cur)
        d['monthly_usd'] = round(d['monthly_local'] * fx, 2) if fx else None
        rows.append(d)

    print(f'[ilo_ilostat] Parseado: {len(rows)} filas ({len(set(r["country_iso2"] for r in rows))} países)')
    return rows


# ── Import a DB ───────────────────────────────────────────────────────────────

def run_ilo_import(db, compressed: bytes | None = None) -> dict:
    """
    Crea tabla ilo_wages e importa datos ILO.
    Si compressed es None, descarga automáticamente.
    """
    # DDL — ejecutar cada sentencia por separado
    for stmt in _DDL_STATEMENTS:
        try:
            db.execute(text(stmt))
            db.commit()
        except Exception as e:
            db.rollback()
            if 'already exists' not in str(e):
                print(f'[ilo_ilostat] DDL warning: {e}')
    print('[ilo_ilostat] Tabla ilo_wages lista.')

    if compressed is None:
        compressed = download_ilo_csv()

    rows = parse_ilo_csv(compressed)
    if not rows:
        return {'ok': False, 'error': 'No data parsed from ILO CSV'}

    inserted = updated = errors = 0
    for r in rows:
        try:
            db.execute(text("""
                INSERT INTO ilo_wages
                    (country_iso2, country_name, isco_group, isco_label,
                     monthly_local, monthly_usd, currency, year, updated_at)
                VALUES
                    (:iso2, :name, :ig, :il, :ml, :mu, :cur, :yr, NOW())
                ON CONFLICT (country_iso2, isco_group) DO UPDATE SET
                    country_name  = EXCLUDED.country_name,
                    isco_label    = EXCLUDED.isco_label,
                    monthly_local = EXCLUDED.monthly_local,
                    monthly_usd   = EXCLUDED.monthly_usd,
                    currency      = EXCLUDED.currency,
                    year          = EXCLUDED.year,
                    updated_at    = NOW()
            """), {
                'iso2': r['country_iso2'],
                'name': r['country_name'],
                'ig':   r['isco_group'],
                'il':   r['isco_label'],
                'ml':   r['monthly_local'],
                'mu':   r['monthly_usd'],
                'cur':  r['currency'],
                'yr':   r['year'],
            })
            inserted += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f'[ilo_ilostat] Error {r["country_iso2"]} ISCO{r["isco_group"]}: {e}')

    db.commit()

    stats = db.execute(text("""
        SELECT COUNT(*), COUNT(DISTINCT country_iso2), MIN(year), MAX(year)
        FROM ilo_wages
    """)).fetchone()

    return {
        'ok':       True,
        'inserted': inserted,
        'errors':   errors,
        'total_db': stats[0],
        'countries': stats[1],
        'year_min': stats[2],
        'year_max': stats[3],
    }


# ── Lookup para _assign_user_tier ─────────────────────────────────────────────

def get_ilo_income(country_iso2: str, isco_group: int, db) -> dict | None:
    """
    Devuelve ingreso mensual en USD y score (0-100) relativo dentro del país.
    Score 100 = grupo ISCO mejor pagado del país, 0 = peor pagado.
    Retorna None si no hay datos ILO para ese país/grupo.
    """
    row = db.execute(text("""
        SELECT monthly_usd FROM ilo_wages
        WHERE country_iso2 = :iso2 AND isco_group = :ig
    """), {'iso2': country_iso2, 'ig': isco_group}).fetchone()

    if not row or not row[0]:
        return None

    monthly_usd = float(row[0])

    # Ranking relativo dentro del país
    all_vals = db.execute(text("""
        SELECT monthly_usd FROM ilo_wages
        WHERE country_iso2 = :iso2 AND monthly_usd IS NOT NULL
        ORDER BY monthly_usd
    """), {'iso2': country_iso2}).fetchall()

    if len(all_vals) < 2:
        score = 50.0
    else:
        vals = [float(r[0]) for r in all_vals]
        mn, mx = min(vals), max(vals)
        score = round(100.0 * (monthly_usd - mn) / (mx - mn), 1) if mx > mn else 50.0

    return {
        'monthly_usd':   monthly_usd,
        'annual_usd':    round(monthly_usd * 12, 0),
        'score':         score,
        'isco_group':    isco_group,
    }


def get_ilo_summary(db) -> dict:
    """Resumen de datos en ilo_wages."""
    row = db.execute(text("""
        SELECT COUNT(*), COUNT(DISTINCT country_iso2), MIN(year), MAX(year)
        FROM ilo_wages
    """)).fetchone()
    if not row or not row[0]:
        return {'status': 'empty — ejecutar /admin/import-ilo-wages'}

    top = db.execute(text("""
        SELECT country_iso2, isco_group, isco_label, monthly_usd, year
        FROM ilo_wages
        WHERE monthly_usd IS NOT NULL
        ORDER BY monthly_usd DESC LIMIT 5
    """)).fetchall()

    latam = db.execute(text("""
        SELECT country_iso2, isco_group, monthly_usd, year
        FROM ilo_wages
        WHERE country_iso2 IN ('CL','BR','MX','CO','AR','PE','VE','EC','UY','BO','PY')
          AND monthly_usd IS NOT NULL
        ORDER BY country_iso2, isco_group
    """)).fetchall()

    return {
        'total_rows':   row[0],
        'countries':    row[1],
        'year_min':     row[2],
        'year_max':     row[3],
        'top_earners':  [{'country': r[0], 'isco': r[1], 'title': r[2],
                          'monthly_usd': r[3], 'year': r[4]} for r in top],
        'latam_rows':   len(latam),
    }
