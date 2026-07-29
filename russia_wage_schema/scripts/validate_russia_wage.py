#!/usr/bin/env python3
"""
validate_russia_wage.py -- standalone validator for the Russia regional-wage CSV
standard (federal subject / federal district aggregate, OKATO codes, plus the
OKZ 1-digit occupation major-group crosstab published biennially via form 57-T).

No third-party dependencies -- stdlib only (csv, re, sys, argparse, json).

Usage:
    python3 validate_russia_wage.py <input.csv> [--report out.json] [--export-clean clean.csv]

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
    "admin_code", "admin_level", "region_name_en", "region_name_ru", "country_iso",
    "federal_district", "occupation_category", "occupation_code", "wage_value", "currency",
    "wage_period", "wage_measure", "survey_type", "year", "population", "parent_admin_code",
    "classification_system", "data_availability", "source", "last_updated",
]

FD_CODES = {
    "RU-FD-Central", "RU-FD-Northwestern", "RU-FD-Southern", "RU-FD-NorthCaucasian",
    "RU-FD-Volga", "RU-FD-Ural", "RU-FD-Siberian", "RU-FD-FarEastern",
}
NAT_CODE = "RU-NAT"
FEDERAL_DISTRICTS = {
    "Central", "Northwestern", "Southern", "North Caucasian", "Volga",
    "Ural", "Siberian", "Far Eastern",
}
OCCUPATION_CATEGORIES = {
    "Total",
    "Managers",
    "Professionals",
    "Technicians and associate professionals",
    "Clerical support workers",
    "Service and sales workers",
    "Skilled agricultural, forestry and fishery workers",
    "Craft and related trades workers",
    "Plant and machine operators and assemblers",
    "Elementary occupations",
}
OCCUPATION_CODES = {str(i) for i in range(1, 10)}
SURVEY_TYPES = {"annual_regional_total", "biennial_occupation_survey_57T", "municipal_indicators_БД_ПМО"}
DATA_AVAILABILITY = {"national", "federal_district", "federal_subject", "municipality", "not_available"}
CLASSIFICATION_SYSTEMS = {"OKATO_FEDERAL_SUBJECT", "OKATO_MACRO", "OKZ", "OKTMO_MUNICIPALITY"}

# admin_code format per level:
#   level 0: RU-NAT or RU-FD-<district>
#   level 1: 2-digit OKATO code (real federal subject), OR a documented RU-<SLUG> fallback
#            for sub-aggregate rows (e.g. autonomous-okrug breakdowns of Arkhangelsk/Tyumen)
#            that do not have their own OKATO top-level code
#   level 2: RU-MUN-<slug> (municipality; illustrative only, no OKZ split)
LEVEL1_OKATO_RE = re.compile(r"^\d{2}$")
LEVEL1_SLUG_RE = re.compile(r"^RU-[A-Za-z0-9-]+$")
LEVEL2_RE = re.compile(r"^RU-MUN-[A-Za-z0-9-]+$")

# Biennial occupation survey (form 57-T) only ran in October of odd years historically
# 2005, 2007, ..., 2023, 2025. Flag anything else as suspicious for that survey_type.
VALID_57T_YEARS = {y for y in range(2005, 2027, 2) if y % 2 == 1}


def _add(findings, severity, row_num, field, message):
    findings.append({"row": row_num, "severity": severity, "field": field, "message": message})


def validate_file(path, mode="russia"):
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

    codes_by_level = {0: {}, 1: {}, 2: {}}  # code -> row_num, for hierarchy pass
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
                if level not in (0, 1, 2):
                    _add(findings, "ERROR", i, "admin_level", f"admin_level must be 0-2, got {level}")
                    row_ok = False
            except ValueError:
                _add(findings, "ERROR", i, "admin_level", f"admin_level must be an integer, got '{level_raw}'")
                row_ok = False
                level = None

        if country and country != "RU":
            _add(findings, "ERROR", i, "country_iso", f"This schema is Russia-only; got country_iso='{country}'")
            row_ok = False

        year = None
        if year_raw:
            try:
                year = int(year_raw)
                if not (1990 <= year <= 2100):
                    _add(findings, "WARNING", i, "year", f"Unusual year value: {year}")
            except ValueError:
                _add(findings, "ERROR", i, "year", f"year must be an integer, got '{year_raw}'")
                row_ok = False

        # --- code format vs level ---
        if code and level_raw:
            try:
                lvl = int(level_raw)
            except ValueError:
                lvl = None
            if lvl == 0:
                if code != NAT_CODE and code not in FD_CODES:
                    _add(findings, "ERROR", i, "admin_code",
                         f"admin_level=0 rows must be '{NAT_CODE}' or one of {sorted(FD_CODES)}, got '{code}'")
                    row_ok = False
                else:
                    codes_by_level[0][code] = i
            elif lvl == 1:
                if LEVEL1_OKATO_RE.match(code) or LEVEL1_SLUG_RE.match(code):
                    codes_by_level[1][code] = i
                else:
                    _add(findings, "ERROR", i, "admin_code",
                         f"admin_level=1 requires a 2-digit OKATO code or a documented RU-<slug> fallback, got '{code}'")
                    row_ok = False
            elif lvl == 2:
                if LEVEL2_RE.match(code):
                    codes_by_level[2][code] = i
                else:
                    _add(findings, "ERROR", i, "admin_code",
                         f"admin_level=2 (municipality) requires an RU-MUN-<slug> code, got '{code}'")
                    row_ok = False

        # --- federal_district enum ---
        fd = (row.get("federal_district") or "").strip()
        if fd and fd not in FEDERAL_DISTRICTS:
            _add(findings, "ERROR", i, "federal_district", f"Invalid federal_district '{fd}', must be one of {sorted(FEDERAL_DISTRICTS)}")
            row_ok = False

        # --- occupation_category / occupation_code enum + consistency ---
        occ = (row.get("occupation_category") or "").strip()
        occ_code = (row.get("occupation_code") or "").strip()
        if occ and occ not in OCCUPATION_CATEGORIES:
            _add(findings, "ERROR", i, "occupation_category", f"Invalid occupation_category '{occ}'")
            row_ok = False
        if occ_code and occ_code not in OCCUPATION_CODES:
            _add(findings, "ERROR", i, "occupation_code", f"Invalid occupation_code '{occ_code}', must be 1-9")
            row_ok = False
        if occ == "Total" and occ_code:
            _add(findings, "WARNING", i, "occupation_code", "occupation_category='Total' should leave occupation_code blank")
        if level_raw:
            try:
                lvl_check = int(level_raw)
                if lvl_check == 2 and occ:
                    _add(findings, "ERROR", i, "occupation_category",
                         "Municipal-level (admin_level=2) rows must not carry an occupation split -- Rosstat's municipal database (БД ПМО) has no OKZ cross-tab")
                    row_ok = False
            except ValueError:
                pass

        # --- survey_type enum ---
        st = (row.get("survey_type") or "").strip()
        if st and st not in SURVEY_TYPES:
            _add(findings, "ERROR", i, "survey_type", f"Invalid survey_type '{st}', must be one of {sorted(SURVEY_TYPES)}")
            row_ok = False
        if st == "biennial_occupation_survey_57T" and year is not None:
            if year not in VALID_57T_YEARS:
                _add(findings, "WARNING", i, "year",
                     f"form 57-T is a biennial October-of-odd-years survey; year={year} is not a documented odd survey year")

        # --- data_availability enum ---
        avail = (row.get("data_availability") or "").strip()
        if avail and avail not in DATA_AVAILABILITY:
            _add(findings, "ERROR", i, "data_availability", f"Invalid data_availability '{avail}'")
            row_ok = False
        wage_val_raw = (row.get("wage_value") or "").strip()
        if avail == "not_available" and wage_val_raw:
            _add(findings, "WARNING", i, "wage_value",
                 "Row marked data_availability='not_available' but has a wage_value -- did you mean to update data_availability?")

        # --- classification_system consistency ---
        cls = (row.get("classification_system") or "").strip()
        if cls and cls not in CLASSIFICATION_SYSTEMS:
            _add(findings, "ERROR", i, "classification_system", f"Invalid classification_system '{cls}'")
            row_ok = False
        if cls and code and level_raw:
            try:
                lvl = int(level_raw)
                if lvl == 0 and cls != "OKATO_MACRO" and occ == "":
                    _add(findings, "WARNING", i, "classification_system",
                         "admin_level=0 (national/federal-district) without an occupation dimension is a Rosstat aggregate -- expected classification_system='OKATO_MACRO'")
                if lvl == 1 and cls not in ("OKATO_FEDERAL_SUBJECT", "OKZ"):
                    _add(findings, "WARNING", i, "classification_system",
                         "admin_level=1 is a real federal subject -- expected classification_system='OKATO_FEDERAL_SUBJECT' (or 'OKZ' if the row's defining dimension is occupation)")
                if lvl == 2 and cls != "OKTMO_MUNICIPALITY":
                    _add(findings, "WARNING", i, "classification_system",
                         "admin_level=2 (municipality) rows are keyed by ОКТМО/ОКАТО municipal directories -- expected classification_system='OKTMO_MUNICIPALITY'")
            except ValueError:
                pass

        # --- wage value sanity ---
        if wage_val_raw:
            try:
                wage = float(wage_val_raw)
                if wage < 0:
                    _add(findings, "ERROR", i, "wage_value", "wage_value cannot be negative")
                    row_ok = False
                elif wage > 5_000_000:
                    _add(findings, "WARNING", i, "wage_value", f"Unusually high wage value: {wage}")
            except ValueError:
                _add(findings, "ERROR", i, "wage_value", f"wage_value must be numeric, got '{wage_val_raw}'")
                row_ok = False

        # --- currency / wage_period sanity ---
        currency = (row.get("currency") or "").strip()
        if currency and currency != "RUB":
            _add(findings, "WARNING", i, "currency", f"Expected currency='RUB', got '{currency}'")
        wp = (row.get("wage_period") or "").strip()
        if wp and wp != "monthly":
            _add(findings, "WARNING", i, "wage_period", f"Expected wage_period='monthly', got '{wp}'")

        # --- duplicate (admin_code, year, occupation_code, survey_type) ---
        dedup_key = (code, year_raw, occ_code, st)
        if dedup_key in seen_keys:
            _add(findings, "ERROR", i, "admin_code",
                 f"Duplicate row for admin_code='{code}', year={year_raw}, occupation_code='{occ_code}', survey_type='{st}' (first seen on row {seen_keys[dedup_key]})")
            row_ok = False
        else:
            seen_keys[dedup_key] = i

        if row_ok:
            clean_records.append(row)

    # --- hierarchy pass: federal subject / municipality must nest in a declared parent (same-file check) ---
    all_level0 = set(codes_by_level[0].keys()) | {NAT_CODE} | FD_CODES
    for code, row_num in codes_by_level[1].items():
        # find this row's parent_admin_code
        pass  # parent check done via row scan below since we need the actual row, not just code

    # re-scan for parent consistency (needs row-level parent_admin_code)
    code_to_level = {}
    for lvl, d in codes_by_level.items():
        for c in d:
            code_to_level[c] = lvl

    for i, row in enumerate(rows, start=2):
        code = (row.get("admin_code") or "").strip()
        parent = (row.get("parent_admin_code") or "").strip()
        level_raw = (row.get("admin_level") or "").strip()
        if not parent or not level_raw:
            continue
        try:
            lvl = int(level_raw)
        except ValueError:
            continue
        if lvl == 1:
            if parent not in FD_CODES and parent != NAT_CODE:
                _add(findings, "WARNING", i, "parent_admin_code",
                     f"Federal-subject row '{code}' declares parent_admin_code='{parent}', which is not one of the 8 RU-FD-* codes or RU-NAT")
        elif lvl == 0 and code in FD_CODES:
            if parent != NAT_CODE:
                _add(findings, "WARNING", i, "parent_admin_code",
                     f"Federal-district row '{code}' should declare parent_admin_code='{NAT_CODE}', got '{parent}'")
        elif lvl == 2:
            if parent and parent not in codes_by_level[1] and not LEVEL1_OKATO_RE.match(parent):
                _add(findings, "WARNING", i, "parent_admin_code",
                     f"Municipal row '{code}' declares parent_admin_code='{parent}', which is not a recognized federal-subject OKATO code in this file")

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
    parser = argparse.ArgumentParser(description="Validate a Russia regional-wage CSV file")
    parser.add_argument("input_csv")
    parser.add_argument("--mode", choices=["russia"], default="russia")
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
