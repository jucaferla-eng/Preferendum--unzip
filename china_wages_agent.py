from __future__ import annotations
"""
china_wages_agent.py — China wage data import + lookup para Preferendum
========================================================================
Fuentes:
  1. china_wage_schema/real_data/china_wage_real_2024.csv
     → NBS datos oficiales por provincia × categoría ocupacional (esquema Perplexity)
  2. Datos hardcoded de msadvisory.com + wagecentre.com (2024-2025)
     → 60 cargos específicos con CNY/mes + grupo ISCO

Tablas:
  - china_wages      — geografía × occupation_category (NBS oficial)
  - china_wage_jobs  — cargo × isco_group × CNY/mes (scraping)

Conversión: se usa tasa PPP (FMI/Banco Mundial) en vez de tasa nominal.
  Nominal:  1 USD = 7.23 RMB  → no refleja poder adquisitivo real
  PPP:      1 USD = 3.29 RMB  → equivalencia de compra real (×2.2x el nominal)
  Fuente: Análisis_Salarios_China_vs_USA_PPP.docx (Perplexity, 2025)
"""

import csv
from pathlib import Path
from sqlalchemy import text

CNY_TO_USD_NOMINAL = 1 / 7.23   # solo para referencia
CNY_TO_USD_PPP     = 1 / 3.29   # usado para estimated_income_usd en tier system

# ── DDL ───────────────────────────────────────────────────────────────────────

DDL_WAGES = """
CREATE TABLE IF NOT EXISTS china_wages (
    id                    SERIAL PRIMARY KEY,
    admin_code            TEXT NOT NULL,
    admin_level           INTEGER NOT NULL,
    region_name_en        TEXT,
    region_name_zh        TEXT,
    macro_region          TEXT,
    occupation_category   TEXT,
    avg_annual_wage_cny   REAL,
    avg_annual_wage_usd_nominal REAL,
    avg_annual_wage_usd_ppp     REAL,
    year                  INTEGER,
    wage_measure          TEXT,
    data_availability     TEXT,
    source                TEXT,
    UNIQUE(admin_code, year, occupation_category, wage_measure)
);
CREATE INDEX IF NOT EXISTS idx_china_wages_code ON china_wages(admin_code);
CREATE INDEX IF NOT EXISTS idx_china_wages_occ  ON china_wages(occupation_category);
"""

DDL_JOBS = """
CREATE TABLE IF NOT EXISTS china_wage_jobs (
    id               SERIAL PRIMARY KEY,
    job_title        TEXT NOT NULL,
    isco_group       INTEGER NOT NULL,
    monthly_cny_min  REAL,
    monthly_cny_max  REAL,
    monthly_cny_avg  REAL NOT NULL,
    monthly_usd_nominal REAL,
    monthly_usd_ppp     REAL,
    annual_usd_ppp      REAL,
    source           TEXT,
    year             INTEGER DEFAULT 2024,
    UNIQUE(job_title, year)
);
CREATE INDEX IF NOT EXISTS idx_china_jobs_isco ON china_wage_jobs(isco_group);
"""

# ── ISCO → NBS occupation_category ───────────────────────────────────────────

_ISCO_TO_NBS = {
    1: 'Middle management and above',
    2: 'Professional and technical personnel',
    3: 'Professional and technical personnel',
    4: 'Office staff and related personnel',
    5: 'Personnel engaged in social production services and life services',
    6: 'Personnel engaged in production and manufacturing',
    7: 'Personnel engaged in production and manufacturing',
    8: 'Personnel engaged in production and manufacturing',
    9: 'Personnel engaged in production and manufacturing',
}

# NBS anual nacional por categoría (enterprises above designated size, 2024)
# Fuente: stats.gov.cn — usado para score relativo (0-100)
_NBS_NATIONAL_CNY = {
    'Middle management and above':                                           203014,
    'Professional and technical personnel':                                  148046,
    'Office staff and related personnel':                                     93189,
    'Personnel engaged in social production services and life services':      77584,
    'Personnel engaged in production and manufacturing':                      78561,
    'Total':                                                                 102452,
}

# ── Ciudad → código provincia GB/T 2260 ──────────────────────────────────────

