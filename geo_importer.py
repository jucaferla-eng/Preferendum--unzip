"""
geo_importer.py — PREFERENDUM
Reusable, source-driven importer for the geo_countries / geo_units
authoritative geography registry (STEP 6 / 6A / 6B).

Never embeds geography data in Python source — every source adapter reads
from a real file (local path, or freshly downloaded to a temp path),
streamed row by row. Adding a new source means writing one new
`parse_<source>()` generator with the same row shape; the transactional
validate/install logic below (`import_country_geography`) is source-agnostic
and is shared by every source.

Currently implements one verified source adapter: Eurostat GISCO LAU 2024
(gisco-services.ec.europa.eu/distribution/v2/lau/csv/LAU_RG_01M_2024_4326.csv).
Chile's existing geography (chile_geography.py, SUBDERE) is a separate,
already-working path from an earlier phase and is untouched by this file.
"""

import csv
import hashlib
import os
import tempfile
import urllib.request
from datetime import datetime, date

import openpyxl


class GeoImportError(Exception):
    """Raised before any database write when a country's source data
    fails validation (duplicate source_unit_id, or row count mismatch
    against the authoritative expected count). `report` carries the
    full diagnostic detail."""
    def __init__(self, report):
        self.report = report
        super().__init__(report.get('error', 'geo import validation failed'))


# ══════════════════════════════════════════════════════════════
# SOURCE ADAPTER — Eurostat GISCO LAU 2024
# ══════════════════════════════════════════════════════════════

EUROSTAT_LAU_URL           = "https://gisco-services.ec.europa.eu/distribution/v2/lau/csv/LAU_RG_01M_2024_4326.csv"
EUROSTAT_LAU_SOURCE_NAME   = "Eurostat GISCO LAU 2024"
EUROSTAT_LAU_SOURCE_URL    = "https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/local-administrative-units"
EUROSTAT_LAU_SOURCE_VERSION = "GISCO-LAU-2024"
EUROSTAT_LAU_SOURCE_DATE   = date(2024, 1, 1)
EUROSTAT_LAU_UNIT_LEVEL    = "LAU (commune/municipality)"

# Authoritative per-country unit counts, read directly from the live
# GISCO CSV itself (never guessed) — the validation target each country's
# import is checked against. Verified 2026-09-29 by counting CNTR_CODE
# occurrences in the real downloaded file (34 countries total in the
# file; these 29 are the ones Preferendum currently supports).
EUROSTAT_LAU_EXPECTED_COUNTS = {
    'LV': 43, 'LT': 60, 'MT': 68, 'EE': 79, 'DK': 99, 'LU': 100, 'IE': 166,
    'SI': 212, 'BG': 265, 'SE': 290, 'FI': 309, 'NL': 342, 'NO': 357,
    'HR': 556, 'BE': 581, 'CY': 615, 'AT': 2093, 'CH': 2180, 'PL': 2477,
    'SK': 2927, 'PT': 3092, 'HU': 3155, 'RO': 3181, 'CZ': 6258, 'GR': 6142,
    'IT': 7900, 'ES': 8132, 'DE': 10978, 'FR': 34946,
}

EUROSTAT_LAU_COUNTRY_NAMES = {
    'LV': 'Latvia', 'LT': 'Lithuania', 'MT': 'Malta', 'EE': 'Estonia',
    'DK': 'Denmark', 'LU': 'Luxembourg', 'IE': 'Ireland', 'SI': 'Slovenia',
    'BG': 'Bulgaria', 'SE': 'Sweden', 'FI': 'Finland', 'NL': 'Netherlands',
    'NO': 'Norway', 'HR': 'Croatia', 'BE': 'Belgium', 'CY': 'Cyprus',
    'AT': 'Austria', 'CH': 'Switzerland', 'PL': 'Poland', 'SK': 'Slovakia',
    'PT': 'Portugal', 'HU': 'Hungary', 'RO': 'Romania', 'CZ': 'Czechia',
    'GR': 'Greece', 'IT': 'Italy', 'ES': 'Spain', 'DE': 'Germany', 'FR': 'France',
}


