from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import os, jwt, bcrypt, hashlib, base64, json, random

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
    created_at = Column(String, default=str(datetime.utcnow()))

class Debate(Base):
    __tablename__ = 'debates'
    id = Column(Integer, primary_key=True)
    title = Column(String)
    description = Column(Text)
    institution = Column(String)
    inst_type = Column(String)
    country = Column(String)
    status = Column(String, default='live')
    created_at = Column(String, default=str(datetime.utcnow()))

class DebateOption(Base):
    __tablename__ = 'debate_options'
    id = Column(Integer, primary_key=True)
    debate_id = Column(Integer)
    text = Column(String)
    order_num = Column(Integer)

class AnonVote(Base):
    __tablename__ = 'anon_votes'
    id = Column(Integer, primary_key=True)
    debate_id = Column(Integer)
    vote_hash = Column(String)
    vcode = Column(String, unique=True)
    gender = Column(String)
    county = Column(String)
    option_text = Column(String)
    created_at = Column(String, default=str(datetime.utcnow()))

class HasVoted(Base):
    __tablename__ = 'has_voted'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    debate_id = Column(Integer)

Base.metadata.create_all(bind=engine)

app = FastAPI(title='Preferendum API', version='2.0.0')
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

def get_user(creds, db):
    try:
        pay = jwt.decode(creds.credentials, SECRET, algorithms=['HS256'])
        u = db.query(User).filter(User.id == int(pay['sub'])).first()
        if not u:
            raise HTTPException(401, 'User not found')
        return u
    except:
        raise HTTPException(401, 'Invalid token')

def seed_debates(db):
    if db.query(Debate).count() > 0:
        return
    debates = [
        ('Prioridad presupuesto 2027', 'Consulta ciudadana sobre presupuesto municipal', 'Municipalidad Las Condes', 'gov', 'CL', ['Infraestructura vial', 'Salud publica', 'Educacion', 'Areas verdes']),
        ('Plan de movilidad', 'Tu opinion sobre el nuevo plan de movilidad', 'Municipalidad Providencia', 'gov', 'CL', ['Ciclovias', 'Metro ampliado', 'Buses electricos', 'Zonas peatonales']),
        ('Cual zapatilla 2026?', 'Nike consulta al mercado antes de producir', 'Nike Chile', 'priv', 'CL', ['Air Max Pulse', 'Air Force 1', 'React Infinity', 'Pegasus Trail']),
    ]
    for title, desc, inst, itype, country, opts in debates:
        d = Debate(title=title, description=desc, institution=inst, inst_type=itype, country=country)
        db.add(d)
        db.flush()
        for i, opt in enumerate(opts):
            db.add(DebateOption(debate_id=d.id, text=opt, order_num=i))
    db.commit()

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

class VoteInput(BaseModel):
    debate_id: int
    option_text: str

@app.get('/')
def root():
    return {'system': 'Preferendum', 'version': '2.0.0', 'status': 'running', 'dedication': 'En memoria de Jose Ignacio Fernandez (1989-2024)'}

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
    seed_debates(db)
    return {'token': make_token(u.id), 'user': {'id': u.id, 'name': u.name, 'email': u.email}}

@app.post('/auth/login')
def login(data: Log, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.email == data.email).first()
    if not u or not bcrypt.checkpw(data.password.encode(), u.password.encode()):
        raise HTTPException(401, 'Invalid credentials')
    seed_debates(db)
    return {'token': make_token(u.id), 'user': {'id': u.id, 'name': u.name, 'email': u.email}}

@app.get('/auth/me')
def me(creds: HTTPAuthorizationCredentials = Depends(HTTPBearer()), db: Session = Depends(get_db)):
    u = get_user(creds, db)
    return {'id': u.id, 'name': u.name, 'email': u.email, 'gender': u.gender, 'country': u.country}

