# ============================================================
# Preferendum — main.py
# Complete unified FastAPI application
# All modules wired together and working
#
# In memory of José Ignacio Fernández (1989–2024)
# ============================================================
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
import os, jwt, bcrypt

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./preferendum.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True)
    name = Column(String)
    password = Column(String)
    country = Column(String)
    county = Column(String)
    gender = Column(String)

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Preferendum API", version="1.0.0", description="En memoria de Jose Ignacio Fernandez (1989-2024)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "preferendum-secret"))
SECRET = os.getenv("JWT_SECRET", "preferendum-secret")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def make_token(user_id):
    return jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")

class RegisterInput(BaseModel):
    email: str
    password: str
    name: str
    country: str = "CL"
    county: str = ""
    gender: str = "F"

class LoginInput(BaseModel):
    email: str
    password: str

@app.get("/")
def root():
    return {"system":"Preferendum","version":"1.0.0","status":"running","dedication":"En memoria de Jose Ignacio Fernandez (1989-2024)"}

@app.get("/health")
def health():
    return {"status":"ok"}

@app.post("/auth/register")
def register(data: RegisterInput, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(400, "Email already registered")
    hashed = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    user = User(email=data.email, name=data.name, password=hashed, country=data.country, county=data.county, gender=data.gender)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = make_token(user.id)
    return {"token": token, "user": {"id": user.id, "name": user.name, "email": user.email}}

@app.post("/auth/login")
def login(data: LoginInput, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        raise HTTPException(401, "Invalid credentials")
    if not bcrypt.checkpw(data.password.encode(), user.password.encode()):
        raise HTTPException(401, "Invalid credentials")
    token = make_token(user.id)
    return {"token": token, "user": {"id": user.id, "name": user.name, "email": user.email}}

@app.get("/auth/me")
def me(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
        user = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not user:
            raise HTTPException(404, "User not found")
        return {"id": user.id, "name": user.name, "email": user.email, "gender": user.gender}
    except:
        raise HTTPException(401, "Invalid token")
