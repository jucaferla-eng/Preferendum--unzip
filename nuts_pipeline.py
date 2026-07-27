"""
nuts_pipeline.py — Preferendum Regional Income Pipeline
────────────────────────────────────────────────────────
Implementa el esquema diseñado en el handoff de Perplexity (2026-07-27):
  - Tabla `countries`                  — 50 países seed
  - Tabla `regions`                    — regiones NUTS2/3 + equivalentes
  - Tabla `import_batches`             — trazabilidad de cada importación
  - Tabla `regional_income_observations` — datos reales de ingreso por región/año

Fuente primaria: Eurostat nama_10r_2hhinc (B6N BAL EUR_HAB) — NUTS2, EU27+UK
Fuente población: Eurostat demo_r_d2jan — NUTS2, EU27+UK

Cubre 244 regiones NUTS2 con datos reales. Idempotente (ON CONFLICT DO UPDATE).
"""

import json
import urllib.request
from datetime import datetime
from typing import Optional

# ── NUTS prefix → ISO2 (solo 2 excepciones en Eurostat, confirmado en handoff) ─
NUTS_PREFIX_TO_ISO = {
    'AT':'AT','BE':'BE','BG':'BG','CY':'CY','CZ':'CZ',
    'DE':'DE','DK':'DK','EE':'EE','EL':'GR','ES':'ES',
    'FI':'FI','FR':'FR','HR':'HR','HU':'HU','IE':'IE',
    'IT':'IT','LT':'LT','LU':'LU','LV':'LV','MT':'MT',
    'NL':'NL','PL':'PL','PT':'PT','RO':'RO','SE':'SE',
    'SI':'SI','SK':'SK','UK':'GB',
}

# ── 50-country seed (Tier A = Eurostat NUTS, Tier B = fuentes nacionales) ────
COUNTRIES_SEED = [
    # Tier A — EU27 + EFTA + UK + candidatos con acuerdo Eurostat
    ('AT','Austria','EUR','H1'),
    ('BE','Belgium','EUR','H1'),
    ('BG','Bulgaria','BGN','H2'),
    ('CY','Cyprus','EUR','H2'),
    ('CZ','Czechia','CZK','H2'),
    ('DE','Germany','EUR','H1'),
    ('DK','Denmark','DKK','H1'),
    ('EE','Estonia','EUR','H2'),
    ('ES','Spain','EUR','H2'),
    ('FI','Finland','EUR','H1'),
    ('FR','France','EUR','H1'),
    ('GR','Greece','EUR','H2'),
    ('HR','Croatia','EUR','H2'),
    ('HU','Hungary','HUF','H2'),
    ('IE','Ireland','EUR','H1'),
    ('IT','Italy','EUR','H2'),
    ('LT','Lithuania','EUR','H2'),
    ('LU','Luxembourg','EUR','H1'),
    ('LV','Latvia','EUR','H2'),
    ('MT','Malta','EUR','H2'),
    ('NL','Netherlands','EUR','H1'),
    ('PL','Poland','PLN','H2'),
    ('PT','Portugal','EUR','H2'),
    ('RO','Romania','RON','H2'),
    ('SE','Sweden','SEK','H1'),
    ('SI','Slovenia','EUR','H2'),
    ('SK','Slovakia','EUR','H2'),
    ('GB','United Kingdom','GBP','H1'),
    ('NO','Norway','NOK','H1'),
    ('CH','Switzerland','CHF','H1'),
    ('IS','Iceland','ISK','H1'),
    ('LI','Liechtenstein','CHF','H1'),
    ('AL','Albania','ALL','M1'),
    ('BA','Bosnia and Herzegovina','BAM','M1'),
    ('ME','Montenegro','EUR','M1'),
    ('MK','North Macedonia','MKD','M1'),
    ('RS','Serbia','RSD','M1'),
    ('TR','Turkey','TRY','M1'),
    # Tier B — otras fuentes (ISO3166-2 / CUSTOM)
    ('US','United States','USD','H1'),
    ('CA','Canada','CAD','H1'),
    ('JP','Japan','JPY','H1'),
    ('KR','South Korea','KRW','H1'),
    ('AU','Australia','AUD','H1'),
    ('CN','China','CNY','M1'),
    ('IN','India','INR','M2L'),
    ('BR','Brazil','BRL','M1'),
    ('MX','Mexico','MXN','M1'),
    ('ID','Indonesia','IDR','M2L'),
    ('SG','Singapore','SGD','H1'),
    ('AE','United Arab Emirates','AED','H1'),
]

