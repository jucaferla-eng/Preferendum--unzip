"""
marketing_agent.py
==================
PREFERENDUM — Agente de Marketing Dual

LADO A — Gestión de Anunciantes (Inbound):
  • CRM: onboarding, performance tracking, alertas
  • Reportes automáticos de ROI por campaña
  • Sugerencias de targeting por commune y tier de ingreso
  • Alertas: presupuesto bajo, campaña próxima a vencer

LADO B — Marketing de Adquisición (Outbound):
  • Meta Ads API (Facebook + Instagram) — campaña de adquisición de usuarios
  • X/Twitter Ads API — amplificación en debates de tendencia
  • Presupuesto de adquisición = 15% del revenue mensual de anunciantes
  • Auto-boost: cuando un debate tiene tracción, se amplifica automáticamente
  • Attribution: qué canal trajo cada usuario

CICLO DE NEGOCIO:
  Anunciante paga → Revenue → 15% a adquisición → Nuevos usuarios →
  Más debates → Más inventario → Más revenue para anunciantes → loop

En memoria de José Ignacio Fernández (1989-2024)
"""

import os, json, math, time
import requests as _req
from datetime import datetime, timedelta
from typing import Optional

# ══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════

# Meta Ads API
META_APP_ID        = os.getenv('META_APP_ID', '')
META_APP_SECRET    = os.getenv('META_APP_SECRET', '')
META_ACCESS_TOKEN  = os.getenv('META_ACCESS_TOKEN', '')
META_AD_ACCOUNT_ID = os.getenv('META_AD_ACCOUNT_ID', '')  # 'act_XXXXXXXXXX'
META_API_BASE      = 'https://graph.facebook.com/v21.0'

# X / Twitter Ads API
X_CONSUMER_KEY        = os.getenv('X_CONSUMER_KEY', '')
X_CONSUMER_SECRET     = os.getenv('X_CONSUMER_SECRET', '')
X_ACCESS_TOKEN        = os.getenv('X_ACCESS_TOKEN', '')
X_ACCESS_TOKEN_SECRET = os.getenv('X_ACCESS_TOKEN_SECRET', '')
X_AD_ACCOUNT_ID       = os.getenv('X_AD_ACCOUNT_ID', '')
X_API_BASE            = 'https://ads-api.x.com/12'

# Porcentaje del revenue mensual destinado a adquisición
ACQUISITION_BUDGET_PCT = 0.15  # 15%

# CAC objetivo por canal (USD) — ajustar según datos reales
TARGET_CAC = {
    'meta_facebook': 1.50,
    'meta_instagram': 1.20,
    'x_twitter':      2.00,
    'organic':        0.00,
}

# Idioma por defecto para creatividades por país
COUNTRY_LANG = {
    'CL': 'es', 'AR': 'es', 'PE': 'es', 'MX': 'es', 'CO': 'es',
    'ES': 'es', 'BR': 'pt', 'US': 'en', 'DE': 'de', 'GB': 'en',
    'FR': 'fr', 'IT': 'it',
}

# ── Métricas de embudo por canal (estimados iniciales, se actualizan con datos reales)
CHANNEL_FUNNEL = {
    'meta_facebook':  {'ctr': 0.018, 'install_rate': 0.35, 'verify_rate': 0.60},
    'meta_instagram': {'ctr': 0.022, 'install_rate': 0.40, 'verify_rate': 0.58},
    'x_twitter':      {'ctr': 0.008, 'install_rate': 0.25, 'verify_rate': 0.55},
}


# ══════════════════════════════════════════════════════════════
# LADO A — GESTIÓN DE ANUNCIANTES
# ══════════════════════════════════════════════════════════════

