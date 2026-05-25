# advertiser/routes_ads_upload.py
from fastapi import APIRouter, Form, Depends
from sqlalchemy.orm import Session
from db import get_db
from models import AdCampaign
from datetime import datetime

router = APIRouter(prefix="/advertiser", tags=["Advertising"])

@router.post("/upload-campaign/")
async def upload_campaign(
    advertiser_email: str  = Form(...),
    advertiser_name:  str  = Form(...),
    campaign_title:   str  = Form(...),
    budget_clp:       int  = Form(...),
    ad_type:          str  = Form("banner"),
    target_country:   str  = Form(""),
    target_gender:    str  = Form("all"),
    target_age_ranges:str  = Form(""),
    target_categories:str  = Form(""),
    excluded_categories:str= Form(""),
    blocked_competitors:str= Form(""),
    start_date:       str  = Form(...),
    end_date:         str  = Form(...),
    db: Session = Depends(get_db)
):
    campaign = AdCampaign(
        advertiser_email    = advertiser_email,
        advertiser_name     = advertiser_name,
        title               = campaign_title,
        budget_clp          = budget_clp,
        ad_type             = ad_type,
        target_country      = target_country,
        target_gender       = target_gender,
        target_age_ranges   = target_age_ranges,
        target_categories   = target_categories,
        excluded_categories = excluded_categories,
        blocked_competitors = blocked_competitors,
        start_date          = datetime.fromisoformat(start_date),
        end_date            = datetime.fromisoformat(end_date),
        is_active           = True,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return {"message": "Campaign created", "campaign_id": campaign.id}
