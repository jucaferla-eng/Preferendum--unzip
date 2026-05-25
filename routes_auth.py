# auth/routes_auth.py — Registration, Login, Current User

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from db import get_db
from models import User
from auth.security import hash_password, verify_password, create_token, decode_token
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

router = APIRouter(prefix="/auth", tags=["Auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── SCHEMAS ──────────────────────────────────────────────────
class RegisterInput(BaseModel):
    email: str
    name: str
    password: str
    country: str
    state: str
    county: str
    dob: str           # YYYY-MM-DD
    gender: str        # F / M / O
    national_id: str

class UserOut(BaseModel):
    id: int
    email: str
    name: str
    country: str
    county: str
    gender: str
    role: str

    class Config:
        from_attributes = True

class TokenOut(BaseModel):
    access_token: str
    token_type: str


# ── REGISTER ─────────────────────────────────────────────────
@router.post("/register", response_model=UserOut)
def register(data: RegisterInput, db: Session = Depends(get_db)):
    # Check uniqueness
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, "Email already registered")
    if db.query(User).filter(User.national_id == data.national_id).first():
        raise HTTPException(400, "National ID already registered")

    user = User(
        email       = data.email,
        name        = data.name,
        password    = hash_password(data.password),
        country     = data.country,
        state       = data.state,
        county      = data.county,
        dob         = data.dob,
        gender      = data.gender,
        national_id = data.national_id,
        role        = "voter",
        is_verified = True,   # simplified — full 7-layer in registration_service.py
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── LOGIN ─────────────────────────────────────────────────────
@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form.username).first()
    if not user or not verify_password(form.password, user.password):
        raise HTTPException(401, "Invalid credentials")
    token = create_token({"sub": str(user.id), "role": user.role})
    return {"access_token": token, "token_type": "bearer"}


# ── CURRENT USER ─────────────────────────────────────────────
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_token(token)
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user:
        raise HTTPException(401, "User not found")
    return user


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
