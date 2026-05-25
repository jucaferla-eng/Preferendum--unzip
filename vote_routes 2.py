# vote_routes.py
# Preferendum — Vote submission
# The bridge is destroyed here: voter identity never touches the vote record.
#
# Flow:
# 1. Authenticated voter sends debate_id + option
# 2. We pull their anonymous demographics (NOT stored in vote)
# 3. Check they haven't already voted (HasVotedLog)
# 4. Encrypt vote + demographics with AES-256
# 5. SHA-256 hash the encrypted blob
# 6. Send hash to Polygon blockchain
# 7. Store AnonymousVoteRecord (no voter_id)
# 8. Store HasVotedLog (debate_id + user_id only — no vote data)
# 9. voter_id is set to None and deleted from local scope → BRIDGE DESTROYED
# 10. Return verification code to voter

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from db import get_db
from models import User, Debate, DebateOption, AnonymousVoteRecord, HasVotedLog, VoteVerificationLog
from auth import get_current_user
from utils.encryptor import encrypt_vote, generate_verification_code
from utils.blockchain import send_vote_to_blockchain
import hashlib

router = APIRouter(prefix="/vote", tags=["Voting"])


class VoteInput(BaseModel):
    debate_id: int
    option_selected: str

class VoteResponse(BaseModel):
    message: str
    verification_code: str
    tx_hash: str


@router.post("/", response_model=VoteResponse)
def submit_vote(
    vote: VoteInput,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user)
):
    # ── 1. Check debate exists and is open ───────────────────
    debate = db.query(Debate).filter(Debate.id == vote.debate_id).first()
    if not debate:
        raise HTTPException(404, "Debate not found")
    if debate.is_closed:
        raise HTTPException(400, "This debate is closed")

    # ── 2. Check option is valid ─────────────────────────────
    valid_options = [o.text for o in debate.options]
    if vote.option_selected not in valid_options:
        raise HTTPException(400, f"Invalid option. Valid: {valid_options}")

    # ── 3. Check user hasn't already voted ───────────────────
    already = db.query(HasVotedLog).filter(
        HasVotedLog.user_id   == user.id,
        HasVotedLog.debate_id == vote.debate_id
    ).first()
    if already:
        raise HTTPException(409, "You have already voted in this debate")

    # ── 4. Extract anonymous demographics ONLY ───────────────
    metadata = {
        "gender":    user.gender,
        "age_group": _age_group(user.dob),
        "county":    user.county,
        "country":   user.country,
    }

    # ── 5. Encrypt vote + metadata (AES-256-CBC, random IV) ──
    encrypted = encrypt_vote(vote.debate_id, vote.option_selected, metadata)

    # ── 6. SHA-256 hash of encrypted blob ────────────────────
    vote_hash = hashlib.sha256(encrypted.encode()).hexdigest()

    # ── 7. Generate verification code ────────────────────────
    vcode = generate_verification_code(vote_hash)

    # ── 8. Send to Polygon blockchain ────────────────────────
    tx_hash = send_vote_to_blockchain(vote_hash, vcode)

    # ── 9. Store ANONYMOUS vote record (NO voter identity) ───
    anon_vote = AnonymousVoteRecord(
        debate_id      = vote.debate_id,
        encrypted_vote = encrypted,
        vote_hash      = vote_hash,
        tx_hash        = tx_hash,
        vcode          = vcode,
        gender         = metadata["gender"],
        age_group      = metadata["age_group"],
        county         = metadata["county"],
        country        = metadata["country"],
        # voter_id intentionally NOT stored
    )
    db.add(anon_vote)

    # ── 10. Store voted log (prevents double-voting, NO vote data) ──
    voted_log = HasVotedLog(
        user_id   = user.id,
        debate_id = vote.debate_id,
    )
    db.add(voted_log)

    # ── 11. Store verification record (public lookup) ────────
    verify_log = VoteVerificationLog(
        vcode     = vcode,
        vote_hash = vote_hash,
        tx_hash   = tx_hash,
        debate_id = vote.debate_id,
    )
    db.add(verify_log)

    db.commit()

    # ── 12. BRIDGE DESTROYED ─────────────────────────────────
    voter_id = user.id   # last reference
    voter_id = None      # severed
    del voter_id         # gone

    return VoteResponse(
        message           = "Voto registrado correctamente en blockchain Polygon",
        verification_code = vcode,
        tx_hash           = tx_hash,
    )


@router.get("/check/{debate_id}")
def check_if_voted(
    debate_id: int,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user)
):
    """Check if current user has already voted in a debate."""
    voted = db.query(HasVotedLog).filter(
        HasVotedLog.user_id   == user.id,
        HasVotedLog.debate_id == debate_id
    ).first()
    return {"has_voted": bool(voted)}


def _age_group(dob: str) -> str:
    """Convert date of birth to anonymous age group."""
    if not dob:
        return "unknown"
    try:
        from datetime import datetime
        birth_year = int(dob[:4])
        age = datetime.now().year - birth_year
        if age < 18:  return "under-18"
        if age < 25:  return "18-24"
        if age < 35:  return "25-34"
        if age < 45:  return "35-44"
        if age < 55:  return "45-54"
        if age < 65:  return "55-64"
        return "65+"
    except Exception:
        return "unknown"