_CITY_TO_PROVINCE = {
    'beijing':        '110000',
    'shanghai':       '310000',
    'tianjin':        '120000',
    'chongqing':      '500000',
    'guangzhou':      '440000',
    'shenzhen':       '440000',
    'zhuhai':         '440000',
    'dongguan':       '440000',
    'foshan':         '440000',
    'hangzhou':       '330000',
    'ningbo':         '330000',
    'wenzhou':        '330000',
    'nanjing':        '320000',
    'suzhou':         '320000',
    'wuxi':           '320000',
    'wuhan':          '420000',
    'chengdu':        '510000',
    'mianyang':       '510000',
    "xi'an":          '610000',
    'xian':           '610000',
    'shenyang':       '210000',
    'dalian':         '210000',
    'qingdao':        '370000',
    'jinan':          '370000',
    'zhengzhou':      '410000',
    'changsha':       '430000',
    'harbin':         '230000',
    'hefei':          '340000',
    'nanchang':       '360000',
    'fuzhou':         '350000',
    'xiamen':         '350000',
    'kunming':        '530000',
    'nanning':        '450000',
    'guiyang':        '520000',
    'lanzhou':        '620000',
    'urumqi':         '650000',
    'hohhot':         '150000',
    'yinchuan':       '640000',
    'xining':         '630000',
    'lhasa':          '540000',
    'taiyuan':        '140000',
    'shijiazhuang':   '130000',
    'changchun':      '220000',
    'haikou':         '460000',
    'sanya':          '460000',
}

# ── Datos de cargos específicos ───────────────────────────────────────────────
# (job_title, isco_group, monthly_cny_min, monthly_cny_max, monthly_cny_avg)

_JOBS = [
    # Fuente: wagecentre.com (valores exactos)
    ('Chip Engineer',                          2,   None,    None,  26000),
    ('Senior Manager',                         1,   None,    None,  22739),
    ('Artificial Intelligence Engineer',       2,   None,    None,  21701),
    ('Investment/Finance Manager',             1,   None,    None,  16899),
    ('Software Developer',                     2,   None,    None,  16891),
    ('Communications & Hardware R&D',          2,   None,    None,  16507),
    ('Mobile R&D Specialist',                  2,   None,    None,  15646),
    ('Automotive Electronics Engineer',        2,   None,    None,  15437),
    ('Securities Broker',                      3,   None,    None,  14498),
    ('Data Engineer',                          2,   None,    None,  14318),
    # Fuente: msadvisory.com (rango → punto medio)
    ('Surgeon',                                2,  50000,  100000,  75000),
    ('Investment Banker',                      2,  40000,   80000,  60000),
    ('Data Scientist',                         2,  30000,   60000,  45000),
    ('Pilot',                                  3,  30000,   60000,  45000),
    ('Marketing Director',                     1,  30000,   60000,  45000),
    ('IT Manager',                             1,  25000,   50000,  37500),
    ('Lawyer',                                 2,  25000,   50000,  37500),
    ('Software Engineer',                      2,  20000,   40000,  30000),
    ('Project Manager',                        1,  20000,   40000,  30000),
    ('Doctor',                                 2,  20000,   40000,  30000),
    ('Sales Manager',                          1,  20000,   40000,  30000),
    ('Business Development Manager',           1,  20000,   40000,  30000),
    ('Operations Manager',                     1,  20000,   40000,  30000),
    ('Supply Chain Manager',                   1,  20000,   40000,  30000),
    ('Product Manager',                        1,  20000,   40000,  30000),
    ('Architect',                              2,  15000,   30000,  22500),
    ('University Professor',                   2,  15000,   30000,  22500),
    ('Pharmacist',                             2,  15000,   30000,  22500),
    ('HR Manager',                             1,  15000,   30000,  22500),
    ('Financial Analyst',                      2,  15000,   30000,  22500),
    ('Hotel Manager',                          1,  15000,   30000,  22500),
    ('Real Estate Agent',                      3,  15000,   30000,  22500),
    ('Digital Marketing Specialist',           2,  15000,   30000,  22500),
    ('Research Scientist',                     2,  15000,   30000,  22500),
    ('UX/UI Designer',                         3,  15000,   30000,  22500),
    ('Social Media Manager',                   3,  15000,   30000,  22500),
    ('PR Specialist',                          3,  15000,   30000,  22500),
    ('Civil Engineer',                         2,  10000,   20000,  15000),
    ('Mechanical Engineer',                    2,  10000,   20000,  15000),
    ('Electrical Engineer',                    2,  10000,   20000,  15000),
    ('Accountant',                             2,  10000,   20000,  15000),
    ('Customer Service Manager',               1,  10000,   20000,  15000),
    ('Chef',                                   5,  10000,   20000,  15000),
    ('Flight Attendant',                       5,  10000,   20000,  15000),
    ('QA Engineer',                            3,  10000,   20000,  15000),
    ('Environmental Engineer',                 2,  10000,   20000,  15000),
    ('Event Planner',                          3,  10000,   20000,  15000),
    ('Executive Assistant',                    4,  10000,   20000,  15000),
    ('Warehouse Manager',                      1,  10000,   20000,  15000),
    ('Procurement Specialist',                 3,  10000,   20000,  15000),
    ('Journalist',                             2,   8000,   15000,  11500),
    ('Nurse',                                  3,   8000,   15000,  11500),
    ('Graphic Designer',                       3,   8000,   15000,  11500),
    ('Translator',                             3,   8000,   15000,  11500),
    ('Content Writer',                         3,   8000,   15000,  11500),
    ('Logistics Coordinator',                  3,   8000,   15000,  11500),
    ('Sales Representative',                   5,   8000,   15000,  11500),
    ('Teacher',                                2,   6000,   12000,   9000),
    ('Administrative Assistant',               4,   6000,   12000,   9000),
    ('Customer Support Specialist',            4,   6000,   12000,   9000),
]