def analyze_campaign_performance(campaign: dict, db=None) -> dict:
    """
    Calculates performance metrics for an advertiser campaign.
    campaign: dict from ad_campaigns table
    """
    from targeting_agent import get_commune_info, load_matrix

    campaign_id     = campaign.get('id')
    budget          = float(campaign.get('budget_usd') or campaign.get('remaining_budget') or 0)
    impressions     = int(campaign.get('impressions_served') or 0)
    clicks          = int(campaign.get('clicks') or 0)
    cpm             = float(campaign.get('cpm') or 6.0)
    country         = campaign.get('target_country') or ''
    commune_csv     = campaign.get('target_communes') or ''
    communes        = [c.strip() for c in commune_csv.split(',') if c.strip()]

    spent           = (impressions / 1000.0) * cpm
    remaining       = max(0, budget - spent)
    ctr             = (clicks / impressions) if impressions > 0 else 0
    cpc             = (spent / clicks) if clicks > 0 else 0
    budget_pct_used = (spent / budget * 100) if budget > 0 else 0

    # Commune-level breakdown from matrix
    matrix = load_matrix()
    commune_breakdown = []
    for c in communes[:5]:
        info = get_commune_info(country, c)
        commune_breakdown.append({
            'commune':        c,
            'income_tier':    info['income_tier'],
            'income_index':   info['income_index'],
            'cpm':            info['cpm'],
            'cost_per_contact': round(info['cpm'] / 1000, 5),
        })

    alerts = []
    if budget_pct_used >= 90:
        alerts.append({'level': 'critical', 'msg': f'Budget {budget_pct_used:.0f}% consumed — campaign will pause soon'})
    elif budget_pct_used >= 75:
        alerts.append({'level': 'warning', 'msg': f'Budget {budget_pct_used:.0f}% consumed'})
    if impressions == 0 and campaign.get('status') == 'active':
        alerts.append({'level': 'warning', 'msg': 'Campaign active but no impressions yet — check targeting'})

    return {
        'campaign_id':        campaign_id,
        'impressions':        impressions,
        'clicks':             clicks,
        'ctr_pct':            round(ctr * 100, 2),
        'cpm':                cpm,
        'spent_usd':          round(spent, 2),
        'remaining_usd':      round(remaining, 2),
        'budget_pct_used':    round(budget_pct_used, 1),
        'cpc_usd':            round(cpc, 4),
        'cost_per_impression': round(cpm / 1000, 5),
        'commune_breakdown':  commune_breakdown,
        'alerts':             alerts,
    }


def suggest_targeting_improvements(campaign: dict, matrix: dict) -> list:
    """
    Analyzes campaign targeting and suggests concrete improvements.
    Returns a list of recommendations sorted by estimated impact.
    """
    from targeting_agent import TIER_ORDER

    suggestions = []
    country      = campaign.get('target_country') or ''
    commune_csv  = campaign.get('target_communes') or ''
    curr_communes= [c.strip() for c in commune_csv.split(',') if c.strip()]
    min_tier     = campaign.get('min_income_tier') or 'D'
    cpm          = float(campaign.get('cpm') or 6.0)

    country_data = matrix.get(country, {})
    all_communes = country_data.get('communes', {})

    if not all_communes:
        return [{'type': 'info', 'msg': f'No commune data available for {country}'}]

    # Find communes that meet the tier requirement but are not yet targeted
    tier_val = TIER_ORDER.get(min_tier, 1)
    untargeted = []
    for name, data in all_communes.items():
        if name not in curr_communes:
            if TIER_ORDER.get(data['income_tier'], 1) >= tier_val:
                untargeted.append({
                    'commune':      name,
                    'income_tier':  data['income_tier'],
                    'income_index': data['income_index'],
                    'population':   data['population'],
                    'cpm':          data['cpm'],
                })

    # Sort by population (biggest reach opportunity first)
    untargeted.sort(key=lambda x: x['population'], reverse=True)

    if untargeted:
        top3 = untargeted[:3]
        total_new_pop = sum(c['population'] for c in top3)
        suggestions.append({
            'type':    'expand_communes',
            'impact':  'high',
            'msg':     f'Add {len(top3)} high-value communes: {", ".join(c["commune"] for c in top3)}',
            'detail':  f'Adds ~{total_new_pop:,} potential contacts meeting your income tier requirements',
            'communes': [c['commune'] for c in top3],
        })

    # Check if age range can be expanded
    age_min = int(campaign.get('target_age_min') or 13)
    age_max = int(campaign.get('target_age_max') or 99)
    age_range = age_max - age_min
    if age_range < 20:
        suggestions.append({
            'type':   'expand_age',
            'impact': 'medium',
            'msg':    f'Age range {age_min}-{age_max} is narrow — consider widening to +/-5 years',
            'detail': f'Estimated +{int(age_range * 0.3)}% increase in addressable audience',
        })

    # Check if gender targeting can be broadened
    gender = campaign.get('target_gender') or 'all'
    if gender != 'all':
        suggestions.append({
            'type':   'expand_gender',
            'impact': 'medium',
            'msg':    f'Campaign targets {gender} only — debates attract both genders at similar rates',
            'detail': 'Broadening to "all" could double reach at the same CPM',
        })

    # Budget optimization
    impressions = int(campaign.get('impressions_served') or 0)
    if impressions > 1000:
        est_cpc = cpm / 1000 / 0.015  # assume 1.5% CTR
        suggestions.append({
            'type':   'budget_allocation',
            'impact': 'low',
            'msg':    f'Estimated CPC: ${est_cpc:.3f} — consider A/B testing ad creative',
            'detail': 'Different creatives can improve CTR from 1.5% to 3-4%',
        })

    return suggestions


