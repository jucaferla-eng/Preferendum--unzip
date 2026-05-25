# verification/routes_global_stats.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db import get_db
from models import AnonymousVoteRecord, Debate, User, AdCampaign

router = APIRouter(prefix="/stats", tags=["Stats"])

@router.get("/global")
def global_stats(db: Session = Depends(get_db)):
    return {
        "total_votes":     db.query(AnonymousVoteRecord).count(),
        "total_debates":   db.query(Debate).count(),
        "active_debates":  db.query(Debate).filter(Debate.is_closed == False).count(),
        "total_voters":    db.query(User).count(),
        "active_campaigns":db.query(AdCampaign).filter(AdCampaign.is_active == True).count(),
        "system":          "Preferendum v1.0",
        "blockchain":      "Polygon Mainnet",
        "dedication":      "En memoria de José Ignacio Fernández (1989–2024)",
    }
