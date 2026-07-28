from __future__ import annotations

"""
ilo_ilostat_agent.py
════════════════════
Descarga salarios reales por grupo ISCO-08 desde ILO ILOSTAT SDMX API.

Dataflow: DF_EAR_EMTM_SEX_OCU_CUR_NB
  = Mean nominal monthly earnings by sex × occupation (ISCO-08), moneda local.

API: https://sdmx.ilo.org/rest/data/ILO,DF_EAR_EMTM_SEX_OCU_CUR_NB,1.0/
Sin API key, acceso público.

Tabla resultante: ilo_wages
  ~70-100 países × 9 grupos ISCO (datos reales, no semillas)
"""

import urllib.request
import xml.etree.ElementTree as ET
from sqlalchemy import text

# ── Dataflow SDMX ─────────────────────────────────────────────────────────────
_SDMX_BASE = (
    'https://sdmx.ilo.org/rest/data/'
    'ILO,DF_EAR_EMTM_SEX_OCU_CUR_NB,1.0/'
)
# Dimensiones SDMX: REF_AREA.FREQ.MEASURE.SEX.OCU.CUR
# Filtramos: SEX_T (ambos), OCU_ISCO08_1-9, CUR_TYPE_LCU (moneda local)
_ISCO_CODES = '+'.join(f'OCU_ISCO08_{i}' for i in range(1, 10))
_KEY = f'{{countries}}.A.EAR_EMTM_NB.SEX_T.{_ISCO_CODES}.CUR_TYPE_LCU'

