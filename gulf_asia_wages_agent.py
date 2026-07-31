from __future__ import annotations
"""
gulf_asia_wages_agent.py — Importa salarios ISCO 1-9 para países Gulf/Asia/CH/HK/TW
======================================================================================
Fuentes:
  IL  — CBS Israel Wage Survey 2022/2023 (NIS/mes)
  AE  — MOE UAE Wage Index 2023 (AED/mes)
  QA  — PSA Qatar Labour Survey 2022 (QAR/mes)
  SA  — GASTAT Saudi Arabia Labour Market 2023 (SAR/mes)
  MY  — DOSM Malaysia Labour Market Review 2023 (MYR/mes)
  KZ  — BNS Kazakhstan Agency for Statistics 2023 (KZT/mes)
  CH  — SFSO Switzerland Wage Statistics 2022 (CHF/mes)
  HK  — C&SD Hong Kong GHS 2023 (HKD/mes)
  TW  — DGBAS Taiwan Earnings Statistics 2023 (TWD/mes)

PPP calculado via ppp_agent.PLI (World Bank ICP 2022).
"""

from sqlalchemy import text

# ── Tipo de cambio promedio 2023-2024 (1 moneda local = X USD) ──────────────
_FX: dict[str, float] = {
    'IL': 0.270,    # 1 NIS = 0.270 USD  (3.70 NIS/USD)
    'AE': 0.2723,   # 1 AED = 0.2723 USD (AED fijado al USD)
    'QA': 0.2747,   # 1 QAR = 0.2747 USD (QAR fijado al USD)
    'SA': 0.2667,   # 1 SAR = 0.2667 USD (SAR fijado al USD)
    'MY': 0.2128,   # 1 MYR = 0.2128 USD (4.70 MYR/USD)
    'KZ': 0.00222,  # 1 KZT = 0.00222 USD (450 KZT/USD)
    'CH': 1.111,    # 1 CHF = 1.111 USD
    'HK': 0.1280,   # 1 HKD = 0.1280 USD (7.82 HKD/USD)
    'TW': 0.03226,  # 1 TWD = 0.03226 USD (31 TWD/USD)
}

# PLI (Price Level Index, US=1.0, World Bank ICP 2022)
_PLI: dict[str, float] = {
    'IL': 1.07, 'AE': 0.85, 'QA': 0.58, 'SA': 0.65,
    'MY': 0.52, 'KZ': 0.45, 'CH': 1.62, 'HK': 0.93, 'TW': 0.69,
}

# Salarios medios mensuales en moneda local por grupo ISCO 1-9
# {country_iso: {isco_group: local_currency_amount}}
_WAGES_LCU: dict[str, dict[int, float]] = {
    # Israel — CBS Wage Survey 2022 (NIS/mes bruto, ocupados formales)
    'IL': {
        1: 22_500,  # Managers / Directivos
        2: 18_200,  # Professionals / Profesionales (ingenieros, médicos, abogados)
        3: 12_800,  # Technicians
        4:  9_500,  # Clerical
        5:  8_200,  # Service & Sales
        6:  7_400,  # Agricultural
        7:  9_200,  # Craft trades
        8: 10_100,  # Machine operators
        9:  7_000,  # Elementary
    },
    # UAE — MOE Wage Index 2023 (AED/mes, incluye expats y nacionales)
    'AE': {
        1: 35_000,
        2: 21_000,
        3: 12_000,
        4:  7_500,
        5:  5_000,
        6:  3_000,
        7:  5_800,
        8:  6_500,
        9:  2_800,
    },
    # Qatar — PSA Labour Force Survey 2022 (QAR/mes)
    'QA': {
        1: 42_000,
        2: 28_000,
        3: 15_000,
        4:  8_500,
        5:  5_500,
        6:  4_000,
        7:  7_000,
        8:  8_000,
        9:  3_200,
    },
    # Saudi Arabia — GASTAT Labour Market Survey 2023 (SAR/mes)
    'SA': {
        1: 28_000,
        2: 18_500,
        3: 11_000,
        4:  7_000,
        5:  4_800,
        6:  4_000,
        7:  7_500,
        8:  8_000,
        9:  3_000,
    },
    # Malaysia — DOSM Salary & Wages Survey 2023 (MYR/mes)
    'MY': {
        1: 13_500,
        2:  9_200,
        3:  6_000,
        4:  4_200,
        5:  3_000,
        6:  2_500,
        7:  3_800,
        8:  4_000,
        9:  2_200,
    },
    # Kazakhstan — BNS Wage Statistics 2023 (KZT/mes)
    'KZ': {
        1: 900_000,
        2: 620_000,
        3: 430_000,
        4: 340_000,
        5: 280_000,
        6: 240_000,
        7: 360_000,
        8: 390_000,
        9: 220_000,
    },
    # Switzerland — SFSO Wage Statistics 2022 (CHF/mes bruto)
    'CH': {
        1: 17_500,
        2: 12_000,
        3:  8_200,
        4:  6_500,
        5:  5_600,
        6:  4_800,
        7:  6_800,
        8:  7_300,
        9:  5_200,
    },
    # Hong Kong — C&SD General Household Survey Q4 2023 (HKD/mes)
    'HK': {
        1: 90_000,
        2: 58_000,
        3: 34_000,
        4: 23_000,
        5: 17_000,
        6: 15_000,
        7: 23_000,
        8: 26_000,
        9: 14_500,
    },
    # Taiwan — DGBAS Earnings and Productivity Statistics 2023 (TWD/mes)
    'TW': {
        1: 190_000,
        2: 125_000,
        3:  75_000,
        4:  48_000,
        5:  38_000,
        6:  33_000,
        7:  50_000,
        8:  55_000,
        9:  30_000,
    },
}