# ── Import CSV ────────────────────────────────────────────────────────────────

def _import_csv(db) -> dict:
    csv_path = Path(__file__).parent / 'china_wage_schema' / 'real_data' / 'china_wage_real.csv'
    if not csv_path.exists():
        return {'error': f'CSV no encontrado: {csv_path}'}

    inserted = skipped = 0
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            wage_raw = (row.get('avg_annual_wage_cny') or '').strip()
            if not wage_raw:
                skipped += 1
                continue
            try:
                wage_cny = float(wage_raw)
            except ValueError:
                skipped += 1
                continue

            db.execute(text("""
                INSERT INTO china_wages
                    (admin_code, admin_level, region_name_en, region_name_zh,
                     macro_region, occupation_category,
                     avg_annual_wage_cny, avg_annual_wage_usd_nominal, avg_annual_wage_usd_ppp,
                     year, wage_measure, data_availability, source)
                VALUES
                    (:code, :level, :name_en, :name_zh,
                     :macro, :occ,
                     :cny, :usd_nom, :usd_ppp,
                     :year, :measure, :avail, :src)
                ON CONFLICT (admin_code, year, occupation_category, wage_measure) DO UPDATE SET
                    avg_annual_wage_cny         = EXCLUDED.avg_annual_wage_cny,
                    avg_annual_wage_usd_nominal = EXCLUDED.avg_annual_wage_usd_nominal,
                    avg_annual_wage_usd_ppp     = EXCLUDED.avg_annual_wage_usd_ppp
            """), {
                'code':    row.get('admin_code', '').strip(),
                'level':   int(row.get('admin_level') or 0),
                'name_en': row.get('region_name_en', '').strip(),
                'name_zh': row.get('region_name_zh', '').strip(),
                'macro':   row.get('macro_region', '').strip() or None,
                'occ':     row.get('occupation_category', '').strip() or None,
                'cny':     wage_cny,
                'usd_nom': round(wage_cny * CNY_TO_USD_NOMINAL, 2),
                'usd_ppp': round(wage_cny * CNY_TO_USD_PPP, 2),
                'year':    int(row.get('year') or 2024),
                'measure': row.get('wage_measure', '').strip() or None,
                'avail':   row.get('data_availability', '').strip() or None,
                'src':     row.get('source', '').strip() or None,
            })
            inserted += 1

    db.commit()
    return {'csv_inserted': inserted, 'csv_skipped': skipped}


