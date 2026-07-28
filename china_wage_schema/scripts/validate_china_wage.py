#!/usr/bin/env python3
"""
validate_china_wage.py -- standalone validator for the China regional-wage CSV
standard (province / prefecture-level city / county-district, GB/T 2260 codes,
plus NBS's macro-region and occupation-category aggregates).

No third-party dependencies -- stdlib only (csv, re, sys, argparse, json).

Usage:
    python3 validate_china_wage.py <input.csv> [--report out.json] [--export-clean clean.csv]

Exit codes:
    0 = no fatal (header) errors -- row-level findings may still exist
    1 = fatal header/structure error, nothing was validated
"""
import argparse
import csv
import json
import re
import sys

REQUIRED_COLUMNS = ["admin_code", "admin_level", "region_name_en", "country_iso", "year"]
ALL_COLUMNS = [
    "admin_code", "admin_level", "region_name_en", "region_name_zh", "country_iso",
    "macro_region", "occupation_category", "avg_annual_wage_cny", "year", "population",
    "parent_admin_code", "classification_system", "wage_measure", "data_availability",
    "source", "last_updated",
]

MACRO_CODES = {"CN-NAT", "CN-E", "CN-C", "CN-W", "CN-NE"}
MACRO_REGIONS = {"Eastern", "Central", "Western", "Northeastern"}
OCCUPATION_CATEGORIES = {
    "Total",
    "Middle management and above",
    "Professional and technical personnel",
    "Office staff and related personnel",
    "Personnel engaged in social production services and life services",
    "Personnel engaged in production and manufacturing",
}
WAGE_MEASURES = {"urban non-private units", "urban private units", "enterprises above designated size"}
DATA_AVAILABILITY = {"national", "macro_region", "province", "prefecture", "county_district", "not_available"}
CLASSIFICATION_SYSTEMS = {"GB_T_2260", "GB_T_2260_MACRO"}

# GB/T 2260 codes are ALWAYS 6 digits. Level is encoded by trailing zeros:
#   province level (1):    XX0000  (first 2 digits meaningful)
#   prefecture level (2):  XXYY00  (first 4 digits meaningful)
#   county/district (3):   XXYYZZ  (all 6 digits meaningful)
CODE_RE = {
    1: re.compile(r"^\d{2}0000$"),
    2: re.compile(r"^\d{4}00$"),
    3: re.compile(r"^\d{6}$"),
}


def _add(findings, severity, row_num, field, message):
    findings.append({"row": row_num, "severity": severity, "field": field, "message": message})


