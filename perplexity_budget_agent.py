from __future__ import annotations
"""
perplexity_budget_agent.py — Benchmarks Perplexity 2026-07-31
==============================================================
Guarda en BD los datos del Executive Summary:
  • Table 1: CEO PPP por país × tamaño empresa (ISCO 0/nivel directivo)
  • Table 2: % presupuesto sugerido, 4 archetypes automotriz/lujo
  • Table 3: % presupuesto sugerido, 5 marcas nuevas
  • Table 4: Participación de mercado Visa por país

Fuente: "Advertising Budget Allocation Model by Country"
Prepared by Perplexity Computer for Juan Carlos — Preferendum, July 31, 2026
"""

from sqlalchemy import text

# ── Table 1: CEO PPP USD/mes por tamaño empresa ──────────────────────────────
# Fuente: Eurostat SES + agencias nacionales + estudios compensación ejecutiva
# País → {small, medium, large} en USD PPP internacionales / mes
CEO_PPP_TABLE1 = {
    'US': {'small': 17_202, 'medium': 250_500, 'large': 1_541_667},
    'GB': {'small': 12_540, 'medium':  56_467, 'large':   740_289},
    'FR': {'small': 10_397, 'medium':  18_960, 'large':   366_974},
    'BR': {'small':  8_759, 'medium':  21_138, 'large':   106_700},
    'RU': {'small':  7_881, 'medium':  39_610, 'large':    87_835},
    'CO': {'small': 22_516, 'medium':  49_684, 'large':    81_377},
    'BD': {'small': 11_729, 'medium':  21_754, 'large':    58_048},
    'MX': {'small': 27_228, 'medium':  36_304, 'large':    47_900},
    'CN': {'small':  1_508, 'medium':   3_392, 'large':    31_663},
    'NO': {'small':  7_293, 'medium':  11_394, 'large':    22_787},
}

# ── Table 2: % presupuesto, 4 archetypes automotriz/lujo ─────────────────────
# Metodología: curva salarial ISCO-08 PPP + HNWI/UHNWI para Porsche/Rolex
BUDGET_TABLE2 = {
    'porsche_rolex': {
        'methodology': 'HNWI_wealth_gt_1M_USD',
        'isco_levels':  'HNWI > USD 1M net worth',
        'data': {
            'US': 66.9, 'CN': 15.0, 'GB': 6.9, 'FR': 6.8,
            'RU':  1.3, 'BR':  1.1, 'NO': 1.0, 'MX': 0.9,
            'CO':  0.1, 'BD':  0.1,
        },
    },
    'bmw_mercedes': {
        'methodology': 'wage_curve_PPP',
        'isco_levels':  'ISCO levels 1-5 (upper-middle and middle)',
        'data': {
            'US': 46.3, 'CN': 29.1, 'GB': 4.4, 'FR': 3.8,
            'RU':  7.9, 'BR':  4.6, 'NO': 0.7, 'MX': 1.7,
            'CO':  1.0, 'BD':  0.5,
        },
    },
    'peugeot_vw_toyota': {
        'methodology': 'wage_curve_PPP',
        'isco_levels':  'ISCO levels 4,5,7,8 + combined 6/9 (middle and below)',
        'data': {
            'US': 35.4, 'CN': 31.2, 'GB': 3.3, 'FR': 3.5,
            'RU': 10.4, 'BR':  7.1, 'NO': 0.6, 'MX': 4.0,
            'CO':  1.8, 'BD':  2.7,
        },
    },
    'byd_chery': {
        'methodology': 'wage_curve_PPP',
        'isco_levels':  'ISCO levels 1-5,7,8 (all except bottom)',
        'data': {
            'US': 44.5, 'CN': 28.8, 'GB': 4.2, 'FR': 3.7,
            'RU':  9.3, 'BR':  5.0, 'NO': 0.7, 'MX': 2.1,
            'CO':  1.0, 'BD':  0.8,
        },
    },
}

