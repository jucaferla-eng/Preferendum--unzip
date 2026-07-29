# Russia Regional Wage Data Standard (by occupation and administrative level)

Companion module to the NUTS 2/3 Regional Income Data Standard, and a sibling
to the China and Japan wage modules in this same pipeline. Russia has no NUTS
equivalent either, but unlike China it **does** publish a genuine
occupation-by-region cross-tabulation — Rosstat's form № 57-Т survey. The
catch, and the thing this module is built to make impossible to miss, is that
this cross-tab is **coarse** (9 occupation major-groups, not the ~130 detailed
groups Rosstat publishes nationally) and **biennial** (October of odd years
only — 2023, 2025, not every year). This module documents exactly that
boundary rather than smoothing over it.

## 1. Why this isn't a 1:1 port of the NUTS schema — and how Russia compares to China and Japan

| | Europe (NUTS) | China | Japan | **Russia** |
|---|---|---|---|---|
| Admin hierarchy | NUTS 0/1/2/3, EU-codified | GB/T 2260: province → prefecture-level city → county/district | Prefecture (47) → municipality | ОКАТО/ОКТМО: federal subject (85) grouped into 8 federal districts |
| Finest level with **any** wage data | NUTS 2 | Province (31), total wage only | Prefecture (47), full detail | Federal subject (85), annual total; municipality also exists for total wage |
| Finest level with **occupation × region** | N/A | **Macro-region only** (4 zones), no province-level occupation split at all | **Full crosstab** — prefecture × detailed occupation, published annually | **Federal subject × ОКЗ major-group (9 groups)** — genuinely a full geography crosstab, but only 1-digit occupation resolution, and only **published every other year** |
| Frequency of the occupation crosstab | — | Annual (macro-region only) | Annual | **Biennial** — October of odd years (2005…2023, 2025); even years get no occupation-by-region release at all |
| Single national data source | Eurostat REST API | Fragmented — national HTML release, then province-by-province bulletins | Consolidated MHLW wage census | Rosstat publishes both series centrally, but the occupation crosstab is a 40+ sheet **RAR-archived** statistical bulletin, not a queryable table |

**Bottom line:** Russia sits between China and Japan in granularity. It beats
China because a real geography × occupation crosstab exists all the way down
to the federal-subject level (85 units) — not just 4 macro-zones. It falls
short of Japan because (a) the occupation axis stops at 9 broad ОКЗ major
groups where Japan's crosstab goes to detailed occupation codes, and (b) the
crosstab is only refreshed **once every two years**, so any pipeline built on
top of it must tolerate real gaps in the even-year columns — 2024 has an
annual region-only total but genuinely **no** occupation-by-region figure,
and fabricating one would misrepresent Rosstat's own publication calendar.

## 2. Administrative code mapping (ОКАТО / ОКЗ)

