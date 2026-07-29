#!/usr/bin/env python3
"""
One-off generator for real_data/japan_wage_real.csv.
Pulls every figure directly from japan_wage_data_availability_report.md
(sections cited below) and the supporting markdown/JSON exports in
/home/user/workspace/. Not part of the shipped module -- kept here only as a
transparent, reviewable record of how the real data file was assembled.
"""
import csv
import json

COLUMNS = [
    "admin_code", "admin_level", "region_name_en", "region_name_ja", "country_iso",
    "region_block", "occupation_category", "occupation_code", "occupation_level",
    "wage_value", "wage_unit", "currency", "wage_measure", "year", "population",
    "parent_admin_code", "classification_system", "data_availability", "source", "last_updated",
]

SANKO1_URL = "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247959&fileKind=4"
HYO2_NAT_URL = "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247948&fileKind=4"
HYO2_2_URL = "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247949&fileKind=4"  # Tokyo, Aichi
HYO2_3_URL = "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247950&fileKind=4"  # Osaka
HYO2_4_URL = "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247951&fileKind=4"  # Fukuoka, Okinawa
HYO3_URL = "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040247952&fileKind=4"
GUIDELINE_URL = "https://www.soumu.go.jp/main_content/000872772.pdf"
SOUMU_CODES_URL = "https://www.soumu.go.jp/main_content/000323625.csv"
LAST_UPDATED = "2025-03-17"  # e-Stat publication date of the R6/2024 wage-structure survey (report Sec 2.1)

rows = []

# ---------------------------------------------------------------------------
# 1. All 47 prefectures + national, Total occupation, §3.2 (参考表1)
#    columns: contractual / scheduled / annual-special / employees(tens)
# ---------------------------------------------------------------------------
PREF_SEC32 = [
    ("00", "National", "全国", None, 359.6, 330.4, 954.7, 2925146),
    ("01", "Hokkaido", "北海道", "Hokkaido", 310.3, 288.5, 722.5, 95376),
    ("02", "Aomori", "青森県", "Tohoku", 283, 259.9, 642.8, 22805),
    ("03", "Iwate", "岩手県", "Tohoku", 287.6, 267, 717.5, 24630),
    ("04", "Miyagi", "宮城県", "Tohoku", 325.1, 298.1, 829.2, 51287),
    ("05", "Akita", "秋田県", "Tohoku", 284.9, 265.5, 662.8, 18140),
    ("06", "Yamagata", "山形県", "Tohoku", 294, 272.4, 733.3, 22320),
    ("07", "Fukushima", "福島県", "Tohoku", 301.6, 276.3, 705.8, 38873),
    ("08", "Ibaraki", "茨城県", "Kanto", 342.6, 312.5, 906.4, 63842),
    ("09", "Tochigi", "栃木県", "Kanto", 346.3, 314.4, 825.3, 45515),
    ("10", "Gunma", "群馬県", "Kanto", 334.6, 302.5, 848.5, 44341),
    ("11", "Saitama", "埼玉県", "Kanto", 353, 322.3, 859.1, 117477),
    ("12", "Chiba", "千葉県", "Kanto", 349.2, 320.3, 820.9, 99752),
    ("13", "Tokyo", "東京都", "Kanto", 434.3, 403.7, 1232.2, 582752),
    ("14", "Kanagawa", "神奈川県", "Kanto", 388.7, 355.8, 1106.3, 181500),
    ("15", "Niigata", "新潟県", "Hokuriku", 313, 288.7, 770.4, 49899),
    ("16", "Toyama", "富山県", "Hokuriku", 320.1, 295.2, 811.3, 26228),
    ("17", "Ishikawa", "石川県", "Hokuriku", 335.4, 308.4, 866.1, 27059),
    ("18", "Fukui", "福井県", "Hokuriku", 317.1, 290.9, 835.7, 17067),
    ("19", "Yamanashi", "山梨県", "Kanto", 328.5, 304.4, 794.7, 17216),
    ("20", "Nagano", "長野県", "Kanto", 324, 298.6, 901.8, 45787),
    ("21", "Gifu", "岐阜県", "Tokai/Chubu", 316.9, 289.3, 754.1, 44065),
    ("22", "Shizuoka", "静岡県", "Tokai/Chubu", 339.2, 309.4, 920.8, 89128),
    ("23", "Aichi", "愛知県", "Tokai/Chubu", 368.2, 332.6, 1065.9, 194434),
    ("24", "Mie", "三重県", "Tokai/Chubu", 346.7, 309.6, 890.4, 38153),
    ("25", "Shiga", "滋賀県", "Kinki", 348.6, 312.9, 917.1, 31311),
    ("26", "Kyoto", "京都府", "Kinki", 354.4, 323.3, 909.3, 54898),
    ("27", "Osaka", "大阪府", "Kinki", 376.9, 348, 1040.9, 234592),
    ("28", "Hyogo", "兵庫県", "Kinki", 349.1, 318.8, 940.8, 105297),
    ("29", "Nara", "奈良県", "Kinki", 343.5, 312.7, 783.3, 16728),
    ("30", "Wakayama", "和歌山県", "Kinki", 323.1, 297.3, 812.1, 15718),
    ("31", "Tottori", "鳥取県", "Chugoku", 291.1, 269.1, 592.9, 10529),
    ("32", "Shimane", "島根県", "Chugoku", 295.8, 269.3, 757.2, 12768),
    ("33", "Okayama", "岡山県", "Chugoku", 325.4, 296.9, 791.2, 42414),
    ("34", "Hiroshima", "広島県", "Chugoku", 344.4, 312.7, 895.6, 63554),
    ("35", "Yamaguchi", "山口県", "Chugoku", 328.6, 298.3, 886.5, 26698),
    ("36", "Tokushima", "徳島県", "Shikoku", 315.6, 293, 839.7, 13473),
    ("37", "Kagawa", "香川県", "Shikoku", 327.1, 297.2, 807.5, 22978),
    ("38", "Ehime", "愛媛県", "Shikoku", 306.2, 281.5, 752.3, 24756),
    ("39", "Kochi", "高知県", "Shikoku", 293.9, 273.3, 678.2, 11626),
    ("40", "Fukuoka", "福岡県", "Kyushu", 338.3, 308, 871.6, 113916),
    ("41", "Saga", "佐賀県", "Kyushu", 301.2, 276.5, 727.1, 17023),
    ("42", "Nagasaki", "長崎県", "Kyushu", 298.5, 278.4, 715.1, 23456),
    ("43", "Kumamoto", "熊本県", "Kyushu", 307, 283.1, 765.5, 32428),
    ("44", "Oita", "大分県", "Kyushu", 309.6, 285, 758.6, 20608),
    ("45", "Miyazaki", "宮崎県", "Kyushu", 281.1, 259.8, 653.8, 19625),
    ("46", "Kagoshima", "鹿児島県", "Kyushu", 294.5, 273.9, 722.3, 26832),
    ("47", "Okinawa", "沖縄県", "Okinawa", 283.3, 266.3, 535.4, 26271),
]

