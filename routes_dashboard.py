# advertiser/routes_dashboard.py
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from db import get_db
from models import AdCampaign, AdImpressionLog

router = APIRouter(prefix="/advertiser", tags=["Advertising"])
COST_PER_VIEW = 20  # CLP

@router.get("/dashboard/{campaign_id}")
def get_dashboard(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    views     = db.query(AdImpressionLog).filter(AdImpressionLog.campaign_id == campaign_id).all()
    total_imp = len(views)
    spent     = total_imp * COST_PER_VIEW
    balance   = campaign.budget_clp - spent

    by_gender = {}
    by_age    = {}
    for v in views:
        by_gender[v.gender]    = by_gender.get(v.gender, 0) + 1
        by_age[v.age_group]    = by_age.get(v.age_group, 0) + 1

    return {
        "campaign_id":    campaign_id,
        "title":          campaign.title,
        "advertiser":     campaign.advertiser_name,
        "budget_clp":     campaign.budget_clp,
        "impressions":    total_imp,
        "spent_clp":      spent,
        "balance_clp":    balance,
        "cost_per_view":  COST_PER_VIEW,
        "by_gender":      by_gender,
        "by_age":         by_age,
    }