def _fetch_eurostat_lau_csv(dest_path=None):
    """Downloads the real source file to a local path (temp file by
    default). Returns the path. Never holds the file in memory as a
    Python literal."""
    if dest_path is None:
        fd, dest_path = tempfile.mkstemp(suffix='_lau2024.csv')
        os.close(fd)
    urllib.request.urlretrieve(EUROSTAT_LAU_URL, dest_path)
    return dest_path


def parse_eurostat_lau(csv_path, countries):
    """Streams (country_code, source_unit_id, unit_name, admin1_id,
    admin1_name, admin2_id, admin2_name, population) tuples for the
    requested countries only, one CSV row at a time — never loads the
    whole ~98k-row file into a single Python list/dict.

    admin1_id/admin1_name/admin2_id/admin2_name are always None for this
    source: the actual downloaded file's columns are exactly
    GISCO_ID, CNTR_CODE, LAU_NAME, POP_2024, POP_DENS_2024, AREA_KM2, YEAR
    (verified directly against the live file — no hierarchy column
    exists). A row-level LAU<->NUTS correspondence dataset was searched
    for (STEP 6B: Eurostat's own "correspondence tables" page was
    checked, and its one downloadable file was opened and confirmed to
    contain only 111 rows of country-level SUMMARY counts, not row-level
    mapping; the linked TERCET service has no discoverable public API
    documentation) and was not found as a verifiable, row-level,
    downloadable dataset. Per policy, the fields are left NULL here
    rather than invented or inferred from the name."""
    countries = {c.upper() for c in countries}
    with open(csv_path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cc = row['CNTR_CODE']
            if cc not in countries:
                continue
            pop = row.get('POP_2024')
            try:
                pop_int = int(float(pop)) if pop not in (None, '', 'NA') else None
            except ValueError:
                pop_int = None
            yield (cc, row['GISCO_ID'], row['LAU_NAME'], None, None, None, None, pop_int)


# ══════════════════════════════════════════════════════════════
# SOURCE-AGNOSTIC VALIDATE + ATOMIC INSTALL
# ══════════════════════════════════════════════════════════════

def import_country_geography(db, GeoCountry, GeoUnit, country_code, rows, *,
                              source_name, source_url, source_date, source_version,
                              local_unit_level, expected_count, norm_fn,
                              country_name=None, dry_run=False):
    """Validate + atomically install ONE country's geography.

    `GeoCountry`/`GeoUnit` — the real ORM model classes, injected by the
    caller (main.py) rather than imported here, so this module has no
    hard dependency on main.py's heavy import chain and can be tested
    standalone against any SQLAlchemy session.

    `rows` — iterable of (country_code, source_unit_id, unit_name,
    admin1_id, admin1_name, admin2_id, admin2_name, population) —
    typically the output of a parse_<source>() generator, already
    filtered to this country.

    `norm_fn` — the app's existing normalization function
    (eligibility.norm_commune), injected, never reimplemented here.

    Raises GeoImportError, with NO database write of any kind (dry_run
    or not), when:
      - the same source_unit_id appears more than once for this country
        (duplicate NAMES are explicitly allowed and are NOT an error);
      - the parsed row count does not exactly equal `expected_count`
        (the authoritative source's own published total).

    dry_run=True: runs every validation step and returns the full report
    — including `would_write` — WITHOUT opening a transaction or issuing
    any DELETE/INSERT/UPDATE.

    Idempotent + never mixes source versions: on a real (non-dry-run)
    install, every existing geo_units row for this country_code is
    deleted and the freshly parsed set is inserted, in ONE transaction.
    Re-running with identical source data yields an identical end state
    (same rows, same IDs) — never accumulates duplicates on rerun. Since
    the delete always fully clears the prior version's rows before the
    new version's rows are inserted, in the same transaction, a
    country's geo_units can never be a silent blend of two source
    versions — it is always exactly one version's data, or (if the
    transaction fails) the previous version's data, untouched.

    `GeoCountry.geography_status` is set to 'implemented' — and
    unit_count/source_name/source_url/source_date/updated_at are
    written — ONLY inside this same transaction, ONLY after validation
    has already passed. A country whose import fails validation keeps
    whatever GeoCountry state it had before this call ran.
    """
    country_code = country_code.upper()
    parsed = []
    seen_ids = set()
    dup_ids = set()
    for r in rows:
        cc, source_unit_id, unit_name, a1id, a1name, a2id, a2name, population = r
        if cc != country_code:
            continue
        if source_unit_id in seen_ids:
            dup_ids.add(source_unit_id)
        seen_ids.add(source_unit_id)
        parsed.append((cc, source_unit_id, unit_name, norm_fn(unit_name),
                        a1id, a1name, a2id, a2name, population))

    # True only if the source actually gave a real admin1 for at least
    # one parsed row — computed from the data itself, never hand-set, so
    # it can never overstate what the source provides. Computed once,
    # reused both in the (dry-run or real) report and, on a real write,
    # for the GeoCountry row below.
    hierarchy_available = any(a1id or a1name for _cc, _sid, _n, _nn, a1id, a1name, _a2id, _a2name, _pop in parsed)

    report = {
        'country_code': country_code,
        'parsed_count': len(parsed),
        'expected_count': expected_count,
        'duplicate_source_unit_ids': sorted(dup_ids),
        'hierarchy_available': hierarchy_available,
        'dry_run': dry_run,
        'ok': False,
    }

    if dup_ids:
        report['error'] = (f'{country_code}: {len(dup_ids)} duplicate source_unit_id(s) '
                            f'found — import aborted, no database write performed')
        raise GeoImportError(report)

    if len(parsed) != expected_count:
        report['error'] = (f'{country_code}: parsed {len(parsed)} rows, expected '
                            f'{expected_count} (authoritative source total) — '
                            f'import aborted, no database write performed')
        raise GeoImportError(report)

    existing_country = db.query(GeoCountry).filter(GeoCountry.country_code == country_code).first()
    existing_unit_count = db.query(GeoUnit).filter(GeoUnit.country_code == country_code).count()
    report['existing_unit_count_before'] = existing_unit_count
    report['existing_geography_status_before'] = existing_country.geography_status if existing_country else None

    if dry_run:
        report['ok'] = True
        report['would_write'] = len(parsed)
        report['would_delete_existing'] = existing_unit_count
        return report

    try:
        db.query(GeoUnit).filter(GeoUnit.country_code == country_code).delete()
        for cc, source_unit_id, unit_name, unit_name_norm, a1id, a1name, a2id, a2name, population in parsed:
            db.add(GeoUnit(
                country_code=cc, source_unit_id=source_unit_id, unit_name=unit_name,
                unit_name_norm=unit_name_norm, admin1_id=a1id, admin1_name=a1name,
                admin2_id=a2id, admin2_name=a2name, population=population,
                source_version=source_version,
            ))

        if existing_country:
            existing_country.country_name     = country_name or existing_country.country_name
            existing_country.local_unit_level = local_unit_level
            existing_country.source_name      = source_name
            existing_country.source_url       = source_url
            existing_country.source_date      = source_date
            existing_country.geography_status = 'implemented'
            existing_country.unit_count       = len(parsed)
            existing_country.hierarchy_available = hierarchy_available
            existing_country.updated_at       = datetime.utcnow()
        else:
            db.add(GeoCountry(
                country_code=country_code, country_name=country_name or country_code,
                local_unit_level=local_unit_level, source_name=source_name,
                source_url=source_url, source_date=source_date,
                geography_status='implemented', unit_count=len(parsed),
                hierarchy_available=hierarchy_available,
                updated_at=datetime.utcnow(),
            ))

        db.commit()
    except Exception:
        db.rollback()
        raise

    report['ok'] = True
    report['written'] = len(parsed)
    return report


def import_eurostat_lau_countries(db, GeoCountry, GeoUnit, norm_fn, countries,
                                   csv_path=None, dry_run=False):
    """Orchestrates import_country_geography() for a batch of countries
    from the Eurostat LAU source, reading the (possibly large) CSV file
    exactly once regardless of how many countries are requested.

    `csv_path` — a local file to parse (e.g. for tests / offline runs);
    if omitted, the real source file is downloaded fresh to a temp path.

    Returns a list of per-country report dicts (see
    import_country_geography). One country's validation failure does
    NOT prevent the others in the same call from being attempted — each
    has its own independent transaction — but a failure is never
    swallowed silently: it's recorded in that country's report with
    ok=False and the exception is re-raised after all countries in the
    batch have been attempted, so a caller always learns about it.
    """
    countries = [c.upper() for c in countries]
    owns_temp_file = csv_path is None
    if csv_path is None:
        csv_path = _fetch_eurostat_lau_csv()
    try:
        rows_by_country = {cc: [] for cc in countries}
        for row in parse_eurostat_lau(csv_path, countries):
            rows_by_country[row[0]].append(row)

        reports = []
        errors = []
        for cc in countries:
            expected = EUROSTAT_LAU_EXPECTED_COUNTS.get(cc)
            if expected is None:
                reports.append({'country_code': cc, 'ok': False,
                                 'error': f'{cc} has no verified expected_count in EUROSTAT_LAU_EXPECTED_COUNTS — refusing to import an unverified country'})
                errors.append(cc)
                continue
            try:
                r = import_country_geography(
                    db, GeoCountry, GeoUnit, cc, rows_by_country[cc],
                    source_name=EUROSTAT_LAU_SOURCE_NAME, source_url=EUROSTAT_LAU_SOURCE_URL,
                    source_date=EUROSTAT_LAU_SOURCE_DATE, source_version=EUROSTAT_LAU_SOURCE_VERSION,
                    local_unit_level=EUROSTAT_LAU_UNIT_LEVEL, expected_count=expected,
                    norm_fn=norm_fn, country_name=EUROSTAT_LAU_COUNTRY_NAMES.get(cc),
                    dry_run=dry_run,
                )
                reports.append(r)
            except GeoImportError as e:
                reports.append(e.report)
                errors.append(cc)

        if errors:
            raise GeoImportError({'batch_errors': errors, 'reports': reports})
        return reports
    finally:
        if owns_temp_file:
            try:
                os.remove(csv_path)
            except OSError:
                pass


# ══════════════════════════════════════════════════════════════
# NUTS HIERARCHY ENRICHMENT — STEP 9
# ══════════════════════════════════════════════════════════════
# This section NEVER creates, deletes, or renames a GeoUnit. Geographic
# identity comes exclusively from import_country_geography() above (the
# locked GISCO CSV + source_unit_id). Everything below only UPDATEs
# nuts1/nuts2/nuts3 code+name on GeoUnit rows that already exist, joined
# strictly by (country_code, source_unit_id) — i.e. by the same
# authoritative ID the geography import itself assigned. A country must
# already be geography_status='implemented' before it can be enriched.
#
# STEP 8B found that Eurostat's LAU<->NUTS3 correspondence table
# (unlike the locked GISCO CSV our importer validates against a fixed
# expected_count) is a LIVE, continuously-corrected file — its own
# File_info sheet showed corrections weeks apart, and its Last-Modified
# header has been within a day of the request in this session. So unlike
# the geography import, enrichment never silently downloads a fresh copy
# by default: the caller must hand in an explicit local file path for
# both the correspondence workbook and the NUTS code->name workbook, and
# every enrichment call/report records the exact SHA-256 of both files it
# read (see hierarchy_correspondence_sha256 / hierarchy_nuts_names_sha256
# on GeoCountry) — so a hierarchy refresh is always a distinct, visible,
# auditable action, never a byproduct of re-running the geography import.

EUROSTAT_LAU_NUTS_CORRESPONDENCE_URL = (
    "https://ec.europa.eu/eurostat/documents/345175/501971/"
    "EU-27-LAU-2024-NUTS-2024.xlsx/12971f56-c035-dbab-4d9f-ff1dcc617bb3?t=1737036272863"
)
EUROSTAT_LAU_NUTS_CORRESPONDENCE_SOURCE_NAME = "Eurostat LAU 2024 <-> NUTS 2024 correspondence (EU-27-LAU-2024-NUTS-2024.xlsx)"
EUROSTAT_LAU_NUTS_CORRESPONDENCE_LANDING_PAGE = "https://ec.europa.eu/eurostat/web/nuts/local-administrative-units"

EUROSTAT_NUTS_NAMES_URL = (
    "https://ec.europa.eu/eurostat/documents/345175/629341/"
    "NUTS2021-NUTS2024.xlsx/2b35915f-9c14-6841-8197-353408c4522d?t=1717505289640"
)
EUROSTAT_NUTS_NAMES_SOURCE_NAME = "Eurostat NUTS 2024 nomenclature (NUTS2021-NUTS2024.xlsx, 'NUTS2024' sheet)"
EUROSTAT_NUTS_NAMES_LANDING_PAGE = "https://ec.europa.eu/eurostat/web/nuts/database"

# The correspondence workbook uses Eurostat's own sheet-name convention,
# which differs from our EUROSTAT_LAU_EXPECTED_COUNTS ISO-alpha-2 keys in
# exactly one case verified so far (STEP 8B): Greece is sheet 'EL', not 'GR'.
_NUTS_SHEET_COUNTRY_CODE = {'GR': 'EL'}


class HierarchyEnrichmentError(Exception):
    """Raised before any database write when hierarchy enrichment can't
    proceed safely — e.g. the target country isn't geography_status=
    'implemented' yet, or the correspondence data itself is internally
    inconsistent (same source_unit_id mapped to two different NUTS3
    codes). `report` carries full diagnostic detail. Never raised for a
    merely partial match — an incomplete join is reported, not fatal,
    since it can never corrupt geographic identity (enrichment only ever
    UPDATEs existing rows' nuts* columns)."""
    def __init__(self, report):
        self.report = report
        super().__init__(report.get('error', 'hierarchy enrichment validation failed'))


def sha256_file(path):
    """SHA-256 of a local file, streamed — used to record exactly which
    version of a (possibly mutable, upstream-changing) source file an
    enrichment run actually read."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def parse_nuts_2024_names(xlsx_path):
    """Reads the 'NUTS2024' sheet of the NUTS code<->name workbook.
    Returns {nuts_code: label} covering every NUTS1/2/3 code, for every
    country in the file — loaded once, reusable across countries."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb['NUTS2024']
    names = {}
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        code, label = row[1], row[2]
        if code:
            names[code] = label
    return names


def parse_lau_nuts_correspondence(xlsx_path, country_code):
    """Reads one country's sheet from the LAU<->NUTS correspondence
    workbook. Yields (source_unit_id, nuts3_code) — source_unit_id is the
    'EU LAU CODE' column, the SAME identifier format/value as the GISCO
    CSV's GISCO_ID (verified 1:1-identical for LU and PT in STEP 8B), so
    it joins directly against GeoUnit.source_unit_id with no translation."""
    country_code = country_code.upper()
    sheet_name = _NUTS_SHEET_COUNTRY_CODE.get(country_code, country_code)
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    if sheet_name not in wb.sheetnames:
        raise HierarchyEnrichmentError({
            'country_code': country_code,
            'error': f"{country_code}: no sheet '{sheet_name}' found in correspondence workbook — "
                     f"available sheets: {wb.sheetnames}",
        })
    ws = wb[sheet_name]
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        nuts3, eu_lau_code = row[0], row[2]
        if eu_lau_code is None:
            continue
        yield (eu_lau_code, nuts3)


def enrich_country_hierarchy(db, GeoCountry, GeoUnit, country_code, correspondence_rows, nuts_names, *,
                              correspondence_source_name, correspondence_source_url, correspondence_sha256,
                              nuts_names_source_name, nuts_names_source_url, nuts_names_sha256,
                              dry_run=False):
    """Source-agnostic NUTS hierarchy enrichment for ONE already-imported
    country. Never creates, deletes, or renames a GeoUnit — only updates
    nuts1/nuts2/nuts3 code+name on rows that already exist, matched
    strictly by (country_code, source_unit_id).

    `correspondence_rows` — iterable of (source_unit_id, nuts3_code),
    typically parse_lau_nuts_correspondence()'s output, already scoped to
    this country's sheet.

    `nuts_names` — {nuts_code: label} dict from parse_nuts_2024_names(),
    used to resolve NUTS1/2/3 codes to real official names. NUTS2/NUTS1
    codes are derived from NUTS3 by truncation (NUTS3 code length 5 ->
    NUTS2 length 4 -> NUTS1 length 3 -> country code length 2), per
    Eurostat's own nesting convention, then looked up in this same dict
    — never invented.

    Requires the country to already be geography_status='implemented'
    (raises HierarchyEnrichmentError otherwise, no write). A source_unit_id
    that exists in GeoUnit but has no correspondence entry is reported as
    unmatched and simply keeps its nuts* fields NULL — never treated as
    fatal, since it cannot corrupt geographic identity. A correspondence
    entry mapping the same source_unit_id to two different NUTS3 codes
    IS fatal (internally inconsistent source data) and aborts with no
    write, exactly like import_country_geography's duplicate-ID check.

    dry_run=True performs every validation/join step and returns the
    full report — including would-be match counts — without opening a
    transaction or writing anything.

    On a real write: one transaction updates every matched GeoUnit row
    plus GeoCountry.nuts_hierarchy_available/hierarchy_source_name/
    hierarchy_source_url/hierarchy_correspondence_sha256/
    hierarchy_nuts_names_sha256/hierarchy_updated_at. Idempotent — rerun
    with the same inputs produces the same end state (UPDATE, not
    INSERT)."""
    country_code = country_code.upper()

    existing_country = db.query(GeoCountry).filter(GeoCountry.country_code == country_code).first()
    if not existing_country or existing_country.geography_status != 'implemented':
        report = {
            'country_code': country_code,
            'error': f"{country_code}: geography_status is "
                     f"{existing_country.geography_status if existing_country else 'unresolved (no GeoCountry row)'}"
                     f" — a country must be 'implemented' via import_country_geography() before its hierarchy "
                     f"can be enriched. No write performed.",
            'ok': False,
        }
        raise HierarchyEnrichmentError(report)

    existing_units = {u.source_unit_id: u for u in
                       db.query(GeoUnit).filter(GeoUnit.country_code == country_code).all()}

    correspondence_map = {}
    conflicting = {}
    for source_unit_id, nuts3_code in correspondence_rows:
        if source_unit_id in correspondence_map and correspondence_map[source_unit_id] != nuts3_code:
            conflicting[source_unit_id] = (correspondence_map[source_unit_id], nuts3_code)
        correspondence_map[source_unit_id] = nuts3_code

    if conflicting:
        report = {
            'country_code': country_code,
            'error': f"{country_code}: {len(conflicting)} source_unit_id(s) map to conflicting NUTS3 codes "
                     f"in the correspondence data — internally inconsistent source, aborting with no write",
            'conflicting_source_unit_ids': dict(list(conflicting.items())[:20]),
            'ok': False,
        }
        raise HierarchyEnrichmentError(report)

    matched = {}
    unmatched_unit_ids = []
    for sid in existing_units:
        nuts3 = correspondence_map.get(sid)
        if nuts3:
            matched[sid] = nuts3
        else:
            unmatched_unit_ids.append(sid)

    correspondence_ids_not_in_geounit = sorted(set(correspondence_map) - set(existing_units))

    name_unresolved = set()
    resolved = {}
    for sid, nuts3 in matched.items():
        nuts2 = nuts3[:4]
        nuts1 = nuts3[:3]
        n3name, n2name, n1name = nuts_names.get(nuts3), nuts_names.get(nuts2), nuts_names.get(nuts1)
        for code, name in ((nuts3, n3name), (nuts2, n2name), (nuts1, n1name)):
            if name is None:
                name_unresolved.add(code)
        resolved[sid] = (nuts3, n3name, nuts2, n2name, nuts1, n1name)

    report = {
        'country_code': country_code,
        'existing_geounit_count': len(existing_units),
        'matched_count': len(matched),
        'unmatched_geounit_source_ids': unmatched_unit_ids[:20],
        'unmatched_geounit_count': len(unmatched_unit_ids),
        'correspondence_ids_not_in_geounit_count': len(correspondence_ids_not_in_geounit),
        'correspondence_ids_not_in_geounit_sample': correspondence_ids_not_in_geounit[:20],
        'nuts_codes_with_no_resolvable_name': sorted(name_unresolved),
        'correspondence_source_name': correspondence_source_name,
        'correspondence_sha256': correspondence_sha256,
        'nuts_names_source_name': nuts_names_source_name,
        'nuts_names_sha256': nuts_names_sha256,
        'dry_run': dry_run,
        'ok': False,
    }

    if dry_run:
        report['ok'] = True
        report['would_update'] = len(matched)
        return report

    try:
        for sid, (nuts3, n3name, nuts2, n2name, nuts1, n1name) in resolved.items():
            unit = existing_units[sid]
            unit.nuts3_code, unit.nuts3_name = nuts3, n3name
            unit.nuts2_code, unit.nuts2_name = nuts2, n2name
            unit.nuts1_code, unit.nuts1_name = nuts1, n1name

        existing_country.nuts_hierarchy_available = len(matched) > 0
        existing_country.hierarchy_source_name = f"{correspondence_source_name} + {nuts_names_source_name}"
        existing_country.hierarchy_source_url = correspondence_source_url or nuts_names_source_url
        existing_country.hierarchy_correspondence_sha256 = correspondence_sha256
        existing_country.hierarchy_nuts_names_sha256 = nuts_names_sha256
        existing_country.hierarchy_updated_at = datetime.utcnow()

        db.commit()
    except Exception:
        db.rollback()
        raise

    report['ok'] = True
    report['updated'] = len(matched)
    return report


def enrich_country_hierarchy_from_files(db, GeoCountry, GeoUnit, country_code,
                                         correspondence_xlsx_path, nuts_names_xlsx_path, dry_run=False):
    """Convenience wrapper: reads both local xlsx files (NO default
    auto-download — both paths are required — see the module-level note
    above on why hierarchy refreshes are never silent/implicit), computes
    their SHA-256, parses them, and calls enrich_country_hierarchy()."""
    correspondence_sha256 = sha256_file(correspondence_xlsx_path)
    nuts_names_sha256 = sha256_file(nuts_names_xlsx_path)
    nuts_names = parse_nuts_2024_names(nuts_names_xlsx_path)
    correspondence_rows = list(parse_lau_nuts_correspondence(correspondence_xlsx_path, country_code))
    return enrich_country_hierarchy(
        db, GeoCountry, GeoUnit, country_code, correspondence_rows, nuts_names,
        correspondence_source_name=EUROSTAT_LAU_NUTS_CORRESPONDENCE_SOURCE_NAME,
        correspondence_source_url=EUROSTAT_LAU_NUTS_CORRESPONDENCE_LANDING_PAGE,
        correspondence_sha256=correspondence_sha256,
        nuts_names_source_name=EUROSTAT_NUTS_NAMES_SOURCE_NAME,
        nuts_names_source_url=EUROSTAT_NUTS_NAMES_LANDING_PAGE,
        nuts_names_sha256=nuts_names_sha256,
        dry_run=dry_run,
    )
