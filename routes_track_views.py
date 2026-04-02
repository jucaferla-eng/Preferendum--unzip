# tracking/routes_track_views.py
from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from db import get_db
from models import AdCampaign, AdImpressionLog

router = APIRouter(prefix="/ads", tags=["Tracking"])
COST_PER_VIEW = 20  # CLP

@router.post("/view/")
async def track_ad_view(request: Request, db: Session = Depends(get_db)):
    data        = await request.json()
    campaign_id = data.get("campaign_id")
    gender      = data.get("gender", "")
    age_group   = data.get("age_group", "")
    county      = data.get("county", "")
    country     = data.get("country", "")
    debate_id   = data.get("debate_id")

    campaign = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not campaign:
        return {"error": "Campaign not found"}

    log = AdImpressionLog(
        campaign_id = campaign_id,
        debate_id   = debate_id,
        gender      = gender,
        age_group   = age_group,
        county      = county,
        country     = country,
    )
    db.add(log)
    campaign.spent_clp += COST_PER_VIEW
    db.commit()

    return {
        "message":      "Impression recorded",
        "spent_clp":    campaign.spent_clp,
        "balance_clp":  campaign.budget_clp - campaign.spent_clp,
    }