@app.get('/debates')
def get_debates(db: Session = Depends(get_db)):
    seed_debates(db)
    debates = db.query(Debate).all()
    result = []
    for d in debates:
        opts = db.query(DebateOption).filter(DebateOption.debate_id == d.id).order_by(DebateOption.order_num).all()
        votes = db.query(AnonVote).filter(AnonVote.debate_id == d.id).count()
        result.append({
            'id': d.id,
            'title': d.title,
            'description': d.description,
            'institution': d.institution,
            'inst_type': d.inst_type,
            'status': d.status,
            'votes': votes,
            'options': [{'id': o.id, 'text': o.text} for o in opts]
        })
    return result

@app.get('/debates/{debate_id}')
def get_debate(debate_id: int, db: Session = Depends(get_db)):
    d = db.query(Debate).filter(Debate.id == debate_id).first()
    if not d:
        raise HTTPException(404, 'Debate not found')
    opts = db.query(DebateOption).filter(DebateOption.debate_id == d.id).order_by(DebateOption.order_num).all()
    votes = db.query(AnonVote).filter(AnonVote.debate_id == d.id).count()
    return {
        'id': d.id, 'title': d.title, 'description': d.description,
        'institution': d.institution, 'inst_type': d.inst_type,
        'status': d.status, 'votes': votes,
        'options': [{'id': o.id, 'text': o.text} for o in opts]
    }

@app.post('/vote')
def vote(data: VoteInput, creds: HTTPAuthorizationCredentials = Depends(HTTPBearer()), db: Session = Depends(get_db)):
    u = get_user(creds, db)
    d = db.query(Debate).filter(Debate.id == data.debate_id).first()
    if not d:
        raise HTTPException(404, 'Debate not found')
    if d.status != 'live':
        raise HTTPException(400, 'Debate is not active')
    already = db.query(HasVoted).filter(HasVoted.user_id == u.id, HasVoted.debate_id == data.debate_id).first()
    if already:
        raise HTTPException(400, 'Already voted in this debate')
    vote_str = str(data.debate_id) + data.option_text + str(u.id) + str(random.random())
    vote_hash = hashlib.sha256(vote_str.encode()).hexdigest()
    h = vote_hash[:12].upper()
    vcode = h[0:4] + '-' + h[4:8] + '-' + h[8:12]
    av = AnonVote(debate_id=data.debate_id, vote_hash=vote_hash, vcode=vcode, gender=u.gender, county=u.county, option_text=data.option_text)
    db.add(av)
    db.add(HasVoted(user_id=u.id, debate_id=data.debate_id))
    db.commit()
    voter_id = u.id
    voter_id = None
    del voter_id
    return {'vcode': vcode, 'vote_hash': vote_hash, 'message': 'Vote recorded. Bridge destroyed.'}

@app.get('/results/{debate_id}')
def results(debate_id: int, db: Session = Depends(get_db)):
    d = db.query(Debate).filter(Debate.id == debate_id).first()
    if not d:
        raise HTTPException(404, 'Debate not found')
    opts = db.query(DebateOption).filter(DebateOption.debate_id == debate_id).order_by(DebateOption.order_num).all()
    results = []
    total = 0
    for o in opts:
        count = db.query(AnonVote).filter(AnonVote.debate_id == debate_id, AnonVote.option_text == o.text).count()
        total += count
        results.append({'option': o.text, 'votes': count})
    for r in results:
        r['pct'] = round(r['votes'] / total * 100, 1) if total > 0 else 0
    return {'debate_id': debate_id, 'title': d.title, 'institution': d.institution, 'total_votes': total, 'results': results}

@app.get('/verify/{vcode}')
def verify(vcode: str, db: Session = Depends(get_db)):
    av = db.query(AnonVote).filter(AnonVote.vcode == vcode.upper()).first()
    if not av:
        raise HTTPException(404, 'Code not found')
    d = db.query(Debate).filter(Debate.id == av.debate_id).first()
    opts = db.query(DebateOption).filter(DebateOption.debate_id == av.debate_id).order_by(DebateOption.order_num).all()
    return {
        'vcode': av.vcode,
        'vote_hash': av.vote_hash,
        'debate': d.title if d else '',
        'institution': d.institution if d else '',
        'options': [o.text for o in opts],
        'your_vote': av.option_text,
        'verified': True
    }