# ── Table 3: % presupuesto, 5 marcas nuevas ──────────────────────────────────
BUDGET_TABLE3 = {
    'coca_cola': {
        'methodology': 'consumption_volume_liters_per_year',
        'isco_levels':  'Universal — all income levels',
        'data': {
            'US': 43.0, 'MX': 21.3, 'CN': 11.8, 'BR': 9.5,
            'GB':  5.4, 'FR':  4.9, 'CO':  3.0, 'RU': 1.0,
            'NO':  0.1, 'BD':  0.1,
        },
    },
    'mcdonalds': {
        'methodology': 'country_conditional_segment_World_Bank_income_class',
        'isco_levels':  'Rich: value segment (ISCO 4-9) | Emerging: aspirational (ISCO 1-5)',
        'data': {
            'CN': 50.1, 'US': 30.1, 'BR': 8.0, 'FR': 3.0,
            'GB':  2.8, 'MX':  2.9, 'CO': 1.7, 'BD': 0.9,
            'NO':  0.5, 'RU':  0.0,
        },
    },
    'visa': {
        'methodology': 'HFCE_spending_x_visa_network_share',
        'isco_levels':  'Household consumption × Visa market share',
        'data': {
            'US': 77.8, 'GB': 8.6, 'MX': 4.7, 'BR': 3.2,
            'FR':  2.4, 'BD': 1.5, 'NO': 0.4, 'CO': 0.5,
            'CN':  0.9, 'RU': 0.0,
        },
    },
    'adidas': {
        'methodology': 'wage_curve_PPP',
        'isco_levels':  'ISCO levels 1-5,7,8 (pure middle — no extremes)',
        'data': {
            'US': 49.0, 'CN': 31.7, 'BR': 5.5, 'GB': 4.6,
            'FR':  4.1, 'MX':  2.3, 'CO': 1.1, 'BD': 0.8,
            'NO':  0.8, 'RU':  0.0,
        },
    },
    'hyundai': {
        'methodology': 'wage_curve_PPP',
        'isco_levels':  'ISCO levels 4,5,7,8 + 6/9 (same as Peugeot/VW)',
        'data': {
            'US': 39.5, 'CN': 34.8, 'BR': 8.0, 'MX': 4.4,
            'FR':  4.0, 'GB':  3.7, 'BD': 3.0, 'CO': 2.0,
            'NO':  0.7, 'RU':  0.0,
        },
    },
}

# ── Table 4: Visa network share por país ─────────────────────────────────────
VISA_NETWORK_SHARE = {
    'US': {'share_pct': 65.8, 'type': 'direct',    'source': 'Nilson Report via Rapyd'},
    'MX': {'share_pct': 62.0, 'type': 'direct',    'source': 'Banxico via El CEO'},
    'BR': {'share_pct': 37.2, 'type': 'direct',    'source': 'Banco Central do Brasil via Nexo'},
    'BD': {'share_pct': 75.5, 'type': 'direct',    'source': 'Bangladesh Bank'},
    'GB': {'share_pct': 60.0, 'type': 'estimated', 'source': '60% of combined 98% Visa+Mastercard'},
    'FR': {'share_pct': 22.0, 'type': 'estimated', 'source': '22% of 36.4% international schemes'},
    'NO': {'share_pct': 33.0, 'type': 'estimated', 'source': '33% of 54% international cards'},
    'CO': {'share_pct': 23.0, 'type': 'estimated', 'source': 'Direct Visa + Credibanco acquirer'},
    'CN': {'share_pct':  2.0, 'type': 'structural', 'source': 'UnionPay ~90-95% domestic; residual cross-border'},
    'RU': {'share_pct':  0.0, 'type': 'structural', 'source': 'Visa processing withdrawn 2026 (CBR)'},
}

_SOURCE = 'Perplexity_2026-07-31_Advertising_Budget_Allocation_Model'