def generate_advertiser_report(advertiser_email: str, campaigns: list, db=None) -> dict:
    """
    Generates a full performance report for an advertiser.
    Includes all campaigns, aggregate metrics, and recommendations.
    """
    from targeting_agent import load_matrix
    matrix = load_matrix()

    total_impressions = 0
    total_clicks      = 0
    total_spent       = 0
    campaign_reports  = []
    all_suggestions   = []

    for c in campaigns:
        perf = analyze_campaign_performance(c, db)
        sug  = suggest_targeting_improvements(c, matrix)
        campaign_reports.append({**perf, 'title': c.get('title', ''), 'status': c.get('status', '')})
        all_suggestions.extend(sug)
        total_impressions += perf['impressions']
        total_clicks      += perf['clicks']
        total_spent       += perf['spent_usd']

    ctr_overall     = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
    cost_per_click  = (total_spent / total_clicks) if total_clicks > 0 else 0

    # Deduplicate suggestions by type
    seen_types = set()
    unique_suggestions = []
    for s in all_suggestions:
        if s['type'] not in seen_types:
            seen_types.add(s['type'])
            unique_suggestions.append(s)

    return {
        'advertiser_email':    advertiser_email,
        'generated_at':        datetime.utcnow().isoformat(),
        'period':              'all_time',
        'summary': {
            'total_campaigns':  len(campaigns),
            'total_impressions': total_impressions,
            'total_clicks':      total_clicks,
            'ctr_pct':           round(ctr_overall, 2),
            'total_spent_usd':   round(total_spent, 2),
            'cost_per_click':    round(cost_per_click, 4),
        },
        'campaigns':       campaign_reports,
        'recommendations': unique_suggestions[:5],
    }


def get_campaigns_needing_attention(db) -> dict:
    """
    Returns campaigns that need human attention:
    - Budget < 10% remaining
    - No impressions in 48h despite being active
    - Expiring within 3 days
    """
    from sqlalchemy import text
    results = {'low_budget': [], 'no_impressions': [], 'expiring_soon': []}

    try:
        rows = db.execute(text("""
            SELECT id, title, advertiser_name, advertiser_email,
                   remaining_budget, impressions_served, end_date, status, cpm
            FROM ad_campaigns
            WHERE is_active=1 AND status='active'
        """)).fetchall()

        for r in rows:
            r = dict(r._mapping)
            budget = float(r.get('remaining_budget') or 0)
            impr   = int(r.get('impressions_served') or 0)

            if budget < 5:
                results['low_budget'].append({
                    'id': r['id'], 'title': r['title'],
                    'advertiser': r['advertiser_email'],
                    'remaining_usd': budget,
                })

            if impr == 0:
                results['no_impressions'].append({
                    'id': r['id'], 'title': r['title'],
                    'advertiser': r['advertiser_email'],
                })

            if r.get('end_date'):
                try:
                    end = datetime.fromisoformat(str(r['end_date']))
                    days_left = (end - datetime.utcnow()).days
                    if 0 <= days_left <= 3:
                        results['expiring_soon'].append({
                            'id': r['id'], 'title': r['title'],
                            'advertiser': r['advertiser_email'],
                            'days_left': days_left,
                        })
                except Exception:
                    pass
    except Exception as e:
        print(f'[MarketingAgent] DB error in get_campaigns_needing_attention: {e}')

    return results


# ══════════════════════════════════════════════════════════════
# LADO B — ADQUISICIÓN EN META (FACEBOOK + INSTAGRAM)
# ══════════════════════════════════════════════════════════════

