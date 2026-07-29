#!/usr/bin/env python3
"""
validate_korea_wage.py -- standalone validator for the South Korea two-table
regional/occupation wage data standard.

Korea's official wage statistics do NOT support a single occupation x region
crosstab (KOSIS Q&A #24532: https://kosis.kr/civilComplaint/qnaDetail.do?boardIdx=24532).
This validator therefore checks TWO independent CSVs:

  1. kr_wage_by_region      -- admin_code in {KR-NAT, 11-39 sido}, NO occupation dimension
  2. kr_wage_by_occupation  -- admin_code always KR-NAT, NO region dimension

The two tables are never joined on region or occupation -- only on
(country_iso, year). This script validates each file independently and
reports a combined summary.

No third-party dependencies -- stdlib only (csv, re, sys, argparse, json).

Usage:
    # Auto-detect by filename (must contain 'region' or 'occupation'):
    python3 validate_korea_wage.py real_data/kr_wage_by_region_real.csv real_data/kr_wage_by_occupation_real.csv --report out.json

    # Or validate just one file:
    python3 validate_korea_wage.py real_data/kr_wage_by_region_real.csv --report out.json

Exit codes:
    0 = no fatal (header) errors in any file -- row-level findings may still exist
    1 = fatal header/structure error in at least one file
"""
import argparse
import csv
import json
import re
import sys

# ---------------------------------------------------------------------------
# TABLE 1: kr_wage_by_region
# ---------------------------------------------------------------------------
REGION_REQUIRED_COLUMNS = ["admin_code", "admin_level", "region_name_en", "country_iso", "year"]
REGION_ALL_COLUMNS = [
    "admin_code", "admin_level", "region_name_en", "region_name_ko", "country_iso",
    "wage_value", "currency", "wage_period", "wage_measure", "year", "population",
    "parent_admin_code", "classification_system", "data_availability", "source", "last_updated",
]
REGION_CODE_RE = re.compile(r"^(KR-NAT|(0[0-9]|1[0-9]|2[0-9]|3[0-9]))$")
REGION_ADMIN_LEVELS = {0, 1}
REGION_WAGE_MEASURES = {"wage_total", "regular_pay", "overtime_pay", "special_pay", "monthly_pay"}
REGION_DATA_AVAILABILITY = {"national", "sido", "not_available"}
REGION_CLASSIFICATION_SYSTEMS = {"SGIS_SIDO"}
REGION_CURRENCIES = {"KRW_thousand"}
REGION_PERIODS = {"monthly"}

# ---------------------------------------------------------------------------
# TABLE 2: kr_wage_by_occupation
# ---------------------------------------------------------------------------
OCC_REQUIRED_COLUMNS = ["admin_code", "occupation_category", "wage_value", "country_iso", "year"]
OCC_ALL_COLUMNS = [
    "admin_code", "occupation_category", "occupation_code", "wage_value", "currency",
    "wage_period", "wage_measure", "year", "classification_system", "data_availability",
    "source", "last_updated", "country_iso",
]
OCC_CATEGORIES = {
    "All occupations",
    "Managers",
    "Professionals and related workers",
    "Clerks",
    "Service workers",
    "Sales workers",
    "Skilled agricultural, forestry and fishery workers",
    "Craft and related trades workers",
    "Equipment, machine operating and assembling workers",
    "Elementary workers",
}
OCC_CODES = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}
OCC_WAGE_MEASURES = {"monthly_wage_total"}
OCC_DATA_AVAILABILITY = {"national_only"}
OCC_CLASSIFICATION_SYSTEMS = {"KSCO_7TH_MAJOR"}


def _add(findings, severity, row_num, field, message):
    findings.append({"row": row_num, "severity": severity, "field": field, "message": message})


def _read_csv(path, required_columns, findings):
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            missing = [c for c in required_columns if c not in header]
            if missing:
                _add(findings, "FATAL", 0, "header", f"Missing required column(s): {missing}")
                return None
            return list(reader)
    except FileNotFoundError:
        _add(findings, "FATAL", 0, "file", f"File not found: {path}")
        return None
    except csv.Error as e:
        _add(findings, "FATAL", 0, "file", f"CSV parse error: {e}")
        return None


