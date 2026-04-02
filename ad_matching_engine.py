# advertising/ad_matching_engine.py
# Matches active ad campaigns to a voter's profile

from sqlalchemy.orm import Session
from models import AdCampaign
from datetime import datetime


def match_ads_for_user(
    db:           Session,
    user_country: str,
    user_county:  str,
    user_age:     int,
    user_gender:  str,
) -> list[dict]:
    """
    Return list of matching ad campaigns for this voter profile.
    Used by routes_debate.py to inject ads into the debate feed.
    """
    today = datetime.utcnow().date()

    campaigns = db.query(AdCampaign).filter(
        AdCampaign.is_active == True,
        AdCampaign.start_date <= datetime.utcnow(),
        AdCampaign.end_date   >= datetime.utcnow(),
    ).all()

    matched = []
    for ad in campaigns:
        # Country match
        if ad.target_country and ad.target_country != user_country:
            continue
        # County match
        if ad.target_communes and user_county not in ad.target_communes.split(","):
            continue
        # Gender match
        if ad.target_gender and ad.target_gender != "all" and ad.target_gender != user_gender:
            continue
        # Age match
        age_ok = True
        if ad.target_age_ranges:
            age_ok = False
            for rng in ad.target_age_ranges.split(","):
                rng = rng.strip()
                if "-" in rng:
                    lo, hi = map(int, rng.split("-"))
                    if lo <= user_age <= hi:
                        age_ok = True
                        break
                elif rng.endswith("+"):
                    if user_age >= int(rng[:-1]):
                        age_ok = True
                        break
        if not age_ok:
            continue

        matched.append({
            "campaign_id":     ad.id,
            "advertiser_name": ad.advertiser_name,
            "title":           ad.title,
            "ad_type":         ad.ad_type,
            "banner_path":     ad.banner_path,
            "ad_text":         ad.ad_text,
        })

    return matched