# ── DDL ──────────────────────────────────────────────────────────────────────
DDL = """
CREATE TABLE IF NOT EXISTS rip_countries (
    country_iso   CHAR(2)      PRIMARY KEY,
    country_name  TEXT         NOT NULL,
    currency_iso  CHAR(3)      DEFAULT 'EUR',
    income_group  TEXT         DEFAULT 'H2',
    created_at    TIMESTAMP    DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rip_regions (
    nuts_code             TEXT        PRIMARY KEY,
    nuts_level            SMALLINT    NOT NULL CHECK (nuts_level BETWEEN 0 AND 3),
    region_name           TEXT        NOT NULL,
    region_name_local     TEXT        DEFAULT '',
    country_iso           CHAR(2)     NOT NULL REFERENCES rip_countries(country_iso),
    parent_nuts_code      TEXT        REFERENCES rip_regions(nuts_code),
    classification_system TEXT        DEFAULT 'NUTS2021',
    created_at            TIMESTAMP   DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rip_import_batches (
    batch_id      SERIAL       PRIMARY KEY,
    source_file   TEXT         DEFAULT '',
    created_by    TEXT         DEFAULT 'nuts_pipeline.py',
    started_at    TIMESTAMP    DEFAULT NOW(),
    finished_at   TIMESTAMP,
    status        TEXT         DEFAULT 'running',
    rows_imported INTEGER      DEFAULT 0,
    rows_failed   INTEGER      DEFAULT 0,
    notes         TEXT         DEFAULT ''
);

CREATE TABLE IF NOT EXISTS rip_observations (
    id                   SERIAL    PRIMARY KEY,
    nuts_code            TEXT      NOT NULL REFERENCES rip_regions(nuts_code),
    obs_year             SMALLINT  NOT NULL,
    income_measure       TEXT      NOT NULL DEFAULT 'disposable_income_eur_hab',
    disposable_income    REAL      NOT NULL,
    currency             CHAR(3)   DEFAULT 'EUR',
    population           INTEGER,
    source               TEXT      DEFAULT '',
    batch_id             INTEGER   REFERENCES rip_import_batches(batch_id),
    created_at           TIMESTAMP DEFAULT NOW(),
    UNIQUE (nuts_code, obs_year, income_measure)
);

CREATE INDEX IF NOT EXISTS idx_rip_obs_nuts     ON rip_observations(nuts_code);
CREATE INDEX IF NOT EXISTS idx_rip_obs_year     ON rip_observations(obs_year);
CREATE INDEX IF NOT EXISTS idx_rip_regions_iso  ON rip_regions(country_iso);
"""

# ── Eurostat API ──────────────────────────────────────────────────────────────

def _fetch_eurostat_income() -> dict[str, tuple[str, int, float]]:
    """Descarga ingreso disponible NUTS2 desde Eurostat.
    Retorna {nuts_code: (iso2, year, eur_hab)}
    """
    url = (
        'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'
        'nama_10r_2hhinc?format=JSON&lang=en&unit=EUR_HAB&sinceTimePeriod=2022'
    )
    print('[nuts_pipeline] Descargando ingreso Eurostat...')
    with urllib.request.urlopen(url, timeout=90) as r:
        data = json.loads(r.read())

    dims   = data['dimension']
    size   = data['size']
    values = data['value']

    geo_idx  = dims['geo']['category']['index']
    time_idx = dims['time']['category']['index']

    strides = [1]
    for sz in reversed(size[1:]):
        strides.insert(0, strides[0] * sz)

    d_bal = dims['direct']['category']['index'].get('BAL', 2)
    n_b6n = dims['na_item']['category']['index'].get('B6N', 2)

    best: dict[str, tuple[str, int, float]] = {}
    for geo_code, g_i in geo_idx.items():
        if len(geo_code) != 4:
            continue
        prefix = geo_code[:2]
        if prefix not in NUTS_PREFIX_TO_ISO:
            continue
        iso2 = NUTS_PREFIX_TO_ISO[prefix]
        for yr, t_i in time_idx.items():
            flat = d_bal * strides[2] + n_b6n * strides[3] + g_i * strides[4] + t_i * strides[5]
            val = values.get(str(flat))
            if val is None:
                continue
            prev = best.get(geo_code)
            if prev is None or yr > str(prev[1]):
                best[geo_code] = (iso2, int(yr), float(val))

    print(f'[nuts_pipeline] {len(best)} regiones NUTS2 con ingreso')
    return best