def validate_region_file(path):
    findings = []
    clean_records = []
    rows = _read_csv(path, REGION_REQUIRED_COLUMNS, findings)
    if rows is None:
        return findings, [], {"total_rows": 0, "clean_rows": 0, "errors": 1, "warnings": 0}

    seen_keys = {}

    for i, row in enumerate(rows, start=2):
        row_ok = True
        code = (row.get("admin_code") or "").strip()
        level_raw = (row.get("admin_level") or "").strip()
        country = (row.get("country_iso") or "").strip()
        year_raw = (row.get("year") or "").strip()

        if not code:
            _add(findings, "ERROR", i, "admin_code", "admin_code is required")
            row_ok = False
        elif not REGION_CODE_RE.match(code):
            _add(findings, "ERROR", i, "admin_code",
                 f"admin_code must be 'KR-NAT' or a 2-digit SGIS sido code (00-39), got '{code}'")
            row_ok = False

        if not level_raw:
            _add(findings, "ERROR", i, "admin_level", "admin_level is required")
            row_ok = False
        else:
            try:
                level = int(level_raw)
                if level not in REGION_ADMIN_LEVELS:
                    _add(findings, "ERROR", i, "admin_level",
                         f"admin_level must be 0 (national) or 1 (sido), got {level}")
                    row_ok = False
                if level == 0 and code != "KR-NAT":
                    _add(findings, "ERROR", i, "admin_code",
                         f"admin_level=0 rows must use admin_code='KR-NAT', got '{code}'")
                    row_ok = False
                if level == 1 and code == "KR-NAT":
                    _add(findings, "ERROR", i, "admin_code",
                         "admin_level=1 (sido) rows must NOT use admin_code='KR-NAT'")
                    row_ok = False
            except ValueError:
                _add(findings, "ERROR", i, "admin_level", f"admin_level must be an integer, got '{level_raw}'")
                row_ok = False

        if country and country != "KR":
            _add(findings, "ERROR", i, "country_iso", f"This schema is Korea-only; got country_iso='{country}'")
            row_ok = False

        if year_raw:
            try:
                year = int(year_raw)
                if not (1990 <= year <= 2100):
                    _add(findings, "WARNING", i, "year", f"Unusual year value: {year}")
            except ValueError:
                _add(findings, "ERROR", i, "year", f"year must be an integer, got '{year_raw}'")
                row_ok = False

        wm = (row.get("wage_measure") or "").strip()
        if wm and wm not in REGION_WAGE_MEASURES:
            _add(findings, "ERROR", i, "wage_measure", f"Invalid wage_measure '{wm}', must be one of {sorted(REGION_WAGE_MEASURES)}")
            row_ok = False

        avail = (row.get("data_availability") or "").strip()
        if avail and avail not in REGION_DATA_AVAILABILITY:
            _add(findings, "ERROR", i, "data_availability", f"Invalid data_availability '{avail}', must be one of {sorted(REGION_DATA_AVAILABILITY)}")
            row_ok = False
        if avail == "not_available":
            wage_val = (row.get("wage_value") or "").strip()
            if wage_val:
                _add(findings, "WARNING", i, "wage_value",
                     "Row marked data_availability='not_available' but has a wage value -- did you mean to update data_availability?")

        cls = (row.get("classification_system") or "").strip()
        if cls and cls not in REGION_CLASSIFICATION_SYSTEMS:
            _add(findings, "ERROR", i, "classification_system", f"Invalid classification_system '{cls}'")
            row_ok = False

        currency = (row.get("currency") or "").strip()
        if currency and currency not in REGION_CURRENCIES:
            _add(findings, "WARNING", i, "currency", f"Unexpected currency '{currency}', expected one of {sorted(REGION_CURRENCIES)}")

        period = (row.get("wage_period") or "").strip()
        if period and period not in REGION_PERIODS:
            _add(findings, "WARNING", i, "wage_period", f"Unexpected wage_period '{period}', expected one of {sorted(REGION_PERIODS)}")

        wage_raw = (row.get("wage_value") or "").strip()
        if wage_raw:
            try:
                wage = float(wage_raw)
                if wage < 0:
                    _add(findings, "ERROR", i, "wage_value", "wage_value cannot be negative")
                    row_ok = False
                elif wage > 50_000:
                    _add(findings, "WARNING", i, "wage_value", f"Unusually high monthly wage value (thousand KRW): {wage}")
            except ValueError:
                _add(findings, "ERROR", i, "wage_value", f"wage_value must be numeric, got '{wage_raw}'")
                row_ok = False

        # duplicate detection: (admin_code, year, wage_measure) -- this table has no occupation dimension
        dedup_key = (code, year_raw, wm)
        if dedup_key in seen_keys:
            _add(findings, "ERROR", i, "admin_code",
                 f"Duplicate row for admin_code='{code}', year={year_raw}, wage_measure='{wm}' (first seen on row {seen_keys[dedup_key]})")
            row_ok = False
        else:
            seen_keys[dedup_key] = i

        if row_ok:
            clean_records.append(row)

    errors = [f for f in findings if f["severity"] == "ERROR"]
    warnings = [f for f in findings if f["severity"] == "WARNING"]
    summary = {
        "table": "kr_wage_by_region",
        "total_rows": len(rows),
        "clean_rows": len(clean_records),
        "errors": len(errors),
        "warnings": len(warnings),
    }
    return findings, clean_records, summary


