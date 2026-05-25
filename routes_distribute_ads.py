# distribution/routes_distribute_ads.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db import get_db
from models import User
from auth import get_current_user
from advertising.ad_matching_engine import match_ads_for_user
from datetime import datetime

router = APIRouter(prefix="/ads", tags=["Advertising"])

@router.get("/user/{user_id}")
def get_ads_for_user(user_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    age = datetime.now().year - int(user.dob[:4]) if user.dob else 30
    ads = match_ads_for_user(db, user.country, user.county, age, user.gender)
    return {"ads": ads}