for code, en, ja, block, contractual, scheduled, special, emp in PREF_SEC32:
    is_nat = code == "00"
    admin_code = "JP-NAT" if is_nat else code
    admin_level = 0 if is_nat else 1
    parent = "" if is_nat else "JP-NAT"
    cls = "" if is_nat else "JIS_X_0401"
    avail = "national" if is_nat else "prefecture"
    region_block = "" if is_nat else block

    for measure, val in (
        ("contractual_cash_earnings", contractual),
        ("scheduled_cash_earnings", scheduled),
        ("annual_special_cash_earnings", special),
    ):
        rows.append({
            "admin_code": admin_code, "admin_level": admin_level,
            "region_name_en": en, "region_name_ja": ja, "country_iso": "JP",
            "region_block": region_block, "occupation_category": "Total",
            "occupation_code": "", "occupation_level": "total",
            "wage_value": val, "wage_unit": "thousand_yen_per_month", "currency": "JPY",
            "wage_measure": measure, "year": 2024, "population": "",
            "parent_admin_code": parent, "classification_system": cls,
            "data_availability": avail, "source": SANKO1_URL, "last_updated": LAST_UPDATED,
        })

# ---------------------------------------------------------------------------
# 2. National, 12 JSOC major occupation groups, §3.4 (all three measures)
# ---------------------------------------------------------------------------
JSOC_MAJOR = [
    ("A", "Administrative and managerial workers", "管理的職業従事者", 579.9, 571.6, 2213.1),
    ("B", "Professional and engineering workers", "専門的・技術的職業従事者", 403.1, 370.6, 1147),
    ("C", "Clerical workers", "事務従事者", 346.2, 321.4, 999),
    ("D", "Sales workers", "販売従事者", 348.6, 325.8, 940.1),
    ("E", "Service workers", "サービス職業従事者", 274, 254.7, 432.5),
    ("F", "Security workers", "保安職業従事者", 264, 230.3, 307.9),
    ("G", "Agriculture, forestry, and fishery workers", "農林漁業従事者", 261, 248.9, 386),
    ("H", "Manufacturing process workers", "生産工程従事者", 314, 276, 781.6),
    ("I", "Transport and machine operation workers", "輸送・機械運転従事者", 354, 293, 502.9),
    ("J", "Construction and mining workers", "建設・採掘従事者", 343.3, 312.7, 720.5),
    ("K", "Carrying, cleaning, packaging, and related workers", "運搬・清掃・包装等従事者", 274.9, 248.5, 470.2),
    # L (不詳 / Unknown) explicitly has no published wage cells ("-") per §3.4 -- skipped, not invented.
]