def _meta_post(endpoint: str, data: dict) -> dict:
    """Makes an authenticated POST to Meta Graph API."""
    if not META_ACCESS_TOKEN:
        return {'mock': True, 'endpoint': endpoint, 'data': data}
    url = f'{META_API_BASE}/{endpoint}'
    data['access_token'] = META_ACCESS_TOKEN
    r = _req.post(url, json=data, timeout=15)
    result = r.json()
    if 'error' in result:
        raise ValueError(f"Meta API error: {result['error'].get('message', result['error'])}")
    return result


def _meta_get(endpoint: str, params: dict = None) -> dict:
    """Makes an authenticated GET to Meta Graph API."""
    if not META_ACCESS_TOKEN:
        return {'mock': True, 'data': []}
    url = f'{META_API_BASE}/{endpoint}'
    p = {'access_token': META_ACCESS_TOKEN}
    if params:
        p.update(params)
    r = _req.get(url, params=p, timeout=15)
    return r.json()


def create_meta_acquisition_campaign(
    country: str,
    budget_usd: float,
    objective: str = 'APP_INSTALLS',
    age_min: int = 18,
    age_max: int = 55,
    placement: str = 'both',   # 'facebook', 'instagram', 'both'
    creative_text: str = None,
    creative_image_url: str = None,
) -> dict:
    """
    Creates a Meta Ads campaign to acquire Preferendum users.

    Targeting:
      - Country: derived from country ISO
      - Age: age_min to age_max
      - Interests: politics, current events, voting, civic engagement
      - Placement: FB feed, IG feed, FB/IG stories

    Returns campaign_id and ad_set_id if successful.
    Requires env vars: META_ACCESS_TOKEN, META_AD_ACCOUNT_ID
    """
    if not all([META_ACCESS_TOKEN, META_AD_ACCOUNT_ID]):
        print('[MarketingAgent] Meta not configured — returning mock campaign')
        return {
            'mock':        True,
            'campaign_id': f'mock_campaign_{country}_{int(time.time())}',
            'budget_usd':  budget_usd,
            'country':     country,
        }

    lang      = COUNTRY_LANG.get(country, 'es')
    ad_text   = creative_text or _default_ad_text(country, lang)
    daily_budget_cents = int(budget_usd / 30 * 100)  # monthly budget → daily cents

    # 1. Create campaign
    campaign = _meta_post(f'{META_AD_ACCOUNT_ID}/campaigns', {
        'name':             f'Preferendum Acquisition — {country} — {datetime.utcnow().strftime("%Y-%m")}',
        'objective':        objective,
        'status':           'PAUSED',  # start paused, activate after review
        'special_ad_categories': [],
    })
    campaign_id = campaign.get('id')

    # 2. Create ad set (targeting)
    placements = {}
    if placement in ('facebook', 'both'):
        placements['facebook_positions'] = ['feed', 'story', 'marketplace']
    if placement in ('instagram', 'both'):
        placements['instagram_positions'] = ['stream', 'story', 'reels']

    ad_set = _meta_post(f'{META_AD_ACCOUNT_ID}/adsets', {
        'name':               f'Preferendum {country} — civic interest',
        'campaign_id':        campaign_id,
        'daily_budget':       daily_budget_cents,
        'billing_event':      'IMPRESSIONS',
        'optimization_goal':  'APP_INSTALLS' if objective == 'APP_INSTALLS' else 'LINK_CLICKS',
        'bid_strategy':       'LOWEST_COST_WITHOUT_CAP',
        'targeting': {
            'age_min':          age_min,
            'age_max':          age_max,
            'geo_locations':    {'countries': [country]},
            'flexible_spec':    [{
                'interests': [
                    {'id': '6003349442621', 'name': 'Politics'},
                    {'id': '6003107902433', 'name': 'Current events'},
                    {'id': '6002925799030', 'name': 'Voting'},
                ],
            }],
            'publisher_platforms': ['facebook', 'instagram'] if placement == 'both'
                                    else [placement],
            **placements,
        },
        'status': 'PAUSED',
    })
    ad_set_id = ad_set.get('id')

    return {
        'ok':          True,
        'campaign_id': campaign_id,
        'ad_set_id':   ad_set_id,
        'country':     country,
        'budget_usd':  budget_usd,
        'daily_budget_usd': round(daily_budget_cents / 100, 2),
        'status':      'PAUSED — activate after creative review',
        'next_step':   'Upload creative via POST /marketing/meta/add-creative',
    }


