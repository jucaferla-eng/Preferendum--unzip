# auth/security.py — Password hashing and JWT tokens

import os
import bcrypt
from jose import jwt, JWTError
from datetime import datetime, timedelta

SECRET_KEY  = os.getenv("JWT_SECRET", "preferendum-jwt-secret-change-in-production")
ALGORITHM   = "HS256"
TOKEN_HOURS = 72

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def create_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(hours=TOKEN_HOURS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