def _import_jobs(db) -> dict:
    inserted = 0
    for title, isco, min_cny, max_cny, avg_cny in _JOBS:
        monthly_nom = round(avg_cny * CNY_TO_USD_NOMINAL, 2)
        monthly_ppp = round(avg_cny * CNY_TO_USD_PPP, 2)
        annual_ppp  = round(monthly_ppp * 12, 2)
        db.execute(text("""
            INSERT INTO china_wage_jobs
                (job_title, isco_group, monthly_cny_min, monthly_cny_max,
                 monthly_cny_avg, monthly_usd_nominal, monthly_usd_ppp, annual_usd_ppp,
                 source, year)
            VALUES
                (:title, :isco, :min, :max, :avg, :nom, :ppp, :annual, :src, 2024)
            ON CONFLICT (job_title, year) DO UPDATE SET
                isco_group          = EXCLUDED.isco_group,
                monthly_cny_avg     = EXCLUDED.monthly_cny_avg,
                monthly_usd_nominal = EXCLUDED.monthly_usd_nominal,
                monthly_usd_ppp     = EXCLUDED.monthly_usd_ppp,
                annual_usd_ppp      = EXCLUDED.annual_usd_ppp
        """), {
            'title': title, 'isco': isco,
            'min': min_cny, 'max': max_cny, 'avg': avg_cny,
            'nom': monthly_nom, 'ppp': monthly_ppp, 'annual': annual_ppp,
            'src': 'msadvisory.com+wagecentre.com 2024',
        })
        inserted += 1
    db.commit()
    return {'jobs_inserted': inserted}