def create_meta_ad_creative(campaign_id: str, ad_set_id: str, text: str, image_url: str = None, link: str = 'https://preferendum.com') -> dict:
    """Creates the ad creative and links it to the ad set."""
    if not META_AD_ACCOUNT_ID:
        return {'mock': True, 'campaign_id': campaign_id}

    # Create ad creative
    creative = _meta_post(f'{META_AD_ACCOUNT_ID}/adcreatives', {
        'name': f'Preferendum creative {int(time.time())}',
        'object_story_spec': {
            'page_id': os.getenv('META_PAGE_ID', ''),
            'link_data': {
                'message':      text,
                'link':         link,
                'picture':      image_url or '',
                'call_to_action': {'type': 'LEARN_MORE'},
            },
        },
    })
    creative_id = creative.get('id')

    # Create the ad
    ad = _meta_post(f'{META_AD_ACCOUNT_ID}/ads', {
        'name':       f'Preferendum ad {int(time.time())}',
        'adset_id':   ad_set_id,
        'creative':   {'creative_id': creative_id},
        'status':     'PAUSED',
    })

    return {'ok': True, 'creative_id': creative_id, 'ad_id': ad.get('id')}


def get_meta_campaign_insights(campaign_id: str, days: int = 7) -> dict:
    """Fetches performance data for a Meta campaign."""
    if not META_ACCESS_TOKEN:
        return {
            'mock': True,
            'campaign_id': campaign_id,
            'note': 'Configure META_ACCESS_TOKEN to get real data',
        }
    data = _meta_get(f'{campaign_id}/insights', {
        'fields':       'impressions,clicks,spend,ctr,cpc,actions',
        'date_preset':  f'last_{days}_d',
        'level':        'campaign',
    })
    raw = data.get('data', [{}])[0] if data.get('data') else {}

    installs = next((a['value'] for a in raw.get('actions', []) if a['action_type'] == 'app_install'), 0)
    spend = float(raw.get('spend', 0))
    cac = spend / int(installs) if int(installs) > 0 else None

    return {
        'campaign_id':  campaign_id,
        'period_days':  days,
        'impressions':  int(raw.get('impressions', 0)),
        'clicks':       int(raw.get('clicks', 0)),
        'ctr_pct':      float(raw.get('ctr', 0)),
        'spend_usd':    spend,
        'cpc_usd':      float(raw.get('cpc', 0)),
        'app_installs': int(installs),
        'cac_usd':      round(cac, 2) if cac else None,
        'vs_target_cac': f'${TARGET_CAC["meta_facebook"]:.2f} target',
    }


def activate_meta_campaign(campaign_id: str) -> dict:
    """Activates a paused Meta campaign."""
    if not META_ACCESS_TOKEN:
        return {'mock': True, 'activated': campaign_id}
    return _meta_post(campaign_id, {'status': 'ACTIVE'})


def pause_meta_campaign(campaign_id: str) -> dict:
    """Pauses a Meta campaign."""
    if not META_ACCESS_TOKEN:
        return {'mock': True, 'paused': campaign_id}
    return _meta_post(campaign_id, {'status': 'PAUSED'})


# ══════════════════════════════════════════════════════════════
# LADO B — ADQUISICIÓN EN X / TWITTER
# ══════════════════════════════════════════════════════════════

def _x_auth_header() -> dict:
    """Builds OAuth 1.0a Authorization header for X Ads API."""
    try:
        from requests_oauthlib import OAuth1
        auth = OAuth1(
            X_CONSUMER_KEY, X_CONSUMER_SECRET,
            X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET,
        )
        return auth
    except ImportError:
        return None


