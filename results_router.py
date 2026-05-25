# results/results_router.py
# Live vote results per debate — anonymous aggregation only

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from db import get_db
from models import Debate, AnonymousVoteRecord
from auth import get_current_user
from models import User
from utils.encryptor import SECRET_KEY
import json, base64
from Crypto.Cipher import AES

router = APIRouter(prefix="/results", tags=["Results"])


def _decrypt_option(encrypted: str) -> str:
    """Decrypt a vote to get the chosen option (for aggregation only)."""
    try:
        raw    = base64.b64decode(encrypted.encode())
        iv     = raw[:16]
        cipher = AES.new(SECRET_KEY, AES.MODE_CBC, iv)
        dec    = cipher.decrypt(raw[16:])
        pad    = dec[-1]
        data   = json.loads(dec[:-pad].decode("utf-8"))
        return data.get("option", "unknown")
    except Exception:
        return "unknown"


@router.get("/{debate_id}")
def get_results(
    debate_id: int,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user)
):
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, "Debate not found")

    votes = db.query(AnonymousVoteRecord).filter(
        AnonymousVoteRecord.debate_id == debate_id
    ).all()

    # Aggregate — count per option
    option_counts = {o.text: 0 for o in debate.options}
    by_gender     = {"F": {}, "M": {}, "O": {}}
    by_age        = {}

    for v in votes:
        option = _decrypt_option(v.encrypted_vote)
        if option in option_counts:
            option_counts[option] += 1

        # Gender breakdown
        g = v.gender or "O"
        if g not in by_gender:
            by_gender[g] = {}
        by_gender[g][option] = by_gender[g].get(option, 0) + 1

        # Age breakdown
        ag = v.age_group or "unknown"
        if ag not in by_age:
            by_age[ag] = {}
        by_age[ag][option] = by_age[ag].get(option, 0) + 1

    total = sum(option_counts.values())

    # Percentages
    results = []
    for opt_text, count in option_counts.items():
        pct = round(count / total * 100, 1) if total > 0 else 0
        results.append({
            "option":     opt_text,
            "votes":      count,
            "percentage": pct,
        })

    # Sort by votes descending
    results.sort(key=lambda x: x["votes"], reverse=True)

    # Statistical irreversibility check
    irreversible = False
    if len(results) >= 2 and total >= 10:
        irreversible = (
            results[0]["percentage"] > 50 and
            results[0]["percentage"] - results[1]["percentage"] > 10
        )

    return {
        "debate_id":               debate_id,
        "debate_title":            debate.title,
        "institution":             debate.institution,
        "total_votes":             total,
        "results":                 results,
        "by_gender":               by_gender,
        "by_age":                  by_age,
        "is_closed":               debate.is_closed,
        "is_statistically_irreversible": irreversible,
    }