for code, en, ja, contractual, scheduled, special in JSOC_MAJOR:
    for measure, val in (
        ("contractual_cash_earnings", contractual),
        ("scheduled_cash_earnings", scheduled),
        ("annual_special_cash_earnings", special),
    ):
        rows.append({
            "admin_code": "JP-NAT", "admin_level": 0,
            "region_name_en": "National", "region_name_ja": "全国", "country_iso": "JP",
            "region_block": "", "occupation_category": en,
            "occupation_code": code, "occupation_level": "major",
            "wage_value": val, "wage_unit": "thousand_yen_per_month", "currency": "JPY",
            "wage_measure": measure, "year": 2024, "population": "",
            "parent_admin_code": "JP-NAT", "classification_system": "JSOC_MAJOR",
            "data_availability": "national", "source": HYO2_NAT_URL, "last_updated": LAST_UPDATED,
        })

# ---------------------------------------------------------------------------
# 3. 6-prefecture x occupation crosstab, §3.5 -- scheduled_cash_earnings only
#    (the crosstab table only reports 所定内給与額 per the report)
# ---------------------------------------------------------------------------
CROSSTAB_PREFS = [
    # National column omitted here -- it's the exact same MHLW national scheduled_cash_earnings
    # figure already carried by the JSOC-major-group rows in section 2 above; repeating it under
    # a different generation loop would create an exact (admin_code, occupation_code, wage_measure)
    # duplicate rather than new information. See README Sec 6 note on crosstab dedup.
    ("13", "Tokyo", "東京都", "13", 1, "Kanto", "JIS_X_0401", HYO2_2_URL),
    ("23", "Aichi", "愛知県", "23", 1, "Tokai/Chubu", "JIS_X_0401", HYO2_2_URL),
    ("27", "Osaka", "大阪府", "27", 1, "Kinki", "JIS_X_0401", HYO2_3_URL),
    ("40", "Fukuoka", "福岡県", "40", 1, "Kyushu", "JIS_X_0401", HYO2_4_URL),
    ("47", "Okinawa", "沖縄県", "47", 1, "Okinawa", "JIS_X_0401", HYO2_4_URL),
]

CROSSTAB_VALUES = {
    # occ_code: (occ_en, [tokyo, aichi, osaka, fukuoka, okinawa])  -- national column dropped, see note above
    "A": ("Administrative and managerial workers", [667.4, 563.8, 565.6, 524.6, 439.1]),
    "B": ("Professional and engineering workers", [418.5, 361.9, 377.5, 349.2, 309.3]),
    "C": ("Clerical workers", [380.8, 320.3, 327.5, 286.1, 248.9]),
    "D": ("Sales workers", [380.7, 337.8, 359.6, 316.9, 245.8]),
    "E": ("Service workers", [290.3, 259.4, 264, 243.1, 227.3]),
    "F": ("Security workers", [234.8, 216.9, 237, 223.4, 202.7]),
    "G": ("Agriculture, forestry, and fishery workers", [253.4, 195.4, 341.6, 204.4, 221.7]),
    "H": ("Manufacturing process workers", [311.4, 297.2, 291.7, 260.3, 224.9]),
    "I": ("Transport and machine operation workers", [372.7, 317.5, 308.2, 260, 259.3]),
    "J": ("Construction and mining workers", [305, 320.8, 461.2, 314.2, 257]),
    "K": ("Carrying, cleaning, packaging, and related workers", [276.2, 265.3, 243.2, 251.9, 220.2]),
}