def _fetch_eurostat_population() -> dict[str, tuple[int, int]]:
    """Descarga población por NUTS2 desde Eurostat demo_r_d2jan.
    Retorna {nuts_code: (year, population)}
    """
    url = (
        'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'
        'demo_r_d2jan?format=JSON&lang=en&sex=T&age=TOTAL&sinceTimePeriod=2022'
    )
    print('[nuts_pipeline] Descargando población Eurostat...')
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f'[nuts_pipeline] Población no disponible: {e}')
        return {}

    dims   = data['dimension']
    size   = data['size']
    values = data['value']

    geo_idx  = dims['geo']['category']['index']
    time_idx = dims['time']['category']['index']

    strides = [1]
    for sz in reversed(size[1:]):
        strides.insert(0, strides[0] * sz)

    best: dict[str, tuple[int, int]] = {}
    for geo_code, g_i in geo_idx.items():
        if len(geo_code) != 4:
            continue
        if geo_code[:2] not in NUTS_PREFIX_TO_ISO:
            continue
        for yr, t_i in time_idx.items():
            flat = g_i * strides[-2] + t_i * strides[-1]
            val = values.get(str(flat))
            if val is None:
                continue
            prev = best.get(geo_code)
            if prev is None or yr > str(prev[0]):
                best[geo_code] = (int(yr), int(val))

    print(f'[nuts_pipeline] {len(best)} regiones NUTS2 con población')
    return best


# ── Region names (hardcoded subset, Eurostat labels) ─────────────────────────
def _get_region_name(nuts_code: str, label_data: Optional[dict] = None) -> str:
    if label_data and nuts_code in label_data:
        return label_data[nuts_code]
    return nuts_code  # fallback al código


def _fetch_region_labels() -> dict[str, str]:
    """Descarga etiquetas de regiones NUTS2 desde Eurostat."""
    url = (
        'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'
        'nama_10r_2hhinc?format=JSON&lang=en&unit=EUR_HAB&sinceTimePeriod=2024'
    )
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = json.loads(r.read())
        labels = data['dimension']['geo']['category']['label']
        return {k: v for k, v in labels.items() if len(k) == 4}
    except Exception:
        return {}


# ── Import principal ──────────────────────────────────────────────────────────

def run_nuts_pipeline(db, source: str = 'Eurostat API 2026-07-27') -> dict:
    """
    Pipeline completo:
    1. Crea tablas si no existen
    2. Upsert countries seed
    3. Descarga income + population de Eurostat
    4. Upsert regions
    5. Upsert observations
    6. Registra batch
    """
    from sqlalchemy import text

    # 1. DDL
    for stmt in DDL.strip().split(';'):
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            db.execute(text(stmt))
            db.commit()
        except Exception as e:
            db.rollback()
            if 'already exists' not in str(e).lower():
                print(f'[nuts_pipeline] DDL warning: {e}')

    # 2. Countries seed
    for iso, name, currency, group in COUNTRIES_SEED:
        try:
            db.execute(text("""
                INSERT INTO rip_countries (country_iso, country_name, currency_iso, income_group)
                VALUES (:iso, :name, :cur, :grp)
                ON CONFLICT (country_iso) DO UPDATE
                  SET country_name=excluded.country_name,
                      currency_iso=excluded.currency_iso,
                      income_group=excluded.income_group
            """), {'iso': iso, 'name': name, 'cur': currency, 'grp': group})
        except Exception as e:
            db.rollback()
            print(f'[nuts_pipeline] Country {iso} error: {e}')
    db.commit()
    print(f'[nuts_pipeline] {len(COUNTRIES_SEED)} países seed upserted')

    # 3. Descargar datos Eurostat
    income_data = _fetch_eurostat_income()
    pop_data    = _fetch_eurostat_population()
    labels      = _fetch_region_labels()

    # 4. Batch
    batch_row = db.execute(text("""
        INSERT INTO rip_import_batches (source_file, created_by, status)
        VALUES (:src, 'nuts_pipeline.py', 'running')
        RETURNING batch_id
    """), {'src': source}).fetchone()
    db.commit()
    batch_id = batch_row[0]

    # 5. Upsert regions + observations
    inserted = updated = errors = 0
    for nuts_code, (iso2, year, eur_hab) in income_data.items():
        pop_year, pop_val = pop_data.get(nuts_code, (year, None))
        region_name = labels.get(nuts_code, nuts_code)

        # Upsert region
        try:
            db.execute(text("""
                INSERT INTO rip_regions
                    (nuts_code, nuts_level, region_name, country_iso,
                     classification_system)
                VALUES (:code, 2, :name, :iso, 'NUTS2021')
                ON CONFLICT (nuts_code) DO UPDATE
                  SET region_name=excluded.region_name,
                      country_iso=excluded.country_iso
            """), {'code': nuts_code, 'name': region_name, 'iso': iso2})
        except Exception as e:
            db.rollback()
            errors += 1
            print(f'[nuts_pipeline] Region error {nuts_code}: {e}')
            continue

        # Upsert observation
        try:
            result = db.execute(text("""
                INSERT INTO rip_observations
                    (nuts_code, obs_year, income_measure, disposable_income,
                     currency, population, source, batch_id)
                VALUES (:code, :yr, 'disposable_income_eur_hab', :inc,
                        'EUR', :pop, :src, :bid)
                ON CONFLICT (nuts_code, obs_year, income_measure) DO UPDATE
                  SET disposable_income=excluded.disposable_income,
                      population=excluded.population,
                      source=excluded.source,
                      batch_id=excluded.batch_id,
                      created_at=NOW()
                RETURNING (xmax = 0) AS inserted
            """), {
                'code': nuts_code, 'yr': year, 'inc': eur_hab,
                'pop': pop_val, 'src': source, 'bid': batch_id,
            })
            row = result.fetchone()
            if row and row[0]:
                inserted += 1
            else:
                updated += 1
        except Exception as e:
            db.rollback()
            errors += 1
            print(f'[nuts_pipeline] Obs error {nuts_code}: {e}')

    db.commit()

    # 6. Finalizar batch
    status = 'succeeded' if errors == 0 else ('partial' if inserted + updated > 0 else 'failed')
    db.execute(text("""
        UPDATE rip_import_batches
        SET status=:s, finished_at=NOW(),
            rows_imported=:ri, rows_failed=:rf
        WHERE batch_id=:bid
    """), {'s': status, 'ri': inserted + updated, 'rf': errors, 'bid': batch_id})
    db.commit()

    print(f'[nuts_pipeline] Batch {batch_id}: {inserted} nuevas, {updated} actualizadas, {errors} errores')
    return {
        'ok':       status != 'failed',
        'batch_id': batch_id,
        'status':   status,
        'regions':  len(income_data),
        'inserted': inserted,
        'updated':  updated,
        'errors':   errors,
        'countries': len(set(v[0] for v in income_data.values())),
        'source':   source,
    }


