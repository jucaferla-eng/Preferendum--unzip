# verification/routes_vote_verification.py
# Voter self-verification — José's insight:
# Every voter can verify their own vote using their code.
# This makes voters the auditors, not a central authority.

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from db import get_db
from models import VoteVerificationLog

router = APIRouter(prefix="/verify", tags=["Verification"])

@router.get("/vote/{vcode}")
def verify_vote(vcode: str, db: Session = Depends(get_db)):
    """
    Public endpoint. Voter enters their verification code.
    Returns: confirmation their vote exists on blockchain.
    No identity. No vote content. Just proof it was recorded.
    """
    record = db.query(VoteVerificationLog).filter(
        VoteVerificationLog.vcode == vcode
    ).first()

    if not record:
        raise HTTPException(404, "Verification code not found. Check the code and try again.")

    return {
        "verified":   True,
        "vcode":      vcode,
        "vote_hash":  record.vote_hash,
        "tx_hash":    record.tx_hash,
        "debate_id":  record.debate_id,
        "verified_at":record.verified_at.isoformat(),
        "message":    "Your vote was recorded and anchored to the Polygon blockchain.",
        "check_on":   f"https://polygonscan.com/tx/{record.tx_hash}",
        "dedication": "En memoria del Socio Fundador José Ignacio Fernández (1989–2024) — who designed this verification system.",
    }