for occ_code, (occ_en, vals) in CROSSTAB_VALUES.items():
    for (code, en, ja, admin_code, admin_level, block, cls, src), val in zip(CROSSTAB_PREFS, vals):
        is_nat = admin_code == "JP-NAT"
        rows.append({
            "admin_code": admin_code, "admin_level": admin_level,
            "region_name_en": en, "region_name_ja": ja, "country_iso": "JP",
            "region_block": block, "occupation_category": occ_en,
            "occupation_code": occ_code, "occupation_level": "major",
            "wage_value": val, "wage_unit": "thousand_yen_per_month", "currency": "JPY",
            "wage_measure": "scheduled_cash_earnings", "year": 2024, "population": "",
            "parent_admin_code": "" if is_nat else "JP-NAT", "classification_system": cls,
            "data_availability": "national" if is_nat else "prefecture",
            "source": src, "last_updated": LAST_UPDATED,
        })

# ---------------------------------------------------------------------------
# 4. Sample of detailed occupations, §3.6, national level, all 3 measures
# ---------------------------------------------------------------------------
DETAILED = [
    ("医師", "Physicians", 44.1, 1025.9, 911.6, 1069.3),
    ("歯科医師", "Dentists", 36.2, 909.2, 895, 444.8),
    ("薬剤師", "Pharmacists", 40.9, 430.8, 407, 823.6),
    ("看護師", "Registered nurses", 41.2, 363.5, 329.6, 835),
    ("保育士", "Nursery school teachers", 39.5, 277.2, 270.3, 741.7),
    ("小・中学校教員", "Elementary and junior high school teachers", 42.3, 459, 447.9, 1757.4),
    ("システムコンサルタント・設計者", "Systems consultants and designers", 41.4, 480.7, 431.7, 1757.3),
    ("ソフトウェア作成者", "Software developers", 38, 386.2, 357, 1106.8),
    ("販売店員", "Sales clerks", 42.7, 271.2, 254.8, 439.9),
    ("介護職員（医療・福祉施設等）", "Care workers (medical and welfare facilities)", 45.2, 271, 255.4, 508.3),
    ("飲食物調理従事者", "Cooks", 45.2, 278.2, 251.3, 356.4),
    ("警備員", "Security guards", 52.9, 268.3, 230.6, 318.5),
    ("タクシー運転者", "Taxi drivers", 60.2, 327.3, 283.6, 220.9),
    ("営業用大型貨物自動車運転者", "Heavy-duty truck drivers (commercial)", 50.9, 377.4, 299.9, 390.5),
    ("大工", "Carpenters", 40.6, 330.5, 301.2, 520.8),
    ("ビル・建物清掃員", "Building cleaners", 52.8, 222.4, 211.1, 194.1),
    ("航空機操縦士", "Aircraft pilots", 40.4, 1268.4, 1217.7, 1749.9),
]

for ja, en, age, contractual, scheduled, special in DETAILED:
    for measure, val in (
        ("contractual_cash_earnings", contractual),
        ("scheduled_cash_earnings", scheduled),
        ("annual_special_cash_earnings", special),
    ):
        rows.append({
            "admin_code": "JP-NAT", "admin_level": 0,
            "region_name_en": "National", "region_name_ja": "全国", "country_iso": "JP",
            "region_block": "", "occupation_category": en,
            "occupation_code": "", "occupation_level": "detailed",
            "wage_value": val, "wage_unit": "thousand_yen_per_month", "currency": "JPY",
            "wage_measure": measure, "year": 2024, "population": "",
            "parent_admin_code": "JP-NAT", "classification_system": "JSOC_DETAILED",
            "data_availability": "national", "source": HYO3_URL, "last_updated": LAST_UPDATED,
        })

# ---------------------------------------------------------------------------
# write out
# ---------------------------------------------------------------------------
out_path = "/home/user/workspace/japan_wage_schema/real_data/japan_wage_real.csv"
with open(out_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=COLUMNS)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)

print(f"Wrote {len(rows)} rows to {out_path}")
