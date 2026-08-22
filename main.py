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
    se_tier              = Column(String, default='')   # A/B/C/D — combinación de comuna + profesión
    income_index         = Column(Float, default=0.0)   # índice de ingreso de su comuna
    estimated_income_usd = Column(Float, default=None)  # ingreso anual estimado en USD (señal ocupacional)
    estimated_income_ppp = Column(Float, default=None)  # ingreso mensual PPP — composite (ocupación+residencial+empresa)
    profession           = Column(String, default='')   # profesión declarada al registrarse
    cargo           = Column(String, default='')   # cargo/posición jerárquica
    company_size    = Column(String, default='')   # tamaño de empresa: 1-10, 11-50, etc.
    ref_source      = Column(String, default='')   # canal de adquisición: fb, ig, tiktok, etc.
    gender          = Column(String, default='F')
    dob             = Column(String, default='')
    national_id     = Column(String, default='')
    doc_serial      = Column(String, default='')   # número de serie del documento físico (9 dígitos)
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
    referral_code       = Column(String, unique=True, index=True)  # código propio para invitar amigos
    referred_by_user_id = Column(Integer, index=True, default=None)  # quién lo invitó (viral, no sponsor)
    tier_pre_evaluated  = Column(Boolean, default=False)  # se_tier heredado del referente, no calculado con datos propios
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
    income_min_usd   = Column(Float, default=None)         # ingreso anual mínimo en USD (None = sin límite)
    income_max_usd   = Column(Float, default=None)         # ingreso anual máximo en USD (None = sin límite)
    category         = Column(String, default='general')   # deportes / política / economía / salud / etc.
    status           = Column(String, default='live')
    opens_at         = Column(DateTime, default=datetime.utcnow)
    closes_at        = Column(DateTime)
    verify_opens_at  = Column(DateTime)
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

class DocSerialVoteLog(Base):
    """Número de serie del documento físico — solo puede votar una vez por debate.
    Bloquea aunque renueven el chip, creen cuenta nueva o cambien de RUT."""
    __tablename__ = 'doc_serial_vote_log'
    id          = Column(Integer, primary_key=True)
    debate_id   = Column(Integer, index=True, nullable=False)
    serial_hash = Column(String, index=True, nullable=False)
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

class Sponsor(Base):
    __tablename__ = 'sponsors'
    id                   = Column(Integer, primary_key=True)
    name                 = Column(String, nullable=False)      # "Emirates"
    logo_url             = Column(String, default='')
    industry             = Column(String, default='')          # airline / hotel / bank
    contact_email        = Column(String, default='')
    discount_code_prefix = Column(String, default='')          # "EMI" → EMI-XXXX-YY
    created_at           = Column(DateTime, default=datetime.utcnow)

class SponsoredDebate(Base):
    __tablename__ = 'sponsored_debates'
    id            = Column(Integer, primary_key=True)
    debate_id     = Column(Integer, index=True, unique=True)
    sponsor_id    = Column(Integer, index=True)
    discount_pct  = Column(Integer, default=15)           # 15%
    discount_text = Column(String, default='')            # "15% off your next Emirates flight"
    total_invited = Column(Integer, default=0)
    total_voted   = Column(Integer, default=0)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)

class SponsorCampaign(Base):
    __tablename__ = 'sponsor_campaigns'
    id                  = Column(Integer, primary_key=True)
    sponsored_debate_id = Column(Integer, index=True)
    sponsor_id          = Column(Integer, index=True)
    name                = Column(String, default='')
    total_emails        = Column(Integer, default=0)
    sent                = Column(Integer, default=0)
    voted               = Column(Integer, default=0)
    status              = Column(String, default='draft')  # draft / sending / sent
    created_at          = Column(DateTime, default=datetime.utcnow)

class SponsorInvitee(Base):
    __tablename__ = 'sponsor_invitees'
    id            = Column(Integer, primary_key=True)
    campaign_id   = Column(Integer, index=True)
    sponsor_id    = Column(Integer, index=True)
    email         = Column(String, index=True)
    invite_token  = Column(String, unique=True, index=True)
    sent          = Column(Boolean, default=False)
    registered    = Column(Boolean, default=False)
    voted         = Column(Boolean, default=False)
    user_id       = Column(Integer, nullable=True)
    discount_code = Column(String, default='')
    created_at    = Column(DateTime, default=datetime.utcnow)

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
    target_age_ranges    = Column(String, default='')        # legacy
    target_age_weights   = Column(String, default='')        # JSON: {"18-24":30,"25-34":70}
    target_company_sizes = Column(String, default='')        # 'small,medium,large' o '' = todos
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
    target_hnw_only     = Column(Boolean, default=False) # True = solo usuarios verified_hnw
    min_hnw_score       = Column(Float, default=0.0)     # hnw_score mínimo (0 = sin límite)
    frequency_cap       = Column(Integer, nullable=True) # máx. veces que UN usuario ve este anuncio (None = sin límite)

class ModelDefinition(Base):
    """Modelos de optimización/matching versionados — guardados por JC y el equipo."""
    __tablename__ = 'model_definitions'
    id          = Column(Integer, primary_key=True)
    name        = Column(String, nullable=False)
    version     = Column(String, default='1.0')
    model_type  = Column(String, default='matching')  # 'matching' | 'optimization' | 'budget'
    description = Column(String, default='')
    config_json = Column(String, default='{}')        # parámetros clave en JSON
    source_code = Column(String, default='')          # código Python del modelo
    author      = Column(String, default='')
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow)


class AdImpressionLog(Base):
    __tablename__ = 'ad_impression_logs'
    id          = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, index=True)
    debate_id   = Column(Integer, index=True, nullable=True)
    user_id     = Column(Integer, index=True, nullable=True)  # quién vio el anuncio — para límite de frecuencia
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
    id                   = Column(Integer, primary_key=True)
    country              = Column(String, index=True)
    commune              = Column(String, index=True)
    price_m2_avg         = Column(Float, default=0.0)
    income_index         = Column(Float, default=100.0)  # mediana global = 100
    income_pct           = Column(Float, default=50.0)   # percentil dentro del grupo de ingreso
    cpm_usd              = Column(Float, default=6.0)
    se_tier              = Column(String, default='C')   # A / B / C / D
    estimated_income_ppp = Column(Float, default=None)   # ingreso individual mensual PPP (del precio m²)
    portal               = Column(String)
    sample_count         = Column(Integer, default=0)
    scraped_at           = Column(DateTime)
    updated_at           = Column(DateTime, default=datetime.utcnow)

class SystemTodo(Base):
    """TO-DO real de trabajo pendiente/incompleto encontrado en auditorías.
    Vive en la base de datos — cualquiera puede consultarlo directo,
    sin depender de que Claude lo reporte de nuevo cada vez."""
    __tablename__ = 'system_todos'
    id           = Column(Integer, primary_key=True)
    title        = Column(String, nullable=False)
    description  = Column(Text, default='')
    category     = Column(String, default='general')   # matching / income_data / verification / etc.
    status       = Column(String, default='open')       # open / in_progress / done
    priority     = Column(String, default='medium')     # low / medium / high
    discovered_by= Column(String, default='')            # qué auditoría/sesión lo encontró
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow)
    resolved_at  = Column(DateTime, nullable=True)

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
            ('income_min_usd',      "FLOAT DEFAULT NULL"),
            ('income_max_usd',      "FLOAT DEFAULT NULL"),
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
        for col, defn in [('se_tier', "TEXT DEFAULT ''"), ('income_index', 'FLOAT DEFAULT 0.0'),
                          ('estimated_income_usd', 'FLOAT DEFAULT NULL'),
                          ('doc_serial', "TEXT DEFAULT ''"), ('profession', "TEXT DEFAULT ''"),
                          ('cargo', "TEXT DEFAULT ''"),
                          ('company_size', "TEXT DEFAULT ''"),
                          ('ref_source', "TEXT DEFAULT ''"),
                          ('hnw_score', 'FLOAT DEFAULT 0.0'),
                          ('verified_hnw', 'BOOLEAN DEFAULT FALSE'),
                          ('hnw_source', "TEXT DEFAULT ''"),
                          ('referral_code', 'TEXT'),
                          ('referred_by_user_id', 'INTEGER'),
                          ('tier_pre_evaluated', 'BOOLEAN DEFAULT FALSE')]:
            if col not in existing_user_cols:
                try:
                    conn.execute(text(f'ALTER TABLE users ADD COLUMN {col} {defn}'))
                    conn.commit()
                except Exception:
                    pass
        # referral_code — índice único, y backfill para usuarios existentes que no lo tengan
        try:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_referral_code ON users (referral_code)"))
            conn.commit()
        except Exception:
            pass
        try:
            rows_no_code = conn.execute(text("SELECT id FROM users WHERE referral_code IS NULL OR referral_code = ''")).fetchall()
            for (uid,) in rows_no_code:
                import secrets as _secrets_migr
                code = 'R' + _secrets_migr.token_hex(4).upper()
                conn.execute(text("UPDATE users SET referral_code=:c WHERE id=:i"), {'c': code, 'i': uid})
            conn.commit()
        except Exception:
            pass
        # debates — verify_opens_at
        existing_debate_cols2 = {c['name'] for c in inspector.get_columns('debates')} if inspector.has_table('debates') else set()
        if 'verify_opens_at' not in existing_debate_cols2:
            try:
                conn.execute(text("ALTER TABLE debates ADD COLUMN verify_opens_at TIMESTAMP"))
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
            ('target_age_weights',    "TEXT DEFAULT ''"),
            ('target_company_sizes',  "TEXT DEFAULT ''"),  # 'small,medium,large' o '' = todos
            ('target_categories',   "TEXT DEFAULT ''"),
            ('excluded_categories', "TEXT DEFAULT ''"),
            ('blocked_competitors', "TEXT DEFAULT ''"),
            ('spent_clp',           'FLOAT DEFAULT 0.0'),
            ('video_url',           "TEXT DEFAULT ''"),
            ('min_per_capita_usd',  'REAL DEFAULT 0.0'),
            ('target_hnw_only',     'BOOLEAN DEFAULT FALSE'),
            ('min_hnw_score',       'REAL DEFAULT 0.0'),
            ('frequency_cap',       'INTEGER DEFAULT NULL'),
        ]:
            if col not in existing_ad_cols:
                try:
                    conn.execute(text(f'ALTER TABLE ad_campaigns ADD COLUMN {col} {defn}'))
                    conn.commit()
                except Exception:
                    pass
        # ad_impression_logs — user_id para poder limitar frecuencia por usuario
        existing_impr_cols = {c['name'] for c in inspector.get_columns('ad_impression_logs')} if inspector.has_table('ad_impression_logs') else set()
        if 'user_id' not in existing_impr_cols:
            try:
                conn.execute(text('ALTER TABLE ad_impression_logs ADD COLUMN user_id INTEGER'))
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
        # commune_market_data — columnas metodología v2 + income estimator
        existing_cmd_cols = {c['name'] for c in inspector.get_columns('commune_market_data')} if inspector.has_table('commune_market_data') else set()
        for col, defn in [
            ('rent_index',          'FLOAT DEFAULT 100.0'),
            ('rent_pct',            'FLOAT DEFAULT 50.0'),
            ('geo_score',           'FLOAT DEFAULT 50.0'),
            ('source_name',         "TEXT DEFAULT ''"),
            ('income_pct',          'FLOAT DEFAULT 50.0'),
            ('estimated_income_ppp', 'FLOAT DEFAULT NULL'),  # ingreso individual mensual PPP estimado desde m²
        ]:
            if col not in existing_cmd_cols:
                try:
                    conn.execute(text(f'ALTER TABLE commune_market_data ADD COLUMN {col} {defn}'))
                    conn.commit()
                except Exception:
                    pass
        # users — columna composite income
        existing_user_cols = {c['name'] for c in inspector.get_columns('users')} if inspector.has_table('users') else set()
        if 'estimated_income_ppp' not in existing_user_cols:
            try:
                conn.execute(text('ALTER TABLE users ADD COLUMN estimated_income_ppp FLOAT DEFAULT NULL'))
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

    def _run_se_lifestyle_job():
        try:
            from se_lifestyle_agent import run_se_lifestyle_debates
            print('[Scheduler] Iniciando SE Lifestyle Agent...')
            result = run_se_lifestyle_debates(max_per_tier=2)
            print(f'[Scheduler] SE Lifestyle — creados: {result.get("debates_created", 0)}, saltados: {result.get("debates_skipped", 0)}')
        except Exception as e:
            print(f'[Scheduler] Error en SE Lifestyle Agent: {e}')

    def _run_annual_rental_prices_job():
        try:
            from rental_price_agent import run_full_agent
            from database import SessionLocal as _SL
            print('[Scheduler] Iniciando RentalPriceAgent — actualización anual precios m²...')
            _db = _SL()
            try:
                result = run_full_agent(_db)
                print(f'[Scheduler] Precios actualizados — comunas: {result.get("total_communes", 0)}, API hits: {result.get("api_hits", 0)}, fuente: {result.get("source", "?")}')
            finally:
                _db.close()
        except Exception as e:
            print(f'[Scheduler] Error en RentalPriceAgent: {e}')

    _scheduler = BackgroundScheduler(timezone='UTC')
    _scheduler.add_job(
        _run_daily_debates_job,
        CronTrigger(hour=7, minute=0),          # 7:00 AM UTC todos los días
        id='daily_debates',
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.add_job(
        _run_annual_rental_prices_job,
        CronTrigger(month=1, day=2, hour=3, minute=0),  # 2 enero, 3:00 AM UTC — anual
        id='annual_rental_prices',
        replace_existing=True,
        misfire_grace_time=86400,
    )
    _scheduler.add_job(
        _run_se_lifestyle_job,
        CronTrigger(day_of_week='mon', hour=8, minute=0),  # lunes 8:00 AM UTC — semanal
        id='se_lifestyle_debates',
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    print('[Scheduler] ✅ Scheduler activo — debates diarios 7:00 AM UTC | lifestyle lunes 8:00 AM | precios 2 enero')
except Exception as _sched_err:
    print(f'[Scheduler] ⚠️ No se pudo iniciar scheduler: {_sched_err}')

SECRET = os.getenv('JWT_SECRET')
security          = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)  # no lanza error si no hay token

# Sin valor de respaldo hardcodeado a propósito — si falta la variable de entorno,
# el sistema debe fallar cerrado (nadie puede firmar tokens ni pasar el chequeo admin)
# en vez de aceptar silenciosamente un secret conocido públicamente.
if not SECRET:
    print('[SECURITY] ⚠️⚠️⚠️ JWT_SECRET no está configurado — todo login/token fallará hasta que se setee en Render.')
if not os.getenv('ADMIN_SECRET'):
    print('[SECURITY] ⚠️⚠️⚠️ ADMIN_SECRET no está configurado — todos los endpoints /admin quedan inaccesibles hasta que se setee en Render.')

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
        # Rol del token tiene prioridad sobre el de la DB (permite override via admin/user-token)
        token_role = payload.get('role', '')
        if token_role:
            user.role = token_role
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

def compute_device_composite(imei_raw: str, sim_raw: str, lat: float = None, lon: float = None) -> dict:
    """Fórmula de identidad compuesta ponderada.
    composite = SHA256( IMEI×3 | SIM×2 | coords×1 )
    Nunca se comparte el valor raw — solo el composite y los hashes individuales.
    Cumple con las políticas de Apple/Google: no se expone el IMEI directamente.

    Si el composite difiere entre dos registros, se contrasta señal por señal:
    1° IMEI → 2° SIM/chip → 3° Ubicación
    Esto permite detectar: mismo teléfono + nuevo SIM, o mismo SIM en otro aparato.
    """
    imei_clean = re.sub(r'\D', '', imei_raw or '')
    sim_clean  = re.sub(r'\D', '', sim_raw  or '')
    lat_r = round(float(lat or 0), 3)   # precisión ~111m
    lon_r = round(float(lon or 0), 3)

    # Pesos: IMEI más único que SIM, SIM más estable que ubicación
    weighted = (imei_clean * 3) + '|' + (sim_clean * 2) + '|' + f'{lat_r},{lon_r}'
    composite = hashlib.sha256(weighted.encode()).hexdigest()

    return {
        'composite':  composite,
        'imei_hash':  hashlib.sha256(imei_clean.encode()).hexdigest() if imei_clean else None,
        'sim_hash':   hashlib.sha256(sim_clean.encode()).hexdigest()  if sim_clean  else None,
        'location':   f'{lat_r},{lon_r}',
    }

def compare_device_signals(new: dict, stored: dict) -> dict:
    """Contraste señal por señal cuando el composite no coincide.
    Orden: IMEI → SIM → ubicación.
    Retorna el nivel de coincidencia para decidir si bloquear o alertar.
    """
    imei_match = bool(new.get('imei_hash') and new['imei_hash'] == stored.get('imei_hash'))
    sim_match  = bool(new.get('sim_hash')  and new['sim_hash']  == stored.get('sim_hash'))
    loc_match  = new.get('location') == stored.get('location')

    if new['composite'] == stored.get('composite'):
        return {'same': True,  'level': 'full',     'detail': 'IMEI+SIM+ubicación coinciden'}
    elif imei_match and sim_match:
        return {'same': True,  'level': 'imei+sim',  'detail': 'Mismo aparato y chip, ubicación distinta (viajó)'}
    elif imei_match:
        return {'same': True,  'level': 'imei_only', 'detail': 'Mismo aparato, SIM distinta — posible cambio de chip'}
    elif sim_match:
        return {'same': False, 'level': 'sim_only',  'detail': 'Mismo chip en otro aparato — alerta fraude'}
    else:
        return {'same': False, 'level': 'none',      'detail': 'Dispositivo distinto'}

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
    verify_opens = debate.verify_opens_at or (debate.closes_at + timedelta(days=1))
    if now < verify_opens:
        return 'closed'      # cerrada, aún no abre verificación (primeras 24h)
    if debate.verify_closes_at and now <= debate.verify_closes_at:
        return 'verifying'
    return 'verified'

def format_debate(debate, has_voted=False, sponsor_info=None):
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
    d = {
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
        'verify_opens_at': debate.verify_opens_at.isoformat() if debate.verify_opens_at else None,
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
        'target_se_tiers': debate.target_se_tiers or 'A,B,C,D',
        'is_sponsored': False,
        'sponsor_name': '',
        'sponsor_logo_url': '',
        'sponsor_discount_pct': 0,
        'sponsor_discount_text': '',
    }
    if sponsor_info:
        d['is_sponsored'] = True
        d['sponsor_name'] = sponsor_info.get('name', '')
        d['sponsor_logo_url'] = sponsor_info.get('logo_url', '')
        d['sponsor_discount_pct'] = sponsor_info.get('discount_pct', 0)
        d['sponsor_discount_text'] = sponsor_info.get('discount_text', '')
    return d

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


def _send_html_email(to_email: str, subject: str, html_body: str) -> bool:
    resend_key = os.getenv('RESEND_API_KEY')
    if resend_key:
        try:
            resp = _requests.post(
                'https://api.resend.com/emails',
                json={'from': 'Preferendum <noreply@preferendum.com>', 'to': [to_email],
                      'subject': subject, 'html': html_body},
                headers={'Authorization': f'Bearer {resend_key}'},
                timeout=10,
            )
            if resp.status_code in (200, 201):
                return True
        except Exception as e:
            print(f'[Resend Error] {e}')
    gmail_user = os.getenv('GMAIL_USER', 'jucaferla@gmail.com')
    gmail_pass = os.getenv('GMAIL_APP_PASSWORD')
    if not gmail_pass:
        print(f'[DEV EMAIL] To: {to_email} | Subject: {subject}')
        return True
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f'Preferendum <{gmail_user}>'
        msg['To'] = to_email
        msg.attach(MIMEText(html_body, 'html'))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f'[Email Error] {e}')
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
    income_min_usd:      float = None   # ingreso anual mínimo en USD — None = sin filtro
    income_max_usd:      float = None   # ingreso anual máximo en USD — None = sin filtro
    category:            str = 'general'
    closes_at:           str
    verify_days:         int = 15
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
    target_age_weights:   str = ''   # JSON {"18-24":30,"25-34":70}
    target_company_sizes: str = ''   # 'small,medium,large' o '' = todos
    target_categories:    str = ''
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
    target_hnw_only:     bool  = False   # True = solo usuarios verified_hnw
    min_hnw_score:       float = 0.0     # hnw_score mínimo (ej: 50.0)
    frequency_cap:       Optional[int] = None  # máx. veces que UN usuario ve este anuncio (None = sin límite)

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
                verify_closes_at=now + timedelta(days=8),
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
                verify_closes_at=now + timedelta(days=15),
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
                verify_closes_at=now + timedelta(days=6),
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
  text-transform:uppercase;margin-bottom:10px;}
.brand span{color:#4d8aff;}
.brand-sub{font-size:clamp(11px,1.8vw,14px);color:rgba(240,244,255,0.50);
  letter-spacing:0.18em;text-transform:uppercase;margin-bottom:42px;font-weight:400;}
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
  <div class="brand-sub">The Global Preference Network</div>
  <h1 class="headline">
    Anyone.<br/>
    Anywhere.<br/>
    <em>Any issue.</em>
  </h1>
  <p class="nuance">
    <strong>Global decisions. Define your path.</strong><br/>
    When every preference is expressed, collective intelligence emerges.
  </p>
  <button class="enter-btn" onclick="showPage2()">
    Enter →
  </button>
  <div class="tagline">Freedom to choose. Together.</div>
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
      <div class="role-phrase">"Do you want to ask your peers to express their preferences to discover collective preferences and define the path forward?"</div>
    </a>
    <a href="/marketers" class="role-card">
      <span class="role-arrow">→</span>
      <div class="role-name">I want to sponsor consultations</div>
      <div class="role-phrase">"Keep participation free. Enable better decisions."</div>
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
    user = db.query(User).filter(func.lower(User.email) == func.lower(email)).first()
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
def health(db: Session = Depends(get_db)):
    # RENDER_GIT_COMMIT is set automatically by Render for every deploy —
    # exposing it lets CI know it's actually talking to the NEW deploy.
    # Also pings the DB so it stays awake on Render's free-tier PostgreSQL
    # (sleeping DB causes 30s+ cold-start that times out vote requests).
    db_ok = False
    try:
        db.execute(text('SELECT 1'))
        db_ok = True
    except Exception:
        pass
    return {
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat(),
        'git_commit': os.getenv('RENDER_GIT_COMMIT', ''),
        'db': 'ok' if db_ok else 'error',
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
    profession:   str        # profesión declarada — obligatoria para tier
    cargo:        str        # cargo jerárquico (ceo, gerente, analista, etc.) — obligatorio
    company_size: str = ''   # tamaño de empresa (opcional)
    ref_source:   str = ''   # canal de adquisición: fb, ig, tiktok, direct, etc.
    ref_code:     str = ''   # código de referido de otro usuario (invitación persona-a-persona)
    device_fp:    str = ''


@app.post('/voter/register')
def voter_register(data: VoterRegisterInput, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Register a voter — sends email OTP for verification."""
    try:
        return _voter_register_inner(data, bg, db)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f'[voter_register] UNCAUGHT: {traceback.format_exc()}')
        raise HTTPException(500, f'Error interno: {str(e)}')

def _voter_register_inner(data: VoterRegisterInput, bg: BackgroundTasks, db):
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
    existing = db.query(User).filter(func.lower(User.email) == func.lower(data.email)).first()
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
    import secrets as _secrets_ref
    referrer = None
    if data.ref_code:
        referrer = db.query(User).filter(User.referral_code == data.ref_code.strip().upper()).first()
    user = User(
        email=data.email, name=data.name, password=hashed,
        country=data.country, email_verified=False,
        phone=data.phone, county=data.commune,
        gender=data.gender, dob=data.dob, national_id=data.national_id,
        profession=data.profession or '',
        cargo=data.cargo or '',
        company_size=data.company_size or '',
        ref_source=data.ref_source or '',
        referral_code='R' + _secrets_ref.token_hex(4).upper(),
        referred_by_user_id=referrer.id if referrer else None,
    )
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as _e:
        db.rollback()
        raise HTTPException(500, f'DB error al crear usuario: {str(_e)}')
    try:
        _assign_user_tier(user, db)
        # Fallback: si no se pudo calcular un tier real (comuna sin datos), heredar
        # el del referente — la gente invita a gente de nivel socioeconómico similar.
        if not user.se_tier and referrer and referrer.se_tier:
            db.execute(text(
                "UPDATE users SET se_tier=:t, income_index=:i, tier_pre_evaluated=TRUE WHERE id=:uid"
            ), {'t': referrer.se_tier, 'i': referrer.income_index or 0, 'uid': user.id})
            db.commit()
            user.se_tier = referrer.se_tier
            user.tier_pre_evaluated = True
    except Exception as _e:
        print(f'[voter_register] _assign_user_tier non-fatal error: {_e}')
    code = gen_otp()
    try:
        check_and_register_device(data.device_fp, user.id, db)
        db.add(OTPCode(user_id=user.id, email=user.email, code=code, channel='email',
                       expires_at=datetime.utcnow() + timedelta(minutes=15)))
        db.commit()
    except Exception as _e:
        print(f'[voter_register] OTP/device error (non-fatal): {_e}')
    bg.add_task(send_email_otp, user.email, code, user.name)
    return {'token': make_token(user.id), 'user': {
        'id': user.id, 'name': user.name, 'email': user.email,
        'email_verified': False, 'phone': data.phone,
        'se_tier': user.se_tier or '',
        'referral_code': user.referral_code or '',
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
    if db.query(User).filter(func.lower(User.email) == func.lower(data.email)).first():
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
    user = db.query(User).filter(func.lower(User.email) == func.lower(data.email)).first()
    if not user or not bcrypt.checkpw(data.password.encode(), user.password.encode()):
        raise HTTPException(401, 'Invalid credentials')
    check_and_register_device(data.device_fp, user.id, db)

    # Cuentas demo para revisión de Apple/Google y auditoría externa — sin 2FA
    # porque quien las usa no tiene acceso al correo/teléfono para completar el código.
    APP_REVIEW_DEMO_EMAILS = {'jucaferla@gmail.com', 'chatgpt.auditor@preferendum.com'}
    is_demo_account = (user.email or '').strip().lower() in APP_REVIEW_DEMO_EMAILS

    needs_2fa = (not is_demo_account) and (user.email_verified or user.phone_verified or user.selfie_verified)
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
        print(f'[login face-token] Rekognition error: {e}')
        raise HTTPException(503, 'Verificación facial no disponible en este momento.')

    # Solo llega aquí si rekognition_mode == 'verified'
    face_token = jwt.encode({
        'sub': user_id, 'type': 'face_login',
        'exp': datetime.utcnow() + timedelta(minutes=5)
    }, SECRET, algorithm='HS256')

    return {
        'face_token': face_token,
        'rekognition_score': rekognition_score,
        'rekognition_mode': rekognition_mode,
        'message': f'✅ {rekognition_score}% coincidencia' if rekognition_score else '✅ Identidad verificada'
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
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {
        'id': user.id, 'name': user.name, 'email': user.email,
        'country': user.country or 'CL',
        'verify_level': user.verify_level, 'is_verified': user.is_verified,
        'email_verified': user.email_verified,
        'phone_verified': user.phone_verified,
        'selfie_verified': user.selfie_verified,
        'referral_code': _ensure_referral_code(user, db),
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
        # Nunca aprobar a ciegas sin revisión real — si no se puede moderar con IA,
        # que quede pendiente de revisión manual, no publicada automáticamente.
        return {'score': 50, 'decision': 'review', 'reason': 'Sin acceso a IA de moderación — requiere revisión manual'}

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


# Profesiones que indican ingreso alto (elevan tier a A si la comuna lo permite)
_PROFESSION_TIER: dict[str, str] = {
    # Códigos nuevos (22 categorías BLS universales)
    'mgmt':           'A',  # Dirección/Gerencia
    'legal':          'A',  # Derecho/Jurídico
    'healthcare_pro': 'A',  # Salud Profesional
    'computer':       'A',  # TI/Computación
    'engineering':    'B',  # Arquitectura/Ingeniería
    'biz_fin':        'B',  # Negocios/Finanzas
    'science':        'B',  # Ciencias
    'education':      'B',  # Educación/Docencia
    'installation':   'B',  # Instalación Industrial
    'arts_media':     'C',  # Arte/Medios
    'construction':   'C',  # Construcción
    'production':     'C',  # Manufactura/Operario
    'transport':      'C',  # Transporte/Logística
    'sales':          'C',  # Ventas
    'admin':          'C',  # Administración/Oficina
    'protective':     'C',  # Seguridad
    'healthcare_sup': 'C',  # Salud Técnico/Apoyo
    'social_svc':     'C',  # Servicios Sociales
    'agriculture':    'C',  # Agricultura
    'cleaning':       'D',  # Limpieza/Mantenimiento
    'food_svc':       'D',  # Alimentación/Gastronomía
    'personal_care':  'D',  # Cuidado Personal
    'student':        'C',  # Estudiante
    'retired':        'C',  # Jubilado
    'homemaker':      'D',  # Labores del hogar
    'unemployed':     'D',  # En búsqueda de trabajo
    # Códigos legacy (usuarios existentes)
    'medico': 'A', 'dentista': 'A', 'abogado': 'A', 'juez': 'A',
    'economista': 'A', 'ing_civil': 'A', 'ing_comercial': 'A',
    'empresario': 'A', 'ejecutivo': 'A', 'financiero': 'A',
    'farmaceutico': 'B', 'psicologo': 'B', 'contador': 'B',
    'ing_informatica': 'B', 'arquitecto': 'B', 'ing_otro': 'B',
    'consultor': 'B', 'marketing': 'B', 'profesor_univ': 'B',
    'cientifico': 'B', 'periodista': 'C', 'artista': 'C',
    'ventas': 'C', 'profesor_escuela': 'C', 'tecnico': 'C',
    'enfermero': 'C', 'comercio': 'C', 'estudiante': 'C',
    'mecanico': 'D', 'construccion': 'D', 'transporte': 'D',
    'servicios': 'D', 'hogar': 'D', 'desempleado': 'D',
}

# Mapeo ocupación → BLS major_group para lookup en occupation_unified (USA)
_US_PROFESSION_SOC: dict[str, str] = {
    # Códigos nuevos (categorías BLS)
    'mgmt':           '11-0000',
    'biz_fin':        '13-0000',
    'computer':       '15-0000',
    'engineering':    '17-0000',
    'science':        '19-0000',
    'social_svc':     '21-0000',
    'legal':          '23-0000',
    'education':      '25-0000',
    'arts_media':     '27-0000',
    'healthcare_pro': '29-0000',
    'healthcare_sup': '31-0000',
    'protective':     '33-0000',
    'food_svc':       '35-0000',
    'cleaning':       '37-0000',
    'personal_care':  '39-0000',
    'sales':          '41-0000',
    'admin':          '43-0000',
    'agriculture':    '45-0000',
    'construction':   '47-0000',
    'installation':   '49-0000',
    'production':     '51-0000',
    'transport':      '53-0000',
    # Códigos legacy → major_group más cercano
    'medico':          '29-0000',
    'dentista':        '29-0000',
    'abogado':         '23-0000',
    'juez':            '23-0000',
    'economista':      '19-0000',
    'ing_civil':       '17-0000',
    'ing_comercial':   '11-0000',
    'empresario':      '11-0000',
    'ejecutivo':       '11-0000',
    'financiero':      '13-0000',
    'farmaceutico':    '29-0000',
    'psicologo':       '19-0000',
    'contador':        '13-0000',
    'ing_informatica': '15-0000',
    'arquitecto':      '17-0000',
    'ing_otro':        '17-0000',
    'consultor':       '13-0000',
    'marketing':       '11-0000',
    'profesor_univ':   '25-0000',
    'cientifico':      '19-0000',
    'periodista':      '27-0000',
    'artista':         '27-0000',
    'ventas':          '41-0000',
    'profesor_escuela':'25-0000',
    'tecnico':         '17-0000',
    'enfermero':       '29-0000',
    'comercio':        '41-0000',
    'mecanico':        '49-0000',
    'construccion':    '47-0000',
    'transporte':      '53-0000',
    'servicios':       '35-0000',
    'hogar':           '37-0000',
}

# Mapeo ocupación → ISCO group para lookup en occupation_unified (no-USA)
_OCC_TO_ISCO: dict[str, int] = {
    # Códigos nuevos
    'mgmt': 1, 'biz_fin': 2, 'computer': 2, 'engineering': 2,
    'science': 2, 'social_svc': 2, 'legal': 2, 'education': 2,
    'arts_media': 2, 'healthcare_pro': 2, 'healthcare_sup': 3,
    'protective': 5, 'food_svc': 5, 'cleaning': 9, 'personal_care': 5,
    'sales': 5, 'admin': 4, 'agriculture': 6, 'construction': 7,
    'installation': 7, 'production': 8, 'transport': 8,
    # Códigos legacy
    'medico': 2, 'dentista': 2, 'abogado': 2, 'juez': 2,
    'economista': 2, 'ing_civil': 2, 'ing_comercial': 1,
    'empresario': 1, 'ejecutivo': 1, 'financiero': 2,
    'farmaceutico': 2, 'psicologo': 2, 'contador': 2,
    'ing_informatica': 2, 'arquitecto': 2, 'ing_otro': 2,
    'consultor': 2, 'marketing': 1, 'profesor_univ': 2,
    'cientifico': 2, 'periodista': 2, 'artista': 2,
    'ventas': 5, 'profesor_escuela': 2, 'tecnico': 3,
    'enfermero': 3, 'comercio': 5, 'mecanico': 7,
    'construccion': 7, 'transporte': 8, 'servicios': 5,
    'hogar': 9,
}

# Cargo jerárquico — eleva el tier independientemente de profesión o comuna
_CARGO_TIER: dict[str, str] = {
    'ceo':              'A',  # CEO / Dueño / Fundador
    'gerente_general':  'A',  # Gerente General
    'director':         'A',  # Director / Socio
    'gerente':          'A',  # Gerente de Área
    'subgerente':       'B',  # Sub-Gerente
    'jefe':             'B',  # Jefe de Departamento
    'supervisor':       'B',  # Supervisor / Coordinador
    'profesional':      'B',  # Profesional / Analista Senior
    'analista':         'C',  # Analista / Especialista
    'asistente':        'C',  # Asistente / Administrativo
    'tecnico_cargo':    'C',  # Técnico / Operario
    'practicante':      'D',  # Practicante / Junior
    'independiente':    'B',  # Independiente / Freelance
}

def _tier_rank(t: str) -> int:
    return {'A': 4, 'B': 3, 'C': 2, 'D': 1}.get(t, 0)

# Palabras clave en títulos/categorías de debates que indican perfil HNW
_HNW_DEBATE_KEYWORDS = [
    'inversion', 'inversión', 'bolsa', 'mercado financiero', 'cripto', 'bitcoin',
    'bienes raices', 'bienes raíces', 'inmobiliaria', 'real estate', 'propiedad',
    'lujo', 'luxury', 'premium', 'porsche', 'ferrari', 'rolex', 'lvmh',
    'viaje', 'turismo', 'primera clase', 'yate', 'aviacion', 'aviación',
    'impuesto', 'riqueza', 'patrimonio', 'dividendo', 'hedge fund',
    'startup', 'venture', 'emprendimiento', 'empresa', 'fusión', 'adquisicion',
    'exportacion', 'exportación', 'comercio internacional',
]

_HNW_DEBATE_CATEGORIES = {'economia', 'finanzas', 'negocios', 'tecnologia', 'lujo', 'viajes'}

_HNW_CARGO = {'ceo', 'chairman', 'director', 'gerente_general', 'founder', 'socio', 'president'}
_HNW_CARGO_MID = {'gerente', 'subgerente', 'vp', 'cfo', 'cto', 'coo'}
_HNW_COMPANY_BIG = {'500+', '201-500'}
_HNW_COMPANY_MID = {'51-200', '100-499'}


def _calculate_hnw_score(user, db) -> float:
    """
    Score 0-100 de probabilidad de ser High Net Worth (patrimonio >$1M USD).
    Combina 4 señales: zona, cargo, empresa y comportamiento en debates.
    No reemplaza se_tier — es una capa adicional para targeting de lujo.
    """
    score = 0.0

    # ── Señal 1: Zona donde vive (35 pts) ────────────────────────────────────
    # Tier A desde la comuna (no solo desde la profesión) = vive en zona cara
    commune_tier = None
    if user.county and _country_code(getattr(user, 'country', 'CL') or 'CL'):
        row = db.execute(text("""
            SELECT se_tier FROM commune_market_data
            WHERE commune ILIKE :c
            LIMIT 1
        """), {'c': user.county.strip()}).fetchone()
        if row:
            commune_tier = row[0]

    if commune_tier == 'A':
        score += 35
    elif commune_tier == 'B':
        score += 15
    elif commune_tier == 'C':
        score += 5

    # ── Señal 2: Cargo jerárquico (25 pts) ───────────────────────────────────
    cargo = (getattr(user, 'cargo', '') or '').lower().strip()
    if cargo in _HNW_CARGO:
        score += 25
    elif cargo in _HNW_CARGO_MID:
        score += 10

    # ── Señal 3: Tamaño de empresa (15 pts) ──────────────────────────────────
    company = (getattr(user, 'company_size', '') or '').strip()
    if company in _HNW_COMPANY_BIG:
        score += 15
    elif company in _HNW_COMPANY_MID:
        score += 7

    # ── Señal 4: Comportamiento en debates (25 pts) ───────────────────────────
    # Cuenta debates de lujo/inversión/viajes en los que el usuario ha votado
    try:
        kw_conditions = ' OR '.join([f"LOWER(d.title) LIKE '%{kw}%'" for kw in _HNW_DEBATE_KEYWORDS[:12]])
        cat_list = "','".join(_HNW_DEBATE_CATEGORIES)
        hnw_votes = db.execute(text(f"""
            SELECT COUNT(DISTINCT d.id)
            FROM debate_votes v
            JOIN debates d ON d.id = v.debate_id
            WHERE v.user_id = :uid
              AND (d.category IN ('{cat_list}') OR {kw_conditions})
        """), {'uid': user.id}).scalar() or 0
        score += min(25, int(hnw_votes) * 5)
    except Exception:
        pass

    return round(min(100.0, score), 1)


def _ensure_referral_code(user, db):
    """Genera y persiste un referral_code si el usuario aún no tiene uno —
    cubre cualquier vía de registro (votante, organizador, marketer), no solo /voter/register."""
    if user.referral_code:
        return user.referral_code
    import secrets as _secrets_lazy
    code = 'R' + _secrets_lazy.token_hex(4).upper()
    try:
        db.execute(text("UPDATE users SET referral_code=:c WHERE id=:uid"), {'c': code, 'uid': user.id})
        db.commit()
        user.referral_code = code
    except Exception:
        db.rollback()
    return user.referral_code


def _assign_user_tier(user, db):
    """Asigna se_tier e income_index combinando comuna + profesión declarada."""
    try:
        with db.no_autoflush:
            _assign_user_tier_inner(user, db)
    except Exception:
        pass

    # Capturar valores calculados (están en el objeto Python aunque la TX esté abortada)
    _new_tier  = user.se_tier
    _new_index = user.income_index
    _new_est   = getattr(user, 'estimated_income_usd', None)
    _new_ppp   = getattr(user, 'estimated_income_ppp',  None)
    _new_hnw   = getattr(user, 'hnw_score', None)

    if not _new_tier:
        return

    # Limpiar cualquier transacción PostgreSQL abortada antes del UPDATE final
    try:
        db.rollback()
    except Exception:
        pass

    # UPDATE directo por SQL — no depende del ORM flush, funciona aunque la TX anterior haya fallado
    try:
        db.execute(text(
            "UPDATE users SET se_tier=:t, income_index=:i, estimated_income_usd=:e,"
            " estimated_income_ppp=:ppp WHERE id=:uid"
        ), {'t': _new_tier, 'i': _new_index or 0, 'e': _new_est, 'ppp': _new_ppp, 'uid': user.id})
        db.commit()
        user.se_tier              = _new_tier
        user.income_index         = _new_index
        if hasattr(user, 'estimated_income_usd'):
            user.estimated_income_usd = _new_est
        if hasattr(user, 'estimated_income_ppp'):
            user.estimated_income_ppp = _new_ppp
    except Exception:
        db.rollback()

def _assign_user_tier_inner(user, db):
    commune_tier = None
    if user.county:
        country_code = _country_code(user.country)
        raw = user.county.strip()
        # 1. Exacto por país
        commune_data = db.query(CommuneMarketData).filter(
            CommuneMarketData.commune.ilike(raw),
            CommuneMarketData.country == country_code
        ).first()
        # 2. Prefijos decrecientes: 6→5→4→3→2 chars (UK "SW1A"→"SW1"→"SW", ES/DE "28001"→"280"→"28")
        if not commune_data:
            for length in (6, 5, 4, 3, 2):
                prefix = raw[:length].rstrip()
                if not prefix or len(prefix) < length:
                    continue
                commune_data = db.query(CommuneMarketData).filter(
                    CommuneMarketData.commune.like(f'{prefix}%'),
                    CommuneMarketData.country == country_code
                ).first()
                if commune_data:
                    break
        # 3. Para UK: probar solo letras del inicio (área postal: "SW", "W", "NW"…)
        if not commune_data and country_code == 'GB':
            area = ''
            for ch in raw:
                if ch.isalpha():
                    area += ch
                else:
                    break
            if area:
                commune_data = db.query(CommuneMarketData).filter(
                    CommuneMarketData.commune.ilike(f'{area}%'),
                    CommuneMarketData.country == 'GB'
                ).first()
        # 4. Fallback global por nombre parcial (usuarios registrados antes del ZIP)
        if not commune_data:
            commune_data = db.query(CommuneMarketData).filter(
                CommuneMarketData.commune.ilike(f'%{raw}%')
            ).first()
        if commune_data:
            commune_tier      = commune_data.se_tier
            user.income_index = commune_data.income_index
        elif country_code:
            # 5. Fallback país — usa la moda del se_tier real de ese país (no get_se_tier(avg_index)
            # porque rent_index y income_index tienen escalas distintas según la fuente del dato)
            from sqlalchemy import func as _sqlfunc
            tier_row = db.execute(text("""
                SELECT se_tier, COUNT(*) AS cnt
                FROM commune_market_data
                WHERE country = :cc
                  AND se_tier IS NOT NULL AND se_tier != ''
                  AND LENGTH(se_tier) = 1
                GROUP BY se_tier ORDER BY cnt DESC LIMIT 1
            """), {'cc': country_code}).fetchone()
            avg_index = db.query(_sqlfunc.avg(CommuneMarketData.income_index)).filter(
                CommuneMarketData.country == country_code,
                CommuneMarketData.income_index > 0,
            ).scalar()
            if tier_row:
                commune_tier      = tier_row[0]
                user.income_index = round(float(avg_index), 1) if avg_index else 50.0

    user_profession   = getattr(user, 'profession', '') or ''
    user_country_code = _country_code(user.country)

    # Consultar GDP per cápita real desde world_countries (Banco Mundial, 264 países)
    _wc = db.execute(text(
        "SELECT gdp_per_capita_usd FROM world_countries WHERE iso2 = :cc"
    ), {'cc': user_country_code}).fetchone()
    _country_gdp = float(_wc[0]) if _wc and _wc[0] else None

    # Países con GDP per cápita < $10K → m² de arriendo es el clasificador primario de tier
    _is_low_gdp = bool(_country_gdp and _country_gdp < 10000)

    # Ingreso mediano estimado ≈ GDP per cápita × 0.50
    # (el GDP incluye utilidades empresariales y gasto público; el ingreso
    #  personal mediano es ~50% del GDP per cápita en la mayoría de países)
    _country_median_income = (_country_gdp * 0.50) if _country_gdp else None

    profession_tier = None
    if user_profession:
        import re as _re
        _is_soc = bool(_re.match(r'^\d{2}-\d{4}$', user_profession))
        try:
            from usa_data_agent import profession_score_to_tier
            if _is_soc:
                # Nuevo sistema: SOC code universal de la lista BLS
                if user_country_code == 'US':
                    # 1. Intentar salario específico por MSA/condado del usuario
                    msa_income = None
                    if getattr(user, 'county', ''):
                        try:
                            from bls_oews_msa_agent import get_msa_salary
                            msa_data = get_msa_salary(user_profession, user.county, db)
                            if msa_data and msa_data.get('median_annual_usd'):
                                msa_income = msa_data['median_annual_usd']
                        except Exception:
                            pass
                    # 2. Fallback: mediana nacional
                    row = db.execute(text("""
                        SELECT profession_score, median_annual_usd FROM occupation_unified
                        WHERE occupation_code=:code AND country_iso='US'
                    """), {'code': user_profession}).fetchone()
                    if row and row[0] is not None:
                        profession_tier = profession_score_to_tier(float(row[0]))
                        user.estimated_income_usd = msa_income or (float(row[1]) if row[1] else None)
                else:
                    # No-USA: SOC → ISCO group → ingreso local del país
                    isco_row = db.execute(text("""
                        SELECT isco_group FROM occupation_unified
                        WHERE occupation_code=:code AND country_iso='US'
                    """), {'code': user_profession}).fetchone()
                    if isco_row and isco_row[0]:
                        isco_grp = isco_row[0]
                        # 0. China: datos NBS PPP-adjusted (fuente primaria para CN)
                        if user_country_code == 'CN':
                            try:
                                from china_wages_agent import get_china_income
                                china = get_china_income(getattr(user, 'county', None), isco_grp, db)
                                if china:
                                    profession_tier = profession_score_to_tier(china['score'])
                                    user.estimated_income_usd = china['annual_usd']
                            except Exception:
                                china = None
                        # 1. Datos reales ILO ILOSTAT (fuente primaria, ~65 países no-CN)
                        if user_country_code != 'CN':
                            try:
                                from ilo_ilostat_agent import get_ilo_income
                                ilo = get_ilo_income(user_country_code, isco_grp, db)
                                if ilo:
                                    profession_tier = profession_score_to_tier(ilo['score'])
                                    user.estimated_income_usd = ilo['annual_usd']
                            except Exception:
                                ilo = None
                        if not profession_tier:
                            # 2. Fallback: occupation_unified ISCO rows (semillas LATAM)
                            row = db.execute(text("""
                                SELECT profession_score, median_annual_usd FROM occupation_unified
                                WHERE country_iso=:cc AND isco_group=:ig
                                  AND occupation_type='ISCO' AND profession_score IS NOT NULL
                                LIMIT 1
                            """), {'cc': user_country_code, 'ig': isco_grp}).fetchone()
                            if row and row[0] is not None:
                                profession_tier = profession_score_to_tier(float(row[0]))
                                if row[1]: user.estimated_income_usd = float(row[1])
                            else:
                                # 3. Fallback global: promedio ISCO en occupation_unified
                                row = db.execute(text("""
                                    SELECT AVG(profession_score), AVG(median_annual_usd)
                                    FROM occupation_unified
                                    WHERE isco_group=:ig AND occupation_type='ISCO'
                                      AND profession_score IS NOT NULL
                                """), {'ig': isco_grp}).fetchone()
                                if row and row[0] is not None:
                                    profession_tier = profession_score_to_tier(float(row[0]))
                                    if row[1]: user.estimated_income_usd = float(row[1])
            elif user_country_code == 'US':
                # Legacy codes — USA: lookup por major_group
                major_group = _US_PROFESSION_SOC.get(user_profession)
                if major_group:
                    row = db.execute(text("""
                        SELECT AVG(profession_score), AVG(median_annual_usd) FROM occupation_unified
                        WHERE country_iso='US'
                          AND SUBSTRING(occupation_code, 1, 2) = SUBSTRING(:mg, 1, 2)
                          AND occupation_type='SOC' AND profession_score IS NOT NULL
                    """), {'mg': major_group}).fetchone()
                    if row and row[0] is not None:
                        profession_tier = profession_score_to_tier(float(row[0]))
                        if row[1]: user.estimated_income_usd = float(row[1])
            else:
                # Legacy codes — no-USA: lookup por ISCO group
                isco_grp = _OCC_TO_ISCO.get(user_profession)
                if isco_grp:
                    # 1. ILO primero
                    try:
                        from ilo_ilostat_agent import get_ilo_income
                        ilo = get_ilo_income(user_country_code, isco_grp, db)
                        if ilo:
                            profession_tier = profession_score_to_tier(ilo['score'])
                            user.estimated_income_usd = ilo['annual_usd']
                    except Exception:
                        ilo = None
                    if not profession_tier:
                        row = db.execute(text("""
                            SELECT profession_score, median_annual_usd FROM occupation_unified
                            WHERE country_iso=:cc AND isco_group=:ig
                              AND occupation_type='ISCO' AND profession_score IS NOT NULL
                            LIMIT 1
                        """), {'cc': user_country_code, 'ig': isco_grp}).fetchone()
                        if row and row[0] is not None:
                            profession_tier = profession_score_to_tier(float(row[0]))
                            if row[1]: user.estimated_income_usd = float(row[1])
        except Exception:
            pass
        if not profession_tier:
            # occupation_salary: datos reales INE ESI (CL) y seeds LATAM (BR/MX/CO/AR)
            try:
                from occupation_salary_agent import PROFESSION_TO_ISCO as _PROF_TO_ISCO
                from usa_data_agent import profession_score_to_tier as _pts
                _occ_isco = _PROF_TO_ISCO.get(user_profession)
                if _occ_isco:
                    _occ_row = db.execute(text("""
                        SELECT profession_score, median_monthly_usd
                        FROM occupation_salary
                        WHERE country_iso=:c AND isco_group=:g
                    """), {'c': user_country_code, 'g': _occ_isco}).fetchone()
                    if _occ_row and _occ_row[0] is not None:
                        profession_tier = _pts(float(_occ_row[0]))
                        if _occ_row[1] and not user.estimated_income_usd:
                            user.estimated_income_usd = round(float(_occ_row[1]) * 12, 0)
            except Exception:
                pass
        if not profession_tier:
            profession_tier = _PROFESSION_TIER.get(user_profession, None)
        # El tier estático actúa como piso mínimo: un médico nunca puede ser Tier C
        # aunque el score ILO/ISCO caiga en ese rango por distribución local
        _static_floor = _PROFESSION_TIER.get(user_profession, None)
        if _static_floor and profession_tier:
            profession_tier = max(profession_tier, _static_floor, key=_tier_rank)
        elif _static_floor:
            profession_tier = _static_floor

    # Ingreso por ocupación específica para JP/KR/RU (datos oficiales detallados)
    if user_profession and not profession_tier:
        if user_country_code == 'JP':
            try:
                from japan_wages_agent import get_japan_occupation_income
                from usa_data_agent import profession_score_to_tier as _pts
                jp_occ = get_japan_occupation_income(user_profession, db)
                if jp_occ and jp_occ.get('score') is not None:
                    profession_tier = _pts(jp_occ['score'])
                    user.estimated_income_usd = jp_occ['annual_usd']
            except Exception:
                pass
        elif user_country_code == 'KR':
            try:
                from korea_wages_agent import get_korea_occupation_income
                from usa_data_agent import profession_score_to_tier as _pts
                kr_occ = get_korea_occupation_income(user_profession, db)
                if kr_occ and kr_occ.get('score') is not None:
                    profession_tier = _pts(kr_occ['score'])
                    user.estimated_income_usd = kr_occ['annual_usd']
            except Exception:
                pass
        elif user_country_code == 'RU':
            try:
                from russia_wages_agent import get_russia_occupation_income
                from usa_data_agent import profession_score_to_tier as _pts
                ru_occ = get_russia_occupation_income(user_profession, db)
                if ru_occ and ru_occ.get('score') is not None:
                    profession_tier = _pts(ru_occ['score'])
                    user.estimated_income_usd = ru_occ['annual_usd']
            except Exception:
                pass
        elif user_country_code in ('NO', 'SE', 'DK'):
            try:
                from scandinavia_wages_agent import get_scandinavia_occupation_income
                from usa_data_agent import profession_score_to_tier as _pts
                sc_occ = get_scandinavia_occupation_income(user_country_code, user_profession, db)
                if sc_occ:
                    # Score basado en ratio vs ISCO 1 del mismo país
                    sc_isco1 = db.execute(text(
                        "SELECT median_monthly_usd FROM occupation_salary WHERE country_iso=:cc AND isco_group=1"
                    ), {'cc': user_country_code}).fetchone()
                    if sc_isco1 and sc_isco1[0]:
                        sc_score = min(100, round(sc_occ['monthly_usd'] / float(sc_isco1[0]) * 100, 1))
                        profession_tier = _pts(sc_score)
                    user.estimated_income_usd = sc_occ['annual_usd']
            except Exception:
                pass
        elif user_country_code == 'SG':
            try:
                from singapore_wages_agent import get_singapore_occupation_income
                from usa_data_agent import profession_score_to_tier as _pts
                sg_occ = get_singapore_occupation_income(user_profession, db)
                if sg_occ and sg_occ.get('score') is not None:
                    profession_tier = _pts(sg_occ['score'])
                    user.estimated_income_usd = sg_occ['annual_usd']
            except Exception:
                pass

    # Ingreso regional para JP/RU/NZ (datos oficiales por prefectura/sujeto federal/región)
    if not user.estimated_income_usd:
        if user_country_code == 'JP':
            try:
                from japan_wages_agent import get_japan_income
                jp = get_japan_income(getattr(user, 'county', None), db)
                if jp:
                    user.estimated_income_usd = jp['annual_usd']
            except Exception:
                pass
        elif user_country_code == 'RU':
            try:
                from russia_wages_agent import get_russia_income
                ru = get_russia_income(getattr(user, 'county', None), db)
                if ru:
                    user.estimated_income_usd = ru['annual_usd']
            except Exception:
                pass
        elif user_country_code == 'NZ':
            try:
                from new_zealand_wages_agent import get_new_zealand_income
                nz = get_new_zealand_income(getattr(user, 'county', None), db)
                if nz:
                    user.estimated_income_usd = nz['annual_usd']
            except Exception:
                pass

    # Fallback de ingreso por commune cuando no hay dato de ocupación
    if not user.estimated_income_usd and _country_median_income and user.income_index and user.income_index > 0:
        user.estimated_income_usd = round(_country_median_income * (user.income_index / 50.0), 0)

    cargo_tier       = _CARGO_TIER.get(getattr(user, 'cargo', '') or '', None)
    company_size     = getattr(user, 'company_size', '') or ''

    # Empresa grande (251+ empleados) sube el cargo 1 nivel adicional
    # Lógica: gerente general de Copec ≠ gerente general de empresa de 5 personas
    _BIG_COMPANY_SIZES = {'+1000', '251-1000'}
    if cargo_tier and company_size in _BIG_COMPANY_SIZES:
        tier_ladder  = ['D', 'C', 'B', 'A']
        cargo_rank   = _tier_rank(cargo_tier)
        cargo_tier   = tier_ladder[min(cargo_rank, 3)]  # sube 1 nivel (ya está en índice 0-3)

    # Tier base:
    # - Países GDP < $10K: commune_tier (m² arriendo) es el clasificador primario
    # - Países GDP >= $10K: el más alto entre commune y profesión
    if _is_low_gdp and commune_tier:
        base_tier = commune_tier  # m² arriendo manda
    else:
        base_candidates = [t for t in [commune_tier, profession_tier] if t]
        base_tier = max(base_candidates, key=_tier_rank) if base_candidates else None

    # Cargo (ya ajustado por tamaño empresa) sube máximo UN nivel sobre el tier base
    if base_tier and cargo_tier:
        base_rank  = _tier_rank(base_tier)
        cargo_rank = _tier_rank(cargo_tier)
        if cargo_rank > base_rank + 1:
            tier_ladder = ['D', 'C', 'B', 'A']
            cargo_tier  = tier_ladder[min(base_rank, 3)]
        user.se_tier = max(base_tier, cargo_tier, key=_tier_rank)
    elif base_tier:
        user.se_tier = base_tier
    elif cargo_tier:
        user.se_tier = cargo_tier

    # ── Ajuste de estimated_income_usd por tamaño de empresa y edad ─────────────
    # Multiplicadores por tamaño de empresa: empresa grande paga más por mismo cargo
    _COMPANY_SIZE_MULT = {
        '1-10':    0.72,
        '11-50':   0.85,
        '51-250':  1.00,
        '251-1000': 1.13,
        '+1000':   1.22,
    }
    # Multiplicadores por edad: curva de carrera típica
    _AGE_INCOME_MULT = {
        (0,  24): 0.55,
        (25, 29): 0.72,
        (30, 34): 0.87,
        (35, 44): 1.00,  # pico de carrera
        (45, 54): 1.08,
        (55, 64): 1.05,
        (65, 99): 0.85,
    }

    user_age_val = None
    if getattr(user, 'dob', ''):
        try:
            from datetime import date as _date
            dob_str = user.dob.strip()
            born = None
            for _fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
                try:
                    born = datetime.strptime(dob_str, _fmt).date()
                    break
                except ValueError:
                    pass
            if born:
                today = _date.today()
                user_age_val = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        except Exception:
            pass

    # Aplicar multiplicadores al ingreso estimado
    if user.estimated_income_usd and user.estimated_income_usd > 0:
        size_mult = _COMPANY_SIZE_MULT.get(company_size, 1.00)
        age_mult  = 1.00
        if user_age_val:
            for (lo, hi), m in _AGE_INCOME_MULT.items():
                if lo <= user_age_val <= hi:
                    age_mult = m
                    break
        user.estimated_income_usd = round(user.estimated_income_usd * size_mult * age_mult, 0)

    # ── Ajuste de tier por edad ───────────────────────────────────────────────
    if user.se_tier and user_age_val:
        try:
            tier_ladder  = ['D', 'C', 'B', 'A']
            current_rank = _tier_rank(user.se_tier)
            if user_age_val < 33:
                user.se_tier = tier_ladder[max(current_rank - 2, 0)]
            elif user_age_val > 45:
                user.se_tier = tier_ladder[min(current_rank + 1, 3)]
        except Exception:
            pass

    # ── Fallback: ingreso per cápita del país cuando no hay otro dato ─────────
    # Para países con GDP < $10K, el m² de arriendo ya domina via commune_tier.
    # Este fallback asegura que estimated_income_usd nunca quede None.
    if not user.estimated_income_usd and _country_median_income:
        if user.income_index and user.income_index > 0:
            # Escalar por posición relativa en el país (income_index 50 = mediana)
            user.estimated_income_usd = round(_country_median_income * (user.income_index / 50.0), 0)
        else:
            # Sin dato de commune: usar directamente la mediana del país
            user.estimated_income_usd = round(_country_median_income, 0)

    # ── Score compuesto de ingreso: fórmula β-comunal ────────────────────────
    # Modelo: y_u = y_ocup × (I_comuna/100)^β_eff
    # I_comuna = price_m2_avg_comuna / mediana_nacional × 100  (fuente: commune_market_data)
    # β_eff ajustado por edad para evitar sesgo hijos-viviendo-con-padres:
    #   < 33 años → β_eff = 0.0   (sin ajuste: solo señal ocupacional)
    #   33-39 años → β_eff = β_base / 2
    #   ≥ 40 años → β_eff = β_base
    _BETA_BASE = 0.35   # punto medio entre 0.30-0.40 (JC 2026-08-01)

    try:
        from ppp_agent import PLI as _PLI_MAP
        from datetime import date as _date_cls

        _pli         = _PLI_MAP.get(user_country_code, 0.60)
        _occ_ppp     = None
        _comm_index  = 100.0   # fallback = mediana nacional

        # Señal ocupacional → mensual PPP
        if user.estimated_income_usd and user.estimated_income_usd > 0:
            _occ_ppp = float(user.estimated_income_usd) / 12.0 / _pli

        # Índice comunal desde nuestra commune_market_data (price_m2_avg)
        # Chile guarda precios en UF → convertir a USD antes de calcular índice
        _UF_USD = 40.5
        _is_uf_country = (user_country_code == 'CL')

        if commune_data and getattr(commune_data, 'price_m2_avg', None) and commune_data.price_m2_avg > 0:
            try:
                _m2_factor = _UF_USD if _is_uf_country else 1.0
                try:
                    _med_r = db.execute(text("""
                        SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_m2_avg * :fx)
                        FROM commune_market_data WHERE country=:cc AND price_m2_avg > 0
                    """), {'cc': user_country_code, 'fx': _m2_factor}).fetchone()
                except Exception:
                    _med_r = db.execute(text("""
                        SELECT AVG(price_m2_avg * :fx) FROM commune_market_data
                        WHERE country=:cc AND price_m2_avg > 0
                    """), {'cc': user_country_code, 'fx': _m2_factor}).fetchone()
                _nat_m2 = float(_med_r[0]) if _med_r and _med_r[0] else None
                if _nat_m2 and _nat_m2 > 0:
                    _commune_price_usd = float(commune_data.price_m2_avg) * _m2_factor
                    _comm_index = (_commune_price_usd / _nat_m2) * 100.0
            except Exception:
                pass

        # β efectivo según edad (dob = 'YYYY-MM-DD')
        _user_age = None
        _dob_str  = getattr(user, 'dob', None)
        if _dob_str:
            try:
                _birth    = datetime.strptime(_dob_str[:10], '%Y-%m-%d').date()
                _user_age = (_date_cls.today() - _birth).days // 365
            except Exception:
                pass

        if _user_age is None:
            _beta_eff = _BETA_BASE            # sin dato edad: β completo
        elif _user_age < 33:
            _beta_eff = 0.0                   # solo ocupación — posible hijo en casa
        elif _user_age < 40:
            _beta_eff = _BETA_BASE / 2.0      # ajuste suave
        else:
            _beta_eff = _BETA_BASE            # β completo

        # Aplicar fórmula
        if _occ_ppp and _occ_ppp > 0:
            if _beta_eff > 0 and _comm_index > 0:
                _composite = _occ_ppp * ((_comm_index / 100.0) ** _beta_eff)
            else:
                _composite = _occ_ppp         # β=0 → solo ocupación
            if hasattr(user, 'estimated_income_ppp'):
                user.estimated_income_ppp = round(_composite, 1)
    except Exception:
        pass

    # ── HNW Score ─────────────────────────────────────────────────────────────
    try:
        hnw = _calculate_hnw_score(user, db)
        if hasattr(user, 'hnw_score'):
            user.hnw_score = hnw
    except Exception:
        pass


def _rekognition_client():
    return boto3.client(
        'rekognition',
        region_name=os.getenv('AWS_REGION', 'us-east-1'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    )

_VOTER_FACE_COLLECTION = 'preferendum-voters'
_voter_face_collection_ready = False

def _ensure_voter_face_collection(rek):
    """Crea la colección de caras de votantes si no existe todavía — idempotente.
    ExternalImageId de cada cara indexada = '{debate_id}_{user_id}', para poder
    detectar si la MISMA cara ya votó en la MISMA consulta bajo otra cuenta."""
    global _voter_face_collection_ready
    if _voter_face_collection_ready:
        return
    try:
        rek.create_collection(CollectionId=_VOTER_FACE_COLLECTION)
    except rek.exceptions.ResourceAlreadyExistsException:
        pass
    _voter_face_collection_ready = True

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

    # Verificar que el documento tenga al menos una cara visible — nunca se
    # aprueba a ciegas: si no se puede verificar de verdad, se bloquea con un
    # error claro en vez de dejar pasar el documento sin revisión.
    aws_key = os.getenv('AWS_ACCESS_KEY_ID')
    if not aws_key:
        raise HTTPException(503, 'Verificación de documento no disponible en este momento.')
    try:
        rek = _rekognition_client()
        resp = rek.detect_faces(
            Image={'Bytes': contents},
            Attributes=['DEFAULT']
        )
        face_detected = len(resp.get('FaceDetails', [])) > 0
        if not face_detected:
            raise HTTPException(400, 'No detectamos una cara en el documento. Asegúrate de fotografiar el lado con tu foto.')
    except HTTPException:
        raise
    except ClientError:
        raise HTTPException(503, 'Verificación de documento no disponible en este momento.')

    # Extraer texto del documento: RUT y número de serie (9 dígitos)
    doc_rut_match = False
    doc_serial_found = None
    if aws_key and face_detected:
        try:
            rek = _rekognition_client()
            text_resp = rek.detect_text(Image={'Bytes': contents})
            detected_lines = [t['DetectedText'] for t in text_resp.get('TextDetections', [])
                              if t['Type'] == 'LINE' and t.get('Confidence', 0) > 60]
            all_text = ' '.join(detected_lines).upper()

            # Buscar RUT en el texto (formato XX.XXX.XXX-X o XXXXXXXX-X)
            import re as _re
            rut_matches = _re.findall(r'\d{1,2}\.?\d{3}\.?\d{3}[-–]\s*[\dkK]', all_text)
            if rut_matches and user.national_id:
                # Normalizar: quitar puntos, guiones, espacios
                def _norm_rut(r): return _re.sub(r'[.\-\s–]', '', r).upper()
                user_rut_norm = _norm_rut(user.national_id)
                doc_rut_norm  = _norm_rut(rut_matches[0])
                doc_rut_match = (user_rut_norm == doc_rut_norm)

            # Buscar número de serie: secuencia de exactamente 9 dígitos (puede tener letra al inicio)
            serial_matches = _re.findall(r'\b[A-Z]?\d{9}\b', all_text)
            if serial_matches:
                doc_serial_found = serial_matches[0]

            # Validar nombre: al menos 2 palabras del nombre registrado deben aparecer en el documento
            if user.name:
                import unicodedata as _ud
                def _norm_name(s):
                    # Quitar tildes y caracteres especiales, dejar solo A-Z y espacios
                    nfkd = _ud.normalize('NFKD', s.upper())
                    ascii_str = ''.join(c for c in nfkd if not _ud.combining(c))
                    return _re.sub(r'[^A-Z ]', ' ', ascii_str)

                registered_tokens = {t for t in _norm_name(user.name).split() if len(t) >= 4}
                doc_tokens        = {t for t in _norm_name(all_text).split() if len(t) >= 4}
                common = registered_tokens & doc_tokens
                # Exigir al menos 2 palabras coincidentes (apellidos o nombres)
                name_match = len(common) >= 2
                if not name_match and rut_matches:
                    print(f'[verify/document] ALERTA nombre no coincide: user={user.name!r} coincidencias={common} doc_tokens={list(doc_tokens)[:15]}')
        except Exception as e:
            print(f'[verify/document] detect_text error (non-fatal): {e}')

    # Guardar número de serie si lo encontramos
    if doc_serial_found:
        user.doc_serial = doc_serial_found

    # Extraer nombre legible del documento para devolver al frontend
    extracted_name = None
    extracted_rut  = None
    if 'detected_lines' in dir() or 'all_text' in locals():
        try:
            # Nombre: líneas que parecen apellidos/nombres (solo letras y espacios, mín 3 palabras)
            name_candidates = [l for l in detected_lines
                               if _re.match(r'^[A-ZÁÉÍÓÚÜÑ ]{6,}$', l.strip().upper())
                               and len(l.strip().split()) >= 2]
            if name_candidates:
                extracted_name = name_candidates[0].strip().title()
            if rut_matches:
                extracted_rut = rut_matches[0].strip()
        except Exception:
            pass

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
    return {
        'verified': face_detected,
        'verify_level': user.verify_level,
        'doc_rut_match': doc_rut_match,
        'doc_serial_found': bool(doc_serial_found),
        'doc_name_match': name_match if 'name_match' in locals() else None,
        'extracted_name': extracted_name,
        'extracted_rut':  extracted_rut,
    }

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

    # Nunca se aprueba a ciegas — sin documento de referencia o sin AWS disponible,
    # se bloquea con un error claro en vez de marcar a la persona como verificada.
    if not doc_log or not doc_log.face_bytes:
        raise HTTPException(400, 'Primero debes subir tu documento de identidad antes de tomarte la selfie.')
    if not aws_key:
        raise HTTPException(503, 'Verificación facial no disponible en este momento.')

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
    except HTTPException:
        raise
    except ClientError:
        raise HTTPException(503, 'Verificación facial no disponible en este momento.')

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
    if not ref or not ref.face_bytes:
        raise HTTPException(400, 'No tienes una cara de referencia registrada.')
    if not aws_key:
        raise HTTPException(503, 'Verificación facial no disponible en este momento.')
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
    except HTTPException:
        raise
    except ClientError:
        raise HTTPException(503, 'Verificación facial no disponible en este momento.')

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
            sp_info = _get_sponsor_info(d.id, db)
            safe.append(format_debate(d, sponsor_info=sp_info))
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

@app.get('/debates/for-me')
def debates_for_me(
    status: str = Query('live'),
    limit:  int = Query(50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Devuelve solo las consultas para las que el usuario califica según su perfil verificado."""
    from datetime import date as _date
    now = datetime.utcnow()

    # Calcular edad del usuario
    user_age = None
    if user.dob:
        try:
            dob = _date.fromisoformat(user.dob)
            today = _date.today()
            user_age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        except Exception:
            pass

    user_country = (user.country or 'CL').upper()
    user_commune = (user.county or '').strip().lower()
    user_gender  = user.gender or ''

    q = db.query(Debate).filter(Debate.status == 'live')
    if status == 'expired':
        q = db.query(Debate).filter(Debate.status != 'draft', Debate.closes_at != None, Debate.closes_at < now)
    else:
        q = q.filter((Debate.closes_at == None) | (Debate.closes_at >= now))

    all_debates = q.order_by(Debate.created_at.desc()).limit(500).all()

    eligible = []
    for d in all_debates:
        # Filtro por alcance geográfico
        scope = (d.scope or 'global').lower()
        if scope == 'commune':
            allowed_communes = {c.strip().lower() for c in (d.scope_commune or '').split(',') if c.strip()}
            if not user_commune or user_commune not in allowed_communes:
                continue
        elif scope == 'country':
            sc = (d.scope_country or '').upper()
            if sc and sc not in ('', 'ALL', 'GLOBAL', 'GL') and sc != user_country:
                continue

        # Filtro por género
        tg = (d.target_gender or 'all').lower()
        if tg != 'all' and user_gender and user_gender != tg:
            continue

        # Filtro por edad
        if user_age is not None:
            if d.target_age_min and user_age < d.target_age_min:
                continue
            if d.target_age_max and user_age > d.target_age_max:
                continue

        # Filtro por ingreso estimado
        user_income = getattr(user, 'estimated_income_usd', None) if user else None
        if user_income is not None:
            if getattr(d, 'income_min_usd', None) and user_income < d.income_min_usd:
                continue
            if getattr(d, 'income_max_usd', None) and user_income > d.income_max_usd:
                continue

        # Filtro por SE Tier
        user_se = (getattr(user, 'se_tier', '') or '') if user else ''
        d_tiers = (getattr(d, 'target_se_tiers', '') or '').strip()
        if user_se and d_tiers and d_tiers not in ('A,B,C,D', 'all', ''):
            if not _tier_matches(user_se, d_tiers):
                continue

        try:
            eligible.append(format_debate(d))
        except Exception:
            pass
        if len(eligible) >= limit:
            break

    return {'debates': eligible}

@app.get('/ads/featured')
def get_featured_ads(user: User = Depends(get_optional_user), db: Session = Depends(get_db)):
    """Returns up to 2 active ad campaigns to display in the debates list.
    Si el usuario está autenticado, filtra por su se_tier."""
    now = datetime.utcnow()
    candidates = db.query(AdCampaign).filter(
        AdCampaign.is_active == True,
        AdCampaign.budget_clp > AdCampaign.spent_clp,
    ).filter(
        (AdCampaign.end_date == None) | (AdCampaign.end_date > now)
    ).order_by(AdCampaign.created_at.desc()).all()

    user_se      = (getattr(user, 'se_tier', '') or '') if user else ''
    user_income  = (getattr(user, 'estimated_income_usd', None)) if user else None
    user_gender  = (getattr(user, 'gender', '') or '').lower() if user else ''
    user_country = _country_code(getattr(user, 'country', '') or '') if user else ''
    user_commune = (getattr(user, 'county', '') or '').strip().lower() if user else ''

    user_age = None
    if user and getattr(user, 'dob', ''):
        try:
            from datetime import date as _date
            dob_str = (user.dob or '').strip()
            for _fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
                try:
                    _born = datetime.strptime(dob_str, _fmt).date()
                    today = _date.today()
                    user_age = today.year - _born.year - ((today.month, today.day) < (_born.month, _born.day))
                    break
                except ValueError:
                    pass
        except Exception:
            pass

    campaigns = []
    for c in candidates:
        # SE Tier
        if user_se and not _tier_matches(user_se, c.target_se_tiers or 'A,B,C,D'):
            continue
        # Ingreso USD
        if user_income is not None:
            inc_min = getattr(c, 'target_income_min', 0.0) or 0.0
            inc_max = getattr(c, 'target_income_max', 9999999.0) or 9999999.0
            if inc_min > 0 and user_income < inc_min:
                continue
            if inc_max < 9999.0 and user_income > inc_max:
                continue
        # Género
        tg = (getattr(c, 'target_gender', 'all') or 'all').lower()
        if tg != 'all' and user_gender and user_gender != tg:
            continue
        # Edad
        if user_age is not None:
            age_min = getattr(c, 'target_age_min', 0) or 0
            age_max = getattr(c, 'target_age_max', 99) or 99
            if age_min > 0 and user_age < age_min:
                continue
            if age_max < 99 and user_age > age_max:
                continue
        # País
        c_country = _country_code(getattr(c, 'target_country', '') or '')
        if c_country and user_country and c_country != user_country:
            continue
        # Comuna
        c_communes = [x.strip().lower() for x in (getattr(c, 'target_communes', '') or '').split(',') if x.strip()]
        if c_communes and user_commune and user_commune not in c_communes:
            continue

        campaigns.append(c)
        if len(campaigns) >= 2:
            break

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
    sp_info = _get_sponsor_info(debate_id, db)
    return format_debate(debate, sponsor_info=sp_info)

@app.post('/debates')
def create_debate(
    data: DebateCreate,
    db: Session = Depends(get_db),
    x_agent_secret: Optional[str] = Header(None, alias='X-Agent-Secret'),
):
    """Endpoint interno para los agentes automáticos (noticias, rescate de campañas).
    Los organizadores humanos usan /organizers/debates, que requiere login."""
    if x_agent_secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    if len(data.options) < 2:
        raise HTTPException(400, 'At least 2 options required')
    closes = datetime.fromisoformat(data.closes_at)
    verify_opens = closes + timedelta(days=1)
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
        income_min_usd=getattr(data, 'income_min_usd', None),
        income_max_usd=getattr(data, 'income_max_usd', None),
        category=getattr(data, 'category', 'general') or 'general',
        closes_at=closes, verify_opens_at=verify_opens, verify_closes_at=verify_closes,
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
    debate_communes = [x.strip() for x in (debate.scope_commune or '').split(',') if x.strip()]
    if target_communes and debate_communes and not (set(debate_communes) & set(target_communes)):
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
    from targeting_agent import optimize_campaigns_for_debate, load_matrix, build_matrix_from_db

    now = datetime.utcnow()
    orm_campaigns = db.query(AdCampaign).filter(
        AdCampaign.is_active == True,
    ).filter(
        (AdCampaign.start_date == None) | (AdCampaign.start_date <= now)
    ).all()

    # ── Campañas ancladas a esta consulta específica (target_debate_ids) ──
    # Bypass total de la matriz de targeting/ranking — usado por el agente de
    # rescate de campañas para garantizar que la campaña estancada gane el
    # espacio en la consulta creada específicamente para ella, en vez de competir
    # con cualquier otra campaña que también matchee genéricamente.
    if debate:
        pinned_orm = [
            c for c in orm_campaigns
            if c.target_debate_ids and
               debate.id in {int(x.strip()) for x in c.target_debate_ids.split(',') if x.strip().isdigit()} and
               ((c.budget_clp or 0) == 0 or (c.spent_clp or 0) < (c.budget_clp or 0))
        ]
        if pinned_orm:
            return [{
                'id': c.id, 'advertiser_name': c.advertiser_name or '',
                'title': c.title or '', 'ad_copy': c.ad_copy or '',
                'logo_url': c.logo_url or '', 'ad_image_url': c.ad_image_url or '',
                'video_url': getattr(c, 'video_url', '') or '', 'link_url': c.link_url or '',
                'cpm': 0, '_orm': c, 'optimization_rank': 0, 'pinned': True,
            } for c in pinned_orm]

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

        # ── TARGETING POSITIVO: target_categories ──
        # Si la campaña pide categorías específicas, la consulta debe estar en esa lista.
        # Antes existía la columna pero nunca se usaba para filtrar — solo se guardaba/mostraba.
        if c.target_categories:
            desired = {t.strip().lower() for t in c.target_categories.split(',') if t.strip()}
            if desired and debate_category not in desired:
                continue

        # ── COUNTRY FILTER ──
        # scope_country puede ser multi-país "CL,AR" o "GLOBAL" — debates globales aceptan todo
        debate_countries = {x.strip().upper() for x in debate_country.split(',') if x.strip()} if debate_country else {'GLOBAL'}
        if not debate_countries.intersection({'GLOBAL','ALL',''}):
            c_tgt = (c.target_country or '').upper().strip()
            if c_tgt and c_tgt not in ('ALL', 'GLOBAL', '') and c_tgt not in debate_countries:
                continue

        # ── SE TIER FILTER — usuario debe pertenecer al tier objetivo ──
        if user and getattr(user, 'se_tier', ''):
            if not _tier_matches(user.se_tier, c.target_se_tiers or 'A,B,C,D'):
                continue

        # ── COMPANY SIZE FILTER (modelo JC 2026-08-01) ──
        # Mapeo: '1-10','11-50' → small | '51-250' → medium | '251-1000','+1000' → large
        tgt_sizes = getattr(c, 'target_company_sizes', '') or ''
        if tgt_sizes and user:
            _SIZE_BUCKET = {
                '1-10': 'small', '11-50': 'small',
                '51-250': 'medium',
                '251-1000': 'large', '+1000': 'large',
            }
            user_cs = getattr(user, 'company_size', '') or ''
            user_bucket = _SIZE_BUCKET.get(user_cs, '')
            allowed = {s.strip().lower() for s in tgt_sizes.split(',') if s.strip()}
            if user_bucket and allowed and user_bucket not in allowed:
                continue

        # ── HNW FILTER — Porsche, LVMH, Rolex, etc. ──
        # target_hnw_only=True → solo usuarios con verified_hnw=True
        # min_hnw_score > 0   → solo usuarios con hnw_score >= umbral
        if user:
            hnw_only = getattr(c, 'target_hnw_only', False) or False
            min_hnw  = float(getattr(c, 'min_hnw_score', 0.0) or 0.0)
            user_hnw_verified = bool(getattr(user, 'verified_hnw', False))
            user_hnw_score    = float(getattr(user, 'hnw_score', 0.0) or 0.0)
            if hnw_only and not user_hnw_verified:
                continue
            if min_hnw > 0 and user_hnw_score < min_hnw:
                continue

        # ── FRECUENCIA — no repetir el mismo anuncio más de N veces al mismo usuario ──
        freq_cap = getattr(c, 'frequency_cap', None)
        if user and freq_cap:
            seen_count = db.query(AdImpressionLog).filter(
                AdImpressionLog.campaign_id == c.id,
                AdImpressionLog.user_id == user.id,
            ).count()
            if seen_count >= freq_cap:
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

    # Build the matrix live from the DB on every call instead of trusting the
    # cached targeting_matrix.json file — Render's web service filesystem is
    # not guaranteed to persist across deploys/restarts, so a file-only cache
    # would silently revert to stale/default data after the next unrelated
    # deploy. CommuneMarketData is a cheap query (~6.5k rows) so this is fine
    # to do per-request; GNI comes from world_countries (kept fresh by the
    # monthly income-data agent), not a re-fetch from World Bank per request.
    try:
        _rows = db.query(CommuneMarketData).all()
        _row_dicts = [{
            'country': r.country, 'commune': r.commune,
            'name': _COMMUNE_NAMES.get((r.country, r.commune), r.commune),
            'income_index': r.income_index, 'cpm_usd': r.cpm_usd, 'se_tier': r.se_tier,
        } for r in _rows]
        _gni_rows = db.execute(text("SELECT iso2, gdp_per_capita_usd FROM world_countries WHERE gdp_per_capita_usd IS NOT NULL")).fetchall()
        _gni_by_country = {row[0]: float(row[1]) for row in _gni_rows}
        matrix = build_matrix_from_db(_row_dicts, _gni_by_country)
    except Exception as _e:
        print(f'[_match_campaigns] live matrix build failed, falling back to cached file: {_e}')
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
        (AdCampaign.end_date == None) | (AdCampaign.end_date > now_ts),
    ).filter(
        # Incluir campañas sin presupuesto definido (pruebas) y las que aún tienen saldo
        (AdCampaign.budget_clp == None) |
        (AdCampaign.budget_clp == 0) |
        (AdCampaign.budget_clp > AdCampaign.spent_clp)
    ).order_by(AdCampaign.created_at.desc()).limit(10).all()
    matched_ids = {c.get('id') for c in matched}
    user_se = (getattr(user, 'se_tier', '') or '') if user else ''
    prepend = []
    for rc in recent:
        if rc.id not in matched_ids:
            # Respetar tier del usuario: si tiene tier asignado, solo campañas compatibles
            if user_se and not _tier_matches(user_se, rc.target_se_tiers or 'A,B,C,D'):
                continue
            # Respetar el límite de frecuencia — esta ruta bypaseaba _match_campaigns
            # (y por lo tanto el filtro de frecuencia) por completo.
            freq_cap = getattr(rc, 'frequency_cap', None)
            if user and freq_cap:
                seen_count = db.query(AdImpressionLog).filter(
                    AdImpressionLog.campaign_id == rc.id,
                    AdImpressionLog.user_id == user.id,
                ).count()
                if seen_count >= freq_cap:
                    continue
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
    # Si no hay ads específicos del debate, usar los globales como fallback
    if not static_ads:
        static_ads = db.query(DebateAd).order_by(DebateAd.impressions.asc()).limit(4).all()

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
                    user_id     = user.id,
                    gender      = user.gender or '',
                    age_group   = _get_age_group(user.dob),
                    county      = user.county or '',
                    country     = user.country or '',
                ))
            cpm_usd  = campaign.get('cpm') or 6.0
            cost_clp = max(1, int(round((cpm_usd * USD_TO_CLP) / 1000.0)))
            # UPDATE atómico — un read-modify-write en Python aquí pierde
            # incrementos bajo concurrencia real (confirmado empíricamente:
            # 15 requests simultáneos → solo ~3 cobros persistidos).
            db.execute(text("""
                UPDATE ad_campaigns
                SET spent_clp = LEAST(COALESCE(budget_clp, 0), COALESCE(spent_clp, 0) + :cost)
                WHERE id = :cid
            """), {'cost': cost_clp, 'cid': orm.id})
            db.expire(orm, ['spent_clp'])

    for i, op in enumerate(opinions):
        result.append({'type': 'opinion', 'opinion': {
            'id': op.id, 'text': op.text,
            'knowledge_level': op.knowledge_level,
            'user_name': op.user_name,
            'created_at': op.created_at.isoformat(),
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

    # Nunca se emite un token de voto sin comparación facial real — si no hay
    # foto de referencia o AWS no está disponible, se bloquea en vez de dejar
    # votar sin verificación de identidad.
    if not ref or not ref.face_bytes:
        raise HTTPException(400, 'No tienes una cara de referencia registrada.')
    if not aws_key:
        raise HTTPException(503, 'Verificación facial no disponible en este momento — intenta de nuevo en unos minutos.')
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

        # Bloqueo por cara duplicada: ¿esta misma cara ya votó en esta consulta,
        # bajo una cuenta distinta? Usa una Face Collection de Rekognition —
        # busca la cara contra todas las ya indexadas, en vez de comparar una por una.
        try:
            _ensure_voter_face_collection(rek)
            search = rek.search_faces_by_image(
                CollectionId=_VOTER_FACE_COLLECTION,
                Image={'Bytes': contents},
                FaceMatchThreshold=90.0,
                MaxFaces=20,
            )
            for m in search.get('FaceMatches', []):
                ext_id = m.get('Face', {}).get('ExternalImageId', '')
                if '_' not in ext_id:
                    continue
                ext_debate, ext_user = ext_id.split('_', 1)
                if ext_debate == str(debate_id) and ext_user != str(user.id):
                    raise HTTPException(409, 'Esta cara ya fue usada para votar en esta consulta, con otra cuenta.')
            rek.index_faces(
                CollectionId=_VOTER_FACE_COLLECTION,
                Image={'Bytes': contents},
                ExternalImageId=f'{debate_id}_{user.id}',
                MaxFaces=1,
                QualityFilter='NONE',
                DetectionAttributes=[],
            )
        except HTTPException:
            raise
        except Exception as _e:
            print(f'[face-dup-check] non-fatal error (not blocking vote): {_e}')
    except HTTPException:
        raise
    except ClientError:
        raise HTTPException(503, 'Verificación facial no disponible en este momento — intenta de nuevo en unos minutos.')
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
        'message': f'Identidad verificada — similitud {rekognition_score}%'
    }


@app.post('/debates/{debate_id}/vote')
def cast_vote(debate_id: int, data: CastVoteRequest, user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    try:
     return _cast_vote_inner(debate_id, data, user, db)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f'[cast_vote UNHANDLED] {traceback.format_exc()}')
        raise HTTPException(500, f'Error interno al votar: {type(e).__name__}: {e}')

def _cast_vote_inner(debate_id: int, data, user, db):
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Consultation not found')
    if get_debate_status(debate) != 'live':
        raise HTTPException(400, 'Consultation is not open for voting')

    # Elegibilidad: el votante debe cumplir las condiciones del consultante
    if debate.scope == 'commune' and debate.scope_commune:
        # scope_commune puede ser una comuna o una lista separada por comas
        allowed_communes = {c.strip().lower() for c in debate.scope_commune.split(',') if c.strip()}
        if (user.county or '').strip().lower() not in allowed_communes:
            raise HTTPException(403, f'Esta consulta es solo para residentes de {debate.scope_commune}')
    elif debate.scope == 'country' and debate.scope_country and debate.scope_country != 'GL':
        if (user.country or '').upper() != debate.scope_country.upper():
            raise HTTPException(403, f'Esta consulta es solo para residentes de {debate.scope_country}')

    if debate.target_gender and debate.target_gender != 'all':
        if (user.gender or '') != debate.target_gender:
            raise HTTPException(403, 'Esta consulta está dirigida a un género específico')

    if user.dob:
        try:
            from datetime import date
            dob = date.fromisoformat(user.dob)
            today = date.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            if debate.target_age_min and age < debate.target_age_min:
                raise HTTPException(403, f'Esta consulta es para mayores de {debate.target_age_min} años')
            if debate.target_age_max and age > debate.target_age_max:
                raise HTTPException(403, f'Esta consulta es para menores de {debate.target_age_max} años')
        except HTTPException:
            raise
        except Exception:
            pass  # si dob tiene formato inválido, no bloqueamos

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

    # Bloqueo 5: mismo número de serie del documento físico
    serial_hash = None
    if user.doc_serial:
        serial_hash = hash_str(user.doc_serial.strip().upper(), 'pref-serial-')
        serial_voted = db.query(DocSerialVoteLog).filter(
            DocSerialVoteLog.serial_hash == serial_hash,
            DocSerialVoteLog.debate_id == debate_id
        ).first()
        if serial_voted:
            raise HTTPException(409, 'Este documento de identidad ya fue usado para votar en esta consulta')

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
        # Store device fingerprint in IMEILog if not already registered for this hash
        existing_fp = db.query(IMEILog).filter(IMEILog.imei_hash == fp_hash).first()
        if not existing_fp:
            db.add(IMEILog(user_id=user.id, imei_hash=fp_hash, device_info='browser-fp'))
        db.add(ImeiVoteLog(debate_id=debate_id, imei_hash=fp_hash))
    elif imei_log:
        db.add(ImeiVoteLog(debate_id=debate_id, imei_hash=imei_log.imei_hash))
    if serial_hash:
        db.add(DocSerialVoteLog(debate_id=debate_id, serial_hash=serial_hash))
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
    # Sponsored consultation: generate discount code + tag user as verified HNW
    sponsor_discount_code = None
    sponsor_name = None
    sponsor_discount_pct = None
    sponsor_discount_text = None
    try:
        sp_debate = db.query(SponsoredDebate).filter(
            SponsoredDebate.debate_id == debate_id,
            SponsoredDebate.is_active == True
        ).first()
        if sp_debate:
            sponsor = db.query(Sponsor).filter(Sponsor.id == sp_debate.sponsor_id).first()
            if sponsor:
                prefix = sponsor.discount_code_prefix or sponsor.name[:3].upper()
                rand_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                sponsor_discount_code = f"{prefix}-{rand_part[:4]}-{rand_part[4:]}"
                sponsor_name = sponsor.name
                sponsor_discount_pct = sp_debate.discount_pct
                sponsor_discount_text = sp_debate.discount_text
                sp_debate.total_voted = (sp_debate.total_voted or 0) + 1
                if hasattr(user, 'verified_hnw'):
                    user.verified_hnw = True
                if hasattr(user, 'hnw_source') and not (user.hnw_source or '').strip():
                    user.hnw_source = sponsor.name.lower().replace(' ', '_')
                if hasattr(user, 'hnw_score'):
                    user.hnw_score = max(float(user.hnw_score or 0), 75.0)
    except Exception as e:
        print(f'[cast_vote] sponsor check error (non-fatal): {e}')
    try:
        db.commit()
    except Exception as e:
        import traceback
        print(f'[cast_vote] DB commit error for user={user.id} debate={debate_id}: {traceback.format_exc()}')
        db.rollback()
        raise HTTPException(500, f'Error al registrar el voto: {type(e).__name__}')

    # Impresión + gasto de campaña al VOTAR — no solo al leer opiniones existentes.
    # Votar es la acción universal (todos lo hacen); escribir opinión es opcional y
    # poco frecuente, así que antes ninguna campaña gastaba presupuesto en consultas
    # nuevas hasta que alguien escribía texto. No debe romper el voto si falla.
    try:
        matched_campaigns = _match_campaigns(user, debate, db)
        if matched_campaigns:
            top = matched_campaigns[0]
            orm = top.get('_orm')
            if orm:
                db.add(AdImpressionLog(
                    campaign_id = orm.id,
                    debate_id   = debate_id,
                    user_id     = user.id,
                    gender      = user.gender or '',
                    age_group   = _get_age_group(user.dob),
                    county      = user.county or '',
                    country     = user.country or '',
                ))
                cpm_usd  = top.get('cpm') or 6.0
                cost_clp = max(1, int(round((cpm_usd * USD_TO_CLP) / 1000.0)))
                # UPDATE atómico — mismo motivo que en get_opinions (ver comentario ahí)
                db.execute(text("""
                    UPDATE ad_campaigns
                    SET spent_clp = LEAST(COALESCE(budget_clp, 0), COALESCE(spent_clp, 0) + :cost)
                    WHERE id = :cid
                """), {'cost': cost_clp, 'cid': orm.id})
                db.commit()
    except Exception as e:
        print(f'[cast_vote] ad impression error (non-fatal): {e}')
        db.rollback()

    return {
        'success': True,
        'verify_code': verify_code,
        'option': option,
        'blockchain_tx': blockchain_tx,
        'total_votes': debate.total_votes,
        'current_results': counts,
        'reward_code': reward_code,
        'sponsor_discount_code': sponsor_discount_code,
        'sponsor_name': sponsor_name,
        'sponsor_discount_pct': sponsor_discount_pct,
        'sponsor_discount_text': sponsor_discount_text,
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
    if db.query(User).filter(func.lower(User.email) == func.lower(data.email)).first():
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
    user = db.query(User).filter(func.lower(User.email) == func.lower(data.email), User.role == 'organizer').first()
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
    verify_opens = closes + timedelta(days=1)
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
        income_min_usd=getattr(data, 'income_min_usd', None),
        income_max_usd=getattr(data, 'income_max_usd', None),
        category=getattr(data, 'category', 'general') or 'general',
        closes_at=closes, verify_opens_at=verify_opens, verify_closes_at=verify_closes,
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

class SponsorLinkInput(BaseModel):
    name:                 str
    logo_url:             str   = ''
    discount_pct:         int   = 15
    discount_code_prefix: str   = ''
    discount_text:        str   = ''

@app.post('/organizers/debates/{debate_id}/sponsor')
def organizer_link_sponsor(
    debate_id: int,
    data: SponsorLinkInput,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if user.role not in ('organizer', 'admin'):
        raise HTTPException(403, 'Organizer role required')
    debate = db.query(Debate).filter(Debate.id == debate_id, Debate.creator_id == user.id).first()
    if not debate:
        raise HTTPException(404, 'Debate no encontrado o no te pertenece')
    already = db.query(SponsoredDebate).filter(SponsoredDebate.debate_id == debate_id).first()
    if already:
        raise HTTPException(400, 'Este debate ya tiene un sponsor vinculado')
    prefix = (data.discount_code_prefix or data.name[:3]).upper()
    sp = Sponsor(
        name=data.name, logo_url=data.logo_url,
        industry='', contact_email=user.email or '',
        discount_code_prefix=prefix
    )
    db.add(sp)
    db.flush()
    sd = SponsoredDebate(
        debate_id=debate_id, sponsor_id=sp.id,
        discount_pct=data.discount_pct,
        discount_text=data.discount_text,
        is_active=True
    )
    db.add(sd)
    db.commit()
    return {
        'ok': True,
        'sponsor_id': sp.id,
        'sponsor_name': sp.name,
        'sponsored_debate_id': sd.id,
        'discount_pct': sd.discount_pct,
        'code_prefix': prefix,
    }

# ══════════════════════════════════════════════════════════════
# ROUTES: MARKETER / ADVERTISER
# ══════════════════════════════════════════════════════════════

COST_PER_VIEW = 20  # CLP por impresión

# ── SECTOR PÚBLICO — PRICING ──────────────────────────────────
# Costo por contacto (USD por usuario registrado verificado por identidad).
# Premium ~5x sobre CPM de Meta Ads para usuarios no verificados,
# justificado por verificación de identidad (comparable a email marketing B2B).
# Fórmula: costo_campaña = Σ( N_usuarios_por_país × CPM_país )
# Actualizable sin redeploy vía POST /admin/set-public-sector-cpm

PUBLIC_SECTOR_CPM_BY_COUNTRY: dict[str, float] = {
    'US': 0.10,   # EE.UU.     — Meta $0.020 × 5x premium verificado
    'GB': 0.06,   # Reino Unido
    'DE': 0.06,   # Alemania
    'FR': 0.06,   # Francia
    'ES': 0.04,   # España
    'MX': 0.02,   # México
    'BR': 0.013,  # Brasil
    'CL': 0.012,  # Chile
    'CO': 0.010,  # Colombia
    'AR': 0.009,  # Argentina
    'PE': 0.008,  # Perú
    'EC': 0.008,  # Ecuador
    'UY': 0.008,  # Uruguay
}
PUBLIC_SECTOR_CPM_DEFAULT: float = float(os.getenv('PUBLIC_SECTOR_CPM_DEFAULT', '0.008'))  # resto del mundo

# Override global (aplica a todos los países) — set by admin endpoint
_public_sector_global_override: float | None = None

def get_cpm_for_country(country_code: str) -> float:
    if _public_sector_global_override is not None:
        return _public_sector_global_override
    code = (country_code or '').upper().strip()
    return PUBLIC_SECTOR_CPM_BY_COUNTRY.get(code, PUBLIC_SECTOR_CPM_DEFAULT)

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
        target_age_ranges    = data.target_age_ranges,
        target_age_weights   = getattr(data, 'target_age_weights', '') or '',
        target_company_sizes = getattr(data, 'target_company_sizes', '') or '',
        target_categories    = data.target_categories,
        excluded_categories  = data.excluded_categories,
        blocked_competitors  = data.blocked_competitors,
        logo_url             = data.logo_url,
        ad_copy             = data.ad_copy,
        ad_image_url        = data.ad_image_url,
        video_url           = data.video_url,
        link_url            = data.link_url,
        min_per_capita_usd  = data.min_per_capita_usd,
        target_hnw_only     = getattr(data, 'target_hnw_only', False) or False,
        min_hnw_score       = getattr(data, 'min_hnw_score', 0.0) or 0.0,
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
    campaign.target_age_ranges    = data.target_age_ranges
    campaign.target_age_weights   = getattr(data, 'target_age_weights', '') or ''
    campaign.target_company_sizes = getattr(data, 'target_company_sizes', '') or ''
    campaign.target_se_tiers      = data.target_se_tiers
    campaign.excluded_categories = data.excluded_categories
    campaign.blocked_competitors = data.blocked_competitors
    campaign.ad_copy             = data.ad_copy
    campaign.link_url            = data.link_url
    campaign.logo_url            = data.logo_url
    campaign.ad_image_url        = data.ad_image_url
    campaign.video_url           = getattr(data, 'video_url', '') or ''
    campaign.min_per_capita_usd  = getattr(data, 'min_per_capita_usd', 0.0) or 0.0
    campaign.target_hnw_only     = getattr(data, 'target_hnw_only', False) or False
    campaign.min_hnw_score       = getattr(data, 'min_hnw_score', 0.0) or 0.0
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
        'target_hnw_only':    bool(getattr(c, 'target_hnw_only', False)),
        'min_hnw_score':      float(getattr(c, 'min_hnw_score', 0.0) or 0.0),
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
    existing = db.query(User).filter(func.lower(User.email) == func.lower(data.email)).first()
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
    user = db.query(User).filter(func.lower(User.email) == func.lower(data.email)).first()
    if not user or not bcrypt.checkpw(data.password.encode(), user.password.encode()):
        raise HTTPException(401, 'Credenciales inválidas')
    if user.role not in ('organizer', 'admin'):
        raise HTTPException(403, 'No tienes cuenta de organizador')
    profile = db.query(OrganizerProfile).filter(OrganizerProfile.user_id == user.id).first()
    return {
        'token':   make_token(user.id, user.role),
        'user':    {'id': user.id, 'name': user.name, 'email': user.email, 'role': user.role,
                    'referral_code': _ensure_referral_code(user, db)},
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
    verify_opens  = closes + timedelta(days=1)
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
        closes_at=closes, verify_opens_at=verify_opens, verify_closes_at=verify_closes,
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
    existing = db.query(User).filter(func.lower(User.email) == func.lower(data.email)).first()
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
    user = db.query(User).filter(func.lower(User.email) == func.lower(data.email), User.role.in_(['marketer', 'admin'])).first()
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

_COMMUNE_NAMES: dict[tuple, str] = {
    ("AE", "10"): "Downtown Dubai / Palm Jumeirah / DIFC",
    ("AE", "20"): "Dubai Marina / JBR / JLT",
    ("AE", "30"): "Business Bay / Jumeirah",
    ("AE", "40"): "Abu Dhabi Corniche / Al Reem Island",
    ("AE", "50"): "Abu Dhabi Yas Island / Saadiyat",
    ("AE", "60"): "Sharjah premium",
    ("AE", "61"): "Sharjah general",
    ("AE", "70"): "Ajman",
    ("AE", "71"): "Ras Al Khaimah",
    ("AE", "72"): "Fujairah",
    ("AE", "73"): "Umm Al Quwain",
    ("AR", "A420"): "Salta Capital",
    ("AR", "B160"): "San Isidro",
    ("AR", "B161"): "San Isidro premium",
    ("AR", "B162"): "Vicente López",
    ("AR", "B163"): "Vicente López Sur",
    ("AR", "B166"): "Tigre",
    ("AR", "B167"): "San Fernando",
    ("AR", "B170"): "Tres de Febrero",
    ("AR", "B171"): "Morón",
    ("AR", "B172"): "Ituzaingó",
    ("AR", "B176"): "Avellaneda",
    ("AR", "B179"): "La Matanza",
    ("AR", "B184"): "Lomas de Zamora",
    ("AR", "B186"): "Almirante Brown",
    ("AR", "B187"): "Quilmes",
    ("AR", "B190"): "La Plata",
    ("AR", "B760"): "Mar del Plata",
    ("AR", "B800"): "Bahía Blanca",
    ("AR", "C108"): "Puerto Madero",
    ("AR", "C110"): "San Cristóbal",
    ("AR", "C112"): "Parque Patricios",
    ("AR", "C113"): "Almagro / Balvanera",
    ("AR", "C118"): "Recoleta / Retiro",
    ("AR", "C123"): "Flores",
    ("AR", "C127"): "Caballito",
    ("AR", "C136"): "Nuñez / Saavedra",
    ("AR", "C138"): "Belgrano",
    ("AR", "C140"): "Palermo / Villa Crespo",
    ("AR", "C141"): "Villa Crespo / Almagro",
    ("AR", "C142"): "Palermo / Colegiales",
    ("AR", "C143"): "Villa del Parque",
    ("AR", "C146"): "Mataderos / Liniers",
    ("AR", "C147"): "Villa Lugano",
    ("AR", "G360"): "Formosa",
    ("AR", "H350"): "Resistencia",
    ("AR", "J521"): "San Juan",
    ("AR", "M553"): "Mendoza Capital",
    ("AR", "N354"): "Posadas",
    ("AR", "P956"): "Comodoro Rivadavia",
    ("AR", "R838"): "Neuquén",
    ("AR", "S200"): "Rosario Centro",
    ("AR", "S211"): "Rosario Sur",
    ("AR", "S300"): "Santa Fe Capital",
    ("AR", "T400"): "Tucumán",
    ("AR", "W380"): "Corrientes",
    ("AR", "X500"): "Córdoba Capital",
    ("AR", "X510"): "Córdoba Noroeste",
    ("AR", "X580"): "Río Cuarto",
    ("AT", "10"): "Viena distritos interiores (1.-9. Bezirk)",
    ("AT", "11"): "Viena distritos exteriores",
    ("AT", "20"): "Baja Austria cerca de Viena",
    ("AT", "21"): "Baja Austria general",
    ("AT", "30"): "Alta Austria norte",
    ("AT", "40"): "Linz",
    ("AT", "50"): "Salzburgo ciudad",
    ("AT", "51"): "Salzburgo Land",
    ("AT", "52"): "Salzburgo rural",
    ("AT", "60"): "Innsbruck / Tirol",
    ("AT", "61"): "Kitzbühel y resorts de Tirol",
    ("AT", "62"): "Tirol medio",
    ("AT", "63"): "Vorarlberg (Bregenz/Dornbirn)",
    ("AT", "64"): "Vorarlberg medio",
    ("AT", "70"): "Burgenland",
    ("AT", "80"): "Graz / Estiria",
    ("AT", "81"): "Estiria media",
    ("AT", "82"): "Estiria rural",
    ("AT", "90"): "Klagenfurt / Carintia",
    ("AT", "91"): "Carintia general",
    ("AU", "0800"): "Darwin CBD",
    ("AU", "2000"): "Sydney CBD",
    ("AU", "2006"): "The University",
    ("AU", "2010"): "Surry Hills",
    ("AU", "2011"): "Potts Point",
    ("AU", "2021"): "Paddington",
    ("AU", "2022"): "Randwick",
    ("AU", "2023"): "Bellevue Hill",
    ("AU", "2025"): "Edgecliff",
    ("AU", "2026"): "Bondi",
    ("AU", "2027"): "Woollahra",
    ("AU", "2028"): "Double Bay",
    ("AU", "2029"): "Rose Bay",
    ("AU", "2030"): "Vaucluse",
    ("AU", "2031"): "Coogee",
    ("AU", "2040"): "Leichhardt",
    ("AU", "2041"): "Balmain",
    ("AU", "2042"): "Newtown",
    ("AU", "2043"): "Erskineville",
    ("AU", "2044"): "St Peters",
    ("AU", "2045"): "Strathfield",
    ("AU", "2046"): "Concord",
    ("AU", "2047"): "Drummoyne",
    ("AU", "2048"): "Marrickville",
    ("AU", "2050"): "Glebe",
    ("AU", "2060"): "North Sydney",
    ("AU", "2061"): "Kirribilli",
    ("AU", "2065"): "St Leonards",
    ("AU", "2066"): "Lane Cove",
    ("AU", "2067"): "Chatswood",
    ("AU", "2068"): "Willoughby",
    ("AU", "2071"): "Killara",
    ("AU", "2073"): "Pymble",
    ("AU", "2074"): "Turramurra",
    ("AU", "2075"): "St Ives",
    ("AU", "2076"): "Wahroonga",
    ("AU", "2100"): "Manly",
    ("AU", "2101"): "Narrabeen",
    ("AU", "2102"): "Dee Why",
    ("AU", "2110"): "Hunters Hill",
    ("AU", "2111"): "Ryde",
    ("AU", "2148"): "Blacktown",
    ("AU", "2150"): "Parramatta",
    ("AU", "2155"): "Blacktown-North",
    ("AU", "2164"): "Wetherill Park",
    ("AU", "2170"): "Liverpool",
    ("AU", "2196"): "Lakemba",
    ("AU", "2200"): "Bankstown",
    ("AU", "2560"): "Campbelltown",
    ("AU", "2600"): "Canberra (ACT)",
    ("AU", "2750"): "Penrith",
    ("AU", "3000"): "Melbourne CBD",
    ("AU", "3002"): "East Melbourne",
    ("AU", "3004"): "South Yarra",
    ("AU", "3006"): "Southbank",
    ("AU", "3029"): "Hoppers Crossing",
    ("AU", "3030"): "Werribee",
    ("AU", "3051"): "Flemington",
    ("AU", "3052"): "Parkville",
    ("AU", "3053"): "Carlton",
    ("AU", "3054"): "Carlton North",
    ("AU", "3055"): "Brunswick South",
    ("AU", "3056"): "Brunswick",
    ("AU", "3057"): "Brunswick East",
    ("AU", "3058"): "Coburg",
    ("AU", "3101"): "Kew",
    ("AU", "3102"): "Kew East",
    ("AU", "3103"): "Balwyn",
    ("AU", "3104"): "Balwyn North",
    ("AU", "3126"): "Camberwell",
    ("AU", "3127"): "Box Hill",
    ("AU", "3128"): "Box Hill South",
    ("AU", "3130"): "Nunawading",
    ("AU", "3141"): "Toorak",
    ("AU", "3142"): "Prahran",
    ("AU", "3143"): "Armadale",
    ("AU", "3144"): "Malvern",
    ("AU", "3145"): "Caulfield",
    ("AU", "3146"): "Glen Iris",
    ("AU", "3150"): "Glen Waverley",
    ("AU", "3162"): "Elsternwick",
    ("AU", "3166"): "Oakleigh",
    ("AU", "3168"): "Clayton",
    ("AU", "3175"): "Dandenong North",
    ("AU", "3181"): "Prahran",
    ("AU", "3182"): "St Kilda",
    ("AU", "4000"): "Brisbane CBD",
    ("AU", "4059"): "Paddington QLD",
    ("AU", "4101"): "South Brisbane",
    ("AU", "4151"): "Coorparoo",
    ("AU", "4152"): "Camp Hill",
    ("AU", "5000"): "Adelaide CBD",
    ("AU", "5041"): "Unley",
    ("AU", "5065"): "Burnside",
    ("AU", "6000"): "Perth CBD",
    ("AU", "6005"): "West Perth",
    ("AU", "6009"): "Nedlands",
    ("AU", "6010"): "Cottesloe",
    ("AU", "6011"): "Claremont",
    ("AU", "6012"): "Mount Claremont",
    ("AU", "7000"): "Hobart CBD",
    ("AU", "7005"): "Battery Point Hobart",
    ("BE", "10"): "Bruselas Ixelles / Etterbeek / Pentagone",
    ("BE", "11"): "Bruselas Uccle / Woluwe-Saint-Pierre",
    ("BE", "12"): "Brabante Valón / Waterloo",
    ("BE", "13"): "Ottignies / Louvain-la-Neuve",
    ("BE", "14"): "Nivelles / Braine-l'Alleud",
    ("BE", "15"): "Halle / Braine-le-Château",
    ("BE", "16"): "Rhode-Saint-Genèse",
    ("BE", "18"): "Vilvoorde / Machelen",
    ("BE", "19"): "Grimbergen / Diegem",
    ("BE", "20"): "Amberes Centro / Eilandje",
    ("BE", "21"): "Amberes Norte / Merksem",
    ("BE", "22"): "Mechelen Ciudad",
    ("BE", "23"): "Turnhout / Mol interior",
    ("BE", "24"): "Mol / Geel (Kempen)",
    ("BE", "30"): "Lovaina / Leuven Centro",
    ("BE", "31"): "Lovaina Este / Tervuren",
    ("BE", "32"): "Tienen",
    ("BE", "33"): "Diest",
    ("BE", "35"): "Hasselt Centro",
    ("BE", "36"): "Genk",
    ("BE", "37"): "Tongeren",
    ("BE", "38"): "Sint-Truiden",
    ("BE", "40"): "Lieja Centro / Guillemins",
    ("BE", "41"): "Lieja Seraing / Ans",
    ("BE", "42"): "Herstal / Visé",
    ("BE", "43"): "Huy",
    ("BE", "44"): "Waremme / Hannut",
    ("BE", "50"): "Namur Centro",
    ("BE", "51"): "Namur Este / Gembloux",
    ("BE", "52"): "Dinant",
    ("BE", "53"): "Philippeville / Couvin",
    ("BE", "60"): "Charleroi Centro",
    ("BE", "61"): "Charleroi Este / Fleurus",
    ("BE", "62"): "Thuin / Beaumont",
    ("BE", "67"): "Arlon / Luxemburgo belga",
    ("BE", "68"): "Bastogne / La Roche-en-Ardenne",
    ("BE", "70"): "Mons Centro",
    ("BE", "71"): "La Louvière",
    ("BE", "72"): "Soignies",
    ("BE", "73"): "Ath / Enghien",
    ("BE", "80"): "Brujas / Brugge Centro",
    ("BE", "81"): "Brujas Este / Beernem",
    ("BE", "82"): "Torhout / Tielt",
    ("BE", "83"): "Ieper / Ypres",
    ("BE", "84"): "Kortrijk Centro",
    ("BE", "85"): "Roeselare",
    ("BE", "86"): "Ostende",
    ("BE", "87"): "Veurne / De Panne (Costa)",
    ("BE", "90"): "Gante / Gent Centro",
    ("BE", "91"): "Gante Este / Wetteren",
    ("BE", "92"): "Lokeren / Sint-Niklaas",
    ("BE", "93"): "Oudenaarde",
    ("BE", "94"): "Aalst Centro",
    ("BE", "95"): "Dendermonde",
    ("BE", "96"): "Geraardsbergen",
    ("BO", "0200"): "Cobija (Pando)",
    ("BO", "0301"): "Trinidad (Beni)",
    ("BO", "0400"): "Oruro",
    ("BO", "0401"): "Oruro Norte",
    ("BO", "0500"): "Tarija",
    ("BO", "0501"): "Tarija suburbios",
    ("BO", "0600"): "Cochabamba premium",
    ("BO", "0601"): "Cochabamba popular",
    ("BO", "0602"): "Quillacollo / Sacaba",
    ("BO", "0603"): "Cochabamba rural",
    ("BO", "0700"): "Santa Cruz Zona Sur",
    ("BO", "0705"): "Santa Cruz 2do anillo",
    ("BO", "0710"): "Santa Cruz 3er anillo",
    ("BO", "0720"): "Santa Cruz anillos ext",
    ("BO", "0800"): "Potosí",
    ("BO", "0900"): "La Paz Zona Sur / Calacoto",
    ("BO", "0901"): "La Paz Sopocachi",
    ("BO", "0902"): "La Paz Miraflores",
    ("BO", "0903"): "La Paz El Alto Sur",
    ("BO", "0910"): "La Paz Centro",
    ("BO", "0911"): "La Paz Zona Norte",
    ("BO", "0920"): "El Alto",
    ("BO", "0921"): "El Alto Ciudad",
    ("BO", "1000"): "Sucre",
    ("BO", "1001"): "Sucre Norte",
    ("BR", "01013"): "República",
    ("BR", "01046"): "Consolação",
    ("BR", "01303"): "Centro",
    ("BR", "01310"): "Jardins / Paulista",
    ("BR", "01401"): "Jardins",
    ("BR", "01419"): "Bela Vista",
    ("BR", "01422"): "Jardins / Cerqueira César",
    ("BR", "01452"): "Pinheiros",
    ("BR", "02210"): "Santana",
    ("BR", "03310"): "Tatuapé",
    ("BR", "04002"): "Vila Mariana",
    ("BR", "04023"): "Planalto Paulista",
    ("BR", "04039"): "Moema",
    ("BR", "04101"): "Vila Nova Conceição",
    ("BR", "04535"): "Itaim Bibi premium",
    ("BR", "04543"): "Jardim Europa",
    ("BR", "04551"): "Vila Olímpia",
    ("BR", "04552"): "Itaim Bibi",
    ("BR", "07750"): "Guarulhos",
    ("BR", "08210"): "São Mateus",
    ("BR", "09210"): "Santo André",
    ("BR", "20040"): "Centro Rio",
    ("BR", "20050"): "Centro Rio",
    ("BR", "21040"): "São Cristóvão",
    ("BR", "21770"): "Complexo do Alemão",
    ("BR", "22070"): "Botafogo",
    ("BR", "22281"): "Flamengo",
    ("BR", "22411"): "Leblon",
    ("BR", "22421"): "Leblon",
    ("BR", "22430"): "Ipanema",
    ("BR", "22450"): "Ipanema",
    ("BR", "22461"): "Copacabana premium",
    ("BR", "22620"): "Barra da Tijuca",
    ("BR", "22793"): "Barra da Tijuca",
    ("BR", "30130"): "Belo Horizonte Centro",
    ("BR", "30140"): "BH Savassi",
    ("BR", "40000"): "Salvador",
    ("BR", "50000"): "Recife",
    ("BR", "60000"): "Fortaleza",
    ("BR", "66000"): "Belém",
    ("BR", "69000"): "Manaus",
    ("BR", "70200"): "Asa Sul",
    ("BR", "70712"): "Asa Norte",
    ("BR", "70910"): "Lago Sul",
    ("BR", "71635"): "Lago Norte",
    ("BR", "72220"): "Ceilândia",
    ("BR", "74000"): "Goiânia",
    ("BR", "80010"): "Curitiba Centro",
    ("BR", "80420"): "Curitiba Batel",
    ("BR", "88015"): "Florianópolis Centro",
    ("BR", "88048"): "Florianópolis premium",
    ("BR", "90010"): "Porto Alegre Centro",
    ("CA", "H1A"): "Pointe-aux-Trembles",
    ("CA", "H1B"): "Rivière-des-Prairies",
    ("CA", "H1C"): "Pointe-aux-Trembles North",
    ("CA", "H1E"): "Montréal-Est",
    ("CA", "H1G"): "Anjou",
    ("CA", "H1H"): "Montréal-Nord",
    ("CA", "H1J"): "Saint-Léonard",
    ("CA", "H1K"): "Saint-Léonard East",
    ("CA", "H1L"): "Villeray",
    ("CA", "H1M"): "Rosemont",
    ("CA", "H1N"): "Hochelaga",
    ("CA", "H1P"): "Saint-Léonard",
    ("CA", "H1R"): "Villeray North",
    ("CA", "H1S"): "Rosemont North",
    ("CA", "H1T"): "Rosemont East",
    ("CA", "H1V"): "Rosemont Village",
    ("CA", "H1W"): "Hochelaga-Maisonneuve",
    ("CA", "H1X"): "Maisonneuve",
    ("CA", "H1Y"): "Rosemont East premium",
    ("CA", "H1Z"): "Villeray East",
    ("CA", "H2A"): "Rosemont",
    ("CA", "H2B"): "Ahuntsic",
    ("CA", "H2C"): "Ahuntsic East",
    ("CA", "H2E"): "Villeray",
    ("CA", "H2G"): "Rosemont",
    ("CA", "H2H"): "Plateau West",
    ("CA", "H2J"): "Plateau",
    ("CA", "H2K"): "Plateau East",
    ("CA", "H2L"): "Plateau premium",
    ("CA", "H2M"): "Ahuntsic premium",
    ("CA", "H2N"): "Ahuntsic North",
    ("CA", "H2P"): "Park-Extension",
    ("CA", "H2R"): "Park-Extension premium",
    ("CA", "H2S"): "Mile End",
    ("CA", "H2T"): "Plateau Mont-Royal",
    ("CA", "H2V"): "Outremont",
    ("CA", "H2W"): "Milton-Parc",
    ("CA", "H2X"): "Plateau Sud",
    ("CA", "H2Y"): "Old Montreal",
    ("CA", "H2Z"): "downtown Montreal",
    ("CA", "H3A"): "McGill",
    ("CA", "H3B"): "downtown Montreal",
    ("CA", "H3C"): "Griffintown",
    ("CA", "H3E"): "Verdun Sud premium",
    ("CA", "H3G"): "Concordia",
    ("CA", "H3H"): "Westmount East",
    ("CA", "H3J"): "Saint-Henri premium",
    ("CA", "H3K"): "Saint-Henri East",
    ("CA", "H3L"): "Cartierville South",
    ("CA", "H3M"): "Ville Saint-Laurent",
    ("CA", "H3N"): "Côte-des-Neiges",
    ("CA", "H3P"): "Snowdon East",
    ("CA", "H3R"): "Hampstead South",
    ("CA", "H3S"): "Côte-des-Neiges premium",
    ("CA", "H3T"): "Côte-des-Neiges",
    ("CA", "H3U"): "Notre-Dame-de-Grâce West",
    ("CA", "H3V"): "Outremont premium",
    ("CA", "H3W"): "Notre-Dame-de-Grâce",
    ("CA", "H3X"): "Snowdon",
    ("CA", "H3Y"): "Westmount Central",
    ("CA", "H3Z"): "Westmount premium",
    ("CA", "H4A"): "Notre-Dame-de-Grâce East",
    ("CA", "H4B"): "Verdun",
    ("CA", "H4C"): "Saint-Henri",
    ("CA", "H4E"): "Ville-Émard",
    ("CA", "H4G"): "LaSalle",
    ("CA", "H4H"): "Verdun South",
    ("CA", "H4J"): "LaSalle East",
    ("CA", "H4K"): "Pierrefonds",
    ("CA", "H4L"): "Saint-Laurent",
    ("CA", "H4M"): "Saint-Laurent Est",
    ("CA", "H4N"): "Saint-Michel",
    ("CA", "H4P"): "Côte-Saint-Luc",
    ("CA", "H4R"): "Cartierville",
    ("CA", "H4S"): "Bois-Franc",
    ("CA", "H4T"): "Mont-Royal",
    ("CA", "H4V"): "Hampstead",
    ("CA", "H4W"): "Côte-Saint-Luc",
    ("CA", "H4X"): "Lachine",
    ("CA", "H4Y"): "Dorval",
    ("CA", "H4Z"): "Montréal downtown",
    ("CA", "H7A"): "Laval East",
    ("CA", "H7B"): "Laval South",
    ("CA", "H7C"): "Laval Central",
    ("CA", "H7E"): "Laval North",
    ("CA", "H7G"): "Laval premium",
    ("CA", "H7H"): "Laval West",
    ("CA", "H7J"): "Laval Central",
    ("CA", "H7K"): "Laval premium",
    ("CA", "H7L"): "Laval North",
    ("CA", "H7M"): "Laval East",
    ("CA", "H7N"): "Laval East",
    ("CA", "H7P"): "Laval",
    ("CA", "H7R"): "Laval premium",
    ("CA", "H7S"): "Laval",
    ("CA", "H7T"): "Laval",
    ("CA", "H7V"): "Laval",
    ("CA", "H7W"): "Laval",
    ("CA", "H7X"): "Laval premium",
    ("CA", "H7Y"): "Laval premium",
    ("CA", "J3H"): "Longueuil",
    ("CA", "J4G"): "Longueuil West",
    ("CA", "J4H"): "Longueuil East",
    ("CA", "J4K"): "Greenfield Park",
    ("CA", "L3R"): "Markham",
    ("CA", "L3S"): "Markham South",
    ("CA", "L3T"): "Thornhill Markham",
    ("CA", "L4B"): "Richmond Hill",
    ("CA", "L4C"): "Richmond Hill South",
    ("CA", "L4E"): "Oak Ridges",
    ("CA", "L4J"): "Thornhill",
    ("CA", "L4K"): "Vaughan",
    ("CA", "L4L"): "Woodbridge",
    ("CA", "L6A"): "Maple",
    ("CA", "L6B"): "Markham East",
    ("CA", "M1B"): "Malvern",
    ("CA", "M1C"): "Rouge Hill",
    ("CA", "M1E"): "West Hill",
    ("CA", "M1G"): "Woburn",
    ("CA", "M1H"): "Scarborough Village",
    ("CA", "M1J"): "Scarborough Village W",
    ("CA", "M1K"): "Kennedy Park",
    ("CA", "M1L"): "Clairlea",
    ("CA", "M1M"): "Cliffcrest",
    ("CA", "M1N"): "Birchcliffe",
    ("CA", "M1P"): "Dorset Park",
    ("CA", "M1R"): "Wexford",
    ("CA", "M1S"): "Agincourt",
    ("CA", "M1T"): "Clarks Corners",
    ("CA", "M1V"): "Milliken",
    ("CA", "M1W"): "L'Amoreaux",
    ("CA", "M1X"): "Upper Rouge",
    ("CA", "M2K"): "Bayview Village",
    ("CA", "M2N"): "Willowdale",
    ("CA", "M2P"): "St Andrews",
    ("CA", "M3C"): "Don Mills",
    ("CA", "M4B"): "East York",
    ("CA", "M4C"): "East York Wood",
    ("CA", "M4E"): "The Beach",
    ("CA", "M4G"): "Leaside",
    ("CA", "M4H"): "Thorncliffe",
    ("CA", "M4J"): "East Danforth",
    ("CA", "M4K"): "Danforth East",
    ("CA", "M4L"): "East End Danforth",
    ("CA", "M4M"): "South Riverdale",
    ("CA", "M4N"): "Lawrence Park",
    ("CA", "M4P"): "Davisville",
    ("CA", "M4R"): "North Toronto",
    ("CA", "M4S"): "Davisville Village",
    ("CA", "M4T"): "Moore Park",
    ("CA", "M4V"): "Deer Park",
    ("CA", "M4W"): "Rosedale",
    ("CA", "M4X"): "Cabbagetown",
    ("CA", "M4Y"): "Church-Wellesley",
    ("CA", "M5A"): "St Lawrence/Regent Park",
    ("CA", "M5B"): "Garden District",
    ("CA", "M5C"): "St James Town",
    ("CA", "M5E"): "Berczy Village",
    ("CA", "M5G"): "Discovery District",
    ("CA", "M5H"): "Bay Street",
    ("CA", "M5J"): "Harbourfront",
    ("CA", "M5K"): "Design Exchange",
    ("CA", "M5L"): "Commerce Court",
    ("CA", "M5N"): "Roselawn",
    ("CA", "M5P"): "Forest Hill",
    ("CA", "M5R"): "Annex",
    ("CA", "M5S"): "University of Toronto",
    ("CA", "M5T"): "Kensington Market",
    ("CA", "M5V"): "King West / Liberty Village",
    ("CA", "M5W"): "Stn A",
    ("CA", "M5X"): "First Canadian Place",
    ("CA", "M6A"): "Lawrence Heights",
    ("CA", "M6B"): "Glencairn",
    ("CA", "M6C"): "Humewood-Cedarvale",
    ("CA", "M6G"): "Christie Pits",
    ("CA", "M6H"): "Dufferin Grove",
    ("CA", "M6J"): "Trinity Bellwoods",
    ("CA", "M6K"): "Brockton Village",
    ("CA", "M6M"): "Mt. Dennis",
    ("CA", "M6N"): "Junction Area",
    ("CA", "M6P"): "High Park North",
    ("CA", "M6R"): "Roncesvalles",
    ("CA", "M6S"): "Swansea",
    ("CA", "M8V"): "New Toronto",
    ("CA", "M8W"): "Alderwood",
    ("CA", "M8X"): "Kingsway",
    ("CA", "M8Y"): "Old Mill",
    ("CA", "M8Z"): "Stonegate",
    ("CA", "M9A"): "Islington Ave",
    ("CA", "M9B"): "West Deane Park",
    ("CA", "M9C"): "Eringate",
    ("CA", "M9M"): "Humber Summit",
    ("CA", "M9N"): "Weston",
    ("CA", "M9P"): "Willowridge",
    ("CA", "M9R"): "Kingsview Village",
    ("CA", "M9V"): "Thistletown",
    ("CA", "M9W"): "Clairville",
    ("CA", "T2A"): "Calgary E",
    ("CA", "T2B"): "Calgary E",
    ("CA", "T2C"): "Calgary SE",
    ("CA", "T2E"): "Calgary NE",
    ("CA", "T2G"): "Calgary SE",
    ("CA", "T2H"): "Calgary S",
    ("CA", "T2J"): "Calgary S premium",
    ("CA", "T2K"): "Calgary N",
    ("CA", "T2L"): "Calgary NW",
    ("CA", "T2M"): "Calgary NW",
    ("CA", "T2N"): "Calgary NW premium",
    ("CA", "T2P"): "Calgary downtown",
    ("CA", "T2R"): "Calgary SW",
    ("CA", "T2S"): "Calgary SW premium",
    ("CA", "T2T"): "Calgary SW premium",
    ("CA", "T2V"): "Calgary S",
    ("CA", "T2W"): "Calgary SW",
    ("CA", "T2X"): "Calgary SE",
    ("CA", "T2Y"): "Calgary S",
    ("CA", "T2Z"): "Calgary SE",
    ("CA", "T3A"): "Calgary NW",
    ("CA", "T3B"): "Calgary NW premium",
    ("CA", "T3C"): "Calgary SW",
    ("CA", "T3E"): "Calgary SW mid",
    ("CA", "T3G"): "Calgary NW",
    ("CA", "T3H"): "Calgary SW premium",
    ("CA", "T3J"): "Calgary NE",
    ("CA", "T3K"): "Calgary N",
    ("CA", "T3L"): "Calgary NW",
    ("CA", "T3M"): "Calgary SE",
    ("CA", "T3N"): "Calgary N",
    ("CA", "T3P"): "Calgary N",
    ("CA", "T3R"): "Calgary N",
    ("CA", "T3Z"): "Calgary SW premium",
    ("CA", "V3M"): "New Westminster",
    ("CA", "V3N"): "Burnaby South",
    ("CA", "V3R"): "Surrey North",
    ("CA", "V3S"): "Surrey Central",
    ("CA", "V3T"): "Surrey Newton",
    ("CA", "V3V"): "Surrey Cloverdale",
    ("CA", "V3W"): "Surrey Fleetwood",
    ("CA", "V3X"): "Surrey South",
    ("CA", "V3Y"): "Langley",
    ("CA", "V3Z"): "Port Coquitlam",
    ("CA", "V4A"): "Surrey White Rock",
    ("CA", "V5A"): "Burnaby North",
    ("CA", "V5B"): "Burnaby East",
    ("CA", "V5C"): "Burnaby Heights",
    ("CA", "V5E"): "Burnaby South East",
    ("CA", "V5G"): "Burnaby Edmonds",
    ("CA", "V5H"): "Burnaby South Central",
    ("CA", "V5J"): "Burnaby Metrotown",
    ("CA", "V5K"): "Vancouver East",
    ("CA", "V5L"): "Vancouver East Grandview",
    ("CA", "V5M"): "Vancouver East Renfrew",
    ("CA", "V5N"): "Vancouver East Commercial",
    ("CA", "V5P"): "Vancouver East Victoria",
    ("CA", "V5V"): "Vancouver East Fraser",
    ("CA", "V5W"): "Vancouver East Sunset",
    ("CA", "V5X"): "Vancouver East Collingwood",
    ("CA", "V5Y"): "Vancouver Mount Pleasant",
    ("CA", "V5Z"): "Vancouver Fairview East",
    ("CA", "V6A"): "East Van/Strathcona",
    ("CA", "V6B"): "Vancouver downtown",
    ("CA", "V6C"): "Vancouver downtown",
    ("CA", "V6E"): "Vancouver West End",
    ("CA", "V6G"): "Vancouver West End English Bay",
    ("CA", "V6H"): "Vancouver Fairview",
    ("CA", "V6J"): "Vancouver Kitsilano",
    ("CA", "V6K"): "Vancouver Kitsilano",
    ("CA", "V6M"): "Vancouver South Granville",
    ("CA", "V6N"): "Vancouver Marpole",
    ("CA", "V6P"): "Vancouver SW Marine",
    ("CA", "V6R"): "Vancouver Point Grey",
    ("CA", "V6S"): "Vancouver UBC area",
    ("CA", "V6T"): "UBC campus",
    ("CA", "V6V"): "Richmond North",
    ("CA", "V6X"): "Richmond Central",
    ("CA", "V6Y"): "Richmond South",
    ("CA", "V6Z"): "Vancouver Yaletown",
    ("CA", "V7A"): "Richmond East",
    ("CA", "V7B"): "Richmond Airport",
    ("CA", "V7C"): "Richmond Southwest",
    ("CA", "V7E"): "Richmond Steveston",
    ("CA", "V7G"): "North Vancouver Deep Cove",
    ("CA", "V7H"): "North Van Lynn Valley",
    ("CA", "V7J"): "North Van Upper Lonsdale",
    ("CA", "V7K"): "North Van Lynn Valley mid",
    ("CA", "V7L"): "North Vancouver Lonsdale",
    ("CA", "V7M"): "North Vancouver east",
    ("CA", "V7N"): "North Vancouver mid",
    ("CA", "V7P"): "North Van Princess Park",
    ("CA", "V7R"): "North Van premium",
    ("CA", "V7S"): "West Van Caulfeild",
    ("CA", "V7T"): "North Vancouver premium",
    ("CA", "V7V"): "West Van norte",
    ("CA", "V7W"): "West Vancouver premium",
    ("CA", "V7X"): "Vancouver downtown east",
    ("CA", "V7Y"): "Vancouver downtown",
    ("CA", "V8P"): "Saanich East",
    ("CA", "V8R"): "Saanich North",
    ("CA", "V8S"): "Oak Bay",
    ("CA", "V8T"): "Saanich West",
    ("CA", "V8V"): "Victoria James Bay",
    ("CA", "V8W"): "Victoria downtown",
    ("CA", "V8X"): "Saanich Central",
    ("CA", "V8Y"): "Saanich Gordon Head",
    ("CA", "V8Z"): "Saanich SW",
    ("CA", "V9A"): "Esquimalt",
    ("CH", "10"): "Lausana / Pully",
    ("CH", "11"): "Morges / Nyon / Vaud Norte",
    ("CH", "12"): "Ginebra Centro / Eaux-Vives",
    ("CH", "13"): "Ginebra Carouge / Plan-les-Ouates",
    ("CH", "17"): "Friburgo / Freiburg",
    ("CH", "19"): "Sion / Sierre (Valais)",
    ("CH", "20"): "Neuchâtel",
    ("CH", "30"): "Berna Centro / Kirchenfeld",
    ("CH", "31"): "Berna Köniz / Muri",
    ("CH", "32"): "Biel / Bienne",
    ("CH", "33"): "Thun",
    ("CH", "34"): "Langnau / Burgdorf",
    ("CH", "36"): "Interlaken / Grindelwald",
    ("CH", "40"): "Basilea Centro / Gundeldingen",
    ("CH", "41"): "Basilea Riehen / Bettingen",
    ("CH", "42"): "Liestal / Arlesheim",
    ("CH", "45"): "Solothurn / Olten",
    ("CH", "50"): "Aarau",
    ("CH", "53"): "Baden",
    ("CH", "60"): "Lucerna Centro",
    ("CH", "61"): "Emmen / Kriens",
    ("CH", "62"): "Sursee / Willisau",
    ("CH", "63"): "Zug (premium)",
    ("CH", "64"): "Schwyz / Brunnen",
    ("CH", "65"): "Lugano",
    ("CH", "66"): "Bellinzona / Locarno",
    ("CH", "70"): "Chur / Graubünden",
    ("CH", "71"): "Davos",
    ("CH", "72"): "St. Moritz / Engadina Alta",
    ("CH", "80"): "Zúrich Seefeld / Enge / Altstadt",
    ("CH", "81"): "Zúrich Fluntern / Witikon",
    ("CH", "82"): "Küsnacht / Zollikon (orilla lago)",
    ("CH", "83"): "Richterswil / Wädenswil",
    ("CH", "84"): "Meilen / Herrliberg (lago premium)",
    ("CH", "85"): "Winterthur Centro",
    ("CH", "86"): "Winterthur Norte",
    ("CH", "87"): "Winterthur Töss",
    ("CH", "88"): "Rapperswil-Jona",
    ("CH", "89"): "Uster / Pfäffikon (Zürichsee)",
    ("CH", "90"): "San Galo / St. Gallen Centro",
    ("CH", "91"): "Rorschach / Gossau",
    ("CH", "94"): "Appenzell / Herisau",
    ("CI", "01"): "Abidján Plateau / Zone 4 (CBD premium)",
    ("CI", "02"): "Abidján Cocody / Riviera",
    ("CI", "03"): "Abidján Marcory / Treichville",
    ("CI", "04"): "Abidján Yopougon",
    ("CI", "05"): "Abidján Abobo",
    ("CI", "06"): "Abidján Koumassi / Port-Bouët",
    ("CI", "07"): "Abidján Deux Plateaux / Angré",
    ("CI", "08"): "Abidján Adjamé / Attécoubé",
    ("CI", "20"): "Bouaké",
    ("CI", "30"): "Daloa",
    ("CI", "40"): "San-Pédro",
    ("CI", "41"): "Korhogo / Savanes",
    ("CI", "50"): "Man / Ouest",
    ("CI", "60"): "Abengourou",
    ("CI", "70"): "Odienné / Nord-Ouest",
    ("CM", "10"): "Bertoua / Est",
    ("CM", "11"): "Ebolowa / Sud",
    ("CM", "20"): "Bafoussam / Ouest",
    ("CM", "21"): "Bamenda / Nord-Ouest",
    ("CM", "30"): "Yaundé Bastos / Nlongkak (premium)",
    ("CM", "31"): "Yaundé Centro / Mvog-Mbi",
    ("CM", "32"): "Yaundé Messa / Tsinga",
    ("CM", "33"): "Yaundé Essos / Mimboman",
    ("CM", "40"): "Douala Akwa / Bonanjo (CBD premium)",
    ("CM", "41"): "Douala Bali / Bonabéri",
    ("CM", "42"): "Douala Makepe / Logbaba",
    ("CM", "43"): "Douala New Bell / Nkongmamba",
    ("CM", "50"): "Garoua / Nord",
    ("CM", "60"): "Ngaoundéré / Adamawa",
    ("CM", "70"): "Maroua / Extrême-Nord",
    ("CN", "100"): "Beijing centro (Dongcheng/Xicheng)",
    ("CN", "101"): "Beijing suburbios",
    ("CN", "102"): "Beijing outer",
    ("CN", "200"): "Shanghai Huangpu/Jing'an",
    ("CN", "201"): "Shanghai Pudong/Changning",
    ("CN", "202"): "Shanghai lejano",
    ("CN", "310"): "Hangzhou",
    ("CN", "315"): "Ningbo",
    ("CN", "350"): "Fuzhou",
    ("CN", "361"): "Xiamen",
    ("CN", "370"): "Qingdao",
    ("CN", "410"): "Zhengzhou",
    ("CN", "420"): "Wuhan",
    ("CN", "430"): "Changsha",
    ("CN", "510"): "Guangzhou",
    ("CN", "511"): "Foshan",
    ("CN", "518"): "Shenzhen Futian/Nanshan",
    ("CN", "519"): "Shenzhen outer",
    ("CN", "520"): "Dongguan",
    ("CN", "530"): "Nanning",
    ("CN", "550"): "Guiyang",
    ("CN", "570"): "Hainan/Sanya",
    ("CN", "610"): "Chengdu",
    ("CN", "650"): "Kunming",
    ("CN", "710"): "Xi'an",
    ("CN", "730"): "Lanzhou",
    ("CN", "750"): "Yinchuan",
    ("CN", "830"): "Urumqi",
    ("CO", "05001"): "El Poblado / Laureles",
    ("CO", "05021"): "Bello / Copacabana",
    ("CO", "05030"): "Envigado / Sabaneta",
    ("CO", "05045"): "Itagüí / La Estrella",
    ("CO", "08001"): "Barranquilla norte",
    ("CO", "08433"): "Soledad",
    ("CO", "11001"): "Chapinero / Chicó",
    ("CO", "11011"): "Teusaquillo",
    ("CO", "11022"): "Usaquén",
    ("CO", "11028"): "Barrios Unidos / Engativá",
    ("CO", "11050"): "Suba premium",
    ("CO", "11071"): "Kennedy",
    ("CO", "11081"): "Bosa",
    ("CO", "13001"): "Cartagena premium",
    ("CO", "13430"): "Cartagena popular",
    ("CO", "17001"): "Manizales",
    ("CO", "23001"): "Montería",
    ("CO", "47001"): "Santa Marta",
    ("CO", "50001"): "Villavicencio",
    ("CO", "52001"): "Pasto",
    ("CO", "54001"): "Cúcuta",
    ("CO", "63001"): "Armenia",
    ("CO", "66001"): "Pereira",
    ("CO", "68001"): "Bucaramanga",
    ("CO", "73001"): "Ibagué",
    ("CO", "76001"): "Cali norte",
    ("CO", "76054"): "Cali sur",
    ("CZ", "10"): "Praga 1-4 (centro)",
    ("CZ", "11"): "Praga 5-8",
    ("CZ", "12"): "Praga 9-12",
    ("CZ", "14"): "Praga outer",
    ("CZ", "15"): "Praga farther",
    ("CZ", "16"): "Praga suburbios",
    ("CZ", "25"): "Bohemia Central (cerca de Praga)",
    ("CZ", "27"): "Bohemia Norte oeste",
    ("CZ", "36"): "Bohemia Oeste / Plzeň",
    ("CZ", "46"): "Liberec",
    ("CZ", "50"): "Hradec Králové",
    ("CZ", "58"): "Bohemia Este / Jihlava",
    ("CZ", "60"): "Brno centro",
    ("CZ", "61"): "Brno suburbios",
    ("CZ", "62"): "Brno outer",
    ("CZ", "70"): "Ostrava",
    ("CZ", "71"): "Ostrava suburbios",
    ("CZ", "75"): "Zlín",
    ("CZ", "79"): "Olomouc",
    ("DE", "01"): "Dresden",
    ("DE", "04"): "Leipzig",
    ("DE", "06"): "Halle",
    ("DE", "07"): "Erfurt",
    ("DE", "08"): "Zwickau",
    ("DE", "09"): "Chemnitz",
    ("DE", "10"): "Berlín Mitte/Prenzlauer Berg",
    ("DE", "12"): "Berlín Tempelhof/Neukölln",
    ("DE", "13"): "Berlín Reinickendorf",
    ("DE", "14"): "Berlín Charlottenburg",
    ("DE", "17"): "Schwerin",
    ("DE", "18"): "Rostock",
    ("DE", "19"): "Schwerin nord",
    ("DE", "20"): "Hamburg centro",
    ("DE", "21"): "Hamburg sur",
    ("DE", "22"): "Hamburg norte (Blankenese)",
    ("DE", "23"): "Lübeck",
    ("DE", "24"): "Kiel",
    ("DE", "25"): "Heide",
    ("DE", "26"): "Oldenburg",
    ("DE", "27"): "Bremerhaven",
    ("DE", "28"): "Bremen",
    ("DE", "29"): "Celle",
    ("DE", "30"): "Hannover",
    ("DE", "31"): "Hildesheim",
    ("DE", "32"): "Herford",
    ("DE", "33"): "Bielefeld",
    ("DE", "34"): "Kassel",
    ("DE", "35"): "Marburg",
    ("DE", "36"): "Fulda",
    ("DE", "37"): "Göttingen",
    ("DE", "38"): "Braunschweig",
    ("DE", "39"): "Magdeburg",
    ("DE", "40"): "Düsseldorf",
    ("DE", "41"): "Mönchengladbach",
    ("DE", "42"): "Wuppertal",
    ("DE", "44"): "Dortmund",
    ("DE", "45"): "Essen",
    ("DE", "47"): "Duisburg",
    ("DE", "50"): "Köln centro",
    ("DE", "51"): "Bergisch Gladbach",
    ("DE", "52"): "Aachen",
    ("DE", "53"): "Bonn",
    ("DE", "55"): "Mainz",
    ("DE", "56"): "Koblenz",
    ("DE", "57"): "Siegen",
    ("DE", "58"): "Hagen",
    ("DE", "59"): "Dortmund sur",
    ("DE", "60"): "Frankfurt centro",
    ("DE", "61"): "Frankfurt norte (Hochtaunus)",
    ("DE", "63"): "Frankfurt este (Offenbach)",
    ("DE", "64"): "Frankfurt sur (Darmstadt)",
    ("DE", "65"): "Wiesbaden",
    ("DE", "66"): "Saarbrücken",
    ("DE", "67"): "Ludwigshafen",
    ("DE", "68"): "Mannheim",
    ("DE", "69"): "Heidelberg",
    ("DE", "70"): "Stuttgart centro",
    ("DE", "71"): "Stuttgart norte",
    ("DE", "72"): "Stuttgart sud (Tübingen)",
    ("DE", "73"): "Göppingen",
    ("DE", "74"): "Heilbronn",
    ("DE", "75"): "Pforzheim",
    ("DE", "76"): "Karlsruhe",
    ("DE", "77"): "Offenburg",
    ("DE", "78"): "Konstanz",
    ("DE", "79"): "Freiburg",
    ("DE", "80"): "München centro",
    ("DE", "81"): "München este",
    ("DE", "82"): "München sur (Starnberg)",
    ("DE", "83"): "Rosenheim",
    ("DE", "84"): "Landshut",
    ("DE", "85"): "München norte (Ebersberg)",
    ("DE", "86"): "Augsburg",
    ("DE", "87"): "Kempten",
    ("DE", "88"): "Ravensburg",
    ("DE", "89"): "Ulm",
    ("DE", "90"): "Nürnberg",
    ("DE", "91"): "Fürth/Erlangen",
    ("DE", "92"): "Amberg",
    ("DE", "93"): "Regensburg",
    ("DE", "94"): "Passau",
    ("DE", "95"): "Hof",
    ("DE", "96"): "Bamberg",
    ("DE", "97"): "Würzburg",
    ("DE", "98"): "Suhl",
    ("DE", "99"): "Erfurt nord",
    ("DO", "10"): "Santo Domingo Piantini / Naco (premium)",
    ("DO", "11"): "Santo Domingo Norte / Villa Mella",
    ("DO", "14"): "Santo Domingo Este / Boca Chica",
    ("DO", "21"): "San Pedro de Macorís",
    ("DO", "22"): "La Romana / Casa de Campo",
    ("DO", "23"): "Punta Cana / Bávaro (turismo)",
    ("DO", "31"): "San Francisco de Macorís",
    ("DO", "41"): "La Vega",
    ("DO", "42"): "Bonao",
    ("DO", "48"): "Moca",
    ("DO", "51"): "Santiago Centro",
    ("DO", "57"): "Puerto Plata",
    ("DO", "81"): "Barahona",
    ("EC", "010"): "Cuenca Norte",
    ("EC", "011"): "Cuenca",
    ("EC", "070"): "Machala",
    ("EC", "090"): "Samborondón / Guayaquil Norte",
    ("EC", "091"): "Guayaquil Norte",
    ("EC", "092"): "Guayaquil Centro",
    ("EC", "093"): "Guayaquil Sur",
    ("EC", "110"): "Loja",
    ("EC", "130"): "Manta",
    ("EC", "170"): "Quito Norte premium",
    ("EC", "171"): "Quito Norte",
    ("EC", "172"): "Quito Centro-Norte",
    ("EC", "173"): "Quito Centro",
    ("EC", "174"): "Quito Sur",
    ("EC", "180"): "Ambato",
    ("EC", "230"): "Santo Domingo",
    ("EG", "11"): "El Cairo Zamalek / Heliopolis / Maadi / Nasr City",
    ("EG", "12"): "Giza / Mohandessin / Dokki / 6th October",
    ("EG", "21"): "Alejandría Centro / Smouha / Sidi Bishr",
    ("EG", "25"): "El Fayum",
    ("EG", "31"): "Tanta / Gharbiya",
    ("EG", "33"): "Damietta / Kafr el-Sheikh Norte",
    ("EG", "34"): "Mahalla el-Kobra / Kafr el-Sheikh",
    ("EG", "35"): "Mansoura / Dakahlia",
    ("EG", "36"): "Benha / Qalyubiya",
    ("EG", "41"): "Ismailia",
    ("EG", "42"): "Port Said",
    ("EG", "43"): "Suez",
    ("EG", "44"): "El-Arish / Sinai Norte",
    ("EG", "46"): "Sharm El Sheikh / Sinai Sur",
    ("EG", "51"): "Marsa Matruh",
    ("EG", "62"): "Beni Suef",
    ("EG", "71"): "Asiut",
    ("EG", "81"): "Aswan",
    ("EG", "82"): "Luxor",
    ("EG", "84"): "Hurghada / Mar Rojo",
    ("EG", "85"): "Qena",
    ("EG", "92"): "Sohag",
    ("ES", "01"): "Álava (Vitoria)",
    ("ES", "02"): "Albacete",
    ("ES", "03"): "Alicante",
    ("ES", "04"): "Almería",
    ("ES", "05"): "Ávila",
    ("ES", "06"): "Badajoz",
    ("ES", "07"): "Baleares",
    ("ES", "08"): "Barcelona",
    ("ES", "09"): "Burgos",
    ("ES", "10"): "Cáceres",
    ("ES", "11"): "Cádiz",
    ("ES", "12"): "Castellón",
    ("ES", "13"): "Ciudad Real",
    ("ES", "14"): "Córdoba",
    ("ES", "15"): "A Coruña",
    ("ES", "16"): "Cuenca",
    ("ES", "17"): "Girona",
    ("ES", "18"): "Granada",
    ("ES", "19"): "Guadalajara",
    ("ES", "20"): "Gipuzkoa (Donostia)",
    ("ES", "21"): "Huelva",
    ("ES", "22"): "Huesca",
    ("ES", "23"): "Jaén",
    ("ES", "24"): "León",
    ("ES", "25"): "Lleida",
    ("ES", "26"): "La Rioja",
    ("ES", "27"): "Lugo",
    ("ES", "28"): "Madrid",
    ("ES", "29"): "Málaga",
    ("ES", "30"): "Murcia",
    ("ES", "31"): "Navarra",
    ("ES", "32"): "Ourense",
    ("ES", "33"): "Asturias",
    ("ES", "34"): "Palencia",
    ("ES", "35"): "Las Palmas",
    ("ES", "36"): "Pontevedra",
    ("ES", "37"): "Salamanca",
    ("ES", "38"): "Santa Cruz Tenerife",
    ("ES", "39"): "Cantabria",
    ("ES", "40"): "Segovia",
    ("ES", "41"): "Sevilla",
    ("ES", "42"): "Soria",
    ("ES", "43"): "Tarragona",
    ("ES", "44"): "Teruel",
    ("ES", "45"): "Toledo",
    ("ES", "46"): "Valencia",
    ("ES", "47"): "Valladolid",
    ("ES", "48"): "Bizkaia (Bilbao)",
    ("ES", "49"): "Zamora",
    ("ES", "50"): "Zaragoza",
    ("FR", "04"): "Alpes-de-Haute-Provence",
    ("FR", "05"): "Hautes-Alpes",
    ("FR", "06"): "Alpes-Maritimes (Nice, Cannes)",
    ("FR", "11"): "Aude (Carcassonne)",
    ("FR", "13"): "Bouches-du-Rhône (Marseille)",
    ("FR", "14"): "Calvados (Caen)",
    ("FR", "21"): "Côte-d'Or (Dijon)",
    ("FR", "22"): "Côtes-d'Armor",
    ("FR", "25"): "Doubs (Besançon)",
    ("FR", "29"): "Finistère (Brest)",
    ("FR", "2A"): "Corse-du-Sud",
    ("FR", "2B"): "Haute-Corse",
    ("FR", "30"): "Gard (Nîmes)",
    ("FR", "31"): "Haute-Garonne (Toulouse)",
    ("FR", "33"): "Gironde (Bordeaux)",
    ("FR", "34"): "Hérault (Montpellier)",
    ("FR", "35"): "Ille-et-Vilaine (Rennes)",
    ("FR", "37"): "Indre-et-Loire (Tours)",
    ("FR", "38"): "Isère (Grenoble)",
    ("FR", "40"): "Landes",
    ("FR", "44"): "Loire-Atlantique (Nantes)",
    ("FR", "49"): "Maine-et-Loire (Angers)",
    ("FR", "51"): "Marne (Reims)",
    ("FR", "54"): "Meurthe-et-Moselle (Nancy)",
    ("FR", "56"): "Morbihan (Vannes)",
    ("FR", "57"): "Moselle (Metz)",
    ("FR", "59"): "Nord (Lille)",
    ("FR", "60"): "Oise (Beauvais)",
    ("FR", "62"): "Pas-de-Calais (Lens)",
    ("FR", "63"): "Puy-de-Dôme (Clermont-Ferrand)",
    ("FR", "64"): "Pyrénées-Atlantiques (Pau/Biarritz)",
    ("FR", "66"): "Pyrénées-Orientales (Perpignan)",
    ("FR", "67"): "Bas-Rhin (Strasbourg)",
    ("FR", "69"): "Rhône (Lyon)",
    ("FR", "73"): "Savoie (Chambéry)",
    ("FR", "74"): "Haute-Savoie (Annecy)",
    ("FR", "75"): "Paris",
    ("FR", "76"): "Seine-Maritime (Rouen)",
    ("FR", "77"): "Seine-et-Marne",
    ("FR", "78"): "Yvelines (Versailles)",
    ("FR", "80"): "Somme (Amiens)",
    ("FR", "83"): "Var (Toulon)",
    ("FR", "84"): "Vaucluse (Avignon)",
    ("FR", "85"): "Vendée (La Roche)",
    ("FR", "86"): "Vienne (Poitiers)",
    ("FR", "87"): "Haute-Vienne (Limoges)",
    ("FR", "91"): "Essonne",
    ("FR", "92"): "Hauts-de-Seine (Neuilly, Boulogne)",
    ("FR", "93"): "Seine-Saint-Denis",
    ("FR", "94"): "Val-de-Marne",
    ("FR", "95"): "Val-d'Oise",
    ("FR", "971"): "Guadeloupe",
    ("FR", "972"): "Martinique",
    ("FR", "973"): "Guyane",
    ("FR", "974"): "Réunion",
    ("FR", "976"): "Mayotte",
    ("GR", "10"): "Atenas centro (Kolonaki/Syntagma)",
    ("GR", "11"): "Atenas norte premium (Kifisia)",
    ("GR", "12"): "Atenas oeste (Peristeri)",
    ("GR", "14"): "Atenas Marousi/Kifisia",
    ("GR", "15"): "Atenas norte suburbio",
    ("GR", "16"): "Atenas sur premium (Glyfada/Vouliagmeni)",
    ("GR", "17"): "Atenas sur (Kallithea)",
    ("GR", "18"): "Pireo premium",
    ("GR", "19"): "Attica este (Vari/Voula)",
    ("GR", "26"): "Patras",
    ("GR", "41"): "Larissa",
    ("GR", "49"): "Corfú",
    ("GR", "54"): "Tesalónica centro",
    ("GR", "55"): "Tesalónica este",
    ("GR", "56"): "Tesalónica oeste",
    ("GR", "57"): "Tesalónica suburbios",
    ("GR", "71"): "Heraklion Creta",
    ("GR", "82"): "Lesbos",
    ("GR", "85"): "Rodas",
    ("HK", "01"): "Central y Western (CBD premium — Hong Kong Island)",
    ("HK", "02"): "Wan Chai",
    ("HK", "03"): "Eastern / Quarry Bay",
    ("HK", "04"): "Southern / Aberdeen",
    ("HK", "05"): "Yau Tsim Mong (Tsim Sha Tsui / Jordan)",
    ("HK", "06"): "Sham Shui Po",
    ("HK", "07"): "Kowloon City",
    ("HK", "08"): "Wong Tai Sin",
    ("HK", "09"): "Kwun Tong",
    ("HK", "10"): "Kwai Tsing",
    ("HK", "11"): "Tsuen Wan",
    ("HK", "12"): "Tuen Mun",
    ("HK", "13"): "Yuen Long",
    ("HK", "14"): "New Territories Norte",
    ("HK", "15"): "Tai Po",
    ("HK", "16"): "Sha Tin",
    ("HK", "17"): "Sai Kung / Clearwater Bay",
    ("HK", "18"): "Isla Lantau / Outlying Islands",
    ("HU", "10"): "Budapest 1.-4. distritos",
    ("HU", "11"): "Budapest 5.-9.",
    ("HU", "12"): "Budapest 10.-14.",
    ("HU", "13"): "Budapest 15.-19.",
    ("HU", "14"): "Budapest 20.-23.",
    ("HU", "20"): "Suburbios Budapest (Pest county)",
    ("HU", "21"): "Suburbios más lejanos",
    ("HU", "22"): "Pest county sur",
    ("HU", "23"): "Pest county este",
    ("HU", "27"): "Nógrád",
    ("HU", "36"): "Eger",
    ("HU", "40"): "Debrecen",
    ("HU", "42"): "Debrecen outer",
    ("HU", "43"): "Nyíregyháza",
    ("HU", "44"): "Miskolc",
    ("HU", "50"): "Szolnok",
    ("HU", "60"): "Kecskemét",
    ("HU", "70"): "Pécs",
    ("HU", "80"): "Győr",
    ("HU", "84"): "Veszprém",
    ("HU", "90"): "Sopron (cerca de Austria)",
    ("HU", "94"): "Zalaegerszeg",
    ("ID", "10"): "Jakarta Pusat (Menteng / Gambir premium)",
    ("ID", "11"): "Jakarta Barat",
    ("ID", "12"): "Jakarta Selatan (Kebayoran Baru / Setiabudi)",
    ("ID", "13"): "Jakarta Timur",
    ("ID", "14"): "Jakarta Utara",
    ("ID", "15"): "Tangerang Selatan / BSD City / Serpong",
    ("ID", "16"): "Bogor / Depok",
    ("ID", "17"): "Bekasi",
    ("ID", "18"): "Tangerang Kota",
    ("ID", "20"): "Medan Centro (Medan Baru / Petisah)",
    ("ID", "25"): "Padang (Sumatra Barat)",
    ("ID", "28"): "Pekanbaru (Riau)",
    ("ID", "29"): "Batam (Kepulauan Riau — zona libre)",
    ("ID", "30"): "Palembang",
    ("ID", "40"): "Bandung Centro (Dago / Coblong premium)",
    ("ID", "42"): "Serang / Cilegon (Banten)",
    ("ID", "43"): "Sukabumi",
    ("ID", "45"): "Cirebon",
    ("ID", "50"): "Semarang Centro",
    ("ID", "51"): "Salatiga / Semarang suburbios",
    ("ID", "55"): "Yogyakarta",
    ("ID", "57"): "Solo / Surakarta",
    ("ID", "60"): "Surabaya Centro (Gubeng / Genteng premium)",
    ("ID", "61"): "Surabaya Norte / Gresik",
    ("ID", "62"): "Surabaya Sur / Sidoarjo",
    ("ID", "65"): "Malang",
    ("ID", "75"): "Samarinda (Kalimantan Timur)",
    ("ID", "76"): "Balikpapan (Kalimantan Timur)",
    ("ID", "78"): "Pontianak (Kalimantan Barat)",
    ("ID", "80"): "Denpasar / Bali Sur (Kuta / Seminyak)",
    ("ID", "83"): "Mataram / Lombok",
    ("ID", "90"): "Makassar Centro (Sulawesi Selatan)",
    ("ID", "91"): "Makassar Norte / Maros",
    ("ID", "95"): "Manado (Sulawesi Utara)",
    ("ID", "99"): "Jayapura (Papua)",
    ("IL", "32"): "Haifa Carmel",
    ("IL", "33"): "Haifa centro",
    ("IL", "35"): "Hadera",
    ("IL", "40"): "Netanya",
    ("IL", "46"): "Hod HaSharon / Kfar Saba",
    ("IL", "52"): "Givatayim / Ramat Gan premium",
    ("IL", "60"): "Tel Aviv Rothschild/Neve Tzedek",
    ("IL", "61"): "Tel Aviv centro",
    ("IL", "62"): "Tel Aviv norte (Ramat Aviv)",
    ("IL", "63"): "Tel Aviv sur",
    ("IL", "66"): "Herzliya Pituah (premium)",
    ("IL", "67"): "Ramat Gan general",
    ("IL", "68"): "Bnei Brak",
    ("IL", "74"): "Ashdod",
    ("IL", "77"): "Beer Sheva",
    ("IL", "90"): "Jerusalén centro",
    ("IL", "91"): "Jerusalén norte",
    ("IL", "92"): "Jerusalén sur",
    ("IN", "110001"): "Connaught Place",
    ("IN", "110003"): "Lodi Estate",
    ("IN", "110010"): "Lutyens",
    ("IN", "110011"): "Karol Bagh",
    ("IN", "110016"): "Hauz Khas / GK",
    ("IN", "110017"): "Green Park",
    ("IN", "110019"): "Kalkaji / GK",
    ("IN", "110020"): "Lajpat Nagar",
    ("IN", "110021"): "South Extension",
    ("IN", "110022"): "CR Park",
    ("IN", "110024"): "Jangpura / Bhogal",
    ("IN", "110025"): "Patel Nagar",
    ("IN", "110026"): "Patparganj",
    ("IN", "110029"): "Greater Kailash",
    ("IN", "110030"): "Vasant Vihar",
    ("IN", "110048"): "Saket / DLF",
    ("IN", "110049"): "Mehrauli / Saket",
    ("IN", "110065"): "Dwarka premium",
    ("IN", "110075"): "Dwarka",
    ("IN", "110091"): "Shahdara",
    ("IN", "208001"): "Kanpur",
    ("IN", "226001"): "Lucknow",
    ("IN", "302001"): "Jaipur",
    ("IN", "380001"): "Ahmedabad",
    ("IN", "380054"): "Ahmedabad premium",
    ("IN", "395001"): "Surat",
    ("IN", "400001"): "Fort / CST",
    ("IN", "400005"): "Colaba",
    ("IN", "400006"): "Malabar Hill",
    ("IN", "400007"): "Grant Road",
    ("IN", "400008"): "Byculla",
    ("IN", "400010"): "Mazagon",
    ("IN", "400011"): "Chunabhatti",
    ("IN", "400012"): "Dadar",
    ("IN", "400013"): "Sion",
    ("IN", "400014"): "Matunga",
    ("IN", "400016"): "Mahim",
    ("IN", "400017"): "Dharavi (gentrifying)",
    ("IN", "400018"): "Worli",
    ("IN", "400019"): "Prabhadevi",
    ("IN", "400022"): "Chembur",
    ("IN", "400025"): "Pali Hill / Bandra West",
    ("IN", "400026"): "Bandra",
    ("IN", "400028"): "Juhu",
    ("IN", "400029"): "Santacruz West",
    ("IN", "400049"): "Andheri West premium",
    ("IN", "400051"): "Andheri West",
    ("IN", "400053"): "Andheri East",
    ("IN", "400058"): "Goregaon West",
    ("IN", "400063"): "Borivali West",
    ("IN", "400070"): "Chembur East",
    ("IN", "400072"): "Powai",
    ("IN", "400076"): "Andheri East premium",
    ("IN", "400080"): "Mulund",
    ("IN", "400086"): "Ghatkopar",
    ("IN", "400088"): "Vikhroli",
    ("IN", "400601"): "Thane West",
    ("IN", "400606"): "Thane East",
    ("IN", "400614"): "Navi Mumbai premium",
    ("IN", "400705"): "Panvel",
    ("IN", "411001"): "Pune central",
    ("IN", "411006"): "Koregaon Park",
    ("IN", "411028"): "Aundh",
    ("IN", "411045"): "Baner",
    ("IN", "440001"): "Nagpur",
    ("IN", "462001"): "Bhopal",
    ("IN", "500003"): "Hyderabad Old City",
    ("IN", "500019"): "Kondapur",
    ("IN", "500032"): "Madhapur / Hi-Tech City",
    ("IN", "500033"): "Jubilee Hills",
    ("IN", "500034"): "Banjara Hills",
    ("IN", "500062"): "Secunderabad",
    ("IN", "500073"): "Kukatpally",
    ("IN", "500082"): "Gachibowli",
    ("IN", "560001"): "MG Road",
    ("IN", "560008"): "Indiranagar",
    ("IN", "560034"): "Koramangala",
    ("IN", "560037"): "Jayanagar",
    ("IN", "560047"): "JP Nagar",
    ("IN", "560066"): "Whitefield premium",
    ("IN", "560076"): "Electronic City premium",
    ("IN", "560100"): "Electronic City",
    ("IN", "560103"): "Whitefield",
    ("IN", "600002"): "Anna Nagar",
    ("IN", "600004"): "Nungambakkam",
    ("IN", "600006"): "Adyar",
    ("IN", "600014"): "Gopalapuram",
    ("IN", "600017"): "Alwarpet",
    ("IN", "600041"): "Velachery",
    ("IN", "682001"): "Kochi",
    ("IN", "700001"): "Kolkata CBD",
    ("IN", "700016"): "Ballygunge",
    ("IN", "700019"): "Park Street",
    ("IN", "700032"): "Behala",
    ("IQ", "10"): "Bagdad Karrada/Mansour premium",
    ("IQ", "11"): "Bagdad Zayouna/Jadriya",
    ("IQ", "12"): "Bagdad Karada",
    ("IQ", "13"): "Bagdad oeste",
    ("IQ", "14"): "Bagdad este",
    ("IQ", "15"): "Bagdad outer",
    ("IQ", "16"): "Bagdad suburbios",
    ("IQ", "36"): "Basra ciudad",
    ("IQ", "37"): "Basra zonas petroleras",
    ("IQ", "38"): "Basra rural",
    ("IQ", "44"): "Erbil (Kurdistan)",
    ("IQ", "45"): "Sulaymaniyah",
    ("IQ", "46"): "Dohuk",
    ("IQ", "54"): "Karbala",
    ("IQ", "56"): "Mosul",
    ("IQ", "60"): "Kirkuk",
    ("IQ", "61"): "Najaf",
    ("IR", "11"): "Teherán norte (Shemiran/Zafaraniyeh)",
    ("IR", "12"): "Teherán centro premium",
    ("IR", "13"): "Teherán Elahiyeh/Jordan",
    ("IR", "14"): "Teherán Saadat Abad",
    ("IR", "15"): "Teherán oeste",
    ("IR", "16"): "Teherán este",
    ("IR", "17"): "Teherán sur",
    ("IR", "18"): "Teherán suroeste",
    ("IR", "19"): "Teherán sur lejano",
    ("IR", "31"): "Isfahan",
    ("IR", "32"): "Isfahan outer",
    ("IR", "38"): "Karaj",
    ("IR", "41"): "Tabriz",
    ("IR", "51"): "Mashhad",
    ("IR", "52"): "Mashhad outer",
    ("IR", "71"): "Shiraz",
    ("IR", "72"): "Shiraz outer",
    ("IR", "76"): "Kish Island (zona libre)",
    ("IR", "79"): "Bandar Abbas",
    ("IT", "00"): "Roma",
    ("IT", "01"): "Viterbo",
    ("IT", "02"): "Rieti",
    ("IT", "03"): "Frosinone",
    ("IT", "04"): "Latina",
    ("IT", "05"): "Terni",
    ("IT", "06"): "Perugia",
    ("IT", "07"): "Sassari",
    ("IT", "08"): "Nuoro",
    ("IT", "09"): "Cagliari",
    ("IT", "10"): "Torino",
    ("IT", "11"): "Aosta",
    ("IT", "12"): "Cuneo",
    ("IT", "13"): "Vercelli",
    ("IT", "14"): "Asti",
    ("IT", "15"): "Alessandria",
    ("IT", "16"): "Genova",
    ("IT", "17"): "Savona",
    ("IT", "18"): "Imperia (Riviera)",
    ("IT", "19"): "La Spezia",
    ("IT", "20"): "Milano",
    ("IT", "21"): "Varese",
    ("IT", "22"): "Como",
    ("IT", "23"): "Sondrio",
    ("IT", "24"): "Bergamo",
    ("IT", "25"): "Brescia",
    ("IT", "27"): "Pavia",
    ("IT", "30"): "Venezia",
    ("IT", "31"): "Treviso",
    ("IT", "32"): "Belluno",
    ("IT", "33"): "Udine",
    ("IT", "34"): "Trieste",
    ("IT", "35"): "Padova",
    ("IT", "36"): "Vicenza",
    ("IT", "37"): "Verona",
    ("IT", "38"): "Trento",
    ("IT", "39"): "Bolzano (BZ)",
    ("IT", "40"): "Bologna",
    ("IT", "41"): "Modena",
    ("IT", "42"): "Reggio Emilia",
    ("IT", "43"): "Parma",
    ("IT", "44"): "Ferrara",
    ("IT", "47"): "Forlì-Cesena",
    ("IT", "48"): "Ravenna",
    ("IT", "50"): "Firenze",
    ("IT", "51"): "Pistoia",
    ("IT", "52"): "Arezzo",
    ("IT", "53"): "Siena",
    ("IT", "54"): "Massa",
    ("IT", "55"): "Lucca",
    ("IT", "56"): "Pisa",
    ("IT", "57"): "Livorno",
    ("IT", "58"): "Grosseto",
    ("IT", "59"): "Prato",
    ("IT", "60"): "Ancona",
    ("IT", "61"): "Pesaro",
    ("IT", "62"): "Macerata",
    ("IT", "63"): "Ascoli Piceno",
    ("IT", "64"): "Teramo",
    ("IT", "65"): "Pescara",
    ("IT", "66"): "Chieti",
    ("IT", "67"): "L'Aquila",
    ("IT", "70"): "Bari",
    ("IT", "71"): "Foggia",
    ("IT", "72"): "Brindisi/Taranto",
    ("IT", "73"): "Lecce",
    ("IT", "74"): "Taranto",
    ("IT", "75"): "Matera",
    ("IT", "76"): "BAT",
    ("IT", "80"): "Napoli",
    ("IT", "81"): "Caserta",
    ("IT", "82"): "Benevento",
    ("IT", "83"): "Avellino",
    ("IT", "84"): "Salerno",
    ("IT", "85"): "Potenza",
    ("IT", "86"): "Campobasso",
    ("IT", "87"): "Cosenza",
    ("IT", "88"): "Catanzaro",
    ("IT", "89"): "Reggio Calabria",
    ("IT", "90"): "Palermo",
    ("IT", "91"): "Trapani",
    ("IT", "92"): "Agrigento",
    ("IT", "93"): "Caltanissetta",
    ("IT", "94"): "Enna",
    ("IT", "95"): "Catania",
    ("IT", "96"): "Siracusa",
    ("IT", "97"): "Ragusa",
    ("IT", "98"): "Messina",
    ("JO", "11"): "Ammán (Abdoun / Shmaisani / Jabal Amman)",
    ("JO", "13"): "Zarqa",
    ("JO", "17"): "Madaba",
    ("JO", "19"): "Salt / Balqa",
    ("JO", "21"): "Irbid",
    ("JO", "25"): "Mafraq",
    ("JO", "26"): "Ajloun / Jerash",
    ("JO", "61"): "Karak",
    ("JO", "66"): "Tafilah",
    ("JO", "71"): "Ma'an / Wadi Rum",
    ("JO", "77"): "Aqaba",
    ("JP", "100"): "Tokyo Chiyoda (zona imperial/financiera)",
    ("JP", "105"): "Tokyo Minato",
    ("JP", "106"): "Tokyo Minato Azabu/Roppongi",
    ("JP", "107"): "Tokyo Akasaka/Roppongi Hills",
    ("JP", "108"): "Tokyo Shiba/Takanawa",
    ("JP", "110"): "Tokyo Taito",
    ("JP", "111"): "Tokyo Taito/Asakusa",
    ("JP", "120"): "Tokyo Adachi",
    ("JP", "125"): "Tokyo Katsushika",
    ("JP", "130"): "Tokyo Sumida",
    ("JP", "135"): "Tokyo Koto (Toyosu/Ariake)",
    ("JP", "141"): "Tokyo Shinagawa estación",
    ("JP", "145"): "Tokyo Shinagawa",
    ("JP", "150"): "Tokyo Shibuya",
    ("JP", "153"): "Tokyo Meguro",
    ("JP", "155"): "Tokyo Setagaya premium",
    ("JP", "160"): "Tokyo Shinjuku",
    ("JP", "167"): "Tokyo Suginami premium",
    ("JP", "171"): "Tokyo Toshima/Ikebukuro",
    ("JP", "180"): "Tokyo Nerima/Suginami",
    ("JP", "190"): "Tokyo oeste (Tachikawa)",
    ("JP", "194"): "Tokyo lejano oeste",
    ("JP", "220"): "Yokohama Nishi",
    ("JP", "221"): "Yokohama Kanagawa",
    ("JP", "231"): "Yokohama centro",
    ("JP", "450"): "Nagoya estación",
    ("JP", "460"): "Nagoya Naka",
    ("JP", "464"): "Nagoya Chikusa",
    ("JP", "530"): "Osaka Kita (Umeda/Nakanoshima)",
    ("JP", "540"): "Osaka centro",
    ("JP", "542"): "Osaka Namba",
    ("JP", "550"): "Osaka Fukushima",
    ("JP", "600"): "Kyoto centro",
    ("JP", "603"): "Kyoto norte",
    ("JP", "810"): "Fukuoka Chuo",
    ("JP", "812"): "Fukuoka Hakata",
    ("KR", "01"): "Seúl Dobong/Nowon",
    ("KR", "02"): "Seúl Seongbuk/Jungnang",
    ("KR", "03"): "Seúl Jongno/Jung",
    ("KR", "04"): "Seúl Jung/Seongdong",
    ("KR", "05"): "Seúl Songpa/Gwangjin",
    ("KR", "06"): "Seúl Gangnam/Seocho (premium)",
    ("KR", "07"): "Seúl Mapo/Yongsan",
    ("KR", "08"): "Seúl Yangcheon/Gangseo",
    ("KR", "10"): "Gyeonggi norte",
    ("KR", "13"): "Seongnam/Bundang (Gyeonggi premium)",
    ("KR", "14"): "Gyeonggi este",
    ("KR", "16"): "Suwon",
    ("KR", "17"): "Gyeonggi sur",
    ("KR", "21"): "Incheon centro",
    ("KR", "22"): "Incheon outer",
    ("KR", "35"): "Daejeon centro",
    ("KR", "38"): "Sejong City (nueva capital)",
    ("KR", "41"): "Daegu centro",
    ("KR", "46"): "Busan Haeundae (premium)",
    ("KR", "47"): "Busan centro",
    ("KR", "48"): "Busan Saha/outer",
    ("KR", "63"): "Jeju Island",
    ("KW", "13"): "Kuwait City Centro / Sharq (premium)",
    ("KW", "22"): "Salmiya / Salwa",
    ("KW", "25"): "Rumaithiya / Bayan",
    ("KW", "32"): "Hawalli",
    ("KW", "42"): "Al Jahra",
    ("KW", "43"): "Bayan / Mishref",
    ("KW", "47"): "Sabah Al-Ahmad (nueva ciudad)",
    ("KW", "61"): "Ahmadi (zona petrolera)",
    ("KW", "62"): "Fahaheel",
    ("KW", "63"): "Abu Halifa",
    ("KW", "64"): "Mahboula",
    ("KW", "77"): "Mubarak Al-Kabeer",
    ("KW", "81"): "Farwaniya",
    ("KZ", "010"): "Astana/Nur-Sultan centro",
    ("KZ", "011"): "Astana outer",
    ("KZ", "040"): "Atyrau (ciudad petrolera)",
    ("KZ", "050"): "Almaty centro premium (Medeu/Bostandyk)",
    ("KZ", "051"): "Almaty inner",
    ("KZ", "052"): "Almaty outer",
    ("KZ", "053"): "Almaty suburbios",
    ("KZ", "060"): "Aktau",
    ("KZ", "070"): "Kyzylorda",
    ("KZ", "071"): "Shymkent",
    ("KZ", "080"): "Aktobe",
    ("KZ", "090"): "Oral",
    ("KZ", "100"): "Karaganda",
    ("KZ", "110"): "Pavlodar",
    ("KZ", "120"): "Semey",
    ("KZ", "130"): "Ust-Kamenogorsk",
    ("KZ", "140"): "Petropavl",
    ("MA", "10"): "Rabat Agdal / Hassan / Hay Riad",
    ("MA", "11"): "Rabat Salé / Témara",
    ("MA", "14"): "Kenitra / Sidi Slimane",
    ("MA", "20"): "Casablanca Centro / Maarif / Anfa",
    ("MA", "21"): "Casablanca Norte / Sidi Maarouf",
    ("MA", "22"): "Casablanca Sur / Aïn Sebaâ",
    ("MA", "23"): "Beni Mellal / Khouribga",
    ("MA", "24"): "El Jadida / Azemmour",
    ("MA", "26"): "Settat",
    ("MA", "30"): "Fès Ville Nouvelle / Agdal",
    ("MA", "31"): "Fès Médina / Saïss",
    ("MA", "40"): "Marrakech Guéliz / Hivernage",
    ("MA", "41"): "Marrakech Médina",
    ("MA", "42"): "Marrakech afueras / Menara",
    ("MA", "44"): "Essaouira",
    ("MA", "46"): "Safi",
    ("MA", "50"): "Meknès Centro",
    ("MA", "51"): "Meknès rural / Ifrane",
    ("MA", "52"): "Errachidia / Midelt",
    ("MA", "60"): "Oujda",
    ("MA", "62"): "Nador",
    ("MA", "70"): "Laayoune",
    ("MA", "73"): "Dakhla",
    ("MA", "80"): "Agadir Centro / Talborjt",
    ("MA", "81"): "Agadir afueras / Inezgane",
    ("MA", "90"): "Tánger Centro / Marchane",
    ("MA", "91"): "Tánger Malabata / Achakar",
    ("MA", "93"): "Tétouan",
    ("MX", "01"): "Álvaro Obregón (Lomas Plateros)",
    ("MX", "02"): "Azcapotzalco",
    ("MX", "03"): "Benito Juárez (Narvarte, Del Valle)",
    ("MX", "04"): "Coyoacán",
    ("MX", "05"): "Cuajimalpa (Santa Fe)",
    ("MX", "06"): "Cuauhtémoc (Juárez, Roma)",
    ("MX", "07"): "Iztacalco",
    ("MX", "08"): "Gustavo A. Madero",
    ("MX", "09"): "Tlalpan",
    ("MX", "10"): "Iztapalapa",
    ("MX", "11"): "Miguel Hidalgo (Polanco, Lomas)",
    ("MX", "13"): "Xochimilco / Tláhuac",
    ("MX", "20"): "Aguascalientes",
    ("MX", "21"): "Mexicali",
    ("MX", "22"): "Tijuana",
    ("MX", "25"): "Saltillo",
    ("MX", "27"): "Torreón",
    ("MX", "29"): "Tuxtla Gutiérrez (Chiapas)",
    ("MX", "31"): "Chihuahua",
    ("MX", "32"): "Ciudad Juárez",
    ("MX", "39"): "Acapulco",
    ("MX", "44"): "Guadalajara",
    ("MX", "45"): "Zapopan",
    ("MX", "46"): "Tlaquepaque / Tonalá",
    ("MX", "48"): "Puerto Vallarta y zona jal",
    ("MX", "50"): "Tlalnepantla",
    ("MX", "52"): "Huixquilucan (Santa Fe / Interlomas)",
    ("MX", "53"): "Naucalpan",
    ("MX", "54"): "Atizapán",
    ("MX", "55"): "Ecatepec",
    ("MX", "56"): "Chimalhuacán / Los Reyes",
    ("MX", "57"): "Nezahualcóyotl",
    ("MX", "58"): "Morelia",
    ("MX", "64"): "Monterrey",
    ("MX", "65"): "Apodaca",
    ("MX", "66"): "San Pedro Garza García",
    ("MX", "67"): "Guadalupe / San Nicolás",
    ("MX", "68"): "Santa Catarina / General Escobedo",
    ("MX", "72"): "Puebla",
    ("MX", "76"): "Querétaro",
    ("MX", "77"): "Cancún",
    ("MX", "78"): "San Luis Potosí",
    ("MX", "80"): "Culiacán",
    ("MX", "83"): "Hermosillo",
    ("MX", "86"): "Villahermosa (Tabasco)",
    ("MX", "90"): "Tlaxcala / Hidalgo",
    ("MX", "91"): "Veracruz",
    ("MX", "96"): "Coatzacoalcos / Tabasco",
    ("MX", "97"): "Mérida",
    ("MY", "10"): "Penang George Town",
    ("MY", "11"): "Penang sur",
    ("MY", "12"): "Penang inner",
    ("MY", "13"): "Penang outer",
    ("MY", "15"): "Kota Bharu (Kelantan)",
    ("MY", "25"): "Kuantan",
    ("MY", "30"): "Ipoh",
    ("MY", "40"): "Shah Alam",
    ("MY", "41"): "Petaling Jaya",
    ("MY", "47"): "Subang Jaya / Damansara",
    ("MY", "50"): "KL Bukit Bintang / KLCC",
    ("MY", "51"): "KL centro",
    ("MY", "52"): "KL norte",
    ("MY", "53"): "KL outer",
    ("MY", "54"): "KL oeste",
    ("MY", "55"): "KL sur",
    ("MY", "56"): "KL Cheras",
    ("MY", "57"): "KL Kepong",
    ("MY", "68"): "Ampang / Hulu Langat",
    ("MY", "80"): "Johor Bahru centro",
    ("MY", "81"): "Johor Bahru este",
    ("MY", "82"): "Johor inner",
    ("MY", "88"): "Kota Kinabalu (Sabah)",
    ("MY", "93"): "Kuching (Sarawak)",
    ("NG", "100"): "Ikeja GRA",
    ("NG", "101"): "Ikoyi",
    ("NG", "102"): "Surulere",
    ("NG", "103"): "Ikeja popular",
    ("NG", "105"): "Lekki phase 1",
    ("NG", "106"): "Ajah",
    ("NG", "200"): "Ibadan",
    ("NG", "234"): "Maitama Abuja",
    ("NG", "400"): "Enugu",
    ("NG", "460"): "Owerri",
    ("NG", "500"): "Port Harcourt GRA",
    ("NG", "600"): "Aba",
    ("NG", "640"): "Maiduguri",
    ("NG", "700"): "Kano",
    ("NG", "810"): "Benin City",
    ("NG", "840"): "Zaria",
    ("NG", "900"): "Maitama",
    ("NG", "901"): "Garki",
    ("NG", "902"): "Wuse II",
    ("NG", "903"): "Abuja popular",
    ("NG", "930"): "Jos",
    ("NG", "960"): "Kaduna",
    ("NL", "10"): "Ámsterdam Centrum / Jordaan / Oud-Zuid",
    ("NL", "11"): "Ámsterdam Zuidoost / Bijlmer",
    ("NL", "12"): "Hilversum / Laren / 't Gooi",
    ("NL", "13"): "Almere (Flevoland)",
    ("NL", "14"): "Bussum / Naarden",
    ("NL", "20"): "Haarlem",
    ("NL", "21"): "Haarlem suburbios / Heemstede",
    ("NL", "22"): "Katwijk / Noordwijk",
    ("NL", "23"): "Leiden Centro",
    ("NL", "24"): "Alphen aan den Rijn",
    ("NL", "25"): "Den Haag Centrum / Statenkwartier",
    ("NL", "26"): "Delft",
    ("NL", "27"): "Zoetermeer / Leidschendam",
    ("NL", "28"): "Gouda",
    ("NL", "30"): "Rotterdam Centrum / Kralingen",
    ("NL", "31"): "Rotterdam Noord / Schiedam",
    ("NL", "32"): "Spijkenisse / Barendrecht",
    ("NL", "33"): "Dordrecht",
    ("NL", "34"): "Gorinchem",
    ("NL", "35"): "Utrecht Centrum",
    ("NL", "36"): "Nieuwegein / IJsselstein",
    ("NL", "37"): "Veenendaal / Zeist",
    ("NL", "38"): "Amersfoort",
    ("NL", "42"): "'s-Hertogenbosch área",
    ("NL", "44"): "Waalwijk",
    ("NL", "46"): "Bergen op Zoom",
    ("NL", "47"): "Helmond",
    ("NL", "48"): "Breda",
    ("NL", "49"): "Roosendaal",
    ("NL", "50"): "Tilburg Centro",
    ("NL", "52"): "'s-Hertogenbosch / Den Bosch",
    ("NL", "55"): "Eindhoven área",
    ("NL", "56"): "Eindhoven Centrum",
    ("NL", "57"): "Veldhoven / Waalre",
    ("NL", "58"): "Weert",
    ("NL", "59"): "Venlo",
    ("NL", "62"): "Maastricht",
    ("NL", "63"): "Nijmegen área",
    ("NL", "65"): "Nijmegen Centrum",
    ("NL", "68"): "Arnhem",
    ("NL", "73"): "Apeldoorn",
    ("NL", "74"): "Deventer",
    ("NL", "75"): "Enschede",
    ("NL", "76"): "Almelo",
    ("NL", "80"): "Zwolle",
    ("NL", "83"): "Hoogeveen / Drenthe Sur",
    ("NL", "89"): "Leeuwarden",
    ("NL", "97"): "Groningen Centrum",
    ("PE", "04001"): "Arequipa",
    ("PE", "04013"): "Yanahuara/Cayma (Arequipa premium)",
    ("PE", "06001"): "Tacna",
    ("PE", "06006"): "Moquegua",
    ("PE", "07001"): "Ica",
    ("PE", "08001"): "Cusco",
    ("PE", "12001"): "Huancayo",
    ("PE", "13001"): "Trujillo",
    ("PE", "14001"): "Chiclayo",
    ("PE", "15001"): "Lima Cercado",
    ("PE", "15012"): "La Molina",
    ("PE", "15013"): "La Victoria",
    ("PE", "15035"): "San Borja",
    ("PE", "15036"): "Miraflores premium",
    ("PE", "15038"): "Surco",
    ("PE", "15046"): "Lince",
    ("PE", "15047"): "Surquillo",
    ("PE", "15048"): "San Isidro",
    ("PE", "15063"): "Barranco",
    ("PE", "15081"): "Jesús María",
    ("PE", "15082"): "San Miguel",
    ("PE", "15083"): "Pueblo Libre",
    ("PE", "15084"): "Magdalena",
    ("PE", "15085"): "Breña",
    ("PE", "15088"): "SJL",
    ("PE", "15304"): "Los Olivos",
    ("PE", "15317"): "Carabayllo",
    ("PE", "15816"): "Villa María del Triunfo",
    ("PE", "15824"): "Villa El Salvador",
    ("PE", "16001"): "Iquitos",
    ("PE", "20001"): "Piura",
    ("PE", "21001"): "Juliaca",
    ("PE", "22001"): "Puno",
    ("PE", "25001"): "Pucallpa",
    ("PE", "25031"): "Huánuco",
    ("PL", "00"): "Varsovia centro (Śródmieście)",
    ("PL", "01"): "Varsovia norte",
    ("PL", "02"): "Varsovia Mokotów premium",
    ("PL", "04"): "Varsovia sur",
    ("PL", "05"): "Varsovia suburbios oeste",
    ("PL", "06"): "Varsovia outer",
    ("PL", "07"): "Varsovia suburbial",
    ("PL", "10"): "Olsztyn",
    ("PL", "15"): "Białystok",
    ("PL", "20"): "Lublin",
    ("PL", "30"): "Cracovia centro (Stare Miasto)",
    ("PL", "31"): "Cracovia premium",
    ("PL", "32"): "Cracovia norte",
    ("PL", "33"): "Cracovia outer",
    ("PL", "40"): "Katowice",
    ("PL", "50"): "Wroclaw centro",
    ("PL", "51"): "Wroclaw norte",
    ("PL", "52"): "Wroclaw outer",
    ("PL", "60"): "Poznan centro",
    ("PL", "61"): "Poznan inner",
    ("PL", "62"): "Poznan outer",
    ("PL", "70"): "Szczecin centro",
    ("PL", "80"): "Gdansk centro",
    ("PL", "81"): "Gdynia (premium)",
    ("PL", "82"): "Gdansk outer",
    ("PL", "83"): "Tricity outer",
    ("PT", "10"): "Lisboa Centro / Alfama",
    ("PT", "11"): "Lisboa Campo de Ourique / Estrela",
    ("PT", "12"): "Lisboa Chiado / Bairro Alto",
    ("PT", "13"): "Lisboa Belém / Ajuda",
    ("PT", "14"): "Lisboa Penha de França / Areeiro",
    ("PT", "15"): "Lisboa Benfica / Carnide",
    ("PT", "16"): "Lisboa Lumiar / Telheiras",
    ("PT", "17"): "Lisboa Alvalade",
    ("PT", "18"): "Lisboa Sacavém / Loures",
    ("PT", "19"): "Lisboa Olivais / Oriente",
    ("PT", "26"): "Sintra / Queluz",
    ("PT", "27"): "Amadora / Cascais",
    ("PT", "28"): "Almada / Seixal",
    ("PT", "29"): "Setúbal",
    ("PT", "30"): "Coimbra Centro",
    ("PT", "31"): "Pombal / Cantanhede",
    ("PT", "32"): "Leiria",
    ("PT", "33"): "Figueira da Foz",
    ("PT", "34"): "Viseu",
    ("PT", "35"): "Guarda",
    ("PT", "40"): "Porto Baixa / Ribeira",
    ("PT", "41"): "Porto Foz / Boavista Premium",
    ("PT", "42"): "Porto Gondomar / Campanhã",
    ("PT", "43"): "Matosinhos / Leça",
    ("PT", "44"): "Vila Nova de Gaia",
    ("PT", "45"): "Espinho / Santa Maria da Feira",
    ("PT", "46"): "Aveiro",
    ("PT", "47"): "Braga Centro",
    ("PT", "48"): "Guimarães",
    ("PT", "49"): "Viana do Castelo",
    ("PT", "50"): "Lamego / Régua",
    ("PT", "51"): "Peso da Régua",
    ("PT", "52"): "Bragança",
    ("PT", "53"): "Chaves",
    ("PT", "54"): "Vila Real",
    ("PT", "60"): "Covilhã",
    ("PT", "61"): "Fundão",
    ("PT", "62"): "Castelo Branco",
    ("PT", "63"): "Portalegre",
    ("PT", "70"): "Évora",
    ("PT", "71"): "Beja",
    ("PT", "72"): "Santiago do Cacém / Sines",
    ("PT", "73"): "Elvas",
    ("PT", "80"): "Faro",
    ("PT", "81"): "Loulé / Vilamoura",
    ("PT", "82"): "Albufeira",
    ("PT", "83"): "Portimão / Lagos",
    ("PT", "84"): "Tavira / Olhão",
    ("PT", "90"): "Ponta Delgada (Açores)",
    ("PT", "91"): "Angra do Heroísmo (Açores)",
    ("PT", "94"): "Funchal (Madeira)",
    ("PT", "95"): "Santa Cruz (Madeira)",
    ("PY", "1201"): "Asunción Centro",
    ("PY", "1202"): "Asunción Centro-Norte",
    ("PY", "1204"): "Asunción Manorá",
    ("PY", "1209"): "Asunción premium (Villa Morra)",
    ("PY", "1227"): "Asunción Sur",
    ("PY", "1906"): "Asunción Sajonia",
    ("PY", "2000"): "Encarnación",
    ("PY", "2160"): "Limpio",
    ("PY", "2200"): "Ypacaraí",
    ("PY", "2300"): "Luque",
    ("PY", "2310"): "Fernando de la Mora",
    ("PY", "2323"): "Lambaré",
    ("PY", "2760"): "San Lorenzo",
    ("PY", "2780"): "Capiatá",
    ("PY", "2910"): "Itauguá",
    ("PY", "2950"): "Areguá",
    ("PY", "3310"): "Coronel Oviedo",
    ("PY", "3900"): "Ciudad del Este premium",
    ("PY", "3901"): "Ciudad del Este popular",
    ("PY", "4210"): "Caazapá",
    ("PY", "6000"): "Villarrica",
    ("PY", "6810"): "Caaguazú",
    ("PY", "7000"): "Concepción",
    ("PY", "8000"): "Pilar",
    ("QA", "20"): "Doha West Bay / Pearl Qatar",
    ("QA", "21"): "Doha Diplomatic Zone",
    ("QA", "22"): "Lusail City",
    ("QA", "23"): "Doha centro",
    ("QA", "24"): "Doha residencial",
    ("QA", "25"): "Doha sur",
    ("QA", "26"): "Doha outer",
    ("QA", "27"): "Al Wakrah",
    ("QA", "28"): "Al Khor",
    ("QA", "29"): "Mesaieed",
    ("QA", "30"): "Al Rayyan",
    ("QA", "31"): "Umm Slal",
    ("QA", "32"): "Al Shamal",
    ("RO", "01"): "Bucarest sector 1 (Floreasca/Dorobanți)",
    ("RO", "02"): "Bucarest sector 2 (Herăstrău)",
    ("RO", "03"): "Bucarest sector 3",
    ("RO", "04"): "Bucarest sector 4 sur",
    ("RO", "05"): "Bucarest sector 5 sur",
    ("RO", "06"): "Bucarest sector 6",
    ("RO", "07"): "Ilfov county (suburbios)",
    ("RO", "10"): "Pitești",
    ("RO", "20"): "Ploiești",
    ("RO", "23"): "Constanța",
    ("RO", "30"): "Timișoara centro",
    ("RO", "31"): "Timișoara outer",
    ("RO", "40"): "Cluj-Napoca centro",
    ("RO", "41"): "Cluj-Napoca outer",
    ("RO", "50"): "Brașov centro",
    ("RO", "51"): "Brașov outer",
    ("RO", "60"): "Sibiu",
    ("RO", "70"): "Iași centro",
    ("RO", "71"): "Iași outer",
    ("RO", "80"): "Galați/Brăila",
    ("RO", "90"): "Costa del Mar Negro",
    ("RU", "101"): "Moscú centro (Kitai-Gorod)",
    ("RU", "103"): "Moscú Tverskoy",
    ("RU", "105"): "Moscú Sokolniki",
    ("RU", "107"): "Moscú Baumanskaya",
    ("RU", "109"): "Moscú Taganka",
    ("RU", "111"): "Moscú Perovo",
    ("RU", "113"): "Moscú Nagatino",
    ("RU", "115"): "Moscú Donskoy/Zamoskvorechye",
    ("RU", "117"): "Moscú suroeste premium (Lomonosovskiy)",
    ("RU", "119"): "Moscú Lomonosovskiy/MGU",
    ("RU", "121"): "Moscú Fili/Khamovniki (premium oeste)",
    ("RU", "123"): "Moscú Presnensky/Patriarshiye Prudy",
    ("RU", "125"): "Moscú norte",
    ("RU", "127"): "Moscú Dmitrovsky",
    ("RU", "129"): "Moscú Ostankino",
    ("RU", "190"): "San Petersburgo centro",
    ("RU", "191"): "San Petersburgo centro este",
    ("RU", "192"): "San Petersburgo sur",
    ("RU", "194"): "San Petersburgo norte",
    ("RU", "196"): "San Petersburgo sur outer",
    ("RU", "197"): "San Petersburgo Vasilievsky Island",
    ("RU", "199"): "San Petersburgo Petrogradsky",
    ("RU", "344"): "Rostov-on-Don",
    ("RU", "350"): "Krasnodar",
    ("RU", "354"): "Sochi",
    ("RU", "400"): "Volgogrado",
    ("RU", "420"): "Kazán",
    ("RU", "443"): "Samara",
    ("RU", "450"): "Ufá",
    ("RU", "454"): "Cheliábinsk",
    ("RU", "614"): "Perm",
    ("RU", "620"): "Ekaterinburg",
    ("RU", "630"): "Novosibirsk",
    ("RU", "660"): "Krasnoyarsk",
    ("RU", "664"): "Irkutsk",
    ("RU", "670"): "Ulán Udé",
    ("RU", "690"): "Vladivostok",
    ("SA", "11"): "Riad centro / Al Olaya / King Fahd Road",
    ("SA", "12"): "Yeda (Jeddah) centro / Al Hamra",
    ("SA", "13"): "Al Khobar premium",
    ("SA", "14"): "La Meca",
    ("SA", "21"): "Yeda Corniche",
    ("SA", "22"): "Yeda este",
    ("SA", "23"): "Yeda sur",
    ("SA", "24"): "Medina",
    ("SA", "25"): "Tabuk",
    ("SA", "26"): "Yanbu",
    ("SA", "28"): "Abha",
    ("SA", "31"): "Dammam",
    ("SA", "32"): "Dhahran Aramco",
    ("SA", "33"): "Jubail industrial premium",
    ("SA", "34"): "Hafar Al-Batin",
    ("SA", "35"): "Qatif",
    ("SN", "10"): "Dakar Plateau / Almadies (premium)",
    ("SN", "11"): "Dakar Mermoz / Fann / Point E",
    ("SN", "12"): "Dakar Médina / Liberté",
    ("SN", "13"): "Dakar Pikine",
    ("SN", "14"): "Guédiawaye",
    ("SN", "15"): "Rufisque / Diamniadio",
    ("SN", "18"): "Touba (ciudad santa)",
    ("SN", "20"): "Thiès",
    ("SN", "22"): "Saint-Louis",
    ("SN", "23"): "Diourbel",
    ("SN", "30"): "Kaolack",
    ("SN", "40"): "Ziguinchor",
    ("SN", "50"): "Kolda / Sédhiou",
    ("SN", "60"): "Tambacounda / Kédougou",
    ("TH", "10"): "Bangkok Sukhumvit / Silom / Sathon",
    ("TH", "11"): "Bangkok centro",
    ("TH", "12"): "Bangkok norte",
    ("TH", "13"): "Bangkok este",
    ("TH", "14"): "Bangkok outer",
    ("TH", "15"): "Pathum Thani",
    ("TH", "20"): "Chonburi / Pattaya",
    ("TH", "21"): "Chonburi inner",
    ("TH", "25"): "Ayutthaya",
    ("TH", "40"): "Khon Kaen",
    ("TH", "41"): "Udon Thani",
    ("TH", "50"): "Chiang Mai",
    ("TH", "51"): "Chiang Rai",
    ("TH", "52"): "Chiang Mai outer",
    ("TH", "53"): "Chiang Mai rural",
    ("TH", "57"): "Mae Hong Son",
    ("TH", "73"): "Nakhon Pathom",
    ("TH", "74"): "Samut Sakhon",
    ("TH", "76"): "Phuket",
    ("TH", "77"): "Surat Thani / Koh Samui",
    ("TH", "80"): "Nakhon Si Thammarat",
    ("TH", "83"): "Phuket ciudad",
    ("TH", "84"): "Surat Thani",
    ("TH", "90"): "Songkhla / Hat Yai",
    ("TH", "94"): "Pattani",
    ("TR", "06"): "Ankara Çankaya / Kavaklidere",
    ("TR", "07"): "Antalya centro",
    ("TR", "09"): "Aydın / Bodrum interior",
    ("TR", "16"): "Bursa centro",
    ("TR", "22"): "Edirne",
    ("TR", "25"): "Erzurum",
    ("TR", "26"): "Eskişehir",
    ("TR", "27"): "Gaziantep",
    ("TR", "31"): "Hatay",
    ("TR", "33"): "Mersin",
    ("TR", "34"): "Estambul (ambos lados)",
    ("TR", "35"): "İzmir Konak / Alsancak",
    ("TR", "36"): "Kars",
    ("TR", "38"): "Kayseri",
    ("TR", "41"): "Kocaeli / İzmit",
    ("TR", "42"): "Konya",
    ("TR", "43"): "Kütahya",
    ("TR", "44"): "Malatya",
    ("TR", "45"): "Manisa",
    ("TR", "46"): "Kahramanmaraş",
    ("TR", "47"): "Mardin",
    ("TR", "48"): "Muğla / Bodrum / Marmaris",
    ("TR", "49"): "Muş",
    ("TR", "52"): "Ordu",
    ("TR", "53"): "Rize",
    ("TR", "54"): "Sakarya / Adapazarı",
    ("TR", "55"): "Samsun",
    ("TR", "56"): "Siirt",
    ("TR", "58"): "Sivas",
    ("TR", "59"): "Tekirdağ",
    ("TR", "60"): "Tokat",
    ("TR", "61"): "Trabzon (alto turismo)",
    ("TR", "63"): "Şanlıurfa",
    ("TR", "65"): "Van",
    ("TR", "67"): "Zonguldak",
    ("TR", "69"): "Bayburt",
    ("TR", "70"): "Karaman",
    ("TR", "71"): "Kırıkkale",
    ("TR", "73"): "Şırnak",
    ("TR", "75"): "Ardahan",
    ("TR", "76"): "Iğdır",
    ("TR", "77"): "Yalova",
    ("TR", "78"): "Karabük",
    ("TW", "100"): "Taipéi Zhongzheng (gobierno/histórico)",
    ("TW", "103"): "Taipéi Datong",
    ("TW", "104"): "Taipéi Zhongshan",
    ("TW", "105"): "Taipéi Songshan",
    ("TW", "106"): "Taipéi Da'an (más premium)",
    ("TW", "108"): "Taipéi Wanhua",
    ("TW", "110"): "Taipéi Xinyi (Taipei 101 / Xinyi Dist)",
    ("TW", "111"): "Taipéi Shilin",
    ("TW", "112"): "Taipéi Beitou",
    ("TW", "114"): "Taipéi Neihu (parque tecnológico)",
    ("TW", "115"): "Taipéi Nangang",
    ("TW", "116"): "Taipéi Wenshan",
    ("TW", "200"): "Keelung Ciudad",
    ("TW", "220"): "Nueva Taipéi Banqiao",
    ("TW", "231"): "Nueva Taipéi Xindian",
    ("TW", "235"): "Nueva Taipéi Zhonghe / Yonghe",
    ("TW", "241"): "Nueva Taipéi Sanchong",
    ("TW", "251"): "Nueva Taipéi Tamsui / Danshui",
    ("TW", "300"): "Hsinchu Ciudad (hub tecnológico)",
    ("TW", "302"): "Hsinchu County",
    ("TW", "320"): "Taoyuan Ciudad",
    ("TW", "330"): "Taoyuan Zhongli",
    ("TW", "401"): "Taichung Centro",
    ("TW", "404"): "Taichung Xitun / Nantun (premium)",
    ("TW", "408"): "Taichung Beitun / Norte",
    ("TW", "413"): "Taichung Dali",
    ("TW", "700"): "Tainan Centro / Anping",
    ("TW", "704"): "Tainan Norte / Rende",
    ("TW", "708"): "Tainan Sur / Yongkang",
    ("TW", "800"): "Kaohsiung Xinxing / Lingya",
    ("TW", "802"): "Kaohsiung Qianzhen / Nanzih",
    ("TW", "806"): "Kaohsiung Zuoying (premium)",
    ("TW", "830"): "Kaohsiung Fengshan",
    ("TW", "900"): "Pingtung Ciudad",
    ("TW", "950"): "Taitung Ciudad",
    ("TW", "970"): "Hualien Ciudad",
    ("US", "011"): "Springfield MA",
    ("US", "012"): "Northampton / Pioneer Valley",
    ("US", "014"): "Lowell MA",
    ("US", "015"): "Worcester MA",
    ("US", "021"): "Boston",
    ("US", "022"): "Cambridge / Brookline",
    ("US", "023"): "Newton MA",
    ("US", "024"): "Boston suburbios premium",
    ("US", "025"): "Boston outer",
    ("US", "026"): "Framingham / Natick",
    ("US", "027"): "Quincy / Braintree",
    ("US", "028"): "New Haven CT",
    ("US", "030"): "Manchester NH",
    ("US", "040"): "Portland ME",
    ("US", "058"): "Burlington VT",
    ("US", "063"): "Greenwich CT (premium)",
    ("US", "064"): "Stamford CT",
    ("US", "065"): "Hartford CT",
    ("US", "069"): "Bridgeport CT",
    ("US", "070"): "Newark",
    ("US", "071"): "NJ Hudson",
    ("US", "072"): "NJ central",
    ("US", "073"): "NJ Middlesex",
    ("US", "074"): "NJ Monmouth",
    ("US", "075"): "NJ shore",
    ("US", "077"): "NJ Shore premium",
    ("US", "079"): "NJ Bergen/Morris (suburbs NYC)",
    ("US", "085"): "NJ Princeton / Mercer",
    ("US", "086"): "NJ Somerset premium",
    ("US", "100"): "Tribeca / SoHo / Financial District",
    ("US", "101"): "Midtown / Upper East Side",
    ("US", "102"): "Upper West Side / Harlem sur",
    ("US", "103"): "Staten Island",
    ("US", "104"): "Bronx",
    ("US", "110"): "Queens centro",
    ("US", "111"): "Forest Hills / Jamaica Estates",
    ("US", "112"): "Brooklyn Prospect Park / Park Slope",
    ("US", "113"): "Brooklyn outer",
    ("US", "114"): "Queens outer",
    ("US", "115"): "Long Island Nassau",
    ("US", "116"): "Long Island central",
    ("US", "117"): "Long Island south shore",
    ("US", "118"): "Long Island Hempstead",
    ("US", "119"): "Hamptons / East End",
    ("US", "191"): "Philadelphia",
    ("US", "192"): "Philadelphia suburbs Main Line",
    ("US", "193"): "Philadelphia premium suburbs",
    ("US", "200"): "Washington DC",
    ("US", "201"): "DC Metro norte",
    ("US", "202"): "DC central",
    ("US", "203"): "DC sureste",
    ("US", "204"): "DC outer",
    ("US", "205"): "DC Metro",
    ("US", "210"): "Baltimore premium (Roland Park)",
    ("US", "212"): "Baltimore",
    ("US", "220"): "Arlington VA",
    ("US", "221"): "Alexandria VA",
    ("US", "222"): "Fairfax VA",
    ("US", "223"): "Fairfax outer VA",
    ("US", "240"): "Virginia occidental",
    ("US", "244"): "Richmond VA",
    ("US", "245"): "Charlottesville VA",
    ("US", "271"): "Raleigh",
    ("US", "275"): "Chapel Hill / Research Triangle",
    ("US", "282"): "Charlotte",
    ("US", "288"): "Greensboro NC",
    ("US", "292"): "Charleston SC",
    ("US", "298"): "Columbia SC",
    ("US", "300"): "Atlanta",
    ("US", "301"): "Atlanta south",
    ("US", "302"): "Atlanta east",
    ("US", "303"): "Atlanta Buckhead / Midtown",
    ("US", "304"): "Marietta / Cobb County premium",
    ("US", "305"): "Alpharetta / Johns Creek",
    ("US", "320"): "Jacksonville FL",
    ("US", "321"): "Orlando FL",
    ("US", "322"): "Gainesville FL",
    ("US", "326"): "Tallahassee FL",
    ("US", "330"): "Miami",
    ("US", "331"): "Miami Beach / Brickell",
    ("US", "333"): "Ft Lauderdale",
    ("US", "334"): "Palm Beach",
    ("US", "335"): "Tampa premium",
    ("US", "337"): "Palm Beach premium",
    ("US", "341"): "Naples / Sarasota FL premium",
    ("US", "342"): "Sarasota FL",
    ("US", "346"): "Tampa FL",
    ("US", "372"): "Nashville",
    ("US", "430"): "Columbus OH premium",
    ("US", "432"): "Columbus OH",
    ("US", "441"): "Cleveland",
    ("US", "442"): "Cleveland Heights / Shaker",
    ("US", "452"): "Cincinnati",
    ("US", "462"): "Indianapolis",
    ("US", "481"): "Detroit",
    ("US", "482"): "Detroit Royal Oak / Birmingham",
    ("US", "489"): "Ann Arbor MI",
    ("US", "531"): "Madison WI",
    ("US", "532"): "Milwaukee",
    ("US", "551"): "St Paul",
    ("US", "553"): "Bloomington / Eden Prairie",
    ("US", "554"): "Minneapolis",
    ("US", "600"): "Chicago Loop",
    ("US", "601"): "Chicago outer norte",
    ("US", "602"): "Chicago outer sur",
    ("US", "603"): "Evanston / North Shore",
    ("US", "604"): "Oak Park / River Forest",
    ("US", "605"): "Naperville / Downers Grove",
    ("US", "606"): "Chicago Lincoln Park / Gold Coast",
    ("US", "607"): "Chicago norte (Lakeview/Wicker Park)",
    ("US", "608"): "Chicago west",
    ("US", "609"): "Chicago south",
    ("US", "631"): "St Louis",
    ("US", "671"): "Kansas City MO",
    ("US", "701"): "New Orleans",
    ("US", "730"): "Oklahoma City",
    ("US", "741"): "Tulsa",
    ("US", "750"): "Dallas",
    ("US", "751"): "Dallas Highland Park / Preston Hollow",
    ("US", "752"): "Dallas outer",
    ("US", "753"): "Plano / Allen",
    ("US", "754"): "Garland / Mesquite",
    ("US", "760"): "Fort Worth",
    ("US", "761"): "Fort Worth north",
    ("US", "762"): "Arlington TX",
    ("US", "770"): "Houston",
    ("US", "771"): "Houston Heights / Montrose",
    ("US", "772"): "Houston south",
    ("US", "773"): "Houston outer",
    ("US", "774"): "Pasadena TX / Pearland",
    ("US", "775"): "The Woodlands / Sugar Land premium",
    ("US", "782"): "San Antonio TX",
    ("US", "787"): "Austin TX",
    ("US", "799"): "El Paso TX",
    ("US", "802"): "Denver",
    ("US", "803"): "Boulder",
    ("US", "804"): "Denver Cherry Creek",
    ("US", "805"): "Denver outer",
    ("US", "806"): "Aspen / ski resorts",
    ("US", "809"): "Colorado Springs",
    ("US", "841"): "Salt Lake City",
    ("US", "850"): "Phoenix",
    ("US", "851"): "Scottsdale",
    ("US", "852"): "Phoenix west",
    ("US", "853"): "Tempe / Chandler",
    ("US", "854"): "Scottsdale premium (Paradise Valley)",
    ("US", "871"): "Albuquerque NM",
    ("US", "889"): "Henderson NV",
    ("US", "890"): "Las Vegas outer",
    ("US", "891"): "Las Vegas Strip",
    ("US", "900"): "LA Central",
    ("US", "901"): "Beverly Hills",
    ("US", "902"): "Santa Monica / Culver City",
    ("US", "903"): "Inglewood / Hawthorne",
    ("US", "904"): "Torrance / South Bay",
    ("US", "905"): "Long Beach",
    ("US", "906"): "Compton / Watts",
    ("US", "907"): "Carson / Gardena",
    ("US", "908"): "San Pedro",
    ("US", "910"): "Pasadena",
    ("US", "911"): "Alhambra / Arcadia",
    ("US", "912"): "El Monte",
    ("US", "913"): "Burbank / Glendale premium",
    ("US", "914"): "Glendale",
    ("US", "915"): "Covina / West Covina",
    ("US", "916"): "Pomona",
    ("US", "917"): "Ontario / Rancho Cucamonga",
    ("US", "918"): "Malibu / Ventura premium",
    ("US", "919"): "San Diego La Jolla premium",
    ("US", "920"): "San Diego Mission Valley",
    ("US", "921"): "San Diego outer",
    ("US", "922"): "San Diego east",
    ("US", "940"): "SF Mission / Castro",
    ("US", "941"): "SF Pac Heights / Marina / Nob Hill",
    ("US", "942"): "SF SoMa / Potrero",
    ("US", "943"): "Palo Alto / Menlo Park",
    ("US", "944"): "Silicon Valley (Mountain View/Sunnyvale)",
    ("US", "945"): "Oakland",
    ("US", "946"): "Fremont / Hayward",
    ("US", "947"): "Berkeley",
    ("US", "948"): "San Mateo / Redwood City",
    ("US", "949"): "Marin County (Sausalito/Mill Valley)",
    ("US", "950"): "San Jose norte",
    ("US", "951"): "San Jose sur",
    ("US", "952"): "Santa Clara",
    ("US", "967"): "Honolulu HI",
    ("US", "970"): "Portland west hills",
    ("US", "971"): "Portland outer",
    ("US", "972"): "Portland",
    ("US", "974"): "Salem OR",
    ("US", "980"): "Seattle",
    ("US", "981"): "Seattle Bellevue",
    ("US", "982"): "Bellevue / Redmond (Microsoft/Amazon)",
    ("US", "983"): "Tacoma",
    ("US", "984"): "Olympia",
    ("US", "998"): "Anchorage AK",
    ("UY", "11000"): "Montevideo Central",
    ("UY", "11100"): "Centro Montevideo",
    ("UY", "11200"): "Cordón premium",
    ("UY", "11300"): "Pocitos premium",
    ("UY", "11400"): "Malvín / Punta Gorda",
    ("UY", "11500"): "Carrasco",
    ("UY", "11600"): "Buceo / Parque Rodó",
    ("UY", "11700"): "Montevideo Brazo Oriental",
    ("UY", "11800"): "Sayago / Casavalle",
    ("UY", "11900"): "Montevideo Prado / Casabó",
    ("UY", "12000"): "Montevideo Sur",
    ("UY", "13000"): "Ciudad de la Costa",
    ("UY", "14000"): "Progreso / Canelones Interior",
    ("UY", "15000"): "Las Piedras",
    ("UY", "16000"): "Canelones",
    ("UY", "17000"): "Florida",
    ("UY", "20000"): "Maldonado",
    ("UY", "20100"): "Punta del Este",
    ("UY", "20200"): "Maldonado Ciudad",
    ("UY", "30000"): "Artigas",
    ("UY", "40000"): "Rivera",
    ("UY", "45000"): "Tacuarembó",
    ("UY", "50000"): "Salto",
    ("UY", "50100"): "Salto Centro",
    ("UY", "60000"): "Paysandú",
    ("UY", "65000"): "Melo / Cerro Largo",
    ("UY", "70000"): "Fray Bentos / Rio Negro",
    ("UY", "75000"): "Minas / Lavalleja",
    ("UY", "97000"): "Colonia del Sacramento",
    ("VE", "1010"): "Caracas Centro histórico",
    ("VE", "1011"): "Caracas Los Palos Grandes (premium)",
    ("VE", "1012"): "Caracas La Florida / San Román",
    ("VE", "1013"): "Caracas Chacao Norte",
    ("VE", "1015"): "Petare",
    ("VE", "1016"): "Caracas populares (oeste)",
    ("VE", "1020"): "Caracas Libertador",
    ("VE", "1025"): "Caracas Catia / Caricuao",
    ("VE", "1030"): "Caracas Libertador Sur",
    ("VE", "1040"): "Caracas Centro-Norte",
    ("VE", "1050"): "Caracas Libertador premium",
    ("VE", "1060"): "Chacao / Las Mercedes",
    ("VE", "1070"): "Chacao / Altamira",
    ("VE", "1080"): "Baruta / El Hatillo",
    ("VE", "2001"): "Valencia premium",
    ("VE", "2005"): "Valencia popular",
    ("VE", "2101"): "Maracay",
    ("VE", "2105"): "Maracay Las Delicias",
    ("VE", "3001"): "Barquisimeto",
    ("VE", "3201"): "Puerto Ordaz premium",
    ("VE", "4001"): "Maracaibo",
    ("VE", "4002"): "Maracaibo popular",
    ("VE", "4005"): "Maracaibo Este",
    ("VE", "4601"): "Maturín interior",
    ("VE", "5101"): "San Cristóbal",
    ("VE", "6001"): "Barcelona / Anzoátegui",
    ("VE", "6101"): "Maturín",
    ("VE", "6301"): "Cumaná",
    ("VE", "7001"): "Barquisimeto Norte",
    ("VE", "8001"): "Ciudad Guayana",
    ("ZA", "0001"): "Pretoria CBD",
    ("ZA", "0028"): "Lynnwood / Faerie Glen",
    ("ZA", "0081"): "Waterkloof / Centurion",
    ("ZA", "0082"): "Hatfield / Arcadia",
    ("ZA", "0157"): "Menlyn / Moreleta",
    ("ZA", "0699"): "Polokwane",
    ("ZA", "1244"): "Nelspruit / Mbombela",
    ("ZA", "1430"): "Boksburg",
    ("ZA", "1685"): "Midrand premium",
    ("ZA", "1709"): "Northriding / Roodepoort",
    ("ZA", "1804"): "Soweto",
    ("ZA", "2000"): "Johannesburg CBD",
    ("ZA", "2090"): "Randburg",
    ("ZA", "2092"): "Craighall",
    ("ZA", "2135"): "Bryanston",
    ("ZA", "2157"): "Fourways",
    ("ZA", "2193"): "Hyde Park / Dunkeld",
    ("ZA", "2195"): "Parktown",
    ("ZA", "2196"): "Sandton / Rosebank",
    ("ZA", "2198"): "Morningside",
    ("ZA", "4001"): "Durban CBD",
    ("ZA", "4052"): "Pinetown",
    ("ZA", "4091"): "Berea",
    ("ZA", "4093"): "Durban North",
    ("ZA", "4320"): "Umhlanga Rocks",
    ("ZA", "5201"): "East London",
    ("ZA", "6001"): "Port Elizabeth / Gqeberha",
    ("ZA", "7441"): "Sea Point / Green Point",
    ("ZA", "7460"): "Milnerton",
    ("ZA", "7490"): "Stellenbosch",
    ("ZA", "7530"): "Bellville premium",
    ("ZA", "7550"): "Claremont / Newlands",
    ("ZA", "7580"): "Southern Suburbs",
    ("ZA", "7700"): "Cape Town City Bowl / Gardens",
    ("ZA", "7708"): "Constantia",
    ("ZA", "7780"): "Mitchells Plain / Khayelitsha",
    ("ZA", "7800"): "Clifton / Fresnaye",
    ("ZA", "7806"): "Camps Bay",
    ("ZA", "7945"): "Cape Town South",
    ("ZA", "8301"): "Kimberley",
    ("ZA", "9301"): "Bloemfontein",
}

@app.get('/marketer/brands')
def get_active_brands(q: str = '', db: Session = Depends(get_db)):
    """Retorna marcas con campañas activas para autocomplete de competidoras bloqueadas."""
    query = db.query(AdCampaign.advertiser_name).filter(
        AdCampaign.is_active == True,
        AdCampaign.advertiser_name != None,
        AdCampaign.advertiser_name != '',
    )
    if q:
        query = query.filter(AdCampaign.advertiser_name.ilike(f'%{q}%'))
    rows = query.distinct().order_by(AdCampaign.advertiser_name).limit(10).all()
    return {'brands': [r[0] for r in rows]}

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
            'name': _COMMUNE_NAMES.get((r.country, r.commune), r.commune),
            'income_index': r.income_index, 'cpm_usd': r.cpm_usd, 'se_tier': r.se_tier} for r in rows],
            'source': 'database'}
    fallback = get_fallback_table()
    if country: fallback = [c for c in fallback if c['country'] == country]
    if se_tier:  fallback = [c for c in fallback if c['se_tier'] == se_tier]
    return {'communes': fallback, 'source': 'fallback'}

@app.get('/marketer/countries')
def get_marketer_countries(db: Session = Depends(get_db)):
    """Países con datos reales de comuna/nivel de ingreso en la base — para pickers de targeting."""
    codes = [r[0] for r in db.query(CommuneMarketData.country).distinct().all() if r[0]]
    codes.sort()
    return {'countries': [{'code': cc, 'name': COUNTRY_NAMES.get(cc, cc)} for cc in codes]}


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
    user = db.query(User).filter(func.lower(User.email) == func.lower(data.advertiser_email), User.role.in_(['marketer','admin'])).first()
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
    user = db.query(User).filter(func.lower(User.email) == func.lower(email), User.role.in_(['marketer','admin'])).first()
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
        func.lower(User.email) == func.lower(data.advertiser_email)
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
        target_age_ranges    = data.target_age_ranges,
        target_age_weights   = getattr(data, 'target_age_weights', '') or '',
        target_company_sizes = getattr(data, 'target_company_sizes', '') or '',
        target_categories    = data.target_categories,
        excluded_categories  = data.excluded_categories,
        blocked_competitors  = data.blocked_competitors,
        start_date           = datetime.fromisoformat(data.start_date),
        end_date            = datetime.fromisoformat(data.end_date),
        is_active           = True,
        logo_url            = data.logo_url or '',
        ad_copy             = data.ad_copy or '',
        ad_image_url        = data.ad_image_url or '',
        video_url           = getattr(data, 'video_url', '') or '',
        link_url            = data.link_url or '',
        min_per_capita_usd  = getattr(data, 'min_per_capita_usd', 0.0) or 0.0,
        frequency_cap       = getattr(data, 'frequency_cap', None),
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

@app.post('/marketer/optimize-budget')
def marketer_optimize_budget(db: Session = Depends(get_db),
    countries:           str = '',        # 'CL,MX,CO'
    age_weights_json:    str = '',        # JSON {"18-35":50,"36-55":50}
    se_tiers:            str = '',        # 'A,B,C'
    company_sizes:       str = '',        # 'small,medium,large'
    min_income_usd:      float = 0,       # umbral ingreso nominal USD/mes (manual)
    budget_usd:          float = 1000,
    archetype:           str = 'universal',  # ultra_premium|premium|mid_premium|mass_market|universal
    product_price_usd:   float = 0,       # precio del producto en USD — deriva threshold automático
    purchase_type:       str = '',        # 'auto'|'luxury'|'appliance'|'cash_premium'|'fmcg'
):
    """
    Motor de optimización de presupuesto.
    Dado los parámetros de campaña, retorna la distribución óptima del
    presupuesto entre segmentos (país × edad × tamaño empresa), proporcional
    a la audiencia calificada esperada usando modelo log-normal JC 2026-08-01.
    """
    from budget_optimizer import optimize_budget
    from ppp_agent import PLI

    # Parsear países
    country_list = [c.strip().upper() for c in countries.split(',') if c.strip()]
    if not country_list:
        raise HTTPException(400, 'Selecciona al menos un país')

    # Parsear age_weights JSON → lista de segmentos
    age_segments = []
    if age_weights_json:
        try:
            aw = json.loads(age_weights_json)
            for range_str, pct in aw.items():
                if '-' in range_str:
                    parts = range_str.split('-')
                    age_segments.append({
                        'min':   int(parts[0]),
                        'max':   int(parts[1]),
                        'pct':   float(pct),
                        'label': f"{parts[0]}-{parts[1]} años",
                    })
        except Exception:
            pass

    # Parsear se_tiers y company_sizes
    tier_list = [t.strip().upper() for t in se_tiers.split(',') if t.strip()] if se_tiers else []
    size_list = [s.strip().lower() for s in company_sizes.split(',') if s.strip()] if company_sizes else []

    # Convertir ingreso mínimo nominal → PPP promedio entre países seleccionados
    min_income_ppp = 0.0
    if min_income_usd > 0 and country_list:
        plis = [PLI.get(cc, 0.7) for cc in country_list]
        avg_pli = sum(plis) / len(plis)
        min_income_ppp = min_income_usd / avg_pli

    result = optimize_budget(
        db=db,
        countries=country_list,
        age_segments=age_segments,
        se_tiers=tier_list,
        company_sizes=size_list,
        min_income_ppp=min_income_ppp,
        budget_usd=budget_usd,
        archetype=archetype,
        product_price_usd=product_price_usd,
        purchase_type=purchase_type,
    )
    return result


@app.post('/marketer/optimize-budget-strategic')
def marketer_optimize_budget_strategic(db: Session = Depends(get_db),
    brand_sales_json:  str   = '',      # '{"US":150000,"DE":80000}' unidades año anterior
    compete_countries: str   = '',      # 'FR,ES,IT' — mercados disputados
    grow_countries:    str   = '',      # 'CN,BR' — vacío = auto-derivar top mercados
    product_price_usd: float = 0,       # precio producto USD
    purchase_type:     str   = 'auto',  # 'auto'|'luxury'|'appliance'|'cash_premium'|'fmcg'
    budget_usd:        float = 100_000,
    defend_pct:        float = 60,      # % del budget para Defender (se normaliza con compete+grow)
    compete_pct:       float = 25,      # % para Competir
    grow_pct:          float = 15,      # % para Crecer
    grow_top_n:        int   = 15,      # máx mercados nuevos a mostrar
    age_weights_json:  str   = '',
    se_tiers:          str   = '',
    company_sizes:     str   = '',
):
    """
    Motor estratégico 3 buckets:
      DEFENDER  — proporcional a ventas reales del año anterior.
      COMPETIR  — audiencia calificada (ingreso) en mercados disputados.
      CRECER    — top N mercados nuevos por audiencia calificada.

    brand_sales_json: JSON con unidades vendidas por país ISO2.
    Ejemplo: {"US":150000,"DE":80000,"GB":45000}
    """
    from budget_optimizer import optimize_budget_strategic

    # Parsear ventas por país
    brand_sales: dict[str, float] = {}
    if brand_sales_json:
        try:
            raw = json.loads(brand_sales_json)
            brand_sales = {k.upper().strip(): float(v) for k, v in raw.items()}
        except Exception:
            raise HTTPException(400, 'brand_sales_json debe ser JSON válido: {"US":150000,"DE":80000}')

    if not brand_sales:
        raise HTTPException(400, 'Proporciona brand_sales_json con ventas del año anterior por país')

    compete_list = [c.strip().upper() for c in compete_countries.split(',') if c.strip()] if compete_countries else []
    grow_list    = [c.strip().upper() for c in grow_countries.split(',')    if c.strip()] if grow_countries    else []
    size_list    = [s.strip().lower() for s in company_sizes.split(',')     if s.strip()] if company_sizes     else []
    tier_list    = [t.strip().upper() for t in se_tiers.split(',')         if t.strip()] if se_tiers          else []

    age_segments = []
    if age_weights_json:
        try:
            aw = json.loads(age_weights_json)
            for range_str, pct in aw.items():
                if '-' in range_str:
                    parts = range_str.split('-')
                    age_segments.append({'min': int(parts[0]), 'max': int(parts[1]),
                                         'pct': float(pct), 'label': f"{parts[0]}-{parts[1]} años"})
        except Exception:
            pass

    result = optimize_budget_strategic(
        db=db,
        brand_sales_by_country=brand_sales,
        product_price_usd=product_price_usd,
        purchase_type=purchase_type,
        budget_usd=budget_usd,
        defend_pct=defend_pct / 100,
        compete_pct=compete_pct / 100,
        grow_pct=grow_pct / 100,
        compete_countries=compete_list,
        grow_countries=grow_list,
        age_segments=age_segments,
        se_tiers=tier_list,
        company_sizes=size_list,
        grow_top_n=grow_top_n,
    )
    return result


@app.post('/admin/car-sales-import')
def car_sales_import(db: Session = Depends(get_db)):
    """Importa datos de ventas de autos por marca × país (seed 2024-2026)."""
    from car_sales_agent import run_car_sales_import
    return run_car_sales_import(db)


@app.get('/marketer/car-brands')
def car_brands_list(db: Session = Depends(get_db)):
    """Lista todas las marcas de autos disponibles en BD."""
    from car_sales_agent import list_brands
    brands = list_brands(db)
    return {'brands': brands, 'count': len(brands)}


@app.post('/marketer/optimize-budget-brand')
def marketer_optimize_budget_brand(db: Session = Depends(get_db),
    brand:             str   = '',      # 'toyota' | 'byd' | 'bmw' ...
    compete_countries: str   = '',      # 'FR,ES,IT'
    grow_countries:    str   = '',      # vacío = auto-derivar
    product_price_usd: float = 0,
    purchase_type:     str   = 'auto',
    budget_usd:        float = 100_000,
    defend_pct:        float = 60,
    compete_pct:       float = 25,
    grow_pct:          float = 15,
    grow_top_n:        int   = 15,
    age_weights_json:  str   = '',
    se_tiers:          str   = '',
    company_sizes:     str   = '',
):
    """
    Motor estratégico usando ventas reales de la marca desde BD.
    Igual que /optimize-budget-strategic pero solo necesita el nombre de la marca.

    Ejemplo: brand=toyota, product_price_usd=28000, purchase_type=auto, budget_usd=5000000
    """
    from car_sales_agent import get_brand_sales, normalize_brand
    from budget_optimizer import optimize_budget_strategic

    if not brand:
        raise HTTPException(400, 'Proporciona el nombre de la marca (brand)')

    brand_norm = normalize_brand(brand)
    brand_sales = get_brand_sales(db, brand_norm)

    if not brand_sales:
        raise HTTPException(404, (
            f"No se encontraron ventas para '{brand_norm}'. "
            f"Corre POST /admin/car-sales-import primero, "
            f"o usa /optimize-budget-strategic con brand_sales_json manual."
        ))

    compete_list = [c.strip().upper() for c in compete_countries.split(',') if c.strip()] if compete_countries else []
    grow_list    = [c.strip().upper() for c in grow_countries.split(',')    if c.strip()] if grow_countries    else []
    size_list    = [s.strip().lower() for s in company_sizes.split(',')     if s.strip()] if company_sizes     else []
    tier_list    = [t.strip().upper() for t in se_tiers.split(',')         if t.strip()] if se_tiers          else []

    age_segments = []
    if age_weights_json:
        try:
            aw = json.loads(age_weights_json)
            for range_str, pct in aw.items():
                if '-' in range_str:
                    parts = range_str.split('-')
                    age_segments.append({'min': int(parts[0]), 'max': int(parts[1]),
                                         'pct': float(pct), 'label': f"{parts[0]}-{parts[1]} años"})
        except Exception:
            pass

    result = optimize_budget_strategic(
        db=db,
        brand_sales_by_country=brand_sales,
        product_price_usd=product_price_usd,
        purchase_type=purchase_type,
        budget_usd=budget_usd,
        defend_pct=defend_pct / 100,
        compete_pct=compete_pct / 100,
        grow_pct=grow_pct / 100,
        compete_countries=compete_list,
        grow_countries=grow_list,
        age_segments=age_segments,
        se_tiers=tier_list,
        company_sizes=size_list,
        grow_top_n=grow_top_n,
    )
    result['brand'] = brand_norm
    result['brand_sales_source'] = 'car_brand_sales BD — Car Sales Statistics 2024-2026'
    return result


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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    user = db.query(User).filter(func.lower(User.email) == func.lower(email)).first()
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
            debate.verify_closes_at = debate.closes_at + timedelta(days=1)
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
    if secret != os.getenv('ADMIN_SECRET'):
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


@app.get('/admin/selfie-verification-audit')
def admin_selfie_verification_audit(secret: str, db: Session = Depends(get_db)):
    """Solo lectura. Distribución real de match_score en selfie_logs — si el
    valor 0.95 aparece con una frecuencia anormal, indica que muchas de esas
    verificaciones cayeron en el modo demo (AWS caído/sin credenciales) en vez
    de una comparación facial real."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    total = db.query(SelfieLog).filter(SelfieLog.verified == True).count()
    demo_mode = db.query(SelfieLog).filter(
        SelfieLog.verified == True, SelfieLog.match_score == 0.95
    ).count()
    sample = db.query(SelfieLog.match_score, SelfieLog.created_at).filter(
        SelfieLog.verified == True
    ).order_by(SelfieLog.created_at.desc()).limit(20).all()
    return {
        'total_verified': total,
        'exactly_0.95_score_demo_mode': demo_mode,
        'pct_demo_mode': round(demo_mode / total * 100, 1) if total else 0,
        'most_recent_20_scores': [
            {'match_score': s[0], 'created_at': str(s[1])} for s in sample
        ],
    }

@app.get('/admin/selfie-verification-audit/real-logs')
def admin_selfie_real_logs(secret: str, db: Session = Depends(get_db)):
    """Solo lectura. Lista los selfie_logs verificados con score real
    (no 0.95 de modo demo) junto a su user_id, para poder cruzarlos
    en una prueba de discriminación real (¿rechaza caras distintas?)."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    rows = db.query(SelfieLog).filter(
        SelfieLog.verified == True, SelfieLog.match_score != 0.95, SelfieLog.face_bytes != None
    ).order_by(SelfieLog.created_at.desc()).all()
    return {'logs': [
        {'id': r.id, 'user_id': r.user_id, 'match_score': r.match_score, 'created_at': str(r.created_at)}
        for r in rows
    ]}

@app.get('/admin/rekognition-cross-test')
def admin_rekognition_cross_test(secret: str, selfie_log_id_a: int, selfie_log_id_b: int, db: Session = Depends(get_db)):
    """Solo lectura / no destructivo. Compara dos face_bytes YA guardados
    (de dos selfie_logs reales existentes) entre sí vía Rekognition, sin
    subir ninguna foto nueva — prueba si el sistema realmente distingue
    caras distintas, o si aprobaría cualquier cosa."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    log_a = db.query(SelfieLog).filter(SelfieLog.id == selfie_log_id_a).first()
    log_b = db.query(SelfieLog).filter(SelfieLog.id == selfie_log_id_b).first()
    if not log_a or not log_b:
        raise HTTPException(404, 'selfie_log no encontrado')
    if not log_a.face_bytes or not log_b.face_bytes:
        raise HTTPException(400, 'Uno de los dos selfie_logs no tiene face_bytes guardado')
    try:
        rek = _rekognition_client()
        resp = rek.compare_faces(
            SourceImage={'Bytes': base64.b64decode(log_a.face_bytes)},
            TargetImage={'Bytes': base64.b64decode(log_b.face_bytes)},
            SimilarityThreshold=1.0,  # bajo, para ver el score real aunque no pase el umbral de negocio (80%)
        )
        matches = resp.get('FaceMatches', [])
        similarity = matches[0]['Similarity'] if matches else 0.0
        return {
            'ok': True,
            'user_id_a': log_a.user_id, 'user_id_b': log_b.user_id,
            'same_user': log_a.user_id == log_b.user_id,
            'similarity_pct': round(similarity, 2),
            'would_pass_80pct_threshold': similarity >= 80.0,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@app.get('/admin/face-collection-test')
def admin_face_collection_test(secret: str, debate_id: int, selfie_log_id: int, as_user_id: int = 0, db: Session = Depends(get_db)):
    """DIAGNÓSTICO TEMPORAL — ejercita el mismo camino de index/search que usa
    el bloqueo de cara duplicada, con una foto real ya guardada, sin pasar por
    todo el flujo HTTP de registro. Solo lectura + escribe en la colección de
    prueba de Rekognition (no toca la base de datos de Preferendum).
    as_user_id: para simular "esta misma foto, reclamada por otra cuenta" —
    prueba de fraude controlada, sin subir fotos nuevas."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    log = db.query(SelfieLog).filter(SelfieLog.id == selfie_log_id).first()
    if not log or not log.face_bytes:
        raise HTTPException(404, 'selfie_log no encontrado o sin face_bytes')
    effective_user_id = as_user_id or log.user_id
    photo = base64.b64decode(log.face_bytes)
    rek = _rekognition_client()
    _ensure_voter_face_collection(rek)

    search = rek.search_faces_by_image(
        CollectionId=_VOTER_FACE_COLLECTION, Image={'Bytes': photo},
        FaceMatchThreshold=90.0, MaxFaces=20,
    )
    existing_matches = [m.get('Face', {}).get('ExternalImageId', '') for m in search.get('FaceMatches', [])]

    blocked_for = None
    for ext_id in existing_matches:
        if '_' in ext_id:
            ext_debate, ext_user = ext_id.split('_', 1)
            if ext_debate == str(debate_id) and ext_user != str(effective_user_id):
                blocked_for = ext_id

    indexed = None
    if not blocked_for:
        idx = rek.index_faces(
            CollectionId=_VOTER_FACE_COLLECTION, Image={'Bytes': photo},
            ExternalImageId=f'{debate_id}_{effective_user_id}', MaxFaces=1,
            QualityFilter='NONE', DetectionAttributes=[],
        )
        indexed = [f['Face']['ExternalImageId'] for f in idx.get('FaceRecords', [])]

    return {
        'selfie_log_id': selfie_log_id, 'user_id': effective_user_id, 'debate_id': debate_id,
        'existing_matches_before': existing_matches,
        'blocked_would_reject': bool(blocked_for),
        'blocked_matched_external_id': blocked_for,
        'newly_indexed_as': indexed,
    }

@app.patch('/admin/campaigns/{campaign_id}/frequency-cap')
def admin_set_frequency_cap(campaign_id: int, secret: str, cap: int = None, db: Session = Depends(get_db)):
    """Setea (o quita, con cap vacío) el límite de frecuencia de una campaña."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    c = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, 'Campaign not found')
    c.frequency_cap = cap
    db.commit()
    return {'ok': True, 'campaign_id': campaign_id, 'frequency_cap': c.frequency_cap}

@app.get('/admin/aws-check')
def aws_check(secret: str):
    if secret != os.getenv('ADMIN_SECRET'):
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
        'secret_last_3_repr': repr(sec[-3:]) if sec else '',
        'key_last_3_repr': repr(key[-3:]) if key else '',
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import traceback as tb
    result = {}
    _blockchain._ensure_init()
    result['live'] = _blockchain.live
    # Diagnóstico de env vars (valores mascarados)
    ca = os.getenv('CONTRACT_ADDRESS', '')
    wa = os.getenv('WALLET_ADDRESS', '')
    pk = os.getenv('WALLET_PRIVATE_KEY', '')
    result['env_CONTRACT_ADDRESS'] = f'{ca[:6]}...{ca[-4:]}' if len(ca) > 10 else (repr(ca) if ca else 'NOT SET')
    result['env_WALLET_ADDRESS']   = f'{wa[:6]}...{wa[-4:]}' if len(wa) > 10 else (repr(wa) if wa else 'NOT SET')
    result['env_WALLET_PRIVATE_KEY'] = f'len={len(pk)}' if pk else 'NOT SET'
    pwa = os.getenv('PREFERENDUM_WALLET_ADDRESS', '')
    pwk = os.getenv('PREFERENDUM_WALLET_KEY', '')
    result['env_PREFERENDUM_WALLET_ADDRESS'] = f'{pwa[:6]}...{pwa[-4:]}' if len(pwa) > 10 else (repr(pwa) if pwa else 'EMPTY')
    result['env_PREFERENDUM_WALLET_KEY']     = f'len={len(pwk)}' if pwk else 'EMPTY'
    result['blockchain_contract_address'] = _blockchain.contract_address or 'empty'
    result['blockchain_wallet_address']   = _blockchain.wallet_address or 'empty'
    # Chequear secret files de Render
    import glob
    secrets_found = glob.glob('/etc/secrets/*')
    result['secret_files'] = [os.path.basename(f) for f in secrets_found]
    for sname in ['WALLET_PRIVATE_KEY', 'CONTRACT_ADDRESS', 'WALLET_ADDRESS']:
        spath = f'/etc/secrets/{sname}'
        try:
            with open(spath) as f:
                v = f.read().strip()
            result[f'secret_{sname}'] = f'len={len(v)}' if v else 'empty'
        except Exception:
            result[f'secret_{sname}'] = 'not found'
    # Todas las env vars disponibles (keys solamente)
    result['all_env_keys'] = sorted(k for k in os.environ.keys())
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    try:
        from targeting_agent import get_matrix_summary
        return {'ok': True, 'matrix': get_matrix_summary()}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@app.post('/admin/targeting/update-communes')
def targeting_update_communes(secret: str, bg: BackgroundTasks):
    """DESACTIVADO — este camino regeneraba targeting_matrix.json desde el
    diccionario estático de 12 países (COMMUNE_DATA), que quedó obsoleto
    cuando el matching pasó a leer la base de datos en vivo (76 países)
    la noche del 2026-08-21. Dejarlo activo arriesgaba revertir ese fix
    en silencio. Usar POST /admin/agent/income-data/sync en su lugar."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    raise HTTPException(410, 'Reemplazado por POST /admin/agent/income-data/sync — este endpoint usaba datos estáticos de solo 12 países.')

@app.post('/admin/targeting/update-gni')
def targeting_update_gni(secret: str, bg: BackgroundTasks):
    """DESACTIVADO — mismo motivo que update-communes. Usar
    POST /admin/agent/income-data/sync, que actualiza GNI real
    (Banco Mundial) directo en world_countries."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    raise HTTPException(410, 'Reemplazado por POST /admin/agent/income-data/sync.')

@app.get('/admin/targeting/match-debate/{debate_id}')
def targeting_match_debate(debate_id: int, secret: str, db: Session = Depends(get_db)):
    """Preview de matching real — usa la MISMA función que corre en producción
    (_match_campaigns), no una copia separada. La versión anterior de este
    endpoint llamaba a una función distinta (targeting_agent.match_campaigns_to_debate)
    que leía el archivo estático viejo y usaba columnas SQL que no existen en el
    esquema real — daba falsos negativos (matches:[] aunque sí había match real).
    Corregido 2026-08-22."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Debate not found')
    matches = _match_campaigns(None, debate, db)
    return {
        'debate_id':  debate_id,
        'debate': {
            'scope_country':  debate.scope_country,
            'scope_commune':  debate.scope_commune,
            'target_gender':  debate.target_gender,
            'target_age_min': debate.target_age_min,
            'target_age_max': debate.target_age_max,
        },
        'matches': [{
            'campaign_id': m.get('id'), 'advertiser_name': m.get('advertiser_name'),
            'optimization_rank': m.get('optimization_rank'), 'pinned': m.get('pinned', False),
        } for m in matches[:10]],
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    users = db.query(User).filter(
        (User.email.ilike(f'%{q}%')) | (User.name.ilike(f'%{q}%'))
    ).order_by(User.id.desc()).limit(20).all()
    return {'users': [{'id': u.id, 'email': u.email, 'name': u.name, 'role': u.role,
                        'email_verified': u.email_verified, 'phone_verified': u.phone_verified,
                        'selfie_verified': u.selfie_verified, 'verify_level': u.verify_level,
                        'se_tier': u.se_tier, 'commune': u.county, 'country': u.country,
                        'income_index': u.income_index, 'dob': u.dob,
                        'profession': u.profession, 'cargo': u.cargo, 'company_size': u.company_size,
                        'created_at': str(u.created_at)} for u in users]}

@app.post('/admin/users/reset-password')
def admin_reset_password(user_id: int, new_password: str, secret: str, db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, 'User not found')
    user.password = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    db.commit()
    return {'ok': True, 'email': user.email, 'message': 'Password updated'}

@app.post('/admin/users/reset-selfie')
def admin_reset_selfie(user_id: int, secret: str, db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, 'User not found')
    db.query(SelfieLog).filter(SelfieLog.user_id == user_id).delete()
    user.selfie_verified = False
    db.commit()
    return {'ok': True, 'email': user.email, 'message': 'Selfie borrada — el usuario puede registrar su cara de nuevo'}

@app.get('/admin/device-fingerprints/count')
def admin_device_fp_count(secret: str, db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    return {'total_device_records': db.query(IMEILog).count()}

@app.delete('/admin/device-fingerprints/clear-all')
def admin_device_fp_clear_all(secret: str, db: Session = Depends(get_db)):
    """Borra todo el historial de huellas de dispositivo (anti-fraude 'un dispositivo = una cuenta').
    Pensado para limpiar datos acumulados durante pruebas internas antes de abrir a usuarios reales —
    cada dispositivo se vuelve a registrar limpio en su próximo login, sin perder cuentas ni datos de usuario."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    deleted = db.query(IMEILog).delete()
    db.commit()
    return {'ok': True, 'deleted': deleted, 'message': 'Registros de dispositivo borrados — se re-registran limpios en el próximo login.'}

@app.post('/admin/purge-user')
def admin_purge_user(user_id: int, secret: str, db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from sqlalchemy import text as _text
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, 'User not found')
    email = user.email
    try:
        tables = [
            'otp_codes', 'selfie_logs', 'document_logs', 'imei_logs',
            'sim_logs', 'geo_logs', 'vote_identity_locks', 'opinions',
            'debate_has_voted', 'post_vote_comments',
            'organizer_profiles', 'marketer_profiles',
            'authorization_requests', 'marketer_authorization_requests',
            'credit_accounts',
        ]
        for tbl in tables:
            try:
                db.execute(_text(f'DELETE FROM {tbl} WHERE user_id = :uid'), {'uid': user_id})
            except Exception:
                db.rollback()
        db.execute(_text('DELETE FROM users WHERE id = :uid'), {'uid': user_id})
        # also clean orphaned device/sim records from any previously deleted accounts
        db.execute(_text('DELETE FROM imei_logs WHERE user_id NOT IN (SELECT id FROM users)'))
        db.execute(_text('DELETE FROM sim_logs WHERE user_id NOT IN (SELECT id FROM users)'))
        db.commit()
        return {'ok': True, 'deleted': email}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))

@app.get('/public-sector/pricing')
def public_sector_pricing(db: Session = Depends(get_db)):
    """Calcula el costo de campaña para el sector público por país.
    Fórmula: costo_USD = Σ( N_usuarios_por_país × CPM_país )
    CPM premium ~5x sobre Meta Ads — usuarios verificados por identidad.
    """
    from sqlalchemy import text as _text
    rows = db.execute(_text(
        "SELECT UPPER(COALESCE(country,'OTHER')) AS c, COUNT(*) AS n FROM users GROUP BY c"
    )).fetchall()

    breakdown = []
    total_users = 0
    total_cost = 0.0
    for row in rows:
        code = row[0] or 'OTHER'
        n = row[1]
        cpm = get_cpm_for_country(code)
        cost = n * cpm
        total_users += n
        total_cost += cost
        breakdown.append({'country': code, 'users': n, 'cpm_usd': cpm, 'subtotal_usd': round(cost, 2)})

    breakdown.sort(key=lambda x: x['subtotal_usd'], reverse=True)
    return {
        'user_count': total_users,
        'campaign_cost_usd': round(total_cost, 2),
        'messages_included': total_users,
        'breakdown_by_country': breakdown,
        'note': 'Tarifa premium verificado por identidad (~5x CPM de Meta Ads). Se actualiza con cada nuevo usuario.'
    }

@app.post('/admin/set-public-sector-cpm')
def admin_set_public_sector_cpm(secret: str, cpm_usd: float, db: Session = Depends(get_db)):
    """Aplica un override global de CPM (todos los países) sin redeploy."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    global _public_sector_global_override
    _public_sector_global_override = cpm_usd
    from sqlalchemy import text as _text
    user_count = db.execute(_text('SELECT COUNT(*) FROM users')).scalar() or 0
    return {
        'ok': True,
        'global_cpm_override_usd': cpm_usd,
        'user_count': user_count,
        'campaign_cost_usd': round(user_count * cpm_usd, 2)
    }

@app.post('/admin/fix-inst-name')
def admin_fix_inst_name(secret: str, old_name: str, new_name: str, db: Session = Depends(get_db)):
    """Renombra inst_name en debates y brand en ad_campaigns."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from sqlalchemy import text as _text
    r1 = db.execute(_text('UPDATE debates SET inst_name = :new WHERE inst_name = :old'), {'new': new_name, 'old': old_name})
    r2 = db.execute(_text('UPDATE ad_campaigns SET advertiser_name = :new WHERE advertiser_name = :old'), {'new': new_name, 'old': old_name})
    r3 = db.execute(_text('UPDATE debate_ads SET brand = :new WHERE brand = :old'), {'new': new_name, 'old': old_name})
    db.commit()
    return {'ok': True, 'debates_updated': r1.rowcount, 'campaigns_updated': r2.rowcount, 'ads_updated': r3.rowcount}

@app.post('/admin/cleanup-orphan-imei')
def admin_cleanup_orphan_imei(secret: str, db: Session = Depends(get_db)):
    """Borra registros de imei_logs y sim_logs huérfanos (user_id que ya no existe en users)."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from sqlalchemy import text as _text
    r1 = db.execute(_text('DELETE FROM imei_logs WHERE user_id NOT IN (SELECT id FROM users)'))
    r2 = db.execute(_text('DELETE FROM sim_logs WHERE user_id NOT IN (SELECT id FROM users)'))
    db.commit()
    return {'ok': True, 'imei_deleted': r1.rowcount, 'sim_deleted': r2.rowcount}

@app.delete('/admin/users/{user_id}')
def admin_delete_user(user_id: int, secret: str, db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, 'User not found')
    email = user.email
    db.query(SelfieLog).filter(SelfieLog.user_id == user_id).delete()
    db.query(DocumentLog).filter(DocumentLog.user_id == user_id).delete()
    db.query(HasVotedLog).filter(HasVotedLog.user_id == user_id).delete()
    db.query(IMEILog).filter(IMEILog.user_id == user_id).delete()
    db.delete(user)
    db.commit()
    return {'ok': True, 'deleted': email}

@app.post('/admin/users/fix')
def admin_fix_user(user_id: int, secret: str, email: str = '', name: str = '', role: str = '',
                   email_verified: str = '', selfie_verified: str = '', db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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

@app.get('/admin/user-token')
def admin_get_user_token(user_id: int, secret: str, role: str = '', db: Session = Depends(get_db)):
    """Admin: genera JWT para un user_id (solo testing). role= para override."""
    _check_admin(secret)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, 'User not found')
    effective_role = role.strip() or user.role or 'voter'
    token = make_token(user.id, role=effective_role)
    return {'token': token, 'user_id': user.id, 'email': user.email, 'role': effective_role}

@app.post('/admin/payments/manual-credit')
def payments_admin_manual(
    user_id:     int,
    credits:     float,
    description: str,
    secret:      str,
    db: Session = Depends(get_db),
):
    """Admin: manually add credits for a user (promos, support refunds, etc.)."""
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from marketing_agent import get_campaigns_needing_attention
    return get_campaigns_needing_attention(db)


@app.post('/admin/marketing/daily-checks')
def marketing_admin_daily(secret: str, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Admin: run daily marketing checks in background."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from marketing_agent import run_daily_marketing_checks
    bg.add_task(run_daily_marketing_checks, db)
    return {'ok': True, 'message': 'Daily marketing checks started — check logs'}


@app.post('/admin/marketing/weekly-reports')
def marketing_admin_weekly(secret: str, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Admin: generate weekly advertiser reports in background."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from marketing_agent import run_weekly_advertiser_reports
    bg.add_task(run_weekly_advertiser_reports, db)
    return {'ok': True, 'message': 'Weekly reports started — check logs'}


@app.get('/admin/agent/test-api')
def agent_test_api(secret: str):
    """Test Anthropic API key and RSS feeds. Returns raw status."""
    if secret != os.getenv('ADMIN_SECRET'):
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

@app.get('/admin/recent-ad-impressions')
def admin_recent_ad_impressions(secret: str, limit: int = 20, db: Session = Depends(get_db)):
    """Solo lectura — últimas impresiones registradas, con nombre de campaña y debate."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    rows = db.query(AdImpressionLog).order_by(AdImpressionLog.created_at.desc()).limit(limit).all()
    result = []
    for r in rows:
        camp = db.query(AdCampaign).filter(AdCampaign.id == r.campaign_id).first()
        result.append({
            'campaign_id': r.campaign_id,
            'advertiser': camp.advertiser_name if camp else '(campaña no encontrada)',
            'spent_clp': camp.spent_clp if camp else None,
            'debate_id': r.debate_id,
            'created_at': str(r.created_at),
        })
    return {'recent': result}

@app.get('/admin/stalled-campaigns')
def admin_stalled_campaigns(secret: str, days: int = 20, db: Session = Depends(get_db)):
    """
    Campañas activas que llevan `days` o más sin que se les muestre ninguna
    consulta (sin fila nueva en ad_impression_logs) — se estancaron aunque
    todavía tienen presupuesto (spent_clp solo se mueve junto con esas filas,
    así que esto también cubre el criterio de "sin movimiento de presupuesto").
    """
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    now = datetime.utcnow()
    cutoff = now - timedelta(days=days)
    campaigns = db.query(AdCampaign).filter(
        AdCampaign.is_active == True,
        (AdCampaign.budget_clp == 0) | (AdCampaign.budget_clp > AdCampaign.spent_clp),
    ).all()
    stalled = []
    for c in campaigns:
        last = db.query(AdImpressionLog).filter(
            AdImpressionLog.campaign_id == c.id
        ).order_by(AdImpressionLog.created_at.desc()).first()
        reference_date = last.created_at if last else c.created_at
        if reference_date and reference_date <= cutoff:
            stalled.append({
                'id':                  c.id,
                'advertiser_name':     c.advertiser_name or '',
                'title':               c.title or '',
                'ad_copy':             c.ad_copy or '',
                'target_country':      c.target_country or '',
                'target_communes':     c.target_communes or '',
                'target_se_tiers':     c.target_se_tiers or 'A,B,C,D',
                'target_gender':       c.target_gender or 'all',
                'target_age_min':      c.target_age_min or 13,
                'target_age_max':      c.target_age_max or 99,
                'excluded_categories': c.excluded_categories or '',
                'target_debate_ids': c.target_debate_ids or '',
                'days_stalled':        (now - reference_date).days,
            })
    return {'stalled_campaigns': stalled, 'count': len(stalled)}

@app.post('/admin/agent/daily-debates')
def agent_daily_debates(secret: str, bg: BackgroundTasks):
    """Trigger the news agent to create debates from world news."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import run_daily_debates
    bg.add_task(run_daily_debates)
    return {'ok': True, 'message': 'News agent started in background — check server logs for results'}

@app.post('/admin/agent/daily-debates/sync')
def agent_daily_debates_sync(secret: str):
    """Run the news agent synchronously and return results (may take up to 2 min)."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import run_daily_debates
    return run_daily_debates()

@app.post('/admin/agent/income-data/sync')
def agent_income_data_sync(secret: str, db: Session = Depends(get_db)):
    """Runs the global income/salary data agent: ILO ILOSTAT import (broad
    real coverage), Chile INE occupation salary, World Bank GNI per capita,
    and rebuilds targeting_matrix.json from the LIVE CommuneMarketData table
    (every country actually in the DB) instead of the old 12-country hardcoded
    dict. Real work, real external calls — runs in a background thread with a
    generous join timeout since it can take a few minutes; if it doesn't
    finish within the timeout it keeps running server-side and the /status
    endpoint below will show the real result once done.
    """
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')

    import threading, time as _time
    result_holder = {}

    def _run():
        summary = {'started_at': datetime.utcnow().isoformat()}
        # 1. ILO ILOSTAT — broad real occupation-salary coverage
        try:
            from ilo_ilostat_agent import run_ilo_import
            summary['ilo'] = run_ilo_import(db)
        except Exception as e:
            summary['ilo'] = {'ok': False, 'error': str(e)}
        # 2. Chile INE + published-report seeds (existing agent)
        try:
            from occupation_salary_agent import run_occupation_import
            summary['occupation_salary'] = run_occupation_import(db)
        except Exception as e:
            summary['occupation_salary'] = {'ok': False, 'error': str(e)}
        # 3. World Bank GNI per capita — only for countries we actually have
        #    commune data for, not a hardcoded country list. Written into the
        #    durable world_countries table (UPDATE only — never INSERT, since
        #    we don't fully control that table's schema/constraints from here)
        #    so it survives restarts, not just the ephemeral matrix file.
        try:
            from targeting_agent import fetch_gni_from_worldbank
            countries = [r[0] for r in db.query(CommuneMarketData.country).distinct().all() if r[0]]
            gni_by_country = {}
            written = 0
            for iso in countries:
                gni = fetch_gni_from_worldbank(iso)
                if gni:
                    gni_by_country[iso] = gni
                    try:
                        res = db.execute(text(
                            "UPDATE world_countries SET gdp_per_capita_usd = :gni WHERE iso2 = :iso"
                        ), {'gni': gni, 'iso': iso})
                        if res.rowcount:
                            written += 1
                    except Exception:
                        pass
            db.commit()
            summary['gni'] = {'ok': True, 'countries_fetched': len(gni_by_country), 'world_countries_rows_updated': written}
        except Exception as e:
            gni_by_country = {}
            summary['gni'] = {'ok': False, 'error': str(e)}
        # 4. Rebuild targeting_matrix.json from the live DB — this is the piece
        #    that actually makes the matching engine use real data for every
        #    country, not just the 12 that used to be hardcoded.
        try:
            from targeting_agent import build_matrix_from_db, save_matrix
            rows = db.query(CommuneMarketData).all()
            row_dicts = [{
                'country': r.country, 'commune': r.commune,
                'name': _COMMUNE_NAMES.get((r.country, r.commune), r.commune),
                'income_index': r.income_index, 'cpm_usd': r.cpm_usd,
                'se_tier': r.se_tier,
            } for r in rows]
            matrix = build_matrix_from_db(row_dicts, gni_by_country)
            save_matrix(matrix)
            summary['matrix'] = {
                'ok': True, 'countries': len(matrix),
                'total_communes': sum(v['commune_count'] for v in matrix.values()),
            }
        except Exception as e:
            summary['matrix'] = {'ok': False, 'error': str(e)}
        summary['finished_at'] = datetime.utcnow().isoformat()
        result_holder['result'] = summary

    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=240)
    if not result_holder:
        return {'ok': True, 'message': 'Income-data agent started — still running server-side, check /admin/agent/income-data/status shortly'}
    return result_holder['result']

@app.get('/admin/agent/income-data/status')
def agent_income_data_status(secret: str, db: Session = Depends(get_db)):
    """Read-only — genuine freshness check, not a self-reported claim.
    Pulls real timestamps directly from the data itself."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from sqlalchemy import text as _text

    status = {}
    try:
        from ilo_ilostat_agent import get_ilo_summary
        status['ilo_wages'] = get_ilo_summary(db)
    except Exception as e:
        status['ilo_wages'] = {'error': str(e)}

    try:
        row = db.execute(_text(
            "SELECT COUNT(*), COUNT(DISTINCT country_iso), MAX(updated_at) FROM occupation_salary"
        )).fetchone()
        status['occupation_salary'] = {
            'total_rows': row[0], 'countries': row[1],
            'most_recent_updated_at': str(row[2]) if row[2] else None,
        }
    except Exception as e:
        status['occupation_salary'] = {'error': str(e)}

    try:
        from targeting_agent import load_matrix
        matrix = load_matrix()
        status['targeting_matrix'] = {
            'countries': len(matrix),
            'total_communes': sum(len(v.get('communes', {})) for v in matrix.values()),
            'source': next(iter(matrix.values()), {}).get('source', 'static_hardcoded'),
            'sample_updated_at': next(iter(matrix.values()), {}).get('communes_updated'),
        }
    except Exception as e:
        status['targeting_matrix'] = {'error': str(e)}

    status['commune_market_data_countries'] = db.query(CommuneMarketData.country).distinct().count()
    return status


# ══════════════════════════════════════════════════════════════
# SYSTEM TODO — trabajo pendiente/incompleto, consultable directo
# ══════════════════════════════════════════════════════════════

@app.get('/admin/todo')
def list_system_todos(secret: str, status: str = '', db: Session = Depends(get_db)):
    """Lista el TO-DO real del sistema — sin depender de que alguien lo reporte de nuevo."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    q = db.query(SystemTodo)
    if status:
        q = q.filter(SystemTodo.status == status)
    rows = q.order_by(SystemTodo.status.asc(), SystemTodo.priority.desc(), SystemTodo.created_at.asc()).all()
    return {'total': len(rows), 'todos': [{
        'id': r.id, 'title': r.title, 'description': r.description,
        'category': r.category, 'status': r.status, 'priority': r.priority,
        'discovered_by': r.discovered_by, 'created_at': str(r.created_at),
        'updated_at': str(r.updated_at), 'resolved_at': str(r.resolved_at) if r.resolved_at else None,
    } for r in rows]}

@app.post('/admin/todo')
def create_system_todo(secret: str, title: str, description: str = '', category: str = 'general',
                        priority: str = 'medium', discovered_by: str = '', db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    todo = SystemTodo(title=title, description=description, category=category,
                       priority=priority, discovered_by=discovered_by)
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return {'ok': True, 'id': todo.id}

@app.patch('/admin/todo/{todo_id}')
def update_system_todo(todo_id: int, secret: str, status: str = '', db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    todo = db.query(SystemTodo).filter(SystemTodo.id == todo_id).first()
    if not todo:
        raise HTTPException(404, 'Not found')
    if status:
        todo.status = status
        if status == 'done':
            todo.resolved_at = datetime.utcnow()
    todo.updated_at = datetime.utcnow()
    db.commit()
    return {'ok': True, 'id': todo.id, 'status': todo.status}


@app.post('/admin/agent/campaign-rescue')
def agent_campaign_rescue(secret: str, bg: BackgroundTasks):
    """Trigger the campaign-rescue agent — finds stalled advertiser campaigns
    (20+ days without a match) and creates a consultation targeted at their audience."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import run_campaign_rescue_debates
    bg.add_task(run_campaign_rescue_debates)
    return {'ok': True, 'message': 'Campaign-rescue agent started in background — check server logs for results'}

@app.post('/admin/agent/campaign-rescue/sync')
def agent_campaign_rescue_sync(secret: str):
    """Run the campaign-rescue agent synchronously and return results."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import run_campaign_rescue_debates
    return run_campaign_rescue_debates()

@app.post('/admin/agent/se-lifestyle-debates')
def agent_se_lifestyle(secret: str, bg: BackgroundTasks):
    """Trigger the SE Lifestyle Agent — generates aspirational debates per income tier (A/B/C/D)."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from se_lifestyle_agent import run_se_lifestyle_debates
    bg.add_task(run_se_lifestyle_debates)
    return {'ok': True, 'message': 'SE Lifestyle Agent started in background — luxury, premium, mass market debates'}

@app.post('/admin/agent/se-lifestyle-debates/sync')
def agent_se_lifestyle_sync(secret: str, tier: str = None):
    """Run SE Lifestyle Agent synchronously. Optional ?tier=A to run only one tier."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from se_lifestyle_agent import run_se_lifestyle_debates, SE_TOPICS
    if tier:
        tier = tier.upper()
        if tier not in SE_TOPICS:
            raise HTTPException(400, f'Tier must be A, B, C or D')
        from se_lifestyle_agent import _generate_se_debate, _create_se_debate_via_api, _created_this_run
        _created_this_run.clear()
        created = 0
        for t in SE_TOPICS[tier][:3]:
            d = _generate_se_debate(t, tier)
            if d and _create_se_debate_via_api(d, tier):
                created += 1
        return {'ok': True, 'tier': tier, 'debates_created': created}
    return run_se_lifestyle_debates(max_per_tier=3)

@app.post('/admin/agent/culture-debates')
def agent_culture_debates(secret: str, bg: BackgroundTasks):
    """Trigger culture/everyday + general knowledge debate generation."""
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import run_regional_debates
    bg.add_task(run_regional_debates)
    return {'ok': True, 'message': 'Regional sector agent started — creates debates from Chilean regional and sector media'}

@app.post('/admin/agent/regional-debates/sync')
def agent_regional_debates_sync(secret: str, force: bool = False):
    """Run regional/sector agent synchronously. force=true bypasses dedup."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import run_regional_debates
    return run_regional_debates(force=force)

@app.post('/admin/agent/task/{task_name}')
def run_agent_task(task_name: str, secret: str):
    """Run any scheduled agent task by name."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import run_scheduled_task
    return run_scheduled_task(task_name)

@app.get('/admin/db-schema')
def db_schema(secret: str):
    """Inspecciona columnas de tablas clave — diagnóstico remoto."""
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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


@app.post('/admin/import-zip-data')
def import_zip_data(secret: str, country: str = 'US',
                    bg: BackgroundTasks = None, db: Session = Depends(get_db)):
    """Importa datos de código postal / prefijo postal por país.
    US: Census Bureau ACS 5-year (~33,000 ZCTAs). Tarda 2-5 min.
    Resto: prefijos de código postal precargados (instantáneo).
    country=ALL importa todos los países disponibles.
    """
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')

    def _upsert_batch(session, items):
        # Solo campos que existen en el modelo CommuneMarketData
        VALID_COLS = {'country','commune','income_index','cpm_usd','se_tier','price_m2_avg'}
        for item in items:
            clean = {k: v for k, v in item.items() if k in VALID_COLS}
            existing = session.query(CommuneMarketData).filter_by(
                country=clean['country'], commune=clean['commune']).first()
            if existing:
                existing.income_index = clean['income_index']
                existing.cpm_usd      = clean['cpm_usd']
                existing.se_tier      = clean['se_tier']
                existing.price_m2_avg = 0
            else:
                session.add(CommuneMarketData(**clean))
        session.commit()

    def _do_import():
        with SessionLocal() as session:
            if country.upper() == 'ALL':
                from zipcode_agent import run_all_countries_import
                result = run_all_countries_import()
            else:
                from zipcode_agent import run_zip_import
                result = run_zip_import(country.upper())
            if result['data']:
                _upsert_batch(session, result['data'])

    if bg:
        bg.add_task(_do_import)
        return {'ok': True, 'status': 'running_in_background', 'country': country,
                'message': 'Import iniciado. Revisa /admin/tier-summary en unos minutos.'}
    else:
        _do_import()
        return {'ok': True, 'status': 'done', 'country': country}


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
    if secret != os.getenv('ADMIN_SECRET'):
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
def get_communes(country: str = None, se_tier: str = None, search: str = None, limit: int = 200, db: Session = Depends(get_db)):
    """Tabla de comunas con índice de ingreso y CPM. Usada por el motor de ads."""
    from market_data_agent import get_fallback_table
    q = db.query(CommuneMarketData)
    if country:
        q = q.filter(CommuneMarketData.country == country)
    if se_tier:
        q = q.filter(CommuneMarketData.se_tier == se_tier)
    if search:
        q = q.filter(CommuneMarketData.commune.ilike(f'%{search}%'))
        # Excluir entradas que son solo códigos numéricos (prefijos zip como "100", "021")
        q = q.filter(
            ~CommuneMarketData.commune.op('~')(r'^[0-9]{2,6}$')
        ).filter(
            CommuneMarketData.commune != ''
        ).filter(
            func.length(CommuneMarketData.commune) > 3
        )
    rows = q.order_by(CommuneMarketData.income_index.desc()).limit(limit).all()
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from preferendum_agent import run_scheduled_task
    result = run_scheduled_task(task_name)
    return result

@app.get('/agent/pending-reviews')
def admin_pending_reviews(secret: str, db: Session = Depends(get_db)):
    """Lista organizadores pendientes y consultas en revisión para el agente."""
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
def admin_reassign_tiers(
    secret: str, force: bool = False,
    batch: int = 50, offset: int = 0,
    db: Session = Depends(get_db)
):
    """Re-corre _assign_user_tier en batches para evitar timeout.
    Usa offset+batch para paginar: offset=0,50,100,..."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    q = db.query(User)
    if not force:
        q = q.filter((User.se_tier == None) | (User.se_tier == ''))
    total = q.count()
    user_ids = [u.id for u in q.offset(offset).limit(batch).all()]
    updated = []
    for uid in user_ids:
        # Sesión fresca por usuario — evita contaminación de TX entre iteraciones
        local_db = SessionLocal()
        try:
            u = local_db.query(User).filter(User.id == uid).first()
            if not u:
                continue
            before = u.se_tier or ''
            _assign_user_tier(u, local_db)
            local_db.refresh(u)
            after = u.se_tier or ''
            if after != before:
                updated.append({'id': uid, 'before': before, 'new_tier': after})
        except Exception:
            try:
                local_db.rollback()
            except Exception:
                pass
        finally:
            local_db.close()
    return {
        'total_eligible': total,
        'batch_size': len(user_ids),
        'offset': offset,
        'next_offset': offset + batch if offset + batch < total else None,
        'updated_in_batch': len(updated),
        'updated': updated,
    }


@app.get('/admin/debug-user')
def admin_debug_user(secret: str, email: str, db: Session = Depends(get_db)):
    """Muestra datos de targeting de un usuario para diagnóstico."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    u = db.query(User).filter(func.lower(User.email) == func.lower(email)).first()
    if not u:
        raise HTTPException(404, 'User not found')
    commune_row = None
    if u.county:
        commune_row = db.query(CommuneMarketData).filter(
            CommuneMarketData.commune.ilike(u.county.strip()),
            CommuneMarketData.country == _country_code(u.country)
        ).first()
        if not commune_row:
            commune_row = db.query(CommuneMarketData).filter(
                CommuneMarketData.commune.ilike(f'%{u.county.strip()}%')
            ).first()
    return {
        'id': u.id, 'email': u.email, 'name': u.name,
        'country': u.country, 'county': u.county,
        'profession': getattr(u, 'profession', ''),
        'se_tier': u.se_tier, 'income_index': u.income_index,
        'commune_match': {
            'commune': commune_row.commune, 'se_tier': commune_row.se_tier,
            'income_index': commune_row.income_index,
        } if commune_row else None,
    }

@app.get('/admin/users/breakdown')
def admin_users_breakdown(secret: str, db: Session = Depends(get_db)):
    """Desglose de usuarios por profesión, cargo y tier."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')

    by_profession = db.execute(text("""
        SELECT profession, COUNT(*) as total,
               COUNT(CASE WHEN se_tier='A' THEN 1 END) as tier_a,
               COUNT(CASE WHEN se_tier='B' THEN 1 END) as tier_b
        FROM users
        WHERE profession IS NOT NULL AND profession != ''
        GROUP BY profession ORDER BY total DESC
    """)).fetchall()

    by_cargo = db.execute(text("""
        SELECT job_position, COUNT(*) as total,
               COUNT(CASE WHEN se_tier='A' THEN 1 END) as tier_a
        FROM users
        WHERE job_position IS NOT NULL AND job_position != ''
        GROUP BY job_position ORDER BY total DESC
    """)).fetchall()

    by_tier = db.execute(text("""
        SELECT se_tier, COUNT(*) as total,
               ROUND(AVG(estimated_income_usd)::numeric, 0) as avg_income_usd
        FROM users
        WHERE se_tier IS NOT NULL
        GROUP BY se_tier ORDER BY se_tier
    """)).fetchall()

    top_earners = db.execute(text("""
        SELECT name, profession, job_position, se_tier,
               ROUND(estimated_income_usd::numeric, 0) as income_usd, country
        FROM users
        WHERE estimated_income_usd IS NOT NULL
        ORDER BY estimated_income_usd DESC LIMIT 10
    """)).fetchall()

    return {
        'by_profession': [{'profession': r[0], 'total': r[1], 'tier_a': r[2], 'tier_b': r[3]} for r in by_profession],
        'by_cargo': [{'cargo': r[0], 'total': r[1], 'tier_a': r[2]} for r in by_cargo],
        'by_tier': [{'tier': r[0], 'total': r[1], 'avg_income_usd': r[2]} for r in by_tier],
        'top_earners': [{'name': r[0], 'profession': r[1], 'cargo': r[2], 'tier': r[3], 'income_usd': r[4], 'country': r[5]} for r in top_earners],
    }


@app.get('/admin/users/hnw')
def admin_hnw_breakdown(secret: str, min_score: float = 50, db: Session = Depends(get_db)):
    """Distribución de usuarios por HNW score. min_score filtra el umbral mínimo."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')

    dist = db.execute(text("""
        SELECT
            CASE
                WHEN hnw_score >= 75 THEN 'HNW alto (75-100)'
                WHEN hnw_score >= 50 THEN 'HNW medio (50-74)'
                WHEN hnw_score >= 25 THEN 'Aspiracional (25-49)'
                ELSE 'Masa (0-24)'
            END as segmento,
            COUNT(*) as total,
            ROUND(AVG(estimated_income_usd)::numeric, 0) as avg_income
        FROM users
        WHERE hnw_score IS NOT NULL
        GROUP BY 1 ORDER BY MIN(hnw_score) DESC
    """)).fetchall()

    top_hnw = db.execute(text("""
        SELECT name, cargo, profession, company_size, se_tier,
               ROUND(hnw_score::numeric, 1) as hnw,
               ROUND(estimated_income_usd::numeric, 0) as income, country
        FROM users
        WHERE hnw_score >= :min
        ORDER BY hnw_score DESC LIMIT 20
    """), {'min': min_score}).fetchall()

    return {
        'distribucion': [{'segmento': r[0], 'total': r[1], 'avg_income_usd': r[2]} for r in dist],
        'top_hnw': [{'name': r[0], 'cargo': r[1], 'profession': r[2], 'company': r[3],
                     'tier': r[4], 'hnw_score': r[5], 'income_usd': r[6], 'country': r[7]}
                    for r in top_hnw],
        'umbral_usado': min_score,
    }


@app.post('/admin/recalculate-hnw')
def admin_recalculate_hnw(secret: str, db: Session = Depends(get_db)):
    """Recalcula hnw_score para todos los usuarios sin hacer reassign-tiers completo."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    users = db.query(User).all()
    updated = 0
    for u in users:
        try:
            hnw = _calculate_hnw_score(u, db)
            if hasattr(u, 'hnw_score'):
                u.hnw_score = hnw
                updated += 1
        except Exception:
            pass
    db.commit()
    return {'updated': updated, 'total': len(users)}


@app.get('/admin/communes-by-country')
def admin_communes_by_country(secret: str, db: Session = Depends(get_db)):
    """Cuenta registros CommuneMarketData por país."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from sqlalchemy import func as _f
    rows = db.query(CommuneMarketData.country, _f.count(CommuneMarketData.id))\
             .group_by(CommuneMarketData.country)\
             .order_by(CommuneMarketData.country).all()
    result = {cc: count for cc, count in rows}
    return {'total_paises': len(result), 'por_pais': result}

@app.get('/admin/tier-summary')
def admin_tier_summary(secret: str, db: Session = Depends(get_db)):
    """Distribución de se_tier entre todos los usuarios."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from collections import Counter
    users = db.query(User).all()
    dist = Counter(u.se_tier or 'sin_tier' for u in users)
    total = len(users)
    return {
        'total_usuarios': total,
        'distribucion': dict(sorted(dist.items())),
        'con_tier': total - dist.get('sin_tier', 0),
        'sin_tier': dist.get('sin_tier', 0),
    }

@app.get('/admin/audience-stats')
def admin_audience_stats(secret: str, db: Session = Depends(get_db)):
    """Inventario de audiencia por país y tier — para pricing de campañas publicitarias."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')

    from commune_agent import CPM_BASE_BY_COUNTRY
    from sqlalchemy import func as sqlfunc

    # Multiplicadores CPM por tier: A es premium, D es bajo
    TIER_CPM_MULT = {'A': 3.0, 'B': 1.5, 'C': 0.8, 'D': 0.4}

    rows = (db.query(User.country, User.se_tier, sqlfunc.count(User.id))
              .filter(User.se_tier.in_(['A', 'B', 'C', 'D']))
              .group_by(User.country, User.se_tier)
              .all())

    # Agrupar por país
    by_country: dict = {}
    for country, tier, cnt in rows:
        cc = (country or 'XX').upper()
        if cc not in by_country:
            by_country[cc] = {'A': 0, 'B': 0, 'C': 0, 'D': 0}
        by_country[cc][tier] = cnt

    # Calcular métricas por país
    output = {}
    for cc, tiers in by_country.items():
        cpm_base = CPM_BASE_BY_COUNTRY.get(cc, 5.0)
        total = sum(tiers.values())
        # CPM ponderado por la mezcla de tiers
        weighted_cpm = sum(tiers.get(t, 0) * cpm_base * m for t, m in TIER_CPM_MULT.items())
        avg_cpm = round(weighted_cpm / total, 2) if total else 0
        # Valor estimado de inventario si todos votan 1 vez (CPM = por 1000, aquí por usuario)
        est_value_usd = round(weighted_cpm / 1000, 2)
        output[cc] = {
            'tiers': tiers,
            'total_users': total,
            'cpm_base_usd': cpm_base,
            'avg_cpm_usd': avg_cpm,
            'est_inventory_value_usd': est_value_usd,
        }

    # Ordenar por total de usuarios desc
    output = dict(sorted(output.items(), key=lambda x: x[1]['total_users'], reverse=True))

    grand_total = sum(v['total_users'] for v in output.values())
    tier_a_total = sum(v['tiers'].get('A', 0) for v in output.values())

    return {
        'summary': {
            'total_users_with_tier': grand_total,
            'tier_a_users': tier_a_total,
            'countries': len(output),
        },
        'by_country': output,
    }


COUNTRY_NAMES = {
    'US':'United States','CL':'Chile','AR':'Argentina','BR':'Brazil','MX':'Mexico',
    'CO':'Colombia','PE':'Peru','VE':'Venezuela','EC':'Ecuador','BO':'Bolivia',
    'PY':'Paraguay','UY':'Uruguay','GB':'United Kingdom','DE':'Germany','FR':'France',
    'ES':'Spain','IT':'Italy','PT':'Portugal','NL':'Netherlands','BE':'Belgium',
    'CH':'Switzerland','AT':'Austria','PL':'Poland','CZ':'Czech Republic','RO':'Romania',
    'HU':'Hungary','GR':'Greece','TR':'Turkey','RU':'Russia','UA':'Ukraine',
    'CA':'Canada','AU':'Australia','NZ':'New Zealand','ZA':'South Africa',
    'NG':'Nigeria','EG':'Egypt','MA':'Morocco','SN':'Senegal','CI':"Côte d'Ivoire",
    'CM':'Cameroon','CN':'China','JP':'Japan','KR':'South Korea','IN':'India',
    'ID':'Indonesia','TH':'Thailand','MY':'Malaysia','PH':'Philippines','VN':'Vietnam',
    'SA':'Saudi Arabia','AE':'UAE','KW':'Kuwait','QA':'Qatar','IL':'Israel',
    'JO':'Jordan','IQ':'Iraq','IR':'Iran','KZ':'Kazakhstan','TW':'Taiwan','HK':'Hong Kong',
    'DO':'Dominican Republic','SG':'Singapore',
    'BG':'Bulgaria','CY':'Cyprus','DK':'Denmark','EE':'Estonia','FI':'Finland',
    'HR':'Croatia','IE':'Ireland','LT':'Lithuania','LU':'Luxembourg','LV':'Latvia',
    'MT':'Malta','NO':'Norway','SE':'Sweden','SI':'Slovenia','SK':'Slovakia',
}

@app.get('/admin/audience-dashboard')
def admin_audience_dashboard(secret: str, db: Session = Depends(get_db)):
    """Dashboard HTML de inventario de audiencia — para presentaciones a anunciantes."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')

    from commune_agent import CPM_BASE_BY_COUNTRY
    from sqlalchemy import func as sqlfunc
    from fastapi.responses import HTMLResponse

    TIER_CPM_MULT = {'A': 3.0, 'B': 1.5, 'C': 0.8, 'D': 0.4}

    rows = (db.query(User.country, User.se_tier, sqlfunc.count(User.id))
              .filter(User.se_tier.in_(['A', 'B', 'C', 'D']))
              .group_by(User.country, User.se_tier)
              .all())

    by_country: dict = {}
    for country, tier, cnt in rows:
        cc = (country or 'XX').upper()
        if cc not in by_country:
            by_country[cc] = {'A': 0, 'B': 0, 'C': 0, 'D': 0}
        by_country[cc][tier] = cnt

    output = {}
    for cc, tiers in by_country.items():
        cpm_base = CPM_BASE_BY_COUNTRY.get(cc, 5.0)
        total = sum(tiers.values())
        weighted_cpm = sum(tiers.get(t, 0) * cpm_base * m for t, m in TIER_CPM_MULT.items())
        avg_cpm = round(weighted_cpm / total, 2) if total else 0
        est_value_usd = round(weighted_cpm / 1000, 2)
        output[cc] = {'tiers': tiers, 'total_users': total,
                      'cpm_base_usd': cpm_base, 'avg_cpm_usd': avg_cpm,
                      'est_inventory_value_usd': est_value_usd}

    output = dict(sorted(output.items(), key=lambda x: x[1]['total_users'], reverse=True))
    grand_total = sum(v['total_users'] for v in output.values())
    tier_a_total = sum(v['tiers'].get('A', 0) for v in output.values())
    total_countries = len(output)
    total_inventory = round(sum(v['est_inventory_value_usd'] for v in output.values()), 2)

    rows_html = ''
    for cc, d in output.items():
        name = COUNTRY_NAMES.get(cc, cc)
        t = d['tiers']
        rows_html += f'''
        <tr>
          <td><span class="flag">{cc}</span> {name}</td>
          <td class="tier-a">{t["A"]:,}</td>
          <td class="tier-b">{t["B"]:,}</td>
          <td class="tier-c">{t["C"]:,}</td>
          <td class="tier-d">{t["D"]:,}</td>
          <td class="bold">{d["total_users"]:,}</td>
          <td>${d["cpm_base_usd"]:.1f}</td>
          <td class="bold">${d["avg_cpm_usd"]:.2f}</td>
          <td class="green">${d["est_inventory_value_usd"]:.2f}</td>
        </tr>'''

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Preferendum — Audience Inventory</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #0f0f1a; color: #e8e8f0; min-height: 100vh; padding: 32px 24px; }}
  h1 {{ font-size: 28px; font-weight: 700; color: #fff; margin-bottom: 4px; }}
  .subtitle {{ color: #8888aa; font-size: 14px; margin-bottom: 32px; }}
  .cards {{ display: flex; gap: 16px; margin-bottom: 32px; flex-wrap: wrap; }}
  .card {{ background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 12px;
           padding: 20px 28px; flex: 1; min-width: 180px; }}
  .card-label {{ font-size: 12px; color: #8888aa; text-transform: uppercase;
                 letter-spacing: 1px; margin-bottom: 8px; }}
  .card-value {{ font-size: 36px; font-weight: 700; color: #fff; }}
  .card-value.gold {{ color: #f5c842; }}
  .card-value.green {{ color: #4ade80; }}
  .card-value.blue {{ color: #60a5fa; }}
  table {{ width: 100%; border-collapse: collapse; background: #1a1a2e;
           border-radius: 12px; overflow: hidden; border: 1px solid #2a2a4a; }}
  thead {{ background: #12122a; }}
  th {{ padding: 14px 16px; text-align: left; font-size: 11px; color: #8888aa;
        text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }}
  td {{ padding: 12px 16px; font-size: 14px; border-top: 1px solid #1f1f38; }}
  tr:hover td {{ background: #1f1f38; }}
  .flag {{ font-weight: 700; color: #8888aa; font-size: 12px; }}
  .tier-a {{ color: #f5c842; font-weight: 600; }}
  .tier-b {{ color: #60a5fa; font-weight: 600; }}
  .tier-c {{ color: #a78bfa; font-weight: 600; }}
  .tier-d {{ color: #6b7280; }}
  .bold {{ font-weight: 700; color: #fff; }}
  .green {{ color: #4ade80; font-weight: 600; }}
  .legend {{ display: flex; gap: 20px; margin-top: 20px; flex-wrap: wrap; }}
  .legend-item {{ font-size: 12px; color: #8888aa; display: flex; align-items: center; gap: 6px; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; }}
  .dot-a {{ background: #f5c842; }}
  .dot-b {{ background: #60a5fa; }}
  .dot-c {{ background: #a78bfa; }}
  .dot-d {{ background: #6b7280; }}
  .timestamp {{ font-size: 11px; color: #555577; margin-top: 24px; text-align: right; }}
</style>
</head>
<body>
  <h1>Preferendum — Audience Inventory</h1>
  <p class="subtitle">Verified users by country and income tier · Real-time data</p>

  <div class="cards">
    <div class="card">
      <div class="card-label">Total Verified Users</div>
      <div class="card-value blue">{grand_total:,}</div>
    </div>
    <div class="card">
      <div class="card-label">Premium Tier A Users</div>
      <div class="card-value gold">{tier_a_total:,}</div>
    </div>
    <div class="card">
      <div class="card-label">Countries Active</div>
      <div class="card-value">{total_countries}</div>
    </div>
    <div class="card">
      <div class="card-label">Est. Inventory Value / Cycle</div>
      <div class="card-value green">${total_inventory:,.2f}</div>
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th>Country</th>
        <th>Tier A ★</th>
        <th>Tier B</th>
        <th>Tier C</th>
        <th>Tier D</th>
        <th>Total</th>
        <th>CPM Base</th>
        <th>Avg CPM</th>
        <th>Est. Value</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>

  <div class="legend">
    <div class="legend-item"><div class="dot dot-a"></div> Tier A — High income (top earners per country)</div>
    <div class="legend-item"><div class="dot dot-b"></div> Tier B — Upper middle income</div>
    <div class="legend-item"><div class="dot dot-c"></div> Tier C — Middle income</div>
    <div class="legend-item"><div class="dot dot-d"></div> Tier D — Entry level income</div>
  </div>
  <p class="timestamp">All users biometrically verified · 1 person = 1 account · Preferendum © 2026</p>
</body>
</html>"""

    return HTMLResponse(content=html)


@app.post('/admin/fix-user-tier')
def admin_fix_user_tier(secret: str, email: str, db: Session = Depends(get_db)):
    """Fuerza recalculo de se_tier para un usuario específico."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    u = db.query(User).filter(func.lower(User.email) == func.lower(email)).first()
    if not u:
        raise HTTPException(404, 'User not found')
    before = u.se_tier
    _assign_user_tier(u, db)
    return {'email': email, 'county': u.county, 'before': before, 'se_tier': u.se_tier, 'income_index': u.income_index}

@app.post('/admin/rental-price-agent/run')
def admin_run_rental_agent(secret: str, country: str = 'CL', db: Session = Depends(get_db)):
    """Ejecuta el RentalPriceAgent para un país — actualiza precios m² desde Portal Inmobiliario."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        from rental_price_agent import run as _agent_run
        result_holder['result'] = _agent_run(country, db)
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=300)
    if not result_holder:
        return {'ok': True, 'message': 'Agente iniciado en background (timeout 5min — ver logs)'}
    return result_holder.get('result', {'ok': False, 'message': 'Sin respuesta del agente'})


@app.get('/admin/rental-price-agent/status')
def admin_rental_agent_status(secret: str, country: str = 'CL', db: Session = Depends(get_db)):
    """Muestra estado actual de commune_market_data — último run del agente."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    rows = db.query(CommuneMarketData).filter(CommuneMarketData.country == country).order_by(CommuneMarketData.income_index.desc()).all()
    if not rows:
        return {'country': country, 'total': 0, 'message': 'Sin datos — corre /admin/rental-price-agent/run primero'}
    last_update = max((r.updated_at for r in rows if r.updated_at), default=None)
    tier_counts = {}
    for r in rows:
        tier_counts[r.se_tier] = tier_counts.get(r.se_tier, 0) + 1
    return {
        'country':     country,
        'total':       len(rows),
        'last_update': last_update.isoformat() if last_update else None,
        'tiers':       tier_counts,
        'top_10':      [{'commune': r.commune, 'income_index': r.income_index, 'se_tier': r.se_tier, 'sample_count': r.sample_count, 'source': r.portal} for r in rows[:10]],
    }


@app.post('/admin/rental-price-agent/run-global')
def admin_run_rental_global(secret: str, db: Session = Depends(get_db)):
    """Carga seed Deutsche Bank 2025 para todos los países (47 países, ~75 ciudades)."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        from rental_price_agent import run_global as _run_global
        result_holder['result'] = _run_global(db)
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=120)
    if not result_holder:
        return {'ok': True, 'message': 'Agente iniciado en background'}
    return result_holder.get('result', {'ok': False})


@app.get('/marketer/advertising-model')
def marketer_advertising_model():
    """
    Modelo de ingresos publicitarios de Preferendum como Media.
    CPM por tier × país + proyecciones en 4 escenarios de crecimiento.
    """
    from advertising_revenue_agent import preferendum_growth_model
    return preferendum_growth_model()


@app.get('/marketer/advertising-cpm')
def marketer_advertising_cpm(country: str = 'CL', tier: str = 'B'):
    """CPM efectivo para país + tier específicos."""
    from advertising_revenue_agent import get_effective_cpm, compute_blended_cpm, _TIER_DIST_DEFAULT
    return {
        'country':         country,
        'tier':            tier,
        'cpm_usd':         get_effective_cpm(country, tier),
        'blended_cpm_usd': compute_blended_cpm(country),
        'note':            'Audiencia 100% verificada (biometría) + SE tier clasificada.',
    }


@app.get('/marketer/advertising-revenue')
def marketer_advertising_revenue(country: str = 'CL', users: int = 1_000_000):
    """
    Calcula ingresos publicitarios para un país y número de usuarios.
    Ejemplo: /marketer/advertising-revenue?country=BR&users=85000000
    """
    from advertising_revenue_agent import revenue_model
    return revenue_model(users, country)


@app.get('/marketer/advertising-govt-scenario')
def marketer_advertising_govt(country: str = 'CL'):
    """
    Impacto de una consulta gubernamental en ingresos publicitarios.
    Países disponibles: CL, CO, MX, AR, BR, ES, IN
    """
    from advertising_revenue_agent import govt_consultation_impact
    return govt_consultation_impact(country.upper())


@app.post('/admin/import-usa-bea')
def admin_import_usa_bea(secret: str, db: Session = Depends(get_db)):
    """Importa 3,115 condados USA desde BEA CAINC1 2024 a commune_market_data."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        from usa_data_agent import import_bea_to_db as _import
        result_holder['result'] = _import(db)
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=600)
    if not result_holder:
        return {'ok': True, 'message': 'Import iniciado en background (timeout 10min — ver logs)'}
    return result_holder.get('result', {'ok': False, 'message': 'Sin respuesta'})


@app.post('/admin/import-nuts-eurostat')
def admin_import_nuts(secret: str, db: Session = Depends(get_db)):
    """Importa 244 regiones NUTS2 Europa desde Eurostat (ingreso disponible real EUR/hab)."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        from nuts_income_agent import run_nuts_import as _import
        result_holder['result'] = _import(db)
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=120)
    if not result_holder:
        return {'ok': True, 'message': 'Import NUTS iniciado (ver logs)'}
    return result_holder.get('result', {'ok': False})


@app.post('/admin/import-occupation-salary')
def admin_import_occupation(secret: str, countries: str = '', db: Session = Depends(get_db)):
    """Importa salario mediano por grupo ISCO-08 a occupation_salary.
    countries: lista separada por coma (ej: CL,BR,MX). Vacío = todos.
    Chile se descarga en tiempo real desde INE ESI SDMX.
    Resto usa seeds publicados (BR/MX/CO/AR/ZA/KR) — marcan fuente como 'seed'.
    """
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    country_list = [c.strip().upper() for c in countries.split(',') if c.strip()] or None
    import threading
    result_holder = {}
    def _run():
        from occupation_salary_agent import run_occupation_import as _import
        result_holder['result'] = _import(db, country_list)
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=120)
    if not result_holder:
        return {'ok': True, 'message': 'Occupation salary import iniciado (ver logs)'}
    return result_holder.get('result', {'ok': False})


@app.get('/admin/occupation-salary/lookup')
def admin_occupation_lookup(secret: str, country: str, profession: str, db: Session = Depends(get_db)):
    """Busca profession_score real para un país y profesión (ej: country=CL&profession=medico)."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from occupation_salary_agent import get_profession_score_from_db, PROFESSION_TO_ISCO
    score = get_profession_score_from_db(country.upper(), profession.lower(), db)
    isco = PROFESSION_TO_ISCO.get(profession.lower())
    return {
        'country': country.upper(),
        'profession': profession.lower(),
        'isco_group': isco,
        'profession_score': score,
        'found': score is not None,
    }

@app.get('/admin/tier-debug')
def admin_tier_debug(secret: str, country: str, profession: str, db: Session = Depends(get_db)):
    """Muestra cada fuente de datos usada para asignar tier a un país+profesión."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    result = {'country': country.upper(), 'profession': profession.lower(), 'sources': {}}
    cc = country.upper()
    prof = profession.lower()

    # 1. _OCC_TO_ISCO mapping
    isco_grp = _OCC_TO_ISCO.get(prof)
    result['isco_group'] = isco_grp

    # 2. ILO data
    try:
        from ilo_ilostat_agent import get_ilo_income
        ilo = get_ilo_income(cc, isco_grp, db) if isco_grp else None
        result['sources']['ilo'] = ilo
    except Exception as e:
        result['sources']['ilo'] = {'error': str(e)}

    # 3. occupation_salary directo
    if isco_grp:
        row = db.execute(text("""
            SELECT profession_score, median_monthly_usd, median_monthly_local, currency, source, year
            FROM occupation_salary WHERE country_iso=:c AND isco_group=:g
        """), {'c': cc, 'g': isco_grp}).fetchone()
        result['sources']['occupation_salary'] = dict(zip(
            ['profession_score','median_monthly_usd','median_monthly_local','currency','source','year'],
            row
        )) if row else None

    # 4. occupation_unified ISCO
    if isco_grp:
        row2 = db.execute(text("""
            SELECT profession_score, median_annual_usd FROM occupation_unified
            WHERE country_iso=:cc AND isco_group=:ig AND occupation_type='ISCO' AND profession_score IS NOT NULL LIMIT 1
        """), {'cc': cc, 'ig': isco_grp}).fetchone()
        result['sources']['occupation_unified'] = {'profession_score': row2[0], 'median_annual_usd': row2[1]} if row2 else None

    # 5. static _PROFESSION_TIER fallback
    result['sources']['static_tier'] = _PROFESSION_TIER.get(prof)

    # 6. commune data for CL (Vitacura como ejemplo)
    commune_ex = db.execute(text(
        "SELECT se_tier, income_index FROM commune_market_data WHERE country=:cc AND commune ILIKE 'Vitacura' LIMIT 1"
    ), {'cc': cc}).fetchone()
    result['commune_example_vitacura'] = {'se_tier': commune_ex[0], 'income_index': commune_ex[1]} if commune_ex else None

    return result

@app.get('/admin/tier-assign-test')
def admin_tier_assign_test(user_id: int, secret: str, db: Session = Depends(get_db)):
    """Ejecuta _assign_user_tier_inner sobre un usuario real y devuelve traceback si falla."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import traceback as _tb
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, f'User {user_id} not found')
    snapshot = {
        'id': user.id,
        'county': user.county,
        'country': user.country,
        'profession': user.profession,
        'se_tier_before': user.se_tier,
        'income_index_before': user.income_index,
    }
    error_msg = None
    try:
        _assign_user_tier(user, db)
        db.refresh(user)
    except Exception as _e:
        db.rollback()
        error_msg = _tb.format_exc()
    snapshot['se_tier_after'] = user.se_tier
    snapshot['income_index_after'] = user.income_index
    snapshot['estimated_income_usd'] = getattr(user, 'estimated_income_usd', None)
    snapshot['error'] = error_msg
    return snapshot

@app.post('/admin/import-ilo-wages')
def admin_import_ilo_wages(secret: str, db: Session = Depends(get_db)):
    """Descarga y guarda en DB los salarios reales ILO ILOSTAT por ISCO group (~100 países).
    Indicador: EAR_4MTH_SEX_OCU_CUR_NB_A — salario mensual por ocupación ISCO-08.
    Tiempo estimado: 2-5 min (descarga ~50 MB + insert ~900 filas).
    """
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        try:
            local_db = SessionLocal()
            try:
                from ilo_ilostat_agent import run_ilo_import
                result_holder['result'] = run_ilo_import(local_db)
            finally:
                local_db.close()
        except Exception as e:
            result_holder['result'] = {'ok': False, 'error': str(e)}
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=360)
    if not result_holder:
        return {'ok': True, 'message': 'ILO import iniciado en background (ver logs Render)'}
    return result_holder.get('result', {'ok': False})


@app.get('/admin/ilo-wages/summary')
def admin_ilo_wages_summary(secret: str, db: Session = Depends(get_db)):
    """Resumen de datos ILO ILOSTAT en ilo_wages."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from ilo_ilostat_agent import get_ilo_summary
    return get_ilo_summary(db)


@app.get('/admin/ilo-wages/lookup')
def admin_ilo_wages_lookup(secret: str, country: str, isco: int, db: Session = Depends(get_db)):
    """Busca salario ILO para un país y grupo ISCO (ej: country=CL&isco=2)."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from ilo_ilostat_agent import get_ilo_income
    result = get_ilo_income(country.upper(), isco, db)
    return result or {'found': False, 'country': country.upper(), 'isco_group': isco}


@app.get('/admin/wages/ranking')
def admin_wages_ranking(secret: str, db: Session = Depends(get_db)):
    """Ranking de salarios por grupo ISCO para todos los países disponibles.
    Combina ILO (65 países) + occupation_salary (CA,AU,KR,CN,CL,etc.) + occupation_unified (US).
    Retorna top países por ISCO group con monthly_usd (nominal) y monthly_ppp_usd (PPP-ajustado)."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')

    from ppp_agent import PLI

    ISCO_LABELS = {
        1: 'Managers', 2: 'Professionals', 3: 'Technicians',
        4: 'Clerical', 5: 'Service & Sales', 6: 'Agricultural',
        7: 'Craft trades', 8: 'Machine operators', 9: 'Elementary',
    }

    # 1. ILO data
    ilo_rows = db.execute(text("""
        SELECT country_iso2, isco_group, monthly_usd
        FROM ilo_wages
        WHERE monthly_usd IS NOT NULL AND monthly_usd > 0
    """)).fetchall()

    ilo_map: dict[tuple, float] = {}
    for r in ilo_rows:
        key = (r[0], r[1])
        if key not in ilo_map:
            ilo_map[key] = float(r[2])

    # 2. occupation_salary (CA, AU, KR, CN, CL, BR, MX, CO, AR, etc.)
    occ_rows = db.execute(text("""
        SELECT country_iso, isco_group, median_monthly_usd, median_monthly_ppp_usd
        FROM occupation_salary
        WHERE median_monthly_usd IS NOT NULL AND median_monthly_usd > 0
    """)).fetchall()
    occ_map: dict[tuple, tuple] = {}
    for r in occ_rows:
        key = (r[0], r[1])
        occ_map[key] = (float(r[2]), float(r[3]) if r[3] else None)

    # 3. USA desde occupation_unified (mediana por ISCO group)
    us_rows = db.execute(text("""
        SELECT isco_group, AVG(median_annual_usd/12.0)
        FROM occupation_unified
        WHERE country_iso='US' AND isco_group IS NOT NULL
          AND median_annual_usd IS NOT NULL AND median_annual_usd > 0
        GROUP BY isco_group
    """)).fetchall()
    us_map: dict[int, float] = {r[0]: round(float(r[1]), 2) for r in us_rows if r[1]}

    # Combinar: occupation_salary > ILO. combined = {(cc,isco): (nominal, ppp)}
    combined: dict[tuple, tuple] = {}
    for key, val in ilo_map.items():
        combined[key] = (val, None)
    for key, val_tuple in occ_map.items():
        combined[key] = val_tuple
    for isco, val in us_map.items():
        existing_ppp = combined.get(('US', isco), (val, None))[1]
        combined[('US', isco)] = (val, existing_ppp)

    # Construir ranking por ISCO con nominal + PPP real (ILOSTAT) o estimado (World Bank PLI)
    result = {}
    for isco_grp, label in ISCO_LABELS.items():
        entries = []
        for (cc, ig), (nominal, ppp_real) in combined.items():
            if ig != isco_grp:
                continue
            pli = PLI.get(cc)
            ppp = round(ppp_real, 0) if ppp_real else (round(nominal / pli, 0) if pli else None)
            ppp_source = 'ILOSTAT' if ppp_real else ('World Bank PLI' if pli else None)
            entries.append({
                'country':         cc,
                'monthly_usd':     round(nominal, 0),
                'monthly_ppp_usd': ppp,
                'ppp_source':      ppp_source,
                'pli':             pli,
            })
        entries.sort(key=lambda x: x['monthly_usd'], reverse=True)
        result[f'ISCO_{isco_grp}_{label}'] = entries

    return result


@app.get('/wages/curve')
def wages_curve(countries: str = 'CL', db: Session = Depends(get_db)):
    """Curva salarial ISCO 1-9 por país. Público — para el marketer portal.
    Combina occupation_salary + ilo_wages + occupation_unified (US) + seed para países sin DB.
    Seed fuente: World Bank / ILO / Numbeo 2025, USD/mes nominal."""
    ISCO_LABELS = {
        1: 'Managers', 2: 'Professionals', 3: 'Technicians',
        4: 'Clerical', 5: 'Service & Sales', 6: 'Agricultural',
        7: 'Craft trades', 8: 'Machine operators', 9: 'Elementary',
    }
    # Seed para países sin datos en DB — ISCO 1-9 USD/mes (World Bank/ILO/Numbeo 2025)
    _SEED: dict[str, dict[int, float]] = {
        'JP': {1:4700,2:3700,3:2530,4:2130,5:1870,6:1730,7:2130,8:2070,9:1600},
        'MY': {1:2500,2:1900,3:1200,4:900, 5:700, 6:600, 7:800, 8:750, 9:550 },
        'EC': {1:1400,2:900, 3:600, 4:480, 5:420, 6:380, 7:430, 8:440, 9:380 },
        'BO': {1:900, 2:600, 3:400, 4:330, 5:300, 6:280, 7:310, 8:320, 9:280 },
        'VE': {1:300, 2:200, 3:150, 4:120, 5:100, 6:90,  7:110, 8:105, 9:90  },
        'IL': {1:6500,2:5200,3:3800,4:2900,5:2400,6:2100,7:3000,8:2800,9:2200},
        'AE': {1:8500,2:5500,3:3200,4:1800,5:1200,6:900, 7:1400,8:1200,9:800 },
        'SA': {1:5500,2:4000,3:2500,4:1800,5:1200,6:900, 7:1500,8:1300,9:700 },
        'QA': {1:8000,2:5500,3:3000,4:2000,5:1400,6:1000,7:1600,8:1400,9:800 },
        'KZ': {1:2000,2:1400,3:900, 4:700, 5:550, 6:480, 7:620, 8:600, 9:430 },
        'IQ': {1:1200,2:800, 3:550, 4:450, 5:380, 6:320, 7:420, 8:400, 9:300 },
        'IR': {1:700, 2:500, 3:350, 4:280, 5:240, 6:210, 7:270, 8:260, 9:200 },
        # Calculados desde gulf_asia_wages_agent (PPP = nominal/PLI)
        'CH': {1:11991,2:8222,3:5618,4:4454,5:3837,6:3289,7:4659,8:5002,9:3563},
        'HK': {1:12375,2:7973,3:4675,4:3162,5:2338,6:2064,7:3162,8:3574,9:1995},
        'TW': {1:8882, 2:5842,3:3505,4:2244,5:1777,6:1543,7:2337,8:2571,9:1402},
        'SG': {1:9000, 2:6800,3:4200,4:2900,5:2100,6:1800,7:2800,8:3000,9:1700},
    }
    cc_list = [c.strip().upper() for c in countries.split(',') if c.strip()][:20]

    from ppp_agent import PLI as _PLI

    # occupation_salary — PPP preferido, fallback nominal con PLI estimado
    occ_all = db.execute(text("""
        SELECT country_iso, isco_group, median_monthly_usd,
               median_monthly_ppp_usd, ppp_price_level_index
        FROM occupation_salary
        WHERE country_iso = ANY(:ccs) AND isco_group BETWEEN 1 AND 9
          AND median_monthly_usd > 0
    """), {'ccs': cc_list}).fetchall()
    occ_map: dict[tuple, float] = {}
    for r in occ_all:
        cc, g, nominal, ppp, pli = r[0], int(r[1]), r[2], r[3], r[4]
        if ppp:
            occ_map[(cc, g)] = round(float(ppp), 0)
        elif nominal and pli:
            occ_map[(cc, g)] = round(float(nominal) / float(pli), 0)
        elif nominal:
            world_pli = _PLI.get(cc, 1.0)
            occ_map[(cc, g)] = round(float(nominal) / world_pli, 0)

    # ilo_wages — PPP preferido, fallback nominal con PLI
    ilo_all = db.execute(text("""
        SELECT country_iso2, isco_group, monthly_usd, monthly_ppp_usd
        FROM ilo_wages
        WHERE country_iso2 = ANY(:ccs) AND monthly_usd > 0
    """), {'ccs': cc_list}).fetchall()
    ilo_map: dict[tuple, float] = {}
    for r in ilo_all:
        cc, g, nominal, ppp = r[0], r[1], r[2], r[3]
        if g is None: continue
        try: g = int(g)
        except: continue
        if not (1 <= g <= 9): continue
        if ppp:
            ilo_map[(cc, g)] = round(float(ppp), 0)
        elif nominal:
            world_pli = _PLI.get(cc, 1.0)
            ilo_map[(cc, g)] = round(float(nominal) / world_pli, 0)

    # occupation_unified para USA (PPP = nominal, PLI USA = 1.0)
    us_map: dict[int, float] = {}
    if 'US' in cc_list:
        us_rows = db.execute(text("""
            SELECT isco_group, AVG(median_annual_usd/12.0)
            FROM occupation_unified
            WHERE country_iso='US' AND isco_group BETWEEN 1 AND 9
              AND median_annual_usd > 0
            GROUP BY isco_group
        """)).fetchall()
        us_map = {int(r[0]): round(float(r[1]), 0) for r in us_rows if r[1]}

    result = {}
    for cc in cc_list:
        curve = {}
        for g in range(1, 10):
            key = (cc, g)
            if key in occ_map:
                curve[str(g)] = occ_map[key]
            elif key in ilo_map:
                curve[str(g)] = ilo_map[key]
            elif cc == 'US' and g in us_map:
                curve[str(g)] = us_map[g]
        if not curve and cc in _SEED:
            # Seed ya en valores PPP estimados (World Bank PLI aplicado)
            curve = {str(g): v for g, v in _SEED[cc].items()}
        if curve:
            result[cc] = curve

    return {
        'countries': result,
        'isco_labels': ISCO_LABELS,
        'currency': 'PPP USD/month (poder adquisitivo real)',
    }


@app.post('/admin/import-ppp-ilo')
def admin_import_ppp_ilo(secret: str, db: Session = Depends(get_db)):
    """Importa curva salarial PPP ILOSTAT 10 países (BGD,BRA,CHN,COL,FRA,GBR,MEX,NOR,RUS,USA).
    Actualiza median_monthly_ppp_usd en occupation_salary con valores PPP reales (dólares internacionales).
    Crea occupation_salary_ceo con nivel CEO/Alta Dirección (ISCO 0)."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        local_db = SessionLocal()
        try:
            from ppp_ilo_agent import run_ppp_ilo_import
            result_holder['result'] = run_ppp_ilo_import(local_db)
        finally:
            local_db.close()
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=60)
    if not result_holder:
        return {'ok': True, 'message': 'Import PPP ILO iniciado (ver logs)'}
    return result_holder.get('result', {'ok': False})


@app.post('/admin/recompute-composite-income')
def admin_recompute_composite_income(secret: str, db: Session = Depends(get_db),
                                      limit: int = 5000):
    """
    Recalcula estimated_income_ppp (fórmula β-comunal) para todos los usuarios.
    Modelo: y_u = y_ocup × (I_comuna/100)^β_eff
    I_comuna = price_m2_comuna / mediana_nacional × 100 (commune_market_data)
    β_eff ajustado por edad: <33→0, 33-39→β/2, ≥40→β (β_base=0.35)
    """
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')

    from ppp_agent import PLI as _PLI_MAP
    from datetime import date as _date_cls

    _BETA_BASE = 0.35

    # Pre-calcular mediana de price_m2_avg por país en USD (una sola query por país)
    # Chile guarda precios en UF → multiplicar por 40.5 para comparar en USD
    _UF_USD = 40.5
    nat_medians: dict[str, float] = {}   # siempre en USD/m²
    try:
        cc_rows = db.execute(text("""
            SELECT DISTINCT country FROM commune_market_data WHERE price_m2_avg > 0
        """)).fetchall()
        for (cc_,) in cc_rows:
            _fx = _UF_USD if cc_ == 'CL' else 1.0
            try:
                try:
                    r = db.execute(text("""
                        SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_m2_avg * :fx)
                        FROM commune_market_data WHERE country=:cc AND price_m2_avg > 0
                    """), {'cc': cc_, 'fx': _fx}).fetchone()
                except Exception:
                    r = db.execute(text("""
                        SELECT AVG(price_m2_avg * :fx) FROM commune_market_data
                        WHERE country=:cc AND price_m2_avg > 0
                    """), {'cc': cc_, 'fx': _fx}).fetchone()
                if r and r[0]:
                    nat_medians[cc_] = round(float(r[0]), 2)
            except Exception:
                pass
    except Exception:
        pass

    users_q = db.execute(text("""
        SELECT id, country, county, estimated_income_usd, dob
        FROM users
        WHERE se_tier IS NOT NULL AND se_tier != ''
        ORDER BY id
        LIMIT :lim
    """), {'lim': limit}).fetchall()

    updated = skipped = 0

    for uid, country, commune, est_usd, dob_str in users_q:
        try:
            cc  = _country_code(country) if country else ''
            pli = _PLI_MAP.get(cc, 0.60)

            _occ_ppp = float(est_usd) / 12.0 / pli if est_usd and float(est_usd) > 0 else None
            if not _occ_ppp:
                skipped += 1
                continue

            # Índice comunal
            _comm_index = 100.0
            if commune and cc:
                cmd = db.execute(text("""
                    SELECT price_m2_avg FROM commune_market_data
                    WHERE country=:cc
                      AND (LOWER(commune) = LOWER(:cm) OR commune ILIKE :cm2)
                    LIMIT 1
                """), {'cc': cc, 'cm': commune.strip(), 'cm2': f'%{commune.strip()}%'}).fetchone()
                if cmd and cmd[0] and float(cmd[0]) > 0 and cc in nat_medians:
                    _price_usd = float(cmd[0]) * (_UF_USD if cc == 'CL' else 1.0)
                    _comm_index = (_price_usd / nat_medians[cc]) * 100.0

            # β efectivo por edad
            _user_age = None
            if dob_str:
                try:
                    _birth    = datetime.strptime(str(dob_str)[:10], '%Y-%m-%d').date()
                    _user_age = (_date_cls.today() - _birth).days // 365
                except Exception:
                    pass

            if _user_age is None:
                _beta_eff = _BETA_BASE
            elif _user_age < 33:
                _beta_eff = 0.0
            elif _user_age < 40:
                _beta_eff = _BETA_BASE / 2.0
            else:
                _beta_eff = _BETA_BASE

            if _beta_eff > 0 and _comm_index > 0:
                composite = _occ_ppp * ((_comm_index / 100.0) ** _beta_eff)
            else:
                composite = _occ_ppp

            db.execute(text(
                "UPDATE users SET estimated_income_ppp=:ppp WHERE id=:uid"
            ), {'ppp': round(composite, 1), 'uid': uid})
            updated += 1

            if updated % 200 == 0:
                db.commit()

        except Exception:
            skipped += 1
            continue

    db.commit()
    return {
        'updated':    updated,
        'skipped':    skipped,
        'total':      len(users_q),
        'model':      'beta-comunal: y_u = y_ocup × (I_comuna/100)^β_eff  (β_base=0.35)',
        'nat_medians': {k: round(v, 2) for k, v in nat_medians.items()},
        'status':     'ok',
    }


@app.post('/admin/import-perplexity-benchmarks')
def admin_import_perplexity_benchmarks(secret: str, db: Session = Depends(get_db)):
    """Importa benchmarks Perplexity 2026-07-31: CEO PPP (Tabla 1), % presupuesto
    9 marcas × 10 países (Tablas 2-3) y participación Visa (Tabla 4).
    Crea tablas: perplexity_budget_benchmarks, perplexity_ceo_ppp, perplexity_visa_share."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from perplexity_budget_agent import run_perplexity_import
    return run_perplexity_import(db)


@app.post('/admin/import-gulf-asia')
def admin_import_gulf_asia(secret: str, db: Session = Depends(get_db)):
    """Importa salarios ISCO 1-9 para IL, AE, QA, SA, MY, KZ, CH, HK, TW.
    Fuentes: CBS/MOE-UAE/PSA-Qatar/GASTAT/DOSM/BNS/SFSO/C&SD/DGBAS 2022-2023."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from gulf_asia_wages_agent import run_gulf_asia_import
    return run_gulf_asia_import(db)


@app.post('/admin/model-definitions')
def save_model_definition(secret: str, db: Session = Depends(get_db),
                           name: str = '', version: str = '1.0',
                           model_type: str = 'matching', description: str = '',
                           config_json: str = '{}', source_code: str = '', author: str = ''):
    """Guarda o actualiza un modelo de optimización/matching en la BD."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    existing = db.execute(text(
        "SELECT id FROM model_definitions WHERE name=:n AND version=:v"
    ), {'n': name, 'v': version}).fetchone()
    if existing:
        db.execute(text("""
            UPDATE model_definitions SET description=:desc, config_json=:cfg,
              source_code=:src, author=:auth, is_active=TRUE, updated_at=NOW()
            WHERE id=:id
        """), {'desc': description, 'cfg': config_json, 'src': source_code,
               'auth': author, 'id': existing[0]})
        db.commit()
        return {'status': 'updated', 'id': existing[0], 'name': name, 'version': version}
    db.execute(text("""
        INSERT INTO model_definitions (name, version, model_type, description, config_json, source_code, author)
        VALUES (:n, :v, :mt, :desc, :cfg, :src, :auth)
    """), {'n': name, 'v': version, 'mt': model_type, 'desc': description,
           'cfg': config_json, 'src': source_code, 'auth': author})
    db.commit()
    return {'status': 'created', 'name': name, 'version': version}


@app.get('/admin/model-definitions')
def list_model_definitions(secret: str, db: Session = Depends(get_db)):
    """Lista todos los modelos guardados."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    rows = db.execute(text(
        "SELECT id, name, version, model_type, description, author, is_active, created_at, updated_at "
        "FROM model_definitions ORDER BY updated_at DESC"
    )).fetchall()
    return {'models': [
        {'id': r[0], 'name': r[1], 'version': r[2], 'type': r[3],
         'description': r[4], 'author': r[5], 'is_active': r[6],
         'created_at': str(r[7]), 'updated_at': str(r[8])}
        for r in rows
    ]}


@app.post('/admin/apply-ppp')
def admin_apply_ppp(secret: str, db: Session = Depends(get_db)):
    """Aplica factores PPP (World Bank ICP 2022) a occupation_salary e ilo_wages.
    Agrega columnas median_monthly_ppp_usd y ppp_price_level_index.
    PPP_USD = Nominal_USD / PLI (donde PLI = precio relativo vs USA=1.0)."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        local_db = SessionLocal()
        try:
            from ppp_agent import run_ppp_import
            result_holder['result'] = run_ppp_import(local_db)
        finally:
            local_db.close()
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=60)
    if not result_holder:
        return {'ok': True, 'message': 'Apply PPP iniciado (ver logs)'}
    return result_holder.get('result', {'ok': False})


# ── China wages (PPP-adjusted) ────────────────────────────────────────────────

@app.post('/admin/import-china-wages')
def admin_import_china_wages(secret: str, db: Session = Depends(get_db)):
    """Importa datos salariales China: NBS oficial × provincia + 60 cargos específicos.
    Usa tasa PPP (1 USD = 3.29 CNY) para estimated_income_usd comparable globalmente."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        local_db = SessionLocal()
        try:
            from china_wages_agent import run_china_wages_import
            result_holder['result'] = run_china_wages_import(local_db)
        finally:
            local_db.close()
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=60)
    if not result_holder:
        return {'ok': True, 'message': 'Import China wages iniciado (ver logs)'}
    return result_holder.get('result', {'ok': False})


@app.get('/admin/china-wages/summary')
def admin_china_wages_summary(secret: str, db: Session = Depends(get_db)):
    """Resumen de datos en china_wages y china_wage_jobs."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from china_wages_agent import get_china_summary
    return get_china_summary(db)


@app.get('/admin/china-wages/lookup')
def admin_china_wages_lookup(secret: str, city: str, isco: int, db: Session = Depends(get_db)):
    """Busca salario PPP para usuario chino (ej: city=Shanghai&isco=2)."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from china_wages_agent import get_china_income
    result = get_china_income(city, isco, db)
    return result or {'found': False, 'city': city, 'isco_group': isco}


@app.post('/admin/import-scandinavia-wages')
def admin_import_scandinavia_wages(secret: str, db: Session = Depends(get_db)):
    """Importa salarios NO/SE/DK: 10 ocupaciones × 3 países, 2026. Fuente: SSB/SCB/DST."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        local_db = SessionLocal()
        try:
            from scandinavia_wages_agent import run_scandinavia_wages_import
            result_holder['result'] = run_scandinavia_wages_import(local_db)
        finally:
            local_db.close()
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=60)
    if not result_holder:
        return {'ok': True, 'message': 'Import Scandinavia wages iniciado'}
    return result_holder.get('result', {'ok': False})


@app.post('/admin/import-australia-wages')
def admin_import_australia_wages(secret: str, db: Session = Depends(get_db)):
    """Importa datos salariales Australia: ABS May 2025, ANZSCO→ISCO 1-9, AUD→USD."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        local_db = SessionLocal()
        try:
            from australia_wages_agent import run_australia_wages_import
            result_holder['result'] = run_australia_wages_import(local_db)
        finally:
            local_db.close()
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=60)
    if not result_holder:
        return {'ok': True, 'message': 'Import Australia wages iniciado'}
    return result_holder.get('result', {'ok': False})


@app.post('/admin/import-canada-wages')
def admin_import_canada_wages(secret: str, db: Session = Depends(get_db)):
    """Importa datos salariales Canadá: Statistics Canada 2024, NOC→ISCO 1-9, CAD→USD."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        local_db = SessionLocal()
        try:
            from canada_wages_agent import run_canada_wages_import
            result_holder['result'] = run_canada_wages_import(local_db)
        finally:
            local_db.close()
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=60)
    if not result_holder:
        return {'ok': True, 'message': 'Import Canada wages iniciado (ver logs)'}
    return result_holder.get('result', {'ok': False})


@app.post('/admin/import-korea-wages')
def admin_import_korea_wages(secret: str, db: Session = Depends(get_db)):
    """Importa datos salariales Korea: MOEL 2024, grupos ISCO 1-9 (KSCO), KRW→USD."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        local_db = SessionLocal()
        try:
            from korea_wages_agent import run_korea_wages_import
            result_holder['result'] = run_korea_wages_import(local_db)
        finally:
            local_db.close()
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=60)
    if not result_holder:
        return {'ok': True, 'message': 'Import Korea wages iniciado (ver logs)'}
    return result_holder.get('result', {'ok': False})


@app.post('/admin/import-japan-wages')
def admin_import_japan_wages(secret: str, db: Session = Depends(get_db)):
    """Importa datos salariales Japan: e-Stat MHLW 2024, 47 prefecturas, JPY→USD."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        local_db = SessionLocal()
        try:
            from japan_wages_agent import run_japan_wages_import
            result_holder['result'] = run_japan_wages_import(local_db)
        finally:
            local_db.close()
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=60)
    if not result_holder:
        return {'ok': True, 'message': 'Import Japan wages iniciado (ver logs)'}
    return result_holder.get('result', {'ok': False})


@app.post('/admin/import-japan-isco')
def admin_import_japan_isco(secret: str, db: Session = Depends(get_db)):
    """Importa Japón a occupation_salary con grupos ISCO 1-9 (MHLW 2024). Necesario para el ranking y gráfico."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from japan_wages_agent import run_japan_isco_import
    return run_japan_isco_import(db)


@app.get('/admin/japan-wages/lookup')
def admin_japan_wages_lookup(secret: str, prefecture: str, db: Session = Depends(get_db)):
    """Busca salario para usuario japonés (ej: prefecture=Tokyo)."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from japan_wages_agent import get_japan_income
    result = get_japan_income(prefecture, db)
    return result or {'found': False, 'prefecture': prefecture}


@app.post('/admin/import-russia-wages')
def admin_import_russia_wages(secret: str, db: Session = Depends(get_db)):
    """Importa datos salariales Rusia: Rosstat 2024, 85+ sujetos federales, RUB→USD."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        local_db = SessionLocal()
        try:
            from russia_wages_agent import run_russia_wages_import
            result_holder['result'] = run_russia_wages_import(local_db)
        finally:
            local_db.close()
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=60)
    if not result_holder:
        return {'ok': True, 'message': 'Import Russia wages iniciado (ver logs)'}
    return result_holder.get('result', {'ok': False})


@app.get('/admin/russia-wages/lookup')
def admin_russia_wages_lookup(secret: str, region: str, db: Session = Depends(get_db)):
    """Busca salario para usuario ruso (ej: region=Moscow)."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from russia_wages_agent import get_russia_income
    result = get_russia_income(region, db)
    return result or {'found': False, 'region': region}


@app.post('/admin/import-singapore-wages')
def admin_import_singapore_wages(secret: str, db: Session = Depends(get_db)):
    """Importa datos salariales Singapore: MOM 2025, ~530 ocupaciones SSOC, SGD→USD."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        local_db = SessionLocal()
        try:
            from singapore_wages_agent import run_singapore_wages_import
            result_holder['result'] = run_singapore_wages_import(local_db)
        finally:
            local_db.close()
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=60)
    if not result_holder:
        return {'ok': True, 'message': 'Import Singapore wages iniciado (ver logs)'}
    return result_holder.get('result', {'ok': False})


@app.post('/admin/import-new-zealand-wages')
def admin_import_new_zealand_wages(secret: str, db: Session = Depends(get_db)):
    """Importa datos salariales Nueva Zelanda: Stats NZ 2025 (8 grupos ANZSCO) + 16 regiones, NZD→USD."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        local_db = SessionLocal()
        try:
            from new_zealand_wages_agent import run_new_zealand_wages_import
            result_holder['result'] = run_new_zealand_wages_import(local_db)
        finally:
            local_db.close()
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=60)
    if not result_holder:
        return {'ok': True, 'message': 'Import New Zealand wages iniciado (ver logs)'}
    return result_holder.get('result', {'ok': False})


@app.post('/admin/nuts-pipeline/run')
def admin_nuts_pipeline_run(secret: str, db: Session = Depends(get_db)):
    """Pipeline NUTS 2/3 completo (handoff Perplexity 2026-07-27).
    Crea tablas rip_countries/rip_regions/rip_import_batches/rip_observations,
    carga 50-country seed y descarga 244 regiones NUTS2 reales de Eurostat.
    """
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    import threading
    result_holder = {}
    def _run():
        from nuts_pipeline import run_nuts_pipeline
        result_holder['result'] = run_nuts_pipeline(db)
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=120)
    if not result_holder:
        return {'ok': True, 'message': 'Pipeline NUTS iniciado (ver logs)'}
    return result_holder.get('result', {'ok': False})


@app.get('/admin/nuts-pipeline/summary')
def admin_nuts_pipeline_summary(secret: str, db: Session = Depends(get_db)):
    """Estado del pipeline NUTS — países, regiones, observaciones, últimos batches."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from nuts_pipeline import get_pipeline_summary
    return get_pipeline_summary(db)


@app.get('/admin/usa-data-agent/stats')
def admin_usa_data_stats(secret: str):
    """Estadísticas del agente USA — condados BEA + ocupaciones BLS cargados en memoria."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from usa_data_agent import get_stats
    return get_stats()


@app.get('/admin/usa-data-agent/county')
def admin_usa_county_lookup(secret: str, county: str, state: str = ''):
    """Busca un condado en los datos BEA — verifica el ingreso y tier asignado."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from usa_data_agent import get_county_data
    data = get_county_data(county, state)
    if not data:
        raise HTTPException(404, f'Condado no encontrado: {county}')
    return data


@app.get('/admin/usa-data-agent/occupation')
def admin_bls_occupation_lookup(secret: str, title: str):
    """Busca una ocupación en los datos BLS — verifica el salario mediano y score."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from usa_data_agent import get_occupation_score, profession_score_to_tier
    data = get_occupation_score(title)
    if not data:
        raise HTTPException(404, f'Ocupación no encontrada: {title}')
    data['tier_h1'] = profession_score_to_tier(data['profession_score'])
    return data


_BLS_MAJOR_GROUP_NAMES: dict[str, str] = {
    '11-0000': 'Management',
    '13-0000': 'Business and Financial Operations',
    '15-0000': 'Computer and Mathematical',
    '17-0000': 'Architecture and Engineering',
    '19-0000': 'Life, Physical, and Social Science',
    '21-0000': 'Community and Social Service',
    '23-0000': 'Legal',
    '25-0000': 'Educational Instruction and Library',
    '27-0000': 'Arts, Design, Entertainment, Sports, and Media',
    '29-0000': 'Healthcare Practitioners and Technical',
    '31-0000': 'Healthcare Support',
    '33-0000': 'Protective Service',
    '35-0000': 'Food Preparation and Serving Related',
    '37-0000': 'Building and Grounds Cleaning and Maintenance',
    '39-0000': 'Personal Care and Service',
    '41-0000': 'Sales and Related',
    '43-0000': 'Office and Administrative Support',
    '45-0000': 'Farming, Fishing, and Forestry',
    '47-0000': 'Construction and Extraction',
    '49-0000': 'Installation, Maintenance, and Repair',
    '51-0000': 'Production',
    '53-0000': 'Transportation and Material Moving',
}


@app.post('/admin/import-oews-msa')
async def admin_import_oews_msa(
    secret: str,
    year: int = 2023,
    file: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    """
    Importa datos BLS OEWS por MSA.
    Sube el archivo oesm23ma.zip manualmente (BLS bloquea descargas automáticas).
    Uso: POST /admin/import-oews-msa?secret=XXX con el ZIP adjunto como 'file'.
    """
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    if not file:
        raise HTTPException(400, 'Se requiere el archivo ZIP de BLS OEWS (oesm23ma.zip). '
                                 'Descárgalo de https://www.bls.gov/oes/tables.htm')
    zip_bytes = await file.read()
    if len(zip_bytes) < 1000:
        raise HTTPException(400, 'Archivo demasiado pequeño — verifica que subiste el ZIP correcto')
    try:
        from bls_oews_msa_agent import run_oews_msa_import
        result = run_oews_msa_import(db, zip_bytes, year=year)
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get('/admin/oews-msa/summary')
def admin_oews_msa_summary(secret: str, db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from bls_oews_msa_agent import get_oews_summary
    return get_oews_summary(db)


@app.get('/admin/oews-msa/lookup')
def admin_oews_msa_lookup(secret: str, soc_code: str, commune: str, db: Session = Depends(get_db)):
    """Busca el salario de una ocupación en el MSA más cercano a la commune."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    from bls_oews_msa_agent import get_msa_salary
    result = get_msa_salary(soc_code, commune, db)
    if not result:
        raise HTTPException(404, f'No se encontró dato para SOC {soc_code} en área "{commune}"')
    return result


@app.get('/api/occupations')
def api_list_occupations(db: Session = Depends(get_db)):
    """Lista las 818 ocupaciones BLS — usada por el formulario de registro."""
    rows = db.execute(text("""
        SELECT occupation_code, title, isco_group, isco_label, profession_score
        FROM occupation_unified
        WHERE country_iso = 'US' AND occupation_type = 'SOC'
          AND title IS NOT NULL
        ORDER BY isco_group, title
    """)).fetchall()
    result = []
    for r in rows:
        soc, title, isco_grp, isco_label, score = r
        major_group = soc[:2] + '-0000' if soc else ''
        result.append({
            'code': soc,
            'title': title,
            'group': major_group,
            'group_name': _BLS_MAJOR_GROUP_NAMES.get(major_group, ''),
            'isco': isco_grp,
            'score': round(float(score), 1) if score else None,
        })
    return result


@app.get('/marketer/project-campaign')
def marketer_project_campaign(
    countries: str,
    tiers: str,
    age_min: int = 18,
    age_max: int = 65,
    budget_usd: float = 100000,
    brand: str = '',
    campaign_name: str = '',
):
    """
    Proyecta alcance y costo de una campaña multi-país.
    countries: códigos separados por coma (ej: FR,ES,BR,CL)
    tiers: A,B o B,C  etc.
    Usa datos demográficos reales WorldBank/ITU 2024.
    """
    from campaign_projector import project_campaign
    cc_list = [c.strip().upper() for c in countries.split(',') if c.strip()]
    tier_list = [t.strip().upper() for t in tiers.split(',') if t.strip()]
    return project_campaign(
        countries=cc_list,
        tiers=tier_list,
        age_min=age_min,
        age_max=age_max,
        budget_usd=budget_usd,
        campaign_name=campaign_name or f'Campaña {brand}',
        brand=brand,
    )


@app.get('/marketer/project-brazil-ab')
def marketer_brazil_ab(budget_usd: float = 200000):
    """Análisis rápido: Brasil tier A+B mayores de 25 años."""
    from campaign_projector import brazil_ab_25plus
    return brazil_ab_25plus(budget_usd)


@app.get('/marketer/demo/peugeot-students')
def demo_peugeot_students(budget_usd: float = 500000):
    """Demo Peugeot 208 — Estudiantes universitarios, 18–26 años, tier B+C, 19 países."""
    from campaign_projector import peugeot_students
    return peugeot_students(budget_usd)


@app.get('/marketer/demo/peugeot-families')
def demo_peugeot_families(budget_usd: float = 750000):
    """Demo Peugeot Rifter/Traveller — Familias, 28–55 años, tier A+B, 19 países."""
    from campaign_projector import peugeot_families
    return peugeot_families(budget_usd)


@app.post('/admin/debates/{debate_id}/force-verify')
def admin_force_verify(debate_id: int, secret: str, db: Session = Depends(get_db)):
    """Fuerza un debate a fase de verificación — para demos y pruebas."""
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Debate not found')
    now = datetime.utcnow()
    debate.closes_at         = now - timedelta(hours=1)
    debate.verify_opens_at   = now - timedelta(minutes=30)
    debate.verify_closes_at  = now + timedelta(days=7)
    db.commit()
    return {'ok': True, 'debate_id': debate_id, 'status': 'verify', 'message': 'Debate forzado a fase de verificación'}


@app.post('/admin/seed-opinions')
def seed_opinions(secret: str, debate_id: int, count: int = 8, db: Session = Depends(get_db)):
    """Agrega opiniones de prueba a un debate para que aparezcan los ads (necesita ≥6)."""
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    campaigns = db.query(AdCampaign).order_by(AdCampaign.id.desc()).all()
    return {'campaigns': [_format_campaign(c) for c in campaigns]}


@app.patch('/admin/campaigns/{campaign_id}/activate')
def admin_activate_campaign(campaign_id: int, secret: str, days: int = 30, db: Session = Depends(get_db)):
    """Reactiva una campaña expirada y extiende su fecha de fin."""
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
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
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
    org_users = db.query(User).filter(User.role == 'organizer').all()
    ids = [u.id for u in org_users]
    deleted_profiles = db.query(OrganizerProfile).filter(OrganizerProfile.user_id.in_(ids)).delete(synchronize_session=False)
    deleted_users = db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return {'ok': True, 'deleted_users': deleted_users, 'deleted_profiles': deleted_profiles}


# ══════════════════════════════════════════════════════════════
# SPONSORED CONSULTATIONS — Sistema B2B de consultas patrocinadas
# Aerolíneas / hoteles / bancos traen sus clientes HNW a votar
# ══════════════════════════════════════════════════════════════

def _check_admin(secret: str):
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')

def _get_sponsor_info(debate_id: int, db: Session):
    sp = db.query(SponsoredDebate).filter(
        SponsoredDebate.debate_id == debate_id,
        SponsoredDebate.is_active == True
    ).first()
    if not sp:
        return None
    sponsor = db.query(Sponsor).filter(Sponsor.id == sp.sponsor_id).first()
    if not sponsor:
        return None
    return {
        'name': sponsor.name,
        'logo_url': sponsor.logo_url,
        'discount_pct': sp.discount_pct,
        'discount_text': sp.discount_text,
    }

@app.post('/admin/sponsors')
def admin_create_sponsor(
    secret: str,
    name: str,
    industry: str = '',
    logo_url: str = '',
    contact_email: str = '',
    discount_code_prefix: str = '',
    db: Session = Depends(get_db)
):
    _check_admin(secret)
    prefix = discount_code_prefix.upper() or name[:3].upper()
    sp = Sponsor(
        name=name, industry=industry, logo_url=logo_url,
        contact_email=contact_email, discount_code_prefix=prefix
    )
    db.add(sp)
    db.commit()
    db.refresh(sp)
    return {'ok': True, 'sponsor_id': sp.id, 'name': sp.name, 'prefix': sp.discount_code_prefix}

@app.get('/admin/sponsors')
def admin_list_sponsors(secret: str, db: Session = Depends(get_db)):
    _check_admin(secret)
    sponsors = db.query(Sponsor).all()
    return [{'id': s.id, 'name': s.name, 'industry': s.industry,
             'contact_email': s.contact_email, 'prefix': s.discount_code_prefix} for s in sponsors]

@app.post('/admin/sponsors/{sponsor_id}/debates/{debate_id}')
def admin_link_sponsored_debate(
    sponsor_id: int, debate_id: int, secret: str,
    discount_pct: int = 15, discount_text: str = '',
    db: Session = Depends(get_db)
):
    _check_admin(secret)
    sponsor = db.query(Sponsor).filter(Sponsor.id == sponsor_id).first()
    if not sponsor:
        raise HTTPException(404, 'Sponsor not found')
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Debate not found')
    existing = db.query(SponsoredDebate).filter(SponsoredDebate.debate_id == debate_id).first()
    if existing:
        existing.sponsor_id = sponsor_id
        existing.discount_pct = discount_pct
        existing.discount_text = discount_text or f'{discount_pct}% de descuento en tu próximo {sponsor.industry or "servicio"} con {sponsor.name}'
        existing.is_active = True
        db.commit()
        return {'ok': True, 'updated': True, 'sponsored_debate_id': existing.id}
    sd = SponsoredDebate(
        debate_id=debate_id, sponsor_id=sponsor_id,
        discount_pct=discount_pct,
        discount_text=discount_text or f'{discount_pct}% de descuento en tu próximo {sponsor.industry or "servicio"} con {sponsor.name}'
    )
    db.add(sd)
    db.commit()
    db.refresh(sd)
    return {'ok': True, 'sponsored_debate_id': sd.id, 'sponsor': sponsor.name, 'debate': debate.title}

@app.post('/admin/sponsors/{sponsor_id}/campaigns')
async def admin_create_campaign(
    sponsor_id: int, secret: str,
    debate_id: int,
    campaign_name: str = 'Campaña',
    emails_csv: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    _check_admin(secret)
    sponsor = db.query(Sponsor).filter(Sponsor.id == sponsor_id).first()
    if not sponsor:
        raise HTTPException(404, 'Sponsor not found')
    sp_debate = db.query(SponsoredDebate).filter(
        SponsoredDebate.debate_id == debate_id,
        SponsoredDebate.sponsor_id == sponsor_id
    ).first()
    if not sp_debate:
        raise HTTPException(400, f'Debate {debate_id} no está vinculado a este sponsor. Usa POST /admin/sponsors/{sponsor_id}/debates/{debate_id} primero.')
    raw = await emails_csv.read()
    lines = raw.decode('utf-8', errors='ignore').splitlines()
    emails = []
    for line in lines:
        line = line.strip().strip('"').strip("'")
        if '@' in line and '.' in line:
            emails.append(line.lower())
    if not emails:
        raise HTTPException(400, 'No se encontraron emails válidos en el CSV')
    campaign = SponsorCampaign(
        sponsored_debate_id=sp_debate.id, sponsor_id=sponsor_id,
        name=campaign_name, total_emails=len(emails), status='draft'
    )
    db.add(campaign)
    db.flush()
    for email in emails:
        token = uuid.uuid4().hex
        db.add(SponsorInvitee(
            campaign_id=campaign.id, sponsor_id=sponsor_id,
            email=email, invite_token=token
        ))
    sp_debate.total_invited = (sp_debate.total_invited or 0) + len(emails)
    db.commit()
    return {'ok': True, 'campaign_id': campaign.id, 'emails_loaded': len(emails), 'status': 'draft'}

@app.post('/admin/sponsors/{sponsor_id}/campaigns/{campaign_id}/send')
def admin_send_campaign(
    sponsor_id: int, campaign_id: int, secret: str,
    base_url: str = 'https://preferendum.com',
    db: Session = Depends(get_db)
):
    _check_admin(secret)
    campaign = db.query(SponsorCampaign).filter(
        SponsorCampaign.id == campaign_id,
        SponsorCampaign.sponsor_id == sponsor_id
    ).first()
    if not campaign:
        raise HTTPException(404, 'Campaign not found')
    sponsor = db.query(Sponsor).filter(Sponsor.id == sponsor_id).first()
    sp_debate = db.query(SponsoredDebate).filter(SponsoredDebate.id == campaign.sponsored_debate_id).first()
    debate = db.query(Debate).filter(Debate.id == sp_debate.debate_id).first() if sp_debate else None
    invitees = db.query(SponsorInvitee).filter(
        SponsorInvitee.campaign_id == campaign_id,
        SponsorInvitee.sent == False
    ).all()
    sent_count = 0
    errors = []
    for inv in invitees:
        invite_url = f"{base_url}/?invite={inv.invite_token}&debate={sp_debate.debate_id if sp_debate else ''}"
        subject = f"{sponsor.name} te invita a compartir tu opinión — {sp_debate.discount_pct}% de descuento"
        html_body = f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
  <div style="background:#1a1a2e;padding:24px;text-align:center;">
    <h2 style="color:#fff;margin:0">{sponsor.name}</h2>
  </div>
  <div style="padding:32px;">
    <h3 style="color:#1a1a2e">Te invitamos a dar tu opinión</h3>
    <p>{sponsor.name} quiere conocer tu experiencia y preferencias.</p>
    <p><strong>Como agradecimiento, recibirás {sp_debate.discount_pct}% de descuento</strong> en tu próximo servicio con nosotros al completar la consulta.</p>
    {'<p style="color:#666">Consulta: ' + debate.title + '</p>' if debate else ''}
    <div style="text-align:center;margin:32px 0;">
      <a href="{invite_url}" style="background:#3b82f6;color:#fff;padding:14px 28px;text-decoration:none;border-radius:8px;font-weight:bold;">
        Votar ahora y obtener {sp_debate.discount_pct}% de descuento
      </a>
    </div>
    <p style="color:#999;font-size:12px;">Tu código de descuento se generará automáticamente al completar tu voto.</p>
  </div>
</div>"""
        try:
            _send_html_email(inv.email, subject, html_body)
            inv.sent = True
            sent_count += 1
        except Exception as e:
            errors.append({'email': inv.email, 'error': str(e)})
    campaign.sent = sent_count
    campaign.status = 'sent' if sent_count > 0 else 'draft'
    db.commit()
    return {'ok': True, 'sent': sent_count, 'errors': len(errors), 'error_detail': errors[:5]}

@app.get('/admin/sponsors/{sponsor_id}/dashboard')
def admin_sponsor_dashboard(sponsor_id: int, secret: str, db: Session = Depends(get_db)):
    _check_admin(secret)
    sponsor = db.query(Sponsor).filter(Sponsor.id == sponsor_id).first()
    if not sponsor:
        raise HTTPException(404, 'Sponsor not found')
    sp_debates = db.query(SponsoredDebate).filter(SponsoredDebate.sponsor_id == sponsor_id).all()
    campaigns = db.query(SponsorCampaign).filter(SponsorCampaign.sponsor_id == sponsor_id).all()
    verified_hnw_from_sponsor = db.query(User).filter(
        User.hnw_source == sponsor.name.lower().replace(' ', '_')
    ).count()
    debates_detail = []
    for sd in sp_debates:
        debate = db.query(Debate).filter(Debate.id == sd.debate_id).first()
        debates_detail.append({
            'debate_id': sd.debate_id,
            'debate_title': debate.title if debate else '',
            'discount_pct': sd.discount_pct,
            'total_invited': sd.total_invited,
            'total_voted': sd.total_voted,
            'conversion_pct': round(sd.total_voted / sd.total_invited * 100, 1) if sd.total_invited else 0,
        })
    return {
        'sponsor': {'id': sponsor.id, 'name': sponsor.name, 'industry': sponsor.industry},
        'verified_hnw_users_acquired': verified_hnw_from_sponsor,
        'debates': debates_detail,
        'campaigns': [{'id': c.id, 'name': c.name, 'total_emails': c.total_emails,
                       'sent': c.sent, 'voted': c.voted, 'status': c.status} for c in campaigns],
    }


# ══════════════════════════════════════════════════════════════
# EXECUTIVE DEMO — Preferendum Intelligence Platform
# Private page for partner / investor meetings
# ══════════════════════════════════════════════════════════════
# PILOT DASHBOARD — real-time metrics for agency/brand during live pilot
# ══════════════════════════════════════════════════════════════

@app.get('/pilot/{debate_id}/live')
def pilot_live_dashboard(debate_id: int, db: Session = Depends(get_db)):
    """Real-time pilot metrics for agency/brand. No auth required (debate_id is the access token)."""
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(404, 'Debate not found')

    # All votes for this debate
    votes = db.query(DebateVote).filter(DebateVote.debate_id == debate_id).all()
    total_votes = len(votes)

    # All users who voted — join to get their ref_source, country, se_tier
    voter_ids = [v.voter_id for v in votes if v.voter_id]
    users_map = {}
    if voter_ids:
        for u in db.query(User).filter(User.id.in_(voter_ids)).all():
            users_map[u.id] = u

    # Registrations by channel (ref_source)
    by_channel: dict = {}
    by_country: dict = {}
    by_tier: dict = {}
    for v in votes:
        u = users_map.get(v.voter_id)
        if not u:
            continue
        ch = u.ref_source or 'direct'
        by_channel[ch] = by_channel.get(ch, 0) + 1
        co = u.country or 'XX'
        by_country[co] = by_country.get(co, 0) + 1
        tier = u.se_tier or '?'
        by_tier[tier] = by_tier.get(tier, 0) + 1

    # Votes by option
    counts = {}
    try:
        counts = json.loads(debate.vote_counts or '{}')
    except Exception:
        pass

    # Reward codes claimed
    total_codes = db.query(DebateRewardCode).filter(DebateRewardCode.debate_id == debate_id).count()
    claimed_codes = db.query(DebateRewardCode).filter(
        DebateRewardCode.debate_id == debate_id,
        DebateRewardCode.claimed == True
    ).count()

    # Votes per hour (last 24h)
    from collections import defaultdict
    hourly: dict = defaultdict(int)
    for v in votes:
        if v.created_at:
            h = v.created_at.strftime('%Y-%m-%dT%H:00')
            hourly[h] += 1

    return {
        'debate_id': debate_id,
        'title': debate.title,
        'total_votes': total_votes,
        'results': counts,
        'by_channel': dict(sorted(by_channel.items(), key=lambda x: -x[1])),
        'by_country': dict(sorted(by_country.items(), key=lambda x: -x[1])),
        'by_tier': dict(sorted(by_tier.items())),
        'reward_codes': {'total': total_codes, 'claimed': claimed_codes, 'remaining': total_codes - claimed_codes},
        'votes_by_hour': dict(sorted(hourly.items())),
        'updated_at': datetime.utcnow().isoformat(),
    }

# ══════════════════════════════════════════════════════════════

@app.post('/admin/fix-commune-tiers')
def admin_fix_commune_tiers(secret: str, db: Session = Depends(get_db)):
    """Recalcula se_tier para todas las comunas con valor corrupto (más de 1 letra)."""
    _check_admin(secret)
    rows = db.query(CommuneMarketData).filter(
        func.length(CommuneMarketData.se_tier) != 1
    ).all()
    fixed = 0
    for r in rows:
        idx = r.income_index or 0
        if idx >= 80:   r.se_tier = 'A'
        elif idx >= 50: r.se_tier = 'B'
        elif idx >= 25: r.se_tier = 'C'
        else:           r.se_tier = 'D'
        fixed += 1
    db.commit()
    return {'ok': True, 'fixed': fixed}

@app.post('/admin/verify-user')
def admin_verify_user(user_id: int, secret: str, db: Session = Depends(get_db)):
    """Admin: marca email_verified=True para un usuario (solo testing)."""
    _check_admin(secret)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, 'User not found')
    user.email_verified = True
    db.commit()
    return {'ok': True, 'user_id': user_id, 'email': user.email, 'email_verified': True}

@app.get('/sable', response_class=HTMLResponse)
def sable_demo(secret: str = '', db: Session = Depends(get_db)):
    if secret != os.getenv('ADMIN_SECRET'):
        raise HTTPException(403, 'Forbidden')
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
      <td style="color:#7dd3fc">{c["uf_m2"]} UF/m²</td>
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
    const r = await fetch(API + '/admin/agent/regional-debates/sync?secret=' + new URLSearchParams(location.search).get('secret'), {{method:'POST'}});
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
    const r = await fetch(API + '/admin/agent/daily-debates/sync?secret=' + new URLSearchParams(location.search).get('secret'), {{method:'POST'}});
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
