# China Regional Wage Data Standard (by occupation and administrative level)

Companion module to the NUTS 2/3 Regional Income Data Standard, adapted for
China. China has no NUTS equivalent, and — critically — **its official wage
statistics are far less granular than Eurostat's**. This module documents
exactly where the real data stops, rather than pretending a fine-grained
breakdown exists.

## 1. Why this isn't a 1:1 port of the NUTS schema

| | Europe (NUTS) | China |
|---|---|---|
| Admin hierarchy | NUTS 0/1/2/3, EU-codified, consistent across 30+ countries | GB/T 2260: province → prefecture-level city → county/district (~31 / ~333 / ~2,800+ units) |
| Finest level with **income** data | NUTS 2 (`nama_10r_2hhinc`) | Province (31) — official, but only *total* wage, not by occupation |
| Finest level with **occupation** breakdown | N/A (income schema doesn't cross occupation) | **Macro-region only** (4 zones: Eastern/Central/Western/Northeastern) — occupation × province, occupation × city, and anything at county/district level **does not exist** as public, consolidated data |
| Single national data source | Eurostat REST API, machine-readable JSON-stat | Fragmented: national release is clean HTML/text ([stats.gov.cn](https://www.stats.gov.cn/english/PressRelease/202505/t20250520_1959885.html)); province totals require assembling each province's own bulletin one by one; city/county data is not published nationally at all (only sold by data vendors like CEIC, or scattered in individual municipal bulletins) |

**Bottom line:** you can get real, sourced numbers at (a) national level, (b)
the 4 NBS macro-regions — both *with* occupation breakdown — and (c)
individual provinces — but *without* occupation breakdown, one province
bulletin at a time. Below province level, occupation-by-region data is not
publicly available in China at all, and even plain average-wage figures
by city/prefecture are fragmented across hundreds of separate local
statistical bureau releases (or paywalled aggregators).

## 2. Administrative level mapping (GB/T 2260)

GB/T 2260 codes are always 6 digits; the level is encoded by how many
trailing digits are zero:

| `admin_level` | Unit | Code pattern | Count | Example |
|---|---|---|---|---|
| 0 | National / NBS macro-region (**not** a real admin unit — a statistical aggregate) | `CN-NAT`, `CN-E`, `CN-C`, `CN-W`, `CN-NE` | 1 + 4 | `CN-E` = Eastern zone |
| 1 | Province / municipality / autonomous region | `XX0000` | 31 | `110000` = Beijing |
| 2 | Prefecture-level city | `XXYY00` | ~333 | `110100` = Beijing (city proper) |
| 3 | County / district (closest analog to a "comuna") | `XXYYZZ` | ~2,800+ | `110101` = Dongcheng District, Beijing |

`classification_system` is `GB_T_2260_MACRO` for level-0 rows (since macro-
regions aren't codified) and `GB_T_2260` for levels 1-3.

## 3. Files

```
china_wage_schema/
├── README.md
├── schema/
│   ├── china_wage_template.csv          ← canonical column layout + worked examples
│   └── china_wage.schema.json           ← draft-07 JSON Schema, mirrors the CSV
├── scripts/
│   └── validate_china_wage.py           ← standalone validator (stdlib only)
└── real_data/
    ├── china_wage_real_2024.csv          ← 44 REAL rows, all officially sourced
    └── validation_report.json            ← output of running the validator on the above
```

## 4. Columns

| Column | Required | Notes |
|---|---|---|
| `admin_code` | yes | See level mapping above |
| `admin_level` | yes | `0`, `1`, `2`, or `3` |
| `region_name_en` / `region_name_zh` | `region_name_en` required | English + native name |
| `country_iso` | yes | Always `CN` |
| `macro_region` | no | One of `Eastern`, `Central`, `Western`, `Northeastern` — lets you join a province/city row to the finest occupation-breakdown data that actually exists |
| `occupation_category` | no | NBS's 5 "position" categories, or `Total`. **Only ever populated for `admin_level=0` rows** — this is the real limitation, not a bug |
| `avg_annual_wage_cny` | no | Leave blank + `data_availability=not_available` rather than guessing |
| `year`, `population` | year required | |
| `parent_admin_code` | no | For hierarchy validation |
| `classification_system` | no | `GB_T_2260` or `GB_T_2260_MACRO` |
| `wage_measure` | no | `urban non-private units`, `urban private units`, or `enterprises above designated size` — **these three series are not comparable to each other and must never be averaged together** |
| `data_availability` | no | Honesty flag: `national`, `macro_region`, `province`, `prefecture`, `county_district`, or `not_available` |
| `source`, `last_updated` | no | Full URL required when a row has real data |

## 5. Validator

```bash
python3 scripts/validate_china_wage.py real_data/china_wage_real_2024.csv --report out.json
```

Checks: required fields, `admin_level ∈ {0,1,2,3}`, 6-digit code pattern per
level, `country_iso == 'CN'`, macro-region/occupation/wage-measure/
data-availability enum validity, `classification_system` consistency with
level, wage-value sanity range, duplicate `(admin_code, year, occupation,
wage_measure)` detection, and same-file parent-hierarchy consistency
(prefecture nests in a declared province, county nests in a declared
prefecture). Exit code `1` only on fatal header errors — same convention as
`validate_nuts_income.py`.

Result on the real data file: **44/44 rows clean, 0 errors, 0 warnings.**

## 6. Real data included — sources

All 44 rows in `real_data/china_wage_real_2024.csv` are genuine 2024
figures, not placeholders:

- **National + 4 macro-regions × 6 occupation categories × wage measure**
  (34 rows) — [NBS official 2024 wage release](https://www.stats.gov.cn/english/PressRelease/202505/t20250520_1959885.html),
  published 2025-05-20. This is the complete occupation-by-geography
  crosstab NBS publishes — there is nothing finer.
- **4 individual provinces, total wage only** (10 rows): Beijing, Shanghai,
  Henan, Heilongjiang — sourced from [China Statistical Yearbook 2025 figures reported by 163.com](https://www.163.com/dy/article/KDEUGMIQ0552DMW3.html)
  and, for Heilongjiang, directly from the [Heilongjiang provincial statistics bureau](https://tjj.hlj.gov.cn/tjj/c106736/202506/c00_31850581.shtml).
  These four were chosen because they were the only provinces with
  individually-quoted exact figures found in available sources — the
  other 27 provinces' 2024 totals exist (all 31 are in the *China
  Statistical Yearbook 2025*) but weren't individually quoted in the
  secondary sources checked, and the Yearbook itself isn't freely
  browsable online table-by-table.

## 7. What's deliberately left as `not_available`

- **Occupation category for any province/city/county row** — NBS does not
  publish this breakdown below macro-region level. Full stop.
- **All city/prefecture-level wage figures** for provinces beyond the ones
  above — real figures exist (e.g. Hefei ¥122,162, Taiyuan ¥113,002 were
  mentioned in passing in Chinese financial press) but there's no single
  consolidated source; each would need its own city statistics bureau
  bulletin.
- **Any county/district-level wage figure** — genuinely not published
  anywhere as public official data, occupation or not.

## 8. Extending this later

To get more real province-level rows: pull the *China Statistical Yearbook
2025* regional wage table directly (behind NBS's own data query tool,
which blocks non-browser traffic — would need a real browser session) or
assemble bulletins from the 27 remaining provincial statistics bureaus
one at a time (each is its own webpage, in Chinese, similar to the
Heilongjiang one cited above).

To get city/prefecture-level rows at scale: either license CEIC's
consolidated series, or run a systematic collection pass across the ~333
prefecture-level cities' own bureau bulletins (slow, partial coverage,
inconsistent years/measures — flagged as an explicit option the user
declined for this pass).

## 9. Fits into the existing Preferendum pipeline

In `nuts_income_schema/seed/seed_countries_50.sql`, China (`CN`) is already
seeded as a Tier B country with `in_nuts_scope = FALSE` — this module is
exactly the kind of country-specific, non-NUTS data source that
`classification_system = 'CUSTOM'` was designed to accommodate in the main
schema. The DDL/ETL scripts built for the NUTS pipeline are generic enough
to reuse for China's data once the `staging_regional_income` table is
extended with an `occupation_category` column (or a separate
`staging_regional_wage_by_occupation` table, given China's data uses a
different unit of measure — CNY, not EUR — and a different dimension
structure — occupation × macro-region rather than a single income figure
per region).