def validate_occupation_file(path):
    findings = []
    clean_records = []
    rows = _read_csv(path, OCC_REQUIRED_COLUMNS, findings)
    if rows is None:
        return findings, [], {"total_rows": 0, "clean_rows": 0, "errors": 1, "warnings": 0}

    seen_keys = {}

    for i, row in enumerate(rows, start=2):
        row_ok = True
        code = (row.get("admin_code") or "").strip()
        occ = (row.get("occupation_category") or "").strip()
        occ_code = (row.get("occupation_code") or "").strip()
        country = (row.get("country_iso") or "").strip()
        year_raw = (row.get("year") or "").strip()

        if not code:
            _add(findings, "ERROR", i, "admin_code", "admin_code is required")
            row_ok = False
        elif code != "KR-NAT":
            _add(findings, "ERROR", i, "admin_code",
                 f"kr_wage_by_occupation has NO region dimension -- admin_code must always be 'KR-NAT', got '{code}'")
            row_ok = False

        if not occ:
            _add(findings, "ERROR", i, "occupation_category", "occupation_category is required")
            row_ok = False
        elif occ not in OCC_CATEGORIES:
            _add(findings, "ERROR", i, "occupation_category", f"Invalid occupation_category '{occ}'")
            row_ok = False

        if occ_code and occ_code not in OCC_CODES:
            _add(findings, "ERROR", i, "occupation_code", f"Invalid occupation_code '{occ_code}', must be one of {sorted(OCC_CODES)}")
            row_ok = False

        if country and country != "KR":
            _add(findings, "ERROR", i, "country_iso", f"This schema is Korea-only; got country_iso='{country}'")
            row_ok = False

        if year_raw:
            try:
                year = int(year_raw)
                if not (1990 <= year <= 2100):
                    _add(findings, "WARNING", i, "year", f"Unusual year value: {year}")
            except ValueError:
                _add(findings, "ERROR", i, "year", f"year must be an integer, got '{year_raw}'")
                row_ok = False

        wm = (row.get("wage_measure") or "").strip()
        if wm and wm not in OCC_WAGE_MEASURES:
            _add(findings, "ERROR", i, "wage_measure", f"Invalid wage_measure '{wm}', must be one of {sorted(OCC_WAGE_MEASURES)}")
            row_ok = False

        avail = (row.get("data_availability") or "").strip()
        if avail and avail not in OCC_DATA_AVAILABILITY:
            _add(findings, "ERROR", i, "data_availability",
                 f"Invalid data_availability '{avail}' -- this table structurally only supports 'national_only'")
            row_ok = False
        if avail == "not_available":
            _add(findings, "ERROR", i, "data_availability",
                 "'not_available' is not a valid value for kr_wage_by_occupation -- use 'national_only' with an empty wage_value instead")
            row_ok = False

        cls = (row.get("classification_system") or "").strip()
        if cls and cls not in OCC_CLASSIFICATION_SYSTEMS:
            _add(findings, "ERROR", i, "classification_system", f"Invalid classification_system '{cls}'")
            row_ok = False

        wage_raw = (row.get("wage_value") or "").strip()
        if wage_raw:
            try:
                wage = float(wage_raw)
                if wage < 0:
                    _add(findings, "ERROR", i, "wage_value", "wage_value cannot be negative")
                    row_ok = False
                elif wage > 50_000:
                    _add(findings, "WARNING", i, "wage_value", f"Unusually high monthly wage value (thousand KRW): {wage}")
            except ValueError:
                _add(findings, "ERROR", i, "wage_value", f"wage_value must be numeric, got '{wage_raw}'")
                row_ok = False
        elif not avail:
            _add(findings, "ERROR", i, "wage_value", "wage_value is required")
            row_ok = False

        # duplicate detection: (occupation_category, year, wage_measure) -- admin_code is always KR-NAT here
        dedup_key = (occ, year_raw, wm)
        if dedup_key in seen_keys:
            _add(findings, "ERROR", i, "occupation_category",
                 f"Duplicate row for occupation_category='{occ}', year={year_raw}, wage_measure='{wm}' (first seen on row {seen_keys[dedup_key]})")
            row_ok = False
        else:
            seen_keys[dedup_key] = i

        if row_ok:
            clean_records.append(row)

    errors = [f for f in findings if f["severity"] == "ERROR"]
    warnings = [f for f in findings if f["severity"] == "WARNING"]
    summary = {
        "table": "kr_wage_by_occupation",
        "total_rows": len(rows),
        "clean_rows": len(clean_records),
        "errors": len(errors),
        "warnings": len(warnings),
    }
    return findings, clean_records, summary