def _create_tables(db) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS perplexity_budget_benchmarks (
            id          SERIAL PRIMARY KEY,
            brand       TEXT NOT NULL,
            country_iso TEXT NOT NULL,
            budget_pct  REAL NOT NULL,
            methodology TEXT,
            isco_levels TEXT,
            source      TEXT,
            updated_at  TIMESTAMP DEFAULT NOW(),
            UNIQUE (brand, country_iso)
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS perplexity_ceo_ppp (
            id          SERIAL PRIMARY KEY,
            country_iso TEXT NOT NULL,
            company_size TEXT NOT NULL,
            monthly_ppp_usd REAL NOT NULL,
            source      TEXT,
            updated_at  TIMESTAMP DEFAULT NOW(),
            UNIQUE (country_iso, company_size)
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS perplexity_visa_share (
            id          SERIAL PRIMARY KEY,
            country_iso TEXT NOT NULL UNIQUE,
            share_pct   REAL NOT NULL,
            share_type  TEXT,
            share_source TEXT,
            updated_at  TIMESTAMP DEFAULT NOW()
        )
    """))
    db.commit()


def run_perplexity_import(db) -> dict:
    _create_tables(db)

    inserted = 0

    # ── Table 1: CEO PPP ─────────────────────────────────────────────────────
    for cc, sizes in CEO_PPP_TABLE1.items():
        for size, ppp in sizes.items():
            db.execute(text("""
                INSERT INTO perplexity_ceo_ppp
                    (country_iso, company_size, monthly_ppp_usd, source, updated_at)
                VALUES (:cc, :sz, :ppp, :src, NOW())
                ON CONFLICT (country_iso, company_size) DO UPDATE SET
                    monthly_ppp_usd = EXCLUDED.monthly_ppp_usd,
                    source          = EXCLUDED.source,
                    updated_at      = NOW()
            """), {'cc': cc, 'sz': size, 'ppp': ppp, 'src': _SOURCE})
            inserted += 1

    # ── Table 2 + Table 3: Budget benchmarks ─────────────────────────────────
    all_brands = {**BUDGET_TABLE2, **BUDGET_TABLE3}
    for brand, meta in all_brands.items():
        for cc, pct in meta['data'].items():
            db.execute(text("""
                INSERT INTO perplexity_budget_benchmarks
                    (brand, country_iso, budget_pct, methodology, isco_levels, source, updated_at)
                VALUES (:brand, :cc, :pct, :method, :isco, :src, NOW())
                ON CONFLICT (brand, country_iso) DO UPDATE SET
                    budget_pct  = EXCLUDED.budget_pct,
                    methodology = EXCLUDED.methodology,
                    isco_levels = EXCLUDED.isco_levels,
                    source      = EXCLUDED.source,
                    updated_at  = NOW()
            """), {
                'brand':  brand,
                'cc':     cc,
                'pct':    pct,
                'method': meta['methodology'],
                'isco':   meta['isco_levels'],
                'src':    _SOURCE,
            })
            inserted += 1

    # ── Table 4: Visa network share ───────────────────────────────────────────
    for cc, v in VISA_NETWORK_SHARE.items():
        db.execute(text("""
            INSERT INTO perplexity_visa_share
                (country_iso, share_pct, share_type, share_source, updated_at)
            VALUES (:cc, :pct, :typ, :src, NOW())
            ON CONFLICT (country_iso) DO UPDATE SET
                share_pct    = EXCLUDED.share_pct,
                share_type   = EXCLUDED.share_type,
                share_source = EXCLUDED.share_source,
                updated_at   = NOW()
        """), {'cc': cc, 'pct': v['share_pct'], 'typ': v['type'], 'src': v['source']})
        inserted += 1

    db.commit()

    return {
        'inserted_or_updated': inserted,
        'tables': ['perplexity_budget_benchmarks', 'perplexity_ceo_ppp', 'perplexity_visa_share'],
        'brands': list(all_brands.keys()),
        'ceo_ppp_countries': list(CEO_PPP_TABLE1.keys()),
        'visa_countries': list(VISA_NETWORK_SHARE.keys()),
        'source': _SOURCE,
        'status': 'ok',
        'note': (
            'Table 1: CEO PPP por tamaño empresa. '
            'Table 2: 4 archetypes automotriz/lujo (HNWI + curva salarial). '
            'Table 3: 5 marcas nuevas (consumo, red pago, segmento condicional). '
            'Table 4: Participación Visa por país.'
        ),
    }