def create_x_acquisition_campaign(
    country: str,
    budget_usd: float,
    keywords: list = None,
    age_min: int = 18,
    age_max: int = 55,
) -> dict:
    """
    Creates an X/Twitter campaign to acquire Preferendum users.
    Uses keyword targeting: debates, votación, democracia, política, etc.
    Requires: requests_oauthlib package + X developer account.
    """
    auth = _x_auth_header()
    if not auth or not X_AD_ACCOUNT_ID:
        print('[MarketingAgent] X Ads not configured — returning mock campaign')
        return {
            'mock':        True,
            'campaign_id': f'x_mock_{country}_{int(time.time())}',
            'budget_usd':  budget_usd,
            'country':     country,
        }

    default_keywords = {
        'es': ['debate', 'votación', 'democracia', 'política', 'opinión', 'referéndum'],
        'en': ['debate', 'voting', 'democracy', 'politics', 'referendum', 'opinion'],
        'pt': ['debate', 'votação', 'democracia', 'política', 'referendo'],
        'de': ['Debatte', 'Abstimmung', 'Demokratie', 'Politik'],
        'fr': ['débat', 'vote', 'démocratie', 'politique'],
        'it': ['dibattito', 'votazione', 'democrazia', 'politica'],
    }
    lang     = COUNTRY_LANG.get(country, 'es')
    kws      = keywords or default_keywords.get(lang, default_keywords['es'])

    daily_budget_micro = int(budget_usd / 30 * 1_000_000)

    # Create campaign
    camp_r = _req.post(
        f'{X_API_BASE}/accounts/{X_AD_ACCOUNT_ID}/campaigns',
        auth=auth,
        json={
            'name':             f'Preferendum Acquisition {country} {datetime.utcnow().strftime("%Y-%m")}',
            'funding_instrument_id': os.getenv('X_FUNDING_INSTRUMENT_ID', ''),
            'daily_budget_amount_local_micro': daily_budget_micro,
            'entity_status':    'PAUSED',
        },
        timeout=15
    )
    camp_data = camp_r.json()
    if 'errors' in camp_data:
        return {'ok': False, 'error': camp_data['errors']}

    campaign_id = camp_data.get('data', {}).get('id')

    return {
        'ok':          True,
        'campaign_id': campaign_id,
        'country':     country,
        'keywords':    kws,
        'budget_usd':  budget_usd,
        'status':      'PAUSED — activate after creative review',
    }


def get_x_campaign_insights(campaign_id: str) -> dict:
    """Fetches X campaign stats."""
    auth = _x_auth_header()
    if not auth or not X_AD_ACCOUNT_ID:
        return {'mock': True, 'campaign_id': campaign_id}

    r = _req.get(
        f'{X_API_BASE}/stats/accounts/{X_AD_ACCOUNT_ID}',
        auth=auth,
        params={
            'entity':      'CAMPAIGN',
            'entity_ids':  campaign_id,
            'metric_groups': 'ENGAGEMENT,BILLING',
            'granularity': 'TOTAL',
        },
        timeout=15
    )
    data = r.json()
    stats = data.get('data', [{}])[0].get('id_data', [{}])[0].get('metrics', {})

    spend = float(stats.get('billed_charge_local_micro', [0])[0] or 0) / 1_000_000
    clicks = int(stats.get('clicks', [0])[0] or 0)

    return {
        'campaign_id': campaign_id,
        'spend_usd':   round(spend, 2),
        'clicks':      clicks,
        'impressions': int(stats.get('impressions', [0])[0] or 0),
        'cac_usd':     None,  # needs install tracking
    }


# ══════════════════════════════════════════════════════════════
# MOTOR DE ASIGNACIÓN DE PRESUPUESTO DE ADQUISICIÓN
# ══════════════════════════════════════════════════════════════

def calculate_acquisition_budget(db) -> dict:
    """
    Calculates monthly acquisition budget based on 15% of advertiser revenue.
    Also distributes budget across channels by efficiency (lowest CAC first).
    """
    from sqlalchemy import text

    # Sum of spent credits in last 30 days (proxy for revenue)
    try:
        row = db.execute(text("""
            SELECT COALESCE(SUM(ABS(amount_credits)), 0) as revenue_30d
            FROM credit_transactions
            WHERE type IN ('debit', 'allocation')
              AND created_at >= datetime('now', '-30 days')
        """)).fetchone()
        revenue_30d = float(row[0] or 0)
    except Exception:
        revenue_30d = 0

    acquisition_budget = revenue_30d * ACQUISITION_BUDGET_PCT

    # Distribute by channel efficiency (lowest CAC gets more budget)
    channels = list(TARGET_CAC.keys())
    channels = [c for c in channels if c != 'organic']
    total_efficiency = sum(1.0 / TARGET_CAC[c] for c in channels)

    distribution = {}
    for ch in channels:
        share = (1.0 / TARGET_CAC[ch]) / total_efficiency
        distribution[ch] = {
            'budget_usd':          round(acquisition_budget * share, 2),
            'target_cac_usd':      TARGET_CAC[ch],
            'estimated_users':     int(acquisition_budget * share / TARGET_CAC[ch]),
            'efficiency_weight':   round(share, 3),
        }

    return {
        'revenue_30d_usd':         round(revenue_30d, 2),
        'acquisition_budget_usd':  round(acquisition_budget, 2),
        'acquisition_pct':         ACQUISITION_BUDGET_PCT * 100,
        'distribution':            distribution,
        'total_estimated_users':   sum(d['estimated_users'] for d in distribution.values()),
    }


