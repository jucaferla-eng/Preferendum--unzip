#!/usr/bin/env python3
"""
validate_japan_wage.py -- standalone validator for the Japan regional-wage CSV
standard (national / prefecture, JIS X 0401 codes, MHLW's Basic Survey on
Wage Structure occupation-by-prefecture crosstab, JSOC major and detailed
occupation groups).

No third-party dependencies -- stdlib only (csv, re, sys, argparse, json).

Usage:
    python3 validate_japan_wage.py <input.csv> [--report out.json] [--export-clean clean.csv]

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
    "admin_code", "admin_level", "region_name_en", "region_name_ja", "country_iso",
    "region_block", "occupation_category", "occupation_code", "occupation_level",
    "wage_value", "wage_unit", "currency", "wage_measure", "year", "population",
    "parent_admin_code", "classification_system", "data_availability", "source", "last_updated",
]

NATIONAL_CODE = "JP-NAT"
REGION_BLOCKS = {
    "Hokkaido", "Tohoku", "Kanto", "Hokuriku", "Tokai/Chubu",
    "Kinki", "Chugoku", "Shikoku", "Kyushu", "Okinawa",
}
JSOC_MAJOR_CATEGORIES = {
    "Total",
    "Administrative and managerial workers",
    "Professional and engineering workers",
    "Clerical workers",
    "Sales workers",
    "Service workers",
    "Security workers",
    "Agriculture, forestry, and fishery workers",
    "Manufacturing process workers",
    "Transport and machine operation workers",
    "Construction and mining workers",
    "Carrying, cleaning, packaging, and related workers",
    "Workers not classifiable by occupation",
}
JSOC_MAJOR_CODES = set("ABCDEFGHIJKL")
WAGE_MEASURES = {"contractual_cash_earnings", "scheduled_cash_earnings", "annual_special_cash_earnings"}
DATA_AVAILABILITY = {"national", "prefecture", "not_available"}
CLASSIFICATION_SYSTEMS = {"JIS_X_0401", "JSOC_MAJOR", "JSOC_DETAILED"}
OCCUPATION_LEVELS = {"major", "detailed", "total"}
WAGE_UNITS = {"thousand_yen_per_month"}

# JIS X 0401: prefecture rows use a zero-padded 2-digit code '01'..'47'.
# The national row uses the synthetic code 'JP-NAT' (not part of JIS X 0401).
PREF_CODE_RE = re.compile(r"^(0[1-9]|[1-3][0-9]|4[0-7])$")


def _add(findings, severity, row_num, field, message):
    findings.append({"row": row_num, "severity": severity, "field": field, "message": message})


def validate_file(path):
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

    pref_codes_seen = {}  # code -> row_num, for hierarchy pass
    national_declared = False
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

        level = None
        if level_raw:
            try:
                level = int(level_raw)
                if level not in (0, 1):
                    _add(findings, "ERROR", i, "admin_level", f"admin_level must be 0 or 1, got {level}")
                    row_ok = False
            except ValueError:
                _add(findings, "ERROR", i, "admin_level", f"admin_level must be an integer, got '{level_raw}'")
                row_ok = False

        if country and country != "JP":
            _add(findings, "ERROR", i, "country_iso", f"This schema is Japan-only; got country_iso='{country}'")
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
        if code and level is not None:
            if level == 0:
                if code != NATIONAL_CODE:
                    _add(findings, "ERROR", i, "admin_code",
                         f"admin_level=0 rows must use admin_code='{NATIONAL_CODE}', got '{code}'")
                    row_ok = False
                else:
                    national_declared = True
            elif level == 1:
                if not PREF_CODE_RE.match(code):
                    _add(findings, "ERROR", i, "admin_code",
                         f"admin_level=1 requires a zero-padded JIS X 0401 prefecture code '01'-'47', got '{code}'")
                    row_ok = False
                else:
                    pref_codes_seen[code] = i

        # --- region_block enum ---
        block = (row.get("region_block") or "").strip()
        if block and block not in REGION_BLOCKS:
            _add(findings, "ERROR", i, "region_block", f"Invalid region_block '{block}', must be one of {sorted(REGION_BLOCKS)}")
            row_ok = False

        # --- occupation_level enum ---
        occ_level = (row.get("occupation_level") or "").strip()
        if occ_level and occ_level not in OCCUPATION_LEVELS:
            _add(findings, "ERROR", i, "occupation_level", f"Invalid occupation_level '{occ_level}', must be one of {sorted(OCCUPATION_LEVELS)}")
            row_ok = False

        # --- occupation_category / occupation_code consistency ---
        occ = (row.get("occupation_category") or "").strip()
        occ_code = (row.get("occupation_code") or "").strip()
        if occ_level == "major":
            if occ and occ not in JSOC_MAJOR_CATEGORIES:
                _add(findings, "ERROR", i, "occupation_category", f"Invalid JSOC major occupation_category '{occ}'")
                row_ok = False
            if occ_code and occ_code not in JSOC_MAJOR_CODES:
                _add(findings, "ERROR", i, "occupation_code", f"occupation_level='major' requires occupation_code in A-L, got '{occ_code}'")
                row_ok = False
        elif occ_level == "total":
            if occ and occ != "Total":
                _add(findings, "WARNING", i, "occupation_category", f"occupation_level='total' but occupation_category='{occ}' (expected 'Total')")
            if occ_code:
                _add(findings, "WARNING", i, "occupation_code", "occupation_level='total' rows normally leave occupation_code blank")
        elif occ_level == "detailed":
            if occ_code:
                _add(findings, "WARNING", i, "occupation_code",
                     "occupation_level='detailed' rows normally leave occupation_code blank (detailed occupations aren't letter-coded in the source tables)")

        # --- wage_unit enum ---
        unit = (row.get("wage_unit") or "").strip()
        if unit and unit not in WAGE_UNITS:
            _add(findings, "ERROR", i, "wage_unit", f"Invalid wage_unit '{unit}', must be one of {sorted(WAGE_UNITS)}")
            row_ok = False

        # --- currency ---
        currency = (row.get("currency") or "").strip()
        if currency and currency != "JPY":
            _add(findings, "ERROR", i, "currency", f"currency must be 'JPY', got '{currency}'")
            row_ok = False

        # --- wage_measure enum ---
        wm = (row.get("wage_measure") or "").strip()
        if wm and wm not in WAGE_MEASURES:
            _add(findings, "ERROR", i, "wage_measure", f"Invalid wage_measure '{wm}', must be one of {sorted(WAGE_MEASURES)}")
            row_ok = False

        # --- data_availability enum ---
        avail = (row.get("data_availability") or "").strip()
        if avail and avail not in DATA_AVAILABILITY:
            _add(findings, "ERROR", i, "data_availability", f"Invalid data_availability '{avail}'")
            row_ok = False
        wage_val_raw = (row.get("wage_value") or "").strip()
        if avail == "not_available" and wage_val_raw:
            _add(findings, "WARNING", i, "wage_value",
                 "Row marked data_availability='not_available' but has a wage_value -- did you mean to update data_availability?")
        if avail in ("national", "prefecture") and not wage_val_raw:
            _add(findings, "WARNING", i, "wage_value",
                 f"Row marked data_availability='{avail}' but wage_value is blank")

        # --- classification_system consistency ---
        cls = (row.get("classification_system") or "").strip()
        if cls and cls not in CLASSIFICATION_SYSTEMS:
            _add(findings, "ERROR", i, "classification_system", f"Invalid classification_system '{cls}'")
            row_ok = False
        if level == 1 and cls and cls not in ("JIS_X_0401",) and occ_level == "total":
            _add(findings, "WARNING", i, "classification_system",
                 "Prefecture Total rows are usually keyed with classification_system='JIS_X_0401'")

        # --- wage value sanity ---
        if wage_val_raw:
            try:
                wage = float(wage_val_raw)
                if wage < 0:
                    _add(findings, "ERROR", i, "wage_value", "wage_value cannot be negative")
                    row_ok = False
                elif wage > 5000:
                    _add(findings, "WARNING", i, "wage_value", f"Unusually high wage_value (千円/month or /year scale expected): {wage}")
            except ValueError:
                _add(findings, "ERROR", i, "wage_value", f"wage_value must be numeric, got '{wage_val_raw}'")
                row_ok = False

        # --- parent-hierarchy consistency ---
        parent = (row.get("parent_admin_code") or "").strip()
        if level == 1 and parent and parent != NATIONAL_CODE:
            _add(findings, "WARNING", i, "parent_admin_code",
                 f"Prefecture row's parent_admin_code should be '{NATIONAL_CODE}', got '{parent}'")

        # --- duplicate (admin_code, year, occupation_code, wage_measure) ---
        dedup_key = (code, year_raw, occ_code or occ, wm)
        if dedup_key in seen_keys:
            _add(findings, "ERROR", i, "admin_code",
                 f"Duplicate row for admin_code='{code}', year={year_raw}, occupation='{occ_code or occ}', wage_measure='{wm}' (first seen on row {seen_keys[dedup_key]})")
            row_ok = False
        else:
            seen_keys[dedup_key] = i

        if row_ok:
            clean_records.append(row)

    # --- hierarchy pass: every prefecture row should have a national row present for context ---
    if pref_codes_seen and not national_declared:
        _add(findings, "WARNING", 0, "parent_admin_code",
             f"{len(pref_codes_seen)} prefecture row(s) present but no admin_level=0 national row found in this file")

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
    parser = argparse.ArgumentParser(description="Validate a Japan regional-wage CSV file")
    parser.add_argument("input_csv")
    parser.add_argument("--report", help="Write full JSON findings report to this path")
    parser.add_argument("--export-clean", help="Write only clean (error-free) rows to this CSV path")
    args = parser.parse_args()

    findings, clean_records, summary = validate_file(args.input_csv)

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