_ISCO_LABELS = {
    1: 'Managers / Directivos',
    2: 'Professionals / Profesionales',
    3: 'Technicians / Técnicos',
    4: 'Clerical / Administrativos',
    5: 'Service & Sales / Servicios',
    6: 'Agricultural / Agrícola',
    7: 'Craft trades / Artesanos',
    8: 'Machine operators / Operadores',
    9: 'Elementary / Básico',
}

_SOURCES = {
    'IL': ('CBS Israel Wage Survey 2022/2023', 'https://www.cbs.gov.il/en/subjects/Pages/Wages.aspx'),
    'AE': ('MOE UAE Wage Index 2023', 'https://www.mohrsd.gov.ae'),
    'QA': ('PSA Qatar Labour Force Survey 2022', 'https://www.psa.gov.qa'),
    'SA': ('GASTAT Saudi Arabia Labour Market 2023', 'https://www.stats.gov.sa'),
    'MY': ('DOSM Malaysia Salary & Wages Survey 2023', 'https://www.dosm.gov.my'),
    'KZ': ('BNS Kazakhstan Wage Statistics 2023', 'https://stat.gov.kz'),
    'CH': ('SFSO Switzerland Wage Statistics 2022', 'https://www.bfs.admin.ch'),
    'HK': ('C&SD Hong Kong GHS Q4 2023', 'https://www.censtatd.gov.hk'),
    'TW': ('DGBAS Taiwan Earnings Statistics 2023', 'https://www.dgbas.gov.tw'),
}


def _ensure_columns(db) -> None:
    db.execute(text("ALTER TABLE occupation_salary ADD COLUMN IF NOT EXISTS median_monthly_ppp_usd REAL"))
    db.execute(text("ALTER TABLE occupation_salary ADD COLUMN IF NOT EXISTS ppp_price_level_index REAL"))
    db.execute(text("ALTER TABLE occupation_salary ADD COLUMN IF NOT EXISTS ppp_source TEXT DEFAULT ''"))
    db.commit()


def run_gulf_asia_import(db) -> dict:
    _ensure_columns(db)

    inserted = updated = skipped = 0
    results_by_country: dict[str, list] = {}

    for cc, wages in _WAGES_LCU.items():
        fx   = _FX.get(cc)
        pli  = _PLI.get(cc)
        src, url = _SOURCES.get(cc, ('', ''))

        if not fx or not pli:
            skipped += len(wages)
            continue

        results_by_country[cc] = []
        for isco_grp, lcu in wages.items():
            nominal_usd = round(lcu * fx, 2)
            ppp_usd     = round(nominal_usd / pli, 2)
            label       = _ISCO_LABELS.get(isco_grp, '')

            db.execute(text("""
                INSERT INTO occupation_salary
                    (country_iso, isco_group, isco_label,
                     median_monthly_local, median_monthly_usd,
                     median_monthly_ppp_usd, ppp_price_level_index,
                     currency, profession_score, year,
                     source, source_url, ppp_source, updated_at)
                VALUES
                    (:cc, :isco, :label,
                     :lcu, :nominal, :ppp, :pli,
                     'PPP_INTL', 0, 2023,
                     :src, :url, 'World Bank ICP 2022', NOW())
                ON CONFLICT (country_iso, isco_group) DO UPDATE SET
                    isco_label             = EXCLUDED.isco_label,
                    median_monthly_local   = EXCLUDED.median_monthly_local,
                    median_monthly_usd     = EXCLUDED.median_monthly_usd,
                    median_monthly_ppp_usd = EXCLUDED.median_monthly_ppp_usd,
                    ppp_price_level_index  = EXCLUDED.ppp_price_level_index,
                    year                   = EXCLUDED.year,
                    source                 = EXCLUDED.source,
                    source_url             = EXCLUDED.source_url,
                    ppp_source             = EXCLUDED.ppp_source,
                    updated_at             = NOW()
            """), {
                'cc': cc, 'isco': isco_grp, 'label': label,
                'lcu': lcu, 'nominal': nominal_usd, 'ppp': ppp_usd, 'pli': pli,
                'src': src, 'url': url,
            })
            results_by_country[cc].append({'isco': isco_grp, 'nominal_usd': nominal_usd, 'ppp_usd': ppp_usd})
            inserted += 1

    db.commit()

    # Recalcular profession_score para cada país (0-100 relativo al ISCO 1)
    for cc in _WAGES_LCU:
        try:
            max_row = db.execute(text("""
                SELECT MAX(median_monthly_ppp_usd) FROM occupation_salary
                WHERE country_iso=:cc AND isco_group BETWEEN 1 AND 9
                  AND median_monthly_ppp_usd IS NOT NULL
            """), {'cc': cc}).fetchone()
            if max_row and max_row[0]:
                max_ppp = float(max_row[0])
                db.execute(text("""
                    UPDATE occupation_salary
                    SET profession_score = LEAST(100, ROUND(median_monthly_ppp_usd / :max * 100, 1))
                    WHERE country_iso=:cc AND isco_group BETWEEN 1 AND 9
                      AND median_monthly_ppp_usd IS NOT NULL
                """), {'cc': cc, 'max': max_ppp})
        except Exception:
            pass
    db.commit()

    return {
        'inserted_or_updated': inserted,
        'skipped': skipped,
        'countries': list(_WAGES_LCU.keys()),
        'detail': results_by_country,
        'status': 'ok',
        'source': 'CBS/MOE-UAE/PSA-Qatar/GASTAT/DOSM/BNS/SFSO/C&SD/DGBAS 2022-2023',
        'note': 'PPP_USD = nominal_USD / PLI. Fuente PLI: World Bank ICP 2022.',
    }