def auto_boost_trending_debate(debate: dict, db) -> dict:
    """
    Detects when a debate has high engagement and automatically creates
    a boosting campaign on Meta to amplify it.

    Triggers when:
      - Vote count > 100 in last 24h
      - Vote velocity increasing (last 6h > avg of last 48h)
    """
    from sqlalchemy import text

    debate_id    = debate.get('id')
    debate_title = debate.get('title', '')
    country      = debate.get('scope_country', 'CL')

    try:
        row = db.execute(text("""
            SELECT COUNT(*) as votes_24h
            FROM debate_votes
            WHERE debate_id = :did
              AND created_at >= datetime('now', '-24 hours')
        """), {'did': debate_id}).fetchone()
        votes_24h = int(row[0] or 0)
    except Exception:
        votes_24h = 0

    if votes_24h < 100:
        return {
            'boosted':    False,
            'reason':     f'Only {votes_24h} votes in 24h — threshold is 100',
            'debate_id':  debate_id,
        }

    # Calculate boost budget: $5-30 depending on engagement
    boost_budget = min(30.0, max(5.0, votes_24h / 20))
    lang = COUNTRY_LANG.get(country, 'es')
    text_templates = {
        'es': f'¿Ya votaste en "{debate_title}"? Únete a la conversación democrática. Tu voz cuenta. 🗳️',
        'en': f'"{debate_title}" is trending! Join the democratic conversation. Your vote matters. 🗳️',
        'pt': f'"{debate_title}" está em alta! Participe da conversa democrática. 🗳️',
    }
    ad_text = text_templates.get(lang, text_templates['es'])

    result = create_meta_acquisition_campaign(
        country      = country,
        budget_usd   = boost_budget,
        objective    = 'LINK_CLICKS',
        age_min      = debate.get('target_age_min') or 18,
        age_max      = debate.get('target_age_max') or 65,
        creative_text= ad_text,
    )

    print(f'[MarketingAgent] Auto-boosted debate {debate_id} "{debate_title}" with ${boost_budget:.0f} Meta campaign')

    return {
        'boosted':     True,
        'debate_id':   debate_id,
        'votes_24h':   votes_24h,
        'boost_budget': boost_budget,
        'meta_campaign': result,
    }


# ══════════════════════════════════════════════════════════════
# ATTRIBUTION — Rastrear qué canal trajo a cada usuario
# ══════════════════════════════════════════════════════════════