# ── Países por lote (ILO usa ISO3) ───────────────────────────────────────────
_COUNTRY_BATCHES = [
    # Américas
    'CHL+BRA+MEX+COL+ARG+PER+ECU+URY+BOL+PRY+VEN+PAN+CRI+GTM+HND+NIC+SLV+CAN+DOM+JAM',
    # Europa Occidental
    'DEU+FRA+GBR+ESP+ITA+PRT+NLD+BEL+CHE+AUT+SWE+NOR+DNK+FIN+IRL+GRC+LUX',
    # Europa Oriental
    'POL+CZE+HUN+ROU+BGR+HRV+SVK+SVN+SRB+MKD+MNE+ALB+MDA+UKR+BLR+RUS',
    # Asia Pacífico
    'AUS+NZL+JPN+KOR+SGP+IND+IDN+THA+PHL+MYS+VNM+BGD+PAK+LKA+KHM+NPL+CHN',
    # África y Medio Oriente
    'ZAF+NGA+EGY+KEN+ETH+GHA+TZA+MAR+TUN+DZA+ARE+SAU+ISR+TUR+IRN+JOR+KWT',
    # Asia Central y Cáucaso
    'KAZ+AZE+GEO+ARM+UZB+KGZ+TJK+MNG',
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

# ── FX → USD ──────────────────────────────────────────────────────────────────
_FX_USD: dict[str, float] = {
    'AED': 0.272,  'AFN': 0.0113, 'ALL': 0.0105, 'AMD': 0.00258,
    'ANG': 0.558,  'AOA': 0.00122,'ARS': 0.00111,'AUD': 0.654,
    'AZN': 0.588,  'BAM': 0.551,  'BDT': 0.00909,'BGN': 0.551,
    'BHD': 2.659,  'BND': 0.745,  'BOB': 0.145,  'BRL': 0.200,
    'BYN': 0.312,  'CAD': 0.739,  'CHF': 1.110,  'CLP': 0.00103,
    'CNY': 0.138,  'COP': 0.000244,'CRC': 0.00192,'CZK': 0.0432,
    'DKK': 0.143,  'DOP': 0.0174, 'DZD': 0.00742,'EGP': 0.0206,
    'ETB': 0.0174, 'EUR': 1.083,  'GBP': 1.270,  'GEL': 0.375,
    'GHS': 0.0680, 'GTQ': 0.129,  'HKD': 0.128,  'HNL': 0.0404,
    'HUF': 0.00274,'IDR': 0.0000640,'ILS': 0.272, 'INR': 0.0120,
    'IQD': 0.000763,'IRR': 0.0000238,'ISK': 0.00728,'JMD': 0.00645,
    'JOD': 1.411,  'JPY': 0.00667,'KES': 0.00767,'KGS': 0.0115,
    'KHR': 0.000245,'KRW': 0.000750,'KWD': 3.254, 'KZT': 0.00222,
    'LBP': 0.0000666,'LKR': 0.00309,'MAD': 0.0986,'MDL': 0.0553,
    'MGA': 0.000224,'MKD': 0.0175, 'MMK': 0.000476,'MNT': 0.000296,
    'MXN': 0.0571, 'MYR': 0.213,  'NGN': 0.000649,'NIO': 0.0272,
    'NOK': 0.0938, 'NPR': 0.00750,'NZD': 0.610,  'OMR': 2.597,
    'PAB': 1.000,  'PEN': 0.266,  'PHP': 0.0172, 'PKR': 0.00357,
    'PLN': 0.246,  'PYG': 0.000135,'QAR': 0.275, 'RON': 0.218,
    'RSD': 0.00920,'RUB': 0.0110, 'SAR': 0.267,  'SEK': 0.0948,
    'SGD': 0.745,  'THB': 0.0277, 'TJS': 0.0916, 'TND': 0.321,
    'TRY': 0.0307, 'TTD': 0.148,  'TWD': 0.0314, 'TZS': 0.000386,
    'UAH': 0.0241, 'UGX': 0.000269,'USD': 1.000, 'UYU': 0.0254,
    'UZS': 0.0000790,'VES': 0.0000274,'VND': 0.0000400,'XAF': 0.00165,
    'XOF': 0.00165,'YER': 0.00399,'ZAR': 0.0541, 'ZMW': 0.0398,
    'DOP': 0.0174, 'JMD': 0.00645,
}

# ── ISO3 → ISO2 ───────────────────────────────────────────────────────────────
_ISO3_TO_ISO2: dict[str, str] = {
    'AFG': 'AF', 'ALB': 'AL', 'DZA': 'DZ', 'AGO': 'AO', 'ARG': 'AR',
    'ARM': 'AM', 'AUS': 'AU', 'AUT': 'AT', 'AZE': 'AZ', 'BHS': 'BS',
    'BHR': 'BH', 'BGD': 'BD', 'BLR': 'BY', 'BEL': 'BE', 'BLZ': 'BZ',
    'BEN': 'BJ', 'BTN': 'BT', 'BOL': 'BO', 'BIH': 'BA', 'BWA': 'BW',
    'BRA': 'BR', 'BRN': 'BN', 'BGR': 'BG', 'BFA': 'BF', 'BDI': 'BI',
    'KHM': 'KH', 'CMR': 'CM', 'CAN': 'CA', 'CAF': 'CF', 'TCD': 'TD',
    'CHL': 'CL', 'CHN': 'CN', 'COL': 'CO', 'COD': 'CD', 'COG': 'CG',
    'CRI': 'CR', 'HRV': 'HR', 'CUB': 'CU', 'CYP': 'CY', 'CZE': 'CZ',
    'DNK': 'DK', 'DOM': 'DO', 'ECU': 'EC', 'EGY': 'EG', 'SLV': 'SV',
    'EST': 'EE', 'ETH': 'ET', 'FJI': 'FJ', 'FIN': 'FI', 'FRA': 'FR',
    'GAB': 'GA', 'GEO': 'GE', 'DEU': 'DE', 'GHA': 'GH', 'GRC': 'GR',
    'GTM': 'GT', 'GIN': 'GN', 'GUY': 'GY', 'HTI': 'HT', 'HND': 'HN',
    'HUN': 'HU', 'ISL': 'IS', 'IND': 'IN', 'IDN': 'ID', 'IRN': 'IR',
    'IRQ': 'IQ', 'IRL': 'IE', 'ISR': 'IL', 'ITA': 'IT', 'JAM': 'JM',
    'JPN': 'JP', 'JOR': 'JO', 'KAZ': 'KZ', 'KEN': 'KE', 'KOR': 'KR',
    'KWT': 'KW', 'KGZ': 'KG', 'LAO': 'LA', 'LVA': 'LV', 'LBN': 'LB',
    'LSO': 'LS', 'LBR': 'LR', 'LBY': 'LY', 'LIE': 'LI', 'LTU': 'LT',
    'LUX': 'LU', 'MDG': 'MG', 'MWI': 'MW', 'MYS': 'MY', 'MDV': 'MV',
    'MLI': 'ML', 'MLT': 'MT', 'MRT': 'MR', 'MUS': 'MU', 'MEX': 'MX',
    'MDA': 'MD', 'MNG': 'MN', 'MNE': 'ME', 'MAR': 'MA', 'MOZ': 'MZ',
    'MMR': 'MM', 'NAM': 'NA', 'NPL': 'NP', 'NLD': 'NL', 'NZL': 'NZ',
    'NIC': 'NI', 'NER': 'NE', 'NGA': 'NG', 'MKD': 'MK', 'NOR': 'NO',
    'OMN': 'OM', 'PAK': 'PK', 'PAN': 'PA', 'PNG': 'PG', 'PRY': 'PY',
    'PER': 'PE', 'PHL': 'PH', 'POL': 'PL', 'PRT': 'PT', 'QAT': 'QA',
    'ROU': 'RO', 'RUS': 'RU', 'RWA': 'RW', 'SAU': 'SA', 'SEN': 'SN',
    'SRB': 'RS', 'SLE': 'SL', 'SGP': 'SG', 'SVK': 'SK', 'SVN': 'SI',
    'SOM': 'SO', 'ZAF': 'ZA', 'SSD': 'SS', 'ESP': 'ES', 'LKA': 'LK',
    'SDN': 'SD', 'SUR': 'SR', 'SWE': 'SE', 'CHE': 'CH', 'SYR': 'SY',
    'TJK': 'TJ', 'TZA': 'TZ', 'THA': 'TH', 'TGO': 'TG', 'TTO': 'TT',
    'TUN': 'TN', 'TUR': 'TR', 'TKM': 'TM', 'UGA': 'UG', 'UKR': 'UA',
    'ARE': 'AE', 'GBR': 'GB', 'USA': 'US', 'URY': 'UY', 'UZB': 'UZ',
    'VEN': 'VE', 'VNM': 'VN', 'YEM': 'YE', 'ZMB': 'ZM', 'ZWE': 'ZW',
    'DOM': 'DO', 'JAM': 'JM', 'BLR': 'BY',
}

# País ISO2 → moneda local
_ISO2_CURRENCY: dict[str, str] = {
    'AR': 'ARS', 'AU': 'AUD', 'BR': 'BRL', 'CA': 'CAD', 'CL': 'CLP',
    'CN': 'CNY', 'CO': 'COP', 'CZ': 'CZK', 'DK': 'DKK', 'DO': 'DOP',
    'EG': 'EGP', 'ET': 'ETB', 'GB': 'GBP', 'GH': 'GHS', 'GT': 'GTQ',
    'HN': 'HNL', 'HU': 'HUF', 'ID': 'IDR', 'IN': 'INR', 'IL': 'ILS',
    'JP': 'JPY', 'JM': 'JMD', 'KE': 'KES', 'KG': 'KGS', 'KR': 'KRW',
    'KW': 'KWD', 'KZ': 'KZT', 'MA': 'MAD', 'MX': 'MXN', 'MY': 'MYR',
    'NG': 'NGN', 'NI': 'NIO', 'NO': 'NOK', 'NP': 'NPR', 'NZ': 'NZD',
    'PE': 'PEN', 'PH': 'PHP', 'PK': 'PKR', 'PL': 'PLN', 'PY': 'PYG',
    'RO': 'RON', 'RS': 'RSD', 'RU': 'RUB', 'SA': 'SAR', 'SE': 'SEK',
    'SG': 'SGD', 'TH': 'THB', 'TJ': 'TJS', 'TN': 'TND', 'TR': 'TRY',
    'TZ': 'TZS', 'UA': 'UAH', 'UG': 'UGX', 'US': 'USD', 'UY': 'UYU',
    'UZ': 'UZS', 'VE': 'VES', 'VN': 'VND', 'ZA': 'ZAR', 'ZM': 'ZMW',
    'AZ': 'AZN', 'GE': 'GEL', 'AM': 'AMD', 'BY': 'BYN', 'MD': 'MDL',
    'MN': 'MNT', 'KH': 'KHR', 'MM': 'MMK', 'LK': 'LKR', 'BD': 'BDT',
    # Eurozona
    'AT': 'EUR', 'BE': 'EUR', 'CY': 'EUR', 'EE': 'EUR', 'FI': 'EUR',
    'FR': 'EUR', 'DE': 'EUR', 'GR': 'EUR', 'IE': 'EUR', 'IT': 'EUR',
    'LV': 'EUR', 'LT': 'EUR', 'LU': 'EUR', 'MT': 'EUR', 'NL': 'EUR',
    'PT': 'EUR', 'SK': 'EUR', 'SI': 'EUR', 'ES': 'EUR', 'HR': 'EUR',
    'MK': 'MKD', 'BA': 'BAM', 'RS': 'RSD', 'ME': 'EUR', 'AL': 'ALL',
}

# ── SDMX namespace ────────────────────────────────────────────────────────────
_NS = {
    'gen':  'http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic',
    'msg':  'http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message',
}


# ── Descarga un lote de países ────────────────────────────────────────────────

def _fetch_batch(countries: str) -> list[dict]:
    """Descarga datos SDMX para un grupo de países ISO3 separados por +."""
    key = _KEY.format(countries=countries)
    url = f'{_SDMX_BASE}{key}?startPeriod=2015&detail=dataonly'
    print(f'[ilo_sdmx] Consultando {len(countries.split("+"))} países...')
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (research/data pipeline)',
        'Accept': 'application/xml',
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            xml_bytes = resp.read()
    except Exception as e:
        print(f'[ilo_sdmx] Error en lote: {e}')
        return []

    return _parse_sdmx(xml_bytes)


def _parse_sdmx(xml_bytes: bytes) -> list[dict]:
    """Parsea respuesta SDMX Generic y devuelve lista de dicts."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f'[ilo_sdmx] XML parse error: {e}')
        return []

    # best[iso2][isco_num] = (year, value)
    best: dict[str, dict[int, tuple[int, float]]] = {}

    for series in root.findall('.//gen:Series', _NS):
        key_vals = {v.get('id'): v.get('value')
                    for v in series.findall('gen:SeriesKey/gen:Value', _NS)}

        ref_area = key_vals.get('REF_AREA', '')
        ocu      = key_vals.get('OCU', '')
        sex      = key_vals.get('SEX', '')

        if sex != 'SEX_T':
            continue
        if not ocu.startswith('OCU_ISCO08_'):
            continue
        suffix = ocu.replace('OCU_ISCO08_', '')
        if not suffix.isdigit() or not (1 <= int(suffix) <= 9):
            continue
        isco_num = int(suffix)

        iso2 = _ISO3_TO_ISO2.get(ref_area)
        if not iso2:
            continue

        for obs in series.findall('gen:Obs', _NS):
            period = obs.find('gen:ObsDimension', _NS)
            value  = obs.find('gen:ObsValue', _NS)
            if period is None or value is None:
                continue
            try:
                yr  = int(period.get('value', '0'))
                val = float(value.get('value', '0'))
            except ValueError:
                continue
            if val <= 0:
                continue

            if iso2 not in best:
                best[iso2] = {}
            prev = best[iso2].get(isco_num)
            if prev is None or yr > prev[0]:
                best[iso2][isco_num] = (yr, val)

    rows = []
    for iso2, groups in best.items():
        cur = _ISO2_CURRENCY.get(iso2, '')
        fx  = _FX_USD.get(cur)
        for isco_num, (yr, val) in groups.items():
            rows.append({
                'country_iso2': iso2,
                'country_name': '',
                'isco_group':   isco_num,
                'isco_label':   ISCO_LABELS.get(isco_num, ''),
                'monthly_local': round(val, 2),
                'monthly_usd':   round(val * fx, 2) if fx else None,
                'currency':     cur,
                'year':         yr,
            })
    return rows


# ── DDL ───────────────────────────────────────────────────────────────────────
_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS ilo_wages (
        country_iso2    TEXT NOT NULL,
        country_name    TEXT,
        isco_group      INTEGER NOT NULL,
        isco_label      TEXT,
        monthly_local   REAL,
        monthly_usd     REAL,
        currency        TEXT,
        year            INTEGER,
        source          TEXT DEFAULT 'ILO ILOSTAT DF_EAR_EMTM_SEX_OCU_CUR_NB (SDMX)',
        updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (country_iso2, isco_group)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ilo_wages_iso2 ON ilo_wages(country_iso2)",
    "CREATE INDEX IF NOT EXISTS idx_ilo_wages_isco ON ilo_wages(isco_group)",
]


# ── Import principal ──────────────────────────────────────────────────────────

def run_ilo_import(db) -> dict:
    """Descarga via SDMX e importa datos ILO a ilo_wages."""
    # DDL
    for stmt in _DDL_STATEMENTS:
        try:
            db.execute(text(stmt))
            db.commit()
        except Exception as e:
            db.rollback()
            if 'already exists' not in str(e):
                print(f'[ilo_sdmx] DDL warning: {e}')
    print('[ilo_sdmx] Tabla ilo_wages lista.')

    all_rows: list[dict] = []
    for batch in _COUNTRY_BATCHES:
        rows = _fetch_batch(batch)
        print(f'[ilo_sdmx] Lote: {len(rows)} registros parseados')
        all_rows.extend(rows)

    if not all_rows:
        return {'ok': False, 'error': 'No se obtuvieron datos de ILO SDMX'}

    inserted = errors = 0
    for r in all_rows:
        try:
            db.execute(text("""
                INSERT INTO ilo_wages
                    (country_iso2, country_name, isco_group, isco_label,
                     monthly_local, monthly_usd, currency, year, updated_at)
                VALUES
                    (:iso2, :name, :ig, :il, :ml, :mu, :cur, :yr, CURRENT_TIMESTAMP)
                ON CONFLICT (country_iso2, isco_group) DO UPDATE SET
                    isco_label    = EXCLUDED.isco_label,
                    monthly_local = EXCLUDED.monthly_local,
                    monthly_usd   = EXCLUDED.monthly_usd,
                    currency      = EXCLUDED.currency,
                    year          = EXCLUDED.year,
                    updated_at    = CURRENT_TIMESTAMP
            """), {
                'iso2': r['country_iso2'], 'name': r['country_name'],
                'ig':   r['isco_group'],   'il':   r['isco_label'],
                'ml':   r['monthly_local'],'mu':   r['monthly_usd'],
                'cur':  r['currency'],     'yr':   r['year'],
            })
            inserted += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f'[ilo_sdmx] Insert error {r}: {e}')

    db.commit()

    stats = db.execute(text("""
        SELECT COUNT(*), COUNT(DISTINCT country_iso2), MIN(year), MAX(year)
        FROM ilo_wages
    """)).fetchone()

    countries_done = sorted(set(r['country_iso2'] for r in all_rows))
    print(f'[ilo_sdmx] Import completo: {inserted} filas, {len(countries_done)} países')
    return {
        'ok':       True,
        'inserted': inserted,
        'errors':   errors,
        'total_db': stats[0],
        'countries': stats[1],
        'year_min': stats[2],
        'year_max': stats[3],
        'countries_list': countries_done,
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
    try:
        row = db.execute(text("""
            SELECT COUNT(*), COUNT(DISTINCT country_iso2), MIN(year), MAX(year)
            FROM ilo_wages
        """)).fetchone()
    except Exception:
        return {'status': 'tabla no existe — ejecutar POST /admin/import-ilo-wages'}

    if not row or not row[0]:
        return {'status': 'vacío — ejecutar POST /admin/import-ilo-wages'}

    latam = db.execute(text("""
        SELECT country_iso2, COUNT(*) as grupos
        FROM ilo_wages
        WHERE country_iso2 IN ('CL','BR','MX','CO','AR','PE','EC','UY','BO','PY','VE')
        GROUP BY country_iso2 ORDER BY country_iso2
    """)).fetchall()

    return {
        'total_rows':    row[0],
        'countries':     row[1],
        'year_min':      row[2],
        'year_max':      row[3],
        'latam_coverage': {r[0]: r[1] for r in latam},
    }
