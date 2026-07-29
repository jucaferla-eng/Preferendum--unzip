# South Korea Regional & Occupational Wage Data Standard

Companion module to the China and Japan wage-schema modules. Korea **breaks
the single-table pattern** used for China/Japan/Russia entirely — this
module ships **two disjoint fact tables**, not one occupation×region
crosstab, because no such crosstab exists in Korean official statistics.

## 1. Why Korea isn't a 1:1 port of the China/Japan/Russia pattern

The China, Japan, and Russia modules are each built around a single fact
table because each country's national statistics agency publishes at least
one genuine occupation × region wage crosstab (coarse-grained in China's
case, but real). **Korea has no equivalent table, at any granularity.**

There are two separate official wage surveys, from the same producer
(고용노동부 / Ministry of Employment and Labor) but with **completely
non-overlapping dimensions**:

| | 고용형태별근로실태조사 (Survey on Labor Conditions by Employment Type) | 사업체노동력조사 (Survey on Labor Force at Establishments) |
|---|---|---|
| Publishes wage **by occupation** | **Yes** — 9 KSCO major groups, national | No |
| Publishes wage **by region (sido)** | **No — zero regional dimension** | **Yes** — all 17 sido |
| Reference period (2024) | June 2024 payroll | April 2024 |
| Universe | 상용근로자, 5+ person establishments | 상용근로자, 1+ person establishments |

A full-text scan of the 2024 report (`kr_report.txt`, 18,099 lines) turns up
**zero** occurrences of "시도" and **zero** of "지역." This is not an
extraction gap — Statistics Korea (KOSTAT) confirmed it directly in an
official KOSIS Q&A answer:

> *"작성기관에 문의한 결과 고용형태별근로실태조사는 전국 자료로 시도별로
> 관리하지 않고 있으며, 사업체노동력조사는 성별자료는 따로 관리하지
> 않고 있습니다"*
> — [KOSIS Q&A #24532](https://kosis.kr/civilComplaint/qnaDetail.do?boardIdx=24532)

In plain terms: the occupation-wage survey has no region field, and the
region-wage survey has no occupation field. There is no shared table to
merge them into, and no third source that cross-tabulates both. A third
survey designed for regional granularity, 지역별고용조사 (Regional
Employment Survey, produced by KOSTAT itself), does publish an
occupation-linked wage variable — but only as **national wage-band
percentage shares** (e.g. "41.9% of Professionals earn ≥400만원
nationally"), never a mean wage, and never broken out by region. See
§3.2 of `south_korea_wage_data_availability_report.md` for the full
citation trail.

**Design decision (per the source report's own §6 recommendation):** build
two independent fact tables joined only by `country_iso` (and, loosely,
`year`) — never by region or occupation. **No merged/crosstab table is
included in this module, and none should be fabricated downstream** by
allocating occupation shares onto regional totals or vice versa; the
source report explicitly rules this out (§6, point 2): *"Do not create a
region × occupation wage field populated by allocation... commission an
MDIS tabulation instead"* ([KOSIS Q&A #21660](https://kosis.kr/civilComplaint/qnaDetail.do?boardIdx=21660)).

## 2. Admin code / classification mapping

### 2.1 SGIS sido codes (`kr_wage_by_region`)

2-digit codes from the SGIS (통계지리정보서비스) Open API sido reference
([SGIS – 시도 코드](https://sgis.mods.go.kr/developer/html/openApi/api/dataCode/SidoCode.html)).
This module maps the source table's `00` (전국) row to the synthetic code
`KR-NAT` for consistency with the China/Japan modules' `-NAT` convention;
all real sido codes (11–39) are used unmodified.

| Code | Region (EN) | Region (KO) | Type |
|---|---|---|---|
| KR-NAT | Whole country | 전국 | national aggregate (사업체노동력조사 estimate, not a weighted mean of the 17 sido) |
| 11 | Seoul | 서울특별시 | Special City |
| 21 | Busan | 부산광역시 | Metropolitan City |
| 22 | Daegu | 대구광역시 | Metropolitan City |
| 23 | Incheon | 인천광역시 | Metropolitan City |
| 24 | Gwangju | 광주광역시 | Metropolitan City |
| 25 | Daejeon | 대전광역시 | Metropolitan City |
| 26 | Ulsan | 울산광역시 | Metropolitan City |
| 29 | Sejong | 세종특별자치시 | Special Self-Governing City |
| 31 | Gyeonggi | 경기도 | Province |
| 32 | Gangwon | 강원특별자치도 | Special Self-Governing Province |
| 33 | Chungbuk | 충청북도 | Province |
| 34 | Chungnam | 충청남도 | Province |
| 35 | Jeonbuk | 전북특별자치도 | Special Self-Governing Province |
| 36 | Jeonnam | 전라남도 | Province |
| 37 | Gyeongbuk | 경상북도 | Province |
| 38 | Gyeongnam | 경상남도 | Province |
| 39 | Jeju | 제주특별자치도 | Special Self-Governing Province |

`classification_system = "SGIS_SIDO"` for every row in this table. There is
no `admin_level 2` or `3` in this module — see §7.

### 2.2 KSCO 7th-revision major groups (`kr_wage_by_occupation`)

The 2024 wage-by-occupation report uses **KSCO 7th revision** (통계청 고시,
2017-07-03), which has 10 major groups (대분류). Wage tables **exclude**
군인 (Armed Forces) — only 9 civilian groups appear (plus this module's
synthetic `"All occupations"` total row, `occupation_code="0"`):

| `occupation_code` | Korean (as printed in the wage table) | `occupation_category` (English) |
|---|---|---|
| 0 | 전체 | All occupations (total, synthetic code — not an official KSCO digit) |
| 1 | 관리자 | Managers |
| 2 | 전문가 및 관련 종사자 | Professionals and related workers |
| 3 | 사무 종사자 | Clerks |
| 4 | 서비스 종사자 | Service workers |
| 5 | 판매 종사자 | Sales workers |
| 6 | 농림·어업 숙련 종사자 | Skilled agricultural, forestry and fishery workers |
| 7 | 기능원 및 관련 기능 종사자 | Craft and related trades workers |
| 8 | 장치·기계 조작 및 조립 종사자 | Equipment, machine operating and assembling workers |
| 9 | 단순 노무 종사자 | Elementary workers |
| A | 군인 | Armed Forces — **excluded from wage tables**, never appears in this module |

`classification_system = "KSCO_7TH_MAJOR"` for every row. Note: 지역별고용조사
migrates to **KSCO 8th revision** from 2024 하반기 onward, but that survey
does not publish mean wage (only band shares, §3.3 of the source report),
so KSCO 8 data is out of scope for this module.

## 3. Files

```
korea_wage_schema/
├── README.md
├── schema/
│   ├── kr_wage_by_region_template.csv        ← canonical column layout + worked examples (region table)
│   ├── kr_wage_by_region.schema.json         ← draft-07 JSON Schema for the region table
│   ├── kr_wage_by_occupation_template.csv    ← canonical column layout + worked examples (occupation table)
│   └── kr_wage_by_occupation.schema.json     ← draft-07 JSON Schema for the occupation table
├── scripts/
│   └── validate_korea_wage.py                ← single validator, handles BOTH CSVs (stdlib only)
└── real_data/
    ├── kr_wage_by_region_real.csv            ← 90 REAL rows (18 regions × 5 wage components), officially sourced
    ├── kr_wage_by_occupation_real.csv        ← 10 REAL rows (national total + 9 KSCO major groups), officially sourced
    └── validation_report.json                ← combined output of running the validator on both files above
```

## 4. Columns

### 4.1 `kr_wage_by_region` (18 regions: KR-NAT + 17 sido; industry-based, NO occupation dimension)

| Column | Required | Notes |
|---|---|---|
| `admin_code` | yes | `KR-NAT` or 2-digit SGIS sido code 11–39 |
| `admin_level` | yes | `0` = national, `1` = sido (17 units) |
| `region_name_en` | yes | English region name |
| `region_name_ko` | no | Native Korean name |
| `country_iso` | yes | Always `KR` |
| `wage_value` | no | Leave blank + `data_availability=not_available` rather than guessing |
| `currency` | no | `KRW_thousand` — source publishes in 천원 |
| `wage_period` | no | `monthly` |
| `wage_measure` | no | One of `wage_total`, `regular_pay`, `overtime_pay`, `special_pay`, `monthly_pay` — these are components of one another (월급여액 = 정액급여+초과급여; 임금총액 = 월급여액+특별급여), **never average across them** |
| `year`, `population` | year required | |
| `parent_admin_code` | no | `KR-NAT` for all sido rows |
| `classification_system` | no | Always `SGIS_SIDO` |
| `data_availability` | no | `national`, `sido`, or `not_available` — this table structurally stops at sido |
| `source`, `last_updated` | no | Full URL required when a row has real data |

This table has **no occupation dimension whatsoever** — it comes from
사업체노동력조사, which cross-tabulates 행정구역(시도) × 산업 × 규모
(industry and establishment size), not occupation
([KOSIS Q&A #24532](https://kosis.kr/civilComplaint/qnaDetail.do?boardIdx=24532)).

### 4.2 `kr_wage_by_occupation` (10 rows: national total + 9 KSCO major groups; NO region dimension)

| Column | Required | Notes |
|---|---|---|
| `admin_code` | yes | Always `KR-NAT` — this table structurally cannot have a region value |
| `occupation_category` | yes | KSCO 7th-revision major-group English label (9 civilian groups + synthetic "All occupations" total) |
| `occupation_code` | no | KSCO major-group digit (`0` synthetic total, `1`–`9` official; `A` Armed Forces never appears) |
| `wage_value` | yes* | *Required unless `data_availability` documents an explicit gap. Leave blank + appropriate `data_availability` rather than guessing |
| `currency` | no | `KRW_thousand` |
| `wage_period` | no | `monthly` |
| `wage_measure` | no | `monthly_wage_total` (월 임금총액) — the only measure populated in this pass |
| `year` | yes | |
| `classification_system` | no | Always `KSCO_7TH_MAJOR` |
| `data_availability` | no | **Only** `national_only` should ever appear — this table cannot structurally have finer granularity |
| `source`, `last_updated` | no | Full URL required when a row has real data |
| `country_iso` | yes | Always `KR` |

## 5. Validator

```bash
python3 scripts/validate_korea_wage.py real_data/kr_wage_by_region_real.csv real_data/kr_wage_by_occupation_real.csv --report real_data/validation_report.json
```

The script auto-detects which table each file is (by filename containing
"region" or "occupation", falling back to header sniffing) and validates
each independently, then writes one combined JSON report. Checks per table:
required fields, `admin_code` pattern (`KR-NAT` vs 2-digit sido, or always
`KR-NAT` for the occupation table), `admin_level ∈ {0,1}` for the region
table, enum validity for `wage_measure` / `data_availability` /
`classification_system` / `occupation_category` / `occupation_code`,
`country_iso == 'KR'`, wage-value sanity range, and duplicate-key detection
within each table (`(admin_code, year, wage_measure)` for the region table;
`(occupation_category, year, wage_measure)` for the occupation table — no
duplicate check spans the two tables, since they share no keys other than
`country_iso`). Exit code `1` only on fatal header errors — same convention
as `validate_china_wage.py`.

**Result on the real data files:**

```
kr_wage_by_region_real.csv:      90/90 rows clean, 0 errors, 0 warnings
kr_wage_by_occupation_real.csv:  10/10 rows clean, 0 errors, 0 warnings
```

## 6. Real data included — sources

**`kr_wage_by_region_real.csv` (90 rows = 18 regions × 5 wage components,
April 2024):** MOEL press release *"2024년 8월 사업체노동력조사 및 2024년
4월 시도별 임금·근로시간조사 결과."* Universe: 상용근로자 1인 이상 사업체의
상용근로자. Values verified against the fetched release PDF
([hamancci.korcham.net mirror](https://hamancci.korcham.net/file/dext5uploaddata/2024/2024%EB%85%84%208%EC%9B%94%20%EC%82%AC%EC%97%85%EC%B2%B4%EB%85%B8%EB%8F%99%EB%A0%A5%EC%A1%B0%EC%82%AC%20%EB%B0%8F%202024%EB%85%84%204%EC%9B%94%20%EC%8B%9C%EB%8F%84%EB%B3%84%20%EC%9E%84%EA%B8%88%C2%B7%EA%B7%BC%EB%A1%9C%EC%8B%9C%EA%B0%84%EC%A1%B0%EC%82%AC%20%EA%B2%B0%EA%B3%BC_.pdf))
and corroborated on the official MOEL page
([고용노동부 보도자료](https://www.moel.go.kr/news/enews/report/enewsView.do?news_seq=17112)),
which also carries the index values (Seoul 112.2, Ulsan 110.9, Jeju 78.7 of
national). All 5 wage components (임금총액/wage_total, 정액급여/regular_pay,
초과급여/overtime_pay, 특별급여/special_pay, 월급여액/monthly_pay) for the
national total and all 17 sido were transcribed directly from the report's
§3.1 table.

**`kr_wage_by_occupation_real.csv` (10 rows = national total + 9 KSCO major
groups, June 2024):** 고용노동부, 고용형태별근로실태조사보고서 2024년판,
table "직종별 월 임금총액" (`kr_report.txt` lines 2185–2196, PDF at
[laborstat.moel.go.kr](https://laborstat.moel.go.kr/cmm/fms/FileDown.do?atchFileId=FILE_000000000054271&fileSn=0)).
Universe: 상용근로자 5인 이상 사업체의 상용근로자; reference: June 2024
payroll period; unit 천원; values cross-checked against the raw extracted
text at `kr_report.txt` lines 2185–2196, which independently confirms
관리자 12,223천원 is 5.5× 서비스종사자 2,226천원, matching the report's own
stated ratio.

## 7. What's NOT available

- **No occupation × region wage crosstab exists anywhere in Korean official
  statistics**, at any granularity. KOSTAT confirmed this explicitly:
  *"고용형태별근로실태조사는 전국 자료로 시도별로 관리하지 않고 있으며..."*
  ([KOSIS Q&A #24532](https://kosis.kr/civilComplaint/qnaDetail.do?boardIdx=24532)).
  This module therefore does **not** contain a merged table, and none
  should be fabricated downstream by allocation or interpolation.
- **No wage data at all — by occupation, region, or otherwise — is
  published at 시군구 (city/county/district) level**, for either survey.
  KOSTAT's own answer to a direct KOSIS user question about 시군구 평균임금
  states that this can only be obtained by the user tabulating **MDIS
  (Microdata Integrated Service)** microdata directly — path: 회원가입/로그인
  → 자료이용 → 다운로드서비스 → 노동 → 지역별고용조사 → 상반기 또는 하반기
  A형 — because the published statistics do not go finer than sido
  ([KOSIS Q&A #21660](https://kosis.kr/civilComplaint/qnaDetail.do?boardIdx=21660)).
  Corroborated by the dedicated 228-시군구 publication itself (*2025년
  하반기 지역별고용조사 시군구 주요고용지표*), in which the string "임금"
  appears only 7 times, every occurrence referring to *share of employees*,
  never a wage amount.
- **Occupation-linked regional wage bands** (지역별고용조사) exist only as
  **national** wage-band percentage shares (e.g. "82.9% of Managers earn
  ≥400만원"), never a mean, and never broken out by region — see §3.3 of
  `south_korea_wage_data_availability_report.md`. Not included in this
  module's fact tables because it is neither a mean wage nor
  region-specific.
- **Institutional naming note:** Statistics Korea / KOSTAT (통계청) has been
  reorganized and renamed **국가데이터처** (National Data Processing Agency /
  "Ministry of Data and Statistics"); its domains now resolve as
  `mods.go.kr`, `sgis.mods.go.kr`, `kssc.mods.go.kr`, `mdis.mods.go.kr`,
  with legacy `kostat.go.kr` / `kosis.kr` still live. Both hostnames appear
  in citations throughout this module because both were fetched during
  research. Also note: 고용형태별근로실태조사 is scheduled to be renamed
  **고용형태별노동실태조사 from 2026** — future data pulls should watch for
  this rename breaking hard-coded source names.

## 8. Extending this later

- **Sub-major / minor occupation detail:** the 2024 report also publishes
  직종 중분류 (51 categories) and 소분류 (132 categories) wage tables
  (`kr_report.txt` TOC lines 115–137) — not yet transcribed into this
  module. Would require a dedicated `occupation_code` sub-level and a
  versioned `classification_system` (KSCO_7TH_SUBMAJOR /
  KSCO_7TH_MINOR).
- **Hourly wage and regular/non-regular splits by occupation:** the same
  report gives 시간당 임금총액 and 정규직/비정규직 breakdowns per
  occupation (`kr_report.txt` lines ~1118–1160) — a natural second
  `wage_measure` value (`hourly_wage_total`) to add to
  `kr_wage_by_occupation`.
- **Time series:** sido-level wage (e-지방지표 "월평균 임금 및
  임금상승률(시도)") covers **2011–2024**
  ([KOSIS Q&A #23903](https://kosis.kr/civilComplaint/qnaDetail.do?boardIdx=23903));
  only the single 2024 cross-section is loaded here. Extending to a full
  time series is straightforward with the same table structure.
- **MDIS custom tabulation:** if a genuine occupation × sido cell is ever
  required, it must be commissioned as custom microdata tabulation via
  MDIS ([KOSIS Q&A #21660](https://kosis.kr/civilComplaint/qnaDetail.do?boardIdx=21660))
  and loaded as an explicitly flagged, separately documented modeled
  estimate — never silently merged into either table here.
- **KSCO 8th revision migration:** 지역별고용조사 already uses KSCO 8 from
  2024 하반기; when 고용형태별근로실태조사 migrates too (expected with a
  future edition), add a `classification_system=KSCO_8TH_MAJOR` variant
  rather than overwriting the KSCO 7 rows.

## 9. Fits into the existing Preferendum pipeline

Unlike the China/Japan/Russia modules, this module's two tables are **not
joined on region or occupation** — there is no shared dimension to join on
besides `country_iso` (`KR`) and, loosely, `year`. Downstream consumers
should treat `kr_wage_by_region` and `kr_wage_by_occupation` as two
independent fact tables loaded into two separate staging tables (e.g.
`staging_regional_wage_kr` and `staging_occupation_wage_kr`), each keyed
only by `(country_iso, year, admin_code)` or `(country_iso, year,
occupation_code)` respectively — never attempt a join key of `(admin_code,
occupation_code)`, because no row in either table carries both a real
region and a real occupation value at the same time. Any future occupation
× region product must be modeled as a distinct, explicitly-flagged
estimate table, not derived by joining these two.