def detect_table_type(path):
    lowered = path.lower()
    if "occupation" in lowered:
        return "occupation"
    if "region" in lowered:
        return "region"
    # fall back to header sniffing
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            header = csv.reader(f).__next__()
            if "occupation_category" in header and "region_name_en" not in header:
                return "occupation"
            if "region_name_en" in header:
                return "region"
    except Exception:
        pass
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Validate South Korea wage-by-region and/or wage-by-occupation CSV file(s)"
    )
    parser.add_argument("input_csv", nargs="+", help="One or two CSV files (region and/or occupation table)")
    parser.add_argument("--report", help="Write full combined JSON findings report to this path")
    args = parser.parse_args()

    if len(args.input_csv) > 2:
        print("ERROR: pass at most two files (one region table, one occupation table)", file=sys.stderr)
        sys.exit(1)

    combined = {"summaries": [], "findings": {}}
    any_fatal = False

    for path in args.input_csv:
        table_type = detect_table_type(path)
        if table_type == "occupation":
            findings, clean, summary = validate_occupation_file(path)
        elif table_type == "region":
            findings, clean, summary = validate_region_file(path)
        else:
            print(f"ERROR: could not auto-detect table type for '{path}' "
                  f"(filename should contain 'region' or 'occupation')", file=sys.stderr)
            sys.exit(1)

        print(f"Validated: {path} (detected table: kr_wage_by_{table_type})")
        print(json.dumps(summary, indent=2))
        for f in findings:
            print(f"  [{f['severity']}] row {f['row']} ({f['field']}): {f['message']}")

        combined["summaries"].append(summary)
        combined["findings"][path] = findings
        if any(f["severity"] == "FATAL" for f in findings):
            any_fatal = True

    combined["totals"] = {
        "total_rows": sum(s["total_rows"] for s in combined["summaries"]),
        "clean_rows": sum(s["clean_rows"] for s in combined["summaries"]),
        "errors": sum(s["errors"] for s in combined["summaries"]),
        "warnings": sum(s["warnings"] for s in combined["summaries"]),
    }

    if args.report:
        with open(args.report, "w", encoding="utf-8") as out:
            json.dump(combined, out, indent=2, ensure_ascii=False)

    sys.exit(1 if any_fatal else 0)


if __name__ == "__main__":
    main()
