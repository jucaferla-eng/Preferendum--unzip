# routes_debate.py — Debate management + comment feed

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
from db import get_db
from models import Debate, DebateOption, DebateComment, User, AdCampaign, AdImpressionLog
from auth import get_current_user
from advertising.ad_matching_engine import match_ads_for_user

router = APIRouter(prefix="/debates", tags=["Debates"])


class DebateCreate(BaseModel):
    title: str
    description: str
    category: str
    institution: str
    inst_type: str = "gov"
    country: str
    state: str = ""
    county: str = ""
    min_age: int = 0
    max_age: int = 120
    gender: str = "all"
    options: list[str]
    end_dt: Optional[str] = None

class CommentCreate(BaseModel):
    content: str


@router.post("/")
def create_debate(
    data: DebateCreate,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user)
):
    if user.role not in ("organizer", "admin"):
        raise HTTPException(403, "Only organizers can create debates")

    debate = Debate(
        title       = data.title,
        description = data.description,
        category    = data.category,
        institution = data.institution,
        inst_type   = data.inst_type,
        country     = data.country,
        state       = data.state,
        county      = data.county,
        min_age     = data.min_age,
        max_age     = data.max_age,
        gender      = data.gender,
        end_dt      = datetime.fromisoformat(data.end_dt) if data.end_dt else None,
    )
    db.add(debate)
    db.flush()

    for i, opt_text in enumerate(data.options):
        db.add(DebateOption(debate_id=debate.id, text=opt_text, order_num=i))

    db.commit()
    db.refresh(debate)
    return _debate_out(debate)


@router.get("/")
def list_debates(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user)
):
    """
    Return debates personalized for this voter.
    Filters by country, county, age, gender.
    Injects matched ads between debate cards.
    """
    from datetime import datetime
    user_age = datetime.now().year - int(user.dob[:4]) if user.dob else 30

    debates = db.query(Debate).filter(Debate.is_closed == False).all()

    # Filter to debates this user can access
    accessible = []
    for d in debates:
        if d.country and d.country != user.country:
            continue
        if d.county and d.county != user.county:
            continue
        if d.min_age and user_age < d.min_age:
            continue
        if d.max_age and user_age > d.max_age:
            continue
        if d.gender and d.gender != "all" and d.gender != user.gender:
            continue
        accessible.append(_debate_out(d))

    # Get matched ads for this user
    ads = match_ads_for_user(
        db          = db,
        user_country= user.country,
        user_county = user.county,
        user_age    = user_age,
        user_gender = user.gender,
    )

    # Interleave: debate, debate, ad, debate, debate, ad…
    feed = []
    for i, debate in enumerate(accessible):
        feed.append({"type": "debate", "data": debate})
        if (i + 1) % 2 == 0 and ads:
            feed.append({"type": "ad", "data": ads[i % len(ads)]})

    return {"feed": feed, "total_debates": len(accessible)}


@router.get("/{debate_id}")
def get_debate(
    debate_id: int,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user)
):
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, "Debate not found")
    return _debate_out(debate, include_comments=True)


@router.post("/{debate_id}/comments")
def post_comment(
    debate_id: int,
    data: CommentCreate,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user)
):
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, "Debate not found")

    comment = DebateComment(
        debate_id = debate_id,
        user_id   = user.id,
        content   = data.content,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return {"id": comment.id, "content": comment.content, "author": user.name}


@router.post("/{debate_id}/comments/{comment_id}/like")
def like_comment(
    debate_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    user: User  = Depends(get_current_user)
):
    comment = db.query(DebateComment).filter(DebateComment.id == comment_id).first()
    if not comment:
        raise HTTPException(404, "Comment not found")
    comment.likes += 1
    db.commit()
    return {"likes": comment.likes}


def _debate_out(debate: Debate, include_comments: bool = False) -> dict:
    out = {
        "id":          debate.id,
        "title":       debate.title,
        "description": debate.description,
        "category":    debate.category,
        "institution": debate.institution,
        "inst_type":   debate.inst_type,
        "country":     debate.country,
        "county":      debate.county,
        "is_closed":   debate.is_closed,
        "end_dt":      debate.end_dt.isoformat() if debate.end_dt else None,
        "options":     [{"id": o.id, "text": o.text} for o in debate.options],
        "vote_count":  len(debate.votes),
    }
    if include_comments:
        out["comments"] = [
            {
                "id":      c.id,
                "content": c.content,
                "author":  c.user.name if c.user else "Anonymous",
                "likes":   c.likes,
                "created": c.created_at.isoformat(),
            }
            for c in sorted(debate.comments, key=lambda x: x.created_at, reverse=True)
        ]
    return out
