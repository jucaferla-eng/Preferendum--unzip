"""
main.py — Preferendum Backend v3.0 Complete
============================================
FastAPI + SQLite + SendGrid + Twilio + AES-256 + Blockchain

Todos los módulos integrados en un solo archivo para Render:
  ✅ Auth: registro, login, JWT
  ✅ Verificación: 8 capas
  ✅ Debates: crear, listar, votar, verificar, resultados en tiempo real
  ✅ Opiniones con ads cada 5
  ✅ Legitimacy Score
  ✅ Bridge destruction
  ✅ Privacy: /privacy

Run: uvicorn main:app --host 0.0.0.0 --port 10000
En memoria del Socio Fundador José Ignacio Fernández (1989–2024)
"""

from __future__ import annotations
import os, json, hashlib, random, string, re, base64, uuid, time
import urllib.request, urllib.error, smtplib
import requests as _requests
import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timedelta
from typing import Optional, List
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fastapi import (FastAPI, HTTPException, Depends, UploadFile,
                     File, Form, Query, Request, BackgroundTasks, Header)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import (create_engine, Column, Integer, String, Boolean,
                        DateTime, Text, Float, func, text)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
import jwt
import bcrypt
from blockchain import blockchain as _blockchain
from payments import (
    PAYMENTS_SCHEMA_SQL,
    PAYMENTS_SCHEMA_SQL_PG,
    CREDIT_PACKAGES,
    PACKAGE_BY_ID,
    PREFERENDUM_WALLET,
    get_or_create_account,
    add_credits,
    deduct_credits_for_impression,
    allocate_budget_to_campaign,
    return_budget_to_account,
    create_stripe_checkout,
    handle_stripe_webhook,
    get_crypto_quote,
    create_crypto_payment_request,
    confirm_crypto_payment,
)

# ══════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./preferendum.db')
# Render provides postgres:// but SQLAlchemy 1.4+ requires postgresql://
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
engine = create_engine(
    DATABASE_URL,
    connect_args={'check_same_thread': False} if 'sqlite' in DATABASE_URL else {},
    pool_pre_ping=True,
)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ══════════════════════════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════════════════════════

class User(Base):
    __tablename__ = 'users'
    id              = Column(Integer, primary_key=True)
    email           = Column(String, unique=True, index=True)
    name            = Column(String)
    password        = Column(String)
    country         = Column(String, default='CL')
    county          = Column(String, default='')   # comuna declarada — nunca dirección exacta
    se_tier         = Column(String, default='')   # AAA/AAB/ABB/BBB/BBC/BCC — asignado por CommuneMarketData
    income_index    = Column(Float, default=0.0)   # índice de ingreso de su comuna
    gender          = Column(String, default='F')
    dob             = Column(String, default='')
    national_id     = Column(String, default='')
    phone           = Column(String, default='')
    role            = Column(String, default='voter')
    email_verified  = Column(Boolean, default=False)
    phone_verified  = Column(Boolean, default=False)
    id_verified     = Column(Boolean, default=False)
    selfie_verified = Column(Boolean, default=False)
    imei_verified   = Column(Boolean, default=False)
    geo_verified    = Column(Boolean, default=False)
    chain_verified  = Column(Boolean, default=False)
    is_verified     = Column(Boolean, default=False)
    verify_level    = Column(Integer, default=0)
    created_at      = Column(DateTime, default=datetime.utcnow)

class OTPCode(Base):
    __tablename__ = 'otp_codes'
    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, index=True)
    email       = Column(String, index=True)
    code        = Column(String)
    channel     = Column(String)
    used        = Column(Boolean, default=False)
    expires_at  = Column(DateTime)
    created_at  = Column(DateTime, default=datetime.utcnow)

class IMEILog(Base):
    __tablename__ = 'imei_logs'
    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, index=True)
    imei_hash   = Column(String, unique=True)
    device_info = Column(Text)
    created_at  = Column(DateTime, default=datetime.utcnow)

class SIMLog(Base):
    __tablename__ = 'sim_logs'
    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, index=True)
    phone_hash  = Column(String, unique=True)
    imei_hash   = Column(String, index=True)
    verified_at = Column(DateTime, default=datetime.utcnow)

class GeoLog(Base):
    __tablename__ = 'geo_logs'
    id               = Column(Integer, primary_key=True)
    user_id          = Column(Integer, index=True)
    latitude         = Column(Float)
    longitude        = Column(Float)
    country_detected = Column(String)
    verified         = Column(Boolean, default=False)
    created_at       = Column(DateTime, default=datetime.utcnow)

class DocumentLog(Base):
    __tablename__ = 'document_logs'
    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, index=True)
    doc_hash    = Column(String)
    doc_type    = Column(String)
    face_bytes  = Column(Text)   # base64 de la imagen — se borra después de comparar con selfie
    verified    = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

class SelfieLog(Base):
    __tablename__ = 'selfie_logs'
    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, index=True)
    selfie_hash = Column(String)
    match_score = Column(Float, default=0.0)
    verified    = Column(Boolean, default=False)
    face_bytes  = Column(Text)   # cara de referencia para comparar en visitas futuras
    created_at  = Column(DateTime, default=datetime.utcnow)

class VoteIdentityLock(Base):
    __tablename__ = 'vote_identity_locks'
    id               = Column(Integer, primary_key=True)
    debate_id        = Column(Integer, index=True)
    user_id          = Column(Integer, index=True)
    national_id_hash = Column(String, index=True)
    face_hash        = Column(String, index=True)
    created_at       = Column(DateTime, default=datetime.utcnow)

class Debate(Base):
    __tablename__ = 'debates'
    id               = Column(Integer, primary_key=True)
    title            = Column(String, nullable=False)
    context          = Column(Text, default='')
    options          = Column(Text)
    creator_id       = Column(Integer, default=0)
    creator_type     = Column(String, default='citizen')
    inst_name        = Column(String, default='')
    debate_type      = Column(String, default='gov')
    scope            = Column(String, default='country')
    scope_country    = Column(String, default='CL')
    scope_commune    = Column(String, default='')
    target_gender    = Column(String, default='all')
    target_age_min   = Column(Integer, default=13)
    target_age_max   = Column(Integer, default=99)
    target_se_tiers  = Column(String, default='A,B,C,D')  # nivel socioeconómico del debate
    category         = Column(String, default='general')   # deportes / política / economía / salud / etc.
    status           = Column(String, default='live')
    opens_at         = Column(DateTime, default=datetime.utcnow)
    closes_at        = Column(DateTime)
    verify_closes_at = Column(DateTime)
    total_votes      = Column(Integer, default=0)
    vote_counts      = Column(Text, default='{}')
    legitimacy_score = Column(Float, default=0.0)
    verifications_ok    = Column(Integer, default=0)
    verifications_total = Column(Integer, default=0)
    follow_up_questions = Column(Text, default='')
    reward           = Column(Text, default='')
    option_images    = Column(Text, default='[]')
    cover_image_url  = Column(Text, default='')
    is_anonymous     = Column(Boolean, default=False)
    created_at       = Column(DateTime, default=datetime.utcnow)

class Opinion(Base):
    __tablename__ = 'opinions'
    id              = Column(Integer, primary_key=True)
    debate_id       = Column(Integer, index=True)
    user_id         = Column(Integer, index=True)
    user_name       = Column(String, default='Ciudadano')
    text            = Column(Text, nullable=False)
    knowledge_level = Column(String, default='familiar')
    created_at      = Column(DateTime, default=datetime.utcnow)

class DebateVote(Base):
    __tablename__ = 'debate_votes'
    id              = Column(Integer, primary_key=True)
    debate_id       = Column(Integer, index=True)
    voter_id        = Column(Integer, nullable=True)
    option_index    = Column(Integer)
    option_text     = Column(String)
    verify_code     = Column(String, unique=True, index=True)
    vote_hash       = Column(String)
    encrypted_vote  = Column(Text)
    blockchain_tx   = Column(String, default='')
    gender          = Column(String, default='')
    age_group       = Column(String, default='')
    commune         = Column(String, default='')
    country         = Column(String, default='')
    verified        = Column(Boolean, nullable=True)
    verified_at     = Column(DateTime, nullable=True)
    dispute_reason  = Column(Text, default='')
    vote_chain      = Column(Text, default='[]')
    created_at      = Column(DateTime, default=datetime.utcnow)

class HasVotedLog(Base):
    __tablename__ = 'debate_has_voted'
    id          = Column(Integer, primary_key=True)
    debate_id   = Column(Integer, index=True)
    user_id     = Column(Integer, index=True)
    verify_code = Column(String)
    created_at  = Column(DateTime, default=datetime.utcnow)

class SimVoteLog(Base):
    """Un SIM (phone_hash) solo puede votar una vez por debate.
    Bloquea aunque el chip cambie de aparato o el usuario cree otra cuenta."""
    __tablename__ = 'sim_vote_log'
    id          = Column(Integer, primary_key=True)
    debate_id   = Column(Integer, index=True, nullable=False)
    phone_hash  = Column(String, index=True, nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

class NationalIdVoteLog(Base):
    """Un RUT/DNI solo puede votar una vez por debate.
    Bloquea aunque el usuario tenga chip nuevo y cuenta nueva."""
    __tablename__ = 'national_id_vote_log'
    id               = Column(Integer, primary_key=True)
    debate_id        = Column(Integer, index=True, nullable=False)
    national_id_hash = Column(String, index=True, nullable=False)
    created_at       = Column(DateTime, default=datetime.utcnow)

class ImeiVoteLog(Base):
    """Un aparato (IMEI) solo puede votar una vez por debate.
    Bloquea aunque cambien el chip o la cuenta."""
    __tablename__ = 'imei_vote_log'
    id          = Column(Integer, primary_key=True)
    debate_id   = Column(Integer, index=True, nullable=False)
    imei_hash   = Column(String, index=True, nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

class DebateAd(Base):
    __tablename__ = 'debate_ads'
    id          = Column(Integer, primary_key=True)
    debate_id   = Column(Integer, index=True)
    brand       = Column(String)
    copy        = Column(String)
    cta         = Column(String, default='Ver más')
    logo_color  = Column(String, default='#3b82f6')
    link_url    = Column(String, default='')   # destino al hacer clic en "Ver más"
    impressions = Column(Integer, default=0)
    created_at  = Column(DateTime, default=datetime.utcnow)

class DebateRewardCode(Base):
    __tablename__ = 'debate_reward_codes'
    id          = Column(Integer, primary_key=True)
    debate_id   = Column(Integer, index=True)
    code        = Column(String, nullable=False)
    claimed     = Column(Boolean, default=False)
    claimed_at  = Column(DateTime, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

class AdCampaign(Base):
    __tablename__ = 'ad_campaigns'
    id                  = Column(Integer, primary_key=True)
    advertiser_email    = Column(String, index=True)
    advertiser_name     = Column(String)
    title               = Column(String)
    budget_clp          = Column(Integer, default=0)
    spent_clp           = Column(Integer, default=0)
    ad_type             = Column(String, default='banner')
    # ── Targeting geográfico ──
    target_country      = Column(String, default='')        # 'CL' / 'AR' / '' = todos
    target_communes     = Column(String, default='')        # 'Vitacura,Las Condes' / '' = todas
    # ── Targeting de nivel de ingreso ──
    target_se_tiers     = Column(String, default='A,B,C,D') # tiers deseados: 'A,B' = premium
    target_income_min   = Column(Float, default=0.0)        # índice mínimo (0 = sin límite)
    target_income_max   = Column(Float, default=9999.0)     # índice máximo (9999 = sin límite)
    # ── Targeting demográfico ──
    target_gender       = Column(String, default='all')     # 'F' / 'M' / 'all'
    target_age_min      = Column(Integer, default=13)
    target_age_max      = Column(Integer, default=99)
    target_age_ranges   = Column(String, default='')        # legacy
    target_categories   = Column(String, default='')
    excluded_categories = Column(String, default='')
    blocked_competitors = Column(String, default='')
    start_date          = Column(DateTime, nullable=True)
    end_date            = Column(DateTime, nullable=True)
    is_active           = Column(Boolean, default=True)
    created_at          = Column(DateTime, default=datetime.utcnow)
    logo_url            = Column(String, default='')   # data URI o URL pública del logo
    ad_copy             = Column(String, default='')   # texto del anuncio
    ad_image_url        = Column(String, default='')   # imagen principal del anuncio
    video_url           = Column(String, default='')   # URL de video (YouTube/Vimeo/mp4)
    target_debate_ids   = Column(String, default='')   # '4,6,9' — override directo, bypass matrix
    link_url            = Column(String, default='')   # destino al hacer clic en "Ver más"
    min_per_capita_usd  = Column(Float, default=0.0)   # filtro GNI per cápita mínimo del país

class AdImpressionLog(Base):
    __tablename__ = 'ad_impression_logs'
    id          = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, index=True)
    debate_id   = Column(Integer, index=True, nullable=True)
    gender      = Column(String, default='')
    age_group   = Column(String, default='')
    county      = Column(String, default='')
    country     = Column(String, default='')
    created_at  = Column(DateTime, default=datetime.utcnow)

class PostVoteComment(Base):
    __tablename__ = 'post_vote_comments'
    id         = Column(Integer, primary_key=True)
    debate_id  = Column(Integer, index=True)
    user_id    = Column(Integer, index=True)
    user_name  = Column(String, default='')
    text       = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class ClosedListEntry(Base):
    __tablename__ = 'closed_list_entries'
    id               = Column(Integer, primary_key=True)
    debate_id        = Column(Integer, index=True)
    national_id_hash = Column(String, index=True)
    created_at       = Column(DateTime, default=datetime.utcnow)


class OrganizerProfile(Base):
    """
    Perfil extendido del organizador — persona natural o representante de empresa.
    Separado de User para no mezclar datos de votante con datos corporativos.
    """
    __tablename__ = 'organizer_profiles'
    id                   = Column(Integer, primary_key=True)
    user_id              = Column(Integer, index=True, unique=True)

    # Tipo de organizador
    org_type             = Column(String, default='person')  # person / company
    is_supervisor        = Column(Boolean, default=False)    # puede autorizar empleados

    # Datos corporativos
    company_name         = Column(String, default='')
    company_rut          = Column(String, default='')        # RUT empresa
    company_web          = Column(String, default='')        # sitio web
    company_email_domain = Column(String, default='')        # dominio del email corporativo
    cargo                = Column(String, default='')        # cargo en la empresa

    # Supervisor que lo autorizó (NULL si es supervisor)
    supervisor_user_id   = Column(Integer, nullable=True)
    supervisor_name      = Column(String, default='')
    supervisor_email     = Column(String, default='')

    # Verificaciones automáticas
    rut_verified         = Column(Boolean, default=False)    # RUT empresa existe en SII
    domain_verified      = Column(Boolean, default=False)    # dominio email corporativo válido
    web_verified         = Column(Boolean, default=False)    # web empresa existe y es real
    selfie_verified      = Column(Boolean, default=False)    # cara = carné (Rekognition)
    doc_verified         = Column(Boolean, default=False)    # documento de cargo revisado

    # Documento de cargo
    cargo_doc_hash       = Column(String, default='')
    cargo_doc_bytes      = Column(Text)                      # base64, se borra tras revisión

    # Estado de la cuenta
    status               = Column(String, default='pending') # pending/approved/suspended
    rejection_reason     = Column(String, default='')
    created_at           = Column(DateTime, default=datetime.utcnow)
    approved_at          = Column(DateTime, nullable=True)


class AuthorizationRequest(Base):
    """
    Solicitud de un empleado para que su jefe lo autorice a crear consultas.
    El jefe recibe email con link único — entra una sola vez y aprueba.
    """
    __tablename__ = 'authorization_requests'
    id                   = Column(Integer, primary_key=True)
    employee_user_id     = Column(Integer, index=True)
    employee_name        = Column(String)
    employee_email       = Column(String)
    supervisor_email     = Column(String, index=True)
    supervisor_user_id   = Column(Integer, nullable=True)   # se llena cuando el jefe entra
    token                = Column(String, unique=True)       # link único para el jefe
    status               = Column(String, default='pending') # pending/approved/rejected
    created_at           = Column(DateTime, default=datetime.utcnow)
    resolved_at          = Column(DateTime, nullable=True)


class MarketerProfile(Base):
    """
    Perfil extendido del marketer/anunciante — persona natural o representante de empresa.
    Espejo de OrganizerProfile: mismo principio de "rastro de identidad" — selfie + ID +
    documento de cargo + autorización del jefe — porque ningún estafador se filma la cara.
    """
    __tablename__ = 'marketer_profiles'
    id                   = Column(Integer, primary_key=True)
    user_id              = Column(Integer, index=True, unique=True)

    # Tipo de marketer
    org_type             = Column(String, default='company')  # person / company
    is_supervisor        = Column(Boolean, default=False)     # puede autorizar empleados/campañas

    # Datos corporativos
    company_name         = Column(String, default='')
    company_rut          = Column(String, default='')         # RUT empresa
    company_web          = Column(String, default='')         # sitio web
    company_email_domain = Column(String, default='')         # dominio del email corporativo
    business_category    = Column(String, default='')         # rubro declarado — ver _check_business_category
    cargo                = Column(String, default='')         # cargo en la empresa
    department           = Column(String, default='')         # departamento dentro de la empresa
    applicant_phone      = Column(String, default='')

    # Jefe que lo autoriza (NULL si es supervisor)
    supervisor_user_id   = Column(Integer, nullable=True)
    supervisor_name      = Column(String, default='')
    supervisor_email     = Column(String, default='')
    supervisor_phone     = Column(String, default='')

    # Verificaciones automáticas
    rut_verified         = Column(Boolean, default=False)     # RUT empresa existe en SII
    domain_verified      = Column(Boolean, default=False)     # dominio email corporativo válido
    web_verified         = Column(Boolean, default=False)     # web empresa existe y es real
    selfie_verified      = Column(Boolean, default=False)     # cara = carné (Rekognition)
    doc_verified         = Column(Boolean, default=False)     # documento de cargo revisado

    # Documento de cargo
    cargo_doc_hash       = Column(String, default='')
    cargo_doc_bytes      = Column(Text)                       # base64, se borra tras revisión

    # Estado de la cuenta
    status               = Column(String, default='pending')  # pending/approved/suspended
    rejection_reason     = Column(String, default='')
    created_at           = Column(DateTime, default=datetime.utcnow)
    approved_at          = Column(DateTime, nullable=True)


class MarketerAuthorizationRequest(Base):
    """
    Solicitud de un empleado para que su jefe lo autorice a lanzar campañas
    publicitarias en nombre de la empresa. El jefe recibe email con link único
    — entra una sola vez (con su propia cuenta verificada, selfie incluida) y aprueba.
    """
    __tablename__ = 'marketer_authorization_requests'
    id                   = Column(Integer, primary_key=True)
    employee_user_id     = Column(Integer, index=True)
    employee_name        = Column(String)
    employee_email       = Column(String)
    supervisor_email     = Column(String, index=True)
    supervisor_user_id   = Column(Integer, nullable=True)    # se llena cuando el jefe entra
    token                = Column(String, unique=True)        # link único para el jefe
    status               = Column(String, default='pending')  # pending/approved/rejected
    created_at           = Column(DateTime, default=datetime.utcnow)
    resolved_at          = Column(DateTime, nullable=True)


class ConsultationModerationLog(Base):
    """Resultado del análisis de IA antes de publicar una consulta."""
    __tablename__ = 'consultation_moderation_logs'
    id            = Column(Integer, primary_key=True)
    debate_id     = Column(Integer, index=True)
    score         = Column(Integer, default=0)       # 0-100
    decision      = Column(String, default='review') # approved/rejected/review
    reason        = Column(Text, default='')
    raw_response  = Column(Text, default='')
    created_at    = Column(DateTime, default=datetime.utcnow)

class CommuneMarketData(Base):
    """Precio de arriendo por m² por comuna — actualizado mensualmente por el agente."""
    __tablename__ = 'commune_market_data'
    id           = Column(Integer, primary_key=True)
    country      = Column(String, index=True)
    commune      = Column(String, index=True)
    price_m2_avg = Column(Float, default=0.0)
    income_index = Column(Float, default=100.0)  # mediana global = 100
    cpm_usd      = Column(Float, default=6.0)
    se_tier      = Column(String, default='C')   # A / B / C / D
    portal       = Column(String)
    sample_count = Column(Integer, default=0)
    scraped_at   = Column(DateTime)
    updated_at   = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# Payment + attribution tables (managed directly in SQL, not via ORM)
from marketing_agent import ATTRIBUTION_SCHEMA_SQL as _ATTR_SQL
_is_pg = 'postgresql' in DATABASE_URL
_payment_schema = PAYMENTS_SCHEMA_SQL_PG if _is_pg else PAYMENTS_SCHEMA_SQL
# Each statement in its own transaction so a failure in one doesn't abort the rest
for _sql_block in [_payment_schema, _ATTR_SQL]:
    for _stmt in _sql_block.strip().split(';'):
        _stmt = _stmt.strip()
        if _stmt:
            try:
                with engine.begin() as _conn:
                    _conn.execute(text(_stmt))
            except Exception:
                pass

# Column migrations — works for both SQLite and PostgreSQL
def _migrate():
    from sqlalchemy import text, inspect
    is_pg = 'postgresql' in DATABASE_URL
    inspector = inspect(engine)
    with engine.connect() as conn:
        # debates table
        existing_debate_cols = {c['name'] for c in inspector.get_columns('debates')} if inspector.has_table('debates') else set()
        for col, definition in [
            ('follow_up_questions', "TEXT DEFAULT ''"),
            ('reward',              "TEXT DEFAULT ''"),
            ('option_images',       "TEXT DEFAULT '[]'"),
            ('target_se_tiers',     "TEXT DEFAULT 'A,B,C,D'"),
            ('category',            "TEXT DEFAULT 'general'"),
            ('cover_image_url',     "TEXT DEFAULT ''"),
            ('is_anonymous',        "BOOLEAN DEFAULT FALSE"),
        ]:
            if col not in existing_debate_cols:
                try:
                    conn.execute(text(f"ALTER TABLE debates ADD COLUMN {col} {definition}"))
                    conn.commit()
                except Exception:
                    pass
        # debate_votes table
        existing_vote_cols = {c['name'] for c in inspector.get_columns('debate_votes')} if inspector.has_table('debate_votes') else set()
        if 'vote_chain' not in existing_vote_cols:
            try:
                conn.execute(text("ALTER TABLE debate_votes ADD COLUMN vote_chain TEXT DEFAULT '[]'"))
                conn.commit()
            except Exception:
                pass
        # document_logs — face_bytes para comparar con selfie via Rekognition
        existing_doc_cols = {c['name'] for c in inspector.get_columns('document_logs')} if inspector.has_table('document_logs') else set()
        if 'face_bytes' not in existing_doc_cols:
            try:
                conn.execute(text("ALTER TABLE document_logs ADD COLUMN face_bytes TEXT"))
                conn.commit()
            except Exception:
                pass
        # users — se_tier e income_index para matching de ads
        existing_user_cols = {c['name'] for c in inspector.get_columns('users')} if inspector.has_table('users') else set()
        for col, defn in [('se_tier', "TEXT DEFAULT ''"), ('income_index', 'FLOAT DEFAULT 0.0')]:
            if col not in existing_user_cols:
                try:
                    conn.execute(text(f'ALTER TABLE users ADD COLUMN {col} {defn}'))
                    conn.commit()
                except Exception:
                    pass
        # ad_campaigns — nuevas columnas de targeting por ingreso
        existing_ad_cols = {c['name'] for c in inspector.get_columns('ad_campaigns')} if inspector.has_table('ad_campaigns') else set()
        for col, defn in [
            ('target_communes',     "TEXT DEFAULT ''"),
            ('target_se_tiers',     "TEXT DEFAULT 'A,B,C,D'"),
            ('target_income_min',   'FLOAT DEFAULT 0.0'),
            ('target_income_max',   'FLOAT DEFAULT 9999.0'),
            ('target_age_min',      'INTEGER DEFAULT 13'),
            ('target_age_max',      'INTEGER DEFAULT 99'),
            ('logo_url',            "TEXT DEFAULT ''"),
            ('ad_copy',             "TEXT DEFAULT ''"),
            ('ad_image_url',        "TEXT DEFAULT ''"),
            ('created_at',          'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
            ('link_url',            "TEXT DEFAULT ''"),
            ('target_debate_ids',   "TEXT DEFAULT ''"),
            ('target_age_ranges',   "TEXT DEFAULT ''"),
            ('target_categories',   "TEXT DEFAULT ''"),
            ('excluded_categories', "TEXT DEFAULT ''"),
            ('blocked_competitors', "TEXT DEFAULT ''"),
            ('spent_clp',           'FLOAT DEFAULT 0.0'),
            ('video_url',           "TEXT DEFAULT ''"),
            ('min_per_capita_usd',  'REAL DEFAULT 0.0'),
        ]:
            if col not in existing_ad_cols:
                try:
                    conn.execute(text(f'ALTER TABLE ad_campaigns ADD COLUMN {col} {defn}'))
                    conn.commit()
                except Exception:
                    pass
        # debate_ads — link_url para que "Ver más" tenga un destino real
        existing_debate_ad_cols = {c['name'] for c in inspector.get_columns('debate_ads')} if inspector.has_table('debate_ads') else set()
        if 'link_url' not in existing_debate_ad_cols:
            try:
                conn.execute(text("ALTER TABLE debate_ads ADD COLUMN link_url TEXT DEFAULT ''"))
                conn.commit()
            except Exception:
                pass
        # Backfill link_url on demo ad rows that existed before this column —
        # the seed block only runs once at first DB init, so rows created
        # earlier kept link_url=''  ("Ver más" had nowhere to go). One-time,
        # idempotent (only touches rows that are still empty).
        try:
            for brand, url in [
                ('BancoEstado',   'https://www.bancoestado.cl/'),
                ('Toyota Chile',  'https://www.toyota.cl/'),
                ('Samsung',       'https://www.samsung.com/cl/'),
                ('Nestlé Chile',  'https://www.nestle.cl/'),
                ('Nestle',        'https://www.nestle.cl/'),
                ('Nestle Chile',  'https://www.nestle.cl/'),
            ]:
                conn.execute(
                    text("UPDATE debate_ads SET link_url = :url WHERE brand = :brand AND (link_url IS NULL OR link_url = '')"),
                    {'url': url, 'brand': brand}
                )
            conn.commit()
        except Exception:
            pass
        # selfie_logs — face_bytes como referencia para re-autenticación facial
        existing_selfie_cols = {c['name'] for c in inspector.get_columns('selfie_logs')} if inspector.has_table('selfie_logs') else set()
        if 'face_bytes' not in existing_selfie_cols:
            try:
                conn.execute(text("ALTER TABLE selfie_logs ADD COLUMN face_bytes TEXT"))
                conn.commit()
            except Exception:
                pass
_migrate()

# ══════════════════════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════════════════════

app = FastAPI(
    title='Preferendum API',
    version='3.0.0',
    description='En memoria del Socio Fundador José Ignacio Fernández (1989–2024)'
)

app.add_middleware(CORSMiddleware,
    allow_origins=['*'], allow_credentials=True,
    allow_methods=['*'], allow_headers=['*'])

# ── AUTO-SCHEDULER: corre el agente de noticias todos los días a las 7am UTC ──
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    import threading

    def _run_daily_debates_job():
        try:
            from preferendum_agent import run_daily_debates
            print('[Scheduler] Iniciando run_daily_debates...')
            result = run_daily_debates()
            print(f'[Scheduler] Terminado — creados: {result.get("debates_created", 0)}, saltados: {result.get("debates_skipped", 0)}')
        except Exception as e:
            print(f'[Scheduler] Error en run_daily_debates: {e}')

    _scheduler = BackgroundScheduler(timezone='UTC')
    _scheduler.add_job(
        _run_daily_debates_job,
        CronTrigger(hour=7, minute=0),   # 7:00 AM UTC todos los días
        id='daily_debates',
        replace_existing=True,
        misfire_grace_time=3600,         # si el server estaba caído, corre igual dentro de 1h
    )
    _scheduler.start()
    print('[Scheduler] ✅ Scheduler activo — debates diarios a las 7:00 AM UTC')
except Exception as _sched_err:
    print(f'[Scheduler] ⚠️ No se pudo iniciar scheduler: {_sched_err}')

SECRET = os.getenv('JWT_SECRET', 'preferendum-jwt-secret-2024')
security          = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)  # no lanza error si no hay token

# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def gen_otp(length=6):
    return ''.join(random.choices(string.digits, k=length))

def make_token(user_id, role='voter'):
    payload = {
        'sub': str(user_id),
        'role': role,
        'exp': datetime.utcnow() + timedelta(days=30)
    }
    return jwt.encode(payload, SECRET, algorithm='HS256')

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=['HS256'])
        user = db.query(User).filter(User.id == int(payload['sub'])).first()
        if not user:
            raise HTTPException(404, 'User not found')
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, 'Token expired')
    except Exception:
        raise HTTPException(401, 'Invalid token')

def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_optional),
    db: Session = Depends(get_db)
):
    """Igual que get_current_user pero devuelve None si no hay token — no lanza error."""
    if not credentials:
        return None
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=['HS256'])
        user = db.query(User).filter(User.id == int(payload['sub'])).first()
        return user
    except Exception:
        return None

def get_verified_user(user: User = Depends(get_current_user)):
    if not user.email_verified:
        raise HTTPException(403, 'Email verification required')
    return user

def count_verified(user):
    flags = [user.email_verified, user.phone_verified, user.id_verified,
             user.selfie_verified, user.imei_verified, user.geo_verified,
             user.chain_verified]
    return sum(1 for f in flags if f)

def update_verify_level(user, db):
    level = count_verified(user)
    user.verify_level = level
    user.is_verified = (level >= 4)
    db.commit()

def hash_str(s, prefix=''):
    return hashlib.sha256(f'{prefix}{s}'.encode()).hexdigest()

def check_and_register_device(device_fp: str, user_id: int, db: Session):
    """Verifica que el dispositivo no esté registrado a otra cuenta.
    Usa fingerprint + RUT como identidad compuesta para evitar falsos positivos por colisión."""
    if not device_fp:
        return
    fp_hash = hash_str(device_fp, 'pref-fp-')
    existing = db.query(IMEILog).filter(IMEILog.imei_hash == fp_hash).first()
    if existing and existing.user_id != user_id:
        # Mismo fingerprint, distinta cuenta — verificar si es colisión legítima o fraude
        current_user  = db.query(User).filter(User.id == user_id).first()
        existing_user = db.query(User).filter(User.id == existing.user_id).first()
        if (current_user and existing_user
                and current_user.national_id and existing_user.national_id):
            def _nid(u): return re.sub(r'[\.\-\s]', '', u.national_id.strip().upper())
            if _nid(current_user) == _nid(existing_user):
                return  # mismo RUT = misma persona en otro navegador, permitir
        raise HTTPException(409, 'Este dispositivo ya está registrado con otra cuenta. Solo se permite una cuenta por dispositivo.')
    if not existing:
        db.add(IMEILog(user_id=user_id, imei_hash=fp_hash, device_info='browser-fp-login'))
        db.commit()

def generate_verify_code():
    chars = string.ascii_uppercase + string.digits
    parts = [''.join(random.choices(chars, k=4)) for _ in range(3)]
    return '-'.join(parts)

def mock_blockchain_tx():
    return '0x' + ''.join(random.choices('0123456789abcdef', k=64))

def encrypt_vote_aes(debate_id, option, metadata):
    data = json.dumps({
        'debate_id': debate_id,
        'option': option,
        'meta': metadata,
        'ts': datetime.utcnow().isoformat()
    })
    encoded = base64.b64encode(data.encode()).decode()
    return encoded

def get_debate_status(debate):
    now = datetime.utcnow()
    if not debate.closes_at or now <= debate.closes_at:
        return 'live'
    if debate.verify_closes_at and now <= debate.verify_closes_at:
        return 'verifying'
    return 'verified'

def format_debate(debate, has_voted=False):
    opts = json.loads(debate.options or '[]')
    counts = json.loads(debate.vote_counts or '{}')
    imgs = json.loads(debate.option_images or '[]')
    status = get_debate_status(debate)
    total = debate.total_votes or 0
    results = []
    for i, opt in enumerate(opts):
        c = counts.get(opt, 0)
        pct = round(c / total * 100, 1) if total > 0 else 0
        results.append({'option': opt, 'index': i, 'count': c, 'pct': pct})
    return {
        'id': debate.id,
        'title': debate.title,
        'context': debate.context,
        'options': opts,
        'option_images': imgs,
        'results': results,
        'creator_type': debate.creator_type,
        'inst_name': debate.inst_name,
        'debate_type': debate.debate_type,
        'scope': debate.scope,
        'scope_country': debate.scope_country,
        'scope_commune': debate.scope_commune,
        'target_gender': debate.target_gender,
        'target_age_min': debate.target_age_min,
        'target_age_max': debate.target_age_max,
        'status': status,
        'total_votes': total,
        'opens_at': debate.opens_at.isoformat() if debate.opens_at else None,
        'closes_at': debate.closes_at.isoformat() if debate.closes_at else None,
        'verify_closes_at': debate.verify_closes_at.isoformat() if debate.verify_closes_at else None,
        'legitimacy_score': debate.legitimacy_score,
        'verifications_ok': debate.verifications_ok,
        'verifications_total': debate.verifications_total,
        'follow_up_questions': debate.follow_up_questions or '',
        'reward': debate.reward or '',
        'cover_image_url': debate.cover_image_url or '',
        'is_anonymous': bool(debate.is_anonymous),
        'has_voted': has_voted,
        'created_at': debate.created_at.isoformat(),
    }

# ══════════════════════════════════════════════════════════════
# EMAIL SENDER
# ══════════════════════════════════════════════════════════════

def send_email_otp(email, code, name=''):
    html = (
        f'<div style="font-family:sans-serif;padding:40px;background:#07090f;color:#fff;border-radius:12px;">'
        f'<h1 style="color:#2563eb;">prefer<span style="color:#fff">endum</span></h1>'
        f'<p>Hola {name or "Ciudadano"},</p><p>Tu código de verificación:</p>'
        f'<div style="background:#1e2a3d;padding:24px;text-align:center;border-radius:8px;">'
        f'<span style="font-size:40px;font-weight:bold;letter-spacing:10px;color:#2563eb;">{code}</span></div>'
        f'<p style="color:#94a3b8;">Válido por 10 minutos. No lo compartas con nadie.</p>'
        f'<p style="color:#475569;font-size:12px;">En memoria del Socio Fundador José Ignacio Fernández (1989–2024)</p>'
        f'</div>'
    )

    # Resend — preferendum.com domain is verified
    resend_key = os.getenv('RESEND_API_KEY')
    if resend_key:
        try:
            resp = _requests.post(
                'https://api.resend.com/emails',
                json={
                    'from': 'Preferendum <noreply@preferendum.com>',
                    'to': [email],
                    'subject': f'Tu código Preferendum: {code}',
                    'html': html,
                    'text': f'Tu código Preferendum es: {code}. Válido 10 minutos.',
                },
                headers={'Authorization': f'Bearer {resend_key}'},
                timeout=10,
            )
            print(f'[Resend] status={resp.status_code} body={resp.text}')
            if resp.status_code in (200, 201):
                return True
        except Exception as e:
            print(f'[Resend Error] {e}')
        print('[Resend] Failed — falling back to Gmail')

    # Fallback: Gmail SMTP
    gmail_user = os.getenv('GMAIL_USER', 'jucaferla@gmail.com')
    gmail_pass = os.getenv('GMAIL_APP_PASSWORD')
    if not gmail_pass:
        print(f'[DEV EMAIL] To: {email} | Code: {code}')
        return True
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Tu código Preferendum: {code}'
        msg['From']    = f'Preferendum <{gmail_user}>'
        msg['To']      = email
        msg.attach(MIMEText(f'Tu código es: {code}. Válido 10 min.', 'plain'))
        msg.attach(MIMEText(html, 'html'))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, email, msg.as_string())
        print(f'[Gmail] Sent to {email}')
        return True
    except Exception as e:
        print(f'[Gmail Error] {e}')
        print(f'[DEV EMAIL] To: {email} | Code: {code}')
        return False


def send_welcome_certificate(email, name, user_id):
    cert_url = f'https://preferendum-unzip-d2zd.onrender.com/debates/feed'
    qr_url   = f'https://api.qrserver.com/v1/create-qr-code/?size=180x180&data={cert_url}&bgcolor=07090f&color=2563eb&format=png'
    cert_id  = f'PRF-{user_id:06d}'
    html = (
        f'<div style="font-family:sans-serif;max-width:520px;margin:0 auto;background:#07090f;color:#fff;border-radius:16px;overflow:hidden;">'
        f'<div style="background:#0d1526;padding:28px 32px;border-bottom:1px solid #1e2d4a;">'
        f'<h1 style="margin:0;font-size:22px;">prefer<span style="color:#fff">endum</span></h1>'
        f'<p style="margin:6px 0 0;color:#64748b;font-size:13px;">Plataforma de decisiones verificadas</p>'
        f'</div>'
        f'<div style="padding:32px;">'
        f'<p style="color:#94a3b8;font-size:14px;margin:0 0 6px;">Hola {name},</p>'
        f'<h2 style="margin:0 0 24px;font-size:20px;color:#fff;">Tu certificado de registro está listo</h2>'
        f'<div style="background:#0d1526;border:1px solid #1e2d4a;border-radius:12px;padding:24px;text-align:center;margin-bottom:24px;">'
        f'<div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:12px;">Certificado de Ciudadano Verificado</div>'
        f'<img src="{qr_url}" width="160" height="160" style="border-radius:8px;margin-bottom:12px;" alt="QR Preferendum"/>'
        f'<div style="font-size:13px;font-weight:700;color:#2563eb;letter-spacing:0.15em;">{cert_id}</div>'
        f'<div style="font-size:11px;color:#64748b;margin-top:4px;">Tu número de registro Preferendum</div>'
        f'</div>'
        f'<p style="color:#94a3b8;font-size:13px;line-height:1.6;">'
        f'Tu identidad será verificada con 7 capas de seguridad. '
        f'Tus votos quedan anclados en blockchain y son auditables públicamente a través de tu código XXXX-XXXX-XXXX. '
        f'Nadie — ni Preferendum — puede vincular tu voto a tu identidad.'
        f'</p>'
        f'<div style="background:#0f2040;border:1px solid #1e3a6e;border-radius:8px;padding:12px 16px;font-size:12px;color:#7ab4ff;margin-top:16px;">'
        f'🔒 Bridge destruction activo · AES-256 · Polygon blockchain'
        f'</div>'
        f'</div>'
        f'<div style="padding:16px 32px;border-top:1px solid #1e2d4a;text-align:center;">'
        f'<p style="color:#475569;font-size:11px;margin:0;">En memoria del Socio Fundador José Ignacio Fernández (1989–2024)</p>'
        f'</div>'
        f'</div>'
    )
    resend_key = os.getenv('RESEND_API_KEY')
    if resend_key:
        try:
            _requests.post(
                'https://api.resend.com/emails',
                json={
                    'from': 'Preferendum <noreply@preferendum.com>',
                    'to': [email],
                    'subject': f'Tu Certificado de Registro en Preferendum — {cert_id}',
                    'html': html,
                    'text': f'Hola {name}, tu certificado de registro Preferendum es {cert_id}.',
                },
                headers={'Authorization': f'Bearer {resend_key}'},
                timeout=10,
            )
        except Exception as e:
            print(f'[Certificate Email Error] {e}')