Two independent code axes are in play, both maintained by Rosstat
([Rosstat classifier hub](https://rosstat.gov.ru/classification)):

- **Region axis — ОКАТО (ОК 019-95)**: a 2-digit code per federal subject
  (e.g. `77` = Moscow, `78`/`40` = Saint Petersburg regionally, `65` =
  Sverdlovsk Oblast). ОКАТО is still actively maintained (change 567/2026,
  file dated 02.07.2026) alongside its newer sibling ОКТМО (ОК 033-2013),
  which is organized as 8 volumes — one per federal district — confirming
  the federal district is Rosstat's own top-level statistical grouping, not
  an ad hoc invention of this module
  ([Rosstat classifier page](https://rosstat.gov.ru/classification)).
- **Occupation axis — ОКЗ (ОК 010-2014, "МСКЗ-08")**: harmonized with
  ISCO-08, with 9 civilian major groups (1 = Managers … 9 = Elementary
  occupations) plus a 10th "Armed forces" group that never appears in the
  wage survey output ([ОК 010-2014](https://docs.cntd.ru/document/1200121893)).

| `admin_level` | Unit | Code pattern | Count | Example |
|---|---|---|---|---|
| 0 | National / federal-district aggregate (**not** a real administrative unit — a Rosstat statistical grouping, same trick as China's `macro_region` codes) | `RU-NAT`, `RU-FD-Central`, `RU-FD-Northwestern`, `RU-FD-Southern`, `RU-FD-NorthCaucasian`, `RU-FD-Volga`, `RU-FD-Ural`, `RU-FD-Siberian`, `RU-FD-FarEastern` | 1 + 8 | `RU-FD-Central` = Central Federal District |
| 1 | Federal subject (real administrative unit) | 2-digit ОКАТО code | 85 in Rosstat's wage series (new territories excluded) | `77` = Moscow |
| 2 | Municipality (raion / gorodskoi okrug) — **illustrative only**, no occupation split exists at this level | `RU-MUN-<slug>` | not enumerated (Rosstat's БД ПМО covers thousands) | `RU-MUN-OREL-CITY` = city of Orel |

Two documented quirks carried over directly from the source report
([§1.3](https://rosstat.gov.ru/storage/mediabank/tab4-zpl-2025.xlsx)):

- **Arkhangelsk Oblast and Tyumen Oblast each appear three times** in
  Rosstat's own annual-total table — the oblast as a whole, its autonomous
  okrug component, and "oblast excluding the AO." These sub-components
  (Nenets AO, Khanty-Mansi AO-Yugra, Yamalo-Nenets AO, and the two
  "excluding AO" rows) do not have their own top-level ОКАТО code, so they
  use a documented `RU-<SLUG>` fallback (e.g. `RU-NAO-SUB-ARK`) rather than
  an invented numeric code. They are **not** part of the 82-subject
  occupation crosstab, only the annual region-total series.
- **Crimea and Sevastopol** sit inside the Southern Federal District in
  Rosstat's own tables, and are treated that way here.

`classification_system` is `OKATO_MACRO` for level-0 rows (national/
federal-district, not a codified ОКАТО unit), `OKATO_FEDERAL_SUBJECT` for
level-1 rows defined by geography alone, `OKZ` for any row whose defining
dimension is the occupation cross-tab, and `OKTMO_MUNICIPALITY` for the one
illustrative level-2 municipal row.

## 3. Files

```
russia_wage_schema/
├── README.md
├── schema/
│   ├── russia_wage_template.csv          ← canonical column layout + worked examples
│   └── russia_wage.schema.json           ← draft-07 JSON Schema, mirrors the CSV
├── scripts/
│   └── validate_russia_wage.py           ← standalone validator (stdlib only)
└── real_data/
    ├── russia_wage_real.csv               ← 2,109 REAL rows, all officially sourced
    └── validation_report.json             ← output of running the validator on the above
```

## 4. Columns

| Column | Required | Notes |
|---|---|---|
| `admin_code` | yes | See level mapping above |
| `admin_level` | yes | `0` (national/federal-district), `1` (federal subject), or `2` (municipality, illustrative only) |
| `region_name_en` / `region_name_ru` | `region_name_en` required | English + native name |
| `country_iso` | yes | Always `RU` |
| `federal_district` | no | One of the 8 Rosstat federal districts — lets you join a federal-subject row to its district aggregate |
| `occupation_category` | no | ОКЗ major-group English label (9 groups) or `Total`. Populated at national, federal-district, and — uniquely versus China — **federal-subject** level too, because the 57-Т crosstab genuinely reaches that far. Never populated for the municipal example row. |
| `occupation_code` | no | ОКЗ 1-digit code (1-9); blank for `Total` |
| `wage_value` | no | Leave blank + `data_availability=not_available` rather than guessing |
| `currency` | no | Always `RUB` |
| `wage_period` | no | Always `monthly` |
| `wage_measure` | no | Free-text label of the exact Rosstat measure, e.g. `average_monthly_nominal_accrued_wage` (annual series) vs. `average_monthly_nominal_accrued_wage_october_survey` (57-Т series) — **these are not the same statistic and must never be averaged together** (see §6) |
| `survey_type` | no | `annual_regional_total` (tab4-zpl series, all regions, no occupation split) or `biennial_occupation_survey_57T` (October odd years, occupation × region) or `municipal_indicators_БД_ПМО` (the one illustrative municipal row) |
| `year`, `population` | year required | For `biennial_occupation_survey_57T` rows, only odd years are genuine — the validator flags anything else |
| `parent_admin_code` | no | For hierarchy validation — federal subject's parent `RU-FD-*` code, or `RU-NAT` for district rows |
| `classification_system` | no | `OKATO_FEDERAL_SUBJECT`, `OKATO_MACRO`, `OKZ`, or `OKTMO_MUNICIPALITY` |
| `data_availability` | no | Honesty flag: `national`, `federal_district`, `federal_subject`, `municipality`, or `not_available` |
| `source`, `last_updated` | no | Full URL required when a row has real data |

## 5. Validator

```bash
python3 scripts/validate_russia_wage.py real_data/russia_wage_real.csv --report out.json
```

Checks: required fields, `admin_level ∈ {0,1,2}`, admin-code pattern per
level (ОКАТО 2-digit for federal subjects, `RU-NAT`/`RU-FD-*` for
aggregates, `RU-MUN-*` for the municipal example), `country_iso == 'RU'`,
federal-district/occupation/survey-type/data-availability enum validity,
`classification_system` consistency with level, a hard rule that
municipal-level rows (`admin_level=2`) must never carry an occupation split,
a soft rule flagging any `biennial_occupation_survey_57T` row whose `year`
isn't a documented odd survey year, wage-value sanity range, duplicate
`(admin_code, year, occupation_code, survey_type)` detection, and same-file
parent-hierarchy consistency (federal-subject rows should point to a real
`RU-FD-*` parent). Exit code `1` only on fatal header errors — same
convention as `validate_nuts_income.py` and `validate_china_wage.py`.

Result on the real data file: **2,109 / 2,109 rows clean, 0 errors, 0
warnings.**

## 6. Real data included — sources

All 2,109 rows in `real_data/russia_wage_real.csv` trace to a figure
explicitly present in
[`russia_wage_data_availability_report.md`](../russia_wage_data_availability_report.md)
or one of the six supporting CSVs it cites, never invented or interpolated:

- **National + federal-district + federal-subject annual whole-economy
  wage totals, 2023-2025** (288 rows, `survey_type=annual_regional_total`,
  `data_availability` = `national`/`federal_district`/`federal_subject`) —
  report §3.1, sourced from
  [tab4-zpl-2025.xlsx](https://rosstat.gov.ru/storage/mediabank/tab4-zpl-2025.xlsx)
  and saved locally as `rosstat_tab4_wage_by_subject_2018_2025.csv`. Covers
  all 82 federal subjects present in the file plus the 5 documented
  autonomous-okrug sub-aggregate rows (Nenets AO, Khanty-Mansi AO-Yugra,
  Yamalo-Nenets AO, and the two "oblast excluding AO" rows) — 87 level-1
  rows in total, each year (2023/2024/2025) where the source file has a
  value.
- **National ОКЗ major-group wages, October 2023 and October 2025** (part
  of the crosstab below; also cross-checked against
  [sr-zpl6_2025.xlsx](https://rosstat.gov.ru/storage/mediabank/sr-zpl6_2025.xlsx))
  — report §3.2.
- **The full occupation × federal-subject crosstab, October 2023** (1,010
  rows: national + 8 federal districts + 82 federal subjects, each × Total
  + 9 ОКЗ groups) — report §3.3, sourced from the October 2023 form 57-Т
  bulletin,
  [sved_57-t_2023.rar](https://rosstat.gov.ru/storage/mediabank/sved_57-t_2023.rar),
  sheet 32, saved locally as `rosstat_57T_2023_table32.csv`. The report's
  own §3.3 table shows only 6 illustrative subjects, but the full CSV
  Rosstat published (and that this module reads) contains the complete
  82-subject table — every one of those subjects is included here.
- **The full occupation × federal-subject crosstab, October 2025** (1,010
  rows, same structure) — report §3.3, sourced from the October 2025 form
  57-Т bulletin,
  [sved_57-t_2025.rar](https://rosstat.gov.ru/storage/mediabank/sved_57-t_2025.rar),
  sheet 31 (note the sheet-number shift vs. the 2023 wave — matched here on
  sheet title, exactly as the report warns), saved locally as
  `rosstat_57T_2025_table31_occupation_x_region.csv`.
- **One municipal-level row** (`data_availability=municipality`,
  `admin_level=2`, occupation columns blank) — report §4.2, the city of
  Orel's 2024 average monthly accrued wage of employees of organizations
  excluding small business, 61,249 RUB/month, from
  [Orelstat, "Заработная плата за 2024 год"](https://57.rosstat.gov.ru/storage/mediabank/ZP_2024.pdf).
  This single row exists to prove the municipal series is real and
  numerically usable — see §7 for why it isn't expanded further.

`rosstat_57T_2023_table30.csv`, `rosstat_57T_2023_table6.csv`, and
`rosstat_57T_2023_table9.csv` (personnel-category, ОКЗ sub-major-group, and
ОКЗ detailed-group tables, all national-only or personnel-category-only per
report §3.3/§5.2/§5.3) were reviewed but are **not** loaded into this CSV,
because none of them cross occupation with region below the level already
captured above — see §7.

## 7. What's NOT available (deliberately left as `not_available` or documented only in prose)

- **Occupation × geography below the federal-subject level.** The form
  57-Т bulletin's finest territorial axis is the federal subject —
  every territorial table inside
  [sved_57-t_2025.rar](https://rosstat.gov.ru/storage/mediabank/sved_57-t_2025.rar)
  is "по субъектам Российской Федерации." Municipal-level wage indicators
  exist (see below) but are never crossed with ОКЗ occupation. Full stop.
- **No occupation-by-region data in even years.** Form 57-Т runs only in
  October of odd years (2005, 2007, … 2023, 2025) — report §2.2. 2024 has
  a real annual whole-economy wage total (part of `annual_regional_total`)
  but genuinely **no** occupation crosstab; this module does not
  interpolate a synthetic 2024 occupation figure. Any consumer joining on
  `year` needs to expect the `biennial_occupation_survey_57T` series to
  have gaps that `annual_regional_total` does not.
- **Detailed occupation groups (ОКЗ sub-major/minor/unit, ~130 groups) are
  national-only.** Report §5.2/§5.3, tables 6 and 9 of the 2023 bulletin
  (`rosstat_57T_2023_table6.csv`, `rosstat_57T_2023_table9.csv`) give
  granular figures like Врачи (physicians) at 100,014 RUB or Разработчики
  и аналитики программного обеспечения (software developers) at 160,175
  RUB — but with **no regional cut whatsoever**. Not loaded into the CSV
  because it would create a phantom `admin_level` this schema doesn't
  define.
- **Municipal wage data exists but only as a plain total, and only
  "excluding small business."** Rosstat's БД ПМО
  ([rosstat.gov.ru/dbscripts/munst/](https://rosstat.gov.ru/dbscripts/munst/))
  publishes municipal average wage by ownership form and institution type
  (schools, hospitals, culture, etc.), never by ОКЗ occupation — report
  §4.1/§4.3. Krymstat states outright that a full-circle (small-business
  included) municipal estimate "не представляется возможным" for lack of
  an information base
  ([Krymstat workbook](https://82.rosstat.gov.ru/storage/mediabank/oybZF7x8/7.%20%D0%A0%D1%8B%D0%BD%D0%BE%D0%BA%20%D1%82%D1%80%D1%83%D0%B4%D0%B0.xlsx)).
  This module includes exactly one worked municipal example (Orel city,
  §6) to prove the series is real and usable, rather than enumerating the
  thousands of raions/gorodskie okruga in БД ПМО, which is out of scope
  for this pass.
- **Occupation series before the 2015 wave uses a different classifier**
  (ОКЗ ОК 010-93, not ОК 010-2014) with different major-group wording —
  report §5.5. Pre-2015 waves are a separate vintage and are not blended
  into this file's 2023/2025 rows.
- **Access friction, noted for anyone re-running this pipeline:**
  `rosstat.gov.ru` required `curl -k` because of a broken TLS certificate
  chain; several regional statistical-office subdomains (e.g.
  `57.rosstat.gov.ru`, `82.rosstat.gov.ru`) serve cp1251-encoded pages; and
  the 57-Т bulletins themselves are distributed as password-free but
  **RAR archives** (`sved_57-t_2023.rar`, `sved_57-t_2025.rar`), not a
  direct spreadsheet or API — report, closing "Access notes."

## 8. Extending this later

- **Re-run this pipeline in October 2027** when the next form 57-Т wave
  is due — the biennial gap means 2026 will have no occupation crosstab no
  matter what, and 2027 is the earliest a fresh occupation × region cut
  can legitimately appear.
- **Pull the men/women-split versions** of the same crosstab (sheets 32/33
  in the 2025 bulletin, report §2.3) if a sex dimension is ever needed —
  the standard errors published in bulletin table 44/43 (report §2.3) show
  the survey is precise enough at "all workers" level (CV mostly ≤2.5% per
  subject) to support this, though narrower occupation × sex × small-region
  cells will be noisier.
- **Expand the municipal row set** using БД ПМО's per-region ОКАТО-keyed
  directories (report §4.1) — this pass intentionally includes only one
  worked example (Orel city) to prove the series out; scaling to more
  municipalities means fetching each region's own `munst<OKATO>` instance.
- **Add the personnel-category axis** (руководители/специалисты/другие
  служащие/рабочие — report §5.4, `rosstat_57T_2023_table30.csv`), an
  orthogonal, non-ОКЗ classification that also exists back through
  pre-2015 waves, if a longer time series is ever needed alongside ОКЗ.

## 9. Fits into the existing Preferendum pipeline

In `nuts_income_schema/seed/seed_countries_50.sql`, Russia (`RU`) fits the
same Tier B, `in_nuts_scope = FALSE` pattern already used for China — a
country-specific, non-NUTS data source that `classification_system =
'CUSTOM'` was designed to accommodate in the main schema. The DDL/ETL
scripts built for the NUTS pipeline are generic enough to reuse for
Russia's data once the `staging_regional_income` table is extended with
`occupation_category`/`occupation_code` columns (or a separate
`staging_regional_wage_by_occupation` table, exactly as recommended for
China) — Russia's data uses a different unit of measure (RUB, not EUR) and,
unlike China, the occupation dimension actually reaches the finest real
administrative level (federal subject) that this module tracks, so the
join key is simpler here than in the China module: no macro-region-only
caveat is needed for the crosstab rows, only the biennial-year and
1-digit-occupation caveats documented in §7.