def _assimilate_to_occupation_salary(db) -> dict:
    """
    Inserta datos China en occupation_salary (tabla compartida del tier system).
    Mapea las 5 categorías NBS a los 9 grupos ISCO usando datos nacionales 2024.
    PPP-adjusted: median_monthly_usd usa tasa 3.29 CNY/USD.
    """
    # Datos NBS nacional 2024 (enterprises above designated size)
    # Fuente: stats.gov.cn — annual CNY → monthly CNY → monthly USD PPP
    _NBS_ISCO_MAP = [
        # (isco_group, annual_cny, label)
        (1, 203014, 'Managers / Directivos'),
        (2, 148046, 'Professionals / Profesionales'),
        (3, 118437, 'Technicians / Técnicos'),        # estimado: 80% del ISCO-2
        (4,  93189, 'Clerical / Admin'),
        (5,  77584, 'Services & Sales / Servicios'),
        (6,  78561, 'Agricultural / Agrícola'),
        (7,  78561, 'Craft trades / Artesanos'),
        (8,  78561, 'Machine operators / Operadores'),
        (9,  55000, 'Elementary / Ocupaciones básicas'),  # estimado desde mínimo
    ]

    max_annual = 203014.0  # directivos nacionales = score 100
    inserted = 0

    # Asegurar que occupation_salary existe
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS occupation_salary (
            id                   SERIAL PRIMARY KEY,
            country_iso          TEXT NOT NULL,
            isco_group           INTEGER NOT NULL,
            isco_label           TEXT DEFAULT '',
            median_monthly_local REAL,
            median_monthly_usd   REAL,
            currency             TEXT DEFAULT '',
            profession_score     REAL DEFAULT 0,
            year                 INTEGER,
            source               TEXT DEFAULT '',
            updated_at           TIMESTAMP DEFAULT NOW(),
            UNIQUE (country_iso, isco_group)
        )
    """))
    db.commit()

    for isco, annual_cny, label in _NBS_ISCO_MAP:
        monthly_cny = round(annual_cny / 12, 2)
        monthly_ppp = round(monthly_cny * CNY_TO_USD_PPP, 2)
        score       = round(annual_cny / max_annual * 100, 1)

        db.execute(text("""
            INSERT INTO occupation_salary
                (country_iso, isco_group, isco_label, median_monthly_local,
                 median_monthly_usd, currency, profession_score, year, source, updated_at)
            VALUES
                ('CN', :isco, :label, :local, :usd, 'CNY', :score, 2024,
                 'NBS China 2024 (PPP-adjusted, stats.gov.cn)', NOW())
            ON CONFLICT (country_iso, isco_group) DO UPDATE SET
                isco_label           = EXCLUDED.isco_label,
                median_monthly_local = EXCLUDED.median_monthly_local,
                median_monthly_usd   = EXCLUDED.median_monthly_usd,
                profession_score     = EXCLUDED.profession_score,
                year                 = EXCLUDED.year,
                source               = EXCLUDED.source,
                updated_at           = NOW()
        """), {
            'isco':  isco,
            'label': label,
            'local': monthly_cny,
            'usd':   monthly_ppp,
            'score': score,
        })
        inserted += 1

    db.commit()
    return {'occupation_salary_cn_rows': inserted}


def run_china_wages_import(db) -> dict:
    db.execute(text(DDL_WAGES))
    db.execute(text(DDL_JOBS))
    db.commit()
    csv_r    = _import_csv(db)
    jobs_r   = _import_jobs(db)
    occ_r    = _assimilate_to_occupation_salary(db)
    return {**csv_r, **jobs_r, **occ_r, 'status': 'ok'}

# ── Lookup ────────────────────────────────────────────────────────────────────

def _resolve_province(city: str) -> str | None:
    """Nombre de ciudad → código provincia GB/T 2260."""
    if not city:
        return None
    return _CITY_TO_PROVINCE.get(city.strip().lower())


def get_china_income(city: str | None, isco_group: int, db) -> dict | None:
    """
    Retorna ingreso estimado PPP para usuario en China.

    Estrategia:
      1. Intenta por provincia (ciudad → código provincia) en china_wages
      2. Si no hay dato provincial, usa CN-NAT (nacional)
      3. annual_usd usa tasa PPP — para comparar con usuarios de otros países
         en términos de poder de compra real.
    """
    nbs_cat = _ISCO_TO_NBS.get(isco_group)
    if not nbs_cat:
        return None

    province_code = _resolve_province(city or '')
    candidates = []
    if province_code:
        candidates.append(province_code)
    candidates.append('CN-NAT')

    for code in candidates:
        row = db.execute(text("""
            SELECT avg_annual_wage_cny,
                   avg_annual_wage_usd_nominal,
                   avg_annual_wage_usd_ppp,
                   region_name_en,
                   data_availability
            FROM china_wages
            WHERE admin_code = :code
              AND occupation_category = :occ
              AND wage_measure = 'enterprises above designated size'
            ORDER BY year DESC
            LIMIT 1
        """), {'code': code, 'occ': nbs_cat}).fetchone()

        if row and row[0]:
            annual_cny  = row[0]
            annual_nom  = row[1] or round(annual_cny * CNY_TO_USD_NOMINAL, 2)
            annual_ppp  = row[2] or round(annual_cny * CNY_TO_USD_PPP, 2)
            # Score relativo a directivos nacionales (techo = 203,014 CNY/año)
            max_cny = float(_NBS_NATIONAL_CNY.get('Middle management and above', 203014))
            score   = min(100, round(annual_cny / max_cny * 100))
            return {
                'region':           row[3],
                'nbs_category':     nbs_cat,
                'annual_cny':       annual_cny,
                'annual_usd':       annual_ppp,       # PPP — usado en estimated_income_usd
                'annual_usd_nominal': annual_nom,     # nominal — solo referencia
                'monthly_usd':      round(annual_ppp / 12, 2),
                'score':            score,
                'source':           'NBS official (PPP-adjusted)',
                'level':            row[4],
            }

    return None


def get_china_summary(db) -> dict:
    w = db.execute(text("""
        SELECT COUNT(*), COUNT(DISTINCT admin_code),
               COUNT(DISTINCT occupation_category)
        FROM china_wages
    """)).fetchone()
    j = db.execute(text("""
        SELECT COUNT(*), COUNT(DISTINCT isco_group),
               MIN(monthly_cny_avg), MAX(monthly_cny_avg)
        FROM china_wage_jobs
    """)).fetchone()
    return {
        'wages_rows':         w[0] if w else 0,
        'wages_regions':      w[1] if w else 0,
        'wages_occ_cats':     w[2] if w else 0,
        'jobs_rows':          j[0] if j else 0,
        'jobs_isco_groups':   j[1] if j else 0,
        'jobs_min_cny_month': j[2] if j else 0,
        'jobs_max_cny_month': j[3] if j else 0,
        'ppp_rate':           '1 USD = 3.29 CNY (FMI/Banco Mundial)',
        'nominal_rate':       '1 USD = 7.23 CNY',
    }