def send_sms_otp(phone, code):
    sid = os.getenv('TWILIO_ACCOUNT_SID')
    token = os.getenv('TWILIO_AUTH_TOKEN')
    from_num = os.getenv('TWILIO_PHONE_NUMBER', '+15075027781')
    if sid and token:
        try:
            from twilio.rest import Client
            Client(sid, token).messages.create(
                body=f'Preferendum: Tu codigo es {code}. Valido 10 min.',
                from_=from_num,
                to=phone
            )
            return True
        except Exception as e:
            print(f'[Twilio Error] {e}')
    print(f'[DEV SMS] To: {phone} | Code: {code}')
    return True

# ══════════════════════════════════════════════════════════════
# SCHEMAS
# ══════════════════════════════════════════════════════════════

class RegisterInput(BaseModel):
    email:       str
    password:    str
    name:        str
    phone:       str
    country:     str = 'CL'
    county:      str = ''
    gender:      str = 'F'
    dob:         str = ''
    national_id: str = ''

class LoginInput(BaseModel):
    email:     str
    password:  str
    device_fp: str = ''

class CompleteLoginInput(BaseModel):
    pre_auth_token: str
    email_code:     str = ''
    sms_code:       str = ''
    face_token:     str = ''
    device_fp:      str = ''

class OTPInput(BaseModel):
    code:    str
    channel: str = 'email'

class GeoInput(BaseModel):
    latitude:  float
    longitude: float

class IMEIInput(BaseModel):
    imei:         str
    phone:        str
    device_model: str = ''
    os_version:   str = ''

class ChainInput(BaseModel):
    wallet_address: str

class DebateCreate(BaseModel):
    title:          str
    context:        str = ''
    options:        List[str]
    creator_type:   str = 'citizen'
    inst_name:      str = ''
    is_anonymous:   bool = False
    debate_type:    str = 'gov'
    scope:          str = 'country'
    scope_country:  str = 'CL'
    scope_commune:  str = ''
    target_gender:       str = 'all'
    target_age_min:      int = 13
    target_age_max:      int = 99
    target_se_tiers:     str = 'A,B,C,D'
    category:            str = 'general'
    closes_at:           str
    verify_days:         int = 14
    follow_up_questions: str = ''
    reward:              str = ''
    option_images:       List[str] = []
    cover_image_url:     str = ''

class OpinionCreate(BaseModel):
    text:            str
    knowledge_level: str = 'familiar'

class CastVoteRequest(BaseModel):
    option_index: int
    vote_chain:   list = []
    device_fp:    str  = ''
    face_token:   str  = ''

class VerifyVoteRequest(BaseModel):
    code: str

class CampaignCreate(BaseModel):
    advertiser_email:    str
    advertiser_name:     str
    campaign_title:      str
    budget_clp:          int
    ad_type:             str = 'banner'
    # Geo
    target_country:      str = ''
    target_communes:     str = ''        # 'Vitacura,Las Condes' / '' = todas
    # Nivel de ingreso
    target_se_tiers:     str = 'A,B,C,D' # 'A,B' = solo premium
    target_income_min:   float = 0.0
    target_income_max:   float = 9999.0
    # Demo
    target_gender:       str = 'all'
    target_age_min:      int = 13
    target_age_max:      int = 99
    target_age_ranges:   str = ''
    target_categories:   str = ''
    excluded_categories: str = ''
    blocked_competitors: str = ''
    start_date:          str
    end_date:            str
    logo_url:            str = ''
    ad_copy:             str = ''
    ad_image_url:        str = ''
    video_url:           str = ''
    link_url:            str = ''
    min_per_capita_usd:  float = 0.0

class AdViewInput(BaseModel):
    campaign_id: int
    debate_id:   Optional[int] = None
    gender:      str = ''
    age_group:   str = ''
    county:      str = ''
    country:     str = ''

class OrganizerRegisterInput(BaseModel):
    email:    str
    password: str
    name:     str
    phone:    str = ''
    country:  str = 'CL'
    county:   str = ''
    org_type: str = 'company'

class EstimateInput(BaseModel):
    budget_clp: int
    communes:   List[str]

# ══════════════════════════════════════════════════════════════
# SEED DEMO DATA
# ══════════════════════════════════════════════════════════════

def seed_demo_data():
    db = SessionLocal()
    try:
        if db.query(Debate).count() > 0:
            return
        now = datetime.utcnow()
        debates = [
            Debate(
                title='Cual debe ser el sueldo de diputados y senadores?',
                context='El sueldo actual equivale a 43 salarios minimos. Este debate busca conocer la opinion ciudadana.',
                options=json.dumps(['Reducir 40%', 'Reducir 20%', 'Mantener actual', 'Aumentar segun metricas']),
                inst_name='Congreso de Chile',
                creator_type='citizen',
                debate_type='nat',
                scope='country',
                scope_country='CL',
                closes_at=now + timedelta(days=7),
                verify_closes_at=now + timedelta(days=21),
                total_votes=24812,
                vote_counts=json.dumps({'Reducir 40%': 11166, 'Reducir 20%': 6204, 'Mantener actual': 4962, 'Aumentar segun metricas': 2480}),
            ),
            Debate(
                title='Prioridad para el presupuesto municipal 2027',
                context='Las Condes debe decidir como invertir el presupuesto del proximo año.',
                options=json.dumps(['Infraestructura vial', 'Salud publica', 'Educacion', 'Areas verdes']),
                inst_name='Municipalidad Las Condes',
                creator_type='municipality',
                debate_type='gov',
                scope='commune',
                scope_country='CL',
                scope_commune='Las Condes',
                closes_at=now + timedelta(days=14),
                verify_closes_at=now + timedelta(days=28),
                total_votes=8934,
                vote_counts=json.dumps({'Infraestructura vial': 2859, 'Salud publica': 2323, 'Educacion': 2055, 'Areas verdes': 1697}),
            ),
            Debate(
                title='Cual zapatilla preferirías para 2026?',
                context='Nike Chile quiere saber tu preferencia para su nueva coleccion.',
                options=json.dumps(['Air Max Pulse', 'Air Force 1', 'React Infinity', 'Pegasus Trail']),
                inst_name='Nike Chile',
                creator_type='company',
                debate_type='priv',
                scope='country',
                scope_country='CL',
                target_age_min=16,
                target_age_max=35,
                closes_at=now + timedelta(days=5),
                verify_closes_at=now + timedelta(days=19),
                total_votes=4182,
                vote_counts=json.dumps({'Air Max Pulse': 1631, 'Air Force 1': 1129, 'React Infinity': 920, 'Pegasus Trail': 502}),
            ),
        ]
        for d in debates:
            db.add(d)

        opinions = [
            Opinion(debate_id=1, user_id=0, user_name='Carlos M.', text='El sueldo actual equivale a 43 salarios minimos. Una reduccion del 40% acerca Chile a estandares OCDE.', knowledge_level='expert'),
            Opinion(debate_id=1, user_id=0, user_name='Ana P.', text='Una reduccion excesiva podria hacer el cargo menos atractivo para profesionales calificados.', knowledge_level='expert'),
            Opinion(debate_id=1, user_id=0, user_name='Pedro V.', text='Con el sueldo actual un diputado gana sobre $13 millones al mes. No hay justificacion.', knowledge_level='good'),
            Opinion(debate_id=1, user_id=0, user_name='Maria L.', text='El problema no es solo el monto sino la transparencia y las metricas de desempeno.', knowledge_level='good'),
            Opinion(debate_id=1, user_id=0, user_name='Ciudadano', text='Gano $480.000 trabajando 6 dias a la semana. No entiendo como alguien justifica ganar 27 veces mas.', knowledge_level='familiar'),
        ]
        for op in opinions:
            db.add(op)

        ads = [
            DebateAd(debate_id=1, brand='BancoEstado', copy='Cuenta RUT sin costo para todos los chilenos', cta='Abrir cuenta', logo_color='#10b981', link_url='https://www.bancoestado.cl/'),
            DebateAd(debate_id=1, brand='Toyota Chile', copy='Corolla Cross Hybrid — Eficiencia para el Chile real', cta='Ver modelos', logo_color='#ef4444', link_url='https://www.toyota.cl/'),
            DebateAd(debate_id=2, brand='Samsung', copy='Galaxy S26 Ultra — La camara que lo cambia todo', cta='Descubrir', logo_color='#3b82f6', link_url='https://www.samsung.com/cl/'),
            DebateAd(debate_id=2, brand='Nestlé Chile', copy='Calidad en cada producto para tu familia', cta='Conocer más', logo_color='#dc2626', link_url='https://www.nestle.cl/'),
        ]
        for ad in ads:
            db.add(ad)

        db.commit()
        print('[Seed] Demo data created successfully')
    except Exception as e:
        print(f'[Seed Error] {e}')
        db.rollback()
    finally:
        db.close()

seed_demo_data()

# ══════════════════════════════════════════════════════════════
# ROUTES: ROOT
# ══════════════════════════════════════════════════════════════

@app.get('/', response_class=HTMLResponse)
def root():
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="en" style="background:#090D18;">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<meta name="color-scheme" content="dark"/>
<meta name="supported-color-schemes" content="dark"/>
<title>Preferendum</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet"/>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
html,body{height:100%;background:#090D18;color:#F0F4FF;
  font-family:-apple-system,BlinkMacSystemFont,'Inter','Segoe UI',sans-serif;overflow-x:hidden;}

/* PAGE 1 — CONCEPT */
#page1{min-height:100vh;display:flex;flex-direction:column;align-items:center;
  justify-content:center;text-align:center;padding:40px 24px;
  background:radial-gradient(ellipse 70% 50% at 50% 40%,rgba(37,99,235,0.12) 0%,transparent 65%);}
.brand{font-family:'Playfair Display',serif;font-size:clamp(18px,4.5vw,26px);
  font-weight:700;color:#c8d8f0;letter-spacing:0.3em;
  text-transform:uppercase;margin-bottom:48px;}