def validate_file(path, mode="china"):
    findings = []
    clean_records = []

    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            missing = [c for c in REQUIRED_COLUMNS if c not in header]
            if missing:
                _add(findings, "FATAL", 0, "header", f"Missing required column(s): {missing}")
                return findings, [], {}

            rows = list(reader)
    except FileNotFoundError:
        _add(findings, "FATAL", 0, "file", f"File not found: {path}")
        return findings, [], {}
    except csv.Error as e:
        _add(findings, "FATAL", 0, "file", f"CSV parse error: {e}")
        return findings, [], {}

    codes_by_level = {1: {}, 2: {}, 3: {}}  # code -> row_num, for hierarchy pass
    seen_keys = {}

    for i, row in enumerate(rows, start=2):  # row 1 is header
        row_ok = True
        code = (row.get("admin_code") or "").strip()
        level_raw = (row.get("admin_level") or "").strip()
        country = (row.get("country_iso") or "").strip()
        year_raw = (row.get("year") or "").strip()

        if not code:
            _add(findings, "ERROR", i, "admin_code", "admin_code is required")
            row_ok = False
        if not level_raw:
            _add(findings, "ERROR", i, "admin_level", "admin_level is required")
            row_ok = False
        else:
            try:
                level = int(level_raw)
                if level not in (0, 1, 2, 3):
                    _add(findings, "ERROR", i, "admin_level", f"admin_level must be 0-3, got {level}")
                    row_ok = False
            except ValueError:
                _add(findings, "ERROR", i, "admin_level", f"admin_level must be an integer, got '{level_raw}'")
                row_ok = False
                level = None

        if country and country != "CN":
            _add(findings, "ERROR", i, "country_iso", f"This schema is China-only; got country_iso='{country}'")
            row_ok = False

        if year_raw:
            try:
                year = int(year_raw)
                if not (1990 <= year <= 2100):
                    _add(findings, "WARNING", i, "year", f"Unusual year value: {year}")
            except ValueError:
                _add(findings, "ERROR", i, "year", f"year must be an integer, got '{year_raw}'")
                row_ok = False

        # --- code format vs level ---
        if code and level_raw and 'level' in dir():
            pass
        if code and level_raw:
            try:
                lvl = int(level_raw)
            except ValueError:
                lvl = None
            if lvl == 0:
                if code not in MACRO_CODES:
                    _add(findings, "ERROR", i, "admin_code",
                         f"admin_level=0 rows must use one of {sorted(MACRO_CODES)}, got '{code}'")
                    row_ok = False
            elif lvl in (1, 2, 3):
                pattern = CODE_RE[lvl]
                if not pattern.match(code):
                    expected_fmt = {1: "XX0000", 2: "XXYY00", 3: "XXYYZZ"}[lvl]
                    _add(findings, "ERROR", i, "admin_code",
                         f"admin_level={lvl} requires a 6-digit GB/T 2260 code in {expected_fmt} form, got '{code}'")
                    row_ok = False
                else:
                    codes_by_level[lvl][code] = i

        # --- macro_region enum ---
        macro = (row.get("macro_region") or "").strip()
        if macro and macro not in MACRO_REGIONS:
            _add(findings, "ERROR", i, "macro_region", f"Invalid macro_region '{macro}', must be one of {sorted(MACRO_REGIONS)}")
            row_ok = False

        # --- occupation_category enum ---
        occ = (row.get("occupation_category") or "").strip()
        if occ and occ not in OCCUPATION_CATEGORIES:
            _add(findings, "ERROR", i, "occupation_category", f"Invalid occupation_category '{occ}'")
            row_ok = False

        # --- wage_measure enum ---
        wm = (row.get("wage_measure") or "").strip()
        if wm and wm not in WAGE_MEASURES:
            _add(findings, "ERROR", i, "wage_measure", f"Invalid wage_measure '{wm}', must be one of {sorted(WAGE_MEASURES)}")
            row_ok = False

        # --- data_availability enum (informational but required to be valid if present) ---
        avail = (row.get("data_availability") or "").strip()
        if avail and avail not in DATA_AVAILABILITY:
            _add(findings, "ERROR", i, "data_availability", f"Invalid data_availability '{avail}'")
            row_ok = False
        if avail == "not_available":
            wage_val = (row.get("avg_annual_wage_cny") or "").strip()
            if wage_val:
                _add(findings, "WARNING", i, "avg_annual_wage_cny",
                     "Row marked data_availability='not_available' but has a wage value -- did you mean to update data_availability?")

        # --- classification_system consistency ---
        cls = (row.get("classification_system") or "").strip()
        if cls and cls not in CLASSIFICATION_SYSTEMS:
            _add(findings, "ERROR", i, "classification_system", f"Invalid classification_system '{cls}'")
            row_ok = False
        if cls and code and level_raw:
            try:
                lvl = int(level_raw)
                if lvl == 0 and cls != "GB_T_2260_MACRO":
                    _add(findings, "WARNING", i, "classification_system",
                         "admin_level=0 (national/macro-region) is an NBS aggregate, not a real GB/T 2260 code -- expected classification_system='GB_T_2260_MACRO'")
                if lvl in (1, 2, 3) and cls != "GB_T_2260":
                    _add(findings, "WARNING", i, "classification_system",
                         f"admin_level={lvl} is a real administrative code -- expected classification_system='GB_T_2260'")
            except ValueError:
                pass

        # --- wage value sanity ---
        wage_raw = (row.get("avg_annual_wage_cny") or "").strip()
        if wage_raw:
            try:
                wage = float(wage_raw)
                if wage < 0:
                    _add(findings, "ERROR", i, "avg_annual_wage_cny", "avg_annual_wage_cny cannot be negative")
                    row_ok = False
                elif wage > 2_000_000:
                    _add(findings, "WARNING", i, "avg_annual_wage_cny", f"Unusually high wage value: {wage}")
            except ValueError:
                _add(findings, "ERROR", i, "avg_annual_wage_cny", f"avg_annual_wage_cny must be numeric, got '{wage_raw}'")
                row_ok = False

        # --- duplicate (admin_code, year, occupation_category, wage_measure) ---
        dedup_key = (code, year_raw, occ, wm)
        if dedup_key in seen_keys:
            _add(findings, "ERROR", i, "admin_code",
                 f"Duplicate row for admin_code='{code}', year={year_raw}, occupation='{occ}', wage_measure='{wm}' (first seen on row {seen_keys[dedup_key]})")
            row_ok = False
        else:
            seen_keys[dedup_key] = i

        if row_ok:
            clean_records.append(row)

    # --- hierarchy pass: prefecture must nest in a declared province, county in a declared prefecture ---
    for code, row_num in codes_by_level[2].items():
        province_code = code[:2] + "0000"
        if province_code not in codes_by_level[1]:
            _add(findings, "WARNING", row_num, "parent_admin_code",
                 f"Prefecture code '{code}' has no matching province '{province_code}' declared in this file (may exist elsewhere in your DB -- this is only a same-file consistency check)")
    for code, row_num in codes_by_level[3].items():
        prefecture_code = code[:4] + "00"
        if prefecture_code not in codes_by_level[2]:
            _add(findings, "WARNING", row_num, "parent_admin_code",
                 f"County/district code '{code}' has no matching prefecture '{prefecture_code}' declared in this file (may exist elsewhere in your DB -- this is only a same-file consistency check)")

    errors = [f for f in findings if f["severity"] == "ERROR"]
    warnings = [f for f in findings if f["severity"] == "WARNING"]
    summary = {
        "total_rows": len(rows),
        "clean_rows": len(clean_records),
        "errors": len(errors),
        "warnings": len(warnings),
    }
    return findings, clean_records, summary


def main():
    parser = argparse.ArgumentParser(description="Validate a China regional-wage CSV file")
    parser.add_argument("input_csv")
    parser.add_argument("--mode", choices=["china"], default="china")
    parser.add_argument("--report", help="Write full JSON findings report to this path")
    parser.add_argument("--export-clean", help="Write only clean (error-free) rows to this CSV path")
    args = parser.parse_args()

    findings, clean_records, summary = validate_file(args.input_csv, mode=args.mode)

    print(f"Validated: {args.input_csv}")
    print(json.dumps(summary, indent=2))
    for f in findings:
        print(f"  [{f['severity']}] row {f['row']} ({f['field']}): {f['message']}")

    if args.report:
        with open(args.report, "w", encoding="utf-8") as out:
            json.dump({"summary": summary, "findings": findings}, out, indent=2, ensure_ascii=False)

    if args.export_clean and clean_records:
        with open(args.export_clean, "w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=ALL_COLUMNS)
            writer.writeheader()
            for r in clean_records:
                writer.writerow({k: r.get(k, "") for k in ALL_COLUMNS})

    fatal = [f for f in findings if f["severity"] == "FATAL"]
    sys.exit(1 if fatal else 0)


if __name__ == "__main__":
    main()
