# Japan Regional Wage Data Standard (by occupation and administrative level)

Companion module to the NUTS 2/3 Regional Income Data Standard and to the
China regional-wage module, adapted for Japan. Unlike China, **Japan
genuinely publishes an occupation × prefecture wage crosstab** — this is
the headline finding of this module and the biggest structural difference
from every other country studied so far.

## 1. Why this isn't a 1:1 port of the NUTS (or China) schema — and why Japan is the best case yet

| | Europe (NUTS) | China | **Japan** |
|---|---|---|---|
| Admin hierarchy | NUTS 0/1/2/3, EU-codified, consistent across 30+ countries | GB/T 2260: province → prefecture-level city → county/district (~31 / ~333 / ~2,800+ units) | 統計に用いる標準地域コード: JIS X 0401 prefecture (2-digit, 47 units) → JIS X 0402 municipality (3-digit, ~1,700+ units) |
| Finest level with **income** data | NUTS 2 (`nama_10r_2hhinc`) | Province (31) — official, but only *total* wage, not by occupation | **Prefecture (47)** — official, both *total* and *by occupation* |
| Finest level with **occupation** breakdown | N/A (income schema doesn't cross occupation) | Macro-region only (4 zones) — occupation × province/city/county **does not exist** as public data | **Prefecture — a genuine, published crosstab.** MHLW's 賃金構造基本統計調査 (Basic Survey on Wage Structure, e-Stat survey code `00450091`) publishes 都道府県別第２表 (prefecture × 12 JSOC major occupation groups) and 都道府県別第３表 (prefecture × ~145 detailed occupations), each split by sex — [e-Stat table list](https://www.e-stat.go.jp/stat-search/files?tclass=000001225453&cycle=0) |
| Single national data source | Eurostat REST API, machine-readable JSON-stat | Fragmented: national release is clean HTML/text; province totals require assembling each province's own bulletin one by one; city/county data not published nationally at all | **Single national source, machine-readable.** All 47 prefectures × all occupation groups come from one MHLW survey, downloadable as structured `.xlsx` files directly from e-Stat via a predictable `file-download?statInfId=…` URL pattern — no per-prefecture bulletin hunting required |

**Bottom line:** Japan is the best-documented case of the three studied so
far. You get real, sourced, occupation-by-prefecture figures for all 47
prefectures from a single official survey — something neither the NUTS
income schema nor the China module can offer below the national/macro-region
level. The genuine limitation in Japan is *geographic*, not occupational:
**no wage data exists below the prefecture level anywhere** (see Section 7).
That is a much narrower gap than China's, where occupation breakdown itself
disappears below the national/macro-region level.

## 2. Administrative code mapping (JIS X 0401)

Japan's authoritative code system for government statistics is the
**統計に用いる標準地域コード** (Standard Regional Codes for Statistics), set
by 総務省 (MIC) in April 1970 and revised on boundary changes
([総務省](https://www.soumu.go.jp/toukei_toukatsu/index/seido/9-5.htm)). Its
first two digits are standardized separately as **JIS X 0401** (prefecture
code); the next three digits are **JIS X 0402** (municipality code), with
`000` denoting the prefecture itself
([e-Stat 統計LOD「地域に関するデータ」](https://data.e-stat.go.jp/lodw/provdata/lodRegion)).

| `admin_level` | Unit | Code pattern | Count | Example |
|---|---|---|---|---|
| 0 | National (MHLW/e-Stat aggregate) | `JP-NAT` (synthetic — not part of JIS X 0401) | 1 | `JP-NAT` |
| 1 | Prefecture | `NN` (2-digit, zero-padded, JIS X 0401) | 47 | `13` = Tokyo |

Unlike China's macro-regions (`CN-E`, `CN-C`, …, which are NBS statistical
aggregates with no formal code), **every `admin_level=1` unit in this
schema is a real, officially codified administrative division** — there is
no synthetic "region block" level in the code system itself. This module
does not define `admin_level=2` (municipality) because no official wage
figure exists at that level for any survey (see Section 7).

`classification_system` is `JIS_X_0401` for prefecture rows keyed on
geography, and `JSOC_MAJOR` / `JSOC_DETAILED` for rows keyed on the
occupation dimension (Japan Standard Occupational Classification, Rev. 5 —
[総務省 日本標準職業分類 PDF](https://www.soumu.go.jp/main_content/000395232.pdf)).

The 47-prefecture code list and official names were joined from the
machine-readable master list published by 総務省:
[全国 CSV, 2,291 records](https://www.soumu.go.jp/main_content/000323625.csv)
(mirrored in this workspace as `soumu_standard_region_codes.csv`).

### 2.1 Region blocks — an important caveat

`region_block` stores MIC's own **類型Ⅰ** 10-block grouping (Hokkaido,
Tohoku, Kanto, Hokuriku, Tokai/Chubu, Kinki, Chugoku, Shikoku, Kyushu,
Okinawa), from the 総務省「地域別表章に関するガイドライン」
([PDF](https://www.soumu.go.jp/main_content/000872772.pdf)). This is
**explicitly not a single legally-unified regional standard** — the
guideline itself says so: 「我が国の地域ブロック別の区分は、行政分野を通じて
統一的に用いられているものはなく…統計作成機関が各統計の目的に応じそれぞれ
設定している」 (p.1 of the same PDF). Competing typologies exist (e-Stat's
own 社会・人口統計体系 grouping, Cabinet Office's 地域区分 A/B/C, the 1997
Employment Structure Survey's 11-block scheme) — 類型Ⅰ was chosen here only
because MIC's guideline recommends it as the default when block-level
publication is unavoidable. Note it differs from the popular "8 regions"
taxonomy: Niigata sits in 北陸 not Chubu, Yamanashi/Nagano sit in 関東, and
Okinawa is its own block, separate from Kyushu.

## 3. Files

```
japan_wage_schema/
├── README.md
├── schema/
│   ├── japan_wage_template.csv          ← canonical column layout + worked examples
│   └── japan_wage.schema.json           ← draft-07 JSON Schema, mirrors the CSV
├── scripts/
│   ├── validate_japan_wage.py           ← standalone validator (stdlib only)
│   └── _generate_real_data.py           ← transparent record of how real_data was assembled (not part of the shipped standard)
└── real_data/
    ├── japan_wage_real.csv               ← 283 REAL rows, all officially sourced
    └── validation_report.json            ← output of running the validator on the above
```

## 4. Columns

| Column | Required | Notes |
|---|---|---|
| `admin_code` | yes | `JP-NAT` for national, else zero-padded JIS X 0401 2-digit prefecture code `01`–`47` |
| `admin_level` | yes | `0` = national, `1` = prefecture |
| `region_name_en` / `region_name_ja` | `region_name_en` required | English + native name |
| `country_iso` | yes | Always `JP` |
| `region_block` | no | 類型Ⅰ 10-block grouping name, or blank — see caveat in Section 2.1; cite [総務省 ガイドライン](https://www.soumu.go.jp/main_content/000872772.pdf) |
| `occupation_category` | no | JSOC major-group English label (12 groups A–L), `Total`, or a detailed occupation's English label when `occupation_level=detailed` |
| `occupation_code` | no | JSOC letter (`A`–`L`) for major groups; blank for `Total` or for detailed occupations |
| `occupation_level` | no | `major` \| `detailed` \| `total` |
| `wage_value` | no | Numeric. Leave blank + `data_availability=not_available` rather than guessing |
| `wage_unit` | no | `thousand_yen_per_month` (千円) — **all figures in this module are monthly, in thousands of yen**, including `annual_special_cash_earnings`, which sums a calendar year of bonuses but is still expressed in 千円 |
| `currency` | no | Always `JPY` |
| `wage_measure` | no | `contractual_cash_earnings` (きまって支給する現金給与額, includes overtime) \| `scheduled_cash_earnings` (所定内給与額, excludes overtime — MHLW's headline "賃金") \| `annual_special_cash_earnings` (年間賞与その他特別給与額, previous calendar year's bonuses) — **these three series measure different things and must never be averaged together** |
| `year`, `population` | `year` required | `population` intentionally left blank throughout — MHLW's wage survey reports *employees* (十人/tens of persons), a labour-force count, not resident population, and mixing the two would misrepresent both |
| `parent_admin_code` | no | `JP-NAT` for prefecture rows |
| `classification_system` | no | `JIS_X_0401` (prefecture rows) or `JSOC_MAJOR` / `JSOC_DETAILED` (occupation rows) |
| `data_availability` | no | Honesty flag: `national`, `prefecture`, or `not_available` |
| `source`, `last_updated` | no | Full URL required when a row has real data |

## 5. Validator

```bash
python3 scripts/validate_japan_wage.py real_data/japan_wage_real.csv --report out.json
```

Checks: required fields, `admin_level ∈ {0,1}`, admin_code pattern per level
(`JP-NAT` for national, zero-padded `01`–`47` JIS X 0401 for prefecture),
`country_iso == 'JP'`, `region_block` / `occupation_level` /
`occupation_category` (JSOC major set) / `occupation_code` (A–L) /
`wage_unit` / `currency` / `wage_measure` / `data_availability` /
`classification_system` enum validity and mutual consistency, wage-value
sanity range, duplicate `(admin_code, year, occupation_code, wage_measure)`
detection, and same-file parent-hierarchy consistency (prefecture rows
should point `parent_admin_code` at `JP-NAT`, and a national row should be
present if any prefecture rows exist). Exit code `1` only on fatal header
errors — same convention as `validate_china_wage.py` and
`validate_nuts_income.py`.

Result on the real data file: **283/283 rows clean, 0 errors, 0 warnings.**

## 6. Real data included — sources

All 283 rows in `real_data/japan_wage_real.csv` are genuine figures from
MHLW's 令和6年 (2024) 賃金構造基本統計調査 (Basic Survey on Wage Structure),
downloaded and parsed directly from e-Stat — nothing is estimated or
interpolated:

- **All 47 prefectures + national, `Total` occupation, all three wage
  measures** (144 rows) — report §3.2, source file 令和6年 都道府県別
  参考表1 「性、都道府県別きまって支給する現金給与額、所定内給与額及び年間
  賞与その他特別給与額（男女計）」,
  [statInfId 000040247959](https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247959&fileKind=4).
  Region blocks and JIS codes joined from the
  [総務省 標準地域コード CSV](https://www.soumu.go.jp/main_content/000323625.csv)
  and [類型Ⅰ definitions](https://www.soumu.go.jp/main_content/000872772.pdf).
- **National, 12 JSOC major occupation groups (A–K; `L`/不詳 excluded — see
  below), all three wage measures** (33 rows) — report §3.4, source file
  令和6年 都道府県別 第２表, 全国 column,
  [statInfId 000040247948](https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247948&fileKind=4).
- **6-prefecture × 11-occupation crosstab, `scheduled_cash_earnings` only**
  (55 rows: Tokyo, Aichi, Osaka, Fukuoka, Okinawa × 11 JSOC major groups;
  the national column is not repeated here because it is identical to the
  rows already captured from §3.4 above, and repeating it would create an
  exact duplicate key rather than new information) — report §3.5, source
  files [000040247948](https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247948&fileKind=4)
  (全国), [000040247949](https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247949&fileKind=4)
  (東京, 愛知), [000040247950](https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247950&fileKind=4)
  (大阪), [000040247951](https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247951&fileKind=4)
  (福岡, 沖縄). This is the direct proof that the crosstab is genuine: e.g.
  建設・採掘従事者 (Construction and mining workers) pays 461.2千円/month in
  Osaka vs only 305.0千円/month in Tokyo — a cell that can only exist if the
  survey truly tabulates occupation *within* prefecture.
- **17 detailed occupations, national level, all three wage measures** (51
  rows) — report §3.6, a representative sample (physicians, nurses,
  software developers, taxi drivers, carpenters, aircraft pilots, etc.)
  out of the ~145 detailed occupations MHLW publishes, source file 令和6年
  都道府県別 第３表,
  [statInfId 000040247952](https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247952&fileKind=4).

**Row count check:** 144 (Total × 47 prefectures + national × 3 measures) +
33 (12 JSOC major groups × national × 3 measures, minus the unpublished `L`
cell) + 55 (11 occupations × 5 non-national prefectures, scheduled only) +
51 (17 detailed occupations × national × 3 measures) = **283 rows**.

## 7. What's NOT available

**No municipality-level (市区町村) wage data exists anywhere in Japan's
official statistics — full stop.** This is the direct Japanese analog of
China's "no city/county occupation data" gap, confirmed across every
source checked in the source report (§4):

- **賃金構造基本統計調査** (the primary wage-by-occupation source): every
  geographic result table in the survey tree sits under the heading
  **都道府県別** — there is no 市区町村 branch at all. Its own grossing
  factors are computed at 都道府県 × 産業 × 事業所規模 level, never finer
  ([概況 dl/14.pdf](https://www.mhlw.go.jp/toukei/itiran/roudou/chingin/kouzou/z2024/dl/14.pdf)).
- **毎月勤労統計調査** (Monthly Labour Survey): prefecture is the design
  unit by construction — 「地方調査にあってはその都道府県別の変動を毎月
  明らかにすることを目的とし」
  ([JILPT](https://www.jil.go.jp/kokunai/statistics/shozai/html/m01.html))
  — and it carries no occupation dimension either.
- **就業構造基本調査** (Employment Structure Survey) goes *below*
  prefecture, but only to 政令指定都市 / 県庁所在都市 / 人口30万以上の市
  (not all ~1,700 municipalities), and its variable is a **headcount
  distribution across income brackets**, not an average wage
  ([集計事項一覧（地域編）](https://www.stat.go.jp/data/shugyou/2022/zuhyou/tablelist-b.xlsx)).
- **市町村税課税状況等の調** (総務省) does cover every municipality, but the
  variable is **課税対象所得** (taxable income of residents), a tax
  aggregate with no occupation dimension — a different universe from an
  employer-side wage survey
  ([令和7年度 調査](https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/ichiran09_25.html)).
- **経済センサス‐活動調査**: a municipality-level 給与総額 (total wage bill)
  table is **not confirmed** to exist from the official results index
  ([統計局 結果](https://www.stat.go.jp/data/e-census/2021/kekka/index.html)).

Two smaller gaps, also not silently dropped:

- The **`L` (不詳 / Workers not classifiable by occupation)** JSOC major
  group is explicitly suppressed in the source table — MHLW prints `-` for
  all three wage measures for this row in 表2 (report §3.4). Rather than
  inventing a zero or blank placeholder row, this category is omitted from
  `real_data/japan_wage_real.csv` entirely.
- Only **17 of the ~145 detailed occupations** are represented (a curated,
  clearly labelled sample per the task scope), and only **5 of 47
  prefectures** appear in the occupation × prefecture crosstab (the exact
  6 columns — national + 5 prefectures — that the report's §3.5 table
  extracted from the 4 regional workbook files; the national column itself
  is folded into the §3.4 national rows rather than duplicated, per the
  dedup note above). Extending either requires parsing the remaining
  columns/rows of the same already-identified source files — no new
  sources needed, just more extraction (see Section 8).

## 8. Extending this later

- **Full crosstab**: the 4 workbook files behind §3.5
  ([000040247948](https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247948&fileKind=4),
  [000040247949](https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247949&fileKind=4),
  [000040247950](https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247950&fileKind=4),
  [000040247951](https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247951&fileKind=4))
  already contain **all 47 prefectures**, not just the 6 extracted here —
  parsing every prefecture column in each file would take the crosstab
  from 5 prefectures to all 47 with no new data collection required.
- **Full detailed-occupation table**: [statInfId 000040247952](https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247952&fileKind=4)
  contains all ~145 detailed occupations at national level (already saved
  in this workspace as `jp_wage_2024_national_detailed_occ.json`), and its
  companion prefecture-split files would extend detailed occupations to
  the prefecture level too.
- **Sex-disaggregated rows**: every source table also carries 男 (male) and
  女 (female) columns alongside 男女計 (both sexes, used throughout this
  module) — a straightforward additional dimension to ingest from the same
  files.
- **Time series**: the same survey has run annually since 1948; 2023
  (令和5) figures for the JSOC-major-group table are already quoted in the
  source report (§3.4) as a year-over-year check, and 2025 (令和7) prefecture
  × occupation microtables were published 2026-03-24, though their
  statInfIds were not yet enumerated as of this report.
- **Monthly Labour Survey cross-check series**: §3.3 of the source report
  gives an independent, yen-denominated, no-occupation prefecture series
  ([06C1T1.xlsx](https://www.mhlw.go.jp/toukei/itiran/roudou/monthly/r06/xlsx/06C1T1.xlsx))
  that could be added as a `measure_family` alongside the wage-structure
  survey for time-series interpolation between wage-census years.
- Re-check e-Stat periodically for whether 経済センサス‐活動調査 ever adds a
  municipality-level 給与総額 table — not confirmed to exist today, but not
  exhaustively ruled out either (see report §7).

## 9. Fits into the existing Preferendum pipeline

In `nuts_income_schema/seed/seed_countries_50.sql`, Japan (`JP`) would be
seeded as a Tier A/B country (fully in-NUTS-scope countries are Tier A;
Japan, like China, is `in_nuts_scope = FALSE` since NUTS is EU-only) — this
module is the non-NUTS, country-specific data source that
`classification_system = 'CUSTOM'` was designed to accommodate. Unlike
China, Japan's data is clean enough that it could realistically graduate
into a shared `staging_regional_wage_by_occupation` table (JPY, occupation ×
prefecture grain, JIS X 0401 codes) with minimal special-casing — no macro-
region-only fallback logic is needed, since the finest geography (prefecture)
already carries the full occupation breakdown. The one adaptation still
required versus a pure NUTS-style load is the `wage_unit` field: MHLW's
survey reports monthly figures in thousands of yen (千円), not the annual
EUR figures NUTS income data uses, so unit and currency conversion must
happen at ingestion time, not left implicit.