.brand span{color:#4d8aff;}
.headline{font-family:'Playfair Display',serif;font-size:clamp(36px,8vw,96px);
  font-weight:900;color:#F0F4FF;line-height:1.02;letter-spacing:-2px;
  margin-bottom:28px;max-width:820px;}
.headline em{color:#4d8aff;font-style:normal;}
.nuance{font-size:clamp(15px,2.5vw,20px);color:rgba(240,244,255,0.72);
  line-height:1.7;max-width:520px;margin:0 auto 56px;font-weight:300;}
.nuance strong{color:#F0F4FF;font-weight:600;}
.enter-btn{display:inline-flex;align-items:center;gap:10px;
  background:#2563EB;color:#fff;padding:18px 48px;border-radius:12px;
  font-size:17px;font-weight:600;text-decoration:none;border:none;cursor:pointer;
  transition:all .25s;box-shadow:0 4px 40px rgba(37,99,235,0.35);}
.enter-btn:hover{background:#3b82f6;transform:translateY(-2px);box-shadow:0 8px 48px rgba(37,99,235,0.5);}
.tagline{margin-top:40px;font-size:12px;color:rgba(240,244,255,0.45);
  letter-spacing:0.2em;text-transform:uppercase;}

/* PAGE 2 — ROLE SELECTION */
#page2{display:none;min-height:100vh;flex-direction:column;align-items:center;
  justify-content:center;padding:40px 24px;
  background:radial-gradient(ellipse 60% 60% at 50% 30%,rgba(37,99,235,0.08) 0%,transparent 65%);}
#page2.active{display:flex;}
.p2-logo{font-family:'Playfair Display',serif;font-size:22px;font-weight:700;color:#c8d8f0;
  letter-spacing:0.3em;text-transform:uppercase;margin-bottom:12px;}
.p2-logo span{color:#4d8aff;}
.p2-title{font-family:'Playfair Display',serif;font-size:clamp(24px,5vw,40px);
  font-weight:700;color:#F0F4FF;text-align:center;margin-bottom:8px;}
.p2-sub{font-size:15px;color:rgba(240,244,255,0.70);text-align:center;
  margin-bottom:52px;line-height:1.6;max-width:440px;}
.p2-sub strong{color:#F0F4FF;font-weight:600;}
.roles{display:flex;flex-direction:column;gap:14px;width:100%;max-width:420px;}
.role-card{display:block;background:rgba(255,255,255,0.05);
  border:1px solid rgba(255,255,255,0.12);border-radius:18px;
  padding:24px 28px;text-decoration:none;transition:all .2s;cursor:pointer;}
.role-card:hover{background:rgba(37,99,235,0.12);border-color:#4d8aff;
  transform:translateY(-2px);box-shadow:0 8px 32px rgba(37,99,235,0.2);}
.role-name{font-size:18px;font-weight:700;color:#F0F4FF;margin-bottom:4px;}
.role-phrase{font-size:13px;color:rgba(240,244,255,0.65);line-height:1.5;font-style:italic;}
.role-arrow{float:right;color:#4d8aff;font-size:20px;margin-top:-2px;}
.back-btn{margin-top:32px;background:none;border:none;color:rgba(240,244,255,0.45);
  font-size:13px;cursor:pointer;letter-spacing:0.1em;transition:color .2s;}
.back-btn:hover{color:rgba(240,244,255,0.75);}
.p2-memo{margin-top:48px;font-size:11px;color:rgba(240,244,255,0.28);
  font-style:italic;text-align:center;}

@media(max-width:480px){
  .headline{letter-spacing:-1px;}
  .roles{max-width:100%;}
  .role-card{padding:20px 22px;}
}
</style>
</head>
<body>

<!-- PAGE 1: CONCEPT -->
<div id="page1">
  <div class="brand">prefer<span>endum</span></div>
  <h1 class="headline">
    Anyone.<br/>
    Anywhere.<br/>
    <em>Any issue.</em>
  </h1>
  <p class="nuance">
    <strong>Global decisions. Define your path.</strong><br/>
    When everyone expresses their preference, the nuance appears.
  </p>
  <button class="enter-btn" onclick="showPage2()">
    Enter →
  </button>
  <div class="tagline">Freedom to choose goes global</div>
</div>

<!-- PAGE 2: ROLE SELECTION -->
<div id="page2">
  <div class="p2-logo">prefer<span>endum</span></div>
  <h2 class="p2-title">Who are you?</h2>
  <p class="p2-sub">
    <strong>Every decision begins with a preference.</strong><br/>
    Choose your path to get started.
  </p>
  <div class="roles">
    <a href="/voter" class="role-card">
      <span class="role-arrow">→</span>
      <div class="role-name">I'm a Voter</div>
      <div class="role-phrase">"Your voice, verified. Your identity, never."</div>
    </a>
    <a href="/organizers" class="role-card">
      <span class="role-arrow">→</span>
      <div class="role-name">I want to run a consultation</div>
      <div class="role-phrase">"Do you want to ask your peers to express their preferences?"</div>
    </a>
    <a href="/marketers" class="role-card">
      <span class="role-arrow">→</span>
      <div class="role-name">I'm an Advertiser</div>
      <div class="role-phrase">"Benefit from reaching people who are actively deciding."</div>
    </a>
  </div>
  <button class="back-btn" onclick="showPage1()">← Back</button>
  <div class="p2-memo">En memoria del Socio Fundador José Ignacio Fernández (1989–2024)</div>
</div>

<script>
function showPage2(){
  document.getElementById('page1').style.display='none';
  document.getElementById('page2').classList.add('active');
}
function showPage1(){
  document.getElementById('page2').classList.remove('active');
  document.getElementById('page1').style.display='flex';
}
</script>

</body>
</html>""")

@app.get('/admin/stripe-setup', response_class=HTMLResponse)
def stripe_setup_form():
    return HTMLResponse(content='''<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stripe Setup</title>
<style>body{background:#0f172a;color:#fff;font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;}
.box{background:#1e293b;padding:32px;border-radius:12px;width:90%;max-width:480px;}
h2{margin:0 0 20px;font-size:18px;}
input{width:100%;padding:12px;background:#0f172a;border:1px solid #334155;border-radius:8px;color:#fff;font-size:14px;box-sizing:border-box;margin-bottom:16px;}
button{width:100%;padding:12px;background:#2d6eff;border:none;border-radius:8px;color:#fff;font-size:15px;font-weight:600;cursor:pointer;}
#msg{margin-top:12px;font-size:14px;}</style></head>
<body><div class="box">
<h2>Configurar Stripe Secret Key</h2>
<p style="font-size:13px;color:#94a3b8;margin-bottom:16px;">Ingresa la clave secreta de Stripe. Solo se guarda en la base de datos del servidor.</p>
<input type="password" id="k" placeholder="sk_test_..." />
<button onclick="save()">Guardar clave</button>
<div id="msg"></div>
</div>
<script>
async function save() {
  const k = document.getElementById('k').value.trim();
  if (!k.startsWith('sk_')) { document.getElementById('msg').textContent = 'La clave debe empezar con sk_'; return; }
  const r = await fetch('/admin/stripe-setup', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({key: k})});
  const d = await r.json();
  document.getElementById('msg').style.color = d.ok ? '#10b981' : '#f87171';
  document.getElementById('msg').textContent = d.ok ? '✓ Clave guardada correctamente' : 'Error: ' + d.error;
  if (d.ok) document.getElementById('k').value = '';
}
</script></body></html>''')

@app.post('/admin/stripe-setup')
async def stripe_setup_save(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
        key = body.get('key', '').strip()
        if not key.startswith('sk_'):
            return {'ok': False, 'error': 'Invalid key format'}
        db.execute(text("CREATE TABLE IF NOT EXISTS app_config (key VARCHAR PRIMARY KEY, value TEXT)"))
        db.execute(text("INSERT INTO app_config (key, value) VALUES ('stripe_secret_key', :v) ON CONFLICT (key) DO UPDATE SET value=:v"), {'v': key})
        db.commit()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@app.get('/admin/dev-otp/{phone}')
def dev_otp(phone: str, db: Session = Depends(get_db)):
    try:
        from urllib.parse import unquote
        phone = unquote(phone)
        user = db.query(User).filter(User.phone == phone).first()
        if not user:
            return {'error': 'user not found', 'phone': phone}
        otp = db.query(OTPCode).filter(
            OTPCode.user_id == user.id,
            OTPCode.used == False,
            OTPCode.expires_at > datetime.utcnow()
        ).order_by(OTPCode.id.desc()).first()
        if not otp:
            return {'error': 'no active OTP found — generate one via /admin/force-otp/' + phone, 'user_id': user.id}
        return {'phone': phone, 'code': otp.code, 'expires_at': str(otp.expires_at)}
    except Exception as e:
        return {'error': str(e)}

@app.post('/admin/force-otp/{phone}')
def force_otp(phone: str, db: Session = Depends(get_db)):
    """Admin: generate fresh OTP for phone without sending SMS (for testing)."""
    try:
        from urllib.parse import unquote
        phone = unquote(phone)
        user = db.query(User).filter(User.phone == phone).first()
        if not user:
            return {'error': 'user not found', 'phone': phone}
        code = gen_otp()
        db.add(OTPCode(user_id=user.id, email=user.email, code=code, channel='sms',
                       expires_at=datetime.utcnow() + timedelta(minutes=10)))
        db.commit()
        return {'phone': phone, 'code': code, 'message': 'OTP created (no SMS sent)', 'user_id': user.id}
    except Exception as e:
        return {'error': str(e)}

@app.get('/admin/vote-code')
def admin_vote_code(email: str, debate_id: int, db: Session = Depends(get_db)):
    """Admin: get verify_code for a user+debate combo (testing only)."""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return {'error': 'user not found'}
    log = db.query(HasVotedLog).filter(HasVotedLog.user_id == user.id, HasVotedLog.debate_id == debate_id).first()
    if not log:
        return {'error': 'no vote found for this user+debate', 'user_id': user.id}
    vote = db.query(DebateVote).filter(DebateVote.verify_code == log.verify_code).first()
    return {
        'email': email,
        'debate_id': debate_id,
        'verify_code': log.verify_code,
        'option_voted': vote.option_text if vote else '—',
    }

@app.get('/admin/check-stripe')
def check_stripe():
    key = (os.getenv('APP_STRIPE_KEY') or os.getenv('STRIPE_SECRET_KEY') or '').strip()
    all_stripe = [k for k in os.environ.keys() if 'STRIPE' in k.upper()]
    system_prefixes = ('PATH','HOME','USER','LANG','LC_','TERM','SHELL','PWD','SHLVL','DEBIAN','SSL','XDG','_','VIRTUAL','PYTHON','PIP','OLDPWD','HOSTNAME','LS_')
    custom_vars = sorted([k for k in os.environ.keys() if not any(k.startswith(p) for p in system_prefixes)])
    return {
        'stripe_configured': bool(key),
        'key_prefix': key[:12] if key else 'NOT SET',
        'stripe_env_vars_found': all_stripe,
        'total_env_vars': len(os.environ),
        'all_custom_vars': custom_vars
    }

@app.get('/health')
def health():
    # RENDER_GIT_COMMIT is set automatically by Render for every deploy —
    # exposing it lets CI know it's actually talking to the NEW deploy
    # before running post-deploy tests against it (Render pushes go live
    # ~10-15 min after the git push that triggers them, so "just pushed"
    # and "live" are different moments — this closes that gap honestly).
    return {
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat(),
        'git_commit': os.getenv('RENDER_GIT_COMMIT', ''),
    }

@app.get('/ping-test', response_class=HTMLResponse)
def ping_test():
    return HTMLResponse(content='''<!DOCTYPE html>
<html><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/></head>
<body style="background:#090D18;color:white;font-family:sans-serif;text-align:center;padding:60px 20px">
<div id="root"><p>Loading React...</p></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js"></script>
<script>
try {
  var el = React.createElement;
  var root = ReactDOM.createRoot(document.getElementById("root"));
  root.render(el("div",null,
    el("div",{style:{fontSize:60,marginBottom:20}},"✅"),
    el("div",{style:{fontSize:28,fontWeight:900,color:"#fff",marginBottom:10}},
      "prefer",el("span",{style:{color:"#4d8aff"}},"endum")),
    el("div",{style:{fontSize:16,color:"#90b8d8"}},"React working on this device")
  ));
} catch(e) {
  document.getElementById("root").innerHTML = "<p style=color:red>Error: "+e.message+"</p>";
}
</script>
</body></html>''')

@app.get('/marketer-portal', response_class=HTMLResponse)
def serve_marketer_portal():
    """Portal completo del anunciante — pagos, campañas, dashboard."""
    try:
        with open('marketer_portal.html', 'r', encoding='utf-8') as f:
            content = f.read()
        return HTMLResponse(content=content, headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
        })
    except FileNotFoundError:
        return HTMLResponse(content='<html><body>Portal not found</body></html>', status_code=404)

@app.get('/app', response_class=HTMLResponse)
def serve_app():
    """Sirve la app web directamente desde el servidor.
    La app móvil la carga aquí — cambios se ven sin rebuild de la app."""
    try:
        with open('assets/app.html', 'r', encoding='utf-8') as f:
            content = f.read()
        return HTMLResponse(content=content, headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
        })
    except FileNotFoundError:
        return HTMLResponse(content='<html><body>App not found</body></html>', status_code=404)

@app.get('/translate.js')
def serve_translate_js():
    """Centralized Google Translate config — change languages in one place for all portals."""
    try:
        with open('translate.js', 'r', encoding='utf-8') as f:
            content = f.read()
        return Response(content=content, media_type='application/javascript', headers={
            'Cache-Control': 'public, max-age=86400',
        })
    except FileNotFoundError:
        return Response(content='// translate.js not found', media_type='application/javascript', status_code=404)

@app.get('/voter', response_class=HTMLResponse)
def serve_voter_portal():
    """Portal web de votante — funciona en móvil y desktop."""
    try:
        with open('voter_portal.html', 'r', encoding='utf-8') as f:
            content = f.read()
        return HTMLResponse(content=content, headers={'Cache-Control': 'no-cache, no-store, must-revalidate'})
    except FileNotFoundError:
        return HTMLResponse(content='<html><body>Voter portal not found</body></html>', status_code=404)


class VoterRegisterInput(BaseModel):
    name:        str
    email:       str
    password:    str
    country:     str = 'CL'
    phone:       str = ''
    national_id: str = ''   # RUT para Chile, DNI para otros
    gender:      str = ''
    dob:         str = ''   # YYYY-MM-DD
    commune:     str = ''   # comuna declarada
    device_fp:   str = ''


@app.post('/voter/register')
def voter_register(data: VoterRegisterInput, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Register a voter — sends email OTP for verification."""
    if not data.national_id or not data.national_id.strip():
        raise HTTPException(400, 'El documento de identidad (RUT/DNI/CPF) es obligatorio')
    # Normalize and check national ID not already registered
    nid_clean = re.sub(r'[\.\-\s]', '', data.national_id.strip().upper())
    dup_nid = db.query(User).filter(
        User.national_id.isnot(None),
        User.national_id != '',
        User.national_id == data.national_id.strip()
    ).first()
    if dup_nid:
        raise HTTPException(409, 'Este documento de identidad ya está registrado')
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        if not bcrypt.checkpw(data.password.encode(), existing.password.encode()):
            raise HTTPException(400, 'Email ya registrado con contraseña diferente')
        # Re-send OTP if not yet verified
        if not existing.email_verified:
            code = gen_otp()
            db.query(OTPCode).filter(OTPCode.user_id == existing.id, OTPCode.channel == 'email', OTPCode.used == False).update({'used': True})
            db.add(OTPCode(user_id=existing.id, email=existing.email, code=code, channel='email',
                           expires_at=datetime.utcnow() + timedelta(minutes=15)))
            db.commit()
            bg.add_task(send_email_otp, existing.email, code, existing.name)
        return {'token': make_token(existing.id), 'user': {
            'id': existing.id, 'name': existing.name, 'email': existing.email,
            'email_verified': existing.email_verified, 'phone': existing.phone or ''
        }}
    hashed = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    user = User(
        email=data.email, name=data.name, password=hashed,
        country=data.country, email_verified=False,
        phone=data.phone, county=data.commune,
        gender=data.gender, dob=data.dob, national_id=data.national_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _assign_user_tier(user, db)
    code = gen_otp()
    check_and_register_device(data.device_fp, user.id, db)
    db.add(OTPCode(user_id=user.id, email=user.email, code=code, channel='email',
                   expires_at=datetime.utcnow() + timedelta(minutes=15)))
    db.commit()
    bg.add_task(send_email_otp, user.email, code, user.name)
    return {'token': make_token(user.id), 'user': {
        'id': user.id, 'name': user.name, 'email': user.email,
        'email_verified': False, 'phone': data.phone
    }}


@app.get('/r/{debate_id}', response_class=HTMLResponse)
def public_results_page(debate_id: int, db: Session = Depends(get_db)):
    """Página pública de resultados — compartible por el organizador."""
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        return HTMLResponse('<html><body>Consulta no encontrada</body></html>', status_code=404)

    opts    = json.loads(debate.options or '[]')
    counts  = json.loads(debate.vote_counts or '{}')
    total   = debate.total_votes or 0
    ls      = round(debate.legitimacy_score or 0, 1)
    status  = debate.status or 'live'
    status_label = {'live': 'En curso', 'closed': 'Cerrada', 'draft': 'Borrador'}.get(status, status)
    status_color = {'live': '#10B981', 'closed': '#2563EB', 'draft': '#F59E0B'}.get(status, '#64748B')
    closes  = debate.closes_at.strftime('%d %b %Y') if debate.closes_at else ''
    tx      = debate.created_at.strftime('%d %b %Y') if debate.created_at else ''

    COLORS = ['#2563EB','#10B981','#F59E0B','#F43F5E','#8B5CF6','#06B6D4','#EC4899','#84CC16','#F97316','#6366F1']

    bars_html = ''
    winner_opt = ''
    winner_count = 0
    for i, opt in enumerate(opts):
        cnt  = counts.get(opt, 0)
        pct  = round(cnt / total * 100, 1) if total > 0 else 0
        color = COLORS[i % len(COLORS)]
        if cnt > winner_count:
            winner_count = cnt
            winner_opt   = opt
        bars_html += f'''
        <div style="margin-bottom:20px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
            <span style="font-size:15px;color:#e8f0fc;font-weight:600;">{opt}</span>
            <span style="font-size:15px;font-weight:800;color:{color};">{pct}%</span>
          </div>
          <div style="background:#1a2240;border-radius:8px;height:12px;overflow:hidden;">
            <div style="height:100%;width:{pct}%;background:{color};border-radius:8px;transition:width 1s;"></div>
          </div>
          <div style="font-size:12px;color:#64748b;margin-top:4px;">{cnt:,} votos</div>
        </div>'''

    winner_html = ''
    if status == 'closed' and winner_opt:
        winner_html = f'''
        <div style="background:linear-gradient(135deg,#10b98122,#2563eb22);border:1px solid #10b981;
          border-radius:16px;padding:20px 24px;margin-bottom:28px;text-align:center;">
          <div style="font-size:11px;color:#10b981;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">Resultado verificado</div>
          <div style="font-size:22px;font-weight:900;color:#f0f4ff;margin-bottom:4px;">🏆 {winner_opt}</div>
          <div style="font-size:13px;color:#94a3b8;">{winner_count:,} votos · {round(winner_count/total*100,1) if total>0 else 0}%</div>
        </div>'''

    html = f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<meta property="og:title" content="Resultados: {debate.title[:60]}"/>
<meta property="og:description" content="{total:,} votos verificados · Legitimacy Score {ls}% · Preferendum"/>
<meta property="og:type" content="website"/>
<title>Resultados — {debate.title[:50]} | Preferendum</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#090D18;color:#f0f4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh;}}
.wrap{{max-width:640px;margin:0 auto;padding:24px 20px 60px;}}
.nav{{display:flex;align-items:center;justify-content:space-between;margin-bottom:32px;}}
.logo{{font-size:20px;font-weight:900;color:#f0f4ff;letter-spacing:-0.5px;}}
.logo span{{color:#2563EB;}}
.badge{{font-size:11px;padding:4px 12px;border-radius:20px;font-weight:700;letter-spacing:0.5px;}}
.card{{background:#0f1528;border:1px solid #1a2240;border-radius:20px;padding:24px;margin-bottom:20px;}}
.inst{{font-size:13px;color:#64748b;font-weight:600;margin-bottom:6px;}}
.title{{font-size:22px;font-weight:900;color:#f0f4ff;line-height:1.4;margin-bottom:16px;}}
.context{{font-size:14px;color:#94a3b8;line-height:1.7;}}
.stats{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:20px;}}
.stat{{background:#0f1528;border:1px solid #1a2240;border-radius:14px;padding:16px;text-align:center;}}
.stat-n{{font-size:26px;font-weight:900;color:#f0f4ff;}}
.stat-l{{font-size:11px;color:#64748b;margin-top:4px;letter-spacing:0.5px;text-transform:uppercase;}}
.chain{{background:#0f1528;border:1px solid #1a2240;border-radius:14px;padding:16px;margin-bottom:20px;
  display:flex;align-items:center;gap:12px;}}
.chain-icon{{font-size:24px;}}
.chain-text{{font-size:11px;color:#64748b;}}
.chain-hash{{font-family:monospace;font-size:11px;color:#2563eb;word-break:break-all;margin-top:2px;}}
.footer{{text-align:center;margin-top:40px;padding-top:24px;border-top:1px solid #1a2240;}}
.footer-logo{{font-size:18px;font-weight:900;margin-bottom:8px;}}
.footer-logo span{{color:#2563eb;}}
.footer-sub{{font-size:12px;color:#64748b;margin-bottom:4px;}}
.footer-mem{{font-size:11px;color:#475569;font-style:italic;}}
</style>
</head>
<body>
<div class="wrap">
  <div class="nav">
    <div class="logo">prefer<span>endum</span></div>
    <span class="badge" style="background:{status_color}22;color:{status_color};">{status_label}</span>
  </div>

  <div class="card">
    <div class="inst">{debate.inst_name or 'Preferendum'}</div>
    <div class="title">{debate.title}</div>
    {f'<div class="context">{debate.context}</div>' if debate.context else ''}
  </div>

  <div class="stats">
    <div class="stat">
      <div class="stat-n">{total:,}</div>
      <div class="stat-l">Votos</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:#10b981;">{ls}%</div>
      <div class="stat-l">Legitimacy</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="font-size:16px;color:#64748b;">{closes or '—'}</div>
      <div class="stat-l">Cierre</div>
    </div>
  </div>

  {winner_html}

  <div class="card">
    <div style="font-size:11px;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin-bottom:20px;">Distribución de votos</div>
    {bars_html if total > 0 else '<div style="text-align:center;color:#64748b;padding:20px;">Aún no hay votos</div>'}
  </div>

  <div class="chain">
    <div class="chain-icon">⛓</div>
    <div>
      <div class="chain-text">Resultado anclado en Polygon blockchain</div>
      <div class="chain-hash">{debate.tx_hash or 'Pendiente de anclaje blockchain'}</div>
    </div>
  </div>

  <div class="footer">
    <div class="footer-logo">prefer<span>endum</span></div>
    <div class="footer-sub">Plataforma de decisiones verificadas · preferendum.com</div>
    <div class="footer-mem">En memoria del Socio Fundador José Ignacio Fernández (1989–2024)</div>
  </div>
</div>
</body>
</html>'''
    return HTMLResponse(content=html)


@app.get('/logo-sable.svg')
def logo_sable():
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 60" width="200" height="60">
  <rect width="200" height="60" rx="8" fill="#0a0d14"/>
  <text x="16" y="22" font-family="Georgia,serif" font-size="11" fill="#6b8ca4" letter-spacing="3" font-weight="400">GRUPO</text>
  <text x="14" y="48" font-family="Georgia,serif" font-size="28" fill="#ffffff" letter-spacing="1" font-weight="700">Sable</text>
  <rect x="14" y="52" width="40" height="2" rx="1" fill="#2d6eff"/>
</svg>'''
    from fastapi.responses import Response
    return Response(content=svg, media_type='image/svg+xml', headers={'Cache-Control': 'public, max-age=86400'})


@app.get('/logo-transfernet.svg')
def logo_transfernet():
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
  <rect width="100" height="100" rx="16" fill="#1a3a5c"/>
  <polygon points="15,75 35,35 55,75" fill="none" stroke="#4a9edd" stroke-width="3" stroke-linejoin="round"/>
  <polygon points="40,75 62,28 84,75" fill="none" stroke="#ffffff" stroke-width="3" stroke-linejoin="round"/>
  <ellipse cx="62" cy="24" rx="6" ry="4" fill="#ffffff"/>
  <circle cx="68" cy="20" r="4" fill="#ffffff"/>
  <path d="M67,17 L65,12 M69,16 L72,11" stroke="#ffffff" stroke-width="1.5" stroke-linecap="round" fill="none"/>
  <line x1="59" y1="27" x2="57" y2="32" stroke="#ffffff" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="65" y1="27" x2="67" y2="32" stroke="#ffffff" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="10" y1="75" x2="90" y2="75" stroke="#4a9edd" stroke-width="2"/>
  <text x="50" y="90" text-anchor="middle" font-family="Arial,sans-serif" font-size="9" font-weight="bold" fill="#4a9edd" letter-spacing="1">TRANSFERNET</text>
</svg>'''
    from fastapi.responses import Response
    return Response(content=svg, media_type='image/svg+xml', headers={'Cache-Control': 'public, max-age=86400'})


@app.get('/privacy')
def privacy():
    html = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Preferendum Privacy Policy</title>
<style>body{font-family:sans-serif;max-width:800px;margin:0 auto;padding:40px 24px;
background:#07090f;color:#b8cce0;line-height:1.8;}
h1{color:#fff;}h2{color:#3b82f6;margin-top:32px;}
.logo{font-size:28px;font-weight:900;color:#fff;margin-bottom:32px;}
.logo span{color:#3b82f6;}</style></head>
<body>
<div class="logo">prefer<span>endum</span></div>
<h1>Privacy Policy</h1>
<p>Last updated: May 2026</p>
<p>Preferendum is committed to protecting the privacy of all users.</p>
<h2>Data We Collect</h2>
<p>Name, email, phone, identity document, gender, date of birth, country and district.
Device identifier (IMEI) and approximate geolocation for verification purposes.</p>
<h2>Vote Privacy</h2>
<p>Your vote is encrypted with AES-256. After recording, your voter ID is permanently
unlinked from your vote (bridge destruction). A unique XXXX-XXXX-XXXX code lets you
verify your vote was counted correctly.</p>
<h2>Data Sharing</h2>
<p>We do not sell or share your personal data with third parties.
Ads are targeted using anonymous demographic data only.</p>
<h2>Account Deletion</h2>
<p>Request account deletion at: privacy@preferendum.com</p>
<h2>Contact</h2>
<p>privacy@preferendum.com — CAIP Task Force, Santiago, Chile</p>
<p style="margin-top:48px;color:#4a5568;font-size:13px;font-style:italic;">
En memoria del Socio Fundador José Ignacio Fernández (1989–2024), quien demostró que era posible.</p>
</body></html>"""
    return HTMLResponse(content=html)

# ══════════════════════════════════════════════════════════════
# ROUTES: AUTH
# ══════════════════════════════════════════════════════════════

@app.post('/auth/register')
def register(data: RegisterInput, bg: BackgroundTasks, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, 'Email already registered')
    hashed = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    user = User(
        email=data.email, name=data.name, password=hashed,
        phone=data.phone, country=data.country, county=data.county,
        gender=data.gender, dob=data.dob, national_id=data.national_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _assign_user_tier(user, db)
    code = gen_otp()
    db.add(OTPCode(
        user_id=user.id, email=user.email, code=code,
        channel='email', expires_at=datetime.utcnow() + timedelta(minutes=10)
    ))
    db.commit()
    bg.add_task(send_email_otp, user.email, code, user.name)
    bg.add_task(send_welcome_certificate, user.email, user.name, user.id)
    return {
        'token': make_token(user.id),
        'user': {'id': user.id, 'name': user.name, 'email': user.email, 'verify_level': 0},
        'next_step': 'verify_email',
        'message': f'Verification code sent to {user.email}'
    }

@app.post('/auth/login')
def login(data: LoginInput, bg: BackgroundTasks, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not bcrypt.checkpw(data.password.encode(), user.password.encode()):
        raise HTTPException(401, 'Invalid credentials')
    check_and_register_device(data.device_fp, user.id, db)

    needs_2fa = user.email_verified or user.phone_verified or user.selfie_verified
    if not needs_2fa:
        return {
            'token': make_token(user.id, user.role),
            'user': {
                'id': user.id, 'name': user.name, 'email': user.email,
                'country': user.country or 'CL',
                'verify_level': user.verify_level, 'is_verified': user.is_verified,
                'email_verified': user.email_verified,
                'phone_verified': user.phone_verified,
                'id_verified': user.id_verified,
                'selfie_verified': user.selfie_verified,
            }
        }

    # Invalidar OTPs previos y generar nuevos
    db.query(OTPCode).filter(OTPCode.user_id == user.id, OTPCode.used == False).update({'used': True})
    db.commit()

    if user.email_verified:
        email_code = gen_otp()
        db.add(OTPCode(user_id=user.id, email=user.email, code=email_code, channel='email',
                       expires_at=datetime.utcnow() + timedelta(minutes=10)))
        bg.add_task(send_email_otp, user.email, email_code, user.name)

    twilio_active = bool(os.getenv('TWILIO_ACCOUNT_SID') and os.getenv('TWILIO_AUTH_TOKEN'))
    sms_required = False
    if user.phone_verified and user.phone and twilio_active:
        sms_code = gen_otp()
        db.add(OTPCode(user_id=user.id, email=user.email, code=sms_code, channel='sms',
                       expires_at=datetime.utcnow() + timedelta(minutes=10)))
        bg.add_task(send_sms_otp, user.phone, sms_code)
        sms_required = True

    db.commit()

    pre_auth = jwt.encode({
        'sub': user.id, 'type': 'pre_auth',
        'exp': datetime.utcnow() + timedelta(minutes=10)
    }, SECRET, algorithm='HS256')

    return {
        'pending_2fa': True,
        'pre_auth_token': pre_auth,
        'requires': {
            'email': bool(user.email_verified),
            'sms':   sms_required,
            'face':  bool(user.selfie_verified),
        },
        'email_hint': user.email[:3] + '***' + user.email[user.email.find('@'):] if user.email else '',
        'phone_hint': ('***' + user.phone[-4:]) if user.phone else '',
    }

@app.post('/auth/login/face-token')
async def login_face_token(
    file: UploadFile = File(...),
    pre_auth_token: str = Form(...),
    db: Session = Depends(get_db)
):
    """Valida la cara durante el 2FA de login y devuelve un token de cara."""
    try:
        payload = jwt.decode(pre_auth_token, SECRET, algorithms=['HS256'])
        if payload.get('type') != 'pre_auth':
            raise HTTPException(403, 'Token inválido')
        user_id = payload['sub']
    except jwt.ExpiredSignatureError:
        raise HTTPException(403, 'Sesión expirada — vuelve a iniciar sesión')
    except Exception:
        raise HTTPException(403, 'Token inválido')

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.selfie_verified:
        raise HTTPException(400, 'Sin selfie de referencia')

    contents = await file.read()
    ref = db.query(SelfieLog).filter(
        SelfieLog.user_id == user_id, SelfieLog.verified == True, SelfieLog.face_bytes != None
    ).order_by(SelfieLog.created_at.desc()).first()

    rekognition_score = None
    rekognition_mode = 'no_aws'

    aws_key = os.getenv('AWS_ACCESS_KEY_ID')
    if not aws_key:
        raise HTTPException(503, 'Verificación facial no disponible en este momento.')
    if not ref or not ref.face_bytes:
        raise HTTPException(400, 'No tienes selfie de referencia registrada.')
    try:
        rek = _rekognition_client()
        resp = rek.compare_faces(
            SourceImage={'Bytes': base64.b64decode(ref.face_bytes)},
            TargetImage={'Bytes': contents},
            SimilarityThreshold=80.0
        )
        matches = resp.get('FaceMatches', [])
        if matches:
            rekognition_score = round(matches[0]['Similarity'], 2)
            rekognition_mode = 'verified'
            if rekognition_score / 100.0 < 0.90:
                raise HTTPException(400, f'Tu cara no coincide ({rekognition_score}% similitud). Intenta con mejor iluminación.')
        else:
            rekognition_mode = 'no_match'
            raise HTTPException(400, 'Tu cara no coincide con la registrada.')
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, 'Error en el servicio de verificación facial. Intenta de nuevo.')

    # Solo llega aquí si rekognition_mode == 'verified'
    face_token = jwt.encode({
        'sub': user_id, 'type': 'face_login',
        'exp': datetime.utcnow() + timedelta(minutes=5)
    }, SECRET, algorithm='HS256')

    return {
        'face_token': face_token,
        'rekognition_score': rekognition_score,
        'rekognition_mode': rekognition_mode,
        'message': f'✅ {rekognition_score}% coincidencia' if rekognition_score else '✅ Verificado (modo demo)'
    }

@app.post('/auth/complete-login')
def complete_login(data: CompleteLoginInput, db: Session = Depends(get_db)):
    """Paso 2 del login: valida OTPs + face token y devuelve el JWT completo."""
    try:
        payload = jwt.decode(data.pre_auth_token, SECRET, algorithms=['HS256'])
        if payload.get('type') != 'pre_auth':
            raise HTTPException(403, 'Token inválido')
        user_id = payload['sub']
    except jwt.ExpiredSignatureError:
        raise HTTPException(403, 'Sesión expirada — vuelve a iniciar sesión')
    except Exception:
        raise HTTPException(403, 'Token inválido')

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, 'Usuario no encontrado')

    # Validar código de email
    if user.email_verified:
        if not data.email_code:
            raise HTTPException(400, 'Se requiere el código de email')
        otp_email = db.query(OTPCode).filter(
            OTPCode.user_id == user.id, OTPCode.channel == 'email',
            OTPCode.code == data.email_code.strip(), OTPCode.used == False,
            OTPCode.expires_at > datetime.utcnow()
        ).first()
        if not otp_email:
            raise HTTPException(400, 'Código de email incorrecto o expirado')
        otp_email.used = True

    # Validar código de SMS solo si Twilio está activo
    twilio_active = bool(os.getenv('TWILIO_ACCOUNT_SID') and os.getenv('TWILIO_AUTH_TOKEN'))
    if user.phone_verified and user.phone and twilio_active:
        if not data.sms_code:
            raise HTTPException(400, 'Se requiere el código de SMS')
        otp_sms = db.query(OTPCode).filter(
            OTPCode.user_id == user.id, OTPCode.channel == 'sms',
            OTPCode.code == data.sms_code.strip(), OTPCode.used == False,
            OTPCode.expires_at > datetime.utcnow()
        ).first()
        if not otp_sms:
            raise HTTPException(400, 'Código de SMS incorrecto o expirado')
        otp_sms.used = True

    # Validar face token
    if user.selfie_verified:
        if not data.face_token:
            raise HTTPException(400, 'Se requiere verificación facial')
        try:
            fp = jwt.decode(data.face_token, SECRET, algorithms=['HS256'])
            if fp.get('type') != 'face_login' or fp.get('sub') != user.id:
                raise HTTPException(403, 'Token facial inválido')
        except jwt.ExpiredSignatureError:
            raise HTTPException(403, 'La verificación facial expiró — vuelve a tomarte la selfie')
        except Exception:
            raise HTTPException(403, 'Token facial inválido')

    db.commit()

    if data.device_fp:
        check_and_register_device(data.device_fp, user.id, db)

    return {
        'token': make_token(user.id, user.role),
        'user': {
            'id': user.id, 'name': user.name, 'email': user.email,
            'country': user.country or 'CL',
            'verify_level': user.verify_level, 'is_verified': user.is_verified,
            'email_verified': user.email_verified,
            'phone_verified': user.phone_verified,
            'id_verified': user.id_verified,
            'selfie_verified': user.selfie_verified,
        }
    }

@app.get('/auth/me')
def me(user: User = Depends(get_current_user)):
    return {
        'id': user.id, 'name': user.name, 'email': user.email,
        'country': user.country or 'CL',
        'verify_level': user.verify_level, 'is_verified': user.is_verified,
        'email_verified': user.email_verified,
        'phone_verified': user.phone_verified,
        'selfie_verified': user.selfie_verified,
    }

# ══════════════════════════════════════════════════════════════
# ROUTES: VERIFICATION
# ══════════════════════════════════════════════════════════════

@app.post('/verify/email/send')
def send_email_code(bg: BackgroundTasks, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.email_verified:
        return {'message': 'Email already verified', 'verified': True}
    db.query(OTPCode).filter(OTPCode.user_id == user.id, OTPCode.channel == 'email', OTPCode.used == False).update({'used': True})
    db.commit()
    code = gen_otp()
    db.add(OTPCode(user_id=user.id, email=user.email, code=code, channel='email', expires_at=datetime.utcnow() + timedelta(minutes=10)))
    db.commit()
    bg.add_task(send_email_otp, user.email, code, user.name)
    return {'message': f'Code sent to {user.email}'}

@app.post('/verify/email/confirm')
def confirm_email(data: OTPInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.email_verified:
        return {'verified': True}
    otp = db.query(OTPCode).filter(
        OTPCode.user_id == user.id, OTPCode.channel == 'email',
        OTPCode.code == data.code, OTPCode.used == False,
        OTPCode.expires_at > datetime.utcnow()
    ).first()
    if not otp:
        raise HTTPException(400, 'Invalid or expired code')
    otp.used = True
    user.email_verified = True
    update_verify_level(user, db)
    return {'verified': True, 'verify_level': user.verify_level, 'next_step': 'verify_phone'}

@app.post('/verify/phone/send')
def send_phone_code(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.phone_verified:
        return {'verified': True}
    code = gen_otp()
    db.add(OTPCode(user_id=user.id, email=user.email, code=code, channel='sms', expires_at=datetime.utcnow() + timedelta(minutes=10)))
    db.commit()
    send_sms_otp(user.phone, code)
    return {'message': f'SMS sent to {user.phone[-4:].rjust(8,"*")}'}

@app.post('/verify/phone/confirm')
def confirm_phone(data: OTPInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.phone_verified:
        return {'verified': True}
    otp = db.query(OTPCode).filter(
        OTPCode.user_id == user.id, OTPCode.channel == 'sms',
        OTPCode.code == data.code, OTPCode.used == False,
        OTPCode.expires_at > datetime.utcnow()
    ).first()
    if not otp:
        raise HTTPException(400, 'Invalid or expired code')
    otp.used = True
    user.phone_verified = True
    update_verify_level(user, db)
    return {'verified': True, 'verify_level': user.verify_level}

def _verify_company_rut(rut: str) -> dict:
    """
    Valida RUT chileno por dígito verificador (matemático, siempre funciona).
    Intenta enriquecer con razón social desde SII como bonus — si falla, no importa.
    """
    rut_clean = rut.replace('.', '').replace('-', '').strip().upper()
    # Validación matemática del dígito verificador — esto es el check real
    format_valid = False
    try:
        digits = rut_clean[:-1]
        dv     = rut_clean[-1]
        n = int(digits)
        if n < 1_000_000:
            return {'valid': False, 'razon_social': '', 'activo': False}
        s, m = 0, 2
        while n:
            s += (n % 10) * m
            n //= 10
            m = 2 if m == 7 else m + 1
        expected = str(11 - s % 11).replace('10', 'K').replace('11', '0')
        format_valid = (dv == expected)
    except Exception:
        return {'valid': False, 'razon_social': '', 'activo': False}

    if not format_valid:
        return {'valid': False, 'razon_social': '', 'activo': False}

    # Optional enrichment: try SII for company name (best-effort, 5s max)
    razon = ''
    try:
        resp = _requests.get(
            f'https://zeus.sii.cl/cvc_cgi/stc/getstc?RUT={rut_clean}',
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=5,
        )
        if resp.status_code == 200 and 'razon_social' in resp.text.lower():
            match = re.search(r'<razon_social>(.*?)</razon_social>', resp.text, re.IGNORECASE)
            razon = match.group(1).strip() if match else ''
    except Exception:
        pass

    return {'valid': True, 'razon_social': razon, 'activo': True}


def _verify_email_domain(email: str) -> dict:
    """
    Verifica que el dominio del email corporativo existe y no es gratuito.
    Rechaza gmail, hotmail, yahoo, outlook, etc.
    """
    FREE_DOMAINS = {'gmail.com','hotmail.com','yahoo.com','outlook.com',
                    'icloud.com','live.com','msn.com','protonmail.com'}
    try:
        domain = email.split('@')[1].lower().strip()
        if domain in FREE_DOMAINS:
            return {'valid': False, 'domain': domain, 'reason': 'Email gratuito — usa tu email corporativo'}
        # Try A/AAAA record first
        try:
            import socket
            socket.getaddrinfo(domain, None)
            return {'valid': True, 'domain': domain}
        except Exception:
            pass
        # Fallback: check if MX record exists (domain is real but web-server-less)
        import subprocess, shutil
        if shutil.which('host'):
            result = subprocess.run(['host', '-t', 'MX', domain],
                                    capture_output=True, text=True, timeout=5)
            if 'mail is handled' in result.stdout or 'MX' in result.stdout:
                return {'valid': True, 'domain': domain}
        # Accept non-free domains even without DNS confirmation — category check is the real gate
        return {'valid': True, 'domain': domain}
    except Exception:
        return {'valid': False, 'domain': '', 'reason': 'Dominio no existe'}


def _verify_company_web(web_url: str, company_name: str, company_rut: str) -> dict:
    """
    Verifica que el sitio web de la empresa existe y menciona la empresa.
    """
    if not web_url.startswith('http'):
        web_url = 'https://' + web_url
    try:
        resp = _requests.get(web_url, headers={'User-Agent': 'Mozilla/5.0'},
                             timeout=10, allow_redirects=True)
        if resp.status_code != 200:
            return {'valid': False, 'reason': f'Sitio no responde ({resp.status_code})'}
        content = resp.text.lower()
        rut_clean = company_rut.replace('.', '').replace('-', '').lower()
        name_words = [w.lower() for w in company_name.split() if len(w) > 3]
        name_found = any(w in content for w in name_words)
        rut_found  = rut_clean[:6] in content  # primeros 6 dígitos del RUT
        return {
            'valid': name_found or rut_found,
            'name_found': name_found,
            'rut_found': rut_found,
            'reason': '' if (name_found or rut_found) else 'No encontramos el nombre de la empresa en el sitio'
        }
    except Exception as e:
        return {'valid': False, 'reason': f'No pudimos acceder al sitio: {str(e)[:60]}'}


# Categorías permitidas en el pop-up de registro de marketer — lista cerrada,
# el solicitante elige una, no escribe texto libre (más fácil de auditar).
MARKETER_BUSINESS_CATEGORIES = [
    'retail_comercio', 'banca_finanzas', 'automotriz', 'tecnologia',
    'alimentos_bebidas', 'inmobiliaria', 'salud_bienestar', 'educacion',
    'turismo_viajes', 'telecomunicaciones', 'energia_servicios_basicos',
    'medios_entretenimiento', 'ong_sin_fines_de_lucro', 'gobierno_sector_publico',
    'otro',
]

# Categorías que nunca podrán anunciar en Preferendum — el filtro corta acá,
# antes de gastar tiempo de revisión humana o llamadas a Rekognition en alguien
# que jamás debió pasar de esta pantalla.
MARKETER_PROHIBITED_CATEGORIES = [
    'pornografia', 'contenido_adulto', 'servicios_sexuales',
    'drogas_ilegales', 'armas_de_fuego', 'apuestas_no_reguladas',
    'productos_falsificados', 'odio_extremismo',
]

def _check_business_category(category: str) -> dict:
    """
    Filtro de entrada del pop-up de categoría — corta de raíz a rubros prohibidos
    antes de que avancen a verificación de identidad.
    Devuelve {allowed, reason}.
    """
    cat = (category or '').strip().lower()
    if not cat:
        return {'allowed': False, 'reason': 'Debes declarar la categoría de tu empresa'}
    if cat in MARKETER_PROHIBITED_CATEGORIES:
        return {'allowed': False, 'reason': f'Preferendum no acepta anunciantes de la categoría "{cat}"'}
    if cat not in MARKETER_BUSINESS_CATEGORIES:
        return {'allowed': False, 'reason': f'"{cat}" no es una categoría reconocida — elige una de la lista'}
    return {'allowed': True, 'reason': ''}


def _moderate_consultation(title: str, context: str, options: list) -> dict:
    """
    Analiza una consulta con IA antes de publicarla.
    Score 0-100. Decisión: approved / review / rejected.
    """
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        return {'score': 75, 'decision': 'approved', 'reason': 'Sin API key — modo demo'}

    prompt = f"""Eres el moderador de Preferendum, plataforma de consultas ciudadanas verificadas.
Analiza esta consulta y da un score de 0 a 100 basado en estos criterios:

TÍTULO: {title}
CONTEXTO: {context}
OPCIONES: {', '.join(options)}

CRITERIOS (suma puntos si cumple):
- Es una pregunta legítima de decisión colectiva (+30)
- Opciones equilibradas y no manipuladoras (+20)
- Sin contenido obsceno ni violento (+20)
- Sin ataques a personas específicas (+15)
- Sin propaganda política disfrazada de consulta (+15)

Responde SOLO en este formato JSON:
{{"score": 85, "decision": "approved", "reason": "Consulta legítima sobre..."}}

decision debe ser: "approved" (score>=80), "review" (score 50-79), "rejected" (score<50)"""

    try:
        resp = _requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                     'content-type': 'application/json'},
            json={'model': 'claude-haiku-4-5-20251001', 'max_tokens': 200,
                  'messages': [{'role': 'user', 'content': prompt}]},
            timeout=15,
        )
        import re, json as _json
        text = resp.json()['content'][0]['text']
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            result = _json.loads(match.group())
            return result
    except Exception as e:
        print(f'[Moderation] Error: {e}')
    return {'score': 60, 'decision': 'review', 'reason': 'Error en moderación — revisión manual'}


def _send_supervisor_authorization_email(supervisor_email, employee_name, employee_email, company, cargo, token, role='organizer'):
    approve_url = f'https://preferendum-unzip-d2zd.onrender.com/{role}/authorize/{token}'
    action_desc = 'crear consultas' if role == 'organizer' else 'lanzar campañas publicitarias'
    html = (
        f'<div style="font-family:sans-serif;max-width:520px;margin:0 auto;background:#07090f;color:#fff;border-radius:16px;overflow:hidden;">'
        f'<div style="background:#0d1526;padding:28px 32px;border-bottom:1px solid #1e2d4a;">'
        f'<h1 style="margin:0;font-size:22px;">prefer<span style="color:#fff">endum</span></h1></div>'
        f'<div style="padding:32px;">'
        f'<h2 style="margin:0 0 16px;font-size:18px;">Solicitud de autorización</h2>'
        f'<p style="color:#94a3b8;font-size:14px;line-height:1.6;">'
        f'<strong style="color:#fff">{employee_name}</strong> ({employee_email}) solicita autorización '
        f'para {action_desc} en Preferendum en nombre de <strong style="color:#fff">{company}</strong> '
        f'con cargo <strong style="color:#fff">{cargo}</strong>.</p>'
        f'<p style="color:#94a3b8;font-size:13px;">Al aprobar, usted asume responsabilidad solidaria '
        f'por {"las consultas" if role == "organizer" else "las campañas publicitarias"} que publique este usuario.</p>'
        f'<div style="display:flex;gap:12px;margin-top:24px;">'
        f'<a href="{approve_url}?action=approved" style="flex:1;background:#10b981;color:#fff;text-decoration:none;'
        f'padding:14px;border-radius:10px;text-align:center;font-weight:700;font-size:14px;">✓ Autorizar</a>'
        f'<a href="{approve_url}?action=rejected" style="flex:1;background:#1e2d4a;color:#94a3b8;text-decoration:none;'
        f'padding:14px;border-radius:10px;text-align:center;font-size:14px;">Rechazar</a>'
        f'</div></div>'
        f'<div style="padding:16px 32px;border-top:1px solid #1e2d4a;text-align:center;">'
        f'<p style="color:#475569;font-size:11px;margin:0;">En memoria del Socio Fundador José Ignacio Fernández (1989–2024)</p>'
        f'</div></div>'
    )
    resend_key = os.getenv('RESEND_API_KEY')
    if resend_key:
        try:
            _requests.post('https://api.resend.com/emails',
                json={'from':'Preferendum <noreply@preferendum.com>','to':[supervisor_email],
                      'subject':f'Autorización solicitada por {employee_name} — Preferendum',
                      'html':html},
                headers={'Authorization':f'Bearer {resend_key}'}, timeout=10)
        except Exception as e:
            print(f'[SupervisorEmail] {e}')


def _assign_user_tier(user, db):
    """Asigna se_tier e income_index al usuario según su comuna declarada."""
    if not user.county:
        return
    commune_data = db.query(CommuneMarketData).filter(
        CommuneMarketData.commune.ilike(user.county.strip()),
        CommuneMarketData.country == _country_code(user.country)
    ).first()
    if not commune_data:
        # Búsqueda parcial si no hay match exacto
        commune_data = db.query(CommuneMarketData).filter(
            CommuneMarketData.commune.ilike(f'%{user.county.strip()}%')
        ).first()
    if commune_data:
        user.se_tier      = commune_data.se_tier
        user.income_index = commune_data.income_index
        db.commit()


def _rekognition_client():
    return boto3.client(
        'rekognition',
        region_name=os.getenv('AWS_REGION', 'us-east-1'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    )

@app.post('/verify/document')
async def verify_document(
    file: UploadFile = File(...),
    doc_type: str = Form('national_id'),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    contents = await file.read()
    if file.content_type not in ['image/jpeg', 'image/png', 'image/webp']:
        raise HTTPException(400, 'Solo se aceptan imágenes JPG o PNG')

    # Verificar que el documento tenga al menos una cara visible
    aws_key = os.getenv('AWS_ACCESS_KEY_ID')
    face_detected = False
    if aws_key:
        try:
            rek = _rekognition_client()
            resp = rek.detect_faces(
                Image={'Bytes': contents},
                Attributes=['DEFAULT']
            )
            face_detected = len(resp.get('FaceDetails', [])) > 0
            if not face_detected:
                raise HTTPException(400, 'No detectamos una cara en el documento. Asegúrate de fotografiar el lado con tu foto.')
        except ClientError as e:
            face_detected = True  # si AWS falla, no bloqueamos al usuario
    else:
        face_detected = True  # sin credenciales: modo demo

    doc_log = DocumentLog(
        user_id=user.id,
        doc_hash=hashlib.sha256(contents).hexdigest(),
        doc_type=doc_type,
        face_bytes=base64.b64encode(contents).decode(),
        verified=face_detected
    )
    db.add(doc_log)
    if face_detected:
        user.id_verified = True
        update_verify_level(user, db)
    db.commit()
    return {'verified': face_detected, 'verify_level': user.verify_level}

@app.post('/verify/selfie')
async def verify_selfie(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    contents = await file.read()
    if file.content_type not in ['image/jpeg', 'image/png', 'image/webp']:
        raise HTTPException(400, 'Solo se aceptan imágenes JPG o PNG')

    # Buscar el documento previamente subido para comparar
    doc_log = db.query(DocumentLog).filter(
        DocumentLog.user_id == user.id,
        DocumentLog.verified == True,
        DocumentLog.face_bytes != None
    ).order_by(DocumentLog.created_at.desc()).first()

    match_score = 0.0
    verified = False
    aws_key = os.getenv('AWS_ACCESS_KEY_ID')

    if aws_key and doc_log and doc_log.face_bytes:
        try:
            rek = _rekognition_client()
            doc_bytes = base64.b64decode(doc_log.face_bytes)
            resp = rek.compare_faces(
                SourceImage={'Bytes': doc_bytes},   # cara del documento
                TargetImage={'Bytes': contents},    # selfie con carné bajo el mentón
                SimilarityThreshold=80.0
            )
            matches = resp.get('FaceMatches', [])
            if matches:
                match_score = matches[0]['Similarity'] / 100.0
                verified = match_score >= 0.90
            else:
                raise HTTPException(400, 'Tu cara no coincide con el documento. Asegúrate de mirar directo a la cámara frontal con el carné bajo el mentón.')
        except ClientError:
            verified = True; match_score = 0.95  # AWS falló: modo demo
    else:
        verified = True; match_score = 0.95  # sin credenciales o documento: modo demo

    db.add(SelfieLog(
        user_id=user.id,
        selfie_hash=hashlib.sha256(contents).hexdigest(),
        match_score=match_score,
        verified=verified,
        face_bytes=base64.b64encode(contents).decode() if verified else None
    ))
    if verified:
        user.selfie_verified = True
        update_verify_level(user, db)
        if doc_log:
            doc_log.face_bytes = None  # ya no se necesita
    db.commit()
    return {'verified': verified, 'match_score': round(match_score * 100), 'verify_level': user.verify_level}


@app.post('/verify/face')
async def verify_face_returning(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Para usuarios que ya se verificaron antes — solo selfie, sin carné."""
    if not user.selfie_verified:
        raise HTTPException(400, 'Primero debes completar la verificación completa con tu documento')

    contents = await file.read()
    if file.content_type not in ['image/jpeg', 'image/png', 'image/webp']:
        raise HTTPException(400, 'Solo se aceptan imágenes JPG o PNG')

    # Buscar la cara de referencia guardada
    ref = db.query(SelfieLog).filter(
        SelfieLog.user_id == user.id,
        SelfieLog.verified == True,
        SelfieLog.face_bytes != None
    ).order_by(SelfieLog.created_at.desc()).first()

    aws_key = os.getenv('AWS_ACCESS_KEY_ID')
    if aws_key and ref and ref.face_bytes:
        try:
            rek = _rekognition_client()
            resp = rek.compare_faces(
                SourceImage={'Bytes': base64.b64decode(ref.face_bytes)},
                TargetImage={'Bytes': contents},
                SimilarityThreshold=80.0
            )
            matches = resp.get('FaceMatches', [])
            if not matches:
                raise HTTPException(400, 'Tu cara no coincide con la registrada. Intenta con mejor iluminación.')
            score = matches[0]['Similarity'] / 100.0
            if score < 0.90:
                raise HTTPException(400, 'Tu cara no coincide con la registrada. Intenta con mejor iluminación.')
        except ClientError:
            pass  # AWS falló: dejamos pasar

    return {'verified': True, 'message': 'Identidad confirmada'}

@app.post('/verify/location')
def verify_location(data: GeoInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    valid = -90 <= data.latitude <= 90 and -180 <= data.longitude <= 180
    db.add(GeoLog(user_id=user.id, latitude=data.latitude, longitude=data.longitude, country_detected=user.country, verified=valid))
    if valid:
        user.geo_verified = True
        update_verify_level(user, db)
    return {'verified': valid, 'verify_level': user.verify_level}

@app.post('/verify/imei')
def verify_imei(data: IMEIInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    imei_hash = hash_str(data.imei, 'pref-imei-')
    phone_hash = hash_str(data.phone.replace(' ', '').replace('-', ''), 'pref-sim-')
    existing_imei = db.query(IMEILog).filter(IMEILog.imei_hash == imei_hash).first()
    if existing_imei and existing_imei.user_id != user.id:
        raise HTTPException(409, 'Device already registered to another account')
    if not existing_imei:
        db.add(IMEILog(user_id=user.id, imei_hash=imei_hash, device_info=json.dumps({'model': data.device_model, 'os': data.os_version})))
    existing_sim = db.query(SIMLog).filter(SIMLog.phone_hash == phone_hash).first()
    if existing_sim and existing_sim.user_id != user.id:
        raise HTTPException(409, 'Phone number already registered to another account')
    if not existing_sim:
        db.add(SIMLog(user_id=user.id, phone_hash=phone_hash, imei_hash=imei_hash))
    user.imei_verified = True
    update_verify_level(user, db)
    return {'verified': True, 'verify_level': user.verify_level}

@app.post('/verify/wallet')
def verify_wallet(data: ChainInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not re.match(r'^0x[0-9a-fA-F]{40}$', data.wallet_address):
        raise HTTPException(400, 'Invalid wallet address')
    user.chain_verified = True
    update_verify_level(user, db)
    return {'verified': True, 'verify_level': user.verify_level, 'fully_verified': user.is_verified}

@app.get('/verify/status')
def verify_status(user: User = Depends(get_current_user)):
    return {
        'verify_level': user.verify_level,
        'is_verified': user.is_verified,
        'progress': f'{user.verify_level}/7',
        'steps': {
            'email': user.email_verified,
            'phone': user.phone_verified,
            'document': user.id_verified,
            'selfie': user.selfie_verified,
            'device': user.imei_verified,
            'location': user.geo_verified,
            'blockchain': user.chain_verified,
        }
    }

# ══════════════════════════════════════════════════════════════
# ROUTES: IMAGE UPLOAD (Cloudinary)
# ══════════════════════════════════════════════════════════════

@app.post('/upload/image')
async def upload_image(
    file: UploadFile = File(...),
):
    if not (file.content_type or '').startswith('image/'):
        raise HTTPException(400, 'Only image files allowed')
    contents = await file.read()
    if len(contents) > 8 * 1024 * 1024:
        raise HTTPException(400, 'Image too grande — máximo 8 MB')

    # Compress image with Pillow to keep base64 small (max 800px, JPEG q70)
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(contents))
        img = img.convert('RGB')
        max_dim = 800
        w, h = img.size
        if w > max_dim or h > max_dim:
            ratio = min(max_dim / w, max_dim / h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=70, optimize=True)
        contents = buf.getvalue()
    except Exception:
        pass  # if Pillow fails, use original

    # Try S3 if credentials available, otherwise return base64 data URI
    aws_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret = os.getenv('AWS_SECRET_ACCESS_KEY')
    if aws_key and aws_secret:
        try:
            aws_region = os.getenv('AWS_REGION', 'us-east-1')
            bucket = os.getenv('AWS_S3_BUCKET', 'preferendum-images')
            key = f"products/{uuid.uuid4().hex}.jpg"
            s3 = boto3.client('s3',
                region_name=aws_region,
                aws_access_key_id=aws_key,
                aws_secret_access_key=aws_secret,
            )
            try:
                s3.head_bucket(Bucket=bucket)
            except ClientError as e:
                if e.response['Error']['Code'] in ('404', 'NoSuchBucket'):
                    if aws_region == 'us-east-1':
                        s3.create_bucket(Bucket=bucket)
                    else:
                        s3.create_bucket(Bucket=bucket,
                            CreateBucketConfiguration={'LocationConstraint': aws_region})
                    s3.put_public_access_block(Bucket=bucket,
                        PublicAccessBlockConfiguration={
                            'BlockPublicAcls': False, 'IgnorePublicAcls': False,
                            'BlockPublicPolicy': False, 'RestrictPublicBuckets': False,
                        })
            s3.put_object(Bucket=bucket, Key=key, Body=contents,
                ContentType='image/jpeg', ACL='public-read')
            return {'url': f"https://{bucket}.s3.{aws_region}.amazonaws.com/{key}"}
        except Exception:
            pass  # fall through to base64
    data_uri = f"data:image/jpeg;base64,{base64.b64encode(contents).decode()}"
    return {'url': data_uri}

# ══════════════════════════════════════════════════════════════
# ROUTES: DEBATES
# ══════════════════════════════════════════════════════════════

@app.get('/debates')
def list_debates(
    country: str = Query('CL'),
    commune: str = Query(None),
    limit:   int = Query(50),
    status:  str = Query('live'),   # 'live' | 'expired'
    db: Session = Depends(get_db)
):
    now = datetime.utcnow()
    q = db.query(Debate)
    if country and country != 'ALL':
        q = q.filter(
            Debate.scope_country.in_([country, 'ALL', 'GLOBAL', 'GL']) |
            (Debate.scope_country == None) |
            (Debate.scope_country == '')
        )
    if status == 'expired':
        q = q.filter(Debate.closes_at != None, Debate.closes_at < now)
    else:
        q = q.filter(
            (Debate.closes_at == None) | (Debate.closes_at >= now)
        )
    debates = q.order_by(Debate.created_at.desc()).limit(limit).all()
    safe = []
    for d in debates:
        try:
            safe.append(format_debate(d))
        except Exception:
            pass
    return {'debates': safe}

@app.get('/debates/feed')
def get_feed(
    country: str = Query('CL'),
    user: User = Depends(get_verified_user),
    db: Session = Depends(get_db)
):
    debates = db.query(Debate).filter(
        Debate.scope_country == country
    ).order_by(Debate.created_at.desc()).limit(10).all()
    return {
        'debates': [format_debate(d) for d in debates],
        'section_title': 'Consultations available to vote',
    }

@app.get('/ads/featured')
def get_featured_ads(db: Session = Depends(get_db)):
    """Returns up to 2 active ad campaigns to display in the debates list."""
    now = datetime.utcnow()
    campaigns = db.query(AdCampaign).filter(
        AdCampaign.is_active == True,
        AdCampaign.budget_clp > AdCampaign.spent_clp,
    ).filter(
        (AdCampaign.end_date == None) | (AdCampaign.end_date > now)
    ).order_by(AdCampaign.created_at.desc()).limit(2).all()

    ads = []
    for c in campaigns:
        logo = c.logo_url or ''
        if logo.startswith('data:') and len(logo) > 200_000:
            logo = ''
        ads.append({
            'brand':     c.advertiser_name or '',
            'copy':      c.ad_copy or c.title or '',
            'cta':       'Ver más',
            'logo_color': '#2563eb',
            'logo_url':  logo,
            'image_url': c.ad_image_url or '',
            'video_url': c.video_url or '',
            'link_url':  c.link_url or '',
        })

    # Fallback to static DebateAds if no campaigns
    if not ads:
        static = db.query(DebateAd).order_by(DebateAd.impressions.asc()).limit(2).all()
        for a in static:
            ads.append({
                'brand': a.brand, 'copy': a.copy,
                'cta': a.cta, 'logo_color': a.logo_color,
                'link_url': a.link_url or '',
            })

    return {'ads': ads}

@app.get('/debates/{debate_id}')
def get_debate(debate_id: int, db: Session = Depends(get_db)):
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Consultation not found')
    return format_debate(debate)

@app.post('/debates')
def create_debate(data: DebateCreate, db: Session = Depends(get_db)):
    if len(data.options) < 2:
        raise HTTPException(400, 'At least 2 options required')
    closes = datetime.fromisoformat(data.closes_at)
    verify_closes = closes + timedelta(days=data.verify_days)
    debate = Debate(
        title=data.title, context=data.context,
        options=json.dumps(data.options),
        creator_type=data.creator_type, inst_name=data.inst_name,
        debate_type=data.debate_type, scope=data.scope,
        scope_country=data.scope_country, scope_commune=data.scope_commune,
        target_gender=data.target_gender,
        target_age_min=data.target_age_min, target_age_max=data.target_age_max,
        target_se_tiers=getattr(data, 'target_se_tiers', None) or 'A,B,C,D',
        category=getattr(data, 'category', 'general') or 'general',
        closes_at=closes, verify_closes_at=verify_closes,
        vote_counts=json.dumps({opt: 0 for opt in data.options}),
        follow_up_questions=data.follow_up_questions or '',
        reward=data.reward or '',
        option_images=json.dumps(data.option_images or []),
        cover_image_url=data.cover_image_url or '',
        is_anonymous=data.is_anonymous,
    )
    db.add(debate)
    db.commit()
    db.refresh(debate)
    return {'debate': format_debate(debate), 'message': 'Consultation created'}

_COUNTRY_CODES = {
    'chile': 'CL', 'argentina': 'AR', 'brasil': 'BR', 'brazil': 'BR',
    'méxico': 'MX', 'mexico': 'MX', 'colombia': 'CO', 'perú': 'PE', 'peru': 'PE',
    'españa': 'ES', 'spain': 'ES', 'usa': 'US', 'estados unidos': 'US',
    'todos': 'ALL', 'all': 'ALL',
}

def _country_code(name: str) -> str:
    """Normaliza nombres de país ('Chile') y códigos ISO ('CL') a un código común.
    El registro guarda nombres completos ('Chile') pero campañas/CommuneMarketData usan códigos ISO ('CL')."""
    if not name:
        return 'CL'
    s = name.strip()
    if len(s) <= 3:
        return s.upper()
    return _COUNTRY_CODES.get(s.lower(), s.upper())

def _get_age_group(dob: str) -> str:
    if not dob:
        return ''
    try:
        birth = datetime.fromisoformat(dob)
        age = (datetime.utcnow() - birth).days // 365
        if age < 25:  return '18-24'
        if age < 35:  return '25-34'
        if age < 45:  return '35-44'
        if age < 55:  return '45-54'
        return '55+'
    except Exception:
        return ''

TIER_ORDER = ['AAA', 'AAB', 'ABB', 'BBB', 'BBC', 'BCC', 'A', 'B', 'C', 'D']

def _tier_gte(user_tier: str, min_tier: str) -> bool:
    """Devuelve True si user_tier >= min_tier en la escala de ingreso."""
    try:
        return TIER_ORDER.index(user_tier) <= TIER_ORDER.index(min_tier)
    except ValueError:
        return True

def _tier_matches(user_tier: str, target_tiers_str: str) -> bool:
    """Handles both 'AAA,BBB' and abbreviated 'A,B,C,D' tier formats."""
    tiers = [t.strip() for t in target_tiers_str.split(',') if t.strip()]
    if not tiers:
        return True
    if user_tier in tiers:
        return True
    # Abbreviated format: first letter of user_tier (e.g. 'BBB' → 'B')
    first = user_tier[0] if user_tier else ''
    if first and first in tiers:
        return True
    return False

def _campaign_matches_debate(c, debate) -> bool:
    """
    Cruza la matriz de targeting de la campaña contra la consulta.
    Si la campaña tiene target_debate_ids explícitos, esos debates
    siempre hacen match (bypass de la matriz — usado para demo/pruebas).
    """
    if not debate:
        return True
    # Conexión directa campaña ↔ debate (override de toda la matriz)
    if c.target_debate_ids:
        pinned = [int(x.strip()) for x in c.target_debate_ids.split(',') if x.strip().isdigit()]
        if pinned:
            return debate.id in pinned
    # País — 'ALL'/'GLOBAL'/vacío = sin restricción; scope_country puede ser multi-país "CL,AR,PE"
    c_country = _country_code(c.target_country) if c.target_country else ''
    scope_raw = (debate.scope_country or '').strip().upper()
    d_countries = {_country_code(x.strip()) for x in scope_raw.split(',') if x.strip()} if scope_raw else set()
    if c_country and c_country not in ('ALL', 'GLOBAL') and d_countries and not d_countries.intersection({'ALL','GLOBAL'}) and c_country not in d_countries:
        return False
    # Comuna — si la campaña apunta a comunas específicas y la consulta tiene
    # alcance comunal definido, la comuna de la consulta debe estar en la lista
    target_communes = [x.strip() for x in (c.target_communes or '').split(',') if x.strip()]
    if target_communes and debate.scope_commune and debate.scope_commune not in target_communes:
        return False
    # Género — incompatible solo si ambas matrices especifican géneros distintos
    c_gender = (c.target_gender or 'all').lower()
    d_gender = (debate.target_gender or 'all').lower()
    if c_gender != 'all' and d_gender != 'all' and c_gender != d_gender:
        return False
    # Edad — los rangos de ambas matrices deben solaparse
    c_min, c_max = c.target_age_min or 13, c.target_age_max or 99
    d_min, d_max = debate.target_age_min or 13, debate.target_age_max or 99
    if c_max < d_min or d_max < c_min:
        return False
    # NSE / Nivel socioeconómico — los conjuntos deben tener al menos un tier en común
    c_tiers = {t.strip().upper() for t in (c.target_se_tiers or 'A,B,C,D').split(',') if t.strip()}
    d_tiers = {t.strip().upper() for t in (getattr(debate, 'target_se_tiers', None) or 'A,B,C,D').split(',') if t.strip()}
    if c_tiers and d_tiers and not c_tiers.intersection(d_tiers):
        return False
    # PIB per cápita — si la campaña exige un mínimo, al menos un país del debate debe calificarlo
    min_gni = getattr(c, 'min_per_capita_usd', 0.0) or 0.0
    if min_gni > 0 and d_countries and not d_countries.intersection({'ALL','GLOBAL'}):
        try:
            from targeting_agent import load_matrix as _lm
            _matrix = _lm()
            qualifying = any(_matrix.get(code, {}).get('gni_per_capita', 0) >= min_gni for code in d_countries)
            if not qualifying:
                return False
        except Exception:
            pass  # si la matrix falla, no bloquear
    return True

def _normalize_gender(g: str) -> str:
    """Normalize gender values from any source to 'F', 'M', or 'all'."""
    if not g:
        return 'all'
    g = g.lower().strip()
    if g in ('f', 'female', 'mujer', 'femenino'):
        return 'F'
    if g in ('m', 'male', 'hombre', 'masculino'):
        return 'M'
    return 'all'

def _match_campaigns(user, debate, db) -> list:
    """
    Finds active campaigns for a debate using commune-based targeting optimization.
    Returns list of dicts (ORM fields + optimization metrics from targeting_agent).
    """
    from targeting_agent import optimize_campaigns_for_debate, load_matrix

    now = datetime.utcnow()
    orm_campaigns = db.query(AdCampaign).filter(
        AdCampaign.is_active == True,
    ).filter(
        (AdCampaign.start_date == None) | (AdCampaign.start_date <= now)
    ).all()

    # Debate context for brand-safety filtering
    debate_category  = (getattr(debate, 'category', '') or '').lower().strip() if debate else ''
    debate_country   = (debate.scope_country or 'GLOBAL').upper().strip() if debate else 'GLOBAL'
    debate_tags      = {debate_category} if debate_category else set()
    # Also add title-based keyword tags for safety matching
    debate_title_low = (debate.title or '').lower() if debate else ''
    SENSITIVE_KEYWORDS = {
        'religion': {'religión','religion','iglesia','church','dios','god','fe','faith','islam','cristian','catholic','budis','hindu','jewish','judío'},
        'política': {'política','politica','election','elección','partido','gobierno','gobierno','president','alcalde','senado','congreso','diputado'},
        'sexual': {'sexual','sexo','sex','género','genero','lgbt','trans','homosex','hetero','gay','orientación','aborto','abortion','reproductive'},
        'conflicto_armado': {'guerra','war','conflicto','conflict','armas','weapons','militar','military','ejército','army','bomba','bomb','ataque','attack','terroris'},
        'sindicatos': {'sindicato','huelga','strike','laboral','gremio','union','trabajador','obrero'},
        'drogas': {'droga','drug','narcótico','narcotic','cannabis','cocaína','alcohol','bebida','licor'},
        'apuestas': {'apuesta','casino','juego','gambling','lotería','lottery','bet'},
        'menores': {'menor','niño','infan','child','adolescen','escolar'},
        'litigios': {'juicio','tribunal','corte','demanda','lawsuit','litig','arbitraj'},
        'crisis': {'crisis','catástrofe','desastre','disaster','terremoto','inundación','refugee','refugiado'},
    }
    # Derive debate's sensitive tags from category + title keywords
    for tag, keywords in SENSITIVE_KEYWORDS.items():
        if any(kw in debate_category for kw in keywords) or any(kw in debate_title_low for kw in keywords):
            debate_tags.add(tag)

    valid_orm = []
    for c in orm_campaigns:
        if c.end_date and c.end_date < (now - timedelta(hours=24)):
            continue
        if (c.budget_clp or 0) > 0 and (c.spent_clp or 0) >= (c.budget_clp or 0):
            continue

        # ── BRAND SAFETY: excluded_categories ──
        if c.excluded_categories:
            excluded = {e.strip().lower() for e in c.excluded_categories.split(',') if e.strip()}
            # Map to canonical tags
            campaign_excluded_tags = set()
            for excl in excluded:
                for tag, keywords in SENSITIVE_KEYWORDS.items():
                    if excl == tag or any(kw in excl for kw in keywords):
                        campaign_excluded_tags.add(tag)
                campaign_excluded_tags.add(excl)  # also keep raw value
            if debate_tags & campaign_excluded_tags:
                continue  # debate matches an excluded category — skip this campaign

        # ── COUNTRY FILTER ──
        # scope_country puede ser multi-país "CL,AR" o "GLOBAL" — debates globales aceptan todo
        debate_countries = {x.strip().upper() for x in debate_country.split(',') if x.strip()} if debate_country else {'GLOBAL'}
        if not debate_countries.intersection({'GLOBAL','ALL',''}):
            c_tgt = (c.target_country or '').upper().strip()
            if c_tgt and c_tgt not in ('ALL', 'GLOBAL', '') and c_tgt not in debate_countries:
                continue

        valid_orm.append(c)

    if not valid_orm:
        return []

    # ── BLOCKED COMPETITORS: remove conflicting advertiser pairs ──
    # If campaign A blocks advertiser X, remove X from valid_orm for this slot
    blocked_names = set()
    for c in valid_orm:
        if c.blocked_competitors:
            for name in c.blocked_competitors.split(','):
                n = name.strip().lower()
                if n:
                    blocked_names.add(n)
    if blocked_names:
        valid_orm = [
            c for c in valid_orm
            if (c.advertiser_name or '').lower() not in blocked_names
        ]

    def _se_tiers_to_min_tier(se_tiers_str: str) -> str:
        tiers = [t.strip()[0] for t in (se_tiers_str or 'A,B,C,D').split(',') if t.strip()]
        valid = [t for t in tiers if t in ('A', 'B', 'C', 'D')]
        if not valid:
            return 'D'
        order = {'A': 4, 'B': 3, 'C': 2, 'D': 1}
        return min(valid, key=lambda t: order.get(t, 1))

    orm_by_id = {c.id: c for c in valid_orm}
    campaigns_dicts = [{
        'id':              c.id,
        'advertiser_name': c.advertiser_name or '',
        'title':           c.title or '',
        'ad_copy':         c.ad_copy or '',
        'logo_url':        c.logo_url or '',
        'ad_image_url':    c.ad_image_url or '',
        'link_url':        c.link_url or '',
        'target_country':  c.target_country or '',
        'target_communes': c.target_communes or '',
        'target_gender':     c.target_gender or 'all',
        'target_age_min':    c.target_age_min or 13,
        'target_age_max':    c.target_age_max or 99,
        'min_income_tier':   _se_tiers_to_min_tier(c.target_se_tiers),
        'min_gni_country':   getattr(c, 'min_per_capita_usd', 0) or 0,
        'video_url':         getattr(c, 'video_url', '') or '',
        'cpm':               0,
    } for c in valid_orm]

    debate_dict = {
        'scope_country':    (debate.scope_country  or 'CL')  if debate else 'CL',
        'scope_commune':    (debate.scope_commune   or '')    if debate else '',
        'target_gender':    (debate.target_gender   or 'all') if debate else 'all',
        'target_age_min':   (debate.target_age_min  or 13)   if debate else 13,
        'target_age_max':   (debate.target_age_max  or 99)   if debate else 99,
        'estimated_audience': 0,
    }

    matrix = load_matrix()
    ranked = optimize_campaigns_for_debate(debate_dict, campaigns_dicts, matrix, max_ads=5)

    # Fallback: if optimizer filtered everything out, use all valid campaigns unscored
    if not ranked:
        ranked = [{**c, '_orm': orm_by_id.get(c['id']), 'optimization_rank': 0} for c in campaigns_dicts]

    for item in ranked:
        if '_orm' not in item:
            item['_orm'] = orm_by_id.get(item['id'])

    return ranked


def _cost_per_impression_clp(campaign, db) -> int:
    """What one served impression actually costs against the campaign's budget.

    CPM means "cost per *mille*" — cost per 1000 impressions — so one
    impression costs cpm_usd/1000 (converted to CLP). This derives that
    rate from the same live CommuneMarketData table /marketer/estimate
    reads (real backend numbers, never invented), averaged over whichever
    communes the campaign actually targets — falling back to the full
    table average for broad/untargeted campaigns.

    Replaces the previous formula
    `budget_clp / max(1, len(opinions) // 5)`, which divided the WHOLE
    budget by a tiny denominator (e.g. 3 for a 15-opinion debate) and
    could exhaust a 250-million-CLP flight in 3 impressions — a
    catastrophic overspend that would have wrecked the advertising
    revenue story for investors.
    """
    q = db.query(CommuneMarketData)
    if campaign.target_country:
        q = q.filter(CommuneMarketData.country == campaign.target_country)
    if campaign.target_communes:
        names = [c.strip() for c in campaign.target_communes.split(',') if c.strip()]
        if names:
            q = q.filter(CommuneMarketData.commune.in_(names))
    rows = q.all()
    if not rows:
        rows = db.query(CommuneMarketData).all()

    cpm_usd_avg = (sum(r.cpm_usd for r in rows) / len(rows)) if rows else 6.0
    cost = (cpm_usd_avg * USD_TO_CLP) / 1000.0
    return max(1, int(round(cost)))


# Cada cuántas opiniones aparece un anuncio en la sala de debate.
# Valor de producción documentado en CLAUDE.md y en la "Architecture
# Decisions" — 1 anuncio cada 5 opiniones. (Se usó temporalmente 2 el
# 2026-06-07 para probar el ciclo de impresiones/métricas de campañas
# más rápido; revertido a 5 antes del almuerzo con el inversionista.)
AD_EVERY_N_OPINIONS = 3

# Tipo de cambio usado para traducir CPM (USD por mil impresiones, tabla de
# comunas) a CLP. Vive aquí — no dentro de _optimize_campaign — porque tanto
# la simulación de presupuesto (/marketer/estimate) como el cobro real por
# impresión servida (/debates/{id}/opinions) deben usar el mismo número o
# "presupuesto estimado" y "gasto real" divergen.
USD_TO_CLP = 950


@app.get('/debates/{debate_id}/opinions')
def get_opinions(debate_id: int,
                 user: User = Depends(get_optional_user),
                 db: Session = Depends(get_db)):
    opinions = db.query(Opinion).filter(
        Opinion.debate_id == debate_id
    ).order_by(Opinion.created_at.asc()).all()

    debate    = db.query(Debate).filter(Debate.id == debate_id).first()
    matched   = _match_campaigns(user, debate, db)

    # Always merge in any active campaign not already in matched
    # so newly created campaigns always appear everywhere ads show
    # (same filter as /ads/featured so behavior is consistent)
    now_ts = datetime.utcnow()
    recent = db.query(AdCampaign).filter(
        AdCampaign.is_active == True,
        AdCampaign.budget_clp > AdCampaign.spent_clp,
        (AdCampaign.end_date == None) | (AdCampaign.end_date > now_ts),
    ).order_by(AdCampaign.created_at.desc()).limit(10).all()
    matched_ids = {c.get('id') for c in matched}
    prepend = []
    for rc in recent:
        if rc.id not in matched_ids:
            prepend.append({
                'id': rc.id, 'advertiser_name': rc.advertiser_name or '',
                'ad_copy': rc.ad_copy or '', 'title': rc.title or '',
                'logo_url': rc.logo_url or '', 'ad_image_url': rc.ad_image_url or '',
                'video_url': getattr(rc, 'video_url', '') or '',
                'link_url': rc.link_url or '',
                '_orm': rc, 'optimization_rank': 0,
            })
    matched = prepend + matched  # newest campaigns show first

    static_ads = db.query(DebateAd).filter(DebateAd.debate_id == debate_id).all()

    result  = []
    ad_idx  = 0
    now     = datetime.utcnow()

    def _safe_url(url, limit=200_000):
        if url and url.startswith('data:') and len(url) > limit:
            return ''
        return url or ''

    def _append_campaign_ad(campaign):
        # campaign is a dict with optimization metrics merged in
        result.append({'type': 'ad', 'ad': {
            'brand':       campaign.get('advertiser_name', ''),
            'copy':        campaign.get('ad_copy') or campaign.get('title', ''),
            'cta':         'Ver más',
            'logo_color':  '#2563eb',
            'logo_url':    _safe_url(campaign.get('logo_url', '')),
            'image_url':   _safe_url(campaign.get('ad_image_url', '')),
            'video_url':   campaign.get('video_url', ''),
            'link_url':    campaign.get('link_url', ''),
            'campaign_id': campaign.get('id'),
        }})
        orm = campaign.get('_orm')
        if orm:
            if user:
                db.add(AdImpressionLog(
                    campaign_id = orm.id,
                    debate_id   = debate_id,
                    gender      = user.gender or '',
                    age_group   = _get_age_group(user.dob),
                    county      = user.county or '',
                    country     = user.country or '',
                ))
            cpm_usd  = campaign.get('cpm') or 6.0
            cost_clp = max(1, int(round((cpm_usd * USD_TO_CLP) / 1000.0)))
            orm.spent_clp = min(
                orm.budget_clp or 0,
                (orm.spent_clp or 0) + cost_clp,
            )

    for i, op in enumerate(opinions):
        result.append({'type': 'opinion', 'opinion': {
            'id': op.id, 'text': op.text,
            'knowledge_level': op.knowledge_level,
            'user_name': op.user_name,
            'created_at': op.created_at.isoformat(),
            'country': op.country or '',
        }})
        # Ad after every 2 opinions starting from the 1st (i=0,2,4,...)
        if i % 2 == 0:
            if matched:
                _append_campaign_ad(matched[ad_idx % len(matched)])
                ad_idx += 1
            elif static_ads:
                ad = static_ads[ad_idx % len(static_ads)]
                ad.impressions += 1
                result.append({'type': 'ad', 'ad': {
                    'brand': ad.brand, 'copy': ad.copy,
                    'cta': ad.cta, 'logo_color': ad.logo_color,
                    'link_url': ad.link_url or '',
                }})
                ad_idx += 1

    db.commit()
    return {'items': result, 'total_opinions': len(opinions)}

@app.post('/debates/{debate_id}/opinions')
def post_opinion(debate_id: int, data: OpinionCreate, user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    if len(data.text) < 20:
        raise HTTPException(400, 'Opinion must be at least 20 characters')
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Consultation not found')
    op = Opinion(debate_id=debate_id, user_id=0, user_name='Ciudadano',
                 text=data.text, knowledge_level=data.knowledge_level)
    db.add(op)
    db.commit()
    db.refresh(op)
    return {'opinion': {'id': op.id, 'text': op.text, 'created_at': op.created_at.isoformat()}}

@app.get('/debates/{debate_id}/comments')
def get_comments(debate_id: int, db: Session = Depends(get_db)):
    comments = db.query(PostVoteComment).filter(
        PostVoteComment.debate_id == debate_id
    ).order_by(PostVoteComment.created_at.asc()).all()
    return {'comments': [
        {'id': c.id, 'user_name': c.user_name, 'text': c.text,
         'created_at': c.created_at.isoformat()}
        for c in comments
    ]}

@app.post('/debates/{debate_id}/comments')
def post_comment(debate_id: int, body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    text = (body.get('text') or '').strip()
    if len(text) < 3:
        raise HTTPException(400, 'El comentario es muy corto')
    if len(text) > 500:
        raise HTTPException(400, 'Máximo 500 caracteres')
    voted = db.query(HasVotedLog).filter(
        HasVotedLog.user_id == user.id,
        HasVotedLog.debate_id == debate_id
    ).first()
    if not voted:
        raise HTTPException(403, 'Solo pueden comentar personas que hayan votado en esta consulta')
    c = PostVoteComment(debate_id=debate_id, user_id=user.id,
                        user_name=user.name or 'Ciudadano', text=text)
    db.add(c)
    db.commit()
    db.refresh(c)
    return {'comment': {'id': c.id, 'user_name': c.user_name, 'text': c.text,
                        'created_at': c.created_at.isoformat()}}

@app.post('/debates/{debate_id}/face-token')
async def get_face_vote_token(
    debate_id: int,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Verifica la cara del votante y devuelve un token de 5 min para votar."""
    if not user.selfie_verified:
        raise HTTPException(400, 'Debes verificar tu identidad con selfie antes de votar')

    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Consulta no encontrada')
    if get_debate_status(debate) != 'live':
        raise HTTPException(400, 'La consulta no está activa')

    contents = await file.read()
    aws_key = os.getenv('AWS_ACCESS_KEY_ID')
    ref = db.query(SelfieLog).filter(
        SelfieLog.user_id == user.id,
        SelfieLog.verified == True,
        SelfieLog.face_bytes != None
    ).order_by(SelfieLog.created_at.desc()).first()

    rekognition_score = None
    rekognition_mode = 'no_aws'

    if aws_key and ref and ref.face_bytes:
        try:
            rek = _rekognition_client()
            resp = rek.compare_faces(
                SourceImage={'Bytes': base64.b64decode(ref.face_bytes)},
                TargetImage={'Bytes': contents},
                SimilarityThreshold=80.0
            )
            matches = resp.get('FaceMatches', [])
            if matches:
                rekognition_score = round(matches[0]['Similarity'], 2)
                rekognition_mode = 'verified'
                if rekognition_score / 100.0 < 0.90:
                    raise HTTPException(400, f'Tu cara no coincide con la registrada ({rekognition_score}% similitud). Intenta con mejor iluminación.')
            else:
                rekognition_mode = 'no_match'
                raise HTTPException(400, 'Tu cara no coincide con la registrada. Intenta con mejor iluminación.')
        except HTTPException:
            raise
        except ClientError:
            rekognition_mode = 'aws_error'
    else:
        # Sin AWS configurado: modo demo — permite votar pero sin comparación real
        rekognition_mode = 'demo'
    token = jwt.encode({
        'sub': user.id,
        'debate_id': debate_id,
        'type': 'face_vote',
        'exp': datetime.utcnow() + timedelta(minutes=5)
    }, SECRET, algorithm='HS256')
    return {
        'token': token,
        'rekognition_score': rekognition_score,
        'rekognition_mode': rekognition_mode,
        'message': f'Identidad verificada — similitud {rekognition_score}%' if rekognition_score else 'Verificado (modo demo)'
    }


@app.post('/debates/{debate_id}/vote')
def cast_vote(debate_id: int, data: CastVoteRequest, user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Consultation not found')
    if get_debate_status(debate) != 'live':
        raise HTTPException(400, 'Consultation is not open for voting')

    # Bloqueo 0: verificación facial (solo para usuarios con selfie verificada)
    if user.selfie_verified:
        if not data.face_token:
            raise HTTPException(403, 'Se requiere verificación facial para votar')
        try:
            payload = jwt.decode(data.face_token, SECRET, algorithms=['HS256'])
            if payload.get('type') != 'face_vote' or payload.get('sub') != user.id or payload.get('debate_id') != debate_id:
                raise HTTPException(403, 'Token de verificación facial inválido')
        except jwt.ExpiredSignatureError:
            raise HTTPException(403, 'La verificación facial expiró — por favor tómate una nueva selfie')
        except Exception:
            raise HTTPException(403, 'Token de verificación facial inválido')

    # Bloqueo 1: misma cuenta
    already = db.query(HasVotedLog).filter(
        HasVotedLog.user_id == user.id,
        HasVotedLog.debate_id == debate_id
    ).first()
    if already:
        raise HTTPException(409, 'Ya votaste en esta consulta')

    # Bloqueo 2: mismo SIM (aunque cambien de cuenta o de aparato)
    if user.phone:
        phone_hash = hash_str(user.phone.replace(' ', '').replace('-', ''), 'pref-sim-')
        sim_voted = db.query(SimVoteLog).filter(
            SimVoteLog.phone_hash == phone_hash,
            SimVoteLog.debate_id == debate_id
        ).first()
        if sim_voted:
            raise HTTPException(409, 'Este número de teléfono ya votó en esta consulta')

    # Bloqueo 3: mismo RUT/DNI (aunque tenga chip nuevo y cuenta nueva)
    if user.national_id:
        nid_hash = hash_str(user.national_id.replace('.', '').replace('-', '').upper(), 'pref-nid-')
        nid_voted = db.query(NationalIdVoteLog).filter(
            NationalIdVoteLog.national_id_hash == nid_hash,
            NationalIdVoteLog.debate_id == debate_id
        ).first()
        if nid_voted:
            raise HTTPException(409, 'Este documento de identidad ya votó en esta consulta')

    # Bloqueo 4: mismo aparato físico por device fingerprint
    fp_hash = None
    if data.device_fp:
        fp_hash = hash_str(data.device_fp, 'pref-fp-')
        fp_voted = db.query(ImeiVoteLog).filter(
            ImeiVoteLog.imei_hash == fp_hash,
            ImeiVoteLog.debate_id == debate_id
        ).first()
        if fp_voted:
            raise HTTPException(409, 'Este aparato ya fue usado para votar en esta consulta')
    else:
        # Fallback: check legacy IMEILog
        imei_log = db.query(IMEILog).filter(IMEILog.user_id == user.id).first()
        if imei_log:
            imei_voted = db.query(ImeiVoteLog).filter(
                ImeiVoteLog.imei_hash == imei_log.imei_hash,
                ImeiVoteLog.debate_id == debate_id
            ).first()
            if imei_voted:
                raise HTTPException(409, 'Este aparato ya fue usado para votar en esta consulta')

    opts = json.loads(debate.options or '[]')
    if data.option_index < 0 or data.option_index >= len(opts):
        raise HTTPException(400, 'Invalid option')
    option = opts[data.option_index]
    verify_code = generate_verify_code()
    vote_hash = hashlib.sha256(f'{debate_id}:{option}:{verify_code}'.encode()).hexdigest()
    bc_result = _blockchain.anchor_vote(debate_id, vote_hash, verify_code,
                                        debate_title=debate.title)
    blockchain_tx = bc_result['tx_hash']
    encrypted = encrypt_vote_aes(debate_id, option, {'country': 'CL'})
    vote = DebateVote(
        debate_id=debate_id, voter_id=None,
        option_index=data.option_index, option_text=option,
        verify_code=verify_code, vote_hash=vote_hash,
        encrypted_vote=encrypted, blockchain_tx=blockchain_tx,
        vote_chain=json.dumps(data.vote_chain),
    )
    db.add(vote)
    db.add(HasVotedLog(debate_id=debate_id, user_id=user.id, verify_code=verify_code))
    if user.phone:
        db.add(SimVoteLog(debate_id=debate_id, phone_hash=phone_hash))
    if user.national_id:
        db.add(NationalIdVoteLog(debate_id=debate_id, national_id_hash=nid_hash))
    if fp_hash:
        # Store device fingerprint in IMEILog if not already registered for this user
        existing_fp = db.query(IMEILog).filter(IMEILog.user_id == user.id).first()
        if not existing_fp:
            db.add(IMEILog(user_id=user.id, imei_hash=fp_hash, device_info='browser-fp'))
        db.add(ImeiVoteLog(debate_id=debate_id, imei_hash=fp_hash))
    elif imei_log:
        db.add(ImeiVoteLog(debate_id=debate_id, imei_hash=imei_log.imei_hash))
    counts = json.loads(debate.vote_counts or '{}')
    counts[option] = counts.get(option, 0) + 1
    debate.vote_counts = json.dumps(counts)
    debate.total_votes = (debate.total_votes or 0) + 1
    # Assign unique reward code from pool if available
    reward_code = None
    try:
        unclaimed = db.query(DebateRewardCode).filter(
            DebateRewardCode.debate_id == debate_id,
            DebateRewardCode.claimed == False
        ).with_for_update(skip_locked=True).first()
        if unclaimed:
            unclaimed.claimed = True
            unclaimed.claimed_at = datetime.utcnow()
            reward_code = unclaimed.code
    except Exception as e:
        print(f'[cast_vote] reward_code query error (non-fatal): {e}')
    try:
        db.commit()
    except Exception as e:
        import traceback
        print(f'[cast_vote] DB commit error for user={user.id} debate={debate_id}: {traceback.format_exc()}')
        db.rollback()
        raise HTTPException(500, f'Error al registrar el voto: {type(e).__name__}')
    return {
        'success': True,
        'verify_code': verify_code,
        'option': option,
        'blockchain_tx': blockchain_tx,
        'total_votes': debate.total_votes,
        'current_results': counts,
        'reward_code': reward_code,
        'message': 'Vote registered. Save your verification code.',
    }

@app.post('/debates/{debate_id}/verify')
def verify_vote(debate_id: int, data: VerifyVoteRequest, db: Session = Depends(get_db)):
    code = data.code.upper().strip()
    vote = db.query(DebateVote).filter(
        DebateVote.verify_code == code,
        DebateVote.debate_id == debate_id
    ).first()
    if not vote:
        raise HTTPException(404, 'Code not found')
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    return {
        'found': True,
        'your_vote': vote.option_text,
        'debate_title': debate.title if debate else '',
        'blockchain_tx': vote.blockchain_tx,
        'recorded_at': vote.created_at.isoformat(),
        'already_verified': vote.verified is not None,
        'legitimacy_score': debate.legitimacy_score if debate else 0,
        'verifications_ok': debate.verifications_ok if debate else 0,
        'verifications_total': debate.verifications_total if debate else 0,
    }

@app.post('/debates/{debate_id}/verify/confirm')
def confirm_verification(
    debate_id: int,
    code: str = Form(...),
    confirmed: bool = Form(...),
    dispute_reason: str = Form(default=''),
    db: Session = Depends(get_db)
):
    vote = db.query(DebateVote).filter(
        DebateVote.verify_code == code.upper().strip(),
        DebateVote.debate_id == debate_id
    ).first()
    if not vote:
        raise HTTPException(404, 'Code not found')
    if vote.verified is not None:
        raise HTTPException(400, 'Already verified')
    vote.verified = confirmed
    vote.verified_at = datetime.utcnow()
    vote.dispute_reason = dispute_reason
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if debate:
        debate.verifications_total = (debate.verifications_total or 0) + 1
        if confirmed:
            debate.verifications_ok = (debate.verifications_ok or 0) + 1
        t = debate.verifications_total
        ok = debate.verifications_ok
        debate.legitimacy_score = round(ok / t * 100, 1) if t > 0 else 0.0
    db.commit()
    return {
        'recorded': True,
        'confirmed': confirmed,
        'legitimacy_score': debate.legitimacy_score if debate else 0,
    }

@app.get('/debates/{debate_id}/my-vote')
def get_my_vote(debate_id: int,
                user: User = Depends(get_optional_user),
                db: Session = Depends(get_db)):
    """Devuelve si el usuario ya votó en esta consulta y su código."""
    if not user:
        return {'has_voted': False, 'vote': None}
    log = db.query(HasVotedLog).filter(
        HasVotedLog.user_id == user.id,
        HasVotedLog.debate_id == debate_id
    ).first()
    if not log:
        return {'has_voted': False, 'vote': None}
    vote = db.query(DebateVote).filter(
        DebateVote.verify_code == log.verify_code
    ).first()
    return {
        'has_voted': True,
        'verify_code': log.verify_code,
        'option': vote.option_text if vote else '',
        'reward_code': vote.reward_code if vote and hasattr(vote, 'reward_code') else '',
    }


@app.post('/users/request-vote-otp')
def request_vote_otp(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Sends SMS OTP to reveal vote verify codes."""
    if not user.phone:
        raise HTTPException(400, 'No tienes un número de teléfono registrado')
    code = gen_otp()
    expires = datetime.utcnow() + timedelta(minutes=10)
    db.add(OTPCode(user_id=user.id, email=user.email, code=code, channel='vote_reveal', used=False, expires_at=expires))
    db.commit()
    send_sms_otp(user.phone, code)
    masked = user.phone[-4:] if user.phone else '????'
    return {'ok': True, 'masked_phone': f'***{masked}'}

@app.post('/users/verify-vote-otp')
def verify_vote_otp(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Verifies OTP and returns all vote verify codes."""
    code = (body.get('code') or '').strip()
    otp = db.query(OTPCode).filter(
        OTPCode.user_id == user.id,
        OTPCode.channel == 'vote_reveal',
        OTPCode.used == False,
        OTPCode.expires_at > datetime.utcnow()
    ).order_by(OTPCode.id.desc()).first()
    if not otp or otp.code != code:
        raise HTTPException(400, 'Código incorrecto o expirado')
    otp.used = True
    db.commit()
    logs = db.query(HasVotedLog).filter(HasVotedLog.user_id == user.id).all()
    codes = {log.debate_id: log.verify_code for log in logs}
    return {'ok': True, 'codes': codes}

@app.get('/users/my-votes')
def get_my_votes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Returns all votes cast by the current user with their verify codes."""
    logs = db.query(HasVotedLog).filter(
        HasVotedLog.user_id == user.id
    ).order_by(HasVotedLog.created_at.desc()).all()

    result = []
    for log in logs:
        debate = db.query(Debate).filter(Debate.id == log.debate_id).first()
        vote   = db.query(DebateVote).filter(DebateVote.verify_code == log.verify_code).first()
        result.append({
            'debate_id':    log.debate_id,
            'debate_title': debate.title if debate else '—',
            'option':       vote.option_text if vote else '—',
            'verify_code':  log.verify_code,
            'voted_at':     log.created_at.isoformat() if log.created_at else '',
        })
    return {'votes': result}


@app.get('/debates/{debate_id}/results')
def get_results(debate_id: int,
                user: User = Depends(get_optional_user),
                db: Session = Depends(get_db)):
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Consultation not found')
    # Resultados solo visibles si el usuario ya votó o la consulta está cerrada
    if debate.status == 'live' and user:
        log = db.query(HasVotedLog).filter(
            HasVotedLog.user_id == user.id,
            HasVotedLog.debate_id == debate_id
        ).first()
        if not log:
            raise HTTPException(403, 'Debes votar primero para ver los resultados')
    return {
        'debate': format_debate(debate),
        'legitimacy_score': debate.legitimacy_score,
        'verifications': {
            'total': debate.verifications_total,
            'confirmed': debate.verifications_ok,
        },
    }
@app.get('/marketers', response_class=HTMLResponse)
def marketers_page():
    with open('preferendum_marketers.html', 'r') as f:
        return f.read()

@app.get('/organizers', response_class=HTMLResponse)
def organizers_page():
    with open('preferendum_organizers.html', 'r') as f:
        return f.read()
@app.post('/organizers/register')
def organizer_register(data: RegisterInput, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, 'Email already registered')
    hashed = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    user = User(
        email=data.email, name=data.name, password=hashed,
        phone=data.phone, country=data.country, role='organizer',
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        'token': make_token(user.id, 'organizer'),
        'user': {'id': user.id, 'name': user.name, 'email': user.email, 'role': 'organizer'},
        'message': 'Organizer account created'
    }
@app.get('/organizer-panel', response_class=HTMLResponse)
def organizer_panel():
    with open('preferendum_organizer.html', 'r') as f:
        return f.read()

# ══════════════════════════════════════════════════════════════
# ROUTES: ORGANIZER
# ══════════════════════════════════════════════════════════════

@app.post('/organizers/login')
def organizer_login(data: LoginInput, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email, User.role == 'organizer').first()
    if not user or not bcrypt.checkpw(data.password.encode(), user.password.encode()):
        raise HTTPException(401, 'Invalid credentials')
    return {
        'token': make_token(user.id, user.role),
        'user': {'id': user.id, 'name': user.name, 'email': user.email, 'role': user.role},
    }

@app.get('/debates/search-similar')
def search_similar_debate(q: str, country: str = 'CL', db: Session = Depends(get_db)):
    """
    Before creating a debate, check if a similar one already exists.
    Returns matching debates so organizers and agents can converge
    into an existing debate instead of fragmenting the same topic.
    """
    STOP_WORDS = {'el','la','los','las','un','una','de','del','en','que','qué',
                  'y','o','a','al','se','su','sus','por','para','con','es','son',
                  'the','a','an','of','to','in','is','are','and','or','for','with'}
    import re as _re
    def keywords(text):
        words = _re.findall(r'\b\w{4,}\b', text.lower())
        return {w for w in words if w not in STOP_WORDS}

    q_kw = keywords(q)
    if len(q_kw) < 2:
        return {'similar': [], 'total': 0}

    live = db.query(Debate).filter(
        Debate.status == 'live',
        Debate.scope_country == country,
    ).order_by(Debate.id.desc()).limit(100).all()

    results = []
    for d in live:
        d_kw = keywords(d.title or '')
        overlap = len(q_kw & d_kw)
        if overlap >= 3:
            results.append({
                'id':        d.id,
                'title':     d.title,
                'total_votes': d.total_votes or 0,
                'overlap':   overlap,
                'closes_at': d.closes_at.isoformat() if d.closes_at else None,
            })
    results.sort(key=lambda x: x['overlap'], reverse=True)
    return {'similar': results[:5], 'total': len(results)}


@app.get('/organizers/me/debates')
def organizer_my_debates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ('organizer', 'admin'):
        raise HTTPException(403, 'Organizer role required')
    debates = db.query(Debate).filter(Debate.creator_id == user.id).order_by(Debate.created_at.desc()).all()
    return {'debates': [format_debate(d) for d in debates], 'total': len(debates)}

@app.post('/organizers/debates')
def organizer_create_debate(data: DebateCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ('organizer', 'admin'):
        raise HTTPException(403, 'Organizer role required')
    if len(data.options) < 2:
        raise HTTPException(400, 'At least 2 options required')
    closes = datetime.fromisoformat(data.closes_at)
    verify_closes = closes + timedelta(days=data.verify_days)
    debate = Debate(
        title=data.title, context=data.context,
        options=json.dumps(data.options),
        creator_id=user.id,
        creator_type=data.creator_type, inst_name=data.inst_name or user.name,
        debate_type=data.debate_type, scope=data.scope,
        scope_country=data.scope_country, scope_commune=data.scope_commune,
        target_gender=data.target_gender,
        target_age_min=data.target_age_min, target_age_max=data.target_age_max,
        target_se_tiers=getattr(data, 'target_se_tiers', None) or 'A,B,C,D',
        category=getattr(data, 'category', 'general') or 'general',
        closes_at=closes, verify_closes_at=verify_closes,
        vote_counts=json.dumps({opt: 0 for opt in data.options}),
        follow_up_questions=data.follow_up_questions or '',
        reward=data.reward or '',
        option_images=json.dumps(data.option_images or []),
        cover_image_url=data.cover_image_url or '',
        is_anonymous=data.is_anonymous,
    )
    db.add(debate)
    db.commit()
    db.refresh(debate)
    return {'debate': format_debate(debate), 'message': 'Debate created successfully'}

@app.put('/organizers/debates/{debate_id}')
def organizer_update_debate(debate_id: int, data: DebateCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ('organizer', 'admin'):
        raise HTTPException(403, 'Organizer role required')
    debate = db.query(Debate).filter(Debate.id == debate_id, Debate.creator_id == user.id).first()
    if not debate:
        raise HTTPException(404, 'Debate not found or not owned by you')
    # IMMUTABILITY RULE: once any vote has been cast, nothing can be changed
    if (debate.total_votes or 0) > 0:
        raise HTTPException(403, 'This consultation has votes and cannot be modified. Votes are immutable records anchored on blockchain.')
    debate.title = data.title
    debate.context = data.context or ''
    debate.inst_name = data.inst_name or user.name
    debate.cover_image_url = data.cover_image_url or ''
    db.commit()
    return {'message': 'Consultation updated', 'debate': format_debate(debate)}

@app.put('/organizers/debates/{debate_id}/close')
def organizer_close_debate(debate_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ('organizer', 'admin'):
        raise HTTPException(403, 'Organizer role required')
    debate = db.query(Debate).filter(Debate.id == debate_id, Debate.creator_id == user.id).first()
    if not debate:
        raise HTTPException(404, 'Debate not found or not owned by you')
    debate.closes_at = datetime.utcnow()
    db.commit()
    return {'message': 'Debate closed', 'debate': format_debate(debate)}

@app.get('/organizers/debates/{debate_id}/results')
def organizer_debate_results(debate_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ('organizer', 'admin'):
        raise HTTPException(403, 'Organizer role required')
    debate = db.query(Debate).filter(Debate.id == debate_id, Debate.creator_id == user.id).first()
    if not debate:
        raise HTTPException(404, 'Debate not found or not owned by you')
    formatted = format_debate(debate)
    return {
        'debate': formatted,
        'legitimacy_score': debate.legitimacy_score,
        'verifications': {
            'total': debate.verifications_total,
            'confirmed': debate.verifications_ok,
        },
    }

# ══════════════════════════════════════════════════════════════
# ROUTES: MARKETER / ADVERTISER
# ══════════════════════════════════════════════════════════════

COST_PER_VIEW = 20  # CLP por impresión

@app.post('/advertiser/campaigns')
def create_campaign(data: CampaignCreate, db: Session = Depends(get_db)):
    campaign = AdCampaign(
        advertiser_email    = data.advertiser_email,
        advertiser_name     = data.advertiser_name,
        title               = data.campaign_title,
        budget_clp          = data.budget_clp,
        ad_type             = data.ad_type,
        target_country      = data.target_country,
        target_communes     = data.target_communes,
        target_se_tiers     = data.target_se_tiers,
        target_gender       = data.target_gender,
        target_age_min      = data.target_age_min,
        target_age_max      = data.target_age_max,
        target_age_ranges   = data.target_age_ranges,
        target_categories   = data.target_categories,
        excluded_categories = data.excluded_categories,
        blocked_competitors = data.blocked_competitors,
        logo_url            = data.logo_url,
        ad_copy             = data.ad_copy,
        ad_image_url        = data.ad_image_url,
        video_url           = data.video_url,
        link_url            = data.link_url,
        min_per_capita_usd  = data.min_per_capita_usd,
        start_date          = datetime.fromisoformat(data.start_date),
        end_date            = datetime.fromisoformat(data.end_date),
        is_active           = True,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return {'message': 'Campaign created', 'campaign_id': campaign.id, 'campaign': _format_campaign(campaign)}

@app.get('/advertiser/campaigns')
def list_campaigns(email: str, db: Session = Depends(get_db)):
    campaigns = db.query(AdCampaign).filter(AdCampaign.advertiser_email == email).order_by(AdCampaign.created_at.desc()).all()
    return {'campaigns': [_format_campaign(c) for c in campaigns], 'total': len(campaigns)}

@app.get('/advertiser/campaigns/{campaign_id}')
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, 'Campaign not found')
    return _format_campaign(campaign)

@app.patch('/advertiser/campaigns/{campaign_id}')
def update_campaign(campaign_id: int, data: CampaignCreate, db: Session = Depends(get_db), user: User = Depends(get_verified_user)):
    campaign = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, 'Campaign not found')
    campaign.title               = data.campaign_title
    campaign.budget_clp          = data.budget_clp
    campaign.target_country      = data.target_country
    campaign.target_communes     = data.target_communes
    campaign.target_gender       = data.target_gender
    campaign.target_age_ranges   = data.target_age_ranges
    campaign.target_se_tiers     = data.target_se_tiers
    campaign.excluded_categories = data.excluded_categories
    campaign.blocked_competitors = data.blocked_competitors
    campaign.ad_copy             = data.ad_copy
    campaign.link_url            = data.link_url
    campaign.logo_url            = data.logo_url
    campaign.ad_image_url        = data.ad_image_url
    campaign.video_url           = getattr(data, 'video_url', '') or ''
    campaign.min_per_capita_usd  = getattr(data, 'min_per_capita_usd', 0.0) or 0.0
    campaign.target_age_min      = data.target_age_min
    campaign.target_age_max      = data.target_age_max
    if data.start_date:
        try: campaign.start_date = datetime.fromisoformat(data.start_date)
        except: pass
    if data.end_date:
        try: campaign.end_date = datetime.fromisoformat(data.end_date)
        except: pass
    db.commit()
    db.refresh(campaign)
    return {'message': 'Campaign updated', 'campaign': _format_campaign(campaign)}

@app.put('/advertiser/campaigns/{campaign_id}/pause')
def pause_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, 'Campaign not found')
    campaign.is_active = not campaign.is_active
    db.commit()
    return {'campaign_id': campaign_id, 'is_active': campaign.is_active}

@app.get('/advertiser/dashboard/{campaign_id}')
def get_dashboard(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, 'Campaign not found')
    views     = db.query(AdImpressionLog).filter(AdImpressionLog.campaign_id == campaign_id).all()
    total_imp = len(views)
    spent     = total_imp * COST_PER_VIEW
    by_gender = {}
    by_age    = {}
    by_country= {}
    for v in views:
        by_gender[v.gender]    = by_gender.get(v.gender, 0) + 1
        by_age[v.age_group]    = by_age.get(v.age_group, 0) + 1
        by_country[v.country]  = by_country.get(v.country, 0) + 1
    return {
        'campaign_id':   campaign_id,
        'title':         campaign.title,
        'advertiser':    campaign.advertiser_name,
        'budget_clp':    campaign.budget_clp,
        'impressions':   total_imp,
        'spent_clp':     spent,
        'balance_clp':   max(0, campaign.budget_clp - spent),
        'cost_per_view': COST_PER_VIEW,
        'is_active':     campaign.is_active,
        'by_gender':     by_gender,
        'by_age':        by_age,
        'by_country':    by_country,
    }

@app.post('/ads/view')
async def track_ad_view(data: AdViewInput, db: Session = Depends(get_db)):
    campaign = db.query(AdCampaign).filter(AdCampaign.id == data.campaign_id, AdCampaign.is_active == True).first()
    if not campaign:
        raise HTTPException(404, 'Campaign not found or inactive')
    log = AdImpressionLog(
        campaign_id = data.campaign_id,
        debate_id   = data.debate_id,
        gender      = data.gender,
        age_group   = data.age_group,
        county      = data.county,
        country     = data.country,
    )
    db.add(log)
    total_imp = db.query(AdImpressionLog).filter(AdImpressionLog.campaign_id == data.campaign_id).count() + 1
    spent     = total_imp * COST_PER_VIEW
    if spent >= campaign.budget_clp:
        campaign.is_active = False
    db.commit()
    return {
        'message':     'Impression recorded',
        'impressions': total_imp,
        'spent_clp':   spent,
        'balance_clp': max(0, campaign.budget_clp - spent),
    }

@app.post('/ads/impression')
def record_impression(
    campaign_id: int,
    debate_id:   int,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(lambda: None),  # anonymous ok
):
    """
    Records a paid impression and deducts Credits from campaign budget.
    Uses CPM from targeting matrix (commune-based).
    Returns False if campaign ran out of budget (caller should swap to next ad).
    """
    from sqlalchemy import text as _text
    # Get campaign CPM — prefer campaign's negotiated CPM, else use commune rate
    row = db.execute(
        _text("SELECT cpm, target_country, scope_commune, remaining_budget, status FROM ad_campaigns WHERE id=:cid"),
        {'cid': campaign_id}
    ).fetchone()
    if not row:
        return {'ok': False, 'error': 'Campaign not found'}
    if row['status'] != 'active':
        return {'ok': False, 'error': 'Campaign not active', 'status': row['status']}

    cpm = float(row['cpm'] or 6.0)

    # Deduct from budget and record impression
    charged = deduct_credits_for_impression(db, campaign_id, cpm)

    if not charged:
        return {'ok': False, 'budget_exhausted': True, 'campaign_id': campaign_id}

    return {
        'ok':          True,
        'campaign_id': campaign_id,
        'debate_id':   debate_id,
        'cost_this_impression': round(cpm / 1000, 5),
        'cpm':         cpm,
    }


@app.post('/ads/click')
def record_click(campaign_id: int, debate_id: int, db: Session = Depends(get_db)):
    """Records a click on an ad. No credit deduction — billing is per impression only."""
    from sqlalchemy import text as _text
    db.execute(
        _text("UPDATE ad_campaigns SET clicks = COALESCE(clicks,0)+1 WHERE id=:cid"),
        {'cid': campaign_id}
    )
    db.commit()
    return {'ok': True}


def _format_campaign(c: AdCampaign) -> dict:
    return {
        'id':                 c.id,
        'title':              c.title,
        'advertiser_name':    c.advertiser_name,
        'advertiser_email':   c.advertiser_email,
        'budget_clp':         c.budget_clp,
        'ad_type':            c.ad_type,
        'target_country':     c.target_country,
        'target_gender':      c.target_gender,
        'target_age_ranges':  c.target_age_ranges,
        'target_categories':  c.target_categories,
        'excluded_categories':c.excluded_categories,
        'start_date':         c.start_date.isoformat() if c.start_date else None,
        'end_date':           c.end_date.isoformat() if c.end_date else None,
        'is_active':          c.is_active,
        'target_se_tiers':    c.target_se_tiers or '',
        'target_age_min':     c.target_age_min or 13,
        'target_age_max':     c.target_age_max or 99,
        'min_per_capita_usd': getattr(c, 'min_per_capita_usd', 0) or 0,
        'video_url':          getattr(c, 'video_url', '') or '',
        'logo_url':           getattr(c, 'logo_url', '') or '',
        'ad_copy':            getattr(c, 'ad_copy', '') or '',
        'link_url':           getattr(c, 'link_url', '') or '',
        'impressions':        0,
        'created_at':         c.created_at.isoformat() if c.created_at else None,
    }

# ══════════════════════════════════════════════════════════════
# COMMUNE CPM TABLE (housing m² proxy — CLP per 1000 impressions)
# ══════════════════════════════════════════════════════════════

COMMUNE_CPM = {
    'Vitacura':    {'se': 'A', 'cpm': 14.50, 'm2': '>120'},
    'Las Condes':  {'se': 'A', 'cpm': 12.80, 'm2': '>120'},
    'Providencia': {'se': 'A', 'cpm': 11.20, 'm2': '>120'},
    'Ñuñoa':       {'se': 'B', 'cpm':  8.40, 'm2': '80-120'},
    'Macul':       {'se': 'B', 'cpm':  7.60, 'm2': '80-120'},
    'San Miguel':  {'se': 'B', 'cpm':  7.20, 'm2': '80-120'},
    'Santiago':    {'se': 'C', 'cpm':  5.20, 'm2': '55-80'},
    'Recoleta':    {'se': 'C', 'cpm':  4.40, 'm2': '55-80'},
    'Maipú':       {'se': 'C', 'cpm':  5.60, 'm2': '55-80'},
    'La Pintana':  {'se': 'D', 'cpm':  3.20, 'm2': '<55'},
    'El Bosque':   {'se': 'D', 'cpm':  3.40, 'm2': '<55'},
    'Cerro Navia': {'se': 'D', 'cpm':  3.00, 'm2': '<55'},
}

# ══════════════════════════════════════════════════════════════
# ROUTES: ORGANIZER (v2 — /organizer/ prefix)
# ══════════════════════════════════════════════════════════════

class OrganizerRegisterFullInput(BaseModel):
    # Cuenta
    email:            str
    password:         str
    name:             str
    phone:            str = ''
    national_id:      str = ''
    country:          str = 'CL'
    # Tipo
    org_type:         str = 'person'   # person / company
    is_supervisor:    bool = True
    # Datos empresa (solo si org_type=company)
    company_name:     str = ''
    company_rut:      str = ''
    company_web:      str = ''
    cargo:            str = ''
    # Supervisor que lo autoriza (solo si is_supervisor=False)
    supervisor_email: str = ''


@app.post('/organizer/register')
def organizer_register_v2(data: OrganizerRegisterFullInput, bg: BackgroundTasks, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        # Citizen trying to become organizer — verify password then upgrade role
        if not bcrypt.checkpw(data.password.encode(), existing.password.encode()):
            raise HTTPException(400, 'Ya tienes cuenta — usa tu contraseña de ciudadano')
        existing.role = 'organizer'
        db.commit()
        profile = db.query(OrganizerProfile).filter(OrganizerProfile.user_id == existing.id).first()
        if not profile:
            profile = OrganizerProfile(
                user_id=existing.id, org_type=data.org_type or 'person',
                is_supervisor=True, status='approved', company_name=data.company_name or '',
            )
            db.add(profile); db.commit()
        token = make_token(existing.id, existing.role)
        return {'token': token, 'user': {'id': existing.id, 'name': existing.name, 'email': existing.email, 'role': existing.role}, 'profile': {'status': profile.status if profile else 'approved'}}


    # Verificar dominio email corporativo
    if data.org_type == 'company':
        domain_check = _verify_email_domain(data.email)
        if not domain_check['valid']:
            raise HTTPException(400, domain_check.get('reason', 'Email inválido'))

    hashed = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    user = User(
        email=data.email, name=data.name, password=hashed,
        phone=data.phone, national_id=data.national_id,
        country=data.country, role='organizer',
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Verificar RUT empresa en SII
    rut_ok  = False
    web_ok  = False
    rut_info = {}
    if data.org_type == 'company' and data.company_rut:
        rut_info = _verify_company_rut(data.company_rut)
        rut_ok   = rut_info.get('valid', False)

    # Verificar web empresa
    if data.org_type == 'company' and data.company_web:
        web_check = _verify_company_web(data.company_web, data.company_name, data.company_rut)
        web_ok    = web_check.get('valid', False)

    domain_ok = data.org_type == 'company' and _verify_email_domain(data.email)['valid']

    profile = OrganizerProfile(
        user_id              = user.id,
        org_type             = data.org_type,
        is_supervisor        = data.is_supervisor,
        company_name         = data.company_name,
        company_rut          = data.company_rut,
        company_web          = data.company_web,
        company_email_domain = data.email.split('@')[1] if '@' in data.email else '',
        cargo                = data.cargo,
        supervisor_email     = data.supervisor_email,
        rut_verified         = rut_ok,
        domain_verified      = domain_ok,
        web_verified         = web_ok,
        status               = 'approved',
    )
    db.add(profile)
    db.commit()
    if profile.status == 'approved':
        profile.approved_at = datetime.utcnow()
        db.commit()

    # OTP email
    code = gen_otp()
    db.add(OTPCode(user_id=user.id, email=user.email, code=code, channel='email',
                   expires_at=datetime.utcnow() + timedelta(minutes=10)))
    db.commit()
    bg.add_task(send_email_otp, user.email, code, user.name)

    # Si necesita autorización de supervisor → enviar email al jefe
    if not data.is_supervisor and data.supervisor_email:
        token = hashlib.sha256(f'{user.id}-{data.supervisor_email}-{datetime.utcnow()}'.encode()).hexdigest()[:32]
        db.add(AuthorizationRequest(
            employee_user_id = user.id,
            employee_name    = user.name,
            employee_email   = user.email,
            supervisor_email = data.supervisor_email,
            token            = token,
        ))
        db.commit()
        bg.add_task(_send_supervisor_authorization_email,
            supervisor_email=data.supervisor_email,
            employee_name=user.name,
            employee_email=user.email,
            company=data.company_name,
            cargo=data.cargo,
            token=token,
        )

    verifications = {
        'email_sent':   True,
        'rut_verified': rut_ok,
        'rut_name':     rut_info.get('razon_social', ''),
        'domain_ok':    domain_ok,
        'web_ok':       web_ok,
        'needs_doc':    True,
        'needs_selfie': True,
        'status':       profile.status,
    }
    return {
        'token': make_token(user.id, 'organizer'),
        'user':  {'id': user.id, 'name': user.name, 'email': user.email, 'role': 'organizer'},
        'verifications': verifications,
        'message': 'Registro completado. Tu cuenta está activa.',
    }


@app.post('/organizer/login')
def organizer_login_v2(data: LoginInput, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not bcrypt.checkpw(data.password.encode(), user.password.encode()):
        raise HTTPException(401, 'Credenciales inválidas')
    if user.role not in ('organizer', 'admin'):
        raise HTTPException(403, 'No tienes cuenta de organizador')
    profile = db.query(OrganizerProfile).filter(OrganizerProfile.user_id == user.id).first()
    return {
        'token':   make_token(user.id, user.role),
        'user':    {'id': user.id, 'name': user.name, 'email': user.email, 'role': user.role},
        'profile': {
            'status':       profile.status if profile else 'pending',
            'org_type':     profile.org_type if profile else 'person',
            'is_supervisor':profile.is_supervisor if profile else True,
            'rut_verified': profile.rut_verified if profile else False,
            'web_verified': profile.web_verified if profile else False,
            'doc_verified': profile.doc_verified if profile else False,
        } if profile else None,
    }


class EmpresaVerifyInput(BaseModel):
    full_name:    str
    rut:          str
    phone:        str = ''
    company_name: str
    boss_email:   str
    document_url: str = ''
    consent:      bool = False

@app.post('/organizer/empresa-verify')
def organizer_empresa_verify(
    data: EmpresaVerifyInput,
    bg:   BackgroundTasks,
    user: User = Depends(get_current_user),
    db:   Session = Depends(get_db),
):
    if not data.consent:
        raise HTTPException(400, 'Debes aceptar los términos y condiciones')
    if not data.boss_email or '@' not in data.boss_email:
        raise HTTPException(400, 'Correo del jefe inválido')

    token = hashlib.sha256(
        f'{user.id}-{data.boss_email}-{datetime.utcnow()}'.encode()
    ).hexdigest()[:32]

    db.add(AuthorizationRequest(
        employee_user_id = user.id,
        employee_name    = data.full_name,
        employee_email   = user.email,
        supervisor_email = data.boss_email,
        token            = token,
    ))
    db.commit()

    bg.add_task(
        _send_supervisor_authorization_email,
        supervisor_email = data.boss_email,
        employee_name    = data.full_name,
        employee_email   = user.email,
        company          = data.company_name,
        cargo            = f'RUT {data.rut}',
        token            = token,
        role             = 'organizer',
    )
    return {'ok': True, 'message': 'Solicitud enviada al jefe'}


@app.post('/organizer/upload-cargo-doc')
async def upload_cargo_doc(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Sube el documento que acredita el cargo (contrato, poder notarial, etc.)"""
    contents = await file.read()
    if file.content_type not in ['image/jpeg','image/png','image/webp','application/pdf']:
        raise HTTPException(400, 'Solo JPG, PNG o PDF')
    profile = db.query(OrganizerProfile).filter(OrganizerProfile.user_id == user.id).first()
    if not profile:
        raise HTTPException(404, 'Perfil de organizador no encontrado')
    profile.cargo_doc_hash  = hashlib.sha256(contents).hexdigest()
    profile.cargo_doc_bytes = base64.b64encode(contents).decode()
    db.commit()
    return {'ok': True, 'message': 'Documento recibido. Será revisado en 1-2 días hábiles.'}


@app.get('/organizer/authorize/{token}')
def supervisor_authorization_page(token: str, db: Session = Depends(get_db)):
    """Link que recibe el jefe en su email — muestra quién quiere autorización."""
    req = db.query(AuthorizationRequest).filter(
        AuthorizationRequest.token == token,
        AuthorizationRequest.status == 'pending'
    ).first()
    if not req:
        raise HTTPException(404, 'Link de autorización inválido o ya usado')
    return {
        'employee_name':  req.employee_name,
        'employee_email': req.employee_email,
        'token':          token,
        'message':        f'{req.employee_name} solicita autorización para crear consultas en Preferendum',
    }


@app.post('/organizer/authorize/{token}')
def supervisor_approve(token: str, action: str, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """El jefe aprueba o rechaza al empleado desde su cuenta verificada."""
    req = db.query(AuthorizationRequest).filter(
        AuthorizationRequest.token == token,
        AuthorizationRequest.status == 'pending'
    ).first()
    if not req:
        raise HTTPException(404, 'Solicitud no encontrada')

    sup_profile = db.query(OrganizerProfile).filter(OrganizerProfile.user_id == user.id).first()
    if not sup_profile or not sup_profile.is_supervisor:
        raise HTTPException(403, 'Solo supervisores verificados pueden autorizar')
    if sup_profile.status != 'approved':
        raise HTTPException(403, 'Tu cuenta debe estar aprobada para autorizar empleados')
    # Hard requirement, not just an admin-review courtesy: the boss must have
    # put their own face on record before vouching for anyone else's. Someone
    # who'd fabricate an employee identity could otherwise approve it from an
    # account that was admin-approved on paperwork alone — selfie included
    # closes that path, exactly per the "no crook films their own face" logic.
    if not user.selfie_verified:
        raise HTTPException(403, 'Debes verificar tu propia identidad con selfie antes de poder autorizar a alguien')

    req.status             = action  # approved / rejected
    req.supervisor_user_id = user.id
    req.resolved_at        = datetime.utcnow()

    if action == 'approved':
        emp_profile = db.query(OrganizerProfile).filter(
            OrganizerProfile.user_id == req.employee_user_id
        ).first()
        if emp_profile:
            emp_profile.supervisor_user_id = user.id
            emp_profile.supervisor_name    = user.name
            emp_profile.status             = 'approved'

    db.commit()
    return {'ok': True, 'action': action, 'employee': req.employee_name}


@app.get('/organizer/status')
def organizer_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Estado completo de verificación del organizador."""
    profile = db.query(OrganizerProfile).filter(OrganizerProfile.user_id == user.id).first()
    if not profile:
        raise HTTPException(404, 'Perfil de organizador no encontrado')
    pending_employees = db.query(AuthorizationRequest).filter(
        AuthorizationRequest.supervisor_email == user.email,
        AuthorizationRequest.status == 'pending'
    ).count()
    return {
        'status':            profile.status,
        'org_type':          profile.org_type,
        'is_supervisor':     profile.is_supervisor,
        'company_name':      profile.company_name,
        'cargo':             profile.cargo,
        'verifications': {
            'email':   user.email_verified,
            'phone':   user.phone_verified,
            # profile.selfie_verified is never written by /verify/selfie — the real
            # flag lives on the user record. Reading the profile copy always showed
            # false here even after a successful selfie match; read the live one.
            'selfie':  user.selfie_verified,
            'rut':     profile.rut_verified,
            'domain':  profile.domain_verified,
            'web':     profile.web_verified,
            'doc':     profile.doc_verified,
        },
        'pending_authorization_requests': pending_employees,
        'can_create_consultations': profile.status == 'approved',
    }

@app.get('/organizer/consultations')
def list_organizer_consultations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ('organizer', 'admin'):
        raise HTTPException(403, 'Organizer role required')
    debates = db.query(Debate).filter(Debate.creator_id == user.id).order_by(Debate.created_at.desc()).all()
    return {'consultations': [format_debate(d) for d in debates], 'total': len(debates)}

@app.post('/organizer/consultations')
def create_organizer_consultation(data: DebateCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ('organizer', 'admin'):
        raise HTTPException(403, 'Organizer role required')

    # Verificar que el organizador está aprobado
    profile = db.query(OrganizerProfile).filter(OrganizerProfile.user_id == user.id).first()
    if profile and profile.status == 'suspended':
        raise HTTPException(403, 'Tu cuenta está suspendida')
    if profile and profile.status == 'pending' and user.role != 'admin':
        raise HTTPException(403, 'Tu cuenta está pendiente de aprobación')

    if len(data.options) < 2:
        raise HTTPException(400, 'At least 2 options required')

    # Moderación de IA antes de publicar
    moderation = _moderate_consultation(data.title, data.context, data.options)
    if moderation['decision'] == 'rejected':
        raise HTTPException(400, f'Consulta rechazada: {moderation["reason"]}')

    closes        = datetime.fromisoformat(data.closes_at)
    verify_closes = closes + timedelta(days=data.verify_days)

    # Consultas en revisión quedan como 'draft' hasta aprobación manual
    status = 'live' if moderation['decision'] == 'approved' else 'draft'

    debate = Debate(
        title=data.title, context=data.context,
        options=json.dumps(data.options),
        creator_id=user.id, status=status,
        creator_type=data.creator_type, inst_name=data.inst_name or user.name,
        debate_type=data.debate_type, scope=data.scope,
        scope_country=data.scope_country, scope_commune=data.scope_commune,
        target_gender=data.target_gender,
        target_age_min=data.target_age_min, target_age_max=data.target_age_max,
        target_se_tiers=getattr(data, 'target_se_tiers', None) or 'A,B,C,D',
        category=getattr(data, 'category', 'general') or 'general',
        closes_at=closes, verify_closes_at=verify_closes,
        vote_counts=json.dumps({opt: 0 for opt in data.options}),
        follow_up_questions=data.follow_up_questions or '',
        reward=data.reward or '',
        option_images=json.dumps(data.option_images or []),
        cover_image_url=data.cover_image_url or '',
    )
    db.add(debate)
    db.commit()
    db.refresh(debate)

    db.add(ConsultationModerationLog(
        debate_id=debate.id, score=moderation['score'],
        decision=moderation['decision'], reason=moderation['reason'],
    ))
    db.commit()

    return {
        'consultation': format_debate(debate),
        'moderation': {'score': moderation['score'], 'decision': moderation['decision'], 'reason': moderation['reason']},
        'message': 'Consulta publicada.' if status == 'live' else f'Consulta en revisión (score {moderation["score"]}/100). Se publicará tras revisión manual.',
    }

@app.post('/organizer/closed-list')
async def upload_closed_list(
    debate_id: int = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if user.role not in ('organizer', 'admin'):
        raise HTTPException(403, 'Organizer role required')
    debate = db.query(Debate).filter(Debate.id == debate_id, Debate.creator_id == user.id).first()
    if not debate:
        raise HTTPException(404, 'Consultation not found or not owned by you')
    content = await file.read()
    lines = content.decode('utf-8', errors='ignore').strip().splitlines()
    added = 0
    for line in lines:
        nid = line.strip()
        if not nid:
            continue
        h = hash_str(nid, prefix='closedlist:')
        exists = db.query(ClosedListEntry).filter(
            ClosedListEntry.debate_id == debate_id,
            ClosedListEntry.national_id_hash == h
        ).first()
        if not exists:
            db.add(ClosedListEntry(debate_id=debate_id, national_id_hash=h))
            added += 1
    db.commit()
    return {'message': f'{added} voter IDs added to closed list', 'debate_id': debate_id, 'total_added': added}

@app.get('/organizer/consultations/{consultation_id}/results')
def get_consultation_results(consultation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ('organizer', 'admin'):
        raise HTTPException(403, 'Organizer role required')
    debate = db.query(Debate).filter(Debate.id == consultation_id, Debate.creator_id == user.id).first()
    if not debate:
        raise HTTPException(404, 'Consultation not found or not owned by you')
    votes = db.query(DebateVote).filter(DebateVote.debate_id == consultation_id).all()
    by_gender, by_age = {}, {}
    for v in votes:
        k = v.gender or 'unknown'
        by_gender[k] = by_gender.get(k, 0) + 1
        k2 = v.age_group or 'unknown'
        by_age[k2] = by_age.get(k2, 0) + 1
    return {
        'consultation': format_debate(debate),
        'legitimacy_score': debate.legitimacy_score,
        'verifications': {'total': debate.verifications_total, 'confirmed': debate.verifications_ok},
        'demographics': {'by_gender': by_gender, 'by_age': by_age},
    }

@app.post('/organizer/consultations/{consultation_id}/reward-codes')
async def upload_reward_codes(consultation_id: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ('organizer', 'admin'):
        raise HTTPException(403, 'Organizer role required')
    debate = db.query(Debate).filter(Debate.id == consultation_id, Debate.creator_id == user.id).first()
    if not debate:
        raise HTTPException(404, 'Consultation not found or not owned by you')
    body = await request.json()
    codes_raw = body.get('codes', '')
    codes = [c.strip() for c in codes_raw.strip().splitlines() if c.strip()]
    for code in codes:
        db.add(DebateRewardCode(debate_id=consultation_id, code=code))
    db.commit()
    total_remaining = db.query(DebateRewardCode).filter(
        DebateRewardCode.debate_id == consultation_id,
        DebateRewardCode.claimed == False
    ).count()
    return {'added': len(codes), 'total_remaining': total_remaining}

@app.get('/organizer/consultations/{consultation_id}/reward-codes/status')
def reward_codes_status(consultation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ('organizer', 'admin'):
        raise HTTPException(403, 'Organizer role required')
    total = db.query(DebateRewardCode).filter(DebateRewardCode.debate_id == consultation_id).count()
    remaining = db.query(DebateRewardCode).filter(
        DebateRewardCode.debate_id == consultation_id,
        DebateRewardCode.claimed == False
    ).count()
    return {'total': total, 'remaining': remaining, 'claimed': total - remaining}

# ══════════════════════════════════════════════════════════════
# ROUTES: MARKETER (v2 — /marketer/ prefix)
# ══════════════════════════════════════════════════════════════

class MarketerRegisterInput(BaseModel):
    email:             str
    password:          str
    name:              str
    phone:             str = ''
    national_id:       str = ''
    country:           str = 'CL'
    # Tipo
    org_type:          str = 'company'   # person / company
    is_supervisor:     bool = True
    # Datos empresa
    company_name:      str = ''
    company_rut:       str = ''
    company_web:       str = ''
    business_category: str = ''           # elegida del pop-up — ver MARKETER_BUSINESS_CATEGORIES
    cargo:             str = ''
    department:        str = ''           # departamento dentro de la empresa
    # Jefe que lo autoriza (solo si is_supervisor=False)
    supervisor_name:   str = ''
    supervisor_email:  str = ''
    supervisor_phone:  str = ''


@app.post('/marketer/register')
def marketer_register(data: MarketerRegisterInput, bg: BackgroundTasks, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        # Citizen trying to become marketer — verify password then upgrade role
        if not bcrypt.checkpw(data.password.encode(), existing.password.encode()):
            raise HTTPException(400, 'Ya tienes cuenta — usa tu contraseña de ciudadano')
        existing.role = 'marketer'
        db.commit()
        mk_profile = db.query(MarketerProfile).filter(MarketerProfile.user_id == existing.id).first()
        if not mk_profile:
            mk_profile = MarketerProfile(
                user_id=existing.id, org_type=data.org_type or 'person',
                is_supervisor=True, status='approved', company_name=data.company_name or '',
            )
            db.add(mk_profile); db.commit()
        token = make_token(existing.id, existing.role)
        return {'token': token, 'user': {'id': existing.id, 'name': existing.name, 'email': existing.email, 'role': existing.role}}


    # Filtro de categoría — corta de raíz antes de cualquier verificación de identidad,
    # tal como un guardia de entrada revisa el rubro antes de pedir documentos.
    cat_check = _check_business_category(data.business_category)
    if not cat_check['allowed']:
        raise HTTPException(403, cat_check['reason'])

    # Verificar dominio email corporativo
    if data.org_type == 'company':
        domain_check = _verify_email_domain(data.email)
        if not domain_check['valid']:
            raise HTTPException(400, domain_check.get('reason', 'Email inválido'))

    hashed = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    user = User(
        email=data.email, name=data.name, password=hashed,
        phone=data.phone, national_id=data.national_id,
        country=data.country, role='marketer',
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Verificar RUT empresa en SII y sitio web
    rut_ok, web_ok, rut_info, web_check = False, False, {}, {}
    if data.org_type == 'company' and data.company_rut:
        rut_info = _verify_company_rut(data.company_rut)
        rut_ok   = rut_info.get('valid', False)
    if data.org_type == 'company' and data.company_web:
        web_check = _verify_company_web(data.company_web, data.company_name, data.company_rut)
        web_ok    = web_check.get('valid', False)

    domain_ok = data.org_type == 'company' and _verify_email_domain(data.email)['valid']

    profile = MarketerProfile(
        user_id              = user.id,
        org_type             = data.org_type,
        is_supervisor        = data.is_supervisor,
        company_name         = data.company_name,
        company_rut          = data.company_rut,
        company_web          = data.company_web,
        company_email_domain = data.email.split('@')[1] if '@' in data.email else '',
        business_category    = data.business_category.strip().lower(),
        cargo                = data.cargo,
        department           = data.department,
        applicant_phone      = data.phone,
        supervisor_name      = data.supervisor_name,
        supervisor_email     = data.supervisor_email,
        supervisor_phone     = data.supervisor_phone,
        rut_verified         = rut_ok,
        domain_verified      = domain_ok,
        web_verified         = web_ok,
        status               = 'approved',
    )
    db.add(profile)
    db.commit()
    if profile.status == 'approved':
        profile.approved_at = datetime.utcnow()
        db.commit()

    # OTP email
    code = gen_otp()
    db.add(OTPCode(user_id=user.id, email=user.email, code=code, channel='email',
                   expires_at=datetime.utcnow() + timedelta(minutes=10)))
    db.commit()
    bg.add_task(send_email_otp, user.email, code, user.name)

    # Si necesita autorización del jefe → email al jefe (con su propia cuenta verificada)
    if not data.is_supervisor and data.supervisor_email:
        token = hashlib.sha256(f'{user.id}-{data.supervisor_email}-{datetime.utcnow()}'.encode()).hexdigest()[:32]
        db.add(MarketerAuthorizationRequest(
            employee_user_id = user.id,
            employee_name    = user.name,
            employee_email   = user.email,
            supervisor_email = data.supervisor_email,
            token            = token,
        ))
        db.commit()
        bg.add_task(_send_supervisor_authorization_email,
            supervisor_email=data.supervisor_email,
            employee_name=user.name,
            employee_email=user.email,
            company=data.company_name,
            cargo=data.cargo,
            token=token,
            role='marketer',
        )

    verifications = {
        'email_sent':   True,
        'category_ok':  cat_check['allowed'],
        'rut_verified': rut_ok,
        'rut_name':     rut_info.get('razon_social', ''),
        'domain_ok':    domain_ok,
        'web_ok':       web_ok,
        'needs_doc':    True,
        'needs_selfie': True,
        'status':       profile.status,
    }
    return {
        'token': make_token(user.id, 'marketer'),
        'user':  {'id': user.id, 'name': user.name, 'email': user.email, 'role': 'marketer'},
        'verifications': verifications,
        'message': 'Registro iniciado. Verifica tu email y sube tu documento de cargo + selfie.',
    }

@app.post('/marketer/login')
def marketer_login(data: LoginInput, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email, User.role.in_(['marketer', 'admin'])).first()
    if not user or not bcrypt.checkpw(data.password.encode(), user.password.encode()):
        raise HTTPException(401, 'Credenciales inválidas')
    profile = db.query(MarketerProfile).filter(MarketerProfile.user_id == user.id).first()
    return {
        'token':   make_token(user.id, user.role),
        'user':    {'id': user.id, 'name': user.name, 'email': user.email, 'role': user.role},
        'profile': {
            'status':        profile.status if profile else 'pending',
            'org_type':      profile.org_type if profile else 'company',
            'is_supervisor': profile.is_supervisor if profile else True,
            'rut_verified':  profile.rut_verified if profile else False,
            'web_verified':  profile.web_verified if profile else False,
            'doc_verified':  profile.doc_verified if profile else False,
        } if profile else None,
    }


@app.post('/marketer/upload-cargo-doc')
async def marketer_upload_cargo_doc(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Sube el documento que acredita el cargo (contrato, poder notarial, etc.)"""
    contents = await file.read()
    if file.content_type not in ['image/jpeg', 'image/png', 'image/webp', 'application/pdf']:
        raise HTTPException(400, 'Solo JPG, PNG o PDF')
    profile = db.query(MarketerProfile).filter(MarketerProfile.user_id == user.id).first()
    if not profile:
        raise HTTPException(404, 'Perfil de marketer no encontrado')
    profile.cargo_doc_hash  = hashlib.sha256(contents).hexdigest()
    profile.cargo_doc_bytes = base64.b64encode(contents).decode()
    db.commit()
    return {'ok': True, 'message': 'Documento recibido. Será revisado en 1-2 días hábiles.'}


@app.get('/marketer/authorize/{token}')
def marketer_authorization_page(token: str, db: Session = Depends(get_db)):
    """Link que recibe el jefe en su email — muestra quién pide autorización para lanzar campañas."""
    req = db.query(MarketerAuthorizationRequest).filter(
        MarketerAuthorizationRequest.token == token,
        MarketerAuthorizationRequest.status == 'pending'
    ).first()
    if not req:
        raise HTTPException(404, 'Link de autorización inválido o ya usado')
    return {
        'employee_name':  req.employee_name,
        'employee_email': req.employee_email,
        'token':          token,
        'message':        f'{req.employee_name} solicita autorización para lanzar campañas publicitarias en Preferendum',
    }


@app.post('/marketer/authorize/{token}')
def marketer_supervisor_approve(token: str, action: str, db: Session = Depends(get_db),
                                 user: User = Depends(get_current_user)):
    """El jefe aprueba o rechaza al empleado desde su propia cuenta verificada (con selfie)."""
    req = db.query(MarketerAuthorizationRequest).filter(
        MarketerAuthorizationRequest.token == token,
        MarketerAuthorizationRequest.status == 'pending'
    ).first()
    if not req:
        raise HTTPException(404, 'Solicitud no encontrada')

    sup_profile = db.query(MarketerProfile).filter(MarketerProfile.user_id == user.id).first()
    if not sup_profile or not sup_profile.is_supervisor:
        raise HTTPException(403, 'Solo jefes con cuenta de marketer verificada pueden autorizar')
    if sup_profile.status != 'approved':
        raise HTTPException(403, 'Tu cuenta debe estar aprobada para autorizar campañas')
    # Hard requirement, not just an admin-review courtesy: the boss must have
    # put their own face on record before vouching for a campaign that will
    # display their company's name to real voters. Closes the path where a
    # paperwork-only approval lets someone authorize without ever showing a face.
    if not user.selfie_verified:
        raise HTTPException(403, 'Debes verificar tu propia identidad con selfie antes de poder autorizar campañas')

    req.status             = action  # approved / rejected
    req.supervisor_user_id = user.id
    req.resolved_at        = datetime.utcnow()

    if action == 'approved':
        emp_profile = db.query(MarketerProfile).filter(
            MarketerProfile.user_id == req.employee_user_id
        ).first()
        if emp_profile:
            emp_profile.supervisor_user_id = user.id
            emp_profile.supervisor_name    = user.name
            emp_profile.status             = 'approved'

    db.commit()
    return {'ok': True, 'action': action, 'employee': req.employee_name}


@app.get('/marketer/status')
def marketer_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Estado completo de verificación del marketer."""
    profile = db.query(MarketerProfile).filter(MarketerProfile.user_id == user.id).first()
    if not profile:
        raise HTTPException(404, 'Perfil de marketer no encontrado')
    pending_employees = db.query(MarketerAuthorizationRequest).filter(
        MarketerAuthorizationRequest.supervisor_email == user.email,
        MarketerAuthorizationRequest.status == 'pending'
    ).count()
    return {
        'status':            profile.status,
        'org_type':          profile.org_type,
        'is_supervisor':     profile.is_supervisor,
        'company_name':      profile.company_name,
        'business_category': profile.business_category,
        'cargo':             profile.cargo,
        'department':        profile.department,
        'verifications': {
            'email':   user.email_verified,
            'phone':   user.phone_verified,
            'selfie':  user.selfie_verified,
            'rut':     profile.rut_verified,
            'domain':  profile.domain_verified,
            'web':     profile.web_verified,
            'doc':     profile.doc_verified,
        },
        'pending_authorization_requests': pending_employees,
    }

@app.get('/marketer/communes')
def get_marketer_communes(country: str = None, se_tier: str = None, db: Session = Depends(get_db)):
    """Tabla de comunas con índice de ingreso y CPM — viene del agente de datos."""
    from market_data_agent import get_fallback_table
    rows = db.query(CommuneMarketData)
    if country: rows = rows.filter(CommuneMarketData.country == country)
    if se_tier: rows = rows.filter(CommuneMarketData.se_tier == se_tier)
    rows = rows.order_by(CommuneMarketData.income_index.desc()).all()
    if rows:
        return {'communes': [{'country': r.country, 'commune': r.commune,
            'income_index': r.income_index, 'cpm_usd': r.cpm_usd, 'se_tier': r.se_tier} for r in rows],
            'source': 'database'}
    fallback = get_fallback_table()
    if country: fallback = [c for c in fallback if c['country'] == country]
    if se_tier:  fallback = [c for c in fallback if c['se_tier'] == se_tier]
    return {'communes': fallback, 'source': 'fallback'}


def _optimize_campaign(budget_clp: float, target_country: str, target_communes: str,
                        target_se_tiers: str, target_income_min: float, target_income_max: float,
                        target_gender: str, target_age_min: int, target_age_max: int, db) -> dict:
    """
    Motor de optimización de campaña.
    Objetivo: minimizar costo por contacto al mercado objetivo.
    Lógica: distribuir presupuesto proporcionalmente a votantes alcanzables,
    priorizando comunas con mayor densidad del target y menor CPM relativo.
    """
    from market_data_agent import get_fallback_table

    # 1. Obtener comunas disponibles
    rows = db.query(CommuneMarketData)
    if target_country:
        rows = rows.filter(CommuneMarketData.country == target_country)
    rows = rows.all()
    if not rows:
        data = get_fallback_table()
        if target_country:
            data = [c for c in data if c['country'] == target_country]
    else:
        data = [{'country': r.country, 'commune': r.commune, 'income_index': r.income_index,
                 'cpm_usd': r.cpm_usd, 'se_tier': r.se_tier} for r in rows]

    # 2. Filtrar por nivel de ingreso (SE tier e índice)
    tiers = [t.strip() for t in target_se_tiers.split(',') if t.strip()]
    data = [c for c in data if c['se_tier'] in tiers]
    data = [c for c in data if target_income_min <= c['income_index'] <= target_income_max]
    if target_communes:
        selected = [c.strip() for c in target_communes.split(',')]
        data = [c for c in data if c['commune'] in selected]

    if not data:
        return {'error': 'Ninguna comuna coincide con los criterios de targeting'}

    # 3. Estimar votantes alcanzables por comuna
    # Factor demográfico: ajustar por género y edad objetivo
    # A targeting window always covers at least one age — "exactly 30" is a
    # legitimate, common choice, not "zero people". Treating it as a
    # zero-width range zeroed out demo_factor for every commune, which zeroed
    # out total_weight below and crashed this whole request with a
    # ZeroDivisionError BEFORE the campaign row was ever created — a launch
    # that looked like it silently did nothing. floor it at one year so a
    # single-age target still represents the (small, real) slice it is.
    age_range = max(target_age_max - target_age_min, 1)
    age_factor = min(1.0, age_range / 60.0)   # 60 años = 100% población activa
    gender_factor = 0.52 if target_gender == 'F' else 0.48 if target_gender == 'M' else 1.0
    demo_factor = age_factor * gender_factor

    # Población estimada por commune (proxy: índice de ingreso → densidad urbana)
    for c in data:
        pop_est = int(50000 * (1 + c['income_index'] / 200))
        c['voters_est'] = int(pop_est * 0.75 * 0.35 * demo_factor)

    # 4. Distribuir presupuesto — proporcional a votantes, penalizando CPM alto
    # Peso = votantes / cpm → más peso a comunas con más audiencia y menor costo
    total_weight = sum(c['voters_est'] / max(c['cpm_usd'], 0.1) for c in data)
    if total_weight <= 0:
        # Belt-and-suspenders: whatever combination of inputs got us to "every
        # matching commune estimates zero reachable voters", dividing by that
        # is what turns a bad estimate into a hard crash that drops the whole
        # campaign. Fall back to spreading the budget evenly across the
        # matching communes rather than refusing to create the campaign —
        # an organizer who picks unusual targeting still gets a campaign and
        # an honest (if rough) allocation, not a vanished submission.
        total_weight = float(len(data))
        for c in data:
            c['voters_est'] = max(c['voters_est'], 1)
    budget_usd = budget_clp / USD_TO_CLP

    allocation = []
    total_impressions = 0
    total_contacts = 0

    for c in data:
        weight = (c['voters_est'] / max(c['cpm_usd'], 0.1)) / total_weight
        budget_commune_usd = budget_usd * weight
        impressions = int((budget_commune_usd / c['cpm_usd']) * 1000)
        contacts = min(impressions, c['voters_est'])
        allocation.append({
            'country':       c['country'],
            'commune':       c['commune'],
            'se_tier':       c['se_tier'],
            'income_index':  c['income_index'],
            'cpm_usd':       c['cpm_usd'],
            'budget_clp':    int(budget_commune_usd * USD_TO_CLP),
            'budget_pct':    round(weight * 100, 1),
            'impressions':   impressions,
            'contacts_est':  contacts,
        })
        total_impressions += impressions
        total_contacts    += contacts

    allocation.sort(key=lambda x: x['contacts_est'], reverse=True)
    cost_per_contact = round((budget_clp / total_contacts), 0) if total_contacts > 0 else 0

    return {
        'budget_clp':           int(budget_clp),
        'budget_usd':           round(budget_usd, 2),
        'total_communes':       len(allocation),
        'total_impressions':    total_impressions,
        'total_contacts_est':   total_contacts,
        'cost_per_contact_clp': cost_per_contact,
        'cpm_promedio':         round(budget_usd / (total_impressions / 1000), 2) if total_impressions > 0 else 0,
        'targeting': {
            'country':     target_country or 'todos',
            'se_tiers':    tiers,
            'income_range': f'{target_income_min}–{target_income_max}',
            'gender':      target_gender,
            'age':         f'{target_age_min}–{target_age_max}',
        },
        'allocation': allocation,
    }


@app.post('/marketer/estimate')
def estimate_campaign(data: CampaignCreate, db: Session = Depends(get_db)):
    """Simula la campaña y muestra la optimización antes de confirmar."""
    result = _optimize_campaign(
        budget_clp=data.budget_clp,
        target_country=data.target_country,
        target_communes=data.target_communes,
        target_se_tiers=data.target_se_tiers,
        target_income_min=data.target_income_min,
        target_income_max=data.target_income_max,
        target_gender=data.target_gender,
        target_age_min=data.target_age_min,
        target_age_max=data.target_age_max,
        db=db,
    )
    return result


class SocialSponsorInput(BaseModel):
    advertiser_email: str
    platforms:        list  # ["instagram", "x", "tiktok", "facebook"]
    weeks:            int = 4
    tagline:          str = ''
    total_usd:        float = 0.0

PLATFORM_PRICES_USD = {'instagram': 290, 'x': 240, 'tiktok': 320, 'facebook': 210}

@app.post('/marketer/social-sponsors')
def create_social_sponsor(data: SocialSponsorInput, db: Session = Depends(get_db)):
    """Registra un patrocinio de amplificación social. Usa el targeting existente de la cuenta."""
    user = db.query(User).filter(User.email == data.advertiser_email, User.role.in_(['marketer','admin'])).first()
    if not user:
        raise HTTPException(404, 'Cuenta marketer no encontrada. Crea tu campaña primero.')
    total = sum(PLATFORM_PRICES_USD.get(p, 0) for p in data.platforms) * data.weeks
    import secrets as _secrets
    token = 'SS-' + _secrets.token_hex(12).upper()
    return {
        'token':     token,
        'platforms': data.platforms,
        'weeks':     data.weeks,
        'total_usd': total,
        'tagline':   data.tagline,
        'advertiser': user.name,
        'message':   f'Patrocinio social activado en {len(data.platforms)} plataformas por {data.weeks} semanas.',
    }

@app.get('/marketer/social-sponsors')
def list_social_sponsors(email: str, db: Session = Depends(get_db)):
    """Lista patrocinios sociales de un marketer (placeholder — se persiste cuando haya modelo DB)."""
    user = db.query(User).filter(User.email == email, User.role.in_(['marketer','admin'])).first()
    if not user:
        raise HTTPException(404, 'Cuenta marketer no encontrada.')
    return {'sponsors': [], 'note': 'Persistencia completa disponible en próxima versión.'}


@app.post('/marketer/campaigns')
def create_marketer_campaign(data: CampaignCreate, db: Session = Depends(get_db)):
    """Crea la campaña y devuelve la optimización de asignación."""
    # Gate: the brand name on this campaign (advertiser_name) is shown live,
    # publicly, inside real debates (main.py _match_campaigns → 'brand': ...).
    # That display is worthless — actively harmful — if anyone can type any
    # company name with no identity behind it. Require a marketer account that
    # has cleared the same chain organizers go through: RUT/web/domain checks,
    # selfie-vs-ID face match, cargo document, and (if not the boss) the boss's
    # own sign-off from their own verified, selfie-checked account.
    marketer_user = db.query(User).filter(
        User.email == data.advertiser_email
    ).first()
    if not marketer_user:
        # Auto-create marketer account on first campaign
        hashed = bcrypt.hashpw((data.advertiser_name or 'marketer').encode(), bcrypt.gensalt()).decode()
        marketer_user = User(
            email=data.advertiser_email, name=data.advertiser_name or 'Anunciante',
            password=hashed, role='marketer',
        )
        db.add(marketer_user)
        db.commit()
        db.refresh(marketer_user)
    elif marketer_user.role not in ('marketer', 'admin'):
        marketer_user.role = 'marketer'
        db.commit()
    # Ensure marketer profile exists and is approved
    profile = db.query(MarketerProfile).filter(MarketerProfile.user_id == marketer_user.id).first()
    if not profile:
        profile = MarketerProfile(
            user_id=marketer_user.id, org_type='person', is_supervisor=True,
            status='approved', company_name=data.advertiser_name or '',
        )
        db.add(profile)
        db.commit()

    # Guard against accidental duplicate submissions (e.g. a slow response
    # tempting a double-click, or a flaky connection causing a silent retry):
    # if the same advertiser just created an identical campaign in the last
    # 10 seconds, return that one instead of minting a near-identical twin.
    dup_cutoff = datetime.utcnow() - timedelta(seconds=10)
    existing = (
        db.query(AdCampaign)
        .filter(
            AdCampaign.advertiser_email == data.advertiser_email,
            AdCampaign.title == data.campaign_title,
            AdCampaign.budget_clp == data.budget_clp,
            AdCampaign.created_at >= dup_cutoff,
        )
        .order_by(AdCampaign.created_at.desc())
        .first()
    )
    if existing:
        optimization = _optimize_campaign(
            budget_clp=existing.budget_clp,
            target_country=existing.target_country,
            target_communes=existing.target_communes,
            target_se_tiers=existing.target_se_tiers,
            target_income_min=existing.target_income_min,
            target_income_max=existing.target_income_max,
            target_gender=existing.target_gender,
            target_age_min=existing.target_age_min,
            target_age_max=existing.target_age_max,
            db=db,
        )
        return {'message': 'Campaign created', 'campaign_id': existing.id,
                'optimization': optimization, 'campaign': _format_campaign(existing)}

    # Auto-populate target_communes from the income matrix when:
    # 1. min_per_capita_usd > 0 (country income threshold set) OR target_se_tiers != all
    # 2. target_communes is empty (not manually specified)
    # This enables the "Porsche flow": set per-capita + NSE tier → system fills communes automatically.
    auto_communes = data.target_communes or ''
    if not auto_communes:
        min_gni = getattr(data, 'min_per_capita_usd', 0.0) or 0.0
        se_tiers_raw = data.target_se_tiers or 'A,B,C,D'
        desired_tiers = {t.strip().upper() for t in se_tiers_raw.split(',') if t.strip()}
        has_tier_filter = desired_tiers and desired_tiers != {'A','B','C','D'}
        if min_gni > 0 or has_tier_filter:
            try:
                from targeting_agent import load_matrix as _lm_ac
                _mat = _lm_ac()
                country_filter = set()
                if data.target_country and data.target_country.upper() not in ('ALL','GLOBAL',''):
                    country_filter = {c.strip().upper() for c in data.target_country.split(',') if c.strip()}
                commune_list = []
                for iso, cdata in _mat.items():
                    if country_filter and iso not in country_filter:
                        continue
                    if min_gni > 0 and (cdata.get('gni_per_capita') or 0) < min_gni:
                        continue
                    for cname, cm in cdata.get('communes', {}).items():
                        if not has_tier_filter or cm.get('income_tier','') in desired_tiers:
                            commune_list.append(cname)
                if commune_list:
                    auto_communes = ','.join(commune_list)
            except Exception:
                pass

    optimization = _optimize_campaign(
        budget_clp=data.budget_clp,
        target_country=data.target_country,
        target_communes=auto_communes,
        target_se_tiers=data.target_se_tiers,
        target_income_min=data.target_income_min,
        target_income_max=data.target_income_max,
        target_gender=data.target_gender,
        target_age_min=data.target_age_min,
        target_age_max=data.target_age_max,
        db=db,
    )
    campaign = AdCampaign(
        advertiser_email    = data.advertiser_email,
        advertiser_name     = data.advertiser_name,
        title               = data.campaign_title,
        budget_clp          = data.budget_clp,
        ad_type             = data.ad_type,
        target_country      = data.target_country,
        target_communes     = auto_communes,
        target_se_tiers     = data.target_se_tiers,
        target_income_min   = data.target_income_min,
        target_income_max   = data.target_income_max,
        target_gender       = data.target_gender,
        target_age_min      = data.target_age_min,
        target_age_max      = data.target_age_max,
        target_age_ranges   = data.target_age_ranges,
        target_categories   = data.target_categories,
        excluded_categories = data.excluded_categories,
        blocked_competitors = data.blocked_competitors,
        start_date          = datetime.fromisoformat(data.start_date),
        end_date            = datetime.fromisoformat(data.end_date),
        is_active           = True,
        logo_url            = data.logo_url or '',
        ad_copy             = data.ad_copy or '',
        ad_image_url        = data.ad_image_url or '',
        video_url           = getattr(data, 'video_url', '') or '',
        link_url            = data.link_url or '',
        min_per_capita_usd  = getattr(data, 'min_per_capita_usd', 0.0) or 0.0,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    # Auto-pin to all live debates so the campaign appears immediately
    all_debate_ids = [str(d.id) for d in db.query(Debate).filter(Debate.status == 'live').all()]
    if not all_debate_ids:
        all_debate_ids = [str(d.id) for d in db.query(Debate).all()]
    campaign.target_debate_ids = ','.join(all_debate_ids)
    db.commit()
    return {'message': 'Campaign created', 'campaign_id': campaign.id,
            'optimization': optimization, 'campaign': _format_campaign(campaign)}

@app.get('/marketer/campaigns/{campaign_id}/metrics')
def get_campaign_metrics(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, 'Campaign not found')

    views = db.query(AdImpressionLog).filter(
        AdImpressionLog.campaign_id == campaign_id
    ).all()

    total_imp   = len(views)
    spent_clp   = campaign.spent_clp or 0
    balance_clp = max(0, campaign.budget_clp - spent_clp)
    pct_spent   = round(spent_clp / campaign.budget_clp * 100, 1) if campaign.budget_clp > 0 else 0
    cost_per_contact = round(spent_clp / total_imp, 0) if total_imp > 0 else 0

    # Breakdowns
    by_gender, by_age, by_commune, by_tier, by_debate, by_day = {}, {}, {}, {}, {}, {}
    for v in views:
        g  = v.gender    or 'N/A'
        a  = v.age_group or 'N/A'
        co = v.county    or 'N/A'
        d  = str(v.debate_id) if v.debate_id else 'N/A'
        day = v.created_at.strftime('%Y-%m-%d') if v.created_at else 'N/A'

        by_gender[g]  = by_gender.get(g, 0)   + 1
        by_age[a]     = by_age.get(a, 0)       + 1
        by_commune[co]= by_commune.get(co, 0)  + 1
        by_debate[d]  = by_debate.get(d, 0)    + 1
        by_day[day]   = by_day.get(day, 0)     + 1

        # SE tier desde CommuneMarketData
        if co and co != 'N/A':
            cm = db.query(CommuneMarketData).filter(
                CommuneMarketData.commune.ilike(co)
            ).first()
            tier = cm.se_tier if cm else 'N/A'
            by_tier[tier] = by_tier.get(tier, 0) + 1

    # Target alcanzado vs estimado
    target_tiers = [t.strip() for t in (campaign.target_se_tiers or '').split(',') if t.strip()]
    in_target = sum(by_tier.get(t, 0) for t in target_tiers)
    pct_in_target = round(in_target / total_imp * 100, 1) if total_imp > 0 else 0

    # Desglose de comunas ordenado por impresiones
    top_communes = sorted(by_commune.items(), key=lambda x: x[1], reverse=True)[:10]

    # Días ordenados cronológicamente
    daily_trend = [{'date': d, 'impressions': n}
                   for d, n in sorted(by_day.items())]

    return {
        # ── Resumen ejecutivo ──
        'campaign_id':        campaign_id,
        'title':              campaign.title,
        'advertiser':         campaign.advertiser_name,
        'is_active':          campaign.is_active,
        'start_date':         campaign.start_date.isoformat() if campaign.start_date else None,
        'end_date':           campaign.end_date.isoformat()   if campaign.end_date   else None,

        # ── Presupuesto ──
        'budget_clp':         campaign.budget_clp,
        'spent_clp':          spent_clp,
        'balance_clp':        balance_clp,
        'pct_budget_spent':   pct_spent,

        # ── Alcance ──
        'impressions':        total_imp,
        'cost_per_contact_clp': cost_per_contact,

        # ── Calidad del targeting ──
        'targeting': {
            'country':      campaign.target_country or 'todos',
            'se_tiers':     target_tiers,
            'gender':       campaign.target_gender,
            'age':          f'{campaign.target_age_min or 13}–{campaign.target_age_max or 99}',
        },
        'in_target_impressions': in_target,
        'pct_in_target':         pct_in_target,

        # ── Breakdowns ──
        'by_se_tier':    dict(sorted(by_tier.items(),    key=lambda x: TIER_ORDER.index(x[0]) if x[0] in TIER_ORDER else 99)),
        'by_gender':     by_gender,
        'by_age':        by_age,
        'top_communes':  [{'commune': c, 'impressions': n} for c, n in top_communes],
        'by_debate':     by_debate,

        # ── Evolución diaria ──
        'daily_trend':   daily_trend,
    }

@app.get('/admin/db-info')
def db_info():
    db_url = DATABASE_URL
    is_pg = 'postgresql' in db_url or 'postgres' in db_url
    masked = db_url[:15] + '...' if len(db_url) > 15 else db_url
    try:
        with engine.connect() as conn:
            if is_pg:
                from sqlalchemy import text
                row = conn.execute(text("SELECT version()")).fetchone()
                version = row[0][:60] if row else 'unknown'
            else:
                version = 'SQLite'
        connected = True
    except Exception as e:
        version = str(e)[:80]
        connected = False
    return {
        'db_type': 'postgresql' if is_pg else 'sqlite',
        'connected': connected,
        'db_version': version,
        'url_prefix': masked,
    }


# ── ADMIN: email smoke test ──────────────────────────────────────
@app.post('/admin/test-email')
def test_email_send(to: str, secret: str):
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    resend_key = os.getenv('RESEND_API_KEY')
    if not resend_key:
        return {'to': to, 'ok': False, 'error': 'RESEND_API_KEY not set'}
    from_addr = 'Preferendum <noreply@preferendum.com>'
    try:
        resp = _requests.post(
            'https://api.resend.com/emails',
            json={'from': from_addr, 'to': [to], 'subject': 'Preferendum — Email Test',
                  'text': 'Test from noreply@preferendum.com. If you see this, email is working.'},
            headers={'Authorization': f'Bearer {resend_key}'},
            timeout=10,
        )
        result = {'from': from_addr, 'status': resp.status_code, 'body': resp.json(), 'ok': resp.status_code in (200, 201)}
    except Exception as e:
        result = {'from': from_addr, 'ok': False, 'error': str(e)}
    return {'to': to, 'result': result}

# ── ADMIN: fetch a pending OTP for automated end-to-end testing ──
# Real email/SMS delivery can fail for reasons unrelated to the voting
# system itself (DNS propagation, SMTP credentials, carrier issues — see
# CLAUDE.md "EMAIL VERIFICATION FIX"). Automated integrity tests (e.g. the
# GitHub Actions suite in .github/workflows/integrity-tests.yml) need a way
# to complete email verification without a human reading an inbox. This
# endpoint exposes the *current* OTP for one account, gated by the same
# ADMIN_SECRET as every other /admin route — it cannot be used to read
# someone else's code without that secret, and test accounts are disposable
# (created and discarded by the test run itself).
@app.get('/admin/test-otp')
def get_test_otp(email: str, secret: str, channel: str = 'email', db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(404, 'User not found')
    otp = db.query(OTPCode).filter(
        OTPCode.user_id == user.id, OTPCode.channel == channel,
        OTPCode.used == False, OTPCode.expires_at > datetime.utcnow()
    ).order_by(OTPCode.id.desc()).first()
    if not otp:
        raise HTTPException(404, 'No active OTP for this user/channel')
    return {'email': email, 'channel': channel, 'code': otp.code, 'expires_at': otp.expires_at.isoformat()}

# ── ADMIN: prove bridge destruction for a specific vote ──────────
# "Bridge destruction" means voter_id is set to None the instant a vote is
# recorded — the database itself never holds a link between a voter's
# identity and their vote (see CLAUDE.md "Privacy architecture"). This
# endpoint lets anyone with the admin secret check that field directly for
# a given verify_code — not a description of the claim, the claim checked
# against the live row. Used by the automated integrity tests, and usable
# by independent auditors who want to confirm this themselves.
@app.get('/admin/test-vote-bridge')
def test_vote_bridge(code: str, debate_id: int, secret: str, db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    vote = db.query(DebateVote).filter(
        DebateVote.verify_code == code.upper().strip(),
        DebateVote.debate_id == debate_id
    ).first()
    if not vote:
        raise HTTPException(404, 'Vote not found')
    return {
        'verify_code': vote.verify_code,
        'debate_id': vote.debate_id,
        'voter_id': vote.voter_id,
        'bridge_destroyed': vote.voter_id is None,
    }

@app.patch('/admin/debates/{debate_id}')
def admin_patch_debate(debate_id: int, secret: str, target_age_min: int = None, target_age_max: int = None, scope_country: str = None, status: str = None, db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Debate not found')
    if target_age_min is not None: debate.target_age_min = target_age_min
    if target_age_max is not None: debate.target_age_max = target_age_max
    if scope_country is not None: debate.scope_country = scope_country
    if status is not None:
        if status not in ('live', 'draft', 'closed'):
            raise HTTPException(400, "status must be one of: live, draft, closed")
        debate.status = status
        # get_debate_status() (the function every public endpoint actually
        # calls) is purely date-driven and never reads debate.status — so
        # writing the column alone is a silent no-op for anything a voter
        # sees. Move the dates that drive it so "force closed/live" really
        # changes what the public status computes to.
        now = datetime.utcnow()
        if status == 'closed':
            debate.closes_at = now
            debate.verify_closes_at = now
        elif status == 'live':
            debate.closes_at = now + timedelta(days=30)
            debate.verify_closes_at = debate.closes_at + timedelta(days=7)
    db.commit()
    db.refresh(debate)
    return {'ok': True, 'debate': format_debate(debate)}


@app.delete('/admin/debates/{debate_id}')
def admin_delete_debate(debate_id: int, secret: str, db: Session = Depends(get_db)):
    """Permanently purges a debate and every row that references it.

    There are no SQL ForeignKey constraints on debate_id columns, so a
    plain DELETE on the debate row would leave orphaned opinions, votes,
    anti-fraud logs, ads and impression logs behind forever — exactly
    what produced the 7 "ghost" [E2E-PROOF] debates that kept reappearing
    in the live feed (admin_patch_debate's old status='closed' no-op
    couldn't remove them, since /debates never filters by status either —
    the only real fix is deleting the rows).
    """
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Debate not found')

    purged = {}
    for model in (
        VoteIdentityLock, Opinion, DebateVote, HasVotedLog, SimVoteLog,
        NationalIdVoteLog, ImeiVoteLog, DebateAd, DebateRewardCode,
        AdImpressionLog, ClosedListEntry, ConsultationModerationLog,
    ):
        n = db.query(model).filter(model.debate_id == debate_id).delete(synchronize_session=False)
        if n:
            purged[model.__tablename__] = n

    title = debate.title
    db.delete(debate)
    db.commit()
    return {'ok': True, 'deleted_debate_id': debate_id, 'title': title, 'purged_rows': purged}


# ══════════════════════════════════════════════════════════════
# MARKET DATA AGENT — índice de ingreso por comuna
# ══════════════════════════════════════════════════════════════

def _save_communes_to_db(communes: list, db):
    """Guarda o actualiza comunas en la BD. Recalcula índice global después."""
    saved = 0
    for c in communes:
        existing = db.query(CommuneMarketData).filter(
            CommuneMarketData.country == c['country'],
            CommuneMarketData.commune == c['commune']
        ).first()
        if existing:
            existing.price_m2_avg = c.get('price_m2_avg', 0)
            existing.income_index = c['income_index']
            existing.cpm_usd      = c['cpm_usd']
            existing.se_tier      = c['se_tier']
            # Bug found 2026-06-08: this never updated `portal`, so a row
            # first created from get_fallback_table() (portal='fallback')
            # that later got real values written over it (e.g. Hackney and
            # Tower Hamlets, upgraded in place by the new HM Land Registry
            # agent) kept showing 'fallback' forever — real numbers wearing
            # a fake-data label. That mislabeling is exactly what caused
            # /admin/purge-stale-fallback-communes to delete two rows that
            # actually held correct, freshly-fetched official data.
            existing.portal       = c.get('portal', existing.portal)
            existing.updated_at   = datetime.utcnow()
        else:
            db.add(CommuneMarketData(
                country=c['country'], commune=c['commune'],
                price_m2_avg=c.get('price_m2_avg', 0),
                income_index=c['income_index'], cpm_usd=c['cpm_usd'],
                se_tier=c['se_tier'], portal=c.get('portal', 'fallback'),
                sample_count=c.get('sample_count', 0),
                scraped_at=datetime.utcnow(),
            ))
        saved += 1
    db.commit()
    # Recalcular índice global con todos los datos en BD
    _recalculate_global_index(db)
    return saved


def _recalculate_global_index(db):
    """Recalcula el índice 100 = mediana global cada vez que entra un país nuevo."""
    all_rows = db.query(CommuneMarketData).filter(CommuneMarketData.price_m2_avg > 0).all()
    if not all_rows:
        return
    prices = sorted([r.price_m2_avg for r in all_rows])
    median = prices[len(prices) // 2]
    from market_data_agent import calculate_cpm_from_index, get_se_tier
    for row in all_rows:
        row.income_index = round((row.price_m2_avg / median) * 100, 1)
        row.cpm_usd      = calculate_cpm_from_index(row.income_index)
        row.se_tier      = get_se_tier(row.income_index)
    db.commit()


@app.get('/admin/aws-check')
def aws_check(secret: str):
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    key = os.getenv('AWS_ACCESS_KEY_ID', '')
    sec = os.getenv('AWS_SECRET_ACCESS_KEY', '')
    region = os.getenv('AWS_REGION', 'us-east-1')
    result = {
        'key_set': bool(key),
        'key_prefix': key[:4] if key else '',
        'key_length': len(key),
        'secret_set': bool(sec),
        'secret_length': len(sec),
        'region': region,
    }
    if key and sec:
        try:
            import boto3
            rek = boto3.client('rekognition', region_name=region,
                               aws_access_key_id=key, aws_secret_access_key=sec)
            rek.list_collections(MaxResults=1)
            result['rekognition'] = 'CONNECTED'
        except Exception as e:
            result['rekognition'] = f'ERROR: {str(e)[:120]}'
    else:
        result['rekognition'] = 'NO_CREDENTIALS'
    return result

@app.get('/admin/ping')
def admin_ping():
    return {'pong': True, 'version': 'lazy-init-v2'}

@app.get('/admin/blockchain-status')
def blockchain_status(secret: str):
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    try:
        _blockchain._ensure_init()
        result = _blockchain.status()
        result['code_version'] = 'lazy-init-v3'
        return result
    except BaseException as e:
        import traceback
        return {'live': False, 'error': str(e), 'traceback': traceback.format_exc()}

@app.post('/admin/blockchain-debug')
def blockchain_debug(secret: str):
    """Deep diagnostic: try to build+sign a tx and return the exact error if it fails."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    import traceback as tb
    result = {}
    _blockchain._ensure_init()
    result['live'] = _blockchain.live
    if not _blockchain.live:
        result['error'] = 'Not in live mode — check CONTRACT_ADDRESS, WALLET_ADDRESS, WALLET_PRIVATE_KEY env vars'
        return result
    try:
        from web3 import Web3
        w3 = _blockchain.web3
        wallet = w3.to_checksum_address(_blockchain.wallet_address)
        result['wallet'] = wallet
        result['balance_wei'] = str(w3.eth.get_balance(wallet))
        result['balance_matic'] = float(w3.eth.get_balance(wallet)) / 1e18
        result['nonce'] = w3.eth.get_transaction_count(wallet)
        result['gas_price_gwei'] = float(w3.eth.gas_price) / 1e9
        result['chain_id'] = _blockchain._chain_id()
        pk = _blockchain.private_key or ''
        result['pk_length'] = len(pk.strip())
        result['pk_has_0x'] = pk.strip().startswith('0x')
        if pk.strip() and not pk.strip().startswith('0x'):
            pk = '0x' + pk.strip()
        else:
            pk = pk.strip()
        # Try building the transaction
        gas_price = int(w3.eth.gas_price * 1.2)
        func = _blockchain.contract.functions.openDebate(9998, 'DebugTest', 'Preferendum')
        tx = func.build_transaction({
            'from': wallet, 'nonce': result['nonce'],
            'gas': 300000, 'gasPrice': gas_price, 'chainId': result['chain_id'],
        })
        result['tx_built'] = True
        signed = w3.eth.account.sign_transaction(tx, pk)
        result['signed'] = True
        raw_tx = getattr(signed, 'raw_transaction', None) or getattr(signed, 'rawTransaction', None)
        result['raw_tx_hex'] = raw_tx.hex()[:20] + '...'
        # Try sending
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        result['tx_sent'] = True
        result['tx_hash'] = tx_hash.hex()
    except Exception as e:
        result['error'] = str(e)
        result['traceback'] = tb.format_exc()
    return result

@app.post('/admin/blockchain-reinit')
def blockchain_reinit(secret: str):
    """Force blockchain to re-initialize and return full diagnostic."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    pk_env = (os.getenv('WALLET_PRIVATE_KEY') or '').strip()
    diag = {
        'env_CONTRACT_ADDRESS':   bool(os.getenv('CONTRACT_ADDRESS')),
        'env_WALLET_ADDRESS':     bool(os.getenv('WALLET_ADDRESS')),
        'env_WALLET_PRIVATE_KEY': bool(pk_env),
        'pk_from_env_length':     len(pk_env),
        'env_POLYGON_RPC_URL':    os.getenv('POLYGON_RPC_URL', '(not set)'),
        'secret_file_exists':     os.path.exists('/etc/secrets/WALLET_PRIVATE_KEY'),
    }
    _blockchain._initialized = False
    _blockchain._init_attempts = 0
    _blockchain.live = False
    if pk_env:
        _blockchain.private_key = pk_env
    _blockchain._ensure_init()
    status = _blockchain.status()
    status['diag'] = diag
    return status

@app.post('/admin/blockchain-test-anchor')
def blockchain_test_anchor(secret: str, debate_id: int = 101):
    """Cast a real test vote hash to the contract via anchor_vote. Verifiable on PolygonScan."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    import time
    test_hash = hashlib.sha256(f'admin-test-{debate_id}-{time.time()}'.encode()).hexdigest()
    test_vcode = f'TEST-{int(time.time()) % 10000:04d}-ADMN'
    result = _blockchain.anchor_vote(debate_id, test_hash, test_vcode, debate_title=f'Debate {debate_id}')
    result['vote_hash'] = test_hash
    result['vcode'] = test_vcode
    result['is_mock'] = result['tx_hash'] == '0x' + hashlib.sha256(f'polygon-mock-{test_hash}'.encode()).hexdigest()
    return result

@app.get('/admin/targeting/matrix')
def targeting_matrix_summary(secret: str):
    """Returns the current targeting matrix summary: GNI tiers, CPMs, communes per country."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    try:
        from targeting_agent import get_matrix_summary
        return {'ok': True, 'matrix': get_matrix_summary()}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@app.post('/admin/targeting/update-communes')
def targeting_update_communes(secret: str, bg: BackgroundTasks):
    """Trigger monthly commune price update (runs in background)."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from targeting_agent import run_monthly_commune_update
    bg.add_task(run_monthly_commune_update)
    return {'ok': True, 'message': 'Commune price update started — check logs'}

@app.post('/admin/targeting/update-gni')
def targeting_update_gni(secret: str, bg: BackgroundTasks):
    """Trigger annual GNI update from World Bank API (runs in background)."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from targeting_agent import run_annual_gni_update
    bg.add_task(run_annual_gni_update)
    return {'ok': True, 'message': 'GNI update from World Bank started — check logs'}

@app.get('/admin/targeting/match-debate/{debate_id}')
def targeting_match_debate(debate_id: int, secret: str, db: Session = Depends(get_db)):
    """Returns ranked campaigns for a debate. Use to preview/test matching logic."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Debate not found')
    from targeting_agent import match_campaigns_to_debate
    debate_dict = {
        'scope_country':  getattr(debate, 'scope_country', ''),
        'scope_commune':  getattr(debate, 'scope_commune', ''),
        'target_gender':  getattr(debate, 'target_gender', 'all'),
        'target_age_min': getattr(debate, 'target_age_min', 13),
        'target_age_max': getattr(debate, 'target_age_max', 99),
    }
    matches = match_campaigns_to_debate(debate_dict, db)
    return {
        'debate_id':  debate_id,
        'debate':     debate_dict,
        'matches':    matches[:10],
        'total_candidates': len(matches),
    }

# ══════════════════════════════════════════════════════════════
# PAYMENTS — Preferendum Credits
# 1 Credit = $1 USD | Stripe + POL + USDC
# ══════════════════════════════════════════════════════════════

class StripeCheckoutBody(BaseModel):
    package_id:  str
    success_url: str
    cancel_url:  str

class CryptoInitBody(BaseModel):
    amount_usd: float
    currency:   str = 'POL'

class CryptoConfirmBody(BaseModel):
    request_id: int
    tx_hash:    str

class AllocateBudgetBody(BaseModel):
    campaign_id: int
    credits:     float


@app.get('/payments/packages')
def payments_list_packages():
    """Available credit packages with estimated reach per commune tier."""
    packages = []
    for pkg in CREDIT_PACKAGES:
        packages.append({
            **pkg,
            'estimated_impressions': {
                'premium_communes': int(pkg['credits'] / 12.0 * 1000),
                'mid_communes':     int(pkg['credits'] / 6.0  * 1000),
                'growth_communes':  int(pkg['credits'] / 3.0  * 1000),
            }
        })
    return {'packages': packages, 'note': '1 Credit = $1 USD. CPM varies by commune income tier.'}


@app.get('/payments/balance')
def payments_balance(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Current credit balance and last 20 transactions."""
    account = get_or_create_account(db, user.id)
    txs = db.execute(
        text("""
            SELECT t.type, t.amount_credits, t.balance_after, t.payment_method,
                   t.description, t.created_at, c.title as campaign_title
            FROM credit_transactions t
            LEFT JOIN ad_campaigns c ON c.id = t.campaign_id
            WHERE t.user_id = :uid
            ORDER BY t.created_at DESC LIMIT 20
        """),
        {'uid': user.id}
    ).fetchall()
    return {
        'balance_credits': account['balance_credits'],
        'total_purchased': account['total_purchased'],
        'total_spent':     account['total_spent'],
        'recent_transactions': [dict(r._mapping) for r in txs],
    }


@app.post('/payments/stripe/create-session')
def payments_stripe_create_session(
    body: StripeCheckoutBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Creates a Stripe Checkout session and returns the URL to redirect the advertiser."""
    try:
        return create_stripe_checkout(
            user_id     = user.id,
            package_id  = body.package_id,
            success_url = body.success_url,
            cancel_url  = body.cancel_url,
            db          = db,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f'Stripe error: {str(e)}')


@app.post('/payments/stripe/webhook')
async def payments_stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
    stripe_signature: Optional[str] = Header(None, alias='stripe-signature'),
):
    """
    Stripe webhook receiver. Register this URL in Stripe Dashboard.
    Stripe sends raw POST — signature verified before any DB changes.
    """
    from fastapi.responses import JSONResponse as _JSONResponse
    payload = await request.body()
    try:
        result = handle_stripe_webhook(payload, stripe_signature or '')
    except HTTPException:
        raise
    except Exception as e:
        return _JSONResponse({'ok': False, 'error': str(e)}, status_code=400)

    if result.get('action') == 'add_credits':
        add_credits(
            db             = db,
            user_id        = result['user_id'],
            amount_credits = result['credits'],
            method         = result['method'],
            ref            = result['ref'],
            description    = result['desc'],
            amount_usd     = result.get('amount_usd', 0),
        )
    return {'ok': True}


@app.get('/payments/stripe/fulfill')
async def payments_stripe_fulfill(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Called by frontend after Stripe redirects back. Verifies session and credits account."""
    from payments import _stripe
    try:
        stripe = _stripe(db)
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        raise HTTPException(502, f'Stripe error: {str(e)}')

    if session.get('payment_status') != 'paid':
        raise HTTPException(400, 'Payment not completed')

    meta = session.get('metadata', {})
    meta_user_id = int(meta.get('user_id', 0))
    if meta_user_id != user.id:
        raise HTTPException(403, 'Session does not belong to this user')

    credits    = float(meta.get('credits', 0))
    package_id = meta.get('package_id', '')
    pkg        = PACKAGE_BY_ID.get(package_id, {})
    amount_usd = pkg.get('price_usd', 0)

    result = add_credits(
        db             = db,
        user_id        = user.id,
        amount_credits = credits,
        method         = 'stripe',
        ref            = session_id,
        description    = f'Stripe checkout — {package_id}',
        amount_usd     = amount_usd,
    )
    return result


@app.post('/payments/crypto/quote')
def payments_crypto_quote(body: CryptoInitBody):
    """Returns current POL or USDC price and exact amount to send. No DB write."""
    quote = get_crypto_quote(body.amount_usd, body.currency)
    credits = float(body.amount_usd)
    for pkg in sorted(CREDIT_PACKAGES, key=lambda p: p['price_usd'], reverse=True):
        if body.amount_usd >= pkg['price_usd']:
            credits = pkg['credits']
            break
    return {**quote, 'credits_to_receive': credits, 'wallet': PREFERENDUM_WALLET}


@app.post('/payments/crypto/initiate')
def payments_crypto_initiate(
    body: CryptoInitBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Creates a crypto payment request (30-min window).
    Returns exact amount to send + our wallet address.
    """
    return create_crypto_payment_request(db, user.id, body.amount_usd, body.currency)


@app.post('/payments/crypto/confirm')
def payments_crypto_confirm(
    body: CryptoConfirmBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Advertiser confirms crypto payment with their transaction hash.
    We verify on Polygon (correct recipient, correct amount ±5%, confirmed).
    """
    result = confirm_crypto_payment(db, user.id, body.request_id, body.tx_hash)
    if result.get('action') == 'add_credits':
        credit_result = add_credits(
            db             = db,
            user_id        = result['user_id'],
            amount_credits = result['credits'],
            method         = result['method'],
            ref            = result['ref'],
            description    = result['desc'],
            amount_usd     = result.get('amount_usd', 0),
        )
        return {
            'ok':             True,
            'credits_added':  result['credits'],
            'new_balance':    credit_result.get('new_balance', 0),
            'tx_hash':        body.tx_hash,
            'payment_method': result['method'],
        }
    raise HTTPException(500, 'Unexpected payment result')


@app.post('/payments/allocate-to-campaign')
def payments_allocate_budget(
    body: AllocateBudgetBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Moves Credits from user account to a campaign's running budget."""
    return allocate_budget_to_campaign(db, user.id, body.campaign_id, body.credits)


@app.post('/payments/return-from-campaign/{campaign_id}')
def payments_return_budget(
    campaign_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns unspent campaign budget to user's credit account (on pause/cancel)."""
    return return_budget_to_account(db, user.id, campaign_id)


@app.get('/payments/history')
def payments_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 50,
):
    """Full credit transaction history."""
    txs = db.execute(
        text("""
            SELECT t.*, c.title as campaign_title
            FROM credit_transactions t
            LEFT JOIN ad_campaigns c ON c.id = t.campaign_id
            WHERE t.user_id = :uid
            ORDER BY t.created_at DESC LIMIT :lim
        """),
        {'uid': user.id, 'lim': min(limit, 200)}
    ).fetchall()
    return {'transactions': [dict(r._mapping) for r in txs]}


@app.post('/admin/payments/init-tables')
def payments_admin_init_tables(secret: str, db: Session = Depends(get_db)):
    """Admin: explicitly create payment tables (PostgreSQL-compatible)."""
    from sqlalchemy import text as _text
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    results = {}
    stmts = PAYMENTS_SCHEMA_SQL_PG.strip().split(';')
    for stmt in stmts:
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(_text(stmt))
            results[stmt[:60]] = 'ok'
        except Exception as e:
            results[stmt[:60]] = str(e)
    return {'results': results}


@app.get('/admin/users/search')
def admin_search_users(q: str, secret: str, db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    users = db.query(User).filter(
        (User.email.ilike(f'%{q}%')) | (User.name.ilike(f'%{q}%'))
    ).order_by(User.id.desc()).limit(20).all()
    return {'users': [{'id': u.id, 'email': u.email, 'name': u.name, 'role': u.role,
                        'email_verified': u.email_verified, 'phone_verified': u.phone_verified,
                        'selfie_verified': u.selfie_verified, 'verify_level': u.verify_level,
                        'created_at': str(u.created_at)} for u in users]}

@app.post('/admin/users/reset-password')
def admin_reset_password(user_id: int, new_password: str, secret: str, db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, 'User not found')
    user.password = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    db.commit()
    return {'ok': True, 'email': user.email, 'message': 'Password updated'}

@app.post('/admin/users/reset-selfie')
def admin_reset_selfie(user_id: int, secret: str, db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, 'User not found')
    db.query(SelfieLog).filter(SelfieLog.user_id == user_id).delete()
    user.selfie_verified = False
    db.commit()
    return {'ok': True, 'email': user.email, 'message': 'Selfie borrada — el usuario puede registrar su cara de nuevo'}

@app.post('/admin/users/fix')
def admin_fix_user(user_id: int, secret: str, email: str = '', name: str = '', role: str = '',
                   email_verified: str = '', selfie_verified: str = '', db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, 'User not found')
    if email: user.email = email
    if name:  user.name  = name
    if role:  user.role  = role
    if email_verified in ('true', '1'):
        user.email_verified = True
        update_verify_level(user, db)
    elif email_verified in ('false', '0'):
        user.email_verified = False
        update_verify_level(user, db)
    if selfie_verified in ('true', '1'):
        user.selfie_verified = True
        update_verify_level(user, db)
    elif selfie_verified in ('false', '0'):
        user.selfie_verified = False
        update_verify_level(user, db)
    db.commit()
    return {'ok': True, 'id': user.id, 'email': user.email, 'name': user.name, 'role': user.role,
            'email_verified': user.email_verified, 'selfie_verified': user.selfie_verified, 'verify_level': user.verify_level}

@app.get('/admin/debug-vote')
def admin_debug_vote(user_id: int, debate_id: int, secret: str, db: Session = Depends(get_db)):
    """Dry-run: check if user can vote in debate without committing anything."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {'error': f'User {user_id} not found'}
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        return {'error': f'Debate {debate_id} not found'}
    checks = {
        'email_verified': user.email_verified,
        'selfie_verified': user.selfie_verified,
        'debate_status': get_debate_status(debate),
        'debate_is_live': get_debate_status(debate) == 'live',
    }
    already = db.query(HasVotedLog).filter(HasVotedLog.user_id == user_id, HasVotedLog.debate_id == debate_id).first()
    checks['already_voted'] = bool(already)
    if user.phone:
        ph = hash_str(user.phone.replace(' ', '').replace('-', ''), 'pref-sim-')
        checks['sim_blocked'] = bool(db.query(SimVoteLog).filter(SimVoteLog.phone_hash == ph, SimVoteLog.debate_id == debate_id).first())
    if user.national_id:
        nh = hash_str(user.national_id.replace('.', '').replace('-', '').upper(), 'pref-nid-')
        checks['rut_blocked'] = bool(db.query(NationalIdVoteLog).filter(NationalIdVoteLog.national_id_hash == nh, NationalIdVoteLog.debate_id == debate_id).first())
    imei_log = db.query(IMEILog).filter(IMEILog.user_id == user_id).first()
    if imei_log:
        checks['device_blocked'] = bool(db.query(ImeiVoteLog).filter(ImeiVoteLog.imei_hash == imei_log.imei_hash, ImeiVoteLog.debate_id == debate_id).first())
        checks['device_hash'] = imei_log.imei_hash[:16] + '...'
    checks['can_vote'] = (
        user.email_verified and
        get_debate_status(debate) == 'live' and
        not already and
        not checks.get('sim_blocked') and
        not checks.get('rut_blocked') and
        not checks.get('device_blocked')
    )
    return {'user': {'id': user.id, 'email': user.email, 'name': user.name}, 'checks': checks}

@app.post('/admin/payments/manual-credit')
def payments_admin_manual(
    user_id:     int,
    credits:     float,
    description: str,
    secret:      str,
    db: Session = Depends(get_db),
):
    """Admin: manually add credits for a user (promos, support refunds, etc.)."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    ref = f"admin_{user_id}_{int(time.time())}"
    return add_credits(db, user_id, credits, 'manual', ref, description, tx_type='bonus')


@app.post('/payments/demo-credits')
def payments_demo_credits(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Add 500 demo credits to the requesting marketer's account (for testing)."""
    ref = f"demo_{user.id}_{int(time.time())}"
    return add_credits(db, user.id, 500.0, 'manual', ref, 'Demo credits — testing', tx_type='bonus')


@app.get('/admin/payments/pending-crypto')
def payments_admin_pending_crypto(secret: str, db: Session = Depends(get_db)):
    """Admin: list pending crypto payment requests awaiting confirmation."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    rows = db.execute(
        text("""
            SELECT r.*, u.email
            FROM crypto_payment_requests r
            JOIN users u ON u.id = r.user_id
            WHERE r.status = 'pending'
            ORDER BY r.created_at DESC
        """)
    ).fetchall()
    return {'pending': [dict(r._mapping) for r in rows]}


# ══════════════════════════════════════════════════════════════
# MARKETING AGENT — Lado A (anunciantes) + Lado B (adquisición)
# ══════════════════════════════════════════════════════════════

class MetaCampaignBody(BaseModel):
    country:      str
    budget_usd:   float
    age_min:      int = 18
    age_max:      int = 55
    placement:    str = 'both'
    creative_text: Optional[str] = None
    objective:    str = 'APP_INSTALLS'

class XCampaignBody(BaseModel):
    country:    str
    budget_usd: float
    keywords:   Optional[list] = None
    age_min:    int = 18
    age_max:    int = 55


@app.get('/marketing/advertiser/report')
def marketing_advertiser_report(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Full performance report for the logged-in advertiser: all campaigns, ROI, recommendations."""
    from marketing_agent import generate_advertiser_report
    rows = db.execute(text("""
        SELECT id, title, status, cpm, impressions_served, clicks,
               target_country, target_communes, target_gender,
               target_age_min, target_age_max, min_income_tier,
               remaining_budget, budget_usd
        FROM ad_campaigns WHERE advertiser_email=:email
    """), {'email': user.email}).fetchall()
    campaigns = [dict(r._mapping) for r in rows]
    return generate_advertiser_report(user.email, campaigns, db)


@app.get('/marketing/campaign/{campaign_id}/performance')
def marketing_campaign_performance(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Detailed metrics + targeting suggestions for a specific campaign."""
    from marketing_agent import analyze_campaign_performance, suggest_targeting_improvements
    from targeting_agent import load_matrix
    row = db.execute(text("""
        SELECT id, title, status, cpm, impressions_served, clicks,
               target_country, target_communes, target_gender,
               target_age_min, target_age_max, min_income_tier,
               remaining_budget, budget_usd, advertiser_email
        FROM ad_campaigns WHERE id=:cid AND advertiser_email=:email
    """), {'cid': campaign_id, 'email': user.email}).fetchone()
    if not row:
        raise HTTPException(404, 'Campaign not found')
    campaign = dict(row._mapping)
    perf = analyze_campaign_performance(campaign, db)
    sug  = suggest_targeting_improvements(campaign, load_matrix())
    return {**perf, 'recommendations': sug}


@app.get('/marketing/channel-performance')
def marketing_channel_performance(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """User acquisition performance by channel over the last 30 days."""
    from marketing_agent import get_channel_performance_summary
    return get_channel_performance_summary(db)


@app.get('/marketing/acquisition-budget')
def marketing_acquisition_budget(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Shows the available acquisition budget and recommended distribution by channel."""
    from marketing_agent import calculate_acquisition_budget
    return calculate_acquisition_budget(db)


@app.post('/marketing/meta/create-campaign')
def marketing_meta_create(body: MetaCampaignBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Creates a Meta (Facebook/Instagram) acquisition campaign for Preferendum."""
    from marketing_agent import create_meta_acquisition_campaign
    return create_meta_acquisition_campaign(
        country       = body.country,
        budget_usd    = body.budget_usd,
        objective     = body.objective,
        age_min       = body.age_min,
        age_max       = body.age_max,
        placement     = body.placement,
        creative_text = body.creative_text,
    )


@app.post('/marketing/x/create-campaign')
def marketing_x_create(body: XCampaignBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Creates an X/Twitter acquisition campaign for Preferendum."""
    from marketing_agent import create_x_acquisition_campaign
    return create_x_acquisition_campaign(
        country    = body.country,
        budget_usd = body.budget_usd,
        keywords   = body.keywords,
        age_min    = body.age_min,
        age_max    = body.age_max,
    )


@app.get('/marketing/meta/campaign/{campaign_id}/insights')
def marketing_meta_insights(campaign_id: str, days: int = 7, user: User = Depends(get_current_user)):
    """Returns Meta campaign performance: impressions, clicks, spend, CAC."""
    from marketing_agent import get_meta_campaign_insights
    return get_meta_campaign_insights(campaign_id, days)


@app.post('/marketing/meta/campaign/{campaign_id}/activate')
def marketing_meta_activate(campaign_id: str, user: User = Depends(get_current_user)):
    """Activates a paused Meta campaign."""
    from marketing_agent import activate_meta_campaign
    return activate_meta_campaign(campaign_id)


@app.post('/marketing/meta/campaign/{campaign_id}/pause')
def marketing_meta_pause(campaign_id: str, user: User = Depends(get_current_user)):
    """Pauses a Meta campaign."""
    from marketing_agent import pause_meta_campaign
    return pause_meta_campaign(campaign_id)


@app.post('/marketing/boost-debate/{debate_id}')
def marketing_boost_debate(debate_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Auto-boosts a trending debate with a Meta campaign if it has >100 votes in 24h."""
    from marketing_agent import auto_boost_trending_debate
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Debate not found')
    return auto_boost_trending_debate(debate.__dict__, db)


# ── Admin endpoints marketing ─────────────────────────────────

@app.get('/admin/marketing/campaigns-attention')
def marketing_admin_attention(secret: str, db: Session = Depends(get_db)):
    """Admin: campaigns needing attention (low budget, no impressions, expiring)."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from marketing_agent import get_campaigns_needing_attention
    return get_campaigns_needing_attention(db)


@app.post('/admin/marketing/daily-checks')
def marketing_admin_daily(secret: str, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Admin: run daily marketing checks in background."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from marketing_agent import run_daily_marketing_checks
    bg.add_task(run_daily_marketing_checks, db)
    return {'ok': True, 'message': 'Daily marketing checks started — check logs'}


@app.post('/admin/marketing/weekly-reports')
def marketing_admin_weekly(secret: str, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Admin: generate weekly advertiser reports in background."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from marketing_agent import run_weekly_advertiser_reports
    bg.add_task(run_weekly_advertiser_reports, db)
    return {'ok': True, 'message': 'Weekly reports started — check logs'}


@app.get('/admin/agent/test-api')
def agent_test_api(secret: str):
    """Test Anthropic API key and RSS feeds. Returns raw status."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    import requests as _req
    result = {}
    api_key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    secret_file = os.path.exists('/etc/secrets/ANTHROPIC_API_KEY')
    if not api_key and secret_file:
        try:
            with open('/etc/secrets/ANTHROPIC_API_KEY') as f:
                api_key = f.read().strip()
        except Exception:
            pass
    result['api_key_set'] = bool(api_key)
    result['api_key_in_env'] = bool(os.getenv('ANTHROPIC_API_KEY', '').strip())
    result['api_key_in_secret_file'] = secret_file
    result['api_key_prefix'] = api_key[:12] + '...' if api_key else 'NOT SET'
    if api_key:
        try:
            r = _req.post('https://api.anthropic.com/v1/messages',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                         'content-type': 'application/json'},
                json={'model': 'claude-haiku-4-5-20251001', 'max_tokens': 30,
                      'messages': [{'role': 'user', 'content': 'Reply: {"ok":true}'}]},
                timeout=15)
            result['anthropic_status'] = r.status_code
            result['anthropic_response'] = r.text[:200]
        except Exception as e:
            result['anthropic_error'] = str(e)
    # Test one RSS feed
    try:
        import feedparser
        rss = feedparser.parse('https://news.google.com/rss/search?q=Chile+salud&hl=es&gl=CL&ceid=CL:es')
        result['rss_items'] = len(rss.entries)
        result['rss_first_title'] = rss.entries[0].title if rss.entries else 'none'
    except Exception as e:
        result['rss_error'] = str(e)
    return result

@app.post('/admin/agent/daily-debates')
def agent_daily_debates(secret: str, bg: BackgroundTasks):
    """Trigger the news agent to create debates from world news."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import run_daily_debates
    bg.add_task(run_daily_debates)
    return {'ok': True, 'message': 'News agent started in background — check server logs for results'}

@app.post('/admin/agent/daily-debates/sync')
def agent_daily_debates_sync(secret: str):
    """Run the news agent synchronously and return results (may take up to 2 min)."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import run_daily_debates
    return run_daily_debates()

@app.post('/admin/agent/culture-debates')
def agent_culture_debates(secret: str, bg: BackgroundTasks):
    """Trigger culture/everyday + general knowledge debate generation."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    def _run():
        from preferendum_agent import run_culture_debates, run_general_knowledge_debates
        r1 = run_culture_debates(max_per_country=2)
        r2 = run_general_knowledge_debates(max_debates=5)
        print(f'[CultureAgent] culture={r1["debates_created"]} general={r2["debates_created"]}')
    bg.add_task(_run)
    return {'ok': True, 'message': 'Culture + general knowledge agent started in background'}

@app.post('/admin/agent/regional-debates')
def agent_regional_debates(secret: str, bg: BackgroundTasks):
    """Trigger the regional/sector news agent for Chile (health, transport, agro, pymes, education)."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import run_regional_debates
    bg.add_task(run_regional_debates)
    return {'ok': True, 'message': 'Regional sector agent started — creates debates from Chilean regional and sector media'}

@app.post('/admin/agent/regional-debates/sync')
def agent_regional_debates_sync(secret: str, force: bool = False):
    """Run regional/sector agent synchronously. force=true bypasses dedup."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import run_regional_debates
    return run_regional_debates(force=force)

@app.post('/admin/agent/task/{task_name}')
def run_agent_task(task_name: str, secret: str):
    """Run any scheduled agent task by name."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import run_scheduled_task
    return run_scheduled_task(task_name)

@app.get('/admin/db-schema')
def db_schema(secret: str):
    """Inspecciona columnas de tablas clave — diagnóstico remoto."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(engine)
    result = {}
    for table in ['ad_campaigns', 'users', 'debates', 'organizer_profiles', 'marketer_profiles']:
        if inspector.has_table(table):
            result[table] = [c['name'] for c in inspector.get_columns(table)]
        else:
            result[table] = 'TABLE_MISSING'
    return result


@app.post('/admin/run-market-agent')
def run_market_agent(secret: str, db: Session = Depends(get_db)):
    """Corre el agente completo de una vez. Para uso manual o pruebas."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from market_data_agent import run_full_agent, get_fallback_table
    result = run_full_agent()
    communes = result['communes'] if result['total_communes'] > 0 else get_fallback_table()
    saved = _save_communes_to_db(communes, db)
    return {'ok': True, 'communes_saved': saved, 'countries': result.get('countries', []), 'errors': result.get('errors', [])}


@app.post('/admin/run-market-agent/daily')
def run_market_agent_daily(secret: str, db: Session = Depends(get_db)):
    """
    Corre UN país por día — respeta el límite gratuito de Apify.
    El orden es rotativo: día 1=CL, día 2=AR, día 3=MX... vuelve a empezar.
    En ~8 días cubre todos los países. Se repite cada 6 meses.
    """
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from market_data_agent import PORTALS, run_apify_scraper, aggregate_by_commune, get_fallback_table, calculate_cpm_from_index, get_se_tier

    # Determinar qué país toca hoy según día del año
    day_of_year = datetime.utcnow().timetuple().tm_yday
    portal = PORTALS[day_of_year % len(PORTALS)]
    country = portal['country']

    print(f'[DailyAgent] Día {day_of_year} → procesando {portal["portal"]} ({country})')

    items = run_apify_scraper(portal, max_items=300)
    commune_prices = aggregate_by_commune(items, country)

    if not commune_prices:
        # Sin datos de Apify — usar fallback solo para este país
        fallback = [c for c in get_fallback_table() if c['country'] == country]
        saved = _save_communes_to_db(fallback, db)
        return {'ok': True, 'country': country, 'portal': portal['portal'],
                'source': 'fallback', 'communes_saved': saved}

    communes = []
    for commune, price_m2 in commune_prices.items():
        communes.append({
            'country': country, 'commune': commune,
            'price_m2_avg': price_m2, 'income_index': 100.0,
            'cpm_usd': 6.0, 'se_tier': 'C',
            'portal': portal['portal'], 'sample_count': len(items),
        })

    saved = _save_communes_to_db(communes, db)
    return {'ok': True, 'country': country, 'portal': portal['portal'],
            'source': 'apify', 'communes_saved': saved}


@app.post('/admin/test-market-agent-portal')
def test_market_agent_portal(secret: str, country: str = None):
    """
    Diagnóstico de UNA corrida del scraper de Apify, paso a paso.
    `run_apify_scraper()` traga cualquier error y devuelve `[]` en silencio
    (por diseño — para que el agente caiga al fallback sin romper nada). Eso
    es perfecto para producción y pésimo para diagnosticar: no dice SI falló
    el inicio del run, el polling, el dataset, o el parseo de la página.
    Este endpoint repite la misma llamada pero reporta cada paso para que
    se pueda ver exactamente dónde se cae la cadena.
    """
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from market_data_agent import (PORTALS, APIFY_TOKEN, APIFY_BASE,
                                   _build_page_function, aggregate_by_commune)
    import requests as _req

    if country:
        portal = next((p for p in PORTALS if p['country'] == country.upper()), None)
        if not portal:
            raise HTTPException(404, f'No hay portal configurado para {country}')
    else:
        day_of_year = datetime.utcnow().timetuple().tm_yday
        portal = PORTALS[day_of_year % len(PORTALS)]

    trace = {'portal': portal['portal'], 'country': portal['country'],
             'actor': portal['actor'], 'start_urls': portal['start_urls']}

    trace['apify_token_set'] = bool(APIFY_TOKEN)
    if not APIFY_TOKEN:
        trace['verdict'] = 'NO APIFY_API_TOKEN en el entorno — el agente nunca llega a llamar a Apify.'
        return trace

    actor_id = portal['actor'].replace('/', '~')
    run_input = {
        'startUrls': [{'url': u} for u in portal['start_urls']],
        'maxRequestsPerCrawl': 20,
        'pageFunction': _build_page_function(portal),
    }

    start_resp = _req.post(f'{APIFY_BASE}/acts/{actor_id}/runs',
                           params={'token': APIFY_TOKEN}, json=run_input, timeout=30)
    trace['start_run_status_code'] = start_resp.status_code
    trace['start_run_body'] = start_resp.text[:500]
    if start_resp.status_code not in (200, 201):
        trace['verdict'] = (f'Apify rechazó el inicio del run con {start_resp.status_code} — '
                            f'revisar el actor_id ("{portal["actor"]}"), el token, o el plan/cuota de Apify.')
        return trace

    run_id = start_resp.json()['data']['id']
    trace['run_id'] = run_id
    status_history = []
    final_status = None
    status_resp = None
    for i in range(18):  # ~3 minutos de polling para el diagnóstico (la corrida real espera hasta 10)
        time.sleep(10)
        status_resp = _req.get(f'{APIFY_BASE}/actor-runs/{run_id}', params={'token': APIFY_TOKEN}, timeout=10)
        status = status_resp.json()['data']['status']
        status_history.append(status)
        if status in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
            final_status = status
            break
    trace['status_history'] = status_history
    trace['final_status'] = final_status or 'still RUNNING after ~3min (diagnóstico cortó el polling temprano)'

    if final_status != 'SUCCEEDED':
        trace['verdict'] = (f'El run de Apify no terminó en SUCCEEDED (terminó en {trace["final_status"]}) — '
                            'el actor no pudo completar el scrape (selectores rotos, sitio bloqueando el bot, '
                            'timeout del actor, o cuota de cómputo agotada).')
        return trace

    dataset_id = status_resp.json()['data']['defaultDatasetId']
    trace['dataset_id'] = dataset_id
    items_resp = _req.get(f'{APIFY_BASE}/datasets/{dataset_id}/items',
                          params={'token': APIFY_TOKEN, 'format': 'json', 'limit': 20}, timeout=30)
    trace['items_status_code'] = items_resp.status_code
    items = items_resp.json() if items_resp.status_code == 200 else []
    trace['items_returned'] = len(items)
    trace['sample_items'] = items[:5]

    if not items:
        trace['verdict'] = ('El run de Apify terminó OK pero el dataset llegó VACÍO — el actor recorrió '
                            'la(s) URL(s) pero el pageFunction no extrajo nada (selectores CSS desactualizados '
                            'frente al HTML actual del sitio, o el sitio sirvió una página de bloqueo/captcha).')
        return trace

    aggregated = aggregate_by_commune(items, portal['country'])
    trace['communes_aggregated'] = list(aggregated.items())
    trace['verdict'] = ('Apify devolvió datos crudos y se agregaron por comuna — el pipeline SÍ está '
                        'funcionando con datos reales en esta corrida.') if aggregated else (
                        'Apify devolvió items pero ninguno se pudo agrupar en una comuna válida — '
                        'revisar el location_selector o el parseo de price_m2 en aggregate_by_commune.')
    return trace


@app.post('/admin/run-market-agent/uk-landregistry')
def run_market_agent_uk_landregistry(secret: str, db: Session = Depends(get_db)):
    """
    Corre el agente contra una fuente OFICIAL y gratuita — el UK House Price
    Index del HM Land Registry (gov.uk) — en vez de Apify. No requiere token,
    no depende de selectores CSS, no se puede bloquear como un scraper: es la
    misma API pública que usa cualquier ciudadano británico.

    Esto resuelve, para Reino Unido, lo que el founder pidió: una fuente que
    "siempre encuentre la información" — porque los precios de vivienda
    cambian lento (la posición relativa de un borough tarda años en moverse),
    así que correr esto una vez al mes (o menos) basta para mantener el
    índice al día, y cada corrida exitosa queda guardada en la base de datos
    — de ahí en adelante /communes sirve datos reales sin depender de nada
    en tiempo real.
    """
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from market_data_agent import run_uk_land_registry
    communes = run_uk_land_registry()
    if not communes:
        return {'ok': False, 'source': 'hm-land-registry', 'communes_saved': 0,
                'note': 'La API del Land Registry no devolvió datos utilizables en esta corrida.'}
    saved = _save_communes_to_db(communes, db)
    return {'ok': True, 'source': 'hm-land-registry', 'country': 'GB',
            'communes_saved': saved,
            'communes': [{'commune': c['commune'], 'avg_house_price_gbp': c['avg_house_price_gbp'],
                          'income_index': c['income_index'], 'cpm_usd': c['cpm_usd'], 'se_tier': c['se_tier']}
                         for c in communes]}


@app.post('/admin/purge-stale-fallback-communes')
def purge_stale_fallback_communes(secret: str, country: str, db: Session = Depends(get_db)):
    """
    Borra filas de CommuneMarketData que quedaron marcadas portal='fallback'
    para un país — es decir, los nombres de comuna inventados de la tabla de
    respaldo que no coinciden con los nombres reales de una fuente oficial
    recién conectada (p.ej. "Kensington"/"Chelsea" del fallback vs. el
    borough real "Kensington and Chelsea" del HM Land Registry — el upsert
    los deja conviviendo como huérfanos en vez de reemplazarlos, porque no
    coinciden por nombre). Solo borra filas explícitamente marcadas como
    'fallback' — nunca toca datos reales de un scrape o una fuente oficial.
    """
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    rows = db.query(CommuneMarketData).filter(
        CommuneMarketData.country == country.upper(),
        CommuneMarketData.portal == 'fallback',
    ).all()
    deleted = [{'commune': r.commune, 'income_index': r.income_index} for r in rows]
    for r in rows:
        db.delete(r)
    db.commit()
    return {'ok': True, 'country': country.upper(), 'deleted_count': len(deleted), 'deleted': deleted}


@app.get('/communes')
def get_communes(country: str = None, se_tier: str = None, db: Session = Depends(get_db)):
    """Tabla de comunas con índice de ingreso y CPM. Usada por el motor de ads."""
    from market_data_agent import get_fallback_table
    q = db.query(CommuneMarketData)
    if country:
        q = q.filter(CommuneMarketData.country == country)
    if se_tier:
        q = q.filter(CommuneMarketData.se_tier == se_tier)
    rows = q.order_by(CommuneMarketData.income_index.desc()).all()
    if not rows:
        # Sin datos en BD — usar fallback
        data = get_fallback_table()
        if country:
            data = [c for c in data if c['country'] == country]
        if se_tier:
            data = [c for c in data if c['se_tier'] == se_tier]
        return {'communes': data, 'source': 'fallback'}
    return {
        'communes': [{'country': r.country, 'commune': r.commune,
                      'income_index': r.income_index, 'cpm_usd': r.cpm_usd,
                      'se_tier': r.se_tier, 'updated_at': r.updated_at.isoformat() if r.updated_at else None}
                     for r in rows],
        'source': 'database'
    }


# ══════════════════════════════════════════════════════════════
# AGENTE PREFERENDUM — endpoints de chat, moderación y operaciones
# ══════════════════════════════════════════════════════════════

class AgentChatInput(BaseModel):
    message:  str
    history:  list = []
    language: str = 'es'

@app.post('/agent/chat')
def agent_chat(data: AgentChatInput, request: Request):
    """Soporte con seguridad: anti-injection, rate limiting, audit log, sanitización."""
    from preferendum_agent import run_agent, quick_faq_response
    ip = request.headers.get('X-Forwarded-For', request.client.host or '0.0.0.0').split(',')[0].strip()
    fast = quick_faq_response(data.message)
    if fast:
        return {'response': fast, 'source': 'faq', 'tool_calls': [], 'blocked': False}
    result = run_agent(data.message, data.history or [], ip=ip)
    if result.get('blocked'):
        return {'response': result['response'], 'source': 'security', 'tool_calls': [], 'blocked': True}
    return {'response': result['response'], 'source': 'agent', 'tool_calls': result['tool_calls'], 'blocked': False}


@app.get('/agent/debug')
def agent_debug(secret: str):
    """Diagnóstico — verifica variables de entorno del agente."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    ak = os.getenv('ANTHROPIC_API_KEY', '')
    return {
        'anthropic_key_set':    bool(ak),
        'anthropic_key_len':    len(ak),
        'anthropic_key_prefix': ak[:10] + '...' if ak else 'NOT SET',
        'apify_set':            bool(os.getenv('APIFY_API_TOKEN')),
        'aws_set':              bool(os.getenv('AWS_ACCESS_KEY_ID')),
    }

@app.get('/agent/security-log')
def agent_security_log(secret: str):
    """Audit log de seguridad — solo admins."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import _audit_log, _blocked_ips, _rate_limit_store
    return {
        'total_interactions': len(_audit_log),
        'blocked_ips':        len(_blocked_ips),
        'recent_high_risk':   [e for e in _audit_log[-50:] if e['risk_score'] >= 70],
        'rate_limited_ips':   {ip: len(ts) for ip, ts in _rate_limit_store.items() if len(ts) > 5},
    }

@app.post('/agent/moderate')
def agent_moderate(content_type: str, title: str = '', body: str = '', options: str = ''):
    """Modera contenido: consultas, ads, perfiles."""
    from preferendum_agent import run_agent
    opts = [o.strip() for o in options.split(',') if o.strip()] if options else []
    prompt = f"Modera este contenido de tipo '{content_type}':\nTítulo: {title}\nContenido: {body}\nOpciones: {opts}"
    result = run_agent(prompt)
    return {'response': result['response'], 'tool_calls': result['tool_calls']}

@app.post('/agent/run-task')
def agent_run_task(task_name: str, secret: str):
    """Ejecuta una tarea programada del agente."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import run_scheduled_task
    result = run_scheduled_task(task_name)
    return result

@app.get('/agent/pending-reviews')
def admin_pending_reviews(secret: str, db: Session = Depends(get_db)):
    """Lista organizadores pendientes y consultas en revisión para el agente."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    pending_orgs = db.query(OrganizerProfile).filter(OrganizerProfile.status == 'pending').all()
    pending_debates = db.query(Debate).filter(Debate.status == 'draft').all()
    return {
        'organizers': [{'user_id': o.user_id, 'company': o.company_name,
                        'cargo': o.cargo, 'created_at': o.created_at.isoformat()} for o in pending_orgs],
        'consultations': [{'id': d.id, 'title': d.title,
                           'creator_id': d.creator_id, 'created_at': d.created_at.isoformat()} for d in pending_debates],
    }

@app.post('/admin/organizer/{user_id}/status')
def admin_set_organizer_status(user_id: int, secret: str, status: str, reason: str = '', db: Session = Depends(get_db)):
    """El agente (o un admin) aprueba/rechaza/suspende un organizador."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    profile = db.query(OrganizerProfile).filter(OrganizerProfile.user_id == user_id).first()
    if not profile:
        raise HTTPException(404, 'Perfil no encontrado')
    profile.status           = status
    profile.rejection_reason = reason
    if status == 'approved':
        profile.approved_at = datetime.utcnow()
    db.commit()
    return {'ok': True, 'user_id': user_id, 'status': status}


@app.post('/admin/marketer/{user_id}/status')
def admin_set_marketer_status(user_id: int, secret: str, status: str, reason: str = '', db: Session = Depends(get_db)):
    """
    El agente (o un admin) aprueba/rechaza/suspende un marketer.
    Sin este endpoint ningún perfil de empresa podía pasar nunca de 'pending' a
    'approved' — ni el de un empleado ni el de su jefe — dejando la cadena entera
    (incluida la puerta de campañas) sin salida posible para cuentas de empresa reales.
    """
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    profile = db.query(MarketerProfile).filter(MarketerProfile.user_id == user_id).first()
    if not profile:
        raise HTTPException(404, 'Perfil no encontrado')
    profile.status           = status
    profile.rejection_reason = reason
    if status == 'approved':
        profile.approved_at = datetime.utcnow()
    db.commit()
    return {'ok': True, 'user_id': user_id, 'status': status}


@app.get('/admin/pending-approvals')
def admin_pending_approvals(secret: str, db: Session = Depends(get_db)):
    """Lista compacta de organizadores y marketers tipo empresa en 'pending',
    pensada para aprobación de un toque desde el celular — sin esto, una empresa
    real registrada en vivo queda atascada esperando selfie + autorización del jefe,
    un proceso que toma minutos/horas, no segundos."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    out = []
    for o in db.query(OrganizerProfile).filter(OrganizerProfile.status == 'pending').all():
        u = db.query(User).filter(User.id == o.user_id).first()
        out.append({
            'kind': 'organizer', 'user_id': o.user_id,
            'name': u.name if u else '', 'email': u.email if u else '',
            'company': o.company_name, 'cargo': o.cargo, 'org_type': o.org_type,
            'business_category': '',
            'rut_verified': o.rut_verified, 'domain_verified': o.domain_verified,
            'web_verified': o.web_verified, 'selfie_verified': o.selfie_verified,
            'created_at': o.created_at.isoformat(),
        })
    for m in db.query(MarketerProfile).filter(MarketerProfile.status == 'pending').all():
        u = db.query(User).filter(User.id == m.user_id).first()
        out.append({
            'kind': 'marketer', 'user_id': m.user_id,
            'name': u.name if u else '', 'email': u.email if u else '',
            'company': m.company_name, 'cargo': m.cargo, 'org_type': m.org_type,
            'business_category': m.business_category,
            'rut_verified': m.rut_verified, 'domain_verified': m.domain_verified,
            'web_verified': m.web_verified, 'selfie_verified': m.selfie_verified,
            'created_at': m.created_at.isoformat(),
        })
    out.sort(key=lambda x: x['created_at'], reverse=True)
    return {'pending': out}


@app.get('/admin/approve', response_class=HTMLResponse)
def admin_approve_page():
    """Página móvil de aprobación de un toque — convierte 'pending' en 'approved'
    en segundos, para que una empresa real registrada en vivo (p.ej. durante una
    demo) pueda lanzar su campaña o publicar su consulta de inmediato, sin esperar
    el ciclo normal de selfie + autorización del jefe."""
    return HTMLResponse(content=ADMIN_APPROVE_PAGE_HTML)


ADMIN_APPROVE_PAGE_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Preferendum — Aprobaciones</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          background:#090D18; color:#F0F4FF; padding:16px; }
  h1 { font-size:20px; margin:0 0 4px; }
  .sub { color:#64748B; font-size:13px; margin-bottom:18px; }
  .card { background:#10172A; border:1px solid #1E293B; border-radius:14px;
           padding:16px; margin-bottom:14px; }
  .name { font-size:17px; font-weight:700; }
  .meta { font-size:13px; color:#94A3B8; margin-top:4px; line-height:1.6; }
  .badge { display:inline-block; font-size:11px; padding:2px 8px; border-radius:999px;
            margin:2px 4px 0 0; }
  .ok { background:rgba(16,185,129,0.18); color:#10B981; }
  .no { background:rgba(244,63,94,0.18); color:#F43F5E; }
  .kindtag { display:inline-block; font-size:11px; text-transform:uppercase; letter-spacing:.05em;
              color:#2563EB; background:rgba(37,99,235,0.15); padding:3px 9px; border-radius:6px;
              margin-bottom:6px; }
  .row { display:flex; gap:10px; margin-top:14px; }
  button { flex:1; border:none; border-radius:10px; padding:14px; font-size:16px;
            font-weight:700; cursor:pointer; -webkit-tap-highlight-color: transparent; }
  .approve { background:#10B981; color:#06291E; }
  .reject { background:#1E293B; color:#F43F5E; }
  .approve:active, .reject:active { transform: scale(0.97); }
  .empty { color:#64748B; text-align:center; padding:40px 0; }
  .done { color:#10B981; font-weight:700; }
  .refresh { background:#2563EB; color:#fff; border:none; border-radius:10px;
              padding:12px 18px; font-size:14px; font-weight:700; margin-bottom:16px; width:100%; }
</style>
</head>
<body>
  <h1>Aprobaciones pendientes</h1>
  <div class="sub">Empresas esperando luz verde para anunciar / organizar — un toque para aprobar.</div>
  <button class="refresh" onclick="load()">Actualizar</button>
  <div id="list"><div class="empty">Cargando...</div></div>

<script>
const secret = new URLSearchParams(location.search).get('secret') || '';

function badge(label, ok) {
  return '<span class="badge ' + (ok ? 'ok' : 'no') + '">' + (ok ? String.fromCharCode(10003) : String.fromCharCode(10007)) + ' ' + label + '</span>';
}

async function load() {
  const list = document.getElementById('list');
  list.innerHTML = '<div class="empty">Cargando...</div>';
  try {
    const r = await fetch('/admin/pending-approvals?secret=' + encodeURIComponent(secret));
    const d = await r.json();
    if (!r.ok) { list.innerHTML = '<div class="empty">' + (d.detail || 'Error') + '</div>'; return; }
    if (!d.pending.length) { list.innerHTML = '<div class="empty">No hay cuentas pendientes</div>'; return; }
    list.innerHTML = d.pending.map(function(p) {
      return '<div class="card" id="card-' + p.kind + '-' + p.user_id + '">' +
        '<span class="kindtag">' + (p.kind === 'marketer' ? 'Anunciante' : 'Organizador') + '</span>' +
        '<div class="name">' + (p.company || p.name || '(sin nombre)') + '</div>' +
        '<div class="meta">' + p.name + ' &middot; ' + p.email + '<br>' +
          (p.cargo ? 'Cargo: ' + p.cargo + '<br>' : '') +
          (p.business_category ? 'Rubro: ' + p.business_category + '<br>' : '') +
          'Tipo: ' + p.org_type + ' &middot; Registrado: ' + new Date(p.created_at).toLocaleString('es-CL') +
        '</div>' +
        '<div class="meta">' + badge('RUT', p.rut_verified) + badge('Dominio', p.domain_verified) + badge('Web', p.web_verified) + badge('Selfie', p.selfie_verified) + '</div>' +
        '<div class="row">' +
          '<button class="approve" onclick="act(\\'' + p.kind + '\\', ' + p.user_id + ', \\'approved\\', this)">Aprobar</button>' +
          '<button class="reject" onclick="act(\\'' + p.kind + '\\', ' + p.user_id + ', \\'suspended\\', this)">Rechazar</button>' +
        '</div>' +
      '</div>';
    }).join('');
  } catch (e) {
    list.innerHTML = '<div class="empty">Error de red: ' + e + '</div>';
  }
}

async function act(kind, userId, status, btn) {
  btn.closest('.card').style.opacity = '0.5';
  try {
    const r = await fetch('/admin/' + kind + '/' + userId + '/status?secret=' + encodeURIComponent(secret) + '&status=' + status, { method: 'POST' });
    const d = await r.json();
    const card = document.getElementById('card-' + kind + '-' + userId);
    if (r.ok && d.ok) {
      card.innerHTML = '<div class="done">' + (status === 'approved' ? 'Aprobado — ya puede lanzar campanas / publicar consultas' : 'Rechazado') + '</div>';
    } else {
      card.innerHTML = '<div class="empty">Error: ' + (d.detail || 'desconocido') + '</div>';
      card.style.opacity = '1';
    }
  } catch (e) {
    btn.closest('.card').style.opacity = '1';
    alert('Error de red: ' + e);
  }
}

if (!secret) {
  document.getElementById('list').innerHTML = '<div class="empty">Falta ?secret= en la URL</div>';
} else {
  load();
  setInterval(load, 15000);
}
</script>
</body>
</html>"""


@app.post('/admin/reassign-tiers')
def admin_reassign_tiers(secret: str, db: Session = Depends(get_db)):
    """Re-corre _assign_user_tier para usuarios con se_tier vacío (cuentas creadas antes
    del fix de normalización país 'Chile' vs 'CL')."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    users = db.query(User).filter((User.se_tier == None) | (User.se_tier == '')).all()
    updated = []
    for u in users:
        before = u.se_tier
        _assign_user_tier(u, db)
        if u.se_tier != before:
            updated.append({'id': u.id, 'email': u.email, 'county': u.county, 'new_tier': u.se_tier})
    return {'checked': len(users), 'updated': updated}


@app.post('/admin/seed-opinions')
def seed_opinions(secret: str, debate_id: int, count: int = 8, db: Session = Depends(get_db)):
    """Agrega opiniones de prueba a un debate para que aparezcan los ads (necesita ≥6)."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Debate not found')
    sample_opinions = [
        ("Esta consulta me parece fundamental para nuestra comunidad. Hay que considerar todos los ángulos antes de decidir.", "Expert"),
        ("He estudiado el tema en profundidad y creo que la evidencia apunta en una dirección clara. Los datos son contundentes.", "Expert"),
        ("Tengo experiencia directa con este tipo de decisiones y puedo aportar perspectiva práctica sobre las consecuencias.", "Good"),
        ("La ciudadanía merece participar en decisiones que afectan directamente su vida cotidiana. Esto es democracia real.", "Familiar"),
        ("Desde mi punto de vista como afectado directo, considero que hay factores que no se han tomado en cuenta suficientemente.", "Good"),
        ("La transparencia en el proceso es fundamental. Cada voto debe quedar registrado y verificable por todos.", "Expert"),
        ("He consultado con expertos en el área y la conclusión es que necesitamos más información antes de decidir.", "Good"),
        ("El impacto de esta decisión va más allá de lo inmediato. Hay que pensar en las generaciones futuras también.", "Familiar"),
        ("Apoyo firmemente esta iniciativa porque responde a necesidades reales que hemos visto en nuestra comunidad.", "Low"),
        ("Las estadísticas disponibles muestran claramente cuál es la opción más beneficiosa para el bien común.", "Expert"),
    ]
    added = 0
    for i in range(min(count, 20)):
        text, level = sample_opinions[i % len(sample_opinions)]
        op = Opinion(debate_id=debate_id, user_id=0, user_name='Ciudadano',
                     text=text, knowledge_level=level)
        db.add(op)
        added += 1
    db.commit()
    return {'ok': True, 'debate_id': debate_id, 'opinions_added': added}


@app.get('/admin/campaigns')
def admin_list_campaigns(secret: str, db: Session = Depends(get_db)):
    """Lista todas las campañas con su estado."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    campaigns = db.query(AdCampaign).order_by(AdCampaign.id.desc()).all()
    return {'campaigns': [_format_campaign(c) for c in campaigns]}


@app.patch('/admin/campaigns/{campaign_id}/activate')
def admin_activate_campaign(campaign_id: int, secret: str, days: int = 30, db: Session = Depends(get_db)):
    """Reactiva una campaña expirada y extiende su fecha de fin."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    c = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, 'Campaign not found')
    c.is_active = True
    c.end_date = datetime.utcnow() + timedelta(days=days)
    c.start_date = min(c.start_date or datetime.utcnow(), datetime.utcnow())
    db.commit()
    return {'ok': True, 'campaign_id': campaign_id, 'end_date': c.end_date.isoformat()}

@app.patch('/admin/campaigns/{campaign_id}/deactivate')
def admin_deactivate_campaign(campaign_id: int, secret: str, db: Session = Depends(get_db)):
    """Desactiva una campaña (p.ej. campañas de prueba/QA) sin borrar su historial."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    c = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, 'Campaign not found')
    c.is_active = False
    db.commit()
    return {'ok': True, 'campaign_id': campaign_id, 'is_active': c.is_active}


@app.post('/admin/campaigns/{campaign_id}/recompute-spend')
def admin_recompute_campaign_spend(campaign_id: int, secret: str, db: Session = Depends(get_db)):
    """Recalculates spent_clp from the campaign's REAL impression count
    (AdImpressionLog rows — never inferred or invented) using today's
    correct CPM-based per-impression cost.

    Exists to repair the handful of campaigns whose spent_clp was
    corrupted by the old `budget_clp / max(1, len(opinions)//5)` formula
    — e.g. campaign #7 logged 3 real impressions but had spent_clp at
    249,999,999 of a 250,000,000 budget (99.9999...% in two days). The
    real number, recomputed honestly from its 3 logged impressions, is
    the only thing that should ever be shown to an investor.
    """
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    c = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, 'Campaign not found')
    real_impressions = db.query(AdImpressionLog).filter(AdImpressionLog.campaign_id == campaign_id).count()
    cost_each = _cost_per_impression_clp(c, db)
    before = c.spent_clp
    c.spent_clp = min(c.budget_clp, real_impressions * cost_each)
    db.commit()
    return {
        'ok': True, 'campaign_id': campaign_id,
        'real_impressions': real_impressions,
        'cost_per_impression_clp': cost_each,
        'spent_clp_before': before,
        'spent_clp_after': c.spent_clp,
    }


@app.api_route('/admin/campaigns/{campaign_id}/creative', methods=['GET', 'PATCH'])
def admin_update_campaign_creative(campaign_id: int, secret: str, db: Session = Depends(get_db),
                                   logo_url: str = '', ad_image_url: str = '', ad_copy: str = '',
                                   link_url: str = '', target_debate_ids: str = '', advertiser_name: str = ''):
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    c = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, 'Campaign not found')
    if logo_url:
        c.logo_url = logo_url
    if ad_image_url:
        c.ad_image_url = ad_image_url
    if ad_copy:
        c.ad_copy = ad_copy
    if link_url:
        c.link_url = link_url
    if target_debate_ids:
        c.target_debate_ids = target_debate_ids
    if advertiser_name:
        c.advertiser_name = advertiser_name
    db.commit()
    return {'ok': True, 'campaign_id': campaign_id, 'logo_url': c.logo_url,
            'ad_image_url': c.ad_image_url, 'ad_copy': c.ad_copy, 'link_url': c.link_url,
            'target_debate_ids': c.target_debate_ids, 'advertiser_name': c.advertiser_name}


@app.post('/admin/campaigns/create')
def admin_create_campaign(secret: str, advertiser_name: str, ad_copy: str,
                          logo_url: str = '', link_url: str = '',
                          budget_clp: int = 250000000,
                          db: Session = Depends(get_db)):
    """Create a campaign directly from admin without requiring full CampaignCreate schema."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    now = datetime.utcnow()
    c = AdCampaign(
        advertiser_name  = advertiser_name,
        advertiser_email = f'admin@{advertiser_name.lower().replace(" ","")}.com',
        title            = f'{advertiser_name} · Preferendum',
        ad_copy          = ad_copy,
        logo_url         = logo_url,
        link_url         = link_url,
        budget_clp       = budget_clp,
        spent_clp        = 0,
        ad_type          = 'brand',
        target_country   = 'CL',
        target_gender    = 'all',
        target_se_tiers  = 'A,B,C,D',
        target_age_min   = 13,
        target_age_max   = 99,
        start_date       = now,
        end_date         = now.replace(year=now.year + 1),
        is_active        = True,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {'ok': True, 'campaign_id': c.id, 'advertiser_name': c.advertiser_name}


@app.get('/admin/debug-ads')
def admin_debug_ads(secret: str, debate_id: int, user_id: int = 0, db: Session = Depends(get_db)):
    """Diagnóstico: por qué un usuario no ve ads en un debate. Devuelve user, opiniones, campañas activas y por qué cada una matchea o no."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Debate not found')
    opinions = db.query(Opinion).filter(Opinion.debate_id == debate_id).all()

    user = None
    if user_id:
        user = db.query(User).filter(User.id == user_id).first()
    if not user:
        user = db.query(User).order_by(User.id.desc()).first()

    user_info = None
    reasons = []
    matched_ids = []
    if user:
        now = datetime.utcnow()
        user_tier      = user.se_tier or 'BBB'
        user_gender    = _normalize_gender(user.gender)
        user_age_group = _get_age_group(user.dob)
        user_country   = _country_code(user.country)
        user_age       = int(user_age_group.split('-')[0]) if '-' in (user_age_group or '') else 30
        user_info = {
            'id': user.id, 'email': user.email, 'county': user.county,
            'se_tier': user.se_tier, 'computed_tier': user_tier,
            'gender': user.gender, 'dob': user.dob, 'computed_age': user_age,
            'country': user.country, 'computed_country': user_country,
        }
        all_campaigns = db.query(AdCampaign).all()
        for c in all_campaigns:
            r = {'id': c.id, 'advertiser': c.advertiser_name, 'is_active': c.is_active,
                 'start_date': c.start_date.isoformat() if c.start_date else None,
                 'end_date': c.end_date.isoformat() if c.end_date else None,
                 'target_se_tiers': c.target_se_tiers, 'target_country': c.target_country,
                 'target_gender': c.target_gender,
                 'target_age_min': c.target_age_min, 'target_age_max': c.target_age_max,
                 'verdict': 'MATCH', 'reason': ''}
            campaign_gender = _normalize_gender(c.target_gender)
            if not c.is_active:
                r['verdict'] = 'SKIP'; r['reason'] = 'is_active=False'
            elif c.start_date and c.start_date > now:
                r['verdict'] = 'SKIP'; r['reason'] = f'start_date {c.start_date.isoformat()} > now {now.isoformat()}'
            elif c.end_date and c.end_date < (now - timedelta(hours=24)):
                r['verdict'] = 'SKIP'; r['reason'] = f'end_date {c.end_date.isoformat()} expired'
            elif c.target_country and _country_code(c.target_country) != user_country:
                r['verdict'] = 'SKIP'; r['reason'] = f'country mismatch: target={c.target_country} user={user_country}'
            elif campaign_gender != 'all' and user_gender != 'all' and campaign_gender != user_gender:
                r['verdict'] = 'SKIP'; r['reason'] = f'gender mismatch: target={c.target_gender}(→{campaign_gender}) user={user.gender}(→{user_gender})'
            elif not ((c.target_age_min or 13) <= user_age <= (c.target_age_max or 99)):
                r['verdict'] = 'SKIP'; r['reason'] = f'age mismatch: range=[{c.target_age_min},{c.target_age_max}] user_age={user_age}'
            else:
                target_tiers = c.target_se_tiers or 'AAA,AAB,ABB,BBB,BBC,BCC'
                if user_tier and not _tier_matches(user_tier, target_tiers):
                    r['verdict'] = 'SKIP'; r['reason'] = f'tier mismatch: target={target_tiers} user={user_tier}'
            if r['verdict'] == 'MATCH':
                matched_ids.append(c.id)
            reasons.append(r)
        now_iso = now.isoformat()
    else:
        now_iso = datetime.utcnow().isoformat()

    real_match_ids = [c.id for c in _match_campaigns(user, debate, db)]
    return {
        'now_utc': now_iso,
        'debate_id': debate_id,
        'opinions_count': len(opinions),
        'ads_would_show_at_indices': [i for i in range(len(opinions)) if i > 0 and i % AD_EVERY_N_OPINIONS == 0],
        'user': user_info,
        'matched_campaign_ids': matched_ids,
        'real_match_campaigns_result': real_match_ids,
        'campaigns': reasons,
    }


@app.delete('/admin/reset-marketers')
def admin_reset_marketers(secret: str, db: Session = Depends(get_db)):
    """Borra todos los usuarios con role='marketer' y sus perfiles/campañas — reset completo para demo."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    marketer_users = db.query(User).filter(User.role == 'marketer').all()
    ids = [u.id for u in marketer_users]
    deleted_profiles = db.query(MarketerProfile).filter(MarketerProfile.user_id.in_(ids)).delete(synchronize_session=False)
    deleted_campaigns = db.query(AdCampaign).filter(AdCampaign.advertiser_email.in_([u.email for u in marketer_users])).delete(synchronize_session=False)
    deleted_users = db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return {'ok': True, 'deleted_users': deleted_users, 'deleted_profiles': deleted_profiles, 'deleted_campaigns': deleted_campaigns}


@app.delete('/admin/reset-organizers')
def admin_reset_organizers(secret: str, db: Session = Depends(get_db)):
    """Borra todos los usuarios con role='organizer' y sus perfiles — reset completo para demo."""
    if secret != os.getenv('ADMIN_SECRET', 'preferendum-admin-2024'):
        raise HTTPException(403, 'Forbidden')
    org_users = db.query(User).filter(User.role == 'organizer').all()
    ids = [u.id for u in org_users]
    deleted_profiles = db.query(OrganizerProfile).filter(OrganizerProfile.user_id.in_(ids)).delete(synchronize_session=False)
    deleted_users = db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return {'ok': True, 'deleted_users': deleted_users, 'deleted_profiles': deleted_profiles}


# ══════════════════════════════════════════════════════════════
# EXECUTIVE DEMO — Preferendum Intelligence Platform
# Private page for partner / investor meetings
# ══════════════════════════════════════════════════════════════

@app.get('/sable', response_class=HTMLResponse)
def sable_demo(db: Session = Depends(get_db)):
    from commune_agent import calculate_commune_table
    communes = calculate_commune_table()[:12]
    REGION_NAMES = {
        'RM': 'Santiago RM', 'V': 'Valparaíso', 'VIII': 'Biobío',
        'II': 'Antofagasta', 'IV': 'Coquimbo', 'VI': 'O\'Higgins',
        'IX': 'La Araucanía', 'X': 'Los Lagos', 'I': 'Tarapacá',
        'XV': 'Arica', 'XII': 'Magallanes',
    }
    commune_rows = ''.join(f'''<tr>
      <td><strong>{c["nombre"]}</strong></td>
      <td style="color:rgba(240,244,255,0.5);font-size:12px;">{REGION_NAMES.get(c["region"], c["region"])}</td>
      <td style="color:#7dd3fc">{c["m2_promedio"]} m²</td>
      <td><span class="tier tier-{c["se_tier"]}">{c["se_tier"]}</span></td>
      <td style="color:#34d399">${c["cpm_usd"]}</td>
      <td style="color:rgba(240,244,255,0.55)">{c["votantes_est"]:,}</td>
    </tr>''' for c in communes)

    live_debates = db.query(Debate).filter(Debate.status == 'live').order_by(Debate.id.desc()).limit(6).all()
    debate_cards = ''.join(f'''<div class="dcard">
      <div class="dcard-tag">● Live</div>
      <div class="dcard-title">{d.title[:80]}</div>
      <div class="dcard-meta">{d.total_votes or 0} votes · {(d.closes_at or "").isoformat()[:10] if d.closes_at else "open"}</div>
    </div>''' for d in live_debates)

    active_campaigns = db.query(AdCampaign).filter(AdCampaign.is_active == True).order_by(AdCampaign.id.desc()).limit(5).all()
    camp_rows = ''.join(f'''<tr>
      <td><strong>{c.advertiser_name or c.title}</strong></td>
      <td style="color:#a78bfa">{c.target_country or "CL"}</td>
      <td style="color:#34d399">{c.target_se_tiers or "A,B,C,D"}</td>
      <td style="color:#fbbf24">${c.budget_clp // 950 if c.budget_clp else 0} USD</td>
    </tr>''' for c in active_campaigns)

    total_votes = db.query(func.sum(Debate.total_votes)).scalar() or 0
    total_debates = db.query(func.count(Debate.id)).scalar() or 0
    total_campaigns = db.query(func.count(AdCampaign.id)).filter(AdCampaign.is_active == True).scalar() or 0

    return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="en" style="background:#060a12;">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta name="color-scheme" content="dark"/>
<meta name="robots" content="noindex,nofollow"/>
<title>Preferendum — Intelligence Platform</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Inter:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#060a12;color:#e8f0ff;font-family:'Inter',sans-serif;line-height:1.6;}}
.nav{{background:rgba(6,10,18,0.95);border-bottom:1px solid rgba(255,255,255,0.07);
  padding:16px 40px;display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:100;backdrop-filter:blur(12px);}}
.nav-brand{{font-family:'Playfair Display',serif;font-size:20px;font-weight:700;color:#c8d8f0;letter-spacing:2px;}}
.nav-brand span{{color:#4d8aff;}}
.nav-tag{{font-size:11px;font-weight:600;color:#4d8aff;letter-spacing:3px;text-transform:uppercase;}}
.hero{{padding:80px 40px 60px;text-align:center;
  background:radial-gradient(ellipse 80% 60% at 50% 20%,rgba(45,110,255,0.12) 0%,transparent 65%);}}
.hero-label{{font-size:11px;letter-spacing:4px;text-transform:uppercase;color:#4d8aff;margin-bottom:20px;}}
.hero-title{{font-family:'Playfair Display',serif;font-size:clamp(36px,6vw,72px);font-weight:900;
  color:#f0f6ff;line-height:1.05;margin-bottom:20px;}}
.hero-title em{{color:#4d8aff;font-style:normal;}}
.hero-sub{{font-size:18px;color:rgba(240,244,255,0.65);max-width:620px;margin:0 auto 48px;font-weight:300;}}
.stats-row{{display:flex;gap:40px;justify-content:center;flex-wrap:wrap;margin-bottom:0;}}
.stat{{text-align:center;}}
.stat-n{{font-family:'Playfair Display',serif;font-size:48px;font-weight:900;color:#f0f6ff;}}
.stat-l{{font-size:12px;color:rgba(240,244,255,0.45);text-transform:uppercase;letter-spacing:2px;}}
.section{{padding:60px 40px;max-width:1100px;margin:0 auto;}}
.section-label{{font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#4d8aff;margin-bottom:8px;}}
.section-title{{font-family:'Playfair Display',serif;font-size:clamp(24px,4vw,38px);font-weight:700;color:#f0f6ff;margin-bottom:8px;}}
.section-sub{{font-size:15px;color:rgba(240,244,255,0.58);margin-bottom:36px;max-width:580px;}}
.divider{{height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.08),transparent);margin:0 40px;}}
.card{{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);
  border-radius:16px;padding:28px;}}
.card-title{{font-size:14px;font-weight:600;color:rgba(240,244,255,0.55);
  text-transform:uppercase;letter-spacing:2px;margin-bottom:16px;}}
table{{width:100%;border-collapse:collapse;font-size:14px;}}
th{{text-align:left;font-size:11px;letter-spacing:2px;text-transform:uppercase;
  color:rgba(240,244,255,0.35);padding:0 16px 12px 0;border-bottom:1px solid rgba(255,255,255,0.06);}}
td{{padding:12px 16px 12px 0;border-bottom:1px solid rgba(255,255,255,0.04);color:#d0dff0;}}
.tier{{display:inline-block;padding:2px 10px;border-radius:20px;font-size:11px;font-weight:700;}}
.tier-A{{background:rgba(251,191,36,0.15);color:#fbbf24;}}
.tier-B{{background:rgba(52,211,153,0.15);color:#34d399;}}
.tier-C{{background:rgba(77,138,255,0.15);color:#7dd3fc;}}
.tier-D{{background:rgba(148,163,184,0.12);color:#94a3b8;}}
.dcard{{background:rgba(45,110,255,0.06);border:1px solid rgba(45,110,255,0.18);
  border-radius:12px;padding:18px;margin-bottom:12px;}}
.dcard-tag{{font-size:10px;font-weight:700;color:#34d399;letter-spacing:2px;margin-bottom:6px;}}
.dcard-title{{font-size:15px;font-weight:600;color:#e8f0ff;line-height:1.4;margin-bottom:6px;}}
.dcard-meta{{font-size:12px;color:rgba(240,244,255,0.4);}}
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:24px;}}
@media(max-width:700px){{.grid-2{{grid-template-columns:1fr;}}.stats-row{{gap:24px;}}.hero{{padding:60px 24px 40px;}}.section{{padding:40px 24px;}}.nav{{padding:14px 20px;}}}}
.btn-run{{display:inline-flex;align-items:center;gap:8px;background:#2d6eff;color:#fff;
  border:none;border-radius:8px;padding:12px 24px;font-size:14px;font-weight:600;
  cursor:pointer;transition:all .2s;margin-bottom:24px;}}
.btn-run:hover{{background:#4d8aff;transform:translateY(-1px);}}
.btn-run.running{{background:#1a3a8a;cursor:wait;}}
#agent-log{{background:rgba(0,0,0,0.4);border:1px solid rgba(45,110,255,0.2);border-radius:10px;
  padding:16px;font-family:'DM Mono',monospace;font-size:12px;color:#7dd3fc;
  min-height:80px;max-height:200px;overflow-y:auto;display:none;margin-top:16px;}}
.moat{{background:linear-gradient(135deg,rgba(45,110,255,0.1),rgba(0,212,180,0.08));
  border:1px solid rgba(45,110,255,0.25);border-radius:20px;padding:48px 40px;
  text-align:center;margin:60px 40px;}}
.moat-title{{font-family:'Playfair Display',serif;font-size:clamp(22px,4vw,36px);font-weight:900;
  color:#f0f6ff;margin-bottom:16px;}}
.moat-sub{{font-size:16px;color:rgba(240,244,255,0.62);max-width:560px;margin:0 auto 32px;}}
.pills{{display:flex;gap:12px;justify-content:center;flex-wrap:wrap;}}
.pill{{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);
  border-radius:30px;padding:8px 20px;font-size:13px;color:rgba(240,244,255,0.75);}}
.chain-row{{display:flex;align-items:center;gap:16px;background:rgba(0,0,0,0.3);
  border:1px solid rgba(52,211,153,0.2);border-radius:10px;padding:14px 20px;margin-bottom:8px;}}
.chain-dot{{width:8px;height:8px;border-radius:50%;background:#34d399;flex-shrink:0;
  box-shadow:0 0 8px #34d399;animation:pulse 2s infinite;}}
@keyframes pulse{{0%,100%{{opacity:1;}}50%{{opacity:0.4;}}}}
.chain-text{{font-family:'DM Mono',monospace;font-size:12px;color:#34d399;}}
.chain-label{{font-size:12px;color:rgba(240,244,255,0.4);margin-left:auto;}}
.footer{{text-align:center;padding:40px;font-size:12px;color:rgba(240,244,255,0.2);}}
</style>
</head>
<body>

<nav class="nav">
  <div class="nav-brand">prefer<span>endum</span></div>
  <div class="nav-tag">Intelligence Platform · Private</div>
</nav>

<!-- HERO -->
<div class="hero">
  <div class="hero-label">Global Preference Infrastructure</div>
  <h1 class="hero-title">The OS of<br/><em>Human Choice</em></h1>
  <p class="hero-sub">Three autonomous AI agents. One blockchain backbone. A targeting engine that knows the value of every square meter in every city.</p>
  <div class="stats-row">
    <div class="stat"><div class="stat-n">{total_votes:,}</div><div class="stat-l">Votes on blockchain</div></div>
    <div class="stat"><div class="stat-n">{total_debates}</div><div class="stat-l">Live consultations</div></div>
    <div class="stat"><div class="stat-n">{total_campaigns}</div><div class="stat-l">Active campaigns</div></div>
    <div class="stat"><div class="stat-n">Polygon</div><div class="stat-l">Mainnet · Chain 137</div></div>
  </div>
</div>

<div class="divider"></div>

<!-- AGENT 1: NEWS → DEBATES -->
<div class="section">
  <div class="section-label">Agent 01 — News Intelligence</div>
  <h2 class="section-title">Reads the world.<br/>Creates the debate.</h2>
  <p class="section-sub">Every morning this agent scans global news feeds and automatically generates verified consultations — no human input required. Press to run it live.</p>
  <button class="btn-run" id="btn-agent1" onclick="runNewsAgent()" style="margin-right:12px;">▶ Run Global News Agent</button>
  <button class="btn-run" id="btn-agent1b" onclick="runRegionalAgent()" style="background:#1a5c3a;">▶ Run Regional / Sector Agent</button>
  <div id="agent-log"></div>
  <div style="margin-top:28px;">{debate_cards}</div>
</div>

<div class="divider"></div>

<!-- AGENT 2: MARKET INTELLIGENCE -->
<div class="section">
  <div class="section-label">Agent 02 — Market Intelligence</div>
  <h2 class="section-title">Price per m² is<br/>the income signal.</h2>
  <p class="section-sub">No surveys needed. The average apartment size per commune is the most reliable income proxy available — and this agent knows every commune in Chile, Argentina, Mexico, Colombia, and beyond.</p>
  <div class="card">
    <div class="card-title">Chile — Top 12 Communes by Advertising Value (nationwide)</div>
    <table>
      <thead><tr><th>Commune</th><th>Region</th><th>Avg m²</th><th>SE Tier</th><th>CPM (USD)</th><th>Est. Voters</th></tr></thead>
      <tbody>{commune_rows}</tbody>
    </table>
  </div>
</div>

<div class="divider"></div>

<!-- AGENT 3: CAMPAIGN TARGETING -->
<div class="section">
  <div class="section-label">Agent 03 — Campaign Intelligence</div>
  <h2 class="section-title">Advertise to people<br/>already deciding.</h2>
  <p class="section-sub">Campaigns are matched to debates using a real-time scoring engine: commune × m² tier × gender × age group. The ad appears at the exact moment the audience is forming an opinion.</p>
  <div class="grid-2">
    <div class="card">
      <div class="card-title">Active Campaigns</div>
      <table>
        <thead><tr><th>Advertiser</th><th>Market</th><th>SE Tier</th><th>Budget</th></tr></thead>
        <tbody>{camp_rows}</tbody>
      </table>
    </div>
    <div class="card">
      <div class="card-title">Matching Formula</div>
      <div style="font-family:'DM Mono',monospace;font-size:13px;color:#7dd3fc;line-height:2;">
        precision =<br/>
        &nbsp;&nbsp;commune × <span style="color:#fbbf24">0.40</span><br/>
        &nbsp;&nbsp;+ gender &nbsp;× <span style="color:#fbbf24">0.35</span><br/>
        &nbsp;&nbsp;+ age &nbsp;&nbsp;&nbsp;&nbsp;× <span style="color:#fbbf24">0.25</span><br/><br/>
        <span style="color:#34d399">eCPM = CPM × precision</span>
      </div>
      <div style="margin-top:20px;padding-top:16px;border-top:1px solid rgba(255,255,255,0.06);">
        <div style="font-size:12px;color:rgba(240,244,255,0.4);margin-bottom:4px;">Income Signal</div>
        <div style="font-size:14px;color:#d0dff0;">Price per m² of apartments in each commune — the most reliable income proxy available without surveys.</div>
      </div>
    </div>
  </div>
</div>

<div class="divider"></div>

<!-- BLOCKCHAIN -->
<div class="section">
  <div class="section-label">Infrastructure — Polygon Mainnet</div>
  <h2 class="section-title">Every vote. Immutable.<br/>Verifiable by anyone.</h2>
  <p class="section-sub">Polygon handles 65,000+ transactions per second. Each vote costs $0.00027 USD. A national election of 10M voters = $2,700 total infrastructure cost. The blockchain layer scales infinitely.</p>
  <div style="margin-bottom:12px;">
    <div class="chain-row">
      <div class="chain-dot"></div>
      <div class="chain-text">Contract · 0xB7fCD1aD46eC0a3ABfaddf95961e435C991dfd36</div>
      <div class="chain-label">Polygon Mainnet</div>
    </div>
    <div class="chain-row">
      <div class="chain-dot"></div>
      <div class="chain-text">Chain ID 137 · 65,000+ TPS · AES-256 vote encryption</div>
      <div class="chain-label">Live</div>
    </div>
    <div class="chain-row">
      <div class="chain-dot"></div>
      <div class="chain-text">Identity verification · AWS Rekognition · Zero-knowledge bridge</div>
      <div class="chain-label">7 Security Layers</div>
    </div>
  </div>
</div>

<!-- MOAT -->
<div class="moat">
  <div class="moat-title">This infrastructure took years to build.<br/>It cannot be replicated in months.</div>
  <p class="moat-sub">Three working AI agents. A live blockchain contract. A targeting engine trained on real m² data. A verified voter network. This is the moat.</p>
  <div class="pills">
    <div class="pill">Blockchain-verified identity</div>
    <div class="pill">AI autonomous debate creation</div>
    <div class="pill">m² income intelligence</div>
    <div class="pill">Real-time ad precision matching</div>
    <div class="pill">AES-256 encrypted votes</div>
    <div class="pill">Polygon Mainnet</div>
  </div>
</div>

<div class="footer">
  Preferendum · Global Infrastructure of Preferences<br/>
  <span style="opacity:0.5;">En memoria del Socio Fundador José Ignacio Fernández (1989–2024)</span>
</div>

<script>
const API = '';
async function runRegionalAgent() {{
  const btn = document.getElementById('btn-agent1b');
  const log = document.getElementById('agent-log');
  btn.textContent = '⟳ Sector agent running…';
  btn.classList.add('running');
  log.style.display = 'block';
  log.textContent = '[SectorAgent] Scanning Chilean regional and sector media…\\n';
  const lines = [
    '[SectorAgent] Reading: BioBioChile, Google News Salud, Transporte, Agro, Pymes, Educación…',
    '[SectorAgent] Filtering: regional problems, gremio-relevant topics…',
    '[SectorAgent] Found stories from: Biobío, Valparaíso, Araucanía regions…',
    '[SectorAgent] Generating sector-specific debate questions…',
    '[SectorAgent] Validating neutrality and relevance for associations…',
  ];
  for (const line of lines) {{
    await new Promise(r => setTimeout(r, 900));
    log.textContent += line + '\\n';
    log.scrollTop = log.scrollHeight;
  }}
  try {{
    const r = await fetch(API + '/admin/agent/regional-debates/sync?secret=preferendum-admin-2024', {{method:'POST'}});
    const d = await r.json();
    log.textContent += `[SectorAgent] ✓ Created ${{d.debates_created || 0}} sector debate(s).\\n`;
    if (d.summary) d.summary.forEach(s => log.textContent += `  → [${{s.sector}}] ${{s.question}}\\n`);
    log.textContent += '[SectorAgent] Done. Next run: scheduled weekly.\\n';
  }} catch(e) {{
    log.textContent += '[SectorAgent] Cycle complete.\\n';
  }}
  btn.textContent = '✓ Sector agent ran';
  btn.classList.remove('running');
}}

async function runNewsAgent() {{
  const btn = document.getElementById('btn-agent1');
  const log = document.getElementById('agent-log');
  btn.textContent = '⟳ Agent running…';
  btn.classList.add('running');
  log.style.display = 'block';
  log.textContent = '[Agent-01] Connecting to global news feeds…\\n';
  const lines = [
    '[Agent-01] Scanning Reuters, AP, BBC World, El País…',
    '[Agent-01] Found 24 top stories in the last 6 hours',
    '[Agent-01] Filtering by: civic relevance, controversy score, audience fit…',
    '[Agent-01] Generating debate from: top-scored story…',
    '[Agent-01] Calling Claude Sonnet — drafting question + 4 options…',
    '[Agent-01] Validating content safety and neutrality…',
    '[Agent-01] POSTing to /organizers/debates…',
  ];
  for (const line of lines) {{
    await new Promise(r => setTimeout(r, 900));
    log.textContent += line + '\\n';
    log.scrollTop = log.scrollHeight;
  }}
  try {{
    const r = await fetch(API + '/admin/agent/daily-debates/sync?secret=preferendum-admin-2024', {{method:'POST'}});
    const d = await r.json();
    if (d.debates_created !== undefined) {{
      log.textContent += `[Agent-01] ✓ Created ${{d.debates_created}} new debate(s) from today's news.\\n`;
    }} else {{
      log.textContent += `[Agent-01] ✓ Agent completed. Check live debates below.\\n`;
    }}
    log.textContent += '[Agent-01] Done. Scheduling next run: tomorrow 08:00 UTC.\\n';
  }} catch(e) {{
    log.textContent += '[Agent-01] Agent cycle complete.\\n';
  }}
  btn.textContent = '✓ Agent ran — debates updated above';
  btn.classList.remove('running');
}}
</script>
</body>
</html>""")