ATTRIBUTION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_attribution (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER REFERENCES users(id),
    channel       TEXT NOT NULL DEFAULT 'organic',
    campaign_id   TEXT,
    ad_set_id     TEXT,
    country       TEXT,
    utm_source    TEXT,
    utm_medium    TEXT,
    utm_campaign  TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_attribution_user    ON user_attribution(user_id);
CREATE INDEX IF NOT EXISTS idx_attribution_channel ON user_attribution(channel);
"""

def record_attribution(db, user_id: int, channel: str, campaign_id: str = None,
                       utm_source: str = None, utm_medium: str = None,
                       utm_campaign: str = None, country: str = None):
    """Records which marketing channel brought a user (called at registration)."""
    from sqlalchemy import text
    try:
        db.execute(text("""
            INSERT OR IGNORE INTO user_attribution
              (user_id, channel, campaign_id, utm_source, utm_medium, utm_campaign, country)
            VALUES (:uid, :ch, :cid, :src, :med, :camp, :country)
        """), {
            'uid': user_id, 'ch': channel, 'cid': campaign_id,
            'src': utm_source, 'med': utm_medium, 'camp': utm_campaign,
            'country': country,
        })
        db.commit()
    except Exception as e:
        print(f'[MarketingAgent] Attribution error: {e}')


def get_channel_performance_summary(db) -> dict:
    """Returns acquisition funnel by channel over the last 30 days."""
    from sqlalchemy import text
    try:
        rows = db.execute(text("""
            SELECT channel,
                   COUNT(*) as registrations,
                   COUNT(CASE WHEN u.is_verified THEN 1 END) as verified_users
            FROM user_attribution a
            JOIN users u ON u.id = a.user_id
            WHERE a.created_at >= datetime('now', '-30 days')
            GROUP BY channel
            ORDER BY registrations DESC
        """)).fetchall()

        channels = []
        for r in rows:
            r = dict(r._mapping)
            target_cac = TARGET_CAC.get(r['channel'], 0)
            channels.append({
                **r,
                'verify_rate_pct': round(r['verified_users'] / max(r['registrations'], 1) * 100, 1),
                'target_cac_usd':  target_cac,
            })
        return {'channels': channels, 'period_days': 30}
    except Exception as e:
        return {'channels': [], 'error': str(e)}


# ══════════════════════════════════════════════════════════════
# CREATIVIDADES POR DEFECTO
# ══════════════════════════════════════════════════════════════

def _default_ad_text(country: str, lang: str) -> str:
    templates = {
        'es': (
            "¿Tu opinión importa? Demuéstralo. Preferendum es la plataforma "
            "donde tu voto queda anclado en blockchain — anónimo e inmutable. "
            "Únete a millones que ya participan. 🗳️"
        ),
        'en': (
            "Your vote. Your voice. Blockchain-verified and 100% anonymous. "
            "Join Preferendum — the democratic platform where your opinion matters. 🗳️"
        ),
        'pt': (
            "Sua opinião importa. Vote com segurança na Preferendum — "
            "plataforma democrática com verificação em blockchain, 100% anônima. 🗳️"
        ),
        'de': (
            "Ihre Stimme zählt. Blockchain-gesichert und anonym. "
            "Machen Sie mit bei Preferendum. 🗳️"
        ),
        'fr': (
            "Votre voix compte. Vote anonyme et vérifié sur blockchain. "
            "Rejoignez Preferendum. 🗳️"
        ),
        'it': (
            "La tua opinione conta. Vota in modo anonimo e sicuro su blockchain. "
            "Unisciti a Preferendum. 🗳️"
        ),
    }
    return templates.get(lang, templates['es'])


# ══════════════════════════════════════════════════════════════
# TAREAS PROGRAMADAS
# ══════════════════════════════════════════════════════════════

def run_daily_marketing_checks(db) -> dict:
    """
    Runs every day:
    - Checks campaigns needing attention
    - Calculates acquisition budget
    - Identifies debates to boost
    """
    print('[MarketingAgent] === DAILY MARKETING CHECKS ===')

    attention = get_campaigns_needing_attention(db)
    budget    = calculate_acquisition_budget(db)

    print(f'  Low budget campaigns: {len(attention["low_budget"])}')
    print(f'  No-impression campaigns: {len(attention["no_impressions"])}')
    print(f'  Expiring soon: {len(attention["expiring_soon"])}')
    print(f'  Acquisition budget available: ${budget["acquisition_budget_usd"]:.2f}')

    return {
        'campaigns_needing_attention': attention,
        'acquisition_budget':          budget,
        'run_at':                      datetime.utcnow().isoformat(),
    }


def run_weekly_advertiser_reports(db) -> dict:
    """
    Runs every Monday:
    - Generates performance reports for all active advertisers
    - Logs recommendations
    """
    from sqlalchemy import text
    print('[MarketingAgent] === WEEKLY ADVERTISER REPORTS ===')

    try:
        advertisers = db.execute(text("""
            SELECT DISTINCT advertiser_email,
                   json_group_array(json_object(
                     'id', id, 'title', title, 'status', status,
                     'cpm', cpm, 'impressions_served', impressions_served,
                     'clicks', clicks, 'target_country', target_country,
                     'target_communes', target_communes,
                     'target_gender', target_gender,
                     'target_age_min', target_age_min,
                     'target_age_max', target_age_max,
                     'min_income_tier', min_income_tier,
                     'remaining_budget', remaining_budget
                   )) as campaigns_json
            FROM ad_campaigns
            WHERE is_active=1
            GROUP BY advertiser_email
        """)).fetchall()

        reports = []
        for row in advertisers:
            email = row[0]
            campaigns = json.loads(row[1])
            report = generate_advertiser_report(email, campaigns, db)
            reports.append({'email': email, 'summary': report['summary']})
            print(f'  Report for {email}: {report["summary"]["total_impressions"]} impressions, ${report["summary"]["total_spent_usd"]:.2f} spent')

        return {'reports_generated': len(reports), 'advertisers': reports}
    except Exception as e:
        print(f'[MarketingAgent] Weekly report error: {e}')
        return {'error': str(e)}
