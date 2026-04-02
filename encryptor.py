# utils/encryptor.py
# AES-256-CBC vote encryption + verification code generator
# José's design: vote encrypted, hash goes to blockchain, code goes to voter

import os
import json
import base64
import hashlib
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

# 32-byte key from env. CHANGE THIS in production — use a proper key vault.
_raw_key = os.getenv("VOTE_ENCRYPTION_KEY", "preferendum_super_secure_key_change_in_prod")
SECRET_KEY = hashlib.sha256(_raw_key.encode()).digest()


def _pad(data: bytes) -> bytes:
    pad_len = AES.block_size - len(data) % AES.block_size
    return data + bytes([pad_len] * pad_len)


def encrypt_vote(debate_id: int, option: str, metadata: dict) -> str:
    """
    Encrypt vote + anonymous metadata with AES-256-CBC.
    Random IV per vote — every encrypted blob is unique.
    Returns base64 string.
    """
    payload = {
        "debate_id": debate_id,
        "option":    option,
        "meta":      metadata,   # gender, age_group, county, country — NO identity
    }
    raw   = json.dumps(payload).encode("utf-8")
    iv    = get_random_bytes(16)
    cipher = AES.new(SECRET_KEY, AES.MODE_CBC, iv)
    enc   = cipher.encrypt(_pad(raw))
    return base64.b64encode(iv + enc).decode("utf-8")


def generate_verification_code(vote_hash: str) -> str:
    """
    Generate human-readable verification code from vote hash.
    Format: XXXX-XXXX-XXXX (first 12 hex chars of SHA-256)
    Voter uses this to self-verify their vote at any time.
    """
    h = vote_hash[:12].upper()
    return f"{h[0:4]}-{h[4:8]}-{h[8:12]}"