# ── Endpoint helper: summary ──────────────────────────────────────────────────

def get_pipeline_summary(db) -> dict:
    from sqlalchemy import text
    try:
        countries = db.execute(text('SELECT COUNT(*) FROM rip_countries')).scalar()
        regions   = db.execute(text('SELECT COUNT(*) FROM rip_regions')).scalar()
        obs       = db.execute(text('SELECT COUNT(*) FROM rip_observations')).scalar()
        batches   = db.execute(text(
            "SELECT batch_id, status, rows_imported, rows_failed, started_at "
            "FROM rip_import_batches ORDER BY batch_id DESC LIMIT 5"
        )).fetchall()
        top5 = db.execute(text(
            "SELECT r.nuts_code, r.region_name, r.country_iso, o.disposable_income, o.obs_year "
            "FROM rip_observations o JOIN rip_regions r ON o.nuts_code=r.nuts_code "
            "ORDER BY o.disposable_income DESC LIMIT 5"
        )).fetchall()
        return {
            'countries': countries, 'regions': regions, 'observations': obs,
            'recent_batches': [
                {'batch_id': b[0], 'status': b[1], 'imported': b[2],
                 'failed': b[3], 'started': str(b[4])} for b in batches
            ],
            'top5_richest': [
                {'nuts_code': r[0], 'region': r[1], 'country': r[2],
                 'eur_hab': r[3], 'year': r[4]} for r in top5
            ],
        }
    except Exception as e:
        return {'error': str(e)}


if __name__ == '__main__':
    print('=== nuts_pipeline.py — test standalone ===')
    income = _fetch_eurostat_income()
    pop    = _fetch_eurostat_population()
    labels = _fetch_region_labels()

    # Top 5 más ricas
    top5 = sorted(income.items(), key=lambda x: -x[1][2])[:5]
    print('\nTop 5 regiones por ingreso disponible:')
    for code, (iso, yr, eur) in top5:
        name = labels.get(code, code)
        p = pop.get(code, (yr, 0))[1]
        print(f'  {code} ({iso}) | {name[:35]:35} | EUR {eur:,.0f}/hab | pop {p:,}')

    bot5 = sorted(income.items(), key=lambda x: x[1][2])[:5]
    print('\nTop 5 más pobres:')
    for code, (iso, yr, eur) in bot5:
        name = labels.get(code, code)
        print(f'  {code} ({iso}) | {name[:35]:35} | EUR {eur:,.0f}/hab')
