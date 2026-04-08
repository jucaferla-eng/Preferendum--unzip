from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from typing import List
from datetime import datetime
import os, jwt, bcrypt, hashlib, json

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
    country = Column(String, default='CL')
    county = Column(String, default='')
    gender = Column(String, default='F')

class Debate(Base):
    __tablename__ = 'debates'
    id = Column(Integer, primary_key=True)
    title = Column(String)
    description = Column(String, default='')
    institution = Column(String)
    inst_type = Column(String, default='gov')
    category = Column(String, default='general')
    country = Column(String, default='CL')
    county = Column(String, default='')
    options_json = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(String, default='')

class Vote(Base):
    __tablename__ = 'votes'
    id = Column(Integer, primary_key=True)
    debate_id = Column(Integer)
    option_text = Column(String)
    vote_hash = Column(String)
    vcode = Column(String, unique=True)
    created_at = Column(String, default='')

class HasVoted(Base):
    __tablename__ = 'has_voted'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    debate_id = Column(Integer)

Base.metadata.create_all(bind=engine)

app = FastAPI(title='Preferendum API', version='2.1.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
SECRET = os.getenv('JWT_SECRET', 'preferendum-production-secret-2026')

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def make_token(uid):
    return jwt.encode({'sub': str(uid)}, SECRET, algorithm='HS256')

def get_user(creds: HTTPAuthorizationCredentials = Depends(HTTPBearer()), db: Session = Depends(get_db)):
    try:
        pay = jwt.decode(creds.credentials, SECRET, algorithms=['HS256'])
        u = db.query(User).filter(User.id == int(pay['sub'])).first()
        if not u:
            raise HTTPException(404, 'User not found')
        return u
    except:
        raise HTTPException(401, 'Invalid token')

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

class DebateCreate(BaseModel):
    title: str
    description: str = ''
    institution: str
    inst_type: str = 'gov'
    category: str = 'general'
    country: str = 'CL'
    county: str = ''
    options: List[str]

@app.get('/')
def root():
    return {'system': 'Preferendum', 'version': '2.1.0', 'status': 'running', 'dedication': 'En memoria de Jose Ignacio Fernandez (1989-2024)'}

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
    return {'token': make_token(u.id), 'user': {'id': u.id, 'name': u.name, 'email': u.email, 'gender': u.gender}}

@app.post('/auth/login')
def login(data: Log, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.email == data.email).first()
    if not u or not bcrypt.checkpw(data.password.encode(), u.password.encode()):
        raise HTTPException(401, 'Invalid credentials')
    return {'token': make_token(u.id), 'user': {'id': u.id, 'name': u.name, 'email': u.email, 'gender': u.gender}}

@app.get('/auth/me')
def me(u: User = Depends(get_user)):
    return {'id': u.id, 'name': u.name, 'email': u.email, 'gender': u.gender, 'county': u.county}

@app.get('/debates')
def get_debates(db: Session = Depends(get_db)):
    debates = db.query(Debate).filter(Debate.is_active == True).all()
    result = []
    for d in debates:
        opts = json.loads(d.options_json) if d.options_json else []
        votes = db.query(Vote).filter(Vote.debate_id == d.id).count()
        result.append({'id': d.id, 'title': d.title, 'description': d.description, 'institution': d.institution, 'inst_type': d.inst_type, 'category': d.category, 'options': [{'text': o} for o in opts], 'votes': votes})
    return result

@app.get('/debates/{debate_id}')
def get_debate(debate_id: int, db: Session = Depends(get_db)):
    d = db.query(Debate).filter(Debate.id == debate_id).first()
    if not d:
        raise HTTPException(404, 'Debate not found')
    opts = json.loads(d.options_json) if d.options_json else []
    votes = db.query(Vote).filter(Vote.debate_id == d.id).count()
    return {'id': d.id, 'title': d.title, 'description': d.description, 'institution': d.institution, 'inst_type': d.inst_type, 'options': [{'text': o} for o in opts], 'votes': votes}

@app.post('/debates/create')
def create_debate(data: DebateCreate, db: Session = Depends(get_db)):
    if len(data.options) < 2:
        raise HTTPException(400, 'Minimum 2 options required')
    d = Debate(title=data.title, description=data.description, institution=data.institution, inst_type=data.inst_type, category=data.category, country=data.country, county=data.county, options_json=json.dumps(data.options), is_active=True, created_at=str(datetime.utcnow()))
    db.add(d)
    db.commit()
    db.refresh(d)
    return {'id': d.id, 'title': d.title, 'institution': d.institution, 'options': data.options, 'message': 'Debate created successfully'}

@app.post('/vote')
def vote(data: VoteInput, u: User = Depends(get_user), db: Session = Depends(get_db)):
    already = db.query(HasVoted).filter(HasVoted.user_id == u.id, HasVoted.debate_id == data.debate_id).first()
    if already:
        raise HTTPException(400, 'Already voted in this debate')
    d = db.query(Debate).filter(Debate.id == data.debate_id).first()
    if not d:
        raise HTTPException(404, 'Debate not found')
    opts = json.loads(d.options_json) if d.options_json else []
    if data.option_text not in opts:
        raise HTTPException(400, 'Invalid option')
    raw = f'{data.debate_id}:{data.option_text}:{u.id}:{datetime.utcnow().isoformat()}'
    vote_hash = hashlib.sha256(raw.encode()).hexdigest()
    vcode_raw = vote_hash[:12].upper()
    vcode = f'{vcode_raw[:4]}-{vcode_raw[4:8]}-{vcode_raw[8:12]}'
    v = Vote(debate_id=data.debate_id, option_text=data.option_text, vote_hash=vote_hash, vcode=vcode, created_at=str(datetime.utcnow()))
    db.add(v)
    hv = HasVoted(user_id=u.id, debate_id=data.debate_id)
    db.add(hv)
    voter_id = u.id
    del voter_id
    db.commit()
    return {'message': 'Vote registered', 'vcode': vcode, 'vote_hash': vote_hash}

@app.get('/results/{debate_id}')
def results(debate_id: int, db: Session = Depends(get_db)):
    d = db.query(Debate).filter(Debate.id == debate_id).first()
    if not d:
        raise HTTPException(404, 'Debate not found')
    opts = json.loads(d.options_json) if d.options_json else []
    total = db.query(Vote).filter(Vote.debate_id == debate_id).count()
    result = []
    for opt in opts:
        count = db.query(Vote).filter(Vote.debate_id == debate_id, Vote.option_text == opt).count()
        pct = round(count / total * 100, 1) if total > 0 else 0
        result.append({'option': opt, 'votes': count, 'pct': pct})
    return {'debate_id': debate_id, 'total_votes': total, 'results': result}

@app.get('/verify/{vcode}')
def verify(vcode: str, db: Session = Depends(get_db)):
    v = db.query(Vote).filter(Vote.vcode == vcode.upper()).first()
    if not v:
        raise HTTPException(404, 'Vote not found')
    d = db.query(Debate).filter(Debate.id == v.debate_id).first()
    opts = json.loads(d.options_json) if d and d.options_json else []
    return {'verified': True, 'debate': d.title if d else '', 'institution': d.institution if d else '', 'your_vote': v.option_text, 'options': opts, 'vote_hash': v.vote_hash}

@app.post('/seed')
def seed(db: Session = Depends(get_db)):
    existing = db.query(Debate).count()
    if existing > 0:
        return {'message': f'Already have {existing} debates - skipping seed'}
    debates_data = [
        {'title': 'Plan de inversion presupuesto Las Condes 2027', 'description': 'La Municipalidad de Las Condes necesita definir las prioridades de inversion para el presupuesto 2027. Como vecino, tu voz es decisiva.', 'institution': 'Municipalidad Las Condes', 'inst_type': 'gov', 'options': ['Infraestructura vial', 'Salud publica', 'Educacion', 'Areas verdes']},
        {'title': 'Plan de movilidad urbana Santiago 2027', 'description': 'Para reducir la congestion y mejorar la calidad de vida necesitamos decidir la prioridad en transporte publico.', 'institution': 'Municipalidad Santiago', 'inst_type': 'gov', 'options': ['Metro ampliado', 'Ciclovias', 'Buses electricos', 'Autopistas']},
        {'title': 'Cual zapatilla Nike quieres para 2026?', 'description': 'Nike Chile quiere saber cual modelo prefieres para la coleccion 2026. Tu voto define lo que producimos.', 'institution': 'Nike Chile', 'inst_type': 'corp', 'options': ['Air Max Pulse', 'Pegasus Trail', 'Air Force 1', 'React Infinity']},
    ]
    for dd in debates_data:
        d = Debate(title=dd['title'], description=dd['description'], institution=dd['institution'], inst_type=dd['inst_type'], options_json=json.dumps(dd['options']), is_active=True, created_at=str(datetime.utcnow()))
        db.add(d)
    db.commit()
    return {'message': f'Seeded {len(debates_data)} debates successfully'}
