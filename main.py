# ============================================================
# Preferendum — main.py
# Complete unified FastAPI application
# All modules wired together and working
#
# In memory of José Ignacio Fernández (1989–2024)
# ============================================================
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
import os, jwt, bcrypt

DB = os.getenv('DATABASE_URL', 'sqlite:///./preferendum.db')
ARGS = {'check_same_thread': False} if 'sqlite' in DB else {}
engine = create_engine(DB, connect_args=ARGS)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True)
    name = Column(String)
    password = Column(String)
    country = Column(String)
    county = Column(String)
    gender = Column(String)

Base.metadata.create_all(bind=engine)
app = FastAPI(title='Preferendum API', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
SECRET = os.getenv('JWT_SECRET', 'preferendum-secret')

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def make_token(uid):
    return jwt.encode({'sub': str(uid)}, SECRET, algorithm='HS256')

class Reg(BaseModel):
    email: str
    password: str
    name: str
    country: str = 'CL'
    county: str = ''
    gender: str = 'F'

class Log(BaseModel):
    email: str
    password: str

@app.get('/')
def root():
    return {'system': 'Preferendum', 'status': 'running'}

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.post('/auth/register')
def register(data: Reg, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, 'Email already registered')
    pw = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    u = User(email=data.email, name=data.name, password=pw, country=data.country, county=data.county, gender=data.gender)
    db.add(u)
    db.commit()
    db.refresh(u)
    return {'token': make_token(u.id), 'user': {'id': u.id, 'name': u.name, 'email': u.email}}

@app.post('/auth/login')
def login(data: Log, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.email == data.email).first()
    if not u or not bcrypt.checkpw(data.password.encode(), u.password.encode()):
        raise HTTPException(401, 'Invalid credentials')
    return {'token': make_token(u.id), 'user': {'id': u.id, 'name': u.name, 'email': u.email}}

@app.get('/auth/me')
def me(creds: HTTPAuthorizationCredentials = Depends(HTTPBearer()), db: Session = Depends(get_db)):
    try:
        pay = jwt.decode(creds.credentials, SECRET, algorithms=['HS256'])
        u = db.query(User).filter(User.id == int(pay['sub'])).first()
        if not u:
            raise HTTPException(404, 'Not found')
        return {'id': u.id, 'name': u.name, 'email': u.email, 'gender': u.gender}
    except:
        raise HTTPException(401, 'Invalid token')
